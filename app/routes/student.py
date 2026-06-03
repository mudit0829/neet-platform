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


def format_seconds_human(total_seconds):
    total_seconds = int(total_seconds or 0)
    hrs = total_seconds // 3600
    mins = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    if hrs > 0:
        return f"{hrs}h {mins}m {secs}s"
    return f"{mins}m {secs}s"

def compute_attempt_time_taken_seconds(attempt):
    duration_seconds = int((attempt.test.duration_minutes or 0) * 60)

    start_base = attempt.started_at or attempt.created_at
    if not start_base:
        return 0

    if attempt.status == "submitted":
        end_base = attempt.submitted_at or utc_now()
        raw_taken = int((end_base - start_base).total_seconds())
        return min(duration_seconds, max(0, raw_taken))

    remaining_seconds = get_attempt_remaining_seconds(attempt)
    return max(0, duration_seconds - remaining_seconds)

def recompute_test_rankings(test_id):
    attempts = (
        TestAttempt.query
        .filter_by(test_id=test_id, status="submitted")
        .order_by(
            TestAttempt.total_score.desc(),
            TestAttempt.correct_count.desc(),
            TestAttempt.wrong_count.asc(),
            TestAttempt.time_taken_seconds.asc(),
            TestAttempt.submitted_at.asc(),
            TestAttempt.id.asc(),
        )
        .all()
    )

    total_participants = len(attempts)
    if total_participants == 0:
        return

    for idx, attempt in enumerate(attempts, start=1):
        attempt.rank_overall = idx
        attempt.percentile_overall = round(((total_participants - idx + 1) / total_participants) * 100, 2)

    batch_groups = defaultdict(list)
    institute_groups = defaultdict(list)

    for attempt in attempts:
        student = getattr(attempt, "student", None)

        batch_id = getattr(student, "batch_id", None)
        institute_id = getattr(student, "institute_id", None)

        if batch_id:
            batch_groups[batch_id].append(attempt)
        if institute_id:
            institute_groups[institute_id].append(attempt)

    for batch_id, batch_attempts in batch_groups.items():
        for idx, attempt in enumerate(batch_attempts, start=1):
            total = len(batch_attempts)
            attempt.rank_batch = idx
            attempt.percentile_batch = round(((total - idx + 1) / total) * 100, 2)

    for institute_id, institute_attempts in institute_groups.items():
        for idx, attempt in enumerate(institute_attempts, start=1):
            total = len(institute_attempts)
            attempt.rank_institute = idx
            attempt.percentile_institute = round(((total - idx + 1) / total) * 100, 2)

    for attempt in attempts:
        attempt.analytics_processed_at = utc_now()


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

    schedule_type = getattr(test, "schedule_type", "instant")

    if schedule_type == "fixed_start":
        if not getattr(test, "start_at", None):
            return False, "This test start time is not configured."
        if now < test.start_at:
            return False, "This test has not started yet."
        if getattr(test, "end_at", None) and now > test.end_at:
            return False, "This test time window has closed."

    elif schedule_type == "window":
        if not getattr(test, "start_at", None) or not getattr(test, "end_at", None):
            return False, "This test window is not configured."
        if now < test.start_at:
            return False, "This test window has not opened yet."
        if now > test.end_at:
            return False, "This test window has closed."

    max_attempts = getattr(test, "max_attempts", 1) or 1

    ongoing_attempt = TestAttempt.query.filter_by(
        test_id=test.id,
        student_id=student_id,
        status="ongoing"
    ).order_by(TestAttempt.id.desc()).first()

    if ongoing_attempt:
        return True, ongoing_attempt

    previous_submitted_count = TestAttempt.query.filter_by(
        test_id=test.id,
        student_id=student_id,
        status="submitted"
    ).count()

    if previous_submitted_count >= max_attempts:
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
    attempt.submitted_at = utc_now()
    attempt.time_taken_seconds = compute_attempt_time_taken_seconds(attempt)

    if auto_submitted and hasattr(attempt, "is_abandoned"):
        attempt.is_abandoned = False


def auto_submit_if_time_over(attempt):
    if attempt.status != "ongoing":
        return False

    remaining = get_attempt_remaining_seconds(attempt)
    if remaining > 0:
        return False

    finalize_attempt(attempt, auto_submitted=True)
    db.session.flush()
    recompute_test_rankings(attempt.test_id)
    db.session.commit()
    return True


def build_attempt_analytics(attempt):
    test_questions = TestQuestion.query.filter_by(
        test_id=attempt.test_id
    ).order_by(TestQuestion.display_order.asc()).all()

    answer_map = {
        answer.question_id: answer
        for answer in attempt.answers
    }

    subject_stats = {}
    chapter_stats = {}
    detailed_rows = []

    for idx, tq in enumerate(test_questions, start=1):
        q = tq.question
        ans = answer_map.get(q.id)

        selected_option = (ans.selected_option or "").strip().upper() if ans and ans.selected_option else ""
        correct_option = (q.correct_option or "").strip().upper()
        subject_name = q.subject.name if q.subject else "General"
        chapter_name = q.chapter.name if q.chapter else "General Chapter"
        time_spent = int(ans.time_spent_seconds or 0) if ans else 0

        if subject_name not in subject_stats:
            subject_stats[subject_name] = {
                "total": 0,
                "correct": 0,
                "wrong": 0,
                "skipped": 0,
                "score": 0.0,
                "time_spent": 0,
                "avg_time_per_question": 0,
                "avg_time_per_answered": 0,
                "accuracy": 0,
            }

        chapter_key = f"{subject_name}|||{chapter_name}"
        if chapter_key not in chapter_stats:
            chapter_stats[chapter_key] = {
                "subject_name": subject_name,
                "chapter_name": chapter_name,
                "total": 0,
                "correct": 0,
                "wrong": 0,
                "skipped": 0,
                "score": 0.0,
                "time_spent": 0,
                "avg_time_per_question": 0,
                "avg_time_per_answered": 0,
                "accuracy": 0,
            }

        subject_stats[subject_name]["total"] += 1
        subject_stats[subject_name]["time_spent"] += time_spent

        chapter_stats[chapter_key]["total"] += 1
        chapter_stats[chapter_key]["time_spent"] += time_spent

        status = "skipped"
        marks_delta = 0.0

        if not selected_option:
            subject_stats[subject_name]["skipped"] += 1
            chapter_stats[chapter_key]["skipped"] += 1
        elif selected_option == correct_option:
            status = "correct"
            marks_delta = float(tq.marks or 0)
            subject_stats[subject_name]["correct"] += 1
            subject_stats[subject_name]["score"] += marks_delta
            chapter_stats[chapter_key]["correct"] += 1
            chapter_stats[chapter_key]["score"] += marks_delta
        else:
            status = "wrong"
            marks_delta = -float(tq.negative_marks or 0)
            subject_stats[subject_name]["wrong"] += 1
            subject_stats[subject_name]["score"] += marks_delta
            chapter_stats[chapter_key]["wrong"] += 1
            chapter_stats[chapter_key]["score"] += marks_delta

        detailed_rows.append({
            "index": idx,
            "status": status,
            "question": q,
            "subject_name": subject_name,
            "chapter_name": chapter_name,
            "selected_option": selected_option,
            "correct_option": correct_option,
            "time_spent_seconds": time_spent,
            "time_spent_human": format_seconds_human(time_spent),
            "marks_delta": marks_delta,
            "is_marked_for_review": bool(ans.is_marked_for_review) if ans else False,
        })

    for stats in subject_stats.values():
        total = int(stats["total"] or 0)
        answered = int(stats["correct"] + stats["wrong"])
        stats["accuracy"] = round((stats["correct"] / total) * 100, 2) if total > 0 else 0
        stats["avg_time_per_question"] = round(stats["time_spent"] / total, 2) if total > 0 else 0
        stats["avg_time_per_answered"] = round(stats["time_spent"] / answered, 2) if answered > 0 else 0
        stats["time_spent_human"] = format_seconds_human(stats["time_spent"])

    chapter_rows = []
    for stats in chapter_stats.values():
        total = int(stats["total"] or 0)
        answered = int(stats["correct"] + stats["wrong"])
        stats["accuracy"] = round((stats["correct"] / total) * 100, 2) if total > 0 else 0
        stats["avg_time_per_question"] = round(stats["time_spent"] / total, 2) if total > 0 else 0
        stats["avg_time_per_answered"] = round(stats["time_spent"] / answered, 2) if answered > 0 else 0
        stats["time_spent_human"] = format_seconds_human(stats["time_spent"])
        chapter_rows.append(stats)

    chapter_rows.sort(key=lambda x: (x["accuracy"], x["score"], -x["time_spent"]))

    return test_questions, subject_stats, chapter_rows, detailed_rows


def build_student_overview(student_id):
    attempts = TestAttempt.query.filter_by(
        student_id=student_id,
        status="submitted"
    ).order_by(TestAttempt.id.desc()).all()

    overview = {
        "total_attempts": len(attempts),
        "avg_score": 0.0,
        "avg_accuracy": 0.0,
        "total_time_spent_seconds": 0,
        "total_time_spent_human": "0m 0s",
        "strongest_subject": None,
        "weakest_subject": None,
        "subject_rollup": {},
        "best_rank": None,
        "latest_rank": None,
        "avg_percentile": 0.0,
        "rank_history": [],
    }

    if not attempts:
        return overview

    total_score = 0.0
    total_questions = 0
    total_correct = 0
    subject_rollup = {}
    percentile_values = []
    rank_history = []

   for attempt in attempts:
       if attempt.percentile_overall is not None:
           percentile_values.append(float(attempt.percentile_overall))

       rank_history.append({
           "attempt_id": attempt.id,
           "test_title": attempt.test.title if attempt.test else "Test",
           "rank_overall": attempt.rank_overall,
           "percentile_overall": attempt.percentile_overall,
           "score": float(attempt.total_score or 0),
           "submitted_at": attempt.submitted_at,
       })

    for attempt in attempts:
        test_questions, subject_stats, _, _ = build_attempt_analytics(attempt)

        total_score += float(attempt.total_score or 0)
        total_questions += len(test_questions)
        total_correct += int(attempt.correct_count or 0)

        for subject_name, stats in subject_stats.items():
            if subject_name not in subject_rollup:
                subject_rollup[subject_name] = {
                    "total": 0,
                    "correct": 0,
                    "wrong": 0,
                    "skipped": 0,
                    "score": 0.0,
                    "time_spent": 0,
                }

            subject_rollup[subject_name]["total"] += stats["total"]
            subject_rollup[subject_name]["correct"] += stats["correct"]
            subject_rollup[subject_name]["wrong"] += stats["wrong"]
            subject_rollup[subject_name]["skipped"] += stats["skipped"]
            subject_rollup[subject_name]["score"] += stats["score"]
            subject_rollup[subject_name]["time_spent"] += stats["time_spent"]

    for stats in subject_rollup.values():
        total = int(stats["total"] or 0)
        stats["accuracy"] = round((stats["correct"] / total) * 100, 2) if total > 0 else 0
        stats["avg_time_per_question"] = round(stats["time_spent"] / total, 2) if total > 0 else 0
        stats["time_spent_human"] = format_seconds_human(stats["time_spent"])

    overview["avg_score"] = round(total_score / len(attempts), 2) if attempts else 0.0
    overview["avg_accuracy"] = round((total_correct / total_questions) * 100, 2) if total_questions > 0 else 0.0
    overview["subject_rollup"] = subject_rollup
    overview["total_time_spent_seconds"] = sum(v["time_spent"] for v in subject_rollup.values())
    overview["total_time_spent_human"] = format_seconds_human(overview["total_time_spent_seconds"])

    if subject_rollup:
        strongest = max(subject_rollup.items(), key=lambda x: (x[1]["accuracy"], x[1]["score"]))
        weakest = min(subject_rollup.items(), key=lambda x: (x[1]["accuracy"], x[1]["score"]))
        overview["strongest_subject"] = strongest
        overview["weakest_subject"] = weakest

    return overview


@student_bp.route("/dashboard")
@login_required
def dashboard():
    student_required()

    now = utc_now()

    available_tests = Test.query.filter_by(status="published").count()

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

    overview = build_student_overview(current_user.id)

    return render_template(
        "student_dashboard.html",
        available_tests=available_tests,
        ongoing_tests=ongoing_tests,
        completed_tests=completed_tests,
        latest_attempts=latest_attempts,
        ongoing_attempts=ongoing_attempts,
        overview=overview,
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
        now=now,
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
        started_at=now,
        expires_at=expires_at,
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

    if getattr(attempt.test, "is_resume_allowed", True) is False and request.args.get("resume") == "blocked":
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
        marked_for_review = bool(ans.is_marked_for_review) if ans else False

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
    time_spent_seconds = request.form.get("time_spent_seconds", type=int, default=0)

    test_question = TestQuestion.query.filter_by(
        test_id=attempt.test_id,
        question_id=question_id
    ).first_or_404()

    answer = get_or_create_answer(attempt.id, test_question.question_id)

    if selected_option not in ["A", "B", "C", "D"]:
        selected_option = None

    if time_spent_seconds and time_spent_seconds > 0:
        answer.time_spent_seconds = int(answer.time_spent_seconds or 0) + int(time_spent_seconds)

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
    db.session.flush()
    recompute_test_rankings(attempt.test_id)
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

    test_questions, subject_stats, chapter_stats, detailed_rows = build_attempt_analytics(attempt)

    total_questions = len(test_questions)
    accuracy = round((attempt.correct_count / total_questions) * 100, 2) if total_questions > 0 else 0.0

    duration_seconds = int((attempt.test.duration_minutes or 0) * 60)
    remaining_seconds = get_attempt_remaining_seconds(attempt)
    time_taken_seconds = max(0, duration_seconds - remaining_seconds)

    start_base = attempt.started_at or attempt.created_at
    if attempt.status == "submitted" and start_base:
        end_base = attempt.submitted_at or utc_now()
        raw_taken = int((end_base - start_base).total_seconds())
        time_taken_seconds = min(duration_seconds, max(0, raw_taken))

    strongest_subject = None
    weakest_subject = None
    if subject_stats:
        strongest_subject = max(subject_stats.items(), key=lambda x: (x[1]["accuracy"], x[1]["score"]))
        weakest_subject = min(subject_stats.items(), key=lambda x: (x[1]["accuracy"], x[1]["score"]))

    participants_count = TestAttempt.query.filter_by(
        test_id=attempt.test_id,
        status="submitted"
    ).count()

    return render_template(
        "student_test_result.html",
        attempt=attempt,
        test=attempt.test,
        subject_stats=subject_stats,
        chapter_stats=chapter_stats,
        detailed_rows=detailed_rows,
        total_questions=total_questions,
        accuracy=accuracy,
        time_taken_seconds=time_taken_seconds,
        strongest_subject=strongest_subject,
        weakest_subject=weakest_subject,
        participants_count=participants_count,
        rank_overall=attempt.rank_overall,
        rank_batch=attempt.rank_batch,
        rank_institute=attempt.rank_institute,
        percentile_overall=attempt.percentile_overall,
        percentile_batch=attempt.percentile_batch,
        percentile_institute=attempt.percentile_institute,
    )


@student_bp.route("/attempts/<int:attempt_id>/review")
@login_required
def review_page(attempt_id):
    student_required()

    attempt = TestAttempt.query.get_or_404(attempt_id)

    if attempt.student_id != current_user.id:
        abort(403)

    if attempt.status != "submitted":
        flash("Submit the test before opening review.", "danger")
        return redirect(url_for("student.attempt_page", attempt_id=attempt.id))

    test_questions, subject_stats, chapter_stats, detailed_rows = build_attempt_analytics(attempt)

    total_questions = len(test_questions)
    accuracy = round((attempt.correct_count / total_questions) * 100, 2) if total_questions > 0 else 0.0

    duration_seconds = int((attempt.test.duration_minutes or 0) * 60)
    remaining_seconds = get_attempt_remaining_seconds(attempt)
    time_taken_seconds = max(0, duration_seconds - remaining_seconds)

    start_base = attempt.started_at or attempt.created_at
    if attempt.status == "submitted" and start_base:
        end_base = attempt.submitted_at or utc_now()
        raw_taken = int((end_base - start_base).total_seconds())
        time_taken_seconds = min(duration_seconds, max(0, raw_taken))

    status_filter = (request.args.get("status") or "all").strip().lower()
    if status_filter in ["correct", "wrong", "skipped"]:
        detailed_rows = [row for row in detailed_rows if row["status"] == status_filter]

    return render_template(
        "student_test_review.html",
        attempt=attempt,
        test=attempt.test,
        subject_stats=subject_stats,
        chapter_stats=chapter_stats,
        detailed_rows=detailed_rows,
        status_filter=status_filter,
        total_questions=total_questions,
        accuracy=accuracy,
        time_taken_seconds=time_taken_seconds,
        time_taken_human=format_seconds_human(time_taken_seconds),
    )


@student_bp.route("/performance")
@login_required
def performance_review_page():
    student_required()

    attempts = TestAttempt.query.filter_by(
        student_id=current_user.id,
        status="submitted"
    ).order_by(TestAttempt.id.desc()).all()

    overview = build_student_overview(current_user.id)

    return render_template(
        "student_performance_review.html",
        attempts=attempts[:10],
        overview=overview,
    )
