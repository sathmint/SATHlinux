import os
import shutil
import subprocess
from pathlib import Path

# ==========================================
# НАСТРОЙКИ ДИСТРИБУТИВА SATH LINUX
# ==========================================
DISTRO_NAME = "SATH Linux"
DISTRO_ID = "sath"
DISTRO_VERSION = "1.0"
ISO_FILENAME = "SATH-Linux-1.0-amd64.iso"
WORK_DIR = Path("/tmp/sath_distro_build")
USER_NAME = "sath"
USER_PASSWORD = "123"

# Совмещенный ASCII-логотип SH для терминала
ASCII_LOGO = r"""
   ███████╗██╗  ██╗
   ██╔════╝██║  ██║
   ███████╗███████║   S A T H   L I N U X
   ╚════██║██╔══██║   -------------------
   ███████║██║  ██║   N/A | N/A
   ╚══════╝╚═╝  ╚═╝
"""

def run_cmd(cmd, chroot_path=None):
    """Выполняет системную команду на хосте или внутри собираемой ОС."""
    if chroot_path:
        cmd = f"chroot {chroot_path} /bin/bash -c '{cmd}'"
    print(f"[ВЫПОЛНЕНИЕ]: {cmd}")
    subprocess.run(cmd, shell=True, check=True)

def main():
    if os.geteuid() != 0:
        print("ОШИБКА: Запустите скрипт через sudo! Пример: sudo python3 build_sath.py")
        return

    print(f"=== Начинаем сборку {DISTRO_NAME} {DISTRO_VERSION} ===")

    # 1. Установка сборочных утилит на хост-систему
    print("\n[1/6] Установка сборочных утилит...")
    run_cmd("apt-get update && apt-get install -y debootstrap squashfs-tools xorriso grub-pc-bin grub-efi-amd64-bin mtools")

    # 2. Подготовка рабочих директорий
    if WORK_DIR.exists():
        shutil.rmtree(WORK_DIR)
    chroot_dir = WORK_DIR / "chroot"
    iso_dir = WORK_DIR / "iso"
    (iso_dir / "live").mkdir(parents=True)
    (iso_dir / "boot/grub").mkdir(parents=True)

    # 3. Базовая система Debian Sid (свежее ядро для 9800X3D и RTX 5060 Ti)
    print("\n[2/6] Скачивание базовой системы (Debian Sid)...")
    run_cmd(f"debootstrap --arch=amd64 sid {chroot_dir} http://debian.org")

    # Подключаем репозитории contrib и non-free для драйверов NVIDIA и прошивок
    sources_list = (
        "deb http://debian.org sid main contrib non-free non-free-firmware\n"
    )
    (chroot_dir / "etc/apt/sources.list").write_text(sources_list)

    # Монтируем системные директории для работы внутри chroot
    for mount_point in ["dev", "proc", "sys"]:
        run_cmd(f"mount --bind /{mount_point} {chroot_dir}/{mount_point}")

    try:
        # 4. Установка ядра, драйверов NVIDIA Open, KDE Plasma 6 и софта
        print("\n[3/6] Установка ядра, KDE Plasma, драйверов RTX 5060 Ti и программ...")
        packages = (
            "linux-image-amd64 linux-headers-amd64 live-boot systemd-sysv network-manager "
            "kde-plasma-desktop plasma-workspace-wayland sddm "
            "firefox-esr kitty fastfetch calamares firmware-linux-nonfree "
            "nvidia-open-kernel-dkms nvidia-driver pipewire-audio sudo nano curl git"
        )
        run_cmd("apt-get update", chroot_dir)
        run_cmd(f"DEBIAN_FRONTEND=noninteractive apt-get install -y {packages}", chroot_dir)

        # 5. Настройка брендинга SATH Linux, пользователя, анимаций и логотипа SH
        print("\n[4/6] Настройка интерфейса, анимаций и логотипа SH...")
        
        os_release = (
            f'PRETTY_NAME="{DISTRO_NAME} {DISTRO_VERSION}"\n'
            f'NAME="{DISTRO_NAME}"\n'
            f'ID={DISTRO_ID}\n'
            f'ID_LIKE=debian\n'
        )
        (chroot_dir / "etc/os-release").write_text(os_release)
        (chroot_dir / "etc/hostname").write_text(DISTRO_ID)

        # Создание пользователя
        run_cmd(f"useradd -m -G sudo -s /bin/bash {USER_NAME}", chroot_dir)
        run_cmd(f"echo '{USER_NAME}:{USER_PASSWORD}' | chpasswd", chroot_dir)

        # Сохранение логотипа SH и автозапуск Fastfetch при открытии терминала
        user_home = chroot_dir / f"home/{USER_NAME}"
        logo_file = user_home / ".sath_logo.txt"
        logo_file.write_text(ASCII_LOGO.strip("\n"))

        bashrc_addition = (
            f"\n# Приветствие {DISTRO_NAME}\n"
            f"fastfetch --logo ~/.sath_logo.txt --logo-type file --logo-color-1 magenta --logo-color-2 cyan\n"
        )
        with open(user_home / ".bashrc", "a") as f:
            f.write(bashrc_addition)

        # Настройка плавных анимаций окон в KDE Plasma (размытие, плавное скольжение, желейные окна)
        kwin_config = user_home / ".config/kwinrc"
        kwin_config.parent.mkdir(parents=True, exist_ok=True)
        kwin_config.write_text("[Plugins]\nblurEnabled=true\nslideEnabled=true\nwobblywindowsEnabled=true\n")

        # Выдача прав пользователю на его домашнюю папку
        run_cmd(f"chown -R {USER_NAME}:{USER_NAME} /home/{USER_NAME}", chroot_dir)

        # Очистка кэша пакетов
        run_cmd("apt-get clean", chroot_dir)

    finally:
        # Обязательно отмонтируем системные директории
        for mount_point in ["dev", "proc", "sys"]:
            run_cmd(f"umount -lf {chroot_dir}/{mount_point}")

    # 6. Упаковка системы в SquashFS и создание загрузочного ISO
    print("\n[5/6] Сжатие файловой системы...")
    shutil.copy(next((chroot_dir / "boot").glob("vmlinuz-*")), iso_dir / "live/vmlinuz")
    shutil.copy(next((chroot_dir / "boot").glob("initrd.img-*")), iso_dir / "live/initrd")
    run_cmd(f"mksquashfs {chroot_dir} {iso_dir}/live/filesystem.squashfs -comp zstd -Xcompression-level 6")

    print("\n[6/6] Генерация загрузочного ISO-образа SATH Linux...")
    grub_cfg = (
        f'set timeout=5\n'
        f'menuentry "Запустить {DISTRO_NAME} {DISTRO_VERSION} (Live)" {{\n'
        f'    linux /live/vmlinuz boot=live quiet splash nvidia-drm.modeset=1\n'
        f'    initrd /live/initrd\n'
        f'}}\n'
    )
    (iso_dir / "boot/grub/grub.cfg").write_text(grub_cfg)

    output_iso = Path.cwd() / ISO_FILENAME
    run_cmd(f"grub-mkrescue -o {output_iso} {iso_dir}")

    print(f"\n==========================================")
    print(f"ГОТОВО! Ваш дистрибутив собран: {output_iso}")
    print(f"Логин: {USER_NAME} | Пароль: {USER_PASSWORD}")
    print(f"==========================================")

if __name__ == "__main__":
    main()
