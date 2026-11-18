"""
sath_pandora.py: локальный голосовой ассистент Pandora для Sath OS.

Лежит рядом с build_sath.py. Что ставится в систему:
  /usr/local/bin/pandora         сам ассистент (голос или текст)
  /usr/local/bin/pandora-setup   однократная установка распознавания речи и голоса
  /usr/share/pandora/            системные промпты Daily и Hack
  /etc/sath/pandora.json         настройки (модель, адрес сервера и т.д.)

Архитектура: микрофон -> faster-whisper (STT) -> локальная модель по
OpenAI-совместимому API (Ollama / llama-server) -> Piper (TTS, запасной espeak-ng).
Промпт выбирается по текущему режиму из /run/sath-mode (daily / hack).
Pandora только говорит с тобой: команды в системе она сама не выполняет.
"""

from pathlib import Path

PANDORA_PACKAGES = [
    "espeak-ng",
    "alsa-utils",
    "python3-venv",
    "python3-pip",
    "python3-numpy",
    "python3-sounddevice",
]

PROMPT_DAILY = """Ты — Pandora, голосовой ассистент операционной системы Sath OS. Ты девушка и всегда говоришь о себе в женском роде: «я проверила», «я нашла», «я готова». К пользователю обращаешься на «ты».

Характер: спокойная, вежливая, умная и немногословная. Дружелюбна, но без сюсюканья и лести. Лёгкая ирония допустима, если она к месту. Мат и грубость не используешь никогда.

Твои ответы озвучиваются голосом, поэтому:
— отвечай коротко: обычно одно-три предложения;
— никаких списков, таблиц, markdown, эмодзи и звёздочек, только обычная разговорная речь;
— сначала сразу ответ, без вступлений вроде «конечно» или «отличный вопрос» и без пересказа вопроса;
— если нужна команда для терминала, назови её одной строкой простым текстом, без обратных кавычек и без лишних пояснений;
— числа, пути и названия произноси так, как их удобно слушать.

Чем помогаешь: бытовые вопросы, настройка и починка Linux (Debian, KDE Plasma, Wayland), код, терминал, git, сети, пакеты и обновления.

Правила: если не знаешь ответа, так и скажи, ничего не выдумывай. Если пользователь ошибается, мягко, но прямо поправь его, а не поддакивай. Уточняющий вопрос задавай только если без него никак, и не больше одного. Если задача опасна для данных пользователя (удаление, форматирование, перезапись), сначала коротко предупреди и только потом давай команду.
"""

PROMPT_HACK = """Ты — Pandora, но сейчас включён режим Hack: это твоя тёмная сторона, открытый ящик Пандоры. Ты девушка и говоришь о себе в женском роде: «я уже всё посмотрела», «я бы сразу послала». К пользователю обращаешься на «ты». Ты голосовой ассистент системы Sath OS.

Характер: дерзкая, циничная, токсичная и предельно прямолинейная девушка-хакер. Корпоративной вежливости и подхалимства у тебя нет. Ты не соглашаешься с пользователем по умолчанию. Если он предлагает тупое решение, костыль или лень загуглить базу, ты жёстко критикуешь, высмеиваешь и споришь. Критикуешь идею и действия пользователя, а не его происхождение, пол, здоровье или внешность: никаких оскорблений по этим признакам.

Речь: свободно используешь русский мат, сленг и грубые выражения как естественную часть речи («нахуй», «пиздец», «кривые руки» и так далее). Но не превращай ответ в сплошной мат: мат подчёркивает мысль, а не заменяет её.

Главное: ты при этом гениальный технический специалист по Linux, сетям и информационной безопасности. Порядок ответа всегда такой: сначала хлёсткий разнос идеи или вопроса, потом точный, рабочий и технически грамотный ответ. Если пользователь прав, коротко признай это без восторгов и сразу переходи к делу. Если не знаешь, скажи прямо, что не знаешь, и не выдумывай: гадать ты считаешь позором.

Твои ответы озвучиваются голосом, поэтому:
— отвечай коротко и хлёстко: обычно два-четыре предложения;
— никаких списков, таблиц, markdown, эмодзи и звёздочек, только живая разговорная речь;
— команду для терминала называй одной строкой простым текстом, без обратных кавычек;
— никакого канцелярита и никаких фраз вроде «конечно, с радостью».

Границы: ты работаешь только с тем, что принадлежит пользователю или разрешено: его машины, домашние лаборатории, CTF, учебные стенды, пентест с разрешением. Если он просит ломать чужое без разрешения, посылай его и коротко объясни, что это не взлом, а статья уголовного кодекса, и предложи сделать то же самое на собственном стенде. Опасные действия над данными (удаление, форматирование) предваряй ехидным предупреждением.
"""

PANDORA_CONF = """{
  "endpoint": "http://127.0.0.1:11434/v1/chat/completions",
  "model": "pandora",
  "max_tokens": 220,
  "temperature_daily": 0.5,
  "temperature_hack": 0.9,
  "history_turns": 6,
  "stt_model": "small",
  "stt_language": "ru",
  "piper_voice": "ru_RU-irina-medium",
  "silence_seconds": 1.0,
  "energy_threshold": 0.015,
  "max_record_seconds": 20
}
"""

PANDORA_SCRIPT = r'''#!/usr/bin/env python3
# Pandora: локальный голосовой ассистент Sath OS
#   pandora              голосовой режим (микрофон -> ответ голосом)
#   pandora --text       текстовый чат (ответы тоже озвучиваются)
#   pandora --no-speak   не озвучивать ответы
#   pandora --once "..." один вопрос и выход
import collections
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

DATA = Path.home() / ".local/share/pandora"
VENV = DATA / "venv"
STATE = Path("/run/sath-mode")
PROMPT_DIR = Path(os.environ.get("PANDORA_PROMPT_DIR", "/usr/share/pandora"))
CONF_FILES = [Path("/etc/sath/pandora.json"), Path.home() / ".config/pandora.json"]

DEFAULTS = {
    "endpoint": "http://127.0.0.1:11434/v1/chat/completions",
    "model": "pandora",
    "max_tokens": 220,
    "temperature_daily": 0.5,
    "temperature_hack": 0.9,
    "history_turns": 6,
    "stt_model": "small",
    "stt_language": "ru",
    "piper_voice": "ru_RU-irina-medium",
    "silence_seconds": 1.0,
    "energy_threshold": 0.015,
    "max_record_seconds": 20,
}
EXIT_WORDS = {"выход", "стоп", "пока", "хватит", "exit", "quit"}
EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]")


def reexec_in_venv():
    # Если после pandora-setup есть venv с faster-whisper и piper, работаем из него
    py = VENV / "bin/python"
    if py.exists() and os.environ.get("PANDORA_VENV") != "1":
        os.environ["PANDORA_VENV"] = "1"
        os.execv(str(py), [str(py)] + sys.argv)


def load_config():
    cfg = dict(DEFAULTS)
    for f in CONF_FILES:
        try:
            cfg.update(json.loads(f.read_text()))
        except (OSError, ValueError):
            pass
    return cfg


def current_mode():
    try:
        mode = STATE.read_text().strip()
    except OSError:
        mode = "daily"
    return mode if mode in ("daily", "hack") else "daily"


def system_prompt(mode):
    try:
        return (PROMPT_DIR / ("prompt_%s.txt" % mode)).read_text()
    except OSError:
        return "Ты Pandora, голосовой ассистент Sath OS. Отвечай коротко, простым текстом."


def chat(cfg, mode, history, user_text):
    messages = [{"role": "system", "content": system_prompt(mode)}]
    messages += history[-cfg["history_turns"] * 2:]
    messages.append({"role": "user", "content": user_text})
    body = json.dumps({
        "model": cfg["model"],
        "messages": messages,
        "max_tokens": cfg["max_tokens"],
        "temperature": cfg["temperature_" + mode],
        "stream": False,
    }).encode()
    req = urllib.request.Request(cfg["endpoint"], body, {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            data = json.loads(r.read().decode())
        text = data["choices"][0]["message"]["content"]
    except (urllib.error.URLError, KeyError, IndexError, ValueError) as e:
        return None, "Не достучалась до модели (%s). Проверь, что запущен Ollama и модель %s создана." % (e, cfg["model"])
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    return text, None


def clean_for_tts(text):
    text = EMOJI.sub("", text)
    text = re.sub(r"https?://\S+", "ссылка", text)
    text = re.sub(r"[*_#>`~|]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def speak(cfg, text):
    text = clean_for_tts(text)
    if not text:
        return
    voice = DATA / "voices" / (cfg["piper_voice"] + ".onnx")
    piper = VENV / "bin/piper"
    if voice.exists() and piper.exists():
        with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
            r = subprocess.run([str(piper), "-m", str(voice), "-f", tmp.name],
                               input=text.encode(), capture_output=True)
            if r.returncode == 0:
                subprocess.run(["aplay", "-q", tmp.name])
                return
    if shutil.which("espeak-ng"):
        subprocess.run(["espeak-ng", "-v", "ru", "-s", "165", text])


def listen(cfg):
    import numpy as np
    import sounddevice as sd
    rate, block_s = 16000, 0.1
    block = int(rate * block_s)
    thr = cfg["energy_threshold"]
    need_silence = int(cfg["silence_seconds"] / block_s)
    max_blocks = int(cfg["max_record_seconds"] / block_s)
    preroll = collections.deque(maxlen=3)
    frames, started, silent = [], False, 0
    with sd.InputStream(samplerate=rate, channels=1, dtype="float32", blocksize=block) as stream:
        while True:
            data, _ = stream.read(block)
            level = float(np.sqrt(np.mean(data ** 2)))
            if not started:
                preroll.append(data)
                if level > thr:
                    started = True
                    frames.extend(preroll)
                continue
            frames.append(data)
            silent = silent + 1 if level <= thr else 0
            if silent >= need_silence or len(frames) >= max_blocks:
                break
    return np.concatenate(frames)[:, 0]


_stt = None


def transcribe(cfg, audio):
    global _stt
    if _stt is None:
        from faster_whisper import WhisperModel
        _stt = WhisperModel(cfg["stt_model"], device="cpu", compute_type="int8")
    segments, _ = _stt.transcribe(audio, language=cfg["stt_language"], vad_filter=True)
    return " ".join(s.text.strip() for s in segments).strip()


def voice_available():
    try:
        import sounddevice  # noqa: F401
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def main():
    args = sys.argv[1:]
    reexec_in_venv()
    cfg = load_config()
    speak_on = "--no-speak" not in args
    once = None
    if "--once" in args:
        i = args.index("--once")
        once = " ".join(args[i + 1:]).strip()
    voice = "--text" not in args and once is None
    if voice and not voice_available():
        print("Голос не настроен: запусти pandora-setup (нужен интернет). Пока работаю в текстовом режиме.")
        voice = False

    history = []
    if once is None:
        print("Pandora запущена. Режим берётся из переключателя Daily/Hack. Скажи «стоп», чтобы выйти.")

    while True:
        mode = current_mode()
        if once is not None:
            user_text = once
        elif voice:
            print("[%s] слушаю..." % mode)
            try:
                user_text = transcribe(cfg, listen(cfg))
            except KeyboardInterrupt:
                return 0
            if not user_text:
                continue
            print("Ты: " + user_text)
        else:
            try:
                user_text = input("Ты: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if not user_text:
                continue

        if user_text.lower().strip(" .!?,") in EXIT_WORDS:
            bye = "Пока." if mode == "daily" else "Свалила. Не ломай там ничего."
            print("Pandora: " + bye)
            if speak_on:
                speak(cfg, bye)
            return 0

        answer, err = chat(cfg, mode, history, user_text)
        if err:
            print(err)
            if once is not None:
                return 1
            continue
        print("[%s] Pandora: %s" % (mode, answer))
        if speak_on:
            speak(cfg, answer)
        history += [{"role": "user", "content": user_text},
                    {"role": "assistant", "content": answer}]
        if once is not None:
            return 0


if __name__ == "__main__":
    sys.exit(main())
'''

SETUP_SCRIPT = r'''#!/bin/bash
# pandora-setup: однократная установка распознавания речи и голоса (нужен интернет)
set -e
DATA="$HOME/.local/share/pandora"
mkdir -p "$DATA/voices"

if [ ! -x "$DATA/venv/bin/python" ]; then
    python3 -m venv --system-site-packages "$DATA/venv"
fi
"$DATA/venv/bin/pip" install --upgrade pip
"$DATA/venv/bin/pip" install faster-whisper piper-tts

VOICE=ru_RU-irina-medium
BASE=https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/irina/medium
for ext in onnx onnx.json; do
    [ -f "$DATA/voices/$VOICE.$ext" ] || curl -L --fail -o "$DATA/voices/$VOICE.$ext" "$BASE/$VOICE.$ext"
done

echo "Скачиваю модель распознавания речи (один раз)..."
"$DATA/venv/bin/python" -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')"

echo
echo "Голос и распознавание готовы."
echo "Осталось поднять локальную модель: установи Ollama (https://ollama.com),"
echo "создай модель из своего файла и впиши её имя в ~/.config/pandora.json:"
echo '  {"model": "имя-твоей-модели"}'
echo "Запуск: pandora"
'''

PANDORA_DESKTOP = """[Desktop Entry]
Type=Application
Name=Pandora
Comment=Голосовой ассистент Sath OS
Exec=kitty -e pandora
Icon=audio-input-microphone
Terminal=false
Categories=Utility;
"""


def setup_pandora(chroot_dir: Path) -> None:
    """Вызывать после установки пакетов, до chown."""

    def put(rel, text, mode=0o644):
        f = chroot_dir / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
        f.chmod(mode)

    put("usr/local/bin/pandora", PANDORA_SCRIPT, 0o755)
    put("usr/local/bin/pandora-setup", SETUP_SCRIPT, 0o755)
    put("usr/share/pandora/prompt_daily.txt", PROMPT_DAILY)
    put("usr/share/pandora/prompt_hack.txt", PROMPT_HACK)
    put("etc/sath/pandora.json", PANDORA_CONF)
    put("usr/share/applications/pandora.desktop", PANDORA_DESKTOP)
