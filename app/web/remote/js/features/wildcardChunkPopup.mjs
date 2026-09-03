/**
 * 와일드카드 청크 — `$그룹:키` 로 부를 조각을 만들고 고치는 창.
 *
 * 사용자 지정 2026-09-03: "청크를 기존 UI에서 빼고 Memo UI를 따라 리디자인. 편집·추가·
 * 관리를 전부 지원하며 사용 가이드라인($)도 제공."
 *
 * ⚠️ **Tag Search 의 뼈대를 그대로 쓴다**(Memo 가 그렇게 한다). 클래스를 갈아 끼우지
 *    않고 `wcchunk-popup` 을 갈고리로 두 곳만 손본다 — 팝업마다 제 옷을 지으면 화면에
 *    앉힐 자리가 사라진다([[feedback-popup-compact-style]]).
 * ⚠️ 값의 SSOT 는 **백엔드**(`core/instant_wildcard_service.py`)다. 여기서는 서버가 준
 *    상태를 그리고, 바꾸면 `set_param` 으로 되돌려 보낸 뒤 **서버가 준 것으로 다시 그린다.**
 *    화면에 사본을 두면 두 잣대가 어긋난다.
 * ⚠️ 이 창이 열리기 전까지 인스턴트 키를 고칠 길이 **아예 없었다**(옛 `instant_wildcard`
 *    모듈 팝업은 런처에 등록돼 있지 않고 여는 호출이 0건이었다 — 실측 2026-09-03).
 */
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
        items().length ? '찾는 키가 없습니다.' : '이 그룹에 키가 없습니다. [+ 새 키] 로 만드세요.')}</div>`;
      return;
    }
    // ⚠️ 선택 표시는 `.is-active` 다(Tag Search·Memo 와 같은 이름). `is-on` 을 쓰면
    //    CSS 가 없어 아무 표시도 안 난다.
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
   * 오른쪽 편집 칸.
   *
   * ⚠️ 치고 있는 중에는 다시 그리지 않는다({keepFields}) - 서버 응답이 올 때마다 커서가
   *    튀고 방금 친 글자가 사라진다(설정 패널이 같은 함정을 밟았다).
   */
  function renderEditor({keepFields = false} = {}) {
    const box = pick('.tagsearch-desc');
    if (!box) return;
    if (keepFields && box.querySelector('.wcchunk-value')) return;
    const key = String(state?.current_key || '');
    const value = String(state?.current_value || '');
    const group = currentGroup();
    const token = key ? `$${group}:${key}` : `$${group}`;
    box.innerHTML = `
      <div class="wcchunk-edit">
        <label class="wcchunk-field">
          <span>키</span>
          <input class="wcchunk-key-input" type="text" spellcheck="false"
                 placeholder="girl" value="${escHtml(key)}">
        </label>
        <label class="wcchunk-field wcchunk-field-grow">
          <span>값</span>
          <textarea class="wcchunk-value" spellcheck="false"
                    placeholder="1girl, solo, looking at viewer">${escHtml(value)}</textarea>
        </label>
        <!-- ⚠️ 여기 적힌 토큰과 [복사]·[넣기] 가 쓰는 값은 **같아야 한다.** 예전에는
             글자는 서버 키, 버튼은 입력칸 키를 써서 이름을 고치는 중에 서로 달랐다.
             이제 입력칸이 바뀌면 이 줄도 함께 고쳐진다(아래 input 처리). -->
        <div class="wcchunk-token">
          <code>${escHtml(token)}</code>
          <button type="button" class="tagsearch-act" data-act="copy">복사</button>
          <button type="button" class="tagsearch-act" data-act="insert">프롬프트에 넣기</button>
        </div>
        <div class="tagsearch-desc-actions">
          <button type="button" class="tagsearch-act is-primary" data-act="save">저장</button>
          <button type="button" class="tagsearch-act" data-act="rename"${key ? '' : ' disabled'}>이름</button>
          <button type="button" class="tagsearch-act is-danger" data-act="delete"${key ? '' : ' disabled'}>삭제</button>
        </div>
        <details class="wcchunk-guide">
          <summary>$ 사용법</summary>
          <div><code>$${escHtml(group || '그룹')}</code> — 그 그룹에서 <b>아무 키나 하나</b></div>
          <div><code>$${escHtml(group || '그룹')}:${escHtml(key || '키')}</code> — 이름에
            <b>그 글자가 들어가는</b> 키들 중 하나. 하나만 걸리면 늘 그것이 나옵니다.</div>
          <div class="wcchunk-guide-note">⚠️ 걸리는 키가 <b>하나도 없으면 그룹 전체에서
            아무거나</b> 나옵니다 — 오타를 내도 조용히 다른 것이 뽑힙니다.
            값 안에 <code>__파일__</code> 을 써도 <b>풀리지 않습니다</b>(쉼표로만 나눕니다).</div>
        </details>
      </div>`;
    const valueBox = box.querySelector('.wcchunk-value');
    const keyBox = box.querySelector('.wcchunk-key-input');
    [valueBox, keyBox].forEach(el => el?.addEventListener('input', () => {
      dirty = true;
      setStatus('저장 안 됨', 'warn');
    }));
    // 키를 고치면 토큰 줄도 그 자리에서 따라 바뀐다 - 보이는 것과 버튼이 쓰는 것이
    // 어긋나면 엉뚱한 토큰을 복사하게 된다.
    keyBox?.addEventListener('input', () => {
      const code = box.querySelector('.wcchunk-token code');
      if (!code) return;
      const now = String(keyBox.value || '').trim();
      code.textContent = now ? `$${currentGroup()}:${now}` : `$${currentGroup()}`;
    });
  }

  function editedKey() {
    return String(pick('.wcchunk-key-input')?.value || '').trim();
  }

  /**
   * 고치던 값을 버리고 자리를 옮겨도 되는지 묻고, 좋다고 하면 `go()` 를 부른다.
   *
   * ⚠️ 자리를 옮기는 **모든 길**이 여기를 지나야 한다(목록 클릭 · 그룹 전환 · 새 키 ·
   *    닫기). 한 길만 막아 두면 나머지로 값이 조용히 사라진다 —
   *    [[feedback-two-entry-points]] 와 같은 함정이다.
   */
  async function leaveCurrent(go) {
    if (dirty) {
      const ok = await Promise.resolve(confirmDialog('저장하지 않은 값이 있습니다. 버리고 옮길까요?', {
        title: '청크 편집', okText: '버리고 이동', cancelText: '취소',
      }));
      if (!ok) return;
    }
    dirty = false;
    go();
  }

  function editedValue() {
    return String(pick('.wcchunk-value')?.value ?? '');
  }

  function save() {
    const key = editedKey();
    if (!key) { showToast('키 이름이 필요합니다', 'error'); return; }
    // ⚠️ 보내기 **전에** `dirty` 를 내리지 않는다. 내려 두면 전송이 실패해도 화면은
    //    저장된 것처럼 굴고, 다음 에코가 방금 친 값을 덮어 쓴다. 성공을 확인하고 내린다.
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
    const oldKey = String(state?.current_key || '');
    if (!oldKey) return;
    const next = await Promise.resolve(promptDialog('새 키 이름', {
      title: '키 이름 바꾸기', okText: '변경', cancelText: '취소', defaultValue: oldKey,
    }));
    if (!next || next === oldKey) return;
    setModuleParam('instant_wildcard', 'rename', JSON.stringify({
      file: currentFile(), old_key: oldKey, new_key: next,
    }));
  }

  async function removeKey() {
    const key = String(state?.current_key || '');
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

  /** 새 키는 편집 칸을 비우는 것으로 시작한다 - 저장을 눌러야 서버에 생긴다. */
  function newKey() {
    if (state) { state.current_key = ''; state.current_value = ''; }
    renderEditor();
    renderList();
    setStatus('새 키 - 저장을 누르면 만들어집니다');
    pick('.wcchunk-key-input')?.focus();
  }

  function onState(message) {
    const previousKey = String(state?.current_key || '');
    const nextKey = String(message?.current_key || '');
    // ⚠️ **치고 있는 중에는 편집 칸을 갈아 끼우지 않는다.** 상태 에코는 아무 때나 오는데,
    //    그때마다 다시 그리면 방금 친 글자가 사라진다. 고른 키가 **바뀐 경우**에만 새로
    //    그린다 - 그건 사용자가 옮겨 간 것이라 새 값을 보여 주는 게 맞다.
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
    const pw = popup.offsetWidth || 560;
    const ph = popup.offsetHeight || 380;
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
        <button type="button" class="tagsearch-x" data-act="close" aria-label="닫기">&times;</button>
      </div>
      <div class="tagsearch-searchrow">
        <select class="mod-select wcchunk-group" aria-label="청크 그룹"></select>
        <input class="tagsearch-input" type="search" autocomplete="off" spellcheck="false"
               placeholder="키·값 안에서 찾기">
        <button type="button" class="tagsearch-act" data-act="new">+ 키</button>
        <button type="button" class="tagsearch-act" data-act="group">+ 그룹</button>
      </div>
      <div class="tagsearch-body">
        <div class="tagsearch-left"><div class="tagsearch-list"></div></div>
        <div class="tagsearch-desc"></div>
      </div>`;
    doc.body.appendChild(popup);

    const input = popup.querySelector('.tagsearch-input');
    input.addEventListener('input', () => { query = input.value; renderList(); });
    input.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); close(); }
    });
    const groupSelect = popup.querySelector('.wcchunk-group');
    groupSelect.addEventListener('change', event => {
      const next = event.target.value || '';
      void leaveCurrent(() => {
        setModuleParam('instant_wildcard', 'select_file', next);
      }).then(() => {
        // 취소했으면 고르개를 원래 그룹으로 되돌린다 - 안 되돌리면 화면은 새 그룹인데
        // 목록은 옛 그룹이라 서로 다른 답이 보인다.
        if (dirty) groupSelect.value = currentFile();
      });
    });

    popup.addEventListener('click', event => {
      // ⚠️ 키 줄은 동작 버튼보다 **나중에** 본다 - 줄이 목록 전체를 덮고 있어서
      //    순서를 뒤집으면 위쪽 버튼이 먹히지 않는다.
      const act = event.target.closest('[data-act]');
      if (act) {
        const action = act.dataset.act;
        if (action === 'close') { void leaveCurrent(close); return; }
        if (action === 'new') { void leaveCurrent(newKey); return; }
        if (action === 'group') { void addGroup(); return; }
        if (action === 'save') { save(); return; }
        if (action === 'rename') { void rename(); return; }
        if (action === 'delete') { void removeKey(); return; }
        const group = currentGroup();
        const key = editedKey();
        const token = key ? `$${group}:${key}` : `$${group}`;
        if (action === 'copy') {
          win.navigator?.clipboard?.writeText(token)
            .then(() => showToast(`${token} 복사했습니다`, 'success'))
            .catch(() => showToast('복사하지 못했습니다', 'error'));
          return;
        }
        if (action === 'insert') {
          if (typeof onInsertText !== 'function') {
            showToast('프롬프트에 넣을 수 없습니다', 'error');
            return;
          }
          const ok = onInsertText(token);
          showToast(ok === false ? '프롬프트에 넣지 못했습니다' : `${token} 를 넣었습니다`,
                    ok === false ? 'error' : 'success');
        }
        return;
      }
      const row = event.target.closest('[data-key]');
      if (!row) return;
      // ⚠️ **`win.confirm` 을 쓰지 않는다.** Electron 에서 네이티브 창이 초점을 잠근다 -
      //    Memo 가 같은 이유로 주입받은 `confirmDialog` 만 쓴다. 여기도 그것을 쓴다.
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
    if (isOpen()) close();
    else open();
  }

  return {open, close, toggle, isOpen, onState};
}
