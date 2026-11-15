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

# Перенесли сборку на диск (/var/tmp), чтобы не переполнить оперативную память (/tmp)
WORK_DIR = Path("/var/tmp/sath_distro_build")
DEBIAN_MIRROR = "http://debian.org"

USER_NAME = "sath"
USER_PASSWORD = "123"

# Поставь True, если собираешь образ специально для ПК с видеокартой NVIDIA.
# Для тестов в виртуальной машине или на Intel/AMD лучше оставить False (сборка пройдет в 2 раза быстрее).
INCLUDE_NVIDIA = False

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
        f"debootstrap --arch=amd64 sid {chroot_dir} {DEBIAN_MIRROR}"
    )

    # Подключаем репозитории и пробрасываем DNS с хоста
    sources_list = f"deb {DEBIAN_MIRROR} sid main contrib non-free non-free-firmware\n"
    (chroot_dir / "etc/apt/sources.list").write_text(sources_list)
    shutil.copy("/etc/resolv.conf", chroot_dir / "etc/resolv.conf")

    # Запрещаем запуск фоновых служб внутри chroot во время установки пакетов
    policy_rc = chroot_dir / "usr/sbin/policy-rc.d"
    policy_rc.write_text("#!/bin/sh\nexit 101\n")
    policy_rc.chmod(0o755)

    # Монтируем системные директории
    mount_points = ["dev", "dev/pts", "proc", "sys"]
    for mp in mount_points:
        run_cmd(f"mount --bind /{mp} {chroot_dir}/{mp}")

    try:
        # 4. Установка ядра, драйверов, KDE Plasma и локализации
        print("\n[3/6] Установка ядра, KDE Plasma, драйверов и программ...")
        packages = [
            "linux-image-amd64",
            "live-boot",
            "systemd-sysv",
            "network-manager",
            "kde-plasma-desktop",
            "plasma-workspace-wayland",
            "sddm",
            "locales",
            "firefox-esr",
            "kitty",
            "fastfetch",
            "firmware-linux-nonfree",
            "pipewire-audio",
            "sudo",
            "nano",
            "curl",
            "git",
        ]

        if INCLUDE_NVIDIA:
            packages.extend(["linux-headers-amd64", "nvidia-open-kernel-dkms", "nvidia-driver"])

        packages_str = " ".join(packages)

        run_cmd("apt-get update", chroot_dir)
        run_cmd(
            f"DEBIAN_FRONTEND=noninteractive apt-get install -y {packages_str}",
            chroot_dir,
        )

        # Настройка русской и английской локалей
        (chroot_dir / "etc/locale.gen").write_text(
            "en_US.UTF-8 UTF-8\nru_RU.UTF-8 UTF-8\n"
        )
        run_cmd("locale-gen", chroot_dir)
        (chroot_dir / "etc/default/locale").write_text("LANG=ru_RU.UTF-8\n")

        # 5. Настройка брендинга, пользователя, автологина и анимаций
        print("\n[4/6] Настройка интерфейса, автологина и логотипа SH...")
        os_release = (
            f'PRETTY_NAME="{DISTRO_NAME} {DISTRO_VERSION}"\n'
            f'NAME="{DISTRO_NAME}"\n'
            f"ID={DISTRO_ID}\n"
            f"ID_LIKE=debian\n"
            f'VERSION_ID="{DISTRO_VERSION}"\n'
        )
        # Удаляем симлинк /etc/os-release, если он есть, и пишем напрямую в /usr/lib/os-release и /etc/os-release
        etc_os_release = chroot_dir / "etc/os-release"
        if etc_os_release.is_symlink():
            etc_os_release.unlink()
        etc_os_release.write_text(os_release)
        (chroot_dir / "usr/lib/os-release").write_text(os_release)

        (chroot_dir / "etc/hostname").write_text(DISTRO_ID + "\n")

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
        logo_file.write_text(ASCII_LOGO.strip("\n") + "\n")

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
    kernel_params = "boot=live quiet splash"
    if INCLUDE_NVIDIA:
        kernel_params += " nvidia-drm.modeset=1 nouveau.modeset=0"

    grub_cfg = (
        f"set timeout=5\n"
        f'menuentry "Запустить {DISTRO_NAME} {DISTRO_VERSION} (Live)" {{\n'
        f"    linux /live/vmlinuz {kernel_params}\n"
        f"    initrd /live/initrd\n"
        f"}}\n"
    )
    (iso_dir / "boot/grub/grub.cfg").write_text(grub_cfg)

    output_iso = Path.cwd() / ISO_FILENAME
    run_cmd(f"grub-mkrescue -o {output_iso} {iso_dir}")

    # Удаляем временные файлы сборки, чтобы освободить место на диске
    shutil.rmtree(WORK_DIR)

    print("\n==========================================")
    print(f"ГОТОВО! Ваш дистрибутив собран: {output_iso}")
    print(f"Логин: {USER_NAME} | Пароль: {USER_PASSWORD}")
    print("==========================================")


if __name__ == "__main__":
    main()
