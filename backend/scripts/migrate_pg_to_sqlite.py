"""
One-off migration: PostgreSQL → SQLite.

Reads every table from the existing Postgres database (using the old
connection string) and writes it into backend/data/ebay_hunter.db.

Run once from the project root:
    python backend/scripts/migrate_pg_to_sqlite.py
"""

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

# Source: old PostgreSQL (override with PG_URL if needed)
PG_URL = os.getenv(
    "PG_URL",
    "postgresql://postgres:aghaff0322@localhost:5432/ebay_hunter",
)

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from config import DATABASE_URL  # sqlite absolute path
from db.database import Base
from db import models  # noqa: F401 — register all tables


def main():
    print(f"Source (Postgres): {PG_URL}")
    print(f"Target (SQLite):   {DATABASE_URL}")

    if not DATABASE_URL.startswith("sqlite"):
        raise SystemExit("DATABASE_URL is not SQLite — aborting.")

    # Ensure target directory exists
    db_path = DATABASE_URL.replace("sqlite:///", "")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    src = create_engine(PG_URL)
    dst = create_engine(DATABASE_URL)

    # Create all tables in SQLite
    Base.metadata.create_all(bind=dst)

    src_inspect = inspect(src)
    tables = src_inspect.get_table_names()
    print(f"Tables found: {tables}")

    total_rows = 0
    with src.connect() as sconn, dst.begin() as dconn:
        for table in tables:
            rows = sconn.execute(text(f'SELECT * FROM "{table}"')).mappings().all()
            if not rows:
                print(f"  {table}: 0 rows (skip)")
                continue

            cols = list(rows[0].keys())
            col_sql = ", ".join(f'"{c}"' for c in cols)
            placeholders = ", ".join(f":{c}" for c in cols)
            insert_sql = f'INSERT INTO "{table}" ({col_sql}) VALUES ({placeholders})'

            for row in rows:
                params = {}
                for k, v in dict(row).items():
                    if isinstance(v, (list, dict)):
                        import json
                        params[k] = json.dumps(v, default=str)
                    else:
                        params[k] = v
                dconn.execute(text(insert_sql), params)

            total_rows += len(rows)
            print(f"  {table}: {len(rows)} rows")

    print(f"Done. Migrated {total_rows} total rows -> {db_path}")


if __name__ == "__main__":
    main()
