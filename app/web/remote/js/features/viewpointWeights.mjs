// 구도/시점 제어의 수식 - 반구 위 관찰점(좌우 yaw · 상하 pitch · 거리 radius) -> 구도 가중치 태그.
//
// 출처: docs/projective_geometry_viewer_20261011 의 변환식을 1girl 실험(docs/girl_viewpoint_lab_20261016)으로 보정한 판.
//   v3 위쪽 곡선 B · 0.1 단위 / v4 straight-on 이 기울기만큼 약해짐 / v5 위쪽 곡선 뒷부분 보강 / v6 후면의 뒤쪽 가중치를
//   좌우 각도만으로(위아래 극단에서 후면 3/4 가 앞모습이 되던 것 - 4회차 0/6).
// 대상은 인물 기준이다: 후면 억제 태그 = 'facing viewer'(뷰어의 소파 전용 태그 대신).
// 좌우(어느 쪽을 보나)는 모델이 시드로 정한다 - 태그는 |yaw| 만 본다(대칭 처리, 사용자 결정 2026-10-16).

export const VIEWPOINT_VERSION = 'viewpoint-v6';
export const LIMITS = Object.freeze({yaw: 90, pitch: 90, minRadius: 2.4, maxRadius: 7, referenceRadius: 4, minWeight: 0.1, maxWeight: 2});

// 이 수식이 쓰는 태그 전부.
export const VIEWPOINT_TAGS = Object.freeze([
  'straight-on', 'from behind', 'facing viewer', 'three-quarter view', 'from side',
  "worm's-eye view", 'low-angle view', 'high-angle view', "bird's-eye view", 'from above', 'from below',
  'close-up', 'wide shot', 'object focus',
]);

const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
const rad = deg => (deg * Math.PI) / 180;

/** share -> 가중치(0.1 단위, 절댓값 0.1 ~ 2.0). 0 이면 태그를 뺀다. */
export function weightOf(share) {
  if (!Number.isFinite(share) || Math.abs(share) < 1e-12) return 0;
  return Math.sign(share) * Math.round(clamp(2 * Math.abs(share), 0.05, 2) * 10) / 10;
}

export function normalizeViewpoint(input = {}) {
  const hemisphere = input.hemisphere === 'rear' ? 'rear' : 'front';
  const num = (v, d) => (Number.isFinite(Number(v)) ? Number(v) : d);
  return {
    hemisphere,
    yaw: clamp(num(input.yaw, 0), -LIMITS.yaw, LIMITS.yaw),
    pitch: clamp(num(input.pitch, 0), -LIMITS.pitch, LIMITS.pitch),
    radius: clamp(num(input.radius, LIMITS.referenceRadius), LIMITS.minRadius, LIMITS.maxRadius),
  };
}

export function convertViewpoint(input) {
  const {hemisphere, yaw, pitch, radius} = normalizeViewpoint(input);
  const ax = Math.abs(yaw) / 90;
  const z = (radius - 4) / (radius < 4 ? 1.6 : 3);
  const visibility = Math.cos(rad(yaw)) * Math.cos(rad(pitch));
  const tags = [];
  const add = (axis, tag, share) => {
    const weight = weightOf(share);
    if (weight) tags.push({axis, tag, share, weight});
  };
  const central = Math.max(0, 1 - 2 * ax);
  const quarter = Math.max(0, 1 - Math.abs(2 * ax - 1));
  const side = Math.max(0, 2 * ax - 1);
  if (hemisphere === 'front') {
    // 'straight-on' = 눈높이 정면(Danbooru) - 기울면 약하게(v4).
    add('X', 'straight-on', central * (1 - Math.abs(pitch) / 90));
    add('X', 'from behind', -0.65 * visibility);
  } else {
    // v6: 뒤쪽은 좌우 각도만으로 - 위아래 극단(|pitch| >= 75)에서 cos(pitch) 때문에 뒤쪽 가중치가 사라져 앞모습이 됐다.
    const behind = Math.cos(rad(yaw));
    add('X', 'from behind', Math.max(central, 0.8 * behind));
    add('X', 'facing viewer', -0.65 * behind);
  }
  add('X', 'three-quarter view', quarter);
  add('X', 'from side', side);
  // 위쪽은 모델이 문턱을 넘으면 한 번에 강한 부감이 된다 - +45 까지 pitch/90, 그 뒤 +70 에서 1(v3 B · v5).
  const up = pitch <= 0 ? 1 : pitch <= 45 ? pitch / 90 : Math.min(1, 0.5 + ((pitch - 45) / 25) * 0.5);
  for (const [center, tag] of [[-90, "worm's-eye view"], [-45, 'low-angle view'], [45, 'high-angle view'], [90, "bird's-eye view"]]) {
    add('Y', tag, up * Math.max(0, 1 - Math.abs(pitch - center) / 45));
  }
  add('Y', 'from above', up * Math.max(0, Math.min(1, pitch / 45)) * 0.5);
  add('Y', 'from below', Math.max(0, Math.min(1, -pitch / 45)) * 0.5);
  const near = Math.max(0, -z);
  const far = Math.max(0, z);
  add('Z', 'close-up', near);
  add('Z', 'wide shot', far);
  add('Z', 'wide shot', -0.675 * near);
  add('Z', 'close-up', -0.675 * far);
  add('Z', 'object focus', 0.5 * near);
  return {version: VIEWPOINT_VERSION, viewpoint: {hemisphere, yaw, pitch, radius}, relative: {x: yaw / 90, y: pitch / 90, z}, tags, summary: summarize({hemisphere, yaw, pitch, radius})};
}

/** 사람이 읽는 한 줄: '3/4 · 약한 부감 · 중간'. 실험의 판정 범주와 같은 경계다. */
export function summarize({hemisphere, yaw, pitch, radius}) {
  const ax = Math.abs(yaw);
  const horizontal = hemisphere === 'rear'
    ? (ax < 15 ? '뒷모습' : ax < 67.5 ? '뒤 3/4' : '옆(뒤)')
    : (ax < 15 ? '정면' : ax < 67.5 ? '3/4' : '옆');
  const ap = Math.abs(pitch);
  const vertical = ap < 20 ? '수평' : pitch > 0 ? (ap < 45 ? '약한 부감' : ap < 80 ? '부감' : '바로 위(한계)') : (ap < 45 ? '약한 앙각' : ap < 80 ? '앙각' : '발아래');
  const framing = radius < 3.2 ? '근접' : radius > 5.5 ? '원경(약함)' : '중간';
  return `${horizontal} · ${vertical} · ${framing}`;
}

/** 모드에 맞는 가중치 문법. NAI = `1.6::tag ::`(음수 = 억제). WEBUI · ComfyUI = `(tag:1.6)` - 음수 가중치가 없어 억제 태그는 뺀다. */
export function formatViewpointTags(tags, mode = 'NAI') {
  const nai = String(mode || 'NAI').toUpperCase() === 'NAI';
  return tags
    .filter(t => nai || t.weight > 0)
    .map(t => (nai ? `${Number(t.weight.toFixed(1))}::${t.tag} ::` : `(${t.tag}:${t.weight.toFixed(1)})`))
    .join(', ');
}

// ── 반구 <-> 관찰점 ───────────────────────────────────────────────────────
// 방위각 az: 0 = 정면(+Z), +90 = 오른쪽(+X), ±180 = 정후방. 앞뒤 반구는 |az| 로 정해진다(뒤로 이어서 돌 수 있다).
export function viewpointToAzimuth({hemisphere, yaw}) {
  if (hemisphere !== 'rear') return yaw;
  if (yaw === 0) return 180;
  return Math.sign(yaw) * (180 - Math.abs(yaw));
}

export function azimuthToViewpoint(az) {
  let a = ((az + 180) % 360 + 360) % 360 - 180;          // -180 ~ 180
  if (a === -180) a = 180;
  if (Math.abs(a) <= 90) return {hemisphere: 'front', yaw: a};
  return {hemisphere: 'rear', yaw: Math.sign(a) * (180 - Math.abs(a))};
}
