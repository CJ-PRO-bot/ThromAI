# routes/hotspots.py
from flask import Blueprint, request, jsonify, Response, abort
from flask_login import login_required, current_user
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo  # Python 3.9+; on Windows you may need: pip install tzdata
from models import Submission
from math import floor
import random, csv, io
from app import limiter  # import limiter instance
from collections import defaultdict

bp_hotspots = Blueprint("bp_hotspots", __name__, url_prefix="/api/v1")

# ----------------
# Helpers / policy
# ----------------
def _is_admin():
    return current_user.is_authenticated and getattr(current_user, "role", None) == "admin"

def _round_coord(x: float, decimals: int = 3) -> float:
    if x is None:
        return None
    m = 10 ** decimals
    return floor(x * m) / m

def _jitter(x: float, amplitude: float = 0.0007) -> float:
    # ~ +/- 70–80 m jitter to protect privacy on public endpoints
    return x + (random.random() * 2 - 1) * amplitude

def _apply_common_filters(q, since, until=None, report_type="all", dzongkhag="all"):
    q = q.filter(Submission.created_at >= since)
    if until is not None:
        q = q.filter(Submission.created_at <= until)

    # approved only
    q = q.filter(Submission.status == "AUTO_OK")

    # category
    if report_type in ("illegal_dumping", "volunteer_works"):
        q = q.filter(Submission.report_type == report_type)

    # dzongkhag simple bounding boxes (rough & fast)
    DZ_BBOX = {
        "thimphu": (27.30, 27.60, 89.45, 89.80),
        "paro":    (27.30, 27.70, 89.20, 89.60),
        "punakha": (27.50, 27.90, 89.65, 90.10),
        "wangdue": (27.30, 27.80, 89.70, 90.30),
        "chukha":  (26.75, 27.35, 89.30, 89.85),
    }
    dz = (dzongkhag or "all").strip().lower()
    if dz != "all" and dz in DZ_BBOX:
        la0, la1, lo0, lo1 = DZ_BBOX[dz]
        q = q.filter(Submission.lat >= la0, Submission.lat <= la1,
                     Submission.lon >= lo0, Submission.lon <= lo1)

    return q

def _aggregate_round(rows, decimals=3):
    """Round lat/lon to small tiles and count."""
    bins = {}
    for r in rows:
        if r.lat is None or r.lon is None:
            continue
        lat = _round_coord(r.lat, decimals)
        lon = _round_coord(r.lon, decimals)
        key = (lat, lon)
        bins[key] = bins.get(key, 0) + 1
    out = []
    for (lat, lon), count in bins.items():
        out.append({"lat": lat, "lon": lon, "count": count})
    return out

def _get_thimphu_tz():
    """
    Safe resolver for Asia/Thimphu.
    On Windows, zoneinfo DB may be missing. If so, fall back to fixed +06:00.
    """
    try:
        return ZoneInfo("Asia/Thimphu")
    except Exception:
        return timezone(timedelta(hours=6))

# -----------------------------
# New endpoints for better UX
# -----------------------------
# A) HEAT POINTS (admin)
@bp_hotspots.route("/heat_points")
@login_required
def heat_points_admin():
    if not _is_admin():
        abort(403)

    days = int(request.args.get("days", 14))
    report_type = request.args.get("type", "all")
    dzongkhag = request.args.get("dzongkhag", "all")

    # optional map bbox for performance
    bbox = request.args.get("bbox")  # west,south,east,north
    since = datetime.utcnow() - timedelta(days=days)
    q = Submission.query
    q = _apply_common_filters(q, since, report_type=report_type, dzongkhag=dzongkhag)

    if bbox:
        try:
            west, south, east, north = map(float, bbox.split(","))
            q = q.filter(Submission.lon.between(west, east),
                         Submission.lat.between(south, north))
        except Exception:
            pass

    rows = q.all()
    points = []
    for r in rows:
        if r.lat is None or r.lon is None:
            continue
        w = 1.0 if (r.ai_label == "valid_report") else 0.6
        points.append([float(r.lat), float(r.lon), float(w)])
    return jsonify({"points": points, "total": len(points), "since_days": days})

# B) COLOR BUCKETS (admin)
@bp_hotspots.route("/tiles_buckets")
@login_required
def tiles_buckets_admin():
    if not _is_admin():
        abort(403)

    days = int(request.args.get("days", 14))
    report_type = request.args.get("type", "all")
    dzongkhag = request.args.get("dzongkhag", "all")

    since = datetime.utcnow() - timedelta(days=days)
    q = Submission.query
    q = _apply_common_filters(q, since, report_type=report_type, dzongkhag=dzongkhag)

    rows = q.all()
    total = len(rows)
    bins = _aggregate_round(rows, decimals=3)

    out = []
    if total < 100:
        mode = "counts"
        for b in bins:
            cnt = int(b["count"])
            if cnt <= 0:
                continue
            if 1 <= cnt < 50:
                band, color = "1-50", "#2ecc71"   # light green
            else:
                band, color = "50-100", "#1e8449" # dark green
            out.append({
                "lat": b["lat"], "lon": b["lon"],
                "count": cnt,
                "percent": round((cnt / max(1, total)) * 100.0, 2),
                "band": band, "color": color
            })
    else:
        mode = "percent"
        for b in bins:
            cnt = int(b["count"])
            if cnt <= 0:
                continue
            pct = (cnt / total) * 100.0
            if 0 <= pct < 10:      band, color = "1-10%",   "#2ecc71"
            elif pct < 20:         band, color = "10-20%",  "#1e8449"
            elif pct < 40:         band, color = "20-40%",  "#3498db"
            elif pct < 75:         band, color = "40-75%",  "#1f618d"
            else:                  band, color = "75-100%", "#e74c3c"
            out.append({
                "lat": b["lat"], "lon": b["lon"],
                "count": cnt,
                "percent": round(pct, 2),
                "band": band, "color": color
            })

    return jsonify({
        "mode": mode,
        "total": int(total),
        "tiles": out,
        "since_days": days
    })

# C) HOTSPOT PINS (admin)
@bp_hotspots.route("/hotspot_pins")
@login_required
def hotspot_pins_admin():
    if not _is_admin():
        abort(403)

    days = int(request.args.get("days", 7))
    report_type = request.args.get("type", "all")
    dzongkhag = request.args.get("dzongkhag", "all")
    min_count = int(request.args.get("min_count", 4))
    min_users = int(request.args.get("min_users", 2))

    since = datetime.utcnow() - timedelta(days=days)
    q = Submission.query
    q = _apply_common_filters(q, since, report_type=report_type, dzongkhag=dzongkhag)

    rows = q.all()

    from collections import defaultdict
    tile_counts = defaultdict(int)
    tile_users  = defaultdict(set)
    tile_centroid = defaultdict(lambda: [0.0, 0.0, 0])  # sum_lat, sum_lon, n

    for r in rows:
        if r.lat is None or r.lon is None:
            continue
        lat = _round_coord(r.lat, 3)
        lon = _round_coord(r.lon, 3)
        key = (lat, lon)
        tile_counts[key] += 1
        if r.user_id:
            tile_users[key].add(r.user_id)
        c = tile_centroid[key]
        tile_centroid[key] = [c[0]+lat, c[1]+lon, c[2]+1]

    feats = []
    for (lat, lon), cnt in tile_counts.items():
        users = len(tile_users[(lat, lon)])
        if cnt >= min_count and users >= min_users:
            s_lat, s_lon, n = tile_centroid[(lat, lon)]
            cen_lat = s_lat / n
            cen_lon = s_lon / n
            feats.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [float(cen_lon), float(cen_lat)]},
                "properties": {
                    "label": "HOTSPOT",
                    "count_7d": int(cnt),
                    "users_7d": int(users),
                    "top_category": report_type if report_type in ("illegal_dumping","volunteer_works") else "mixed"
                }
            })

    return jsonify({"type": "FeatureCollection", "features": feats, "since_days": days})

# ----------------------------
# Keep your existing endpoints
# ----------------------------
@bp_hotspots.route("/dzongkhags")
@login_required
def dzongkhags():
    if not _is_admin():
        abort(403)
    names = ["all", "thimphu", "paro", "punakha", "wangdue", "chukha"]
    return jsonify({"dzongkhags": names})

@bp_hotspots.route("/hotspots")
@login_required
def hotspots_admin_legacy():
    if not _is_admin():
        abort(403)

    days = int(request.args.get("days", 30))
    report_type = request.args.get("type", "all")
    dzongkhag = request.args.get("dzongkhag", "all")

    since = datetime.utcnow() - timedelta(days=days)
    q = Submission.query
    q = _apply_common_filters(q, since, report_type=report_type, dzongkhag=dzongkhag)

    rows = q.all()
    bins = _aggregate_round(rows, decimals=4)  # finer bins for admins
    return jsonify({"bins": bins, "total": len(rows), "since_days": days})

@bp_hotspots.route("/public_hotspots")
@limiter.limit("10 per minute")
def hotspots_public():
    days = int(request.args.get("days", 30))
    report_type = request.args.get("type", "all")
    dzongkhag = request.args.get("dzongkhag", "all")

    # Delay last 24 hours to protect active reports
    since = datetime.utcnow() - timedelta(days=days, hours=24)
    until = datetime.utcnow() - timedelta(hours=24)

    q = Submission.query
    q = _apply_common_filters(q, since, until=until, report_type=report_type, dzongkhag=dzongkhag)

    rows = q.all()
    bins = _aggregate_round(rows, decimals=3)
    out = []
    for b in bins:
        out.append({
            "lat": _jitter(b["lat"]),
            "lon": _jitter(b["lon"]),
            "count": b["count"]
        })
    return jsonify({"bins": out, "total": len(rows), "since_days": days, "delayed": True})

# -----------------------------
# Admin CSV (investor-friendly)
# -----------------------------
@bp_hotspots.route("/export_csv")
@login_required
def export_csv():
    """
    Investor-safe CSV:
      - created_at_utc: ISO-8601 with 'Z'
      - created_at_thimphu: ISO-8601 with '+06:00' (or fixed +06:00 fallback)
      - approved_at_thimphu: ISO-8601 or blank
      - time_to_approval_min: numeric minutes between approval and creation (blank if not approved)
    """
    if not _is_admin():
        return jsonify({"error": "Admin only"}), 403

    since_days = int(request.args.get("days", 30))
    report_type = request.args.get("type", "all")
    dzongkhag = request.args.get("dzongkhag", "all")

    since = datetime.utcnow() - timedelta(days=since_days)
    q = Submission.query
    q = _apply_common_filters(q, since, report_type=report_type, dzongkhag=dzongkhag)

    rows = q.all()

    thimphu = _get_thimphu_tz()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id",
        "username",
        "report_type",
        "lat",
        "lon",
        "created_at_utc",
        "created_at_thimphu",
        "approved_at_thimphu",
        "time_to_approval_min",
        "points_awarded",
    ])

    for r in rows:
        # Treat DB naive datetimes as UTC (your app uses datetime.utcnow())
        created_utc = (r.created_at or datetime.utcnow()).replace(tzinfo=timezone.utc)
        created_iso_utc = created_utc.isoformat(timespec="seconds").replace("+00:00", "Z")
        created_local = created_utc.astimezone(thimphu)
        created_iso_local = created_local.isoformat(timespec="seconds")

        if r.approved_at:
            approved_utc = r.approved_at.replace(tzinfo=timezone.utc)
            approved_local = approved_utc.astimezone(thimphu)
            approved_iso_local = approved_local.isoformat(timespec="seconds")
            tta_minutes = round((approved_utc - created_utc).total_seconds() / 60.0, 1)
        else:
            approved_iso_local = ""
            tta_minutes = ""

        writer.writerow([
            r.id,
            r.user.username if r.user else "",
            r.report_type,
            r.lat,
            r.lon,
            created_iso_utc,       # e.g., 2025-11-01T13:42:17Z
            created_iso_local,     # e.g., 2025-11-01T19:42:17+06:00
            approved_iso_local,    # e.g., 2025-11-01T20:05:10+06:00
            tta_minutes,           # e.g., 23.5
            r.points_awarded
        ])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename=hotspots_{since_days}d.csv"}
    )

# -------------------------------------------------
# NEW: TILE DETAILS (admin) — click a bucket circle
# -------------------------------------------------
@bp_hotspots.route("/tile_details")
@login_required
def tile_details_admin():
    if not _is_admin():
        abort(403)

    try:
        lat = float(request.args.get("lat"))
        lon = float(request.args.get("lon"))
    except (TypeError, ValueError):
        return jsonify({"error": "lat & lon required"}), 400

    days = int(request.args.get("days", 14))
    report_type = request.args.get("type", "all")
    dzongkhag = request.args.get("dzongkhag", "all")

    since = datetime.utcnow() - timedelta(days=days)
    q = Submission.query
    q = _apply_common_filters(q, since, report_type=report_type, dzongkhag=dzongkhag)

    # Load rows then select those whose rounded tile matches
    rows = q.all()
    tgt_lat = _round_coord(lat, 3)
    tgt_lon = _round_coord(lon, 3)

    sel = []
    for r in rows:
        if r.lat is None or r.lon is None:
            continue
        if _round_coord(r.lat, 3) == tgt_lat and _round_coord(r.lon, 3) == tgt_lon:
            sel.append(r)

    total = len(sel)
    unique_reporters = len({r.user_id for r in sel if r.user_id})

    by_type = defaultdict(int)
    by_day = defaultdict(int)  # YYYY-MM-DD -> count
    for r in sel:
        by_type[r.report_type or "unknown"] += 1
        d = (r.created_at or datetime.utcnow()).date().isoformat()
        by_day[d] += 1

    # Sort by day ascending
    by_day_sorted = [{"date": k, "count": by_day[k]} for k in sorted(by_day.keys())]

    return jsonify({
        "ok": True,
        "tile_lat": float(tgt_lat),
        "tile_lon": float(tgt_lon),
        "total": int(total),
        "unique_reporters": int(unique_reporters),
        "by_type": by_type,
        "by_day": by_day_sorted,
        "since_days": days
    })

# ----------------------------------------------------
# NEW: TILE DETAILS (public) — privacy-safe & delayed
# ----------------------------------------------------
@bp_hotspots.route("/public_tile_details")
@limiter.limit("10 per minute")
def public_tile_details():
    try:
        lat = float(request.args.get("lat"))
        lon = float(request.args.get("lon"))
    except (TypeError, ValueError):
        return jsonify({"error": "lat & lon required"}), 400

    days = int(request.args.get("days", 30))
    report_type = request.args.get("type", "all")
    dzongkhag = request.args.get("dzongkhag", "all")

    since = datetime.utcnow() - timedelta(days=days, hours=24)
    until = datetime.utcnow() - timedelta(hours=24)

    q = Submission.query
    q = _apply_common_filters(q, since, until=until, report_type=report_type, dzongkhag=dzongkhag)

    rows = q.all()
    tgt_lat = _round_coord(lat, 3)
    tgt_lon = _round_coord(lon, 3)

    sel = []
    for r in rows:
        if r.lat is None or r.lon is None:
            continue
        if _round_coord(r.lat, 3) == tgt_lat and _round_coord(r.lon, 3) == tgt_lon:
            sel.append(r)

    total = len(sel)

    by_type = defaultdict(int)
    by_day = defaultdict(int)
    for r in sel:
        by_type[r.report_type or "unknown"] += 1
        d = (r.created_at or datetime.utcnow()).date().isoformat()
        by_day[d] += 1

    by_day_sorted = [{"date": k, "count": by_day[k]} for k in sorted(by_day.keys())]

    return jsonify({
        "ok": True,
        "tile_lat": float(tgt_lat),
        "tile_lon": float(tgt_lon),
        "total": int(total),
        # no unique_reporters in public
        "by_type": by_type,
        "by_day": by_day_sorted,
        "since_days": days,
        "delayed": True
    })
