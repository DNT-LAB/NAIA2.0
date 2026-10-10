export function createPeFieldHub({
  getState = () => ({}),
  getLiveBox = () => null,
  commitState = () => {},
  cloneState = state => ({...state}),
  now = () => Date.now(),
} = {}) {
  const subscribers = new Set();
  // 보냈지만 서버의 답을 아직 못 받은 글 - 칸마다 보낸 차례대로.
  // ⚠️ 답은 보낸 차례대로 온다. X 를 보내고 그 답이 오기 전에 Y 를 보내면 **X 의 답이 먼저** 와서 상태를 X 로
  //    되돌린다(Y 의 답이 올 때까지) - 그 사이 비추는 창에서 X 를 바탕으로 친 글이 Y 를 덮는다(Codex 리뷰 2026-10-10).
  //    `base` = 그 글들을 보내기 **전에** 서버가 갖고 있던 글(답을 받을 때마다 받은 글로 옮긴다). 받은 글이
  //    이것이면 "아직 내 글을 처리하기 전의 상태" 다 - **다른 칸**을 고친 답에는 이 칸의 옛 글이 실려 온다.
  const unacked = new Map();      // key → {preset, base, sent: [{text, at}]}
  const UNACKED_TTL = 5000;       // 답이 끝내 안 오는 글(끊긴 소켓)을 영영 믿지 않는다

  function noteUnacked(key, text, preset, before) {
    const at = now();
    let entry = unacked.get(key);
    if (entry) entry.sent = entry.sent.filter(item => at - item.at < UNACKED_TTL);
    if (!entry || entry.preset !== preset || entry.sent.length === 0) {
      entry = {preset, base: before, sent: []};
      unacked.set(key, entry);
    }
    entry.sent.push({text, at});
  }

  /** 서버가 보낸 PE 상태를 받아들이기 전에 부른다. 돌려준 것을 상태로 쓴다.
   *  받은 글이 **보낸 글 중 하나**면 거기까지는 답을 받은 것이다 - 그 뒤에 보낸 글이 남아 있으면 가장 새것을 지킨다.
   *  받은 글이 **보내기 전의 글**(`base`)이면 서버가 아직 내 글을 처리하지 않은 것이다 - 그대로 가장 새것을 지킨다.
   *  그 밖의 글이면(다른 창이 고쳤다 · 서버가 다듬었다 · 프리셋이 바뀌었다) 서버가 진실이다 - 기억을 버린다. */
  function reconcileIncoming(incoming) {
    if (!incoming || unacked.size === 0) return incoming;
    const at = now();
    const preset = String(incoming.preset ?? '');
    let next = incoming;
    for (const [key, entry] of [...unacked]) {
      entry.sent = entry.sent.filter(item => at - item.at < UNACKED_TTL);
      const got = String(incoming[key] ?? '');
      const index = entry.preset === preset ? entry.sent.findIndex(item => item.text === got) : -1;
      const notYetProcessed = index < 0 && entry.preset === preset && got === entry.base;
      if (index < 0 && !notYetProcessed) {
        unacked.delete(key);
        continue;
      }
      if (index >= 0) {
        entry.sent.splice(0, index + 1);
        entry.base = got;
      }
      if (entry.sent.length === 0) {
        unacked.delete(key);
        continue;
      }
      if (next === incoming) next = cloneState(incoming);
      next[key] = entry.sent[entry.sent.length - 1].text;
    }
    return next;
  }

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
    noteUnacked(key, next[key], String(state?.preset ?? ''), String(state?.[key] ?? ''));
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

  return {read, noteLocalWrite, noteLiveInput, reconcileIncoming, subscribe};
}
