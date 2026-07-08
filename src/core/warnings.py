import datetime
import json
import discord
from discord.utils import escape_markdown, escape_mentions
from ..core.utils import has_current_team_role
from .hierarchy import can_act_on_member, get_role_display_name, get_user_level

# Import from config instead of hardcoding
from ..config import (
    WARNING_CHANNEL_ID,
    FIRST_PROBATION_ROLE_NAME,
    SECOND_PROBATION_ROLE_NAME,
    FIRST_PROBATION_WARNING_COUNT,
    SECOND_PROBATION_WARNING_COUNT
)
from .storage import guild_data_path, locked_path, read_json, write_json_atomic

WARNINGS_FILENAME = "warnings.json"
CASUAL_LEAVE_FILENAME = "casual_leave.json"
MANUAL_WARNING_DAILY_LIMIT = 4


def _warnings_path(guild_id: int):
    return guild_data_path(guild_id, WARNINGS_FILENAME)


def _casual_leave_path(guild_id: int):
    return guild_data_path(guild_id, CASUAL_LEAVE_FILENAME)


def _normalize_warning_entry(value, username: str = "Unknown"):
    if isinstance(value, int):
        return {
            "count": value,
            "username": username,
            "history": []
        }

    if not isinstance(value, dict):
        return {
            "count": 0,
            "username": username,
            "history": []
        }

    history = value.get("history", [])
    if not isinstance(history, list):
        history = []

    return {
        "count": max(0, int(value.get("count", 0))),
        "username": value.get("username", username),
        "history": history
    }


def _warning_month_key(user_id, year: int, month: int) -> str:
    return f"{user_id}-{year}-{month:02d}"


def _warning_key_for_date(user_id, warning_date: datetime.date) -> str:
    return _warning_month_key(user_id, warning_date.year, warning_date.month)


def _safe_text(value: str) -> str:
    return escape_mentions(escape_markdown((value or "").strip()))


def _normalized_reason(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _parse_history_date(value: str | None) -> datetime.date | None:
    if not value:
        return None

    for date_format in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(value, date_format).date()
        except ValueError:
            continue

    try:
        parsed = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None

    return parsed.date()


def _warning_history_date(item: dict) -> datetime.date | None:
    explicit_warning_date = _parse_history_date(item.get("warning_date"))
    if explicit_warning_date:
        return explicit_warning_date

    return _parse_history_date(item.get("timestamp"))


def _count_warning_history_for_date(entry: dict, target_date: datetime.date, source: str | None = None) -> int:
    total = 0

    for item in entry.get("history", []):
        if not isinstance(item, dict):
            continue
        if source and item.get("source") != source:
            continue
        if _warning_history_date(item) != target_date:
            continue

        try:
            total += max(0, int(item.get("warning_count", 0)))
        except (TypeError, ValueError):
            continue

    return total


def load_warnings(guild_id: int):
    path = _warnings_path(guild_id)
    try:
        data = read_json(path, {})
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Warning data is corrupted for this server ({path} line {exc.lineno}, column {exc.colno})."
        ) from exc
    
    # Convert old format to new format if needed
    converted_data = {}
    for key, value in data.items():
        converted_data[key] = _normalize_warning_entry(value)
    
    return converted_data

def save_warnings(guild_id: int, data):
    path = _warnings_path(guild_id)
    with locked_path(path):
        write_json_atomic(path, data)


def validate_manual_warning(issuer: discord.Member, target: discord.Member) -> str | None:
    """Return an error message if the issuer cannot manually warn the target."""
    if issuer.bot:
        return "Bots cannot issue manual warnings."

    if target.bot:
        return "You cannot warn a bot account."

    if issuer.id == target.id:
        return "You cannot issue a warning to yourself."

    issuer_level = get_user_level(issuer.roles)
    if issuer_level <= 0:
        return "You do not have a role in the warning hierarchy."

    if not has_current_team_role(target.roles):
        return "You can only warn current-team members."

    if not can_act_on_member(issuer.roles, target.roles):
        return (
            "You can only warn members below your role level. "
            "Equal or higher roles are not allowed."
        )

    return None


def _append_warning_history(
    entry: dict,
    member: discord.Member,
    warning_count: int,
    issued_by,
    reason: str | None,
    source: str,
    warning_date: datetime.date,
):
    history = entry.get("history")
    if not isinstance(history, list):
        history = []

    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    history.append(
        {
            "target_id": member.id,
            "target_username": member.display_name,
            "issuer_id": issued_by.id if issued_by else None,
            "issuer_username": issued_by.display_name if issued_by else "System",
            "issuer_role": get_role_display_name(issued_by.roles) if issued_by else "System",
            "reason": _normalized_reason(reason),
            "warning_date": warning_date.strftime("%d-%m-%Y"),
            "warning_count": warning_count,
            "source": source,
            "timestamp": timestamp,
        }
    )
    entry["history"] = history

def is_core_member_or_exempt(user_roles):
    """Check if user is exempt from warnings."""
    role_names = [role.name for role in user_roles]
    
    if "4th_years" in role_names:
        return True
    
    # 3rd year Core Members are NOT exempt (they get warnings)
    if "3rd_years" in role_names and "Core Member" in role_names:
        return False
    
    if "Core Member" in role_names:
        return True
        
    return False

def get_leave_user_ids_for_date(guild_id: int, date, pending_requests=None, casual_data=None) -> set[int]:
    """Return the set of user IDs with approved leave on a specific date."""
    from .user_stats import load_pending_requests

    requests = load_pending_requests(guild_id) if pending_requests is None else pending_requests
    casual_data = read_json(_casual_leave_path(guild_id), {}) if casual_data is None else casual_data
    leave_user_ids: set[int] = set()

    for request in requests:
        if request.get("status") in ["approved", "auto-approved"]:
            # Hostel work still requires a status update, so it must not exempt warnings.
            if request.get("type") == "hostel_work":
                continue
            try:
                start_date_str = request["dates"]["start"]
                end_date_str = request["dates"]["end"]
                
                start_date = datetime.datetime.strptime(start_date_str, "%d-%m-%Y").date()
                end_date = datetime.datetime.strptime(end_date_str, "%d-%m-%Y").date()
                
                if start_date <= date <= end_date:
                    member_id = request.get("member_id")
                    if member_id is not None:
                        leave_user_ids.add(member_id)
            except (KeyError, ValueError):
                continue

    for user_id_str, user_record in casual_data.items():
        for leave in user_record.get("leaves", []):
            try:
                start_date = datetime.datetime.strptime(leave["start"], "%d-%m-%Y").date()
                end_date = datetime.datetime.strptime(leave["end"], "%d-%m-%Y").date()
                
                if start_date <= date <= end_date:
                    try:
                        leave_user_ids.add(int(user_id_str))
                    except (TypeError, ValueError):
                        pass
            except (KeyError, ValueError):
                continue

    return leave_user_ids


def user_has_leave_on_date(guild_id: int, user_id, date, pending_requests=None, casual_data=None, leave_user_ids=None):
    """Check if user has approved leave on the specified date."""
    if leave_user_ids is None:
        leave_user_ids = get_leave_user_ids_for_date(
            guild_id,
            date,
            pending_requests=pending_requests,
            casual_data=casual_data,
        )

    return user_id in leave_user_ids

async def should_give_warning(member: discord.Member, date, submission_user_ids=None, leave_user_ids=None):
    """
    Determine if a member should receive a warning.
    Returns the number of warnings to give (0, 1, or 2).
    """
    # 1. Skip bots
    if member.bot:
        return 0
    
    # 2. Check if user has current-team role
    if not has_current_team_role(member.roles):
        return 0

    # 3. Check if user has roles that exempt them from warnings
    if is_core_member_or_exempt(member.roles):
        return 0
    
    # 4. Check if user has required roles (team + year)
    try:
        from ..ui.secure_forms import validate_user_roles
        validate_user_roles(member.roles)
    except ValueError:
        return 0
    
    # 5. Check if user has approved leave
    if leave_user_ids is None:
        has_leave = user_has_leave_on_date(member.guild.id, member.id, date)
    else:
        has_leave = member.id in leave_user_ids
    
    # 6. Check if user submitted status
    if submission_user_ids is None:
        from .user_stats import get_user_submissions_for_date

        submissions = get_user_submissions_for_date(member.guild.id, member.id, date)
        has_submission = len(submissions) > 0
    else:
        has_submission = member.id in submission_user_ids
    
    # Determine warning count
    if has_leave:
        return 0
    
    if has_submission:
        return 0
    
    # If no leave AND no submission: 2 warnings
    return 2

async def give_warning(
    bot,
    member: discord.Member,
    warning_count: int = 1,
    for_date=None,
    issued_by: discord.Member | None = None,
    reason: str | None = None,
    source: str = "automatic",
):
    """
    Assign warning(s) to a member with proper escalation.
    
    Args:
        bot: Discord bot instance
        member: Member to warn
        warning_count: Number of warnings to give (default 1, can be 2)
    """
    guild_id = member.guild.id
    warning_date = for_date or datetime.date.today()
    month_key = _warning_key_for_date(member.id, warning_date)
    path = _warnings_path(guild_id)

    with locked_path(path):
        warnings = load_warnings(guild_id)
        current_data = _normalize_warning_entry(
            warnings.get(month_key),
            username=member.display_name,
        )
        if source == "manual":
            manual_warnings_today = _count_warning_history_for_date(
                current_data,
                target_date=warning_date,
                source="manual",
            )
            if manual_warnings_today + warning_count > MANUAL_WARNING_DAILY_LIMIT:
                remaining = max(0, MANUAL_WARNING_DAILY_LIMIT - manual_warnings_today)
                if remaining == 0:
                    raise ValueError(
                        f"{member.display_name} has already reached the daily limit of "
                        f"{MANUAL_WARNING_DAILY_LIMIT} manual warnings."
                    )
                raise ValueError(
                    f"You can only issue {remaining} more manual warning"
                    f"{'' if remaining == 1 else 's'} to {member.display_name} today. "
                    f"Daily limit: {MANUAL_WARNING_DAILY_LIMIT}."
                )
        old_count = current_data["count"]
        new_count = old_count + warning_count
        current_data["count"] = new_count
        current_data["username"] = member.display_name
        _append_warning_history(
            current_data,
            member=member,
            warning_count=warning_count,
            issued_by=issued_by,
            reason=reason,
            source=source,
            warning_date=warning_date,
        )
        warnings[month_key] = current_data
        write_json_atomic(path, warnings)

    # Post warning message in channel
    channel = member.guild.get_channel(WARNING_CHANNEL_ID)
    safe_reason = _safe_text(reason) if reason else None
    if channel:
        if source == "manual":
            message = (
                f"{member.mention} received **{warning_count} manual warning"
                f"{'s' if warning_count != 1 else ''}** from {issued_by.mention if issued_by else 'System'}.\n"
                f"Total warnings this month: **{new_count}**"
            )
            if safe_reason:
                message += f"\nReason: {safe_reason}"
            await channel.send(message, allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
        elif warning_count == 2:
            await channel.send(
                f"{member.mention} received **{warning_count} warnings** "
                f"(No status update AND no leave request)\n"
                f"Total warnings this month: **{new_count}**"
            )
        else:
            await channel.send(
                f"{member.mention} warning: {new_count}"
            )

    # Probation escalation with configurable thresholds
    guild = member.guild
    # Use role names from config
    role_1st = discord.utils.get(guild.roles, name=FIRST_PROBATION_ROLE_NAME)
    role_2nd = discord.utils.get(guild.roles, name=SECOND_PROBATION_ROLE_NAME)

    # Check if roles exist
    if not role_1st:
        print(f"Warning: '{FIRST_PROBATION_ROLE_NAME}' role not found in server")
    if not role_2nd:
        print(f"Warning: '{SECOND_PROBATION_ROLE_NAME}' role not found in server")

    # Use warning counts from config
    # First probation: When user reaches configured count (default: 3)
    if old_count < FIRST_PROBATION_WARNING_COUNT <= new_count and role_1st:
        if role_1st not in member.roles:
            try:
                await member.add_roles(role_1st)
                if channel:
                    await channel.send(
                        f"{member.mention} has been placed on **{FIRST_PROBATION_ROLE_NAME}** "
                        f"({FIRST_PROBATION_WARNING_COUNT} warnings)."
                    )
                print(f"Added {FIRST_PROBATION_ROLE_NAME} role to {member.display_name}")
            except discord.Forbidden:
                print(f"Bot lacks permission to add {FIRST_PROBATION_ROLE_NAME} role to {member.display_name}")
            except Exception as e:
                print(f"Error adding {FIRST_PROBATION_ROLE_NAME} role: {e}")

    # Second probation: When user reaches configured count (default: 4)
    elif new_count >= SECOND_PROBATION_WARNING_COUNT and role_2nd:
        # Remove 1st probation if they have it
        if role_1st and role_1st in member.roles:
            try:
                await member.remove_roles(role_1st)
                print(f"Removed {FIRST_PROBATION_ROLE_NAME} from {member.display_name}")
            except Exception as e:
                print(f"Error removing {FIRST_PROBATION_ROLE_NAME}: {e}")
        
        # Add 2nd probation if they don't have it
        if role_2nd not in member.roles:
            try:
                await member.add_roles(role_2nd)
                if channel:
                    await channel.send(
                        f"{member.mention} has been escalated to **{SECOND_PROBATION_ROLE_NAME}** "
                        f"({new_count} warnings)."
                    )
                print(f"Added {SECOND_PROBATION_ROLE_NAME} role to {member.display_name}")
            except discord.Forbidden:
                print(f"Bot lacks permission to add {SECOND_PROBATION_ROLE_NAME} role to {member.display_name}")
            except Exception as e:
                print(f"Error adding {SECOND_PROBATION_ROLE_NAME} role: {e}")

    return new_count


async def give_manual_warning(
    bot,
    issuer: discord.Member,
    target: discord.Member,
    warning_count: int = 1,
    reason: str | None = None,
):
    """
    Issue one or more manual warnings after hierarchy validation.

    Returns a tuple of (new_warning_count, normalized_reason).
    """
    error = validate_manual_warning(issuer, target)
    if error:
        raise ValueError(error)

    if warning_count < 1:
        raise ValueError("Warning count must be at least 1.")
    if warning_count > MANUAL_WARNING_DAILY_LIMIT:
        raise ValueError(
            f"You cannot issue more than {MANUAL_WARNING_DAILY_LIMIT} manual warnings in a day."
        )

    normalized_reason = _normalized_reason(reason)
    if normalized_reason and len(normalized_reason) > 500:
        raise ValueError("Reason cannot exceed 500 characters.")
    new_count = await give_warning(
        bot,
        target,
        warning_count=warning_count,
        for_date=datetime.date.today(),
        issued_by=issuer,
        reason=normalized_reason,
        source="manual",
    )
    return new_count, normalized_reason

def get_user_warning_count(guild_id: int, user_id, month=None, year=None):
    """Get warning count for a user in a specific month/year."""
    warnings = load_warnings(guild_id)
    
    if month is None or year is None:
        now = datetime.datetime.now()
        month = month or now.month
        year = year or now.year
    
    month_key = f"{user_id}-{year}-{month:02d}"
    warning_data = warnings.get(month_key, {"count": 0, "username": "Unknown"})
    
    if isinstance(warning_data, int):
        return warning_data
    return warning_data.get("count", 0)

def reset_monthly_warnings(guild_id: int):
    """Reset warnings for the new month."""
    warnings = load_warnings(guild_id)
    current_month = datetime.datetime.now().strftime('%Y-%m')
    
    new_warnings = {}
    for key, value in warnings.items():
        if key.endswith(f"-{current_month}"):
            new_warnings[key] = value
    
    save_warnings(guild_id, new_warnings)
    return len(warnings) - len(new_warnings)
