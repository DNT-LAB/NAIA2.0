import { createRatingStore, RATING_KEYS, filteredCount } from './ratingStore.mjs';
import { libraryHtml, librarySignature, recipeSummary, PQL_CSS } from './parquetLibrary.mjs?v=20260921-pql3';

// 검색 층 컴팩트 배치(사용자 지정 2026-09-21): 상단 단추 셋 · 행 수 한 줄 · 등급 한 줄 ·
// [검색 기록 | 검색]. ⚠️ display 를 주는 요소는 [hidden] 짝 규칙을 같이 둔다(이 저장소가 여러 번 밟았다).
const SEARCH_COMPACT_CSS = `
.sp-toolbar{display:flex;gap:4px;align-items:stretch}
.sp-toolbar .search-parquet-control{position:relative;flex:1 1 0;display:flex}
.sp-tbtn{flex:1 1 0;min-width:0;height:24px;padding:0 6px;font-size:10.5px;font-weight:600;border-radius:5px;
  border:1px solid var(--border,#33333f);background:rgba(255,255,255,0.03);color:var(--text-secondary,#c8c8d0);
  cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sp-tbtn:hover{color:var(--text-primary,#e8e8ee);border-color:var(--accent-blue,#8d7bd6)}
.sp-tbtn.is-on{border-color:var(--accent-green,#5a9e6f);color:var(--accent-green,#5a9e6f)}
.search-parquet-host[hidden]{display:none!important}
.sp-counts{display:flex;align-items:center;height:26px;border:1px solid var(--border,#2c2c36);border-radius:6px;
  background:rgba(255,255,255,0.02);font-size:10.5px;color:var(--text-muted,#9a9aa6)}
.sp-count-cell{flex:1 1 0;display:flex;align-items:baseline;gap:4px;padding:0 9px;min-width:0}
.sp-count-label{flex:1 1 auto;white-space:nowrap}
.sp-count-cell b{font-family:var(--font-mono,monospace);font-size:12.5px;color:var(--accent-green,#5a9e6f)}
.sp-unit{font-size:10px}
.sp-count-sep{width:1px;align-self:stretch;margin:5px 0;background:var(--border,#33333f)}
.sp-ratings{display:flex;align-items:center;gap:8px;flex-wrap:nowrap;white-space:nowrap}
.sp-ratings .mod-section-label{margin:0}
.sp-ratings .mod-checkbox-item{display:inline-flex;align-items:center;gap:3px;margin:0}
.sp-ratings .mod-checkbox-label{font-size:10.5px}
.sp-search-row{display:flex;gap:4px;align-items:stretch}
.sp-hist-btn{flex:0 0 auto;height:26px;padding:0 10px;font-size:10.5px;border-radius:5px;cursor:pointer;
  border:1px solid var(--border,#33333f);background:rgba(255,255,255,0.03);color:var(--text-secondary,#c8c8d0)}
.sp-hist-btn:hover{color:var(--text-primary,#e8e8ee)}
.sp-hist-btn.is-on{border-color:var(--accent-blue,#8d7bd6);color:var(--text-primary,#e8e8ee)}
.sp-search-row .mod-start{flex:1 1 auto;height:26px;min-height:26px;font-size:11.5px}
.sp-history{display:flex;flex-direction:column;gap:4px;border:1px solid var(--accent-blue,#8d7bd6);border-radius:6px;padding:5px}
.sp-history[hidden]{display:none!important}
.sp-hist-filter{height:22px;font-size:11px;padding:1px 6px;background:var(--bg-surface,#15151b);color:var(--text-primary,#e8e8ee);
  border:1px solid var(--border,#33333f);border-radius:4px}
.sp-hist-list{max-height:240px;overflow:auto;display:flex;flex-direction:column;gap:2px}
.sp-hist-item{display:flex;align-items:flex-start;gap:4px;padding:4px 6px;border-radius:4px;cursor:pointer}
.sp-hist-item:hover{background:rgba(255,255,255,0.05)}
.sp-hist-text{flex:1;min-width:0}
.sp-hist-q{font-size:11px;color:var(--text-primary,#e8e8ee);word-break:break-all}
.sp-hist-x{font-size:10.5px;color:#e39a9a;word-break:break-all}
.sp-hist-meta{font-size:9.5px;color:var(--text-dimmer,#6c6c78);font-family:var(--font-mono,monospace)}
.sp-hist-del{flex:0 0 auto;border:none;background:transparent;color:var(--text-dimmer,#6c6c78);cursor:pointer;font-size:13px;line-height:1}
.sp-hist-del:hover{color:#f0a0a0}
.sp-hist-empty{font-size:10.5px;color:var(--text-dimmer,#6c6c78);padding:4px}
/* 기간 슬라이더 트랙: 원래 배경이 var(--bg-elevated) 인데 떠 있는 창의 배경도 같은 색이라
   트랙이 사라졌다(사용자 제보). 창 배경 위에서도 보이는 반투명 흰색으로. */
.dr-track{background:rgba(255,255,255,0.13);box-shadow:inset 0 0 0 1px rgba(255,255,255,0.05)}
.search-progress{font-family:var(--font-mono,monospace);font-size:10px;color:var(--text-dim,#888)}
.search-progress:empty{display:none}
`;

export function createSearchPanel({
  document,
  moduleBody,
  searchCountEl,
  escHtml,
  getWs,
  WebSocket,
  getQuickFilter,
  getCurrentModuleId,
  // 검색 화면이 지금 그려져야 하나. 리모컨 창이 주입한다(창이 열려 있으면 참). 없으면 예전처럼
  // 'search' 모듈이 열려 있을 때. ⚠️ 창으로 옮긴 뒤 currentModuleId 는 다시 'search' 가 안 된다 -
  // 이것 없이 옮기면 창이 영영 빈 채로 뜬다.
  isSearchVisible = null,
  // Custom Parquets 는 검색 창 옆 동반 창(searchQuickWindow)에 산다. 목록을 그릴 요소와 여닫기를 받는다.
  libraryHost = null,
  toggleLibrary = () => {},
  showLibrary = () => {},
  isLibraryOpen = () => false,
  bindTagAssist,
  lockTagSurface = () => {},
  unlockTagSurface = () => {},
  // ⚠️ 기본값을 둔다. 이 패널은 원격 브라우저에서도 뜨는데 거기엔 설치 관리자가
  //    없다 - 토스트를 못 띄운다고 검색이 죽으면 안 된다.
  showToast = () => {},
}) {
  let searchingActive = false;
  const searchVisible = () => (typeof isSearchVisible === 'function'
    ? !!isSearchVisible()
    : getCurrentModuleId() === 'search');
  let initialFilterRestoreDone = false; // 시작 시 Tag Filter 자동 Search→Assign 1회 가드
  let latestTagFilterRevision = 0;
  // Rating state lives in one store holding BOTH the generation-pool ratings
  // (active) and the search-execution ratings (search) — distinct concepts,
  // managed together. ratingState/searchRatingState alias the store's live
  // objects so existing in-place reads/writes keep working; the Quick/Tag Filter
  // shares the same store via deps instead of mutating these by reference.
  const ratingStore = createRatingStore();
  const ratingState = ratingStore.active;
  const searchRatingState = ratingStore.search;
  // Rating toggles are always live: local state + count update instantly and the
  // set_active_ratings push is debounced so a burst of clicks coalesces into one
  // backend recompute. No button lock — the backend never emits a rating_update,
  // so the previous lock only ever released via its 4s safety timeout, which read
  // as a fixed minimum delay between rating clicks.
  let ratingSendTimer = null;
  let cachedRatingCounts = null;
  let parquetPickMode = 'load';
  // Render-once model (A4): the search DOM is built once per module open and then
  // patched in place, so the input nodes — and any autocomplete popup bound to
  // them — survive every search_state update (the old full innerHTML rebuild used
  // to destroy the focused field and dismiss its autocomplete). The previous
  // draftSearch shadow is gone: the live input value IS the source of truth while
  // focused. The only residual reconciliation is pendingEcho — the value we just
  // committed to the backend, kept authoritative until the server echoes it back,
  // guarding against a stale search_state overwriting a freshly typed-and-saved
  // value after blur.
  // pendingEcho tracks, per field, the value we just committed to the backend and
  // are awaiting an echo of. A field stays authoritative (incoming server values
  // skipped) until its own echo arrives — so a normalized/diverging sibling field
  // can't freeze it — and re-focusing the field drops its guard (the user is
  // editing again).
  let pendingEcho = { query: null, exclude: null };
  let lastParquetSig = null;
  // 카드 목록이 그려지는 곳 - 동반 창 본문에 붙는다(없으면 떠도는 요소 = 시험·옛 배선).
  const libHost = libraryHost || document.createElement('div');
  libHost.classList.add('search-parquet-host');
  // Custom Parquet 카드 목록(parquetLibrary.mjs) - 다시 그려도 펼침·메뉴·이름 바꾸기 상태를 잇는다.
  let lastLibrary = [];
  let lastProvenance = null;
  const pqlOpen = new Set();
  let pqlMore = null;
  let pqlRenaming = null;
  let pqlConfirmTrash = null;
  let pqlConfirmTimer = null;
  // [검색 기록] - 최근 검색 최대 500개(백엔드 core/search_history.py). 열 때만 받는다.
  let historyItems = [];
  let historyOpen = false;

  document.addEventListener('click', event => {
    if (!event.target.closest('.search-parquet-control')) closeParquetMenu();
  });

  function getRatingState() {
    return ratingState;
  }

  function getActiveRatings() {
    return RATING_KEYS.filter(key => ratingState[key]);
  }

  function setRatingState(nextState) {
    Object.assign(ratingState, nextState);
  }

  function setRatingsFromList(ratings) {
    if (!Array.isArray(ratings)) return;
    for (const key of RATING_KEYS) {
      ratingState[key] = ratings.includes(key);
    }
  }

  function setSearchRatingsFromMap(ratings) {
    if (!ratings || typeof ratings !== 'object') return;
    for (const key of RATING_KEYS) {
      if (key in ratings) searchRatingState[key] = !!ratings[key];
    }
  }

  function setRatingCounts(ratingCounts) {
    if (ratingCounts) cachedRatingCounts = ratingCounts;
  }

  function computeLocalFilteredCount() {
    const quickFilter = getQuickFilter();
    const quickRatingCounts = quickFilter ? quickFilter.getRatingCounts() : null;
    const ratingCounts = (quickFilter && quickFilter.isActive() && quickRatingCounts)
      ? quickRatingCounts
      : cachedRatingCounts;
    if (!ratingCounts || !Object.keys(ratingCounts).length) return null;
    return filteredCount(ratingCounts, ratingState);
  }

  function updateSearchCount(count) {
    searchCountEl.textContent = count;
  }

  function updatePromptGeneratedCount(message) {
    if (message.rating_counts) cachedRatingCounts = message.rating_counts;
    const filtered = computeLocalFilteredCount();
    updateSearchCount(filtered !== null ? filtered : message.remaining);
  }

  function sendActiveRatings() {
    const ws = getWs();
    if (ws && ws.readyState === WebSocket.OPEN) {
      lockTagSurface();   // G/S/Q/E recompute in flight → released by onSearchState
      ws.send(JSON.stringify({ type: 'set_active_ratings', ratings: getActiveRatings() }));
    }
  }

  function collectFilterState() {
    return {
      query: (document.getElementById('searchQuery') || {}).value || '',
      exclude: (document.getElementById('searchExclude') || {}).value || '',
      ratings: getActiveRatings(),
    };
  }

  function serverSearchText(message, key) {
    const hasDirect = message && Object.prototype.hasOwnProperty.call(message, key);
    const direct = hasDirect
      ? String(message[key] || '')
      : '';
    if (hasDirect) return direct;
    const preferences = message && message.filter_preferences;
    if (preferences && Object.prototype.hasOwnProperty.call(preferences, key)) {
      return String(preferences[key] || '');
    }
    return direct;
  }

  function serverSearchTexts(message) {
    return {
      query: serverSearchText(message, 'query'),
      exclude: serverSearchText(message, 'exclude'),
    };
  }

  function saveFilterState(extra = {}) {
    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const state = {
      type: 'save_search_filter_state',
      ...collectFilterState(),
      ...extra,
    };
    // Hold each field authoritative until the backend echoes it (see pendingEcho).
    pendingEcho = { query: String(state.query || ''), exclude: String(state.exclude || '') };
    ws.send(JSON.stringify(state));
  }

  function jsString(value) {
    return JSON.stringify(String(value || ''))
      .replace(/&/g, '\\u0026')
      .replace(/</g, '\\u003c')
      .replace(/>/g, '\\u003e')
      .replace(/"/g, '&quot;');
  }

  function closeParquetMenu() {
    const menu = moduleBody.querySelector('.search-parquet-menu');
    if (menu) menu.classList.remove('open');
  }

  function toggleParquetMenu(event) {
    if (event && typeof event.stopPropagation === 'function') event.stopPropagation();
    const menu = moduleBody.querySelector('.search-parquet-menu');
    if (menu) menu.classList.toggle('open');
  }

  function openParquetUpload(action) {
    const mode = action === 'merge' ? 'merge' : 'load';
    closeParquetMenu();
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.parquet';
    input.style.display = 'none';
    input.addEventListener('change', () => {
      const file = input.files && input.files[0];
      input.remove();
      if (file) uploadParquetFile(file, mode);
    }, {once: true});
    document.body.appendChild(input);
    input.click();
  }

  async function uploadParquetFile(file, mode) {
    const params = new URLSearchParams({
      action: mode === 'merge' ? 'merge' : 'load',
      filename: file.name || 'uploaded.parquet',
    });
    // Lock now; the successful path stays locked until the server broadcasts
    // search_state (onSearchState releases). Only failures unlock here.
    lockTagSurface();
    try {
      const response = await fetch(`/api/search/parquet/upload?${params}`, {
        method: 'POST',
        headers: {'Content-Type': 'application/octet-stream'},
        body: file,
      });
      if (!response.ok) {
        let message = 'Parquet upload failed';
        try {
          const data = await response.json();
          if (data && data.error) message = data.error;
        } catch (error) {
          // Keep the generic message when the server did not return JSON.
        }
        console.error(message);
        // 예전엔 콘솔에만 남아 사용자는 실패를 몰랐다.
        showToast(`불러오기 실패: ${message}`, 'error');
        unlockTagSurface();
        return;
      }
      try {
        const data = await response.json();
        const verb = mode === 'merge' ? '합쳤습니다' : '불러왔습니다';
        showToast(`${file.name} ${verb} (${Number(data.rows || 0).toLocaleString('en-US')}행 → 풀 ${Number(data.total || 0).toLocaleString('en-US')}행)`, 'success');
      } catch (error) {
        // 성공 본문을 못 읽어도 풀은 이미 바뀌었다 - 조용히 넘어간다.
      }
    } catch (error) {
      console.error('Parquet upload failed', error);
      showToast('불러오기 실패: 서버에 닿지 못했습니다', 'error');
      unlockTagSurface();
    }
  }

  function selectParquetMode(mode) {
    parquetPickMode = mode === 'merge' ? 'merge' : 'load';
    closeParquetMenu();
    const section = moduleBody.querySelector('.search-parquet-section');
    if (section) section.dataset.parquetMode = parquetPickMode;
    const hint = moduleBody.querySelector('.search-parquet-mode-label');
    if (hint) {
      hint.textContent = parquetPickMode === 'merge'
        ? '합칠 parquet을 아래에서 선택하세요'
        : '불러올 parquet을 아래에서 선택하세요';
    }
    const header = moduleBody.querySelector('.mod-section-label.mod-collapsible');
    const list = moduleBody.querySelector('.search-parquet-list');
    if (header) header.classList.add('open');
    if (list) list.classList.remove('collapsed');
  }

  function runParquetAction(action, extra = {}) {
    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    closeParquetMenu();
    lockTagSurface();
    ws.send(JSON.stringify({type: 'search_parquet_action', action, ...extra}));
    return true;
  }

  // ---- '이 결과 저장' 양식 --------------------------------------------------------
  // 저장 대상 = 지금 조건에 맞는 행 전체(등급·Tag Filter 반영, Random 이 뽑아 쓴 행 포함).
  // 파일에는 만든 조건(명함)이 함께 새겨진다 - 목록 카드가 그걸 읽는다.
  function saveFormNote() {
    const origin = recipeSummary(lastProvenance);
    return `지금 풀: ${origin || '조건 기록 없음'}\n+ 현재 등급·Tag Filter 조건이 그대로 기록됩니다.`;
  }

  function openSaveForm() {
    closeParquetMenu();
    const form = moduleBody.querySelector('.search-save-form');
    if (!form) return;
    form.hidden = false;
    const note = form.querySelector('.ssf-note');
    if (note) note.textContent = saveFormNote();
    const input = form.querySelector('input');
    if (input) { input.value = ''; input.focus(); }
  }

  function closeSaveForm() {
    const form = moduleBody.querySelector('.search-save-form');
    if (form) form.hidden = true;
  }

  function submitSaveForm() {
    const input = moduleBody.querySelector('.search-save-form input');
    const filename = (input && input.value || '').trim();
    if (runParquetAction('export_results', filename ? { filename } : {})) {
      closeSaveForm();
      showLibrary();   // 방금 저장한 카드가 보이게
    }
  }

  function toggleRating(rating) {
    ratingState[rating] = !ratingState[rating];
    syncRatingButtons();
    // Instant local feedback from the cached per-rating counts — no wait for the
    // backend round-trip.
    const localCount = computeLocalFilteredCount();
    if (localCount !== null) updateSearchCount(localCount);
    // Debounce the authoritative push so a burst of toggles sends a single
    // set_active_ratings; the search_state reply reconciles the count.
    if (ratingSendTimer) clearTimeout(ratingSendTimer);
    ratingSendTimer = setTimeout(() => {
      ratingSendTimer = null;
      sendActiveRatings();
    }, 160);
    const quickFilter = getQuickFilter();
    if (quickFilter) {
      quickFilter.savePreferences();
      // 등급 토글 시 Tag Filter 팝업의 "N matched" 라벨도 즉시 재계산(캐시된 등급별 카운트 합).
      if (quickFilter.refreshCount) quickFilter.refreshCount();
    }
  }

  function onFilterReset(message) {
    const quickFilter = getQuickFilter();
    const serverPreferences = message.filter_preferences;
    if (serverPreferences) {
      setRatingsFromList(serverPreferences.ratings);
      if (quickFilter) {
        quickFilter.applyPreferences(serverPreferences, {
          send: false,
          updateCount: false,
          persistLocal: true,
        });
      } else {
        syncRatingButtons();
      }
    } else {
      setRatingsFromList(['g', 's', 'q']);
      syncRatingButtons();
      if (quickFilter) quickFilter.reset({ persist: false });
    }
    if (message.rating_counts) cachedRatingCounts = message.rating_counts;
    if (message.count != null) updateSearchCount(message.count);
  }

  function onRatingUpdate(message) {
    if (message.rating_counts) cachedRatingCounts = message.rating_counts;
    const quickFilter = getQuickFilter();
    updateSearchCount(message.count || 0);
    if (message.active_ratings) {
      setRatingsFromList(message.active_ratings);
      syncRatingButtons();
    }
    if (quickFilter) quickFilter.updateHighlight();
  }

  function syncRatingButtons() {
    document.querySelectorAll('.rating-btn').forEach(button => {
      if (!button.dataset.r) return;
      button.classList.toggle('active', !!ratingState[button.dataset.r]);
    });
    const quickFilter = getQuickFilter();
    if (quickFilter) quickFilter.updateHighlight();
  }

  function onSearchState(message) {
    const quickFilter = getQuickFilter();
    const tagFilterRevision = Number(message.tag_filter_revision) || 0;
    if (tagFilterRevision > 0) {
      // Websocket broadcasts from concurrent tabs may complete out of order.
      // quickFilter also observes requester-only assigned/update messages, so
      // consult both guards before applying any part of an older search state.
      // stale/superseded 상태: 처리하지 않고 false 반환 → app.js 가 pool 잠금/게이트를
      // 조기 해제하지 않게 한다(newer 작업이 아직 진행 중; Codex NEW 선재 결함).
      if (tagFilterRevision < latestTagFilterRevision) return false;
      if (quickFilter?.noteAuthoritativeRevision
          && !quickFilter.noteAuthoritativeRevision(tagFilterRevision)) return false;
      latestTagFilterRevision = tagFilterRevision;
    }
    if (message.rating_counts) cachedRatingCounts = message.rating_counts;
    updateSearchCount(message.count || 0);
    // 라이브 green [검색] 이 방금 완료됐는지(잠금 해제 오버레이 판정용) + startup autoApply 로
    // 재적용됐는지 캡처. 검색은 워커 스레드로 돌아(비블로킹) 그동안 rating/tag_filter broadcast
    // 등 다른 search_state 가 끼어들 수 있으므로(Codex A3), 백엔드가 실제 green 검색 완료에만
    // 다는 `search_completed` 마커가 있을 때만 완료로 취급한다 — 끼어든 broadcast 는 무시.
    const wasSearching = searchingActive;
    const isSearchDone = !!message.search_completed;
    let autoApplied = false;
    if (isSearchDone) searchingActive = false;
    if (message.active_ratings) {
      setRatingsFromList(message.active_ratings);
    }
    setSearchRatingsFromMap(message.ratings);
    // A backend-authoritative tag assignment/clear was broadcast to every tab.
    // Treat it as the completed restore so passive receivers do not launch a
    // duplicate Search→Assign cycle from the same persisted chips.
    if (message.tag_filter_settled) initialFilterRestoreDone = true;
    if (quickFilter && quickFilter.setPresets) quickFilter.setPresets(message.filter_presets || []);
    const serverPreferences = message.filter_preferences;
    if (serverPreferences && quickFilter) {
      // 시작 후 첫 search_state 에서 영속된 Tag Filter 칩이 있으면 자동 Search→Assign 1회.
      // (그 이후 search_state 는 기존대로 {send:false} — 카운트 갱신마다 재검색/재할당 방지)
      // ⚠️ '칩 존재' 기준(과거엔 tag_filter_active 도 요구): Parquet 로드가 필터를 비활성으로
      // 영속(tag_filter_active=false)해도 칩은 draft 로 남으므로, 재시작 시 그 칩이 재적용되지
      // 않고 'N matched' 가 비어버리던 문제(사용자 리포트). 칩이 있으면 사용자가 원하는 필터로 보고
      // startup 1회 재적용 → active=true 로 재영속(assign→save). 시작 경로 한정(initialFilterRestoreDone
      // 가드)이라 green search/일반 search_state 에는 영향 없음.
      const hasActiveTags = ((serverPreferences.tag_filter || []).length)
        || ((serverPreferences.tag_filter_exclude || []).length);
      // 데이터셋이 아직 로드되기 전(랜덤 warmup 레이스)이면 자동 적용을 '소비'하지 않는다. 빈
      // 스냅샷에 필터를 걸면 0매칭 → 빈 필터가 할당돼 풀이 비고(Random "no matching rows"), 매치
      // 카운트 라벨도 비어버린다(사용자 리포트: 4,810 매칭인데 라벨 공백). 데이터가 실제로 로드된
      // 첫 search_state 에서만 1회 자동 Search→Assign 하여 라벨이 실데이터 기준으로 채워지고 풀이
      // 비지 않게 한다.
      // 준비 신호는 '스냅샷에 데이터가 있는가'다 — 태그필터는 스냅샷(search_results_snapshot)을
      // 대상으로 매칭하므로. total_count(=라이브 풀 잔량)는 직전 빈 할당으로 0이 돼도 스냅샷엔
      // 데이터가 남아 있을 수 있어, 스냅샷 기반 rating_counts 합을 우선 신호로 쓴다(Codex High#1).
      const ratingTotal = message.rating_counts
        ? Object.values(message.rating_counts).reduce((a, b) => a + (Number(b) || 0), 0) : 0;
      const dataReady = ratingTotal > 0 || (Number(message.total_count) || 0) > 0;
      const autoApply = !initialFilterRestoreDone && !!hasActiveTags && dataReady;
      if (autoApply) initialFilterRestoreDone = true;
      autoApplied = autoApply;
      quickFilter.applyPreferences(serverPreferences, {
        send: autoApply,
        updateCount: false,
        persistLocal: true,
      });
    } else if (serverPreferences) {
      setRatingsFromList(serverPreferences.ratings);
      syncRatingButtons();
    } else {
      syncRatingButtons();
    }
    // Passive tabs receive the authoritative search_state rather than the
    // requester's tag_filter_assigned event. Rehydrate the filter-specific
    // per-rating counts after the chips/active flag above have reconciled so
    // every tab retains the same "N assigned" label.
    if (
      message.tag_filter_settled
      && serverPreferences?.tag_filter_active
      && message.tag_filter_rating_counts
      && quickFilter?.onUpdate
    ) {
      quickFilter.onUpdate({rating_counts: message.tag_filter_rating_counts});
    }
    // Parquet load/merge swapped the working pool → the backend deactivated the
    // filter and kept the chips as a draft, leaving the Tag Filter's 'N matched'
    // stale (old pool). Auto re-apply the draft to the NEW pool so the filter
    // follows the dataset and every count recomputes (user-chosen sync). Guarded
    // to parquet-swap states only (assign/rating search_states carry no
    // loaded/merged, so this never loops).
    if ((message.loaded || message.merged) && quickFilter && quickFilter.onPoolSwap) {
      quickFilter.onPoolSwap();
    } else if (
      wasSearching
      && isSearchDone
      && !autoApplied
      && !message.tag_filter_settled
      && quickFilter && quickFilter.onSearchReleased
    ) {
      // 실제 green [검색] 완료(search_completed 마커)가 활성 태그필터를 백엔드에서 해제(칩=draft)
      // → 자동 재적용 대신 '해제됨' 오버레이(블러 + [재적용]/[초기화])로 사용자 선택을 받는다.
      // 끼어든 rating/tag_filter broadcast 는 마커가 없어 여기서 걸러진다(A3 false-positive 방지).
      quickFilter.onSearchReleased();
    }
    if (searchVisible()) renderSearch(message);
    // 방금 끝난 검색이 기록 맨 위에 올라갔다 - 기록 창이 열려 있으면 다시 받는다.
    if (isSearchDone && historyOpen) requestHistory();
    // app.js 는 이 반환값이 true 일 때만 pool 잠금/Random 게이트를 해제한다. pool 잠금 해제는
    // 실제 pool 작업 완료일 때만이어야 한다: green 검색 진행 중(wasSearching)이면 그 검색의
    // 완료 마커(search_completed=isSearchDone)에만 해제하고, 끼어든 authoritative state
    // (rating/tag_filter broadcast 등, 마커 없음)로는 조기 해제하지 않는다(Codex §3-1).
    // 검색 진행 중이 아니면(parquet load/merge·restore·rating 완료 등) 정상 해제.
    return isSearchDone || !wasSearching;
  }

  function onSearchProgress(message) {
    if (searchVisible()) {
      const progress = moduleBody.querySelector('.search-progress');
      if (progress) progress.textContent = `Searching... ${message.completed}/${message.total}`;
    }
  }

  // ── Render-once: build the DOM once, then patch it in place ──────────────────

  function renderSearch(message) {
    if (moduleBody.querySelector('#searchQuery')) {
      updateSearchPanel(message);
    } else {
      buildSearchPanel(message);
    }
  }

  function ratingCheckboxesHtml() {
    return [
      ['e', 'Explicit'], ['q', 'NSFW'], ['s', 'Sensitive'], ['g', 'General']
    ].map(([key, label]) =>
      `<label class="mod-checkbox-item">
      <input type="checkbox" id="sr_${key}" ${searchRatingState[key] ? 'checked' : ''}>
      <span class="mod-checkbox-label">${label}</span>
    </label>`
    ).join('');
  }

  function libraryFromMessage(message) {
    if (Array.isArray(message.parquet_library)) return message.parquet_library;
    // 옛 백엔드(카드 없음) - 이름만으로라도 그린다.
    return (message.parquets || []).map(name => ({ name, rows: null, recipe: null, has_meta: false }));
  }

  function parquetSignature(message) {
    return librarySignature(libraryFromMessage(message));
  }

  // 예전엔 파일이 없으면 칸 자체가 없고, 있어도 접혀 있어 저장한 파일이 어디 있는지 몰랐다 -
  // 항상 보이고 기본으로 펼친다. 카드 = 이름 · 행 수 · 만든 조건 요약(눌러서 펼침).
  function parquetSectionHtml(message) {
    lastLibrary = libraryFromMessage(message);
    return `<div class="pql-wrap">${libraryHtml(lastLibrary, {
      escHtml, openNames: pqlOpen, moreName: pqlMore, renaming: pqlRenaming, confirmTrash: pqlConfirmTrash,
    })}</div>`;
  }

  function rerenderLibrary() {
    const host = libHost;
    host.innerHTML = parquetSectionHtml({ parquet_library: lastLibrary });
    updateLibraryCount();
    if (pqlRenaming) {
      const input = host.querySelector('.pql-rename');
      if (input) { input.focus(); input.select(); }
    }
  }

  function updateLibraryCount() {
    const count = moduleBody.querySelector('.sp-pq-count');
    if (count) count.textContent = String(lastLibrary.length);
  }

  // 동반 창이 열리고 닫힐 때 창 쪽에서 부른다 - [Custom Parquets] 단추가 상태를 비춘다.
  function syncLibraryButton(open) {
    const button = moduleBody.querySelector('[data-sp="parquets"]');
    if (!button) return;
    button.classList.toggle('is-on', !!open);
    button.setAttribute('aria-pressed', open ? 'true' : 'false');
  }

  // ---- [검색 기록] ---------------------------------------------------------------
  function requestHistory() {
    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ type: 'get_search_history' }));
  }

  function setHistoryOpen(open) {
    historyOpen = !!open;
    const box = moduleBody.querySelector('.sp-history');
    if (box) box.hidden = !historyOpen;
    const button = moduleBody.querySelector('[data-sp="history"]');
    if (button) {
      button.classList.toggle('is-on', historyOpen);
      button.setAttribute('aria-pressed', historyOpen ? 'true' : 'false');
    }
    if (historyOpen) {
      renderHistory();
      requestHistory();
      moduleBody.querySelector('.sp-hist-filter')?.focus();
    }
  }

  function historyWhen(at) {
    // 2026-09-21T19:31:20 -> 09-21 19:31
    const m = /^\d{4}-(\d{2}-\d{2})T(\d{2}:\d{2})/.exec(String(at || ''));
    return m ? `${m[1]} ${m[2]}` : '';
  }

  // 찾기 = 검색어·제외어에 들어 있는가(대소문자 무시) - 사용자 지정: 복잡하게 만들지 말 것.
  function historyMatches(item, needle) {
    if (!needle) return true;
    return `${item.query || ''}\n${item.exclude || ''}`.toLowerCase().includes(needle);
  }

  function renderHistory() {
    const list = moduleBody.querySelector('.sp-hist-list');
    if (!list) return;
    const needle = (moduleBody.querySelector('.sp-hist-filter')?.value || '').trim().toLowerCase();
    const shown = [];
    historyItems.forEach((item, index) => { if (historyMatches(item, needle)) shown.push([item, index]); });
    if (!shown.length) {
      list.innerHTML = `<div class="sp-hist-empty">${historyItems.length ? '맞는 기록이 없습니다' : '아직 검색 기록이 없습니다'}</div>`;
      return;
    }
    list.innerHTML = shown.map(([item, index]) => {
      const ratings = Array.isArray(item.ratings) && item.ratings.length && item.ratings.length < 4 ? item.ratings.join('/') : '';
      const meta = [
        typeof item.rows === 'number' ? `${item.rows.toLocaleString('en-US')}행` : '',
        ratings, item.period || '', historyWhen(item.at),
      ].filter(Boolean).join(' · ');
      return `<div class="sp-hist-item" data-sp-hist="${index}" title="눌러서 검색 칸에 채우기">
        <div class="sp-hist-text">
          <div class="sp-hist-q">${escHtml(item.query || '(전체)')}</div>
          ${item.exclude ? `<div class="sp-hist-x">− ${escHtml(item.exclude)}</div>` : ''}
          <div class="sp-hist-meta">${escHtml(meta)}</div>
        </div>
        <button type="button" class="sp-hist-del" data-sp-hist-del="${index}" title="기록에서 지우기">×</button>
      </div>`;
    }).join('');
  }

  function onSearchHistory(message) {
    historyItems = Array.isArray(message.items) ? message.items : [];
    if (historyOpen) renderHistory();
  }

  function useHistoryItem(item) {
    const query = moduleBody.querySelector('#searchQuery');
    const exclude = moduleBody.querySelector('#searchExclude');
    if (query) query.value = item.query || '';
    if (exclude) exclude.value = item.exclude || '';
    saveFilterState();
    setHistoryOpen(false);
    moduleBody.querySelector('.mod-start')?.focus();
  }

  function bindParquetLibrary() {
    // 검색 층과 동반 창(카드 그리드) 두 곳에 같은 위임 처리기를 건다.
    for (const root of [moduleBody, libHost]) bindLibraryRoot(root);
  }

  function bindLibraryRoot(root) {
    // 카드는 다시 그릴 때마다 새 요소라 위임으로 받는다(인라인 onclick·전역 함수 없음).
    if (root._pqlBound) return;
    root._pqlBound = true;
    root.addEventListener('click', event => {
      if (event.target.closest('[data-sp="parquets"]')) { toggleLibrary(); return; }
      if (event.target.closest('[data-sp="history"]')) { setHistoryOpen(!historyOpen); return; }
      const del = event.target.closest('[data-sp-hist-del]');
      if (del) {
        const item = historyItems[Number(del.dataset.spHistDel)];
        const ws = getWs();
        if (item && ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'delete_search_history', query: item.query || '', exclude: item.exclude || '' }));
        }
        return;
      }
      const hist = event.target.closest('[data-sp-hist]');
      if (hist) {
        const item = historyItems[Number(hist.dataset.spHist)];
        if (item) useHistoryItem(item);
        return;
      }
      if (event.target.closest('[data-ssf="save"]')) { submitSaveForm(); return; }
      if (event.target.closest('[data-ssf="cancel"]')) { closeSaveForm(); return; }
      if (event.target.closest('[data-ssf="open"]')) { openSaveForm(); return; }
      const button = event.target.closest('[data-pql]');
      const card = event.target.closest('.pql-tile');
      if (!button || !card) return;
      const name = card.dataset.pqlName;
      const action = button.dataset.pql;
      if (action === 'load' || action === 'merge') {
        loadParquet(name, action);
      } else if (action === 'expand') {
        if (pqlOpen.has(name)) pqlOpen.delete(name); else pqlOpen.add(name);
        rerenderLibrary();
      } else if (action === 'more') {
        pqlMore = pqlMore === name ? null : name;
        pqlConfirmTrash = null;
        rerenderLibrary();
      } else if (action === 'rename') {
        pqlRenaming = name;
        pqlMore = null;
        rerenderLibrary();
      } else if (action === 'trash') {
        // 두 번 눌러야 옮긴다(휴지통이라 되살릴 수 있지만, 한 번 실수로 목록에서 사라지면 놀란다).
        if (pqlConfirmTrash === name) {
          pqlConfirmTrash = null;
          pqlMore = null;
          runParquetAction('trash', { filename: name });
        } else {
          pqlConfirmTrash = name;
          clearTimeout(pqlConfirmTimer);
          pqlConfirmTimer = setTimeout(() => { pqlConfirmTrash = null; rerenderLibrary(); }, 3000);
          rerenderLibrary();
        }
      }
    });
    root.addEventListener('keydown', event => {
      const rename = event.target.closest && event.target.closest('.pql-rename');
      if (rename) {
        if (event.key === 'Enter') {
          event.preventDefault();
          const from = rename.dataset.pqlRename;
          const to = rename.value.trim();
          pqlRenaming = null;
          if (to && to !== from.replace(/\.parquet$/i, '')) runParquetAction('rename', { filename: from, new_name: to });
          else rerenderLibrary();
        } else if (event.key === 'Escape') {
          pqlRenaming = null;
          rerenderLibrary();
        }
        return;
      }
      const histFilter = event.target.closest && event.target.closest('.sp-hist-filter');
      if (histFilter) {
        if (event.key === 'Escape') setHistoryOpen(false);
        return;
      }
      const save = event.target.closest && event.target.closest('.search-save-form input');
      if (save) {
        if (event.key === 'Enter') { event.preventDefault(); submitSaveForm(); }
        else if (event.key === 'Escape') closeSaveForm();
      }
    });
    root.addEventListener('input', event => {
      if (event.target.classList && event.target.classList.contains('sp-hist-filter')) renderHistory();
    });
    root.addEventListener('focusout', event => {
      if (event.target.classList && event.target.classList.contains('pql-rename') && pqlRenaming) {
        pqlRenaming = null;
        setTimeout(rerenderLibrary, 0);
      }
    });
  }

  function ensureParquetLibraryStyle() {
    if (document.getElementById('pql-style')) return;
    const style = document.createElement('style');
    style.id = 'pql-style';
    style.textContent = PQL_CSS + SEARCH_COMPACT_CSS;
    document.head.appendChild(style);
  }

  function bindSearchInputs() {
    const fieldByInputId = { searchQuery: 'query', searchExclude: 'exclude' };
    ['searchQuery', 'searchExclude'].forEach(id => {
      const element = moduleBody.querySelector(`#${id}`);
      if (!element) return;
      bindTagAssist(element, { excludeE621: true });
      // Re-focusing a field means the user is editing it again — drop its pending
      // echo guard so server values can flow back once they move on (and a fresh
      // guard is set on the next blur/change via saveFilterState).
      element.addEventListener('focus', () => { pendingEcho[fieldByInputId[id]] = null; });
      element.addEventListener('change', () => saveFilterState());
      element.addEventListener('blur', () => saveFilterState());
    });
    for (const key of ['e', 'q', 's', 'g']) {
      const checkbox = moduleBody.querySelector(`#sr_${key}`);
      if (!checkbox) continue;
      checkbox.addEventListener('change', () => {
        searchRatingState[key] = checkbox.checked;
      });
    }
  }

  function buildSearchPanel(message) {
    const searchText = serverSearchTexts(message);
    pendingEcho = { query: null, exclude: null };
    lastParquetSig = parquetSignature(message);
    if ('pool_provenance' in message) lastProvenance = message.pool_provenance;
    moduleBody.innerHTML = `
    <div class="sp-toolbar">
      <button type="button" class="sp-tbtn" data-sp="parquets" aria-pressed="false"
        data-naia-guide="저장해 둔 parquet 목록 - 파일마다 행 수와 만든 조건이 보입니다. 불러오기·합치기·이름 바꾸기·휴지통.">Custom Parquets (<span class="sp-pq-count">0</span>)</button>
      <div class="search-parquet-control">
        <button type="button" class="sp-tbtn" onclick="toggleSearchParquetMenu(event)"
          data-naia-guide="지금 결과를 parquet 으로 저장하거나, PC 의 parquet 을 불러오거나 합칩니다.">Load / Save Parquets</button>
        <div class="search-parquet-menu">
          <button type="button" data-ssf="open" data-naia-guide="이 결과 저장 — 지금 조건에 맞는 행 전체(등급·Tag Filter 반영)를 parquet 으로 저장합니다. 만든 조건이 파일에 함께 기록되어 목록에서 무엇이 들었는지 보입니다.">이 결과 저장…</button>
          <button type="button" onclick="openSearchParquetUpload('load')" data-naia-guide="PC에서 불러오기 — 내 컴퓨터의 parquet 파일로 지금 풀을 바꿉니다. (저장해 둔 파일은 Custom Parquets 목록에서 바로 불러오세요.)">PC에서 불러오기</button>
          <button type="button" onclick="openSearchParquetUpload('merge')" data-naia-guide="PC에서 합치기 — 내 컴퓨터의 parquet 파일을 지금 풀에 더합니다(중복 id 는 한 번만).">PC에서 합치기</button>
          <button type="button" onclick="searchParquetAction('save_runner')" data-naia-guide="실행파일 저장 — 현재 결과를 실행용 parquet(naia_temp_rows)로 저장합니다. 재시작·복구 시 이 풀에서 랜덤 프롬프트가 생성됩니다.">실행파일 저장</button>
        </div>
      </div>
      <button type="button" class="sp-tbtn" onclick="restoreSnapshot()"
        data-naia-guide="Restore — 태그 필터와 범위 좁히기를 모두 해제하고, 마지막 검색 결과셋 전체로 되돌립니다.">Restore</button>
    </div>
    <div class="search-save-form" hidden>
      <div class="ssf-row">
        <input type="text" placeholder="파일 이름 (비우면 날짜로)" spellcheck="false">
        <button type="button" class="pql-btn" data-ssf="save">저장</button>
        <button type="button" class="pql-btn" data-ssf="cancel">취소</button>
      </div>
      <div class="ssf-note" style="white-space:pre-line"></div>
    </div>
    <div class="sp-counts">
      <span class="sp-count-cell" title="지금 데이터셋(검색 결과) 전체 행 수">
        <span class="sp-count-label">검색된 행</span><b class="sp-snap-count">${Number(message.snapshot_count || 0).toLocaleString('en-US')}</b><span class="sp-unit">개</span>
      </span>
      <span class="sp-count-sep"></span>
      <span class="sp-count-cell" title="등급·Tag Filter 를 적용하고 Random 이 아직 쓰지 않은 행 수">
        <span class="sp-count-label">남은 행</span><b class="search-count-display">${Number(message.count || 0).toLocaleString('en-US')}</b><span class="sp-unit">개</span>
      </span>
    </div>
    <div>
      <div class="dr-label-row">
        <span class="mod-section-label">Search Keyword</span>
        <button type="button" class="header-guide-btn" data-naia-guide="Search Keyword — 포함 검색(AND). 쉼표로 구분한 태그를 모두 포함하는 결과만 남깁니다.\\n\\n부분일치 — 기본은 부분 문자열 매칭입니다. 예: girl → 1girl·cowgirl 도 매칭, hair → long hair 도 매칭. (_ 는 공백으로 처리)\\n\\n{a|b|c} — OR 그룹. 중괄호 안 태그 중 하나라도 포함하면 매칭. 그룹끼리는 AND로 결합됩니다. 그룹 안에서도 *를 쓸 수 있습니다 — 예: {*dog|*cat} 은 태그가 정확히 dog 또는 cat 인 행만 남깁니다.\\n\\n*tag — 태그 전체 일치. 태그가 정확히 그것인 행만 매칭합니다. 예: *girl 은 girl 만 — 1girl·cowgirl 은 물론 girl (character) 처럼 뒤에 말이 더 붙은 태그도 제외됩니다. *dog 은 dog ears·hot dog 을 끌어오지 않습니다.\\n\\n~tag — 포함 칸에 써도 됩니다. 그 태그를 정확히 가진 행을 뺍니다(제외 칸의 ~tag 와 같음).">ⓘ 가이드</button>
      </div>
      <input class="mod-input" id="searchQuery" type="text" value="${escHtml(searchText.query)}" placeholder="tags, keywords...">
    </div>
    <div>
      <div class="dr-label-row">
        <span class="mod-section-label">Exclude Keyword</span>
        <button type="button" class="header-guide-btn" data-naia-guide="Exclude Keyword — 제외 검색. 입력한 태그가 든 결과를 빼냅니다. 포함 검색과 문법이 다릅니다.\\n\\ntag — 부분일치 제외. 해당 문자열이 든 행을 모두 제외합니다. 예: abs 는 absurdres 까지 함께 제외될 수 있습니다.\\n\\n~tag — 정확 태그 제외. 정확한 토큰만 제외합니다(부분일치 아님). 예: ~abs 는 abs 토큰만 제외하고 absurdres 는 유지.\\n\\n*tag — 정확 태그 제외. ~tag 와 같습니다(둘 다 받습니다).\\n\\n{a|b} — OR 그룹 제외. 그 중 하나라도 든 행을 뺍니다.">ⓘ 가이드</button>
      </div>
      <input class="mod-input" id="searchExclude" type="text" value="${escHtml(searchText.exclude)}" placeholder="exclude tags...">
    </div>
    <div class="sp-ratings">
      <span class="mod-section-label">Ratings</span>
      <button type="button" class="header-guide-btn" data-naia-guide="Ratings — 포함할 콘텐츠 등급. 켜진 등급의 결과만 검색합니다.\\n\\nExplicit — 명확한 성적인 행위가 있는 구도.\\n\\nNSFW — 확실한 노출이 있고 일부 성기 노출이 포함될 수 있는 구도, 또는 성적인 행위를 암시하는 구도.\\n\\nSensitive — 수영복이나 속옷 같은 일반적인 노출이 있는 구도.\\n\\nGeneral — 그 외의 일반적인 Safe 구도.">ⓘ</button>
      ${ratingCheckboxesHtml()}
    </div>
    ${dateRangeSliderHtml()}
    <div class="sp-search-row">
      <button type="button" class="sp-hist-btn" data-sp="history" aria-pressed="false"
        data-naia-guide="검색 기록 — 실행했던 검색(검색어·제외어)을 최근 순으로 최대 500개 기억합니다. 눌러서 칸에 채운 뒤 [검색] 하세요.">검색 기록</button>
      <button class="mod-action-btn mod-start" onclick="doSearch()" ${searchingActive ? 'disabled' : ''}>검색</button>
    </div>
    <div class="sp-history" hidden>
      <input type="text" class="sp-hist-filter" placeholder="검색어·제외어에서 찾기" spellcheck="false">
      <div class="sp-hist-list"></div>
    </div>
    <span class="search-progress"></span>
  `;
    bindSearchInputs();
    ensureDateRangeStyle();
    ensureParquetLibraryStyle();
    libHost.innerHTML = parquetSectionHtml(message);
    bindParquetLibrary();
    updateLibraryCount();
    syncLibraryButton(isLibraryOpen());
    historyOpen = false;
    bindDateRangeDrag();
    bindTagIncrementButton();
    renderDateRange();
    requestBucketDates();
    // 검색 화면을 열 때마다 확인한다 - 설치 관리자는 이 창 밖(Setup)에서도 받을 수
    // 있어서, 여기 상태를 한 번 잡아두고 마는 건 어긋난다.
    refreshIncrementState();
  }

  function bindTagIncrementButton() {
    // 버튼은 다시 그릴 때마다 새 요소라 위임으로 받는다.
    if (moduleBody._tagIncrementBound) return;
    moduleBody._tagIncrementBound = true;
    moduleBody.addEventListener('click', event => {
      if (event.target.closest('#searchTagUpdateBtn')) startIncrementDownload();
    });
  }

  function applyInputValue(element, serverVal, guard, focusedEl) {
    if (!element || element === focusedEl) return; // never clobber the field being edited
    if (guard) return;                              // awaiting echo of a local commit
    if (element.value !== serverVal) element.value = serverVal;
  }

  function syncParquetSection(message) {
    const sig = parquetSignature(message);
    if (sig === lastParquetSig) return;
    lastParquetSig = sig;
    lastLibrary = libraryFromMessage(message);
    // 사라진 파일의 펼침·메뉴 상태는 버린다(이름 바꾸기·휴지통 뒤).
    const names = new Set(lastLibrary.map(card => card.name));
    for (const name of [...pqlOpen]) if (!names.has(name)) pqlOpen.delete(name);
    if (pqlMore && !names.has(pqlMore)) pqlMore = null;
    if (pqlRenaming && !names.has(pqlRenaming)) pqlRenaming = null;
    rerenderLibrary();
  }

  function updateSearchPanel(message) {
    if ('pool_provenance' in message) lastProvenance = message.pool_provenance;
    const saveNote = moduleBody.querySelector('.search-save-form:not([hidden]) .ssf-note');
    if (saveNote) saveNote.textContent = saveFormNote();
    const countEl = moduleBody.querySelector('.search-count-display');
    if (countEl) countEl.textContent = Number(message.count || 0).toLocaleString('en-US');
    const snapEl = moduleBody.querySelector('.sp-snap-count');
    if (snapEl && 'snapshot_count' in message) snapEl.textContent = Number(message.snapshot_count || 0).toLocaleString('en-US');

    const server = serverSearchTexts(message);
    // Per-field: clear a field's guard once the server echoes that field's value,
    // so a sibling field that diverges (or never echoes exactly) can't keep it stuck.
    if (pendingEcho.query !== null && server.query === pendingEcho.query) pendingEcho.query = null;
    if (pendingEcho.exclude !== null && server.exclude === pendingEcho.exclude) pendingEcho.exclude = null;
    const focusedEl = document.activeElement;
    applyInputValue(moduleBody.querySelector('#searchQuery'), server.query, pendingEcho.query !== null, focusedEl);
    applyInputValue(moduleBody.querySelector('#searchExclude'), server.exclude, pendingEcho.exclude !== null, focusedEl);

    for (const key of ['e', 'q', 's', 'g']) {
      const checkbox = moduleBody.querySelector(`#sr_${key}`);
      if (checkbox) checkbox.checked = !!searchRatingState[key];
    }

    const button = moduleBody.querySelector('.mod-start');
    if (button) button.disabled = searchingActive;
    if (!searchingActive) {
      const progress = moduleBody.querySelector('.search-progress');
      if (progress) progress.textContent = '';
    }

    syncParquetSection(message);
  }

  function doSearch() {
    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const query = (document.getElementById('searchQuery') || {}).value || '';
    const exclude = (document.getElementById('searchExclude') || {}).value || '';
    for (const key of ['e','q','s','g']) {
      const element = document.getElementById('sr_' + key);
      if (element) searchRatingState[key] = element.checked;
    }
    const ratings = {};
    for (const key of ['e','q','s','g']) {
      ratings['rating_' + key] = searchRatingState[key];
    }
    searchingActive = true;
    lockTagSurface();   // heavy archive scan → released by onSearchState (search_progress keeps it alive)
    saveFilterState({query, exclude});
    const bucketRange = bucketState.loaded
      ? { bucket_start: bucketState.start, bucket_end: bucketState.end }
      : {};
    ws.send(JSON.stringify({ type: 'search', query, exclude, ...ratings, ...bucketRange }));
    const progress = moduleBody.querySelector('.search-progress');
    if (progress) progress.textContent = 'Starting...';
    const button = moduleBody.querySelector('.mod-start');
    if (button) button.disabled = true;
  }

  function loadParquet(filename, mode = parquetPickMode) {
    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    lockTagSurface();
    // 카드마다 [불러오기]·[합치기] 가 따로 있다 - 예전엔 합치기 모드로 바꾸는 호출자가 없어
    // 목록에서 합치기가 불가능했다.
    ws.send(JSON.stringify({
      type: mode === 'merge' ? 'merge_parquet' : 'load_parquet',
      filename,
    }));
  }

  function restoreSnapshot() {
    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    lockTagSurface();
    ws.send(JSON.stringify({ type: 'restore_snapshot' }));
  }

  // ── Date-cutoff range slider (perf: scan only buckets [start..end]) ──────────
  // bucketState mirrors the persisted [start,end] over the date-ordered tag files.
  let bucketState = { buckets: [], count: 0, start: 0, end: 0, loaded: false };
  let bucketRequested = false;

  function requestBucketDates() {
    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    bucketRequested = true;
    ws.send(JSON.stringify({ type: 'get_bucket_dates' }));
  }

  function onBucketDates(message) {
    const buckets = Array.isArray(message.buckets) ? message.buckets : [];
    bucketState.buckets = buckets;
    bucketState.count = buckets.length || (message.bucket_count || 0);
    const last = Math.max(0, bucketState.count - 1);
    const cs = Number.isInteger(message.current_start) ? message.current_start : 0;
    const ce = Number.isInteger(message.current_end) ? message.current_end : last;
    bucketState.start = Math.min(Math.max(cs, 0), last);
    bucketState.end = Math.min(Math.max(ce, 0), last);
    if (bucketState.start > bucketState.end) [bucketState.start, bucketState.end] = [bucketState.end, bucketState.start];
    bucketState.loaded = bucketState.count > 0;
    // 설치 직후 한 번: 끝을 마지막 버킷까지 민다(위 pushEndAfterBuckets 참조).
    if (pushEndAfterBuckets && bucketState.loaded) {
      pushEndAfterBuckets = false;
      const lastBucket = bucketState.count - 1;
      if (bucketState.end < lastBucket) {
        bucketState.end = lastBucket;
        if (bucketState.start > bucketState.end) bucketState.start = bucketState.end;
        persistBucketRange();
        showToast(`최신 태그 데이터 설치 완료 — 검색 기간을 ${ymEnd(lastBucket)} 까지 넓혔습니다.`, 'success');
      } else {
        showToast('최신 태그 데이터 설치 완료.', 'success');
      }
    }
    // ⚠️ 슬라이더만 다시 그리면 안 된다. 버킷 표는 **버튼을 그린 뒤에** 도착하는데,
    //    버튼 라벨의 기간이 그 표에서 나온다 - 슬라이더만 갱신하면 라벨이 폴백
    //    ("Download latest tag data")에 굳는다(실측).
    if (searchVisible()) renderDateRangeHost();
  }

  async function refreshIncrementState({ rerender = true } = {}) {
    try {
      const res = await fetch('/api/install-manager', { cache: 'no-store' });
      if (!res.ok) return;
      const data = await res.json();
      const next = data?.tag_archive_increment || null;
      const was = incrementState?.ready;
      incrementState = next;
      // 다운로더는 **단일 비행**이고 진행 상태가 하나뿐이다. 그 상태가 이 아카이브를
      // 가리킬 때만 "받는 중" 이다 - `phase` 에 스펙 키가 들어간다.
      const dl = next?.download || {};
      incrementBusy = Boolean(dl.active && dl.phase === 'tag_archive_increment');
      if (next?.ready && was === false) {
        // ⚠️ 받았다고 검색 범위가 저절로 늘지는 않는다. 기본 끝은 `DEFAULT_END_YM`
        //    기준이라(예: 버킷 135) **다운로드해도 2026 데이터가 안 잡힌다.**
        //    받은 이유가 그 데이터를 쓰려는 것이니 끝을 마지막 버킷까지 민다
        //    (사용자 지정). 시작점은 건드리지 않는다.
        //    버킷 수는 응답이 와야 아므로 표를 다시 받은 뒤에 민다.
        pushEndAfterBuckets = true;
        requestBucketDates();
      }
      if (rerender && searchVisible()) renderDateRangeHost();
    } catch (_) { /* 설치 관리자는 로컬 전용 - 원격에서는 조용히 없다 */ }
  }

  function renderDateRangeHost() {
    // 버튼은 슬라이더와 같은 부모에 산다. 슬라이더만 다시 그리면 버튼이 안 바뀐다.
    const host = moduleBody.querySelector('#drTrack')?.closest('.search-daterange')?.parentElement;
    const btn = moduleBody.querySelector('#searchTagUpdateBtn');
    const wanted = tagIncrementHtml();
    // ⚠️ 버튼이 사라지는 경우에도 **슬라이더는 반드시 다시 그린다.** 예전에는 여기서
    //    조기 반환했는데, 설치가 끝나는 순간이 바로 "버튼이 사라지는" 순간이라
    //    같이 넓힌 기간이 화면에 안 나타났다(토스트만 뜨고 막대는 그대로, 실측).
    if (!wanted) {
      btn?.remove();
    } else if (btn) {
      btn.outerHTML = wanted;
    } else if (host) {
      host.insertAdjacentHTML('afterbegin', wanted);
    }
    renderDateRange();
  }

  async function startIncrementDownload() {
    if (incrementBusy) return;
    incrementBusy = true;
    renderDateRangeHost();
    try {
      const res = await fetch('/api/install-manager/tag-archive-increment/download', { method: 'POST' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data?.ok === false) {
        incrementBusy = false;
        showToast(data?.error || '최신 태그 데이터 내려받기를 시작하지 못했습니다.', 'error');
        renderDateRangeHost();
        return;
      }
      // ⚠️ 다운로더는 단일 비행이다. 다른 아카이브를 받는 중이면 위 요청은 조용히
      //    기존 상태만 돌려준다 - 그걸 "시작됨" 으로 읽으면 안 된다.
      const dl = data?.tag_archive_increment?.download || {};
      if (dl.active && dl.phase !== 'tag_archive_increment') {
        incrementBusy = false;
        showToast('다른 데이터를 내려받는 중입니다. 끝난 뒤 다시 눌러 주세요.', 'warning');
        renderDateRangeHost();
        return;
      }
      showToast('최신 태그 데이터를 내려받는 중입니다 (275MB).', 'success');
      // 완료·실패는 스냅샷 폴링으로 확인한다. 다운로더가 이어받기·취소를 이미 한다.
      const poll = setInterval(async () => {
        await refreshIncrementState();
        if (!incrementBusy) clearInterval(poll);
      }, 1500);
    } catch (error) {
      incrementBusy = false;
      showToast('최신 태그 데이터 내려받기 실패.', 'error');
      renderDateRangeHost();
    }
  }

  function ymStart(i) { const b = bucketState.buckets[i]; return b ? (b.start_ym || '') : ''; }
  function ymEnd(i) { const b = bucketState.buckets[i]; return b ? (b.end_ym || '') : ''; }

  function renderDateRange() {
    const track = moduleBody.querySelector('#drTrack');
    if (!track || !bucketState.loaded) return;
    const last = Math.max(1, bucketState.count - 1);
    const sPct = (bucketState.start / last) * 100;
    const ePct = (bucketState.end / last) * 100;
    const hs = moduleBody.querySelector('#drHandleStart');
    const he = moduleBody.querySelector('#drHandleEnd');
    const fill = moduleBody.querySelector('#drFill');
    if (hs) hs.style.left = sPct + '%';
    if (he) he.style.left = ePct + '%';
    if (fill) { fill.style.left = sPct + '%'; fill.style.width = Math.max(0, ePct - sPct) + '%'; }
    const ts = moduleBody.querySelector('#drTipStart');
    const te = moduleBody.querySelector('#drTipEnd');
    if (ts) ts.textContent = ymStart(bucketState.start);
    if (te) te.textContent = ymEnd(bucketState.end);
    const rangeLabel = moduleBody.querySelector('#drRangeLabel');
    const countLabel = moduleBody.querySelector('#drCountLabel');
    if (rangeLabel) rangeLabel.textContent = `${ymStart(bucketState.start)} — ${ymEnd(bucketState.end)}`;
    if (countLabel) countLabel.textContent = `selected parquets: ${bucketState.end - bucketState.start + 1}`;
  }

  function persistBucketRange() {
    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ type: 'save_search_filter_state', bucket_start: bucketState.start, bucket_end: bucketState.end }));
  }

  function bindDateRangeDrag() {
    const track = moduleBody.querySelector('#drTrack');
    if (!track) return;
    const last = () => Math.max(1, bucketState.count - 1);
    const idxFromX = (clientX) => {
      const rect = track.getBoundingClientRect();
      let pct = rect.width ? (clientX - rect.left) / rect.width : 0;
      pct = Math.max(0, Math.min(1, pct));
      return Math.round(pct * last());
    };
    const hs = moduleBody.querySelector('#drHandleStart');
    const he = moduleBody.querySelector('#drHandleEnd');
    const setDragging = (h, on) => { if (h) h.classList.toggle('dragging', on); };
    const startDrag = (handle, edge) => (ev) => {
      if (!bucketState.loaded) return;
      ev.preventDefault();
      // 드래그 도중 잡은 쪽이 바뀔 수 있어(아래 교차 처리) let 으로 둔다.
      let curHandle = handle;
      let curEdge = edge;
      setDragging(curHandle, true);
      const move = (e) => {
        const cx = (e.touches ? e.touches[0].clientX : e.clientX);
        const idx = idxFromX(cx);
        // 상대 핸들을 지나치면 잡은 쪽을 넘긴다.
        // 이 교차 처리가 없으면 두 핸들이 같은 칸에 겹쳤을 때 DOM 뒤쪽인 end 만
        // 잡히는데, end 는 start 왼쪽으로 못 가므로 사용자가 영영 못 푼다.
        // (양끝이 맨 오른쪽에서 겹쳐 selected parquets: 1 로 굳던 제보 버그)
        if (curEdge === 'start' && idx > bucketState.end) {
          bucketState.start = bucketState.end;
          bucketState.end = idx;
          setDragging(curHandle, false);
          curHandle = he; curEdge = 'end';
          setDragging(curHandle, true);
        } else if (curEdge === 'end' && idx < bucketState.start) {
          bucketState.end = bucketState.start;
          bucketState.start = idx;
          setDragging(curHandle, false);
          curHandle = hs; curEdge = 'start';
          setDragging(curHandle, true);
        } else if (curEdge === 'start') {
          bucketState.start = idx;
        } else {
          bucketState.end = idx;
        }
        renderDateRange();
      };
      const up = () => {
        setDragging(curHandle, false);
        document.removeEventListener('pointermove', move);
        document.removeEventListener('pointerup', up);
        document.removeEventListener('pointercancel', up);
        persistBucketRange();
      };
      document.addEventListener('pointermove', move);
      document.addEventListener('pointerup', up);
      // 포인터가 취소되면(창 밖 드롭 등) pointerup 이 안 와 드래그가 붙어 있는다.
      document.addEventListener('pointercancel', up);
    };
    // 키보드: 핸들은 이미 tabindex=0 이지만 동작이 없었다. 겹쳐도 Tab 으로 각각
    // 잡히므로 마우스가 막혔을 때의 탈출구가 된다. 여기선 교차 대신 clamp 한다.
    const nudge = (edge, delta) => {
      if (!bucketState.loaded) return;
      const lim = last();
      const clamp = (v) => Math.min(Math.max(v, 0), lim);
      if (edge === 'start') bucketState.start = clamp(Math.min(bucketState.start + delta, bucketState.end));
      else bucketState.end = clamp(Math.max(bucketState.end + delta, bucketState.start));
      renderDateRange();
      persistBucketRange();
    };
    const onKey = (edge) => (e) => {
      const step = e.shiftKey ? 10 : 1;
      if (e.key === 'ArrowLeft') nudge(edge, -step);
      else if (e.key === 'ArrowRight') nudge(edge, step);
      else if (e.key === 'Home') nudge(edge, -bucketState.count);
      else if (e.key === 'End') nudge(edge, bucketState.count);
      else return;
      e.preventDefault();
    };
    if (hs) {
      hs.addEventListener('pointerdown', startDrag(hs, 'start'));
      hs.addEventListener('keydown', onKey('start'));
    }
    if (he) {
      he.addEventListener('pointerdown', startDrag(he, 'end'));
      he.addEventListener('keydown', onKey('end'));
    }
  }

  // ── 최신 태그 데이터 받기 ────────────────────────────────────────────────
  //
  // ⚠️ 설치 패널(Setup)에만 두면 **평생 안 받는 사람이 나온다**(사용자 지적).
  //    설정을 열 이유가 없는 사람에게는 그런 데이터가 있다는 사실 자체가 안 보인다.
  //    그래서 검색 화면, 기간 슬라이더 바로 위에 크게 붙인다 - 사용자가 "더 최근
  //    그림" 을 찾으려는 바로 그 자리다.
  //
  // 라벨의 기간은 **버킷 표에서 뽑는다.** 손으로 적으면 데이터와 갈린다
  // (실제 2025/09~2026/06 인데 2025.11 로 적을 뻔했다).
  let incrementState = null;      // /api/install-manager 의 tag_archive_increment
  let incrementBusy = false;
  let pushEndAfterBuckets = false;   // 설치 직후, 새 표가 오면 끝을 마지막으로 민다

  function missingBucketSpan() {
    // 날짜표에는 있는데 파일이 없는 구간 = 아직 안 받은 데이터.
    const buckets = bucketState.buckets || [];
    const have = incrementState?.file_count ?? 0;
    if (!buckets.length || have <= 0 || have >= buckets.length) return null;
    const first = buckets[have];
    const last = buckets[buckets.length - 1];
    if (!first || !last) return null;
    return { from: String(first.start_ym || '').replace('/', '.'),
             to: String(last.end_ym || '').replace('/', '.') };
  }

  function tagIncrementHtml() {
    if (!incrementState || incrementState.ready || !incrementState.base_ready) return '';
    const span = missingBucketSpan();
    return `
    <button type="button" class="search-tag-update" id="searchTagUpdateBtn"
            ${incrementBusy ? 'disabled' : ''}>
      <span class="stu-icon" aria-hidden="true">⬇</span>
      <span class="stu-stack">
        <span class="stu-title">${incrementBusy ? '받는 중...' : 'Download Dataset'}</span>
        <span class="stu-span">${incrementBusy ? '최신 태그 데이터' : (span ? `${span.from}-${span.to}` : '최신 태그 데이터')}</span>
      </span>
      <span class="stu-sub">${incrementBusy ? '' : '275MB'}</span>
    </button>`;
  }

  function dateRangeSliderHtml() {
    return tagIncrementHtml() + `
    <div class="search-daterange">
      <div class="dr-label-row">
        <span class="mod-section-label">기간 컷오프 (Date Cutoff)</span>
        <button type="button" class="header-guide-btn" data-naia-guide="기간 컷오프 — 태그 아카이브를 날짜 구간으로 제한합니다. 선택한 [시작–끝] 버킷만 검색해 속도를 높이고 모델 학습 컷오프에 맞춥니다.\\n\\n핸들을 드래그해 시작·끝 시점을 정하면 그 구간의 parquet만 스캔합니다(구간이 좁을수록 빠름).\\n\\n핸들에 마우스를 올리면 해당 YYYY/MM, 아래에 선택된 parquet 수가 표시됩니다. 위치는 자동 저장됩니다.">ⓘ 가이드</button>
      </div>
      <div class="dr-track" id="drTrack">
        <div class="dr-fill" id="drFill"></div>
        <div class="dr-handle" id="drHandleStart" data-edge="start" tabindex="0"><div class="dr-tip" id="drTipStart"></div></div>
        <div class="dr-handle" id="drHandleEnd" data-edge="end" tabindex="0"><div class="dr-tip" id="drTipEnd"></div></div>
      </div>
      <div class="dr-meta">
        <span class="dr-range" id="drRangeLabel">…</span>
        <span class="dr-count" id="drCountLabel">selected parquets: …</span>
      </div>
    </div>`;
  }

  function ensureDateRangeStyle() {
    if (document.getElementById('dr-slider-style')) return;
    const css = `
.search-tag-update{
  display:flex;align-items:center;gap:9px;width:100%;margin:0 0 10px;padding:11px 14px;
  cursor:pointer;text-align:left;border-radius:8px;
  border:1px solid rgba(132,206,94,0.60);background:rgba(20,34,16,0.92);
  color:rgb(178,232,146);font-family:var(--font-mono);font-size:12.5px;font-weight:600;
  transition:background .14s,color .14s,border-color .14s;
}
.search-tag-update:hover:not(:disabled){background:rgb(154,220,112);color:#0f1a0c;border-color:rgb(154,220,112)}
.search-tag-update:disabled{opacity:.62;cursor:default}
.search-tag-update .stu-icon{font-size:16px;line-height:1}
.search-tag-update .stu-stack{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px}
.search-tag-update .stu-title{font-size:13px;line-height:1.2}
.search-tag-update .stu-span{font-size:11.5px;font-weight:500;opacity:.82;line-height:1.2}
.search-tag-update .stu-sub{opacity:.66;font-size:10.5px;font-weight:500;white-space:nowrap}
.search-daterange{margin:2px 0}
.dr-label-row{display:flex;align-items:center;gap:8px;margin-bottom:2px}
.dr-label-row .mod-section-label{margin:0}
.dr-track{position:relative;height:6px;border-radius:3px;background:var(--bg-elevated,#2a2a33);margin:20px 7px 8px}
.dr-fill{position:absolute;top:0;height:100%;border-radius:3px;background:linear-gradient(90deg,var(--accent-blue,#8d7bd6),var(--accent-green,#5a9e6f))}
.dr-handle{position:absolute;top:50%;width:14px;height:14px;margin-left:-7px;transform:translateY(-50%);border-radius:50%;background:var(--text,#e8e8ee);border:2px solid var(--accent-blue,#8d7bd6);cursor:grab;touch-action:none;box-shadow:0 1px 3px rgba(0,0,0,.5);z-index:2}
.dr-handle:active{cursor:grabbing}
.dr-handle[data-edge="end"]{border-color:var(--accent-green,#5a9e6f)}
.dr-tip{position:absolute;bottom:18px;left:50%;transform:translateX(-50%);padding:2px 6px;border-radius:4px;background:#15151b;border:1px solid #33333f;color:var(--text,#e8e8ee);font-family:var(--font-mono,monospace);font-size:10px;white-space:nowrap;opacity:0;transition:opacity .12s;pointer-events:none}
.dr-handle:hover .dr-tip,.dr-handle.dragging .dr-tip{opacity:1}
.dr-meta{display:flex;justify-content:space-between;align-items:center;font-family:var(--font-mono,monospace);font-size:10px;color:var(--text-dim,#888)}
.dr-count{color:var(--accent-green,#5a9e6f)}`;
    const style = document.createElement('style');
    style.id = 'dr-slider-style';
    style.textContent = css;
    document.head.appendChild(style);
  }

  return {
    getRatingState,
    getRatingStore: () => ratingStore,
    getActiveRatings,
    setRatingState,
    setRatingsFromList,
    setRatingCounts,
    computeLocalFilteredCount,
    updateSearchCount,
    updatePromptGeneratedCount,
    sendActiveRatings,
    toggleRating,
    onFilterReset,
    onRatingUpdate,
    syncRatingButtons,
    onSearchState,
    onSearchProgress,
    onBucketDates,
    renderSearch,
    doSearch,
    toggleParquetMenu,
    openParquetUpload,
    selectParquetMode,
    runParquetAction,
    loadParquet,
    restoreSnapshot,
    openSaveForm,
    onSearchHistory,
    syncLibraryButton,
    getLibraryHost: () => libHost,
  };
}
