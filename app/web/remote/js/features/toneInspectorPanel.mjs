/**
 * NAI Inspector — 결과 화면 왼쪽 아래, 시드 알약 옆에 떠 있는 접이식 판.
 *
 * 무엇을 하나: 지금 화면의 그림 한 장을 재서
 *   1. RGB 로 어느 쪽에 얼마나 치우쳤는지
 *   2. 밝기 · 채도 · 선 같은 축이 기준값에서 몇 % 플러스 / 마이너스인지
 *   3. 벗어난 쪽마다 어떤 보정(프롬프트 · 네거티브 태그)이 있는지
 * 를 보여 준다. **판정하지 않는다** — 기준값은 표본의 가운데일 뿐이고, 고칠지는 사용자가 고른다.
 *
 * 보정은 **바로 반영하지 않는다**(사용자 지정 2026-10-03). 해 볼 보정마다 세기를 고르고 맨 아래의 [시험 생성] 을 누르면
 * 그 그림을 같은 시드 · 같은 설정으로, 고른 보정들만 얹어 한 장 다시 뽑는다 — 프롬프트 칸과 프리셋은 그대로다.
 * 단추는 하나다: 카드마다 두면 같은 단추가 줄줄이 반복된다. 근거 · 주의도 카드에 적지 않고 제목의 툴팁에 둔다.
 * 결과가 오면 전후를 견줘 보여 주고, 마음에 들 때 [프롬프트에 반영] 으로 지금 프롬프트에 넣는다.
 *
 * 펼쳐도 **기본은 결과만** 보인다(사용자 지정 2026-10-03: 그림을 너무 많이 가린다). 보정은 판에 마우스를 가까이 대면 뜬다.
 * 진행 중이거나 끝난 시험의 결과는 마우스가 없어도 보인다 — 그걸 보려고 시험한 것이다.
 *
 * 재는 일 · 추천 · 프롬프트 고치기 · 시험 생성 요청은 전부 서버가 한다(`/api/inspect/tone/*`). 여기는 그린다.
 *
 * ⚠️ 접혀 있으면 **재지 않는다.** 한 장을 재는 데 0.3초쯤 걸리는 계산이라, 켜 두기만 한 사람의
 *    생성마다 돌리지 않는다. 펼쳤을 때와, 펼쳐 둔 채 화면의 그림이 바뀔 때만 잰다.
 * ⚠️ 응답은 늦게 올 수 있다. 요청마다 번호를 매겨 **마지막 요청의 답만** 그린다 — 안 그러면
 *    히스토리를 빠르게 넘길 때 앞 그림의 수치가 뒤 그림 위에 앉는다.
 */

/** 축 막대가 담는 범위(거리 단위). ±1 이 표준 대역의 끝이다. */
const BAR_RANGE = 2.5;
/** 마우스가 판을 벗어난 뒤 보정을 이만큼 더 띄워 둔다 — 스쳐 나갔다 들어올 때 깜빡이지 않게. */
const LEAVE_DELAY_MS = 450;
/**
 * 색 치우침의 세기. 단위는 Lab 의 a* · b* 거리(밝은 영역의 값이 기준값에서 떨어진 정도)다.
 * ⚠️ 대역 반폭으로 나눈 '거리' 로 재지 않는다 — 누런 기의 아래쪽 대역이 좁아서(0.0 ~ 2.0), 흰색이 깨끗한 보통 그림이
 *    전부 "푸른 쪽" 으로 읽힌다(실측: 작가 없는 그림 다섯 중 셋).
 */
const CAST_LEVELS = [[3, ''], [7, '약함'], [14, '뚜렷'], [Infinity, '강함']];
/** a* · b* 평면의 방향을 45도씩 나눈 이름. 0도 = +a(붉은), 90도 = +b(누런). */
const CAST_NAMES = ['붉은', '주황', '누런', '연두', '초록', '청록', '푸른', '보라'];
/** 시험 생성의 결과를 이만큼 기다린다. 넘으면 "오지 않았다" 고 말하고 놓아준다. */
const TRIAL_TIMEOUT_MS = 240000;

/**
 * 퍼센트의 분모. 기본은 **기준값**이다(밝기 66.0 · 기준 69.4 → −5%).
 * 기준값이 0 근처인 축은 그렇게 나누면 숫자가 터진다(누런 기 기준 2.0 → +445%). 그런 축은 눈금의 폭으로 나눈다:
 * Lab 의 a* · b* 는 100, RGB 채널은 255.
 */
const PERCENT_BASIS = {yellow: 100, red: 100};
const RGB_PERCENT_BASIS = 255;

const EVIDENCE_LABEL = {
  validated_30: '30장 검증',
  validated_pairs: '같은 시드 짝 검증',
  single_seed: '한 시드',
  user_report: '사용자 발견',
};

const FIELD_LABEL = {
  pre_prompt: 'prefix',
  prompt: '프롬프트',
  post_prompt: 'postfix',
  negative_prompt: '네거티브',
};

const STRENGTHS = [
  {value: 0.5, label: '약하게'},
  {value: 1, label: '기본'},
  {value: 1.5, label: '세게'},
];

const RGB_ROWS = [
  {label: '전체', ids: ['rgb_r', 'rgb_g', 'rgb_b'], mean: 'overall'},
  {label: '밝은 곳', ids: ['rgb_hi_r', 'rgb_hi_g', 'rgb_hi_b'], mean: 'highlights'},
];
const CHANNELS = ['r', 'g', 'b'];

/**
 * 색이 어느 쪽으로 치우쳤는가 — 밝은 영역(흰색이어야 할 곳)의 a* · b* 가 기준값에서 벗어난 방향과 크기.
 * 그림 전체의 평균색으로 재지 않는다: 머리 · 옷 · 배경의 색이 그대로 실려서 보라를 붉다고, 파랑을 자주라고 읽는다(실측).
 */
function castSummary(axes) {
  const a = axes.get('red');
  const b = axes.get('yellow');
  if (!a || !b || a.value == null || b.value == null) return null;
  const da = a.value - a.zero;
  const db = b.value - b.zero;
  const size = Math.hypot(da, db);
  const angle = (Math.atan2(db, da) * 180 / Math.PI + 360) % 360;
  const level = CAST_LEVELS.find(([limit]) => size < limit)[1];
  // 채도가 낮으면 색 이름보다 '무채색에 가깝다' 가 먼저다 — 가운데 영역으로 본다(흰 배경에 덜 끌린다).
  const chroma = axes.get('center_chroma') || axes.get('chroma');
  return {
    name: size < CAST_LEVELS[0][0] ? '' : CAST_NAMES[Math.floor(((angle + 22.5) % 360) / 45)],
    level,
    size,
    pale: chroma?.distance != null && chroma.distance <= -1,
  };
}

function clamp(value, low, high) {
  return Math.max(low, Math.min(high, value));
}

/** 부호 붙은 퍼센트. 0 으로 반올림되면 부호를 떼고 `0%`. */
function signedPercent(value) {
  if (value == null || !Number.isFinite(value)) return '–';
  const rounded = Math.round(value);
  if (rounded === 0) return '0%';
  return `${rounded < 0 ? '−' : '+'}${Math.abs(rounded)}%`;
}

/** 축 값이 기준값에서 몇 % 벗어났는가. */
function axisPercent(axis, basisOverride) {
  if (!axis || axis.value == null) return null;
  const basis = basisOverride ?? PERCENT_BASIS[axis.id] ?? Math.abs(axis.zero);
  if (!basis) return null;
  return (axis.value - axis.zero) / basis * 100;
}

/** 가중치를 글로. `0.5` · `-2` · `1.25`. */
function weightText(weight) {
  return String(Number(Number(weight).toFixed(2)));
}

/** 세기를 곱한 actions — 서버의 `scaled_actions` 와 같은 규칙(화면에 미리 보여 주려고 여기서도 계산한다). */
function scaledActions(actions, strength) {
  if (strength === 1) return actions;
  return (actions || []).map(action => (action.op === 'set_weight'
    ? {...action, weight: Math.round(action.weight * strength * 100) / 100}
    : {...action, op: 'set_weight', weight: Math.round(strength * 100) / 100}));
}

/** 보정 하나가 프롬프트에 하는 일을 한 줄로. */
function actionPhrase(action) {
  const where = action.field === 'negative_prompt' ? '네거티브' : '프롬프트';
  const tags = (action.tags || []).join(', ');
  if (action.op === 'set_weight') return `${where}에 ${weightText(action.weight)}::${tags} ::`;
  return `${where}에 ${tags}`;
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
  // (message) => Promise<boolean>   유료(Anlas) 시험 생성을 물을 때 쓴다.
  confirmDialog = async message => window.confirm(message),
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
                data-naia-title="NAI Inspector · 지금 그림의 색 · 선이 기준값에서 얼마나 벗어났는지와 보정">
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

  const prefs = {open: false, toPreset: false, pinned: false, ...(loadPrefs() || {})};
  let enabled = false;
  let open = Boolean(prefs.open);
  let seq = 0;                 // 요청 번호 — 마지막 요청의 답만 그린다
  let shownId = '';            // 지금 판에 그려진 그림
  let data = null;             // {inspection, advice}
  let status = 'idle';         // idle | loading | ready | error | none
  let errorText = '';
  let showRest = false;        // 크게 벗어나지 않은 축의 보정도 펼쳐 보는가
  const choices = new Map();   // 보정 id -> {strength, level}  (카드에서 고른 세기)
  // 시험 생성 하나. {id, title, level, strength, requestId, sourceId, before: Map, state: 'queued'|'done'|'lost', afterId}
  let trial = null;
  let trialTimer = 0;
  let busy = false;            // 시험 생성 요청 · 반영을 보내는 중
  let near = false;            // 마우스(또는 초점)가 판 위에 있다 — 그동안 보정을 띄운다
  let pinned = Boolean(prefs.pinned);   // 보정을 마우스 없이도 띄워 둔다
  let leaveTimer = 0;

  function remember() {
    savePrefs({open, toPreset: Boolean(prefs.toPreset), pinned});
  }

  async function postJson(url, payload, {allowStatus = []} = {}) {
    const response = await fetchImpl(url, {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload),
    });
    const json = await response.json().catch(() => ({}));
    if (!response.ok && !allowStatus.includes(response.status)) throw new Error(json.error || `HTTP ${response.status}`);
    return {status: response.status, json};
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

  function choiceOf(id) {
    // strength 가 null 이면 고르지 않은 것이다 - 시험 생성에 들어가지 않는다.
    if (!choices.has(id)) choices.set(id, {strength: null, level: null});
    return choices.get(id);
  }

  function primaryValues(inspection) {
    // 밝기도 화면의 축이다(10-04 에 되돌렸다 - 어두운 그림을 밝히는 보정이 생겼다). 전후 비교는 화면의 축 그대로 본다.
    return new Map((inspection?.axes || []).filter(axis => axis.primary).map(axis => [axis.id, axis]));
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
        postJson('/api/inspect/tone/advise', {history_id: id, fields: currentFields()}).then(result => result.json),
      ]);
      if (mine !== seq) return;
      data = {inspection, advice};
      status = 'ready';
      // 이 그림이 내가 청한 시험 생성의 결과인가.
      if (trial && trial.state === 'queued' && inspection.generation_request_id
          && inspection.generation_request_id === trial.requestId) {
        clearTimeout(trialTimer);
        trial = {...trial, state: 'done', afterId: id, after: primaryValues(inspection)};
      }
    } catch (error) {
      if (mine !== seq) return;
      status = 'error';
      errorText = String(error?.message || error || '');
    }
    render();
  }

  /** 프롬프트가 바뀐 뒤 추천의 상태(반영되어 있음 등)만 다시 받는다 — 그림은 다시 재지 않는다. */
  async function refreshAdvice() {
    if (!enabled || !open || !shownId || !data) return;
    const mine = ++seq;
    try {
      const {json: advice} = await postJson('/api/inspect/tone/advise', {history_id: shownId, fields: currentFields()});
      if (mine !== seq) return;
      data = {...data, advice};
      render();
    } catch (_) { /* 다음 갱신 때 다시 받는다 */ }
  }

  /** 세기를 고른 보정들. 지금 그림에 해당하는 것만. */
  function chosenItems() {
    return (data?.advice?.suggestions || [])
      .map(suggestion => ({suggestion, choice: choiceOf(suggestion.id)}))
      .filter(({choice}) => choice.strength != null)
      .map(({suggestion, choice}) => ({
        suggestion_id: suggestion.id, level: choice.level, strength: choice.strength,
        title: suggestion.title || suggestion.id,
      }));
  }

  /** 고른 보정들을 얹어 같은 시드로 한 장 시험 생성한다. 프롬프트 칸은 건드리지 않는다. */
  async function startTrial() {
    if (busy || (trial && trial.state === 'queued') || !shownId || !data) return;
    const chosen = chosenItems();
    if (!chosen.length) return;
    const items = chosen.map(({suggestion_id, level, strength}) => ({suggestion_id, level, strength}));
    const payload = {history_id: shownId, items};
    busy = true;
    render();
    try {
      let {status: code, json} = await postJson('/api/inspect/tone/trial', payload, {allowStatus: [409]});
      if (code === 409 && json.needs_confirmation) {
        const ok = await confirmDialog(
          `이 시험 생성은 무료 구간이 아닙니다 — Anlas 약 ${json.anlas_cost} 을 씁니다. 계속할까요?`);
        if (!ok) { busy = false; render(); return; }
        ({status: code, json} = await postJson('/api/inspect/tone/trial', {...payload, allow_paid: true}));
      }
      if (!json.ok) throw new Error(json.error || '시험 생성을 시작하지 못했습니다');
      trial = {
        items, title: chosen.map(item => item.title).join(' + '),
        requestId: String(json.generation_request_id || ''), sourceId: shownId,
        before: primaryValues(data.inspection), state: 'queued', afterId: '', after: null,
      };
      clearTimeout(trialTimer);
      trialTimer = setTimeout(() => {
        if (trial && trial.state === 'queued') { trial = {...trial, state: 'lost'}; render(); }
      }, TRIAL_TIMEOUT_MS);
      showToast('같은 시드로 시험 생성을 시작했습니다 — 프롬프트 칸은 그대로입니다', 'info');
    } catch (error) {
      showToast(`시험 생성을 시작하지 못했습니다: ${String(error?.message || error)}`, 'error');
    }
    busy = false;
    render();
  }

  /** 시험해 본 보정들을 지금 프롬프트에 넣는다(같은 세기 · 같은 단계로). */
  async function applyTrial() {
    if (busy || !trial || trial.state !== 'done') return;
    busy = true;
    render();
    try {
      const {json: main} = await postJson('/api/inspect/tone/apply', {fields: currentFields(), items: trial.items});
      const mainChanges = Array.isArray(main.changes) ? main.changes : [];
      let presetChanges = [];
      if (prefs.toPreset) {
        const preset = getPresetFields();
        if (preset) {
          // 프리셋의 prefix · postfix 는 메인 칸과 **따로** 고친다. 메인 칸에는 이미 그 둘이 펼쳐져 들어 있어서,
          // 한 번에 이어 붙여 보내면 같은 태그를 두 번 세게 된다.
          const {json: result} = await postJson('/api/inspect/tone/apply', {
            fields: {pre_prompt: String(preset.pre_prompt || ''), post_prompt: String(preset.post_prompt || '')},
            items: trial.items,
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
      trial = {...trial, applied: true};
    } catch (error) {
      showToast(`보정을 반영하지 못했습니다: ${String(error?.message || error)}`, 'error');
    }
    busy = false;
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
    return `<span class="ti-bar${over}${cls ? ` ${cls}` : ''}">`
      + `<span class="ti-bar-band"></span>`
      + `<span class="ti-bar-fill" style="left:${left.toFixed(1)}%;width:${half.toFixed(1)}%"></span>`
      + `<span class="ti-bar-zero"></span></span>`;
  }

  function rgbSection(axes) {
    const rgb = data?.inspection?.rgb || {};
    const rows = RGB_ROWS.map(row => {
      const items = row.ids.map(id => axes.get(id));
      if (items.some(item => !item)) return '';
      const mean = rgb[row.mean]?.mean;
      const swatch = mean
        ? `<span class="ti-swatch" style="background:rgb(${Math.round(mean.r)},${Math.round(mean.g)},${Math.round(mean.b)})"`
          + ` data-naia-title="${escHtml(`${row.label}의 평균색 · R ${Math.round(mean.r)} G ${Math.round(mean.g)} B ${Math.round(mean.b)}`)}"></span>`
        : '<span class="ti-swatch is-empty"></span>';
      const cells = items.map((item, index) => {
        const name = CHANNELS[index].toUpperCase();
        return `<span class="ti-rgb-cell" data-naia-title="${escHtml(`${name} 가 기준보다 ${signedPercent(axisPercent(item, RGB_PERCENT_BASIS))} (0~255 눈금 기준)`)}">`
          + `<span class="ti-rgb-name is-${CHANNELS[index]}">${name}</span>`
          + barHtml(item.distance, {cls: `is-${CHANNELS[index]}`})
          + `<span class="ti-num">${escHtml(signedPercent(axisPercent(item, RGB_PERCENT_BASIS)))}</span></span>`;
      }).join('');
      return `<div class="ti-rgb-row">`
        + `<div class="ti-rgb-head">${swatch}<span class="ti-rgb-label">${escHtml(row.label)}</span></div>`
        + `<div class="ti-rgb-cells">${cells}</div></div>`;
    }).join('');
    if (!rows) return '';
    // 한 낱말 요약 — 어느 색 쪽으로, 얼마나. RGB 줄은 그 아래의 세부다.
    const cast = castSummary(axes);
    const castText = !cast ? '' : [
      cast.name ? `${cast.name} 쪽${cast.level ? ` · ${cast.level}` : ''}` : '치우침 없음',
      cast.pale ? '무채색에 가까움' : '',
    ].filter(Boolean).join(' · ');
    const castHtml = cast
      ? `<span class="ti-cast${cast.name || cast.pale ? '' : ' is-flat'}" data-naia-title="${escHtml('밝은 영역의 색이 기준에서 벗어난 방향 · 무채색 여부는 가운데 영역의 채도로 본다')}">${escHtml(castText)}</span>`
      : '';
    return `<section class="ti-sec"><h4 class="ti-sec-title">색 치우침 ${castHtml}</h4>${rows}</section>`;
  }

  /** 축에 마우스를 올리면 뜨는 안내 — 높을 때 · 낮을 때 무엇을 하면 되는가. */
  function axisGuide(axis) {
    const guide = Array.isArray(data?.advice?.guide) ? data.advice.guide : [];
    const lines = side => {
      const rules = guide.filter(rule => rule.axis === axis.id && rule.side === side);
      if (!rules.length) return '권할 보정이 없습니다';
      return rules.map(rule => (rule.actions || []).map(action => `${actionPhrase(action)} 추가`).join(', ')).join('  /  또는  ');
    };
    const digits = Number.isInteger(axis.digits) ? axis.digits : 1;
    return [
      `높을 때 : ${lines('high')}`,
      `낮을 때 : ${lines('low')}`,
      `지금 ${axis.value == null ? '–' : axis.value.toFixed(digits)} · 기준 ${axis.zero.toFixed(digits)}`,
      ...(axis.cautions || []).map(text => `※ ${text}`),
    ].join('\n');
  }

  function axesSection(axes) {
    const primary = [...axes.values()].filter(axis => axis.primary);
    if (!primary.length) return '';
    const rows = primary.map(axis => {
      const digits = Number.isInteger(axis.digits) ? axis.digits : 1;
      return `<div class="ti-axis${axis.reliable === false ? ' is-unsure' : ''}" data-naia-guide="${escHtml(axisGuide(axis))}">`
        + `<span class="ti-axis-label">${escHtml(axis.label)}${axis.reliable === false ? '<span class="ti-unsure">?</span>' : ''}</span>`
        + barHtml(axis.distance)
        + `<span class="ti-num">${escHtml(axis.value == null ? '–' : axis.value.toFixed(digits))}`
        + `<span class="ti-delta">${escHtml(signedPercent(axisPercent(axis)))}</span></span></div>`;
    }).join('');
    return `<section class="ti-sec"><h4 class="ti-sec-title">기준값 대비 <span class="ti-sec-note">이름에 마우스를 올리면 보정 방법</span></h4>${rows}</section>`;
  }

  // 규칙의 **원래** 모양(그림 · 프롬프트와 무관). `suggestions[].actions` 는 아직 안 들어간 것만 남긴 목록이라,
  // 시험 생성이 실제로 얹는 것을 보여 주려면 안내(guide)의 원본을 쓴다.
  const rules = new Map();
  function indexRules() {
    rules.clear();
    for (const rule of (data?.advice?.guide || [])) rules.set(rule.id, rule);
  }

  function ruleOf(suggestion) {
    return rules.get(suggestion.id) || {actions: suggestion.actions || [], levels: []};
  }

  /** 카드에서 고른 단계 · 세기를 반영한 actions. */
  function chosenActions(suggestion) {
    const choice = choiceOf(suggestion.id);
    const rule = ruleOf(suggestion);
    const level = (rule.levels || []).find(item => item.id === choice.level);
    // 아직 고르지 않은 보정은 기본 세기로 미리 보여 준다.
    return scaledActions((level ? level.actions : rule.actions) || [], choice.strength ?? 1);
  }

  /** 태그까지 바꾸는 단계만 따로 고르게 한다(가중치만 다른 단계는 세기로 충분하다). */
  function tagChangingLevels(suggestion) {
    const rule = ruleOf(suggestion);
    const tags = actions => (actions || []).flatMap(action => action.tags || []).sort().join('|');
    return (rule.levels || []).filter(level => tags(level.actions) !== tags(rule.actions));
  }

  function suggestionHtml(suggestion, axes) {
    const axis = axes.get(suggestion.axis);
    const evidence = suggestion.evidence || {};
    const choice = choiceOf(suggestion.id);
    const chosen = choice.strength != null;
    const chips = chosenActions(suggestion).map(action =>
      `<span class="ti-act is-${action.field === 'negative_prompt' ? 'neg' : 'pos'}">${escHtml(actionPhrase(action))}</span>`).join('');
    const verify = (suggestion.verify || []).map(id => axes.get(id)?.label).filter(Boolean);
    // 근거 · 주의는 카드에 적지 않는다(읽을 것이 너무 많았다) - 제목에 마우스를 올리면 뜬다.
    const tip = [
      `근거 : ${EVIDENCE_LABEL[evidence.level] || evidence.level || '–'}${evidence.note ? ` (${evidence.note})` : ''}`,
      ...(suggestion.cautions || []).map(text => `※ ${text}`),
      ...(verify.length ? [`※ 시험 결과에서 ${verify.join(' · ')}도 같이 본다`] : []),
    ].join('\n');
    const strengths = STRENGTHS.map(step =>
      `<button type="button" class="ti-seg-btn${choice.strength === step.value ? ' is-on' : ''}" data-ti-strength="${step.value}"`
      + ` data-ti-for="${escHtml(suggestion.id)}" aria-pressed="${choice.strength === step.value}">${escHtml(step.label)}</button>`).join('');
    const levels = tagChangingLevels(suggestion).map(level =>
      `<button type="button" class="ti-seg-btn${choice.level === level.id ? ' is-on' : ''}" data-ti-level="${escHtml(level.id)}"`
      + ` data-ti-for="${escHtml(suggestion.id)}" aria-pressed="${choice.level === level.id}">${escHtml(level.label || level.id)}</button>`).join('');
    const present = suggestion.state === 'already_applied' || suggestion.state === 'partly_applied';
    return `<div class="ti-sug${suggestion.prominent ? ' is-prominent' : ''}${chosen ? ' is-chosen' : ''}">`
      + `<div class="ti-sug-head" data-naia-guide="${escHtml(tip)}"><span class="ti-sug-title">${escHtml(suggestion.title || suggestion.id)}</span>`
      + `<span class="ti-sug-axis">${escHtml(axis?.label || suggestion.axis)} ${escHtml(signedPercent(axisPercent(axis)))}</span></div>`
      + (chips ? `<div class="ti-acts">${chips}</div>` : '')
      + `<div class="ti-sug-foot"><span class="ti-seg" role="group" aria-label="세기 — 고르면 시험 생성에 들어간다">${strengths}</span>`
      + (levels ? `<span class="ti-seg" role="group">${levels}</span>` : '') + `</div>`
      + (present ? '<div class="ti-state">이미 존재하는 프롬프트 (가중치 조절 권장)</div>' : '')
      + `</div>`;
  }

  /** 시험 생성의 상태와 결과. 결과가 왔으면 전후를 견주고 [프롬프트에 반영] 을 내놓는다. */
  function trialHtml(axes) {
    if (!trial) return '';
    const head = `<div class="ti-trial-head"><span class="ti-trial-title">시험 · ${escHtml(trial.title)}</span>`
      + `<button type="button" class="ti-trial-close" data-ti-trial-close aria-label="닫기" data-naia-title="이 시험을 접는다">✕</button></div>`;
    if (trial.state === 'queued') {
      return `<div class="ti-trial">${head}<div class="ti-trial-note">같은 시드로 생성하는 중… 결과가 화면에 오면 여기서 견줍니다.</div></div>`;
    }
    if (trial.state === 'lost') {
      return `<div class="ti-trial is-lost">${head}<div class="ti-trial-note">결과가 오지 않았습니다. 큐를 확인하거나 다시 시험해 보세요.</div></div>`;
    }
    const rows = [...(trial.after || new Map()).values()].map(after => {
      const before = trial.before.get(after.id);
      if (!before || before.value == null || after.value == null) return null;
      // 견주는 눈금은 거리(표준 대역의 반폭)다 — 축마다 단위가 달라 값의 차로는 크기를 못 견준다.
      const moved = (after.distance ?? 0) - (before.distance ?? 0);
      return {after, before, moved};
    }).filter(Boolean).sort((a, b) => Math.abs(b.moved) - Math.abs(a.moved)).slice(0, 4);
    const list = rows.map(({after, before, moved}) => {
      const digits = Number.isInteger(after.digits) ? after.digits : 1;
      // 기준값에 가까워졌는가. 같은 쪽에서 0 으로 다가갔으면 가까워진 것이다.
      const closer = Math.abs(after.distance ?? 0) < Math.abs(before.distance ?? 0);
      const still = Math.abs(moved) < 0.1;
      return `<div class="ti-cmp${still ? ' is-still' : (closer ? ' is-closer' : ' is-farther')}">`
        + `<span class="ti-cmp-label">${escHtml(after.label)}</span>`
        + `<span class="ti-cmp-vals">${escHtml(before.value.toFixed(digits))} → ${escHtml(after.value.toFixed(digits))}</span>`
        + `<span class="ti-cmp-note">${still ? '그대로' : (closer ? '기준에 가까워짐' : '기준에서 멀어짐')}</span></div>`;
    }).join('');
    const onResult = shownId === trial.afterId;
    return `<div class="ti-trial is-done">${head}`
      + (list || '<div class="ti-trial-note">눈에 띄게 움직인 축이 없습니다.</div>')
      + (onResult ? '' : '<div class="ti-trial-note">지금 화면은 시험 결과가 아닌 다른 그림입니다.</div>')
      + `<div class="ti-trial-foot">`
      + `<button type="button" class="ti-btn is-primary" data-ti-apply-trial${busy || trial.applied ? ' disabled' : ''}`
      + ` data-naia-title="이 보정을 같은 세기로 지금 프롬프트 칸 · 네거티브 칸에 넣는다">${trial.applied ? '반영했습니다' : '프롬프트에 반영'}</button>`
      + `<label class="ti-preset" data-naia-title="켜면 프리셋의 postfix 도 같이 고친다 — Random 으로 프롬프트를 새로 뽑아도 남는다. 끄면 지금 프롬프트 칸에만 반영한다.">`
      + `<input type="checkbox" data-ti-preset${prefs.toPreset ? ' checked' : ''}><span>프리셋 postfix 에도</span></label>`
      + `</div></div>`;
  }

  /** 보정 영역 맨 아래의 단추 하나 - 세기를 고른 보정들을 한 번에 얹어 시험 생성한다. */
  function tryBarHtml(total) {
    if (!total) return '';
    const count = chosenItems().length;
    const queued = trial && trial.state === 'queued';
    const label = queued ? '생성 중…' : (count > 1 ? `시험 생성 (${count})` : '시험 생성');
    return `<div class="ti-trybar"><span class="ti-trybar-note">${count ? '' : '해 볼 보정의 세기를 고르세요'}</span>`
      + `<button type="button" class="ti-btn is-primary ti-try" data-ti-trial${busy || queued || !count ? ' disabled' : ''}`
      + ` data-naia-title="이 그림을 같은 시드로, 고른 보정만 얹어 한 장 다시 뽑는다 — 프롬프트 칸은 그대로다">${label}</button></div>`;
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
    return {
      count: main.length,
      html: `<section class="ti-sec ti-advice"><h4 class="ti-sec-title">보정 <span class="ti-sec-note">같은 시드로 시험해 보고 반영</span>`
        + `<button type="button" class="ti-pin${pinned ? ' is-on' : ''}" data-ti-pin aria-pressed="${pinned}"`
        + ` data-naia-title="켜 두면 마우스를 떼도 보정이 접히지 않는다">고정</button></h4>`
        + warningHtml
        + (list || '<div class="ti-empty">이 그림에 권할 보정이 없습니다.</div>')
        + tryBarHtml(suggestions.length)
        + `</section>`,
    };
  }

  function render() {
    box.classList.toggle('is-open', open);
    box.classList.toggle('is-near', near);
    box.classList.toggle('is-pinned', pinned);
    toggle.setAttribute('aria-expanded', String(open));
    caret.textContent = open ? '▾' : '▸';
    body.hidden = !open;
    refreshBtn.hidden = !open;
    const axesNow = axisMap();
    const prominent = (data?.advice?.suggestions || [])
      .filter(s => s.prominent && axesNow.get(s.axis)?.reliable !== false).length;
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
    indexRules();
    const keepScroll = body.scrollTop;
    body.classList.toggle('is-loading', status === 'loading');
    const advice = adviceSection(axesNow);
    // 기본은 결과(색 치우침 · 기준값 대비)만. 보정은 마우스를 가까이 대면(또는 고정하면) 뜬다 - 감추는 것은 CSS 가 한다
    // (`.ti-box:not(.is-near):not(.is-pinned) .ti-advice`). 다시 그리지 않고 클래스만 바꾸므로 깜빡이지 않는다.
    // 시험의 진행 · 결과는 마우스가 없어도 보인다.
    body.innerHTML = `<div class="ti-results">${rgbSection(axesNow)}${axesSection(axesNow)}</div>`
      + trialHtml(axesNow)
      + `<div class="ti-hint">${advice.count > 0 ? `보정 ${advice.count}개 · ` : ''}마우스를 올리면 보정이 열립니다</div>`
      + advice.html;
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
    const strength = event.target.closest('[data-ti-strength]');
    if (strength) {
      // 고른 세기를 다시 누르면 그 보정을 뺀다.
      const choice = choiceOf(strength.dataset.tiFor);
      const value = Number(strength.dataset.tiStrength);
      choice.strength = choice.strength === value ? null : value;
      render();
      return;
    }
    const level = event.target.closest('[data-ti-level]');
    if (level) {
      const choice = choiceOf(level.dataset.tiFor);
      choice.level = choice.level === level.dataset.tiLevel ? null : level.dataset.tiLevel;
      // 단계를 고른 것은 그 보정을 하겠다는 뜻이다 - 세기를 안 골랐으면 기본으로 넣는다.
      if (choice.level && choice.strength == null) choice.strength = 1;
      render();
      return;
    }
    const tryButton = event.target.closest('[data-ti-trial]');
    if (tryButton && !tryButton.disabled) {
      startTrial();
      return;
    }
    if (event.target.closest('[data-ti-trial-close]')) {
      clearTimeout(trialTimer);
      trial = null;
      render();
      return;
    }
    const applyButton = event.target.closest('[data-ti-apply-trial]');
    if (applyButton && !applyButton.disabled) { applyTrial(); return; }
    if (event.target.closest('[data-ti-pin]')) {
      pinned = !pinned;
      remember();
      render();
    }
  });
  // 마우스가 판에 닿으면 보정을 띄우고, 떠나면 잠깐 뒤에 접는다. 클래스만 바꾼다 - 다시 그리지 않는다.
  function setNear(next) {
    clearTimeout(leaveTimer);
    if (next) {
      if (!near) { near = true; box.classList.add('is-near'); }
      return;
    }
    leaveTimer = setTimeout(() => {
      near = false;
      box.classList.remove('is-near');
    }, LEAVE_DELAY_MS);
  }
  box.addEventListener('mouseenter', () => setNear(true));
  box.addEventListener('mouseleave', () => setNear(false));
  // 키보드로 들어온 경우도 같다(초점이 판 안에 있는 동안).
  box.addEventListener('focusin', () => setNear(true));
  box.addEventListener('focusout', event => { if (!box.contains(event.relatedTarget)) setNear(false); });
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
