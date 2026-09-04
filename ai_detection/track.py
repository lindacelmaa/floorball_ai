import cv2
from ultralytics import YOLO

VIDEO = "match.webm"
OUTPUT_VIDEO = "tracking_preview.mp4"
MAX_FRAMES = 3500

model = YOLO("yolo26n.pt")

cap = cv2.VideoCapture(VIDEO)

if not cap.isOpened():
    raise RuntimeError(f"Could not open video: {VIDEO}")

fps = cap.get(cv2.CAP_PROP_FPS)
width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

print(f"FPS: {fps}")
print(f"Resolution: {width}x{height}")
print(f"Creating preview from first {MAX_FRAMES} frames...")

# MP4 video writer
fourcc = cv2.VideoWriter_fourcc(*"mp4v")
out = cv2.VideoWriter(
    OUTPUT_VIDEO,
    fourcc,
    fps,
    (width, height)
)

frame_number = 0

while frame_number < MAX_FRAMES:

    success, frame = cap.read()

    if not success:
        print("Could not read next frame.")
        break

    results = model.track(
        frame,
        tracker="bytetrack.yaml",
        conf=0.3,
        classes=[0],
        imgsz=960,
        persist=True,
        verbose=False
    )

    result = results[0]

    # Draw tracking boxes and IDs
    if result.boxes is not None and result.boxes.id is not None:

        boxes = result.boxes.xyxy.cpu().numpy()
        track_ids = result.boxes.id.cpu().numpy()
        confidences = result.boxes.conf.cpu().numpy()

        for box, track_id, confidence in zip(
            boxes, track_ids, confidences
        ):

            x1, y1, x2, y2 = map(int, box)

            track_id = int(track_id)

            # Draw bounding box
            cv2.rectangle(
                frame,
                (x1, y1),
                (x2, y2),
                (0, 255, 0),
                2
            )

            # ID text
            label = f"Player {track_id} ({confidence:.2f})"

            cv2.putText(
                frame,
                label,
                (x1, max(y1 - 10, 20)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2
            )

    # Add frame/time information
    current_time = frame_number / fps

    cv2.putText(
        frame,
        f"Time: {current_time:.2f}s",
        (30, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        1,
        (255, 255, 255),
        2
    )

    out.write(frame)

    if frame_number % 100 == 0:
        print(f"Frame {frame_number}/{MAX_FRAMES}")

    frame_number += 1

cap.release()
out.release()

print()
print(f"Finished! Processed {frame_number} frames.")
print(f"Preview saved to: {OUTPUT_VIDEO}")