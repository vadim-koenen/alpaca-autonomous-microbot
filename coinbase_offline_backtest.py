"""
coinbase_offline_backtest.py — Offline deterministic replay/backtest harness for Coinbase crypto.

Pure offline: loads fixture OHLCV (JSON/CSV), replays, applies fees, TP/SL/hold exits.
No broker, no network, no orders, no state mutation, no .env.

Supports:
- fixture driven entries (via "signal" column or entry bars)
- simple_mean_reversion rule for baseline
- configurable TP, SL, max_hold, fees, slippage buffer
- output closed trades with gross/net P/L, exit_reason
- report style with trade_permission=none, risk_increase=not_approved, scaling_allowed=false

This is a scaffold for P2-025E exit logic experiments. It does not perfectly replicate live strategy_crypto.py logic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

MONEY_QUANT = Decimal("0.00000001")
RATE_QUANT = Decimal("0.000001")

DEFAULT_ENTRY_FEE_RATE = Decimal("0.0060")  # 0.60%
DEFAULT_EXIT_FEE_RATE = Decimal("0.0120")   # 1.20% taker roundtrip example
DEFAULT_SPREAD_SLIPPAGE_BUFFER_RATE = Decimal("0.0010")
DEFAULT_TAKE_PROFIT_PCT = Decimal("3.00")
DEFAULT_STOP_LOSS_PCT = Decimal("1.50")
DEFAULT_MAX_HOLD_MINUTES = 90
DEFAULT_MAX_HOLD_BARS = 18  # 5min bars

SCHEMA_VERSION = "p2-025d.coinbase_offline_backtest.v1"


def _to_decimal(v: Any, default: Decimal = Decimal("0")) -> Decimal:
    if v is None:
        return default
    try:
        d = Decimal(str(v))
        if d.is_nan():
            return default
        return d
    except Exception:
        return default


def _fmt_money(d: Decimal) -> str:
    return str(d.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP))


def _fmt_rate(d: Decimal) -> str:
    return str(d.quantize(RATE_QUANT, rounding=ROUND_HALF_UP))


@dataclass
class Bar:
    t: datetime
    o: Decimal
    h: Decimal
    l: Decimal
    c: Decimal
    v: Decimal = field(default=Decimal("0"))


@dataclass
class ClosedTrade:
    symbol: str
    strategy_name: str
    entry_time: str
    exit_time: str
    entry_price: str
    exit_price: str
    exit_reason: str
    gross_pnl: str
    fees: str
    net_pnl: str
    hold_minutes: float
    notional: str


@dataclass
class BacktestResult:
    schema_version: str = SCHEMA_VERSION
    symbol: str = ""
    strategy_name: str = ""
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    breakeven: int = 0
    win_rate: float = 0.0
    gross_pnl_sum: str = "0"
    fees_sum: str = "0"
    net_pnl_sum: str = "0"
    exit_reason_breakdown: Dict[str, int] = field(default_factory=dict)
    closed_trades: List[Dict[str, Any]] = field(default_factory=list)
    trade_permission: str = "none"
    risk_increase: str = "not_approved"
    scaling_allowed: bool = False
    notes: List[str] = field(default_factory=list)


def load_bars_from_fixture(path) -> List[Bar]:
    """Load bars from JSON (list of dicts with o,h,l,c, timestamp_utc or t) or JSONL."""
    p = Path(path) if not isinstance(path, Path) else path
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8").strip()
    if not text:
        return []
    bars: List[Bar] = []
    try:
        if path.suffix.lower() == ".jsonl" or "\n" in text and text.startswith("{"):
            for line in text.splitlines():
                if not line.strip():
                    continue
                obj = json.loads(line)
                bars.append(_obj_to_bar(obj))
        else:
            data = json.loads(text)
            if isinstance(data, list):
                for obj in data:
                    bars.append(_obj_to_bar(obj))
            elif isinstance(data, dict) and "bars" in data:
                for obj in data["bars"]:
                    bars.append(_obj_to_bar(obj))
    except Exception:
        return []
    safe = []
    for b in bars:
        if not b:
            continue
        try:
            if b.c > 0:
                safe.append(b)
        except Exception:
            continue
    return safe


def _obj_to_bar(obj: Dict[str, Any]) -> Bar:
    ts = obj.get("timestamp_utc") or obj.get("t") or obj.get("timestamp")
    if isinstance(ts, str):
        try:
            t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            t = datetime.now(timezone.utc)
    else:
        t = datetime.now(timezone.utc)
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    def _safe_d(x):
        try:
            d = _to_decimal(x)
            if d is None:
                return Decimal("0")
            return d
        except Exception:
            return Decimal("0")
    return Bar(
        t=t,
        o=_safe_d(obj.get("o") or obj.get("open")),
        h=_safe_d(obj.get("h") or obj.get("high")),
        l=_safe_d(obj.get("l") or obj.get("low")),
        c=_safe_d(obj.get("c") or obj.get("close")),
        v=_safe_d(obj.get("v") or obj.get("volume")),
    )


def _apply_slippage(price: Decimal, buffer_rate: Decimal, is_buy: bool) -> Decimal:
    """Simple adverse slippage model."""
    if is_buy:
        return price * (1 + buffer_rate)
    else:
        return price * (1 - buffer_rate)


def run_backtest(
    bars: Sequence[Bar],
    *,
    symbol: str = "BTC/USD",
    strategy_name: str = "baseline_replay",
    entry_fee_rate: Any = DEFAULT_ENTRY_FEE_RATE,
    exit_fee_rate: Any = DEFAULT_EXIT_FEE_RATE,
    slippage_buffer_rate: Any = DEFAULT_SPREAD_SLIPPAGE_BUFFER_RATE,
    take_profit_pct: Any = DEFAULT_TAKE_PROFIT_PCT,
    stop_loss_pct: Any = DEFAULT_STOP_LOSS_PCT,
    max_hold_minutes: int = DEFAULT_MAX_HOLD_MINUTES,
    entry_rule: str = "fixture_signal",  # or "simple_mean_reversion"
    signals: Optional[Dict[datetime, bool]] = None,  # for fixture_signal: bar.t -> enter?
) -> BacktestResult:
    """
    Deterministic replay over bars.
    - Entry at close of signal bar (or first bar if no signals).
    - Exit at next bar close that hits TP/SL or max hold.
    - Fees on notional at entry/exit.
    - Slippage on fill prices.
    Documented assumption: entry/exit prices use bar close with adverse slippage; no intra-bar simulation.
    """
    # Accept float/int/Decimal for convenience from CLI/report
    entry_fee_rate = _to_decimal(entry_fee_rate, default=DEFAULT_ENTRY_FEE_RATE)
    exit_fee_rate = _to_decimal(exit_fee_rate, default=DEFAULT_EXIT_FEE_RATE)
    slippage_buffer_rate = _to_decimal(slippage_buffer_rate, default=DEFAULT_SPREAD_SLIPPAGE_BUFFER_RATE)
    take_profit_pct = _to_decimal(take_profit_pct, default=DEFAULT_TAKE_PROFIT_PCT)
    stop_loss_pct = _to_decimal(stop_loss_pct, default=DEFAULT_STOP_LOSS_PCT)

    res = BacktestResult(
        symbol=symbol,
        strategy_name=strategy_name,
        notes=[
            "Offline deterministic replay. Entry/exit at bar close + adverse slippage buffer.",
            "Fees modeled on notional. Max hold uses wall time from entry.",
            "trade_permission=none; risk_increase=not_approved; scaling_allowed=false",
        ],
    )
    if not bars or len(bars) < 2:
        res.notes.append("Insufficient bars for replay")
        return res

    tp_rate = take_profit_pct / Decimal("100")
    sl_rate = stop_loss_pct / Decimal("100")
    max_hold = timedelta(minutes=max_hold_minutes)

    # Prepare signals
    enter_at: set[datetime] = set()
    if signals:
        for ts, do_enter in signals.items():
            if do_enter:
                enter_at.add(ts)
    elif entry_rule == "simple_mean_reversion":
        # Very naive: enter on every 5th bar if price below recent low (toy)
        closes = [b.c for b in bars]
        for i in range(5, len(bars)):
            if closes[i] < min(closes[i-4:i]):
                enter_at.add(bars[i].t)
    else:
        # fixture_signal: if no signals provided, enter on first bar for demo
        enter_at.add(bars[0].t)

    closed: List[ClosedTrade] = []
    i = 0
    while i < len(bars) - 1:
        bar = bars[i]
        if bar.t not in enter_at:
            i += 1
            continue

        # Enter at close + slippage (buy)
        entry_price = _apply_slippage(bar.c, slippage_buffer_rate, is_buy=True)
        entry_time = bar.t
        entry_notional = Decimal("5.0")
        entry_fee = entry_notional * entry_fee_rate
        position_qty = entry_notional / entry_price  # approx

        # Look for exit
        exit_price = entry_price
        exit_time = entry_time
        exit_reason = "max_hold_time_exceeded"
        j = i + 1
        while j < len(bars):
            b = bars[j]
            # simulate at close
            cur_price = _apply_slippage(b.c, slippage_buffer_rate, is_buy=False)  # sell
            hold = b.t - entry_time
            tp_hit = cur_price >= entry_price * (1 + tp_rate)
            sl_hit = cur_price <= entry_price * (1 - sl_rate)
            if tp_hit:
                exit_price = cur_price
                exit_time = b.t
                exit_reason = "take_profit"
                break
            if sl_hit:
                exit_price = cur_price
                exit_time = b.t
                exit_reason = "stop_loss"
                break
            if hold >= max_hold:
                exit_price = cur_price
                exit_time = b.t
                exit_reason = "max_hold_time_exceeded"
                break
            j += 1
        else:
            # end of data, force exit
            exit_price = _apply_slippage(bars[-1].c, slippage_buffer_rate, is_buy=False)
            exit_time = bars[-1].t
            exit_reason = "end_of_data"

        # P/L
        exit_notional = position_qty * exit_price
        gross = exit_notional - entry_notional
        exit_fee = exit_notional * exit_fee_rate
        total_fees = entry_fee + exit_fee
        net = gross - total_fees
        hold_min = (exit_time - entry_time).total_seconds() / 60.0

        trade = ClosedTrade(
            symbol=symbol,
            strategy_name=strategy_name,
            entry_time=entry_time.isoformat(),
            exit_time=exit_time.isoformat(),
            entry_price=_fmt_money(entry_price),
            exit_price=_fmt_money(exit_price),
            exit_reason=exit_reason,
            gross_pnl=_fmt_money(gross),
            fees=_fmt_money(total_fees),
            net_pnl=_fmt_money(net),
            hold_minutes=round(hold_min, 2),
            notional=_fmt_money(entry_notional),
        )
        closed.append(trade)

        # advance past this trade
        i = j + 1 if j > i else i + 1

    # aggregate
    res.total_trades = len(closed)
    res.closed_trades = [trade.__dict__ for trade in closed]
    gross_sum = Decimal("0")
    fees_sum = Decimal("0")
    net_sum = Decimal("0")
    wins = losses = breakeven = 0
    reasons: Dict[str, int] = {}
    for t in closed:
        g = _to_decimal(t.gross_pnl)
        f = _to_decimal(t.fees)
        n = _to_decimal(t.net_pnl)
        gross_sum += g
        fees_sum += f
        net_sum += n
        if n > 0:
            wins += 1
        elif n < 0:
            losses += 1
        else:
            breakeven += 1
        reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1

    res.wins = wins
    res.losses = losses
    res.breakeven = breakeven
    res.win_rate = round(wins / res.total_trades, 6) if res.total_trades > 0 else 0.0
    res.gross_pnl_sum = _fmt_money(gross_sum)
    res.fees_sum = _fmt_money(fees_sum)
    res.net_pnl_sum = _fmt_money(net_sum)
    res.exit_reason_breakdown = reasons
    res.trade_permission = "none"
    res.risk_increase = "not_approved"
    res.scaling_allowed = False
    if res.total_trades == 0:
        res.notes.append("No trades generated in replay")
    return res


def run_backtest_from_fixture(
    fixture_path: Path,
    **kwargs: Any,
) -> BacktestResult:
    bars = load_bars_from_fixture(fixture_path)
    return run_backtest(bars, **kwargs)
