"""磁力链接的纯函数: 判定与 info hash 归一."""

from base64 import b32decode
from binascii import Error as BinasciiError
from urllib.parse import parse_qs, urlsplit

_HEX = frozenset("0123456789abcdef")
_BTIH_PREFIX = "urn:btih:"


def is_magnet_uri(value: str) -> bool:
    """判断字符串是否为磁力链接; 大小写不敏感, 允许首尾空白."""
    return value.strip().lower().startswith("magnet:")


def magnet_info_hash(uri: str) -> str | None:
    """取 ``xt=urn:btih:`` 的 info hash, 统一为小写十六进制.

    40 位十六进制直接转小写; 32 位 base32 解码为十六进制. 同一 torrent 的两种写法因此得到同一值.
    缺失、非 btih 或无法解码时返回 None.
    """
    if not is_magnet_uri(uri):
        return None
    try:
        query = urlsplit(uri.strip()).query
    except ValueError:
        return None
    for xt in parse_qs(query).get("xt", []):
        if not xt.lower().startswith(_BTIH_PREFIX):
            continue
        raw = xt[len(_BTIH_PREFIX) :]
        if len(raw) == 40:
            lowered = raw.lower()
            return lowered if all(char in _HEX for char in lowered) else None
        if len(raw) == 32:
            try:
                return b32decode(raw.upper()).hex()
            except BinasciiError, ValueError:
                return None
    return None
