"""
Home page: quick stats + the "import match from URL" form/handler +
season creation + team management.
"""

import glob
import os
import re

from flask import Blueprint, current_app, request

from data.url_import import import_match_from_url
from data.teams_config import (
    list_teams,
    add_team,
    set_active_team,
    get_active_team_keyword,
)

from .layout import page


home_bp = Blueprint("home", __name__)


def _season_options(games_dir: str) -> list:
    if not os.path.isdir(games_dir):
        return []
    return sorted(
        d for d in os.listdir(games_dir)
        if os.path.isdir(os.path.join(games_dir, d))
    )


@home_bp.route("/")
def index():
    games_dir = current_app.config["GAMES_DIR"]

    if not os.path.isdir(games_dir):
        os.makedirs(games_dir, exist_ok=True)

    seasons = _season_options(games_dir)

    total_games = sum(
        len(glob.glob(os.path.join(games_dir, s, "*.json")))
        for s in seasons
    )

    teams = list_teams()
    active_keyword = get_active_team_keyword()

    team_rows = ""
    for t in teams:
        checked = "checked" if t["keyword"] == active_keyword else ""
        team_rows += f"""
        <li>
            <label>
                <input type="radio" name="team_keyword_display" {checked} disabled>
                <strong>{t['name']}</strong>
                <span class="muted">({t['keyword']})</span>
                {"<span class='muted'> - active</span>" if checked else ""}
            </label>
        </li>
        """

    active_switch_options = "".join(
        f'<option value="{t["keyword"]}" {"selected" if t["keyword"] == active_keyword else ""}>{t["name"]}</option>'
        for t in teams
    )

    season_options_html = "".join(
        f'<option value="{s}">{s}</option>' for s in seasons
    )

    body = f"""
    <section>
        <h2>Import match from URL</h2>

        <p>
            Paste the floorball.lv match-report URL below.
            The match date, teams, score, players, events and other
            available information will be read automatically from the page.
        </p>

        <form method="post" action="/import-match-url">
            <label for="match_url">
                <strong>Match report URL</strong>
            </label>

            <input
                id="match_url"
                name="match_url"
                type="url"
                required
                placeholder="https://www.floorball.lv/..."
                style="
                    width: 100%;
                    box-sizing: border-box;
                    padding: 10px;
                    margin: 8px 0 12px 0;
                    border: 1px solid #bbb;
                    border-radius: 5px;
                    font-size: 14px;
                "
            >

            <button
                type="submit"
                style="
                    padding: 9px 16px;
                    border: 0;
                    border-radius: 5px;
                    cursor: pointer;
                    font-weight: 600;
                "
            >
                Import match
            </button>
        </form>

        <p class="muted">
            The downloaded HTML is passed directly to the existing
            <code>parse_match.py</code> parser. No match information
            needs to be entered manually.
        </p>
    </section>

    <section>
        <h2>Seasons</h2>

        <p class="muted">
            {"Existing seasons: " + ", ".join(seasons) if seasons else "No seasons yet."}
        </p>

        <form method="post" action="/start-season">
            <label for="season_name">
                <strong>Start a new season</strong>
            </label>
            <p class="muted" style="margin: 4px 0 8px 0;">
                Format: <code>YYYY-YYYY</code> (e.g. <code>2026-2027</code>).
                Matches imported by URL are already filed into the right
                season automatically - use this if you want the season to
                show up before its first match is imported, or to create a
                season out of the normal August-start pattern.
            </p>

            <input
                id="season_name"
                name="season_name"
                type="text"
                required
                pattern="\\d{{4}}-\\d{{4}}"
                placeholder="2026-2027"
                style="
                    padding: 8px;
                    margin-right: 8px;
                    border: 1px solid #bbb;
                    border-radius: 5px;
                    font-size: 14px;
                "
            >

            <button
                type="submit"
                style="
                    padding: 9px 16px;
                    border: 0;
                    border-radius: 5px;
                    cursor: pointer;
                    font-weight: 600;
                "
            >
                Create season
            </button>
        </form>
    </section>

    <section>
        <h2>Teams</h2>

        <p class="muted">
            The "active" team is the one used for the "show only our team"
            filter on the season page and the record-by-opponent breakdown.
            Add another team here once you start uploading its games too.
        </p>

        <ul class="games-list">
            {team_rows}
        </ul>

        <form method="post" action="/set-active-team" style="margin-bottom: 20px;">
            <label for="active_team_keyword"><strong>Switch active team</strong></label><br>
            <select
                id="active_team_keyword"
                name="team_keyword"
                style="padding: 8px; margin: 8px 8px 0 0; border: 1px solid #bbb; border-radius: 5px;"
            >
                {active_switch_options}
            </select>
            <button
                type="submit"
                style="padding: 9px 16px; border: 0; border-radius: 5px; cursor: pointer; font-weight: 600;"
            >
                Set active
            </button>
        </form>

        <form method="post" action="/add-team">
            <label for="team_name"><strong>Add a new team</strong></label>
            <p class="muted" style="margin: 4px 0 8px 0;">
                Use the team name exactly as it appears in match reports
                (or close to it) - it's matched as a lowercase substring
                against team names in the parsed game data.
            </p>

            <input
                id="team_name"
                name="team_name"
                type="text"
                required
                placeholder="Ķekavas Bulldogs"
                style="
                    width: 100%;
                    box-sizing: border-box;
                    padding: 10px;
                    margin: 8px 0 12px 0;
                    border: 1px solid #bbb;
                    border-radius: 5px;
                    font-size: 14px;
                "
            >

            <label>
                <input type="checkbox" name="make_active" value="1">
                Make this the active team
            </label>
            <br><br>

            <button
                type="submit"
                style="padding: 9px 16px; border: 0; border-radius: 5px; cursor: pointer; font-weight: 600;"
            >
                Add team
            </button>
        </form>
    </section>

    <section>
        <p>{len(seasons)} season(s), {total_games} game(s) tracked.</p>

        <ul class='games-list'>
            <li>
                <a href='/game-stats'>Game Stats</a>
                <span class='muted'>- browse any single match</span>
            </li>

            <li>
                <a href='/season-stats'>Season Stats</a>
                <span class='muted'>- standings and leaders for one season</span>
            </li>

            <li>
                <a href='/career'>Career Stats</a>
                <span class='muted'>- totals and trends across every season</span>
            </li>
        </ul>
    </section>
    """

    return page("Floorball Stats", body)


@home_bp.route("/start-season", methods=["POST"])
def start_season():
    games_dir = current_app.config["GAMES_DIR"]
    season_name = request.form.get("season_name", "").strip()

    if not re.match(r"^\d{4}-\d{4}$", season_name):
        return page(
            "Could not create season",
            f"""
            <section>
                <p>'{season_name}' doesn't look like a season name
                (expected format: YYYY-YYYY, e.g. 2026-2027).</p>
                <p><a href="/">Back to Home</a></p>
            </section>
            """
        )

    season_dir = os.path.join(games_dir, season_name)
    already_existed = os.path.isdir(season_dir)
    os.makedirs(season_dir, exist_ok=True)

    body = f"""
    <section>
        <h2>{"Season already existed" if already_existed else "Season created"}</h2>
        <p>Season <strong>{season_name}</strong> is ready at
           <code>{season_dir}</code>.</p>
        <p>Import matches via the URL form on the home page and they'll be
           filed automatically, or place parsed JSON files directly in
           that folder.</p>
        <p><a href="/">Back to Home</a></p>
    </section>
    """
    return page("Season ready", body)


@home_bp.route("/add-team", methods=["POST"])
def add_team_route():
    team_name = request.form.get("team_name", "").strip()
    make_active = request.form.get("make_active") == "1"

    if not team_name:
        return page(
            "Could not add team",
            """
            <section>
                <p>Team name was not provided.</p>
                <p><a href="/">Back to Home</a></p>
            </section>
            """
        )

    config = add_team(team_name, make_active=make_active)
    added = next((t for t in config["teams"] if t["name"] == team_name), None)

    body = f"""
    <section>
        <h2>Team added</h2>
        <p><strong>{team_name}</strong> is now tracked
           (keyword: <code>{added['keyword'] if added else '?'}</code>).</p>
        <p>{"This is now the active team." if make_active else
            "It is not the active team yet - switch to it from the home page when you're ready to view its stats."}</p>
        <p><a href="/">Back to Home</a></p>
    </section>
    """
    return page("Team added", body)


@home_bp.route("/set-active-team", methods=["POST"])
def set_active_team_route():
    keyword = request.form.get("team_keyword", "").strip()

    try:
        config = set_active_team(keyword)
    except ValueError as exc:
        return page(
            "Could not switch team",
            f"""
            <section>
                <p>{exc}</p>
                <p><a href="/">Back to Home</a></p>
            </section>
            """
        )

    active = next((t for t in config["teams"] if t["keyword"] == keyword), None)
    body = f"""
    <section>
        <h2>Active team switched</h2>
        <p><strong>{active['name'] if active else keyword}</strong> is now
           the active team for filters and opponent breakdowns.</p>
        <p><a href="/">Back to Home</a></p>
    </section>
    """
    return page("Active team switched", body)


@home_bp.route("/import-match-url", methods=["POST"])
def import_match_url():
    games_dir = current_app.config["GAMES_DIR"]

    url = request.form.get("match_url", "").strip()

    if not url:
        return page(
            "Import failed",
            """
            <section>
                <p>Match URL was not provided.</p>
                <p><a href="/">Back to Home</a></p>
            </section>
            """
        )

    try:
        result = import_match_from_url(
            url=url,
            output_dir=games_dir,
        )

        match = result["match"]

        # Determine whether the match went to extra time
        # or a penalty shootout.
        home_notation = match.get("score_notation", {}).get("home")
        away_notation = match.get("score_notation", {}).get("away")

        notation = next(
            (
                n for n in (home_notation, away_notation)
                if n in ("ET", "PS")
            ),
            None,
        )

        score_suffix = f" {notation}" if notation else ""

        season = None

        # The importer creates the JSON directly in games_dir if called
        # with games_dir. If your normal structure is:
        #
        # data/games/2025-2026/*.json
        #
        # determine the season from the match date and move it there.
        date_value = match.get("date") or ""

        season_match = re.search(
            r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})",
            date_value,
        )

        if season_match:
            year = int(season_match.group(1))
            month = int(season_match.group(2))

            # Season convention: August-July.
            season = (
                f"{year}-{year + 1}"
                if month >= 8
                else f"{year - 1}-{year}"
            )

        # If a season can be determined, move the generated file into
        # the normal season directory.
        if season:
            source_path = result["output_path"]
            season_dir = os.path.join(games_dir, season)
            os.makedirs(season_dir, exist_ok=True)

            destination = os.path.join(
                season_dir,
                result["filename"],
            )

            # If destination differs, move it.
            if os.path.abspath(source_path) != os.path.abspath(destination):
                os.replace(source_path, destination)

            output_path = destination
        else:
            output_path = result["output_path"]

        body = f"""
        <section>
            <h2>Match imported successfully</h2>

            <p class="score">
                {match["home_team"]}
                {match["home_score"]}
                -
                {match["away_score"]}{score_suffix}
                {match["away_team"]}
            </p>

            <p>
                <strong>Date:</strong>
                {match.get("date") or "N/A"}
            </p>

            <p>
                <strong>League:</strong>
                {match.get("league") or "N/A"}
            </p>

            <p>
                <strong>Venue:</strong>
                {match.get("venue") or "N/A"}
            </p>

            <p>
                <strong>Saved as:</strong>
                <code>{output_path}</code>
            </p>

            <p>
                <a href="/">Back to Home</a>
            </p>
        </section>
        """

        return page("Match imported", body)

    except Exception as exc:
        body = f"""
        <section>
            <h2>Could not import match</h2>

            <p>
                The URL could not be parsed as a floorball.lv match report.
            </p>

            <p class="muted">
                Error: {str(exc)}
            </p>

            <p>
                <a href="/">Back to Home</a>
            </p>
        </section>
        """

        return page("Import failed", body)