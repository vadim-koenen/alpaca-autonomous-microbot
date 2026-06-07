async function fetchData(url) {
    try {
        const response = await fetch(url);
        return await response.json();
    } catch (error) {
        console.error(`Error fetching ${url}:`, error);
        return { error: error.message };
    }
}

function updateElement(id, value, className = '') {
    const el = document.getElementById(id);
    if (el) {
        el.textContent = value;
        if (className) el.className = className;
    }
}

function formatCurrency(value) {
    const num = parseFloat(value) || 0;
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(num);
}

async function refreshDashboard() {
    const status = await fetchData('/api/status');
    const heartbeat = await fetchData('/api/heartbeat/coinbase');
    const profit = await fetchData('/api/profit-readout');
    const watchdog = await fetchData('/api/watchdog/latest');
    const reconciler = await fetchData('/api/reconciler/latest');
    const diagnostics = await fetchData('/api/diagnostics/latest');

    // Status
    updateElement('stop-trading-status', status.stop_trading_present ? 'PRESENT' : 'MISSING', 
        status.stop_trading_present ? 'status-off' : 'status-on');
    updateElement('git-head', status.git_head);

    // Heartbeat
    if (heartbeat.error) {
        updateElement('hb-status', 'MISSING', 'status-off');
    } else {
        updateElement('hb-status', heartbeat.status || 'UNKNOWN', 
            heartbeat.status === 'running' ? 'status-on' : 'status-off');
        updateElement('hb-time', heartbeat.last_loop_time || 'N/A');
        updateElement('risk-halt', heartbeat.risk_halt_active ? 'ACTIVE' : 'INACTIVE',
            heartbeat.risk_halt_active ? 'status-off' : 'status-on');
    }

    // Profit
    updateElement('equity', formatCurrency(profit.equity));
    updateElement('buying-power', formatCurrency(profit.buying_power));
    updateElement('daily-pnl', formatCurrency(profit.daily_pnl), 
        profit.daily_pnl >= 0 ? 'status-on' : 'status-off');
    updateElement('cumulative-net', formatCurrency(profit.cumulative_net_usd));

    // Activity
    updateElement('trades-today', profit.trades_today);
    updateElement('last-trade', profit.last_trade_at || 'N/A');
    updateElement('last-exit', profit.last_exit_at || 'N/A');

    // Diagnostics
    updateElement('watchdog-level', watchdog.highest_alert_level || 'N/A',
        watchdog.highest_alert_level === 'CRITICAL' ? 'status-off' : 'status-on');
    updateElement('reconciler-verdict', reconciler.resume_micro_trading_go_no_go || 'N/A',
        reconciler.resume_micro_trading_go_no_go === 'GO' ? 'status-on' : 'status-off');
    updateElement('diag-action', diagnostics.recommended_next_action || 'N/A');
    document.getElementById('diag-json').textContent = JSON.stringify(diagnostics, null, 2);
}

// Initial refresh
refreshDashboard();

// Poll every 10 seconds
setInterval(refreshDashboard, 10000);
