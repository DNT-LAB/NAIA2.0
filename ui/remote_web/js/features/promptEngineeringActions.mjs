export function createPromptEngineeringActions({
  document,
  getMode,
  showToast,
  confirmDialog = message => globalThis.confirm(message),
  flushPromptEngineeringEdits,
  flushMainPromptAndParams,
  setModuleParam,
  closePresetAddPanel,
  closePresetManagePanel,
  getLastPromptEngineeringState,
  isComfyUiAnimaMode,
}) {
  function flushPresetSaveState() {
    flushPromptEngineeringEdits();
    flushMainPromptAndParams();
  }

  function onPresetChange(value) {
    flushPresetSaveState();
    setModuleParam('prompt_engineering', 'preset', value);
  }

  function saveCurrentPreset() {
    flushPresetSaveState();
    setModuleParam('prompt_engineering', 'preset_save_current', 'true');
  }

  function createPreset() {
    const input = document.getElementById('modPresetNewName');
    const name = input ? input.value.trim() : '';
    if (!name) {
      showToast('Preset name required', 'error');
      return;
    }
    flushPresetSaveState();
    setModuleParam('prompt_engineering', 'preset_create', name);
    if (input) input.value = '';
    closePresetAddPanel();
  }

  async function applyRecommendedPreset() {
    const mode = getMode();
    const isAnima = typeof isComfyUiAnimaMode === 'function' && isComfyUiAnimaMode();
    if (mode !== 'NAI' && !isAnima) {
      showToast('추천 설정 적용은 NAI 또는 COMFYUI ANIMA 모드에서만 사용할 수 있습니다.', 'error');
      return;
    }
    if (!await Promise.resolve(confirmDialog('추천 설정을 새 프리셋으로 만들고 즉시 적용하시겠습니까?'))) return;
    setModuleParam('prompt_engineering', 'preset_apply_recommended', 'true');
  }

  async function deleteCurrentPreset() {
    const preset = document.getElementById('modPreset')?.value || '';
    if (!preset || preset === 'default' || preset === '*randomized') {
      showToast('This preset cannot be deleted', 'error');
      return;
    }
    if (!await Promise.resolve(confirmDialog(`Delete preset "${preset}"?`))) return;
    setModuleParam('prompt_engineering', 'preset_delete', preset);
    closePresetManagePanel();
  }

  function saveE621Settings() {
    const hiddenRaw = document.getElementById('modE621HiddenTags')?.value || '';
    const hiddenTags = hiddenRaw
      .split(/[\n,]+/)
      .map(tag => tag.trim())
      .filter(Boolean);
    const payload = {
      weight: parseFloat(document.getElementById('modE621Weight')?.value || '0') || 0,
      mode: document.getElementById('modE621Mode')?.value || 'stable',
      hidden_tags: hiddenTags,
    };
    setModuleParam('prompt_engineering', 'e621_settings', JSON.stringify(payload));
  }

  function saveDanbooruSettings() {
    const numberValue = (id, fallback) => {
      const parsed = parseFloat(document.getElementById(id)?.value ?? '');
      return Number.isFinite(parsed) ? parsed : fallback;
    };
    const intValue = (id, fallback) => {
      const parsed = parseInt(document.getElementById(id)?.value ?? '', 10);
      return Number.isFinite(parsed) ? parsed : fallback;
    };
    const payload = {
      magnitude: intValue('modDanMagnitude', 3),
      rating_blend: numberValue('modDanBlend', 0.3),
      override_on: !!document.getElementById('modDanOverrideOn')?.checked,
      override_scale: numberValue('modDanOverrideScale', 0.35),
      override_min: numberValue('modDanOverrideMin', 0.8),
      override_max: numberValue('modDanOverrideMax', 1.35),
      rating_override_on: !!document.getElementById('modDanRatingOverrideOn')?.checked,
      rating_override: document.getElementById('modDanRatingOverride')?.value || 's',
      invert_weight: !!document.getElementById('modDanInvertWeight')?.checked,
    };
    setModuleParam('prompt_engineering', 'danbooru_settings', JSON.stringify(payload));
  }

  function refreshDebug() {
    setModuleParam('prompt_engineering', 'debug_refresh', 'true');
  }

  function setOption(key, checked) {
    const lastState = getLastPromptEngineeringState();
    if (lastState) {
      if (!lastState.preprocessing) lastState.preprocessing = {};
      lastState.preprocessing[key] = !!checked;
    }
    setModuleParam('prompt_engineering', `pp_${key}`, checked ? 'true' : 'false');
  }

  return {
    flushPresetSaveState,
    onPresetChange,
    saveCurrentPreset,
    createPreset,
    applyRecommendedPreset,
    deleteCurrentPreset,
    saveE621Settings,
    saveDanbooruSettings,
    refreshDebug,
    setOption,
  };
}
