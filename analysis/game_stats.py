"""
Compute coach-relevant stats for a single parsed match JSON (output of parse_match.py).

Usage:
    python game_stats.py data/games/2025-09-27_knss-saulkalne.json
    python game_stats.py data/games/2025-09-27_knss-saulkalne.json --json   (raw JSON instead of report)
"""

import json
import re
import sys
from collections import Counter, defaultdict


# ---------- helpers ----------

def time_to_seconds(t: str) -> int:
    m, s = t.split(":")
    return int(m) * 60 + int(s)


def seconds_to_time(sec: int) -> str:
    sec = max(0, int(sec))
    return f"{sec // 60:02d}:{sec % 60:02d}"


def shooting_pct(goals: int, shots: int) -> float:
    return round(100 * goals / shots, 1) if shots else 0.0


def team_name_for_side(match: dict, side: str) -> str:
    return match["home_team"] if side == "home" else match["away_team"]


# ---------- individual stat builders ----------

def basic_leaders(rosters: dict) -> dict:
    all_players = []
    for team_name, players in rosters.items():
        for p in players:
            if "staff" in p:
                continue
            all_players.append({**p, "team": team_name})

    scorers = sorted(
        (p for p in all_players if (p["points"] or 0) > 0),
        key=lambda p: p["points"], reverse=True,
    )
    penalized = sorted(
        (p for p in all_players if p["penalty_minutes"]),
        key=lambda p: p["name"],
    )
    return {"top_scorers": scorers[:5], "penalties": penalized}


def shots_summary(goals_shots: list) -> dict:
    summary = {}
    for row in goals_shots:
        total = row["by_period"].get("Kopā") or row["by_period"].get("Total")
        by_period = {k: v for k, v in row["by_period"].items() if k not in ("Kopā", "Total")}
        summary[row["team"]] = {
            "goals": total["goals"] if total else None,
            "shots": total["shots"] if total else None,
            "shooting_pct": shooting_pct(total["goals"], total["shots"]) if total else None,
            "by_period": {
                label: {**v, "shooting_pct": shooting_pct(v["goals"], v["shots"])}
                for label, v in by_period.items()
            },
        }
    return summary


NON_GOAL_TYPES_WITH_SCORE = {"Spēles beigas", "Perioda beigas"}


def goal_events(events: list) -> list:
    """Events that actually represent a goal being scored (have a 'X - Y' score
    field, excluding the final/period-end summary rows which also carry the
    running score but aren't a scoring play themselves)."""
    return [
        e for e in events
        if e.get("score") and e["type"] not in NON_GOAL_TYPES_WITH_SCORE
    ]


def penalty_events(events: list) -> list:
    return [e for e in events if e["type"] == "Sods"]


def time_to_first_and_last_goal(events: list) -> dict:
    goals = goal_events(events)
    if not goals:
        return {"first_goal": None, "last_goal": None}
    return {
        "first_goal": {"time": goals[0]["time"], "side": goals[0]["side"], "detail": goals[0]["detail"]},
        "last_goal": {"time": goals[-1]["time"], "side": goals[-1]["side"], "detail": goals[-1]["detail"]},
    }


def scoring_runs(events: list, match: dict) -> dict:
    """Longest streak of consecutive goals by one side without reply."""
    goals = goal_events(events)
    if not goals:
        return {"longest_run": None}

    best = {"side": None, "count": 0, "start_time": None, "end_time": None}
    current_side, current_count, current_start = None, 0, None

    for g in goals:
        if g["side"] == current_side:
            current_count += 1
        else:
            current_side, current_count, current_start = g["side"], 1, g["time"]
        if current_count > best["count"]:
            best = {"side": current_side, "count": current_count,
                    "start_time": current_start, "end_time": g["time"]}

    if best["side"]:
        best["team"] = team_name_for_side(match, best["side"])
    return {"longest_run": best}


def goals_by_time_bucket(events: list, match: dict, bucket_minutes: int = 5) -> dict:
    goals = goal_events(events)
    buckets = defaultdict(lambda: {"home": 0, "away": 0})
    for g in goals:
        sec = time_to_seconds(g["time"])
        bucket_start = (sec // (bucket_minutes * 60)) * bucket_minutes
        label = f"{bucket_start}-{bucket_start + bucket_minutes} min"
        if g["side"] in ("home", "away"):
            buckets[label][g["side"]] += 1

    ordered = dict(sorted(buckets.items(), key=lambda kv: int(kv[0].split("-")[0])))
    return {
        "bucket_minutes": bucket_minutes,
        "home_team": match["home_team"],
        "away_team": match["away_team"],
        "buckets": ordered,
    }


def parse_penalty_minutes(detail: str) -> int:
    m = re.search(r"(\d+)\s*min", detail)
    return int(m.group(1)) if m else 0


def power_play_stats(events: list, match: dict) -> dict:
    penalties = penalty_events(events)
    pp_goals = [e for e in goal_events(events) if "vairākumā" in e["type"].lower()]

    home_penalties = [e for e in penalties if e["side"] == "home"]
    away_penalties = [e for e in penalties if e["side"] == "away"]
    home_pp_goals = [e for e in pp_goals if e["side"] == "home"]
    away_pp_goals = [e for e in pp_goals if e["side"] == "away"]

    def pct(goals, opp_penalties):
        return round(100 * len(goals) / len(opp_penalties), 1) if opp_penalties else None

    home_pk = pct(away_pp_goals, home_penalties)
    away_pk = pct(home_pp_goals, away_penalties)

    return {
        "note": "Power-play opportunities are approximated as the opponent's penalty count "
                "(doesn't account for overlapping/stacked penalties).",
        match["home_team"]: {
            "penalties_taken": len(home_penalties),
            "total_penalty_minutes": sum(parse_penalty_minutes(e["detail"]) for e in home_penalties),
            "power_play_goals": len(home_pp_goals),
            "power_play_opportunities": len(away_penalties),
            "power_play_pct": pct(home_pp_goals, away_penalties),
            "penalty_kill_pct": round(100 - home_pk, 1) if home_pk is not None else None,
        },
        match["away_team"]: {
            "penalties_taken": len(away_penalties),
            "total_penalty_minutes": sum(parse_penalty_minutes(e["detail"]) for e in away_penalties),
            "power_play_goals": len(away_pp_goals),
            "power_play_opportunities": len(home_penalties),
            "power_play_pct": pct(away_pp_goals, home_penalties),
            "penalty_kill_pct": round(100 - away_pk, 1) if away_pk is not None else None,
        },
    }


def penalty_discipline_timing(events: list, match: dict, thirds_minutes: int = 20) -> dict:
    """Bucket penalties into game thirds (default = periods) to spot discipline patterns."""
    penalties = penalty_events(events)
    buckets = defaultdict(lambda: defaultdict(int))
    for e in penalties:
        sec = time_to_seconds(e["time"])
        third = sec // (thirds_minutes * 60) + 1
        label = f"Period {third}"
        if e["side"] in ("home", "away"):
            buckets[label][e["side"]] += 1

    return {
        "home_team": match["home_team"],
        "away_team": match["away_team"],
        "by_period": {k: dict(v) for k, v in sorted(buckets.items())},
    }


ASSIST_RE = re.compile(r"^#\d+\s+(?P<scorer>.+?)\s*(?:\((?P<assists>.+)\))?$")
ASSIST_NAME_RE = re.compile(r"#\d+\s+([^,]+)")


def assist_network(events: list) -> dict:
    """Who assists whom most often - reveals real on-ice chemistry."""
    pairs = Counter()
    unassisted = Counter()

    for e in goal_events(events):
        detail = e["detail"]
        # Skip penalty-shot lines like "(#99 Name) realizēts soda metiens" - no assist structure
        if "soda metiens" in detail.lower():
            continue
        m = ASSIST_RE.match(detail)
        if not m:
            continue
        scorer = m.group("scorer").strip()
        assists_blob = m.group("assists")
        if not assists_blob:
            unassisted[scorer] += 1
            continue
        for assist_name in ASSIST_NAME_RE.findall(assists_blob):
            pairs[(assist_name.strip(), scorer)] += 1

    return {
        "top_assist_scorer_pairs": [
            {"assist_by": a, "goal_by": s, "times": n}
            for (a, s), n in pairs.most_common(10)
        ],
        "unassisted_goals": dict(unassisted),
    }


def goalie_workload(events: list) -> list:
    stats = []
    for e in events:
        if e["type"] != "Vārtsarga stat.":
            continue
        m = re.match(
            r"#(\d+)\s+(.+?)\s*-\s*Vārti:\s*(\d+);\s*Metieni:\s*(\d+);\s*Minūtes:\s*(\d+:\d+)",
            e["detail"],
        )
        if not m:
            continue
        number, name, goals_against, shots_faced, minutes = m.groups()
        goals_against, shots_faced = int(goals_against), int(shots_faced)
        saves = shots_faced - goals_against
        stats.append({
            "side": e["side"],
            "number": int(number),
            "name": name,
            "goals_against": goals_against,
            "shots_faced": shots_faced,
            "saves": saves,
            "save_pct": round(100 * saves / shots_faced, 1) if shots_faced else None,
            "minutes_played": minutes,
        })
    return stats


def goalie_changes(events: list, match: dict) -> list:
    changes = []
    for e in events:
        if e["type"] not in ("Vārtos", "Vārtsarga maiņa"):
            continue
        m = re.search(r"#(\d+)\s+(.+)$", e["detail"])
        goalie = m.group(2).strip() if m else e["detail"]
        changes.append({
            "time": e["time"],
            "side": e["side"],
            "team": team_name_for_side(match, e["side"]) if e["side"] in ("home", "away") else None,
            "type": "starts" if e["type"] == "Vārtos" else "change",
            "goalie": goalie,
        })
    return changes


def goals_soon_after_goalie_change(events: list, match: dict, window_seconds: int = 180) -> list:
    """Flag goals scored against a team within `window_seconds` of that team putting in a
    new/changed goalie - useful for spotting a shaky entrance."""
    changes = [c for c in goalie_changes(events, match) if c["type"] == "change"]
    goals = goal_events(events)
    flagged = []
    for c in changes:
        change_sec = time_to_seconds(c["time"])
        conceding_side = c["side"]  # team that changed goalies
        for g in goals:
            if g["side"] and g["side"] != conceding_side:  # opponent scored
                g_sec = time_to_seconds(g["time"])
                if 0 <= g_sec - change_sec <= window_seconds:
                    flagged.append({
                        "goalie_change_time": c["time"],
                        "goalie_in": c["goalie"],
                        "team_conceded": team_name_for_side(match, conceding_side),
                        "goal_against_time": g["time"],
                        "seconds_after_change": g_sec - change_sec,
                    })
    return flagged


def penalty_player_name(detail: str) -> str:
    """Extract the offending player's name from a penalty detail string.
    Works even when someone else serves the time, e.g.
    '#22 Rihards Diūra (12 min; ...) (Sodu izcieš #73 Markuss Salenieks)'
    -> 'Rihards Diūra' (the person actually charged with the penalty)."""
    m = re.match(r"^#\d+\s+(.+?)\s*\(", detail)
    return m.group(1).strip() if m else detail.strip()


def game_length_seconds(events: list) -> int:
    for e in events:
        if e["type"] == "Spēles beigas":
            return time_to_seconds(e["time"])
    return time_to_seconds(events[-1]["time"]) if events else 3600


def score_margin_timeline(events: list) -> list:
    """One entry per goal: running score and which side leads (None = tied)."""
    timeline = []
    for e in goal_events(events):
        try:
            home_s, away_s = (int(x.strip()) for x in e["score"].split("-"))
        except ValueError:
            continue
        margin = home_s - away_s
        leading = "home" if margin > 0 else "away" if margin < 0 else None
        timeline.append({
            "time": e["time"], "home_score": home_s, "away_score": away_s,
            "margin": margin, "leading": leading,
        })
    return timeline


def time_in_each_state(events: list, match: dict) -> dict:
    """How many seconds of the game each team spent leading, plus time tied."""
    timeline = score_margin_timeline(events)
    total = game_length_seconds(events)

    home_secs = away_secs = tied_secs = 0
    prev_time, prev_state = 0, None  # 0-0 start = tied
    for entry in timeline:
        t = time_to_seconds(entry["time"])
        dur = max(0, t - prev_time)
        if prev_state == "home":
            home_secs += dur
        elif prev_state == "away":
            away_secs += dur
        else:
            tied_secs += dur
        prev_time, prev_state = t, entry["leading"]

    dur = max(0, total - prev_time)
    if prev_state == "home":
        home_secs += dur
    elif prev_state == "away":
        away_secs += dur
    else:
        tied_secs += dur

    return {
        match["home_team"]: {"leading_seconds": home_secs, "leading_time": seconds_to_time(home_secs)},
        match["away_team"]: {"leading_seconds": away_secs, "leading_time": seconds_to_time(away_secs)},
        "tied_seconds": tied_secs,
        "tied_time": seconds_to_time(tied_secs),
        "total_seconds": total,
    }


def longest_droughts(events: list, match: dict) -> dict:
    """Longest gap without a goal, per team (including from kickoff to their
    first goal, and from their last goal to the final whistle)."""
    total = game_length_seconds(events)
    result = {}
    for side in ("home", "away"):
        times = [0] + [time_to_seconds(e["time"]) for e in goal_events(events) if e["side"] == side] + [total]
        gaps = [(times[i + 1] - times[i], times[i], times[i + 1]) for i in range(len(times) - 1)]
        longest = max(gaps, key=lambda g: g[0]) if gaps else (0, 0, 0)
        team = team_name_for_side(match, side)
        result[team] = {
            "longest_drought_seconds": longest[0],
            "longest_drought": seconds_to_time(longest[0]),
            "from_time": seconds_to_time(longest[1]),
            "to_time": seconds_to_time(longest[2]),
        }
    return result


def penalties_with_score_context(events: list, match: dict) -> list:
    """For every penalty, what the score situation was for the penalized team
    at that moment (leading/trailing/tied and by how much)."""
    timeline = score_margin_timeline(events)
    results = []
    for pen in penalty_events(events):
        t = time_to_seconds(pen["time"])
        margin = 0
        for entry in timeline:
            if time_to_seconds(entry["time"]) <= t:
                margin = entry["margin"]
            else:
                break

        side = pen["side"]
        team_margin = margin if side == "home" else -margin if side == "away" else 0
        if team_margin > 0:
            situation = f"leading by {team_margin}"
        elif team_margin < 0:
            situation = f"trailing by {abs(team_margin)}"
        else:
            situation = "tied"

        results.append({
            "time": pen["time"],
            "team": team_name_for_side(match, side) if side in ("home", "away") else None,
            "player": penalty_player_name(pen["detail"]),
            "score_situation": situation,
        })
    return results


def retaliation_penalties(events: list, match: dict, window_seconds: int = 60) -> list:
    """Penalties taken shortly after conceding a goal - a common frustration/
    discipline-breakdown signal."""
    goals = goal_events(events)
    flagged = []
    for pen in penalty_events(events):
        pen_t = time_to_seconds(pen["time"])
        side = pen["side"]
        for g in goals:
            if g["side"] and g["side"] != side:
                g_t = time_to_seconds(g["time"])
                if 0 <= pen_t - g_t <= window_seconds:
                    flagged.append({
                        "penalty_time": pen["time"],
                        "team": team_name_for_side(match, side) if side in ("home", "away") else None,
                        "player": penalty_player_name(pen["detail"]),
                        "seconds_after_conceding": pen_t - g_t,
                        "conceded_goal_time": g["time"],
                    })
                    break
    return flagged


def overlapping_penalties(events: list, match: dict) -> list:
    """Time windows where a team had 2+ penalties running at once (e.g. a
    5-on-3), based on the assessed penalty durations. Note: long
    (10+ min) misconduct-type penalties often don't create the same
    numerical disadvantage as a straight minor for their whole length -
    treat these as a heuristic, not an exact ruling."""
    intervals_by_side = defaultdict(list)
    for e in penalty_events(events):
        start = time_to_seconds(e["time"])
        dur = parse_penalty_minutes(e["detail"]) * 60
        intervals_by_side[e["side"]].append((start, start + dur, penalty_player_name(e["detail"])))

    overlaps = []
    for side, intervals in intervals_by_side.items():
        intervals.sort()
        for i in range(len(intervals)):
            for j in range(i + 1, len(intervals)):
                s1, e1, p1 = intervals[i]
                s2, e2, p2 = intervals[j]
                if s2 < e1:
                    overlaps.append({
                        "team_shorthanded": team_name_for_side(match, side) if side in ("home", "away") else None,
                        "players": [p1, p2],
                        "overlap_start": seconds_to_time(max(s1, s2)),
                        "overlap_end": seconds_to_time(min(e1, e2)),
                    })
    return overlaps


def repeat_offenders(events: list, match: dict) -> list:
    """Players penalized 2+ times in this game."""
    counts, minutes, team_of = Counter(), Counter(), {}
    for e in penalty_events(events):
        name = penalty_player_name(e["detail"])
        counts[name] += 1
        minutes[name] += parse_penalty_minutes(e["detail"])
        team_of[name] = team_name_for_side(match, e["side"]) if e["side"] in ("home", "away") else None

    return sorted(
        (
            {"player": name, "team": team_of[name], "infractions": c, "total_minutes": minutes[name]}
            for name, c in counts.items() if c >= 2
        ),
        key=lambda r: r["infractions"], reverse=True,
    )


def quiet_players(rosters: dict) -> list:
    """Players who dressed but recorded zero points - useful for spotting
    over-reliance on a small handful of scorers."""
    quiet = []
    for team, players in rosters.items():
        for p in players:
            if "staff" in p:
                continue
            if (p["points"] or 0) == 0:
                quiet.append({"name": p["name"], "number": p["number"], "team": team})
    return quiet


# ---------- top-level ----------

def game_stats(data: dict) -> dict:
    match = data["match"]
    events = data["events"]
    rosters = data["rosters"]

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

    return {
        "final_score": (
            f"{match['home_team']} "
            f"{match['home_score']} - "
            f"{match['away_score']}{score_suffix} "
            f"{match['away_team']}"
        ),
        **basic_leaders(rosters),
        "shooting": shots_summary(data.get("goals_shots_by_period", [])),
        "goal_timing": time_to_first_and_last_goal(events),
        "scoring_runs": scoring_runs(events, match),
        "goals_by_time_bucket": goals_by_time_bucket(events, match),
        "special_teams": power_play_stats(events, match),
        "penalty_discipline_by_period": penalty_discipline_timing(events, match),
        "assist_network": assist_network(events),
        "goalie_workload": goalie_workload(events),
        "goalie_changes": goalie_changes(events, match),
        "goals_soon_after_goalie_change": goals_soon_after_goalie_change(events, match),
        "score_margin_timeline": score_margin_timeline(events),
        "time_in_each_state": time_in_each_state(events, match),
        "longest_droughts": longest_droughts(events, match),
        "penalties_with_score_context": penalties_with_score_context(events, match),
        "retaliation_penalties": retaliation_penalties(events, match),
        "overlapping_penalties": overlapping_penalties(events, match),
        "repeat_offenders": repeat_offenders(events, match),
        "quiet_players": quiet_players(rosters),
        "referees": data.get("referees"),
        "attendance": data.get("attendance"),
    }


# ---------- human-readable report ----------

def print_report(stats: dict) -> None:
    line = "=" * 60

    print(line)
    print(f"  {stats['final_score']}")
    print(line)

    print("\n--- TOP SCORERS ---")
    for p in stats["top_scorers"]:
        print(f"  {p['points']} pts ({p['goals']}+{p['assists']})  "
              f"#{p['number']} {p['name']}  [{p['team']}]")

    print("\n--- PENALTIES ---")
    if stats["penalties"]:
        for p in stats["penalties"]:
            print(f"  {p['penalty_minutes']:>6}  #{p['number']} {p['name']}  [{p['team']}]")
    else:
        print("  None")

    print("\n--- SHOOTING ---")
    for team, s in stats["shooting"].items():
        print(f"  {team}: {s['goals']}/{s['shots']} shots ({s['shooting_pct']}%)")
        for label, p in s["by_period"].items():
            print(f"      {label}: {p['goals']}/{p['shots']} ({p['shooting_pct']}%)")

    gt = stats["goal_timing"]
    print("\n--- GOAL TIMING ---")
    if gt["first_goal"]:
        print(f"  First goal: {gt['first_goal']['time']} - {gt['first_goal']['detail']}")
        print(f"  Last goal:  {gt['last_goal']['time']} - {gt['last_goal']['detail']}")
    else:
        print("  No goals scored")

    run = stats["scoring_runs"]["longest_run"]
    print("\n--- LONGEST SCORING RUN ---")
    if run and run["side"]:
        print(f"  {run['count']} unanswered goals by {run['team']} "
              f"({run['start_time']} - {run['end_time']})")
    else:
        print("  N/A")

    gb = stats["goals_by_time_bucket"]
    print(f"\n--- GOALS BY {gb['bucket_minutes']}-MIN BUCKET ---")
    print(f"  {'Bucket':<12}{gb['home_team']:<25}{gb['away_team']}")
    for label, counts in gb["buckets"].items():
        print(f"  {label:<12}{counts['home']:<25}{counts['away']}")

    print("\n--- SPECIAL TEAMS (approximate) ---")
    for team, s in stats["special_teams"].items():
        if team == "note":
            continue
        print(f"  {team}:")
        print(f"      Penalties taken: {s['penalties_taken']} "
              f"({s['total_penalty_minutes']} PIM)")
        pp = f"{s['power_play_pct']}%" if s['power_play_pct'] is not None else "N/A"
        pk = f"{s['penalty_kill_pct']}%" if s['penalty_kill_pct'] is not None else "N/A"
        print(f"      Power play: {s['power_play_goals']}/{s['power_play_opportunities']} ({pp})")
        print(f"      Penalty kill: {pk}")

    pd = stats["penalty_discipline_by_period"]
    print("\n--- PENALTIES BY PERIOD ---")
    for period, counts in pd["by_period"].items():
        print(f"  {period}: {pd['home_team']} {counts.get('home', 0)}  |  "
              f"{pd['away_team']} {counts.get('away', 0)}")

    an = stats["assist_network"]
    print("\n--- TOP ASSIST -> GOAL PAIRS ---")
    if an["top_assist_scorer_pairs"]:
        for pair in an["top_assist_scorer_pairs"]:
            print(f"  {pair['assist_by']} -> {pair['goal_by']}  ({pair['times']}x)")
    else:
        print("  None")

    print("\n--- GOALIE WORKLOAD ---")
    for g in stats["goalie_workload"]:
        print(f"  #{g['number']} {g['name']}: {g['saves']}/{g['shots_faced']} saves "
              f"({g['save_pct']}%), {g['minutes_played']} min, {g['goals_against']} GA")

    print("\n--- GOALIE CHANGES ---")
    for c in stats["goalie_changes"]:
        print(f"  {c['time']}  {c['team']}: {c['goalie']} ({c['type']})")

    flagged = stats["goals_soon_after_goalie_change"]
    if flagged:
        print("\n--- GOALS SOON AFTER A GOALIE CHANGE ---")
        for f in flagged:
            print(f"  {f['team_conceded']} changed goalies at {f['goalie_change_time']} "
                  f"({f['goalie_in']}) -> conceded at {f['goal_against_time']} "
                  f"({f['seconds_after_change']}s later)")

    tis = stats["time_in_each_state"]
    print("\n--- TIME LEADING / TRAILING / TIED ---")
    for team, s in tis.items():
        if team in ("tied_seconds", "tied_time", "total_seconds"):
            continue
        print(f"  {team}: leading for {s['leading_time']}")
    print(f"  Tied for: {tis['tied_time']}  (game length {seconds_to_time(tis['total_seconds'])})")

    ld = stats["longest_droughts"]
    print("\n--- LONGEST SCORELESS STRETCH PER TEAM ---")
    for team, d in ld.items():
        print(f"  {team}: {d['longest_drought']}  ({d['from_time']} - {d['to_time']})")

    pc = stats["penalties_with_score_context"]
    print("\n--- PENALTIES IN CONTEXT (score situation at the time) ---")
    if pc:
        for p in pc:
            print(f"  {p['time']}  {p['player']} [{p['team']}] - team was {p['score_situation']}")
    else:
        print("  None")

    rp = stats["retaliation_penalties"]
    print("\n--- POSSIBLE RETALIATION PENALTIES (within 60s of conceding) ---")
    if rp:
        for r in rp:
            print(f"  {r['penalty_time']}  {r['player']} [{r['team']}] - "
                  f"{r['seconds_after_conceding']}s after conceding at {r['conceded_goal_time']}")
    else:
        print("  None")

    op = stats["overlapping_penalties"]
    print("\n--- OVERLAPPING PENALTIES (possible multi-man advantage) ---")
    if op:
        for o in op:
            print(f"  {o['team_shorthanded']} shorthanded {o['overlap_start']}-{o['overlap_end']} "
                  f"({', '.join(o['players'])})")
    else:
        print("  None")

    ro = stats["repeat_offenders"]
    print("\n--- REPEAT OFFENDERS (2+ penalties this game) ---")
    if ro:
        for r in ro:
            print(f"  {r['player']} [{r['team']}]: {r['infractions']} penalties, {r['total_minutes']} min total")
    else:
        print("  None")

    qp = stats["quiet_players"]
    print("\n--- PLAYERS WITH NO POINTS THIS GAME ---")
    if qp:
        by_team = defaultdict(list)
        for p in qp:
            by_team[p["team"]].append(f"#{p['number']} {p['name']}")
        for team, names in by_team.items():
            print(f"  {team}: {', '.join(names)}")
    else:
        print("  Every player who scored a point... (unlikely - check data)")

    print(f"\nReferees: {', '.join(stats['referees']) if stats['referees'] else 'N/A'}")
    print(f"Attendance: {stats['attendance']}")
    print(line)


def main():
    if len(sys.argv) < 2:
        print("Usage: python game_stats.py path/to/game.json [--json]")
        sys.exit(1)

    with open(sys.argv[1], encoding="utf-8") as f:
        data = json.load(f)

    stats = game_stats(data)

    if "--json" in sys.argv:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    else:
        print_report(stats)


if __name__ == "__main__":
    main()