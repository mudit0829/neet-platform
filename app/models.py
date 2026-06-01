from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from ..models import Question, Test, User, Batch, Subject, Chapter
from ..extensions import db

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required():
    if not current_user.is_authenticated:
        abort(401)
    if getattr(current_user, "role", "") != "admin":
        abort(403)


@admin_bp.route("/")
@login_required
def dashboard():
    admin_required()

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
    admin_required()

    if request.method == "POST":
        try:
            subject_id = request.form.get("subject_id", type=int)
            chapter_id = request.form.get("chapter_id", type=int)
            stem = (request.form.get("stem") or "").strip()
            option_a = (request.form.get("option_a") or "").strip()
            option_b = (request.form.get("option_b") or "").strip()
            option_c = (request.form.get("option_c") or "").strip()
            option_d = (request.form.get("option_d") or "").strip()
            correct_option = (request.form.get("correct_option") or "").strip().upper()
            explanation = (request.form.get("explanation") or "").strip()
            difficulty_level = (request.form.get("difficulty_level") or "medium").strip().lower()

            if not subject_id:
                flash("Subject is required.", "danger")
                return redirect(url_for("admin.questions_page"))

            if not chapter_id:
                flash("Chapter is required.", "danger")
                return redirect(url_for("admin.questions_page"))

            if not stem:
                flash("Question text is required.", "danger")
                return redirect(url_for("admin.questions_page"))

            if not option_a or not option_b or not option_c or not option_d:
                flash("All four options are required.", "danger")
                return redirect(url_for("admin.questions_page"))

            if correct_option not in ["A", "B", "C", "D"]:
                flash("Correct option must be A, B, C, or D.", "danger")
                return redirect(url_for("admin.questions_page"))

            subject = Subject.query.get(subject_id)
            chapter = Chapter.query.get(chapter_id)

            if not subject:
                flash("Selected subject does not exist.", "danger")
                return redirect(url_for("admin.questions_page"))

            if not chapter:
                flash("Selected chapter does not exist.", "danger")
                return redirect(url_for("admin.questions_page"))

            if chapter.subject_id != subject.id:
                flash("Selected chapter does not belong to the chosen subject.", "danger")
                return redirect(url_for("admin.questions_page"))

            if difficulty_level not in ["easy", "medium", "hard"]:
                difficulty_level = "medium"

            question = Question(
                institute_id=current_user.institute_id,
                subject_id=subject_id,
                chapter_id=chapter_id,
                stem=stem,
                option_a=option_a,
                option_b=option_b,
                option_c=option_c,
                option_d=option_d,
                correct_option=correct_option,
                explanation=explanation if explanation else None,
                difficulty_level=difficulty_level,
            )

            db.session.add(question)
            db.session.commit()
            flash("Question added successfully.", "success")

        except Exception as e:
            db.session.rollback()
            flash(f"Error adding question: {str(e)}", "danger")

        return redirect(url_for("admin.questions_page"))

    subjects = Subject.query.order_by(Subject.name.asc()).all()
    chapters = Chapter.query.order_by(Chapter.name.asc()).all()
    questions = Question.query.order_by(Question.id.desc()).all()

    return render_template(
        "admin_questions.html",
        subjects=subjects,
        chapters=chapters,
        questions=questions,
    )


@admin_bp.route("/students")
@login_required
def students_page():
    admin_required()

    students = User.query.filter_by(role="student").order_by(User.id.desc()).all()
    return render_template("admin_students.html", students=students)


@admin_bp.route("/tests")
@login_required
def tests_page():
    admin_required()

    tests = Test.query.order_by(Test.id.desc()).all()
    return render_template("admin_tests.html", tests=tests)
