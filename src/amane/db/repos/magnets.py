"""订阅源磁力链接的持久化与按番号读取."""

from collections.abc import Sequence

from sqlalchemy import func
from sqlmodel import col, select

from ..models import Feed, MagnetLink
from ..repo_types import MagnetLinkInput
from .base import RepositoryMixinBase, acquire_write_lock, chunks


class MagnetsRepoMixin(RepositoryMixinBase):
    async def upsert_magnet_links(self, feed_id: int, magnets: Sequence[MagnetLinkInput]) -> int:
        """按 ``(number, info_hash)`` 与 ``(number, url)`` 去重后写入, 返回新增行数.

        判定与写入在同一写锁内: 两个订阅源并发发现同一 torrent 时只保留一行.
        """
        if not magnets:
            return 0
        numbers = list({magnet["number"] for magnet in magnets})
        async with self._session() as session:
            await acquire_write_lock(session)
            seen_hashes: set[tuple[str, str]] = set()
            seen_urls: set[tuple[str, str]] = set()
            for chunk in chunks(numbers):
                existing = await session.exec(select(MagnetLink).where(col(MagnetLink.number).in_(chunk)))
                for row in existing.all():
                    key = row.number.casefold()
                    if row.info_hash is not None:
                        seen_hashes.add((key, row.info_hash))
                    seen_urls.add((key, row.url))

            added = 0
            for magnet in magnets:
                key = magnet["number"].casefold()
                info_hash = magnet["info_hash"]
                if info_hash is not None and (key, info_hash) in seen_hashes:
                    continue
                if (key, magnet["url"]) in seen_urls:
                    continue
                session.add(
                    MagnetLink(
                        number=magnet["number"],
                        url=magnet["url"],
                        info_hash=info_hash,
                        title=magnet["title"],
                        feed_id=feed_id,
                        published_at=magnet["published_at"],
                    )
                )
                if info_hash is not None:
                    seen_hashes.add((key, info_hash))
                seen_urls.add((key, magnet["url"]))
                added += 1
            await session.commit()
            return added

    async def list_magnets_for_number(self, number: str, limit: int = 20) -> list[tuple[MagnetLink, str | None]]:
        """按番号取磁力链接, 新发布的在前; 第二项是订阅源当前名称, 源已删除时为空."""
        if limit <= 0:
            return []
        async with self._session() as session:
            stmt = (
                select(MagnetLink, Feed.name)
                .outerjoin(Feed, col(MagnetLink.feed_id) == col(Feed.id))
                .where(col(MagnetLink.number) == number)
                .order_by(
                    func.coalesce(col(MagnetLink.published_at), col(MagnetLink.created_at)).desc(),
                    col(MagnetLink.id).desc(),
                )
                .limit(limit)
            )
            return [(magnet, feed_name) for magnet, feed_name in (await session.exec(stmt)).all()]
