"""Explicit, local import validation for future authorized behavioral datasets."""
from __future__ import annotations

import csv
import json
from pathlib import Path


REQUIRED = {"category", "evidence_ref"}


def load_authorized_signals(path: Path) -> list[dict]:
    path = Path(path)
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    elif path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            data = list(csv.DictReader(stream))
    else:
        raise ValueError("Only user-selected JSON and CSV signal imports are supported")
    if not isinstance(data, list) or any(not isinstance(row, dict) or not REQUIRED <= row.keys() for row in data):
        raise ValueError("Each imported signal requires category and evidence_ref")
    return [{"category": str(row["category"]), "evidence_ref": str(row["evidence_ref"]),
             "source": str(row.get("source") or path.name), "timestamp": row.get("timestamp"),
             "provenance": f"user-selected import: {path.name}"} for row in data]
