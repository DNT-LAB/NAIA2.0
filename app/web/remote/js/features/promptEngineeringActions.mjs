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
  onPresetCreated = null,
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
    // 모델 변경을 '복제' 로 미뤄 뒀다면 **여기서** 보낸다.
    //
    // ⚠️ 순서가 전부다. 한 소켓에서 순서대로 처리되므로 `preset_create` 가 끝나
    // 새 프리셋이 현재 프리셋이 된 뒤에 `set_param model` 이 도착한다 - 그래서
    // 모델은 **새 프리셋**에 들어가고 원본은 그대로 남는다. 순서가 뒤집히면
    // 원본이 고쳐진다(복제한 의미가 없어진다).
    if (typeof onPresetCreated === 'function') onPresetCreated();
    if (input) input.value = '';
    closePresetAddPanel();
  }

  /** 같은 이름 칸으로 **랜덤 칸**을 만든다(`*randomized:이름`, 사용자 지정 2026-10-04: 랜더마이저 여러 개).
   *  프리셋 만들기와 같은 손놀림이다 - 지금의 모델 · 생성 설정 · 네거티브를 그 칸이 기억하고 그 칸으로 넘어간다.
   *  ⚠️ 모델 변경을 '복제' 로 미뤄 둔 것(`onPresetCreated`)은 여기서 보내지 않는다 - 그것은 프리셋을 복제할 때의 약속이다. */
  function createRandomizedSlot() {
    const input = document.getElementById('modPresetNewName');
    const name = input ? input.value.trim() : '';
    if (!name) {
      showToast('랜덤 칸 이름을 입력하세요', 'error');
      return;
    }
    flushPresetSaveState();
    setModuleParam('prompt_engineering', 'randomized_slot_create', name);
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
    // NAI 는 세대마다 추천 묶음이 다르다 - V5 와 V4.5 는 같은 프롬프트에 다르게
    // 반응해서 하나로 뭉뚱그리면 어느 쪽에서도 추천이 아니게 된다(사용자 지시
    // 2026-08-21). 그래서 **어느 모델의 추천인지 먼저 묻는다.**
    if (mode === 'NAI') {
      const picked = await Promise.resolve(confirmDialog(
        '어느 모델의 추천 설정을 적용할까요? 새 프리셋으로 만들고 즉시 적용합니다.',
        {
          title: '추천 설정 적용',
          choices: [
            { key: 'NAID5F', label: 'NAID5F' },
            { key: 'NAID4.5F', label: 'NAID4.5F' },
          ],
        }));
      // 취소는 false/null 로 온다. 모델 키만 통과시킨다.
      if (typeof picked !== 'string' || !picked) return;
      flushPresetSaveState();
      setModuleParam('prompt_engineering', 'preset_apply_recommended', picked);
      return;
    }
    if (!await Promise.resolve(confirmDialog('추천 설정을 새 프리셋으로 만들고 즉시 적용하시겠습니까?'))) return;
    flushPresetSaveState();
    setModuleParam('prompt_engineering', 'preset_apply_recommended', 'true');
  }

  async function deleteCurrentPreset() {
    const preset = document.getElementById('modPreset')?.value || '';
    if (!preset || preset === 'default' || preset === '*randomized' || preset === '*snapshot') {
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

  function refreshDebug() {
    setModuleParam('prompt_engineering', 'debug_refresh', 'true');
  }

  // 카테고리별 전처리 필터 오버라이드 저장(단일 카테고리 부분 업데이트).
  // exclude/include/hide 는 이미 프론트에서 split+trim+빈 항목 제거된 배열.
  // ⚠️ 세 목록을 **다 보낸다**. 하나를 빼면 백엔드가 그 값을 그대로 두므로(부분
  //    업데이트) 편집기에서 비운 목록이 안 비워진다.
  // 반환: 전송 성공 여부 — 실패(재연결 중 등) 시 호출부가 dirty 를 유지해야 한다.
  function saveCategoryFilter(category, exclude, include, hide) {
    const name = String(category || '').trim();
    if (!name) return false;
    const sent = setModuleParam('prompt_engineering', 'category_filters', JSON.stringify({
      category: name,
      exclude: Array.isArray(exclude) ? exclude : [],
      include: Array.isArray(include) ? include : [],
      hide: Array.isArray(hide) ? hide : [],
    }));
    if (typeof showToast === 'function') {
      if (sent) showToast('카테고리 필터 저장됨', 'success');
      else showToast('연결이 끊겨 저장하지 못했습니다 — 재연결 후 다시 저장하세요', 'error');
    }
    return sent !== false;
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
  // 이름은 Ollama 시절 것 그대로다 — 지금은 앱 내장 모델(Boost v2)의 Auto Boost 토글이다. v2 는 캐릭터 프롬프트를
  // 접지하지 않으므로 사용자의 재굴림 선택을 건드리지 않는다(Ollama 때의 reroll 강제 해제는 없앴다, 09-26).
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
    createRandomizedSlot,
    applyRecommendedPreset,
    deleteCurrentPreset,
    addRandomizedPreset,
    removeRandomizedPreset,
    switchRandomizedPreset,
    clearRandomizedPresets,
    setRandomizedWildcard,
    saveE621Settings,
    saveDanbooruSettings,
    refreshDebug,
    saveCategoryFilter,
    setOption,
    setOllamaAutoBoost,
  };
}
