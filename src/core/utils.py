def has_current_team_role(user_roles):
    """
    Check if user has the 'current-team' role.
    Only members with this role should be monitored by the bot.
    """
    role_names = [role.name.lower() for role in user_roles]
    return "current-team" in role_names

def validate_current_team_member(user_roles):
    """
    Validate that user is a current team member.
    Raises ValueError if user doesn't have current-team role.
    """
    if not has_current_team_role(user_roles):
        raise ValueError("This bot only monitors members with the 'current-team' role. Please contact an admin if you should have access.")
    return True