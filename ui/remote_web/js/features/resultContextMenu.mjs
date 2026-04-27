const MAIN_IMAGE_MENU = [
  {label: '프롬프트 불러오기'},
  {label: '프롬프트 다시개봉'},
  {type: 'separator'},
  {label: '생성 설정 복원'},
  {label: '전체 메타데이터 보기'},
  {type: 'separator'},
  {label: '이미지 붙여넣기'},
  {type: 'separator'},
  {label: '파일 위치 열기'},
  {label: '이미지 저장'},
  {label: 'PNG로 클립보드 복사'},
  {label: 'WEBP로 클립보드 복사'},
  {type: 'separator'},
  {label: 'NAI 2x 업스케일'},
  {
    label: 'NAI 인페인트 메뉴',
    children: [
      {label: 'Send to img2img'},
      {label: 'Send to Inpaint'},
      {label: 'Instant Outpaint Request'},
      {label: 'Send to Outpainting'},
      {label: 'Use as outpainting base'},
    ],
  },
  {label: 'Send to Character Reference'},
  {type: 'separator'},
  {label: '리모트에 이벤트 저장'},
];

const THUMBNAIL_MENU = [
  {label: '프롬프트 불러오기'},
  {label: '프롬프트 다시개봉'},
  {type: 'separator'},
  {
    label: '큐 앞에 추가',
    children: [
      {label: '원본 프롬프트 유지'},
      {label: '현재 UI 프롬프트 반영'},
    ],
  },
  {
    label: '큐 뒤에 추가',
    children: [
      {label: '원본 프롬프트 유지'},
      {label: '현재 UI 프롬프트 반영'},
    ],
  },
  {type: 'separator'},
  {label: '생성 설정 복원'},
  {label: '전체 메타데이터 보기'},
  {label: 'PNG로 클립보드 복사'},
  {label: 'WEBP로 클립보드 복사'},
  {type: 'separator'},
  {label: 'NAI 2x 업스케일'},
  {type: 'separator'},
  {label: '리모트에 이벤트 저장'},
  {type: 'separator'},
  {label: '이미지 삭제', danger: true},
];

export function createResultContextMenu({
  document,
  window,
}) {
  let menu = null;

  function close() {
    if (!menu) return;
    menu.remove();
    menu = null;
  }

  function renderItem(item) {
    if (item.type === 'separator') {
      return '<div class="result-context-separator"></div>';
    }
    const danger = item.danger ? ' danger' : '';
    const childHtml = item.children
      ? `<div class="result-context-children">${item.children.map(renderItem).join('')}</div>`
      : '';
    return `
      <div class="result-context-group">
        <button type="button" class="result-context-item${danger}" disabled aria-disabled="true">
          <span>${item.label}</span>${item.children ? '<span class="result-context-arrow">›</span>' : ''}
        </button>
        ${childHtml}
      </div>`;
  }

  function positionMenu(x, y) {
    if (!menu) return;
    const rect = menu.getBoundingClientRect();
    const left = Math.max(8, Math.min(x, window.innerWidth - rect.width - 8));
    const top = Math.max(8, Math.min(y, window.innerHeight - rect.height - 8));
    menu.style.left = `${Math.round(left)}px`;
    menu.style.top = `${Math.round(top)}px`;
  }

  function open(kind, x, y) {
    close();
    const items = kind === 'thumbnail' ? THUMBNAIL_MENU : MAIN_IMAGE_MENU;
    menu = document.createElement('div');
    menu.className = `result-context-menu ${kind === 'thumbnail' ? 'thumbnail' : 'image-plane'}`;
    menu.innerHTML = items.map(renderItem).join('');
    document.body.appendChild(menu);
    menu.classList.add('open');
    positionMenu(x, y);
  }

  function isPreviewVisible(preview) {
    return preview && preview.classList.contains('show') && preview.getAttribute('src');
  }

  function onContextMenu(event) {
    const target = event.target;
    if (!target || !(target instanceof window.Element)) return;

    const thumb = target.closest('.viewer-thumb');
    if (thumb) {
      event.preventDefault();
      open('thumbnail', event.clientX, event.clientY);
      return;
    }

    if (target.closest('.stats-island, .viewer-panel, .right-tab-bar')) {
      return;
    }

    const preview = document.getElementById('preview');
    const imagePlaneTarget = target.closest('#preview, #viewerLightboxImg, .vp-preview, .viewer');
    if (imagePlaneTarget && isPreviewVisible(preview)) {
      event.preventDefault();
      open('image-plane', event.clientX, event.clientY);
    }
  }

  function bind() {
    document.addEventListener('contextmenu', onContextMenu);
    document.addEventListener('mousedown', event => {
      if (!menu) return;
      if (menu.contains(event.target)) return;
      close();
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape') close();
    });
    window.addEventListener('resize', close);
    window.addEventListener('scroll', close, true);
  }

  return {
    bind,
    close,
  };
}
