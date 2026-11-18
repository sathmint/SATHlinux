#!/usr/bin/env python3
"""
Вставляет подключение sath_snapshots.py в build_sath.py.

Запуск (в папке, где лежат build_sath.py и sath_snapshots.py):
    python3 apply_snapshots_patch.py

Делает резервную копию build_sath.py.bak, ищет строки-якоря и вставляет
нужные строки с правильным отступом. Повторный запуск ничего не дублирует.
"""

import shutil
import sys
from pathlib import Path

TARGET = Path("build_sath.py")

# (якорь, позиция, вставляемая строка)
PATCHES = [
    (
        "from pathlib import Path",
        "after",
        "from sath_snapshots import SNAPSHOT_PACKAGES, setup_snapshots, setup_calamares_btrfs",
    ),
    (
        'run_cmd("apt-get update", chroot_dir)',
        "before",
        "packages.extend(SNAPSHOT_PACKAGES)",
    ),
    (
        '(calamares_dir / "modules/bootloader.conf").write_text(bootloader_conf)',
        "after",
        "setup_calamares_btrfs(calamares_dir)",
    ),
    (
        'run_cmd(f"chown -R {LIVE_USER}:{LIVE_USER} /home/{LIVE_USER}", chroot_dir)',
        "before",
        "setup_snapshots(chroot_dir, run_cmd)",
    ),
]


def main() -> int:
    if not TARGET.exists():
        print(f"Не найден {TARGET}. Запусти скрипт в папке с build_sath.py.")
        return 1

    lines = TARGET.read_text(encoding="utf-8").split("\n")
    text = "\n".join(lines)

    # Сначала проверяем, что все якоря на месте и каждый встречается один раз
    for anchor, _, _ in PATCHES:
        hits = [i for i, l in enumerate(lines) if l.strip() == anchor]
        if len(hits) != 1:
            print(f"Якорь найден {len(hits)} раз(а), нужно ровно 1:\n  {anchor}")
            return 1

    backup = TARGET.with_suffix(".py.bak")
    if not backup.exists():
        shutil.copy(TARGET, backup)

    for anchor, where, new in PATCHES:
        if new in text:
            print(f"Уже есть, пропускаю: {new}")
            continue
        idx = next(i for i, l in enumerate(lines) if l.strip() == anchor)
        indent = lines[idx][: len(lines[idx]) - len(lines[idx].lstrip())]
        pos = idx + 1 if where == "after" else idx
        lines.insert(pos, indent + new)
        print(f"Вставлено ({where}): {new}")

    TARGET.write_text("\n".join(lines), encoding="utf-8")
    print("Готово. Оригинал сохранён как build_sath.py.bak")
    return 0


if __name__ == "__main__":
    sys.exit(main())
