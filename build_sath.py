import os
import shutil
import subprocess
from pathlib import Path

# ==========================================
# НАСТРОЙКИ ДИСТРИБУТИВА SATH LINUX
# ==========================================
DISTRO_NAME = "Sath Linux"
DISTRO_ID = "sath"
DISTRO_VERSION = "2.3"
ISO_FILENAME = "SATH-Linux-2.3-amd64.iso"

WORK_DIR = Path("/var/tmp/sath_distro_build")
DEBIAN_SUITE = "sid"
DEBIAN_MIRROR = "http://debian.org"

LIVE_USER = "sath"
LIVE_PASSWORD = "1"

# Поставь True, если собираешь образ специально под видеокарту NVIDIA (RTX 5060 Ti)
INCLUDE_NVIDIA = True

# Чистый логотип S (информацию о системе справа нарисует сам fastfetch)
ASCII_LOGO = r"""
   ▄▄▄▄▄▄▄▄▄▄▄▄▄
  ███████████████
  ████       ████
  ████
  ███████████████
   ▀▀▀▀▀▀▀▀▀▀▀████
             █████
  ████       █████
  ███████████████
   ▀▀▀▀▀▀▀▀▀▀▀▀▀
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
    print("\n[1/6] Установка сборочных утилит на хост...")
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
    print(f"\n[2/6] Скачивание базовой системы ({DEBIAN_SUITE})...")
    run_cmd(
        f"debootstrap --arch=amd64 {DEBIAN_SUITE} {chroot_dir} {DEBIAN_MIRROR}"
    )

    # Подключаем репозитории и пробрасываем DNS с хоста
    sources_list = f"deb {DEBIAN_MIRROR} {DEBIAN_SUITE} main contrib non-free non-free-firmware\n"
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
        # 4. Установка ядра, KDE Plasma 6, драйверов, Steam, Flatpak и Calamares
        print("\n[3/6] Установка ядра, рабочего стола, игр и утилит...")

        # Включаем поддержку 32-битных библиотек (обязательно для Steam)
        run_cmd("dpkg --add-architecture i386", chroot_dir)

        packages = [
            "linux-image-amd64",
            "linux-headers-amd64",
            "live-boot",
            "systemd-sysv",
            "network-manager",
            "grub-efi-amd64",
            "os-prober",
            "efibootmgr",
            "locales",
            "sudo",
            "curl",
            "git",
            "nano",
            "btop",
            "kde-plasma-desktop",
            "plasma-workspace-wayland",
            "sddm",
            "dolphin",
            "spectacle",
            "kate",
            "plasma-discover",
            "flatpak",
            "plasma-discover-backend-flatpak",
            "firmware-linux-nonfree",
            "pipewire-audio",
            "steam-installer",
            "gamemode",
            "mangohud",
            "vulkan-tools",
            "libvulkan1:i386",
            "firefox-esr",
            "kitty",
            "fastfetch",
            "ark",
            "p7zip-full",
            "unrar-free",
            "ffmpeg",
            "gstreamer1.0-libav",
            "fonts-noto-color-emoji",
            "calamares",
        ]

        if INCLUDE_NVIDIA:
            packages.extend([
                "nvidia-open-kernel-dkms",
                "nvidia-driver",
                "nvidia-driver-libs:i386",
            ])

        run_cmd("apt-get update", chroot_dir)
        run_cmd(
            f"DEBIAN_FRONTEND=noninteractive apt-get install -y {' '.join(packages)}",
            chroot_dir,
        )

        # Подключаем главный репозиторий приложений Flathub
        run_cmd(
            "flatpak remote-add --if-not-exists flathub https://flathub.org",
            chroot_dir,
        )

        # Генерация русской и английской локалей
        (chroot_dir / "etc/locale.gen").write_text(
            "en_US.UTF-8 UTF-8\nru_RU.UTF-8 UTF-8\n"
        )
        run_cmd("locale-gen", chroot_dir)

        # 5. Настройка брендинга, пользователя, автологина и анимаций
        print(
            "\n[4/6] Настройка интерфейса, автологина, логотипа S и Calamares..."
        )
        os_release = (
            f'PRETTY_NAME="{DISTRO_NAME} {DISTRO_VERSION}"\n'
            f'NAME="{DISTRO_NAME}"\n'
            f"ID={DISTRO_ID}\n"
            f"ID_LIKE=debian\n"
        )
        (chroot_dir / "etc/os-release").write_text(os_release)
        (chroot_dir / "etc/hostname").write_text(DISTRO_ID)

        # Передаем управление сетью в NetworkManager
        (chroot_dir / "etc/network/interfaces").write_text(
            "auto lo\niface lo inet loopback\n"
        )

        # Создание Live-пользователя
        run_cmd(f"useradd -m -G sudo -s /bin/bash {LIVE_USER}", chroot_dir)
        run_cmd(f"echo '{LIVE_USER}:{LIVE_PASSWORD}' | chpasswd", chroot_dir)

        # Настройка автологина в SDDM (сразу в сессию Wayland)
        sddm_conf_dir = chroot_dir / "etc/sddm.conf.d"
        sddm_conf_dir.mkdir(parents=True, exist_ok=True)
        (sddm_conf_dir / "autologin.conf").write_text(
            f"[Autologin]\nUser={LIVE_USER}\nSession=plasma\n"
        )

        # Сохранение логотипа S и автозапуск Fastfetch (слева S, справа инфо о системе)
        user_home = chroot_dir / f"home/{LIVE_USER}"
        logo_file = user_home / ".sath_logo.txt"
        logo_file.write_text(ASCII_LOGO.strip("\n"))

        bashrc_addition = (
            f"\n# Приветствие {DISTRO_NAME}\n"
            f"fastfetch --logo ~/.sath_logo.txt --logo-type file --logo-color-1 green --logo-color-2 cyan\n"
        )
        with open(user_home / ".bashrc", "a") as f:
            f.write(bashrc_addition)

        # Настройка плавных анимаций окон в KDE Plasma
        kwin_config = user_home / ".config/kwinrc"
        kwin_config.parent.mkdir(parents=True, exist_ok=True)
        kwin_config.write_text(
            "[Plugins]\nblurEnabled=true\nslideEnabled=true\nwobblywindowsEnabled=true\nmagiclampEnabled=true\n"
        )

        # ==========================================
        # НАСТРОЙКА ГРАФИЧЕСКОГО УСТАНОВЩИКА CALAMARES
        # ==========================================
        calamares_dir = chroot_dir / "etc/calamares"
        (calamares_dir / "modules").mkdir(parents=True, exist_ok=True)
        (calamares_dir / "branding/sath").mkdir(parents=True, exist_ok=True)

        settings_conf = """---
modules-search: [ local ]

sequence:
- show:
  - welcome
  - locale
  - keyboard
  - partition
  - users
  - summary
- exec:
  - partition
  - mount
  - unpackfs
  - machineid
  - fstab
  - locale
  - keyboard
  - localecfg
  - users
  - displaymanager
  - networkcfg
  - hwclock
  - initramfs
  - grubcfg
  - bootloader
  - umount
- show:
  - finished

branding: sath
prompt-install: true
dont-chroot: false
"""
        (calamares_dir / "settings.conf").write_text(settings_conf)

        unpackfs_conf = """---
unpack:
    - source: "/run/live/medium/live/filesystem.squashfs"
      sourcefs: "squashfs"
      destination: ""
"""
        (calamares_dir / "modules/unpackfs.conf").write_text(unpackfs_conf)

        bootloader_conf = """---
efiBootLoader: "grub"
kernel: "/vmlinuz"
img: "/initrd.img"
fallback: "/initrd.img"
timeout: "5"
grubInstall: "grub-install"
grubMkconfig: "grub-mkconfig"
grubCfg: "/boot/grub/grub.cfg"
grubProbe: "grub-probe"
efiBootMgr: "efibootmgr"
installEFIFallback: true
"""
        (calamares_dir / "modules/bootloader.conf").write_text(bootloader_conf)

        branding_desc = f"""---
componentName: sath
welcomeStyleCalamares: true
welcomeExpandingLogo: true
windowExpanding: normal
windowSize: 800px,520px
windowPlacement: center

strings:
    productName:         {DISTRO_NAME}
    shortProductName:    SATH
    version:             {DISTRO_VERSION}
    shortVersion:        {DISTRO_VERSION}
    versionedName:       {DISTRO_NAME} {DISTRO_VERSION}
    shortVersionedName:  SATH {DISTRO_VERSION}
    bootloaderEntryName: {DISTRO_NAME}

images:
    productLogo:         "logo.png"
    productIcon:         "logo.png"
    productWelcome:      "welcome.png"

style:
   sidebarBackground:    "#1e1e2e"
   sidebarText:          "#cdd6f4"
   sidebarTextSelect:    "#cba6f7"
"""
        (calamares_dir / "branding/sath/branding.desc").write_text(branding_desc)

        run_cmd(
            "cp /usr/share/pixmaps/debian-logo.png /etc/calamares/branding/sath/logo.png || true",
            chroot_dir,
        )
        run_cmd(
            "cp /usr/share/pixmaps/debian-logo.png /etc/calamares/branding/sath/welcome.png || true",
            chroot_dir,
        )

        # Ярлык установщика на рабочий стол
        desktop_dir = user_home / "Desktop"
        desktop_dir.mkdir(parents=True, exist_ok=True)
        calamares_desktop = f"""[Desktop Entry]
Type=Application
Version=1.0
Name=Установить {DISTRO_NAME}
GenericName=System Installer
Comment=Установить {DISTRO_NAME} на диск
