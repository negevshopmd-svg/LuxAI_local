"""The media gateway of the film decoder (0.4.3c audit 4 #2, rebuilt in 0.4.3e for audit 5 #1, #12, #13, #18).

FFmpeg (the decoder) is allowed to talk ONLY to this gateway on 127.0.0.1 (protocol whitelist http,tcp,crypto —
no https/tls of its own). Jarvis makes every real request itself:

- the host is resolved here and EVERY address must be public (no loopback, LAN, link-local, multicast…), and
  the connection goes to that checked address — a second DNS answer can never send it elsewhere;
- HTTPS is verified by Python's ssl (Windows certificate store, server name checked): a self-signed, expired,
  wrong-host or untrusted certificate is refused — for the first address AND every playlist segment and key;
- redirects are followed here (at most 5), each one checked the same way;
- HLS playlists are rewritten so every segment, key, map and variant goes through the gateway too.

Each film gets a session with an unguessable id (the path is the credential). Stopping the session closes its
connections at once, so a decoder waiting on a slow server returns immediately (audit 5 #13). Nothing in the
process environment is changed (audit 5 #12).
"""
from __future__ import annotations

import collections
import http.client
import ipaddress
import os
import re
import secrets
import socket
import ssl
import threading
from urllib.parse import quote, urljoin, urlsplit

HEADER_LIMIT = 32 * 1024
CONNECT_TIMEOUT = 15
IDLE_TIMEOUT = 60
MAX_CONNECTIONS = 24
MAX_REDIRECTS = 5
MAX_PLAYLIST = 8 * 1024 * 1024
MAX_URLS = 20000           # addresses one session may hand out
FORWARDED = ("range", "if-range", "user-agent", "referer", "origin", "accept", "accept-language")
_URI_ATTRIBUTE = re.compile(r'URI="([^"]*)"')
_PLAYLIST_TYPE = re.compile(r"mpegurl", re.I)


def allowed_addresses(host: str, port: int) -> list[str]:
    """The addresses of ``host`` when ALL of them are public; [] otherwise (LUXAI_FILM_ALLOW_LOCAL=1: any)."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        return []
    addresses = []
    for info in infos:
        text = info[4][0]
        try:
            address = ipaddress.ip_address(text.split("%")[0])
        except ValueError:
            return []
        if os.environ.get("LUXAI_FILM_ALLOW_LOCAL") != "1" and (not address.is_global or address.is_multicast):
            return []
        addresses.append(text)
    return addresses


def rewrite_playlist(text: str, base: str, map_url) -> str:
    """Every http(s) address of an HLS playlist (segments, variants, URI="…" of keys, maps, media) → the
    gateway address ``map_url`` returns. Relative addresses are resolved against ``base`` first."""
    def mapped(value: str) -> str:
        absolute = urljoin(base, value.strip())
        return map_url(absolute) if urlsplit(absolute).scheme in ("http", "https") else value

    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append(line)
        elif stripped.startswith("#"):
            lines.append(_URI_ATTRIBUTE.sub(lambda match: f'URI="{mapped(match.group(1))}"', line))
        else:
            lines.append(mapped(stripped))
    return "\n".join(lines) + "\n"


class Refused(Exception):
    """A destination the policy does not allow (or a certificate that does not verify)."""


class Session:
    def __init__(self, gateway: "MediaGateway"):
        self.gateway = gateway
        self.id = secrets.token_hex(16)
        self.closed = False
        self._lock = threading.Lock()
        self._urls: list[str] = []
        self._index: dict[str, int] = {}
        self._sockets: set = set()

    def url_for(self, url: str) -> str:
        """The gateway address standing for ``url`` (its file name is kept: FFmpeg checks extensions)."""
        with self._lock:
            number = self._index.get(url)
            if number is None:
                if len(self._urls) >= MAX_URLS:
                    raise Refused("too many addresses in one session")
                number = len(self._urls)
                self._urls.append(url)
                self._index[url] = number
        name = urlsplit(url).path.rsplit("/", 1)[-1] or "media"
        name = quote(re.sub(r"[^0-9A-Za-z._-]", "_", name)[-80:] or "media")
        return f"{self.gateway.base}/{self.id}/{number}/{name}"

    def target(self, number: int) -> str | None:
        with self._lock:
            return self._urls[number] if 0 <= number < len(self._urls) else None

    def hold(self, sock) -> bool:
        with self._lock:
            if self.closed:
                return False
            self._sockets.add(sock)
            return True

    def release(self, sock) -> None:
        with self._lock:
            self._sockets.discard(sock)

    def close(self) -> None:
        """Every connection of this film ends now; later requests are refused."""
        with self._lock:
            self.closed = True
            sockets, self._sockets = list(self._sockets), set()
        for sock in sockets:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        self.gateway.forget(self)


class MediaGateway:
    def __init__(self):
        self._server = None
        self._gate = threading.BoundedSemaphore(MAX_CONNECTIONS)
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()
        # The last few refusals only, for diagnosis (audit 5 #18): bounded, plus a counter.
        self.refused = collections.deque(maxlen=20)
        self.refused_count = 0
        self.tls = ssl.create_default_context()  # CERT_REQUIRED + host name check, Windows store

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self._server.getsockname()[1]}"

    @property
    def running(self) -> bool:
        return self._server is not None

    def start(self) -> "MediaGateway":
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            server.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        server.bind(("127.0.0.1", 0))
        server.listen(32)
        self._server = server
        threading.Thread(target=self._accept, args=(server,), name="JarvisMediaGateway", daemon=True).start()
        return self

    def stop(self) -> None:
        server, self._server = self._server, None
        for session in list(self._sessions.values()):
            session.close()
        if server is not None:
            try:
                server.close()
            except OSError:
                pass

    def open_session(self) -> Session:
        session = Session(self)
        with self._lock:
            self._sessions[session.id] = session
        return session

    def forget(self, session: Session) -> None:
        with self._lock:
            self._sessions.pop(session.id, None)

    def _note_refused(self, host: str) -> None:
        self.refused.append(host)
        self.refused_count += 1

    # -- serving the decoder --------------------------------------------------------------------------
    def _accept(self, server):
        while self._server is server:
            try:
                client, _ = server.accept()
            except OSError:
                return
            if not self._gate.acquire(blocking=False):
                client.close()  # bounded before a thread exists
                continue
            threading.Thread(target=self._serve, args=(client,), daemon=True).start()

    def _serve(self, client: socket.socket):
        session = None
        upstream = None
        try:
            client.settimeout(CONNECT_TIMEOUT)
            head = b""
            while b"\r\n\r\n" not in head:
                chunk = client.recv(4096)
                if not chunk:
                    return
                head += chunk
                if len(head) > HEADER_LIMIT:
                    return
            lines = head.split(b"\r\n\r\n", 1)[0].decode("latin-1").split("\r\n")
            method, target = (lines[0].split(" ") + ["", ""])[:2]
            parts = target.split("/")
            session = self._sessions.get(parts[1]) if len(parts) >= 3 else None
            real = session.target(int(parts[2])) if session is not None and parts[2].isdigit() else None
            if method not in ("GET", "HEAD") or real is None or not session.hold(client):
                client.sendall(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                return
            headers = {}
            for line in lines[1:]:
                name, _, value = line.partition(":")
                if name.strip().lower() in FORWARDED:
                    headers[name.strip()] = value.strip()
            try:
                upstream, response, final = self._fetch(session, method, real, headers)
            except Refused:
                client.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                return
            except (OSError, http.client.HTTPException, ValueError):
                client.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                return
            self._relay(session, client, method, response, final)
        except (OSError, ValueError, http.client.HTTPException, Refused):
            pass
        finally:
            for sock in (client, upstream):
                if sock is not None:
                    if session is not None:
                        session.release(sock)
                    try:
                        sock.close()
                    except OSError:
                        pass
            self._gate.release()

    def _fetch(self, session: Session, method: str, url: str, headers: dict):
        """Open ``url`` (redirects followed and each checked); (socket, response, final address)."""
        for _hop in range(MAX_REDIRECTS + 1):
            parts = urlsplit(url)
            if parts.scheme not in ("http", "https") or not parts.hostname:
                raise Refused(url)
            port = parts.port or (443 if parts.scheme == "https" else 80)
            sock = self._connect(session, parts.hostname, port)
            try:
                if parts.scheme == "https":
                    raw = sock
                    sock = self.tls.wrap_socket(raw, server_hostname=parts.hostname)  # verified (audit 5 #1)
                    session.release(raw)
                    if not session.hold(sock):
                        raise Refused("stopped")
            except ssl.SSLError as error:
                self._note_refused(parts.hostname)
                sock.close()
                raise Refused(f"certificate: {error}") from error
            path = parts.path or "/"
            if parts.query:
                path += "?" + parts.query
            host = parts.hostname if parts.port is None else f"{parts.hostname}:{parts.port}"
            request = [f"{method} {path} HTTP/1.1", f"Host: {host}", "Connection: close", "Accept-Encoding: identity"]
            request += [f"{name}: {value}" for name, value in headers.items()]
            sock.sendall(("\r\n".join(request) + "\r\n\r\n").encode("latin-1"))
            response = http.client.HTTPResponse(sock, method=method)
            response.begin()
            location = response.getheader("Location")
            if response.status in (301, 302, 303, 307, 308) and location:
                response.close()
                session.release(sock)
                sock.close()
                url = urljoin(url, location)
                continue
            return sock, response, url
        raise Refused("too many redirects")

    def _connect(self, session: Session, host: str, port: int):
        if not 0 < port < 65536:
            raise Refused(host)
        addresses = allowed_addresses(host, port)
        if not addresses:
            self._note_refused(host)
            raise Refused(host)
        last = None
        for address in addresses:  # the CHECKED address is used, never a second lookup
            if session.closed:
                raise Refused("stopped")
            try:
                sock = socket.create_connection((address, port), timeout=CONNECT_TIMEOUT)
            except OSError as error:
                last = error
                continue
            sock.settimeout(IDLE_TIMEOUT)
            if not session.hold(sock):
                sock.close()
                raise Refused("stopped")
            return sock
        raise last or OSError(f"cannot connect to {host}")

    def _relay(self, session: Session, client, method: str, response, final: str):
        client.settimeout(IDLE_TIMEOUT)
        kind = response.getheader("Content-Type", "") or ""
        first = b"" if method == "HEAD" else response.read(7)
        if method != "HEAD" and (_PLAYLIST_TYPE.search(kind) or urlsplit(final).path.lower().endswith(".m3u8")
                                 or first.startswith(b"#EXTM3U")):
            body = first + response.read(MAX_PLAYLIST + 1 - len(first))
            if len(body) > MAX_PLAYLIST:
                raise ValueError("playlist too large")
            text = rewrite_playlist(body.decode("utf-8", "surrogateescape"), final, session.url_for)
            data = text.encode("utf-8", "surrogateescape")
            client.sendall((f"HTTP/1.1 {response.status} {response.reason}\r\n"
                            "Content-Type: application/vnd.apple.mpegurl\r\n"
                            f"Content-Length: {len(data)}\r\nConnection: close\r\n\r\n").encode("latin-1") + data)
            return
        head = [f"HTTP/1.1 {response.status} {response.reason}"]
        for name in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges"):
            value = response.getheader(name)
            if value and not (name == "Content-Length" and response.getheader("Transfer-Encoding")):
                head.append(f"{name}: {value}")
        head.append("Connection: close")
        client.sendall(("\r\n".join(head) + "\r\n\r\n").encode("latin-1") + first)
        while not session.closed:
            data = response.read(65536)
            if not data:
                break
            client.sendall(data)
