const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");

const template = readFileSync(path.join(__dirname, "../../templates/transit_dashboard.html"), "utf8");
const script = new vm.Script(template.match(/<script>\s*([\s\S]*?)<\/script>/)[1]);

class Element {
    constructor() {
        this.hidden = false;
        this.children = [];
        this.properties = new Map();
        this.style = { setProperty: (key, value) => this.properties.set(key, String(value)) };
        this.classList = { toggle() {} };
    }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = children; }
    removeAttribute() {}
    querySelector(selector) { return this.selectors?.[selector] || null; }
}

function point(x, y) {
    return {
        x, y,
        subtract(p) { return point(x - p.x, y - p.y); },
        add(p) { return point(x + p.x, y + p.y); },
        divideBy(n) { return point(x / n, y / n); },
    };
}

function latLng(lat, lng) {
    if (Array.isArray(lat)) [lat, lng] = lat;
    else if (typeof lat === "object") ({ lat, lng } = lat);
    return {
        lat, lng,
        equals(other) { return lat === other.lat && lng === other.lng; },
        distanceTo(other) { return Math.hypot(lat - other.lat, lng - other.lng) * 111320; },
    };
}

function eventSource(target) {
    const listeners = new Map();
    target.on = (events, callback) => {
        events.split(" ").forEach((event) => listeners.set(event, [...(listeners.get(event) || []), callback]));
        return target;
    };
    target.emit = (event) => (listeners.get(event) || []).forEach((callback) => callback());
    return target;
}

const bus = (overrides = {}) => ({ equipmentID: "101", routeID: 1, lat: 42.088, lng: -75.968, heading: 359, ...overrides });
const feed = (vehicles) => ({ vehicles, alerts: [{ text: "Detour" }], incoming: [], liveAvailable: true });

async function harness(initialFeed = feed([bus()]), routes = [{ id: 1, routeCode: "CS", color: "#008833", encLine: "_p~iF~ps|U_ulLnnqC_mqNvxq`@", stopIds: [] }]) {
    const elements = new Map();
    for (const id of ["app", "status", "alert-section", "arrival-section", "alert-rail", "alert-list", "arrival-list"]) {
        elements.set(id, new Element());
    }
    ["alert-section", "arrival-section", "alert-rail"].forEach((id) => { elements.get(id).hidden = true; });
    elements.get("app").dataset = {
        showIncoming: "true", showAlerts: "true", animationEnabled: "false", mapUrl: "map", liveUrl: "live",
    };
    const state = { now: 0, nextId: 0, frames: new Map(), intervals: new Map(), feed: initialFeed, markers: [], lines: [], signals: [] };
    const routeSvg = new Element();
    const map = eventSource({
        zoom: 15, layers: new Set(), invalidations: 0,
        setView(center, zoom) { this.center = latLng(center); this.zoom = zoom; return this; },
        getZoom() { return this.zoom; },
        getCenter() { return this.center; },
        getZoomScale(to, from) { return 2 ** (to - from); },
        getSize() { return point(1000, 600); },
        project(p) { return point(p.lng * 10000, -p.lat * 10000); },
        latLngToContainerPoint(p) {
            const exact = this.project(p).subtract(this.project(this.center)).add(this.getSize().divideBy(2));
            return point(Math.round(exact.x), Math.round(exact.y));
        },
        createPane() { const pane = new Element(); pane.selectors = { svg: routeSvg }; return pane; },
        invalidateSize() { this.invalidations++; },
        removeLayer(layer) { this.layers.delete(layer); },
        remove() { this.removed = true; },
    });
    const renderer = eventSource({ addTo() { return this; } });
    const group = (items = []) => ({
        layers: new Set(items),
        addTo(target) { target.layers.add(this); this.layers.forEach((line) => line.addTo?.(target)); return this; },
        eachLayer(callback) { this.layers.forEach(callback); },
        clearLayers() { this.layers.clear(); },
        removeLayer(layer) { this.layers.delete(layer); },
    });
    class Polyline {
        constructor(points, options) { this.points = points; this.options = options; state.lines.push(this); }
        static extend(methods) {
            class Extended extends this {}
            Object.assign(Extended.prototype, methods);
            return Extended;
        }
        addTo(target) { this._map = target; this._project(); this._updatePath(); return this; }
        getLatLngs() { return this.points.map(([lat, lng]) => ({ lat, lng })); }
        _project() { this._rings = [this.points.map(([lat, lng]) => point(lng * 10000, -lat * 10000))]; }
        _updatePath() { this.renderedParts = this._parts; }
    }
    const lifecycle = new Map();
    const L = {
        map: () => map, svg: () => renderer, layerGroup: group, latLng, point, Polyline,
        tileLayer: () => ({ addTo() { return this; } }),
        polyline: (_, options) => {
            const line = { options, setStyle(style) { Object.assign(this.options, style); } };
            state.lines.push(line);
            return line;
        },
        divIcon: (options) => options,
        marker: (position) => {
            const element = new Element(), icon = new Element(), label = new Element();
            element.selectors = { ".bus-icon": icon };
            icon.selectors = { ".bus-marker": label };
            const marker = {
                position, element, icon,
                addTo(target) { target.layers.add(this); return this; },
                getElement() { return element; },
                getLatLng() { return this.position; },
                setLatLng(value) { this.position = latLng(value); return this; },
                bindPopup(popup) { this.popup = popup; return this; },
                getPopup() { return this.popup; },
                setPopupContent(popup) { this.popup = popup; },
            };
            state.markers.push(marker);
            return marker;
        },
    };
    const context = vm.createContext({
        L, AbortController, performance: { now: () => state.now },
        document: {
            querySelector: (selector) => elements.get(selector === ".transit-app" ? "app" : "status"),
            getElementById: (id) => elements.get(id), createElement: () => new Element(),
        },
        requestAnimationFrame: (callback) => { const id = ++state.nextId; state.frames.set(id, callback); return id; },
        cancelAnimationFrame: (id) => state.frames.delete(id),
        window: {
            setInterval: (callback) => { const id = ++state.nextId; state.intervals.set(id, callback); return id; },
            clearInterval: (id) => state.intervals.delete(id), clearTimeout() {},
            addEventListener: (event, callback) => lifecycle.set(event, callback),
        },
        fetch: async (url, options) => {
            state.signals.push(options.signal);
            return { ok: true, json: async () => url === "map" ? {
                routes, stops: [],
            } : state.feed };
        },
    });
    script.runInContext(context);
    await new Promise(setImmediate);
    return {
        state, map, renderer, elements, routeSvg,
        async refresh(nextFeed, now = state.now + 15000) {
            state.now = now;
            state.feed = nextFeed;
            await [...state.intervals.values()][0]();
        },
        tick(now) {
            state.now = now;
            const callbacks = [...state.frames.values()];
            state.frames.clear();
            callbacks.forEach((callback) => callback(now));
        },
        close() { lifecycle.get("pagehide")(); },
    };
}

test("route strokes grow gently to 6px and stay the same through reprojection", async () => {
    const h = await harness();
    const route = h.state.lines[1];
    for (const zoom of [15, 14.5, 14, 13.5, 13]) {
        h.map.zoom = zoom;
        h.map.emit("zoom");
        const visibleWidth = route.options.weight * Number(h.routeSvg.properties.get("--route-line-scale")) * h.map.getZoomScale(zoom, 15);
        assert.ok(Math.abs(visibleWidth - 5 * (1 + (15 - zoom) * 0.1)) < 1e-9);
    }
    h.renderer.emit("update");
    assert.equal(route.options.weight * Number(h.routeSvg.properties.get("--route-line-scale")), 6);
});

test("close-up route widths stay unchanged and wider views cap growth at 30 percent", async () => {
    const h = await harness();
    const route = h.state.lines[1];
    for (const [zoom, expectedWidth] of [[16, 4.5], [15.25, 4.625], [15, 5], [12, 6.5], [8, 6.5]]) {
        h.map.zoom = zoom;
        h.map.emit("zoom");
        const visibleWidth = route.options.weight * Number(h.routeSvg.properties.get("--route-line-scale")) * h.map.getZoomScale(zoom, 15);
        assert.ok(Math.abs(visibleWidth - expectedWidth) < 1e-9);
    }
});

function encodedRoute(id, points) {
    let previous = [0, 0], encLine = "";
    for (const point of points) {
        const next = point.map((value) => Math.round(value * 1e5));
        next.forEach((value, axis) => {
            const delta = value - previous[axis];
            let encoded = delta < 0 ? ~(delta << 1) : delta << 1;
            while (encoded >= 32) { encLine += String.fromCharCode((32 | (encoded & 31)) + 63); encoded >>>= 5; }
            encLine += String.fromCharCode(encoded + 63);
        });
        previous = next;
    }
    return { id, encLine, color: "#008833", stopIds: [] };
}

test("shared corners and lane joins remain one complete path per route", async () => {
    const a = [42, -76], b = [42, -75.99], c = [42.01, -75.99], d = [42.01, -75.98];
    const h = await harness(feed([]), [encodedRoute(1, [a, b, c, d]), encodedRoute(2, [c, b, a])]);
    assert.equal(h.state.lines.length, 4, "one outline and one color path per route, never fragments");
    h.state.lines.forEach((line) => {
        assert.equal(line.renderedParts.length, 1);
        assert.equal(line.renderedParts[0].length, line.points.length);
        line.renderedParts[0].forEach((p) => assert.ok(Number.isFinite(p.x) && Number.isFinite(p.y)));
    });
    const first = h.state.lines[1].renderedParts[0];
    const reversed = h.state.lines[3].renderedParts[0];
    assert.notEqual(first[1].x, reversed[1].x, "opposing routes occupy separate lanes at the shared corner");
    assert.equal(first[3].x, d[1] * 10000, "unshared road returns to its geographic path");
});

test("zooming out compresses lanes instead of moving routes away from the road", async () => {
    const points = [[42, -76], [42, -75.99], [42.01, -75.99]];
    const h = await harness(feed([]), [encodedRoute(1, points), encodedRoute(2, points)]);
    const [a, b] = [h.state.lines[1], h.state.lines[3]];
    const initialGap = a.renderedParts[0][0].y - b.renderedParts[0][0].y;
    const metresPerPixel = (zoom) => 40075016.686 * Math.cos(42 * Math.PI / 180) / (256 * 2 ** zoom);
    assert.ok(Math.abs(initialGap) * metresPerPixel(15) <= 12.000001);
    for (const zoom of [14.75, 14.25, 13.5, 13]) {
        h.map.zoom = zoom;
        h.map.emit("zoom");
        const gap = a.renderedParts[0][0].y - b.renderedParts[0][0].y;
        assert.ok(Math.abs(gap * h.map.getZoomScale(zoom, 15)) * metresPerPixel(zoom) <= 12.000001);
        assert.equal(a.renderedParts.length, 1);
    }
    for (const line of h.state.lines) { line._project(); line._updatePath(); }
    const finalGap = a.renderedParts[0][0].y - b.renderedParts[0][0].y;
    assert.ok(Math.abs(finalGap - initialGap / 4) < 1e-8);
});

test("crowded bends stay within the road corridor even with seventeen shared routes", async () => {
    const points = [[42, -76], [42, -75.99999], [42.00001, -75.99999], [42.00001, -75.9998]];
    const h = await harness(feed([]), Array.from({ length: 17 }, (_, index) => encodedRoute(index + 1, points)));
    for (const line of h.state.lines) {
        line.options.laneOffsets.forEach((offset) => assert.ok(Math.hypot(offset.x, offset.y) <= 8.000001));
        line.renderedParts[0].forEach((p, index) => {
            const base = line._rings[0][index];
            const neighbors = [line._rings[0][index - 1], line._rings[0][index + 1]].filter(Boolean);
            const shortest = Math.min(...neighbors.map((q) => Math.hypot(q.x - base.x, q.y - base.y)));
            assert.ok(Math.hypot(p.x - base.x, p.y - base.y) <= shortest / 4 + 1e-8);
        });
    }
});

test("closed routes join their last offset vertex to their first without a gap", async () => {
    const loop = [[42, -76], [42, -75.99], [42.01, -75.99], [42, -76]];
    const h = await harness(feed([]), [encodedRoute(1, loop), encodedRoute(2, loop)]);
    for (const line of h.state.lines) {
        const ring = line.renderedParts[0];
        assert.equal(ring[0].x, ring.at(-1).x);
        assert.equal(ring[0].y, ring.at(-1).y);
    }
});

test("buffered playback stays about one update behind without position jumps", async () => {
    const h = await harness();
    const marker = h.state.markers[0];
    await h.refresh(feed([bus({ lat: 42.089 })]));
    assert.equal(h.state.markers.length, 1);
    assert.equal(marker.position.lat, 42.088);
    assert.equal(h.state.frames.size, 1);
    await h.refresh(feed([bus({ lat: 42.090 })]));
    assert.equal(h.state.frames.size, 1);
    h.tick(37500);
    assert.ok(marker.position.lat > 42.089 && marker.position.lat < 42.090);
    h.tick(44999);
    const before = marker.position.lat;
    await h.refresh(feed([bus({ lat: 42.091 })]), 45000);
    assert.ok(Math.abs(marker.position.lat - before) < 0.000001);
    assert.ok(marker.position.lat > 42.089 && marker.position.lat < 42.090);
    h.tick(52500);
    assert.ok(marker.position.lat > 42.090 && marker.position.lat < 42.091);
    h.tick(60000);
    assert.ok(marker.position.lat < 42.091);
});

test("one stationary reading does not stop motion; repeated near-zero movement does", async () => {
    const h = await harness();
    await h.refresh(feed([bus({ lat: 42.089 })]));
    await h.refresh(feed([bus({ lat: 42.090 })]));
    await h.refresh(feed([bus({ lat: 42.090 })]));
    assert.equal(h.state.frames.size, 1);
    h.tick(52500);
    assert.ok(h.state.markers[0].position.lat > 42.089);
    await h.refresh(feed([bus({ lat: 42.090 })]), 60000);
    h.tick(60001);
    assert.equal(h.state.frames.size, 0);
    assert.ok(Math.abs(h.state.markers[0].position.lat - 42.090) * 111320 < 3);
});

test("small GPS noise is ignored and distant corrections do not animate across town", async () => {
    const h = await harness();
    await h.refresh(feed([bus({ lat: 42.08801 })]));
    assert.equal(h.state.frames.size, 0);
    assert.equal(h.state.markers[0].position.lat, 42.088);
    await h.refresh(feed([bus({ lat: 42.2 })]));
    assert.equal(h.state.frames.size, 0);
    assert.equal(h.state.markers[0].position.lat, 42.2);
});

test("bearing follows a nearby compatible route, not the provider heading", async () => {
    const h = await harness(feed([bus({ heading: 180 })]), [encodedRoute(1, [[42.08, -75.968], [42.10, -75.968]])]);
    await h.refresh(feed([bus({ lat: 42.089, lng: -75.9679, heading: 270 })]));
    await h.refresh(feed([bus({ lat: 42.090, lng: -75.9678, heading: 270 })]));
    assert.ok(Math.abs(Number.parseFloat(h.state.markers[0].icon.properties.get("--heading"))) < 1e-8);
});

test("significant directional deviations override the route bearing", async () => {
    const h = await harness(feed([bus()]), [encodedRoute(1, [[42.08, -75.968], [42.10, -75.968]])]);
    await h.refresh(feed([bus({ lng: -75.967 })]));
    await h.refresh(feed([bus({ lng: -75.966 })]));
    const heading = (Number.parseFloat(h.state.markers[0].icon.properties.get("--heading")) % 360 + 360) % 360;
    assert.ok(Math.abs(heading - 90) < 0.1);
});

test("a route farther than 35 metres cannot override measured bearing", async () => {
    const h = await harness(feed([bus()]), [encodedRoute(1, [[42.08, -75.966], [42.10, -75.966]])]);
    await h.refresh(feed([bus({ lat: 42.089, lng: -75.9679 })]));
    await h.refresh(feed([bus({ lat: 42.090, lng: -75.9678 })]));
    const heading = (Number.parseFloat(h.state.markers[0].icon.properties.get("--heading")) % 360 + 360) % 360;
    assert.ok(heading > 3 && heading < 6);
});

test("feed outage preserves markers and stops at buffered data without extrapolating", async () => {
    const h = await harness();
    await h.refresh(feed([bus({ lat: 42.089 })]));
    await h.refresh(feed([bus({ lat: 42.090 })]));
    await h.refresh({ ...feed([]), vehiclesAvailable: false });
    h.tick(60000);
    assert.equal(h.state.markers[0].position.lat, 42.090);
    assert.equal(h.state.frames.size, 0);
    const group = [...h.map.layers].find((group) => group.layers?.has(h.state.markers[0]));
    assert.ok(group);
});

test("uneven update timing never overshoots or reverses the buffered GPS leg", async () => {
    const h = await harness();
    await h.refresh(feed([bus({ lat: 42.089 })]), 14000);
    await h.refresh(feed([bus({ lat: 42.0905 })]), 31000);
    let previous = h.state.markers[0].position.lat;
    for (let now = 31000; now <= 48000; now += 200) {
        h.tick(now);
        const current = h.state.markers[0].position.lat;
        assert.ok(current >= previous && current <= 42.0905);
        previous = current;
    }
});

test("recovery after a long outage starts a new track instead of inventing movement", async () => {
    const h = await harness();
    await h.refresh(feed([bus({ lat: 42.089 })]));
    await h.refresh(feed([bus({ lat: 42.091 })]), 100000);
    h.tick(100001);
    assert.equal(h.state.markers[0].position.lat, 42.091);
    assert.equal(h.state.markers[0].icon.properties.get("--direction-opacity"), "1");
    assert.equal(h.state.markers[0].icon.properties.get("--heading"), "359deg");
    assert.equal(h.state.frames.size, 0);
});

test("reported bearing is immediately visible without waiting for a second position", async () => {
    for (const [values, expected] of [
        [{ heading: 125, bearing: 90 }, 125],
        [{ heading: 0 }, 0],
        [{ heading: null, bearing: "270" }, 270],
        [{ heading: "", bearing: null, direction: 180 }, 180],
        [{ heading: -1, bearing: 360 }, 0],
    ]) {
        const h = await harness(feed([bus(values)]));
        const icon = h.state.markers[0].icon;
        assert.equal(icon.properties.get("--heading"), `${expected}deg`);
        assert.equal(icon.properties.get("--direction-opacity"), "1");
        assert.equal(h.state.frames.size, 0);
    }
});

test("missing reported bearings use nearby route geometry instead of a blank arrow", async () => {
    const route = encodedRoute(1, [[42.088, -75.98], [42.088, -75.95]]);
    const h = await harness(feed([bus({ heading: null, bearing: "", direction: null })]), [route]);
    const icon = h.state.markers[0].icon;
    assert.ok(Math.abs(Number.parseFloat(icon.properties.get("--heading")) - 90) < 0.1);
    assert.equal(icon.properties.get("--direction-opacity"), "1");
});

test("bearing crosses north along the short arc using positional history", async () => {
    const h = await harness();
    await h.refresh(feed([bus({ lat: 42.089, lng: -75.96802 })]));
    await h.refresh(feed([bus({ lat: 42.090, lng: -75.96804 })]));
    const before = Number.parseFloat(h.state.markers[0].icon.properties.get("--heading"));
    await h.refresh(feed([bus({ lat: 42.091, lng: -75.96798 })]));
    h.tick(50000);
    const after = Number.parseFloat(h.state.markers[0].icon.properties.get("--heading"));
    assert.ok(before > 350 && after > 359 && after < 370);
});

test("fractional placement cancels marker rounding without moving its geographic position", async () => {
    const h = await harness(feed([bus({ lng: -75.968025, lat: 42.088025 })]));
    const marker = h.state.markers[0];
    assert.ok(Math.abs(parseFloat(marker.icon.properties.get("--bus-offset-x")) + 0.25) < 1e-8);
    assert.ok(Math.abs(parseFloat(marker.icon.properties.get("--bus-offset-y")) + 0.25) < 1e-8);
    assert.equal(marker.position.lat, 42.088025);
});

test("only removed buses are unmounted and an empty animation loop stops", async () => {
    const h = await harness(feed([bus(), bus({ equipmentID: "102" })]));
    const vehicleGroup = [...h.map.layers].find((group) => group.layers?.has(h.state.markers[0]));
    await h.refresh(feed([bus({ lat: 42.089 })]));
    assert.equal(vehicleGroup.layers.size, 1);
    assert.equal(h.state.markers.length, 2);
    await h.refresh(feed([]));
    h.tick(600);
    assert.equal(vehicleGroup.layers.size, 0);
    assert.equal(h.state.frames.size, 0);
});

test("unchanged sidebar does not repeatedly invalidate the map layout", async () => {
    const h = await harness();
    assert.equal(h.map.invalidations, 1);
    await h.refresh(feed([bus()]));
    assert.equal(h.map.invalidations, 1);
    await h.refresh({ ...feed([bus()]), alerts: [] });
    assert.equal(h.map.invalidations, 2);
});

test("leaving the page cancels smoothing, polling and pending requests", async () => {
    const h = await harness();
    await h.refresh(feed([bus({ lat: 42.089 })]));
    await h.refresh(feed([bus({ lat: 42.090 })]));
    assert.equal(h.state.frames.size, 1);
    h.close();
    assert.equal(h.state.frames.size, 0);
    assert.equal(h.state.intervals.size, 0);
    assert.ok(h.state.signals.every((signal) => signal.aborted));
    assert.equal(h.map.removed, true);
});
