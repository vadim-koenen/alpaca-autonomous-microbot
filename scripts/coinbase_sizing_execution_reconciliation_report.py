# ADVISORY ONLY — read-only analysis, no live trading calls. Class 1 diagnostic report.
"""
Coinbase Sizing / Execution / Profitability Reconciliation Report — P2-006.

Reads local CSV/config files and prints an advisory stdout report explaining
controlled-exploration sizing, fee drag, buy/sell cycle outcomes, and whether
there is enough evidence to justify future Class 2 tuning.
"""
from __future__ import annotations
import argparse
import csv
import re
import sys
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Optional
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / 'config_coinbase_crypto.yaml'
DEFAULT_JOURNAL_PATH = REPO_ROOT / 'journal_coinbase_crypto.csv'
DEFAULT_PRICE_PATH = REPO_ROOT / 'logs' / 'coinbase_price_path.csv'
THRESHOLDS_PCT = (0.6, 1.2, 1.5, 2.0, 2.4)
MIN_COMPLETED_PATHS = 20
MIN_DATA_SPAN_DAYS = 14.0

@dataclass(frozen=True)
class ConfigSnapshot:
    legacy_probe_notional_usd: Optional[float] = None
    controlled_max_single_trade_usd: Optional[float] = None
    max_total_exploration_exposure_usd: Optional[float] = None
    max_open_positions: Optional[int] = None
    maker_fee_pct: Optional[float] = None
    taker_fee_pct: Optional[float] = None
    dynamic_position_size_pct: Optional[float] = None
    dynamic_min_notional_usd: Optional[float] = None
    dynamic_max_notional_usd: Optional[float] = None
    dynamic_scaling_threshold_usd: Optional[float] = None
    expected_starting_equity: Optional[float] = None

    @property
    def maker_round_trip_break_even_pct(self) -> Optional[float]:
        if self.maker_fee_pct is None:
            return None
        return self.maker_fee_pct * 200.0

    @property
    def taker_round_trip_break_even_pct(self) -> Optional[float]:
        if self.taker_fee_pct is None:
            return None
        return self.taker_fee_pct * 200.0

@dataclass(frozen=True)
class TradeRow:
    raw: dict[str, str]
    timestamp: Optional[datetime]
    symbol: str
    side: str
    quantity: Optional[float]
    price: Optional[float]
    notional: Optional[float]
    fee: float
    reason: str
    status: str

@dataclass
class PathStats:
    symbol: str
    entry_timestamp: str
    sample_count: int = 0
    first_timestamp: Optional[datetime] = None
    last_timestamp: Optional[datetime] = None
    mfe_pct: Optional[float] = None
    mae_pct: Optional[float] = None
    latest_unrealized_pct: Optional[float] = None
    max_hold_minutes: Optional[float] = None
    crossings: dict[float, Optional[float]] = field(default_factory=dict)

@dataclass
class TradeCycle:
    symbol: str
    entry_timestamp: Optional[datetime]
    exit_timestamp: Optional[datetime]
    entry_notional: Optional[float]
    exit_notional: Optional[float]
    entry_fee: float
    exit_fee: float
    quantity: Optional[float]
    entry_price: Optional[float]
    exit_price: Optional[float]
    exit_reason: str
    entry_raw: dict[str, str] = field(default_factory=dict)
    exit_raw: dict[str, str] = field(default_factory=dict)
    path_stats: Optional[PathStats] = None

    @property
    def total_fees(self) -> float:
        return self.entry_fee + self.exit_fee

    @property
    def gross_pnl(self) -> Optional[float]:
        if self.entry_notional is None or self.exit_notional is None:
            return None
        return self.exit_notional - self.entry_notional

    @property
    def net_pnl(self) -> Optional[float]:
        gross = self.gross_pnl
        if gross is None:
            return None
        return gross - self.total_fees

    @property
    def gross_return_pct(self) -> Optional[float]:
        if not self.entry_notional:
            return None
        gross = self.gross_pnl
        if gross is None:
            return None
        return gross / self.entry_notional * 100.0

    @property
    def net_return_pct(self) -> Optional[float]:
        if not self.entry_notional:
            return None
        net = self.net_pnl
        if net is None:
            return None
        return net / self.entry_notional * 100.0

    @property
    def hold_minutes(self) -> Optional[float]:
        if self.entry_timestamp is None or self.exit_timestamp is None:
            return None
        return (self.exit_timestamp - self.entry_timestamp).total_seconds() / 60.0

    @property
    def is_max_hold_exit(self) -> bool:
        text = self.exit_reason.lower().replace('_', ' ').replace('-', ' ')
        return 'max hold' in text or 'max position' in text or 'time exit' in text or ('timeout' in text)

    @property
    def exit_kind(self) -> str:
        text = self.exit_reason.lower().replace('_', ' ').replace('-', ' ')
        if self.is_max_hold_exit:
            return 'max_hold'
        if 'take profit' in text or 'takeprofit' in text or text.strip() == 'tp':
            return 'take_profit'
        if 'stop loss' in text or 'stoploss' in text or text.strip() == 'sl':
            return 'stop_loss'
        return 'unknown'

def parse_iso_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    candidates = [text]
    if text.endswith('Z'):
        candidates.append(text[:-1] + '+00:00')
    candidates.extend([text.replace(' ', 'T'), text.replace(' UTC', '+00:00')])
    for candidate in candidates:
        try:
            dt = datetime.fromisoformat(candidate)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            continue
    return None

def safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace('$', '').replace(',', '')
    if not text or text.lower() in {'none', 'nan', 'null'}:
        return None
    try:
        return float(text)
    except ValueError:
        return None

def safe_int(value: Any) -> Optional[int]:
    number = safe_float(value)
    if number is None:
        return None
    return int(number)

def first_value(row: dict[str, str], names: Iterable[str]) -> str:
    lowered = {k.lower().strip(): v for k, v in row.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return ''

def first_float(row: dict[str, str], names: Iterable[str]) -> Optional[float]:
    return safe_float(first_value(row, names))

def extract_scalar(text: str, key: str) -> Optional[float]:
    match = re.search(f'(?m)^\\s*{re.escape(key)}\\s*:\\s*([-+]?\\d+(?:\\.\\d+)?)\\b', text)
    if not match:
        return None
    return safe_float(match.group(1))

def extract_section_scalar(text: str, section: str, key: str) -> Optional[float]:
    lines = text.splitlines()
    in_section = False
    base_indent = None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        section_match = re.match('^(\\s*)([A-Za-z0-9_]+):\\s*$', line)
        if section_match:
            indent = len(section_match.group(1))
            name = section_match.group(2)
            if name == section:
                in_section = True
                base_indent = indent
                continue
            if in_section and base_indent is not None and (indent <= base_indent):
                in_section = False
        if in_section:
            match = re.match(f'^\\s*{re.escape(key)}\\s*:\\s*([-+]?\\d+(?:\\.\\d+)?)\\b', line)
            if match:
                return safe_float(match.group(1))
    return None

def load_config_snapshot(path: Path=DEFAULT_CONFIG_PATH) -> ConfigSnapshot:
    if not path.exists():
        return ConfigSnapshot()
    text = path.read_text(encoding='utf-8')
    return ConfigSnapshot(legacy_probe_notional_usd=extract_scalar(text, 'coinbase_probe_notional_usd'), controlled_max_single_trade_usd=extract_section_scalar(text, 'controlled_exploration', 'max_single_trade_notional_usd') or extract_scalar(text, 'max_single_trade_notional_usd'), max_total_exploration_exposure_usd=extract_section_scalar(text, 'controlled_exploration', 'max_total_exploration_exposure_usd') or extract_scalar(text, 'max_total_exploration_exposure_usd'), max_open_positions=safe_int(extract_section_scalar(text, 'controlled_exploration', 'max_open_positions') or extract_section_scalar(text, 'global_risk', 'max_open_positions')), maker_fee_pct=extract_section_scalar(text, 'fees', 'maker_fee_pct') or extract_scalar(text, 'maker_fee_pct'), taker_fee_pct=extract_section_scalar(text, 'fees', 'taker_fee_pct') or extract_scalar(text, 'taker_fee_pct'), dynamic_position_size_pct=extract_section_scalar(text, 'dynamic_sizing', 'position_size_pct'), dynamic_min_notional_usd=extract_section_scalar(text, 'dynamic_sizing', 'min_notional_usd'), dynamic_max_notional_usd=extract_section_scalar(text, 'dynamic_sizing', 'max_notional_usd'), dynamic_scaling_threshold_usd=extract_section_scalar(text, 'dynamic_sizing', 'scaling_threshold_usd'), expected_starting_equity=extract_section_scalar(text, 'account', 'expected_starting_equity'))

def read_csv_rows(path: Path) -> tuple[list[dict[str, str]], Optional[str]]:
    if not path.exists():
        return ([], f'missing: {path}')
    with path.open('r', encoding='utf-8', newline='') as fh:
        sample = fh.read(4096)
        fh.seek(0)
        if not sample.strip():
            return ([], None)
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            return ([], None)
        rows = [{str(k): '' if v is None else str(v) for k, v in row.items()} for row in reader]
    return (rows, None)

def normalize_side(row: dict[str, str]) -> str:
    text = ' '.join((first_value(row, names) for names in [('side',), ('action',), ('event',), ('type',), ('order_side',), ('decision',)])).lower()
    if 'buy' in text or 'entry' in text:
        return 'buy'
    if 'sell' in text or 'exit' in text or 'close' in text:
        return 'sell'
    return ''


def normalize_trade_row(row: dict[str, str]) -> Optional[TradeRow]:
    symbol = first_value(row, ('symbol', 'product_id', 'instrument', 'pair', 'asset'))
    if not symbol:
        return None

    side = normalize_side(row)
    if side not in {'buy', 'sell'}:
        return None

    timestamp = parse_iso_datetime(
        first_value(
            row,
            (
                'timestamp',
                'timestamp_utc',
                'time',
                'created_at',
                'submitted_at',
                'filled_at',
                'exit_timestamp',
                'entry_timestamp',
            ),
        )
    )

    quantity = first_float(row, ('quantity', 'qty', 'filled_qty', 'base_size', 'size', 'amount'))
    price = first_float(
        row,
        (
            'price',
            'filled_avg_price',
            'average_price',
            'avg_price',
            'entry_price',
            'exit_price',
            'fill_price',
        ),
    )

    notional_text = first_value(
        row,
        (
            'notional',
            'notional_usd',
            'usd_notional',
            'trade_notional_usd',
            'filled_notional',
            'value_usd',
            'cost',
            'proceeds',
        ),
    )
    notional = safe_float(notional_text)

    if notional is None and quantity is not None and price is not None:
        notional = abs(quantity * price)

    # Critical safety/accuracy rule:
    # Some Coinbase journal exit/status rows record a close event but do not include
    # actual sell fill proceeds. Those rows often appear as 0.00 notional. Treat
    # sell-side zero notional as unavailable unless quantity and price can
    # reconstruct a non-zero fill. Do not turn missing sell proceeds into -100% P/L.
    if side == 'sell' and notional is not None and abs(notional) < 1e-12:
        if quantity is not None and price is not None and abs(quantity) > 0 and abs(price) > 0:
            reconstructed = abs(quantity * price)
            notional = reconstructed if reconstructed > 0 else None
        else:
            notional = None

    fee = first_float(row, ('fee', 'fee_usd', 'fees', 'commission', 'commission_usd')) or 0.0
    reason = first_value(row, ('exit_reason', 'reason', 'close_reason', 'status_reason', 'note', 'notes')) or 'unknown'
    status = first_value(row, ('status', 'order_status', 'result'))

    return TradeRow(
        raw=row,
        timestamp=timestamp,
        symbol=symbol.strip().upper(),
        side=side,
        quantity=quantity,
        price=price,
        notional=notional,
        fee=abs(fee),
        reason=reason,
        status=status,
    )

def load_trade_rows(path: Path=DEFAULT_JOURNAL_PATH) -> tuple[list[TradeRow], Optional[str]]:
    rows, error = read_csv_rows(path)
    trade_rows = [row for row in (normalize_trade_row(raw) for raw in rows) if row is not None]
    trade_rows.sort(key=lambda r: r.timestamp or datetime.min.replace(tzinfo=timezone.utc))
    return (trade_rows, error)

def reconstruct_cycles(rows: list[TradeRow]) -> list[TradeCycle]:
    open_by_symbol: dict[str, deque[TradeRow]] = defaultdict(deque)
    cycles: list[TradeCycle] = []
    for row in rows:
        if row.side == 'buy':
            open_by_symbol[row.symbol].append(row)
            continue
        if row.side == 'sell' and open_by_symbol[row.symbol]:
            entry = open_by_symbol[row.symbol].popleft()
            cycles.append(TradeCycle(symbol=row.symbol, entry_timestamp=entry.timestamp, exit_timestamp=row.timestamp, entry_notional=entry.notional, exit_notional=row.notional, entry_fee=entry.fee, exit_fee=row.fee, quantity=entry.quantity, entry_price=entry.price, exit_price=row.price, exit_reason=row.reason, entry_raw=entry.raw, exit_raw=row.raw))
    return cycles

def load_price_path_stats(path: Path=DEFAULT_PRICE_PATH) -> tuple[dict[tuple[str, str], PathStats], Optional[str]]:
    rows, error = read_csv_rows(path)
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        symbol = first_value(row, ('symbol', 'product_id', 'pair')).strip().upper()
        entry_ts = first_value(row, ('entry_timestamp', 'entry_timestamp_utc', 'entry_time')).strip()
        if symbol and entry_ts:
            grouped[symbol, entry_ts].append(row)
    stats: dict[tuple[str, str], PathStats] = {}
    for (symbol, entry_ts), group in grouped.items():
        unrealized_values: list[float] = []
        hold_values: list[float] = []
        timestamps: list[datetime] = []
        sorted_group = sorted(group, key=lambda r: parse_iso_datetime(first_value(r, ('timestamp_utc', 'timestamp', 'time'))) or datetime.min.replace(tzinfo=timezone.utc))
        for row in sorted_group:
            unrl = first_float(row, ('unrealized_pct', 'unrealized_percent', 'return_pct'))
            hold = first_float(row, ('hold_minutes', 'minutes_held', 'age_minutes'))
            ts = parse_iso_datetime(first_value(row, ('timestamp_utc', 'timestamp', 'time')))
            if unrl is not None:
                unrealized_values.append(unrl)
            if hold is not None:
                hold_values.append(hold)
            if ts is not None:
                timestamps.append(ts)
        path = PathStats(symbol=symbol, entry_timestamp=entry_ts, sample_count=len(group), first_timestamp=min(timestamps) if timestamps else None, last_timestamp=max(timestamps) if timestamps else None, mfe_pct=max(unrealized_values) if unrealized_values else None, mae_pct=min(unrealized_values) if unrealized_values else None, latest_unrealized_pct=unrealized_values[-1] if unrealized_values else None, max_hold_minutes=max(hold_values) if hold_values else None, crossings={threshold: None for threshold in THRESHOLDS_PCT})
        for threshold in THRESHOLDS_PCT:
            for row in sorted_group:
                unrl = first_float(row, ('unrealized_pct', 'unrealized_percent', 'return_pct'))
                if unrl is not None and unrl >= threshold:
                    path.crossings[threshold] = first_float(row, ('hold_minutes', 'minutes_held', 'age_minutes'))
                    break
        stats[symbol, entry_ts] = path
    return (stats, error)

def attach_price_paths(cycles: list[TradeCycle], paths: dict[tuple[str, str], PathStats]) -> None:
    for cycle in cycles:
        if cycle.entry_timestamp is None:
            continue
        candidates = [cycle.entry_timestamp.isoformat(), cycle.entry_timestamp.replace(tzinfo=None).isoformat(), cycle.entry_timestamp.strftime('%Y-%m-%dT%H:%M:%S%z'), cycle.entry_timestamp.strftime('%Y-%m-%d %H:%M:%S%z')]
        for candidate in candidates:
            found = paths.get((cycle.symbol, candidate))
            if found is not None:
                cycle.path_stats = found
                break
        if cycle.path_stats is not None:
            continue
        best: tuple[float, Optional[PathStats]] = (999999.0, None)
        for (symbol, entry_text), path in paths.items():
            if symbol != cycle.symbol:
                continue
            parsed = parse_iso_datetime(entry_text)
            if parsed is None:
                continue
            diff = abs((parsed - cycle.entry_timestamp).total_seconds())
            if diff < best[0]:
                best = (diff, path)
        if best[1] is not None and best[0] <= 120:
            cycle.path_stats = best[1]

def fmt_money(value: Optional[float]) -> str:
    if value is None:
        return 'n/a'
    return f'${value:.4f}'

def fmt_pct(value: Optional[float]) -> str:
    if value is None:
        return 'n/a'
    return f'{value:+.3f}%'

def fmt_minutes(value: Optional[float]) -> str:
    if value is None:
        return 'n/a'
    return f'{value:.1f}'

def fmt_dt(value: Optional[datetime]) -> str:
    if value is None:
        return 'n/a'
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')

def theoretical_dynamic_notional(config: ConfigSnapshot, observed_notional: Optional[float]) -> Optional[float]:
    equity = config.expected_starting_equity
    pct = config.dynamic_position_size_pct
    if equity is None or pct is None:
        return None
    calc = equity * pct / 100.0
    if config.dynamic_min_notional_usd is not None:
        calc = max(calc, config.dynamic_min_notional_usd)
    if config.dynamic_max_notional_usd is not None:
        calc = min(calc, config.dynamic_max_notional_usd)
    return calc

def winning_cap(config: ConfigSnapshot, final_notional: Optional[float]) -> str:
    if final_notional is None:
        return 'unknown'
    controlled = config.controlled_max_single_trade_usd
    dynamic_max = config.dynamic_max_notional_usd
    legacy = config.legacy_probe_notional_usd
    close = lambda a, b: a is not None and abs(a - b) < 0.015
    if close(controlled, final_notional):
        return 'controlled_exploration.max_single_trade_notional_usd'
    if close(legacy, final_notional):
        return 'legacy coinbase_probe_notional_usd'
    if close(dynamic_max, final_notional):
        return 'dynamic_sizing.max_notional_usd'
    return 'observed fill / unknown cap'

def render_config_section(config: ConfigSnapshot) -> list[str]:
    return ['## A. Configuration snapshot', f'Legacy probe notional: {fmt_money(config.legacy_probe_notional_usd)}', f'Controlled exploration max single-trade cap: {fmt_money(config.controlled_max_single_trade_usd)}', f'Max total exploration exposure: {fmt_money(config.max_total_exploration_exposure_usd)}', f"Max open positions: {(config.max_open_positions if config.max_open_positions is not None else 'n/a')}", f'Maker fee: {fmt_pct(config.maker_fee_pct * 100.0 if config.maker_fee_pct is not None else None)}', f'Taker fee: {fmt_pct(config.taker_fee_pct * 100.0 if config.taker_fee_pct is not None else None)}', f'Estimated maker/maker round-trip break-even: {fmt_pct(config.maker_round_trip_break_even_pct)}', f'Estimated taker/taker round-trip break-even: {fmt_pct(config.taker_round_trip_break_even_pct)}', 'Current behavior is fixed-cap controlled exploration, not uncapped adaptive sizing.', 'Sell size closes the bought position quantity; it is not independently selecting a new variable sell value.', '']


def render_cycle_section(cycles: list[TradeCycle], config: ConfigSnapshot) -> list[str]:
    lines = ['## B/C. Trade-cycle reconstruction and sizing explanation']
    if not cycles:
        lines.extend(
            [
                'No completed buy/sell cycles reconstructed from the journal.',
                'This usually means the journal is missing, empty, or uses columns this advisory report does not recognize yet.',
                '',
            ]
        )
        return lines

    for idx, cycle in enumerate(cycles, 1):
        dyn = theoretical_dynamic_notional(config, cycle.entry_notional)
        cap = winning_cap(config, cycle.entry_notional)

        lines.extend(
            [
                f'Cycle {idx}: {cycle.symbol}',
                f'  Entry: {fmt_dt(cycle.entry_timestamp)} | Exit: {fmt_dt(cycle.exit_timestamp)} | Hold minutes: {fmt_minutes(cycle.hold_minutes)}',
                f'  Entry notional: {fmt_money(cycle.entry_notional)} | Exit notional: {fmt_money(cycle.exit_notional)}',
                f'  Gross P/L: {fmt_money(cycle.gross_pnl)} | Fees: {fmt_money(cycle.total_fees)} | Net P/L: {fmt_money(cycle.net_pnl)}',
                f'  Gross return: {fmt_pct(cycle.gross_return_pct)} | Net return: {fmt_pct(cycle.net_return_pct)}',
                f'  Exit reason: {cycle.exit_reason or "unknown"} | Exit kind: {cycle.exit_kind} | Max-hold exit: {"yes" if cycle.is_max_hold_exit else "no"}',
                f'  Legacy probe notional: {fmt_money(config.legacy_probe_notional_usd)} | Controlled cap: {fmt_money(config.controlled_max_single_trade_usd)} | Dynamic theoretical: {fmt_money(dyn)}',
                f'  Final applied notional: {fmt_money(cycle.entry_notional)} | Limiting factor: {cap}',
            ]
        )

        if cycle.exit_notional is None:
            lines.append(
                '  Exit fill warning: journal exit event present but sell fill value unavailable; P/L and returns are unavailable, not -100%.'
            )

        if cycle.path_stats is None:
            lines.append('  Price-path MFE/MAE: unavailable for this cycle')
        else:
            path = cycle.path_stats
            crossings = ', '.join(
                f'+{threshold:.2f}%={"yes at " + fmt_minutes(minutes) + "m" if minutes is not None else "no"}'
                for threshold, minutes in path.crossings.items()
            )
            lines.extend(
                [
                    f'  Price-path samples: {path.sample_count} | MFE: {fmt_pct(path.mfe_pct)} | MAE: {fmt_pct(path.mae_pct)} | Max hold sample: {fmt_minutes(path.max_hold_minutes)}m',
                    f'  Threshold crossings: {crossings}',
                ]
            )

        lines.append('')

    return lines


def render_profitability_summary(cycles: list[TradeCycle]) -> list[str]:
    lines = ['## D. Fee-adjusted profitability summary']
    if not cycles:
        lines.extend(['Completed cycles: 0', 'Cycles with usable P/L: 0', ''])
        return lines

    gross_values = [c.gross_pnl for c in cycles if c.gross_pnl is not None]
    net_values = [c.net_pnl for c in cycles if c.net_pnl is not None]
    gross_returns = [c.gross_return_pct for c in cycles if c.gross_return_pct is not None]
    net_returns = [c.net_return_pct for c in cycles if c.net_return_pct is not None]

    total_gross = sum(gross_values) if gross_values else None
    total_fees = sum(c.total_fees for c in cycles)
    total_net = sum(net_values) if net_values else None
    wins_before = sum(1 for value in gross_values if value > 0)
    wins_after = sum(1 for value in net_values if value > 0)

    kinds = defaultdict(int)
    for cycle in cycles:
        kinds[cycle.exit_kind] += 1

    fee_drag = None
    gross_opportunity = sum(abs(value) for value in gross_values)
    if gross_opportunity > 0:
        fee_drag = total_fees / gross_opportunity * 100.0

    lines.extend(
        [
            f'Completed cycles: {len(cycles)}',
            f'Cycles with usable P/L: {len(net_values)}',
            f'Wins before fees: {wins_before}/{len(gross_values)}',
            f'Wins after fees: {wins_after}/{len(net_values)}',
            f'Total gross P/L: {fmt_money(total_gross)}',
            f'Total fees: {fmt_money(total_fees)}',
            f'Total net P/L: {fmt_money(total_net)}',
            f'Average gross return: {fmt_pct(mean(gross_returns) if gross_returns else None)}',
            f'Average net return: {fmt_pct(mean(net_returns) if net_returns else None)}',
            f'Fee drag as % of gross opportunity: {fmt_pct(fee_drag)}',
            f'Max-hold exits: {kinds["max_hold"]}',
            f'TP exits: {kinds["take_profit"]}',
            f'SL exits: {kinds["stop_loss"]}',
            f'Unknown exits: {kinds["unknown"]}',
            '',
        ]
    )
    return lines


def render_symbol_summary(cycles: list[TradeCycle], config: ConfigSnapshot) -> list[str]:
    lines = ['## E. Symbol summary']
    if not cycles:
        lines.extend(['No symbol summary available.', ''])
        return lines

    by_symbol: dict[str, list[TradeCycle]] = defaultdict(list)
    for cycle in cycles:
        by_symbol[cycle.symbol].append(cycle)

    break_even = config.taker_round_trip_break_even_pct or 2.40

    for symbol in sorted(by_symbol):
        group = by_symbol[symbol]
        gross_values = [c.gross_pnl for c in group if c.gross_pnl is not None]
        net_values = [c.net_pnl for c in group if c.net_pnl is not None]
        gross = sum(gross_values) if gross_values else None
        net = sum(net_values) if net_values else None
        mfes = [c.path_stats.mfe_pct for c in group if c.path_stats and c.path_stats.mfe_pct is not None]
        maes = [c.path_stats.mae_pct for c in group if c.path_stats and c.path_stats.mae_pct is not None]
        break_even_crossings = sum(
            1
            for c in group
            if c.path_stats and c.path_stats.mfe_pct is not None and c.path_stats.mfe_pct >= break_even
        )

        if len(group) < 3 or not net_values:
            status = 'inconclusive'
        elif sum(net_values) > 0 and break_even_crossings > 0:
            status = 'promising'
        elif sum(net_values) < 0:
            status = 'avoid for now'
        else:
            status = 'inconclusive'

        lines.append(
            f'{symbol}: cycles={len(group)} gross={fmt_money(gross)} net={fmt_money(net)} '
            f'avg_MFE={fmt_pct(mean(mfes) if mfes else None)} '
            f'avg_MAE={fmt_pct(mean(maes) if maes else None)} '
            f'best_MFE={fmt_pct(max(mfes) if mfes else None)} '
            f'worst_MAE={fmt_pct(min(maes) if maes else None)} '
            f'break_even_crossings={break_even_crossings} status={status}'
        )

    lines.append('')
    return lines

def data_span_days(paths: dict[tuple[str, str], PathStats], cycles: list[TradeCycle]) -> float:
    timestamps: list[datetime] = []
    for cycle in cycles:
        if cycle.entry_timestamp:
            timestamps.append(cycle.entry_timestamp)
        if cycle.exit_timestamp:
            timestamps.append(cycle.exit_timestamp)
    for path in paths.values():
        if path.first_timestamp:
            timestamps.append(path.first_timestamp)
        if path.last_timestamp:
            timestamps.append(path.last_timestamp)
    if len(timestamps) < 2:
        return 0.0
    return (max(timestamps) - min(timestamps)).total_seconds() / 86400.0

def render_decision_gate(cycles: list[TradeCycle], paths: dict[tuple[str, str], PathStats]) -> list[str]:
    span = data_span_days(paths, cycles)
    observed_paths = max(len(paths), len(cycles))
    net_values = [c.net_pnl for c in cycles if c.net_pnl is not None]
    total_net = sum(net_values)
    lines = ['## F. Decision gate']
    lines.append(f'Completed/reconstructed cycles: {len(cycles)}')
    lines.append(f'Observed price paths: {len(paths)}')
    lines.append(f'Data span days: {span:.2f}')
    if observed_paths < MIN_COMPLETED_PATHS:
        lines.append(f'Class 2 tuning: BLOCKED — fewer than {MIN_COMPLETED_PATHS} completed paths.')
    if span < MIN_DATA_SPAN_DAYS:
        lines.append(f'Class 2 tuning: BLOCKED — fewer than {MIN_DATA_SPAN_DAYS:.0f} days of P2-003/P2-005 evidence.')
    if not net_values or total_net <= 0:
        lines.append('Notional increase: BLOCKED — fee-adjusted expectancy is not proven positive.')
    else:
        lines.append('Notional increase: STILL REQUIRES HUMAN APPROVAL — positive net history alone is not enough.')
    lines.append('Prediction/betting: SHADOW ONLY — do not connect P2-002 features to live trading decisions.')
    lines.append('Profit path: reconcile fees and exits first, then use paper-only what-if tests before any live Class 2 change.')
    lines.append('')
    return lines

def build_report(config_path: Path=DEFAULT_CONFIG_PATH, journal_path: Path=DEFAULT_JOURNAL_PATH, price_path: Path=DEFAULT_PRICE_PATH) -> str:
    config = load_config_snapshot(config_path)
    trade_rows, journal_error = load_trade_rows(journal_path)
    cycles = reconstruct_cycles(trade_rows)
    paths, path_error = load_price_path_stats(price_path)
    attach_price_paths(cycles, paths)
    lines: list[str] = ['Coinbase Sizing / Execution / Profitability Reconciliation Report — P2-006', 'ADVISORY ONLY — read-only report; no live trading calls; no config changes.', '']
    if journal_error:
        lines.append(f'Journal warning: {journal_error}')
    elif not trade_rows:
        lines.append(f'Journal warning: no recognized buy/sell rows in {journal_path}')
    if path_error:
        lines.append(f'Price-path warning: {path_error}')
    elif not paths:
        lines.append(f'Price-path warning: no price-path samples in {price_path}')
    if len(lines) > 3:
        lines.append('')
    lines.extend(render_config_section(config))
    lines.extend(render_cycle_section(cycles, config))
    lines.extend(render_profitability_summary(cycles))
    lines.extend(render_symbol_summary(cycles, config))
    lines.extend(render_decision_gate(cycles, paths))
    return '\n'.join(lines).rstrip() + '\n'

def main(argv: Optional[list[str]]=None) -> int:
    parser = argparse.ArgumentParser(description='Coinbase sizing/execution reconciliation report — advisory only.')
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument('--journal', type=Path, default=DEFAULT_JOURNAL_PATH)
    parser.add_argument('--price-path', type=Path, default=DEFAULT_PRICE_PATH)
    args = parser.parse_args(argv)
    sys.stdout.write(build_report(args.config, args.journal, args.price_path))
    return 0
if __name__ == '__main__':
    raise SystemExit(main())
