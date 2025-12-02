import os
import sys
from urllib.parse import urlparse
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(), override=True)

# Usage:
#   python tools/migrate_sqlite_to_postgres.py \
#     --sqlite sqlite:///site.db \
#     --postgres postgresql+psycopg://USER:PASS@HOST:5432/DB
# If --postgres is omitted, will use DATABASE_URL from env.

DEFAULT_SQLITE = "sqlite:///site.db"

def parse_args(argv):
    sqlite_url = None
    pg_url = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--sqlite" and i+1 < len(argv):
            sqlite_url = argv[i+1]; i += 2; continue
        if a == "--postgres" and i+1 < len(argv):
            pg_url = argv[i+1]; i += 2; continue
        i += 1
    return sqlite_url or os.getenv("SQLITE_URL", DEFAULT_SQLITE), pg_url or os.getenv("DATABASE_URL")


def ensure_postgres_url(pg_url: str | None):
    if not pg_url:
        print("ERROR: Missing Postgres URL. Provide --postgres or set DATABASE_URL in env.")
        sys.exit(2)
    if pg_url.startswith("sqlite:"):
        print("ERROR: DATABASE_URL points to SQLite. Provide a Postgres URL.")
        sys.exit(2)
    return pg_url


def main():
    sqlite_url, pg_url = parse_args(sys.argv[1:])
    pg_url = ensure_postgres_url(pg_url)

    src_engine = create_engine(sqlite_url, pool_pre_ping=True)
    dst_engine = create_engine(pg_url, pool_pre_ping=True)

    # Create destination schema from models (if app is importable)
    try:
        from app import app, db
        with app.app_context():
            db.create_all()
        print("[INIT] Ensured destination schema exists via models.")
    except Exception as e:
        print("[WARN] Could not auto-create destination schema via app models:", e)
        print("[HINT] Ensure the Postgres database is reachable and the URL is correct.")

    # Copy tables respecting FKs: user -> submission/message; supw tables independent
    order = [
        "user",
        "supw_place",
        "supw_assignment",
        "submission",
        "message",
        "chat_message",
    ]

    with src_engine.connect() as src, dst_engine.begin() as dst:
        src_inspect = inspect(src_engine)
        dst_inspect = inspect(dst_engine)

        for tbl in order:
            if tbl not in src_inspect.get_table_names():
                print(f"[SKIP] {tbl} not in source")
                continue
            cols = [c["name"] for c in src_inspect.get_columns(tbl)]
            dst_cols = [c["name"] for c in dst_inspect.get_columns(tbl)]
            common = [c for c in cols if c in dst_cols]
            if not common:
                print(f"[SKIP] {tbl} has no common columns")
                continue

            sel = text(f"SELECT {', '.join(common)} FROM {tbl}")
            rows = list(src.execute(sel))
            if not rows:
                print(f"[OK] {tbl}: no rows to migrate")
                continue

            placeholders = ", ".join([f":{c}" for c in common])
            ins = text(f"INSERT INTO {tbl} ({', '.join(common)}) VALUES ({placeholders})")

            print(f"[COPY] {tbl}: {len(rows)} rows")
            # Batch insert
            batch = []
            BATCH_SIZE = 1000
            for r in rows:
                batch.append({c: r[idx] for idx, c in enumerate(common)})
                if len(batch) >= BATCH_SIZE:
                    dst.execute(ins, batch)
                    batch.clear()
            if batch:
                dst.execute(ins, batch)
            print(f"[DONE] {tbl}")

    # Verify counts
    with src_engine.connect() as src, dst_engine.connect() as dst:
        def count(conn, tbl):
            try:
                return conn.execute(text(f"SELECT COUNT(*) FROM {tbl}")).scalar() or 0
            except Exception:
                return 0
        for tbl in order:
            sc = count(src, tbl)
            dc = count(dst, tbl)
            if sc or dc:
                print(f"[VERIFY] {tbl}: src={sc} dst={dc}")

    print("[SUCCESS] Migration complete.")

if __name__ == "__main__":
    main()
