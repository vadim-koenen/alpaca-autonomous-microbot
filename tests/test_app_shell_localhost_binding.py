from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "app_shell" / "server.py"
LAUNCHER = ROOT / "scripts" / "launch_app_shell_mac.sh"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_app_shell_defaults_to_localhost_only():
    text = read(SERVER)

    assert '"127.0.0.1"' in text
    assert "APP_SHELL_HOST" in text
    assert "ReusableTCPServer((host, PORT), ReadOnlyDashboardHandler)" in text


def test_app_shell_does_not_bind_to_all_interfaces_by_default():
    text = read(SERVER)

    forbidden = [
        'TCPServer(("", PORT)',
        "TCPServer(('', PORT)",
        'TCPServer(("0.0.0.0", PORT)',
        "TCPServer(('0.0.0.0', PORT)",
    ]

    for token in forbidden:
        assert token not in text


def test_mac_launcher_does_not_force_wildcard_host():
    text = read(LAUNCHER)

    assert "APP_SHELL_HOST=0.0.0.0" not in text
    assert "APP_SHELL_HOST='0.0.0.0'" not in text
    assert 'APP_SHELL_HOST="0.0.0.0"' not in text
