#!/usr/bin/env python3
"""Tiny HTTP server: POST /tts with text body -> MP3 synthesized by Piper (pt-BR)."""
import os
import shlex
import subprocess
import tempfile
from http.server import HTTPServer, BaseHTTPRequestHandler

PIPER_BIN = "/home/rafael/piper/piper/piper"
VOICE = "/home/rafael/piper/voices/pt_BR-faber-medium.onnx"
LD_DIR = "/home/rafael/piper/piper"
PORT = 8080
MAX_CHARS = 1500

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
        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS]
        self.log_message("synth: %d chars", len(text))

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
