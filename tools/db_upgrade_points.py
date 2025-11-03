# tools/db_upgrade_points.py
import sqlite3, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
dbp = ROOT / "site.db"
if not dbp.exists():
    print("No site.db found (run the app once to create it).")
    sys.exit(0)

con = sqlite3.connect(dbp.as_posix())
cur = con.cursor()

def add_col(table, coldef):
    try:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {coldef}")
        print(f"Added {table}.{coldef}")
    except Exception as e:
        # already exists or other no-op
        pass

add_col("user", "points INTEGER DEFAULT 0")
add_col("submission", "points_awarded INTEGER DEFAULT 0")
add_col("submission", "approved_at DATETIME")
add_col("submission", "approved_by INTEGER")

con.commit()
con.close()
print("DB upgrade done.")
