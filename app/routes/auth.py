from flask import Blueprint, request, redirect, url_for, flash, render_template
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy import or_

from ..extensions import db, login_manager
from ..models import User

auth_bp = Blueprint("auth", __name__)


@login_manager.unauthorized_handler
def unauthorized():
    flash("Please login to continue.", "warning")
    return redirect(url_for("auth.login"))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        if current_user.role == "admin":
            return redirect(url_for("admin.dashboard"))
        if current_user.role == "student":
            return redirect(url_for("student.dashboard"))
        return redirect(url_for("auth.logout"))

    if request.method == "POST":
        login_input = (request.form.get("login", "") or "").strip()
        password = request.form.get("password", "")

        if not login_input or not password:
            flash("Username/email and password are required.", "danger")
            return render_template("login.html")

        user = User.query.filter(
            or_(
                User.email == login_input.lower(),
                User.username == login_input
            )
        ).first()

        if not user or not user.check_password(password):
            flash("Invalid login credentials.", "danger")
            return render_template("login.html")

        if not user.is_active_user:
            flash("This account is inactive. Please contact admin.", "danger")
            return render_template("login.html")

        login_user(user)

        if user.role == "admin":
            return redirect(url_for("admin.dashboard"))
        if user.role == "student":
            return redirect(url_for("student.dashboard"))

        flash("Unknown role assigned to this account.", "danger")
        logout_user()
        return render_template("login.html")

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
                username=None,
                role="admin",
                institute_id=None
            )
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash("Admin account created. Please login.", "success")
            return redirect(url_for("auth.login"))

    return render_template("setup.html")
