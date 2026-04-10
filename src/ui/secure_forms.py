import csv
import datetime
import math
import re
import uuid
from collections import Counter
from pathlib import Path

import discord
from dateutil.relativedelta import relativedelta
from discord.utils import escape_markdown, escape_mentions

from ..config import (
    LEAVE_REQUEST_CHANNEL_ID,
    LEAVE_TRACKING_CHANNEL_ID,
    LATE_SUBMISSION_MONTHS_LIMIT,
    MAX_CASUAL_LEAVE_DAYS,
    MAX_SPECIAL_LEAVE_DAYS,
    CSV_EXPORT_FILE,
)
from ..core.channel_lookup import TEAM_CATEGORY_MAP, YEAR_CHANNEL_PREFIX_MAP, get_user_status_channel
from ..core.storage import guild_data_path, guild_reports_dir, locked_path, read_json, write_json_atomic
from ..core.user_stats import (
    count_user_statistics_for_range,
    get_user_submissions_for_date,
    load_pending_requests,
    load_user_data,
    record_status_update,
)
from ..core.utils import validate_current_team_member
from ..ui.buttons import LeaveApprovalView

CASUAL_LEAVE_FILENAME = "casual_leave.json"
PENDING_FILENAME = "pending.json"


def _casual_leave_path(guild_id: int):
    return guild_data_path(guild_id, CASUAL_LEAVE_FILENAME)


def _pending_path(guild_id: int):
    return guild_data_path(guild_id, PENDING_FILENAME)


def load_casual_leave_history(guild_id: int):
    return read_json(_casual_leave_path(guild_id), {})


def save_casual_leave_history(guild_id: int, data):
    path = _casual_leave_path(guild_id)
    with locked_path(path):
        write_json_atomic(path, data)


def append_pending_request(guild_id: int, request_data: dict):
    path = _pending_path(guild_id)
    with locked_path(path):
        pending_requests = read_json(path, [])
        if not isinstance(pending_requests, list):
            pending_requests = []
        pending_requests.append(request_data)
        write_json_atomic(path, pending_requests)


def sanitize_public_text(value: str) -> str:
    cleaned = (value or "").strip().replace("```", "'''")
    return escape_mentions(escape_markdown(cleaned))


def sanitize_code_block_text(value: str) -> str:
    cleaned = (value or "").strip().replace("```", "'''").replace("`", "'")
    return escape_mentions(cleaned)


def get_casual_leave_limit(user_roles):
    role_names = [role.name for role in user_roles]

    if "3rd_years" in role_names and "Core Member" in role_names:
        return 10

    if "Core Member" in role_names or "4th_years" in role_names:
        return float("inf")

    return MAX_CASUAL_LEAVE_DAYS


def days_in_month_for_range(start_date: datetime.date, end_date: datetime.date, month: int, year: int) -> int:
    month_start = datetime.date(year, month, 1)
    month_end = month_start + relativedelta(months=1) - datetime.timedelta(days=1)
    overlap_start = max(start_date, month_start)
    overlap_end = min(end_date, month_end)
    if overlap_start > overlap_end:
        return 0
    return (overlap_end - overlap_start).days + 1


def split_days_by_month(start_date: datetime.date, end_date: datetime.date) -> Counter:
    allocations = Counter()
    current = start_date
    while current <= end_date:
        allocations[(current.year, current.month)] += 1
        current += datetime.timedelta(days=1)
    return allocations


def get_casual_leave_usage(guild_id: int, user_id, month, year, roles=None):
    allowed_days = get_casual_leave_limit(roles) if roles else MAX_CASUAL_LEAVE_DAYS
    data = load_casual_leave_history(guild_id)
    user_id_str = str(user_id)
    used_days = 0

    if user_id_str in data:
        bonus_days = data.get(user_id_str, {}).get("bonus_days", 0)
        if allowed_days != float("inf"):
            allowed_days += bonus_days

        for record in data[user_id_str].get("leaves", []):
            try:
                record_start = datetime.datetime.strptime(record["start"], "%d-%m-%Y").date()
                record_end = datetime.datetime.strptime(record["end"], "%d-%m-%Y").date()
            except ValueError:
                continue

            used_days += days_in_month_for_range(record_start, record_end, month, year)

    return used_days, allowed_days


def record_casual_leave(guild_id: int, user_id, start_date_str: str, end_date_str: str, days: int):
    path = _casual_leave_path(guild_id)
    with locked_path(path):
        data = read_json(path, {})
        user_id_str = str(user_id)
        if user_id_str not in data:
            data[user_id_str] = {"bonus_days": 0, "leaves": []}

        data[user_id_str]["leaves"].append(
            {"start": start_date_str, "end": end_date_str, "days": days}
        )
        write_json_atomic(path, data)


def get_week_dates(date: datetime.date):
    monday = date - datetime.timedelta(days=date.weekday())
    sunday = monday + datetime.timedelta(days=6)
    return monday, sunday


def get_weekly_hours(guild_id: int, user_id, target_date: datetime.date) -> float:
    monday, sunday = get_week_dates(target_date)
    data = load_user_data(guild_id)
    user_id_str = str(user_id)

    if user_id_str not in data:
        return 0.0

    total_hours = 0.0
    submissions = data[user_id_str].get("submissions", {})
    for submission in submissions.values():
        try:
            sub_date = datetime.datetime.strptime(submission["date"], "%d-%m-%Y").date()
        except ValueError:
            continue

        if monday <= sub_date <= sunday:
            total_hours += submission["hours"]

    return total_hours


def check_weekly_target(guild_id: int, user_id, target_date: datetime.date, new_hours: float):
    current_weekly_hours = get_weekly_hours(guild_id, user_id, target_date)
    total_with_new = current_weekly_hours + new_hours
    return current_weekly_hours, total_with_new


def export_to_csv(guild_id: int, from_date=None, to_date=None):
    data = load_user_data(guild_id)
    csv_data = []

    if from_date is None:
        from_date = datetime.date(2020, 1, 1)
    if to_date is None:
        to_date = datetime.date.today()

    for user_id, user_info in data.items():
        stats = count_user_statistics_for_range(guild_id, int(user_id), from_date, to_date)
        csv_data.append(
            {
                "username": user_info.get("username", "Unknown"),
                "total_status_updates": stats["total_status_updates"],
                "total_hours_worked": stats["total_hours_worked"],
                "number_of_leaves": stats["total_leaves"],
                "late_status_hours": stats["late_status_hours"],
                "total_submissions": stats["total_submissions"],
                "from_date": from_date.strftime("%d-%m-%Y"),
                "to_date": to_date.strftime("%d-%m-%Y"),
            }
        )

    reports_dir = guild_reports_dir(guild_id)
    reports_dir.mkdir(parents=True, exist_ok=True)
    base_name = Path(CSV_EXPORT_FILE).stem
    suffix = f"{from_date.strftime('%d%m%Y')}_to_{to_date.strftime('%d%m%Y')}"
    csv_path = reports_dir / f"{base_name}_{suffix}.csv"

    with csv_path.open("w", newline="", encoding="utf-8") as csvfile:
        fieldnames = [
            "username",
            "total_status_updates",
            "total_hours_worked",
            "number_of_leaves",
            "late_status_hours",
            "total_submissions",
            "from_date",
            "to_date",
        ]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(csv_data)

    return str(csv_path)


def date_ranges_overlap(start_a: datetime.date, end_a: datetime.date, start_b: datetime.date, end_b: datetime.date) -> bool:
    return max(start_a, start_b) <= min(end_a, end_b)


def has_overlapping_leave_request(guild_id: int, user_id, start_date: datetime.date, end_date: datetime.date) -> bool:
    pending_requests = load_pending_requests(guild_id)

    for request in pending_requests:
        if request.get("member_id") != user_id:
            continue
        if request.get("status") not in {"pending", "approved", "auto-approved"}:
            continue

        try:
            existing_start = datetime.datetime.strptime(request["dates"]["start"], "%d-%m-%Y").date()
            existing_end = datetime.datetime.strptime(request["dates"]["end"], "%d-%m-%Y").date()
        except (KeyError, ValueError):
            continue

        if date_ranges_overlap(start_date, end_date, existing_start, existing_end):
            return True

    casual_history = load_casual_leave_history(guild_id).get(str(user_id), {}).get("leaves", [])
    for leave in casual_history:
        try:
            existing_start = datetime.datetime.strptime(leave["start"], "%d-%m-%Y").date()
            existing_end = datetime.datetime.strptime(leave["end"], "%d-%m-%Y").date()
        except (KeyError, ValueError):
            continue

        if date_ranges_overlap(start_date, end_date, existing_start, existing_end):
            return True

    return False


async def handle_auto_approval(interaction: discord.Interaction, request_data: dict, date_range_str: str):
    guild_id = interaction.guild.id

    if "username" not in request_data:
        request_data["username"] = interaction.user.display_name
    request_data["approver_id"] = interaction.client.user.id
    request_data["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    append_pending_request(guild_id, request_data)

    leave_tracking_channel = interaction.guild.get_channel(LEAVE_TRACKING_CHANNEL_ID)
    if leave_tracking_channel:
        safe_reason = sanitize_public_text(request_data.get("reason", "N/A"))
        safe_mode = sanitize_public_text(request_data.get("mode", ""))
        mode_line = f"\nMode: {safe_mode}" if safe_mode else ""
        auto_approved_message = (
            f"Leave on ({date_range_str})\n"
            f"Leave Type: {request_data.get('type', 'unknown').capitalize()}\n"
            f"Reason: {safe_reason}{mode_line}\n"
            f"From {interaction.user.display_name} auto approved by {interaction.client.user.display_name}."
        )
        await leave_tracking_channel.send(
            auto_approved_message,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    if request_data.get("type") == "hostel_work":
        return await interaction.followup.send(
            "Your hostel work request has been automatically approved. "
            "Please remember to post your status update for the selected date(s), otherwise warnings may still apply.",
            ephemeral=True,
        )

    return await interaction.followup.send(
        "Your leave request has been automatically approved.",
        ephemeral=True,
    )


def is_core_member(user_roles):
    return any(role.name == "Core Member" for role in user_roles)


def validate_date_format(date_str):
    if not date_str or not date_str.strip():
        raise ValueError("Date cannot be empty.")

    date_str = date_str.strip()
    if not re.match(r"^\d{2}-\d{2}-\d{4}$", date_str):
        raise ValueError("Date must be in DD-MM-YYYY format (e.g., 14-09-2025).")

    try:
        return datetime.datetime.strptime(date_str, "%d-%m-%Y").date()
    except ValueError as exc:
        raise ValueError("Invalid date. Please check day/month values are correct.") from exc


def validate_status_date(date_str):
    date_obj = validate_date_format(date_str)
    today = datetime.date.today()

    if date_obj > today:
        raise ValueError("Date cannot be in the future.")

    oldest_allowed = today - relativedelta(months=LATE_SUBMISSION_MONTHS_LIMIT)
    if date_obj < oldest_allowed:
        raise ValueError(
            f"Cannot submit status older than {LATE_SUBMISSION_MONTHS_LIMIT} month(s)."
        )

    return date_obj


def validate_leave_date_range(date_range_str):
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
    if not hours_str or not hours_str.strip():
        raise ValueError("Hours cannot be empty.")

    try:
        hours = float(hours_str)
    except ValueError as exc:
        raise ValueError("Hours must be a valid number (e.g., 8, 8.5, 6.25).") from exc

    if not math.isfinite(hours):
        raise ValueError("Hours must be a finite number.")
    if hours < 0:
        raise ValueError("Hours cannot be negative.")
    if hours > 15:
        raise ValueError("Hours cannot exceed 15 in a single day.")

    if is_weekend:
        min_hours = 6 if not is_wfh else 3
        day_type = "weekend"
    else:
        min_hours = 4 if not is_wfh else 2
        day_type = "weekday"

    return hours, min_hours, day_type


def validate_work_description(description):
    if not description or not description.strip():
        raise ValueError("Work description cannot be empty.")

    description = description.strip()
    if len(description) > 5000:
        raise ValueError("Work description cannot exceed 5000 characters.")

    unique_chars = len(set(description.replace(" ", "").lower()))
    if unique_chars < 3:
        raise ValueError("Work description must contain meaningful content.")

    return description


def validate_user_roles(user_roles):
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
        raise ValueError(
            "You must have a year role (Trainee Member, 1st_years, 2nd_years, 3rd_years, 4th_years) to use this bot."
        )

    return team_role, year_role


def is_late_submission(submission_date):
    return submission_date < datetime.date.today()


class StatusForm(discord.ui.Modal, title="Daily Status Update"):
    def __init__(self, wfh_option: str):
        super().__init__(title="Daily Status Update")
        normalized_wfh = wfh_option.strip().lower()
        if normalized_wfh not in {"yes", "no"}:
            raise ValueError("Work from hostel selection must be either 'Yes' or 'No'.")

        self.wfh_option = normalized_wfh

        self.date_input = discord.ui.TextInput(
            label="Date (DD-MM-YYYY)",
            placeholder="e.g., 04-09-2025",
            required=True,
            max_length=10,
            default=datetime.date.today().strftime("%d-%m-%Y"),
            custom_id="date_input",
        )
        self.add_item(self.date_input)

        self.hours_input = discord.ui.TextInput(
            label="Hours Worked",
            placeholder="e.g., 8",
            required=True,
            max_length=8,
            custom_id="hours_input",
        )
        self.add_item(self.hours_input)

        self.work_description = discord.ui.TextInput(
            label="Work Description",
            placeholder="What did you work on today?",
            style=discord.TextStyle.paragraph,
            required=True,
            custom_id="work_description",
        )
        self.add_item(self.work_description)

        self.blockers = discord.ui.TextInput(
            label="Blockers (if any)",
            placeholder="Any issues you are facing?",
            style=discord.TextStyle.paragraph,
            required=False,
            custom_id="blockers",
        )
        self.add_item(self.blockers)

    async def on_submit(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id

        try:
            validate_current_team_member(interaction.user.roles)
            validate_user_roles(interaction.user.roles)

            submission_date = validate_status_date(self.date_input.value)
            is_late = is_late_submission(submission_date)
            is_wfh = self.wfh_option == "yes"
            is_weekend = submission_date.weekday() >= 5

            existing_submissions = get_user_submissions_for_date(guild_id, interaction.user.id, submission_date)
            if existing_submissions:
                await interaction.response.send_message(
                    "You have already submitted a status update for this date. Only one submission per day is allowed.",
                    ephemeral=True,
                )
                return

            hours_worked, min_hours, day_type = validate_hours(
                self.hours_input.value,
                is_wfh,
                is_weekend,
            )
            _, total_weekly = check_weekly_target(guild_id, interaction.user.id, submission_date, hours_worked)

            work_desc = validate_work_description(self.work_description.value)
            blockers_text = self.blockers.value.strip() if self.blockers.value else "None"
            if len(blockers_text) > 500:
                await interaction.response.send_message(
                    "Blockers description cannot exceed 500 characters.",
                    ephemeral=True,
                )
                return

            target_channel = await get_user_status_channel(interaction.guild, interaction.user.roles)
            if not target_channel:
                await interaction.response.send_message(
                    "Could not find a matching status channel for your roles. Please contact an admin.",
                    ephemeral=True,
                )
                return

        except ValueError as exc:
            await interaction.response.send_message(f"Validation Error: {exc}", ephemeral=True)
            return
        except Exception as exc:
            await interaction.response.send_message(f"An unexpected error occurred: {exc}", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        safe_work_desc = sanitize_code_block_text(work_desc)
        safe_blockers = sanitize_code_block_text(blockers_text)
        late_indicator = " (Late Submission)" if is_late else ""
        status_message = (
            f"```Namah Shivaya ({submission_date.strftime('%d-%m-%Y')}){late_indicator}\n"
            f"{safe_work_desc}\n\n"
            f"Work from hostel: {'YES' if is_wfh else 'NO'}\n"
            f"Blockers: {safe_blockers}\n"
            f"Time Spent: {hours_worked} hrs\n"
            f"Weekly Progress: {total_weekly:.1f}/32 hours```\n"
            f"By {interaction.user.display_name}"
        )

        try:
            await target_channel.send(
                status_message,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except Exception as exc:
            await interaction.followup.send(
                f"Could not post your status update to the target channel: {exc}",
                ephemeral=True,
            )
            return

        record_status_update(
            guild_id=guild_id,
            user_id=interaction.user.id,
            username=interaction.user.display_name,
            date=submission_date,
            hours=hours_worked,
            description=work_desc,
            blockers=blockers_text,
            is_wfh=is_wfh,
            is_late=is_late,
        )

        success_msg = "Your status update has been accepted and posted."
        wfh_note = " (WFH)" if is_wfh else ""
        if hours_worked < min_hours:
            success_msg += f" Note: Minimum {min_hours} hours for {day_type}{wfh_note} is recommended."
        else:
            success_msg += " Reminder: Weekdays require minimum 4 hours and weekends require minimum 6 hours."

        if total_weekly >= 32:
            success_msg += " Target achieved!"
        elif total_weekly > 25:
            success_msg += f" Warning: {32 - total_weekly:.1f} hours remaining this week."

        await interaction.followup.send(success_msg, ephemeral=True)

        try:
            export_to_csv(guild_id)
        except Exception as exc:
            print(f"CSV export error: {exc}")


class CasualLeaveModal(discord.ui.Modal, title="Casual Leave Request"):
    date_range = discord.ui.TextInput(
        label="Date Range (DD-MM-YYYY to DD-MM-YYYY)",
        placeholder="e.g., 14-09-2025 to 15-09-2025",
        required=True,
        custom_id="casual_date_range",
    )
    reason = discord.ui.TextInput(
        label="Reason for Leave",
        style=discord.TextStyle.paragraph,
        placeholder="Optional",
        required=False,
        custom_id="casual_reason",
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild.id

        try:
            validate_current_team_member(interaction.user.roles)
            validate_user_roles(interaction.user.roles)
            start_date, end_date, start_date_str, end_date_str = validate_leave_date_range(self.date_range.value)
            reason = self.reason.value.strip() if self.reason.value else "No reason provided"
            if len(reason) > 500:
                await interaction.followup.send("Reason cannot exceed 500 characters.", ephemeral=True)
                return

            if has_overlapping_leave_request(guild_id, interaction.user.id, start_date, end_date):
                await interaction.followup.send(
                    "This leave overlaps with an existing pending or approved leave request.",
                    ephemeral=True,
                )
                return

        except ValueError as exc:
            await interaction.followup.send(f"Validation Error: {exc}", ephemeral=True)
            return

        requested_days = (end_date - start_date).days + 1
        requested_by_month = split_days_by_month(start_date, end_date)

        for (year, month), requested_in_month in requested_by_month.items():
            used_days, allowed_days = get_casual_leave_usage(
                guild_id,
                interaction.user.id,
                month,
                year,
                interaction.user.roles,
            )
            if allowed_days != float("inf") and used_days + requested_in_month > allowed_days:
                remaining = max(0, allowed_days - used_days)
                await interaction.followup.send(
                    f"Casual leave limit exceeded for {month:02d}-{year}. "
                    f"You have {remaining} day(s) remaining in that month and requested {requested_in_month}.",
                    ephemeral=True,
                )
                return

        record_casual_leave(guild_id, interaction.user.id, start_date_str, end_date_str, requested_days)

        leave_tracking_channel = interaction.guild.get_channel(LEAVE_TRACKING_CHANNEL_ID)
        if leave_tracking_channel:
            leave_message = (
                f"Leave on ({self.date_range.value})\n"
                f"Leave Type: Casual Leave\n"
                f"Reason: {sanitize_public_text(reason)}\n"
                f"From {interaction.user.display_name} approved by {interaction.client.user.display_name}"
            )
            await leave_tracking_channel.send(
                leave_message,
                allowed_mentions=discord.AllowedMentions.none(),
            )

        await interaction.followup.send(
            f"Your casual leave has been auto-approved for {requested_days} day(s).",
            ephemeral=True,
        )

        try:
            export_to_csv(guild_id)
        except Exception as exc:
            print(f"CSV export error: {exc}")


class MedicalLeaveModal(discord.ui.Modal, title="Medical Leave Request"):
    date_range = discord.ui.TextInput(
        label="Date Range (DD-MM-YYYY to DD-MM-YYYY)",
        placeholder="e.g., 14-09-2025 to 14-09-2025",
        required=True,
        custom_id="medical_date_range",
    )
    reason = discord.ui.TextInput(
        label="Reason for Leave",
        style=discord.TextStyle.paragraph,
        placeholder="e.g., Flu, high fever, etc.",
        required=True,
        custom_id="medical_reason",
    )
    mode = discord.ui.TextInput(
        label="Mode (Day-off or WFH)",
        placeholder="e.g., Day-off or WFH",
        required=True,
        custom_id="medical_mode",
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild.id

        try:
            validate_current_team_member(interaction.user.roles)
            validate_user_roles(interaction.user.roles)
            start_date, end_date, start_date_str, end_date_str = validate_leave_date_range(self.date_range.value)

            reason = self.reason.value.strip()
            if not reason:
                await interaction.followup.send("Medical leave reason is required.", ephemeral=True)
                return
            if len(reason) > 500:
                await interaction.followup.send("Reason cannot exceed 500 characters.", ephemeral=True)
                return

            mode = self.mode.value.strip().lower()
            if mode not in {"day-off", "wfh"}:
                await interaction.followup.send("Mode must be either 'Day-off' or 'WFH'.", ephemeral=True)
                return

            if has_overlapping_leave_request(guild_id, interaction.user.id, start_date, end_date):
                await interaction.followup.send(
                    "This leave overlaps with an existing pending or approved leave request.",
                    ephemeral=True,
                )
                return

        except ValueError as exc:
            await interaction.followup.send(f"Validation Error: {exc}", ephemeral=True)
            return

        request_id = str(uuid.uuid4())
        request_data = {
            "request_id": request_id,
            "type": "medical",
            "member_id": interaction.user.id,
            "username": interaction.user.display_name,
            "dates": {"start": start_date_str, "end": end_date_str},
            "reason": reason,
            "mode": mode,
            "status": "pending",
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

        if is_core_member(interaction.user.roles):
            request_data["status"] = "auto-approved"
            return await handle_auto_approval(interaction, request_data, self.date_range.value)

        append_pending_request(guild_id, request_data)

        leave_embed = discord.Embed(
            title="New Medical Leave Request",
            color=discord.Color.gold(),
            description=(
                f"Submitted by: {interaction.user.display_name}\n"
                f"Reason: {sanitize_public_text(reason)}\n"
                f"Mode: {sanitize_public_text(mode)}"
            ),
        )
        leave_embed.add_field(name="Date Range", value=self.date_range.value, inline=False)
        leave_embed.add_field(name="Status", value="Pending", inline=False)

        leave_request_channel = interaction.guild.get_channel(LEAVE_REQUEST_CHANNEL_ID)
        if leave_request_channel:
            await leave_request_channel.send(
                "A new leave request is waiting!",
                embed=leave_embed,
                view=LeaveApprovalView(request_id=request_id),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        else:
            print(f"Leave request channel {LEAVE_REQUEST_CHANNEL_ID} not found")

        await interaction.followup.send("Your medical leave request has been submitted for review.", ephemeral=True)


class SpecialLeaveModal(discord.ui.Modal, title="Special Leave Request"):
    date_range = discord.ui.TextInput(
        label="Date Range (DD-MM-YYYY to DD-MM-YYYY)",
        placeholder="e.g., 14-09-2025 to 18-09-2025",
        required=True,
        custom_id="special_date_range",
    )
    reason = discord.ui.TextInput(
        label="Reason for Leave",
        style=discord.TextStyle.paragraph,
        placeholder="e.g., Exams, family emergency, etc.",
        required=True,
        custom_id="special_reason",
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild.id

        try:
            validate_current_team_member(interaction.user.roles)
            validate_user_roles(interaction.user.roles)
            start_date, end_date, start_date_str, end_date_str = validate_leave_date_range(self.date_range.value)

            days_difference = (end_date - start_date).days + 1
            if days_difference > MAX_SPECIAL_LEAVE_DAYS:
                await interaction.followup.send(
                    f"Special leave requests cannot exceed {MAX_SPECIAL_LEAVE_DAYS} days.",
                    ephemeral=True,
                )
                return

            reason = self.reason.value.strip()
            if not reason:
                await interaction.followup.send("Special leave reason is required.", ephemeral=True)
                return
            if len(reason) > 500:
                await interaction.followup.send("Reason cannot exceed 500 characters.", ephemeral=True)
                return

            if has_overlapping_leave_request(guild_id, interaction.user.id, start_date, end_date):
                await interaction.followup.send(
                    "This leave overlaps with an existing pending or approved leave request.",
                    ephemeral=True,
                )
                return

        except ValueError as exc:
            await interaction.followup.send(f"Validation Error: {exc}", ephemeral=True)
            return

        request_id = str(uuid.uuid4())
        request_data = {
            "request_id": request_id,
            "type": "special",
            "member_id": interaction.user.id,
            "username": interaction.user.display_name,
            "dates": {"start": start_date_str, "end": end_date_str},
            "reason": reason,
            "status": "pending",
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

        if is_core_member(interaction.user.roles):
            request_data["status"] = "auto-approved"
            return await handle_auto_approval(interaction, request_data, self.date_range.value)

        append_pending_request(guild_id, request_data)

        leave_embed = discord.Embed(
            title="New Special Leave Request",
            color=discord.Color.gold(),
            description=(
                f"Submitted by: {interaction.user.display_name}\n"
                f"Reason: {sanitize_public_text(reason)}"
            ),
        )
        leave_embed.add_field(name="Date Range", value=self.date_range.value, inline=False)
        leave_embed.add_field(name="Status", value="Pending", inline=False)

        leave_request_channel = interaction.guild.get_channel(LEAVE_REQUEST_CHANNEL_ID)
        if leave_request_channel:
            await leave_request_channel.send(
                embed=leave_embed,
                view=LeaveApprovalView(request_id=request_id),
                allowed_mentions=discord.AllowedMentions.none(),
            )

        await interaction.followup.send("Your special leave request has been submitted for review.", ephemeral=True)


class WorkFromHostelModal(discord.ui.Modal, title="Hostel Work Leave Request"):
    def __init__(self):
        super().__init__(title="Hostel Work Leave Request")
        today_str = datetime.date.today().strftime("%d-%m-%Y")
        default_range = f"{today_str} to {today_str}"

        self.date_range = discord.ui.TextInput(
            label="Date Range (DD-MM-YYYY to DD-MM-YYYY)",
            placeholder="e.g., 14-09-2025 to 18-09-2025",
            default=default_range,
            required=True,
            custom_id="hostel_work_date_range",
        )
        self.add_item(self.date_range)

        self.reason = discord.ui.TextInput(
            label="Reason for Hostel Work",
            style=discord.TextStyle.paragraph,
            placeholder="e.g., Personal work, family situation, etc.",
            required=True,
            custom_id="hostel_work_reason",
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild.id

        try:
            validate_current_team_member(interaction.user.roles)
            validate_user_roles(interaction.user.roles)
            start_date, end_date, start_date_str, end_date_str = validate_leave_date_range(self.date_range.value)

            reason = self.reason.value.strip()
            if not reason:
                await interaction.followup.send("Hostel work leave reason is required.", ephemeral=True)
                return
            if len(reason) > 500:
                await interaction.followup.send("Reason cannot exceed 500 characters.", ephemeral=True)
                return

            if has_overlapping_leave_request(guild_id, interaction.user.id, start_date, end_date):
                await interaction.followup.send(
                    "This leave overlaps with an existing pending or approved leave request.",
                    ephemeral=True,
                )
                return

        except ValueError as exc:
            await interaction.followup.send(f"Validation Error: {exc}", ephemeral=True)
            return

        request_id = str(uuid.uuid4())
        request_data = {
            "request_id": request_id,
            "type": "hostel_work",
            "member_id": interaction.user.id,
            "username": interaction.user.display_name,
            "dates": {"start": start_date_str, "end": end_date_str},
            "reason": reason,
            "status": "pending",
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

        if is_core_member(interaction.user.roles):
            request_data["status"] = "auto-approved"
            return await handle_auto_approval(interaction, request_data, self.date_range.value)

        append_pending_request(guild_id, request_data)

        leave_embed = discord.Embed(
            title="New Hostel Work Leave Request",
            color=discord.Color.orange(),
            description=(
                f"Submitted by: {interaction.user.display_name}\n"
                f"Reason: {sanitize_public_text(reason)}"
            ),
        )
        leave_embed.add_field(name="Date Range", value=self.date_range.value, inline=False)
        leave_embed.add_field(name="Status", value="Pending", inline=False)

        leave_request_channel = interaction.guild.get_channel(LEAVE_REQUEST_CHANNEL_ID)
        if leave_request_channel:
            await leave_request_channel.send(
                "A new hostel work leave request is waiting!",
                embed=leave_embed,
                view=LeaveApprovalView(request_id=request_id),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        else:
            print(f"Leave request channel {LEAVE_REQUEST_CHANNEL_ID} not found")

        await interaction.followup.send(
            "Your hostel work request has been submitted for review. "
            "If it is approved, you still need to post your status update for the selected date(s), "
            "otherwise warnings may still apply.",
            ephemeral=True,
        )


worK_from_hostel = WorkFromHostelModal
