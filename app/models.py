from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from .extensions import db, login_manager


class TimestampMixin:
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )


class Institute(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    slug = db.Column(db.String(150), unique=True, nullable=False)
    status = db.Column(db.String(20), default="active")


class User(UserMixin, TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    institute_id = db.Column(db.Integer, db.ForeignKey("institute.id"), nullable=True)
    full_name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="student")
    is_active_user = db.Column(db.Boolean, default=True)

    institute = db.relationship("Institute", backref=db.backref("users", lazy=True))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Batch(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    institute_id = db.Column(db.Integer, db.ForeignKey("institute.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    academic_year = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), default="active")


class Subject(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)


class Chapter(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subject.id"), nullable=False)
    name = db.Column(db.String(150), nullable=False)

    subject = db.relationship("Subject", backref=db.backref("chapters", lazy=True))


class Question(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    institute_id = db.Column(db.Integer, db.ForeignKey("institute.id"), nullable=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subject.id"), nullable=False)
    chapter_id = db.Column(db.Integer, db.ForeignKey("chapter.id"), nullable=False)
    stem = db.Column(db.Text, nullable=False)
    option_a = db.Column(db.String(255), nullable=False)
    option_b = db.Column(db.String(255), nullable=False)
    option_c = db.Column(db.String(255), nullable=False)
    option_d = db.Column(db.String(255), nullable=False)
    correct_option = db.Column(db.String(1), nullable=False)
    explanation = db.Column(db.Text, nullable=True)
    difficulty_level = db.Column(db.String(20), default="medium")

    subject = db.relationship("Subject", backref=db.backref("questions", lazy=True))
    chapter = db.relationship("Chapter", backref=db.backref("questions", lazy=True))


class Test(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    institute_id = db.Column(db.Integer, db.ForeignKey("institute.id"), nullable=True)
    title = db.Column(db.String(200), nullable=False)
    test_type = db.Column(db.String(30), default="chapter")
    duration_minutes = db.Column(db.Integer, default=180)
    total_marks = db.Column(db.Integer, default=720)
    negative_marks = db.Column(db.Float, default=1.0)
    status = db.Column(db.String(20), default="draft")


class TestQuestion(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    test_id = db.Column(db.Integer, db.ForeignKey("test.id"), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey("question.id"), nullable=False)
    display_order = db.Column(db.Integer, nullable=False)
    marks = db.Column(db.Float, default=4.0)
    negative_marks = db.Column(db.Float, default=1.0)

    test = db.relationship(
        "Test",
        backref=db.backref("test_questions", lazy=True, cascade="all, delete-orphan")
    )
    question = db.relationship("Question", backref=db.backref("test_links", lazy=True))


class TestAttempt(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    test_id = db.Column(db.Integer, db.ForeignKey("test.id"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    status = db.Column(db.String(20), default="ongoing")
    total_score = db.Column(db.Float, default=0.0)
    correct_count = db.Column(db.Integer, default=0)
    wrong_count = db.Column(db.Integer, default=0)
    skipped_count = db.Column(db.Integer, default=0)

    test = db.relationship("Test", backref=db.backref("attempts", lazy=True))
    student = db.relationship("User", backref=db.backref("attempts", lazy=True))


class AttemptAnswer(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    attempt_id = db.Column(db.Integer, db.ForeignKey("test_attempt.id"), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey("question.id"), nullable=False)
    selected_option = db.Column(db.String(1), nullable=True)
    is_marked_for_review = db.Column(db.Boolean, default=False)
    time_spent_seconds = db.Column(db.Integer, default=0)

    attempt = db.relationship(
        "TestAttempt",
        backref=db.backref("answers", lazy=True, cascade="all, delete-orphan")
    )
    question = db.relationship("Question", backref=db.backref("attempt_answers", lazy=True))


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
