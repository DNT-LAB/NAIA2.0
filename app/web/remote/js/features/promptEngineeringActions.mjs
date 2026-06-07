export function createPromptEngineeringActions({
  document,
  getMode,
  showToast,
  confirmDialog = async () => false,
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
    if (mode !== 'NAI' && mode !== 'WEBUI' && !isAnima) {
      showToast('추천 설정 적용은 NAI, WEBUI 또는 COMFYUI ANIMA 모드에서만 사용할 수 있습니다.', 'error');
      return;
    }
    if (!await Promise.resolve(confirmDialog('추천 설정을 새 프리셋으로 만들고 즉시 적용하시겠습니까?'))) return;
    flushPresetSaveState();
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

  function commitHoveredRandomizedPresetOption() {
    const select = document.getElementById('modRandomizedPresetAddSelect');
    if (!select) return null;
    const hovered = document.querySelector(
      '.custom-select-menu[data-select-id="modRandomizedPresetAddSelect"]:not([hidden]) .custom-select-option.is-hovered',
    );
    const index = Number(hovered?.dataset?.index ?? -1);
    if (Number.isInteger(index) && index >= 0 && index < select.options.length && !select.options[index].disabled) {
      select.selectedIndex = index;
      select.dispatchEvent(new Event('input', { bubbles: true }));
      select.dispatchEvent(new Event('change', { bubbles: true }));
    }
    return select;
  }

  function addRandomizedPreset() {
    const select = commitHoveredRandomizedPresetOption();
    const preset = select ? select.value.trim() : '';
    if (!preset) {
      showToast('랜덤 풀에 추가할 프리셋이 없습니다.', 'error');
      return;
    }
    setModuleParam('prompt_engineering', 'randomized_add', preset);
  }

  function removeRandomizedPreset(preset) {
    const name = String(preset || '').trim();
    if (!name) return;
    setModuleParam('prompt_engineering', 'randomized_remove', name);
  }

  function switchRandomizedPreset(preset) {
    const name = String(preset || '').trim();
    if (!name) return;
    closePresetManagePanel();
    const select = document.getElementById('modPreset');
    const hasOption = select && Array.from(select.options || []).some(option => option.value === name);
    if (hasOption) {
      select.value = name;
      select.dispatchEvent(new Event('input', { bubbles: true }));
      select.dispatchEvent(new Event('change', { bubbles: true }));
      return;
    }
    onPresetChange(name);
  }

  function clearRandomizedPresets() {
    setModuleParam('prompt_engineering', 'randomized_clear', 'true');
  }

  function setRandomizedWildcard(front, back, enabled) {
    setModuleParam('prompt_engineering', 'randomized_wildcard', JSON.stringify({
      front: String(front || ''),
      back: String(back || ''),
      enabled: !!enabled,
    }));
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

  function saveOllamaBoostSettings() {
    const nlWeightRaw = parseFloat(document.getElementById('modOllamaBoostWeight')?.value ?? '');
    const nlWeight = Number.isFinite(nlWeightRaw) ? nlWeightRaw : 1.0;
    const effortChecked = document.querySelector('input[name="modOllamaBoostEffort"]:checked');
    const effort = effortChecked ? effortChecked.value : 'rich';
    const payload = {
      nl_weight: nlWeight,
      effort,
      include_prefix: !!document.getElementById('modOllamaBoostIncludePrefix')?.checked,
      include_postfix: !!document.getElementById('modOllamaBoostIncludePostfix')?.checked,
      include_e621: !!document.getElementById('modOllamaBoostIncludeE621')?.checked,
    };
    setModuleParam('prompt_engineering', 'ollama_boost_settings', JSON.stringify(payload));
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

  // Session-only flag (never persisted; backend resets it to false on load). Unlike
  // setOption() this uses the bare `ollama_auto_boost` key (NOT the `pp_` prefix) and
  // lives at the top level of the module state, not inside `preprocessing`.
  function setOllamaAutoBoost(checked) {
    const lastState = getLastPromptEngineeringState();
    if (lastState) lastState.ollama_auto_boost = !!checked;
    setModuleParam('prompt_engineering', 'ollama_auto_boost', checked ? 'true' : 'false');
  }

  return {
    flushPresetSaveState,
    onPresetChange,
    saveCurrentPreset,
    createPreset,
    applyRecommendedPreset,
    deleteCurrentPreset,
    addRandomizedPreset,
    removeRandomizedPreset,
    switchRandomizedPreset,
    clearRandomizedPresets,
    setRandomizedWildcard,
    saveE621Settings,
    saveDanbooruSettings,
    saveOllamaBoostSettings,
    refreshDebug,
    setOption,
    setOllamaAutoBoost,
  };
}
