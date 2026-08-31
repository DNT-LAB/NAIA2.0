/** Image Tagger 결과 창 — 분석된 태그를 **NAIA 프롬프트 엔지니어링과 같은 분류**로
 *  펼쳐 놓고, 사용자가 고쳐서 메인/캐릭터 프롬프트로 보내는 임시 창.
 *
 *  사용자 지정 2026-08-31:
 *    "요청을 보내면 자동으로 창을 닫고 (토스트 알림) 대기합니다. 수신된 응답은
 *     NAIA의 프롬프트 엔지니어링 방식과 유사하게 종류별로 파싱되어야 하며
 *     (상단 : Full Prompt, 하단 : 종류별 Prompt 로 나눔), Memo 패턴을 활용하여
 *     임시적으로 띄운 상태로 사용자가 메인 프롬프트 및 캐릭터 프롬프트를 수정할
 *     수 있도록 해야합니다."
 *
 *  들어오는 문은 이 창이 아니라 **DETECTED IMAGE 팝업의 한 칸**이다. 이 파일은
 *  결과만 맡는다 — 파일 고르기·미리보기가 여기 없는 이유.
 *
 *      ┌──────────────────────────────────────────┐
 *      │ Image Tagger                           × │
 *      │ ⚠ 외부 전송 고지                          │
 *      ├──────────────────────────────────────────┤
 *      │ Full Prompt        [메인][캐릭터 ▾][복사] │
 *      │ [    편집 가능 textarea               ]  │
 *      ├──────────────────────────────────────────┤
 *      │ #의상:             [메인][캐릭터]         │
 *      │ [    편집 가능 textarea               ]  │
 *      │ #표정: …                                 │
 *      └──────────────────────────────────────────┘
 *
 *  ⚠️ **임시 창이다.** 어디에도 저장하지 않는다 — 닫으면 사라진다(사용자 지정).
 *     그래서 닫기 전에 되묻지 않는다: 되물으면 임시가 아니게 된다.
 */
export function createImageTaggerResultPanel({
  document,
  window: win = window,
  escHtml = value => String(value ?? ''),
  showToast = () => {},
  onInsertMain = null,          // (text) -> bool
  onInsertCharacter = null,     // (index, text) -> bool
  getCharacters = () => [],
}) {
  let popup = null;
  let data = null;              // 마지막 분석 결과
  let notice = '';
  // textarea 의 편집 내용을 다시 그릴 때 잃지 않도록 여기에 들고 있는다.
  // (`render()` 가 innerHTML 을 갈아 끼우므로 DOM 을 믿을 수 없다.)
  let drafts = new Map();

  const pick = selector => (popup ? popup.querySelector(selector) : null);

  function isOpen() {
    return !!popup && popup.style.display !== 'none';
  }

  function close() {
    if (popup) popup.style.display = 'none';
  }

  function draft(key, fallback) {
    return drafts.has(key) ? drafts.get(key) : fallback;
  }

  // ── 프롬프트로 보내기 ─────────────────────────────────────────
  function targetIndex() {
    const select = pick('.imgtag-target');
    const value = select ? Number(select.value) : 0;
    return Number.isFinite(value) ? value : 0;
  }

  function send(where, key) {
    const box = popup && popup.querySelector(`textarea[data-key="${key}"]`);
    const text = String(box ? box.value : draft(key, '')).trim();
    if (!text) { showToast('보낼 태그가 없습니다.', 'warning'); return; }
    if (where === 'main') {
      const ok = typeof onInsertMain === 'function' && onInsertMain(text);
      showToast(ok === false ? '메인 프롬프트에 넣지 못했습니다.' : '메인 프롬프트에 넣었습니다.',
                ok === false ? 'error' : 'success');
      return;
    }
    const index = targetIndex();
    const characters = getCharacters() || [];
    if (!characters.length) { showToast('활성화된 캐릭터가 없습니다.', 'warning'); return; }
    const ok = typeof onInsertCharacter === 'function' && onInsertCharacter(index, text);
    showToast(ok === false ? '캐릭터 프롬프트에 넣지 못했습니다.'
                           : `캐릭터 ${index + 1} 에 넣었습니다.`,
              ok === false ? 'error' : 'success');
  }

  async function copy(key) {
    const box = popup && popup.querySelector(`textarea[data-key="${key}"]`);
    const text = String(box ? box.value : '').trim();
    if (!text) return;
    try {
      await win.navigator.clipboard.writeText(text);
      showToast('복사했습니다.', 'success');
    } catch (error) {
      showToast('복사하지 못했습니다.', 'error');
    }
  }

  // ── 그리기 ───────────────────────────────────────────────────
  function actionsHtml(key, {withCopy = false} = {}) {
    return `
      <div class="imgtag-acts">
        <button type="button" class="imgtag-act" data-send="main" data-key="${escHtml(key)}">메인</button>
        <button type="button" class="imgtag-act" data-send="character" data-key="${escHtml(key)}">캐릭터</button>
        ${withCopy ? `<button type="button" class="imgtag-act" data-copy="${escHtml(key)}">복사</button>` : ''}
      </div>`;
  }

  function sectionHtml(key, title, text, {withCopy = false} = {}) {
    return `
      <section class="imgtag-section">
        <div class="imgtag-section-head">
          <span class="imgtag-section-title">${escHtml(title)}</span>
          ${actionsHtml(key, {withCopy})}
        </div>
        <textarea class="imgtag-area" data-key="${escHtml(key)}" spellcheck="false"
                  rows="${key === 'full' ? 4 : 2}">${escHtml(text)}</textarea>
      </section>`;
  }

  /** 캐릭터 목록을 다시 그린다.
   *
   *  ⚠️ `render()` 안에서만 그리면 **낡는다.** 이 창은 임시로 떠 있고 그 동안
   *     사용자가 캐릭터를 추가/삭제할 수 있다 — 실측에서 캐릭터를 만든 뒤에도
   *     드롭다운이 "캐릭터 없음" 이었다(보내기는 되는데 화면만 거짓말). 그래서
   *     열 때마다(pointerdown/focus) 다시 그린다.
   */
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
    // 고르던 값이 아직 있으면 지킨다 - 목록을 새로 그린다고 선택이 튀면 안 된다.
    if (keep && select.querySelector(`option[value="${keep}"]`)) select.value = keep;
    select.disabled = !characters.length;
  }

  function render() {
    if (!popup || !pick('.imgtag-notice')) return;
    pick('.imgtag-notice').innerHTML = notice
      ? `<span class="imgtag-notice-mark" aria-hidden="true">⚠</span>${escHtml(notice)}`
      : '';

    renderTargets();

    const body = pick('.imgtag-body');
    if (!data) {
      body.innerHTML = '<div class="imgtag-hint">아직 분석 결과가 없습니다.</div>';
      return;
    }
    const groups = Array.isArray(data.categories) ? data.categories : [];
    body.innerHTML =
      sectionHtml('full', 'Full Prompt', draft('full', data.tag_string || ''), {withCopy: true}) +
      (groups.length
        ? groups.map(group =>
            sectionHtml(`cat:${group.key}`, group.marker || group.label,
                        draft(`cat:${group.key}`, (group.tags || []).join(', ')))).join('')
        // 분류 데이터가 없으면 **가짜 분류를 만들지 않는다.** 전부 '#추가:' 인
        // 화면은 분류된 척하면서 아무것도 안 알려 준다.
        : '<div class="imgtag-hint">태그 사전이 아직 안 올라와 종류별 분류를 못 했습니다. 위의 Full Prompt 를 쓰세요.</div>');

    body.querySelectorAll('textarea[data-key]').forEach(area => {
      area.addEventListener('input', () => drafts.set(area.dataset.key, area.value));
    });
  }

  function build() {
    popup = document.createElement('div');
    popup.className = 'imgtag-popup';
    popup.innerHTML = `
      <div class="imgtag-head">
        <span class="imgtag-title">Image Tagger</span>
        <span class="imgtag-status"></span>
        <select class="imgtag-target" aria-label="캐릭터 대상"></select>
        <button type="button" class="imgtag-x" data-act="close" aria-label="닫기">&times;</button>
      </div>
      <div class="imgtag-notice"></div>
      <div class="imgtag-body"></div>
    `;
    document.body.appendChild(popup);

    popup.addEventListener('click', event => {
      if (event.target.closest('[data-act="close"]')) { close(); return; }
      const sender = event.target.closest('[data-send]');
      if (sender) { send(sender.dataset.send, sender.dataset.key); return; }
      const copier = event.target.closest('[data-copy]');
      if (copier) { copy(copier.dataset.copy); }
    });
    const target = pick('.imgtag-target');
    target.addEventListener('pointerdown', renderTargets);
    target.addEventListener('focus', renderTargets);
    popup.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); close(); }
    });
  }

  /** 새 분석 결과를 띄운다. 앞선 결과의 편집분은 버린다 — 다른 이미지의 태그다. */
  function show(payload, {externalNotice = ''} = {}) {
    if (!popup) build();
    data = payload || null;
    drafts = new Map();
    if (externalNotice) notice = externalNotice;
    const status = pick('.imgtag-status');
    if (status) {
      const seconds = Math.round((payload?.elapsed_ms || 0) / 100) / 10;
      const count = (payload?.general || []).length + (payload?.character || []).length;
      status.textContent = `태그 ${count}개 · ${seconds}초`;
      status.className = 'imgtag-status ok';
    }
    popup.style.display = '';
    render();
  }

  return {show, close, isOpen};
}
