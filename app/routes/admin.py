import os
import uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, abort
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from ..models import Question, Test, TestQuestion, User, Batch, Subject, Chapter
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


@admin_bp.route("/tests", methods=["GET", "POST"])
@login_required
def tests_page():
    admin_required()

    if request.method == "POST":
        try:
            title = (request.form.get("title") or "").strip()
            test_type = (request.form.get("test_type") or "mock").strip().lower()
            instructions = (request.form.get("description") or "").strip()
            duration_minutes = request.form.get("duration_minutes", type=int)
            total_marks = request.form.get("total_marks", type=int)
            negative_marks = request.form.get("negative_marks", type=float)
            batch_id = request.form.get("batch_id", type=int)

            if not title:
                flash("Test name is required.", "danger")
                return redirect(url_for("admin.tests_page"))

            if test_type not in ["chapter", "subject", "monthly", "mock", "full_syllabus"]:
                test_type = "mock"

            if not duration_minutes or duration_minutes < 1:
                flash("Duration must be at least 1 minute.", "danger")
                return redirect(url_for("admin.tests_page"))

            if not total_marks or total_marks < 1:
                flash("Total marks must be at least 1.", "danger")
                return redirect(url_for("admin.tests_page"))

            if negative_marks is None or negative_marks < 0:
                flash("Negative marks cannot be negative.", "danger")
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

    subject_counts = {
        "Physics": 0,
        "Chemistry": 0,
        "Biology": 0,
    }

    total_selected_marks = 0.0

    for item in linked_questions:
        if item.question and item.question.subject:
            subject_name = (item.question.subject.name or "").strip()
            if subject_name in subject_counts:
                subject_counts[subject_name] += 1
        total_selected_marks += float(item.marks or 0)

    total_selected_questions = sum(subject_counts.values())

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

    available_query = db.session.query(
        Question,
        db.func.coalesce(usage_subquery.c.usage_count, 0).label("usage_count")
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

    usage_expr = db.func.coalesce(usage_subquery.c.usage_count, 0)

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

    subject_counts = {
        "Physics": 0,
        "Chemistry": 0,
        "Biology": 0,
    }

    for item in linked_questions:
        if item.question and item.question.subject:
            q_subject_name = (item.question.subject.name or "").strip()
            if q_subject_name in subject_counts:
                subject_counts[q_subject_name] += 1

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

    subject_counts = {
        "Physics": 0,
        "Chemistry": 0,
        "Biology": 0,
    }

    for item in test.test_questions:
        if item.question and item.question.subject:
            subject_name = (item.question.subject.name or "").strip()
            if subject_name in subject_counts:
                subject_counts[subject_name] += 1

    if subject_counts["Physics"] < 45 or subject_counts["Chemistry"] < 45 or subject_counts["Biology"] < 90:
        flash("Cannot publish. Required minimum: Physics 45, Chemistry 45, Biology 90.", "danger")
        return redirect(url_for("admin.test_builder_page", test_id=test.id))

    test.status = "published"
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
        subject_counts = {
            "Physics": 0,
            "Chemistry": 0,
            "Biology": 0,
        }

        for item in test.test_questions:
            if item.question and item.question.subject:
                subject_name = (item.question.subject.name or "").strip()
                if subject_name in subject_counts:
                    subject_counts[subject_name] += 1

        if subject_counts["Physics"] < 45 or subject_counts["Chemistry"] < 45 or subject_counts["Biology"] < 90:
            test.status = "draft"
            db.session.commit()
            flash("Question removed. Test moved back to draft because NEET subject requirement is no longer complete.", "success")
            return redirect(url_for("admin.test_builder_page", test_id=test_id))

    flash("Question removed from test.", "success")
    return redirect(request.referrer or url_for("admin.test_builder_page", test_id=test_id))


@admin_bp.route("/tests/<int:test_id>/builder", methods=["GET", "POST"])
@login_required
def test_builder_page(test_id):
    admin_required()
    test = Test.query.get_or_404(test_id)

    if request.method == "POST":
        try:
            question_ids = request.form.getlist("question_ids")
            single_question_id = request.form.get("question_id", type=int)

            selected_ids = []
            for qid in question_ids:
                try:
                    selected_ids.append(int(qid))
                except (TypeError, ValueError):
                    pass

            if single_question_id and single_question_id not in selected_ids:
                selected_ids.append(single_question_id)

            if not selected_ids:
                flash("Please select at least one question to add.", "danger")
                return redirect(url_for("admin.test_builder_page", test_id=test.id))

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
                flash(
                    f"{added_count} question(s) added successfully. {skipped_count} duplicate/invalid question(s) skipped.",
                    "success"
                )
            elif added_count:
                flash(f"{added_count} question(s) added successfully.", "success")
            else:
                flash("No new questions were added.", "info")

        except Exception as e:
            db.session.rollback()
            flash(f"Error adding questions to test: {str(e)}", "danger")

        return redirect(url_for("admin.test_builder_page", test_id=test.id, **request.args.to_dict()))

    subject_id = request.args.get("subject_id", type=int)
    chapter_id = request.args.get("chapter_id", type=int)
    difficulty_level = (request.args.get("difficulty_level") or "").strip().lower()
    usage_count_filter = (request.args.get("usage_count") or "").strip().lower()
    search = (request.args.get("search") or "").strip()

    linked_questions = TestQuestion.query.filter_by(test_id=test.id).order_by(
        TestQuestion.display_order.asc(),
        TestQuestion.id.asc()
    ).all()

    linked_question_ids = [item.question_id for item in linked_questions]

    usage_subquery = db.session.query(
        TestQuestion.question_id.label("question_id"),
        db.func.count(TestQuestion.id).label("usage_count")
    ).group_by(TestQuestion.question_id).subquery()

    available_query = db.session.query(
        Question,
        db.func.coalesce(usage_subquery.c.usage_count, 0).label("usage_count")
    ).outerjoin(
        usage_subquery,
        usage_subquery.c.question_id == Question.id
    )

    if linked_question_ids:
        available_query = available_query.filter(~Question.id.in_(linked_question_ids))

    if subject_id:
        available_query = available_query.filter(Question.subject_id == subject_id)

    if chapter_id:
        available_query = available_query.filter(Question.chapter_id == chapter_id)

    if difficulty_level in ["easy", "medium", "hard"]:
        available_query = available_query.filter(Question.difficulty_level == difficulty_level)

    if usage_count_filter:
        usage_expr = db.func.coalesce(usage_subquery.c.usage_count, 0)

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
        db.func.coalesce(usage_subquery.c.usage_count, 0).asc(),
        Question.subject_id.asc(),
        Question.chapter_id.asc(),
        Question.id.desc()
    ).all()

    available_questions = []
    filtered_available_subject_counts = {}

    for question, usage_count in available_rows:
        usage_count = int(usage_count or 0)
        available_questions.append({
            "id": question.id,
            "stem": question.stem,
            "subject_name": question.subject.name if question.subject else "Subject",
            "chapter_name": question.chapter.name if question.chapter else "Chapter",
            "difficulty_level": question.difficulty_level or "medium",
            "correct_option": question.correct_option,
            "usage_count": usage_count,
        })
        subject_name = question.subject.name if question.subject else "Unknown"
        filtered_available_subject_counts[subject_name] = filtered_available_subject_counts.get(subject_name, 0) + 1

    selected_subject_counts = {}
    total_selected_marks = 0.0

    for item in linked_questions:
        subject_name = (
            item.question.subject.name
            if item.question and item.question.subject
            else "Unknown"
        )
        selected_subject_counts[subject_name] = selected_subject_counts.get(subject_name, 0) + 1
        total_selected_marks += float(item.marks or 0)

    subjects = Subject.query.order_by(Subject.name.asc()).all()

    chapters_query = Chapter.query.order_by(Chapter.name.asc())
    if subject_id:
        chapters_query = chapters_query.filter_by(subject_id=subject_id)
    chapters = chapters_query.all()

    return render_template(
        "admin_test_builder.html",
        test=test,
        linked_questions=linked_questions,
        available_questions=available_questions,
        subjects=subjects,
        chapters=chapters,
        subject_id=subject_id,
        chapter_id=chapter_id,
        difficulty_level=difficulty_level,
        usage_count_filter=usage_count_filter,
        search=search,
        selected_subject_counts=selected_subject_counts,
        filtered_available_subject_counts=filtered_available_subject_counts,
        total_selected_questions=len(linked_questions),
        total_selected_marks=total_selected_marks,
    )


@admin_bp.route("/tests/<int:test_id>/publish", methods=["POST"])
@login_required
def publish_test(test_id):
    admin_required()
    test = Test.query.get_or_404(test_id)

    if not test.test_questions:
        flash("Add at least one question before publishing.", "danger")
        return redirect(url_for("admin.tests_page"))

    test.status = "published"
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
    if test and test.status == "published" and not test.test_questions:
        test.status = "draft"
        db.session.commit()
        flash("Question removed. Test moved back to draft because it has no questions.", "success")
    else:
        flash("Question removed from test.", "success")

    return redirect(url_for("admin.test_builder_page", test_id=test_id))
