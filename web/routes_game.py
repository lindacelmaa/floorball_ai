"""
/game-stats  - menu listing every game, grouped by season
/game/<season>/<filename>  - full single-game analysis page

This page is intentionally kept as-is (unchanged behavior) - it is not
part of the season-analysis expansion.
"""

import json
import os

from flask import Blueprint, abort, current_app

from analysis.game_stats import game_stats
from analysis.season_stats import load_games

from .layout import esc, page, table


game_bp = Blueprint("game", __name__)


@game_bp.route("/game-stats")
def game_stats_menu():
    """Top-level Game Stats section: browse every game and jump to its page."""
    games_dir = current_app.config["GAMES_DIR"]

    if not os.path.isdir(games_dir):
        return page(
            "Game Stats",
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

    body = ""

    for season in seasons:
        games = load_games(
            os.path.join(games_dir, season)
        )

        body += (
            f"<section>"
            f"<h2>{esc(season)}</h2>"
            f"<ul class='games-list'>"
        )

        for g in games:
            m = g["match"]
            fname = g["_source_file"]

            notation = next(
                (
                    n for n in (
                    m.get("score_notation", {}).get("home"),
                    m.get("score_notation", {}).get("away"),
                )
                    if n in ("ET", "PS")
                ),
                None,
            )

            score_suffix = f" {notation}" if notation else ""

            body += (
                f"<li>"
                f"<a href='/game/{esc(season)}/{esc(fname)}'>"
                f"{esc(m['date'])}: "
                f"{esc(m['home_team'])} "
                f"{esc(m['home_score'])} - "
                f"{esc(m['away_score'])}"
                f"{esc(score_suffix)} "
                f"{esc(m['away_team'])}"
                f"</a>"
                f"</li>"
            )

    body += "</ul></section>"

    if not seasons:
        body = (
            "<p class='muted'>"
            "No games found yet."
            "</p>"
        )

    return page("Game Stats", body)


@game_bp.route("/game/<season>/<filename>")
def game_page(season, filename):
    games_dir = current_app.config["GAMES_DIR"]

    path = os.path.join(
        games_dir,
        season,
        filename,
    )

    if not os.path.isfile(path):
        abort(404)

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    stats = game_stats(data)

    body = (
        f"<p class='score'>"
        f"{esc(stats['final_score'])}"
        f"</p>"
    )

    body += (
        f"<p class='muted'>"
        f"Referees: "
        f"{esc(', '.join(stats['referees']) if stats['referees'] else 'N/A')} "
        f"&middot; Attendance: "
        f"{esc(stats['attendance'])}"
        f"</p>"
    )

    body += "<section><h3>Top scorers</h3>"

    body += table(
        [
            "Player",
            "Team",
            "Pts",
            "G",
            "A",
        ],
        [
            [
                esc(p["name"]),
                esc(p["team"]),
                p["points"],
                p["goals"],
                p["assists"],
            ]
            for p in stats["top_scorers"]
        ],
    )

    body += "</section>"

    body += "<section><h3>Penalties</h3>"

    body += table(
        [
            "Player",
            "Team",
            "Minutes",
        ],
        [
            [
                esc(p["name"]),
                esc(p["team"]),
                p["penalty_minutes"],
            ]
            for p in stats["penalties"]
        ],
    )

    body += "</section>"

    body += "<section><h3>Shooting</h3>"

    for team, s in stats["shooting"].items():
        body += (
            f"<p>"
            f"<strong>{esc(team)}</strong>: "
            f"{s['goals']}/{s['shots']} "
            f"({esc(s['shooting_pct'])}%)"
            f"</p>"
        )

        body += table(
            [
                "Period",
                "Goals",
                "Shots",
                "Sh%",
            ],
            [
                [
                    esc(label),
                    p["goals"],
                    p["shots"],
                    p["shooting_pct"],
                ]
                for label, p in s["by_period"].items()
            ],
        )

    body += "</section>"

    gt = stats["goal_timing"]

    body += "<section><h3>Goal timing</h3>"

    if gt["first_goal"]:
        body += (
            f"<p>"
            f"First goal: "
            f"{esc(gt['first_goal']['time'])} - "
            f"{esc(gt['first_goal']['detail'])}"
            f"</p>"
        )

        body += (
            f"<p>"
            f"Last goal: "
            f"{esc(gt['last_goal']['time'])} - "
            f"{esc(gt['last_goal']['detail'])}"
            f"</p>"
        )

    run = stats["scoring_runs"]["longest_run"]

    if run and run["side"]:
        body += (
            f"<p>"
            f"Longest scoring run: "
            f"{run['count']} unanswered goals by "
            f"{esc(run['team'])} "
            f"({esc(run['start_time'])} - "
            f"{esc(run['end_time'])})"
            f"</p>"
        )

    body += "</section>"

    gb = stats["goals_by_time_bucket"]

    body += (
        f"<section>"
        f"<h3>"
        f"Goals by {esc(gb['bucket_minutes'])}-min bucket"
        f"</h3>"
    )

    body += table(
        [
            "Bucket",
            gb["home_team"],
            gb["away_team"],
        ],
        [
            [
                esc(label),
                c["home"],
                c["away"],
            ]
            for label, c in gb["buckets"].items()
        ],
    )

    body += "</section>"

    body += (
        "<section>"
        "<h3>Special teams (approximate)</h3>"
    )

    rows = []

    for team, s in stats["special_teams"].items():
        if team == "note":
            continue

        rows.append([
            esc(team),
            s["penalties_taken"],
            s["total_penalty_minutes"],
            (
                f"{s['power_play_goals']}/"
                f"{s['power_play_opportunities']}"
            ),
            (
                f"{s['power_play_pct']}%"
                if s["power_play_pct"] is not None
                else "N/A"
            ),
            (
                f"{s['penalty_kill_pct']}%"
                if s["penalty_kill_pct"] is not None
                else "N/A"
            ),
        ])

    body += table(
        [
            "Team",
            "Penalties",
            "PIM",
            "PP goals/opp",
            "PP%",
            "PK%",
        ],
        rows,
    )

    body += (
        f"<p class='muted'>"
        f"{esc(stats['special_teams'].get('note', ''))}"
        f"</p>"
    )

    body += "</section>"

    an = stats["assist_network"]

    body += (
        "<section>"
        "<h3>Assist -> goal pairs</h3>"
    )

    body += table(
        [
            "Assist by",
            "Goal by",
            "Times",
        ],
        [
            [
                esc(p["assist_by"]),
                esc(p["goal_by"]),
                p["times"],
            ]
            for p in an["top_assist_scorer_pairs"]
        ],
    )

    body += "</section>"

    body += "<section><h3>Goalies</h3>"

    body += table(
        [
            "Goalie",
            "Saves",
            "Shots faced",
            "Save%",
            "Minutes",
            "GA",
        ],
        [
            [
                esc(g["name"]),
                g["saves"],
                g["shots_faced"],
                f"{g['save_pct']}%",
                g["minutes_played"],
                g["goals_against"],
            ]
            for g in stats["goalie_workload"]
        ],
    )

    body += "</section>"

    tis = stats["time_in_each_state"]

    body += (
        "<section>"
        "<h3>Time leading / trailing / tied</h3>"
    )

    rows = [
        [
            esc(team),
            s["leading_time"],
        ]
        for team, s in tis.items()
        if team not in (
            "tied_seconds",
            "tied_time",
            "total_seconds",
        )
    ]

    rows.append([
        "Tied",
        tis["tied_time"],
    ])

    body += table(
        [
            "Team / state",
            "Time",
        ],
        rows,
    )

    body += "</section>"

    ld = stats["longest_droughts"]

    body += (
        "<section>"
        "<h3>Longest scoreless stretch per team</h3>"
    )

    body += table(
        [
            "Team",
            "Duration",
            "From",
            "To",
        ],
        [
            [
                esc(team),
                esc(d["longest_drought"]),
                esc(d["from_time"]),
                esc(d["to_time"]),
            ]
            for team, d in ld.items()
        ],
    )

    body += "</section>"

    pc = stats["penalties_with_score_context"]

    body += (
        "<section>"
        "<h3>Penalties in context</h3>"
    )

    body += table(
        [
            "Time",
            "Player",
            "Team",
            "Score situation",
        ],
        [
            [
                esc(p["time"]),
                esc(p["player"]),
                esc(p["team"]),
                esc(p["score_situation"]),
            ]
            for p in pc
        ],
    )

    body += "</section>"

    rp = stats["retaliation_penalties"]

    body += (
        "<section>"
        "<h3>"
        "Possible retaliation penalties "
        "(within 60s of conceding)"
        "</h3>"
    )

    body += table(
        [
            "Time",
            "Player",
            "Team",
            "Seconds after conceding",
            "Conceded at",
        ],
        [
            [
                esc(r["penalty_time"]),
                esc(r["player"]),
                esc(r["team"]),
                r["seconds_after_conceding"],
                esc(r["conceded_goal_time"]),
            ]
            for r in rp
        ],
    )

    body += "</section>"

    op = stats["overlapping_penalties"]

    body += (
        "<section>"
        "<h3>"
        "Overlapping penalties "
        "(possible multi-man advantage)"
        "</h3>"
    )

    body += table(
        [
            "Team shorthanded",
            "Players",
            "From",
            "To",
        ],
        [
            [
                esc(o["team_shorthanded"]),
                esc(", ".join(o["players"])),
                esc(o["overlap_start"]),
                esc(o["overlap_end"]),
            ]
            for o in op
        ],
    )

    body += (
        "<p class='muted'>"
        "Heuristic based on assessed penalty duration; long "
        "misconduct-type penalties may not create a real numerical "
        "disadvantage for their full length."
        "</p>"
    )

    body += "</section>"

    ro = stats["repeat_offenders"]

    body += (
        "<section>"
        "<h3>Repeat offenders (2+ penalties this game)</h3>"
    )

    body += table(
        [
            "Player",
            "Team",
            "Infractions",
            "Total minutes",
        ],
        [
            [
                esc(r["player"]),
                esc(r["team"]),
                r["infractions"],
                r["total_minutes"],
            ]
            for r in ro
        ],
    )

    body += "</section>"

    qp = stats["quiet_players"]

    body += (
        "<section>"
        "<h3>Players with no points this game</h3>"
    )

    body += table(
        [
            "Player",
            "Number",
            "Team",
        ],
        [
            [
                esc(p["name"]),
                esc(p["number"]),
                esc(p["team"]),
            ]
            for p in qp
        ],
    )

    body += "</section>"

    return page(
        stats["final_score"],
        body,
    )
