#!/usr/bin/env python3
"""
P2-031A Local App Shell Foundation Server (Read-Only).

A lightweight web server providing a read-only API and dashboard UI
for the investing bot.
"""

import http.server
import json
import os
import socketserver
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PORT = 8080
REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = REPO_ROOT / "app_shell" / "static"

class DashboardAPI:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root

    def get_status(self) -> Dict[str, Any]:
        stop_trading = (self.repo_root / "runtime" / "STOP_TRADING").exists()
        git_head = "unknown"
        try:
            git_head = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=self.repo_root,
                stderr=subprocess.DEVNULL,
                text=True
            ).strip()
        except:
            pass

        return {
            "bot_name": "alpaca-autonomous-microbot",
            "stop_trading_present": stop_trading,
            "git_head": git_head,
            "server_time_utc": datetime.now(timezone.utc).isoformat(),
            "read_only": True
        }

    def get_coinbase_heartbeat(self) -> Dict[str, Any]:
        path = self.repo_root / "runtime" / "coinbase_heartbeat.json"
        return self._read_json_safe(path)

    def get_latest_watchdog(self) -> Dict[str, Any]:
        search_dirs = [
            self.repo_root / "reports" / "operator_recovery",
            self.repo_root / "reports"
        ]
        latest_file = self._find_latest_json(search_dirs, "watchdog")
        return self._read_json_safe(latest_file) if latest_file else {"error": "No watchdog report found"}

    def get_latest_reconciler(self) -> Dict[str, Any]:
        search_dirs = [
            self.repo_root / "reports" / "operator_recovery",
            self.repo_root / "reports"
        ]
        latest_file = self._find_latest_json(search_dirs, "reconciler")
        return self._read_json_safe(latest_file) if latest_file else {"error": "No reconciler report found"}

    def get_latest_diagnostics(self) -> Dict[str, Any]:
        search_dirs = [self.repo_root / "reports" / "coinbase_diagnostics"]
        latest_file = self._find_latest_json(search_dirs, "diagnostics")
        return self._read_json_safe(latest_file) if latest_file else {"error": "No diagnostics report found"}

    def get_profit_readout(self) -> Dict[str, Any]:
        hb = self.get_coinbase_heartbeat()
        net_path = self.repo_root / "reports" / "spot_checks" / "last_net.txt"
        last_net = "0.00"
        if net_path.exists():
            try:
                last_net = net_path.read_text().strip()
            except:
                pass

        return {
            "daily_pnl": hb.get("daily_pnl", 0.0),
            "trades_today": hb.get("trades_today", 0),
            "last_trade_at": hb.get("last_trade_at"),
            "last_exit_at": hb.get("last_exit_at"),
            "cumulative_net_usd": last_net,
            "equity": hb.get("equity", 0.0),
            "buying_power": hb.get("buying_power", 0.0)
        }

    def _read_json_safe(self, path: Path) -> Dict[str, Any]:
        if not path or not path.exists():
            return {}
        try:
            return json.loads(path.read_text())
        except:
            return {"error": "Failed to parse JSON"}

    def _find_latest_json(self, dirs: List[Path], pattern: str) -> Optional[Path]:
        candidates = []
        for d in dirs:
            if not d.exists():
                continue
            for f in d.glob(f"*{pattern}*.json"):
                candidates.append(f)
        
        if not candidates:
            return None
        
        candidates.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        return candidates[0]

class ReadOnlyDashboardHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        self.api = DashboardAPI(REPO_ROOT)
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_GET(self):
        if self.path.startswith("/api/"):
            self.handle_api()
        else:
            super().do_GET()

    def handle_api(self):
        routes = {
            "/api/status": self.api.get_status,
            "/api/heartbeat/coinbase": self.api.get_coinbase_heartbeat,
            "/api/watchdog/latest": self.api.get_latest_watchdog,
            "/api/reconciler/latest": self.api.get_latest_reconciler,
            "/api/diagnostics/latest": self.api.get_latest_diagnostics,
            "/api/profit-readout": self.api.get_profit_readout,
        }

        handler = routes.get(self.path)
        if handler:
            try:
                data = handler()
                self.send_json(data)
            except Exception as e:
                self.send_json({"error": str(e)}, status=500)
        else:
            self.send_json({"error": "Not Found"}, status=404)

def run_server():
    print(f"Starting read-only app shell foundation on http://localhost:{PORT}")
    with socketserver.TCPServer(("", PORT), ReadOnlyDashboardHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server.")
            httpd.shutdown()

if __name__ == "__main__":
    run_server()
