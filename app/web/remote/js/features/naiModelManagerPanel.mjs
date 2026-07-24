export function createNaiModelManagerPanel({
  document,
  window,
  showToast,
  onStateChanged,
}) {
  const panel = document.getElementById('naiModelManagerPanel');
  if (!panel) {
    return {
      open() {},
      close() {},
      isOpen: () => false,
    };
  }

  const body = panel.querySelector('[data-nai-model-manager-body]');
  const state = {
    builtIn: [],
    custom: [],
    payloadProfiles: ['passthrough', 'v3', 'v4', 'v4.5'],
    maxCustomModels: 32,
    defaultModel: 'NAID4.5F',
  };
  let editingKey = '';
  let busy = false;

  const pick = selector => panel.querySelector(selector);

  // 실측 기준(NAID4.5F txt2img payload)의 parameters 키 목록. 제거/덮어쓰기 대상을
  // 사용자가 이름으로 추측하지 않도록 샘플 값과 함께 나열한다.
  const V45_SAMPLE_PARAMS = [
    ['width', '832'],
    ['height', '1216'],
    ['steps', '28'],
    ['scale', '5.0'],
    ['cfg_rescale', '0.0'],
    ['sampler', '"k_euler_ancestral"'],
    ['noise_schedule', '"native"'],
    ['seed', '0'],
    ['extra_noise_seed', '0'],
    ['n_samples', '1'],
    ['negative_prompt', '"..."'],
    ['skip_cfg_above_sigma', '58'],
    ['autoSmea', 'true'],
    ['prefer_brownian', 'true'],
    ['ucPreset', '0'],
    ['use_coords', 'false'],
    ['add_original_image', 'true'],
    ['legacy', 'false'],
    ['legacy_uc', 'false'],
    ['legacy_v3_extend', 'false'],
    ['params_version', '3'],
    ['v4_prompt', '{caption: …}'],
    ['v4_negative_prompt', '{caption: …}'],
  ];

  function escapeHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function setBusy(nextBusy) {
    busy = !!nextBusy;
    body.querySelectorAll('button, input, textarea, select').forEach(element => {
      element.disabled = busy;
    });
    panel.classList.toggle('is-busy', busy);
  }

  function setEditorMessage(message = '', level = '') {
    const element = pick('[data-nai-model-editor-message]');
    if (!element) return;
    element.textContent = String(message || '');
    element.dataset.level = level;
  }

  function applyServerState(payload = {}) {
    state.builtIn = Array.isArray(payload.built_in) ? payload.built_in.slice() : [];
    state.custom = Array.isArray(payload.custom) ? payload.custom.slice() : [];
    state.payloadProfiles = Array.isArray(payload.payload_profiles)
      ? payload.payload_profiles.slice()
      : state.payloadProfiles;
    state.maxCustomModels = Number(payload.max_custom_models) || 32;
    state.defaultModel = String(payload.default_model || 'NAID4.5F');
    if (editingKey && !state.custom.some(model => model.key === editingKey)) {
      editingKey = '';
    }
  }

  async function loadState() {
    const response = await window.fetch('/api/nai-models', {cache: 'no-store'});
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || `모델 목록을 불러오지 못했습니다 (HTTP ${response.status}).`);
    }
    applyServerState(payload);
  }

  function renderShell() {
    body.innerHTML = `
      <div class="nai-model-manager-layout">
        <section class="nai-model-manager-left">
          <div class="nai-model-manager-section-head">
            <div>
              <strong>사용자 모델</strong>
              <span data-nai-model-count></span>
            </div>
            <button type="button" class="nai-model-manager-btn" data-nai-model-action="new">새 모델</button>
          </div>
          <div class="nai-model-manager-list" data-nai-model-list></div>

          <div class="nai-model-manager-editor-head">
            <strong data-nai-model-editor-title>새 모델 추가</strong>
            <span data-nai-model-editor-key></span>
          </div>
          <label class="nai-model-manager-field">
            <span>보여질 모델 명</span>
            <input type="text" maxlength="80" autocomplete="off"
                   data-nai-model-label placeholder="NAID4C">
          </label>
          <label class="nai-model-manager-field">
            <span>API 모델 명</span>
            <input type="text" maxlength="128" autocomplete="off" spellcheck="false"
                   data-nai-model-api placeholder="nai-diffusion-4-curated-preview">
          </label>
          <label class="nai-model-manager-field">
            <span>API 인페인트 모델 명</span>
            <input type="text" maxlength="128" autocomplete="off" spellcheck="false"
                   data-nai-model-inpaint placeholder="nai-diffusion-4-curated-inpainting">
            <small>비워두면 인페인트 호출은 ${escapeHtml(state.defaultModel)}로 fallback 됩니다.</small>
          </label>
          <label class="nai-model-manager-field compact">
            <span>Payload 호환 프로필</span>
            <select data-nai-model-profile data-native-select>
              <option value="auto">Auto — 알 수 없는 모델은 V4.5로 처리</option>
              <option value="v4.5">V4.5</option>
              <option value="v4">V4</option>
              <option value="v3">V3</option>
              <option value="passthrough">Passthrough — 미래/미확정 모델</option>
            </select>
          </label>

          <div class="nai-model-manager-guide">
            <strong>샘플 가이드</strong>
            <ol>
              <li>보여질 모델 명으로 <code>NAID4C</code>를 입력합니다.</li>
              <li>API에 <code>nai-diffusion-4-curated-preview</code>를 추가합니다.</li>
              <li>인페인팅은 <code>nai-diffusion-4-curated-inpainting</code>를 추가합니다.</li>
              <li>인페인팅 모델이 없거나 모르면 비워둡니다. 이 경우 인페인팅 호출은 <code>${escapeHtml(state.defaultModel)}</code>로 fallback 됩니다.</li>
            </ol>
          </div>
        </section>

        <section class="nai-model-manager-right">
          <label class="nai-model-manager-field grow">
            <span>커스텀 API 파라미터</span>
            <textarea spellcheck="false" data-nai-model-overrides
                      placeholder='key = "value",&#10;steps = 28,'></textarea>
            <small><code>key = value,</code>를 한 줄에 하나씩 입력하세요. value는 JSON으로 파싱됩니다. 전체 JSON 객체도 사용할 수 있습니다. 같은 key의 기존 파라미터는 서버 전송 직전에 덮어씁니다.</small>
          </label>
          <label class="nai-model-manager-field grow removal">
            <span>강제로 제거할 파라미터</span>
            <textarea spellcheck="false" data-nai-model-removals
                      placeholder="skip_cfg_above_sigma&#10;legacy_uc"></textarea>
            <small>한 줄 또는 쉼표로 key를 구분합니다. 일치하는 파라미터는 최종 payload에서 <code>pop</code>됩니다. 제거 규칙이 덮어쓰기보다 우선합니다.</small>
          </label>
          <div class="nai-model-manager-sample">
            <div class="nai-model-manager-sample-head">
              <strong>V4.5 기본 파라미터</strong>
              <span>클릭하면 제거 목록에 추가/해제</span>
            </div>
            <div class="nai-model-manager-sample-list">
              ${V45_SAMPLE_PARAMS.map(([name, sample]) => `
                <button type="button" class="nai-model-manager-sample-chip"
                        data-nai-model-sample="${escapeHtml(name)}"
                        title="${escapeHtml(`${name} = ${sample}`)}">${escapeHtml(name)}</button>
              `).join('')}
            </div>
          </div>
        </section>

        <footer class="nai-model-manager-footer">
          <span data-nai-model-editor-message aria-live="polite"></span>
          <button type="button" class="nai-model-manager-btn" data-nai-model-action="close">닫기</button>
          <button type="button" class="nai-model-manager-btn primary" data-nai-model-action="save">저장</button>
        </footer>
      </div>
    `;
  }

  function renderList() {
    const list = pick('[data-nai-model-list]');
    const count = pick('[data-nai-model-count]');
    if (count) count.textContent = `${state.custom.length} / ${state.maxCustomModels}`;
    if (!list) return;
    if (!state.custom.length) {
      list.innerHTML = '<div class="nai-model-manager-empty">등록된 사용자 모델이 없습니다.</div>';
      return;
    }
    list.innerHTML = state.custom.map(model => {
      const key = String(model.key || '');
      const label = String(model.label || key);
      const inpaint = model.inpainting_api_model
        ? escapeHtml(model.inpainting_api_model)
        : `${escapeHtml(state.defaultModel)} fallback`;
      return `
        <div class="nai-model-manager-row${key === editingKey ? ' selected' : ''}">
          <button type="button" class="nai-model-manager-row-main"
                  data-nai-model-select="${escapeHtml(key)}">
            <strong>${escapeHtml(label)}</strong>
            <span>${escapeHtml(model.api_model || '')}</span>
            <small>Inpaint: ${inpaint}</small>
          </button>
          <button type="button" class="nai-model-manager-row-delete"
                  data-nai-model-delete="${escapeHtml(key)}" aria-label="${escapeHtml(label)} 삭제">×</button>
        </div>
      `;
    }).join('');
  }

  function inferPayloadProfile(apiModel) {
    const wire = String(apiModel || '').trim().toLowerCase();
    if (wire.includes('nai-diffusion-4-5')) return 'v4.5';
    if (wire.includes('nai-diffusion-4')) return 'v4';
    if (wire.includes('nai-diffusion-3')) return 'v3';
    // 미지의 모델(NAID5 등)은 V4.5 파이프라인을 기본으로 태운다(2026-07-24 사용자 결정).
    // 서버가 4.5 필드를 거부하는 모델이면 프로필을 Passthrough로 직접 바꾸면 된다.
    return 'v4.5';
  }

  function formatOverrides(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return '';
    return Object.entries(value)
      .map(([key, item]) => `${key} = ${JSON.stringify(item)},`)
      .join('\n');
  }

  function parseOverrides(raw) {
    const text = String(raw || '').trim();
    if (!text) return {};
    if (text.startsWith('{')) {
      const parsed = JSON.parse(text);
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('커스텀 API 파라미터 JSON은 객체여야 합니다.');
      }
      return parsed;
    }
    const result = {};
    text.split(/\r?\n/).forEach((rawLine, index) => {
      let line = rawLine.trim();
      if (!line) return;
      if (line.endsWith(',')) line = line.slice(0, -1).trim();
      const separator = line.indexOf('=');
      if (separator <= 0) {
        throw new Error(`커스텀 API 파라미터 ${index + 1}행은 key = value 형식이어야 합니다.`);
      }
      let key = line.slice(0, separator).trim();
      const valueText = line.slice(separator + 1).trim();
      if ((key.startsWith('"') && key.endsWith('"')) || (key.startsWith("'") && key.endsWith("'"))) {
        key = key.slice(1, -1).trim();
      }
      if (!key || !valueText) {
        throw new Error(`커스텀 API 파라미터 ${index + 1}행의 key/value가 비어 있습니다.`);
      }
      try {
        result[key] = JSON.parse(valueText);
      } catch (_error) {
        throw new Error(
          `커스텀 API 파라미터 ${index + 1}행의 value가 유효한 JSON 값이 아닙니다. 문자열은 큰따옴표로 감싸세요.`
        );
      }
    });
    return result;
  }

  function parseRemovals(raw) {
    return Array.from(new Set(
      String(raw || '')
        .split(/[\r\n,]+/)
        .map(value => value.trim())
        .filter(Boolean)
    ));
  }

  function refreshSampleChips() {
    const removals = new Set(parseRemovals(pick('[data-nai-model-removals]')?.value));
    panel.querySelectorAll('[data-nai-model-sample]').forEach(chip => {
      chip.classList.toggle('active', removals.has(chip.dataset.naiModelSample));
    });
  }

  function toggleSampleRemoval(name) {
    const element = pick('[data-nai-model-removals]');
    if (!element || !name) return;
    const current = parseRemovals(element.value);
    const next = current.includes(name)
      ? current.filter(item => item !== name)
      : [...current, name];
    element.value = next.join('\n');
    refreshSampleChips();
  }

  function uniqueInternalKey(label) {
    let base = String(label || '')
      .normalize('NFKC')
      .trim()
      .toUpperCase()
      .replace(/\s+/g, '_')
      .replace(/[^A-Z0-9._-]/g, '')
      .replace(/^[^A-Z0-9]+/, '')
      .slice(0, 40);
    if (!base) base = `CUSTOM_${Date.now().toString(36).toUpperCase()}`.slice(0, 40);
    const used = new Set(
      [...state.builtIn, ...state.custom]
        .map(model => String(model.key || '').toUpperCase())
        .filter(Boolean)
    );
    if (!used.has(base)) return base;
    for (let suffix = 2; suffix < 1000; suffix += 1) {
      const tail = `_${suffix}`;
      const candidate = `${base.slice(0, 40 - tail.length)}${tail}`;
      if (!used.has(candidate)) return candidate;
    }
    return `CUSTOM_${Date.now().toString(36).toUpperCase()}`.slice(0, 40);
  }

  function resetEditor() {
    editingKey = '';
    const fields = [
      '[data-nai-model-label]',
      '[data-nai-model-api]',
      '[data-nai-model-inpaint]',
      '[data-nai-model-overrides]',
      '[data-nai-model-removals]',
    ];
    fields.forEach(selector => {
      const element = pick(selector);
      if (element) element.value = '';
    });
    const profile = pick('[data-nai-model-profile]');
    if (profile) profile.value = 'auto';
    const title = pick('[data-nai-model-editor-title]');
    const key = pick('[data-nai-model-editor-key]');
    if (title) title.textContent = '새 모델 추가';
    if (key) key.textContent = '';
    setEditorMessage();
    refreshSampleChips();
    renderList();
  }

  function loadEditor(modelKey) {
    const model = state.custom.find(item => String(item.key || '') === String(modelKey || ''));
    if (!model) return;
    editingKey = String(model.key || '');
    pick('[data-nai-model-label]').value = String(model.label || model.key || '');
    pick('[data-nai-model-api]').value = String(model.api_model || '');
    pick('[data-nai-model-inpaint]').value = String(model.inpainting_api_model || '');
    pick('[data-nai-model-profile]').value = String(model.payload_profile || 'passthrough');
    pick('[data-nai-model-overrides]').value = formatOverrides(model.api_parameter_overrides);
    pick('[data-nai-model-removals]').value = Array.isArray(model.api_parameter_removals)
      ? model.api_parameter_removals.join('\n')
      : '';
    pick('[data-nai-model-editor-title]').textContent = '모델 편집';
    pick('[data-nai-model-editor-key]').textContent = editingKey;
    setEditorMessage();
    refreshSampleChips();
    renderList();
  }

  async function saveEditor() {
    const label = String(pick('[data-nai-model-label]')?.value || '').trim();
    const apiModel = String(pick('[data-nai-model-api]')?.value || '').trim();
    const inpaintModel = String(pick('[data-nai-model-inpaint]')?.value || '').trim();
    const requestedProfile = String(pick('[data-nai-model-profile]')?.value || 'auto');
    if (!label) throw new Error('보여질 모델 명을 입력하세요.');
    if (!apiModel) throw new Error('API 모델 명을 입력하세요.');

    const profile = requestedProfile === 'auto'
      ? inferPayloadProfile(apiModel)
      : requestedProfile;
    const key = editingKey || uniqueInternalKey(label);
    const entry = {
      key,
      label,
      api_model: apiModel,
      inpainting_api_model: inpaintModel,
      payload_profile: profile,
      family: profile === 'passthrough' ? 'custom' : profile,
      api_parameter_overrides: parseOverrides(
        pick('[data-nai-model-overrides]')?.value
      ),
      api_parameter_removals: parseRemovals(
        pick('[data-nai-model-removals]')?.value
      ),
    };

    const response = await window.fetch('/api/nai-models', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(entry),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || `모델을 저장하지 못했습니다 (HTTP ${response.status}).`);
    }
    applyServerState(payload.state || {});
    editingKey = String(payload.model?.key || key);
    renderList();
    loadEditor(editingKey);
    onStateChanged?.(payload);
    showToast?.(`${label} 모델을 저장하고 선택했습니다.`, 'success');
  }

  async function deleteModel(modelKey) {
    const model = state.custom.find(item => String(item.key || '') === String(modelKey || ''));
    if (!model) return;
    const label = String(model.label || model.key || '');
    if (!window.confirm(`사용자 모델 "${label}"을 삭제할까요?`)) return;
    const response = await window.fetch(`/api/nai-models/${encodeURIComponent(model.key)}`, {
      method: 'DELETE',
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || `모델을 삭제하지 못했습니다 (HTTP ${response.status}).`);
    }
    const wasEditing = editingKey === model.key;
    applyServerState(payload.state || {});
    if (wasEditing) resetEditor();
    else renderList();
    onStateChanged?.(payload);
    showToast?.(`${label} 모델을 삭제했습니다.`, 'success');
  }

  async function open() {
    panel.classList.add('open');
    renderShell();
    resetEditor();
    setBusy(true);
    try {
      await loadState();
      renderList();
    } catch (error) {
      showToast?.(error.message || 'NAI 모델 목록을 불러오지 못했습니다.', 'error');
      close();
    } finally {
      setBusy(false);
    }
  }

  function close() {
    panel.classList.remove('open');
    body.innerHTML = '';
    editingKey = '';
  }

  panel.addEventListener('input', event => {
    if (event.target?.matches?.('[data-nai-model-removals]')) refreshSampleChips();
  });

  panel.addEventListener('click', async event => {
    const sample = event.target.closest('[data-nai-model-sample]');
    if (sample && !busy) {
      toggleSampleRemoval(sample.dataset.naiModelSample);
      return;
    }
    const select = event.target.closest('[data-nai-model-select]');
    if (select && !busy) {
      loadEditor(select.dataset.naiModelSelect);
      return;
    }
    const remove = event.target.closest('[data-nai-model-delete]');
    if (remove && !busy) {
      setBusy(true);
      try {
        await deleteModel(remove.dataset.naiModelDelete);
      } catch (error) {
        setEditorMessage(error.message || '모델 삭제 실패', 'error');
        showToast?.(error.message || '모델 삭제 실패', 'error');
      } finally {
        setBusy(false);
      }
      return;
    }
    const action = event.target.closest('[data-nai-model-action]')?.dataset.naiModelAction;
    if (!action || busy) return;
    if (action === 'new') resetEditor();
    else if (action === 'close') close();
    else if (action === 'save') {
      setEditorMessage();
      setBusy(true);
      try {
        await saveEditor();
        setEditorMessage('저장 완료', 'success');
      } catch (error) {
        setEditorMessage(error.message || '모델 저장 실패', 'error');
        showToast?.(error.message || '모델 저장 실패', 'error');
      } finally {
        setBusy(false);
      }
    }
  });

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && panel.classList.contains('open')) close();
  });

  return {
    open,
    close,
    isOpen: () => panel.classList.contains('open'),
  };
}
