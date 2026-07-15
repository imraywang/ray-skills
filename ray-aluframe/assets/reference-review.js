/* Ray Aluframe multi-view reference review, alignment, and scale calibration. */
(() => {
  'use strict';

  const payloadNode = document.getElementById('payload');
  if (!payloadNode) return;
  const payload = JSON.parse(payloadNode.textContent);
  const design = payload.design || {};
  const references = [design.reference_image, ...(design.reference_images || [])]
    .filter((item) => item && item.data_uri);
  if (!references.length) return;

  const byId = (id) => document.getElementById(id);
  const tools = byId('reference-tools');
  const toggle = byId('reference-review-toggle');
  const opacityControl = byId('reference-opacity-control');
  const opacity = byId('reference-opacity');
  const scaleControl = byId('reference-scale-control');
  const scaleInput = byId('reference-scale');
  const xControl = byId('reference-x-control');
  const xInput = byId('reference-x');
  const yControl = byId('reference-y-control');
  const yInput = byId('reference-y');
  const select = byId('reference-view-select');
  const calibrate = byId('reference-calibrate');
  const calibration = byId('reference-calibration');
  const calibrationLayer = byId('reference-calibration-layer');
  const knownControl = byId('reference-known-control');
  const knownLength = byId('reference-known-length');
  const saveScale = byId('reference-save-scale');
  const layer = byId('reference-layer');
  const image = byId('reference-image');
  const regionsRoot = byId('reference-regions');
  const note = byId('reference-note');
  const canvas = byId('canvas');
  if (![tools, toggle, opacity, scaleInput, xInput, yInput, select, calibrate, calibrationLayer, knownControl, knownLength, saveScale, layer, image, regionsRoot, note, canvas].every(Boolean)) return;

  const numeric = (value, fallback) => Number.isFinite(Number(value)) ? Number(value) : fallback;
  const confidenceNames = { high: '高', medium: '中', low: '低' };
  const viewNames = { front: '正面', rear: '背面', left: '左侧', right: '右侧', top: '顶面', detail: '细节' };
  const states = references.map((reference, index) => {
    const transform = reference.transform || {};
    return {
      id: reference.id || `reference-${index + 1}`,
      view: reference.view || (index === 0 ? 'front' : 'detail'),
      source_name: reference.source_name || reference.label || `参考图 ${index + 1}`,
      opacity: Math.max(0, Math.min(100, numeric(reference.default_opacity, 48))),
      scale: Math.max(0.25, Math.min(4, numeric(transform.scale, 1))),
      x: Math.max(-100, Math.min(100, numeric(transform.translate_x_pct, 0))),
      y: Math.max(-100, Math.min(100, numeric(transform.translate_y_pct, 0))),
      mirror: Boolean(reference.mirror_x),
      calibration: reference.calibration || null,
      confirmed_regions: [],
    };
  });
  window.rayReferenceReviewState = { active: false, selected_index: 0, images: states };
  let selected = 0;
  let calibrationPoints = [];
  let calibrating = false;
  let pendingPixelLength = 0;

  select.innerHTML = references.map((reference, index) => `<option value="${index}">${viewNames[states[index].view] || states[index].view} · ${states[index].source_name}</option>`).join('');
  const regions = (design.reference_topology?.regions || []).filter((region) => Array.isArray(region.x_range_mm) && region.x_range_mm.length === 2);

  const renderRegions = () => {
    regionsRoot.innerHTML = '';
    const current = states[selected];
    if (current.view !== 'front') return;
    const ordered = regions.slice().sort((a, b) => Number(a.x_range_mm[0]) - Number(b.x_range_mm[0]));
    if (current.mirror) ordered.reverse();
    ordered.forEach((region, index) => {
      const item = document.createElement('button');
      const width = Math.max(1, Math.abs(Number(region.x_range_mm[1]) - Number(region.x_range_mm[0])));
      const regionId = String(region.id || region.label || index);
      item.type = 'button';
      item.className = 'reference-region';
      item.style.flex = `${width} 1 0`;
      item.dataset.confirmed = String(current.confirmed_regions.includes(regionId));
      const confidence = confidenceNames[region.confidence] || region.confidence || '未标注';
      item.innerHTML = `<strong>${region.side_label || region.label || `分区 ${index + 1}`}</strong><span>${region.label || region.id || '未命名区域'} · ${region.expected_rows || '?'} 格 · ${confidence}置信度</span>`;
      item.onclick = () => {
        const position = current.confirmed_regions.indexOf(regionId);
        if (position >= 0) current.confirmed_regions.splice(position, 1); else current.confirmed_regions.push(regionId);
        renderRegions();
      };
      regionsRoot.appendChild(item);
    });
  };

  const updateCalibration = () => {
    const current = states[selected];
    calibration.hidden = !current.calibration;
    calibration.textContent = current.calibration ? `${Number(current.calibration.mm_per_pixel).toFixed(3)} mm/px` : '';
  };

  const resetCalibrationUi = () => {
    calibrationPoints = [];
    pendingPixelLength = 0;
    calibrating = false;
    calibrationLayer.hidden = true;
    calibrationLayer.innerHTML = '';
    knownControl.hidden = true;
    saveScale.hidden = true;
    calibrate.textContent = '两点定尺度';
  };

  const applyReference = () => {
    const reference = references[selected];
    const current = states[selected];
    image.src = reference.data_uri;
    image.alt = reference.label || current.source_name;
    image.style.objectFit = ['contain', 'cover'].includes(reference.object_fit) ? reference.object_fit : 'contain';
    image.style.objectPosition = reference.object_position || '50% 50%';
    image.style.opacity = String(current.opacity / 100);
    image.style.transform = `translate(${current.x}%,${current.y}%) scale(${current.scale * (current.mirror ? -1 : 1)},${current.scale})`;
    opacity.value = String(current.opacity);
    scaleInput.value = String(current.scale * 100);
    xInput.value = String(current.x);
    yInput.value = String(current.y);
    renderRegions();
    updateCalibration();
    const preset = { front: 'front', rear: 'front', left: 'side', right: 'side', top: 'top' }[current.view];
    if (preset) document.querySelector(`[data-view="${preset}"]`)?.click();
  };

  const setActive = (active) => {
    window.rayReferenceReviewState.active = active;
    toggle.setAttribute('aria-pressed', String(active));
    layer.hidden = !active;
    regionsRoot.hidden = !active || !regions.length;
    note.hidden = !active;
    [opacityControl, scaleControl, xControl, yControl, select, calibrate].forEach((element) => { element.hidden = !active; });
    if (!active) resetCalibrationUi();
    if (active) applyReference();
    window.dispatchEvent(new CustomEvent('ray-reference-review', { detail: { active } }));
  };

  toggle.addEventListener('click', () => setActive(toggle.getAttribute('aria-pressed') !== 'true'));
  select.addEventListener('change', () => {
    selected = Number(select.value);
    window.rayReferenceReviewState.selected_index = selected;
    resetCalibrationUi();
    applyReference();
  });
  opacity.addEventListener('input', () => { states[selected].opacity = Number(opacity.value); applyReference(); });
  scaleInput.addEventListener('input', () => { states[selected].scale = Number(scaleInput.value) / 100; applyReference(); });
  xInput.addEventListener('input', () => { states[selected].x = Number(xInput.value); applyReference(); });
  yInput.addEventListener('input', () => { states[selected].y = Number(yInput.value); applyReference(); });
  calibrate.addEventListener('click', () => {
    resetCalibrationUi();
    calibrating = true;
    calibrationLayer.hidden = false;
    calibrate.textContent = '请在图上点两点';
  });
  calibrationLayer.addEventListener('pointerdown', (event) => {
    if (!calibrating || toggle.getAttribute('aria-pressed') !== 'true') return;
    event.preventDefault();
    const rect = calibrationLayer.getBoundingClientRect();
    const point = [event.clientX - rect.left, event.clientY - rect.top];
    calibrationPoints.push(point);
    const marker = document.createElement('span');
    marker.className = 'reference-calibration-point';
    marker.style.left = `${point[0]}px`;
    marker.style.top = `${point[1]}px`;
    calibrationLayer.appendChild(marker);
    if (calibrationPoints.length < 2) {
      calibrate.textContent = '再点第二点';
      return;
    }
    pendingPixelLength = Math.hypot(calibrationPoints[1][0] - calibrationPoints[0][0], calibrationPoints[1][1] - calibrationPoints[0][1]);
    calibrating = false;
    calibrationLayer.hidden = true;
    knownControl.hidden = false;
    saveScale.hidden = false;
    calibrate.textContent = '已选两点';
    knownLength.focus();
    knownLength.select();
  });
  saveScale.addEventListener('click', () => {
    const known = Number(knownLength.value);
    if (!Number.isFinite(known) || known <= 0 || pendingPixelLength <= 0) {
      knownLength.focus();
      return;
    }
    states[selected].calibration = { known_length_mm: known, pixel_length: pendingPixelLength, mm_per_pixel: known / pendingPixelLength };
    updateCalibration();
    resetCalibrationUi();
    updateCalibration();
  });

  tools.hidden = false;
})();
