"""A checking proxy for the film decoder (0.4.3c, audit 4 #2).

FFmpeg follows redirects and opens every playlist segment and key by itself, so checking only the first
media address left the indirect ones open. Every connection the decoder makes now goes through this proxy
on 127.0.0.1: the host is resolved HERE, every resolved address must be public (no loopback, LAN,
link-local, multicast…), and the proxy connects to that checked address itself — a second DNS answer can
never send the decoder elsewhere. HTTPS is tunnelled with CONNECT (the TLS check stays end to end), plain
HTTP is forwarded. A random password (Proxy-Authorization) means only Jarvis's own decoder can use it.
"""
from __future__ import annotations

import base64
import ipaddress
import os
import secrets
import socket
import threading
from urllib.parse import urlsplit

HEADER_LIMIT = 32 * 1024
CONNECT_TIMEOUT = 15
IDLE_TIMEOUT = 60
MAX_CONNECTIONS = 24


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


class MediaProxy:
    def __init__(self):
        self.user = "jarvis"
        self.password = secrets.token_hex(16)
        self._server = None
        self._gate = threading.BoundedSemaphore(MAX_CONNECTIONS)
        self.refused: list[str] = []  # hosts refused (for diagnosis and tests)

    @property
    def url(self) -> str:
        port = self._server.getsockname()[1]
        return f"http://{self.user}:{self.password}@127.0.0.1:{port}"

    def start(self) -> "MediaProxy":
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            server.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        server.bind(("127.0.0.1", 0))
        server.listen(32)
        self._server = server
        threading.Thread(target=self._accept, name="JarvisMediaProxy", daemon=True).start()
        return self

    def stop(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            try:
                server.close()
            except OSError:
                pass

    def _accept(self):
        server = self._server
        while server is not None and self._server is server:
            try:
                client, _ = server.accept()
            except OSError:
                return
            if not self._gate.acquire(blocking=False):
                client.close()  # bounded before a thread exists
                continue
            threading.Thread(target=self._serve, args=(client,), daemon=True).start()

    def _serve(self, client: socket.socket):
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
            head, _, rest = head.partition(b"\r\n\r\n")
            lines = head.decode("latin-1").split("\r\n")
            method, target, version = (lines[0].split(" ") + ["", "", ""])[:3]
            headers = lines[1:]
            if not self._authorized(headers):
                # FFmpeg sends the credentials only after this challenge
                client.sendall(b"HTTP/1.1 407 Proxy Authentication Required\r\n"
                               b"Proxy-Authenticate: Basic realm=\"jarvis\"\r\nContent-Length: 0\r\n\r\n")
                return
            if method == "CONNECT":
                host, _, port = target.rpartition(":")
                host = host.strip("[]")
                upstream = self._connect(host, int(port or 443))
                if upstream is None:
                    client.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
                    return
                client.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            else:
                parts = urlsplit(target)
                if parts.scheme != "http" or not parts.hostname:
                    client.sendall(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
                    return
                upstream = self._connect(parts.hostname, parts.port or 80)
                if upstream is None:
                    client.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
                    return
                path = parts.path or "/"
                if parts.query:
                    path += "?" + parts.query
                kept = [line for line in headers if not line.lower().startswith(("proxy-", "connection:"))]
                request = "\r\n".join([f"{method} {path} {version}", *kept, "Connection: close", "", ""])
                upstream.sendall(request.encode("latin-1") + rest)
                rest = b""
            if rest:
                upstream.sendall(rest)
            self._pipe(client, upstream)
        except (OSError, ValueError):
            pass
        finally:
            for sock in (client, upstream):
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass
            self._gate.release()

    def _authorized(self, headers) -> bool:
        expected = "Basic " + base64.b64encode(f"{self.user}:{self.password}".encode()).decode()
        for line in headers:
            name, _, value = line.partition(":")
            if name.strip().lower() == "proxy-authorization":
                return secrets.compare_digest(value.strip(), expected)
        return False

    def _connect(self, host: str, port: int):
        if not 0 < port < 65536:
            return None
        addresses = allowed_addresses(host, port)
        if not addresses:
            self.refused.append(host)
            return None
        for address in addresses:  # the CHECKED address is used, never a second lookup
            try:
                upstream = socket.create_connection((address, port), timeout=CONNECT_TIMEOUT)
                upstream.settimeout(IDLE_TIMEOUT)
                return upstream
            except OSError:
                continue
        return None

    @staticmethod
    def _pipe(a: socket.socket, b: socket.socket):
        a.settimeout(IDLE_TIMEOUT)

        def copy(source, target):
            try:
                while True:
                    data = source.recv(65536)
                    if not data:
                        break
                    target.sendall(data)
            except OSError:
                pass
            finally:
                try:
                    target.shutdown(socket.SHUT_WR)
                except OSError:
                    pass

        other = threading.Thread(target=copy, args=(b, a), daemon=True)
        other.start()
        copy(a, b)
        other.join(IDLE_TIMEOUT)
