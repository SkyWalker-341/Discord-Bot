import datetime
import uuid

from .storage import guild_data_path, locked_path, read_json, write_json_atomic
from .utils import has_current_team_role

USERS_FILENAME = "users.json"
PENDING_FILENAME = "pending.json"
CASUAL_LEAVE_FILENAME = "casual_leave.json"


def _users_path(guild_id: int):
    return guild_data_path(guild_id, USERS_FILENAME)


def _pending_path(guild_id: int):
    return guild_data_path(guild_id, PENDING_FILENAME)


def _casual_leave_path(guild_id: int):
    return guild_data_path(guild_id, CASUAL_LEAVE_FILENAME)


def load_user_data(guild_id: int):
    """Loads user data for a guild from users.json."""
    return read_json(_users_path(guild_id), {})


def save_user_data(guild_id: int, data):
    """Saves user data for a guild."""
    path = _users_path(guild_id)
    with locked_path(path):
        write_json_atomic(path, data)


def load_pending_requests(guild_id: int):
    """Loads pending requests for a guild."""
    return read_json(_pending_path(guild_id), [])


def save_pending_requests(guild_id: int, data):
    """Saves pending requests for a guild."""
    path = _pending_path(guild_id)
    with locked_path(path):
        write_json_atomic(path, data)


def record_status_update(
    guild_id: int,
    user_id,
    username,
    date,
    hours,
    description,
    blockers,
    is_wfh,
    is_late=False,
):
    """
    Record a new status update for a user with atomic guild-scoped storage.
    """
    path = _users_path(guild_id)
    with locked_path(path):
        data = read_json(path, {})
        user_id_str = str(user_id)

        if isinstance(date, datetime.date):
            date_str = date.strftime("%d-%m-%Y")
        else:
            try:
                parsed_date = datetime.datetime.strptime(str(date), "%d-%m-%Y").date()
                date_str = parsed_date.strftime("%d-%m-%Y")
            except ValueError:
                try:
                    parsed_date = datetime.datetime.strptime(str(date), "%Y-%m-%d").date()
                    date_str = parsed_date.strftime("%d-%m-%Y")
                except ValueError as exc:
                    raise ValueError(
                        f"Invalid date format: {date}. Expected DD-MM-YYYY format."
                    ) from exc

        if user_id_str not in data:
            data[user_id_str] = {
                "username": username,
                "submissions": {},
                "total_hours": 0.0,
                "total_submissions": 0,
                "late_submissions": 0,
            }

        data[user_id_str]["username"] = username

        submission_id = str(uuid.uuid4())
        submission_data = {
            "date": date_str,
            "hours": hours,
            "description": description,
            "blockers": blockers,
            "is_wfh": is_wfh,
            "is_late": is_late,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

        existing_submission = None
        for sub_id, sub_data in data[user_id_str]["submissions"].items():
            if sub_data["date"] == date_str:
                existing_submission = sub_id
                break

        if existing_submission:
            old_submission = data[user_id_str]["submissions"][existing_submission]
            old_hours = old_submission["hours"]
            data[user_id_str]["total_hours"] -= old_hours

            if old_submission.get("is_late", False) and not is_late:
                data[user_id_str]["late_submissions"] = max(
                    0, data[user_id_str]["late_submissions"] - 1
                )
            elif not old_submission.get("is_late", False) and is_late:
                data[user_id_str]["late_submissions"] += 1

            data[user_id_str]["submissions"][existing_submission] = submission_data
        else:
            data[user_id_str]["submissions"][submission_id] = submission_data
            data[user_id_str]["total_submissions"] += 1
            if is_late:
                data[user_id_str]["late_submissions"] += 1

        data[user_id_str]["total_hours"] += hours
        write_json_atomic(path, data)


def get_users_without_submission_for_date(guild_id: int, guild_members, date):
    """Get current-team users who have not submitted status for a specific date."""
    data = load_user_data(guild_id)
    submitted_user_ids = get_submission_user_ids_for_date(guild_id, date, data=data)
    non_submitters = []

    for member in guild_members:
        if member.bot:
            continue
        if not has_current_team_role(member.roles):
            continue
        if member.id not in submitted_user_ids:
            non_submitters.append(member)

    return non_submitters


def get_submission_user_ids_for_date(guild_id: int, date, data=None) -> set[int]:
    """Return the set of user IDs that submitted a status update on a specific date."""
    data = load_user_data(guild_id) if data is None else data
    date_str = date.strftime("%d-%m-%Y")
    submitted_user_ids: set[int] = set()

    for user_id_str, user_record in data.items():
        submissions = user_record.get("submissions", {})
        for submission in submissions.values():
            if submission.get("date") == date_str:
                try:
                    submitted_user_ids.add(int(user_id_str))
                except (TypeError, ValueError):
                    pass
                break

    return submitted_user_ids


def get_user_submissions_for_date(guild_id: int, user_id, date, data=None):
    """Get all submissions for a user on a specific date."""
    data = load_user_data(guild_id) if data is None else data
    user_id_str = str(user_id)
    date_str = date.strftime("%d-%m-%Y")

    if user_id_str not in data:
        return []

    return [
        submission
        for submission in data[user_id_str].get("submissions", {}).values()
        if submission["date"] == date_str
    ]


def get_weekly_stats(guild_id: int, user_id, week_start_date):
    """Get weekly statistics for a user."""
    data = load_user_data(guild_id)
    user_id_str = str(user_id)

    if user_id_str not in data:
        return {
            "total_hours": 0.0,
            "submissions_count": 0,
            "target_met": False,
            "daily_breakdown": [],
            "remaining_hours": 32.0,
        }

    weekly_hours = 0.0
    submissions_count = 0
    daily_breakdown = []
    submissions = data[user_id_str].get("submissions", {})

    for offset in range(7):
        current_date = week_start_date + datetime.timedelta(days=offset)
        date_str = current_date.strftime("%d-%m-%Y")
        day_hours = 0.0

        for submission in submissions.values():
            if submission["date"] == date_str:
                day_hours += submission["hours"]
                submissions_count += 1

        weekly_hours += day_hours
        daily_breakdown.append(
            {
                "date": date_str,
                "hours": day_hours,
                "day_name": current_date.strftime("%A"),
            }
        )

    return {
        "total_hours": weekly_hours,
        "submissions_count": submissions_count,
        "target_met": weekly_hours >= 32.0,
        "daily_breakdown": daily_breakdown,
        "remaining_hours": max(0, 32.0 - weekly_hours),
    }


def get_monthly_stats(guild_id: int, user_id, month, year):
    """Get monthly statistics for a user."""
    data = load_user_data(guild_id)
    user_id_str = str(user_id)

    if user_id_str not in data:
        return {
            "total_hours": 0.0,
            "total_submissions": 0,
            "late_submissions": 0,
            "days_worked": 0,
        }

    monthly_hours = 0.0
    monthly_submissions = 0
    late_submissions = 0
    days_worked = set()

    for submission in data[user_id_str].get("submissions", {}).values():
        try:
            sub_date = datetime.datetime.strptime(submission["date"], "%d-%m-%Y").date()
        except ValueError:
            continue

        if sub_date.month == month and sub_date.year == year:
            monthly_hours += submission["hours"]
            monthly_submissions += 1
            days_worked.add(submission["date"])
            if submission.get("is_late", False):
                late_submissions += 1

    return {
        "total_hours": monthly_hours,
        "total_submissions": monthly_submissions,
        "late_submissions": late_submissions,
        "days_worked": len(days_worked),
    }


def count_user_statistics_for_range(guild_id: int, user_id, from_date, to_date):
    """Count statistics for a specific date range."""
    data = load_user_data(guild_id)
    casual_data = read_json(_casual_leave_path(guild_id), {})
    user_id_str = str(user_id)

    stats = {
        "total_status_updates": 0,
        "total_hours_worked": 0.0,
        "total_leaves": 0,
        "late_status_hours": 0.0,
        "total_submissions": 0,
    }

    if user_id_str in data:
        submissions = data[user_id_str].get("submissions", {})
        for submission in submissions.values():
            try:
                sub_date = datetime.datetime.strptime(submission["date"], "%d-%m-%Y").date()
            except ValueError:
                continue

            if from_date <= sub_date <= to_date:
                stats["total_status_updates"] += 1
                stats["total_submissions"] += 1
                stats["total_hours_worked"] += submission["hours"]
                if submission.get("is_late", False):
                    stats["late_status_hours"] += submission["hours"]

    if user_id_str in casual_data:
        for leave in casual_data[user_id_str].get("leaves", []):
            try:
                leave_start = datetime.datetime.strptime(leave["start"], "%d-%m-%Y").date()
            except ValueError:
                continue

            if from_date <= leave_start <= to_date:
                stats["total_leaves"] += 1

    return stats


def find_pending_request(guild_id: int, request_id: str):
    """Find a request by its unique ID inside a guild."""
    requests = load_pending_requests(guild_id)
    for request in requests:
        if request.get("request_id") == request_id:
            return request
    return None


def update_pending_request(
    guild_id: int,
    request_id: str,
    status: str,
    approver_id: int,
    expected_status: str = "pending",
):
    """Atomically update a request status and return the updated request."""
    path = _pending_path(guild_id)
    with locked_path(path):
        requests = read_json(path, [])
        updated_request = None

        for request in requests:
            if request.get("request_id") != request_id:
                continue
            if expected_status and request.get("status") != expected_status:
                return None

            request["status"] = status
            request["approver_id"] = approver_id
            request["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            updated_request = request
            break

        if updated_request:
            write_json_atomic(path, requests)
        return updated_request


def cleanup_old_pending_requests(guild_id: int, days_old=30):
    """Remove pending requests older than the specified number of days."""
    path = _pending_path(guild_id)
    with locked_path(path):
        requests = read_json(path, [])
        cutoff_date = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days_old)

        cleaned_requests = []
        for request in requests:
            try:
                created_at = datetime.datetime.fromisoformat(request.get("created_at", ""))
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=datetime.timezone.utc)
            except (ValueError, TypeError):
                cleaned_requests.append(request)
                continue

            if created_at > cutoff_date:
                cleaned_requests.append(request)

        write_json_atomic(path, cleaned_requests)
        return len(requests) - len(cleaned_requests)
