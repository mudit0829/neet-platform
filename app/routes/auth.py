from flask import Blueprint, request, redirect, url_for, flash, render_template
from flask_login import login_user, logout_user, login_required
from ..extensions import db
from ..models import User

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for("admin.dashboard"))

        flash("Invalid email or password", "danger")

    return render_template("login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


@auth_bp.route("/setup", methods=["GET", "POST"])
def setup():
    existing_admin = User.query.filter_by(role="admin").first()
    if existing_admin:
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not full_name or not email or not password:
            flash("All fields are required", "danger")
        elif User.query.filter_by(email=email).first():
            flash("Email already exists", "danger")
        else:
            user = User(
                full_name=full_name,
                email=email,
                role="admin",
                institute_id=None
            )
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash("Admin account created. Please login.", "success")
            return redirect(url_for("auth.login"))

    return render_template("setup.html")
