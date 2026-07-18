"""
One-off script: create the (lat, lon) composite index on the `routes` table.

`Base.metadata.create_all()` (used by seed.py/tests) only creates missing
tables, not missing indexes on tables that already exist -- so on a DB that
was seeded before `Routes.__table_args__` gained the index, it has to be
added by hand via this script.

Usage:
    python scripts/add_bbox_index.py
"""

from sqlalchemy import text

from app.db.session import engine

with engine.begin() as conn:
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_routes_lat_lon ON routes (lat, lon)"))

print("ix_routes_lat_lon ready.")
