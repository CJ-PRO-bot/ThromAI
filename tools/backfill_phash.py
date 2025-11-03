# tools/backfill_phash.py
from pathlib import Path
import sys, os
from PIL import Image
import imagehash

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# IMPORTANT: this assumes your main file is app.py.
# If your file is named apps.py, change next line to: from apps import app, db
from app import app, db
from models import Submission

with app.app_context():
    updated = 0
    rows = Submission.query.all()
    for s in rows:
        if not s.phash and s.image_path:
            abs_path = os.path.join(app.root_path, s.image_path)
            if os.path.exists(abs_path):
                try:
                    ph = imagehash.phash(Image.open(abs_path))
                    s.phash = str(ph)
                    updated += 1
                except Exception:
                    pass
    db.session.commit()
    print(f"Backfilled {updated} phash values.")
