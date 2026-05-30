#!/usr/bin/env python3
"""
coinbase_exploration_performance_report.py

Analyzes Coinbase controlled_exploration trades to answer:
  "Can $1.00 trades overcome Coinbase fee drag?"

Reads journal CSVs in priority order:
  1. logs/coinbase_journal.csv
  2. state/coinbase/journal.csv
  3. journal.csv
  4. logs/coinbase.launchd.out.log (fallback parser)

Advisory only. No live system mutation.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, List, Tuple
import csv

try:
    import pandas as pd
except ImportError:
    pd = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
)
logger = logging.getLogger("coinbase_exploration_perf")

ROOT = Path(__file__).parent.parent


class CoinbaseExplorationAnalyzer:
    """Analyzes Coinbase controlled_exploration trades."""

    def __init__(self):
        self.df = None
        self.trades = []

    def find_journal_file(self) -> Optional[Path]:
        """Find journal file in priority order."""
        candidates = [
            ROOT / "logs" / "coinbase_journal.csv",
            ROOT / "state" / "coinbase" / "journal.csv",
            ROOT / "journal_coinbase_crypto.csv",
            ROOT / "journal.csv",
        ]
        for path in candidates:
            if path.exists():
                logger.info(f"Found journal: {path}")
                return path
        logger.warning("No journal file found in priority locations")
        return None

    def load_journal(self) -> bool:
        """Load and parse journal CSV."""
        journal_path = self.find_journal_file()
        if not journal_path:
            logger.error("No journal file available")
            return False

        if pd is None:
            logger.error("pandas required but not installed")
            return False

        try:
            self.df = pd.read_csv(journal_path, low_memory=False)
            if self.df.empty:
                logger.warning("Journal is empty")
                return False

            logger.info(f"Loaded {len(self.df)} rows from {journal_path}")

            # Convert timestamp to datetime
            if "timestamp" in self.df.columns:
                self.df["timestamp"] = pd.to_datetime(
                    self.df["timestamp"], utc=True, errors="coerce"
                )
                self.df = self.df.dropna(subset=["timestamp"])

            return True
        except Exception as e:
            logger.error(f"Failed to load journal: {e}")
            return False

    def extract_exploration_trades(self) -> List[Dict]:
        """Extract round trips from exploration trades."""
        if self.df is None or self.df.empty:
            return []

        trades = []

        # Filter for exploration trades
        df_filtered = self.df.copy()

        # Only include rows with strategy matching exploration patterns
        if "strategy" in df_filtered.columns:
            df_filtered = df_filtered[
                df_filtered["strategy"].isin([
                    "controlled_exploration",
                    "coinbase_exploration",
                ])
            ]

        if df_filtered.empty:
            logger.warning("No controlled_exploration trades found")
            return []

        # Group by symbol to form round trips
        for symbol, group in df_filtered.groupby("symbol"):
            group = group.sort_values("timestamp")

            # Pair entry and exit rows
            entries = []
            for _, row in group.iterrows():
                action = str(row.get("action", "")).upper()
                status = str(row.get("status", "")).upper()
                
                # Accept BUY/SHORT with various status values
                # (PLACED, preview, pending_new, or filled orders)
                if action in ["BUY", "SHORT"]:
                    # Only use non-error entry rows with reasonable qty
                    qty = float(row.get("qty", 0.0) or 0.0)
                    if qty > 0:
                        entries.append(row)
                
                # Collect EXIT rows for pairing
                elif action == "EXIT" and entries:
                    # EXIT should have valid exit_price and reason
                    exit_price = float(row.get("exit_price", 0.0) or 0.0)
                    reason = str(row.get("reason", "unknown"))
                    
                    # Only pair if we have valid exit data
                    if exit_price != 0.0 and reason != "nan":
                        entry = entries.pop(0)
                        trade = self._construct_trade(entry, row, symbol)
                        if trade:
                            trades.append(trade)

        logger.info(f"Extracted {len(trades)} round trips")
        return trades

    def _construct_trade(
        self, entry: pd.Series, exit_row: pd.Series, symbol: str
    ) -> Optional[Dict]:
        """Construct a trade record from entry and exit."""
        try:
            entry_price = float(entry.get("fill_price", 0.0) or 0.0)
            exit_price = float(exit_row.get("exit_price", 0.0) or 0.0)
            qty = float(exit_row.get("qty", 0.0) or 0.0)
            gross_pnl = float(exit_row.get("gross_pnl", 0.0) or 0.0)
            fees = float(exit_row.get("fees_paid", 0.0) or 0.0)
            net_pnl = float(exit_row.get("pnl_usd", 0.0) or 0.0)
            reason = str(exit_row.get("reason", "unknown")).lower()
            regime = str(exit_row.get("regime", "unknown")).lower()

            # Determine exit type from reason
            exit_type = self._classify_exit_type(reason)

            return {
                "symbol": symbol,
                "entry_time": entry.get("timestamp"),
                "exit_time": exit_row.get("timestamp"),
                "entry_price": entry_price,
                "exit_price": exit_price,
                "qty": qty,
                "gross_pnl": gross_pnl,
                "fees": fees,
                "net_pnl": net_pnl,
                "exit_type": exit_type,
                "regime": regime,
                "reason": reason,
            }
        except Exception as e:
            logger.debug(f"Failed to construct trade: {e}")
            return None

    def _classify_exit_type(self, reason: str) -> str:
        """Classify exit type from reason text."""
        reason_lower = reason.lower()
        if "max hold" in reason_lower or "max_hold" in reason_lower:
            return "max_hold"
        elif "stop" in reason_lower or "stop_loss" in reason_lower:
            return "stop_loss"
        elif "take profit" in reason_lower or "take_profit" in reason_lower:
            return "take_profit"
        else:
            return "unknown"

    def compute_metrics(self, trades: List[Dict]) -> Dict:
        """Compute performance metrics."""
        metrics = {
            "total_trades": len(trades),
            "gross_pnl_total": 0.0,
            "fees_total": 0.0,
            "net_pnl_total": 0.0,
            "gross_wins": 0,
            "gross_losses": 0,
            "net_wins": 0,
            "net_losses": 0,
            "by_symbol": {},
            "by_exit_type": {},
            "by_regime": {},
        }

        for trade in trades:
            # Aggregate totals
            metrics["gross_pnl_total"] += trade["gross_pnl"]
            metrics["fees_total"] += trade["fees"]
            metrics["net_pnl_total"] += trade["net_pnl"]

            if trade["gross_pnl"] > 0:
                metrics["gross_wins"] += 1
            elif trade["gross_pnl"] < 0:
                metrics["gross_losses"] += 1

            if trade["net_pnl"] > 0:
                metrics["net_wins"] += 1
            elif trade["net_pnl"] < 0:
                metrics["net_losses"] += 1

            # By symbol
            symbol = trade["symbol"]
            if symbol not in metrics["by_symbol"]:
                metrics["by_symbol"][symbol] = {
                    "count": 0,
                    "gross_pnl": 0.0,
                    "fees": 0.0,
                    "net_pnl": 0.0,
                    "gross_wins": 0,
                    "gross_losses": 0,
                    "net_wins": 0,
                    "net_losses": 0,
                }
            metrics["by_symbol"][symbol]["count"] += 1
            metrics["by_symbol"][symbol]["gross_pnl"] += trade["gross_pnl"]
            metrics["by_symbol"][symbol]["fees"] += trade["fees"]
            metrics["by_symbol"][symbol]["net_pnl"] += trade["net_pnl"]
            if trade["gross_pnl"] > 0:
                metrics["by_symbol"][symbol]["gross_wins"] += 1
            else:
                metrics["by_symbol"][symbol]["gross_losses"] += 1
            if trade["net_pnl"] > 0:
                metrics["by_symbol"][symbol]["net_wins"] += 1
            else:
                metrics["by_symbol"][symbol]["net_losses"] += 1

            # By exit type
            exit_type = trade["exit_type"]
            if exit_type not in metrics["by_exit_type"]:
                metrics["by_exit_type"][exit_type] = {
                    "count": 0,
                    "net_pnl_total": 0.0,
                    "net_wins": 0,
                }
            metrics["by_exit_type"][exit_type]["count"] += 1
            metrics["by_exit_type"][exit_type]["net_pnl_total"] += trade["net_pnl"]
            if trade["net_pnl"] > 0:
                metrics["by_exit_type"][exit_type]["net_wins"] += 1

            # By regime
            regime = trade.get("regime", "unknown")
            if regime not in metrics["by_regime"]:
                metrics["by_regime"][regime] = {
                    "count": 0,
                    "net_pnl_total": 0.0,
                }
            metrics["by_regime"][regime]["count"] += 1
            metrics["by_regime"][regime]["net_pnl_total"] += trade["net_pnl"]

        return metrics

    def generate_report(self) -> str:
        """Generate the performance report."""
        if not self.load_journal():
            return "ERROR: Could not load journal"

        trades = self.extract_exploration_trades()
        if not trades:
            return "No controlled_exploration trades found"

        metrics = self.compute_metrics(trades)

        lines = []
        lines.append("=" * 70)
        lines.append("COINBASE CONTROLLED EXPLORATION PERFORMANCE REPORT")
        lines.append("=" * 70)
        lines.append(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%SZ')}")
        lines.append(f"Total round trips: {metrics['total_trades']}")
        lines.append("")

        # Summary section
        lines.append("SUMMARY")
        lines.append("-" * 70)
        gross_wr = (
            (metrics["gross_wins"] / metrics["total_trades"] * 100)
            if metrics["total_trades"] > 0
            else 0.0
        )
        net_wr = (
            (metrics["net_wins"] / metrics["total_trades"] * 100)
            if metrics["total_trades"] > 0
            else 0.0
        )
        avg_gross = (
            metrics["gross_pnl_total"] / metrics["total_trades"]
            if metrics["total_trades"] > 0
            else 0.0
        )
        avg_net = (
            metrics["net_pnl_total"] / metrics["total_trades"]
            if metrics["total_trades"] > 0
            else 0.0
        )

        lines.append(f"  Gross win rate:        {gross_wr:.1f}%")
        lines.append(f"  Net win rate:          {net_wr:.1f}%")
        lines.append(f"  Total gross P/L:       ${metrics['gross_pnl_total']:+.4f}")
        lines.append(f"  Total estimated fees:  ${metrics['fees_total']:+.4f}")
        lines.append(f"  Total net P/L:         ${metrics['net_pnl_total']:+.4f}")
        lines.append(f"  Average gross/trade:   ${avg_gross:+.4f}")
        lines.append(f"  Average net/trade:     ${avg_net:+.4f}")
        lines.append("")

        # By symbol
        lines.append("BY SYMBOL")
        lines.append("-" * 70)
        for symbol in sorted(metrics["by_symbol"].keys()):
            sym_data = metrics["by_symbol"][symbol]
            sym_gross_wr = (
                (sym_data["gross_wins"] / sym_data["count"] * 100)
                if sym_data["count"] > 0
                else 0.0
            )
            sym_net_wr = (
                (sym_data["net_wins"] / sym_data["count"] * 100)
                if sym_data["count"] > 0
                else 0.0
            )
            sym_avg_net = (
                sym_data["net_pnl"] / sym_data["count"]
                if sym_data["count"] > 0
                else 0.0
            )
            lines.append(f"  {symbol}")
            lines.append(f"    Trades:              {sym_data['count']}")
            lines.append(f"    Gross P/L:           ${sym_data['gross_pnl']:+.4f}")
            lines.append(f"    Fees:                ${sym_data['fees']:+.4f}")
            lines.append(f"    Net P/L:             ${sym_data['net_pnl']:+.4f}")
            lines.append(f"    Gross win rate:      {sym_gross_wr:.1f}%")
            lines.append(f"    Net win rate:        {sym_net_wr:.1f}%")
            lines.append(f"    Average net/trade:   ${sym_avg_net:+.4f}")
            lines.append("")

        # Exit type distribution
        lines.append("EXIT TYPE DISTRIBUTION")
        lines.append("-" * 70)
        for exit_type in sorted(metrics["by_exit_type"].keys()):
            exit_data = metrics["by_exit_type"][exit_type]
            exit_avg = (
                exit_data["net_pnl_total"] / exit_data["count"]
                if exit_data["count"] > 0
                else 0.0
            )
            lines.append(f"  {exit_type}")
            lines.append(f"    Count:               {exit_data['count']}")
            lines.append(f"    Total net P/L:       ${exit_data['net_pnl_total']:+.4f}")
            lines.append(f"    Average net:         ${exit_avg:+.4f}")
            lines.append("")

        # Fee breakeven analysis
        lines.append("FEE BREAKEVEN ANALYSIS")
        lines.append("-" * 70)
        if metrics["total_trades"] > 0:
            avg_fee_per_trade = metrics["fees_total"] / metrics["total_trades"]
            avg_gross_per_trade = avg_gross
            min_gross_move = avg_fee_per_trade

            lines.append(f"  Average fee per trade:     ${avg_fee_per_trade:+.4f}")
            lines.append(f"  Minimum gross move needed: ${min_gross_move:+.4f}")
            lines.append(f"  Average actual gross move: ${avg_gross_per_trade:+.4f}")

            if avg_gross_per_trade >= min_gross_move:
                lines.append(f"  Status:                     ✓ Breakeven viable")
            else:
                lines.append(f"  Status:                     ✗ Below breakeven")
        lines.append("")

        # Regime breakdown
        if metrics["by_regime"]:
            lines.append("REGIME BREAKDOWN")
            lines.append("-" * 70)
            for regime in sorted(metrics["by_regime"].keys()):
                regime_data = metrics["by_regime"][regime]
                regime_avg = (
                    regime_data["net_pnl_total"] / regime_data["count"]
                    if regime_data["count"] > 0
                    else 0.0
                )
                lines.append(f"  {regime}")
                lines.append(f"    Count:               {regime_data['count']}")
                lines.append(f"    Total net P/L:       ${regime_data['net_pnl_total']:+.4f}")
                lines.append(f"    Average net:         ${regime_avg:+.4f}")
                lines.append("")

        # Warnings
        lines.append("WARNINGS & DIAGNOSTICS")
        lines.append("-" * 70)
        warnings = []

        if metrics["net_pnl_total"] < 0:
            warnings.append(
                "  ⚠ Net P/L is negative. Exploration is useful for learning"
            )
            warnings.append("    but NOT YET PROFITABLE.")

        all_max_hold = all(
            t["exit_type"] == "max_hold" for t in trades
        )
        if all_max_hold:
            warnings.append(
                "  ⚠ All exits are max_hold. Stop-loss/take-profit thresholds"
            )
            warnings.append("    are NOT PARTICIPATING.")

        if not warnings:
            warnings.append("  ✓ No issues detected.")

        for warning in warnings:
            lines.append(warning)
        lines.append("")

        lines.append("=" * 70)

        return "\n".join(lines)


def main():
    """Main entry point."""
    analyzer = CoinbaseExplorationAnalyzer()
    report = analyzer.generate_report()
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
