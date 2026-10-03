(() => {
    'use strict';
    const editor = document.getElementById('rich-editor');
    const dialog = document.getElementById('qr-dialog');
    const form = document.getElementById('qr-insert-form');
    const button = document.getElementById('qr-confirm');
    const error = document.getElementById('qr-error');
    let selectionRange = null;
    let request = null;

    document.getElementById('insert-qr').addEventListener('click', () => {
        const selection = window.getSelection();
        selectionRange = selection.rangeCount && editor.contains(selection.getRangeAt(0).commonAncestorContainer)
            ? selection.getRangeAt(0).cloneRange() : null;
        error.hidden = true;
        dialog.showModal();
        document.getElementById('qr-text').focus();
    });
    document.getElementById('qr-cancel').addEventListener('click', () => dialog.close());
    dialog.addEventListener('close', () => { request?.abort(); });
    editor.addEventListener('input', () => window.SliderCMSQR?.refresh());
    form.addEventListener('submit', async event => {
        event.preventDefault();
        if (request) return;
        const controller = new AbortController();
        request = controller;
        const timeout = window.setTimeout(() => controller.abort(), 15000);
        button.disabled = true;
        button.textContent = 'Generating...';
        error.hidden = true;
        try {
            const response = await fetch(form.dataset.url, {
                method: 'POST', signal: controller.signal,
                headers: { 'X-CSRFToken': document.querySelector('#rich-form [name=csrfmiddlewaretoken]').value },
                body: new URLSearchParams({text: document.getElementById('qr-text').value, size: document.getElementById('qr-size').value}),
            });
            if (response.redirected) throw new Error('Please sign in again to generate a QR code.');
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || 'QR code could not be generated.');
            dialog.close();
            editor.focus();
            const selection = window.getSelection();
            const range = selectionRange && editor.contains(selectionRange.commonAncestorContainer) ? selectionRange : document.createRange();
            if (range !== selectionRange) { range.selectNodeContents(editor); range.collapse(false); }
            selection.removeAllRanges();
            selection.addRange(range);
            // execCommand keeps insertion in the editor's native undo history.
            document.execCommand('insertHTML', false, result.html + '&nbsp;');
            editor.dispatchEvent(new Event('input', {bubbles: true}));
        } catch (failure) {
            if (dialog.open) {
                error.textContent = failure.name === 'AbortError' ? 'QR generation timed out. Please try again.' : failure.message;
                error.hidden = false;
            }
        } finally {
            window.clearTimeout(timeout);
            request = null;
            button.disabled = false;
            button.textContent = 'Insert QR';
        }
    });
    window.addEventListener('pagehide', () => { request?.abort(); selectionRange = null; });
})();
