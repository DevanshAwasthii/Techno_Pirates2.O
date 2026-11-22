"""Runtime root override; the installed package location remains the default."""
import os
from pathlib import Path


def project_root():
    override = os.environ.get('NEXDATA_ROOT')
    return Path(override).expanduser().resolve() if override else Path(__file__).resolve().parents[1]


ROOT = project_root()
