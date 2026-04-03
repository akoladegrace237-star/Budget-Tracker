/**
 * main.js — Mobile-first utilities for Budget Tracker
 */

// ─── Active sheet tracker ─────────────────────────────────────────
let _activeSheet = null;

// ─── Bottom Sheet ─────────────────────────────────────────────────

function openSheet(sheetId) {
    // Close any open sheet first
    if (_activeSheet) closeSheet(_activeSheet);

    const sheet   = document.getElementById(sheetId);
    const overlay = document.getElementById('sheetOverlay');
    if (!sheet || !overlay) return;

    overlay.style.display = 'block';
    // Trigger transition on next frame
    requestAnimationFrame(() => {
        overlay.classList.add('open');
        sheet.classList.add('open');
    });
    _activeSheet = sheetId;
    document.body.style.overflow = 'hidden';
}

function closeSheet(sheetId) {
    const id      = sheetId || _activeSheet;
    const sheet   = document.getElementById(id);
    const overlay = document.getElementById('sheetOverlay');
    if (!sheet) return;

    sheet.classList.remove('open');
    if (overlay) {
        overlay.classList.remove('open');
        setTimeout(() => { overlay.style.display = 'none'; }, 260);
    }
    _activeSheet = null;
    document.body.style.overflow = '';
}

function closeActiveSheet() { closeSheet(_activeSheet); }

// ─── More Menu ────────────────────────────────────────────────────

function openMoreMenu() {
    const overlay = document.getElementById('moreOverlay');
    const sheet   = document.getElementById('moreSheet');
    if (!overlay || !sheet) return;
    overlay.style.display = 'block';
    requestAnimationFrame(() => {
        overlay.classList.add('open');
        sheet.classList.add('open');
    });
    document.body.style.overflow = 'hidden';
}

function closeMoreMenu() {
    const overlay = document.getElementById('moreOverlay');
    const sheet   = document.getElementById('moreSheet');
    if (!overlay || !sheet) return;
    overlay.classList.remove('open');
    sheet.classList.remove('open');
    setTimeout(() => { overlay.style.display = 'none'; }, 300);
    document.body.style.overflow = '';
}

// ─── Record card expand / collapse ───────────────────────────────

function toggleRecord(el) {
    const card = el.closest('.record-card');
    if (!card) return;
    card.classList.toggle('expanded');
}

// ─── Desktop inline form toggle (backwards compat) ───────────────

function toggleForm(formId) {
    const el = document.getElementById(formId);
    if (!el) return;
    el.classList.toggle('open');
    // Also handle legacy style display
    if (!el.classList.contains('open')) {
        el.style.display = 'none';
    } else {
        el.style.display = 'block';
    }
}

// ─── Default month inputs ─────────────────────────────────────────

function setDefaultMonths() {
    const today = new Date();
    const val   = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}`;
    document.querySelectorAll('input[type="month"]').forEach(inp => {
        if (!inp.value) inp.value = val;
    });
}

// ─── Confirm delete helper ────────────────────────────────────────

function confirmDelete(msg) {
    return confirm(msg || 'Delete this record? This cannot be undone.');
}

// ─── DOMContentLoaded ────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    setDefaultMonths();

    // Auto-dismiss flash alerts
    document.querySelectorAll('.alert').forEach(alert => {
        setTimeout(() => {
            alert.style.transition = 'opacity 0.4s';
            alert.style.opacity = '0';
            setTimeout(() => alert.remove(), 400);
        }, 4000);
    });

    // Swipe down on bottom sheet to close
    let touchStartY = 0;
    document.addEventListener('touchstart', e => {
        touchStartY = e.touches[0].clientY;
    }, { passive: true });
    document.addEventListener('touchend', e => {
        if (!_activeSheet) return;
        const delta = e.changedTouches[0].clientY - touchStartY;
        if (delta > 80) closeActiveSheet(); // swipe down 80px
    }, { passive: true });
});

