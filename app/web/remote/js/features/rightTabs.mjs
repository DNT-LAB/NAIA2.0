export function createRightTabsController({document, onLeaveResult}) {
  const buttons = Array.from(document.querySelectorAll('.right-tab-btn'));
  const panes = Array.from(document.querySelectorAll('.right-tab-pane'));
  const hiddenTabs = new Set(
    buttons
      .filter(button => button.dataset.rightTabHidden === 'true')
      .map(button => button.dataset.rightTab)
      .filter(Boolean),
  );

  function hideTabButton(button) {
    button.hidden = true;
    // CSS 규칙(.right-tab-btn[data-right-tab-hidden="true"])과 런타임 상태 동기화.
    button.setAttribute('data-right-tab-hidden', 'true');
    button.classList.remove('active');
    button.setAttribute('aria-hidden', 'true');
    button.setAttribute('aria-selected', 'false');
    button.setAttribute('tabindex', '-1');
  }

  function hideTabPane(pane) {
    pane.hidden = true;
    pane.classList.remove('active');
    pane.setAttribute('aria-hidden', 'true');
  }

  function showTabButton(button) {
    button.hidden = false;
    // hidden 속성만 지우면 마크업의 data-right-tab-hidden="true"가 CSS
    // display:none !important로 남아 버튼이 영영 보이지 않는다.
    button.removeAttribute('data-right-tab-hidden');
    button.removeAttribute('aria-hidden');
    button.removeAttribute('tabindex');
  }

  function showTabPane(pane) {
    pane.hidden = false;
    pane.removeAttribute('aria-hidden');
  }

  function applyHiddenState() {
    buttons.forEach(button => {
      if (hiddenTabs.has(button.dataset.rightTab)) {
        hideTabButton(button);
        return;
      }
      showTabButton(button);
    });
    panes.forEach(pane => {
      if (hiddenTabs.has(pane.dataset.rightPane)) {
        hideTabPane(pane);
        return;
      }
      showTabPane(pane);
    });
  }

  function switchTo(tabName) {
    const nextTab = hiddenTabs.has(tabName) ? 'result' : tabName;
    buttons.forEach(button => {
      if (hiddenTabs.has(button.dataset.rightTab)) {
        hideTabButton(button);
        return;
      }
      const active = button.dataset.rightTab === nextTab;
      button.classList.toggle('active', active);
      button.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    panes.forEach(pane => {
      if (hiddenTabs.has(pane.dataset.rightPane)) {
        hideTabPane(pane);
        return;
      }
      pane.hidden = false;
      pane.removeAttribute('aria-hidden');
      pane.classList.toggle('active', pane.dataset.rightPane === nextTab);
    });

    if (nextTab !== 'result' && onLeaveResult) {
      onLeaveResult();
    }
    return nextTab;
  }

  applyHiddenState();

  function setAvailability(tabAvailability = {}) {
    Object.entries(tabAvailability || {}).forEach(([tabName, available]) => {
      if (available) hiddenTabs.delete(tabName);
      else hiddenTabs.add(tabName);
    });
    const active = buttons.find(button => button.classList.contains('active'))?.dataset.rightTab || 'result';
    applyHiddenState();
    return switchTo(hiddenTabs.has(active) ? 'result' : active);
  }

  return {switchTo, setAvailability};
}
