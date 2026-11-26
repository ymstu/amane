"""magnet links

Revision ID: 8817a3d16149
Revises: dc04a8ae624e
Create Date: 2026-11-26 19:07:50.094982
"""

from base64 import b32decode
from binascii import Error as BinasciiError
from collections.abc import Sequence
from urllib.parse import parse_qs, urlsplit

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8817a3d16149"
down_revision: str | None = "dc04a8ae624e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_HEX = frozenset("0123456789abcdef")


def _info_hash(url: str) -> str | None:
    """迁移内自包含的 btih 解析: 不依赖会演进的 ``amane.parsing``."""
    try:
        query = urlsplit(url.strip()).query
    except ValueError:
        return None
    for xt in parse_qs(query).get("xt", []):
        if not xt.lower().startswith("urn:btih:"):
            continue
        raw = xt[9:]
        if len(raw) == 40:
            lowered = raw.lower()
            return lowered if all(char in _HEX for char in lowered) else None
        if len(raw) == 32:
            try:
                return b32decode(raw.upper()).hex()
            except BinasciiError, ValueError:
                return None
    return None


def _backfill_magnets() -> None:
    """把存量订阅条目的磁力链接迁入新表; 同一 torrent 的 tracker 变体只保留一行."""
    conn = op.get_bind()
    rows = (
        conn.execute(
            sa.text(
                "SELECT feed_id, number, title, link, published_at, created_at FROM feed_items "
                "WHERE number IS NOT NULL AND trim(number) <> '' AND link LIKE 'magnet:%'"
            )
        )
        .mappings()
        .all()
    )
    seen: set[tuple[str, str]] = set()
    for row in rows:
        url = str(row["link"]).strip()
        key = (str(row["number"]).casefold(), _info_hash(url) or url)
        if key in seen:
            continue
        seen.add(key)
        conn.execute(
            sa.text(
                "INSERT OR IGNORE INTO magnet_links "
                "(number, url, info_hash, title, feed_id, published_at, created_at) "
                "VALUES (:number, :url, :info_hash, :title, :feed_id, :published_at, :created_at)"
            ),
            {
                "number": row["number"],
                "url": url,
                "info_hash": _info_hash(url),
                "title": row["title"],
                "feed_id": row["feed_id"],
                "published_at": row["published_at"],
                "created_at": row["created_at"],
            },
        )


def upgrade() -> None:
    op.create_table(
        "magnet_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("number", sa.String(collation="NOCASE"), nullable=False),
        sa.Column("url", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("info_hash", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("feed_id", sa.Integer(), nullable=True),
        sa.Column("published_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True),
        sa.Column("created_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["feed_id"], ["feeds.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("number", "info_hash", name="uq_magnet_links_number_info_hash"),
        sa.UniqueConstraint("number", "url", name="uq_magnet_links_number_url"),
    )
    op.create_index(op.f("ix_magnet_links_feed_id"), "magnet_links", ["feed_id"], unique=False)
    op.create_index(
        "ix_magnet_links_number_published",
        "magnet_links",
        [sa.literal_column("number"), sa.literal_column("coalesce(published_at, created_at)"), "id"],
        unique=False,
    )
    _backfill_magnets()


def downgrade() -> None:
    op.drop_index("ix_magnet_links_number_published", table_name="magnet_links")
    op.drop_index(op.f("ix_magnet_links_feed_id"), table_name="magnet_links")
    op.drop_table("magnet_links")
