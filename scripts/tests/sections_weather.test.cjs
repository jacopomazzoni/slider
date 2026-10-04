const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '../..');

function weather() {
    const nodes = new Map();
    const element = () => ({ innerHTML: '', children: [], style: {}, appendChild(node) { this.children.push(node); } });
    const context = vm.createContext({
        window: { addEventListener() {} }, console,
        document: { getElementById(id) { if (!nodes.has(id)) nodes.set(id, element()); return nodes.get(id); }, createElement: element },
    });
    const source = readFileSync(path.join(root, 'templates/static/app.js'), 'utf8');
    vm.runInContext(source.slice(0, source.lastIndexOf('\ninitMap();')), context);
    return { context, nodes, run: (js) => vm.runInContext(js, context) };
}

test('missing numeric weather values are hidden, real zeros are retained', () => {
    const { run } = weather();
    for (const value of ['null', 'undefined', 'NaN', 'Infinity', 'true', 'false', '" "', '"N/A"', '"NaN"']) {
        assert.equal(run(`safeNumber(${value})`), null);
        assert.equal(run(`weatherMetric('wi-test', safeNumber(${value}), '%')`), '');
    }
    for (const value of ['null', 'undefined', 'NaN', 'Infinity', '"N/A"', '"NA"', '"NaN"', '" "']) {
        assert.equal(run(`weatherMetric('wi-test', ${value}, '%')`), '');
    }
    assert.match(run("weatherMetric('wi-test', 0, '%', 0)"), /0 %/);
});

test('current conditions and forecast never turn absent precipitation into zero', () => {
    const { run, nodes } = weather();
    run('renderMain({properties:{periods:[{temperature:null, windSpeed:"N/A", probabilityOfPrecipitation:{value:null}}]}}, {features:[]})');
    assert.equal(nodes.get('col-right').innerHTML, '');
    run('renderForecast({properties:{periods:[{}, {name:"Tomorrow",temperature:null,probabilityOfPrecipitation:{value:null}}]}})');
    assert.doesNotMatch(nodes.get('forecast-row').children[0].innerHTML, /N\/A|NaN|null|0 %/);
    run('renderExtraMetrics({RH:0, Pressure:"N/A", Sky:0, Wgust:null})');
    assert.match(nodes.get('col-center').innerHTML, /Humidity: 0 %/);
    assert.doesNotMatch(nodes.get('col-center').innerHTML, /Pressure|Wind Gust|N\/A|NaN/);
});

function navigation(section, sections = ['media', 'weather', 'transit']) {
    const listeners = {};
    const destinations = [];
    const context = {
        document: { currentScript: {dataset: {section}}, getElementById: () => ({textContent: JSON.stringify(sections.map(key => ({key, url: `/${key}/`})) )}) },
        window: { location: { assign: url => destinations.push(url) },
            addEventListener: (type, callback) => { listeners[type] = callback; },
            removeEventListener: type => { delete listeners[type]; } },
    };
    vm.runInNewContext(readFileSync(path.join(root, 'templates/static/js/section_navigation.js'), 'utf8'), context);
    const key = (name, extra = {}) => listeners.keydown({ key: name, preventDefault() {}, stopImmediatePropagation() {}, ...extra });
    return {key, listeners, destinations, context};
}

test('weather resize work is coalesced and released when leaving the slide', () => {
    const {context, run} = weather();
    let pending;
    let frames = 0;
    let fits = 0;
    let disconnected = false;
    let cancelled = false;
    context.requestAnimationFrame = callback => { pending = callback; frames += 1; return 42; };
    context.cancelAnimationFrame = id => { cancelled = id === 42; };
    context.fit = () => { fits += 1; };
    context.disconnect = () => { disconnected = true; };
    run('fitSidebarToMap = fit; map = {invalidateSize() {}, remove() {}}; mapResizeObserver = {disconnect};');
    run('scheduleSidebarFit(); scheduleSidebarFit();');
    assert.equal(frames, 1);
    pending(); assert.equal(fits, 1);
    run('scheduleSidebarFit(); disposeWeatherDashboard(); scheduleSidebarFit();');
    assert.equal(frames, 2);
    assert.ok(disconnected && cancelled);
    pending(); assert.equal(fits, 1);
});

test('arrows move between sections and wrap in both directions', () => {
    const first = navigation('media'); first.key('ArrowLeft'); assert.deepEqual(first.destinations, ['/transit/']);
    const last = navigation('transit'); last.key('ArrowRight'); assert.deepEqual(last.destinations, ['/media/']);
    const middle = navigation('weather'); middle.key('ArrowRight'); assert.deepEqual(middle.destinations, ['/transit/']);
    middle.key('ArrowLeft'); assert.equal(middle.destinations.length, 1);
    middle.listeners.pagehide(); assert.equal(middle.listeners.keydown, undefined);
});

test('typing, repeats and one-section displays retain normal key behavior', () => {
    const nav = navigation('media');
    nav.key('ArrowLeft', {repeat:true}); nav.key('ArrowRight', {target:{closest: () => ({})}});
    nav.key('ArrowLeft', {ctrlKey:true}); assert.deepEqual(nav.destinations, []);
    const single = navigation('media', ['media']); single.key('ArrowRight'); assert.deepEqual(single.destinations, []);
});
