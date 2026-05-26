export function createSetupController({
  document,
  getWs,
  WebSocket,
  showToast,
  updateModeSelectAvailability,
  renderCloudflaredControls,
  setupLauncherBtn,
  modeApiCombo,
  confirmDialog = async () => false,
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
  const setupClearBtns = { NAI: byId('setupBtnClearNai'), WEBUI: byId('setupBtnClearWebui'), COMFYUI: byId('setupBtnClearComfyui') };
  const SETUP_READY_LABEL = '확인 후 저장';
  const SETUP_LOADING_LABEL = '확인 중...';
  const NOT_SET_LABEL = '미설정';
  const SAVED_LABEL = '저장됨';

  let setupForced = false;
  let setupAllowed = true;
  let setupBlockReason = '';
  let serverSetupForced = false;
  let runtimeSetupForced = false;
  let runtimeSetupReason = '';
  let apiStatusLast = null;
  let initialProbeDone = false;
  let probeCompleted = false;
  let pendingForcedClose = false;
  const probeState = { NAI: null, WEBUI: null, COMFYUI: null };
  const clearPending = { NAI: false, WEBUI: false, COMFYUI: false };
  const clearTimers = { NAI: null, WEBUI: null, COMFYUI: null };

  function getApiStatus() {
    return apiStatusLast;
  }

  function resetInitialProbe() {
    initialProbeDone = false;
  }

  function isModeConnected(mode) {
    return probeState && probeState[mode] === 'ok';
  }

  function hasConnectedMode() {
    return Object.values(probeState).some(state => state === 'ok');
  }

  function isProbePending() {
    return Object.values(probeState).some(state => state === 'probing');
  }

  function hasProbeCompleted() {
    return probeCompleted;
  }

  function setRuntimeSetupForced(forced, reason = '') {
    runtimeSetupForced = !!forced;
    runtimeSetupReason = reason || '';
    refreshSetupGateDisplay();
  }

  function isModeConfigured(mode) {
    const last = apiStatusLast || {};
    if (mode === 'NAI') return !!last.nai_configured;
    if (mode === 'WEBUI') return !!(last.webui_url && last.webui_url.length);
    if (mode === 'COMFYUI') return !!(last.comfyui_url && last.comfyui_url.length);
    return false;
  }

  function refreshClearButtons() {
    Object.keys(setupClearBtns).forEach(mode => {
      const button = setupClearBtns[mode];
      if (!button) return;
      const configured = isModeConfigured(mode);
      const pending = !!clearPending[mode];
      button.disabled = !setupAllowed || pending || !configured;
      button.title = configured ? '저장된 연결 정보를 제거합니다.' : '저장된 연결 정보가 없습니다.';
    });
  }

  function refreshSetupGateDisplay() {
    setupForced = serverSetupForced || runtimeSetupForced;
    setupDialog.classList.toggle('blocked', !setupAllowed);
    if (setupForced) {
      setupCloseBtn.classList.add('hidden');
      setupOverlay.classList.add('open');
    } else {
      setupCloseBtn.classList.remove('hidden');
      if (pendingForcedClose) {
        // 강제 설정이 해제됨(백엔드 연결 성공) → 모달 자동 닫기
        pendingForcedClose = false;
        setupOverlay.classList.remove('open');
      }
    }
    if (setupSubTitle) {
      if (setupAllowed) {
        setupSubTitle.classList.remove('blocked');
        setupSubTitle.textContent = runtimeSetupForced
          ? (runtimeSetupReason || '연결된 백엔드가 없습니다. API 설정을 확인하세요.')
          : setupSubDefault;
      } else {
        setupSubTitle.classList.add('blocked');
        setupSubTitle.textContent = setupBlockReason || '설정 비활성화 - 로컬 접속이 필요합니다.';
      }
    }
    if (setupLauncherBtn) setupLauncherBtn.classList.toggle('needs-setup', setupForced);
    if (modeApiCombo) modeApiCombo.classList.toggle('needs-setup', setupForced);
    refreshClearButtons();
  }

  function openApiPopup() {
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
    probeCompleted = false;
    const last = apiStatusLast || {};
    probeState.NAI = last.nai_configured ? 'probing' : null;
    probeState.WEBUI = (last.webui_url && last.webui_url.length) ? 'probing' : null;
    probeState.COMFYUI = (last.comfyui_url && last.comfyui_url.length) ? 'probing' : null;
    refreshDotsFromProbe();
    ws.send(JSON.stringify({ type: 'probe_api' }));
  }

  function onProbeResult(message) {
    probeCompleted = true;
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
      showToast('백엔드를 하나 이상 연결하세요.', 'error');
      return;
    }
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
    button.textContent = loading ? SETUP_LOADING_LABEL : SETUP_READY_LABEL;
  }

  function setupGateCheck() {
    if (!setupAllowed) {
      showToast(setupBlockReason || '이 클라이언트에서는 설정이 차단되었습니다.', 'error');
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
      setSetupResult('NAI', '토큰을 먼저 붙여넣으세요.', 'error');
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
      setSetupResult('WEBUI', '서버 주소를 먼저 입력하세요.', 'error');
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
      setSetupResult('COMFYUI', '서버 주소를 먼저 입력하세요.', 'error');
      return;
    }
    setSetupLoading('COMFYUI', true);
    setSetupResult('COMFYUI', '', '');
    getWs().send(JSON.stringify({ type: 'verify_comfyui', url }));
  }

  async function clearApi(mode) {
    if (!setupGateCheck()) return;
    if (!isModeConfigured(mode)) {
      refreshClearButtons();
      setSetupResult(mode, '이미 연결 해제된 상태입니다.', 'warning');
      return false;
    }
    const confirmed = await Promise.resolve(confirmDialog(`${mode} 연결을 해제할까요?`, {
      title: '연결 해제',
      okText: '연결 해제',
      cancelText: '취소',
    }));
    if (!confirmed) return;
    setSetupLoading(mode, true);
    setSetupResult(mode, '연결 해제 중...', 'info');
    clearPending[mode] = true;
    refreshClearButtons();
    if (clearTimers[mode]) clearTimeout(clearTimers[mode]);
    clearTimers[mode] = setTimeout(() => {
      if (!clearPending[mode]) return;
      clearPending[mode] = false;
      clearTimers[mode] = null;
      setSetupLoading(mode, false);
      setSetupResult(mode, '연결 해제 응답 시간이 초과되었습니다. 상태를 다시 확인해주세요.', 'error');
      refreshClearButtons();
    }, 8000);
    getWs().send(JSON.stringify({ type: 'clear_api', mode }));
    return true;
  }

  function clearInputForMode(mode) {
    if (mode === 'NAI') byId('setupNaiToken').value = '';
    if (mode === 'WEBUI') byId('setupWebuiUrl').value = '';
    if (mode === 'COMFYUI') byId('setupComfyuiUrl').value = '';
  }

  function finishClearApi(mode, success, message, messageType) {
    if (clearTimers[mode]) {
      clearTimeout(clearTimers[mode]);
      clearTimers[mode] = null;
    }
    clearPending[mode] = false;
    setSetupLoading(mode, false);
    setSetupResult(mode, message, messageType);
    if (!success) {
      refreshClearButtons();
      return;
    }
    clearInputForMode(mode);
    probeState[mode] = null;
    refreshDotsFromProbe();
    refreshClearButtons();
  }

  function onClearApiResult(message) {
    const mode = message.mode;
    finishClearApi(mode, !!message.success, message.message, message.message_type);
  }

  function onVerifyResult(message) {
    const mode = message.mode;
    setSetupLoading(mode, false);
    setSetupResult(mode, message.message, message.message_type);
    if (message.success && setupForced) {
      // 강제 설정 모달에서 인증 성공 → 게이트가 풀리는 순간 자동 닫기
      pendingForcedClose = true;
    }
    if (message.success && mode === 'NAI') {
      byId('setupNaiToken').value = '';
    }
    probeState[mode] = message.success ? 'ok' : 'err';
    refreshDotsFromProbe();
  }

  function onSetupBlocked(message) {
    if (message.command === 'probe_api') return;
    showToast(message.reason || '이 클라이언트에서는 설정이 차단되었습니다.', 'error');
  }

  function applySetupGate(message) {
    setupAllowed = message.setup_allowed !== false;
    serverSetupForced = !!message.setup_required;
    setupBlockReason = message.setup_block_reason || '';
    refreshSetupGateDisplay();
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
      if (!configured) return NOT_SET_LABEL;
      if (!preview) return SAVED_LABEL;
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

    if (clearPending.NAI && !hasNai) {
      finishClearApi('NAI', true, '연결 해제됨', 'info');
    }
    if (clearPending.WEBUI && !hasWebui) {
      finishClearApi('WEBUI', true, '연결 해제됨', 'info');
    }
    if (clearPending.COMFYUI && !hasComfy) {
      finishClearApi('COMFYUI', true, '연결 해제됨', 'info');
    }

    if (setupMetaEls.NAI) setupMetaEls.NAI.textContent = lastVerified.nai || '\u2014';
    if (setupMetaEls.WEBUI) setupMetaEls.WEBUI.textContent = lastVerified.webui || '\u2014';
    if (setupMetaEls.COMFYUI) setupMetaEls.COMFYUI.textContent = lastVerified.comfyui || '\u2014';
    refreshClearButtons();

    const naiPreview = byId('setupMetaNaiPreview');
    if (naiPreview) naiPreview.textContent = message.nai_token_preview ? (message.nai_token_preview + '\u2026') : '\u2014';
    const naiInput = byId('setupNaiToken');
    if (naiInput) {
      naiInput.placeholder = hasNai ? '저장됨 - 새 토큰을 붙여넣으면 교체됩니다' : 'NovelAI 토큰 붙여넣기';
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
    hasConnectedMode,
    isProbePending,
    hasProbeCompleted,
    setRuntimeSetupForced,
    openApiPopup,
    probeApi,
    onProbeResult,
    closeApiPopup,
    onSetupBackdrop,
    switchSetupTab,
    toggleSetupReveal,
    setSetupResult,
    setSetupLoading,
    verifyNai,
    verifyWebui,
    verifyComfyui,
    clearApi,
    onClearApiResult,
    onVerifyResult,
    onSetupBlocked,
    applySetupGate,
    setLauncherConn,
    updateApiStatus,
  };
}
