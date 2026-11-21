"""Real OCR integration checks; no OCR output or parser results are mocked."""
from pathlib import Path

import cv2
import numpy as np
import pytest

from app import pipeline
from app.engine.records import ParseError
from app.parsers import ocr

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"
FEED = SAMPLES / "persona_instagram_feed.mp4"
STATUS = SAMPLES / "persona_whatsapp_status.mp4"
EXPECTED_FRIENDS = {"arjun.das", "meera_k", "rahul.k"}
EXPECTED_VIEWERS = {"Arjun Das", "Meera K", "Kabir Roy", "Tanvi M", "Ishaan G", "Pooja S"}


@pytest.fixture(scope="module", autouse=True)
def warm_ocr_engine():
    """Load and warm the real engine once; ocr._engine is shared by later calls."""
    engine = ocr._ocr()
    engine(np.zeros((64, 64, 3), dtype=np.uint8))
    return engine


@pytest.fixture(scope="module")
def result():
    paths = sorted(SAMPLES.glob("persona_*"))
    assert FEED in paths and STATUS in paths, "Run python -m samples.make_recordings first"
    # Media deliberately come first: the pipeline must still parse exports before OCR.
    return pipeline.run([FEED, STATUS] + [p for p in paths if p not in {FEED, STATUS}])


def frame_at(path, second):
    cap = cv2.VideoCapture(str(path))
    try:
        assert cap.isOpened(), str(path)
        cap.set(cv2.CAP_PROP_POS_MSEC, second * 1000)
        ok, frame = cap.read()
        assert ok and frame is not None, f"Missing frame at {second}s in {path}"
        return frame
    finally:
        cap.release()


@pytest.mark.parametrize("path", [FEED, STATUS], ids=["instagram", "whatsapp"])
def test_recording_dimensions_duration_and_decoding(path):
    cap = cv2.VideoCapture(str(path))
    try:
        assert cap.isOpened()
        assert (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))) == (720, 1280)
        fps = cap.get(cv2.CAP_PROP_FPS)
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        assert fps > 0 and 8 <= count / fps <= 12
        decoded = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            assert frame.shape == (1280, 720, 3)
            decoded += 1
        assert decoded == count
    finally:
        cap.release()


def test_all_personas_parse_without_errors(result):
    assert result["errors"] == []
    sources = {r["sourceFile"] for r in result["records"] if r["meta"].get("capture") == "ocr"}
    assert {FEED.name, STATUS.name} <= sources


def test_friends_liked_finding_has_exact_count_and_evidence(result):
    finding = next(f for f in result["findings"] if "friends liked" in f["title"])
    assert finding["title"] == "Instagram showed you what 3 friends liked"
    assert finding["metric"] == {"value": 3, "unit": "friends"}
    records = [r for r in result["records"] if r["meta"].get("action") == "friend_like"]
    assert {r["meta"]["person"] for r in records} == EXPECTED_FRIENDS
    assert set(finding["evidence"]) == {r["id"] for r in records}


def test_deliberate_typo_is_read_then_snapped(result):
    lines = ocr.read_lines(frame_at(FEED, 6))
    assert any("arjun.dass" in line for line in lines), lines
    typo_record = next(r for r in result["records"] if r["sourceFile"] == FEED.name and r["meta"].get("others") == 87)
    assert typo_record["meta"]["person"] == "arjun.das"
    assert "arjun.dass" not in typo_record["item"]
    assert "arjun.das" in typo_record["item"]
    assert typo_record["recordRef"] == "frame at 6s"


def test_six_status_viewers_and_recent_updates_are_separate(result):
    finding = next(f for f in result["findings"] if "people watch your WhatsApp status" in f["title"])
    assert finding["title"] == "6 people watch your WhatsApp status"
    assert finding["metric"] == {"value": 6, "unit": "people"}
    viewers = [r for r in result["records"] if r["meta"].get("action") == "status_view"]
    posters = [r for r in result["records"] if r["meta"].get("action") == "status_post"]
    assert {r["meta"]["person"] for r in viewers} == EXPECTED_VIEWERS
    assert {r["meta"]["person"] for r in posters} == EXPECTED_VIEWERS
    assert set(finding["evidence"]) == {r["id"] for r in viewers}
    totals = [r["meta"]["views"] for r in result["records"] if r["meta"].get("action") == "status_views_total"]
    assert totals == [6]
    chats = "\n".join(p.read_text(encoding="utf-8") for p in SAMPLES.glob("persona_whatsapp_*.txt"))
    assert all(name in chats for name in EXPECTED_VIEWERS)


def test_media_records_have_unique_resolvable_ids(result):
    ids = [r["id"] for r in result["records"]]
    assert len(ids) == len(set(ids))
    for finding in result["findings"]:
        assert set(finding["evidence"]) <= set(ids)


def test_video_over_max_seconds_is_too_large(tmp_path):
    path = tmp_path / "too_long.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 1, (16, 16))
    assert writer.isOpened()
    try:
        for _ in range(ocr.MAX_SECONDS + 1):
            writer.write(np.zeros((16, 16, 3), dtype=np.uint8))
    finally:
        writer.release()
    cap = cv2.VideoCapture(str(path))
    try:
        assert cap.isOpened()
        assert cap.get(cv2.CAP_PROP_FRAME_COUNT) / cap.get(cv2.CAP_PROP_FPS) > ocr.MAX_SECONDS
    finally:
        cap.release()
    with pytest.raises(ParseError) as error:
        ocr.parse(path)
    assert error.value.code == "too_large"
    assert pipeline.run([path])["errors"][0]["code"] == "too_large"


def test_image_without_relevant_text_is_wrong_format(tmp_path):
    path = tmp_path / "empty.png"
    assert cv2.imwrite(str(path), np.full((320, 240, 3), 18, dtype=np.uint8))
    with pytest.raises(ParseError) as error:
        ocr.parse(path)
    assert error.value.code == "wrong_format"
    assert pipeline.run([path])["errors"][0]["code"] == "wrong_format"


def test_repeated_line_in_distinct_consecutive_frames_counted_once(tmp_path):
    path = tmp_path / "duplicate.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 1, (720, 1280))
    assert writer.isOpened()
    try:
        # The same like appears in different posts at 2s and 8s of the real clip.
        # Their artwork differs, so both must survive the near-duplicate filter.
        writer.write(frame_at(FEED, 2))
        writer.write(frame_at(FEED, 8))
    finally:
        writer.release()
    frames = list(ocr.frames(path))
    assert [sec for sec, _ in frames] == [0, 1]
    records, _ = ocr.parse(path, ["meera_k"])
    assert len(records) == 1
    assert records[0].meta["person"] == "meera_k"
    assert records[0].meta["action"] == "friend_like"


def test_unchanged_video_frames_are_skipped():
    assert [sec for sec, _ in ocr.frames(FEED)] == [0, 2, 4, 6, 8]
    assert [sec for sec, _ in ocr.frames(STATUS)] == [0, 5]


def test_same_platform_recordings_get_unique_ids(tmp_path):
    import shutil
    a, b = tmp_path / "a" / "feed.mp4", tmp_path / "b" / "feed.mp4"  # same name, different folders
    for p in (a, b):
        p.parent.mkdir()
        shutil.copyfile(FEED, p)
    r = pipeline.run([a, b])
    ids = [x["id"] for x in r["records"]]
    assert len(ids) == len(set(ids))
    known = set(ids)
    for f in r["findings"]:
        assert set(f["evidence"]) <= known
    by_id = {x["id"]: x for x in r["records"]}
    srcs = {by_id[i]["sourceFile"] for i in ids}
    assert srcs == {"feed.mp4"}  # both sources kept, distinguished by id namespace not name


def _header_change_video(path):
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 1, (720, 1280))
    for sec in range(4):
        img = np.zeros((1280, 720, 3), np.uint8)
        header = "My status" if sec < 2 else "Viewed by 6"  # only the header changes at second 2
        cv2.putText(img, header, (40, 90), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 255, 255), 3)
        for k, name in enumerate(["Arjun Das", "Meera K", "Kabir Roy"]):
            cv2.putText(img, name, (40, 300 + 160 * k), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 255, 255), 3)
        w.write(img)
    w.release()


def test_header_only_change_is_not_skipped(tmp_path):
    p = tmp_path / "header.mp4"
    _header_change_video(p)
    secs = [s for s, _ in ocr.frames(p)]
    assert secs == [0, 2]  # identical held frame skipped, header-only change kept
