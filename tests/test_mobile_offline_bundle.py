"""A native cold start must need no cached document, server asset or credential."""

import importlib.util
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "mobile_bundle", ROOT / "mobile/scripts/bundle-offline.py"
)
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)


def test_bundled_workspace_is_neutral_and_contains_all_executable_assets():
    document = bundle.build()
    assert 'data-offline-shell="true"' in document
    assert 'data-offline-session="unknown"' in document
    assert 'data-draft-scope=""' in document
    assert "window.NurseNativeOffline = true" in document
    assert 'data-offline-editor' in document
    assert 'id="offline-profile-template"' in document
    assert 'data-offline-drafts' in document
    assert 'data-offline-records' in document
    assert 'data-offline-operations' in document
    assert 'activity-csrf' not in document
    assert 'name="csrf_token"' not in document
    assert "bundle.invalid" not in document

    class Resources(HTMLParser):
        def handle_starttag(self, tag, attrs):
            attributes = dict(attrs)
            if tag in {"script", "img", "iframe", "source"}:
                assert not attributes.get("src") or attributes["src"].startswith("data:")
            if tag == "link":
                assert attributes.get("rel") == "icon"
                assert attributes["href"].startswith("data:")

    Resources().feed(document)
    styles = re.findall(r"<style>(.*?)</style>", document, re.S)
    assert styles
    for css in styles:
        assert all(url.strip("\"' ").startswith("data:")
                   for url in re.findall(r"url\(([^)]+)\)", css))
    # Tests the actual packaged store and sync client, not a placeholder retry page.
    for name in ["offline-store", "offline", "offline-sync", "offline-data", "offline-content"]:
        assert (ROOT / f"app/static/js/{name}.js").read_text() in document


@pytest.mark.parametrize("url", ["https://example.org/a.js", "//example.org/a.js",
                                      "/static/../../private.key", "../../../private.key"])
def test_bundle_rejects_external_assets_and_paths_outside_static(url):
    with pytest.raises(ValueError):
        bundle.asset(url)
