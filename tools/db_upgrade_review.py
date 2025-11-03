# tools/db_upgrade_review.py
import sqlite3, os
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "site.db"
if not DB.exists():
    print("No site.db found.")
    raise SystemExit(0)

con = sqlite3.connect(DB.as_posix())
cur = con.cursor()

def add_col(table, coldef):
    try:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {coldef}")
        print(f"Added {table}.{coldef}")
    except Exception as e:
        print(f"Skip {table}.{coldef}: {e}")

add_col("submission", "human_state TEXT DEFAULT 'unreviewed'")
add_col("submission", "reviewed_at DATETIME")
add_col("submission", "reviewed_by INTEGER")
add_col("submission", "notes_admin TEXT")

# quick index for queue speed
try:
    cur.execute("CREATE INDEX idx_submission_human_state ON submission (human_state)")
    print("Created index idx_submission_human_state")
except Exception as e:
    print("Skip index:", e)

con.commit()
con.close()
print("DB review upgrade done.")
