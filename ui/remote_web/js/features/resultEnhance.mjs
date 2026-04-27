export function createResultEnhanceController({
  document,
  WebSocket,
  getWs,
  getMode,
  showToast,
}) {
  const button = document.getElementById('resultEnhanceBtn');
  let currentMeta = null;
  let running = false;

  function getDisabledReason() {
    if (running) return 'Enhance is running';
    if (!currentMeta) return 'No generated image is selected';
    if (getMode() !== 'NAI') return 'Enhance is available in NAI mode only';
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
    button.textContent = running ? 'Enhancing...' : 'Enhance';
    button.title = disabledReason || 'Run NAI Enhance on the current desktop result';
  }

  function setCurrentMeta(meta) {
    currentMeta = meta || null;
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
    socket.send(JSON.stringify({type: 'result_enhance'}));
  }

  update();

  return {
    clearCurrentMeta,
    request,
    setCurrentMeta,
    setRunning,
    update,
  };
}
