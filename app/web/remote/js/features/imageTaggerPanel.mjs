/** Image Tagger — 이미지를 넣으면 태그를 뽑아 프롬프트로 옮기는 임시 창.
 *
 *  사용자 지정 2026-08-31 (2차):
 *    "왼쪽 공간 : 이번 세션에서 업로드한 이미지들을 나열합니다. 오른쪽 공간 :
 *     프롬프트 공간이며 나열 방식을 메모처럼 그냥 단일 텍스트 공간으로 처리합니다.
 *     1. 먼저 Full Prompt 나열 2. 캐릭터가 있으면 그다음 #추정 캐릭터: 표시
 *     3. 이후로 구간별로 나열하고, #로 기입되는 주석형 컨텐츠들은 전부 연노랑색
 *     하이라이팅 처리합니다. ... Batch 업로드 지원하며, 여러 이미지를 올리는 경우
 *     하나 반환이 완료되면 2초 후에 다음 요청을 보냅니다. 요청 중인 item들은
 *     [In Queue X] 라벨이 붙고, 언제든지 X 버튼을 눌러 취소할 수 있도록 합니다.
 *     ... _ 를 누르면 최소화되어 Recent, Scene이 있는 자리에 [ Tagger (10) X ]"
 *
 *      ┌──────────────────────────────────────────────┐
 *      │ Image Tagger  태그48개·5초   [캐릭터▾][_][×] │
 *      │ [ 웹에서 사용 : huggingface.co/... ]          │
 *      ├────────────────┬─────────────────────────────┤
 *      │ 이번 세션 업로드 │ <full prompt>               │
 *      │ ▣ a.png        │                             │
 *      │ ▣ b.png [In Q ×]│ #추정 캐릭터:                │
 *      │ ▣ c.png [In Q ×]│ hatsune miku                │
 *      │                │                             │
 *      │  + 이미지 추가   │ #특징:                       │
 *      │  (끌어다 놓기)   │ long hair, ...              │
 *      ├────────────────┴─────────────────────────────┤
 *      │                        [메인][캐릭터][복사]    │
 *      └──────────────────────────────────────────────┘
 *
 *  ⚠️ **임시 창이다.** 어디에도 저장하지 않는다 — 새로고침하면 사라진다.
 */
const NL = String.fromCharCode(10);

/** 결과를 오른쪽 텍스트 한 덩어리로 조립한다 (사용자 지정 순서).
 *
 *   1) Full Prompt  2) 캐릭터가 있으면 `#추정 캐릭터:`  3) 이후 구간별
 *
 *  NAIA 메인 프롬프트가 쓰는 모양과 같다(본문 -> 빈 줄 -> `#분류:` 블록).
 *  그래야 여기서 옮긴 것이 프롬프트 창에서 그대로 읽힌다.
 *
 *  ⚠️ 창 바깥으로 꺼내 둔 이유는 **시험에서 진짜로 실행**하기 위해서다 -
 *     클로저 안에 두면 문자열 대조밖에 할 수 없다.
 */
export function composeTaggerText(result) {
  if (!result) return '';
  const parts = [String(result.tag_string || '').trim()];
  const characters = (result.character || []).map(row => row && row.tag).filter(Boolean);
  if (characters.length) {
    // WD14 의 확신도는 낮을 수 있어 '추정' 이라고 못 박는다.
    parts.push(`#추정 캐릭터:${NL}${characters.join(', ')}`);
  }
  (result.categories || []).forEach(group => {
    const tags = (group.tags || []).filter(Boolean);
    if (!tags.length) return;
    parts.push(`${group.marker || group.label}${NL}${tags.join(', ')}`);
  });
  return parts.filter(Boolean).join(NL + NL);
}

/** `#` 으로 시작하는 줄만 감싼다 — 거울(하이라이팅)이 쓰는 순수 부분. */
export function highlightComments(text, escape) {
  return String(text || '').split(NL).map(line =>
    line.trimStart().startsWith('#')
      ? `<span class="imgtag-cmt">${escape(line)}</span>`
      : escape(line)
  ).join(NL) + NL;   // 마지막 줄바꿈이 없으면 거울이 한 줄 짧아진다
}

export function createImageTaggerResultPanel({
  document,
  window: win = window,
  escHtml = value => String(value ?? ''),
  showToast = () => {},
  onInsertMain = null,          // (text) -> bool
  onInsertCharacter = null,     // (index, text) -> bool
  getCharacters = () => [],
  analyze = null,               // (blob) -> Promise<result>
  setTimeoutFn = (fn, ms) => win.setTimeout(fn, ms),
  clearTimeoutFn = id => win.clearTimeout(id),
}) {
  // 사용자 지정: "하나 반환이 완료되면 2초 후에 다음 요청을 보냅니다."
  const QUEUE_GAP_MS = 2000;
  const MAX_ITEMS = 40;         // 세션 목록 상한 - 미리보기 blob 이 쌓인다

  let popup = null;
  let chip = null;              // 최소화했을 때 뜨는 [ Tagger (N) × ]
  let minimized = false;
  let notice = '';
  let spaceUrl = '';
  /** 이번 세션에 올린 것들. {id, name, url, blob, state, result, error} */
  let items = [];
  let activeId = null;
  let seq = 0;
  let pumping = false;
  let gapTimer = null;
  /** 오른쪽 텍스트의 편집분. 항목마다 따로 들고 있는다(다른 이미지의 태그다). */
  const drafts = new Map();

  const pick = selector => (popup ? popup.querySelector(selector) : null);
  const byId = id => items.find(item => item.id === id) || null;

  function isOpen() {
    return !!popup && popup.style.display !== 'none';
  }

  function queueLength() {
    return items.filter(item => item.state === 'queued' || item.state === 'running').length;
  }

  const composeText = composeTaggerText;

  function currentText() {
    const area = pick('.imgtag-area');
    if (area) return area.value;
    const item = byId(activeId);
    if (!item) return '';
    return drafts.has(item.id) ? drafts.get(item.id) : composeText(item.result);
  }

  // ── 주석 하이라이팅 ──────────────────────────────────────────
  /** `#` 으로 시작하는 줄을 연노랑으로 칠한다.
   *
   *  ⚠️ textarea 안은 칠할 수 없다. 뒤에 **같은 글꼴·같은 여백**의 거울을 깔고
   *     textarea 의 글자를 투명하게 만든다(프롬프트 창이 쓰는 그 방식).
   *     둘의 여백이 어긋나면 글자가 겹쳐 보이므로 CSS 를 한 곳에 묶어 뒀다
   *     (`.imgtag-area`, `.imgtag-mirror` 가 같은 값을 쓴다).
   */
  function paintMirror() {
    const mirror = pick('.imgtag-mirror');
    const area = pick('.imgtag-area');
    if (!mirror || !area) return;
    mirror.innerHTML = highlightComments(area.value, escHtml);
    mirror.scrollTop = area.scrollTop;
    mirror.scrollLeft = area.scrollLeft;
  }

  // ── 큐 ──────────────────────────────────────────────────────
  function addFiles(files) {
    const incoming = Array.from(files || []).filter(file => /^image\//.test(file.type || ''));
    if (!incoming.length) { showToast('이미지 파일이 아닙니다.', 'error'); return; }
    incoming.forEach(file => {
      if (items.length >= MAX_ITEMS) return;
      seq += 1;
      items.push({
        id: `it${seq}`,
        name: file.name || `image ${seq}`,
        url: win.URL.createObjectURL(file),
        blob: file,
        state: 'queued',
        result: null,
        error: '',
      });
    });
    render();
    pump();
  }

  /** 한 번에 하나만 보낸다. 끝나면 2초 쉬고 다음(사용자 지정). */
  async function pump() {
    if (pumping) return;
    pumping = true;
    try {
      while (true) {
        const next = items.find(item => item.state === 'queued');
        if (!next) break;
        next.state = 'running';
        render();
        try {
          const result = await analyze(next.blob);
          // 도는 동안 사용자가 취소했으면 **결과만 버린다**(상태는 그대로 둔다).
          // ⚠️ 예전에는 여기서 `continue` 했는데, 그러면 아래 2초 간격을 건너뛰어
          //    다음 요청이 즉시 나갔다(Codex CONCERN). 남의 서버에 대한 간격은
          //    이쪽 사정(취소)과 무관하다.
          if (next.state === 'running') {
            next.state = 'done';
            next.result = result;
            // 방금 끝난 것을 보여 준다 - 기다린 사람이 보고 싶은 것은 그것이다.
            activeId = next.id;
          }
        } catch (error) {
          if (next.state === 'running') {
            next.state = 'error';
            next.error = String(error && error.message ? error.message : error);
            showToast(next.error, 'error');
          }
        }
        render();
        if (!items.some(item => item.state === 'queued')) break;
        await new Promise(resolve => { gapTimer = setTimeoutFn(resolve, QUEUE_GAP_MS); });
        gapTimer = null;
      }
    } finally {
      pumping = false;
      render();
    }
  }

  function cancel(id) {
    const item = byId(id);
    if (!item) return;
    if (item.state === 'queued' || item.state === 'running') {
      // 이미 날아간 요청을 되돌릴 수는 없다 - 결과를 **버린다**고 표시할 뿐이다.
      item.state = 'cancelled';
      render();
      return;
    }
    // 끝난 항목의 × 는 목록에서 지우기다.
    try { win.URL.revokeObjectURL(item.url); } catch (error) { /* 무해 */ }
    drafts.delete(item.id);
    items = items.filter(row => row.id !== item.id);
    if (activeId === item.id) {
      const done = items.filter(row => row.state === 'done');
      activeId = done.length ? done[done.length - 1].id : null;
    }
    render();
  }

  // ── 프롬프트로 보내기 ─────────────────────────────────────────
  function send(where) {
    const text = currentText().trim();
    if (!text) { showToast('보낼 내용이 없습니다.', 'warning'); return; }
    if (where === 'main') {
      const ok = typeof onInsertMain === 'function' && onInsertMain(text);
      showToast(ok === false ? '메인 프롬프트에 넣지 못했습니다.' : '메인 프롬프트에 넣었습니다.',
                ok === false ? 'error' : 'success');
      return;
    }
    const characters = getCharacters() || [];
    if (!characters.length) { showToast('활성화된 캐릭터가 없습니다.', 'warning'); return; }
    const select = pick('.imgtag-target');
    const index = select ? Number(select.value) || 0 : 0;
    const ok = typeof onInsertCharacter === 'function' && onInsertCharacter(index, text);
    showToast(ok === false ? '캐릭터 프롬프트에 넣지 못했습니다.' : `캐릭터 ${index + 1} 에 넣었습니다.`,
              ok === false ? 'error' : 'success');
  }

  async function copy() {
    const text = currentText().trim();
    if (!text) return;
    try {
      await win.navigator.clipboard.writeText(text);
      showToast('복사했습니다.', 'success');
    } catch (error) {
      showToast('복사하지 못했습니다.', 'error');
    }
  }

  // ── 최소화 칩 ────────────────────────────────────────────────
  /** Interactive 의 Recent/Scene 과 **같은 자리**에 뜬다(사용자 지정).
   *  그 패널은 Interactive 가 꺼지면 사라지므로 자리만 빌리고 물건은 따로 둔다.
   */
  function ensureChip() {
    if (chip && document.body.contains(chip)) return chip;
    chip = document.createElement('div');
    chip.className = 'imgtag-chip-float';
    (document.querySelector('.viewer-wrapper') || document.body).appendChild(chip);
    chip.addEventListener('click', event => {
      if (event.target.closest('[data-chip="close"]')) { closeAll(); return; }
      if (event.target.closest('[data-chip="open"]')) { restore(); }
    });
    return chip;
  }

  function renderChip() {
    const host = ensureChip();
    if (!minimized) { host.classList.remove('open'); host.innerHTML = ''; return; }
    const n = queueLength();
    host.innerHTML = `
      <button type="button" class="imgtag-chip-btn" data-chip="open">
        <span>Tagger</span>${n ? `<span class="imgtag-chip-count">${n}</span>` : ''}
      </button>
      <button type="button" class="imgtag-chip-btn is-x" data-chip="close" aria-label="닫기">×</button>`;
    host.classList.add('open');
    positionChip();
  }

  function positionChip() {
    if (!chip || !minimized) return;
    const stage = document.querySelector('.viewer-wrapper');
    const info = document.querySelector('.result-info-panel');
    if (!stage) return;
    const box = stage.getBoundingClientRect();
    // 결과 정보 패널 **위**에 앉힌다.
    const bottom = info ? win.innerHeight - info.getBoundingClientRect().top + 8 : 56;
    // ⚠️ **오른쪽**에 붙인다. 왼쪽 구석에는 이미 다른 플로트가 있어 글자가 겹쳤다
    //    (사용자 지적 2026-08-31). 창 본체도 오른쪽이라 손이 한 곳에 머문다.
    chip.style.right = `${Math.round(win.innerWidth - box.right + 12)}px`;
    chip.style.left = 'auto';
    chip.style.bottom = `${Math.round(bottom)}px`;
  }

  function minimize() {
    minimized = true;
    if (popup) popup.style.display = 'none';
    renderChip();
  }

  function restore() {
    minimized = false;
    renderChip();
    if (!popup) build();
    popup.style.display = '';
    render();
  }

  function closeAll() {
    // 닫아 놓고 최대 2초 뒤 깨어나 다시 그리던 타이머를 놓는다.
    if (gapTimer) { clearTimeoutFn(gapTimer); gapTimer = null; }
    minimized = false;
    if (chip) { chip.classList.remove('open'); chip.innerHTML = ''; }
    if (popup) popup.style.display = 'none';
  }

  // ── 그리기 ───────────────────────────────────────────────────
  /** 상태 표시. 아이콘만 남기기로 했으므로 **글자 대신 배지**로 얹는다.
   *  ⚠️ 대기·진행 중인 것은 취소(×)가 반드시 닿아야 한다 - 사용자 지정이다.
   */
  function stateBadge(item) {
    if (item.state === 'queued' || item.state === 'running') {
      return `<span class="imgtag-dot is-q" title="In Queue"></span>
        <button type="button" class="imgtag-x-mini" data-cancel="${escHtml(item.id)}"
          aria-label="취소" title="취소">×</button>`;
    }
    if (item.state === 'error' || item.state === 'cancelled') {
      const tone = item.state === 'error' ? 'is-err' : 'is-off';
      const label = item.state === 'error' ? '실패' : '취소됨';
      return `<span class="imgtag-dot ${tone}" title="${label}"></span>
        <button type="button" class="imgtag-x-mini" data-cancel="${escHtml(item.id)}"
          aria-label="목록에서 지우기" title="목록에서 지우기">×</button>`;
    }
    return `<button type="button" class="imgtag-x-mini is-solo" data-cancel="${escHtml(item.id)}"
      aria-label="목록에서 지우기" title="목록에서 지우기">×</button>`;
  }

  function renderTargets() {
    const select = pick('.imgtag-target');
    if (!select) return;
    const characters = getCharacters() || [];
    const keep = select.value;
    select.innerHTML = characters.length
      ? characters.map((character, index) => {
          const name = String(character?.custom_name || '').trim();
          return `<option value="${index}">캐릭터 ${index + 1}${name ? ` · ${escHtml(name)}` : ''}</option>`;
        }).join('')
      : '<option value="0">캐릭터 없음</option>';
    if (keep && select.querySelector(`option[value="${keep}"]`)) select.value = keep;
    select.disabled = !characters.length;
  }

  function render() {
    if (!popup || !pick('.imgtag-list')) { renderChip(); return; }
    renderTargets();

    const link = pick('.imgtag-notice');
    link.innerHTML = notice && spaceUrl
      ? `[ ${escHtml(notice)} : <a href="${escHtml(spaceUrl)}" target="_blank" rel="noopener noreferrer">${escHtml(spaceUrl)}</a> ]`
      : '';

    // 사용자 지정 2026-08-31: 파일 이름 없이 **아이콘만**. 이름은 툴팁으로 남긴다.
    pick('.imgtag-list').innerHTML = items.length
      ? items.map(item => `
        <button type="button" class="imgtag-item${item.id === activeId ? ' is-active' : ''}"
                data-open="${escHtml(item.id)}" title="${escHtml(item.name)}">
          <img class="imgtag-thumb" src="${escHtml(item.url)}" alt="${escHtml(item.name)}">
          ${stateBadge(item)}
        </button>`).join('')
      : '<div class="imgtag-empty">비어 있음</div>';

    const active = byId(activeId);
    const area = pick('.imgtag-area');
    const text = active
      ? (drafts.has(active.id) ? drafts.get(active.id) : composeText(active.result))
      : '';
    if (area.value !== text) area.value = text;
    area.disabled = !active || active.state !== 'done';
    paintMirror();

    const status = pick('.imgtag-status');
    const waiting = queueLength();
    if (waiting) {
      status.textContent = `대기 ${waiting}건`;
      status.className = 'imgtag-status busy';
    } else if (active && active.result) {
      const seconds = Math.round((active.result.elapsed_ms || 0) / 100) / 10;
      const count = (active.result.general || []).length + (active.result.character || []).length;
      status.textContent = `태그 ${count}개 · ${seconds}초`;
      status.className = 'imgtag-status ok';
    } else {
      status.textContent = '';
      status.className = 'imgtag-status';
    }
    renderChip();
  }

  function build() {
    popup = document.createElement('div');
    popup.className = 'imgtag-popup';
    popup.innerHTML = `
      <div class="imgtag-head">
        <span class="imgtag-title">Image Tagger</span>
        <span class="imgtag-status"></span>
        <select class="imgtag-target" aria-label="캐릭터 대상"></select>
        <button type="button" class="imgtag-x" data-act="min" aria-label="최소화">_</button>
        <button type="button" class="imgtag-x" data-act="close" aria-label="닫기">&times;</button>
      </div>
      <div class="imgtag-notice"></div>
      <div class="imgtag-body">
        <div class="imgtag-left">
          <div class="imgtag-left-head" title="이번 세션에 올린 이미지">업로드</div>
          <div class="imgtag-list"></div>
          <button type="button" class="imgtag-add" data-act="add" title="이미지 추가">＋</button>
          <input class="imgtag-file" type="file" accept="image/*" multiple hidden>
        </div>
        <div class="imgtag-right">
          <div class="imgtag-editor">
            <div class="imgtag-mirror" aria-hidden="true"></div>
            <textarea class="imgtag-area" spellcheck="false"
                      placeholder="이미지를 올리면 여기에 태그가 정리됩니다."></textarea>
          </div>
          <div class="imgtag-acts">
            <button type="button" class="imgtag-act" data-send="main">메인</button>
            <button type="button" class="imgtag-act" data-send="character">캐릭터</button>
            <button type="button" class="imgtag-act" data-act="copy">복사</button>
          </div>
        </div>
      </div>`;
    document.body.appendChild(popup);

    popup.addEventListener('click', event => {
      const act = event.target.closest('[data-act]')?.dataset.act;
      if (act === 'close') { closeAll(); return; }
      if (act === 'min') { minimize(); return; }
      if (act === 'add') { pick('.imgtag-file').click(); return; }
      if (act === 'copy') { copy(); return; }
      const cancelId = event.target.closest('[data-cancel]');
      if (cancelId) { event.stopPropagation(); cancel(cancelId.dataset.cancel); return; }
      const open = event.target.closest('[data-open]');
      if (open) { activeId = open.dataset.open; render(); return; }
      const sender = event.target.closest('[data-send]');
      if (sender) send(sender.dataset.send);
    });
    pick('.imgtag-file').addEventListener('change', event => {
      addFiles(event.target.files);
      event.target.value = '';        // 같은 파일을 다시 고를 수 있게
    });
    const area = pick('.imgtag-area');
    area.addEventListener('input', () => {
      if (activeId) drafts.set(activeId, area.value);
      paintMirror();
    });
    area.addEventListener('scroll', paintMirror);
    const target = pick('.imgtag-target');
    target.addEventListener('pointerdown', renderTargets);
    target.addEventListener('focus', renderTargets);
    // 창 어디에나 끌어다 놓을 수 있다 - 왼쪽 목록만 받으면 조준이 필요해진다.
    popup.addEventListener('dragover', event => { event.preventDefault(); popup.classList.add('is-over'); });
    popup.addEventListener('dragleave', event => {
      if (!popup.contains(event.relatedTarget)) popup.classList.remove('is-over');
    });
    popup.addEventListener('drop', event => {
      event.preventDefault();
      popup.classList.remove('is-over');
      addFiles(event.dataTransfer?.files);
    });
    popup.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); minimize(); }
    });
    win.addEventListener('resize', positionChip);
  }

  /** 바깥(DETECTED IMAGE 팝업)에서 이미지를 밀어 넣는 문. */
  function push(blob, label, {externalNotice = '', url = ''} = {}) {
    if (!popup) build();
    if (externalNotice) notice = externalNotice;
    if (url) spaceUrl = url;
    minimized = false;
    popup.style.display = '';
    renderChip();
    const file = blob;
    // ⚠️ `addFiles` 만 상한을 보던 탓에 이 문(DETECTED IMAGE 팝업)으로는 무제한으로
    //    쌓였다 - 미리보기 blob 이 계속 는다(Codex CONCERN).
    if (file && items.length >= MAX_ITEMS) {
      showToast(`목록이 가득 찼습니다(${MAX_ITEMS}장). 오래된 항목을 지우세요.`, 'warning');
    } else if (file) {
      seq += 1;
      items.push({
        id: `it${seq}`,
        name: label || `image ${seq}`,
        url: win.URL.createObjectURL(file),
        blob: file,
        state: 'queued',
        result: null,
        error: '',
      });
    }
    render();
    pump();
  }

  function setNotice(text, url) {
    notice = text || notice;
    spaceUrl = url || spaceUrl;
    if (popup) render();
  }

  return {
    push, setNotice, close: closeAll, isOpen, minimize, restore,
    _internals: {composeText, queueLength, cancel, addFiles, get items() { return items; }},
  };
}
