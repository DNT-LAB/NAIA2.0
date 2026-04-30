export function createRightTabsController({document, onLeaveResult}) {
  const buttons = Array.from(document.querySelectorAll('.right-tab-btn'));
  const panes = Array.from(document.querySelectorAll('.right-tab-pane'));
  const temporaryHiddenTabs = new Set(['danbooru', 'thumb', 'artists', 'studio', 'settings']);
  const hiddenTabs = new Set(
    [
      ...temporaryHiddenTabs,
      ...buttons
        .filter(button => button.hidden || button.dataset.temporaryHidden === 'true')
        .map(button => button.dataset.rightTab)
        .filter(Boolean),
    ],
  );

  function hideTabButton(button) {
    button.hidden = true;
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

  function applyHiddenState() {
    buttons.forEach(button => {
      if (!hiddenTabs.has(button.dataset.rightTab)) {
        return;
      }
      hideTabButton(button);
    });
    panes.forEach(pane => {
      if (!hiddenTabs.has(pane.dataset.rightPane)) {
        return;
      }
      hideTabPane(pane);
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
  }

  applyHiddenState();

  return {switchTo};
}
