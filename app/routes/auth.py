from flask import Blueprint, request, redirect, url_for, flash, render_template_string
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
            return redirect(url_for("main.home"))

        flash("Invalid email or password", "danger")

    return render_template_string("""
    <!doctype html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Login</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                background: #0f172a;
                color: white;
                display: flex;
                justify-content: center;
                align-items: center;
                min-height: 100vh;
                margin: 0;
            }
            .box {
                width: 100%;
                max-width: 420px;
                background: #1e293b;
                padding: 28px;
                border-radius: 18px;
            }
            input {
                width: 100%;
                padding: 12px;
                margin: 8px 0 14px;
                border-radius: 10px;
                border: none;
                box-sizing: border-box;
            }
            button {
                width: 100%;
                padding: 12px;
                border: none;
                border-radius: 10px;
                background: #2563eb;
                color: white;
                font-weight: bold;
                cursor: pointer;
            }
            a { color: #93c5fd; }
            .flash { margin-bottom: 12px; color: #fca5a5; }
        </style>
    </head>
    <body>
        <form class="box" method="post">
            <h1>Login</h1>
            {% with messages = get_flashed_messages(with_categories=true) %}
              {% if messages %}
                {% for category, message in messages %}
                  <div class="flash">{{ message }}</div>
                {% endfor %}
              {% endif %}
            {% endwith %}
            <label>Email</label>
            <input type="email" name="email" required>
            <label>Password</label>
            <input type="password" name="password" required>
            <button type="submit">Sign in</button>
            <p style="margin-top:16px;">Need first admin? <a href="/setup">Create account</a></p>
        </form>
    </body>
    </html>
    """)


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

    return render_template_string("""
    <!doctype html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Setup Admin</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                background: #0f172a;
                color: white;
                display: flex;
                justify-content: center;
                align-items: center;
                min-height: 100vh;
                margin: 0;
            }
            .box {
                width: 100%;
                max-width: 460px;
                background: #1e293b;
                padding: 28px;
                border-radius: 18px;
            }
            input {
                width: 100%;
                padding: 12px;
                margin: 8px 0 14px;
                border-radius: 10px;
                border: none;
                box-sizing: border-box;
            }
            button {
                width: 100%;
                padding: 12px;
                border: none;
                border-radius: 10px;
                background: #16a34a;
                color: white;
                font-weight: bold;
                cursor: pointer;
            }
            .flash { margin-bottom: 12px; color: #fca5a5; }
        </style>
    </head>
    <body>
        <form class="box" method="post">
            <h1>Create First Admin</h1>
            {% with messages = get_flashed_messages(with_categories=true) %}
              {% if messages %}
                {% for category, message in messages %}
                  <div class="flash">{{ message }}</div>
                {% endfor %}
              {% endif %}
            {% endwith %}
            <label>Full name</label>
            <input type="text" name="full_name" required>
            <label>Email</label>
            <input type="email" name="email" required>
            <label>Password</label>
            <input type="password" name="password" required>
            <button type="submit">Create admin</button>
        </form>
    </body>
    </html>
    """)
