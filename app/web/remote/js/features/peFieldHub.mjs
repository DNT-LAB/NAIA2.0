export function createPeFieldHub({
  getState = () => ({}),
  getLiveBox = () => null,
  commitState = () => {},
  cloneState = state => ({...state}),
} = {}) {
  const subscribers = new Set();

  function notify(key, origin) {
    for (const fn of [...subscribers]) {
      try { fn({key, origin}); } catch (_) {}
    }
  }

  function read(key) {
    const state = getState();
    if (state == null) return '';
    let box = null;
    try { box = getLiveBox(key); } catch (_) {}
    if (box && String(box.preset) === String(state.preset)) {
      return String(box.value ?? '');
    }
    return String(state[key] ?? '');
  }

  function noteLocalWrite(key, text, {seenPreset = null, origin = ''} = {}) {
    const state = getState();
    const stamp = seenPreset == null ? '' : String(seenPreset);
    if (stamp !== '' && stamp !== String(state?.preset ?? '')) {
      notify(key, origin);
      return false;
    }
    const next = cloneState(state || {});
    next[key] = String(text ?? '');
    commitState(next);
    notify(key, origin);
    return true;
  }

  function noteLiveInput(key, {origin = 'module'} = {}) {
    notify(key, origin);
  }

  function subscribe(fn) {
    subscribers.add(fn);
    return () => subscribers.delete(fn);
  }

  return {read, noteLocalWrite, noteLiveInput, subscribe};
}
