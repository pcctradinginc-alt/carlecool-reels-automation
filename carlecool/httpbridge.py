"""Local HTTP bridge so FFmpeg never touches the internet itself.

Why: on GitHub runners the bundled static FFmpeg (johnvansickle build) could not read
any https URL (every NASA/Prelinger/Wikimedia frame grab failed with "No frame"),
while Python downloads (Coverr) worked. FFmpeg now reads http://127.0.0.1:<port>/<id>;
this bridge fetches the real URL with Python `requests` (TLS, DNS, redirects, the
Wikimedia User-Agent) and forwards Range requests, so seeking inside multi-GB films
still only transfers the bytes FFmpeg needs.

Safety: only URLs registered by our own code are served (random ids), the bridge
listens on 127.0.0.1 only, and redirect targets must stay on allowed hosts.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import secrets
import threading
from urllib.parse import urlparse

import requests

ALLOWED_SUFFIXES = (".nasa.gov", "archive.org", ".wikimedia.org", "catalog.archives.gov")
_lock = threading.Lock()
_server: ThreadingHTTPServer | None = None
_routes: dict[str, tuple[str, str | None]] = {}
_reported: set[tuple[str, int]] = set()


def _allowed(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(host == s.lstrip(".") or host.endswith(s) for s in ALLOWED_SUFFIXES)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # keep CI logs clean
        pass

    def _proxy(self, head: bool) -> None:
        route = _routes.get(self.path.lstrip("/").split("?")[0])
        if route is None:
            self.send_error(404)
            return
        url, agent = route
        headers = {"User-Agent": agent or "ReelBuilder/1.0 (python-requests)"}
        if self.headers.get("Range"):
            headers["Range"] = self.headers["Range"]
        try:
            upstream = requests.request("HEAD" if head else "GET", url, headers=headers, stream=True,
                                        timeout=(15, 60), allow_redirects=True)
        except requests.RequestException:
            self.send_error(502)
            return
        try:
            if not _allowed(upstream.url):
                self.send_error(403)
                return
            if upstream.status_code >= 400:
                # Surface throttling/blocking (e.g. Wikimedia 429) in the run log, once per host.
                host = urlparse(url).hostname or "?"
                if (host, upstream.status_code) not in _reported:
                    _reported.add((host, upstream.status_code))
                    print(f"Media host {host} answered HTTP {upstream.status_code}")
            self.send_response(upstream.status_code)
            for name in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges", "Last-Modified"):
                if upstream.headers.get(name):
                    self.send_header(name, upstream.headers[name])
            self.end_headers()
            if not head:
                for chunk in upstream.iter_content(256 * 1024):
                    if chunk:
                        self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass  # FFmpeg closed the connection after it had enough bytes (normal when seeking)
        finally:
            upstream.close()

    def do_GET(self):
        self._proxy(False)

    def do_HEAD(self):
        self._proxy(True)


def local_url(url: str, user_agent: str | None = None) -> str:
    """Register `url` and return a 127.0.0.1 URL FFmpeg can read; non-http paths pass through."""
    if not str(url).startswith("http"):
        return str(url)
    if not _allowed(url):
        raise ValueError("Bridge host not allowed")
    global _server
    with _lock:
        if _server is None:
            _server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
            _server.daemon_threads = True
            threading.Thread(target=_server.serve_forever, daemon=True).start()
        key = secrets.token_hex(8)
        _routes[key] = (url, user_agent)
        port = _server.server_address[1]
    return f"http://127.0.0.1:{port}/{key}"
