(() => {
    const root = document.getElementById('library-sections');
    if (!root) return;
    const status = document.getElementById('library-order-status');
    const storageKey = 'slidercms-library-collapsed';
    let collapsed = [];
    try { const saved = JSON.parse(localStorage.getItem(storageKey)); if (Array.isArray(saved)) collapsed = saved; } catch (_) {}
    let savedOrder = JSON.parse(document.getElementById('library-section-order').textContent);
    let busy = false;
    let dragged = null;
    let dropped = false;
    const sections = new Map();
    const icons = {
        up: '<path d="m6 14 6-6 6 6"/>',
        down: '<path d="m6 10 6 6 6-6"/>',
        drag: '<path d="M8 5h1m6 0h1M8 12h1m6 0h1M8 19h1m6 0h1"/>',
    };
    function order() { return Array.from(root.children).map((section) => section.dataset.section); }
    function arrange(keys) { keys.forEach((key) => root.append(sections.get(key))); updateButtons(); }
    function updateButtons() {
        const keys = order();
        keys.forEach((key, index) => {
            const section = sections.get(key);
            section.querySelector('[data-move="up"]').disabled = busy || index === 0;
            section.querySelector('[data-move="down"]').disabled = busy || index === keys.length - 1;
            section.querySelector('.section-drag').draggable = !busy;
        });
    }
    async function saveOrder() {
        busy = true;
        updateButtons();
        status.textContent = 'Saving order...';
        try {
            const response = await fetch(root.dataset.reorderUrl, {
                method: 'POST', credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value },
                body: JSON.stringify({ section_order: order() }),
            });
            if (!response.ok) throw new Error('Unable to save section order.');
            savedOrder = (await response.json()).section_order;
            status.textContent = 'Section order saved.';
        } catch (_) {
            arrange(savedOrder);
            status.textContent = 'Could not save. Previous order restored. Please retry.';
        } finally { busy = false; updateButtons(); }
    }
    Array.from(root.children).forEach((panel) => {
        const key = panel.dataset.section;
        const heading = panel.querySelector('h2');
        const title = heading.textContent;
        const details = document.createElement('details');
        details.className = 'library-section';
        details.dataset.section = key;
        details.open = !collapsed.includes(key);
        const summary = document.createElement('summary');
        summary.append(heading);
        const controls = document.createElement('span');
        controls.className = 'section-controls';
        ['up', 'down', 'drag'].forEach((action) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.title = action === 'drag' ? `Drag ${title}` : `Move ${title} ${action}`;
            button.setAttribute('aria-label', button.title);
            button.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">${icons[action]}</svg>`;
            if (action === 'drag') { button.className = 'section-drag'; button.draggable = true; }
            else button.dataset.move = action;
            button.addEventListener('click', (event) => {
                event.preventDefault(); event.stopPropagation();
                if (busy || dragged || action === 'drag') return;
                const keys = order();
                const index = keys.indexOf(key);
                const destination = index + (action === 'up' ? -1 : 1);
                if (destination < 0 || destination >= keys.length) return;
                [keys[index], keys[destination]] = [keys[destination], keys[index]];
                arrange(keys); button.focus(); saveOrder();
            });
            controls.append(button);
        });
        summary.append(controls);
        const body = document.createElement('div');
        body.className = 'library-section-body';
        panel.querySelector('.generated-slide-kicker')?.remove();
        body.append(...panel.childNodes);
        details.append(summary, body);
        panel.replaceWith(details);
        sections.set(key, details);
        details.addEventListener('toggle', () => {
            try { localStorage.setItem(storageKey, JSON.stringify(Array.from(sections).filter(([, node]) => !node.open).map(([id]) => id))); } catch (_) {}
        });
    });
    arrange(savedOrder);
    root.addEventListener('dragstart', (event) => {
        if (!event.target.closest('.section-drag') || busy) return;
        dragged = event.target.closest('.library-section');
        dropped = false;
        event.dataTransfer.effectAllowed = 'move';
        event.dataTransfer.setData('text/plain', dragged.dataset.section);
        dragged.classList.add('is-dragging');
    });
    root.addEventListener('dragover', (event) => {
        if (!dragged) return;
        event.preventDefault();
        const target = event.target.closest('.library-section');
        if (!target || target === dragged) return;
        const bounds = target.getBoundingClientRect();
        root.insertBefore(dragged, event.clientY < bounds.top + bounds.height / 2 ? target : target.nextSibling);
    });
    root.addEventListener('drop', (event) => {
        if (!dragged) return;
        event.preventDefault(); dropped = true; saveOrder();
    });
    root.addEventListener('dragend', () => {
        if (!dragged) return;
        dragged.classList.remove('is-dragging'); dragged = null;
        if (!dropped) arrange(savedOrder);
    });
    document.getElementById('library-expand-all').addEventListener('click', () => sections.forEach((node) => { node.open = true; }));
    document.getElementById('library-collapse-all').addEventListener('click', () => sections.forEach((node) => { node.open = false; }));
})();
