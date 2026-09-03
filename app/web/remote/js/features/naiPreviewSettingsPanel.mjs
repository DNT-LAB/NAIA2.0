/**
 * V4.5 프리뷰 설정 패널 — 툴바의 [4.5 프리뷰] 를 누르면 뜨는 팝업.
 *
 * ⚠️ 2026-09-03: 톱니를 없앴다가 **되돌렸다**(사용자 지정). 표식 삽입/제거가 잦아서
 *    설정이 한 클릭 더 멀어지는 값이 footer 23px 보다 크다. 툴바에서 **글자 = 생성 ·
 *    톱니 = 설정** 이고, 머리줄의 [생성] 은 값을 고쳐 가며 다시 뽑는 용도로 남는다.
 *    폭은 **메인 프롬프트 텍스트창에 맞춘다**(같은 지정) — 왼쪽 끝까지 맞춰 겹쳐 놓으면
 *    어느 글을 두고 하는 설정인지가 눈으로 이어진다.
 *
 * 사용자 SPEC 2026-09-01. 치수는 Memo·Tagger 계열을 따른다(높이 22px · 글자 10px ·
 * 라운드 5px) — 앞으로 팝업 모듈의 기준이라는 사용자 지정.
 *
 * ⚠️ 값의 SSOT 는 **백엔드**다(`core/nai_preview_settings.py`). 여기서는 서버가 준
 *    값을 그리고, 바뀌면 되돌려 보낸 뒤 **서버가 정규화해 돌려준 것**으로 다시 그린다.
 *    범위를 화면에서도 한 벌 더 들면 두 잣대가 어긋난다 — 스텝 상한 28 은 곧 무료
 *    경계라, 어긋나면 돈이 나간다.
 */
export function createNaiPreviewSettingsPanel({
  document: doc,
  window: win,
  showToast,
  escHtml,
  onMarkers,
  onGenerate,
}) {
  const SETTINGS_URL = '/api/nai-preview/settings';
  // 팝업을 여는 톱니. 위치의 기준이자 열림 표시(`aria-expanded`)를 다는 자리다.
  const ANCHOR_ID = 'preview45GearBtn';
  // 폭을 맞출 대상 - 메인 프롬프트 텍스트창.
  const WIDTH_SOURCE_ID = 'promptEdit';
  let panel = null;
  let settings = null;
  let options = null;
  let saveTimer = null;
  let activeTab = 'prompt';

  const el = id => doc.getElementById(id);

  function isOpen() {
    return !!(panel && panel.classList.contains('open'));
  }

  async function load() {
    const res = await fetch(SETTINGS_URL, {headers: {Accept: 'application/json'}});
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    settings = data.settings || {};
    options = data.options || {};
  }

  /** 바뀐 값을 보내고 **서버가 정규화한 것**으로 갈아 낀다. 잘린 값이 화면에 바로 보인다. */
  function queueSave(patch) {
    Object.assign(settings, patch);
    if (saveTimer) win.clearTimeout(saveTimer);
    saveTimer = win.setTimeout(async () => {
      saveTimer = null;
      try {
        const res = await fetch(SETTINGS_URL, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(settings),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { showToast(data.error || '프리뷰 설정을 저장하지 못했습니다.', 'error'); return; }
        settings = data.settings || settings;
        render();
      } catch (error) {
        showToast('프리뷰 설정 저장 실패: ' + error.message, 'error');
      }
    }, 350);
  }

  function toggleRow(key, label) {
    const on = !!settings[key];
    return `<button type="button" class="pv45-toggle${on ? ' on' : ''}" data-toggle="${key}"
              aria-pressed="${on}"><span class="pv45-box"></span>${escHtml(label)}</button>`;
  }

  function segment(key, choices) {
    return `<div class="pv45-seg" role="group">` + choices.map(([value, text]) =>
      `<button type="button" class="pv45-seg-btn${settings[key] === value ? ' on' : ''}"
         data-seg="${key}" data-value="${escHtml(value)}">${escHtml(text)}</button>`).join('') + `</div>`;
  }

  function select(key, values, current) {
    return `<select class="pv45-select" data-select="${key}">` + values.map(value =>
      `<option value="${escHtml(String(value))}"${String(current) === String(value) ? ' selected' : ''}>${escHtml(String(value))}</option>`
    ).join('') + `</select>`;
  }

  function render() {
    if (!panel || !settings) return;
    const body = panel.querySelector('.pv45-body');
    if (!body) return;
    // ⚠️ 편집 중인 칸이 있으면 다시 그리지 않는다 - 디바운스 저장의 응답이 도착할 때마다
    //    커서가 튀고 방금 친 글자가 사라진다.
    const active = doc.activeElement;
    if (active && body.contains(active)
        && (active.tagName === 'TEXTAREA' || active.tagName === 'INPUT')) return;

    const custom = settings.resolution_mode === 'custom';
    const resList = (options.custom_resolutions || []).map(r => `${r.width} x ${r.height}`);
    const currentRes = `${settings.custom_width} x ${settings.custom_height}`;

    body.innerHTML = `
      <div class="pv45-row pv45-markers">
        <button type="button" class="pv45-btn" data-act="insert">프리뷰 표식 삽입</button>
        <button type="button" class="pv45-btn" data-act="remove">제거</button>
      </div>
      <div class="pv45-sep"></div>
      ${toggleRow('on_random', '랜덤 버튼이 작동할 때 함께 요청')}
      ${toggleRow('send_character', '캐릭터 프롬프트를 함께 보냅니다')}
      ${toggleRow('alt_p_hotkey', 'ALT + P 로 요청')}
      <div class="pv45-sep"></div>
      <div class="pv45-row"><span class="pv45-label">해상도</span>
        ${segment('resolution_mode', [['custom', '직접 선택'], ['small', 'Small'], ['standard', 'Standard']])}
      </div>
      ${custom ? `<div class="pv45-row"><span class="pv45-label"></span>
        ${select('custom_resolution', resList, currentRes)}</div>` : ''}
      <div class="pv45-row"><span class="pv45-label">샘플러</span>
        ${select('sampler', options.samplers || [], settings.sampler)}</div>
      <div class="pv45-row"><span class="pv45-label">스케줄러</span>
        ${select('scheduler', options.schedulers || [], settings.scheduler)}</div>
      <div class="pv45-row pv45-nums">
        <label class="pv45-num">Steps<input type="number" data-num="steps" min="1" max="28" step="1"
          value="${escHtml(String(settings.steps))}"></label>
        <label class="pv45-num">CFG<input type="number" data-num="cfg_scale" min="1" max="7" step="0.1"
          value="${escHtml(String(settings.cfg_scale))}"></label>
        <label class="pv45-num">Rescale<input type="number" data-num="cfg_rescale" min="-0.2" max="1" step="0.05"
          value="${escHtml(String(settings.cfg_rescale))}"></label>
      </div>
      <div class="pv45-row">
        ${toggleRow('var_plus', 'VAR+')}
        ${toggleRow('decrisp', 'DECRISP')}
      </div>
      <div class="pv45-sep"></div>
      <div class="pv45-tabs">
        <button type="button" class="pv45-tab${activeTab === 'prompt' ? ' on' : ''}" data-tab="prompt">선행/후행 프롬프트</button>
        <button type="button" class="pv45-tab${activeTab === 'negative' ? ' on' : ''}" data-tab="negative">네거티브 프롬프트</button>
      </div>
      ${activeTab === 'prompt' ? `
        <div class="pv45-field"><span class="pv45-label">선행 고정 프롬프트</span>
          <textarea class="pv45-area" data-text="prefix" rows="2">${escHtml(settings.prefix || '')}</textarea></div>
        <div class="pv45-field"><span class="pv45-label">후행 고정 프롬프트</span>
          <textarea class="pv45-area" data-text="postfix" rows="3">${escHtml(settings.postfix || '')}</textarea></div>`
      : `
        <div class="pv45-field"><span class="pv45-label">네거티브 프롬프트</span>
          <textarea class="pv45-area" data-text="negative" rows="5">${escHtml(settings.negative || '')}</textarea></div>`}
    `;
  }

  function build() {
    panel = doc.createElement('div');
    panel.className = 'pv45-panel';
    panel.id = 'preview45Panel';
    // ⚠️ [생성] 은 **머리줄**에 둔다. 몸통(`.pv45-body`)은 값이 바뀔 때마다 통째로 다시
    //    그려서, 거기 두면 누르는 순간 사라질 수 있다. 머리줄은 한 번만 만든다.
    panel.innerHTML = `
      <div class="pv45-head">
        <span class="pv45-title">V4.5 PREVIEW</span>
        <button type="button" class="pv45-run" id="preview45PanelRunBtn" data-generate>생성</button>
        <button type="button" class="pv45-x" data-close aria-label="닫기">&times;</button>
      </div>
      <div class="pv45-body"></div>`;
    doc.body.appendChild(panel);

    panel.addEventListener('click', event => {
      if (event.target.closest('[data-close]')) { close(); return; }
      // 생성은 창을 닫지 않는다 - 결과를 보고 값을 고쳐 다시 뽑는 것이 이 팝업의 쓰임새다.
      if (event.target.closest('[data-generate]')) { onGenerate?.(); return; }
      const act = event.target.closest('[data-act]');
      if (act) { onMarkers?.(act.dataset.act); return; }
      const toggle = event.target.closest('[data-toggle]');
      if (toggle) { queueSave({[toggle.dataset.toggle]: !settings[toggle.dataset.toggle]}); render(); return; }
      const seg = event.target.closest('[data-seg]');
      if (seg) { queueSave({[seg.dataset.seg]: seg.dataset.value}); render(); return; }
      const tab = event.target.closest('[data-tab]');
      if (tab) { activeTab = tab.dataset.tab; render(); }
    });
    panel.addEventListener('change', event => {
      const sel = event.target.closest('[data-select]');
      if (sel) {
        if (sel.dataset.select === 'custom_resolution') {
          const [w, h] = String(sel.value).split('x').map(part => parseInt(part.trim(), 10));
          queueSave({custom_width: w, custom_height: h});
        } else {
          queueSave({[sel.dataset.select]: sel.value});
        }
        return;
      }
      const num = event.target.closest('[data-num]');
      // ⚠️ 값 검사를 여기서 하지 않는다 - 서버가 clamp 해 돌려준 값으로 다시 그린다.
      //    화면에도 상한을 적으면 두 잣대가 생기고, 그 상한이 곧 무료 경계다.
      if (num) queueSave({[num.dataset.num]: num.value});
    });
    panel.addEventListener('input', event => {
      const area = event.target.closest('[data-text]');
      if (area) queueSave({[area.dataset.text]: area.value});
    });
    doc.addEventListener('pointerdown', event => {
      if (isOpen() && !panel.contains(event.target)
          && event.target.id !== ANCHOR_ID) close();
    }, true);
    doc.addEventListener('keydown', event => {
      if (event.key === 'Escape' && isOpen()) close();
    });
    win.addEventListener('resize', place);
  }

  /**
   * 버튼 위에 띄우고 **그린 뒤 재서** 화면 안으로 가둔다(내용에 따라 높이가 변한다).
   *
   * 폭과 왼쪽 끝을 **메인 프롬프트 텍스트창에 맞춘다**(사용자 지정 2026-09-03). 폭을
   * 먼저 정하고 나서 높이를 재야 한다 — 넓어지면 줄이 덜 접혀 높이가 줄어든다.
   * 텍스트창을 못 찾으면 CSS 기본 폭으로 두고 예전처럼 버튼 오른쪽에 맞춘다.
   */
  function place() {
    if (!isOpen()) return;
    const anchor = el(ANCHOR_ID);
    if (!anchor) return;
    const box = anchor.getBoundingClientRect();

    const source = el(WIDTH_SOURCE_ID);
    const sourceBox = source ? source.getBoundingClientRect() : null;
    // 폭 0 은 숨겨져 있다는 뜻이다 - 그때는 손대지 않는다(0px 짜리 팝업이 뜬다).
    const wide = sourceBox && sourceBox.width > 0;
    if (wide) {
      panel.style.width = `${Math.round(Math.min(sourceBox.width, win.innerWidth - 16))}px`;
    } else {
      panel.style.width = '';
    }

    const rect = panel.getBoundingClientRect();
    const preferredLeft = wide ? sourceBox.left : box.right - rect.width;
    const left = Math.max(8, Math.min(preferredLeft, win.innerWidth - rect.width - 8));
    const top = Math.max(8, box.top - rect.height - 6);
    panel.style.left = `${Math.round(left)}px`;
    panel.style.top = `${Math.round(top)}px`;
  }

  /** 생성 중에는 팝업의 [생성] 도 함께 잠근다(툴바 글자 버튼과 같은 잠금). */
  function setBusy(busy) {
    const run = el('preview45PanelRunBtn');
    if (run) run.disabled = !!busy;
  }

  function close() {
    if (panel) panel.classList.remove('open');
    el(ANCHOR_ID)?.setAttribute('aria-expanded', 'false');
  }

  async function open() {
    if (!panel) build();
    try {
      await load();
    } catch (error) {
      showToast('프리뷰 설정을 불러오지 못했습니다: ' + error.message, 'error');
      return;
    }
    render();
    panel.classList.add('open');
    el(ANCHOR_ID)?.setAttribute('aria-expanded', 'true');
    place();
  }

  function toggle() {
    if (isOpen()) { close(); return; }
    void open();
  }

  /** 프런트의 다른 곳(랜덤 연동·ALT+P)이 물어보는 값. 아직 안 열었으면 null. */
  function current() {
    return settings;
  }

  return {open, close, toggle, isOpen, current, setBusy, refresh: load};
}
