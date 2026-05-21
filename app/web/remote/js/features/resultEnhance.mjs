export function createResultEnhanceController({
  document,
  window,
  WebSocket,
  getWs,
  getMode,
  showToast,
  getWebUiHiresSettings = () => ({}),
  setWebUiHiresSetting = () => {},
  getWebUiHiresUpscalerOptions = () => [],
}) {
  const button = document.getElementById('resultEnhanceBtn');
  const settingsButton = document.getElementById('resultEnhanceSettingsBtn');
  let currentMeta = null;
  let running = false;
  let settingsPopup = null;
  let config = {
    upscale: 1.5,
    strength: 0.2,
    noise: 0.0,
  };

  function clampNumber(value, min, max, fallback) {
    const number = Number(value);
    if (!Number.isFinite(number)) return fallback;
    return Math.min(max, Math.max(min, number));
  }

  function escapeHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function roundStep(value, step = 10) {
    return Math.round(Number(value) * step) / step;
  }

  function formatFlexibleNumber(value, digits = 1) {
    const number = Number(value);
    if (!Number.isFinite(number)) return '0';
    const fixed = number.toFixed(digits);
    return fixed.replace(/\.0+$/, '').replace(/(\.\d*?)0+$/, '$1');
  }

  function normalizeConfig(next = {}) {
    const upscale = Number(next.upscale) === 1 ? 1.0 : 1.5;
    const strength = Math.round(clampNumber(next.strength, 0.1, 0.9, config.strength) * 10) / 10;
    const noise = Math.round(clampNumber(next.noise, 0.0, 0.1, config.noise) * 10) / 10;
    return {upscale, strength, noise};
  }

  function normalizeWebUiHiresSettings(next = {}) {
    const source = getWebUiHiresSettings();
    const fallback = source && typeof source === 'object' ? source : {};
    const merged = {...fallback, ...(next && typeof next === 'object' ? next : {})};
    return {
      enable_hr: true,
      hr_scale: roundStep(clampNumber(merged.hr_scale, 1.0, 4.0, 2.0), 10),
      hr_upscaler: String(merged.hr_upscaler || 'Latent (nearest-exact)'),
      denoising_strength: roundStep(clampNumber(merged.denoising_strength, 0.0, 1.0, 0.5), 100),
      hires_steps: Math.trunc(clampNumber(merged.hires_steps, 0, 150, 10)),
      hr_cfg: roundStep(clampNumber(merged.hr_cfg, 0.0, 30.0, 7.0), 10),
      webui_hiresfix_assist: Boolean(merged.webui_hiresfix_assist),
      webui_hiresfix_assist_target: Number(merged.webui_hiresfix_assist_target) === 768 ? 768 : 512,
    };
  }

  function formatUpscale(value) {
    return Number(value) === 1 ? '1' : '1.5';
  }

  function currentMode() {
    return String(getMode() || '').toUpperCase();
  }

  function isNaiMode() {
    return currentMode() === 'NAI';
  }

  function isWebUiMode() {
    return currentMode() === 'WEBUI';
  }

  function isSupportedMode() {
    return isNaiMode() || isWebUiMode();
  }

  function label() {
    if (isWebUiMode()) {
      const settings = normalizeWebUiHiresSettings();
      return `Enhance x${formatFlexibleNumber(settings.hr_scale, 1)} | ${formatFlexibleNumber(settings.denoising_strength, 2)}`;
    }
    return `Enhance x${formatUpscale(config.upscale)} | ${config.strength.toFixed(1)}`;
  }

  function getDisabledReason(meta = currentMeta) {
    if (running && !isWebUiMode()) return 'Enhance is running';
    if (!meta) return 'No generated image is selected';
    if (!isSupportedMode()) return 'Enhance is available in NAI or WEBUI mode only';
    if (!meta.can_enhance) {
      return 'Generation parameters are unavailable';
    }
    return '';
  }

  function canRequest(meta = currentMeta) {
    return !getDisabledReason(meta);
  }

  function update() {
    if (!button) return;
    const disabledReason = getDisabledReason();
    button.disabled = !!disabledReason;
    button.classList.toggle('running', running);
    button.textContent = running && !isWebUiMode() ? 'Enhancing...' : label();
    button.title = disabledReason || (isWebUiMode()
      ? 'Run WEBUI Hires.fix Enhance on the current desktop result'
      : 'Run NAI Enhance on the current desktop result');
    if (settingsButton) settingsButton.disabled = running || !isSupportedMode();
  }

  function setCurrentMeta(meta) {
    currentMeta = meta ? {...meta} : null;
    running = false;
    update();
  }

  function clearCurrentMeta() {
    currentMeta = null;
    running = false;
    update();
  }

  function setRunning(value) {
    running = !!value;
    update();
  }

  function setConfig(nextConfig = {}) {
    config = normalizeConfig({...config, ...nextConfig});
    update();
  }

  function closeSettings() {
    if (!settingsPopup) return;
    settingsPopup.remove();
    settingsPopup = null;
  }

  function updateDraftUi(root, draft) {
    root.querySelectorAll('[data-enhance-upscale]').forEach(control => {
      control.classList.toggle('active', Number(control.dataset.enhanceUpscale) === draft.upscale);
    });
    const strengthInput = root.querySelector('[data-enhance-strength]');
    const strengthValue = root.querySelector('[data-enhance-strength-value]');
    const noiseValue = root.querySelector('[data-enhance-noise-value]');
    if (strengthInput) strengthInput.value = String(Math.round(draft.strength * 10));
    if (strengthValue) strengthValue.textContent = draft.strength.toFixed(1);
    if (noiseValue) noiseValue.textContent = draft.noise.toFixed(1);
  }

  function updateWebUiDraftUi(root, draft) {
    const normalized = normalizeWebUiHiresSettings(draft);
    root.querySelectorAll('[data-webui-enhance-value]').forEach(el => {
      const field = el.dataset.webuiEnhanceValue;
      if (field === 'hr_scale') el.textContent = `x${formatFlexibleNumber(normalized.hr_scale, 1)}`;
      else if (field === 'denoising_strength') el.textContent = formatFlexibleNumber(normalized.denoising_strength, 2);
      else if (field === 'hires_steps') el.textContent = String(normalized.hires_steps);
      else if (field === 'hr_cfg') el.textContent = formatFlexibleNumber(normalized.hr_cfg, 1);
      else if (field === 'hr_upscaler') el.textContent = normalized.hr_upscaler;
    });
  }

  function sendConfig(nextConfig) {
    const socket = getWs();
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      if (showToast) showToast('Remote connection is not open', 'error', true);
      return false;
    }
    const payload = normalizeConfig(nextConfig);
    const previousConfig = {...config};
    setConfig(payload);
    try {
      socket.send(JSON.stringify({
        type: 'set_result_enhance_config',
        ...payload,
      }));
    } catch (error) {
      setConfig(previousConfig);
      if (showToast) showToast('Enhance settings update failed', 'error', true);
      return false;
    }
    return true;
  }

  function webUiUpscalerOptions(currentValue) {
    const rawOptions = getWebUiHiresUpscalerOptions();
    const options = Array.isArray(rawOptions) ? rawOptions.map(String) : [];
    const current = String(currentValue || '').trim();
    if (current && !options.includes(current)) options.unshift(current);
    if (!options.length) options.push('Latent (nearest-exact)');
    return Array.from(new Set(options.filter(value => value.trim())));
  }

  function applyWebUiSettings(draft) {
    const next = normalizeWebUiHiresSettings(draft);
    setWebUiHiresSetting('hr_scale', String(next.hr_scale));
    setWebUiHiresSetting('hr_upscaler', next.hr_upscaler);
    setWebUiHiresSetting('denoising_strength', String(next.denoising_strength));
    setWebUiHiresSetting('hires_steps', String(next.hires_steps));
    setWebUiHiresSetting('hr_cfg', String(next.hr_cfg));
    update();
    return true;
  }

  function openNaiSettings() {
    const draft = {...config};
    settingsPopup = document.createElement('div');
    settingsPopup.className = 'result-enhance-settings-root';
    settingsPopup.innerHTML = `
      <div class="result-enhance-settings-backdrop" data-enhance-close></div>
      <section class="result-enhance-settings-panel" role="dialog" aria-modal="true" aria-label="Enhance settings">
        <header class="result-enhance-settings-header">
          <div>
            <div class="result-enhance-settings-kicker">Enhance</div>
            <div class="result-enhance-settings-title">Settings</div>
          </div>
          <button type="button" class="result-enhance-settings-close" data-enhance-close aria-label="Close">&times;</button>
        </header>
        <div class="result-enhance-field">
          <div class="result-enhance-field-label">Upscale Amount</div>
          <div class="result-enhance-segment">
            <button type="button" data-enhance-upscale="1">1x</button>
            <button type="button" data-enhance-upscale="1.5">1.5x</button>
          </div>
        </div>
        <div class="result-enhance-field">
          <div class="result-enhance-field-row">
            <span class="result-enhance-field-label">Strength</span>
            <span class="result-enhance-value" data-enhance-strength-value></span>
          </div>
          <input class="result-enhance-slider" type="range" min="1" max="9" step="1" data-enhance-strength>
        </div>
        <div class="result-enhance-field">
          <div class="result-enhance-field-row">
            <span class="result-enhance-field-label">Magnitude Presets</span>
            <span class="result-enhance-value">noise <span data-enhance-noise-value></span></span>
          </div>
          <div class="result-enhance-presets">
            <button type="button" data-enhance-preset="0.2,0.0">1</button>
            <button type="button" data-enhance-preset="0.3,0.0">2</button>
            <button type="button" data-enhance-preset="0.4,0.0">3</button>
            <button type="button" data-enhance-preset="0.5,0.0">4</button>
            <button type="button" data-enhance-preset="0.7,0.1">5</button>
          </div>
        </div>
        <footer class="result-enhance-settings-actions">
          <button type="button" class="secondary" data-enhance-close>Cancel</button>
          <button type="button" class="primary" data-enhance-apply>Apply</button>
        </footer>
      </section>`;
    document.body.appendChild(settingsPopup);
    updateDraftUi(settingsPopup, draft);

    settingsPopup.addEventListener('click', event => {
      const target = event.target;
      if (!(target instanceof window.Element)) return;
      if (target.closest('[data-enhance-close]')) {
        closeSettings();
        return;
      }
      const upscaleButton = target.closest('[data-enhance-upscale]');
      if (upscaleButton) {
        draft.upscale = Number(upscaleButton.dataset.enhanceUpscale) === 1 ? 1.0 : 1.5;
        updateDraftUi(settingsPopup, draft);
        return;
      }
      const presetButton = target.closest('[data-enhance-preset]');
      if (presetButton) {
        const [strength, noise] = String(presetButton.dataset.enhancePreset || '').split(',').map(Number);
        draft.strength = strength;
        draft.noise = noise;
        updateDraftUi(settingsPopup, draft);
        return;
      }
      if (target.closest('[data-enhance-apply]')) {
        if (sendConfig(draft)) closeSettings();
      }
    });

    const strengthInput = settingsPopup.querySelector('[data-enhance-strength]');
    if (strengthInput) {
      strengthInput.addEventListener('input', () => {
        draft.strength = Number(strengthInput.value) / 10;
        updateDraftUi(settingsPopup, draft);
      });
    }
  }

  function openWebUiSettings() {
    const draft = normalizeWebUiHiresSettings();
    const upscalerOptions = webUiUpscalerOptions(draft.hr_upscaler)
      .map(value => `<option value="${escapeHtml(value)}"${value === draft.hr_upscaler ? ' selected' : ''}>${escapeHtml(value)}</option>`)
      .join('');

    settingsPopup = document.createElement('div');
    settingsPopup.className = 'result-enhance-settings-root';
    settingsPopup.innerHTML = `
      <div class="result-enhance-settings-backdrop" data-enhance-close></div>
      <section class="result-enhance-settings-panel" role="dialog" aria-modal="true" aria-label="WEBUI Hires.fix settings">
        <header class="result-enhance-settings-header">
          <div>
            <div class="result-enhance-settings-kicker">WEBUI Hires.fix</div>
            <div class="result-enhance-settings-title">Enhance Settings</div>
          </div>
          <button type="button" class="result-enhance-settings-close" data-enhance-close aria-label="Close">&times;</button>
        </header>
        <div class="result-enhance-field">
          <div class="result-enhance-field-row">
            <span class="result-enhance-field-label">Upscale Amount</span>
            <span class="result-enhance-value" data-webui-enhance-value="hr_scale"></span>
          </div>
          <input class="result-enhance-input" type="number" min="1" max="4" step="0.1" value="${escapeHtml(draft.hr_scale)}" data-webui-enhance-field="hr_scale">
        </div>
        <div class="result-enhance-field">
          <div class="result-enhance-field-row">
            <span class="result-enhance-field-label">Upscaler</span>
            <span class="result-enhance-value" data-webui-enhance-value="hr_upscaler"></span>
          </div>
          <select class="result-enhance-select" data-webui-enhance-field="hr_upscaler">${upscalerOptions}</select>
        </div>
        <div class="result-enhance-field">
          <div class="result-enhance-field-row">
            <span class="result-enhance-field-label">Denoise</span>
            <span class="result-enhance-value" data-webui-enhance-value="denoising_strength"></span>
          </div>
          <input class="result-enhance-input" type="number" min="0" max="1" step="0.05" value="${escapeHtml(draft.denoising_strength)}" data-webui-enhance-field="denoising_strength">
        </div>
        <div class="result-enhance-field">
          <div class="result-enhance-field-row">
            <span class="result-enhance-field-label">HR Steps</span>
            <span class="result-enhance-value" data-webui-enhance-value="hires_steps"></span>
          </div>
          <input class="result-enhance-input" type="number" min="0" max="150" step="1" value="${escapeHtml(draft.hires_steps)}" data-webui-enhance-field="hires_steps">
        </div>
        <div class="result-enhance-field">
          <div class="result-enhance-field-row">
            <span class="result-enhance-field-label">HR CFG</span>
            <span class="result-enhance-value" data-webui-enhance-value="hr_cfg"></span>
          </div>
          <input class="result-enhance-input" type="number" min="0" max="30" step="0.1" value="${escapeHtml(draft.hr_cfg)}" data-webui-enhance-field="hr_cfg">
        </div>
        <footer class="result-enhance-settings-actions">
          <button type="button" class="secondary" data-enhance-close>Cancel</button>
          <button type="button" class="primary" data-enhance-apply>Apply</button>
        </footer>
      </section>`;
    document.body.appendChild(settingsPopup);
    updateWebUiDraftUi(settingsPopup, draft);

    settingsPopup.addEventListener('click', event => {
      const target = event.target;
      if (!(target instanceof window.Element)) return;
      if (target.closest('[data-enhance-close]')) {
        closeSettings();
        return;
      }
      if (target.closest('[data-enhance-apply]')) {
        if (applyWebUiSettings(draft)) closeSettings();
      }
    });

    settingsPopup.querySelectorAll('[data-webui-enhance-field]').forEach(control => {
      control.addEventListener('input', () => {
        const field = control.dataset.webuiEnhanceField;
        draft[field] = control.value;
        updateWebUiDraftUi(settingsPopup, draft);
      });
      control.addEventListener('change', () => {
        const field = control.dataset.webuiEnhanceField;
        draft[field] = control.value;
        updateWebUiDraftUi(settingsPopup, draft);
      });
    });
  }

  function openSettings() {
    closeSettings();
    if (isWebUiMode()) openWebUiSettings();
    else openNaiSettings();
  }

  function handleState(message = {}) {
    const wasRunning = running;
    setRunning(!!message.running);
    if (message.running && message.message && showToast) {
      showToast(message.message, 'success');
    } else if (wasRunning && !message.running && message.success && showToast) {
      showToast(message.message || 'Enhance complete', 'success');
    }
  }

  function request(metaOverride = null) {
    const requestMeta = metaOverride ? {...metaOverride} : currentMeta;
    if (!canRequest(requestMeta)) {
      const reason = getDisabledReason(requestMeta);
      if (reason && showToast) showToast(reason, 'error', true);
      update();
      return;
    }

    const socket = getWs();
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      if (showToast) showToast('Remote connection is not open', 'error', true);
      return;
    }

    running = true;
    update();
    try {
      const payload = {
        type: 'result_enhance',
        mode: currentMode(),
        source: requestMeta?.source || '',
        path: requestMeta?.source === 'current' ? '' : (requestMeta?.path || ''),
        file_path: requestMeta?.file_path || requestMeta?.filePath || '',
      };
      if (isWebUiMode()) {
        payload.hires_settings = normalizeWebUiHiresSettings();
      } else {
        Object.assign(payload, normalizeConfig(config));
      }
      socket.send(JSON.stringify(payload));
      if (showToast) showToast('Enhance request sent to server', 'success');
    } catch (error) {
      running = false;
      update();
      if (showToast) showToast('Enhance request failed', 'error');
    }
  }

  if (settingsButton) {
    settingsButton.addEventListener('click', event => {
      event.preventDefault();
      openSettings();
    });
  }
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') closeSettings();
  });
  update();

  return {
    clearCurrentMeta,
    handleState,
    request,
    setConfig,
    setCurrentMeta,
    setRunning,
    update,
  };
}
