from core.web_shell_config import (
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


def test_default_launcher_prefers_web_shell():
    assert should_launch_web_shell_by_default()


def test_explicit_legacy_modes_disable_default_web_shell():
    assert not should_launch_web_shell_by_default(desktop_requested=True)
    assert not should_launch_web_shell_by_default(web_session_requested=True)
