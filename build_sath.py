import os
import shutil
import subprocess
from pathlib import Path

from sath_snapshots import SNAPSHOT_PACKAGES, setup_snapshots, setup_calamares_btrfs
from sath_extras import EXTRA_PACKAGES, setup_extras, setup_calamares_cleanup

DISTRO_NAME = "Sath Linux"
DISTRO_ID = "sath"
DISTRO_VERSION = "2.3"
ISO_FILENAME = "SATH-Linux-2.3-amd64.iso"

WORK_DIR = Path("/var/tmp/sath_distro_build")
DEBIAN_SUITE = "trixie"
DEBIAN_MIRROR = "http://deb.debian.org/debian"

LIVE_USER = "admin"
LIVE_PASSWORD = "1"

INCLUDE_NVIDIA = True

ASCII_LOGO = r'''
      _,met$$$$$$$$$$gg.
   ,g$$$$$$$$$$$$$$$$$$$P.
 ,g$$P""           """Y$$.".
,$$P'                   `$$$.
$$P'
`$$b._
  `"Y$$$$$$$$$$$$$$$gg._
        `"""""""""Y$$$$$$b.
                        `$$b
                         ,$$P
 ,$$P.                 ,g$$P'
  `Y$$b.__         __,g$$P'
    `"Y$$$$$$$$$$$$$$$P"'
         `"""""""""'
'''


def run_cmd(cmd, chroot_path=None):
    if chroot_path:
        cmd = f'chroot {chroot_path} /bin/bash -c "{cmd}"'
    print(f"[ВЫПОЛНЕНИЕ]: {cmd}")
    subprocess.run(cmd, shell=True, check=True)


def main():
    if os.geteuid() != 0:
        print("ОШИБКА: Запустите скрипт через sudo! Пример: sudo python3 build_sath.py")
        return

    print(f"=== Начинаем сборку {DISTRO_NAME} {DISTRO_VERSION} ===")

    print("\n[1/6] Установка сборочных утилит на хост...")
    run_cmd(
        "apt-get update && apt-get install -y debootstrap squashfs-tools xorriso grub-pc-bin grub-efi-amd64-bin mtools"
    )

    if WORK_DIR.exists():
        shutil.rmtree(WORK_DIR)
    chroot_dir = WORK_DIR / "chroot"
    iso_dir = WORK_DIR / "iso"
    (iso_dir / "live").mkdir(parents=True)
    (iso_dir / "boot/grub").mkdir(parents=True)

    print(f"\n[2/6] Скачивание базовой системы ({DEBIAN_SUITE})...")
    run_cmd(f"debootstrap --arch=amd64 {DEBIAN_SUITE} {chroot_dir} {DEBIAN_MIRROR}")

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
        print("\n[3/6] Установка ядра, рабочего стола, игр и утилит...")
        run_cmd("dpkg --add-architecture i386", chroot_dir)

                packages = [
            "linux-image-amd64",
            "linux-headers-amd64",
            "live-boot",
            "systemd-sysv",
            "network-manager",
            "grub-efi-amd64-bin",
            "grub-pc-bin",
            "os-prober",
            "efibootmgr",
            "locales",
            "sudo",
            "curl",
            "git",
            "nano",
            "btop",
            "kde-plasma-desktop",
            "sddm",
            "dolphin",
            "spectacle",
            "kate",
            "plasma-discover",
            "flatpak",
            "plasma-discover-backend-flatpak",
            "firmware-linux-nonfree",
            "pipewire-audio",
            "vulkan-tools",
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
            packages.extend(["nvidia-driver"])

        packages.extend(SNAPSHOT_PACKAGES)
        packages.extend(EXTRA_PACKAGES)
        run_cmd("apt-get update", chroot_dir)
        run_cmd(
            f"DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends {' '.join(packages)} 2>&1",
            chroot_dir,
        )

        run_cmd(
            "flatpak remote-add --if-not-exists flathub https://flathub.org",
            chroot_dir,
        )

        (chroot_dir / "etc/locale.gen").write_text("en_US.UTF-8 UTF-8\nru_RU.UTF-8 UTF-8\n")
        run_cmd("locale-gen", chroot_dir)


        print("\n[4/6] Настройка интерфейса, автологина, логотипа S и Calamares...")
        os_release = (
            f'PRETTY_NAME="{DISTRO_NAME} {DISTRO_VERSION}"\n'
            f'NAME="{DISTRO_NAME}"\n'
            f"ID={DISTRO_ID}\n"
            f"ID_LIKE=debian\n"
        )
        (chroot_dir / "etc/os-release").write_text(os_release)
        (chroot_dir / "etc/hostname").write_text(DISTRO_ID)

        (chroot_dir / "etc/network/interfaces").write_text("auto lo\niface lo inet loopback\n")

        run_cmd(f"useradd -m -G sudo -s /bin/bash {LIVE_USER}", chroot_dir)
        run_cmd(f"echo '{LIVE_USER}:{LIVE_PASSWORD}' | chpasswd", chroot_dir)

        sudoers_file = chroot_dir / f"etc/sudoers.d/{LIVE_USER}"
        sudoers_file.write_text(f"{LIVE_USER} ALL=(ALL) NOPASSWD: ALL\n")
        sudoers_file.chmod(0o440)

        sddm_conf_dir = chroot_dir / "etc/sddm.conf.d"
        sddm_conf_dir.mkdir(parents=True, exist_ok=True)
        (sddm_conf_dir / "autologin.conf").write_text(
            f"[Autologin]\nUser={LIVE_USER}\nSession=plasma\n"
        )

        user_home = chroot_dir / f"home/{LIVE_USER}"
        logo_file = user_home / ".sath_logo.txt"
        logo_file.write_text(ASCII_LOGO.strip("\n"))

        bashrc_addition = (
            f"\nfastfetch --logo ~/.sath_logo.txt --logo-type file --logo-color-1 green --logo-color-2 cyan\n"
        )
        with open(user_home / ".bashrc", "a") as f:
            f.write(bashrc_addition)

        kwin_config = user_home / ".config/kwinrc"
        kwin_config.parent.mkdir(parents=True, exist_ok=True)
        kwin_config.write_text(
            "[Plugins]\nblurEnabled=true\nslideEnabled=true\nwobblywindowsEnabled=true\nmagiclampEnabled=true\n"
        )

        calamares_dir = chroot_dir / "etc/calamares"
        (calamares_dir / "modules").mkdir(parents=True, exist_ok=True)
        (calamares_dir / "branding/sath").mkdir(parents=True, exist_ok=True)

        settings_conf = """---
modules-search: [ local ]

instances:
- id: sath_cleanup
  module: shellprocess
  config: shellprocess_sath_cleanup.conf

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
  - removeuser
  - shellprocess@sath_cleanup
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
        setup_calamares_btrfs(calamares_dir)
        setup_calamares_cleanup(calamares_dir, LIVE_USER)

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

        desktop_dir = user_home / "Desktop"
        desktop_dir.mkdir(parents=True, exist_ok=True)
        calamares_desktop = f"""[Desktop Entry]
Type=Application
Version=1.0
Name=Установить {DISTRO_NAME}
GenericName=System Installer
Comment=Установить {DISTRO_NAME} на диск
Exec=sudo calamares
Icon=calamares
Terminal=false
Categories=System;
"""
        desktop_file = desktop_dir / "calamares.desktop"
        desktop_file.write_text(calamares_desktop)
        desktop_file.chmod(0o755)

        setup_snapshots(chroot_dir, run_cmd)
        setup_extras(chroot_dir, run_cmd, LIVE_USER)
        run_cmd(f"chown -R {LIVE_USER}:{LIVE_USER} /home/{LIVE_USER}", chroot_dir)
        run_cmd("apt-get clean", chroot_dir)
        if policy_rc.exists():
            policy_rc.unlink()

    finally:
        for mp in reversed(mount_points):
            subprocess.run(f"umount -lf {chroot_dir}/{mp}", shell=True)

    print("\n[5/6] Упаковка корневой файловой системы в SquashFS...")
    run_cmd(
        f"mksquashfs {chroot_dir} {iso_dir}/live/filesystem.squashfs -comp zstd -Xcompression-level 15"
    )

    kernel_path = next((chroot_dir / "boot").glob("vmlinuz-*"))
    initrd_path = next((chroot_dir / "boot").glob("initrd.img-*"))
    shutil.copy(kernel_path, iso_dir / "live/vmlinuz")
    shutil.copy(initrd_path, iso_dir / "live/initrd")

    grub_cfg = f"""set default="0"
set timeout=5

menuentry "Запустить {DISTRO_NAME} {DISTRO_VERSION} (Live)" {{
    linux /live/vmlinuz boot=live components quiet splash
    initrd /live/initrd
}}

menuentry "Запустить {DISTRO_NAME} {DISTRO_VERSION} (Безопасный режим / nomodeset)" {{
    linux /live/vmlinuz boot=live components nomodeset
    initrd /live/initrd
}}
"""
    (iso_dir / "boot/grub/grub.cfg").write_text(grub_cfg)

    print("\n[6/6] Сборка ISO-образа (BIOS + UEFI)...")
    iso_path = WORK_DIR / ISO_FILENAME
    run_cmd(f"grub-mkrescue -o {iso_path} {iso_dir}")

    print(f"\n=== Готово! ISO: {iso_path} ===")


if __name__ == "__main__":
    main()
