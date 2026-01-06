import discord
from typing import Optional

# This maps your exact team role name to the corresponding category name.
TEAM_CATEGORY_MAP = {
    "RedTeam": "Red Teaming",
    "Android": "Mobile",
    "BlockChain": "Blockchain",
    "Mobile": "Mobile",
}

# This maps your exact year role name to the channel name prefix.
YEAR_CHANNEL_PREFIX_MAP = {
    "Trainee Member": "1st",
    "1st_years": "1st",
    "2nd_years": "2nd",
    "3rd_years": "3rd",
    "4nd_years": "4th"  
}

# async def get_user_status_channel(guild: discord.Guild, user_roles: list[discord.Role]) -> Optional[discord.TextChannel]:
#     """
#     Finds the correct status channel by matching a user's team role to a category
#     and their year role to a channel within that category using a direct map.
#     """
#     # 1. Find the user's team and year role names
#     team_role_name = None
#     year_role_name = None
    
#     user_role_names = {role.name for role in user_roles}

#     for role_name in user_role_names:
#         if role_name in TEAM_CATEGORY_MAP:
#             team_role_name = role_name
#         if role_name in YEAR_CHANNEL_PREFIX_MAP:
#             year_role_name = role_name
    
#     # 2. Check if a valid team and year were found
#     if not team_role_name or not year_role_name:
#         return None

#     # 3. Use the maps to get the category and channel name
#     target_category_name = TEAM_CATEGORY_MAP.get(team_role_name)
#     target_channel_prefix = YEAR_CHANNEL_PREFIX_MAP.get(year_role_name)
    
#     if not target_category_name or not target_channel_prefix:
#         return None

#     # 4. Find the correct category by name
#     target_category = discord.utils .get(guild.categories, name=target_category_name)
#     if not target_category:
#         return None

#     # 5. Find the correct channel within the category by name
#     target_channel = discord.utils.get(target_category.text_channels, name=f"{target_channel_prefix}-year-status-updates")
    
#     return target_channel
async def get_user_status_channel(guild: discord.Guild, user_roles: list[discord.Role]) -> Optional[discord.TextChannel]:
    team_role_name = None
    year_role_name = None

    for role in user_roles:
        if role.name in TEAM_CATEGORY_MAP:
            team_role_name = role.name
        if role.name in YEAR_CHANNEL_PREFIX_MAP:
            year_role_name = role.name

    if not team_role_name or not year_role_name:
        return None

    category_name = TEAM_CATEGORY_MAP[team_role_name]
    channel_prefix = YEAR_CHANNEL_PREFIX_MAP[year_role_name]
    category = discord.utils.get(guild.categories, name=category_name)

    if not category:
        return None

    expected_channel_name = f"{channel_prefix}-year-status-updates"
    channel = discord.utils.get(category.channels, name=expected_channel_name)

    # ✅ Auto-create if missing
    if not channel:
        channel = await guild.create_text_channel(
            name=expected_channel_name,
            category=category,
            topic=f"Status updates for {channel_prefix}-year members of {team_role_name}"
        )

    return channel
