import sys
import pandas as pd

if len(sys.argv) < 2:
    print("Usage: python check_track_stats.py <path_to_tracking_csv>")
    sys.exit(1)

csv_path = sys.argv[1]

df = pd.read_csv(csv_path)

if df.empty:
    raise RuntimeError(f"{csv_path} is empty.")

n_tracks = df["track_id"].nunique()
duration = df["time"].max() - df["time"].min()
avg_track_frames = df.groupby("track_id").size().mean()
median_track_frames = df.groupby("track_id").size().median()

print(f"File: {csv_path}")
print(f"Unique track IDs: {n_tracks}")
print(f"Video duration covered: {duration:.1f}s")
print(f"Avg frames per track: {avg_track_frames:.1f}")
print(f"Median frames per track: {median_track_frames:.1f}")