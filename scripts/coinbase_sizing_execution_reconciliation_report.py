# ADVISORY ONLY — read-only analysis, no live trading calls.
# Do not import from: broker, order_manager, risk_manager, main.

"""
P2-006 — Coinbase Sizing / Execution Reconciliation Report

Reconstructs coinbase_exploration round trips from local journal/logs and explains
fixed-cap sizing vs dynamic sizing, buy/sell notionals, and fee-dominated P/L.
"""

from __future__ import annotations

import csv
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO_ROOT / "config_coinbase_crypto.yaml"
JOURNAL_CANDIDATES = (
    REPO_ROOT / "journal_coinbase_crypto.csv",
    REPO_ROOT / "logs" / "coinbase_journal.csv",
    REPO_ROOT / "state" / "coinbase" / "journal.csv",
    REPO_ROOT / "journal.csv",
)
PRICE_PATH_CSV = REPO_ROOT / "logs" / "coinbase_price_path.csv"

MAKER_BE_PCT = 0.60
TAKER_ROUND_TRIP_BE_PCT = 2.40
EXPLORATION_STRATEGIES = frozenset({"coinbase_exploration", "controlled_exploration"})
PROBE_STRATEGIES = frozenset({"coinbase_probe", "probe"})


@dataclass
class SizingConfig:
    probe_notional_usd: float = 0.50
    max_trade_notional_usd: float = 2.00
    max_single_trade_notional_usd: float = 1.00
    buying_power_buffer: float = 0.85
    dynamic_enabled: bool = False
    dynamic_min_usd: float = 1.00
    dynamic_max_usd: float = 25.00
    dynamic_threshold_usd: float = 20.00
    dynamic_position_pct: float = 2.5
    maker_fee_pct: float = 0.60
    taker_fee_pct: float = 1.20
    config_path: Optional[Path] = None
    config_found: bool = False


@dataclass
class TradeCycle:
    symbol: str
    strategy: str
    entry_timestamp: str
    exit_timestamp: str
    configured_probe_notional: float
    exploration_hard_cap: float
    dynamic_calculated_notional: Optional[float]
    journal_proposed_notional: Optional[float]
    winning_cap: str
    final_applied_notional: Optional[float]
    filled_buy_notional: Optional[float]
    filled_sell_notional: Optional[float]
    qty: Optional[float]
    entry_price: Optional[float]
    exit_price: Optional[float]
    gross_pnl: Optional[float]
    total_fees: Optional[float]
    net_pnl: Optional[float]
    exit_reason: str
    hold_minutes: Optional[float]
    mfe_pct: Optional[float] = None
    beat_maker_be: Optional[bool] = None
    beat_taker_be: Optional[bool] = None
    price_path_samples: int = 0


def safe_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_iso_timestamp(ts_str: str) -> Optional[datetime]:
    if not ts_str or not str(ts_str).strip():
        return None
    try:
        normalized = str(ts_str).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def yaml_scalar(text: str, key: str) -> Optional[str]:
    pattern = rf"^\s*{re.escape(key)}:\s*(.+?)\s*$"
    match = re.search(pattern, text, re.MULTILINE)
    if not match:
        return None
    raw = match.group(1).strip()
    if "#" in raw:
        raw = raw.split("#", 1)[0].strip()
    if raw in ("true", "True"):
        return "true"
    if raw in ("false", "False"):
        return "false"
    return raw.strip('"').strip("'")


def load_sizing_config(path: Path = DEFAULT_CONFIG) -> SizingConfig:
    cfg = SizingConfig(config_path=path)
    if not path.exists():
        return cfg

    text = path.read_text(encoding="utf-8")
    cfg.config_found = True

    def f(key: str, default: float) -> float:
        val = yaml_scalar(text, key)
        return float(val) if val is not None else default

    cfg.probe_notional_usd = f("coinbase_probe_notional_usd", 0.50)
    cfg.max_trade_notional_usd = f("max_trade_notional_usd", 2.00)
    cfg.max_single_trade_notional_usd = f("max_single_trade_notional_usd", 1.00)
    cfg.buying_power_buffer = f("buying_power_safety_buffer", 0.85)
    cfg.dynamic_min_usd = f("min_notional_usd", 1.00)
    cfg.dynamic_max_usd = f("max_notional_usd", 25.00)
    cfg.dynamic_threshold_usd = f("scaling_threshold_usd", 20.00)
    cfg.dynamic_position_pct = f("position_size_pct", 2.5)
    cfg.maker_fee_pct = f("maker_fee_pct", 0.006)
    cfg.taker_fee_pct = f("taker_fee_pct", 0.012)
    ds_block = re.search(
        r"dynamic_sizing:\s*\n((?:[ \t]+[^\n]+\n)+)",
        text,
        re.IGNORECASE,
    )
    if ds_block:
        enabled_match = re.search(
            r"enabled:\s*(true|false)",
            ds_block.group(1),
            re.IGNORECASE,
        )
        if enabled_match:
            cfg.dynamic_enabled = enabled_match.group(1).lower() == "true"
    return cfg


def find_journal_path() -> Optional[Path]:
    for path in JOURNAL_CANDIDATES:
        if path.exists() and path.stat().st_size > 0:
            return path
    return None


def read_journal_rows(path: Path) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def compute_dynamic_notional(
    equity: Optional[float],
    buying_power: Optional[float],
    cfg: SizingConfig,
) -> Optional[float]:
    if not cfg.dynamic_enabled or equity is None or equity <= 0:
        return None
    if equity < cfg.dynamic_threshold_usd:
        raw = cfg.dynamic_min_usd
    else:
        scaled = equity * (cfg.dynamic_position_pct / 100.0)
        raw = max(cfg.dynamic_min_usd, min(scaled, cfg.dynamic_max_usd))
    caps = [raw, cfg.dynamic_max_usd, cfg.max_single_trade_notional_usd]
    if buying_power is not None and buying_power > 0:
        caps.append(buying_power * cfg.buying_power_buffer)
    return round(min(caps), 4)


def determine_winning_cap(
    journal_notional: Optional[float],
    dynamic_calc: Optional[float],
    cfg: SizingConfig,
    strategy: str,
) -> tuple[str, Optional[float]]:
    candidates: list[tuple[str, float]] = [
        ("legacy_probe_notional", cfg.probe_notional_usd),
        ("crypto.max_trade_notional_usd", cfg.max_trade_notional_usd),
        ("controlled_exploration.max_single_trade_notional_usd", cfg.max_single_trade_notional_usd),
    ]
    if dynamic_calc is not None:
        candidates.append(("dynamic_sizing (capped)", dynamic_calc))

    if journal_notional is not None:
        final = journal_notional
        tol = 0.02
        if strategy in EXPLORATION_STRATEGIES and abs(final - cfg.max_single_trade_notional_usd) <= tol:
            return "controlled_exploration.max_single_trade_notional_usd ($1.00 hard cap)", final
        if strategy in PROBE_STRATEGIES and abs(final - cfg.probe_notional_usd) <= tol:
            return "legacy_probe / coinbase_probe_notional_usd ($0.50 path)", final
        if abs(final - cfg.max_single_trade_notional_usd) <= tol:
            return "controlled_exploration.max_single_trade_notional_usd ($1.00 hard cap)", final
        if abs(final - cfg.probe_notional_usd) <= tol:
            return "legacy_probe / coinbase_probe_notional_usd ($0.50 path)", final
        if dynamic_calc is not None and abs(final - dynamic_calc) <= tol:
            return "dynamic_sizing (matched journal notional)", final
        return "journal_proposed_notional (see BUY row)", final

    if strategy in PROBE_STRATEGIES:
        return "legacy_probe / coinbase_probe_notional_usd ($0.50 path)", cfg.probe_notional_usd
    if dynamic_calc is not None and abs(dynamic_calc - cfg.max_single_trade_notional_usd) < 0.001:
        return "controlled_exploration.max_single_trade_notional_usd (dynamic clamped to hard cap)", dynamic_calc
    return "controlled_exploration.max_single_trade_notional_usd (default exploration cap)", cfg.max_single_trade_notional_usd


def is_entry_row(row: dict[str, str]) -> bool:
    action = (row.get("action") or "").upper()
    decision = (row.get("decision") or "").upper()
    if action != "BUY":
        return False
    if decision in {"SKIPPED", "PREVIEW", "REJECTED", "ERROR"}:
        return False
    return decision in {"PLACED", "FILLED", "PARTIAL_FILL"}


def is_exit_row(row: dict[str, str]) -> bool:
    action = (row.get("action") or "").upper()
    decision = (row.get("decision") or "").upper()
    return action == "EXIT" and decision in {"PLACED", "FILLED"}


def extract_cycles(rows: list[dict[str, str]], cfg: SizingConfig) -> list[TradeCycle]:
    filtered = [
        r
        for r in rows
        if (r.get("strategy") or "") in EXPLORATION_STRATEGIES
        or (r.get("strategy") or "") in PROBE_STRATEGIES
    ]
    filtered.sort(key=lambda r: (parse_iso_timestamp(r.get("timestamp", "")) or datetime.min.replace(tzinfo=timezone.utc)))

    open_entries: dict[tuple[str, str], list[dict[str, str]]] = {}
    cycles: list[TradeCycle] = []

    for row in filtered:
        symbol = (row.get("symbol") or "").strip()
        if not symbol:
            continue
        strategy = (row.get("strategy") or "coinbase_exploration").strip()
        stack_key = (symbol, strategy)

        if is_entry_row(row):
            open_entries.setdefault(stack_key, []).append(row)
            continue

        if not is_exit_row(row):
            continue

        queue = open_entries.get(stack_key) or []
        if not queue:
            continue
        entry = queue.pop(0)
        if not queue:
            open_entries.pop(stack_key, None)

        entry_ts = (entry.get("timestamp") or "").strip()
        exit_ts = (row.get("timestamp") or "").strip()
        entry_dt = parse_iso_timestamp(entry_ts)
        exit_dt = parse_iso_timestamp(exit_ts)
        hold_minutes: Optional[float] = None
        if entry_dt and exit_dt:
            hold_minutes = round((exit_dt - entry_dt).total_seconds() / 60.0, 2)

        equity = safe_float(entry.get("equity")) or safe_float(row.get("equity"))
        buying_power = safe_float(entry.get("buying_power")) or safe_float(row.get("buying_power"))
        dynamic_calc = compute_dynamic_notional(equity, buying_power, cfg)
        journal_notional = safe_float(entry.get("notional"))
        winning_cap, final_notional = determine_winning_cap(journal_notional, dynamic_calc, cfg, strategy)

        qty = safe_float(row.get("qty")) or safe_float(entry.get("qty"))
        entry_price = safe_float(row.get("fill_price")) or safe_float(entry.get("fill_price"))
        exit_price = safe_float(row.get("exit_price"))
        filled_buy = (entry_price * qty) if entry_price and qty else journal_notional
        filled_sell = (exit_price * qty) if exit_price and qty else None

        cycles.append(
            TradeCycle(
                symbol=symbol,
                strategy=strategy,
                entry_timestamp=entry_ts,
                exit_timestamp=exit_ts,
                configured_probe_notional=cfg.probe_notional_usd,
                exploration_hard_cap=cfg.max_single_trade_notional_usd,
                dynamic_calculated_notional=dynamic_calc,
                journal_proposed_notional=journal_notional,
                winning_cap=winning_cap,
                final_applied_notional=final_notional,
                filled_buy_notional=round(filled_buy, 6) if filled_buy is not None else None,
                filled_sell_notional=round(filled_sell, 6) if filled_sell is not None else None,
                qty=qty,
                entry_price=entry_price,
                exit_price=exit_price,
                gross_pnl=safe_float(row.get("gross_pnl")),
                total_fees=safe_float(row.get("fees_paid")),
                net_pnl=safe_float(row.get("pnl_usd")),
                exit_reason=(row.get("reason") or "").strip(),
                hold_minutes=hold_minutes,
                mfe_pct=None,
                beat_maker_be=None,
                beat_taker_be=None,
            )
        )

    return cycles


def load_price_path_mfe() -> dict[tuple[str, str], tuple[float, int]]:
    """Map (symbol, entry_timestamp) -> (max unrealized_pct, sample count)."""
    result: dict[tuple[str, str], tuple[float, int]] = {}
    if not PRICE_PATH_CSV.exists():
        return result
    with open(PRICE_PATH_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            symbol = (row.get("symbol") or "").strip()
            entry_ts = (row.get("entry_timestamp") or "").strip()
            unrealized = safe_float(row.get("unrealized_pct"))
            if not symbol or not entry_ts or unrealized is None:
                continue
            key = (symbol, entry_ts)
            prev_mfe, count = result.get(key, (unrealized, 0))
            result[key] = (max(prev_mfe, unrealized), count + 1)
    return result


def attach_mfe(cycles: list[TradeCycle], mfe_index: dict[tuple[str, str], tuple[float, int]]) -> None:
    for cycle in cycles:
        # Try exact entry_timestamp match; fallback to symbol-only latest if single path
        key = (cycle.symbol, cycle.entry_timestamp)
        mfe_data = mfe_index.get(key)
        if mfe_data is None:
            symbol_keys = [k for k in mfe_index if k[0] == cycle.symbol]
            if len(symbol_keys) == 1:
                mfe_data = mfe_index[symbol_keys[0]]
        if mfe_data is None:
            continue
        mfe, samples = mfe_data
        cycle.mfe_pct = round(mfe, 4)
        cycle.price_path_samples = samples
        cycle.beat_maker_be = mfe >= MAKER_BE_PCT
        cycle.beat_taker_be = mfe >= TAKER_ROUND_TRIP_BE_PCT


def format_money(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    return f"${value:.4f}"


def format_report(
    cfg: SizingConfig,
    journal_path: Optional[Path],
    cycles: list[TradeCycle],
    journal_row_count: int,
) -> str:
    lines: list[str] = []
    lines.append("=" * 76)
    lines.append("COINBASE SIZING / EXECUTION RECONCILIATION (P2-006 — ADVISORY ONLY)")
    lines.append("=" * 76)
    lines.append("")
    lines.append("SUMMARY (read this first)")
    lines.append("-" * 76)
    lines.append(
        "Current behavior is fixed-cap controlled exploration, not uncapped adaptive sizing."
    )
    lines.append(
        "Sells close the same position quantity that was bought; sell notional tracks exit price × qty,"
    )
    lines.append(
        "so buy and sell USD amounts look similar and net to small gross moves — fees dominate at $1 size."
    )
    lines.append(
        f"P2-004 dynamic sizing is {'ENABLED' if cfg.dynamic_enabled else 'DISABLED'} in config, but the"
    )
    lines.append(
        f"hard exploration cap (${cfg.max_single_trade_notional_usd:.2f}) still wins at ~${cfg.dynamic_threshold_usd:.0f} equity."
    )
    lines.append(
        f"Legacy probe path used ${cfg.probe_notional_usd:.2f} notional when coinbase_probe fired (before/alongside exploration)."
    )
    lines.append(
        "Class 2 SL/TP/hold-time and hard-cap tuning remain BLOCKED until P2-005 shows ≥20 paths and ~2+ weeks of data."
    )
    lines.append("")

    lines.append("CONFIGURED SIZING (from config_coinbase_crypto.yaml snapshot)")
    lines.append("-" * 76)
    if cfg.config_found:
        lines.append(f"Config: {cfg.config_path}")
    else:
        lines.append(f"Config: not found at {cfg.config_path} — using defaults")
    lines.append(f"  coinbase_probe_notional_usd:              ${cfg.probe_notional_usd:.2f}")
    lines.append(f"  crypto.max_trade_notional_usd:            ${cfg.max_trade_notional_usd:.2f}")
    lines.append(
        f"  controlled_exploration.max_single_trade:  ${cfg.max_single_trade_notional_usd:.2f}  ← live cap"
    )
    lines.append(f"  dynamic_sizing.enabled:                   {cfg.dynamic_enabled}")
    if cfg.dynamic_enabled:
        lines.append(
            f"  dynamic_sizing (equity-scaled, pre-cap):    {cfg.dynamic_position_pct}% of equity, "
            f"min ${cfg.dynamic_min_usd:.2f}, max ${cfg.dynamic_max_usd:.2f}, threshold ${cfg.dynamic_threshold_usd:.2f}"
        )
    maker_display = cfg.maker_fee_pct * 100 if cfg.maker_fee_pct < 0.5 else cfg.maker_fee_pct
    taker_display = cfg.taker_fee_pct * 100 if cfg.taker_fee_pct < 0.5 else cfg.taker_fee_pct
    lines.append(f"  fee model (maker / taker %):                {maker_display:.2f}% / {taker_display:.2f}%")
    lines.append(f"  intra-hold maker break-even (approx):       +{MAKER_BE_PCT:.2f}% MFE")
    lines.append(f"  round-trip taker break-even (approx):       +{TAKER_ROUND_TRIP_BE_PCT:.2f}% MFE")
    lines.append("")

    lines.append("DATA SOURCES")
    lines.append("-" * 76)
    if journal_path:
        lines.append(f"Journal: {journal_path} ({journal_row_count} rows)")
    else:
        lines.append("Journal: not found — no trade cycles reconstructed")
    if PRICE_PATH_CSV.exists():
        lines.append(f"Price path (optional MFE): {PRICE_PATH_CSV}")
    else:
        lines.append("Price path (optional MFE): not present")
    lines.append("")

    if not cycles:
        lines.append("No completed exploration round trips found in journal.")
        lines.append("=" * 76)
        return "\n".join(lines) + "\n"

    lines.append(f"COMPLETED ROUND TRIPS: {len(cycles)}")
    lines.append("-" * 76)

    for idx, cycle in enumerate(cycles, 1):
        lines.append("")
        lines.append(f"--- Cycle {idx}: {cycle.symbol} | {cycle.strategy} ---")
        lines.append(f"  entry:  {cycle.entry_timestamp}")
        lines.append(f"  exit:   {cycle.exit_timestamp}")
        lines.append(f"  configured_probe_notional:        ${cycle.configured_probe_notional:.2f}")
        lines.append(f"  exploration_max_single_trade_cap: ${cycle.exploration_hard_cap:.2f}")
        lines.append(
            f"  dynamic_sizing_calculated_notional: "
            f"{format_money(cycle.dynamic_calculated_notional)}"
        )
        lines.append(f"  journal_proposed_notional (BUY):  {format_money(cycle.journal_proposed_notional)}")
        lines.append(f"  final_applied_notional:           {format_money(cycle.final_applied_notional)}")
        lines.append(f"  which_cap_won:                    {cycle.winning_cap}")
        lines.append(f"  filled_buy_notional (≈ entry×qty):  {format_money(cycle.filled_buy_notional)}")
        lines.append(f"  filled_sell_notional (≈ exit×qty):  {format_money(cycle.filled_sell_notional)}")
        lines.append(f"  qty:                              {cycle.qty}")
        lines.append(f"  entry_price / exit_price:         {cycle.entry_price} / {cycle.exit_price}")
        lines.append(f"  gross_pnl:                        {format_money(cycle.gross_pnl)}")
        lines.append(f"  total_fees:                       {format_money(cycle.total_fees)}")
        lines.append(f"  net_pnl:                          {format_money(cycle.net_pnl)}")
        lines.append(f"  exit_reason:                      {cycle.exit_reason or 'n/a'}")
        lines.append(f"  hold_minutes:                     {cycle.hold_minutes}")
        if cycle.mfe_pct is not None:
            lines.append(
                f"  price_path_MFE:                   {cycle.mfe_pct:.4f}% "
                f"({cycle.price_path_samples} samples) | beat_maker_BE={cycle.beat_maker_be} | "
                f"beat_taker_BE={cycle.beat_taker_be}"
            )
        else:
            lines.append("  price_path_MFE:                   n/a (no matching P2-003 path data)")

    # Aggregates
    nets = [c.net_pnl for c in cycles if c.net_pnl is not None]
    fees = [c.total_fees for c in cycles if c.total_fees is not None]
    notionals = [c.final_applied_notional for c in cycles if c.final_applied_notional is not None]
    lines.append("")
    lines.append("AGGREGATE")
    lines.append("-" * 76)
    if notionals:
        lines.append(
            f"  final_applied_notional: min=${min(notionals):.2f} max=${max(notionals):.2f} "
            f"avg=${sum(notionals)/len(notionals):.2f}"
        )
    if fees:
        lines.append(f"  total_fees_sum: ${sum(fees):.4f}  avg_fees_per_cycle: ${sum(fees)/len(fees):.4f}")
    if nets:
        lines.append(f"  net_pnl_sum: ${sum(nets):.4f}  winning_cycles: {sum(1 for n in nets if n > 0)}/{len(nets)}")
    cap_wins = {}
    for c in cycles:
        cap_wins[c.winning_cap] = cap_wins.get(c.winning_cap, 0) + 1
    lines.append("  which_cap_won counts:")
    for cap, count in sorted(cap_wins.items(), key=lambda x: -x[1]):
        lines.append(f"    {count}x {cap}")

    lines.append("")
    lines.append("=" * 76)
    return "\n".join(lines) + "\n"


def run_analysis(
    config_path: Path = DEFAULT_CONFIG,
    journal_path: Optional[Path] = None,
) -> str:
    cfg = load_sizing_config(config_path)
    jpath = journal_path or find_journal_path()
    rows: list[dict[str, str]] = []
    journal_readable: Optional[Path] = None
    if jpath and jpath.exists():
        journal_readable = jpath
        try:
            rows = read_journal_rows(jpath)
        except OSError:
            rows = []
    cycles = extract_cycles(rows, cfg)
    attach_mfe(cycles, load_price_path_mfe())
    return format_report(cfg, journal_readable, cycles, len(rows))


def main() -> None:
    config_path = DEFAULT_CONFIG
    journal_path: Optional[Path] = None
    args = sys.argv[1:]
    if args:
        journal_path = Path(args[0]).expanduser().resolve()
    print(run_analysis(config_path, journal_path), end="")


if __name__ == "__main__":
    main()
