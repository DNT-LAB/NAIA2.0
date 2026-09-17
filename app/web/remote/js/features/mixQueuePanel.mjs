/** 믹스 큐 — 아티스트 여러 명을 순서·가중치와 함께 쌓는 판 (리모컨 전용).
 *
 *  리모컨의 확대 보기가 뜨던 자리에 붙는다. 큐는 위에서 아래로 **삽입 순서**이고,
 *  켜져 있는 블럭만 조립에 들어간다. 조립 결과는 곧바로 ARTIST PROMPT 칸으로 간다
 *  (사용자 지정) - 그 칸이 Generate 와 Generate with Random Prompt 가 쓰는 자리다.
 *
 *      ┌ 믹스 모드 ─────────────┐
 *      │ [−] 0.9 [+]  kouji     │ ← 끌어서 순서를 바꾼다
 *      │ [−] 1.0 [+]  dairi *   │ ← `*` = 임시(격자에서 방금 고른 것)
 *      │ [−]-1.0 [+]  collab ▨  │ ← 못 지우는 블럭. 기본 꺼짐
 *      ├────────────────────────┤
 *      │ [삽입] [삭제] [비활성] │
 *      └────────────────────────┘
 *
 *  ⚠️ **서식은 여기서 만들지 않는다.** `formatToken` 을 받아 쓴다 - NAI/Anima/SD 표기가
 *     이미 `artistThumbTab` 에 있고, 두 곳에서 만들면 반드시 어긋난다(오늘 한 번 겪었다).
 *  ⚠️ 우클릭 하나에 **세 가지**를 몰아 둔다(`artist:` 토글 · 비활성 · 제거) - 블럭이
 *     좁아 단추를 더 못 놓는다(사용자 지정).
 */

import { anchorToken, nextAnchorId } from './artistAnchors.mjs?v=20260915-anchor1';
// ⚠️ 중개자는 **모든 곳에서 같은 주소**로 불러야 한다. 주소(쿼리 포함)가 다르면 모듈이
//    둘로 뜨고, 한쪽에 등록한 받는 쪽을 다른 쪽이 못 본다. 계약 시험이 대조한다.
import { dragBrokerFor } from './dragBroker.mjs?v=20260917-grp1';

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
  // 고정 토글(자동 접힘 끄기). 상태는 리모컨이 쥔다 - 여기서는 누른 것만 알린다.
  onPin = () => {},
  // ── 앵커 ──
  // 표식이 아직 prefix/postfix 에 살아 있는가. 큐는 글을 안 갖고 있어 물어본다.
  hasAnchorIn = () => true,
  // 표식을 글에 넣어 달라 / 빼 달라(넣는 자리는 prefix 맨 뒤 - 사용자 지정).
  onAnchorAdd = () => {},
  onAnchorRemove = () => {},
  // [그룹] 단추 - 무엇을 보여 줄지는 주인이 정한다(그룹 목록·새 그룹·임시 창).
  onGroupsMenu = () => {},
  // 큐 블럭을 끌어 내기 시작했다(확대 보기 끄기 등).
  onDragStart = () => {},
} = {}) {
  const el = doc.createElement('div');
  el.className = 'mixq';
  el.hidden = true;
  el.innerHTML = `
    <div class="mixq-head">
      <span class="mixq-title">믹스 모드</span>
      <span class="mixq-hint">끌어서 순서 · 우클릭으로 더 보기</span>
      <button type="button" class="mixq-groups" title="아티스트 그룹 · 임시 창">그룹</button>
      <button type="button" class="mixq-pin" aria-pressed="false"
              title="고정 - 가만히 둬도 접히지 않습니다">📌</button>
    </div>
    <div class="mixq-list" role="list"></div>
    <div class="mixq-foot">
      <button type="button" class="mixq-btn" data-mixq-act="commit">현재 태그 삽입</button>
      <button type="button" class="mixq-btn" data-mixq-act="remove">선택 태그 삭제</button>
      <button type="button" class="mixq-btn" data-mixq-act="disable">선택 태그 비활성</button>
    </div>
    <div class="mixq-menu" hidden role="menu"></div>
  `;
  const listEl = el.querySelector('.mixq-list');
  const menuEl = el.querySelector('.mixq-menu');
  // 제목줄은 접혀도 남는 유일한 띠라, 고정 단추는 두 상태 모두에서 손이 닿는다.
  const pinEl = el.querySelector('.mixq-pin');
  const broker = dragBrokerFor(doc);
  el.querySelector('.mixq-groups').addEventListener('click', event => {
    onGroupsMenu(event.currentTarget);
  });
  pinEl.addEventListener('click', () => {
    const next = pinEl.getAttribute('aria-pressed') !== 'true';
    pinEl.setAttribute('aria-pressed', next ? 'true' : 'false');
    pinEl.classList.toggle('is-on', next);
    onPin(next);
  });

  /** 큐. 마지막의 collab 블럭은 못 지우지만 **움직일 수는 있다**(사용자 지정). */
  let blocks = [collabBlock()];
  let drag = null;       // {id, node, startY, moved, pointerId}
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
      selected: false,
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
      selected: false, locked: false, temp: false, enabled: true,
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
  /** 앵커 줄. 블럭과 **다른 모양**이어야 한다 - 같은 목록에 섞여 있으니
   *  한눈에 '여기서부터 다른 자리' 라고 읽혀야 한다. */
  function anchorRowHtml(b) {
    const classes = ['mixq-anchor'];
    if (b.broken) classes.push('is-broken');
    if (b.selected) classes.push('is-selected');
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

  function render() {
    listEl.innerHTML = blocks.map(b => {
      if (isAnchor(b)) return anchorRowHtml(b);
      const classes = ['mixq-block'];
      if (!b.enabled) classes.push('is-off');
      if (b.selected) classes.push('is-selected');
      if (b.temp) classes.push('is-temp');
      if (b.locked) classes.push('is-locked');
      const name = b.withPrefix ? `artist:${b.artist}` : b.artist;
      return `<div class="${classes.join(' ')}" role="listitem"
                   data-mixq-id="${escHtml(b.id)}" title="${escHtml(name)}">
        <button type="button" class="mixq-step" data-mixq-step="-1" aria-label="가중치 내리기">−</button>
        <input class="mixq-weight" type="text" inputmode="decimal"
               value="${escHtml(weightText(b.weight))}" aria-label="가중치">
        <button type="button" class="mixq-step" data-mixq-step="1" aria-label="가중치 올리기">+</button>
        <span class="mixq-name">${escHtml(name)}</span>
        ${b.temp ? '<span class="mixq-badge">임시</span>' : ''}
      </div>`;
    }).join('');
    paintFoot();
  }

  /** 아래 단추는 **대상이 있을 때만** 살아난다 - 단추가 켜지는 것이 곧 '고른 것이
   *  무엇에 쓰이는지' 의 설명이다(상태가 뜻을 못 전달한다는 제보). */
  function paintFoot() {
    const commit = el.querySelector('[data-mixq-act="commit"]');
    if (commit) commit.disabled = !tempBlock();
    const picked = blocks.filter(b => b.selected).length;
    el.querySelectorAll('[data-mixq-act="remove"], [data-mixq-act="disable"]')
      .forEach(btn => { btn.disabled = picked === 0; });
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
      <button type="button" data-mixq-menu="prefix"${block.locked ? ' disabled' : ''}>${block.withPrefix ? '`artist:` 떼기' : '`artist:` 붙이기'}</button>
      <button type="button" data-mixq-menu="enabled">${block.enabled ? '비활성으로' : '다시 켜기'}</button>
      <button type="button" data-mixq-menu="remove"${block.locked ? ' disabled' : ''}>제거</button>
      <button type="button" data-mixq-menu="anchor-above">앵커 추가 · 이 위에</button>
      <button type="button" data-mixq-menu="anchor-below">앵커 추가 · 이 아래에</button>
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

  /** 포인터 Y -> 몇 번째 앞에 넣을지. 재배치와 **같은 규칙**(이웃의 가운데 기준).
   *  빈 곳(모든 줄 아래)이면 collab 블럭 앞 - setTempArtist 와 같은 자리다. */
  function insertionIndexAt(clientY) {
    const nodes = [...listEl.children];
    for (let i = 0; i < nodes.length; i += 1) {
      const r = nodes[i].getBoundingClientRect();
      if (clientY < r.top + r.height / 2) return i;
    }
    const collab = blocks.findIndex(b => b.id === COLLAB_ID);
    return collab < 0 ? blocks.length : collab;
  }

  /** 정식 블럭으로 넣는다(임시가 아니다 - 임시는 다음 격자 클릭에 갈린다).
   *  큐는 같은 작가를 두 번 허용한다 - 다른 앵커 밑이면 뜻이 다르다. */
  function insertArtists(items, clientY = null) {
    let at = clientY == null ? insertionIndexAt(Infinity) : insertionIndexAt(clientY);
    const added = [];
    for (const raw of items || []) {
      const artist = String(raw?.artist || '').trim();
      if (!artist) continue;
      const w = Number.parseFloat(raw.weight);
      const block = {
        id: nextId(), artist, weight: roundStep(Number.isFinite(w) ? w : 1),
        withPrefix: raw.withPrefix !== false, enabled: true, temp: false,
        locked: false, selected: false, image: String(raw.image || ''),
      };
      blocks.splice(at, 0, block);
      at += 1;
      added.push(block);
    }
    if (added.length) refresh();
    return added.length;
  }

  broker.registerZone(listEl, {
    kind: 'artist',
    canAccept: payload => payload?.kind === 'artist' && !payload.sourceQueue,
    accept: (payload, point) => {
      // ⚠️ 큐 자신의 재배치가 진행 중이면 받지 않는다 - 다시 그리면 그 줄이 죽는다.
      if (drag) return false;
      return insertArtists([payload], point.y) > 0;
    },
  });

  /** 블럭을 누르면 고름 = 아래 두 단추의 대상. **하나만** 잡힌다(사용자 결정).
   *  여럿을 잡게 두면 몇 개가 걸려 있는지 계속 기억해야 하는데, 한 번에 여러 개를
   *  정리하는 일은 우클릭(블럭별 제거·비활성)이 이미 감당한다.
   *  다른 블럭을 누르면 선택이 옮겨 가고, 같은 블럭을 다시 누르면 풀린다. */
  function selectOnly(id) {
    const wanted = find(id);
    // 앵커 줄은 고르지 않는다 - 아래 두 단추는 아티스트 태그를 다루는 것이고,
    // 앵커에 할 일(동기화·복원·제거)은 전부 우클릭에 있다.
    if (isAnchor(wanted)) return;
    const turnOff = !wanted || wanted.selected;
    blocks.forEach(b => { b.selected = !turnOff && b === wanted; });
    // ⚠️ render() 를 부르면 스크롤이 튄다 - 칠만 다시 한다.
    listEl.querySelectorAll('[data-mixq-id]').forEach(node => {
      node.classList.toggle('is-selected', find(node.dataset.mixqId)?.selected === true);
    });
    paintFoot();
  }

  listEl.addEventListener('click', event => {
    if (swallowClick) { swallowClick = false; return; }
    if (event.target.closest('[data-mixq-step], .mixq-weight')) return;
    const host = event.target.closest('[data-mixq-id]');
    if (host) selectOnly(host.dataset.mixqId);
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
    if (action === 'prefix') { if (block.locked) return; block.withPrefix = !block.withPrefix; }
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

  /** 끌기가 끝난 뒤 따라오는 click 한 번을 삼킨다 - 안 그러면 놓자마자 선택이 토글된다. */
  let swallowClick = false;

  function blocksFromDom() {
    const byId = new Map(blocks.map(b => [b.id, b]));
    const order = [...listEl.children].map(node => node.dataset.mixqId);
    const next = order.map(id => byId.get(id)).filter(Boolean);
    // 목록에 없던 것이 있으면 버리지 않는다(방어) - 길이가 맞을 때만 갈아 끼운다.
    if (next.length === blocks.length) blocks = next;
  }

  /** 줄을 **원래 자리로 되돌리고** 중개자에게 넘긴다. 복사이므로 큐는 그대로여야 한다. */
  function handOffToBroker(event) {
    const block = find(drag.id);
    const node = drag.node;
    const home = listEl.children[drag.startIndex] || null;
    if (home !== node) listEl.insertBefore(node, home);
    blocksFromDom();
    node.classList.remove('is-dragging');
    try { listEl.releasePointerCapture(drag.pointerId); } catch { /* 이미 풀림 */ }
    drag = null;
    // ⚠️ 여기서 swallowClick 을 세우지 않는다. 놓는 곳은 다른 창이라 그 click 은 큐로
    //    안 온다 - 세워 두면 사용자의 **다음 진짜 클릭**을 삼킨다. 삼키기는 중개자가
    //    문서 단위로 한 번 한다.
    if (!block || isAnchor(block) || !String(block.artist || '').trim()) return;
    onDragStart();
    broker.takeOver(event, {
      kind: 'artist',
      artist: block.artist,
      weight: block.weight,
      image: block.image || '',
      label: block.withPrefix ? `artist:${block.artist}` : block.artist,
      sourceQueue: true,
    });
  }

  function endDrag() {
    if (!drag) return;
    const moved = drag.moved;
    drag.node.classList.remove('is-dragging');
    try { listEl.releasePointerCapture(drag.pointerId); } catch { /* 이미 풀림 */ }
    drag = null;
    if (!moved) return;
    swallowClick = true;
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
    drag = {id: host.dataset.mixqId, node: host, startY: event.clientY,
            startIndex: [...listEl.children].indexOf(host),
            moved: false, pointerId: event.pointerId};
  });

  listEl.addEventListener('pointermove', event => {
    if (!drag) return;
    if (!drag.moved) {
      if (Math.abs(event.clientY - drag.startY) < DRAG_SLOP) return;
      drag.moved = true;
      drag.node.classList.add('is-dragging');
      onLeaveBlock();                       // 끄는 동안 확대 보기는 방해만 된다
      try { listEl.setPointerCapture(drag.pointerId); } catch { /* 옛 브라우저 */ }
    }
    event.preventDefault();
    // 가로로 목록을 벗어나면 **복사 끌기**로 바꾼다(다른 창으로 가져가는 중).
    // 세로 이탈은 넣지 않는다 - 목록 끝에 놓으려다 아래로 조금 넘치는 것이 자연스럽다.
    const box = listEl.getBoundingClientRect();
    if (event.clientX < box.left - 6 || event.clientX > box.right + 6) {
      handOffToBroker(event);
      return;
    }
    const over = [...listEl.children].find(node => {
      if (node === drag.node) return false;
      const rect = node.getBoundingClientRect();
      return event.clientY >= rect.top && event.clientY <= rect.bottom;
    });
    if (!over) return;
    const rect = over.getBoundingClientRect();
    const before = event.clientY < rect.top + rect.height / 2;
    const want = before ? over : over.nextSibling;
    if (want === drag.node) return;
    // ⚠️ 여기서 render() 를 부르면 끌고 있던 노드가 사라져 끌기가 죽는다.
    //    DOM 을 직접 옮기고, 목록은 그 순서에서 다시 읽는다.
    listEl.insertBefore(drag.node, want);
    blocksFromDom();
  });

  doc.addEventListener('pointerup', endDrag);
  doc.addEventListener('pointercancel', endDrag);

  // 블럭에 마우스를 올리면 확대 보기(3-f). 격자 쪽과 달리 **믹스 판 옆**에 뜬다.
  listEl.addEventListener('pointerover', event => {
    if (event.pointerType === 'touch') return;
    if (drag?.moved) return;        // 끄는 중에는 확대 보기가 방해만 된다
    const host = event.target.closest('[data-mixq-id]');
    if (!host) { onLeaveBlock(); return; }
    const block = find(host.dataset.mixqId);
    if (block) onHoverBlock(host, block);
  });
  listEl.addEventListener('pointerout', event => {
    if (!event.relatedTarget || !listEl.contains(event.relatedTarget)) onLeaveBlock();
    else if (!event.relatedTarget.closest?.('[data-mixq-id]')) onLeaveBlock();
  });

  el.querySelector('.mixq-foot').addEventListener('click', event => {
    const action = event.target.closest('[data-mixq-act]')?.dataset.mixqAct;
    if (!action) return;
    if (action === 'commit') {
      const temp = tempBlock();
      if (!temp) { showToast('격자에서 아티스트를 먼저 고르세요.', 'error'); return; }
      temp.temp = false;
      refresh();
      return;
    }
    const picked = blocks.find(b => b.selected) || null;
    if (!picked) { showToast('블럭을 먼저 고르세요.', 'error'); return; }
    if (action === 'remove') {
      if (picked.locked) { showToast('이 블럭은 지울 수 없습니다.', 'error'); return; }
      blocks = blocks.filter(b => b !== picked);
    } else if (action === 'disable') {
      picked.enabled = !picked.enabled;
    }
    refresh();
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
          enabled: true, temp: true, locked: false, selected: false, image,
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
