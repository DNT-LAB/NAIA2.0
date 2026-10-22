/**
 * 세션 와일드카드 창(사용자 결정 2026-10-21) - 랜덤 슬롯의 [세션 와일드카드 펼치기 ↗] 로 연다.
 *
 * 지금 랜덤 풀(세션 와일드카드)에 **실제로 들어 있는 줄**을 본다: 캐릭터마다 한 줄(썸네일 · 이름 · 작품 · 뽑힌 수 · ✕).
 * 줄을 누르면 그 줄 **하나만** 펼쳐진다(다른 줄은 접힌다 · 창 폭을 키우지 않는다): 단추 한 줄
 * [임시 고정] [즉시 생성] [랜덤+생성] + 그 캐릭터가 내보내는 프롬프트 줄(지금 출력 옵션이 걸린 모양).
 * 키 줄 = `__키__ [총 n명] [히스토리 n장]`(2026-10-22) - [히스토리] 는 이 풀의 그림 창(왼쪽 캐릭터 · 오른쪽 격자 · 크게 보기).
 * 뽑힌 수 단추도 그 창을 그 캐릭터로 연다.
 *
 *   임시 고정  랜덤 슬롯은 그대로 두고 다음 생성부터 그 캐릭터만. 직접 풀기 · 풀이 바뀜 · 재시작에 풀린다.
 *   즉시 생성  지금 메인 프롬프트 그대로 그 캐릭터로 한 장. 랜덤+생성 = Random 으로 새 프롬프트 뒤 한 장. 둘 다 뽑힌 수에 든다.
 *   ✕          이 풀에서만 빼기(숨김 아님). [풀 비우기] = 슬롯까지 지운다(두 번 누른다 · 누른 때의 풀만).
 *
 * 서버 = GET /api/character-viewer/session-pool · POST session-pool/remove · clear · pin · generate · GET session-pool/history.
 * 요청에는 **그린 때의 풀 키**를 싣는다 - 그사이 풀이 바뀌면 서버가 409 로 거절한다(Find 풀 탭 Codex 리뷰와 같은 규칙).
 */
import {createDraggablePanel} from './draggablePanel.mjs?v=20260926-childalign';
import {createSessionPoolHistoryWindow} from './sessionPoolHistoryWindow.mjs?v=20261022-sph2';
import {createImageLightbox} from './imageLightbox.mjs?v=20261022-sph3';

/** 지금 출력 옵션 -> 슬롯의 단추 이름 그대로(묶음 [이름+작품만] = drop_features · [이름만] = 그것 + drop_copyright). */
function optionLabels(options) {
  const o = options || {};
  const labels = [];
  if (o.parens) labels.push('괄호 제거');
  if (o.drop_features) labels.push(o.drop_copyright ? '이름만' : '이름+작품만');
  else if (o.drop_copyright) labels.push('작품명 제거');
  if (o.drop_name) labels.push('캐릭터명 제거');
  return labels;
}

export function createSessionPoolWindow({
  document: doc = document,
  escHtml = value => String(value ?? ''),
  showToast = () => {},
  openWcSave = () => {},
  onPoolChanged = () => {},
} = {}) {
  let panel = null;
  let info = null;
  let seq = 0;
  let query = '';
  let sort = 'order';                 // order(풀 차례) | picks(뽑힌 수)
  let openKey = '';                   // 펼친 줄 하나 = `그룹\u0000캐릭터`(하나 펼치면 다른 것은 접힌다 · 사용자 결정)
  let busy = '';                      // 진행 중인 일 = `할 일\u0000그룹\u0000캐릭터` · 'clear'
  let clearArmed = 0;
  let clearKey = '';
  let history = null;                 // 히스토리 창(sessionPoolHistoryWindow) - 처음 열 때 만든다

  const escAttr = value => escHtml(String(value ?? '')).replace(/"/g, '&quot;');
  const keyOf = member => `${member.group}\u0000${member.character}`;
  const active = () => !!(info && info.active);
  const pinKey = () => (active() && info.pin ? `${info.pin.group}\u0000${info.pin.character}` : '');

  function ensurePanel() {
    if (panel) return panel;
    panel = createDraggablePanel({
      document: doc,
      title: '세션 와일드카드',
      variant: 'spw',
      storageKey: 'session-pool-window',
      width: 440,
      height: 520,
      minWidth: 320,
      minHeight: 200,
      maxWidth: 900,
      resizable: true,
      // ⚠️ 이번 실행에서 처음 열 때는 창 틀의 전역 규칙(왼쪽 패널 | 결과 화면 경계 · 2026-09-27)이 이긴다 - 이 값은 그 밖의 경우.
      initial: {right: 360, y: 90},
      onClose: () => disarmClear(),
    });
    panel.body.innerHTML = `<div class="spw-key" data-spw-key></div>`
      + `<div class="spw-pin" data-spw-pin hidden></div>`
      + `<div class="spw-tools"><input class="spw-q" type="search" placeholder="줄 · 캐릭터 · 작품 검색" spellcheck="false" data-spw-q>`
      + `<button type="button" class="spw-btn" data-spw-sort="order">풀 차례</button>`
      + `<button type="button" class="spw-btn" data-spw-sort="picks">뽑힌 수</button></div>`
      + `<div class="spw-list" data-spw-list></div>`
      + `<div class="spw-foot"><button type="button" class="spw-btn" data-spw-save>와일드카드로 저장</button>`
      + `<span class="spw-sp"></span><button type="button" class="spw-btn is-danger" data-spw-clear></button></div>`;
    panel.body.addEventListener('click', onClick);
    panel.body.addEventListener('input', event => {
      if (!event.target.closest('[data-spw-q]')) return;
      query = event.target.value || '';
      render();
    });
    return panel;
  }

  function disarmClear() {
    clearTimeout(clearArmed);
    clearArmed = 0;
    clearKey = '';
  }

  function visibleMembers() {
    if (!active()) return [];
    const q = query.trim().toLowerCase();
    const rows = (info.members || []).filter(member => !q
      || `${member.character} ${member.group} ${member.line || ''}`.toLowerCase().includes(q));
    if (sort === 'picks') rows.sort((a, b) => (Number(b.picks) || 0) - (Number(a.picks) || 0));
    return rows;
  }

  function lineHtml(line) {
    const text = String(line || '');
    const match = /^(girl|boy|other)(,\s*)/i.exec(text);
    return match ? `<em>${escHtml(match[1])}</em>${escHtml(text.slice(match[1].length))}` : escHtml(text);
  }

  function rowHtml(member, last, pinned, pool) {
    const key = keyOf(member);
    const open = key === openKey;
    const isPinned = key === pinned;
    const working = what => busy === `${what}\u0000${key}`;
    const off = busy ? ' disabled' : '';
    const picks = Number(member.picks || 0);
    return `<div class="spw-row${key === last ? ' is-last' : ''}${isPinned ? ' is-pinned' : ''}${open ? ' is-open' : ''}"`
      + ` data-spw-group="${escAttr(member.group)}" data-spw-char="${escAttr(member.character)}" data-spw-pool="${pool}">`
      + `<div class="spw-head" data-spw-toggle role="button" tabindex="0" aria-expanded="${open ? 'true' : 'false'}">`
      + `<span class="spw-car" aria-hidden="true">${open ? '▾' : '▸'}</span>`
      + (member.thumbnail_url
        ? `<img class="spw-img" loading="lazy" decoding="async" alt="" src="${escAttr(member.thumbnail_url)}">`
        : `<span class="spw-img is-initial">${escHtml(String(member.character || '?').trim().charAt(0).toUpperCase() || '?')}</span>`)
      + `<span class="spw-name"><b>${isPinned ? '📌 ' : ''}${escHtml(member.character)}</b>`
      + `<span>${escHtml(member.group)}${member.hidden ? ' · 숨김' : ''}</span></span>`
      // 뽑힌 수 = 단추(사용자 결정) - 히스토리 창을 이 캐릭터로 연다.
      // 0 이어도 누를 수 있다: 뽑힌 수는 최근 500회 기록이라 그림이 남아 있어도 0 일 수 있다.
      + `<button type="button" class="spw-picks" data-spw-images title="이 캐릭터로 나온 그림 보기">`
      + `${picks.toLocaleString()}</button>`
      + `<button type="button" class="spw-rm" data-spw-rm title="이 풀에서만 빼기(숨김 아님)"${off}>`
      + `${working('remove') ? '…' : '✕'}</button></div>`
      + (open
        ? `<div class="spw-acts">`
          + `<button type="button" class="spw-act is-pin${isPinned ? ' is-on' : ''}" data-spw-pinact${off}`
          + ` title="${isPinned ? '임시 고정을 풀고 다시 랜덤' : '다음 생성부터 이 캐릭터만(랜덤 슬롯은 그대로)'}">`
          + `${working('pin') ? '…' : isPinned ? '고정 풀기' : '임시 고정'}</button>`
          + `<button type="button" class="spw-act" data-spw-gen="now"${off} title="지금 메인 프롬프트 그대로 이 캐릭터로 한 장">`
          + `${working('now') ? '…' : '즉시 생성'}</button>`
          + `<button type="button" class="spw-act" data-spw-gen="random"${off} title="Random 으로 새 프롬프트를 뽑고 이 캐릭터로 한 장">`
          + `${working('random') ? '…' : '랜덤+생성'}</button></div>`
          + `<div class="spw-line">${lineHtml(member.line)}</div>`
        : '')
      + `</div>`;
  }

  function render() {
    if (!panel) return;
    const keyEl = panel.body.querySelector('[data-spw-key]');
    const pinEl = panel.body.querySelector('[data-spw-pin]');
    const list = panel.body.querySelector('[data-spw-list]');
    // 제목은 이름만 - 인원 · 장 수는 키 줄로 옮겼다(사용자 지시 2026-10-22).
    panel.setTitle('세션 와일드카드');
    const shots = Number(info?.history_total || 0);
    const lost = Number(info?.history_lost || 0);
    const keyHtml = active()
      ? `<code>${escHtml(info.wildcard || '')}</code>`
        + `<span class="spw-chip is-count">총 ${Number(info.count || 0).toLocaleString()}명</span>`
        + `<button type="button" class="spw-histbtn" data-spw-history`
        + ` title="이 풀에서 나온 그림${lost ? ` · ${lost.toLocaleString()}장은 저장 없이 지워짐` : ''}">`
        + `히스토리 ${shots.toLocaleString()}장</button>`
        + optionLabels(info.options).map(text => `<span class="spw-chip">${escHtml(text)}</span>`).join('')
      : '';
    if (keyEl._html !== keyHtml) { keyEl._html = keyHtml; keyEl.innerHTML = keyHtml; }
    const pin = active() ? info.pin : null;
    const pinHtml = pin
      ? `<span>📌 임시 고정: <b>${escHtml(pin.character)}</b> — 다음 생성부터 이 캐릭터만</span>`
        + `<button type="button" class="spw-btn" data-spw-unpin data-spw-group="${escAttr(pin.group)}" data-spw-char="${escAttr(pin.character)}"`
        + ` data-spw-pool="${escAttr(info.key || '')}"${busy ? ' disabled' : ''}>풀기</button>`
      : '';
    pinEl.hidden = !pin;
    if (pinEl._html !== pinHtml) { pinEl._html = pinHtml; pinEl.innerHTML = pinHtml; }
    panel.body.querySelectorAll('[data-spw-sort]').forEach(button =>
      button.classList.toggle('is-on', button.dataset.spwSort === sort));
    const rows = visibleMembers();
    let html;
    if (!info) {
      html = '<div class="spw-empty">불러오는 중…</div>';
    } else if (!active()) {
      html = '<div class="spw-empty">지금 랜덤 풀(세션 와일드카드)이 없습니다.</div>';
    } else if (!rows.length) {
      html = '<div class="spw-empty">맞는 줄이 없습니다.</div>';
    } else {
      const last = info.last_pick ? `${info.last_pick.group}\u0000${info.last_pick.character}` : '';
      const pool = escAttr(info.key || '');
      const pinned = pinKey();
      html = rows.map(member => rowHtml(member, last, pinned, pool)).join('');
    }
    if (list._html !== html) {
      const keep = list.scrollTop;
      list._html = html;
      list.innerHTML = html;
      list.scrollTop = keep;
    }
    const clear = panel.body.querySelector('[data-spw-clear]');
    const save = panel.body.querySelector('[data-spw-save]');
    if (clear) {
      clear.hidden = !active();
      clear.disabled = !!busy;
      clear.textContent = busy === 'clear' ? '지우는 중…' : clearArmed ? '한 번 더 누르면 지웁니다' : '풀 비우기';
      clear.classList.toggle('is-armed', !!clearArmed);
    }
    if (save) save.hidden = !active();
  }

  async function refresh() {
    if (!panel || !panel.isOpen()) {
      // 이 창은 닫았어도 히스토리 창이 떠 있으면 그것은 계속 따라간다(새 그림 · 풀이 바뀜 - Codex 리뷰).
      if (history && history.isOpen()) await followHistoryOnly();
      return;
    }
    const mine = ++seq;
    let next;
    try {
      const res = await fetch('/api/character-viewer/session-pool', {cache: 'no-store'});
      const data = await res.json().catch(() => ({}));
      next = res.ok ? data : {active: false};
    } catch (_) {
      next = {active: false};
    }
    if (mine !== seq) return;                   // 늦게 온 옛 답은 버린다
    const changedPool = !info || !next.active || !info.active || info.key !== next.key;
    info = next;
    if (clearArmed && (!active() || info.key !== clearKey)) disarmClear();
    if (changedPool) openKey = '';              // 새 풀이면 펼침도 처음부터
    render();
    if (history && history.isOpen()) {
      if (changedPool && active()) history.follow(info.key || '');
      else void history.refresh();
    }
  }

  async function followHistoryOnly() {
    try {
      const res = await fetch('/api/character-viewer/session-pool', {cache: 'no-store'});
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.active && data.key) {
        if (!info || info.key !== data.key) info = data;
        history.follow(data.key);
        void history.refresh();
      }
    } catch (_) { /* 다음 갱신에서 다시 본다 */ }
  }

  async function request(path, body) {
    const res = await fetch(`/api/character-viewer/session-pool/${path}`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || '처리하지 못했습니다.');
    return data;
  }

  /** 줄 동작 하나. 이름 · 풀 키는 **그 줄을 그릴 때의 것**(누르는 사이 풀이 바뀌면 서버가 409). */
  async function rowAction(what, row) {
    const group = row?.dataset.spwGroup || '';
    const character = row?.dataset.spwChar || '';
    const pool = row?.dataset.spwPool || '';
    if (busy || !group || !character) return;
    // 고정 단추의 켬/끔도 **그 줄을 그릴 때의 상태**로 정한다.
    const pinOn = what === 'pin' && !row.classList.contains('is-pinned');
    busy = `${what}\u0000${group}\u0000${character}`;
    render();
    try {
      if (what === 'remove') {
        await request('remove', {key: pool, group, character});
        showToast(`${character} - 이 풀에서 뺐습니다`, 'info');
      } else if (what === 'pin' || what === 'unpin') {
        await request('pin', {key: pool, group, character, pin: pinOn});
        showToast(pinOn ? `${character} - 임시 고정: 다음 생성부터 이 캐릭터만` : '임시 고정을 풀었습니다 - 다시 랜덤', 'info');
      } else {
        await request('generate', {key: pool, group, character, random: what === 'random'});
        showToast(what === 'random' ? `${character} - 랜덤 프롬프트로 한 장 생성합니다` : `${character} - 한 장 생성합니다`, 'info');
      }
    } catch (error) {
      showToast(error.message || String(error), 'error');
    } finally {
      busy = '';
      await refresh();
      onPoolChanged();
    }
  }

  async function clearPool() {
    if (busy || !active()) return;
    if (!clearArmed || clearKey !== info.key) {
      disarmClear();
      clearKey = info.key;
      clearArmed = setTimeout(() => { disarmClear(); render(); }, 3000);
      render();
      return;
    }
    const target = clearKey;                     // 첫 클릭의 풀 - 서버가 키가 다르면 409
    disarmClear();
    busy = 'clear';
    render();
    try {
      await request('clear', {key: target});
      showToast('풀과 랜덤 슬롯을 지웠습니다', 'info');
    } catch (error) {
      showToast(error.message || String(error), 'error');
    } finally {
      busy = '';
      await refresh();
      onPoolChanged();
    }
  }

  // ── 히스토리 창(사용자 결정 2026-10-22) - 키 줄 [히스토리 n장] = 전체 · 줄의 뽑힌 수 = 그 캐릭터 ──────────
  function openHistory(select = null) {
    if (!active()) return;
    if (!history) history = createSessionPoolHistoryWindow({document: doc, escHtml, lightbox: createImageLightbox({document: doc, escHtml})});
    history.open(info.key || '', select);
  }

  function onClick(event) {
    const row = event.target.closest('[data-spw-char]');
    const unpin = event.target.closest('[data-spw-unpin]');
    if (unpin) { void rowAction('unpin', unpin); return; }
    if (event.target.closest('[data-spw-rm]')) { event.stopPropagation(); void rowAction('remove', row); return; }
    if (event.target.closest('[data-spw-images]')) {
      event.stopPropagation();
      openHistory({group: row?.dataset.spwGroup || '', character: row?.dataset.spwChar || ''});
      return;
    }
    if (event.target.closest('[data-spw-history]')) { openHistory(); return; }
    if (event.target.closest('[data-spw-pinact]')) { void rowAction('pin', row); return; }
    const gen = event.target.closest('[data-spw-gen]');
    if (gen) { void rowAction(gen.dataset.spwGen === 'random' ? 'random' : 'now', row); return; }
    if (event.target.closest('[data-spw-toggle]') && row) {
      // 하나 펼치면 다른 것은 접힌다(사용자 결정 2026-10-21).
      const key = `${row.dataset.spwGroup || ''}\u0000${row.dataset.spwChar || ''}`;
      openKey = openKey === key ? '' : key;
      render();
      return;
    }
    const sortBtn = event.target.closest('[data-spw-sort]');
    if (sortBtn) { sort = sortBtn.dataset.spwSort === 'picks' ? 'picks' : 'order'; render(); return; }
    if (event.target.closest('[data-spw-save]')) { void openWcSave(); return; }
    if (event.target.closest('[data-spw-clear]')) { void clearPool(); }
  }

  function open() {
    ensurePanel();
    if (panel.isOpen()) panel.raise(); else panel.open();
    if (panel.isCollapsed && panel.isCollapsed()) panel.expand();
    render();
    void refresh();
  }

  return {
    open,
    refresh,
    isOpen: () => !!(panel && panel.isOpen()),
  };
}
