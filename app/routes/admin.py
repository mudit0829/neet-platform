from flask import Blueprint, render_template_string
from flask_login import login_required, current_user
from ..models import Question, Test, User, Batch

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.route("/")
@login_required
def dashboard():
    total_questions = Question.query.count()
    total_tests = Test.query.count()
    total_students = User.query.filter_by(role="student").count()
    total_batches = Batch.query.count()

    return render_template_string("""
    <!doctype html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Admin Dashboard</title>
        <style>
            body {
                margin: 0;
                font-family: Arial, sans-serif;
                background: #0f172a;
                color: white;
                padding: 32px;
            }
            .wrap {
                max-width: 1100px;
                margin: 0 auto;
            }
            .top {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 24px;
                gap: 16px;
                flex-wrap: wrap;
            }
            .grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
                gap: 16px;
            }
            .card {
                background: #1e293b;
                padding: 24px;
                border-radius: 18px;
            }
            .num {
                font-size: 32px;
                font-weight: 700;
                margin-top: 10px;
            }
            a {
                color: #93c5fd;
                text-decoration: none;
            }
        </style>
    </head>
    <body>
        <div class="wrap">
            <div class="top">
                <div>
                    <h1>Admin Dashboard</h1>
                    <p>Welcome, {{ current_user.full_name }}</p>
                </div>
                <div>
                    <a href="/">Home</a> |
                    <a href="/logout">Logout</a>
                </div>
            </div>

            <div class="grid">
                <div class="card">
                    <div>Total Questions</div>
                    <div class="num">{{ total_questions }}</div>
                </div>
                <div class="card">
                    <div>Total Tests</div>
                    <div class="num">{{ total_tests }}</div>
                </div>
                <div class="card">
                    <div>Total Students</div>
                    <div class="num">{{ total_students }}</div>
                </div>
                <div class="card">
                    <div>Total Batches</div>
                    <div class="num">{{ total_batches }}</div>
                </div>
            </div>
        </div>
    </body>
    </html>
    """, current_user=current_user, total_questions=total_questions, total_tests=total_tests, total_students=total_students, total_batches=total_batches)
