from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from PIL.TiffImagePlugin import IFDRational

from app.image_exposure.analysis import analyze_image
from app.image_exposure.service import ImageExposureStore, scan_exposure


def photo(path, gps=False):
    image = Image.new('RGB', (240, 120), 'white')
    ImageDraw.Draw(image).rectangle((20, 30, 80, 90), fill='blue')
    exif = Image.Exif()
    exif[271] = 'Synthetic Camera'
    exif[272] = 'Test Model'
    exif[34665] = {36867: '2026:11:20 09:10:00'}
    if gps:
        exif[34853] = {1: 'N', 2: (IFDRational(12), IFDRational(30), IFDRational(0)),
                       3: 'E', 4: (IFDRational(77), IFDRational(15), IFDRational(0))}
    image.save(path, exif=exif)
    return path


def test_generated_gps_camera_metadata_and_ocr_flags(tmp_path, monkeypatch):
    from app.parsers import ocr
    monkeypatch.setattr(ocr, '_ocr', lambda: lambda image: ([([0], 'fake@example.test', .99)], 0))
    value = analyze_image(photo(tmp_path / 'gps.jpg', True), ocr=True)
    assert value['metadata']['latitude'] == 12.5
    assert value['metadata']['longitude'] == 77.25
    assert value['metadata']['camera_make'] == 'Synthetic Camera'
    assert value['metadata']['timestamp_original'] == '2026:11:20 09:10:00'
    assert value['sensitive_text'] == ['Email address']
    assert 'fake@example.test' not in str(value)
    assert len(value['sha256']) == 64 and len(value['phash']) == 16


def test_store_duplicates_findings_evidence_clear_and_originals(tmp_path):
    original = photo(tmp_path / 'one.jpg', True)
    duplicate = tmp_path / 'two.jpg'
    duplicate.write_bytes(original.read_bytes())
    store = ImageExposureStore(tmp_path)
    store.add([original, duplicate])
    assert len(store.list()) == 2
    store.add([original])
    assert len(store.list()) == 2
    result = scan_exposure(store)
    assert result['summary']['imagesAnalyzed'] == 2
    assert result['summary']['exactDuplicates'] == 1
    assert result['summary']['locationMetadata'] == 2
    assert any('2 of your photos contain GPS location' in f['title'] for f in result['findings'])
    ids = {r['id'] for r in result['records']}
    assert all(set(f['evidence']) <= ids for f in result['findings'])
    assert all(r['platform'] == 'device' and r['meta']['source'] == 'local_photo' for r in result['records'])
    assert all(Path(r['sourceFile']).is_relative_to(store.root) for r in result['records'])
    store.clear_images()
    assert store.list() == [] and original.exists() and duplicate.exists()
    assert not list(store.root.glob('*.jpg'))


def test_similar_image_invalid_input_and_failed_ocr(tmp_path, monkeypatch):
    from app.parsers import ocr
    a = photo(tmp_path / 'a.jpg')
    with Image.open(a) as image:
        image.save(tmp_path / 'b.jpg', quality=60)
    monkeypatch.setattr(ocr, '_ocr', lambda: (_ for _ in ()).throw(RuntimeError('offline failure')))
    value = analyze_image(a, ocr=True)
    assert not value['ocr_available'] and value['metadata']
    store = ImageExposureStore(tmp_path)
    store.add([a, tmp_path / 'b.jpg'])
    result = scan_exposure(store)
    assert result['summary']['similarPairs'] == 1
    bad = tmp_path / 'bad.jpg'
    bad.write_text('not an image')
    with pytest.raises(ValueError): store.add([bad])
    assert len(store.list()) == 2


def test_tampered_index_cannot_read_or_delete_outside_storage(tmp_path):
    import json
    outside = photo(tmp_path / 'outside.jpg')
    store = ImageExposureStore(tmp_path)
    store.root.mkdir(parents=True)
    store.index.write_text(json.dumps([{'id': 'evil', 'file': str(outside)}]))
    assert store.list() == []
    store.clear_images()
    assert outside.exists()


def test_add_cancellation_rolls_back_retained_copies(tmp_path, monkeypatch):
    from app.cancellation import Cancelled
    from app.image_exposure import service
    store = ImageExposureStore(tmp_path)
    original = photo(tmp_path / 'original.jpg')
    def cancel(*a, **k): raise Cancelled()
    monkeypatch.setattr(service, 'analyze_image', cancel)
    with pytest.raises(Cancelled): store.add([original])
    assert store.list() == [] and original.exists()
    assert not list(store.root.glob('*.jpg'))
