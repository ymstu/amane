"""日亚高清海报: 检索结果须经商品页确认, 年龄门与会话无关地当场领取.

线上实录: 番号检索会混入无关商品 (ABW-001 命中油漆刷清洗器), 因此首条不能直接当命中;
商品页可能缺 製造元リファレンス (SSIS-001), 此时退回标题比对. 商品图带缩放后缀, 原图要去掉.
"""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import AsyncMock

import pytest

from amane.crawlers.models import SearchQuery
from amane.crawlers.sites.amazon import AmazonCrawler, original_image_url
from amane.net.errors import FailureKind, FailureReason, RequestError, RequestFailure, SourceError

from .driven import http_client

Route = Callable[[str], str]

_HD = "https://m.media-amazon.com/images/I/81lE-x1pVQL.jpg"
_THUMB = "https://m.media-amazon.com/images/I/81lE-x1pVQL._AC_SY445_SX342_QL70_ML2_.jpg"


def _search_page(*cards: tuple[str, str]) -> str:
    body = "".join(
        f'<div data-asin="{asin}" data-component-type="s-search-result"><h2 aria-label="{title}">{title}</h2></div>'
        for asin, title in cards
    )
    return f"<html><body>{body}</body></html>"


def _product_page(title: str, image: str, reference: str | None = None) -> str:
    ref = f'<span class="a-text-bold">製造元リファレンス</span><span>{reference}</span>' if reference else ""
    return f'<html><body><span id="productTitle">{title}</span><img id="landingImage" src="{image}">{ref}</body></html>'


_BLACK_CURTAIN = '<html><body><div id="black-curtain-warning">18歳以上ですか</div></body></html>'


def _ok(text: str) -> Route:
    def route(_url: str) -> str:
        return text

    return route


def _status(status: int) -> Route:
    def route(url: str) -> str:
        raise RequestError(url, RequestFailure(kind=FailureKind.HTTP_STATUS, status=status, message=f"HTTP {status}"))

    return route


def _fake_web(routes: dict[str, Route]) -> AsyncMock:
    """URL 含某键即走该路由; 路由抛异常即该请求失败, 未声明的 URL 一样失败."""
    web = AsyncMock()

    async def get_text(url: str, **kwargs: object) -> str:
        for pattern, route in routes.items():
            if pattern in url:
                return route(url)
        raise RequestError(url, "no mock matched")

    web.get_text.side_effect = get_text
    return web


def _crawler(routes: dict[str, Route]) -> AmazonCrawler:
    return AmazonCrawler(client=http_client(_fake_web(routes)))


ORIGINAL_URL_CASES: list[tuple[str, str | None]] = [
    (_THUMB, _HD),
    (_HD, _HD),
    # 查询串与锚点不属于图片地址
    (f"{_THUMB}?v=1#frag", _HD),
    # 非 Amazon 图床不猜
    ("https://example.com/images/I/a._AC_SY445_.jpg", None),
    ("", None),
]


@pytest.mark.parametrize(("url", "expected"), ORIGINAL_URL_CASES)
def test_original_image_url_strips_size_suffix(url: str, expected: str | None) -> None:
    assert original_image_url(url) == expected


@pytest.mark.asyncio(loop_scope="function")
async def test_find_poster_confirms_by_reference() -> None:
    crawler = _crawler(
        {
            "/s?k=": _ok(_search_page(("B0D9TKJLZD", "無関係な商品"))),
            "/dp/B0D9TKJLZD": _ok(_product_page("昔から好きだった同級生", _THUMB, "FSDSS-827")),
        }
    )
    assert await crawler.find_poster("FSDSS-827", None) == _HD


@pytest.mark.asyncio(loop_scope="function")
async def test_find_poster_confirms_by_title_when_reference_missing() -> None:
    crawler = _crawler(
        {
            "/s?k=": _ok(_search_page(("B0D9TKJLZD", "タイトル"))),
            "/dp/B0D9TKJLZD": _ok(_product_page("素晴らしい作品 三葉ちはる", _THUMB)),
        }
    )
    assert await crawler.find_poster("SSIS-001", "素晴らしい作品") == _HD


@pytest.mark.asyncio(loop_scope="function")
async def test_find_poster_rejects_unrelated_product() -> None:
    crawler = _crawler(
        {
            "/s?k=": _ok(_search_page(("B000000001", "ペンキ洗浄器"))),
            "/dp/B000000001": _ok(_product_page("ペンキ洗浄器", _THUMB)),
        }
    )
    assert await crawler.find_poster("ABW-001", "全く違うタイトル") is None


@pytest.mark.asyncio(loop_scope="function")
async def test_find_poster_claims_age_gate() -> None:
    crawler = _crawler(
        {
            "/s?k=": _ok(_search_page(("B0D9TKJLZD", "タイトル"))),
            "save-eligibility": _ok(_product_page("対象作品", _THUMB, "FSDSS-827")),
            "/dp/B0D9TKJLZD": _ok(_BLACK_CURTAIN),
        }
    )
    assert await crawler.find_poster("FSDSS-827", None) == _HD


@pytest.mark.asyncio(loop_scope="function")
async def test_find_poster_claims_age_gate_detected_as_block() -> None:
    def age_error(url: str) -> str:
        raise SourceError(FailureReason.AGE_VERIFICATION, detail=url)

    crawler = _crawler(
        {
            "/s?k=": _ok(_search_page(("B0D9TKJLZD", "タイトル"))),
            "save-eligibility": _ok(_product_page("対象作品", _THUMB, "FSDSS-827")),
            "/dp/B0D9TKJLZD": age_error,
        }
    )
    assert await crawler.find_poster("FSDSS-827", None) == _HD


@pytest.mark.asyncio(loop_scope="function")
async def test_find_poster_without_cards_is_miss() -> None:
    crawler = _crawler({"/s?k=": _ok("<html><body>該当なし</body></html>")})
    assert await crawler.find_poster("FSDSS-827", None) is None


@pytest.mark.asyncio(loop_scope="function")
async def test_find_poster_skips_404_product() -> None:
    crawler = _crawler(
        {
            "/s?k=": _ok(_search_page(("B000000001", "无関係"), ("B0D9TKJLZD", "対象"))),
            "/dp/B000000001": _status(404),
            "/dp/B0D9TKJLZD": _ok(_product_page("対象作品", _THUMB, "FSDSS-827")),
        }
    )
    assert await crawler.find_poster("FSDSS-827", None) == _HD


@pytest.mark.asyncio(loop_scope="function")
async def test_find_poster_search_failure_propagates() -> None:
    crawler = _crawler({"/s?k=": _status(503)})
    with pytest.raises(RequestError) as excinfo:
        await crawler.find_poster("FSDSS-827", None)
    assert excinfo.value.http_status == 503


@pytest.mark.asyncio(loop_scope="function")
async def test_find_poster_all_products_fail_raises_last_error() -> None:
    crawler = _crawler(
        {
            "/s?k=": _ok(_search_page(("B000000001", "無関係"))),
            "/dp/B000000001": _status(500),
        }
    )
    with pytest.raises(RequestError) as excinfo:
        await crawler.find_poster("FSDSS-827", None)
    assert excinfo.value.http_status == 500


@pytest.mark.asyncio(loop_scope="function")
async def test_fetch_returns_poster_only() -> None:
    crawler = _crawler(
        {
            "/s?k=": _ok(_search_page(("B0D9TKJLZD", "対象"))),
            "/dp/B0D9TKJLZD": _ok(_product_page("対象作品", _THUMB, "FSDSS-827")),
        }
    )
    result = await crawler.fetch(SearchQuery("FSDSS-827"))
    assert result is not None
    assert result.poster_urls == [_HD]
    assert result.title is None
