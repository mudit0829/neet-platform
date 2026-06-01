from flask import Blueprint, render_template
from flask_login import login_required, current_user
from ..models import Question, Test, User, Batch

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
