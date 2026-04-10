from __future__ import annotations

from ..config import OLD_TRAINER_ROLE_NAME, TEAM_LEAD_ROLE_NAME


ROLE_HIERARCHY = {
    "Trainee Member": 1,
    "1st_years": 1,
    "2nd_years": 2,
    OLD_TRAINER_ROLE_NAME: 2,
    "3rd_years": 3,
    "4th_years": 4,
    "Core Member": 5,
    TEAM_LEAD_ROLE_NAME: 6,
}


def get_user_level(user_roles) -> int:
    level = 0
    for role in user_roles:
        if role.name in ROLE_HIERARCHY:
            level = max(level, ROLE_HIERARCHY[role.name])
    return level


def get_role_display_name(user_roles) -> str:
    highest_level = 0
    role_name = "Unknown"

    for role in user_roles:
        if role.name in ROLE_HIERARCHY:
            level = ROLE_HIERARCHY[role.name]
            if level > highest_level:
                highest_level = level
                role_name = role.name

    return role_name


def has_role(user_roles, role_name: str) -> bool:
    return any(role.name == role_name for role in user_roles)


def is_team_lead(user_roles) -> bool:
    return has_role(user_roles, TEAM_LEAD_ROLE_NAME)


def can_act_on_member(actor_roles, target_roles) -> bool:
    return get_user_level(actor_roles) > get_user_level(target_roles)
