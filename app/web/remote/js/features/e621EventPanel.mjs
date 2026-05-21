export function createE621EventPanel({
  document,
  escHtml,
  setModuleParam,
  bindTagAssist,
  showToast,
}) {
  const moduleBody = document.getElementById('modulePopupBody');
  let lastState = null;

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
      tag.matched_in_wiki ? 'wiki' : '',
    ].filter(Boolean).join(' · ');
    return `<button class="${classes}" data-tag="${attr(tag.tag)}" onclick="e621SelectTag(this)">
      <span>${escHtml(tag.display)}</span>
      <small>${escHtml(meta)}</small>
    </button>`;
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

  function render(state) {
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
    const truncated = state.tag_total > state.tag_limit
      ? `<span class="e621-muted">Showing ${state.tag_limit} / ${state.tag_total}</span>`
      : `<span class="e621-muted">${state.tag_total || 0} tags</span>`;
    const wikiText = state.wiki && state.wiki.text ? state.wiki.text : '';
    const translationControl = state.translation_control_visible === false ? '' : `
          <label class="mod-check-row">
            <input type="checkbox" ${state.disable_translation ? 'checked' : ''} oninput="setModuleParam('e621_event','disable_translation',String(this.checked))">
            <span>자동 번역을 사용하지 않습니다</span>
          </label>`;
    const wikiSearchControl = state.wiki_search_control_visible === false ? '' : `
          <label class="mod-check-row">
            <input type="checkbox" ${state.disable_wiki_search ? 'checked' : ''} oninput="setModuleParam('e621_event','disable_wiki_search',String(this.checked))">
            <span>원문 검색을 사용하지 않습니다</span>
          </label>`;
    const promptTestbench = state.prompt_testbench_visible === false ? '' : `
            <div class="mod-section-label">e621 프롬프트 테스트벤치</div>
            <textarea class="mod-textarea mod-textarea-lg" id="e621Testbench" oninput="e621OnTestbenchInput(this)">${escHtml(state.testbench || '')}</textarea>
            <button class="mod-action-btn mod-start" onclick="e621Generate()">생성</button>`;

    moduleBody.innerHTML = `
      <div class="e621-panel">
        <div class="e621-toolbar">
          <input class="mod-input" id="e621SearchInput" type="text" value="${attr(state.search_text || '')}" placeholder="태그 검색 - 꼭 정확한 단어로 검색하세요" onkeydown="if(event.key==='Enter')e621Search()">
          <button class="mod-btn-sm" onclick="e621Search()">검색</button>
          <button class="mod-btn-sm" onclick="e621Reset()">초기화</button>
        </div>

        <div class="e621-toolbar compact">
          <button class="mod-btn-sm${state.view_mode === 'default' ? ' active' : ''}" onclick="e621SetViewMode('default')">기본</button>
          <button class="mod-btn-sm${state.view_mode === 'starred' ? ' active' : ''}" onclick="e621SetViewMode('starred')">즐겨찾기</button>
${translationControl}
${wikiSearchControl}
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
            <pre class="e621-wiki">${escHtml(wikiText)}</pre>
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
