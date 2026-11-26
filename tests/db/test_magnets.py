"""磁力链接 repository: 去重、番号大小写与排序."""

from datetime import UTC, datetime

import pytest

from amane.db.repo_types import MagnetLinkInput
from amane.db.repository import Repository

_HEX = "b0920b07e8457b73274b39a1745455c76dd2b7d5"


def _magnet(
    number: str,
    url: str,
    *,
    info_hash: str | None = _HEX,
    title: str | None = None,
    published_at: datetime | None = None,
) -> MagnetLinkInput:
    return MagnetLinkInput(
        number=number,
        url=url,
        info_hash=info_hash,
        title=title,
        published_at=published_at,
    )


@pytest.mark.asyncio
async def test_upsert_dedupes_info_hash_and_url(repo: Repository) -> None:
    feed = await repo.create_feed(name="bt4g", url="https://example.com/magnet.xml")
    assert feed.id is not None

    added = await repo.upsert_magnet_links(
        feed.id,
        [
            _magnet("ABF-371", f"magnet:?xt=urn:btih:{_HEX}&dn=a", title="first"),
            _magnet("abf-371", f"magnet:?xt=urn:btih:{_HEX}&dn=b", title="same torrent"),
            _magnet("ABF-371", f"magnet:?xt=urn:btih:{_HEX}&dn=a", title="same url"),
            _magnet("ABF-371", "magnet:?dn=no-hash", info_hash=None, title="no hash"),
        ],
    )

    assert added == 2
    rows = await repo.list_magnets_for_number("ABF-371")
    assert len(rows) == 2
    assert {row[0].title for row in rows} == {"first", "no hash"}


@pytest.mark.asyncio
async def test_upsert_empty_returns_zero(repo: Repository) -> None:
    feed = await repo.create_feed(name="bt4g", url="https://example.com/empty.xml")
    assert feed.id is not None
    assert await repo.upsert_magnet_links(feed.id, []) == 0


@pytest.mark.asyncio
async def test_list_is_case_insensitive_and_newest_first(repo: Repository) -> None:
    feed = await repo.create_feed(name="bt4g", url="https://example.com/order.xml")
    assert feed.id is not None
    await repo.upsert_magnet_links(
        feed.id,
        [
            _magnet(
                "ABF-371", "magnet:?xt=urn:btih:old", info_hash="old", published_at=datetime(2024, 1, 1, tzinfo=UTC)
            ),
            _magnet(
                "ABF-371", "magnet:?xt=urn:btih:new", info_hash="new", published_at=datetime(2025, 1, 1, tzinfo=UTC)
            ),
            _magnet("OTHER-001", "magnet:?xt=urn:btih:other", info_hash="other"),
        ],
    )

    rows = await repo.list_magnets_for_number("abf-371")
    assert [row[0].info_hash for row in rows] == ["new", "old"]
    assert all(row[1] == "bt4g" for row in rows)


@pytest.mark.asyncio
async def test_list_respects_limit(repo: Repository) -> None:
    feed = await repo.create_feed(name="bt4g", url="https://example.com/limit.xml")
    assert feed.id is not None
    await repo.upsert_magnet_links(
        feed.id,
        [_magnet("ABF-371", f"magnet:?xt=urn:btih:{index:040d}", info_hash=f"{index:040d}") for index in range(3)],
    )

    assert len(await repo.list_magnets_for_number("ABF-371", limit=2)) == 2
    assert await repo.list_magnets_for_number("ABF-371", limit=0) == []
