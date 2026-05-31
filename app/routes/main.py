from flask import Blueprint, render_template
from flask_login import login_required, current_user
from ..models import Test, Question, User, Batch

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def home():
    stats = {
        "students": User.query.filter_by(role="student").count(),
        "tests": Test.query.count(),
        "questions": Question.query.count(),
        "batches": Batch.query.count(),
    }
    return render_template("home.html", stats=stats)


@main_bp.route("/dashboard")
@login_required
def dashboard():
    institute_id = current_user.institute_id

    dashboard_stats = {
        "students": User.query.filter_by(institute_id=institute_id, role="student").count() if institute_id else 0,
        "teachers": User.query.filter_by(institute_id=institute_id, role="teacher").count() if institute_id else 0,
        "tests": Test.query.filter_by(institute_id=institute_id).count() if institute_id else 0,
        "questions": Question.query.filter_by(institute_id=institute_id).count() if institute_id else 0,
    }

    recent_tests = (
        Test.query.filter_by(institute_id=institute_id)
        .order_by(Test.created_at.desc())
        .limit(5)
        .all()
        if institute_id else []
    )

    recent_questions = (
        Question.query.filter_by(institute_id=institute_id)
        .order_by(Question.created_at.desc())
        .limit(5)
        .all()
        if institute_id else []
    )

    return render_template(
        "dashboard.html",
        current_user=current_user,
        dashboard_stats=dashboard_stats,
        recent_tests=recent_tests,
        recent_questions=recent_questions,
    )
