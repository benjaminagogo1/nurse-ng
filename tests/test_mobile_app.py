"""Member install entry and truthful native download availability."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings, settings
from tests.helpers import register_and_sign_in


def test_install_entry_is_visible_to_members_before_downloads_are_published(client, monkeypatch):
    monkeypatch.setattr(settings, "android_app_download_url", "")
    monkeypatch.setattr(settings, "ios_app_download_url", "")
    assert 'data-mobile-install' not in client.get('/').text
    register_and_sign_in(client)
    assert 'data-mobile-install' in client.get('/').text
    assert 'Install the app' in client.get('/settings').text
    page = client.get('/app')
    assert page.status_code == 200
    assert 'Android download is being prepared' in page.text
    assert 'iPhone release is being prepared' in page.text
    assert 'data-android-download' not in page.text
    assert 'data-ios-download' not in page.text
    # The existing web application remains usable throughout mobile preparation.
    assert client.get('/jobs').status_code == 200
    assert client.get('/feed').status_code == 200
    assert client.get('/settings').status_code == 200


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
