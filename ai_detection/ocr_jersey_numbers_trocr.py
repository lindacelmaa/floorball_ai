import re
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import torch
from PIL import Image
from transformers import TrOCRProcessor, VisionEncoderDecoderModel

# ============================================================
# CONFIG
# ============================================================

CANDIDATES_CSV = "ocr_candidates.csv"
CROPS_DIR = "ocr_crops"

OUTPUT_CSV = "track_jersey_numbers.csv"

MIN_QUALITY_SCORE_FOR_OCR = 0.70
MAX_CROPS_PER_TRACK_FOR_OCR = 8

# Same torso band used in the EasyOCR version — keeping this identical
# so we're only changing the OCR engine, not the crop assumptions.
TORSO_TOP_FRAC = 0.15
TORSO_BOTTOM_FRAC = 0.55

UPSCALE_HEIGHT = 160

MIN_VOTES_TO_ACCEPT = 2
VALID_NUMBER_PATTERN = re.compile(r"^\d{1,2}$")

SAVE_DEBUG_CROPS = True
DEBUG_DIR = "ocr_debug"

# ============================================================
# LOAD CANDIDATES
# ============================================================

df = pd.read_csv(CANDIDATES_CSV)

if df.empty:
    raise RuntimeError(f"{CANDIDATES_CSV} is empty.")

before_count = len(df)
df = df[df["quality_score"] >= MIN_QUALITY_SCORE_FOR_OCR].copy()

print(f"Candidates above quality threshold ({MIN_QUALITY_SCORE_FOR_OCR}): "
      f"{len(df)} / {before_count}")

if df.empty:
    raise RuntimeError(
        "No candidates survive the quality threshold. "
        "Lower MIN_QUALITY_SCORE_FOR_OCR and try again."
    )

df = df.sort_values(["track_id", "quality_score"], ascending=[True, False])
df = df.groupby("track_id", group_keys=False).head(MAX_CROPS_PER_TRACK_FOR_OCR)

print(f"Tracks with at least one usable candidate: {df['track_id'].nunique()}")
print(f"Total crops going to OCR: {len(df)}")

# ============================================================
# INIT TrOCR
# ============================================================

device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Loading TrOCR on {device}...")

MODEL_NAME = "microsoft/trocr-base-printed"
processor = TrOCRProcessor.from_pretrained(MODEL_NAME, use_fast=False)
model = VisionEncoderDecoderModel.from_pretrained(MODEL_NAME).to(device)
model.eval()

if SAVE_DEBUG_CROPS:
    Path(DEBUG_DIR).mkdir(parents=True, exist_ok=True)

# ============================================================
# PREPROCESS
# ============================================================


def preprocess_number_crop(image):
    """Crop to the torso band and upscale for OCR — identical to the
    EasyOCR version's preprocessing, so the only variable being changed
    is the OCR engine itself."""
    h, w = image.shape[:2]

    top = int(h * TORSO_TOP_FRAC)
    bottom = int(h * TORSO_BOTTOM_FRAC)
    torso = image[top:bottom, :]

    if torso.size == 0:
        return None

    th, tw = torso.shape[:2]
    if th == 0 or tw == 0:
        return None

    scale = max(1.0, UPSCALE_HEIGHT / th)
    resized = cv2.resize(
        torso,
        (int(tw * scale), int(th * scale)),
        interpolation=cv2.INTER_CUBIC,
    )

    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)

    # Back to 3-channel so it can be treated as RGB for TrOCR's processor.
    enhanced_bgr = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)

    return enhanced_bgr


@torch.no_grad()
def run_trocr(bgr_image):
    """Run TrOCR on a BGR crop, return (text, pseudo_confidence)."""
    rgb = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2RGB)
    pil_image = Image.fromarray(rgb)

    pixel_values = processor(images=pil_image, return_tensors="pt").pixel_values
    pixel_values = pixel_values.to(device)

    outputs = model.generate(
        pixel_values,
        max_new_tokens=4,
        output_scores=True,
        return_dict_in_generate=True,
    )

    text = processor.batch_decode(outputs.sequences, skip_special_tokens=True)[0]
    text = text.strip()

    # Approximate confidence from the generation scores (average token
    # probability). TrOCR doesn't give a single calibrated confidence
    # the way EasyOCR does, so treat this as a rough ranking signal
    # rather than a precise probability.
    if outputs.scores:
        probs = [torch.softmax(s, dim=-1).max().item() for s in outputs.scores]
        confidence = float(np.mean(probs)) if probs else 0.0
    else:
        confidence = 0.0

    return text, confidence


# ============================================================
# RUN OCR PER CROP
# ============================================================

results_per_row = []

print("\nRunning OCR (TrOCR)...")

for i, row in df.reset_index(drop=True).iterrows():

    track_id = int(row["track_id"])
    frame_number = int(row["frame"])
    quality_score = row["quality_score"]

    filename = f"frame_{frame_number:06d}_score_{quality_score:.3f}.jpg"
    crop_path = Path(CROPS_DIR) / f"track_{track_id:04d}" / filename

    if not crop_path.exists():
        continue

    image = cv2.imread(str(crop_path))
    if image is None:
        continue

    processed = preprocess_number_crop(image)
    if processed is None:
        continue

    if SAVE_DEBUG_CROPS:
        debug_track_dir = Path(DEBUG_DIR) / f"track_{track_id:04d}"
        debug_track_dir.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(debug_track_dir / filename), processed)

    text, confidence = run_trocr(processed)

    ocr_number = text if VALID_NUMBER_PATTERN.match(text) else None

    results_per_row.append({
        "track_id": track_id,
        "frame": frame_number,
        "quality_score": quality_score,
        "ocr_number": ocr_number,
        "ocr_raw_text": text,
        "ocr_confidence": confidence,
    })

    if (i + 1) % 100 == 0:
        print(f"Processed {i + 1}/{len(df)} crops")

ocr_df = pd.DataFrame(results_per_row)
ocr_df.to_csv("ocr_raw_results.csv", index=False)

print(f"\nOCR attempted on {len(ocr_df)} crops")
print(f"Crops with a valid number read: {ocr_df['ocr_number'].notna().sum()}")

# ============================================================
# AGGREGATE PER TRACK (confidence-weighted majority vote)
# ============================================================

track_results = []

for track_id, group in ocr_df.groupby("track_id"):

    valid = group.dropna(subset=["ocr_number"])

    if valid.empty:
        track_results.append({
            "track_id": track_id,
            "jersey_number": None,
            "vote_count": 0,
            "total_attempts": len(group),
            "mean_confidence": 0.0,
            "resolved": False,
        })
        continue

    weighted = valid.groupby("ocr_number")["ocr_confidence"].agg(
        vote_count="count",
        weight_sum="sum",
    ).reset_index()

    weighted = weighted.sort_values("weight_sum", ascending=False)
    top = weighted.iloc[0]

    resolved = (top["vote_count"] >= MIN_VOTES_TO_ACCEPT) or (
        top["vote_count"] == 1 and top["weight_sum"] >= 0.95
    )

    track_results.append({
        "track_id": track_id,
        "jersey_number": top["ocr_number"] if resolved else None,
        "vote_count": int(top["vote_count"]),
        "total_attempts": len(group),
        "mean_confidence": valid.loc[
            valid["ocr_number"] == top["ocr_number"], "ocr_confidence"
        ].mean(),
        "resolved": resolved,
    })

track_df = pd.DataFrame(track_results).sort_values("track_id")
track_df.to_csv(OUTPUT_CSV, index=False)

print("\n========================================")
print("Finished.")
print("========================================")
print(f"Tracks processed: {len(track_df)}")
print(f"Tracks resolved to a jersey number: {track_df['resolved'].sum()}")
print(f"Tracks unresolved: {(~track_df['resolved']).sum()}")
print(f"\nSaved per-crop OCR results to: ocr_raw_results.csv")
print(f"Saved per-track jersey numbers to: {OUTPUT_CSV}")

if SAVE_DEBUG_CROPS:
    print(f"Saved preprocessed OCR input crops to: {DEBUG_DIR}/ "
          f"(inspect these to tune TORSO_TOP_FRAC/TORSO_BOTTOM_FRAC)")