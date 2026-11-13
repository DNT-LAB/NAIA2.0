/* Draft - 영구 제외 창(사용자 지시 2026-11-13).
 *
 * 남은 게시물 수는 영구 제외(Search 의 붉은 줄 = 이벤트 맵의 영구 제외와 **같은 글**)에 걸린 게시물을 뺀 수다.
 * 그런데 Draft 화면에는 그 사실이 안 보여서 "왜 전체보다 적지?" 가 나왔다. 등급 단추 옆 [제외 : N] 이 이 창을 연다.
 *
 *  · 글의 주인은 서버(search_filter_state.exclude_permanent)다. 읽기 · 저장은 이벤트 맵과 같은 길
 *    (`/api/event-map/permanent-exclude`)이고, 저장은 언제나 글 전체를 보낸다.
 *  · 입력 줄 = 이벤트 맵 색인의 태그 자동완성(`/api/event-map/suggest`)에서 고른 것만 더한다(이벤트 맵 창과 같은 규칙).
 *  · 칩의 × = 그 항을 뺀다. 저장되면 Draft 스냅숏을 다시 받아 남은 게시물 수가 곧바로 바뀐다.
 *  · 조회 · 저장은 한 줄로 선다 - 늦은 응답이 방금 저장한 글을 덮지 않게(이벤트 맵 리뷰 2026-10-14 · 10-15 교훈).
 *  · 저장은 **서버의 지금 글** 위에 편집(더하기 · 빼기)을 얹는다: 보내기 직전에 다시 읽고, 그 글을 base 로 싣는다.
 *    그 사이 다른 탭 · Search · 이벤트 맵이 바꿨으면 서버가 409 + 지금 글을 준다 - 그 글 위에 다시 얹어 보낸다
 *    (Codex 리뷰 2026-11-13 #1 · #2: 창이 들고 있던 옛 글 · 못 읽은 빈 글로 남의 항을 지웠다).
 */

import { createDraggablePanel } from './draggablePanel.mjs?v=20260926-childalign';

const AC_DEBOUNCE_MS = 120;

export function initDraftPermExclude({
  esc,
  fmt,
  showToast = () => {},
  getSnapshot = () => null,
  refreshSnapshot = async () => {},
  onTextChange = () => {},       // (text) => void - Search 칸도 같은 글로(다음 Search 저장이 옛 글을 다시 쓰지 않게)
  searchEditStamp = () => 0,     // () => 수 - 사용자가 Search 칸을 고칠 때마다 오른다(읽는 사이 고쳤으면 건네지 않는다)
} = {}) {
  const splitTerms = text => String(text || '').split(',').map(t => t.trim()).filter(Boolean);
  const fmtK = n => (n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : String(n || 0));

  let panel = null, headEl = null, chipsEl = null, inputEl = null, acEl = null;
  let text = '', info = null, saving = 0;
  let queue = Promise.resolve();
  // 마지막으로 Search 칸에 건넨 글. 읽은 글이 이것과 다를 때만 건넨다 - 늘 건네면 늦게 온 읽기 응답이 그 사이 Search 에서
  // 고친 글을 옛 글로 덮었다(Codex 리뷰 2026-11-13 5차 #1). 저장이 실패해 못 건넨 글은 이것과 달라 다음 읽기가 건넨다(3차 #3).
  let told = null;
  /** stamp = 이 일을 시작할 때의 Search 편집 번호. 그 사이 사용자가 Search 칸을 고쳤으면 건네지 않는다 - 늦게 온 읽기가
   *  그 편집을 옛 글로 되돌렸다(Codex 리뷰 2026-11-13 6차 #2). 건네지 않은 글은 told 가 아니라 다음 읽기가 다시 본다. */
  function tell(value, stamp) {
    if (stamp !== searchEditStamp()) return;
    told = value;
    onTextChange(value);
  }
  let acItems = [], acActive = -1, acSeq = 0, acTimer = null;

  async function call(method, body) {
    const res = await fetch('/api/event-map/permanent-exclude', {
      method, cache: 'no-store', headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined, signal: AbortSignal.timeout(30000),
    });
    const data = await res.json().catch(() => null);
    if (!res.ok || !data || data.ok === false) {
      const d = data || {};
      throw Object.assign(new Error(d.message || `HTTP ${res.status}`), { code: d.error || '', data: d });
    }
    // 본문이 깨졌거나 글이 없는 응답을 '빈 글' 로 받으면 Search 칸을 비웠다(Codex 리뷰 2026-11-13 7차 #3) - 실패로 다룬다
    if (typeof data.text !== 'string') throw new Error('응답에 영구 제외 글이 없습니다');
    return data;
  }
  function take(data) {
    const changed = String(data.text || '') !== text;
    info = data; text = String(data.text || ''); loadError = '';
    return changed;
  }

  let loadError = '';
  function load({ snapshot = false } = {}) {
    const stamp = searchEditStamp();   // 청한 때의 번호(줄에서 기다리는 동안 고친 것도 지킨다 - 7차 #2)
    queue = queue.then(async () => {
      try {
        take(await call('GET'));
        if (text !== told) tell(text, stamp);
        if (snapshot) await refreshSnapshot();   // 다른 곳에서 바뀌었을 수 있다 - 남은 게시물 · [제외 : N] 도 새로(#4)
      } catch (error) { loadError = error.message || '읽기 실패'; }
      paint();
    }).catch(() => {});
    return queue;
  }
  /** makeTerms(서버의 지금 항 목록) -> 새 목록. 못 읽으면 저장하지 않는다(빈 글로 덮지 않게 - #2). */
  function save(makeTerms, done) {
    const stamp = searchEditStamp();   // 청한 때의 번호(앞 저장이 끝나길 기다리는 동안 고친 Search 칸도 지킨다 - 7차 #2)
    queue = queue.then(async () => {
      saving++; paint();
      const before = text;
      let read = false;
      let posted = false;   // POST 를 보냈나 - 보낸 뒤 실패(응답 유실 등)면 실제로 써졌는지 다시 읽어 본다(7차 #3)   // 이 일에서 서버 글을 받았나 - 못 받았으면 실패 길이 아무것도 건네지 않는다(6차 #1: 빈 글로 Search 칸을 비웠다)
      try {
        take(await call('GET'));
        read = true;
        let wrote = false;
        for (let attempt = 0; ; attempt++) {
          const next = makeTerms(splitTerms(text)).join(', ');
          if (next === text.trim()) break;      // 할 일이 없다(다른 곳에서 먼저 했다)
          try {
            posted = true;
            take(await call('POST', { text: next, base: text }));
            wrote = true;
            break;
          } catch (error) {
            if (error.code !== 'conflict' || typeof error.data?.text !== 'string') throw error;
            take(error.data);   // 그 사이 바뀐 글 위에 다시 얹는다
            // 세 번째 충돌이면 포기 - 그래도 그 응답의 새 글은 받아 둔 뒤라 실패 길이 Search 칸에 퍼뜨린다(Codex 4차 #1)
            if (attempt >= 2) throw error;
          }
        }
        if (!wrote && text === before) return;
        tell(text, stamp);
        if (wrote) showToast(done, 'success');
        await refreshSnapshot();   // 남은 게시물 · [제외 : N] 을 새 글로(쓰지 않았어도 받은 글이 새것이면 - 2차 #4)
      } catch (error) {
        // 저장은 못 했어도 읽은 서버 글은 Search 칸에(다음 Search 저장이 옛 글로 덮지 않게) - 읽지도 못했으면 건드리지 않는다
        if (posted) { try { take(await call('GET')); } catch (_) {} }   // 써졌을 수도 있다 - 서버의 지금 글로
        if (read && text !== told) tell(text, stamp);
        showToast(`영구 제외 저장 실패 — ${error.message}`, 'error');
      } finally { saving--; paint(); }
    }).catch(() => {});
    return queue;
  }

  function ensure() {
    if (panel) return panel;
    panel = createDraggablePanel({
      document, window, title: '영구 제외', variant: 'emt-chips-window drp', storageKey: 'draft-perm-exclude',
      width: 340, height: 300, minWidth: 260, minHeight: 170, maxWidth: 700, resizable: true, escHtml: esc,
      onClose: () => closeAc(),
    });
    panel.body.innerHTML = `<div class="emt-chips-head" data-drp-head></div>
      <div class="drp-in-row"><input class="drp-in" data-drp-in type="text" autocomplete="off" spellcheck="false"
        aria-label="영구 제외에 더할 태그" placeholder="영구 제외에 더할 태그 - 치면 고를 태그가 뜬다"></div>
      <div class="emt-chips" data-drp-chips></div>
      <div class="emt-chips-note">이 태그가 달린 게시물은 Draft 가 세지도 뽑지도 않는다. Search · 이벤트 맵의 영구 제외와 같은 목록이다.</div>`;
    headEl = panel.body.querySelector('[data-drp-head]');
    chipsEl = panel.body.querySelector('[data-drp-chips]');
    inputEl = panel.body.querySelector('[data-drp-in]');
    chipsEl.addEventListener('click', event => {
      const x = event.target.closest('[data-drp-x]');
      if (!x || saving) return;
      const gone = splitTerms(text)[Number(x.dataset.drpX)];
      if (gone == null) return;
      // 차례가 왔을 때의 글에서 글자로 뺀다(그 사이에 목록이 바뀌어도 맞는 항을 뺀다).
      void save(terms => { const at = terms.indexOf(gone); return at < 0 ? terms : terms.filter((_, i) => i !== at); },
        `영구 제외에서 뺐습니다 — ${gone}`);
    });
    inputEl.addEventListener('input', scheduleAc);
    inputEl.addEventListener('blur', () => setTimeout(closeAc, 120));
    inputEl.addEventListener('keydown', event => {
      if (event.isComposing) return;
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        if (!acItems.length) return;
        event.preventDefault();
        acActive = (acActive + (event.key === 'ArrowDown' ? 1 : -1) + acItems.length) % acItems.length;
        paintAc();
      } else if (event.key === 'Enter') {
        event.preventDefault();
        if (acActive >= 0) choose(acActive);
      } else if (event.key === 'Escape') {
        if (acItems.length) { event.stopPropagation(); closeAc(); }
      }
    });
    return panel;
  }

  function paint() {
    if (!panel || !panel.isOpen()) return;
    const terms = splitTerms(text);
    const hits = new Map((info?.terms || []).map(t => [t.term, t.tags || []]));
    const perm = getSnapshot()?.derived?.perm;
    panel.setTitle(`영구 제외 · ${terms.length}`);
    const parts = [];
    if (perm && Number.isFinite(perm.dropped)) parts.push(`지금 조건에서 빠진 게시물 ${fmt(perm.dropped)}`);
    if (info) parts.push(`걸린 태그 ${fmt(info.tag_count || 0)}`);
    headEl.textContent = saving ? '저장 중…' : (loadError ? `목록을 읽지 못했습니다 — ${loadError}` : parts.join(' · '));
    chipsEl.innerHTML = terms.length ? terms.map((t, i) => {
      const tags = hits.get(t);
      const dead = Array.isArray(tags) && !tags.length;
      return `<span class="emt-chip${dead ? ' is-dead' : ''}" title="${esc(dead ? '이벤트 맵에서는 걸리는 태그가 없다(Search 전용 문법 · 없는 태그)'
        : `걸리는 태그: ${(tags || [t]).join(', ')}`)}">${esc(t)}<button type="button" data-drp-x="${i}" aria-label="${esc(t)} 빼기">×</button></span>`;
    }).join('') : '<div class="st-empty">영구 제외 태그가 없습니다. 입력 줄에서 태그를 쳐서 더한다.</div>';
    chipsEl.inert = saving > 0;
  }

  // ---- 자동완성(이벤트 맵 색인의 태그만) ----
  function closeAc() {
    clearTimeout(acTimer); ++acSeq;
    acItems = []; acActive = -1;
    if (acEl) { acEl.hidden = true; acEl.innerHTML = ''; }
  }
  function paintAc() {
    if (!acEl) {
      acEl = document.createElement('div');
      acEl.className = 'emt-ac';
      acEl.setAttribute('role', 'listbox');
      document.body.append(acEl);
      acEl.addEventListener('mousedown', event => event.preventDefault());   // 입력 칸이 초점을 잃지 않게
      acEl.addEventListener('click', event => {
        const row = event.target.closest('[data-ac]');
        if (row) choose(Number(row.dataset.ac));
      });
    }
    if (!acItems.length || !panel?.isOpen()) { acEl.hidden = true; return; }
    acEl.innerHTML = acItems.map((it, i) => `<div class="emt-ac-row${i === acActive ? ' is-active' : ''}${it.blocked === '영구 제외' ? ' is-off' : ''}" data-ac="${i}" role="option">
        <span class="emt-ac-tag">${esc(it.tag)}</span><span class="emt-ac-kind">${esc(it.blocked === '영구 제외' ? '이미 제외' : (it.role_label || ''))}</span><span class="emt-ac-n">${fmtK(it.observed)}</span></div>`).join('');
    acEl.hidden = false;
    acEl.style.zIndex = String((Number.parseInt(getComputedStyle(panel.el).zIndex, 10) || 1000) + 2);
    const r = inputEl.getBoundingClientRect();
    acEl.style.left = `${Math.round(r.left)}px`;
    acEl.style.top = `${Math.round(r.bottom + 2)}px`;
    acEl.style.width = `${Math.round(Math.max(260, Math.min(r.width, 380)))}px`;
  }
  function scheduleAc() {
    clearTimeout(acTimer);
    const q = inputEl.value.trim();
    if (!q) { closeAc(); return; }
    acTimer = setTimeout(async () => {
      const mine = ++acSeq;
      try {
        const res = await fetch(`/api/event-map/suggest?${new URLSearchParams({ q, limit: '8' })}`, { cache: 'no-store' });
        const body = await res.json();
        if (mine !== acSeq) return;
        acItems = body.items || [];
        acActive = acItems.findIndex(it => it.blocked !== '영구 제외');
      } catch { if (mine === acSeq) { acItems = []; acActive = -1; } }
      paintAc();
    }, AC_DEBOUNCE_MS);
  }
  function choose(i) {
    const it = acItems[i];
    if (!it) return;
    closeAc();
    if (it.blocked === '영구 제외') { showToast(`이미 영구 제외에 있습니다 — ${it.tag}`, 'info'); return; }
    inputEl.value = '';
    // 서버의 지금 목록에 이미 있으면(다른 곳에서 먼저 더했다) 그대로 둔다
    const same = t => t.trim().toLowerCase() === String(it.tag).trim().toLowerCase();
    void save(terms => (terms.some(same) ? terms : [...terms, it.tag]), `영구 제외에 더했습니다 — ${it.tag}`);
  }

  function open() {
    ensure();
    panel.open();
    paint();
    void load({ snapshot: true });   // 항마다 걸리는 태그 · 지금 글 · Draft 수를 새로(Search 에서 고쳤을 수 있다)
    inputEl.value = '';
    inputEl.focus({ preventScroll: true });
  }
  function close() { if (panel?.isOpen()) panel.close(); closeAc(); }

  return {
    toggle: () => (panel?.isOpen() ? close() : open()),
    close,
    isOpen: () => !!panel?.isOpen(),
    sync: () => paint(),
  };
}
