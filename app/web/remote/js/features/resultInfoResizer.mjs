const STORAGE_KEY = 'naia_result_info_height';
const MIN_HEIGHT = 38;
const MIN_VIEWER_HEIGHT = 220;
const MAX_HEIGHT = 520;
const COLLAPSED_HEIGHT = 44;
const MAX_DRAG_MS = 12000;

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
    panel.classList.toggle('is-collapsed', nextHeight <= COLLAPSED_HEIGHT);
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
    let activePointerId = null;
    let dragTimer = null;

    const clearDragTimer = () => {
      if (!dragTimer) return;
      window.clearTimeout(dragTimer);
      dragTimer = null;
    };

    const updateDrag = event => {
      if (!dragging) return;
      if (activePointerId !== null && event.pointerId !== activePointerId) return;
      setHeight(startHeight - (event.clientY - startY), false);
      event.preventDefault();
    };

    const finishDrag = (event = {}) => {
      if (!dragging) return;

      const pointerId = event.pointerId ?? activePointerId;
      dragging = false;
      activePointerId = null;
      clearDragTimer();
      document.body.classList.remove('resizing-result-info');
      window.removeEventListener('pointermove', updateDrag, true);
      window.removeEventListener('pointerup', finishDrag, true);
      window.removeEventListener('pointercancel', finishDrag, true);
      try {
        if (pointerId !== null && handle.hasPointerCapture(pointerId)) {
          handle.releasePointerCapture(pointerId);
        }
      } catch (_) {}
      setHeight(panel.getBoundingClientRect().height, true);
    };

    const abortDrag = () => finishDrag({pointerId: activePointerId});

    handle.addEventListener('pointerdown', event => {
      if (event.button !== undefined && event.button !== 0) return;
      if (dragging) finishDrag({pointerId: activePointerId});

      dragging = true;
      activePointerId = event.pointerId;
      startY = event.clientY;
      startHeight = panel.getBoundingClientRect().height;
      document.body.classList.add('resizing-result-info');
      try { handle.setPointerCapture(event.pointerId); } catch (_) {}
      window.addEventListener('pointermove', updateDrag, true);
      window.addEventListener('pointerup', finishDrag, true);
      window.addEventListener('pointercancel', finishDrag, true);
      dragTimer = window.setTimeout(abortDrag, MAX_DRAG_MS);
      event.preventDefault();
    });

    handle.addEventListener('lostpointercapture', event => {
      if (dragging && event.pointerId === activePointerId) finishDrag(event);
    });
    window.addEventListener('blur', abortDrag);
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) abortDrag();
    });

    window.addEventListener('resize', () => {
      if (dragging) abortDrag();
      setHeight(panel.getBoundingClientRect().height, true);
    });
  }

  return {init, setHeight};
}
