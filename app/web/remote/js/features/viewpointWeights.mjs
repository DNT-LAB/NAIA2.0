// 구도/시점 제어의 수식 - 반구 위 관찰점(좌우 yaw · 상하 pitch · 거리 radius) -> 구도 가중치 태그.
//
// 출처: docs/projective_geometry_viewer_20261011 의 변환식을 1girl 실험(docs/girl_viewpoint_lab_20261016)으로 보정한 판.
//   v3 위쪽 곡선 B · 0.1 단위 / v4 straight-on 이 기울기만큼 약해짐 / v5 위쪽 곡선 뒷부분 보강 / v6 후면의 뒤쪽 가중치를
//   좌우 각도만으로(위아래 극단에서 후면 3/4 가 앞모습이 되던 것 - 4회차 0/6) / v7 straight-on 회수(사용자 지시 2026-10-17:
//   구도 제어를 방해할 때가 많다 - 정면은 억제 태그 'from behind' 만 남는다).
//   v8(사용자 제보 2026-10-17 "가중치가 너무 세다 · 정면~45° 는 조합이 복잡해 헷갈린다 · 후면은 이상한 프롬프트로 안 된다"):
//   - 가중치 절반(0.05 단위, 최대 1). 1 이면 가중치 문법 없이 태그만.
//   - 0.2 미만은 뺀다 - 작은 몫이 최소 가중치로 올라붙어 생기던 꼬리 태그(0.1::high-angle view 따위)를 없앤다.
//   - 요약과 같은 띠에서는 태그도 없다: |yaw| < 15 = 정면 / 뒷모습(3/4 가 새지 않는다), |pitch| < 20 = 수평(위아래 태그 없음).
//   - 후면 = 사용자가 실제로 돌려 본 프롬프트 그대로: `1.5::rear view, from behind ::, looking away, -1.3::looking at viewer ::`
//     (절반 규칙보다 이 예가 우선 - 'facing viewer' 억제는 'looking at viewer' 억제로 바뀌었다).
//   - 'object focus' 회수 - 사물에 초점을 두라는 태그라 인물 근접에 맞지 않는다. 인물이 물건을 들고 있으면 그 물건으로
//     초점이 넘어가 그림이 무너진다(사용자 2026-10-17). 다시 넣지 말 것.
//   v9(사용자 지시 2026-10-17): 부감(위쪽 high-angle · bird's-eye · from above)만 v7 값으로 되돌린다(최대 2).
//   v10(사용자 지시 2026-10-17): 'from side' 도 v7 값으로 - 7회차에서 옆(90)이 진짜 옆얼굴 0/2(몸만 돌고 얼굴은 정면).
//   v11(사용자 제안 2026-10-17): 'side view' 를 옆 몫 그대로 덧붙인다 - 9회차에서 옆(90) 옆얼굴 1/2 -> 2/2.
//   v12(사용자 지시 2026-10-17): 후면 묶음 · looking away · looking at viewer 억제가 덜 빨리 약해진다(45 까지 그대로, 65 에서 2/3).
//   10회차에서 뒤 3/4(65)가 앞 3/4 로 뒤집혔다(1/2) - 후면 0.5 가 from side 0.9 · 3/4 0.55 에 졌다.
//   v13(사용자 지시 2026-10-17): v12 는 뒤 45 를 순수 뒷모습으로 과보정(0/2) - 후면 몫을 0~15 = 1, 15~45 에서 2/3 로,
//   45~70 = 2/3 평평, 70~90 에서 0 으로. 후면 묶음 1.5 -> 1.0 이 뒤 3/4 구간 전체에 걸린다.
//   5회차에서 절반 값(+45 = 0.5 + 0.25)은 전면 부감 4장 모두 약했다 - 모델이 부감을 문턱 넘는 스위치로 받는다(3차).
// 좌우(어느 쪽을 보나)는 모델이 시드로 정한다 - 태그는 |yaw| 만 본다(대칭 처리, 사용자 결정 2026-10-16).

export const VIEWPOINT_VERSION = 'viewpoint-v13';
export const LIMITS = Object.freeze({yaw: 90, pitch: 90, minRadius: 2.4, maxRadius: 7, referenceRadius: 4, minWeight: 0.2, maxWeight: 1.5});

// 후면 묶음 - 사용자가 실제로 돌려 본 예(2026-10-17)의 가중치. 절반 규칙의 예외다.
const REAR_TAG = 'rear view, from behind';
const REAR_WEIGHT = 1.5;
const REAR_LOOK_AT_VIEWER = -1.3;
// v7 값으로 되돌린 태그(부감 = v9 · from side = v10) - 2 x share, 최대 2.
const V7_GAIN = 2;
const V7_MAX = 2;

// 이 수식이 쓰는 태그 전부(묶음 'rear view, from behind' 는 한 가중치로 나간다).
export const VIEWPOINT_TAGS = Object.freeze([
  'from behind', REAR_TAG, 'looking away', 'looking at viewer', 'three-quarter view', 'from side', 'side view',
  "worm's-eye view", 'low-angle view', 'high-angle view', "bird's-eye view", 'from above', 'from below',
  'close-up', 'wide shot',
]);

// 구도 · 시점 탭의 추가 옵션 - 3D 시점과 상관없이 켜고 끄는 태그(사용자 지시 2026-10-17). 출처 = 옛 Interactive 구도 블록의
// '스페셜 태그' 다섯 + POV 체크(C:/VNR/NAIA2.0/ui/interactive/composition_block.py). 이름은 Danbooru 그대로(건수 2026-04):
// dutch angle 15만 · perspective 9천 · foreshortening 6.4만 · upside-down 3.2만 · sideways 5천 · pov 17.7만.
// 옛 POV 체크는 'pov, first person view' 를 냈다 - first person view 는 Danbooru 에 없어 pov 만 둔다.
export const VIEW_EXTRAS = Object.freeze([
  ['dutch angle', '기울임'], ['perspective', '원근감'], ['foreshortening', '역동감'],
  ['upside-down', '뒤집기'], ['sideways', '90도'], ['pov', '1인칭(POV)'],
]);

/** 켠 추가 옵션 - 알려진 것만, VIEW_EXTRAS 차례로. */
export function normalizeExtras(list) {
  const on = new Set(Array.isArray(list) ? list.map(String) : []);
  return VIEW_EXTRAS.map(([tag]) => tag).filter(tag => on.has(tag));
}

const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
const rad = deg => (deg * Math.PI) / 180;

/** 원하는 가중치 -> 0.05 단위(절댓값 최대 max, 기본 1.5). 0.2 미만이면 0(태그를 뺀다). v7 의 2 x share 를 절반으로 = share 그대로. */
export function weightOf(value, max = LIMITS.maxWeight) {
  if (!Number.isFinite(value)) return 0;
  const w = Math.round(Math.min(Math.abs(value), max) * 20) / 20;
  return w < LIMITS.minWeight - 1e-9 ? 0 : Math.sign(value) * w;
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
  const tags = [];
  const add = (axis, tag, value, max) => {
    const weight = weightOf(value, max);
    if (weight) tags.push({axis, tag, share: value, weight});
  };
  const ay = Math.abs(yaw);
  // 정면 / 뒷모습 몫: |yaw| <= 15 에서 1(요약의 '정면' · '뒷모습' 띠), 90 에서 0. 15 밖은 v6 의 max(1-2ax, 0.8cos) 와 거의 같다.
  // v6 그대로 좌우 각도만 본다 - 위아래 극단에서 후면 3/4 가 앞모습이 되던 것(4회차 0/6).
  const facing = clamp((90 - ay) / 75, 0, 1);
  // 3/4: 15 까지 0 -> 45 에서 1 -> 90 에서 0. 정면 · 뒷모습 띠에는 새지 않는다.
  const quarter = ay <= 15 ? 0 : ay <= 45 ? (ay - 15) / 30 : (90 - ay) / 45;
  const side = Math.max(0, 2 * ax - 1);
  if (hemisphere === 'front') {
    add('X', 'from behind', -0.65 * facing * Math.cos(rad(pitch)));
  } else {
    // v13: 뒷모습 띠(15)까지 1, 45 까지 2/3 로 내려 뒤 3/4 구간(45~70)은 2/3 평평, 70 -> 90 에서 0.
    //      옆 · 3/4 태그에 지지 않으면서(v11 의 65 가 앞으로 뒤집힘) 3/4 를 누르지도 않게(v12 의 45 가 순수 뒷모습).
    const rearFacing = ay <= 15 ? 1 : ay <= 45 ? 1 - ((ay - 15) / 30) / 3 : ay <= 70 ? 2 / 3 : (2 / 3) * (90 - ay) / 20;
    add('X', REAR_TAG, REAR_WEIGHT * rearFacing);
    add('X', 'looking away', rearFacing);
    add('X', 'looking at viewer', REAR_LOOK_AT_VIEWER * rearFacing);
  }
  add('X', 'three-quarter view', quarter);
  add('X', 'from side', V7_GAIN * side, V7_MAX);
  add('X', 'side view', side);
  // 위쪽은 모델이 문턱을 넘으면 한 번에 강한 부감이 된다 - +45 까지 pitch/90, 그 뒤 +70 에서 1(v3 B · v5).
  const up = pitch <= 0 ? 1 : pitch <= 45 ? pitch / 90 : Math.min(1, 0.5 + ((pitch - 45) / 25) * 0.5);
  // v8: 수평 띠(|pitch| < 20)에는 위아래 태그가 없다 - 15 에서 0 -> 30 에서 1 로 켠다(앙각 쪽이 -13 에서도 low-angle 을 냈다).
  const level = clamp((Math.abs(pitch) - 15) / 15, 0, 1);
  for (const [center, tag] of [[-90, "worm's-eye view"], [-45, 'low-angle view'], [45, 'high-angle view'], [90, "bird's-eye view"]]) {
    // v9: 부감 쪽만 v7 값(2 x share, 최대 2) - 앙각은 v8 절반 그대로.
    const gain = center > 0 ? V7_GAIN : 1;
    add('Y', tag, gain * level * up * Math.max(0, 1 - Math.abs(pitch - center) / 45), center > 0 ? V7_MAX : undefined);
  }
  add('Y', 'from above', V7_GAIN * level * up * Math.max(0, Math.min(1, pitch / 45)) * 0.5, V7_MAX);
  add('Y', 'from below', level * Math.max(0, Math.min(1, -pitch / 45)) * 0.5);
  const near = Math.max(0, -z);
  const far = Math.max(0, z);
  add('Z', 'close-up', near);
  add('Z', 'wide shot', far);
  // 억제 쪽은 사용자가 돌려 본 후면 예의 -0.75(v7 -1.35 의 절반 -0.675 와 가깝다).
  add('Z', 'wide shot', -0.75 * near);
  add('Z', 'close-up', -0.75 * far);
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

/** 모드에 맞는 가중치 문법. NAI = `0.65::tag ::`(음수 = 억제). WEBUI · ComfyUI = `(tag:0.65)` - 음수 가중치가 없어 억제 태그는 뺀다.
 *  가중치 1 은 문법 없이 태그만(v8 - 사용자가 돌려 본 후면 예의 `looking away`). */
export function formatViewpointTags(tags, mode = 'NAI') {
  const nai = String(mode || 'NAI').toUpperCase() === 'NAI';
  return tags
    .filter(t => nai || t.weight > 0)
    .map(t => {
      const w = Number(t.weight.toFixed(2));
      if (w === 1) return t.tag;
      return nai ? `${w}::${t.tag} ::` : `(${t.tag}:${w})`;
    })
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
