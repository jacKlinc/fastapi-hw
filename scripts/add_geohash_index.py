"""
One-off script: create the geohash prefix index on the `routes` table.

Same reason as add_bbox_index.py -- `Base.metadata.create_all()` only creates
missing tables, not missing indexes on tables that already exist.

`varchar_pattern_ops` is the whole point. The database collation is en_US.utf8,
under which a default btree cannot serve `geohash LIKE 'c3jfx%'` -- Postgres
sequentially scans instead, which is why the radius search was no faster than
brute-force haversine before this index existed.

Usage:
    uv run python scripts/add_geohash_index.py
"""

from sqlalchemy import text

from app.db.session import engine

with engine.begin() as conn:
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_routes_geohash "
            "ON routes (geohash varchar_pattern_ops)"
        )
    )

print("ix_routes_geohash ready.")
