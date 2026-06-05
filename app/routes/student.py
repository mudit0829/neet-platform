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


def _get_attr(obj, *names, default=None):
    for name in names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value is not None:
                return value
    return default


def _get_test_id(test_obj):
    return _get_attr(test_obj, "id", default=None)


def _get_attempt_test_id(attempt):
    return _get_attr(attempt, "test_id", "testid", default=None)


def _get_attempt_student_id(attempt):
    return _get_attr(attempt, "student_id", "studentid", default=None)


def _get_question_id(tq):
    return _get_attr(tq, "question_id", "questionid", default=None)


def _get_display_order(tq):
    value = _get_attr(tq, "display_order", "displayorder", default=0)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _get_test_duration_minutes(test):
    value = _get_attr(test, "duration_minutes", "durationminutes", default=0)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _get_test_status(test):
    return (_get_attr(test, "status", default="") or "").strip().lower()


def _get_test_schedule_type(test):
    return (_get_attr(test, "schedule_type", "scheduletype", default="instant") or "instant").strip().lower()


def _get_test_start_at(test):
    return _get_attr(test, "start_at", "startat", default=None)


def _get_test_end_at(test):
    return _get_attr(test, "end_at", "endat", default=None)


def _get_test_max_attempts(test):
    value = _get_attr(test, "max_attempts", "maxattempts", default=1)
    try:
        return int(value or 1)
    except (TypeError, ValueError):
        return 1


def _get_question_fields(question):
    subject = _get_attr(question, "subject", default=None)
    chapter = _get_attr(question, "chapter", default=None)
    return {
        "id": _get_attr(question, "id", default=None),
        "stem": _get_attr(question, "stem", default="") or "",
        "question_image": _get_attr(question, "question_image", "questionimage", default=None),
        "explanation_image": _get_attr(question, "explanation_image", "explanationimage", default=None),
        "option_a": _get_attr(question, "option_a", "optiona", default="") or "",
        "option_b": _get_attr(question, "option_b", "optionb", default="") or "",
        "option_c": _get_attr(question, "option_c", "optionc", default="") or "",
        "option_d": _get_attr(question, "option_d", "optiond", default="") or "",
        "correct_option": (_get_attr(question, "correct_option", "correctoption", default="") or "").strip().upper(),
        "explanation": _get_attr(question, "explanation", default="") or "",
        "subject_name": _get_attr(subject, "name", default="General") or "General",
        "chapter_name": _get_attr(chapter, "name", default="General") or "General",
    }


def format_seconds_human(total_seconds):
    total_seconds = int(total_seconds or 0)
    hrs = total_seconds // 3600
    mins = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    if hrs > 0:
        return f"{hrs}h {mins}m {secs}s"
    return f"{mins}m {secs}s"


def get_attempt_questions(attempt):
    test_id = _get_attempt_test_id(attempt)
    if not test_id:
        return []

    rows = TestQuestion.query.filter_by(test_id=test_id).all()
    rows.sort(key=_get_display_order)
    return rows


def get_attempt_answers(attempt):
    answers = _get_attr(attempt, "answers", default=None)
    if answers is not None:
        return list(answers)

    answers = _get_attr(attempt, "attempt_answers", default=None)
    if answers is not None:
        return list(answers)

    answers = _get_attr(attempt, "responses", default=None)
    if answers is not None:
        return list(answers)

    test_id = _get_attempt_test_id(attempt)
    attempt_id = _get_attr(attempt, "id", default=None)
    if not test_id or attempt_id is None:
        return []

    return AttemptAnswer.query.filter_by(attempt_id=attempt_id).all()


def get_answer_map(attempt):
    answer_map = {}
    for answer in get_attempt_answers(attempt):
        qid = _get_attr(answer, "question_id", "questionid", default=None)
        if qid is not None:
            answer_map[qid] = answer
    return answer_map


def get_attempt_remaining_seconds(attempt):
    now = utc_now()

    expires_at = _get_attr(attempt, "expires_at", "expiresat", default=None)
    if expires_at:
        remaining = int((expires_at - now).total_seconds())
        return max(0, remaining)

    test = _get_attr(attempt, "test", default=None)
    duration_seconds = _get_test_duration_minutes(test) * 60 if test else 0

    start_base = _get_attr(attempt, "started_at", "startedat", default=None) or _get_attr(attempt, "created_at", "createdat", default=None)
    if not start_base or duration_seconds <= 0:
        return 0

    elapsed = int((now - start_base).total_seconds())
    remaining = duration_seconds - elapsed
    return max(0, remaining)


def compute_attempt_time_taken_seconds(attempt):
    test = _get_attr(attempt, "test", default=None)
    duration_seconds = _get_test_duration_minutes(test) * 60 if test else 0

    start_base = _get_attr(attempt, "started_at", "startedat", default=None) or _get_attr(attempt, "created_at", "createdat", default=None)
    if not start_base:
        return 0

    if _get_attr(attempt, "status", default="") == "submitted":
        end_base = _get_attr(attempt, "submitted_at", "submittedat", default=None) or utc_now()
        raw_taken = int((end_base - start_base).total_seconds())
        if duration_seconds > 0:
            return min(duration_seconds, max(0, raw_taken))
        return max(0, raw_taken)

    remaining_seconds = get_attempt_remaining_seconds(attempt)
    if duration_seconds <= 0:
        return 0
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

        batch_id = _get_attr(student, "batch_id", "batchid", default=None)
        institute_id = _get_attr(student, "institute_id", "instituteid", default=None)

        if batch_id:
            batch_groups[batch_id].append(attempt)
        if institute_id:
            institute_groups[institute_id].append(attempt)

    for batch_attempts in batch_groups.values():
        total = len(batch_attempts)
        for idx, attempt in enumerate(batch_attempts, start=1):
            attempt.rank_batch = idx
            attempt.percentile_batch = round(((total - idx + 1) / total) * 100, 2)

    for institute_attempts in institute_groups.values():
        total = len(institute_attempts)
        for idx, attempt in enumerate(institute_attempts, start=1):
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

    if _get_test_status(test) != "published":
        return False, "This test is not available."

    question_count = TestQuestion.query.filter_by(test_id=_get_test_id(test)).count()
    if question_count <= 0:
        return False, "This test has no questions yet."

    schedule_type = _get_test_schedule_type(test)

    if schedule_type == "fixed_start":
        start_at = _get_test_start_at(test)
        end_at = _get_test_end_at(test)
        if not start_at:
            return False, "This test start time is not configured."
        if now < start_at:
            return False, "This test has not started yet."
        if end_at and now > end_at:
            return False, "This test time window has closed."

    elif schedule_type == "window":
        start_at = _get_test_start_at(test)
        end_at = _get_test_end_at(test)
        if not start_at or not end_at:
            return False, "This test window is not configured."
        if now < start_at:
            return False, "This test window has not opened yet."
        if now > end_at:
            return False, "This test window has closed."

    max_attempts = _get_test_max_attempts(test)

    ongoing_attempt = TestAttempt.query.filter_by(
        test_id=_get_test_id(test),
        student_id=student_id,
        status="ongoing"
    ).order_by(TestAttempt.id.desc()).first()

    if ongoing_attempt:
        return True, ongoing_attempt

    previous_submitted_count = TestAttempt.query.filter_by(
        test_id=_get_test_id(test),
        student_id=student_id,
        status="submitted"
    ).count()

    if previous_submitted_count >= max_attempts:
        return False, "Maximum allowed attempts reached."

    return True, None


def calculate_attempt_expiry(test, started_at):
    duration_minutes = _get_test_duration_minutes(test)
    duration_delta = timedelta(minutes=duration_minutes)
    schedule_type = _get_test_schedule_type(test)

    start_at = _get_test_start_at(test)

    if schedule_type == "fixed_start":
        fixed_start = start_at or started_at
        fixed_end = fixed_start + duration_delta
        end_at = _get_test_end_at(test)
        if end_at:
            return min(fixed_end, end_at)
        return fixed_end

    if schedule_type == "window":
        rolling_end = started_at + duration_delta
        end_at = _get_test_end_at(test)
        if end_at:
            return min(rolling_end, end_at)
        return rolling_end

    return started_at + duration_delta


def finalize_attempt(attempt, auto_submitted=False):
    if _get_attr(attempt, "status", default="") == "submitted":
        return

    test_questions = get_attempt_questions(attempt)
    answer_map = get_answer_map(attempt)

    total_score = 0.0
    correct_count = 0
    wrong_count = 0
    skipped_count = 0

    for tq in test_questions:
        question_id = _get_question_id(tq)
        question = _get_attr(tq, "question", default=None)
        answer = answer_map.get(question_id)

        selected_option = ""
        if answer and _get_attr(answer, "selected_option", "selectedoption", default=None):
            selected_option = (_get_attr(answer, "selected_option", "selectedoption", default="") or "").strip().upper()

        correct_option = (_get_attr(question, "correct_option", "correctoption", default="") or "").strip().upper()

        if not selected_option:
            skipped_count += 1
        elif selected_option == correct_option:
            correct_count += 1
            total_score += float(_get_attr(tq, "marks", default=0) or 0)
        else:
            wrong_count += 1
            total_score -= float(_get_attr(tq, "negative_marks", "negativemarks", default=0) or 0)

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
    if _get_attr(attempt, "status", default="") != "ongoing":
        return False

    remaining = get_attempt_remaining_seconds(attempt)
    if remaining > 0:
        return False

    finalize_attempt(attempt, auto_submitted=True)
    db.session.flush()
    recompute_test_rankings(_get_attempt_test_id(attempt))
    db.session.commit()
    return True


def build_attempt_analytics(attempt):
    test_questions = get_attempt_questions(attempt)
    answer_map = get_answer_map(attempt)

    subject_stats = {}
    chapter_stats = {}
    detailed_rows = []

    for idx, tq in enumerate(test_questions, start=1):
        q = _get_attr(tq, "question", default=None)
        if not q:
            continue

        ans = answer_map.get(_get_attr(q, "id", default=None))

        selected_option = (_get_attr(ans, "selected_option", "selectedoption", default="") or "").strip().upper() if ans else ""
        correct_option = (_get_attr(q, "correct_option", "correctoption", default="") or "").strip().upper()
        subject_name = _get_attr(_get_attr(q, "subject", default=None), "name", default="General") or "General"
        chapter_name = _get_attr(_get_attr(q, "chapter", default=None), "name", default="General Chapter") or "General Chapter"

        time_spent = 0
        if ans:
            try:
                time_spent = int(_get_attr(ans, "time_spent_seconds", "timespentseconds", default=0) or 0)
            except (TypeError, ValueError):
                time_spent = 0

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
            marks_delta = float(_get_attr(tq, "marks", default=0) or 0)
            subject_stats[subject_name]["correct"] += 1
            subject_stats[subject_name]["score"] += marks_delta
            chapter_stats[chapter_key]["correct"] += 1
            chapter_stats[chapter_key]["score"] += marks_delta
        else:
            status = "wrong"
            marks_delta = -float(_get_attr(tq, "negative_marks", "negativemarks", default=0) or 0)
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
            "is_marked_for_review": bool(_get_attr(ans, "is_marked_for_review", "ismarkedforreview", default=False)) if ans else False,
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


def build_review_questions(attempt):
    test_questions = get_attempt_questions(attempt)
    answer_map = get_answer_map(attempt)
    review_questions = []

    for idx, tq in enumerate(test_questions, start=1):
        q = _get_attr(tq, "question", default=None)
        if not q:
            continue

        ans = answer_map.get(_get_attr(q, "id", default=None))

        selected_option = (_get_attr(ans, "selected_option", "selectedoption", default=None) or "").strip().upper()
        correct_option = (_get_attr(q, "correct_option", "correctoption", default="") or "").strip().upper()
        is_skipped = not selected_option
        is_correct = bool(selected_option and correct_option and selected_option == correct_option)
        is_marked_for_review = bool(_get_attr(ans, "is_marked_for_review", "ismarkedforreview", default=False)) if ans else False

        try:
            time_spent_seconds = int(_get_attr(ans, "time_spent_seconds", "timespentseconds", default=0) or 0) if ans else 0
        except (TypeError, ValueError):
            time_spent_seconds = 0

        qf = _get_question_fields(q)

        review_questions.append({
            "index": idx,
            "question_id": qf["id"],
            "stem": qf["stem"],
            "question_image": qf["question_image"],
            "subject_name": qf["subject_name"],
            "chapter_name": qf["chapter_name"],
            "option_a": qf["option_a"],
            "option_b": qf["option_b"],
            "option_c": qf["option_c"],
            "option_d": qf["option_d"],
            "correct_option": correct_option,
            "selected_option": selected_option,
            "is_correct": is_correct,
            "is_skipped": is_skipped,
            "is_marked_for_review": is_marked_for_review,
            "time_spent_seconds": time_spent_seconds,
            "time_spent_human": format_seconds_human(time_spent_seconds),
            "explanation": qf["explanation"],
            "explanation_image": qf["explanation_image"],
        })

    return review_questions


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
        if _get_attr(attempt, "percentile_overall", "percentileoverall", default=None) is not None:
            percentile_values.append(float(_get_attr(attempt, "percentile_overall", "percentileoverall")))

        rank_history.append({
            "attempt_id": _get_attr(attempt, "id", default=None),
            "test_title": _get_attr(_get_attr(attempt, "test", default=None), "title", default="Test") or "Test",
            "rank_overall": _get_attr(attempt, "rank_overall", "rankoverall", default=None),
            "percentile_overall": _get_attr(attempt, "percentile_overall", "percentileoverall", default=None),
            "score": float(_get_attr(attempt, "total_score", "totalscore", default=0) or 0),
            "submitted_at": _get_attr(attempt, "submitted_at", "submittedat", default=None),
        })

    for attempt in attempts:
        test_questions, subject_stats, _, _ = build_attempt_analytics(attempt)

        total_score += float(_get_attr(attempt, "total_score", "totalscore", default=0) or 0)
        total_questions += len(test_questions)
        total_correct += int(_get_attr(attempt, "correct_count", "correctcount", default=0) or 0)

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

    valid_ranks = [
        _get_attr(a, "rank_overall", "rankoverall", default=None)
        for a in attempts
        if _get_attr(a, "rank_overall", "rankoverall", default=None) is not None
    ]
    overview["best_rank"] = min(valid_ranks) if valid_ranks else None
    overview["latest_rank"] = _get_attr(attempts[0], "rank_overall", "rankoverall", default=None) if attempts else None
    overview["avg_percentile"] = round(sum(percentile_values) / len(percentile_values), 2) if percentile_values else 0.0
    overview["rank_history"] = rank_history[:10]

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
        if _get_attr(attempt, "expires_at", "expiresat", default=None) and now >= _get_attr(attempt, "expires_at", "expiresat"):
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
        schedule_type = _get_test_schedule_type(test)

        if schedule_type == "fixed_start":
            if _get_test_end_at(test) and now > _get_test_end_at(test):
                continue
        elif schedule_type == "window":
            if _get_test_end_at(test) and now > _get_test_end_at(test):
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

    if _get_test_status(test) != "published":
        flash("This test is not available.", "danger")
        return redirect(url_for("student.tests_page"))

    question_count = TestQuestion.query.filter_by(test_id=_get_test_id(test)).count()

    ongoing_attempt = TestAttempt.query.filter_by(
        test_id=_get_test_id(test),
        student_id=current_user.id,
        status="ongoing"
    ).order_by(TestAttempt.id.desc()).first()

    submitted_attempt = TestAttempt.query.filter_by(
        test_id=_get_test_id(test),
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
        test_id=_get_test_id(test),
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

    if _get_attempt_student_id(attempt) != current_user.id:
        abort(403)

    if auto_submit_if_time_over(attempt):
        flash("Time is over. Your test was submitted automatically.", "info")
        return redirect(url_for("student.result_page", attempt_id=attempt.id))

    if _get_attr(attempt, "status", default="") == "submitted":
        return redirect(url_for("student.result_page", attempt_id=attempt.id))

    if getattr(attempt.test, "is_resume_allowed", True) is False and request.args.get("resume") == "blocked":
        flash("Resume is not allowed for this test.", "danger")
        return redirect(url_for("student.tests_page"))

    question_number = request.args.get("q", type=int, default=1)

    test_questions = get_attempt_questions(attempt)

    if not test_questions:
        flash("This test has no questions.", "danger")
        return redirect(url_for("student.tests_page"))

    total_questions = len(test_questions)

    if question_number < 1:
        question_number = 1
    if question_number > total_questions:
        question_number = total_questions

    current_test_question = test_questions[question_number - 1]
    current_question = _get_attr(current_test_question, "question", default=None)

    answer_map = {}
    for item in test_questions:
        qid = _get_question_id(item)
        if qid is not None:
            answer_map[qid] = get_or_create_answer(attempt.id, qid)

    db.session.commit()

    current_answer = answer_map.get(_get_attr(current_question, "id", default=None))

    subject_groups = defaultdict(list)
    answered_count = 0

    for index, tq in enumerate(test_questions, start=1):
        q = _get_attr(tq, "question", default=None)
        if not q:
            continue

        ans = answer_map.get(_get_attr(q, "id", default=None))

        selected_option = (_get_attr(ans, "selected_option", "selectedoption", default="") or "").strip() if ans else ""
        marked_for_review = bool(_get_attr(ans, "is_marked_for_review", "ismarkedforreview", default=False)) if ans else False

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

        subject_name = _get_attr(_get_attr(q, "subject", default=None), "name", default="General") or "General"
        subject_groups[subject_name].append({
            "index": index,
            "question_id": _get_attr(q, "id", default=None),
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

    if _get_attempt_student_id(attempt) != current_user.id:
        abort(403)

    if auto_submit_if_time_over(attempt):
        flash("Time is over. Your test was submitted automatically.", "info")
        return redirect(url_for("student.result_page", attempt_id=attempt.id))

    if _get_attr(attempt, "status", default="") != "ongoing":
        return redirect(url_for("student.result_page", attempt_id=attempt.id))

    question_id = request.form.get("question_id", type=int)
    question_number = request.form.get("question_number", type=int, default=1)
    action_type = (request.form.get("action_type") or "save_next").strip()
    selected_option = (request.form.get("selected_option") or "").strip().upper()
    time_spent_seconds = request.form.get("time_spent_seconds", type=int, default=0)

    test_question = TestQuestion.query.filter_by(
        test_id=_get_attempt_test_id(attempt),
        question_id=question_id
    ).first_or_404()

    answer = get_or_create_answer(attempt.id, _get_question_id(test_question))

    if selected_option not in ["A", "B", "C", "D"]:
        selected_option = None

    if time_spent_seconds and time_spent_seconds > 0:
        answer.time_spent_seconds = int(_get_attr(answer, "time_spent_seconds", "timespentseconds", default=0) or 0) + int(time_spent_seconds)

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

    total_questions = TestQuestion.query.filter_by(test_id=_get_attempt_test_id(attempt)).count()
    next_question_number = question_number

    if action_type in ["save_next", "mark_review"] and question_number < total_questions:
        next_question_number = question_number + 1

    return redirect(url_for("student.attempt_page", attempt_id=attempt.id, q=next_question_number))


@student_bp.route("/attempts/<int:attempt_id>/submit", methods=["POST"])
@login_required
def submit_attempt(attempt_id):
    student_required()

    attempt = TestAttempt.query.get_or_404(attempt_id)

    if _get_attempt_student_id(attempt) != current_user.id:
        abort(403)

    if _get_attr(attempt, "status", default="") == "submitted":
        return redirect(url_for("student.result_page", attempt_id=attempt.id))

    finalize_attempt(attempt)
    db.session.flush()
    recompute_test_rankings(_get_attempt_test_id(attempt))
    db.session.commit()

    flash("Test submitted successfully.", "success")
    return redirect(url_for("student.result_page", attempt_id=attempt.id))


@student_bp.route("/attempts/<int:attempt_id>/result")
@login_required
def result_page(attempt_id):
    student_required()

    attempt = TestAttempt.query.get_or_404(attempt_id)

    if _get_attempt_student_id(attempt) != current_user.id:
        abort(403)

    if _get_attr(attempt, "status", default="") == "ongoing":
        if auto_submit_if_time_over(attempt):
            flash("Time is over. Your test was submitted automatically.", "info")
        else:
            flash("Complete and submit your test first.", "danger")
            return redirect(url_for("student.attempt_page", attempt_id=attempt.id))

    test_questions, subject_stats, chapter_stats, detailed_rows = build_attempt_analytics(attempt)
    review_questions = build_review_questions(attempt)

    total_questions = len(test_questions)
    correct_count = int(_get_attr(attempt, "correct_count", "correctcount", default=0) or 0)
    accuracy = round((correct_count / total_questions) * 100, 2) if total_questions > 0 else 0.0

    duration_seconds = _get_test_duration_minutes(_get_attr(attempt, "test", default=None)) * 60
    remaining_seconds = get_attempt_remaining_seconds(attempt)
    time_taken_seconds = max(0, duration_seconds - remaining_seconds)

    start_base = _get_attr(attempt, "started_at", "startedat", default=None) or _get_attr(attempt, "created_at", "createdat", default=None)
    if _get_attr(attempt, "status", default="") == "submitted" and start_base:
        end_base = _get_attr(attempt, "submitted_at", "submittedat", default=None) or utc_now()
        raw_taken = int((end_base - start_base).total_seconds())
        if duration_seconds > 0:
            time_taken_seconds = min(duration_seconds, max(0, raw_taken))
        else:
            time_taken_seconds = max(0, raw_taken)

    strongest_subject = None
    weakest_subject = None
    if subject_stats:
        strongest_subject = max(subject_stats.items(), key=lambda x: (x[1]["accuracy"], x[1]["score"]))
        weakest_subject = min(subject_stats.items(), key=lambda x: (x[1]["accuracy"], x[1]["score"]))

    participants_count = TestAttempt.query.filter_by(
        test_id=_get_attempt_test_id(attempt),
        status="submitted"
    ).count()

    return render_template(
        "student_test_result.html",
        attempt=attempt,
        test=attempt.test,
        subject_stats=subject_stats,
        chapter_stats=chapter_stats,
        detailed_rows=detailed_rows,
        review_questions=review_questions,
        total_questions=total_questions,
        accuracy=accuracy,
        time_taken_seconds=time_taken_seconds,
        time_taken_human=format_seconds_human(time_taken_seconds),
        strongest_subject=strongest_subject,
        weakest_subject=weakest_subject,
        participants_count=participants_count,
        rank_overall=_get_attr(attempt, "rank_overall", "rankoverall", default=None),
        rank_batch=_get_attr(attempt, "rank_batch", "rankbatch", default=None),
        rank_institute=_get_attr(attempt, "rank_institute", "rankinstitute", default=None),
        percentile_overall=_get_attr(attempt, "percentile_overall", "percentileoverall", default=None),
        percentile_batch=_get_attr(attempt, "percentile_batch", "percentilebatch", default=None),
        percentile_institute=_get_attr(attempt, "percentile_institute", "percentileinstitute", default=None),
    )


@student_bp.route("/attempts/<int:attempt_id>/review")
@login_required
def review_page(attempt_id):
    student_required()

    attempt = TestAttempt.query.get_or_404(attempt_id)

    if _get_attempt_student_id(attempt) != current_user.id:
        abort(403)

    if _get_attr(attempt, "status", default="") != "submitted":
        flash("Submit the test before opening review.", "danger")
        return redirect(url_for("student.attempt_page", attempt_id=attempt.id))

    test_questions, subject_stats, chapter_stats, detailed_rows = build_attempt_analytics(attempt)

    total_questions = len(test_questions)
    correct_count = int(_get_attr(attempt, "correct_count", "correctcount", default=0) or 0)
    accuracy = round((correct_count / total_questions) * 100, 2) if total_questions > 0 else 0.0

    duration_seconds = _get_test_duration_minutes(_get_attr(attempt, "test", default=None)) * 60
    remaining_seconds = get_attempt_remaining_seconds(attempt)
    time_taken_seconds = max(0, duration_seconds - remaining_seconds)

    start_base = _get_attr(attempt, "started_at", "startedat", default=None) or _get_attr(attempt, "created_at", "createdat", default=None)
    if _get_attr(attempt, "status", default="") == "submitted" and start_base:
        end_base = _get_attr(attempt, "submitted_at", "submittedat", default=None) or utc_now()
        raw_taken = int((end_base - start_base).total_seconds())
        if duration_seconds > 0:
            time_taken_seconds = min(duration_seconds, max(0, raw_taken))
        else:
            time_taken_seconds = max(0, raw_taken)

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
