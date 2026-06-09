# Automation Setup — free, Claude-credit-free status sync

The Claude scheduled tasks (`coinbase-bot-spot-check`, `bot-handoff-sync`) are **disabled** — they burned credits per run. They're replaced by `scripts/handoff_status_sync.sh`, a Mac-native bash job that does the same work for $0 and writes shared context to git for GPT.

## What GPT reads
Branch **`ops/status`**, file **`docs/STATUS_AUTO.md`** (current snapshot) and `docs/STATUS_AUTO_LOG.md` (history). The sync writes there via an isolated git worktree, so your working branch and the running bot are never touched.

## One-time setup (run on the Mac)

1. Make the script executable and test it once (this also authenticates the push):
```bash
cd /Users/vadimkoenen/Documents/Claude/Projects/Investing/alpaca-autonomous-microbot
chmod +x scripts/handoff_status_sync.sh
bash scripts/handoff_status_sync.sh
```
You should see `synced+pushed ...`. Confirm on GitHub that branch `ops/status` now has `docs/STATUS_AUTO.md`.

2. Install the launchd job (every 4 hours). Create `~/Library/LaunchAgents/com.vadim.status-sync.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.vadim.status-sync</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>/Users/vadimkoenen/Documents/Claude/Projects/Investing/alpaca-autonomous-microbot/scripts/handoff_status_sync.sh</string>
  </array>
  <key>StartInterval</key><integer>14400</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>/tmp/status-sync.out.log</string>
  <key>StandardErrorPath</key><string>/tmp/status-sync.err.log</string>
</dict>
</plist>
```

3. Load it:
```bash
launchctl unload ~/Library/LaunchAgents/com.vadim.status-sync.plist 2>/dev/null
launchctl load ~/Library/LaunchAgents/com.vadim.status-sync.plist
```

To change cadence, edit `StartInterval` (seconds): 14400 = 4h, 3600 = hourly, 86400 = daily.

## Safety
Read-only w.r.t. broker/orders/`.env`. Writes only `docs/STATUS_AUTO*.md` on the `ops/status` branch via a worktree at `~/.investing_status_worktree`. Never restarts the bot, never touches `main` or your feature branch. Uses zero Claude credits.

## If you ever want a one-off check yourself
`bash scripts/audit_snapshot.sh` — prints the digest to your terminal, no commit.
