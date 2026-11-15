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

WORK_DIR = Path("/var/tmp/sath_distro_build")
DEBIAN_SUITE = "testing"
DEBIAN_MIRROR = "http://debian.org"

LIVE_USER = "sath"
LIVE_PASSWORD = "123"

# Поставь True, если собираешь образ специально для ПК с видеокартой NVIDIA
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

    print(f"=== Начинаем сборку полноценной ОС {DISTRO_NAME} {DISTRO_VERSION} ===")

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

    # 3. Базовая система Debian
    print(f"\n[2/6] Скачивание базовой системы (Debian {DEBIAN_SUITE})...")
    run_cmd(
        f"debootstrap --arch=amd64 {DEBIAN_SUITE} {chroot_dir} {DEBIAN_MIRROR}"
    )

    sources_list = f"deb {DEBIAN_MIRROR} {DEBIAN_SUITE} main contrib non-free non-free-firmware\n"
    (chroot_dir / "etc/apt/sources.list").write_text(sources_list)
    shutil.copy("/etc/resolv.conf", chroot_dir / "etc/resolv.conf")

    policy_rc = chroot_dir / "usr/sbin/policy-rc.d"
    policy_rc.write_text("#!/bin/sh\nexit 101\n")
    policy_rc.chmod(0o755)

    mount_points = ["dev", "dev/pts", "proc", "sys"]
    for mp in mount_points:
        run_cmd(f"mount --bind /{mp} {chroot_dir}/{mp}")

    try:
        # 4. Установка ядра, KDE Plasma, Calamares и утилит проверки железа
        print("\n[3/6] Установка ядра, KDE Plasma, Calamares и программ...")
        packages = [
            "linux-image-amd64",
            "live-boot",
            "live-config",
            "live-config-systemd",
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
            # Установщик на диск и загрузчики
            "calamares",
            "calamares-settings-debian",
            "grub-pc",
            "grub-efi-amd64",
            "os-prober",
            "gparted",
            # Утилиты для сканирования и оптимизации железа
            "pciutils",
            "usbutils",
            "dmidecode",
            "inxi",
            "zram-tools",
            "power-profiles-daemon",
            "mesa-vulkan-drivers",
        ]

        if INCLUDE_NVIDIA:
            packages.extend(["linux-headers-amd64", "nvidia-open-kernel-dkms", "nvidia-driver"])

        packages_str = " ".join(packages)

        run_cmd("apt-get update", chroot_dir)
        run_cmd(
            f"DEBIAN_FRONTEND=noninteractive apt-get install -y {packages_str}",
            chroot_dir,
        )

        # Настройка локалей
        (chroot_dir / "etc/locale.gen").write_text(
            "en_US.UTF-8 UTF-8\nru_RU.UTF-8 UTF-8\n"
        )
        run_cmd("locale-gen", chroot_dir)
        (chroot_dir / "etc/default/locale").write_text("LANG=ru_RU.UTF-8\n")

        # 5. Настройка брендинга, Live-пользователя и Calamares
        print("\n[4/6] Настройка брендинга, установщика и рабочего стола...")
        os_release = (
            f'PRETTY_NAME="{DISTRO_NAME} {DISTRO_VERSION}"\n'
            f'NAME="{DISTRO_NAME}"\n'
            f"ID={DISTRO_ID}\n"
            f"ID_LIKE=debian\n"
            f'VERSION_ID="{DISTRO_VERSION}"\n'
        )
        etc_os_release = chroot_dir / "etc/os-release"
        if etc_os_release.is_symlink():
            etc_os_release.unlink()
        etc_os_release.write_text(os_release)
        (chroot_dir / "usr/lib/os-release").write_text(os_release)
        (chroot_dir / "etc/hostname").write_text(DISTRO_ID + "\n")

        # Чистая конфигурация сети для NetworkManager
        (chroot_dir / "etc/network/interfaces").write_text(
            "auto lo\niface lo inet loopback\n"
        )

        # Создание Live-пользователя
        run_cmd(f"useradd -m -G sudo -s /bin/bash {LIVE_USER}", chroot_dir)
        run_cmd(f"echo '{LIVE_USER}:{LIVE_PASSWORD}' | chpasswd", chroot_dir)

        # Настройка автологина только для Live-режима
        live_conf_dir = chroot_dir / "etc/live/config.conf.d"
        live_conf_dir.mkdir(parents=True, exist_ok=True)
        (live_conf_dir / "sath-live.conf").write_text(
            f'LIVE_USERNAME="{LIVE_USER}"\n'
            f'LIVE_USER_FULLNAME="{DISTRO_NAME} Live User"\n'
            f'LIVE_HOSTNAME="{DISTRO_ID}"\n'
        )

        # Конфигурация SDDM
        sddm_conf_dir = chroot_dir / "etc/sddm.conf.d"
        sddm_conf_dir.mkdir(parents=True, exist_ok=True)
        (sddm_conf_dir / "session.conf").write_text(
            "[General]\nDefaultSession=plasma.desktop\n"
        )

        # Настройка /etc/skel (скопируется каждому новому пользователю при установке)
        skel_dir = chroot_dir / "etc/skel"
        (skel_dir / ".sath_logo.txt").write_text(ASCII_LOGO.strip("\n") + "\n")

        bashrc_addition = (
            f"\n# Приветствие {DISTRO_NAME}\n"
            f"fastfetch --logo ~/.sath_logo.txt --logo-type file --logo-color-1 magenta --logo-color-2 cyan\n"
        )
        with open(skel_dir / ".bashrc", "a") as f:
            f.write(bashrc_addition)

        kwin_skel = skel_dir / ".config/kwinrc"
        kwin_skel.parent.mkdir(parents=True, exist_ok=True)
        kwin_skel.write_text(
            "[Plugins]\nblurEnabled=true\nslideEnabled=true\nwobblywindowsEnabled=true\n"
        )

        # Копируем настройки в домашнюю папку Live-пользователя
        user_home = chroot_dir / f"home/{LIVE_USER}"
        shutil.copy(skel_dir / ".sath_logo.txt", user_home / ".sath_logo.txt")
        with open(user_home / ".bashrc", "a") as f:
            f.write(bashrc_addition)
        kwin_user = user_home / ".config/kwinrc"
        kwin_user.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(kwin_skel, kwin_user)

        # Ярлык "Установить SATH Linux" на рабочем столе Live-пользователя
        desktop_dir = user_home / "Desktop"
        desktop_dir.mkdir(parents=True, exist_ok=True)
        installer_shortcut = desktop_dir / "install-sath.desktop"
        installer_shortcut.write_text(
            f"[Desktop Entry]\n"
            f"Type=Application\n"
            f"Version=1.0\n"
            f"Name=Установить {DISTRO_NAME}\n"
            f"Name[en]=Install {DISTRO_NAME}\n"
            f"Comment=Установка {DISTRO_NAME} на жесткий диск\n"
            f"Exec=pkexec calamares\n"
            f"Icon=calamares\n"
            f"Terminal=false\n"
            f"Categories=System;\n"
        )
        installer_shortcut.chmod(0o755)

        # Разрешаем запуск calamares через pkexec без пароля в Live-режиме
        polkit_dir = chroot_dir / "etc/polkit-1/rules.d"
        polkit_dir.mkdir(parents=True, exist_ok=True)
        (polkit_dir / "49-nopasswd-calamares.rules").write_text(
            'polkit.addRule(function(action, subject) {\n'
            '    if (action.id == "com.github.calamares.calamares.pkexec.run" && subject.isInGroup("sudo")) {\n'
            '        return polkit.Result.YES;\n'
            '    }\n'
            '});\n'
        )

        # Обновляем название дистрибутива в конфиге брендинга Calamares
        calamares_branding = chroot_dir / "etc/calamares/branding/debian/branding.desc"
        if calamares_branding.exists():
            text = calamares_branding.read_text()
            text = text.replace("Debian", DISTRO_NAME)
            calamares_branding.write_text(text)

        # ==========================================
        # СКРИПТ АВТОПРОВЕРКИ ЖЕЛЕЗА (SATH-HWCHECK)
        # ==========================================
        hwcheck_script = chroot_dir / "usr/local/bin/sath-hwcheck"
        hwcheck_script.write_text(
            '#!/bin/bash\n'
            'echo "=== [SATH Linux] Сканирование конфигурации оборудования ==="\n\n'
            '# 1. Проверка процессора (Intel / AMD)\n'
            'CPU_VENDOR=$(grep -m 1 "vendor_id" /proc/cpuinfo | awk \'{print $3}\')\n'
            'echo "[CPU] Производитель: $CPU_VENDOR"\n\n'
            '# 2. Проверка видеокарты\n'
            'GPU_INFO=$(lspci | grep -iE "vga|3d|display")\n'
            'echo "[GPU] Найдено: $GPU_INFO"\n'
            'if echo "$GPU_INFO" | grep -qi "nvidia"; then\n'
            '    echo "[GPU] Обнаружена NVIDIA! Рекомендуется включить nvidia-drm.modeset=1"\n'
            'fi\n\n'
            '# 3. Проверка батареи (Ноутбук или Десктоп)\n'
            'if ls /sys/class/power_supply/BAT* 1> /dev/null 2>&1; then\n'
            '    echo "[POWER] Обнаружена батарея (Ноутбук). Активация профиля энергосбережения..."\n'
            '    systemctl enable --now power-profiles-daemon 2>/dev/null || true\n'
