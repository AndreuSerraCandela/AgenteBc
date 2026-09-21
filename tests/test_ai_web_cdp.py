from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agentebc.ai_web_cdp import (
    AiWebCdpError,
    ensure_ai_web_cdp_ready,
    is_cdp_available,
)


def test_is_cdp_available_true() -> None:
    response = MagicMock()
    response.status = 200
    response.__enter__ = MagicMock(return_value=response)
    response.__exit__ = MagicMock(return_value=False)

    with patch(
        "agentebc.ai_web_cdp.urllib.request.urlopen",
        return_value=response,
    ) as urlopen:
        assert is_cdp_available("http://127.0.0.1:9222") is True

    urlopen.assert_called_once()


def test_is_cdp_available_false_on_connection_error() -> None:
    with patch(
        "agentebc.ai_web_cdp.urllib.request.urlopen",
        side_effect=OSError("connection refused"),
    ):
        assert is_cdp_available("http://127.0.0.1:9222") is False


def test_ensure_does_not_launch_when_cdp_is_ready() -> None:
    with (
        patch("agentebc.ai_web_cdp.is_cdp_available", return_value=True) as check,
        patch("agentebc.ai_web_cdp.subprocess.Popen") as popen,
    ):
        ensure_ai_web_cdp_ready(
            "http://127.0.0.1:9222",
            "https://www.google.com/ai",
        )

    check.assert_called_once()
    popen.assert_not_called()


def test_ensure_launches_chrome_when_cdp_is_down(tmp_path: Path) -> None:
    availability = iter([False, False, True])

    with (
        patch(
            "agentebc.ai_web_cdp.is_cdp_available",
            side_effect=lambda *_args, **_kwargs: next(availability),
        ),
        patch(
            "agentebc.ai_web_cdp.find_chrome_executable",
            return_value=tmp_path / "chrome.exe",
        ),
        patch("agentebc.ai_web_cdp.subprocess.Popen") as popen,
        patch("agentebc.ai_web_cdp.time.sleep"),
    ):
        (tmp_path / "chrome.exe").write_text("", encoding="utf-8")
        ensure_ai_web_cdp_ready(
            "http://127.0.0.1:9222",
            "https://chat.deepseek.com",
            profile_dir=tmp_path / "profile",
        )

    popen.assert_called_once()
    args = popen.call_args.args[0]
    assert "--remote-debugging-port=9222" in args
    assert any("profile" in arg for arg in args)
    assert "https://chat.deepseek.com" in args


def test_ensure_raises_when_chrome_does_not_start(tmp_path: Path) -> None:
    with (
        patch("agentebc.ai_web_cdp.is_cdp_available", return_value=False),
        patch(
            "agentebc.ai_web_cdp.find_chrome_executable",
            return_value=tmp_path / "chrome.exe",
        ),
        patch("agentebc.ai_web_cdp.subprocess.Popen"),
        patch("agentebc.ai_web_cdp.time.sleep"),
        patch("agentebc.ai_web_cdp.time.monotonic", side_effect=[0.0, 25.0]),
    ):
        (tmp_path / "chrome.exe").write_text("", encoding="utf-8")
        with pytest.raises(AiWebCdpError, match="Inicia sesión manualmente"):
            ensure_ai_web_cdp_ready(
                "http://127.0.0.1:9222",
                "https://www.google.com/ai",
                profile_dir=tmp_path / "profile",
                launch_wait_seconds=20.0,
            )
