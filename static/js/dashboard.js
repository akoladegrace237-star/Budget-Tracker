/**
 * dashboard.js — Flask Budget Tracker dashboard
 * Fetches data from /api/dashboard-data and renders the rich dashboard UI.
 */

// ─── Helpers ──────────────────────────────────────────────────────────────────
const CURRENCY = window.CURRENCY || '£';

function fmt(n) {
    return CURRENCY + Number(n || 0).toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
}

// ─── Greeting & date ─────────────────────────────────────────────────────────

function setGreeting(username) {
    const h = new Date().getHours();
    const greet = h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
    setText('greetingMsg', `${greet}, ${username || 'there'} 👋`);
    const opts = { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' };
    setText('dashboardDate', new Date().toLocaleDateString('en-GB', opts));
}

// ─── Cards ────────────────────────────────────────────────────────────────────

function populateCards(data) {
    const t = data.totals;
    setText('netWorthAmount',          fmt(t.net_worth));
    setText('totalIncome',             fmt(t.income));
    setText('totalExpenses',           fmt(t.expenses));
    setText('totalSavings',            fmt(t.savings));
    setText('totalInvestments',        fmt(t.investments));
    setText('totalDebt',               fmt(t.debt));
    setText('totalPortfolioValue',     fmt(t.portfolio));

    // This month income vs expense
    const cm = data.current_month;
    setText('monthIncome',  fmt(cm.income));
    setText('monthExpense', fmt(cm.expense));

    // Left-over row on income card
    const bal   = cm.balance;
    const balEl = document.getElementById('monthBalance');
    if (balEl) {
        balEl.textContent = fmt(Math.abs(bal));
        balEl.className   = 'card-month-val ' + (bal >= 0 ? 'positive' : 'danger');
        // Update label
        const row = document.getElementById('monthBalanceRow');
        if (row) {
            const label = row.querySelector('.card-month-tag');
            if (label) label.textContent = bal >= 0 ? 'Left over' : 'Over budget';
        }
    }
}

// ─── Budget health ────────────────────────────────────────────────────────────

function populateHealth(score) {
    const fill   = document.getElementById('healthFill');
    const badge  = document.getElementById('healthScoreBadge');
    const status = document.getElementById('healthStatus');
    const pct    = document.getElementById('healthPercent');

    if (!fill) return;

    fill.style.width = score + '%';

    let label, color, msg;
    if (score >= 80)      { label = 'Excellent'; color = '#06C270'; msg = '🌟 Excellent financial health! Keep it up.'; }
    else if (score >= 60) { label = 'Good';      color = '#4361EE'; msg = '👍 Good financial health. A few tweaks could make it great.'; }
    else if (score >= 40) { label = 'Fair';      color = '#FFCB47'; msg = '⚠️ Fair health. Focus on increasing your savings rate.'; }
    else                  { label = 'Needs Work';color = '#EF4444'; msg = '🔴 Needs attention. Consider reducing expenses or increasing income.'; }

    if (badge)  { badge.textContent = `${score} — ${label}`; badge.style.background = color + '22'; badge.style.color = color; }
    if (pct)    pct.textContent = score + '%';
    if (status) status.textContent = msg;
    if (fill)   fill.style.background = `linear-gradient(90deg, ${color}, ${color}cc)`;
}

// ─── Savings goals ────────────────────────────────────────────────────────────

function populateGoals(goals) {
    const container = document.getElementById('dashboardGoalsList');
    if (!container) return;

    if (!goals || goals.length === 0) {
        container.innerHTML = '<p class="dg-empty">No goals yet — <a class="link-btn" href="/savings">add one in Savings</a></p>';
        return;
    }

    container.innerHTML = goals.slice(0, 4).map(g => {
        const pct = g.target > 0 ? Math.min(100, (g.saved / g.target * 100)) : 0;
        return `
        <div class="dg-goal-item">
            <div class="dg-goal-top">
                <span class="dg-goal-name">${g.name}</span>
                <span class="dg-goal-pct">${pct.toFixed(0)}%</span>
            </div>
            <div class="dg-progress-bar">
                <div class="dg-progress-fill" style="width:${pct}%"></div>
            </div>
            <div class="dg-goal-amounts">
                <span>${fmt(g.saved)} saved</span>
                <span>${fmt(g.target)} target</span>
            </div>
        </div>`;
    }).join('');
}

// ─── Upcoming bills ───────────────────────────────────────────────────────────

function populateBills(bills) {
    const container = document.getElementById('upcomingBillsList');
    if (!container) return;

    if (!bills || bills.length === 0) {
        container.innerHTML = '<p class="bills-empty">No recurring bills set up yet</p>';
        return;
    }

    container.innerHTML = bills.map(b => `
        <div class="bill-item${b.paid ? ' bill-paid' : ''}">
            <div class="bill-left">
                <span class="bill-name">${b.name}</span>
                <span class="bill-category badge">${b.category}</span>
            </div>
            <div class="bill-right">
                <span class="bill-amount">${fmt(b.amount)}</span>
                ${b.paid
                    ? '<span class="bill-status status-paid">✅ Paid</span>'
                    : `<button class="bill-pay-btn" onclick="markBillPaid(${b.id}, '${b.name}')">Mark Paid</button>`
                }
            </div>
        </div>
    `).join('');
}

// ─── Charts ───────────────────────────────────────────────────────────────────

let incomeChart   = null;
let breakdownChart = null;

function buildCharts(data) {
    // ── Income vs Expenses bar chart ──────────────────────────────
    const incomeMap  = {};
    const expenseMap = {};
    data.income_by_month.forEach(r  => incomeMap[r.month]  = r.total);
    data.expense_by_month.forEach(r => expenseMap[r.month] = r.total);

    const allLabels = [...new Set([
        ...data.income_by_month.map(r  => r.month),
        ...data.expense_by_month.map(r => r.month),
    ])].sort();

    const incomeCtx = document.getElementById('incomeVsExpenseChart');
    if (incomeCtx) {
        if (incomeChart) incomeChart.destroy();
        incomeChart = new Chart(incomeCtx, {
            type: 'bar',
            data: {
                labels: allLabels,
                datasets: [
                    {
                        label: 'Income (£)',
                        data: allLabels.map(l => incomeMap[l]  || 0),
                        backgroundColor: 'rgba(67,97,238,0.75)',
                        borderRadius: 6,
                    },
                    {
                        label: 'Expenses (£)',
                        data: allLabels.map(l => expenseMap[l] || 0),
                        backgroundColor: 'rgba(239,68,68,0.75)',
                        borderRadius: 6,
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                plugins: { legend: { position: 'bottom' } },
                scales: { y: { beginAtZero: true } }
            }
        });
    }

    // ── Expense breakdown doughnut ────────────────────────────────
    const bd = data.expense_breakdown || {};
    const bdKeys   = Object.keys(bd).filter(k => (bd[k] || 0) > 0);
    const bdValues = bdKeys.map(k => bd[k]);
    const bdLabels = bdKeys.map(k => k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()));

    const breakdownCtx = document.getElementById('expenseBreakdownChart');
    if (breakdownCtx) {
        if (breakdownChart) breakdownChart.destroy();
        if (bdValues.length > 0) {
            breakdownChart = new Chart(breakdownCtx, {
                type: 'doughnut',
                data: {
                    labels: bdLabels,
                    datasets: [{
                        data: bdValues,
                        backgroundColor: [
                            '#4361EE','#EF4444','#06C270','#FFCB47',
                            '#7C3AED','#06B6D4','#F97316','#EC4899','#14B8A6'
                        ],
                        borderWidth: 2,
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { position: 'bottom' } }
                }
            });
        } else {
            breakdownCtx.parentElement.innerHTML =
                '<p style="text-align:center;color:var(--text-light);padding:40px 0">No expense data yet</p>';
        }
    }
}

// ─── Budget status ────────────────────────────────────────────────────────────

function populateBudgetStatus(data) {
    const section   = document.getElementById('dashboardBudgetSection');
    const listEl    = document.getElementById('dashboardBudgetList');
    const forecastEl = document.getElementById('dashForecastRow');
    if (!section || !listEl) return;

    const cats = (data.budget_comparison || []).filter(c => c.limit > 0);
    if (cats.length === 0) {
        section.style.display = 'none';
        return;
    }
    section.style.display = '';

    // Show top 4 by % used (descending)
    const top4 = cats
        .filter(c => c.pct !== null)
        .sort((a, b) =>  b.pct - a.pct)
        .slice(0, 4);

    const dot = status => {
        if (status === 'over')    return '<span class="traffic-light tl-red">●</span>';
        if (status === 'warning') return '<span class="traffic-light tl-yellow">●</span>';
        return '<span class="traffic-light tl-green">●</span>';
    };

    listEl.innerHTML = top4.map(c => `
        <div class="dash-budget-row">
            <div class="dash-budget-row-top">
                <span class="dash-budget-label">${c.label}</span>
                ${dot(c.status)}
                <span class="dash-budget-pct ${c.status === 'over' ? 'pct-over' : ''}">${c.pct}%</span>
            </div>
            <div class="budget-bar-track">
                <div class="budget-bar-fill status-${c.status}" style="width:${Math.min(c.pct, 100)}%"></div>
            </div>
        </div>
    `).join('');

    // Cash flow forecast pill
    const cf = data.cash_flow_forecast;
    if (cf && forecastEl) {
        const sign  = cf.balance >= 0 ? '+' : '';
        const cls   = cf.balance >= 0 ? 'pos' : 'neg';
        forecastEl.innerHTML = `
            <span class="forecast-pill">
                📅 Month forecast: <strong class="${cls}">${sign}${fmt(cf.balance)}</strong>
                <span class="forecast-pill-detail">(Income ${fmt(cf.income)} − Bills ${fmt(cf.recurring)} − Spent ${fmt(cf.spent)})</span>
            </span>`;
    }
}

// ─── Bill Alerts ──────────────────────────────────────────────────────────────

function populateBillAlerts(bills) {
    const banner = document.getElementById('billAlertBanner');
    const textEl = document.getElementById('billAlertText');
    if (!banner || !textEl) return;

    if (!bills || bills.length === 0) { banner.style.display = 'none'; return; }

    const today = new Date().getDate();
    const urgent = bills.filter(b => {
        const diff = b.due_day - today;
        return diff >= 0 && diff <= 3;
    });

    if (urgent.length === 0) { banner.style.display = 'none'; return; }

    const total = urgent.reduce((s, b) => s + (b.amount || 0), 0);
    const names = urgent.map(b => b.name).join(', ');
    textEl.textContent = `${urgent.length} bill${urgent.length > 1 ? 's' : ''} due within 3 days: ${names} (${fmt(total)})`;
    banner.style.display = 'flex';
}

// ─── Net Worth Trend ──────────────────────────────────────────────────────────

let netWorthChart = null;

function buildNetWorthChart(history) {
    const section = document.getElementById('netWorthChartSection');
    const ctx = document.getElementById('netWorthTrendChart');
    if (!ctx || !history || history.length < 2) { if (section) section.style.display = 'none'; return; }

    if (section) section.style.display = '';
    const labels = history.map(h => h.month);
    const values = history.map(h => h.net_worth);

    if (netWorthChart) netWorthChart.destroy();
    netWorthChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Net Worth',
                data: values,
                borderColor: '#4361EE',
                backgroundColor: 'rgba(67,97,238,0.1)',
                fill: true,
                tension: 0.3,
                pointRadius: 4,
                pointBackgroundColor: '#4361EE',
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: { y: { beginAtZero: false } }
        }
    });
}

// ─── Main ─────────────────────────────────────────────────────────────────────

async function loadDashboard() {
    try {
        const res  = await fetch('/api/dashboard-data');
        const data = await res.json();

        setGreeting(data.username);
        populateCards(data);
        populateHealth(data.health_score || 0);
        populateBudgetStatus(data);
        populateGoals(data.savings_goals || []);
        populateBills(data.upcoming_bills || []);
        populateBillAlerts(data.bill_alerts || data.upcoming_bills || []);
        buildCharts(data);
        buildNetWorthChart(data.net_worth_history || []);
    } catch (err) {
        console.error('Dashboard data fetch failed:', err);
    }
}

// ─── Mark bill paid from dashboard ────────────────────────────────────────────

async function markBillPaid(billId, billName) {
    if (!confirm(`Mark "${billName}" as paid for this month?`)) return;
    try {
        await fetch(`/recurring/mark-paid/${billId}`);
        loadDashboard();   // refresh all dashboard data
    } catch (err) {
        console.error('Failed to mark bill paid:', err);
    }
}

document.addEventListener('DOMContentLoaded', loadDashboard);
