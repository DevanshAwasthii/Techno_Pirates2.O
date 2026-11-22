"""Validated, atomic local preferences. Loading never enables malformed settings."""
import json
import os
from pathlib import Path
import tempfile

from .models import AIConfig


class AIConfigStore:
    def __init__(self, root):
        self.path = Path(root) / '.cache' / 'behavioral-ai.json'

    def load(self):
        try:
            return AIConfig.from_dict(json.loads(self.path.read_text(encoding='utf-8')))
        except (OSError, ValueError, TypeError):
            return AIConfig()

    def save(self, config):
        data = AIConfig.from_dict(config.to_dict()).to_dict()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        name = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.path.parent, suffix='.tmp', delete=False) as stream:
                name = stream.name
                json.dump(data, stream, indent=2, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            if name:
                Path(name).unlink(missing_ok=True)
