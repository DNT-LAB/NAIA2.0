export function createMobileViewportController({
  window,
  document,
  isPC,
  relayoutFloatingPanels,
  getTagTooltip,
}) {
  let keyboardOpen = false;

  if (window.visualViewport) {
    const visualViewport = window.visualViewport;
    const bottomControls = document.querySelector('.bottom-controls');
    const toggleBar = document.querySelector('.prompt-toggle-bar');
    const modulePopup = document.querySelector('.module-popup');
    let fullHeight = visualViewport.height;

    function syncKeyboardPositions() {
      if (modulePopup) {
        modulePopup.style.top = visualViewport.offsetTop + 'px';
        modulePopup.style.bottom = 'auto';
        modulePopup.style.maxHeight = visualViewport.height + 'px';
      }
      relayoutFloatingPanels();
      const tagTooltip = getTagTooltip();
      if (tagTooltip) {
        tagTooltip.style.top = (visualViewport.offsetTop + 4) + 'px';
        tagTooltip.style.maxHeight = Math.min(visualViewport.height * 0.4, 200) + 'px';
      }
    }

    visualViewport.addEventListener('resize', () => {
      if (isPC.matches) return;
      const shrink = fullHeight - visualViewport.height;
      keyboardOpen = shrink > 100;
      if (keyboardOpen) {
        bottomControls.classList.add('kb-open');
        toggleBar.style.display = 'none';
        syncKeyboardPositions();
      } else {
        fullHeight = visualViewport.height;
        bottomControls.classList.remove('kb-open');
        toggleBar.style.display = '';
        if (modulePopup) {
          modulePopup.style.top = '';
          modulePopup.style.bottom = '';
          modulePopup.style.maxHeight = '';
        }
        relayoutFloatingPanels();
        const tagTooltip = getTagTooltip();
        if (tagTooltip) {
          tagTooltip.style.top = '';
          tagTooltip.style.maxHeight = '';
        }
      }
    });

    visualViewport.addEventListener('scroll', () => {
      if (keyboardOpen) syncKeyboardPositions();
    });
  }

  window.addEventListener('resize', () => {
    relayoutFloatingPanels();
  });

  function isKeyboardOpen() {
    return keyboardOpen;
  }

  return {
    isKeyboardOpen,
  };
}
