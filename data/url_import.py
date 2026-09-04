"""
Import a floorball.lv match report directly from its URL.

parse_match.py is NOT modified.

This module:
    1. Downloads the match-report HTML.
    2. Uses the existing parse_match() function.
    3. Reads date and team names from the parsed match.
    4. Converts Latvian dates into YYYY-MM-DD.
    5. Determines the season automatically.
    6. Saves the JSON into data/games/<season>/.

Example:

    2025-11-01_KNSS-Linde_Grupa_vs_Ķekavas_Bulldogs.json
"""

import json
import os
import re
import unicodedata
from urllib.parse import urlparse

import requests

from data.parse_match import parse_match


DEFAULT_TIMEOUT = 20

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0 Safari/537.36"
)


# Latvian month names used by floorball.lv.
LATVIAN_MONTHS = {
    "janvāris": 1,
    "janvāra": 1,
    "februāris": 2,
    "februāra": 2,
    "marts": 3,
    "marta": 3,
    "aprīlis": 4,
    "aprīļa": 4,
    "maijs": 5,
    "maija": 5,
    "jūnijs": 6,
    "jūnija": 6,
    "jūlijs": 7,
    "jūlija": 7,
    "augusts": 8,
    "augusta": 8,
    "septembris": 9,
    "septembra": 9,
    "oktobris": 10,
    "oktobra": 10,
    "novembris": 11,
    "novembra": 11,
    "decembris": 12,
    "decembra": 12,
}


def fetch_match_html(url: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    """Download a match-report page and return its HTML."""

    url = url.strip()

    if not url:
        raise ValueError("URL cannot be empty.")

    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL must start with http:// or https://.")

    if not parsed.netloc:
        raise ValueError("Invalid URL.")

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/xml;q=0.9,*/*;q=0.8"
        ),
        "Accept-Language": "lv,en;q=0.8",
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Could not download the URL: {exc}"
        ) from exc

    if not response.text.strip():
        raise ValueError(
            "The website returned an empty HTML document."
        )

    return response.text


def parse_match_date(date_value: str) -> tuple:
    """
    Parse the date returned by parse_match.py.

    Supports formats such as:

        1. novembris, 2025
        1. novembra, 2025
        24.10.2025
        24/10/2025
        24-10-2025
        2025-10-24

    Returns:

        (year, month, day)
    """

    if not date_value:
        raise ValueError(
            "Match date was not found in the HTML."
        )

    value = str(date_value).strip().lower()

    # ---------------------------------------------------------
    # Latvian format:
    #
    #   1. novembris, 2025
    #   1. novembra, 2025
    #
    # ---------------------------------------------------------

    for month_name, month_number in LATVIAN_MONTHS.items():
        pattern = (
            rf"\b(\d{{1,2}})\.?\s+"
            rf"{re.escape(month_name)}"
            rf"(?:,)?\s+"
            rf"(20\d{{2}})\b"
        )

        match = re.search(pattern, value)

        if match:
            day = int(match.group(1))
            year = int(match.group(2))

            return year, month_number, day

    # ---------------------------------------------------------
    # YYYY-MM-DD / YYYY.MM.DD / YYYY/MM/DD
    # ---------------------------------------------------------

    match = re.search(
        r"\b(20\d{2})[./-](\d{1,2})[./-](\d{1,2})\b",
        value,
    )

    if match:
        year, month, day = map(
            int,
            match.groups(),
        )

        return year, month, day

    # ---------------------------------------------------------
    # DD.MM.YYYY / DD/MM/YYYY / DD-MM-YYYY
    # ---------------------------------------------------------

    match = re.search(
        r"\b(\d{1,2})[./-](\d{1,2})[./-](20\d{2})\b",
        value,
    )

    if match:
        day, month, year = map(
            int,
            match.groups(),
        )

        return year, month, day

    raise ValueError(
        f"Could not understand match date: '{date_value}'"
    )


def make_date_filename(date_value: str) -> str:
    """Convert the parsed date to YYYY-MM-DD."""

    year, month, day = parse_match_date(date_value)

    return (
        f"{year:04d}-"
        f"{month:02d}-"
        f"{day:02d}"
    )


def season_from_date(date_value: str) -> str:
    """
    Determine the season from the match date.

    Season is assumed to run August -> July.

    Examples:

        1. novembris, 2025 -> 2025-2026
        15. marts, 2026    -> 2025-2026
        10. septembris, 2026 -> 2026-2027
    """

    year, month, _ = parse_match_date(
        date_value
    )

    if month >= 8:
        return f"{year}-{year + 1}"

    return f"{year - 1}-{year}"


def _clean_team_name(name: str) -> str:
    """
    Make a team name safe for a filename while keeping
    readable Unicode characters.
    """

    value = str(name).strip()

    # Replace slash with hyphen because slash is a path separator.
    value = value.replace("/", "-")
    value = value.replace("\\", "-")

    # Remove characters forbidden in Windows filenames.
    value = re.sub(
        r'[<>:"|?*]',
        "-",
        value,
    )

    # Collapse whitespace into underscores.
    value = re.sub(
        r"\s+",
        "_",
        value,
    )

    # Collapse repeated separators.
    value = re.sub(
        r"_+",
        "_",
        value,
    )

    value = re.sub(
        r"-+",
        "-",
        value,
    )

    return value.strip("._- ") or "unknown"


def make_match_filename(match: dict) -> str:
    """
    Build the JSON filename from parsed match information.

    Example:

        2025-11-01_KNSS-Linde_Grupa_vs_Ķekavas_Bulldogs.json
    """

    date = make_date_filename(
        match.get("date")
    )

    home = _clean_team_name(
        match.get("home_team", "home")
    )

    away = _clean_team_name(
        match.get("away_team", "away")
    )

    return f"{date}_{home}_vs_{away}.json"


def save_match_json(
    data: dict,
    games_dir: str,
) -> str:
    """
    Save the match into:

        data/games/<season>/

    Returns the complete output path.
    """

    match = data.get("match", {})

    date_value = match.get("date")

    if not date_value:
        raise ValueError(
            "The parsed match does not contain a date."
        )

    season = season_from_date(
        date_value
    )

    season_dir = os.path.join(
        games_dir,
        season,
    )

    os.makedirs(
        season_dir,
        exist_ok=True,
    )

    filename = make_match_filename(
        match
    )

    output_path = os.path.join(
        season_dir,
        filename,
    )

    if os.path.exists(output_path):
        raise FileExistsError(
            f"This match already exists: {output_path}"
        )

    with open(
        output_path,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2,
        )

    return output_path


def import_match_from_url(
    url: str,
    output_dir: str,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict:
    html = fetch_match_html(
        url,
        timeout=timeout,
    )

    data = parse_match(html)

    match = data["match"]

    season = season_from_date(
        match["date"]
    )

    output_path = save_match_json(
        data,
        output_dir,
    )

    return {
        "data": data,
        "output_path": output_path,
        "filename": os.path.basename(output_path),
        "season": season,
        "match": match,
    }