import pandas as pd

TRACKING_CSV = "tracking.csv"
STATS_CSV = "player_statistics.csv"

FILTERED_TRACKING_CSV = "tracking_filtered.csv"
FILTERED_STATS_CSV = "player_statistics_filtered.csv"

# Minimum number of frames a track must appear in to be kept.
# Tune this after looking at the histogram printed below.
MIN_FRAMES = 10

# Load raw tracking data (frame-by-frame detections)
df = pd.read_csv(TRACKING_CSV)

if df.empty:
    raise RuntimeError("tracking.csv is empty.")

# Load existing per-track stats (from your player_statistics.py output)
stats = pd.read_csv(STATS_CSV)

if stats.empty:
    raise RuntimeError("player_statistics.csv is empty.")

# --- Inspect the distribution before picking a cutoff ---
print("Distribution of frames_detected per track_id:")
print(stats["frames_detected"].describe())
print()

bins = [0, 5, 10, 20, 50, 100, 200, 500, stats["frames_detected"].max() + 1]
print("Track count by frame-count bucket:")
print(pd.cut(stats["frames_detected"], bins=bins).value_counts().sort_index())
print()

# --- Apply the filter ---
before_tracks = stats["track_id"].nunique()
before_rows = len(df)

keep_ids = stats.loc[stats["frames_detected"] >= MIN_FRAMES, "track_id"]

stats_filtered = stats[stats["track_id"].isin(keep_ids)].copy()
df_filtered = df[df["track_id"].isin(keep_ids)].copy()

after_tracks = stats_filtered["track_id"].nunique()
after_rows = len(df_filtered)

# --- Save results ---
#df_filtered.to_csv(FILTERED_TRACKING_CSV, index=False)
stats_filtered.to_csv(FILTERED_STATS_CSV, index=False)

print(f"MIN_FRAMES threshold: {MIN_FRAMES}")
print()
print(f"Tracks: {before_tracks} -> {after_tracks} "
      f"(removed {before_tracks - after_tracks})")
print(f"Detection rows: {before_rows} -> {after_rows} "
      f"(removed {before_rows - after_rows})")
print()
print(f"Saved filtered tracking data to: {FILTERED_TRACKING_CSV}")
print(f"Saved filtered stats to: {FILTERED_STATS_CSV}")