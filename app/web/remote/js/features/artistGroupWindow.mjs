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
  onClosed = () => {},
} = {}) {
  const broker = dragBrokerFor(doc, win);
  const isTempNow = () => store.isTemp(groupId);
  const imageCache = new Map();    // artist -> image_url ('' = 그림 없음)
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
      <button type="button" class="agw-btn" data-agw-act="queue-all" title="이 그룹을 믹스 큐 끝에 넣습니다">큐에 전부</button>
      <button type="button" class="agw-btn danger" data-agw-act="delete"></button>
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

  function group() {
    return store.get(groupId);
  }

  /** 제목 = 그룹 이름. 임시 창의 이름(`임시 창 N`)도 **서버가** 붙인 것이라
   *  화면에서 번호를 다시 세지 않는다 - 세던 때는 창마다 제목이 갈렸다. */
  function titleText() {
    return store.get(groupId)?.name || '그룹';
  }

  // ── 그리기 ────────────────────────────────────────────────────────────
  function cardHtml(item) {
    const url = imageCache.get(item.artist) || '';
    const img = url
      ? `<img src="${escHtml(url)}" alt="" loading="lazy" draggable="false">`
      : '<span class="agw-noimg">No Image</span>';
    const weight = Number.isFinite(item.weight) && item.weight !== 1
      ? `<span class="agw-weight">${escHtml(String(item.weight))}</span>` : '';
    return `<button type="button" class="agw-card" role="listitem" data-artist="${escHtml(item.artist)}"
                    title="${escHtml(item.artist)}">
      <span class="agw-img">${img}</span>
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
    deleteBtn.textContent = temp ? '비우고 닫기' : '삭제';
    deleteBtn.dataset.armed = '';
    renameBtn.title = temp ? '이름을 붙여 저장합니다' : '이름 바꾸기';
    const items = g.items || [];
    countEl.textContent = `${items.length}명`;
    gridEl.innerHTML = items.map(cardHtml).join('');
    emptyEl.hidden = items.length > 0;
    void fillImages(items);
  }

  async function fillImages(items) {
    const missing = items.map(i => i.artist).filter(a => !imageCache.has(a));
    if (!missing.length) return;
    let described = {};
    try { described = await describe(missing) || {}; } catch { described = {}; }
    let changed = false;
    for (const artist of missing) {
      const url = described[artist]?.image_url || '';
      imageCache.set(artist, url);
      if (url) changed = true;
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
    if (!card) return;
    const artist = card.dataset.artist;
    const item = (group()?.items || []).find(i => i.artist === artist);
    broker.arm(event, {
      kind: 'artist',
      artist,
      weight: item?.weight ?? 1,
      image: imageCache.get(artist) || '',
      label: artist,
      sourceGroup: groupId,
    }, {onStart: onDragStart});
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
    if (payload.image && !imageCache.has(payload.artist)) imageCache.set(payload.artist, payload.image);
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

  // ── 누르기 ────────────────────────────────────────────────────────────
  gridEl.addEventListener('click', event => {
    const card = event.target.closest('.agw-card');
    if (card) onPick(card.dataset.artist);
  });

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
    if (act === 'queue-all') {
      if (!g.items.length) { showToast('그룹이 비어 있습니다.', 'info'); return; }
      onSendToQueue(g.items.map(i => ({artist: i.artist, weight: i.weight ?? 1, image: imageCache.get(i.artist) || ''})));
    } else if (act === 'name-cancel') {
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
  };
  OPEN.add(api);
  panel.open();
  render();
  place();
  return api;
}
