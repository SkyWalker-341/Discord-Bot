from asyncio import tasks
import os
import datetime
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
import csv

from .config import (
    DISCORD_BOT_TOKEN,
    SUPPORT_CHANNEL_ID,
    WARNING_CHANNEL_ID,
    COMMAND_PREFIX,
    WARNING_CHECK_HOUR,
    WARNING_CHECK_MINUTE,
    REMINDER_HOUR,
    REMINDER_MINUTE,
    IST_OFFSET_HOURS,
    IST_OFFSET_MINUTES,
    CSV_EXPORT_FILE,
    validate_config,
    print_config
)

from .core.user_stats import load_user_data, record_status_update, find_pending_request, get_users_without_submission_for_date
from .core.warnings import give_warning,user_has_leave_on_date,should_give_warning
from .core.channel_lookup import get_user_status_channel
from .core.current_team_manager import CurrentTeamManager
from .core.current_team_manager import CURRENT_TEAM_ROLE_NAME
from .core.user_stats import count_user_statistics_for_range,get_user_submissions_for_date
from .core.utils import has_current_team_role
from .ui.buttons import LeaveApprovalView
from .ui.forms import StatusForm, CasualLeaveModal, MedicalLeaveModal, SpecialLeaveModal, export_to_csv,validate_user_roles

load_dotenv()

intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.message_content = True
intents.members = True  

# Use COMMAND_PREFIX from config
bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents)

# Initialize the current team manager
current_team_manager = CurrentTeamManager()

def generate_csv_file(file_path, report_data, from_date, to_date):
    """Generate CSV file from report data."""
    
    with open(file_path, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = [
            "Rank", "Name", "Total Hours", "Submissions", 
            "Leaves", "Late Hours", "From Date", "To Date"
        ]
        
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        
        for i, user in enumerate(report_data, start=1):
            writer.writerow({
                "Rank": i,
                "Name": user['name'],
                "Total Hours": f"{user['hours']:.1f}",
                "Submissions": user['submissions'],
                "Leaves": user['leaves'],
                "Late Hours": f"{user['late_hours']:.1f}",
                "From Date": from_date.strftime("%d-%m-%Y"),
                "To Date": to_date.strftime("%d-%m-%Y")
            })

@bot.event
async def on_ready():
    print(f'{bot.user.name} has connected to Discord!')
    
    # Validate and print configuration
    if not validate_config():
        print("Bot configuration is incomplete. Please check your .env file.")
        print("Bot will continue but some features may not work correctly.")
    
    #print_config()
    
    bot.add_view(LeaveApprovalView(request_id="dummy"))
    print('Bot is ready to receive commands.')
    try:
        synced = await bot.tree.sync()
        print(f'Synced {len(synced)} command(s)')
    except Exception as e:
        print(f'Error syncing commands: {e}')

    print(f"Heppo is online")
    check_daily_warnings.start()
    daily_reminder.start()

@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    """Handle role changes to update current-team cache."""
    
    before_roles = set(role.name.lower() for role in before.roles)
    after_roles = set(role.name.lower() for role in after.roles)
    
    current_team_role = CURRENT_TEAM_ROLE_NAME.lower()
    
    # Check if current-team role was added or removed
    if current_team_role in after_roles and current_team_role not in before_roles:
        current_team_manager.add_member_to_cache(after.guild.id, after.id)
        print(f"Added {after.display_name} to current-team cache")
        
    elif current_team_role in before_roles and current_team_role not in after_roles:
        current_team_manager.remove_member_from_cache(after.guild.id, after.id)
        print(f"Removed {after.display_name} from current-team cache")

class WFHSelect(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.select(
        cls=discord.ui.Select,
        placeholder="Work from Hostel?",
        options=[
            discord.SelectOption(label="No", value="No", description="Work from lab"),
            discord.SelectOption(label="Yes", value="Yes", description="Work from the hostel (targets are halved)"),
        ],
        custom_id="wfh_select"
    )
    async def wfh_select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        if not current_team_manager.is_current_team_member(interaction.user):
            await interaction.response.send_message(
                "Access denied. This bot only monitors members with the 'current-team' role.",
                ephemeral=True
            )
            return
            
        wfh_option = select.values[0]
        modal = StatusForm(wfh_option=wfh_option)
        await interaction.response.send_modal(modal)

class LeaveTypeView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.select(
        cls=discord.ui.Select,
        placeholder="Select Leave Type...",
        options=[
            discord.SelectOption(label="Casual Leave", value="casual"),
            discord.SelectOption(label="Medical Leave", value="medical"),
            discord.SelectOption(label="Special Leave", value="special")
        ],
        custom_id="leave_type_select"
    )
    async def leave_type_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        if not current_team_manager.is_current_team_member(interaction.user):
            await interaction.response.send_message(
                "Access denied. This bot only monitors members with the 'current-team' role.",
                ephemeral=True
            )
            return
            
        selected_type = select.values[0]
        
        if selected_type == "casual":
            modal = CasualLeaveModal()
        elif selected_type == "medical":
            modal = MedicalLeaveModal()
        elif selected_type == "special":
            modal = SpecialLeaveModal()
        else:
            await interaction.response.send_message("Invalid leave type selected.", ephemeral=True)
            return

        await interaction.response.send_modal(modal)

class SupportView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Status Updates", style=discord.ButtonStyle.green, custom_id="status_updates_btn")
    async def status_updates_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not current_team_manager.is_current_team_member(interaction.user):
            await interaction.response.send_message(
                "Access denied. This bot only monitors members with the 'current-team' role.",
                ephemeral=True
            )
            return
            
        await interaction.response.send_message("Are you working from the hostel today?", view=WFHSelect(), ephemeral=True)

    @discord.ui.button(label="Leave Tracking", style=discord.ButtonStyle.blurple, custom_id="leave_tracking_btn")
    async def leave_tracking_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not current_team_manager.is_current_team_member(interaction.user):
            await interaction.response.send_message(
                "Access denied. This bot only monitors members with the 'current-team' role.",
                ephemeral=True
            )
            return
            
        await interaction.response.send_message("Please select the type of leave:", view=LeaveTypeView(), ephemeral=True)

@bot.tree.command(name="setup_support_channel", description="Sets up the main support message with buttons.")
@commands.is_owner()
async def setup_support_channel(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    try:
        channel = await bot.fetch_channel(SUPPORT_CHANNEL_ID)
        
        embed = discord.Embed(
            title="Work & Leave Tracker",
            description="Use the buttons below to submit your daily status update or to request leave.",
            color=discord.Color.blue()
        )
        await channel.send(embed=embed, view=SupportView())
        
        await interaction.followup.send(f"Support channel message has been set up in <#{SUPPORT_CHANNEL_ID}>!", ephemeral=True)
    
    except discord.errors.NotFound:
        await interaction.followup.send(
            f"Could not find channel with ID {SUPPORT_CHANNEL_ID}. Please check your .env file.",
            ephemeral=True
        )
    
    except Exception as e:
        await interaction.followup.send(f"An unexpected error occurred: {e}", ephemeral=True)

@bot.tree.command(name="export_full_report", description="Export complete activity report (CSV only).")
@commands.has_permissions(administrator=True)
async def export_full_report_command(
    interaction: discord.Interaction,
    from_date: str = None,
    to_date: str = None
):
    """Exports activity report in CSV format only."""
    await interaction.response.defer(ephemeral=False)
    
    try:
        # Parse dates
        parsed_from_date = datetime.datetime.strptime(from_date, "%d-%m-%Y").date() if from_date else None
        parsed_to_date = datetime.datetime.strptime(to_date, "%d-%m-%Y").date() if to_date else None
        
        if parsed_from_date and parsed_to_date and parsed_from_date > parsed_to_date:
            await interaction.followup.send("from_date cannot be after to_date.", ephemeral=True)
            return
        
        # Use defaults
        if not parsed_from_date:
            parsed_from_date = datetime.date(2020, 1, 1)
        if not parsed_to_date:
            parsed_to_date = datetime.date.today()
        
        # Get data
        data = load_user_data()
        current_team_members = current_team_manager.get_current_team_members(interaction.guild)
        
        # Prepare data
        report_data = []
        total_hours = 0
        total_submissions = 0
        total_leaves = 0
        
        for member in current_team_members:
            user_id_str = str(member.id)
            if user_id_str in data:
                stats = count_user_statistics_for_range(member.id, parsed_from_date, parsed_to_date)
                report_data.append({
                    "name": member.display_name,
                    "hours": stats["total_hours_worked"],
                    "submissions": stats["total_submissions"],
                    "leaves": stats["total_leaves"],
                    "late_hours": stats["late_status_hours"]
                })
                total_hours += stats["total_hours_worked"]
                total_submissions += stats["total_submissions"]
                total_leaves += stats["total_leaves"]
        
        report_data.sort(key=lambda x: x["hours"], reverse=True)
        
        # Generate file suffix
        if from_date and to_date:
            date_range = f"{from_date} to {to_date}"
            file_suffix = f"{parsed_from_date.strftime('%d%m%Y')}_to_{parsed_to_date.strftime('%d%m%Y')}"
        else:
            date_range = "All time"
            file_suffix = "all_time"
        
        # Create reports directory
        os.makedirs("data/reports", exist_ok=True)
        
        # Generate CSV (only)
        csv_filename = f"activity_report_{file_suffix}.csv"
        csv_path = os.path.join("data/reports", csv_filename)
        generate_csv_file(csv_path, report_data, parsed_from_date, parsed_to_date)
        
        # Create embed
        embed = discord.Embed(
            title="Activity Report (CSV)",
            description=f"Report generated for **{date_range}**",
            color=discord.Color.blue(),
            timestamp=datetime.datetime.now()
        )
        
        # Summary
        avg_hours = total_hours / len(current_team_members) if current_team_members else 0
        summary = f"""
**Period:** {date_range}
**Total Members:** {len(current_team_members)}
**Total Hours:** {total_hours:.1f}h
**Total Submissions:** {total_submissions}
**Total Leaves:** {total_leaves}
**Average Hours/Member:** {avg_hours:.1f}h
"""
        embed.add_field(name="Summary", value=summary, inline=False)
        
        # Top 5 preview
        
        if report_data:  # if there is at least one member
            table_text = "```\n"
            table_text += f"{'S.No':<6} {'Name':<25} {'Hours':<8}\n"

            for i, user in enumerate(report_data, start=1):
                rank_str = f"{i:>4}"          # right-aligned number
                name_str = user['name'][:23]   # truncate long names
                hours_str = f"{user['hours']:<7.1f}"
                table_text += f"{rank_str}  {name_str:<25} {hours_str}\n"  
            table_text += "```"
            embed.add_field(
                name=f"Current Team Performance — All Members ({len(report_data)})",
                value=table_text,
                inline=False
            )
        else:
            embed.add_field(
                name="Performance",
                value="No data available for the selected period.",
                inline=False
            ) 
                
        embed.set_footer(text=f"Generated by {interaction.user.display_name}")
        
        # Send with file (only CSV)
        with open(csv_path, 'rb') as csv_file:
            file = discord.File(csv_file, filename=csv_filename)
            await interaction.followup.send(embed=embed, file=file)
        
    except ValueError as e:
        await interaction.followup.send(f"Date format error: {str(e)}\nUse DD-MM-YYYY format.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"Error generating report: {str(e)}", ephemeral=True)

@bot.tree.command(name="weekly_report", description="Get weekly report for current-team members.")
@commands.has_permissions(administrator=True)
async def weekly_report(interaction: discord.Interaction, user: discord.Member = None, week_offset: int = 0):
    await interaction.response.defer(ephemeral=True)
    
    from .core.user_stats import get_weekly_stats
    
    today = datetime.date.today()
    days_since_monday = today.weekday()
    current_week_monday = today - datetime.timedelta(days=days_since_monday)
    target_week_monday = current_week_monday - datetime.timedelta(weeks=week_offset)
    
    if user:
        if not current_team_manager.is_current_team_member(user):
            await interaction.followup.send(f"{user.display_name} is not a current-team member.", ephemeral=True)
            return
        
        stats = get_weekly_stats(user.id, target_week_monday)
        remaining_hours = stats.get('remaining_hours', max(0, 32.0 - stats['total_hours']))
        
        embed = discord.Embed(
            title=f"Weekly Report - {user.display_name}",
            description=f"Week of {target_week_monday.strftime('%d-%m-%Y')}",
            color=discord.Color.green() if stats["target_met"] else discord.Color.orange()
        )
        
        embed.add_field(
            name="Summary",
            value=f"**Total Hours:** {stats['total_hours']:.1f}/32\n"
                  f"**Submissions:** {stats['submissions_count']}\n"
                  f"**Target Met:** {'Yes' if stats['target_met'] else 'No'}\n"
                  f"**Remaining:** {remaining_hours:.1f} hours",
            inline=False
        )
        
        daily_text = ""
        daily_breakdown = stats.get("daily_breakdown", [])
        for day_info in daily_breakdown:
            daily_text += f"**{day_info['day_name']}:** {day_info['hours']} hrs\n"
        
        if daily_text:
            embed.add_field(name="Daily Breakdown", value=daily_text, inline=True)
        else:
            embed.add_field(name="Daily Breakdown", value="No daily data available", inline=True)
        
        await interaction.followup.send(embed=embed, ephemeral=True)
    
    else:
        current_team_members = current_team_manager.get_current_team_members(interaction.guild)
        summary_data = []
        current_team_count = len(current_team_members)
        
        for member in current_team_members:
            stats = get_weekly_stats(member.id, target_week_monday)
            if stats["submissions_count"] > 0:
                summary_data.append({
                    "name": member.display_name,
                    "hours": stats["total_hours"],
                    "target_met": stats["target_met"],
                    "submissions": stats["submissions_count"]
                })
        
        summary_data.sort(key=lambda x: x["hours"], reverse=True)
        
        embed = discord.Embed(
            title="Weekly Report - Current Team Members",
            description=f"Week of {target_week_monday.strftime('%d-%m-%Y')}\nTotal current-team members: {current_team_count}",
            color=discord.Color.blue()
        )
        
        summary_text = ""
        for user_data in summary_data[:15]:
            status = "Yes" if user_data["target_met"] else "No"
            summary_text += f"{status} **{user_data['name']}:** {user_data['hours']:.1f}h ({user_data['submissions']} days)\n"
        
        if summary_text:
            embed.add_field(name="User Summary", value=summary_text, inline=False)
        else:
            embed.add_field(name="User Summary", value="No submissions found for this week.", inline=False)
        
        await interaction.followup.send(embed=embed, ephemeral=True)       

@bot.tree.command(name="refresh_current_team", description="Refresh the current-team member cache.")
@commands.has_permissions(administrator=True)
async def refresh_current_team_cache(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    
    current_team_manager.force_refresh_cache(interaction.guild)
    count = current_team_manager.get_current_team_count(interaction.guild)
    
    await interaction.followup.send(f"Current-team cache refreshed. Found {count} active members.", ephemeral=True)

# Use configured times from config
@tasks.loop(time=datetime.time(hour=WARNING_CHECK_HOUR, minute=WARNING_CHECK_MINUTE, tzinfo=datetime.timezone.utc))
async def check_daily_warnings():
    print("Running daily warning check...")
    
    # Use IST offset from config
    ist_timezone = datetime.timezone(datetime.timedelta(hours=IST_OFFSET_HOURS, minutes=IST_OFFSET_MINUTES))
    ist_now = datetime.datetime.now(ist_timezone)
    yesterday = (ist_now - datetime.timedelta(days=1)).date()
    
    print(f"Checking submissions for date: {yesterday}")
    
    for guild in bot.guilds:
        print(f"\nChecking guild: {guild.name}")
        total_warnings_given = 0
        total_members_checked = 0
        exempted_count = 0
        submitted_count = 0
        leave_count = 0
        double_warning_count = 0
        single_warning_count = 0
        
        current_team_members = current_team_manager.get_current_team_members(guild)
        current_team_members_count = len(current_team_members)
        
        print(f"Found {current_team_members_count} current-team members")
        
        for member in current_team_members:
            total_members_checked += 1
            try:
                warnings_to_give = await should_give_warning(member, yesterday)
                
                if warnings_to_give > 0:
                    await give_warning(bot, member, warnings_to_give)
                    total_warnings_given += warnings_to_give
                    
                    if warnings_to_give == 2:
                        double_warning_count += 1
                        print(f"Double warning given to {member.display_name}")
                    else:
                        single_warning_count += 1
                        print(f"Warning given to {member.display_name}")
                else:
                    if member.bot:
                        reason = "bot"
                        exempted_count += 1
                    elif any(role.name in ["Core Member", "4th_years"] for role in member.roles):
                        role_names = [role.name for role in member.roles]
                        if "3rd_years" in role_names and "Core Member" in role_names:
                            reason = "3rd year Core Member (NOT exempt)"
                        else:
                            reason = "core member/4th year (exempt)"
                            exempted_count += 1
                    else:
                        if user_has_leave_on_date(member.id, yesterday):
                            reason = "has approved leave"
                            leave_count += 1
                        elif get_user_submissions_for_date(member.id, yesterday):
                            reason = "already submitted"
                            submitted_count += 1
                        else:
                            reason = "no required roles"
                            exempted_count += 1
                    
                    print(f"Skipped: {member.display_name} - {reason}")
                    
            except Exception as e:
                print(f"Error checking warning for {member.display_name}: {e}")
        
        print(f"\nSummary for {guild.name}:")
        print(f" Total members checked: {total_members_checked}")
        print(f" Submitted status: {submitted_count}")
        print(f" On approved leave: {leave_count}")
        print(f" Exempt: {exempted_count}")
        print(f" Single warnings: {single_warning_count}")
        print(f" Double warnings: {double_warning_count}")
        print(f" Total warnings given: {total_warnings_given}")
        
        # Use WARNING_CHANNEL_ID from config
        warning_channel = bot.get_channel(WARNING_CHANNEL_ID)
        if warning_channel and total_warnings_given > 0:
            summary_message = f"""
**Daily Warning Summary - {yesterday.strftime('%d-%m-%Y')}**

Submitted: {submitted_count}
On Leave: {leave_count}
Exempt: {exempted_count}
Single Warnings: {single_warning_count}
Double Warnings: {double_warning_count}
Total Warnings: {total_warnings_given}

Total checked: {total_members_checked} current-team members
            """
            try:
                await warning_channel.send(summary_message)
            except Exception as e:
                print(f"Could not send summary to warning channel: {e}")


# Use configured times from config
@tasks.loop(time=datetime.time(hour=REMINDER_HOUR, minute=REMINDER_MINUTE, tzinfo=datetime.timezone.utc))
async def daily_reminder():
    """Send daily reminders to users who haven't submitted status."""
    print("Running daily reminder check...")
    
    ist_timezone = datetime.timezone(datetime.timedelta(hours=IST_OFFSET_HOURS, minutes=IST_OFFSET_MINUTES))
    ist_now = datetime.datetime.now(ist_timezone)
    today = ist_now.date()
    
    for guild in bot.guilds:
        print(f"Checking reminders for guild: {guild.name}")
        
        non_submitters = get_users_without_submission_for_date(guild.members, today)
        
        valid_non_submitters = []
        for member in non_submitters:
            if member.bot:
                continue

            if not current_team_manager.is_current_team_member(member):
                continue
            if user_has_leave_on_date(member.id, today):
                print(f"Skipped reminder for {member.display_name}: on approved leave")
                continue

            try:
                validate_user_roles(member.roles)
                valid_non_submitters.append(member)
            except ValueError:
                continue
        
        if not valid_non_submitters:
            print(f"No valid non-submitters found in {guild.name}")
            continue
        
        print(f"Found {len(valid_non_submitters)} members who need reminders")
        
        channel_to_members = {}
        
        for member in valid_non_submitters:
            try:
                user_channel = await get_user_status_channel(guild, member.roles)
                
                if user_channel:
                    if user_channel.id not in channel_to_members:
                        channel_to_members[user_channel.id] = {
                            "channel": user_channel,
                            "members": []
                        }
                    channel_to_members[user_channel.id]["members"].append(member)
                    print(f"  - {member.display_name} → {user_channel.name}")
                else:
                    print(f"  - Could not find channel for {member.display_name}")
                    
            except Exception as e:
                print(f"Error finding channel for {member.display_name}: {e}")
                continue
        
        reminders_sent = 0
        for channel_data in channel_to_members.values():
            channel = channel_data["channel"]
            members = channel_data["members"]
            
            if members:
                mention_list = [member.mention for member in members[:10]]
                remaining_count = len(members) - 10
                
                reminder_text = f"**Reminder:** {', '.join(mention_list)}"
                if remaining_count > 0:
                    reminder_text += f" and {remaining_count} others"
                reminder_text += " - Submit your daily status update! Deadline is 11:59 PM."
                
                try:
                    await channel.send(reminder_text)
                    print(f"Sent reminder to {len(members)} members in {channel.name}")
                    reminders_sent += len(members)
                except Exception as e:
                    print(f"Error sending reminder to {channel.name}: {e}")
        
        print(f"Total reminders sent in {guild.name}: {reminders_sent} members")

if __name__ == "__main__":
    if not DISCORD_BOT_TOKEN:
        print("Error:  DISCORD_BOT_TOKEN is not set. Please check your .env file.")
    else:   
        bot.run(DISCORD_BOT_TOKEN)