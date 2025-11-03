# routes/supw.py
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import asc
import random

from models import db, User, SupwPlace, SupwAssignment

bp_supw = Blueprint("bp_supw", __name__)

# --- helpers ---
def admin_required():
    return current_user.is_authenticated and getattr(current_user, "role", "") == "admin"

# -------------------
# USER: My assignments
# -------------------
@bp_supw.route("/supw")
@login_required
def supw_my():
    assigns = (SupwAssignment
               .query
               .filter_by(user_id=current_user.id)
               .join(SupwPlace, SupwAssignment.place_id == SupwPlace.id)
               .order_by(asc(SupwPlace.name))
               .all())
    return render_template("supw_user.html", assignments=assigns)

# -------------------
# ADMIN: Manage SUPW
# -------------------
@bp_supw.route("/admin/supw", methods=["GET"])
@login_required
def supw_admin():
    if not admin_required():
        flash("Admin only")
        return redirect(url_for("index"))

    users = User.query.order_by(asc(User.username)).all()
    places = SupwPlace.query.order_by(asc(SupwPlace.name)).all()

    # current assignments grouped by place
    by_place = {}
    for p in places:
        by_place[p.id] = {
            "place": p,
            "users": [a.user for a in p.assignments]
        }

    return render_template("supw_admin.html",
                           users=users,
                           places=places,
                           by_place=by_place)

# ---- Place CRUD ----
@bp_supw.route("/admin/supw/place/create", methods=["POST"])
@login_required
def supw_place_create():
    if not admin_required():
        flash("Admin only")
        return redirect(url_for("index"))

    name = (request.form.get("name") or "").strip()
    desc = (request.form.get("description") or "").strip()
    if not name:
        flash("Place name required.")
        return redirect(url_for("bp_supw.supw_admin"))

    if SupwPlace.query.filter_by(name=name).first():
        flash("Place with that name already exists.")
        return redirect(url_for("bp_supw.supw_admin"))

    p = SupwPlace(name=name, description=desc, active=True)
    db.session.add(p); db.session.commit()
    flash("Place created.")
    return redirect(url_for("bp_supw.supw_admin"))

@bp_supw.route("/admin/supw/place/<int:pid>/update", methods=["POST"])
@login_required
def supw_place_update(pid):
    if not admin_required():
        flash("Admin only")
        return redirect(url_for("index"))

    p = SupwPlace.query.get_or_404(pid)
    p.name = (request.form.get("name") or p.name).strip()
    p.description = (request.form.get("description") or p.description).strip()
    p.active = True if request.form.get("active", "1") == "1" else False
    db.session.commit()
    flash("Place updated.")
    return redirect(url_for("bp_supw.supw_admin"))

@bp_supw.route("/admin/supw/place/<int:pid>/delete", methods=["POST"])
@login_required
def supw_place_delete(pid):
    if not admin_required():
        flash("Admin only")
        return redirect(url_for("index"))

    p = SupwPlace.query.get_or_404(pid)
    db.session.delete(p); db.session.commit()
    flash("Place deleted.")
    return redirect(url_for("bp_supw.supw_admin"))

# ---- Manual assign: assign selected users to ONE place (adds, avoids dup) ----
@bp_supw.route("/admin/supw/assign/manual", methods=["POST"])
@login_required
def supw_assign_manual():
    if not admin_required():
        flash("Admin only")
        return redirect(url_for("index"))

    place_id = int(request.form.get("place_id", "0"))
    user_ids = request.form.getlist("user_ids")
    if not place_id or not user_ids:
        flash("Select a place and at least one user.")
        return redirect(url_for("bp_supw.supw_admin"))

    p = SupwPlace.query.get_or_404(place_id)
    inserted = 0
    for uid in user_ids:
        try:
            uid = int(uid)
            if not SupwAssignment.query.filter_by(place_id=p.id, user_id=uid).first():
                db.session.add(SupwAssignment(place_id=p.id, user_id=uid))
                inserted += 1
        except Exception:
            pass
    db.session.commit()
    flash(f"Assigned {inserted} user(s) to {p.name}.")
    return redirect(url_for("bp_supw.supw_admin"))

# ---- Random distribute: spread selected (or all) users across SELECTED places ----
@bp_supw.route("/admin/supw/assign/random", methods=["POST"])
@login_required
def supw_assign_random():
    if not admin_required():
        flash("Admin only")
        return redirect(url_for("index"))

    mode_all = request.form.get("all_users") == "1"
    user_ids = []
    if mode_all:
        # all non-admin users
        user_ids = [u.id for u in User.query.filter(User.role != "admin").all()]
    else:
        user_ids = [int(x) for x in request.form.getlist("user_ids")]

    place_ids = [int(x) for x in request.form.getlist("place_ids")]

    if not user_ids or not place_ids:
        flash("Pick at least one user and one place (or select 'All users').")
        return redirect(url_for("bp_supw.supw_admin"))

    random.shuffle(user_ids)
    placed = 0
    i = 0
    for uid in user_ids:
        pid = place_ids[i % len(place_ids)]
        if not SupwAssignment.query.filter_by(place_id=pid, user_id=uid).first():
            db.session.add(SupwAssignment(place_id=pid, user_id=uid))
            placed += 1
        i += 1
    db.session.commit()
    flash(f"Randomly assigned {placed} user(s) across {len(place_ids)} place(s).")
    return redirect(url_for("bp_supw.supw_admin"))

# ---- Unassign a user from a place ----
@bp_supw.route("/admin/supw/unassign/<int:aid>", methods=["POST"])
@login_required
def supw_unassign(aid):
    if not admin_required():
        flash("Admin only")
        return redirect(url_for("index"))
    a = SupwAssignment.query.get_or_404(aid)
    db.session.delete(a); db.session.commit()
    flash("Unassigned.")
    return redirect(url_for("bp_supw.supw_admin"))
