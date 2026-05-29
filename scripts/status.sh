#!/usr/bin/env bash
# status.sh — Show current status of both bots.
# Reads heartbeat files and launchd state.

BOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

equities_likely_closed_reason() {
    # Weekend plus Memorial Day. This is a visibility hint only; trading gates
    # remain in Python risk/order code.
    local dow month day year last_monday
    dow="$(date +%u)"   # 1=Mon ... 7=Sun
    month="$(date +%m)"
    day="$(date +%d)"
    year="$(date +%Y)"

    if [[ "$dow" == "6" || "$dow" == "7" ]]; then
        echo "weekend"
        return
    fi

    if [[ "$month" == "05" && "$dow" == "1" ]]; then
        last_monday="$(python3 - "$year" <<'PY'
import calendar
import sys

year = int(sys.argv[1])
last = max(
    day for day in range(1, 32)
    if calendar.weekday(year, 5, day) == calendar.MONDAY
)
print(f"{last:02d}")
PY
)"
        if [[ "$day" == "$last_monday" ]]; then
            echo "Memorial Day"
            return
        fi
    fi
}

heartbeat_value() {
    local hb="$1"
    local key="$2"
    python3 - "$hb" "$key" <<'PY' 2>/dev/null || echo "?"
import json
import sys

with open(sys.argv[1]) as f:
    data = json.load(f)
value = data.get(sys.argv[2], "?")
print(value if value is not None else "none")
PY
}

redact_output() {
    if [[ -f "$BOT_DIR/scripts/redact.py" ]]; then
        python3 "$BOT_DIR/scripts/redact.py"
    else
        cat
    fi
}

echo "=== Trading Bot Status ==="
echo "$(date)"
echo ""

closed_reason="$(equities_likely_closed_reason)"
if [[ -n "$closed_reason" ]]; then
    echo "⚠️   U.S. equities likely closed: $closed_reason"
    echo "    Alpaca equity inactivity may be market-calendar related."
    echo ""
fi

# Kill switch
SWITCH="$BOT_DIR/runtime/STOP_TRADING"
if [[ -f "$SWITCH" ]]; then
    echo "⛔  KILL SWITCH ACTIVE — trading halted"
else
    echo "✅  Kill switch: inactive (trading allowed)"
fi
echo ""

# launchd / heartbeat / lock status
if [[ -f "$BOT_DIR/scripts/runtime_status.py" ]]; then
    python3 "$BOT_DIR/scripts/runtime_status.py" --root "$BOT_DIR" 2>/dev/null || {
        echo "--- Runtime supervisor ---"
        echo "  runtime status unavailable"
    }
else
    echo "--- Runtime supervisor ---"
    echo "  runtime status helper missing"
fi
echo ""

# Heartbeat files
echo "--- Heartbeats ---"
for broker in alpaca coinbase; do
    HB="$BOT_DIR/runtime/${broker}_heartbeat.json"
    if [[ -f "$HB" ]]; then
        last_loop=$(heartbeat_value "$HB" "last_loop_time")
        status=$(heartbeat_value "$HB" "status")
        pnl=$(heartbeat_value "$HB" "daily_pnl")
        trades=$(heartbeat_value "$HB" "trades_today")
        last_trade_at=$(heartbeat_value "$HB" "last_trade_at")
        last_exit_at=$(heartbeat_value "$HB" "last_exit_at")
        equity=$(heartbeat_value "$HB" "equity")
        open_positions=$(heartbeat_value "$HB" "open_positions")
        api_errors=$(heartbeat_value "$HB" "api_errors_this_session")
        consec_losses=$(heartbeat_value "$HB" "consecutive_losses")
        halt_active=$(heartbeat_value "$HB" "risk_halt_active")
        halt_reason=$(heartbeat_value "$HB" "halt_reason")
        bot_pid=$(heartbeat_value "$HB" "pid")
        if [[ "$last_trade_at" == "?" || "$last_trade_at" == "" || "$last_trade_at" == "None" || "$last_trade_at" == "null" ]]; then
            last_trade_at="none"
        fi
        if [[ "$last_exit_at" == "?" || "$last_exit_at" == "" || "$last_exit_at" == "None" || "$last_exit_at" == "null" ]]; then
            last_exit_at="none"
        fi
        echo "  $broker: status=$status | last_loop=$last_loop | equity=\$$equity | pnl=\$$pnl | trades=$trades"
        echo "          open_positions=$open_positions | consecutive_losses=$consec_losses | api_errors=$api_errors"
        echo "          last_trade_at=$last_trade_at | last_exit_at=$last_exit_at"
        # Halt state — only print if active
        if [[ "$halt_active" == "True" || "$halt_active" == "true" ]]; then
            echo "          ⛔ RISK HALT ACTIVE | halt_reason=$halt_reason"
        fi
        # Bot uptime from PID
        if [[ "$bot_pid" != "?" && "$bot_pid" =~ ^[0-9]+$ ]]; then
            uptime_str=$(ps -o etime= -p "$bot_pid" 2>/dev/null | tr -d ' ' || echo "")
            if [[ -n "$uptime_str" ]]; then
                echo "          pid=$bot_pid | uptime=$uptime_str"
            else
                echo "          pid=$bot_pid | uptime=not_found (process may have exited)"
            fi
        fi
    else
        echo "  $broker: no heartbeat file (bot not running or hasn't completed a cycle)"
    fi
done
echo ""

# Alpaca equity market-data visibility
ALPACA_LOG="$BOT_DIR/logs/alpaca.launchd.out.log"
if [[ -f "$ALPACA_LOG" ]]; then
    equity_data_skips=$(
        tail -100 "$ALPACA_LOG" \
            | grep -E "SCAN .* (equity|starter).* (invalid quote|stale quote|no bars|insufficient bars|spread too wide)" \
            | wc -l \
            | tr -d ' '
    )
    if [[ "$equity_data_skips" != "0" ]]; then
        echo "⚠️   Alpaca equity data warning: $equity_data_skips recent market-data skip(s)"
        echo "    Recent reasons:"
        tail -100 "$ALPACA_LOG" \
            | grep -E "SCAN .* (equity|starter).* (invalid quote|stale quote|no bars|insufficient bars|spread too wide)" \
            | tail -3 \
            | redact_output \
            | sed 's/^/      /'
        echo ""
    fi
fi

if [[ -f "$BOT_DIR/scripts/alpaca_no_trade_diagnose.py" ]]; then
    python3 "$BOT_DIR/scripts/alpaca_no_trade_diagnose.py" --brief 2>/dev/null || {
        echo "--- Alpaca movement ---"
        echo "  diagnosis unavailable; run: python3 scripts/alpaca_no_trade_diagnose.py"
    }
    echo ""
fi

# State maintenance preflight summary
if [[ -f "$BOT_DIR/scripts/state_maintenance_preflight.py" ]]; then
    preflight_json="$(python3 "$BOT_DIR/scripts/state_maintenance_preflight.py" --json 2>/dev/null || true)"
    if [[ -n "$preflight_json" ]]; then
        python3 - "$preflight_json" <<'PY'
import json
import sys

try:
    payload = json.loads(sys.argv[1])
except Exception:
    print("--- State preflight ---")
    print("  state_preflight_status=unavailable")
    raise SystemExit(0)

brokers = payload.get("brokers", {})
recovered_open = sum(
    int((brokers.get(broker) or {}).get("broker_recovered_open_count", 0))
    for broker in ("coinbase", "alpaca")
)
actions = payload.get("action_required_items") or []

print("--- State preflight ---")
print(f"  state_preflight_status={payload.get('overall_status', 'unknown')}")
print(f"  broker_recovered_open_count={recovered_open}")
print(f"  action_required_items={len(actions)}")
PY
        echo ""
    fi
fi

# Position state breakdown (coinbase broker)
echo "--- Coinbase position state ---"
export CB_STATE="$BOT_DIR/state/coinbase/open_positions.json"
export CB_CONFIG="$BOT_DIR/config_coinbase_crypto.yaml"
if [[ -f "$CB_STATE" ]]; then
    python3 - <<'PYEOF'
import json, os, sys
state_file = os.environ.get("CB_STATE", "")
try:
    with open(state_file) as f:
        data = json.load(f)
    positions = data.get("positions", {})
    if not positions:
        print("  (no tracked positions)")
        sys.exit(0)
    total_exposure = 0.0
    counted_exposure = 0.0
    manual_review_open_count = 0
    non_controllable_open_count = 0
    recovered = []
    pending = []
    filled = []
    def manual_review_override(pos):
        return (
            pos.get("manual_review_entry_override_approved") is True
            and pos.get("manual_review_entry_override_scope") == "allow_new_crypto_entries"
            and bool(pos.get("manual_review_entry_override_reason", ""))
        )
    for sym, pos in positions.items():
        notional = float(pos.get("notional", 0.0))
        status = pos.get("order_status", "unknown")
        api_ctrl = pos.get("api_controllable", status != "broker_recovered")
        exit_en = pos.get("exit_evaluation_enabled", status != "broker_recovered")
        user_act = pos.get("user_action_required", status == "broker_recovered")
        counts_exp = pos.get("counts_toward_exposure", True)
        override = manual_review_override(pos)
        total_exposure += notional
        if counts_exp is not False:
            counted_exposure += notional
        if not override:
            if user_act is True:
                manual_review_open_count += 1
            if api_ctrl is False or exit_en is False:
                non_controllable_open_count += 1
        entry = {"sym": sym, "notional": notional, "status": status,
                 "strategy": pos.get("strategy", "?"), "entry_price": pos.get("entry_price", 0)}
        if status == "broker_recovered":
            recovered.append(entry)
        elif status == "pending_new":
            pending.append(entry)
        elif status == "filled":
            filled.append(entry)
        else:
            filled.append(entry)  # treat other statuses as bot-placed
    try:
        import yaml
        config_path = os.environ.get("CB_CONFIG", "")
        if not config_path:
            config_path = os.path.join(os.path.dirname(state_file), "..", "..", "config_coinbase_crypto.yaml")
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        cap = float(cfg.get("crypto", {}).get("max_total_crypto_exposure_usd", 4.0))
    except Exception:
        cap = 4.0
    print(f"  tracked_exposure : ${total_exposure:.4f}")
    print(f"  counted_exposure : ${counted_exposure:.4f}")
    print(f"  exposure_cap     : ${cap:.2f}")
    exposure_blocked = counted_exposure >= cap
    manual_blocked = manual_review_open_count > 0 or non_controllable_open_count > 0
    guard_status = "🔴 BLOCKED" if exposure_blocked or manual_blocked else "🟢 ok"
    print(f"  exposure_guard   : {guard_status}")
    print(f"  manual_review_open_count    : {manual_review_open_count}")
    print(f"  non_controllable_open_count : {non_controllable_open_count}")
    entry_allowed = not exposure_blocked and not manual_blocked
    if manual_review_open_count > 0:
        block_reason = "manual_review_position_open"
    elif non_controllable_open_count > 0:
        block_reason = "non_controllable_position_open"
    elif exposure_blocked:
        block_reason = "exposure_cap_exceeded"
    else:
        block_reason = "none"
    print(f"  entry_allowed   : {'YES' if entry_allowed else 'NO'}")
    print(f"  block_reason    : {block_reason}")
    print(f"  positions        : {len(positions)} total | {len(filled)} bot-filled | {len(recovered)} broker-recovered | {len(pending)} pending")
    if recovered:
        print("  broker-recovered (consumer wallet, uncontrollable via API):")
        for e in recovered:
            print(f"    {e['sym']:12s}  notional=${e['notional']:.4f}  entry={e['entry_price']}")
        print("  coinbase_close_capability = unknown")
        print("  recommended_diagnostic    = python3 scripts/coinbase_position_capability_diagnose.py")
    if filled:
        print("  bot-placed positions:")
        for e in filled:
            print(f"    {e['sym']:12s}  notional=${e['notional']:.4f}  strategy={e['strategy']}  status={e['status']}")
    if pending:
        print("  pending_new (awaiting fill confirmation):")
        for e in pending:
            print(f"    {e['sym']:12s}  notional=${e['notional']:.4f}  strategy={e['strategy']}")
except FileNotFoundError:
    print("  (state file not found)")
except Exception as ex:
    print(f"  (error reading state: {ex})")
PYEOF
else
    echo "  (state file not found: $CB_STATE)"
fi
echo ""

# Recent logs
echo "--- Recent log lines ---"
for log in "$BOT_DIR/logs/alpaca.launchd.out.log" "$BOT_DIR/logs/coinbase.launchd.out.log"; do
    if [[ -f "$log" ]]; then
        echo "  $(basename "$log") (last 3 lines):"
        tail -3 "$log" | redact_output | sed 's/^/    /'
    fi
done
echo ""
echo "Watch live: scripts/tail_logs.sh"
