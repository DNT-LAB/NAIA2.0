export function createRightTabsController({document, onLeaveResult}) {
  const buttons = Array.from(document.querySelectorAll('.right-tab-btn'));
  const panes = Array.from(document.querySelectorAll('.right-tab-pane'));

  function switchTo(tabName) {
    buttons.forEach(button => {
      const active = button.dataset.rightTab === tabName;
      button.classList.toggle('active', active);
      button.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    panes.forEach(pane => {
      pane.classList.toggle('active', pane.dataset.rightPane === tabName);
    });

    if (tabName !== 'result' && onLeaveResult) {
      onLeaveResult();
    }
  }

  return {switchTo};
}
