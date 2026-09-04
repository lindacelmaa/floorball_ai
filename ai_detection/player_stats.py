import pandas as pd

INPUT_CSV = "tracking.csv"
OUTPUT_CSV = "player_statistics.csv"

# Load tracking data
df = pd.read_csv(INPUT_CSV)

if df.empty:
    raise RuntimeError("tracking.csv is empty.")

# Calculate statistics for each tracking ID
stats = (
    df.groupby("track_id")
    .agg(
        first_seen=("time", "min"),
        last_seen=("time", "max"),
        frames_detected=("frame", "count"),
    )
    .reset_index()
)

# FPS from the tracking data
fps = 60.0

# Number of frames detected / FPS
stats["time_detected"] = stats["frames_detected"] / fps

# Time between first and last detection
stats["time_span"] = stats["last_seen"] - stats["first_seen"]

# Convert seconds to minutes
stats["time_detected_minutes"] = stats["time_detected"] / 60

# Sort by total detected time
stats = stats.sort_values(
    "time_detected",
    ascending=False
)

# Save results
stats.to_csv(OUTPUT_CSV, index=False)

print()
print("Player statistics:")
print(stats.to_string(index=False))

print()
print(f"Saved statistics to: {OUTPUT_CSV}")
