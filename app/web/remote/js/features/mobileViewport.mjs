export function createMobileViewportController({
  window,
  document,
  isPC,
  relayoutFloatingPanels,
  positionTagTooltip = () => {},
  getTagTooltip,
}) {
  let keyboardOpen = false;

  if (window.visualViewport) {
    const visualViewport = window.visualViewport;
    const bottomControls = document.querySelector('.bottom-controls');
    const toggleBar = document.querySelector('.prompt-toggle-bar');
    const modulePopup = document.querySelector('.module-popup');

    function syncKeyboardPositions() {
      if (modulePopup) {
        modulePopup.style.top = visualViewport.offsetTop + 'px';
        modulePopup.style.bottom = 'auto';
        modulePopup.style.maxHeight = visualViewport.height + 'px';
      }
      relayoutFloatingPanels();
      positionTagTooltip();
      const tagTooltip = getTagTooltip();
      if (tagTooltip) {
        tagTooltip.style.top = (visualViewport.offsetTop + 4) + 'px';
        tagTooltip.style.maxHeight = Math.min(visualViewport.height * 0.4, 200) + 'px';
      }
    }

    // "높이가 줄었다 = 키보드"는 핀치 줌·브라우저 줌·창 리사이즈·주소창
    // 등장에도 발화해 PROMPT/PARAMS/MODULES 토글바와 quick bar(kb-open)가
    // 간헐적으로 사라지는 버그가 있었다. 키보드는 편집 가능한 요소에
    // 포커스가 있을 때만 뜨므로 포커스를 필수 조건으로 건다.
    function isEditableFocused() {
      const el = document.activeElement;
      if (!el) return false;
      const tag = el.tagName;
      if (tag === 'TEXTAREA' || tag === 'INPUT' || tag === 'SELECT') return true;
      return !!el.isContentEditable;
    }

    function enterKeyboardMode() {
      keyboardOpen = true;
      if (bottomControls) bottomControls.classList.add('kb-open');
      if (toggleBar) toggleBar.style.display = 'none';
      syncKeyboardPositions();
    }

    function exitKeyboardMode() {
      keyboardOpen = false;
      if (bottomControls) bottomControls.classList.remove('kb-open');
      if (toggleBar) toggleBar.style.display = '';
      if (modulePopup) {
        modulePopup.style.top = '';
        modulePopup.style.bottom = '';
        modulePopup.style.maxHeight = '';
      }
      relayoutFloatingPanels();
      positionTagTooltip();
      const tagTooltip = getTagTooltip();
      if (tagTooltip) {
        tagTooltip.style.top = '';
        tagTooltip.style.maxHeight = '';
      }
    }

    // 키보드 크기 추정: 가상 키보드는 visualViewport.height만 줄이고
    // window.innerHeight(레이아웃 뷰포트)는 유지한다(iOS Safari·Chrome Android
    // 기본 resizes-visual). 회전/창 리사이즈/브라우저 줌은 둘을 함께 바꿔
    // 차이가 0에 가깝다 — 시점 기준(fullHeight) 추적이 필요 없어 스테일
    // 베이스라인 문제(회전·줌 직후 오판) 클래스가 통째로 사라진다.
    function keyboardShrink() {
      return Math.max(0, Number(window.innerHeight || 0) - Number(visualViewport.height || 0));
    }

    visualViewport.addEventListener('resize', () => {
      if (isPC.matches) {
        if (keyboardOpen) exitKeyboardMode();
        return;
      }
      // 핀치 줌(scale≠1) 중에는 vv.height가 줌 배율로 줄어든다 — 키보드 아님.
      const scale = Number(visualViewport.scale) || 1;
      if (Math.abs(scale - 1) > 0.05) {
        if (keyboardOpen) exitKeyboardMode();
        return;
      }
      if (keyboardShrink() > 100 && isEditableFocused()) {
        if (!keyboardOpen) enterKeyboardMode();
        else syncKeyboardPositions();
      } else if (keyboardOpen) {
        exitKeyboardMode();
      }
    });

    // 키보드가 resize 이벤트 없이(또는 그 전에) 내려가는 경우(완료 버튼,
    // 포커스 이동 등)에도 UI를 복원한다 — kb-open 고착 방지의 안전망.
    document.addEventListener('focusout', () => {
      window.setTimeout(() => {
        if (keyboardOpen && !isEditableFocused()) exitKeyboardMode();
      }, 80);
    });

    visualViewport.addEventListener('scroll', () => {
      if (keyboardOpen) syncKeyboardPositions();
    });
  }

  window.addEventListener('resize', () => {
    relayoutFloatingPanels();
    positionTagTooltip();
  });

  function isKeyboardOpen() {
    return keyboardOpen;
  }

  return {
    isKeyboardOpen,
  };
}
