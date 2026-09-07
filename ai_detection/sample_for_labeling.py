import random
import re
import shutil
from pathlib import Path

CROPS_DIR = "ocr_crops"
OUTPUT_DIR = "labeling_batch"

# How many images to pull per track — spread across a track's saved
# crops rather than always grabbing the single best one, so the
# detector sees a bit of variation (pose, lighting) even within the
# same player.
IMAGES_PER_TRACK = 2

# Overall cap so you're not labeling thousands of images. With ~150-300
# diverse examples you can get a usable single-class detector via
# transfer learning.
MAX_TOTAL_IMAGES = 250

SCORE_PATTERN = re.compile(r"score_([\d.]+)\.jpg$")

Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

track_dirs = sorted(Path(CROPS_DIR).glob("track_*"))

if not track_dirs:
    raise RuntimeError(f"No track folders found under {CROPS_DIR}/")

selected = []

for track_dir in track_dirs:
    images = sorted(track_dir.glob("*.jpg"))
    if not images:
        continue

    # Spread the pick across the track's score range instead of only
    # the top-scoring crop, so labeled examples include some easier
    # and some harder cases from the same player.
    def score_of(path):
        m = SCORE_PATTERN.search(path.name)
        return float(m.group(1)) if m else 0.0

    images_sorted = sorted(images, key=score_of)

    if len(images_sorted) <= IMAGES_PER_TRACK:
        picks = images_sorted
    else:
        # Evenly spaced indices across the sorted list.
        step = len(images_sorted) / IMAGES_PER_TRACK
        picks = [
            images_sorted[int(i * step)] for i in range(IMAGES_PER_TRACK)
        ]

    for p in picks:
        selected.append((track_dir.name, p))

print(f"Tracks available: {len(track_dirs)}")
print(f"Candidate images before cap: {len(selected)}")

if len(selected) > MAX_TOTAL_IMAGES:
    random.seed(42)
    selected = random.sample(selected, MAX_TOTAL_IMAGES)

print(f"Images selected for labeling: {len(selected)}")

for track_name, src_path in selected:
    dest_name = f"{track_name}__{src_path.name}"
    shutil.copy(src_path, Path(OUTPUT_DIR) / dest_name)

print(f"\nCopied {len(selected)} images to: {OUTPUT_DIR}/")
print("Upload this whole folder to Roboflow to start labeling.")