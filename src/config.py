"""
Configuration module for Discord Bot
Loads all channel IDs and settings from environment variables
"""

import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Discord Bot Token
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# Channel IDs
SUPPORT_CHANNEL_ID = int(os.getenv("SUPPORT_CHANNEL_ID", "0"))
LEAVE_TRACKING_CHANNEL_ID = int(os.getenv("LEAVE_TRACKING_CHANNEL_ID", "0"))
LEAVE_REQUEST_CHANNEL_ID = int(os.getenv("LEAVE_REQUEST_CHANNEL_ID", "0"))
WARNING_CHANNEL_ID = int(os.getenv("WARNING_CHANNEL_ID", "0"))

# Role Names (can also be configured)
CURRENT_TEAM_ROLE_NAME = os.getenv("CURRENT_TEAM_ROLE_NAME", "current-team")
FIRST_PROBATION_ROLE_NAME = os.getenv("FIRST_PROBATION_ROLE_NAME", "1st Probation")
SECOND_PROBATION_ROLE_NAME = os.getenv("SECOND_PROBATION_ROLE_NAME", "2nd Probation")

# File Paths
DATA_FOLDER = os.getenv("DATA_FOLDER", "data")
USERS_FILE = os.path.join(DATA_FOLDER, "users.json")
PENDING_FILE = os.path.join(DATA_FOLDER, "pending.json")
WARNINGS_FILE = os.path.join(DATA_FOLDER, "warnings.json")
CASUAL_LEAVE_FILE = os.path.join(DATA_FOLDER, "casual_leave.json")
CURRENT_TEAM_CACHE_FILE = os.path.join(DATA_FOLDER, "current_team_cache.json")
CSV_EXPORT_FILE = os.path.join(DATA_FOLDER, "activity_report.csv")

# Bot Settings
COMMAND_PREFIX = os.getenv("COMMAND_PREFIX", "!")
MAX_CASUAL_LEAVE_DAYS = int(os.getenv("MAX_CASUAL_LEAVE_DAYS", "2"))
MAX_SPECIAL_LEAVE_DAYS = int(os.getenv("MAX_SPECIAL_LEAVE_DAYS", "92"))
WEEKLY_HOUR_TARGET = float(os.getenv("WEEKLY_HOUR_TARGET", "32.0"))
LATE_SUBMISSION_MONTHS_LIMIT = int(os.getenv("LATE_SUBMISSION_MONTHS_LIMIT", "3"))

# Warning Settings
FIRST_PROBATION_WARNING_COUNT = int(os.getenv("FIRST_PROBATION_WARNING_COUNT", "3"))
SECOND_PROBATION_WARNING_COUNT = int(os.getenv("SECOND_PROBATION_WARNING_COUNT", "4"))

# Timezone Settings
IST_OFFSET_HOURS = int(os.getenv("IST_OFFSET_HOURS", "5"))
IST_OFFSET_MINUTES = int(os.getenv("IST_OFFSET_MINUTES", "30"))

# Daily Task Times (in UTC)
WARNING_CHECK_HOUR = int(os.getenv("WARNING_CHECK_HOUR", "18"))  # 12:00 AM IST
WARNING_CHECK_MINUTE = int(os.getenv("WARNING_CHECK_MINUTE", "30"))

REMINDER_HOUR = int(os.getenv("REMINDER_HOUR", "5"))  # 10:45 PM IST
REMINDER_MINUTE = int(os.getenv("REMINDER_MINUTE", "15"))

# Validation
def validate_config():
    """Validate that all required configuration is present"""
    errors = []
    
    if not DISCORD_BOT_TOKEN:
        errors.append("DISCORD_BOT_TOKEN is missing in .env file")
    
    if SUPPORT_CHANNEL_ID == 0:
        errors.append("SUPPORT_CHANNEL_ID is missing or invalid in .env file")
    
    if LEAVE_TRACKING_CHANNEL_ID == 0:
        errors.append("LEAVE_TRACKING_CHANNEL_ID is missing or invalid in .env file")
    
    if LEAVE_REQUEST_CHANNEL_ID == 0:
        errors.append("LEAVE_REQUEST_CHANNEL_ID is missing or invalid in .env file")
    
    if WARNING_CHANNEL_ID == 0:
        errors.append("WARNING_CHANNEL_ID is missing or invalid in .env file")
    
    if errors:
        print("Configuration Errors:")
        for error in errors:
            print(f"  - {error}")
        return False
    
    print("Configuration validated successfully")
    return True


def print_config():
    """Print current configuration (for debugging)"""
    print("\nBot Configuration")
    print(f"Support Channel ID: {SUPPORT_CHANNEL_ID}")
    print(f"Leave Tracking Channel ID: {LEAVE_TRACKING_CHANNEL_ID}")
    print(f"Leave Request Channel ID: {LEAVE_REQUEST_CHANNEL_ID}")
    print(f"Warning Channel ID: {WARNING_CHANNEL_ID}")
    print(f"Current Team Role: {CURRENT_TEAM_ROLE_NAME}")
    print(f"Weekly Hour Target: {WEEKLY_HOUR_TARGET}")
    print(f"Command Prefix: {COMMAND_PREFIX}")
    print("")


# Validate on import
if __name__ == "__main__":
    validate_config()
    print_config()