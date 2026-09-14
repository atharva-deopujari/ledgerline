"""Serves `frontend/dist` the way the deployment does, for the browser tests and the capture.

A thread around `http.server`: the build is static, and the one thing it has to get right
beyond that is FastAPI's catch-all — `/review/users/{phone}` is a route, not a file, and must
return the app rather than a 404.
"""

from __future__ import annotations

import functools
import http.server
import socketserver
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DIST = REPO_ROOT / "frontend" / "dist"


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args: object) -> None:  # noqa: D102 - no per-request logging
        pass

    def send_head(self):  # noqa: ANN201 - matches the stdlib signature
        if not Path(self.translate_path(self.path)).exists():
            self.path = "/index.html"
        return super().send_head()


def serve() -> tuple[socketserver.TCPServer, str]:
    """Start the server on a free port; returns it and its base URL."""
    handler = functools.partial(QuietHandler, directory=str(DIST))
    server = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"
