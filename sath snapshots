"""
sath_snapshots.py: откат из GRUB на Btrfs-снапшотах для Sath Linux.

Кладётся рядом с build_sath.py. Подключение (3 вставки) описано в INTEGRATION.md
или в ответе в чате.

Схема:
  * Calamares ставит систему на Btrfs с подтомами @, @home, @log, @cache.
  * При ПЕРВОЙ загрузке установленной системы oneshot-сервис создаёт конфиг
    snapper для / и первый снапшот. В live-сессии он ничего не делает.
  * apt/dpkg перед и после каждой операции делает пару снапшотов pre/post.
  * grub-btrfsd следит за /.snapshots и сам обновляет меню GRUB.
"""

from pathlib import Path

# Добавить к списку packages в build_sath.py
SNAPSHOT_PACKAGES = [
    "btrfs-progs",
    "snapper",
    "grub-btrfs",
    "inotify-tools",
]

# ---------------------------------------------------------------- Calamares

PARTITION_CONF = """---
efiSystemPartition: "/boot/efi"
defaultFileSystemType: "btrfs"
availableFileSystemTypes: ["btrfs", "ext4", "xfs"]
"""

# Ключи btrfsSubvolumes/mountOptions проверь по образцу из пакета:
#   /usr/share/calamares/modules/mount.conf  (нужен Calamares 3.3+)
MOUNT_CONF = """---
extraMounts:
    - device: proc
      fs: proc
      mountPoint: /proc
    - device: sys
      fs: sysfs
      mountPoint: /sys
    - device: /dev
      mountPoint: /dev
      options: [ bind ]
    - device: tmpfs
      fs: tmpfs
      mountPoint: /run
    - device: /run/udev
      mountPoint: /run/udev
      options: [ bind ]

mountOptions:
    - filesystem: default
      options: [ defaults ]
    - filesystem: efi
      options: [ umask=0077 ]
    - filesystem: btrfs
      options: [ defaults, noatime, compress=zstd ]

btrfsSubvolumes:
    - mountPoint: /
      subvolume: /@
    - mountPoint: /home
      subvolume: /@home
    - mountPoint: /var/log
      subvolume: /@log
    - mountPoint: /var/cache
      subvolume: /@cache
"""


def setup_calamares_btrfs(calamares_dir: Path) -> None:
    """Вызывать после записи settings.conf (модули partition и mount там уже есть)."""
    modules = calamares_dir / "modules"
    modules.mkdir(parents=True, exist_ok=True)
    (modules / "partition.conf").write_text(PARTITION_CONF)
    (modules / "mount.conf").write_text(MOUNT_CONF)


# ------------------------------------------------------- первая загрузка

SNAPSHOTS_INIT = r"""#!/bin/bash
# Sath Linux: первичная настройка снапшотов (выполняется один раз)
[ -e /run/live ] && exit 0
[ "$(findmnt -no FSTYPE /)" = "btrfs" ] || exit 0

if [ ! -f /etc/snapper/configs/root ]; then
    snapper -c root create-config / || exit 1
    snapper -c root set-config \
        TIMELINE_CREATE=yes \
        TIMELINE_LIMIT_HOURLY=3 TIMELINE_LIMIT_DAILY=5 \
        TIMELINE_LIMIT_WEEKLY=2 TIMELINE_LIMIT_MONTHLY=0 TIMELINE_LIMIT_YEARLY=0 \
        NUMBER_LIMIT=10 NUMBER_LIMIT_IMPORTANT=5
    snapper -c root create -c number -d "Sath Linux: fresh install"
fi

systemctl enable --now snapper-timeline.timer snapper-cleanup.timer grub-btrfsd.service
update-grub
"""

SNAPSHOTS_SERVICE = """[Unit]
Description=Sath Linux: first-boot Btrfs snapshots setup
ConditionPathExists=!/run/live
ConditionPathExists=!/etc/snapper/configs/root
After=local-fs.target dbus.service
Wants=dbus.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/sath-snapshots-init
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
"""

# grub-btrfsd по умолчанию может смотреть не туда: явно указываем каталог snapper.
GRUB_BTRFSD_OVERRIDE = """[Service]
ExecStart=
ExecStart=/usr/bin/env grub-btrfsd --syslog /.snapshots
"""

# Пара pre/post вокруг каждой операции apt/dpkg
SNAP_HELPER = r"""#!/bin/bash
# sath-snap pre|post: снапшот до/после операции пакетного менеджера
[ -e /run/live ] && exit 0
[ -f /etc/snapper/configs/root ] || exit 0
[ "$(findmnt -no FSTYPE /)" = "btrfs" ] || exit 0
STATE=/run/sath-snap-pre
case "$1" in
    pre)  snapper -c root create -t pre -c number -p -d "apt" > "$STATE" 2>/dev/null ;;
    post) [ -s "$STATE" ] && snapper -c root create -t post -c number \
              --pre-number "$(cat "$STATE")" -d "apt" >/dev/null 2>&1
          rm -f "$STATE" ;;
esac
exit 0
"""

APT_HOOK = """DPkg::Pre-Invoke { "/usr/local/sbin/sath-snap pre || true"; };
DPkg::Post-Invoke { "/usr/local/sbin/sath-snap post || true"; };
"""


def setup_snapshots(chroot_dir: Path, run_cmd) -> None:
    """Вызывать после установки пакетов, до chown/apt-get clean.

    run_cmd: функция run_cmd из build_sath.py.
    """
    sbin = chroot_dir / "usr/local/sbin"
    sbin.mkdir(parents=True, exist_ok=True)
    for name, body in (
        ("sath-snapshots-init", SNAPSHOTS_INIT),
        ("sath-snap", SNAP_HELPER),
    ):
        f = sbin / name
        f.write_text(body)
        f.chmod(0o755)

    unit_dir = chroot_dir / "etc/systemd/system"
    unit_dir.mkdir(parents=True, exist_ok=True)
    (unit_dir / "sath-snapshots-init.service").write_text(SNAPSHOTS_SERVICE)

    drop_in = unit_dir / "grub-btrfsd.service.d"
    drop_in.mkdir(parents=True, exist_ok=True)
    (drop_in / "override.conf").write_text(GRUB_BTRFSD_OVERRIDE)

    (chroot_dir / "etc/apt/apt.conf.d/80sath-snapshot").write_text(APT_HOOK)

    # В chroot запущенного systemd нет, но enable просто создаёт симлинк
    run_cmd("systemctl enable sath-snapshots-init.service", chroot_dir)
