# Piper TTS proxy for the muse-gadget

A tiny HTTP server that turns the Raspberry Pi (or any Linux box on the gadget's
LAN) into an on-device TTS backend. The gadget POSTs the reply text to it and
plays the returned MP3 through the normal `start_tts` audio path.

Why Pi + Piper instead of cloud TTS?

- **Free**: no API key, no per-character cost.
- **Private**: reply text never leaves your LAN.
- **Fast**: ~1 s latency on a Pi 5 for short replies (0.14x real-time factor on `pt_BR/faber/medium`).
- **Offline-capable**: still works when the Pi is on but the Internet is down.

## Install on a Raspberry Pi (aarch64)

```bash
# 1. Piper binary + pt-BR voice
mkdir -p ~/piper && cd ~/piper
curl -fsSL -o piper.tar.gz \
  https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_aarch64.tar.gz
tar xzf piper.tar.gz && rm piper.tar.gz

mkdir -p voices && cd voices
BASE=https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/faber/medium
curl -fsSL -O "$BASE/pt_BR-faber-medium.onnx"
curl -fsSL -O "$BASE/pt_BR-faber-medium.onnx.json"

# 2. Copy the server script into the same directory
cp /path/to/this/repo/linux/tts/piper_server.py ~/piper/

# 3. Install the systemd unit (adjust paths/user in the unit file first)
sudo cp /path/to/this/repo/linux/tts/piper-tts.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now piper-tts.service
sudo systemctl status piper-tts --no-pager
```

Health check:

```bash
curl http://127.0.0.1:8080/health            # -> ok
curl -X POST --data 'Testando a voz do Piper.' \
     http://127.0.0.1:8080/tts -o /tmp/t.mp3
file /tmp/t.mp3                               # MPEG ADTS, layer III, mono
```

## Wire the gadget to the server

Set `CONFIG_PIPER_TTS_URL` in a **local, uncommitted** sdkconfig fragment:

```ini
# ~/muse-local/sdkconfig.local-token  (gitignored)
CONFIG_PIPER_TTS_URL="http://<pi-ip>:8080/tts"
```

Pass that fragment to `idf.py` via `SDKCONFIG_DEFAULTS`:

```bash
idf.py -B build-muse-waveshare-s3-175c -DIDF_TARGET=esp32s3 \
  -DSDKCONFIG=build-muse-waveshare-s3-175c/sdkconfig \
  -DSDKCONFIG_DEFAULTS="sdkconfig.defaults;devices/sdkconfig.muse;devices/sdkconfig.muse-waveshare-s3-175c;$HOME/muse-local/sdkconfig.local-token" \
  build flash
```

Leave `CONFIG_PIPER_TTS_URL` empty (default) to keep the SDK's silent
caption-pacing behaviour. Non-empty => every reply goes through Piper.

## Switch voices

Any pt-BR Piper voice from <https://huggingface.co/rhasspy/piper-voices/tree/main/pt/pt_BR>
works â€” just download the `.onnx` + `.onnx.json` pair, update `VOICE` in
`piper_server.py`, and restart the service.
