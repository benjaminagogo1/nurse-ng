"""Actionable browser installation and optional native downloads."""

from io import BytesIO

import pytest
from PIL import Image
from pydantic import ValidationError

from app.core.config import Settings, settings
from tests.helpers import has_element, register_and_sign_in


def test_browser_installation_is_available_before_native_downloads(client, monkeypatch):
    monkeypatch.setattr(settings, "android_app_download_url", "")
    monkeypatch.setattr(settings, "ios_app_download_url", "")
    assert 'data-mobile-install' not in client.get('/').text
    register_and_sign_in(client)
    assert 'data-mobile-install' in client.get('/').text
    assert has_element(client.get('/'), 'button', type='button', **{
        'aria-label': 'Dismiss installation reminder',
    })
    assert 'Install the app' in client.get('/settings').text
    page = client.get('/app')
    assert page.status_code == 200
    assert 'data-web-install' in page.text
    assert 'Install on Android' in page.text
    assert 'Install on iPhone' in page.text
    assert 'Add to Home Screen' in page.text
    assert 'Installing on a computer' in page.text
    assert 'release is being prepared' not in page.text
    assert 'download is being prepared' not in page.text
    assert 'data-android-download' not in page.text
    assert 'data-ios-download' not in page.text
    # The existing web application remains usable throughout mobile preparation.
    assert client.get('/jobs').status_code == 200
    assert client.get('/feed').status_code == 200
    assert client.get('/settings').status_code == 200


def test_install_manifest_and_touch_icon_reference_real_sized_images(client):
    response = client.get('/manifest.webmanifest')
    assert response.headers['content-type'].startswith('application/manifest+json')
    manifest = response.json()
    assert manifest['id'] == manifest['start_url'] == manifest['scope'] == '/'
    assert manifest['display'] == 'standalone'
    images = {icon['sizes']: icon for icon in manifest['icons'] if icon['type'] == 'image/png'}
    assert {'192x192', '512x512'} <= images.keys()
    for dimensions, icon in images.items():
        response = client.get(icon['src'])
        assert response.status_code == 200
        assert response.headers['content-type'].startswith('image/png')
        with Image.open(BytesIO(response.content)) as image:
            assert image.size == tuple(int(size) for size in dimensions.split('x'))
    page = client.get('/app').text
    assert 'rel="apple-touch-icon" href="/static/img/app-icon-180.png"' in page
    with Image.open(BytesIO(client.get('/static/img/app-icon-180.png').content)) as image:
        assert image.size == (180, 180)


def test_published_downloads_are_actionable_and_can_be_shared(client, monkeypatch):
    monkeypatch.setattr(settings, 'android_app_download_url', '/downloads/nurse-ng.apk')
    monkeypatch.setattr(settings, 'ios_app_download_url', 'https://apps.apple.com/app/id123456')
    page = client.get('/app')
    assert 'href="/downloads/nurse-ng.apk"' in page.text
    assert 'href="https://apps.apple.com/app/id123456"' in page.text
    downloads = page.text.split('<div class="mobile-downloads">', 1)[1].split('</div>', 1)[0]
    assert 'disabled' not in downloads


@pytest.mark.parametrize('url', [
    'javascript:alert(1)', '//example.org/app.apk', '/\\example.org/app.apk',
    'https://member:secret@example.org/app.apk', 'http://example.org/app.apk',
    'https://example.org/\napp.apk',
])
def test_download_configuration_rejects_unsafe_links(url):
    with pytest.raises(ValidationError, match='Mobile app download links'):
        Settings(_env_file=None, environment='development', android_app_download_url=url)
