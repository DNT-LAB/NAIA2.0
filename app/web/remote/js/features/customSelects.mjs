export function createCustomSelectController({
  document,
  window,
  showToast = () => {},
  fetchFn = null,
  useNativeClipboardFallback = () => false,
}) {
  const SELECTOR = 'select:not([multiple]):not([data-native-select])';
  const enhanced = new WeakMap();
  const states = new Set();
  let openState = null;
  let syncTimer = null;
  let observer = null;
  const requestFetch = fetchFn || window.fetch?.bind(window);

  function selectClasses(select) {
    const classes = Array.from(select.classList)
      .filter(Boolean)
      .map(name => `custom-${name}`);
    if (select.closest?.('.studio-tab')) classes.push('custom-studio-select');
    return classes.join(' ');
  }

  function enhance(select) {
    if (!select || enhanced.has(select) || select.size > 1) return;

    const wrapper = document.createElement('div');
    wrapper.className = `custom-select ${selectClasses(select)}`;
    wrapper.dataset.selectId = select.id || '';

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'custom-select-button';
    button.setAttribute('aria-haspopup', 'listbox');
    button.setAttribute('aria-expanded', 'false');

    const label = document.createElement('span');
    label.className = 'custom-select-label';

    const arrow = document.createElement('span');
    arrow.className = 'custom-select-arrow';
    arrow.setAttribute('aria-hidden', 'true');

    button.append(label, arrow);
    wrapper.append(button);

    const menu = document.createElement('div');
    menu.className = `custom-select-menu ${selectClasses(select)}`;
    menu.dataset.selectId = select.id || '';
    menu.setAttribute('role', 'listbox');
    menu.hidden = true;
    document.body.append(menu);

    select.classList.add('native-select-hidden');
    select.setAttribute('aria-hidden', 'true');
    select.tabIndex = -1;
    select.insertAdjacentElement('afterend', wrapper);

    const state = {
      select,
      wrapper,
      button,
      label,
      menu,
      preview: null,
      previewHideTimer: null,
      cleanup: [],
    };
    enhanced.set(select, state);
    states.add(state);

    const onButtonClick = event => {
      event.preventDefault();
      event.stopPropagation();
      if (select.disabled) return;
      if (openState?.select === select) closeOpen();
      else openSelect(state);
    };
    const onButtonKeydown = event => handleButtonKeydown(state, event);
    const onPreviewBoundaryEnter = () => cancelPreviewHide(state);
    const onPreviewBoundaryLeave = event => {
      if (isInsidePreviewBoundary(state, event.relatedTarget)) return;
      schedulePreviewHide(state);
    };
    const onSelectChange = () => syncState(state, { refreshMenu: true });
    const optionObserver = new MutationObserver(mutations => {
      const previewOnly = mutations.length > 0 && mutations.every(mutation => (
        mutation.type === 'attributes'
        && typeof mutation.attributeName === 'string'
        && mutation.attributeName.startsWith('data-preview-')
      ));
      if (previewOnly) return;
      syncState(state, { refreshMenu: true });
    });
    optionObserver.observe(select, {
      childList: true,
      subtree: true,
      attributes: true,
      characterData: true,
    });

    button.addEventListener('click', onButtonClick);
    button.addEventListener('keydown', onButtonKeydown);
    wrapper.addEventListener('pointerenter', onPreviewBoundaryEnter);
    wrapper.addEventListener('pointerleave', onPreviewBoundaryLeave);
    menu.addEventListener('pointerenter', onPreviewBoundaryEnter);
    menu.addEventListener('pointerleave', onPreviewBoundaryLeave);
    select.addEventListener('change', onSelectChange);
    state.cleanup.push(
      () => button.removeEventListener('click', onButtonClick),
      () => button.removeEventListener('keydown', onButtonKeydown),
      () => wrapper.removeEventListener('pointerenter', onPreviewBoundaryEnter),
      () => wrapper.removeEventListener('pointerleave', onPreviewBoundaryLeave),
      () => menu.removeEventListener('pointerenter', onPreviewBoundaryEnter),
      () => menu.removeEventListener('pointerleave', onPreviewBoundaryLeave),
      () => select.removeEventListener('change', onSelectChange),
      () => optionObserver.disconnect(),
    );

    syncState(state);
  }

  function syncState(state, { refreshMenu = false } = {}) {
    const { select, wrapper, button, label } = state;
    if (!document.documentElement.contains(select)) {
      destroyState(state);
      return;
    }

    const selectedOption = select.selectedOptions?.[0] || select.options[select.selectedIndex] || select.options[0];
    const displayLabel = String(select.dataset.customSelectLabel || '').trim()
      || (selectedOption ? selectedOption.textContent : '');
    label.textContent = displayLabel;
    button.title = String(select.dataset.customSelectTitle || '').trim() || displayLabel;
    button.disabled = select.disabled;
    wrapper.classList.toggle('is-disabled', select.disabled);
    button.setAttribute('aria-expanded', openState?.select === select ? 'true' : 'false');

    if (openState?.select === select && refreshMenu) {
      renderMenu(state);
      positionMenu(state);
    } else if (openState?.select === select) {
      positionMenu(state);
    }
  }

  function renderMenu(state) {
    const { select, menu } = state;
    hidePreview(state);
    menu.textContent = '';
    Array.from(select.options).forEach((option, index) => {
      const item = document.createElement('button');
      item.type = 'button';
      item.className = 'custom-select-option';
      item.textContent = option.textContent;
      item.dataset.index = String(index);
      item.setAttribute('role', 'option');
      item.setAttribute('aria-selected', option.selected ? 'true' : 'false');
      item.disabled = option.disabled;
      item.classList.toggle('is-selected', option.selected);

      item.addEventListener('mouseenter', () => setHoveredItem(state, item));
      item.addEventListener('focus', () => setHoveredItem(state, item));
      item.addEventListener('mousedown', event => event.preventDefault());
      item.addEventListener('click', event => {
        event.preventDefault();
        if (!option.disabled) commitValue(state, index);
      });

      menu.append(item);
    });
  }

  function setHoveredItem(state, item) {
    state.menu.querySelectorAll('.custom-select-option.is-hovered').forEach(el => {
      if (el !== item) el.classList.remove('is-hovered');
    });
    item.classList.add('is-hovered');
    renderPreview(state, item);
  }

  function clearHoveredItem(state) {
    state.menu.querySelectorAll('.custom-select-option.is-hovered').forEach(el => {
      el.classList.remove('is-hovered');
    });
    hidePreview(state);
  }

  function isInsidePreviewBoundary(state, target) {
    if (!target) return false;
    return (
      state.wrapper.contains(target)
      || state.menu.contains(target)
      || !!state.preview?.contains(target)
    );
  }

  function cancelPreviewHide(state) {
    if (!state.previewHideTimer) return;
    window.clearTimeout(state.previewHideTimer);
    state.previewHideTimer = null;
  }

  function schedulePreviewHide(state) {
    cancelPreviewHide(state);
    state.previewHideTimer = window.setTimeout(() => {
      state.previewHideTimer = null;
      clearHoveredItem(state);
    }, 220);
  }

  function openSelect(state) {
    closeOpen();
    openState = state;
    state.wrapper.classList.add('is-open');
    state.button.setAttribute('aria-expanded', 'true');
    renderMenu(state);
    positionMenu(state);
    state.menu.hidden = false;

    const selected = state.menu.querySelector('.custom-select-option.is-selected');
    if (selected) {
      setHoveredItem(state, selected);
      selected.scrollIntoView({ block: 'nearest' });
    } else {
      hidePreview(state);
    }
  }

  function closeOpen() {
    if (!openState) return;
    const state = openState;
    openState = null;
    state.wrapper.classList.remove('is-open');
    state.button.setAttribute('aria-expanded', 'false');
    state.menu.hidden = true;
    state.menu.textContent = '';
    hidePreview(state);
  }

  function hasPreview(state) {
    return state.select.dataset.previewKind === 'prompt-preset';
  }

  function ensurePreview(state) {
    if (state.preview) return state.preview;
    const preview = document.createElement('div');
    preview.className = 'custom-select-preview custom-select-preview-prompt-preset';
    preview.hidden = true;
    preview.addEventListener('pointerenter', () => cancelPreviewHide(state));
    preview.addEventListener('pointerleave', event => {
      if (isInsidePreviewBoundary(state, event.relatedTarget)) return;
      schedulePreviewHide(state);
    });
    document.body.append(preview);
    state.preview = preview;
    return preview;
  }

  function hidePreview(state) {
    cancelPreviewHide(state);
    if (!state.preview) return;
    state.preview.hidden = true;
    state.preview.classList.remove('is-busy');
    state.preview.textContent = '';
  }

  function optionForItem(state, item) {
    const index = Number(item?.dataset?.index ?? -1);
    return Number.isInteger(index) && index >= 0 ? state.select.options[index] : null;
  }

  function renderPreview(state, item) {
    if (!hasPreview(state)) return;
    const option = optionForItem(state, item);
    if (!option) {
      hidePreview(state);
      return;
    }

    const preview = ensurePreview(state);
    preview.textContent = '';

    const thumb = document.createElement('div');
    thumb.className = 'custom-select-preview-thumb';
    const thumbnailUrl = option.dataset.previewThumbnail || '';
    if (thumbnailUrl) {
      thumb.classList.add('has-image');
      const image = document.createElement('img');
      image.src = thumbnailUrl;
      image.alt = '';
      image.loading = 'lazy';
      image.decoding = 'async';
      const markImageRatio = () => {
        const isPortrait = image.naturalWidth > 0 && image.naturalHeight / image.naturalWidth >= 1.18;
        thumb.classList.toggle('is-portrait', isPortrait);
      };
      if (image.complete) markImageRatio();
      else image.addEventListener('load', markImageRatio, { once: true });
      thumb.append(image);
    } else {
      const empty = document.createElement('span');
      empty.textContent = 'No image';
      thumb.append(empty);
    }

    const copy = document.createElement('div');
    copy.className = 'custom-select-preview-copy';
    const head = document.createElement('div');
    head.className = 'custom-select-preview-head';
    const title = document.createElement('strong');
    title.textContent = option.dataset.previewName || option.textContent || '';
    head.append(title);
    const mode = option.dataset.previewMode || '';
    if (mode) {
      const modeEl = document.createElement('span');
      modeEl.textContent = mode;
      head.append(modeEl);
    }
    copy.append(head);

    const description = option.dataset.previewDescription || '';
    if (description) {
      const desc = document.createElement('p');
      desc.className = 'custom-select-preview-desc';
      desc.textContent = description;
      copy.append(desc);
    }

    // Quick Preset 판과 **같은 구조**로 보여준다: Prefix 다음 Postfix.
    // 예전에는 prefix 만 떠서, 검색이 postfix 까지 훑는데도 무엇이 걸렸는지
    // 여기서 확인할 방법이 없었다(사용자 지적 2026-08-08).
    // postfix 를 실어 주지 않는 select 는 그 칸 자체가 나오지 않는다.
    const body = [
      ['Prefix', option.dataset.previewPrefix || '', 'No prefix prompt'],
      ['Postfix', option.dataset.previewPostfix, null],
    ];
    body.forEach(([label, text, fallback]) => {
      if (text === undefined) return;                 // 이 select 는 그 칸을 안 쓴다
      const value = String(text || '');
      if (!value && fallback === null) return;        // 비어 있으면 굳이 자리를 만들지 않는다
      const cap = document.createElement('div');
      cap.className = 'custom-select-preview-cap';
      cap.textContent = label;
      const pre = document.createElement('pre');
      pre.className = 'custom-select-preview-prefix';
      pre.textContent = value || fallback;
      copy.append(cap, pre);
    });

    preview.append(thumb, copy);
    if (state.select.dataset.previewActions !== 'none') {
      preview.append(buildPreviewActions(state, option));
    }
    preview.hidden = false;
    positionPreview(state);
  }

  function buildPreviewActions(state, option) {
    const actions = document.createElement('div');
    actions.className = 'custom-select-preview-actions';
    const identity = previewPresetIdentity(option);
    const canManage = !!identity.name && identity.name !== '*randomized';

    const generate = document.createElement('button');
    generate.type = 'button';
    generate.textContent = '임시 썸네일 생성';
    generate.disabled = !canManage;
    generate.dataset.previewCanManage = canManage ? 'true' : 'false';
    generate.addEventListener('click', event => {
      event.preventDefault();
      event.stopPropagation();
      requestTemporaryThumbnail(state, option);
    });

    const upload = document.createElement('button');
    upload.type = 'button';
    upload.textContent = '썸네일 업로드';
    upload.disabled = !canManage;
    upload.dataset.previewCanManage = canManage ? 'true' : 'false';

    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/png,image/jpeg,image/webp';
    input.hidden = true;
    input.addEventListener('change', () => {
      const file = input.files?.[0];
      input.value = '';
      if (file) uploadPresetThumbnail(state, option, file);
    });
    upload.addEventListener('click', event => {
      event.preventDefault();
      event.stopPropagation();
      if (!upload.disabled) input.click();
    });

    const paste = document.createElement('button');
    paste.type = 'button';
    paste.textContent = '썸네일 붙여넣기';
    paste.disabled = !canManage;
    paste.dataset.previewCanManage = canManage ? 'true' : 'false';
    paste.addEventListener('click', event => {
      event.preventDefault();
      event.stopPropagation();
      pastePresetThumbnail(state, option);
    });

    actions.append(generate, upload, paste, input);
    return actions;
  }

  function previewPresetIdentity(option) {
    return {
      name: String(option?.dataset?.previewName || option?.value || option?.textContent || '').trim(),
      mode: String(option?.dataset?.previewMode || '').trim(),
    };
  }

  async function readActionResponse(response) {
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data?.ok === false) {
      throw new Error(data?.error || data?.message || `HTTP ${response.status}`);
    }
    return data;
  }

  function setPreviewBusy(state, busy) {
    if (!state.preview) return;
    state.preview.classList.toggle('is-busy', !!busy);
    state.preview.querySelectorAll('.custom-select-preview-actions button').forEach(button => {
      button.disabled = !!busy || button.dataset.previewCanManage !== 'true';
    });
  }

  function applyPresetThumbnailUpdate(state, detail = {}) {
    const name = String(detail.name || '').trim();
    const mode = String(detail.mode || '').trim();
    const thumbnailUrl = String(detail.thumbnail_url || detail.thumbnailUrl || '').trim();
    if (!name || !thumbnailUrl) return;

    Array.from(state.select.options).forEach(option => {
      const identity = previewPresetIdentity(option);
      if (identity.name !== name) return;
      if (mode && identity.mode && identity.mode !== mode) return;
      option.dataset.previewThumbnail = thumbnailUrl;
    });

    const hovered = state.menu.querySelector('.custom-select-option.is-hovered');
    const hoveredOption = optionForItem(state, hovered);
    if (hoveredOption && previewPresetIdentity(hoveredOption).name === name) {
      renderPreview(state, hovered);
    }
  }

  async function uploadPresetThumbnail(state, option, blob) {
    const identity = previewPresetIdentity(option);
    if (!identity.name || identity.name === '*randomized') return;
    try {
      setPreviewBusy(state, true);
      const params = new URLSearchParams({ name: identity.name, mode: identity.mode });
      const response = await window.fetch(`/api/prompt-engineering/preset-thumbnail/upload?${params.toString()}`, {
        method: 'POST',
        headers: { 'Content-Type': blob.type || 'application/octet-stream' },
        body: blob,
      });
      const data = await readActionResponse(response);
      applyPresetThumbnailUpdate(state, data);
      showToast('프리셋 썸네일을 저장했습니다.', 'success');
    } catch (error) {
      console.error('Preset thumbnail upload failed', error);
      showToast(error.message || '프리셋 썸네일 저장 실패', 'error');
    } finally {
      setPreviewBusy(state, false);
    }
  }

  async function readBrowserClipboardImageBlob() {
    if (!window.navigator?.clipboard?.read) {
      throw new Error('이 브라우저는 이미지 붙여넣기를 지원하지 않습니다.');
    }
    const items = await window.navigator.clipboard.read();
    for (const item of items) {
      const type = item.types.find(candidate => candidate.startsWith('image/'));
      if (!type) continue;
      return item.getType(type);
    }
    throw new Error('클립보드에 이미지가 없습니다.');
  }

  async function readNativeClipboardImageBlob() {
    if (typeof requestFetch !== 'function') {
      throw new Error('클립보드 fallback을 사용할 수 없습니다.');
    }
    const response = await requestFetch('/api/clipboard/png', {cache: 'no-store'});
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || `클립보드 이미지 읽기 실패: HTTP ${response.status}`);
    }
    return response.blob();
  }

  async function readClipboardImageBlob() {
    let browserError = null;
    if (useNativeClipboardFallback()) {
      try {
        return await readNativeClipboardImageBlob();
      } catch (error) {
        browserError = error;
      }
    }

    try {
      return await readBrowserClipboardImageBlob();
    } catch (error) {
      browserError = error;
    }

    throw browserError || new Error('클립보드에 이미지가 없습니다.');
  }

  async function pastePresetThumbnail(state, option) {
    try {
      const blob = await readClipboardImageBlob();
      await uploadPresetThumbnail(state, option, blob);
    } catch (error) {
      console.error('Preset thumbnail paste failed', error);
      showToast(error.message || '썸네일 붙여넣기 실패', 'error');
    }
  }

  async function requestTemporaryThumbnail(state, option) {
    const identity = previewPresetIdentity(option);
    if (!identity.name || identity.name === '*randomized') return;
    try {
      setPreviewBusy(state, true);
      const response = await window.fetch('/api/prompt-engineering/preset-thumbnail/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(identity),
      });
      const data = await readActionResponse(response);
      showToast(data.message || '임시 썸네일 생성을 요청했습니다.', 'success');
    } catch (error) {
      console.error('Preset thumbnail generation request failed', error);
      showToast(error.message || '임시 썸네일 생성 요청 실패', 'error');
    } finally {
      setPreviewBusy(state, false);
    }
  }

  function positionPreview(state) {
    if (!state.preview || state.preview.hidden || state.menu.hidden) return;
    const menuRect = state.menu.getBoundingClientRect();
    const gap = 8;
    const viewportGap = 8;
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    const preferredWidth = Math.min(390, Math.max(280, viewportWidth - viewportGap * 2));
    state.preview.style.width = `${Math.round(preferredWidth)}px`;
    state.preview.style.maxHeight = `${Math.max(180, viewportHeight - viewportGap * 2)}px`;

    const previewRect = state.preview.getBoundingClientRect();
    let left;
    if (viewportWidth - menuRect.right - gap >= previewRect.width) {
      left = menuRect.right + gap;
    } else if (menuRect.left - gap - viewportGap >= previewRect.width) {
      left = menuRect.left - gap - previewRect.width;
    } else {
      left = Math.min(
        Math.max(viewportGap, menuRect.left),
        Math.max(viewportGap, viewportWidth - previewRect.width - viewportGap),
      );
    }

    const maxTop = Math.max(viewportGap, viewportHeight - previewRect.height - viewportGap);
    const top = Math.min(Math.max(viewportGap, menuRect.top), maxTop);
    state.preview.style.left = `${Math.round(left)}px`;
    state.preview.style.top = `${Math.round(top)}px`;
  }

  function positionMenu(state) {
    const rect = state.button.getBoundingClientRect();
    const viewportGap = 8;
    const menuMaxHeight = Math.min(420, Math.max(160, window.innerHeight - viewportGap * 2));
    const desiredHeight = Math.min(menuMaxHeight, Math.max(44, state.select.options.length * 36 + 8));
    const below = window.innerHeight - rect.bottom - viewportGap;
    const above = rect.top - viewportGap;
    const preferBelow = state.wrapper.classList.contains('custom-studio-select') && below >= 64;
    const openUpward = !preferBelow && below < desiredHeight && above > below;
    const available = Math.max(44, openUpward ? above : below);
    const height = Math.min(menuMaxHeight, desiredHeight, available);

    state.menu.style.left = `${Math.round(rect.left)}px`;
    state.menu.style.width = `${Math.round(rect.width)}px`;
    state.menu.style.maxHeight = `${Math.round(height)}px`;
    // 위로 열 때는 메뉴의 '아래' 끝을 버튼 바로 위에 고정(bottom-anchor)한다. top + 추정높이 방식은
    // 옵션 높이를 과대추정(옵션당 36px 가정)할 때 실제 짧은 메뉴가 버튼에서 떨어져 보이는 간격이 생긴다.
    // 아래로 열 때는 기존대로 버튼 아래에 붙인다(간격 없음).
    if (openUpward) {
      state.menu.style.top = 'auto';
      state.menu.style.bottom = `${Math.round(Math.max(viewportGap, window.innerHeight - (rect.top - 4)))}px`;
    } else {
      state.menu.style.bottom = 'auto';
      state.menu.style.top = `${Math.round(Math.min(window.innerHeight - viewportGap, rect.bottom + 4))}px`;
    }
    positionPreview(state);
  }

  function commitValue(state, index) {
    const option = state.select.options[index];
    if (!option || option.disabled) return;

    const oldValue = state.select.value;
    state.select.selectedIndex = index;
    syncState(state);
    closeOpen();

    if (state.select.value !== oldValue) {
      state.select.dispatchEvent(new Event('input', { bubbles: true }));
      state.select.dispatchEvent(new Event('change', { bubbles: true }));
    }
    state.button.focus({ preventScroll: true });
  }

  function handleButtonKeydown(state, event) {
    if (state.select.disabled) return;

    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      openState?.select === state.select ? closeOpen() : openSelect(state);
      return;
    }

    if (event.key === 'Escape') {
      closeOpen();
      return;
    }

    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
    event.preventDefault();

    if (openState?.select !== state.select) openSelect(state);
    const direction = event.key === 'ArrowDown' ? 1 : -1;
    moveHover(state, direction);
  }

  function moveHover(state, direction) {
    const items = Array.from(state.menu.querySelectorAll('.custom-select-option:not(:disabled)'));
    if (!items.length) return;

    const current = state.menu.querySelector('.custom-select-option.is-hovered');
    const currentIndex = current ? items.indexOf(current) : -1;
    const nextIndex = currentIndex < 0
      ? (direction > 0 ? 0 : items.length - 1)
      : (currentIndex + direction + items.length) % items.length;

    setHoveredItem(state, items[nextIndex]);
    items[nextIndex].scrollIntoView({ block: 'nearest' });
  }

  function destroyState(state) {
    if (openState === state) closeOpen();
    state.cleanup.forEach(fn => fn());
    if (state.preview) state.preview.remove();
    state.menu.remove();
    state.wrapper.remove();
    states.delete(state);
    enhanced.delete(state.select);
  }

  function scan() {
    document.querySelectorAll(SELECTOR).forEach(enhance);
    Array.from(states).forEach(syncState);
  }

  function mutationNeedsScan(mutations) {
    return mutations.some(mutation => {
      if (isCustomSelectNode(mutation.target)) return false;

      const addedOrRemovedNodes = [
        ...Array.from(mutation.addedNodes || []),
        ...Array.from(mutation.removedNodes || []),
      ];
      return addedOrRemovedNodes.some(nodeContainsSelectable);
    });
  }

  function nodeContainsSelectable(node) {
    if (isCustomSelectNode(node)) return false;
    if (node.nodeType !== Node.ELEMENT_NODE) return false;
    if (node.matches?.(SELECTOR)) return true;
    return !!node.querySelector?.(SELECTOR);
  }

  function isCustomSelectNode(node) {
    if (node.nodeType !== Node.ELEMENT_NODE) return false;
    return !!node.closest?.('.custom-select, .custom-select-menu');
  }

  function onDocumentPointerDown(event) {
    if (!openState) return;
    const { wrapper, menu, preview } = openState;
    if (wrapper.contains(event.target) || menu.contains(event.target) || preview?.contains(event.target)) return;
    closeOpen();
  }

  function onPresetThumbnailUpdated(event) {
    const detail = event?.detail || {};
    Array.from(states).forEach(state => {
      if (hasPreview(state)) applyPresetThumbnailUpdate(state, detail);
    });
  }

  function onWindowLayoutChange() {
    if (openState) positionMenu(openState);
  }

  function start() {
    scan();
    observer = new MutationObserver(mutations => {
      if (mutationNeedsScan(mutations)) scan();
    });
    observer.observe(document.body, { childList: true, subtree: true });
    syncTimer = window.setInterval(scan, 750);
    document.addEventListener('pointerdown', onDocumentPointerDown, true);
    document.addEventListener('prompt-engineering-thumbnail-updated', onPresetThumbnailUpdated);
    window.addEventListener('resize', onWindowLayoutChange);
    window.addEventListener('scroll', onWindowLayoutChange, true);
  }

  function stop() {
    closeOpen();
    if (observer) observer.disconnect();
    observer = null;
    if (syncTimer) window.clearInterval(syncTimer);
    syncTimer = null;
    document.removeEventListener('pointerdown', onDocumentPointerDown, true);
    document.removeEventListener('prompt-engineering-thumbnail-updated', onPresetThumbnailUpdated);
    window.removeEventListener('resize', onWindowLayoutChange);
    window.removeEventListener('scroll', onWindowLayoutChange, true);
    Array.from(states).forEach(destroyState);
  }

  return {
    start,
    stop,
    scan,
  };
}
