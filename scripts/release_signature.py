"""Signed releases (0.4.2u, audit #8): Ed25519 (RFC 8032) in pure Python, standard library only.

Every release carries ``release_manifest.json`` (the SHA-256 of every file) and
``release_manifest.sig`` (an Ed25519 signature of that manifest). The private
key exists only on the maintainer's PC; the public key below is built into the
updater, so a changed or foreign file is refused even if the GitHub repository
itself were compromised.

Used by scripts/fetch_updater.py and Update.py (which keep their own copy of
``verify`` so they also work before this file is installed) and by the release
tool tests/sign_release.py.
"""
from __future__ import annotations

import hashlib
import json

PUBLIC_KEY_HEX = "3e8a92f065399c640b507a1bf5488a91230c9582ed3595f226210c91b62237fb"
MANIFEST = "release_manifest.json"
SIGNATURE = "release_manifest.sig"
_CRLF_SUFFIXES = (".bat", ".cmd")  # GitHub archives turn these to CRLF (.gitattributes)

_P = 2 ** 255 - 19
_Q = 2 ** 252 + 27742317777372353535851937790883648493


def _inv(x: int) -> int:
    return pow(x, _P - 2, _P)


_D = -121665 * _inv(121666) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)


def _add(a, b):
    A = (a[1] - a[0]) * (b[1] - b[0]) % _P
    B = (a[1] + a[0]) * (b[1] + b[0]) % _P
    C = 2 * a[3] * b[3] * _D % _P
    D = 2 * a[2] * b[2] % _P
    E, F, G, H = B - A, D - C, D + C, B + A
    return (E * F % _P, G * H % _P, F * G % _P, E * H % _P)


def _mul(s: int, point):
    result = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            result = _add(result, point)
        point = _add(point, point)
        s >>= 1
    return result


def _equal(a, b) -> bool:
    return (a[0] * b[2] - b[0] * a[2]) % _P == 0 and (a[1] * b[2] - b[1] * a[2]) % _P == 0


def _recover_x(y: int, sign: int):
    if y >= _P:
        return None
    x2 = (y * y - 1) * _inv(_D * y * y + 1) % _P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


_GY = 4 * _inv(5) % _P
_GX = _recover_x(_GY, 0)
_G = (_GX, _GY, 1, _GX * _GY % _P)


def _compress(point) -> bytes:
    z = _inv(point[2])
    x, y = point[0] * z % _P, point[1] * z % _P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _decompress(data: bytes):
    if len(data) != 32:
        return None
    y = int.from_bytes(data, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % _P)


def _hash_int(data: bytes) -> int:
    return int.from_bytes(hashlib.sha512(data).digest(), "little") % _Q


def _expand(secret: bytes):
    digest = hashlib.sha512(secret).digest()
    a = int.from_bytes(digest[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, digest[32:]


def public_key(secret: bytes) -> bytes:
    a, _prefix = _expand(secret)
    return _compress(_mul(a, _G))


def sign(secret: bytes, message: bytes) -> bytes:
    a, prefix = _expand(secret)
    public = _compress(_mul(a, _G))
    r = _hash_int(prefix + message)
    encoded_r = _compress(_mul(r, _G))
    s = (r + _hash_int(encoded_r + public + message) * a) % _Q
    return encoded_r + s.to_bytes(32, "little")


def verify(public: bytes, message: bytes, signature: bytes) -> bool:
    if len(public) != 32 or len(signature) != 64:
        return False
    point_a = _decompress(public)
    point_r = _decompress(signature[:32])
    if point_a is None or point_r is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _Q:
        return False
    h = _hash_int(signature[:32] + public + message)
    return _equal(_mul(s, _G), _add(point_r, _mul(h, point_a)))


def file_digest(name: str, data: bytes) -> str:
    """SHA-256 as GitHub's archive has the file; batch files are compared with LF line ends."""
    if name.lower().endswith(_CRLF_SUFFIXES):
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def check_manifest(manifest: bytes, signature_hex: str, public_hex: str = PUBLIC_KEY_HEX) -> dict:
    """The parsed manifest when its signature is valid; ValueError otherwise."""
    try:
        signature = bytes.fromhex(signature_hex.strip())
        public = bytes.fromhex(public_hex)
    except ValueError:
        raise ValueError("release signature is not valid hex") from None
    if not verify(public, manifest, signature):
        raise ValueError("the release signature does not match the LuxAI release key")
    data = json.loads(manifest.decode("utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        raise ValueError("the release manifest has an unexpected shape")
    return data
