from flask import Blueprint, render_template_string
from ..models import Test, Question, User, Batch

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def home():
    total_tests = Test.query.count()
    total_questions = Question.query.count()
    total_students = User.query.filter_by(role="student").count()
    total_batches = Batch.query.count()

    return render_template_string("""
    <!doctype html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>NEET Platform</title>
        <style>
            body {
                margin: 0;
                font-family: Arial, sans-serif;
                background: #0f172a;
                color: white;
                padding: 40px;
            }
            .wrap {
                max-width: 1100px;
                margin: 0 auto;
            }
            .hero {
                padding: 32px;
                background: #1e293b;
                border-radius: 18px;
                margin-bottom: 24px;
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
            <div class="hero">
                <h1>NEET Coaching Test Platform</h1>
                <p>Online test engine, question bank, analytics, and institute management.</p>
                <p><a href="/login">Login</a></p>
            </div>

            <div class="grid">
                <div class="card">
                    <div>Total Tests</div>
                    <div class="num">{{ total_tests }}</div>
                </div>
                <div class="card">
                    <div>Total Questions</div>
                    <div class="num">{{ total_questions }}</div>
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
    """, total_tests=total_tests, total_questions=total_questions, total_students=total_students, total_batches=total_batches)
