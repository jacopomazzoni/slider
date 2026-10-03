const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');

const source = readFileSync(path.join(__dirname, '../../templates/static/js/responsive_qr.js'), 'utf8');

test('QR selects sufficient rasters and whole device-pixel modules across screen densities', () => {
    for (const slotSize of [48, 84, 128, 192, 256]) {
        for (const density of [1, 1.25, 1.5, 2, 3, 4, 6, 8, 10]) {
            const widths = [82, 123, 164, 205, 287, 369, 533, 697];
            const sources = widths.map(width => ({ width, url: `qr.png?size=${width}` }));
            const listeners = {};
            let disconnected = false;
            const image = {
                dataset: { qrModules: '41' }, style: {}, isConnected: true,
                parentElement: { getBoundingClientRect: () => ({ width: slotSize, height: slotSize }) },
                getBoundingClientRect: () => ({ left: 111.3, top: 5.5 }),
                getAttribute: () => '',
            };
            vm.runInNewContext(source, {
                document: {
                    querySelectorAll: () => [image],
                    getElementById: () => ({ textContent: JSON.stringify(sources) }),
                },
                window: {
                    devicePixelRatio: density,
                    matchMedia: () => ({ addEventListener() {}, removeEventListener() {} }),
                    addEventListener: (name, callback) => { listeners[name] = callback; },
                },
                ResizeObserver: class { observe() {} disconnect() { disconnected = true; } },
            });
            const rendered = parseFloat(image.style.width) * density;
            const chosen = sources.find(item => item.url === image.src).width;
            assert.ok(Math.abs(rendered / 41 - Math.round(rendered / 41)) < 1e-9);
            assert.ok(chosen >= rendered);
            assert.ok(rendered <= slotSize * density);
            assert.equal(chosen, widths.find(width => width >= rendered));
            listeners.pagehide();
            assert.ok(disconnected);
        }
    }
});

test('mobile never schedules a map animation even if desktop animation is enabled', () => {
    const template = readFileSync(path.join(__dirname, '../../templates/transit_dashboard.html'), 'utf8');
    const body = template.match(/function transitionToFinalView\(\) \{([\s\S]*?)\n            function decodeLine/)[0].replace(/\n            function decodeLine$/, '');
    vm.runInNewContext(`${body}; transitionToFinalView();`, {
        mobileMode: true,
        app: { dataset: { animationEnabled: 'true' } },
        window: { setTimeout() { throw new Error('Mobile animation scheduled'); } },
        map: { flyTo() { throw new Error('Mobile map moved'); } },
    });
});

test('QR refresh releases deleted editor nodes and supports reinsertion', () => {
    const observed = new Set();
    const slot = {getBoundingClientRect: () => ({width: 192, height: 192})};
    const image = {
        isConnected: true, parentElement: slot, style: {},
        dataset: {qrModules: '41', qrSources: JSON.stringify([{width: 205, url: 'qr.png'}])},
        getBoundingClientRect: () => ({left: 0, top: 0}), getAttribute: () => '',
    };
    const window = {devicePixelRatio: 1, addEventListener() {},
        matchMedia: () => ({addEventListener() {}, removeEventListener() {}})};
    vm.runInNewContext(source, {window,
        document: {querySelectorAll: () => image.isConnected ? [image] : []},
        ResizeObserver: class {
            observe(node) { observed.add(node); }
            unobserve(node) { observed.delete(node); }
            disconnect() { observed.clear(); }
        },
    });
    for (let index = 0; index < 30; index++) {
        assert.equal(observed.size, 1);
        image.isConnected = false;
        image.parentElement = null;
        window.SliderCMSQR.refresh();
        assert.equal(observed.size, 0);
        image.isConnected = true;
        image.parentElement = slot;
        window.SliderCMSQR.refresh();
    }
});
