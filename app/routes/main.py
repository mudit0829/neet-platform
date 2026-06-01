from flask import Blueprint, render_template
from sqlalchemy.exc import SQLAlchemyError
from ..models import Test, Question, User, Batch

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def home():
    try:
        stats = {
            "tests": Test.query.count(),
            "questions": Question.query.count(),
            "students": User.query.filter_by(role="student").count(),
            "batches": Batch.query.count(),
        }
        db_ready = True
    except SQLAlchemyError:
        stats = {
            "tests": 0,
            "questions": 0,
            "students": 0,
            "batches": 0,
        }
        db_ready = False

    return render_template("home.html", stats=stats, db_ready=db_ready)
