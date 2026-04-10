from __future__ import annotations

import copy
import json
import os
import shutil
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from ..config import DATA_FOLDER

_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[str, threading.Lock] = {}

LEGACY_GUILD_DATA_FILES = (
    "users.json",
    "pending.json",
    "warnings.json",
    "casual_leave.json",
)


def data_root() -> Path:
    return Path(DATA_FOLDER)


def guild_data_dir(guild_id: int) -> Path:
    return data_root() / str(guild_id)


def guild_data_path(guild_id: int, filename: str) -> Path:
    return guild_data_dir(guild_id) / filename


def guild_reports_dir(guild_id: int) -> Path:
    return guild_data_dir(guild_id) / "reports"


def legacy_data_path(filename: str) -> Path:
    return data_root() / filename


def get_lock(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _LOCKS_GUARD:
        if key not in _LOCKS:
            _LOCKS[key] = threading.Lock()
        return _LOCKS[key]


@contextmanager
def locked_path(path: Path) -> Iterator[Path]:
    lock = get_lock(path)
    lock.acquire()
    try:
        yield path
    finally:
        lock.release()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return copy.deepcopy(default)
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    os.replace(temp_path, path)


def maybe_seed_guild_data(guild_id: int, allow_legacy_seed: bool) -> list[str]:
    if not allow_legacy_seed:
        return []

    seeded_files = []
    target_dir = guild_data_dir(guild_id)
    target_dir.mkdir(parents=True, exist_ok=True)

    for filename in LEGACY_GUILD_DATA_FILES:
        source = legacy_data_path(filename)
        destination = guild_data_path(guild_id, filename)
        if destination.exists() or not source.exists():
            continue
        shutil.copy2(source, destination)
        seeded_files.append(filename)

    return seeded_files
