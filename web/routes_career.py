
"""
/career - coach-oriented career, recent-form and forecast dashboard.
"""

import json
import os

from flask import (
    Blueprint,
    current_app,
    request,
)

from analysis.career_stats import (
    discover_seasons,
    build_career_team_stats,
    build_career_player_stats,
)

from .layout import (
    esc,
    fmt_signed,
    page,
    section,
    table,
    knss_filter_ui,
)

from data.teams_config import get_active_team_keyword, get_active_team_name

def _team_filter_value(entry):
    """
    Build the string used for the KNSS-filter's substring match.

    entry["team"] is only the player's MOST RECENT team, so filtering
    on it alone drops players who played for KNSS in an earlier season
    but finished their career (so far) on a different roster.

    entry["teams"] holds every team the player has ever appeared for,
    so we join all of them and match against that instead.
    """

    teams = entry.get("teams") or []

    if not teams and entry.get("team"):
        teams = [entry["team"]]

    return " | ".join(teams)


career_bp = Blueprint("career", __name__)


WINDOW_LABELS = {
    "all_season": "All season games",
    "last_5": "Last 5 games",
    "last_10": "Last 10 games",
    "last_season_current": "Last season + current season",
}


def _selected_window():
    value = request.args.get(
        "window",
        "last_5",
    )

    if value not in WINDOW_LABELS:
        return "last_5"

    return value


def _line_chart(
    title,
    points,
    series,
    height=260,
):
    """
    Generic inline SVG line chart.

    points:
        [
            {"label": "G1", "values": {"points": 2}},
            ...
        ]

    series:
        [
            ("points", "Points"),
            ...
        ]
    """

    if not points:
        return (
            "<p class='muted'>"
            "Not enough game data for this graph."
            "</p>"
        )

    width = 760

    padding_left = 45
    padding_right = 20
    padding_top = 35
    padding_bottom = 45

    chart_width = (
        width
        - padding_left
        - padding_right
    )

    chart_height = (
        height
        - padding_top
        - padding_bottom
    )

    values = []

    for point in points:
        for key, _ in series:
            values.append(
                float(
                    point["values"].get(
                        key,
                        0,
                    )
                )
            )

    maximum = max(
        values or [1]
    )

    maximum = max(
        1,
        maximum * 1.15,
    )

    svg = (
        f"<div class='trend-chart'>"
        f"<div class='chart-title'>"
        f"{esc(title)}"
        f"</div>"
        f"<svg "
        f"viewBox='0 0 {width} {height}' "
        f"width='100%' "
        f"height='{height}' "
        f"role='img' "
        f"aria-label='{esc(title)}'>"
    )

    # Grid lines.
    for i in range(5):

        ratio = i / 4

        y = (
            padding_top
            + chart_height
            - ratio * chart_height
        )

        value = maximum * ratio

        svg += (
            f"<line "
            f"x1='{padding_left}' "
            f"y1='{y:.1f}' "
            f"x2='{width - padding_right}' "
            f"y2='{y:.1f}' "
            f"stroke='#ddd'/>"
        )

        svg += (
            f"<text "
            f"x='5' "
            f"y='{y + 4:.1f}' "
            f"font-size='10'>"
            f"{value:.1f}"
            f"</text>"
        )

    # X axis.
    svg += (
        f"<line "
        f"x1='{padding_left}' "
        f"y1='{height - padding_bottom}' "
        f"x2='{width - padding_right}' "
        f"y2='{height - padding_bottom}' "
        f"stroke='#aaa'/>"
    )

    for series_index, (
        key,
        label,
    ) in enumerate(series):

        coords = []

        for i, point in enumerate(points):

            if len(points) == 1:
                x = padding_left
            else:
                x = (
                    padding_left
                    + chart_width
                    * i
                    / (len(points) - 1)
                )

            value = float(
                point["values"].get(
                    key,
                    0,
                )
            )

            y = (
                padding_top
                + chart_height
                - value / maximum
                * chart_height
            )

            coords.append(
                (x, y, value)
            )

        polyline = " ".join(
            f"{x:.1f},{y:.1f}"
            for x, y, _ in coords
        )

        svg += (
            f"<polyline "
            f"points='{polyline}' "
            f"fill='none' "
            f"stroke='{'#1a5fb4' if series_index == 0 else '#d97706' if series_index == 1 else '#15803d'}' "
            f"stroke-width='3'/>"
        )

        for x, y, value in coords:

            svg += (
                f"<circle "
                f"cx='{x:.1f}' "
                f"cy='{y:.1f}' "
                f"r='4' "
                f"fill='{'#1a5fb4' if series_index == 0 else '#d97706' if series_index == 1 else '#15803d'}'/>"
            )

        svg += (
            f"<text "
            f"x='{padding_left + series_index * 120}' "
            f"y='18' "
            f"font-size='11'>"
            f"{esc(label)}"
            f"</text>"
        )

    # X labels.
    for i, point in enumerate(points):

        if len(points) == 1:
            x = padding_left
        else:
            x = (
                padding_left
                + chart_width
                * i
                / (len(points) - 1)
            )

        label = str(
            point.get(
                "label",
                i + 1,
            )
        )

        svg += (
            f"<text "
            f"x='{x:.1f}' "
            f"y='{height - 18}' "
            f"text-anchor='middle' "
            f"font-size='9'>"
            f"{esc(label)}"
            f"</text>"
        )

    svg += "</svg></div>"

    return svg


def _forecast_chart(forecast):
    games = forecast.get(
        "games",
        [],
    )

    if not games:
        return ""

    points = [
        {
            "label": f"F{i['game']}",
            "values": {
                "projection": i["projected_points"],
            },
        }
        for i in games
    ]

    return _line_chart(
        "Projected points — next 5 games",
        points,
        [
            (
                "projection",
                "Projected points",
            ),
        ],
        height=230,
    )


def _window_selector(selected):
    options = []

    for key, label in WINDOW_LABELS.items():

        selected_attr = (
            " selected"
            if key == selected
            else ""
        )

        options.append(
            f"<option value='{esc(key)}'{selected_attr}>"
            f"{esc(label)}"
            f"</option>"
        )

    return (
        "<form method='get' class='trend-controls'>"
        "<label>"
        "<strong>Trend window</strong>"
        "<select name='window' "
        "onchange='this.form.submit()'>"
        + "".join(options)
        + "</select>"
        "</label>"
        "</form>"
    )


def _metric_card(label, value, subtitle=""):
    return (
        "<div class='card'>"
        f"<div class='label'>{esc(label)}</div>"
        f"<div class='value'>{esc(str(value))}</div>"
        f"<div class='muted'>{esc(subtitle)}</div>"
        "</div>"
    )


def render_career_player_details(
    name,
    entry,
    selected_window,
):
    career = entry["career"]

    trend = entry.get(
        "trend",
        {},
    ).get(
        selected_window,
        {},
    )

    forecast = entry.get(
        "forecast",
        {},
    ).get(
        selected_window,
        {},
    )

    coach = entry.get(
        "coach_metrics",
        {},
    ).get(
        selected_window,
        {},
    )

    summary = trend.get(
        "summary",
        {},
    )

    game_rows = trend.get(
        "games",
        [],
    )

    content = ""

    content += (
        f"<p>"
        f"<strong>Team:</strong> "
        f"{esc(entry['team'])}"
        f"</p>"
    )

    # -------------------------------------------------------------
    # Window selector
    # -------------------------------------------------------------

    content += _window_selector(
        selected_window
    )

    # -------------------------------------------------------------
    # Current form cards
    # -------------------------------------------------------------

    content += "<h3>Current form</h3>"

    content += (
        "<div class='cards'>"
        + _metric_card(
            "Games",
            summary.get("games", 0),
        )
        + _metric_card(
            "Points/GP",
            summary.get(
                "points_per_game",
                0,
            ),
        )
        + _metric_card(
            "Goals/GP",
            summary.get(
                "goals_per_game",
                0,
            ),
        )
        + _metric_card(
            "Assists/GP",
            summary.get(
                "assists_per_game",
                0,
            ),
        )
        + _metric_card(
            "PIM/GP",
            summary.get(
                "penalty_minutes_per_game",
                0,
            ),
        )
        + _metric_card(
            "Consistency",
            coach.get(
                "consistency",
                "unknown",
            ),
        )
        + "</div>"
    )

    # -------------------------------------------------------------
    # Game trend graph
    # -------------------------------------------------------------

    points = []

    for game in game_rows:
        points.append(
            {
                "label": (
                    f"G{game['game']}"
                ),
                "values": {
                    "points": game["points"],
                    "rolling": game["rolling_5"],
                },
            }
        )

    content += "<h3>Recent scoring form</h3>"

    content += _line_chart(
        "Points per game with rolling form",
        points,
        [
            (
                "points",
                "Game points",
            ),
            (
                "rolling",
                "5-game rolling average",
            ),
        ],
    )

    # -------------------------------------------------------------
    # Goals / assists graph
    # -------------------------------------------------------------

    ga_points = []

    for game in game_rows:
        ga_points.append(
            {
                "label": (
                    f"G{game['game']}"
                ),
                "values": {
                    "goals": game["goals"],
                    "assists": game["assists"],
                },
            }
        )

    content += _line_chart(
        "Goals and assists",
        ga_points,
        [
            (
                "goals",
                "Goals",
            ),
            (
                "assists",
                "Assists",
            ),
        ],
    )

    # -------------------------------------------------------------
    # Form analysis
    # -------------------------------------------------------------

    content += "<h3>Form analysis</h3>"

    direction = trend.get(
        "direction",
        "insufficient data",
    )

    slope = trend.get(
        "slope",
        0,
    )

    momentum = trend.get(
        "recent_momentum",
        0,
    )

    ppg_change = coach.get(
        "ppg_change_percent",
        0,
    )

    content += (
        "<div class='cards'>"
        + _metric_card(
            "Trend",
            direction,
            f"Slope {slope:+.3f}",
        )
        + _metric_card(
            "Recent momentum",
            f"{momentum:+.2f}",
            "points/game",
        )
        + _metric_card(
            "vs career baseline",
            f"{ppg_change:+.1f}%",
            "Pts/GP change",
        )
        + _metric_card(
            "0-point games",
            summary.get(
                "zero_point_games",
                0,
            ),
        )
        + _metric_card(
            "2+ point games",
            summary.get(
                "multi_point_games",
                0,
            ),
        )
        + _metric_card(
            "3+ point games",
            summary.get(
                "three_plus_point_games",
                0,
            ),
        )
        + "</div>"
    )

    # -------------------------------------------------------------
    # Coach flags
    # -------------------------------------------------------------

    content += "<h3>Coach indicators</h3>"

    flags = coach.get(
        "flags",
        [],
    )

    content += (
        "<ul class='coach-flags'>"
        + "".join(
            f"<li>{esc(flag)}</li>"
            for flag in flags
        )
        + "</ul>"
    )

    # -------------------------------------------------------------
    # Discipline
    # -------------------------------------------------------------

    content += "<h3>Discipline</h3>"

    content += table(
        [
            "Metric",
            "Selected window",
            "Career",
        ],
        [
            [
                "PIM",
                summary.get(
                    "penalty_minutes",
                    0,
                ),
                career.get(
                    "penalty_minutes",
                    0,
                ),
            ],
            [
                "PIM/GP",
                summary.get(
                    "penalty_minutes_per_game",
                    0,
                ),
                career.get(
                    "penalty_minutes_per_game",
                    0,
                ),
            ],
        ],
    )

    # -------------------------------------------------------------
    # Production consistency
    # -------------------------------------------------------------

    content += "<h3>Production consistency</h3>"

    content += table(
        [
            "Metric",
            "Value",
        ],
        [
            [
                "Median points/game",
                summary.get(
                    "median_points",
                    0,
                ),
            ],
            [
                "Points volatility",
                summary.get(
                    "stddev_points",
                    0,
                ),
            ],
            [
                "Goal involvement",
                f"{coach.get('goal_involvement_percent', 0):.1f}%",
            ],
            [
                "Consistency",
                coach.get(
                    "consistency",
                    "unknown",
                ),
            ],
        ],
    )

    # -------------------------------------------------------------
    # Next five games
    # -------------------------------------------------------------

    content += "<h3>Next 5 games projection</h3>"

    content += (
        "<p class='muted'>"
        "Projection is based on recent production, "
        "recency weighting, momentum and scoring volatility. "
        "It is an estimate, not a guaranteed prediction."
        "</p>"
    )

    content += (
        "<div class='cards'>"
        + _metric_card(
            "Projected Pts/GP",
            forecast.get(
                "points_per_game",
                0,
            ),
        )
        + _metric_card(
            "Projected points",
            forecast.get(
                "points_5_games",
                0,
            ),
        )
        + _metric_card(
            "Projected goals",
            forecast.get(
                "goals_5_games",
                0,
            ),
        )
        + _metric_card(
            "Projected assists",
            forecast.get(
                "assists_5_games",
                0,
            ),
        )
        + _metric_card(
            "Expected points range",
            (
                f"{forecast.get('low_points', 0):.1f}"
                f" – "
                f"{forecast.get('high_points', 0):.1f}"
            ),
        )
        + _metric_card(
            "Confidence",
            forecast.get(
                "confidence",
                "unknown",
            ),
        )
        + "</div>"
    )

    content += _forecast_chart(
        forecast
    )

    # -------------------------------------------------------------
    # Season progression
    # -------------------------------------------------------------

    content += "<h3>Season progression</h3>"

    content += table(
        [
            "Season",
            "Team",
            "GP",
            "G",
            "A",
            "P",
            "Pts/GP",
            "G/GP",
            "A/GP",
        ],
        [
            [
                esc(season),
                esc(stats["team"]),
                stats["games_played"],
                stats["goals"],
                stats["assists"],
                stats["points"],
                stats["points_per_game"],
                stats["goals_per_game"],
                stats["assists_per_game"],
            ]
            for season, stats
            in entry["by_season"].items()
        ],
    )

    # -------------------------------------------------------------
    # Career totals
    # -------------------------------------------------------------

    content += "<h3>Career totals</h3>"

    content += (
        "<div class='cards'>"
        + _metric_card(
            "Games",
            career["games_played"],
        )
        + _metric_card(
            "Goals",
            career["goals"],
        )
        + _metric_card(
            "Assists",
            career["assists"],
        )
        + _metric_card(
            "Points",
            career["points"],
        )
        + _metric_card(
            "Pts/GP",
            career["points_per_game"],
        )
        + "</div>"
    )

    return (
        f"<details "
        f"data-team='{esc(_team_filter_value(entry))}'>"
        f"<summary>"
        f"<strong>{esc(name)}</strong> "
        f"— {esc(entry['team'])}"
        f"</summary>"
        f"{content}"
        f"</details>"
    )


@career_bp.route("/career")
def career_page():

    games_dir = current_app.config[
        "GAMES_DIR"
    ]

    my_team_keyword = get_active_team_keyword()

    if not os.path.isdir(games_dir):

        return page(
            "Career",
            (
                f"<p>"
                f"Games folder not found: "
                f"<code>{esc(games_dir)}</code>"
                f"</p>"
            ),
        )

    seasons = discover_seasons(
        games_dir
    )

    if not seasons:

        return page(
            "Career",
            "<p>"
            "No season subfolders with games found."
            "</p>",
        )

    players = build_career_player_stats(
        seasons
    )

    teams = build_career_team_stats(
        seasons
    )

    selected_window = _selected_window()

    body = ""

    body += knss_filter_ui(
        my_team_keyword,
        get_active_team_name(),
    )

    body += (
        "<div class='career-header'>"
        "<h1>Career & player form</h1>"
        "<p class='muted'>"
        "Historical performance combined with "
        "recent form and next-five-game projections."
        "</p>"
        "</div>"
    )

    body += section(
        "Team career totals",
        table(
            [
                "Team",
                "GP",
                "W-L-D",
                "GF",
                "GA",
                "Diff",
            ],
            [
                [
                    esc(name),
                    entry["career"]["games_played"],
                    (
                        f"{entry['career']['wins']}-"
                        f"{entry['career']['losses']}-"
                        f"{entry['career']['draws']}"
                    ),
                    entry["career"]["goals_for"],
                    entry["career"]["goals_against"],
                    fmt_signed(
                        entry["career"]["goal_diff"]
                    ),
                ]
                for name, entry in teams.items()
            ],
        ),
    )

    player_rows = []

    for name, entry in players.items():

        career = entry["career"]

        trend = entry.get(
            "trend",
            {},
        ).get(
            selected_window,
            {},
        )

        summary = trend.get(
            "summary",
            {},
        )

        player_rows.append(
            [
                esc(name),
                esc(entry["team"]),
                summary.get(
                    "games",
                    0,
                ),
                summary.get(
                    "goals",
                    0,
                ),
                summary.get(
                    "assists",
                    0,
                ),
                summary.get(
                    "points",
                    0,
                ),
                summary.get(
                    "points_per_game",
                    0,
                ),
                career.get(
                    "points_per_game",
                    0,
                ),
                career.get(
                    "penalty_minutes",
                    0,
                ),
            ]
        )

    body += section(
        "Player form",
        (
            _window_selector(
                selected_window
            )
            +
            table(
                [
                    "Player",
                    "Team",
                    "GP",
                    "G",
                    "A",
                    "P",
                    "Pts/GP",
                    "Career Pts/GP",
                    "PIM",
                ],
                player_rows,
                row_teams=[
                    _team_filter_value(entry)
                    for entry in players.values()
                ],
                max_rows=100,
            )
        ),
    )

    details = []

    for name, entry in players.items():
        details.append(
            render_career_player_details(
                name,
                entry,
                selected_window,
            )
        )

    body += section(
        f"Player analysis — "
        f"{WINDOW_LABELS[selected_window]}",
        "".join(details),
    )

    return page(
        "Career stats",
        body,
    )

