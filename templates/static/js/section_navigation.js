(() => {
    const current = document.currentScript.dataset.section;
    const sections = JSON.parse(document.getElementById('display-sections').textContent);
    let navigating = false;
    function go(direction) {
        if (navigating || !sections.length) return;
        const index = sections.findIndex((section) => section.key === current);
        const target = index < 0 ? 0 : (index + direction + sections.length) % sections.length;
        navigating = true;
        window.location.assign(sections[target].url);
    }
    window.SlideSections = { next: () => go(1), previous: () => go(-1) };
    function onKey(event) {
        if (sections.length < 2 || event.defaultPrevented || event.repeat || event.altKey || event.ctrlKey || event.metaKey) return;
        if (event.target?.closest?.('input, textarea, select, [contenteditable="true"]')) return;
        if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
        event.preventDefault();
        event.stopImmediatePropagation();
        go(event.key === 'ArrowRight' ? 1 : -1);
    }
    window.addEventListener('keydown', onKey, true);
    window.addEventListener('pagehide', () => window.removeEventListener('keydown', onKey, true), { once: true });
})();
