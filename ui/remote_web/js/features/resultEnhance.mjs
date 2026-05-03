export function createResultEnhanceController({
  document,
  window,
  WebSocket,
  getWs,
  getMode,
  showToast,
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

  function normalizeConfig(next = {}) {
    const upscale = Number(next.upscale) === 1 ? 1.0 : 1.5;
    const strength = Math.round(clampNumber(next.strength, 0.1, 0.9, config.strength) * 10) / 10;
    const noise = Math.round(clampNumber(next.noise, 0.0, 0.1, config.noise) * 10) / 10;
    return {upscale, strength, noise};
  }

  function formatUpscale(value) {
    return Number(value) === 1 ? '1' : '1.5';
  }

  function label() {
    return `Enhance x${formatUpscale(config.upscale)} | ${config.strength.toFixed(1)}`;
  }

  function currentMode() {
    return String(getMode() || '').toUpperCase();
  }

  function getDisabledReason() {
    if (running) return 'Enhance is running';
    if (!currentMeta) return 'No generated image is selected';
    if (currentMode() !== 'NAI') return 'Enhance is available in NAI mode only';
    if (!currentMeta.can_enhance) {
      return 'Generation parameters are unavailable';
    }
    return '';
  }

  function canRequest() {
    return !getDisabledReason();
  }

  function update() {
    if (!button) return;
    const disabledReason = getDisabledReason();
    button.disabled = !!disabledReason;
    button.classList.toggle('running', running);
    button.textContent = running ? 'Enhancing...' : label();
    button.title = disabledReason || 'Run NAI Enhance on the current desktop result';
    if (settingsButton) settingsButton.disabled = running || currentMode() !== 'NAI';
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

  function sendConfig(nextConfig) {
    const socket = getWs();
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      if (showToast) showToast('Remote connection is not open', 'error', true);
      return false;
    }
    const payload = normalizeConfig(nextConfig);
    try {
      socket.send(JSON.stringify({
        type: 'set_result_enhance_config',
        ...payload,
      }));
    } catch (error) {
      if (showToast) showToast('Enhance settings update failed', 'error', true);
      return false;
    }
    return true;
  }

  function openSettings() {
    closeSettings();
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
          <button type="button" class="result-enhance-settings-close" data-enhance-close aria-label="Close">×</button>
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

  function handleState(message = {}) {
    const wasRunning = running;
    setRunning(!!message.running);
    if (message.running && message.message && showToast) {
      showToast(message.message, 'success');
    } else if (wasRunning && !message.running && message.success && showToast) {
      showToast(message.message || 'Enhance complete', 'success');
    }
  }

  function request() {
    if (!canRequest()) {
      const reason = getDisabledReason();
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
        source: currentMeta?.source || '',
        path: currentMeta?.source === 'current' ? '' : (currentMeta?.path || ''),
        file_path: currentMeta?.file_path || currentMeta?.filePath || '',
      };
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
