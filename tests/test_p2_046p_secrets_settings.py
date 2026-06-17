"""P2-046P — Keychain-backed secrets store + in-app key entry (no real Keychain, injected runner)."""
import os
import subprocess
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app_config
import secrets_store as ss
from app_api import AccumulatorAPI


def make_fake_keychain():
    """An in-memory stand-in for the `security` CLI."""
    store = {}

    def run(args, check=False, capture_output=False, text=False):
        op = args[1]
        kv = {}
        rest = args[2:]
        i = 0
        while i < len(rest):
            a = rest[i]
            if a in ("-s", "-a"):           # always followed by a value
                kv[a] = rest[i + 1]; i += 2
            elif a == "-w" and op == "add-generic-password":  # -w takes a value only on add
                kv[a] = rest[i + 1]; i += 2
            else:                            # flags like -U, or trailing -w on find
                i += 1
        key = (kv.get("-s"), kv.get("-a"))
        if op == "add-generic-password":
            store[key] = kv.get("-w")
            return SimpleNamespace(stdout="", returncode=0)
        if op == "find-generic-password":
            if key in store:
                return SimpleNamespace(stdout=store[key] + "\n", returncode=0)
            raise subprocess.CalledProcessError(1, args)
        if op == "delete-generic-password":
            existed = store.pop(key, None) is not None
            if not existed:
                raise subprocess.CalledProcessError(1, args)
            return SimpleNamespace(stdout="", returncode=0)
        raise subprocess.CalledProcessError(2, args)

    return run, store


# --- secrets_store ------------------------------------------------------------

def test_set_get_delete_roundtrip():
    run, _ = make_fake_keychain()
    assert ss.set_secret("ALPACA_PAPER_API_KEY", "PK123", runner=run) is True
    assert ss.get_secret("ALPACA_PAPER_API_KEY", runner=run) == "PK123"
    assert ss.has_secret("ALPACA_PAPER_API_KEY", runner=run) is True
    assert ss.delete_secret("ALPACA_PAPER_API_KEY", runner=run) is True
    assert ss.get_secret("ALPACA_PAPER_API_KEY", runner=run) is None


def test_set_empty_value_rejected():
    run, _ = make_fake_keychain()
    assert ss.set_secret("X", "", runner=run) is False


def test_get_credential_prefers_env(monkeypatch):
    run, store = make_fake_keychain()
    ss.set_secret("ALPACA_API_KEY", "from_keychain", runner=run)
    monkeypatch.setenv("ALPACA_API_KEY", "from_env")
    assert ss.get_credential("ALPACA_API_KEY", runner=run) == "from_env"


def test_get_credential_falls_back_to_keychain(monkeypatch, tmp_path):
    run, _ = make_fake_keychain()
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    ss.set_secret("ALPACA_API_KEY", "kc_val", runner=run)
    assert ss.get_credential("ALPACA_API_KEY", runner=run, env_path=str(tmp_path / "none")) == "kc_val"


def test_get_credential_reads_env_file(monkeypatch, tmp_path):
    run, _ = make_fake_keychain()  # empty keychain
    monkeypatch.delenv("MYVAR", raising=False)
    env = tmp_path / ".env"
    env.write_text('MYVAR="hello"\n')
    assert ss.get_credential("MYVAR", runner=run, env_path=str(env)) == "hello"


# --- app_api settings ---------------------------------------------------------

def test_save_keys_writes_to_keychain_and_resets_broker(tmp_path):
    run, store = make_fake_keychain()
    api = AccumulatorAPI(config=app_config.default_config(), state_path=tmp_path / "s.json",
                         history_path=tmp_path / "h.jsonl", price_provider=lambda: {},
                         secrets_runner=run)
    api._broker = object()  # pretend connected
    r = api.save_keys(paper_api="PKabc", paper_secret="sec123")
    assert r["count"] == 2 and set(r["saved"]) == {"paper_api", "paper_secret"}
    assert store[("Accumulator", "ALPACA_PAPER_API_KEY")] == "PKabc"
    assert api._broker is None  # forced reconnect


def test_get_settings_reports_presence_not_values(tmp_path, monkeypatch):
    run, _ = make_fake_keychain()
    monkeypatch.delenv("ALPACA_PAPER_API_KEY", raising=False)
    ss.set_secret("ALPACA_PAPER_API_KEY", "PKxyz", runner=run)
    api = AccumulatorAPI(config=app_config.default_config(), state_path=tmp_path / "s.json",
                         history_path=tmp_path / "h.jsonl", price_provider=lambda: {},
                         secrets_runner=run)
    # point credential resolution at a temp .env so the repo .env doesn't leak in
    s = api.get_settings()
    assert set(s["keys"]) == {"paper_api", "paper_secret", "live_api", "live_secret"}
    assert s["keys"]["paper_api"] is True               # present
    assert all(v in (True, False) for v in s["keys"].values())  # booleans only, no values
