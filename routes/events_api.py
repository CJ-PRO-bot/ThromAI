# routes/events_api.py
import os, json, uuid, datetime
from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename
from models import db, Incident  # we'll add Incident to models.py in step 2

bp_events = Blueprint("bp_events", __name__)

# Simple token check (recommended)
def check_auth(req):
    token = req.headers.get("X-API-TOKEN") or req.form.get("api_token")
    expected = os.getenv("API_TOKEN", "")
    return (expected != "") and (token == expected)

def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)
    return path

@bp_events.route("/events", methods=["POST"])
def ingest_event():
    if not check_auth(request):
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    # meta
    try:
        meta = json.loads(request.form.get("meta", "{}"))
    except Exception:
        meta = {}

    camera_id  = meta.get("camera_id", "unknown_cam")
    event_type = meta.get("event_type", "litter_event")
    confidence = str(meta.get("confidence", ""))

    clip_file  = request.files.get("clip")
    image_file = request.files.get("image")
    if not (clip_file or image_file):
        return jsonify({"ok": False, "error": "no files provided"}), 400

    ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    uid = f"{ts}_{uuid.uuid4().hex[:8]}"

    base_dir = ensure_dir(os.path.join(current_app.root_path, "static", "uploads", "events"))
    rel_clip, rel_img = "", ""

    if clip_file:
        clip_name = secure_filename(f"{uid}.mp4")
        clip_path = os.path.join(base_dir, clip_name)
        clip_file.save(clip_path)
        rel_clip = f"/static/uploads/events/{clip_name}"

    if image_file:
        img_name = secure_filename(f"{uid}.jpg")
        img_path = os.path.join(base_dir, img_name)
        image_file.save(img_path)
        rel_img = f"/static/uploads/events/{img_name}"

    incident = Incident(
        camera_id=camera_id,
        event_type=event_type,
        confidence=confidence,
        image_path=rel_img,
        video_path=rel_clip,
        meta_json=json.dumps(meta),
        status="pending",
    )
    db.session.add(incident)
    db.session.commit()

    return jsonify({
        "ok": True,
        "id": incident.id,
        "camera_id": camera_id,
        "event_type": event_type,
        "image_url": rel_img,
        "video_url": rel_clip
    }), 201
