import sqlite3, pathlib
db = pathlib.Path("site.db").resolve()
print("DB at:", db)
con = sqlite3.connect(db)
cur = con.cursor()
cur.execute("PRAGMA table_info(submission)")
print("submission columns:")
for row in cur.fetchall():
    print(row)
con.close()
