"""
report.py — Daily report generator.

Reads journal.csv and produces a human-readable text report.
Saved to /reports/report_YYYYMMDD.txt.
Also prints a summary to stdout.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from utils import ROOT, load_config, now_utc, get_mode

logger = logging.getLogger("report")


class ReportGenerator:
    def __init__(self) -> None:
        cfg = load_config()
        log_cfg = cfg.get("logging", {})
        self._journal_path = ROOT / log_cfg.get("journal_file", "journal.csv")
        self._report_dir = ROOT / log_cfg.get("report_dir", "reports")
        self._report_dir.mkdir(exist_ok=True)

    def generate_daily_report(
        self,
        target_date: Optional[date] = None,
        starting_equity: float = 0.0,
        ending_equity: float = 0.0,
        unrealized_pnl: float = 0.0,
    ) -> str:
        """
        Generate and save a daily report.
        Returns the report text.
        """
        if target_date is None:
            target_date = now_utc().date()

        date_str = target_date.strftime("%Y-%m-%d")
        mode = get_mode()

        # Load journal for today
        df = self._load_journal(target_date)

        # Compute metrics — guard against missing columns on empty/new journal
        def _safe_filter(frame, col, val):
            if frame.empty or col not in frame.columns:
                return pd.DataFrame()
            return frame[frame[col] == val]

        placed = _safe_filter(df, "decision", "PLACED")
        skipped = _safe_filter(df, "decision", "SKIPPED")
        exits = _safe_filter(df, "action", "EXIT")

        if not placed.empty and "action" in placed.columns:
            num_trades = len(placed[placed["action"].isin(["BUY", "SHORT", "COVER"])])
        else:
            num_trades = 0
        num_skipped = len(skipped)

        pnl_series = exits["pnl_usd"].astype(float) if not exits.empty and "pnl_usd" in exits.columns else pd.Series([], dtype=float)
        realized_pnl = pnl_series.sum() if not pnl_series.empty else 0.0

        wins = pnl_series[pnl_series > 0]
        losses = pnl_series[pnl_series < 0]
        win_rate = len(wins) / len(pnl_series) * 100.0 if len(pnl_series) > 0 else 0.0
        avg_win = wins.mean() if len(wins) > 0 else 0.0
        avg_loss = losses.mean() if len(losses) > 0 else 0.0
        largest_win = wins.max() if len(wins) > 0 else 0.0
        largest_loss = losses.min() if len(losses) > 0 else 0.0

        # Max drawdown (running min of cumulative P/L)
        if not pnl_series.empty:
            cumulative = pnl_series.cumsum()
            running_max = cumulative.cummax()
            drawdown = (cumulative - running_max)
            max_drawdown = drawdown.min()
        else:
            max_drawdown = 0.0

        # Errors and violations
        errors_df = df[df["action"] == "ERROR"] if not df.empty else pd.DataFrame()
        num_errors = len(errors_df)

        # Best and worst setups
        best_setup = ""
        worst_setup = ""
        if not exits.empty and "strategy" in exits.columns and "pnl_usd" in exits.columns:
            exits_copy = exits.copy()
            exits_copy["pnl_usd"] = exits_copy["pnl_usd"].astype(float)
            if not exits_copy.empty:
                best_idx = exits_copy["pnl_usd"].idxmax()
                worst_idx = exits_copy["pnl_usd"].idxmin()
                best_row = exits_copy.loc[best_idx]
                worst_row = exits_copy.loc[worst_idx]
                best_setup = (
                    f"{best_row.get('symbol','?')} / {best_row.get('strategy','?')} "
                    f"(+${float(best_row.get('pnl_usd',0)):.4f})"
                )
                worst_setup = (
                    f"{worst_row.get('symbol','?')} / {worst_row.get('strategy','?')} "
                    f"(${float(worst_row.get('pnl_usd',0)):.4f})"
                )

        # Skip breakdown
        skip_reasons = ""
        if not skipped.empty and "reason" in skipped.columns:
            top_reasons = skipped["reason"].value_counts().head(5)
            skip_reasons = "\n".join(
                f"  [{count:3d}x] {reason}" for reason, count in top_reasons.items()
            )

        # Config recommendations
        recommendations = _generate_recommendations(
            realized_pnl=realized_pnl,
            win_rate=win_rate,
            num_trades=num_trades,
            num_skipped=num_skipped,
            max_drawdown=max_drawdown,
            num_errors=num_errors,
        )

        # Compose report
        separator = "=" * 65
        report = f"""
{separator}
ALPACA AUTONOMOUS MICRO-BOT — DAILY REPORT
{separator}
Date              : {date_str}
Mode              : {mode.upper()}
Generated (UTC)   : {now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")}
{separator}
ACCOUNT
  Starting equity : ${starting_equity:.4f}
  Ending equity   : ${ending_equity:.4f}
  Change          : ${ending_equity - starting_equity:+.4f}

P/L SUMMARY
  Realized P/L    : ${realized_pnl:+.4f}
  Unrealized P/L  : ${unrealized_pnl:+.4f}
  Max drawdown    : ${max_drawdown:.4f}

TRADE STATS
  Trades placed   : {num_trades}
  Trades skipped  : {num_skipped}
  Exits logged    : {len(pnl_series)}
  Win rate        : {win_rate:.1f}%
  Average win     : ${avg_win:+.4f}
  Average loss    : ${avg_loss:.4f}
  Largest win     : ${largest_win:+.4f}
  Largest loss    : ${largest_loss:.4f}

BEST SETUP      : {best_setup or 'N/A'}
WORST SETUP     : {worst_setup or 'N/A'}

ERRORS          : {num_errors}

TOP SKIP REASONS:
{skip_reasons or '  (none)'}

RECOMMENDATIONS:
{recommendations}
{separator}
""".strip()

        # Save to file
        report_file = self._report_dir / f"report_{date_str}.txt"
        try:
            with open(report_file, "w") as f:
                f.write(report + "\n")
            logger.info(f"Daily report saved to {report_file}")
        except Exception as e:
            logger.error(f"Failed to save report: {e}")

        print("\n" + report + "\n")
        return report

    def _load_journal(self, target_date: date) -> pd.DataFrame:
        """Load journal rows for a specific date."""
        if not self._journal_path.exists():
            return pd.DataFrame()
        try:
            df = pd.read_csv(self._journal_path, low_memory=False)
            if df.empty or "timestamp" not in df.columns:
                return pd.DataFrame()
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
            df = df.dropna(subset=["timestamp"])
            mask = df["timestamp"].dt.date == target_date
            return df[mask].copy()
        except Exception as e:
            logger.error(f"Error loading journal for report: {e}")
            return pd.DataFrame()


def _generate_recommendations(
    realized_pnl: float,
    win_rate: float,
    num_trades: int,
    num_skipped: int,
    max_drawdown: float,
    num_errors: int,
) -> str:
    lines = []

    if num_trades == 0 and num_skipped > 10:
        lines.append("  - High skip rate with no trades. Consider loosening confidence threshold.")
    if win_rate > 0 and win_rate < 40:
        lines.append("  - Win rate < 40%. Review signal quality and spread filters.")
    if realized_pnl < -1.0:
        lines.append("  - P/L exceeds 50% of daily loss limit. Review stop-loss levels.")
    if max_drawdown < -1.5:
        lines.append("  - Max drawdown is large. Consider tighter stops.")
    if num_errors > 3:
        lines.append(f"  - {num_errors} API errors today. Check connectivity and API key validity.")
    if num_trades >= 5:
        lines.append("  - Hit max trades/day. Consider whether all signals were high quality.")
    if not lines:
        lines.append("  - No config changes recommended. Continue monitoring.")

    return "\n".join(lines)
