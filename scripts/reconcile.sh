#!/usr/bin/env bash
# reconcile.sh — One-command broker reconciliation report.
#
# Answers:
#   Can the bot trade right now?
#   If not, why not?
#   What exact exposure is blocking it?
#   Can the bot control that exposure?
#   What user action is required?
#
# Reads: heartbeat files, state files, config files.
# Does NOT make live broker API calls — offline-safe.
#
# Usage:
#   bash scripts/reconcile.sh            # normal report
#   bash scripts/reconcile.sh --dry-run  # label output as dry-run (same logic; no side effects)

DRY_RUN=0
for arg in "$@"; do
    if [[ "$arg" == "--dry-run" ]]; then
        DRY_RUN=1
    fi
done

BOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CB_STATE="$BOT_DIR/state/coinbase/open_positions.json"
AL_STATE="$BOT_DIR/state/alpaca/open_positions.json"
CB_CFG="$BOT_DIR/config_coinbase_crypto.yaml"
AL_CFG="$BOT_DIR/config_alpaca_stocks.yaml"
CB_HB="$BOT_DIR/runtime/coinbase_heartbeat.json"
AL_HB="$BOT_DIR/runtime/alpaca_heartbeat.json"

if [[ "$DRY_RUN" == "1" ]]; then
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║       BROKER RECONCILIATION REPORT  [DRY-RUN]               ║"
    echo "║  (no broker API calls; reading local state files only)      ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
else
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║          BROKER RECONCILIATION REPORT                       ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
fi
echo "  Generated : $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo ""

python3 - <<'PYEOF'
import json, os, sys
from pathlib import Path

BOT_DIR = Path(os.environ.get("BOT_DIR", Path(__file__).parent.parent))
CB_STATE = Path(os.environ.get("CB_STATE", BOT_DIR / "state/coinbase/open_positions.json"))
AL_STATE = Path(os.environ.get("AL_STATE", BOT_DIR / "state/alpaca/open_positions.json"))
CB_CFG   = Path(os.environ.get("CB_CFG",   BOT_DIR / "config_coinbase_crypto.yaml"))
AL_CFG   = Path(os.environ.get("AL_CFG",   BOT_DIR / "config_alpaca_stocks.yaml"))
CB_HB    = Path(os.environ.get("CB_HB",    BOT_DIR / "runtime/coinbase_heartbeat.json"))
AL_HB    = Path(os.environ.get("AL_HB",    BOT_DIR / "runtime/alpaca_heartbeat.json"))

try:
    import yaml
    def load_yaml(p):
        with open(p) as f:
            return yaml.safe_load(f) or {}
except ImportError:
    def load_yaml(p):
        return {}

def load_json(p):
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return {}

def load_hb(p):
    return load_json(p)

def fmt_usd(v):
    try:
        return f"${float(v):.4f}"
    except Exception:
        return "?"

def bool_icon(v):
    return "✅" if v else "❌"

def manual_review_override(pos):
    return (
        pos.get("manual_review_entry_override_approved") is True
        and pos.get("manual_review_entry_override_scope") == "allow_new_crypto_entries"
        and bool(pos.get("manual_review_entry_override_reason", ""))
    )

# ── Heartbeat / account state ─────────────────────────────────────────────
print("── ACCOUNT STATE ──────────────────────────────────────────────────")

for label, hb_path in [("Alpaca", AL_HB), ("Coinbase", CB_HB)]:
    hb = load_hb(hb_path)
    if hb:
        eq     = fmt_usd(hb.get("equity", "?"))
        bp     = fmt_usd(hb.get("buying_power", "?"))
        status = hb.get("status", "?")
        loop   = hb.get("last_loop_time", "?")
        pnl    = fmt_usd(hb.get("daily_pnl", "?"))
        trades = hb.get("trades_today", "?")
        halt   = hb.get("risk_halt_active", False)
        halt_r = hb.get("halt_reason") or "—"
        print(f"  {label:8s}  equity={eq}  buying_power={bp}  status={status}  last_loop={loop}")
        print(f"            daily_pnl={pnl}  trades_today={trades}  halted={halt}  halt_reason={halt_r}")
    else:
        print(f"  {label:8s}  (no heartbeat — bot not running or hasn't completed a cycle)")
print()

# ── Config caps ───────────────────────────────────────────────────────────
print("── RISK CONFIG (from yaml) ─────────────────────────────────────────")
cb_cfg = load_yaml(CB_CFG)
al_cfg = load_yaml(AL_CFG)

# Coinbase caps
crypto_cap  = float((cb_cfg.get("crypto") or {}).get("max_total_crypto_exposure_usd", 4.0))
global_cap  = float((cb_cfg.get("global_risk") or {}).get("max_total_live_exposure_usd", 6.0))
max_trade   = float((cb_cfg.get("crypto") or {}).get("max_trade_notional_usd", 3.0))
max_loss    = float((cb_cfg.get("global_risk") or {}).get("max_daily_loss_usd", 2.0))
max_consec  = int((cb_cfg.get("global_risk") or {}).get("stop_after_consecutive_losses", 2))
eq_floor    = float((cb_cfg.get("account") or {}).get("disable_live_below_equity", 7.0))

print(f"  Coinbase crypto_exposure_cap    = ${crypto_cap:.2f}  [crypto.max_total_crypto_exposure_usd]  ← primary crypto guard")
print(f"  Coinbase global_exposure_cap    = ${global_cap:.2f}  [global_risk.max_total_live_exposure_usd]")
print(f"  max_trade_notional_crypto       = ${max_trade:.2f}")
print(f"  max_daily_loss                  = ${max_loss:.2f}")
print(f"  max_consecutive_losses          = {max_consec}")
print(f"  equity_floor                    = ${eq_floor:.2f}")
print()

# ── Coinbase positions ─────────────────────────────────────────────────────
print("── COINBASE POSITIONS ─────────────────────────────────────────────")
cb_data = load_json(CB_STATE)
cb_positions = cb_data.get("positions", {})
saved_at = cb_data.get("saved_at", "?")
print(f"  State file saved : {saved_at}")
print(f"  Positions        : {len(cb_positions)}")
print()

bot_placed_exp    = 0.0
recovered_exp     = 0.0
excluded_exp      = 0.0
user_actions      = []
manual_review_open_count = 0
non_controllable_open_count = 0

for sym, pos in cb_positions.items():
    notional     = float(pos.get("notional", 0.0))
    order_status = pos.get("order_status", "unknown")
    strategy     = pos.get("strategy", "?")
    api_ctrl     = pos.get("api_controllable", order_status != "broker_recovered")
    exit_en      = pos.get("exit_evaluation_enabled", order_status != "broker_recovered")
    counts_exp   = pos.get("counts_toward_exposure", True)
    user_act     = pos.get("user_action_required", order_status == "broker_recovered")
    bot_opened   = strategy not in ("recovered", "") and order_status != "broker_recovered"
    override     = manual_review_override(pos)
    entry_price  = pos.get("entry_price", "?")
    sl           = pos.get("stop_loss", "?")
    tp           = pos.get("take_profit", "?")

    if not override:
        if user_act:
            manual_review_open_count += 1
        if api_ctrl is False or exit_en is False:
            non_controllable_open_count += 1

    if order_status == "broker_recovered":
        classification = "external/untradeable (consumer wallet)"
        if counts_exp:
            recovered_exp += notional
        else:
            excluded_exp += notional
            classification += " — excluded from exposure cap"
        if user_act and not override:
            user_actions.append(
                f"  → {sym}: Transfer from consumer Coinbase wallet to Advanced Trade, "
                "or manually exclude after explicit approval."
            )
    else:
        classification = "bot-placed"
        if counts_exp:
            bot_placed_exp += notional
        else:
            excluded_exp += notional
            classification += " — excluded from exposure cap"
        if (user_act or api_ctrl is False or exit_en is False) and not override:
            user_actions.append(
                f"  → {sym}: Resolve manual-review/non-controllable state before "
                "allowing unattended Coinbase entries."
            )

    print(f"  {sym}")
    print(f"    notional                  = {fmt_usd(notional)}")
    print(f"    classification            = {classification}")
    print(f"    order_status              = {order_status}")
    print(f"    source                    = {pos.get('recovery_source', 'bot_strategy')}")
    print(f"    api_controllable          = {bool_icon(api_ctrl)}  {api_ctrl}")
    print(f"    bot_opened                = {bool_icon(bot_opened)}  {bot_opened}")
    print(f"    exit_evaluation_enabled   = {bool_icon(exit_en)}  {exit_en}")
    print(f"    counts_toward_exposure    = {bool_icon(counts_exp)}  {counts_exp}")
    print(f"    user_action_required      = {'⚠️ ' if user_act else '  '}  {user_act}")
    print(f"    entry_price               = {entry_price}  |  stop={sl}  |  tp={tp}")
    print()

# ── Alpaca positions ───────────────────────────────────────────────────────
print("── ALPACA POSITIONS ───────────────────────────────────────────────")
al_data = load_json(AL_STATE)
al_positions = al_data.get("positions", {})
al_saved_at = al_data.get("saved_at", "?")
print(f"  State file saved : {al_saved_at}")
print(f"  Positions        : {len(al_positions)}")
if al_positions:
    for sym, pos in al_positions.items():
        print(f"  {sym}  notional={fmt_usd(pos.get('notional',0))}  "
              f"status={pos.get('order_status','?')}  strategy={pos.get('strategy','?')}")
else:
    print("  (none)")
print()

# ── Risk totals ────────────────────────────────────────────────────────────
print("── RISK TOTALS ─────────────────────────────────────────────────────")
total_counted = bot_placed_exp + recovered_exp
entry_block_reason = ""
if manual_review_open_count > 0:
    entry_block_reason = "manual_review_position_open"
elif non_controllable_open_count > 0:
    entry_block_reason = "non_controllable_position_open"
elif total_counted >= crypto_cap:
    overage = total_counted - crypto_cap
    entry_block_reason = (
        f"total_counted_exposure {fmt_usd(total_counted)} >= "
        f"crypto_cap ${crypto_cap:.2f} (overage: {fmt_usd(overage)})"
    )
entry_allowed = entry_block_reason == ""

print(f"  bot_placed_exposure             = {fmt_usd(bot_placed_exp)}")
print(f"  external_untradeable_exposure   = {fmt_usd(recovered_exp)}  (broker_recovered)")
print(f"  explicitly_excluded_exposure    = {fmt_usd(excluded_exp)}  (counts_toward_exposure=false)")
print(f"  total_counted_exposure          = {fmt_usd(total_counted)}")
print(f"  manual_review_open_count        = {manual_review_open_count}")
print(f"  non_controllable_open_count     = {non_controllable_open_count}")
print(f"  crypto_exposure_cap             = ${crypto_cap:.2f}  [crypto.max_total_crypto_exposure_usd]")
print(f"  global_exposure_cap             = ${global_cap:.2f}  [global_risk.max_total_live_exposure_usd]")
print()

if entry_allowed:
    headroom = crypto_cap - total_counted
    print(f"  entry_allowed                   = {bool_icon(True)}  YES  (headroom: {fmt_usd(headroom)})")
    print(f"  block_reason                    = none")
else:
    print(f"  entry_allowed                   = {bool_icon(False)}  NO")
    print(f"  block_reason                    = {entry_block_reason}")
print()

# ── User actions required ──────────────────────────────────────────────────
if user_actions:
    print("── USER ACTIONS REQUIRED ───────────────────────────────────────────")
    for action in user_actions:
        print(action)
    print()

# ── Summary verdict ────────────────────────────────────────────────────────
print("── VERDICT ─────────────────────────────────────────────────────────")
if entry_allowed:
    print("  ✅  Bot can open new Coinbase entries (exposure below cap).")
else:
    if manual_review_open_count > 0 or non_controllable_open_count > 0:
        print("  🔴  Bot CANNOT open new Coinbase entries.")
        print("      Reason: manual-review or non-controllable Coinbase position is open.")
        print("      Resolve the position state or use a separately approved override.")
    elif recovered_exp > 0:
        print("  🔴  Bot CANNOT open new Coinbase entries.")
        print(f"      Reason: {fmt_usd(recovered_exp)} of external/untradeable exposure")
        print(f"      (broker_recovered positions in consumer Coinbase wallet)")
        print(f"      is eating into the ${crypto_cap:.2f} crypto cap.")
        print()
        print("      To unblock:")
        print("        1. Transfer ETH (and any other recovered assets) from your")
        print("           consumer Coinbase wallet into your Advanced Trade account.")
        print("        2. Wait for bot to detect position gone → auto-cleanup.")
        print("        3. Run ./scripts/reconcile.sh again to confirm unblocked.")
    else:
        print(f"  🔴  Bot CANNOT open new Coinbase entries (bot-placed exposure full).")
print()

PYEOF
