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
    // 바깥에서 목록을 여는 길. 프리셋 검색이 한 글자마다 이걸 쏜다 — 검색해 놓고
    // 드롭다운을 따로 눌러야 결과가 보이면, 걸렀는지조차 알 수 없다(사용자 지정).
    // `openSelect` 는 포커스를 옮기지 않으므로 검색창에서 계속 칠 수 있다.
    // 이미 열려 있어도 **다시 연다.** 한 글자 더 치면 목록이 바뀌는데, 그때
    // 호버가 옛 항목에 남아 있으면 미리보기가 사라지거나 엉뚱한 것을 가리킨다.
    // openSelect 는 앞에서 closeOpen 을 부르므로 다시 부르는 것이 안전하다.
    const onOpenRequest = () => {
      openSelect(state);
      // 마우스가 메뉴 밖에 있어도 미리보기를 지킨다(schedulePreviewHide 주석).
      state.searchOpen = true;
      cancelPreviewHide(state);
    };
    const onCloseRequest = () => { if (openState === state) closeOpen(); };
    select.addEventListener('naia:select-open', onOpenRequest);
    select.addEventListener('naia:select-close', onCloseRequest);
    state.cleanup.push(
      () => select.removeEventListener('naia:select-open', onOpenRequest),
      () => select.removeEventListener('naia:select-close', onCloseRequest),
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
    const forcedLabel = String(select.dataset.customSelectLabel || '').trim();
    const displayLabel = forcedLabel || (selectedOption ? selectedOption.textContent : '');
    // 접힌 버튼에도 배지를 그린다 — 목록을 닫으면 어느 모델의 프리셋인지 알 수
    // 없어지면 배지의 의미가 반으로 준다. 강제 라벨이 있으면 그쪽이 이긴다.
    if (!forcedLabel && selectedOption && selectedOption.dataset.modelLabel) {
      paintOptionText(label, selectedOption);
    } else {
      label.textContent = displayLabel;
    }
    button.title = String(select.dataset.customSelectTitle || '').trim() || displayLabel;
    button.disabled = select.disabled;
    wrapper.classList.toggle('is-disabled', select.disabled);
    button.setAttribute('aria-expanded', openState?.select === select ? 'true' : 'false');

    if (openState?.select === select && refreshMenu) {
      renderMenu(state);
      positionMenu(state);
      // **호버를 되살린다.** renderMenu 는 항목을 통째로 다시 만들고 미리보기를
      // 걷는다. 프리셋 검색은 옵션을 갈아 끼우므로 여기로 오는데, 되살리지 않으면
      // 목록만 남고 미리보기가 사라진다 — 검색어를 칠해 보여줄 자리가 없어진다
      // (실측: 한 글자씩 치면 되고 한 번에 붙여넣으면 안 되던 차이가 이것이었다).
      focusPreviewTarget(state);
    } else if (openState?.select === select) {
      positionMenu(state);
    }
  }

  /** 옵션 텍스트를 `[배지] 이름` 으로 그린다.
   *
   *  ⚠️ **`data-model-label` 이 있는 옵션에만** 적용한다 — 이 함수는 앱의 모든
   *  커스텀 셀렉트가 지나가는 길이라, 조건 없이 손대면 관계없는 드롭다운이 같이
   *  바뀐다. 배지 색은 CSS 가 `data-family` 로 정한다(라벨 부분에만 색).
   *  innerHTML 은 쓰지 않는다 — 프리셋 이름은 사용자가 적은 것이다. */
  function paintOptionText(host, option) {
    host.textContent = '';
    const badge = String(option.dataset.modelLabel || '').trim();
    if (!badge) { host.textContent = option.textContent; return; }
    const tag = document.createElement('span');
    tag.className = 'custom-select-model-tag';
    tag.dataset.family = String(option.dataset.modelFamily || '');
    // Full / Curated 를 색 밝기로 가른다. 같은 세대(family)라 색상은 같고 밝기만
    // 다르다 - 갈래 구분은 그대로 두면서 F/C 만 눈에 띄게 하려는 것이다.
    tag.dataset.variant = String(option.dataset.modelVariant || '');
    tag.textContent = `[${badge}]`;
    host.appendChild(tag);
    host.appendChild(document.createTextNode(' ' + option.textContent));
  }

  /** 목록 **맨 위**에 붙는 갈래 필터 바(`[ ALL | NAI5 | NAI4.5 | ETC ]`).
   *
   *  `data-option-filters` 가 있는 셀렉트에만 그린다. 누르면 셀렉트에
   *  `naia:option-filter` 를 쏘고, 무엇을 걸러낼지는 **소유자가 정한다** —
   *  이 파일은 목록을 그릴 뿐 프리셋을 모른다. */
  function renderFilterBar(state, menu) {
    const { select } = state;
    let groups;
    try { groups = JSON.parse(select.dataset.optionFilters || '[]'); } catch (_) { groups = []; }
    if (!Array.isArray(groups) || groups.length < 2) return;
    const active = String(select.dataset.optionFilterActive || groups[0]?.key || '');
    const bar = document.createElement('div');
    bar.className = 'custom-select-filterbar';
    groups.forEach(g => {
      if (!g || !g.key) return;
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'custom-select-filter-btn';
      b.textContent = String(g.label || g.key);
      b.classList.toggle('is-active', String(g.key) === active);
      b.addEventListener('mousedown', event => event.preventDefault());
      b.addEventListener('click', event => {
        event.preventDefault();
        event.stopPropagation();          // 항목 선택으로 번지면 드롭다운이 닫힌다
        select.dataset.optionFilterActive = String(g.key);
        select.dispatchEvent(new CustomEvent('naia:option-filter', {
          bubbles: true, detail: { key: String(g.key) },
        }));
      });
      bar.appendChild(b);
    });
    menu.appendChild(bar);
  }

  function renderMenu(state) {
    const { select, menu } = state;
    hidePreview(state);
    menu.textContent = '';
    renderFilterBar(state, menu);
    Array.from(select.options).forEach((option, index) => {
      const item = document.createElement('button');
      item.type = 'button';
      item.className = 'custom-select-option';
      paintOptionText(item, option);
      item.dataset.index = String(index);
      item.setAttribute('role', 'option');
      item.setAttribute('aria-selected', option.selected ? 'true' : 'false');
      item.disabled = option.disabled;
      item.classList.toggle('is-selected', option.selected);
      // 검색에 실제로 걸린 항목 표시(프리셋 검색이 붙인다). 미리보기를 여기로 짚는다.
      if (option.dataset.searchHit) item.dataset.searchHit = '1';

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
    // 검색으로 연 동안은 미리보기를 걷지 않는다. 그 경로에서는 마우스가 메뉴
    // 밖(검색창 근처)에 있어서, 목록이 뜨는 순간 pointerleave 가 걸려 220ms 뒤
    // 미리보기가 사라진다 — 검색어를 칠하려고 띄운 것이 바로 없어졌다(실측).
    if (state.searchOpen) return;
    cancelPreviewHide(state);
    state.previewHideTimer = window.setTimeout(() => {
      state.previewHideTimer = null;
      clearHoveredItem(state);
    }, 220);
  }

  function openSelect(state) {
    closeOpen();
    state.searchOpen = false;     // 검색 경로면 부른 쪽이 다시 켠다
    openState = state;
    state.wrapper.classList.add('is-open');
    state.button.setAttribute('aria-expanded', 'true');
    renderMenu(state);
    positionMenu(state);
    state.menu.hidden = false;

    focusPreviewTarget(state);
  }

  /** 목록을 (다시) 그린 뒤 어디를 짚어 미리보기를 띄울지 정한다.
   *
   *  검색 중이면 **첫 결과**다. 고른 것은 검색에 안 걸려도 목록에 남아 있어서
   *  (프리셋 검색 규칙) 그쪽을 띄우면 정작 찾은 것은 안 보인다. */
  function focusPreviewTarget(state) {
    const searching = !!(state.select.dataset.previewHighlight || '').trim();
    // **첫 항목이 아니라 첫 '매치'다.** 프리셋 검색은 지금 고른 것을 검색에 안
    // 걸려도 원래 순서 그대로 남기므로, 그것이 매치보다 앞이면 검색 결과 대신
    // 그쪽이 열리고 형광펜도 안 보인다(Codex 리뷰 2026-08-08).
    const firstHit = state.menu.querySelector('.custom-select-option[data-search-hit]');
    const first = state.menu.querySelector('.custom-select-option');
    const selected = state.menu.querySelector('.custom-select-option.is-selected');
    const target = (searching && (firstHit || first)) || selected;
    if (target) {
      setHoveredItem(state, target);
      target.scrollIntoView({ block: 'nearest' });
    } else {
      hidePreview(state);
    }
  }

  function closeOpen() {
    if (!openState) return;
    const state = openState;
    openState = null;
    state.searchOpen = false;     // 닫히면 미리보기 고정도 푼다
    state.wrapper.classList.remove('is-open');
    state.button.setAttribute('aria-expanded', 'false');
    state.menu.hidden = true;
    state.menu.textContent = '';
    hidePreview(state);
  }

  /** 손가락으로 쓰는 화면인가. 마우스 hover 가 성립하지 않는 환경이다.
   *
   *  ⚠️ **매번 다시 묻는다**(캐시하지 않는다). 데스크톱 브라우저에서 창을 줄이거나
   *     기기 에뮬레이션을 켜면 이 값이 바뀐다 - 한 번 재서 굳히면 그때부터 거짓말을 한다.
   */
  function isCoarsePointer() {
    try {
      return window.matchMedia('(pointer: coarse)').matches
        || window.matchMedia('(hover: none)').matches;
    } catch (_) {
      return false;
    }
  }

  function hasPreview(state) {
    // ⚠️ **터치 화면에서는 preview 를 아예 만들지 않는다.**
    //
    //    preview 는 `position: fixed` 레이어이고 z-index 가 메뉴보다 **높다**
    //    (--z-floating-select-preview 10110 > --z-floating-select 10100).
    //    데스크톱에서는 메뉴 좌우에 놓이지만, 좌우 공간이 없는 모바일에서는 폴백이
    //    메뉴와 **같은 자리**를 골라 옵션을 통째로 덮는다. `pointer-events: auto`
    //    라서 탭이 preview 로 먹히고, 프리셋을 눌러도 값이 안 바뀐다.
    //
    //    실측(2026-08-26 조사 · 2026-08-29 재확인, 375~393px):
    //      옵션 중앙의 `document.elementFromPoint()` = `.custom-select-preview-thumb`
    //      실제 터치 뒤에도 `#modPreset.value` 가 그대로였다.
    //
    //    z-index 나 `pointer-events` 를 손보는 대신 **애초에 안 만든다** - 손가락에는
    //    hover 라는 것이 없어서 preview 를 띄울 계기 자체가 없다.
    if (isCoarsePointer()) return false;
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

  /** `data-preview-highlight` 에 담긴 검색어들. 줄바꿈으로 구분한다 —
   *  검색어에 쉼표가 들어갈 수 있어 쉼표로는 못 가른다. */
  function highlightTerms(select) {
    return String(select?.dataset.previewHighlight || '')
      .split('\n').map(t => t.trim()).filter(Boolean);
  }

  /** 본문에 검색어가 나온 자리를 형광펜으로 칠한다.
   *
   *  **innerHTML 을 쓰지 않는다.** 프리셋 본문은 사용자가 적은 것이고 `<` 나
   *  따옴표가 얼마든지 들어간다 — 문자열로 이어 붙이면 그대로 마크업이 된다.
   *  텍스트 노드와 `<mark>` 를 직접 만들어 붙인다. */
  function paintTerms(host, text, terms) {
    host.textContent = '';
    if (!terms.length) { host.textContent = text; return; }
    const hay = text.toLowerCase();
    // 어느 자리가 칠해지는지 먼저 모은다(검색어끼리 겹칠 수 있다 → 병합).
    const spans = [];
    terms.forEach(term => {
      const t = term.toLowerCase();
      let i = hay.indexOf(t);
      while (i >= 0) { spans.push([i, i + t.length]); i = hay.indexOf(t, i + t.length); }
    });
    if (!spans.length) { host.textContent = text; return; }
    spans.sort((a, b) => a[0] - b[0]);
    const merged = [spans[0]];
    for (const [s, e] of spans.slice(1)) {
      const last = merged[merged.length - 1];
      if (s <= last[1]) last[1] = Math.max(last[1], e);
      else merged.push([s, e]);
    }
    let at = 0;
    for (const [s, e] of merged) {
      if (s > at) host.append(document.createTextNode(text.slice(at, s)));
      const mark = document.createElement('mark');
      mark.className = 'custom-select-hit';
      mark.textContent = text.slice(s, e);
      host.append(mark);
      at = e;
    }
    if (at < text.length) host.append(document.createTextNode(text.slice(at)));
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
    const terms = highlightTerms(state.select);
    body.forEach(([label, text, fallback]) => {
      if (text === undefined) return;                 // 이 select 는 그 칸을 안 쓴다
      const value = String(text || '');
      if (!value && fallback === null) return;        // 비어 있으면 굳이 자리를 만들지 않는다
      const cap = document.createElement('div');
      cap.className = 'custom-select-preview-cap';
      cap.textContent = label;
      const pre = document.createElement('pre');
      pre.className = 'custom-select-preview-prefix';
      if (value) paintTerms(pre, value, terms);
      else pre.textContent = fallback;
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

  /** 지금 **실제로 보이는** 세로 구간. 소프트 키보드가 먹은 자리는 뺀다.
   *
   *  ⚠️ `window.innerHeight` 만 보면 모바일에서 키보드가 올라온 순간 메뉴를 그 아래로
   *     밀어 넣는다 - 화면에는 안 보이는데 열려 있는 상태가 된다. `visualViewport` 는
   *     키보드가 먹은 높이를 빼고 돌려주므로 그것을 기준으로 삼는다.
   *  ⚠️ `visualViewport` 가 없으면(옛 브라우저) 예전과 **똑같이** 동작한다.
   */
  function viewportBand() {
    const vv = window.visualViewport;
    if (!vv || !(vv.height > 0)) {
      return {top: 0, bottom: window.innerHeight, height: window.innerHeight};
    }
    const top = vv.offsetTop || 0;
    return {top, bottom: top + vv.height, height: vv.height};
  }

  function positionMenu(state) {
    const rect = state.button.getBoundingClientRect();
    const viewportGap = 8;
    const band = viewportBand();
    const menuMaxHeight = Math.min(420, Math.max(160, band.height - viewportGap * 2));
    // ⚠️ **머리말 높이를 더한다.** 이 추정은 원래 옵션 개수만 봤는데(개당 36px),
    // 목록 맨 위에 고정 필터 바가 붙으면서 그 높이가 빠졌다. 항목이 적을 때 바로
    // 드러난다 - 2개면 `2*36+8 = 80px` 로 잡히는데 실제 내용은 바 37 + 항목 56 +
    // 여백 8 = 101px 이라, 메뉴가 잘리고 스크롤이 생겼다(실측, 사용자 지적).
    // 항목이 많을 때는 상한(420)에 먼저 걸려 안 보였다.
    const header = state.menu.querySelector('.custom-select-filterbar');
    const headerHeight = header ? header.offsetHeight : 0;
    const desiredHeight = Math.min(
      menuMaxHeight,
      Math.max(44, state.select.options.length * 36 + 8 + headerHeight),
    );
    const below = band.bottom - rect.bottom - viewportGap;
    const above = rect.top - band.top - viewportGap;
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
      state.menu.style.top = `${Math.round(Math.min(band.bottom - viewportGap, rect.bottom + 4))}px`;
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

  /** 바깥에서 드롭다운 하나를 펼친다(원본 `<select>` 를 준다).
   *
   *  생성이 모르는 모델 키로 막혔을 때 화면이 여기를 열어 다시 고르게 한다
   *  (사용자 지정 2026-08-25). 트리거를 가짜로 클릭하면 열려 있던 경우 **닫혀 버려서**
   *  토글이 아니라 '열기'가 필요하다.
   */
  function openFor(select) {
    const state = Array.from(states).find(item => item.select === select);
    if (!state || state.select.disabled) return false;
    openSelect(state);
    return true;
  }

  return {
    start,
    stop,
    scan,
    openFor,
  };
}
