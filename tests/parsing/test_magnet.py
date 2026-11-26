"""磁力链接的判定与 info hash 归一."""

from base64 import b32encode

import pytest

from amane.parsing import is_magnet_uri, magnet_info_hash

_HEX = "b0920b07e8457b73274b39a1745455c76dd2b7d5"
_BASE32 = b32encode(bytes.fromhex(_HEX)).decode()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("magnet:?xt=urn:btih:" + _HEX, True),
        ("  MAGNET:?xt=urn:btih:" + _HEX, True),
        ("https://example.com/item", False),
        ("", False),
        ("magnet", False),
    ],
)
def test_is_magnet_uri(value: str, expected: bool):
    assert is_magnet_uri(value) is expected


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        ("magnet:?xt=urn:btih:" + _HEX, _HEX),
        ("magnet:?xt=urn:btih:" + _HEX.upper(), _HEX),
        ("magnet:?dn=name&xt=urn%3Abtih%3A" + _HEX, _HEX),
        ("magnet:?xt=urn:btih:" + _BASE32, _HEX),
        ("magnet:?xt=urn:btih:short", None),
        ("magnet:?xt=urn:btih:" + "z" * 40, None),
        ("magnet:?xt=urn:btmh:1220" + _HEX, None),
        ("magnet:?dn=name", None),
        ("https://example.com/?xt=urn:btih:" + _HEX, None),
    ],
)
def test_magnet_info_hash(uri: str, expected: str | None):
    assert magnet_info_hash(uri) == expected
