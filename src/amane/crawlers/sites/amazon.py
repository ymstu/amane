"""Amazon.co.jp 高清海报.

番号在アダルトDVD 目录内检索, 商品页确认后取主图原图. 只提供 ``poster_urls``; 不参与默认类型路由,
由 ``scraping.hd_poster`` 在聚合后单独调用, 因此未命中不会写进站点失败.

检索结果不能直接当命中: 无关商品会排在前面, 必须按商品页的 製造元リファレンス 或刮削标题确认.
商品页命中黑帘时改取 ``save-eligibility``: 它跟随 returnUrl 直接回商品页, 年龄确认因此不需要持久会话.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from typing import override
from urllib.parse import quote, urlparse

from parsel import Selector

from ...enums import SiteName
from ...net.errors import FailureReason, RequestError, SourceError
from ...plugins.models import SourceTrait
from ..base import Crawler, CrawlerProfile
from ..models import FetchOptions, MediaMetadata, SearchQuery
from ..parsing import extract_text, fold_number, is_same_number

_ADULT_DVD_NODE = "896246"
_SEARCH_URL = "https://www.amazon.co.jp/s?k={query}&rh=n%3A{node}"
_PRODUCT_URL = "https://www.amazon.co.jp/dp/{asin}"
_ELIGIBILITY_URL = "https://www.amazon.co.jp/black-curtain/save-eligibility/black-curtain?returnUrl={return_url}"
_MAX_CARDS = 3
_ASIN_RE = re.compile(r'data-asin="([A-Z0-9]{10})"')
_IMAGE_SUFFIX_RE = re.compile(r"\._[A-Za-z0-9_,]+_(?=\.(?:jpe?g|png|webp)$)", re.IGNORECASE)
_TITLE_NOISE_RE = re.compile(r"[^\w\u3040-\u30ff\u3400-\u9fff]", re.UNICODE)


@dataclass(frozen=True)
class _SearchCard:
    asin: str
    title: str


def _title_key(text: str) -> str:
    """标题比对用的折叠: 去空白与标点, 统一全半角; 只用于判断包含关系."""
    return _TITLE_NOISE_RE.sub("", unicodedata.normalize("NFKC", text).casefold())


def _same_title(query_title: str | None, product_title: str) -> bool:
    if not query_title or not product_title:
        return False
    query_key = _title_key(query_title)
    product_key = _title_key(product_title)
    if min(len(query_key), len(product_key)) < 6:
        return False
    return query_key in product_key or product_key in query_key


def _title_has_number(title: str, number: str) -> bool:
    folded = fold_number(number)
    return len(folded) >= 5 and folded in fold_number(title)


def _is_amazon_image(url: str) -> bool:
    host = urlparse(url).hostname or ""
    return host.endswith((".media-amazon.com", ".ssl-images-amazon.com"))


def original_image_url(url: str) -> str | None:
    """Amazon 图片地址 → 原图; 非 Amazon 图床或空值返回 ``None``.

    商品页与搜索结果给的是带缩放后缀的地址, 去掉 ``._..._`` 才是原图.
    """
    if not url:
        return None
    url = url.split("?", 1)[0].split("#", 1)[0]
    if not _is_amazon_image(url):
        return None
    return _IMAGE_SUFFIX_RE.sub("", url)


def _parse_cards(text: str) -> list[_SearchCard]:
    cards: list[_SearchCard] = []
    seen: set[str] = set()
    for match in re.finditer(r'<div[^>]*data-component-type="s-search-result"[^>]*>', text):
        asin_match = _ASIN_RE.search(match.group(0))
        if asin_match is None:
            continue
        asin = asin_match.group(1)
        if asin in seen:
            continue
        chunk = Selector(text=text[match.end() : match.end() + 6000])
        title = extract_text(chunk, "//h2[@aria-label]/@aria-label", "//h2//text()")
        seen.add(asin)
        cards.append(_SearchCard(asin=asin, title=title))
    return cards


def _largest_dynamic_image(raw: str) -> str:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    if not isinstance(data, dict):
        return ""
    best_url = ""
    best_area = -1
    for url, size in data.items():
        if not isinstance(url, str) or not isinstance(size, list) or len(size) < 2:
            continue
        try:
            area = int(size[0]) * int(size[1])
        except TypeError, ValueError:
            continue
        if area > best_area:
            best_area = area
            best_url = url
    return best_url


def _parse_product(text: str) -> tuple[str, str | None, str | None]:
    """商品页 → (标题, 主图地址, 製造元リファレンス)."""
    selector = Selector(text=text)
    title = extract_text(selector, "//span[@id='productTitle']/text()")
    reference = extract_text(
        selector,
        "//span[contains(@class,'a-text-bold') and contains(., '製造元リファレンス')]/following-sibling::span[1]/text()",
        "//tr[th[contains(., '製造元リファレンス')]]/td//text()",
    )
    image = extract_text(selector, "//img[@id='landingImage']/@src", "//img[@id='imgBlkFront']/@src")
    if original_image_url(image) is None:
        image = _largest_dynamic_image(extract_text(selector, "//img[@id='landingImage']/@data-a-dynamic-image"))
    return title, image or None, reference or None


def _confirmed(title: str, reference: str | None, number: str, query_title: str | None) -> bool:
    if reference is not None and is_same_number(reference, number):
        return True
    return _title_has_number(title, number) or _same_title(query_title, title)


class AmazonCrawler(Crawler):
    @classmethod
    def profile(cls) -> CrawlerProfile:
        return CrawlerProfile(
            name=SiteName.AMAZON,
            base_url="https://www.amazon.co.jp",
            urls=["https://m.media-amazon.com"],
            headers={"Accept-Language": "ja-JP,ja;q=0.9,en;q=0.8"},
            traits=frozenset({SourceTrait.NEEDS_PARTIAL}),
        )

    @override
    async def fetch(self, query: SearchQuery, options: FetchOptions | None = None) -> MediaMetadata | None:
        title = query.partial_result.title if query.partial_result else None
        url = await self.find_poster(query.number, title)
        if url is None:
            return None
        return MediaMetadata(number=query.number, poster_urls=[url])

    async def _search(self, query: SearchQuery, options: FetchOptions | None = None) -> str | None:
        # 单一检索流程在 ``fetch`` 内完成; 基类的两段式不适用.
        return None

    async def _scrape(self, url: str, options: FetchOptions | None = None) -> MediaMetadata | None:
        return None

    async def find_poster(self, number: str, title: str | None) -> str | None:
        """按番号查高清海报; 未命中返回 ``None``, 网络失败按来源失败冒泡."""
        query = quote(f'"{number}"')
        search_url = _SEARCH_URL.format(query=query, node=_ADULT_DVD_NODE)
        cards = _parse_cards(await self.client.get_html(search_url, headers=self.headers, cookies=self.cookies))
        if not cards:
            self.logger.info("hd poster miss", number=number)
            return None

        last_error: RequestError | None = None
        for card in cards[:_MAX_CARDS]:
            try:
                product = await self._product_html(card.asin)
            except RequestError as exc:
                if exc.http_status != 404:
                    last_error = exc
                continue
            product_title, image, reference = _parse_product(product)
            if not _confirmed(product_title, reference, number, title):
                continue
            original = original_image_url(image or "")
            if original is not None:
                self.logger.info("hd poster found", number=number, asin=card.asin)
                return original

        if last_error is not None:
            raise last_error
        self.logger.info("hd poster miss", number=number)
        return None

    async def _product_html(self, asin: str) -> str:
        """取商品页; 黑帘 (正文标记或被判为年龄门) 时经 save-eligibility 直接回商品页."""
        age_gated = False
        try:
            text = await self.client.get_html(
                _PRODUCT_URL.format(asin=asin), headers=self.headers, cookies=self.cookies
            )
        except SourceError as exc:
            if exc.reason is not FailureReason.AGE_VERIFICATION:
                raise
            age_gated = True
            text = ""
        if not age_gated and 'id="black-curtain-warning"' not in text:
            return text
        return await self.client.get_html(
            _ELIGIBILITY_URL.format(return_url=quote(f"/dp/{asin}", safe="")),
            headers=self.headers,
            cookies=self.cookies,
        )
