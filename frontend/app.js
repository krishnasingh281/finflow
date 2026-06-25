// Change this to your deployed backend URL once you deploy to Google Cloud Run
// For local testing, keep it as localhost:8000
const API_BASE = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
    ? 'http://127.0.0.1:8000/api'
    : 'https://finflow-api.onrender.com/api';  // <-- update this after deployment


// =====================================================
//  UTILITY HELPERS
// =====================================================

function showResult(elementId, data, type = 'info') {
    const box = document.getElementById(elementId);
    box.className = 'result-box ' + type;
    box.textContent = JSON.stringify(data, null, 2);
    box.classList.remove('hidden');
}

function hideResult(elementId) {
    const box = document.getElementById(elementId);
    box.classList.add('hidden');
}

function generateUUID() {
    // simple UUID v4 generator — good enough for idempotency keys
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
        const r = Math.random() * 16 | 0;
        const v = c === 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}

function generateKey() {
    document.getElementById('tx-ikey').value = generateUUID();
}

function formatCurrency(value) {
    const num = parseFloat(value);
    if (isNaN(num)) return '—';
    return '₹' + num.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}


// =====================================================
//  POST /api/transaction
// =====================================================

async function submitTransaction() {
    const userId = document.getElementById('tx-userid').value.trim();
    const amount = document.getElementById('tx-amount').value.trim();
    const txType = document.getElementById('tx-type').value;
    const description = document.getElementById('tx-desc').value.trim();
    const idempotencyKey = document.getElementById('tx-ikey').value.trim();

    // basic client-side checks before we even hit the server
    if (!userId) {
        showResult('tx-result', { error: 'User ID is required.' }, 'error');
        return;
    }

    if (!amount || parseFloat(amount) <= 0) {
        showResult('tx-result', { error: 'Amount must be a positive number.' }, 'error');
        return;
    }

    const payload = {
        user_id: userId,
        amount: parseFloat(amount),
        transaction_type: txType,
        description: description,
    };

    if (idempotencyKey) {
        payload.idempotency_key = idempotencyKey;
    }

    showResult('tx-result', { status: 'Submitting...' }, 'info');

    try {
        const response = await fetch(API_BASE + '/transaction', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(payload),
        });

        const data = await response.json();

        if (response.ok) {
            showResult('tx-result', data, 'success');
            // auto-refresh the ranking and this user's summary after a transaction
            setTimeout(() => {
                fetchRanking();
                const summaryInput = document.getElementById('summary-userid');
                if (summaryInput.value === userId) {
                    fetchSummary();
                }
            }, 300);
        } else {
            showResult('tx-result', data, 'error');
        }

    } catch (err) {
        showResult('tx-result', { error: 'Network error. Is the backend running?', detail: err.message }, 'error');
    }
}


// =====================================================
//  GET /api/summary/:userId
// =====================================================

async function fetchSummary() {
    const userId = document.getElementById('summary-userid').value.trim();

    if (!userId) {
        showResult('summary-result', { error: 'Please enter a User ID.' }, 'error');
        document.getElementById('summary-stats').classList.add('hidden');
        return;
    }

    showResult('summary-result', { status: 'Loading...' }, 'info');

    try {
        const response = await fetch(API_BASE + '/summary/' + encodeURIComponent(userId));
        const data = await response.json();

        if (response.ok && data.success) {
            hideResult('summary-result');
            populateSummaryStats(data.summary);
        } else {
            showResult('summary-result', data, 'error');
            document.getElementById('summary-stats').classList.add('hidden');
        }

    } catch (err) {
        showResult('summary-result', { error: 'Network error.', detail: err.message }, 'error');
        document.getElementById('summary-stats').classList.add('hidden');
    }
}

function populateSummaryStats(summary) {
    document.getElementById('stat-credit').textContent = formatCurrency(summary.total_credit);
    document.getElementById('stat-debit').textContent = formatCurrency(summary.total_debit);
    document.getElementById('stat-net').textContent = formatCurrency(summary.net_balance);
    document.getElementById('stat-count').textContent = summary.transaction_count;
    document.getElementById('stat-reliability').textContent = (parseFloat(summary.reliability_score) * 100).toFixed(1) + '%';
    document.getElementById('stat-score').textContent = parseFloat(summary.composite_rank_score).toFixed(2);

    const statsGrid = document.getElementById('summary-stats');
    statsGrid.classList.remove('hidden');
}


// =====================================================
//  GET /api/ranking
// =====================================================

async function fetchRanking() {
    const limit = document.getElementById('ranking-limit').value;

    showResult('ranking-result', { status: 'Loading leaderboard...' }, 'info');
    document.getElementById('ranking-table-wrapper').classList.add('hidden');

    try {
        const response = await fetch(API_BASE + '/ranking?limit=' + limit);
        const data = await response.json();

        if (response.ok && data.success) {
            hideResult('ranking-result');
            populateRankingTable(data.ranking);
        } else {
            showResult('ranking-result', data, 'error');
        }

    } catch (err) {
        showResult('ranking-result', { error: 'Network error.', detail: err.message }, 'error');
    }
}

function populateRankingTable(rankingList) {
    const tbody = document.getElementById('ranking-tbody');
    tbody.innerHTML = '';

    if (!rankingList || rankingList.length === 0) {
        const row = document.createElement('tr');
        row.innerHTML = '<td colspan="6" style="text-align:center; color: var(--text-secondary); padding: 24px;">No users yet. Submit some transactions to see the leaderboard.</td>';
        tbody.appendChild(row);
        document.getElementById('ranking-table-wrapper').classList.remove('hidden');
        return;
    }

    rankingList.forEach(function(entry) {
        const row = document.createElement('tr');

        // rank badge styling
        let rankClass = 'rank-other';
        if (entry.rank === 1) rankClass = 'rank-1';
        else if (entry.rank === 2) rankClass = 'rank-2';
        else if (entry.rank === 3) rankClass = 'rank-3';

        // reliability fill bar width
        const reliabilityPct = (parseFloat(entry.reliability_score) * 100).toFixed(0);

        // color the reliability bar based on value
        let barColor = '#3fb950';
        if (parseFloat(entry.reliability_score) < 0.5) barColor = '#f85149';
        else if (parseFloat(entry.reliability_score) < 0.8) barColor = '#d29922';

        const netBalance = parseFloat(entry.net_balance) || 0;
        const netColor = netBalance >= 0 ? 'var(--accent-green)' : 'var(--accent-red)';

        row.innerHTML = `
            <td><span class="rank-badge ${rankClass}">${entry.rank}</span></td>
            <td><strong>${escapeHtml(entry.user_id)}</strong></td>
            <td><span class="score-chip">${parseFloat(entry.composite_rank_score).toFixed(2)}</span></td>
            <td style="color: ${netColor};">${formatCurrency(entry.net_balance)}</td>
            <td>${entry.transaction_count}</td>
            <td>
                <div class="reliability-bar">
                    <div class="bar-track">
                        <div class="bar-fill" style="width: ${reliabilityPct}%; background: ${barColor};"></div>
                    </div>
                    <span style="font-size: 11px; color: var(--text-secondary); min-width: 34px;">${reliabilityPct}%</span>
                </div>
            </td>
        `;

        tbody.appendChild(row);
    });

    document.getElementById('ranking-table-wrapper').classList.remove('hidden');
}

function escapeHtml(str) {
    // prevent XSS if someone puts HTML in their user_id
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}


// =====================================================
//  INIT — load the leaderboard on page load
// =====================================================

document.addEventListener('DOMContentLoaded', function () {
    fetchRanking();

    // allow pressing Enter in the summary input to trigger the fetch
    document.getElementById('summary-userid').addEventListener('keydown', function (e) {
        if (e.key === 'Enter') fetchSummary();
    });
});
