# tools/db_add_reporter_location.py
# One-time migration to add reporter_location column to submission table.
# Usage (PowerShell):
#   & "c:\\PhotoVerifierApp_2(0) - pilot_testing\\.venv\\Scripts\\python.exe" "c:\\PhotoVerifierApp_2(0) - pilot_testing\\tools\\db_add_reporter_location.py"

from sqlalchemy import text
from app import app, db


def main():
    print("Applying migration: add reporter_location column...")
    with app.app_context():
        try:
            db.session.execute(text("ALTER TABLE submission ADD COLUMN reporter_location TEXT"))
            db.session.commit()
            print("Column reporter_location added.")
        except Exception as e:
            print("Migration step raised:", e)
            # Check if column already exists
            try:
                db.session.execute(text("SELECT reporter_location FROM submission LIMIT 1"))
                print("Column already exists; nothing to do.")
            except Exception as e2:
                print("Sanity check failed:", e2)
                raise SystemExit(1)


if __name__ == "__main__":
    main()
