"""
sath_extras.py: Sath Lab (полигоны в Podman), переключатель режимов Daily/Hack
в трее и очистка live-пользователя после установки.

Лежит рядом с build_sath.py. Подключается из него (см. build_sath.py).
"""

import shutil
from pathlib import Path

# Добавить к списку packages в build_sath.py
EXTRA_PACKAGES = [
    # Sath Lab
    "podman",
    "uidmap",
    "slirp4netns",
    "fuse-overlayfs",
    "kdialog",
    # режимы Daily / Hack
    "python3-pyqt6",
    "nftables",
]

# ------------------------------------------------------------------ Sath Lab

LAB_SCRIPT = r'''#!/usr/bin/env python3
# Sath Lab: уязвимые полигоны в rootless Podman, порты только на 127.0.0.1
import shutil
import subprocess
import sys

PREFIX = "sath-lab-"

# ключ: (название, образ, порт в контейнере, порт на хосте)
LABS = {
    "dvwa": ("DVWA", "docker.io/vulnerables/web-dvwa", 80, 8081),
    "juice": ("OWASP Juice Shop", "docker.io/bkimminich/juice-shop", 3000, 3000),
}


def sh(*args):
    return subprocess.run(args, capture_output=True, text=True)


def notify(text):
    if shutil.which("notify-send"):
        sh("notify-send", "Sath Lab", text)
    print(text)


def status(key):
    name = PREFIX + key
    r = sh("podman", "ps", "-a", "--filter", "name=^" + name + "$", "--format", "{{.Status}}")
    out = r.stdout.strip()
    if not out:
        return "не создан"
    return "запущен" if out.startswith("Up") else "остановлен"


def start(key):
    title, image, cport, hport = LABS[key]
    name = PREFIX + key
    st = status(key)
    if st == "не создан":
        notify(title + ": скачиваю образ и запускаю (первый раз это долго)...")
        r = sh("podman", "run", "-d", "--name", name,
               "-p", "127.0.0.1:%d:%d" % (hport, cport), image)
    elif st == "остановлен":
        r = sh("podman", "start", name)
    else:
        r = None
    if r is not None and r.returncode != 0:
        notify("Ошибка запуска " + title + ": " + r.stderr.strip()[:200])
        return
    url = "http://127.0.0.1:%d" % hport
    notify(title + " доступен: " + url)
    sh("xdg-open", url)


def stop(key):
    sh("podman", "stop", PREFIX + key)
    notify(LABS[key][0] + " остановлен")


def reset(key):
    sh("podman", "rm", "-f", PREFIX + key)
    notify(LABS[key][0] + " удалён (при следующем запуске будет чистым)")


def kdialog_menu(title, text, items):
    cmd = ["kdialog", "--title", title, "--menu", text]
    for tag, label in items:
        cmd += [tag, label]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def gui():
    while True:
        items = [(k, "%s  [%s]" % (v[0], status(k))) for k, v in LABS.items()]
        items.append(("quit", "Выход"))
        key = kdialog_menu("Sath Lab", "Выбери полигон", items)
        if key in (None, "quit"):
            return
        act = kdialog_menu(LABS[key][0], "Действие", [
            ("start", "Запустить и открыть в браузере"),
            ("stop", "Остановить"),
            ("reset", "Сбросить (удалить контейнер)"),
            ("back", "Назад"),
        ])
        if act == "start":
            start(key)
        elif act == "stop":
            stop(key)
        elif act == "reset":
            reset(key)


def main():
    args = sys.argv[1:]
    if not shutil.which("podman"):
        print("podman не установлен")
        return 1
    if not args:
        if shutil.which("kdialog"):
            gui()
            return 0
        args = ["status"]
    cmd = args[0]
    keys = [args[1]] if len(args) > 1 else list(LABS)
    for k in keys:
        if k not in LABS:
            print("Неизвестный полигон:", k, "| доступны:", ", ".join(LABS))
            return 1
        if cmd == "start":
            start(k)
        elif cmd == "stop":
            stop(k)
        elif cmd == "reset":
            reset(k)
        elif cmd == "status":
            print("%s: %s" % (LABS[k][0], status(k)))
        else:
            print("Использование: sath-lab [start|stop|reset|status] [dvwa|juice]")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

LAB_DESKTOP = """[Desktop Entry]
Type=Application
Name=Sath Lab
Comment=Уязвимые полигоны для тренировки (Podman)
Exec=sath-lab
Icon=applications-development
Terminal=false
Categories=System;Security;
"""

# --------------------------------------------------------- режимы Daily / Hack

MODE_SCRIPT = r'''#!/bin/bash
# sath-mode daily|hack  (от root; из трея вызывается через sudo)
# Состояние хранится в /run, поэтому после перезагрузки система всегда в Daily.
STATE=/run/sath-mode
NM_CONF=/run/NetworkManager/conf.d/90-sath-mode.conf

case "${1:-}" in
  hack)
    mkdir -p /run/NetworkManager/conf.d
    cat > "$NM_CONF" <<'EOF'
[device-mac-randomization]
wifi.scan-rand-mac-address=yes

[connection-mac-randomization]
ethernet.cloned-mac-address=random
wifi.cloned-mac-address=random
EOF
    nft delete table inet sath_hack 2>/dev/null
    nft -f - <<'EOF'
table inet sath_hack {
  chain input {
    type filter hook input priority 0; policy drop;
    ct state established,related accept
    iif lo accept
    udp sport 67 udp dport 68 accept
    udp sport 547 udp dport 546 accept
    ip6 nexthdr icmpv6 accept
  }
}
EOF
    systemctl restart NetworkManager
    echo hack > "$STATE"
    ;;
  daily)
    nft delete table inet sath_hack 2>/dev/null
    rm -f "$NM_CONF"
    systemctl restart NetworkManager
    echo daily > "$STATE"
    ;;
  *)
    echo "Использование: sath-mode daily|hack"
    exit 1
    ;;
esac
exit 0
'''

TRAY_SCRIPT = r'''#!/usr/bin/env python3
# Иконка в трее: переключение режимов Daily / Hack
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

STATE = Path("/run/sath-mode")
# режим: (название, цвет иконки, цветовая схема KDE)
MODES = {
    "daily": ("Daily", "#2ecc71", "BreezeLight"),
    "hack": ("Hack", "#e74c3c", "BreezeDark"),
}


def current():
    try:
        mode = STATE.read_text().strip()
    except OSError:
        mode = "daily"
    return mode if mode in MODES else "daily"


def make_icon(color):
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(4, 4, 56, 56)
    p.setPen(QColor("white"))
    f = p.font()
    f.setPixelSize(36)
    f.setBold(True)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "S")
    p.end()
    return QIcon(pm)


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    tray = QSystemTrayIcon()
    menu = QMenu()
    actions = {}

    def refresh():
        mode = current()
        name, color, _ = MODES[mode]
        tray.setIcon(make_icon(color))
        tray.setToolTip("Sath: режим " + name)
        for key, act in actions.items():
            act.setChecked(key == mode)

    def set_mode(mode):
        if mode == current():
            refresh()
            return
        r = subprocess.run(["sudo", "-n", "/usr/local/sbin/sath-mode", mode])
        if r.returncode == 0:
            subprocess.run(["plasma-apply-colorscheme", MODES[mode][2]])
            tray.showMessage("Sath", "Режим: " + MODES[mode][0])
        else:
            tray.showMessage("Sath", "Не удалось переключить режим")
        refresh()

    for key, (name, _, _) in MODES.items():
        act = QAction(name, menu)
        act.setCheckable(True)
        act.triggered.connect(lambda _checked, k=key: set_mode(k))
        menu.addAction(act)
        actions[key] = act
    menu.addSeparator()
    quit_act = QAction("Выход", menu)
    quit_act.triggered.connect(app.quit)
    menu.addAction(quit_act)

    tray.setContextMenu(menu)
    refresh()
    tray.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
'''

TRAY_DESKTOP = """[Desktop Entry]
Type=Application
Name=Sath Mode
Comment=Переключатель режимов Daily / Hack
Exec=/usr/local/bin/sath-mode-tray
Icon=security-medium
Terminal=false
X-KDE-autostart-after=panel
"""

# Группа sudo может запускать только этот скрипт без пароля
MODE_SUDOERS = "%sudo ALL=(root) NOPASSWD: /usr/local/sbin/sath-mode\n"


def setup_extras(chroot_dir: Path, run_cmd, live_user: str) -> None:
    """Вызывать после создания домашней папки live-пользователя, до chown."""

    def put(rel, text, mode=0o644):
        f = chroot_dir / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
        f.chmod(mode)

    put("usr/local/bin/sath-lab", LAB_SCRIPT, 0o755)
    put("usr/share/applications/sath-lab.desktop", LAB_DESKTOP)

    put("usr/local/sbin/sath-mode", MODE_SCRIPT, 0o755)
    put("usr/local/bin/sath-mode-tray", TRAY_SCRIPT, 0o755)
    put("etc/xdg/autostart/sath-mode-tray.desktop", TRAY_DESKTOP)
    put("etc/sudoers.d/sath-mode", MODE_SUDOERS, 0o440)

    # Оформление (логотип, fastfetch, kwin) в /etc/skel, чтобы оно было
    # у пользователя, которого создаст установщик, а не только у live-пользователя
    home = chroot_dir / f"home/{live_user}"
    skel = chroot_dir / "etc/skel"
    for rel in (".sath_logo.txt", ".bashrc", ".config/kwinrc"):
        src = home / rel
        if src.exists():
            dst = skel / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


# ------------------------------------------- очистка live-пользователя в Calamares

def setup_calamares_cleanup(calamares_dir: Path, live_user: str) -> None:
    """Удаляет live-пользователя, его sudo без пароля и автологин на установленной системе.

    Требует в settings.conf: instances (sath_cleanup), removeuser и
    shellprocess@sath_cleanup в exec-последовательности после users.
    """
    modules = calamares_dir / "modules"
    modules.mkdir(parents=True, exist_ok=True)

    (modules / "removeuser.conf").write_text(f"---\nusername: {live_user}\n")

    (modules / "shellprocess_sath_cleanup.conf").write_text(
        "---\n"
        "dontChroot: false\n"
        "timeout: 30\n"
        "script:\n"
        '    - "rm -f /etc/sddm.conf.d/autologin.conf"\n'
        f'    - "rm -f /etc/sudoers.d/{live_user}"\n'
        f'    - "rm -rf /home/{live_user}"\n'
    )

    # Группы нового пользователя: sudo обязательно
    (modules / "users.conf").write_text(
        "---\n"
        "defaultGroups:\n"
        "    - cdrom\n"
        "    - floppy\n"
        "    - sudo\n"
        "    - audio\n"
        "    - dip\n"
        "    - video\n"
        "    - plugdev\n"
        "    - netdev\n"
        "    - lpadmin\n"
        "sudoersGroup: sudo\n"
        "setRootPassword: false\n"
    )
