"""Generate deterministic, OCR-readable phone screen recordings for the demo.

Run from the project root: python -m samples.make_recordings
"""
from pathlib import Path

import cv2
import numpy as np

SAMPLES = Path(__file__).resolve().parent
WIDTH, HEIGHT = 720, 1280
FPS = 10
FONT = cv2.FONT_HERSHEY_SIMPLEX
VIEWERS = ("Arjun Das", "Meera K", "Kabir Roy", "Tanvi M", "Ishaan G", "Pooja S")


def text(frame, value, y, scale=1.1):
    width = cv2.getTextSize(value, FONT, scale, 2)[0][0]
    if width > WIDTH - 84:
        scale *= (WIDTH - 84) / width
    cv2.putText(frame, value, (42, y), FONT, scale, (255, 255, 255), 2, cv2.LINE_AA)


def phone(title):
    frame = np.full((HEIGHT, WIDTH, 3), 18, dtype=np.uint8)
    text(frame, "9:41", 48, 0.8)
    text(frame, title, 126, 1.45)
    cv2.line(frame, (30, 158), (690, 158), (75, 75, 75), 2)
    return frame


def feed_screen(index):
    frame = phone("Instagram")
    text(frame, "Home    Reels    Friends", 207, 1.0)
    # Moving post artwork makes the screen scroll visibly between content updates.
    top = (245, 425, 265, 365, 485)[index]
    cv2.rectangle(frame, (42, top), (678, top + 250), (58, 58, 58), -1)
    cv2.circle(frame, (180 + index * 70, top + 125), 68, (90, 90, 90), -1)
    lines = (
        ("Liked by arjun.das and 214 others", "A weekend walk by the river"),
        ("meera_k liked this", "Coffee and conversations"),
        ("rahul.k reacted to a reel", "A little music for your day"),
        ("Liked by arjun.dass and 87 others", "New places and familiar faces"),
        ("meera_k liked this", "More photos from the weekend"),
    )[index]
    text(frame, lines[0], top + 320)
    text(frame, lines[1], top + 385, 0.95)
    text(frame, "View comments", top + 445, 0.85)
    text(frame, "Home     Search     Reels     Profile", 1215, 0.88)
    return frame


def status_screen(viewed):
    frame = phone("My status" if viewed else "Updates")
    if viewed:
        # The viewer sheet has its own dark header panel, unlike the Updates list.
        cv2.rectangle(frame, (30, 170), (690, 265), (52, 52, 52), -1)
    text(frame, "Viewed by 6" if viewed else "Recent updates", 220, 1.2)
    for index, name in enumerate(VIEWERS):
        y = 310 + index * 135
        text(frame, name, y, 1.25)
        text(frame, f"Today, 9:{12 + index:02d} pm", y + 48, 0.95)
    return frame


def write_video(path, screens):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (WIDTH, HEIGHT))
    if not writer.isOpened():
        raise RuntimeError(f"Could not create mp4v recording: {path}")
    try:
        for frame, seconds in screens:
            for _ in range(round(seconds * FPS)):
                writer.write(frame)
    finally:
        writer.release()
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise RuntimeError(f"Cannot reopen generated recording: {path}")
        duration = cap.get(cv2.CAP_PROP_FRAME_COUNT) / cap.get(cv2.CAP_PROP_FPS)
        size = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        ok, first = cap.read()
        if not ok or first is None or size != (WIDTH, HEIGHT) or not 8 <= duration <= 12:
            raise RuntimeError(f"Invalid generated recording: {path}, {size=}, {duration=}")
        print(f"{path.name}: {size[0]}x{size[1]}, {duration:.1f}s, mp4v, {FPS} fps")
    finally:
        cap.release()


def main():
    write_video(SAMPLES / "persona_instagram_feed.mp4", [(feed_screen(i), 2) for i in range(5)])
    write_video(SAMPLES / "persona_whatsapp_status.mp4", [(status_screen(False), 5), (status_screen(True), 5)])


if __name__ == "__main__":
    main()
