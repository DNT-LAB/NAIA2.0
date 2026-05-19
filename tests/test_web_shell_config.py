from pathlib import Path

from core.web_shell_config import (
    DEFAULT_WEB_SHELL_BIND_HOST,
    DEFAULT_WEB_SHELL_HOST,
    DEFAULT_WEB_SHELL_PORT,
    build_web_shell_url,
    normalize_web_shell_port,
    should_launch_web_shell_by_default,
)


def test_normalize_web_shell_port_accepts_valid_values():
    assert normalize_web_shell_port("9000") == 9000
    assert normalize_web_shell_port(1024) == 1024
    assert normalize_web_shell_port(65535) == 65535


def test_normalize_web_shell_port_falls_back_for_invalid_values():
    assert normalize_web_shell_port(None) == DEFAULT_WEB_SHELL_PORT
    assert normalize_web_shell_port("abc") == DEFAULT_WEB_SHELL_PORT
    assert normalize_web_shell_port(80) == DEFAULT_WEB_SHELL_PORT
    assert normalize_web_shell_port(70000) == DEFAULT_WEB_SHELL_PORT


def test_build_web_shell_url_marks_embedded_desktop_shell():
    assert build_web_shell_url("127.0.0.1", 7243) == "http://127.0.0.1:7243/?desktop_shell=1"
    assert build_web_shell_url("localhost", 7243, embedded=False) == "http://localhost:7243/"


def test_default_web_shell_separates_load_host_from_bind_host():
    assert DEFAULT_WEB_SHELL_HOST == "127.0.0.1"
    assert DEFAULT_WEB_SHELL_BIND_HOST == "0.0.0.0"
    assert build_web_shell_url(DEFAULT_WEB_SHELL_HOST, 7243) == "http://127.0.0.1:7243/?desktop_shell=1"


def test_default_launcher_does_not_open_legacy_web_shell():
    assert not should_launch_web_shell_by_default()


def test_explicit_legacy_modes_disable_default_web_shell():
    assert not should_launch_web_shell_by_default(desktop_requested=True)
    assert not should_launch_web_shell_by_default(web_session_requested=True)


def test_web_launchers_use_headless_entrypoint():
    for launcher in ["run_NAIA_web.bat", "run_NAIA_web.command"]:
        text = Path(launcher).read_text(encoding="utf-8")
        assert "NAIA_web_headless.py" in text
        assert "NAIA_cold_v4.py --web-session" not in text


def test_desktop_launchers_are_explicit_legacy_desktop():
    for launcher in ["run_NAIA.bat", "run_NAIA.command"]:
        text = Path(launcher).read_text(encoding="utf-8")
        assert "NAIA_cold_v4.py --desktop" in text


def test_cold_v4_legacy_web_session_is_guarded():
    text = Path("NAIA_cold_v4.py").read_text(encoding="utf-8")
    assert "--allow-legacy-web-session" in text
    assert "NAIA_web_headless.py" in text
