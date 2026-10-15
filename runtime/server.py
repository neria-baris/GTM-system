"""Serve the immutable GTM Tracker demo using Python's standard library only."""
import argparse
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import signal
import socket
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
ASSETS = {"app/index.html", "app/app.js", "app/styles.css", "assets/logo.svg"}
DATA = {"demo/" + n + ".json" for n in ("manifest", "overview", "opportunities",
        "opportunity_details", "weekly_snapshots", "evidence_summaries", "review_queue", "belief_states")}


def verify_release():
    manifest = json.loads((ROOT / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
    for relative, expected in manifest["sha256"].items():
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            raise ValueError("Missing or invalid release file: " + relative)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("Release integrity check failed: " + relative)
    if not (ASSETS | DATA).issubset(manifest["sha256"]):
        raise ValueError("Incomplete release manifest")


class Server(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def send_head(self):
        path = unquote(urlsplit(self.path).path)
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return None
        if path in {"/", "/app"}:
            self.send_response(302)
            self.send_header("Location", "/app/")
            self.end_headers()
            return None
        if path == "/app/":
            self.path = "/app/index.html"
        elif path.removeprefix("/") not in ASSETS | DATA:
            self.send_error(404, "Not a product resource")
            return None
        return super().send_head()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; "
                         "style-src 'self'; connect-src 'self'; img-src 'self'; font-src 'self'; "
                         "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        super().end_headers()

    def log_message(self, format, *args):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8877)
    args = parser.parse_args()
    verify_release()
    try:
        server = Server(("127.0.0.1", args.port), Handler)
    except OSError as exc:
        if exc.errno not in {48, 98, 10048}:
            raise
        print("Requested port is busy; selecting another local port.", flush=True)
        server = Server(("127.0.0.1", 0), Handler)
    print("\nGTM TRACKER\n", flush=True)
    print(f"Open: http://127.0.0.1:{server.server_port}/app/", flush=True)
    print("Frozen offline demo. Keep this window open. Press Ctrl+C to stop.\n", flush=True)
    def stop(signum, frame):
        raise KeyboardInterrupt
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, stop)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Demo stopped.", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError) as exc:
        raise SystemExit("Unable to start demo: " + str(exc))
