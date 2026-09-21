import json

from agentebc.updater import (
    ReleaseManifest,
    is_newer_version,
    update_available,
)


def test_is_newer_version() -> None:
    assert is_newer_version("0.1.0", "0.2.0") is True
    assert is_newer_version("0.2.0", "0.2.0") is False
    assert is_newer_version("1.0.0", "0.9.9") is False


def test_release_manifest_from_dict() -> None:
    manifest = ReleaseManifest.from_dict(
        {
            "version": "0.2.0",
            "download_url": "https://agentebc.malla.es/releases/setup.exe",
            "sha256": "abc",
            "release_notes": "Novedades",
        }
    )
    assert manifest.version == "0.2.0"
    assert manifest.sha256 == "abc"


def test_update_available_with_mocked_manifest(monkeypatch) -> None:
    payload = json.dumps(
        {
            "version": "9.9.9",
            "download_url": "https://example.test/setup.exe",
        }
    ).encode("utf-8")

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return payload

    monkeypatch.setattr(
        "agentebc.updater.urllib.request.urlopen",
        lambda *args, **kwargs: _Response(),
    )

    manifest = update_available(current_version="0.2.0")
    assert manifest is not None
    assert manifest.version == "9.9.9"
