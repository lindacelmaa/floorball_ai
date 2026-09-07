import re
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

# ============================================================
# CONFIG
# ============================================================

CANDIDATES_CSV = "ocr_candidates.csv"
CROPS_DIR = "ocr_crops"

OUTPUT_CSV = "track_jersey_numbers.csv"

# Only attempt OCR on crops likely to actually be legible.
# Based on visual inspection: ~0.80+ was clearly readable,
# ~0.65 and below was an unreadable blur. Adjust after reviewing
# ocr_debug/ output below.
MIN_QUALITY_SCORE_FOR_OCR = 0.70

# Cap how many crops per track we bother running OCR on
# (they're already sorted best-first upstream).
MAX_CROPS_PER_TRACK_FOR_OCR = 8

# Single band of the body box where the number lives.
# 0.0 = top of box (head), 1.0 = bottom of box (feet).
TORSO_TOP_FRAC = 0.15
TORSO_BOTTOM_FRAC = 0.55

# Resize the torso crop so its height is at least this many
# pixels before OCR — small text needs upscaling to read reliably.
UPSCALE_HEIGHT = 220

# A track needs at least this many *agreeing* reads before we
# accept a jersey number for it. Below this, leave it unresolved
# rather than guess.
MIN_VOTES_TO_ACCEPT = 2

# Valid jersey numbers (adjust if your league allows 3-digit numbers).
VALID_NUMBER_PATTERN = re.compile(r"^\d{1,2}$")

# Save the exact preprocessed image fed to OCR, for debugging/tuning.
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
# INIT OCR ENGINE
# ============================================================

import easyocr  # noqa: E402  (import here so the CSV/threshold errors above surface fast)

try:
    import torch
    use_gpu = torch.cuda.is_available()
except ImportError:
    use_gpu = False

print(f"Initializing EasyOCR (gpu={use_gpu})...")
reader = easyocr.Reader(["en"], gpu=use_gpu, verbose=False)

if SAVE_DEBUG_CROPS:
    Path(DEBUG_DIR).mkdir(parents=True, exist_ok=True)

# ============================================================
# PREPROCESS + OCR PER CROP
# ============================================================


def deskew_gray(gray):
    """Estimate the tilt of the foreground text blob and rotate it
    upright. Handles players leaning/rotating relative to the camera,
    which otherwise skews the number and hurts OCR."""
    # Rough foreground mask just for angle estimation (not the final
    # binarization used for OCR).
    _, mask = cv2.threshold(
        gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )
    coords = cv2.findNonZero(mask)

    if coords is None or len(coords) < 20:
        return gray

    angle = cv2.minAreaRect(coords)[-1]

    # cv2.minAreaRect angle convention needs normalizing into a
    # sensible "how far from upright" value.
    if angle < -45:
        angle = 90 + angle

    # Don't bother correcting tiny skews — not worth the resample cost
    # and risk of introducing artifacts on already-upright crops.
    if abs(angle) < 3:
        return gray

    h, w = gray.shape[:2]
    center = (w // 2, h // 2)
    rot_matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    rotated = cv2.warpAffine(
        gray, rot_matrix, (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return rotated


def pad_white(image, border=12):
    """Add a small white margin — text recognizers generally do better
    when characters aren't touching the image edge."""
    return cv2.copyMakeBorder(
        image, border, border, border, border,
        cv2.BORDER_CONSTANT, value=255,
    )


def generate_ocr_variants(image):
    """Crop to the torso band, then produce several differently
    processed versions and let OCR confidence pick a winner, rather
    than betting everything on one preprocessing guess."""
    h, w = image.shape[:2]

    top = int(h * TORSO_TOP_FRAC)
    bottom = int(h * TORSO_BOTTOM_FRAC)
    torso = image[top:bottom, :]

    if torso.size == 0:
        return []

    th, tw = torso.shape[:2]
    if th == 0 or tw == 0:
        return []

    gray = cv2.cvtColor(torso, cv2.COLOR_BGR2GRAY)

    scale = max(1.0, UPSCALE_HEIGHT / th)
    up = cv2.resize(
        gray,
        (int(tw * scale), int(th * scale)),
        interpolation=cv2.INTER_CUBIC,
    )

    up = deskew_gray(up)

    variants = []

    # 1. Plain upscaled — the baseline that was already reading
    #    numbers correctly before any of the fancier processing.
    variants.append(("bicubic", up))

    # 2. Local contrast boost.
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    contrast = clahe.apply(up)
    variants.append(("clahe", contrast))

    # 3. Unsharp mask on top of the contrast boost.
    blur = cv2.GaussianBlur(contrast, (0, 0), 1.2)
    sharp = cv2.addWeighted(contrast, 2.0, blur, -1.0, 0)
    variants.append(("sharp", sharp))

    # 4. Global Otsu threshold on the sharpened image. Works well when
    #    the number/jersey do have real contrast; can fail on very
    #    dark low-contrast jerseys (see "strong_sharp"/"adaptive" for
    #    those cases instead).
    _, otsu = cv2.threshold(sharp, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants.append(("otsu", otsu))

    # 5. Adaptive (local) threshold — thresholds each neighborhood
    #    independently instead of one global cutoff, which handles
    #    uneven lighting/low global contrast better than Otsu.
    adaptive = cv2.adaptiveThreshold(
        contrast, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31, 7,
    )
    variants.append(("adaptive", adaptive))

    # 6. Stronger sharpening — sometimes recovers digit edges on
    #    blurrier/smaller crops that "sharp" doesn't fully resolve.
    blur2 = cv2.GaussianBlur(contrast, (0, 0), 2.0)
    strong_sharp = cv2.addWeighted(contrast, 3.0, blur2, -2.0, 0)
    variants.append(("strong_sharp", strong_sharp))

    return [(name, pad_white(img)) for name, img in variants]


def save_debug_composite(variants, path):
    """Stack all variants side by side into one image for easy review."""
    images = [v for _, v in variants]
    max_h = max(img.shape[0] for img in images)
    padded = [
        cv2.copyMakeBorder(
            img, 0, max_h - img.shape[0], 0, 0,
            cv2.BORDER_CONSTANT, value=255,
        )
        for img in images
    ]
    separator = np.full((max_h, 6), 128, dtype=np.uint8)
    composite_parts = []
    for i, img in enumerate(padded):
        composite_parts.append(img)
        if i != len(padded) - 1:
            composite_parts.append(separator)
    composite = cv2.hconcat(composite_parts)
    cv2.imwrite(str(path), composite)


def best_valid_match(ocr_result):
    best_text, best_conf = None, 0.0
    for _, text, conf in ocr_result:
        text = text.strip()
        if VALID_NUMBER_PATTERN.match(text) and conf > best_conf:
            best_text, best_conf = text, conf
    return best_text, best_conf


results_per_row = []

print("\nRunning OCR...")

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

    variants = generate_ocr_variants(image)
    if not variants:
        continue

    if SAVE_DEBUG_CROPS:
        debug_track_dir = Path(DEBUG_DIR) / f"track_{track_id:04d}"
        debug_track_dir.mkdir(parents=True, exist_ok=True)
        save_debug_composite(variants, debug_track_dir / filename)

    overall_best_text, overall_best_conf = None, 0.0

    for _, variant_image in variants:

        ocr_result = reader.readtext(variant_image, allowlist="0123456789")
        text, conf = best_valid_match(ocr_result)

        # Fallback: detector found nothing at all for this variant —
        # bypass detection and force recognition on the lower half
        # (below the name line), treating it as one text region.
        if text is None:
            vh = variant_image.shape[0]
            number_band = variant_image[int(vh * 0.4):, :]
            if number_band.size > 0:
                fallback_result = reader.recognize(
                    number_band, allowlist="0123456789"
                )
                text, conf = best_valid_match(fallback_result)

        if text is not None and conf > overall_best_conf:
            overall_best_text, overall_best_conf = text, conf

    results_per_row.append({
        "track_id": track_id,
        "frame": frame_number,
        "quality_score": quality_score,
        "ocr_number": overall_best_text,
        "ocr_confidence": overall_best_conf,
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

    # Weighted vote: sum of confidences per candidate number.
    weighted = valid.groupby("ocr_number")["ocr_confidence"].agg(
        vote_count="count",
        weight_sum="sum",
    ).reset_index()

    weighted = weighted.sort_values("weight_sum", ascending=False)
    top = weighted.iloc[0]

    resolved = (top["vote_count"] >= MIN_VOTES_TO_ACCEPT) or (
        top["vote_count"] == 1 and top["weight_sum"] >= 0.98
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

print("\nNext step:")
print("1. Check track_jersey_numbers.csv — spot-check a few resolved tracks")
print("2. For unresolved tracks, inspect ocr_debug/ to see why OCR failed")
print("3. Then merge track_ids that share the same jersey_number")