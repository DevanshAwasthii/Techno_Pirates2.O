import zipfile
from pathlib import Path

import pytest

from app import pipeline
from app.parsers import chrome

ROOT = Path(__file__).resolve().parents[1]
ZIP = ROOT / "samples" / "persona_chrome.zip"


@pytest.fixture(scope="module")
def res():
    return pipeline.run([ZIP])


def test_chrome_findings(res):
    assert res["errors"] == []
    assert all("records your session" not in r["item"] for r in res["records"])
    t = [f["title"] for f in res["findings"]]
    assert "6 sites may use session-recording tools (cookie indicators)" in t
    assert any(x.startswith("12 known tracker domains") for x in t)
    assert any(x.startswith("6 sites can access your location, camera or microphone") for x in t)
    assert res["summary"]["sessionRecorders"] == 6 and res["summary"]["trackersFound"] == 12


def test_never_reads_secret_values(res):
    blob = repr(res)
    assert "encrypted" not in blob  # cookie and password values never selected
    assert "riya.sen" not in blob  # usernames not read either


def test_downloads_and_saved_logins(res):
    items = [r["item"] for r in res["records"]]
    assert any("aadhaar_card.pdf" in i for i in items)
    assert any(i == "Saved login for oldgamesite.net" for i in items)


def test_profile_folder_input(tmp_path):
    with zipfile.ZipFile(ZIP) as z:
        z.extractall(tmp_path)
    assert chrome.is_profile(tmp_path / "Default")
    r = pipeline.run([tmp_path / "Default"])
    assert r["errors"] == [] and r["summary"]["sessionRecorders"] == 6


def test_temp_files_cleaned():
    pipeline.run([ZIP])
    left = list((ROOT / ".cache" / "tmp").glob("*")) if (ROOT / ".cache" / "tmp").exists() else []
    assert left == []
