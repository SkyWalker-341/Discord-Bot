from asyncio import tasks
import os
import datetime
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
import csv

from .core.user_stats import load_user_data, record_status_update, find_pending_request, get_users_without_submission_for_date
from .core.warnings import give_warning,user_has_leave_on_date,should_give_warning,user_has_leave_on_date
from .core.channel_lookup import get_user_status_channel
from .core.current_team_manager import CurrentTeamManager
from .core.current_team_manager import CURRENT_TEAM_ROLE_NAME
from .core.user_stats import count_user_statistics_for_range,get_user_submissions_for_date
from .core.utils import has_current_team_role
from .ui.buttons import LeaveApprovalView
from .ui.forms import StatusForm, CasualLeaveModal, MedicalLeaveModal, SpecialLeaveModal, export_to_csv,validate_user_roles

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.message_content = True
intents.members = True  

# welcome to heppo 

bot = commands.Bot(command_prefix="!", intents=intents)

# Initialize the current team manager
current_team_manager = CurrentTeamManager()

# Define CSV export file path
CSV_EXPORT_FILE = os.path.join("data", "activity_report.csv")

def export_current_team_csv(guild, from_date=None, to_date=None):
    """
    Export CSV data for only current-team members.
    Requires guild context to check member roles.
    """
    data = load_user_data()
    csv_data = []
    
    if from_date is None:
        from_date = datetime.date(2020, 1, 1)
    if to_date is None:
        to_date = datetime.date.today()
    
    # Get all current-team members using the manager
    current_team_members = current_team_manager.get_current_team_members(guild)
    
    # Process only current-team members' data
    for member in current_team_members:
        user_id_str = str(member.id)
        if user_id_str in data:
            user_info = data[user_id_str]
            stats = count_user_statistics_for_range(member.id, from_date, to_date)
            csv_row = {
                "username": user_info.get("username", member.display_name),
                "total_status_updates": stats["total_status_updates"],
                "total_hours_worked": stats["total_hours_worked"],
                "number_of_leaves": stats["total_leaves"],
                "late_status_hours": stats["late_status_hours"],
                "total_submissions": stats["total_submissions"],
                "from_date": from_date.strftime("%d-%m-%Y"),
                "to_date": to_date.strftime("%d-%m-%Y"),
                "current_team_member": "Yes"
            }
            csv_data.append(csv_row)
    
    # Create filename
    date_suffix = f"_{from_date.strftime('%d%m%Y')}_to_{to_date.strftime('%d%m%Y')}"
    csv_file_path = CSV_EXPORT_FILE.replace('.csv', f'{date_suffix}_current_team_only.csv')
    
    # Write to CSV
    os.makedirs(os.path.dirname(csv_file_path), exist_ok=True)
    with open(csv_file_path, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ["username", "total_status_updates", "total_hours_worked", 
                     "number_of_leaves", "late_status_hours", "total_submissions",
                     "from_date", "to_date", "current_team_member"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(csv_data)
    
    return csv_file_path

@bot.event
async def on_ready():
    print(f'{bot.user.name} has connected to Discord!')
    bot.add_view(LeaveApprovalView(request_id="dummy"))
    print('Bot is ready to receive commands.')
    try:
        synced = await bot.tree.sync()
        print(f'Synced {len(synced)} command(s)')
    except Exception as e:
        print(f'Error syncing commands: {e}')

    print(f"Heppo is online")
    check_daily_warnings.start()
    daily_reminder.start()  # Start the 11 PM reminder task

@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    """Handle role changes to update current-team cache."""

    
    before_roles = set(role.name.lower() for role in before.roles)
    after_roles = set(role.name.lower() for role in after.roles)
    
    current_team_role = CURRENT_TEAM_ROLE_NAME.lower()
    
    # Check if current-team role was added or removed
    if current_team_role in after_roles and current_team_role not in before_roles:
        # Role added
        current_team_manager.add_member_to_cache(after.guild.id, after.id)
        print(f"Added {after.display_name} to current-team cache")
        
    elif current_team_role in before_roles and current_team_role not in after_roles:
        # Role removed
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
        # Check if user is current-team member before allowing interaction
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
        # Check if user is current-team member before allowing interaction
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
        # Check if user is current-team member before allowing interaction
        if not current_team_manager.is_current_team_member(interaction.user):
            await interaction.response.send_message(
                "Access denied. This bot only monitors members with the 'current-team' role.",
                ephemeral=True
            )
            return
            
        await interaction.response.send_message("Are you working from the hostel today?", view=WFHSelect(), ephemeral=True)

    @discord.ui.button(label="Leave Tracking", style=discord.ButtonStyle.blurple, custom_id="leave_tracking_btn")
    async def leave_tracking_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check if user is current-team member before allowing interaction
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

    SUPPORT_CHANNEL_ID = 1415432843886329988
    
    try:
        channel = await bot.fetch_channel(SUPPORT_CHANNEL_ID)
        
        embed = discord.Embed(
            title="Work & Leave Tracker",
            description="Use the buttons below to submit your daily status update or to request leave.",
            color=discord.Color.blue()
        )
        await channel.send(embed=embed, view=SupportView())
        
        await interaction.followup.send("Support channel message has been set up!", ephemeral=True)
    
    except discord.errors.NotFound:
        await interaction.followup.send("Could not find the specified channel. Please check the channel ID.", ephemeral=True)
    
    except Exception as e:
        await interaction.followup.send(f"An unexpected error occurred: {e}", ephemeral=True)

@bot.tree.command(name="export_csv", description="Export current-team member activity data to CSV.")
@commands.has_permissions(administrator=True)
async def export_csv_command(interaction: discord.Interaction, from_date: str = None, to_date: str = None):
    await interaction.response.defer(ephemeral=True)
    
    try:
        # Parse date strings if provided
        parsed_from_date = None
        parsed_to_date = None
        
        if from_date:
            try:
                parsed_from_date = datetime.datetime.strptime(from_date, "%d-%m-%Y").date()
            except ValueError:
                await interaction.followup.send("Invalid from_date format. Use DD-MM-YYYY (e.g., 01-01-2024)", ephemeral=True)
                return
        
        if to_date:
            try:
                parsed_to_date = datetime.datetime.strptime(to_date, "%d-%m-%Y").date()
            except ValueError:
                await interaction.followup.send("Invalid to_date format. Use DD-MM-YYYY (e.g., 31-12-2024)", ephemeral=True)
                return
        
        # Validate date range
        if parsed_from_date and parsed_to_date and parsed_from_date > parsed_to_date:
            await interaction.followup.send("from_date cannot be after to_date.", ephemeral=True)
            return

        csv_file_path = export_current_team_csv(interaction.guild, parsed_from_date, parsed_to_date)
        
        if parsed_from_date and parsed_to_date:
            date_info = f" for current-team members from {from_date} to {to_date}"
        elif parsed_from_date:
            date_info = f" for current-team members from {from_date} onwards"
        elif parsed_to_date:
            date_info = f" for current-team members up to {to_date}"
        else:
            date_info = " for all current-team members (all time)"
        
        await interaction.followup.send(f"CSV exported successfully{date_info} to: {csv_file_path}", ephemeral=True)
    
    except Exception as e:
        await interaction.followup.send(f"Error exporting CSV: {str(e)}", ephemeral=True)

@bot.tree.command(name="weekly_report", description="Get weekly report for current-team members.")
@commands.has_permissions(administrator=True)
async def weekly_report(interaction: discord.Interaction, user: discord.Member = None, week_offset: int = 0):
    await interaction.response.defer(ephemeral=True)
    
    from .core.user_stats import get_weekly_stats
    
    # Calculate week start (Monday) for the specified offset
    today = datetime.date.today()
    days_since_monday = today.weekday()
    current_week_monday = today - datetime.timedelta(days=days_since_monday)
    target_week_monday = current_week_monday - datetime.timedelta(weeks=week_offset)
    
    if user:
        # Check if specified user has current-team role
        if not current_team_manager.is_current_team_member(user):
            await interaction.followup.send(f"{user.display_name} is not a current-team member.", ephemeral=True)
            return
        
        # Single user report
        stats = get_weekly_stats(user.id, target_week_monday)
        
        # CALCULATE remaining_hours locally if not in stats
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
                  f"**Remaining:** {remaining_hours:.1f} hours",  # USE LOCAL VARIABLE
            inline=False
        )
        
        # Daily breakdown
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
        # All current-team users summary
        current_team_members = current_team_manager.get_current_team_members(interaction.guild)
        summary_data = []
        current_team_count = len(current_team_members)
        
        for member in current_team_members:
            stats = get_weekly_stats(member.id, target_week_monday)
            if stats["submissions_count"] > 0:  # Only include users with submissions
                summary_data.append({
                    "name": member.display_name,
                    "hours": stats["total_hours"],
                    "target_met": stats["target_met"],
                    "submissions": stats["submissions_count"]
                })
        
        # Sort by hours descending
        summary_data.sort(key=lambda x: x["hours"], reverse=True)
        
        embed = discord.Embed(
            title="Weekly Report - Current Team Members",
            description=f"Week of {target_week_monday.strftime('%d-%m-%Y')}\nTotal current-team members: {current_team_count}",
            color=discord.Color.blue()
        )
        
        # Create summary text
        summary_text = ""
        for user_data in summary_data[:15]:  # Limit to top 15 to avoid message limits
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

# Background task to check for daily warnings at midnight IST
@tasks.loop(time=datetime.time(hour=18, minute=30, tzinfo=datetime.timezone.utc))  # 12:00 AM IST
async def check_daily_warnings():
    print("Running daily warning check...")
    
    # Calculate yesterday's date in IST
    ist_timezone = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    ist_now = datetime.datetime.now(ist_timezone)
    yesterday = (ist_now - datetime.timedelta(days=1)).date()
    
    print(f"Checking submissions for date: {yesterday}")
    
    # Check all guilds
    for guild in bot.guilds:
        print(f"Checking guild: {guild.name}")
        warning_count = 0
        
        # Get current-team members efficiently
        current_team_members = current_team_manager.get_current_team_members(guild)
        current_team_members_count = len(current_team_members)
        
        print(f"Found {current_team_members_count} current-team members")
        
        for member in current_team_members:
            try:
                if await should_give_warning(member, yesterday):
                    await give_warning(bot, member)
                    warning_count += 1
                    print(f"Warning given to {member.display_name}")
                else:
                    # Log why warning was skipped
                    if member.bot:
                        reason = "bot"
                    elif any(role.name in ["Core Member", "4th_years"] for role in member.roles):
                        reason = "core member/4th year (exempt)"
                    else:
                        
                        if user_has_leave_on_date(member.id, yesterday):
                            reason = "has approved leave"
                        elif get_user_submissions_for_date(member.id, yesterday):
                            reason = "already submitted"
                        else:
                            reason = "no required roles"
                    
                    print(f"Skipped warning for {member.display_name}: {reason}")
                    
            except Exception as e:
                print(f"Error checking warning for {member.display_name}: {e}")
        
        print(f"Checked {current_team_members_count} current-team members in {guild.name}")
        print(f"Total warnings given: {warning_count}")

# 11:00 PM IST reminder for daily status updates
@tasks.loop(time=datetime.time(hour=8, minute=50, tzinfo=datetime.timezone.utc))  # 11:59 PM IST
async def daily_reminder():
    """
    Send daily reminders to users who haven't submitted status.
    Uses channel_lookup.py to find the correct channel for each user.
    """
    print("Running 11 PM daily reminder check...")
    
    ist_timezone = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    ist_now = datetime.datetime.now(ist_timezone)
    today = ist_now.date()
    
    for guild in bot.guilds:
        print(f"Checking reminders for guild: {guild.name}")
        
        # Get current-team members who haven't submitted today
        non_submitters = get_users_without_submission_for_date(guild.members, today)
        
        # Filter for current-team members with proper roles
        valid_non_submitters = []
        for member in non_submitters:
            if member.bot:
                continue

            # Check if member is current-team
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
        
        # Group members by their status channel
        channel_to_members = {}
        
        for member in valid_non_submitters:
            try:
                # Use channel_lookup to find the correct channel for this user
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
        
        # Send reminders to each channel
        reminders_sent = 0
        for channel_data in channel_to_members.values():
            channel = channel_data["channel"]
            members = channel_data["members"]
            
            if members:
                # Limit to 10 mentions per message to avoid Discord limits
                mention_list = [member.mention for member in members[:10]]
                remaining_count = len(members) - 10
                
                reminder_text = f"**11 PM Reminder:** {', '.join(mention_list)}"
                if remaining_count > 0:
                    reminder_text += f" and {remaining_count} others"
                reminder_text += " - Submit your daily status update! Deadline is 11:59 PM."
                
                try:
                    await channel.send(reminder_text)
                    print(f"✅ Sent reminder to {len(members)} members in {channel.name}")
                    reminders_sent += len(members)
                except Exception as e:
                    print(f"❌ Error sending reminder to {channel.name}: {e}")
        
        print(f"Total reminders sent in {guild.name}: {reminders_sent} members")

if __name__ == "__main__":
    if not TOKEN:
        print("Error: DISCORD_BOT_TOKEN not found in .env file.")
    else:
        bot.run(TOKEN)
