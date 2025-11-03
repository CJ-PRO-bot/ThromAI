# tools/db_upgrade.py
import sqlite3, os
DB = "site.db"
if not os.path.exists(DB):
    print("No site.db found (nothing to upgrade).")
    raise SystemExit(0)

con = sqlite3.connect(DB)
cur = con.cursor()
for coldef in ("lat REAL", "lon REAL"):
    try:
        cur.execute(f"ALTER TABLE submission ADD COLUMN {coldef}")
        print(f"Added column: {coldef}")
    except Exception as e:
        print(f"Skip {coldef}: {e}")
con.commit(); con.close()
print("DB upgrade attempted.")
