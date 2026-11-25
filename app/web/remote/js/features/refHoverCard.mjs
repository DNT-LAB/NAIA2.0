/**
 * 프롬프트 칸의 `ref:분류:이름` · `ref:분류:__폴더__` 호출에 마우스를 올리면 그 그림 · 넣는 글을 카드로 띄운다(사용자 2026-11-25).
 *
 * - 칸마다 따로 붙이지 않는다: 문서 전체의 mousemove 를 보고 textarea 위에서만 잰다. 그래서 메인 · 앞뒤 고정 ·
 *   캐릭터 퀵 패널 · 캐릭터 창 칸이 한 번에 된다(칸의 링크 모양은 각 칸의 강조 층이 따로 칠한다).
 * - 글자 자리는 숨은 거울(textarea 와 같은 글꼴 · 폭 · 줄바꿈)에 호출만 span 으로 감싸 재 본다.
 * - 내용은 서버가 설명한다(`/api/ref-vibe/library/describe` - 차례를 굴리지 않는다). 몇 초 동안만 기억한다.
 * - 카드는 보기만 한다(사용자 지정 - 바로가기 없음) · pointer-events 없음.
 */

const REF_CORE = /^ref:\S/i;
const CACHE_MS = 5000;

export function createRefHoverCard({document, window, fetchFn, escHtml}) {
  const card = document.createElement('div');
  card.className = 'ref-hover-card';
  card.setAttribute('aria-hidden', 'true');
  document.body.appendChild(card);

  const cache = new Map();       // `${scope}|${token}` -> {at, promise}
  let frame = 0;
  let lastEvent = null;
  let shownKey = '';
  let seq = 0;

  function scopeOf(el) {
    return el.matches?.('[data-cw-min="prompt"], [data-cq-min="prompt"], [data-cq-field^="char_prompt_"]') ? 'char' : 'main';
  }

  function isNegative(el) {
    const id = String(el.id || '');
    const field = String(el.dataset?.field || el.dataset?.cqField || el.dataset?.cwField || '');
    return el.classList.contains('is-neg') || /negative|negedit|_uc_|^uc$/i.test(id) || /negative|_uc_|^uc$/i.test(field)
      || el.matches?.('[data-cq-min="uc"], [data-cw-min="uc"]');
  }

  /** 글 안의 `ref:` 토막 자리 [start, end) - 쉼표 · 줄바꿈으로 가르고 앞뒤 빈칸은 뺀다. */
  function refRanges(text) {
    const out = [];
    const re = /[^,\n]+/g;
    let match;
    while ((match = re.exec(text)) !== null) {
      const piece = match[0];
      const lead = piece.match(/^\s*/)[0].length;
      const core = piece.slice(lead).replace(/\s+$/, '');
      if (REF_CORE.test(core)) out.push([match.index + lead, match.index + lead + core.length, core]);
    }
    return out;
  }

  function copyStyle(source, mirror) {
    const style = window.getComputedStyle(source);
    ['boxSizing', 'width', 'height', 'fontFamily', 'fontSize', 'fontWeight', 'fontStyle', 'letterSpacing',
      'textTransform', 'lineHeight', 'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft',
      'borderTopWidth', 'borderRightWidth', 'borderBottomWidth', 'borderLeftWidth', 'tabSize']
      .forEach(name => { mirror.style[name] = style[name]; });
    mirror.style.borderStyle = 'solid';
    mirror.style.borderColor = 'transparent';
    mirror.style.whiteSpace = 'pre-wrap';
    mirror.style.wordBreak = style.wordBreak || 'normal';
    mirror.style.overflowWrap = style.overflowWrap || style.wordWrap || 'normal';
    // 세로 스크롤바만큼 줄바꿈 폭이 좁다 - 오른쪽 여백으로 맞춘다(tagAssist 캐럿 거울과 같은 보정)
    const scrollbar = Math.max(0, source.offsetWidth - source.clientWidth
      - (parseFloat(style.borderLeftWidth) || 0) - (parseFloat(style.borderRightWidth) || 0));
    if (scrollbar > 0) mirror.style.paddingRight = `${(parseFloat(style.paddingRight) || 0) + scrollbar}px`;
  }

  /** 마우스 아래의 호출(없으면 null) - {token, rect}. */
  function tokenAt(el, x, y) {
    const text = String(el.value || '');
    if (!/ref:/i.test(text)) return null;
    const ranges = refRanges(text);
    if (!ranges.length) return null;
    const rect = el.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    const mirror = document.createElement('div');
    mirror.setAttribute('aria-hidden', 'true');
    Object.assign(mirror.style, {position: 'fixed', visibility: 'hidden', pointerEvents: 'none',
      left: `${rect.left}px`, top: `${rect.top}px`, overflow: 'hidden'});
    copyStyle(el, mirror);
    let cursor = 0;
    const spans = [];
    for (const [start, end, core] of ranges) {
      mirror.appendChild(document.createTextNode(text.slice(cursor, start)));
      const span = document.createElement('span');
      span.textContent = text.slice(start, end);
      mirror.appendChild(span);
      spans.push([span, core]);
      cursor = end;
    }
    mirror.appendChild(document.createTextNode(text.slice(cursor) + '​'));
    document.body.appendChild(mirror);
    mirror.scrollTop = el.scrollTop || 0;
    mirror.scrollLeft = el.scrollLeft || 0;
    let hit = null;
    for (const [span, core] of spans) {
      for (const box of span.getClientRects()) {
        if (x >= box.left - 1 && x <= box.right + 1 && y >= box.top - 1 && y <= box.bottom + 1) {
          hit = {token: core, rect: {left: box.left, right: box.right, top: box.top, bottom: box.bottom}};
          break;
        }
      }
      if (hit) break;
    }
    mirror.remove();
    // 칸 밖으로 스크롤된 글자는 안 보인다 - 칸 안에 걸친 것만
    if (hit && (hit.rect.bottom < rect.top || hit.rect.top > rect.bottom)) return null;
    return hit;
  }

  function describe(token, scope) {
    const key = `${scope}|${token}`;
    const now = Date.now();
    const hit = cache.get(key);
    if (hit && now - hit.at < CACHE_MS) return hit.promise;
    const params = new URLSearchParams({token, scope});
    const promise = fetchFn(`/api/ref-vibe/library/describe?${params}`)
      .then(response => response.json())
      .catch(() => ({ok: false, token, error: '보관함을 읽지 못했습니다'}));
    cache.set(key, {at: now, promise});
    return promise;
  }

  function line(text, cls = '') {
    return `<div class="rhc-line${cls}">${escHtml(text)}</div>`;
  }

  function cardHtml(info) {
    if (!info || info.ok === false) {
      return `<div class="rhc-body"><div class="rhc-title">${escHtml(info?.token || '')}</div>`
        + `<div class="rhc-error">${escHtml(info?.error || '부를 수 없습니다')}</div></div>`;
    }
    const value = Number(info.strength ?? 1);
    const strength = `강도 ${Number.isInteger(value) ? value.toFixed(1) : String(Math.round(value * 100) / 100)}`;
    if (info.kind === 'wild') {
      const thumbs = (info.thumbs || []).slice(0, 6)
        .map(url => `<img src="${escHtml(url)}" alt="" draggable="false">`).join('');
      return (thumbs ? `<div class="rhc-thumbs">${thumbs}</div>` : '')
        + `<div class="rhc-body"><div class="rhc-title">${escHtml(info.group)} · ${escHtml(info.folder)}</div>`
        + `<div class="rhc-meta">${info.mode === 'sequential' ? '장마다 다음 그림' : '장마다 무작위 한 장'} · ${info.count}장 · ${strength}</div></div>`;
    }
    const state = String(info.prompt_state || 'empty');
    let body = `<div class="rhc-title">${escHtml(info.folder)} · ${escHtml(info.name)}</div>`
      + `<div class="rhc-meta">${escHtml(info.type || '')} · ${strength}</div>`;
    if (state === 'empty') body += line('넣는 글 없음', ' is-dim');
    else {
      if (state === 'off') body += line('넣는 글 꺼 둠 - 그림만 갑니다', ' is-dim');
      if (info.call_prompt) body += line(info.call_prompt, state === 'off' ? ' is-off' : '');
      if (info.call_uc) body += line(`UC: ${info.call_uc}`, state === 'off' ? ' is-off' : ' is-uc');
    }
    if (info.same_outfit_off) body += line('같은 옷 유지 끔', ' is-dim');
    const thumb = info.thumb ? `<img class="rhc-thumb" src="${escHtml(info.thumb)}" alt="" draggable="false">` : '';
    return thumb + `<div class="rhc-body">${body}</div>`;
  }

  function place(rect) {
    const vw = window.innerWidth, vh = window.innerHeight;
    const box = card.getBoundingClientRect();
    let left = Math.min(Math.max(8, rect.left), vw - box.width - 8);
    let top = rect.bottom + 6;
    if (top + box.height > vh - 8) top = Math.max(8, rect.top - box.height - 6);
    card.style.left = `${Math.round(left)}px`;
    card.style.top = `${Math.round(top)}px`;
  }

  function hide() {
    shownKey = '';
    seq += 1;
    card.classList.remove('open', 'is-error');
  }

  function check() {
    frame = 0;
    const event = lastEvent;
    if (!event) return;
    const el = event.target;
    if (!el || el.tagName !== 'TEXTAREA' || isNegative(el)) { if (shownKey) hide(); return; }
    const hit = tokenAt(el, event.clientX, event.clientY);
    if (!hit) { if (shownKey) hide(); return; }
    const scope = scopeOf(el);
    const key = `${scope}|${hit.token}|${Math.round(hit.rect.left)}|${Math.round(hit.rect.top)}`;
    if (key === shownKey) return;
    shownKey = key;
    const mine = ++seq;
    describe(hit.token, scope).then(info => {
      if (mine !== seq) return;
      card.innerHTML = cardHtml(info);
      card.classList.toggle('is-error', !info || info.ok === false);
      card.classList.add('open');
      place(hit.rect);
    });
  }

  function onMove(event) {
    lastEvent = event;
    if (!frame) frame = window.requestAnimationFrame(check);
  }

  document.addEventListener('mousemove', onMove, true);
  // 치거나 · 스크롤하거나 · 칸을 떠나면 닫는다
  document.addEventListener('keydown', () => { if (shownKey) hide(); }, true);
  document.addEventListener('scroll', () => { if (shownKey) hide(); }, true);
  document.addEventListener('mouseout', event => {
    if (shownKey && event.target?.tagName === 'TEXTAREA' && !event.target.contains(event.relatedTarget)) hide();
  }, true);

  return {
    hide,
    destroy() {
      document.removeEventListener('mousemove', onMove, true);
      card.remove();
    },
  };
}
