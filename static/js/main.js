/**
 * main.js — Mobile-first utilities for Budget Tracker
 */

// ─── Active sheet tracker ─────────────────────────────────────────
let _activeSheet = null;
let _returnFocus = null;
let _overlayTimer = null;

function activateDialog(dialog) {
    _returnFocus = document.activeElement;
    dialog.inert = false;
    dialog.setAttribute('aria-hidden', 'false');
    // Sheets live inside the main content: make their siblings inert, not their parent.
    document.querySelectorAll('#pageContent > *, .header, #navTabs, #bottomNav').forEach(el => {
        if (el !== dialog && !el.contains(dialog)) el.inert = true;
    });
    requestAnimationFrame(() => {
        if (dialog.getAttribute('aria-hidden') === 'true') return;
        const focusable = dialog.querySelector('input:not([type=hidden]),select,button,a[href]');
        if (focusable) focusable.focus(); else dialog.focus();
    });
}
function deactivateDialog(dialog) {
    dialog.inert = true;
    dialog.setAttribute('aria-hidden', 'true');
    document.querySelectorAll('#pageContent > *, .header, #navTabs, #bottomNav').forEach(el => {
        el.inert = el.matches('.bottom-sheet,.more-sheet') && !el.classList.contains('open');
    });
    if (_returnFocus && _returnFocus.isConnected) _returnFocus.focus();
    _returnFocus = null;
}

// ─── Bottom Sheet ─────────────────────────────────────────────────

function openSheet(sheetId) {
    // Close any open sheet first
    if (_activeSheet) closeSheet(_activeSheet);

    const sheet   = document.getElementById(sheetId);
    const overlay = document.getElementById('sheetOverlay');
    if (!sheet || !overlay) return;
    clearTimeout(_overlayTimer);
    activateDialog(sheet);

    overlay.style.display = 'block';
    // Trigger transition on next frame
    requestAnimationFrame(() => {
        if (_activeSheet !== sheetId || sheet.getAttribute('aria-hidden') === 'true') return;
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
        _overlayTimer = setTimeout(() => { overlay.style.display = 'none'; }, 260);
    }
    _activeSheet = null;
    document.body.style.overflow = '';
    deactivateDialog(sheet);
}

function closeActiveSheet() { closeSheet(_activeSheet); }

// ─── More Menu ────────────────────────────────────────────────────

function openMoreMenu() {
    const overlay = document.getElementById('moreOverlay');
    const sheet   = document.getElementById('moreSheet');
    if (!overlay || !sheet) return;
    activateDialog(sheet);
    document.querySelector('#bottomNav button').setAttribute('aria-expanded','true');
    overlay.style.display = 'block';
    requestAnimationFrame(() => {
        if (sheet.getAttribute('aria-hidden') === 'true') return;
        overlay.classList.add('open');
        sheet.classList.add('open');
    });
    document.body.style.overflow = 'hidden';
}

function closeMoreMenu() {
    const overlay = document.getElementById('moreOverlay');
    const sheet   = document.getElementById('moreSheet');
    if (!overlay || !sheet) return;
    document.querySelector('#bottomNav button').setAttribute('aria-expanded','false');
    overlay.classList.remove('open');
    sheet.classList.remove('open');
    setTimeout(() => { overlay.style.display = 'none'; }, 300);
    document.body.style.overflow = '';
    if (sheet) deactivateDialog(sheet);
}

// ─── Record card expand / collapse ───────────────────────────────

function toggleRecord(el) {
    const card = el.closest('.record-card');
    if (!card) return;
    card.classList.toggle('expanded');
    el.setAttribute('aria-expanded', String(card.classList.contains('expanded')));
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

    document.querySelectorAll('.bottom-sheet,.more-sheet').forEach((sheet,index) => {
        sheet.setAttribute('role','dialog'); sheet.setAttribute('aria-modal','true');
        sheet.setAttribute('aria-hidden','true'); sheet.tabIndex=-1; sheet.inert=true;
        const heading=sheet.querySelector('h3,.more-sheet-title');
        if (heading) { heading.id=heading.id || `dialogTitle${index}`; sheet.setAttribute('aria-labelledby',heading.id); }
    });
    document.querySelectorAll('label').forEach((label,index) => {
        if (label.htmlFor || label.querySelector('input,select,textarea')) return;
        const field=label.parentElement.querySelector('input:not([type=hidden]),select,textarea');
        if (field) { field.id=field.id || `field${index}`; label.htmlFor=field.id; }
    });
    document.querySelectorAll('.record-card-main').forEach(el => {
        el.tabIndex=0; el.setAttribute('role','button'); el.setAttribute('aria-expanded','false');
        el.addEventListener('keydown',event => { if (event.key==='Enter' || event.key===' ') { event.preventDefault(); toggleRecord(el); } });
    });
    document.querySelectorAll('nav a.active').forEach(link => link.setAttribute('aria-current','page'));
    document.querySelectorAll('.sheet-close-btn').forEach(button => button.setAttribute('aria-label','Close dialog'));

    // Swipe down on bottom sheet to close
    let touchStartY = 0;
    document.addEventListener('touchstart', e => {
        touchStartY = e.target.closest('.sheet-drag-bar') ? e.touches[0].clientY : null;
    }, { passive: true });
    document.addEventListener('touchend', e => {
        if (!_activeSheet || touchStartY === null) return;
        const delta = e.changedTouches[0].clientY - touchStartY;
        if (delta > 80) closeActiveSheet(); // swipe down 80px
    }, { passive: true });
});

document.addEventListener('keydown', event => {
    const dialog=_activeSheet ? document.getElementById(_activeSheet) : document.querySelector('.more-sheet[aria-hidden="false"]');
    if (!dialog) return;
    if (event.key==='Escape') { event.preventDefault(); if (_activeSheet) closeActiveSheet(); else closeMoreMenu(); }
    if (event.key==='Tab') {
        const elements=Array.from(dialog.querySelectorAll('a[href],button,input:not([type=hidden]),select,textarea,[tabindex="0"]')).filter(el => !el.disabled && el.getClientRects().length);
        if (!elements.length) { event.preventDefault(); dialog.focus(); return; }
        const first=elements[0],last=elements[elements.length-1];
        if (event.shiftKey && document.activeElement===first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement===last) { event.preventDefault(); first.focus(); }
    }
});

