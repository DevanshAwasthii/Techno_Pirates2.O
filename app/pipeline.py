"""Single entry point the GUI calls. Runs in a background thread.

    result = run(paths, progress=lambda stage, file, pct: ..., cancel=threading.Event())

Returns {"records", "findings", "coverage", "summary", "graph", "errors"} as plain dicts.
One bad file never stops the others: its error goes into "errors".
"""
from __future__ import annotations

import zipfile
import json
from pathlib import Path

from app.engine.records import ParseError, to_dict
from app.engine.coverage import laptop_sources, coverage_rows
from app.engine.rules import build_findings, build_graph
import shutil
import tempfile

from app.parsers import instagram, spotify, whatsapp, mbox, chrome, ocr, deviceScan, iosPrivacy

TMP = Path(__file__).resolve().parents[1] / ".cache" / "tmp"  # stays on the project drive


class Cancelled(Exception):
    pass


def _wa_text(raw: bytes) -> str:
    return raw.decode("utf-8-sig", errors="replace")


def _detect_and_parse(path: Path, wa_offset: int = 0, warnings=None, source_coverage=None):
    """Pick a parser by content, not filename. Returns (platform, records, coverage)."""
    suffix = path.suffix.lower()
    if chrome.is_profile(path):
        recs, cov = chrome.parse(path, warnings=warnings, source_coverage=source_coverage)
        return "chrome", recs, cov
    if suffix == ".ndjson":
        recs, cov, stats = iosPrivacy.parse(path)
        if source_coverage is not None:
            source_coverage.append({"name": path.name, "source": str(path), "platform": "ios", "kind": "ios_report",
                                    "status": "partial" if stats["bad_lines"] else "scanned", "records": len(recs),
                                    "detail": f"{len(recs)} events read; {stats['bad_lines']} bad lines skipped; {stats['ignored_lines']} end events or unsupported rows excluded."})
        return "ios", recs, cov
    if suffix not in {".zip", ".mbox"}:
        with path.open("rb") as stream:
            looks_json = stream.read(256).lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"{")
        if looks_json or suffix == ".json":
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
            except (ValueError, UnicodeError):
                raise ParseError("wrong_format", "Invalid JSON scan file", path.name) from None
            if isinstance(data, dict) and ("laptop" in data or "android" in data):
                recs, cov = deviceScan.parse(path, data)
                if source_coverage is not None:
                    source_coverage.extend(laptop_sources(path, data))
                return None, recs, cov  # One scan can cover both laptop and Android.
            raise ParseError("wrong_format", "JSON is not a device scan", path.name)
    if suffix == ".zip":
        try:
            zf = zipfile.ZipFile(path)
        except zipfile.BadZipFile:
            raise ParseError("corrupt_zip", "This zip is damaged. Download it again.", path.name)
        with zf:
            if instagram.is_instagram_zip(zf):
                recs, cov, _ = instagram.parse(zf, path.name)
                return "instagram", recs, cov
            if spotify.is_spotify_zip(zf):
                recs, cov = spotify.parse(zf, path.name)
                return "spotify", recs, cov
            chats = [n for n in zf.namelist() if n.endswith(".txt") and ("_chat" in n or "WhatsApp Chat" in n)]
            if chats:
                recs, _ = whatsapp.parse_text(_wa_text(zf.read(chats[0])), chats[0], wa_offset)
                return "whatsapp", recs, _wa_cov()
            hist = [n for n in zf.namelist() if n.rsplit("/", 1)[-1] == "History"]
            if hist:  # zipped browser profile: extract to project-drive temp, parse, delete
                TMP.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(dir=TMP) as d:
                    zf.extractall(d)
                    prof = Path(d) / hist[0].rsplit("/", 1)[0] if "/" in hist[0] else Path(d)
                    recs, cov = chrome.parse(prof, path.name)
                return "chrome", recs, cov
            boxes = [n for n in zf.namelist() if n.lower().endswith(".mbox")]
            if boxes:  # Takeout: mailbox needs a real file, extract to project-drive temp
                TMP.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=TMP, suffix=".mbox", delete=False) as out:
                    shutil.copyfileobj(zf.open(boxes[0]), out)
                try:
                    recs, cov = mbox.parse(out.name, boxes[0])
                finally:
                    Path(out.name).unlink(missing_ok=True)
                return "gmail", recs, cov
    elif suffix == ".txt":
        recs, _ = whatsapp.parse_text(_wa_text(path.read_bytes()), path.name, wa_offset)
        return "whatsapp", recs, _wa_cov()
    elif suffix == ".mbox":
        recs, cov = mbox.parse(str(path), path.name)
        return "gmail", recs, cov
    raise ParseError("wrong_format", "We don't recognise this file.", path.name)


def _wa_cov():
    return {"location": "not_found", "interest": "not_assessed", "contact": "found", "activity": "found"}


def run(paths, progress=lambda *a: None, cancel=None) -> dict:
    records, coverage, errors = [], {}, []
    source_coverage = []
    media = ocr.VIDEO | ocr.IMAGE
    # recordings last: OCR snaps names to people already found in the exports
    paths = sorted((Path(p) for p in paths), key=lambda p: p.suffix.lower() in media)
    for i, p in enumerate(paths):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        progress("parse", p.name, int(80 * i / max(len(paths), 1)))
        records_before, errors_before, coverage_before = len(records), len(errors), len(source_coverage)
        try:
            if p.suffix.lower() in media:
                known = sorted({n for r in records for n in [r.meta.get("person")] if n})
                recs, cov = ocr.parse(p, known)
                platform = recs[0].platform
                records += recs
                prev = coverage.get(platform, {})
                coverage[platform] = {k: ("found" if "found" in (v, prev.get(k)) else prev.get(k, v)) for k, v in cov.items()}
                continue
            platform, recs, cov = _detect_and_parse(p, sum(r.platform == "whatsapp" for r in records), warnings=errors, source_coverage=source_coverage)
            records += recs
            sections = cov if platform is None else {platform: cov}
            for name, values in sections.items():
                prev = coverage.get(name, {})
                coverage[name] = {k: ("found" if "found" in (v, prev.get(k)) else v) for k, v in values.items()}
        except ParseError as e:
            errors.append(e.to_dict())
        except Exception as e:  # never crash the whole run on one file
            errors.append({"code": "unknown", "message": str(e), "file": p.name})
        finally:
            if len(source_coverage) == coverage_before:
                added = records[records_before:]
                issues = errors[errors_before:]
                platforms = sorted({r.platform for r in added})
                source_coverage.append({"name": p.name, "source": str(p), "platform": ", ".join(platforms), "kind": "import",
                                        "status": "partial" if issues and added else "unavailable" if issues else "scanned",
                                        "records": len(added), "detail": "; ".join(str(error.get("message", "Unavailable")) for error in issues)
                                        if issues else f"{len(added)} records extracted by the supported parser; other contents were not assessed."})
    # only chat-export messages carry chat/senders; OCR status records do not
    whatsapp.assign_owner([r for r in records if r.platform == "whatsapp" and "chat" in r.meta])
    progress("rules", "", 90)
    findings, summary = build_findings(records)
    graph = build_graph(records, summary)
    progress("done", "", 100)
    result = {
        "records": [to_dict(r) for r in records],
        "findings": [to_dict(f) for f in findings],
        "coverage": coverage,
        "summary": summary,
        "graph": graph,
        "errors": errors,
        "sourceCoverage": source_coverage,
    }
    result["sourceCoverage"] = coverage_rows(result)
    return result
