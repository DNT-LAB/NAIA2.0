// Settings > Global > 생성 - 로컬 생성(ComfyUI · WEBUI) 시간 제한(사용자 지정 2026-11-24).
//
// 값은 서버가 쥔다(core/local_generation_timeout.py · 초 · 0 = Off). 화면은 `options` 메시지로 받은 값을 그리고,
// 바꾸면 같은 `set_option` 명령으로 보낸다. 불린 스위치 통로(optBoxes)와 달리 숫자라 이 모듈이 따로 맡는다.
// ⚠️ 서버가 범위를 다시 자른다 - 여기서 자르는 것은 칸에 보이는 값을 서버와 맞추기 위해서다.

export const LOCAL_TIMEOUT_OPTION_KEY = 'local_generation_timeout_seconds';
export const LOCAL_TIMEOUT_DEFAULT = 180;
export const LOCAL_TIMEOUT_MIN = 30;
export const LOCAL_TIMEOUT_MAX = 7200;

/** 칸에 적은 값 -> 보낼 초. 0 = Off. 읽을 수 없으면 null(보내지 않는다). */
export function normalizeLocalTimeout(raw) {
  const text = String(raw ?? '').trim();
  if (!text) return null;
  const number = Number(text);
  if (!Number.isFinite(number) || number < 0) return null;
  if (number === 0) return 0;
  return Math.min(LOCAL_TIMEOUT_MAX, Math.max(LOCAL_TIMEOUT_MIN, Math.round(number)));
}

export function createLocalTimeoutSetting({root, send}) {
  if (!root) return {sync() {}};
  const seg = root.querySelector('[data-local-timeout-seg]');
  const input = root.querySelector('[data-local-timeout-input]');
  let current = null;

  function paint(seconds) {
    current = seconds;
    for (const button of seg?.querySelectorAll('button[data-local-timeout]') || []) {
      const on = Number(button.dataset.localTimeout) === seconds;
      button.classList.toggle('is-on', on);
      button.setAttribute('aria-pressed', on ? 'true' : 'false');
    }
    if (input) {
      input.disabled = seconds === 0;
      // 적는 중인 칸은 덮지 않는다 - 다른 창의 변경이 들어와도 손가락 아래 숫자가 바뀌지 않게.
      if (seconds !== 0 && document.activeElement !== input) input.value = String(seconds);
    }
  }

  function choose(seconds) {
    if (seconds === null || seconds === current) {
      paint(current);
      return;
    }
    paint(seconds);
    send(LOCAL_TIMEOUT_OPTION_KEY, seconds);
  }

  seg?.addEventListener('click', event => {
    const button = event.target.closest('button[data-local-timeout]');
    if (!button) return;
    choose(Number(button.dataset.localTimeout));
  });
  input?.addEventListener('change', () => {
    const seconds = normalizeLocalTimeout(input.value);
    // 칸의 0 은 Off 가 아니라 잘못 적은 값으로 본다 - Off 는 단추로만 고른다.
    choose(seconds === 0 ? null : seconds);
    if (current) input.value = String(current);
  });
  input?.addEventListener('keydown', event => {
    if (event.key === 'Enter') input.blur();
  });

  return {
    /** 서버 값(options 메시지)을 그린다. */
    sync(value) {
      const seconds = Number(value);
      if (!Number.isFinite(seconds) || seconds < 0) return;
      paint(Math.round(seconds));
    },
  };
}
