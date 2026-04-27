export function createGenerationProgress({
  document,
  window,
  getGenStartTime,
  getDurations,
}) {
  let progressTimer = null;

  function clearProgressTimer() {
    if (progressTimer) {
      window.clearInterval(progressTimer);
      progressTimer = null;
    }
  }

  function clearFinishTimeout() {
    if (window._progressFinishTimeout) {
      window.clearTimeout(window._progressFinishTimeout);
      window._progressFinishTimeout = null;
    }
  }

  function start() {
    const bar = document.getElementById('genProgressBar');
    const bar2 = document.getElementById('genProgressBar2');
    const wrap = document.getElementById('genProgress');
    clearProgressTimer();
    clearFinishTimeout();

    bar.style.transition = 'none';
    bar.style.width = '0%';
    bar2.style.transition = 'none';
    bar2.style.width = '0%';
    void bar.offsetWidth;
    bar.style.transition = 'width 0.3s linear';
    bar2.style.transition = 'width 0.3s linear';
    wrap.classList.add('active');

    const durations = getDurations();
    const estimated = durations.length > 0
      ? durations.reduce((a, b) => a + b, 0) / durations.length
      : 12000;

    progressTimer = window.setInterval(() => {
      const elapsed = Date.now() - getGenStartTime();
      const pct = Math.min((elapsed / estimated) * 100, 100);
      bar.style.width = pct + '%';
      if (elapsed > estimated) {
        const overPct = Math.min(((elapsed - estimated) / estimated) * 100, 100);
        bar2.style.width = overPct + '%';
      }
    }, 50);
  }

  function finish() {
    clearProgressTimer();
    clearFinishTimeout();
    const bar = document.getElementById('genProgressBar');
    const bar2 = document.getElementById('genProgressBar2');
    const wrap = document.getElementById('genProgress');
    bar.style.transition = 'width 0.2s ease-out';
    bar2.style.transition = 'width 0.2s ease-out';
    bar.style.width = '100%';
    window._progressFinishTimeout = window.setTimeout(() => {
      window._progressFinishTimeout = null;
      wrap.classList.remove('active');
      bar.style.width = '0%';
      bar2.style.width = '0%';
    }, 400);
  }

  return {
    start,
    finish,
  };
}
