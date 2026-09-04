"""
/season-stats            - choose a season
/season/<season>         - full season analysis page

The page itself is assembled from the small render_* functions in
season_sections.py so this file stays a readable "compute -> render"
pipeline instead of one giant function.
"""

import glob
import os

from flask import Blueprint, abort, current_app

from analysis.season_stats import (
    load_games,
    build_player_season_stats,
    build_team_season_stats,
    build_season_assist_network,
    build_season_discipline,
    build_opponent_breakdown,
    build_season_overview,
    build_player_consistency,
    build_player_streaks,
    build_scoring_contribution,
    build_player_win_loss_performance,
    build_player_impact,
    build_team_with_without_players,
    build_opponent_player_performance,
    build_goal_scoring_combinations,
    build_player_discipline,
    build_penalties_followed_by_conceded_goals,
    build_first_last_scoring_impact,
    build_close_game_performance,
    build_scoring_runs,
    build_season_scoring_run_summary,
    build_team_trends,
    build_recent_form,
    build_player_reliability,
    build_game_to_game_variation,
)

from . import season_sections as sec
from .layout import esc, knss_filter_ui, page


season_bp = Blueprint("season", __name__)


@season_bp.route("/season-stats")
def season_stats_menu():
    """Top-level Season Stats section."""
    games_dir = current_app.config["GAMES_DIR"]

    if not os.path.isdir(games_dir):
        return page(
            "Season Stats",
            (
                f"<p>Games folder not found: "
                f"<code>{esc(games_dir)}</code></p>"
            ),
        )

    seasons = sorted(
        d
        for d in os.listdir(games_dir)
        if os.path.isdir(
            os.path.join(games_dir, d)
        )
    )

    body = (
        "<section>"
        "<h2>Choose a season</h2>"
        "<ul class='games-list'>"
    )

    for season in seasons:
        n_games = len(
            glob.glob(
                os.path.join(games_dir, season, "*.json")
            )
        )

        body += (
            f"<li>"
            f"<a href='/season/{esc(season)}'>"
            f"{esc(season)}"
            f"</a> "
            f"<span class='muted'>"
            f"({n_games} games)"
            f"</span>"
            f"</li>"
        )

    body += "</ul></section>"

    if not seasons:
        body = (
            "<p class='muted'>"
            "No seasons found yet."
            "</p>"
        )

    return page("Season Stats", body)


@season_bp.route("/season/<season>")
def season_page(season):
    games_dir = current_app.config["GAMES_DIR"]
    my_team_keyword = current_app.config["MY_TEAM_KEYWORD"]

    season_dir = os.path.join(games_dir, season)

    if not os.path.isdir(season_dir):
        abort(404)

    games = load_games(season_dir)

    if not games:
        return page(
            f"Season {season}",
            "<p class='muted'>No games found.</p>",
        )

    # ------------------------------------------------------------------
    # Compute every analysis (unchanged logic, just gathered here)
    # ------------------------------------------------------------------

    players = build_player_season_stats(games)
    teams = build_team_season_stats(games)
    assist_network = build_season_assist_network(games)
    discipline = build_season_discipline(games)  # noqa: F841 (kept for parity)
    opponents = build_opponent_breakdown(games, my_team_keyword)

    overview = build_season_overview(games, my_team_keyword)
    consistency = build_player_consistency(games)
    streaks = build_player_streaks(games)
    contribution = build_scoring_contribution(games, my_team_keyword)
    win_loss = build_player_win_loss_performance(games)
    impact = build_player_impact(games, my_team_keyword)
    with_without = build_team_with_without_players(games, my_team_keyword)
    opponent_players = build_opponent_player_performance(games, my_team_keyword)
    combinations = build_goal_scoring_combinations(games)
    player_discipline = build_player_discipline(games)
    penalty_conceded = build_penalties_followed_by_conceded_goals(games)
    first_last = build_first_last_scoring_impact(games, my_team_keyword)
    close_games = build_close_game_performance(games, my_team_keyword)
    scoring_runs = build_scoring_runs(games, my_team_keyword)
    run_summary = build_season_scoring_run_summary(games, my_team_keyword)
    trends = build_team_trends(games, my_team_keyword)
    recent_form = build_recent_form(games, my_team_keyword)
    reliability = build_player_reliability(games)
    variation = build_game_to_game_variation(games)

    # ------------------------------------------------------------------
    # Render each section and assemble the page
    # ------------------------------------------------------------------

    body = f"<p class='muted'>{len(games)} games tracked in this season.</p>"
    body += knss_filter_ui(my_team_keyword)

    body += sec.render_overview(overview)
    body += sec.render_standings(teams)
    body += sec.render_player_leaders(players)
    body += sec.render_consistency(consistency)
    body += sec.render_reliability(reliability)
    body += sec.render_streaks(streaks)
    body += sec.render_variation(variation)
    body += sec.render_contribution(contribution)
    body += sec.render_win_loss(win_loss)
    body += sec.render_with_without(with_without)
    body += sec.render_impact_detail(impact)
    body += sec.render_assist_network(assist_network)
    body += sec.render_goal_combinations(combinations)
    body += sec.render_unassisted_goals(assist_network)
    body += sec.render_player_discipline(player_discipline)
    body += sec.render_penalty_conceded(penalty_conceded)
    body += sec.render_opponent_record(opponents)
    body += sec.render_opponent_players(opponent_players)
    body += sec.render_first_last(first_last)
    body += sec.render_close_games(close_games)
    body += sec.render_scoring_runs(scoring_runs)
    body += sec.render_scoring_run_summary(run_summary)
    body += sec.render_team_trends(trends)
    body += sec.render_recent_form(recent_form)
    body += sec.render_games_list(games, season)
    body += sec.render_data_limitations()

    return page(f"Season {season}", body)
