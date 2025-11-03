# app.py
# ======================================================
# PhotoVerifierApp - Flask Main Application
# ======================================================
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from sqlalchemy import desc, func
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(), override=True)

import os
import uuid
from pathlib import Path
from datetime import datetime, timedelta
import piexif

from flask import Flask, render_template, request, redirect, url_for, flash, abort, jsonify
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import (
    LoginManager, login_user, logout_user, login_required, current_user
)
from PIL import Image
import imagehash

from models import db, User, Submission, Message
from ai.verifier import Verifier

# -------------------------
# GPS helpers
# -------------------------
def _dms_to_deg(dms, ref):
    def v(x): return float(x[0]) / float(x[1])
    deg = v(dms[0]) + v(dms[1]) / 60.0 + v(dms[2]) / 3600.0
    if ref in [b"S", b"W"]:
        deg *= -1.0
    return deg

def extract_gps(path: str):
    try:
        exif = piexif.load(path)
        gps = exif.get("GPS", {})
        lat = lon = None
        if gps.get(piexif.GPSIFD.GPSLatitude) and gps.get(piexif.GPSIFD.GPSLatitudeRef):
            lat = _dms_to_deg(gps[piexif.GPSIFD.GPSLatitude], gps[piexif.GPSIFD.GPSLatitudeRef])
        if gps.get(piexif.GPSIFD.GPSLongitude) and gps.get(piexif.GPSIFD.GPSLongitudeRef):
            lon = _dms_to_deg(gps[piexif.GPSIFD.GPSLongitude], gps[piexif.GPSIFD.GPSLongitudeRef])
        return (lat, lon)
    except Exception:
        return (None, None)

ROOT = Path(__file__).resolve().parent

def _abs(p: str | None) -> str | None:
    if not p:
        return None
    path = Path(p)
    return str(path if path.is_absolute() else (ROOT / path))

os.environ.setdefault("PV_MODEL_PATH", _abs("ai/waste_v1/validity_classifier.onnx"))
os.environ.setdefault("PV_CLASS_MAP_PATH", _abs("ai/waste_v1/class_map.json"))
os.environ.setdefault("PV_MODEL_VERSION", "waste_v1_onnx")
os.environ.setdefault("PV_ACTION_CUTOFF", "0.50")
os.environ.setdefault("PV_DISABLE_DUP_PENALTY", "1")
os.environ.setdefault("PV_DUP_DISTANCE", "3")

POINTS_PER_APPROVAL = int(os.getenv("POINTS_PER_APPROVAL", "10"))

verifier = Verifier()

# -------------------------
# Flask config
# -------------------------
app = Flask(__name__)
limiter = Limiter(get_remote_address, app=app, default_limits=["60 per hour"])

app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

DB_PATH = (ROOT / "site.db").resolve()
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH.as_posix()}"
app.config["REMEMBER_COOKIE_DURATION"] = timedelta(days=30)

app.config["UPLOAD_FOLDER"] = os.path.join(app.root_path, "static", "uploads")
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

db.init_app(app)

try:
    with app.app_context():
        db.create_all()
except Exception as e:
    print("[WARN] db.create_all failed:", e)

login_manager = LoginManager(app)
login_manager.login_view = "login"

@login_manager.user_loader
def load_user(uid):
    return User.query.get(int(uid))

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "bmp"}

def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def unique_filename(original: str) -> str:
    base = secure_filename(os.path.splitext(original)[0]) or "upload"
    ext = os.path.splitext(original)[1].lower() or ".jpg"
    if not ext.startswith("."):
        ext = "." + ext
    return f"{base}-{uuid.uuid4().hex[:8]}{ext}"

def admin_required(fn):
    from functools import wraps
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != "admin":
            flash("Admin only")
            return redirect(url_for("index"))
        return fn(*args, **kwargs)
    return wrapper

def _award_points_if_needed(sub: Submission):
    if sub.status == "AUTO_OK" and (sub.points_awarded or 0) == 0:
        sub.points_awarded = POINTS_PER_APPROVAL
        if sub.user:
            sub.user.points = (sub.user.points or 0) + POINTS_PER_APPROVAL
        if not sub.approved_at:
            sub.approved_at = datetime.utcnow()
        if not sub.approved_by and current_user.is_authenticated:
            sub.approved_by = current_user.id

def _save_and_score(file_storage, report_type, msg, lat, lon):
    fname = unique_filename(getattr(file_storage, "filename", "camera.jpg"))
    path = os.path.join(app.config["UPLOAD_FOLDER"], fname)
    file_storage.save(path)

    ex_lat, ex_lon = extract_gps(path)
    if ex_lat is not None and ex_lon is not None:
        lat, lon = ex_lat, ex_lon

    try:
        new_phash = imagehash.phash(Image.open(path))
    except Exception:
        new_phash = None

    nearest_id = None
    nearest_dist = 999
    recent = Submission.query.order_by(desc(Submission.created_at)).limit(200).all()
    if new_phash is not None:
        for s in recent:
            if s.phash:
                try:
                    dist = abs(new_phash - imagehash.hex_to_hash(s.phash))
                    if dist < nearest_dist:
                        nearest_dist = dist
                        nearest_id = s.id
                except Exception:
                    pass
        dup_thresh = int(os.getenv("PV_DUP_DISTANCE", "3"))
        duplicate_of = nearest_id if nearest_dist <= dup_thresh else None
    else:
        duplicate_of = None

    existing = [(s.id, getattr(s, "phash", None)) for s in recent if getattr(s, "phash", None)]
    scores = verifier.score(path, existing_phashes=existing)

    final_phash = scores.get("phash") or (str(new_phash) if new_phash is not None else None)
    final_duplicate_of = scores.get("duplicate_of") or duplicate_of

    sub = Submission(
        user_id=current_user.id,
        report_type=report_type,
        image_path=os.path.relpath(path, app.root_path).replace("\\", "/"),
        lat=(float(lat) if lat not in (None, "", "null") else None),
        lon=(float(lon) if lon not in (None, "", "null") else None),
        ai_label=scores.get("ai_label"),
        ai_score=scores.get("action_score"),
        status=scores.get("status"),
        phash=final_phash,
        duplicate_of=final_duplicate_of,
        exif_time_ok=scores.get("exif_time_ok"),
        action_score=scores.get("action_score"),
        auth_score=scores.get("auth_score"),
        relevance_score=scores.get("relevance_score"),
        model_version=scores.get("model_version"),

        # NEW: make sure fresh items default to unreviewed
        human_state="unreviewed",
    )
    db.session.add(sub)
    db.session.flush()
    if sub.status == "AUTO_OK":
        _award_points_if_needed(sub)
    db.session.commit()

    if msg:
        m = Message(submission_id=sub.id, sender_id=current_user.id, body=msg)
        db.session.add(m); db.session.commit()

    return sub

# -------------------------
# Auth
# -------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        e = request.form.get("email", "").strip().lower()
        pw = request.form.get("password", "")
        if not u or not e or not pw:
            flash("All fields are required.")
            return redirect(url_for("register"))
        if User.query.filter((User.username == u) | (User.email == e)).first():
            flash("Username or email already exists.")
            return redirect(url_for("register"))
        user = User(username=u, email=e, password_hash=generate_password_hash(pw), role="user")
        db.session.add(user); db.session.commit()
        flash("Registered. Please log in.")
        return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        ident = request.form.get("identifier", "").strip()
        p = request.form.get("password", "")
        user = User.query.filter_by(username=ident).first()
        if not user:
            user = User.query.filter_by(email=ident.lower()).first()
        if user and check_password_hash(user.password_hash, p):
            login_user(user)
            nxt = request.args.get("next")
            return redirect(nxt or url_for("index"))
        flash("Invalid credentials")
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out.")
    return redirect(url_for("login"))

# -------------------------
# Upload (form) + message
# -------------------------
@app.route("/", methods=["GET", "POST"])
@login_required
def index():
    if request.method == "POST":
        report_type = request.form.get("report_type", "illegal_dumping")
        f = request.files.get("photo")
        msg = request.form.get("message", "").strip()

        if not f or f.filename == "":
            flash("No file selected.")
            return redirect(url_for("index"))
        if not allowed_file(f.filename):
            flash("Unsupported file type. Please upload an image.")
            return redirect(url_for("index"))

        lat = request.form.get("lat"); lon = request.form.get("lon")
        sub = _save_and_score(f, report_type, msg, lat, lon)
        return redirect(url_for("result", sid=sub.id))

    return render_template("index.html")

@app.route("/upload_api", methods=["POST"])
@login_required
def upload_api():
    f = request.files.get("photo")
    if not f:
        return jsonify({"ok": False, "error": "No photo"}), 400
    report_type = request.form.get("report_type", "illegal_dumping")
    msg = request.form.get("message", "").strip()
    lat = request.form.get("lat")
    lon = request.form.get("lon")
    sub = _save_and_score(f, report_type, msg, lat, lon)
    return jsonify({"ok": True, "redirect": url_for("result", sid=sub.id)})

@app.route("/result/<int:sid>")
@login_required
def result(sid):
    sub = Submission.query.get_or_404(sid)
    if sub.user_id != current_user.id and current_user.role != "admin":
        flash("Not authorized")
        return redirect(url_for("index"))

    cutoff = float(os.getenv("PV_ACTION_CUTOFF", "0.50"))
    dup_disabled = os.getenv("PV_DISABLE_DUP_PENALTY", "0") == "1"
    dup_penalty = float(os.getenv("PV_DUP_PENALTY", "0.40"))

    return render_template(
        "result.html",
        submission=sub,
        cutoff=cutoff,
        dup_disabled=dup_disabled,
        dup_penalty=dup_penalty,
    )

@app.route("/message/<int:sid>", methods=["POST"])
@login_required
def post_message(sid):
    sub = Submission.query.get_or_404(sid)
    if sub.user_id != current_user.id and current_user.role != "admin":
        flash("Not authorized")
        return redirect(url_for("index"))

    body = request.form.get("body", "").strip()
    if body:
        m = Message(submission_id=sid, sender_id=current_user.id, body=body)
        db.session.add(m)
        db.session.commit()

    return redirect(url_for("result", sid=sid))

# -------------------------
# Admin (legacy)
# -------------------------
@app.route("/admin")
@login_required
@admin_required
def admin_home():
    # Keep old dashboard but now show counts and link to the new Review Console
    pending_count = Submission.query.filter_by(human_state="unreviewed").count()
    approved_count = Submission.query.filter_by(human_state="approved").count()
    rejected_count = Submission.query.filter_by(human_state="rejected").count()

    auto_ok = Submission.query.filter_by(status="AUTO_OK").order_by(Submission.created_at.desc()).limit(20).all()
    rechecks = Submission.query.filter_by(status="RECHECK").order_by(Submission.created_at.desc()).limit(20).all()

    return render_template("admin_dashboard.html",
                           auto_ok=auto_ok,
                           rechecks=rechecks,
                           pending_count=pending_count,
                           approved_count=approved_count,
                           rejected_count=rejected_count)

@app.route("/admin/mark/<int:sid>/<string:new_status>", methods=["POST"])
@login_required
@admin_required
def admin_mark(sid, new_status):
    # unchanged: this is still the AI-status override (optional to keep)
    if new_status not in ("AUTO_OK", "RECHECK"):
        flash("Invalid status")
        return redirect(url_for("admin_home"))
    sub = Submission.query.get_or_404(sid)
    prev = sub.status
    sub.status = new_status
    if new_status == "AUTO_OK" and prev != "AUTO_OK":
        _award_points_if_needed(sub)
    db.session.commit()
    return redirect(url_for("admin_home"))

@app.route("/admin/set_category/<int:sid>", methods=["POST"])
@login_required
@admin_required
def admin_set_category(sid):
    sub = Submission.query.get_or_404(sid)
    new_type = request.form.get("report_type", "").strip()
    if new_type not in ("illegal_dumping", "volunteer_works"):
        flash("Invalid category")
        return redirect(url_for("result", sid=sid))
    sub.report_type = new_type
    db.session.commit()
    flash("Category updated.")
    return redirect(url_for("result", sid=sid))

# -------------------------
# NEW REVIEW CONSOLE
# -------------------------
def _queue_base_query(tab: str):
    q = Submission.query
    if tab == "pending":
        q = q.filter(Submission.human_state == "unreviewed")
    elif tab == "accepted":
        q = q.filter(Submission.human_state == "approved")
    elif tab == "rejected":
        q = q.filter(Submission.human_state == "rejected")
    elif tab == "mine_today":
        start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        q = q.filter(Submission.reviewed_by == current_user.id, Submission.reviewed_at >= start)
    else:
        q = q  # all
    return q

@app.route("/admin/review")
@login_required
@admin_required
def admin_review():
    tab = (request.args.get("tab") or "pending").lower()
    page = max(1, int(request.args.get("page", "1")))
    per_page = min(50, int(request.args.get("per_page", "25")))
    category = request.args.get("type", "all")
    dz = request.args.get("dzongkhag", "all")

    q = _queue_base_query(tab)

    if category in ("illegal_dumping", "volunteer_works"):
        q = q.filter(Submission.report_type == category)

    # simple dz bounding box like your hotspots (optional; safe-guard if lat/lon present)
    if dz and dz != "all":
        DZ_BBOX = {
            "thimphu": (27.30, 27.60, 89.45, 89.80),
            "paro":    (27.30, 27.70, 89.20, 89.60),
            "punakha": (27.50, 27.90, 89.65, 90.10),
            "wangdue": (27.30, 27.80, 89.70, 90.30),
            "chukha":  (26.75, 27.35, 89.30, 89.85),
        }
        if dz in DZ_BBOX:
            la0, la1, lo0, lo1 = DZ_BBOX[dz]
            q = q.filter(Submission.lat >= la0, Submission.lat <= la1,
                         Submission.lon >= lo0, Submission.lon <= lo1)

    q = q.order_by(Submission.created_at.desc())
    total = q.count()
    rows = q.offset((page-1)*per_page).limit(per_page).all()

    # counts for tabs
    pending_count = Submission.query.filter_by(human_state="unreviewed").count()
    approved_count = Submission.query.filter_by(human_state="approved").count()
    rejected_count = Submission.query.filter_by(human_state="rejected").count()

    # find the "next id" for auto-advance (next row in this page, else first on next page)
    next_id = None
    if rows:
        # default to the second item; if you click on first, next is the second, etc.
        if len(rows) >= 2:
            next_id = rows[1].id
        else:
            # look ahead into next page
            nxt = q.offset(page*per_page).limit(1).all()
            if nxt:
                next_id = nxt[0].id

    return render_template(
        "admin_review.html",
        tab=tab, rows=rows, total=total, page=page, per_page=per_page,
        pending_count=pending_count, approved_count=approved_count, rejected_count=rejected_count,
        category=category, dz=dz, next_id=next_id
    )

@app.route("/admin/review/decide/<int:sid>/<string:decision>", methods=["POST"])
@login_required
@admin_required
def admin_review_decide(sid, decision):
    # decision: approve|reject|flag
    sub = Submission.query.get_or_404(sid)
    if decision not in ("approve", "reject", "flag"):
        flash("Invalid decision")
        return redirect(url_for("admin_review"))

    now = datetime.utcnow()
    if decision == "approve":
        sub.human_state = "approved"
        sub.reviewed_at = now
        sub.reviewed_by = current_user.id
        # You may still want to award points only when AI also okayed it; keeping your old rule:
        if sub.status == "AUTO_OK":
            # award once
            if (sub.points_awarded or 0) == 0:
                sub.points_awarded = int(os.getenv("POINTS_PER_APPROVAL", "10"))
                if sub.user:
                    sub.user.points = (sub.user.points or 0) + sub.points_awarded
                if not sub.approved_at:
                    sub.approved_at = now
                if not sub.approved_by:
                    sub.approved_by = current_user.id

    elif decision == "reject":
        sub.human_state = "rejected"
        sub.reviewed_at = now
        sub.reviewed_by = current_user.id
    else:
        sub.human_state = "flagged"
        sub.reviewed_at = now
        sub.reviewed_by = current_user.id

    # optional short note
    note = (request.form.get("note") or "").strip()
    if note:
        sub.notes_admin = note[:280]

    db.session.commit()

    # AUTO-ADVANCE: return to same filtered view, jump to "next_id" if provided
    tab = request.form.get("tab", "pending")
    category = request.form.get("type", "all")
    dz = request.form.get("dzongkhag", "all")
    page = request.form.get("page", "1")
    next_id = request.form.get("next_id")

    if tab == "pending" and next_id:
        return redirect(url_for("admin_review", tab=tab, type=category, dzongkhag=dz, page=page) + f"#s{next_id}")
    return redirect(url_for("admin_review", tab=tab, type=category, dzongkhag=dz, page=page))

@app.route("/map")
def public_map():
    return render_template("public_map.html")

@app.route("/chat", methods=["GET", "POST"])
@login_required
def chat_room():
    if request.method == "POST":
        body = (request.form.get("body") or "").strip()
        if body:
            from models import ChatMessage
            m = ChatMessage(user_id=current_user.id, body=body)
            db.session.add(m); db.session.commit()
        return redirect(url_for("chat_room"))

    from models import ChatMessage
    # ...
    msgs = ChatMessage.query.order_by(ChatMessage.created_at.desc()).limit(100).all()
    msgs = list(reversed(msgs))
    last_id = msgs[-1].id if msgs else 0
    return render_template("chat.html", msgs=msgs, last_id=last_id)


# lightweight polling to fetch recent messages as HTML fragment
@app.route("/chat/stream")
@login_required
def chat_stream():
    from models import ChatMessage
    since_id = int(request.args.get("since", "0"))
    q = ChatMessage.query
    if since_id:
        q = q.filter(ChatMessage.id > since_id)
    new_msgs = q.order_by(ChatMessage.id.asc()).limit(100).all()
    return render_template("_chat_items.html", msgs=new_msgs)

@app.route("/admin/heatmap")
@login_required
@admin_required
def admin_heatmap():
    return render_template("admin_heatmap.html")

@app.route("/leaderboard")
@login_required
def leaderboard():
    top_users = User.query.order_by(User.points.desc(), User.username.asc()).limit(50).all()
    my_rank = None
    if current_user.is_authenticated:
        higher = User.query.filter(User.points > (current_user.points or 0)).count()
        my_rank = higher + 1
    return render_template("leaderboard.html", users=top_users, my_rank=my_rank)

# Blueprints
try:
    from routes.hotspots import bp_hotspots
    app.register_blueprint(bp_hotspots)
except Exception as e:
    print("[WARN] hotspots blueprint not registered:", repr(e))

try:
    from routes.supw import bp_supw
    app.register_blueprint(bp_supw)
except Exception as e:
    print("[WARN] SUPW blueprint not registered:", repr(e))

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True, use_reloader=False)
