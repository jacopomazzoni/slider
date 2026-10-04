// Endpoints
const forecastEndpoint = "https://api.weather.gov/gridpoints/BGM/64,56/forecast";
const alertEndpoint = "https://api.weather.gov/alerts/active?zone=NYZ009";
const gridEndpoint = "https://api.weather.gov/gridpoints/BGM/64,56";
const rainViewerEndpoint = "https://api.rainviewer.com/public/weather-maps.json";
const WEATHER_OVERLAY_SOURCE = window.WEATHER_OVERLAY_SOURCE || "rainviewer";
const WEATHER_SLIDE_DURATION = Number(window.WEATHER_SLIDE_DURATION) || 24000;
const SLIDE_PAUSED = Boolean(window.SLIDE_PAUSED);
const WEATHER_NEXT_URL = window.WEATHER_NEXT_URL || "/slidedisplay/";
const RADAR_REFRESH_INTERVAL = 10 * 60 * 1000;
const FRAME_FADE_DURATION = 1800;
const RADAR_OPACITY = 0.58;
const SATELLITE_OPACITY = 0.28;
const NASA_GIBS_OPACITY = 1;
const NASA_GIBS_FRAME_COUNT = 8;
const NASA_GIBS_FRAME_STEP_MINUTES = 10;
const NASA_GIBS_AVAILABILITY_LAG_MINUTES = 30;
const NASA_GIBS_IMAGE_SCALE = 2;
const NASA_GIBS_MAX_IMAGE_DIMENSION = 4096;
const RAINVIEWER_MAX_NATIVE_ZOOM = 7;
const MAX_DISPLAY_ZOOM = 20;
const NASA_GIBS_WMS_ENDPOINT = "https://gibs.earthdata.nasa.gov/wms/epsg3857/nrt/wms.cgi";
const NASA_GIBS_GOES_EAST_LAYER = "GOES-East_ABI_GeoColor_v0_NRT";
const TRANSPARENT_TILE = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==";

const MAP_LAYERS = {
  osm_hot: {
    url: "https://{s}.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png",
    options: { minZoom: 0, maxZoom: 20 },
    attribution: "Map © OpenStreetMap contributors, tiles by Humanitarian OpenStreetMap Team hosted by OpenStreetMap France"
  },
  osm_standard: {
    url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    options: { minZoom: 0, maxZoom: 19 },
    attribution: "Map © OpenStreetMap contributors"
  },
  opentopomap: {
    url: "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
    options: { minZoom: 0, maxZoom: 17 },
    attribution: "Map data © OpenStreetMap contributors, SRTM | map style © OpenTopoMap (CC-BY-SA)"
  },
  cyclosm: {
    url: "https://{s}.tile-cyclosm.openstreetmap.fr/cyclosm/{z}/{x}/{y}.png",
    options: { minZoom: 0, maxZoom: 20 },
    attribution: "CyclOSM | Map data © OpenStreetMap contributors"
  }
};

let map;
let weatherFrames = [];
let radarLayers = [];
let satelliteLayers = [];
let frameIndex = 0;
let animationFrameId = null;
let refreshIntervalId = null;
let slideTimeoutId = null;
let resizeReloadTimerId = null;
let sidebarFitFrameId = null;
let mapResizeObserver = null;
let animationGeneration = 0;
let isDisposed = false;

function byId(id) {
  return document.getElementById(id);
}

function safeNumber(value) {
  if ((typeof value !== 'number' && typeof value !== 'string') || String(value).trim() === '') return null;
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? numberValue : null;
}

function formatNumber(value, digits = 1, fallback = null) {
  const numberValue = safeNumber(value);
  return numberValue === null ? fallback : numberValue.toFixed(digits);
}

function formatValue(value, unit = "", digits = 1) {
  const formatted = typeof value === "number" ? formatNumber(value, digits) : value;
  if (formatted === null || formatted === undefined || /^(?:\s*|n\/?a|nan|null|undefined|unknown|unavailable|infinity)$/i.test(String(formatted).trim())) {
    return null;
  }
  return `${formatted}${unit ? ` ${unit}` : ""}`;
}

function weatherEscape(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
}

function weatherMetric(icon, value, unit = '', digits = 1, label = '') {
  const formatted = formatValue(value, unit, digits);
  if (formatted === null) return '';
  return `<span><i class="wi ${icon}"></i>${weatherEscape(label)}${weatherEscape(formatted)}</span>`;
}

function firstVal(gridProperty) {
  const values = gridProperty?.values || [];
  for (let i = 0; i < values.length; i++) {
    if (values[i].value !== null && values[i].value !== undefined) {
      return values[i].value;
    }
  }
  return null;
}

function toF(value, unit) {
  const numberValue = safeNumber(value);
  if (numberValue === null) return null;
  if (unit && unit.includes("degC")) return (numberValue * 9 / 5) + 32;
  return numberValue;
}

function getSelectedMapLayer() {
  return MAP_LAYERS[window.WEATHER_MAP_LAYER] || MAP_LAYERS.osm_hot;
}

function updateMapAttribution(layerConfig) {
  const attribution = byId("map-attribution");
  if (attribution) attribution.textContent = layerConfig.attribution;
}

function updateOverlayAttribution(text) {
  const attribution = byId("weather-overlay-attribution");
  if (attribution) attribution.textContent = text;
}

function initMap() {
  map = L.map("radar-map", {
    center: [42.06, -75.97],
    zoom: 10,
    zoomControl: false,
    attributionControl: false,
    dragging: false,
    scrollWheelZoom: false
  });

  const baseLayerConfig = getSelectedMapLayer();
  L.tileLayer(baseLayerConfig.url, baseLayerConfig.options).addTo(map);
  updateMapAttribution(baseLayerConfig);
}

function clearLayerGroup(layers) {
  layers.forEach((layer) => map.removeLayer(layer));
  layers.length = 0;
}

function cancelWeatherAnimation() {
  animationGeneration += 1;
  if (animationFrameId !== null) {
    cancelAnimationFrame(animationFrameId);
    animationFrameId = null;
  }
}

function buildTimeline() {
  const track = byId("timeline-track");
  if (!track) return;
  track.innerHTML = "";
  if (weatherFrames.length === 0) return;

  const count = weatherFrames.length;
  for (let i = 0; i < count; i++) {
    const tick = document.createElement("div");
    tick.className = "timeline-tick";
    tick.style.left = count === 1 ? "0%" : `${(i / (count - 1)) * 100}%`;
    track.appendChild(tick);
  }

  const marker = document.createElement("div");
  marker.className = "timeline-marker";
  marker.id = "timeline-marker";
  marker.style.left = "0%";
  track.appendChild(marker);
}

function updateTimelineMarker(index) {
  const marker = byId("timeline-marker");
  if (marker && weatherFrames.length > 1) {
    marker.style.left = `${(index / (weatherFrames.length - 1)) * 100}%`;
  }
}

function updateTimestamp(unixTime) {
  const timestamp = byId("timestamp");
  if (!timestamp) return;

  const numberValue = safeNumber(unixTime);
  if (numberValue === null) {
    timestamp.textContent = "Weather map unavailable";
    return;
  }

  const date = new Date(numberValue * 1000);
  timestamp.textContent = `${date.toISOString().replace("T", " ").split(".")[0]} UTC`;
}

function satelliteFrameOpacity() {
  return WEATHER_OVERLAY_SOURCE === "nasa_gibs" ? NASA_GIBS_OPACITY : SATELLITE_OPACITY;
}

function rainViewerTileUrl(host, path, isSatellite) {
  const color = isSatellite ? 0 : 2;
  const options = isSatellite ? "0_0" : "1_1";
  return `${host}${path}/256/{z}/{x}/{y}/${color}/${options}.png`;
}

function rainViewerLayerOptions(opacity, zIndex) {
  return {
    opacity,
    zIndex,
    minZoom: 0,
    maxZoom: MAX_DISPLAY_ZOOM,
    maxNativeZoom: RAINVIEWER_MAX_NATIVE_ZOOM,
    errorTileUrl: TRANSPARENT_TILE,
    keepBuffer: 1
  };
}

function normalizeRainViewerFrames(data) {
  const host = data.host || "https://tilecache.rainviewer.com";
  const radarPast = data.radar?.past || [];
  const radarNowcast = data.radar?.nowcast || [];
  const radarFrames = radarPast.concat(radarNowcast).filter((frame) => frame.path && frame.time).slice(-12);

  return radarFrames
    .map((frame) => ({
      time: frame.time,
      radarUrl: rainViewerTileUrl(host, frame.path, false)
    }));
}

function addWeatherLayers(frames) {
  clearLayerGroup(radarLayers);
  clearLayerGroup(satelliteLayers);

  frames.forEach((frame, index) => {
    if (frame.satelliteUrl) {
      const satelliteLayer = L.tileLayer(
        frame.satelliteUrl,
        rainViewerLayerOptions(index === 0 ? SATELLITE_OPACITY : 0, 10 + index)
      );
      satelliteLayer.addTo(map);
      satelliteLayers.push(satelliteLayer);
    }

    const radarLayer = L.tileLayer(
      frame.radarUrl,
      rainViewerLayerOptions(index === 0 ? RADAR_OPACITY : 0, 40 + index)
    );
    radarLayer.addTo(map);
    radarLayers.push(radarLayer);
  });
}

function roundDownToFrameTime(date) {
  const rounded = new Date(date);
  const minutes = rounded.getUTCMinutes();
  rounded.setUTCMinutes(
    Math.floor(minutes / NASA_GIBS_FRAME_STEP_MINUTES) * NASA_GIBS_FRAME_STEP_MINUTES,
    0,
    0
  );
  return rounded;
}

function nasaGibsFrameTimes() {
  const endTime = roundDownToFrameTime(
    new Date(Date.now() - NASA_GIBS_AVAILABILITY_LAG_MINUTES * 60 * 1000)
  );
  const frames = [];

  for (let i = NASA_GIBS_FRAME_COUNT - 1; i >= 0; i--) {
    const frameDate = new Date(endTime.getTime() - i * NASA_GIBS_FRAME_STEP_MINUTES * 60 * 1000);
    frames.push({
      time: Math.floor(frameDate.getTime() / 1000),
      isoTime: frameDate.toISOString().replace(".000Z", "Z")
    });
  }

  return frames;
}

function projectedBbox(bounds) {
  const crs = map.options.crs;
  const southwest = crs.project(bounds.getSouthWest());
  const northeast = crs.project(bounds.getNorthEast());
  return [
    southwest.x,
    southwest.y,
    northeast.x,
    northeast.y
  ].join(",");
}

function nasaGibsImageSize() {
  const mapElement = byId("radar-map");
  const cssWidth = Math.max(1, mapElement?.clientWidth || 1024);
  const cssHeight = Math.max(1, mapElement?.clientHeight || 512);
  const scale = Math.max(NASA_GIBS_IMAGE_SCALE, Math.min(3, window.devicePixelRatio || 1));
  let width = Math.ceil(cssWidth * scale);
  let height = Math.ceil(cssHeight * scale);
  const largestDimension = Math.max(width, height);

  if (largestDimension > NASA_GIBS_MAX_IMAGE_DIMENSION) {
    const downscale = NASA_GIBS_MAX_IMAGE_DIMENSION / largestDimension;
    width = Math.max(1, Math.floor(width * downscale));
    height = Math.max(1, Math.floor(height * downscale));
  }

  return { width, height };
}

function nasaGibsGetMapUrl(frame, bounds) {
  const { width, height } = nasaGibsImageSize();
  const params = new URLSearchParams({
    SERVICE: "WMS",
    VERSION: "1.1.1",
    REQUEST: "GetMap",
    LAYERS: NASA_GIBS_GOES_EAST_LAYER,
    STYLES: "",
    FORMAT: "image/png",
    TRANSPARENT: "true",
    SRS: "EPSG:3857",
    BBOX: projectedBbox(bounds),
    WIDTH: width.toString(),
    HEIGHT: height.toString(),
    TIME: frame.isoTime
  });
  return `${NASA_GIBS_WMS_ENDPOINT}?${params.toString()}`;
}

function addNasaGibsLayers(frames) {
  clearLayerGroup(radarLayers);
  clearLayerGroup(satelliteLayers);
  const bounds = map.getBounds();

  frames.forEach((frame, index) => {
    const layer = L.imageOverlay(nasaGibsGetMapUrl(frame, bounds), bounds, {
      opacity: index === 0 ? NASA_GIBS_OPACITY : 0,
      zIndex: 10 + index,
      interactive: false,
      crossOrigin: true,
      className: "nasa-gibs-overlay"
    });
    layer.addTo(map);
    satelliteLayers.push(layer);
  });
}

function loadNasaGibsFrames() {
  cancelWeatherAnimation();
  updateOverlayAttribution("NASA GIBS GOES-East GeoColor");

  weatherFrames = nasaGibsFrameTimes();
  frameIndex = 0;
  addNasaGibsLayers(weatherFrames);
  buildTimeline();
  updateTimestamp(weatherFrames[0]?.time);

  if (weatherFrames.length > 1) {
    animateWeatherLayers(animationGeneration);
  }
}

async function loadWeatherFrames() {
  cancelWeatherAnimation();

  if (WEATHER_OVERLAY_SOURCE === "nasa_gibs") {
    loadNasaGibsFrames();
    return;
  }

  updateOverlayAttribution("RainViewer radar (precipitation only)");

  try {
    const response = await fetch(rainViewerEndpoint, { cache: "no-store" });
    if (!response.ok) throw new Error(`RainViewer HTTP ${response.status}`);

    const data = await response.json();
    const frames = normalizeRainViewerFrames(data);
    if (frames.length === 0) {
      updateTimestamp(null);
      return;
    }

    weatherFrames = frames;
    frameIndex = 0;
    addWeatherLayers(weatherFrames);
    buildTimeline();
    updateTimestamp(weatherFrames[0]?.time);
    if (weatherFrames.length === 1) return;
    animateWeatherLayers(animationGeneration);
  } catch (error) {
    console.error("Unable to load weather map frames:", error);
    updateTimestamp(null);
  }
}

function setLayerOpacity(layers, index, opacity) {
  const layer = layers[index];
  if (layer) layer.setOpacity(opacity);
}

function animateWeatherLayers(generation) {
  if (isDisposed || generation !== animationGeneration || weatherFrames.length === 0) return;

  const nextIndex = (frameIndex + 1) % weatherFrames.length;
  const start = performance.now();
  const targetSatelliteOpacity = satelliteFrameOpacity();
  updateTimestamp(weatherFrames[nextIndex]?.time);
  updateTimelineMarker(nextIndex);

  function step(now) {
    if (isDisposed || generation !== animationGeneration) return;

    const progress = Math.min(1, (now - start) / FRAME_FADE_DURATION);
    const eased = 0.5 - 0.5 * Math.cos(Math.PI * progress);

    setLayerOpacity(radarLayers, frameIndex, RADAR_OPACITY * (1 - eased));
    setLayerOpacity(radarLayers, nextIndex, RADAR_OPACITY * eased);
    setLayerOpacity(satelliteLayers, frameIndex, targetSatelliteOpacity * (1 - eased));
    setLayerOpacity(satelliteLayers, nextIndex, targetSatelliteOpacity * eased);

    if (progress < 1) {
      animationFrameId = requestAnimationFrame(step);
      return;
    }

    frameIndex = nextIndex;
    animationFrameId = requestAnimationFrame(() => animateWeatherLayers(generation));
  }

  animationFrameId = requestAnimationFrame(step);
}

async function fetchForecastAndAlerts() {
  try {
    const [forecastResponse, alertResponse] = await Promise.all([
      fetch(forecastEndpoint, { headers: { "Accept": "application/geo+json" } }),
      fetch(alertEndpoint)
    ]);
    if (!forecastResponse.ok) throw new Error(`Forecast HTTP ${forecastResponse.status}`);

    const forecastData = await forecastResponse.json();
    const alertData = alertResponse.ok ? await alertResponse.json() : { features: [] };
    renderMain(forecastData, alertData);
    renderForecast(forecastData);
  } catch (error) {
    console.error("Unable to load forecast data:", error);
    const left = byId("col-left");
    if (left) left.textContent = "Weather forecast unavailable.";
  }
}

function alertIcon(event = "") {
  const value = event.toLowerCase();
  if (value.includes("wind")) return "wi-strong-wind";
  if (value.includes("flood")) return "wi-flood";
  if (value.includes("thunder")) return "wi-thunderstorm";
  if (value.includes("snow")) return "wi-snow";
  if (value.includes("heat")) return "wi-hot";
  if (value.includes("tornado")) return "wi-tornado";
  if (value.includes("fog")) return "wi-fog";
  return "wi-warning";
}

function renderMain(forecastData, alertData) {
  const current = forecastData.properties?.periods?.[0];
  if (!current) return;

  const desc = `${current.shortForecast || ""}. ${current.detailedForecast || ""}`.trim();
  const left = byId("col-left");
  if (left) left.textContent = desc.replace(/\. /g, ".\n");

  const dirs = { N: 0, NNE: 22, NE: 45, ENE: 67, E: 90, ESE: 112, SE: 135, SSE: 157, S: 180, SSW: 202, SW: 225, WSW: 247, W: 270, WNW: 292, NW: 315, NNW: 337 };
  const ang = dirs[current.windDirection] || 0;
  const right = byId("col-right");
  if (right) {
    right.innerHTML = weatherMetric('wi-thermometer', safeNumber(current.temperature), `°${current.temperatureUnit || ''}`)
      + weatherMetric(`wi-wind from-${ang}-deg`, current.windSpeed)
      + weatherMetric('wi-raindrops', safeNumber(current.probabilityOfPrecipitation?.value), '%', 0);
  }

  if (window.__extraData) renderExtraMetrics(window.__extraData);

  const banner = byId("alert-banner");
  if (!banner) return;
  if (alertData.features?.length > 0) {
    const alert = alertData.features[0].properties;
    const event = alert.event || "Weather alert";
    const headline = alert.headline || "";
    banner.style.display = "block";
    banner.innerHTML = `<i class="wi ${alertIcon(event)}"></i> ${weatherEscape(event.toUpperCase())}: ${weatherEscape(headline)}`;
  } else {
    banner.style.display = "none";
  }
}

function mapForecastToIcon(shortForecast = "", isDaytime = true) {
  const value = shortForecast.toLowerCase();
  if (value.includes("thunder")) return { icon: "wi-thunderstorm", anim: "animate-thunder" };
  if (value.includes("snow")) return { icon: "wi-snow", anim: "animate-snow" };
  if (value.includes("rain") || value.includes("showers")) return { icon: "wi-rain", anim: "animate-rain" };
  if (value.includes("cloudy")) return { icon: "wi-cloudy", anim: "animate-cloud" };
  if (value.includes("fog")) return { icon: "wi-fog", anim: "animate-cloud" };
  if (value.includes("clear")) return { icon: isDaytime ? "wi-day-sunny" : "wi-night-clear", anim: "animate-sun" };
  return { icon: "wi-day-sunny-overcast", anim: "animate-cloud" };
}

function renderForecast(forecastData) {
  const row = byId("forecast-row");
  if (!row) return;
  row.innerHTML = "";

  const periods = forecastData.properties?.periods || [];
  periods.slice(1, 4).forEach((period) => {
    const { icon, anim } = mapForecastToIcon(period.shortForecast, period.isDaytime);
    const temperature = safeNumber(period.temperature);
    const card = document.createElement("div");
    card.className = "forecast-card";
    card.innerHTML = `
      <h3>${weatherEscape(period.name || "Forecast")}</h3>
      <i class="wi ${icon} ${anim}"></i>
      ${temperature === null ? '' : `<div><b>${formatNumber(temperature)}°${weatherEscape(period.temperatureUnit || '')}</b></div>`}
      <div>${weatherEscape(period.shortForecast || "Forecast unavailable")}</div>
      <div>${weatherMetric('wi-raindrops', safeNumber(period.probabilityOfPrecipitation?.value), '%', 0)}</div>`;
    row.appendChild(card);
  });
}

function renderExtraMetrics(extraData) {
  const center = byId("col-center");
  if (!center) return;
  center.innerHTML = weatherMetric('wi-humidity', extraData.RH, '%', 0, 'Humidity: ')
    + weatherMetric('wi-barometer', extraData.Pressure, 'hPa', 1, 'Pressure: ')
    + weatherMetric('wi-cloudy', extraData.Sky, '%', 0, 'Sky: ')
    + weatherMetric('wi-strong-wind', extraData.Wgust, 'km/h', 1, 'Wind Gust: ');
}

async function fetchGridpoints() {
  try {
    const response = await fetch(gridEndpoint, { headers: { "Accept": "application/geo+json" } });
    if (!response.ok) throw new Error(`Gridpoint HTTP ${response.status}`);

    const data = await response.json();
    const properties = data.properties || {};
    populateSideTab(properties);

    const pressureValue = safeNumber(firstVal(properties.pressure));
    const extraData = {
      RH: formatNumber(firstVal(properties.relativeHumidity), 0),
      Pressure: pressureValue === null ? null : formatNumber(pressureValue / 100, 1),
      Sky: formatNumber(firstVal(properties.skyCover), 0),
      Wgust: formatNumber(firstVal(properties.windGust), 1)
    };

    window.__extraData = extraData;
    renderExtraMetrics(extraData);
    requestAnimationFrame(() => requestAnimationFrame(() => fitSidebarToMap()));
  } catch (error) {
    console.error("Unable to load gridpoint data:", error);
    window.__extraData = {};
    renderExtraMetrics({});
    populateSideTab({});
  }
}

function addRow(container, icon, label, value, unit = "", digits = 1) {
  if (!container) return;
  const displayValue = formatValue(value, unit, digits);
  if (displayValue === null) return;

  const row = document.createElement("div");
  row.className = "row";
  row.innerHTML = `<i class="wi ${icon}"></i><span>${weatherEscape(label)}: <b>${weatherEscape(displayValue)}</b></span>`;
  container.appendChild(row);
}

function addWindRow(container, label, value) {
  const numberValue = safeNumber(value);
  if (!container || numberValue === null) return;

  const direction = Math.round(numberValue);
  const row = document.createElement("div");
  row.className = "row";
  row.innerHTML = `<i class="wi wi-wind from-${direction}-deg"></i><span>${label}: <b>${direction}°</b></span>`;
  container.appendChild(row);
}

function populateSideTab(properties) {
  const gT = byId("grp-temp");
  const gM = byId("grp-moist");
  const gW = byId("grp-wind");
  const gC = byId("grp-clouds");
  const gP = byId("grp-pressure");
  [gT, gM, gW, gC, gP].forEach((element) => {
    if (element) element.innerHTML = "";
  });

  addRow(gT, "wi-thermometer", "Temperature", toF(firstVal(properties.temperature), properties.temperature?.uom), "°F");
  addRow(gT, "wi-thermometer-exterior", "Dew Point", toF(firstVal(properties.dewpoint), properties.dewpoint?.uom), "°F");
  addRow(gT, "wi-thermometer", "Feels Like", toF(firstVal(properties.apparentTemperature), properties.apparentTemperature?.uom), "°F");
  addRow(gT, "wi-direction-up", "Max Temperature", toF(firstVal(properties.maxTemperature), properties.maxTemperature?.uom), "°F");
  addRow(gT, "wi-direction-down", "Min Temperature", toF(firstVal(properties.minTemperature), properties.minTemperature?.uom), "°F");

  addRow(gM, "wi-humidity", "Relative Humidity", firstVal(properties.relativeHumidity), "%", 0);
  addRow(gM, "wi-raindrops", "Precipitation", firstVal(properties.quantitativePrecipitation), "mm");
  addRow(gM, "wi-snow", "Snowfall", firstVal(properties.snowfallAmount), "mm");
  addRow(gM, "wi-rain-mix", "Ice Accumulation", firstVal(properties.iceAccumulation), "mm");

  addRow(gW, "wi-strong-wind", "Wind Speed", firstVal(properties.windSpeed), "km/h");
  addRow(gW, "wi-windy", "Wind Gust", firstVal(properties.windGust), "km/h");
  addWindRow(gW, "Wind Direction", firstVal(properties.windDirection));
  addRow(gW, "wi-wind-beaufort-6", "Transport Wind Speed", firstVal(properties.transportWindSpeed), "km/h");
  addWindRow(gW, "Transport Wind Direction", firstVal(properties.transportWindDirection));

  const weatherCode = properties.weather?.values?.[0]?.value?.[0]?.weather;
  addRow(gC, "wi-cloudy", "Sky Cover", firstVal(properties.skyCover), "%", 0);
  addRow(gC, "wi-na", "Weather Code", weatherCode, "", 0);
  addRow(gC, "wi-cloud", "Mixing Height", firstVal(properties.mixingHeight), "m");

  const pressure = safeNumber(firstVal(properties.pressure));
  if (pressure !== null) addRow(gP, "wi-barometer", "Pressure", pressure / 100, "hPa");
}

function fitSidebarToMap() {
  const mapElement = byId("radar-map");
  const tab = byId("side-tab");
  if (!mapElement || !tab) return;

  tab.style.setProperty("--s", 1);
  const targetHeight = mapElement.clientHeight - 20;
  const ratio = targetHeight / tab.scrollHeight;
  let scale = Math.min(1, Math.max(0.35, ratio * 0.92));
  let safety = 0;
  tab.style.setProperty("--s", scale);

  while (tab.scrollHeight > targetHeight && scale > 0.35 && safety < 30) {
    scale = Math.max(0.35, scale * 0.94);
    tab.style.setProperty("--s", scale);
    void tab.offsetHeight;
    safety += 1;
  }
}

function scheduleSidebarFit() {
  if (isDisposed || sidebarFitFrameId !== null) return;
  sidebarFitFrameId = requestAnimationFrame(() => {
    sidebarFitFrameId = null;
    if (isDisposed) return;
    fitSidebarToMap();
    if (map) map.invalidateSize({ animate: false, pan: false });
  });
}

function disposeWeatherDashboard() {
  isDisposed = true;
  if (sidebarFitFrameId !== null) cancelAnimationFrame(sidebarFitFrameId);
  if (mapResizeObserver) mapResizeObserver.disconnect();
  cancelWeatherAnimation();
  if (refreshIntervalId !== null) clearInterval(refreshIntervalId);
  if (slideTimeoutId !== null) clearTimeout(slideTimeoutId);
  if (resizeReloadTimerId !== null) clearTimeout(resizeReloadTimerId);
  if (map) {
    clearLayerGroup(radarLayers);
    clearLayerGroup(satelliteLayers);
    map.remove();
  }
}

window.addEventListener("resize", () => {
  scheduleSidebarFit();
  if (WEATHER_OVERLAY_SOURCE === "nasa_gibs" && !isDisposed) {
    if (resizeReloadTimerId !== null) clearTimeout(resizeReloadTimerId);
    resizeReloadTimerId = window.setTimeout(loadWeatherFrames, 500);
  }
});
window.addEventListener("pagehide", disposeWeatherDashboard);

initMap();
if (typeof ResizeObserver !== 'undefined') {
  mapResizeObserver = new ResizeObserver(scheduleSidebarFit);
  mapResizeObserver.observe(byId('radar-map'));
}
loadWeatherFrames();
refreshIntervalId = window.setInterval(loadWeatherFrames, RADAR_REFRESH_INTERVAL);
fetchGridpoints();
fetchForecastAndAlerts();
if (!SLIDE_PAUSED) {
  slideTimeoutId = window.setTimeout(() => {
    window.location.href = WEATHER_NEXT_URL;
  }, Math.max(1000, WEATHER_SLIDE_DURATION));
}
