/** Memo — 앱 안에서 쓰는 메모장.
 *
 *  프롬프트를 만들다 보면 "다음엔 이 조합" · "이 작가는 이 해상도" 같은 것을 적어 둘
 *  자리가 필요한데, 지금까지는 앱 밖으로 나가야 했다. **Tag Search 와 같은 옷**을
 *  입는다(사용자 지정) — 같은 자리, 같은 뼈대, 같은 클래스.
 *
 *      ┌──────────────────────────────────────┐
 *      │  검색                        [+ 새 메모] │
 *      ├───────────────┬──────────────────────┤
 *      │   메모 목록    │      본문 편집        │
 *      └───────────────┴──────────────────────┘
 *
 *  ⚠️ 저장은 **서버**다(`core/headless_memo_service.py`). LAN 링크로 폰에서 여는 일이
 *     흔해 localStorage 에 두면 기기마다 다른 메모가 생긴다.
 *  ⚠️ 새 WS 메시지 타입을 만들지 않는다 — 기존 모듈 디스패치(`set_module_param` /
 *     `get_module_state`)를 그대로 탄다. 웹 스모크 계약이 타입을 순서대로 세기 때문이다.
 */
export function createMemoPopup({
  document,
  window: win = window,
  escHtml = value => String(value ?? ''),
  showToast = () => {},
  setModuleParam = () => false,
  requestModuleState = () => false,
  onInsertText = null,
  setTimeoutFn = globalThis.setTimeout,
  clearTimeoutFn = globalThis.clearTimeout,
}) {
  // 타이핑이 멈추고 조금 뒤에 저장한다. 한 글자마다 디스크를 치면 파일이 종일 열린다.
  const SAVE_MS = 700;

  let popup = null;
  let notes = [];
  let selectedId = '';
  let query = '';
  let saveTimer = null;
  let onResize = null;
  // 저장 요청을 보낸 뒤 돌아오는 상태로 **본문 칸을 다시 그리지 않는다** — 그리면
  // 타이핑 도중 커서가 맨 뒤로 튄다. 어느 메모를 쓰던 중인지 여기서 든다.
  let editingId = '';

  const pick = selector => (popup ? popup.querySelector(selector) : null);

  function isOpen() {
    return !!popup && popup.style.display !== 'none';
  }

  function noteById(id) {
    return notes.find(note => note.id === id) || null;
  }

  function visibleNotes() {
    const needle = query.trim().toLowerCase();
    if (!needle) return notes;
    return notes.filter(note => (
      String(note.title || '').toLowerCase().includes(needle)
      || String(note.body || '').toLowerCase().includes(needle)
    ));
  }

  function setStatus(text, tone = '') {
    const el = pick('.tagsearch-status');
    if (!el) return;
    el.className = 'tagsearch-status' + (tone ? ` ${tone}` : '');
    el.textContent = text || '';
  }

  function fmtWhen(seconds) {
    const value = Number(seconds);
    if (!Number.isFinite(value) || value <= 0) return '';
    const date = new Date(value * 1000);
    const pad = n => String(n).padStart(2, '0');
    const today = new Date();
    const sameDay = date.toDateString() === today.toDateString();
    return sameDay
      ? `${pad(date.getHours())}:${pad(date.getMinutes())}`
      : `${date.getMonth() + 1}/${pad(date.getDate())}`;
  }

  // ── 목록 ──────────────────────────────────────────────────────────────
  function renderList() {
    const list = pick('.tagsearch-list');
    if (!list) return;
    const shown = visibleNotes();
    if (!shown.length) {
      list.innerHTML = `<div class="tagsearch-empty">${escHtml(
        notes.length ? '찾는 메모가 없습니다' : '아직 메모가 없습니다')}</div>`;
      return;
    }
    list.innerHTML = shown.map(note => {
      const on = note.id === selectedId ? ' is-active' : '';
      const title = String(note.title || '').trim() || '(제목 없음)';
      return `<button type="button" class="tagsearch-item${on}" data-note="${escHtml(note.id)}"
                title="${escHtml(title)}">
        <span class="tagsearch-item-tag">${escHtml(title)}</span>
        <b class="tagsearch-item-count">${escHtml(fmtWhen(note.updated))}</b>
      </button>`;
    }).join('');
  }

  // ── 본문 ──────────────────────────────────────────────────────────────
  function renderBody({keepText = false} = {}) {
    const box = pick('.tagsearch-desc');
    if (!box) return;
    const note = noteById(selectedId);
    if (!note) {
      box.innerHTML = `<div class="tagsearch-empty">${escHtml(
        notes.length ? '왼쪽에서 메모를 고르세요' : '[+ 새 메모] 로 시작하세요')}</div>`;
      return;
    }
    // 이미 이 메모를 그려 두었고 글자만 보존하면 되는 경우 - 다시 그리지 않는다.
    const editor = box.querySelector('.memo-editor');
    if (keepText && editor && editor.dataset.note === note.id) return;
    box.innerHTML = `
      <div class="memo-editor-wrap">
        <textarea class="memo-editor" data-note="${escHtml(note.id)}" spellcheck="false"
                  placeholder="첫 줄이 제목이 됩니다.">${escHtml(note.body || '')}</textarea>
        <div class="tagsearch-desc-actions">
          <button type="button" class="tagsearch-act" data-act="insert">프롬프트에 추가</button>
          <button type="button" class="tagsearch-act" data-act="copy">복사</button>
          <button type="button" class="tagsearch-act is-danger" data-act="delete">삭제</button>
        </div>
      </div>`;
    const area = box.querySelector('.memo-editor');
    area.addEventListener('input', () => scheduleSave(note.id, area.value));
    area.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); flushSave(); close(); }
    });
  }

  function selectNote(id) {
    if (selectedId === id) return;
    flushSave();
    selectedId = id;
    editingId = '';
    renderList();
    renderBody();
    pick('.memo-editor')?.focus();
  }

  // ── 저장 ──────────────────────────────────────────────────────────────
  function scheduleSave(id, text) {
    const note = noteById(id);
    if (note) {
      // 화면의 목록/제목이 곧바로 따라오게 낙관적으로 반영한다.
      note.body = text;
      note.title = String(text || '').split('\n').find(line => line.trim())?.trim().slice(0, 80) || '';
      renderList();
    }
    editingId = id;
    if (saveTimer) clearTimeoutFn(saveTimer);
    setStatus('입력 중...', 'busy');
    saveTimer = setTimeoutFn(() => { saveTimer = null; sendWrite(id, text); }, SAVE_MS);
  }

  function flushSave() {
    if (!saveTimer) return;
    clearTimeoutFn(saveTimer);
    saveTimer = null;
    const area = pick('.memo-editor');
    if (area) sendWrite(area.dataset.note, area.value);
  }

  function sendWrite(id, text) {
    if (!id) return;
    if (setModuleParam('memo', 'write', {id, body: String(text ?? '')}) === false) {
      setStatus('연결이 끊겼습니다', 'warn');
      return;
    }
    setStatus('저장했습니다', 'ok');
  }

  /** 백엔드가 돌려준 `module_state`(module_id === 'memo'). app.js 라우터가 넘겨준다. */
  function onState(message) {
    if (!message || message.module_id !== 'memo') return false;
    notes = Array.isArray(message.notes) ? message.notes : [];
    const focus = String(message.focus_id || '');
    if (focus) {
      selectedId = focus;
      editingId = '';
    } else if (!noteById(selectedId)) {
      selectedId = notes[0]?.id || '';
      editingId = '';
    }
    if (!isOpen()) return true;
    renderList();
    // 저장 응답으로 돌아온 것이면 **본문 칸을 건드리지 않는다** - 커서가 튄다.
    renderBody({keepText: !focus && String(message.written_id || '') === editingId});
    setStatus(notes.length ? `${notes.length}개` : '', notes.length ? 'ok' : '');
    return true;
  }

  // ── 위치 ── Tag Search 와 같은 자리(결과 이미지 영역 좌하단). ─────────────
  function position() {
    if (!popup) return;
    const margin = 10;
    const pw = popup.offsetWidth || 560;
    const ph = popup.offsetHeight || 380;
    const host = document.getElementById('resultViewer')
      || document.getElementById('rightTabResult')
      || document.querySelector('.right-tab-pane.active');
    const rect = host ? host.getBoundingClientRect() : null;
    let left;
    let top;
    if (rect && rect.width > pw + margin * 2 && rect.height > ph + margin * 2) {
      left = rect.left + margin;
      top = rect.bottom - ph - margin;
    } else {
      left = margin;
      top = win.innerHeight - ph - margin;
    }
    left = Math.max(margin, Math.min(left, win.innerWidth - pw - margin));
    top = Math.max(margin, Math.min(top, win.innerHeight - ph - margin));
    popup.style.left = `${Math.round(left)}px`;
    popup.style.top = `${Math.round(top)}px`;
  }

  function close() {
    flushSave();
    if (onResize) { win.removeEventListener('resize', onResize); onResize = null; }
    if (popup) popup.style.display = 'none';
  }

  function build() {
    popup = document.createElement('div');
    // Tag Search 의 뼈대를 그대로 쓴다 - 클래스를 갈아 끼우지 않는다(사용자 지정:
    // "태그 Search의 디자인을 재활용"). `memo-popup` 은 두 곳만 손보는 갈고리다.
    popup.className = 'tagsearch-popup memo-popup';
    popup.innerHTML = `
      <div class="tagsearch-head">
        <span class="tagsearch-title">Memo</span>
        <span class="tagsearch-status"></span>
        <button type="button" class="tagsearch-x" data-act="close" aria-label="닫기">&times;</button>
      </div>
      <div class="tagsearch-searchrow">
        <input class="tagsearch-input" type="search" autocomplete="off" spellcheck="false"
               placeholder="메모 안에서 찾기">
        <button type="button" class="tagsearch-act memo-new" data-act="create">+ 새 메모</button>
      </div>
      <div class="tagsearch-body">
        <div class="tagsearch-left">
          <div class="tagsearch-list"></div>
        </div>
        <div class="tagsearch-desc"></div>
      </div>
    `;
    document.body.appendChild(popup);

    const input = pick('.tagsearch-input');
    input.addEventListener('input', () => { query = input.value; renderList(); });
    input.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); close(); }
    });

    popup.addEventListener('click', event => {
      const item = event.target.closest('[data-note]');
      if (item) { selectNote(item.dataset.note); return; }
      const act = event.target.closest('[data-act]');
      if (!act) return;
      const action = act.dataset.act;
      if (action === 'close') { close(); return; }
      if (action === 'create') {
        flushSave();
        setModuleParam('memo', 'create', {body: ''});
        return;
      }
      const note = noteById(selectedId);
      if (!note) return;
      if (action === 'delete') {
        if (!win.confirm('이 메모를 지웁니다.')) return;
        if (saveTimer) { clearTimeoutFn(saveTimer); saveTimer = null; }
        editingId = '';
        setModuleParam('memo', 'delete', {id: note.id});
        return;
      }
      const text = String(pick('.memo-editor')?.value ?? note.body ?? '');
      if (action === 'copy') {
        win.navigator?.clipboard?.writeText(text)
          .then(() => showToast('메모를 복사했습니다', 'success'))
          .catch(() => showToast('복사하지 못했습니다', 'error'));
        return;
      }
      if (action === 'insert') {
        if (typeof onInsertText !== 'function' || !text.trim()) {
          showToast('프롬프트에 추가할 수 없습니다', 'error');
          return;
        }
        const ok = onInsertText(text.trim());
        showToast(ok === false ? '프롬프트에 추가하지 못했습니다' : '프롬프트에 추가했습니다',
                  ok === false ? 'error' : 'success');
      }
    });
  }

  function open() {
    if (!popup) build();
    popup.style.display = 'flex';
    renderList();
    renderBody();
    onResize = () => position();
    win.addEventListener('resize', onResize);
    position();
    // 목록은 열 때마다 다시 받는다 - 다른 기기/창에서 적었을 수 있다.
    requestModuleState('memo');
    win.requestAnimationFrame(() => {
      position();
      pick('.memo-editor')?.focus();
    });
  }

  return {open, close, isOpen, onState};
}
