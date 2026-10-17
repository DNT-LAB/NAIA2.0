// [프롬프트 도구] > [구도 / 시점 제어] - 관찰점 C 로 시점을 고르면 구도 가중치 태그를 만든다(사용자 지시 2026-10-16).
//
// 수식은 viewpointWeights.mjs(v7). 이 창은 고르는 화면과 복사뿐이다:
//   - 왼쪽 캔버스 = **C 에서 본 장면**(사용자 제안 2026-10-17 "C 와 사용자 View 를 동기화"). 끌면 카메라가 인물 둘레를 360° 돈다 -
//     좌우 = 방위(정면 -> 옆 -> 뒤로 이어진다), 위아래 = 상하, 휠 = 거리. 앞 / 뒤 반구는 C 의 자리로 정해진다(배지로만 보인다).
//     예전 뷰어는 보이는 앞면 위의 점으로만 잡아 반구 뒤로 못 넘어갔다 · 그다음 판은 반구를 바깥에서 돌려 앞뒤가 뒤집혀 보였다.
//   - 인물 = 앞면엔 정면 그림 · 뒷면엔 뒷모습 그림을 붙인 판 + 발밑 고리 + 허리 높이의 정면 화살표
//     + 오른쪽 위 나침반(위에서 본 지도, 아래 = 정면).
//     판의 +X 가장자리에 'L'(그녀의 왼쪽) - 좌우가 뒤집혀 그려지는지 눈으로 가릴 수 있다(목업에서 실제로 뒤집혔었다).
//   - 위 탭(사용자 지시 2026-10-17 "한 페이지에 다 넣으면 부대낀다"): [구도 · 시점] = 반구 배지 · 요약 · 거리 슬라이더 /
//     [시선] = 방향 · 대상 · 신체 세 칸을 창 전체 폭에 한눈에(칸마다 하나, viewpointGaze.mjs).
//     둘은 **별개**다(사용자 지시 2026-10-17 "시선쪽에서는 XYZ 를 걷어냅시다. 둘은 별개로 취급"): 글 칸 · [복사] 는
//     지금 탭의 것만 다룬다. 시선 탭에는 3D 장면이 없다 - 판의 그림은 늘 정면을 봐서 시선을 보여 줄 수 없다(사용자 2026-10-17).
//   - 메인 프롬프트에 넣는 단추는 없다 - 글 칸을 드래그해 복사하거나 [복사](사용자 지시 2026-10-17). 넣기는 '전에 넣은 태그' 를
//     프롬프트에서 찾아 바꿔야 했는데, 가중치 없는 시선 태그는 사용자가 쓴 것과 끝내 못 가려(Codex 리뷰 6차까지) 걷어 냈다.
// 투영 미리보기는 넣지 않는다(사용자 결정). 껍데기는 다른 떠 있는 창과 같다(em-overlay em-window).

import {createDraggablePanel} from './draggablePanel.mjs?v=20260926-childalign';
import {
  LIMITS, azimuthToViewpoint, convertViewpoint, formatViewpointTags, normalizeViewpoint, viewpointToAzimuth,
} from './viewpointWeights.mjs?v=20261017-v7';
import {GAZE_GROUPS, gazeLabel, gazeTags, normalizeGaze} from './viewpointGaze.mjs?v=20261017-copy1';

const STYLE_ID = 'vpc-style';
const STATE_KEY = 'naia.viewpoint.state';
const GAZE_KEY = 'naia.viewpoint.gaze';
const TAB_KEY = 'naia.viewpoint.tab';
const GUIDE = '구도 / 시점 제어 - 화면은 관찰점(C)에서 본 장면입니다. 시점을 고르면 구도 가중치 태그를 만듭니다.\n\n'
  + '끌기 - 카메라가 인물 둘레를 돕니다(좌우 = 방위, 정면 -> 옆 -> 뒤로 이어짐 / 위아래 = 상하).\n'
  + '휠 · 거리 슬라이더 - 가까이 / 멀리. 방향키도 됩니다.\n'
  + '판의 L 표식 = 그녀의 왼쪽. 오른쪽 위 나침반 = 위에서 본 자리(아래가 정면).\n\n'
  + '[시선] 탭 - 방향 · 대상 · 신체에서 하나씩 고릅니다. 다시 누르면 풉니다.\n'
  + '시선 탭은 구도와 따로입니다 - 글 칸 · [복사] 는 지금 탭의 것만 다룹니다.\n\n'
  + '글 칸을 드래그해 복사하거나 [복사] 를 눌러 메인 · 캐릭터 프롬프트에 붙여 넣습니다.\n\n'
  + '한계(실험): 좌우 방향은 시드가 정합니다(대칭). 원경과 바로 위 시점은 태그만으로는 약합니다.';
// [이름, {az?, pitch?, radius?}] - 비운 값은 그대로 둔다.
const PRESETS = [
  ['정면', {az: 0}], ['3/4', {az: 45}], ['옆', {az: 90}], ['뒤', {az: 180}],
  ['위', {pitch: 60}], ['수평', {pitch: 0}], ['아래', {pitch: -60}],
  ['근접', {radius: 2.6}], ['기본 거리', {radius: 4}],
];
const W = 320;
const H = 280;
const FOCAL = 330;            // 화면 px / (세계 단위 / 깊이)
const CAM_SCALE = 0.9;        // 거리(2.4 ~ 7) -> 카메라까지의 세계 거리
const DEG_PER_PX = 0.7;       // 좌우 끌기
const PITCH_PER_PX = 0.5;     // 위아래 끌기
const KEY_STEP = 5;
const CARD_HEIGHT = 1.5;      // 발(-0.75) ~ 머리(+0.75)
const CARD_HALF = 0.44;       // 정면 그림의 반폭(1.5 x 247 / 420 / 2)
// 판에 붙일 그림 - 실험(docs/girl_viewpoint_lab_20261016)의 정면 · 뒷모습(시드 520310117)에서 배경을 걷은 것.
// 뒷모습은 좌우를 뒤집어 두었다 - 사이드 포니테일이 그녀의 왼쪽(L)에 오게(그 장은 모델이 반대쪽에 그렸다).
const SPRITES = {front: loadSprite('viewpoint_front.png'), back: loadSprite('viewpoint_back.png')};

function loadSprite(name) {
  const sprite = {img: null, ready: false, waiters: new Set()};
  if (typeof Image === 'undefined') return sprite;
  sprite.img = new Image();
  sprite.img.onload = () => {
    sprite.ready = true;
    sprite.waiters.forEach(fn => fn());
    sprite.waiters.clear();
  };
  sprite.img.src = new URL(`../assets/${name}`, import.meta.url).href;
  return sprite;
}

export function createViewpointControlWindow({
  document: doc,
  window: win = (typeof window !== 'undefined' ? window : null),
  getMode = () => 'NAI',
  notify = () => {},
  storage = (typeof localStorage !== 'undefined' ? localStorage : null),
  escHtml = v => String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'),
  onVisibilityChange = () => {},
}) {
  ensureStyle(doc);
  let view = readState();          // {hemisphere, yaw, pitch, radius} - 수식의 입력
  let az = viewpointToAzimuth(view);  // 방위 -180 ~ 180(0 = 정면, +90 = 그녀의 왼쪽, ±180 = 뒤) - 끄는 동안의 연속값
  let gaze = readGaze();           // {dir, tgt, body}
  let tab = readTab();             // 'view' | 'gaze'

  const panel = createDraggablePanel({
    document: doc, window: win, id: 'viewpointControlWindow', title: '구도 / 시점 제어',
    variant: 'em-overlay em-window vpc-window', storageKey: 'viewpoint-control',
    width: 660, height: 440, minWidth: 360, maxWidth: 920, minHeight: 240, resizable: true,
    escHtml,
    onOpen: () => { draw(); onVisibilityChange(); },
    onClose: () => onVisibilityChange(),
  });
  const guide = doc.createElement('button');
  guide.type = 'button';
  guide.className = 'header-guide-btn vpc-guide';
  guide.textContent = 'ⓘ';
  guide.setAttribute('aria-label', '구도 / 시점 제어 안내');
  guide.dataset.naiaGuide = GUIDE;
  panel.slot.appendChild(guide);

  panel.body.innerHTML = `
    <div class="vpc-tabs" role="tablist">
      <button type="button" role="tab" data-vpc-tab="view">구도 · 시점</button>
      <button type="button" role="tab" data-vpc-tab="gaze">시선</button>
    </div>
    <div class="vpc">
      <div class="vpc-left" data-vpc-only="view">
        <canvas class="vpc-canvas" tabindex="0"
          aria-label="관찰점 C 에서 본 장면 - 끌면 카메라가 둘레를 돈다(좌우 = 방위, 위아래 = 상하), 휠 = 거리, 방향키도 된다"></canvas>
        <div class="vpc-presets">${PRESETS.map(([label], i) => `<button type="button" data-vpc-preset="${i}">${escHtml(label)}</button>`).join('')}</div>
        <div class="vpc-hint">끌기 = 카메라가 둘레를 돎 · 휠 = 거리 · L = 그녀의 왼쪽</div>
      </div>
      <div class="vpc-right">
        <div class="vpc-page" data-vpc-page="view">
          <div class="vpc-head"><span class="vpc-hemi-badge" data-vpc-hemi></span><span class="vpc-summary"></span></div>
          <label class="vpc-radius-row"><span>거리</span>
            <input type="range" class="vpc-radius" data-vpc-range="radius" min="${LIMITS.minRadius}" max="${LIMITS.maxRadius}" step="0.1" aria-label="거리"></label>
        </div>
        <div class="vpc-page" data-vpc-page="gaze" hidden>
          <div class="vpc-head"><span class="vpc-gaze-badge">시선</span><span class="vpc-gaze-summary"></span>
            <button type="button" class="vpc-gaze-clear" data-vpc-gaze-clear>지우기</button></div>
          <div class="vpc-gaze-cols">${GAZE_GROUPS.map(g => `<div class="vpc-gaze-col" role="group" aria-label="${escHtml(g.label)}">
            <div class="vpc-gaze-col-head"><span>${escHtml(g.label)}${g.adult ? ' (성인)' : ''}</span><span class="vpc-gaze-pick" data-vpc-gaze-pick="${g.key}"></span></div>
            ${g.items.map(([tag, label]) => `<button type="button" class="vpc-gaze-chip" data-vpc-gaze-key="${g.key}" data-vpc-gaze="${escHtml(tag)}" title="${escHtml(tag)}">${escHtml(label)}</button>`).join('')}
          </div>`).join('')}</div>
        </div>
        <textarea class="vpc-text" rows="3" readonly spellcheck="false" aria-label="복사할 시점 태그"></textarea>
        <div class="vpc-actions">
          <button type="button" class="vpc-copy" data-vpc-copy>복사</button>
          <span class="vpc-status" role="status" aria-live="polite"></span>
        </div>
        <div class="vpc-note" data-vpc-only="view">좌우 방향은 시드가 정함(대칭) · 원경 · 바로 위는 태그로 한계</div>
      </div>
    </div>`;
  const $ = sel => panel.body.querySelector(sel);
  const canvas = $('.vpc-canvas');
  const ctx = canvas.getContext ? canvas.getContext('2d') : null;
  const dpr = Math.max(1, Math.min(3, Number(win?.devicePixelRatio) || 1));
  canvas.width = Math.round(W * dpr);
  canvas.height = Math.round(H * dpr);

  // ── 상태 ──────────────────────────────────────────────────────────────
  function readState() {
    try { return normalizeViewpoint(JSON.parse(storage?.getItem(STATE_KEY) || '{}')); } catch { return normalizeViewpoint({}); }
  }
  function writeState() {
    try { storage?.setItem(STATE_KEY, JSON.stringify(view)); } catch { /* 이번 실행에만 산다 */ }
  }
  function readGaze() {
    try { return normalizeGaze(JSON.parse(storage?.getItem(GAZE_KEY) || '{}')); } catch { return normalizeGaze({}); }
  }
  function readTab() {
    try { return storage?.getItem(TAB_KEY) === 'gaze' ? 'gaze' : 'view'; } catch { return 'view'; }
  }
  function setGaze(next) {
    gaze = normalizeGaze({...gaze, ...next});
    try { storage?.setItem(GAZE_KEY, JSON.stringify(gaze)); } catch { /* 이번 실행에만 산다 */ }
    render();
  }
  function setTab(next) {
    tab = next === 'gaze' ? 'gaze' : 'view';
    try { storage?.setItem(TAB_KEY, tab); } catch { /* 이번 실행에만 산다 */ }
    render();
  }
  /** {az?, pitch?, radius?} 를 바꾼다. 방위는 앞 / 뒤 반구 + 대칭 yaw 로 바꿔 수식에 넘긴다. */
  function move(next) {
    if (Number.isFinite(next.az)) az = wrap(next.az);
    view = normalizeViewpoint({
      ...view, ...azimuthToViewpoint(az),
      ...(Number.isFinite(next.pitch) ? {pitch: next.pitch} : {}),
      ...(Number.isFinite(next.radius) ? {radius: next.radius} : {}),
    });
    writeState();
    render();
  }

  function result() {
    const r = convertViewpoint(view);
    return {...r, text: formatViewpointTags(r.tags, getMode())};
  }
  /** 지금 탭의 넣을 글. */
  function currentText() {
    return tab === 'gaze' ? gazeTags(gaze).join(', ') : result().text;
  }
  /** 장면을 그리는 카메라 = 관찰점 C. */
  function viewCam() {
    return {az, pitch: view.pitch, radius: view.radius};
  }

  function render() {
    const r = result();
    const rear = view.hemisphere === 'rear';
    const badge = $('[data-vpc-hemi]');
    badge.textContent = rear ? '후면' : '전면';
    badge.classList.toggle('is-rear', rear);
    $('.vpc-summary').textContent = r.summary;
    // X / Y / Z 숫자 줄과 가중치 칩은 뺐다(사용자 지시 2026-10-17) - 요약 한 줄 + 넣을 글로 충분하다.
    const range = $('[data-vpc-range="radius"]');
    if (range && Number(range.value) !== view.radius) range.value = String(view.radius);
    panel.body.querySelectorAll('[data-vpc-tab]').forEach(b => b.setAttribute('aria-selected', String(b.dataset.vpcTab === tab)));
    panel.body.querySelectorAll('[data-vpc-page]').forEach(page => { page.hidden = page.dataset.vpcPage !== tab; });
    panel.body.querySelectorAll('[data-vpc-only]').forEach(el => { el.hidden = el.dataset.vpcOnly !== tab; });
    $('.vpc').classList.toggle('is-gaze', tab === 'gaze');
    renderGaze();
    const ta = $('.vpc-text');
    ta.value = currentText();
    ta.placeholder = tab === 'gaze' ? '시선을 고르면 여기에 태그가 나옵니다' : '';
    ta.setAttribute('aria-label', tab === 'gaze' ? '복사할 시선 태그' : '복사할 시점 태그');
    draw();
  }

  function renderGaze() {
    const picked = GAZE_GROUPS.map(g => gazeLabel(g.key, gaze[g.key])).filter(Boolean);
    $('.vpc-gaze-summary').textContent = picked.join(' · ') || '정하지 않음';
    panel.body.querySelectorAll('[data-vpc-gaze-pick]').forEach(el => { el.textContent = gazeLabel(el.dataset.vpcGazePick, gaze[el.dataset.vpcGazePick]); });
    panel.body.querySelectorAll('[data-vpc-gaze]').forEach(b => {
      const on = gaze[b.dataset.vpcGazeKey] === b.dataset.vpcGaze;
      b.classList.toggle('is-on', on);
      b.setAttribute('aria-pressed', String(on));
    });
  }

  // ── C 에서 본 장면 ─────────────────────────────────────────────────────
  // 세계 좌표: 인물 판은 원점, 정면이 +Z, 그녀의 왼쪽이 +X, 위 +Y.
  // C = (sin az · cos p, sin p, cos az · cos p) x 거리. 화면 오른쪽 = 시선 f 와 위(+Y)의 외적 f x Y = (-f.z, 0, f.x).
  function cameraPoint() {
    const cam = viewCam();
    const p = rad(Math.max(-88, Math.min(88, cam.pitch)));   // 바로 위 / 아래에서는 화면 오른쪽이 정해지지 않는다
    const d = cam.radius * CAM_SCALE;
    return [Math.sin(rad(cam.az)) * Math.cos(p) * d, Math.sin(p) * d, Math.cos(rad(cam.az)) * Math.cos(p) * d];
  }
  function basis(c) {
    const len = Math.hypot(...c);
    const f = c.map(v => -v / len);
    const rl = Math.hypot(f[2], f[0]) || 1;
    const r = [-f[2] / rl, 0, f[0] / rl];
    const u = [r[1] * f[2] - r[2] * f[1], r[2] * f[0] - r[0] * f[2], r[0] * f[1] - r[1] * f[0]];
    return {f, r, u};
  }
  function projector() {
    const c = cameraPoint();
    const b = basis(c);
    const dot = (a, v) => a[0] * v[0] + a[1] * v[1] + a[2] * v[2];
    return {
      cam: c,
      at(p) {
        const d = [p[0] - c[0], p[1] - c[1], p[2] - c[2]];
        const z = dot(d, b.f);
        return {x: W / 2 + (dot(d, b.r) / z) * FOCAL, y: H / 2 + 8 - (dot(d, b.u) / z) * FOCAL, z};
      },
    };
  }
  function path(P, points) {
    ctx.beginPath();
    points.forEach((p, i) => { const q = P.at(p); if (i) ctx.lineTo(q.x, q.y); else ctx.moveTo(q.x, q.y); });
    ctx.closePath();
  }
  function draw() {
    if (!ctx || !panel.isOpen() || tab !== 'view') return;   // 시선 탭에는 장면이 없다
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    ctx.lineWidth = 1;
    const P = projector();
    const FLOOR = -0.75;
    // 발밑 고리 셋과 정면 화살표
    ctx.strokeStyle = 'rgba(140,160,200,.22)';
    for (const ring of [0.6, 1.0, 1.4]) {
      ctx.beginPath();
      for (let a = 0; a <= 360; a += 6) {
        const q = P.at([Math.sin(rad(a)) * ring, FLOOR, Math.cos(rad(a)) * ring]);
        if (a) ctx.lineTo(q.x, q.y); else ctx.moveTo(q.x, q.y);
      }
      ctx.stroke();
    }
    // 인물 판 - C 가 앞쪽(+Z)에 있으면 앞면(정면 그림), 뒤쪽이면 뒷면(뒷모습 그림). 정면 화살표는 허리 높이(사용자 지시 2026-10-17) -
    // 판보다 카메라 쪽에 있을 때만 판 위에 그린다.
    const front = P.cam[2] >= 0;
    if (!front) drawFacingArrow(P);
    ctx.fillStyle = front ? 'rgba(133,183,235,.10)' : 'rgba(150,150,170,.08)';
    ctx.strokeStyle = front ? 'rgba(133,183,235,.55)' : 'rgba(154,154,176,.5)';
    path(P, [[-CARD_HALF, FLOOR, 0], [CARD_HALF, FLOOR, 0], [CARD_HALF, -FLOOR, 0], [-CARD_HALF, -FLOOR, 0]]);
    ctx.fill(); ctx.stroke();
    const sprite = front ? SPRITES.front : SPRITES.back;
    if (sprite.ready) {
      drawSprite(P, sprite.img, front);
    } else {
      const m = P.at([0, 0, 0]);
      ctx.fillStyle = front ? '#cfe2f7' : '#c8c8d8';
      ctx.font = '13px monospace';
      ctx.fillText(front ? '앞' : '뒤', m.x - 6, m.y + 5);
    }
    ctx.fillStyle = '#fac775';
    path(P, [[CARD_HALF, 0.35, 0], [CARD_HALF + 0.1, 0.35, 0], [CARD_HALF + 0.1, 0.55, 0], [CARD_HALF, 0.55, 0]]);
    ctx.fill();
    const l = P.at([CARD_HALF + 0.16, 0.45, 0]);
    ctx.font = '11px monospace';
    ctx.fillText('L', l.x - 3, l.y + 4);
    if (front) drawFacingArrow(P);
    const top = P.at([0, 0.75, 0]);
    ctx.fillStyle = 'rgba(160,170,200,.7)';
    ctx.font = '11px monospace';
    ctx.fillText('1girl', top.x - 16, top.y - 6);
    // 나침반 - 위에서 본 지도(아래 = 정면, 오른쪽 = 그녀의 왼쪽)
    const cx = W - 36, cy = 36;
    ctx.strokeStyle = 'rgba(140,160,200,.5)';
    ctx.beginPath(); ctx.arc(cx, cy, 22, 0, Math.PI * 2); ctx.stroke();
    ctx.fillStyle = 'rgba(230,168,74,.7)';
    ctx.beginPath(); ctx.moveTo(cx, cy + 8); ctx.lineTo(cx - 4, cy); ctx.lineTo(cx + 4, cy); ctx.closePath(); ctx.fill();
    ctx.fillStyle = '#e6a84a';
    const camAz = viewCam().az;
    ctx.beginPath(); ctx.arc(cx + Math.sin(rad(camAz)) * 22, cy + Math.cos(rad(camAz)) * 22, 4, 0, Math.PI * 2); ctx.fill();
  }

  // 정면 화살표 - 허리 높이(y = 0)에서 앞(+Z)으로. 가로 · 세로 날개를 엇갈려 어느 높이에서 봐도 납작하게 사라지지 않는다.
  function drawFacingArrow(P) {
    ctx.strokeStyle = 'rgba(230,168,74,.85)';
    ctx.lineWidth = 1.4;
    const a = P.at([0, 0, 0.04]), b = P.at([0, 0, 0.5]);
    ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
    ctx.lineWidth = 1;
    ctx.fillStyle = 'rgba(230,168,74,.75)';
    path(P, [[-0.1, 0, 0.5], [0.1, 0, 0.5], [0, 0, 0.82]]);
    ctx.fill();
    path(P, [[0, -0.1, 0.5], [0, 0.1, 0.5], [0, 0, 0.82]]);
    ctx.fill();
  }
  // 그림을 판(z = 0 평면)에 붙인다. 2D 캔버스엔 원근 그리기가 없어 칸을 삼각형으로 나눠 아핀 변환으로 그린다.
  // 앞면: 그림 왼쪽 = 그녀의 오른쪽(-X) - 정면 그림의 포니테일(그녀의 왼쪽)은 그림 오른쪽에 있다.
  // 뒷면(좌우를 뒤집어 둔 뒷모습): 그림 왼쪽 = 그녀의 왼쪽(+X). (처음 판은 부호가 반대라 앞면이 거울상이었다 - Codex 리뷰 2026-10-17.)
  function drawSprite(P, img, front) {
    const iw = img.naturalWidth, ih = img.naturalHeight;
    const half = (CARD_HEIGHT * iw) / ih / 2;
    const world = (u, v) => [(front ? 1 : -1) * (-half + (2 * half * u) / iw), CARD_HEIGHT / 2 - (CARD_HEIGHT * v) / ih, 0];
    const cols = 6, rows = 10;
    for (let i = 0; i < cols; i++) {
      for (let j = 0; j < rows; j++) {
        const u0 = (iw * i) / cols, u1 = (iw * (i + 1)) / cols, v0 = (ih * j) / rows, v1 = (ih * (j + 1)) / rows;
        const s = [[u0, v0], [u1, v0], [u1, v1], [u0, v1]];
        const d = s.map(([u, v]) => P.at(world(u, v)));
        drawTriangle(img, [s[0], s[1], s[2]], [d[0], d[1], d[2]]);
        drawTriangle(img, [s[0], s[2], s[3]], [d[0], d[2], d[3]]);
      }
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  function drawTriangle(img, [[u0, v0], [u1, v1], [u2, v2]], [p0, p1, p2]) {
    const den = u0 * (v1 - v2) + u1 * (v2 - v0) + u2 * (v0 - v1);
    if (!den) return;
    const a = (p0.x * (v1 - v2) + p1.x * (v2 - v0) + p2.x * (v0 - v1)) / den;
    const b = (p0.y * (v1 - v2) + p1.y * (v2 - v0) + p2.y * (v0 - v1)) / den;
    const c = (p0.x * (u2 - u1) + p1.x * (u0 - u2) + p2.x * (u1 - u0)) / den;
    const d = (p0.y * (u2 - u1) + p1.y * (u0 - u2) + p2.y * (u1 - u0)) / den;
    const e = (p0.x * (u1 * v2 - u2 * v1) + p1.x * (u2 * v0 - u0 * v2) + p2.x * (u0 * v1 - u1 * v0)) / den;
    const f = (p0.y * (u1 * v2 - u2 * v1) + p1.y * (u2 * v0 - u0 * v2) + p2.y * (u0 * v1 - u1 * v0)) / den;
    // 이음매가 비치지 않게 삼각형을 무게중심에서 조금 키워 자른다.
    const cx = (p0.x + p1.x + p2.x) / 3, cy = (p0.y + p1.y + p2.y) / 3;
    const grow = p => { const dx = p.x - cx, dy = p.y - cy, len = Math.hypot(dx, dy) || 1; return [p.x + (dx / len) * 0.6, p.y + (dy / len) * 0.6]; };
    ctx.save();
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.beginPath();
    [p0, p1, p2].map(grow).forEach(([x, y], k) => (k ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
    ctx.closePath();
    ctx.clip();
    ctx.setTransform(dpr * a, dpr * b, dpr * c, dpr * d, dpr * e, dpr * f);
    ctx.drawImage(img, 0, 0);
    ctx.restore();
  }
  for (const sprite of Object.values(SPRITES)) {
    if (!sprite.ready) sprite.waiters.add(draw);
  }

  // ── 끌기 · 휠 · 방향키 ─────────────────────────────────────────────────
  // 장면을 손으로 잡고 돌리는 느낌: 오른쪽으로 끌면 장면이 오른쪽으로 돈다(= 카메라는 왼쪽으로), 아래로 끌면 위에서 내려다본다.
  // 이동량만 쓴다 - 창이 확대 · 축소돼도(UI 배율) 손과 어긋나지 않는다.
  let drag = null;
  canvas.addEventListener('pointerdown', event => {
    if (event.button != null && event.button !== 0) return;
    drag = {x: event.clientX, y: event.clientY};
    try { canvas.setPointerCapture(event.pointerId); } catch { /* noop */ }
    canvas.classList.add('is-dragging');
    event.preventDefault();
  });
  canvas.addEventListener('pointermove', event => {
    if (!drag) return;
    const dx = event.clientX - drag.x, dy = event.clientY - drag.y;
    drag.x = event.clientX; drag.y = event.clientY;
    if (!dx && !dy) return;
    const cam = viewCam();
    move({az: cam.az - dx * DEG_PER_PX, pitch: cam.pitch + dy * PITCH_PER_PX});
  });
  const endDrag = () => { drag = null; canvas.classList.remove('is-dragging'); };
  canvas.addEventListener('pointerup', endDrag);
  canvas.addEventListener('pointercancel', endDrag);
  canvas.addEventListener('wheel', event => {
    event.preventDefault();
    if (!event.deltaY) return;
    move({radius: Math.round((viewCam().radius + (event.deltaY > 0 ? 0.2 : -0.2)) * 10) / 10});
  }, {passive: false});
  canvas.addEventListener('keydown', event => {
    const step = {ArrowLeft: [KEY_STEP, 0], ArrowRight: [-KEY_STEP, 0], ArrowUp: [0, -KEY_STEP], ArrowDown: [0, KEY_STEP]}[event.key];
    if (!step) return;
    event.preventDefault();
    const cam = viewCam();
    move({az: cam.az + step[0], pitch: cam.pitch + step[1]});
  });

  // ── 조작 ───────────────────────────────────────────────────────────────
  panel.body.addEventListener('input', event => {
    if (event.target?.dataset?.vpcRange === 'radius') move({radius: Number(event.target.value)});
  });
  panel.body.addEventListener('click', event => {
    const tabBtn = event.target.closest('[data-vpc-tab]');
    if (tabBtn) { setTab(tabBtn.dataset.vpcTab); return; }
    const chip = event.target.closest('[data-vpc-gaze]');
    if (chip) {
      const key = chip.dataset.vpcGazeKey, value = chip.dataset.vpcGaze;
      setGaze({[key]: gaze[key] === value ? '' : value});   // 칸마다 하나 · 다시 누르면 푼다
      return;
    }
    if (event.target.closest('[data-vpc-gaze-clear]')) { setGaze({dir: '', tgt: '', body: ''}); return; }
    const preset = event.target.closest('[data-vpc-preset]');
    if (preset) { move(PRESETS[Number(preset.dataset.vpcPreset)][1]); return; }
    if (event.target.closest('[data-vpc-copy]')) copy();
  });

  function status(text) {
    const el = $('.vpc-status');
    if (el) el.textContent = text;
  }
  // 복사가 이 창의 유일한 내보내기다 - 클립보드 API 가 막힌 곳(권한 · 브라우저 창)에서는 글 칸을 골라 execCommand 로
  // (이벤트 맵 · Fast Search 와 같은 예비 길). 그것도 막히면 글을 골라 둔 채 Ctrl+C 를 안내한다.
  async function copy() {
    const text = currentText();
    if (!text) { status('복사할 태그가 없습니다'); return; }
    let ok = false;
    try { await win.navigator.clipboard.writeText(text); ok = true; } catch { ok = false; }
    const ta = $('.vpc-text');
    if (!ok) {
      try { ta.focus(); ta.select(); ok = doc.execCommand('copy'); } catch { ok = false; }
    }
    if (ok) { status('복사했습니다'); return; }
    ta.focus(); ta.select();
    status('복사가 막혔습니다 - 글을 골라 두었으니 Ctrl+C 하세요');
    notify('클립보드에 쓰지 못했습니다', 'error');
  }

  render();

  return {
    el: panel.el,
    open: () => { panel.open(); if (panel.isCollapsed()) panel.expand(); render(); },
    close: () => panel.close(),
    toggle: () => { if (panel.isOpen()) panel.close(); else { panel.open(); render(); } },
    isOpen: () => panel.isOpen(),
    refresh: render,                       // 모드가 바뀌면 문법이 바뀐다
  };
}

function rad(deg) { return (deg * Math.PI) / 180; }
/** 방위를 -180 < a <= 180 으로. */
function wrap(a) {
  const w = ((a + 180) % 360 + 360) % 360 - 180;
  return w === -180 ? 180 : w;
}

function ensureStyle(doc) {
  if (doc.getElementById(STYLE_ID)) return;
  const style = doc.createElement('style');
  style.id = STYLE_ID;
  style.textContent = VPC_CSS;
  doc.head.appendChild(style);
}

const VPC_CSS = `
.dragpanel.vpc-window .dragpanel-body{overflow:auto;container-type:inline-size}
.dragpanel.vpc-window .dragpanel-slot{justify-content:flex-end}
.dragpanel.vpc-window .vpc-guide{height:16px;padding:0 6px;font-size:10px;line-height:14px}
.vpc-tabs{display:flex;gap:2px;padding:6px 12px 0;border-bottom:1px solid var(--border-dim)}
.vpc-tabs button{border:1px solid transparent;border-bottom:0;border-radius:5px 5px 0 0;background:transparent;color:var(--text-dim);padding:4px 12px;font:inherit;font-family:var(--font-mono);font-size:11px;cursor:pointer;margin-bottom:-1px}
.vpc-tabs button[aria-selected="true"]{background:rgba(255,255,255,.04);color:#dfe4ff;border-color:var(--border-dim)}
.vpc-page[hidden]{display:none}
.vpc-gaze-badge{border:1px solid rgba(127,224,200,.5);border-radius:4px;padding:1px 7px;color:#7fe0c8}
.vpc-gaze-summary{color:#fac775;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.vpc-gaze-clear{border:0;background:transparent;color:var(--text-dim);font:inherit;cursor:pointer;padding:0 2px}
.vpc-gaze-clear:hover{color:var(--text-primary)}
.vpc.is-gaze{grid-template-columns:minmax(0,1fr)}
.vpc-gaze-cols{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:8px 0 10px}
.vpc-gaze-col{display:flex;flex-wrap:wrap;align-content:flex-start;gap:4px;border:1px solid var(--border-dim);border-radius:6px;padding:8px}
.vpc-gaze-col-head{flex:1 0 100%;display:flex;justify-content:space-between;gap:6px;color:var(--text-dim);margin-bottom:2px}
.vpc-gaze-pick{color:#fac775}
.vpc-gaze-chip{border:1px solid var(--border-dim);border-radius:4px;background:transparent;color:var(--text-primary);padding:3px 9px;font:inherit;cursor:pointer}
.vpc-gaze-chip:hover{background:rgba(255,255,255,.06)}
.vpc-gaze-chip.is-on{border-color:rgba(120,140,255,.7);background:rgba(120,140,255,.22);color:#dfe4ff}
.vpc [hidden]{display:none}
.vpc{display:grid;grid-template-columns:320px minmax(0,1fr);gap:12px;padding:10px 12px;font-family:var(--font-mono);font-size:11px;color:var(--text-primary)}
.vpc-canvas{display:block;width:320px;height:280px;touch-action:none;cursor:grab;border-radius:6px;background:#0d0d14;outline:none}
.vpc-canvas.is-dragging{cursor:grabbing}
.vpc-canvas:focus-visible{box-shadow:0 0 0 1px rgba(120,140,255,.7)}
.vpc-presets{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px}
.vpc-hint{color:var(--text-dim);font-size:10px;margin-top:5px}
.vpc-presets button,.vpc-actions button{border:1px solid var(--border-dim);border-radius:5px;background:rgba(255,255,255,.045);color:var(--text-primary);padding:3px 8px;font:inherit;cursor:pointer}
.vpc-presets button:hover,.vpc-actions button:hover{background:rgba(255,255,255,.08)}
.vpc-head{display:flex;align-items:center;gap:6px;margin-bottom:2px}
.vpc-hemi-badge{border:1px solid rgba(133,183,235,.45);border-radius:4px;padding:1px 7px;color:#85b7eb}
.vpc-hemi-badge.is-rear{border-color:rgba(154,154,176,.5);color:#c8c8d8}
.vpc-summary{color:#fac775}
.vpc-radius-row{display:flex;align-items:center;gap:8px;color:var(--text-dim);margin:10px 0 8px}
.vpc-radius{flex:1;min-width:0}
.vpc-text{width:100%;box-sizing:border-box;resize:vertical;background:var(--bg-input,#101019);border:1px solid var(--border-dim);border-radius:3px;color:var(--text-primary);font:inherit;padding:6px 8px}
.vpc-actions{display:flex;align-items:center;gap:6px;margin-top:8px;flex-wrap:wrap}
.vpc-actions .vpc-copy{border-color:rgba(120,140,255,.55);background:rgba(120,140,255,.18);color:#dfe4ff}
.vpc-status{color:var(--text-dim)}
.vpc-note{margin-top:8px;color:var(--text-dim);font-size:10px}
@container (max-width: 640px){.vpc{grid-template-columns:minmax(0,1fr)}.vpc-gaze-cols{grid-template-columns:minmax(0,1fr)}.vpc-canvas{width:100%;max-width:320px;height:auto;aspect-ratio:320/280}}
`;
