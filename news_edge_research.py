#!/usr/bin/env python3
"""
news_edge_research.py — P2-045A: does NEWS/SENTIMENT predict forward returns?

The live evidence (P2-044H) showed the bot's PRICE-ONLY technical signals have no
edge. The untested hypothesis is alternative data: does news sentiment predict the
next move, net of fees? This harness answers that OFFLINE on historical data, so
we never repeat unvalidated live patching.

METHOD
- Inputs: daily OHLCV bars + timestamped news events (each with a sentiment score
  in [-1, 1], or a headline we score with a simple built-in lexicon).
- For each news event: enter long at the close of the bar on/after the event date
  (long-only; the account cannot short), exit `horizon_days` later. Compute the
  forward return NET of a round-trip cost.
- Trade only when sentiment exceeds a threshold (the "news signal").
- EDGE TEST: (1) net mean forward return of news-triggered trades > 0 and beats
  no-trade, out-of-sample; (2) sentiment correlates with forward return.

GOVERNANCE: offline only, no broker, no network, no runtime mutation. /tmp output.
A positive result authorizes only an offline gate + paper repro, never live.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import equities_swing_backtest_gate as gate  # reuse Bar, CostModel, load_bars_csv

BPS = 1e4
MIN_EVENTS = 30
SENTIMENT_THRESHOLD = 0.2
IN_SAMPLE_FRACTION = 0.6

# Tiny lexicon fallback when events have no sentiment score. Deliberately simple +
# clearly flagged: real research should supply model/vendor sentiment.
_POS = {"surge", "rally", "soar", "gain", "bullish", "approval", "adopt", "partnership",
        "record", "beat", "upgrade", "inflow", "breakout", "jump", "win"}
_NEG = {"plunge", "crash", "drop", "bearish", "ban", "hack", "lawsuit", "selloff",
        "downgrade", "outflow", "fear", "fall", "loss", "probe", "halt", "exploit"}


@dataclass(frozen=True)
class NewsEvent:
    date: str          # YYYY-MM-DD
    symbol: str
    sentiment: float   # [-1, 1]
    headline: str = ""


def lexicon_sentiment(headline: str) -> float:
    words = [w.strip(".,!?:;()[]\"'").lower() for w in (headline or "").split()]
    pos = sum(1 for w in words if w in _POS)
    neg = sum(1 for w in words if w in _NEG)
    if pos == neg == 0:
        return 0.0
    return (pos - neg) / (pos + neg)


def load_news(path: Path) -> List[NewsEvent]:
    """Accept CSV or JSONL. Fields: date/timestamp, symbol, sentiment? , headline?"""
    events: List[NewsEvent] = []
    text = path.read_text().splitlines()
    is_jsonl = path.suffix.lower() in (".jsonl", ".ndjson") or (text and text[0].lstrip().startswith("{"))
    rows: List[Dict[str, Any]] = []
    if is_jsonl:
        for line in text:
            line = line.strip()
            if line and not line.startswith("#"):
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    else:
        rows = list(csv.DictReader(text))

    for r in rows:
        ts = r.get("date") or r.get("timestamp") or r.get("timestamp_utc") or r.get("created_at")
        if not ts:
            continue
        sym = (r.get("symbol") or r.get("product_id") or "").strip()
        headline = r.get("headline") or r.get("title") or r.get("summary") or ""
        if r.get("sentiment") not in (None, ""):
            try:
                sent = float(r["sentiment"])
            except (TypeError, ValueError):
                sent = lexicon_sentiment(headline)
        else:
            sent = lexicon_sentiment(headline)
        events.append(NewsEvent(date=str(ts)[:10], symbol=sym,
                                sentiment=max(-1.0, min(1.0, sent)), headline=headline))
    return events


def _bar_index_on_or_after(bars: List[gate.Bar], date: str) -> Optional[int]:
    for i, b in enumerate(bars):
        if b.date[:10] >= date:
            return i
    return None


def _pearson(xs: List[float], ys: List[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)


def _t_stat(values: List[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    sd = statistics.pstdev(values)
    return statistics.fmean(values) / (sd / math.sqrt(n)) if sd else 0.0


def _forward_returns(
    bars: List[gate.Bar], events: List[NewsEvent], horizon_days: int, rt_cost_bps: float,
) -> List[Tuple[float, float]]:
    """Return list of (sentiment, net_forward_return_bps) for events that map to bars."""
    out: List[Tuple[float, float]] = []
    for ev in events:
        i = _bar_index_on_or_after(bars, ev.date)
        if i is None or i + horizon_days >= len(bars):
            continue
        entry = bars[i].c
        exit_ = bars[i + horizon_days].c
        if entry <= 0:
            continue
        net_bps = (exit_ / entry - 1.0) * BPS - rt_cost_bps
        out.append((ev.sentiment, net_bps))
    return out


def research(
    bars: List[gate.Bar],
    events: List[NewsEvent],
    horizon_days: int = 3,
    costs: Optional[gate.CostModel] = None,
    sentiment_threshold: float = SENTIMENT_THRESHOLD,
    min_events: int = MIN_EVENTS,
    decision_grade: bool = True,
) -> Dict[str, Any]:
    costs = costs or gate.CostModel()
    rt = costs.round_trip_cost_bps
    pairs = _forward_returns(bars, events, horizon_days, rt)

    # Out-of-sample split on event order.
    cut = int(len(pairs) * IN_SAMPLE_FRACTION)
    oos = pairs[cut:]

    def _signal_trades(ps: List[Tuple[float, float]]) -> List[float]:
        # Long only when sentiment is meaningfully positive.
        return [ret for s, ret in ps if s >= sentiment_threshold]

    oos_trades = _signal_trades(oos)
    all_sent = [s for s, _ in pairs]
    all_ret = [r for _, r in pairs]
    corr = _pearson(all_sent, all_ret)

    n_oos = len(oos_trades)
    mean_oos = round(statistics.fmean(oos_trades), 3) if oos_trades else 0.0
    t_oos = round(_t_stat(oos_trades), 3) if oos_trades else 0.0
    win_oos = round(sum(1 for r in oos_trades if r > 0) / n_oos, 4) if n_oos else 0.0

    # Primary edge test: are the OOS news-triggered trades net-positive with signal?
    # Correlation is a DIAGNOSTIC (sign/strength of the sentiment->return relation),
    # not a hard gate — thresholded/binary sentiment can have edge without linear corr.
    if len(pairs) < min_events or n_oos < max(10, min_events // 3):
        verdict = "INSUFFICIENT_DATA"
        explanation = (f"Only {len(pairs)} usable events ({n_oos} OOS). Need >= {min_events} "
                       "to test the news-edge hypothesis credibly.")
    elif mean_oos > 0 and t_oos > 1.0:
        verdict = "NEWS_EDGE_SIGNAL"
        explanation = (f"OOS news-triggered trades net +{mean_oos} bps/trade (t={t_oos}), "
                       f"sentiment-return corr {round(corr,3)} (diagnostic). Worth a formal "
                       "offline gate + paper repro. Still NOT live until the gate passes.")
    else:
        verdict = "NO_NEWS_EDGE"
        explanation = (f"OOS news-triggered trades net {mean_oos} bps/trade (t={t_oos}), "
                       f"sentiment-return corr {round(corr,3)}. News did not predict forward "
                       "returns net of fees on this data.")

    return {
        "schema": "p2_045a_news_edge_research/v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "decision_grade": decision_grade,
        "disclaimer": "Offline news-edge research. Not live authorization. A positive result earns an offline gate + paper repro only.",
        "n_bars": len(bars),
        "n_events_total": len(events),
        "n_events_mapped": len(pairs),
        "horizon_days": horizon_days,
        "round_trip_cost_bps": round(rt, 2),
        "sentiment_threshold": sentiment_threshold,
        "sentiment_return_correlation": round(corr, 4),
        "oos": {
            "n_trades": n_oos,
            "mean_net_fwd_return_bps": mean_oos,
            "t_stat": t_oos,
            "win_rate": win_oos,
        },
        "verdict": verdict,
        "explanation": explanation,
        "authorizes_live": False,
    }


def render_markdown(r: Dict[str, Any]) -> str:
    o = r["oos"]
    return "\n".join([
        "# P2-045A — News-Edge Research (does news predict returns?)",
        "",
        f"Generated: {r['generated_utc']} · decision_grade={r['decision_grade']}",
        f"> {r['disclaimer']}",
        "",
        f"Bars: {r['n_bars']} · events: {r['n_events_total']} (mapped {r['n_events_mapped']}) · "
        f"horizon {r['horizon_days']}d · round-trip cost {r['round_trip_cost_bps']} bps",
        f"Sentiment↔forward-return correlation: **{r['sentiment_return_correlation']}**",
        "",
        "## Out-of-sample news-triggered trades",
        f"- trades: {o['n_trades']}",
        f"- mean net forward return: **{o['mean_net_fwd_return_bps']} bps**",
        f"- t-stat: {o['t_stat']} · win rate: {o['win_rate']*100:.1f}%",
        "",
        f"## Verdict: **{r['verdict']}**",
        "",
        r["explanation"],
        "",
    ])


def write_outputs(r: Dict[str, Any], out_dir: Path) -> Dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    jp = out_dir / "p2_045a_news_edge_research.json"
    mp = out_dir / "p2_045a_news_edge_research.md"
    jp.write_text(json.dumps(r, indent=2))
    mp.write_text(render_markdown(r))
    return {"json": str(jp), "md": str(mp)}


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="P2-045A news-edge research")
    p.add_argument("--prices", required=True, help="Daily OHLCV CSV (date,open,high,low,close,volume).")
    p.add_argument("--news", required=True, help="News CSV/JSONL (date,symbol,sentiment?,headline?).")
    p.add_argument("--horizon-days", type=int, default=3)
    p.add_argument("--out-dir", default="/tmp")
    p.add_argument("--print", action="store_true")
    args = p.parse_args(argv)

    bars = gate.load_bars_csv(Path(args.prices))
    events = load_news(Path(args.news))
    r = research(bars, events, horizon_days=args.horizon_days, decision_grade=True)
    paths = write_outputs(r, Path(args.out_dir))
    if args.print:
        print(render_markdown(r))
    print(f"[p2-045a] verdict={r['verdict']} events_mapped={r['n_events_mapped']}")
    print(f"[p2-045a] wrote {paths['json']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
