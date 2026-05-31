from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from ..extensions import db
from ..models import Batch, Test, Subject, Chapter, Question

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required():
    return current_user.is_authenticated and current_user.role in ["institute_admin", "super_admin", "teacher"]


def get_question_or_404(question_id):
    return Question.query.filter_by(
        id=question_id,
        institute_id=current_user.institute_id
    ).first_or_404()


@admin_bp.route("/batches", methods=["GET", "POST"])
@login_required
def batches():
    if not admin_required():
        flash("Access denied.", "danger")
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        batch = Batch(
            institute_id=current_user.institute_id,
            name=request.form.get("name", "").strip(),
            academic_year=request.form.get("academic_year", "2026-27").strip(),
        )
        db.session.add(batch)
        db.session.commit()
        flash("Batch created.", "success")
        return redirect(url_for("admin.batches"))

    batches = (
        Batch.query.filter_by(institute_id=current_user.institute_id)
        .order_by(Batch.created_at.desc())
        .all()
    )
    return render_template("batches.html", batches=batches)


@admin_bp.route("/tests")
@login_required
def tests():
    if not admin_required():
        flash("Access denied.", "danger")
        return redirect(url_for("main.dashboard"))

    tests = (
        Test.query.filter_by(institute_id=current_user.institute_id)
        .order_by(Test.created_at.desc())
        .all()
    )
    return render_template("tests.html", tests=tests)


@admin_bp.route("/questions")
@login_required
def questions():
    if not admin_required():
        flash("Access denied.", "danger")
        return redirect(url_for("main.dashboard"))

    q = request.args.get("q", "").strip()
    subject_id = request.args.get("subject_id", "").strip()
    chapter_id = request.args.get("chapter_id", "").strip()
    difficulty = request.args.get("difficulty", "").strip()

    query = Question.query.filter_by(institute_id=current_user.institute_id)

    if q:
        query = query.filter(Question.stem.ilike(f"%{q}%"))
    if subject_id.isdigit():
        query = query.filter(Question.subject_id == int(subject_id))
    if chapter_id.isdigit():
        query = query.filter(Question.chapter_id == int(chapter_id))
    if difficulty:
        query = query.filter(Question.difficulty_level == difficulty)

    questions = query.order_by(Question.created_at.desc()).all()

    subjects = Subject.query.order_by(Subject.name.asc()).all()
    chapters = Chapter.query.order_by(Chapter.name.asc()).all()

    stats = {
        "total": Question.query.filter_by(institute_id=current_user.institute_id).count(),
        "easy": Question.query.filter_by(institute_id=current_user.institute_id, difficulty_level="easy").count(),
        "medium": Question.query.filter_by(institute_id=current_user.institute_id, difficulty_level="medium").count(),
        "hard": Question.query.filter_by(institute_id=current_user.institute_id, difficulty_level="hard").count(),
    }

    filters = {
        "q": q,
        "subject_id": subject_id,
        "chapter_id": chapter_id,
        "difficulty": difficulty,
    }

    return render_template(
        "questions.html",
        questions=questions,
        subjects=subjects,
        chapters=chapters,
        filters=filters,
        stats=stats,
    )


@admin_bp.route("/questions/new", methods=["GET", "POST"])
@login_required
def create_question():
    if not admin_required():
        flash("Access denied.", "danger")
        return redirect(url_for("main.dashboard"))

    subjects = Subject.query.order_by(Subject.name.asc()).all()
    chapters = Chapter.query.order_by(Chapter.name.asc()).all()

    if request.method == "POST":
        question = Question(
            institute_id=current_user.institute_id,
            subject_id=int(request.form.get("subject_id")),
            chapter_id=int(request.form.get("chapter_id")),
            stem=request.form.get("stem", "").strip(),
            option_a=request.form.get("option_a", "").strip(),
            option_b=request.form.get("option_b", "").strip(),
            option_c=request.form.get("option_c", "").strip(),
            option_d=request.form.get("option_d", "").strip(),
            correct_option=request.form.get("correct_option", "").strip().upper(),
            explanation=request.form.get("explanation", "").strip(),
            difficulty_level=request.form.get("difficulty_level", "medium").strip(),
        )

        db.session.add(question)
        db.session.commit()
        flash("Question created successfully.", "success")
        return redirect(url_for("admin.questions"))

    return render_template(
        "question_form.html",
        subjects=subjects,
        chapters=chapters,
        question=None,
        page_title="Create Question",
        submit_label="Save Question",
    )


@admin_bp.route("/questions/<int:question_id>/edit", methods=["GET", "POST"])
@login_required
def edit_question(question_id):
    if not admin_required():
        flash("Access denied.", "danger")
        return redirect(url_for("main.dashboard"))

    question = get_question_or_404(question_id)
    subjects = Subject.query.order_by(Subject.name.asc()).all()
    chapters = Chapter.query.order_by(Chapter.name.asc()).all()

    if request.method == "POST":
        question.subject_id = int(request.form.get("subject_id"))
        question.chapter_id = int(request.form.get("chapter_id"))
        question.stem = request.form.get("stem", "").strip()
        question.option_a = request.form.get("option_a", "").strip()
        question.option_b = request.form.get("option_b", "").strip()
        question.option_c = request.form.get("option_c", "").strip()
        question.option_d = request.form.get("option_d", "").strip()
        question.correct_option = request.form.get("correct_option", "").strip().upper()
        question.explanation = request.form.get("explanation", "").strip()
        question.difficulty_level = request.form.get("difficulty_level", "medium").strip()

        db.session.commit()
        flash("Question updated successfully.", "success")
        return redirect(url_for("admin.questions"))

    return render_template(
        "question_form.html",
        subjects=subjects,
        chapters=chapters,
        question=question,
        page_title="Edit Question",
        submit_label="Update Question",
    )


@admin_bp.route("/questions/<int:question_id>/delete", methods=["POST"])
@login_required
def delete_question(question_id):
    if not admin_required():
        flash("Access denied.", "danger")
        return redirect(url_for("main.dashboard"))

    question = get_question_or_404(question_id)
    db.session.delete(question)
    db.session.commit()
    flash("Question deleted.", "info")
    return redirect(url_for("admin.questions"))
