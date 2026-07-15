/* Ray Aluframe reference-image review overlay. Expects #payload and preview toolbar nodes. */
(() => {
  'use strict';

  const payloadNode = document.getElementById('payload');
  if (!payloadNode) return;
  const payload = JSON.parse(payloadNode.textContent);
  const design = payload.design || {};
  const reference = design.reference_image || {};
  if (!reference.data_uri) return;

  const tools = document.getElementById('reference-tools');
  const toggle = document.getElementById('reference-review-toggle');
  const opacityControl = document.getElementById('reference-opacity-control');
  const opacity = document.getElementById('reference-opacity');
  const layer = document.getElementById('reference-layer');
  const image = document.getElementById('reference-image');
  const regionsRoot = document.getElementById('reference-regions');
  const note = document.getElementById('reference-note');
  if (!tools || !toggle || !opacityControl || !opacity || !layer || !image || !regionsRoot || !note) return;

  const numeric = (value, fallback) => Number.isFinite(Number(value)) ? Number(value) : fallback;
  const confidenceNames = { high: '高', medium: '中', low: '低' };
  const transform = reference.transform || {};
  const defaultOpacity = Math.max(0, Math.min(100, numeric(reference.default_opacity, 48)));
  const scale = Math.max(0.25, Math.min(4, numeric(transform.scale, 1)));
  const translateX = Math.max(-100, Math.min(100, numeric(transform.translate_x_pct, 0)));
  const translateY = Math.max(-100, Math.min(100, numeric(transform.translate_y_pct, 0)));
  const mirror = reference.mirror_x ? -1 : 1;

  tools.hidden = false;
  image.src = reference.data_uri;
  image.alt = reference.label || '设计参考图';
  image.style.objectFit = ['contain', 'cover'].includes(reference.object_fit) ? reference.object_fit : 'contain';
  image.style.objectPosition = reference.object_position || '50% 50%';
  image.style.opacity = String(defaultOpacity / 100);
  image.style.transform = `translate(${translateX}%,${translateY}%) scale(${scale * mirror},${scale})`;
  opacity.value = String(defaultOpacity);
  toggle.title = reference.source_name ? `参考图：${reference.source_name}` : '参考图校对';

  const regions = (design.reference_topology?.regions || [])
    .filter((region) => Array.isArray(region.x_range_mm) && region.x_range_mm.length === 2)
    .slice()
    .sort((a, b) => Number(a.x_range_mm[0]) - Number(b.x_range_mm[0]));
  if (reference.mirror_x) regions.reverse();
  regions.forEach((region, index) => {
    const item = document.createElement('div');
    const width = Math.max(1, Math.abs(Number(region.x_range_mm[1]) - Number(region.x_range_mm[0])));
    const title = document.createElement('strong');
    const detail = document.createElement('span');
    item.className = 'reference-region';
    item.style.flex = `${width} 1 0`;
    title.textContent = region.side_label || region.label || `分区 ${index + 1}`;
    const confidence = confidenceNames[region.confidence] || region.confidence || '未标注';
    detail.textContent = `${region.label || region.id || '未命名区域'} · ${region.expected_rows || '?'} 格 · ${confidence}置信度`;
    item.append(title, detail);
    regionsRoot.appendChild(item);
  });

  const setActive = (active) => {
    toggle.setAttribute('aria-pressed', String(active));
    layer.hidden = !active;
    regionsRoot.hidden = !active || regions.length === 0;
    note.hidden = !active;
    opacityControl.hidden = !active;
    if (active) {
      const frontButton = document.querySelector('[data-view="front"]');
      if (frontButton) frontButton.click();
    }
    window.dispatchEvent(new CustomEvent('ray-reference-review', { detail: { active } }));
  };

  toggle.addEventListener('click', () => setActive(toggle.getAttribute('aria-pressed') !== 'true'));
  opacity.addEventListener('input', () => {
    image.style.opacity = String(Math.max(0, Math.min(100, Number(opacity.value))) / 100);
  });
})();
