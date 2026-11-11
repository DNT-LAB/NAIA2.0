// [자동화 / 고급 기능] > [아티스트 태그 관리](사용자 지시 2026-11-11) - 메인 프롬프트에 쓴 작가를 썸네일 타일로 보여 준다.
//
//   - **부른 그때 한 번** 읽는다. 프롬프트를 고쳐도 따라가지 않는다 - 다시 열면 그때의 프롬프트로 다시 읽는다.
//   - 메인 프롬프트만 본다(네거티브 · 캐릭터 프롬프트는 보지 않는다).
//   - 그림은 서버가 팩을 통째로 올리지 않고 그 작가의 자리만 읽어 낸다(core/artist_pack_index). 처음 여는 팩은
//     자리 색인을 만드느라 몇 초가 든다 - 그동안 '찾는 중' 을 보여 준다.
//   - 작가의 그림은 여러 팩에 나뉘어 있다. 받은 팩 어디에도 없으면 그 타일은 '데이터 없음'.
// 껍데기는 다른 떠 있는 창과 같다(em-overlay em-window). 옷은 이 파일이 직접 넣는다(style.css 를 건드리지 않는다).

import {createDraggablePanel} from './draggablePanel.mjs?v=20260926-childalign';

const STYLE_ID = 'atw-style';
const ATW_CSS = `
.atw-window .dragpanel-body { display: flex; flex-direction: column; min-height: 0; padding: 0; }
.atw-count { font-family: var(--font-mono); font-size: 11px; color: var(--text-dim); }
.atw-note { margin: auto; padding: 24px 16px; text-align: center; font-size: 12px; line-height: 1.6; color: var(--text-dim); }
.atw-note.is-error { color: #ffb4b4; }
.atw-grid { flex: 1 1 auto; min-height: 0; overflow-y: auto; padding: 10px;
  display: grid; grid-template-columns: repeat(auto-fill, minmax(104px, 1fr)); gap: 8px; align-content: start;
  /* 줄 높이를 내용에 맞춘다 - 안 하면 타일(overflow hidden)이 창 높이에 맞춰 눌려 이름 줄이 잘린다(실측 150 -> 77px). */
  grid-auto-rows: max-content; }
.atw-tile { min-width: 0; border: 1px solid var(--border-dim); border-radius: 6px; overflow: hidden; background: var(--bg-surface); }
.atw-img { display: block; width: 100%; aspect-ratio: 3 / 4; object-fit: cover; background: #0c0c12; }
.atw-none { display: flex; align-items: center; justify-content: center; width: 100%; aspect-ratio: 3 / 4;
  background: #0c0c12; color: var(--text-dim); font-size: 11px; }
.atw-name { padding: 4px 6px 0; font-size: 11px; color: var(--text-primary);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.atw-meta { padding: 0 6px 5px; font-family: var(--font-mono); font-size: 10px; color: var(--text-dim); text-align: right; }
`;

function ensureStyle(doc) {
  if (doc.getElementById(STYLE_ID)) return;
  const style = doc.createElement('style');
  style.id = STYLE_ID;
  style.textContent = ATW_CSS;
  doc.head.appendChild(style);
}

function shortCount(value) {
  const n = Number(value) || 0;
  if (n <= 0) return '';
  if (n < 1000) return String(n);
  const k = n / 1000;
  return `${k >= 10 ? Math.round(k) : Math.round(k * 10) / 10}k`;
}

export function createArtistTagWindow({
  document: doc,
  window: win = (typeof window !== 'undefined' ? window : null),
  fetch: fetchFn = win.fetch.bind(win),
  // 지금의 메인 프롬프트 글.
  getPrompt = () => '',
  // Artist Thumbnail 에서 고른 모드(팩 계열을 정한다). 모르면 빈 글 - 서버가 API 모드로 고른다.
  getThumbMode = () => '',
  escHtml = v => String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'),
  onVisibilityChange = () => {},
}) {
  ensureStyle(doc);
  let serial = 0;      // 늦게 온 응답이 새 목록을 덮지 않게
  const panel = createDraggablePanel({
    document: doc, window: win, id: 'artistTagWindow', title: '아티스트 태그 관리',
    variant: 'em-overlay em-window atw-window', storageKey: 'artist-tag-manager',
    width: 500, height: 460, minWidth: 260, maxWidth: 960, minHeight: 200, resizable: true,
    escHtml,
    onOpen: () => { load(); onVisibilityChange(); },
    onClose: () => { serial += 1; onVisibilityChange(); },
  });
  const count = doc.createElement('span');
  count.className = 'atw-count';
  panel.slot.append(count);

  function note(text, isError = false) {
    panel.body.innerHTML = `<div class="atw-note${isError ? ' is-error' : ''}">${escHtml(text)}</div>`;
  }

  function tileHtml(row) {
    const name = String(row.name || '');
    const posts = shortCount(row.count);
    const tip = row.image_url ? `${name} · ${row.pack_label || row.pack || ''}` : `${name} · 받은 팩에 이 작가의 그림이 없습니다`;
    const picture = row.image_url
      ? `<img class="atw-img" loading="lazy" alt="" src="${escHtml(row.image_url)}">`
      : '<div class="atw-none">데이터 없음</div>';
    return `<div class="atw-tile" title="${escHtml(tip)}">${picture}`
      + `<div class="atw-name">${escHtml(name)}</div><div class="atw-meta">${escHtml(posts || ' ')}</div></div>`;
  }

  async function load() {
    const mine = ++serial;
    count.textContent = '';
    note('작가를 찾는 중… 처음 여는 팩은 몇 초 걸립니다.');
    let data = null;
    try {
      const response = await fetchFn('/api/artist-thumb/used', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({text: String(getPrompt() || ''), mode: String(getThumbMode() || '')}),
      });
      data = await response.json();
      if (!response.ok || !data?.ok) throw new Error(data?.error || `HTTP ${response.status}`);
    } catch (error) {
      if (mine !== serial) return;
      note(`작가 목록을 읽지 못했습니다 - ${error?.message || error}`, true);
      return;
    }
    if (mine !== serial) return;
    const rows = Array.isArray(data.artists) ? data.artists : [];
    count.textContent = rows.length ? `${rows.length}명` : '';
    if (!rows.length) { note('메인 프롬프트에 작가 태그가 없습니다.'); return; }
    panel.body.innerHTML = `<div class="atw-grid">${rows.map(tileHtml).join('')}</div>`;
  }

  // 그림을 못 읽은 타일은 '데이터 없음' 으로 바꾼다(팩이 그사이 갈린 경우).
  panel.body.addEventListener('error', event => {
    const img = event.target;
    if (!img?.classList?.contains('atw-img')) return;
    const empty = doc.createElement('div');
    empty.className = 'atw-none';
    empty.textContent = '데이터 없음';
    img.replaceWith(empty);
  }, true);

  return {
    open: () => panel.open(),
    close: () => panel.close(),
    toggle: () => panel.toggle(),
    isOpen: () => panel.isOpen(),
    el: panel.el,
  };
}
