/** 아티스트 그룹 창 — 그룹 하나를 떠 있는 창으로. 임시 창도 **같은 코드**다.
 *
 *  - 카드를 누르면 격자에서 고른 것과 같다(믹스 모드면 임시 블럭이 된다).
 *  - 카드를 끌면 다른 창·믹스 큐로 **복사**된다(원본은 그대로).
 *  - 창 몸통은 받는 쪽이다: 격자 카드·큐 블럭·다른 그룹 창 항목을 놓으면 들어온다.
 *    같은 창 안에서 끌어 놓으면 **순서 바꾸기**다.
 *  - 이미 있는 작가를 놓으면 거절 + 그 카드를 잠깐 강조한다.
 *
 *  ⚠️ 목록은 이 창이 들고 있지 않다. `store` 가 유일한 주인이고 창은 구독만 한다 -
 *     우클릭 메뉴로 등록하면 열린 창도 곧바로 바뀐다.
 *  ⚠️ `window.prompt()` 를 쓰지 않는다. Electron 렌더러는 prompt 를 구현하지 않는다.
 *     이름은 창 안의 인라인 칸으로 받는다 - 머리줄의 ✎ 가 그 칸을 편다.
 *  ⚠️ 임시/저장은 **레코드의 표**(`temp`)로 판단한다. 창을 만들 때 한 번 재 두면
 *     이름을 붙인 뒤에도 옛 판정이 남아 단추 이름이 안 바뀐다.
 *
 *  보기(벤치) 줄(사용자 지정 2026-09-26): [보기 ▾][⚙] … [선택][전체][미생성][생성 N].
 *   - 보기는 **공용**이고 그룹은 고른 것만 기억한다(`views.viewOf(groupId)`).
 *   - 보기를 고르면 카드가 그 보기의 그림이 된다. 없으면 기본 썸네일 위에 **반투명 검은 막 +
 *     미생성**(사용자 지정 - 흐리게가 아니라 막).
 *   - 선택 모드에서 카드를 누르면 고르기다(작가 고르기·끌기는 쉰다). [생성] 은 고른 작가를
 *     **격자 차례대로** 탭에 넘긴다 - 확인 팝업과 큐는 탭이 맡는다(돈이 드는 일은 한 곳에서).
 */
import {createDraggablePanel} from './draggablePanel.mjs?v=20260919-headdrag';
import {dragBrokerFor} from './dragBroker.mjs?v=20260919-strip';

const OPEN = new Set();   // 열린 그룹 창들 - 겹쳐 뜨지 않게 계단식으로 비킨다

export function openGroupWindows() {
  return [...OPEN];
}

export function createArtistGroupWindow({
  document: doc,
  window: win = (typeof window !== 'undefined' ? window : null),
  store,
  groupId,
  escHtml = v => String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'),
  showToast = () => {},
  describe = async () => ({}),     // (names[]) => {name: {image_url, known}}
  onPick = () => {},               // (artist) => void
  onSendToQueue = () => {},        // (items[]) => void
  onDragStart = () => {},          // 확대 보기 끄기 등
  onHoverCard = () => {},          // (card, {src, title, anchor}) => void   크게 보기
  onLeaveCard = () => {},
  onClosed = () => {},
  views = null,                    // 보기(벤치) 저장소 - 없으면 보기 줄을 안 그린다
  onEditView = () => {},           // (viewId) => void    보기 설정 창
  onNewView = () => {},            // (groupId) => void   지금 설정으로 새 구도
  onGenerateView = async () => false,   // ({viewId, artists}) => 넣었으면 true
  onStopQueue = () => {},          // 일괄 생성 중지(지금 한 장은 마저 끝난다)
} = {}) {
  const broker = dragBrokerFor(doc, win);
  const isTempNow = () => store.isTemp(groupId);
  const imageCache = new Map();    // artist -> image_url ('' = 그림 없음)
  const viewImages = new Map();    // `${view}\u0001${artist}` -> 그 보기의 그림 주소 ('' = 미생성)
  const viewKey = (view, artist) => `${view}\u0001${artist}`;
  const currentView = () => (views ? views.viewOf(groupId) : '');
  let selecting = false;           // 선택 모드
  const picked = new Set();        // 고른 작가들
  let menuEl = null;

  const panel = createDraggablePanel({
    document: doc,
    window: win,
    title: titleText(),
    variant: 'agw',
    // 창마다 제 자리를 기억한다. ⚠️ 임시 창들이 열쇠 하나를 나눠 쓰던 때는 서로의
    //    자리와 **접힘 상태까지** 덮어썼다 - 둘째 창을 접으면 첫째가 접힌 채 되살아났다.
    //    임시 그룹도 이제 서버에 살아남으므로 자리도 같이 오래 기억한다.
    storageKey: `agroup-${groupId}`,
    width: 300,
    minWidth: 220,
    maxWidth: 720,
    height: 380,
    resizable: true,
    // 기본은 **왼쪽 가장자리**. 리모컨은 오른쪽, 믹스 판은 그 왼쪽에 붙는다 -
    // 가운데쯤(right: 520)에 띄웠더니 1600 폭에서 믹스 판을 통째로 덮었다(놓을 자리를 가림).
    initial: {x: 24, y: 140},
    escHtml,
    onClose: () => teardown(),
  });
  panel.el.setAttribute('data-agw-id', groupId);
  // 이름 고치기는 **머리줄**에 둔다(사용자 지정) - 임시 창에 이름을 붙이는 것이 곧
  // 저장이라, 단추 줄 구석이 아니라 제목 옆에 있어야 손이 간다.
  const renameBtn = doc.createElement('button');
  renameBtn.type = 'button';
  renameBtn.className = 'agw-rename';
  renameBtn.textContent = '✎';
  panel.slot.appendChild(renameBtn);
  // 와일드카드 복사(사용자 지정 2026-09-26) - `__artist_group/이름__`, 관심 작가는 `__favorite_artist__`.
  // 파일에는 작가 이름만 있다 - 가중치·`artist:` 는 부르는 쪽이 감싼다.
  const copyWcBtn = doc.createElement('button');
  copyWcBtn.type = 'button';
  copyWcBtn.className = 'agw-rename agw-copywc';
  copyWcBtn.textContent = '⧉';
  panel.slot.appendChild(copyWcBtn);
  copyWcBtn.addEventListener('click', () => { void copyWildcard(); });
  renameBtn.addEventListener('click', () => {
    if (nameForm.hidden) showNaming();
    else hideNaming();
  });
  // 리모컨의 '바깥 누름' 판정에서 **안쪽**으로 친다 - 여기서 누르자마자 믹스 판이
  // 접히면 놓을 자리가 사라진다.
  panel.el.setAttribute('data-rctl-companion', '');

  panel.body.innerHTML = `
    <div class="agw-bar">
      <span class="agw-count"></span>
      <span class="agw-spacer"></span>
      <button type="button" class="agw-btn danger" data-agw-act="delete"></button>
    </div>
    <div class="agw-viewbar"${views ? '' : ' hidden'}>
      <select class="agw-view" title="보기 - 고른 벤치 조건으로 뽑은 그림을 봅니다"></select>
      <button type="button" class="agw-btn" data-agw-act="view-edit" title="보기 설정">⚙</button>
      <span class="agw-spacer"></span>
      <button type="button" class="agw-btn" data-agw-act="select-mode" title="카드를 눌러 고릅니다">선택</button>
      <button type="button" class="agw-btn" data-agw-act="select-all" title="모두 고르기 / 모두 풀기">전체</button>
      <button type="button" class="agw-btn" data-agw-act="select-missing" title="이 보기의 그림이 없는 작가만 고릅니다">미생성</button>
      <button type="button" class="agw-btn primary" data-agw-act="generate" title="고른 작가를 이 보기의 조건으로 뽑습니다">생성</button>
    </div>
    <div class="agw-progress" hidden>
      <span class="agw-prog-text"></span>
      <button type="button" class="agw-btn danger" data-agw-act="queue-stop"
              title="남은 대기열을 비웁니다. 지금 생성 중인 한 장은 마저 끝납니다">중지</button>
    </div>
    <form class="agw-name" hidden>
      <input class="agw-name-input" type="text" maxlength="40" spellcheck="false" placeholder="그룹 이름">
      <button type="submit" class="agw-btn">확인</button>
      <button type="button" class="agw-btn" data-agw-act="name-cancel">취소</button>
    </form>
    <div class="agw-grid" role="list"></div>
    <div class="agw-empty">여기로 썸네일을 끌어 오세요</div>
  `;
  const gridEl = panel.body.querySelector('.agw-grid');
  const emptyEl = panel.body.querySelector('.agw-empty');
  const countEl = panel.body.querySelector('.agw-count');
  const nameForm = panel.body.querySelector('.agw-name');
  const deleteBtn = panel.body.querySelector('[data-agw-act="delete"]');
  const nameInput = panel.body.querySelector('.agw-name-input');
  const viewSelect = panel.body.querySelector('.agw-view');
  const progressEl = panel.body.querySelector('.agw-progress');
  const progressText = panel.body.querySelector('.agw-prog-text');
  let progress = null;
  const viewBtn = sel => panel.body.querySelector(`[data-agw-act="${sel}"]`);

  function group() {
    return store.get(groupId);
  }

  function wildcardToken() {
    const name = group()?.wildcard;
    return name ? `__${name}__` : '';
  }

  async function copyWildcard() {
    const token = wildcardToken();
    if (!token) return;
    if (!(group()?.items || []).length) {
      showToast('빈 그룹은 와일드카드 파일이 없습니다 - 작가를 넣은 뒤 복사하세요.', 'info');
    }
    try {
      await win.navigator.clipboard.writeText(token);
    } catch {
      // 클립보드 권한이 없는 창(오래된 Electron 등) - 숨긴 칸으로 복사한다.
      const area = doc.createElement('textarea');
      area.value = token;
      area.style.position = 'fixed'; area.style.opacity = '0';
      doc.body.appendChild(area); area.select();
      try { doc.execCommand('copy'); } finally { area.remove(); }
    }
    showToast(`복사했습니다: ${token}`, 'success');
  }

  /** 제목 = 그룹 이름. 임시 창의 이름(`임시 창 N`)도 **서버가** 붙인 것이라
   *  화면에서 번호를 다시 세지 않는다 - 세던 때는 창마다 제목이 갈렸다. */
  function titleText() {
    return store.get(groupId)?.name || '그룹';
  }

  // ── 그리기 ────────────────────────────────────────────────────────────
  function cardHtml(item) {
    const view = currentView();
    const viewUrl = view ? (viewImages.get(viewKey(view, item.artist)) || '') : '';
    const url = viewUrl || imageCache.get(item.artist) || '';
    const img = url
      ? `<img src="${escHtml(url)}" alt="" loading="lazy" draggable="false">`
      : '<span class="agw-noimg">No Image</span>';
    // 보기를 골랐는데 그 보기의 그림이 아직 없다 - 기본 그림 위에 막(누군지는 알아보게).
    // 답을 받기 전('미확인')에는 막을 안 덮는다 - 깜빡이며 덮였다 걷히면 어지럽다.
    const known = view ? viewImages.has(viewKey(view, item.artist)) : false;
    const veil = view && known && !viewUrl ? '<span class="agw-veil">미생성</span>' : '';
    const weight = Number.isFinite(item.weight) && item.weight !== 1
      ? `<span class="agw-weight">${escHtml(String(item.weight))}</span>` : '';
    const isPicked = selecting && picked.has(item.artist);
    const check = selecting ? `<span class="agw-check" aria-hidden="true">${isPicked ? '✓' : ''}</span>` : '';
    return `<button type="button" class="agw-card${isPicked ? ' is-picked' : ''}${selecting ? ' is-selecting' : ''}"
                    role="listitem" data-artist="${escHtml(item.artist)}" title="${escHtml(item.artist)}">
      <span class="agw-img">${img}${veil}${check}</span>
      <span class="agw-label"><span class="agw-name-text">${escHtml(item.artist)}</span>${weight}</span>
    </button>`;
  }

  function render() {
    const g = group();
    if (!g) { panel.close(); return; }
    panel.setTitle(titleText());
    // ⚠️ 이름을 붙이면 임시가 아니다 - 단추 이름도 그 자리에서 따라와야 한다.
    //    한 번 그려 두면 '비우고 닫기' 가 저장 그룹에 남아 통째로 지워 버린다.
    const temp = isTempNow();
    // 관심 작가 그룹(`fixed`)은 관심 목록 그 자체라 이름을 바꾸거나 지울 수 없다.
    const fixed = Boolean(g.fixed);
    renameBtn.hidden = fixed;
    deleteBtn.hidden = fixed;
    deleteBtn.textContent = temp ? '비우고 닫기' : '삭제';
    deleteBtn.dataset.armed = '';
    renameBtn.title = temp ? '이름을 붙여 저장합니다' : '이름 바꾸기';
    copyWcBtn.hidden = !g.wildcard;
    copyWcBtn.title = g.wildcard ? `와일드카드 복사: __${g.wildcard}__ (작가 이름만 - artist: 는 감싸서 쓰세요)` : '';
    const items = g.items || [];
    countEl.textContent = `${items.length}명`;
    // 그룹에서 빠진 작가는 고름에서도 뺀다(남기면 [생성 N] 의 N 이 거짓말이 된다).
    const present = new Set(items.map(i => i.artist));
    for (const artist of [...picked]) if (!present.has(artist)) picked.delete(artist);
    renderViewbar();
    gridEl.innerHTML = items.map(cardHtml).join('');
    // 다시 그리면 올려 둔 카드가 사라진다 - 없는 카드를 크게 보여 주지 않는다.
    if (hoverCard && !hoverCard.isConnected) leaveHover();
    if (progress) setQueueProgress(progress);   // 다시 그리면 '지금 뽑는 카드' 표시가 사라진다
    emptyEl.hidden = items.length > 0;
    void fillImages(items);
  }

  // 서버의 describe 는 한 번에 2,000명까지만 답한다 - 넘는 목록(관심 작가 3천 명 등)은
  // 뒤쪽이 답 없이 '그림 없음' 으로 굳었다. 나눠서 묻는다.
  const DESCRIBE_CHUNK = 1000;

  async function fillImages(items) {
    const view = currentView();
    const missing = items.map(i => i.artist)
      .filter(a => !imageCache.has(a) || (view && !viewImages.has(viewKey(view, a))));
    if (!missing.length) return;
    let changed = false;
    for (let start = 0; start < missing.length; start += DESCRIBE_CHUNK) {
      const chunk = missing.slice(start, start + DESCRIBE_CHUNK);
      let described;
      // ⚠️ 실패한 조각은 기억하지 않는다 - '그림 없음' 으로 굳히면 다시 묻지 않는다.
      try { described = await describe(chunk, view) || {}; } catch { continue; }
      for (const artist of chunk) {
        const url = described[artist]?.image_url || '';
        if (!imageCache.has(artist)) {
          imageCache.set(artist, url);
          if (url) changed = true;
        }
        if (view) {
          viewImages.set(viewKey(view, artist), described[artist]?.view_image_url || '');
          changed = true;          // 막을 덮을지 말지가 이제 정해졌다
        }
      }
    }
    // ⚠️ 끄는 중에 다시 그려도 끌기는 산다(중개자가 값으로 들고 있다). 그래도 손 밑의
    //    카드가 바뀌면 어지러우니 끄는 중이면 한 박자 미룬다.
    if (!changed) return;
    if (broker.isDragging()) {
      const off = broker.subscribe(state => { if (state === 'end') { off(); render(); } });
      return;
    }
    render();
  }

  function flash(artist) {
    const card = gridEl.querySelector(`.agw-card[data-artist="${CSS.escape(artist)}"]`);
    if (!card) return;
    card.classList.remove('is-flash');
    void card.offsetWidth;          // 다시 켜야 애니메이션이 처음부터 돈다
    card.classList.add('is-flash');
    card.scrollIntoView({block: 'nearest'});
  }

  // ── 끌기: 원본 ────────────────────────────────────────────────────────
  gridEl.addEventListener('pointerdown', event => {
    const card = event.target.closest('.agw-card');
    if (!card || selecting) return;       // 고르는 중에는 끌지 않는다(누름이 곧 고르기)
    const artist = card.dataset.artist;
    const item = (group()?.items || []).find(i => i.artist === artist);
    broker.arm(event, {
      kind: 'artist',
      artist,
      weight: item?.weight ?? 1,
      image: imageCache.get(artist) || '',
      label: artist,
      sourceGroup: groupId,
    }, {onStart: () => { leaveHover(); onDragStart(); }});
  });

  // ── 끌기: 받는 쪽 ─────────────────────────────────────────────────────
  /** 포인터 자리 -> 몇 번째 앞에 넣을지. 격자라 가장 가까운 카드의 좌/우로 가른다. */
  function dropIndex(point) {
    const cards = [...gridEl.querySelectorAll('.agw-card')];
    if (!cards.length) return 0;
    let best = cards.length;
    let bestDist = Infinity;
    cards.forEach((card, index) => {
      const r = card.getBoundingClientRect();
      const cx = r.left + r.width / 2;
      const cy = r.top + r.height / 2;
      const dist = Math.hypot(point.x - cx, point.y - cy);
      if (dist < bestDist) {
        bestDist = dist;
        best = point.x < cx ? index : index + 1;
      }
    });
    return best;
  }

  const unzone = broker.registerZone(panel.body, {
    kind: 'artist',
    canAccept: payload => payload?.kind === 'artist' && Boolean(payload.artist),
    accept: (payload, point) => {
      void acceptDrop(payload, point);
      return true;
    },
  });

  async function acceptDrop(payload, point) {
    const g = group();
    if (!g) return;
    const names = (g.items || []).map(i => i.artist);
    // 같은 창 안에서 끌었다 = 순서 바꾸기.
    if (payload.sourceGroup === groupId) {
      const from = names.indexOf(payload.artist);
      let to = dropIndex(point);
      if (from < 0) return;
      if (to > from) to -= 1;
      if (to === from) return;
      names.splice(from, 1);
      names.splice(to, 0, payload.artist);
      try { await store.reorder(groupId, names); } catch (error) { showToast(`순서 저장 실패 — ${error.message}`, 'error'); }
      return;
    }
    // ⚠️ `has` 가 아니라 **값**을 본다. 한 번 '그림 없음'('') 으로 기억한 작가는 끌어 온
    //    그림을 받아 주지 않았다 - 모드가 달라 describe 가 못 찾은 작가가 영영 No Image 였다.
    if (payload.image && !imageCache.get(payload.artist)) imageCache.set(payload.artist, payload.image);
    try {
      const at = dropIndex(point);
      const result = await store.add(groupId, [{artist: payload.artist, weight: payload.weight}]);
      if (!result.added) {
        showToast(`${payload.artist} 은(는) 이미 있습니다.`, 'info');
        flash(payload.artist);
        return;
      }
      // 놓은 자리로 옮긴다(add 는 끝에 붙인다).
      const after = (store.get(groupId)?.items || []).map(i => i.artist);
      if (at < after.length - 1) {
        after.splice(after.indexOf(payload.artist), 1);
        after.splice(at, 0, payload.artist);
        await store.reorder(groupId, after);
      }
      flash(payload.artist);
    } catch (error) {
      showToast(`그룹에 넣지 못했습니다 — ${error.message}`, 'error');
    }
  }

  // ── 크게 보기 ─────────────────────────────────────────────────────────
  //  리모컨 격자·믹스 띠와 같은 확대 보기(사용자 지정 2026-09-25). 이 창 **옆**에 뜬다.
  //  ⚠️ 누를 때는 걷지 않는다(리모컨과 같은 규칙) - 크게 보면서 고르는 것이 쓸모다.
  const HOVER_DELAY_MS = 140;
  let hoverTimer = null;
  let hoverCard = null;

  function leaveHover() {
    if (hoverTimer) { clearTimeout(hoverTimer); hoverTimer = null; }
    if (!hoverCard) return;
    hoverCard = null;
    onLeaveCard();
  }

  function onPointer(event) {
    // 손가락은 hover 가 없다 · 끄는 중에는 지나는 카드마다 뜨면 방해만 된다.
    if (event.pointerType === 'touch' || broker.isDragging()) return;
    const card = event.target.closest('.agw-card');
    if (!card) { leaveHover(); return; }
    if (card === hoverCard) return;
    hoverCard = card;
    if (hoverTimer) clearTimeout(hoverTimer);
    hoverTimer = setTimeout(() => {
      hoverTimer = null;
      if (hoverCard !== card || !card.isConnected) return;
      const src = card.querySelector('img')?.getAttribute('src') || '';
      // 그림이 없으면 띄우지 않는다(리모컨과 같은 규칙).
      if (src) onHoverCard(card, {src, title: card.dataset.artist || '', anchor: panel.el.getBoundingClientRect()});
      else onLeaveCard();
    }, HOVER_DELAY_MS);
  }
  gridEl.addEventListener('pointerover', onPointer);
  gridEl.addEventListener('pointerout', event => {
    const next = event.relatedTarget;
    if (!next || !gridEl.contains(next) || !next.closest?.('.agw-card')) leaveHover();
  });
  gridEl.addEventListener('scroll', leaveHover);

  // ── 누르기 ────────────────────────────────────────────────────────────
  gridEl.addEventListener('click', event => {
    const card = event.target.closest('.agw-card');
    if (!card) return;
    if (selecting) { togglePick(card); return; }
    onPick(card.dataset.artist);
  });

  // ── 보기 · 고르기 ─────────────────────────────────────────────────────
  function renderViewbar() {
    if (!views || !viewSelect) return;
    const view = currentView();
    const list = views.views();
    viewSelect.innerHTML = [
      `<option value="">기본 썸네일</option>`,
      ...list.map(v => `<option value="${escHtml(v.id)}"${v.id === view ? ' selected' : ''}>${escHtml(v.name)}</option>`),
      `<option value="__new__">+ 새 구도</option>`,
    ].join('');
    viewSelect.value = view;
    viewBtn('view-edit').hidden = !view;
    viewBtn('select-mode').classList.toggle('is-on', selecting);
    viewBtn('select-missing').hidden = !view;
    const gen = viewBtn('generate');
    gen.hidden = !view;
    gen.disabled = !picked.size;
    gen.textContent = picked.size ? `생성 ${picked.size}` : '생성';
  }

  function setSelecting(next) {
    selecting = Boolean(next);
    if (!selecting) picked.clear();
    leaveHover();
    render();
  }

  function togglePick(card) {
    const artist = card.dataset.artist;
    if (picked.has(artist)) picked.delete(artist); else picked.add(artist);
    // 카드 하나만 고친다 - 3천 장을 다시 그리면 누를 때마다 0.1초가 든다.
    card.classList.toggle('is-picked', picked.has(artist));
    const mark = card.querySelector('.agw-check');
    if (mark) mark.textContent = picked.has(artist) ? '✓' : '';
    renderViewbar();
  }

  function pickWhere(test) {
    const items = group()?.items || [];
    const want = items.map(i => i.artist).filter(test);
    // 이미 전부 골라져 있으면 푼다(한 단추로 켜고 끄기).
    const all = want.length && want.every(a => picked.has(a));
    selecting = true;
    if (all) want.forEach(a => picked.delete(a)); else want.forEach(a => picked.add(a));
    render();
  }

  viewSelect?.addEventListener('change', async () => {
    const value = viewSelect.value;
    if (value === '__new__') {
      viewSelect.value = currentView();
      onNewView(groupId);
      return;
    }
    try { await views.select(groupId, value); } catch (error) { showToast(error.message, 'error'); }
  });

  const unsubViews = views ? views.subscribe(() => render()) : () => {};

  /** 일괄 생성 진행(탭이 부른다). null = 쉬는 중. 지금 뽑는 작가의 카드에 표시를 단다. */
  function setQueueProgress(next) {
    progress = next || null;
    progressEl.hidden = !progress;
    gridEl.querySelectorAll('.agw-card.is-busy').forEach(c => c.classList.remove('is-busy'));
    if (!progress) return;
    const stopBtn = progressEl.querySelector('[data-agw-act="queue-stop"]');
    progressText.textContent = progress.cancelling
      ? `중지하는 중 - ${progress.artist} 까지 끝냅니다`
      : `생성 중 ${Math.min(progress.done + 1, progress.total)}/${progress.total} · ${progress.artist}`;
    stopBtn.disabled = Boolean(progress.cancelling);
    if (progress.artist) {
      gridEl.querySelector(`.agw-card[data-artist="${CSS.escape(progress.artist)}"]`)?.classList.add('is-busy');
    }
  }

  /** 탭이 결과를 받으면 부른다 - 그 보기의 그 작가 카드만 새 그림으로. */
  function viewResult(viewId, artist, url) {
    if (!viewId || !artist) return;
    viewImages.set(viewKey(viewId, artist), url || '');
    if (viewId !== currentView()) return;
    const card = gridEl.querySelector(`.agw-card[data-artist="${CSS.escape(artist)}"]`);
    if (!card) return;
    const host = card.querySelector('.agw-img');
    host.querySelector('.agw-veil')?.remove();
    host.querySelector('.agw-noimg')?.remove();
    let img = host.querySelector('img');
    if (!img) { img = doc.createElement('img'); img.alt = ''; img.draggable = false; host.prepend(img); }
    img.src = url;
  }

  gridEl.addEventListener('contextmenu', event => {
    const card = event.target.closest('.agw-card');
    if (!card) return;
    event.preventDefault();
    openMenu(card.dataset.artist, event.clientX, event.clientY);
  });

  function closeMenu() {
    menuEl?.remove();
    menuEl = null;
  }

  function openMenu(artist, x, y) {
    closeMenu();
    menuEl = doc.createElement('div');
    menuEl.className = 'agw-menu';
    menuEl.innerHTML = `
      <button type="button" data-agw-menu="queue">큐에 넣기</button>
      <button type="button" data-agw-menu="remove">이 그룹에서 빼기</button>`;
    doc.body.appendChild(menuEl);
    const box = menuEl.getBoundingClientRect();
    const vw = win?.innerWidth || 1280;
    const vh = win?.innerHeight || 800;
    menuEl.style.left = `${Math.round(Math.min(x, vw - box.width - 6))}px`;
    menuEl.style.top = `${Math.round(Math.min(y, vh - box.height - 6))}px`;
    menuEl.addEventListener('click', async event => {
      const act = event.target.closest('[data-agw-menu]')?.dataset.agwMenu;
      closeMenu();
      if (act === 'queue') {
        const item = (group()?.items || []).find(i => i.artist === artist);
        onSendToQueue([{artist, weight: item?.weight ?? 1, image: imageCache.get(artist) || ''}]);
      } else if (act === 'remove') {
        try { await store.remove(groupId, [artist]); } catch (error) { showToast(error.message, 'error'); }
      }
    });
  }

  const closeMenuOutside = event => {
    if (menuEl && !menuEl.contains(event.target)) closeMenu();
  };
  doc.addEventListener('pointerdown', closeMenuOutside, true);

  // ── 단추 줄 ───────────────────────────────────────────────────────────
  function showNaming() {
    nameForm.hidden = false;
    // 임시 창은 서버가 지어 준 이름(`임시 창 N`)이 들어 있다 - 그대로 두면 사용자가
    //    지우고 쳐야 하니 비워서 연다. 이름이 있는 그룹은 고치라고 넣어 준다.
    nameInput.value = isTempNow() ? '' : (group()?.name || '');
    nameInput.focus();
    nameInput.select();
  }

  function hideNaming() {
    nameForm.hidden = true;
  }

  panel.body.addEventListener('click', async event => {
    const act = event.target.closest('[data-agw-act]')?.dataset.agwAct;
    if (!act) return;
    const g = group();
    if (!g) return;
    if (act === 'queue-stop') { onStopQueue(); return; }
    if (act === 'select-mode') { setSelecting(!selecting); return; }
    if (act === 'select-all') { pickWhere(() => true); return; }
    if (act === 'select-missing') {
      const view = currentView();
      pickWhere(a => view && viewImages.has(viewKey(view, a)) && !viewImages.get(viewKey(view, a)));
      return;
    }
    if (act === 'view-edit') { if (currentView()) onEditView(currentView()); return; }
    if (act === 'generate') {
      const view = currentView();
      if (!view || !picked.size) return;
      const artists = (g.items || []).map(i => i.artist).filter(a => picked.has(a));
      const queued = await onGenerateView({viewId: view, artists});
      if (queued) setSelecting(false);
      return;
    }
    // [큐에 전부] 는 없앴다(사용자 지정 2026-09-26) - 160명 그룹에서 무심코 눌러 믹스 큐가
    // 160칸이 됐다. 한 명씩은 카드 우클릭 [큐에 넣기] 로 넣는다(믹스 큐는 20칸까지).
    if (act === 'name-cancel') {
      hideNaming();
    } else if (act === 'delete') {
      if (isTempNow()) {
        await store.destroy(groupId);       // render 가 창을 닫는다
        return;
      }
      if (event.target.dataset.armed !== '1') {
        // 한 번 더 눌러야 지운다 - 되돌릴 수 없는 조작에 확인창(confirm)도 Electron 에서
        // 흔들리므로 단추 자체를 두 단계로 만든다.
        event.target.dataset.armed = '1';
        event.target.textContent = '정말 삭제';
        setTimeout(() => {
          if (!event.target.isConnected) return;
          event.target.dataset.armed = '';
          event.target.textContent = '삭제';
        }, 2500);
        return;
      }
      try { await store.destroy(groupId); } catch (error) { showToast(error.message, 'error'); }
    }
  });

  nameForm.addEventListener('submit', async event => {
    event.preventDefault();
    const name = nameInput.value.trim();
    if (!name) { nameInput.focus(); return; }
    // ⚠️ 이름을 붙이는 것이 곧 저장이다. 아이디는 그대로라 **창을 다시 띄우지 않는다** -
    //    전에는 임시본을 지우고 새로 만드느라 창이 닫혔다 열렸고, 그 사이 구독자가
    //    '그룹이 사라졌다' 고 보는 틈을 막으려 따로 빗장(promoting)이 필요했다.
    const wasTemp = isTempNow();
    try {
      const saved = await store.rename(groupId, name);
      hideNaming();
      if (wasTemp) showToast(`'${saved.name}' 그룹으로 저장했습니다.`, 'info');
    } catch (error) {
      showToast(error.message, 'error');
      nameInput.focus();
    }
  });

  nameInput.addEventListener('keydown', event => {
    // 글로벌 단축키(Ctrl+Enter = Generate 등)가 여기로 새지 않게.
    event.stopPropagation();
    if (event.key === 'Escape') { event.preventDefault(); hideNaming(); }
  });

  // ── 수명 ──────────────────────────────────────────────────────────────
  const unsubscribe = store.subscribe(() => {
    if (!group()) { panel.close(); return; }
    render();
  });

  let alive = true;
  function teardown({keepPanel = false} = {}) {
    if (!alive) return;
    alive = false;
    leaveHover();
    unsubViews();
    OPEN.delete(api);
    unsubscribe();
    unzone();
    closeMenu();
    doc.removeEventListener('pointerdown', closeMenuOutside, true);
    // 빈 임시 창은 닫으면 사라진다. 내용이 있으면 남겨 둔다(메뉴에서 다시 연다).
    const g = group();
    // 빈 임시 창은 닫으면 사라진다 - 서버에 이름뿐인 빈 그룹이 쌓이지 않게.
    if (isTempNow() && g && !(g.items || []).length) void store.destroy(groupId);
    if (!keepPanel) {
      try { panel.destroy(); } catch { /* 이미 내려감 */ }
    }
    onClosed({});
  }

  /** 먼저 뜬 창과 겹치면 **옆자리**부터 찾는다. 28px 계단식만 쓰면 새 창이 기존 창을
   *  거의 통째로 덮어 그 창의 카드를 못 잡는다(실측: 임시 창이 저장 창을 가림).
   *  오른쪽 -> 아래 -> 계단식 순. 화면 밖으로는 안 놓는다. */
  function place() {
    const vw = win?.innerWidth || 1280;
    const vh = win?.innerHeight || 800;
    const me = () => panel.el.getBoundingClientRect();
    const overlaps = (a, b) => a.left < b.right - 8 && b.left < a.right - 8
      && a.top < b.bottom - 8 && b.top < a.bottom - 8;
    const others = () => [...OPEN].filter(o => o !== api).map(o => o.panel.el.getBoundingClientRect());
    const clear = () => others().every(r => !overlaps(me(), r));
    if (clear()) return;
    const {width: w, height: h} = me();
    const spots = [];
    for (const r of others()) {
      spots.push([r.right + 8, r.top], [r.left, r.bottom + 8]);
    }
    for (const [x, y] of spots) {
      if (x + w > vw - 8 || y + h > vh - 8) continue;
      panel.moveTo(x, y);
      if (clear()) return;
    }
    // 자리가 없으면 계단식(최대 10번).
    for (let i = 1; i <= 10 && !clear(); i += 1) {
      const r = me();
      panel.moveTo(Math.min(r.left + 28, vw - w - 8), Math.min(r.top + 28, vh - 48));
    }
  }

  const api = {
    groupId,
    panel,
    focus() { panel.open(); panel.raise(); },
    close() { panel.close(); },
    isTemp: () => isTempNow(),
    viewResult,
    setQueueProgress,
  };
  OPEN.add(api);
  panel.open();
  render();
  place();
  return api;
}
