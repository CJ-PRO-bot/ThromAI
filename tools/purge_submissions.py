# tools/purge_submissions.py
from pathlib import Path
import sys, os

# --- Ensure we can import app/models from the project root ---
ROOT = Path(__file__).resolve().parents[1]   # .../PhotoVerifierApp_2(0)
sys.path.insert(0, str(ROOT))

from app import app, db                 # your Flask app + DB
from models import Submission, Message  # your models

UPLOAD_DIR = (ROOT / "static" / "uploads").resolve()

def main():
    with app.app_context():
        # Gather file paths first (so we can delete after DB rows are gone)
        paths = []
        for s in Submission.query.all():
            if s.image_path:
                p = (Path(app.root_path) / s.image_path).resolve()
                paths.append(p)

        # Delete child rows first, then submissions
        Message.query.delete()
        db.session.commit()

        Submission.query.delete()
        db.session.commit()

    # Remove files from disk (safety: only inside uploads/)
    deleted = 0
    for p in paths:
        try:
            if str(p).startswith(str(UPLOAD_DIR)) and p.exists():
                p.unlink()
                deleted += 1
        except Exception as e:
            print("Could not delete:", p, e)

    print(f"Done. Deleted {deleted} uploaded files and all submissions/messages.")

if __name__ == "__main__":
    main()
