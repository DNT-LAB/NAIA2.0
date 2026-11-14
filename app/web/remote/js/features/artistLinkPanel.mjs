/**
 * 결과 화면 작가 패널(사용자 지정 2026-11-03).
 *
 * [메인 랜덤 버튼 연결] 이 켜져 있으면 결과 화면 왼쪽 아래(시드 고정 알약 오른쪽)에 **늘** 뜬다.
 * 다루는 작가 = **보이는 그림에 붙은 작가**(히스토리 `linked_artist`). Auto Gen 은 다음 컷을 미리 만들므로
 * '마지막으로 뽑힌 작가' 를 쓰면 엉뚱한 작가를 숨긴다.
 * 예외 = **'다음' 작가**(사용자 지정 2026-11-14): 사람이 누른 Random 이 붙인 작가는 그림이 나오기 전부터 보인다(`setPending`).
 * 보이는 그림이 실제로 바뀌면(새 결과 · 다른 히스토리 그림) 풀리고(`noteDisplayChanged`), 글에서 그 작가가 사라져도 풀린다
 * (`checkPrompt`). Auto Gen 은 예전대로 - 화면(app.js)이 Auto Gen 의 글로는 '다음' 작가를 세우지 않는다.
 * '다음' 작가의 [× 가중치] 는 랜덤 가중치와 함께 **지금 프롬프트의 그 작가 가중치**도 바꾼다(`onPendingWeight` · 생성 없음).
 *
 *   [그림 · 이름 × 가중치] [고정] [기억] [제외] [삽입 ▴] [그룹 ▴] [추가 ▴]
 *   좁으면(옆 [… 연동됨] 알약까지 한 줄에 안 들어가면) 두 줄 - 위 = 이름 · 가중치(알약은 그 오른쪽), 아래 = 단추들.
 *
 * - [그림 · 이름] = 누르면 썸네일 미리보기 판을 켜고 끈다(사용자 지정 2026-11-14). 패널 위 왼쪽 끝에 뜨고, 그림은 아티스트
 *   태그 관리와 같은 길(`/api/artist-thumb/used` -> 팩 바이트 색인 -> `/used-image`)로 받는다. 우상단 = [✕] · 모서리 빗금
 *   손잡이(끌어서 크기). 켜짐 · 폭은 이 브라우저에 기억한다(`naia.artistLinkPanel.preview`).
 * - [× 가중치] = 누르면 위에 손잡이(휠 0.01씩). 바꾸면 **랜덤 작가 가중치**(아티스트 창 손잡이)에 바로 반영한다 -
 *   고정하지 않는다(사용자 지정 2026-11-03 · 처음엔 '그 값으로 고정' 이었다). 고정 중이면 고정 작가도 그 값을 쓴다.
 * - [고정] = 다음 Random 도 이 작가 · 이 가중치. [생성 버튼 → 랜덤 아티스트](상위 정책)를 서버가 **빌려** 끄고,
 *   풀면 돌려준다(`ArtistThumbnailService.link_pin`).
 * - [기억] = 패널 전용 그룹 한 칸(`임시 그룹`) - 와일드카드로 바로 쓰이고 재시작해도 남는다. 이름을 붙이면 저장.
 *   사람이 있으면 [그룹 ▴] 맨 위에 그 칸이 뜨고, 누르면 아티스트 그룹 창으로 연다.
 * - [제외] = 제외 작가(예전 이름 [숨김] - 아래 [숨김 ▴] 방식과 겹쳐 바꿨다 · 사용자 지정 2026-11-06).
 *   고정해 둔 작가를 제외하면 정책이 돌아온다.
 * - [추가 ▴] = 붙인 작가를 다른 작가 앞에 추가(기본) / [숨김 ▴] = 다른 작가 전부 숨김(사용자 지정 2026-11-06).
 *   서버 `main_exclusive`(이번 실행에만) - PE 훅이 프리픽스 · 포스트픽스 · 랜덤 행의 다른 작가를 걷는다. 숨김이면 노란 강조.
 * - [삽입 ▴] = 이 작가를 지금 가중치로 PE Prefix 맨 앞 / Postfix 맨 뒤에(사용자 지정 2026-11-04). 이미 있으면 가중치만
 *   바꾼다. 넣은 작가는 위의 삽입 그룹 판(`artistInsertTray.mjs`)이 추적한다. 넣으면 [고정] 은 풀린다([기억] 도 같다).
 * - [그룹] = 관심 작가 + 저장된 그룹. 누르면 넣고 빼기.
 * ⚠️ 상태는 서버가 주인이다 - 조작 응답과 `artist_random_tools` 알림으로만 그린다(다른 탭 · 아티스트 창과 같은 값).
 */
// 미리보기 판 모양 - 이 모듈이 싣는다(style.css 는 바이트로만 고치는 파일이라 새 규칙을 여기 둔다).
const PREVIEW_CSS = `
.artist-link-preview { position: absolute; z-index: 6; box-sizing: border-box; overflow: hidden; border-radius: 8px;
  border: 1px solid rgba(255,240,170,0.35); background: #14161a; color: #e7e2cf; font-size: 11px; }
.artist-link-preview[hidden] { display: none; }
.artist-link-preview .alpv-pic { display: flex; align-items: center; justify-content: center; min-height: 72px; background: #1b1d22; }
.artist-link-preview .alpv-pic img { display: block; width: 100%; height: auto; object-fit: contain; }
.artist-link-preview .alpv-none { padding: 22px 8px; color: #8d887a; text-align: center; }
.artist-link-preview .alpv-foot { display: flex; justify-content: space-between; gap: 6px; padding: 3px 7px; color: #b8b19a; }
.artist-link-preview .alpv-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.artist-link-preview .alpv-meta { flex: none; font-variant-numeric: tabular-nums; }
.artist-link-preview .alpv-x { position: absolute; top: 5px; right: 26px; width: 22px; height: 22px; padding: 0; border: 0;
  border-radius: 6px; background: rgba(20,22,26,0.72); color: #f3eedb; font-size: 12px; line-height: 22px; cursor: pointer; }
.artist-link-preview .alpv-x:hover { background: rgba(20,22,26,0.95); }
/* 누르는 자리 = 네모 전체(22px). 빗금 삼각형은 그림만이다 - 손잡이에 clip-path 를 걸면 누르는 자리도 반쪽이 되어 대각선
   아래를 누르면 판 바닥이 눌리고 글자 선택이 패널 단추까지 번졌다(사용자 제보 2026-11-14). */
.artist-link-preview .alpv-grip { position: absolute; top: 0; right: 0; width: 22px; height: 22px; cursor: nesw-resize;
  touch-action: none; }
.artist-link-preview .alpv-grip::before { content: ''; position: absolute; top: 0; right: 0; width: 18px; height: 18px;
  clip-path: polygon(0 0, 100% 0, 100% 100%);
  background: repeating-linear-gradient(45deg, transparent 0 3px, rgba(243,238,219,0.75) 3px 4.5px); }
/* 판 · 패널은 글자를 고르는 곳이 아니다 - 끌다 번진 선택이 단추 글자를 칠하지 않게. 끄는 동안은 문서 전체를 막는다. */
.artist-link-preview, .artist-link-panel { -webkit-user-select: none; user-select: none; }
html.alpv-resizing, html.alpv-resizing * { -webkit-user-select: none !important; user-select: none !important;
  cursor: nesw-resize !important; }
.artist-link-panel .alp-who[data-alp-preview] { cursor: pointer; border-radius: 999px; }
.artist-link-panel .alp-who[data-alp-preview]:hover { background: rgba(255,240,170,0.10); }
.artist-link-panel .alp-who.is-preview { background: rgba(255,240,170,0.18); }
.artist-link-panel .alp-next { flex: none; align-self: center; padding: 0 5px; border: 1px dashed rgba(255,240,170,0.55);
  border-radius: 999px; color: #f3e6a6; font-size: 10px; line-height: 15px; white-space: nowrap; }
`;

function ensurePreviewStyle(document) {
  if (document.getElementById('artistLinkPreviewStyle')) return;
  const style = document.createElement('style');
  style.id = 'artistLinkPreviewStyle';
  style.textContent = PREVIEW_CSS;
  document.head.appendChild(style);
}

export function installArtistLinkPanel({
  document, fetch = window.fetch.bind(window), showToast, escHtml,
  openGroupWindow = null,          // (groupId) => 그 그룹을 아티스트 그룹 창으로 연다
  onGroupsChanged = null,          // () => 패널이 그룹을 바꿨다 - 열린 그룹 창이 새로 읽는다
  onBanChanged = null,             // (artist, banned) => [숨김] - 아티스트 창의 [제외 작가] 수 · 카드가 따라온다
  onInsert = null,                 // ({artist, weight}) => PE Prefix 맨 앞에 넣는다(있으면 가중치만)
  getThumbMode = null,             // () => 아티스트 창의 팩 계열(미리보기 그림을 찾을 팩 차례)
  onPendingWeight = null,          // ({artist, weight, isCurrent}) => '다음' 작가의 가중치를 지금 프롬프트에서도 바꾼다(실패 = 안내 글)
  storage = (() => { try { return window.localStorage; } catch (_) { return null; } })(),
}) {
  const el = document.getElementById('artistLinkPanel');
  const seedPill = document.getElementById('seedLockPill');
  if (!el) return null;
  const esc = typeof escHtml === 'function' ? escHtml : (value => String(value ?? '').replace(/[&<>"']/g, c => (
    {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c])));

  let tools = null;          // 서버의 랜덤 도구(main_link · link_pin · pin_hold · focus …)
  let artist = '';           // 다루는 작가 = '다음' 작가가 있으면 그것, 없으면 보이는 그림의 작가
  let weight = null;
  let visibleArtist = '';    // 보이는 그림의 작가(`setAsset`)
  let visibleWeight = null;
  let pending = null;        // '다음' 작가 {artist, weight} - 이번 Random 에 붙었고 그 그림은 아직 없다(사용자 지정 2026-11-14)
  let pendingGen = 0;        // '다음' 작가가 바뀔 때마다 오른다 - 늦게 끝난 가중치 고치기가 다른 Random 의 글에 걸리지 않게
  let shownPending = false;
  // 보이는 그림이 바뀌었다 - '다음' 작가는 **그 그림의 정보가 올 때**(다음 setAsset) 내린다. 바로 내리면 그사이 옛 그림의
  // 작가가 잠깐 뜬다. 그사이 새 Random 이 오면 그것이 새 '다음' 작가다(늦게 온 옛 그림의 정보가 그것을 지우지 않는다).
  let pendingEnds = false;
  let info = null;           // GET /api/artist-thumb/link-panel 답(그림 · 숨김 · 임시 · 그룹)
  let infoSeq = 0;
  let busy = false;
  // 보이는 그림이 막 바뀌었고 그 그림의 작가를 아직 모른다 - 그동안 단추는 옛 그림의 작가를 다루므로 막는다(Codex 리뷰 P1).
  let stale = false;
  // '다음' 작가는 보이는 그림의 조회를 기다리지 않는다 - 그 작가는 이미 안다.
  const locked = () => stale && !pending;
  let assetGen = 0;                // 보이는 그림이 바뀔 때마다 오른다 - 기다린 클릭이 다른 그림에 걸리지 않게
  let refreshTimer = null;

  const menu = document.createElement('div');
  menu.className = 'artist-link-menu';
  menu.hidden = true;
  menu.setAttribute('role', 'menu');
  el.after(menu);

  // 가중치 손잡이 - 칩을 누르면 위에 뜬다. 바꾸면 곧바로 랜덤 작가 가중치가 된다(휠은 손잡이 위에서만 받는다).
  const WEIGHT_MIN = 0, WEIGHT_MAX = 2, WEIGHT_STEP = 0.01;
  const weightPop = document.createElement('div');
  weightPop.className = 'artist-link-weight';
  weightPop.hidden = true;
  weightPop.innerHTML = `
    <div class="alp-weight-head"><span class="alp-weight-who"></span><span class="alp-weight-value"></span></div>
    <input type="range" min="${WEIGHT_MIN}" max="${WEIGHT_MAX}" step="${WEIGHT_STEP}" aria-label="가중치">
    <div class="alp-weight-foot">휠 ${WEIGHT_STEP}씩 · 랜덤 가중치에 바로 반영</div>`;
  menu.after(weightPop);

  // [삽입 ▴] - Prefix 맨 앞 / Postfix 맨 뒤 중 고른다(사용자 지정 2026-11-04). 넣은 작가는 삽입 그룹 판이 추적한다.
  const insertMenu = document.createElement('div');
  insertMenu.className = 'artist-link-menu artist-link-insert';
  insertMenu.hidden = true;
  insertMenu.setAttribute('role', 'menu');
  insertMenu.innerHTML = `
    <button type="button" class="alp-menu-item" data-alp-insert="pre" role="menuitem">Prefix 맨 앞에</button>
    <button type="button" class="alp-menu-item" data-alp-insert="post" role="menuitem">Postfix 맨 뒤에</button>`;
  weightPop.after(insertMenu);

  // [추가 ▴] / [숨김 ▴] - 다른 작가를 어떻게 다룰지(사용자 지정 2026-11-06).
  const modeMenu = document.createElement('div');
  modeMenu.className = 'artist-link-menu artist-link-mode';
  modeMenu.hidden = true;
  modeMenu.setAttribute('role', 'menu');
  insertMenu.after(modeMenu);
  // ── 썸네일 미리보기(사용자 지정 2026-11-14) ─────────────────────────────
  //  이름을 누르면 켜고 끈다. 보이는 그림의 작가가 바뀌면 판도 따라간다. 붙은 작가가 없으면 숨는다.
  const PREVIEW_KEY = 'naia.artistLinkPanel.preview';
  const PREVIEW_MIN = 120, PREVIEW_MAX = 330, PREVIEW_DEFAULT = 220;
  const preview = (() => {
    try {
      const saved = JSON.parse(storage?.getItem(PREVIEW_KEY) || 'null');
      const width = Number(saved?.width);
      return {on: saved?.on === true,
        width: Number.isFinite(width) ? Math.min(PREVIEW_MAX, Math.max(PREVIEW_MIN, Math.round(width))) : PREVIEW_DEFAULT};
    } catch (_) {
      return {on: false, width: PREVIEW_DEFAULT};
    }
  })();
  const savePreview = () => { try { storage?.setItem(PREVIEW_KEY, JSON.stringify(preview)); } catch (_) { /* 기억은 장식 */ } };
  const thumbs = new Map();        // `팩 계열\n이름` -> 'loading' | {image_url, count, name} | {none: true}
  ensurePreviewStyle(document);
  const previewEl = document.createElement('div');
  previewEl.className = 'artist-link-preview';
  previewEl.hidden = true;
  previewEl.innerHTML = `
    <div class="alpv-pic"></div>
    <div class="alpv-foot"><span class="alpv-name"></span><span class="alpv-meta"></span></div>
    <button type="button" class="alpv-x" aria-label="미리보기 닫기" title="닫기">✕</button>
    <div class="alpv-grip" aria-hidden="true"></div>`;
  modeMenu.after(previewEl);
  let observedTray = null;

  const linkPill = document.getElementById('artistLinkPill');
  const weightRange = weightPop.querySelector('input');
  let weightTimer = null;
  let weightSaving = null;         // 도는 중인 가중치 저장(다른 단추는 이것을 기다린다 - busy 에 버려지지 않게)
  let weightTicket = 0;            // 버린 가중치 저장 표(연결이 꺼지면 오른다 - 이미 기다리는 저장도 멈춘다)

  const formatWeight = value => {
    const n = Number(value);
    if (!Number.isFinite(n) || Math.abs(n - 1) < 1e-9) return '';
    return String(Math.round(n * 100) / 100);
  };
  const seedShown = () => Boolean(seedPill && seedPill.offsetParent !== null && seedPill.offsetWidth > 0);
  // 메인 Random 은 늘 뽑는다 - [고정](`link_pin`) 중일 때만 그 작가(`pin_artist`)를 붙인다(사용자 지시 2026-11-03).
  // `focus`(아티스트 창 격자에서 고른 작가)와 다르다 - 격자를 눌러도 고정은 안 옮겨 간다.
  const pinnedHere = () => Boolean(tools && artist && tools.link_pin && tools.pin_artist === artist);
  const weightNumber = () => (Number.isFinite(Number(weight)) && weight !== null ? Number(weight) : 1);
  const weightLabel = () => formatWeight(weightNumber()) || '1';

  /** [그룹 ▴] 메뉴는 그 단추 바로 위에(사용자 지정 2026-11-04 - 패널 왼쪽 끝에 붙어 단추와 멀었다).
   *  오른쪽이 모자라면 뷰어 안으로 당긴다. */
  function placeGroupMenu() {
    const button = el.querySelector('[data-alp="group"]');
    let left = el.offsetLeft + (button ? button.offsetLeft : 0);
    const room = menu.offsetParent ? menu.offsetParent.clientWidth - menu.offsetWidth - 4 : Infinity;
    if (Number.isFinite(room)) left = Math.min(left, room);
    menu.style.left = `${Math.max(0, left)}px`;
  }

  /** 한 줄에 안 들어가면 두 줄(사용자 지정 2026-11-06). 옆 [… 연동됨] 알약 폭까지 센다 - 휴대폰에서 알약이 잘렸다.
   *  두 줄이면 뷰어에 `--alp-row-lift` 를 실어 메뉴 · 손잡이 · 연동됨 알약이 위 줄 위로 비켜 선다. */
  function fitRows() {
    const host = el.offsetParent;
    if (!host) return;
    // 클래스를 껐다 켜며 재지 않는다 - [… 연동됨] 알약 쪽이 이 패널의 클래스 변화를 보고 자리를 옮기므로 매번 바꾸면
    // 서로 부르며 돈다. 두 줄일 때 한 줄 폭 = 두 줄의 폭 합(줄마다 테두리 몇 px 더 셈 - 경계에서 흔들리지 않는 여유).
    const twoNow = el.classList.contains('is-two-row');
    const rows = el.querySelectorAll('.alp-row');
    const oneRowWidth = twoNow
      ? [...rows].reduce((sum, row) => sum + row.offsetWidth, 0)
      : Math.max(el.offsetWidth, el.scrollWidth);
    const pillWidth = linkPill && !linkPill.hidden ? linkPill.offsetWidth + 6 : 0;
    const room = host.clientWidth - el.offsetLeft - 8;
    const two = Boolean(artist) && rows.length > 1 && room > 0 && oneRowWidth + pillWidth > room;
    if (two !== twoNow) el.classList.toggle('is-two-row', two);
    const lift = two ? `${Math.max(0, el.offsetHeight - 26)}px` : '0px';
    if (el.parentElement && el.parentElement.style.getPropertyValue('--alp-row-lift') !== lift) {
      el.parentElement.style.setProperty('--alp-row-lift', lift);
    }
  }

  function place() {
    if (el.hidden || !seedPill) return;
    el.style.left = `${seedPill.offsetLeft + seedPill.offsetWidth + 6}px`;
    fitRows();
    if (!menu.hidden) placeGroupMenu();
    if (!weightPop.hidden) {
      const chip = el.querySelector('[data-alp="weight"]');
      weightPop.style.left = `${el.offsetLeft + (chip ? chip.offsetLeft : 0)}px`;
    }
    placePreview();
  }

  const thumbKey = name => `${String(getThumbMode?.() || '')}\n${name}`;
  const shortCount = value => {
    const n = Number(value) || 0;
    if (n <= 0) return '';
    if (n < 1000) return String(n);
    const k = n / 1000;
    return `${k >= 10 ? Math.round(k) : Math.round(k * 10) / 10}k`;
  };

  /** 이 작가의 그림 - 아티스트 태그 관리와 같은 길(팩 차례대로 색인을 보고 처음 찾은 팩의 그림 주소). */
  async function loadThumb(name) {
    const key = thumbKey(name);
    if (thumbs.has(key)) return;
    thumbs.set(key, 'loading');
    let row = null;
    try {
      // 이름의 괄호는 SD 묶음으로 읽히지 않게 이스케이프한다(메인 Random 이 붙이는 토큰과 같은 글).
      const text = `artist:${name.replace(/([()])/g, '\\$1')}`;
      const res = await fetch('/api/artist-thumb/used', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({text, mode: String(getThumbMode?.() || '')}),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data?.ok) throw new Error(data?.error || `HTTP ${res.status}`);
      const rows = Array.isArray(data.artists) ? data.artists : [];
      row = rows.find(r => String(r?.name || '').toLowerCase() === name.toLowerCase()) || rows[0] || null;
      thumbs.set(key, row?.image_url ? row : {none: true, count: row?.count});
    } catch (_) {
      thumbs.delete(key);                              // 다음에 켤 때 다시 묻는다
      thumbs.set(`${key}\nerror`, true);
    }
    if (thumbs.size > 200) thumbs.delete(thumbs.keys().next().value);
    if (artist === name) renderPreview();
  }

  function renderPreview() {
    const show = preview.on && !el.hidden && Boolean(artist);
    el.querySelector('.alp-who')?.classList.toggle('is-preview', preview.on);
    if (previewEl.hidden !== !show) previewEl.hidden = !show;
    if (!show) return;
    const key = thumbKey(artist);
    const row = thumbs.get(key);
    const failed = !row && thumbs.has(`${key}\nerror`);
    if (!row && !failed) void loadThumb(artist);
    const pic = previewEl.querySelector('.alpv-pic');
    const want = row && row !== 'loading' && !row.none ? row.image_url : '';
    const img = pic.querySelector('img');
    if (want) {
      if (!img || img.getAttribute('src') !== want) {
        pic.innerHTML = `<img alt="" src="${esc(want)}">`;
        pic.querySelector('img').addEventListener('load', placePreview);
      }
    } else {
      pic.innerHTML = `<div class="alpv-none">${failed ? '그림을 읽지 못했습니다' : row?.none ? '데이터 없음' : '불러오는 중…'}</div>`;
    }
    const count = row && row !== 'loading' && Number.isFinite(Number(row.count)) && Number(row.count) > 0
      ? row.count : (info?.artist === artist ? info.count : null);
    previewEl.querySelector('.alpv-name').textContent = artist;
    previewEl.querySelector('.alpv-meta').textContent = [weightLabel(), shortCount(count)].filter(Boolean).join(' · ');
    previewEl.title = row?.none ? `${artist} · 받은 팩에 이 작가의 그림이 없습니다` : '';
    placePreview();
  }

  /** 패널 위 · 시드 알약 왼쪽 끝에 맞춘다. 삽입 그룹 판이 떠 있으면 그 위로. 높이는 뷰어 안에 들어가게 줄인다. */
  function placePreview() {
    if (previewEl.hidden) return;
    const host = el.offsetParent;
    if (!host) return;
    const tray = el.parentElement?.querySelector('.artist-insert-tray');
    if (tray && tray !== observedTray && typeof ResizeObserver === 'function') {
      observedTray = tray;
      new ResizeObserver(() => placePreview()).observe(tray);   // 판이 뜨고 지면 비켜 선다
    }
    let top = el.offsetTop;
    if (tray && !tray.hidden && tray.offsetHeight > 0) top = Math.min(top, tray.offsetTop);
    const left = seedPill && seedPill.offsetParent ? seedPill.offsetLeft : el.offsetLeft;
    previewEl.style.left = `${left}px`;
    previewEl.style.bottom = `${Math.max(0, host.clientHeight - top + 6)}px`;
    previewEl.style.width = `${Math.max(PREVIEW_MIN, Math.min(preview.width, host.clientWidth - left - 8))}px`;
    const foot = previewEl.querySelector('.alpv-foot')?.offsetHeight || 20;
    const img = previewEl.querySelector('.alpv-pic img');
    if (img) img.style.maxHeight = `${Math.max(60, top - 14 - foot)}px`;
  }

  function setPreview(on) {
    preview.on = Boolean(on);
    if (preview.on) {                                  // 켤 때마다 지난 실패는 다시 묻는다
      for (const key of [...thumbs.keys()]) if (key.endsWith('\nerror')) thumbs.delete(key);
    }
    savePreview();
    renderPreview();
  }

  function render() {
    const show = Boolean(tools?.main_link) && seedShown();
    el.hidden = !show;
    if (!show) {
      closeMenu(); closeInsert(); closeMode(); closeWeight({commit: false});
      el.parentElement?.style.setProperty('--alp-row-lift', '0px');
      renderPreview();
      return;
    }
    if (!artist) {
      shownPending = false;
      el.innerHTML = '<span class="alp-empty" title="이 그림은 메인 Random 이 작가를 붙이지 않았습니다">붙은 작가 없음</span>';
      closeMenu();
      closeInsert();
      closeMode();
      closeWeight();
      place();
      renderPreview();
      return;
    }
    const w = weightLabel();
    const image = info?.artist === artist ? info.image_url : '';
    const pin = pinnedHere();
    const slot = info?.artist === artist ? info.slot : null;
    const banned = info?.artist === artist && info.banned;
    const pinTitle = pin ? '고정 해제 - 다시 무작위로 뽑습니다' : '다음 Random 에도 이 작가를 붙입니다';
    // 이름 툴팁 = 게시물 수(사용자 지정 2026-11-04 - 가중치는 옆 칩에 이미 있다). 사전에 없는 작가면 이름만.
    const count = info?.artist === artist && Number.isFinite(info.count) ? info.count : null;
    const whoTitle = count === null ? artist : `${artist} · 게시물 ${count.toLocaleString('en-US')}`;
    const exclusive = Boolean(tools?.main_exclusive);
    shownPending = Boolean(pending);
    el.innerHTML = `
      <span class="alp-row alp-row-who">${pending ? `
      <span class="alp-next" title="이번 Random 에 붙은 작가 - 그림이 나오면 그 그림의 작가로 바뀝니다">다음</span>` : ''}
      <span class="alp-who${preview.on ? ' is-preview' : ''}" data-alp-preview role="button" tabindex="0"
        aria-pressed="${preview.on}" title="${esc(`${whoTitle}\n눌러서 썸네일 미리보기 ${preview.on ? '끄기' : '켜기'}`)}">
        ${image ? `<img class="alp-thumb" src="${esc(image)}" alt="" loading="lazy">`
    : `<span class="alp-thumb alp-thumb-blank" aria-hidden="true">${esc(artist.slice(0, 1).toUpperCase())}</span>`}
        <span class="alp-name">${esc(artist)}</span>
      </span>
      <button type="button" class="alp-weight${weightPop.hidden ? '' : ' is-open'}" data-alp="weight"
        aria-expanded="${!weightPop.hidden}" title="가중치 조절 - 바꾸면 랜덤 작가 가중치에 바로 반영합니다">× ${esc(w)}</button>
      </span>
      <span class="alp-row alp-row-btns">
      <button type="button" class="alp-btn${pin ? ' is-on' : ''}" data-alp="pin" aria-pressed="${pin}" title="${esc(pinTitle)}">고정</button>
      <button type="button" class="alp-btn${slot?.has ? ' is-on' : ''}" data-alp="slot" aria-pressed="${Boolean(slot?.has)}"
        title="${esc(`${slot?.name || '임시 그룹'} 에${slot?.has ? '서 뺍니다' : ' 담습니다'} - 와일드카드로 쓰이고 재시작해도 남습니다. [그룹 ▴] 에서 열어 이름을 붙이면 저장됩니다.`)}">기억</button>
      <button type="button" class="alp-btn alp-ban${banned ? ' is-on' : ''}" data-alp="ban" aria-pressed="${Boolean(banned)}"
        title="${banned ? '제외 작가에서 뺍니다' : '제외 작가로 - 다음부터 뽑히지 않습니다'}">제외</button>
      <button type="button" class="alp-btn" data-alp="insert" aria-haspopup="menu" aria-expanded="${!insertMenu.hidden}"
        title="${esc(`× ${w} 로 Prefix 맨 앞 · Postfix 맨 뒤에 넣습니다 - 이미 있으면 가중치만 바꾸고, 위의 삽입 그룹에서 추적합니다`)}">삽입 ▴</button>
      <button type="button" class="alp-btn" data-alp="group" aria-haspopup="menu" aria-expanded="${!menu.hidden}" title="그룹에 담기">그룹 ▴</button>
      <button type="button" class="alp-btn alp-mode${exclusive ? ' is-on' : ''}" data-alp="mode" aria-haspopup="menu"
        aria-expanded="${!modeMenu.hidden}" title="${exclusive
    ? '다른 작가 전부 숨김 - 붙인 작가만 나갑니다(PE 프리픽스 · 포스트픽스 · 랜덤 행의 작가를 이번 생성에서 뺌)'
    : '다른 작가 앞에 추가 - 붙인 작가를 PE 프리픽스 맨 앞에 더합니다(기본)'}">${exclusive ? '숨김' : '추가'} ▴</button>
      </span>`;
    place();
    renderPreview();
  }

  // ── 다른 작가 방식 메뉴 ────────────────────────────────────────────────
  function renderModeMenu() {
    const exclusive = Boolean(tools?.main_exclusive);
    const item = (value, label) => `
      <button type="button" class="alp-menu-item" data-alp-mode="${value}" role="menuitemradio"
        aria-checked="${exclusive === (value === 'hide')}"><span class="alp-check" aria-hidden="true">${exclusive === (value === 'hide') ? '✓' : ''}</span>
        <span>${label}</span></button>`;
    modeMenu.innerHTML = item('add', '다른 작가 앞에 추가 (기본)') + item('hide', '다른 작가 전부 숨김');
  }

  function openMode(button) {
    closeMenu();
    closeInsert();
    renderModeMenu();
    modeMenu.hidden = false;
    let left = el.offsetLeft + (button ? button.offsetLeft : 0);
    const room = modeMenu.offsetParent ? modeMenu.offsetParent.clientWidth - modeMenu.offsetWidth - 4 : Infinity;
    if (Number.isFinite(room)) left = Math.min(left, room);
    modeMenu.style.left = `${Math.max(0, left)}px`;
    el.querySelector('[data-alp="mode"]')?.setAttribute('aria-expanded', 'true');
  }

  function closeMode() {
    if (modeMenu.hidden) return;
    modeMenu.hidden = true;
    el.querySelector('[data-alp="mode"]')?.setAttribute('aria-expanded', 'false');
  }

  async function setExclusive(on) {
    try {
      const res = await fetch('/api/artist-thumb/options', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({random_tools: {main_exclusive: on}}),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
      if (data.random_tools) tools = data.random_tools;
      render();
      showToast?.(on ? '다른 작가를 전부 숨기고 붙인 작가만 넣습니다.' : '붙인 작가를 다른 작가 앞에 추가합니다.', 'info');
    } catch (error) {
      showToast?.(`바꾸지 못했습니다: ${error.message || error}`, 'error');
    }
  }

  async function loadInfo() {
    const seq = ++infoSeq;
    const target = artist;
    try {
      const res = await fetch(`/api/artist-thumb/link-panel?artist=${encodeURIComponent(target)}`, {cache: 'no-store'});
      const data = await res.json().catch(() => ({}));
      if (seq !== infoSeq || !res.ok) return;
      if (data.tools) tools = data.tools;
      info = target ? data : null;
      render();
      if (!menu.hidden) renderMenu();
    } catch (_) { /* 다음 알림 때 다시 */ }
  }

  function scheduleRefresh(delay = 150) {
    if (refreshTimer) clearTimeout(refreshTimer);
    refreshTimer = setTimeout(() => { refreshTimer = null; void loadInfo(); }, delay);
  }

  async function op(name, extra = {}) {
    if (busy || !artist) return null;
    busy = true;
    el.classList.add('is-busy');
    const target = artist;
    try {
      const res = await fetch('/api/artist-thumb/link-panel', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({op: name, artist, weight, ...extra}),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      if (data.tools) tools = data.tools;
      if (artist === target) {
        infoSeq += 1;                                  // 늦게 온 옛 조회가 덮지 않게
        if (data.artist === artist) info = data;
      } else {
        scheduleRefresh();                             // 그사이 그림이 바뀌었다 - 그 그림의 조회는 살려 두고 새로 받는다
      }
      render();
      if (!menu.hidden) renderMenu();
      if (name === 'slot' || name === 'group' || name === 'group_new') onGroupsChanged?.();
      return data;
    } catch (error) {
      showToast?.(error.message || '작가 패널 조작에 실패했습니다.', 'error');
      return null;
    } finally {
      busy = false;
      el.classList.remove('is-busy');
    }
  }

  // ── 그룹 메뉴 ──────────────────────────────────────────────────────────
  function renderMenu() {
    const groups = info?.artist === artist ? (info.groups || []) : [];
    const slot = info?.artist === artist ? info.slot : null;
    // [기억] 칸에 사람이 있으면 맨 위에 - 누르면 그 칸을 아티스트 그룹 창으로 연다(넣고 빼기는 [기억] 단추).
    const slotRow = slot?.id && slot.count > 0 ? `
      <button type="button" class="alp-menu-item alp-menu-slot" data-alp-slot-open="${esc(slot.id)}" role="menuitem"
        title="${esc(slot.name)} 창을 엽니다"><span class="alp-check" aria-hidden="true">${slot.has ? '✓' : ''}</span>
        <span>${esc(slot.name)}</span><span class="alp-menu-count">${Number(slot.count)}명 ↗</span></button>
      <div class="alp-menu-sep" role="separator"></div>` : '';
    menu.innerHTML = `${slotRow}
      ${groups.map(g => `
        <button type="button" class="alp-menu-item${g.has ? ' is-on' : ''}" data-alp-group="${esc(g.id)}" role="menuitemcheckbox"
          aria-checked="${Boolean(g.has)}"><span class="alp-check" aria-hidden="true">${g.has ? '✓' : ''}</span><span>${esc(g.name)}</span></button>`).join('')}
      <div class="alp-menu-sep" role="separator"></div>
      <form class="alp-menu-new" data-alp-new>
        <input type="text" maxlength="40" placeholder="새 그룹 이름" aria-label="새 그룹 이름">
        <button type="submit" class="alp-btn">만들기</button>
      </form>`;
  }

  function openMenu() {
    closeInsert();
    closeMode();
    renderMenu();
    menu.hidden = false;
    placeGroupMenu();
    el.querySelector('[data-alp="group"]')?.setAttribute('aria-expanded', 'true');
    void loadInfo();                                   // 그룹 창에서 바뀐 것까지 - 열 때 새로 받는다
  }

  function openInsert(button) {
    closeMenu();
    closeMode();
    insertMenu.hidden = false;
    // 단추는 줄(.alp-row) 안에 있어도 자리는 패널(position:absolute)에서 잰다 - 줄은 위치 기준이 아니다.
    insertMenu.style.left = `${el.offsetLeft + (button ? button.offsetLeft : 0)}px`;
    el.querySelector('[data-alp="insert"]')?.setAttribute('aria-expanded', 'true');
  }

  function closeInsert() {
    if (insertMenu.hidden) return;
    insertMenu.hidden = true;
    el.querySelector('[data-alp="insert"]')?.setAttribute('aria-expanded', 'false');
  }

  function closeMenu() {
    if (menu.hidden) return;
    menu.hidden = true;
    el.querySelector('[data-alp="group"]')?.setAttribute('aria-expanded', 'false');
  }

  // ── 가중치 손잡이 ──────────────────────────────────────────────────────
  function paintWeight() {
    const w = weightLabel();
    const chip = el.querySelector('[data-alp="weight"]');
    if (chip) chip.textContent = `× ${w}`;
    weightPop.querySelector('.alp-weight-who').textContent = artist;
    weightPop.querySelector('.alp-weight-value').textContent = weightNumber().toFixed(2);
    renderPreview();
  }

  function openWeight() {
    closeMenu();
    weightRange.value = String(weightNumber());
    weightPop.hidden = false;
    paintWeight();
    render();
    weightRange.focus({preventScroll: true});
  }

  /** 손잡이를 닫는다. `commit` = 대기 중인 값을 지금 보낸다(아니면 버린다). 돌려주는 값 = 도는 가중치 저장. */
  function closeWeight({commit = true} = {}) {
    if (!commit) weightTicket += 1;
    if (weightTimer) {
      clearTimeout(weightTimer);
      weightTimer = null;
      if (commit) startWeightCommit();
    }
    if (!weightPop.hidden) {
      weightPop.hidden = true;
      el.querySelector('[data-alp="weight"]')?.classList.remove('is-open');
      el.querySelector('[data-alp="weight"]')?.setAttribute('aria-expanded', 'false');
    }
    return weightSaving || Promise.resolve();
  }

  function startWeightCommit() {
    const saving = commitWeight(artist);
    weightSaving = saving;
    saving.finally(() => { if (weightSaving === saving) weightSaving = null; });
    return saving;
  }

  function setWeight(value) {
    const n = Math.min(WEIGHT_MAX, Math.max(WEIGHT_MIN, Math.round(Number(value) / WEIGHT_STEP) * WEIGHT_STEP));
    if (!Number.isFinite(n)) return;
    weight = Math.round(n * 100) / 100;
    if (pending && pending.artist === artist) pending.weight = weight;
    weightRange.value = String(weight);
    paintWeight();
    if (weightTimer) clearTimeout(weightTimer);
    weightTimer = setTimeout(() => { weightTimer = null; startWeightCommit(); }, 150);   // 휠 한 칸마다 쓰지 않게만
  }

  // 바꾼 값을 랜덤 작가 가중치로 보낸다(고정은 건드리지 않는다). 다른 조작이 도는 중이면 끝난 뒤에.
  async function commitWeight(target) {
    const ticket = weightTicket;
    // '다음' 작가면 지금 프롬프트의 그 작가 가중치도 바꾼다 - 이 값 · 이 '다음' 작가일 때만(기다리는 사이 Random 이 오면 버린다).
    const pend = pending && pending.artist === target ? {gen: pendingGen, weight} : null;
    while (busy) await new Promise(resolve => setTimeout(resolve, 80));
    if (ticket !== weightTicket) return;                // 기다리는 사이 연결이 꺼졌다 - 보내지 않는다
    if (!artist || artist !== target) return;          // 기다리는 사이 그림이 바뀌었다 - 옛 손잡이 값은 버린다
    await op('weight');
    if (!pend || pend.gen !== pendingGen || typeof onPendingWeight !== 'function') return;
    const isCurrent = () => pend.gen === pendingGen;
    const problem = await onPendingWeight({artist: target, weight: pend.weight, isCurrent});
    if (typeof problem === 'string' && problem && isCurrent()) showToast?.(problem, 'info');
  }

  // 패널은 결과 뷰어(`.viewer`, draggable) 안에 산다 - 슬라이더 · 단추를 끌면 뷰어 끌기(→ 메타데이터 뷰어)가 시작된다.
  // 자식의 draggable="false" 로는 안 막힌다(dragstart 의 target 이 뷰어다). 누르는 동안만 감싼 끌기를 끈다.
  const holdAncestorDrag = event => {
    const host = event.currentTarget.parentElement?.closest('[draggable="true"]');
    if (!host) return;
    host.draggable = false;
    const restore = () => {
      host.draggable = true;
      window.removeEventListener('pointerup', restore, true);
      window.removeEventListener('pointercancel', restore, true);
    };
    window.addEventListener('pointerup', restore, true);
    window.addEventListener('pointercancel', restore, true);
  };
  for (const node of [el, menu, weightPop, insertMenu, modeMenu, previewEl]) node.addEventListener('pointerdown', holdAncestorDrag);

  // 미리보기 판 - [✕] · 모서리 손잡이. 판 위의 클릭은 뷰어로 보내지 않는다(그림 넘기기 · 열기가 걸리지 않게).
  previewEl.addEventListener('click', event => {
    event.stopPropagation();
    if (event.target.closest('.alpv-x')) setPreview(false);
  });
  previewEl.addEventListener('dblclick', event => event.stopPropagation());
  const grip = previewEl.querySelector('.alpv-grip');
  grip.addEventListener('pointerdown', event => {
    if (event.button !== 0) return;
    event.preventDefault();
    grip.setPointerCapture?.(event.pointerId);
    // 끄는 동안 글자 선택을 막는다 - 이미 걸린 선택도 지운다(사용자 제보 2026-11-14: 패널 단추 글자가 파랗게 칠해졌다).
    window.getSelection?.()?.removeAllRanges?.();
    document.documentElement.classList.add('alpv-resizing');
    const startX = event.clientX, startY = event.clientY, startW = previewEl.offsetWidth;
    // 왼쪽 아래에 붙은 판이라 오른쪽 · 위로 끌면 커진다. 더 크게 움직인 쪽을 따른다.
    const move = ev => {
      const dx = ev.clientX - startX, dy = startY - ev.clientY;
      const d = Math.abs(dx) >= Math.abs(dy) ? dx : dy;
      preview.width = Math.round(Math.min(PREVIEW_MAX, Math.max(PREVIEW_MIN, startW + d)));
      placePreview();
    };
    const up = () => {
      document.documentElement.classList.remove('alpv-resizing');
      grip.removeEventListener('pointermove', move);
      grip.removeEventListener('pointerup', up);
      grip.removeEventListener('pointercancel', up);
      savePreview();
    };
    grip.addEventListener('pointermove', move);
    grip.addEventListener('pointerup', up);
    grip.addEventListener('pointercancel', up);
  });

  weightRange.addEventListener('input', () => setWeight(weightRange.value));
  weightPop.addEventListener('wheel', event => {
    event.preventDefault();
    setWeight(weightNumber() + (event.deltaY < 0 ? WEIGHT_STEP : -WEIGHT_STEP));
  }, {passive: false});

  el.addEventListener('keydown', event => {
    if ((event.key === 'Enter' || event.key === ' ') && event.target.closest?.('[data-alp-preview]')) {
      event.preventDefault();
      setPreview(!preview.on);
    }
  });
  el.addEventListener('click', async event => {
    if (event.target.closest('[data-alp-preview]')) {   // 미리보기는 서버 상태가 아니다 - 그림이 바뀌는 중에도 켜고 끈다
      setPreview(!preview.on);
      return;
    }
    const button = event.target.closest('[data-alp]');
    if (!button || locked()) return;
    const action = button.dataset.alp;
    if (action === 'weight') {
      if (weightPop.hidden) openWeight(); else closeWeight();
      return;
    }
    const gen = assetGen;
    await closeWeight();
    if (locked() || gen !== assetGen) return;          // 저장을 기다리는 사이 그림이 바뀌었다 - 새 그림의 작가에 걸지 않는다
    if (action === 'group') {
      if (menu.hidden) openMenu(); else closeMenu();
      return;
    }
    if (action === 'pin') {
      const wasPinned = pinnedHere();
      const data = await op(wasPinned ? 'unpin' : 'pin');
      if (data) showToast?.(wasPinned ? '고정을 풀었습니다 - 다시 무작위로 뽑습니다.' : `다음 Random 에도 ${artist} 를 붙입니다.`, 'info');
      return;
    }
    if (action === 'slot') {
      const data = await op('slot');
      if (data?.slot) {
        showToast?.(data.slot.has ? `${data.slot.name} 에 기억했습니다(${data.slot.count}명).` : `${data.slot.name} 에서 뺐습니다.`, 'info');
        // 기억했으면 [고정] 을 푼다(사용자 지정 2026-11-04 · [삽입] 과 같은 규칙).
        if (data.slot.has && gen === assetGen && !locked() && pinnedHere()) await op('unpin');
      }
      return;
    }
    if (action === 'insert') {
      if (insertMenu.hidden) openInsert(button); else closeInsert();
      return;
    }
    if (action === 'mode') {
      if (modeMenu.hidden) openMode(button); else closeMode();
      return;
    }
    if (action === 'ban') {
      const wasBanned = Boolean(info?.artist === artist && info.banned);
      const data = await op(wasBanned ? 'unban' : 'ban');
      if (data) onBanChanged?.(artist, !wasBanned);
      if (data) showToast?.(wasBanned ? `${artist} 를 제외 작가에서 뺐습니다.` : `${artist} 를 제외했습니다 - 다음부터 뽑히지 않습니다.`, 'info');
    }
  });

  menu.addEventListener('click', async event => {
    if (locked()) return;
    const slotOpen = event.target.closest('[data-alp-slot-open]');
    if (slotOpen) {
      closeMenu();
      if (openGroupWindow) await openGroupWindow(slotOpen.dataset.alpSlotOpen);
      return;
    }
    const item = event.target.closest('[data-alp-group]');
    if (!item) return;
    const group = (info?.groups || []).find(g => g.id === item.dataset.alpGroup);
    if (!group) return;
    const data = await op('group', {group_id: group.id, add: !group.has});
    if (data) showToast?.(group.has ? `${group.name} 에서 뺐습니다.` : `${group.name} 에 담았습니다.`, 'info');
  });

  menu.addEventListener('submit', async event => {
    const form = event.target.closest('[data-alp-new]');
    if (!form) return;
    event.preventDefault();
    if (locked()) return;
    const input = form.querySelector('input');
    const name = String(input?.value || '').trim();
    if (!name) { input?.focus(); return; }
    const data = await op('group_new', {name});
    if (data) showToast?.(`${name} 그룹을 만들어 담았습니다.`, 'info');
  });

  modeMenu.addEventListener('click', event => {
    const item = event.target.closest('[data-alp-mode]');
    if (!item) return;
    closeMode();
    const on = item.dataset.alpMode === 'hide';
    if (on !== Boolean(tools?.main_exclusive)) void setExclusive(on);
  });

  insertMenu.addEventListener('click', async event => {
    const item = event.target.closest('[data-alp-insert]');
    if (!item || locked()) return;
    const gen = assetGen;
    closeInsert();
    if (gen !== assetGen) return;
    const inserted = await onInsert?.({artist, weight: weightNumber(), slot: item.dataset.alpInsert === 'post' ? 'post' : 'pre'});
    // 넣었으면 [고정] 을 푼다(사용자 지정 2026-11-04) - 글에 들어간 작가를 랜덤 연결이 또 붙이지 않게.
    if (inserted && gen === assetGen && !locked() && pinnedHere()) await op('unpin');
  });

  document.addEventListener('pointerdown', event => {
    if (el.contains(event.target)) return;
    if (!insertMenu.hidden && !insertMenu.contains(event.target)) closeInsert();
    if (!modeMenu.hidden && !modeMenu.contains(event.target)) closeMode();
    if (!menu.hidden && !menu.contains(event.target)) closeMenu();
    if (!weightPop.hidden && !weightPop.contains(event.target)) closeWeight();
  }, true);
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    if (!menu.hidden) { closeMenu(); event.stopPropagation(); }
    if (!insertMenu.hidden) { closeInsert(); event.stopPropagation(); }
    if (!modeMenu.hidden) { closeMode(); event.stopPropagation(); }
    if (!weightPop.hidden) { closeWeight(); event.stopPropagation(); }
  }, true);

  // 시드 알약 폭이 바뀌면(고정 켜고 끔 · 시드 번호) 옆자리를 따라간다 - [아티스트 탭 연동됨] 알약과 같은 방식.
  if (seedPill) {
    // 보임이 바뀔 때만 다시 그린다 - 폭만 바뀌면 자리만 옮긴다(그림이 깜박이지 않게).
    const later = () => {
      const show = Boolean(tools?.main_link) && seedShown();
      if (show === el.hidden) render(); else place();
    };
    if (typeof ResizeObserver === 'function') new ResizeObserver(later).observe(seedPill);
    if (typeof MutationObserver === 'function') {
      new MutationObserver(later).observe(seedPill, {attributes: true, childList: true, characterData: true, subtree: true});
    }
  }
  // [… 연동됨] 알약이 뜨고 지면 한 줄 · 두 줄을 다시 잰다(알약 폭까지 세므로). 폭은 창 크기에도 따른다.
  if (linkPill && typeof MutationObserver === 'function') {
    let pillShown = !linkPill.hidden;
    new MutationObserver(() => {
      if (pillShown === !linkPill.hidden) return;      // 같은 값을 다시 쓴 것 - 무시(서로 부르며 돌지 않게)
      pillShown = !linkPill.hidden;
      if (!el.hidden) place();
    }).observe(linkPill, {attributes: true, attributeFilter: ['hidden']});
  }
  window.addEventListener('resize', () => { if (!el.hidden) place(); });
  // 앱을 켠 직후 - 연결 상태를 안다(가벼운 조회 · 잠깐 뒤에).
  setTimeout(() => { if (!tools) void loadInfo(); }, 1500);

  const paintStale = () => el.classList.toggle('is-stale', locked());
  const readLinked = linked => {
    const name = linked && typeof linked === 'object' ? String(linked.artist || '').trim() : '';
    const w = name && Number.isFinite(Number(linked.weight)) ? Number(linked.weight) : null;
    return {name, w};
  };
  // 다루는 작가를 다시 정한다('다음' 작가 > 보이는 그림의 작가). 바뀌었으면 예전 setAsset 이 하던 일을 한다.
  function settle() {
    const nextArtist = pending ? pending.artist : visibleArtist;
    const nextWeight = pending ? pending.weight : visibleWeight;
    paintStale();
    if (nextArtist === artist && nextWeight === weight) {
      if (shownPending !== Boolean(pending)) render();   // 같은 작가여도 '다음' 표식은 바뀐다
      return;
    }
    assetGen += 1;
    closeWeight();                                     // 손잡이로 바꾼 값은 옛 작가에 먼저 보낸다
    artist = nextArtist;
    weight = nextWeight;
    info = null;
    closeMenu();
    render();
    scheduleRefresh(0);
  }
  function dropPending() {
    pendingEnds = false;
    if (!pending) return;
    pendingGen += 1;
    pending = null;
    settle();
  }
  const promptHas = (text, name) => String(text || '').replace(/\\/g, '').toLowerCase()
    .includes(String(name || '').replace(/\\/g, '').toLowerCase());

  return {
    /** 결과 화면에 보이는 그림의 정보가 왔다 - 그 그림의 `linked_artist`. '다음' 작가가 있으면 그것이 앞선다. */
    setAsset(asset) {
      const {name, w} = readLinked(asset && typeof asset === 'object' ? asset.linked_artist : null);
      if (stale) stale = false;
      visibleArtist = name;
      visibleWeight = w;
      if (pendingEnds) {                               // 바뀐 그림의 정보다 - '다음' 작가는 끝났다
        pendingEnds = false;
        pendingGen += 1;
        pending = null;
      }
      settle();
    },
    /** 보이는 그림이 바뀌기 시작했다(그 그림의 작가는 곧 `setAsset` 으로 온다) - 그때까지 단추를 막는다. */
    markStale() {
      if (!pending) assetGen += 1;                     // '다음' 작가를 다루는 동안은 다루는 작가가 그대로다
      stale = true;
      paintStale();
      if (!pending) closeMenu();
    },
    /** 사람이 누른 Random 이 붙인 작가(`prompt_generated` 의 `linked_artist` · 없으면 null) - 그림이 나오기 전에 보인다. */
    setPending(linked) {
      const {name, w} = readLinked(linked);
      pendingGen += 1;
      pendingEnds = false;
      pending = name ? {artist: name, weight: w} : null;
      settle();
    },
    /** 보이는 그림이 실제로 바뀌었다(새 결과 · 다른 히스토리 그림) - '다음' 작가는 그 그림의 정보가 오면 끝난다.
     *  조회 · 재조회(저장 · 지우기 뒤의 다시 읽기)와는 다르다 - 그것들은 이것을 부르지 않는다. */
    noteDisplayChanged() {
      if (pending) pendingEnds = true;
    },
    /** 프롬프트 글이 바뀌었다 - '다음' 작가가 글에 없으면(손으로 지움 · 다른 글로 바뀜) 푼다. */
    checkPrompt(text) {
      if (pending && !promptHas(text, pending.artist)) dropPending();
    },
    /** 서버 알림(`artist_random_tools`) - 아티스트 창 · 다른 탭이 바꾼 고정 · 숨김도 따라간다. */
    receiveTools(next) {
      if (!next || typeof next !== 'object') return;
      tools = next;
      render();
      if (artist) scheduleRefresh();
    },
    refresh: () => loadInfo(),
  };
}
