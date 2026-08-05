"""Apply db/init/02-schema.sql to the running database.

Postgres only executes db/init/ on the first boot of an empty data volume, so an
existing volume needs the DDL applied explicitly. This runs the same file, which
keeps one copy of the schema rather than a second one embedded in Python.

Safe to re-run: every statement in the .sql uses IF NOT EXISTS.

    python scripts/apply_schema.py
"""
from pathlib import Path

from db import connect

SCHEMA = Path(__file__).resolve().parent.parent / "db" / "init" / "02-schema.sql"


def main():
    sql = SCHEMA.read_text(encoding="utf-8")

    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql)
        conn.commit()

        cur.execute(
            """
            SELECT column_name, data_type, is_generated
            FROM information_schema.columns
            WHERE table_name = 'movies'
            ORDER BY ordinal_position
            """
        )
        columns = cur.fetchall()

        cur.execute(
            "SELECT indexname FROM pg_indexes WHERE tablename = 'movies' ORDER BY indexname"
        )
        indexes = [row[0] for row in cur.fetchall()]

    print(f"applied {SCHEMA.name}")
    print(f"\nmovies: {len(columns)} columns")
    for name, dtype, generated in columns:
        flag = "   <- generated" if generated == "ALWAYS" else ""
        print(f"  {name:<18} {dtype}{flag}")

    print(f"\nindexes: {len(indexes)}")
    for name in indexes:
        print(f"  {name}")


if __name__ == "__main__":
    main()
