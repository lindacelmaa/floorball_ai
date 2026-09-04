"""
Parse a floorball.lv match-report HTML block into structured JSON.

Usage (in PyCharm or terminal):
    python parse_match.py input.html output.json

Requires:
    pip install beautifulsoup4 lxml
"""

import json
import re
import sys
from bs4 import BeautifulSoup


def clean(text: str) -> str:
    """Collapse whitespace and strip &nbsp; artifacts."""
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()

def parse_score(value: str) -> tuple[int, str | None]:
    """
    Parse a floorball.lv score.

    Examples:
        "7"   -> (7, None)
        "7ET" -> (7, "ET")
        "7PS" -> (7, "PS")
    """
    value = clean(value).upper()

    match = re.fullmatch(r"(\d+)\s*(ET|PS)?", value)

    if not match:
        raise ValueError(
            f"Could not parse score: '{value}'"
        )

    score = int(match.group(1))
    notation = match.group(2)

    return score, notation

def parse_scoreboard(soup: BeautifulSoup) -> dict:
    table = soup.find("table", class_="tablo")
    row = table.find_all("tr")[1]
    cells = row.find_all("td")

    home_name = clean(cells[0].find("p").get_text())
    home_score_raw = clean(cells[1].get_text())
    meta_lines = [clean(x) for x in cells[2].stripped_strings]
    away_score_raw = clean(cells[3].get_text())
    away_name = clean(cells[4].find("p").get_text())

    home_score, home_notation = parse_score(home_score_raw)
    away_score, away_notation = parse_score(away_score_raw)

    return {
        "status": clean(table.find("th").get_text()),
        "home_team": home_name,
        "home_score": home_score,
        "away_team": away_name,
        "away_score": away_score,
        "score_notation": {
            "home": home_notation,
            "away": away_notation,
        },
        "extra_time": (
            home_notation == "ET"
            or away_notation == "ET"
        ),

        "penalty_shootout": (
                home_notation == "PS"
                or away_notation == "PS"
        ),

        # meta_lines is typically [league, round, date, time, venue]
        "league": meta_lines[0] if len(meta_lines) > 0 else None,
        "round": meta_lines[1] if len(meta_lines) > 1 else None,
        "date": meta_lines[2] if len(meta_lines) > 2 else None,
        "time": meta_lines[3] if len(meta_lines) > 3 else None,
        "venue": meta_lines[4] if len(meta_lines) > 4 else None,
    }


def parse_events(soup: BeautifulSoup) -> list:
    table = soup.find("table", class_="event_list")
    events = []
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) != 4:
            continue  # skip header/spacer rows
        side_class = cells[0].get("class", [""])[0]
        side = {"maj": "home", "vie": "away", "both": None}.get(side_class, side_class)
        time_ = clean(cells[0].get_text())
        event_type = clean(cells[1].get_text())
        score = clean(cells[2].get_text()) or None
        detail = clean(cells[3].get_text())

        if not time_ and not event_type and not detail:
            continue  # empty spacer row

        events.append({
            "time": time_,
            "side": side,
            "type": event_type,
            "score": score,
            "detail": detail,
        })
    return events


def parse_roster_table(table) -> list:
    players = []
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        name_cell = clean(cells[1].get_text())
        if not name_cell or name_cell.lower().startswith(("treneris", "pārstāvis")):
            # staff line, e.g. "Treneris Ivo Solomahins"
            if name_cell:
                players.append({"staff": name_cell})
            continue

        m = re.match(r"(.+?)\s*#(\d+)$", name_cell)
        name, number = (m.group(1), m.group(2)) if m else (name_cell, None)

        points = clean(cells[2].get_text()) if len(cells) > 2 else ""
        penalty = clean(cells[3].get_text()) if len(cells) > 3 else ""

        goals = assists = total_points = None
        pm = re.match(r"(\d+)\s*\((\d+)\+(\d+)\)", points)
        if pm:
            total_points, goals, assists = int(pm.group(1)), int(pm.group(2)), int(pm.group(3))

        players.append({
            "number": int(number) if number else None,
            "name": name.strip(),
            "points": total_points,
            "goals": goals,
            "assists": assists,
            "penalty_minutes": penalty or None,
        })
    return players


def parse_rosters(soup: BeautifulSoup) -> dict:
    wrap = soup.find("table", class_="speletaji_wrap")
    header_cells = wrap.find("tr").find_all("td")
    home_label, away_label = clean(header_cells[0].get_text()), clean(header_cells[1].get_text())

    roster_tables = wrap.find_all("table", class_="speletaji")
    return {
        home_label: parse_roster_table(roster_tables[0]),
        away_label: parse_roster_table(roster_tables[1]) if len(roster_tables) > 1 else [],
    }


def parse_goals_shots(soup: BeautifulSoup) -> list:
    table = soup.find("table", class_="goals_shots")
    if not table:
        return []
    rows = table.find_all("tr")
    period_labels = [clean(th.get_text()) for th in rows[0].find_all("th")][1:]

    summary = []
    for row in rows[1:]:
        cells = row.find_all("td")
        team = clean(cells[0].get_text())
        periods = {}
        for label, cell in zip(period_labels, cells[1:]):
            text = clean(cell.get_text())
            m = re.match(r"(\d+)\s*\((\d+)\)", text)
            if m:
                periods[label] = {"goals": int(m.group(1)), "shots": int(m.group(2))}
        summary.append({"team": team, "by_period": periods})
    return summary


def parse_referees_attendance(soup: BeautifulSoup) -> dict:
    result = {"referees": None, "attendance": None}
    for p in soup.find_all("p"):
        text = clean(p.get_text())
        if text.startswith("Tiesneši:"):
            result["referees"] = [r.strip() for r in text.replace("Tiesneši:", "").split(",")]
        elif text.startswith("Apmeklētāji"):
            m = re.search(r"(\d+)", text)
            result["attendance"] = int(m.group(1)) if m else None
    return result


def make_soup(html: str) -> BeautifulSoup:
    # Prefer lxml, but don't crash the whole script if it's missing/broken.
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def parse_match(html: str) -> dict:
    soup = make_soup(html)

    table = soup.find("table", class_="tablo")
    if table is None:
        found_classes = sorted({
            c
            for t in soup.find_all("table")
            for c in (t.get("class") or [])
        })
        raise ValueError(
            "Could not find <table class=\"tablo\"> in the input HTML.\n"
            f"Tables found instead have these classes: {found_classes or '(none found — no <table> tags at all)'}\n"
            "This usually means input.html doesn't contain the match-report snippet "
            "(e.g. it's a full page save, a login/error page, or the wrong file)."
        )

    return {
        "match": parse_scoreboard(soup),
        "events": parse_events(soup),
        "rosters": parse_rosters(soup),
        "goals_shots_by_period": parse_goals_shots(soup),
        **parse_referees_attendance(soup),
    }


def main():
    if len(sys.argv) != 3:
        print("Usage: python parse_match.py input.html output.json")
        sys.exit(1)

    input_path, output_path = sys.argv[1], sys.argv[2]

    with open(input_path, "r", encoding="utf-8") as f:
        html = f.read()

    data = parse_match(html)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()