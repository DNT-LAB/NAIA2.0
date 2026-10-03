export function createE621EventPanel({
  document,
  escHtml,
  setModuleParam,
  bindTagAssist,
  showToast,
}) {
  const moduleBody = document.getElementById('modulePopupBody');
  let lastState = null;
  let lastRenderedStructureSignature = '';
  let deferredFocusedRenderState = null;
  let deferredFocusTarget = null;

  function attr(value) {
    return escHtml(String(value ?? ''));
  }

  function selectedTagName() {
    return lastState && lastState.selected ? lastState.selected.tag : '';
  }

  function renderCategoryButton(category) {
    const classes = [
      'e621-chip',
      category.selected ? 'selected' : '',
      category.matched ? 'matched' : '',
      category.starred_count > 0 ? 'has-starred' : '',
    ].filter(Boolean).join(' ');
    const subtitle = `${category.section} · ${category.tag_count}`;
    return `<button class="${classes}" data-category="${attr(category.name)}" onclick="e621SelectCategory(this)">
      <span>${escHtml(category.name.replace(/_/g, ' '))}</span>
      <small>${escHtml(subtitle)}${category.starred_count ? ` · *${category.starred_count}` : ''}</small>
    </button>`;
  }

  function renderFolderButton(folder) {
    return `<button class="e621-list-item${folder.selected ? ' selected' : ''}" data-folder="${attr(folder.name)}" onclick="e621SelectFolder(this)">
      <span>${escHtml(folder.display)}</span>
      <small>${folder.tag_count}</small>
    </button>`;
  }

  function renderTagButton(tag) {
    const selected = lastState && lastState.selected && lastState.selected.tag === tag.tag;
    const classes = [
      'e621-list-item',
      'e621-tag-item',
      selected ? 'selected' : '',
      tag.starred ? 'starred' : '',
      tag.matched_in_wiki ? 'wiki-match' : '',
    ].filter(Boolean).join(' ');
    const meta = [
      tag.count_label,
      tag.starred ? 'starred' : '',
      tag.matched_in_wiki ? '본문 일치' : '',
      tag.matched_in_korean ? '한국어 일치' : '',
    ].filter(Boolean).join(' · ');
    const coverage = [
      tag.has_body ? '본문' : '',
      tag.has_korean_description ? '한국어 설명' : '',
      tag.has_korean_search && !tag.has_korean_description ? '한글 검색어' : '',
    ].filter(Boolean).join(' · ') || (tag.review_status === 'metadata_unavailable' ? '설명 확인 불가' : '설명 없음');
    const koreanLabel = !lastState?.disable_translation && tag.kor
      ? `<span class="e621-tag-korean">${escHtml(tag.kor)}</span>` : '';
    return `<button class="${classes}" data-tag="${attr(tag.tag)}" onclick="e621SelectTag(this)">
      <span class="e621-tag-name"><span>${escHtml(tag.display)}</span>${koreanLabel}</span>
      <small class="e621-tag-status"><span>${escHtml(meta)}</span><span>${escHtml(coverage)}</span></small>
    </button>`;
  }

  function renderResearchDetails(state) {
    if (!state.selected) return '<div class="mod-empty">태그를 선택하면 설명과 검토 상태를 확인할 수 있습니다.</div>';
    const research = state.selected.research || {};
    const status = research.review_label || state.selected.review_label || '미검토';
    const source = research.description_source ? `<small>${escHtml(research.description_source)}</small>` : '';
    const missingKorean = research.review_status === 'metadata_unavailable'
      ? '한국어 설명 사전을 확인할 수 없습니다.' : '등록된 한국어 설명이 없습니다.';
    const descriptionEvidence = (research.description_evidence || []).map(item => `
      <small>${escHtml([item.site, item.retrieved_at?.slice(0, 10)].filter(Boolean).join(' · '))}</small>
      <pre class="e621-research-text">${escHtml(item.quote || '')}</pre>`).join('');
    const searchEvidence = (research.search_evidence || []).map(item => `
      <small>${escHtml(item.site || 'e621')}</small>
      <pre class="e621-research-text">${escHtml(item.quote || '')}</pre>`).join('');
    const korean = state.disable_translation ? '' : `
      <section class="e621-research-section">
        <div class="mod-section-label">한국어 설명</div>
        ${research.korean_label ? `<strong>${escHtml(research.korean_label)}</strong>` : ''}
        <pre class="e621-research-text">${escHtml(research.korean_description || missingKorean)}</pre>
        ${research.korean_keywords ? `<small>검색어: ${escHtml(research.korean_keywords)}</small>` : ''}
        ${research.search_review_status === 'reviewed_search_terms' ? '<small>한국어 검색어 · 직접 정의 대조 완료</small>' : ''}
        ${research.search_source_label ? `<small>${escHtml(research.search_source_label)}</small>` : ''}
        ${research.search_review_status === 'stale_evidence' ? '<small>한국어 검색어 · 근거 변경으로 적용 보류</small>' : ''}
        ${descriptionEvidence ? `<details><summary>설명 근거 발췌</summary>${descriptionEvidence}</details>` : ''}
        ${searchEvidence ? `<details><summary>검색어 근거 발췌</summary>${searchEvidence}</details>` : ''}
      </section>`;
    const body = state.wiki?.body ?? state.wiki?.text ?? '';
    const crosslinks = (research.cross_site_links || []).map(link => `
      <div class="e621-cross-site-card">
        <strong>${escHtml(`${link.site || 'danbooru'} · ${link.tag || ''}`)}</strong>
        <small>${escHtml([link.relation_label || link.relation, link.status_label || link.status].filter(Boolean).join(' · '))}</small>
        ${link.reason ? `<p>${escHtml(link.reason)}</p>` : ''}
        ${(link.sources || []).length ? `<details><summary>대조한 정의 발췌</summary>${link.sources.map(item => `
          <small>${escHtml(`${item.site || ''} · ${item.exact_tag || ''}`)}</small>
          <pre class="e621-research-text">${escHtml(item.quote || '')}</pre>`).join('')}</details>` : ''}
      </div>`).join('');
    return `
      <div class="e621-research-meta"><span>${escHtml(status)}</span>${source}</div>
      ${korean}
      <section class="e621-research-section">
        <div class="mod-section-label">저장된 위키 본문</div>
        <pre class="e621-research-text">${escHtml(body || '저장된 본문이 없습니다.')}</pre>
      </section>
      <section class="e621-research-section">
        <div class="mod-section-label">다른 사이트의 개념 연결</div>
        ${crosslinks || '<div class="mod-empty">등록된 연결이 없습니다.</div>'}
        ${crosslinks ? '<div class="e621-muted">연결 관계와 검토 상태를 참고용으로 표시합니다.</div>' : ''}
      </section>`;
  }

  function renderHiddenList(state) {
    if (!state.hidden_items || !state.hidden_items.length) {
      return '<div class="mod-empty">숨긴 태그 없음</div>';
    }
    return state.hidden_items.map(tag => `<button class="e621-hidden-item" data-tag="${attr(tag)}" onclick="e621RestoreHidden(this)">
      <span>${escHtml(tag.replace(/_/g, ' '))}</span>
      <small>복원</small>
    </button>`).join('');
  }

  function bindRenderedInputs() {
    const testbench = document.getElementById('e621Testbench');
    if (testbench && bindTagAssist) {
      bindTagAssist(testbench);
    }
  }

  function focusedE621Testbench() {
    const active = document.activeElement;
    if (!active || !moduleBody || !moduleBody.contains(active)) return null;
    if (active.tagName !== 'TEXTAREA' || active.id !== 'e621Testbench') return null;
    return active;
  }

  function e621StructureSignature(state) {
    if (!state || !state.data_loaded) return JSON.stringify({loaded: false, path: state?.data_path || ''});
    // Everything EXCEPT the testbench text (echoed per-keystroke by onTestbenchInput)
    // so a server echo for a local testbench edit keeps the same signature and never
    // replaces the focused #e621Testbench textarea.
    const rest = {...state};
    delete rest.testbench;
    return JSON.stringify(rest);
  }

  function clearDeferredE621Render() {
    if (deferredFocusTarget) deferredFocusTarget.removeEventListener('blur', flushDeferredE621Render);
    deferredFocusTarget = null;
    deferredFocusedRenderState = null;
  }

  function queueDeferredE621Render(textarea, state) {
    deferredFocusedRenderState = state;
    if (deferredFocusTarget === textarea) return;
    if (deferredFocusTarget) deferredFocusTarget.removeEventListener('blur', flushDeferredE621Render);
    deferredFocusTarget = textarea;
    textarea.addEventListener('blur', flushDeferredE621Render, {once: true});
  }

  function flushDeferredE621Render() {
    const pendingState = deferredFocusedRenderState;
    deferredFocusTarget = null;
    deferredFocusedRenderState = null;
    if (!pendingState) return;
    globalThis.setTimeout(() => { if (!focusedE621Testbench()) render(pendingState); }, 0);
  }

  function render(state) {
    // A server echo for a local testbench edit must not rebuild moduleBody.innerHTML
    // while the testbench is focused — replacing it drops focus and collapses tag
    // autocomplete (same regression fixed for Character/Img2Img: 38d3898 / c9edf4b).
    const structureSignature = e621StructureSignature(state);
    const focusedTextarea = focusedE621Testbench();
    if (focusedTextarea && lastRenderedStructureSignature === structureSignature) {
      lastState = state;
      queueDeferredE621Render(focusedTextarea, state);
      return;
    }
    clearDeferredE621Render();
    lastRenderedStructureSignature = structureSignature;
    lastState = state;
    if (!state.data_loaded) {
      moduleBody.innerHTML = `
        <div class="mod-section">
          <div class="mod-section-label">E621 Event Module</div>
          <div class="mod-empty">E621 데이터가 로드되지 않았습니다.</div>
          <div class="mod-status">${escHtml(state.data_path || '')}</div>
        </div>
      `;
      return;
    }

    const categories = state.categories || [];
    const general = categories.filter(item => item.section === 'General').map(renderCategoryButton).join('');
    const species = categories.filter(item => item.section === 'Species').map(renderCategoryButton).join('');
    const folders = state.folders && state.folders.length
      ? state.folders.map(renderFolderButton).join('')
      : '<div class="mod-empty">카테고리를 선택하세요</div>';
    const tags = state.tags && state.tags.length
      ? state.tags.map(renderTagButton).join('')
      : '<div class="mod-empty">태그 없음</div>';
    const selected = state.selected;
    const selectedName = selected ? selected.display : '선택된 태그 없음';
    const selectedMeta = selected
      ? `${selected.count_label}${selected.starred ? ' · starred' : ''}`
      : '';
    const offset = Number(state.tag_offset) || 0;
    const pageSize = Number(state.tag_page_size || state.tag_limit) || 300;
    const total = Number(state.tag_total) || 0;
    const shown = state.tags?.length || 0;
    const truncated = `<span class="e621-muted">${total ? `${offset + 1}–${offset + shown} / ${total}` : '0'} tags</span>`;
    const pagination = `
      <div class="e621-pagination">
        <button class="mod-btn-sm" ${state.has_previous ? '' : 'disabled'} onclick="setModuleParam('e621_event','tag_offset','${Math.max(0, offset - pageSize)}')" aria-label="이전 태그 페이지">이전</button>
        <span class="e621-muted">${total ? Math.floor(offset / pageSize) + 1 : 0} / ${Math.ceil(total / pageSize)}</span>
        <button class="mod-btn-sm" ${state.has_next ? '' : 'disabled'} onclick="setModuleParam('e621_event','tag_offset','${offset + pageSize}')" aria-label="다음 태그 페이지">다음</button>
      </div>`;
    const contentFilter = state.content_filter || 'all';
    const summary = state.research_summary || {};
    const noDescriptionLabel = summary.metadata_available === false ? '설명 미확인' : '설명 없음';
    const filterOptions = [['all', '전체 설명 상태'], ['with_body', '저장된 본문 있음'], ['with_korean', '한국어 설명 있음'], ['with_korean_search', '한글 검색어 있음'], ['without_description', noDescriptionLabel]]
      .map(([value, label]) => `<option value="${value}" ${contentFilter === value ? 'selected' : ''}>${label}</option>`).join('');
    const summaryText = Object.hasOwn(summary, 'total')
      ? `고유 태그 ${summary.total} · 저장된 본문 ${summary.with_body || 0} · 한글 검색 ${summary.with_korean_search || 0} · 한국어 설명 ${summary.with_korean_description || 0} · ${noDescriptionLabel} ${summary.without_description || 0}` : '';
    const translationControl = state.translation_control_visible === false ? '' : `
          <label class="mod-check-row">
            <input type="checkbox" ${state.disable_translation ? 'checked' : ''} oninput="setModuleParam('e621_event','disable_translation',String(this.checked))">
            <span>한국어 설명 숨김</span>
          </label>`;
    const wikiSearchControl = state.wiki_search_control_visible === false ? '' : `
          <label class="mod-check-row">
            <input type="checkbox" ${state.disable_wiki_search ? 'checked' : ''} oninput="setModuleParam('e621_event','disable_wiki_search',String(this.checked))">
            <span>저장된 본문 검색 제외</span>
          </label>`;
    const promptTestbench = state.prompt_testbench_visible === false ? '' : `
            <div class="mod-section-label">e621 프롬프트 테스트벤치</div>
            <textarea class="mod-textarea mod-textarea-lg" id="e621Testbench" oninput="e621OnTestbenchInput(this)">${escHtml(state.testbench || '')}</textarea>
            <button class="mod-action-btn mod-start" onclick="e621Generate()">생성</button>`;

    moduleBody.innerHTML = `
      <div class="e621-panel">
        <div class="e621-toolbar">
          <input class="mod-input" id="e621SearchInput" type="text" value="${attr(state.search_text || '')}" placeholder="영문 태그 · 한국어 이름과 설명 검색" onkeydown="if(event.key==='Enter')e621Search()">
          <button class="mod-btn-sm" onclick="e621Search()">검색</button>
          <button class="mod-btn-sm" onclick="e621Reset()">초기화</button>
        </div>

        <div class="e621-toolbar compact">
          <button class="mod-btn-sm${state.view_mode === 'default' ? ' active' : ''}" onclick="e621SetViewMode('default')">기본</button>
          <button class="mod-btn-sm${state.view_mode === 'starred' ? ' active' : ''}" onclick="e621SetViewMode('starred')">즐겨찾기</button>
          <label class="e621-description-filter">설명 상태
            <select class="mod-input" id="e621ContentFilter" data-native-select aria-label="설명 상태" onchange="setModuleParam('e621_event','content_filter',this.value)">${filterOptions}</select>
          </label>
${translationControl}
${wikiSearchControl}
          <div class="e621-research-summary">${escHtml(summaryText)}${summary.warning ? `<span>${escHtml(summary.warning)}</span>` : ''}</div>
        </div>

        <div class="e621-layout">
          <section class="e621-column categories">
            <div class="mod-section-label">General</div>
            <div class="e621-chip-grid">${general}</div>
            <div class="mod-section-label">Species</div>
            <div class="e621-chip-grid">${species}</div>
          </section>

          <section class="e621-column">
            <div class="mod-section-label">Folders</div>
            <div class="e621-scroll-list">${folders}</div>
          </section>

          <section class="e621-column">
            <div class="mod-section-label">Tags ${truncated}</div>
            <div class="e621-scroll-list">${tags}</div>
            ${pagination}
          </section>
        </div>

        <div class="e621-detail-grid">
          <section class="e621-detail-card">
            <div class="e621-selected-head">
              <div>
                <div class="mod-section-label">선택된 태그</div>
                <strong>${escHtml(selectedName)}</strong>
                <small>${escHtml(selectedMeta)}</small>
              </div>
              <div class="e621-selected-actions">
                <button class="mod-btn-sm" onclick="e621ToggleStar()" ${selected ? '' : 'disabled'}>${selected && selected.starred ? '즐겨찾기 해제' : '즐겨찾기'}</button>
                <button class="mod-btn-sm danger" onclick="e621HideSelected()" ${selected ? '' : 'disabled'}>숨김</button>
              </div>
            </div>
            <div class="e621-research-details">${renderResearchDetails(state)}</div>
          </section>

          <section class="e621-detail-card">
${promptTestbench}

            <div class="e621-hidden-head">
              <div class="mod-section-label">숨긴 태그</div>
              <small>${state.hidden_total || 0}</small>
            </div>
            <div class="e621-hidden-list">${renderHiddenList(state)}</div>
          </section>
        </div>
      </div>
    `;
    bindRenderedInputs();
  }

  function search() {
    const input = document.getElementById('e621SearchInput');
    setModuleParam('e621_event', 'search', input ? input.value : '');
  }

  function reset() {
    setModuleParam('e621_event', 'reset', '1');
  }

  function setViewMode(value) {
    setModuleParam('e621_event', 'view_mode', value);
  }

  function selectCategory(element) {
    setModuleParam('e621_event', 'category', element.dataset.category || '');
  }

  function selectFolder(element) {
    setModuleParam('e621_event', 'level2', element.dataset.folder || '');
  }

  function selectTag(element) {
    setModuleParam('e621_event', 'selected_tag', element.dataset.tag || '');
  }

  function toggleStar() {
    const tag = selectedTagName();
    if (!tag) {
      if (showToast) showToast('Select a tag first', 'error');
      return;
    }
    setModuleParam('e621_event', 'toggle_star', tag);
  }

  function hideSelected() {
    const tag = selectedTagName();
    if (!tag) {
      if (showToast) showToast('Select a tag first', 'error');
      return;
    }
    setModuleParam('e621_event', 'hide', tag);
  }

  function restoreHidden(element) {
    setModuleParam('e621_event', 'restore', element.dataset.tag || '');
  }

  function onTestbenchInput(element) {
    setModuleParam('e621_event', 'testbench', element.value);
  }

  function generate() {
    const testbench = document.getElementById('e621Testbench');
    const value = testbench ? testbench.value : '';
    setModuleParam('e621_event', 'generate', value);
  }

  return {
    render,
    search,
    reset,
    setViewMode,
    selectCategory,
    selectFolder,
    selectTag,
    toggleStar,
    hideSelected,
    restoreHidden,
    onTestbenchInput,
    generate,
  };
}
