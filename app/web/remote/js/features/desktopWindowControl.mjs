export function createDesktopWindowControl({
  document,
  getWs,
  WebSocket,
}) {
  const button = document.getElementById('desktopToggleBtn');
  let visible = true;
  let controlAllowed = false;

  function disable() {
    controlAllowed = false;
    if (button) button.classList.add('hidden');
  }

  function onState(message) {
    if (typeof message.visible === 'boolean') visible = message.visible;
    if (typeof message.control_allowed === 'boolean') {
      controlAllowed = message.control_allowed;
    }
    if (!button) return;

    if (!controlAllowed) {
      button.classList.add('hidden');
      return;
    }

    button.classList.remove('hidden');
    button.classList.toggle('visible-state', visible);
    button.classList.toggle('hidden-state', !visible);
    button.textContent = visible ? '데스크톱 숨기기' : '데스크톱 표시';
    button.title = visible ? '데스크톱 앱 숨기기' : '데스크톱 앱 표시';
  }

  function toggle() {
    const ws = getWs();
    if (!controlAllowed || !ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({
      type: 'set_desktop_window_visibility',
      visible: !visible,
    }));
  }

  return {
    disable,
    onState,
    toggle,
  };
}
