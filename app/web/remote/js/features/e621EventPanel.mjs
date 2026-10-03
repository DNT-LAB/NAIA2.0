// E621 연구모듈 패널.
//
// 배치(2026-10-03 개편, docs/E621_MODULE_UX_PROPOSAL_2026_10_03.md):
//   툴바 한 줄 / [분류 | 폴더 | 태그 | 선택한 태그] / 프롬프트 조립 트레이
//
// ⚠️ 그리는 방식 - 영역(data-e621-region)마다 따로 쓴다. 영역의 HTML 이 지난번과 같으면 건드리지 않는다.
//    예전에는 상태가 올 때마다 본문 전체를 innerHTML 로 갈아 끼워, 태그 하나만 눌러도 분류 · 폴더 · 태그 ·
//    상세의 스크롤이 전부 0 으로 돌아갔다(사용자 제보 2026-10-03). 그래서:
//      · 태그 목록 HTML 에는 '지금 고른 태그' · '조립에 담긴 태그' 를 넣지 않는다 → 클래스만 옮긴다(syncMarks).
//      · 입력 중인 값(검색어 · 템플릿)은 영역 HTML 에 넣지 않는다 → 쓴 뒤에 value 로 넣는다.
//      · 영역을 다시 쓸 때는 data-scroll-key 가 같은 스크롤 · 포커스를 되돌린다(swap).
// ⚠️ 그리는 곳이 둘이다 - 떠 있는 창(e621Window 의 본문)과, 떼어 낸 브라우저 창의 모듈 팝업 본문.
//    모양은 이 모듈이 싣는 PANEL_CSS 하나가 정한다(폭 반응은 .e6-root 의 컨테이너 질의).
// 클릭은 data-e621-act 로 위임해 받는다 - 공용 app.js 에 전역 함수를 늘리지 않는다.
export function createE621EventPanel({
  document,
  escHtml,
  setModuleParam,
  bindTagAssist,
  showToast,
  // 그릴 자리. 메인 화면은 떠 있는 창(e621Window)의 본문을 넘긴다. 없으면 예전처럼 모듈 팝업 본문
  // (별도 브라우저 창으로 떼어 낸 모듈은 그 창 전체가 모듈 팝업이다).
  moduleBody: host = null,
}) {
  const moduleBody = host || document.getElementById('modulePopupBody');
  const DEFAULT_TEMPLATE = '{{selected_tags}}';
  const REGIONS = ['toolbar', 'cats', 'folders', 'tags', 'detail', 'tray'];
  const send = (key, value) => setModuleParam('e621_event', key, value);
  const esc = value => escHtml(String(value ?? ''));
  const fmt = value => (Number(value) || 0).toLocaleString('en-US');
  const spaced = tag => String(tag || '').replace(/_/g, ' ');

  let lastState = null;
  // 영역마다 마지막으로 써 넣은 HTML. 같으면 다시 쓰지 않는다.
  let written = {};
  let marksSignature = null;
  let lastSearchText = null;
  // 화면 상태 - 이 탭의 것이다(서버에 두지 않는다: 다른 탭이 내 팝오버 · 펼침을 바꾸면 안 된다).
  const ui = {pop: '', searchDraft: null, expanded: new Set(), expandedFor: '', folds: new Set(), templateOpen: null};
  // 가짜 DOM(시험) 용 옛 길의 상태 - renderWhole 참고.
  let lastWholeSignature = '';
  let deferredState = null;
  let deferredTarget = null;

  ensureStyle(document);
  bindDelegates();

  function canQuery() {
    return Boolean(moduleBody) && typeof moduleBody.querySelector === 'function';
  }

  function selectedTagName() {
    return lastState && lastState.selected ? lastState.selected.tag : '';
  }

  function selectionSet() {
    return new Set((lastState?.selected_tags || []).map(row => row.exact_tag));
  }

  function weightLimits() {
    // 서버가 모드별 한도를 준다(지금은 세 모드 모두 0~2).
    const limits = lastState?.weight_limits || {};
    return limits[lastState?.selection_preview?.api_mode] || limits.NAI || {min: 0, max: 2, default: 1};
  }

  function formatWeight(value) {
    return String(Math.round(Number(value) * 100) / 100);
  }

  function isDefaultTemplate(text) {
    const value = String(text ?? '').trim();
    return !value || value === DEFAULT_TEMPLATE;
  }

  // ── 검색 일치 이유 ─────────────────────────────────────────────────────────
  // 응답 계약 = docs/e621_stage2_response_contract.ko.md. 이름이 통째로 같으면(match_grade 0) '정확'.
  const MATCH_LABELS = {
    tag_name: '이름',
    korean_name: '한국어 이름',
    korean_keywords: '검색어',
    korean_description: '한국어 설명',
    stored_body: '본문',
  };

  function matchFieldsOf(tag) {
    if (Array.isArray(tag.match_fields)) return tag.match_fields;
    // 옛 백엔드(필드 배열이 없다) - 예전 두 bool 로 대신한다.
    return [tag.matched_in_korean ? 'korean_name' : '', tag.matched_in_wiki ? 'stored_body' : ''].filter(Boolean);
  }

  function matchChips(tag, limit = Infinity) {
    const fields = matchFieldsOf(tag);
    if (!fields.length) return '';
    const compact = new Set(Array.isArray(tag.match_compact_fields) ? tag.match_compact_fields : []);
    const label = field => (field === 'tag_name' && tag.match_grade === 0 ? '정확' : (MATCH_LABELS[field] || field));
    // 줄에는 가장 높은 등급 하나만 보인다 - 나머지는 title 로.
    const rest = fields.slice(limit).map(label).join(' · ');
    return fields.slice(0, limit).map((field, index) => {
      const exact = field === 'tag_name' && tag.match_grade === 0;
      const classes = ['e6-match', exact ? 'exact' : '', field === 'stored_body' ? 'body' : '',
        compact.has(field) ? 'compact' : ''].filter(Boolean).join(' ');
      const title = (exact ? '태그 이름과 통째로 같습니다'
        : compact.has(field) ? `${label(field)} - 띄어쓰기를 빼고 맞았습니다` : `${label(field)}에서 맞았습니다`)
        + (rest && index === limit - 1 ? ` · 그 밖에: ${rest}` : '');
      return `<span class="${classes}" title="${esc(title)}">${esc(label(field))}</span>`;
    }).join('');
  }

  // ── 영역 HTML ──────────────────────────────────────────────────────────────
  function popHtml(state) {
    const summary = state.research_summary || {};
    const noDescription = summary.metadata_available === false ? '설명 미확인' : '설명 없음';
    if (ui.pop === 'hidden') {
      const items = state.hidden_items || [];
      const rows = items.map(tag => `<div class="e6-row e6-pop-row"><span class="e6-row-name e6-mono">${esc(spaced(tag))}</span>`
        + `<button class="e6-link" data-e621-act="restore" data-tag="${esc(tag)}">복원</button></div>`).join('');
      const more = (Number(state.hidden_total) || 0) > items.length
        ? `<div class="e6-note">외 ${fmt(state.hidden_total - items.length)}</div>` : '';
      return `<div class="e6-pop" data-e621-pop="hidden"><div class="e6-pop-list" data-scroll-key="pop-hidden">${
        rows || '<div class="e6-empty">숨긴 태그가 없습니다</div>'}${more}</div></div>`;
    }
    if (ui.pop === 'settings') {
      const stats = Object.hasOwn(summary, 'total')
        ? `태그 ${fmt(summary.total)} · 위키 본문 ${fmt(summary.with_body)} · 한글 검색 ${fmt(summary.with_korean_search)}`
          + ` · 한국어 설명 ${fmt(summary.with_korean_description)} · ${noDescription} ${fmt(summary.without_description)}` : '';
      // 서버 키는 부정형(disable_*)이다 - 화면은 긍정형으로 보이고 값을 뒤집어 보낸다.
      const check = (key, label, title) => `<label class="e6-check" title="${esc(title)}">`
        + `<input type="checkbox" data-e621-setting="${key}"${state[key] ? '' : ' checked'}><span>${label}</span></label>`;
      return `<div class="e6-pop" data-e621-pop="settings">${
        state.translation_control_visible === false ? '' : check('disable_translation', '한국어 표시', '태그 줄과 상세에 한국어 이름 · 설명을 보입니다')}${
        state.wiki_search_control_visible === false ? '' : check('disable_wiki_search', '위키 본문도 검색', '태그 이름 · 한국어뿐 아니라 저장된 위키 본문에서도 찾습니다')}${
        stats ? `<div class="e6-pop-stats">${esc(stats)}</div>` : ''}</div>`;
    }
    return '';
  }

  function toolbarHtml(state) {
    const summary = state.research_summary || {};
    const filter = state.content_filter || 'all';
    const noDescription = summary.metadata_available === false ? '설명 미확인' : '설명 없음';
    const options = [['all', '설명 상태'], ['with_body', '위키 본문 있음'], ['with_korean', '한국어 설명 있음'],
      ['with_korean_search', '한글 검색어 있음'], ['without_description', noDescription]]
      .map(([value, label]) => `<option value="${value}"${filter === value ? ' selected' : ''}>${label}</option>`).join('');
    const hidden = Number(state.hidden_total) || 0;
    const starred = state.view_mode === 'starred';
    return `<div class="e6-search">`
      + `<input class="mod-input" id="e621SearchInput" type="text" placeholder="태그 · 한국어 검색" autocomplete="off" spellcheck="false">`
      + `<button class="e6-search-x" data-e621-act="reset" title="검색 · 분류 · 필터 초기화" aria-label="초기화">×</button></div>`
      + `<div class="e6-seg" role="group" aria-label="보기">`
      + `<button class="${starred ? '' : 'on'}" data-e621-act="view" data-value="default">기본</button>`
      + `<button class="${starred ? 'on' : ''}" data-e621-act="view" data-value="starred" title="즐겨찾기한 태그만 봅니다">★ ${fmt(state.starred_total)}</button></div>`
      + `<select class="mod-input e6-filter${filter === 'all' ? '' : ' on'}" id="e621ContentFilter" data-native-select data-e621-filter aria-label="설명 상태">${options}</select>`
      + (summary.warning ? `<span class="e6-warn" title="${esc(summary.warning)}">${esc(summary.warning)}</span>` : '')
      + `<button class="e6-btn${ui.pop === 'hidden' ? ' on' : ''}${hidden ? '' : ' is-empty'}" data-e621-act="pop" data-pop="hidden" title="숨긴 태그 보기 · 복원">숨김 ${fmt(hidden)}</button>`
      + `<button class="e6-btn e6-btn-icon${ui.pop === 'settings' ? ' on' : ''}" data-e621-act="pop" data-pop="settings" title="표시 · 검색 설정" aria-label="설정">⚙</button>`
      + popHtml(state);
  }

  function catsHtml(state) {
    const categories = state.categories || [];
    const group = (section, label) => {
      const rows = categories.filter(item => item.section === section).map(item => {
        const classes = ['e6-row', item.selected ? 'selected' : '', item.matched ? 'matched' : ''].filter(Boolean).join(' ');
        return `<button class="${classes}" data-e621-act="category" data-value="${esc(item.name)}"${item.matched ? ' title="검색이 맞은 태그가 있습니다"' : ''}>`
          + `<span class="e6-row-name">${esc(spaced(item.name))}</span>`
          + (item.starred_count ? `<span class="e6-star">★${fmt(item.starred_count)}</span>` : '')
          + `<span class="e6-row-num">${fmt(item.tag_count)}</span></button>`;
      }).join('');
      return rows ? `<div class="e6-group-head">${label}</div>${rows}` : '';
    };
    return `<div class="e6-col-head">분류</div><div class="e6-list" data-scroll-key="cats">${group('General', '일반')}${group('Species', '종')}</div>`;
  }

  function foldersHtml(state) {
    const rows = (state.folders || []).map(folder =>
      `<button class="e6-row${folder.selected ? ' selected' : ''}" data-e621-act="folder" data-value="${esc(folder.name)}">`
      + `<span class="e6-row-name">${esc(folder.display)}</span><span class="e6-row-num">${fmt(folder.tag_count)}</span></button>`).join('');
    const empty = `<div class="e6-empty">${state.current_category ? '폴더 없음' : '분류를 고르면 보입니다'}</div>`;
    return `<div class="e6-col-head">폴더</div><div class="e6-list" data-scroll-key="${esc(`folders|${state.current_category || ''}`)}">${rows || empty}</div>`;
  }

  // 태그 줄 = 한 줄 3칸(영문 | 게시물 수 | 한글). ⚠️ 여기에는 '지금 고른 태그' · '조립에 담긴 태그' 를 넣지 않는다 -
  // 넣으면 태그를 누를 때마다 300줄을 다시 쓰고 스크롤이 처음으로 돌아간다. 그 둘은 syncMarks 가 클래스로 옮긴다.
  function tagRowHtml(tag, state) {
    const fields = matchFieldsOf(tag);
    const coverage = [
      tag.has_body ? '위키 본문' : '',
      tag.has_korean_description ? '한국어 설명' : '',
      tag.has_korean_search && !tag.has_korean_description ? '한글 검색어' : '',
    ].filter(Boolean).join(' · ') || (tag.review_status === 'metadata_unavailable' ? '설명 확인 불가' : '설명 없음');
    const korean = state.disable_translation ? '' : String(tag.kor || '');
    const title = [tag.display, korean, coverage].filter(Boolean).join('\n');
    const classes = ['e6-row', 'e6-tag', tag.starred ? 'starred' : '',
      fields.length && fields.every(field => field === 'stored_body') ? 'body-only' : ''].filter(Boolean).join(' ');
    return `<div class="${classes}" data-e621-act="open" data-tag="${esc(tag.tag)}" title="${esc(title)}">`
      + `<span class="e6-tag-en">${esc(tag.display)}</span>`
      + `<span class="e6-tag-num">${tag.starred ? '<i class="e6-star">★</i>' : ''}${esc(tag.count_label || '')}</span>`
      + `<span class="e6-tag-ko"><span class="e6-tag-ko-text">${esc(korean)}</span>${matchChips(tag, 1)}</span>`
      + `<button class="e6-tag-add" data-e621-act="toggle-selection" data-tag="${esc(tag.tag)}" tabindex="-1" aria-label="프롬프트 조립에 담기 · 빼기"></button>`
      + '</div>';
  }

  function tagsHtml(state) {
    const tags = state.tags || [];
    const offset = Number(state.tag_offset) || 0;
    const pageSize = Number(state.tag_page_size || state.tag_limit) || 300;
    const total = Number(state.tag_total) || 0;
    const range = total ? `${fmt(offset + 1)}–${fmt(offset + tags.length)} / ${fmt(total)}` : '0';
    const pager = total > pageSize ? `<div class="e6-pager">`
      + `<button class="e6-btn" data-e621-act="page" data-value="${Math.max(0, offset - pageSize)}"${state.has_previous ? '' : ' disabled'} aria-label="이전 태그 페이지">이전</button>`
      + `<span class="e6-dim">${Math.floor(offset / pageSize) + 1} / ${Math.ceil(total / pageSize)}</span>`
      + `<button class="e6-btn" data-e621-act="page" data-value="${offset + pageSize}"${state.has_next ? '' : ' disabled'} aria-label="다음 태그 페이지">다음</button></div>` : '';
    // 같은 목록인지 = 무엇을 보고 있나. 같으면 다시 써도 스크롤을 되돌리고, 다르면(다음 페이지 · 새 검색) 처음부터.
    const key = ['tags', state.search_text, state.current_category, state.current_level2, state.view_mode,
      state.content_filter, offset, state.disable_wiki_search ? 1 : 0].join('|');
    const rows = tags.map(tag => tagRowHtml(tag, state)).join('');
    return `<div class="e6-col-head">태그 <span class="e6-dim">${range}</span></div>`
      + `<div class="e6-list e6-tags" tabindex="0" data-scroll-key="${esc(key)}">${rows || '<div class="e6-empty">태그 없음</div>'}</div>${pager}`;
  }

  // 관계 · 추천 칩: 이름을 누르면 그 태그로 간다, 올리면 나오는 + 는 조립에 담는다(이미 담겼으면 ✓).
  function relChip(item, small = '') {
    const title = [item.kor, item.count ? `${fmt(item.count)} posts` : '',
      item.share ? `함께 ${Math.round(item.share * 100)}%` : ''].filter(Boolean).join(' · ');
    return `<span class="e6-chip${item.in_selection ? ' in-sel' : ''}">`
      + `<button class="e6-chip-name" data-e621-act="open" data-tag="${esc(item.tag)}" title="${esc(title)}">${esc(item.display || item.tag)}${small}</button>`
      + (item.in_selection ? '' : `<button class="e6-chip-add" data-e621-act="add" data-tag="${esc(item.tag)}" title="조립에 담기" aria-label="조립에 담기">+</button>`)
      + '</span>';
  }

  // 관계 한 줄: 칩 6개까지 + '외 N'(누르면 펼침). 서버가 준 것보다 더 있으면(하위 수천 개) 남은 수만 적는다.
  function relRow(label, title, items, key, render, total = items.length) {
    if (!items.length) return '';
    const open = ui.expanded.has(key);
    const shown = open ? items : items.slice(0, 6);
    const beyond = total - items.length;
    const more = open
      ? (items.length > 6 ? `<button class="e6-more" data-e621-act="expand" data-key="${key}">접기</button>` : '')
        + (beyond > 0 ? `<span class="e6-more is-static" title="게시물 수가 많은 순으로 여기까지 보입니다">외 ${fmt(beyond)}</span>` : '')
      : items.length > shown.length ? `<button class="e6-more" data-e621-act="expand" data-key="${key}">외 ${fmt(total - shown.length)}</button>`
        : beyond > 0 ? `<span class="e6-more is-static" title="게시물 수가 많은 순으로 여기까지 보입니다">외 ${fmt(beyond)}</span>` : '';
    return `<div class="e6-rel-row"><span class="e6-rel-label" title="${esc(title)}">${label}</span>`
      + `<span class="e6-chips">${shown.map(render).join('')}${more}</span></div>`;
  }

  function relationsHtml(relations) {
    if (!relations || relations.status !== 'available') return '';
    const rows = relRow('상위', '이 태그가 붙으면 함께 붙는 상위 태그(e621 포함 관계)', relations.broader || [], 'broader',
      item => relChip(item), relations.broader_total)
      + relRow('하위', '이 태그를 포함하는 하위 태그(e621 포함 관계)', relations.narrower || [], 'narrower',
        item => relChip(item), relations.narrower_total)
      + relRow('별칭', 'e621 별칭 - 입력 정규화 제안', relations.aliases || [], 'aliases',
        item => `<span class="e6-alias">${esc(item.from)} → ${esc(item.to)}</span>`)
      + relRow('함께', '같은 게시물에 자주 함께 붙는 태그(관측일 뿐 의미 관계가 아님). 숫자 = 함께 붙은 게시물 수',
        relations.cooccurrences || [], 'together',
        item => relChip(item, ` <small>${fmt(item.pair_count)}</small>`));
    if (!rows) return '';
    const snapshot = relations.snapshot ? ` title="e621 ${esc(relations.snapshot)} 기준"` : '';
    return `<section class="e6-sec e6-relations"><div class="e6-sec-head"${snapshot}>관계</div>${rows}</section>`;
  }

  function quotes(items, heading) {
    return (items || []).map(item => `<div class="e6-note">${esc(heading(item))}</div>`
      + `<pre class="e6-quote">${esc(item.quote || '')}</pre>`).join('');
  }

  // 연구자용 정보(검색어 · 검토 상태 · 근거 발췌 · 다른 사이트 연결)는 맨 아래에 접어 둔다. 없으면 그리지 않는다.
  function evidenceHtml(state, research) {
    if (state.disable_translation) return '';
    const status = research.review_label || state.selected.review_label || '';
    const lines = [
      research.korean_keywords ? `검색어: ${research.korean_keywords}` : '',
      [status, research.description_source].filter(Boolean).join(' · '),
      research.search_review_status === 'reviewed_search_terms' ? '한국어 검색어 · 직접 정의 대조 완료' : '',
      research.search_source_label || '',
      research.search_review_status === 'stale_evidence' ? '한국어 검색어 · 근거 변경으로 적용 보류' : '',
    ].filter(Boolean).map(line => `<div class="e6-note">${esc(line)}</div>`).join('');
    const evidence = quotes(research.description_evidence,
      item => ['설명 근거', item.site, item.retrieved_at?.slice(0, 10)].filter(Boolean).join(' · '))
      + quotes(research.search_evidence, item => ['검색어 근거', item.site || 'e621'].join(' · '));
    const links = (research.cross_site_links || []).map(link =>
      `<div class="e6-cross"><strong>${esc(`${link.site || 'danbooru'} · ${link.tag || ''}`)}</strong>`
      + `<div class="e6-note">${esc([link.relation_label || link.relation, link.status_label || link.status].filter(Boolean).join(' · '))}</div>`
      + (link.reason ? `<div class="e6-note">${esc(link.reason)}</div>` : '')
      + quotes(link.sources, item => `${item.site || ''} · ${item.exact_tag || ''}`) + '</div>').join('');
    if (!lines && !evidence && !links) return '';
    return `<details class="e6-fold" data-e621-fold="evidence"${ui.folds.has('evidence') ? ' open' : ''}>`
      + `<summary>근거 · 검토</summary><div class="e6-fold-body">${lines}${evidence}${
        links ? `<div class="e6-sec-head e6-cross-head">다른 사이트 연결</div>${links}` : ''}</div></details>`;
  }

  // 상세 칸: 읽는 순서 = 쓸모 순서. 머리(영문 · 한글 · 수) → 행동([+ 선택] 하나만 채운 단추) → 설명 → 관계 → 근거.
  function detailHtml(state) {
    const head = '<div class="e6-col-head">선택한 태그</div>';
    const selected = state.selected;
    if (!selected) return `${head}<div class="e6-detail"><div class="e6-empty e6-detail-empty">태그를 고르면 설명과 관계가 보입니다</div></div>`;
    const research = selected.research || {};
    const inSelection = selectionSet().has(selected.tag);
    const korean = state.disable_translation ? '' : String(research.korean_label || selected.kor || '');
    const chips = matchChips(selected);
    const body = String(state.wiki?.body ?? '');
    const koreanText = state.disable_translation ? '' : String(research.korean_description || '');
    // 설명 자리: 한국어 설명이 있으면 그것, 없으면 영어 위키 본문(6줄에서 접는다).
    let description = '';
    if (koreanText) {
      description = `<p class="e6-desc">${esc(koreanText)}</p>`;
    } else if (body) {
      const open = ui.expanded.has('wiki');
      const long = body.length > 300 || body.split('\n').length > 6;
      description = (state.disable_translation ? '' : `<div class="e6-note">${
        research.review_status === 'metadata_unavailable' ? '한국어 설명 사전을 확인할 수 없습니다' : '한국어 설명 없음'} · 위키 원문</div>`)
        + `<p class="e6-desc en${long && !open ? ' clamp' : ''}">${esc(body)}</p>`
        + (long ? `<button class="e6-link" data-e621-act="expand" data-key="wiki">${open ? '접기' : '더 보기'}</button>` : '');
    } else if (!state.disable_translation) {
      description = `<div class="e6-note">${research.review_status === 'metadata_unavailable'
        ? '한국어 설명 사전을 확인할 수 없습니다' : '설명 없음'}</div>`;
    }
    const wikiFold = koreanText && body
      ? `<details class="e6-fold" data-e621-fold="wiki"${ui.folds.has('wiki') ? ' open' : ''}><summary>위키 원문</summary>`
        + `<div class="e6-fold-body"><p class="e6-desc en">${esc(body)}</p></div></details>` : '';
    return `${head}<div class="e6-detail">`
      + `<div class="e6-detail-head"><span class="e6-detail-en">${esc(selected.display)}</span>`
      + (korean ? `<span class="e6-detail-ko">${esc(korean)}</span>` : '')
      + `<span class="e6-detail-num" title="e621 게시물 수">${esc(selected.count_label || '')}</span></div>`
      + `<div class="e6-detail-acts">`
      + `<button class="e6-primary${inSelection ? ' on' : ''}" data-e621-act="toggle-selection" data-tag="${esc(selected.tag)}" title="프롬프트 조립에 담기 · 빼기">${inSelection ? '✓ 선택됨' : '+ 선택'}</button>`
      + `<button class="e6-icon star${selected.starred ? ' on' : ''}" data-e621-act="star" title="${selected.starred ? '즐겨찾기 해제' : '즐겨찾기'}" aria-pressed="${selected.starred ? 'true' : 'false'}">★</button>`
      + `<button class="e6-icon hide" data-e621-act="hide" title="이 태그 숨기기(툴바의 '숨김' 에서 복원)" aria-label="숨기기">${ICON_HIDE}</button>`
      + (chips ? `<span class="e6-match-line" title="검색이 맞은 곳">${chips}</span>` : '')
      + '</div>'
      + `<div class="e6-detail-body" data-scroll-key="${esc(`detail|${selected.tag}`)}">${description}`
      + relationsHtml(selected.relations) + wikiFold + evidenceHtml(state, research) + '</div></div>';
  }

  // ── 프롬프트 조립 트레이 ────────────────────────────────────────────────────
  function selChipHtml(row) {
    const limits = weightLimits();
    const weight = Number(row.weight);
    const tone = weight > 1 ? ' up' : weight < 1 ? ' down' : '';
    const tag = esc(row.exact_tag);
    // 1.0 이면 숫자를 숨긴다(− + 만) - 칩이 짧아진다.
    const number = weight === 1 ? ''
      : `<input class="e6-sel-weight" type="number" min="${limits.min}" max="${limits.max}" step="0.05" value="${formatWeight(weight)}" data-e621-weight="${tag}" data-fk="w:${tag}" aria-label="가중치">`;
    return `<span class="e6-sel${tone}" draggable="true" data-sel-tag="${tag}" title="${esc([row.kor, '끌어서 순서를 바꿉니다'].filter(Boolean).join(' · '))}">`
      + `<button class="e6-sel-name" data-e621-act="open" data-tag="${tag}">${esc(row.display || row.exact_tag)}</button>`
      + `<button class="e6-sel-step" data-e621-act="weight-down" data-tag="${tag}" data-fk="d:${tag}" aria-label="가중치 내리기">−</button>`
      + number
      + `<button class="e6-sel-step" data-e621-act="weight-up" data-tag="${tag}" data-fk="u:${tag}" aria-label="가중치 올리기">+</button>`
      + `<button class="e6-sel-x" data-e621-act="remove" data-tag="${tag}" aria-label="조립에서 빼기">×</button></span>`;
  }

  // 자동으로 붙은 태그: 점선 테두리. 핀 = 내가 고른 것으로 올린다, × = 자동에서 뺀다(다시 안 붙는다).
  function autoChipHtml(item) {
    const tag = esc(item.tag);
    const anchors = (item.anchors || []).map(spaced).join(' · ');
    const title = [item.kor, anchors ? `${anchors} 와 함께${item.share ? ` ${Math.round(item.share * 100)}%` : ''}` : '',
      item.species ? '이 종에서만 주로 나오는 태그라 종을 함께 넣었습니다' : ''].filter(Boolean).join(' · ');
    return `<span class="e6-auto${item.species ? ' species' : ''}" title="${esc(title)}">`
      + `<button class="e6-sel-name" data-e621-act="open" data-tag="${tag}">${esc(item.display || item.tag)}</button>`
      + `<button class="e6-auto-pin" data-e621-act="add" data-tag="${tag}" title="내가 고른 태그로 고정" aria-label="고정">${ICON_PIN}</button>`
      + `<button class="e6-sel-x" data-e621-act="auto-exclude" data-tag="${tag}" title="자동에서 빼기" aria-label="자동에서 빼기">×</button></span>`;
  }

  function trayHtml(state) {
    if (state.prompt_testbench_visible === false) return '';
    const rows = state.selected_tags || [];
    const auto = state.auto_related || null; // 옛 백엔드에는 없다 - 그러면 예전처럼 '함께' 추천만 보인다.
    const autoTags = auto?.enabled ? (auto.tags || []) : [];
    const chips = rows.length
      ? rows.map(selChipHtml).join('') + (autoTags.length ? `<span class="e6-chip-sep" aria-hidden="true"></span>${autoTags.map(autoChipHtml).join('')}` : '')
      : '<span class="e6-hint">태그 줄의 + 또는 더블클릭으로 담습니다</span>';
    const excluded = auto?.excluded || [];
    const autoControls = auto ? `<button class="e6-switch${auto.enabled ? ' on' : ''}" data-e621-act="auto-toggle" aria-pressed="${auto.enabled ? 'true' : 'false'}" title="고른 태그와 늘 함께 붙는 코어 태그를 자동으로 덧붙입니다">자동</button>`
      + `<span class="e6-stepper${auto.enabled ? '' : ' is-off'}" title="자동으로 덧붙일 최대 개수">`
      + `<button data-e621-act="auto-step" data-delta="-1" aria-label="줄이기">−</button><b>${fmt(auto.limit)}</b>`
      + `<button data-e621-act="auto-step" data-delta="1" aria-label="늘리기">+</button></span>`
      + (excluded.length ? `<button class="e6-link" data-e621-act="auto-reset" title="${esc(`뺀 태그: ${excluded.map(spaced).join(', ')}`)}">뺀 ${fmt(excluded.length)}개 되돌리기</button>` : '') : '';
    const suggestions = auto?.enabled ? [] : (state.selection_suggestions?.candidates || []);
    const suggest = suggestions.length
      ? `<div class="e6-suggest"><span class="e6-rel-label" title="고른 태그들과 같은 게시물에 자주 함께 붙는 태그">함께</span>`
        + `<span class="e6-chips" data-scroll-key="tray-suggest">${suggestions.map(item => relChip(item)).join('')}</span></div>` : '';
    // 템플릿 칸: 기본값이면 접어 둔다(미리보기만 보인다). 사용자가 한 번 펴거나 접으면 그 선택을 따른다.
    const collapsed = ui.templateOpen === null ? isDefaultTemplate(state.testbench) : !ui.templateOpen;
    return `<div class="e6-tray-head"><span class="e6-tray-title">프롬프트 조립</span>`
      + `<span class="e6-dim">선택 ${fmt(rows.length)}${auto?.enabled ? ` + 자동 ${fmt(autoTags.length)}` : ''}</span><span class="e6-spacer"></span>`
      + autoControls
      + `<label class="e6-check" title="메인 프롬프트의 접두 · 접미 · 와일드카드를 함께 씁니다"><input type="checkbox" data-e621-pipeline${state.use_main_pipeline === false ? '' : ' checked'}><span>메인 설정</span></label>`
      + `<button class="e6-btn" data-e621-act="clear"${rows.length ? '' : ' disabled'}>비우기</button></div>`
      + `<div class="e6-chips e6-tray-chips" data-scroll-key="tray-chips">${chips}</div>${suggest}`
      + `<div class="e6-out"><div class="e6-out-main">`
      // ⚠️ 템플릿 글은 여기 넣지 않는다(쓴 뒤 value 로 넣는다) - 넣으면 한 글자 칠 때마다 이 영역이 통째로 바뀐다.
      + `<textarea class="mod-textarea e6-template${collapsed ? ' is-collapsed' : ''}" id="e621Testbench" rows="1" spellcheck="false" placeholder="${DEFAULT_TEMPLATE} 자리에 조립한 태그가 들어갑니다(없으면 맨 뒤)"></textarea>`
      + `<div class="e6-preview" data-e621-region="preview"></div></div>`
      + `<button class="e6-link e6-template-toggle" data-e621-act="template-toggle" title="조립한 태그 앞뒤에 붙일 글(템플릿)">${collapsed ? '템플릿' : '템플릿 접기'}</button>`
      + `<button class="e6-go" data-e621-act="generate">생성</button></div>`;
  }

  // 미리보기 = [생성] 이 실제로 보낼 글(서버가 같은 함수로 만든다). 메인 설정을 쓰면 접두 · 접미가 더해진다.
  function previewHtml(state) {
    const preview = state.selection_preview;
    if (!preview) return '';
    if (preview.error) return `<span class="e6-pv-error">${esc(preview.error)}</span>`;
    const segments = preview.segments || [];
    if (!segments.length) return '<span class="e6-dim">조립할 태그가 없습니다</span>';
    const names = {manual: '고른 태그', auto: '자동으로 붙은 태그', template: '템플릿'};
    return segments.map(segment => `<span class="e6-pv-${esc(segment.source)}" title="${names[segment.source] || ''}">${esc(segment.text)}</span>`)
      .join('<span class="e6-pv-sep">, </span>')
      + (state.use_main_pipeline === false ? ''
        : '<span class="e6-pv-tail" title="[생성] 때 메인 프롬프트의 접두 · 접미 · 와일드카드가 더해집니다"> + 메인 설정</span>');
  }

  function regionsHtml(state) {
    return {
      toolbar: toolbarHtml(state),
      cats: catsHtml(state),
      folders: foldersHtml(state),
      tags: tagsHtml(state),
      detail: detailHtml(state),
      tray: trayHtml(state),
    };
  }

  function panelClasses(state, html) {
    return ['e6-panel', state.disable_translation ? 'no-ko' : '', html.tray ? '' : 'no-tray'].filter(Boolean).join(' ');
  }

  function skeletonHtml(state, html) {
    return `<div class="e6-root"><div class="${panelClasses(state, html)}">`
      + `<div class="e6-toolbar" data-e621-region="toolbar">${html.toolbar}</div>`
      + '<div class="e6-main">'
      + `<section class="e6-col e6-col-cats" data-e621-region="cats">${html.cats}</section>`
      + `<section class="e6-col e6-col-folders" data-e621-region="folders">${html.folders}</section>`
      + `<section class="e6-col e6-col-tags" data-e621-region="tags">${html.tags}</section>`
      + `<section class="e6-col e6-col-detail" data-e621-region="detail">${html.detail}</section>`
      + '</div>'
      + `<section class="e6-tray" data-e621-region="tray">${html.tray}</section>`
      + '</div></div>';
  }

  function notLoadedHtml(state) {
    return `<div class="mod-section"><div class="mod-section-label">E621 연구모듈</div>`
      + `<div class="mod-empty">E621 데이터가 로드되지 않았습니다.</div><div class="mod-status">${esc(state.data_path || '')}</div></div>`;
  }

  // ── 영역 쓰기 ──────────────────────────────────────────────────────────────
  // 영역을 다시 쓰되, 같은 목록(data-scroll-key 가 같은 것)의 스크롤과 포커스를 되돌린다.
  function swap(element, html) {
    const scrolls = new Map();
    element.querySelectorAll('[data-scroll-key]').forEach(node => scrolls.set(node.dataset.scrollKey, node.scrollTop));
    const active = document.activeElement;
    let focus = null;
    if (active && active !== element && element.contains(active)) {
      const key = active.id ? `#${active.id}` : (active.dataset?.fk ? `fk:${active.dataset.fk}` : '');
      if (key) {
        focus = {key, value: active.id ? active.value : undefined};
        try {
          focus.start = active.selectionStart;
          focus.end = active.selectionEnd;
        } catch (error) { /* number 입력은 선택 범위를 못 읽는다 */ }
      }
    }
    element.innerHTML = html;
    element.querySelectorAll('[data-scroll-key]').forEach(node => {
      const top = scrolls.get(node.dataset.scrollKey);
      if (top) node.scrollTop = top;
    });
    if (!focus) return;
    const target = focus.key.startsWith('#')
      ? element.querySelector(focus.key)
      : [...element.querySelectorAll('[data-fk]')].find(node => `fk:${node.dataset.fk}` === focus.key);
    if (!target) return;
    if (focus.value !== undefined) target.value = focus.value;
    target.focus({preventScroll: true});
    try {
      if (typeof focus.start === 'number') target.setSelectionRange(focus.start, focus.end);
    } catch (error) { /* 위와 같다 */ }
  }

  // 입력 중인 값은 영역 HTML 밖에 있다 - 쓴 뒤에, 그리고 서버 값이 바뀌었을 때 여기서 맞춘다(치는 중이면 안 건드린다).
  function syncInputs(state, {trayWritten = false} = {}) {
    const search = document.getElementById('e621SearchInput');
    const wantSearch = ui.searchDraft ?? state.search_text ?? '';
    if (search && search.value !== wantSearch && (document.activeElement !== search || ui.searchDraft === null)) {
      search.value = wantSearch;
    }
    const testbench = document.getElementById('e621Testbench');
    if (!testbench) return;
    if (trayWritten && bindTagAssist) bindTagAssist(testbench);
    const wantTemplate = String(state.testbench ?? '');
    if (testbench.value !== wantTemplate && (trayWritten || document.activeElement !== testbench)) testbench.value = wantTemplate;
  }

  // 태그 줄의 '지금 고른 것' · '조립에 담긴 것' · '자동으로 붙은 것' 표시 - 줄을 다시 쓰지 않고 클래스만 옮긴다.
  function syncMarks(state, force = false) {
    if (!canQuery()) return;
    const selected = state.selected?.tag || '';
    const chosen = new Set((state.selected_tags || []).map(row => row.exact_tag));
    const auto = new Set((state.auto_related?.enabled ? state.auto_related.tags || [] : []).map(item => item.tag));
    const signature = `${selected}\n${[...chosen].join('\u0001')}\n${[...auto].join('\u0001')}`;
    if (!force && signature === marksSignature) return;
    marksSignature = signature;
    moduleBody.querySelectorAll('.e6-tag').forEach(row => {
      const tag = row.dataset.tag;
      row.classList.toggle('selected', tag === selected);
      row.classList.toggle('in-sel', chosen.has(tag));
      row.classList.toggle('in-auto', auto.has(tag));
    });
  }

  function paintPreview(state, panel) {
    const html = previewHtml(state);
    if (written.preview === html) return;
    const element = panel.querySelector('[data-e621-region="preview"]');
    if (!element) return;
    element.innerHTML = html;
    element.classList.toggle('is-empty', !html);
    written.preview = html;
  }

  function paint(state) {
    const html = regionsHtml(state);
    const panel = moduleBody.querySelector('.e6-panel');
    if (!panel) {
      // 처음이거나, 떼어 낸 창에서 다른 모듈이 본문을 썼다 - 뼈대부터 쓴다.
      moduleBody.innerHTML = skeletonHtml(state, html);
      written = {...html, preview: null};
      const mounted = moduleBody.querySelector('.e6-panel');
      syncInputs(state, {trayWritten: true});
      if (mounted) paintPreview(state, mounted);
      syncMarks(state, true);
      return;
    }
    panel.className = panelClasses(state, html);
    let trayWritten = false;
    let tagsWritten = false;
    for (const name of REGIONS) {
      if (written[name] === html[name]) continue;
      const element = panel.querySelector(`[data-e621-region="${name}"]`);
      if (!element) continue;
      swap(element, html[name]);
      written[name] = html[name];
      if (name === 'tray') {
        trayWritten = true;
        written.preview = null; // 트레이를 새로 썼으니 그 안의 미리보기 자리도 비었다.
      }
      if (name === 'tags') tagsWritten = true;
    }
    syncInputs(state, {trayWritten});
    paintPreview(state, panel);
    syncMarks(state, tagsWritten);
  }

  // 화면 상태(팝오버 · 펼침)만 바뀌었을 때 - 서버를 거치지 않고 지금 상태로 다시 그린다.
  function repaint() {
    if (lastState && lastState.data_loaded && canQuery()) paint(lastState);
  }

  // ── 가짜 DOM(시험) 용 옛 길 ───────────────────────────────────────────────
  // 영역을 찾을 수 없는 환경(querySelector 없는 시험용 document)에서는 본문을 통째로 쓴다. 이때는 예전 보호를 그대로
  // 쓴다: 템플릿을 치는 중이고 나머지가 그대로면 건너뛰고, 포커스를 잃을 때 한 번 그린다.
  function focusedTestbench() {
    const active = document.activeElement;
    if (!active || !moduleBody || !moduleBody.contains(active)) return null;
    return active.tagName === 'TEXTAREA' && active.id === 'e621Testbench' ? active : null;
  }

  function wholeSignature(state) {
    if (!state || !state.data_loaded) return JSON.stringify({loaded: false, path: state?.data_path || ''});
    const rest = {...state};
    delete rest.testbench;
    delete rest.selection_preview;
    return JSON.stringify(rest);
  }

  function flushDeferred() {
    const pending = deferredState;
    deferredTarget = null;
    deferredState = null;
    if (pending) globalThis.setTimeout(() => { if (!focusedTestbench()) render(pending); }, 0);
  }

  function renderWhole(state) {
    const signature = wholeSignature(state);
    const focused = focusedTestbench();
    if (focused && lastWholeSignature === signature) {
      deferredState = state;
      if (deferredTarget !== focused) {
        if (deferredTarget) deferredTarget.removeEventListener('blur', flushDeferred);
        deferredTarget = focused;
        focused.addEventListener('blur', flushDeferred, {once: true});
      }
      return;
    }
    if (deferredTarget) deferredTarget.removeEventListener('blur', flushDeferred);
    deferredTarget = null;
    deferredState = null;
    lastWholeSignature = signature;
    moduleBody.innerHTML = state.data_loaded ? skeletonHtml(state, regionsHtml(state)) : notLoadedHtml(state);
    if (state.data_loaded) syncInputs(state, {trayWritten: true});
  }

  function render(state) {
    if (!state || !moduleBody) return;
    const previousSearch = lastSearchText;
    lastState = state;
    lastSearchText = state.search_text ?? '';
    // 서버의 검색어가 바뀌었다(검색 · 초기화가 반영됐다) - 치다 만 글은 버리고 서버 값을 따른다.
    if (previousSearch !== lastSearchText) ui.searchDraft = null;
    const selected = state.selected?.tag || '';
    if (ui.expandedFor !== selected) {
      ui.expanded.clear();
      ui.expandedFor = selected;
    }
    if (!canQuery()) {
      renderWhole(state);
      return;
    }
    if (!state.data_loaded) {
      moduleBody.innerHTML = notLoadedHtml(state);
      written = {};
      marksSignature = null;
      return;
    }
    paint(state);
  }

  // ── 조작 ───────────────────────────────────────────────────────────────────
  function search() {
    const input = document.getElementById('e621SearchInput');
    send('search', input ? input.value : '');
  }

  function reset() {
    ui.searchDraft = null;
    const input = document.getElementById('e621SearchInput');
    if (input) input.value = '';
    send('reset', '1');
  }

  function toggleStar() {
    const tag = selectedTagName();
    if (!tag) {
      if (showToast) showToast('태그를 먼저 고르세요', 'error');
      return;
    }
    send('toggle_star', tag);
  }

  function hideSelected() {
    const tag = selectedTagName();
    if (!tag) {
      if (showToast) showToast('태그를 먼저 고르세요', 'error');
      return;
    }
    send('hide', tag);
  }

  function generate() {
    const testbench = document.getElementById('e621Testbench');
    send('generate', testbench ? testbench.value : '');
  }

  // 누른 줄을 서버 응답 전에 먼저 표시한다(상세는 응답이 와야 바뀐다).
  function markSelectedNow(tag) {
    if (!canQuery()) return;
    moduleBody.querySelectorAll('.e6-tag.selected').forEach(row => row.classList.remove('selected'));
    marksSignature = null;
    return [...moduleBody.querySelectorAll('.e6-tag')].find(row => row.dataset.tag === tag)?.classList.add('selected');
  }

  function bindDelegates() {
    // 떼어 낸 창에서는 모듈 팝업 본문(다른 모듈도 그리는 곳)에 걸린다 - data-e621-* 표식이 있는 것만 받는다.
    if (!moduleBody || typeof moduleBody.addEventListener !== 'function' || moduleBody.dataset?.e621Delegated) return;
    if (moduleBody.dataset) moduleBody.dataset.e621Delegated = '1';
    const clampWeight = value => {
      const limits = weightLimits();
      return Math.min(limits.max, Math.max(limits.min, Math.round(value * 100) / 100));
    };

    moduleBody.addEventListener('click', event => {
      // 팝오버 밖을 누르면 닫는다(이어서 누른 것의 동작은 그대로 한다).
      if (ui.pop && !event.target?.closest?.('.e6-pop,[data-e621-act="pop"]')) {
        ui.pop = '';
        repaint();
      }
      const target = event.target?.closest?.('[data-e621-act]');
      if (!target || !moduleBody.contains(target) || target.disabled) return;
      const {tag = '', value = ''} = target.dataset;
      const current = (lastState?.selected_tags || []).find(row => row.exact_tag === tag);
      const auto = lastState?.auto_related;
      switch (target.dataset.e621Act) {
        case 'open':
          markSelectedNow(tag);
          send('selected_tag', tag);
          break;
        case 'add': send('selected_tags_add', {exact_tag: tag}); break;
        case 'remove': send('selected_tags_remove', {exact_tag: tag}); break;
        case 'toggle-selection':
          send(selectionSet().has(tag) ? 'selected_tags_remove' : 'selected_tags_add', {exact_tag: tag});
          break;
        case 'clear': send('selected_tags_clear', null); break;
        case 'weight-up':
        case 'weight-down':
          if (current) {
            const step = target.dataset.e621Act === 'weight-up' ? 0.1 : -0.1;
            send('selected_tags_weight', {exact_tag: tag, weight: clampWeight(Number(current.weight) + step)});
          }
          break;
        // 고른 분류 · 폴더를 다시 누르면 푼다.
        case 'category': send('category', lastState?.current_category === value ? '' : value); break;
        case 'folder': send('level2', lastState?.current_level2 === value ? '' : value); break;
        case 'page': send('tag_offset', value); break;
        case 'view': send('view_mode', value); break;
        case 'reset': reset(); break;
        case 'star': toggleStar(); break;
        case 'hide': hideSelected(); break;
        case 'restore': send('restore', tag); break;
        case 'generate': generate(); break;
        case 'pop':
          ui.pop = ui.pop === target.dataset.pop ? '' : target.dataset.pop;
          repaint();
          break;
        case 'expand': {
          const key = target.dataset.key || '';
          if (ui.expanded.has(key)) ui.expanded.delete(key); else ui.expanded.add(key);
          repaint();
          break;
        }
        case 'template-toggle': {
          const textarea = document.getElementById('e621Testbench');
          const collapsedNow = !textarea || textarea.classList.contains('is-collapsed');
          ui.templateOpen = collapsedNow;
          repaint();
          if (collapsedNow) document.getElementById('e621Testbench')?.focus();
          break;
        }
        case 'auto-toggle': send('auto_related_enabled', !(auto && auto.enabled)); break;
        case 'auto-step':
          if (auto) {
            const next = Math.min(Number(auto.limit_max) || 12, Math.max(0, (Number(auto.limit) || 0) + Number(target.dataset.delta || 0)));
            if (next !== auto.limit) send('auto_related_limit', next);
          }
          break;
        case 'auto-exclude': send('auto_related_exclude', {exact_tag: tag}); break;
        case 'auto-reset': send('auto_related_reset', null); break;
        default: break;
      }
    });

    // 태그 줄 더블클릭 = 조립에 담기(상세를 거치지 않는다).
    moduleBody.addEventListener('dblclick', event => {
      const row = event.target?.closest?.('.e6-tag');
      if (!row || event.target.closest('.e6-tag-add')) return;
      if (!selectionSet().has(row.dataset.tag)) send('selected_tags_add', {exact_tag: row.dataset.tag});
    });

    moduleBody.addEventListener('change', event => {
      const input = event.target;
      if (input?.dataset?.e621Weight) {
        const value = Number(input.value);
        if (Number.isFinite(value)) send('selected_tags_weight', {exact_tag: input.dataset.e621Weight, weight: clampWeight(value)});
      } else if (input?.matches?.('[data-e621-pipeline]')) {
        send('use_main_pipeline', Boolean(input.checked));
      } else if (input?.dataset?.e621Setting) {
        send(input.dataset.e621Setting, String(!input.checked));
      } else if (input?.matches?.('[data-e621-filter]')) {
        send('content_filter', input.value);
      }
    });

    moduleBody.addEventListener('input', event => {
      const input = event.target;
      if (input?.id === 'e621SearchInput') ui.searchDraft = input.value;
      else if (input?.id === 'e621Testbench') {
        // 치는 동안에는 칸을 편 채로 둔다 - 글을 다 지워 기본값이 돼도 치던 칸이 접히면 안 된다.
        ui.templateOpen = true;
        send('testbench', input.value);
      }
    });

    moduleBody.addEventListener('keydown', event => {
      const target = event.target;
      if (!target?.closest?.('.e6-panel')) return;
      if (target.id === 'e621SearchInput') {
        if (event.key === 'Enter') {
          event.preventDefault();
          search();
        }
        return;
      }
      if (event.key === 'Escape' && ui.pop) {
        ui.pop = '';
        repaint();
        return;
      }
      const typing = target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT';
      if (event.key === '/' && !typing) {
        event.preventDefault();
        const input = document.getElementById('e621SearchInput');
        input?.focus();
        input?.select();
        return;
      }
      // 태그 목록: ↑↓ 로 옮기고 Enter 로 조립에 담는다 · 뺀다.
      const list = target.closest('.e6-tags');
      if (!list || typing) return;
      const rows = [...list.querySelectorAll('.e6-tag')];
      const index = rows.findIndex(row => row.classList.contains('selected'));
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        const next = rows[Math.min(rows.length - 1, Math.max(0, index + (event.key === 'ArrowDown' ? 1 : -1)))];
        if (!next || next === rows[index]) return;
        markSelectedNow(next.dataset.tag);
        next.scrollIntoView({block: 'nearest'});
        send('selected_tag', next.dataset.tag);
      } else if (event.key === 'Enter' && index >= 0) {
        event.preventDefault();
        const tag = rows[index].dataset.tag;
        send(selectionSet().has(tag) ? 'selected_tags_remove' : 'selected_tags_add', {exact_tag: tag});
      }
    });

    // <details> 를 펼친 상태는 다시 그려도 남긴다. toggle 은 위로 올라오지 않아 capture 로 받는다.
    moduleBody.addEventListener('toggle', event => {
      const name = event.target?.dataset?.e621Fold;
      if (!name) return;
      if (event.target.open) ui.folds.add(name); else ui.folds.delete(name);
      // 방금 바뀐 것은 화면에 이미 있다 - 다음 상태에서 같은 내용을 다시 쓰지 않게 기록만 맞춘다.
      if (lastState?.data_loaded && written.detail !== undefined) written.detail = detailHtml(lastState);
    }, true);

    // 선택 태그 순서 = 조립 순서. 칩을 끌어 다른 칩 위에 놓으면 그 자리로 옮긴다.
    let dragging = '';
    moduleBody.addEventListener('dragstart', event => {
      const chip = event.target?.closest?.('[data-sel-tag]');
      if (!chip) return;
      dragging = chip.dataset.selTag;
      event.dataTransfer?.setData?.('text/plain', dragging);
      chip.classList.add('dragging');
    });
    moduleBody.addEventListener('dragover', event => {
      if (dragging && event.target?.closest?.('[data-sel-tag]')) event.preventDefault();
    });
    moduleBody.addEventListener('drop', event => {
      const chip = event.target?.closest?.('[data-sel-tag]');
      if (!dragging || !chip) return;
      event.preventDefault();
      const order = (lastState?.selected_tags || []).map(row => row.exact_tag);
      const index = order.indexOf(chip.dataset.selTag);
      if (index >= 0 && chip.dataset.selTag !== dragging) send('selected_tags_move', {exact_tag: dragging, index});
      dragging = '';
    });
    moduleBody.addEventListener('dragend', () => {
      dragging = '';
      moduleBody.querySelectorAll?.('.e6-sel.dragging').forEach(element => element.classList.remove('dragging'));
    });
  }

  // 밖에서 부르는 것은 상태를 넘기는 render 하나다. 조작은 전부 위의 위임 클릭이 받는다.
  return {render};
}

const ICON_HIDE = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
  + '<path d="M3 3l18 18"/><path d="M10.6 5.1A10.9 10.9 0 0 1 12 5c6 0 10 7 10 7a17.6 17.6 0 0 1-3.3 4.2"/>'
  + '<path d="M6.6 6.6A17.3 17.3 0 0 0 2 12s4 7 10 7a10.6 10.6 0 0 0 4.4-1"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/></svg>';
const ICON_PIN = '<svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
  + '<path d="M12 17v5"/><path d="M9 3h6l-1 6 3 3v2H7v-2l3-3z"/></svg>';

// 패널 스타일은 style.css 가 아니라 패널과 함께 싣는다 - 패널이 그리는 곳(떠 있는 창 · 떼어 낸 창의 모듈 팝업)
// 어디서나 같아야 한다. 새 이름공간(e6-)이라 style.css 의 옛 .e621-* 규칙과 얽히지 않는다.
//
// 원칙(개편안 6절):
//   · 테두리는 그릇(목록 상자 · 상세 · 트레이)에만. 그 안의 줄은 테두리 없이 hover 배경.
//   · 글자 크기 12(머리 · 고른 태그) / 11(목록 · 본문) / 10(부가). 상세의 태그 이름만 14.
//   · 색의 뜻: 보라 = 지금 보고 있는 것 · 초록 = 조립에 담긴 것 · 노랑 = 즐겨찾기 · 빨강 = 파괴 동작의 hover.
//   · mono 는 영문 태그와 숫자만. 줄 높이 24px, 간격 4 · 8.
const STYLE_ID = 'e621-panel-style';
const PANEL_CSS = `
.e6-root{flex:1 1 auto;height:100%;min-height:0;display:flex;flex-direction:column;container-type:inline-size;container-name:e6}
.e6-panel{flex:1 1 auto;min-height:0;display:grid;grid-template-rows:auto minmax(0,1fr) auto;gap:8px;
  color:var(--text-muted);font-family:var(--font-display);font-size:11px;line-height:1.4}
.e6-panel.no-tray{grid-template-rows:auto minmax(0,1fr)}
/* :where 로 낮춘다 - 아래의 클래스 하나짜리 규칙(칩 이름의 mono 등)이 이겨야 한다. */
:where(.e6-panel) button,:where(.e6-panel) select{font-family:inherit}
.e6-panel button:disabled{opacity:0.35;cursor:default}
.e6-mono{font-family:var(--font-mono)}
.e6-dim{color:var(--text-dim);font-weight:400}
.e6-spacer{flex:1 1 auto}
.e6-empty{padding:16px 8px;color:var(--text-dim);font-size:11px;text-align:center}
.e6-note{margin-top:4px;color:var(--text-dim);font-size:10px;line-height:1.5;overflow-wrap:anywhere}
.e6-star{color:#e8c76a;font-style:normal}
.e6-link{flex:0 0 auto;padding:0;border:0;background:transparent;color:var(--accent-glow);font-size:10px;white-space:nowrap;cursor:pointer}
.e6-link:hover{color:var(--text-primary);text-decoration:underline}

/* 단추 · 입력 */
.e6-btn{flex:0 0 auto;height:24px;padding:0 10px;border:1px solid var(--border-dim);border-radius:4px;background:transparent;
  color:var(--text-muted);font-size:11px;white-space:nowrap;cursor:pointer}
.e6-btn:hover:not(:disabled){background:var(--bg-hover);color:var(--text-primary)}
.e6-btn.on{border-color:var(--accent);color:var(--text-primary)}
.e6-btn.is-empty{color:var(--text-dim)}
.e6-btn-icon{width:26px;padding:0;font-size:13px}
.e6-check{flex:0 0 auto;display:inline-flex;align-items:center;gap:4px;color:var(--text-muted);font-size:11px;white-space:nowrap;cursor:pointer}
.e6-check input{margin:0;accent-color:var(--accent)}

/* 툴바 - 한 줄 */
.e6-toolbar{position:relative;display:flex;align-items:center;gap:8px;min-width:0}
.e6-search{position:relative;flex:1 1 auto;min-width:120px}
.e6-search .mod-input{height:26px;padding:0 26px 0 10px;font-size:11px}
.e6-search-x{position:absolute;top:2px;right:2px;width:22px;height:22px;border:0;border-radius:3px;background:transparent;
  color:var(--text-dim);font-size:14px;line-height:1;cursor:pointer}
.e6-search-x:hover{background:var(--bg-hover);color:var(--text-primary)}
.e6-seg{flex:0 0 auto;display:inline-flex;border:1px solid var(--border-dim);border-radius:4px;overflow:hidden}
.e6-seg button{height:24px;padding:0 10px;border:0;background:transparent;color:var(--text-muted);font-size:11px;white-space:nowrap;cursor:pointer}
.e6-seg button:hover{background:var(--bg-hover)}
.e6-seg button.on{background:rgba(124,106,239,0.24);color:var(--text-primary)}
.e6-toolbar .e6-filter{flex:0 0 auto;width:auto;max-width:150px;height:26px;padding:0 6px;font-family:var(--font-display);font-size:11px}
.e6-toolbar .e6-filter.on{border-color:var(--accent);color:var(--text-primary)}
.e6-warn{flex:0 1 auto;min-width:0;overflow:hidden;color:#e8b46a;font-size:10px;text-overflow:ellipsis;white-space:nowrap}
.e6-pop{position:absolute;top:calc(100% + 4px);right:0;z-index:2;width:260px;max-width:100%;padding:8px;box-sizing:border-box;
  border:1px solid var(--border-dim);border-radius:6px;background:var(--bg-surface);box-shadow:0 10px 28px rgba(0,0,0,0.55);
  display:flex;flex-direction:column;gap:8px}
.e6-pop-list{max-height:264px;overflow:auto}
.e6-pop-row{cursor:default}
.e6-pop-stats{padding-top:8px;border-top:1px solid var(--border-dim);color:var(--text-dim);font-size:10px;line-height:1.5}

/* 네 칸 */
.e6-main{min-height:0;display:grid;gap:8px;
  grid-template-columns:minmax(120px,0.62fr) minmax(104px,0.5fr) minmax(220px,1.15fr) minmax(250px,1.25fr)}
.e6-col{min-width:0;min-height:0;display:flex;flex-direction:column}
.e6-col-head{flex:0 0 auto;display:flex;align-items:baseline;gap:8px;height:20px;color:var(--text-dim);font-size:10px;font-weight:600}
.e6-list{flex:1 1 auto;min-height:0;overflow:auto;padding:2px;border:1px solid var(--border-dim);border-radius:5px;background:var(--bg-deep)}
.e6-list:focus-visible{outline:none;border-color:var(--accent)}
.e6-group-head{position:sticky;top:-2px;display:flex;align-items:center;height:20px;padding:0 8px;background:var(--bg-deep);
  color:var(--text-dim);font-size:10px;font-weight:600}
.e6-row{position:relative;display:flex;align-items:center;gap:8px;width:100%;height:24px;padding:0 8px;box-sizing:border-box;border:0;
  border-radius:3px;background:transparent;color:var(--text-muted);font-size:11px;text-align:left;cursor:pointer}
.e6-row:hover{background:var(--bg-hover)}
.e6-row.selected{background:rgba(124,106,239,0.22);color:var(--text-primary);box-shadow:inset 2px 0 0 var(--accent-glow)}
.e6-row.matched .e6-row-name{color:var(--text-primary)}
.e6-row.matched .e6-row-name::after{content:'';display:inline-block;width:5px;height:5px;margin-left:6px;border-radius:50%;
  background:#7fd18f;vertical-align:middle}
.e6-row-name{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.e6-row-num,.e6-row .e6-star{flex:0 0 auto;font-family:var(--font-mono);font-size:10px;font-variant-numeric:tabular-nums}
.e6-row-num{color:var(--text-dim)}

/* 태그 줄: 영문 | 게시물 수 | 한글 */
.e6-row.e6-tag{display:grid;grid-template-columns:minmax(0,1.2fr) 56px minmax(0,1fr);align-items:center}
.e6-panel.no-ko .e6-row.e6-tag{grid-template-columns:minmax(0,1fr) 56px auto}
.e6-tag-en{min-width:0;overflow:hidden;font-family:var(--font-mono);text-overflow:ellipsis;white-space:nowrap}
.e6-tag-num{color:var(--text-dim);font-family:var(--font-mono);font-size:10px;font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
.e6-tag-num .e6-star{margin-right:3px}
.e6-tag-ko{min-width:0;display:flex;align-items:center;justify-content:flex-end;gap:4px}
.e6-tag-ko-text{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.e6-tag.body-only .e6-tag-en{color:var(--text-dim)}
.e6-tag.in-auto{box-shadow:inset 2px 0 0 rgba(127,209,143,0.4)}
.e6-tag.in-sel{box-shadow:inset 2px 0 0 #7fd18f}
.e6-tag.in-sel .e6-tag-num::before{content:'✓';margin-right:3px;color:#9ddfa8}
.e6-tag-add{position:absolute;top:2px;right:2px;bottom:2px;display:none;align-items:center;justify-content:center;width:22px;padding:0;
  border:1px solid var(--border-dim);border-radius:3px;background:var(--bg-surface);color:var(--text-primary);font-size:13px;line-height:1;cursor:pointer}
.e6-tag-add::before{content:'+'}
.e6-tag.in-sel .e6-tag-add::before{content:'−'}
.e6-tag:hover .e6-tag-add{display:inline-flex}
.e6-tag-add:hover{border-color:#7fd18f;color:#9ddfa8}
.e6-tag.in-sel .e6-tag-add:hover{border-color:#ff8a8a;color:#ff8a8a}
.e6-pager{flex:0 0 auto;display:flex;align-items:center;justify-content:space-between;gap:8px;padding-top:4px}

/* 일치 이유 칩: 초록 = 이름 · 한국어에서 맞음, 보라 = 이름이 통째로 같음, 회색 = 본문에서만, 점선 = 띄어쓰기를 빼고 맞음 */
.e6-match{flex:0 0 auto;padding:0 4px;border:1px solid rgba(144,238,144,0.38);border-radius:3px;background:rgba(144,238,144,0.07);
  color:#b9e3b9;font-size:10px;line-height:14px;white-space:nowrap}
.e6-match.exact{border-color:rgba(157,139,255,0.6);background:rgba(157,139,255,0.14);color:#d2c9ff}
.e6-match.body{border-color:rgba(170,170,170,0.32);background:transparent;color:#a8a8a8}
.e6-match.compact{border-style:dashed}
.e6-match-line{display:inline-flex;flex-wrap:wrap;gap:4px;margin-left:auto}

/* 선택한 태그(상세) */
.e6-detail{flex:1 1 auto;min-height:0;display:flex;flex-direction:column;border:1px solid var(--border-dim);border-radius:5px;background:var(--bg-deep)}
.e6-detail-empty{margin:auto}
.e6-detail-head{flex:0 0 auto;display:flex;align-items:baseline;gap:8px;padding:8px 12px 0}
.e6-detail-en{color:var(--text-primary);font-family:var(--font-mono);font-size:14px;font-weight:700;overflow-wrap:anywhere}
.e6-detail-ko{color:var(--text-primary);font-size:12px;overflow-wrap:anywhere}
.e6-detail-num{flex:0 0 auto;margin-left:auto;color:var(--text-dim);font-family:var(--font-mono);font-size:10px}
.e6-detail-acts{flex:0 0 auto;display:flex;align-items:center;gap:4px;padding:8px 12px}
.e6-primary{height:24px;margin-right:4px;padding:0 12px;border:1px solid var(--accent);border-radius:4px;background:var(--accent);color:#fff;
  font-size:11px;font-weight:600;white-space:nowrap;cursor:pointer}
.e6-primary:hover{filter:brightness(1.12)}
.e6-primary.on{border-color:rgba(127,209,143,0.6);background:transparent;color:#9ddfa8}
.e6-icon{display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;padding:0;border:0;border-radius:4px;
  background:transparent;color:var(--text-dim);font-size:13px;line-height:1;cursor:pointer}
.e6-icon:hover{background:var(--bg-hover);color:var(--text-primary)}
.e6-icon.star.on{color:#e8c76a}
.e6-icon.hide:hover{color:#ff8a8a}
.e6-detail-body{flex:1 1 auto;min-height:0;overflow:auto;padding:0 12px 12px}
.e6-desc{margin:0;color:var(--text-primary);font-size:11px;line-height:1.6;white-space:pre-wrap;overflow-wrap:anywhere}
.e6-desc.en{margin-top:4px;color:var(--text-muted)}
.e6-desc.clamp{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:6;line-clamp:6;overflow:hidden}
.e6-sec{margin-top:12px}
.e6-sec-head{margin-bottom:4px;color:var(--text-dim);font-size:10px;font-weight:600}
.e6-rel-row{display:flex;align-items:flex-start;gap:8px;margin-top:4px}
.e6-rel-label{flex:0 0 26px;padding-top:3px;color:var(--text-dim);font-size:10px;cursor:help}
.e6-chips{display:flex;flex-wrap:wrap;align-items:center;gap:4px;min-width:0}
.e6-chip{position:relative;display:inline-flex;align-items:center;height:20px;border:1px solid var(--border-dim);border-radius:4px;overflow:hidden}
.e6-chip.in-sel{border-color:rgba(127,209,143,0.5)}
.e6-chip-name{height:100%;padding:0 6px;border:0;background:transparent;color:var(--text-muted);font-family:var(--font-mono);font-size:10px;cursor:pointer}
.e6-chip-name:hover{background:var(--bg-hover);color:var(--text-primary)}
.e6-chip-name small{color:var(--text-dim);font-size:10px;font-variant-numeric:tabular-nums}
.e6-chip.in-sel .e6-chip-name::after{content:' ✓';color:#9ddfa8}
.e6-chip-add{position:absolute;top:0;right:0;bottom:0;display:none;width:20px;padding:0;border:0;border-left:1px solid var(--border-dim);
  background:var(--bg-surface);color:#9ddfa8;font-size:13px;line-height:1;cursor:pointer}
.e6-chip:hover .e6-chip-add{display:block}
.e6-more{height:20px;padding:0 4px;border:0;background:transparent;color:var(--accent-glow);font-size:10px;white-space:nowrap;cursor:pointer}
.e6-more.is-static{display:inline-flex;align-items:center;color:var(--text-dim);cursor:default}
.e6-alias{color:var(--text-dim);font-family:var(--font-mono);font-size:10px;line-height:20px}
.e6-fold{margin-top:12px}
.e6-fold > summary{color:var(--text-dim);font-size:10px;cursor:pointer;user-select:none}
.e6-fold > summary:hover{color:var(--text-primary)}
.e6-quote{margin:4px 0 0;padding:4px 8px;border-left:2px solid var(--border-dim);color:var(--text-muted);font:inherit;font-size:10px;line-height:1.5;
  white-space:pre-wrap;overflow-wrap:anywhere}
.e6-cross{margin-top:8px;color:var(--text-muted);font-size:10px;overflow-wrap:anywhere}
.e6-cross-head{margin-top:12px}

/* 프롬프트 조립 트레이 */
.e6-tray{min-width:0;display:flex;flex-direction:column;gap:8px;padding:8px 12px;border:1px solid var(--border-dim);border-radius:5px;background:var(--bg-deep)}
.e6-tray:empty{display:none}
.e6-tray-head{display:flex;align-items:center;gap:8px;min-width:0}
.e6-tray-title{color:var(--text-primary);font-size:12px;font-weight:600;white-space:nowrap}
.e6-switch{flex:0 0 auto;display:inline-flex;align-items:center;gap:6px;height:24px;padding:0 10px 0 8px;border:1px solid var(--border-dim);border-radius:12px;
  background:transparent;color:var(--text-dim);font-size:11px;white-space:nowrap;cursor:pointer}
.e6-switch::before{content:'';width:8px;height:8px;border-radius:50%;background:var(--text-dim)}
.e6-switch.on{border-color:rgba(127,209,143,0.6);color:#9ddfa8}
.e6-switch.on::before{background:#7fd18f}
.e6-stepper{flex:0 0 auto;display:inline-flex;align-items:center;height:24px;border:1px solid var(--border-dim);border-radius:4px;overflow:hidden}
.e6-stepper.is-off{opacity:0.45}
.e6-stepper button{width:20px;height:100%;padding:0;border:0;background:transparent;color:var(--text-muted);font-size:12px;cursor:pointer}
.e6-stepper button:hover{background:var(--bg-hover);color:var(--text-primary)}
.e6-stepper b{min-width:18px;color:var(--text-primary);font-family:var(--font-mono);font-size:11px;font-weight:400;text-align:center}
.e6-tray-chips{max-height:52px;overflow:auto}
.e6-hint{color:var(--text-dim);font-size:11px;line-height:24px}
.e6-sel,.e6-auto{display:inline-flex;align-items:center;height:24px;border:1px solid rgba(127,209,143,0.45);border-radius:4px;overflow:hidden}
.e6-sel{cursor:grab}
.e6-sel.dragging{opacity:0.45}
.e6-sel.up{border-color:rgba(232,180,106,0.6)}
.e6-sel.down{border-color:rgba(110,170,230,0.6)}
.e6-auto{border-style:dashed;border-color:var(--border-dim)}
.e6-sel button,.e6-auto button{display:inline-flex;align-items:center;height:100%;padding:0 4px;border:0;background:transparent;color:var(--text-dim);font-size:12px;cursor:pointer}
.e6-sel button:hover,.e6-auto button:hover{background:var(--bg-hover);color:var(--text-primary)}
.e6-sel .e6-sel-name,.e6-auto .e6-sel-name{max-width:180px;padding:0 4px 0 8px;overflow:hidden;font-family:var(--font-mono);font-size:11px;
  text-overflow:ellipsis;white-space:nowrap}
.e6-sel .e6-sel-name{color:var(--text-primary)}
.e6-auto .e6-sel-name{color:var(--text-muted)}
.e6-auto.species .e6-sel-name::after{content:' · 종';color:var(--text-dim);font-family:var(--font-display);font-size:10px}
.e6-sel-weight{width:36px;height:100%;padding:0;border:0;background:rgba(255,255,255,0.05);color:var(--text-primary);font-family:var(--font-mono);
  font-size:11px;text-align:center;-moz-appearance:textfield;appearance:textfield}
.e6-sel-weight::-webkit-inner-spin-button,.e6-sel-weight::-webkit-outer-spin-button{-webkit-appearance:none;margin:0}
.e6-sel.up .e6-sel-weight{color:#f0c987}
.e6-sel.down .e6-sel-weight{color:#9cc8f0}
.e6-sel .e6-sel-x:hover,.e6-auto .e6-sel-x:hover{color:#ff8a8a}
.e6-auto .e6-auto-pin:hover{color:#9ddfa8}
.e6-chip-sep{align-self:stretch;width:1px;margin:2px 4px;background:var(--border-dim)}
.e6-suggest{display:flex;align-items:flex-start;gap:8px;max-height:44px;overflow:auto}
.e6-out{display:flex;align-items:flex-end;gap:8px;min-width:0}
.e6-out-main{flex:1 1 auto;min-width:0;display:flex;flex-direction:column;gap:4px}
.e6-out .e6-template{width:100%;height:28px;min-height:28px;max-height:96px;padding:4px 8px;box-sizing:border-box;font-size:11px;line-height:1.6;resize:vertical}
.e6-out .e6-template.is-collapsed{display:none}
.e6-preview{min-height:28px;max-height:46px;overflow:auto;padding:4px 8px;box-sizing:border-box;border:1px dashed var(--border-dim);border-radius:5px;
  color:var(--text-primary);font-family:var(--font-mono);font-size:11px;line-height:1.7;overflow-wrap:anywhere}
.e6-preview.is-empty{display:none}
.e6-pv-auto{color:var(--text-muted);text-decoration:underline dotted;text-underline-offset:3px}
.e6-pv-template,.e6-pv-sep,.e6-pv-tail{color:var(--text-dim)}
.e6-pv-tail{font-family:var(--font-display);font-size:10px}
.e6-pv-error{color:#ff8a8a;font-family:var(--font-display)}
.e6-out .e6-template-toggle{align-self:center}
.e6-go{flex:0 0 auto;height:28px;padding:0 18px;border:0;border-radius:5px;background:var(--success,#5cb87a);color:#fff;font-size:12px;font-weight:700;
  white-space:nowrap;cursor:pointer}
.e6-go:hover{filter:brightness(1.1)}

/* 그릇이 좁으면(창 폭 · 떼어 낸 창 폭 기준) 한 줄로 쌓고 패널 안을 굴린다. */
@container e6 (max-width: 760px){
  .e6-panel{display:flex;flex-direction:column;overflow:auto}
  .e6-toolbar{flex-wrap:wrap}
  .e6-main{display:flex;flex-direction:column;flex:0 0 auto}
  .e6-col{flex:0 0 auto}
  .e6-list{flex:0 0 auto;max-height:200px}
  .e6-detail{flex:0 0 auto}
  .e6-detail-body{max-height:320px}
  .e6-tray{flex:0 0 auto}
  .e6-tray-head{flex-wrap:wrap}
}
`;

function ensureStyle(doc) {
  // 시험용 가짜 document(head · createElement 없음)에서도 패널은 살아야 한다.
  if (!doc || !doc.head || typeof doc.createElement !== 'function' || doc.getElementById(STYLE_ID)) return;
  const style = doc.createElement('style');
  style.id = STYLE_ID;
  style.textContent = PANEL_CSS;
  doc.head.appendChild(style);
}
