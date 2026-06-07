# App Shell Mac Launcher

P2-032A adds a small Mac launcher foundation for the local Investing Bot app shell.

The launcher starts the existing read-only local dashboard and opens it in the browser.

## Run from Terminal

Run:

    bash scripts/launch_app_shell_mac.sh

## What it starts

The launcher starts:

    PYTHONPATH=.:scripts python3 scripts/run_app_shell.py

## URL

    http://localhost:8080

The port can be overridden with:

    APP_SHELL_PORT=8081 bash scripts/launch_app_shell_mac.sh

## Logs

Launcher logs are written under:

    reports/app_shell/app_shell_<timestamp>.log

## Compile a Mac app

From the repo root:

    osacompile -o "Investing Bot.app" app_shell/macos/InvestingBotLauncher.applescript

Then open it:

    open "Investing Bot.app"

You can drag or pin the compiled app to the Dock.

A custom icon can be added later.

## Troubleshooting port 8080

Check whether the app shell is already listening:

    lsof -iTCP:8080 -sTCP:LISTEN -P -n

If it is already running, the launcher opens the existing dashboard instead of starting another copy.

## Stop the app shell

    pkill -f "scripts/run_app_shell.py" || true
    pkill -f "app_shell.server" || true

## Read-only safety warning

This launcher is read-only.

It does not place/cancel/close orders.

It does not mutate broker state.

It does not remove `runtime/STOP_TRADING`.

It does not restart live trading.

It does not run `main.py --mode live`.

It does not scale or change strategy.
