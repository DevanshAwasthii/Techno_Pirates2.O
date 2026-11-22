"""Bounded image fingerprints, EXIF metadata and optional local OCR pattern flags."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import warnings

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError

from app.cancellation import Cancelled, check_cancel
from app.engine.messages import scan_text

MAX_BYTES = 25 * 1024 * 1024
MAX_PIXELS = 20_000_000


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            check_cancel()
            digest.update(block)
    return digest.hexdigest()


def _phash(image):
    gray = np.asarray(image.convert('L').resize((32, 32)), dtype=np.float32)
    frequencies = cv2.dct(gray)[:8, :8].flatten()
    bits = frequencies > np.median(frequencies[1:])
    bits[0] = False
    return f"{int(''.join('1' if bit else '0' for bit in bits), 2):016x}"


def hamming(left, right):
    return (int(left, 16) ^ int(right, 16)).bit_count()


def _metadata(image):
    result = {}
    try:
        exif = image.getexif()
        for key, name in ((271, 'camera_make'), (272, 'camera_model'), (305, 'software'), (306, 'timestamp')):
            if exif.get(key):
                result[name] = str(exif[key])[:500]
        nested = exif.get_ifd(34665)
        if nested.get(36867):
            result['timestamp_original'] = str(nested[36867])[:100]
        gps = exif.get_ifd(34853)

        def degrees(values, ref, limit):
            if ref not in ('N', 'S', 'E', 'W') or not isinstance(values, (tuple, list)) or len(values) != 3:
                return None
            a, b, c = map(float, values)
            if not all(math.isfinite(v) for v in (a, b, c)) or not (0 <= b < 60 and 0 <= c < 60):
                return None
            value = a + b / 60 + c / 3600
            return (-value if ref in ('S', 'W') else value) if 0 <= value <= limit else None

        lat, lon = degrees(gps.get(2), gps.get(1), 90), degrees(gps.get(4), gps.get(3), 180)
        if lat is not None and lon is not None:
            result.update(latitude=lat, longitude=lon)
    except (OSError, ValueError, TypeError, AttributeError, KeyError, ZeroDivisionError, OverflowError, SyntaxError):
        pass  # Fingerprints remain useful even when EXIF is malformed.
    return result


def analyze_image(path, *, ocr=False):
    path = Path(path)
    check_cancel()
    if path.stat().st_size > MAX_BYTES:
        raise ValueError('Image exceeds the 25 MB local analysis limit')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(path) as image:
                width, height = image.size
                if width * height > MAX_PIXELS:
                    raise ValueError('Image exceeds the 20 megapixel local analysis limit')
                metadata = _metadata(image)
                image.load()
                result = {'sha256': sha256_file(path), 'phash': _phash(image),
                          'dimensions': {'width': width, 'height': height}, 'metadata': metadata,
                          'sensitive_text': [], 'ocr_available': False}
                if ocr:
                    try:
                        check_cancel()
                        from app.parsers.ocr import _ocr
                        # OCR sees a bounded rendering; recognized text is never persisted.
                        preview = image.convert('RGB')
                        preview.thumbnail((2400, 2400))
                        rows, _ = _ocr()(cv2.cvtColor(np.asarray(preview), cv2.COLOR_RGB2BGR))
                        text = ' '.join(row[1] for row in (rows or []) if row[2] > .5)
                        result['sensitive_text'] = sorted(set(scan_text(text)))
                        result['ocr_available'] = True
                    except Cancelled:
                        raise
                    except Exception:
                        pass  # Supplementary OCR failure never hides metadata checks.
                check_cancel()
                return result
    except (UnidentifiedImageError, OSError, Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise ValueError('The selected file is not a supported, bounded image') from exc
