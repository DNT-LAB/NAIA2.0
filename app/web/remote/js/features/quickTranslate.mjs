/* /translate 작은 창(사용자 지정 2026-10-01) — [한국어 입력] · [영어 출력] · [닫기 ESC | 삽입 ENTER].
 *
 * 번역은 Translate 창과 같은 길이다(WS translate_text ko_en -> translation_result, 요청 ID 로 이 창의 것만 받는다).
 * Enter 는 지금 글의 번역을 엔트리를 연 캐럿 자리에 넣는다 — 번역이 아직이면 받는 대로 넣는다. 한글이 없는 글은 번역할 것이
 * 없으니 그대로 넣는다. 명령 뒤에 이어 친 글(`/translate 창가의 소녀`)은 바로 번역해서 넣는다(/assist 와 같다).
 *
 * ⚠️ 번역기는 모든 소비자(자동완성 · Translate 창 · 여기)가 함께 쓰는 서버 백오프를 탄다(utils/translator: 429 면 60초부터 두 배씩,
 *    그동안 요청은 곧바로 rate_limited 로 돌아온다). 막힌 동안 두드리면 차단이 길어진다 — 그래서 Translate 창의 규칙을 그대로 쓴다:
 *    · 멈춤(600ms) 뒤에만 보낸다 · 완성 음절에 붙은 자모 하나(조합 중)는 보내지 않는다
 *    · **같은 글은 다시 보내지 않는다** — 보낸 글 기억은 응답이 와도 · 10초 안전망에서도 지우지 않는다
 *    · 10초 안전망 = 응답이 영영 안 올 때(연결 끊김) '번역 중' 표시만 푼다. 기다리거나 다시 보내지 않는다
 *    · 창을 닫으면 타이머를 모두 끄고 늦게 온 응답은 버린다
 *    [삽입] 만은 같은 글이라도 실패한 뒤면 다시 보낸다(사용자가 누른 것 — Translate 창의 [Translate] 와 같다).
 */
import { openSlashPopup } from './slashPopup.mjs?v=20261001-slashpop';

const AUTO_MS = 600;
const SAFETY_MS = 10000;
const HANGUL = /[가-힣ㄱ-ㅎㅏ-ㅣ]/;
const COMPOSING_TAIL = /[가-힣][ㄱ-ㆎ]$/;

export function createQuickTranslate({ getWs, showToast } = {}) {
  let st = null;          // 열려 있을 때만
  let seq = 0;

  const esc = value => String(value == null ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

  function open(ctx = {}) {
    st?.pop.close('replaced');
    const pop = openSlashPopup({
      className: 'slash-tr', okLabel: '삽입', left: ctx.left, top: ctx.top,
      bodyHtml: `<textarea class="slash-pop-text" data-tr-in rows="2" spellcheck="false" autocomplete="off"
          aria-label="번역할 글" placeholder="한국어 — 멈추면 번역합니다"></textarea>
        <textarea class="slash-pop-text is-out" data-tr-out rows="2" readonly tabindex="-1"
          aria-label="번역" placeholder="English"></textarea>`,
      onOk: () => insertNow(),
      onClose: reason => {
        const was = st;
        if (!was || was.pop !== pop) return;
        clearTimeout(was.timer);
        clearTimeout(was.safety);
        st = null;
        if (reason === 'esc' || reason === 'button') was.ctx.cancel?.();
      },
    });
    st = {
      pop, ctx,
      input: pop.el.querySelector('[data-tr-in]'),
      output: pop.el.querySelector('[data-tr-out]'),
      sentText: '',        // 마지막으로 보낸 글(같은 글 재발사 차단) — 응답 · 안전망에서도 남긴다
      pendingId: '',       // 답을 기다리는 요청
      doneText: '',        // 출력 칸의 번역이 어느 글의 것인가
      failed: false,       // 마지막 응답이 실패였다 — [삽입] 은 같은 글이라도 다시 보낸다
      insertWhenDone: false,
      timer: 0, safety: 0,
    };
    st.input.addEventListener('input', schedule);
    // 조합이 끝난 자리는 확실한 멈춤이다 — 뒤따르는 input 과 겹쳐도 같은 글 차단이 잡는다(Translate 창과 같다)
    st.input.addEventListener('compositionend', schedule);
    const seed = String(ctx.seed || '').trim();
    if (seed) {
      st.input.value = seed;
      insertNow();
    }
    st?.input.focus();
  }

  function schedule() {
    if (!st) return;
    clearTimeout(st.timer);
    const text = st.input.value.trim();
    st.pop.setNote('');
    if (!text) { st.output.value = ''; st.doneText = ''; return; }
    if (!HANGUL.test(text)) { st.output.value = text; st.doneText = text; return; }   // 번역할 것이 없다 — 그대로
    if (COMPOSING_TAIL.test(text)) return;                                           // 음절을 만드는 중
    st.timer = setTimeout(() => { if (st) request(st.input.value.trim(), false); }, AUTO_MS);
  }

  function request(text, force) {
    if (!st || !text) return;
    if (!force && text === st.sentText) return;        // 같은 글은 다시 보내지 않는다
    const ws = typeof getWs === 'function' ? getWs() : null;
    if (!ws || ws.readyState !== 1) {
      st.pop.setNote('원격 연결이 열려 있지 않아 번역하지 못했습니다.', 'error');
      if (st.insertWhenDone) { st.insertWhenDone = false; st.pop.setBusy(false); }
      return;
    }
    st.sentText = text;
    st.failed = false;
    const requestId = `slash-tr-${Date.now()}-${++seq}`;
    st.pendingId = requestId;
    st.output.value = '…';
    ws.send(JSON.stringify({ type: 'translate_text', direction: 'ko_en', text, requestId }));
    clearTimeout(st.safety);
    st.safety = setTimeout(() => {
      // 응답이 안 왔다(연결 끊김 등) — '번역 중' 만 푼다. 보낸 글 기억은 남긴다(지우면 아무 입력이나 같은 글을 다시 보낸다)
      if (!st || st.pendingId !== requestId) return;
      st.pendingId = '';
      st.failed = true;
      if (st.output.value === '…') st.output.value = '';
      st.pop.setNote('번역 응답이 없습니다 — 연결을 확인하고 [삽입] 으로 다시 시도해 주세요.', 'error');
      if (st.insertWhenDone) { st.insertWhenDone = false; st.pop.setBusy(false); }
    }, SAFETY_MS);
  }

  /** translation_result — 이 창이 보낸 것이면 받고 true(app.js 의 Translate 창 처리기 앞에서 부른다) */
  function onResult(message) {
    const requestId = String(message?.requestId || '');
    if (!requestId.startsWith('slash-tr-')) return false;
    if (!st || requestId !== st.pendingId) return true;           // 닫혔거나 늦게 온 옛 응답 — 버린다
    st.pendingId = '';
    clearTimeout(st.safety);
    const answered = String(message?.text || '');
    const current = st.input.value.trim();
    const translated = String(message?.translated || '');
    if (!translated) {
      st.failed = true;
      if (st.output.value === '…') st.output.value = '';
      const reason = typeof message?.error === 'string' && message.error ? message.error : '번역하지 못했습니다';
      st.pop.setNote(esc(reason), 'error');
      if (st.insertWhenDone) { st.insertWhenDone = false; st.pop.setBusy(false); }
      return true;
    }
    if (answered && answered !== current) {
      // 그 사이 글이 바뀌었다 — 출력 칸에 옛 번역을 앉히지 않는다. 바뀐 글은 멈춤 타이머 · [삽입] 이 보낸다
      if (st.insertWhenDone) request(current, true);
      return true;
    }
    st.output.value = translated;
    st.doneText = answered || current;
    if (st.insertWhenDone) finish(translated);
    return true;
  }

  /** [삽입] · Enter — 지금 글의 번역을 넣는다. 아직이면 받는 대로 */
  function insertNow() {
    if (!st) return;
    clearTimeout(st.timer);
    const text = st.input.value.trim();
    if (!text) { st.input.focus(); return; }
    if (!HANGUL.test(text)) { finish(text); return; }
    if (st.doneText === text && st.output.value && st.output.value !== '…') { finish(st.output.value); return; }
    st.insertWhenDone = true;
    st.pop.setBusy(true, '번역 중…');
    st.pop.setNote('');
    if (st.pendingId && st.sentText === text) return;              // 이 글은 이미 답을 기다린다
    request(text, st.failed || st.sentText !== text);
  }

  function finish(text) {
    if (!st) return;
    const { pop, ctx } = st;
    const ok = typeof ctx.insert === 'function' ? ctx.insert(text) : false;
    pop.close('done');
    if (!ok) showToast?.('프롬프트에 넣지 못했습니다', 'error');
  }

  return { open, onResult, isOpen: () => !!st };
}
