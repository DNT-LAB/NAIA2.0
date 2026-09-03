/**
 * 와일드카드 청크 — `$그룹:키` 로 부를 조각을 만들고 고치는 창.
 *
 * 사용자 지정 2026-09-03: "청크를 기존 UI에서 빼고 Memo UI를 따라 리디자인. 편집·추가·
 * 관리를 전부 지원하며 사용 가이드라인($)도 제공."
 *
 * ## 자리 배치 (사용자 지정 2026-09-03 2차)
 *
 *     머리줄   와일드카드 청크 · N개 로드됨 ······················ [ⓘ 가이드] [×]
 *     그룹줄   [그룹 ▾] [+ 그룹] ························ [키·값 검색      ]
 *     칸머리   키                          [+ 키 추가] │ 키값
 *     몸통     (키 목록)                              │ (값 편집 · 토큰 · 동작)
 *
 * ⚠️ **그룹과 키를 다른 줄로 갈랐다.** 한 줄에 [+ 그룹][+ 키] 를 붙여 뒀더니 무엇이
 *    무엇을 만드는지 읽히지 않았다. 그룹은 그룹줄에서, 키는 자기 목록 머리에서 만든다.
 * ⚠️ **편집 칸에 키 이름 입력을 두지 않는다.** 키는 왼쪽 목록이 정하고 이름 바꾸기는
 *    [이름] 이 한다. 예전에는 토큰 줄이 서버 키를, 버튼이 입력칸 키를 써서 이름을
 *    고치는 중에 둘이 어긋났다 - 입력칸을 없애 그 어긋남 자체를 없앴다.
 * ⚠️ 사용법은 `<details>` 가 아니라 **머리줄의 [ⓘ 가이드]** 다(다른 모듈과 같은
 *    `header-guide-btn` + `data-naia-guide`). 접이식은 펼칠 때마다 아래 칸을 밀어냈다.
 *
 * ⚠️ Tag Search 의 뼈대를 그대로 쓴다(Memo 가 그렇게 한다). 자체 `<style>` 주입 금지 —
 *    새 클래스는 언제나 `style.css` 에, 같은 커밋에([[feedback-popup-compact-style]]).
 * ⚠️ 값의 SSOT 는 백엔드(`core/instant_wildcard_service.py`)다.
 */

/** `$` 문법 안내. ⚠️ **코드와 맞춰 적는다** — `core/wildcard_processor.py:135-150` 실측. */
const CHUNK_GUIDE = [
  '$그룹 — 그 그룹에서 아무 키나 하나를 뽑습니다.',
  '',
  '$그룹:글자 — 이름에 그 글자가 들어가는 키들 중 하나를 뽑습니다. 정확히 일치할 필요가 없고,'
  + ' 하나만 걸리면 늘 그것이 나옵니다.',
  '',
  '⚠️ 걸리는 키가 하나도 없으면 그룹 전체에서 아무거나 나옵니다 — 오타를 내도 오류가 아니라'
  + ' 조용히 다른 것이 뽑힙니다.',
  '',
  '⚠️ 값 안에 __파일__ 을 써도 풀리지 않습니다. 값은 쉼표로만 나눕니다.',
].join('\n');

export function createWildcardChunkPopup({
  document: doc,
  window: win,
  escHtml,
  setModuleParam,
  requestModuleState,
  showToast,
  onInsertText,
  confirmDialog = async () => false,
  promptDialog = async () => null,
}) {
  let popup = null;
  let state = null;
  let query = '';
  let onResize = null;
  let dirty = false;

  const pick = selector => (popup ? popup.querySelector(selector) : null);

  function isOpen() {
    return !!(popup && popup.style.display !== 'none');
  }

  function groups() {
    return Array.isArray(state?.files) ? state.files : [];
  }

  function items() {
    return Array.isArray(state?.items) ? state.items : [];
  }

  function currentFile() {
    return String(state?.current_file || '');
  }

  function currentGroup() {
    return String(state?.current_group || '');
  }

  function currentKey() {
    return String(state?.current_key || '');
  }

  function token() {
    const key = currentKey();
    return key ? `$${currentGroup()}:${key}` : `$${currentGroup()}`;
  }

  function setStatus(text, tone = '') {
    const el = pick('.tagsearch-status');
    if (!el) return;
    el.textContent = text || '';
    el.className = 'tagsearch-status' + (tone ? ` ${tone}` : '');
  }

  /** 검색은 **키와 값 둘 다** 본다 - 키 이름을 잊어도 내용으로 찾는다. */
  function visibleItems() {
    const needle = query.trim().toLowerCase();
    if (!needle) return items();
    return items().filter(item =>
      String(item.key || '').toLowerCase().includes(needle)
      || String(item.value || '').toLowerCase().includes(needle));
  }

  function renderList() {
    const list = pick('.tagsearch-list');
    if (!list) return;
    const shown = visibleItems();
    if (!shown.length) {
      list.innerHTML = `<div class="tagsearch-empty">${escHtml(
        items().length ? '찾는 키가 없습니다.' : '이 그룹에 키가 없습니다. [+ 키 추가] 를 누르세요.')}</div>`;
      return;
    }
    // ⚠️ 선택 표시는 `.is-active` 다(Tag Search·Memo 와 같은 이름).
    list.innerHTML = shown.map(item => `
      <button type="button" class="tagsearch-item wcchunk-item${item.selected ? ' is-active' : ''}"
              data-key="${escHtml(String(item.key || ''))}">
        <span class="tagsearch-item-tag">${escHtml(String(item.key || ''))}</span>
        <span class="wcchunk-val">${escHtml(String(item.value || '').slice(0, 90))}</span>
      </button>`).join('');
  }

  function renderGroups() {
    const select = pick('.wcchunk-group');
    if (!select) return;
    const list = groups();
    select.innerHTML = list.length
      ? list.map(file => `<option value="${escHtml(String(file.name || ''))}"${file.selected ? ' selected' : ''}>`
        + `${escHtml(String(file.group || file.name || ''))} (${Number(file.count) || 0})</option>`).join('')
      : '<option value="">그룹 없음</option>';
  }

  /**
   * 오른쪽 편집 칸 — **값과 동작만** 있다(키 이름은 왼쪽 목록이 정한다).
   *
   * ⚠️ 치고 있는 중에는 다시 그리지 않는다(`keepFields`) - 상태 에코가 올 때마다 다시
   *    그리면 방금 친 글자가 사라진다.
   */
  function renderEditor({keepFields = false} = {}) {
    const box = pick('.tagsearch-desc');
    if (!box) return;
    if (keepFields && box.querySelector('.wcchunk-value')) return;
    const key = currentKey();
    if (!key) {
      box.innerHTML = `<div class="tagsearch-empty">${escHtml(
        '왼쪽에서 키를 고르거나 [+ 키 추가] 를 누르세요.')}</div>`;
      return;
    }
    box.innerHTML = `
      <div class="wcchunk-edit">
        <textarea class="wcchunk-value" spellcheck="false"
                  placeholder="1girl, solo, looking at viewer">${escHtml(String(state?.current_value || ''))}</textarea>
        <div class="wcchunk-token">
          <code>${escHtml(token())}</code>
          <button type="button" class="tagsearch-act" data-act="copy">복사</button>
          <button type="button" class="tagsearch-act" data-act="insert">넣기</button>
        </div>
        <div class="tagsearch-desc-actions">
          <button type="button" class="tagsearch-act is-primary" data-act="save">저장</button>
          <button type="button" class="tagsearch-act" data-act="rename">이름</button>
          <button type="button" class="tagsearch-act is-danger" data-act="delete">삭제</button>
        </div>
      </div>`;
    box.querySelector('.wcchunk-value')?.addEventListener('input', () => {
      dirty = true;
      setStatus('저장 안 됨', 'warn');
    });
  }

  function editedValue() {
    return String(pick('.wcchunk-value')?.value ?? '');
  }

  /**
   * 고치던 값을 버리고 자리를 옮겨도 되는지 묻고, 좋다고 하면 `go()` 를 부른다.
   *
   * ⚠️ 자리를 옮기는 **모든 길**이 여기를 지나야 한다(목록 클릭 · 그룹 전환 · 키 추가 ·
   *    닫기). 한 길만 막으면 나머지로 값이 조용히 사라진다 —
   *    [[feedback-two-entry-points]] 와 같은 함정이다.
   */
  async function leaveCurrent(go) {
    if (dirty) {
      const ok = await Promise.resolve(confirmDialog('저장하지 않은 값이 있습니다. 버리고 옮길까요?', {
        title: '청크 편집', okText: '버리고 이동', cancelText: '취소',
      }));
      if (!ok) return false;
    }
    dirty = false;
    go();
    return true;
  }

  function save() {
    const key = currentKey();
    if (!key) { showToast('고른 키가 없습니다', 'error'); return; }
    // ⚠️ 보내기 **전에** `dirty` 를 내리지 않는다. 내려 두면 전송이 실패해도 화면은
    //    저장된 것처럼 굴고, 다음 에코가 방금 친 값을 덮어 쓴다.
    const sent = setModuleParam('instant_wildcard', 'upsert', JSON.stringify({
      file: currentFile(), key, value: editedValue(),
    }));
    if (sent === false) {
      showToast('저장하지 못했습니다 - 연결을 확인하세요', 'error');
      setStatus('저장 안 됨', 'warn');
      return;
    }
    dirty = false;
    setStatus('저장 중…');
  }

  async function rename() {
    const oldKey = currentKey();
    if (!oldKey) return;
    const next = await Promise.resolve(promptDialog('새 키 이름', {
      title: '키 이름 바꾸기', okText: '변경', cancelText: '취소', defaultValue: oldKey,
    }));
    if (!next || next === oldKey) return;
    // ⚠️ 같은 이름이 이미 있으면 서버가 **조용히 덮어쓴다** - 먼저 묻는다.
    if (items().some(item => String(item.key || '') === next)) {
      const ok = await Promise.resolve(confirmDialog(`'${next}' 가 이미 있습니다. 덮어쓸까요?`, {
        title: '키 덮어쓰기', okText: '덮어쓰기', cancelText: '취소',
      }));
      if (!ok) return;
    }
    setModuleParam('instant_wildcard', 'rename', JSON.stringify({
      file: currentFile(), old_key: oldKey, new_key: next,
    }));
  }

  async function removeKey() {
    const key = currentKey();
    if (!key) return;
    const ok = await Promise.resolve(confirmDialog(`'${key}' 를 지웁니다.`, {
      title: '청크 키 삭제', okText: '삭제', cancelText: '취소',
    }));
    if (!ok) return;
    setModuleParam('instant_wildcard', 'delete', JSON.stringify({file: currentFile(), key}));
  }

  async function addGroup() {
    const name = await Promise.resolve(promptDialog('새 그룹 이름', {
      title: '청크 그룹 추가', okText: '추가', cancelText: '취소', placeholder: 'characters',
    }));
    if (!name) return;
    setModuleParam('instant_wildcard', 'add_group', name);
  }

  /**
   * 값의 첫 태그에서 키 이름을 짐작한다. 옛 청크 패널의 규칙을 그대로 옮겼다 —
   * 두 곳이 다른 이름을 지으면 같은 글을 담아도 결과가 달라진다.
   */
  function suggestKeyFromValue(value) {
    const firstToken = (value || '')
      .split(/[,\n]/)
      .map(part => part.trim())
      .find(Boolean) || '';
    const cleaned = firstToken
      .replace(/^[({[\s]+|[)}\]\s]+$/g, '')
      .replace(/^[+-]?\d+(?:\.\d+)?::\s*/, '')
      .replace(/\s*::\s*$/, '')
      .replace(/^#+/, '')
      .replace(/[^\p{L}\p{N}_-]+/gu, '_')
      .replace(/^_+|_+$/g, '')
      .slice(0, 40);
    return cleaned || `chunk_${Date.now().toString(36)}`;
  }

  /**
   * 이름을 먼저 묻고 만든다 - 편집 칸에 이름 입력을 두지 않기 때문이다.
   * `value` 를 주면 그 값으로 바로 만든다(프롬프트에서 고른 글을 청크로 만드는 길).
   */
  async function addKey({value = '', suggested = ''} = {}) {
    const name = await Promise.resolve(promptDialog('새 키 이름', {
      title: '청크 키 추가', okText: '추가', cancelText: '취소', placeholder: 'girl',
      defaultValue: suggested || (value ? suggestKeyFromValue(value) : ''),
    }));
    if (!name) return;
    if (items().some(item => String(item.key || '') === name)) {
      showToast(`'${name}' 는 이미 있습니다`, 'error');
      return;
    }
    setModuleParam('instant_wildcard', 'upsert', JSON.stringify({
      file: currentFile(), key: name, value,
    }));
  }

  /**
   * 프롬프트에서 고른 글을 청크로 만든다 — **옛 청크 패널을 대신하는 길**이다.
   *
   * ⚠️ 팝업을 새로 만들지 않는다. 이미 있는 이 창을 열고 이름만 물어 바로 만든다
   *    (사용자 지적: 팝업을 또 만드는 것은 번거롭다).
   * ⚠️ 상태가 아직 없으면 그룹을 몰라 `upsert` 가 갈 곳이 없다 - 먼저 받고 나서 만든다.
   */
  async function addFromSelection(value) {
    const text = String(value || '').trim();
    if (!text) { showToast('고른 글이 없습니다', 'error'); return; }
    open();
    if (!currentFile()) {
      requestModuleState('instant_wildcard');
      for (let i = 0; i < 20 && !currentFile(); i += 1) {
        await new Promise(resolve => win.setTimeout(resolve, 100));
      }
    }
    if (!currentFile()) { showToast('청크 그룹을 불러오지 못했습니다', 'error'); return; }
    await addKey({value: text});
  }

  function onState(message) {
    const previousKey = currentKey();
    const nextKey = String(message?.current_key || '');
    // ⚠️ 치는 중에는 편집 칸을 갈아 끼우지 않는다. 고른 키가 **바뀐 경우**에만 새로 그린다.
    const typing = dirty && nextKey === previousKey;
    state = message || null;
    if (!typing) dirty = false;
    renderGroups();
    renderList();
    renderEditor({keepFields: typing});
    const count = Number(state?.flat_count) || 0;
    if (typing) setStatus('저장 안 됨', 'warn');
    else setStatus(count ? `${count.toLocaleString()}개 로드됨` : '');
  }

  // ── 위치 ── Memo·Tag Search 와 **같은 자리**(결과 이미지 영역 좌하단). ──────────
  // ⚠️ 고정 offset 을 쓰지 않는다 - 결과 정보 패널은 드래그로 높이가 변한다.
  function position() {
    if (!popup) return;
    const margin = 10;
    const pw = popup.offsetWidth || 660;
    const ph = popup.offsetHeight || 440;
    const host = doc.getElementById('resultViewer')
      || doc.getElementById('rightTabResult')
      || doc.querySelector('.right-tab-pane.active');
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
    if (onResize) { win.removeEventListener('resize', onResize); onResize = null; }
    if (popup) popup.style.display = 'none';
  }

  function build() {
    popup = doc.createElement('div');
    popup.className = 'tagsearch-popup wcchunk-popup';
    popup.innerHTML = `
      <div class="tagsearch-head">
        <span class="tagsearch-title">와일드카드 청크</span>
        <span class="tagsearch-status"></span>
        <button type="button" class="header-guide-btn" data-naia-guide="${escHtml(CHUNK_GUIDE)}">ⓘ 가이드</button>
        <button type="button" class="tagsearch-x" data-act="close" aria-label="닫기">&times;</button>
      </div>
      <div class="tagsearch-searchrow wcchunk-grouprow">
        <select class="mod-select wcchunk-group" aria-label="청크 그룹"></select>
        <button type="button" class="tagsearch-act" data-act="group">+ 그룹</button>
        <input class="tagsearch-input" type="search" autocomplete="off" spellcheck="false"
               placeholder="키·값 검색">
      </div>
      <div class="wcchunk-colhead">
        <div class="wcchunk-colhead-left">
          <span>키</span>
          <button type="button" class="tagsearch-act" data-act="newkey">+ 키 추가</button>
        </div>
        <div class="wcchunk-colhead-right"><span>키값</span></div>
      </div>
      <div class="tagsearch-body">
        <div class="tagsearch-left"><div class="tagsearch-list"></div></div>
        <div class="tagsearch-desc"></div>
      </div>`;
    doc.body.appendChild(popup);

    const input = popup.querySelector('.tagsearch-input');
    input.addEventListener('input', () => { query = input.value; renderList(); });
    input.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); void leaveCurrent(close); }
    });
    const groupSelect = popup.querySelector('.wcchunk-group');
    groupSelect.addEventListener('change', event => {
      const next = event.target.value || '';
      void leaveCurrent(() => {
        setModuleParam('instant_wildcard', 'select_file', next);
      }).then(moved => {
        // 취소했으면 고르개를 원래 그룹으로 되돌린다 - 안 되돌리면 고르개는 새 그룹인데
        // 목록은 옛 그룹이라 한 화면이 두 답을 보인다.
        if (!moved) groupSelect.value = currentFile();
      });
    });

    popup.addEventListener('click', event => {
      // ⚠️ 동작 버튼을 **줄보다 먼저** 본다 - 줄이 목록 전체를 덮고 있다.
      const act = event.target.closest('[data-act]');
      if (act) {
        const action = act.dataset.act;
        if (action === 'close') { void leaveCurrent(close); return; }
        if (action === 'group') { void addGroup(); return; }
        if (action === 'newkey') { void leaveCurrent(() => { void addKey(); }); return; }
        if (action === 'save') { save(); return; }
        if (action === 'rename') { void rename(); return; }
        if (action === 'delete') { void removeKey(); return; }
        if (action === 'copy') {
          win.navigator?.clipboard?.writeText(token())
            .then(() => showToast(`${token()} 복사했습니다`, 'success'))
            .catch(() => showToast('복사하지 못했습니다', 'error'));
          return;
        }
        if (action === 'insert') {
          if (typeof onInsertText !== 'function') {
            showToast('프롬프트에 넣을 수 없습니다', 'error');
            return;
          }
          const ok = onInsertText(token());
          showToast(ok === false ? '프롬프트에 넣지 못했습니다' : `${token()} 를 넣었습니다`,
                    ok === false ? 'error' : 'success');
        }
        return;
      }
      const row = event.target.closest('[data-key]');
      if (!row) return;
      void leaveCurrent(() => {
        setModuleParam('instant_wildcard', 'select_key', row.dataset.key || '');
      });
    });
  }

  function open() {
    if (!popup) build();
    popup.style.display = 'flex';
    renderGroups();
    renderList();
    renderEditor({keepFields: true});
    onResize = () => position();
    win.addEventListener('resize', onResize);
    position();
    // 열 때마다 다시 받는다 - 다른 창에서 고쳤을 수 있다.
    requestModuleState('instant_wildcard');
    win.requestAnimationFrame(position);
  }

  function toggle() {
    if (isOpen()) void leaveCurrent(close);
    else open();
  }

  return {open, close, toggle, isOpen, onState, addFromSelection};
}
