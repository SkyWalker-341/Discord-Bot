from __future__ import annotations

import datetime
import json
import re
from pathlib import Path
from typing import Iterable

import discord
from openai import APIError, AsyncOpenAI, AuthenticationError, BadRequestError, RateLimitError

from ..config import TEAM_SUMMARY_API_KEY, TEAM_SUMMARY_BASE_URL, TEAM_SUMMARY_MODEL
from .storage import guild_reports_dir
from .user_stats import load_user_data

TEAM_ROLE_DISPLAY_NAMES = {
    "RedTeam": "Red Team",
    "Android": "Android",
    "BlockChain": "Blockchain",
    "Mobile": "Mobile",
}

TEAM_ROLE_ALIASES = {
    "red": "RedTeam",
    "redteam": "RedTeam",
    "redteaming": "RedTeam",
    "android": "Android",
    "blockchain": "BlockChain",
    "blockchainteam": "BlockChain",
    "mobile": "Mobile",
}


def _normalize_team_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.strip().lower())


def _clean_text(value: str | None, *, default: str = "") -> str:
    if value is None:
        return default
    cleaned = " ".join(str(value).split()).strip()
    return cleaned or default


def _parse_submission_date(value: str | None) -> datetime.date | None:
    if not value:
        return None

    for date_format in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(value, date_format).date()
        except ValueError:
            continue
    return None


def format_summary_date(value: datetime.date) -> str:
    return value.strftime("%d/%m/%Y")


def parse_summary_date(value: str) -> datetime.date:
    normalized = value.strip()

    for date_format in ("%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.datetime.strptime(normalized, date_format).date()
        except ValueError:
            continue

    raise ValueError(f"Invalid date '{value}'. Use DD/MM/YYYY format.")


def resolve_team_role_name(team_name: str) -> str:
    if not team_name or not team_name.strip():
        raise ValueError("A team name is required when summary mode is enabled.")

    normalized = _normalize_team_key(team_name)
    if normalized in TEAM_ROLE_ALIASES:
        return TEAM_ROLE_ALIASES[normalized]

    for role_name in TEAM_ROLE_DISPLAY_NAMES:
        if normalized == _normalize_team_key(role_name):
            return role_name

    valid_teams = ", ".join(("red", "android", "blockchain", "mobile"))
    raise ValueError(f"Unknown team '{team_name}'. Choose one of: {valid_teams}.")


def get_team_display_name(team_role_name: str) -> str:
    return TEAM_ROLE_DISPLAY_NAMES.get(team_role_name, team_role_name)


def _member_has_team_role(member: discord.Member, team_role_name: str) -> bool:
    return any(role.name == team_role_name for role in member.roles)


def get_team_members(members: Iterable[discord.Member], team_role_name: str) -> list[discord.Member]:
    team_members = [member for member in members if _member_has_team_role(member, team_role_name)]
    team_members.sort(key=lambda member: member.display_name.lower())
    return team_members


def collect_team_status_updates(
    guild_id: int,
    members: Iterable[discord.Member],
    start_date: datetime.date,
    end_date: datetime.date,
) -> tuple[list[dict], int]:
    data = load_user_data(guild_id)
    grouped_updates: list[dict] = []
    total_updates = 0

    for member in members:
        user_record = data.get(str(member.id), {})
        submissions = []

        for submission in user_record.get("submissions", {}).values():
            submission_date = _parse_submission_date(submission.get("date"))
            if submission_date is None or not (start_date <= submission_date <= end_date):
                continue

            description = _clean_text(submission.get("description"), default="No work description provided.")
            blockers = _clean_text(submission.get("blockers"), default="No blockers mentioned.")

            submissions.append(
                {
                    "date": submission_date.isoformat(),
                    "hours": float(submission.get("hours", 0.0) or 0.0),
                    "description": description[:2000],
                    "blockers": blockers[:1000],
                    "work_mode": "WFH" if submission.get("is_wfh") else "Onsite",
                    "is_late": bool(submission.get("is_late", False)),
                }
            )

        submissions.sort(key=lambda item: item["date"])
        total_updates += len(submissions)
        grouped_updates.append(
            {
                "member_name": member.display_name,
                "member_id": member.id,
                "updates": submissions,
            }
        )

    return grouped_updates, total_updates


def build_team_summary_prompt(
    team_display_name: str,
    start_date: datetime.date,
    end_date: datetime.date,
    grouped_updates: list[dict],
) -> tuple[str, str]:
    system_prompt = (
        "You summarize engineering status updates. Use only the facts in the provided JSON. "
        "Do not invent tasks, blockers, progress, or conclusions. Output concise Markdown only."
    )

    payload = {
        "team": team_display_name,
        "start_date": format_summary_date(start_date),
        "end_date": format_summary_date(end_date),
        "members": grouped_updates,
    }

    user_prompt = (
        f"Create a structured markdown summary for the {team_display_name} team.\n\n"
        "Required format:\n"
        f"# Team: {team_display_name}\n"
        "## <Member Name>\n"
        "- Concise summary of the member's work during the range\n"
        "- Mention blockers only if they were explicitly stated\n"
        "## Overall Team Summary\n"
        "- Key achievements\n"
        "- Progress highlights\n"
        "- Any blockers that were explicitly mentioned\n\n"
        "Rules:\n"
        f"- Cover the inclusive date range {format_summary_date(start_date)} to {format_summary_date(end_date)}.\n"
        "- Preserve individual member contributions before the overall team section.\n"
        "- Use only the supplied JSON. If a member has no updates, write exactly: "
        "'- No status updates submitted during this period.'\n"
        "- Keep each member section concise and informative.\n"
        "- Keep the overall team summary to 3-6 bullets.\n"
        "- Do not mention being an AI or add boilerplate disclaimers.\n\n"
        "Input JSON:\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )

    return system_prompt, user_prompt


def _extract_openai_error_details(exc: Exception) -> tuple[str | None, str | None, str]:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error_payload = body.get("error", {}) if isinstance(body.get("error"), dict) else {}
        code = error_payload.get("code") or getattr(exc, "code", None)
        error_type = error_payload.get("type")
        message = error_payload.get("message") or str(exc)
        return code, error_type, message

    return getattr(exc, "code", None), None, str(exc)


def _raise_summary_provider_error(exc: Exception) -> None:
    error_code, error_type, message = _extract_openai_error_details(exc)
    normalized_message = message.lower()

    if isinstance(exc, RateLimitError):
        if error_code == "insufficient_quota" or error_type == "insufficient_quota" or "quota" in normalized_message:
            raise RuntimeError(
                "The summary provider API key has no remaining quota. Update billing for the current key, "
                "switch to another API key, or configure another compatible provider before retrying."
            ) from exc

        raise RuntimeError(
            "The summary provider rate-limited this request. Please try again in a few minutes."
        ) from exc

    if isinstance(exc, AuthenticationError):
        raise RuntimeError(
            "The summary provider rejected the API key. Check TEAM_SUMMARY_API_KEY or OPENAI_API_KEY."
        ) from exc

    if isinstance(exc, BadRequestError):
        raise RuntimeError(
            f"The summary request was rejected by the model provider: {message}"
        ) from exc

    if isinstance(exc, APIError):
        raise RuntimeError(
            "The summary provider is temporarily unavailable. Please retry shortly."
        ) from exc


async def generate_team_summary_markdown(
    team_display_name: str,
    start_date: datetime.date,
    end_date: datetime.date,
    grouped_updates: list[dict],
) -> tuple[str, str]:
    if not TEAM_SUMMARY_API_KEY:
        raise RuntimeError(
            "Team summary generation is not configured. Set TEAM_SUMMARY_API_KEY or OPENAI_API_KEY in the environment."
        )

    system_prompt, user_prompt = build_team_summary_prompt(
        team_display_name=team_display_name,
        start_date=start_date,
        end_date=end_date,
        grouped_updates=grouped_updates,
    )

    client_kwargs = {"api_key": TEAM_SUMMARY_API_KEY}
    if TEAM_SUMMARY_BASE_URL:
        client_kwargs["base_url"] = TEAM_SUMMARY_BASE_URL

    client = AsyncOpenAI(**client_kwargs)
    try:
        response = await client.chat.completions.create(
            model=TEAM_SUMMARY_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
    except (RateLimitError, AuthenticationError, BadRequestError, APIError) as exc:
        _raise_summary_provider_error(exc)

    content = response.choices[0].message.content if response.choices else None
    if not content or not content.strip():
        raise RuntimeError("The summary model returned an empty response.")

    return content.strip(), user_prompt


def build_summary_filename(team_role_name: str, start_date: datetime.date, end_date: datetime.date) -> str:
    slug = get_team_display_name(team_role_name).lower().replace(" ", "_")
    return f"{slug}_summary_{start_date.isoformat()}_to_{end_date.isoformat()}.md"


def write_team_summary_file(guild_id: int, filename: str, markdown: str) -> Path:
    reports_dir = guild_reports_dir(guild_id)
    reports_dir.mkdir(parents=True, exist_ok=True)
    file_path = reports_dir / filename
    file_path.write_text(markdown.rstrip() + "\n", encoding="utf-8")
    return file_path


async def generate_team_summary_report(
    guild_id: int,
    members: Iterable[discord.Member],
    team_name: str,
    start_date: datetime.date,
    end_date: datetime.date,
) -> dict:
    if start_date > end_date:
        raise ValueError("start_date cannot be after end_date.")

    team_role_name = resolve_team_role_name(team_name)
    team_display_name = get_team_display_name(team_role_name)
    team_members = get_team_members(members, team_role_name)

    if not team_members:
        raise ValueError(f"No current-team members found for {team_display_name}.")

    grouped_updates, total_updates = collect_team_status_updates(
        guild_id=guild_id,
        members=team_members,
        start_date=start_date,
        end_date=end_date,
    )

    if total_updates == 0:
        raise ValueError(
            f"No status updates found for {team_display_name} between {format_summary_date(start_date)} and {format_summary_date(end_date)}."
        )

    markdown, prompt = await generate_team_summary_markdown(
        team_display_name=team_display_name,
        start_date=start_date,
        end_date=end_date,
        grouped_updates=grouped_updates,
    )

    filename = build_summary_filename(team_role_name, start_date, end_date)
    file_path = write_team_summary_file(guild_id, filename, markdown)

    return {
        "team_role_name": team_role_name,
        "team_display_name": team_display_name,
        "filename": filename,
        "file_path": file_path,
        "member_count": len(team_members),
        "status_update_count": total_updates,
        "prompt": prompt,
    }
