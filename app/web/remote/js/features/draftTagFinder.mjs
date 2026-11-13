/* Draft '남은 태그' 창(사용자 지시 2026-11-12) - 지금 칩 조건에 남은 게시물들이 가진 태그를 보고 눌러서 칩으로 넣는다.
 *
 *  · Draft 가 켜져 있으면 E 반구 단추 · Ctrl+E 가 이벤트 맵 대신 이 창을 연다/닫는다(갈림은 eventMapPanel.mjs 의
 *    routeToDraftFinder). Draft 를 끄면 닫힌다. Draft 를 켤 때 이벤트 맵 창이 열려 있으면 닫는다(sync).
 *  · 자리 = 이벤트 맵 창이 뜨던 결과 화면 왼쪽 E 단추 옆 · 높이 = #resultViewer(ResizeObserver). 옮기기 · 고정 스위치 없음.
 *  · 바깥을 눌러도 닫지 않는다(칩 판을 보며 계속 고르는 창). 닫기 = x · Esc(창 안 초점) · E · Ctrl+E · Draft 끔.
 *  · 줄 클릭 = 포함 칩 `*tag` · 우클릭 = 제외 칩 `*tag`. 칩 넣기는 draftMode.mjs 의 편집 줄(edit)을 빌린다 - 판 번호(base_rev)
 *    차례를 칸 입력과 함께 지킨다.
 *  · 목록 = GET /api/event-map/draft/remaining. 응답이 옛 조건이면 그리지 않는다: 응답 rev 가 지금 스냅숏 rev 와 같거나,
 *    청할 때의 rev 그대로이고 그 뒤 조건(include · exclude · ratings · tags = 서버 _condition_key)이 안 바뀌었을 때만 그린다.
 *    조건과 무관한 rev 변화(뽑기 · Extra · PE 재조립)는 목록을 다시 받지 않는다 - Auto Gen 이 매 장 목록을 맨 위로 튕기지 않게.
 *  · 말풍선 = 한글 설명(desc) + 썸네일. 썸네일은 이벤트 맵 .em-tip 과 같은 길(/api/interactive-thumb/index 한 번 +
 *    /api/interactive-thumb?axis=&tag=) - 이벤트 맵 코드는 건드리지 않고 작게 복제했다. 설명도 썸네일도 없으면 띄우지 않는다.
 */

const PAGE = 60;
const Q_DEBOUNCE_MS = 180;
const SORT_KEY = 'naia.draft.finderSort.v1';
const SORTS = [
  { id: 'mix', label: '조합', title: '많이 나오면서 치우친 태그(이벤트 맵 mix 순)' },
  { id: 'posts', label: '게시물', title: '남은 게시물에 많이 달린 태그부터' },
  { id: 'lift', label: '치우침', title: '평소보다 이 조건에서 몇 배 자주 나오나(lift)' },
];
const ALL_TOAST = '남은 게시물 전부에 있는 태그라 넣어도 줄지 않습니다';

export function initDraftTagFinder({
  esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])),
  fmt = n => (Number.isFinite(n) ? Number(n).toLocaleString('en-US') : ''),
  showToast = () => {},
  isActive = () => false,
  getSnapshot = () => null,      // draftMode 의 마지막 스냅숏
  refreshSnapshot = async () => {},   // 서버가 앞선 응답을 받았다 - 스냅숏을 다시 받는다(받으면 sync 가 불린다)
  addChip = async () => { throw new Error('Draft 가 준비되지 않았습니다'); },   // (zone, text) => Promise<data> · 실패는 던진다
  closeEventMap = () => { try { if (window.eventMap?.isOpen?.()) window.eventMap.close(); } catch (_) {} },
} = {}) {
  const man = n => (n >= 10000 ? `${String(Math.round(n / 1000) / 10).replace(/\.0$/, '')}만` : fmt(n));

  let open = false;
  let sort = 'mix';
  try { const v = localStorage.getItem(SORT_KEY); if (SORTS.some(s => s.id === v)) sort = v; } catch (_) {}
  let group = '';
  let q = '';
  let data = null;               // 마지막으로 그린 응답(머리 · 탭)
  let items = [];                // 그린 줄(더 보기로 이어 붙인다)
  let labels = new Map();        // 갈래 id -> 라벨
  let error = '';
  let loading = false;
  let stale = false;           // 조건이 바뀌었고 새 목록을 기다리는 중 - 옛 줄은 누르지 못한다
  let seq = 0;
  let ctl = null;
  let qTimer = 0;
  let lastRev = null, lastKey = null;
  const pending = new Set();     // 넣는 중인 태그 - 연타로 같은 칩을 두 번 보내지 않는다

  // 서버의 조건 지문(derived.cond = 칩 · 등급 · 분면 + 영구 제외)으로 가른다 - 영구 제외만 바뀌어도 다시 받는다
  // (Codex 리뷰 2026-11-13 2차 #2). 지문이 없는 옛 스냅숏이면 칩 상태로.
  const condKey = snap => {
    if (snap?.derived?.cond) return String(snap.derived.cond);
    const st = snap?.state || {};
    return JSON.stringify([st.include || [], st.exclude || [], st.ratings ?? null, st.tags || {}]);
  };
  const revOf = snap => (snap && snap.rev != null ? Number(snap.rev) : null);

  // ---- 뼈대(한 번만) ----
  const win = document.createElement('div');
  win.className = 'drf-win';
  win.hidden = true;
  win.setAttribute('role', 'dialog');
  win.setAttribute('aria-label', '남은 태그');
  win.innerHTML = `
    <div class="drf-head">
      <span class="drf-title">남은 태그</span>
      <span class="drf-meta" data-drf-meta></span>
      <span class="drf-sort" role="group" aria-label="정렬">${SORTS.map(s =>
        `<button type="button" data-drf-sort="${s.id}" aria-pressed="false" data-naia-title="${esc(s.title)}">${esc(s.label)}</button>`).join('')}</span>
      <button type="button" class="drf-x" data-drf-close aria-label="닫기" data-naia-title="닫기 (Esc · Ctrl+E)">&times;</button>
    </div>
    <div class="drf-q-row"><input class="drf-q" data-drf-q type="text" autocomplete="off" spellcheck="false"
      placeholder="태그 이름으로 거르기" aria-label="태그 이름으로 거르기"></div>
    <div class="drf-cats" data-drf-cats role="tablist" aria-label="갈래"></div>
    <div class="drf-list" data-drf-list role="listbox" aria-label="남은 태그 목록"></div>
    <div class="drf-foot">
      <span class="drf-hint">누르면 포함 · 우클릭하면 제외</span>
      <button type="button" class="drf-more" data-drf-more hidden>더 보기</button>
    </div>`;
  document.body.appendChild(win);
  const metaEl = win.querySelector('[data-drf-meta]');
  const qEl = win.querySelector('[data-drf-q]');
  const catsEl = win.querySelector('[data-drf-cats]');
  const listEl = win.querySelector('[data-drf-list]');
  const moreEl = win.querySelector('[data-drf-more]');
  const tipEl = document.createElement('div');
  tipEl.className = 'drf-tip';
  tipEl.hidden = true;
  document.body.appendChild(tipEl);

  // ---- 자리: 결과 화면 왼쪽 E 단추 옆 · 결과 화면 높이 ----
  function viewer() { return document.getElementById('resultViewer'); }
  function place() {
    if (!open) return;
    const vw = window.innerWidth, vh = window.innerHeight;
    const r = viewer()?.getBoundingClientRect();
    let left = 16, top = 64, bottom = vh - 16, room = vw - 32;
    if (r && r.width > 0 && r.height > 0) {
      left = r.left + 26;              // E · S · A 반구(20px) 오른쪽
      top = r.top + 8;
      bottom = r.bottom - 8;
      room = r.width - 40;
    }
    top = Math.max(8, top);
    bottom = Math.min(vh - 8, bottom);
    const width = Math.round(Math.max(260, Math.min(340, room, vw - 16)));
    left = Math.max(8, Math.min(left, vw - width - 8));
    // 결과 화면이 낮아도 220 은 확보한다 - 모자라면 위로 올린다(화면 밖으로는 안 나간다)
    const height = Math.min(Math.max(220, bottom - top), vh - 16);
    if (top + height > vh - 8) top = Math.max(8, vh - 8 - height);
    win.style.left = `${Math.round(left)}px`;
    win.style.top = `${Math.round(top)}px`;
    win.style.width = `${width}px`;
    win.style.height = `${Math.round(height)}px`;
  }
  window.addEventListener('resize', () => { if (open) { hideTip(); place(); } });
  let viewerRo = null;
  function watchViewer() {
    const el = viewer();
    if (!el || viewerRo || typeof ResizeObserver === 'undefined') return;
    viewerRo = new ResizeObserver(() => { if (open) place(); });
    viewerRo.observe(el);
  }

  function tabButton() { return document.getElementById('eventMapTab'); }

  // ---- 열기 · 닫기 ----
  function show() {
    if (open || !isActive()) return;
    open = true;
    win.hidden = false;
    watchViewer();
    place();
    paintSort();
    tabButton()?.setAttribute('aria-pressed', 'true');
    const snap = getSnapshot();
    lastRev = revOf(snap);
    lastKey = condKey(snap);
    q = qEl.value.trim();          // 닫기 전에 친 글(디바운스 전)이 칸에 남아 있다 - 칸과 요청을 맞춘다(리뷰 3차 #7)
    void load({ top: true });
    try { qEl.focus({ preventScroll: true }); } catch (_) {}
  }
  function close() {
    if (!open) return;
    open = false;
    win.hidden = true;
    hideTip();
    clearTimeout(qTimer);
    seq++;
    try { ctl?.abort(); } catch (_) {}
    ctl = null;
    loading = false;
    if (win.contains(document.activeElement)) { try { document.activeElement.blur(); } catch (_) {} }
    // 이벤트 맵이 열려 있으면(드물다) 단추의 눌림은 이벤트 맵 것 - 건드리지 않는다
    if (!window.eventMap?.isOpen?.()) tabButton()?.setAttribute('aria-pressed', 'false');
  }
  function toggle() { if (open) close(); else show(); }

  // ---- 서버 ----
  /** 목록 받기. top = 첫 쪽부터(스크롤 맨 위) · 아니면 더 보기(이어 붙이기). attempt = 옛 조건 응답을 버리고 다시 청한 횟수. */
  async function load({ top = true, attempt = 0 } = {}) {
    if (!open) return;
    const mine = ++seq;
    try { ctl?.abort(); } catch (_) {}
    const ac = new AbortController();
    ctl = ac;
    const timer = setTimeout(() => ac.abort(), 30000);
    const snap = getSnapshot();
    const reqRev = revOf(snap);
    const reqKey = condKey(snap);
    const offset = top ? 0 : items.length;
    loading = true;
    paintMeta();
    moreEl.disabled = true;
    let got;
    try {
      const params = new URLSearchParams({ sort, limit: String(PAGE), offset: String(offset) });
      if (group) params.set('group', group);
      if (q) params.set('q', q);
      const res = await fetch(`/api/event-map/draft/remaining?${params}`, { cache: 'no-store', signal: ac.signal });
      got = await res.json().catch(() => ({}));
      if (!res.ok || got.ok === false) throw new Error(got.message || `HTTP ${res.status}`);
    } catch (err) {
      clearTimeout(timer);
      if (mine !== seq || !open) return;         // 새 요청이 앞섰거나 닫혔다
      loading = false;
      error = ac.signal.aborted ? '응답이 늦어 멈췄습니다 - 다시 열어 주세요' : (err.message || '남은 태그를 받지 못했습니다');
      if (top) { items = []; data = null; }
      paint({ top });
      return;
    }
    clearTimeout(timer);
    if (mine !== seq || !open) return;
    // 옛 조건의 목록은 그리지 않는다
    const nowSnap = getSnapshot();
    const nowRev = revOf(nowSnap);
    const gotRev = got.rev != null ? Number(got.rev) : null;
    // 조건의 지문이 같으면 지금 조건의 목록이다 - rev 는 뽑기 · Extra 로도 오르므로 Auto Gen 중에는 rev 가 끝내 안 맞았다
    // (리뷰 3차 #5). 옛 백엔드(cond 없음)면 예전처럼 rev 로 가린다.
    const nowCond = nowSnap?.derived?.cond;
    const fresh = (got.cond != null && nowCond != null)
      ? got.cond === nowCond
      : (gotRev === nowRev || (gotRev === reqRev && reqKey === condKey(nowSnap)));
    if (!fresh) {
      if (attempt >= 3) {
        loading = false;
        error = '조건이 바뀌는 중입니다 - 잠시 뒤 다시 열어 주세요';
        paint({ top });
        return;
      }
      if (gotRev != null && nowRev != null && gotRev > nowRev) {
        // 서버가 앞섰다(이 탭이 아직 새 스냅숏을 못 받았다) - 받아 오면 sync 가 다시 부른다(그때 이 차례는 seq 로 끝난다)
        try { await refreshSnapshot(); } catch (_) {}
      } else {
        await new Promise(resolve => setTimeout(resolve, 150 * (attempt + 1)));
      }
      if (mine !== seq || !open) return;
      void load({ top, attempt: attempt + 1 });
      return;
    }
    loading = false;
    error = '';
    // 고른 갈래가 새 조건에서 0 이 됐다(탭이 사라진다) - [전체] 로 돌아가 다시 받는다
    if (group && top && Number(got.pool) > 0 && !(got.group_counts || []).some(g => g.id === group)) {
      group = '';
      void load({ top: true });
      return;
    }
    // 옛 줄의 잠금은 **새 목록을 실제로 그릴 때** 푼다 - 위의 갈래 되돌리기 분기에서 먼저 풀면 옛 조건의 줄이 다시 눌린다
    // (Codex 리뷰 2026-11-12 4차 #2).
    stale = false;
    listEl.classList.remove('is-stale');
    data = got;
    (got.group_counts || []).forEach(g => labels.set(g.id, g.label));
    const rows = Array.isArray(got.items) ? got.items : [];
    if (top) items = rows;
    else {
      const have = new Set(items.map(it => it.tag));
      items = items.concat(rows.filter(it => !have.has(it.tag)));
    }
    paint({ top });
  }

  // ---- 그리기 ----
  function paintSort() {
    win.querySelectorAll('[data-drf-sort]').forEach(btn => {
      const on = btn.dataset.drfSort === sort;
      btn.classList.toggle('is-on', on);
      btn.setAttribute('aria-pressed', String(on));
    });
  }
  function paintMeta() {
    metaEl.classList.toggle('is-busy', loading);
    if (!data) { metaEl.textContent = loading ? '세는 중…' : ''; return; }
    const total = Number(data.total) || 0;
    if (!total) { metaEl.textContent = '남은 게시물 없음'; return; }
    metaEl.textContent = data.sampled
      ? `≈ ${fmt(total)}건 중 ${man(Number(data.scanned) || 0)} 건 표본`
      : `${fmt(total)}건 안에서`;
  }
  function paintCats() {
    if (!data || !Number(data.total)) { catsEl.innerHTML = ''; catsEl.hidden = true; return; }
    catsEl.hidden = false;
    const tab = (id, label, n) => `<button type="button" class="drf-cat${group === id ? ' is-on' : ''}" role="tab"
      aria-selected="${group === id}" data-drf-cat="${esc(id)}"${id ? ` data-g="${esc(id)}"` : ''}><span>${esc(label)}</span><span
      class="drf-cat-n">${fmt(n)}</span></button>`;
    catsEl.innerHTML = tab('', '전체', Number(data.pool) || 0)
      + (data.group_counts || []).filter(g => Number(g.count) > 0).map(g => tab(g.id, g.label || g.id, Number(g.count))).join('');
  }
  function countHtml(it) {
    if (it.all) return '<span class="drf-n">전부</span>';
    const n = Number(it.count);
    if (!Number.isFinite(n)) return '<span class="drf-n"></span>';
    return data?.sampled
      ? `<span class="drf-n">≈ ${fmt(n)}</span>`
      : `<span class="drf-n">${fmt(n)} / ${fmt(Number(data?.total) || 0)}</span>`;
  }
  function rowHtml(it, i) {
    const gid = it.group || '';
    const label = labels.get(gid) || '';
    return `<div class="drf-row${it.all ? ' is-all' : ''}${pending.has(it.tag) ? ' is-pending' : ''}" role="option" data-drf-i="${i}"><span
      class="drf-g"${gid ? ` data-g="${esc(gid)}"` : ''}>${esc(label)}</span><span class="drf-t">${esc(it.tag)}</span>${countHtml(it)}</div>`;
  }
  function paint({ top = true } = {}) {
    hideTip();
    paintMeta();
    paintCats();
    if (error && !items.length) {
      listEl.innerHTML = `<div class="drf-empty">${esc(error)}</div>`;
    } else if (!data && loading) {
      listEl.innerHTML = '';
    } else if (data && !Number(data.total)) {
      listEl.innerHTML = '<div class="drf-empty">이 조건에 남은 게시물이 없습니다</div>';
    } else if (!items.length) {
      listEl.innerHTML = `<div class="drf-empty">${q ? '이름에 맞는 태그가 없습니다' : '더 좁힐 태그가 없습니다'}</div>`;
    } else {
      listEl.innerHTML = items.map(rowHtml).join('');
    }
    if (error && items.length) showToast(error, 'warning');
    if (top) listEl.scrollTop = 0;
    moreEl.hidden = !(data && data.more && items.length);
    moreEl.disabled = loading;
  }

  // ---- 말풍선(설명 + 썸네일) ----
  let thumbAxis = null;          // 태그 -> 썸네일 축 · null = 아직
  let thumbAsked = false;
  let tipRow = null;
  async function ensureThumbIndex() {
    if (thumbAxis || thumbAsked) return;
    thumbAsked = true;
    try {
      const r = await fetch('/api/interactive-thumb/index');
      const axes = r.ok ? (await r.json()).axes || {} : {};
      thumbAxis = new Map();
      for (const [axis, tags] of Object.entries(axes)) for (const t of tags || []) if (!thumbAxis.has(t)) thumbAxis.set(t, axis);
    } catch (_) { thumbAxis = new Map(); }
    if (tipRow) paintTip(tipRow);
  }
  function paintTip(row) {
    const it = items[Number(row.dataset.drfI)];
    if (!open || !it || !row.isConnected) { hideTip(); return; }
    const axis = thumbAxis?.get(it.tag) || '';
    if (!it.desc && !axis) { tipEl.hidden = true; return; }   // 썸네일 색인을 기다리는 중이면 오면 다시 그린다
    const gid = it.group || '';
    tipEl.innerHTML = `<div class="drf-tip-main"><div class="drf-tip-head"><span class="drf-tip-tag">${esc(it.tag)}</span>${
      labels.get(gid) ? `<span class="drf-tip-g">${esc(labels.get(gid))}</span>` : ''}</div>${
      it.desc ? `<div class="drf-tip-desc">${esc(it.desc)}</div>` : ''}</div>${axis
      ? `<img class="drf-tip-thumb" alt="" src="/api/interactive-thumb?axis=${encodeURIComponent(axis)}&tag=${encodeURIComponent(it.tag)}">` : ''}`;
    const img = tipEl.querySelector('img');
    if (img) {
      img.addEventListener('error', () => {
        img.remove();
        if (!it.desc) tipEl.hidden = true;
      }, { once: true });
    }
    tipEl.hidden = false;
    // 창 오른쪽(결과 화면 위)에 그 줄 높이로 - 목록을 가리지 않는다. 자리가 없으면 줄 아래로.
    const w = win.getBoundingClientRect(), a = row.getBoundingClientRect(), b = tipEl.getBoundingClientRect();
    const vw = window.innerWidth, vh = window.innerHeight, m = 8;
    let left = w.right + 8, top = a.top;
    if (left + b.width > vw - m) { left = Math.max(m, Math.min(a.left + a.width * 0.5, vw - b.width - m)); top = a.bottom + 6; }
    if (top + b.height > vh - m) top = Math.max(m, vh - b.height - m);
    tipEl.style.left = `${Math.round(left)}px`;
    tipEl.style.top = `${Math.round(Math.max(m, top))}px`;
  }
  function showTip(row) {
    if (row === tipRow) return;
    tipRow = row;
    if (!row) { tipEl.hidden = true; return; }
    void ensureThumbIndex();
    paintTip(row);
  }
  function hideTip() { tipRow = null; tipEl.hidden = true; }

  // ---- 칩 넣기 ----
  async function put(zone, it) {
    if (!it || pending.has(it.tag)) return;
    // 조건이 바뀌었는데 새 목록이 아직 안 왔다 - 옛 줄(옛 '전부' 판정 · 이미 넣은 태그)은 누르지 못한다(리뷰 3차 #6)
    if (stale) return;
    if (zone === 'include' && it.all) { showToast(ALL_TOAST, 'info'); return; }
    if (!isActive()) { close(); return; }
    pending.add(it.tag);
    listEl.querySelectorAll('[data-drf-i]').forEach(el => {
      if (items[Number(el.dataset.drfI)]?.tag === it.tag) el.classList.add('is-pending');
    });
    try {
      await addChip(zone, `*${it.tag}`);
      // 스냅숏이 바뀌면 sync 가 새 조건으로 다시 받는다(탭 · 정렬 · 거르기 유지 · 맨 위로)
    } catch (err) {
      showToast(err?.message || '칩을 넣지 못했습니다', 'warning');
    } finally {
      pending.delete(it.tag);
      listEl.querySelectorAll('[data-drf-i].is-pending').forEach(el => {
        if (!pending.has(items[Number(el.dataset.drfI)]?.tag)) el.classList.remove('is-pending');
      });
    }
  }

  // ---- 손 ----
  win.addEventListener('click', event => {
    const t = event.target;
    if (t.closest('[data-drf-close]')) { close(); return; }
    const sb = t.closest('[data-drf-sort]');
    if (sb) {
      if (sb.dataset.drfSort === sort) return;
      sort = sb.dataset.drfSort;
      try { localStorage.setItem(SORT_KEY, sort); } catch (_) {}
      paintSort();
      void load({ top: true });
      return;
    }
    const cat = t.closest('[data-drf-cat]');
    if (cat) {
      if (cat.dataset.drfCat === group) return;
      group = cat.dataset.drfCat;
      paintCats();
      void load({ top: true });
      return;
    }
    if (t.closest('[data-drf-more]')) { if (!loading) void load({ top: false }); return; }
    const row = t.closest('[data-drf-i]');
    if (row) void put('include', items[Number(row.dataset.drfI)]);
  });
  listEl.addEventListener('contextmenu', event => {
    const row = event.target.closest('[data-drf-i]');
    if (!row) return;
    event.preventDefault();
    void put('exclude', items[Number(row.dataset.drfI)]);
  });
  // 줄을 눌러도 초점은 거르기 칸에 남긴다(Esc 가 계속 먹게)
  listEl.addEventListener('mousedown', event => { if (event.target.closest('[data-drf-i]')) event.preventDefault(); });
  listEl.addEventListener('mouseover', event => showTip(event.target.closest('[data-drf-i]')));
  listEl.addEventListener('mouseleave', hideTip);
  listEl.addEventListener('scroll', hideTip, { passive: true });
  qEl.addEventListener('input', () => {
    clearTimeout(qTimer);
    qTimer = setTimeout(() => {
      const next = qEl.value.trim();
      if (next === q) return;
      q = next;
      void load({ top: true });
    }, Q_DEBOUNCE_MS);
  });
  win.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || event.isComposing) return;
    event.preventDefault();
    event.stopPropagation();
    close();
  });

  /** draftMode 가 스냅숏을 받을 때마다 부른다. */
  function sync(snap) {
    const on = !!snap?.state?.active;
    if (!on) { lastRev = null; lastKey = null; close(); return; }
    if (lastRev === null && lastKey === null && !open) {
      // 막 켜졌다(또는 처음 받은 스냅숏이 켜진 Draft) - 이벤트 맵 창이 열려 있으면 닫는다
      closeEventMap();
    }
    const rev = revOf(snap);
    const key = condKey(snap);
    const changed = open && lastKey !== null && key !== lastKey;
    lastRev = rev;
    lastKey = key;
    if (changed) {
      stale = true;
      listEl.classList.add('is-stale');
      void load({ top: true });
    }
  }

  return { show, close, toggle, isOpen: () => open, sync };
}
