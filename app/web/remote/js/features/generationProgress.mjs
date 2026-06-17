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

    // 진행 중에는 transition을 켜지 않는다(=instant). 50ms마다 width를 갱신하는데
    // 'width 0.3s' transition이 켜져 있으면 갱신마다 0.3s 컴포지트가 겹쳐 매 프레임
    // 합성 → 생성 중 GPU 폭증(주사율 비례)했다. instant 갱신은 paint만 발생(저비용).
    bar.style.transition = 'none';
    bar.style.width = '0%';
    bar2.style.transition = 'none';
    bar2.style.width = '0%';
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
    }, 33);
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
