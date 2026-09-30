// Electron 임베드(Danbooru Browser)는 다른 떠 있는 창과 같은 draggablePanel 에 산다(끌기 · 크기 조절 · z 레지스트리 ·
// 자리 기억). ⚠️ 다른 창들과 **같은 주소**(쿼리까지)로 불러야 z 레지스트리를 나눠 쓴다 - 다르면 겹침 순서가 깨진다.
import {createDraggablePanel} from './draggablePanel.mjs?v=20260926-childalign';

// Tag-group layout ported from future01 tabs/web_view.py:28-47.
// PRIMARY groups (general is NOT primary — it is broken down below).
const DANBOORU_PRIMARY_GROUPS = [
  ['artist', 'ARTIST'],
  ['copyright', 'COPYRIGHT'],
  ['character', 'CHARACTER'],
  ['meta', 'META'],
];
// 12 GENERAL BREAKDOWN buckets (must match danbooru_routes.DANBOORU_GENERAL_BREAKDOWN_KEYS order).
const DANBOORU_GENERAL_BREAKDOWN_GROUPS = [
  ['character_features', 'CHARACTER FEATURES'],
  ['subject_count', 'SUBJECT COUNT'],
  ['clothing_events', 'CLOTHING EVENTS'],
  ['clothes', 'CLOTHES'],
  ['colors', 'COLORS'],
  ['location_background', 'LOCATION / BACKGROUND'],
  ['expression', 'EXPRESSION'],
  ['pose_action', 'POSE / ACTION'],
  ['objects', 'OBJECTS'],
  ['meta_like', 'META-LIKE'],
  ['noise', 'LOW-FREQ / NOISE'],
  ['other', 'OTHER GENERALS'],
];

// 떠 있는 창의 처음 크기(CSS px). 예전 오버레이는 화면을 통째로 덮었다 - 창은 화면 안에 들어오게 잡는다.
const WINDOW_SIZE = {width: 1180, height: 780};
const WINDOW_MIN = {width: 560, height: 320};
// 웹 칸 격자 hit test 의 점들(칸 폭 · 높이의 비율). 층 사각형으로 못 찾는 것(body 자식 밖으로 넘쳐 나온 고정 위치
// 자손 등)을 받는 대비다. ⚠️ 이것만으로는 칸이 클 때 점 사이가 벌어져 작은 창을 놓친다 - regionCovered 의 1) 참고.
const COVER_STEPS = [0.01, 0.25, 0.5, 0.75, 0.99];
// 겹친 사각형의 모서리 점은 이만큼 안쪽에서 잰다. 끝 픽셀은 칸 밖으로 떨어지고, 둥근 모서리(8~12px)의 바깥 조각은
// 밑이 보여 창을 놓친다(반지름 R 이면 0.3R 안쪽이면 된다 - 6px 는 20px 모서리까지).
const COVER_INSET = 6;

export function createDanbooruBrowserController({
  document,
  window: win = window,
  fetch: fetchFn = window.fetch.bind(window),
  showToast,
  hostElement = null,
  onRequestTab = null,
  onDisplayModeChange = null,
  onLoadPrompt = null,
  onGenerateFromPrompt = null,
  onInsertImageToHistory = null,
}) {
  // Electron shell exposes a native WebContentsView bridge; a plain browser does not.
  const naia = (win && win.naiaShell) || null;
  const embedMode = !!(naia && typeof naia.danbooruAttach === 'function');
  // Electron App은 native WebContentsView를 우측 탭 안에 호스팅할 수 있다(canTabMode).
  // 사용자는 떠 있는 창 / 우측 탭을 머리줄 토글로 선택한다(기본=창, localStorage 저장 - 저장값 이름은
  // 오버레이 시절의 'popup' 그대로 둔다. 바꾸면 사용자가 골라 둔 모드를 잃는다).
  // 일반 Web은 native surface가 없어 항상 기존 경량 lookup 팝업.
  const canTabMode = !!(embedMode && hostElement);
  const DISPLAY_MODE_KEY = 'naia.danbooru.displayMode';
  let displayMode = 'popup';
  if (canTabMode) {
    try {
      const saved = win.localStorage && win.localStorage.getItem(DISPLAY_MODE_KEY);
      if (saved === 'tab' || saved === 'popup') displayMode = saved;
    } catch (_error) {}
  }
  function isTabMode() { return canTabMode && displayMode === 'tab'; }
  // Electron 임베드인데 우측 탭이 아니면 **떠 있는 창**이다(예전의 전체 화면 '팝업' 오버레이 자리).
  function isWindowMode() { return embedMode && !isTabMode(); }

  let panel = null;
  // 떠 있는 창(draggablePanel). 창 모드에서만 있다 - panel(판)은 이 창의 본문에 들어간다.
  let dragWin = null;
  // 최소화 · 모드 전환이 창을 닫을 때는 '닫기' 뒷정리(onWindowClosed)를 건너뛴다.
  let windowQuiet = false;
  let queryInput = null;
  let addressInput = null;
  let viewRegion = null;
  let statusEl = null;
  let resultEl = null;
  let lastQuery = '';
  let lastPost = null;

  // Embedded-view state (Electron only).
  let embedActive = false;
  let lastAutoPostId = null;
  let autoExtractTimer = 0;
  let boundsRaf = 0;
  let unsubscribeNav = null;
  let unsubscribeInsert = null;
  let boundsListener = null;
  let regionObserver = null;   // 웹 칸 크기 변화(창 크기 조절 · 탭 폭 변화)
  let coverObserver = null;    // 다른 창 · 모달이 웹 칸 위로 올라오는지(창 모드)
  let lastSentKey = '';        // 같은 자리를 되풀이해 보내지 않는다

  // Minimize-to-island state (the panel can collapse to a floating pill near
  // the Auto Save control while preserving the embedded view's page state).
  let minimized = false;
  let islandEl = null;
  let islandReposition = null;
  let islandObserver = null;   // 알약 열림/닫힘·탭 전환을 따라 자리를 다시 잡는다
  let islandRaf = 0;

  function escHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function tagGroupHtml(label, values) {
    const list = Array.isArray(values) ? values : [];
    // Group prompt = every tag in this group joined as a comma prompt (full list, not the
    // display-capped slice) so the copy button always yields the complete group.
    const groupPrompt = list.join(', ');
    const copyBtn = list.length
      ? `<button type="button" class="danbooru-group-copy" data-danbooru-copy-group="${escHtml(groupPrompt)}" title="이 그룹을 프롬프트로 복사" aria-label="Copy ${escHtml(label)} prompt">⧉</button>`
      : '';
    const body = list.length
      ? list.slice(0, 120)
          .map(tag => `<button type="button" class="danbooru-tag" data-danbooru-tag="${escHtml(tag)}">${escHtml(tag)}</button>`)
          .join('')
      : '<span class="danbooru-empty">—</span>';
    return `
      <section class="danbooru-tag-group">
        <h3><span class="danbooru-tag-group-name">${escHtml(label)}</span> <span class="danbooru-tag-count">· ${list.length}</span>${copyBtn}</h3>
        <div class="danbooru-tags">${body}</div>
      </section>`;
  }

  function setStatus(message, tone = '') {
    if (!statusEl) return;
    statusEl.textContent = message || '';
    if (tone) statusEl.dataset.tone = tone;
    else delete statusEl.dataset.tone;
  }

  function setBusy(busy) {
    panel?.querySelectorAll('[data-danbooru-busy-control]').forEach(el => {
      el.disabled = !!busy;
    });
  }

  function renderEmpty(message = 'Search by post id, URL, or tags.') {
    if (!resultEl) return;
    resultEl.innerHTML = `<div class="danbooru-result-empty">${escHtml(message)}</div>`;
  }

  function renderPost(post) {
    if (!resultEl) return;
    lastPost = post;
    const tags = post?.tags || {};
    const prompt = String(post?.prompt || '');
    const postUrl = String(post?.post_url || '');
    const breakdown = post?.general_breakdown || {};
    const breakdownTotal = DANBOORU_GENERAL_BREAKDOWN_GROUPS.reduce(
      (sum, [key]) => sum + (Array.isArray(breakdown[key]) ? breakdown[key].length : 0),
      0,
    );
    const primaryHtml = DANBOORU_PRIMARY_GROUPS
      .map(([key, label]) => tagGroupHtml(label, tags[key]))
      .join('');
    // Only non-empty buckets are rendered (desktop setVisible(bool(tags))).
    const breakdownHtml = DANBOORU_GENERAL_BREAKDOWN_GROUPS
      .filter(([key]) => Array.isArray(breakdown[key]) && breakdown[key].length)
      .map(([key, label]) => tagGroupHtml(label, breakdown[key]))
      .join('') || '<span class="danbooru-empty">—</span>';
    resultEl.innerHTML = `
      <section class="danbooru-result-card">
        <header class="danbooru-result-head">
          <div>
            <div class="danbooru-result-kicker">Post ${escHtml(post?.post_id || '')}</div>
            <a class="danbooru-result-link" href="${escHtml(postUrl)}" target="_blank" rel="noopener noreferrer">${escHtml(postUrl || 'Danbooru post')}</a>
          </div>
          <div class="danbooru-result-actions">
            <button type="button" class="danbooru-copy-btn danbooru-apply-btn" data-danbooru-apply-prompt>프롬프트 적용</button>
            ${typeof onGenerateFromPrompt === 'function'
              ? '<button type="button" class="danbooru-gen-btn" data-danbooru-generate title="이 프롬프트로 즉시 이미지 생성">이미지 생성</button>'
              : ''}
          </div>
        </header>
        <div class="danbooru-prompt-box">${escHtml(prompt || 'No prompt preview')}</div>
        <div class="danbooru-tag-groups">${primaryHtml}</div>
        <div class="danbooru-breakdown-head">GENERAL BREAKDOWN <span class="danbooru-tag-count">· ${breakdownTotal}</span></div>
        <div class="danbooru-tag-groups danbooru-breakdown-groups">${breakdownHtml}</div>
      </section>
    `;
  }

  async function loadPost(queryOverride = null) {
    ensurePanel();
    const query = String(queryOverride ?? queryInput?.value ?? '').trim();
    if (!query) {
      renderEmpty('Enter a Danbooru post id, URL, or tag query.');
      setStatus('Query is empty', 'error');
      return false;
    }
    lastQuery = query;
    setBusy(true);
    setStatus('Loading Danbooru post...', 'busy');
    // Embed mode: crawl tags from the already-loaded view DOM (uses the user's session,
    // Cloudflare-safe) and let the backend normalize them — avoids the backend's own
    // donmai request being reset. Falls back to the server-side fetch if extraction fails.
    let requestBody = {query};
    if (embedMode && naia && typeof naia.danbooruExtractPost === 'function') {
      try {
        const res = await naia.danbooruExtractPost();
        if (res && res.ok && res.extracted) {
          requestBody = {query, extracted: res.extracted};
        }
      } catch (_error) { /* fall back to server-side fetch */ }
    }
    try {
      const response = await fetchFn('/api/danbooru/post', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(requestBody),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      renderPost(data);
      setStatus(`#${data.post_id} 태그를 읽었습니다.`, 'ok');
      return true;
    } catch (error) {
      console.error('Danbooru post lookup failed', error);
      renderEmpty(error.message || 'Danbooru lookup failed');
      setStatus(error.message || 'Lookup failed', 'error');
      if (showToast) showToast(error.message || 'Danbooru lookup failed', 'error');
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function openExternalBrowser({query: explicitQuery = null} = {}) {
    const query = String(explicitQuery ?? addressInput?.value ?? queryInput?.value ?? lastQuery ?? '').trim();
    setBusy(true);
    setStatus('Opening Danbooru web...', 'busy');
    try {
      const response = await fetchFn('/api/danbooru/browser/open', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({query}),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      if (data.url) win.open(data.url, '_blank', 'noopener,noreferrer');
      setStatus('Opened in browser', 'ok');
      return true;
    } catch (error) {
      console.error('Danbooru browser open failed', error);
      setStatus(error.message || 'Open failed', 'error');
      if (showToast) showToast(error.message || 'Danbooru web open failed', 'error');
      return false;
    } finally {
      setBusy(false);
    }
  }

  function applyPrompt() {
    const prompt = String(lastPost?.prompt || '').trim();
    if (!prompt) {
      if (showToast) showToast('No Danbooru prompt to apply', 'error');
      return;
    }
    if (typeof onLoadPrompt === 'function') {
      onLoadPrompt(prompt);
      if (showToast) showToast('Danbooru prompt applied', 'success');
    }
  }

  async function copyGroup(value) {
    const text = String(value || '').trim();
    if (!text) {
      if (showToast) showToast('복사할 태그가 없습니다.', 'error');
      return;
    }
    try {
      const clip = win.navigator && win.navigator.clipboard;
      if (clip && typeof clip.writeText === 'function') {
        await clip.writeText(text);
      } else {
        // Fallback for non-secure contexts where navigator.clipboard is absent.
        const scratch = document.createElement('textarea');
        scratch.value = text;
        scratch.style.position = 'fixed';
        scratch.style.opacity = '0';
        document.body.append(scratch);
        scratch.select();
        document.execCommand('copy');
        scratch.remove();
      }
      if (showToast) showToast('프롬프트를 복사했습니다.', 'success');
    } catch (error) {
      console.error('Danbooru group copy failed', error);
      if (showToast) showToast('복사 실패: ' + (error.message || ''), 'error');
    }
  }

  // Mirror of desktop on_generate_with_image_requested: build the prompt from the
  // post, then run it through the host generation pipeline immediately.
  function generateFromPost() {
    const prompt = String(lastPost?.prompt || '').trim();
    if (!prompt) {
      if (showToast) showToast('생성할 Danbooru 프롬프트가 없습니다.', 'error');
      return;
    }
    if (typeof onGenerateFromPrompt !== 'function') {
      applyPrompt();
      return;
    }
    // onGenerateFromPrompt가 false면 생성이 막힌 것(이미 생성 중/연결 없음) — 거짓 성공 토스트 금지.
    const started = onGenerateFromPrompt(prompt) !== false;
    if (showToast) {
      showToast(
        started
          ? 'Danbooru 프롬프트로 이미지 생성을 시작합니다.'
          : '지금은 생성할 수 없습니다 (이미 생성 중이거나 연결이 없습니다).',
        started ? 'success' : 'error',
      );
    }
  }

  // ---- Embedded native view (Electron only) --------------------------------
  // 보내는 자리는 **CSS px**(getBoundingClientRect) 그대로다. 창의 DIP 로 바꾸는 것(× 앱 화면 배율)은 메인
  // 프로세스가 한다 - 배율의 원본이 거기 있고, 배율이 바뀌면 거기서 바로 다시 넣는다(main.cjs danbooruViewBounds).
  function currentViewRect() {
    if (!viewRegion) return null;
    const r = viewRegion.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return null;
    return {x: r.left, y: r.top, width: r.width, height: r.height};
  }

  // 네이티브 뷰는 **모든 HTML 위에** 그려진다. 떠 있는 창 위로 다른 창 · API 설정 모달 · 확인 대화상자가 올라오면
  // 그것들이 웹 칸 밑에 깔려 안 보이고 눌리지도 않는다. 그래서 웹 칸 안의 점들을 hit test 해서 맨 위가 우리 칸이
  // 아니면 '덮였다' 고 보고하고 메인이 그동안 뷰를 숨긴다. 이 창을 누르면(앞으로 오면) 다시 보인다.
  // pointer-events:none 인 툴팁 · 토스트 · 끌기 유령은 hit test 를 지나가므로 여기에 걸리지 않는다.
  // 우측 탭 모드는 재지 않는다 - 바닥층이라 늘 떠 있는 칩 하나에도 뷰가 통째로 사라진다.
  function regionCovered(rect) {
    if (!dragWin || !viewRegion || typeof document.elementFromPoint !== 'function') return false;
    const coveredAt = (x, y) => {
      const hit = document.elementFromPoint(x, y);
      return !!(hit && hit !== viewRegion && !viewRegion.contains(hit));
    };
    // 겹친 사각형이 같은 층(화면을 다 덮는 층이 여럿)은 한 번만 잰다. 점마다 기억하면 겹치는 층이 없는 평소에도
    // 점 25 개를 다 기억해야 해서 오히려 비쌌다(실측) - 겹친 층이 있을 때만 드는 사각형 단위로 기억한다.
    const sampled = new Set();
    const right = rect.x + rect.width;
    const bottom = rect.y + rect.height;
    // 1) 층마다 - 떠 있는 창 · 모달 · 드롭다운 · 확인창은 body 의 최상위 자식으로 붙는다. 층과 웹 칸이 겹치는
    //    사각형 **안**(가운데 + 안쪽 네 모서리)을 잰다. 고정 격자만 쓰던 때는 칸이 크면 점 사이가 벌어져 그 사이에
    //    올라온 작은 창을 놓쳤다(Codex 리뷰: 2098x718 칸의 왼쪽 x=100~400 에 300x250 창 -> 뷰가 그 창을 덮고 입력을
    //    가로챘다). 겹치지 않는 층(닫힌 층은 크기 0)은 hit test 를 하지 않는다. 겹치기만 하고 우리 창 **밑**에 있는
    //    층(앱 화면 등)은 hit test 가 우리 칸을 돌려주므로 덮개가 아니다 - 그래서 점은 반드시 겹친 사각형 안에서 찍는다.
    const layers = document.body ? document.body.children : [];
    for (const layer of layers) {
      if (layer.contains(viewRegion)) continue;          // 우리 창(과 그 조상)
      const box = layer.getBoundingClientRect();
      const left = Math.max(rect.x, box.left);
      const top = Math.max(rect.y, box.top);
      const width = Math.min(right, box.right) - left;
      const height = Math.min(bottom, box.bottom) - top;
      if (!(width > 0 && height > 0)) continue;
      const area = `${Math.round(left)},${Math.round(top)},${Math.round(width)},${Math.round(height)}`;
      if (sampled.has(area)) continue;
      sampled.add(area);
      const ix = Math.min(COVER_INSET, width / 2);
      const iy = Math.min(COVER_INSET, height / 2);
      if (coveredAt(left + width / 2, top + height / 2)
        || coveredAt(left + ix, top + iy) || coveredAt(left + width - ix, top + iy)
        || coveredAt(left + ix, top + height - iy) || coveredAt(left + width - ix, top + height - iy)) {
        return true;
      }
    }
    // 2) 격자 - body 자식의 사각형 밖으로 넘쳐 나온 것(크기 0 인 상자의 고정 위치 자손 등)을 받는 대비.
    for (const fy of COVER_STEPS) {
      for (const fx of COVER_STEPS) {
        if (coveredAt(rect.x + rect.width * fx, rect.y + rect.height * fy)) return true;
      }
    }
    return false;
  }

  function boundsPayload() {
    const rect = currentViewRect();
    // 칸이 사라졌으면(크기 0) 뷰도 비운다 - 예전엔 보고를 건너뛰어 뷰가 마지막 자리에 남았다.
    if (!rect) return {x: 0, y: 0, width: 0, height: 0, hidden: true};
    return {...rect, hidden: regionCovered(rect)};
  }

  function payloadKey(payload) {
    // 배율(devicePixelRatio)도 열쇠에 넣는다 - 배율만 바뀌고 CSS 자리가 같아도 한 번은 다시 보낸다.
    return [payload.x, payload.y, payload.width, payload.height]
      .map(value => Math.round(value * 100) / 100).join(',')
      + (payload.hidden ? ':hidden' : ':shown') + '@' + (win.devicePixelRatio || 1);
  }

  function reportBounds() {
    if (!embedActive || !naia) return;
    const payload = boundsPayload();
    const key = payloadKey(payload);
    if (key === lastSentKey) return;
    lastSentKey = key;
    const pending = naia.danbooruSetBounds(payload);
    if (pending && typeof pending.catch === 'function') pending.catch(() => {});
  }

  function scheduleReportBounds() {
    if (!embedActive) return;
    if (boundsRaf) win.cancelAnimationFrame(boundsRaf);
    boundsRaf = win.requestAnimationFrame(() => {
      boundsRaf = 0;
      reportBounds();
    });
  }

  function onDidNavigate(info) {
    if (addressInput && info && info.url) addressInput.value = info.url;
    const postId = info && info.postId ? String(info.postId) : null;
    if (!postId || postId === lastAutoPostId) return;
    lastAutoPostId = postId;
    if (autoExtractTimer) win.clearTimeout(autoExtractTimer);
    autoExtractTimer = win.setTimeout(() => loadPost(postId), 200);
  }

  async function navigateEmbed(text = null) {
    if (!naia) return;
    const value = String(text ?? addressInput?.value ?? '').trim();
    setBusy(true);
    setStatus('이동 중...', 'busy');
    try {
      const res = await naia.danbooruNavigate(value);
      if (res && res.ok) {
        if (addressInput && res.url) addressInput.value = res.url;
        setStatus('', 'muted');
      } else {
        setStatus((res && res.error) || '이동 실패', 'error');
      }
    } catch (error) {
      setStatus(error.message || '이동 실패', 'error');
    } finally {
      setBusy(false);
    }
  }

  // 창을 끄는 동안은 draggablePanel 이 자리를 옮긴 **그 프레임에** 바로 보낸다. rAF 를 한 번 더 거치면 뷰가
  // 한 프레임씩 늦게 따라온다.
  function onWindowMoved() { reportBounds(); }

  function attachEmbed() {
    if (!embedMode || embedActive) return;
    embedActive = true;
    const payload = boundsPayload();
    lastSentKey = payloadKey(payload);
    naia.danbooruAttach(payload);
    if (typeof naia.onDanbooruDidNavigate === 'function') {
      unsubscribeNav = naia.onDanbooruDidNavigate(onDidNavigate);
    }
    if (typeof naia.onDanbooruInsertHistory === 'function') {
      unsubscribeInsert = naia.onDanbooruInsertHistory(onInsertHistoryEvent);
    }
    // 화면 배율(Ctrl+휠 · Ctrl+± · Ctrl+0)이 바뀌면 CSS 뷰포트가 바뀌어 resize 가 온다(Electron 실측) - 그때
    // 다시 잰다. DIP 환산은 메인이 새 배율로 한다.
    boundsListener = () => scheduleReportBounds();
    win.addEventListener('resize', boundsListener, true);
    win.addEventListener('scroll', boundsListener, true);
    if (dragWin) {
      dragWin.el.addEventListener('dragpanel-move', onWindowMoved);
      dragWin.el.addEventListener('dragpanel-resize', boundsListener);
    }
    // 창 크기 조절 · 우측 탭 폭 변화처럼 resize 없이 칸만 바뀌는 경우.
    if (viewRegion && typeof win.ResizeObserver === 'function') {
      regionObserver = new win.ResizeObserver(() => scheduleReportBounds());
      regionObserver.observe(viewRegion);
    }
    // 다른 창이 앞으로 오거나 모달이 열리고 닫히는 것은 전부 DOM 변화다 - 한 프레임에 한 번만 다시 잰다.
    if (dragWin && document.body && typeof win.MutationObserver === 'function') {
      coverObserver = new win.MutationObserver(() => scheduleReportBounds());
      coverObserver.observe(document.body, {
        subtree: true, childList: true, attributes: true, attributeFilter: ['class', 'style', 'hidden'],
      });
    }
    // Track late layout/reflow after the panel opens.
    win.requestAnimationFrame(() => win.requestAnimationFrame(reportBounds));
  }

  function detachEmbed() {
    if (!embedMode || !embedActive) return;
    embedActive = false;
    lastSentKey = '';
    if (boundsRaf) {
      win.cancelAnimationFrame(boundsRaf);
      boundsRaf = 0;
    }
    if (autoExtractTimer) {
      win.clearTimeout(autoExtractTimer);
      autoExtractTimer = 0;
    }
    if (boundsListener) {
      win.removeEventListener('resize', boundsListener, true);
      win.removeEventListener('scroll', boundsListener, true);
      if (dragWin) dragWin.el.removeEventListener('dragpanel-resize', boundsListener);
      boundsListener = null;
    }
    if (dragWin) dragWin.el.removeEventListener('dragpanel-move', onWindowMoved);
    if (regionObserver) {
      regionObserver.disconnect();
      regionObserver = null;
    }
    if (coverObserver) {
      coverObserver.disconnect();
      coverObserver = null;
    }
    if (typeof unsubscribeNav === 'function') {
      unsubscribeNav();
      unsubscribeNav = null;
    }
    if (typeof unsubscribeInsert === 'function') {
      unsubscribeInsert();
      unsubscribeInsert = null;
    }
    try { naia.danbooruDetach(); } catch (_error) {}
  }

  // 메인 프로세스가 임베드 뷰 세션으로 받아 보낸 이미지(data URL)를 히스토리에 삽입한다.
  // 성공 시 단부루 패널을 최소화해 결과/히스토리가 바로 보이도록 한다(우클릭 → 히스토리에 추가 UX).
  async function onInsertHistoryEvent(payload) {
    payload = payload || {};
    if (payload.error) {
      if (showToast) showToast(payload.error, 'error');
      return;
    }
    const dataUrl = String(payload.dataUrl || '');
    if (!dataUrl.startsWith('data:')) {
      if (showToast) showToast('이미지 데이터를 받지 못했습니다.', 'error');
      return;
    }
    let ok = false;
    try {
      const blob = await (await fetchFn(dataUrl)).blob();
      if (typeof onInsertImageToHistory === 'function') {
        ok = await onInsertImageToHistory({ blob, label: payload.label || 'Danbooru Image' });
      }
    } catch (_error) {
      if (showToast) showToast('히스토리 추가 실패', 'error');
      return;
    }
    if (ok) {
      if (isTabMode() && typeof onRequestTab === 'function') onRequestTab('result');
      else minimizePanel();
    }
  }

  // ---- Minimize-to-island --------------------------------------------------
  function ensureIsland() {
    if (islandEl) return islandEl;
    islandEl = document.createElement('div');
    islandEl.className = 'danbooru-mini-island';
    islandEl.hidden = true;
    islandEl.innerHTML = `
      <button type="button" class="danbooru-mini-label" data-danbooru-restore title="Danbooru 창 펼치기">📦 Danbooru</button>
      <button type="button" class="danbooru-mini-btn" data-danbooru-restore aria-label="펼치기" title="펼치기">▢</button>
      <button type="button" class="danbooru-mini-btn danbooru-mini-close" data-danbooru-island-close aria-label="닫기" title="닫기">×</button>`;
    islandEl.addEventListener('click', event => {
      const target = event.target;
      if (!(target instanceof win.Element)) return;
      if (target.closest('[data-danbooru-island-close]')) {
        closePanel();
      } else if (target.closest('[data-danbooru-restore]')) {
        restorePanel();
      }
    });
    document.body.append(islandEl);
    return islandEl;
  }

  function positionIsland() {
    if (!islandEl || islandEl.hidden) return;
    // 자리: 결과 칸 위쪽 알약 줄, CHARACTER 알약(.cq-box) **바로 오른쪽**(사용자 지정 2026-09-07).
    // 예전엔 Auto Save 에 우측 정렬해 탭 바 줄에 띄웠는데, 캐릭터/조건부 모듈 팝업이
    // right:12px 까지 덮어서 **팝업의 ×·↗ 위에 이 섬의 × 가 얹혔다**(실측: 팝업 × x1383-1411,
    // 섬 × x1395-1417). 알약이 없으면(다른 탭·비-NAI·캐릭터 0) 같은 줄 왼쪽 끝으로 물러선다.
    // 세로는 알약 **머리줄**에 맞춘다 - 패널이 펼쳐지면 .cq-box 가 길어지는데 그 가운데로
    // 내려가면 안 된다.
    const doc = win.document;
    const wrapper = doc.querySelector('.viewer-wrapper');
    const box = doc.querySelector('.cq-float.open .cq-box');
    const head = box && (box.querySelector('.cq-head-row') || box);
    const boxRect = box && box.getBoundingClientRect();
    const headRect = head && head.getBoundingClientRect();
    const wrapRect = wrapper && wrapper.getBoundingClientRect();
    const h = islandEl.offsetHeight;
    const w = islandEl.offsetWidth;
    let left;
    let top;
    if (boxRect && boxRect.width > 0 && headRect && headRect.height > 0) {
      left = boxRect.right + 8;
      top = headRect.top + (headRect.height - h) / 2;
    } else if (wrapRect && wrapRect.width > 0) {
      // .cq-float 의 기본 자리(left:12px; top:40px, 머리 23px)와 같은 줄.
      left = wrapRect.left + 12;
      top = wrapRect.top + 40 + (23 - h) / 2;
    } else {
      left = 12;
      top = 8;
    }
    // 화면 밖으로 나가지 않게 - 좁은 창에서 알약 오른쪽이 없으면 안쪽으로 접는다.
    left = Math.max(8, Math.min(Math.round(left), win.innerWidth - w - 8));
    top = Math.max(8, Math.min(Math.round(top), win.innerHeight - h - 8));
    islandEl.style.right = 'auto';
    islandEl.style.left = `${left}px`;
    islandEl.style.top = `${top}px`;
  }

  function schedulePositionIsland() {
    // Throttle to one reflow per frame — scroll/resize fire in bursts (capture phase
    // catches every scroller), mirroring the embed bounds path's scheduleReportBounds.
    if (islandRaf) win.cancelAnimationFrame(islandRaf);
    islandRaf = win.requestAnimationFrame(() => {
      islandRaf = 0;
      positionIsland();
    });
  }

  function showIsland() {
    ensureIsland();
    islandEl.hidden = false;
    positionIsland();
    if (!islandReposition) {
      islandReposition = () => schedulePositionIsland();
      win.addEventListener('resize', islandReposition, true);
      win.addEventListener('scroll', islandReposition, {capture: true, passive: true});
    }
    // 알약은 resize/scroll 없이도 움직인다(펼침/접힘, 캐릭터 수, 탭 전환). 최소화 중에만 본다.
    if (!islandObserver && typeof win.MutationObserver === 'function') {
      islandObserver = new win.MutationObserver(() => schedulePositionIsland());
      const wrapper = win.document.querySelector('.viewer-wrapper');
      if (wrapper) islandObserver.observe(wrapper, {childList: true, subtree: true, attributes: true, attributeFilter: ['class', 'style']});
      const pane = win.document.getElementById('rightTabResult');
      if (pane) islandObserver.observe(pane, {attributes: true, attributeFilter: ['class']});
    }
  }

  function hideIsland() {
    if (islandEl) islandEl.hidden = true;
    if (islandReposition) {
      win.removeEventListener('resize', islandReposition, true);
      win.removeEventListener('scroll', islandReposition, true);
      islandReposition = null;
    }
    if (islandObserver) {
      islandObserver.disconnect();
      islandObserver = null;
    }
    if (islandRaf) {
      win.cancelAnimationFrame(islandRaf);
      islandRaf = 0;
    }
  }

  function minimizePanel() {
    if (isTabMode()) {
      if (typeof onRequestTab === 'function') onRequestTab('result');
      else setActive(false);
      return;
    }
    if (minimized) return;
    if (!panelIsOpen()) return;
    minimized = true;
    // Detach the native view (removeChildView preserves its page state) so the
    // floating island and the main UI are unobstructed.
    if (embedMode) detachEmbed();
    if (dragWin) {
      // 창은 닫되 '닫기' 로 치지 않는다 - 자리 · 크기는 그대로 두었다가 섬에서 펼치면 같은 자리에 돌아온다.
      windowQuiet = true;
      try { dragWin.close(); } finally { windowQuiet = false; }
    } else {
      panel.classList.remove('open');
      panel.hidden = true;
    }
    showIsland();
  }

  function restorePanel() {
    if (!minimized || !panel) return;
    minimized = false;
    hideIsland();
    if (dragWin) {
      dragWin.open();
    } else {
      panel.hidden = false;
      panel.classList.add('open');
    }
    if (embedMode) attachEmbed();
  }

  function panelIsOpen() {
    if (!panel) return false;
    if (dragWin) return dragWin.isOpen();
    return !panel.hidden && panel.classList.contains('open');
  }

  // 머리줄 [×] 가 draggablePanel 을 닫으면 여기로 온다(Esc · 섬의 [×] 도 closePanel 을 거쳐 온다).
  function onWindowClosed() {
    if (windowQuiet) return;
    detachEmbed();
    minimized = false;
    hideIsland();
  }

  function createWindow() {
    const vw = win.innerWidth || WINDOW_SIZE.width;
    const vh = win.innerHeight || WINDOW_SIZE.height;
    const width = Math.max(WINDOW_MIN.width, Math.min(WINDOW_SIZE.width, vw - 48));
    const height = Math.max(WINDOW_MIN.height, Math.min(WINDOW_SIZE.height, vh - 96));
    const floating = createDraggablePanel({
      document,
      window: win,
      title: 'Danbooru Browser',
      variant: 'dbw',
      storageKey: 'danbooru-browser',
      width,
      height,
      minWidth: WINDOW_MIN.width,
      minHeight: WINDOW_MIN.height,
      maxWidth: 2400,
      resizable: true,
      // 접기 대신 예전 그대로 '최소화 -> 섬'. 둘 다 두면 [–] 가 두 개가 된다.
      collapsible: false,
      closable: true,
      initial: {x: Math.max(8, Math.round((vw - width) / 2)), y: 48},
      escHtml,
      onClose: onWindowClosed,
    });
    floating.slot.innerHTML = `
      ${canTabMode ? '<button type="button" class="dragpanel-btn dbw-mode" data-danbooru-toggle-mode title="우측 탭으로 옮기기">⤡ 탭으로</button>' : ''}
      <button type="button" class="dragpanel-btn dbw-min" data-danbooru-minimize aria-label="최소화" title="최소화">&#8211;</button>`;
    return floating;
  }

  // 왼쪽 = 주소 줄 + 웹 칸(네이티브 뷰가 덮는 빈 자리), 오른쪽 = 상태 + 태그. 창 · 우측 탭이 같이 쓴다.
  function embedBodyHtml() {
    return `
        <div class="danbooru-embed-body">
          <div class="danbooru-embed-left">
            <div class="danbooru-embed-toolbar">
              <button type="button" class="danbooru-nav-btn" data-danbooru-back data-danbooru-busy-control aria-label="Back">←</button>
              <button type="button" class="danbooru-nav-btn" data-danbooru-forward data-danbooru-busy-control aria-label="Forward">→</button>
              <button type="button" class="danbooru-nav-btn" data-danbooru-reload data-danbooru-busy-control aria-label="Reload">⟳</button>
              <input class="danbooru-address-input" data-danbooru-address data-danbooru-busy-control placeholder="URL, post ID, or tag query">
              <button type="button" class="danbooru-nav-btn danbooru-go-btn" data-danbooru-go data-danbooru-busy-control>이동</button>
            </div>
            <div class="danbooru-view-region" data-danbooru-view-region></div>
          </div>
          <div class="danbooru-embed-right">
            <div class="danbooru-status" data-danbooru-status></div>
            <div class="danbooru-results" data-danbooru-results></div>
          </div>
        </div>`;
  }

  // 우측 탭 판 - 머리줄을 판이 직접 그린다. 떠 있는 창은 머리줄([⤡ 탭으로] [–] [×])을 draggablePanel 이 그린다.
  function embedTabHtml() {
    return `
      <div class="danbooru-tool-dialog danbooru-embed">
        <header class="danbooru-tool-header">
          <div>
            <div class="danbooru-tool-kicker">Danbooru</div>
            <h2>Danbooru Browser</h2>
          </div>
          <div class="danbooru-header-actions">
            <button type="button" class="danbooru-mode-btn" data-danbooru-toggle-mode title="떠 있는 창으로 꺼내기">⤢ 창으로</button>
          </div>
        </header>
        ${embedBodyHtml()}
      </div>`;
  }

  function lookupDialogHtml() {
    return `
      <div class="danbooru-tool-dialog">
        <header class="danbooru-tool-header">
          <div>
            <div class="danbooru-tool-kicker">Danbooru</div>
            <h2>Danbooru Tag Lookup</h2>
          </div>
          <button type="button" class="danbooru-close-btn" data-danbooru-close aria-label="Close">×</button>
        </header>
        <div class="danbooru-tool-search">
          <input class="danbooru-query-input" data-danbooru-query data-danbooru-busy-control placeholder="post id, URL, or tags">
          <button type="button" class="danbooru-load-btn" data-danbooru-load data-danbooru-busy-control>Load</button>
          <button type="button" class="danbooru-open-btn" data-danbooru-open-web data-danbooru-busy-control>Open Web</button>
        </div>
        <div class="danbooru-status" data-danbooru-status></div>
        <div class="danbooru-results" data-danbooru-results></div>
      </div>`;
  }

  function ensurePanel() {
    if (panel) return panel;
    panel = document.createElement('section');
    if (isWindowMode()) {
      // 떠 있는 창의 본문. `.danbooru-tool-panel`(전체 화면 오버레이 뼈대)은 달지 않는다.
      panel.className = 'danbooru-window-panel';
      panel.innerHTML = embedBodyHtml();
      dragWin = createWindow();
      dragWin.body.appendChild(panel);
    } else {
      panel.className = 'danbooru-tool-panel';
      if (embedMode) panel.classList.add('danbooru-tool-panel-embed');
      if (isTabMode()) panel.classList.add('danbooru-tab-panel');
      panel.innerHTML = embedMode ? embedTabHtml() : lookupDialogHtml();
      (isTabMode() ? hostElement : document.body).append(panel);
      if (isTabMode()) panel.hidden = true;
    }
    queryInput = panel.querySelector('[data-danbooru-query]');
    addressInput = panel.querySelector('[data-danbooru-address]');
    viewRegion = panel.querySelector('[data-danbooru-view-region]');
    statusEl = panel.querySelector('[data-danbooru-status]');
    resultEl = panel.querySelector('[data-danbooru-results]');
    renderEmpty(embedMode ? '포스트를 열면 자동으로 태그를 읽습니다.' : undefined);

    // 창 모드는 머리줄 단추([⤡ 탭으로] [–])가 판 밖(draggablePanel 머리줄)에 있다 - 창 전체에서 받는다.
    (dragWin ? dragWin.el : panel).addEventListener('click', event => {
      const target = event.target;
      if (!(target instanceof win.Element)) return;
      if (target.closest('[data-danbooru-close]')) {
        closePanel();
      } else if (target.closest('[data-danbooru-load]')) {
        loadPost();
      } else if (target.closest('[data-danbooru-open-web]')) {
        openExternalBrowser();
      } else if (target.closest('[data-danbooru-back]')) {
        naia?.danbooruBack();
      } else if (target.closest('[data-danbooru-forward]')) {
        naia?.danbooruForward();
      } else if (target.closest('[data-danbooru-reload]')) {
        naia?.danbooruReload();
      } else if (target.closest('[data-danbooru-go]')) {
        navigateEmbed();
      } else if (target.closest('[data-danbooru-apply-prompt]')) {
        applyPrompt();
      } else if (target.closest('[data-danbooru-generate]')) {
        generateFromPost();
      } else if (target.closest('[data-danbooru-toggle-mode]')) {
        toggleDisplayMode();
      } else if (target.closest('[data-danbooru-minimize]')) {
        minimizePanel();
      } else if (target.closest('[data-danbooru-copy-group]')) {
        const copyBtn = target.closest('[data-danbooru-copy-group]');
        copyGroup(copyBtn.dataset.danbooruCopyGroup || '');
      } else {
        const tag = target.closest('[data-danbooru-tag]');
        if (tag) {
          const value = tag.dataset.danbooruTag || '';
          if (embedMode) {
            // Danbooru tag search uses underscores within a tag ('blue hair' -> 'blue_hair').
            const tagQuery = value.trim().replace(/\s+/g, '_');
            if (addressInput) addressInput.value = tagQuery;
            navigateEmbed(tagQuery);
          } else if (queryInput) {
            queryInput.value = value;
            queryInput.focus();
          }
        }
      }
    });
    queryInput?.addEventListener('keydown', event => {
      if (event.key === 'Enter') loadPost();
      if (event.key === 'Escape') closePanel();
    });
    addressInput?.addEventListener('keydown', event => {
      if (event.key === 'Enter') navigateEmbed();
      if (event.key === 'Escape') closePanel();
    });
    return panel;
  }

  function openPanel({query = ''} = {}) {
    ensurePanel();
    minimized = false;
    hideIsland();
    if (queryInput && query) queryInput.value = query;
    if (embedMode && addressInput && query) addressInput.value = query;
    if (isTabMode() && typeof onRequestTab === 'function') {
      const activeTab = onRequestTab('danbooru');
      setActive(activeTab === 'danbooru');
    } else if (dragWin) {
      dragWin.open();   // 이미 열려 있으면 앞으로만 부른다
    } else {
      panel.hidden = false;
      panel.classList.add('open');
    }
    if (embedMode && panelIsOpen()) {
      attachEmbed();
      setStatus('포스트를 열면 자동으로 태그를 읽습니다.', 'muted');
      if (query) navigateEmbed(query);
    } else {
      queryInput?.focus();
      setStatus('Ready', 'muted');
    }
    return true;
  }

  function closePanel() {
    if (!panel) return;
    if (isTabMode()) {
      if (typeof onRequestTab === 'function') onRequestTab('result');
      else setActive(false);
      return;
    }
    if (dragWin) {
      // draggablePanel 을 닫으면 onWindowClosed 가 뷰를 떼고 섬을 치운다. 최소화 중(창은 이미 닫힘)이면 직접.
      if (dragWin.isOpen()) dragWin.close();
      else onWindowClosed();
      return;
    }
    detachEmbed();
    minimized = false;
    hideIsland();
    panel.classList.remove('open');
    panel.hidden = true;
  }

  function openBrowser(options = {}) {
    return openPanel(options);
  }

  function setActive(active) {
    if (!isTabMode()) return false;
    if (!active && !panel) return false;
    ensurePanel();
    const nextActive = !!active;
    panel.hidden = !nextActive;
    panel.classList.toggle('open', nextActive);
    if (nextActive) {
      attachEmbed();
      win.requestAnimationFrame(() => win.requestAnimationFrame(reportBounds));
    } else {
      detachEmbed();
    }
    return nextActive;
  }

  function setDisplayMode(next) {
    if (!canTabMode) return;
    if (next !== 'tab' && next !== 'popup') return;
    if (next === displayMode) return;
    // 열려 있던 상태면 새 모드로 재오픈하기 위해 현재 패널을 완전히 헐고(native 뷰는
    // detach만 — 페이지/워밍업 상태 보존) 다른 부모/마크업으로 다시 만든다.
    const wasOpen = panelIsOpen();
    // 재구성으로 패널 DOM 이 비워지지만 native 뷰는 같은 포스트를 유지한다. lastAutoPostId 를
    // 그대로 두면 재부착 후 같은 페이지의 재추출이 억제돼 태그 패널이 빈 채로 남는다(Codex MED).
    // 이전 포스트를 기억했다가 재부착 후 다시 읽는다.
    const priorPost = lastAutoPostId;
    detachEmbed();
    minimized = false;
    hideIsland();
    if (dragWin) {
      // 떠 있는 창을 통째로 거둔다(판은 그 안에 있다). 닫기 뒷정리는 위에서 이미 했다.
      windowQuiet = true;
      try { dragWin.destroy(); } finally { windowQuiet = false; }
      dragWin = null;
    } else if (panel && panel.parentNode) {
      panel.parentNode.removeChild(panel);
    }
    panel = null;
    queryInput = addressInput = viewRegion = statusEl = resultEl = null;
    lastAutoPostId = null;
    displayMode = next;
    try {
      if (win.localStorage) win.localStorage.setItem(DISPLAY_MODE_KEY, next);
    } catch (_error) {}
    // 우측 탭 가용성(app.js)을 갱신 — 창 모드=탭 숨김, 탭 모드=탭 노출.
    if (typeof onDisplayModeChange === 'function') {
      try { onDisplayModeChange(next); } catch (_error) {}
    }
    if (wasOpen) {
      openPanel();
      if (priorPost) {
        if (autoExtractTimer) win.clearTimeout(autoExtractTimer);
        autoExtractTimer = win.setTimeout(() => loadPost(priorPost), 300);
      }
    }
  }

  function toggleDisplayMode() {
    if (!canTabMode) return;
    setDisplayMode(displayMode === 'tab' ? 'popup' : 'tab');
  }

  return {
    closePanel,
    loadPost,
    openBrowser,
    openExternalBrowser,
    openPanel,
    setActive,
    setDisplayMode,
    getDisplayMode: () => displayMode,
    get mode() { return isTabMode() ? 'app' : 'web'; },
  };
}

export const createDanbooruTabController = createDanbooruBrowserController;
