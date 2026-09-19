/** 믹스 큐 — 아티스트 여러 명을 순서·가중치와 함께 쌓는 **가로 썸네일 띠**.
 *
 *  리모컨 창 **안쪽, 격자 바로 위**에 산다(사용자 지정 2026-09-19). 왼쪽에서
 *  오른쪽으로 **삽입 순서**이고, 켜져 있는 칸만 조립에 들어간다. 조립 결과는 곧바로
 *  ARTIST PROMPT 칸으로 간다 - 그 칸이 Generate 와 Generate with Random Prompt 가 쓴다.
 *
 *      ┌ 믹스 띠 ─────────────────────────────┐
 *      │ ▣kouji ▣dairi │ ▣nasuuni │ ▣collab   │
 *      │  0.9    1.0   ⟨1⟩  1.15    ⟨2⟩ -1.0   │
 *      └──────────────────────────────────────┘
 *        └ 칸 = 썸네일·이름·가중치 세 상자   └ `│` = 앵커
 *
 *  ⚠️ **자료 모형은 평면 배열 하나**다(칸도 앵커도 같은 목록의 원소). 칸은 **바로 앞**
 *     앵커에 속해서, 순서를 바꾸는 것이 곧 레이어 이동이 된다 - 앵커별로 묶어 그리면
 *     그 등식이 깨지고 '묶음 밖으로 끌기' 를 따로 배선해야 한다.
 *  ⚠️ **서식은 여기서 만들지 않는다.** `formatToken` 을 받아 쓴다 - NAI/Anima/SD 표기가
 *     이미 `artistThumbTab` 에 있고, 두 곳에서 만들면 반드시 어긋난다.
 *  ⚠️ 칸은 격자 카드를 **재사용하지 않는다**. 격자 카드는 `<button>` 이라 안에 가중치
 *     `<input>` 을 넣을 수 없고, `.artist-thumb-card` 에 걸린 상태 옷(favorite/active/
 *     batch-*)이 통째로 따라온다. 그림 상자(`.artist-thumb-card-image`)만 빌린다.
 */

import { anchorToken, nextAnchorId } from './artistAnchors.mjs?v=20260915-anchor1';
// ⚠️ 중개자는 **모든 곳에서 같은 주소**로 불러야 한다. 주소(쿼리 포함)가 다르면 모듈이
//    둘로 뜨고, 한쪽에 등록한 받는 쪽을 다른 쪽이 못 본다. 계약 시험이 대조한다.
import { dragBrokerFor } from './dragBroker.mjs?v=20260919-strip';

const COLLAB_ID = '__collab__';
const HOLD_FIRST_MS = 320;     // 누르고 있을 때 반복이 시작되기까지
// 그 뒤 0.5초마다 (사용자 지정). ⚠️ 0.1초마다로 두었더니 1초만 쥐어도 0.6 이
// 움직여 조절이 안 됐다 - 쥐는 것은 '성큼' 이지 '순식간' 이 아니다.
const HOLD_STEP_MS = 500;
const STEP = 0.01;             // 한 번 누르면 (사용자 지정)
// 길게 누를 때는 **0.1**씩(사용자 지정). 0.1 은 0.01 의 배수라 눈금이 어긋나지 않는다.
const HOLD_STEP = 0.1;

let seq = 0;
const nextId = () => `mq${++seq}`;

/** 0.01 씩 더하면 부동소수 찌꺼기가 붙는다(0.7000000000000001). 두 자리로 고정한다. */
function roundStep(value) {
  const n = Number.parseFloat(value);
  if (!Number.isFinite(n)) return 1;
  return Math.round(n * 100) / 100;
}

/** 꼬리 0 은 뗀다 - 44px 칸에 `0.90` 보다 `0.9` 가 낫다. */
function weightText(value) {
  return String(roundStep(value));
}

export function createMixQueuePanel({
  document: doc,
  escHtml = value => String(value ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'),
  showToast = () => {},
  // (artist, weight, {withPrefix}) => string   ⚠️ 서식의 단일 소유자
  formatToken = (artist, weight) => `${weight}::${artist}`,
  onChange = () => {},        // (조립된 문자열) => void
  onHoverBlock = () => {},    // (element, {artist}) => void   확대 보기 요청
  onLeaveBlock = () => {},
  // 임시 블럭의 가중치가 큐 안에서 바뀌었다 - 메인 슬라이더도 따라와야 한다(사용자 지정).
  // ⚠️ 이 콜백은 **큐가 원인일 때만** 부른다. 메인에서 들어온 값(`setTempWeight`)에
  //    다시 부르면 둘이 서로를 밀어 무한히 돈다.
  onTempWeight = () => {},
  // ── 앵커 ──
  // 표식이 아직 prefix/postfix 에 살아 있는가. 큐는 글을 안 갖고 있어 물어본다.
  hasAnchorIn = () => true,
  // 표식을 글에 넣어 달라 / 빼 달라(넣는 자리는 prefix 맨 뒤 - 사용자 지정).
  onAnchorAdd = () => {},
  onAnchorRemove = () => {},
  // 큐 블럭을 끌어 내기 시작했다(확대 보기 끄기 등).
  onDragStart = () => {},
  // (태그) => {kind, className}   메인 프롬프트와 **같은** 분류. 없으면 색을 안 칠한다.
  classifyTag = null,
} = {}) {
  const el = doc.createElement('div');
  el.className = 'mixq';
  el.hidden = true;
  // 머리줄도 아래 단추도 없다 - 띠는 리모컨 창 **안**이라 제 상자를 가질 자리가 없고,
  // 단추가 하던 일은 끌기(제거)와 우클릭(고정·비활성·제거)이 나눠 가졌다.
  el.innerHTML = `
    <div class="mixq-list" role="list"></div>
    <div class="mixq-menu" hidden role="menu"></div>
  `;
  const listEl = el.querySelector('.mixq-list');
  const menuEl = el.querySelector('.mixq-menu');
  const broker = dragBrokerFor(doc);

  /** 큐. 마지막의 collab 블럭은 못 지우지만 **움직일 수는 있다**(사용자 지정). */
  let blocks = [collabBlock()];
  let drag = null;       // {id, node, startX, moved, pointerId}
  let menuFor = '';
  let menuAt = -1;

  function collabBlock() {
    return {
      id: COLLAB_ID,
      artist: 'artist collaboration',
      weight: -1,
      withPrefix: false,     // `artist:` 를 붙이지 않는다
      enabled: false,        // 기본 꺼짐
      temp: false,
      locked: true,          // 제거 불가
      image: '',
    };
  }

  const find = id => blocks.find(b => b.id === id) || null;
  const tempBlock = () => blocks.find(b => b.temp && !isAnchor(b)) || null;

  // ── 앵커 ──────────────────────────────────────────────────────────────
  //  앵커는 **같은 목록 안의 줄**이다. 블럭은 바로 위 앵커에 속한다 - 그래서 끌어서
  //  순서를 바꾸는 것이 곧 '레이어 안으로 넣기' 가 된다(따로 배선할 것이 없다).
  const isAnchor = b => b?.kind === 'anchor';
  const anchorRows = () => blocks.filter(isAnchor);

  function anchorBlock(anchorId) {
    return {
      id: nextId(), kind: 'anchor', anchorId: String(anchorId),
      syncWeights: false,   // 앵커 정책: 그룹 첫 태그가 Master, 나머지가 Slave
      broken: false,        // 글에서 표식이 사라졌다
      locked: false, temp: false, enabled: true,
      artist: '', weight: 1, withPrefix: false, image: '',
    };
  }

  /** 이 블럭이 속한 앵커(위쪽에서 가장 가까운 것). 없으면 선행부다. */
  function ownerAnchor(block) {
    const at = blocks.indexOf(block);
    for (let i = at - 1; i >= 0; i -= 1) {
      if (isAnchor(blocks[i])) return blocks[i];
    }
    return null;
  }

  /** 한 앵커에 딸린 블럭들(다음 앵커 전까지). 순서 그대로 - 첫째가 Master 다. */
  function membersOf(anchor) {
    const at = blocks.indexOf(anchor);
    const out = [];
    for (let i = at + 1; i < blocks.length; i += 1) {
      if (isAnchor(blocks[i])) break;
      out.push(blocks[i]);
    }
    return out;
  }

  /** 글에서 표식이 사라졌는지 다시 본다. 사라지면 빨강, 돌아오면 원래대로 -
   *  ⚠️ **회복도 추적해야 한다**(사용자 지정). 표식을 옮기는 동안에는 잘라내기와
   *     붙여넣기 사이에서 잠깐 사라진다 - 그때마다 그룹이 영영 죽으면 못 쓴다. */
  function refreshAnchorHealth() {
    let changed = false;
    for (const row of anchorRows()) {
      const broken = !hasAnchorIn(row.anchorId);
      if (broken !== row.broken) { row.broken = broken; changed = true; }
    }
    return changed;
  }

  // ── 조립 ──────────────────────────────────────────────────────────────
  function tokensOf(list) {
    return list
      .filter(b => !isAnchor(b))
      .filter(b => b.enabled && String(b.artist || '').trim())
      .map(b => formatToken(b.artist, b.weight, {withPrefix: b.withPrefix}))
      .filter(Boolean);
  }

  /** 첫 앵커보다 **앞**에 있는 블럭들. 예전처럼 ARTIST PROMPT 칸으로 간다(사용자 지정).
   *  앵커가 하나도 없으면 큐 전체가 여기다 - 앵커를 안 쓰면 예전 그대로다. */
  function compose() {
    const at = blocks.findIndex(isAnchor);
    return tokensOf(at < 0 ? blocks : blocks.slice(0, at)).join(', ');
  }

  /** `{앵커 아이디: 합친 글}`. 표식이 깨진 앵커는 **보내지 않는다** - 서버가 짝 없는
   *  표식을 지우므로, 보내 봐야 갈 곳이 없고 조용히 사라지는 편이 낫다. */
  function composeGroups() {
    const out = {};
    for (const row of anchorRows()) {
      if (row.broken) continue;
      const text = tokensOf(membersOf(row)).join(', ');
      if (text) out[row.anchorId] = out[row.anchorId]
        ? `${out[row.anchorId]}, ${text}` : text;
    }
    return out;
  }

  function emit() {
    onChange(compose(), composeGroups());
  }

  // ── 그리기 ────────────────────────────────────────────────────────────
  /** 앵커 = 칸 사이의 **얇은 세로 막대**(`□□|□|□□`, 사용자 지정). 같은 목록에
   *  섞여 있으니 한눈에 '여기서부터 다른 자리' 라고 읽혀야 한다. */
  function anchorRowHtml(b) {
    const classes = ['mixq-anchor'];
    if (b.broken) classes.push('is-broken');
    if (b.syncWeights) classes.push('is-sync');
    const title = b.broken
      ? `${anchorToken(b.anchorId)} 를 프롬프트에서 찾지 못했습니다 - 우클릭으로 되돌리세요`
      : `${anchorToken(b.anchorId)} 자리에 아래 태그들이 들어갑니다`;
    return `<div class="${classes.join(' ')}" role="listitem"
                 data-mixq-id="${escHtml(b.id)}" title="${escHtml(title)}">
      <span class="mixq-anchor-mark">${escHtml(anchorToken(b.anchorId))}</span>
      ${b.syncWeights ? '<span class="mixq-anchor-tag">동기화</span>' : ''}
      ${b.broken ? '<span class="mixq-anchor-tag is-warn">표식 없음</span>' : ''}
    </div>`;
  }

  /** 이 블럭의 이름이 무슨 태그인가. 분류는 `artist:` 접두사를 스스로 읽으니
   *  **붙이기 전 이름**을 준다 - 안 그러면 접두사만 보고 전부 아티스트가 된다. */
  function nameTokenClass(block) {
    if (typeof classifyTag !== 'function') return '';
    let result = null;
    try { result = classifyTag(String(block.artist || '')); } catch (_) { return ''; }
    return result?.className || '';
  }

  /** 칸 하나 = **세 상자**(썸네일 · 이름 · 가중치, 사용자 지정).
   *
   *  ⚠️ 그림 상자만 격자에서 빌린다(`.artist-thumb-card-image`) - 잘라내기·확대 규칙이
   *     거기 있어서, 흉내 내면 같은 작가가 격자와 띠에서 다르게 잘린다.
   *  ⚠️ 그림이 없어도 칸은 **같은 크기**여야 한다 - 안 그러면 띠의 높이가 들쭉날쭉하다.
   */
  function blockHtml(b) {
    const classes = ['mixq-block'];
    if (!b.enabled) classes.push('is-off');
    if (b.temp) classes.push('is-temp');
    if (b.locked) classes.push('is-locked');
    const name = b.withPrefix ? `artist:${b.artist}` : b.artist;
    // 이름에 메인 프롬프트와 **같은** 분류색. 색인에 없는 이름은 색이 안 붙어
    // 그 자리에서 오타가 드러난다(사용자 지정: "실수하지 않게").
    const nameClass = ['mixq-name', nameTokenClass(b)].filter(Boolean).join(' ');
    const image = b.image
      ? `<img src="${escHtml(b.image)}" alt="" loading="lazy" draggable="false">`
      : `<span class="mixq-noimg">${b.locked ? 'collab' : 'No Image'}</span>`;
    return `<div class="${classes.join(' ')}" role="listitem"
                 data-mixq-id="${escHtml(b.id)}" data-artist="${escHtml(b.artist)}"
                 title="${escHtml(name)}">
      <span class="artist-thumb-card-image mixq-thumb">${image}</span>
      <span class="${nameClass}">${escHtml(name)}</span>
      <span class="mixq-weight-box">
        <button type="button" class="mixq-step" data-mixq-step="-1" aria-label="가중치 내리기">−</button>
        <input class="mixq-weight" type="text" inputmode="decimal"
               value="${escHtml(weightText(b.weight))}" aria-label="가중치">
        <button type="button" class="mixq-step" data-mixq-step="1" aria-label="가중치 올리기">+</button>
      </span>
      ${b.temp ? '<span class="mixq-badge">임시</span>' : ''}
    </div>`;
  }

  function render() {
    listEl.innerHTML = blocks.map(b => (isAnchor(b) ? anchorRowHtml(b) : blockHtml(b))).join('');
  }

  function refresh() {
    render();
    emit();
  }

  // ── 가중치 ────────────────────────────────────────────────────────────
  /** 가중치를 바꾸는 **모든 길**이 여기로 모인다 - 임시 블럭이면 메인 가중치도
   *  같이 움직여야 한다(사용자 지정). 길이 셋(+/- · 타이핑 · 커밋)이라 한 곳에
   *  모으지 않으면 넷째 길이 생길 때 또 빠뜨린다. */
  /** 앵커 정책: 그룹의 **첫** 아티스트가 Master, 나머지가 Slave(사용자 지정).
   *  ⚠️ 여기서 render() 를 부르면 누르고 있던 단추가 사라진다 - 칸만 직접 고친다. */
  function syncGroupWeights(anchor) {
    if (!anchor?.syncWeights) return;
    const members = membersOf(anchor);
    const master = members[0];
    if (!master) return;
    for (const slave of members.slice(1)) {
      slave.weight = master.weight;
      const input = listEl.querySelector(`[data-mixq-id="${CSS.escape(slave.id)}"] .mixq-weight`);
      if (input) input.value = weightText(slave.weight);
    }
  }

  function applyWeight(block, value) {
    block.weight = value;
    if (block.temp) onTempWeight(block.weight);
    const owner = ownerAnchor(block);
    // Master 를 움직였을 때만 번진다 - Slave 를 직접 만지는 것은 그 하나로 끝난다.
    if (owner?.syncWeights && membersOf(owner)[0] === block) syncGroupWeights(owner);
    emit();          // ⚠️ 여기서 render() 를 부르면 누르고 있는 단추가 사라진다
  }

  function bump(id, direction, step = STEP) {
    const block = find(id);
    if (!block) return;
    const next = roundStep(block.weight + direction * step);
    const input = listEl.querySelector(`[data-mixq-id="${CSS.escape(id)}"] .mixq-weight`);
    if (input) input.value = weightText(next);
    applyWeight(block, next);
  }

  let holdTimer = null;
  let holdRepeat = null;

  function stopHold() {
    if (holdTimer) { clearTimeout(holdTimer); holdTimer = null; }
    if (holdRepeat) { clearInterval(holdRepeat); holdRepeat = null; }
  }

  function startHold(id, direction) {
    stopHold();
    bump(id, direction);
    // 누르고 있으면 0.1초당 0.1씩(사용자 지정). 첫 반복 전에는 조금 기다린다 -
    // 한 번 누르려던 것이 두세 번 먹으면 미세 조정이 안 된다.
    holdTimer = setTimeout(() => {
      holdTimer = null;
      holdRepeat = setInterval(() => bump(id, direction, HOLD_STEP), HOLD_STEP_MS);
    }, HOLD_FIRST_MS);
  }

  // ── 우클릭 메뉴 (artist: 토글 · 비활성 · 제거) ─────────────────────────
  function menuHtmlFor(block) {
    // 빈 공간 - 여기에 새 앵커(사용자 지정: '이 자리에').
    if (!block) {
      return '<button type="button" data-mixq-menu="anchor-here">여기에 앵커 추가</button>';
    }
    if (isAnchor(block)) {
      return `
      <button type="button" data-mixq-menu="anchor-sync">${block.syncWeights ? '가중치 동기화 끄기' : '가중치 동기화'}</button>
      <button type="button" data-mixq-menu="anchor-restore"${block.broken ? '' : ' disabled'}>표식 되돌리기</button>
      <button type="button" data-mixq-menu="anchor-remove">앵커 제거</button>
    `;
    }
    return `
      <button type="button" data-mixq-menu="pin"${block.temp ? '' : ' disabled'}>이 자리에 고정</button>
      <button type="button" data-mixq-menu="prefix"${block.locked ? ' disabled' : ''}>${block.withPrefix ? '`artist:` 떼기' : '`artist:` 붙이기'}</button>
      <button type="button" data-mixq-menu="enabled">${block.enabled ? '비활성으로' : '다시 켜기'}</button>
      <button type="button" data-mixq-menu="remove"${block.locked ? ' disabled' : ''}>제거</button>
      <button type="button" data-mixq-menu="anchor-above">앵커 추가 · 이 왼쪽에</button>
      <button type="button" data-mixq-menu="anchor-below">앵커 추가 · 이 오른쪽에</button>
    `;
  }

  function openMenu(block, x, y) {
    menuFor = block ? block.id : '';
    menuEl.innerHTML = menuHtmlFor(block);
    menuEl.hidden = false;
    const box = el.getBoundingClientRect();
    const menu = menuEl.getBoundingClientRect();
    const left = Math.min(Math.max(4, x - box.left), box.width - menu.width - 4);
    const top = Math.min(Math.max(4, y - box.top), box.height - menu.height - 4);
    menuEl.style.left = `${Math.round(left)}px`;
    menuEl.style.top = `${Math.round(top)}px`;
  }

  function closeMenu() {
    menuFor = '';
    menuEl.hidden = true;
  }

  // ── 배선 ──────────────────────────────────────────────────────────────
  listEl.addEventListener('pointerdown', event => {
    const step = event.target.closest('[data-mixq-step]');
    if (!step) return;
    event.preventDefault();
    const id = step.closest('[data-mixq-id]')?.dataset.mixqId || '';
    startHold(id, Number(step.dataset.mixqStep) || 1);
  });
  doc.addEventListener('pointerup', stopHold);
  doc.addEventListener('pointercancel', stopHold);

  // 숫자 칸 위에서 휠 = 0.01 씩(사용자 지정). 값은 +/- 와 **같은 문**(bump)으로 간다 -
  // 임시 블럭이면 메인 가중치도 따라온다.
  // ⚠️ 휠 한 칸의 deltaY 는 **환경마다 다르다**(100 · 120 · 53 · 배율이 붙으면 150 -
  //    실측: 100 을 보냈는데 -150 으로 왔다). 픽셀 문턱으로 '한 칸' 을 정하면 한 칸에
  //    0.02 가 움직였다. 그래서 규칙은 크기가 아니라 **사건**이다:
  //      - 큰 delta 한 번(마우스 휠 한 칸) = 정확히 한 걸음
  //      - 작은 delta(터치패드가 수십 번 쏘는 것)만 모아서 WHEEL_NOTCH 마다 한 걸음
  // ⚠️ passive:false 로 걸어야 막을 수 있다. 안 막으면 값이 바뀌면서 목록도 같이 굴러간다.
  const WHEEL_NOTCH = 40;
  let wheelAcc = 0;
  let wheelFor = '';
  // ⚠️ 숫자 칸 위에서만 받다가 **칸 전체**로 넓혔다(사용자 지정 2026-09-19). 썸네일
  //    위에서 굴려도 아무 일이 없었으니 잃을 것이 없고, 1.01 만 한 과녁을 겨누게 하는
  //    것이 실제로 안 먹는 것처럼 보였다. 앵커·collab 는 가중치가 없어 그냥 지나간다.
  listEl.addEventListener('wheel', event => {
    const block = find(event.target.closest('[data-mixq-id]')?.dataset.mixqId || '');
    if (!block || isAnchor(block) || block.id === COLLAB_ID) return;
    const id = block.id;
    event.preventDefault();
    // 줄 단위(파이어폭스)·쪽 단위를 픽셀로 맞춘다.
    const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? 400 : 1;
    const dy = event.deltaY * unit;
    if (!dy) return;
    // 위로 굴리면(deltaY<0) 올라간다.
    if (Math.abs(dy) >= WHEEL_NOTCH) {
      wheelAcc = 0;
      bump(id, dy < 0 ? 1 : -1, STEP);
      return;
    }
    // 칸이 바뀌거나 방향이 바뀌면 모은 것을 버린다.
    if (wheelFor !== id || Math.sign(dy) !== Math.sign(wheelAcc)) wheelAcc = 0;
    wheelFor = id;
    wheelAcc += dy;
    if (Math.abs(wheelAcc) >= WHEEL_NOTCH) {
      bump(id, wheelAcc < 0 ? 1 : -1, STEP);
      wheelAcc = 0;
    }
  }, {passive: false});

  listEl.addEventListener('input', event => {
    const input = event.target.closest('.mixq-weight');
    if (!input) return;
    const block = find(input.closest('[data-mixq-id]')?.dataset.mixqId || '');
    if (!block) return;
    // 타이핑 도중에는 값을 다시 쓰지 않는다 - 캐럿이 끝으로 튄다.
    const parsed = Number.parseFloat(input.value);
    if (Number.isFinite(parsed)) applyWeight(block, parsed);
  });
  listEl.addEventListener('change', event => {
    const input = event.target.closest('.mixq-weight');
    if (!input) return;
    const block = find(input.closest('[data-mixq-id]')?.dataset.mixqId || '');
    if (!block) return;
    const next = roundStep(input.value);
    input.value = weightText(next);
    applyWeight(block, next);
  });

  /** 포인터 -> 몇 번째 앞에 넣을지. 재배치와 **같은 규칙**(이웃의 가운데 기준).
   *  빈 곳(모든 칸 뒤)이면 collab 칸 앞 - setTempArtist 와 같은 자리다.
   *
   *  ⚠️ 줄바꿈이 생기면서 X 만으로는 자리를 못 찾는다 - 둘째 줄 맨 왼쪽 칸이 첫 줄 맨
   *     오른쪽 칸보다 X 가 **작다**. 줄을 먼저 가리고(포인터가 이 칸의 줄보다 위면 그
   *     앞), 같은 줄 안에서만 가운데로 가른다. point 가 없으면 끝에 붙인다. */
  function insertionIndexAt(point) {
    const nodes = [...listEl.children];
    if (point) {
      for (let i = 0; i < nodes.length; i += 1) {
        const r = nodes[i].getBoundingClientRect();
        if (point.y < r.top) return i;
        if (point.y <= r.bottom && point.x < r.left + r.width / 2) return i;
      }
    }
    const collab = blocks.findIndex(b => b.id === COLLAB_ID);
    return collab < 0 ? blocks.length : collab;
  }

  /** 큐에 넣는다. 큐는 같은 작가를 두 번 허용한다 - 다른 앵커 밑이면 뜻이 다르다.
   *
   *  `asTemp` 는 **끌어다 놓은 길**만 쓴다(사용자 지정 2026-09-19): 새로 끌어온 칸이
   *  임시가 되고, 그 전에 임시였던 칸은 그 자리에 굳는다. 끌어올리는 행위 자체가
   *  '지금 이걸 보는 중' 이라는 뜻이라 - 고정하려고 딴 칸을 끌어오던 일이 없어진다.
   *  그룹 창의 [큐에 전부] 처럼 한꺼번에 담는 길은 임시를 만들지 않는다. */
  function insertArtists(items, point = null, {asTemp = false} = {}) {
    let at = insertionIndexAt(point);
    const added = [];
    for (const raw of items || []) {
      const artist = String(raw?.artist || '').trim();
      if (!artist) continue;
      const w = Number.parseFloat(raw.weight);
      const block = {
        id: nextId(), artist, weight: roundStep(Number.isFinite(w) ? w : 1),
        withPrefix: raw.withPrefix !== false, enabled: true, temp: false,
        locked: false, image: String(raw.image || ''),
      };
      blocks.splice(at, 0, block);
      at += 1;
      added.push(block);
    }
    if (added.length && asTemp) {
      // 그 전의 임시는 굳힌다 - 임시는 언제나 하나다(tempBlock 이 그 전제 위에 선다).
      for (const b of blocks) if (b.temp) b.temp = false;
      const last = added[added.length - 1];
      last.temp = true;
      onTempWeight(last.weight);
    }
    if (added.length) refresh();
    return added.length;
  }

  /** 띠를 벗어났다가 **다시 띠 위에** 놓았다 - 새로 만들지 말고 그 칸을 옮긴다.
   *  안 그러면 자리를 고치려던 손이 같은 작가를 둘로 불린다. */
  function moveBlockTo(id, point) {
    const block = find(id);
    if (!block) return false;
    const at = insertionIndexAt(point);
    const from = blocks.indexOf(block);
    if (from < 0) return false;
    blocks.splice(from, 1);
    blocks.splice(at > from ? at - 1 : at, 0, block);
    refresh();
    return true;
  }

  broker.registerZone(listEl, {
    kind: 'artist',
    // ⚠️ 제 칸도 받는다(예전에는 `!payload.sourceQueue` 로 거부했다). 띠에서는 밖으로
    //    나간 것이 **제거**라, 돌아온 칸을 안 받으면 되돌릴 길이 없다.
    canAccept: payload => payload?.kind === 'artist',
    accept: (payload, point) => {
      // ⚠️ 띠 자신의 재배치가 진행 중이면 받지 않는다 - 다시 그리면 그 칸이 죽는다.
      if (drag) return false;
      if (payload.sourceQueue && payload.sourceId) return moveBlockTo(payload.sourceId, point);
      return insertArtists([payload], point, {asTemp: true}) > 0;
    },
  });

  /** 칸을 누르면 켜고 끈다. 예전의 '고르기' 는 아래 단추 셋의 대상 지정이었는데
   *  그 단추들이 없어졌다 - 우클릭은 누른 칸을 직접 잡으므로 선택 상태가 필요 없다. */
  listEl.addEventListener('click', event => {
    if (swallowClick) { swallowClick = false; return; }
    if (event.target.closest('[data-mixq-step], .mixq-weight')) return;
    const block = find(event.target.closest('[data-mixq-id]')?.dataset.mixqId || '');
    if (!block || isAnchor(block)) return;
    block.enabled = !block.enabled;
    refresh();
  });

  listEl.addEventListener('contextmenu', event => {
    const host = event.target.closest('[data-mixq-id]');
    if (!host) {
      // 빈 공간 - 그래도 메뉴는 연다(사용자 지정: '혹은 이 자리에 (빈 공간)').
      event.preventDefault();
      menuAt = blocks.length;
      openMenu(null, event.clientX, event.clientY);
      return;
    }
    menuAt = blocks.indexOf(find(host.dataset.mixqId));
    event.preventDefault();
    const block = find(host.dataset.mixqId);
    if (block) openMenu(block, event.clientX, event.clientY);
  });

  /** 새 앵커를 목록의 `at` 자리에 끼우고, 표식을 글 맨 뒤에 넣어 달라고 알린다. */
  function addAnchorAt(at) {
    const used = anchorRows().map(r => r.anchorId);
    const row = anchorBlock(nextAnchorId(used));
    const where = Math.max(0, Math.min(Number.isFinite(at) ? at : blocks.length, blocks.length));
    blocks.splice(where, 0, row);
    // 표식이 글에 들어가기 전까지는 '깨진' 상태다 - 넣어 준 뒤 다시 잰다.
    row.broken = true;
    onAnchorAdd(row.anchorId);
    refresh();
    return row;
  }

  menuEl.addEventListener('click', event => {
    const action = event.target.closest('[data-mixq-menu]')?.dataset.mixqMenu;
    const at = menuAt;
    const block = find(menuFor);
    closeMenu();
    if (!action) return;
    if (action === 'anchor-here') { addAnchorAt(at < 0 ? blocks.length : at); return; }
    if (!block) return;
    if (action === 'anchor-above') { addAnchorAt(blocks.indexOf(block)); return; }
    if (action === 'anchor-below') { addAnchorAt(blocks.indexOf(block) + 1); return; }
    if (action === 'anchor-sync') {
      block.syncWeights = !block.syncWeights;
      if (block.syncWeights) syncGroupWeights(block);
      refresh();
      return;
    }
    if (action === 'anchor-restore') { onAnchorAdd(block.anchorId); refresh(); return; }
    if (action === 'anchor-remove') {
      blocks = blocks.filter(b => b !== block);
      onAnchorRemove(block.anchorId);
      refresh();
      return;
    }
    // 임시 칸을 정식으로. 예전 [현재 태그 삽입] 이 하던 일이다 - 단추 줄이 없어져
    // 우클릭으로 왔다(띠 안에서 자리를 옮겨도 고정된다, `endDrag`).
    if (action === 'pin') { block.temp = false; }
    else if (action === 'prefix') { if (block.locked) return; block.withPrefix = !block.withPrefix; }
    else if (action === 'enabled') block.enabled = !block.enabled;
    else if (action === 'remove') {
      if (block.locked) { showToast('이 블럭은 지울 수 없습니다.', 'error'); return; }
      blocks = blocks.filter(b => b.id !== block.id);
    }
    refresh();
  });
  // 메뉴는 **관심이 떠나면** 닫힌다 - 바깥 누름 · 바깥으로 간 초점 · Esc.
  // ⚠️ `.mixq` 안의 누름에만 걸어 두었더니 옆 판(postfix 칸)으로 초점이 가도 그대로
  //    떠 있었다(사용자 제보). document 의 캡처 단계에 건다 - 아래에서 이벤트를 삼켜도
  //    여기가 먼저다. 열리는 순서도 맞다: 우클릭의 pointerdown 이 먼저 와서 (닫힌 메뉴에)
  //    아무 일도 안 하고, 그 뒤 contextmenu 가 연다.
  const closeMenuIfOutside = event => {
    if (menuEl.hidden) return;
    if (!menuEl.contains(event.target)) closeMenu();
  };
  doc.addEventListener('pointerdown', closeMenuIfOutside, true);
  doc.addEventListener('focusin', closeMenuIfOutside, true);
  doc.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !menuEl.hidden) closeMenu();
  }, true);

  // ── 끌어서 순서 바꾸기 ────────────────────────────────────────────────
  //  ⚠️ HTML5 drag-and-drop 을 **쓰지 않는다**. 그쪽은 브라우저가 유령 그림을 따로
  //     그리고 줄 자체는 제자리에 있어서, 손이 간 곳과 보이는 것이 어긋난다
  //     ("상당히 부자연스럽네요"). 덜 부드럽더라도 **이동을 따라가게** 한다
  //     (사용자 지정) - 이웃의 가운데를 지나는 순간 줄을 그 자리로 옮긴다.
  //     유령도 드롭 표시도 없다. 보이는 것이 곧 결과다.
  const DRAG_SLOP = 4;   // 이만큼은 움직여야 끌기다 - 아니면 고르기(클릭)가 죽는다
  // ⚠️ 세로 이탈은 **제거**다(사용자 지정). 되돌릴 수 없는 조작이라 문턱이 곧
  //    안전장치다 - 가로로 끌다가 손이 조금 흔들린 것을 삭제로 읽으면 안 된다.
  const LEAVE_SLOP = 28;

  /** 끌기가 끝난 뒤 따라오는 click 한 번을 삼킨다 - 안 그러면 놓자마자 선택이 토글된다. */
  let swallowClick = false;

  function blocksFromDom() {
    const byId = new Map(blocks.map(b => [b.id, b]));
    const order = [...listEl.children].map(node => node.dataset.mixqId);
    const next = order.map(id => byId.get(id)).filter(Boolean);
    // 목록에 없던 것이 있으면 버리지 않는다(방어) - 길이가 맞을 때만 갈아 끼운다.
    if (next.length === blocks.length) blocks = next;
  }

  /** 칸을 **원래 자리로 되돌리고** 중개자에게 넘긴다.
   *
   *  놓는 곳이 판정을 정한다: 받는 쪽(그룹 창·띠 자신)에 놓이면 복사·이동,
   *  **아무 데도 안 놓이면 제거**(사용자 지정: "믹스 모드 레이어에서 드래그 드롭 하면 제거").
   *  ⚠️ Esc·pointercancel 은 제거가 **아니다**. 중개자가 `cancelled` 로 갈라 준다 -
   *     안 그러면 끌기를 물린 사용자가 칸을 잃는다(되돌릴 수 없다).
   */
  function handOffToBroker(event) {
    const block = find(drag.id);
    const node = drag.node;
    const home = listEl.children[drag.startIndex] || null;
    if (home !== node) listEl.insertBefore(node, home);
    blocksFromDom();
    node.classList.remove('is-dragging');
    // ⚠️ 포인터 캡처를 **먼저** 푼다. 쥔 채로 넘기면 중개자의 `elementFromPoint` 가
    //    늘 이 목록을 돌려줘 받는 쪽을 못 찾는다.
    try { listEl.releasePointerCapture(drag.pointerId); } catch { /* 이미 풀림 */ }
    drag = null;
    // ⚠️ 여기서 swallowClick 을 세우지 않는다. 놓는 곳은 다른 창이라 그 click 은 띠로
    //    안 온다 - 세워 두면 사용자의 **다음 진짜 클릭**을 삼킨다.
    if (!block || isAnchor(block) || !String(block.artist || '').trim()) return;
    onDragStart();
    broker.takeOver(event, {
      kind: 'artist',
      artist: block.artist,
      weight: block.weight,
      image: block.image || '',
      label: block.withPrefix ? `artist:${block.artist}` : block.artist,
      sourceQueue: true,
      sourceId: block.id,
    }, {
      onEnd: (dropped, {cancelled = false} = {}) => {
        if (dropped || cancelled) return;
        // 잠긴 칸(collab)은 단추로도 못 지운다 - 끌기로도 못 지운다.
        if (block.locked) { showToast('이 블럭은 지울 수 없습니다.', 'error'); return; }
        if (!blocks.includes(block)) return;
        blocks = blocks.filter(b => b !== block);
        refresh();
        showToast(`'${block.artist}' 를 뺐습니다.`, 'info');
      },
    });
  }

  function endDrag() {
    if (!drag) return;
    const moved = drag.moved;
    const id = drag.id;
    drag.node.classList.remove('is-dragging');
    try { listEl.releasePointerCapture(drag.pointerId); } catch { /* 이미 풀림 */ }
    drag = null;
    if (!moved) return;
    swallowClick = true;
    // 손으로 자리를 옮긴 칸은 **내 것**이다 - 임시로 두면 다음 격자 클릭에 갈린다.
    const block = find(id);
    if (block?.temp) block.temp = false;
    refresh();          // 순서가 바뀌었으니 조립을 다시 낸다
  }

  listEl.addEventListener('pointerdown', event => {
    if (event.button !== 0) return;
    // +/- 는 누르고 있는 조작이 따로 있어 끌기가 아니다.
    if (event.target.closest('[data-mixq-step], .mixq-menu')) return;
    // 가중치 칸은 **편집 중(초점 있음)일 때만** 뺀다. 통째로 빼 두었더니 줄 왼쪽 1/3 이
    // 죽은 자리가 되어 "안 따라간다" 로 보였다(실측: 손이 44px 칸에 내려갔다).
    // 그냥 누르면 초점이 가고, 누른 채 움직이면 줄이 끌린다.
    const weightBox = event.target.closest('.mixq-weight');
    if (weightBox && doc.activeElement === weightBox) return;
    const host = event.target.closest('[data-mixq-id]');
    if (!host) return;
    drag = {id: host.dataset.mixqId, node: host,
            startX: event.clientX, startY: event.clientY,
            startIndex: [...listEl.children].indexOf(host),
            moved: false, pointerId: event.pointerId};
  });

  listEl.addEventListener('pointermove', event => {
    if (!drag) return;
    if (!drag.moved) {
      // ⚠️ 가로 거리만 재다가 **거리**로 바꿨다. 줄바꿈이 생긴 뒤로는 바로 아랫줄로
      //    내리는 것이 뜻 있는 움직임인데, 가로만 재면 그 손이 영영 안 잡힌다
      //    (띠 밖으로 곧장 내려 빼는 것도 마찬가지로 안 잡혔다).
      if (Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) < DRAG_SLOP) return;
      drag.moved = true;
      drag.node.classList.add('is-dragging');
      onLeaveBlock();                       // 끄는 동안 확대 보기는 방해만 된다
      try { listEl.setPointerCapture(drag.pointerId); } catch { /* 옛 브라우저 */ }
    }
    event.preventDefault();
    // **세로로** 띠를 벗어나면 중개자에게 넘긴다 - 가로는 순서 바꾸기라 못 쓴다.
    // 가로 이탈은 넣지 않는다: 띠 끝에 놓으려다 옆으로 조금 넘치는 것이 자연스럽다.
    const box = listEl.getBoundingClientRect();
    if (event.clientY < box.top - LEAVE_SLOP || event.clientY > box.bottom + LEAVE_SLOP) {
      handOffToBroker(event);
      return;
    }
    const over = [...listEl.children].find(node => {
      if (node === drag.node) return false;
      const rect = node.getBoundingClientRect();
      // ⚠️ 줄이 여럿이면 X 만으로는 **다른 줄의 같은 X** 칸이 먼저 걸린다.
      return event.clientY >= rect.top && event.clientY <= rect.bottom
          && event.clientX >= rect.left && event.clientX <= rect.right;
    });
    if (!over) return;
    const rect = over.getBoundingClientRect();
    const before = event.clientX < rect.left + rect.width / 2;
    const want = before ? over : over.nextSibling;
    if (want === drag.node) return;
    // ⚠️ 여기서 render() 를 부르면 끌고 있던 노드가 사라져 끌기가 죽는다.
    //    DOM 을 직접 옮기고, 목록은 그 순서에서 다시 읽는다.
    listEl.insertBefore(drag.node, want);
    blocksFromDom();
  });

  doc.addEventListener('pointerup', endDrag);
  doc.addEventListener('pointercancel', endDrag);

  // 칸에 마우스를 올리면 확대 보기. 격자와 같은 인프라를 쓰되 **띠 옆**에 뜬다.
  listEl.addEventListener('pointerover', event => {
    if (event.pointerType === 'touch') return;
    // ⚠️ 끄는 중에는 **부모까지 막는다**. 띠 자신의 끌기는 중개자를 안 거쳐서
    //    리모컨의 `broker.isDragging()` 가드가 안 걸린다 - 안 막으면 지나는 칸마다
    //    확대가 뜬다.
    if (drag?.moved) { event.stopPropagation(); onLeaveBlock(); return; }
    const host = event.target.closest('[data-mixq-id]');
    if (!host) { onLeaveBlock(); return; }
    const block = find(host.dataset.mixqId);
    if (block) onHoverBlock(host, block);
  });
  listEl.addEventListener('pointerout', event => {
    if (!event.relatedTarget || !listEl.contains(event.relatedTarget)) onLeaveBlock();
    else if (!event.relatedTarget.closest?.('[data-mixq-id]')) onLeaveBlock();
  });

  // ── 바깥에서 부르는 것 ────────────────────────────────────────────────
  return {
    el,
    isOpen: () => !el.hidden,
    setOpen(open) {
      el.hidden = !open;
      closeMenu();
      if (open) refresh();
      return !el.hidden;
    },
    /** 격자에서 고른 작가 - 임시 블럭 한 자리를 차지하고 다음 선택에 갈린다. */
    setTempArtist(artist, image = '') {
      const name = String(artist || '').trim();
      const temp = tempBlock();
      if (!name) {
        if (temp) blocks = blocks.filter(b => !b.temp);
        refresh();
        return;
      }
      if (temp) {
        temp.artist = name;
        temp.image = image;
      } else {
        // collab 블럭은 늘 마지막이 **기본**이지만 사용자가 옮겼다면 그 자리를 지킨다.
        const at = blocks.findIndex(b => b.id === COLLAB_ID);
        const block = {
          id: nextId(), artist: name, weight: 1, withPrefix: true,
          enabled: true, temp: true, locked: false, image,
        };
        if (at < 0) blocks.push(block);
        else blocks.splice(at, 0, block);
      }
      refresh();
    },
    /** 임시 블럭의 가중치 - 리모컨의 슬라이더가 이걸 민다. */
    setTempWeight(value) {
      const temp = tempBlock();
      if (!temp) return false;
      // ⚠️ 메인에서 들어온 값이다 - `onTempWeight` 로 되돌려 부르지 않는다(서로 민다).
      temp.weight = roundStep(value);
      const input = listEl.querySelector(`[data-mixq-id="${CSS.escape(temp.id)}"] .mixq-weight`);
      if (input) input.value = weightText(temp.weight);
      emit();
      return true;
    },
    compose,
    composeGroups,
    /** 그룹 창의 [큐에 넣기] · [큐에 전부] 가 쓴다. 끝(collab 앞)에 넣는다. */
    insertArtists: items => insertArtists(items, null),
    /** 글이 바뀌었다 - 표식이 살아 있는지 다시 재고, 달라졌으면 다시 그린다.
     *  ⚠️ 표식을 옮기는 동안의 **일시 소실과 회복**이 이 길로 들어온다. */
    recheckAnchors() {
      if (refreshAnchorHealth()) refresh();
      else emit();
      return anchorRows().map(r => ({id: r.anchorId, broken: r.broken, sync: r.syncWeights}));
    },
    anchors: () => anchorRows().map(r => ({id: r.anchorId, broken: r.broken, sync: r.syncWeights})),
    blockFor: id => find(id),
    snapshot: () => blocks.map(b => ({...b})),
  };
}
