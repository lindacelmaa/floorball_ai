
"""
Career / Multi-Season Statistics
================================

Career and recent-form statistics for floorball game JSON.

Supported source JSON structure:

{
    "match": {
        "status": "...",
        "home_team": "...",
        "home_score": 12,
        "away_team": "...",
        "away_score": 5,
        "league": "...",
        "round": "...",
        "date": "...",
        "time": "...",
        "venue": "..."
    },
    "events": [...],
    "rosters": {
        "Team A": [
            {
                "number": 25,
                "name": "Player",
                "points": 3,
                "goals": 2,
                "assists": 1,
                "penalty_minutes": "2 min"
            }
        ],
        "Team B": [...]
    },
    "goals_shots_by_period": [...],
    "referees": [...],
    "attendance": 261
}

The roster is treated as the authoritative player box score.

The events are additionally parsed so that:
    - goal scorers / assists can be recovered
    - penalty minutes can be recovered
    - goalkeeper events are not treated as skater statistics
    - game metadata can be preserved

Public player structure:

    entry["games"]
    entry["windows"]
    entry["trend"]
    entry["forecast"]
    entry["coach_metrics"]

Supported windows:

    all_season
    last_5
    last_10
    last_season_current
"""

import argparse
import json
import math
import os
import re
from collections import defaultdict



try:
    from analysis.season_stats import load_games
except ImportError:
    try:
        from season_stats import load_games
    except ImportError:
        load_games = None


# ---------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------

def _first_value(data, keys, default=None):
    if not isinstance(data, dict):
        return default

    for key in keys:
        if key in data and data[key] is not None:
            return data[key]

    return default


def _number(value, default=0.0):
    if value is None:
        return default

    if isinstance(value, bool):
        return float(value)

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int_number(value, default=0):
    if value is None:
        return default

    if isinstance(value, bool):
        return int(value)

    if isinstance(value, (int, float)):
        return int(round(value))

    # Handles strings such as:
    #   "2"
    #   "2 min"
    #   "14 min"
    match = re.search(r"-?\d+(?:\.\d+)?", str(value))

    if not match:
        return default

    try:
        return int(round(float(match.group(0))))
    except (TypeError, ValueError):
        return default


def _safe_round(value, digits=2):
    return round(float(value), digits)


def _mean(values):
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def _median(values):
    values = sorted(values)

    if not values:
        return 0.0

    middle = len(values) // 2

    if len(values) % 2:
        return values[middle]

    return (values[middle - 1] + values[middle]) / 2


def _stddev(values):
    values = list(values)

    if len(values) < 2:
        return 0.0

    mean = _mean(values)

    return math.sqrt(
        sum((x - mean) ** 2 for x in values)
        / len(values)
    )


def player_key(name):
    """
    Normalize player names for dictionary keys.

    Keeps Latvian characters intact while removing accidental
    whitespace differences.
    """

    if not name:
        return ""

    return " ".join(str(name).strip().split())


# ---------------------------------------------------------------------
# Season / game loading
# ---------------------------------------------------------------------

def _load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return data if isinstance(data, dict) else None

    except (OSError, json.JSONDecodeError):
        return None


def _looks_like_game(data):
    if not isinstance(data, dict):
        return False

    return (
        isinstance(data.get("match"), dict)
        or isinstance(data.get("rosters"), dict)
        or isinstance(data.get("events"), list)
    )


def _load_games_direct(season_path):
    """
    Direct loader for the actual game JSON structure.

    This is preferred over the old season_stats.py loader because
    career_stats.py needs access to the complete raw game dictionary.
    """

    games = []

    if not os.path.isdir(season_path):
        return games

    for filename in sorted(os.listdir(season_path)):

        if not filename.lower().endswith(".json"):
            continue

        # Do not accidentally load generated career files.
        if filename in {
            "career_player_stats.json",
            "career_team_stats.json",
        }:
            continue

        path = os.path.join(season_path, filename)

        if not os.path.isfile(path):
            continue

        data = _load_json_file(path)

        if data and _looks_like_game(data):
            games.append(data)

    return games


def discover_seasons(root_dir):
    """
    Discover season folders.

    Expected:

        root/
            2024-2025/
                game1.json
                game2.json
            2025-2026/
                game1.json
                game2.json
    """

    seasons = {}

    if not os.path.isdir(root_dir):
        return seasons

    for entry in sorted(os.listdir(root_dir)):

        season_path = os.path.join(root_dir, entry)

        if not os.path.isdir(season_path):
            continue

        games = _load_games_direct(season_path)

        if games:
            seasons[entry] = games

    return seasons


# ---------------------------------------------------------------------
# Match metadata
# ---------------------------------------------------------------------

def _match(game):
    value = game.get("match", {})

    return value if isinstance(value, dict) else {}


def _date_from_game(game):
    return _first_value(
        _match(game),
        [
            "date",
            "game_date",
            "match_date",
            "datetime",
            "timestamp",
        ],
        "",
    )


def _time_from_game(game):
    return _first_value(
        _match(game),
        [
            "time",
            "game_time",
        ],
        "",
    )


def _sort_games(games):
    """
    Sort chronologically.

    ISO dates sort naturally.

    Latvian dates such as:

        27. septembris, 2025

    are converted into a sortable tuple where possible.
    """

    month_map = {
        "janvāris": 1,
        "februāris": 2,
        "marts": 3,
        "aprīlis": 4,
        "maijs": 5,
        "jūnijs": 6,
        "jūlijs": 7,
        "augusts": 8,
        "septembris": 9,
        "oktobris": 10,
        "novembris": 11,
        "decembris": 12,
    }

    def sort_key(game):
        date = str(_date_from_game(game) or "").strip()
        time = str(_time_from_game(game) or "").strip()

        match = re.search(
            r"(\d{1,2})\.\s*([A-Za-zāčēģīķļņōŗšūž]+),?\s*(\d{4})",
            date.lower(),
        )

        if match:
            day = int(match.group(1))
            month = month_map.get(match.group(2), 0)
            year = int(match.group(3))

            return (
                year,
                month,
                day,
                time,
            )

        # ISO / numeric dates work well as strings.
        return (
            0,
            0,
            0,
            date,
            time,
        )

    return sorted(games, key=sort_key)


# ---------------------------------------------------------------------
# Event parsing
# ---------------------------------------------------------------------

_GOAL_EVENT_TYPES = {
    "Vārti",
    "Vārti (vairākumā)",
    "Vārti (mazākumā)",
}


def _events(game):
    value = game.get("events", [])

    return value if isinstance(value, list) else []


def _parse_event_player_numbers(detail):
    """
    Parse player numbers from event details.

    Examples:

        "#25 Salvis Sīkmanis (#10 Linards Vimbsons)"

    becomes:

        [25, 10]

    The first player is the scorer.
    The second player is the assist.
    """

    if not detail:
        return []

    return [
        int(number)
        for number in re.findall(
            r"#(\d+)",
            str(detail),
        )
    ]


def _parse_event_penalty_minutes(detail):
    if not detail:
        return 0

    # "12 min"
    # "2 min; ..."
    return _int_number(
        re.search(
            r"(\d+)\s*min",
            str(detail),
            flags=re.IGNORECASE,
        ).group(1)
        if re.search(
            r"(\d+)\s*min",
            str(detail),
            flags=re.IGNORECASE,
        )
        else 0
    )


def _event_stats_by_number(game):
    """
    Extract event-derived statistics indexed by jersey number.

    Returns:

        {
            number: {
                "goals": ...,
                "assists": ...,
                "penalty_minutes": ...
            }
        }

    This is supplementary to the roster data.
    """

    stats = defaultdict(
        lambda: {
            "goals": 0,
            "assists": 0,
            "penalty_minutes": 0,
        }
    )

    for event in _events(game):

        if not isinstance(event, dict):
            continue

        event_type = str(
            event.get("type") or ""
        ).strip()

        detail = event.get("detail", "")

        numbers = _parse_event_player_numbers(detail)

        # -------------------------------------------------------------
        # Goals
        # -------------------------------------------------------------

        if event_type in _GOAL_EVENT_TYPES:

            if numbers:
                scorer = numbers[0]
                stats[scorer]["goals"] += 1

            if len(numbers) >= 2:
                assister = numbers[1]
                stats[assister]["assists"] += 1

        # -------------------------------------------------------------
        # Penalties
        # -------------------------------------------------------------

        if event_type == "Sods":

            if numbers:
                penalized_player = numbers[0]

                minutes = _parse_event_penalty_minutes(
                    detail
                )

                stats[penalized_player][
                    "penalty_minutes"
                ] += minutes

    return dict(stats)


# ---------------------------------------------------------------------
# Roster parsing
# ---------------------------------------------------------------------

def _rosters(game):
    value = game.get("rosters", {})

    return value if isinstance(value, dict) else {}


def _is_player_record(record):
    return (
        isinstance(record, dict)
        and record.get("name")
        and record.get("staff") is None
    )


def _roster_player_records(game):
    """
    Return:

        [
            {
                "team": ...,
                "number": ...,
                "name": ...,
                ...
            }
        ]
    """

    result = []

    for team_name, roster in _rosters(game).items():

        if not isinstance(roster, list):
            continue

        for record in roster:

            if not _is_player_record(record):
                continue

            result.append(
                {
                    "team": team_name,
                    "number": _int_number(
                        record.get("number"),
                        None,
                    ),
                    "name": record.get("name"),
                    "points": _int_number(
                        record.get("points")
                    ),
                    "goals": _int_number(
                        record.get("goals")
                    ),
                    "assists": _int_number(
                        record.get("assists")
                    ),
                    "penalty_minutes": _int_number(
                        record.get("penalty_minutes")
                    ),
                }
            )

    return result


def _team_score(game, team):
    match = _match(game)

    home_team = match.get("home_team")
    away_team = match.get("away_team")

    if team == home_team:
        return (
            _int_number(match.get("home_score")),
            _int_number(match.get("away_score")),
        )

    if team == away_team:
        return (
            _int_number(match.get("away_score")),
            _int_number(match.get("home_score")),
        )

    return 0, 0


def _opponent(game, team):
    match = _match(game)

    home_team = match.get("home_team")
    away_team = match.get("away_team")

    if team == home_team:
        return away_team

    if team == away_team:
        return home_team

    return None


def _game_result(game, team):
    team_score, opponent_score = _team_score(
        game,
        team,
    )

    if team_score > opponent_score:
        return "W"

    if team_score < opponent_score:
        return "L"

    return "D"


# ---------------------------------------------------------------------
# Player game extraction
# ---------------------------------------------------------------------

def _extract_player_games(seasons):
    """
    Build complete game-by-game player records.

    IMPORTANT:
    The roster is authoritative for player totals.

    Example output:

        {
            "Salvis Sīkmanis": [
                {
                    "date": "27. septembris, 2025",
                    "season": "2025-2026",
                    "team": "KNSS/Linde Grupa",
                    "opponent": "FK Saulkalne/Salaspils",
                    "home_team": "KNSS/Linde Grupa",
                    "away_team": "FK Saulkalne/Salaspils",
                    "home_score": 12,
                    "away_score": 5,
                    "result": "W",
                    "goals": 2,
                    "assists": 1,
                    "points": 3,
                    "penalty_minutes": 0
                }
            ]
        }
    """

    result = defaultdict(list)

    for season_name, season_games in seasons.items():

        for game in season_games:

            match = _match(game)

            event_stats = _event_stats_by_number(game)

            home_team = match.get("home_team")
            away_team = match.get("away_team")

            home_score = _int_number(
                match.get("home_score")
            )

            away_score = _int_number(
                match.get("away_score")
            )

            date = _date_from_game(game)

            league = match.get("league")
            round_name = match.get("round")
            venue = match.get("venue")

            for player in _roster_player_records(game):

                name = player["name"]

                if not name:
                    continue

                number = player["number"]

                event_record = (
                    event_stats.get(number)
                    if number is not None
                    else None
                )

                # -----------------------------------------------------
                # Roster values are authoritative.
                #
                # Events are only used as a fallback when a roster
                # statistic is absent.
                # -----------------------------------------------------

                goals = player["goals"]
                assists = player["assists"]
                points = player["points"]
                pim = player["penalty_minutes"]

                if (
                    player.get("goals") is None
                    and event_record
                ):
                    goals = event_record["goals"]

                if (
                    player.get("assists") is None
                    and event_record
                ):
                    assists = event_record["assists"]

                if (
                    player.get("penalty_minutes") is None
                    and event_record
                ):
                    pim = event_record["penalty_minutes"]

                goals = _int_number(goals)
                assists = _int_number(assists)
                pim = _int_number(pim)

                # In floorball points = goals + assists.
                #
                # If the JSON provides an explicit points value,
                # use it. Otherwise calculate it.
                if player.get("points") is None:
                    points = goals + assists

                points = _int_number(points)

                team = player["team"]

                result[player_key(name)].append(
                    {
                        "date": date,
                        "time": _time_from_game(game),
                        "season": season_name,

                        "name": name,
                        "number": number,
                        "team": team,
                        "opponent": _opponent(
                            game,
                            team,
                        ),

                        "home_team": home_team,
                        "away_team": away_team,
                        "home_score": home_score,
                        "away_score": away_score,

                        "team_score": _team_score(
                            game,
                            team,
                        )[0],

                        "opponent_score": _team_score(
                            game,
                            team,
                        )[1],

                        "result": _game_result(
                            game,
                            team,
                        ),

                        "goals": goals,
                        "assists": assists,
                        "points": points,
                        "penalty_minutes": pim,

                        "league": league,
                        "round": round_name,
                        "venue": venue,

                        "attendance": _int_number(
                            game.get("attendance")
                        ),
                    }
                )

    for name in result:
        result[name] = _sort_player_games(
            result[name]
        )

    return dict(result)


def _sort_player_games(games):
    """
    Sort already-normalized player records chronologically.
    """

    month_map = {
        "janvāris": 1,
        "februāris": 2,
        "marts": 3,
        "aprīlis": 4,
        "maijs": 5,
        "jūnijs": 6,
        "jūlijs": 7,
        "augusts": 8,
        "septembris": 9,
        "oktobris": 10,
        "novembris": 11,
        "decembris": 12,
    }

    def key(record):
        date = str(record.get("date") or "")

        match = re.search(
            r"(\d{1,2})\.\s*([A-Za-zāčēģīķļņōŗšūž]+),?\s*(\d{4})",
            date.lower(),
        )

        if match:
            return (
                int(match.group(3)),
                month_map.get(match.group(2), 0),
                int(match.group(1)),
                str(record.get("time") or ""),
            )

        return (
            0,
            0,
            0,
            date,
            str(record.get("time") or ""),
        )

    return sorted(games, key=key)


# ---------------------------------------------------------------------
# Player windows
# ---------------------------------------------------------------------

def _window_games(games, seasons, window):
    games = _sort_player_games(games)

    if window == "last_5":
        return games[-5:]

    if window == "last_10":
        return games[-10:]

    if window == "last_season_current":

        season_names = list(seasons.keys())

        if not season_names:
            return games

        current = season_names[-1]

        previous = (
            season_names[-2]
            if len(season_names) >= 2
            else None
        )

        allowed = {current}

        if previous:
            allowed.add(previous)

        return [
            game
            for game in games
            if game.get("season") in allowed
        ]

    return games


def build_player_windows(games, seasons):
    return {
        "all_season": _window_games(
            games,
            seasons,
            "all_season",
        ),
        "last_5": _window_games(
            games,
            seasons,
            "last_5",
        ),
        "last_10": _window_games(
            games,
            seasons,
            "last_10",
        ),
        "last_season_current": _window_games(
            games,
            seasons,
            "last_season_current",
        ),
    }


# ---------------------------------------------------------------------
# Form calculations
# ---------------------------------------------------------------------

def _summarize_games(games):
    games = list(games)

    gp = len(games)

    goals = sum(
        _int_number(g.get("goals"))
        for g in games
    )

    assists = sum(
        _int_number(g.get("assists"))
        for g in games
    )

    points = sum(
        _int_number(g.get("points"))
        for g in games
    )

    pim = sum(
        _int_number(g.get("penalty_minutes"))
        for g in games
    )

    point_values = [
        _int_number(g.get("points"))
        for g in games
    ]

    wins = sum(
        1
        for g in games
        if g.get("result") == "W"
    )

    losses = sum(
        1
        for g in games
        if g.get("result") == "L"
    )

    draws = sum(
        1
        for g in games
        if g.get("result") == "D"
    )

    return {
        "games": gp,

        "wins": wins,
        "losses": losses,
        "draws": draws,

        "goals": goals,
        "assists": assists,
        "points": points,
        "penalty_minutes": pim,

        "goals_per_game": _safe_round(
            goals / gp if gp else 0
        ),

        "assists_per_game": _safe_round(
            assists / gp if gp else 0
        ),

        "points_per_game": _safe_round(
            points / gp if gp else 0
        ),

        "penalty_minutes_per_game": _safe_round(
            pim / gp if gp else 0
        ),

        "median_points": _safe_round(
            _median(point_values)
        ),

        "stddev_points": _safe_round(
            _stddev(point_values)
        ),

        "zero_point_games": sum(
            1
            for value in point_values
            if value == 0
        ),

        "one_point_games": sum(
            1
            for value in point_values
            if value == 1
        ),

        "multi_point_games": sum(
            1
            for value in point_values
            if value >= 2
        ),

        "three_plus_point_games": sum(
            1
            for value in point_values
            if value >= 3
        ),
    }


def _rolling_average(values, window=5):
    result = []

    for i in range(len(values)):
        start = max(
            0,
            i - window + 1,
        )

        chunk = values[start:i + 1]

        result.append(
            _safe_round(
                _mean(chunk)
            )
        )

    return result


def _linear_slope(values):
    if len(values) < 2:
        return 0.0

    x = list(range(len(values)))

    x_mean = _mean(x)
    y_mean = _mean(values)

    numerator = sum(
        (xi - x_mean) * (yi - y_mean)
        for xi, yi in zip(x, values)
    )

    denominator = sum(
        (xi - x_mean) ** 2
        for xi in x
    )

    if denominator == 0:
        return 0.0

    return numerator / denominator


def _weighted_recent_average(values):
    if not values:
        return 0.0

    weights = list(
        range(1, len(values) + 1)
    )

    numerator = sum(
        value * weight
        for value, weight in zip(
            values,
            weights,
        )
    )

    denominator = sum(weights)

    return numerator / denominator


def build_form_analysis(games):
    games = _sort_player_games(games)

    if not games:
        return {
            "games": [],
            "summary": _summarize_games([]),
            "rolling_3": [],
            "rolling_5": [],
            "slope": 0,
            "direction": "insufficient data",
            "recent_average": 0,
            "recent_momentum": 0,
            "goal_series": [],
            "assist_series": [],
            "point_series": [],
        }

    points = [
        _int_number(g.get("points"))
        for g in games
    ]

    goals = [
        _int_number(g.get("goals"))
        for g in games
    ]

    assists = [
        _int_number(g.get("assists"))
        for g in games
    ]

    rolling_3 = _rolling_average(
        points,
        3,
    )

    rolling_5 = _rolling_average(
        points,
        5,
    )

    slope = _linear_slope(points)

    if slope > 0.08:
        direction = "strongly improving"
    elif slope > 0.02:
        direction = "improving"
    elif slope < -0.08:
        direction = "strongly declining"
    elif slope < -0.02:
        direction = "declining"
    else:
        direction = "stable"

    recent_count = min(
        3,
        len(points),
    )

    recent = points[-recent_count:]

    previous = (
        points[
            -recent_count * 2:
            -recent_count
        ]
        if len(points) >= recent_count * 2
        else []
    )

    recent_average = _mean(recent)

    previous_average = _mean(
        previous
    )

    momentum = (
        recent_average - previous_average
        if previous
        else 0
    )

    chart = []

    for index, game in enumerate(games):

        chart.append(
            {
                "game": index + 1,
                "date": game.get("date"),
                "season": game.get("season"),
                "team": game.get("team"),
                "opponent": game.get("opponent"),
                "result": game.get("result"),
                "team_score": game.get("team_score"),
                "opponent_score": game.get(
                    "opponent_score"
                ),
                "points": game.get("points", 0),
                "goals": game.get("goals", 0),
                "assists": game.get("assists", 0),
                "pim": game.get(
                    "penalty_minutes",
                    0,
                ),
                "rolling_3": rolling_3[index],
                "rolling_5": rolling_5[index],
            }
        )

    return {
        "games": chart,
        "summary": _summarize_games(games),

        "rolling_3": rolling_3,
        "rolling_5": rolling_5,

        "slope": _safe_round(
            slope,
            3,
        ),

        "direction": direction,

        "recent_average": _safe_round(
            recent_average
        ),

        "recent_momentum": _safe_round(
            momentum
        ),

        "goal_series": goals,
        "assist_series": assists,
        "point_series": points,
    }


# ---------------------------------------------------------------------
# Five-game forecast
# ---------------------------------------------------------------------

def build_five_game_forecast(games):
    games = _sort_player_games(games)

    if not games:
        return {
            "points_per_game": 0,
            "goals_per_game": 0,
            "assists_per_game": 0,
            "points_5_games": 0,
            "goals_5_games": 0,
            "assists_5_games": 0,
            "low_points": 0,
            "high_points": 0,
            "confidence": "insufficient data",
            "games": [],
        }

    points = [
        _int_number(g.get("points"))
        for g in games
    ]

    goals = [
        _int_number(g.get("goals"))
        for g in games
    ]

    assists = [
        _int_number(g.get("assists"))
        for g in games
    ]

    recent_points = _weighted_recent_average(
        points[-10:]
    )

    recent_goals = _weighted_recent_average(
        goals[-10:]
    )

    recent_assists = _weighted_recent_average(
        assists[-10:]
    )

    point_slope = _linear_slope(
        points[-10:]
    )

    goal_slope = _linear_slope(
        goals[-10:]
    )

    assist_slope = _linear_slope(
        assists[-10:]
    )

    projected_points = max(
        0,
        recent_points + point_slope * 1.5,
    )

    projected_goals = max(
        0,
        recent_goals + goal_slope * 1.5,
    )

    projected_assists = max(
        0,
        recent_assists + assist_slope * 1.5,
    )

    volatility = _stddev(
        points[-10:]
    )

    if len(points) < 3:
        confidence = "low"
    elif len(points) < 5:
        confidence = "medium-low"
    elif volatility <= 0.75:
        confidence = "high"
    elif volatility <= 1.5:
        confidence = "medium"
    else:
        confidence = "low"

    total_points = (
        projected_points * 5
    )

    uncertainty = max(
        1.5,
        volatility * 2,
    )

    low_points = max(
        0,
        total_points - uncertainty,
    )

    high_points = (
        total_points + uncertainty
    )

    forecast_games = []

    for i in range(1, 6):

        projected = max(
            0,
            projected_points
            + point_slope * (i - 1),
        )

        forecast_games.append(
            {
                "game": i,
                "projected_points": _safe_round(
                    projected
                ),
            }
        )

    return {
        "points_per_game": _safe_round(
            projected_points
        ),

        "goals_per_game": _safe_round(
            projected_goals
        ),

        "assists_per_game": _safe_round(
            projected_assists
        ),

        "points_5_games": _safe_round(
            projected_points * 5
        ),

        "goals_5_games": _safe_round(
            projected_goals * 5
        ),

        "assists_5_games": _safe_round(
            projected_assists * 5
        ),

        "low_points": _safe_round(
            low_points
        ),

        "high_points": _safe_round(
            high_points
        ),

        "confidence": confidence,

        "games": forecast_games,
    }


# ---------------------------------------------------------------------
# Coach metrics
# ---------------------------------------------------------------------

def build_coach_metrics(
    games,
    baseline_games=None,
):
    games = list(games)

    if baseline_games is None:
        baseline_games = games

    recent = _summarize_games(
        games
    )

    baseline = _summarize_games(
        baseline_games
    )

    if baseline["points_per_game"]:
        ppg_change_pct = (
            (
                recent["points_per_game"]
                - baseline["points_per_game"]
            )
            / baseline["points_per_game"]
            * 100
        )
    else:
        ppg_change_pct = 0

    goal_involvement = (
        recent["points"]
        / baseline["points"]
        * 100
        if baseline["points"]
        else 0
    )

    consistency = (
        recent["stddev_points"]
        / recent["points_per_game"]
        if recent["points_per_game"]
        else 0
    )

    if consistency <= 0.5:
        consistency_label = "high"
    elif consistency <= 1:
        consistency_label = "medium"
    else:
        consistency_label = "low"

    flags = []

    if ppg_change_pct >= 20:
        flags.append(
            "Scoring form is improving."
        )

    elif ppg_change_pct <= -20:
        flags.append(
            "Scoring form is declining."
        )

    if (
        recent["assists_per_game"]
        > baseline["assists_per_game"] * 1.2
    ):
        flags.append(
            "Assist production is increasing."
        )

    if (
        recent["goals_per_game"]
        > baseline["goals_per_game"] * 1.2
    ):
        flags.append(
            "Goal production is increasing."
        )

    if (
        recent["penalty_minutes_per_game"]
        > baseline["penalty_minutes_per_game"] * 1.5
        and recent["penalty_minutes_per_game"] > 1
    ):
        flags.append(
            "Penalty rate is elevated."
        )

    if recent["zero_point_games"] >= max(
        2,
        round(recent["games"] * 0.4),
    ):
        flags.append(
            "Low-output games are frequent."
        )

    if not flags:
        flags.append(
            "No major form warning detected."
        )

    return {
        "recent": recent,
        "baseline": baseline,

        "ppg_change_percent": _safe_round(
            ppg_change_pct
        ),

        "goal_involvement_percent": _safe_round(
            goal_involvement
        ),

        "consistency_score": _safe_round(
            consistency
        ),

        "consistency": consistency_label,

        "flags": flags,
    }


# ---------------------------------------------------------------------
# Career player statistics
# ---------------------------------------------------------------------

def build_career_player_stats(seasons):
    """
    Build career statistics directly from the supplied JSON schema.

    No dependency on build_player_season_stats() is required.
    """

    game_data = _extract_player_games(
        seasons
    )

    career = {}

    for name, games in game_data.items():

        games = _sort_player_games(
            games
        )

        if not games:
            continue

        by_season = defaultdict(list)

        for game in games:
            by_season[
                game["season"]
            ].append(game)

        season_stats = {}

        for season_name, season_games in by_season.items():

            summary = _summarize_games(
                season_games
            )

            teams = sorted(
                {
                    g.get("team")
                    for g in season_games
                    if g.get("team")
                }
            )

            season_stats[season_name] = {
                "team": (
                    teams[0]
                    if len(teams) == 1
                    else None
                ),

                "teams": teams,

                "games_played": summary[
                    "games"
                ],

                "wins": summary["wins"],
                "losses": summary["losses"],
                "draws": summary["draws"],

                "goals": summary["goals"],
                "assists": summary["assists"],
                "points": summary["points"],
                "penalty_minutes": summary[
                    "penalty_minutes"
                ],

                "points_per_game": summary[
                    "points_per_game"
                ],

                "goals_per_game": summary[
                    "goals_per_game"
                ],

                "assists_per_game": summary[
                    "assists_per_game"
                ],

                "penalty_minutes_per_game": (
                    summary[
                        "penalty_minutes_per_game"
                    ]
                ),
            }

        career_summary = _summarize_games(
            games
        )

        teams = sorted(
            {
                g.get("team")
                for g in games
                if g.get("team")
            }
        )

        ordered_seasons = list(
            season_stats.items()
        )

        best_season = None
        best_ppg_season = None

        if ordered_seasons:

            best_season_name, best_season_stats = max(
                ordered_seasons,
                key=lambda item: (
                    item[1]["points"],
                    item[1]["points_per_game"],
                ),
            )

            best_season = {
                "season": best_season_name,
                "points": best_season_stats[
                    "points"
                ],
                "goals": best_season_stats[
                    "goals"
                ],
                "assists": best_season_stats[
                    "assists"
                ],
                "points_per_game": best_season_stats[
                    "points_per_game"
                ],
            }

            best_ppg_name, best_ppg_stats = max(
                ordered_seasons,
                key=lambda item: (
                    item[1]["points_per_game"],
                    item[1]["points"],
                ),
            )

            best_ppg_season = {
                "season": best_ppg_name,
                "points_per_game": best_ppg_stats[
                    "points_per_game"
                ],
            }

        if len(ordered_seasons) >= 2:

            first_ppg = ordered_seasons[0][1][
                "points_per_game"
            ]

            latest_ppg = ordered_seasons[-1][1][
                "points_per_game"
            ]

            ppg_change = round(
                latest_ppg - first_ppg,
                2,
            )

        else:
            ppg_change = 0

        entry = {
            "name": name,

            "team": (
                games[-1].get("team")
            ),

            "teams": teams,

            "first_season": (
                ordered_seasons[0][0]
                if ordered_seasons
                else None
            ),

            "latest_season": (
                ordered_seasons[-1][0]
                if ordered_seasons
                else None
            ),

            "by_season": dict(
                ordered_seasons
            ),

            "career": {
                "games_played": career_summary[
                    "games"
                ],

                "wins": career_summary[
                    "wins"
                ],

                "losses": career_summary[
                    "losses"
                ],

                "draws": career_summary[
                    "draws"
                ],

                "goals": career_summary[
                    "goals"
                ],

                "assists": career_summary[
                    "assists"
                ],

                "points": career_summary[
                    "points"
                ],

                "penalty_minutes": career_summary[
                    "penalty_minutes"
                ],

                "points_per_game": career_summary[
                    "points_per_game"
                ],

                "goals_per_game": career_summary[
                    "goals_per_game"
                ],

                "assists_per_game": career_summary[
                    "assists_per_game"
                ],

                "penalty_minutes_per_game": (
                    career_summary[
                        "penalty_minutes_per_game"
                    ]
                ),
            },

            "best_season": best_season,

            "best_ppg_season": (
                best_ppg_season
            ),

            "ppg_change": ppg_change,

            # Complete game-by-game history.
            "games": games,
        }

        # -------------------------------------------------------------
        # Windows
        # -------------------------------------------------------------

        windows = build_player_windows(
            games,
            seasons,
        )

        entry["windows"] = windows

        entry["trend"] = {}
        entry["forecast"] = {}
        entry["coach_metrics"] = {}

        all_games = windows[
            "all_season"
        ]

        for window_name, window_games in windows.items():

            entry["trend"][
                window_name
            ] = build_form_analysis(
                window_games
            )

            entry["forecast"][
                window_name
            ] = build_five_game_forecast(
                window_games
            )

            entry["coach_metrics"][
                window_name
            ] = build_coach_metrics(
                window_games,
                all_games,
            )

        # Backwards compatibility.
        latest_window = (
            windows["last_5"]
            or windows["last_10"]
            or windows["all_season"]
        )

        entry["trend_legacy"] = (
            build_form_analysis(
                latest_window
            )
        )

        entry["projection"] = (
            build_five_game_forecast(
                latest_window
            )
        )

        career[name] = entry

    return dict(
        sorted(
            career.items(),
            key=lambda item: (
                item[1]["career"]["points"],
                item[1]["career"]["points_per_game"],
            ),
            reverse=True,
        )
    )


def player_season_points(entry):
    """
    Return season-by-season chart data.
    """

    return [
        {
            "season": season,

            "points_per_game": stats[
                "points_per_game"
            ],

            "points": stats["points"],
            "goals": stats["goals"],
            "assists": stats["assists"],

            "games_played": stats[
                "games_played"
            ],
        }

        for season, stats
        in entry["by_season"].items()
    ]


# ---------------------------------------------------------------------
# Team career statistics
# ---------------------------------------------------------------------

def _extract_team_games(seasons):
    """
    Build team-level game records directly from match JSON.
    """

    result = defaultdict(list)

    for season_name, season_games in seasons.items():

        for game in season_games:

            match = _match(game)

            home = match.get(
                "home_team"
            )

            away = match.get(
                "away_team"
            )

            home_score = _int_number(
                match.get("home_score")
            )

            away_score = _int_number(
                match.get("away_score")
            )

            date = _date_from_game(game)

            if home:
                result[home].append(
                    {
                        "date": date,
                        "season": season_name,
                        "team": home,
                        "opponent": away,
                        "home_team": home,
                        "away_team": away,
                        "home_score": home_score,
                        "away_score": away_score,
                        "goals_for": home_score,
                        "goals_against": away_score,
                        "result": (
                            "W"
                            if home_score > away_score
                            else "L"
                            if home_score < away_score
                            else "D"
                        ),
                    }
                )

            if away:
                result[away].append(
                    {
                        "date": date,
                        "season": season_name,
                        "team": away,
                        "opponent": home,
                        "home_team": home,
                        "away_team": away,
                        "home_score": home_score,
                        "away_score": away_score,
                        "goals_for": away_score,
                        "goals_against": home_score,
                        "result": (
                            "W"
                            if away_score > home_score
                            else "L"
                            if away_score < home_score
                            else "D"
                        ),
                    }
                )

    return dict(result)


def build_career_team_stats(seasons):
    team_games = _extract_team_games(
        seasons
    )

    career = {}

    for team, games in team_games.items():

        by_season = defaultdict(list)

        for game in games:
            by_season[
                game["season"]
            ].append(game)

        season_stats = {}

        for season, season_games in by_season.items():

            games_played = len(
                season_games
            )

            wins = sum(
                1
                for g in season_games
                if g["result"] == "W"
            )

            losses = sum(
                1
                for g in season_games
                if g["result"] == "L"
            )

            draws = sum(
                1
                for g in season_games
                if g["result"] == "D"
            )

            goals_for = sum(
                g["goals_for"]
                for g in season_games
            )

            goals_against = sum(
                g["goals_against"]
                for g in season_games
            )

            season_stats[season] = {
                "games_played": games_played,
                "wins": wins,
                "losses": losses,
                "draws": draws,
                "goals_for": goals_for,
                "goals_against": goals_against,
                "goal_diff": (
                    goals_for
                    - goals_against
                ),
                "points": (
                    wins * 2 + draws
                ),
            }

        games_played = len(games)

        wins = sum(
            1
            for g in games
            if g["result"] == "W"
        )

        losses = sum(
            1
            for g in games
            if g["result"] == "L"
        )

        draws = sum(
            1
            for g in games
            if g["result"] == "D"
        )

        goals_for = sum(
            g["goals_for"]
            for g in games
        )

        goals_against = sum(
            g["goals_against"]
            for g in games
        )

        career[team] = {
            "by_season": dict(
                season_stats
            ),

            "career": {
                "games_played": games_played,
                "wins": wins,
                "losses": losses,
                "draws": draws,
                "goals_for": goals_for,
                "goals_against": goals_against,
                "goal_diff": (
                    goals_for
                    - goals_against
                ),
                "points": (
                    wins * 2 + draws
                ),
            },

            "games": games,
        }

    return dict(
        sorted(
            career.items(),
            key=lambda item: (
                item[1]["career"]["goals_for"],
            ),
            reverse=True,
        )
    )


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------

def print_player_career(name, entry):
    print("=" * 70)

    teams = ", ".join(
        entry.get("teams", [])
    )

    print(
        f"PLAYER: {name}"
        f"{' [' + teams + ']' if teams else ''}"
    )

    print("=" * 70)

    for season, stats in entry[
        "by_season"
    ].items():

        print(
            f"{season:<14} "
            f"GP {stats['games_played']:>3} "
            f"G {stats['goals']:>3} "
            f"A {stats['assists']:>3} "
            f"P {stats['points']:>3} "
            f"({stats['points_per_game']:.2f} pts/gm)"
        )

    c = entry["career"]

    print("-" * 70)

    print(
        f"CAREER         "
        f"GP {c['games_played']:>3} "
        f"G {c['goals']:>3} "
        f"A {c['assists']:>3} "
        f"P {c['points']:>3} "
        f"({c['points_per_game']:.2f} pts/gm)"
    )

    for window in (
        "last_5",
        "last_10",
        "all_season",
    ):

        trend = entry[
            "trend"
        ].get(window)

        if not trend:
            continue

        summary = trend[
            "summary"
        ]

        print(
            f"{window:<20} "
            f"GP {summary['games']:>3} "
            f"Pts/GP "
            f"{summary['points_per_game']:.2f} "
            f"Trend "
            f"{trend['direction']}"
        )

    print()


def print_team_career(name, entry):
    print("=" * 70)
    print(f"TEAM: {name}")
    print("=" * 70)

    for season, stats in entry[
        "by_season"
    ].items():

        print(
            f"{season:<14} "
            f"GP {stats['games_played']:>3} "
            f"{stats['wins']}W-"
            f"{stats['losses']}L-"
            f"{stats['draws']}D "
            f"GF {stats['goals_for']:>3} "
            f"GA {stats['goals_against']:>3} "
            f"Diff {stats['goal_diff']:+d}"
        )

    c = entry["career"]

    print("-" * 70)

    print(
        f"CAREER         "
        f"GP {c['games_played']:>3} "
        f"{c['wins']}W-"
        f"{c['losses']}L-"
        f"{c['draws']}D "
        f"GF {c['goals_for']:>3} "
        f"GA {c['goals_against']:>3} "
        f"Diff {c['goal_diff']:+d}"
    )

    print()


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Aggregate floorball statistics across seasons "
            "with recent-form analysis."
        )
    )

    parser.add_argument(
        "root_dir",
        help="Folder containing season subfolders",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Write career JSON files",
    )

    parser.add_argument(
        "--player",
        help="Show one player",
    )

    parser.add_argument(
        "--team",
        help="Show one team",
    )

    parser.add_argument(
        "--top",
        type=int,
        default=15,
    )

    args = parser.parse_args()

    seasons = discover_seasons(
        args.root_dir
    )

    if not seasons:
        print(
            "No season folders containing valid "
            f"game JSON files found under {args.root_dir}"
        )
        return

    print(
        f"Found {len(seasons)} season(s): "
        f"{', '.join(seasons)}"
    )

    players = build_career_player_stats(
        seasons
    )

    teams = build_career_team_stats(
        seasons
    )

    if args.json:

        player_out = os.path.join(
            args.root_dir,
            "career_player_stats.json",
        )

        team_out = os.path.join(
            args.root_dir,
            "career_team_stats.json",
        )

        with open(
            player_out,
            "w",
            encoding="utf-8",
        ) as f:

            json.dump(
                players,
                f,
                ensure_ascii=False,
                indent=2,
            )

        with open(
            team_out,
            "w",
            encoding="utf-8",
        ) as f:

            json.dump(
                teams,
                f,
                ensure_ascii=False,
                indent=2,
            )

        print(
            f"Wrote {player_out}"
        )

        print(
            f"Wrote {team_out}"
        )

        return

    if args.player:

        key = player_key(
            args.player
        )

        if key in players:
            print_player_career(
                key,
                players[key],
            )
        else:
            print(
                f"No player found matching "
                f"'{args.player}'"
            )

        return

    if args.team:

        if args.team in teams:
            print_team_career(
                args.team,
                teams[args.team],
            )
        else:
            print(
                f"No team found matching "
                f"'{args.team}'"
            )

        return

    print("#" * 70)
    print("PLAYER RECENT FORM")
    print("#" * 70)

    for name, entry in list(
        players.items()
    )[:args.top]:

        print_player_career(
            name,
            entry,
        )


if __name__ == "__main__":
    main()
