"""
Season Statistics Engine
=========================
Aggregates every parsed match JSON (output of parse_match.py) in a folder
into season-wide player and team profiles.

Pipeline:
    data/games/*.json  --->  season_stats.py  --->  player + team season profiles

Usage:
    python season_stats.py data/games

    python season_stats.py data/games --json

    python season_stats.py data/games --player "Salvis Sīkmanis"

    python season_stats.py data/games --team "KNSS/Linde Grupa"

    python season_stats.py data/games --my-team knss

Known data limitation:
    The source (floorball.lv match reports) publishes TEAM-level shot counts
    (goals_shots_by_period), not per-player shots. Per-player shooting %
    therefore is intentionally not calculated.
"""

import argparse
import glob
import json
import math
import os
import re
from collections import Counter, defaultdict
from statistics import mean, median, pstdev

try:
    from analysis.game_stats import (
        ASSIST_RE,
        ASSIST_NAME_RE,
        goal_events,
        penalty_events,
        penalty_player_name,
        parse_penalty_minutes as gs_parse_penalty_minutes,
    )
except ImportError:
    from game_stats import (
        ASSIST_RE,
        ASSIST_NAME_RE,
        goal_events,
        penalty_events,
        penalty_player_name,
        parse_penalty_minutes as gs_parse_penalty_minutes,
    )


# ============================================================================
# Loading / generic helpers
# ============================================================================
def _resolve_roster_aliases(game):
    """Maps actual roster dict keys -> the canonical match['home_team']/
    match['away_team'] name, by cross-referencing player squad numbers
    seen in home/away-tagged events against each roster's player numbers.
    Handles cases where the scoreboard uses a different name than the
    roster section for the same club (e.g. 'FK VFK' vs
    'Florbola klubs "VFK"' - seen in the VFK match reports)."""
    match = game["match"]
    home_team, away_team = match["home_team"], match["away_team"]
    rosters = game.get("rosters", {})

    if home_team in rosters and away_team in rosters:
        return {}  # nothing to fix

    side_numbers = {"home": set(), "away": set()}
    for e in game.get("events", []):
        side = e.get("side")
        if side not in ("home", "away"):
            continue
        for m in re.finditer(r"#(\d+)", e.get("detail") or ""):
            side_numbers[side].add(int(m.group(1)))

    roster_numbers = {}
    for key, players in rosters.items():
        roster_numbers[key] = {
            p["number"] for p in players
            if isinstance(p, dict) and p.get("number") is not None
        }

    alias = {}
    for side, team_name in (("home", home_team), ("away", away_team)):
        wanted = side_numbers[side]
        best_key, best_overlap = None, 0
        for key, nums in roster_numbers.items():
            overlap = len(wanted & nums)
            if overlap > best_overlap:
                best_overlap = overlap
                best_key = key
        if best_key:
            alias[best_key] = team_name
    return alias


def normalize_roster_team_names(game):
    alias = _resolve_roster_aliases(game)
    if not alias:
        return game
    rosters = game.get("rosters", {})
    game["rosters"] = {alias.get(k, k): v for k, v in rosters.items()}
    return game


def load_games(games_dir: str) -> list:
    """Load every *.json in games_dir in filename/chronological order."""
    games = []

    for path in sorted(glob.glob(os.path.join(games_dir, "*.json"))):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        data["_source_file"] = os.path.basename(path)
        normalize_roster_team_names(data)
        games.append(data)

    return games


def player_key(name: str) -> str:
    """Normalize a player name for aggregation."""
    return " ".join(str(name or "").strip().split())


def parse_penalty_minutes(raw) -> int:
    """'2 min' -> 2. Handles None/empty safely."""
    if not raw:
        return 0

    m = re.search(r"(\d+)", str(raw))
    return int(m.group(1)) if m else 0


def safe_pct(numerator, denominator, decimals=1):
    if not denominator:
        return None
    return round(100.0 * numerator / denominator, decimals)


def safe_rate(numerator, denominator, decimals=2):
    if not denominator:
        return 0
    return round(numerator / denominator, decimals)


def normalize_side(side):
    if side in ("home", "away"):
        return side
    return None


def team_for_side(match, side):
    if side == "home":
        return match.get("home_team")
    if side == "away":
        return match.get("away_team")
    return None


def opposite_side(side):
    if side == "home":
        return "away"
    if side == "away":
        return "home"
    return None


def team_matches_keyword(team_name, keyword="knss"):
    return bool(
        team_name
        and keyword
        and keyword.lower() in team_name.lower()
    )


def identify_game_result(match, team_name):
    home = match["home_team"]
    away = match["away_team"]
    hs = match["home_score"]
    aws = match["away_score"]

    if team_name == home:
        gf, ga = hs, aws
    elif team_name == away:
        gf, ga = aws, hs
    else:
        return None

    if gf > ga:
        return "W"
    if gf < ga:
        return "L"
    return "D"


def get_team_game_values(match, team_name):
    home = match["home_team"]
    away = match["away_team"]
    hs = match["home_score"]
    aws = match["away_score"]

    if team_name == home:
        return hs, aws, away, "home"

    if team_name == away:
        return aws, hs, home, "away"

    return None, None, None, None


def parse_event_seconds(value):
    """
    Convert common floorball event times into seconds.

    Handles:
        12:34
        1:02:34
        62
        numeric values

    Returns None when the value cannot be interpreted.
    """
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()

    m = re.search(r"(\d+):(\d+):(\d+)", text)
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))

    m = re.search(r"(\d+):(\d+)", text)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))

    m = re.search(r"\b(\d+(?:\.\d+)?)\b", text)
    if m:
        return float(m.group(1))

    return None


def event_time(event):
    return (
        event.get("seconds")
        if isinstance(event, dict) and event.get("seconds") is not None
        else parse_event_seconds(
            event.get("time") if isinstance(event, dict) else None
        )
    )


def sorted_goal_events(game):
    events = []

    for e in goal_events(game.get("events", [])):
        seconds = event_time(e)

        if seconds is None:
            continue

        copy = dict(e)
        copy["_seconds"] = seconds
        events.append(copy)

    return sorted(events, key=lambda x: x["_seconds"])


def sorted_penalty_events(game):
    events = []

    for e in penalty_events(game.get("events", [])):
        seconds = event_time(e)

        if seconds is None:
            continue

        copy = dict(e)
        copy["_seconds"] = seconds
        events.append(copy)

    return sorted(events, key=lambda x: x["_seconds"])


def event_is_goal_for_team(event, team_name, match):
    return team_for_side(match, normalize_side(event.get("side"))) == team_name


def event_is_goal_against_team(event, team_name, match):
    side = normalize_side(event.get("side"))
    opponent = opposite_side(side)
    return team_for_side(match, opponent) == team_name


def player_name_from_goal_event(event):
    detail = str(event.get("detail", ""))

    m = ASSIST_RE.match(detail)
    if m:
        return player_key(m.group("scorer"))

    # Fallback for unusual event formatting.
    for pattern in (
        r"^\s*(?:\d+\s+)?(.+?)(?:\s+\(|$)",
        r"^\s*(.+?)(?:\s*-\s*)",
    ):
        m = re.search(pattern, detail)
        if m:
            candidate = player_key(m.group(1))
            if candidate:
                return candidate

    return None


def assists_from_goal_event(event):
    detail = str(event.get("detail", ""))
    m = ASSIST_RE.match(detail)

    if not m or not m.group("assists"):
        return []

    return [
        player_key(name)
        for name in ASSIST_NAME_RE.findall(m.group("assists"))
        if player_key(name)
    ]


def roster_players_for_team(game, team_name):
    result = []

    for p in game.get("rosters", {}).get(team_name, []):
        if "staff" in p:
            continue

        name = player_key(p.get("name"))

        if name:
            result.append(name)

    return result


def game_has_player(game, team_name, player_name):
    target = player_key(player_name)

    return target in {
        player_key(p)
        for p in roster_players_for_team(game, team_name)
    }


def standard_deviation(values):
    values = [float(v) for v in values]

    if len(values) < 2:
        return 0

    return round(pstdev(values), 2)


def coefficient_of_variation(values):
    values = [float(v) for v in values]
    if not values:
        return 0

    avg = mean(values)

    if avg == 0:
        return 0

    return round(pstdev(values) / abs(avg), 2)


def longest_boolean_streak(values, target=True):
    """
    Returns:
        {
            "length": ...,
            "start_index": ...,
            "end_index": ...
        }
    """
    best = {
        "length": 0,
        "start_index": None,
        "end_index": None,
    }

    current_start = None
    current_length = 0

    for i, value in enumerate(values):
        if value == target:
            if current_length == 0:
                current_start = i

            current_length += 1

            if current_length > best["length"]:
                best = {
                    "length": current_length,
                    "start_index": current_start,
                    "end_index": i,
                }
        else:
            current_length = 0
            current_start = None

    return best


def longest_value_streak(values, predicate):
    best = {
        "length": 0,
        "start_index": None,
        "end_index": None,
    }

    current_start = None
    current_length = 0

    for i, value in enumerate(values):
        if predicate(value):
            if current_length == 0:
                current_start = i

            current_length += 1

            if current_length > best["length"]:
                best = {
                    "length": current_length,
                    "start_index": current_start,
                    "end_index": i,
                }
        else:
            current_length = 0
            current_start = None

    return best


# ============================================================================
# Existing player aggregation
# ============================================================================

def build_player_season_stats(games: list) -> dict:
    players = defaultdict(lambda: {
        "team": None,
        "games_played": 0,
        "goals": 0,
        "assists": 0,
        "points": 0,
        "penalty_minutes": 0,
        "game_log": [],
    })

    for game in games:
        match = game["match"]
        game_date = match.get("date")
        rosters = game.get("rosters", {})

        for team_name, roster in rosters.items():
            for p in roster:
                if "staff" in p:
                    continue

                key = player_key(p["name"])
                rec = players[key]

                rec["team"] = team_name
                rec["games_played"] += 1

                g = p.get("goals") or 0
                a = p.get("assists") or 0
                pts = p.get("points") or 0
                pim = parse_penalty_minutes(p.get("penalty_minutes"))

                rec["goals"] += g
                rec["assists"] += a
                rec["points"] += pts
                rec["penalty_minutes"] += pim

                gf, ga, opponent, side = get_team_game_values(
                    match, team_name
                )

                rec["game_log"].append({
                    "date": game_date,
                    "opponent": opponent,
                    "goals": g,
                    "assists": a,
                    "points": pts,
                    "penalty_minutes": pim,
                    "team_goals_for": gf,
                    "team_goals_against": ga,
                    "result": (
                        "W" if gf > ga
                        else "L" if gf < ga
                        else "D"
                    ),
                })

    for rec in players.values():
        running = 0

        for entry in rec["game_log"]:
            running += entry["points"]
            entry["cumulative_points"] = running

        gp = rec["games_played"]

        rec["goals_per_game"] = safe_rate(rec["goals"], gp)
        rec["assists_per_game"] = safe_rate(rec["assists"], gp)
        rec["points_per_game"] = safe_rate(rec["points"], gp)

    return dict(
        sorted(
            players.items(),
            key=lambda kv: kv[1]["points"],
            reverse=True,
        )
    )


# ============================================================================
# Existing team aggregation
# ============================================================================

def build_team_season_stats(games: list) -> dict:
    teams = defaultdict(lambda: {
        "games_played": 0,
        "wins": 0,
        "losses": 0,
        "draws": 0,
        "goals_for": 0,
        "goals_against": 0,
        "shots_for": 0,
        "shots_against": 0,
        "game_log": [],
    })

    for game in games:
        match = game["match"]
        home = match["home_team"]
        away = match["away_team"]
        hs = match["home_score"]
        aws = match["away_score"]

        team_shots = {}

        for row in game.get("goals_shots_by_period", []):
            total = (
                row.get("by_period", {}).get("Kopā")
                or row.get("by_period", {}).get("Total")
            )

            if total:
                team_shots[row["team"]] = total.get("shots", 0) or 0

        for team, gf, ga in (
            (home, hs, aws),
            (away, aws, hs),
        ):
            rec = teams[team]

            rec["games_played"] += 1
            rec["goals_for"] += gf
            rec["goals_against"] += ga

            opponent = away if team == home else home

            rec["shots_for"] += team_shots.get(team, 0)
            rec["shots_against"] += team_shots.get(opponent, 0)

            if gf > ga:
                rec["wins"] += 1
                result = "W"
            elif gf < ga:
                rec["losses"] += 1
                result = "L"
            else:
                rec["draws"] += 1
                result = "D"

            rec["game_log"].append({
                "date": match.get("date"),
                "opponent": opponent,
                "goals_for": gf,
                "goals_against": ga,
                "result": result,
            })

    for rec in teams.values():
        rec["goal_diff"] = (
            rec["goals_for"] - rec["goals_against"]
        )

        rec["standings_points"] = (
            rec["wins"] * 3
            + rec["draws"]
        )

        rec["goals_for_per_game"] = safe_rate(
            rec["goals_for"],
            rec["games_played"],
        )

        rec["goals_against_per_game"] = safe_rate(
            rec["goals_against"],
            rec["games_played"],
        )

        rec["points_percentage"] = safe_pct(
            rec["standings_points"],
            rec["games_played"] * 3,
        )

        rec["shooting_pct"] = safe_pct(
            rec["goals_for"],
            rec["shots_for"],
        )

    return dict(
        sorted(
            teams.items(),
            key=lambda kv: (
                kv[1]["standings_points"],
                kv[1]["goal_diff"],
            ),
            reverse=True,
        )
    )


# ============================================================================
# Assist / goal combinations
# ============================================================================

def build_season_assist_network(games: list) -> dict:
    pairs = Counter()
    unassisted = Counter()

    for game in games:
        match = game["match"]

        for e in goal_events(game.get("events", [])):
            detail = str(e.get("detail", ""))

            if "soda metiens" in detail.lower():
                continue

            m = ASSIST_RE.match(detail)

            if not m:
                continue

            scorer = player_key(m.group("scorer"))

            team = (
                match["home_team"]
                if e["side"] == "home"
                else match["away_team"]
                if e["side"] == "away"
                else None
            )

            assists_blob = m.group("assists")

            if not assists_blob:
                unassisted[(scorer, team)] += 1
                continue

            for assist_name in ASSIST_NAME_RE.findall(
                assists_blob
            ):
                pairs[
                    (
                        player_key(assist_name),
                        scorer,
                        team,
                    )
                ] += 1

    return {
        "top_pairs": [
            {
                "assist_by": a,
                "goal_by": s,
                "team": t,
                "times": n,
            }
            for (a, s, t), n in pairs.most_common(30)
        ],
        "unassisted_goals": [
            {
                "player": s,
                "team": t,
                "times": n,
            }
            for (s, t), n in unassisted.most_common(30)
        ],
    }


def build_goal_scoring_combinations(games: list) -> list:
    """
    More detailed scorer/assist combination analysis.

    Includes:
        - total goals involving a pair
        - direct assists
        - share of scorer's goals assisted by player
    """
    pair_data = defaultdict(
        lambda: {
            "team": None,
            "assist_by": None,
            "goal_by": None,
            "assists": 0,
        }
    )

    scorer_goals = Counter()

    for game in games:
        match = game["match"]

        for event in goal_events(game.get("events", [])):
            detail = str(event.get("detail", ""))

            if "soda metiens" in detail.lower():
                continue

            scorer = player_name_from_goal_event(event)

            if not scorer:
                continue

            team = team_for_side(
                match,
                normalize_side(event.get("side")),
            )

            scorer_goals[(scorer, team)] += 1

            for assister in assists_from_goal_event(event):
                key = (assister, scorer, team)

                pair_data[key]["team"] = team
                pair_data[key]["assist_by"] = assister
                pair_data[key]["goal_by"] = scorer
                pair_data[key]["assists"] += 1

    result = []

    for (assister, scorer, team), rec in pair_data.items():
        total_goals = scorer_goals[(scorer, team)]

        result.append({
            "assist_by": assister,
            "goal_by": scorer,
            "team": team,
            "assists": rec["assists"],
            "scorer_goals": total_goals,
            "scorer_goal_share_pct": safe_pct(
                rec["assists"],
                total_goals,
            ),
        })

    result.sort(
        key=lambda x: (
            x["assists"],
            x["scorer_goal_share_pct"] or 0,
        ),
        reverse=True,
    )

    return result


# ============================================================================
# Discipline
# ============================================================================

def build_season_discipline(games: list) -> list:
    infractions = Counter()
    minutes = Counter()

    for game in games:
        match = game["match"]

        for e in penalty_events(game.get("events", [])):
            name = penalty_player_name(e["detail"])

            team = (
                match["home_team"]
                if e["side"] == "home"
                else match["away_team"]
                if e["side"] == "away"
                else None
            )

            infractions[(name, team)] += 1
            minutes[(name, team)] += gs_parse_penalty_minutes(
                e["detail"]
            )

    result = []

    for (name, team), count in sorted(
        infractions.items(),
        key=lambda kv: kv[1],
        reverse=True,
    ):
        result.append({
            "player": name,
            "team": team,
            "infractions": count,
            "total_minutes": minutes[(name, team)],
            "minutes_per_infraction": safe_rate(
                minutes[(name, team)],
                count,
            ),
        })

    return result


def build_player_discipline(games: list) -> list:
    """
    Discipline normalized by games played.

    This is more useful than raw PIM because a player who played 20 games
    should not be compared directly with someone who played 4.
    """
    data = defaultdict(
        lambda: {
            "player": None,
            "team": None,
            "games": 0,
            "infractions": 0,
            "minutes": 0,
        }
    )

    for game in games:
        for team, roster in game.get("rosters", {}).items():
            for p in roster:
                if "staff" in p:
                    continue

                name = player_key(p.get("name"))
                key = (name, team)

                data[key]["player"] = name
                data[key]["team"] = team
                data[key]["games"] += 1

                data[key]["minutes"] += parse_penalty_minutes(
                    p.get("penalty_minutes")
                )

        match = game["match"]

        for e in penalty_events(game.get("events", [])):
            name = player_key(
                penalty_player_name(e["detail"])
            )

            team = team_for_side(
                match,
                normalize_side(e.get("side")),
            )

            if not name or not team:
                continue

            key = (name, team)
            data[key]["infractions"] += 1

    result = []

    for rec in data.values():
        result.append({
            **rec,
            "minutes_per_game": safe_rate(
                rec["minutes"],
                rec["games"],
            ),
            "infractions_per_game": safe_rate(
                rec["infractions"],
                rec["games"],
            ),
        })

    result.sort(
        key=lambda x: (
            x["minutes_per_game"],
            x["infractions_per_game"],
        ),
        reverse=True,
    )

    return result


# ============================================================================
# Penalties followed by conceded goals
# ============================================================================

def build_penalties_followed_by_conceded_goals(
    games: list,
    window_seconds: int = 120,
) -> list:
    """
    Finds penalties followed by an opponent goal within the selected window.

    This is a contextual heuristic, not proof that the penalty caused the goal.
    """
    results = []

    for game in games:
        match = game["match"]
        goals = sorted_goal_events(game)
        penalties = sorted_penalty_events(game)

        for penalty in penalties:
            team = team_for_side(
                match,
                normalize_side(penalty.get("side")),
            )

            if not team:
                continue

            penalty_seconds = penalty["_seconds"]

            for goal in goals:
                if goal["_seconds"] <= penalty_seconds:
                    continue

                delta = goal["_seconds"] - penalty_seconds

                if delta > window_seconds:
                    break

                if event_is_goal_against_team(
                    goal,
                    team,
                    match,
                ):
                    results.append({
                        "date": match.get("date"),
                        "team": team,
                        "player": penalty_player_name(
                            penalty.get("detail", "")
                        ),
                        "penalty_time": penalty.get("time"),
                        "penalty_detail": penalty.get("detail"),
                        "conceded_goal_time": goal.get("time"),
                        "seconds_after_penalty": round(delta),
                        "conceded_goal_detail": goal.get("detail"),
                        "window_seconds": window_seconds,
                    })
                    break

    return results


# ============================================================================
# Player consistency / reliability / variation
# ============================================================================

def build_player_consistency(games: list) -> list:
    result = []

    players = build_player_season_stats(games)

    for name, rec in players.items():
        logs = rec["game_log"]

        if not logs:
            continue

        points = [x["points"] for x in logs]
        goals = [x["goals"] for x in logs]
        assists = [x["assists"] for x in logs]

        scoring_games = sum(p > 0 for p in points)
        goal_games = sum(g > 0 for g in goals)

        point_streak = longest_value_streak(
            points,
            lambda x: x > 0,
        )

        scoreless_streak = longest_value_streak(
            points,
            lambda x: x == 0,
        )

        result.append({
            "player": name,
            "team": rec["team"],
            "games": len(logs),
            "points": rec["points"],
            "points_per_game": rec["points_per_game"],
            "point_games": scoring_games,
            "point_game_pct": safe_pct(
                scoring_games,
                len(logs),
            ),
            "goal_games": goal_games,
            "goal_game_pct": safe_pct(
                goal_games,
                len(logs),
            ),
            "points_std_dev": standard_deviation(points),
            "goals_std_dev": standard_deviation(goals),
            "assists_std_dev": standard_deviation(assists),
            "points_cv": coefficient_of_variation(points),
            "longest_point_streak": point_streak["length"],
            "longest_scoreless_streak": scoreless_streak["length"],
            "min_points_game": min(points),
            "max_points_game": max(points),
            "median_points": median(points),
        })

    # High point-game rate + low variation = reliable.
    result.sort(
        key=lambda x: (
            x["point_game_pct"] or 0,
            -(x["points_std_dev"] or 0),
            x["points_per_game"],
        ),
        reverse=True,
    )

    return result


def build_player_reliability(games: list) -> list:
    consistency = build_player_consistency(games)
    result = []

    for rec in consistency:
        """
        Reliability score is intentionally transparent and bounded.

        Components:
            50% games producing at least one point
            30% normalized points/game
            20% low game-to-game variation
        """
        point_rate = (rec["point_game_pct"] or 0) / 100.0
        ppg = rec["points_per_game"]

        variation = rec["points_cv"]

        consistency_component = (
            1 / (1 + variation)
            if variation >= 0
            else 0
        )

        # Cap the production component at 1 so huge point rates do not
        # overwhelm reliability.
        production_component = min(ppg / 2.0, 1.0)

        score = round(
            100 * (
                0.50 * point_rate
                + 0.30 * production_component
                + 0.20 * consistency_component
            ),
            1,
        )

        result.append({
            **rec,
            "reliability_score": score,
        })

    result.sort(
        key=lambda x: x["reliability_score"],
        reverse=True,
    )

    return result


def build_game_to_game_variation(games: list) -> list:
    consistency = build_player_consistency(games)

    return [
        {
            "player": x["player"],
            "team": x["team"],
            "games": x["games"],
            "points_avg": x["points_per_game"],
            "points_std_dev": x["points_std_dev"],
            "points_cv": x["points_cv"],
            "goals_std_dev": x["goals_std_dev"],
            "assists_std_dev": x["assists_std_dev"],
            "min_points": x["min_points_game"],
            "max_points": x["max_points_game"],
            "median_points": x["median_points"],
        }
        for x in sorted(
            consistency,
            key=lambda x: x["points_std_dev"],
            reverse=True,
        )
    ]


# ============================================================================
# Hot / cold streaks
# ============================================================================

def build_player_streaks(games: list) -> list:
    players = build_player_season_stats(games)
    result = []

    for name, rec in players.items():
        logs = rec["game_log"]

        if not logs:
            continue

        points = [x["points"] for x in logs]

        hot = longest_value_streak(
            points,
            lambda x: x >= 1,
        )

        multi_point = longest_value_streak(
            points,
            lambda x: x >= 2,
        )

        cold = longest_value_streak(
            points,
            lambda x: x == 0,
        )

        def slice_avg(streak):
            if streak["length"] <= 0:
                return 0

            values = points[
                streak["start_index"]:
                streak["end_index"] + 1
            ]

            return round(mean(values), 2)

        result.append({
            "player": name,
            "team": rec["team"],
            "games": len(logs),
            "longest_hot_streak": hot["length"],
            "hot_streak_points_per_game": slice_avg(hot),
            "longest_multi_point_streak": multi_point["length"],
            "longest_cold_streak": cold["length"],
            "current_streak": (
                longest_value_streak(
                    list(reversed(points)),
                    lambda x: x > 0,
                )["length"]
            ),
        })

    result.sort(
        key=lambda x: (
            x["longest_hot_streak"],
            x["hot_streak_points_per_game"],
        ),
        reverse=True,
    )

    return result


# ============================================================================
# Scoring contribution
# ============================================================================

def build_scoring_contribution(
    games: list,
    my_team_keyword: str = "knss",
) -> list:
    """
    Measures how much of the team's scoring production each player represents.
    """
    players = build_player_season_stats(games)

    team_goals = Counter()

    for game in games:
        match = game["match"]

        for team in (
            match["home_team"],
            match["away_team"],
        ):
            gf, _, _, _ = get_team_game_values(match, team)
            team_goals[team] += gf

    result = []

    for name, rec in players.items():
        team = rec["team"]

        result.append({
            "player": name,
            "team": team,
            "goals": rec["goals"],
            "assists": rec["assists"],
            "points": rec["points"],
            "team_goals": team_goals[team],
            "goal_share_pct": safe_pct(
                rec["goals"],
                team_goals[team],
            ),
            "point_share_pct": safe_pct(
                rec["points"],
                team_goals[team],
            ),
            "points_per_team_goal": safe_rate(
                rec["points"],
                team_goals[team],
            ),
            "games": rec["games_played"],
        })

    result.sort(
        key=lambda x: x["point_share_pct"] or 0,
        reverse=True,
    )

    return result


# ============================================================================
# Player impact
# ============================================================================

def build_player_impact(
    games: list,
    my_team_keyword: str = "knss",
) -> list:
    """
    Impact combines:
        - team win rate when player is in roster
        - team win rate when player is absent
        - points contribution
        - goal differential while present/absent

    Since parsed JSON does not provide shifts/minutes played, "present" means
    present on the match roster. It does NOT mean the player was on the floor
    for every second.
    """
    candidate_teams = set()

    for game in games:
        for team in game.get("rosters", {}):
            if team_matches_keyword(team, my_team_keyword):
                candidate_teams.add(team)

    if not candidate_teams:
        for game in games:
            for team in game.get("rosters", {}):
                candidate_teams.add(team)

    target_teams = candidate_teams

    player_names = set()

    for game in games:
        for team in target_teams:
            player_names.update(
                roster_players_for_team(game, team)
            )

    result = []

    for player in sorted(player_names):
        for team in target_teams:
            present = []
            absent = []

            for game in games:
                if team not in game.get("rosters", {}):
                    continue

                gf, ga, opponent, side = get_team_game_values(
                    game["match"],
                    team,
                )

                if gf is None:
                    continue

                row = {
                    "date": game["match"].get("date"),
                    "opponent": opponent,
                    "gf": gf,
                    "ga": ga,
                    "diff": gf - ga,
                    "result": (
                        "W" if gf > ga
                        else "L" if gf < ga
                        else "D"
                    ),
                }

                if game_has_player(
                    game,
                    team,
                    player,
                ):
                    present.append(row)
                else:
                    absent.append(row)

            if not present:
                continue

            present_wins = sum(
                x["result"] == "W"
                for x in present
            )

            absent_wins = sum(
                x["result"] == "W"
                for x in absent
            )

            present_diff = sum(
                x["diff"] for x in present
            )

            absent_diff = sum(
                x["diff"] for x in absent
            )

            present_win_pct = safe_pct(
                present_wins,
                len(present),
            )

            absent_win_pct = safe_pct(
                absent_wins,
                len(absent),
            )

            win_rate_delta = None

            if absent:
                win_rate_delta = round(
                    present_win_pct - absent_win_pct,
                    1,
                )

            result.append({
                "player": player,
                "team": team,
                "games_present": len(present),
                "games_absent": len(absent),
                "wins_present": present_wins,
                "wins_absent": absent_wins,
                "win_pct_present": present_win_pct,
                "win_pct_absent": absent_win_pct,
                "win_pct_delta": win_rate_delta,
                "goal_diff_present": present_diff,
                "goal_diff_absent": absent_diff,
                "goal_diff_per_game_present": safe_rate(
                    present_diff,
                    len(present),
                ),
                "goal_diff_per_game_absent": safe_rate(
                    absent_diff,
                    len(absent),
                ),
            })

    result.sort(
        key=lambda x: (
            x["win_pct_delta"]
            if x["win_pct_delta"] is not None
            else -999
        ),
        reverse=True,
    )

    return result


# ============================================================================
# Player performance when team wins/losses
# ============================================================================

def build_player_win_loss_performance(games: list) -> list:
    players = build_player_season_stats(games)

    result = []

    for name, rec in players.items():
        wins = []
        losses = []
        draws = []

        for game in rec["game_log"]:
            result_value = game["result"]

            if result_value == "W":
                wins.append(game)
            elif result_value == "L":
                losses.append(game)
            else:
                draws.append(game)

        def stats_for(rows):
            return {
                "games": len(rows),
                "goals": sum(x["goals"] for x in rows),
                "assists": sum(x["assists"] for x in rows),
                "points": sum(x["points"] for x in rows),
                "points_per_game": safe_rate(
                    sum(x["points"] for x in rows),
                    len(rows),
                ),
            }

        w = stats_for(wins)
        l = stats_for(losses)
        d = stats_for(draws)

        result.append({
            "player": name,
            "team": rec["team"],
            "wins": w,
            "losses": l,
            "draws": d,
            "win_loss_ppg_delta": round(
                w["points_per_game"]
                - l["points_per_game"],
                2,
            ),
        })

    result.sort(
        key=lambda x: x["win_loss_ppg_delta"],
        reverse=True,
    )

    return result


# ============================================================================
# Opponent-specific player performance
# ============================================================================

def build_opponent_player_performance(
    games: list,
    my_team_keyword: str = "knss",
) -> list:
    """
    Player performance against each individual opponent.
    """
    data = defaultdict(
        lambda: {
            "player": None,
            "team": None,
            "opponent": None,
            "games": 0,
            "goals": 0,
            "assists": 0,
            "points": 0,
            "wins": 0,
            "losses": 0,
            "draws": 0,
        }
    )

    for game in games:
        match = game["match"]

        my_teams = [
            team
            for team in (
                match["home_team"],
                match["away_team"],
            )
            if team_matches_keyword(
                team,
                my_team_keyword,
            )
        ]

        if len(my_teams) != 1:
            continue

        team = my_teams[0]
        opponent = (
            match["away_team"]
            if team == match["home_team"]
            else match["home_team"]
        )

        gf, ga, _, _ = get_team_game_values(
            match,
            team,
        )

        result_value = (
            "W" if gf > ga
            else "L" if gf < ga
            else "D"
        )

        for p in game.get("rosters", {}).get(team, []):
            if "staff" in p:
                continue

            name = player_key(p.get("name"))

            if not name:
                continue

            key = (name, team, opponent)
            rec = data[key]

            rec["player"] = name
            rec["team"] = team
            rec["opponent"] = opponent
            rec["games"] += 1
            rec["goals"] += p.get("goals") or 0
            rec["assists"] += p.get("assists") or 0
            rec["points"] += p.get("points") or 0

            if result_value == "W":
                rec["wins"] += 1
            elif result_value == "L":
                rec["losses"] += 1
            else:
                rec["draws"] += 1

    result = []

    for rec in data.values():
        result.append({
            **rec,
            "goals_per_game": safe_rate(
                rec["goals"],
                rec["games"],
            ),
            "assists_per_game": safe_rate(
                rec["assists"],
                rec["games"],
            ),
            "points_per_game": safe_rate(
                rec["points"],
                rec["games"],
            ),
        })

    result.sort(
        key=lambda x: (
            x["opponent"],
            x["points"],
        ),
        reverse=False,
    )

    return result


# ============================================================================
# First / last scoring impact
# ============================================================================

def build_first_last_scoring_impact(
    games: list,
    my_team_keyword: str = "knss",
) -> dict:
    data = defaultdict(
        lambda: {
            "games": 0,
            "first_goal_games": 0,
            "first_goal_wins": 0,
            "first_goal_losses": 0,
            "last_goal_games": 0,
            "last_goal_wins": 0,
            "last_goal_wins_when_for": 0,
            "last_goal_losses_when_for": 0,
        }
    )

    team_names = set()

    for game in games:
        match = game["match"]

        for team in (
            match["home_team"],
            match["away_team"],
        ):
            if team_matches_keyword(
                team,
                my_team_keyword,
            ):
                team_names.add(team)

    for game in games:
        match = game["match"]
        goals = sorted_goal_events(game)

        if not goals:
            continue

        for team in team_names:
            gf, ga, opponent, side = get_team_game_values(
                match,
                team,
            )

            if gf is None:
                continue

            result_value = (
                "W" if gf > ga
                else "L" if gf < ga
                else "D"
            )

            rec = data[team]
            rec["games"] += 1

            first = goals[0]
            first_team = team_for_side(
                match,
                normalize_side(first.get("side")),
            )

            last = goals[-1]
            last_team = team_for_side(
                match,
                normalize_side(last.get("side")),
            )

            if first_team == team:
                rec["first_goal_games"] += 1

                if result_value == "W":
                    rec["first_goal_wins"] += 1

                if result_value == "L":
                    rec["first_goal_losses"] += 1

            if last_team == team:
                rec["last_goal_games"] += 1
                rec["last_goal_wins_when_for"] += (
                    result_value == "W"
                )
                rec["last_goal_losses_when_for"] += (
                    result_value == "L"
                )

    result = {}

    for team, rec in data.items():
        result[team] = {
            **rec,
            "first_goal_win_pct": safe_pct(
                rec["first_goal_wins"],
                rec["first_goal_games"],
            ),
            "last_goal_win_pct": safe_pct(
                rec["last_goal_wins_when_for"],
                rec["last_goal_games"],
            ),
        }

    return result


# ============================================================================
# Close games
# ============================================================================

def build_close_game_performance(
    games: list,
    my_team_keyword: str = "knss",
    max_margin: int = 2,
) -> dict:
    result = {}

    for game in games:
        match = game["match"]

        for team in (
            match["home_team"],
            match["away_team"],
        ):
            if not team_matches_keyword(
                team,
                my_team_keyword,
            ):
                continue

            gf, ga, opponent, side = get_team_game_values(
                match,
                team,
            )

            if abs(gf - ga) > max_margin:
                continue

            result.setdefault(
                team,
                {
                    "games": 0,
                    "wins": 0,
                    "losses": 0,
                    "draws": 0,
                    "goals_for": 0,
                    "goals_against": 0,
                    "game_log": [],
                },
            )

            rec = result[team]

            rec["games"] += 1
            rec["goals_for"] += gf
            rec["goals_against"] += ga

            if gf > ga:
                rec["wins"] += 1
                result_value = "W"
            elif gf < ga:
                rec["losses"] += 1
                result_value = "L"
            else:
                rec["draws"] += 1
                result_value = "D"

            rec["game_log"].append({
                "date": match.get("date"),
                "opponent": opponent,
                "score": f"{gf}-{ga}",
                "result": result_value,
                "margin": gf - ga,
            })

    for rec in result.values():
        rec["win_pct"] = safe_pct(
            rec["wins"],
            rec["games"],
        )
        rec["goal_diff"] = (
            rec["goals_for"] - rec["goals_against"]
        )
        rec["goal_diff_per_game"] = safe_rate(
            rec["goal_diff"],
            rec["games"],
        )

    return result


# ============================================================================
# Scoring runs
# ============================================================================

def build_scoring_runs(
    games: list,
    my_team_keyword: str = "knss",
) -> list:
    """
    Finds the longest unanswered scoring runs for every team in each game.
    """
    runs = []

    for game in games:
        match = game["match"]
        goals = sorted_goal_events(game)

        if not goals:
            continue

        current_side = None
        current_goals = []
        best = None

        for goal in goals:
            side = normalize_side(goal.get("side"))

            if side == current_side:
                current_goals.append(goal)
            else:
                if current_goals:
                    candidate = {
                        "side": current_side,
                        "team": team_for_side(
                            match,
                            current_side,
                        ),
                        "count": len(current_goals),
                        "start_time": current_goals[0].get("time"),
                        "end_time": current_goals[-1].get("time"),
                        "start_seconds": current_goals[0]["_seconds"],
                        "end_seconds": current_goals[-1]["_seconds"],
                    }

                    if (
                        best is None
                        or candidate["count"] > best["count"]
                    ):
                        best = candidate

                current_side = side
                current_goals = [goal]

        if current_goals:
            candidate = {
                "side": current_side,
                "team": team_for_side(
                    match,
                    current_side,
                ),
                "count": len(current_goals),
                "start_time": current_goals[0].get("time"),
                "end_time": current_goals[-1].get("time"),
                "start_seconds": current_goals[0]["_seconds"],
                "end_seconds": current_goals[-1]["_seconds"],
            }

            if (
                best is None
                or candidate["count"] > best["count"]
            ):
                best = candidate

        if best:
            best["date"] = match.get("date")
            best["opponent"] = (
                match["away_team"]
                if best["team"] == match["home_team"]
                else match["home_team"]
            )
            best["our_team"] = team_matches_keyword(
                best["team"],
                my_team_keyword,
            )
            runs.append(best)

    runs.sort(
        key=lambda x: x["count"],
        reverse=True,
    )

    return runs


def build_season_scoring_run_summary(
    games: list,
    my_team_keyword: str = "knss",
) -> dict:
    runs = build_scoring_runs(
        games,
        my_team_keyword,
    )

    summary = defaultdict(
        lambda: {
            "games_with_runs": 0,
            "runs_2_plus": 0,
            "runs_3_plus": 0,
            "runs_4_plus": 0,
            "longest_run": 0,
            "average_run": 0,
        }
    )

    all_runs = defaultdict(list)

    for run in runs:
        team = run["team"]

        if not team:
            continue

        all_runs[team].append(run["count"])

        if run["count"] >= 2:
            summary[team]["runs_2_plus"] += 1
        if run["count"] >= 3:
            summary[team]["runs_3_plus"] += 1
        if run["count"] >= 4:
            summary[team]["runs_4_plus"] += 1

        summary[team]["games_with_runs"] += 1

    for team, counts in all_runs.items():
        summary[team]["longest_run"] = max(counts)
        summary[team]["average_run"] = round(
            mean(counts),
            2,
        )

    return dict(summary)


# ============================================================================
# Trends
# ============================================================================

def build_team_trends(
    games: list,
    my_team_keyword: str = "knss",
) -> dict:
    """
    Splits season into chronological game-to-game trends.

    Also reports first-half vs second-half of the available season.
    """
    result = {}

    for game in games:
        match = game["match"]

        for team in (
            match["home_team"],
            match["away_team"],
        ):
            if not team_matches_keyword(
                team,
                my_team_keyword,
            ):
                continue

            gf, ga, opponent, side = get_team_game_values(
                match,
                team,
            )

            result.setdefault(team, []).append({
                "date": match.get("date"),
                "opponent": opponent,
                "gf": gf,
                "ga": ga,
                "diff": gf - ga,
                "result": (
                    "W" if gf > ga
                    else "L" if gf < ga
                    else "D"
                ),
            })

    for team, logs in result.items():
        logs.sort(key=lambda x: str(x["date"] or ""))

        midpoint = max(1, len(logs) // 2)

        first_half = logs[:midpoint]
        second_half = logs[midpoint:]

        def summarize(rows):
            wins = sum(x["result"] == "W" for x in rows)
            losses = sum(x["result"] == "L" for x in rows)
            draws = sum(x["result"] == "D" for x in rows)
            gf = sum(x["gf"] for x in rows)
            ga = sum(x["ga"] for x in rows)

            return {
                "games": len(rows),
                "wins": wins,
                "losses": losses,
                "draws": draws,
                "goals_for": gf,
                "goals_against": ga,
                "goal_diff": gf - ga,
                "goals_for_per_game": safe_rate(
                    gf,
                    len(rows),
                ),
                "goals_against_per_game": safe_rate(
                    ga,
                    len(rows),
                ),
                "win_pct": safe_pct(
                    wins,
                    len(rows),
                ),
            }

        first = summarize(first_half)
        second = summarize(second_half)

        result[team] = {
            "game_log": logs,
            "first_half": first,
            "second_half": second,
            "win_pct_change": (
                round(
                    (second["win_pct"] or 0)
                    - (first["win_pct"] or 0),
                    1,
                )
            ),
            "gf_per_game_change": round(
                second["goals_for_per_game"]
                - first["goals_for_per_game"],
                2,
            ),
            "ga_per_game_change": round(
                second["goals_against_per_game"]
                - first["goals_against_per_game"],
                2,
            ),
        }

    return result


def build_recent_form(
    games: list,
    my_team_keyword: str = "knss",
    n: int = 5,
) -> dict:
    trends = build_team_trends(
        games,
        my_team_keyword,
    )

    result = {}

    for team, data in trends.items():
        recent = data["game_log"][-n:]

        wins = sum(
            x["result"] == "W"
            for x in recent
        )

        losses = sum(
            x["result"] == "L"
            for x in recent
        )

        draws = sum(
            x["result"] == "D"
            for x in recent
        )

        gf = sum(x["gf"] for x in recent)
        ga = sum(x["ga"] for x in recent)

        result[team] = {
            "games": len(recent),
            "wins": wins,
            "losses": losses,
            "draws": draws,
            "goals_for": gf,
            "goals_against": ga,
            "goal_diff": gf - ga,
            "win_pct": safe_pct(
                wins,
                len(recent),
            ),
            "goals_for_per_game": safe_rate(
                gf,
                len(recent),
            ),
            "goals_against_per_game": safe_rate(
                ga,
                len(recent),
            ),
            "results": [x["result"] for x in recent],
        }

    return result


# ============================================================================
# Team performance with / without players
# ============================================================================

def build_team_with_without_players(
    games: list,
    my_team_keyword: str = "knss",
) -> list:
    """
    Explicit with/without table.

    "With" means player appears in the roster for that game.
    "Without" means the player does not appear in that team's roster.
    """
    impact = build_player_impact(
        games,
        my_team_keyword,
    )

    return [
        {
            "player": x["player"],
            "team": x["team"],
            "with_games": x["games_present"],
            "without_games": x["games_absent"],
            "with_win_pct": x["win_pct_present"],
            "without_win_pct": x["win_pct_absent"],
            "win_pct_difference": x["win_pct_delta"],
            "with_goal_diff_per_game": x[
                "goal_diff_per_game_present"
            ],
            "without_goal_diff_per_game": x[
                "goal_diff_per_game_absent"
            ],
        }
        for x in impact
    ]


# ============================================================================
# Opponent breakdown - existing function
# ============================================================================

def build_opponent_breakdown(
    games: list,
    my_team_keyword: str = "knss",
) -> dict:
    breakdown = defaultdict(lambda: {
        "games_played": 0,
        "wins": 0,
        "losses": 0,
        "draws": 0,
        "goals_for": 0,
        "goals_against": 0,
    })

    for game in games:
        match = game["match"]
        home = match["home_team"]
        away = match["away_team"]
        hs = match["home_score"]
        aws = match["away_score"]

        home_is_mine = team_matches_keyword(
            home,
            my_team_keyword,
        )
        away_is_mine = team_matches_keyword(
            away,
            my_team_keyword,
        )

        if home_is_mine and not away_is_mine:
            opponent, gf, ga = away, hs, aws
        elif away_is_mine and not home_is_mine:
            opponent, gf, ga = home, aws, hs
        else:
            continue

        rec = breakdown[opponent]

        rec["games_played"] += 1
        rec["goals_for"] += gf
        rec["goals_against"] += ga

        if gf > ga:
            rec["wins"] += 1
        elif gf < ga:
            rec["losses"] += 1
        else:
            rec["draws"] += 1

    for rec in breakdown.values():
        rec["goal_diff"] = (
            rec["goals_for"] - rec["goals_against"]
        )

        rec["win_pct"] = safe_pct(
            rec["wins"],
            rec["games_played"],
        )

    return dict(
        sorted(
            breakdown.items(),
            key=lambda kv: kv[1]["goals_for"],
            reverse=True,
        )
    )


# ============================================================================
# Season overview
# ============================================================================

def build_season_overview(
    games: list,
    my_team_keyword: str = "knss",
) -> dict:
    teams = build_team_season_stats(games)

    target = {}

    for name, rec in teams.items():
        if team_matches_keyword(
            name,
            my_team_keyword,
        ):
            target[name] = rec

    if not target:
        target = teams

    result = {}

    for team, rec in target.items():
        logs = rec["game_log"]

        margins = [
            abs(
                x["goals_for"] - x["goals_against"]
            )
            for x in logs
        ]

        win_streak = longest_value_streak(
            [x["result"] for x in logs],
            lambda x: x == "W",
        )

        unbeaten_streak = longest_value_streak(
            [x["result"] for x in logs],
            lambda x: x in ("W", "D"),
        )

        result[team] = {
            "games": rec["games_played"],
            "wins": rec["wins"],
            "losses": rec["losses"],
            "draws": rec["draws"],
            "goals_for": rec["goals_for"],
            "goals_against": rec["goals_against"],
            "goal_diff": rec["goal_diff"],
            "goals_for_per_game": rec[
                "goals_for_per_game"
            ],
            "goals_against_per_game": rec[
                "goals_against_per_game"
            ],
            "win_pct": safe_pct(
                rec["wins"],
                rec["games_played"],
            ),
            "average_margin": round(
                mean(margins),
                2,
            ) if margins else 0,
            "largest_win": max(
                (
                    x["goals_for"] - x["goals_against"]
                    for x in logs
                    if x["goals_for"] > x["goals_against"]
                ),
                default=0,
            ),
            "largest_loss": min(
                (
                    x["goals_for"] - x["goals_against"]
                    for x in logs
                    if x["goals_for"] < x["goals_against"]
                ),
                default=0,
            ),
            "longest_win_streak": win_streak["length"],
            "longest_unbeaten_streak": unbeaten_streak["length"],
        }

    return result


# ============================================================================
# Printed reports
# ============================================================================

def print_player_report(name: str, rec: dict) -> None:
    print("=" * 40)
    print(f"PLAYER: {name}  [{rec['team']}]")
    print("=" * 40)
    print(f"Games:             {rec['games_played']}")
    print(f"Goals:             {rec['goals']}")
    print(f"Assists:           {rec['assists']}")
    print(f"Points:            {rec['points']}")
    print()
    print(f"Goals / game:      {rec['goals_per_game']}")
    print(f"Assists / game:    {rec['assists_per_game']}")
    print(f"Points / game:     {rec['points_per_game']}")
    print()
    print(f"Penalty minutes:   {rec['penalty_minutes']}")
    print(
        "(Per-player shot/shooting-% stats are not published "
        "by the source for individual players.)"
    )
    print()


def print_player_season_report(
    players: dict,
    top_n: int = 15,
) -> None:
    print("\n" + "#" * 60)
    print("  PLAYER SEASON LEADERS (by points)")
    print("#" * 60 + "\n")

    for name, rec in list(players.items())[:top_n]:
        print_player_report(name, rec)


def print_team_report(name: str, rec: dict) -> None:
    print("=" * 40)
    print(f"TEAM: {name}")
    print("=" * 40)
    print(f"Games:             {rec['games_played']}")
    print(
        f"Record:            "
        f"{rec['wins']}W - {rec['losses']}L - {rec['draws']}D"
    )
    print(f"Points:            {rec['standings_points']}")
    print()
    print(f"Goals for:         {rec['goals_for']}")
    print(f"Goals against:     {rec['goals_against']}")
    print(f"Goal diff:         {rec['goal_diff']:+d}")
    print()

    if rec["shots_for"] or rec["shots_against"]:
        pct = (
            round(
                100 * rec["goals_for"] / rec["shots_for"],
                1,
            )
            if rec["shots_for"]
            else None
        )

        if pct is not None:
            print(
                f"Shots for:         {rec['shots_for']} "
                f"(shooting {pct}%)"
            )
        else:
            print(
                f"Shots for:         {rec['shots_for']}"
            )

        print(
            f"Shots against:     {rec['shots_against']}"
        )

    print()


def print_team_season_report(teams: dict) -> None:
    print("\n" + "#" * 60)
    print("  TEAM STANDINGS")
    print("#" * 60 + "\n")

    for name, rec in teams.items():
        print_team_report(name, rec)


def print_season_assist_network(
    network: dict,
    top_n: int = 15,
) -> None:
    print("\n" + "#" * 60)
    print("  SEASON ASSIST -> GOAL PAIRS")
    print("#" * 60 + "\n")

    for pair in network["top_pairs"][:top_n]:
        print(
            f"  {pair['assist_by']} -> {pair['goal_by']} "
            f"({pair['times']}x) [{pair['team']}]"
        )


def print_season_discipline(
    discipline: list,
    top_n: int = 15,
) -> None:
    print("\n" + "#" * 60)
    print("  SEASON DISCIPLINE")
    print("#" * 60 + "\n")

    for d in discipline[:top_n]:
        print(
            f"  {d['player']} [{d['team']}]: "
            f"{d['infractions']} infractions, "
            f"{d['total_minutes']} min total"
        )


def print_opponent_breakdown(
    breakdown: dict,
) -> None:
    print("\n" + "#" * 60)
    print("  RECORD BY OPPONENT")
    print("#" * 60 + "\n")

    for opponent, r in breakdown.items():
        print(
            f"  {opponent}: "
            f"{r['wins']}W-{r['losses']}L-{r['draws']}D  "
            f"GF {r['goals_for']}  "
            f"GA {r['goals_against']}  "
            f"Diff {r['goal_diff']:+d}"
        )


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Aggregate season stats from parsed match JSON files."
        )
    )

    parser.add_argument(
        "games_dir",
        help="Folder containing parsed game JSON files",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help=(
            "Write player_season_stats.json, "
            "team_season_stats.json and season_highlights.json"
        ),
    )

    parser.add_argument(
        "--player",
        help="Print only this player's season profile",
    )

    parser.add_argument(
        "--team",
        help="Print only this team's season profile",
    )

    parser.add_argument(
        "--top",
        type=int,
        default=15,
        help="How many players to show",
    )

    parser.add_argument(
        "--my-team",
        default="knss",
        help="Keyword identifying our team",
    )

    args = parser.parse_args()

    games = load_games(args.games_dir)

    if not games:
        print(
            f"No .json game files found in {args.games_dir}"
        )
        return

    players = build_player_season_stats(games)
    teams = build_team_season_stats(games)

    assist_network = build_season_assist_network(games)
    discipline = build_season_discipline(games)
    opponents = build_opponent_breakdown(
        games,
        args.my_team,
    )

    highlights = {
        "season_overview": build_season_overview(
            games,
            args.my_team,
        ),
        "player_consistency": build_player_consistency(
            games,
        ),
        "player_streaks": build_player_streaks(
            games,
        ),
        "scoring_contribution": build_scoring_contribution(
            games,
            args.my_team,
        ),
        "player_win_loss_performance": (
            build_player_win_loss_performance(games)
        ),
        "player_impact": build_player_impact(
            games,
            args.my_team,
        ),
        "team_with_without_players": (
            build_team_with_without_players(
                games,
                args.my_team,
            )
        ),
        "opponent_player_performance": (
            build_opponent_player_performance(
                games,
                args.my_team,
            )
        ),
        "goal_scoring_combinations": (
            build_goal_scoring_combinations(games)
        ),
        "player_discipline": build_player_discipline(
            games,
        ),
        "penalties_followed_by_conceded_goals": (
            build_penalties_followed_by_conceded_goals(
                games,
            )
        ),
        "first_last_scoring_impact": (
            build_first_last_scoring_impact(
                games,
                args.my_team,
            )
        ),
        "close_game_performance": (
            build_close_game_performance(
                games,
                args.my_team,
            )
        ),
        "scoring_runs": build_scoring_runs(
            games,
            args.my_team,
        ),
        "scoring_run_summary": (
            build_season_scoring_run_summary(
                games,
                args.my_team,
            )
        ),
        "team_trends": build_team_trends(
            games,
            args.my_team,
        ),
        "recent_form": build_recent_form(
            games,
            args.my_team,
        ),
        "reliability": build_player_reliability(
            games,
        ),
        "game_to_game_variation": (
            build_game_to_game_variation(games)
        ),
        "assist_network": assist_network,
        "discipline": discipline,
        "opponent_breakdown": opponents,
    }

    if args.json:
        parent_dir = (
            os.path.dirname(
                os.path.normpath(args.games_dir)
            )
            or "."
        )

        player_out = os.path.join(
            parent_dir,
            "player_season_stats.json",
        )

        team_out = os.path.join(
            parent_dir,
            "team_season_stats.json",
        )

        highlights_out = os.path.join(
            parent_dir,
            "season_highlights.json",
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

        with open(
            highlights_out,
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(
                highlights,
                f,
                ensure_ascii=False,
                indent=2,
            )

        print(f"Aggregated {len(games)} game(s).")
        print(f"Wrote {player_out}")
        print(f"Wrote {team_out}")
        print(f"Wrote {highlights_out}")
        return

    if args.player:
        key = player_key(args.player)

        if key in players:
            print_player_report(
                key,
                players[key],
            )
        else:
            print(
                f"No player found matching '{args.player}'. "
                f"Known players: "
                f"{', '.join(list(players)[:10])}..."
            )

        return

    if args.team:
        if args.team in teams:
            print_team_report(
                args.team,
                teams[args.team],
            )
        else:
            print(
                f"No team found matching '{args.team}'. "
                f"Known teams: {', '.join(teams)}"
            )

        return

    print(
        f"Aggregated {len(games)} game(s) "
        f"from {args.games_dir}\n"
    )

    print_team_season_report(teams)
    print_player_season_report(
        players,
        top_n=args.top,
    )
    print_season_assist_network(
        assist_network,
        top_n=args.top,
    )
    print_season_discipline(
        discipline,
        top_n=args.top,
    )
    print_opponent_breakdown(opponents)


if __name__ == "__main__":
    main()