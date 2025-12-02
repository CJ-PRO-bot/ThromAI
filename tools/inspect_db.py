import os import sqlite3

def get_db_path(): try: from app import app uri = app.config.get('SQLALCHEMY_DATABASE_URI', '') # Handle sqlite:///absolute/path or sqlite:////C:/... forms if uri.startswith('sqlite:///'): raw = uri[len('sqlite:///'):] # If path starts with / on Windows, strip extra leading slash if os.name == 'nt' and raw.startswith('/'): raw = raw.lstrip('/') return raw except Exception: pass # Fallback to local site.db return os.path.abspath('site.db')

DB = get_db_path() print('DB:', DB, 'exists=', os.path.exists(DB))

con = sqlite3.connect(DB) c = con.cursor() c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name") tables = [r[0] for r in c.fetchall()] print('Tables:', tables)

if 'user' in tables: c.execute('PRAGMA table_info(user)') cols = c.fetchall() print('user columns:') for col in cols: print(' -', col) else: print("Table 'user' not found (yet).")

con.close()