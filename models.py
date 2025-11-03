# models.py
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(db.Model, UserMixin):
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(16), default="user")

    # points / timestamps
    points = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    submissions = db.relationship(
        "Submission",
        back_populates="user",
        foreign_keys="Submission.user_id",
        lazy="dynamic",
    )
    approvals = db.relationship(
        "Submission",
        back_populates="approver",
        foreign_keys="Submission.approved_by",
        lazy="dynamic",
    )
    messages = db.relationship(
        "Message",
        back_populates="sender",
        foreign_keys="Message.sender_id",
        lazy="dynamic",
    )

    supw_assignments = db.relationship(
        "SupwAssignment",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User", backref="chat_messages")

class Submission(db.Model):
    __tablename__ = "submission"

    id = db.Column(db.Integer, primary_key=True)

    # reporter
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    report_type = db.Column(db.String(32))
    image_path = db.Column(db.String(256), nullable=False)

    # GPS
    lat = db.Column(db.Float)
    lon = db.Column(db.Float)

    # AI fields (machine side)
    ai_label = db.Column(db.String(32))
    ai_score = db.Column(db.Float)
    status = db.Column(db.String(16))
    phash = db.Column(db.String(32), index=True)
    duplicate_of = db.Column(db.Integer)
    exif_time_ok = db.Column(db.Boolean)
    action_score = db.Column(db.Float)
    auth_score = db.Column(db.Float)
    relevance_score = db.Column(db.Float)
    model_version = db.Column(db.String(32))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # approval / points (existing)
    points_awarded = db.Column(db.Integer, default=0)
    approved_at = db.Column(db.DateTime)
    approved_by = db.Column(db.Integer, db.ForeignKey("user.id"))

    # ==== NEW: Human review (admin) side ====
    # human_state controls where items show up in the admin queues
    human_state = db.Column(db.String(16), default="unreviewed", index=True)  # unreviewed|approved|rejected|flagged
    reviewed_at = db.Column(db.DateTime)
    reviewed_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    notes_admin = db.Column(db.String(280))  # optional short note
    # ========================================

    user = db.relationship(
        "User",
        foreign_keys=[user_id],
        back_populates="submissions",
    )
    approver = db.relationship(
        "User",
        foreign_keys=[approved_by],
        back_populates="approvals",
    )

    messages = db.relationship(
        "Message",
        back_populates="submission",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

class Message(db.Model):
    __tablename__ = "message"

    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer, db.ForeignKey("submission.id"), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    submission = db.relationship(
        "Submission",
        back_populates="messages",
    )
    sender = db.relationship(
        "User",
        foreign_keys=[sender_id],
        back_populates="messages",
    )

# -------------------------
# SUPW Coordination Models
# -------------------------
class SupwPlace(db.Model):
    __tablename__ = "supw_place"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    description = db.Column(db.Text)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    assignments = db.relationship(
        "SupwAssignment",
        back_populates="place",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

class SupwAssignment(db.Model):
    __tablename__ = "supw_assignment"
    id = db.Column(db.Integer, primary_key=True)
    place_id = db.Column(db.Integer, db.ForeignKey("supw_place.id"), nullable=False, index=True)
    user_id  = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    assigned_at = db.Column(db.DateTime, default=datetime.utcnow)

    place = db.relationship("SupwPlace", back_populates="assignments")
    user  = db.relationship("User", back_populates="supw_assignments")

    __table_args__ = (
        db.UniqueConstraint("place_id", "user_id", name="uq_place_user"),
    )
