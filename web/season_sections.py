"""
Each function here renders one <section> (or <details>) of the season
page from already-computed analysis data. Splitting these out keeps
routes_season.py to a short list of "compute -> render -> append" calls.
"""

from .layout import esc, fmt_pct, fmt_signed, section, subsection, table


def render_overview(overview):
    if not overview:
        return ""

    cards = ""

    for team, r in overview.items():
        cards += f"""
        <div class="card">
            <div class="label">{esc(team)}</div>
            <div class="value">
                {r["wins"]}-{r["losses"]}-{r["draws"]}
            </div>
            <div class="muted">
                {r["goals_for"]} GF /
                {r["goals_against"]} GA
            </div>
        </div>
        """

    return section(
        "Season overview",
        f"<div class='cards'>{cards}</div>",
    )


def render_standings(teams):
    rows = []

    for name, r in teams.items():
        rows.append([
            esc(name),
            r["games_played"],
            f"{r['wins']}-{r['losses']}-{r['draws']}",
            r["standings_points"],
            r["goals_for"],
            r["goals_against"],
            fmt_signed(r["goal_diff"]),
            f"{r['shots_for']} ({fmt_pct(r.get('shooting_pct'))})",
        ])

    return section(
        "Team standings",
        table(
            ["Team", "GP", "W-L-D", "Pts", "GF", "GA", "Diff", "Shots (Sh%)"],
            rows,
            row_teams=list(teams.keys()),
        ),
    )


def render_player_leaders(players):
    rows = list(players.items())[:50]

    return section(
        "Player leaders",
        table(
            ["Player", "Team", "GP", "G", "A", "P", "Pts/GP", "PIM"],
            [
                [
                    esc(name),
                    esc(r["team"]),
                    r["games_played"],
                    r["goals"],
                    r["assists"],
                    r["points"],
                    r["points_per_game"],
                    r["penalty_minutes"],
                ]
                for name, r in rows
            ],
            row_teams=[r["team"] for _, r in rows],
        ),
    )


def render_consistency(consistency):
    return section(
        "Player consistency",
        (
            "<p class='muted'>"
            "Point-game percentage shows how often a player produced "
            "at least one point. Lower standard deviation means less "
            "game-to-game variation."
            "</p>"
            + table(
                [
                    "Player", "Team", "GP", "Pts/GP", "Point games",
                    "Point-game %", "Pts SD", "Pts CV", "Best Pts",
                    "Longest hot", "Longest cold",
                ],
                [
                    [
                        esc(x["player"]),
                        esc(x["team"]),
                        x["games"],
                        x["points_per_game"],
                        x["point_games"],
                        fmt_pct(x["point_game_pct"]),
                        x["points_std_dev"],
                        x["points_cv"],
                        x["max_points_game"],
                        x["longest_point_streak"],
                        x["longest_scoreless_streak"],
                    ]
                    for x in consistency
                ],
                row_teams=[x["team"] for x in consistency],
            )
        ),
    )


def render_reliability(reliability):
    return section(
        "Player reliability",
        (
            "<p class='muted'>"
            "Reliability combines point-game frequency, scoring production "
            "and game-to-game consistency. It is a comparison aid, not an "
            "official statistic."
            "</p>"
            + table(
                [
                    "Player", "Team", "Reliability", "Point-game %",
                    "Pts/GP", "Variation", "Longest cold",
                ],
                [
                    [
                        esc(x["player"]),
                        esc(x["team"]),
                        x["reliability_score"],
                        fmt_pct(x["point_game_pct"]),
                        x["points_per_game"],
                        x["points_cv"],
                        x["longest_scoreless_streak"],
                    ]
                    for x in reliability
                ],
                row_teams=[x["team"] for x in reliability],
            )
        ),
    )


def render_streaks(streaks):
    rows = streaks[:40]

    return section(
        "Hot / cold streaks",
        table(
            [
                "Player", "Team", "Longest scoring streak", "Hot Pts/GP",
                "2+ point streak", "Longest cold streak", "Current streak",
            ],
            [
                [
                    esc(x["player"]),
                    esc(x["team"]),
                    x["longest_hot_streak"],
                    x["hot_streak_points_per_game"],
                    x["longest_multi_point_streak"],
                    x["longest_cold_streak"],
                    x["current_streak"],
                ]
                for x in rows
            ],
            row_teams=[x["team"] for x in rows],
        ),
    )


def render_variation(variation):
    rows = variation[:40]

    return section(
        "Game-to-game variation",
        (
            "<p class='muted'>"
            "Higher Pts SD / CV means more variation from game to game."
            "</p>"
            + table(
                [
                    "Player", "Team", "GP", "Avg Pts", "Median", "Pts SD",
                    "Pts CV", "G SD", "A SD", "Min", "Max",
                ],
                [
                    [
                        esc(x["player"]),
                        esc(x["team"]),
                        x["games"],
                        x["points_avg"],
                        x["median_points"],
                        x["points_std_dev"],
                        x["points_cv"],
                        x["goals_std_dev"],
                        x["assists_std_dev"],
                        x["min_points"],
                        x["max_points"],
                    ]
                    for x in rows
                ],
                row_teams=[x["team"] for x in rows],
            )
        ),
    )


def render_contribution(contribution):
    rows = contribution[:40]

    return section(
        "Scoring contribution",
        (
            "<p class='muted'>"
            "Point share compares a player's points with total team goals. "
            "Because a goal can have multiple credited points, point share "
            "can exceed 100%."
            "</p>"
            + table(
                [
                    "Player", "Team", "G", "A", "P", "Team goals",
                    "Goal share", "Point share", "Pts / team goal",
                ],
                [
                    [
                        esc(x["player"]),
                        esc(x["team"]),
                        x["goals"],
                        x["assists"],
                        x["points"],
                        x["team_goals"],
                        fmt_pct(x["goal_share_pct"]),
                        fmt_pct(x["point_share_pct"]),
                        x["points_per_team_goal"],
                    ]
                    for x in rows
                ],
                row_teams=[x["team"] for x in rows],
            )
        ),
    )


def render_win_loss(win_loss):
    rows = win_loss[:40]

    return section(
        "Player performance in team wins vs losses",
        table(
            [
                "Player", "Team", "Win Pts/GP", "Loss Pts/GP",
                "Win-Loss PPG", "Win G", "Win A", "Loss G", "Loss A",
            ],
            [
                [
                    esc(x["player"]),
                    esc(x["team"]),
                    x["wins"]["points_per_game"],
                    x["losses"]["points_per_game"],
                    x["win_loss_ppg_delta"],
                    x["wins"]["goals"],
                    x["wins"]["assists"],
                    x["losses"]["goals"],
                    x["losses"]["assists"],
                ]
                for x in rows
            ],
            row_teams=[x["team"] for x in rows],
        ),
    )


def render_with_without(with_without):
    rows = with_without[:50]

    return section(
        "Player impact: team with vs without player",
        (
            "<div class='note'>"
            "<strong>Important:</strong> 'with' means the player appeared "
            "on the match roster. The JSON does not provide shifts or exact "
            "time-on-floor, so this is not an on-court possession metric."
            "</div>"
            + table(
                [
                    "Player", "Team", "With GP", "Without GP", "With W%",
                    "Without W%", "W% difference", "With diff/GP",
                    "Without diff/GP",
                ],
                [
                    [
                        esc(x["player"]),
                        esc(x["team"]),
                        x["with_games"],
                        x["without_games"],
                        fmt_pct(x["with_win_pct"]),
                        fmt_pct(x["without_win_pct"]),
                        (
                            fmt_signed(x["win_pct_difference"])
                            if x["win_pct_difference"] is not None
                            else "N/A"
                        ),
                        x["with_goal_diff_per_game"],
                        x["without_goal_diff_per_game"],
                    ]
                    for x in rows
                ],
                row_teams=[x["team"] for x in rows],
            )
        ),
    )


def render_impact_detail(impact):
    rows = impact[:50]

    return subsection(
        "Detailed player impact",
        table(
            [
                "Player", "Team", "Present", "Absent", "Wins with",
                "Wins without", "W% with", "W% without", "Diff with",
                "Diff without",
            ],
            [
                [
                    esc(x["player"]),
                    esc(x["team"]),
                    x["games_present"],
                    x["games_absent"],
                    x["wins_present"],
                    x["wins_absent"],
                    fmt_pct(x["win_pct_present"]),
                    fmt_pct(x["win_pct_absent"]),
                    x["goal_diff_present"],
                    x["goal_diff_absent"],
                ]
                for x in rows
            ],
            row_teams=[x["team"] for x in rows],
        ),
    )


def render_assist_network(assist_network):
    pairs = assist_network["top_pairs"]

    return section(
        "Assist relationships",
        table(
            ["Assist by", "Goal by", "Times", "Team"],
            [
                [esc(x["assist_by"]), esc(x["goal_by"]), x["times"], esc(x["team"])]
                for x in pairs
            ],
            row_teams=[x["team"] for x in pairs],
        ),
    )


def render_goal_combinations(combinations):
    rows = combinations[:50]

    return section(
        "Goal-scoring combinations",
        (
            "<p class='muted'>"
            "Shows how frequently an assist relationship accounts for "
            "a scorer's goals."
            "</p>"
            + table(
                [
                    "Assist by", "Goal by", "Team", "Assists",
                    "Scorer goals", "Share of scorer goals",
                ],
                [
                    [
                        esc(x["assist_by"]),
                        esc(x["goal_by"]),
                        esc(x["team"]),
                        x["assists"],
                        x["scorer_goals"],
                        fmt_pct(x["scorer_goal_share_pct"]),
                    ]
                    for x in rows
                ],
                row_teams=[x["team"] for x in rows],
            )
        ),
    )


def render_unassisted_goals(assist_network):
    entries = assist_network["unassisted_goals"]

    return subsection(
        "Unassisted goals",
        table(
            ["Player", "Team", "Unassisted goals"],
            [[esc(x["player"]), esc(x["team"]), x["times"]] for x in entries],
            row_teams=[x["team"] for x in entries],
        ),
    )


def render_player_discipline(player_discipline):
    rows = player_discipline[:50]

    return section(
        "Player discipline",
        (
            "<p class='muted'>"
            "Penalty counts are based on event data; penalty minutes are "
            "taken from the parsed roster/event data where available."
            "</p>"
            + table(
                [
                    "Player", "Team", "Games", "Infractions", "PIM",
                    "PIM/GP", "Infractions/GP",
                ],
                [
                    [
                        esc(x["player"]),
                        esc(x["team"]),
                        x["games"],
                        x["infractions"],
                        x["minutes"],
                        x["minutes_per_game"],
                        x["infractions_per_game"],
                    ]
                    for x in rows
                ],
                row_teams=[x["team"] for x in rows],
            )
        ),
    )


def render_penalty_conceded(penalty_conceded):
    return section(
        "Penalties followed by conceded goals",
        (
            "<p class='muted'>"
            "The table uses a 120-second window after a penalty. This is a "
            "contextual association, not proof that the penalty caused the goal."
            "</p>"
            + table(
                [
                    "Date", "Team", "Player", "Penalty time",
                    "Conceded at", "Seconds later",
                ],
                [
                    [
                        esc(x["date"]),
                        esc(x["team"]),
                        esc(x["player"]),
                        esc(x["penalty_time"]),
                        esc(x["conceded_goal_time"]),
                        x["seconds_after_penalty"],
                    ]
                    for x in penalty_conceded
                ],
                row_teams=[x["team"] for x in penalty_conceded],
            )
        ),
    )


def render_opponent_record(opponents):
    return section(
        "Record by opponent",
        table(
            ["Opponent", "GP", "W-L-D", "GF", "GA", "Diff", "Win %"],
            [
                [
                    esc(opp),
                    r["games_played"],
                    f"{r['wins']}-{r['losses']}-{r['draws']}",
                    r["goals_for"],
                    r["goals_against"],
                    fmt_signed(r["goal_diff"]),
                    fmt_pct(r.get("win_pct")),
                ]
                for opp, r in opponents.items()
            ],
        ),
    )


def render_opponent_players(opponent_players):
    rows = opponent_players[:100]

    return section(
        "Player performance by opponent",
        table(
            ["Player", "Opponent", "GP", "G", "A", "P", "Pts/GP", "Record"],
            [
                [
                    esc(x["player"]),
                    esc(x["opponent"]),
                    x["games"],
                    x["goals"],
                    x["assists"],
                    x["points"],
                    x["points_per_game"],
                    f"{x['wins']}-{x['losses']}-{x['draws']}",
                ]
                for x in rows
            ],
            row_teams=[x["team"] for x in rows],
        ),
    )


def render_first_last(first_last):
    rows = []

    for team, x in first_last.items():
        rows.append([
            esc(team),
            x["games"],
            x["first_goal_games"],
            fmt_pct(x["first_goal_win_pct"]),
            x["first_goal_wins"],
            x["last_goal_games"],
            fmt_pct(x["last_goal_win_pct"]),
            x["last_goal_wins_when_for"],
            x["last_goal_losses_when_for"],
        ])

    return section(
        "First / last scoring impact",
        (
            "<p class='muted'>"
            "Shows how often scoring first or scoring the final goal "
            "corresponded with winning."
            "</p>"
            + table(
                [
                    "Team", "GP", "Scored first", "Win % after first",
                    "Wins after first", "Scored last", "Win % after last",
                    "Wins after last", "Losses after last",
                ],
                rows,
            )
        ),
    )


def render_close_games(close_games):
    rows = []

    for team, x in close_games.items():
        rows.append([
            esc(team),
            x["games"],
            f"{x['wins']}-{x['losses']}-{x['draws']}",
            fmt_pct(x["win_pct"]),
            x["goals_for"],
            x["goals_against"],
            fmt_signed(x["goal_diff"]),
            x["goal_diff_per_game"],
        ])

    return section(
        "Close-game performance",
        (
            "<p class='muted'>"
            "Close games are matches decided by two goals or fewer."
            "</p>"
            + table(
                ["Team", "Close GP", "W-L-D", "Win %", "GF", "GA", "Diff", "Diff/GP"],
                rows,
            )
        ),
    )


def render_scoring_runs(scoring_runs):
    rows = [
        [
            esc(x["date"]),
            esc(x["team"]),
            esc(x["opponent"]),
            x["count"],
            esc(x["start_time"]),
            esc(x["end_time"]),
        ]
        for x in scoring_runs[:50]
    ]

    return section(
        "Longest scoring runs",
        (
            "<p class='muted'>"
            "A scoring run is a sequence of consecutive goals by the same "
            "team without an opponent goal between them."
            "</p>"
            + table(
                ["Date", "Team", "Opponent", "Unanswered goals", "From", "To"],
                rows,
            )
        ),
    )


def render_scoring_run_summary(run_summary):
    rows = []

    for team, x in run_summary.items():
        rows.append([
            esc(team),
            x["games_with_runs"],
            x["runs_2_plus"],
            x["runs_3_plus"],
            x["runs_4_plus"],
            x["longest_run"],
            x["average_run"],
        ])

    return subsection(
        "Season scoring-run summary",
        table(
            [
                "Team", "Games with runs", "2+ goal runs", "3+ goal runs",
                "4+ goal runs", "Longest", "Average run",
            ],
            rows,
        ),
    )


def render_team_trends(trends):
    rows = []

    for team, x in trends.items():
        first = x["first_half"]
        second = x["second_half"]

        rows.append([
            esc(team),
            f"{first['wins']}-{first['losses']}-{first['draws']}",
            f"{second['wins']}-{second['losses']}-{second['draws']}",
            fmt_pct(first["win_pct"]),
            fmt_pct(second["win_pct"]),
            fmt_signed(x["win_pct_change"]),
            first["goals_for_per_game"],
            second["goals_for_per_game"],
            x["gf_per_game_change"],
            first["goals_against_per_game"],
            second["goals_against_per_game"],
            x["ga_per_game_change"],
        ])

    return section(
        "Season trends",
        (
            "<p class='muted'>"
            "The season is split chronologically into two halves. "
            "Changes show whether results and scoring improved or declined."
            "</p>"
            + table(
                [
                    "Team", "First W-L-D", "Second W-L-D", "First W%",
                    "Second W%", "W% change", "First GF/GP", "Second GF/GP",
                    "GF/GP change", "First GA/GP", "Second GA/GP",
                    "GA/GP change",
                ],
                rows,
            )
        ),
    )


def render_recent_form(recent_form):
    rows = []

    for team, x in recent_form.items():
        rows.append([
            esc(team),
            x["games"],
            f"{x['wins']}-{x['losses']}-{x['draws']}",
            fmt_pct(x["win_pct"]),
            x["goals_for"],
            x["goals_against"],
            fmt_signed(x["goal_diff"]),
            x["goals_for_per_game"],
            x["goals_against_per_game"],
            " ".join(x["results"]),
        ])

    return section(
        "Recent form",
        table(
            [
                "Team", "Games", "W-L-D", "Win %", "GF", "GA", "Diff",
                "GF/GP", "GA/GP", "Results",
            ],
            rows,
        ),
    )


def render_games_list(games, season):
    rows = []

    for g in games:
        m = g["match"]
        fname = g["_source_file"]

        rows.append(
            "<li>"
            f"<a href='/game/{esc(season)}/{esc(fname)}'>"
            f"{esc(m['date'])}: "
            f"{esc(m['home_team'])} "
            f"{esc(m['home_score'])} - "
            f"{esc(m['away_score'])} "
            f"{esc(m['away_team'])}"
            "</a>"
            "</li>"
        )

    return section(
        "Games",
        "<ul class='games-list'>" + "".join(rows) + "</ul>",
    )


def render_data_limitations():
    return section(
        "Data limitations",
        """
        <div class="note">
            <strong>Per-player shots:</strong>
            the source provides team-level shot counts, not individual-player
            shots, so player shooting percentage is not calculated.
        </div>

        <div class="note">
            <strong>Player impact:</strong>
            with/without-player analysis is based on roster presence because
            the parsed JSON does not provide player shifts or exact
            time-on-floor.
        </div>

        <div class="note">
            <strong>Penalty → goal:</strong>
            penalties followed by conceded goals are contextual associations
            within a time window, not causal proof.
        </div>

        <div class="note">
            <strong>No video analysis:</strong>
            this season page currently uses only the parsed match JSON.
        </div>
        """,
    )
