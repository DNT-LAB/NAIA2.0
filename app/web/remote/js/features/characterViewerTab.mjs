export function createCharacterViewerController({
  document,
  fetch,
  escHtml,
  showToast,
  negEdit,
  getGenerationMode = () => 'NAI',
}) {
  const groupSearchEl = document.getElementById('characterViewerGroupSearch');
  const groupListEl = document.getElementById('characterViewerGroupList');
  const searchEl = document.getElementById('characterViewerSearch');
  const listEl = document.getElementById('characterViewerList');
  const subtabEls = [...document.querySelectorAll('[data-character-viewer-tab]')];
  const paneEls = [...document.querySelectorAll('[data-character-viewer-pane]')];
  const summaryEl = document.getElementById('characterViewerSummary');
  const statusEl = document.getElementById('characterViewerStatus');
  const gridEl = document.getElementById('characterViewerGrid');
  const thumbFirstEl = document.getElementById('characterViewerThumbFirst');
  // 도감 즐겨찾기(사용자 요청 2026-09-03). ⚠️ 저장소는 백엔드 한 곳이라 캐릭터 모듈의
  // 검색 탭과 **같은 목록**이다 - 여기서 켠 별이 저쪽에도 그대로 보인다.
  const favOnlyEl = document.getElementById('characterViewerFavOnly');
  const prevBtn = document.getElementById('characterViewerPrevBtn');
  const nextBtn = document.getElementById('characterViewerNextBtn');
  const pageLabel = document.getElementById('characterViewerPageLabel');
  const gotoInput = document.getElementById('characterViewerGotoInput');
  const gotoBtn = document.getElementById('characterViewerGotoBtn');
  const selectedImage = document.getElementById('characterViewerSelectedImage');
  const selectedEmpty = document.getElementById('characterViewerSelectedEmpty');
  const selectedName = document.getElementById('characterViewerSelectedName');
  const selectedMeta = document.getElementById('characterViewerSelectedMeta');
  const resultPreviewEl = document.getElementById('characterViewerResultPreview');
  const resultTitleEl = document.getElementById('characterViewerResultTitle');
  const resultExpandBtn = document.getElementById('characterViewerResultExpand');
  const resultCloseBtn = document.getElementById('characterViewerResultClose');
  const resultImageEl = document.getElementById('characterViewerResultImage');
  const resultEmptyEl = document.getElementById('characterViewerResultEmpty');
  const variantEl = document.getElementById('characterViewerVariant');
  const tagSectionsEl = document.getElementById('characterViewerTagSections');
  const promptEl = document.getElementById('characterViewerPrompt');
  const prefixEl = document.getElementById('characterViewerPrefix');
  const postfixEl = document.getElementById('characterViewerPostfix');
  const autoCopyrightEl = document.getElementById('characterViewerAutoCopyright');
  const autoCharacteristicsEl = document.getElementById('characterViewerAutoCharacteristics');
  const hideNameEl = document.getElementById('characterViewerHideName');
  const noSaveEl = document.getElementById('characterViewerNoSave');
  const continuousGenEl = document.getElementById('characterViewerContinuous');
  const emptyOnlyEl = document.getElementById('characterViewerEmptyOnly');
  const cosplayEl = document.getElementById('characterViewerCosplay');
  const cosplayNameEl = document.getElementById('characterViewerCosplayName');
  const copyBtn = document.getElementById('characterViewerCopyBtn');
  const generateBtn = document.getElementById('characterViewerGenerateBtn');
  const deleteThumbBtn = document.getElementById('characterViewerDeleteThumbBtn');
  const rootEl = document.querySelector('.character-viewer-tab');

  const PAGE_SIZE = 9;
  const LIST_ITEM_HEIGHT = 30;
  const LIST_OVERSCAN = 8;
  let state = null;
  let groups = [];
  let allItems = [];
  let listRequestId = 0;
  let listRenderFrame = 0;
  let groupRequestId = 0;
  let detailRequestId = 0;
  let promptRequestId = 0;
  let saveTimer = null;
  let searchTimer = null;
  let groupSearchTimer = null;
  let wheelPageLocked = false;
  let loaded = false;
  let currentGroup = '__ALL__';
  let currentPage = 0;
  let totalPages = 1;
  let currentTotal = 0;
  let selected = null;
  let detail = null;
  let lastPromptPayload = null;
  let pendingResultRequestId = '';
  let pendingResultMeta = null;
  let resultBlobUrl = '';
  let resultPreviewOpen = false;
  let resultExpanded = false;
  let pendingResultTimer = null;
  let active = document.querySelector('[data-right-pane="characters"]')?.classList.contains('active') || false;
  let activeView = 'characters';
  let suppressResultCollapseClick = false;
  let suppressResultCollapseClickTimer = null;
  let contextMenuEl = null;
  let contextMenuTarget = null;
  let continuousTimer = null;
  let continuousScheduleToken = 0;
  let deletingThumb = false;

  const html = value => escHtml(String(value ?? ''));

  function isCompactViewport() {
    return Boolean(window.matchMedia?.('(max-width: 767px)').matches);
  }

  function syncViewState() {
    if (!rootEl) return;
    rootEl.dataset.characterViewerView = activeView;
  }

  function gridThumbnailUrl(url) {
    const raw = String(url || '');
    if (!raw) return '';
    try {
      const parsed = new URL(raw, window.location.origin);
      parsed.searchParams.set('size', 'grid');
      return `${parsed.pathname}${parsed.search}${parsed.hash}`;
    } catch {
      return `${raw}${raw.includes('?') ? '&' : '?'}size=grid`;
    }
  }

  function setStatus(message, tone = '') {
    if (!statusEl) return;
    statusEl.textContent = message || '';
    if (tone) statusEl.dataset.tone = tone;
    else delete statusEl.dataset.tone;
  }

  function setSummary(message) {
    if (summaryEl) summaryEl.textContent = message || 'Character data';
  }

  function renderSummary() {
    if (!state) return;
    setSummary(
      `${formatCount(state.character_count)} characters · ${formatCount(state.group_count)} groups`
      + ` · ${formatCount(state.thumbnail_count)} thumbnails`,
    );
  }

  function formatCount(value) {
    return Number(value || 0).toLocaleString();
  }

  function currentGenerationMode() {
    return String(getGenerationMode?.() || 'NAI').trim().toUpperCase();
  }

  function normalizeCharacterPromptForCopy(value) {
    const raw = String(value || '').trim();
    if (!raw) return '';
    const parts = raw.split(',').map(part => part.trim()).filter(Boolean);
    if (currentGenerationMode() === 'NAI') {
      const head = String(parts[0] || '').toLowerCase();
      return (head === 'girl' || head === '1girl') ? parts.join(', ') : `girl, ${parts.join(', ')}`;
    }
    while (parts.length && ['girl', '1girl'].includes(String(parts[0]).toLowerCase())) {
      parts.shift();
    }
    return parts.join(', ');
  }

  function currentOptions() {
    return {
      prefix: prefixEl?.value || '',
      postfix: postfixEl?.value || '',
      cosplay_enabled: Boolean(cosplayEl?.checked),
      cosplay_name: cosplayNameEl?.value || '',
      auto_copyright: Boolean(autoCopyrightEl?.checked),
      auto_characteristics: Boolean(autoCharacteristicsEl?.checked),
      hide_charname: Boolean(hideNameEl?.checked),
      no_save: Boolean(noSaveEl?.checked),
      thumb_first: Boolean(thumbFirstEl?.checked),
      empty_thumb_only: Boolean(emptyOnlyEl?.checked),
    };
  }

  function makeRequestId() {
    return `character-viewer-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  }

  async function getJson(url) {
    const response = await fetch(url, {cache: 'no-store'});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  }

  async function postJson(url, payload) {
    const response = await fetch(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload || {}),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  }

  function applyOptions(options = {}) {
    if (prefixEl && !prefixEl.dataset.seeded) {
      prefixEl.value = String(options.prefix || '');
      prefixEl.dataset.seeded = '1';
    }
    if (postfixEl && !postfixEl.dataset.seeded) {
      postfixEl.value = String(options.postfix || '');
      postfixEl.dataset.seeded = '1';
    }
    if (cosplayNameEl && !cosplayNameEl.dataset.seeded) {
      cosplayNameEl.value = String(options.cosplay_name || '');
      cosplayNameEl.dataset.seeded = '1';
    }
    if (cosplayEl) cosplayEl.checked = Boolean(options.cosplay_enabled);
    if (autoCopyrightEl) autoCopyrightEl.checked = Boolean(options.auto_copyright);
    if (autoCharacteristicsEl) autoCharacteristicsEl.checked = Boolean(options.auto_characteristics ?? true);
    if (hideNameEl) hideNameEl.checked = Boolean(options.hide_charname);
    if (noSaveEl) noSaveEl.checked = Boolean(options.no_save);
    if (thumbFirstEl) thumbFirstEl.checked = Boolean(options.thumb_first ?? true);
    if (emptyOnlyEl) emptyOnlyEl.checked = Boolean(options.empty_thumb_only ?? true);
  }

  function updatePager() {
    if (pageLabel) pageLabel.textContent = `${currentPage + 1} / ${totalPages}`;
    if (prevBtn) prevBtn.disabled = currentPage <= 0;
    if (nextBtn) nextBtn.disabled = currentPage >= totalPages - 1;
    if (gotoInput) {
      gotoInput.max = String(totalPages);
      gotoInput.value = String(currentPage + 1);
    }
  }

  function updateActionAvailability() {
    const enabled = Boolean(selected && detail);
    if (copyBtn) copyBtn.disabled = !enabled;
    if (generateBtn) generateBtn.disabled = !enabled || Boolean(pendingResultRequestId);
    if (deleteThumbBtn) deleteThumbBtn.disabled = deletingThumb || !currentThumbnailTarget();
    subtabEls.forEach(button => {
      if (button.dataset.characterViewerTab === 'detail') {
        button.disabled = !enabled;
      }
    });
  }

  function switchCharacterView(view) {
    const nextView = view === 'detail' && detail ? 'detail' : 'characters';
    activeView = nextView;
    syncViewState();
    subtabEls.forEach(button => {
      const isActive = button.dataset.characterViewerTab === nextView;
      button.classList.toggle('active', isActive);
      button.setAttribute('aria-selected', String(isActive));
    });
    paneEls.forEach(pane => {
      const isActive = pane.dataset.characterViewerPane === nextView;
      pane.classList.toggle('active', isActive);
      pane.hidden = !isActive;
    });
    if (nextView !== 'detail') setResultExpanded(false);
    applyResultPreviewVisibility();
  }

  function renderGroups() {
    if (!groupListEl) return;
    groupListEl.innerHTML = groups.map(group => {
      const activeClass = group.key === currentGroup ? ' active' : '';
      return `
        <button type="button" class="character-viewer-group-item${activeClass}" data-group="${html(group.key)}" title="${html(group.name)}">
          <span>${html(group.name)}</span>
          <b>${formatCount(group.count)}</b>
        </button>
      `;
    }).join('');
  }

  async function loadGroups() {
    const requestId = ++groupRequestId;
    const query = String(groupSearchEl?.value || '').trim();
    const data = await getJson(`/api/character-viewer/groups?query=${encodeURIComponent(query)}`);
    if (requestId !== groupRequestId) return;
    groups = data.items || [];
    renderGroups();
  }

  function thumbnailMarkup(item) {
    if (item.thumbnail_url) {
      return `<img src="${html(item.thumbnail_url)}" alt="${html(item.character)}" loading="lazy" decoding="async">`;
    }
    return `<span class="character-viewer-card-empty">No Thumb</span>`;
  }

  function listItemMarkup(item) {
    const activeClass = selected && selected.group === item.group && selected.character === item.character ? ' active' : '';
    const thumbClass = item.has_thumbnail ? ' has-thumb' : ' no-thumb';
    const index = Number(item.index || 0);
    return `
      <button type="button" class="character-viewer-list-item${activeClass}${thumbClass}" data-group="${html(item.group)}" data-character="${html(item.character)}" data-index="${index}" title="${html(item.character)} · ${html(item.group)} · #${index + 1}">
        <span>${html(item.character)}</span>
        <b>${formatCount(item.count)}</b>
      </button>
    `;
  }

  function renderListItems(items = allItems, options = {}) {
    if (!listEl) return;
    if (options.resetScroll) listEl.scrollTop = 0;
    const count = items.length;
    const viewportHeight = Math.max(LIST_ITEM_HEIGHT, listEl.clientHeight || 360);
    const scrollTop = Math.max(0, listEl.scrollTop || 0);
    const firstVisible = Math.floor(scrollTop / LIST_ITEM_HEIGHT);
    const visibleCount = Math.ceil(viewportHeight / LIST_ITEM_HEIGHT);
    const start = Math.max(0, firstVisible - LIST_OVERSCAN);
    const end = Math.min(count, firstVisible + visibleCount + LIST_OVERSCAN);
    const topHeight = start * LIST_ITEM_HEIGHT;
    const bottomHeight = Math.max(0, (count - end) * LIST_ITEM_HEIGHT);
    const rows = items.slice(start, end).map(listItemMarkup).join('');
    listEl.innerHTML = `
      <div class="character-viewer-list-spacer" style="height:${topHeight}px"></div>
      ${rows}
      <div class="character-viewer-list-spacer" style="height:${bottomHeight}px"></div>
    `;
  }

  function scheduleListRender() {
    if (listRenderFrame) return;
    listRenderFrame = requestAnimationFrame(() => {
      listRenderFrame = 0;
      renderListItems(allItems);
    });
  }

  function renderGrid(items) {
    if (!gridEl) return;
    gridEl.innerHTML = items.map(item => {
      const activeClass = selected && selected.group === item.group && selected.character === item.character ? ' active' : '';
      const thumbClass = item.has_thumbnail ? ' has-thumb' : ' no-thumb';
      const index = Number(item.index || 0);
      // 별은 카드 안에 있지만 **카드와 다른 일**을 한다. 카드가 이미 button 이라
      // button 을 겹쳐 넣을 수 없어 span 으로 두고, 클릭에서 카드보다 먼저 잡는다.
      const star = `<span class="character-viewer-card-star${item.favorite ? ' is-on' : ''}"
        role="button" tabindex="-1" data-favorite-toggle="1"
        data-fav-group="${html(item.group)}" data-fav-character="${html(item.character)}"
        title="${item.favorite ? '즐겨찾기에서 뺍니다' : '즐겨찾기에 넣습니다'}"
        >${item.favorite ? '★' : '☆'}</span>`;
      return `
        <button type="button" class="character-viewer-card${activeClass}${thumbClass}" data-group="${html(item.group)}" data-character="${html(item.character)}" data-index="${index}" title="${html(item.character)} · ${html(item.group)} · ${formatCount(item.count)}">
          <div class="character-viewer-card-image">
            ${thumbnailMarkup(item)}
            <span class="character-viewer-card-group">[${html(item.group)}]</span>
            ${star}
          </div>
          <div class="character-viewer-card-name">${html(item.character)}</div>
        </button>
      `;
    }).join('');
  }

  function scrollGrid(anchor = 'top') {
    if (!gridEl) return;
    if (anchor === 'bottom') gridEl.scrollTop = gridEl.scrollHeight;
    else gridEl.scrollTop = 0;
  }

  /**
   * 도감 즐겨찾기를 켜고 끈다. 저장소는 백엔드 한 곳이라 캐릭터 모듈 검색 탭과 같다.
   *
   * ⚠️ 응답으로 화면을 고친다 - 먼저 뒤집어 두면 거절당했을 때 별만 켜진 채 남는다.
   * ⚠️ [★ 즐겨찾기] 로 걸러 보는 중에 별을 끄면 그 카드는 빠져야 하므로 다시 부른다.
   *    아니면 손에 든 두 목록(`allItems` · 지금 페이지)만 고쳐 스크롤을 지킨다.
   */
  async function toggleFavorite(group, character) {
    if (!group || !character) return;
    const findIn = list => (Array.isArray(list) ? list : []).find(
      row => row.group === group && row.character === character);
    const known = findIn(allItems);
    const next = !(known ? known.favorite : false);
    try {
      const res = await fetch('/api/character-viewer/favorite', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({group, character, favorite: next}),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || 'Favorite failed');
      if (favOnlyEl?.checked && !data.favorite) {
        await loadPage(currentPage, {includeAll: true, skipAutoSelect: true});
        return;
      }
      if (known) known.favorite = !!data.favorite;
      const cards = gridEl ? gridEl.querySelectorAll('[data-favorite-toggle]') : [];
      cards.forEach(node => {
        if (node.dataset.favGroup !== group || node.dataset.favCharacter !== character) return;
        node.classList.toggle('is-on', !!data.favorite);
        node.textContent = data.favorite ? '★' : '☆';
        node.title = data.favorite ? '즐겨찾기에서 뺍니다' : '즐겨찾기에 넣습니다';
      });
      setStatus(`${formatCount(currentTotal)} characters · ★ ${formatCount(data.favorite_count || 0)}`, 'ok');
    } catch (error) {
      setStatus(String(error.message || error), 'error');
    }
  }

  async function loadPage(page = 0, options = {}) {
    const requestId = ++listRequestId;
    const query = String(searchEl?.value || '').trim();
    const includeAll = Boolean(options.includeAll);
    const params = new URLSearchParams({
      group: currentGroup,
      query,
      page: String(page),
      per_page: String(PAGE_SIZE),
      thumb_first: String(Boolean(thumbFirstEl?.checked)),
      include_all: String(includeAll),
      favorites_only: String(Boolean(favOnlyEl?.checked)),
    });
    setStatus('Loading characters...', 'busy');
    try {
      const data = await getJson(`/api/character-viewer/list?${params.toString()}`);
      if (requestId !== listRequestId) return;
      currentPage = Number(data.page || 0);
      totalPages = Math.max(1, Number(data.total_pages || 1));
      currentTotal = Number(data.total || 0);
      const items = data.items || [];
      if (includeAll || Array.isArray(data.all_items)) {
        allItems = Array.isArray(data.all_items) ? data.all_items : items;
        renderListItems(allItems, {resetScroll: Boolean(options.resetList)});
      }
      renderGrid(items);
      updatePager();
      scrollGrid(options.anchor || 'top');
      setStatus(`${formatCount(currentTotal)} characters`, 'ok');
      const selectedStillVisible = selected && items.some(item => (
        item.group === selected.group && item.character === selected.character
      ));
      if (!options.skipAutoSelect && !selected && items.length) {
        await selectCharacter(items[0].group, items[0].character);
      } else if (!selectedStillVisible) {
        markSelection();
      }
    } catch (error) {
      console.error('Character list failed', error);
      setStatus(error.message || 'Character list failed', 'error');
      showToast?.(error.message || 'Character list failed', 'error');
    }
  }

  async function loadAdjacentPage(direction) {
    const nextPage = currentPage + direction;
    if (wheelPageLocked || nextPage < 0 || nextPage >= totalPages) return;
    wheelPageLocked = true;
    try {
      await loadPage(nextPage, {anchor: direction > 0 ? 'top' : 'bottom'});
    } finally {
      setTimeout(() => {
        wheelPageLocked = false;
      }, 260);
    }
  }

  function onGridWheel(event) {
    if (!gridEl || wheelPageLocked) return;
    const atTop = gridEl.scrollTop <= 2;
    const atBottom = gridEl.scrollTop + gridEl.clientHeight >= gridEl.scrollHeight - 2;
    if (event.deltaY > 0 && atBottom && currentPage < totalPages - 1) {
      event.preventDefault();
      loadAdjacentPage(1);
    } else if (event.deltaY < 0 && atTop && currentPage > 0) {
      event.preventDefault();
      loadAdjacentPage(-1);
    }
  }

  function markSelection() {
    const group = selected?.group || '';
    const character = selected?.character || '';
    [gridEl, listEl].forEach(container => {
      container?.querySelectorAll('[data-group][data-character]').forEach(item => {
        item.classList.toggle(
          'active',
          item.dataset.group === group && item.dataset.character === character,
        );
      });
    });
  }

  function getItemIndex(group, character) {
    const found = allItems.find(item => item.group === group && item.character === character);
    return found ? Number(found.index || 0) : -1;
  }

  function focusGridCard(group, character) {
    const card = gridEl?.querySelector(`.character-viewer-card[data-group="${CSS.escape(group)}"][data-character="${CSS.escape(character)}"]`);
    if (!card) return;
    card.focus({preventScroll: true});
    card.scrollIntoView({block: 'nearest', inline: 'nearest'});
  }

  async function selectCharacterFromList(group, character, index) {
    if (!group || !character) return;
    const targetIndex = Number.isFinite(index) && index >= 0 ? index : getItemIndex(group, character);
    const targetPage = targetIndex >= 0 ? Math.floor(targetIndex / PAGE_SIZE) : currentPage;
    const openDetail = activeView === 'detail' || isCompactViewport();
    if (!openDetail) switchCharacterView('characters');
    if (targetPage !== currentPage) {
      await loadPage(targetPage, {anchor: 'top', skipAutoSelect: true});
    }
    await selectCharacter(group, character, '', {openDetail});
    if (openDetail) switchCharacterView('detail');
    else focusGridCard(group, character);
  }

  function renderEmptyDetail() {
    detail = null;
    selected = null;
    if (selectedImage) {
      selectedImage.removeAttribute('src');
      selectedImage.classList.remove('show');
    }
    if (selectedEmpty) selectedEmpty.hidden = false;
    if (selectedName) selectedName.textContent = '캐릭터를 선택하세요';
    if (selectedMeta) selectedMeta.textContent = '';
    if (variantEl) variantEl.innerHTML = '';
    if (tagSectionsEl) tagSectionsEl.innerHTML = '';
    if (promptEl) promptEl.value = '';
    updateActionAvailability();
    switchCharacterView('characters');
  }

  function renderTagSection(title, items, toneClass = '') {
    if (!items?.length) return '';
    const rows = items.map(item => `
      <div class="character-viewer-tag-row">
        <span>${html(item.tag)}</span>
        <b>${formatCount(item.count)}</b>
        <em>${Number(item.pct || 0).toFixed(1)}%</em>
      </div>
    `).join('');
    return `
      <section class="character-viewer-tag-card ${toneClass}">
        <header>${html(title)} <span>${items.length}</span></header>
        ${rows}
      </section>
    `;
  }

  function renderDetail(data) {
    detail = data;
    const displayName = data.variant
      ? `${data.character} (${String(data.variant).replace(/_/g, ' ')})`
      : data.character;
    if (selectedName) selectedName.textContent = displayName || '캐릭터를 선택하세요';
    if (selectedMeta) {
      const groupText = data.group ? `Group: ${data.group}` : '';
      selectedMeta.textContent = `${groupText}${groupText ? ' · ' : ''}${formatCount(data.count)} posts`;
    }
    const thumbUrl = data.thumbnail_url || data.default_thumbnail_url || '';
    if (selectedImage) {
      if (thumbUrl) {
        selectedImage.src = thumbUrl;
        selectedImage.classList.add('show');
        if (selectedEmpty) selectedEmpty.hidden = true;
      } else {
        selectedImage.removeAttribute('src');
        selectedImage.classList.remove('show');
        if (selectedEmpty) selectedEmpty.hidden = false;
      }
    }
    if (variantEl) {
      variantEl.innerHTML = (data.variants || []).map(item => `
        <option value="${html(item.label)}">${html(item.name || 'Default')} · ${formatCount(item.rows)}</option>
      `).join('');
      variantEl.value = data.variant || '';
    }
    const sections = data.sections || {};
    if (tagSectionsEl) {
      tagSectionsEl.innerHTML = [
        renderTagSection('Personal Color', sections.personal_color || [], 'personal'),
        renderTagSection('Characteristics', sections.characteristics || [], 'characteristics'),
        renderTagSection('Attire', sections.attire || [], 'attire'),
      ].filter(Boolean).join('') || '<div class="character-viewer-tag-empty">No tag detail</div>';
    }
    lastPromptPayload = data.prompt || null;
    // #characterViewerPrompt는 편집 가능한 textarea(Copy/Generate의 소스) — 사용자가
    // 직접 편집 중(포커스)일 때 재시드하면 수동 편집·캐럿·스크롤이 날아간다.
    if (promptEl && lastPromptPayload && document.activeElement !== promptEl
        && promptEl.value !== (lastPromptPayload.character_prompt || '')) {
      promptEl.value = lastPromptPayload.character_prompt || '';
    }
    updateActionAvailability();
    markSelection();
    if (activeView === 'detail') switchCharacterView('detail');
  }

  async function selectCharacter(group, character, variant = '', options = {}) {
    if (!group || !character) return;
    const requestId = ++detailRequestId;
    promptRequestId += 1;
    const variantKey = String(variant || '');
    selected = {group, character, variant: variantKey};
    markSelection();
    setStatus(`${character} loading...`, 'busy');
    try {
      const data = await postJson('/api/character-viewer/detail', {
        group,
        character,
        variant,
        options: currentOptions(),
      });
      if (
        requestId !== detailRequestId
        || selected?.group !== group
        || selected?.character !== character
        || String(selected?.variant || '') !== variantKey
      ) {
        return;
      }
      renderDetail(data);
      setStatus(`${formatCount(currentTotal)} characters`, 'ok');
      if (options.openDetail) switchCharacterView('detail');
    } catch (error) {
      if (requestId !== detailRequestId) return;
      console.error('Character detail failed', error);
      showToast?.(error.message || 'Character detail failed', 'error');
      setStatus(error.message || 'Character detail failed', 'error');
      updateActionAvailability();
    }
  }

  async function refreshPrompt() {
    if (!selected) return;
    const requestId = ++promptRequestId;
    const group = selected.group;
    const character = selected.character;
    const variantKey = String(selected.variant || '');
    try {
      const data = await postJson('/api/character-viewer/prompt', {
        group,
        character,
        variant: variantKey,
        options: currentOptions(),
      });
      if (
        requestId !== promptRequestId
        || selected?.group !== group
        || selected?.character !== character
        || String(selected?.variant || '') !== variantKey
      ) {
        return;
      }
      lastPromptPayload = data;
      // 디바운스 refresh(120ms)가 사용자 편집 중에도 도달할 수 있다 — 포커스 중이면
      // 재시드하지 않아 수동 편집·캐럿·스크롤을 보존한다(eventPreset :4117 가드와 동일).
      if (promptEl && document.activeElement !== promptEl
          && promptEl.value !== (data.character_prompt || '')) {
        promptEl.value = data.character_prompt || '';
      }
    } catch (error) {
      console.error('Character prompt refresh failed', error);
      showToast?.(error.message || 'Character prompt failed', 'error');
    }
  }

  function schedulePromptRefresh() {
    if (promptEl?._characterPromptTimer) clearTimeout(promptEl._characterPromptTimer);
    promptEl._characterPromptTimer = setTimeout(refreshPrompt, 120);
  }

  async function saveCurrentOptions() {
    try {
      const saved = await postJson('/api/character-viewer/options', currentOptions());
      state = {...(state || {}), options: saved};
      return saved;
    } catch (error) {
      console.error('Character options save failed', error);
      return null;
    }
  }

  function scheduleSaveOptions() {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(saveCurrentOptions, 350);
  }

  async function copyPrompt() {
    const text = normalizeCharacterPromptForCopy(promptEl?.value || '');
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      showToast?.('캐릭터 프롬프트를 복사했습니다.', 'success');
    } catch (_) {
      showToast?.('복사에 실패했습니다.', 'error');
    }
  }

  function buildGenerationPayload() {
    const charPrompt = String(promptEl?.value || '').trim();
    const prefix = String(prefixEl?.value || '').trim();
    const postfix = String(postfixEl?.value || '').trim();
    const characterUc = Array.isArray(lastPromptPayload?.cosplay_excluded_pc)
      ? lastPromptPayload.cosplay_excluded_pc.join(', ')
      : '';
    return {
      ...currentOptions(),
      request_id: makeRequestId(),
      group: selected?.group || '',
      character: selected?.character || '',
      variant: variantEl?.value || detail?.variant || '',
      character_prompt: charPrompt,
      prefix,
      postfix,
      character_uc: characterUc,
      negative_prompt: negEdit?.value || '',
      api_mode: currentGenerationMode(),
    };
  }

  async function generateSelected(options = {}) {
    if (!selected || !detail) return;
    clearContinuousTimer();
    const payload = buildGenerationPayload();
    if (!(payload.character_prompt || payload.prefix || payload.postfix)) {
      showToast?.('프롬프트가 비어 있습니다.', 'error');
      return;
    }
    pendingResultRequestId = payload.request_id;
    pendingResultMeta = null;
    armPendingResultTimeout(payload.request_id);
    revokeResultBlobUrl();
    if (resultTitleEl) resultTitleEl.textContent = `${detail.character} · generating`;
    showResultPreview('Waiting for generated image...');
    updateActionAvailability();
    try {
      await saveCurrentOptions();
      await postJson('/api/character-viewer/generate', payload);
      if (!options.automatic) showToast?.('Character 생성 요청을 보냈습니다.', 'success');
    } catch (error) {
      pendingResultRequestId = '';
      pendingResultMeta = null;
      clearPendingResultTimeout();
      showResultPreview(error.message || 'Generate failed');
      showToast?.(error.message || 'Generate failed', 'error');
      updateActionAvailability();
    }
  }

  function clearContinuousTimer() {
    continuousScheduleToken += 1;
    if (continuousTimer) {
      clearTimeout(continuousTimer);
      continuousTimer = null;
    }
  }

  function continuousEnabled() {
    return Boolean(active && continuousGenEl?.checked);
  }

  function continuousDelayMs() {
    const value = Number(state?.generation_delay_ms ?? 500);
    return Number.isFinite(value) && value >= 0 ? value : 500;
  }

  async function refreshGenerationDelay() {
    try {
      const data = await getJson('/api/character-viewer/state');
      if (data && typeof data === 'object') {
        state = {
          ...(state || {}),
          generation_delay_ms: data.generation_delay_ms,
        };
      }
    } catch (error) {
      console.warn('Character Viewer generation delay refresh failed', error);
    }
  }

  function nextGenerableItem() {
    if (!allItems.length) return null;
    const selectedIndex = selected ? getItemIndex(selected.group, selected.character) : -1;
    const start = selectedIndex >= 0 ? selectedIndex + 1 : Math.max(0, currentPage * PAGE_SIZE);
    const emptyOnly = Boolean(emptyOnlyEl?.checked);
    for (let index = start; index < allItems.length; index += 1) {
      const item = allItems[index];
      if (!item) continue;
      if (emptyOnly && item.has_thumbnail) continue;
      return item;
    }
    return null;
  }

  function scheduleContinuousNext(reason = 'result') {
    clearContinuousTimer();
    if (!continuousEnabled()) return;
    const token = ++continuousScheduleToken;
    refreshGenerationDelay().finally(() => {
      if (token !== continuousScheduleToken || !continuousEnabled()) return;
      continuousTimer = setTimeout(() => {
        continuousTimer = null;
        generateNextContinuous(reason).catch(error => {
          console.error('Character continuous generation failed', error);
          showToast?.(error.message || 'Character continuous generation failed', 'error');
          if (continuousGenEl) continuousGenEl.checked = false;
        });
      }, continuousDelayMs());
    });
  }

  async function generateNextContinuous() {
    if (!continuousEnabled() || pendingResultRequestId) return;
    const next = nextGenerableItem();
    if (!next) {
      if (continuousGenEl) continuousGenEl.checked = false;
      showToast?.('연속 생성 완료: 생성 가능한 캐릭터가 없습니다.', 'success');
      return;
    }
    const targetPage = Math.floor(Number(next.index || 0) / PAGE_SIZE);
    if (targetPage !== currentPage) {
      await loadPage(targetPage, {anchor: 'top', skipAutoSelect: true});
    }
    await selectCharacter(next.group, next.character, '', {openDetail: activeView === 'detail'});
    if (activeView === 'characters') focusGridCard(next.group, next.character);
    const expectedGroup = next.group;
    const expectedCharacter = next.character;
    setTimeout(() => {
      if (
        continuousEnabled()
        && !pendingResultRequestId
        && selected?.group === expectedGroup
        && selected?.character === expectedCharacter
      ) {
        generateSelected({automatic: true});
      }
    }, 300);
  }

  function clearPendingResultTimeout() {
    if (pendingResultTimer) {
      clearTimeout(pendingResultTimer);
      pendingResultTimer = null;
    }
  }

  function armPendingResultTimeout(requestId) {
    clearPendingResultTimeout();
    pendingResultTimer = setTimeout(() => {
      if (pendingResultRequestId !== requestId) return;
      pendingResultRequestId = '';
      pendingResultMeta = null;
      showResultPreview('Generate timed out before a result was received.');
      showToast?.('Character 생성 응답을 받지 못했습니다.', 'error');
      updateActionAvailability();
    }, 10 * 60 * 1000);
  }

  function revokeResultBlobUrl() {
    if (!resultBlobUrl) return;
    URL.revokeObjectURL(resultBlobUrl);
    resultBlobUrl = '';
  }

  function updateResultExpandButton() {
    if (!resultExpandBtn) return;
    const hasImage = Boolean(resultBlobUrl && resultImageEl?.classList.contains('show'));
    resultExpandBtn.disabled = !hasImage || resultExpanded;
    resultExpandBtn.textContent = resultExpanded ? '확대 중' : '크게 보기';
  }

  function applyResultPreviewVisibility() {
    if (!resultPreviewEl) return;
    resultPreviewEl.hidden = !(resultPreviewOpen && active && activeView === 'detail');
    updateResultExpandButton();
  }

  function clearResultCollapseClickBlock() {
    suppressResultCollapseClick = false;
    if (suppressResultCollapseClickTimer) {
      clearTimeout(suppressResultCollapseClickTimer);
      suppressResultCollapseClickTimer = null;
    }
    document.removeEventListener('click', blockResultCollapseClick, true);
  }

  function blockResultCollapseClick(event) {
    if (!suppressResultCollapseClick) return;
    event.preventDefault();
    event.stopPropagation();
    clearResultCollapseClickBlock();
  }

  function armResultCollapseClickBlock() {
    clearResultCollapseClickBlock();
    suppressResultCollapseClick = true;
    document.addEventListener('click', blockResultCollapseClick, true);
    suppressResultCollapseClickTimer = setTimeout(clearResultCollapseClickBlock, 350);
  }

  function collapseResultOnPointer(event) {
    if (!resultExpanded) return;
    setResultExpanded(false);
    armResultCollapseClickBlock();
    event.preventDefault();
    event.stopPropagation();
  }

  function setResultExpanded(expanded) {
    const canExpand = Boolean(active && resultPreviewOpen && resultPreviewEl && resultBlobUrl && resultImageEl?.classList.contains('show'));
    resultExpanded = Boolean(expanded && canExpand);
    resultPreviewEl?.classList.toggle('is-expanded', resultExpanded);
    document.body?.classList.toggle('character-viewer-result-spotlight', resultExpanded);
    document.removeEventListener('pointerdown', collapseResultOnPointer, true);
    if (resultExpanded) {
      clearResultCollapseClickBlock();
      document.addEventListener('pointerdown', collapseResultOnPointer, true);
    }
    updateResultExpandButton();
  }

  function showResultPreview(message = 'Waiting for generated image...') {
    setResultExpanded(false);
    resultPreviewOpen = true;
    applyResultPreviewVisibility();
    if (resultEmptyEl) {
      resultEmptyEl.hidden = false;
      resultEmptyEl.textContent = message;
    }
    if (resultImageEl) {
      resultImageEl.removeAttribute('src');
      resultImageEl.classList.remove('show');
    }
    updateResultExpandButton();
  }

  function closeResultPreview() {
    setResultExpanded(false);
    clearResultCollapseClickBlock();
    clearPendingResultTimeout();
    pendingResultRequestId = '';
    pendingResultMeta = null;
    resultPreviewOpen = false;
    revokeResultBlobUrl();
    if (resultPreviewEl) resultPreviewEl.hidden = true;
    if (resultImageEl) {
      resultImageEl.removeAttribute('src');
      resultImageEl.classList.remove('show');
    }
    if (resultEmptyEl) resultEmptyEl.hidden = false;
    updateActionAvailability();
    updateResultExpandButton();
  }

  function refreshThumbnailFromMeta(meta) {
    const group = String(meta?.character_viewer_group || selected?.group || '');
    const character = String(meta?.character_viewer_character_name || selected?.character || '');
    if (!meta?.character_viewer_thumbnail_url || !group || !character) return;
    if (selected && selected.group !== group && !meta.character_viewer_group) return;
    if (selected && selected.character !== character && !meta.character_viewer_character_name) return;
    // 서버 URL 에 파일 판(`v=<mtime>-<size>`)이 이미 붙어 있다 — 내용이 바뀌면 URL 이
    // 바뀌므로 여기서 `&_=Date.now()` 로 뚫을 필요가 없다. 예전 그 임시방편은 이 순간만
    // 통했고, 탭을 다시 열거나 새로고침하면 평범한 URL 로 돌아가 **캐시된 폴백이 다시
    // 나왔다** — 사용자가 만든 썸네일이 "소리없이 사라진" 이유다.
    const savedUrl = String(meta.character_viewer_thumbnail_url || '');
    const gridUrl = gridThumbnailUrl(savedUrl);
    // detail 캐시도 같이 갱신해야 방금 생성한 썸네일을 곧바로 DELETE 할 수 있다
    // (currentThumbnailTarget 이 detail 의 URL 필드로 대상을 판정한다).
    const savedVariant = String(meta.character_viewer_variant || '');
    if (detail && detail.group === group && detail.character === character) {
      if (!savedVariant) detail.default_thumbnail_url = savedUrl;
      if (String(detail.variant || '') === savedVariant) detail.thumbnail_url = savedUrl;
    }
    if (state && Number.isFinite(Number(meta.character_viewer_thumbnail_count))
        && Number(meta.character_viewer_thumbnail_count) > 0) {
      state.thumbnail_count = Number(meta.character_viewer_thumbnail_count);
      renderSummary();
    }
    allItems = allItems.map(item => (
      item.group === group && item.character === character
        ? {...item, has_thumbnail: true, thumbnail_url: gridUrl}
        : item
    ));
    const listItem = listEl?.querySelector(`.character-viewer-list-item[data-group="${CSS.escape(group)}"][data-character="${CSS.escape(character)}"]`);
    listItem?.classList.add('has-thumb');
    listItem?.classList.remove('no-thumb');
    if (selected?.group === group && selected?.character === character && selectedImage) {
      selectedImage.src = savedUrl;
      selectedImage.classList.add('show');
      if (selectedEmpty) selectedEmpty.hidden = true;
    }
    gridEl?.querySelectorAll(`.character-viewer-card[data-group="${CSS.escape(group)}"][data-character="${CSS.escape(character)}"]`).forEach(card => {
      const stage = card.querySelector('.character-viewer-card-image');
      if (stage) {
        stage.innerHTML = `
          <img src="${html(gridUrl)}" alt="${html(character)}" loading="lazy" decoding="async">
          <span class="character-viewer-card-group">[${html(group)}]</span>
        `;
      }
      card.classList.add('has-thumb');
      card.classList.remove('no-thumb');
    });
  }

  function currentThumbnailTarget() {
    if (!selected || !detail) return null;
    const group = String(detail.group || selected.group || '');
    const character = String(detail.character || selected.character || '');
    if (!group || !character) return null;
    // 화면에 떠 있는 이미지가 이 바리에이션 자신의 썸네일인지, renderDetail 이
    // default_thumbnail_url 로 떨어뜨린 대표 썸네일인지 구분한다. 폴백을 보고
    // 있는데 바리에이션 키로 삭제를 보내면 서버에는 지울 것이 없고 이미지는
    // 그대로 남는다 — "보고 있는 것을 지운다"가 이 버튼의 계약.
    if (detail.thumbnail_url) {
      return {group, character, variant: String(detail.variant || '')};
    }
    if (detail.default_thumbnail_url) {
      return {group, character, variant: ''};
    }
    return null;
  }

  function clearThumbnailLocally(group, character, variant, after = null) {
    // ⚠️ 사용자 썸네일을 지워도 **번들 폴백이 있으면 그림은 남는다**. 서버가 지운 뒤의
    // 실효 상태(`has_thumbnail`/`thumbnail_url`)를 주므로 그대로 따른다. 예전엔 무조건
    // `false` 로 칠해서 폴백이 있는 캐릭터가 새로고침 전까지 "No Thumb" 로 보였다.
    const variantKey = String(variant || '');
    const restoredUrl = String(after?.thumbnail_url || '');
    const restoredDefault = String(after?.default_thumbnail_url || '');
    const stillHas = Boolean(after?.has_thumbnail);
    if (detail && detail.group === group && detail.character === character) {
      if (!variantKey) detail.default_thumbnail_url = restoredDefault;
      if (String(detail.variant || '') === variantKey) detail.thumbnail_url = restoredUrl;
    }
    if (selectedImage && selected?.group === group && selected?.character === character) {
      const showing = detail?.thumbnail_url || detail?.default_thumbnail_url || '';
      if (showing) {
        selectedImage.src = showing;
      } else {
        selectedImage.removeAttribute('src');
        selectedImage.classList.remove('show');
        if (selectedEmpty) selectedEmpty.hidden = false;
      }
    }
    // 그리드/리스트의 has_thumbnail 은 대표(variant 없음) 썸네일만 가리킨다.
    if (variantKey) return;
    const gridUrl = stillHas ? gridThumbnailUrl(restoredDefault) : '';
    allItems = allItems.map(item => (
      item.group === group && item.character === character
        ? {...item, has_thumbnail: stillHas, thumbnail_url: gridUrl}
        : item
    ));
    const listItem = listEl?.querySelector(`.character-viewer-list-item[data-group="${CSS.escape(group)}"][data-character="${CSS.escape(character)}"]`);
    listItem?.classList.toggle('has-thumb', stillHas);
    listItem?.classList.toggle('no-thumb', !stillHas);
    gridEl?.querySelectorAll(`.character-viewer-card[data-group="${CSS.escape(group)}"][data-character="${CSS.escape(character)}"]`).forEach(card => {
      const stage = card.querySelector('.character-viewer-card-image');
      if (stage) {
        stage.innerHTML = stillHas && gridUrl
          ? `
          <img src="${html(gridUrl)}" alt="${html(character)}" loading="lazy" decoding="async">
          <span class="character-viewer-card-group">[${html(group)}]</span>
        `
          : `
          <span class="character-viewer-card-empty">No Thumb</span>
          <span class="character-viewer-card-group">[${html(group)}]</span>
        `;
      }
      card.classList.toggle('has-thumb', stillHas);
      card.classList.toggle('no-thumb', !stillHas);
    });
  }

  async function deleteSelectedThumbnail() {
    // 확인 없이 즉시 삭제(사용자 지시).
    const target = currentThumbnailTarget();
    if (!target || deletingThumb) return;
    deletingThumb = true;
    updateActionAvailability();
    const label = target.variant
      ? `${target.character} (${target.variant.replace(/_/g, ' ')})`
      : target.character;
    try {
      const data = await postJson('/api/character-viewer/thumbnail/delete', target);
      clearThumbnailLocally(target.group, target.character, target.variant, data);
      if (state && Number.isFinite(Number(data.thumbnail_count))) {
        state.thumbnail_count = Number(data.thumbnail_count);
        renderSummary();
      }
      if (data.removed) showToast?.(`${label} 썸네일을 삭제했습니다.`, 'success');
      else showToast?.('삭제할 썸네일이 없습니다.', 'warning');
    } catch (error) {
      console.error('Character thumbnail delete failed', error);
      showToast?.(error.message || '썸네일 삭제에 실패했습니다.', 'error');
    } finally {
      deletingThumb = false;
      updateActionAvailability();
    }
  }

  function handleResultMeta(meta) {
    if (!meta || !meta.character_viewer_request) return false;
    const requestId = String(meta.character_viewer_request_id || '');
    if (pendingResultRequestId && requestId && requestId !== pendingResultRequestId) return false;
    if (!pendingResultRequestId && requestId) pendingResultRequestId = requestId;
    pendingResultMeta = meta;
    const title = meta.character_viewer_character || detail?.character || 'Character';
    const size = meta.width && meta.height ? ` · ${meta.width}x${meta.height}` : '';
    if (resultTitleEl) resultTitleEl.textContent = `${title}${size}`;
    showResultPreview('Receiving generated image...');
    return true;
  }

  function handleResultBlob(blob) {
    if (!pendingResultMeta || !blob) return false;
    clearPendingResultTimeout();
    revokeResultBlobUrl();
    resultBlobUrl = URL.createObjectURL(blob);
    resultPreviewOpen = true;
    applyResultPreviewVisibility();
    if (resultImageEl) {
      resultImageEl.src = resultBlobUrl;
      resultImageEl.classList.add('show');
    }
    if (resultEmptyEl) resultEmptyEl.hidden = true;
    refreshThumbnailFromMeta(pendingResultMeta);
    pendingResultMeta = null;
    pendingResultRequestId = '';
    updateActionAvailability();
    updateResultExpandButton();
    scheduleContinuousNext('result');
    return true;
  }

  function handleGenerationError(message) {
    const requestId = String(message?.request_id || '');
    if (pendingResultRequestId && requestId && requestId !== pendingResultRequestId) return false;
    clearPendingResultTimeout();
    pendingResultRequestId = '';
    pendingResultMeta = null;
    showResultPreview(message?.message || 'Generate failed');
    showToast?.(message?.message || 'Generate failed', 'error');
    updateActionAvailability();
    scheduleContinuousNext('error');
    return true;
  }

  function gotoPage() {
    const value = Math.max(1, Math.min(totalPages, Number.parseInt(gotoInput?.value || '1', 10) || 1));
    loadPage(value - 1, {anchor: value - 1 < currentPage ? 'bottom' : 'top'});
  }

  function cardTargetFromElement(card) {
    if (!card) return null;
    const group = card.dataset.group || '';
    const character = card.dataset.character || '';
    if (!group || !character) return null;
    return {group, character};
  }

  function closeContextMenu() {
    if (contextMenuEl?.parentNode) contextMenuEl.parentNode.removeChild(contextMenuEl);
    contextMenuEl = null;
    contextMenuTarget = null;
    document.removeEventListener('pointerdown', onContextMenuPointerDown, true);
    document.removeEventListener('keydown', onContextMenuKeyDown, true);
    window.removeEventListener('blur', closeContextMenu);
    window.removeEventListener('resize', closeContextMenu);
  }

  function onContextMenuPointerDown(event) {
    if (contextMenuEl?.contains(event.target)) return;
    closeContextMenu();
  }

  function onContextMenuKeyDown(event) {
    if (event.key === 'Escape') closeContextMenu();
  }

  function positionContextMenu(menu, x, y) {
    const margin = 8;
    const rect = menu.getBoundingClientRect();
    const left = Math.min(Math.max(margin, x), window.innerWidth - rect.width - margin);
    const top = Math.min(Math.max(margin, y), window.innerHeight - rect.height - margin);
    menu.style.left = `${left}px`;
    menu.style.top = `${top}px`;
  }

  async function copyCharacterPromptFor(target) {
    if (!target?.group || !target?.character) return;
    const data = await postJson('/api/character-viewer/prompt', {
      group: target.group,
      character: target.character,
      variant: '',
      options: currentOptions(),
    });
    const text = normalizeCharacterPromptForCopy(data.character_prompt || '');
    if (!text) throw new Error('Character prompt is empty');
    await navigator.clipboard.writeText(text);
    showToast?.('캐릭터 프롬프트를 복사했습니다.', 'success');
  }

  function openContextMenu(event, target) {
    if (!target?.group || !target?.character) return;
    event.preventDefault();
    event.stopPropagation();
    closeContextMenu();
    contextMenuTarget = target;
    const menu = document.createElement('div');
    menu.className = 'result-context-menu character-viewer-context-menu open';
    menu.setAttribute('role', 'menu');
    menu.innerHTML = `
      <div class="result-context-group">
        <button type="button" class="result-context-item" data-action="copy-character-prompt" role="menuitem">
          <span>캐릭터 프롬프트 복사</span>
        </button>
      </div>
    `;
    menu.addEventListener('contextmenu', e => e.preventDefault());
    menu.addEventListener('click', event => {
      const button = event.target.closest('.result-context-item[data-action]');
      if (!button) return;
      event.preventDefault();
      event.stopPropagation();
      const action = button.dataset.action || '';
      const targetItem = contextMenuTarget;
      closeContextMenu();
      if (action === 'copy-character-prompt') {
        copyCharacterPromptFor(targetItem).catch(error => {
          showToast?.(error.message || 'Character prompt copy failed', 'error');
        });
      }
    });
    contextMenuEl = menu;
    document.body.appendChild(menu);
    positionContextMenu(menu, event.clientX, event.clientY);
    document.addEventListener('pointerdown', onContextMenuPointerDown, true);
    document.addEventListener('keydown', onContextMenuKeyDown, true);
    window.addEventListener('blur', closeContextMenu);
    window.addEventListener('resize', closeContextMenu);
  }

  function bind() {
    groupSearchEl?.addEventListener('input', () => {
      if (groupSearchTimer) clearTimeout(groupSearchTimer);
      groupSearchTimer = setTimeout(loadGroups, 160);
    });
    groupListEl?.addEventListener('click', event => {
      const button = event.target.closest('.character-viewer-group-item[data-group]');
      if (!button || !groupListEl.contains(button)) return;
      currentGroup = button.dataset.group || '__ALL__';
      selected = null;
      detail = null;
      renderGroups();
      renderEmptyDetail();
      loadPage(0, {anchor: 'top', includeAll: true, resetList: true});
    });
    searchEl?.addEventListener('input', () => {
      if (searchTimer) clearTimeout(searchTimer);
      searchTimer = setTimeout(() => loadPage(0, {anchor: 'top', includeAll: true, resetList: true}), 180);
    });
    thumbFirstEl?.addEventListener('change', () => {
      scheduleSaveOptions();
      loadPage(0, {anchor: 'top', includeAll: true, resetList: true});
    });
    // ⚠️ 이 체크는 **옵션으로 저장하지 않는다.** 즐겨찾기만 보는 것은 지금의 시선이지
    //    설정이 아니다 - 저장하면 다음에 탭을 열었을 때 도감이 텅 빈 것처럼 보인다.
    favOnlyEl?.addEventListener('change', () => {
      loadPage(0, {anchor: 'top', includeAll: true, resetList: true});
    });
    gridEl?.addEventListener('wheel', onGridWheel, {passive: false});
    listEl?.addEventListener('scroll', scheduleListRender, {passive: true});
    listEl?.addEventListener('click', event => {
      const item = event.target.closest('[data-group][data-character]');
      if (!item || !listEl.contains(item)) return;
      selectCharacterFromList(
        item.dataset.group || '',
        item.dataset.character || '',
        Number(item.dataset.index || -1),
      );
    });
    gridEl?.addEventListener('click', event => {
      // ⚠️ 별을 **카드보다 먼저** 본다. 별이 카드 안에 있어서 순서를 뒤집으면 별을
      //    눌러도 카드가 먼저 걸려 상세만 열린다.
      const star = event.target.closest('[data-favorite-toggle]');
      if (star && gridEl.contains(star)) {
        event.preventDefault();
        void toggleFavorite(star.dataset.favGroup || '', star.dataset.favCharacter || '');
        return;
      }
      const item = event.target.closest('[data-group][data-character]');
      if (!item || !gridEl.contains(item)) return;
      selectCharacter(item.dataset.group || '', item.dataset.character || '', '', {openDetail: true});
    });
    gridEl?.addEventListener('contextmenu', event => {
      const card = event.target.closest('.character-viewer-card[data-group][data-character]');
      if (!card || !gridEl.contains(card)) return;
      const target = cardTargetFromElement(card);
      if (target) openContextMenu(event, target);
    });
    subtabEls.forEach(button => {
      button.addEventListener('click', () => switchCharacterView(button.dataset.characterViewerTab || 'characters'));
    });
    prevBtn?.addEventListener('click', () => loadPage(Math.max(0, currentPage - 1), {anchor: 'bottom'}));
    nextBtn?.addEventListener('click', () => loadPage(Math.min(totalPages - 1, currentPage + 1), {anchor: 'top'}));
    gotoBtn?.addEventListener('click', gotoPage);
    gotoInput?.addEventListener('keydown', event => {
      if (event.key === 'Enter') {
        event.preventDefault();
        gotoPage();
      }
    });
    variantEl?.addEventListener('change', () => {
      if (selected) selectCharacter(selected.group, selected.character, variantEl.value || '', {openDetail: activeView === 'detail'});
    });
    [autoCopyrightEl, autoCharacteristicsEl, hideNameEl, noSaveEl, cosplayEl, cosplayNameEl].forEach(control => {
      control?.addEventListener('input', () => {
        scheduleSaveOptions();
        schedulePromptRefresh();
      });
      control?.addEventListener('change', () => {
        scheduleSaveOptions();
        schedulePromptRefresh();
      });
    });
    emptyOnlyEl?.addEventListener('change', scheduleSaveOptions);
    continuousGenEl?.addEventListener('change', () => {
      if (!continuousGenEl.checked) clearContinuousTimer();
    });
    [prefixEl, postfixEl].forEach(control => {
      control?.addEventListener('input', scheduleSaveOptions);
      control?.addEventListener('change', scheduleSaveOptions);
    });
    copyBtn?.addEventListener('click', copyPrompt);
    generateBtn?.addEventListener('click', generateSelected);
    deleteThumbBtn?.addEventListener('click', deleteSelectedThumbnail);
    resultExpandBtn?.addEventListener('click', event => {
      event.preventDefault();
      event.stopPropagation();
      setResultExpanded(true);
    });
    resultCloseBtn?.addEventListener('click', closeResultPreview);
  }

  async function load(options = {}) {
    if (loaded && !options.force) {
      applyResultPreviewVisibility();
      return;
    }
    try {
      state = await getJson('/api/character-viewer/state');
      applyOptions(state.options || {});
      renderSummary();
      if (!state.available) {
        setStatus('Character data is not available', 'error');
        return;
      }
      await loadGroups();
      await loadPage(currentPage, {anchor: 'top', includeAll: true, resetList: true});
      loaded = true;
    } catch (error) {
      console.error('Character Viewer load failed', error);
      setStatus(error.message || 'Character Viewer load failed', 'error');
      showToast?.(error.message || 'Character Viewer load failed', 'error');
    }
  }

  function setActive(nextActive) {
    active = Boolean(nextActive);
    if (!active) setResultExpanded(false);
    applyResultPreviewVisibility();
  }

  bind();
  syncViewState();

  return {
    load,
    reload: () => load({force: true}),
    setActive,
    handleResultMeta,
    handleResultBlob,
    handleGenerationError,
  };
}
