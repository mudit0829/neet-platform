import os
import uuid
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, abort
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from ..models import (
    Question,
    Test,
    TestQuestion,
    User,
    Batch,
    Subject,
    Chapter,
    StudentProfile,
    TestAttempt,
)
from ..extensions import db

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}


def admin_required():
    if not current_user.is_authenticated:
        abort(401)
    if getattr(current_user, "role", "") != "admin":
        abort(403)


def allowed_image_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


def save_uploaded_image(file_storage, subfolder="questions"):
    if not file_storage or not file_storage.filename:
        return None

    if not allowed_image_file(file_storage.filename):
        return None

    original_name = secure_filename(file_storage.filename)
    ext = original_name.rsplit(".", 1)[1].lower()
    new_filename = f"{uuid.uuid4().hex}.{ext}"

    upload_dir = os.path.join(current_app.root_path, "static", "uploads", subfolder)
    os.makedirs(upload_dir, exist_ok=True)

    save_path = os.path.join(upload_dir, new_filename)
    file_storage.save(save_path)

    return f"uploads/{subfolder}/{new_filename}"


def utc_now():
    return datetime.utcnow()


def parse_datetime_local(value):
    value = (value or "").strip()
    if not value:
        return None

    for fmt in ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"]:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue

    return None


def get_test_subject_counts(test):
    subject_counts = {
        "Physics": 0,
        "Chemistry": 0,
        "Biology": 0,
    }

    total_questions = 0
    total_selected_marks = 0.0

    for item in test.test_questions:
        total_questions += 1
        total_selected_marks += float(item.marks or 0)

        if item.question and item.question.subject:
            subject_name = (item.question.subject.name or "").strip()
            if subject_name in subject_counts:
                subject_counts[subject_name] += 1

    return subject_counts, total_questions, total_selected_marks


def validate_test_publishable(test):
    subject_counts, total_questions, _ = get_test_subject_counts(test)

    test_mode = (getattr(test, "test_mode", "custom") or "custom").strip().lower()
    schedule_type = (getattr(test, "schedule_type", "instant") or "instant").strip().lower()

    if total_questions <= 0:
        return False, "Cannot publish. Add at least 1 question first."

    if test_mode == "neet_full":
        if (
            subject_counts["Physics"] < 45 or
            subject_counts["Chemistry"] < 45 or
            subject_counts["Biology"] < 90
        ):
            return False, "Cannot publish. Required minimum: Physics 45, Chemistry 45, Biology 90."

    if schedule_type == "fixed_start":
        if not getattr(test, "start_at", None):
            return False, "Cannot publish. Start time is required for fixed start tests."
        if getattr(test, "end_at", None) and test.end_at <= test.start_at:
            return False, "Cannot publish. End time must be after start time."

    elif schedule_type == "window":
        if not getattr(test, "start_at", None) or not getattr(test, "end_at", None):
            return False, "Cannot publish. Start time and end time are required for window tests."
        if test.end_at <= test.start_at:
            return False, "Cannot publish. End time must be after start time."
        exam_duration_seconds = int((test.duration_minutes or 0) * 60)
        window_seconds = int((test.end_at - test.start_at).total_seconds())
        if window_seconds <= 0:
            return False, "Cannot publish. Invalid test window."
        if exam_duration_seconds > window_seconds:
            return False, "Cannot publish. Duration cannot be longer than the available window."

    return True, "Test is publishable."


@admin_bp.route("/")
@login_required
def dashboard():
    admin_required()

    stats = {
        "questions": Question.query.count(),
        "tests": Test.query.count(),
        "students": User.query.filter_by(role="student").count(),
        "batches": Batch.query.count(),
        "subjects": Subject.query.count(),
        "chapters": Chapter.query.count(),
    }

    recent_activity = [
        "Admin workspace loaded successfully",
        "Question bank module is active",
        "Test builder is available",
        "Academic setup can be expanded from sidebar",
    ]

    quick_actions = [
        {"label": "Add Batch", "url": url_for("admin.batches_page")},
        {"label": "Add Subject", "url": url_for("admin.subjects_page")},
        {"label": "Add Chapter", "url": url_for("admin.chapters_page")},
        {"label": "Create Test", "url": url_for("admin.tests_page")},
    ]

    latest_tests = Test.query.order_by(Test.id.desc()).limit(5).all()
    latest_questions = Question.query.order_by(Question.id.desc()).limit(5).all()

    return render_template(
        "admin_dashboard.html",
        current_user=current_user,
        stats=stats,
        recent_activity=recent_activity,
        quick_actions=quick_actions,
        latest_tests=latest_tests,
        latest_questions=latest_questions,
    )


@admin_bp.route("/batches", methods=["GET", "POST"])
@login_required
def batches_page():
    admin_required()

    if request.method == "POST":
        try:
            name = (request.form.get("name") or "").strip()
            academic_year = (request.form.get("academic_year") or "").strip()
            status = (request.form.get("status") or "active").strip().lower()

            if not name:
                flash("Batch name is required.", "danger")
                return redirect(url_for("admin.batches_page"))

            if not academic_year:
                flash("Academic year is required.", "danger")
                return redirect(url_for("admin.batches_page"))

            if status not in ["active", "inactive"]:
                status = "active"

            if not getattr(current_user, "institute_id", None):
                flash("Your admin account is not linked to any institute. Please assign an institute first.", "danger")
                return redirect(url_for("admin.batches_page"))

            batch = Batch(
                institute_id=current_user.institute_id,
                name=name,
                academic_year=academic_year,
                status=status,
            )

            db.session.add(batch)
            db.session.commit()
            flash("Batch created successfully.", "success")

        except Exception as e:
            db.session.rollback()
            flash(f"Error creating batch: {str(e)}", "danger")

        return redirect(url_for("admin.batches_page"))

    batches = Batch.query.order_by(Batch.id.desc()).all()
    return render_template("admin_batches.html", batches=batches)


@admin_bp.route("/subjects", methods=["GET", "POST"])
@login_required
def subjects_page():
    admin_required()

    if request.method == "POST":
        try:
            name = (request.form.get("name") or "").strip()

            if not name:
                flash("Subject name is required.", "danger")
                return redirect(url_for("admin.subjects_page"))

            existing = Subject.query.filter(db.func.lower(Subject.name) == name.lower()).first()
            if existing:
                flash("Subject already exists.", "danger")
                return redirect(url_for("admin.subjects_page"))

            subject = Subject(name=name)
            db.session.add(subject)
            db.session.commit()
            flash("Subject created successfully.", "success")

        except Exception as e:
            db.session.rollback()
            flash(f"Error creating subject: {str(e)}", "danger")

        return redirect(url_for("admin.subjects_page"))

    subjects = Subject.query.order_by(Subject.name.asc()).all()
    return render_template("admin_subjects.html", subjects=subjects)


@admin_bp.route("/chapters", methods=["GET", "POST"])
@login_required
def chapters_page():
    admin_required()

    if request.method == "POST":
        try:
            subject_id = request.form.get("subject_id", type=int)
            name = (request.form.get("name") or "").strip()

            if not subject_id:
                flash("Subject is required.", "danger")
                return redirect(url_for("admin.chapters_page"))

            if not name:
                flash("Chapter name is required.", "danger")
                return redirect(url_for("admin.chapters_page"))

            subject = Subject.query.get(subject_id)
            if not subject:
                flash("Selected subject does not exist.", "danger")
                return redirect(url_for("admin.chapters_page"))

            existing = Chapter.query.filter(
                Chapter.subject_id == subject_id,
                db.func.lower(Chapter.name) == name.lower()
            ).first()

            if existing:
                flash("Chapter already exists under this subject.", "danger")
                return redirect(url_for("admin.chapters_page"))

            chapter = Chapter(subject_id=subject_id, name=name)
            db.session.add(chapter)
            db.session.commit()
            flash("Chapter created successfully.", "success")

        except Exception as e:
            db.session.rollback()
            flash(f"Error creating chapter: {str(e)}", "danger")

        return redirect(url_for("admin.chapters_page"))

    subjects = Subject.query.order_by(Subject.name.asc()).all()
    chapters = Chapter.query.order_by(Chapter.id.desc()).all()
    return render_template("admin_chapters.html", subjects=subjects, chapters=chapters)


@admin_bp.route("/students", methods=["GET", "POST"])
@login_required
def students_page():
    admin_required()

    if request.method == "POST":
        try:
            if not getattr(current_user, "institute_id", None):
                flash("Your admin account is not linked to any institute.", "danger")
                return redirect(url_for("admin.students_page"))

            full_name = (request.form.get("full_name") or "").strip()
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            admission_no = (request.form.get("admission_no") or "").strip()
            admission_session = (request.form.get("admission_session") or "").strip()
            course_applied = (request.form.get("course_applied") or "").strip()
            target_exam = (request.form.get("target_exam") or "").strip()
            current_class = (request.form.get("current_class") or "").strip()

            batch_id = request.form.get("batch_id", type=int)

            student_mobile = (request.form.get("student_mobile") or "").strip()
            student_email = (request.form.get("student_email") or "").strip().lower() or None
            father_name = (request.form.get("father_name") or "").strip()
            mother_name = (request.form.get("mother_name") or "").strip() or None
            father_mobile = (request.form.get("father_mobile") or "").strip()
            mother_mobile = (request.form.get("mother_mobile") or "").strip() or None
            parent_email = (request.form.get("parent_email") or "").strip().lower() or None

            dob_raw = (request.form.get("dob") or "").strip()
            gender = (request.form.get("gender") or "").strip()
            category = (request.form.get("category") or "").strip() or None

            address = (request.form.get("address") or "").strip()
            city = (request.form.get("city") or "").strip()
            district = (request.form.get("district") or "").strip() or None
            state = (request.form.get("state") or "").strip()
            pincode = (request.form.get("pincode") or "").strip() or None

            school_name = (request.form.get("school_name") or "").strip() or None
            board_name = (request.form.get("board_name") or "").strip() or None
            remarks = (request.form.get("remarks") or "").strip() or None
            status = (request.form.get("status") or "active").strip().lower()

            photo_file = request.files.get("photograph")

            if not full_name:
                flash("Student full name is required.", "danger")
                return redirect(url_for("admin.students_page"))

            if not username:
                flash("Username is required.", "danger")
                return redirect(url_for("admin.students_page"))

            if len(username) < 4:
                flash("Username must be at least 4 characters.", "danger")
                return redirect(url_for("admin.students_page"))

            if not password or len(password) < 6:
                flash("Password must be at least 6 characters.", "danger")
                return redirect(url_for("admin.students_page"))

            if not admission_no:
                flash("Admission number is required.", "danger")
                return redirect(url_for("admin.students_page"))

            if not admission_session:
                flash("Admission session is required.", "danger")
                return redirect(url_for("admin.students_page"))

            if not course_applied:
                flash("Course applied is required.", "danger")
                return redirect(url_for("admin.students_page"))

            if not batch_id:
                flash("Batch is required.", "danger")
                return redirect(url_for("admin.students_page"))

            batch = Batch.query.get(batch_id)
            if not batch:
                flash("Selected batch does not exist.", "danger")
                return redirect(url_for("admin.students_page"))

            if batch.institute_id != current_user.institute_id:
                flash("You can only assign students to your own institute batch.", "danger")
                return redirect(url_for("admin.students_page"))

            if not student_mobile:
                flash("Student mobile is required.", "danger")
                return redirect(url_for("admin.students_page"))

            if not father_name:
                flash("Father name is required.", "danger")
                return redirect(url_for("admin.students_page"))

            if not father_mobile:
                flash("Parent mobile is required.", "danger")
                return redirect(url_for("admin.students_page"))

            if not dob_raw:
                flash("Date of birth is required.", "danger")
                return redirect(url_for("admin.students_page"))

            try:
                dob = datetime.strptime(dob_raw, "%Y-%m-%d").date()
            except ValueError:
                flash("Invalid date of birth format.", "danger")
                return redirect(url_for("admin.students_page"))

            if gender not in ["Male", "Female", "Other"]:
                flash("Please select a valid gender.", "danger")
                return redirect(url_for("admin.students_page"))

            if not address:
                flash("Address is required.", "danger")
                return redirect(url_for("admin.students_page"))

            if not city:
                flash("City is required.", "danger")
                return redirect(url_for("admin.students_page"))

            if not state:
                flash("State is required.", "danger")
                return redirect(url_for("admin.students_page"))

            if status not in ["active", "inactive"]:
                status = "active"

            if not photo_file or not photo_file.filename:
                flash("Student photograph is required.", "danger")
                return redirect(url_for("admin.students_page"))

            if not allowed_image_file(photo_file.filename):
                flash("Photograph must be png, jpg, jpeg, gif, or webp.", "danger")
                return redirect(url_for("admin.students_page"))

            if User.query.filter(db.func.lower(User.username) == username.lower()).first():
                flash("Username already exists.", "danger")
                return redirect(url_for("admin.students_page"))

            if student_email and User.query.filter(db.func.lower(User.email) == student_email.lower()).first():
                flash("Student email is already used by another account.", "danger")
                return redirect(url_for("admin.students_page"))

            if StudentProfile.query.filter_by(admission_no=admission_no).first():
                flash("Admission number already exists.", "danger")
                return redirect(url_for("admin.students_page"))

            photograph = save_uploaded_image(photo_file, "students")
            if not photograph:
                flash("Unable to upload photograph.", "danger")
                return redirect(url_for("admin.students_page"))

            student_user = User(
                institute_id=current_user.institute_id,
                batch_id=batch.id,
                full_name=full_name,
                username=username,
                email=student_email,
                role="student",
                is_active_user=(status == "active"),
            )
            student_user.set_password(password)

            db.session.add(student_user)
            db.session.flush()

            student_profile = StudentProfile(
                user_id=student_user.id,
                admission_no=admission_no,
                admission_session=admission_session,
                course_applied=course_applied,
                target_exam=target_exam or None,
                current_class=current_class or None,
                student_mobile=student_mobile,
                student_email=student_email,
                father_name=father_name,
                mother_name=mother_name,
                father_mobile=father_mobile,
                mother_mobile=mother_mobile,
                parent_email=parent_email,
                dob=dob,
                gender=gender,
                category=category,
                address=address,
                city=city,
                district=district,
                state=state,
                pincode=pincode,
                school_name=school_name,
                board_name=board_name,
                remarks=remarks,
                photograph=photograph,
                status=status,
            )

            db.session.add(student_profile)
            db.session.commit()
            flash("Student created successfully.", "success")

        except Exception as e:
            db.session.rollback()
            flash(f"Error creating student: {str(e)}", "danger")

        return redirect(url_for("admin.students_page"))

    students = User.query.filter_by(role="student").order_by(User.id.desc()).all()
    batches = Batch.query.filter_by(institute_id=current_user.institute_id).order_by(Batch.id.desc()).all()

    student_attempt_counts = {
        row[0]: row[1]
        for row in db.session.query(
            TestAttempt.student_id,
            db.func.count(TestAttempt.id)
        ).group_by(TestAttempt.student_id).all()
    }

    return render_template(
        "admin_students.html",
        students=students,
        batches=batches,
        student_attempt_counts=student_attempt_counts,
    )

@admin_bp.route("/students/<int:student_id>/edit", methods=["GET", "POST"])
@login_required
def student_edit_page(student_id):
    admin_required()

    institute_id = getattr(current_user, "institute_id", None)

    student_query = User.query.filter(
        User.id == student_id,
        User.role == "student",
    )

    if institute_id and hasattr(User, "institute_id"):
        student_query = student_query.filter(User.institute_id == institute_id)

    student = student_query.first_or_404()
    profile = student.student_profile

    if not profile:
        flash("Student profile record was not found.", "danger")
        return redirect(url_for("admin.students_page"))

    batches_query = Batch.query
    if institute_id and hasattr(Batch, "institute_id"):
        batches_query = batches_query.filter(Batch.institute_id == institute_id)

    batches = batches_query.order_by(Batch.id.desc()).all()

    if request.method == "POST":
        try:
            full_name = (request.form.get("full_name") or "").strip()
            username = (request.form.get("username") or "").strip()
            new_password = request.form.get("password") or ""
            admission_no = (request.form.get("admission_no") or "").strip()
            admission_session = (request.form.get("admission_session") or "").strip()
            course_applied = (request.form.get("course_applied") or "").strip()
            target_exam = (request.form.get("target_exam") or "").strip()
            current_class = (request.form.get("current_class") or "").strip()

            batch_id = request.form.get("batch_id", type=int)

            student_mobile = (request.form.get("student_mobile") or "").strip()
            student_email = (request.form.get("student_email") or "").strip().lower() or None
            father_name = (request.form.get("father_name") or "").strip()
            mother_name = (request.form.get("mother_name") or "").strip() or None
            father_mobile = (request.form.get("father_mobile") or "").strip()
            mother_mobile = (request.form.get("mother_mobile") or "").strip() or None
            parent_email = (request.form.get("parent_email") or "").strip().lower() or None

            dob_raw = (request.form.get("dob") or "").strip()
            gender = (request.form.get("gender") or "").strip()
            category = (request.form.get("category") or "").strip() or None

            address = (request.form.get("address") or "").strip()
            city = (request.form.get("city") or "").strip()
            district = (request.form.get("district") or "").strip() or None
            state = (request.form.get("state") or "").strip()
            pincode = (request.form.get("pincode") or "").strip() or None

            school_name = (request.form.get("school_name") or "").strip() or None
            board_name = (request.form.get("board_name") or "").strip() or None
            remarks = (request.form.get("remarks") or "").strip() or None
            status = (request.form.get("status") or "active").strip().lower()

            photo_file = request.files.get("photograph")

            if not full_name:
                flash("Student full name is required.", "danger")
                return redirect(url_for("admin.student_edit_page", student_id=student.id))

            if not username:
                flash("Username is required.", "danger")
                return redirect(url_for("admin.student_edit_page", student_id=student.id))

            if len(username) < 4:
                flash("Username must be at least 4 characters.", "danger")
                return redirect(url_for("admin.student_edit_page", student_id=student.id))

            if new_password and len(new_password) < 6:
                flash("New password must be at least 6 characters.", "danger")
                return redirect(url_for("admin.student_edit_page", student_id=student.id))

            if not admission_no:
                flash("Admission number is required.", "danger")
                return redirect(url_for("admin.student_edit_page", student_id=student.id))

            if not admission_session:
                flash("Admission session is required.", "danger")
                return redirect(url_for("admin.student_edit_page", student_id=student.id))

            if not course_applied:
                flash("Course applied is required.", "danger")
                return redirect(url_for("admin.student_edit_page", student_id=student.id))

            if not batch_id:
                flash("Batch is required.", "danger")
                return redirect(url_for("admin.student_edit_page", student_id=student.id))

            batch = Batch.query.get(batch_id)
            if not batch:
                flash("Selected batch does not exist.", "danger")
                return redirect(url_for("admin.student_edit_page", student_id=student.id))

            if institute_id and getattr(batch, "institute_id", None) != institute_id:
                flash("You can only assign students to your own institute batch.", "danger")
                return redirect(url_for("admin.student_edit_page", student_id=student.id))

            if not student_mobile:
                flash("Student mobile is required.", "danger")
                return redirect(url_for("admin.student_edit_page", student_id=student.id))

            if not father_name:
                flash("Father name is required.", "danger")
                return redirect(url_for("admin.student_edit_page", student_id=student.id))

            if not father_mobile:
                flash("Parent mobile is required.", "danger")
                return redirect(url_for("admin.student_edit_page", student_id=student.id))

            if not dob_raw:
                flash("Date of birth is required.", "danger")
                return redirect(url_for("admin.student_edit_page", student_id=student.id))

            try:
                dob = datetime.strptime(dob_raw, "%Y-%m-%d").date()
            except ValueError:
                flash("Invalid date of birth format.", "danger")
                return redirect(url_for("admin.student_edit_page", student_id=student.id))

            if gender not in ["Male", "Female", "Other"]:
                flash("Please select a valid gender.", "danger")
                return redirect(url_for("admin.student_edit_page", student_id=student.id))

            if not address:
                flash("Address is required.", "danger")
                return redirect(url_for("admin.student_edit_page", student_id=student.id))

            if not city:
                flash("City is required.", "danger")
                return redirect(url_for("admin.student_edit_page", student_id=student.id))

            if not state:
                flash("State is required.", "danger")
                return redirect(url_for("admin.student_edit_page", student_id=student.id))

            if status not in ["active", "inactive"]:
                status = "active"

            existing_user = User.query.filter(
                db.func.lower(User.username) == username.lower(),
                User.id != student.id
            ).first()
            if existing_user:
                flash("Username already exists.", "danger")
                return redirect(url_for("admin.student_edit_page", student_id=student.id))

            if student_email:
                existing_email_user = User.query.filter(
                    db.func.lower(User.email) == student_email.lower(),
                    User.id != student.id
                ).first()
                if existing_email_user:
                    flash("Student email is already used by another account.", "danger")
                    return redirect(url_for("admin.student_edit_page", student_id=student.id))

            existing_admission = StudentProfile.query.filter(
                StudentProfile.admission_no == admission_no,
                StudentProfile.user_id != student.id
            ).first()
            if existing_admission:
                flash("Admission number already exists.", "danger")
                return redirect(url_for("admin.student_edit_page", student_id=student.id))

            if photo_file and photo_file.filename:
                if not allowed_image_file(photo_file.filename):
                    flash("Photograph must be png, jpg, jpeg, gif, or webp.", "danger")
                    return redirect(url_for("admin.student_edit_page", student_id=student.id))

                uploaded_photo = save_uploaded_image(photo_file, "students")
                if not uploaded_photo:
                    flash("Unable to upload photograph.", "danger")
                    return redirect(url_for("admin.student_edit_page", student_id=student.id))

                profile.photograph = uploaded_photo

            student.full_name = full_name
            student.username = username
            student.email = student_email
            student.batch_id = batch.id
            student.is_active_user = (status == "active")

            if new_password:
                student.set_password(new_password)

            profile.admission_no = admission_no
            profile.admission_session = admission_session
            profile.course_applied = course_applied
            profile.target_exam = target_exam or None
            profile.current_class = current_class or None
            profile.student_mobile = student_mobile
            profile.student_email = student_email
            profile.father_name = father_name
            profile.mother_name = mother_name
            profile.father_mobile = father_mobile
            profile.mother_mobile = mother_mobile
            profile.parent_email = parent_email
            profile.dob = dob
            profile.gender = gender
            profile.category = category
            profile.address = address
            profile.city = city
            profile.district = district
            profile.state = state
            profile.pincode = pincode
            profile.school_name = school_name
            profile.board_name = board_name
            profile.remarks = remarks
            profile.status = status

            db.session.commit()
            flash("Student updated successfully.", "success")
            return redirect(url_for("admin.student_edit_page", student_id=student.id))

        except Exception as e:
            db.session.rollback()
            flash(f"Error updating student: {str(e)}", "danger")
            return redirect(url_for("admin.student_edit_page", student_id=student.id))

    total_attempts = TestAttempt.query.filter_by(student_id=student.id).count()

    return render_template(
        "admin_student_edit.html",
        student=student,
        profile=profile,
        batches=batches,
        total_attempts=total_attempts,
    )


@admin_bp.route("/students/<int:student_id>/toggle-status", methods=["POST"])
@login_required
def student_toggle_status(student_id):
    admin_required()

    institute_id = getattr(current_user, "institute_id", None)

    student_query = User.query.filter(
        User.id == student_id,
        User.role == "student",
    )

    if institute_id and hasattr(User, "institute_id"):
        student_query = student_query.filter(User.institute_id == institute_id)

    student = student_query.first_or_404()
    profile = student.student_profile

    student.is_active_user = not bool(getattr(student, "is_active_user", False))
    if profile:
        profile.status = "active" if student.is_active_user else "inactive"

    db.session.commit()
    flash(
        "Student account activated successfully." if student.is_active_user else "Student account blocked successfully.",
        "success"
    )
    return redirect(request.referrer or url_for("admin.students_page"))


@admin_bp.route("/students/<int:student_id>/reset-password", methods=["POST"])
@login_required
def student_reset_password(student_id):
    admin_required()

    institute_id = getattr(current_user, "institute_id", None)

    student_query = User.query.filter(
        User.id == student_id,
        User.role == "student",
    )

    if institute_id and hasattr(User, "institute_id"):
        student_query = student_query.filter(User.institute_id == institute_id)

    student = student_query.first_or_404()

    new_password = (request.form.get("new_password") or "").strip()
    if not new_password or len(new_password) < 6:
        flash("New password must be at least 6 characters.", "danger")
        return redirect(request.referrer or url_for("admin.student_edit_page", student_id=student.id))

    student.set_password(new_password)
    db.session.commit()
    flash("Student password reset successfully.", "success")
    return redirect(request.referrer or url_for("admin.student_edit_page", student_id=student.id))

@admin_bp.route("/students/<int:student_id>/delete", methods=["POST"])
@login_required
def student_delete(student_id):
    admin_required()

    institute_id = getattr(current_user, "institute_id", None)

    student_query = User.query.filter(
        User.id == student_id,
        User.role == "student",
    )

    if institute_id and hasattr(User, "institute_id"):
        student_query = student_query.filter(User.institute_id == institute_id)

    student = student_query.first_or_404()
    profile = student.student_profile

    try:
        student_name = student.full_name or student.username or f"Student #{student.id}"

        photograph_path = None
        if profile and profile.photograph:
            photograph_path = os.path.join(
                current_app.root_path,
                "static",
                *profile.photograph.split("/")
            )

        TestAttempt.query.filter_by(student_id=student.id).delete(synchronize_session=False)

        if profile:
            db.session.delete(profile)

        db.session.delete(student)
        db.session.commit()

        if photograph_path and os.path.exists(photograph_path):
            try:
                os.remove(photograph_path)
            except Exception:
                pass

        flash(f"Student '{student_name}' deleted successfully.", "success")

    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting student: {str(e)}", "danger")

    return redirect(request.referrer or url_for("admin.students_page"))

@admin_bp.route("/questions", methods=["GET", "POST"])
@admin_bp.route("/questions", methods=["GET", "POST"], endpoint="questions")
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

            question_image_file = request.files.get("question_image")
            explanation_image_file = request.files.get("explanation_image")

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

            question_image = None
            explanation_image = None

            if question_image_file and question_image_file.filename:
                if not allowed_image_file(question_image_file.filename):
                    flash("Question image must be png, jpg, jpeg, gif, or webp.", "danger")
                    return redirect(url_for("admin.questions_page"))
                question_image = save_uploaded_image(question_image_file, "questions")

            if explanation_image_file and explanation_image_file.filename:
                if not allowed_image_file(explanation_image_file.filename):
                    flash("Explanation image must be png, jpg, jpeg, gif, or webp.", "danger")
                    return redirect(url_for("admin.questions_page"))
                explanation_image = save_uploaded_image(explanation_image_file, "questions")

            question = Question(
                institute_id=current_user.institute_id,
                subject_id=subject_id,
                chapter_id=chapter_id,
                stem=stem,
                question_image=question_image,
                option_a=option_a,
                option_b=option_b,
                option_c=option_c,
                option_d=option_d,
                correct_option=correct_option,
                explanation=explanation if explanation else None,
                explanation_image=explanation_image,
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

    # Filters expected by template
    filters = {
        "q": request.args.get("q", ""),
        "subject_id": request.args.get("subject_id", type=int),
        "chapter_id": request.args.get("chapter_id", type=int),
        "difficulty": request.args.get("difficulty", ""),
        "created_by": request.args.get("created_by", type=int),
    }

    questions_query = Question.query

     # Subject filter
    if filters["subject_id"]:
        questions_query = questions_query.filter(
            Question.subject_id == filters["subject_id"]
        )

    # Chapter filter
    if filters["chapter_id"]:
        questions_query = questions_query.filter(
            Question.chapter_id == filters["chapter_id"]
        )

    # Difficulty filter
    if filters["difficulty"]:
        questions_query = questions_query.filter(
            Question.difficulty_level == filters["difficulty"]
        )

    # Search filter
    if filters["q"]:
        questions_query = questions_query.filter(
            Question.stem.ilike(f"%{filters['q']}%")
        )

    questions = questions_query.order_by(
        Question.id.desc()
    ).all()

    # Stats expected by template
    stats = {
        "total": len(questions),
        "easy": len([q for q in questions if (q.difficulty_level or "").lower() == "easy"]),
        "medium": len([q for q in questions if (q.difficulty_level or "").lower() == "medium"]),
        "hard": len([q for q in questions if (q.difficulty_level or "").lower() == "hard"]),
    }

    # Creator dropdown expected by template
    try:
        creators = User.query.order_by(User.full_name.asc()).all()
    except Exception:
        creators = []

    return render_template(
        "admin_questions.html",
        subjects=subjects,
        chapters=chapters,
        questions=questions,
        filters=filters,
        stats=stats,
        creators=creators,
    )

@admin_bp.route("/questions/create", methods=["GET", "POST"], endpoint="create_question")
@login_required
def create_question():

    subjects = Subject.query.order_by(Subject.name.asc()).all()
    chapters = Chapter.query.order_by(Chapter.name.asc()).all()

    if request.method == "POST":

        question = Question(
            subject_id=int(request.form["subject_id"]),
            chapter_id=int(request.form["chapter_id"]),
            stem=request.form["stem"],
            option_a=request.form["option_a"],
            option_b=request.form["option_b"],
            option_c=request.form["option_c"],
            option_d=request.form["option_d"],
            correct_option=request.form["correct_option"],
            difficulty_level=request.form["difficulty_level"],
            explanation=request.form.get("explanation", "")
        )

        db.session.add(question)
        db.session.commit()

        flash("Question created successfully.", "success")

        return redirect(url_for("admin.questions"))

    return render_template(
        "question_form.html",
        page_title="Add Question",
        submit_label="Create Question",
        subjects=subjects,
        chapters=chapters,
        question=None
    )


# add these helpers near your other helper functions

def _form_value(*names, default=None, strip=True):
    for name in names:
        if name in request.form:
            value = request.form.get(name)
            if isinstance(value, str) and strip:
                value = value.strip()
            return value
    return default


def _set_attr_compat(obj, possible_names, value):
    for name in possible_names:
        if hasattr(obj, name):
            setattr(obj, name, value)
            return
    setattr(obj, possible_names[0], value)


def _get_attr_compat(obj, *possible_names):
    for name in possible_names:
        if hasattr(obj, name):
            return getattr(obj, name)
    return None


def _delete_uploaded_static_file(relative_path):
    if not relative_path:
        return
    try:
        abs_path = os.path.join(current_app.root_path, "static", relative_path)
        if os.path.exists(abs_path):
            os.remove(abs_path)
    except Exception:
        pass


@admin_bp.route("/questions/<int:question_id>/edit", methods=["GET", "POST"], endpoint="edit_question")
@login_required
def edit_question(question_id):
    admin_required()

    question_query = Question.query.filter(Question.id == question_id)
    if getattr(current_user, "institute_id", None) and hasattr(Question, "institute_id"):
        question_query = question_query.filter(Question.institute_id == current_user.institute_id)

    question = question_query.first_or_404()

    subjects = Subject.query.order_by(Subject.name.asc()).all()
    chapters = Chapter.query.order_by(Chapter.name.asc()).all()

    if request.method == "POST":
        try:
            subject_id = request.form.get("subject_id", type=int) or request.form.get("subjectid", type=int)
            chapter_id = request.form.get("chapter_id", type=int) or request.form.get("chapterid", type=int)

            stem = _form_value("stem", default="")
            option_a = _form_value("option_a", "optiona", default="")
            option_b = _form_value("option_b", "optionb", default="")
            option_c = _form_value("option_c", "optionc", default="")
            option_d = _form_value("option_d", "optiond", default="")
            correct_option = (_form_value("correct_option", "correctoption", default="") or "").upper()
            explanation = _form_value("explanation", default="")
            difficulty_level = (_form_value("difficulty_level", "difficultylevel", default="medium") or "medium").lower()

            question_image_file = request.files.get("question_image") or request.files.get("questionimage")
            explanation_image_file = request.files.get("explanation_image") or request.files.get("explanationimage")

            if not subject_id:
                flash("Subject is required.", "danger")
                return redirect(url_for("admin.edit_question", question_id=question.id))

            if not chapter_id:
                flash("Chapter is required.", "danger")
                return redirect(url_for("admin.edit_question", question_id=question.id))

            if not stem:
                flash("Question text is required.", "danger")
                return redirect(url_for("admin.edit_question", question_id=question.id))

            if not option_a or not option_b or not option_c or not option_d:
                flash("All four options are required.", "danger")
                return redirect(url_for("admin.edit_question", question_id=question.id))

            if correct_option not in {"A", "B", "C", "D"}:
                flash("Correct option must be A, B, C, or D.", "danger")
                return redirect(url_for("admin.edit_question", question_id=question.id))

            if difficulty_level not in {"easy", "medium", "hard"}:
                difficulty_level = "medium"

            subject = Subject.query.get(subject_id)
            chapter = Chapter.query.get(chapter_id)

            if not subject:
                flash("Selected subject does not exist.", "danger")
                return redirect(url_for("admin.edit_question", question_id=question.id))

            if not chapter:
                flash("Selected chapter does not exist.", "danger")
                return redirect(url_for("admin.edit_question", question_id=question.id))

            if getattr(chapter, "subject_id", None) != subject.id and getattr(chapter, "subjectid", None) != subject.id:
                flash("Selected chapter does not belong to the chosen subject.", "danger")
                return redirect(url_for("admin.edit_question", question_id=question.id))

            current_question_image = _get_attr_compat(question, "question_image", "questionimage")
            current_explanation_image = _get_attr_compat(question, "explanation_image", "explanationimage")

            if question_image_file and question_image_file.filename:
                if not allowed_image_file(question_image_file.filename):
                    flash("Question image must be png, jpg, jpeg, gif, or webp.", "danger")
                    return redirect(url_for("admin.edit_question", question_id=question.id))

                new_question_image = save_uploaded_image(question_image_file, "questions")
                if not new_question_image:
                    flash("Unable to upload question image.", "danger")
                    return redirect(url_for("admin.edit_question", question_id=question.id))

                if current_question_image:
                    _delete_uploaded_static_file(current_question_image)

                _set_attr_compat(question, ["question_image", "questionimage"], new_question_image)

            if explanation_image_file and explanation_image_file.filename:
                if not allowed_image_file(explanation_image_file.filename):
                    flash("Explanation image must be png, jpg, jpeg, gif, or webp.", "danger")
                    return redirect(url_for("admin.edit_question", question_id=question.id))

                new_explanation_image = save_uploaded_image(explanation_image_file, "questions")
                if not new_explanation_image:
                    flash("Unable to upload explanation image.", "danger")
                    return redirect(url_for("admin.edit_question", question_id=question.id))

                if current_explanation_image:
                    _delete_uploaded_static_file(current_explanation_image)

                _set_attr_compat(question, ["explanation_image", "explanationimage"], new_explanation_image)

            _set_attr_compat(question, ["subject_id", "subjectid"], subject_id)
            _set_attr_compat(question, ["chapter_id", "chapterid"], chapter_id)
            _set_attr_compat(question, ["stem"], stem)
            _set_attr_compat(question, ["option_a", "optiona"], option_a)
            _set_attr_compat(question, ["option_b", "optionb"], option_b)
            _set_attr_compat(question, ["option_c", "optionc"], option_c)
            _set_attr_compat(question, ["option_d", "optiond"], option_d)
            _set_attr_compat(question, ["correct_option", "correctoption"], correct_option)
            _set_attr_compat(question, ["explanation"], explanation or None)
            _set_attr_compat(question, ["difficulty_level", "difficultylevel"], difficulty_level)

            if hasattr(question, "updated_at"):
                question.updated_at = datetime.utcnow()

            db.session.commit()
            flash("Question updated successfully.", "success")
            return redirect(url_for("admin.questions"))

        except Exception as e:
            db.session.rollback()
            flash(f"Error updating question: {str(e)}", "danger")
            return redirect(url_for("admin.edit_question", question_id=question.id))

    return render_template(
        "question_form.html",
        page_title="Edit Question",
        submit_label="Update Question",
        subjects=subjects,
        chapters=chapters,
        question=question,
    )


@admin_bp.route("/questions/<int:question_id>/delete", methods=["POST"], endpoint="delete_question")
@login_required
def delete_question(question_id):
    admin_required()

    question_query = Question.query.filter(Question.id == question_id)
    if getattr(current_user, "institute_id", None) and hasattr(Question, "institute_id"):
        question_query = question_query.filter(Question.institute_id == current_user.institute_id)

    question = question_query.first_or_404()

    try:
        question_image = getattr_compat(question, ("question_image", "questionimage"))
        explanation_image = getattr_compat(question, ("explanation_image", "explanationimage"))

        linked_rows = TestQuestion.query.filter_by(question_id=question.id).all()
        affected_test_ids = sorted({row.test_id for row in linked_rows})

        if affected_test_ids:
            affected_tests = Test.query.filter(Test.id.in_(affected_test_ids)).all()
        else:
            affected_tests = []

        published_tests = [
            test for test in affected_tests
            if (getattr(test, "status", "") or "").strip().lower() == "published"
        ]

        if published_tests:
            published_names = [
                getattr(test, "title", None) or f"Test #{test.id}"
                for test in published_tests[:5]
            ]
            extra_count = len(published_tests) - len(published_names)

            message = (
                f"Cannot delete Question #{question.id}. "
                f"It is used in published test(s): {', '.join(published_names)}"
            )
            if extra_count > 0:
                message += f" and {extra_count} more"
            message += ". Unpublish/remove it from those tests first."

            flash(message, "danger")
            return redirect(url_for("admin.questions"))

        TestQuestion.query.filter_by(question_id=question.id).delete(synchronize_session=False)
        db.session.delete(question)
        db.session.commit()

        if question_image:
            delete_uploaded_static_file(question_image)
        if explanation_image:
            delete_uploaded_static_file(explanation_image)

        tests_moved_to_draft = []

        for test in affected_tests:
            is_valid, validation_message = validate_test_publishable(test)
            current_status = (getattr(test, "status", "") or "").strip().lower()

            if current_status == "published" and not is_valid:
                test.status = "draft"
                tests_moved_to_draft.append(getattr(test, "title", None) or f"Test #{test.id}")

        if tests_moved_to_draft:
            db.session.commit()
            flash(
                "Question deleted successfully. Some affected tests were moved to draft: "
                + ", ".join(tests_moved_to_draft[:5])
                + (f" and {len(tests_moved_to_draft) - 5} more" if len(tests_moved_to_draft) > 5 else ""),
                "warning"
            )
        else:
            flash(f"Question #{question.id} deleted successfully.", "success")

    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting question: {str(e)}", "danger")

    return redirect(url_for("admin.questions"))

@admin_bp.route("/questions/<int:question_id>/archive", methods=["POST"], endpoint="archivequestion")
@login_required
def archivequestion(question_id):
    admin_required()

    question_query = Question.query.filter(Question.id == question_id)
    if getattr(current_user, "institute_id", None) and hasattr(Question, "institute_id"):
        question_query = question_query.filter(Question.institute_id == current_user.institute_id)

    question = question_query.first_or_404()

    try:
        if hasattr(question, "is_active"):
            question.is_active = not bool(getattr(question, "is_active", True))
            db.session.commit()

            flash(
                f"Question {question.id} {'activated' if question.is_active else 'archived'} successfully.",
                "success"
            )
        else:
            flash("Question model does not support archive status yet. Add is_active field first.", "danger")

    except Exception as e:
        db.session.rollback()
        flash(f"Error updating question archive status: {str(e)}", "danger")

    return redirect(request.referrer or url_for("admin.questions"))

import json

@admin_bp.route("/questions/bulk-upload", methods=["POST"])
@login_required
def bulk_upload_questions():
    admin_required()

    try:
        raw_json = (request.form.get("questions_json") or "").strip()

        if not raw_json:
            flash("Questions JSON is required.", "danger")
            return redirect(url_for("admin.questions_page"))

        try:
            payload = json.loads(raw_json)
        except json.JSONDecodeError as e:
            flash(f"Invalid JSON: {str(e)}", "danger")
            return redirect(url_for("admin.questions_page"))

        if not isinstance(payload, list) or not payload:
            flash("JSON must be a non-empty array of question objects.", "danger")
            return redirect(url_for("admin.questions_page"))

        inserted_count = 0
        failed_items = []

        for index, item in enumerate(payload, start=1):
            try:
                subject_name = (item.get("subject") or "").strip()
                chapter_name = (item.get("chapter") or "").strip()
                stem = (item.get("stem") or "").strip()
                option_a = (item.get("option_a") or "").strip()
                option_b = (item.get("option_b") or "").strip()
                option_c = (item.get("option_c") or "").strip()
                option_d = (item.get("option_d") or "").strip()
                correct_option = (item.get("correct_option") or "").strip().upper()
                explanation = (item.get("explanation") or "").strip()
                difficulty_level = (item.get("difficulty_level") or "medium").strip().lower()

                if not subject_name:
                    raise ValueError("Subject is required")
                if not chapter_name:
                    raise ValueError("Chapter is required")
                if not stem:
                    raise ValueError("Question text is required")
                if not option_a or not option_b or not option_c or not option_d:
                    raise ValueError("All four options are required")
                if correct_option not in ["A", "B", "C", "D"]:
                    raise ValueError("Correct option must be A, B, C, or D")
                if difficulty_level not in ["easy", "medium", "hard"]:
                    difficulty_level = "medium"

                subject = Subject.query.filter(
                    db.func.lower(Subject.name) == subject_name.lower()
                ).first()
                if not subject:
                    raise ValueError(f"Subject not found: {subject_name}")

                chapter = Chapter.query.filter(
                    Chapter.subject_id == subject.id,
                    db.func.lower(Chapter.name) == chapter_name.lower()
                ).first()
                if not chapter:
                    raise ValueError(f"Chapter not found under {subject_name}: {chapter_name}")

                question = Question(
                    institute_id=current_user.institute_id,
                    subject_id=subject.id,
                    chapter_id=chapter.id,
                    stem=stem,
                    option_a=option_a,
                    option_b=option_b,
                    option_c=option_c,
                    option_d=option_d,
                    correct_option=correct_option,
                    explanation=explanation or None,
                    difficulty_level=difficulty_level,
                )

                db.session.add(question)
                inserted_count += 1

            except Exception as item_error:
                failed_items.append(f"Item {index}: {str(item_error)}")

        if inserted_count == 0:
            db.session.rollback()
            flash("No questions were inserted. " + " | ".join(failed_items[:5]), "danger")
            return redirect(url_for("admin.questions_page"))

        db.session.commit()

        if failed_items:
            flash(
                f"{inserted_count} questions inserted successfully. "
                f"{len(failed_items)} failed. "
                + " | ".join(failed_items[:5]),
                "success"
            )
        else:
            flash(f"All {inserted_count} questions inserted successfully.", "success")

    except Exception as e:
        db.session.rollback()
        flash(f"Error in bulk upload: {str(e)}", "danger")

    return redirect(url_for("admin.questions_page"))


@admin_bp.route("/tests", methods=["GET", "POST"])
@login_required
def tests_page():
    admin_required()

    if request.method == "POST":
        try:
            title = (request.form.get("title") or "").strip()
            test_type = (request.form.get("test_type") or "mock").strip().lower()
            test_mode = (request.form.get("test_mode") or "custom").strip().lower()
            instructions = (request.form.get("description") or "").strip()
            duration_minutes = request.form.get("duration_minutes", type=int)
            total_marks = request.form.get("total_marks", type=int)
            negative_marks = request.form.get("negative_marks", type=float)
            batch_id = request.form.get("batch_id", type=int)

            schedule_type = (request.form.get("schedule_type") or "instant").strip().lower()
            start_at_raw = request.form.get("start_at")
            end_at_raw = request.form.get("end_at")
            max_attempts = request.form.get("max_attempts", type=int)
            is_resume_allowed = (request.form.get("is_resume_allowed") or "").strip() in ["1", "true", "on", "yes"]

            if not title:
                flash("Test name is required.", "danger")
                return redirect(url_for("admin.tests_page"))

            if test_type not in ["chapter", "subject", "monthly", "mock", "full_syllabus"]:
                test_type = "mock"

            if test_mode not in ["neet_full", "quick_test", "custom"]:
                test_mode = "custom"

            if schedule_type not in ["instant", "fixed_start", "window"]:
                schedule_type = "instant"

            if not duration_minutes or duration_minutes < 1:
                flash("Duration must be at least 1 minute.", "danger")
                return redirect(url_for("admin.tests_page"))

            if not total_marks or total_marks < 1:
                flash("Total marks must be at least 1.", "danger")
                return redirect(url_for("admin.tests_page"))

            if negative_marks is None or negative_marks < 0:
                flash("Negative marks cannot be negative.", "danger")
                return redirect(url_for("admin.tests_page"))

            if not max_attempts or max_attempts < 1:
                max_attempts = 1

            start_at = parse_datetime_local(start_at_raw)
            end_at = parse_datetime_local(end_at_raw)

            if schedule_type == "fixed_start":
                if not start_at:
                    flash("Start time is required for fixed start tests.", "danger")
                    return redirect(url_for("admin.tests_page"))
                if end_at and end_at <= start_at:
                    flash("End time must be after start time.", "danger")
                    return redirect(url_for("admin.tests_page"))

            if schedule_type == "window":
                if not start_at or not end_at:
                    flash("Start time and end time are required for window tests.", "danger")
                    return redirect(url_for("admin.tests_page"))
                if end_at <= start_at:
                    flash("End time must be after start time.", "danger")
                    return redirect(url_for("admin.tests_page"))

            selected_batch = None
            if batch_id:
                selected_batch = Batch.query.get(batch_id)
                if not selected_batch:
                    flash("Selected batch does not exist.", "danger")
                    return redirect(url_for("admin.tests_page"))

            test = Test(
                title=title,
                test_type=test_type,
                duration_minutes=duration_minutes,
                total_marks=total_marks,
                negative_marks=negative_marks,
                status="draft",
            )

            if hasattr(Test, "instructions"):
                test.instructions = instructions if instructions else None

            if hasattr(Test, "batch_id"):
                test.batch_id = batch_id if selected_batch else None

            if hasattr(Test, "institute_id"):
                test.institute_id = getattr(current_user, "institute_id", None)

            if hasattr(Test, "test_mode"):
                test.test_mode = test_mode

            if hasattr(Test, "schedule_type"):
                test.schedule_type = schedule_type

            if hasattr(Test, "start_at"):
                test.start_at = start_at

            if hasattr(Test, "end_at"):
                test.end_at = end_at

            if hasattr(Test, "max_attempts"):
                test.max_attempts = max_attempts

            if hasattr(Test, "is_resume_allowed"):
                test.is_resume_allowed = is_resume_allowed

            if hasattr(Test, "auto_submit_on_expiry"):
                test.auto_submit_on_expiry = True

            db.session.add(test)
            db.session.commit()
            flash("Test created successfully. Build subject-wise paper next.", "success")

        except Exception as e:
            db.session.rollback()
            flash(f"Error creating test: {str(e)}", "danger")

        return redirect(url_for("admin.tests_page"))

    tests = Test.query.order_by(Test.id.desc()).all()
    batches = Batch.query.order_by(Batch.id.desc()).all()

    return render_template("admin_tests.html", tests=tests, batches=batches)


@admin_bp.route("/tests/<int:test_id>/builder")
@login_required
def test_builder_page(test_id):
    admin_required()
    test = Test.query.get_or_404(test_id)

    linked_questions = TestQuestion.query.filter_by(test_id=test.id).all()

    subject_targets = {
        "Physics": 45,
        "Chemistry": 45,
        "Biology": 90,
    }

    subject_counts, total_selected_questions, total_selected_marks = get_test_subject_counts(test)

    return render_template(
        "admin_test_builder.html",
        test=test,
        subject_targets=subject_targets,
        subject_counts=subject_counts,
        total_selected_questions=total_selected_questions,
        total_selected_marks=total_selected_marks,
    )


@admin_bp.route("/tests/<int:test_id>/builder/<subject_name>", methods=["GET", "POST"])
@login_required
def test_builder_subject_page(test_id, subject_name):
    admin_required()
    test = Test.query.get_or_404(test_id)

    allowed_subjects = {
        "physics": "Physics",
        "chemistry": "Chemistry",
        "biology": "Biology",
    }

    subject_key = (subject_name or "").strip().lower()
    if subject_key not in allowed_subjects:
        abort(404)

    selected_subject_name = allowed_subjects[subject_key]
    subject_obj = Subject.query.filter(db.func.lower(Subject.name) == subject_key).first()

    if not subject_obj:
        flash(f"{selected_subject_name} subject is not available in database.", "danger")
        return redirect(url_for("admin.test_builder_page", test_id=test.id))

    if request.method == "POST":
        try:
            question_ids = request.form.getlist("question_ids")
            selected_ids = []

            for qid in question_ids:
                try:
                    selected_ids.append(int(qid))
                except (TypeError, ValueError):
                    pass

            if not selected_ids:
                flash("Please select at least one question to add.", "danger")
                return redirect(url_for("admin.test_builder_subject_page", test_id=test.id, subject_name=subject_key, **request.args.to_dict()))

            marks = request.form.get("marks", type=float)
            negative_marks = request.form.get("negative_marks", type=float)

            if marks is None or marks < 0:
                marks = 4.0

            if negative_marks is None or negative_marks < 0:
                negative_marks = 1.0

            max_order = db.session.query(
                db.func.coalesce(db.func.max(TestQuestion.display_order), 0)
            ).filter(TestQuestion.test_id == test.id).scalar() or 0

            added_count = 0
            skipped_count = 0

            for question_id in selected_ids:
                question = Question.query.get(question_id)
                if not question:
                    skipped_count += 1
                    continue

                if question.subject_id != subject_obj.id:
                    skipped_count += 1
                    continue

                existing = TestQuestion.query.filter_by(
                    test_id=test.id,
                    question_id=question.id
                ).first()

                if existing:
                    skipped_count += 1
                    continue

                max_order += 1
                link = TestQuestion(
                    test_id=test.id,
                    question_id=question.id,
                    display_order=max_order,
                    marks=marks,
                    negative_marks=negative_marks,
                )
                db.session.add(link)
                added_count += 1

            db.session.commit()

            if added_count and skipped_count:
                flash(f"{added_count} question(s) added successfully. {skipped_count} duplicate/invalid question(s) skipped.", "success")
            elif added_count:
                flash(f"{added_count} question(s) added successfully.", "success")
            else:
                flash("No new questions were added.", "info")

        except Exception as e:
            db.session.rollback()
            flash(f"Error adding questions to test: {str(e)}", "danger")

        return redirect(url_for("admin.test_builder_subject_page", test_id=test.id, subject_name=subject_key, **request.args.to_dict()))

    chapter_id = request.args.get("chapter_id", type=int)
    difficulty_level = (request.args.get("difficulty_level") or "").strip().lower()
    usage_count_filter = (request.args.get("usage_count") or "").strip().lower()
    search = (request.args.get("search") or "").strip()
    only_unused = (request.args.get("only_unused") or "").strip()

    linked_questions = TestQuestion.query.filter_by(test_id=test.id).order_by(
        TestQuestion.display_order.asc(),
        TestQuestion.id.asc()
    ).all()

    linked_question_ids = [item.question_id for item in linked_questions]

    usage_subquery = db.session.query(
        TestQuestion.question_id.label("question_id"),
        db.func.count(TestQuestion.id).label("usage_count")
    ).group_by(TestQuestion.question_id).subquery()

    usage_expr = db.func.coalesce(usage_subquery.c.usage_count, 0)

    available_query = db.session.query(
        Question,
        usage_expr.label("usage_count")
    ).outerjoin(
        usage_subquery,
        usage_subquery.c.question_id == Question.id
    ).filter(
        Question.subject_id == subject_obj.id
    )

    if linked_question_ids:
        available_query = available_query.filter(~Question.id.in_(linked_question_ids))

    if chapter_id:
        available_query = available_query.filter(Question.chapter_id == chapter_id)

    if difficulty_level in ["easy", "medium", "hard"]:
        available_query = available_query.filter(Question.difficulty_level == difficulty_level)

    if only_unused == "1":
        available_query = available_query.filter(usage_expr == 0)

    if usage_count_filter:
        if usage_count_filter == "5_plus":
            available_query = available_query.filter(usage_expr >= 5)
        else:
            try:
                usage_number = int(usage_count_filter)
                available_query = available_query.filter(usage_expr == usage_number)
            except ValueError:
                pass

    if search:
        available_query = available_query.filter(Question.stem.ilike(f"%{search}%"))

    available_rows = available_query.order_by(
        usage_expr.asc(),
        Question.chapter_id.asc(),
        Question.id.desc()
    ).all()

    available_questions = []
    for question, usage_count in available_rows:
        available_questions.append({
            "id": question.id,
            "stem": question.stem,
            "chapter_name": question.chapter.name if question.chapter else "Chapter",
            "difficulty_level": question.difficulty_level or "medium",
            "correct_option": question.correct_option,
            "usage_count": int(usage_count or 0),
            "question_image": question.question_image,
            "option_a": question.option_a,
            "option_b": question.option_b,
            "option_c": question.option_c,
            "option_d": question.option_d,
            "explanation": question.explanation,
        })

    subject_targets = {
        "Physics": 45,
        "Chemistry": 45,
        "Biology": 90,
    }

    subject_counts, _, _ = get_test_subject_counts(test)

    current_subject_selected = subject_counts.get(selected_subject_name, 0)
    current_subject_target = subject_targets.get(selected_subject_name, 0)

    chapters = Chapter.query.filter_by(subject_id=subject_obj.id).order_by(Chapter.name.asc()).all()

    return render_template(
        "admin_test_builder_subject.html",
        test=test,
        selected_subject_name=selected_subject_name,
        subject_key=subject_key,
        subject_targets=subject_targets,
        subject_counts=subject_counts,
        current_subject_selected=current_subject_selected,
        current_subject_target=current_subject_target,
        linked_questions=linked_questions,
        available_questions=available_questions,
        chapters=chapters,
        chapter_id=chapter_id,
        difficulty_level=difficulty_level,
        usage_count_filter=usage_count_filter,
        search=search,
        only_unused=only_unused,
    )


@admin_bp.route("/tests/<int:test_id>/publish", methods=["POST"])
@login_required
def publish_test(test_id):
    admin_required()
    test = Test.query.get_or_404(test_id)

    is_valid, message = validate_test_publishable(test)
    if not is_valid:
        flash(message, "danger")
        return redirect(url_for("admin.test_builder_page", test_id=test.id))

    test.status = "published"

    if hasattr(test, "published_at"):
        test.published_at = utc_now()

    db.session.commit()
    flash("Test published successfully.", "success")
    return redirect(url_for("admin.tests_page"))


@admin_bp.route("/tests/<int:test_id>/unpublish", methods=["POST"])
@login_required
def unpublish_test(test_id):
    admin_required()
    test = Test.query.get_or_404(test_id)
    test.status = "draft"
    db.session.commit()
    flash("Test moved back to draft.", "success")
    return redirect(url_for("admin.tests_page"))


@admin_bp.route("/tests/<int:test_id>/questions/<int:link_id>/delete", methods=["POST"])
@login_required
def delete_test_question(test_id, link_id):
    admin_required()
    link = TestQuestion.query.filter_by(id=link_id, test_id=test_id).first_or_404()

    db.session.delete(link)
    db.session.commit()

    test = Test.query.get(test_id)
    if test and test.status == "published":
        is_valid, message = validate_test_publishable(test)
        if not is_valid:
            test.status = "draft"
            db.session.commit()
            flash(f"Question removed. Test moved back to draft. {message}", "success")
            return redirect(url_for("admin.test_builder_page", test_id=test_id))

    flash("Question removed from test.", "success")
    return redirect(request.referrer or url_for("admin.test_builder_page", test_id=test_id))

@admin_bp.route("/analytics")
@login_required
def analytics_overview_page():
    admin_required()

    institute_id = getattr(current_user, "institute_id", None)

    student_query = User.query.filter_by(role="student")
    batch_query = Batch.query
    test_query = Test.query
    attempt_query = TestAttempt.query.filter_by(status="submitted")

    if institute_id:
        if hasattr(User, "institute_id"):
            student_query = student_query.filter(User.institute_id == institute_id)
        if hasattr(Batch, "institute_id"):
            batch_query = batch_query.filter(Batch.institute_id == institute_id)
        if hasattr(Test, "institute_id"):
            test_query = test_query.filter(Test.institute_id == institute_id)

    students = student_query.all()
    batches = batch_query.order_by(Batch.id.desc()).all()
    tests = test_query.order_by(Test.id.desc()).all()

    test_ids = [t.id for t in tests]
    student_ids = [s.id for s in students]
    batch_map = {b.id: b for b in batches}

    if test_ids:
        attempts = attempt_query.filter(TestAttempt.test_id.in_(test_ids)).all()
    else:
        attempts = []

    if institute_id and not test_ids and student_ids:
        attempts = attempt_query.filter(TestAttempt.student_id.in_(student_ids)).all()

    total_students = len(students)
    active_students = sum(1 for s in students if bool(getattr(s, "is_active_user", False)))
    total_batches = len(batches)
    total_tests = len(tests)
    total_submitted = len(attempts)

    avg_score = round(
        sum(float(getattr(a, "total_score", 0) or 0) for a in attempts) / total_submitted,
        2
    ) if total_submitted else 0

    total_correct = sum(int(getattr(a, "correct_count", 0) or 0) for a in attempts)
    total_questions_seen = sum(
        int(getattr(a, "correct_count", 0) or 0) +
        int(getattr(a, "wrong_count", 0) or 0) +
        int(getattr(a, "skipped_count", 0) or 0)
        for a in attempts
    )
    avg_accuracy = round((total_correct / total_questions_seen) * 100, 2) if total_questions_seen else 0

    percentile_values = []
    for a in attempts:
        percentile_overall = getattr(a, "percentile_overall", None)
        if percentile_overall is not None:
            try:
                percentile_values.append(float(percentile_overall))
            except (TypeError, ValueError):
                pass
    avg_percentile = round(sum(percentile_values) / len(percentile_values), 2) if percentile_values else 0

    students_with_attempts = {getattr(a, "student_id", None) for a in attempts if getattr(a, "student_id", None)}
    participation_rate = round((len(students_with_attempts) / total_students) * 100, 2) if total_students else 0

    student_summary = {}
    for student in students:
        student_summary[student.id] = {
            "student": student,
            "attempts": [],
            "scores": [],
            "accuracies": [],
            "percentiles": [],
        }

    for a in attempts:
        sid = getattr(a, "student_id", None)
        if sid not in student_summary:
            continue

        score = float(getattr(a, "total_score", 0) or 0)
        correct = int(getattr(a, "correct_count", 0) or 0)
        wrong = int(getattr(a, "wrong_count", 0) or 0)
        skipped = int(getattr(a, "skipped_count", 0) or 0)
        total = correct + wrong + skipped
        accuracy = round((correct / total) * 100, 2) if total else 0

        student_summary[sid]["attempts"].append(a)
        student_summary[sid]["scores"].append(score)
        student_summary[sid]["accuracies"].append(accuracy)

        percentile_overall = getattr(a, "percentile_overall", None)
        if percentile_overall is not None:
            try:
                student_summary[sid]["percentiles"].append(float(percentile_overall))
            except (TypeError, ValueError):
                pass

    center_top_student = None
    center_risk_student = None
    risk_students = []

    ranked_students = []

    for sid, data in student_summary.items():
        student = data["student"]
        attempt_count = len(data["attempts"])
        avg_student_score = round(sum(data["scores"]) / len(data["scores"]), 2) if data["scores"] else 0
        avg_student_accuracy = round(sum(data["accuracies"]) / len(data["accuracies"]), 2) if data["accuracies"] else 0
        avg_student_percentile = round(sum(data["percentiles"]) / len(data["percentiles"]), 2) if data["percentiles"] else 0

        latest_score = data["scores"][-1] if data["scores"] else 0
        recent_scores = data["scores"][-3:] if len(data["scores"]) >= 3 else data["scores"]
        score_trend_down = False
        if len(recent_scores) >= 2 and recent_scores[-1] < recent_scores[0]:
            score_trend_down = True

        batch_name = "Unassigned"
        student_batch_id = getattr(student, "batch_id", None)
        if student_batch_id in batch_map:
            batch_name = batch_map[student_batch_id].name

        ranked_students.append({
            "student_id": student.id,
            "full_name": getattr(student, "full_name", "Student"),
            "batch_name": batch_name,
            "attempt_count": attempt_count,
            "avg_score": avg_student_score,
            "avg_accuracy": avg_student_accuracy,
            "avg_percentile": avg_student_percentile,
            "latest_score": latest_score,
            "score_trend_down": score_trend_down,
            "is_active_user": bool(getattr(student, "is_active_user", False)),
        })

    ranked_students.sort(key=lambda x: (x["avg_score"], x["avg_accuracy"], x["attempt_count"]), reverse=True)

    if ranked_students:
        top_item = ranked_students[0]
        center_top_student = {
            "student_id": top_item["student_id"],
            "full_name": top_item["full_name"],
            "latest_score": top_item["latest_score"],
            "percentile_overall": top_item["avg_percentile"],
        }

    risk_candidates = []
    for item in ranked_students:
        risk_level = "low"
        if item["attempt_count"] == 0:
            risk_level = "high"
        elif item["avg_accuracy"] < 35 or item["avg_score"] < 120:
            risk_level = "high"
        elif item["avg_accuracy"] < 50 or item["score_trend_down"]:
            risk_level = "medium"

        enriched = {
            **item,
            "risk_level": risk_level,
        }

        if risk_level in ["high", "medium"]:
            risk_candidates.append(enriched)

    risk_order = {"high": 0, "medium": 1, "low": 2}
    risk_candidates.sort(key=lambda x: (risk_order.get(x["risk_level"], 9), x["avg_accuracy"], x["avg_score"]))

    risk_students = risk_candidates[:6]
    if risk_students:
        center_risk_student = risk_students[0]

    batch_rows = []
    best_batch = None
    weakest_batch = None

    for batch in batches:
        batch_students = [s for s in students if getattr(s, "batch_id", None) == batch.id]
        batch_student_ids = {s.id for s in batch_students}
        batch_attempts = [a for a in attempts if getattr(a, "student_id", None) in batch_student_ids]

        attempt_count = len(batch_attempts)
        student_count = len(batch_students)

        batch_avg_score = round(
            sum(float(getattr(a, "total_score", 0) or 0) for a in batch_attempts) / attempt_count,
            2
        ) if attempt_count else 0

        batch_correct = sum(int(getattr(a, "correct_count", 0) or 0) for a in batch_attempts)
        batch_total_q = sum(
            int(getattr(a, "correct_count", 0) or 0) +
            int(getattr(a, "wrong_count", 0) or 0) +
            int(getattr(a, "skipped_count", 0) or 0)
            for a in batch_attempts
        )
        batch_avg_accuracy = round((batch_correct / batch_total_q) * 100, 2) if batch_total_q else 0

        batch_percentiles = []
        for a in batch_attempts:
            p = getattr(a, "percentile_overall", None)
            if p is not None:
                try:
                    batch_percentiles.append(float(p))
                except (TypeError, ValueError):
                    pass
        batch_avg_percentile = round(sum(batch_percentiles) / len(batch_percentiles), 2) if batch_percentiles else 0

        participated_students = {getattr(a, "student_id", None) for a in batch_attempts if getattr(a, "student_id", None)}
        batch_participation_rate = round((len(participated_students) / student_count) * 100, 2) if student_count else 0

        row = {
            "id": batch.id,
            "name": getattr(batch, "name", "Unnamed Batch"),
            "academic_year": getattr(batch, "academic_year", ""),
            "student_count": student_count,
            "attempt_count": attempt_count,
            "avg_score": batch_avg_score,
            "avg_accuracy": batch_avg_accuracy,
            "avg_percentile": batch_avg_percentile,
            "participation_rate": batch_participation_rate,
        }
        batch_rows.append(row)

    batch_rows.sort(key=lambda x: (x["avg_score"], x["avg_accuracy"], x["participation_rate"]), reverse=True)

    if batch_rows:
        best_batch = batch_rows[0]
        weakest_batch = sorted(
            batch_rows,
            key=lambda x: (x["avg_score"], x["avg_accuracy"], x["participation_rate"])
        )[0]

    weak_subject = "Not enough data"
    subject_stats = {"Physics": [], "Chemistry": [], "Biology": []}

    for a in attempts:
        physics_score = getattr(a, "physics_score", None)
        chemistry_score = getattr(a, "chemistry_score", None)
        biology_score = getattr(a, "biology_score", None)

        if physics_score is not None:
            try:
                subject_stats["Physics"].append(float(physics_score))
            except (TypeError, ValueError):
                pass

        if chemistry_score is not None:
            try:
                subject_stats["Chemistry"].append(float(chemistry_score))
            except (TypeError, ValueError):
                pass

        if biology_score is not None:
            try:
                subject_stats["Biology"].append(float(biology_score))
            except (TypeError, ValueError):
                pass

    subject_avgs = []
    for subject_name, values in subject_stats.items():
        if values:
            subject_avgs.append((subject_name, round(sum(values) / len(values), 2)))

    if subject_avgs:
        subject_avgs.sort(key=lambda x: x[1])
        weak_subject = subject_avgs[0][0]

    recent_test_rows = []
    for test in tests[:8]:
        test_attempts = [a for a in attempts if getattr(a, "test_id", None) == test.id]
        participants_count = len(test_attempts)

        test_avg_score = round(
            sum(float(getattr(a, "total_score", 0) or 0) for a in test_attempts) / participants_count,
            2
        ) if participants_count else 0

        test_correct = sum(int(getattr(a, "correct_count", 0) or 0) for a in test_attempts)
        test_total_q = sum(
            int(getattr(a, "correct_count", 0) or 0) +
            int(getattr(a, "wrong_count", 0) or 0) +
            int(getattr(a, "skipped_count", 0) or 0)
            for a in test_attempts
        )
        test_avg_accuracy = round((test_correct / test_total_q) * 100, 2) if test_total_q else 0

        recent_test_rows.append({
            "id": test.id,
            "title": getattr(test, "title", "Untitled Test"),
            "participants_count": participants_count,
            "avg_score": test_avg_score,
            "avg_accuracy": test_avg_accuracy,
        })

    recent_tests = tests[:10]

    return render_template(
        "admin_analytics_overview.html",
        total_students=total_students,
        active_students=active_students,
        total_batches=total_batches,
        total_tests=total_tests,
        total_submitted=total_submitted,
        avg_score=avg_score,
        avg_accuracy=avg_accuracy,
        avg_percentile=avg_percentile,
        participation_rate=participation_rate,
        best_batch=best_batch,
        weakest_batch=weakest_batch,
        center_top_student=center_top_student,
        center_risk_student=center_risk_student,
        weak_subject=weak_subject,
        risk_students=risk_students,
        batch_rows=batch_rows,
        recent_test_rows=recent_test_rows,
        recent_tests=recent_tests,
    )

@admin_bp.route("/analytics/tests")
@login_required
def analytics_tests_page():
    admin_required()

    tests = Test.query.order_by(Test.id.desc()).all()
    return render_template("admin_analytics_tests.html", tests=tests)

@admin_bp.route("/analytics/tests/<int:test_id>")
@login_required
def analytics_test_detail_page(test_id):
    admin_required()

    institute_id = getattr(current_user, "institute_id", None)

    test_query = Test.query.filter(Test.id == test_id)
    if institute_id and hasattr(Test, "institute_id"):
        test_query = test_query.filter(Test.institute_id == institute_id)

    test = test_query.first_or_404()

    attempts_query = TestAttempt.query.filter_by(
        test_id=test.id,
        status="submitted"
    )

    attempts = attempts_query.order_by(TestAttempt.id.desc()).all()

    total_attempts = len(attempts)

    score_values = []
    accuracy_values = []
    percentile_values = []
    rank_values = []
    time_taken_values = []

    processed_attempts = []

    for attempt in attempts:
        score = float(getattr(attempt, "total_score", 0) or 0)

        correct = int(getattr(attempt, "correct_count", 0) or 0)
        wrong = int(getattr(attempt, "wrong_count", 0) or 0)
        skipped = int(getattr(attempt, "skipped_count", 0) or 0)
        total_questions = correct + wrong + skipped

        accuracy = round((correct / total_questions) * 100, 2) if total_questions else 0

        rank_overall = getattr(attempt, "rank_overall", None)
        percentile_overall = getattr(attempt, "percentile_overall", None)
        rank_batch = getattr(attempt, "rank_batch", None)
        time_taken_seconds = int(getattr(attempt, "time_taken_seconds", 0) or 0)

        score_values.append(score)
        accuracy_values.append(accuracy)

        if time_taken_seconds > 0:
            time_taken_values.append(time_taken_seconds)

        if percentile_overall is not None:
            try:
                percentile_values.append(float(percentile_overall))
            except (TypeError, ValueError):
                pass

        if rank_overall is not None:
            try:
                rank_values.append(int(rank_overall))
            except (TypeError, ValueError):
                pass

        setattr(attempt, "safe_rank_overall", rank_overall)
        setattr(attempt, "safe_percentile_overall", percentile_overall)
        setattr(attempt, "safe_rank_batch", rank_batch)
        setattr(attempt, "safe_time_taken_seconds", time_taken_seconds)
        setattr(attempt, "safe_accuracy", accuracy)

        processed_attempts.append(attempt)

    avg_score = round(sum(score_values) / len(score_values), 2) if score_values else 0
    highest_score = round(max(score_values), 2) if score_values else 0
    lowest_score = round(min(score_values), 2) if score_values else 0
    avg_accuracy = round(sum(accuracy_values) / len(accuracy_values), 2) if accuracy_values else 0
    avg_percentile = round(sum(percentile_values) / len(percentile_values), 2) if percentile_values else 0
    best_rank = min(rank_values) if rank_values else None
    avg_time_taken_seconds = round(sum(time_taken_values) / len(time_taken_values)) if time_taken_values else 0

    return render_template(
        "admin_analytics_test_detail.html",
        test=test,
        attempts=processed_attempts,
        total_attempts=total_attempts,
        avg_score=avg_score,
        highest_score=highest_score,
        lowest_score=lowest_score,
        avg_accuracy=avg_accuracy,
        avg_percentile=avg_percentile,
        best_rank=best_rank,
        avg_time_taken_seconds=avg_time_taken_seconds,
    )

@admin_bp.route("/analytics/students")
@login_required
def analytics_students_page():
    admin_required()

    institute_id = getattr(current_user, "institute_id", None)

    q = (request.args.get("q") or "").strip()
    batch_id = request.args.get("batch_id", type=int)
    status_filter = (request.args.get("status") or "").strip().lower()
    risk_filter = (request.args.get("risk") or "").strip().lower()

    students_query = User.query.filter_by(role="student")
    batches_query = Batch.query

    if institute_id:
        if hasattr(User, "institute_id"):
            students_query = students_query.filter(User.institute_id == institute_id)
        if hasattr(Batch, "institute_id"):
            batches_query = batches_query.filter(Batch.institute_id == institute_id)

    if q:
        students_query = students_query.filter(User.full_name.ilike(f"%{q}%"))

    if batch_id:
        students_query = students_query.filter(User.batch_id == batch_id)

    if status_filter == "active":
        students_query = students_query.filter(User.is_active_user.is_(True))
    elif status_filter == "inactive":
        students_query = students_query.filter(User.is_active_user.is_(False))

    students = students_query.order_by(User.id.desc()).all()
    batches = batches_query.order_by(Batch.id.desc()).all()

    student_ids = [student.id for student in students]
    batch_map = {batch.id: batch for batch in batches}

    attempts = []
    if student_ids:
        attempts = TestAttempt.query.filter(
            TestAttempt.student_id.in_(student_ids),
            TestAttempt.status == "submitted"
        ).all()

    attempt_map = {}
    for student in students:
        attempt_map[student.id] = []

    for attempt in attempts:
        sid = getattr(attempt, "student_id", None)
        if sid in attempt_map:
            attempt_map[sid].append(attempt)

    enriched_students = []
    high_risk_count = 0
    medium_risk_count = 0

    for student in students:
        student_attempts = attempt_map.get(student.id, [])

        scores = []
        accuracies = []
        percentiles = []

        for attempt in student_attempts:
            score = float(getattr(attempt, "total_score", 0) or 0)
            correct = int(getattr(attempt, "correct_count", 0) or 0)
            wrong = int(getattr(attempt, "wrong_count", 0) or 0)
            skipped = int(getattr(attempt, "skipped_count", 0) or 0)
            total_questions = correct + wrong + skipped

            accuracy = round((correct / total_questions) * 100, 2) if total_questions else 0

            scores.append(score)
            accuracies.append(accuracy)

            percentile_overall = getattr(attempt, "percentile_overall", None)
            if percentile_overall is not None:
                try:
                    percentiles.append(float(percentile_overall))
                except (TypeError, ValueError):
                    pass

        attempt_count = len(student_attempts)
        avg_score = round(sum(scores) / len(scores), 2) if scores else 0
        avg_accuracy = round(sum(accuracies) / len(accuracies), 2) if accuracies else 0
        avg_percentile = round(sum(percentiles) / len(percentiles), 2) if percentiles else 0

        score_trend_down = False
        if len(scores) >= 2 and scores[-1] < scores[0]:
            score_trend_down = True

        risk_level = "low"
        if attempt_count == 0:
            risk_level = "high"
        elif avg_accuracy < 35 or avg_score < 120:
            risk_level = "high"
        elif avg_accuracy < 50 or score_trend_down:
            risk_level = "medium"

        if risk_level == "high":
            high_risk_count += 1
        elif risk_level == "medium":
            medium_risk_count += 1

        if risk_filter and risk_level != risk_filter:
            continue

        setattr(student, "attempt_count", attempt_count)
        setattr(student, "avg_score", avg_score)
        setattr(student, "avg_accuracy", avg_accuracy)
        setattr(student, "avg_percentile", avg_percentile)
        setattr(student, "risk_level", risk_level)

        batch_name = "Not assigned"
        if getattr(student, "batch_id", None) in batch_map:
            batch_name = getattr(batch_map[student.batch_id], "name", "Not assigned")
        setattr(student, "batch_name", batch_name)

        enriched_students.append(student)

    total_students = len(enriched_students)
    active_students = sum(1 for student in enriched_students if bool(getattr(student, "is_active_user", False)))
    inactive_students = total_students - active_students

    return render_template(
        "admin_analytics_students.html",
        students=enriched_students,
        batches=batches,
        total_students=total_students,
        active_students=active_students,
        inactive_students=inactive_students,
        high_risk_count=high_risk_count,
        medium_risk_count=medium_risk_count,
    )

@admin_bp.route("/analytics/students/<int:student_id>")
@login_required
def analytics_student_detail_page(student_id):
    admin_required()

    institute_id = getattr(current_user, "institute_id", None)

    student_query = User.query.filter(
        User.id == student_id,
        User.role == "student"
    )

    if institute_id and hasattr(User, "institute_id"):
        student_query = student_query.filter(User.institute_id == institute_id)

    student = student_query.first_or_404()

    attempts = TestAttempt.query.filter_by(
        student_id=student.id,
        status="submitted"
    ).order_by(TestAttempt.id.desc()).all()

    total_attempts = len(attempts)

    score_values = []
    percentile_values = []
    rank_values = []

    total_correct = 0
    total_questions = 0

    latest_percentile = None
    latest_rank = None

    for index, attempt in enumerate(attempts):
        score = float(getattr(attempt, "total_score", 0) or 0)
        score_values.append(score)

        correct = int(getattr(attempt, "correct_count", 0) or 0)
        wrong = int(getattr(attempt, "wrong_count", 0) or 0)
        skipped = int(getattr(attempt, "skipped_count", 0) or 0)

        total_correct += correct
        total_questions += (correct + wrong + skipped)

        percentile_overall = getattr(attempt, "percentile_overall", None)
        if percentile_overall is not None:
            try:
                percentile_values.append(float(percentile_overall))
            except (TypeError, ValueError):
                pass

        rank_overall = getattr(attempt, "rank_overall", None)
        if rank_overall is not None:
            try:
                rank_values.append(int(rank_overall))
            except (TypeError, ValueError):
                pass

        if index == 0:
            latest_percentile = percentile_overall
            latest_rank = rank_overall

    avg_score = round(sum(score_values) / len(score_values), 2) if score_values else 0
    best_score = round(max(score_values), 2) if score_values else 0
    avg_accuracy = round((total_correct / total_questions) * 100, 2) if total_questions else 0
    avg_percentile = round(sum(percentile_values) / len(percentile_values), 2) if percentile_values else 0
    best_rank = min(rank_values) if rank_values else None

    score_trend_down = False
    if len(score_values) >= 2 and score_values[0] < score_values[-1]:
        score_trend_down = True

    risk_level = "low"
    if total_attempts == 0:
        risk_level = "high"
    elif avg_accuracy < 35 or avg_score < 120:
        risk_level = "high"
    elif avg_accuracy < 50 or score_trend_down:
        risk_level = "medium"

    return render_template(
        "admin_analytics_student_detail.html",
        student=student,
        attempts=attempts,
        total_attempts=total_attempts,
        avg_score=avg_score,
        best_score=best_score,
        avg_accuracy=avg_accuracy,
        avg_percentile=avg_percentile,
        latest_percentile=latest_percentile,
        best_rank=best_rank,
        latest_rank=latest_rank,
        risk_level=risk_level,
    )
