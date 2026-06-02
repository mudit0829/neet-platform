from collections import defaultdict
from datetime import datetime, timedelta
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user

from ..extensions import db
from ..models import Test, TestQuestion, TestAttempt, AttemptAnswer

student_bp = Blueprint("student", __name__, url_prefix="/student")


def utc_now():
    return datetime.utcnow()


def student_required():
    if not current_user.is_authenticated:
        abort(401)
    if getattr(current_user, "role", "") != "student":
        abort(403)


def get_attempt_remaining_seconds(attempt):
    now = utc_now()

    if getattr(attempt, "expires_at", None):
        remaining = int((attempt.expires_at - now).total_seconds())
        return max(0, remaining)

    start_base = attempt.started_at or attempt.created_at
    duration_seconds = int((attempt.test.duration_minutes or 0) * 60)
    elapsed = int((now - start_base).total_seconds())
    remaining = duration_seconds - elapsed
    return max(0, remaining)


def get_or_create_answer(attempt_id, question_id):
    answer = AttemptAnswer.query.filter_by(
        attempt_id=attempt_id,
        question_id=question_id
    ).first()

    if not answer:
        answer = AttemptAnswer(
            attempt_id=attempt_id,
            question_id=question_id,
            selected_option=None,
            is_marked_for_review=False,
            time_spent_seconds=0,
        )
        db.session.add(answer)
        db.session.flush()

    return answer


def can_student_start_test(test, student_id):
    now = utc_now()

    if test.status != "published":
        return False, "This test is not available."

    question_count = TestQuestion.query.filter_by(test_id=test.id).count()
    if question_count <= 0:
        return False, "This test has no questions yet."

    if getattr(test, "schedule_type", "instant") == "fixed_start":
        if not getattr(test, "start_at", None):
            return False, "This test start time is not configured."
        if now < test.start_at:
            return False, "This test has not started yet."
        if getattr(test, "end_at", None) and now > test.end_at:
            return False, "This test time window has closed."

    elif getattr(test, "schedule_type", "instant") == "window":
        if not getattr(test, "start_at", None) or not getattr(test, "end_at", None):
            return False, "This test window is not configured."
        if now < test.start_at:
            return False, "This test window has not opened yet."
        if now > test.end_at:
            return False, "This test window has closed."

    max_attempts = getattr(test, "max_attempts", 1) or 1
    previous_attempts_count = TestAttempt.query.filter(
        TestAttempt.test_id == test.id,
        TestAttempt.student_id == student_id,
        TestAttempt.status.in_(["submitted", "ongoing"])
    ).count()

    if previous_attempts_count >= max_attempts:
        ongoing_attempt = TestAttempt.query.filter_by(
            test_id=test.id,
            student_id=student_id,
            status="ongoing"
        ).order_by(TestAttempt.id.desc()).first()

        if ongoing_attempt:
            return True, ongoing_attempt

        return False, "Maximum allowed attempts reached."

    return True, None


def calculate_attempt_expiry(test, started_at):
    duration_minutes = int(test.duration_minutes or 0)
    duration_delta = timedelta(minutes=duration_minutes)

    schedule_type = getattr(test, "schedule_type", "instant")

    if schedule_type == "fixed_start":
        fixed_start = test.start_at or started_at
        fixed_end = fixed_start + duration_delta

        if getattr(test, "end_at", None):
            return min(fixed_end, test.end_at)

        return fixed_end

    if schedule_type == "window":
        rolling_end = started_at + duration_delta
        if getattr(test, "end_at", None):
            return min(rolling_end, test.end_at)
        return rolling_end

    return started_at + duration_delta


def auto_submit_if_time_over(attempt):
    if attempt.status != "ongoing":
        return False

    remaining = get_attempt_remaining_seconds(attempt)
    if remaining > 0:
        return False

    finalize_attempt(attempt, auto_submitted=True)
    db.session.commit()
    return True


def finalize_attempt(attempt, auto_submitted=False):
    if attempt.status == "submitted":
        return

    test_questions = TestQuestion.query.filter_by(
        test_id=attempt.test_id
    ).order_by(TestQuestion.display_order.asc()).all()

    answer_map = {
        answer.question_id: answer
        for answer in attempt.answers
    }

    total_score = 0.0
    correct_count = 0
    wrong_count = 0
    skipped_count = 0

    for tq in test_questions:
        answer = answer_map.get(tq.question_id)

        selected_option = ""
        if answer and answer.selected_option:
            selected_option = (answer.selected_option or "").strip().upper()

        correct_option = (tq.question.correct_option or "").strip().upper()

        if not selected_option:
            skipped_count += 1
        elif selected_option == correct_option:
            correct_count += 1
            total_score += float(tq.marks or 0)
        else:
            wrong_count += 1
            total_score -= float(tq.negative_marks or 0)

    attempt.status = "submitted"
    attempt.total_score = total_score
    attempt.correct_count = correct_count
    attempt.wrong_count = wrong_count
    attempt.skipped_count = skipped_count

    if hasattr(attempt, "submitted_at"):
        attempt.submitted_at = utc_now()

    if hasattr(attempt, "is_abandoned") and auto_submitted:
        attempt.is_abandoned = False


@student_bp.route("/dashboard")
@login_required
def dashboard():
    student_required()

    now = utc_now()

    available_tests = Test.query.filter_by(status="published").count()

    ongoing_tests = TestAttempt.query.filter_by(
        student_id=current_user.id,
        status="ongoing"
    ).count()

    completed_tests = TestAttempt.query.filter_by(
        student_id=current_user.id,
        status="submitted"
    ).count()

    latest_attempts = TestAttempt.query.filter_by(
        student_id=current_user.id
    ).order_by(TestAttempt.id.desc()).limit(5).all()

    ongoing_attempts = TestAttempt.query.filter_by(
        student_id=current_user.id,
        status="ongoing"
    ).order_by(TestAttempt.id.desc()).limit(5).all()

    for attempt in ongoing_attempts:
        if getattr(attempt, "expires_at", None) and now >= attempt.expires_at:
            finalize_attempt(attempt, auto_submitted=True)

    db.session.commit()

    ongoing_attempts = TestAttempt.query.filter_by(
        student_id=current_user.id,
        status="ongoing"
    ).order_by(TestAttempt.id.desc()).limit(5).all()

    return render_template(
        "student_dashboard.html",
        available_tests=available_tests,
        ongoing_tests=ongoing_tests,
        completed_tests=completed_tests,
        latest_attempts=latest_attempts,
        ongoing_attempts=ongoing_attempts,
    )


@student_bp.route("/tests")
@login_required
def tests_page():
    student_required()

    now = utc_now()
    tests = Test.query.filter_by(status="published").order_by(Test.id.desc()).all()

    visible_tests = []
    for test in tests:
        schedule_type = getattr(test, "schedule_type", "instant")

        if schedule_type == "fixed_start":
            if getattr(test, "end_at", None) and now > test.end_at:
                continue
        elif schedule_type == "window":
            if getattr(test, "end_at", None) and now > test.end_at:
                continue

        visible_tests.append(test)

    ongoing_attempts = {
        a.test_id: a
        for a in TestAttempt.query.filter_by(
            student_id=current_user.id,
            status="ongoing"
        ).all()
    }

    submitted_attempts = {}
    all_submitted = TestAttempt.query.filter_by(
        student_id=current_user.id,
        status="submitted"
    ).order_by(TestAttempt.id.desc()).all()

    for att in all_submitted:
        if att.test_id not in submitted_attempts:
            submitted_attempts[att.test_id] = att

    return render_template(
        "student_tests.html",
        tests=visible_tests,
        ongoing_attempts=ongoing_attempts,
        submitted_attempts=submitted_attempts,
    )


@student_bp.route("/tests/<int:test_id>/instructions")
@login_required
def test_instructions_page(test_id):
    student_required()

    test = Test.query.get_or_404(test_id)

    if test.status != "published":
        flash("This test is not available.", "danger")
        return redirect(url_for("student.tests_page"))

    question_count = TestQuestion.query.filter_by(test_id=test.id).count()

    ongoing_attempt = TestAttempt.query.filter_by(
        test_id=test.id,
        student_id=current_user.id,
        status="ongoing"
    ).order_by(TestAttempt.id.desc()).first()

    submitted_attempt = TestAttempt.query.filter_by(
        test_id=test.id,
        student_id=current_user.id,
        status="submitted"
    ).order_by(TestAttempt.id.desc()).first()

    can_start, reason = can_student_start_test(test, current_user.id)

    return render_template(
        "student_test_instructions.html",
        test=test,
        question_count=question_count,
        ongoing_attempt=ongoing_attempt,
        submitted_attempt=submitted_attempt,
        can_start=can_start if isinstance(can_start, bool) else True,
        start_message=reason if isinstance(reason, str) else None,
    )


@student_bp.route("/tests/<int:test_id>/start", methods=["POST"])
@login_required
def start_test_attempt(test_id):
    student_required()

    test = Test.query.get_or_404(test_id)

    can_start, result = can_student_start_test(test, current_user.id)

    if not can_start:
        flash(result, "danger")
        return redirect(url_for("student.test_instructions_page", test_id=test.id))

    if isinstance(result, TestAttempt):
        if auto_submit_if_time_over(result):
            flash("Previous attempt expired and was auto-submitted.", "info")
            return redirect(url_for("student.result_page", attempt_id=result.id))
        return redirect(url_for("student.attempt_page", attempt_id=result.id))

    now = utc_now()
    expires_at = calculate_attempt_expiry(test, now)

    if expires_at <= now:
        flash("This test can no longer be started because its allowed time is over.", "danger")
        return redirect(url_for("student.test_instructions_page", test_id=test.id))

    attempt = TestAttempt(
        test_id=test.id,
        student_id=current_user.id,
        status="ongoing",
        total_score=0.0,
        correct_count=0,
        wrong_count=0,
        skipped_count=0,
        started_at=now if hasattr(TestAttempt, "started_at") else None,
        expires_at=expires_at if hasattr(TestAttempt, "expires_at") else None,
    )

    db.session.add(attempt)
    db.session.commit()

    return redirect(url_for("student.attempt_page", attempt_id=attempt.id))


@student_bp.route("/attempts/<int:attempt_id>", methods=["GET"])
@login_required
def attempt_page(attempt_id):
    student_required()

    attempt = TestAttempt.query.get_or_404(attempt_id)

    if attempt.student_id != current_user.id:
        abort(403)

    if auto_submit_if_time_over(attempt):
        flash("Time is over. Your test was submitted automatically.", "info")
        return redirect(url_for("student.result_page", attempt_id=attempt.id))

    if attempt.status == "submitted":
        return redirect(url_for("student.result_page", attempt_id=attempt.id))

    if hasattr(attempt.test, "is_resume_allowed") and attempt.test.is_resume_allowed is False:
        if request.args.get("resume") == "blocked":
            flash("Resume is not allowed for this test.", "danger")
            return redirect(url_for("student.tests_page"))

    question_number = request.args.get("q", type=int, default=1)

    test_questions = TestQuestion.query.filter_by(
        test_id=attempt.test_id
    ).order_by(TestQuestion.display_order.asc()).all()

    if not test_questions:
        flash("This test has no questions.", "danger")
        return redirect(url_for("student.tests_page"))

    total_questions = len(test_questions)

    if question_number < 1:
        question_number = 1
    if question_number > total_questions:
        question_number = total_questions

    current_test_question = test_questions[question_number - 1]
    current_question = current_test_question.question

    answer_map = {}
    for item in test_questions:
        answer_map[item.question_id] = get_or_create_answer(attempt.id, item.question_id)

    db.session.commit()

    current_answer = answer_map.get(current_question.id)

    subject_groups = defaultdict(list)
    answered_count = 0

    for index, tq in enumerate(test_questions, start=1):
        q = tq.question
        ans = answer_map.get(q.id)

        selected_option = (ans.selected_option or "").strip() if ans else ""
        marked_for_review = ans.is_marked_for_review if ans else False

        if selected_option:
            answered_count += 1

        if marked_for_review and selected_option:
            state = "review_answered"
        elif marked_for_review and not selected_option:
            state = "review"
        elif selected_option:
            state = "answered"
        else:
            state = "not_answered"

        subject_name = q.subject.name if q.subject else "General"
        subject_groups[subject_name].append({
            "index": index,
            "question_id": q.id,
            "state": state,
            "is_current": index == question_number,
        })

    remaining_seconds = get_attempt_remaining_seconds(attempt)

    return render_template(
        "student_test_attempt.html",
        attempt=attempt,
        test=attempt.test,
        test_questions=test_questions,
        total_questions=total_questions,
        question_number=question_number,
        current_test_question=current_test_question,
        current_question=current_question,
        current_answer=current_answer,
        subject_groups=dict(subject_groups),
        answered_count=answered_count,
        remaining_seconds=remaining_seconds,
    )


@student_bp.route("/attempts/<int:attempt_id>/save", methods=["POST"])
@login_required
def save_answer(attempt_id):
    student_required()

    attempt = TestAttempt.query.get_or_404(attempt_id)

    if attempt.student_id != current_user.id:
        abort(403)

    if auto_submit_if_time_over(attempt):
        flash("Time is over. Your test was submitted automatically.", "info")
        return redirect(url_for("student.result_page", attempt_id=attempt.id))

    if attempt.status != "ongoing":
        return redirect(url_for("student.result_page", attempt_id=attempt.id))

    question_id = request.form.get("question_id", type=int)
    question_number = request.form.get("question_number", type=int, default=1)
    action_type = (request.form.get("action_type") or "save_next").strip()
    selected_option = (request.form.get("selected_option") or "").strip().upper()

    test_question = TestQuestion.query.filter_by(
        test_id=attempt.test_id,
        question_id=question_id
    ).first_or_404()

    answer = get_or_create_answer(attempt.id, test_question.question_id)

    if selected_option not in ["A", "B", "C", "D"]:
        selected_option = None

    if action_type == "clear":
        answer.selected_option = None
        answer.is_marked_for_review = False
    elif action_type == "mark_review":
        answer.selected_option = selected_option
        answer.is_marked_for_review = True
    else:
        answer.selected_option = selected_option
        answer.is_marked_for_review = False

    db.session.commit()

    total_questions = TestQuestion.query.filter_by(test_id=attempt.test_id).count()
    next_question_number = question_number

    if action_type in ["save_next", "mark_review"] and question_number < total_questions:
        next_question_number = question_number + 1

    return redirect(url_for("student.attempt_page", attempt_id=attempt.id, q=next_question_number))


@student_bp.route("/attempts/<int:attempt_id>/submit", methods=["POST"])
@login_required
def submit_attempt(attempt_id):
    student_required()

    attempt = TestAttempt.query.get_or_404(attempt_id)

    if attempt.student_id != current_user.id:
        abort(403)

    if attempt.status == "submitted":
        return redirect(url_for("student.result_page", attempt_id=attempt.id))

    finalize_attempt(attempt)
    db.session.commit()

    flash("Test submitted successfully.", "success")
    return redirect(url_for("student.result_page", attempt_id=attempt.id))


@student_bp.route("/attempts/<int:attempt_id>/result")
@login_required
def result_page(attempt_id):
    student_required()

    attempt = TestAttempt.query.get_or_404(attempt_id)

    if attempt.student_id != current_user.id:
        abort(403)

    if attempt.status == "ongoing":
        if auto_submit_if_time_over(attempt):
            flash("Time is over. Your test was submitted automatically.", "info")
        else:
            flash("Complete and submit your test first.", "danger")
            return redirect(url_for("student.attempt_page", attempt_id=attempt.id))

    test_questions = TestQuestion.query.filter_by(
        test_id=attempt.test_id
    ).order_by(TestQuestion.display_order.asc()).all()

    answer_map = {
        answer.question_id: answer
        for answer in attempt.answers
    }

    subject_stats = {}
    detailed_rows = []

    for idx, tq in enumerate(test_questions, start=1):
        q = tq.question
        ans = answer_map.get(q.id)

        selected_option = (ans.selected_option or "").strip().upper() if ans and ans.selected_option else ""
        correct_option = (q.correct_option or "").strip().upper()
        subject_name = q.subject.name if q.subject else "General"
        chapter_name = q.chapter.name if q.chapter else "Chapter"

        if subject_name not in subject_stats:
            subject_stats[subject_name] = {
                "total": 0,
                "correct": 0,
                "wrong": 0,
                "skipped": 0,
                "score": 0.0,
            }

        subject_stats[subject_name]["total"] += 1

        status = "skipped"
        if not selected_option:
            subject_stats[subject_name]["skipped"] += 1
        elif selected_option == correct_option:
            status = "correct"
            subject_stats[subject_name]["correct"] += 1
            subject_stats[subject_name]["score"] += float(tq.marks or 0)
        else:
            status = "wrong"
            subject_stats[subject_name]["wrong"] += 1
            subject_stats[subject_name]["score"] -= float(tq.negative_marks or 0)

        detailed_rows.append({
            "index": idx,
            "status": status,
            "question": q,
            "chapter_name": chapter_name,
            "selected_option": selected_option,
            "correct_option": correct_option,
        })

    total_questions = len(test_questions)
    accuracy = 0.0
    if total_questions > 0:
        accuracy = round((attempt.correct_count / total_questions) * 100, 2)

    duration_seconds = int((attempt.test.duration_minutes or 0) * 60)
    remaining_seconds = get_attempt_remaining_seconds(attempt)
    time_taken_seconds = max(0, duration_seconds - remaining_seconds)

    start_base = attempt.started_at or attempt.created_at
    if attempt.status == "submitted" and start_base:
        end_base = attempt.submitted_at or utc_now()
        raw_taken = int((end_base - start_base).total_seconds())
        time_taken_seconds = min(duration_seconds, max(0, raw_taken))

    return render_template(
        "student_test_result.html",
        attempt=attempt,
        test=attempt.test,
        subject_stats=subject_stats,
        detailed_rows=detailed_rows,
        total_questions=total_questions,
        accuracy=accuracy,
        time_taken_seconds=time_taken_seconds,
    )
