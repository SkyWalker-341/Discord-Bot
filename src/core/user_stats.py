import json
import os
import datetime 
import uuid


DATA_FILE = os.path.join("data", "users.json")
PENDING_FILE = os.path.join("data", "pending.json")

def has_current_team_role(user_roles):
    """Check if user has the 'current-team' role."""
    role_names = [role.name.lower() for role in user_roles]
    return "current-team" in role_names

def load_user_data():
    """Loads user data from the users.json file."""
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_user_data(data):
    """Saves user data to the users.json file."""
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def load_pending_requests():
    """Loads pending requests from pending.json."""
    if not os.path.exists(PENDING_FILE):
        return []
    with open(PENDING_FILE, "r") as f:
        return json.load(f)

def save_pending_requests(data):
    """Saves pending requests to pending.json."""
    os.makedirs(os.path.dirname(PENDING_FILE), exist_ok=True)
    with open(PENDING_FILE, "w") as f:
        json.dump(data, f, indent=4)

def record_status_update(user_id, username, date, hours, description, blockers, is_wfh, is_late=False):
    """
    Records a new status update for a user with enhanced tracking.
    Now includes late submission tracking and better data structure.
    """
    data = load_user_data()
    user_id_str = str(user_id)
    
    # Ensure date is in correct format
    if isinstance(date, datetime.date):
        date_str = date.strftime("%d-%m-%Y")
    else:
        # If it's already a string, validate the format
        try:
            # Try to parse and reformat to ensure consistency
            parsed_date = datetime.datetime.strptime(str(date), "%d-%m-%Y").date()
            date_str = parsed_date.strftime("%d-%m-%Y")
        except ValueError:
            try:
                # Try parsing YYYY-MM-DD format and convert to DD-MM-YYYY
                parsed_date = datetime.datetime.strptime(str(date), "%Y-%m-%d").date()
                date_str = parsed_date.strftime("%d-%m-%Y")
            except ValueError:
                raise ValueError(f"Invalid date format: {date}. Expected DD-MM-YYYY format.")

    if user_id_str not in data:
        data[user_id_str] = {
            "username": username,
            "submissions": {},
            "total_hours": 0.0,
            "total_submissions": 0,
            "late_submissions": 0
        }
    
    # Update username if it changed
    data[user_id_str]["username"] = username
    
    submission_id = str(uuid.uuid4())
    submission_data = {
        "date": date_str,
        "hours": hours,
        "description": description,
        "blockers": blockers,
        "is_wfh": is_wfh,
        "is_late": is_late,
        "timestamp": datetime.datetime.now().isoformat()
    }
    
    # Check if this date already has a submission (override case)
    existing_submission = None
    for sub_id, sub_data in data[user_id_str]["submissions"].items():
        if sub_data["date"] == date_str:
            existing_submission = sub_id
            break
    
    if existing_submission:
        # Remove old hours from total before adding new ones
        old_hours = data[user_id_str]["submissions"][existing_submission]["hours"]
        data[user_id_str]["total_hours"] -= old_hours
        data[user_id_str]["submissions"][existing_submission] = submission_data
    else:
        # New submission
        data[user_id_str]["submissions"][submission_id] = submission_data
        data[user_id_str]["total_submissions"] += 1
        if is_late:
            data[user_id_str]["late_submissions"] += 1
    
    # Update total hours
    data[user_id_str]["total_hours"] += hours

    save_user_data(data)

def get_users_without_submission_for_date(guild_members, date):
    """Get list of current-team users who haven't submitted status for a specific date."""
    data = load_user_data()
    date_str = date.strftime("%d-%m-%Y")
    non_submitters = []
    
    for member in guild_members:
        if member.bot:
            continue
        
        # Only check current-team members
        if not has_current_team_role(member.roles):
            continue
            
        user_id_str = str(member.id)
        has_submission = False
        
        if user_id_str in data:
            submissions = data[user_id_str].get("submissions", {})
            for submission in submissions.values():
                if submission["date"] == date_str:
                    has_submission = True
                    break
        
        if not has_submission:
            non_submitters.append(member)
    
    return non_submitters

def get_user_submissions_for_date(user_id, date):
    """Get all submissions for a specific date."""
    data = load_user_data()
    user_id_str = str(user_id)
    date_str = date.strftime("%d-%m-%Y")
    
    if user_id_str not in data:
        return []
    
    submissions = []
    for submission in data[user_id_str].get("submissions", {}).values():
        if submission["date"] == date_str:
            submissions.append(submission)
    
    return submissions

def get_weekly_stats(user_id, week_start_date):
    """Get weekly statistics for a user."""
    data = load_user_data()
    user_id_str = str(user_id)
    
    if user_id_str not in data:
        return {
            "total_hours": 0.0,
            "submissions_count": 0,
            "target_met": False,
            "daily_breakdown": [],
            "remaining_hours": 32.0
        }
    
    # Calculate week end date (Sunday)
    week_end_date = week_start_date + datetime.timedelta(days=6)
    
    weekly_hours = 0.0
    submissions_count = 0
    daily_breakdown = []
    
    # Check each day of the week
    for i in range(7):
        current_date = week_start_date + datetime.timedelta(days=i)
        date_str = current_date.strftime("%d-%m-%Y")
        day_hours = 0.0
        
        submissions = data[user_id_str].get("submissions", {})
        for submission in submissions.values():
            if submission["date"] == date_str:
                day_hours += submission["hours"]
                submissions_count += 1
        
        weekly_hours += day_hours
        daily_breakdown.append({
            "date": date_str,
            "hours": day_hours,
            "day_name": current_date.strftime("%A")
        })
    
    return {
        "total_hours": weekly_hours,
        "submissions_count": submissions_count,
        "target_met": weekly_hours >= 32.0,
        "daily_breakdown": daily_breakdown,
        "remaining_hours": max(0, 32.0 - weekly_hours)
    }

def get_monthly_stats(user_id, month, year):
    """Get monthly statistics for a user."""
    data = load_user_data()
    user_id_str = str(user_id)
    
    if user_id_str not in data:
        return {
            "total_hours": 0.0,
            "total_submissions": 0,
            "late_submissions": 0,
            "days_worked": 0
        }
    
    monthly_hours = 0.0
    monthly_submissions = 0
    late_submissions = 0
    days_worked = set()
    
    submissions = data[user_id_str].get("submissions", {})
    for submission in submissions.values():
        try:
            sub_date = datetime.datetime.strptime(submission["date"], "%d-%m-%Y").date()
            if sub_date.month == month and sub_date.year == year:
                monthly_hours += submission["hours"]
                monthly_submissions += 1
                days_worked.add(submission["date"])
                
                if submission.get("is_late", False):
                    late_submissions += 1
        except ValueError:
            continue
    
    return {
        "total_hours": monthly_hours,
        "total_submissions": monthly_submissions,
        "late_submissions": late_submissions,
        "days_worked": len(days_worked)
    }

def count_user_statistics_for_range(user_id, from_date, to_date):
    """Count statistics for a specific date range."""
    data = load_user_data()
    user_id_str = str(user_id)
    
    # Load casual leave data
    casual_file = os.path.join("data", "casual_leave.json")
    casual_data = {}
    if os.path.exists(casual_file):
        with open(casual_file, "r") as f:
            casual_data = json.load(f)
    
    stats = {
        "total_status_updates": 0,
        "total_hours_worked": 0.0,
        "total_leaves": 0,
        "late_status_hours": 0.0,
        "total_submissions": 0
    }
    
    # Count status updates and hours within date range
    if user_id_str in data:
        submissions = data[user_id_str].get("submissions", {})
        
        for submission in submissions.values():
            try:
                sub_date = datetime.datetime.strptime(submission["date"], "%d-%m-%Y").date()
                if from_date <= sub_date <= to_date:
                    stats["total_status_updates"] += 1
                    stats["total_submissions"] += 1
                    stats["total_hours_worked"] += submission["hours"]
                    
                    if submission.get("is_late", False):
                        stats["late_status_hours"] += submission["hours"]
            except ValueError:
                continue
    
    # Count casual leaves within date range
    if user_id_str in casual_data:
        leaves = casual_data[user_id_str].get("leaves", [])
        for leave in leaves:
            try:
                leave_start = datetime.datetime.strptime(leave["start"], "%d-%m-%Y").date()
                if from_date <= leave_start <= to_date:
                    stats["total_leaves"] += 1
            except ValueError:
                continue
    
    return stats

def find_pending_request(request_id: str):
    """Finds a pending request by its unique ID."""
    requests = load_pending_requests()
    for request in requests:
        if request.get("request_id") == request_id:
            return request
    return None

def update_pending_request(request_id: str, status: str, approver_id: int):
    """Updates the status of a pending request and returns the updated request."""
    requests = load_pending_requests()
    updated_request = None
    for request in requests:
        if request.get("request_id") == request_id:
            request["status"] = status
            request["approver_id"] = approver_id
            request["updated_at"] = datetime.datetime.now().isoformat()
            updated_request = request
            break
    
    if updated_request:
        save_pending_requests(requests)
    return updated_request

def cleanup_old_pending_requests(days_old=30):
    """Remove pending requests older than specified days."""
    requests = load_pending_requests()
    cutoff_date = datetime.datetime.now() - datetime.timedelta(days=days_old)
    
    cleaned_requests = []
    for request in requests:
        try:
            created_at = datetime.datetime.fromisoformat(request.get("created_at", ""))
            if created_at > cutoff_date:
                cleaned_requests.append(request)
        except (ValueError, TypeError):
            # Keep requests with invalid dates for manual review
            cleaned_requests.append(request)
    
    save_pending_requests(cleaned_requests)
    return len(requests) - len(cleaned_requests)