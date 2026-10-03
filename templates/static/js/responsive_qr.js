(() => {
    "use strict";
    const images = new Map();
    const slots = new WeakMap();
    let densityQuery;

    function renderImage(image, sources) {
        if (!image.isConnected || !image.parentElement) return;
        const modules = Number(image.dataset.qrModules);
        const density = window.devicePixelRatio || 1;
        const slot = image.parentElement.getBoundingClientRect();
        if (!slot.width || !slot.height) return;
        // Snap both the module size and the image origin to physical pixels.
        const pixels = Math.max(modules, Math.floor(Math.min(slot.width, slot.height) * density / modules) * modules);
        const source = sources.find((item) => item.width >= pixels) || sources[sources.length - 1];
        const size = Math.min(pixels, source.width);
        image.style.width = `${size / density}px`;
        image.style.height = `${size / density}px`;
        image.style.transform = "none";
        const rect = image.getBoundingClientRect();
        image.style.transform = `translate(${(Math.round(rect.left * density) / density) - rect.left}px, ${(Math.round(rect.top * density) / density) - rect.top}px)`;
        if (image.getAttribute("src") !== source.url) image.src = source.url;
    }
    function render() {
        images.forEach((sources, image) => renderImage(image, sources));
    }
    const observer = new ResizeObserver(render);
    function refresh() {
        images.forEach((_, image) => {
            if (!image.isConnected) {
                observer.unobserve(slots.get(image));
                images.delete(image);
            }
        });
        document.querySelectorAll('[data-qr-modules]').forEach(image => {
            if (images.has(image)) return;
            const manifest = image.dataset.qrSources || document.getElementById('transit-qr-sources')?.textContent;
            if (!manifest) return;
            const sources = JSON.parse(manifest).sort((a, b) => a.width - b.width);
            if (!sources.length) return;
            images.set(image, sources);
            slots.set(image, image.parentElement);
            observer.observe(image.parentElement);
        });
        render();
    }
    window.SliderCMSQR = { refresh };
    function watchDensity() {
        densityQuery?.removeEventListener("change", watchDensity);
        densityQuery = window.matchMedia(`(resolution: ${window.devicePixelRatio || 1}dppx)`);
        densityQuery.addEventListener("change", watchDensity);
        render();
    }
    function start() {
        refresh();
        watchDensity();
    }
    window.addEventListener("pagehide", () => {
        observer.disconnect();
        images.clear();
        densityQuery?.removeEventListener("change", watchDensity);
    });
    window.addEventListener("pageshow", start);
    start();
})();
