// NAI Director Tools 미니 팝업 (제거 가능) — GENERATION INFO [Director] 버튼 위에 앵커되는
// 모듈형 미니 팝업. 작은 썸네일 + 모드 + (Emotion 시) 감정 + 강도 + 프롬프트(독립 한 줄) + Transform.
//
// 모드(NAI 식 분리): Declutter / Line Art / Sketch / Colorize / Emotion.
//  - Emotion 선택 시에만 감정 드롭다운(24) + 강도 + 프롬프트 표시.
//  - Colorize: 강도 + 프롬프트 (감정 없음).  - declutter/lineart/sketch: 변형만(추가 입력 없음).
// 전송 시 Emotion 모드면 mode=<감정명>(예 'Happy'), 그 외엔 mode=<req_type>('lineart' 등) → 백엔드 무변경.
//
// 셀렉트는 전역 customSelects 컨트롤러가 NAIA 표준 커스텀 셀렉트로 자동 enhance 한다(메뉴는 body
// 레벨에 렌더). 그래서 ① 각 필드를 .nai-director-field 래퍼 행으로 묶어(라벨+native+enhance 래퍼를
// 함께 숨김/표시) ② 바깥 클릭 자동닫기를 두지 않는다(메뉴 항목 클릭이 팝업 밖이라 닫혀버리는 것 방지).
// 닫기는 × 버튼만. Transform 후에도 열어 둬 연속 변형 가능.
//
// 제거: 이 파일 + app.js wiring + index.html [Director] 버튼 + 백엔드 nai_director_commands 삭제.

const K_MODE = 'naia_nai_director_mode';
const K_EMOTION = 'naia_nai_director_emotion';
const K_DEFRY = 'naia_nai_director_defry';
const K_PROMPT = 'naia_nai_director_prompt';

const MODES = [
  {value: 'declutter', label: 'Declutter'},
  {value: 'lineart', label: 'Line Art'},
  {value: 'sketch', label: 'Sketch'},
  {value: 'colorize', label: 'Colorize'},
  {value: 'emotion', label: 'Emotion'},
];
const EMOTIONS = [
  'Neutral', 'Happy', 'Sad', 'Angry', 'Scared', 'Surprised', 'Tired', 'Excited',
  'Nervous', 'Thinking', 'Confused', 'Shy', 'Disgusted', 'Smug', 'Bored', 'Laughing',
  'Irritated', 'Aroused', 'Embarrassed', 'Worried', 'Love', 'Determined', 'Hurt', 'Playful',
];
const DEFRY_LEVELS = ['Normal', 'Slightly Weak', 'Weak', 'Even Weaker', 'Very Weak', 'Weakest'];

const usesEmotion = (mode) => mode === 'emotion';
const usesPromptDefry = (mode) => mode === 'emotion' || mode === 'colorize';

function lsGet(key, fallback) {
  try { const v = localStorage.getItem(key); return v === null ? fallback : v; }
  catch (error) { return fallback; }
}
function lsSet(key, value) { try { localStorage.setItem(key, value); } catch (error) { /* 비치명 */ } }

export function createNaiDirectorModal({document, window: win = window, getWs, WebSocket, showToast = () => {}, escHtml = (value) => String(value), bindTagAssist = () => {}}) {
  let popup = null;
  let ctx = null;
  let running = false;
  let onResize = null;
  let titleObserver = null;

  function pick(selector) { return popup ? popup.querySelector(selector) : null; }

  function modeValue() { const s = pick('.nai-director-mode'); return s ? s.value : 'colorize'; }

  function savePrefs() {
    if (!popup) return;
    lsSet(K_MODE, modeValue());
    const emo = pick('.nai-director-emotion');
    const defry = pick('.nai-director-defry');
    const prompt = pick('.nai-director-prompt');
    if (emo) lsSet(K_EMOTION, emo.value || 'Neutral');
    if (defry) lsSet(K_DEFRY, defry.value || 'Weakest');
    if (prompt) lsSet(K_PROMPT, prompt.value || '');
  }

  // 래퍼 행(.nai-director-*-row)을 통째로 토글 → 라벨 + native select + customSelects enhance 래퍼가 함께 숨겨짐.
  function setRowHidden(cls, hidden) {
    if (!popup) return;
    popup.querySelectorAll('.' + cls).forEach((el) => { el.hidden = !!hidden; });
  }

  function syncFields() {
    const m = modeValue();
    setRowHidden('nai-director-emotion-row', !usesEmotion(m));
    setRowHidden('nai-director-defry-row', !usesPromptDefry(m));
    setRowHidden('nai-director-prompt-row', !usesPromptDefry(m));
    position();  // 높이 변동 → 재배치
  }

  // customSelects 가 버튼에 title=<선택값> 을 달면 앱 title-tooltip(initNaiaTitleTooltips)이 그 값을
  // 박스로 띄운다 — 컴팩트 팝업에선 값이 이미 보이므로 중복/거슬림. 팝업 내 custom-select 버튼의
  // title/data-naia-title 을 지워 이 툴팁만 끈다(커스텀 셀렉트 자체는 유지). 750ms 재스캔으로 title 이
  // 다시 붙을 수 있어 MutationObserver 로 계속 제거한다.
  function stripSelectTitles() {
    if (!popup) return;
    popup.querySelectorAll('.custom-select-button').forEach((b) => {
      if (b.hasAttribute('title')) b.removeAttribute('title');
      if (b.hasAttribute('data-naia-title')) b.removeAttribute('data-naia-title');
    });
  }

  function close() {
    if (titleObserver) { titleObserver.disconnect(); titleObserver = null; }
    if (onResize) { win.removeEventListener('resize', onResize); onResize = null; }
    if (popup) { popup.remove(); popup = null; }
    ctx = null;
    running = false;
  }

  function setStatus(text, type) {
    const status = pick('.nai-director-status');
    if (!status) return;
    status.className = 'nai-director-status' + (type ? ' ' + type : '');
    status.textContent = text || '';
  }

  function setRunning(on) {
    running = !!on;
    const go = pick('.nai-director-go');
    if (go) { go.disabled = running; go.textContent = running ? '변형 중…' : 'Transform'; }
  }

  function transform() {
    if (running || !ctx) return;
    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) { setStatus('서버에 연결되어 있지 않습니다.', 'error'); return; }
    const m = modeValue();
    // Emotion 모드면 감정명을 mode 로 전송(백엔드가 emotion 으로 처리), 그 외엔 req_type 그대로.
    const sendMode = usesEmotion(m) ? ((pick('.nai-director-emotion') || {}).value || 'Neutral') : m;
    const pd = usesPromptDefry(m);
    const prompt = pd ? ((pick('.nai-director-prompt') || {}).value || '') : '';
    const defry = pd ? ((pick('.nai-director-defry') || {}).value || 'Weakest') : '';
    savePrefs();
    setRunning(true);
    setStatus('Director 변형 중… (수 초)', 'info');
    ws.send(JSON.stringify({
      type: 'nai_director',
      source: ctx.source || '',
      path: ctx.path || '',
      file_path: ctx.filePath || '',
      label: ctx.label || '',
      mode: sendMode,
      prompt,
      defry,
    }));
  }

  function position() {
    if (!popup) return;
    const btn = document.getElementById('naiDirectorBtn');
    const rect = btn ? btn.getBoundingClientRect() : null;
    const pw = popup.offsetWidth;
    const ph = popup.offsetHeight;
    const margin = 8;
    let left = rect ? (rect.right - pw) : (win.innerWidth - pw - 16);
    left = Math.max(margin, Math.min(left, win.innerWidth - pw - margin));
    let top = rect ? (rect.top - ph - margin) : (win.innerHeight - ph - 52);
    top = Math.max(margin, top);
    popup.style.left = `${Math.round(left)}px`;
    popup.style.top = `${Math.round(top)}px`;
  }

  function open(context) {
    if (!context || !context.hasImage) { showToast('변형할 결과 이미지가 없습니다.', 'error'); return; }
    close();
    ctx = context;
    const savedMode = lsGet(K_MODE, 'colorize');
    const savedEmotion = lsGet(K_EMOTION, 'Neutral');
    const savedDefry = lsGet(K_DEFRY, 'Weakest');
    const savedPrompt = lsGet(K_PROMPT, '');
    const opt = (value, label, sel) => `<option value="${escHtml(value)}"${value === sel ? ' selected' : ''}>${escHtml(label)}</option>`;

    popup = document.createElement('div');
    popup.className = 'nai-director-popup';
    popup.innerHTML = `
      <div class="nai-director-pop-header">
        <span class="nai-director-pop-title">NAI · Director Tools</span>
        <button type="button" class="nai-director-pop-x" aria-label="닫기">&times;</button>
      </div>
      <div class="nai-director-pop-body">
        <div class="nai-director-pop-top">
          <div class="nai-director-pop-thumb"><img src="${escHtml(context.imageSrc || '')}" alt=""></div>
          <div class="nai-director-pop-fields">
            <div class="nai-director-field">
              <label class="nai-director-fld-label">모드</label>
              <select class="nai-director-mode">${MODES.map(m => opt(m.value, m.label, savedMode)).join('')}</select>
            </div>
            <div class="nai-director-field nai-director-emotion-row" hidden>
              <label class="nai-director-fld-label">감정</label>
              <select class="nai-director-emotion">${EMOTIONS.map(e => opt(e, e, savedEmotion)).join('')}</select>
            </div>
            <div class="nai-director-field nai-director-defry-row" hidden>
              <label class="nai-director-fld-label">강도</label>
              <select class="nai-director-defry">${DEFRY_LEVELS.map(d => opt(d, d, savedDefry)).join('')}</select>
            </div>
          </div>
        </div>
        <div class="nai-director-pop-prompt-row nai-director-prompt-row" hidden>
          <textarea class="nai-director-prompt" spellcheck="false" placeholder="프롬프트 (colorize / emotion 보조 지시 · 선택)">${escHtml(savedPrompt)}</textarea>
        </div>
        <div class="nai-director-pop-actions">
          <button type="button" class="nai-director-go">Transform</button>
        </div>
        <div class="nai-director-status"></div>
      </div>`;
    document.body.appendChild(popup);

    pick('.nai-director-pop-x').addEventListener('click', close);
    pick('.nai-director-go').addEventListener('click', transform);
    const modeSel = pick('.nai-director-mode');
    if (modeSel) modeSel.addEventListener('change', () => { syncFields(); savePrefs(); });
    const emoSel = pick('.nai-director-emotion');
    if (emoSel) emoSel.addEventListener('change', savePrefs);
    const defrySel = pick('.nai-director-defry');
    if (defrySel) defrySel.addEventListener('change', savePrefs);
    const promptBox = pick('.nai-director-prompt');
    if (promptBox) {
      promptBox.addEventListener('input', savePrefs);
      bindTagAssist(promptBox);  // 메인 프롬프트와 동일한 태그 autocomplete 적용
    }

    syncFields();
    position();
    // customSelects enhance(비동기) 후 높이가 바뀔 수 있어 한 프레임 뒤 재배치.
    win.requestAnimationFrame(() => position());
    win.setTimeout(() => position(), 120);
    // customSelects 가 버튼에 다는 title(=중복 툴팁) 억제 — enhance/재스캔으로 계속 붙으므로 관찰해 제거.
    titleObserver = new MutationObserver(stripSelectTitles);
    titleObserver.observe(popup, {subtree: true, childList: true, attributes: true, attributeFilter: ['title', 'data-naia-title']});
    stripSelectTitles();

    // 닫기는 × 버튼만 (바깥 클릭 자동닫기 없음 — 커스텀 셀렉트 메뉴가 body 레벨이라 항목 클릭 시
    // 닫혀버리던 문제 방지). 리사이즈 시엔 닫지 않고 재배치만.
    onResize = () => position();
    win.addEventListener('resize', onResize);
  }

  function onState(msg) {
    if (!popup) return;
    if (msg && msg.running) { setRunning(true); setStatus(msg.message || '변형 중…', 'info'); return; }
    setRunning(false);
    if (msg && msg.success) {
      showToast(msg.message || 'Director 변형 완료', 'success');
      setStatus('완료 — 결과창에 반영됨 (연속 변형 가능)', 'info');  // × 로만 닫음
    } else {
      setStatus((msg && msg.message) || '변형 실패', 'error');
    }
  }

  return {open, close, onState};
}
