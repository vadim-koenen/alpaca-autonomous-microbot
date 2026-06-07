set repoRoot to "/Users/vadimkoenen/Documents/Claude/Projects/Investing/alpaca-autonomous-microbot"
set dashboardUrl to "http://localhost:8080"

do shell script "cd " & quoted form of repoRoot & " && bash scripts/launch_app_shell_mac.sh"

tell application "Google Chrome"
    open location dashboardUrl
    activate
end tell
