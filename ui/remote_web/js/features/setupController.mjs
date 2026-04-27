export function createSetupController({
  document,
  getWs,
  WebSocket,
  getSharedMode,
  showToast,
  updateModeSelectAvailability,
  renderCloudflaredControls,
  setupLauncherBtn,
  modeApiCombo,
  confirmDialog = message => globalThis.confirm(message),
}) {
  const byId = id => document.getElementById(id);
  const setupOverlay = byId('apiPopupOverlay');
  const setupDialog = byId('setupDialog');
  const setupCloseBtn = byId('setupClose');
  const setupSubTitle = document.querySelector('.setup-sub');
  const setupSubDefault = setupSubTitle ? setupSubTitle.textContent : '';
  const setupNavDots = { NAI: byId('setupDotNai'), WEBUI: byId('setupDotWebui'), COMFYUI: byId('setupDotComfyui') };
  const setupNavSubs = { NAI: byId('setupNavSubNai'), WEBUI: byId('setupNavSubWebui'), COMFYUI: byId('setupNavSubComfyui') };
  const setupMetaEls = { NAI: byId('setupMetaNai'), WEBUI: byId('setupMetaWebui'), COMFYUI: byId('setupMetaComfyui') };
  const setupResultEls = { NAI: byId('setupResultNai'), WEBUI: byId('setupResultWebui'), COMFYUI: byId('setupResultComfyui') };
  const setupVerifyBtns = { NAI: byId('setupBtnVerifyNai'), WEBUI: byId('setupBtnVerifyWebui'), COMFYUI: byId('setupBtnVerifyComfyui') };

  let setupForced = false;
  let setupAllowed = true;
  let setupBlockReason = '';
  let apiStatusLast = null;
  let initialProbeDone = false;
  const probeState = { NAI: null, WEBUI: null, COMFYUI: null };

  function getApiStatus() {
    return apiStatusLast;
  }

  function resetInitialProbe() {
    initialProbeDone = false;
  }

  function isModeConnected(mode) {
    return probeState && probeState[mode] === 'ok';
  }

  function openApiPopup() {
    if (getSharedMode()) return;
    setupOverlay.classList.add('open');
    if (apiStatusLast) applySetupGate(apiStatusLast);
    const ws = getWs();
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send('sync');
    }
  }

  function probeApi() {
    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const last = apiStatusLast || {};
    probeState.NAI = last.nai_configured ? 'probing' : null;
    probeState.WEBUI = (last.webui_url && last.webui_url.length) ? 'probing' : null;
    probeState.COMFYUI = (last.comfyui_url && last.comfyui_url.length) ? 'probing' : null;
    refreshDotsFromProbe();
    ws.send(JSON.stringify({ type: 'probe_api' }));
  }

  function onProbeResult(message) {
    const results = message.results || {};
    ['NAI', 'WEBUI', 'COMFYUI'].forEach(mode => {
      if (results[mode] === true) probeState[mode] = 'ok';
      else if (results[mode] === false) probeState[mode] = 'err';
      else probeState[mode] = null;
    });
    refreshDotsFromProbe();
  }

  function refreshDotsFromProbe() {
    Object.keys(setupNavDots).forEach(mode => {
      const element = setupNavDots[mode];
      if (!element) return;
      const state = probeState[mode];
      let className = 'setup-nav-dot';
      if (state === 'ok') className += ' ok';
      else if (state === 'err') className += ' err';
      else if (state === 'probing') className += ' warn';
      element.className = className;
    });
    updateModeSelectAvailability();
  }

  function closeApiPopup() {
    if (setupForced) {
      showToast('Connect at least one backend first', 'error');
      return;
    }
    setupOverlay.classList.remove('open');
  }

  function forceCloseForSharedMode() {
    setupForced = false;
    setupOverlay.classList.remove('open');
  }

  function onSetupBackdrop(event) {
    if (event.target !== event.currentTarget) return;
    if (setupForced) return;
    closeApiPopup();
  }

  function switchSetupTab(tab) {
    document.querySelectorAll('.setup-nav-item').forEach(element => {
      element.classList.toggle('active', element.dataset.tab === tab);
    });
    document.querySelectorAll('.setup-tab-pane').forEach(element => {
      element.classList.toggle('active', element.dataset.pane === tab);
    });
  }

  function toggleSetupReveal(id, button) {
    const element = byId(id);
    if (!element) return;
    const hidden = element.type === 'password';
    element.type = hidden ? 'text' : 'password';
    button.textContent = hidden ? '\u25C8' : '\u25C9';
  }

  function setSetupResult(mode, message, messageType) {
    const element = setupResultEls[mode];
    if (!element) return;
    const className = (messageType === 'info' || messageType === 'warning' || messageType === 'error') ? messageType : '';
    element.className = 'setup-result ' + className;
    element.textContent = message || '';
  }

  function setSetupLoading(mode, loading) {
    const button = setupVerifyBtns[mode];
    if (!button) return;
    button.disabled = !!loading;
    button.textContent = loading ? 'VERIFYING\u2026' : 'VERIFY & SAVE';
  }

  function setupGateCheck() {
    if (!setupAllowed) {
      showToast(setupBlockReason || 'Setup blocked on this client', 'error');
      return false;
    }
    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    return true;
  }

  function verifyNai() {
    if (!setupGateCheck()) return;
    const token = byId('setupNaiToken').value.trim();
    if (!token) {
      setSetupResult('NAI', 'Paste a token first', 'error');
      return;
    }
    setSetupLoading('NAI', true);
    setSetupResult('NAI', '', '');
    getWs().send(JSON.stringify({ type: 'verify_nai', token }));
  }

  function verifyWebui() {
    if (!setupGateCheck()) return;
    const url = byId('setupWebuiUrl').value.trim();
    if (!url) {
      setSetupResult('WEBUI', 'Enter a server URL first', 'error');
      return;
    }
    setSetupLoading('WEBUI', true);
    setSetupResult('WEBUI', '', '');
    getWs().send(JSON.stringify({ type: 'verify_webui', url }));
  }

  function verifyComfyui() {
    if (!setupGateCheck()) return;
    const url = byId('setupComfyuiUrl').value.trim();
    if (!url) {
      setSetupResult('COMFYUI', 'Enter a server URL first', 'error');
      return;
    }
    setSetupLoading('COMFYUI', true);
    setSetupResult('COMFYUI', '', '');
    getWs().send(JSON.stringify({ type: 'verify_comfyui', url }));
  }

  function clearApi(mode) {
    if (!setupGateCheck()) return;
    if (!confirmDialog(`Disconnect ${mode}?`)) return;
    getWs().send(JSON.stringify({ type: 'clear_api', mode }));
    setSetupResult(mode, 'Disconnected', '');
    if (mode === 'NAI') byId('setupNaiToken').value = '';
    if (mode === 'WEBUI') byId('setupWebuiUrl').value = '';
    if (mode === 'COMFYUI') byId('setupComfyuiUrl').value = '';
  }

  function onVerifyResult(message) {
    const mode = message.mode;
    setSetupLoading(mode, false);
    setSetupResult(mode, message.message, message.message_type);
    if (message.success && mode === 'NAI') {
      byId('setupNaiToken').value = '';
    }
    probeState[mode] = message.success ? 'ok' : 'err';
    refreshDotsFromProbe();
  }

  function onSetupBlocked(message) {
    if (message.command === 'probe_api') return;
    showToast(message.reason || 'Setup blocked on this client', 'error');
  }

  function applySetupGate(message) {
    setupAllowed = message.setup_allowed !== false;
    setupForced = !!message.setup_required;
    setupBlockReason = message.setup_block_reason || '';
    setupDialog.classList.toggle('blocked', !setupAllowed);
    if (setupForced) {
      setupCloseBtn.classList.add('hidden');
      setupOverlay.classList.add('open');
    } else {
      setupCloseBtn.classList.remove('hidden');
    }
    if (setupSubTitle) {
      if (setupAllowed) {
        setupSubTitle.classList.remove('blocked');
        setupSubTitle.textContent = setupSubDefault;
      } else {
        setupSubTitle.classList.add('blocked');
        setupSubTitle.textContent = setupBlockReason || 'Setup disabled \u2014 loopback access required.';
      }
    }
    if (setupLauncherBtn) setupLauncherBtn.classList.toggle('needs-setup', setupForced);
    if (modeApiCombo) modeApiCombo.classList.toggle('needs-setup', setupForced);
  }

  function setLauncherConn(on) {
    if (!setupLauncherBtn) return;
    setupLauncherBtn.classList.toggle('online', !!on);
    setupLauncherBtn.classList.toggle('offline', !on);
    if (modeApiCombo) {
      modeApiCombo.classList.toggle('online', !!on);
      modeApiCombo.classList.toggle('offline', !on);
    }
  }

  function updateApiStatus(message) {
    apiStatusLast = message;
    const lastVerified = message.last_verified || {};
    const maxSub = 18;
    const trunc = value => (value && value.length > maxSub) ? (value.slice(0, maxSub) + '\u2026') : value;
    const subOf = (configured, preview) => {
      if (!configured) return 'NOT SET';
      if (!preview) return 'SAVED';
      return trunc(preview);
    };

    const hasNai = !!message.nai_configured;
    const hasWebui = !!(message.webui_url && message.webui_url.length);
    const hasComfy = !!(message.comfyui_url && message.comfyui_url.length);

    if (setupNavSubs.NAI) setupNavSubs.NAI.textContent = subOf(hasNai, message.nai_token_preview || '');
    if (setupNavSubs.WEBUI) setupNavSubs.WEBUI.textContent = subOf(hasWebui, (message.webui_url || '').replace(/^https?:\/\//, ''));
    if (setupNavSubs.COMFYUI) setupNavSubs.COMFYUI.textContent = subOf(hasComfy, (message.comfyui_url || '').replace(/^https?:\/\//, ''));

    if (!hasNai && probeState.NAI !== null) {
      probeState.NAI = null;
      refreshDotsFromProbe();
    }
    if (!hasWebui && probeState.WEBUI !== null) {
      probeState.WEBUI = null;
      refreshDotsFromProbe();
    }
    if (!hasComfy && probeState.COMFYUI !== null) {
      probeState.COMFYUI = null;
      refreshDotsFromProbe();
    }

    if (setupMetaEls.NAI) setupMetaEls.NAI.textContent = lastVerified.nai || '\u2014';
    if (setupMetaEls.WEBUI) setupMetaEls.WEBUI.textContent = lastVerified.webui || '\u2014';
    if (setupMetaEls.COMFYUI) setupMetaEls.COMFYUI.textContent = lastVerified.comfyui || '\u2014';

    const naiPreview = byId('setupMetaNaiPreview');
    if (naiPreview) naiPreview.textContent = message.nai_token_preview ? (message.nai_token_preview + '\u2026') : '\u2014';
    const naiInput = byId('setupNaiToken');
    if (naiInput) {
      naiInput.placeholder = hasNai ? 'Saved \u2014 paste new token to replace' : 'paste NovelAI token';
    }

    const webuiUrl = byId('setupWebuiUrl');
    if (webuiUrl && document.activeElement !== webuiUrl && !webuiUrl.value) {
      webuiUrl.value = (message.webui_url || '').replace(/^https?:\/\//, '');
    }
    const comfyUrl = byId('setupComfyuiUrl');
    if (comfyUrl && document.activeElement !== comfyUrl && !comfyUrl.value) {
      comfyUrl.value = (message.comfyui_url || '').replace(/^https?:\/\//, '');
    }

    applySetupGate(message);
    renderCloudflaredControls(message);

    const ws = getWs();
    if (!initialProbeDone && ws && ws.readyState === WebSocket.OPEN) {
      initialProbeDone = true;
      probeApi();
    }
  }

  updateModeSelectAvailability();

  return {
    getApiStatus,
    resetInitialProbe,
    isModeConnected,
    openApiPopup,
    probeApi,
    onProbeResult,
    closeApiPopup,
    forceCloseForSharedMode,
    onSetupBackdrop,
    switchSetupTab,
    toggleSetupReveal,
    setSetupResult,
    setSetupLoading,
    verifyNai,
    verifyWebui,
    verifyComfyui,
    clearApi,
    onVerifyResult,
    onSetupBlocked,
    applySetupGate,
    setLauncherConn,
    updateApiStatus,
  };
}
