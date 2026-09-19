"""Tiny local static server for the mock SAP Fiori console."""

from __future__ import annotations

import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CONSOLE_DIR = Path(__file__).resolve().parent


class SapHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(CONSOLE_DIR), **kwargs)

    def log_message(self, format: str, *args) -> None:
        return


class SapServer(ThreadingHTTPServer):
    allow_reuse_address = True


def serve_in_thread(
    host: str = "127.0.0.1", port: int = 8766
) -> ThreadingHTTPServer:
    """Serve the SAP console on a background thread. Call ``.shutdown()`` to stop."""
    server = SapServer((host, port), SapHandler)
    thread = threading.Thread(
        target=server.serve_forever, daemon=True, name="mock-sap"
    )
    thread.start()
    return server


def main(host: str = "127.0.0.1", port: int = 8766) -> None:
    sap_dir = Path(__file__).resolve().parent

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(sap_dir), **kwargs)

    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
