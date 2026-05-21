export function createPromptDrawer({
  document,
  getWs,
  WebSocket,
  mediaQuery,
}) {
  const drawer = document.getElementById('promptDrawer');
  const toggleBar = document.querySelector('.prompt-toggle-bar');
  const toggleArrow = document.getElementById('toggleArrow');
  const toggleArrow2 = document.getElementById('toggleArrow2');
  const promptNewDot = document.getElementById('promptNewDot');
  let open = false;

  function syncOpenClasses() {
    if (drawer) drawer.classList.toggle('open', open);
    if (toggleBar) toggleBar.classList.toggle('open', open);
    if (toggleArrow) {
      toggleArrow.classList.toggle('open', open);
      toggleArrow.innerHTML = open ? '&#9660;' : '&#9650;';
    }
    if (toggleArrow2) {
      toggleArrow2.classList.toggle('open', open);
      toggleArrow2.innerHTML = open ? '&#9660;' : '&#9650;';
    }
  }

  function toggle() {
    if (mediaQuery.matches) return;
    open = !open;
    syncOpenClasses();
    if (open) {
      if (promptNewDot) promptNewDot.classList.add('hidden');
      const ws = getWs();
      if (ws && ws.readyState === WebSocket.OPEN) ws.send('sync');
    }
  }

  function showNewContentDot() {
    if (!open && promptNewDot) promptNewDot.classList.remove('hidden');
  }

  function closeForDesktop() {
    if (!mediaQuery.matches) return;
    if (drawer) drawer.classList.remove('open');
    open = false;
  }

  function switchTab(name) {
    document.querySelectorAll('.tab-btn').forEach(button => {
      button.classList.toggle('active', button.dataset.tab === name);
    });
    document.querySelectorAll('.tab-page').forEach(page => {
      page.classList.remove('active');
    });
    document.getElementById('tab' + name.charAt(0).toUpperCase() + name.slice(1)).classList.add('active');
  }

  mediaQuery.addEventListener('change', closeForDesktop);

  return {
    toggle,
    showNewContentDot,
    switchTab,
  };
}
