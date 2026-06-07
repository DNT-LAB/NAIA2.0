const LOADING_HTML = '<div style="text-align:center;color:var(--text-dim);padding:20px">Loading...</div>';

export function createPromptEngineeringPopups({
  getWs,
  WebSocket,
  modulePopup,
  panels,
  positionFloatingPanel,
  relayoutFloatingPanels,
  closeAuxiliaryPopups,
  refreshDebug,
  getLastState,
  renderers,
}) {
  const openState = {
    presetAdd: false,
    presetManage: false,
    e621: false,
    danbooru: false,
    ollamaBoost: false,
    debug: false,
  };

  function requestState() {
    const ws = getWs();
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({type: 'get_module_state', module_id: 'prompt_engineering'}));
    }
  }

  function setLoading(panel) {
    const body = panel.querySelector('.pe-popup-body');
    if (body) body.innerHTML = LOADING_HTML;
  }

  function openPanel(key, {refreshOnly = false} = {}) {
    const panel = panels[key];
    if (!panel) return;
    if (openState[key]) {
      closePanel(key);
      return;
    }
    closeAuxiliaryPopups(panel);
    openState[key] = true;
    panel.classList.add('open');
    positionFloatingPanel(panel, modulePopup);
    setLoading(panel);
    sync(getLastState());
    if (refreshOnly) refreshDebug();
    else requestState();
  }

  function closePanel(key) {
    const panel = panels[key];
    openState[key] = false;
    if (panel) panel.classList.remove('open');
  }

  function closeAll() {
    Object.keys(openState).forEach(closePanel);
  }

  function sync(lastState = getLastState()) {
    relayoutFloatingPanels();
    if (!lastState) return;
    if (openState.presetAdd) renderers.presetAdd(lastState);
    if (openState.presetManage) renderers.presetManage(lastState);
    if (openState.e621) renderers.e621(lastState);
    if (openState.danbooru) renderers.danbooru(lastState);
    if (openState.ollamaBoost) renderers.ollamaBoost(lastState);
    if (openState.debug) renderers.debug(lastState);
  }

  function isOpen(key) {
    return !!openState[key];
  }

  return {
    openPresetAdd: () => openPanel('presetAdd'),
    closePresetAdd: () => closePanel('presetAdd'),
    openPresetManage: () => openPanel('presetManage'),
    closePresetManage: () => closePanel('presetManage'),
    openE621: () => openPanel('e621'),
    closeE621: () => closePanel('e621'),
    openDanbooru: () => openPanel('danbooru'),
    closeDanbooru: () => closePanel('danbooru'),
    openOllamaBoost: () => openPanel('ollamaBoost'),
    closeOllamaBoost: () => closePanel('ollamaBoost'),
    openDebug: () => openPanel('debug', {refreshOnly: true}),
    closeDebug: () => closePanel('debug'),
    closeAll,
    sync,
    isOpen,
  };
}
