/* Ray Aluframe offline 3D viewer. Expects window.THREE and #payload. */
(() => {
  'use strict';

  const THREE = window.THREE;
  if (!THREE) throw new Error('3D renderer failed to load');

  const payload = JSON.parse(document.getElementById('payload').textContent);
  const design = payload.design;
  const members = design.members || [];
  const profiles = Object.fromEntries((design.profiles || []).map((profile) => [profile.id, profile]));
  const memberMap = Object.fromEntries(members.map((member) => [member.id, member]));
  const roleNames = { post: '立柱', 'level beam': '层横梁', 'side beam': '侧横梁' };
  const allPoints = members.flatMap((member) => [member.start, member.end]);
  const bounds = [0, 1, 2].map((axis) => [
    Math.min(...allPoints.map((point) => point[axis])),
    Math.max(...allPoints.map((point) => point[axis])),
  ]);
  const envelope = bounds.map(([minimum, maximum]) => Math.round(maximum - minimum));
  const designCenter = bounds.map(([minimum, maximum]) => (minimum + maximum) / 2);
  const worldCenter = toWorld(designCenter);
  const span = Math.hypot(envelope[0], envelope[1], envelope[2]);

  const canvas = document.getElementById('canvas');
  const renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: true,
    alpha: false,
    preserveDrawingBuffer: true,
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.08;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.setClearColor(0x202428, 1);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x202428);
  scene.fog = new THREE.FogExp2(0x202428, 0.00012);

  const camera = new THREE.PerspectiveCamera(42, 1, 5, Math.max(20000, span * 12));
  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  const clock = new THREE.Clock();

  const state = {
    yaw: -Math.PI / 4,
    pitch: 0.34,
    distance: Math.max(2500, span * 1.12),
    selected: null,
    hoverIds: new Set(),
    dragging: false,
    last: null,
    dragDistance: 0,
    renderMode: 'realistic',
    showPanels: true,
    showHardware: true,
    showDimensions: true,
    step: 0,
    needsRender: true,
  };
  const presets = {
    iso: [-Math.PI / 4, 0.34],
    front: [-Math.PI / 2, 0.02],
    side: [0, 0.02],
    top: [-Math.PI / 2, Math.PI / 2 - 0.015],
  };

  const modelRoot = new THREE.Group();
  const memberRoot = new THREE.Group();
  const panelRoot = new THREE.Group();
  const hardwareRoot = new THREE.Group();
  const dimensionRoot = new THREE.Group();
  modelRoot.add(memberRoot, panelRoot, hardwareRoot);
  scene.add(modelRoot, dimensionRoot);

  const materials = createMaterials();
  const geometryCache = new Map();
  const memberObjects = new Map();
  const pickMeshes = [];

  setupLighting();
  setupFloor();
  buildMembers();
  buildPanels();
  buildHardware();
  buildDimensions();
  setupPage();
  setupControls();
  updateCamera(true);
  requestDraw();

  function toWorld(point) {
    return new THREE.Vector3(point[0], point[2], point[1]);
  }

  function memberLength(member) {
    return Math.round(Math.hypot(
      member.end[0] - member.start[0],
      member.end[1] - member.start[1],
      member.end[2] - member.start[2],
    ));
  }

  function createMaterials() {
    return {
      aluminum: new THREE.MeshPhysicalMaterial({
        color: 0xc8ced0,
        metalness: 0.88,
        roughness: 0.23,
        clearcoat: 0.3,
        clearcoatRoughness: 0.3,
      }),
      aluminumDim: new THREE.MeshStandardMaterial({
        color: 0x737b80,
        metalness: 0.55,
        roughness: 0.48,
        transparent: true,
        opacity: 0.24,
      }),
      selected: new THREE.MeshPhysicalMaterial({
        color: 0xf08a36,
        emissive: 0x5a1f04,
        emissiveIntensity: 0.32,
        metalness: 0.68,
        roughness: 0.24,
        clearcoat: 0.35,
      }),
      structurePost: new THREE.MeshStandardMaterial({ color: 0x4c6478, metalness: 0.18, roughness: 0.56 }),
      structureBeam: new THREE.MeshStandardMaterial({ color: 0x2c86bd, metalness: 0.16, roughness: 0.52 }),
      edge: new THREE.LineBasicMaterial({ color: 0x1a2024, transparent: true, opacity: 0.34 }),
      edgeLight: new THREE.LineBasicMaterial({ color: 0xd8e0e3, transparent: true, opacity: 0.32 }),
      bracket: new THREE.MeshStandardMaterial({ color: 0x9da4a7, metalness: 0.76, roughness: 0.32 }),
      bolt: new THREE.MeshStandardMaterial({ color: 0x42494d, metalness: 0.9, roughness: 0.24 }),
      foot: new THREE.MeshStandardMaterial({ color: 0x343a3e, metalness: 0.72, roughness: 0.38 }),
      rubber: new THREE.MeshStandardMaterial({ color: 0x181a1c, metalness: 0.05, roughness: 0.86 }),
    };
  }

  function setupLighting() {
    const hemisphere = new THREE.HemisphereLight(0xeaf4ff, 0x20242a, 1.65);
    const key = new THREE.DirectionalLight(0xfff7e8, 3.4);
    key.position.set(worldCenter.x + 1500, worldCenter.y + 2600, worldCenter.z - 1900);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    key.shadow.camera.near = 20;
    key.shadow.camera.far = 9000;
    const shadowExtent = Math.max(1800, span * 0.78);
    key.shadow.camera.left = -shadowExtent;
    key.shadow.camera.right = shadowExtent;
    key.shadow.camera.top = shadowExtent;
    key.shadow.camera.bottom = -shadowExtent;
    key.shadow.bias = -0.00015;
    const fill = new THREE.DirectionalLight(0xaecbff, 1.55);
    fill.position.set(worldCenter.x - 1800, worldCenter.y + 900, worldCenter.z + 1600);
    const rim = new THREE.DirectionalLight(0xffffff, 1.15);
    rim.position.set(worldCenter.x + 400, worldCenter.y + 1400, worldCenter.z + 2100);
    scene.add(hemisphere, key, fill, rim);
  }

  function setupFloor() {
    const size = Math.max(4200, Math.ceil(Math.max(envelope[0], envelope[1]) / 500) * 2000);
    const floorY = bounds[2][0] - 44;
    const grid = new THREE.GridHelper(size, Math.round(size / 100), 0x81909b, 0x3c444a);
    grid.position.set(worldCenter.x, floorY + 0.8, worldCenter.z);
    grid.material.transparent = true;
    grid.material.opacity = 0.56;
    scene.add(grid);
    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(size, size),
      new THREE.MeshStandardMaterial({ color: 0x2b3034, metalness: 0.05, roughness: 0.86 }),
    );
    floor.rotation.x = -Math.PI / 2;
    floor.position.set(worldCenter.x, floorY, worldCenter.z);
    floor.receiveShadow = true;
    scene.add(floor);
  }

  function slotCenters(size) {
    const count = Math.max(1, Math.round(size / 30));
    return Array.from({ length: count }, (_, index) => (index - (count - 1) / 2) * 30);
  }

  function createProfileShape(width, height) {
    const halfW = width / 2;
    const halfH = height / 2;
    const slot = Math.min(8, Math.max(5.2, Math.min(width, height) * 0.27));
    const throat = slot * 0.48;
    const lip = Math.min(2.2, Math.min(width, height) * 0.075);
    const depth = Math.min(7.2, Math.min(width, height) * 0.25);
    const points = [];
    const add = (x, y) => points.push(new THREE.Vector2(x, y));
    add(-halfW, -halfH);
    slotCenters(width).forEach((center) => {
      add(center - slot / 2, -halfH);
      add(center - slot / 2, -halfH + lip);
      add(center - throat / 2, -halfH + lip);
      add(center - throat / 2, -halfH + depth);
      add(center + throat / 2, -halfH + depth);
      add(center + throat / 2, -halfH + lip);
      add(center + slot / 2, -halfH + lip);
      add(center + slot / 2, -halfH);
    });
    add(halfW, -halfH);
    slotCenters(height).forEach((center) => {
      add(halfW, center - slot / 2);
      add(halfW - lip, center - slot / 2);
      add(halfW - lip, center - throat / 2);
      add(halfW - depth, center - throat / 2);
      add(halfW - depth, center + throat / 2);
      add(halfW - lip, center + throat / 2);
      add(halfW - lip, center + slot / 2);
      add(halfW, center + slot / 2);
    });
    add(halfW, halfH);
    slotCenters(width).slice().reverse().forEach((center) => {
      add(center + slot / 2, halfH);
      add(center + slot / 2, halfH - lip);
      add(center + throat / 2, halfH - lip);
      add(center + throat / 2, halfH - depth);
      add(center - throat / 2, halfH - depth);
      add(center - throat / 2, halfH - lip);
      add(center - slot / 2, halfH - lip);
      add(center - slot / 2, halfH);
    });
    add(-halfW, halfH);
    slotCenters(height).slice().reverse().forEach((center) => {
      add(-halfW, center + slot / 2);
      add(-halfW + lip, center + slot / 2);
      add(-halfW + lip, center + throat / 2);
      add(-halfW + depth, center + throat / 2);
      add(-halfW + depth, center - throat / 2);
      add(-halfW + lip, center - throat / 2);
      add(-halfW + lip, center - slot / 2);
      add(-halfW, center - slot / 2);
    });

    const shape = new THREE.Shape(points);
    const columns = Math.max(1, Math.round(width / 30));
    const rows = Math.max(1, Math.round(height / 30));
    for (let column = 0; column < columns; column += 1) {
      for (let row = 0; row < rows; row += 1) {
        const hole = new THREE.Path();
        const x = (column - (columns - 1) / 2) * 30;
        const y = (row - (rows - 1) / 2) * 30;
        hole.absarc(x, y, Math.min(3.15, Math.min(width, height) * 0.11), 0, Math.PI * 2, true);
        shape.holes.push(hole);
      }
    }
    return shape;
  }

  function profileGeometry(profile, length) {
    const width = Number(profile.width_mm || 30);
    const height = Number(profile.height_mm || 30);
    const key = `${width}x${height}x${Math.round(length)}`;
    if (geometryCache.has(key)) return geometryCache.get(key);
    const geometry = new THREE.ExtrudeGeometry(createProfileShape(width, height), {
      depth: length,
      steps: 1,
      bevelEnabled: true,
      bevelSize: 0.38,
      bevelThickness: 0.38,
      bevelSegments: 1,
      curveSegments: 10,
    });
    geometry.translate(0, 0, -length / 2);
    geometry.computeVertexNormals();
    geometry.computeBoundingSphere();
    geometryCache.set(key, geometry);
    return geometry;
  }

  function buildMembers() {
    members.forEach((member) => {
      const profile = profiles[member.profile_id] || {};
      const start = toWorld(member.start);
      const end = toWorld(member.end);
      const direction = end.clone().sub(start);
      const length = direction.length();
      const geometry = profileGeometry(profile, length);
      const mesh = new THREE.Mesh(geometry, materials.aluminum);
      mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), direction.clone().normalize());
      mesh.position.copy(start).add(end).multiplyScalar(0.5);
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      mesh.userData.memberId = member.id;
      const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geometry, 38), materials.edge);
      edges.quaternion.copy(mesh.quaternion);
      edges.position.copy(mesh.position);
      edges.renderOrder = 2;
      memberRoot.add(mesh, edges);
      memberObjects.set(member.id, { mesh, edges, member });
      pickMeshes.push(mesh);
    });
  }

  function makeWoodTexture() {
    const textureCanvas = document.createElement('canvas');
    textureCanvas.width = textureCanvas.height = 256;
    const context = textureCanvas.getContext('2d');
    context.fillStyle = '#ccb98f';
    context.fillRect(0, 0, 256, 256);
    for (let y = 8; y < 256; y += 13) {
      context.strokeStyle = `rgba(91,61,34,${0.045 + (y % 5) * 0.006})`;
      context.beginPath();
      context.moveTo(0, y);
      context.bezierCurveTo(65, y - 4, 178, y + 5, 256, y - 1);
      context.stroke();
    }
    const texture = new THREE.CanvasTexture(textureCanvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
    texture.repeat.set(4, 2);
    return texture;
  }

  function makePegboardTexture() {
    const textureCanvas = document.createElement('canvas');
    textureCanvas.width = textureCanvas.height = 128;
    const context = textureCanvas.getContext('2d');
    context.fillStyle = '#aaa79d';
    context.fillRect(0, 0, 128, 128);
    context.fillStyle = '#3a3b39';
    for (let x = 8; x < 128; x += 16) {
      for (let y = 8; y < 128; y += 16) {
        context.beginPath();
        context.arc(x, y, 1.8, 0, Math.PI * 2);
        context.fill();
      }
    }
    const texture = new THREE.CanvasTexture(textureCanvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
    texture.repeat.set(5, 5);
    return texture;
  }

  function buildPanels() {
    const wood = new THREE.MeshStandardMaterial({
      color: 0xd4c39a,
      map: makeWoodTexture(),
      roughness: 0.73,
      metalness: 0.02,
    });
    const pegboard = new THREE.MeshStandardMaterial({
      color: 0xb8b4a9,
      map: makePegboardTexture(),
      roughness: 0.78,
      metalness: 0.03,
    });
    (design.visuals || []).filter((visual) => visual.type === 'panel' && visual.corners?.length >= 3).forEach((panel) => {
      const axes = [0, 1, 2].map((axis) => {
        const values = panel.corners.map((point) => point[axis]);
        return [Math.min(...values), Math.max(...values)];
      });
      const extents = axes.map(([minimum, maximum]) => maximum - minimum);
      const thicknessAxis = extents.indexOf(Math.min(...extents));
      const dimensions = [Math.max(10, extents[0]), Math.max(10, extents[2]), Math.max(10, extents[1])];
      dimensions[thicknessAxis === 0 ? 0 : thicknessAxis === 2 ? 1 : 2] = panel.pattern === 'pegboard' ? 8 : 16;
      const mesh = new THREE.Mesh(new THREE.BoxGeometry(...dimensions), panel.pattern === 'pegboard' ? pegboard : wood);
      mesh.position.copy(toWorld(axes.map(([minimum, maximum]) => (minimum + maximum) / 2)));
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      panelRoot.add(mesh);
    });
  }

  function uniqueHorizontalDirections(joint) {
    const origin = toWorld(joint.at);
    const directions = [];
    (joint.member_ids || []).forEach((id) => {
      const member = memberMap[id];
      if (!member) return;
      const a = toWorld(member.start);
      const b = toWorld(member.end);
      const other = a.distanceTo(origin) > b.distanceTo(origin) ? a : b;
      const direction = other.sub(origin).normalize();
      if (Math.abs(direction.y) > 0.25) return;
      if (!directions.some((known) => Math.abs(known.dot(direction)) > 0.985)) directions.push(direction);
    });
    return directions;
  }

  function createBracket(joint) {
    const directions = uniqueHorizontalDirections(joint);
    if (!directions.length) return;
    directions.slice(0, 2).forEach((direction, index) => {
      const group = new THREE.Group();
      const yaw = Math.atan2(-direction.z, direction.x);
      group.rotation.y = yaw;
      group.position.copy(toWorld(joint.at));
      group.position.y += index ? -2 : 2;
      const horizontal = new THREE.Mesh(new THREE.BoxGeometry(25, 4, 22), materials.bracket);
      horizontal.position.set(12.5, 2, 0);
      const vertical = new THREE.Mesh(new THREE.BoxGeometry(4, 25, 22), materials.bracket);
      vertical.position.set(2, 12.5, 0);
      const boltGeometry = new THREE.CylinderGeometry(3.4, 3.4, 2.8, 12);
      const boltA = new THREE.Mesh(boltGeometry, materials.bolt);
      boltA.rotation.x = Math.PI / 2;
      boltA.position.set(14, 4.3, -11.5);
      const boltB = boltA.clone();
      boltB.position.set(4.3, 15, -11.5);
      [horizontal, vertical, boltA, boltB].forEach((part) => {
        part.castShadow = true;
        part.receiveShadow = true;
      });
      group.add(horizontal, vertical, boltA, boltB);
      hardwareRoot.add(group);
    });
  }

  function createFoot(foot) {
    const origin = toWorld(foot.at);
    const stem = Number(foot.stem_mm || 35);
    const radius = Number(foot.pad_diameter_mm || 44) / 2;
    const group = new THREE.Group();
    const rod = new THREE.Mesh(new THREE.CylinderGeometry(3.8, 3.8, stem, 16), materials.bolt);
    rod.position.y = -stem / 2;
    const nut = new THREE.Mesh(new THREE.CylinderGeometry(8.5, 8.5, 6, 6), materials.bracket);
    nut.position.y = -6;
    const pad = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius * 0.94, 7, 28), materials.foot);
    pad.position.y = -stem + 1;
    const rubber = new THREE.Mesh(new THREE.CylinderGeometry(radius * 0.96, radius * 0.96, 2.4, 28), materials.rubber);
    rubber.position.y = -stem - 3.5;
    [rod, nut, pad, rubber].forEach((part) => { part.castShadow = true; part.receiveShadow = true; });
    group.add(rod, nut, pad, rubber);
    group.position.copy(origin);
    hardwareRoot.add(group);
  }

  function buildHardware() {
    (design.joints || []).forEach(createBracket);
    (design.visuals || []).filter((visual) => visual.type === 'leveling_foot').forEach(createFoot);
  }

  function makeLabelSprite(text, color = '#d6ff59') {
    const labelCanvas = document.createElement('canvas');
    const context = labelCanvas.getContext('2d');
    context.font = '700 34px Avenir Next, PingFang SC, sans-serif';
    const width = Math.ceil(context.measureText(text).width + 36);
    labelCanvas.width = Math.max(256, width);
    labelCanvas.height = 64;
    context.font = '700 34px Avenir Next, PingFang SC, sans-serif';
    context.fillStyle = 'rgba(25,29,31,.86)';
    context.fillRect(0, 0, labelCanvas.width, labelCanvas.height);
    context.strokeStyle = color;
    context.lineWidth = 2;
    context.strokeRect(1, 1, labelCanvas.width - 2, labelCanvas.height - 2);
    context.fillStyle = color;
    context.textAlign = 'center';
    context.textBaseline = 'middle';
    context.fillText(text, labelCanvas.width / 2, labelCanvas.height / 2 + 1);
    const texture = new THREE.CanvasTexture(labelCanvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false }));
    const scale = 105;
    sprite.scale.set(scale * (labelCanvas.width / labelCanvas.height), scale, 1);
    sprite.renderOrder = 20;
    return sprite;
  }

  function addDimension(start, end, label, extensionStart, extensionEnd) {
    const color = 0xc9f04a;
    const points = [toWorld(start), toWorld(end)];
    if (extensionStart && extensionEnd) {
      points.push(toWorld(extensionStart), toWorld(start), toWorld(extensionEnd), toWorld(end));
    }
    const geometry = new THREE.BufferGeometry().setFromPoints(points);
    const line = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ color, depthTest: false }));
    line.renderOrder = 19;
    dimensionRoot.add(line);
    const midpoint = toWorld(start).add(toWorld(end)).multiplyScalar(0.5);
    const sprite = makeLabelSprite(label);
    sprite.position.copy(midpoint);
    sprite.position.y += label.startsWith('高') ? 0 : 50;
    dimensionRoot.add(sprite);
  }

  function buildDimensions() {
    const [minX, maxX] = bounds[0];
    const [minY, maxY] = bounds[1];
    const [minZ, maxZ] = bounds[2];
    addDimension([minX, minY - 110, minZ - 55], [maxX, minY - 110, minZ - 55], `宽 ${envelope[0]} mm`, [minX, minY, minZ], [maxX, minY, minZ]);
    addDimension([maxX + 105, minY, minZ - 55], [maxX + 105, maxY, minZ - 55], `深 ${envelope[1]} mm`, [maxX, minY, minZ], [maxX, maxY, minZ]);
    addDimension([maxX + 105, maxY + 70, minZ], [maxX + 105, maxY + 70, maxZ], `高 ${envelope[2]} mm`, [maxX, maxY, minZ], [maxX, maxY, maxZ]);
  }

  function currentStepKind(member) {
    const horizontal = Math.abs(member.end[2] - member.start[2]) < 0.001;
    const horizontalMembers = members.filter((item) => Math.abs(item.end[2] - item.start[2]) < 0.001);
    const minZ = Math.min(...horizontalMembers.map((item) => item.start[2]));
    if (state.step === 1) return horizontal && Math.abs(member.start[2] - minZ) < 0.001;
    if (state.step === 2) return (member.role || '').toLowerCase().includes('post');
    if (state.step === 3) return horizontal && Math.abs(member.start[2] - minZ) >= 0.001;
    return false;
  }

  function applyAppearance() {
    memberObjects.forEach(({ mesh, edges, member }, id) => {
      const highlighted = state.selected === id || state.hoverIds.has(id);
      const dimmed = state.step > 0 && state.step < 4 && !currentStepKind(member);
      if (highlighted) mesh.material = materials.selected;
      else if (dimmed) mesh.material = materials.aluminumDim;
      else if (state.renderMode === 'structure') mesh.material = (member.role || '').toLowerCase().includes('post') ? materials.structurePost : materials.structureBeam;
      else mesh.material = materials.aluminum;
      edges.material = state.renderMode === 'realistic' ? materials.edge : materials.edgeLight;
      edges.visible = !dimmed || highlighted;
    });
    panelRoot.visible = state.showPanels && ![1, 2, 3].includes(state.step);
    hardwareRoot.visible = state.showHardware && ![1, 2, 3].includes(state.step);
    dimensionRoot.visible = state.showDimensions;
    requestDraw();
  }

  function setupPage() {
    document.getElementById('project-title').textContent = design.project?.name || '铝型材交互预览';
    document.getElementById('revision').textContent = `版本 ${design.project?.revision || '未标注'}`;
    document.getElementById('envelope').textContent = `${envelope[0]} × ${envelope[1]} × ${envelope[2]} mm`;
    document.getElementById('readiness').textContent = payload.readiness;
    document.getElementById('dimensions').innerHTML = [`宽 ${envelope[0]} mm`, `深 ${envelope[1]} mm`, `高 ${envelope[2]} mm`]
      .map((text) => `<span class="dimension">${text}</span>`).join('');
    renderSelection();
    renderMembers();
    renderBom();
    renderAssembly();
    renderIssues();
    applyAppearance();
  }

  function renderSelection() {
    const root = document.getElementById('selection');
    const member = members.find((item) => item.id === state.selected);
    if (!member) {
      root.innerHTML = '<p class="selection-kicker">当前选择</p><h2>检查结构</h2><p class="selection-empty">点击模型中的型材，查看长度、规格和连接信息。</p>';
      return;
    }
    const profile = profiles[member.profile_id] || {};
    const connected = (design.joints || []).filter((joint) => joint.member_ids?.includes(member.id));
    root.innerHTML = `<p class="selection-kicker">当前构件</p><h2>${member.id}</h2><dl class="facts">
      <div class="fact"><dt>目录编号</dt><dd>${profile.catalog_id || '未绑定'}</dd></div>
      <div class="fact"><dt>型材</dt><dd>${profile.part_number || `${profile.width_mm || ''}${profile.height_mm || ''}`}</dd></div>
      <div class="fact"><dt>长度</dt><dd>${memberLength(member)} mm</dd></div>
      <div class="fact"><dt>用途</dt><dd>${roleNames[member.role] || member.role || '构件'}</dd></div>
      <div class="fact"><dt>相连节点</dt><dd>${connected.length}</dd></div>
      <div class="fact"><dt>加工</dt><dd>${member.machining_status === 'not_required' ? '无需加工' : member.machining_status === 'specified' ? '已说明' : '待确认'}</dd></div>
    </dl>`;
  }

  function selectMember(id) {
    state.selected = id;
    state.hoverIds.clear();
    renderSelection();
    renderMembers();
    applyAppearance();
  }

  function renderMembers() {
    const root = document.getElementById('members-panel');
    root.innerHTML = '<p class="section-title">全部构件</p><div class="member-list">' + members.map((member) => `<button class="list-row ${state.selected === member.id ? 'active' : ''}" data-member="${member.id}"><span class="list-main"><span class="list-name">${member.id}</span><span class="list-sub">${roleNames[member.role] || member.role || '构件'} · ${profiles[member.profile_id]?.catalog_id || member.profile_id}</span></span><span class="list-value">${memberLength(member)} mm</span></button>`).join('') + '</div>';
    root.querySelectorAll('[data-member]').forEach((button) => {
      button.onclick = () => selectMember(button.dataset.member);
      button.onmouseenter = () => { state.hoverIds = new Set([button.dataset.member]); applyAppearance(); };
      button.onmouseleave = () => { state.hoverIds.clear(); applyAppearance(); };
    });
  }

  function renderBom() {
    const root = document.getElementById('bom-panel');
    root.innerHTML = '<p class="section-title">型材下料汇总</p><div class="bom-list">' + payload.bom.map((row, index) => `<button class="list-row" data-bom="${index}"><span class="list-main"><span class="list-name">${row.catalog_id} · ${row.designation}</span><span class="list-sub">${row.length_mm} mm</span></span><span class="list-value">× ${row.qty}</span></button>`).join('') + '</div>';
    root.querySelectorAll('[data-bom]').forEach((button) => {
      const ids = payload.bom[Number(button.dataset.bom)].member_ids;
      button.onmouseenter = () => { state.hoverIds = new Set(ids); applyAppearance(); };
      button.onmouseleave = () => { state.hoverIds.clear(); applyAppearance(); };
      button.onclick = () => { state.hoverIds = new Set(ids); state.selected = ids[0]; renderSelection(); applyAppearance(); };
    });
  }

  const steps = [
    { name: '完整结构', copy: '查看所有型材、板材和五金。' },
    { name: '第 1 步 · 底部框架', copy: '先拼装底部横梁，测量两条对角线并校方。' },
    { name: '第 2 步 · 立柱', copy: '安装立柱，先临时拧紧，确认垂直。' },
    { name: '第 3 步 · 各层横梁', copy: '从下往上安装横梁，每层再次核对对角线。' },
    { name: '第 4 步 · 层板与背板', copy: '安装层板、背板和展示板，确认边缘固定点。' },
    { name: '第 5 步 · 五金与复紧', copy: '安装底脚与剩余五金，空载复紧后逐步加载。' },
  ];

  function renderAssembly() {
    const step = steps[state.step];
    const root = document.getElementById('assembly-panel');
    root.innerHTML = `<div class="assembly-head"><div><p class="section-title">装配演示</p><p class="step-name">${step.name}</p></div><div class="step-controls"><button class="step-button" id="prev-step" aria-label="上一步">←</button><button class="step-button" id="next-step" aria-label="下一步">→</button></div></div><p class="step-copy">${step.copy}</p><div class="progress" aria-label="装配进度">${Array.from({ length: 5 }, (_, index) => `<span class="${index < state.step ? 'done' : ''}"></span>`).join('')}</div>`;
    root.querySelector('#prev-step').onclick = () => { state.step = Math.max(0, state.step - 1); renderAssembly(); applyAppearance(); };
    root.querySelector('#next-step').onclick = () => { state.step = Math.min(5, state.step + 1); renderAssembly(); applyAppearance(); };
  }

  function renderIssues() {
    const labels = { error: '错误', blocker: '必须确认', warning: '提醒' };
    const root = document.getElementById('issues-panel');
    root.innerHTML = '<p class="section-title">方案检查</p><div class="issue-list">' + (payload.issues.length ? payload.issues.map((issue) => `<div class="issue ${issue.severity}"><span class="issue-label">${labels[issue.severity]}</span><p>${issue.text}</p></div>`).join('') : '<p class="empty">没有发现阻断项，可以继续准备询价。</p>') + '</div>';
  }

  function setTab(tab) {
    document.querySelectorAll('.tab').forEach((button) => {
      const active = button.id === `${tab}-tab`;
      button.setAttribute('aria-selected', active);
      button.tabIndex = active ? 0 : -1;
    });
    document.querySelectorAll('.tab-panel').forEach((panel) => { panel.hidden = panel.id !== `${tab}-panel`; });
  }

  function setupControls() {
    document.querySelectorAll('.tab').forEach((button, index, all) => {
      button.onclick = () => setTab(button.id.replace('-tab', ''));
      button.onkeydown = (event) => {
        if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
        event.preventDefault();
        const next = (index + (event.key === 'ArrowRight' ? 1 : -1) + all.length) % all.length;
        all[next].focus();
        all[next].click();
      };
    });
    document.querySelectorAll('[data-view]').forEach((button) => {
      button.onclick = () => {
        [state.yaw, state.pitch] = presets[button.dataset.view];
        state.distance = Math.max(2500, span * 1.12);
        document.querySelectorAll('[data-view]').forEach((item) => item.setAttribute('aria-pressed', item === button));
        updateCamera();
      };
    });
    document.querySelectorAll('[data-mode]').forEach((button) => {
      button.onclick = () => {
        state.renderMode = button.dataset.mode;
        document.querySelectorAll('[data-mode]').forEach((item) => item.setAttribute('aria-pressed', item === button));
        document.getElementById('mode-note').hidden = state.renderMode !== 'realistic';
        applyAppearance();
      };
    });
    document.getElementById('reset-view').onclick = () => {
      [state.yaw, state.pitch] = presets.iso;
      state.distance = Math.max(2500, span * 1.12);
      updateCamera();
    };
    document.getElementById('show-panels').onchange = (event) => { state.showPanels = event.target.checked; applyAppearance(); };
    document.getElementById('show-hardware').onchange = (event) => { state.showHardware = event.target.checked; applyAppearance(); };
    document.getElementById('show-dimensions').onchange = (event) => {
      state.showDimensions = event.target.checked;
      document.getElementById('dimensions').hidden = !event.target.checked;
      applyAppearance();
    };
    canvas.addEventListener('pointerdown', (event) => {
      state.dragging = true;
      state.last = [event.clientX, event.clientY];
      state.dragDistance = 0;
      canvas.classList.add('dragging');
      canvas.setPointerCapture(event.pointerId);
    });
    canvas.addEventListener('pointermove', (event) => {
      if (!state.dragging) return;
      const dx = event.clientX - state.last[0];
      const dy = event.clientY - state.last[1];
      state.last = [event.clientX, event.clientY];
      state.dragDistance += Math.hypot(dx, dy);
      state.yaw -= dx * 0.006;
      state.pitch = THREE.MathUtils.clamp(state.pitch + dy * 0.005, -Math.PI / 2 + 0.03, Math.PI / 2 - 0.03);
      updateCamera();
    });
    const release = (event) => {
      if (!state.dragging) return;
      state.dragging = false;
      canvas.classList.remove('dragging');
      if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
    };
    canvas.addEventListener('pointerup', release);
    canvas.addEventListener('pointercancel', release);
    canvas.addEventListener('wheel', (event) => {
      event.preventDefault();
      state.distance = THREE.MathUtils.clamp(state.distance * (event.deltaY > 0 ? 1.1 : 0.9), span * 0.38, span * 4.2);
      updateCamera();
    }, { passive: false });
    canvas.addEventListener('click', (event) => {
      if (state.dragDistance > 5) return;
      const rect = canvas.getBoundingClientRect();
      pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);
      const hit = raycaster.intersectObjects(pickMeshes, false)[0];
      if (hit?.object?.userData?.memberId) selectMember(hit.object.userData.memberId);
    });
    canvas.addEventListener('keydown', (event) => {
      if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
      event.preventDefault();
      if (event.key === 'ArrowLeft') state.yaw -= 0.08;
      if (event.key === 'ArrowRight') state.yaw += 0.08;
      if (event.key === 'ArrowUp') state.pitch = Math.min(Math.PI / 2 - 0.03, state.pitch + 0.06);
      if (event.key === 'ArrowDown') state.pitch = Math.max(-Math.PI / 2 + 0.03, state.pitch - 0.06);
      updateCamera();
    });
    new ResizeObserver(resize).observe(canvas.parentElement);
  }

  function resize() {
    const rect = canvas.getBoundingClientRect();
    const width = Math.max(1, Math.round(rect.width));
    const height = Math.max(1, Math.round(rect.height));
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    requestDraw();
  }

  function updateCamera(initial = false) {
    const horizontal = Math.cos(state.pitch) * state.distance;
    camera.position.set(
      worldCenter.x + Math.cos(state.yaw) * horizontal,
      worldCenter.y + Math.sin(state.pitch) * state.distance,
      worldCenter.z + Math.sin(state.yaw) * horizontal,
    );
    camera.lookAt(worldCenter);
    if (initial) resize();
    requestDraw();
  }

  function requestDraw() {
    state.needsRender = true;
  }

  function animate() {
    requestAnimationFrame(animate);
    const elapsed = clock.getElapsedTime();
    if (state.needsRender || state.dragging || elapsed < 1.2) {
      renderer.render(scene, camera);
      state.needsRender = false;
    }
  }
  animate();
})();
