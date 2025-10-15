import discord
import datetime
import json
import os
from ..core.utils import has_current_team_role


WARNINGS_FILE = "data/warnings.json"
WARNING_CHANNEL_ID = 1416744851457704158

def load_warnings():
    if not os.path.exists(WARNINGS_FILE):
        return {}
    with open(WARNINGS_FILE, "r") as f:
        return json.load(f)

def save_warnings(data):
    os.makedirs(os.path.dirname(WARNINGS_FILE), exist_ok=True)
    with open(WARNINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def is_core_member_or_exempt(user_roles):
    """Check if user is core member or has roles that exempt them from warnings."""
    role_names = [role.name for role in user_roles]
    
    # Core members are exempt from warnings
    if "Core Member" in role_names:
        return True
    
    # 4th years are also exempt (high-level members)
    if "4th_years" in role_names:
        return True
        
    return False

def user_has_leave_on_date(user_id, date):
    """Check if user has approved leave on the specified date."""
    from .user_stats import load_pending_requests
    
    # Load all requests (including approved ones)
    requests = load_pending_requests()
    date_str = date.strftime("%d-%m-%Y")
    
    for request in requests:
        if request.get("member_id") == user_id and request.get("status") in ["approved", "auto-approved"]:
            try:
                start_date_str = request["dates"]["start"]
                end_date_str = request["dates"]["end"]
                
                start_date = datetime.datetime.strptime(start_date_str, "%d-%m-%Y").date()
                end_date = datetime.datetime.strptime(end_date_str, "%d-%m-%Y").date()
                
                # Check if the date falls within the leave range
                if start_date <= date <= end_date:
                    return True
            except (KeyError, ValueError):
                continue
    
    # Also check casual leave history
    casual_file = os.path.join("data", "casual_leave.json")
    if os.path.exists(casual_file):
        with open(casual_file, "r") as f:
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
    """Determine if a member should receive a warning for a specific date."""
    
    # 1. Skip bots
    if member.bot:
        return False
    
    # 2. NEW: Check if user has current-team role - if not, ignore them
    if not has_current_team_role(member.roles):
        return False

    # 3. Check if user has roles that exempt them from warnings
    if is_core_member_or_exempt(member.roles):
        return False
    
    # 3. Check if user has required roles (team + year)
    try:
        # Import here to avoid circular imports
        from ..ui.forms import validate_user_roles
        validate_user_roles(member.roles)
    except ValueError:
        # Skip members without proper roles
        return False
    
    # 4. Check if user has approved leave on this date
    if user_has_leave_on_date(member.id, date):
        return False
    
    # 5. Check if user already submitted for this date
    from .user_stats import get_user_submissions_for_date
    submissions = get_user_submissions_for_date(member.id, date)
    if submissions:
        return False
    
    # If all checks pass, user should get a warning
    return True

async def give_warning(bot, member: discord.Member):
    """Assign a warning to a member and check for probation escalation."""
    warnings = load_warnings()
    now = datetime.datetime.now()
    month_key = f"{member.id}-{now.strftime('%Y-%m')}"  # user-month key
    
    count = warnings.get(month_key, 0) + 1
    warnings[month_key] = count
    save_warnings(warnings)

    # Post warning message in channel
    channel = bot.get_channel(WARNING_CHANNEL_ID)
    if channel:
        await channel.send(f"{member.mention} warning: {count}")

    # Probation escalation
    guild = member.guild
    role_1st = discord.utils.get(guild.roles, name="1st Probation")
    role_2nd = discord.utils.get(guild.roles, name="2nd Probation")

    if count == 3 and role_1st:
        await member.add_roles(role_1st)
        if channel:
            await channel.send(f"⚠️ {member.mention} has been placed on 1st Probation.")

    elif count > 3 and role_2nd:
        # Upgrade to 2nd probation
        if role_1st and role_1st in member.roles:
            await member.remove_roles(role_1st)
        await member.add_roles(role_2nd)
        if channel:
            await channel.send(f"🚨 {member.mention} has been escalated to 2nd Probation.")

def get_user_warning_count(user_id, month=None, year=None):
    """Get warning count for a user in a specific month/year."""
    warnings = load_warnings()
    
    if month is None or year is None:
        now = datetime.datetime.now()
        month = month or now.month
        year = year or now.year
    
    month_key = f"{user_id}-{year}-{month:02d}"
    return warnings.get(month_key, 0)

def reset_monthly_warnings():
    """Reset warnings for the new month (can be called manually if needed)."""
    warnings = load_warnings()
    current_month = datetime.datetime.now().strftime('%Y-%m')
    
    # Keep only current month's warnings
    new_warnings = {}
    for key, value in warnings.items():
        if key.endswith(f"-{current_month}"):
            new_warnings[key] = value
    
    save_warnings(new_warnings)
    return len(warnings) - len(new_warnings)  # Return number of warnings cleared