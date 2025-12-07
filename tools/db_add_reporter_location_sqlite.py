# tools/db_add_reporter_location_sqlite.py
# Direct SQLite migration without importing the Flask app.
# Uses site.db in the project root.
import sqlite3
import pathlib
import sys

def main():
    db_path = str(pathlib.Path('site.db').resolve())
    print("Using SQLite file:", db_path)
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    try:
        cur.execute("ALTER TABLE submission ADD COLUMN reporter_location TEXT")
        con.commit()
        print("Column reporter_location added.")
    except Exception as e:
        print("Migration step:", e)
        try:
            cur.execute("SELECT reporter_location FROM submission LIMIT 1").fetchall()
            print("Column already exists, nothing to do.")
        except Exception as e2:
            print("Sanity check failed:", e2)
            sys.exit(1)
    finally:
        con.close()

if __name__ == "__main__":
    main()
