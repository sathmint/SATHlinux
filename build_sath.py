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

ASCII_LOGO = r"""
███████╗██╗  ██╗
██╔════╝██║  ██║
███████╗███████║  S A T H   L I N U X
╚════██║██╔══██║  -------------------
███████║██║  ██║  N/A | N/A
╚══════╝╚═╝  ╚═╝
"""


def run_cmd(cmd, chroot_path=None):
    """Выполняет системную команду на хосте или внутри собираемой ОС."""
    if chroot_path:
        cmd = f'chroot {chroot_path} /bin/bash -c "{cmd}"'
    print(f"[ВЫПОЛНЕНИЕ]: {cmd}")
    subprocess.run(cmd, shell=True, check=True)


def main():
    if os.geteuid() != 0:
        print(
            "ОШИБКА: Запустите скрипт через sudo! Пример: sudo python3 build_sath.py"
        )
        return

    print(f"=== Начинаем сборку {DISTRO_NAME} {DISTRO_VERSION} ===")

    # 1. Установка сборочных утилит на хост-систему
    print("\n[1/6] Установка сборочных утилит...")
    run_cmd(
        "apt-get update && apt-get install -y debootstrap squashfs-tools xorriso grub-pc-bin grub-efi-amd64-bin mtools"
    )

    # 2. Подготовка рабочих директорий
    if WORK_DIR.exists():
        shutil.rmtree(WORK_DIR)
    chroot_dir = WORK_DIR / "chroot"
    iso_dir = WORK_DIR / "iso"
    (iso_dir / "live").mkdir(parents=True)
    (iso_dir / "boot/grub").mkdir(parents=True)

    # 3. Базовая система Debian Sid (исправлен URL зеркала)
    print("\n[2/6] Скачивание базовой системы (Debian Sid)...")
    run_cmd(
        f"debootstrap --arch=amd64 sid {chroot_dir} http://debian.org"
    )

    # Подключаем репозитории и пробрасываем DNS с хоста
    sources_list = "deb http://debian.org sid main contrib non-free non-free-firmware\n"
    (chroot_dir / "etc/apt/sources.list").write_text(sources_list)
    shutil.copy("/etc/resolv.conf", chroot_dir / "etc/resolv.conf")

    # Запрещаем запуск фоновых служб внутри chroot во время установки пакетов
    policy_rc = chroot_dir / "usr/sbin/policy-rc.d"
    policy_rc.write_text("#!/bin/sh\nexit 101\n")
    policy_rc.chmod(0o755)

    # Монтируем системные директории (включая dev/pts)
    mount_points = ["dev", "dev/pts", "proc", "sys"]
    for mp in mount_points:
        run_cmd(f"mount --bind /{mp} {chroot_dir}/{mp}")

    try:
        # 4. Установка ядра, драйверов, KDE Plasma 6 и локализации
        print("\n[3/6] Установка ядра, KDE Plasma, драйверов и программ...")
        packages = (
            "linux-image-amd64 linux-headers-amd64 live-boot systemd-sysv network-manager "
            "kde-plasma-desktop plasma-workspace-wayland sddm locales "
            "firefox-esr kitty fastfetch firmware-linux-nonfree "
            "nvidia-open-kernel-dkms nvidia-driver pipewire-audio sudo nano curl git"
        )
        run_cmd("apt-get update", chroot_dir)
        run_cmd(
            f"DEBIAN_FRONTEND=noninteractive apt-get install -y {packages}",
            chroot_dir,
        )

        # Настройка русской и английской локалей
        (chroot_dir / "etc/locale.gen").write_text(
            "en_US.UTF-8 UTF-8\nru_RU.UTF-8 UTF-8\n"
        )
        run_cmd("locale-gen", chroot_dir)

        # 5. Настройка брендинга, пользователя, автологина и анимаций
        print("\n[4/6] Настройка интерфейса, автологина и логотипа SH...")
        os_release = (
            f'PRETTY_NAME="{DISTRO_NAME} {DISTRO_VERSION}"\n'
            f'NAME="{DISTRO_NAME}"\n'
            f"ID={DISTRO_ID}\n"
            f"ID_LIKE=debian\n"
        )
        (chroot_dir / "etc/os-release").write_text(os_release)
        (chroot_dir / "etc/hostname").write_text(DISTRO_ID)

        # Очистка стандартной конфигурации сети, чтобы работал NetworkManager в трее
        (chroot_dir / "etc/network/interfaces").write_text(
            "auto lo\niface lo inet loopback\n"
        )

        # Создание пользователя
        run_cmd(f"useradd -m -G sudo -s /bin/bash {USER_NAME}", chroot_dir)
        run_cmd(f"echo '{USER_NAME}:{USER_PASSWORD}' | chpasswd", chroot_dir)

        # Настройка автологина в SDDM (сразу на рабочий стол Wayland)
        sddm_conf_dir = chroot_dir / "etc/sddm.conf.d"
        sddm_conf_dir.mkdir(parents=True, exist_ok=True)
        (sddm_conf_dir / "autologin.conf").write_text(
            f"[Autologin]\nUser={USER_NAME}\nSession=plasma\n"
        )

        # Логотип SH и автозапуск Fastfetch
        user_home = chroot_dir / f"home/{USER_NAME}"
        logo_file = user_home / ".sath_logo.txt"
        logo_file.write_text(ASCII_LOGO.strip("\n"))

        bashrc_addition = (
            f"\n# Приветствие {DISTRO_NAME}\n"
            f"fastfetch --logo ~/.sath_logo.txt --logo-type file --logo-color-1 magenta --logo-color-2 cyan\n"
        )
        with open(user_home / ".bashrc", "a") as f:
            f.write(bashrc_addition)

        # Плавные анимации окон в KDE Plasma
        kwin_config = user_home / ".config/kwinrc"
        kwin_config.parent.mkdir(parents=True, exist_ok=True)
        kwin_config.write_text(
            "[Plugins]\nblurEnabled=true\nslideEnabled=true\nwobblywindowsEnabled=true\n"
        )

        run_cmd(f"chown -R {USER_NAME}:{USER_NAME} /home/{USER_NAME}", chroot_dir)
        run_cmd("apt-get clean", chroot_dir)

    finally:
        # Отмонтируем в обратном порядке (сначала dev/pts, потом dev)
        for mp in reversed(mount_points):
            run_cmd(f"umount -lf {chroot_dir}/{mp}")
        if policy_rc.exists():
            policy_rc.unlink()

    # 6. Упаковка системы в SquashFS и создание загрузочного ISO
    print("\n[5/6] Сжатие файловой системы...")
    shutil.copy(
        next((chroot_dir / "boot").glob("vmlinuz-*")), iso_dir / "live/vmlinuz"
    )
    shutil.copy(
        next((chroot_dir / "boot").glob("initrd.img-*")), iso_dir / "live/initrd"
    )
    run_cmd(
        f"mksquashfs {chroot_dir} {iso_dir}/live/filesystem.squashfs -comp zstd -Xcompression-level 6"
    )

    print("\n[6/6] Генерация загрузочного ISO-образа SATH Linux...")
    grub_cfg = (
        f"set timeout=5\n"
        f'menuentry "Запустить {DISTRO_NAME} {DISTRO_VERSION} (Live)" {{\n'
        f"    linux /live/vmlinuz boot=live quiet splash nvidia-drm.modeset=1 nouveau.modeset=0\n"
        f"    initrd /live/initrd\n"
        f"}}\n"
    )
    (iso_dir / "boot/grub/grub.cfg").write_text(grub_cfg)

    output_iso = Path.cwd() / ISO_FILENAME
    run_cmd(f"grub-mkrescue -o {output_iso} {iso_dir}")

    print("\n==========================================")
    print(f"ГОТОВО! Ваш дистрибутив собран: {output_iso}")
    print(f"Логин: {USER_NAME} | Пароль: {USER_PASSWORD}")
    print("==========================================")


if __name__ == "__main__":
    main()
