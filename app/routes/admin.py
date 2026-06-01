from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from ..models import Question, Test, User, Batch
from ..extensions import db

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.route("/")
@login_required
def dashboard():
    stats = {
        "questions": Question.query.count(),
        "tests": Test.query.count(),
        "students": User.query.filter_by(role="student").count(),
        "batches": Batch.query.count(),
    }

    recent_activity = [
        "New admin workspace initialized",
        "Core NEET subjects seeded",
        "Database schema created successfully",
        "Platform ready for question bank module",
    ]

    upcoming_modules = [
        "Question Bank",
        "Test Builder",
        "Student Panel",
        "Analytics",
    ]

    return render_template(
        "admin_dashboard.html",
        current_user=current_user,
        stats=stats,
        recent_activity=recent_activity,
        upcoming_modules=upcoming_modules,
    )


@admin_bp.route("/questions", methods=["GET", "POST"])
@login_required
def questions_page():
    if request.method == "POST":
        try:
            question_text = request.form.get("question_text", "").strip()
            subject = request.form.get("subject", "").strip()
            chapter = request.form.get("chapter", "").strip()
            topic = request.form.get("topic", "").strip()

            option_a = request.form.get("option_a", "").strip()
            option_b = request.form.get("option_b", "").strip()
            option_c = request.form.get("option_c", "").strip()
            option_d = request.form.get("option_d", "").strip()

            correct_option = request.form.get("correct_option", "").strip().upper()
            explanation = request.form.get("explanation", "").strip()

            marks = request.form.get("marks", "4").strip()
            negative_marks = request.form.get("negative_marks", "1").strip()
            is_active = True if request.form.get("is_active") == "on" else False

            if not question_text:
                flash("Question text is required.", "danger")
                return redirect(url_for("admin.questions_page"))

            if correct_option not in ["A", "B", "C", "D"]:
                flash("Correct option must be A, B, C, or D.", "danger")
                return redirect(url_for("admin.questions_page"))

            question = Question(
                question_text=question_text,
                subject=subject,
                chapter=chapter,
                topic=topic,
                option_a=option_a,
                option_b=option_b,
                option_c=option_c,
                option_d=option_d,
                correct_option=correct_option,
                explanation=explanation,
                marks=float(marks or 4),
                negative_marks=float(negative_marks or 1),
                is_active=is_active,
            )

            db.session.add(question)
            db.session.commit()
            flash("Question added successfully.", "success")

        except Exception as e:
            db.session.rollback()
            flash(f"Error adding question: {str(e)}", "danger")

        return redirect(url_for("admin.questions_page"))

    questions = Question.query.order_by(Question.id.desc()).all()
    return render_template("admin_questions.html", questions=questions)


@admin_bp.route("/students")
@login_required
def students_page():
    students = User.query.filter_by(role="student").order_by(User.id.desc()).all()
    return render_template("admin_students.html", students=students)


@admin_bp.route("/tests")
@login_required
def tests_page():
    tests = Test.query.order_by(Test.id.desc()).all()
    return render_template("admin_tests.html", tests=tests)
