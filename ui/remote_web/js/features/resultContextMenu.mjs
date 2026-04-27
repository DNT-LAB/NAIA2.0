const ACTION_METADATA = 'show_metadata';

const MAIN_IMAGE_MENU = [
  {label: '프롬프트 불러오기'},
  {label: '프롬프트 다시개봉'},
  {type: 'separator'},
  {label: '생성 설정 복원'},
  {label: '전체 메타데이터 보기', action: ACTION_METADATA},
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
  {label: '전체 메타데이터 보기', action: ACTION_METADATA, requiresPath: true},
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
  fetch: fetchFn = window.fetch.bind(window),
  showToast = () => {},
  escHtml = defaultEscHtml,
}) {
  let menu = null;
  let metadataModal = null;

  function close() {
    if (!menu) return;
    menu.remove();
    menu = null;
  }

  function closeMetadataModal() {
    if (!metadataModal) return;
    metadataModal.remove();
    metadataModal = null;
  }

  function escapeText(value) {
    return escHtml(String(value ?? ''));
  }

  function renderItem(item, context) {
    if (item.type === 'separator') {
      return '<div class="result-context-separator"></div>';
    }
    const danger = item.danger ? ' danger' : '';
    const enabled = item.action === ACTION_METADATA && (!item.requiresPath || context.path || context.source === 'current');
    const disabledAttr = enabled ? '' : ' disabled aria-disabled="true"';
    const actionAttr = item.action ? ` data-action="${item.action}"` : '';
    const childHtml = item.children
      ? `<div class="result-context-children">${item.children.map(child => renderItem(child, context)).join('')}</div>`
      : '';
    return `
      <div class="result-context-group">
        <button type="button" class="result-context-item${danger}"${actionAttr}${disabledAttr}>
          <span>${escapeText(item.label)}</span>${item.children ? '<span class="result-context-arrow">›</span>' : ''}
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

  function bindActions(context) {
    if (!menu) return;
    menu.querySelectorAll('[data-action]').forEach(button => {
      button.addEventListener('click', event => {
        event.preventDefault();
        event.stopPropagation();
        if (button.disabled) return;
        const action = button.dataset.action;
        close();
        if (action === ACTION_METADATA) {
          showMetadata(context);
        }
      });
    });
  }

  function open(kind, x, y, context = {}) {
    close();
    const items = kind === 'thumbnail' ? THUMBNAIL_MENU : MAIN_IMAGE_MENU;
    menu = document.createElement('div');
    menu.className = `result-context-menu ${kind === 'thumbnail' ? 'thumbnail' : 'image-plane'}`;
    menu.innerHTML = items.map(item => renderItem(item, context)).join('');
    document.body.appendChild(menu);
    menu.classList.add('open');
    bindActions(context);
    positionMenu(x, y);
  }

  function isPreviewVisible(preview) {
    return preview && preview.classList.contains('show') && preview.getAttribute('src');
  }

  function extractViewerPathFromSrc(src) {
    if (!src) return '';
    try {
      const url = new URL(src, window.location.href);
      const prefix = '/api/viewer/image/';
      if (!url.pathname.startsWith(prefix)) return '';
      return decodeURI(url.pathname.slice(prefix.length));
    } catch (error) {
      return '';
    }
  }

  function getImagePlanePath(target) {
    const sourceImage = target.closest('#preview, #viewerLightboxImg, #vpPreview');
    if (sourceImage && sourceImage.getAttribute('src')) {
      return extractViewerPathFromSrc(sourceImage.getAttribute('src'));
    }
    const preview = document.getElementById('preview');
    return preview ? extractViewerPathFromSrc(preview.getAttribute('src')) : '';
  }

  async function showMetadata(context) {
    const path = context && context.path ? context.path : '';
    const useCurrent = !path && context && context.source === 'current';
    if (!path && !useCurrent) {
      showToast('No image is selected', 'error');
      return;
    }
    try {
      const url = path
        ? '/api/viewer/meta/' + encodeURI(path) + '?full=1'
        : '/api/result/metadata';
      const response = await fetchFn(url);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      openMetadataModal(path || 'Current Result', data);
    } catch (error) {
      console.error('Failed to load image metadata', error);
      showToast('Failed to load metadata', 'error');
    }
  }

  function openMetadataModal(path, data) {
    closeMetadataModal();
    const raw = data && typeof data === 'object' && 'raw' in data ? data.raw : data;
    const summary = data && typeof data === 'object' && 'summary' in data ? data.summary : {};
    const hasRaw = raw && (typeof raw !== 'object' || Object.keys(raw).length > 0);
    const rawText = hasRaw
      ? (typeof raw === 'string' ? raw : JSON.stringify(raw, null, 2))
      : '메타데이터가 없습니다.';
    const summaryRows = summary && typeof summary === 'object'
      ? Object.entries(summary).map(([key, value]) => `
        <div class="result-metadata-row">
          <div class="result-metadata-key">${escapeText(key)}</div>
          <div class="result-metadata-value">${escapeText(formatMetadataValue(value))}</div>
        </div>`).join('')
      : '';

    metadataModal = document.createElement('div');
    metadataModal.className = 'result-metadata-modal';
    metadataModal.innerHTML = `
      <div class="result-metadata-backdrop" data-close="metadata"></div>
      <section class="result-metadata-dialog" role="dialog" aria-modal="true" aria-label="Image metadata">
        <header class="result-metadata-header">
          <div>
            <div class="result-metadata-title">전체 메타데이터</div>
            <div class="result-metadata-path">${escapeText(path)}</div>
          </div>
          <button type="button" class="result-metadata-close" data-close="metadata" aria-label="Close">×</button>
        </header>
        ${summaryRows ? `<div class="result-metadata-summary">${summaryRows}</div>` : ''}
        <pre class="result-metadata-raw">${escapeText(rawText)}</pre>
      </section>`;
    document.body.appendChild(metadataModal);
    metadataModal.addEventListener('click', event => {
      if (!(event.target instanceof window.Element)) return;
      if (event.target.closest('[data-close="metadata"]')) {
        closeMetadataModal();
      }
    });
  }

  function formatMetadataValue(value) {
    if (value == null) return '';
    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
      return value;
    }
    return JSON.stringify(value);
  }

  function onContextMenu(event) {
    const target = event.target;
    if (!target || !(target instanceof window.Element)) return;

    const thumb = target.closest('.viewer-thumb');
    if (thumb) {
      event.preventDefault();
      open('thumbnail', event.clientX, event.clientY, {path: thumb.dataset.path || ''});
      return;
    }

    if (target.closest('.stats-island, .viewer-panel, .right-tab-bar')) {
      return;
    }

    const preview = document.getElementById('preview');
    const imagePlaneTarget = target.closest('#preview, #viewerLightboxImg, .vp-preview, .viewer');
    if (imagePlaneTarget && isPreviewVisible(preview)) {
      event.preventDefault();
      const path = getImagePlanePath(target);
      open('image-plane', event.clientX, event.clientY, {path, source: path ? 'saved' : 'current'});
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
      if (event.key === 'Escape') {
        close();
        closeMetadataModal();
      }
    });
    window.addEventListener('resize', close);
    window.addEventListener('scroll', close, true);
  }

  return {
    bind,
    close,
  };
}

function defaultEscHtml(value) {
  return String(value).replace(/[&<>"']/g, char => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  })[char]);
}
