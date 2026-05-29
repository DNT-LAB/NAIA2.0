const DANBOORU_MAGNITUDE_TABLE = {
  1:  { min_weight: 0.88, max_weight: 1.15, scale: 0.15, label: '약한' },
  2:  { min_weight: 0.84, max_weight: 1.25, scale: 0.25, label: '중간' },
  3:  { min_weight: 0.80, max_weight: 1.35, scale: 0.35, label: '추천' },
  4:  { min_weight: 0.75, max_weight: 1.42, scale: 0.42, label: '강한' },
  5:  { min_weight: 0.70, max_weight: 1.50, scale: 0.50, label: '최대' },
  6:  { min_weight: 0.62, max_weight: 1.60, scale: 0.60, label: '최대+' },
  7:  { min_weight: 0.55, max_weight: 1.70, scale: 0.70, label: '최대++' },
  8:  { min_weight: 0.50, max_weight: 1.80, scale: 0.80, label: '극한' },
  9:  { min_weight: 0.45, max_weight: 1.90, scale: 0.90, label: '극한+' },
  10: { min_weight: 0.40, max_weight: 2.00, scale: 1.00, label: '극한++' },
};

const RATING_LABEL_MAP = {
  g: 'General',
  s: 'Sensitive',
  q: 'Questionable',
  e: 'Explicit',
};

const FEEDBACK_CONTROL_IDS = [
  'modDanMagnitude',
  'modDanBlend',
  'modDanOverrideOn',
  'modDanOverrideScale',
  'modDanOverrideMin',
  'modDanOverrideMax',
  'modDanRatingOverrideOn',
  'modDanRatingOverride',
  'modDanInvertWeight',
];

export function createDanbooruFeedbackController({ document }) {
  const byId = id => document.getElementById(id);

  function numberValue(id, fallback) {
    const el = byId(id);
    if (!el) return fallback;
    const parsed = parseFloat(el.value ?? '');
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  function intValue(id, fallback) {
    const el = byId(id);
    if (!el) return fallback;
    const parsed = parseInt(el.value ?? '', 10);
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  function getPreviewState(baseSettings = {}) {
    const magnitude = Math.max(1, Math.min(10, intValue('modDanMagnitude', Number(baseSettings.magnitude ?? 3))));
    const preset = DANBOORU_MAGNITUDE_TABLE[magnitude] || DANBOORU_MAGNITUDE_TABLE[3];
    const overrideOn = !!byId('modDanOverrideOn')?.checked;
    const ratingOverrideOn = !!byId('modDanRatingOverrideOn')?.checked;
    const minWeight = overrideOn
      ? numberValue('modDanOverrideMin', Number(baseSettings.override_min ?? preset.min_weight))
      : preset.min_weight;
    const maxWeight = overrideOn
      ? numberValue('modDanOverrideMax', Number(baseSettings.override_max ?? preset.max_weight))
      : preset.max_weight;
    const scale = overrideOn
      ? numberValue('modDanOverrideScale', Number(baseSettings.override_scale ?? preset.scale))
      : preset.scale;
    const blend = numberValue('modDanBlend', Number(baseSettings.rating_blend ?? 0.3));

    return {
      magnitude,
      label: preset.label,
      overrideOn,
      ratingOverrideOn,
      ratingOverride: byId('modDanRatingOverride')?.value || baseSettings.rating_override || 's',
      invertWeight: !!byId('modDanInvertWeight')?.checked,
      minWeight,
      maxWeight,
      scale,
      blend,
    };
  }

  function renderVisualFeedback(state) {
    const spread = Math.max(0, state.maxWeight - state.minWeight);
    const chipTone = spread >= 0.9 ? 'danger' : spread >= 0.55 ? 'accent' : 'muted';
    const samples = [
      { label: 'Common', value: state.invertWeight ? state.maxWeight : state.minWeight, tone: state.invertWeight ? 'high' : 'low' },
      { label: 'Neutral', value: 1.0, tone: 'mid' },
      { label: 'Rare', value: state.invertWeight ? state.minWeight : state.maxWeight, tone: state.invertWeight ? 'low' : 'high' },
    ];
    const maxVisual = Math.max(2.0, state.maxWeight, state.minWeight, 1.0);
    const directionText = state.invertWeight ? 'High-frequency tags gain weight' : 'Rare tags gain weight';

    const sampleRows = samples.map((item) => {
      const pct = Math.max(6, Math.min(100, (item.value / maxVisual) * 100));
      return `
      <div class="mod-dan-sample-row">
        <span class="mod-dan-sample-label">${item.label}</span>
        <div class="mod-dan-sample-bar">
          <span class="mod-dan-sample-fill ${item.tone}" style="width:${pct}%"></span>
        </div>
        <strong>${item.value.toFixed(2)}</strong>
      </div>
    `;
    }).join('');

    return `
    <div class="mod-dan-feedback-card">
      <div class="mod-dan-feedback-head">
        <div>
          <div class="mod-dan-feedback-title">${state.magnitude}단계 · ${state.label}</div>
          <div class="mod-dan-feedback-subtitle">${state.overrideOn ? 'Custom curve active' : 'Preset curve active'} · ${directionText}</div>
        </div>
        <span class="mod-dan-pill ${chipTone}">spread ${spread.toFixed(2)}</span>
      </div>
      <div class="mod-dan-pill-row">
        <span class="mod-dan-pill muted">scale ${state.scale.toFixed(2)}</span>
        <span class="mod-dan-pill muted">blend ${(state.blend * 100).toFixed(0)}%</span>
        <span class="mod-dan-pill ${state.ratingOverrideOn ? 'accent' : 'muted'}">${state.ratingOverrideOn ? `IDF ${RATING_LABEL_MAP[state.ratingOverride] || state.ratingOverride}` : 'IDF auto'}</span>
        <span class="mod-dan-pill ${state.invertWeight ? 'danger' : 'muted'}">${state.invertWeight ? 'inverted' : 'normal'}</span>
      </div>
      <div class="mod-dan-range-caption">Effective weight curve</div>
      <div class="mod-dan-sample-list">${sampleRows}</div>
    </div>
  `;
  }

  function sync(baseSettings = {}) {
    const state = getPreviewState(baseSettings);
    const feedback = byId('modDanFeedback');
    if (feedback) feedback.innerHTML = renderVisualFeedback(state);

    // 슬라이더 중심 패널의 인라인 라벨 (존재할 때만 갱신)
    const magLabel = byId('modDanMagLabel');
    if (magLabel) magLabel.textContent = state.label;
    const magValue = byId('modDanMagValue');
    if (magValue) magValue.textContent = `${state.magnitude} / 10`;
    const rangeEl = byId('modDanRange');
    if (rangeEl) rangeEl.textContent = `${state.minWeight.toFixed(2)} ~ ${state.maxWeight.toFixed(2)}`;
    const blendEl = byId('modDanBlendValue');
    if (blendEl) blendEl.textContent = state.blend.toFixed(1);

    const overrideOn = !!byId('modDanOverrideOn')?.checked;
    const ratingOverrideOn = !!byId('modDanRatingOverrideOn')?.checked;
    ['modDanOverrideScale', 'modDanOverrideMin', 'modDanOverrideMax'].forEach((id) => {
      const el = byId(id);
      if (el) el.disabled = !overrideOn;
    });
    const ratingSelect = byId('modDanRatingOverride');
    if (ratingSelect) ratingSelect.disabled = !ratingOverrideOn;
  }

  function bind(baseSettings = {}) {
    FEEDBACK_CONTROL_IDS.forEach((id) => {
      const el = byId(id);
      if (!el) return;
      const eventName = el.tagName === 'SELECT' || el.type === 'checkbox' ? 'change' : 'input';
      el.addEventListener(eventName, () => sync(baseSettings));
    });
    sync(baseSettings);
  }

  return {
    getPreviewState,
    renderVisualFeedback,
    sync,
    bind,
  };
}
