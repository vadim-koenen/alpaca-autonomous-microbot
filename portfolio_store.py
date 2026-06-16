#!/usr/bin/env python3
"""
portfolio_store.py — P2-046D: local portfolio state persistence.

Saves/loads the accumulator's Portfolio (holdings + cash) and an append-only history of
executed plans, as plain JSON on local disk. Inspectable, backup-friendly, no DB needed.

GOVERNANCE: local state only. No broker, no orders, no live authorization. The store
records what HAPPENED (after human-approved paper/live fills); it never places trades.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from allocator_engine import Portfolio

DEFAULT_PATH = Path("runtime/accumulator_state.json")


def load_portfolio(path: Path = DEFAULT_PATH) -> Portfolio:
    if not Path(path).exists():
        return Portfolio(holdings={}, cash=0.0)
    data = json.loads(Path(path).read_text())
    return Portfolio(holdings={k: float(v) for k, v in data.get("holdings", {}).items()},
                     cash=float(data.get("cash", 0.0)))


def save_portfolio(portfolio: Portfolio, path: Path = DEFAULT_PATH) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "holdings": {k: round(v, 10) for k, v in portfolio.holdings.items()},
        "cash": round(portfolio.cash, 10),
        "updated_utc": datetime.now(timezone.utc).isoformat(),
    }
    Path(path).write_text(json.dumps(payload, indent=2))


def append_history(record: Dict[str, Any], path: Path = Path("runtime/accumulator_history.jsonl")) -> None:
    """Append-only audit log of plans/fills (one JSON object per line)."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({**record, "logged_utc": datetime.now(timezone.utc).isoformat()})
    with Path(path).open("a") as f:
        f.write(line + "\n")


def load_history(path: Path = Path("runtime/accumulator_history.jsonl")) -> List[Dict[str, Any]]:
    if not Path(path).exists():
        return []
    out: List[Dict[str, Any]] = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out
