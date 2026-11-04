/**
 * 삽입 그룹 추적 판(사용자 지정 2026-11-04).
 *
 * 결과 화면 작가 패널의 [삽입] 으로 PE Prefix / Postfix 에 넣은 작가를 이번 실행 동안 추적한다. 패널 바로 위에 뜬다.
 *
 *   삽입 그룹 3 · 솔로 [전체|그룹]                    [확정]
 *   [a:][앞] abo (hechouchou)  ×1.04  ◎  ✕
 *
 * - **글이 진실이다.** 켜기/끄기 · a: · 앞/뒤 · 가중치 · ✕ 는 이 판이 PE 글을 바로 고친다(`/pe` 편집창과 같은 길).
 *   끄면 글에서 빠지고, 켜면 Prefix 는 맨 앞 · Postfix 는 맨 뒤에 다시 들어간다.
 * - 솔로(◎)만 글을 안 고친다 - 생성할 때 서버의 PE 훅이 다른 작가를 뺀다(전체 = 모든 작가 · 그룹 = 추적 중인 작가끼리).
 * - [확정] 또는 프리셋 전환 = 추적을 끝낸다. 글은 그대로(꺼 둔 작가는 이미 글에 없으니 버려진다).
 * - 손으로 글을 고치면 맞춘다: 조각이 사라졌으면 끈 것으로, 가중치 · 접두가 바뀌었으면 그 값으로.
 * ⚠️ 목록은 서버가 주인이다(`/api/artist-thumb/insert-tracker` · WS `artist_insert_tracker`) - 다른 탭도 같은 판을 본다.
 */

const NUM = '-?\\d*\\.?\\d+';
const escRe = text => String(text).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const round2 = value => Math.round(Number(value) * 100) / 100;

/** 글에서 이 작가의 **홀로 선** 조각. 없으면 null. `bodies` = 가중치 없는 몸통들(`artist:x` · `x` · `@x` …).
 *  조각 = 글 처음 · 쉼표 · 줄바꿈 사이. NAI `w::몸통 ::` · 몸통 / SD `(몸통:w)` · 몸통.
 *  ⚠️ NAI 가중치 묶음(`1.2::artist:a, artist:b ::`) 안의 조각은 건드리지 않는다 - 앞의 `::` 수가 홀수면 묶음 안이다. */
export function findArtistPiece(text, bodies) {
  const names = [...new Set((bodies || []).map(b => String(b || '').trim()).filter(Boolean))].map(escRe);
  if (!names.length) return null;
  const alt = names.join('|');
  const source = String(text ?? '');
  const re = new RegExp(`(^|[,\\n])([ \\t]*)(${NUM}::(?:${alt})\\s*::|\\((?:${alt}):${NUM}\\)|(?:${alt}))(?=[ \\t]*(?:,|\\n|$))`, 'gi');
  let m;
  while ((m = re.exec(source))) {
    const start = m.index + m[1].length + m[2].length;
    if (((source.slice(0, start).match(/::/g) || []).length % 2) === 1) continue;
    const piece = m[3];
    const nai = piece.match(new RegExp(`^(${NUM})::`));
    const sd = piece.match(new RegExp(`:(${NUM})\\)$`));
    const weight = nai ? Number(nai[1]) : (sd ? Number(sd[1]) : 1);
    return {start, end: start + piece.length, piece, weight, withPrefix: /artist:/i.test(piece)};
  }
  return null;
}

/** 조각 하나를 빼고 그 옆 쉼표 하나도 같이 뺀다. */
export function removeArtistPiece(text, hit) {
  const source = String(text ?? '');
  let start = hit.start;
  let end = hit.end;
  const after = source.slice(end).match(/^[ \t]*,[ \t]*/);
  if (after) {
    end += after[0].length;
  } else {
    const before = source.slice(0, start).match(/,[ \t]*$/);
    if (before) start -= before[0].length;
  }
  return source.slice(0, start) + source.slice(end);
}

/** Prefix = 맨 앞 · Postfix = 맨 뒤. */
export function putArtistToken(text, slot, token) {
  const source = String(text ?? '');
  if (!source.trim()) return token;
  if (slot === 'post') return `${source.replace(/[\s,]+$/, '')}, ${token}`;
  return `${token}, ${source.replace(/^\s+/, '')}`;
}

export function installArtistInsertTray({
  document, fetch = window.fetch.bind(window), showToast, escHtml,
  readField,                       // (slot 'pre'|'post') => 지금 그 칸의 글
  writeField,                      // (slot, text) => 보냈으면 true
  formatToken,                     // (artist, weight, withPrefix) => 지금 모드의 작가 태그
  getPreset = () => '',            // 지금 PE 프리셋 이름
  isNai = () => true,              // a: 단추는 NAI 에서만 뜻이 있다
}) {
  const panel = document.getElementById('artistLinkPanel');
  const seedPill = document.getElementById('seedLockPill');
  if (!panel) return null;
  const esc = typeof escHtml === 'function' ? escHtml : (value => String(value ?? '').replace(/[&<>"']/g, c => (
    {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c])));

  const el = document.createElement('div');
  el.className = 'artist-insert-tray';
  el.hidden = true;
  el.setAttribute('aria-label', '삽입 그룹');
  panel.before(el);

  let tracker = {items: [], solo: null, preset: '', rev: 0};
  let working = false;             // 이 판이 글을 고치는 중 - 그동안 맞추기를 쉰다(내가 쓴 글을 남의 손질로 오해하지 않게)
  let reconcileTimer = null;
  const weightTimers = new Map();  // 항목 id → 가중치 저장 타이머(휠은 바로 그리고 잠깐 뒤 쓴다)
  let anchorShown = false;

  const SLOT_FIELD = {pre: 'Prefix', post: 'Postfix'};
  const fmtWeight = value => {
    const n = round2(value);
    return Number.isFinite(n) ? n.toFixed(2).replace(/\.?0+$/, '') || '0' : '1';
  };
  const bodiesOf = artist => {
    const name = String(artist || '').trim();
    const out = [formatToken(name, 1, true), formatToken(name, 1, false), name];
    if (name.startsWith('@')) out.push(name.slice(1));
    return out.filter(Boolean);
  };
  const tokenOf = item => formatToken(item.artist, item.weight, item.with_prefix !== false);
  const itemById = id => (tracker.items || []).find(item => item.id === id) || null;

  // ── 서버 ───────────────────────────────────────────────────────────────
  async function post(body) {
    const res = await fetch('/api/artist-thumb/insert-tracker', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    receive(data);
    return data;
  }

  async function load() {
    try {
      const res = await fetch('/api/artist-thumb/insert-tracker', {cache: 'no-store'});
      if (res.ok) receive(await res.json(), {force: true});
    } catch (_) { /* 다음 알림 때 */ }
  }

  function receive(next, {force = false} = {}) {
    if (!next || typeof next !== 'object') return;
    if (!force && Number(next.rev) < Number(tracker.rev)) return;   // 늦게 온 옛 알림(다른 탭의 새 조작이 먼저 왔다)
    tracker = {items: [], solo: null, ...next};
    render();
    scheduleReconcile();
  }

  /** 글을 고치고 서버에 알린다 - 한 번에 하나. 글을 못 보냈으면 서버도 안 고친다. */
  async function act(edit, body) {
    if (working) return null;
    working = true;
    el.classList.add('is-busy');
    try {
      if (edit) {
        for (const [slot, text] of Object.entries(edit)) {
          if (text === readField(slot)) continue;
          if (!writeField(slot, text)) throw new Error(`${SLOT_FIELD[slot] || slot} 를 고치지 못했습니다 - 연결을 확인하세요.`);
        }
      }
      return body ? await post(body) : null;
    } catch (error) {
      showToast?.(error.message || '삽입 그룹 조작에 실패했습니다.', 'error');
      return null;
    } finally {
      working = false;
      el.classList.remove('is-busy');
      scheduleReconcile();
    }
  }

  // ── 글 손질 ─────────────────────────────────────────────────────────────
  /** 이 항목을 글에 (지금 값으로) 넣은 결과 - 있으면 그 자리를 바꾸고, 없으면 그 칸의 앞 · 뒤에. */
  function withItem(item, slot = item.slot) {
    const text = readField(slot);
    const hit = findArtistPiece(text, bodiesOf(item.artist));
    const token = tokenOf(item);
    return hit ? text.slice(0, hit.start) + token + text.slice(hit.end) : putArtistToken(text, slot, token);
  }

  function withoutItem(item, slot = item.slot) {
    const text = readField(slot);
    const hit = findArtistPiece(text, bodiesOf(item.artist));
    return hit ? removeArtistPiece(text, hit) : text;
  }

  /** 작가 패널 [삽입] - 그 칸에 넣고(있으면 가중치만) 추적을 시작한다. 넣었으면 서버 스냅숏, 못 넣었으면 null. */
  async function insert({artist, weight, slot = 'pre'}) {
    const name = String(artist || '').trim();
    if (!name) return null;
    const where = slot === 'post' ? 'post' : 'pre';
    const item = {artist: name, weight: round2(weight ?? 1), with_prefix: true, slot: where};
    const text = readField(where);
    const had = findArtistPiece(text, bodiesOf(name));
    const data = await act({[where]: withItem(item, where)},
      {op: 'add', artist: name, weight: item.weight, slot: where, with_prefix: true});
    if (data) {
      showToast?.(had ? `${SLOT_FIELD[where]} 에 있던 ${name} 를 ${tokenOf(item)} 로 바꿨습니다.`
        : `${SLOT_FIELD[where]} ${where === 'post' ? '맨 뒤' : '맨 앞'}에 ${tokenOf(item)} 를 넣었습니다.`, 'success');
    }
    return data;
  }

  // ── 맞추기 - 손으로 고친 글을 목록에 반영한다 ─────────────────────────────
  function scheduleReconcile(delay = 500) {
    if (reconcileTimer) clearTimeout(reconcileTimer);
    reconcileTimer = setTimeout(() => { reconcileTimer = null; void reconcile(); }, delay);
  }

  async function reconcile() {
    if (working || weightTimers.size) { scheduleReconcile(); return; }
    const items = tracker.items || [];
    if (!items.length) return;
    // 프리셋이 바뀌었다 - 서버가 읽을 때 확정한다(게으른 검사).
    const preset = String(getPreset() || '');
    if (tracker.preset && preset && preset !== tracker.preset) { await load(); return; }
    for (const item of items) {
      if (!item.on) continue;
      const hit = findArtistPiece(readField(item.slot), bodiesOf(item.artist));
      const patch = {};
      if (!hit) {
        patch.on = false;
      } else {
        if (Math.abs(round2(hit.weight) - round2(item.weight)) > 0.001) patch.weight = round2(hit.weight);
        if (isNai() && hit.withPrefix !== (item.with_prefix !== false)) patch.with_prefix = hit.withPrefix;
      }
      if (!Object.keys(patch).length) continue;
      await act(null, {op: 'update', id: item.id, ...patch});
      return;                                          // 한 번에 하나 - 답이 오면 다시 돈다
    }
  }

  // ── 그리기 ─────────────────────────────────────────────────────────────
  function place() {
    if (el.hidden || !seedPill) return;
    el.style.left = `${seedPill.offsetLeft}px`;
  }

  function render() {
    const items = tracker.items || [];
    el.hidden = !(items.length && anchorShown);
    if (el.hidden) return;
    const solo = tracker.solo || null;
    const scope = solo?.scope === 'group' ? 'group' : 'all';
    const nai = isNai();
    el.classList.toggle('has-solo', Boolean(solo));
    el.innerHTML = `
      <div class="ait-head">
        <span class="ait-title">삽입 그룹 <b>${items.length}</b></span>
        ${solo ? `<span class="ait-scope" role="group" aria-label="솔로 범위">
          <button type="button" data-ait-scope="all" class="${scope === 'all' ? 'is-on' : ''}" title="Prefix · Postfix 의 모든 작가를 잠깐 뺍니다">전체</button>
          <button type="button" data-ait-scope="group" class="${scope === 'group' ? 'is-on' : ''}" title="이 판의 다른 작가만 잠깐 뺍니다">그룹</button>
        </span>` : ''}
        <span class="ait-gap"></span>
        <button type="button" class="ait-commit" data-ait="commit" title="지금 글 그대로 확정 - 추적을 끝냅니다(프리셋을 바꿔도 확정)">확정</button>
      </div>
      ${items.map(item => {
        const on = Boolean(item.on);
        const soloHere = solo?.id === item.id;
        const dim = solo && !soloHere;
        const wp = item.with_prefix !== false;
        return `<div class="ait-chip${on ? '' : ' is-off'}${soloHere ? ' is-solo' : ''}${dim ? ' is-dim' : ''}" data-ait-id="${esc(item.id)}">
          ${nai ? `<button type="button" class="ait-pfx${wp ? ' is-on' : ''}" data-ait="prefix" title="${wp ? 'artist: 떼기' : 'artist: 붙이기'}">a:</button>` : ''}
          <button type="button" class="ait-slot" data-ait="slot" title="${item.slot === 'post' ? 'Postfix 맨 뒤 - 누르면 Prefix 맨 앞으로' : 'Prefix 맨 앞 - 누르면 Postfix 맨 뒤로'}">${item.slot === 'post' ? '뒤' : '앞'}</button>
          <button type="button" class="ait-name" data-ait="toggle" title="${on ? '끄기 - 글에서 뺍니다' : '켜기 - 글에 다시 넣습니다'}">${esc(item.artist)}</button>
          <button type="button" class="ait-weight" data-ait="weight" title="가중치 - 휠 0.01씩">×${esc(fmtWeight(item.weight))}</button>
          <button type="button" class="ait-solo${soloHere ? ' is-on' : ''}" data-ait="solo" title="${soloHere ? '솔로 끄기' : '이 작가만 - 생성할 때 다른 작가를 잠깐 뺍니다'}">◎</button>
          <button type="button" class="ait-remove" data-ait="remove" title="해제 - 글에서 빼고 목록에서도 지웁니다">✕</button>
        </div>`;
      }).join('')}`;
    place();
  }

  // ── 조작 ───────────────────────────────────────────────────────────────
  el.addEventListener('click', async event => {
    const scopeBtn = event.target.closest('[data-ait-scope]');
    if (scopeBtn) {
      const solo = tracker.solo;
      if (solo && solo.scope !== scopeBtn.dataset.aitScope) await act(null, {op: 'solo', id: solo.id, scope: scopeBtn.dataset.aitScope});
      return;
    }
    const button = event.target.closest('[data-ait]');
    if (!button) return;
    const action = button.dataset.ait;
    if (action === 'commit') {
      const data = await act(null, {op: 'commit'});
      if (data) showToast?.('삽입 그룹을 확정했습니다 - 지금 글 그대로 둡니다.', 'info');
      return;
    }
    const item = itemById(button.closest('[data-ait-id]')?.dataset.aitId);
    if (!item) return;
    if (action === 'toggle') {
      const on = !item.on;
      await act({[item.slot]: on ? withItem(item) : withoutItem(item)}, {op: 'update', id: item.id, on});
    } else if (action === 'prefix') {
      const next = {...item, with_prefix: item.with_prefix === false};
      await act(item.on ? {[item.slot]: withItem(next)} : null, {op: 'update', id: item.id, with_prefix: next.with_prefix});
    } else if (action === 'slot') {
      const slot = item.slot === 'post' ? 'pre' : 'post';
      // 두 칸을 함께 고친다 - 옛 칸에서 빼고 새 칸에 넣는다(새 칸에 이미 있으면 그 자리를 바꾼다).
      const edit = item.on ? {[item.slot]: withoutItem(item), [slot]: withItem({...item, slot}, slot)} : null;
      await act(edit, {op: 'update', id: item.id, slot});
    } else if (action === 'solo') {
      const soloHere = tracker.solo?.id === item.id;
      await act(null, {op: 'solo', id: soloHere ? null : item.id, scope: tracker.solo?.scope || 'all'});
    } else if (action === 'remove') {
      const data = await act(item.on ? {[item.slot]: withoutItem(item)} : null, {op: 'remove', id: item.id});
      if (data) showToast?.(`${item.artist} 를 ${SLOT_FIELD[item.slot]} 에서 뺐습니다.`, 'info');
    }
  });

  // 가중치 - 휠 한 칸 0.01. 판은 바로 그리고, 글 · 서버는 손을 멈춘 뒤에.
  el.addEventListener('wheel', event => {
    const button = event.target.closest('[data-ait="weight"]');
    if (!button) return;
    event.preventDefault();
    const item = itemById(button.closest('[data-ait-id]')?.dataset.aitId);
    if (!item) return;
    item.weight = Math.min(5, Math.max(0, round2(Number(item.weight) + (event.deltaY < 0 ? 0.01 : -0.01))));
    button.textContent = `×${fmtWeight(item.weight)}`;
    clearTimeout(weightTimers.get(item.id));
    weightTimers.set(item.id, setTimeout(async () => {
      weightTimers.delete(item.id);
      while (working) await new Promise(resolve => setTimeout(resolve, 60));
      const now = itemById(item.id);
      if (!now) return;
      now.weight = item.weight;
      await act(now.on ? {[now.slot]: withItem(now)} : null, {op: 'update', id: now.id, weight: now.weight});
    }, 200));
  }, {passive: false});

  // 판은 결과 뷰어(draggable) 안에 산다 - 누르는 동안 감싼 끌기를 끈다(작가 패널과 같은 이유).
  el.addEventListener('pointerdown', event => {
    const host = el.parentElement?.closest('[draggable="true"]');
    if (!host) return;
    host.draggable = false;
    const restore = () => {
      host.draggable = true;
      window.removeEventListener('pointerup', restore, true);
      window.removeEventListener('pointercancel', restore, true);
    };
    window.addEventListener('pointerup', restore, true);
    window.addEventListener('pointercancel', restore, true);
  });

  // 시드 알약이 보일 때만 - 작가 패널과 같은 자리 규칙.
  const syncAnchor = () => {
    const shown = Boolean(seedPill && seedPill.offsetParent !== null && seedPill.offsetWidth > 0);
    if (shown !== anchorShown) { anchorShown = shown; render(); } else place();
  };
  if (seedPill) {
    if (typeof ResizeObserver === 'function') new ResizeObserver(syncAnchor).observe(seedPill);
    if (typeof MutationObserver === 'function') {
      new MutationObserver(syncAnchor).observe(seedPill, {attributes: true, childList: true, characterData: true, subtree: true});
    }
  }
  setTimeout(() => { syncAnchor(); void load(); }, 1200);

  return {
    insert,
    /** WS `artist_insert_tracker` */
    receive,
    /** PE 글이 바뀌었다(어느 창이든) · 프리셋이 바뀌었을 수 있다 - 목록을 글에 맞춘다. */
    reconcile: () => scheduleReconcile(),
    reload: () => load(),
  };
}
