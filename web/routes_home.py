"""
Home page: quick stats + the "import match from URL" form/handler.
"""

import glob
import os
import re

from flask import Blueprint, current_app, request

from data.url_import import import_match_from_url

from .layout import page


home_bp = Blueprint("home", __name__)


@home_bp.route("/")
def index():
    games_dir = current_app.config["GAMES_DIR"]

    if not os.path.isdir(games_dir):
        return page(
            "Setup needed",
            f"<p>Games folder not found: <code>{games_dir}</code></p>"
        )

    seasons = sorted(
        d for d in os.listdir(games_dir)
        if os.path.isdir(os.path.join(games_dir, d))
    )

    total_games = sum(
        len(glob.glob(os.path.join(games_dir, s, "*.json")))
        for s in seasons
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
