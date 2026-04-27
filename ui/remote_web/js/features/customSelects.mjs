export function createCustomSelectController({ document, window }) {
  const SELECTOR = 'select:not([multiple]):not([data-native-select])';
  const enhanced = new WeakMap();
  const states = new Set();
  let openState = null;
  let syncTimer = null;
  let observer = null;

  function selectClasses(select) {
    return Array.from(select.classList)
      .filter(Boolean)
      .map(name => `custom-${name}`)
      .join(' ');
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
    const onSelectChange = () => syncState(state);
    const optionObserver = new MutationObserver(() => syncState(state));
    optionObserver.observe(select, {
      childList: true,
      subtree: true,
      attributes: true,
      characterData: true,
    });

    button.addEventListener('click', onButtonClick);
    button.addEventListener('keydown', onButtonKeydown);
    select.addEventListener('change', onSelectChange);
    state.cleanup.push(
      () => button.removeEventListener('click', onButtonClick),
      () => button.removeEventListener('keydown', onButtonKeydown),
      () => select.removeEventListener('change', onSelectChange),
      () => optionObserver.disconnect(),
    );

    syncState(state);
  }

  function syncState(state) {
    const { select, wrapper, button, label } = state;
    if (!document.documentElement.contains(select)) {
      destroyState(state);
      return;
    }

    const selectedOption = select.selectedOptions?.[0] || select.options[select.selectedIndex] || select.options[0];
    label.textContent = selectedOption ? selectedOption.textContent : '';
    button.disabled = select.disabled;
    wrapper.classList.toggle('is-disabled', select.disabled);
    button.setAttribute('aria-expanded', openState?.select === select ? 'true' : 'false');

    if (openState?.select === select) {
      renderMenu(state);
      positionMenu(state);
    }
  }

  function renderMenu(state) {
    const { select, menu } = state;
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

      item.addEventListener('mouseenter', () => setHoveredItem(menu, item));
      item.addEventListener('mousedown', event => event.preventDefault());
      item.addEventListener('click', event => {
        event.preventDefault();
        if (!option.disabled) commitValue(state, index);
      });

      menu.append(item);
    });
  }

  function setHoveredItem(menu, item) {
    menu.querySelectorAll('.custom-select-option.is-hovered').forEach(el => {
      if (el !== item) el.classList.remove('is-hovered');
    });
    item.classList.add('is-hovered');
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
      selected.classList.add('is-hovered');
      selected.scrollIntoView({ block: 'nearest' });
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
  }

  function positionMenu(state) {
    const rect = state.button.getBoundingClientRect();
    const viewportGap = 8;
    const menuMaxHeight = Math.min(420, Math.max(160, window.innerHeight - viewportGap * 2));
    const below = window.innerHeight - rect.bottom - viewportGap;
    const above = rect.top - viewportGap;
    const openUpward = below < 180 && above > below;
    const height = Math.min(menuMaxHeight, Math.max(120, openUpward ? above : below));
    const top = openUpward ? Math.max(viewportGap, rect.top - height - 4) : Math.min(window.innerHeight - viewportGap, rect.bottom + 4);

    state.menu.style.left = `${Math.round(rect.left)}px`;
    state.menu.style.top = `${Math.round(top)}px`;
    state.menu.style.width = `${Math.round(rect.width)}px`;
    state.menu.style.maxHeight = `${Math.round(height)}px`;
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

    setHoveredItem(state.menu, items[nextIndex]);
    items[nextIndex].scrollIntoView({ block: 'nearest' });
  }

  function destroyState(state) {
    if (openState === state) closeOpen();
    state.cleanup.forEach(fn => fn());
    state.menu.remove();
    state.wrapper.remove();
    states.delete(state);
    enhanced.delete(state.select);
  }

  function scan() {
    document.querySelectorAll(SELECTOR).forEach(enhance);
    Array.from(states).forEach(syncState);
  }

  function onDocumentPointerDown(event) {
    if (!openState) return;
    const { wrapper, menu } = openState;
    if (wrapper.contains(event.target) || menu.contains(event.target)) return;
    closeOpen();
  }

  function onWindowLayoutChange() {
    if (openState) positionMenu(openState);
  }

  function start() {
    scan();
    observer = new MutationObserver(() => scan());
    observer.observe(document.body, { childList: true, subtree: true });
    syncTimer = window.setInterval(scan, 750);
    document.addEventListener('pointerdown', onDocumentPointerDown, true);
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
