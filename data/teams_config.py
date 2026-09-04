"""
Tracks which team(s) we follow and which one is currently "active" - used by
the season/career pages for the "show only our team" filter and the
record-by-opponent breakdown.

Previously this was a single hardcoded constant (MY_TEAM_KEYWORD = "knss").
Now it's a small JSON file so a new team can be added/switched from the UI
without editing code.

Storage format (data/teams.json):

    {
      "teams": [
        {"name": "Kuldīgas KNSS", "keyword": "knss"},
        {"name": "Ķekavas Bulldogs", "keyword": "kekavas"}
      ],
      "active_team": "knss"
    }

"keyword" is a lowercase substring matched case-insensitively against team
names in the parsed match JSON (same matching approach as the old
MY_TEAM_KEYWORD constant), since match reports don't use a stable team ID.
"""

import json
import os
import re

DEFAULT_CONFIG_PATH = "data/teams.json"

# Seeded on first run so existing installs keep working with no setup step.
_BOOTSTRAP_TEAM = {"name": "Kuldīgas KNSS", "keyword": "knss"}


def _slugify_keyword(name: str) -> str:
    """Turn a team name into a reasonable default keyword, e.g.
    'Ķekavas Bulldogs' -> 'kekavas' (first word, lowercased, ascii-folded)."""
    first_word = name.strip().split()[0] if name.strip() else name.strip()
    # Basic ascii-fold for common Latvian diacritics so keywords stay simple.
    table = str.maketrans("āčēģīķļņōŗšūžĀČĒĢĪĶĻŅŌŖŠŪŽ", "acegiklnorsuzACEGIKLNORSUZ")
    folded = first_word.translate(table)
    return re.sub(r"[^a-z0-9]", "", folded.lower()) or "team"


def load_teams(path: str = DEFAULT_CONFIG_PATH) -> dict:
    if not os.path.exists(path):
        config = {"teams": [_BOOTSTRAP_TEAM], "active_team": _BOOTSTRAP_TEAM["keyword"]}
        save_teams(config, path)
        return config
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_teams(config: dict, path: str = DEFAULT_CONFIG_PATH) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def list_teams(path: str = DEFAULT_CONFIG_PATH) -> list:
    return load_teams(path)["teams"]


def add_team(name: str, keyword: str = None, path: str = DEFAULT_CONFIG_PATH,
             make_active: bool = True) -> dict:
    """Add a new team to track. If keyword is omitted, one is derived from
    the name. If a team with that keyword already exists, it's left as-is
    (not duplicated). Returns the updated config."""
    name = name.strip()
    if not name:
        raise ValueError("Team name cannot be empty.")

    keyword = (keyword or _slugify_keyword(name)).strip().lower()
    config = load_teams(path)

    existing = next((t for t in config["teams"] if t["keyword"] == keyword), None)
    if existing is None:
        config["teams"].append({"name": name, "keyword": keyword})

    if make_active or not config.get("active_team"):
        config["active_team"] = keyword

    save_teams(config, path)
    return config


def set_active_team(keyword: str, path: str = DEFAULT_CONFIG_PATH) -> dict:
    config = load_teams(path)
    known = {t["keyword"] for t in config["teams"]}
    if keyword not in known:
        raise ValueError(f"Unknown team keyword '{keyword}'. Known: {sorted(known)}")
    config["active_team"] = keyword
    save_teams(config, path)
    return config


def get_active_team_keyword(path: str = DEFAULT_CONFIG_PATH) -> str:
    return load_teams(path).get("active_team") or _BOOTSTRAP_TEAM["keyword"]


def get_active_team_name(path: str = DEFAULT_CONFIG_PATH) -> str:
    config = load_teams(path)
    keyword = config.get("active_team")
    match = next((t for t in config["teams"] if t["keyword"] == keyword), None)
    return match["name"] if match else keyword or "Unknown"