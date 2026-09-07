import cv2
import pandas as pd
import numpy as np
from pathlib import Path

# ============================================================
# CONFIG
# ============================================================

INPUT_CSV = "tracking.csv"
VIDEO = "match.webm"

OUTPUT_CSV = "ocr_candidates.csv"
CROPS_DIR = "ocr_crops"

# How many candidate frames to keep per player track
MAX_CANDIDATES_PER_TRACK = 30

# Minimum YOLO confidence
MIN_CONFIDENCE = 0.50

# Minimum player box dimensions
MIN_BOX_WIDTH = 40
MIN_BOX_HEIGHT = 80

# Ignore boxes touching the image border by this many pixels
EDGE_MARGIN = 5

# Save the actual crops for inspection/OCR
SAVE_CROPS = True

# ============================================================
# LOAD TRACKING DATA
# ============================================================

df = pd.read_csv(INPUT_CSV)

required_columns = [
    "frame",
    "track_id",
    "x1",
    "y1",
    "x2",
    "y2",
    "confidence",
]

missing = [c for c in required_columns if c not in df.columns]

if missing:
    raise RuntimeError(
        "tracking.csv is missing required columns: "
        + ", ".join(missing)
        + "\n\n"
        "You need to rerun tracking with x1, y1, x2, y2 saved."
    )

# ============================================================
# VIDEO INFO
# ============================================================

cap = cv2.VideoCapture(VIDEO)

if not cap.isOpened():
    raise RuntimeError(f"Could not open video: {VIDEO}")

video_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
video_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

print(f"Video: {video_width} x {video_height}")
print(f"Tracking rows: {len(df)}")
print(f"Tracks: {df['track_id'].nunique()}")

# ============================================================
# CALCULATE QUALITY FEATURES
# ============================================================

df["box_width"] = df["x2"] - df["x1"]
df["box_height"] = df["y2"] - df["y1"]
df["box_area"] = df["box_width"] * df["box_height"]

# Player aspect ratio.
# Very extreme ratios are usually partial/bad detections.
df["aspect_ratio"] = df["box_height"] / df["box_width"].replace(0, np.nan)

# Normalized size. Larger players generally give OCR more pixels.
df["area_ratio"] = df["box_area"] / (video_width * video_height)

# Distance from the closest image edge.
df["edge_distance"] = df.apply(
    lambda r: min(
        r["x1"],
        r["y1"],
        video_width - r["x2"],
        video_height - r["y2"],
    ),
    axis=1,
)

# ============================================================
# BASIC FILTERING
# ============================================================

candidates = df[
    (df["confidence"] >= MIN_CONFIDENCE)
    & (df["box_width"] >= MIN_BOX_WIDTH)
    & (df["box_height"] >= MIN_BOX_HEIGHT)
    & (df["edge_distance"] >= EDGE_MARGIN)
].copy()

# Reject extremely unusual player-box shapes.
candidates = candidates[
    (candidates["aspect_ratio"] >= 1.0)
    & (candidates["aspect_ratio"] <= 5.0)
].copy()

print(f"After basic filtering: {len(candidates)} detections")

# ============================================================
# QUALITY SCORE
# ============================================================
#
# We want:
#   - high detector confidence
#   - large player crop
#   - reasonable box shape
#   - player away from image edges
#
# This is NOT OCR yet.
# It simply chooses promising frames to send to OCR.
# ============================================================

# Confidence contribution: 0-1
conf_score = candidates["confidence"].clip(0, 1)

# Size score.
# Saturates around a reasonably large player crop.
size_score = np.sqrt(
    candidates["area_ratio"] / 0.05
).clip(0, 1)

# Aspect ratio score.
# Typical player boxes are roughly 1.5-3.5 in height/width.
aspect_score = 1 - (
    abs(candidates["aspect_ratio"] - 2.3) / 2.3
).clip(0, 1)

# Edge score.
# Prefer players comfortably inside the frame.
edge_score = (
    candidates["edge_distance"] / 100.0
).clip(0, 1)

# Combined score.
candidates["quality_score"] = (
    0.40 * conf_score
    + 0.35 * size_score
    + 0.20 * aspect_score
    + 0.05 * edge_score
)

# ============================================================
# SELECT BEST FRAMES PER TRACK
# ============================================================

candidates = candidates.sort_values(
    ["track_id", "quality_score"],
    ascending=[True, False],
)

selected = (
    candidates
    .groupby("track_id", group_keys=False)
    .head(MAX_CANDIDATES_PER_TRACK)
    .copy()
)

print(f"Selected candidates: {len(selected)}")
print(
    f"Average candidates per track: "
    f"{len(selected) / selected['track_id'].nunique():.1f}"
)

# ============================================================
# SAVE CROPS  (single sequential pass over the video)
# ============================================================
#
# IMPORTANT: cv2.CAP_PROP_POS_FRAMES seeking is unreliable on
# compressed formats like webm (it snaps to the nearest keyframe,
# not the exact frame). Instead of seeking per-row, we decode the
# video sequentially exactly once, from frame 0 to the highest
# needed frame number, and grab a frame only when it's actually
# needed. This guarantees the pixels we crop match the coordinates
# the tracker computed for that frame.
# ============================================================

if SAVE_CROPS:
    Path(CROPS_DIR).mkdir(parents=True, exist_ok=True)

    print("\nSaving candidate crops (sequential pass)...")

    # Sort globally by frame number (not per-track) so the single
    # forward pass only has to move forward, never backward.
    selected_by_frame = selected.sort_values("frame").reset_index(drop=True)

    # Group all rows that need a crop from the same frame together,
    # so we only decode/store each frame once.
    rows_by_frame = selected_by_frame.groupby("frame")

    needed_frames = set(selected_by_frame["frame"].astype(int))
    max_needed_frame = max(needed_frames)

    saved_count = 0
    frame_number = 0

    while frame_number <= max_needed_frame:

        success, frame_image = cap.read()

        if not success:
            print(f"Warning: video ended early at frame {frame_number}")
            break

        if frame_number in needed_frames:

            rows = rows_by_frame.get_group(frame_number)

            for _, row in rows.iterrows():

                x1 = max(0, int(row["x1"]))
                y1 = max(0, int(row["y1"]))
                x2 = min(video_width, int(row["x2"]))
                y2 = min(video_height, int(row["y2"]))

                crop = frame_image[y1:y2, x1:x2]

                if crop.size == 0:
                    continue

                track_id = int(row["track_id"])

                track_dir = Path(CROPS_DIR) / f"track_{track_id:04d}"
                track_dir.mkdir(parents=True, exist_ok=True)

                filename = (
                    f"frame_{frame_number:06d}"
                    f"_score_{row['quality_score']:.3f}.jpg"
                )

                cv2.imwrite(str(track_dir / filename), crop)
                saved_count += 1

                if saved_count % 500 == 0:
                    print(f"Saved {saved_count} crops")

        frame_number += 1

    print(f"Total crops saved: {saved_count}")

# Sort chronologically for easier inspection in the CSV.
selected = selected.sort_values(["track_id", "frame"]).reset_index(drop=True)

# ============================================================
# SAVE CSV
# ============================================================

selected.to_csv(OUTPUT_CSV, index=False)

cap.release()

print("\n========================================")
print("Finished.")
print("========================================")
print(f"Candidate CSV: {OUTPUT_CSV}")
print(f"Crop directory: {CROPS_DIR}/")
print(f"Tracks represented: {selected['track_id'].nunique()}")
print(f"Candidate detections: {len(selected)}")

# Show distribution.
counts = selected.groupby("track_id").size()

print("\nCandidates per track:")
print(counts.describe())

print("\nNext step:")
print("1. Inspect some folders inside ocr_crops/")
print("2. Confirm the jersey is visible in useful crops")
print("3. Then preprocess the number region")
print("4. Then run OCR and aggregate results by track_id")