(() => {
  'use strict';
  const form = document.getElementById('design-editor');
  if (!form) return;
  const $ = selector => form.querySelector(selector);
  const stage = $('#design-stage');
  const error = $('#design-error');
  const status = $('#design-status');
  const layers = $('#design-layers');
  const properties = $('#design-properties');
  const source = document.getElementById('design-document');
  const fontSelect = $('[data-property="fontFamily"]');
  const googleFonts = new Set(Array.from(fontSelect.querySelectorAll('[data-google-font]'), option => option.value));
  const fontStylesheets = new Map();
  let canvas, width = 1920, height = 1080, dirty = false, busy = false, disposed = false;
  let history = [], cursor = -1, restoring = false, resizeFrame = 0, dragLayer = null;
  let pendingTextHistory = 0, requestController = null;
  const abort = new AbortController();
  const listen = (element, event, handler) => element.addEventListener(event, handler, {signal: abort.signal});
  const fail = message => { error.textContent = message; error.hidden = !message; };
  const current = () => canvas?.getActiveObject();
  const isText = object => object?.type === 'textbox';
  const label = object => isText(object) ? (object.text.trim().slice(0, 28) || 'Text') : ({image:'Image', rect:'Rectangle', circle:'Circle'}[object.type] || 'Layer');

  function fontStylesheet(family) {
    if (!googleFonts.has(family)) return Promise.resolve();
    if (fontStylesheets.has(family)) return fontStylesheets.get(family);
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = `https://fonts.googleapis.com/css2?family=${encodeURIComponent(family).replace(/%20/g, '+')}:ital,wght@0,400;0,700;1,400;1,700&display=swap`;
    const ready = new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error(`${family} could not be loaded. Check your connection and try again.`)), 15000);
      link.onload = () => { clearTimeout(timeout); resolve(); };
      link.onerror = () => { clearTimeout(timeout); reject(new Error(`${family} could not be loaded. Check your connection and try again.`)); };
      document.head.append(link);
    }).catch(error => { fontStylesheets.delete(family); link.remove(); throw error; });
    fontStylesheets.set(family, ready);
    return ready;
  }

  async function loadFont(family, sample) {
    if (!googleFonts.has(family)) return;
    await fontStylesheet(family);
    const text = sample || 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    const variants = ['normal 400', 'normal 700', 'italic 400', 'italic 700'];
    const faces = await Promise.all(variants.map(variant => document.fonts.load(`${variant} 32px "${family}"`, text)));
    if (faces.some(group => !group.length || group.some(face => face.status !== 'loaded')))
      throw new Error(`${family} could not be loaded. Check your connection and try again.`);
  }

  async function loadDocumentFonts(doc) {
    const samples = new Map();
    doc.objects.forEach(object => {
      if (object.type !== 'Textbox' || !googleFonts.has(object.fontFamily)) return;
      samples.set(object.fontFamily, (samples.get(object.fontFamily) || '') + object.text);
    });
    await Promise.all(Array.from(samples, ([family, sample]) => loadFont(family, sample)));
  }

  function documentValue() {
    return {schema: 1, width, height, background: canvas.backgroundColor,
      objects: canvas.toObject(['locked', 'cornerRadius', 'shadowSettings']).objects};
  }

  const defaultShadow = () => ({color:'#000000', opacity:.35, blur:12, offsetX:6, offsetY:6});

  function applyEffects(object) {
    object.set({stroke:object.stroke || '#222222', strokeWidth:object.strokeWidth || 0, paintFirst:'stroke'});
    if (object.type === 'rect') {
      const radius = Math.min(object.cornerRadius || 0, object.width / 2, object.height / 2);
      object.set({rx:radius, ry:radius});
    }
    if (object.type === 'image') {
      const radius = Math.min(object.cornerRadius || 0, object.width / 2, object.height / 2);
      object.set('clipPath', radius ? new fabric.Rect({width:object.width, height:object.height,
        rx:radius, ry:radius, originX:'center', originY:'center'}) : undefined);
    }
    if (object.shadowSettings) {
      const settings = object.shadowSettings;
      const rgb = [1, 3, 5].map(index => parseInt(settings.color.slice(index, index + 2), 16));
      object.set('shadow', new fabric.Shadow({color:`rgba(${rgb.join(',')},${settings.opacity})`,
        blur:settings.blur, offsetX:settings.offsetX, offsetY:settings.offsetY}));
    } else object.set('shadow', null);
    object.dirty = true;
  }

  function fit() {
    if (!canvas || disposed || !stage.clientWidth) return;
    const scale = Math.min((stage.clientWidth - 32) / width, (stage.clientHeight - 32) / height, 1);
    canvas.setDimensions({width: Math.round(width * scale), height: Math.round(height * scale)});
    canvas.setZoom(scale);
    canvas.requestRenderAll();
    $('#design-size-status').textContent = `${width} x ${height} | ${Math.round(scale * 100)}%`;
  }

  function applyLock(object) {
    const locked = !!object.locked;
    object.set({lockMovementX: locked, lockMovementY: locked, lockScalingX: locked,
      lockScalingY: locked, lockRotation: locked, hasControls: !locked,
      editable: !locked, originX:'left', originY:'top'});
  }

  function renderLayers() {
    const active = current();
    const objects = canvas.getObjects();
    layers.replaceChildren();
    objects.slice().reverse().forEach(object => {
      const index = objects.indexOf(object);
      const row = document.createElement('li');
      row.className = `design-layer${object === active ? ' is-selected' : ''}`;
      row.dataset.index = index;
      const name = document.createElement('button');
      name.type = 'button'; name.className = 'layer-name'; name.draggable = true;
      name.textContent = label(object); name.title = label(object); name.dataset.layerAction = 'select';
      name.setAttribute('aria-pressed', String(object === active));
      row.append(name);
      const definitions = [
        ['up', 'Raise layer', '<path d="m5 14 7-7 7 7"/>'],
        ['down', 'Lower layer', '<path d="m5 10 7 7 7-7"/>'],
        ['visible', object.visible ? 'Hide layer' : 'Show layer', '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>'],
        ['lock', object.locked ? 'Unlock layer' : 'Lock layer', '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V6a4 4 0 0 1 8 0v4"/>'],
      ];
      definitions.forEach(([action, title, path]) => {
        const button = document.createElement('button');
        button.type = 'button'; button.dataset.layerAction = action;
        button.title = title; button.setAttribute('aria-label', `${title}: ${label(object)}`);
        button.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">${path}</svg>`;
        if (action === 'lock') button.style.opacity = object.locked ? '1' : '.45';
        if (action === 'visible') button.style.opacity = object.visible ? '1' : '.35';
        button.disabled = (action === 'up' && index === objects.length - 1) || (action === 'down' && index === 0);
        row.append(button);
      });
      layers.append(row);
    });
    $('#design-layer-count').textContent = `${objects.length} / 80`;
  }

  function selection() {
    const object = current();
    properties.disabled = !object || !!object.locked || busy;
    $('#design-selection-name').textContent = object ? `${label(object)}${object.locked ? ' (locked)' : ''}` : 'No layer selected';
    form.querySelectorAll('[data-selection]').forEach(button => { button.disabled = !object || !!object.locked || busy; });
    $('#design-text-properties').hidden = !isText(object);
    $('#design-fill-label').hidden = object?.type === 'image';
    $('#design-radius-properties').hidden = !['rect', 'image'].includes(object?.type);
    $('#design-shadow-properties').hidden = !object?.shadowSettings;
    if (object) form.querySelectorAll('[data-property]').forEach(input => {
      const key = input.dataset.property;
      let value = key === 'visualWidth' ? object.width * object.scaleX : key === 'visualHeight' ? object.height * object.scaleY : object[key];
      if (key === 'angle') value = ((value + 180) % 360 + 360) % 360 - 180;
      if (typeof value === 'number' && input.type !== 'range') value = Math.round(value * 10) / 10;
      if (value !== undefined && document.activeElement !== input) input.value = value;
    });
    if (object) {
      $('[data-effect="strokeColor"]').value = object.stroke || '#222222';
      $('[data-effect="strokeWidth"]').value = object.strokeWidth || 0;
      $('[data-effect="cornerRadius"]').value = object.cornerRadius || 0;
      $('[data-output="cornerRadius"]').textContent = `${Math.round(object.cornerRadius || 0)} px`;
      $('[data-effect="shadowEnabled"]').checked = !!object.shadowSettings;
      const shadow = object.shadowSettings || defaultShadow();
      $('[data-effect="shadowColor"]').value = shadow.color;
      $('[data-effect="shadowOpacity"]').value = shadow.opacity;
      $('[data-effect="shadowBlur"]').value = shadow.blur;
      $('[data-effect="shadowOffsetX"]').value = shadow.offsetX;
      $('[data-effect="shadowOffsetY"]').value = shadow.offsetY;
      $('[data-output="shadowOpacity"]').textContent = `${Math.round(shadow.opacity * 100)}%`;
      $('[data-output="shadowBlur"]').textContent = `${Math.round(shadow.blur)} px`;
      $('[data-output="angle"]').textContent = `${Math.round(object.angle)} degrees`;
      $('[data-output="opacity"]').textContent = `${Math.round(object.opacity * 100)}%`;
      form.querySelectorAll('[data-style]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.style === 'underline' ? !!object.underline : object[button.dataset.style] !== 'normal')));
    }
    renderLayers();
  }

  function remember() {
    if (restoring || !canvas || disposed) return;
    clearTimeout(pendingTextHistory);
    pendingTextHistory = 0;
    const snapshot = JSON.stringify(documentValue());
    if (history[cursor] === snapshot) return;
    history = history.slice(0, cursor + 1);
    history.push(snapshot);
    // Images are embedded: bound history by bytes as well as action count.
    while (history.length > 1 && (history.length > 30 || history.reduce((sum, item) => sum + item.length, 0) > 24 * 1024 * 1024)) history.shift();
    cursor = history.length - 1;
    dirty = true; status.textContent = 'Unsaved changes';
    $('[data-action="undo"]').disabled = cursor <= 0;
    $('[data-action="redo"]').disabled = true;
    selection();
  }

  async function load(document) {
    width = document.width; height = document.height;
    await loadDocumentFonts(document);
    await canvas.loadFromJSON({objects: document.objects, background: document.background});
    if (disposed) return;
    canvas.getObjects().forEach(object => { applyLock(object); applyEffects(object); });
    $('#design-size').value = `${width}x${height}`;
    $('#design-background').value = document.background;
    fit(); selection();
  }

  async function travel(delta) {
    if (pendingTextHistory && !busy && !restoring) remember();
    if (busy || restoring || cursor + delta < 0 || cursor + delta >= history.length) return;
    restoring = true; form.setAttribute('aria-busy', 'true');
    try {
      await load(JSON.parse(history[cursor + delta])); cursor += delta;
      dirty = true; status.textContent = 'Unsaved changes';
    } catch (exception) { fail(exception.message || 'The previous design could not be restored.'); }
    finally {
      restoring = false; form.removeAttribute('aria-busy');
      $('[data-action="undo"]').disabled = cursor <= 0;
      $('[data-action="redo"]').disabled = cursor >= history.length - 1;
    }
  }

  function add(object) {
    if (canvas.getObjects().length >= 80) { fail('A design can contain up to 80 layers.'); return; }
    object.set({originX:'left', originY:'top', cornerColor:'#005A43', borderColor:'#005A43', transparentCorners:false});
    applyEffects(object);
    canvas.add(object); canvas.setActiveObject(object); canvas.requestRenderAll(); remember();
  }

  async function importImage(file) {
    if (!file || busy || restoring) return;
    if (!['image/png','image/jpeg','image/webp'].includes(file.type) || file.size > 20 * 1024 * 1024) {
      fail('Choose a PNG, JPEG, or WebP image smaller than 20 MB.'); return;
    }
    busy = true; status.textContent = 'Loading image...';
    let bitmap;
    try {
      bitmap = await createImageBitmap(file);
      const factor = Math.min(1, 2048 / Math.max(bitmap.width, bitmap.height));
      const reduced = document.createElement('canvas');
      reduced.width = Math.max(1, Math.round(bitmap.width * factor));
      reduced.height = Math.max(1, Math.round(bitmap.height * factor));
      reduced.getContext('2d').drawImage(bitmap, 0, 0, reduced.width, reduced.height);
      const src = reduced.toDataURL('image/webp', .9);
      reduced.width = reduced.height = 0;
      const object = await fabric.FabricImage.fromURL(src);
      if (disposed) return;
      const scale = Math.min(width * .65 / object.width, height * .65 / object.height, 1);
      object.set({left:width * .15, top:height * .15, scaleX:scale, scaleY:scale});
      add(object); fail('');
    } catch (_) { fail('This image could not be opened. Try a smaller PNG, JPEG, or WebP.'); }
    finally { bitmap?.close(); busy = false; status.textContent = dirty ? 'Unsaved changes' : 'Ready'; selection(); }
  }

  async function action(name) {
    if (!canvas || busy || restoring) return;
    const object = current();
    if (name === 'text') add(new fabric.Textbox('Your text', {left:width * .12, top:height * .18, width:width * .65, fontFamily:'Arial', fontSize:72, fill:'#222222', strokeWidth:0}));
    if (name === 'rect') add(new fabric.Rect({left:width * .15, top:height * .25, width:width * .4, height:height * .3, fill:'#005A43', strokeWidth:0}));
    if (name === 'circle') add(new fabric.Circle({left:width * .2, top:height * .25, radius:Math.min(width,height) * .15, fill:'#E1B544', strokeWidth:0}));
    if (name === 'image') $('#design-image-file').click();
    if (name === 'undo') await travel(-1);
    if (name === 'redo') await travel(1);
    if (!object || object.locked) return;
    if (name === 'delete') { canvas.discardActiveObject(); canvas.remove(object); canvas.requestRenderAll(); remember(); }
    if (name === 'duplicate') {
      const clone = await object.clone(['locked', 'cornerRadius', 'shadowSettings']);
      if (!disposed) { clone.set({left:object.left + 32, top:object.top + 32}); add(clone); }
    }
    if (name === 'center-x' || name === 'center-y') {
      const bounds = object.getBoundingRect();
      object.set(name === 'center-x' ? {left:object.left + (width - bounds.width) / 2 - bounds.left} : {top:object.top + (height - bounds.height) / 2 - bounds.top});
      object.setCoords(); canvas.requestRenderAll(); remember();
    }
  }

  async function init() {
    if (canvas || disposed || stage.clientWidth === 0) return;
    if (!window.fabric) { fail('The editor library failed to load. Refresh the page to retry.'); return; }
    canvas = new fabric.Canvas('design-canvas', {backgroundColor:'#FFFFFF', preserveObjectStacking:true, selection:false, renderOnAddRemove:false});
    canvas.on('selection:created', selection); canvas.on('selection:updated', selection); canvas.on('selection:cleared', selection);
    canvas.on('object:modified', remember);
    canvas.on('text:changed', () => { dirty = true; clearTimeout(pendingTextHistory); pendingTextHistory = setTimeout(remember, 400); });
    try {
      if (source) { restoring = true; await load(JSON.parse(source.textContent)); }
      else fit();
      restoring = false; remember(); dirty = false; status.textContent = 'Ready';
    } catch (exception) { restoring = false; fail(exception.message || 'The saved design could not be opened. Reload the page before saving.'); $('.design-save').disabled = true; }
  }

  listen(form, 'click', event => {
    const tool = event.target.closest('[data-action]');
    if (tool) action(tool.dataset.action).catch(() => fail('That action could not be completed.'));
    const style = event.target.closest('[data-style]');
    if (style && current() && !busy && !restoring && !current().locked) {
      const key = style.dataset.style;
      current().set(key, key === 'underline' ? !current().underline : current()[key] === 'normal' ? (key === 'fontWeight' ? 'bold' : 'italic') : 'normal');
      canvas.requestRenderAll(); remember();
    }
  });

  listen(form, 'input', event => {
    if (event.target.name) { dirty = true; status.textContent = 'Unsaved changes'; }
    const key = event.target.dataset.property, object = current();
    if (!key || !object || busy || restoring || object.locked) return;
    const numeric = ['number','range'].includes(event.target.type);
    const value = numeric ? Number(event.target.value) : event.target.value;
    if (numeric && (!event.target.value || !Number.isFinite(value) || !event.target.validity.valid)) return;
    if (key === 'fontFamily') {
      if (value === object.fontFamily) return;
      const previous = object.fontFamily;
      busy = true; form.setAttribute('aria-busy', 'true'); $('.design-save').disabled = true;
      status.textContent = `Loading ${value}...`;
      loadFont(value, object.text).then(() => {
        if (disposed || !canvas.getObjects().includes(object)) return;
        object.set('fontFamily', value); object.initDimensions(); object.setCoords();
        canvas.requestRenderAll(); fail(''); remember();
      }).catch(exception => { fontSelect.value = previous; fail(exception.message); }).finally(() => {
        busy = false; form.removeAttribute('aria-busy'); $('.design-save').disabled = false;
        status.textContent = dirty ? 'Unsaved changes' : 'Ready'; selection();
      });
      return;
    }
    if (key === 'visualWidth') object.set('scaleX', Math.min(20, Math.max(.01, value / object.width)));
    else if (key === 'visualHeight') object.set('scaleY', Math.min(20, Math.max(.01, value / object.height)));
    else object.set(key, value);
    object.setCoords(); canvas.requestRenderAll(); dirty = true;
    selection();
  });
  listen(form, 'change', event => { if (event.target.dataset.property && event.target.dataset.property !== 'fontFamily') remember(); });
  listen(form, 'input', event => {
    const key = event.target.dataset.effect, object = current();
    if (!key || !object || busy || restoring || object.locked) return;
    const value = event.target.type === 'checkbox' ? event.target.checked :
      ['number', 'range'].includes(event.target.type) ? Number(event.target.value) : event.target.value;
    if (event.target.type === 'number' && (!event.target.value || !event.target.validity.valid)) return;
    if (key === 'strokeColor') object.set('stroke', value);
    else if (key === 'strokeWidth') object.set('strokeWidth', value);
    else if (key === 'cornerRadius') object.cornerRadius = value;
    else if (key === 'shadowEnabled') object.shadowSettings = value ? defaultShadow() : null;
    else {
      const property = {shadowColor:'color', shadowOpacity:'opacity', shadowBlur:'blur',
        shadowOffsetX:'offsetX', shadowOffsetY:'offsetY'}[key];
      if (property && object.shadowSettings) object.shadowSettings = {...object.shadowSettings, [property]:value};
    }
    applyEffects(object); object.setCoords(); canvas.requestRenderAll(); dirty = true; selection();
  });
  listen(form, 'change', event => { if (event.target.dataset.effect) remember(); });
  listen($('#design-image-file'), 'change', event => { importImage(event.target.files[0]); event.target.value = ''; });
  listen($('#design-background'), 'input', event => { if (canvas && !busy) { canvas.backgroundColor = event.target.value; canvas.requestRenderAll(); dirty = true; } });
  listen($('#design-background'), 'change', remember);
  listen($('#design-size'), 'change', event => {
    if (!canvas || busy || restoring) return;
    [width, height] = event.target.value.split('x').map(Number); fit(); remember();
  });
  listen(layers, 'click', event => {
    if (busy || restoring) return;
    const button = event.target.closest('[data-layer-action]'), row = button?.closest('[data-index]');
    if (!row) return;
    const object = canvas.getObjects()[Number(row.dataset.index)], command = button.dataset.layerAction;
    if (command === 'select') canvas.setActiveObject(object);
    if (command === 'up') canvas.bringObjectForward(object);
    if (command === 'down') canvas.sendObjectBackwards(object);
    if (command === 'visible') object.set('visible', !object.visible);
    if (command === 'lock') { object.locked = !object.locked; applyLock(object); }
    canvas.requestRenderAll(); selection();
    if (command !== 'select') remember();
  });
  listen(layers, 'dragstart', event => {
    const row = event.target.closest('[data-index]');
    if (row) { dragLayer = canvas.getObjects()[Number(row.dataset.index)]; event.dataTransfer.setData('text/plain', row.dataset.index); }
  });
  listen(layers, 'dragover', event => event.preventDefault());
  listen(layers, 'drop', event => {
    event.preventDefault();
    const row = event.target.closest('[data-index]');
    if (row && dragLayer && !busy && !restoring) { canvas.moveObjectTo(dragLayer, Number(row.dataset.index)); canvas.requestRenderAll(); remember(); }
    dragLayer = null;
  });
  listen(layers, 'dragend', () => { dragLayer = null; });
  listen(stage, 'dragover', event => event.preventDefault());
  listen(stage, 'drop', event => { event.preventDefault(); importImage(event.dataTransfer.files[0]); });

  listen(document, 'keydown', event => {
    if (!canvas || !form.getClientRects().length || busy || restoring || current()?.isEditing || event.target.closest('input,textarea,select,[contenteditable="true"]')) return;
    const key = event.key.toLowerCase();
    if ((event.ctrlKey || event.metaKey) && ['z','y','d'].includes(key)) {
      event.preventDefault(); action(key === 'd' ? 'duplicate' : key === 'y' || event.shiftKey ? 'redo' : 'undo'); return;
    }
    if (key === 'delete' || key === 'backspace') { event.preventDefault(); action('delete'); }
    const object = current(), steps = {ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]};
    if (object && !object.locked && steps[event.key]) {
      event.preventDefault(); const [x,y] = steps[event.key], step = event.shiftKey ? 10 : 1;
      object.set({left:object.left+x*step, top:object.top+y*step}); object.setCoords(); canvas.requestRenderAll(); remember();
    }
  });

  listen(form, 'submit', async event => {
    event.preventDefault();
    if (!canvas || busy || restoring) return;
    if (!form.reportValidity()) return;
    const document = documentValue();
    const doc = JSON.stringify(document);
    if (new Blob([doc]).size > 12 * 1024 * 1024) { fail('The design is too large. Remove some images (12 MB maximum).'); return; }
    busy = true; form.setAttribute('aria-busy', 'true'); $('.design-save').disabled = true;
    fail(''); status.textContent = 'Rendering and saving...';
    requestController = new AbortController();
    const timeout = setTimeout(() => requestController.abort(), 120000);
    let rendered;
    try {
      status.textContent = 'Loading fonts...';
      await loadDocumentFonts(document);
      if (disposed) return;
      status.textContent = 'Rendering and saving...';
      canvas.discardActiveObject();
      canvas.setDimensions({width, height}); canvas.setZoom(1);
      try { rendered = canvas.toCanvasElement(2); } finally { fit(); }
      const preview = await new Promise(resolve => rendered.toBlob(resolve, 'image/png'));
      if (!preview) throw new Error('The preview could not be rendered.');
      const body = new FormData(form);
      body.append('document', new Blob([doc], {type:'application/json'}), 'design.json');
      body.append('preview', preview, 'preview.png');
      const response = await fetch(form.action, {method:'POST', body, signal:requestController.signal, headers:{'Accept':'application/json'}});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'The slide could not be saved.');
      dirty = false; window.location.assign(result.redirect);
    } catch (exception) {
      fail(exception.name === 'AbortError' ? 'Saving timed out. Check the Slide Library before retrying.' : exception.message || 'Unable to save. Your design is still open.');
      status.textContent = 'Not saved';
    } finally {
      clearTimeout(timeout); if (rendered) rendered.width = rendered.height = 0;
      busy = false; form.removeAttribute('aria-busy'); $('.design-save').disabled = false; selection();
    }
  });
  listen(window, 'beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
  // A cached page must not reuse a canvas disposed during pagehide.
  window.addEventListener('pageshow', event => { if (event.persisted) window.location.reload(); });
  const observer = new ResizeObserver(() => {
    cancelAnimationFrame(resizeFrame);
    resizeFrame = requestAnimationFrame(() => { if (!canvas) init(); else fit(); });
  });
  observer.observe(stage);
  listen(window, 'pagehide', () => {
    disposed = true; observer.disconnect(); cancelAnimationFrame(resizeFrame); clearTimeout(pendingTextHistory);
    requestController?.abort(); abort.abort(); canvas?.dispose(); history = [];
  });
  init();
})();
