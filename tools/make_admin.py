# tools/make_admin.py
import sys, pathlib
# ensure project root on sys.path
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import app, db
from models import User

import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--user", "-u", required=True, help="username to promote to admin")
args = parser.parse_args()

with app.app_context():
    u = User.query.filter_by(username=args.user).first()
    if not u:
        raise SystemExit(f"User '{args.user}' not found. Create it in the UI first.")
    u.role = "admin"
    db.session.commit()
    print(f"Done. '{args.user}' is now admin.")
