import discord
import datetime
import json
import os
import uuid
import re
import csv
from ..core.user_stats import record_status_update, load_pending_requests, save_pending_requests, load_user_data, save_user_data,get_user_submissions_for_date
from ..core.channel_lookup import get_user_status_channel
from ..ui.buttons import LeaveApprovalView


# =====================
# Helper Functions
# =====================

CASUAL_HISTORY_FILE = os.path.join("data", "casual_leave.json")
CSV_EXPORT_FILE = os.path.join("data", "activity_report.csv")

def load_casual_leave_history():
    if not os.path.exists(CASUAL_HISTORY_FILE):
        return {}
    with open(CASUAL_HISTORY_FILE, "r") as f:
        return json.load(f)

def save_casual_leave_history(data):
    os.makedirs(os.path.dirname(CASUAL_HISTORY_FILE), exist_ok=True)
    with open(CASUAL_HISTORY_FILE, "w") as f:
        json.dump(data, f, indent=4)

def has_unlimited_casual_leave(user_roles):
    """Check if user has privilege for unlimited casual leave."""
    role_names = [r.name for r in user_roles]
    if "Core Member" in role_names or "4th_years" in role_names:
        return True
    return False

def is_3rd_year_core_member(user_roles):
    """Check if user is both 3rd year AND Core Member"""
    role_names = [role.name for role in user_roles]
    return "3rd_years" in role_names and "Core Member" in role_names

def get_casual_leave_limit(user_roles):
    """
    Get casual leave limit based on role combination
    
    Returns:
    - 4: 3rd year Core Members
    - float("inf"): Other Core Members or 4th years
    - 2: Regular members
    """
    role_names = [role.name for role in user_roles]
    
    # 3rd year Core Members get 10 days
    if "3rd_years" in role_names and "Core Member" in role_names:
        return 10
    
    # Other Core Members and 4th years get unlimited
    if "Core Member" in role_names or "4th_years" in role_names:
        return float("inf")
    
    # Regular members get 2 days per month
    return 2

# UPDATE: forms.py - get_casual_leave_usage function

def get_casual_leave_usage(user_id, month, year, roles=None):
    """
    Returns (used_days, allowed_days). 
    - 3rd year Core Members: 22 days per month
    - Other Core Members / 4th_years: unlimited
    - Regular members: 2 days per month
    """
    if roles:
        allowed_days = get_casual_leave_limit(roles)
    else:
        allowed_days = 2  # Default for members without role context

    data = load_casual_leave_history()
    user_id_str = str(user_id)
    used_days = 0
    
    # Add bonus days to the base limit
    if user_id_str in data:
        bonus_days = data.get(user_id_str, {}).get("bonus_days", 0)
        if allowed_days != float("inf"):
            allowed_days += bonus_days

    # Calculate used days for this month
    if user_id_str in data:
        for record in data[user_id_str].get("leaves", []):
            try:
                record_date = datetime.datetime.strptime(record["start"], "%d-%m-%Y").date()
                if record_date.month == month and record_date.year == year:
                    used_days += record["days"]
            except ValueError:
                continue

    return used_days, allowed_days


def record_casual_leave(user_id, start_date_str, end_date_str, days):
    data = load_casual_leave_history()
    user_id_str = str(user_id)
    if user_id_str not in data:
        data[user_id_str] = {"bonus_days": 0, "leaves": []}

    data[user_id_str]["leaves"].append({
        "start": start_date_str,
        "end": end_date_str,
        "days": days
    })
    save_casual_leave_history(data)

def get_week_dates(date):
    """Get Monday to Sunday dates for the week containing the given date."""
    monday = date - datetime.timedelta(days=date.weekday())
    sunday = monday + datetime.timedelta(days=6)
    return monday, sunday

def get_weekly_hours(user_id, target_date):
    """Calculate total hours worked in the week containing target_date."""
    monday, sunday = get_week_dates(target_date)
    data = load_user_data()
    user_id_str = str(user_id)
    
    if user_id_str not in data:
        return 0.0
    
    total_hours = 0.0
    submissions = data[user_id_str].get("submissions", {})
    
    for submission in submissions.values():
        sub_date = datetime.datetime.strptime(submission["date"], "%d-%m-%Y").date()
        if monday <= sub_date <= sunday:
            total_hours += submission["hours"]
    
    return total_hours

def check_weekly_target(user_id, target_date, new_hours):
    """Check if adding new_hours would exceed or meet the 32-hour weekly target."""
    current_weekly_hours = get_weekly_hours(user_id, target_date)
    total_with_new = current_weekly_hours + new_hours
    return current_weekly_hours, total_with_new

def count_user_statistics(user_id):
    """Count various statistics for CSV export."""
    data = load_user_data()
    casual_data = load_casual_leave_history()
    user_id_str = str(user_id)
    
    stats = {
        "total_status_updates": 0,
        "total_hours_worked": 0.0,
        "total_leaves": 0,
        "late_status_hours": 0.0,
        "total_submissions": 0
    }
    
    # Count status updates and hours
    if user_id_str in data:
        submissions = data[user_id_str].get("submissions", {})
        stats["total_status_updates"] = len(submissions)
        stats["total_submissions"] = len(submissions)
        
        for submission in submissions.values():
            stats["total_hours_worked"] += submission["hours"]
            if submission.get("is_late", False):
                stats["late_status_hours"] += submission["hours"]
    
    # Count casual leaves
    if user_id_str in casual_data:
        stats["total_leaves"] = len(casual_data[user_id_str].get("leaves", []))
    
    return stats

def export_to_csv(from_date=None, to_date=None):
    """Export user data to CSV format with optional date range filtering."""
    data = load_user_data()
    csv_data = []
    
    # If no date range specified, use all data
    if from_date is None:
        from_date = datetime.date(2020, 1, 1)  # Very early date
    if to_date is None:
        to_date = datetime.date.today()
    
    for user_id, user_info in data.items():
        stats = count_user_statistics_for_range(int(user_id), from_date, to_date)
        csv_row = {
            "username": user_info.get("username", "Unknown"),
            "total_status_updates": stats["total_status_updates"],
            "total_hours_worked": stats["total_hours_worked"],
            "number_of_leaves": stats["total_leaves"],
            "late_status_hours": stats["late_status_hours"],
            "total_submissions": stats["total_submissions"],
            "from_date": from_date.strftime("%d-%m-%Y"),
            "to_date": to_date.strftime("%d-%m-%Y")
        }
        csv_data.append(csv_row)
    
    # Create filename with date range
    date_suffix = f"_{from_date.strftime('%d%m%Y')}_to_{to_date.strftime('%d%m%Y')}"
    csv_file_with_dates = CSV_EXPORT_FILE.replace('.csv', f'{date_suffix}.csv')
    
    # Write to CSV file
    os.makedirs(os.path.dirname(csv_file_with_dates), exist_ok=True)
    with open(csv_file_with_dates, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ["username", "total_status_updates", "total_hours_worked", 
                     "number_of_leaves", "late_status_hours", "total_submissions",
                     "from_date", "to_date"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(csv_data)
    
    return csv_file_with_dates

def count_user_statistics_for_range(user_id, from_date, to_date):
    """Count statistics for a specific date range."""
    data = load_user_data()
    casual_data = load_casual_leave_history()
    user_id_str = str(user_id)
    
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

async def handle_auto_approval(interaction: discord.Interaction, request_data: dict, date_range_str: str):
    """Handles the final steps for an auto-approved leave request."""
    pending_requests = load_pending_requests()
    
    # Ensure pending_requests is a list
    if not isinstance(pending_requests, list):
        pending_requests = []
    
    pending_requests.append(request_data)
    save_pending_requests(pending_requests)

    leave_tracking_channel_id = 1415019014224089147
    leave_tracking_channel = interaction.client.get_channel(leave_tracking_channel_id)
    bot_mention = interaction.client.user.mention
    if leave_tracking_channel:
        auto_approved_message = f"""```Leave on ({date_range_str})
Leave Type: {request_data.get("type").capitalize()}
Reason: {request_data.get("reason", "N/A")}```from {interaction.user.mention} auto approved by {bot_mention}."""
        await leave_tracking_channel.send(auto_approved_message)
    return await interaction.followup.send("Your leave request has been automatically approved.", ephemeral=True)

def is_core_member(user_roles):
    """Checks if a user has the Core Member role."""
    for role in user_roles:
        if "Core Member" == role.name:
            return True
    return False

def validate_date_format(date_str):
    """Enhanced date validation with proper format handling."""
    if not date_str or not date_str.strip():
        raise ValueError("Date cannot be empty.")
    
    date_str = date_str.strip()
    
    # Check basic format with regex
    if not re.match(r'^\d{2}-\d{2}-\d{4}$', date_str):
        raise ValueError("Date must be in DD-MM-YYYY format (e.g., 14-09-2025).")
    
    try:
        date_obj = datetime.datetime.strptime(date_str, "%d-%m-%Y").date()
    except ValueError:
        raise ValueError("Invalid date. Please check day/month values are correct.")
    
    return date_obj

def validate_status_date(date_str):
    """Validate date for status updates - allows past dates, not future dates."""
    date_obj = validate_date_format(date_str)
    
    if date_obj > datetime.date.today():
        raise ValueError("Date cannot be in the future.")
    
    # Allow backdated submissions (past dates are OK)
    return date_obj

def validate_leave_date_range(date_range_str):
    """Validate date range for leave requests - start date cannot be in past."""
    if not date_range_str or " to " not in date_range_str:
        raise ValueError("Date range must be in format 'DD-MM-YYYY to DD-MM-YYYY'.")
    
    parts = date_range_str.split(" to ")
    if len(parts) != 2:
        raise ValueError("Date range must contain exactly one ' to ' separator.")
    
    start_str, end_str = parts[0].strip(), parts[1].strip()
    
    if not start_str or not end_str:
        raise ValueError("Both start and end dates are required.")
    
    start_date = validate_date_format(start_str)
    end_date = validate_date_format(end_str)
    
    if start_date > end_date:
        raise ValueError("Start date cannot be after end date.")
    
    if start_date < datetime.date.today():
        raise ValueError("Leave start date cannot be in the past.")
    
    return start_date, end_date, start_str, end_str

def validate_hours(hours_str, is_wfh=False, is_weekend=False):
    """Enhanced hours validation."""
    if not hours_str or not hours_str.strip():
        raise ValueError("Hours cannot be empty.")
    
    try:
        hours = float(hours_str)
    except ValueError:
        raise ValueError("Hours must be a valid number (e.g., 8, 8.5, 6.25).")
    
    if hours < 0:
        raise ValueError("Hours cannot be negative.")
    
    if hours > 15:
        raise ValueError("Hours cannot exceed 15 in a single day.")

    # Calculate minimum required hours
    if is_weekend:
        min_hours = 6 if not is_wfh else 3
        day_type = "weekend"
    else:
        min_hours = 4 if not is_wfh else 2
        day_type = "weekday"
    
    if hours < min_hours:
        wfh_note = " (WFH)" if is_wfh else ""
        raise ValueError(f"Minimum {min_hours} hours required for {day_type}{wfh_note}. You submitted {hours} hours.")
    
    return hours

def validate_work_description(description):
    """Enhanced work description validation."""
    if not description or not description.strip():
        raise ValueError("Work description cannot be empty.")
    
    description = description.strip()
    
    if len(description) < 1:
        raise ValueError("Work description must be at least 1 character long.")

    if len(description) > 5000:
        raise ValueError("Work description cannot exceed 5000 characters.")

    # Check for meaningful content
    unique_chars = len(set(description.replace(' ', '').lower()))
    if unique_chars < 3:
        raise ValueError("Work description must contain meaningful content.")
    
    return description

def validate_user_roles(user_roles):
    """Validate user has required team and year roles."""
    from ..core.channel_lookup import TEAM_CATEGORY_MAP, YEAR_CHANNEL_PREFIX_MAP
    
    team_role = None
    year_role = None
    
    role_names = {role.name for role in user_roles}
    
    for role_name in role_names:
        if role_name in TEAM_CATEGORY_MAP:
            team_role = role_name
        if role_name in YEAR_CHANNEL_PREFIX_MAP:
            year_role = role_name
    
    if not team_role:
        raise ValueError("You must have a team role (RedTeam, Android, BlockChain, Mobile) to use this bot.")
    
    if not year_role:
        raise ValueError("You must have a year role (Trainee Member, 1st_years, 2nd_years, 3rd_years, 4th_years) to use this bot.")
    
    return team_role, year_role

def is_late_submission(submission_date):
    """Check if submission is backdated (late)."""
    return submission_date < datetime.date.today()

class StatusForm(discord.ui.Modal, title="Daily Status Update"):
    def __init__(self, wfh_option: str):
        super().__init__(title="Daily Status Update")
        self.wfh_option = wfh_option

        self.date_input = discord.ui.TextInput(
            label="Date (DD-MM-YYYY)",
            placeholder="e.g., 04-09-2025",
            required=True,
            max_length=10,
            custom_id="date_input"
        )
        self.add_item(self.date_input)

        self.hours_input = discord.ui.TextInput(
            label="Hours Worked",
            placeholder="e.g., 8",
            required=True,
            max_length=4,
            custom_id="hours_input"
        )
        self.add_item(self.hours_input)
        
        self.wfh_input = discord.ui.TextInput(
            label="Work from Hostel? (Yes/No)",
            placeholder="This was already set.",
            required=True,
            default=self.wfh_option,
            custom_id="wfh_input"
        )
        self.add_item(self.wfh_input)

        self.work_description = discord.ui.TextInput(
            label="Work Description",
            placeholder="What did you work on today?",
            style=discord.TextStyle.paragraph,
            required=True,
            custom_id="work_description"
        )
        self.add_item(self.work_description)

        self.blockers = discord.ui.TextInput(
            label="Blockers (if any)",
            placeholder="Any issues you are facing?",
            style=discord.TextStyle.paragraph,
            required=False,
            custom_id="blockers"
        )
        self.add_item(self.blockers)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            # 1. Validate user roles first
            validate_user_roles(interaction.user.roles)
            
            # 2. Validate date - allows past dates for backdated submissions
            submission_date = validate_status_date(self.date_input.value)
            
            # 3. Check if this is a late submission
            is_late = is_late_submission(submission_date)
            
            # 4. Validate WFH input
            wfh_option = self.wfh_input.value.lower().strip()
            if wfh_option not in ['yes', 'no']:
                await interaction.response.send_message("Work from Hostel must be 'Yes' or 'No'.", ephemeral=True)
                return
            
            is_wfh = wfh_option == 'yes'
            day_of_week = submission_date.weekday()
            is_weekend = day_of_week >= 5

            # 5. Check if user already submitted a status for this date
            existing_submissions = get_user_submissions_for_date(interaction.user.id, submission_date)
            if existing_submissions:
                await interaction.response.send_message(
                    "You have already submitted a status update for this date. Only one submission per day is allowed.",
                    ephemeral=True
                )
                return
            
            # 6. Validate hours with enhanced validation
            hours_worked = validate_hours(self.hours_input.value, is_wfh, is_weekend)
            
            # 7. Check weekly target (32 hours)
            current_weekly, total_weekly = check_weekly_target(interaction.user.id, submission_date, hours_worked)
            
            # 8. Validate work description
            work_desc = validate_work_description(self.work_description.value)
            
            # 9. Validate blockers (optional field)
            blockers_text = self.blockers.value.strip() if self.blockers.value else "None"
            if len(blockers_text) > 500:
                await interaction.response.send_message("Blockers description cannot exceed 500 characters.", ephemeral=True)
                return
            
        except ValueError as e:
            await interaction.response.send_message(f"Validation Error: {str(e)}", ephemeral=True)
            return
        except Exception as e:
            await interaction.response.send_message(f"An unexpected error occurred: {str(e)}", ephemeral=True)
            return

        # 10. Record the status update with late flag
        record_status_update(
            user_id=interaction.user.id,
            username=interaction.user.display_name,
            date=submission_date,
            hours=hours_worked,
            description=work_desc,
            blockers=blockers_text,
            is_wfh=is_wfh,
            is_late=is_late
        )

        # 11. Find the correct channel dynamically
        target_channel = await get_user_status_channel(interaction.guild, interaction.user.roles)
        
        if not target_channel:
            await interaction.response.send_message(
                "Could not find a matching status channel for your roles. Please contact an admin.", 
                ephemeral=True
            )
            return

        # 12. Create status message with weekly progress
        late_indicator = " (Late Submission)" if is_late else ""
        weekly_progress = f"\nWeekly Progress: {total_weekly:.1f}/32 hours"
        
        status_message = f"""```Namah Shivaya ({submission_date.strftime('%d-%m-%Y')}){late_indicator}
{work_desc}
work from hostel: {'YES' if is_wfh else 'NO'}
Blockers: {blockers_text}
Time Spent: {hours_worked} hrs```By {interaction.user.mention}."""

        # 13. Weekly target notification
        weekly_note = ""
        if total_weekly >= 32:
            weekly_note = " Target achieved!"
        elif total_weekly > 25:
            weekly_note = f" Warning: {32 - total_weekly:.1f} hours remaining this week."

        await interaction.response.send_message(f"Your status has been accepted and will be posted publicly.{weekly_note}", ephemeral=True)
        await target_channel.send(status_message)

        # 14. Export updated CSV
        try:
            export_to_csv()
        except Exception as e:
            print(f"CSV export error: {e}")


#everything is update here is the proof 

class CasualLeaveModal(discord.ui.Modal, title="Casual Leave Request"):
    date_range = discord.ui.TextInput(
        label="Date Range (DD-MM-YYYY to DD-MM-YYYY)",
        placeholder="e.g., 14-09-2025 to 15-09-2025",
        required=True,
        custom_id="casual_date_range"
    )
    reason = discord.ui.TextInput(
        label="Reason for Leave",
        style=discord.TextStyle.paragraph,
        placeholder="Optional",
        required=False,
        custom_id="casual_reason"
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            # 1. Validate user roles
            validate_user_roles(interaction.user.roles)
            
            # 2. Validate date range for leaves (cannot be in past)
            start_date, end_date, start_date_str, end_date_str = validate_leave_date_range(self.date_range.value)
            
            # 3. Validate reason (optional but length check)
            reason = self.reason.value.strip() if self.reason.value else "No reason provided"
            if len(reason) > 500:
                await interaction.followup.send("Reason cannot exceed 500 characters.", ephemeral=True)
                return
            
        except ValueError as e:
            await interaction.followup.send(f"Validation Error: {str(e)}", ephemeral=True)
            return

        # 4. Calculate requested days
        requested_days = (end_date - start_date).days + 1

        # 5. Check monthly limit (unless unlimited)
        used_days, allowed_days = get_casual_leave_usage(
            interaction.user.id, start_date.month, start_date.year, interaction.user.roles
        )

        if allowed_days != float("inf") and used_days + requested_days > allowed_days:
            remaining = max(0, allowed_days - used_days)
            await interaction.followup.send(
                f"Casual leave limit exceeded. You have {remaining} days remaining this month "
                f"(requested: {requested_days}, allowed: {allowed_days}).",
                ephemeral=True
            )
            return

        # 6. Record leave as auto-approved
        record_casual_leave(interaction.user.id, start_date_str, end_date_str, requested_days)

        # 7. Post to leave-tracking channel
        bot_mention = interaction.client.user.mention
        leave_tracking_channel = interaction.client.get_channel(1415019014224089147)
        if leave_tracking_channel:
            await leave_tracking_channel.send(
                f"""```Leave on ({self.date_range.value})
Leave Type: Casual leave
Reason: {reason}```
from {interaction.user.mention} Approved by {bot_mention}"""
            )

        await interaction.followup.send(
            f"Your casual leave has been auto-approved for {requested_days} day(s).",
            ephemeral=True
        )

        # Export updated CSV
        try:
            export_to_csv()
        except Exception as e:
            print(f"CSV export error: {e}")


class MedicalLeaveModal(discord.ui.Modal, title="Medical Leave Request"):
    date_range = discord.ui.TextInput(
        label="Date Range (DD-MM-YYYY to DD-MM-YYYY)",
        placeholder="e.g., 14-09-2025 to 14-09-2025",
        required=True,
        custom_id="medical_date_range"
    )
    reason = discord.ui.TextInput(
        label="Reason for Leave",
        style=discord.TextStyle.paragraph,
        placeholder="e.g., Flu, high fever, etc.",
        required=True,
        custom_id="medical_reason"
    )
    mode = discord.ui.TextInput(
        label="Mode (Day-off or WFH)",
        placeholder="e.g., Day-off or WFH",
        required=True,
        custom_id="medical_mode"
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            # 1. Validate user roles
            validate_user_roles(interaction.user.roles)
            
            # 2. Validate date range for leaves
            start_date, end_date, start_date_str, end_date_str = validate_leave_date_range(self.date_range.value)
            
            # 3. Validate reason
            reason = self.reason.value.strip()
            if not reason:
                await interaction.followup.send("Medical leave reason is required.", ephemeral=True)
                return
            if len(reason) > 500:
                await interaction.followup.send("Reason cannot exceed 500 characters.", ephemeral=True)
                return
            
            # 4. Validate mode
            mode = self.mode.value.strip().lower()
            if mode not in ['day-off', 'wfh']:
                await interaction.followup.send("Mode must be either 'Day-off' or 'WFH'.", ephemeral=True)
                return
                
        except ValueError as e:
            await interaction.followup.send(f"Validation Error: {str(e)}", ephemeral=True)
            return

        request_id = str(uuid.uuid4())
        
        if is_core_member(interaction.user.roles):
            request_data = {
                "request_id": request_id,
                "type": "medical",
                "member_id": interaction.user.id,
                "dates": {"start": start_date_str, "end": end_date_str},
                "reason": reason,
                "mode": mode,
                "status": "auto-approved",
                "created_at": datetime.datetime.now().isoformat()
            }
            return await handle_auto_approval(interaction, request_data, self.date_range.value)

        status = "pending"
        request_data = {
            "request_id": request_id,
            "type": "medical",
            "member_id": interaction.user.id,
            "dates": {"start": start_date_str, "end": end_date_str},
            "reason": reason,
            "mode": mode,
            "status": status,
            "created_at": datetime.datetime.now().isoformat()
        }
        pending_requests = load_pending_requests()
        
        # Ensure pending_requests is a list
        if not isinstance(pending_requests, list):
            pending_requests = []
            
        pending_requests.append(request_data)
        save_pending_requests(pending_requests)

        leave_embed = discord.Embed(
            title="New Medical Leave Request",
            color=discord.Color.gold(),
            description=f"**Submitted by:** {interaction.user.mention}\n**Reason:** {reason}\n**Mode:** {mode}"
        )
        leave_embed.add_field(name="Date Range", value=self.date_range.value, inline=False)
        leave_embed.add_field(name="Status", value="Pending", inline=False)

        leave_request_channel_id = 1416718401044349038
        leave_request_channel = interaction.client.get_channel(leave_request_channel_id)
        if leave_request_channel:
            await leave_request_channel.send(f"A new leave request is waiting!", embed=leave_embed, view=LeaveApprovalView(request_id=request_id))

        await interaction.followup.send("Your medical leave request has been submitted for review.", ephemeral=True)


### SpecialLeaveModal  ###

class SpecialLeaveModal(discord.ui.Modal, title="Special Leave Request"):
    date_range = discord.ui.TextInput(
        label="Date Range (DD-MM-YYYY to DD-MM-YYYY)",
        placeholder="e.g., 14-09-2025 to 18-09-2025",
        required=True,
        custom_id="special_date_range"
    )
    reason = discord.ui.TextInput(
        label="Reason for Leave",
        style=discord.TextStyle.paragraph,
        placeholder="e.g., Exams, family emergency, etc.",
        required=True,
        custom_id="special_reason"
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            # 1. Validate user roles
            validate_user_roles(interaction.user.roles)
            
            # 2. Validate date range for leaves
            start_date, end_date, start_date_str, end_date_str = validate_leave_date_range(self.date_range.value)

            # NEW: Check if the date range exceeds 92 days
            days_difference = (end_date - start_date).days + 1  # Inclusive of start and end dates
            if days_difference > 92:
                await interaction.followup.send(
                    "Special leave requests cannot exceed 92 days. Please adjust the date range.",
                    ephemeral=True
                )
                return
            
            # 3. Validate reason
            reason = self.reason.value.strip()
            if not reason:
                await interaction.followup.send("Special leave reason is required.", ephemeral=True)
                return
            if len(reason) > 500:
                await interaction.followup.send("Reason cannot exceed 500 characters.", ephemeral=True)
                return
                
        except ValueError as e:
            await interaction.followup.send(f"Validation Error: {str(e)}", ephemeral=True)
            return

        request_id = str(uuid.uuid4())
        request_data = {
            "request_id": request_id,
            "type": "special",
            "member_id": interaction.user.id,
            "dates": {"start": start_date_str, "end": end_date_str},
            "reason": reason,
            "status": "pending",
            "created_at": datetime.datetime.now().isoformat()
        }

        if is_core_member(interaction.user.roles):
            request_data["status"] = "auto-approved"
            return await handle_auto_approval(interaction, request_data, self.date_range.value)

        pending_requests = load_pending_requests()
        
        # Ensure pending_requests is a list
        if not isinstance(pending_requests, list):
            pending_requests = []
            
        pending_requests.append(request_data)
        save_pending_requests(pending_requests)
        
        leave_embed = discord.Embed(
            title="New Special Leave Request",
            color=discord.Color.gold(),
            description=f"**Submitted by:** {interaction.user.mention}\n**Reason:** {reason}"
        )
        leave_embed.add_field(name="Date Range", value=self.date_range.value, inline=False)
        leave_embed.add_field(name="Status", value="Pending", inline=False)

        leave_request_channel_id = 1416718401044349038
        leave_request_channel = interaction.client.get_channel(leave_request_channel_id)
        if leave_request_channel:
            await leave_request_channel.send(embed=leave_embed, view=LeaveApprovalView(request_id=request_id))

        await interaction.followup.send("Your special leave request has been submitted for review.", ephemeral=True)