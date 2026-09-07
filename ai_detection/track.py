import cv2
import pandas as pd
from ultralytics import YOLO

VIDEO = "match.webm"
OUTPUT_CSV = "tracking.csv"
OUTPUT_VIDEO = "tracked_output.mp4"

MAX_FRAMES = 3500

model = YOLO("yolo26n.pt")

cap = cv2.VideoCapture(VIDEO)

if not cap.isOpened():
    raise RuntimeError(f"Could not open video: {VIDEO}")

fps = cap.get(cv2.CAP_PROP_FPS)
width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

print(f"FPS: {fps}")
print(f"Processing first {MAX_FRAMES} frames...")

# Set up video writer
fourcc = cv2.VideoWriter_fourcc(*"mp4v")
writer = cv2.VideoWriter(OUTPUT_VIDEO, fourcc, fps, (width, height))

tracking_data = []

frame_number = 0

while frame_number < MAX_FRAMES:

    success, frame = cap.read()

    if not success:
        print("Could not read next frame.")
        break

    results = model.track(
        frame,
        tracker="botsort_tuned.yaml",
        conf=0.3,
        classes=[0],
        imgsz=960,
        persist=True,
        verbose=False
    )

    result = results[0]

    # Draw boxes/IDs on the frame and write it out
    annotated_frame = result.plot()
    writer.write(annotated_frame)

    if result.boxes is not None and result.boxes.id is not None:

        boxes = result.boxes.xyxy.cpu().numpy()
        track_ids = result.boxes.id.cpu().numpy()
        confidences = result.boxes.conf.cpu().numpy()

        for box, track_id, confidence in zip(
            boxes,
            track_ids,
            confidences
        ):

            x1, y1, x2, y2 = box

            # Center point
            x = (x1 + x2) / 2
            y = (y1 + y2) / 2

            time_seconds = frame_number / fps

            tracking_data.append({
                "frame": frame_number,
                "time": time_seconds,
                "track_id": int(track_id),

                # Full bounding box
                "x1": float(x1),
                "y1": float(y1),
                "x2": float(x2),
                "y2": float(y2),

                # Center point
                "x": float(x),
                "y": float(y),

                "confidence": float(confidence)
            })

    if frame_number % 100 == 0:
        print(f"Frame {frame_number}/{MAX_FRAMES}")

    frame_number += 1

cap.release()
writer.release()

df = pd.DataFrame(tracking_data)

df.to_csv(OUTPUT_CSV, index=False)

print()
print(f"Finished! Processed {frame_number} frames.")
print(f"Saved {len(df)} player detections.")
print(f"Saved tracking data to: {OUTPUT_CSV}")
print(f"Saved annotated video to: {OUTPUT_VIDEO}")