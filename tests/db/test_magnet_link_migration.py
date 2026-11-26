"""磁力链接表迁移: 建表、索引与存量订阅条目回填."""

from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from tests.helpers import alembic_config

_PREVIOUS = "dc04a8ae624e"
_TARGET = "8817a3d16149"
_HEX = "b0920b07e8457b73274b39a1745455c76dd2b7d5"
_OTHER = "67dcd3b15d122a3768622e11cb3582c6b790fc53"


def test_magnet_link_migration_backfills_and_dedupes(tmp_path: Path) -> None:
    db_path = tmp_path / "migrate.db"
    cfg = alembic_config(db_path)
    command.upgrade(cfg, _PREVIOUS)

    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        feed_id = conn.execute(
            text(
                "INSERT INTO feeds "
                "(name, url, enabled, auto_enqueue, interval_seconds, use_cache, last_enqueued) "
                "VALUES ('bt4g', 'https://example.com/magnet.xml', 1, 1, 3600, '[]', 0)"
            )
        ).lastrowid
        assert feed_id is not None
        for item_key, title, link, number in [
            ("m-1", "ABF-371", f"magnet:?xt=urn:btih:{_HEX}&dn=a", "ABF-371"),
            ("m-2", "ABF-371 again", f"magnet:?xt=urn:btih:{_HEX.upper()}&dn=b", "ABF-371"),
            ("m-3", "DPMI-015", f"magnet:?xt=urn:btih:{_OTHER}&dn=c", "DPMI-015"),
            ("m-4", "WEB-001", "https://example.com/WEB-001", "WEB-001"),
            ("m-5", "no number", f"magnet:?xt=urn:btih:{_HEX}&dn=d", None),
        ]:
            conn.execute(
                text(
                    "INSERT INTO feed_items (feed_id, item_key, title, link, number, created_at) "
                    "VALUES (:feed_id, :item_key, :title, :link, :number, CURRENT_TIMESTAMP)"
                ),
                {"feed_id": feed_id, "item_key": item_key, "title": title, "link": link, "number": number},
            )

    command.upgrade(cfg, _TARGET)

    with engine.connect() as conn:
        assert "magnet_links" in inspect(conn).get_table_names()
        indexes = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE tbl_name='magnet_links'"))}
        assert "ix_magnet_links_feed_id" in indexes
        assert "ix_magnet_links_number_published" in indexes

        rows = conn.execute(text("SELECT number, info_hash, feed_id, title FROM magnet_links ORDER BY number")).all()
        assert rows == [
            ("ABF-371", _HEX, feed_id, "ABF-371"),
            ("DPMI-015", _OTHER, feed_id, "DPMI-015"),
        ]

    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            text("INSERT INTO magnet_links (number, url, created_at) VALUES ('abf-371', :url, CURRENT_TIMESTAMP)"),
            {"url": f"magnet:?xt=urn:btih:{_HEX}&dn=a"},
        )

    command.downgrade(cfg, _PREVIOUS)
    with engine.connect() as conn:
        assert "magnet_links" not in inspect(conn).get_table_names()

    engine.dispose()
