import discord
import datetime
import json
import os
from ..core.utils import has_current_team_role

# Import from config instead of hardcoding
from ..config import (
    WARNING_CHANNEL_ID,
    WARNINGS_FILE,
    FIRST_PROBATION_ROLE_NAME,
    SECOND_PROBATION_ROLE_NAME,
    FIRST_PROBATION_WARNING_COUNT,
    SECOND_PROBATION_WARNING_COUNT
)

def load_warnings():
    if not os.path.exists(WARNINGS_FILE):
        return {}
    with open(WARNINGS_FILE, "r") as f:
        data = json.load(f)
    
    # Convert old format to new format if needed
    converted_data = {}
    for key, value in data.items():
        if isinstance(value, int):
            converted_data[key] = {
                "count": value,
                "username": "Unknown"
            }
        else:
            converted_data[key] = value
    
    return converted_data

def save_warnings(data):
    os.makedirs(os.path.dirname(WARNINGS_FILE), exist_ok=True)
    with open(WARNINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)

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

def user_has_leave_on_date(user_id, date):
    """Check if user has approved leave on the specified date."""
    from .user_stats import load_pending_requests
    
    requests = load_pending_requests()
    date_str = date.strftime("%d-%m-%Y")
    
    for request in requests:
        if request.get("member_id") == user_id and request.get("status") in ["approved", "auto-approved"]:
            try:
                start_date_str = request["dates"]["start"]
                end_date_str = request["dates"]["end"]
                
                start_date = datetime.datetime.strptime(start_date_str, "%d-%m-%Y").date()
                end_date = datetime.datetime.strptime(end_date_str, "%d-%m-%Y").date()
                
                if start_date <= date <= end_date:
                    return True
            except (KeyError, ValueError):
                continue
    
    # Check casual leave history
    from ..config import CASUAL_LEAVE_FILE
    if os.path.exists(CASUAL_LEAVE_FILE):
        with open(CASUAL_LEAVE_FILE, "r") as f:
            casual_data = json.load(f)
        
        user_id_str = str(user_id)
        if user_id_str in casual_data:
            for leave in casual_data[user_id_str].get("leaves", []):
                try:
                    start_date = datetime.datetime.strptime(leave["start"], "%d-%m-%Y").date()
                    end_date = datetime.datetime.strptime(leave["end"], "%d-%m-%Y").date()
                    
                    if start_date <= date <= end_date:
                        return True
                except (KeyError, ValueError):
                    continue
    
    return False

async def should_give_warning(member: discord.Member, date):
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
        from ..ui.forms import validate_user_roles
        validate_user_roles(member.roles)
    except ValueError:
        return 0
    
    # 5. Check if user has approved leave
    has_leave = user_has_leave_on_date(member.id, date)
    
    # 6. Check if user submitted status
    from .user_stats import get_user_submissions_for_date
    submissions = get_user_submissions_for_date(member.id, date)
    has_submission = len(submissions) > 0
    
    # Determine warning count
    if has_leave:
        return 0
    
    if has_submission:
        return 0
    
    # If no leave AND no submission: 2 warnings
    return 2

async def give_warning(bot, member: discord.Member, warning_count: int = 1):
    """
    Assign warning(s) to a member with proper escalation.
    
    Args:
        bot: Discord bot instance
        member: Member to warn
        warning_count: Number of warnings to give (default 1, can be 2)
    """
    warnings = load_warnings()
    now = datetime.datetime.now()
    month_key = f"{member.id}-{now.strftime('%Y-%m')}"
    
    # Get current data
    current_data = warnings.get(month_key, {"count": 0, "username": member.display_name})
    old_count = current_data["count"]
    new_count = old_count + warning_count
    
    # Update with new count and username
    warnings[month_key] = {
        "count": new_count,
        "username": member.display_name
    }
    save_warnings(warnings)

    # Post warning message in channel
    channel = bot.get_channel(WARNING_CHANNEL_ID)
    if channel:
        if warning_count == 2:
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

def get_user_warning_count(user_id, month=None, year=None):
    """Get warning count for a user in a specific month/year."""
    warnings = load_warnings()
    
    if month is None or year is None:
        now = datetime.datetime.now()
        month = month or now.month
        year = year or now.year
    
    month_key = f"{user_id}-{year}-{month:02d}"
    warning_data = warnings.get(month_key, {"count": 0, "username": "Unknown"})
    
    if isinstance(warning_data, int):
        return warning_data
    return warning_data.get("count", 0)

def reset_monthly_warnings():
    """Reset warnings for the new month."""
    warnings = load_warnings()
    current_month = datetime.datetime.now().strftime('%Y-%m')
    
    new_warnings = {}
    for key, value in warnings.items():
        if key.endswith(f"-{current_month}"):
            new_warnings[key] = value
    
    save_warnings(new_warnings)
    return len(warnings) - len(new_warnings)