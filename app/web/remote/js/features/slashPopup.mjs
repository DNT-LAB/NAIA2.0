/* 슬래시 작은 창의 틀(/assist · /translate, 사용자 지정 2026-10-01).
 *
 * 메인 프롬프트에서 `/assist` · `/translate` 를 고르면 엔트리가 있던 자리(캐럿)에 뜬다. 틀 = 내용(부르는 쪽이 채운다) ·
 * 알림 줄 · [닫기 ESC | 확인 ENTER]. 한 번에 하나만 뜬다(새로 열면 앞의 것은 'replaced' 로 닫힌다).
 * - 바깥을 눌러도 닫지 않는다 — Assist 는 답을 기다리는 몇 초 동안 메인 칸을 만질 수 있어야 한다. 닫기는 Esc · [닫기] 뿐.
 * - Enter = 확인 · Shift+Enter = 줄바꿈. ⚠️ 한글 조합 중의 Enter 는 글자를 확정하는 키다 — 보내지 않는다(assistPanel 과 같다).
 *   Enter 로 제출하는 것은 **글칸에서만** — 단추에 포커스가 있으면 그 단추가 눌린다([닫기] 에서 Enter 가 삽입하던 것, Codex S1 ④).
 * - Esc · Enter 는 여기서 전파를 끊는다 — 글로벌 단축키(Ctrl+Enter = Generate)가 버블 단계에 붙어 있다(슬래시 편집창 제보 09-13).
 * - CSS 는 이 모듈이 싣는다(style.css 의 z-index 숫자는 시험이 훑는다 — 셋업 모달 10300 아래, 슬래시 편집창과 같은 층).
 *   ⚠️ CSS 템플릿 안에는 백틱을 쓰지 않는다.
 */

const STYLE_ID = 'slash-pop-style';
const CSS = `
.slash-pop { position: fixed; z-index: 10002; width: min(460px, calc(100vw - 16px)); box-sizing: border-box;
  padding: 7px 9px 8px; border-radius: 8px; background: #16151f; border: 1px solid rgba(139,118,255,0.75);
  box-shadow: 0 6px 24px rgba(0,0,0,0.55); color: var(--text-primary); font-size: 11px; }
.slash-pop-body { display: flex; flex-direction: column; gap: 6px; }
.slash-pop-row { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.slash-pop-gap { flex: 1 1 auto; }
.slash-pop-text { width: 100%; box-sizing: border-box; resize: vertical; min-height: 44px; max-height: 40vh; padding: 6px 8px;
  border-radius: 6px; border: 1px solid var(--border-dim); background: #0f0e16; color: var(--text-primary);
  font-family: var(--font-editor, var(--font-mono)); font-size: 12px; line-height: 1.5; outline: none; }
.slash-pop-text:focus { border-color: var(--accent); }
.slash-pop-text.is-out { background: #13121c; color: var(--text-muted); }
.slash-pop-note { font-size: 10.5px; line-height: 1.45; color: var(--text-muted); }
.slash-pop-note.is-error { color: #ff8a80; }
.slash-pop-note button { margin-left: 6px; }
.slash-pop-foot { display: flex; align-items: center; gap: 6px; margin-top: 7px; }
.slash-pop-btn { height: 22px; padding: 0 9px; border-radius: 5px; border: 1px solid var(--border-dim); background: transparent;
  color: var(--text-muted); font-size: 10.5px; cursor: pointer; white-space: nowrap; }
.slash-pop-btn:hover { color: var(--text-primary); border-color: var(--text-dim); }
.slash-pop-btn.is-ok { border-color: rgba(139,118,255,0.75); background: rgba(88,76,170,0.35); color: var(--text-primary); }
.slash-pop-btn:disabled { opacity: 0.45; cursor: default; }
.slash-pop-btn kbd { margin-left: 4px; font-family: var(--font-mono); font-size: 9px; color: var(--text-dim); }
`;

let current = null;

function ensureStyle(document) {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement('style');
  style.id = STYLE_ID;
  style.textContent = CSS;
  document.head.appendChild(style);
}

/**
 * @param {object} o
 * @param {string} [o.className] 이 창만의 클래스(내용 칸 꾸밈)
 * @param {string} o.bodyHtml   내용 칸
 * @param {string} [o.okLabel]  확인 단추 글(제출 · 삽입)
 * @param {number} o.left       엔트리가 있던 자리
 * @param {number} o.top
 * @param {() => void} o.onOk   Enter · 확인
 * @param {(reason: string) => void} [o.onClose]  'esc' · 'button' · 'done' · 'replaced'
 */
export function openSlashPopup({ document = globalThis.document, window = globalThis.window, className = '', bodyHtml = '',
  okLabel = '확인', left = 0, top = 0, onOk, onClose } = {}) {
  current?.close('replaced');
  ensureStyle(document);
  const el = document.createElement('div');
  el.className = `slash-pop${className ? ` ${className}` : ''}`;
  el.innerHTML = `<div class="slash-pop-body">${bodyHtml}</div>
    <div class="slash-pop-note" data-sp-note hidden></div>
    <div class="slash-pop-foot">
      <button type="button" class="slash-pop-btn" data-sp-close>닫기<kbd>ESC</kbd></button>
      <span class="slash-pop-gap"></span>
      <button type="button" class="slash-pop-btn is-ok" data-sp-ok>${okLabel}<kbd>ENTER</kbd></button>
    </div>`;
  document.body.appendChild(el);
  const note = el.querySelector('[data-sp-note]');
  const okBtn = el.querySelector('[data-sp-ok]');
  let closed = false;

  // 캐럿 자리에 — 화면 밖으로 나가면 안쪽으로 당긴다(아래가 모자라면 위로)
  const vw = window.innerWidth, vh = window.innerHeight;
  const rect = el.getBoundingClientRect();
  el.style.left = `${Math.round(Math.max(8, Math.min(left, vw - rect.width - 8)))}px`;
  el.style.top = `${Math.round(Math.max(8, Math.min(top, vh - rect.height - 8)))}px`;

  const handle = {
    el,
    okLabel,
    isOpen: () => !closed,
    close(reason = 'done') {
      if (closed) return;
      closed = true;
      if (current === handle) current = null;
      el.remove();
      try { onClose?.(reason); } catch (error) { console.warn('slash popup close failed', error); }
    },
    /** 알림 줄 — html 은 부르는 쪽이 이스케이프한다. 빈 글이면 숨긴다 */
    setNote(html, kind = '') {
      note.innerHTML = html || '';
      note.hidden = !html;
      note.classList.toggle('is-error', kind === 'error');
    },
    /** 도는 동안 확인 단추를 잠그고 글을 바꾼다(찾는 중… · 번역 중…). 닫기는 늘 된다 */
    setBusy(on, label = '') {
      okBtn.disabled = !!on;
      okBtn.firstChild.textContent = on && label ? label : okLabel;
    },
    setOkEnabled(on) { okBtn.disabled = !on; },
  };

  el.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      handle.close('esc');
      return;
    }
    if (event.key !== 'Enter') return;
    event.stopPropagation();                          // Ctrl+Enter 가 Generate 까지 누르지 않게
    const tag = String(event.target?.tagName || '').toUpperCase();
    if (tag !== 'TEXTAREA' && tag !== 'INPUT') return;   // 단추 위의 Enter 는 그 단추(기본 동작)
    if (event.isComposing || event.keyCode === 229) return;
    if (event.shiftKey) return;                       // 줄바꿈
    event.preventDefault();
    if (!okBtn.disabled) onOk?.();
  });
  el.addEventListener('click', event => {
    if (event.target.closest('[data-sp-close]')) { handle.close('button'); return; }
    if (event.target.closest('[data-sp-ok]') && !okBtn.disabled) onOk?.();
  });
  current = handle;
  return handle;
}
