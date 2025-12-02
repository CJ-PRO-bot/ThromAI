import sqlite3, os db = 'site.db' print('DB:', os.path.abspath(db), 'exists=', os.path.exists(db)) con = sqlite3.connect(db) c = con.cursor() print('Before:') c.execute('PRAGMA table_info(user)') print(c.fetchall())

def ensure(col, ddl): if not c.execute("SELECT 1 FROM pragma_table_info('user') WHERE name=?", (col,)).fetchone(): c.execute(ddl) print('Added column', col) else: print('Column already exists:', col)

ensure('photo_url', 'ALTER TABLE user ADD COLUMN photo_url VARCHAR(256)') ensure('bio', 'ALTER TABLE user ADD COLUMN bio VARCHAR(160)')

print('After:') c.execute('PRAGMA table_info(user)') print(c.fetchall()) con.commit() con.close()