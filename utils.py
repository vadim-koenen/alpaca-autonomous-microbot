"""
utils.py — Shared utilities for the Alpaca autonomous micro-trading bot.

Handles:
- Config loading and validation
- Environment variable loading with strict secret protection
- Logging setup
- Time helpers
- Safe numeric helpers
"""

from __future__ import annotations

import logging
import hashlib
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytz
import yaml
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).parent
CONFIG_PATH = ROOT / "config.yaml"
ENV_PATH = ROOT / ".env"
RUNTIME_DIR = ROOT / "runtime"


def get_runtime_namespace() -> str:
    """
    Resolve broker namespace for runtime files.

    Required so Alpaca and Coinbase can run live at the same time without
    fighting over a single runtime/bot.lock file.
    """
    raw = " ".join([
        os.environ.get("BOT_STATE_NAMESPACE", ""),
        os.environ.get("BROKER", ""),
        os.environ.get("BOT_NAME", ""),
        os.environ.get("CONFIG_FILE", ""),
    ]).strip().lower()

    if "coinbase" in raw:
        return "coinbase"

    if "alpaca" in raw:
        return "alpaca"

    raise RuntimeError(
        "Unable to determine runtime namespace. "
        "Set BROKER=alpaca or BROKER=coinbase in the launchd plist/environment."
    )


def get_lock_file() -> Path:
    """
    Return broker-specific live lock file.

    Examples:
      runtime/alpaca.lock
      runtime/coinbase.lock
    """
    namespace = get_runtime_namespace()
    return RUNTIME_DIR / f"{namespace}.lock"


class _DynamicLockFile:
    """
    Backward-compatible proxy for old code that imports LOCK_FILE directly.

    Existing code can still call LOCK_FILE.exists(), read_text(), write_text(),
    and unlink(), but the resolved path is now broker-specific.
    """
    def _path(self) -> Path:
        return get_lock_file()

    def exists(self):
        return self._path().exists()

    def read_text(self, *args, **kwargs):
        return self._path().read_text(*args, **kwargs)

    def write_text(self, *args, **kwargs):
        return self._path().write_text(*args, **kwargs)

    def unlink(self, *args, **kwargs):
        return self._path().unlink(*args, **kwargs)

    def __fspath__(self):
        return str(self._path())

    def __str__(self):
        return str(self._path())


LOCK_FILE = _DynamicLockFile()
STOP_FILE = RUNTIME_DIR / "STOP_TRADING"

# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

_config: dict[str, Any] | None = None


def _resolve_config_path() -> Path:
    """
    Determine which config file to load.

    Priority order:
      1. CONFIG_FILE env var (absolute or relative to ROOT)
      2. Default: config.yaml in ROOT

    This allows running multiple bot instances with different configs:
      CONFIG_FILE=config_coinbase_crypto.yaml python main.py
      CONFIG_FILE=config_alpaca_stocks.yaml  python main.py
    """
    env_path = os.environ.get("CONFIG_FILE", "").strip()
    if env_path:
        p = Path(env_path)
        if not p.is_absolute():
            p = ROOT / p
        return p
    return CONFIG_PATH


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Load and cache the config file. Raises on missing file.

    If *path* is None, the config path is resolved from the CONFIG_FILE env
    var (or the default config.yaml).  Passing an explicit *path* is retained
    for backwards-compatibility with tests that supply a temporary file.
    """
    global _config
    if _config is not None:
        return _config
    resolved = path if path is not None else _resolve_config_path()
    if not resolved.exists():
        raise FileNotFoundError(f"Config file not found at {resolved}")
    with open(resolved, "r") as f:
        _config = yaml.safe_load(f)
    return _config


def get_config_path() -> Path:
    """Return the resolved config path currently used by load_config()."""
    return _resolve_config_path()


def get_cfg(*keys: str, default: Any = None) -> Any:
    """Nested key lookup: get_cfg('crypto', 'max_trade_notional_usd')."""
    cfg = load_config()
    node = cfg
    for k in keys:
        if not isinstance(node, dict):
            return default
        node = node.get(k, default)
        if node is None:
            return default
    return node


# ---------------------------------------------------------------------------
# Environment / secrets
# ---------------------------------------------------------------------------

def load_env() -> None:
    """Load .env file. Must be called before any env access."""
    if ENV_PATH.exists():
        load_dotenv(ENV_PATH, override=False)
    else:
        # Allow environment variables to be set externally (CI, Docker, etc.)
        pass


def _first_present_env_pair(pairs: list[tuple[str, str]]) -> tuple[str, str, str, str]:
    for key_name, secret_name in pairs:
        api_key = os.environ.get(key_name, "")
        secret_key = os.environ.get(secret_name, "")
        if api_key or secret_key:
            return api_key, secret_key, key_name, secret_name
    key_name, secret_name = pairs[-1]
    return os.environ.get(key_name, ""), os.environ.get(secret_name, ""), key_name, secret_name


def get_alpaca_keys() -> tuple[str, str]:
    """
    Return (api_key, secret_key).
    Raises RuntimeError if either is missing or still set to placeholder.
    Never prints/logs the values.
    """
    if is_paper():
        pairs = [
            ("ALPACA_PAPER_API_KEY", "ALPACA_PAPER_SECRET_KEY"),
            ("ALPACA_API_KEY", "ALPACA_SECRET_KEY"),
        ]
    else:
        pairs = [
            ("ALPACA_LIVE_API_KEY", "ALPACA_LIVE_SECRET_KEY"),
            ("ALPACA_API_KEY", "ALPACA_SECRET_KEY"),
        ]

    api_key, secret_key, key_name, secret_name = _first_present_env_pair(pairs)
    if not api_key or api_key == "replace_me":
        raise RuntimeError(
            f"{key_name} is not set. Edit .env and add your Alpaca API key."
        )
    if not secret_key or secret_key == "replace_me":
        raise RuntimeError(
            f"{secret_name} is not set. Edit .env and add your Alpaca secret key."
        )
    return api_key, secret_key


def is_paper() -> bool:
    """True if ALPACA_PAPER env var is 'true' (case-insensitive)."""
    return os.environ.get("ALPACA_PAPER", "true").strip().lower() == "true"


def is_live_trading_enabled() -> bool:
    """
    Returns True only when LIVE_TRADING env var is exactly the string 'true'.
    This is the master kill switch.
    """
    return os.environ.get("LIVE_TRADING", "false").strip().lower() == "true"


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

_logging_configured = False


def setup_logging(name: str = "bot") -> logging.Logger:
    """
    Configure root logger to write to console and a rotating log file.
    Safe to call multiple times; only configures once.
    """
    global _logging_configured
    cfg = load_config()
    log_dir = ROOT / cfg.get("logging", {}).get("log_dir", "logs")
    log_dir.mkdir(exist_ok=True)
    level_str = cfg.get("logging", {}).get("log_level", "INFO").upper()
    level = getattr(logging, level_str, logging.INFO)

    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not _logging_configured:
        fmt = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        # Console handler
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(fmt)
        ch.setLevel(level)

        # File handler
        log_file = log_dir / f"bot_{datetime.now(timezone.utc).strftime('%Y%m%d')}.log"
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        fh.setLevel(level)

        root = logging.getLogger()
        root.setLevel(level)
        root.addHandler(ch)
        root.addHandler(fh)
        _logging_configured = True

    return logger


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_local() -> datetime:
    cfg = load_config()
    tz_name = cfg.get("account", {}).get("timezone", "America/Chicago")
    tz = pytz.timezone(tz_name)
    return datetime.now(tz)


def utc_ts() -> str:
    return now_utc().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def data_is_stale(ts: datetime | None, max_seconds: int) -> bool:
    """Return True if ts is None or older than max_seconds ago (UTC)."""
    if ts is None:
        return True
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    age = (now_utc() - ts).total_seconds()
    return age > max_seconds


# ---------------------------------------------------------------------------
# Safe numeric helpers
# ---------------------------------------------------------------------------

def safe_float(value: Any, default: float = 0.0) -> float:
    """Parse a value to float without raising."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _order_id_token(value: Any, *, uppercase: bool = False) -> str:
    """Sanitize a client-order-id token for broker APIs and log scanning."""
    token = re.sub(r"[^A-Za-z0-9_]+", "", str(value or ""))
    if uppercase:
        return token.upper()
    return token.lower()


def build_client_order_id(
    *,
    broker: str,
    strategy: str,
    symbol: str,
    side: str,
    purpose: str,
    timestamp: datetime | None = None,
    suffix: str | None = None,
    max_length: int = 64,
) -> str:
    """
    Build a traceable, unique client_order_id accepted by both broker paths.

    Format:
      <broker>-<strategy>-<symbol>-<side>-<UTC timestamp>-<purpose>-<suffix>

    The strategy/symbol/purpose tokens may be truncated to keep the ID within
    *max_length*, but the broker, side, timestamp, and uniqueness suffix are
    preserved. Alpaca currently allows client_order_id up to 128 chars; this
    bot stays well below that and keeps Coinbase IDs compact too.
    """
    if max_length < 32:
        raise ValueError("max_length must be at least 32 for a traceable order id")

    broker_map = {
        "coinbase": "cb",
        "brokercoinbase": "cb",
        "alpaca": "alp",
        "brokeralpaca": "alp",
    }
    broker_key = _order_id_token(broker)
    broker_token = broker_map.get(broker_key, _order_id_token(broker)[:8] or "brk")
    strategy_token = _order_id_token(strategy) or "strategy"
    symbol_token = _order_id_token(symbol, uppercase=True) or "SYMBOL"
    side_token = _order_id_token(side) or "side"
    purpose_token = _order_id_token(purpose) or "order"

    ts = timestamp or now_utc()
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    ts_token = ts.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    suffix_token = _order_id_token(suffix or uuid.uuid4().hex[:4])[:8] or "0000"

    def _joined() -> str:
        return "-".join([
            broker_token,
            strategy_token,
            symbol_token,
            side_token,
            ts_token,
            purpose_token,
            suffix_token,
        ])

    # Preserve the most important routing tokens and trim human-readable fields
    # only when a long strategy/symbol name would otherwise breach max_length.
    min_lengths = {
        "strategy": 4,
        "symbol": 3,
        "purpose": 3,
    }
    while len(_joined()) > max_length:
        candidates = [
            ("strategy", len(strategy_token), min_lengths["strategy"]),
            ("symbol", len(symbol_token), min_lengths["symbol"]),
            ("purpose", len(purpose_token), min_lengths["purpose"]),
        ]
        name, length, minimum = max(candidates, key=lambda item: item[1] - item[2])
        if length <= minimum:
            break
        over_by = len(_joined()) - max_length
        cut_by = min(over_by, length - minimum)
        if name == "strategy":
            strategy_token = strategy_token[:-cut_by]
        elif name == "symbol":
            symbol_token = symbol_token[:-cut_by]
        else:
            purpose_token = purpose_token[:-cut_by]

    client_order_id = _joined()
    if len(client_order_id) > max_length:
        raise ValueError(
            f"Unable to build client_order_id within {max_length} chars: "
            f"{client_order_id}"
        )
    return client_order_id


def build_order_intent_key(
    *,
    broker: str,
    strategy: str,
    asset_class: str,
    symbol: str,
    side: str,
    purpose: str,
) -> str:
    """
    Build a stable duplicate-prevention key for an order's economic intent.

    Unlike client_order_id, this intentionally has no timestamp or random
    suffix, so restarts can recognize the same strategy/symbol/side/purpose.
    """
    broker_token = _order_id_token(broker) or "broker"
    strategy_token = _order_id_token(strategy) or "strategy"
    asset_token = _order_id_token(asset_class) or "asset"
    symbol_token = re.sub(r"\s+", "", str(symbol or "")).upper() or "SYMBOL"
    side_token = _order_id_token(side) or "side"
    purpose_token = _order_id_token(purpose) or "order"
    return ":".join([
        broker_token,
        strategy_token,
        asset_token,
        symbol_token,
        side_token,
        purpose_token,
    ])


_SECRET_CONFIG_TOKENS = (
    "api_key",
    "apikey",
    "secret",
    "token",
    "password",
    "private_key",
    "credential",
)


def sanitize_for_memory(value: Any) -> Any:
    """Return a JSON-safe object with secret-looking keys redacted."""
    if isinstance(value, dict):
        sanitized = {}
        for key, child in value.items():
            key_str = str(key)
            lower_key = key_str.lower()
            if any(token in lower_key for token in _SECRET_CONFIG_TOKENS):
                sanitized[key_str] = "<redacted>"
            else:
                sanitized[key_str] = sanitize_for_memory(child)
        return sanitized
    if isinstance(value, (list, tuple)):
        return [sanitize_for_memory(item) for item in value]
    return value


def compute_config_hash(config: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    """
    Return (sha256, sanitized_config_snapshot).

    Values under secret-looking keys are redacted before hashing and storage.
    """
    snapshot = sanitize_for_memory(config if config is not None else load_config())
    encoded = json.dumps(snapshot, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), snapshot


def calculate_crypto_exposure(open_positions: dict) -> tuple[float, float]:
    """
    Return (total_counted_crypto_exposure, broker_recovered_exposure).

    Missing counts_toward_exposure remains conservative and counts. Only an
    explicit False excludes a position from the cap calculation.
    """
    tracked_crypto_exposure = 0.0
    broker_recovered_crypto_exposure = 0.0
    for pos in open_positions.values():
        if pos.get("asset_class", "") != "crypto":
            continue
        if pos.get("counts_toward_exposure", True) is False:
            continue
        notional = safe_float(pos.get("notional", 0.0))
        tracked_crypto_exposure += notional
        if pos.get("order_status") == "broker_recovered":
            broker_recovered_crypto_exposure += notional
    return tracked_crypto_exposure, broker_recovered_crypto_exposure


def has_manual_review_entry_override(position: dict) -> bool:
    """
    Return True only for an explicit future human-approved override.

    No code path creates this automatically. It exists so a separately reviewed
    operator process can eventually allow entries while a known manual-review
    position remains open.
    """
    return (
        position.get("manual_review_entry_override_approved") is True
        and position.get("manual_review_entry_override_scope") == "allow_new_crypto_entries"
        and bool(position.get("manual_review_entry_override_reason", ""))
    )


def calculate_crypto_entry_blockers(open_positions: dict) -> tuple[int, int]:
    """
    Return (manual_review_open_count, non_controllable_open_count).

    These counts intentionally ignore counts_toward_exposure. A position can be
    excluded from exposure accounting only after human approval, but it still
    blocks unattended entries while it requires manual review or cannot be
    safely exited by the bot.
    """
    manual_review_open_count = 0
    non_controllable_open_count = 0

    for pos in open_positions.values():
        if not isinstance(pos, dict):
            continue
        if pos.get("asset_class", "") != "crypto":
            continue
        if has_manual_review_entry_override(pos):
            continue
        if pos.get("user_action_required") is True:
            manual_review_open_count += 1
        if (
            pos.get("api_controllable") is False
            or pos.get("exit_evaluation_enabled") is False
        ):
            non_controllable_open_count += 1

    return manual_review_open_count, non_controllable_open_count


BOT_OPEN_POSITION_SAFETY_DEFAULTS = {
    "counts_toward_exposure": True,
    "api_controllable": True,
    "bot_opened": True,
    "exit_evaluation_enabled": True,
    "user_action_required": False,
}

BROKER_RECOVERED_POSITION_SAFETY_FIELDS = {
    "api_controllable": False,
    "bot_opened": False,
    "exit_evaluation_enabled": False,
    "user_action_required": True,
}


def is_broker_recovered_position(position: dict) -> bool:
    """Return True when a saved position is broker-recovered/manual state."""
    return (
        position.get("order_status") == "broker_recovered"
        or (
            not position.get("order_id", "")
            and position.get("strategy") == "recovered"
        )
    )


def normalize_position_safety_fields(position: dict) -> dict:
    """
    Backfill explicit safety fields without loosening exposure accounting.

    Missing counts_toward_exposure defaults to True. An explicit False remains
    False so operator-authored state is not silently overwritten.
    """
    pos = dict(position)
    if is_broker_recovered_position(pos):
        pos["order_status"] = "broker_recovered"
        pos.setdefault("recovery_source", "broker_position")
        pos.setdefault("reconciliable", False)
        for key, value in BROKER_RECOVERED_POSITION_SAFETY_FIELDS.items():
            pos[key] = value
        pos.setdefault("counts_toward_exposure", True)
        return pos

    for key, value in BOT_OPEN_POSITION_SAFETY_DEFAULTS.items():
        pos.setdefault(key, value)
    return pos


def normalize_open_positions_safety_fields(open_positions: dict) -> dict:
    """Return a normalized copy of open position state keyed by symbol."""
    return {
        sym: normalize_position_safety_fields(pos) if isinstance(pos, dict) else pos
        for sym, pos in open_positions.items()
    }


def get_broker_name() -> str:
    """Return 'alpaca' or 'coinbase' based on BROKER env var. Default: alpaca."""
    return os.environ.get("BROKER", "alpaca").strip().lower()


def build_broker():
    """
    Broker factory. Returns the appropriate broker instance based on BROKER env var.
    This is the single place where broker selection happens; main.py calls this.
    """
    name = get_broker_name()
    if name == "coinbase":
        from broker_coinbase import BrokerCoinbase
        return BrokerCoinbase()
    else:
        from broker_alpaca import BrokerAlpaca
        return BrokerAlpaca()


def spread_pct(bid: float, ask: float) -> float:
    """Spread as a percentage of mid-price. Returns 999 if mid is zero."""
    if bid <= 0 or ask <= 0:
        return 999.0
    mid = (bid + ask) / 2.0
    if mid == 0:
        return 999.0
    return ((ask - bid) / mid) * 100.0


# ---------------------------------------------------------------------------
# Trade mode helper
# ---------------------------------------------------------------------------

def get_mode() -> str:
    """Return config mode: 'dry_run', 'paper', or 'live'."""
    return load_config().get("mode", "dry_run").lower()


def assert_not_live_without_env() -> None:
    """
    Hard guard: if mode is 'live', LIVE_TRADING env var must be 'true'.
    Raises RuntimeError otherwise.
    """
    if get_mode() == "live" and not is_live_trading_enabled():
        raise RuntimeError(
            "LIVE_TRADING=true is required in .env to run in live mode. "
            "Currently LIVE_TRADING is not set or is false. "
            "Set it explicitly only after dry_run and paper validation."
        )


# ---------------------------------------------------------------------------
# Process lock — prevents duplicate live instances per broker
# ---------------------------------------------------------------------------

def acquire_process_lock(force: bool = False) -> bool:
    """
    Write broker-specific runtime/<broker>.lock with the current PID.

    Returns True if lock was acquired.
    Returns False (does NOT raise) if another live instance is running.
    Set force=True to steal the lock regardless (use with caution).

    Only enforced in live mode — paper/dry_run are allowed to run concurrently.
    """
    if get_mode() != "live":
        return True  # no lock needed for non-live modes

    RUNTIME_DIR.mkdir(exist_ok=True)
    my_pid = os.getpid()

    if LOCK_FILE.exists() and not force:
        try:
            existing_pid = int(LOCK_FILE.read_text().strip())
            # Check if that PID is still alive
            os.kill(existing_pid, 0)   # signal 0 = existence check, no actual signal
            # Process is alive — refuse to start
            return False
        except (ProcessLookupError, PermissionError):
            # Stale lock — dead process, safe to overwrite. Log for ops visibility.
            logger = logging.getLogger("runtime_safety")
            logger.warning(
                f"Recovered stale process lock (PID {existing_pid} is dead). "
                "This can happen after hard kills or unclean shutdowns."
            )
            pass
        except ValueError:
            # Corrupt lock file — overwrite it
            pass

    LOCK_FILE.write_text(str(my_pid))
    return True


def release_process_lock() -> None:
    """Remove the lock file on clean shutdown. Safe to call multiple times."""
    try:
        if LOCK_FILE.exists():
            stored = LOCK_FILE.read_text().strip()
            if stored == str(os.getpid()):
                LOCK_FILE.unlink()
    except Exception:
        pass  # never let cleanup errors propagate


# ---------------------------------------------------------------------------
# Kill switch — operator drops runtime/STOP_TRADING to halt the bot
# ---------------------------------------------------------------------------

def kill_switch_active() -> bool:
    """
    Returns True if the operator has placed a STOP_TRADING file in runtime/.
    The file can be created with: touch runtime/STOP_TRADING
    Remove it to allow trading to resume on the next restart.
    """
    return STOP_FILE.exists()


def clear_kill_switch() -> None:
    """Remove the STOP_TRADING file (only needed in tests / manual recovery)."""
    try:
        if STOP_FILE.exists():
            STOP_FILE.unlink()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# State persistence — survive restarts without losing stop/TP levels
# ---------------------------------------------------------------------------

import json as _json
import os as _os
import sys as _sys
from datetime import datetime as _datetime

STATE_ROOT = ROOT / "state"


def _detect_state_namespace() -> str:
    """
    Determine which broker-specific state directory this process should use.

    launchd plists should provide BROKER=alpaca or BROKER=coinbase.
    Falls back to BOT_STATE_NAMESPACE / BOT_NAME / argv inspection.
    Refuses to use shared state/open_positions.json when namespace is unknown.
    """
    candidates = [
        _os.getenv("BOT_STATE_NAMESPACE", ""),
        _os.getenv("BROKER", ""),
        _os.getenv("BOT_NAME", ""),
    ]

    raw = " ".join(candidates).strip().lower()
    argv = " ".join(_sys.argv).lower()
    combined = f"{raw} {argv}"

    if "coinbase" in combined:
        return "coinbase"

    if "alpaca" in combined:
        return "alpaca"

    raise RuntimeError(
        "Unable to determine bot state namespace. "
        "Set BROKER=alpaca or BROKER=coinbase in the launchd plist/environment."
    )


def get_state_namespace() -> str:
    return _detect_state_namespace()


def get_state_dir() -> Path:
    namespace = get_state_namespace()
    state_dir = STATE_ROOT / namespace

    # Hard guard: never allow writes directly to shared state/
    if state_dir == STATE_ROOT:
        raise RuntimeError("Unsafe state directory resolved to shared state root")

    return state_dir


def get_positions_file() -> Path:
    return get_state_dir() / "open_positions.json"


def _dt_serializer(obj):
    """JSON encoder for datetime objects."""
    if isinstance(obj, _datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _dt_deserializer(d: dict) -> dict:
    """Attempt to parse known datetime fields back from ISO strings."""
    for key in ("entry_time",):
        if key in d and isinstance(d[key], str):
            try:
                from datetime import timezone
                dt = _datetime.fromisoformat(d[key])
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                d[key] = dt
            except (ValueError, AttributeError):
                pass
    return d


def save_positions(open_positions: dict) -> None:
    """
    Persist session.open_positions to broker-specific state/<broker>/open_positions.json.
    Call this after every position open or close.
    """
    try:
        state_dir = get_state_dir()
        positions_file = get_positions_file()
        state_dir.mkdir(parents=True, exist_ok=True)
        normalized_positions = normalize_open_positions_safety_fields(open_positions)
        payload = {
            "saved_at": now_utc().isoformat(),
            "state_namespace": get_state_namespace(),
            "positions": normalized_positions,
        }
        positions_file.write_text(
            _json.dumps(payload, default=_dt_serializer, indent=2)
        )
    except Exception as e:
        logging.getLogger("state").error(f"Failed to save positions: {e}")


def load_saved_positions() -> dict:
    """
    Load previously saved open_positions from disk.
    Returns empty dict if file is missing, corrupt, or stale.
    Performs a staleness check: positions older than max_position_minutes are discarded.
    """
    log = logging.getLogger("state")
    positions_file = get_positions_file()
    if not positions_file.exists():
        log.info(f"No saved positions file found at {positions_file}")
        return {}
    try:
        data = _json.loads(positions_file.read_text())
        positions = data.get("positions", {})
        saved_at_str = data.get("saved_at", "")

        # Staleness guard: if state file is very old, discard it
        if saved_at_str:
            try:
                from datetime import timezone
                saved_at = _datetime.fromisoformat(saved_at_str)
                if saved_at.tzinfo is None:
                    saved_at = saved_at.replace(tzinfo=timezone.utc)
                age_hours = (now_utc() - saved_at).total_seconds() / 3600.0
                max_hours = 24.0  # discard state older than 24h
                if age_hours > max_hours:
                    log.warning(
                        f"Saved state is {age_hours:.1f}h old (>{max_hours}h) — discarding"
                    )
                    return {}
            except Exception:
                pass

        # Deserialize datetime fields and normalise pre-patch entries.
        parsed = {}
        for sym, pos_data in positions.items():
            pos = _dt_deserializer(dict(pos_data))

            # Recovered/manual positions — no order_id, strategy=="recovered".
            # Mark broker_recovered so:
            #   1. reconciliation polling is skipped (no order_id to poll)
            #   2. exposure guard counts them toward max_total_crypto_exposure_usd
            #   3. status.sh / reconcile.sh can classify them explicitly
            # Must NOT mark these pending_new — there is no order to poll.
            if not pos.get("order_id", "") and pos.get("strategy") == "recovered":
                if "order_status" not in pos or pos.get("order_status") == "pending_new":
                    pos["order_status"] = "broker_recovered"
                    pos.setdefault("recovery_source", "broker_position")
                    pos.setdefault("reconciliable", False)
                    # Explicit classification fields so every consumer of state
                    # can answer: can we close this? should we try? does it count?
                    pos.setdefault("api_controllable", False)
                    pos.setdefault("exit_evaluation_enabled", False)
                    pos.setdefault("counts_toward_exposure", True)
                    pos.setdefault("user_action_required", True)
                    log.info(
                        f"state_normalize: recovered {sym} no order_id "
                        "marked broker_recovered "
                        "(api_controllable=False, exit_evaluation_enabled=False, "
                        "counts_toward_exposure=True, user_action_required=True)"
                    )

            # Positions saved before the order-reconciliation patch have a
            # real order_id but no order_status field.  Mark them "pending_new"
            # so _backfill_missing_order_status() will poll the broker on
            # startup and write the correct terminal value before the first
            # monitor() loop runs.
            elif pos.get("order_id", "") and "order_status" not in pos:
                pos["order_status"] = "pending_new"

            pos = normalize_position_safety_fields(pos)
            parsed[sym] = pos

        log.info(f"Loaded {len(parsed)} saved position(s) from {positions_file}")
        return parsed
    except Exception as e:
        log.error(f"Failed to load saved positions: {e}")
        return {}
