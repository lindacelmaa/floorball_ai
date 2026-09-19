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

# Variants are tried in priority order (rgb -> sharp -> otsu) and we stop
# escalating as soon as one produces a read at/above this confidence —
# i.e. "try color; if it can't read it, try grayscale; if it still can't,
# try the binary version." Below this confidence we keep the best result
# seen so far but still try the next variant in the chain.
EARLY_STOP_CONFIDENCE = 0.60

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
# INIT OCR ENGINE (PaddleOCR)
# ============================================================

# NOTE ON VERSIONS: PaddleOCR's Python API changed a lot between the 2.x
# line (`PaddleOCR(use_angle_cls=...)` + `ocr.ocr(img, cls=True)` returning
# `[bbox, (text, conf)]` tuples) and the current 3.x line
# (`PaddleOCR(use_textline_orientation=...)` + `ocr.predict(img)` returning
# Result objects). This script targets the current 3.x API. If `pip show
# paddleocr` reports a 2.x version, see the "PaddleOCR 2.x" note in the
# implementation steps below.
from paddleocr import PaddleOCR, TextRecognition  # noqa: E402

try:
    import paddle
    use_gpu = paddle.device.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0
except Exception:
    use_gpu = False

device = "gpu:0" if use_gpu else "cpu"

print(f"Initializing PaddleOCR (device={device})...")

# Full det+rec pipeline. We turn off doc-orientation / unwarping / textline
# orientation because these crops are already tight, upright torso bands —
# those extra stages just add latency here.
ocr_engine = PaddleOCR(
    lang="en",
    device=device,
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False,
    # oneDNN's PIR runtime currently chokes on some ops with:
    #   NotImplementedError: ConvertPirAttribute2RuntimeAttribute not
    #   support [pir::ArrayAttribute<pir::DoubleAttribute>]
    # This is a known PaddleOCR 3.x issue on CPU inference, not a config
    # mistake — disabling MKL-DNN avoids it (costs some CPU speed).
    enable_mkldnn=False,
)

# Detector-free recognizer, used only as a fallback when the full pipeline's
# text detector finds nothing on a variant. It treats the whole image it's
# given as a single text line, mirroring what EasyOCR's reader.recognize()
# did in the original script.
text_recognizer = TextRecognition(device=device, enable_mkldnn=False)

if SAVE_DEBUG_CROPS:
    Path(DEBUG_DIR).mkdir(parents=True, exist_ok=True)

# ============================================================
# PREPROCESS
# ============================================================


def compute_tight_bounds(gray, pad=10):
    """Find the (top, bottom, left, right) box around the number's ink,
    based on edge density in the grayscale image. Returns None if the
    estimate looks unreliable, so the caller can fall back to the
    original, uncropped region rather than crop to noise.

    No rotation/deskew step is used here on purpose — angle search based
    on Hough lines proved unreliable in practice (background clutter and
    motion-blur streaks scored higher than genuine text, causing rotation
    on crops that didn't need it, while some genuinely tilted crops still
    weren't corrected). PaddleOCR tolerates modest in-plane tilt on its
    own, so a tight, unrotated crop is the more predictable choice here.
    """
    edges = cv2.Canny(gray, 50, 150)

    row_density = edges.sum(axis=1).astype(np.float32)
    col_density = edges.sum(axis=0).astype(np.float32)

    def _trim(density, size):
        if density.max() == 0:
            return 0, size
        kernel = np.ones(5, dtype=np.float32) / 5.0
        smoothed = np.convolve(density, kernel, mode="same")
        threshold = smoothed.max() * 0.35
        idx = np.where(smoothed >= threshold)[0]
        if len(idx) == 0:
            return 0, size
        lo = max(0, int(idx[0]) - pad)
        hi = min(size, int(idx[-1]) + pad)
        return lo, hi

    top, bottom = _trim(row_density, gray.shape[0])
    left, right = _trim(col_density, gray.shape[1])

    # Sanity check: if either dimension collapsed to something implausibly
    # small, the density estimate probably locked onto noise.
    if (bottom - top) < 20 or (right - left) < 20:
        return None

    return top, bottom, left, right


def pad_white(image, border=12):
    """Add a small white margin — text recognizers generally do better
    when characters aren't touching the image edge. Works for both
    single-channel (grayscale) and 3-channel (color) images."""
    border_value = (255, 255, 255) if image.ndim == 3 else 255
    return cv2.copyMakeBorder(
        image, border, border, border, border,
        cv2.BORDER_CONSTANT, value=border_value,
    )


def generate_ocr_variants(image):
    """Crop to the torso band, tighten the crop to just the number itself
    (both row and column extent), then produce three candidate inputs
    for OCR, tried in priority order in the main loop:
      1. "rgb"   — the color crop, untouched apart from cropping/scaling.
                   PaddleOCR's models are trained on natural color photos,
                   so this is usually the most informative input, not a
                   fallback.
      2. "sharp" — a contrast-boosted, sharpened grayscale version, for
                   cases the color version doesn't resolve cleanly.
      3. "otsu"  — a binarized last resort, only used with the
                   detector-free recognizer (see the main loop) since
                   running the text detector on a binary silhouette is
                   unreliable.
    """
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
    new_size = (int(tw * scale), int(th * scale))
    gray_up = cv2.resize(gray, new_size, interpolation=cv2.INTER_CUBIC)
    color_up = cv2.resize(torso, new_size, interpolation=cv2.INTER_CUBIC)

    # Find the number's ink bounds on the grayscale version (edge density
    # is easier to reason about on a single channel), then apply the same
    # crop window to both the grayscale and color images so they stay in
    # sync. No rotation step (see compute_tight_bounds's docstring).
    bounds = compute_tight_bounds(gray_up)
    if bounds is not None:
        t, b, l, r = bounds
        gray_up = gray_up[t:b, l:r]
        color_up = color_up[t:b, l:r]

    # The tight crop just made the image shorter — re-upscale so small
    # digits still get enough pixels for OCR. Apply the same scale factor
    # to both so they stay the same size as each other.
    th2 = gray_up.shape[0]
    if 0 < th2 < UPSCALE_HEIGHT:
        scale2 = UPSCALE_HEIGHT / th2
        size2 = (int(gray_up.shape[1] * scale2), int(th2 * scale2))
        gray_up = cv2.resize(gray_up, size2, interpolation=cv2.INTER_CUBIC)
        color_up = cv2.resize(color_up, size2, interpolation=cv2.INTER_CUBIC)

    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    contrast = clahe.apply(gray_up)

    blur = cv2.GaussianBlur(contrast, (0, 0), 1.2)
    sharp = cv2.addWeighted(contrast, 2.0, blur, -1.0, 0)

    _, otsu = cv2.threshold(sharp, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # (name, image, try_detector) — try_detector=False means skip the
    # full det+rec pipeline and go straight to the detector-free
    # recognizer (see run_recognition_only and the main loop).
    variants = [
        ("rgb", color_up, True),
        ("sharp", sharp, True),
        ("otsu", otsu, False),
    ]

    return [(name, pad_white(img), try_detector) for name, img, try_detector in variants]


def save_debug_composite(variants, path):
    """Stack all variants side by side into one image for easy review.
    Handles a mix of grayscale and color images (the 'rgb' variant is
    color, 'sharp'/'otsu' are grayscale) by converting everything to BGR
    before stacking."""
    images = []
    for _, img, _try_detector in variants:
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        images.append(img)

    max_h = max(img.shape[0] for img in images)
    padded = [
        cv2.copyMakeBorder(
            img, 0, max_h - img.shape[0], 0, 0,
            cv2.BORDER_CONSTANT, value=(255, 255, 255),
        )
        for img in images
    ]
    separator = np.full((max_h, 6, 3), 128, dtype=np.uint8)
    composite_parts = []
    for i, img in enumerate(padded):
        composite_parts.append(img)
        if i != len(padded) - 1:
            composite_parts.append(separator)
    composite = cv2.hconcat(composite_parts)
    cv2.imwrite(str(path), composite)


# ============================================================
# PADDLEOCR RESULT PARSING
# ============================================================
#
# PaddleOCR is not built around a character allowlist the way EasyOCR's
# `allowlist="0123456789"` is. There's no equivalent kwarg on `predict()`.
# Two ways to get digit-only behavior:
#   (a) Post-filter recognized text down to digits (what this script does —
#       simple, but a misread letter that looks like a digit, e.g. "O"→"",
#       just gets dropped rather than corrected).
#   (b) Train/point PaddleOCR at a digits-only character dictionary via
#       `rec_char_dict_path` on a custom recognition model — more correct,
#       more setup. Not needed for most jersey-number use cases.
# This script uses (a).

def _extract_res_dict(result_obj):
    """PaddleOCR 3.x Result objects behave like dicts in most released
    versions, but also expose a `.json` attribute. Try both defensively
    since the exact access pattern has moved around between point
    releases."""
    if result_obj is None:
        return {}
    if isinstance(result_obj, dict):
        return result_obj.get("res", result_obj)
    if hasattr(result_obj, "json"):
        data = result_obj.json
        if isinstance(data, dict):
            return data.get("res", data)
    try:
        return result_obj["res"]
    except Exception:
        return {}


def _box_to_points(box):
    """Normalize a PaddleOCR box into drawable corner points. PaddleOCR
    returns either an axis-aligned [x1, y1, x2, y2] (rec_boxes) or a
    4-point polygon (rec_polys/dt_polys) depending on version/field."""
    arr = np.array(box).astype(np.float32).reshape(-1)
    if arr.size == 4:
        x1, y1, x2, y2 = arr
        pts = np.array([[x1, y1], [x2, y1], [x2, y2], [x1, y2]])
    else:
        pts = arr.reshape(-1, 2)
    return pts.astype(np.int32)


def best_valid_match_from_lists(texts, scores):
    """Returns (text, confidence, index) — the index lets the caller look
    up the matching detection box for that read, for debug visualization."""
    best_text, best_conf, best_idx = None, 0.0, None
    for idx, (text, conf) in enumerate(zip(texts, scores)):
        digits_only = re.sub(r"\D", "", str(text)).strip()
        conf = float(conf)
        if digits_only and VALID_NUMBER_PATTERN.match(digits_only) and conf > best_conf:
            best_text, best_conf, best_idx = digits_only, conf, idx
    return best_text, best_conf, best_idx


def run_full_pipeline(image):
    """Run the standard det+rec pipeline on one preprocessed variant.
    Returns texts, scores, and boxes (may be None if the field isn't
    present in your installed PaddleOCR version)."""
    result = ocr_engine.predict(image)
    if not result:
        return [], [], None
    res = _extract_res_dict(result[0])
    texts = res.get("rec_texts", []) or []
    scores = res.get("rec_scores", []) or []
    boxes = res.get("rec_boxes")
    if boxes is None:
        boxes = res.get("rec_polys")
    if boxes is None:
        boxes = res.get("dt_polys")
    return texts, scores, boxes


def run_recognition_only(image):
    """Detector-free read: treat the whole image handed to it as one text
    line — mirrors EasyOCR's reader.recognize() fallback in the original
    script, and is also what the 'otsu' variant uses instead of the full
    pipeline (see the main loop). There's no real detection box in this
    mode, so the full image rect is used as the debug box instead — this
    is only a reasonable stand-in because the crop was already trimmed
    close to the number by compute_tight_bounds() before it got here."""
    result = text_recognizer.predict(image)
    if not result:
        return [], [], None
    res = _extract_res_dict(result[0])
    text = res.get("rec_text")
    score = res.get("rec_score")
    if text is None:
        return [], [], None
    h, w = image.shape[:2]
    fallback_box = [[0, 0, w, h]]
    return [text], [score if score is not None else 0.0], fallback_box


# ============================================================
# OCR PER CROP
# ============================================================

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
    overall_best_box, overall_best_variant_bgr = None, None

    # Variants are already ordered by priority: rgb -> sharp -> otsu.
    # Stop as soon as one clears EARLY_STOP_CONFIDENCE — "try color; if
    # it can't read it, try grayscale; if it still can't, try binary."
    # Below that confidence we keep going and take whatever the best
    # result across all tried variants ends up being.
    for variant_name, variant_image, try_detector in variants:

        # PaddleOCR's recognizer expects a 3-channel image; grayscale
        # variants need converting back before predict().
        variant_bgr = (
            variant_image if variant_image.ndim == 3
            else cv2.cvtColor(variant_image, cv2.COLOR_GRAY2BGR)
        )

        if try_detector:
            texts, scores, boxes = run_full_pipeline(variant_bgr)
        else:
            # Running the text DETECTOR on a pure black/white silhouette
            # is unreliable — a straight edge that isn't text at all (a
            # stick, a limb outline against the solid black jersey) can
            # look more "text-like" to the detector than the actual
            # number does. Skip detection for this variant entirely and
            # just force a single-line read of the whole (already-tight)
            # crop — a second opinion without the false-detection risk.
            texts, scores, boxes = run_recognition_only(variant_bgr)

        text, conf, idx = best_valid_match_from_lists(texts, scores)
        box = boxes[idx] if (boxes is not None and idx is not None and idx < len(boxes)) else None
        source_image = variant_bgr

        if text is None and try_detector:
            # Full-pipeline detector found nothing at all on this variant
            # — fall back to forcing a read of the lower part of the crop.
            vh = variant_bgr.shape[0]
            number_band = variant_bgr[int(vh * 0.4):, :]
            if number_band.size > 0:
                fb_texts, fb_scores, fb_boxes = run_recognition_only(number_band)
                text, conf, idx = best_valid_match_from_lists(fb_texts, fb_scores)
                if text is not None:
                    box = fb_boxes[idx] if fb_boxes is not None else None
                    source_image = number_band

        if text is not None and conf > overall_best_conf:
            overall_best_text, overall_best_conf = text, conf
            overall_best_box, overall_best_variant_bgr = box, source_image

        if overall_best_conf >= EARLY_STOP_CONFIDENCE:
            break

    if SAVE_DEBUG_CROPS and overall_best_variant_bgr is not None:
        boxed = overall_best_variant_bgr.copy()
        if overall_best_box is not None:
            pts = _box_to_points(overall_best_box)
            cv2.polylines(boxed, [pts], isClosed=True, color=(0, 255, 0), thickness=2)
        label = overall_best_text if overall_best_text is not None else "NO READ"
        cv2.putText(
            boxed, f"{label} ({overall_best_conf:.2f})",
            (5, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1, cv2.LINE_AA,
        )
        detected_dir = Path(DEBUG_DIR) / f"track_{track_id:04d}"
        detected_dir.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(detected_dir / f"{crop_path.stem}_detected.jpg"), boxed)

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
# AGGREGATE PER TRACK (confidence-weighted majority vote) — unchanged
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
    print(f"Saved per-crop '*_detected.jpg' images to: {DEBUG_DIR}/ "
          f"— green box + read/confidence label show exactly what OCR "
          f"matched, for debugging misreads or bad rotations")

print("\nNext step:")
print("1. Check track_jersey_numbers.csv — spot-check a few resolved tracks")
print("2. For unresolved tracks, inspect ocr_debug/ to see why OCR failed")
print("3. Then merge track_ids that share the same jersey_number")