import json

from analysis.game_stats import analyze_player


with open("data/sample_match.json", "r") as file:
    data = json.load(file)


for player in data["players"]:
    result = analyze_player(player)

    print()
    print("=" * 40)
    print(player["name"])
    print("=" * 40)

    print(f"Goals: {player['goals']}")
    print(f"Assists: {player['assists']}")
    print(f"Points: {result['points']}")
    print(f"Shot accuracy: {result['shot_accuracy']:.1f}%")
    print(f"Pass accuracy: {result['pass_accuracy']:.1f}%")
    print(f"Points / 60 min: {result['points_per_60']:.1f}")