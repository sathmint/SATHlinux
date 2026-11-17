# Sath Linux 🐧

**SATH Linux** — это кастомный дистрибутив Linux на базе **Debian Testing** с рабочим столом **KDE Plasma (Wayland)**, настроенным терминалом и графическим установщиком.

## ✨ Особенности
* **База:** Debian Testing (`amd64`).
* **Графическое окружение:** KDE Plasma 6 на Wayland с включенными плавными анимациями окон (`wobbly windows`, размытие и скольжение).
* **Терминал:** Kitty + `fastfetch` с фирменным ASCII-логотипом S при запуске.
* **Полноценная установка:** Встроенный графический установщик **Calamares** с ярлыком прямо на рабочем столе Live-системы.
* **Поддержка драйверов:** Включены несвободные прошивки (`firmware-linux-nonfree`), звуковой сервер PipeWire и опциональная поддержка видеокарт NVIDIA.

## 🛠️ Как собрать ISO-образ

Сборка тестировалась на системах семейства Debian/Ubuntu.

1. Клонируйте репозиторий:
   ```bash
   git clone https://github.com
   cd sath-linux
   ```
2. При необходимости откройте `build_sath.py` и измените `INCLUDE_NVIDIA = True`, если собираете образ для ПК с видеокартой NVIDIA.
3. Запустите сборку с правами суперпользователя:
   ```bash
   sudo python3 build_sath.py
   ```
4. После завершения в текущей папке появится файл `SATH-Linux-1.0-amd64.iso`.

## 🚀 Тестирование в QEMU

```bash
qemu-img create -f qcow2 sath_disk.qcow2 20G
qemu-system-x86_64 -m 4G -enable-kvm -cpu host -smp 2 -vga virtio -hda sath_disk.qcow2 -cdrom SATH-Linux-1.0-amd64.iso -boot d
```

* **Логин Live-пользователя:** `sath`
* **Пароль:** `123`
