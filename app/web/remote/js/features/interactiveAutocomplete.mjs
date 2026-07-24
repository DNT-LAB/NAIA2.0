// Interactive 슬롯 전용 자동완성.
//
// tagAssist.mjs 를 복제하지 않고 **필요한 부분만 격리 복사**한다(사용자 결정 2번안):
//   - IME 조합 처리 (compositionstart/update/end + 한글 stable retry + settle)
//   - 캐럿 토큰 추출 (여기서는 <input> 하나라 훨씬 단순 — 쉼표 분해/가중치/괄호 불필요)
//   - stale 응답 가드 (requestId 대조)
// 버린 것: 프리셋 3축, swapToken(토큰 치환), 캐럿 미러 위치계산, chunk/vibe 분기.
//
// 고도화 재료:
//   - 축 스코프 검색   interactive_autocomplete {query, axis}  (search_autocomplete axes)
//   - 관계 추천        interactive_related {tag, axis}          (TagRelationRanker)
//
// 이 모듈은 팝업 DOM 을 스스로 소유한다(공유 tagTooltip 미사용) — 우측 패널과 공존해야 하므로.
//
// cache-bust marker: 20260724-iac1

const HANGUL_RE = /[가-힣ㄱ-ㅎㅏ-ㅣ]/;
const DEBOUNCE_MS = 140;
const HANGUL_STABLE_RETRY_MS = 500;

export function createInteractiveAutocomplete({
  document,
  window: win = window,
  escHtml = value => String(value == null ? '' : value),
  send,                    // (payload) => void  — WS 송신
} = {}) {
  let input = null;        // 현재 바인딩된 <input>
  let axis = '';           // 현재 슬롯 축
  let onCommit = () => {};  // (tag) => void
  let getExisting = () => []; // () => string[]  이미 선택된 태그(중복 억제 표시용)

  let popup = null;
  let rows = [];           // [{tag, count, desc, group, axis, source}]
  let sel = -1;
  let open = false;
  let debounceTimer = null;
  let reqSeq = 0;
  let lastAcReqId = '';    // 최신 autocomplete 요청 id — 이것만 유효
  let lastRelReqId = '';   // 최신 related 요청 id
  let lastQuery = null;

  // IME 상태 (textarea 대신 input 하나만 추적하므로 WeakMap 불필요)
  const ime = {composing: false, active: false, base: '', start: 0, end: 0, data: '', stableTimer: null, settleTimer: null};

  // ---------------------------------------------------------------- popup DOM

  function ensurePopup() {
    if (popup) return popup;
    popup = document.createElement('div');
    popup.className = 'ia-ac-popup';
    popup.hidden = true;
    document.body.appendChild(popup);
    // mousedown 으로 처리(click 은 input blur 뒤라 팝업이 이미 닫힘)
    popup.addEventListener('mousedown', event => {
      const item = event.target.closest('.ia-ac-item');
      if (!item) return;
      event.preventDefault();   // input 포커스 유지
      commit(Number(item.dataset.idx));
    });
    popup.addEventListener('mousemove', event => {
      const item = event.target.closest('.ia-ac-item');
      if (!item) return;
      const idx = Number(item.dataset.idx);
      if (idx !== sel) { sel = idx; paint(); }
    });
    return popup;
  }

  function positionPopup() {
    if (!input || !popup) return;
    const r = input.getBoundingClientRect();
    popup.style.left = `${Math.round(r.left)}px`;
    popup.style.width = `${Math.round(r.width)}px`;
    // 아래로 펼치되 화면 밖이면 위로 뒤집는다.
    const belowSpace = win.innerHeight - r.bottom;
    const desired = Math.min(popup.scrollHeight || 240, 260);
    if (belowSpace < desired && r.top > desired) {
      popup.style.top = 'auto';
      popup.style.bottom = `${Math.round(win.innerHeight - r.top + 4)}px`;
    } else {
      popup.style.bottom = 'auto';
      popup.style.top = `${Math.round(r.bottom + 4)}px`;
    }
  }

  function paint() {
    if (!rows.length) { hide(); return; }
    ensurePopup();
    const existing = new Set((getExisting() || []).map(t => String(t).toLowerCase()));
    popup.innerHTML = rows.map((row, i) => {
      const already = existing.has(String(row.tag).toLowerCase());
      const meta = row.source
        ? `<span class="ia-ac-src">${escHtml(sourceLabel(row.source))}</span>`
        : `<span class="ia-ac-count">${escHtml(fmtCount(row.count))}</span>`;
      const kr = row.desc ? `<span class="ia-ac-kr">${escHtml(row.desc)}</span>` : '';
      return `<div class="ia-ac-item${i === sel ? ' selected' : ''}${already ? ' is-dupe' : ''}" data-idx="${i}">` +
        `<span class="ia-ac-tag">${escHtml(row.tag)}</span>${kr}${meta}` +
        (already ? '<span class="ia-ac-dupe-mark">있음</span>' : '') +
      '</div>';
    }).join('');
    popup.hidden = false;
    open = true;
    positionPopup();
  }

  function sourceLabel(source) {
    return {children: '하위', siblings: '유사', word_match: '연관'}[source] || source;
  }

  function fmtCount(n) {
    const v = Number(n || 0);
    if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
    if (v >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
    return String(v);
  }

  function hide() {
    open = false;
    sel = -1;
    rows = [];
    if (popup) popup.hidden = true;
  }

  // ---------------------------------------------------------------- query

  function currentText() {
    if (ime.active && ime.data) {
      // 조합 중에는 확정 전 글자를 반영한 가상 텍스트로 질의한다.
      const base = ime.base;
      return base.substring(0, ime.start) + ime.data + base.substring(ime.end);
    }
    return String(input?.value || '');
  }

  function scheduleQuery({force = false} = {}) {
    const text = currentText().trim();
    // 빈 입력이면 진행 중 debounce 까지 취소한다. 안 그러면 예약된 옛 query 가 나중에 발사돼
    // 지운 입력창에 팝업을 다시 연다(Codex H1).
    if (!text) { win.clearTimeout(debounceTimer); hide(); lastQuery = ''; return; }
    if (text === lastQuery && !force) return;
    lastQuery = text;
    win.clearTimeout(debounceTimer);
    debounceTimer = win.setTimeout(() => runQuery(text), DEBOUNCE_MS);
  }

  function runQuery(text) {
    if (typeof send !== 'function') return;
    const requestId = `iac_${++reqSeq}`;
    lastAcReqId = requestId;   // 이 응답만 유효(H1: 슬롯 전환/삭제 후 옛 응답 폐기)
    try {
      send({type: 'interactive_autocomplete', query: text, axis, requestId});
    } catch (error) { /* offline — 조용히 무시, 다음 입력에서 재시도 */ }
  }

  /** 슬롯에 이미 태그가 있을 때, 그 태그 기준 관계 추천을 요청한다(입력이 비었을 때). */
  function requestRelated(seedTag) {
    if (typeof send !== 'function' || !seedTag) return;
    const requestId = `iar_${++reqSeq}`;
    lastRelReqId = requestId;
    try {
      send({type: 'interactive_related', tag: seedTag, axis, requestId});
    } catch (error) { /* offline */ }
  }

  // 백엔드 응답 라우팅. 정확한 requestId + 현재 슬롯(axis) 이 일치할 때만 반영한다.
  // requestId 를 계열별(iac_/iar_)로 저장·대조하므로, autocomplete 와 related 가 서로의
  // seq 를 올려 stale 처리하는 문제가 없다(Codex H1).
  function onResult(message) {
    if (!input) return;
    const rid = String(message?.requestId || '');
    // 슬롯이 이미 바뀌었으면 폐기(늦게 도착한 옛 axis 응답이 새 입력창에 그려지는 것 방지).
    if (message.axis !== undefined && String(message.axis) !== axis) return;
    if (rid.startsWith('iac_')) { if (rid !== lastAcReqId) return; }
    else if (rid.startsWith('iar_')) { if (rid !== lastRelReqId) return; }
    else return;
    rows = Array.isArray(message?.results) ? message.results : [];
    sel = rows.length ? 0 : -1;
    paint();
  }

  // ---------------------------------------------------------------- commit

  function commit(idx) {
    const row = rows[idx];
    if (!row) return;
    onCommit(row.tag);
    if (input) {
      input.value = '';
      lastQuery = '';
    }
    hide();
    // 방금 넣은 태그 기준으로 다음 추천을 미리 띄운다(연속 입력 흐름).
    requestRelated(row.tag);
  }

  function move(delta) {
    if (!rows.length) return;
    sel = (sel + delta + rows.length) % rows.length;
    paint();
  }

  // ---------------------------------------------------------------- IME

  function clearImeTimers() {
    if (ime.stableTimer) { win.clearTimeout(ime.stableTimer); ime.stableTimer = null; }
    if (ime.settleTimer) { win.clearTimeout(ime.settleTimer); ime.settleTimer = null; }
  }

  function captureAnchor() {
    ime.active = true;
    ime.base = String(input?.value || '');
    const s = input?.selectionStart ?? ime.base.length;
    const e = input?.selectionEnd ?? s;
    ime.start = Math.max(0, Math.min(s, ime.base.length));
    ime.end = Math.max(ime.start, Math.min(e, ime.base.length));
  }

  function scheduleStableRetry() {
    if (ime.stableTimer) win.clearTimeout(ime.stableTimer);
    const text = currentText();
    if (!HANGUL_RE.test(text)) return;
    // 한글은 compositionupdate 가 자모 단위로 와서, 완성형이 안정될 때까지 한 박자 뒤 재질의.
    ime.stableTimer = win.setTimeout(() => {
      ime.stableTimer = null;
      if (ime.active && ime.data) scheduleQuery({force: true});
    }, HANGUL_STABLE_RETRY_MS);
  }

  function scheduleSettle() {
    if (ime.settleTimer) win.clearTimeout(ime.settleTimer);
    const settle = () => {
      ime.settleTimer = null;
      ime.active = false;
      ime.data = '';
      scheduleQuery({force: true});
    };
    const raf = typeof win.requestAnimationFrame === 'function' ? win.requestAnimationFrame.bind(win) : null;
    if (raf) raf(() => { ime.settleTimer = win.setTimeout(settle, 50); });
    else ime.settleTimer = win.setTimeout(settle, 50);
  }

  // ---------------------------------------------------------------- binding

  function bind(el, options = {}) {
    unbind();
    input = el;
    axis = String(options.axis || '');
    onCommit = typeof options.onCommit === 'function' ? options.onCommit : () => {};
    getExisting = typeof options.getExisting === 'function' ? options.getExisting : () => [];
    lastQuery = null;
    if (!input) return;

    input.addEventListener('compositionstart', onCompStart);
    input.addEventListener('compositionupdate', onCompUpdate);
    input.addEventListener('compositionend', onCompEnd);
    input.addEventListener('input', onInput);
    input.addEventListener('keydown', onKeydown);
    input.addEventListener('blur', onBlur);
    input.addEventListener('focus', onFocus);
  }

  function unbind() {
    if (input) {
      input.removeEventListener('compositionstart', onCompStart);
      input.removeEventListener('compositionupdate', onCompUpdate);
      input.removeEventListener('compositionend', onCompEnd);
      input.removeEventListener('input', onInput);
      input.removeEventListener('keydown', onKeydown);
      input.removeEventListener('blur', onBlur);
      input.removeEventListener('focus', onFocus);
    }
    // 진행 중 debounce 를 취소하고 요청 식별자를 리셋한다. 안 하면 슬롯 전환 후 옛 query 가
    // 새 axis 로 발사되거나(scheduleQuery), 늦게 온 옛 응답이 새 입력에 그려진다(Codex H1).
    win.clearTimeout(debounceTimer);
    clearImeTimers();
    lastQuery = null;
    lastAcReqId = '';
    lastRelReqId = '';
    hide();
    input = null;
  }

  function onCompStart() { clearImeTimers(); ime.composing = true; ime.data = ''; captureAnchor(); }
  function onCompUpdate(e) {
    if (!ime.active) captureAnchor();
    ime.composing = true;
    ime.data = String(e.data || '');
    scheduleQuery();
    scheduleStableRetry();
  }
  function onCompEnd(e) {
    if (!ime.active) captureAnchor();
    ime.data = String(e.data || ime.data || '');
    ime.composing = false;
    if (ime.stableTimer) { win.clearTimeout(ime.stableTimer); ime.stableTimer = null; }
    scheduleQuery({force: true});
    scheduleSettle();
  }
  function onInput(e) {
    if (ime.composing || e.isComposing) {
      if (e.data) ime.data = String(e.data);
      scheduleQuery();
      scheduleStableRetry();
      return;
    }
    ime.active = false;
    ime.data = '';
    if (ime.stableTimer) { win.clearTimeout(ime.stableTimer); ime.stableTimer = null; }
    scheduleQuery();
  }
  function onKeydown(e) {
    // IME 조합 중 Enter(keyCode 229 포함)는 조합 확정이므로 가로채지 않는다.
    if (ime.composing || e.isComposing || e.keyCode === 229) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); move(1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); move(-1); }
    else if (e.key === 'Enter' || e.key === 'Tab') {
      if (open && sel >= 0) { e.preventDefault(); commit(sel); }
      else if (input && input.value.trim()) {
        // 팝업이 없어도 Enter 로 자유 입력을 커밋한다(직접 입력 선호 사용자).
        e.preventDefault();
        input.value.split(',').map(s => s.trim()).filter(Boolean).forEach(onCommit);
        input.value = '';
        lastQuery = '';
        hide();
      }
    } else if (e.key === 'Escape') {
      if (open) { e.preventDefault(); hide(); }
    }
  }
  function onBlur() {
    // mousedown 커밋이 끝나도록 한 박자 뒤 닫는다.
    win.setTimeout(() => {
      if (document.activeElement !== input) hide();
    }, 150);
  }
  function onFocus() {
    // 포커스 시 입력이 비었고 슬롯에 태그가 있으면 관계 추천을 미리 띄운다.
    const existing = getExisting() || [];
    if (!String(input?.value || '').trim() && existing.length) {
      requestRelated(existing[existing.length - 1]);
    }
  }

  return {
    bind,
    unbind,
    onResult,
    setAxis: next => { axis = String(next || ''); },
    isOpen: () => open,
    reposition: positionPopup,
    destroy: () => { unbind(); if (popup) { popup.remove(); popup = null; } },
  };
}
