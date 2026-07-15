/* Ray Aluframe offline 3D viewer. Expects window.THREE and #payload. */
(() => {
  'use strict';

  const THREE = window.THREE;
  if (!THREE) throw new Error('3D renderer failed to load');

  const payload = JSON.parse(document.getElementById('payload').textContent);
  const design = payload.design;
  const editState = applyEditableOverrides(design);
  const members = design.members || [];
  const accessories = design.accessories || [];
  const profiles = Object.fromEntries((design.profiles || []).map((profile) => [profile.id, profile]));
  const catalogProducts = Object.fromEntries((payload.catalog?.products || []).map((product) => [product.id, product]));
  const catalogProfiles = Object.fromEntries((payload.catalog?.profiles || []).map((profile) => [profile.id, profile]));
  const defaultAngleSpec = catalogProducts['RAF-C-ANGLE-30-8'] || {
    width_mm: 30,
    arm_a_mm: 50,
    arm_b_mm: 50,
    thickness_mm: 4,
    hole_diameter_mm: 6.2,
  };
  const memberMap = Object.fromEntries(members.map((member) => [member.id, member]));
  const roleNames = { post: '立柱', 'level beam': '层横梁', 'side beam': '侧横梁' };
  const evidenceNames = { visible: '原图可见', inferred: '结构推测', confirmed: '用户确认' };
  const confidenceNames = { high: '高', medium: '中', low: '低' };
  const allPoints = members.flatMap((member) => [member.start, member.end]);
  if (editState.enabled) {
    allPoints.push([0, 0, 0], [editState.values.width_mm, editState.values.depth_mm, editState.values.height_mm]);
  }
  const bounds = [0, 1, 2].map((axis) => [
    Math.min(...allPoints.map((point) => point[axis])),
    Math.max(...allPoints.map((point) => point[axis])),
  ]);
  const envelope = bounds.map(([minimum, maximum]) => Math.round(maximum - minimum));
  const designCenter = bounds.map(([minimum, maximum]) => (minimum + maximum) / 2);
  const worldCenter = toWorld(designCenter);
  const cameraTarget = worldCenter.clone();
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

  const state = {
    yaw: Math.PI / 4,
    pitch: 0.34,
    distance: Math.max(2500, span * 1.12),
    selected: null,
    selectedHardware: null,
    hoverIds: new Set(),
    dragging: false,
    last: null,
    dragDistance: 0,
    renderMode: 'realistic',
    showPanels: true,
    showHardware: true,
    showDimensions: true,
    referenceReview: false,
    step: 0,
    needsRender: true,
  };
  const presets = {
    iso: [Math.PI / 4, 0.34],
    front: [Math.PI / 2, 0.02],
    side: [0, 0.02],
    top: [Math.PI / 2, Math.PI / 2 - 0.015],
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
  const hardwarePickMeshes = [];
  const hardwareUnits = [];
  const hardwareEntries = [];
  const hardwareMarker = createHardwareMarker();
  hardwareRoot.add(hardwareMarker);
  const steps = payload.assembly_plan?.steps?.length ? payload.assembly_plan.steps : [
    { name: '完整结构', copy: '查看所有型材、板材和五金。', check: '清单齐全。' },
    { name: '第 1 步 · 底部框架', copy: '先拼装底部横梁，测量两条对角线并校方。', check: '底框方正。' },
  ];

  setupLighting();
  setupFloor();
  buildMembers();
  buildPanels();
  buildHardware();
  buildDimensions();
  fitCameraToModel();
  setupPage();
  updateCamera(true);
  try {
    drawNow();
    animate();
  } catch (error) {
    showRenderFailure(error);
  }
  try {
    setupControls();
  } catch (error) {
    console.error('Preview controls failed to initialize', error);
  }

  function clamp(value, minimum, maximum) {
    return Math.min(maximum, Math.max(minimum, value));
  }

  function applyEditableOverrides(targetDesign) {
    const editable = targetDesign.editable;
    if (!editable?.enabled) {
      return { enabled: false, changed: false, values: {} };
    }
    if (editable.layout === 'bay_frame_v1') return applyBayFrameOverrides(targetDesign, editable);
    if (editable.layout !== 'split_cabinet_v1') return { enabled: false, changed: false, values: {} };
    const defaults = Object.fromEntries((editable.fields || []).map((field) => [field.id, Number(field.value)]));
    let overrides = {};
    try {
      const raw = new URLSearchParams(window.location.search).get('ray-edit')
        || new URLSearchParams(window.location.hash.slice(1)).get('ray-edit');
      if (raw) overrides = JSON.parse(raw);
    } catch (error) {
      console.warn('Ignored invalid preview edit values', error);
    }
    const changed = Object.keys(overrides).length > 0;
    const values = { ...defaults };
    (editable.fields || []).forEach((field) => {
      const candidate = Number(overrides[field.id]);
      if (!Number.isFinite(candidate)) return;
      values[field.id] = clamp(candidate, Number(field.min), Number(field.max));
      if (Number(field.step) === 1) values[field.id] = Math.round(values[field.id]);
    });
    if (!changed) {
      if (!targetDesign.doors?.length) materializeDoors(targetDesign, values, editable.anchors || {});
      return { enabled: true, changed: false, values, defaults };
    }

    const anchors = editable.anchors || {};
    const oldWidth = Number(defaults.width_mm);
    const oldDepth = Number(defaults.depth_mm);
    const oldHeight = Number(anchors.overall_height_mm || defaults.height_mm);
    const oldDivider = Number(anchors.divider_x_mm || defaults.divider_mm);
    const baseZ = Number(anchors.base_z_mm || 0);
    const oldCabinetTop = Number(anchors.cabinet_top_z_mm || oldHeight * 0.48);
    const rightMinimum = Number(editable.minimum_right_bay_mm || 250);
    const upperMinimum = Number(editable.minimum_upper_zone_mm || 250);
    values.divider_mm = clamp(values.divider_mm, 250, values.width_mm - rightMinimum);
    values.level_count = clamp(Math.round(values.level_count), 1, 8);
    const maximumLayerHeight = Math.max(120, (values.height_mm - upperMinimum - baseZ) / values.level_count);
    values.level_height_mm = clamp(values.level_height_mm, 120, maximumLayerHeight);
    const newCabinetTop = baseZ + values.level_count * values.level_height_mm;

    const mapX = (x) => {
      if (x < 0) return x;
      if (x <= oldDivider) return oldDivider ? x / oldDivider * values.divider_mm : x;
      const oldRight = oldWidth - oldDivider;
      return values.divider_mm + (oldRight ? (x - oldDivider) / oldRight * (values.width_mm - values.divider_mm) : 0);
    };
    const mapY = (y) => y < 0 ? y : oldDepth ? y / oldDepth * values.depth_mm : y;
    const mapZ = (z) => {
      if (z <= baseZ) return z;
      if (z <= oldCabinetTop) {
        const ratio = (z - baseZ) / Math.max(1, oldCabinetTop - baseZ);
        return baseZ + ratio * (newCabinetTop - baseZ);
      }
      const ratio = (z - oldCabinetTop) / Math.max(1, oldHeight - oldCabinetTop);
      return newCabinetTop + ratio * (values.height_mm - newCabinetTop);
    };
    const mapPoint = (point) => [mapX(Number(point[0])), mapY(Number(point[1])), mapZ(Number(point[2]))];

    targetDesign.members = (targetDesign.members || [])
      .filter((member) => member.editable_group !== editable.dynamic_member_group)
      .map((member) => ({ ...member, start: mapPoint(member.start), end: mapPoint(member.end) }));
    for (let index = 1; index < values.level_count; index += 1) {
      const z = baseZ + index * values.level_height_mm;
      [[0, 'F'], [values.depth_mm, 'R']].forEach(([y, side]) => {
        targetDesign.members.push(editableLayerMember(`EDIT-L${index}-${side}-LEFT`, '左柜层横梁', [0, y, z], [values.divider_mm, y, z], editable));
      });
      [[0, 'L'], [values.divider_mm, 'D']].forEach(([x, side]) => {
        targetDesign.members.push(editableLayerMember(`EDIT-L${index}-SIDE-${side}`, '左柜侧横梁', [x, 0, z], [x, values.depth_mm, z], editable));
      });
    }
    targetDesign.visuals = (targetDesign.visuals || []).map((visual) => {
      const next = { ...visual };
      if (visual.corners) next.corners = visual.corners.map(mapPoint);
      if (visual.at) next.at = mapPoint(visual.at);
      return next;
    });
    targetDesign.ground_points = (targetDesign.ground_points || []).map(mapPoint);
    if (targetDesign.reference_topology?.regions) {
      targetDesign.reference_topology.regions = targetDesign.reference_topology.regions.map((region) => ({
        ...region,
        x_range_mm: [mapX(region.x_range_mm[0]), mapX(region.x_range_mm[1])],
        z_range_mm: [mapZ(region.z_range_mm[0]), mapZ(region.z_range_mm[1])],
        expected_rows: region.id === 'LOWER-LEFT' ? values.level_count : region.expected_rows,
      }));
    }
    targetDesign.joints = makeEditableJoints(targetDesign.members);
    materializeDoors(targetDesign, values, { ...anchors, cabinet_top_z_mm: newCabinetTop });
    updateEditableAccessories(targetDesign, values);
    updateDoorAccessories(targetDesign);
    const originalName = String(targetDesign.project?.name || '铝型材方案');
    const updatedName = originalName.replace(/\d+\s*[×x]\s*\d+\s*[×x]\s*\d+/, `${Math.round(values.width_mm)}×${Math.round(values.depth_mm)}×${Math.round(values.height_mm)}`);
    targetDesign.project = { ...targetDesign.project, name: updatedName, revision: `${targetDesign.project?.revision || 'A'} · 页面修改` };
    return { enabled: true, changed: true, values, defaults, cabinetTop: newCabinetTop };
  }

  function editableValues(editable) {
    const defaults = Object.fromEntries((editable.fields || []).map((field) => [field.id, Number(field.value)]));
    let overrides = {};
    try {
      const raw = new URLSearchParams(window.location.search).get('ray-edit')
        || new URLSearchParams(window.location.hash.slice(1)).get('ray-edit');
      if (raw) overrides = JSON.parse(raw);
    } catch (error) {
      console.warn('Ignored invalid preview edit values', error);
    }
    const values = { ...defaults };
    (editable.fields || []).forEach((field) => {
      const candidate = Number(overrides[field.id]);
      if (!Number.isFinite(candidate)) return;
      values[field.id] = clamp(candidate, Number(field.min), Number(field.max));
      if (Number(field.step) === 1) values[field.id] = Math.round(values[field.id]);
    });
    return { defaults, values, changed: Object.keys(overrides).length > 0 };
  }

  function applyBayFrameOverrides(targetDesign, editable) {
    const parsed = editableValues(editable);
    const values = parsed.values;
    if (!parsed.changed) return { enabled: true, ...parsed };
    const width = values.width_mm;
    const depth = values.depth_mm;
    const height = values.height_mm;
    const bays = Math.max(1, Math.round(values.bay_count || 1));
    const levels = Math.max(1, Math.round(values.level_count || 1));
    const baseZ = Number(editable.base_z_mm || 0);
    const profileId = editable.profile_id;
    const xPositions = Array.from({ length: bays + 1 }, (_, index) => index * width / bays);
    const zPositions = Array.from({ length: levels + 1 }, (_, index) => baseZ + index * (height - baseZ) / levels);
    const generated = [];
    xPositions.forEach((x, xi) => [0, depth].forEach((y, yi) => generated.push(genericMember(`POST-${xi}-${yi}`, 'post', [x, y, baseZ], [x, y, height], profileId))));
    zPositions.forEach((z, zi) => {
      [0, depth].forEach((y, yi) => {
        for (let bay = 0; bay < bays; bay += 1) generated.push(genericMember(`LEVEL-${zi}-${yi}-${bay}`, 'level beam', [xPositions[bay], y, z], [xPositions[bay + 1], y, z], profileId));
      });
      xPositions.forEach((x, xi) => generated.push(genericMember(`SIDE-${zi}-${xi}`, 'side beam', [x, 0, z], [x, depth, z], profileId)));
    });
    targetDesign.members = generated;
    targetDesign.joints = makeEditableJoints(generated);
    targetDesign.ground_points = xPositions.flatMap((x) => [[x, 0, baseZ], [x, depth, baseZ]]);
    const panels = [];
    if (editable.template !== 'open_frame') {
      for (let index = 1; index < zPositions.length; index += 1) {
        const z = zPositions[index];
        panels.push({ type: 'panel', id: `SHELF-${index}`, corners: [[0, 0, z + 10], [width, 0, z + 10], [width, depth, z + 10], [0, depth, z + 10]], fill: '#caa06d', edge: '#7c5635', opacity: 0.94, evidence_basis: 'confirmed', evidence_confidence: 'high', evidence_note: '由页面设置的层数生成。' });
      }
    }
    if (editable.template === 'enclosure') {
      panels.push({ type: 'panel', id: 'BACK-PANEL', corners: [[0, depth, baseZ], [width, depth, baseZ], [width, depth, height], [0, depth, height]], fill: '#dce8e4', edge: '#7e918c', opacity: 0.55, evidence_basis: 'confirmed', evidence_confidence: 'high', evidence_note: '由机罩模板生成。' });
    }
    targetDesign.visuals = panels;
    targetDesign.doors = [];
    const loadPerLevel = Number(editable.load_per_level_kg || 0);
    targetDesign.loads = [];
    if (loadPerLevel > 0) {
      for (let zi = 1; zi < zPositions.length; zi += 1) {
        for (let bay = 0; bay < bays; bay += 1) {
          [0, 1].forEach((yi) => targetDesign.loads.push({ id: `LOAD-${zi}-${yi}-${bay}`, member_id: `LEVEL-${zi}-${yi}-${bay}`, mass_kg: loadPerLevel / bays / 2, distribution: 'uniform', support: 'simply_supported', inertia_axis: 'y', safety_factor: Number(editable.load_safety_factor || 1.5), dynamic_factor: Number(editable.dynamic_factor || 1), deflection_limit_ratio: Number(editable.deflection_limit_ratio || 200) }));
        }
      }
    }
    const anchors = editable.anchors || {};
    const oldWidth = Number(anchors.width_mm || parsed.defaults.width_mm || width);
    const oldDepth = Number(anchors.depth_mm || parsed.defaults.depth_mm || depth);
    const oldHeight = Number(anchors.height_mm || parsed.defaults.height_mm || height);
    if (targetDesign.stability?.center_of_mass_mm) {
      const oldCom = targetDesign.stability.center_of_mass_mm;
      targetDesign.stability.center_of_mass_mm = [Number(oldCom[0]) / oldWidth * width, Number(oldCom[1]) / oldDepth * depth, Number(oldCom[2]) / oldHeight * height];
      targetDesign.stability.force_height_mm = Number(targetDesign.stability.force_height_mm || oldHeight * 0.75) / oldHeight * height;
    }
    (targetDesign.accessories || []).forEach((accessory) => {
      if (accessory.category === 'foot' || accessory.category === 'caster') accessory.qty = 2 * (bays + 1);
      if (accessory.category === 'shelf') accessory.qty = editable.template === 'rack' ? levels : 1;
    });
    const bayNames = ['零', '单', '双', '三', '四', '五', '六', '七', '八'];
    const dimensionedName = String(targetDesign.project?.name || '参数化架体').replace(/\d+\s*[×x]\s*\d+\s*[×x]\s*\d+/, `${Math.round(width)}×${Math.round(depth)}×${Math.round(height)}`);
    targetDesign.project = { ...targetDesign.project, name: dimensionedName.replace(/[一二三四五六七八九十单双\d]+格/, `${bayNames[bays] || bays}格`), revision: `${targetDesign.project?.revision || 'A'} · 页面修改` };
    return { enabled: true, ...parsed };
  }

  function genericMember(id, role, start, end, profileId) {
    return { id, profile_id: profileId, role, start, end, machining_status: 'not_required', machining: [], evidence_basis: 'confirmed', evidence_confidence: 'high', evidence_note: '由通用参数编辑器生成。' };
  }

  function editableLayerMember(id, role, start, end, editable) {
    return {
      id,
      profile_id: editable.profile_id,
      role,
      start,
      end,
      editable_group: editable.dynamic_member_group,
      machining_status: 'specified',
      machining: [{ location: '随页面尺寸重算', operation: '连接方式沿用原方案，询价前复核' }],
      evidence_basis: 'confirmed',
      evidence_confidence: 'high',
      evidence_note: '由用户在预览页设置的层数和层高生成。',
    };
  }

  function pointOnMember(point, member) {
    return point.every((value, axis) => value >= Math.min(member.start[axis], member.end[axis]) - 0.01
      && value <= Math.max(member.start[axis], member.end[axis]) + 0.01)
      && point.every((value, axis) => member.start[axis] !== member.end[axis] || Math.abs(value - member.start[axis]) < 0.01);
  }

  function makeEditableJoints(currentMembers) {
    const points = new Map();
    currentMembers.forEach((member) => [member.start, member.end].forEach((point) => points.set(point.map((value) => Number(value.toFixed(4))).join('|'), point)));
    return [...points.values()].sort((a, b) => a[2] - b[2] || a[1] - b[1] || a[0] - b[0]).flatMap((point, index) => {
      const memberIds = currentMembers.filter((member) => pointOnMember(point, member)).map((member) => member.id);
      if (memberIds.length < 2) return [];
      return [{
        id: `EDIT-J${String(index + 1).padStart(2, '0')}`,
        at: point,
        member_ids: memberIds,
        connector: { description: '直角节点连接件，随页面尺寸重算', qty: Math.max(1, memberIds.length - 1) },
      }];
    });
  }

  function materializeDoors(targetDesign, values, anchors) {
    const system = targetDesign.door_system;
    if (!system) return;
    const baseZ = Number(anchors.base_z_mm || 0);
    const cabinetTop = Number(anchors.cabinet_top_z_mm || baseZ + values.level_count * values.level_height_mm);
    const common = {
      front_y_mm: Number(system.front_y_mm ?? -10),
      gap_mm: Number(system.gap_mm || 4),
      frame_profile_catalog_id: system.frame_profile_catalog_id,
      frame_profile_mm: Number(system.frame_profile_mm || 20),
      panel_catalog_id: system.panel_catalog_id,
      panel_thickness_mm: Number(system.panel_thickness_mm || 5),
      hinge_catalog_id: system.hinge_catalog_id,
      handle_catalog_id: system.handle_catalog_id,
      catch_catalog_id: system.catch_catalog_id,
      restraint_catalog_id: system.restraint_catalog_id,
      opening_clearance_mm: system.opening_clearance_mm,
      evidence_basis: 'confirmed',
      evidence_confidence: 'high',
    };
    const doors = [];
    for (let index = 0; index < values.level_count; index += 1) {
      const z0 = baseZ + index * values.level_height_mm;
      const z1 = index === values.level_count - 1 ? cabinetTop : baseZ + (index + 1) * values.level_height_mm;
      doors.push({
        ...common,
        id: `DOOR-LEFT-${index + 1}`,
        label: `左侧第 ${index + 1} 层下翻门`,
        bounds: [0, values.divider_mm, z0, z1],
        opening: system.left_opening || 'drop_down',
        hinge_edge: system.left_hinge_edge || 'bottom',
        hinge_qty: Number(system.left_hinge_qty || 2),
        handle_position: 'top_center',
        catch_position: 'top_center',
        restraint_catalog_id: system.left_restraint_catalog_id || system.restraint_catalog_id,
        opening_clearance_mm: system.left_opening_clearance_mm || system.opening_clearance_mm,
        evidence_note: '参考图显示为横向分块门；开启方向按把手在上、合页在下的下翻门表达。',
      });
    }
    doors.push({
      ...common,
      id: 'DOOR-RIGHT',
      label: '右侧通高侧开门',
      bounds: [values.divider_mm, values.width_mm, baseZ, cabinetTop],
      opening: system.right_opening || 'side_hinged',
      hinge_edge: system.right_hinge_edge || 'right',
      hinge_qty: Number(system.right_hinge_qty || 3),
      handle_position: 'left_center',
      catch_position: 'left_center',
      restraint_catalog_id: null,
      opening_clearance_mm: system.right_opening_clearance_mm || system.opening_clearance_mm,
      evidence_note: '参考图右边缘可见合页，按右侧铰接的通高侧开门表达。',
    });
    targetDesign.doors = doors;
  }

  function updateDoorAccessories(targetDesign) {
    const doors = targetDesign.doors || [];
    const counts = {
      door_panel: doors.length,
      door_hinge: doors.reduce((sum, door) => sum + Number(door.hinge_qty || 0), 0),
      door_handle: doors.length,
      door_catch: doors.length,
      door_restraint: doors.filter((door) => door.restraint_catalog_id).length,
    };
    (targetDesign.accessories || []).forEach((accessory) => {
      if (counts[accessory.category] !== undefined) accessory.qty = counts[accessory.category];
    });
  }

  function updateEditableAccessories(targetDesign, values) {
    const visualById = Object.fromEntries((targetDesign.visuals || []).map((visual) => [visual.id, visual]));
    const panelSize = (visual) => {
      if (!visual?.corners?.length) return null;
      const axes = [0, 1, 2].map((axis) => {
        const numbers = visual.corners.map((point) => Number(point[axis]));
        return Math.round(Math.max(...numbers) - Math.min(...numbers));
      });
      return axes.filter((value) => value > 1).sort((a, b) => b - a);
    };
    const worktopSize = panelSize(visualById.WORKTOP) || [Math.round(values.width_mm), Math.round(values.depth_mm)];
    const backingSize = panelSize(visualById.PEGBOARD);
    (targetDesign.accessories || []).forEach((accessory) => {
      if (accessory.category === 'worktop') accessory.description = `${worktopSize[0]}×${worktopSize[1]} mm 木质台面`;
      if (accessory.category === 'backing' && backingSize) accessory.description = `${backingSize[0]}×${backingSize[1]} mm 木质洞洞板`;
    });
  }

  function toWorld(point) {
    // Design +Y runs from the cabinet front toward the wall. Three.js cameras
    // conventionally look from +Z toward -Z, so depth maps to negative world Z.
    return new THREE.Vector3(point[0], point[2], -point[1]);
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
      evidenceInferred: new THREE.MeshPhysicalMaterial({
        color: 0x5696bd,
        metalness: 0.38,
        roughness: 0.45,
        transparent: true,
        opacity: 0.34,
      }),
      evidenceConfirmed: new THREE.MeshPhysicalMaterial({
        color: 0xe2a24f,
        metalness: 0.56,
        roughness: 0.32,
        clearcoat: 0.2,
      }),
      structurePost: new THREE.MeshStandardMaterial({ color: 0x4c6478, metalness: 0.18, roughness: 0.56 }),
      structureBeam: new THREE.MeshStandardMaterial({ color: 0x2c86bd, metalness: 0.16, roughness: 0.52 }),
      edge: new THREE.LineBasicMaterial({ color: 0x1a2024, transparent: true, opacity: 0.34 }),
      edgeLight: new THREE.LineBasicMaterial({ color: 0xd8e0e3, transparent: true, opacity: 0.32 }),
      bracket: new THREE.MeshPhysicalMaterial({
        color: 0xb9c9be,
        metalness: 0.74,
        roughness: 0.25,
        clearcoat: 0.24,
      }),
      bolt: new THREE.MeshStandardMaterial({ color: 0x42494d, metalness: 0.9, roughness: 0.24 }),
      foot: new THREE.MeshStandardMaterial({ color: 0x343a3e, metalness: 0.72, roughness: 0.38 }),
      rubber: new THREE.MeshStandardMaterial({ color: 0x181a1c, metalness: 0.05, roughness: 0.86 }),
      pick: new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false, colorWrite: false }),
    };
  }

  function accessoryQuantity(category, fallback = 0) {
    const item = accessories.find((accessory) => accessory.category === category);
    return Math.max(0, Math.round(Number(item?.qty ?? fallback)));
  }

  function registerHardware(parts, info) {
    hardwareUnits.push(info);
    parts.forEach((part) => {
      if (!part?.isMesh) return;
      part.userData.hardwareInfo = info;
      part.userData.hardwareMaterial = part.material;
      part.userData.hardwareHitbox = part.material === materials.pick;
      hardwarePickMeshes.push(part);
    });
    hardwareEntries.push({ info, parts });
  }

  function createHardwareMarker() {
    const markerCanvas = document.createElement('canvas');
    markerCanvas.width = markerCanvas.height = 128;
    const context = markerCanvas.getContext('2d');
    context.strokeStyle = '#ff7a1a';
    context.lineWidth = 10;
    context.beginPath();
    context.arc(64, 64, 45, 0, Math.PI * 2);
    context.stroke();
    context.fillStyle = '#ff7a1a';
    context.beginPath();
    context.arc(64, 64, 8, 0, Math.PI * 2);
    context.fill();
    const texture = new THREE.CanvasTexture(markerCanvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    const marker = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false }));
    marker.scale.set(105, 105, 1);
    marker.renderOrder = 30;
    marker.visible = false;
    return marker;
  }

  function updateHardwareMarker() {
    const entry = hardwareEntries.find(({ info }) => info.id === state.selectedHardware?.id);
    if (!entry || state.selectedHardware?.groupCatalogId) {
      hardwareMarker.visible = false;
      return;
    }
    scene.updateMatrixWorld(true);
    const box = new THREE.Box3();
    entry.parts.filter((part) => !part.userData.hardwareHitbox).forEach((part) => box.expandByObject(part));
    if (box.isEmpty()) {
      hardwareMarker.visible = false;
      return;
    }
    box.getCenter(hardwareMarker.position);
    hardwareMarker.visible = true;
  }

  function panelBounds(panel) {
    return [0, 1, 2].map((axis) => {
      const values = panel.corners.map((point) => Number(point[axis]));
      return [Math.min(...values), Math.max(...values)];
    });
  }

  function allocateByWeight(items, total, weightFor) {
    if (!items.length || total <= 0) return [];
    const weights = items.map((item) => Math.max(0, Number(weightFor(item)) || 0));
    const weightTotal = weights.reduce((sum, weight) => sum + weight, 0) || items.length;
    const raw = items.map((item, index) => total * (weights[index] || 1) / weightTotal);
    const counts = raw.map(Math.floor);
    let remaining = total - counts.reduce((sum, count) => sum + count, 0);
    raw.map((value, index) => ({ index, remainder: value - counts[index] }))
      .sort((a, b) => b.remainder - a.remainder || a.index - b.index)
      .forEach(({ index }) => {
        if (remaining <= 0) return;
        counts[index] += 1;
        remaining -= 1;
      });
    return counts;
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

  function makeFlutedTexture() {
    const textureCanvas = document.createElement('canvas');
    textureCanvas.width = textureCanvas.height = 128;
    const context = textureCanvas.getContext('2d');
    context.fillStyle = '#d7e1df';
    context.fillRect(0, 0, 128, 128);
    for (let x = 0; x < 128; x += 8) {
      context.fillStyle = x % 16 === 0 ? 'rgba(255,255,255,.58)' : 'rgba(92,112,111,.16)';
      context.fillRect(x, 0, 4, 128);
    }
    const texture = new THREE.CanvasTexture(textureCanvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
    texture.repeat.set(5, 2);
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
    const doorMaterials = {
      'RAF-B-PC-FLUTED-5': new THREE.MeshPhysicalMaterial({
        color: 0xdce6e2,
        map: makeFlutedTexture(),
        roughness: 0.3,
        metalness: 0.02,
        transparent: true,
        opacity: 0.58,
        transmission: 0.18,
        thickness: 5,
        side: THREE.DoubleSide,
      }),
      'RAF-B-ACRYLIC-CLEAR-5': new THREE.MeshPhysicalMaterial({
        color: 0xe8f3f3,
        roughness: 0.12,
        metalness: 0,
        transparent: true,
        opacity: 0.34,
        transmission: 0.5,
        thickness: 5,
        side: THREE.DoubleSide,
      }),
      'RAF-B-PLYWOOD-9': wood,
    };
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
    (design.doors || []).forEach((door) => buildDoor(door, doorMaterials));
  }

  function doorGeometry(door) {
    const [rawX0, rawX1, rawZ0, rawZ1] = door.bounds.map(Number);
    const gap = Number(door.gap_mm || 4);
    return {
      x0: rawX0 + gap,
      x1: rawX1 - gap,
      z0: rawZ0 + gap,
      z1: rawZ1 - gap,
      y: Number(door.front_y_mm ?? -10),
      frame: Number(door.frame_profile_mm || 20),
      thickness: Number(door.panel_thickness_mm || 5),
    };
  }

  function addDoorProfile(group, start, end, size) {
    const a = toWorld(start);
    const b = toWorld(end);
    const direction = b.clone().sub(a);
    const geometry = profileGeometry({ width_mm: size, height_mm: size }, direction.length());
    const mesh = new THREE.Mesh(geometry, materials.aluminum);
    mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), direction.clone().normalize());
    mesh.position.copy(a).add(b).multiplyScalar(0.5);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    group.add(mesh);
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geometry, 38), materials.edge);
    edges.quaternion.copy(mesh.quaternion);
    edges.position.copy(mesh.position);
    group.add(edges);
  }

  function buildDoor(door, doorMaterials) {
    const geometry = doorGeometry(door);
    const width = Math.max(20, geometry.x1 - geometry.x0);
    const height = Math.max(20, geometry.z1 - geometry.z0);
    const frame = Math.min(geometry.frame, width / 4, height / 4);
    const group = new THREE.Group();
    addDoorProfile(group, [geometry.x0, geometry.y, geometry.z0], [geometry.x1, geometry.y, geometry.z0], frame);
    addDoorProfile(group, [geometry.x0, geometry.y, geometry.z1], [geometry.x1, geometry.y, geometry.z1], frame);
    addDoorProfile(group, [geometry.x0, geometry.y, geometry.z0 + frame], [geometry.x0, geometry.y, geometry.z1 - frame], frame);
    addDoorProfile(group, [geometry.x1, geometry.y, geometry.z0 + frame], [geometry.x1, geometry.y, geometry.z1 - frame], frame);

    const panelWidth = Math.max(10, width - frame * 2);
    const panelHeight = Math.max(10, height - frame * 2);
    const panelMaterial = doorMaterials[door.panel_catalog_id] || doorMaterials['RAF-B-PC-FLUTED-5'];
    const panel = new THREE.Mesh(new THREE.BoxGeometry(panelWidth, panelHeight, geometry.thickness), panelMaterial);
    panel.position.set((geometry.x0 + geometry.x1) / 2, (geometry.z0 + geometry.z1) / 2, -geometry.y + 1);
    panel.castShadow = true;
    panel.receiveShadow = true;
    group.add(panel);
    panelRoot.add(group);
    buildDoorHardware(door, geometry);
  }

  function doorHardwareInfo(door, suffix, catalogId, name, location, specification, fasteners) {
    return {
      id: `${suffix}-${door.id}`,
      catalogId,
      name,
      location: `${door.label || door.id} · ${location}`,
      quantity: 1,
      specification,
      fasteners,
    };
  }

  function buildDoorHardware(door, geometry) {
    const hingeSpec = catalogProducts[door.hinge_catalog_id] || {};
    const handleSpec = catalogProducts[door.handle_catalog_id] || {};
    const catchSpec = catalogProducts[door.catch_catalog_id] || {};
    const hingeCount = Math.max(1, Number(door.hinge_qty || 2));
    const hingeEdgeNames = { bottom: '下边', top: '上边', left: '左边', right: '右边' };
    for (let index = 0; index < hingeCount; index += 1) {
      const fraction = (index + 1) / (hingeCount + 1);
      let x = geometry.x0 + fraction * (geometry.x1 - geometry.x0);
      let z = geometry.z0;
      if (door.hinge_edge === 'right' || door.hinge_edge === 'left') {
        x = door.hinge_edge === 'right' ? geometry.x1 : geometry.x0;
        z = geometry.z0 + fraction * (geometry.z1 - geometry.z0);
      } else if (door.hinge_edge === 'top') {
        z = geometry.z1;
      }
      const group = new THREE.Group();
      const leafA = new THREE.Mesh(new THREE.BoxGeometry(36, 18, 4), materials.bracket);
      const leafB = new THREE.Mesh(new THREE.BoxGeometry(36, 18, 4), materials.bracket);
      if (door.hinge_edge === 'right' || door.hinge_edge === 'left') {
        leafA.geometry = new THREE.BoxGeometry(18, 36, 4);
        leafB.geometry = new THREE.BoxGeometry(18, 36, 4);
        leafA.position.x = -9;
        leafB.position.x = 9;
      } else {
        leafA.position.y = -9;
        leafB.position.y = 9;
      }
      const pin = new THREE.Mesh(new THREE.CylinderGeometry(3.5, 3.5, 42, 16), materials.bolt);
      if (door.hinge_edge === 'bottom' || door.hinge_edge === 'top') pin.rotation.z = Math.PI / 2;
      const parts = [leafA, leafB, pin];
      parts.forEach((part) => { part.castShadow = true; part.receiveShadow = true; });
      const hitbox = new THREE.Mesh(new THREE.BoxGeometry(48, 48, 18), materials.pick);
      group.add(...parts, hitbox);
      group.position.set(x, z, -geometry.y + 13);
      registerHardware([...parts, hitbox], {
        ...doorHardwareInfo(
          door,
          `HINGE-${index + 1}`,
          door.hinge_catalog_id,
          hingeSpec.name || '表装合页',
          `${hingeEdgeNames[door.hinge_edge] || door.hinge_edge}合页 ${index + 1}`,
          `${hingeSpec.width_mm || 40}×${hingeSpec.height_mm || 40} mm · 叶片厚 ${hingeSpec.leaf_thickness_mm || 4} mm`,
          hingeSpec.fastener || '按门框槽系配套螺栓和槽螺母',
        ),
        id: `HINGE-${door.id}-${index + 1}`,
      });
      hardwareRoot.add(group);
    }

    const handleX = door.handle_position?.startsWith('left') ? geometry.x0 + 42 : door.handle_position?.startsWith('right') ? geometry.x1 - 42 : (geometry.x0 + geometry.x1) / 2;
    const handleZ = door.handle_position?.startsWith('top') ? geometry.z1 - 42 : (geometry.z0 + geometry.z1) / 2;
    const handle = new THREE.Mesh(new THREE.CylinderGeometry((handleSpec.diameter_mm || 25) / 2, (handleSpec.diameter_mm || 25) / 2, handleSpec.projection_mm || 22, 28), materials.bracket);
    handle.rotation.x = Math.PI / 2;
    handle.position.set(handleX, handleZ, -geometry.y + 25);
    const handleHitbox = new THREE.Mesh(new THREE.BoxGeometry(42, 42, 42), materials.pick);
    handleHitbox.position.copy(handle.position);
    registerHardware([handle, handleHitbox], doorHardwareInfo(
      door,
      'HANDLE',
      door.handle_catalog_id,
      handleSpec.name || '圆形门把手',
      '门板把手',
      `直径 ${handleSpec.diameter_mm || 25} mm · 高 ${handleSpec.projection_mm || 22} mm`,
      handleSpec.fastener || 'M4 穿板螺钉',
    ));
    hardwareRoot.add(handle, handleHitbox);

    const catchX = door.catch_position?.startsWith('left') ? geometry.x0 + 30 : door.catch_position?.startsWith('right') ? geometry.x1 - 30 : (geometry.x0 + geometry.x1) / 2;
    const catchZ = door.catch_position?.startsWith('top') ? geometry.z1 - 18 : (geometry.z0 + geometry.z1) / 2;
    const catchBody = new THREE.Mesh(new THREE.BoxGeometry(catchSpec.length_mm || 45, catchSpec.height_mm || 13, catchSpec.width_mm || 15), materials.foot);
    catchBody.position.set(catchX, catchZ, -geometry.y - 12);
    const catchPlate = new THREE.Mesh(new THREE.BoxGeometry(30, 12, 2), materials.bracket);
    catchPlate.position.set(catchX, catchZ, -geometry.y + 5);
    const catchHitbox = new THREE.Mesh(new THREE.BoxGeometry(56, 38, 38), materials.pick);
    catchHitbox.position.set(catchX, catchZ, -geometry.y);
    registerHardware([catchBody, catchPlate, catchHitbox], doorHardwareInfo(
      door,
      'CATCH',
      door.catch_catalog_id,
      catchSpec.name || '柜门磁吸',
      '闭合位置',
      `${catchSpec.length_mm || 45}×${catchSpec.width_mm || 15}×${catchSpec.height_mm || 13} mm`,
      catchSpec.fastener || '底座固定件 + 门板吸片',
    ));
    hardwareRoot.add(catchBody, catchPlate, catchHitbox);

    if (door.opening === 'drop_down' && door.restraint_catalog_id) {
      const restraintSpec = catalogProducts[door.restraint_catalog_id] || {};
      const restraintParts = [];
      [geometry.x0 + 28, geometry.x1 - 28].forEach((x, index) => {
        const start = new THREE.Vector3(x, geometry.z1 - 42, -geometry.y + 8);
        const end = new THREE.Vector3(x, geometry.z0 + 48, -geometry.y + 34);
        const direction = end.clone().sub(start);
        const chain = new THREE.Mesh(new THREE.CylinderGeometry(2, 2, direction.length(), 8), materials.bolt);
        chain.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction.clone().normalize());
        chain.position.copy(start).add(end).multiplyScalar(0.5);
        const hitbox = new THREE.Mesh(new THREE.BoxGeometry(28, Math.max(48, direction.length()), 42), materials.pick);
        hitbox.position.copy(chain.position);
        restraintParts.push(chain, hitbox);
        hardwareRoot.add(chain, hitbox);
      });
      registerHardware(restraintParts, {
        ...doorHardwareInfo(door, 'RESTRAINT', door.restraint_catalog_id, restraintSpec.name || '下翻门限位件', '左右限位件', '一套含左右两处，长度按开启角度确认', restraintSpec.purchase_note || '固定端螺栓和槽螺母'),
        id: `RESTRAINT-${door.id}`,
      });
    }
  }

  function horizontalConnections(joint) {
    const origin = toWorld(joint.at);
    const connections = [];
    (joint.member_ids || []).forEach((id) => {
      const member = memberMap[id];
      if (!member) return;
      const a = toWorld(member.start);
      const b = toWorld(member.end);
      const other = a.distanceTo(origin) > b.distanceTo(origin) ? a : b;
      const direction = other.sub(origin).normalize();
      if (Math.abs(direction.y) > 0.25) return;
      connections.push({ direction, member, profile: profiles[member.profile_id] || {} });
    });
    return connections;
  }

  function createBracket(joint) {
    const connections = horizontalConnections(joint);
    if (!connections.length) return;
    const origin = toWorld(joint.at);
    const width = Number(defaultAngleSpec.width_mm || 30);
    const armA = Number(defaultAngleSpec.arm_a_mm || 50);
    const armB = Number(defaultAngleSpec.arm_b_mm || 50);
    const thickness = Number(defaultAngleSpec.thickness_mm || 4);
    const holeRadius = Number(defaultAngleSpec.hole_diameter_mm || 6.2) / 2;
    const boltRadius = Math.max(4.2, holeRadius + 1.3);
    const ribShape = new THREE.Shape([
      new THREE.Vector2(thickness, thickness),
      new THREE.Vector2(Math.min(30, armA - 4), thickness),
      new THREE.Vector2(thickness, Math.min(30, armB - 4)),
    ]);
    const ribGeometry = new THREE.ExtrudeGeometry(ribShape, {
      depth: 2.4,
      steps: 1,
      bevelEnabled: true,
      bevelSize: 0.45,
      bevelThickness: 0.45,
      bevelSegments: 1,
    });
    connections.forEach(({ direction, profile, member }) => {
      const tallBeam = Math.max(Number(profile.width_mm || 30), Number(profile.height_mm || 30)) >= 55;
      const verticalSigns = tallBeam ? [-1, 1] : [origin.y <= bounds[2][0] + 120 ? 1 : -1];
      verticalSigns.forEach((verticalSign) => {
        const group = new THREE.Group();
        group.rotation.y = Math.atan2(-direction.z, direction.x);
        const beamHalfHeight = tallBeam ? 30 : 15;
        group.position.copy(origin)
          .addScaledVector(direction, 15)
          .add(new THREE.Vector3(0, verticalSign * beamHalfHeight, 0));
        group.scale.y = verticalSign;

        const horizontalPlate = new THREE.Mesh(
          new THREE.BoxGeometry(armA, thickness, width),
          materials.bracket,
        );
        horizontalPlate.position.set(armA / 2, thickness / 2, 0);
        const verticalPlate = new THREE.Mesh(
          new THREE.BoxGeometry(thickness, armB, width),
          materials.bracket,
        );
        verticalPlate.position.set(thickness / 2, armB / 2, 0);

        const ribA = new THREE.Mesh(ribGeometry, materials.bracket);
        ribA.position.z = width / 2 - 3;
        const ribB = ribA.clone();
        ribB.position.z = -width / 2 + 0.6;

        const washerGeometry = new THREE.CylinderGeometry(boltRadius + 1.5, boltRadius + 1.5, 1.2, 20);
        const boltGeometry = new THREE.CylinderGeometry(boltRadius, boltRadius, 3.2, 16);
        const horizontalWasher = new THREE.Mesh(washerGeometry, materials.bracket);
        horizontalWasher.position.set(Math.min(31, armA * 0.62), thickness + 0.6, 0);
        const horizontalBolt = new THREE.Mesh(boltGeometry, materials.bolt);
        horizontalBolt.position.set(horizontalWasher.position.x, thickness + 2.1, 0);
        const verticalWasher = new THREE.Mesh(washerGeometry, materials.bracket);
        verticalWasher.rotation.z = Math.PI / 2;
        verticalWasher.position.set(thickness + 0.6, Math.min(31, armB * 0.62), 0);
        const verticalBolt = new THREE.Mesh(boltGeometry, materials.bolt);
        verticalBolt.rotation.z = Math.PI / 2;
        verticalBolt.position.set(thickness + 2.1, verticalWasher.position.y, 0);

        const horizontalNut = new THREE.Mesh(new THREE.BoxGeometry(15, 2.6, 8), materials.bolt);
        horizontalNut.position.set(horizontalWasher.position.x, -1.8, 0);
        const verticalNut = new THREE.Mesh(new THREE.BoxGeometry(2.6, 15, 8), materials.bolt);
        verticalNut.position.set(-1.8, verticalWasher.position.y, 0);

        const parts = [horizontalPlate, verticalPlate, ribA, ribB, horizontalWasher, horizontalBolt, verticalWasher, verticalBolt, horizontalNut, verticalNut];
        parts.forEach((part) => {
          part.castShadow = true;
          part.receiveShadow = true;
        });
        const hitbox = new THREE.Mesh(new THREE.BoxGeometry(Math.max(54, armA), Math.max(54, armB), width + 8), materials.pick);
        hitbox.position.set(armA / 2, armB / 2, 0);
        group.add(...parts, hitbox);
        group.userData = {
          kind: 'connector',
          jointId: joint.id,
          memberId: member.id,
          catalogId: 'RAF-C-ANGLE-30-8',
        };
        registerHardware([...parts, hitbox], {
          id: `ANGLE-${joint.id}-${member.id}-${verticalSign}`,
          catalogId: 'RAF-C-ANGLE-30-8',
          name: '30 系槽 8 外露直角角码',
          location: `节点 ${joint.id} · ${member.id}`,
          quantity: 1,
          specification: '30 mm 宽 · 50×50 mm · 厚 4 mm · 孔径 6.2 mm',
          fasteners: '每只：M6×12 螺栓 2 + 槽8 M6后装螺母 2',
        });
        hardwareRoot.add(group);
      });
    });
  }

  function createShelfBracket(panel, x, designY, inwardSign, index) {
    const axes = panelBounds(panel);
    const shelfY = (axes[2][0] + axes[2][1]) / 2;
    const worldInward = -inwardSign;
    const group = new THREE.Group();
    group.position.set(x, shelfY - 9.5, -designY + worldInward * 16);

    const horizontalPlate = new THREE.Mesh(new THREE.BoxGeometry(22, 3, 18), materials.bracket);
    horizontalPlate.position.z = worldInward * 8;
    const verticalPlate = new THREE.Mesh(new THREE.BoxGeometry(22, 18, 3), materials.bracket);
    verticalPlate.position.set(0, -7.5, 0);

    const boardWasher = new THREE.Mesh(new THREE.CylinderGeometry(4.4, 4.4, 1, 16), materials.bracket);
    boardWasher.position.set(0, 2, worldInward * 8);
    const boardScrew = new THREE.Mesh(new THREE.CylinderGeometry(2.8, 2.8, 3.2, 12), materials.bolt);
    boardScrew.position.set(0, 3.4, worldInward * 8);

    const profileWasher = new THREE.Mesh(new THREE.CylinderGeometry(5.4, 5.4, 1.1, 18), materials.bracket);
    profileWasher.rotation.x = Math.PI / 2;
    profileWasher.position.set(0, -7.5, worldInward * 2.1);
    const profileBolt = new THREE.Mesh(new THREE.CylinderGeometry(4.2, 4.2, 3.2, 16), materials.bolt);
    profileBolt.rotation.x = Math.PI / 2;
    profileBolt.position.set(0, -7.5, worldInward * 3.7);
    const tNut = new THREE.Mesh(new THREE.BoxGeometry(15, 8, 2.8), materials.bolt);
    tNut.position.set(0, -7.5, -worldInward * 2.6);

    const parts = [horizontalPlate, verticalPlate, boardWasher, boardScrew, profileWasher, profileBolt, tNut];
    parts.forEach((part) => { part.castShadow = true; part.receiveShadow = true; });
    const hitbox = new THREE.Mesh(new THREE.BoxGeometry(30, 28, 34), materials.pick);
    hitbox.position.set(0, -4, worldInward * 5);
    group.add(...parts, hitbox);
    registerHardware([...parts, hitbox], {
      id: `SHELF-BRACKET-${panel.id}-${index + 1}`,
      catalogId: 'RAF-P-SHELF-BRACKET-30',
      name: '30 系层板底部小角码',
      location: `${panel.id} · 固定点 ${index + 1}`,
      quantity: 1,
      specification: '适配 30 系槽 8；木层板厚度至少 15 mm',
      fasteners: 'M6×12 + 槽8 M6后装螺母；4×12 木螺钉',
    });
    hardwareRoot.add(group);
  }

  function buildShelfBrackets() {
    const shelves = (design.visuals || []).filter((visual) => {
      if (visual.type !== 'panel' || !visual.corners?.length) return false;
      const axes = panelBounds(visual);
      return axes[2][1] - axes[2][0] < 1;
    });
    const target = accessoryQuantity('shelf_fastener', shelves.length * 4);
    const counts = allocateByWeight(shelves, target, () => 1);
    shelves.forEach((panel, panelIndex) => {
      const axes = panelBounds(panel);
      const count = counts[panelIndex] || 0;
      const frontCount = Math.ceil(count / 2);
      const rearCount = Math.floor(count / 2);
      const addSide = (sideCount, designY, inwardSign, offset) => {
        for (let index = 0; index < sideCount; index += 1) {
          const fraction = (index + 1) / (sideCount + 1);
          const x = axes[0][0] + 45 + fraction * Math.max(0, axes[0][1] - axes[0][0] - 90);
          createShelfBracket(panel, x, designY, inwardSign, offset + index);
        }
      };
      addSide(frontCount, axes[1][0], 1, 0);
      addSide(rearCount, axes[1][1], -1, frontCount);
    });
  }

  function perimeterPoint(axes, fraction) {
    const width = axes[0][1] - axes[0][0];
    const height = axes[2][1] - axes[2][0];
    const perimeter = 2 * (width + height);
    let distance = ((fraction % 1) + 1) % 1 * perimeter;
    if (distance < width) return { x: axes[0][0] + distance, z: axes[2][0], edge: 'bottom' };
    distance -= width;
    if (distance < height) return { x: axes[0][1], z: axes[2][0] + distance, edge: 'right' };
    distance -= height;
    if (distance < width) return { x: axes[0][1] - distance, z: axes[2][1], edge: 'top' };
    distance -= width;
    return { x: axes[0][0], z: axes[2][1] - distance, edge: 'left' };
  }

  function createPanelClip(panel, point, designY, index) {
    const group = new THREE.Group();
    group.position.set(point.x, point.z, -designY + 8);
    if (point.edge === 'left' || point.edge === 'right') group.rotation.z = Math.PI / 2;

    const plate = new THREE.Mesh(new THREE.BoxGeometry(24, 20, 3), materials.bracket);
    const returnLip = new THREE.Mesh(new THREE.BoxGeometry(5, 20, 7), materials.bracket);
    returnLip.position.set(point.edge === 'top' || point.edge === 'right' ? -9.5 : 9.5, 0, -3.2);
    const washer = new THREE.Mesh(new THREE.CylinderGeometry(5.4, 5.4, 1.1, 18), materials.bracket);
    washer.rotation.x = Math.PI / 2;
    washer.position.z = 2.1;
    const bolt = new THREE.Mesh(new THREE.CylinderGeometry(4.2, 4.2, 3.2, 16), materials.bolt);
    bolt.rotation.x = Math.PI / 2;
    bolt.position.z = 3.7;
    const tNut = new THREE.Mesh(new THREE.BoxGeometry(15, 8, 2.8), materials.bolt);
    tNut.position.z = -2.7;

    const parts = [plate, returnLip, washer, bolt, tNut];
    parts.forEach((part) => { part.castShadow = true; part.receiveShadow = true; });
    const hitbox = new THREE.Mesh(new THREE.BoxGeometry(32, 28, 18), materials.pick);
    group.add(...parts, hitbox);
    registerHardware([...parts, hitbox], {
      id: `PANEL-CLIP-${panel.id}-${index + 1}`,
      catalogId: 'RAF-P-PANEL-CLIP-30',
      name: '30 系后装面板夹',
      location: `${panel.id} · ${point.edge} 边固定点 ${index + 1}`,
      quantity: 1,
      specification: '适配 30 系槽 8；夹持板厚 3–10 mm',
      fasteners: 'M6×12 + 槽8 M6后装螺母；较厚背板需另选固定方式',
    });
    hardwareRoot.add(group);
  }

  function buildPanelClips() {
    const panels = (design.visuals || []).filter((visual) => {
      if (visual.type !== 'panel' || !visual.corners?.length) return false;
      const axes = panelBounds(visual);
      return axes[1][1] - axes[1][0] < 1 && axes[2][1] - axes[2][0] > 1;
    });
    const target = accessoryQuantity('panel_fastener', panels.length * 8);
    const counts = allocateByWeight(panels, target, (panel) => {
      const axes = panelBounds(panel);
      return 2 * ((axes[0][1] - axes[0][0]) + (axes[2][1] - axes[2][0]));
    });
    panels.forEach((panel, panelIndex) => {
      const axes = panelBounds(panel);
      const count = counts[panelIndex] || 0;
      const designY = (axes[1][0] + axes[1][1]) / 2;
      for (let index = 0; index < count; index += 1) {
        createPanelClip(panel, perimeterPoint(axes, (index + 0.5) / count), designY, index);
      }
    });
  }

  function createFoot(foot) {
    const origin = toWorld(foot.at);
    const stem = Number(foot.stem_mm || 35);
    const radius = Number(catalogProducts['RAF-A-FOOT-PLATE-30']?.foot_diameter_mm || foot.pad_diameter_mm || 50) / 2;
    const group = new THREE.Group();
    const plate = new THREE.Mesh(new THREE.BoxGeometry(50, 5, 50), materials.bracket);
    plate.position.y = -2.5;
    const rod = new THREE.Mesh(new THREE.CylinderGeometry(3.8, 3.8, stem, 16), materials.bolt);
    rod.position.y = -stem / 2 - 4;
    const nut = new THREE.Mesh(new THREE.CylinderGeometry(8.5, 8.5, 6, 6), materials.bracket);
    nut.position.y = -9;
    const pad = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius * 0.94, 7, 28), materials.foot);
    pad.position.y = -stem - 3;
    const rubber = new THREE.Mesh(new THREE.CylinderGeometry(radius * 0.96, radius * 0.96, 2.4, 28), materials.rubber);
    rubber.position.y = -stem - 7.7;
    const plateBolts = [[-15, -15], [-15, 15], [15, -15], [15, 15]].map(([x, z]) => {
      const bolt = new THREE.Mesh(new THREE.CylinderGeometry(3.7, 3.7, 2.2, 14), materials.bolt);
      bolt.position.set(x, 0.8, z);
      return bolt;
    });
    const parts = [plate, rod, nut, pad, rubber, ...plateBolts];
    parts.forEach((part) => { part.castShadow = true; part.receiveShadow = true; });
    const hitbox = new THREE.Mesh(new THREE.BoxGeometry(58, stem + 18, 58), materials.pick);
    hitbox.position.y = -(stem + 8) / 2;
    group.add(...parts, hitbox);
    group.position.copy(origin);
    registerHardware([...parts, hitbox], {
      id: `FOOT-${foot.at.join('-')}`,
      catalogId: 'RAF-A-FOOT-PLATE-30',
      name: '30 系底脚连接板 + M10 调节脚',
      location: `立柱底部 ${foot.at.join(' / ')} mm`,
      quantity: 1,
      specification: `M10 调节杆 · 脚垫直径 ${radius * 2} mm`,
      fasteners: '底脚连接板安装方式需随供应商套装确认',
    });
    hardwareRoot.add(group);
  }

  function buildHardware() {
    (design.joints || []).forEach(createBracket);
    buildShelfBrackets();
    buildPanelClips();
    (design.visuals || []).filter((visual) => visual.type === 'leveling_foot').forEach(createFoot);
    const hardwareCounts = hardwareUnits.reduce((counts, item) => {
      counts[item.catalogId] = (counts[item.catalogId] || 0) + Number(item.quantity || 1);
      return counts;
    }, {});
    window.__rayAluframeDebug = { hardwareUnits, hardwareCounts };
    canvas.dataset.hardwareCounts = JSON.stringify(hardwareCounts);
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

  function fitCameraToModel() {
    modelRoot.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(modelRoot);
    if (box.isEmpty()) return;
    const sphere = box.getBoundingSphere(new THREE.Sphere());
    cameraTarget.copy(sphere.center);
    const halfFov = THREE.MathUtils.degToRad(camera.fov * 0.5);
    state.distance = Math.max(1200, (sphere.radius / Math.sin(halfFov)) * 1.18);
  }

  function applyAppearance() {
    memberObjects.forEach(({ mesh, edges, member }, id) => {
      const highlighted = state.selected === id || state.hoverIds.has(id);
      const dimmed = state.step > 0 && state.step < 4 && !currentStepKind(member);
      if (highlighted) mesh.material = materials.selected;
      else if (dimmed) mesh.material = materials.aluminumDim;
      else if (state.referenceReview && member.evidence_basis === 'inferred') mesh.material = materials.evidenceInferred;
      else if (state.referenceReview && member.evidence_basis === 'confirmed') mesh.material = materials.evidenceConfirmed;
      else if (state.renderMode === 'structure') mesh.material = (member.role || '').toLowerCase().includes('post') ? materials.structurePost : materials.structureBeam;
      else mesh.material = materials.aluminum;
      edges.material = state.renderMode === 'realistic' ? materials.edge : materials.edgeLight;
      edges.visible = !dimmed || highlighted;
    });
    hardwareEntries.forEach(({ info, parts }) => {
      const selected = state.selectedHardware?.id === info.id && !state.selectedHardware?.groupCatalogId;
      parts.forEach((part) => {
        if (!part?.isMesh || part.userData.hardwareHitbox) return;
        part.material = selected ? materials.selected : part.userData.hardwareMaterial;
      });
    });
    updateHardwareMarker();
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
    renderHardwareList();
    renderBom();
    renderQuote();
    renderAssembly();
    renderIssues();
    setupEditor();
    applyAppearance();
  }

  function renderSelection() {
    const root = document.getElementById('selection');
    if (state.selectedHardware) {
      const hardware = state.selectedHardware;
      const locationContent = hardware.groupCatalogId
        ? `<button class="inline-action" id="show-hardware-locations">查看 ${hardware.quantity} 个安装位置</button>`
        : `${hardware.location}<span class="location-note">已在模型中用橙色标出</span>`;
      root.innerHTML = `<p class="selection-kicker">当前五金</p><h2>${hardware.name}</h2><dl class="facts">
        <div class="fact"><dt>目录编号</dt><dd>${hardware.catalogId}</dd></div>
        <div class="fact"><dt>所在位置</dt><dd>${locationContent}</dd></div>
        <div class="fact"><dt>当前件数</dt><dd>${hardware.quantity}</dd></div>
        <div class="fact"><dt>适配规格</dt><dd>${hardware.specification}</dd></div>
        <div class="fact"><dt>紧固件</dt><dd>${hardware.fasteners}</dd></div>
      </dl>`;
      const locationButton = root.querySelector('#show-hardware-locations');
      if (locationButton) {
        locationButton.onclick = () => {
          setTab('hardware');
          renderHardwareList();
          requestAnimationFrame(() => document.querySelector('.hardware-locations')?.scrollIntoView({ block: 'start', behavior: 'smooth' }));
        };
      }
      return;
    }
    const member = members.find((item) => item.id === state.selected);
    if (!member) {
      root.innerHTML = '<p class="selection-kicker">当前选择</p><h2>检查结构</h2><p class="selection-empty">点击模型中的型材或五金，查看对应规格和安装信息。</p>';
      return;
    }
    const profile = profiles[member.profile_id] || {};
    const connected = (design.joints || []).filter((joint) => joint.member_ids?.includes(member.id));
    const evidence = evidenceNames[member.evidence_basis] || '未标注';
    root.innerHTML = `<p class="selection-kicker">当前构件</p><h2>${member.id}</h2><dl class="facts">
      <div class="fact"><dt>目录编号</dt><dd>${profile.catalog_id || '未绑定'}</dd></div>
      <div class="fact"><dt>型材</dt><dd>${profile.part_number || `${profile.width_mm || ''}${profile.height_mm || ''}`}</dd></div>
      <div class="fact"><dt>长度</dt><dd>${memberLength(member)} mm</dd></div>
      <div class="fact"><dt>用途</dt><dd>${roleNames[member.role] || member.role || '构件'}</dd></div>
      <div class="fact"><dt>相连节点</dt><dd>${connected.length}</dd></div>
      <div class="fact"><dt>加工</dt><dd>${member.machining_status === 'not_required' ? '无需加工' : member.machining_status === 'specified' ? '已说明' : '待确认'}</dd></div>
      <div class="fact"><dt>识别依据</dt><dd>${evidence}</dd></div>
      <div class="fact"><dt>置信度</dt><dd>${confidenceNames[member.evidence_confidence] || member.evidence_confidence || '未标注'}</dd></div>
      ${member.evidence_note ? `<div class="fact" style="grid-column:1/-1"><dt>依据说明</dt><dd>${member.evidence_note}</dd></div>` : ''}
    </dl>`;
  }

  function selectMember(id) {
    state.selected = id;
    state.selectedHardware = null;
    hardwareMarker.visible = false;
    state.hoverIds.clear();
    renderSelection();
    renderMembers();
    applyAppearance();
  }

  function selectHardware(info) {
    state.selected = null;
    state.selectedHardware = info;
    state.showHardware = true;
    document.getElementById('show-hardware').checked = true;
    if ([1, 2, 3].includes(state.step)) {
      state.step = 0;
      renderAssembly();
    }
    state.hoverIds.clear();
    renderSelection();
    renderMembers();
    renderHardwareList();
    applyAppearance();
  }

  function renderMembers() {
    const root = document.getElementById('members-panel');
    const badge = (member) => member.evidence_basis && evidenceNames[member.evidence_basis]
      ? `<span class="evidence-badge evidence-${member.evidence_basis}">${evidenceNames[member.evidence_basis]}</span>` : '';
    const legend = design.reference_image ? `<div class="evidence-legend"><span class="evidence-badge evidence-visible">原图可见</span><span class="evidence-badge evidence-inferred">结构推测</span><span class="evidence-badge evidence-confirmed">用户确认</span></div>` : '';
    root.innerHTML = '<p class="section-title">全部构件</p>' + legend + '<div class="member-list">' + members.map((member) => `<button class="list-row ${state.selected === member.id ? 'active' : ''}" data-member="${member.id}"><span class="list-main"><span class="list-name">${member.id}${badge(member)}</span><span class="list-sub">${roleNames[member.role] || member.role || '构件'} · ${profiles[member.profile_id]?.catalog_id || member.profile_id}</span></span><span class="list-value">${memberLength(member)} mm</span></button>`).join('') + '</div>';
    root.querySelectorAll('[data-member]').forEach((button) => {
      button.onclick = () => selectMember(button.dataset.member);
      button.onmouseenter = () => { state.hoverIds = new Set([button.dataset.member]); applyAppearance(); };
      button.onmouseleave = () => { state.hoverIds.clear(); applyAppearance(); };
    });
  }

  function renderHardwareList() {
    const root = document.getElementById('hardware-panel');
    const groups = new Map();
    hardwareUnits.forEach((item) => {
      if (!groups.has(item.catalogId)) groups.set(item.catalogId, { item, count: 0 });
      groups.get(item.catalogId).count += Number(item.quantity || 1);
    });
    const rows = [...groups.values()];
    const countFor = (catalogId) => groups.get(catalogId)?.count || 0;
    const mainAngles = countFor('RAF-C-ANGLE-30-8');
    const shelfBrackets = countFor('RAF-P-SHELF-BRACKET-30');
    const panelClips = countFor('RAF-P-PANEL-CLIP-30');
    const m6Total = mainAngles * 2 + shelfBrackets + panelClips;
    const hardwareFasteners = new Map();
    groups.forEach(({ item, count }, catalogId) => {
      const product = catalogProducts[catalogId] || {};
      (product.fastener_components || []).forEach((component) => {
        const productId = component.product_id;
        hardwareFasteners.set(productId, (hardwareFasteners.get(productId) || 0) + count * Number(component.qty || 1));
      });
    });
    const hardwareFastenerRows = [...hardwareFasteners.entries()].map(([productId, count]) => `<div class="list-row"><span class="list-main"><span class="list-name">${catalogProducts[productId]?.name || productId}</span><span class="list-sub">门板和附件五金配套</span></span><span class="list-value">× ${count}</span></div>`).join('');
    const fastenerSummary = `<p class="section-title" style="margin-top:22px">紧固件合计</p><div class="bom-list">
      <div class="list-row"><span class="list-main"><span class="list-name">M6×12 内六角螺栓</span><span class="list-sub">主角码、层板角码和面板夹</span></span><span class="list-value">× ${m6Total}</span></div>
      <div class="list-row"><span class="list-main"><span class="list-name">槽 8 M6 后装螺母</span><span class="list-sub">与 M6×12 一一配套</span></span><span class="list-value">× ${m6Total}</span></div>
      <div class="list-row"><span class="list-main"><span class="list-name">4×12 木螺钉</span><span class="list-sub">每个层板小角码 1 颗</span></span><span class="list-value">× ${shelfBrackets}</span></div>
      ${hardwareFastenerRows}
    </div>`;
    const selectedCatalogId = state.selectedHardware?.groupCatalogId || state.selectedHardware?.catalogId;
    const selectedUnits = selectedCatalogId ? hardwareUnits.filter((item) => item.catalogId === selectedCatalogId) : [];
    const locationSection = selectedUnits.length ? `<section class="hardware-locations"><p class="section-title">安装位置 · ${selectedUnits[0].name}</p><div class="member-list">${selectedUnits.map((item, index) => `<button class="list-row ${state.selectedHardware?.id === item.id && !state.selectedHardware?.groupCatalogId ? 'active' : ''}" data-hardware-location="${index}"><span class="list-main"><span class="list-name">位置 ${index + 1}</span><span class="list-sub">${item.location}</span></span><span class="list-value">定位</span></button>`).join('')}</div></section>` : '';
    root.innerHTML = '<p class="section-title">当前方案五金</p><div class="bom-list">' + rows.map(({ item, count }, index) => `<button class="list-row ${selectedCatalogId === item.catalogId ? 'active' : ''}" data-hardware="${index}"><span class="list-main"><span class="list-name">${item.name}</span><span class="list-sub">${item.catalogId} · ${item.fasteners}</span></span><span class="list-value">× ${count}</span></button>`).join('') + '</div>' + locationSection + fastenerSummary;
    root.querySelectorAll('[data-hardware]').forEach((button) => {
      button.onclick = () => {
        const group = rows[Number(button.dataset.hardware)];
        selectHardware({
          ...group.item,
          id: `GROUP-${group.item.catalogId}`,
          quantity: group.count,
          location: `全架共 ${group.count} 处`,
          groupCatalogId: group.item.catalogId,
        });
      };
    });
    root.querySelectorAll('[data-hardware-location]').forEach((button) => {
      button.onclick = () => selectHardware({ ...selectedUnits[Number(button.dataset.hardwareLocation)], groupCatalogId: null });
    });
  }

  function renderBom() {
    const root = document.getElementById('bom-panel');
    const bom = currentBomRows();
    const doorRows = doorCutRows();
    const doorFrameRows = doorRows.frame.map((row) => `<div class="list-row"><span class="list-main"><span class="list-name">${row.catalogId} · 门框型材</span><span class="list-sub">${row.length} mm · ${row.note}</span></span><span class="list-value">× ${row.qty}</span></div>`).join('');
    const panelRows = doorRows.panels.map((row) => `<div class="list-row"><span class="list-main"><span class="list-name">${row.label}</span><span class="list-sub">${row.catalogId} · ${row.width}×${row.height}×${row.thickness} mm · ${row.opening} · 四周缝 ${row.gap} mm · 合页 ${row.hinges} 只</span></span><span class="list-value">× 1</span></div>`).join('');
    const accessoryRows = (design.accessories || []).map((item) => `<div class="list-row"><span class="list-main"><span class="list-name">${item.description || item.category}</span><span class="list-sub">${item.catalog_id || item.catalog_kit_id || '按尺寸制作'}</span></span><span class="list-value">× ${item.qty || 0}</span></div>`).join('');
    root.innerHTML = '<p class="section-title">主体型材下料</p><div class="bom-list">' + bom.map((row, index) => `<button class="list-row" data-bom="${index}"><span class="list-main"><span class="list-name">${row.catalog_id} · ${row.designation}</span><span class="list-sub">${row.length_mm} mm</span></span><span class="list-value">× ${row.qty}</span></button>`).join('') + '</div>'
      + (doorFrameRows ? `<p class="section-title bom-section">门框型材下料</p><div class="bom-list">${doorFrameRows}</div>` : '')
      + (panelRows ? `<p class="section-title bom-section">门板实际尺寸</p><div class="bom-list">${panelRows}</div>` : '')
      + `<p class="section-title bom-section">附件与板材</p><div class="bom-list">${accessoryRows}</div>`;
    root.querySelectorAll('[data-bom]').forEach((button) => {
      const ids = bom[Number(button.dataset.bom)].member_ids;
      button.onmouseenter = () => { state.hoverIds = new Set(ids); applyAppearance(); };
      button.onmouseleave = () => { state.hoverIds.clear(); applyAppearance(); };
      button.onclick = () => {
        state.hoverIds = new Set(ids);
        state.selected = ids[0];
        state.selectedHardware = null;
        renderSelection();
        applyAppearance();
      };
    });
  }

  function currentBomRows() {
    const groups = new Map();
    members.forEach((member) => {
      const length = memberLength(member);
      const key = `${member.profile_id}|${length}`;
      if (!groups.has(key)) groups.set(key, { profile_id: member.profile_id, length_mm: length, qty: 0, member_ids: [] });
      const row = groups.get(key);
      row.qty += 1;
      row.member_ids.push(member.id);
    });
    return [...groups.values()].sort((a, b) => a.profile_id.localeCompare(b.profile_id) || a.length_mm - b.length_mm).map((row) => {
      const profile = profiles[row.profile_id] || {};
      return {
        ...row,
        catalog_id: profile.catalog_id || '未绑定',
        designation: profile.part_number || profile.designation || `${profile.width_mm || ''}${profile.height_mm || ''}`,
      };
    });
  }

  function doorCutRows() {
    const frameGroups = new Map();
    const panels = [];
    (design.doors || []).forEach((door) => {
      const geometry = doorGeometry(door);
      const frame = Number(door.frame_profile_mm || 20);
      const width = Math.round(geometry.x1 - geometry.x0);
      const height = Math.round(geometry.z1 - geometry.z0);
      [
        { length: width, qty: 2, note: `${door.label} 上下边` },
        { length: Math.max(10, height - frame * 2), qty: 2, note: `${door.label} 左右边，直角拼接` },
      ].forEach((entry) => {
        const key = `${door.frame_profile_catalog_id}|${entry.length}`;
        if (!frameGroups.has(key)) frameGroups.set(key, { catalogId: door.frame_profile_catalog_id, length: entry.length, qty: 0, notes: [] });
        const row = frameGroups.get(key);
        row.qty += entry.qty;
        row.notes.push(entry.note);
      });
      panels.push({
        label: door.label,
        catalogId: door.panel_catalog_id,
        width: Math.max(10, width - frame * 2),
        height: Math.max(10, height - frame * 2),
        thickness: Number(door.panel_thickness_mm || 5),
        opening: door.opening === 'drop_down' ? '向下翻开' : door.hinge_edge === 'right' ? '右侧铰接' : '侧向开启',
        gap: Number(door.gap_mm || 4),
        hinges: Number(door.hinge_qty || 0),
      });
    });
    return {
      frame: [...frameGroups.values()].map((row) => ({ ...row, note: row.notes.join('；') })),
      panels,
    };
  }

  function renderAssembly() {
    const step = steps[state.step];
    const root = document.getElementById('assembly-panel');
    root.innerHTML = `<div class="assembly-head"><div><p class="section-title">装配演示</p><p class="step-name">${step.name}</p></div><div class="step-controls"><button class="step-button" id="prev-step" aria-label="上一步">←</button><button class="step-button" id="next-step" aria-label="下一步">→</button></div></div><p class="step-copy">${step.copy}</p>${step.check ? `<div class="issue"><span class="issue-label">这一步要核对</span><p>${step.check}</p></div>` : ''}<div class="progress" aria-label="装配进度">${Array.from({ length: Math.max(1, steps.length - 1) }, (_, index) => `<span class="${index < state.step ? 'done' : ''}"></span>`).join('')}</div>`;
    root.querySelector('#prev-step').onclick = () => { state.step = Math.max(0, state.step - 1); renderAssembly(); applyAppearance(); };
    root.querySelector('#next-step').onclick = () => { state.step = Math.min(steps.length - 1, state.step + 1); renderAssembly(); applyAppearance(); };
  }

  function renderQuote() {
    const root = document.getElementById('quote-panel');
    const quote = runtimeQuote();
    const money = (range) => range ? `¥${Number(range[0]).toFixed(2)}–¥${Number(range[1]).toFixed(2)}` : '缺少价格';
    const rows = (quote.rows || []).map((row) => `<div class="list-row"><span class="list-main"><span class="list-name">${row.item}</span><span class="list-sub">${row.section} · ${row.catalog_id || '按规格制作'} · ${row.qty} ${row.unit} · ${row.price_source}</span></span><span class="list-value">${money(row.amount_range_cny)}</span></div>`).join('');
    const unknown = (quote.unknown_items || []).map((item) => `<div class="issue blocker"><span class="issue-label">缺价</span><p>${item.item}${item.catalog_id ? ` · ${item.catalog_id}` : ''}</p></div>`).join('');
    const receipt = runtimeReceipt(quote).map((item) => `<div class="list-row"><span class="list-main"><span class="list-name">${item.category} · ${item.item}</span><span class="list-sub">应收到：${item.expected}<br>核对：${item.check}</span></span></div>`).join('');
    const changed = editState.changed ? '<div class="issue warning"><span class="issue-label">已按新尺寸重算</span><p>原料支数、余料、门板、五金与费用均使用页面当前尺寸；承载和稳定性仍需下载后重新运行检查。</p></div>' : '';
    root.innerHTML = `<p class="section-title">整套预算</p><div class="assembly-head"><div><p class="step-name">${money(quote.total_range_cny)}</p><p class="step-copy">含 ${quote.contingency_percent || 0}% 预留；${quote.status === 'complete_budget_range' ? '预算项目齐全' : '仍有缺价项'}</p></div></div>${changed}<div class="bom-list">${rows}</div>${unknown ? `<p class="section-title bom-section">仍需补价</p><div class="issue-list">${unknown}</div>` : ''}<p class="section-title bom-section">收货核对</p><div class="bom-list">${receipt}</div>`;
  }

  function runtimeReceipt(quote) {
    const rows = [];
    Object.entries(quote.cut_plans || {}).forEach(([profileId, plan]) => {
      const profile = profiles[profileId] || {};
      const reference = catalogProfiles[profile.catalog_id] || {};
      const wall = reference.wall_thickness_mm || profile.wall_thickness_mm;
      rows.push({ category: '型材', item: reference.vendor_name || reference.name || profile.catalog_id, expected: `${plan.bars.length} 根 × ${plan.stock_length_mm} mm；${reference.width_mm || profile.width_mm}×${reference.height_mm || profile.height_mm} mm；槽 ${reference.slot_width_mm || profile.slot_width_mm}；${wall ? `壁厚 ${wall} mm` : '壁厚待商家确认'}`, check: '卡尺核对外形、槽宽与壁厚；逐根核长度、划伤、压伤、弯曲和毛刺。' });
    });
    const jointQty = (design.joints || []).reduce((sum, joint) => sum + Number(joint.connector?.qty || 1), 0);
    if (jointQty) rows.push({ category: '节点套装', item: '直角节点连接件', expected: `${jointQty} 套；角码、螺栓、后装螺母成套`, check: '先拿一套与型材试装，确认定位凸台进槽、孔径和螺纹吻合。' });
    doorCutRows().panels.forEach((panel) => rows.push({ category: '门板', item: panel.label, expected: `${panel.width}×${panel.height}×${panel.thickness} mm，1 块`, check: '钢尺核对长宽，卡尺核厚度；检查崩边、翘曲与保护膜。' }));
    const doorHardware = new Map();
    (design.doors || []).forEach((door) => [[door.hinge_catalog_id, Number(door.hinge_qty || 0)], [door.handle_catalog_id, 1], [door.catch_catalog_id, 1], [door.restraint_catalog_id, door.restraint_catalog_id ? 1 : 0]].forEach(([id, qty]) => { if (id) doorHardware.set(id, (doorHardware.get(id) || 0) + qty); }));
    doorHardware.forEach((qty, id) => {
      const product = catalogProducts[id] || {};
      const fasteners = (product.fastener_components || []).map((component) => `${catalogProducts[component.product_id]?.name || component.product_id}×${qty * Number(component.qty || 1)}`).join('；') || '紧固件待确认';
      rows.push({ category: '门五金', item: product.name || id, expected: `${qty} 件；${fasteners}`, check: '逐项点数，先在一扇门上试装；确认螺纹、槽宽、板厚与开启方向。' });
    });
    rows.push({ category: '整批', item: '数量与配套抽检', expected: '按下载方案分袋并标注', check: '逐类点数；螺栓与螺母抽装；型材切口去毛刺；门板先干装一扇。' });
    return rows;
  }

  function packCuts(cuts, stockLength, kerf = 3, trim = 5) {
    const capacity = stockLength - trim * 2;
    const bars = [];
    [...cuts].sort((a, b) => b.length - a.length).forEach((cut) => {
      let target = bars.find((bar) => bar.used + (bar.cuts.length ? kerf : 0) + cut.length <= capacity + 0.001);
      if (!target) { target = { cuts: [], used: 0 }; bars.push(target); }
      if (target.cuts.length) target.used += kerf;
      target.cuts.push(cut);
      target.used += cut.length;
    });
    return bars.map((bar, index) => ({ index: index + 1, cuts: bar.cuts, used_mm: Math.round(bar.used), remaining_usable_mm: Math.max(0, Math.round(capacity - bar.used)) }));
  }

  function runtimeCutPlans() {
    const settings = design.settings || {};
    const groups = new Map();
    members.forEach((member) => {
      if (!groups.has(member.profile_id)) groups.set(member.profile_id, []);
      groups.get(member.profile_id).push({ id: member.id, length: memberLength(member) });
    });
    return Object.fromEntries([...groups.entries()].map(([profileId, cuts]) => {
      const profile = profiles[profileId] || {};
      const reference = catalogProfiles[profile.catalog_id] || {};
      const stock = Number(profile.stock_length_mm || reference.stock_length_options_mm?.[0] || 6000);
      return [profileId, { stock_length_mm: stock, bars: packCuts(cuts, stock, Number(settings.kerf_mm || 0), Number(settings.end_trim_mm_each || 0)) }];
    }));
  }

  function priceRange(table, key) {
    const value = table?.[key];
    return Array.isArray(value) && value.length === 2 ? value.map(Number) : null;
  }

  function runtimeQuote() {
    const costing = design.costing || {};
    const rows = [];
    const add = (section, item, catalogId, qty, unit, range, source = '方案预算区间') => rows.push({ section, item, catalog_id: catalogId || '', qty: Math.round(qty * 1000) / 1000, unit, unit_price_range_cny: range, amount_range_cny: range ? [qty * range[0], qty * range[1]].map((value) => Math.round(value * 100) / 100) : null, price_source: source });
    const plans = runtimeCutPlans();
    Object.entries(plans).forEach(([profileId, plan]) => {
      const profile = profiles[profileId] || {};
      const reference = catalogProfiles[profile.catalog_id] || {};
      let range = priceRange(costing.profile_unit_cost_ranges_cny_per_m, profile.catalog_id);
      let source = '方案预算区间';
      if (!range && reference.price_cny_per_m != null) { range = [Number(reference.price_cny_per_m), Number(reference.price_cny_per_m)]; source = `目录快照 ${reference.price_captured_on || ''}`; }
      add('型材', reference.vendor_name || reference.name || profile.catalog_id, profile.catalog_id, plan.bars.length * plan.stock_length_mm / 1000, '米', range, source);
    });
    const systemIds = new Set(Object.values(profiles).map((profile) => profile.system_id || catalogProfiles[profile.catalog_id]?.system_id).filter(Boolean));
    const selectedSystem = systemIds.size === 1 ? payload.catalog.systems.find((system) => systemIds.has(system.id)) : null;
    const jointKitId = selectedSystem?.standard_joint_kit_id;
    const jointKit = payload.catalog.kits.find((kit) => kit.id === jointKitId);
    const jointQty = (design.joints || []).reduce((sum, joint) => sum + Number(joint.connector?.qty || 1), 0);
    (jointKit?.components || []).filter((component) => !component.optional).forEach((component) => {
      const product = catalogProducts[component.product_id] || {};
      const qty = jointQty * Number(component.qty || 1);
      add('连接紧固件', product.name || component.product_id, component.product_id, qty, '件', priceRange(costing.catalog_unit_cost_ranges_cny_each, component.product_id));
    });
    const doorRows = doorCutRows();
    const frameCuts = new Map();
    doorRows.frame.forEach((row) => {
      if (!frameCuts.has(row.catalogId)) frameCuts.set(row.catalogId, []);
      for (let index = 0; index < row.qty; index += 1) frameCuts.get(row.catalogId).push({ id: row.note, length: row.length });
    });
    frameCuts.forEach((cuts, catalogId) => {
      const reference = catalogProfiles[catalogId] || {};
      const stock = Number(reference.stock_length_options_mm?.[0] || 6000);
      const bars = packCuts(cuts, stock, Number(design.settings?.kerf_mm || 3), Number(design.settings?.end_trim_mm_each || 5));
      add('门系统', '门框型材原料', catalogId, bars.length * stock / 1000, '米', priceRange(costing.profile_unit_cost_ranges_cny_per_m, catalogId));
    });
    doorRows.panels.forEach((panel) => add('门系统', panel.label, panel.catalogId, panel.width * panel.height / 1e6, '平方米', priceRange(costing.panel_unit_cost_ranges_cny_m2, panel.catalogId)));
    const doorHardware = new Map();
    (design.doors || []).forEach((door) => [[door.hinge_catalog_id, Number(door.hinge_qty || 0)], [door.handle_catalog_id, 1], [door.catch_catalog_id, 1], [door.restraint_catalog_id, door.restraint_catalog_id ? 1 : 0]].forEach(([id, qty]) => { if (id) doorHardware.set(id, (doorHardware.get(id) || 0) + qty); }));
    doorHardware.forEach((qty, id) => {
      const product = catalogProducts[id] || {};
      add('门系统', product.name || id, id, qty, '件', priceRange(costing.catalog_unit_cost_ranges_cny_each, id));
      (product.fastener_components || []).forEach((component) => {
        const fastener = catalogProducts[component.product_id] || {};
        const fastenerQty = qty * Number(component.qty || 1);
        add('门系统紧固件', fastener.name || component.product_id, component.product_id, fastenerQty, '件', priceRange(costing.catalog_unit_cost_ranges_cny_each, component.product_id));
      });
    });
    const skippedDoor = new Set(['door_panel', 'door_hinge', 'door_handle', 'door_catch', 'door_restraint']);
    (design.accessories || []).filter((item) => !skippedDoor.has(item.category)).forEach((item) => {
      const id = item.catalog_id || item.catalog_kit_id || '';
      add('板材与附件', item.description || item.category, id, Number(item.qty || 0), '件', id ? priceRange(costing.catalog_unit_cost_ranges_cny_each, id) : priceRange(costing.category_unit_cost_ranges_cny_each, item.category));
    });
    const bodyCuts = members.length;
    const doorCuts = doorRows.frame.reduce((sum, row) => sum + Number(row.qty || 0), 0);
    add('加工', '主体型材切割', '', bodyCuts, '刀', priceRange(costing.processing_unit_cost_ranges_cny, 'profile_cut'));
    if (doorCuts) add('加工', '门框型材切割', '', doorCuts, '刀', priceRange(costing.processing_unit_cost_ranges_cny, 'door_frame_cut'));
    const shipping = priceRange(costing, 'shipping_cost_range_cny');
    if (shipping) add('物流', '包装与运输', '', 1, '批', shipping);
    const known = rows.filter((row) => row.amount_range_cny);
    const unknown = rows.filter((row) => !row.amount_range_cny);
    const subtotal = [0, 1].map((index) => known.reduce((sum, row) => sum + row.amount_range_cny[index], 0));
    const contingency = Number(costing.contingency_percent || 0);
    const total = subtotal.map((value) => Math.round(value * (1 + contingency / 100) * 100) / 100);
    return { currency: 'CNY', status: unknown.length ? 'incomplete' : 'complete_budget_range', rows, total_range_cny: total, contingency_percent: contingency, unknown_items: unknown.map((row) => ({ section: row.section, item: row.item, catalog_id: row.catalog_id })), cut_plans: plans };
  }

  function exportCurrentPackage() {
    const quote = runtimeQuote();
    const packageData = { format: 'ray-aluframe-package-v1', exported_at: new Date().toISOString(), design, bom: currentBomRows(), door_cuts: doorCutRows(), cut_plans: quote.cut_plans, quote, receipt_checklist: runtimeReceipt(quote), assembly_plan: payload.assembly_plan || {}, reference_review: window.rayReferenceReviewState || null, note: '页面修改后的承载与稳定性需要重新运行检查。' };
    const blob = new Blob([JSON.stringify(packageData, null, 2)], { type: 'application/json;charset=utf-8' });
    const link = document.createElement('a');
    const downloadUrl = URL.createObjectURL(blob);
    link.href = downloadUrl;
    link.download = `ray-aluframe-${String(design.project?.name || 'design').replace(/[^a-zA-Z0-9\u4e00-\u9fff-]+/g, '-')}.json`;
    document.body.appendChild(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(downloadUrl), 1000);
    const status = document.getElementById('export-status');
    if (status) {
      status.textContent = `已生成当前方案：${packageData.bom.length} 组主体下料，${Object.values(packageData.cut_plans).reduce((sum, plan) => sum + plan.bars.length, 0)} 根原料。`;
      status.hidden = false;
      setTimeout(() => { status.hidden = true; }, 5000);
    }
  }

  function renderIssues() {
    const labels = { error: '错误', blocker: '必须确认', warning: '提醒' };
    const root = document.getElementById('issues-panel');
    const runtimeNotice = editState.changed ? [{ severity: 'warning', text: '页面已重算模型、下料和门板数量；承载、稳定性和最终采购规格需要导出设计后重新检查。' }] : [];
    const issues = [...runtimeNotice, ...(payload.issues || [])];
    root.innerHTML = '<p class="section-title">方案检查</p><div class="issue-list">' + (issues.length ? issues.map((issue) => `<div class="issue ${issue.severity}"><span class="issue-label">${labels[issue.severity]}</span><p>${issue.text}</p></div>`).join('') : '<p class="empty">没有发现阻断项，可以继续准备询价。</p>') + '</div>';
  }

  function setupEditor() {
    const toggle = document.getElementById('edit-layout');
    const editor = document.getElementById('dimension-editor');
    if (!toggle || !editor || !editState.enabled) {
      if (toggle) toggle.hidden = true;
      return;
    }
    const fields = design.editable?.fields || [];
    const values = editState.values;
    editor.querySelector('.editor-fields').innerHTML = fields.map((field) => `<label class="editor-field"><span>${field.label}</span><span class="editor-input"><input type="number" data-edit-field="${field.id}" value="${Math.round(values[field.id] * 10) / 10}" min="${field.min}" max="${field.max}" step="${field.step}"><small>${field.unit || ''}</small></span></label>`).join('');
    const status = editor.querySelector('.editor-status');
    const validateValues = (next) => {
      if (design.editable.layout === 'split_cabinet_v1') {
        const rightBay = next.width_mm - next.divider_mm;
        const cabinetTop = Number(design.editable.anchors.base_z_mm || 0) + next.level_count * next.level_height_mm;
        if (rightBay < Number(design.editable.minimum_right_bay_mm || 250)) return `右侧净宽至少保留 ${design.editable.minimum_right_bay_mm || 250} mm`;
        if (cabinetTop > next.height_mm - Number(design.editable.minimum_upper_zone_mm || 250)) return '层数与层高组合过高，上部区域不足';
      }
      if (next.bay_count && next.width_mm / next.bay_count < Number(design.editable.minimum_bay_width_mm || 250)) return `每格宽度至少保留 ${design.editable.minimum_bay_width_mm || 250} mm`;
      return '';
    };
    const applyValues = (changedField) => {
      const next = {};
      editor.querySelectorAll('[data-edit-field]').forEach((input) => { next[input.dataset.editField] = Number(input.value); });
      if (changedField === 'level_count' && design.editable.layout === 'split_cabinet_v1') {
        const base = Number(design.editable.anchors.base_z_mm || 0);
        const currentTop = editState.cabinetTop || Number(design.editable.anchors.cabinet_top_z_mm);
        next.level_height_mm = Math.max(120, Math.round((currentTop - base) / Math.max(1, next.level_count) / 5) * 5);
        editor.querySelector('[data-edit-field="level_height_mm"]').value = next.level_height_mm;
      }
      const error = validateValues(next);
      if (error) {
        status.textContent = error;
        status.dataset.state = 'error';
        return;
      }
      status.textContent = '正在更新模型与清单…';
      status.dataset.state = 'working';
      const url = new URL(window.location.href);
      url.hash = '';
      url.searchParams.set('ray-edit', JSON.stringify(next));
      window.location.assign(url.toString());
    };
    toggle.onclick = () => {
      const open = editor.hidden;
      editor.hidden = !open;
      toggle.setAttribute('aria-pressed', open);
      if (open) editor.querySelector('input')?.focus();
    };
    editor.querySelectorAll('[data-edit-field]').forEach((input) => {
      input.onchange = () => applyValues(input.dataset.editField);
      input.onkeydown = (event) => {
        if (event.key !== 'Enter') return;
        event.preventDefault();
        applyValues(input.dataset.editField);
      };
    });
    editor.querySelector('#reset-layout').onclick = () => {
      const url = new URL(window.location.href);
      url.hash = '';
      url.searchParams.delete('ray-edit');
      window.location.assign(url.toString());
    };
    if (editState.changed) {
      status.textContent = '当前为页面修改版；模型、下料和门板清单已同步。';
      status.dataset.state = 'changed';
    }
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
    document.getElementById('export-design').onclick = exportCurrentPackage;
    document.getElementById('show-panels').onchange = (event) => { state.showPanels = event.target.checked; applyAppearance(); };
    document.getElementById('show-hardware').onchange = (event) => { state.showHardware = event.target.checked; applyAppearance(); };
    document.getElementById('show-dimensions').onchange = (event) => {
      state.showDimensions = event.target.checked;
      document.getElementById('dimensions').hidden = !event.target.checked;
      applyAppearance();
    };
    window.addEventListener('ray-reference-review', (event) => {
      state.referenceReview = Boolean(event.detail?.active);
      applyAppearance();
    });
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
      const candidates = state.showHardware ? [...hardwarePickMeshes, ...pickMeshes] : pickMeshes;
      const hit = raycaster.intersectObjects(candidates, false)[0];
      if (hit?.object?.userData?.hardwareInfo) selectHardware(hit.object.userData.hardwareInfo);
      else if (hit?.object?.userData?.memberId) selectMember(hit.object.userData.memberId);
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
    if ('ResizeObserver' in window) {
      new ResizeObserver(resize).observe(canvas.parentElement);
    } else {
      window.addEventListener('resize', resize);
    }
  }

  function resize() {
    const rect = canvas.getBoundingClientRect();
    const width = Math.max(1, Math.round(rect.width || canvas.parentElement?.clientWidth || window.innerWidth || 1));
    const height = Math.max(1, Math.round(rect.height || canvas.parentElement?.clientHeight || window.innerHeight || 1));
    const pixelRatio = renderer.getPixelRatio();
    const expectedWidth = Math.round(width * pixelRatio);
    const expectedHeight = Math.round(height * pixelRatio);
    if (canvas.width !== expectedWidth || canvas.height !== expectedHeight) {
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      requestDraw();
      return true;
    }
    return false;
  }

  function updateCamera(initial = false) {
    const horizontal = Math.cos(state.pitch) * state.distance;
    camera.position.set(
      cameraTarget.x + Math.cos(state.yaw) * horizontal,
      cameraTarget.y + Math.sin(state.pitch) * state.distance,
      cameraTarget.z + Math.sin(state.yaw) * horizontal,
    );
    camera.lookAt(cameraTarget);
    if (initial) resize();
    requestDraw();
  }

  function requestDraw() {
    state.needsRender = true;
  }

  function showRenderFailure(error) {
    console.error('3D preview failed to render', error);
    const notice = document.createElement('div');
    notice.className = 'render-failure';
    notice.innerHTML = '<strong>三维预览未能启动</strong><span>请重新打开此文件；如果仍然失败，请把这条提示截图发回来。</span>';
    canvas.parentElement.appendChild(notice);
  }

  function drawNow() {
    renderer.render(scene, camera);
    state.needsRender = false;
  }

  function animate() {
    requestAnimationFrame(animate);
    resize();
    drawNow();
  }
})();
