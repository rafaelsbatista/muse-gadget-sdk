#!/usr/bin/env python3
"""Tiny HTTP server: POST /tts with text body -> MP3 synthesized by Piper (pt-BR)."""
import os
import re
import shlex
import subprocess
import tempfile
from http.server import HTTPServer, BaseHTTPRequestHandler

PIPER_BIN = "/home/rafael/piper/piper/piper"
VOICE = "/home/rafael/piper/voices/pt_BR-faber-medium.onnx"
LD_DIR = "/home/rafael/piper/piper"
PORT = 8080
MAX_CHARS = 1500


# --- Markdown / plain-text sanitizer --------------------------------------
# Strips the common markdown that Muse replies include so Piper doesn't
# read "asteriscos" or spell out hashtags.

_RE_CODE_FENCE = re.compile(r"```[\s\S]*?```")
_RE_INLINE_CODE = re.compile(r"`([^`]*)`")
_RE_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_RE_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
_RE_BOLD_ITALIC = re.compile(r"(\*{1,3}|_{1,3})(\S(?:.*?\S)?)\1")
_RE_STRIKETHROUGH = re.compile(r"~~(.+?)~~")
_RE_HEADER = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)
_RE_BLOCKQUOTE = re.compile(r"^\s{0,3}>\s?", re.MULTILINE)
_RE_HR = re.compile(r"^\s{0,3}([-*_])\s*\1\s*\1[\s\S]*?$", re.MULTILINE)
_RE_LIST_BULLET = re.compile(r"^\s{0,3}[-*+]\s+", re.MULTILINE)
_RE_LIST_NUMBER = re.compile(r"^\s{0,3}\d+[.)]\s+", re.MULTILINE)
# Emoji — Piper reads these poorly in pt-BR, so strip them.
_RE_EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF"
    "\U00002600-\U000027BF\U0001F900-\U0001F9FF]+",
    flags=re.UNICODE,
)
_RE_WS = re.compile(r"[ \t]+")
_RE_BLANKLINES = re.compile(r"\n{3,}")


def clean_text(s: str) -> str:
    s = _RE_CODE_FENCE.sub(" ", s)
    s = _RE_IMAGE.sub("", s)
    s = _RE_LINK.sub(r"\1", s)
    s = _RE_INLINE_CODE.sub(r"\1", s)
    s = _RE_STRIKETHROUGH.sub(r"\1", s)
    # Run bold/italic twice to catch nested cases like ***both***.
    s = _RE_BOLD_ITALIC.sub(r"\2", s)
    s = _RE_BOLD_ITALIC.sub(r"\2", s)
    s = _RE_HEADER.sub("", s)
    s = _RE_BLOCKQUOTE.sub("", s)
    s = _RE_HR.sub("", s)
    s = _RE_LIST_BULLET.sub("", s)
    s = _RE_LIST_NUMBER.sub("", s)
    s = _RE_EMOJI.sub("", s)
    s = _RE_WS.sub(" ", s)
    s = _RE_BLANKLINES.sub("\n\n", s)
    return s.strip()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("[%s] %s - %s" % (self.log_date_time_string(), self.address_string(), fmt % args), flush=True)

    def do_GET(self):
        # Health probe
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok\n")
            return
        self.send_error(404)

    def do_POST(self):
        if self.path != "/tts":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0 or length > 32 * 1024:
            self.send_error(400, "bad length")
            return
        raw = self.rfile.read(length)
        try:
            text = raw.decode("utf-8", errors="replace").strip()
        except Exception as e:
            self.send_error(400, "decode: %s" % e)
            return
        if not text:
            self.send_error(400, "empty")
            return
        raw_len = len(text)
        text = clean_text(text)
        if not text:
            self.send_error(400, "empty after sanitize")
            return
        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS]
        self.log_message("synth: %d chars (raw %d)", len(text), raw_len)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f_wav:
            wav_path = f_wav.name
        try:
            env = os.environ.copy()
            env["LD_LIBRARY_PATH"] = LD_DIR
            # text -> Piper
            p = subprocess.run(
                [PIPER_BIN, "--model", VOICE, "--output_file", wav_path],
                input=text.encode("utf-8"),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=30,
            )
            if p.returncode != 0 or not os.path.exists(wav_path) or os.path.getsize(wav_path) < 100:
                self.send_error(500, "piper failed: %s" % p.stderr.decode(errors="replace")[:200])
                return
            # wav -> mp3 (mono 22050 32kbps for the gadget)
            mp3 = subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error",
                 "-i", wav_path, "-ac", "1", "-ar", "22050",
                 "-b:a", "32k", "-c:a", "libmp3lame",
                 "-f", "mp3", "pipe:1"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )
            if mp3.returncode != 0:
                self.send_error(500, "ffmpeg failed")
                return
            data = mp3.stdout
            self.log_message("sent %d bytes mp3", len(data))
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
        finally:
            try: os.unlink(wav_path)
            except Exception: pass

if __name__ == "__main__":
    print("piper tts server listening on 0.0.0.0:%d" % PORT, flush=True)
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
