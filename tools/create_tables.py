from app import app, db
import models  # ensure models are imported so SQLAlchemy registers metadata

if __name__ == '__main__':
    print('Creating tables using SQLALCHEMY_DATABASE_URI =', app.config.get('SQLALCHEMY_DATABASE_URI'))
    with app.app_context():
        # Touch model classes to ensure import side-effects
        _ = (models.User, models.Submission, models.Message)
        db.create_all()
        print('create_all done')
