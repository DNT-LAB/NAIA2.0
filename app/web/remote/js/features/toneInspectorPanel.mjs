/**
 * NAI Inspector — 결과 화면 왼쪽 아래, 시드 알약 옆에 떠 있는 접이식 판.
 *
 * 무엇을 하나: 지금 화면의 그림 한 장을 재서
 *   1. RGB 로 어느 쪽에 얼마나 치우쳤는지
 *   2. 밝기 · 채도 · 선 같은 축이 기준값에서 얼마나 플러스 / 마이너스인지
 *   3. 벗어난 쪽마다 어떤 보정(프롬프트 · 네거티브 태그)이 있는지
 * 를 보여 준다. **판정하지 않는다** — 기준값은 표본의 가운데일 뿐이고, 고칠지는 사용자가 고른다.
 *
 * 재는 일 · 추천 · 프롬프트 고치기는 전부 서버가 한다(`/api/inspect/tone/*`). 여기는 그린다.
 *
 * ⚠️ 접혀 있으면 **재지 않는다.** 한 장을 재는 데 0.3초쯤 걸리는 계산이라, 켜 두기만 한 사람의
 *    생성마다 돌리지 않는다. 펼쳤을 때와, 펼쳐 둔 채 화면의 그림이 바뀔 때만 잰다.
 * ⚠️ 응답은 늦게 올 수 있다. 요청마다 번호를 매겨 **마지막 요청의 답만** 그린다 — 안 그러면
 *    히스토리를 빠르게 넘길 때 앞 그림의 수치가 뒤 그림 위에 앉는다.
 */

/** 축 막대가 담는 범위(거리 단위). ±1 이 표준 대역의 끝이다. */
const BAR_RANGE = 2.5;
/** RGB 한 채널이 이만큼(거리) 벗어나야 "치우쳤다" 고 말한다. */
const RGB_SPEAK = 0.5;

const EVIDENCE_LABEL = {
  validated_30: '30장 검증',
  single_seed: '한 시드',
  user_report: '사용자 발견',
};

const FIELD_LABEL = {
  pre_prompt: 'prefix',
  prompt: '프롬프트',
  post_prompt: 'postfix',
  negative_prompt: '네거티브',
};

const RGB_ROWS = [
  {label: '전체', ids: ['rgb_r', 'rgb_g', 'rgb_b'], mean: 'overall'},
  {label: '밝은 곳', ids: ['rgb_hi_r', 'rgb_hi_g', 'rgb_hi_b'], mean: 'highlights'},
];
const CHANNELS = ['r', 'g', 'b'];

/** 세 채널의 벗어난 방향을 한 낱말로. 높은 채널과 낮은 채널의 조합으로 정한다. */
function rgbWord(distances) {
  const up = CHANNELS.filter((_, i) => (distances[i] ?? 0) >= RGB_SPEAK);
  const down = CHANNELS.filter((_, i) => (distances[i] ?? 0) <= -RGB_SPEAK);
  const key = `${up.join('')}|${down.join('')}`;
  const table = {
    'r|': '붉은 쪽', 'r|g': '붉은 쪽', 'r|b': '주황 · 누런 쪽', 'r|gb': '붉은 쪽',
    'g|': '초록 쪽', 'g|r': '초록 쪽', 'g|b': '연두 쪽', 'g|rb': '초록 쪽',
    'b|': '푸른 쪽', 'b|r': '푸른 쪽', 'b|g': '보라 쪽', 'b|rg': '푸른 쪽',
    'rg|': '누런 쪽', 'rg|b': '누런 쪽',
    'gb|': '청록 쪽', 'gb|r': '청록 쪽',
    'rb|': '자주 쪽', 'rb|g': '자주 쪽',
    '|r': '청록 쪽', '|g': '자주 쪽', '|b': '누런 쪽',
    '|rg': '푸른 쪽', '|gb': '붉은 쪽', '|rb': '초록 쪽',
  };
  return table[key] || '';
}

function clamp(value, low, high) {
  return Math.max(low, Math.min(high, value));
}

function signed(value, digits) {
  if (value == null || !Number.isFinite(value)) return '–';
  const text = Math.abs(value).toFixed(digits);
  if (Number(text) === 0) return (0).toFixed(digits);
  return `${value < 0 ? '−' : '+'}${text}`;
}

export function createToneInspectorPanel({
  document,
  escHtml,
  // () => string   지금 화면에 있는 그림의 히스토리 id. 히스토리 항목이 아니면 ''.
  getHistoryId = () => '',
  // () => {prompt, negative_prompt}   다음 생성에 나갈 글(메인 칸 · 네거티브 칸).
  getFields = () => ({prompt: '', negative_prompt: ''}),
  // () => {pre_prompt, post_prompt} | null   프리셋의 prefix · postfix. 아직 모르면 null.
  getPresetFields = () => null,
  // (changes: [{field, before, after}]) => void   메인 칸 · 네거티브 칸에 넣는다.
  applyFields = () => {},
  // (changes: [{field, before, after}]) => void   프리셋의 prefix · postfix 에 넣는다.
  applyPresetFields = () => {},
  // () => void   프리셋의 prefix · postfix 를 아직 모르면 청한다(답은 `getPresetFields` 로 읽힌다).
  requestPresetFields = () => {},
  // 열림 · postfix 반영 여부를 기억한다(이 브라우저).
  loadPrefs = () => ({}),
  savePrefs = () => {},
  showToast = () => {},
  fetchImpl = (...args) => fetch(...args),
} = {}) {
  const el = document.createElement('div');
  el.className = 'ti-float';
  el.hidden = true;
  el.innerHTML = `
    <div class="ti-box" data-ti-box>
      <div class="ti-body" data-ti-body hidden></div>
      <div class="ti-head-row">
        <button type="button" class="ti-head" data-ti-toggle aria-expanded="false"
                data-naia-title="NAI Inspector · 지금 그림의 색 · 선이 기준값에서 얼마나 벗어났는지와 보정 태그">
          <span class="ti-caret">▸</span><span class="ti-title">INSPECTOR</span>
          <span class="ti-count" data-ti-count hidden></span>
        </button>
        <button type="button" class="ti-refresh" data-ti-refresh hidden
                data-naia-title="지금 그림을 다시 잰다">↻</button>
      </div>
    </div>`;
  const box = el.querySelector('[data-ti-box]');
  const body = el.querySelector('[data-ti-body]');
  const toggle = el.querySelector('[data-ti-toggle]');
  const caret = el.querySelector('.ti-caret');
  const countEl = el.querySelector('[data-ti-count]');
  const refreshBtn = el.querySelector('[data-ti-refresh]');

  const prefs = {open: false, toPreset: false, ...(loadPrefs() || {})};
  let enabled = false;
  let open = Boolean(prefs.open);
  let seq = 0;                 // 요청 번호 — 마지막 요청의 답만 그린다
  let shownId = '';            // 지금 판에 그려진 그림
  let data = null;             // {inspection, advice}
  let status = 'idle';         // idle | loading | ready | error | none
  let errorText = '';
  let busyApply = '';          // 적용 중인 추천 id
  let showRest = false;        // 크게 벗어나지 않은 축의 보정도 펼쳐 보는가

  function remember() {
    savePrefs({open, toPreset: Boolean(prefs.toPreset)});
  }

  async function postJson(url, payload) {
    const response = await fetchImpl(url, {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload),
    });
    const json = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(json.error || `HTTP ${response.status}`);
    return json;
  }

  async function getJson(url) {
    const response = await fetchImpl(url);
    const json = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(json.error || `HTTP ${response.status}`);
    return json;
  }

  function currentFields() {
    const fields = getFields() || {};
    return {prompt: String(fields.prompt || ''), negative_prompt: String(fields.negative_prompt || '')};
  }

  /** 지금 그림을 잰다. `force` 가 아니면 이미 그려 둔 그림은 다시 재지 않는다. */
  async function refresh({force = false} = {}) {
    if (!enabled || !open) return;
    const id = String(getHistoryId() || '');
    if (!id) {
      seq += 1;
      shownId = ''; data = null; status = 'none';
      render();
      return;
    }
    if (!force && id === shownId && status === 'ready') return;
    const mine = ++seq;
    status = 'loading';
    if (id !== shownId) data = null;
    shownId = id;
    render();
    try {
      // 측정은 서버가 id 로 기억한다 — 둘을 같이 보내도 재는 것은 한 번이다.
      const [inspection, advice] = await Promise.all([
        getJson(`/api/inspect/tone/history/${encodeURIComponent(id)}`),
        postJson('/api/inspect/tone/advise', {history_id: id, fields: currentFields()}),
      ]);
      if (mine !== seq) return;
      data = {inspection, advice};
      status = 'ready';
    } catch (error) {
      if (mine !== seq) return;
      status = 'error';
      errorText = String(error?.message || error || '');
    }
    render();
  }

  /** 프롬프트가 바뀐 뒤 추천의 상태(적용됨 등)만 다시 받는다 — 그림은 다시 재지 않는다. */
  async function refreshAdvice() {
    if (!enabled || !open || !shownId || !data) return;
    const mine = ++seq;
    try {
      const advice = await postJson('/api/inspect/tone/advise', {history_id: shownId, fields: currentFields()});
      if (mine !== seq) return;
      data = {...data, advice};
      render();
    } catch (_) { /* 다음 갱신 때 다시 받는다 */ }
  }

  async function applySuggestion(id, level) {
    if (busyApply) return;
    busyApply = id;
    render();
    try {
      const main = await postJson('/api/inspect/tone/apply', {
        fields: currentFields(), suggestion_id: id, level: level || null,
      });
      const mainChanges = Array.isArray(main.changes) ? main.changes : [];
      let presetChanges = [];
      if (prefs.toPreset) {
        const preset = getPresetFields();
        if (preset) {
          // 프리셋의 prefix · postfix 는 메인 칸과 **따로** 고친다. 메인 칸에는 이미 그 둘이 펼쳐져 들어 있어서,
          // 한 번에 이어 붙여 보내면 같은 태그를 두 번 세게 된다.
          const result = await postJson('/api/inspect/tone/apply', {
            fields: {pre_prompt: String(preset.pre_prompt || ''), post_prompt: String(preset.post_prompt || '')},
            suggestion_id: id, level: level || null,
          });
          presetChanges = (Array.isArray(result.changes) ? result.changes : [])
            .filter(change => change.field === 'pre_prompt' || change.field === 'post_prompt');
        } else {
          showToast('프리셋의 postfix 를 아직 읽지 못했습니다 — 프롬프트 칸에만 반영했습니다', 'info');
        }
      }
      if (mainChanges.length) applyFields(mainChanges);
      if (presetChanges.length) applyPresetFields(presetChanges);
      if (!mainChanges.length && !presetChanges.length) {
        showToast('이미 반영되어 있습니다', 'info');
      } else {
        const where = [...new Set([...mainChanges, ...presetChanges].map(change => FIELD_LABEL[change.field] || change.field))];
        showToast(`${where.join(' · ')}에 반영했습니다 — 다음 생성부터 적용됩니다`, 'success');
      }
    } catch (error) {
      showToast(`보정을 반영하지 못했습니다: ${String(error?.message || error)}`, 'error');
    }
    busyApply = '';
    await refreshAdvice();
    render();
  }

  // ── 그리기 ────────────────────────────────────────────────────────────────

  function axisMap() {
    const axes = data?.inspection?.axes || data?.advice?.axes || [];
    return new Map(axes.map(axis => [axis.id, axis]));
  }

  function barHtml(distance, {cls = ''} = {}) {
    if (distance == null || !Number.isFinite(distance)) {
      return `<span class="ti-bar is-empty${cls ? ` ${cls}` : ''}"></span>`;
    }
    const shown = clamp(distance, -BAR_RANGE, BAR_RANGE);
    const half = Math.abs(shown) / BAR_RANGE * 50;
    const left = shown < 0 ? 50 - half : 50;
    const over = Math.abs(distance) >= 1 ? ' is-out' : '';
    const edge = Math.abs(distance) > BAR_RANGE ? ' is-clipped' : '';
    return `<span class="ti-bar${over}${edge}${cls ? ` ${cls}` : ''}">`
      + `<span class="ti-bar-band"></span>`
      + `<span class="ti-bar-fill" style="left:${left.toFixed(1)}%;width:${half.toFixed(1)}%"></span>`
      + `<span class="ti-bar-zero"></span></span>`;
  }

  function rgbSection(axes) {
    const rgb = data?.inspection?.rgb || {};
    const rows = RGB_ROWS.map(row => {
      const items = row.ids.map(id => axes.get(id));
      if (items.some(item => !item)) return '';
      const distances = items.map(item => item.distance);
      const mean = rgb[row.mean]?.mean;
      const swatch = mean
        ? `<span class="ti-swatch" style="background:rgb(${Math.round(mean.r)},${Math.round(mean.g)},${Math.round(mean.b)})"`
          + ` data-naia-title="${escHtml(`${row.label}의 평균색 · R ${Math.round(mean.r)} G ${Math.round(mean.g)} B ${Math.round(mean.b)}`)}"></span>`
        : '<span class="ti-swatch is-empty"></span>';
      const word = rgbWord(distances);
      const cells = items.map((item, index) => {
        const delta = item.value == null ? null : item.value - item.zero;
        return `<span class="ti-rgb-cell" data-naia-title="${escHtml(`${CHANNELS[index].toUpperCase()} 치우침 ${item.value == null ? '–' : item.value.toFixed(1)} · 기준 ${item.zero.toFixed(1)}`)}">`
          + `<span class="ti-rgb-name is-${CHANNELS[index]}">${CHANNELS[index].toUpperCase()}</span>`
          + barHtml(item.distance, {cls: `is-${CHANNELS[index]}`})
          + `<span class="ti-num">${escHtml(signed(delta, 1))}</span></span>`;
      }).join('');
      return `<div class="ti-rgb-row">`
        + `<div class="ti-rgb-head">${swatch}<span class="ti-rgb-label">${escHtml(row.label)}</span>`
        + `<span class="ti-rgb-word${word ? '' : ' is-flat'}">${escHtml(word || '치우침 없음')}</span></div>`
        + `<div class="ti-rgb-cells">${cells}</div></div>`;
    }).join('');
    if (!rows) return '';
    return `<section class="ti-sec"><h4 class="ti-sec-title">RGB 치우침 <span class="ti-sec-note">기준값 대비</span></h4>${rows}</section>`;
  }

  function axesSection(axes) {
    const primary = [...axes.values()].filter(axis => axis.primary);
    if (!primary.length) return '';
    const rows = primary.map(axis => {
      const digits = Number.isInteger(axis.digits) ? axis.digits : 1;
      const delta = axis.value == null ? null : axis.value - axis.zero;
      const tip = [
        `${axis.label} ${axis.value == null ? '–' : axis.value.toFixed(digits)} · 기준 ${axis.zero.toFixed(digits)}`
          + ` (표본의 가운데 75% = ${axis.low.toFixed(digits)} ~ ${axis.high.toFixed(digits)})`,
        ...(axis.cautions || []),
      ].join('\n');
      return `<div class="ti-axis${axis.reliable === false ? ' is-unsure' : ''}" data-naia-title="${escHtml(tip)}">`
        + `<span class="ti-axis-label">${escHtml(axis.label)}${axis.reliable === false ? '<span class="ti-unsure">?</span>' : ''}</span>`
        + barHtml(axis.distance)
        + `<span class="ti-num">${escHtml(axis.value == null ? '–' : axis.value.toFixed(digits))}`
        + `<span class="ti-delta">${escHtml(signed(delta, digits))}</span></span></div>`;
    }).join('');
    return `<section class="ti-sec"><h4 class="ti-sec-title">기준값 대비 <span class="ti-sec-note">막대의 옅은 띠 = 표본의 가운데 75%</span></h4>${rows}</section>`;
  }

  function actionText(action) {
    const where = FIELD_LABEL[action.field] || action.field;
    const tags = (action.tags || []).join(', ');
    if (action.op === 'set_weight') {
      const from = action.from_weight == null ? '' : `${Number(action.from_weight)} → `;
      return `${where} · ${tags} ${from}${Number(action.weight)}`;
    }
    return `${where} + ${tags}`;
  }

  function suggestionHtml(suggestion, axes) {
    const axis = axes.get(suggestion.axis);
    const evidence = suggestion.evidence || {};
    const applied = suggestion.state === 'already_applied';
    const busy = busyApply === suggestion.id;
    const actions = (suggestion.actions || []).map(action =>
      `<span class="ti-act is-${action.field === 'negative_prompt' ? 'neg' : 'pos'}">${escHtml(actionText(action))}</span>`).join('');
    const cautions = (suggestion.cautions || []).map(text => `<li>${escHtml(text)}</li>`).join('');
    const verify = (suggestion.verify || []).map(id => axes.get(id)?.label).filter(Boolean);
    const levels = (suggestion.levels || []).map(level =>
      `<button type="button" class="ti-btn" data-ti-apply="${escHtml(suggestion.id)}" data-ti-level="${escHtml(level.id)}"`
      + `${busyApply ? ' disabled' : ''}${level.state === 'already_applied' ? ' disabled' : ''}>${escHtml(level.label || level.id)}</button>`).join('');
    return `<div class="ti-sug${suggestion.prominent ? ' is-prominent' : ''}${applied ? ' is-applied' : ''}">`
      + `<div class="ti-sug-head"><span class="ti-sug-title">${escHtml(suggestion.title || suggestion.id)}</span>`
      + `<span class="ti-sug-axis">${escHtml(axis?.label || suggestion.axis)} ${escHtml(signed(suggestion.distance, 1))}</span>`
      + `<span class="ti-ev is-${escHtml(evidence.level || '')}" data-naia-title="${escHtml(evidence.note || '')}">`
      + `${escHtml(EVIDENCE_LABEL[evidence.level] || evidence.level || '')}</span></div>`
      + (actions ? `<div class="ti-acts">${actions}</div>` : '')
      + (cautions || verify.length
        ? `<ul class="ti-cautions">${cautions}${verify.length ? `<li>반영한 뒤 ${escHtml(verify.join(' · '))}도 같이 본다</li>` : ''}</ul>` : '')
      + `<div class="ti-sug-foot">`
      + (applied ? '<span class="ti-state">반영되어 있음</span>'
        : `<button type="button" class="ti-btn is-primary" data-ti-apply="${escHtml(suggestion.id)}"${busyApply ? ' disabled' : ''}>`
          + `${busy ? '반영 중…' : (suggestion.state === 'partly_applied' ? '나머지 반영' : '반영')}</button>`)
      + levels + `</div></div>`;
  }

  function adviceSection(axes) {
    const advice = data?.advice || {};
    const suggestions = Array.isArray(advice.suggestions) ? advice.suggestions : [];
    const warnings = Array.isArray(advice.warnings) ? advice.warnings : [];
    const warningHtml = warnings.map(warning =>
      `<div class="ti-warn">${escHtml(FIELD_LABEL[warning.field] || warning.field)} · `
      + `${escHtml(`${Number(warning.weight)}::${(warning.tags || []).join(', ')}`)} — ${escHtml(warning.message || '')}</div>`).join('');
    // 먼저 보이는 것 = 표준 대역 밖으로 벗어난 축의 보정. 대역 안의 것과, 믿기 어려운 축(선이 사라진 그림의
    // 선 굵기)에 걸린 것은 접어 둔다 - 고를 수는 있어야 하지만 먼저 읽을 것은 아니다.
    // 같은 축 안의 차례(약한 것 먼저)는 서버가 준 대로 둔다.
    const isMain = suggestion => suggestion.prominent && axes.get(suggestion.axis)?.reliable !== false;
    const main = suggestions.filter(isMain);
    const rest = suggestions.filter(suggestion => !isMain(suggestion));
    const mainHtml = main.map(suggestion => suggestionHtml(suggestion, axes)).join('');
    const restHtml = rest.length
      ? `<button type="button" class="ti-more" data-ti-more aria-expanded="${showRest}">`
        + `<span class="ti-caret">${showRest ? '▾' : '▸'}</span>크게 벗어나지 않은 축의 보정 ${rest.length}개</button>`
        + (showRest ? rest.map(suggestion => suggestionHtml(suggestion, axes)).join('') : '')
      : '';
    const list = (mainHtml || (rest.length ? '<div class="ti-empty">크게 벗어난 축이 없습니다.</div>' : '')) + restHtml;
    const footer = `<label class="ti-preset" data-naia-title="켜면 프리셋의 postfix 도 같이 고친다 — Random 으로 프롬프트를 새로 뽑아도 남는다. 끄면 지금 프롬프트 칸에만 반영한다.">`
      + `<input type="checkbox" data-ti-preset${prefs.toPreset ? ' checked' : ''}>`
      + `<span>프리셋 postfix 에도 반영</span></label>`;
    return `<section class="ti-sec"><h4 class="ti-sec-title">보정 <span class="ti-sec-note">다음 생성부터 적용</span></h4>`
      + warningHtml
      + (list || '<div class="ti-empty">이 그림에 권할 보정이 없습니다.</div>')
      + footer + `</section>`;
  }

  function render() {
    box.classList.toggle('is-open', open);
    toggle.setAttribute('aria-expanded', String(open));
    caret.textContent = open ? '▾' : '▸';
    body.hidden = !open;
    refreshBtn.hidden = !open;
    const prominent = (data?.advice?.suggestions || []).filter(s => s.prominent && s.state !== 'already_applied').length;
    countEl.hidden = !(open && status === 'ready' && prominent > 0);
    countEl.textContent = prominent > 0 ? String(prominent) : '';
    if (!open) return;
    if (status === 'none') {
      body.innerHTML = '<div class="ti-empty">잴 그림이 없습니다. 히스토리에 있는 그림을 화면에 띄우면 잽니다.</div>';
      return;
    }
    if (status === 'error') {
      body.innerHTML = `<div class="ti-empty is-error">재지 못했습니다: ${escHtml(errorText)}</div>`;
      return;
    }
    if (!data) {
      body.innerHTML = '<div class="ti-empty">재는 중…</div>';
      return;
    }
    const axes = axisMap();
    const keepScroll = body.scrollTop;
    body.classList.toggle('is-loading', status === 'loading');
    body.innerHTML = rgbSection(axes) + axesSection(axes) + adviceSection(axes);
    body.scrollTop = keepScroll;
  }

  // ── 이벤트 ────────────────────────────────────────────────────────────────

  el.addEventListener('click', event => {
    if (event.target.closest('[data-ti-toggle]')) {
      setOpen(!open);
      return;
    }
    if (event.target.closest('[data-ti-refresh]')) {
      refresh({force: true});
      return;
    }
    if (event.target.closest('[data-ti-more]')) {
      showRest = !showRest;
      render();
      return;
    }
    const apply = event.target.closest('[data-ti-apply]');
    if (apply && !apply.disabled) {
      applySuggestion(apply.dataset.tiApply, apply.dataset.tiLevel || null);
    }
  });
  el.addEventListener('change', event => {
    const preset = event.target.closest('[data-ti-preset]');
    if (!preset) return;
    prefs.toPreset = Boolean(preset.checked);
    remember();
    // 반영을 누를 때는 값이 와 있어야 한다 - 켜는 순간 미리 청해 둔다.
    if (prefs.toPreset) requestPresetFields();
  });

  function setOpen(next) {
    open = Boolean(next);
    remember();
    render();
    if (open) refresh();
  }

  function setEnabled(next) {
    enabled = Boolean(next);
    el.hidden = !enabled;
    if (enabled) {
      if (prefs.toPreset) requestPresetFields();
      render();
      if (open) refresh();
    }
  }

  render();

  return {
    element: el,
    setEnabled,
    isEnabled: () => enabled,
    setOpen,
    isOpen: () => open,
    /** 화면의 그림이 바뀌었다 — 펼쳐져 있을 때만 다시 잰다. */
    onImageChanged: () => refresh(),
    /** 프롬프트 · 네거티브가 바뀌었다 — 추천의 상태만 다시 받는다. */
    onFieldsChanged: () => refreshAdvice(),
  };
}
