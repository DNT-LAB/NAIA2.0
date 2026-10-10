/** Settings > Global > UI 확대 · 축소 - 앱 화면 배율을 다섯 단계 슬라이더로 드러낸다.
 *
 *  사용자 지시(2026-10-10): "설정에서 UI 확대 축소 섹션을 만들고, 슬라이더로 5단계 설정 가능하게.
 *  Ctrl +, Ctrl - 혹은 Ctrl + 마우스 휠로도 조작 가능하다고 적어 주세요."
 *
 *  ⚠️ **배율의 주인은 앱 껍데기(Electron main)다.** 값 · 단계 · 저장(`naia-zoom.json`)이 전부 거기 있고,
 *     Ctrl+± · Ctrl+0 · Ctrl+휠도 거기서 바꾼다. 이 화면은 **그 값을 비추고, 고르면 껍데기에 청한다** -
 *     단계의 범위도 껍데기가 알려 준 것(min · max · step)으로 그린다. 여기서 CSS `zoom` 같은 것으로
 *     따로 키우지 않는다(값이 둘이 되면 단축키와 슬라이더가 서로 다른 화면을 만든다).
 *  ⚠️ 다섯 단계(80 ~ 120%)로 묶인 까닭도 껍데기에 있다 - 더 키우면 CSS 폭이 반응형 문턱 아래로 내려가
 *     모바일 배치로 넘어간다.
 *  ⚠️ 통로가 없을 수 있다: 브라우저 탭(껍데기가 없다 - 거기서 Ctrl+± 는 브라우저의 것이라 페이지가 못 바꾼다)
 *     · 옛 껍데기(`getZoom` 이 없다 - 단축키는 되지만 값을 읽고 쓸 길이 없다). 그때는 슬라이더를 끄고 까닭을 적는다.
 */

const FALLBACK = {factor: 1, min: 0.8, max: 1.2, step: 0.1, default: 1};

/** 껍데기가 알려 준 범위로 단계를 만든다(소수 오차는 백분율로 반올림해 턴다). */
export function zoomLevels(state) {
  const s = state && typeof state === 'object' ? state : FALLBACK;
  const min = Number.isFinite(s.min) ? s.min : FALLBACK.min;
  const max = Number.isFinite(s.max) ? s.max : FALLBACK.max;
  const step = Number.isFinite(s.step) && s.step > 0 ? s.step : FALLBACK.step;
  const levels = [];
  for (let pct = Math.round(min * 100); pct <= Math.round(max * 100) + 0.5; pct += Math.round(step * 100)) {
    levels.push(pct / 100);
    if (levels.length > 40) break;                       // 엉뚱한 값이 와도 돌지 않는다
  }
  return levels.length ? levels : [1];
}

/** 그 배율에 가장 가까운 단계의 번호. */
export function levelIndex(levels, factor) {
  let best = 0;
  levels.forEach((level, index) => {
    if (Math.abs(level - factor) < Math.abs(levels[best] - factor)) best = index;
  });
  return best;
}

export const percentLabel = factor => `${Math.round(Number(factor) * 100)}%`;

export function createUiZoomSetting({
  document: doc,
  root,                         // `#uiZoomSetting`
  shell = null,                 // `window.naiaShell`(없으면 브라우저 탭)
  showToast = () => {},
} = {}) {
  if (!doc || !root) return null;
  const wired = !!(shell && typeof shell.getZoom === 'function' && typeof shell.setZoom === 'function');
  let state = {...FALLBACK};
  let levels = zoomLevels(state);

  root.innerHTML = `
    <div class="font-scale-row ui-zoom-row">
      <label for="uiZoomRange">화면 배율</label>
      <span class="ui-zoom-track">
        <input type="range" id="uiZoomRange" min="0" max="4" step="1" value="2" disabled>
        <span class="ui-zoom-ticks" aria-hidden="true"></span>
      </span>
      <span class="font-scale-value" data-ui-zoom-value>100%</span>
      <button type="button" class="mod-btn-secondary" data-ui-zoom-reset disabled>기본값</button>
    </div>
    <div class="ui-zoom-note" data-ui-zoom-note hidden></div>`;
  const range = root.querySelector('#uiZoomRange');
  const ticks = root.querySelector('.ui-zoom-ticks');
  const value = root.querySelector('[data-ui-zoom-value]');
  const reset = root.querySelector('[data-ui-zoom-reset]');
  const note = root.querySelector('[data-ui-zoom-note]');

  function paint() {
    levels = zoomLevels(state);
    const index = levelIndex(levels, Number(state.factor) || 1);
    range.max = String(levels.length - 1);
    range.value = String(index);
    range.setAttribute('aria-valuetext', percentLabel(levels[index]));
    value.textContent = percentLabel(levels[index]);
    ticks.innerHTML = levels.map((level, at) =>
      `<span class="${at === index ? 'is-on' : ''}">${Math.round(level * 100)}</span>`).join('');
    const base = Number.isFinite(state.default) ? state.default : 1;
    reset.disabled = !wired || Math.abs(levels[index] - base) < 0.001;
  }

  function accept(next) {
    if (!next || typeof next !== 'object' || !Number.isFinite(Number(next.factor))) return false;
    state = {...state, ...next, factor: Number(next.factor)};
    paint();
    return true;
  }

  async function apply(factor) {
    try {
      const result = await shell.setZoom(factor);
      // 껍데기가 정한 값이 진실이다(범위 밖을 청했으면 가까운 단계로 맞춰 돌려준다).
      if (!accept(result) || result.ok === false) throw new Error('앱 창이 배율을 바꾸지 못했습니다');
    } catch (error) {
      showToast(`화면 배율을 바꾸지 못했습니다 — ${error?.message || error}`, 'error');
      refresh();                                          // 슬라이더를 실제 값으로 되돌린다
    }
  }

  async function refresh() {
    try { accept(await shell.getZoom()); } catch (_) { /* 못 읽으면 지금 그림을 둔다 */ }
  }

  paint();
  if (!wired) {
    note.hidden = false;
    note.textContent = shell
      ? '이 앱 창은 슬라이더를 지원하지 않는 버전입니다 — 아래 단축키로는 바꿀 수 있습니다.'
      : '브라우저 탭으로 접속했습니다 — 여기서는 브라우저의 확대 · 축소가 적용됩니다(앱이 바꿀 수 없습니다).';
    return {wired: false, refresh: () => {}};
  }

  range.disabled = false;
  // 끄는 동안에는 숫자만 따라가고, 놓을 때 한 번 청한다 - 단계마다 화면 전체가 다시 짜여 손이 놓친다.
  range.addEventListener('input', () => {
    const index = Number(range.value) || 0;
    value.textContent = percentLabel(levels[index]);
    ticks.querySelectorAll('span').forEach((el, at) => el.classList.toggle('is-on', at === index));
  });
  range.addEventListener('change', () => { void apply(levels[Number(range.value) || 0]); });
  reset.addEventListener('click', () => {
    void apply(Number.isFinite(state.default) ? state.default : 1);
  });
  // 단축키 · 휠 · 폭 맞춤으로 바뀐 것도 따라간다.
  if (typeof shell.onZoomChanged === 'function') {
    try { shell.onZoomChanged(next => { accept(next); }); } catch (_) {}
  }
  void refresh();
  return {wired: true, refresh};
}
