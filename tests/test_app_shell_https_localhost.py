from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "app_shell" / "server.py"
LAUNCHER = ROOT / "scripts" / "launch_app_shell_mac.sh"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_server_defaults_to_localhost_and_reuses_port_safely():
    text = read(SERVER)

    assert '"127.0.0.1"' in text
    assert "APP_SHELL_HOST" in text
    assert "allow_reuse_address = True" in text
    assert "ReusableTCPServer((host, PORT), ReadOnlyDashboardHandler)" in text
    assert 'TCPServer(("", PORT)' not in text
    assert 'TCPServer(("0.0.0.0", PORT)' not in text


def test_server_supports_optional_https_with_explicit_cert_paths():
    text = read(SERVER)

    assert "import ssl" in text
    assert "APP_SHELL_HTTPS" in text
    assert "APP_SHELL_CERT_FILE" in text
    assert "APP_SHELL_KEY_FILE" in text
    assert "ssl.PROTOCOL_TLS_SERVER" in text
    assert "context.load_cert_chain" in text
    assert "wrap_socket" in text


def test_launcher_uses_https_url_when_enabled_without_forcing_it():
    text = read(LAUNCHER)

    assert "APP_SHELL_HTTPS" in text
    assert 'SCHEME="http"' in text
    assert 'SCHEME="https"' in text
    assert 'URL="${SCHEME}://localhost:${PORT}"' in text
    assert "APP_SHELL_HOST=0.0.0.0" not in text
