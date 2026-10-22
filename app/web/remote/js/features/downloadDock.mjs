/** 공용 다운로드 띠 - 결과 뷰어 오른쪽 아래(사용자 지시 2026-10-22 · Queue 창 옷).
 *
 *      ┌──────────────────────────────────────┐
 *      │ DOWNLOAD  캐릭터 썸네일 확장 팩    42% │
 *      │ ▬▬▬▬▬▬▬▬▬▬▬▬░░░░░░░░░░░░░░░░░░░░░░░ │
 *      │ 312 MB / 740 MB · 7,677명 · 뒤에서 받는 중 │
 *      └──────────────────────────────────────┘
 *
 *  사용자 지정: **펼치기 · 접기 없음 · 취소 없음**. 실패하면 [재시도]. 공용 - install-manager 의 다운로드라면
 *  무엇이든 이 띠에 한 줄씩 뜬다(`GET /api/install-manager` 의 `downloads`). 끝나면 몇 초 보여 주고 사라진다.
 *
 *  ⚠️ 실패를 자동으로 다시 받지 않는다 - 다시 받는 것은 [재시도] 뿐이다(이벤트 맵에서 실패 뒤 폴링이 2초마다
 *     처음부터 다시 받을 뻔했다). 이 판은 **읽기만** 한다 - 시작은 서버가 앱을 켤 때 스스로 한다.
 *  ⚠️ 속도 · 남은 시간을 쓰지 않는다(화면에 예상 속도 금지).
 */

const ACTIVE_POLL_MS = 1500;
const IDLE_POLL_MS = 15000;
const DONE_SHOW_MS = 4000;
const FIRST_RETRY_MS = 3000;   // 첫 정상 응답 전 실패(서버가 아직 뜨는 중)는 15초를 기다리지 않는다

export function createDownloadDock({
  document: doc,
  fetch: fetchFn = window.fetch.bind(window),
  escHtml = value => String(value ?? ''),
  showToast = () => {},
  onDone = () => {},           // (key) => void   받기가 끝났다 - 열려 있는 화면을 다시 그리게
} = {}) {
  const root = doc.getElementById('downloadDock');
  if (!root) return {refresh() {}};

  let timer = 0;
  let rows = [];
  const doneUntil = new Map();   // key -> 이 시각까지 '완료' 를 보여 준다
  const seenActive = new Set();  // 이번 실행에서 받는 것을 본 키 - 그것만 '완료' 를 띄운다(옛 done 이 매번 뜨지 않게)
  const retrying = new Set();
  const notified = new Set();    // onDone 을 부른 키 - 한 번만
  let wasActive = false;
  let answered = false;          // 정상 응답을 한 번이라도 받았나

  const mb = n => `${Math.round((Number(n) || 0) / 1048576).toLocaleString()} MB`;

  function lineHtml(d) {
    const pct = Math.max(0, Math.min(100, Math.round(Number(d.percent) || 0)));
    const state = String(d.state || '');
    const done = state === 'done';
    const failed = state === 'error';
    const parts = [];
    if (Number(d.total) > 0) parts.push(`${mb(d.bytes)} / ${mb(d.total)}`);
    else if (Number(d.bytes) > 0) parts.push(mb(d.bytes));
    if (Number(d.items) > 0) parts.push(`${Number(d.items).toLocaleString()}명`);
    let sub;
    if (failed) sub = escHtml(d.error || '받지 못했습니다.');
    else if (done) sub = Number(d.items) > 0 ? `썸네일 ${Number(d.items).toLocaleString()}명 추가` : '받았습니다';
    else if (state === 'queued') sub = '대기 중 · 다른 다운로드가 끝나면 받습니다';
    else if (state === 'installing') sub = [...parts, '적용 중'].join(' · ');
    else sub = [...parts, '뒤에서 받는 중'].join(' · ');
    const retry = failed
      ? (d.retryable
        ? `<button type="button" class="dl-retry" data-dl-retry="${escHtml(d.key)}"${retrying.has(d.key) ? ' disabled' : ''}>재시도</button>`
        : '<span class="dl-note">PC 에서 다시 시도</span>')
      : '';
    return `<div class="dl-row${done ? ' is-done' : ''}${failed ? ' is-error' : ''}" data-dl-key="${escHtml(d.key)}">`
      + `<div class="dl-top"><span class="dl-eyebrow">DOWNLOAD</span><span class="dl-name">${escHtml(d.label || d.key)}</span>`
      + `<span class="dl-pct">${done ? '완료' : `${pct}%`}</span></div>`
      + `<div class="dl-bar"><i style="width:${done ? 100 : pct}%"></i></div>`
      + `<div class="dl-sub"><span>${sub}</span>${retry}</div></div>`;
  }

  function paint() {
    const now = Date.now();
    const shown = rows.filter(d => d.state !== 'done' || (doneUntil.get(d.key) || 0) > now);
    root.hidden = !shown.length;
    const html = shown.map(lineHtml).join('');
    if (root._dlHtml !== html) { root._dlHtml = html; root.innerHTML = html; }
  }

  function finish(key) {
    if (notified.has(key)) return;
    notified.add(key);
    try { onDone(key); } catch (_) {}
  }

  async function poll() {
    clearTimeout(timer);
    // 조회가 실패해도 받는 중이었으면 빠른 주기를 지킨다 - 15초로 밀리면 서버가 잠깐 남겨 두는 '완료' 줄을 놓친다(Codex 리뷰).
    let active = wasActive;
    try {
      const res = await fetchFn('/api/install-manager', {cache: 'no-store'});
      const data = await res.json().catch(() => null);
      // 실패 응답 · 깨진 JSON 은 '빈 목록' 이 아니다 - 그걸 빈 목록으로 읽으면 받는 중인 키가 사라진 것으로 보여
      // 완료로 오인한다(Codex 재리뷰). 정상 응답의 `downloads` 배열만 믿는다.
      if (!res.ok || !Array.isArray(data?.downloads)) throw new Error('bad install-manager response');
      const list = data.downloads;
      const now = Date.now();
      list.forEach(d => {
        if (['queued', 'downloading', 'installing'].includes(d.state)) seenActive.add(d.key);
        if (d.state === 'done' && seenActive.has(d.key) && !doneUntil.has(d.key)) {
          doneUntil.set(d.key, now + DONE_SHOW_MS);
          finish(d.key);
        }
      });
      // 받는 걸 본 키가 '완료' 줄 없이 목록에서 사라졌다 - 완료 줄을 놓친 것이다. 화면은 다시 그리게 한다.
      seenActive.forEach(key => {
        if (!list.some(d => d.key === key)) finish(key);
      });
      rows = list;
      active = list.some(d => ['queued', 'downloading', 'installing'].includes(d.state))
        || [...doneUntil.values()].some(t => t > now);
      wasActive = active;
      answered = true;
    } catch (_) { /* 서버가 잠깐 안 받아도 다음에 다시 본다 */ }
    paint();
    timer = setTimeout(poll, active ? ACTIVE_POLL_MS : (answered ? IDLE_POLL_MS : FIRST_RETRY_MS));
  }

  root.addEventListener('click', async event => {
    const btn = event.target.closest('[data-dl-retry]');
    if (!btn) return;
    const key = btn.dataset.dlRetry;
    retrying.add(key);
    paint();
    try {
      // 라우트 이름 = 키의 '_' 를 '-' 로(tag_archive -> tag-archive · character_pack -> character-pack).
      const res = await fetchFn(`/api/install-manager/${key.replace(/_/g, '-')}/download`, {method: 'POST'});
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) throw new Error(data.error || `HTTP ${res.status}`);
    } catch (error) {
      showToast(`다시 받지 못했습니다 — ${error.message || error}`, 'error');
    } finally {
      retrying.delete(key);
      void poll();
    }
  });

  void poll();
  return {refresh: () => { void poll(); }};
}
