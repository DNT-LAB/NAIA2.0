/** Tag Search — 태그 이름 **부분 매칭**으로 필요한 태그를 찾는 창.
 *
 *  자동완성은 속도 때문에 접두사만 본다(`search_autocomplete` 가
 *  `scan_substrings=False`). 그래서 `utsusumi kio` 의 뒷부분(`kio`)만 기억나면
 *  찾을 길이 없었다 — 이 창이 채우는 구멍이 정확히 그것이다(사용자 지정).
 *
 *  배치(사용자 모형):
 *
 *      ┌──────────────────────────────────────┐
 *      │  검색 (lazy)                          │
 *      ├───────────────┬──────────────────────┤
 *      │ ALL Char Art  │                      │
 *      │ Gen           │   태그 설명           │
 *      ├───────────────┤                      │
 *      │   태그 목록    │                      │
 *      └───────────────┴──────────────────────┘
 *
 *  ⚠️ 백엔드는 **기존 `tag_search` 커맨드를 재사용**한다. 새 메시지 타입을 만들면
 *     웹 스모크 계약이 타입을 순서대로 세기 때문에 이후 전부가 밀린다.
 *     그 커맨드는 `#tagSearchBar`(display:none, "reserved for future")만 쓰던
 *     사실상 죽은 경로였다.
 */
export function createTagSearchPopup({
  document,
  window: win = window,
  escHtml = value => String(value ?? ''),
  showToast = () => {},
  getWs = () => null,
  onInsertTag = null,
  setTimeoutFn = globalThis.setTimeout,
  clearTimeoutFn = globalThis.clearTimeout,
}) {
  // 사용자의 **마지막 입력을 예측해 약간 느리게** 친다(사용자 지정: lazy search).
  // 한 글자마다 19만 태그를 훑으면(질의당 30~50ms 실측) 타이핑이 끈적해진다.
  const DEBOUNCE_MS = 260;
  // 한글 입력은 조합 중에 자모가 튄다 — 조합이 끝나고 조금 더 기다린다.
  const IME_SETTLE_MS = 120;
  const TABS = [
    {key: 'all', label: 'ALL'},
    {key: 'character', label: 'Character'},
    {key: 'artist', label: 'Artists'},
    {key: 'general', label: 'General'},
  ];
  const CAT_COLORS = {
    artist: '#d4736a', copyright: '#a87fd4', character: '#6abf7b', e621: '#d4c36a',
  };

  let popup = null;
  let timer = null;
  let composing = false;
  let onResize = null;
  let activeTab = 'all';
  let rows = [];
  let selectedTag = '';
  let lastQuery = '';
  let pendingQuery = '';
  // 같은 질의에 번역을 두 번 청하지 않는다 - 버튼이 되풀이되면 사용자가 계속 누른다.
  let triedTranslate = false;

  const pick = selector => (popup ? popup.querySelector(selector) : null);

  function isOpen() {
    return !!popup && popup.style.display !== 'none';
  }

  function close() {
    if (timer) { clearTimeoutFn(timer); timer = null; }
    if (onResize) { win.removeEventListener('resize', onResize); onResize = null; }
    if (popup) popup.style.display = 'none';
  }

  function fmtCount(n) {
    const v = Number(n) || 0;
    if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
    if (v >= 1e3) return `${Math.round(v / 1e3)}k`;
    return String(v);
  }

  function setStatus(text, tone = '') {
    const el = pick('.tagsearch-status');
    if (!el) return;
    el.className = 'tagsearch-status' + (tone ? ` ${tone}` : '');
    el.textContent = text || '';
  }

  // ── 목록 ──────────────────────────────────────────────────────────────
  function renderList() {
    const list = pick('.tagsearch-list');
    if (!list) return;
    if (!rows.length) {
      const q = String(pick('.tagsearch-input')?.value || '').trim();
      if (!q) {
        list.innerHTML = `<div class="tagsearch-empty">${escHtml('태그의 일부를 입력하세요')}</div>`;
        return;
      }
      // 한글로 찾아 0건이면 **번역해서 다시 찾기**를 내민다(사용자 제안).
      // ⚠️ 자동으로 하지 않는다 - 번역기가 네트워크라 질의당 0.8초를 문다(실측).
      //    누를 때만 물면 흔한 경우가 안 느려지고, 오프라인이면 멈춤 대신
      //    "번역하지 못했습니다" 로 끝난다.
      const offer = /[가-힣ㄱ-ㅎㅏ-ㅣ]/.test(q) && !triedTranslate;
      list.innerHTML = `<div class="tagsearch-empty">${escHtml('결과가 없습니다')}${
        offer
          ? `<br><button type="button" class="tagsearch-act tagsearch-retry"
                data-act="translate">번역해서 다시 찾기</button>`
          : ''
      }</div>`;
      return;
    }
    list.innerHTML = rows.map((row, index) => {
      const cat = String(row.cat || '');
      const style = CAT_COLORS[cat] ? ` style="color:${CAT_COLORS[cat]}"` : '';
      const on = row.tag === selectedTag ? ' is-active' : '';
      return `<button type="button" class="tagsearch-item${on}" data-index="${index}" title="${escHtml(row.tag)}">
        <span class="tagsearch-item-tag"${style}>${escHtml(row.tag)}</span>
        <b class="tagsearch-item-count">${escHtml(fmtCount(row.count))}</b>
      </button>`;
    }).join('');
  }

  function renderDesc() {
    const box = pick('.tagsearch-desc');
    if (!box) return;
    const row = rows.find(item => item.tag === selectedTag);
    if (!row) {
      box.innerHTML = `<div class="tagsearch-empty">${escHtml('왼쪽에서 태그를 고르세요')}</div>`;
      return;
    }
    const cat = String(row.cat || '');
    const style = CAT_COLORS[cat] ? ` style="color:${CAT_COLORS[cat]}"` : '';
    const keywords = Array.isArray(row.keywords) ? row.keywords.filter(Boolean) : [];
    box.innerHTML = `
      <div class="tagsearch-desc-head">
        <div class="tagsearch-desc-tag"${style}>${escHtml(row.tag)}</div>
        <div class="tagsearch-desc-meta">
          ${cat ? `<span class="tagsearch-chip"${style}>${escHtml(cat)}</span>` : ''}
          ${row.group ? `<span class="tagsearch-chip">${escHtml(row.group)}</span>` : ''}
          <span class="tagsearch-chip">${escHtml(fmtCount(row.count))}</span>
        </div>
      </div>
      ${row.desc ? `<p class="tagsearch-desc-body">${escHtml(row.desc)}</p>` : ''}
      ${keywords.length ? `<div class="tagsearch-desc-kw">${
        keywords.map(k => `<span class="tagsearch-kw">${escHtml(k)}</span>`).join('')
      }</div>` : ''}
      <div class="tagsearch-desc-actions">
        <button type="button" class="tagsearch-act" data-act="insert">프롬프트에 추가</button>
        <button type="button" class="tagsearch-act" data-act="copy">복사</button>
      </div>
    `;
  }

  function selectIndex(index) {
    const row = rows[index];
    if (!row) return;
    selectedTag = row.tag;
    renderList();
    renderDesc();
  }

  // ── 검색 ──────────────────────────────────────────────────────────────
  function send(query, {translate = false} = {}) {
    const ws = getWs();
    if (!ws || ws.readyState !== 1) {
      setStatus('연결이 끊겼습니다', 'warn');
      return;
    }
    // 백엔드가 부분 매칭을 켜고 **빈도순**으로 세운다 — 그래야 이름 일부만
    // 기억나는 상황에서 유명한 것부터 보인다(실측: `kio` 로 utsusumi kio 5위).
    ws.send(JSON.stringify({type: 'tag_search', query, tab: activeTab, limit: 200, translate}));
    pendingQuery = query;
    if (translate) triedTranslate = true;
    setStatus(translate ? '번역해서 찾는 중...' : '검색 중...', 'busy');
  }

  function schedule({immediate = false} = {}) {
    if (timer) { clearTimeoutFn(timer); timer = null; }
    const input = pick('.tagsearch-input');
    const query = String(input?.value || '').trim();
    if (!query) {
      rows = [];
      selectedTag = '';
      lastQuery = '';
      renderList();
      renderDesc();
      setStatus('');
      return;
    }
    // ⚠️ 조합 중에는 보내지 않는다 — 한글 자모가 튀어 헛질의가 쌓인다.
    if (composing) return;
    if (query !== lastQuery) triedTranslate = false;
    const wait = immediate ? 0 : (DEBOUNCE_MS);
    timer = setTimeoutFn(() => { timer = null; send(query); }, wait);
  }

  /** 백엔드 응답. app.js 의 `tag_search_result` 라우터가 넘겨준다. */
  function onResult(message) {
    if (!isOpen()) return false;
    const query = String(message?.query || '');
    // 늦게 도착한 옛 질의 응답이 새 결과를 덮지 않게 한다.
    if (pendingQuery && query !== pendingQuery) return true;
    // 탭이 그새 바뀌었으면 버린다(탭 전환은 곧바로 새 질의를 낸다).
    if (message?.tab && String(message.tab) !== activeTab) return true;
    rows = Array.isArray(message?.results) ? message.results : [];
    lastQuery = query;
    if (!rows.some(row => row.tag === selectedTag)) selectedTag = rows[0]?.tag || '';
    renderList();
    renderDesc();
    // 한글이 안 걸려 번역으로 다시 찾았으면 **그렇다고 말한다** — 안 그러면 왜 다른
    // 말의 결과가 나오는지 알 수 없다(사용자 제안으로 넣은 폴백).
    const translated = String(message?.translated || '').trim();
    if (!rows.length) {
      setStatus(triedTranslate ? '번역해도 결과가 없습니다' : '결과 없음', 'warn');
    }
    else if (translated) setStatus(`${translated} → ${rows.length}개`, 'warn');
    else setStatus(`${rows.length}개`, 'ok');
    return true;
  }

  function setTab(next) {
    const key = TABS.some(tab => tab.key === next) ? next : 'all';
    if (key === activeTab) return;
    activeTab = key;
    popup?.querySelectorAll('[data-tab]').forEach(btn => {
      btn.classList.toggle('is-active', btn.dataset.tab === activeTab);
    });
    schedule({immediate: true});
  }

  // ── 위치 ──────────────────────────────────────────────────────────────
  /** Result 탭 이미지 영역의 **좌측 하단**에 붙인다(사용자 지정).
   *
   *  ⚠️ 처음에는 런처 버튼 아래에 뒀는데, 그 버튼이 왼쪽 패널 아래쪽이라 창이
   *     프롬프트 편집기를 통째로 덮었다. 결과 이미지 옆이 비어 있는 자리이고,
   *     찾은 태그를 프롬프트에 넣는 동안 프롬프트가 보여야 한다.
   *  ⚠️ 그 영역을 못 찾으면(모바일·좁은 화면) 화면 좌하단으로 물러선다 —
   *     그때는 어차피 겹칠 수밖에 없다.
   */
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

  function build() {
    popup = document.createElement('div');
    popup.className = 'tagsearch-popup';
    popup.innerHTML = `
      <div class="tagsearch-head">
        <span class="tagsearch-title">Tag Search</span>
        <span class="tagsearch-status"></span>
        <button type="button" class="tagsearch-x" data-act="close" aria-label="닫기">&times;</button>
      </div>
      <div class="tagsearch-searchrow">
        <input class="tagsearch-input" type="search" autocomplete="off" spellcheck="false"
               placeholder="태그의 일부를 입력하세요 (예: kio → utsusumi kio)">
      </div>
      <div class="tagsearch-body">
        <div class="tagsearch-left">
          <div class="tagsearch-tabs" role="tablist">
            ${TABS.map(tab => `<button type="button" class="tagsearch-tab${
              tab.key === activeTab ? ' is-active' : ''
            }" data-tab="${tab.key}" role="tab">${escHtml(tab.label)}</button>`).join('')}
          </div>
          <div class="tagsearch-list"></div>
        </div>
        <div class="tagsearch-desc"></div>
      </div>
    `;
    document.body.appendChild(popup);

    const input = pick('.tagsearch-input');
    input.addEventListener('input', () => schedule());
    input.addEventListener('compositionstart', () => { composing = true; });
    input.addEventListener('compositionend', () => {
      composing = false;
      // 조합이 막 끝난 값이 아직 input.value 에 안 반영된 브라우저가 있다 —
      // 한 틱 뒤에 읽는다.
      setTimeoutFn(() => schedule(), IME_SETTLE_MS);
    });
    input.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); close(); return; }
      if (event.key === 'Enter' && !event.isComposing) {
        event.preventDefault();
        schedule({immediate: true});
      }
    });

    popup.addEventListener('click', event => {
      const tab = event.target.closest('[data-tab]');
      if (tab) { setTab(tab.dataset.tab); return; }
      const item = event.target.closest('.tagsearch-item');
      if (item) { selectIndex(Number(item.dataset.index)); return; }
      const act = event.target.closest('[data-act]');
      if (!act) return;
      const action = act.dataset.act;
      if (action === 'close') { close(); return; }
      if (action === 'translate') {
        const q = String(pick('.tagsearch-input')?.value || '').trim();
        if (q) send(q, {translate: true});
        return;
      }
      if (!selectedTag) return;
      if (action === 'copy') {
        win.navigator?.clipboard?.writeText(selectedTag)
          .then(() => showToast(`복사했습니다: ${selectedTag}`, 'success'))
          .catch(() => showToast('복사하지 못했습니다', 'error'));
        return;
      }
      if (action === 'insert') {
        if (typeof onInsertTag !== 'function') {
          showToast('프롬프트에 추가할 수 없습니다', 'error');
          return;
        }
        const ok = onInsertTag(selectedTag);
        showToast(ok === false ? '프롬프트에 추가하지 못했습니다' : `추가했습니다: ${selectedTag}`,
                  ok === false ? 'error' : 'success');
      }
    });
    // 항목을 두 번 누르면 바로 넣는다 — 설명을 읽을 필요가 없을 때가 많다.
    popup.addEventListener('dblclick', event => {
      const item = event.target.closest('.tagsearch-item');
      if (!item || typeof onInsertTag !== 'function') return;
      const row = rows[Number(item.dataset.index)];
      if (!row) return;
      const ok = onInsertTag(row.tag);
      if (ok !== false) showToast(`추가했습니다: ${row.tag}`, 'success');
    });
  }

  function open() {
    if (!popup) build();
    popup.style.display = 'flex';
    renderList();
    renderDesc();
    onResize = () => position();
    win.addEventListener('resize', onResize);
    position();
    win.requestAnimationFrame(() => {
      position();
      pick('.tagsearch-input')?.focus();
    });
  }

  return {open, close, isOpen, onResult};
}
