"""Local photo storage, linked evidence and aggregate privacy findings."""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from uuid import uuid4

from app.cancellation import check_cancel
from app.engine.records import Record, Finding, to_dict
from .analysis import MAX_BYTES, analyze_image, sha256_file, hamming

IMAGE_SUFFIXES = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tif', '.tiff'}
FILE_NAME = re.compile(r'[0-9a-f]{32}\.(?:jpg|jpeg|png|webp|bmp|tif|tiff)\Z')
MAX_IMAGES = 200


class ImageExposureStore:
    def __init__(self, root):
        self.project = Path(root).resolve()
        self.root = self.project / '.cache' / 'image-exposure'
        self.index = self.root / 'index.json'

    def _check_root(self):
        if self.root.resolve() != self.root or not self.root.resolve().is_relative_to(self.project):
            raise ValueError('Image storage must stay within the project cache')

    def list(self):
        self._check_root()
        try:
            rows = json.loads(self.index.read_text(encoding='utf-8'))
            if not isinstance(rows, list):
                return []
            return [r for r in rows if isinstance(r, dict) and isinstance(r.get('file'), str)
                    and FILE_NAME.fullmatch(r['file']) and isinstance(r.get('id'), str)
                    and r['id'] == 'photo-img-' + r['file'].split('.')[0]
                    and (self.root / r['file']).resolve().parent == self.root][:MAX_IMAGES]
        except (OSError, ValueError):
            return []

    def _write(self, rows):
        self._check_root()
        self.root.mkdir(parents=True, exist_ok=True)
        name = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.root, suffix='.tmp', delete=False) as stream:
                name = stream.name
                json.dump(rows, stream, ensure_ascii=False, allow_nan=False)
            os.replace(name, self.index)
        finally:
            if name:
                Path(name).unlink(missing_ok=True)

    def add(self, paths):
        self._check_root()
        rows, added, created = self.list(), [], []
        known = {r.get('selection_key') for r in rows}
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            for path in map(Path, paths):
                check_cancel()
                if path.suffix.lower() not in IMAGE_SUFFIXES:
                    raise ValueError('Select JPEG, PNG, WebP, BMP or TIFF photos')
                if path.stat().st_size > MAX_BYTES:
                    raise ValueError('Image exceeds the 25 MB local analysis limit')
                key = hashlib.sha256(str(path.resolve()).casefold().encode()).hexdigest()
                digest = sha256_file(path)
                selection_key = key + digest
                if selection_key in known:
                    continue
                if len(rows) + len(added) >= MAX_IMAGES:
                    raise ValueError('Clear images before exceeding the 200 photo limit')
                name = uuid4().hex + path.suffix.lower()
                stored = self.root / name
                # Analyze the retained copy so evidence describes exactly those bytes.
                created.append(stored)
                shutil.copyfile(path, stored)
                analysis = analyze_image(stored)
                added.append({'id': 'photo-img-' + name.split('.')[0], 'file': name,
                              'original_name': path.name, 'selection_key': selection_key, **analysis})
                known.add(selection_key)
            self._write(rows + added)
        except BaseException:
            for path in created:
                path.unlink(missing_ok=True)
            raise
        return added

    def clear_images(self):
        """Delete retained copies only, never user originals or paths from an index."""
        self._check_root()
        if self.root.exists():
            for path in self.root.iterdir():
                check_cancel()
                if path.is_file() and FILE_NAME.fullmatch(path.name):
                    path.unlink()
            self._write([])


def scan_exposure(store, *, use_ocr=False):
    records, errors, images = [], [], []
    for row in store.list():
        check_cancel()
        path = store.root / row['file']
        try:
            current = analyze_image(path, ocr=use_ocr)
        except (OSError, ValueError):
            errors.append({'code': 'photo_unavailable', 'message': 'A retained photo could not be analyzed.', 'file': row['file']})
            continue
        rid = row['id']
        records.append(Record(rid, 'device', 'device', 'User-selected local photo', None,
                              sourceFile=str(path), recordRef=row.get('original_name', 'Selected photo'),
                              meta={'source': 'local_photo', **current}))
        images.append({'id': rid, 'name': row.get('original_name', 'Selected photo'), **current})
    gps = [r.id for r in records if 'latitude' in r.meta['metadata'] and 'longitude' in r.meta['metadata']]
    camera = [r.id for r in records if any(k in r.meta['metadata'] for k in ('camera_make', 'camera_model', 'software', 'timestamp', 'timestamp_original'))]
    text = [r.id for r in records if r.meta['sensitive_text']]
    exact, similar, groups = [], [], defaultdict(list)
    for row in images:
        groups[row['sha256']].append(row['id'])
    for ids in groups.values():
        exact.extend(ids[1:])
    similar_ids = set()
    for i, row in enumerate(images):
        check_cancel()
        for other in images[:i]:
            if row['sha256'] != other['sha256'] and hamming(row['phash'], other['phash']) <= 6:
                similar.append({'evidence': [other['id'], row['id']], 'distance': hamming(row['phash'], other['phash'])})
                similar_ids.update((other['id'], row['id']))
    findings = []

    def finding(key, title, ids, detail, priority, steps):
        if ids:
            findings.append(Finding('photo-f-' + key, 3, title, detail, priority, 'device', ['device'],
                                    {'value': len(ids), 'unit': 'photos'}, sorted(ids), {'steps': steps, 'link': ''}))

    finding('gps', f'{len(gps)} of your photos contain GPS location', gps,
            'Embedded coordinates can reveal a stored location. They do not independently prove where a photo was taken.', 'high',
            ['Review the linked photo evidence.', 'Remove location metadata from a sharing copy; keep your original if needed.'])
    finding('camera', f'{len(camera)} of your photos contain camera or timestamp metadata', camera,
            'Camera, editing-software or capture-time fields may reveal device and timing information.', 'low',
            ['Review metadata before sharing.', 'Export a copy without metadata when appropriate.'])
    finding('text', f'{len(text)} of your photos contain potential identifying text', text,
            'Local OCR found sensitive pattern types only. No recognized text was retained; manually confirm each flag.', 'medium',
            ['Review each photo for context and OCR accuracy.', 'Crop or blur identifying content before sharing.'])
    duplicate_ids = {rid for ids in groups.values() if len(ids) > 1 for rid in ids}
    finding('duplicates', f'{len(exact)} extra exact duplicate photos selected', duplicate_ids,
            'SHA-256 matches identify identical retained bytes. These are local copies, not evidence of publication.', 'low',
            ['Review linked duplicate copies.', 'Clear retained images when you finish reviewing.'])
    finding('similar', f'{len(similar)} visually similar photo pairs selected', similar_ids,
            'Perceptual hashes suggest visual similarity and can produce false matches; this is not proof of the same photo or online exposure.', 'low',
            ['Compare the linked images manually.'])
    return {'records': [to_dict(r) for r in records], 'findings': [to_dict(f) for f in findings], 'errors': errors,
            'images': images, 'similarPairs': similar,
            'summary': {'imagesAnalyzed': len(images), 'locationMetadata': len(gps), 'cameraMetadata': len(camera),
                        'potentialIdentifiers': len(text), 'exactDuplicates': len(exact), 'similarPairs': len(similar)},
            'limitations': 'Only user-selected retained photos were checked locally. No upload, public search or account search occurred.'}
