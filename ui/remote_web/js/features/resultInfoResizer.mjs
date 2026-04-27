const STORAGE_KEY = 'naia_result_info_height';
const MIN_HEIGHT = 72;
const MIN_VIEWER_HEIGHT = 220;
const MAX_HEIGHT = 520;

export function createResultInfoResizer({document, window, localStorage}) {
  const panel = document.getElementById('resultInfoPanel');
  const handle = document.getElementById('resultInfoResize');
  const host = document.querySelector('.result-main');
  let initialized = false;

  function clampHeight(height) {
    const hostHeight = host ? host.clientHeight : window.innerHeight;
    const availableMax = Math.max(
      MIN_HEIGHT,
      Math.min(MAX_HEIGHT, hostHeight - MIN_VIEWER_HEIGHT)
    );
    return Math.round(Math.min(Math.max(height, MIN_HEIGHT), availableMax));
  }

  function setHeight(height, persist = true) {
    if (!panel) return;
    const nextHeight = clampHeight(height);
    panel.style.setProperty('--result-info-height', `${nextHeight}px`);
    if (persist) {
      try { localStorage.setItem(STORAGE_KEY, String(nextHeight)); } catch (_) {}
    }
  }

  function init() {
    if (!panel || !handle || initialized) return;
    initialized = true;

    try {
      const stored = Number(localStorage.getItem(STORAGE_KEY));
      if (Number.isFinite(stored) && stored > 0) setHeight(stored, false);
    } catch (_) {}

    let startY = 0;
    let startHeight = 0;
    let dragging = false;

    handle.addEventListener('pointerdown', event => {
      dragging = true;
      startY = event.clientY;
      startHeight = panel.getBoundingClientRect().height;
      document.body.classList.add('resizing-result-info');
      handle.setPointerCapture(event.pointerId);
      event.preventDefault();
    });

    handle.addEventListener('pointermove', event => {
      if (!dragging) return;
      setHeight(startHeight - (event.clientY - startY), false);
    });

    const finishDrag = event => {
      if (!dragging) return;
      dragging = false;
      document.body.classList.remove('resizing-result-info');
      try { handle.releasePointerCapture(event.pointerId); } catch (_) {}
      setHeight(panel.getBoundingClientRect().height, true);
    };

    handle.addEventListener('pointerup', finishDrag);
    handle.addEventListener('pointercancel', finishDrag);

    window.addEventListener('resize', () => {
      setHeight(panel.getBoundingClientRect().height, true);
    });
  }

  return {init, setHeight};
}
