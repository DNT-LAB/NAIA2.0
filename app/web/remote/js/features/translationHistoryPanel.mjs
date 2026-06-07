// Translation History panel — Ollama 어시스트 팝업의 *우측에 도킹*되는 2단 플로팅 패널.
// 와일드카드 관리 모듈처럼 부모(.ollama-assistant-popup) 오른쪽에 바로 붙어 따라다닌다.
// 상단 = 고정(Pinned), 하단 = 기록(History). 각 행은 아코디언: 머리(한글 입력 + 등급/분량
// 배지 + 핀/삭제)를 누르면 펼쳐져 변환 결과(영문 태그)를 보여준다.
//
// 표시 대상 = 어시스트 **최종 결과**(태그 + 자연어 프롬프트). 백엔드가 중간 KR→EN 번역은
// 기록하지 않고 최종 결과만 context='ollama_assist'(effort/등급/모드 메타 포함)로 1건
// 남기므로, 패널은 그 context만 보여준다. 행 머리=한글 입력(미리보기), 펼치면 최종
// 프롬프트(태그+자연어). effort/등급 메타로 배지를 단다.
// 백엔드(/api/translation-history)가 진실의 원천: 목록(GET)은 모든 클라이언트에 열려
// 있고, 핀/삭제(POST/DELETE)는 호스트 로컬에서만 허용된다(원격이면 403 → 토스트).
//
// 표시/숨김은 팝업의 작은 [기록] 버튼이 토글한다(자동 등장·접힘 UI 없음).

const LIST_URL = '/api/translation-history';
// 어시스트 최종 결과만 표시 — 백엔드가 이 context로 최종 프롬프트를 남긴다.
const ASSIST_CONTEXT = 'ollama_assist';
const FETCH_LIMIT = 200;  // 혼합 컨텍스트에서 어시스트 결과만 추려도 충분하도록 넉넉히.
const _LEVEL_KR = {concise: '간결', standard: '표준', rich: '풍부', max: '최대'};

export function createTranslationHistoryPanel({
  document,
  window: win = window,
  showToast = () => {},
  escHtml = value => String(value ?? ''),
  onVisibilityChange = null,   // (visible:boolean) → 팝업이 [기록] 버튼 active 상태 동기화
} = {}) {
  let panel = null;
  let onResize = null;
  let loading = false;
  let lastQuery = '';
  let records = [];
  let pinned = [];
  let searchTimer = null;
  let visible = false;
  let reposTimer = null;   // Ollama 팝업 추종(열림/이동/최소화) 재배치

  function pick(selector) {
    return panel ? panel.querySelector(selector) : null;
  }

  function visibleRecords(arr) {
    return (Array.isArray(arr) ? arr : []).filter(
      r => String(r && r.context || '') === ASSIST_CONTEXT);
  }

  // ------------------------------------------------------------------
  // fetch 헬퍼 — ollama 패턴과 동일(응답 JSON 파싱 실패는 빈 객체로).
  // ------------------------------------------------------------------
  async function fetchJson(url, options) {
    const response = await win.fetch(url, options);
    let payload = null;
    try {
      payload = await response.json();
    } catch (error) {
      payload = null;
    }
    return {status: response.status, payload: payload || {}};
  }

  // ▶ Ollama 팝업의 sibling 위젯 — 그 *우측에 바로 붙인다*(와일드카드 관리 모듈처럼).
  function position() {
    if (!panel) return;
    const margin = 8;
    const ollama = document.querySelector('.ollama-assistant-popup');
    if (ollama && ollama.offsetWidth > 0 && ollama.style.display !== 'none'
        && !ollama.classList.contains('minimized')) {
      const r = ollama.getBoundingClientRect();
      const pw = panel.offsetWidth || 280;
      // 우측에 공간이 없으면 팝업 왼쪽에 붙인다(좁은 화면 보호).
      let left = r.right + margin;
      if (left + pw > win.innerWidth - margin) {
        left = Math.max(margin, r.left - margin - pw);
      }
      panel.style.left = `${Math.round(left)}px`;
      panel.style.top = `${Math.round(Math.max(margin, r.top))}px`;
      panel.style.right = 'auto';
      panel.style.bottom = 'auto';
      panel.style.maxHeight = `${Math.round(Math.max(200, win.innerHeight - r.top - margin))}px`;
      return;
    }
    // 폴백(팝업 없음/닫힘/최소화): 화면 우상단.
    panel.style.right = `${margin}px`;
    panel.style.top = `${margin}px`;
    panel.style.left = 'auto';
    panel.style.bottom = 'auto';
    panel.style.maxHeight = `${Math.round(win.innerHeight - 2 * margin)}px`;
  }

  function setStatus(text, type = '') {
    const status = pick('.xlation-history-status');
    if (!status) return;
    status.className = 'xlation-history-status' + (type ? ' ' + type : '');
    status.textContent = text || '';
  }

  function setCount(n) {
    const el = pick('.xlation-history-count');
    if (el) el.textContent = (n || n === 0) ? `(${n})` : '';
  }

  // ------------------------------------------------------------------
  // 한 레코드 = 아코디언 행. 머리: 한글 입력(미리보기) + 등급/분량 배지 + 핀/삭제.
  // 몸통(펼침): 변환 결과(영문 태그). 머리 클릭 → 토글, 몸통 클릭 → 결과 복사.
  // ------------------------------------------------------------------
  function timeLabel(ts) {
    const m = String(ts || '').match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
    return m ? `${m[2]}-${m[3]} ${m[4]}:${m[5]}` : String(ts || '');
  }

  function buildRow(rec, isPinned) {
    const meta = (rec && rec.meta) || {};
    const lvl = _LEVEL_KR[meta.level] || meta.level || '';
    const rt = String(meta.rating || '').toLowerCase();

    const row = document.createElement('div');
    row.className = 'xlation-history-row' + (isPinned ? ' pinned' : '');
    row.dataset.id = String(rec.id || '');

    // 머리(미리보기) — 항상 보임.
    const head = document.createElement('div');
    head.className = 'xlation-history-row-head';

    const src = document.createElement('div');
    src.className = 'xlation-history-src';
    src.title = String(rec.source || '');
    src.textContent = String(rec.source || '') || '(빈 입력)';

    const badges = document.createElement('span');
    badges.className = 'xlation-history-badges';
    if (rt) {
      const b = document.createElement('span');
      b.className = `xlation-history-rating r-${rt}`;
      b.textContent = rt.toUpperCase();
      badges.appendChild(b);
    }
    if (lvl) {
      const b = document.createElement('span');
      b.className = 'xlation-history-level';
      b.textContent = lvl;
      badges.appendChild(b);
    }

    const actions = document.createElement('div');
    actions.className = 'xlation-history-row-actions';
    const pinBtn = document.createElement('button');
    pinBtn.type = 'button';
    pinBtn.className = 'xlation-history-act pin' + (rec.pinned ? ' active' : '');
    pinBtn.title = rec.pinned ? '핀 해제' : '핀 고정';
    pinBtn.setAttribute('aria-pressed', rec.pinned ? 'true' : 'false');
    pinBtn.textContent = '★';
    pinBtn.addEventListener('click', (e) => { e.stopPropagation(); togglePin(rec); });
    const delBtn = document.createElement('button');
    delBtn.type = 'button';
    delBtn.className = 'xlation-history-act delete';
    delBtn.title = '삭제';
    delBtn.textContent = '✕';
    delBtn.addEventListener('click', (e) => { e.stopPropagation(); removeRecord(rec); });
    actions.appendChild(pinBtn);
    actions.appendChild(delBtn);

    head.appendChild(src);
    head.appendChild(badges);
    head.appendChild(actions);

    // 몸통(펼침) — 변환 결과(영문 태그).
    const body = document.createElement('div');
    body.className = 'xlation-history-row-body';
    const dst = document.createElement('div');
    dst.className = 'xlation-history-dst';
    dst.textContent = String(rec.translated || '') || '(결과 없음)';
    const foot = document.createElement('div');
    foot.className = 'xlation-history-meta';
    const ctxTime = timeLabel(rec.ts);
    foot.textContent = ctxTime ? `${ctxTime} · 클릭하면 복사` : '클릭하면 복사';
    body.appendChild(dst);
    body.appendChild(foot);
    body.addEventListener('click', (e) => {
      e.stopPropagation();
      copyText(String(rec.translated || ''), '변환 결과');
    });

    // 머리 클릭(액션 제외) → 펼침 토글.
    head.addEventListener('click', () => row.classList.toggle('expanded'));

    row.appendChild(head);
    row.appendChild(body);
    return row;
  }

  function renderList(container, items, isPinned, emptyText) {
    if (!container) return;
    container.textContent = '';
    if (!items || !items.length) {
      const empty = document.createElement('div');
      empty.className = 'xlation-history-empty';
      empty.textContent = emptyText;
      container.appendChild(empty);
      return;
    }
    const frag = document.createDocumentFragment();
    items.forEach(rec => frag.appendChild(buildRow(rec, isPinned)));
    container.appendChild(frag);
  }

  function render() {
    renderList(pick('.xlation-history-pinned-list'), pinned, true, '고정된 변환이 없습니다.');
    const pinnedIds = new Set((pinned || []).map(r => String(r.id)));
    const flat = (records || []).filter(r => !pinnedIds.has(String(r.id)));
    renderList(pick('.xlation-history-list'), flat, false,
      lastQuery ? '검색 결과가 없습니다.' : '변환 기록이 없습니다.');
    setCount(records ? records.length : 0);
    const pinnedSection = pick('.xlation-history-pinned');
    if (pinnedSection) pinnedSection.classList.toggle('empty', !(pinned && pinned.length));
  }

  // 데이터 로드(GET) — 검색어가 있으면 q 파라미터로 필터. 어시스트 컨텍스트만 추린다.
  async function refresh() {
    if (!panel || !visible || loading) return;
    loading = true;
    setStatus('불러오는 중…');
    const q = lastQuery ? `&q=${encodeURIComponent(lastQuery)}` : '';
    try {
      const {payload} = await fetchJson(`${LIST_URL}?limit=${FETCH_LIMIT}${q}`);
      if (!panel) return;
      if (payload && payload.ok !== false) {
        records = visibleRecords(payload.records);
        pinned = visibleRecords(payload.pinned);
        setStatus('');
      } else {
        records = [];
        pinned = [];
        setStatus(String(payload?.error || '기록을 불러오지 못했습니다.'), 'error');
      }
      render();
    } catch (error) {
      setStatus('백엔드 요청 실패', 'error');
    } finally {
      loading = false;
      position();
    }
  }

  // 핀 토글(POST) — 서버 동기화. 403(원격)이면 토스트.
  async function togglePin(rec) {
    const id = String(rec.id || '');
    if (!id) return;
    const want = !rec.pinned;
    try {
      const {status, payload} = await fetchJson(
        `${LIST_URL}/${encodeURIComponent(id)}/pin`,
        {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({pinned: want}),
        });
      if (status === 403) {
        showToast(payload.error || '핀은 NAIA가 실행 중인 PC에서만 가능합니다.', 'error');
        return;
      }
      if (!payload || payload.ok === false) {
        showToast(payload?.error || '핀 처리에 실패했습니다.', 'error');
        return;
      }
      showToast(want ? '핀 고정됨' : '핀 해제됨', 'success');
      refresh();
    } catch (error) {
      showToast('핀 요청 실패', 'error');
    }
  }

  // 삭제(DELETE) — 낙관적으로 행 제거 후 서버 동기화. 403(원격)이면 롤백.
  async function removeRecord(rec) {
    const id = String(rec.id || '');
    if (!id) return;
    records = (records || []).filter(r => String(r.id) !== id);
    pinned = (pinned || []).filter(r => String(r.id) !== id);
    render();
    try {
      const {status, payload} = await fetchJson(
        `${LIST_URL}/${encodeURIComponent(id)}`, {method: 'DELETE'});
      if (status === 403) {
        showToast(payload.error || '삭제는 NAIA가 실행 중인 PC에서만 가능합니다.', 'error');
        refresh();
        return;
      }
      if (!payload || payload.ok === false) {
        refresh();
        return;
      }
      showToast('삭제됨', 'success');
      refresh();
    } catch (error) {
      showToast('삭제 요청 실패', 'error');
      refresh();
    }
  }

  async function copyText(text, label) {
    const value = String(text || '');
    if (!value) return;
    try {
      if (!win.navigator?.clipboard?.writeText) throw new Error('Clipboard API unavailable');
      await win.navigator.clipboard.writeText(value);
      showToast(`${label} 복사됨`, 'success');
    } catch (error) {
      showToast('클립보드 복사 실패', 'error');
    }
  }

  function onSearchInput(value) {
    lastQuery = String(value || '').trim();
    if (searchTimer) win.clearTimeout(searchTimer);
    searchTimer = win.setTimeout(() => refresh(), 220);
  }

  function build() {
    panel = document.createElement('div');
    panel.className = 'xlation-history-panel';
    panel.innerHTML = `
      <div class="xlation-history-header">
        <span class="xlation-history-title">변환 기록 <span class="xlation-history-count"></span></span>
        <button type="button" class="xlation-history-refresh" aria-label="새로고침" title="새로고침">⟳</button>
        <button type="button" class="xlation-history-close" aria-label="닫기" title="닫기">&times;</button>
      </div>
      <div class="xlation-history-body">
        <div class="xlation-history-search-row">
          <input type="text" class="xlation-history-search" placeholder="기록 검색 (한글/영문)" autocomplete="off" spellcheck="false">
        </div>
        <section class="xlation-history-pinned empty" aria-label="고정된 변환">
          <div class="xlation-history-section-label">고정됨</div>
          <div class="xlation-history-pinned-list xlation-history-scroll"></div>
        </section>
        <section class="xlation-history-section" aria-label="변환 기록">
          <div class="xlation-history-section-label">기록</div>
          <div class="xlation-history-list xlation-history-scroll"></div>
        </section>
        <div class="xlation-history-status"></div>
      </div>`;
    document.body.appendChild(panel);

    pick('.xlation-history-refresh')?.addEventListener('click', () => refresh());
    pick('.xlation-history-close')?.addEventListener('click', () => setVisible(false));
    const search = pick('.xlation-history-search');
    if (search) search.addEventListener('input', () => onSearchInput(search.value));

    onResize = () => position();
    win.addEventListener('resize', onResize);
    win.requestAnimationFrame(() => position());
    win.setTimeout(() => position(), 120);
  }

  function setVisible(next) {
    const want = !!next;
    if (want === visible && panel) { if (want) position(); return visible; }
    visible = want;
    if (reposTimer) { win.clearInterval(reposTimer); reposTimer = null; }
    if (!visible) {
      if (panel) panel.style.display = 'none';
      if (typeof onVisibilityChange === 'function') onVisibilityChange(false);
      return visible;
    }
    if (!panel) build();
    panel.style.display = '';
    position();
    refresh();
    reposTimer = win.setInterval(position, 500);  // 팝업 추종.
    if (typeof onVisibilityChange === 'function') onVisibilityChange(true);
    return visible;
  }

  function toggle() { return setVisible(!visible); }
  function isVisible() { return visible; }
  function open() { return setVisible(true); }
  function close() { return setVisible(false); }

  function destroy() {
    if (onResize) { win.removeEventListener('resize', onResize); onResize = null; }
    if (searchTimer) { win.clearTimeout(searchTimer); searchTimer = null; }
    if (reposTimer) { win.clearInterval(reposTimer); reposTimer = null; }
    if (panel) { panel.remove(); panel = null; }
    visible = false;
  }

  return {open, close, toggle, isVisible, setVisible, refresh, position, destroy};
}
