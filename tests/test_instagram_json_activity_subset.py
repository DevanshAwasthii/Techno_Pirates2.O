"""List-form Instagram likes are a supported activity subset; all values are fictional."""
import json
import zipfile

from app.pipeline import run


def test_list_form_json_likes_subset(tmp_path):
    path = tmp_path / 'synthetic_likes.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('your_instagram_activity/likes/liked_posts.json', json.dumps([
            {'title': 'fictional_creator', 'string_list_data': [{'timestamp': 1760000000}]}]))
    result = run([path])
    assert result['errors'] == []
    assert len(result['records']) == 1
    assert result['records'][0]['meta']['action'] == 'like'
    assert result['records'][0]['meta']['person'] == 'fictional_creator'
    assert result['connections'][0]['counts']['like'] == 1


def test_list_form_json_off_meta_subset(tmp_path):
    path = tmp_path / 'synthetic_off_meta.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('apps_and_websites/your_activity_off_meta_technologies.json', json.dumps([
            {'name': 'fictional.invalid', 'events': [{'timestamp': 1760000000}]}]))
    result = run([path])
    assert result['errors'] == []
    assert len(result['records']) == 1
    assert result['records'][0]['meta']['source'] == 'off_meta'
    assert result['records'][0]['meta']['events'] == 1
    assert result['profile']['shopping'][0]['evidence'] == [result['records'][0]['id']]
