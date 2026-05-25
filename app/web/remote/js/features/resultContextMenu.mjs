const ACTION_METADATA = 'show_metadata';
const ACTION_PASTE_IMAGE = 'paste_image';
const ACTION_IMAGE_ACTION = 'image_action';
const ACTION_LOAD_PROMPT = 'load_prompt';
const ACTION_REROLL_PROMPT = 'reroll_prompt';
const ACTION_QUEUE_RESULT = 'queue_result';
const ACTION_RESTORE_PARAMS = 'restore_params';
const ACTION_OPEN_LOCATION = 'open_location';
const ACTION_SAVE_IMAGE = 'save_image';
const ACTION_COPY_IMAGE = 'copy_image';
const ACTION_UPSCALE_NAI = 'upscale_nai';
const ACTION_METADATA_DETACHED = 'show_metadata_detached';
const ACTION_WEBUI_ENHANCE = 'webui_enhance';

const DEFAULT_CAPABILITIES = {
  load_prompt: false,
  reroll: false,
  queue: false,
  restore_params: false,
  metadata: false,
  paste_image: true,
  image_action: false,
  open_file: false,
  save_image: false,
  copy_png: false,
  enhance: false,
  upscale_nai: false,
  inpaint: false,
  character_reference: false,
  remote_event: false,
  delete: false,
};

const MAIN_IMAGE_ACTIONS = [
  {label: '이미지 붙여넣기', action: ACTION_PASTE_IMAGE, alwaysEnabled: true},
  {label: '이미지 저장', action: ACTION_SAVE_IMAGE, capability: 'save_image'},
  {label: '클립보드 복사', action: ACTION_COPY_IMAGE, capability: 'copy_png', copyFormat: 'png', badge: 'PNG', badgeTone: 'blue'},
  {type: 'separator'},
];

const THUMBNAIL_IMAGE_ACTIONS = [
  {label: '이미지 저장', action: ACTION_SAVE_IMAGE, capability: 'save_image'},
  {label: '클립보드 복사', action: ACTION_COPY_IMAGE, capability: 'copy_png', copyFormat: 'png', badge: 'PNG', badgeTone: 'blue'},
  {type: 'separator'},
];

const MAIN_IMAGE_MENU = [
  ...MAIN_IMAGE_ACTIONS,
  {label: '프롬프트 불러오기', action: ACTION_LOAD_PROMPT, capability: 'load_prompt'},
  {label: '프롬프트 다시개봉', action: ACTION_REROLL_PROMPT, capability: 'reroll'},
  {label: 'WEBUI Enhance', action: ACTION_WEBUI_ENHANCE, capability: 'enhance', modes: ['WEBUI']},
  {type: 'separator'},
  {
    label: '큐 앞에 추가',
    capability: 'queue',
    children: [
      {label: '원본 프롬프트 유지', action: ACTION_QUEUE_RESULT, capability: 'queue', queuePosition: 'front', queueMode: 'original'},
      {label: 'P.Eng / WC 재개봉', action: ACTION_QUEUE_RESULT, capability: 'reroll', queuePosition: 'front', queueMode: 'reopen'},
      {label: '현재 캐릭터로 재요청', action: ACTION_QUEUE_RESULT, capability: 'queue', queuePosition: 'front', queueMode: 'current_character', modes: ['NAI']},
    ],
  },
  {
    label: '큐 뒤에 추가',
    capability: 'queue',
    children: [
      {label: '원본 프롬프트 유지', action: ACTION_QUEUE_RESULT, capability: 'queue', queuePosition: 'back', queueMode: 'original'},
      {label: 'P.Eng / WC 재개봉', action: ACTION_QUEUE_RESULT, capability: 'reroll', queuePosition: 'back', queueMode: 'reopen'},
      {label: '현재 캐릭터로 재요청', action: ACTION_QUEUE_RESULT, capability: 'queue', queuePosition: 'back', queueMode: 'current_character', modes: ['NAI']},
    ],
  },
  {type: 'separator'},
  {label: '생성 설정 복원', action: ACTION_RESTORE_PARAMS, capability: 'restore_params'},
  {
    label: '메타데이터',
    capability: 'metadata',
    children: [
      {label: '탭에서 보기', action: ACTION_METADATA},
      {label: '새 창으로 열기', action: ACTION_METADATA_DETACHED},
    ],
  },
  {type: 'separator'},
  {
    label: 'NAI 도구',
    modes: ['NAI'],
    children: [
      {label: 'NAI 2x 업스케일', action: ACTION_UPSCALE_NAI, capability: 'upscale_nai', modes: ['NAI']},
      {label: 'Send to img2img', action: ACTION_IMAGE_ACTION, imageAction: 'img2img', capability: 'image_action', desktopImg2Img: true, modes: ['NAI']},
      {label: 'Send to Inpaint', action: ACTION_IMAGE_ACTION, imageAction: 'inpaint', capability: 'inpaint', desktopImg2Img: true, modes: ['NAI']},
      {label: 'Instant Outpaint Request'},
      {label: 'Send to Outpainting'},
      {label: 'Use as outpainting base'},
      {label: 'Send to Character Reference'},
    ],
  },
  {type: 'separator'},
  {label: '리모트에 이벤트 저장'},
];

const THUMBNAIL_MENU = [
  ...THUMBNAIL_IMAGE_ACTIONS,
  {label: '프롬프트 불러오기', action: ACTION_LOAD_PROMPT, capability: 'load_prompt'},
  {label: '프롬프트 다시개봉', action: ACTION_REROLL_PROMPT, capability: 'reroll'},
  {label: 'WEBUI Enhance', action: ACTION_WEBUI_ENHANCE, capability: 'enhance', modes: ['WEBUI']},
  {type: 'separator'},
  {
    label: '큐 앞에 추가',
    capability: 'queue',
    children: [
      {label: '원본 프롬프트 유지', action: ACTION_QUEUE_RESULT, capability: 'queue', queuePosition: 'front', queueMode: 'original'},
      {label: 'P.Eng / WC 재개봉', action: ACTION_QUEUE_RESULT, capability: 'reroll', queuePosition: 'front', queueMode: 'reopen'},
      {label: '현재 캐릭터로 재요청', action: ACTION_QUEUE_RESULT, capability: 'queue', queuePosition: 'front', queueMode: 'current_character', modes: ['NAI']},
    ],
  },
  {
    label: '큐 뒤에 추가',
    capability: 'queue',
    children: [
      {label: '원본 프롬프트 유지', action: ACTION_QUEUE_RESULT, capability: 'queue', queuePosition: 'back', queueMode: 'original'},
      {label: 'P.Eng / WC 재개봉', action: ACTION_QUEUE_RESULT, capability: 'reroll', queuePosition: 'back', queueMode: 'reopen'},
      {label: '현재 캐릭터로 재요청', action: ACTION_QUEUE_RESULT, capability: 'queue', queuePosition: 'back', queueMode: 'current_character', modes: ['NAI']},
    ],
  },
  {type: 'separator'},
  {label: '생성 설정 복원', action: ACTION_RESTORE_PARAMS, capability: 'restore_params'},
  {
    label: '메타데이터',
    capability: 'metadata',
    children: [
      {label: '탭에서 보기', action: ACTION_METADATA, requiresPath: true},
      {label: '새 창으로 열기', action: ACTION_METADATA_DETACHED, requiresPath: true},
    ],
  },
  {
    label: 'NAI 도구',
    modes: ['NAI'],
    children: [
      {label: 'NAI 2x 업스케일', action: ACTION_UPSCALE_NAI, capability: 'upscale_nai', modes: ['NAI']},
      {label: 'Send to img2img', action: ACTION_IMAGE_ACTION, imageAction: 'img2img', capability: 'image_action', desktopImg2Img: true, modes: ['NAI']},
    ],
  },
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
  onPasteImage = () => {},
  onShowMetadata = null,
  onShowMetadataDetached = null,
  onImageAction = null,
  onLoadPrompt = null,
  onRerollPrompt = null,
  onQueueResult = null,
  onRestoreSettings = null,
  onOpenLocation = null,
  onSaveImage = null,
  onCopyImage = null,
  onUpscaleNai = null,
  onWebUiEnhance = null,
  getMode = () => '',
  getCurrentSavedPath = () => '',
  canUseDesktopImg2Img = () => true,
}) {
  let menu = null;
  let metadataModal = null;
  let menuVersion = 0;
  const submenuCloseTimers = new WeakMap();

  function isTouchMenu() {
    const mediaQuery = window.matchMedia?.('(hover: none), (pointer: coarse)');
    return Boolean(mediaQuery?.matches) || window.innerWidth <= 720;
  }

  function syncMenuMode() {
    if (!menu) return;
    const touch = isTouchMenu();
    menu.classList.toggle('touch-mode', touch);
    menu.classList.toggle('flyout-mode', !touch);
  }

  function close() {
    if (!menu) return;
    menuVersion += 1;
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

  function hasCapability(context, key) {
    return Boolean(context?.capabilities?.[key]);
  }

  function currentMode() {
    return String(getMode() || '').toUpperCase();
  }

  function itemModeAllowed(item) {
    return !item.modes || item.modes.includes(currentMode());
  }

  function isItemEnabled(item, context) {
    if (!itemModeAllowed(item)) return false;
    if (item.desktopImg2Img && !(typeof canUseDesktopImg2Img === 'function' && canUseDesktopImg2Img())) return false;
    if (item.alwaysEnabled) return true;
    if (item.requiresPath && !context?.path) return false;
    if (item.children) {
      return item.children.some(child => isItemEnabled(child, context));
    }
    if (item.capability && !hasCapability(context, item.capability)) return false;
    if (item.action === ACTION_LOAD_PROMPT) {
      return typeof onLoadPrompt === 'function';
    }
    if (item.action === ACTION_REROLL_PROMPT) {
      return typeof onRerollPrompt === 'function';
    }
    if (item.action === ACTION_QUEUE_RESULT) {
      return typeof onQueueResult === 'function' && hasCapability(context, 'queue');
    }
    if (item.action === ACTION_RESTORE_PARAMS) {
      return typeof onRestoreSettings === 'function';
    }
    if (item.action === ACTION_METADATA) {
      return hasCapability(context, 'metadata');
    }
    if (item.action === ACTION_METADATA_DETACHED) {
      return typeof onShowMetadataDetached === 'function' && hasCapability(context, 'metadata');
    }
    if (item.action === ACTION_PASTE_IMAGE) {
      return hasCapability(context, 'paste_image');
    }
    if (item.action === ACTION_OPEN_LOCATION) {
      return typeof onOpenLocation === 'function';
    }
    if (item.action === ACTION_SAVE_IMAGE) {
      return typeof onSaveImage === 'function';
    }
    if (item.action === ACTION_COPY_IMAGE) {
      return typeof onCopyImage === 'function';
    }
    if (item.action === ACTION_UPSCALE_NAI) {
      return typeof onUpscaleNai === 'function';
    }
    if (item.action === ACTION_WEBUI_ENHANCE) {
      return typeof onWebUiEnhance === 'function';
    }
    if (item.action === ACTION_IMAGE_ACTION) {
      if (!hasCapability(context, 'image_action')) return false;
      return typeof onImageAction === 'function';
    }
    return false;
  }

  function renderItem(item, context) {
    if (!itemModeAllowed(item)) {
      return '';
    }
    if (item.desktopImg2Img && !(typeof canUseDesktopImg2Img === 'function' && canUseDesktopImg2Img())) {
      return '';
    }
    if (item.type === 'separator') {
      return '<div class="result-context-separator"></div>';
    }
    const hasChildren = Array.isArray(item.children) && item.children.length > 0;
    const danger = item.danger ? ' danger' : '';
    const enabled = isItemEnabled(item, context);
    const disabledAttr = enabled ? '' : ' disabled aria-disabled="true"';
    const actionAttr = item.action ? ` data-action="${item.action}"` : '';
    const imageActionAttr = item.imageAction ? ` data-image-action="${item.imageAction}"` : '';
    const copyFormatAttr = item.copyFormat ? ` data-copy-format="${item.copyFormat}"` : '';
    const queuePositionAttr = item.queuePosition ? ` data-queue-position="${item.queuePosition}"` : '';
    const queueModeAttr = item.queueMode ? ` data-queue-mode="${item.queueMode}"` : '';
    const submenuAttr = hasChildren ? ' data-submenu-trigger="true" aria-haspopup="menu" aria-expanded="false"' : '';
    const badgeClass = item.badgeTone ? ` ${item.badgeTone}` : '';
    const badgeHtml = item.badge
      ? `<span class="result-context-badge${badgeClass}">${escapeText(item.badge)}</span>`
      : '';
    const childHtml = hasChildren
      ? `<div class="result-context-children" role="menu">${item.children.map(child => renderItem(child, context)).join('')}</div>`
      : '';
    return `
      <div class="result-context-group${hasChildren ? ' has-children' : ''}">
        <button type="button" class="result-context-item${danger}${hasChildren ? ' has-children' : ''}"${actionAttr}${imageActionAttr}${copyFormatAttr}${queuePositionAttr}${queueModeAttr}${submenuAttr}${disabledAttr}>
          <span>${escapeText(item.label)}</span><span class="result-context-item-tail">${badgeHtml}${hasChildren ? '<span class="result-context-arrow" aria-hidden="true">›</span>' : ''}</span>
        </button>
        ${childHtml}
      </div>`;
  }

  function renderMenu(kind, context) {
    if (!menu) return;
    syncMenuMode();
    const items = kind === 'thumbnail' ? THUMBNAIL_MENU : MAIN_IMAGE_MENU;
    menu.innerHTML = items.map(item => renderItem(item, context)).join('');
    bindActions(context);
  }

  function positionMenu(x, y) {
    if (!menu) return;
    const rect = menu.getBoundingClientRect();
    const left = Math.max(8, Math.min(x, window.innerWidth - rect.width - 8));
    const top = Math.max(8, Math.min(y, window.innerHeight - rect.height - 8));
    menu.style.left = `${Math.round(left)}px`;
    menu.style.top = `${Math.round(top)}px`;
    positionOpenSubmenus();
  }

  function getDirectChild(parent, selector) {
    try {
      return parent.querySelector(`:scope > ${selector}`);
    } catch (error) {
      return Array.from(parent.children).find(child => child.matches(selector)) || null;
    }
  }

  function clearSubmenuCloseTimer(group) {
    const timer = submenuCloseTimers.get(group);
    if (!timer) return;
    window.clearTimeout(timer);
    submenuCloseTimers.delete(group);
  }

  function scheduleSubmenuClose(group) {
    if (!group || isTouchMenu()) return;
    clearSubmenuCloseTimer(group);
    const version = menuVersion;
    const timer = window.setTimeout(() => {
      submenuCloseTimers.delete(group);
      if (!menu || version !== menuVersion) return;
      const childMenu = getDirectChild(group, '.result-context-children');
      if (group.matches(':hover') || childMenu?.matches(':hover')) return;
      closeSubmenu(group);
    }, 180);
    submenuCloseTimers.set(group, timer);
  }

  function closeSiblingSubmenus(group) {
    const parent = group.parentElement;
    if (!parent) return;
    Array.from(parent.children).forEach(child => {
      if (child !== group && child.classList?.contains('submenu-open')) {
        closeSubmenu(child);
      }
    });
  }

  function closeSubmenu(group) {
    clearSubmenuCloseTimer(group);
    group.classList.remove('submenu-open');
    const trigger = getDirectChild(group, '.result-context-item');
    const childMenu = getDirectChild(group, '.result-context-children');
    trigger?.setAttribute('aria-expanded', 'false');
    if (childMenu) {
      childMenu.style.left = '';
      childMenu.style.top = '';
    }
    group.querySelectorAll('.result-context-group.submenu-open').forEach(closeSubmenu);
  }

  function openSubmenu(group) {
    if (!group || !menu) return;
    clearSubmenuCloseTimer(group);
    closeSiblingSubmenus(group);
    group.classList.add('submenu-open');
    getDirectChild(group, '.result-context-item')?.setAttribute('aria-expanded', 'true');
    if (!isTouchMenu()) {
      positionSubmenu(group);
    }
  }

  function toggleTouchSubmenu(group) {
    if (!group) return;
    if (group.classList.contains('submenu-open')) {
      closeSubmenu(group);
    } else {
      openSubmenu(group);
    }
  }

  function positionOpenSubmenus() {
    if (!menu || isTouchMenu()) return;
    menu.querySelectorAll('.result-context-group.submenu-open').forEach(positionSubmenu);
  }

  function positionSubmenu(group) {
    const trigger = getDirectChild(group, '.result-context-item');
    const childMenu = getDirectChild(group, '.result-context-children');
    if (!trigger || !childMenu) return;

    childMenu.style.visibility = 'hidden';
    childMenu.style.display = 'grid';
    const triggerRect = trigger.getBoundingClientRect();
    const parentMenuRect = (group.parentElement || menu).getBoundingClientRect();
    const childRect = childMenu.getBoundingClientRect();
    const overlap = 1;
    const margin = 8;
    const rightLeft = parentMenuRect.right - overlap;
    const fitsRight = rightLeft + childRect.width <= window.innerWidth - margin;
    const left = fitsRight
      ? rightLeft
      : Math.max(margin, parentMenuRect.left - childRect.width + overlap);
    const top = Math.max(margin, Math.min(triggerRect.top, window.innerHeight - childRect.height - margin));
    childMenu.style.left = `${Math.round(left)}px`;
    childMenu.style.top = `${Math.round(top)}px`;
    childMenu.classList.toggle('flyout-left', !fitsRight);
    childMenu.style.visibility = '';
    childMenu.style.display = '';
  }

  function bindActions(context) {
    if (!menu) return;
    menu.querySelectorAll('[data-submenu-trigger]').forEach(button => {
      const group = button.closest('.result-context-group');
      button.addEventListener('click', event => {
        if (!isTouchMenu()) return;
        event.preventDefault();
        event.stopPropagation();
        if (button.disabled) return;
        toggleTouchSubmenu(group);
      });
      button.addEventListener('mouseenter', () => {
        clearSubmenuCloseTimer(group);
        if (!button.disabled && !isTouchMenu()) openSubmenu(group);
      });
      button.addEventListener('focus', () => {
        clearSubmenuCloseTimer(group);
        if (!button.disabled && !isTouchMenu()) openSubmenu(group);
      });
    });
    menu.querySelectorAll('.result-context-group.has-children').forEach(group => {
      const childMenu = getDirectChild(group, '.result-context-children');
      group.addEventListener('mouseenter', () => clearSubmenuCloseTimer(group));
      group.addEventListener('mouseleave', () => {
        scheduleSubmenuClose(group);
      });
      childMenu?.addEventListener('mouseenter', () => clearSubmenuCloseTimer(group));
      childMenu?.addEventListener('mouseleave', () => scheduleSubmenuClose(group));
    });
    menu.querySelectorAll('[data-action]').forEach(button => {
      button.addEventListener('click', event => {
        event.preventDefault();
        event.stopPropagation();
        if (button.disabled) return;
        const action = button.dataset.action;
        close();
        if (action === ACTION_LOAD_PROMPT) {
          onLoadPrompt(context);
        } else if (action === ACTION_REROLL_PROMPT) {
          onRerollPrompt(context);
        } else if (action === ACTION_QUEUE_RESULT) {
          onQueueResult(context, {
            position: button.dataset.queuePosition || 'back',
            mode: button.dataset.queueMode || 'original',
          });
        } else if (action === ACTION_RESTORE_PARAMS) {
          onRestoreSettings(context);
        } else if (action === ACTION_METADATA) {
          if (typeof onShowMetadata === 'function' && onShowMetadata(context) !== false) return;
          showMetadata(context);
        } else if (action === ACTION_METADATA_DETACHED) {
          if (typeof onShowMetadataDetached === 'function') onShowMetadataDetached(context);
        } else if (action === ACTION_PASTE_IMAGE) {
          onPasteImage();
        } else if (action === ACTION_OPEN_LOCATION) {
          onOpenLocation(context);
        } else if (action === ACTION_SAVE_IMAGE) {
          onSaveImage(context);
        } else if (action === ACTION_COPY_IMAGE) {
          onCopyImage(context, button.dataset.copyFormat || 'png');
        } else if (action === ACTION_UPSCALE_NAI) {
          onUpscaleNai(context);
        } else if (action === ACTION_WEBUI_ENHANCE) {
          onWebUiEnhance(context);
        } else if (action === ACTION_IMAGE_ACTION) {
          onImageAction(context, button.dataset.imageAction || '');
        }
      });
    });
  }

  function open(kind, x, y, context = {}) {
    close();
    const version = ++menuVersion;
    menu = document.createElement('div');
    menu.className = `result-context-menu ${kind === 'thumbnail' ? 'thumbnail' : 'image-plane'}`;
    renderMenu(kind, context);
    document.body.appendChild(menu);
    menu.classList.add('open');
    positionMenu(x, y);
    refreshAssetContext(kind, context, version, x, y);
  }

  function isPreviewVisible(preview) {
    return preview && preview.classList.contains('show') && preview.getAttribute('src');
  }

  function viewerMetaUrl(path, full = false) {
    const params = new URLSearchParams({path: String(path || '')});
    if (full) params.set('full', '1');
    return '/api/viewer/meta?' + params.toString();
  }

  function extractViewerPathFromSrc(src) {
    if (!src) return '';
    try {
      const url = new URL(src, window.location.href);
      const prefix = '/api/viewer/image/';
      if (!url.pathname.startsWith(prefix)) return '';
      return decodeURIComponent(url.pathname.slice(prefix.length));
    } catch (error) {
      return '';
    }
  }

  function getSourceImageFromTarget(target) {
    const sourceImage = target.closest('#preview, #viewerLightboxImg, #vpPreview, .vp-preview');
    if (sourceImage && sourceImage.getAttribute('src')) return sourceImage;
    return null;
  }

  function isElementVisible(element) {
    if (!element || !element.getClientRects().length) return false;
    const style = window.getComputedStyle(element);
    return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
  }

  function hasVisibleImage(image) {
    if (!image || !image.getAttribute('src')) return false;
    if (image.id === 'preview') return isPreviewVisible(image);
    return isElementVisible(image);
  }

  function getImagePlanePath(sourceImage) {
    if (sourceImage && sourceImage.getAttribute('src')) {
      if (sourceImage.dataset && sourceImage.dataset.source === 'saved' && sourceImage.dataset.path) {
        return sourceImage.dataset.path;
      }
      const pathFromSrc = extractViewerPathFromSrc(sourceImage.getAttribute('src'));
      if (pathFromSrc) return pathFromSrc;
      if (sourceImage.id === 'preview' && sourceImage.dataset?.source === 'current') {
        return String(getCurrentSavedPath() || '');
      }
      return '';
    }
    const preview = document.getElementById('preview');
    if (preview && preview.dataset && preview.dataset.source === 'saved' && preview.dataset.path) {
      return preview.dataset.path;
    }
    const pathFromPreview = preview ? extractViewerPathFromSrc(preview.getAttribute('src')) : '';
    if (pathFromPreview) return pathFromPreview;
    if (preview?.dataset?.source === 'current') return String(getCurrentSavedPath() || '');
    return '';
  }

  function buildContext(source, path = '', hasImage = false, imageSrc = '') {
    const isCurrent = source === 'current';
    const isSaved = source === 'saved';
    const isInput = source === 'input';
    const metadataAvailable = hasImage && isSaved;
    const naiMode = currentMode() === 'NAI';
    const canUseNaiImageAction = hasImage && !isSaved && naiMode;
    return {
      id: isSaved && path ? `saved:${path}` : source,
      source,
      path,
      imageSrc,
      hasImage,
      hasMetadata: metadataAvailable,
      capabilities: {
        ...DEFAULT_CAPABILITIES,
        metadata: metadataAvailable,
        paste_image: true,
        image_action: canUseNaiImageAction,
        inpaint: canUseNaiImageAction,
        copy_png: hasImage,
        open_file: false,
        save_image: (isCurrent || isSaved) && hasImage,
      },
    };
  }

  function assetUrlForContext(context) {
    if (!context || !context.hasImage) return '';
    if (context.source === 'saved' && context.path) {
      const params = new URLSearchParams({path: context.path});
      return '/api/result/asset/saved?' + params.toString();
    }
    if (context.source === 'current') {
      return '/api/result/asset/current';
    }
    return '';
  }

  function mergeAssetContext(context, asset) {
    if (!asset || typeof asset !== 'object') return context;
    const capabilities = {
      ...DEFAULT_CAPABILITIES,
      ...(context.capabilities || {}),
      ...(asset.capabilities || {}),
    };
    if ('has_metadata' in asset || 'hasMetadata' in asset) {
      capabilities.metadata = Boolean(asset.has_metadata ?? asset.hasMetadata);
    }
    return {
      ...context,
      id: asset.id ?? context.id,
      source: asset.source ?? context.source,
      path: asset.path ?? context.path,
      filePath: asset.file_path ?? context.filePath,
      label: asset.label ?? context.label,
      metadataUrl: asset.metadata_url ?? asset.metadataUrl,
      imageSrc: asset.image_url ?? asset.imageUrl ?? context.imageSrc,
      hasImage: Boolean(asset.has_image ?? asset.hasImage ?? context.hasImage),
      hasMetadata: Boolean(asset.has_metadata ?? asset.hasMetadata ?? context.hasMetadata),
      can_enhance: Boolean(asset.can_enhance ?? asset.canEnhance ?? capabilities.enhance ?? context.can_enhance ?? context.canEnhance),
      capabilities,
    };
  }

  async function refreshAssetContext(kind, context, version, x, y) {
    const url = assetUrlForContext(context);
    if (!url) return;
    try {
      const response = await fetchFn(url);
      if (!response.ok) return;
      const asset = await response.json();
      if (!menu || version !== menuVersion) return;
      const mergedContext = mergeAssetContext(context, asset);
      renderMenu(kind, mergedContext);
      positionMenu(x, y);
    } catch (error) {
      console.warn('Failed to resolve result asset context', error);
    }
  }

  function buildThumbnailContext(thumb) {
    const path = thumb.dataset.path || '';
    const imageSrc = path ? '/api/viewer/image/' + encodeURI(path) : (thumb.getAttribute('src') || '');
    const context = buildContext('saved', path, true, imageSrc);
    context.capabilities.image_action = false;
    return context;
  }

  function buildImagePlaneContext(target) {
    const preview = document.getElementById('preview');
    const sourceImage = getSourceImageFromTarget(target);
    const image = sourceImage || preview;
    const hasImage = hasVisibleImage(image);
    if (!hasImage) return buildContext('empty', '', false);

    const datasetSource = image?.dataset ? image.dataset.source : '';
    const path = datasetSource === 'current' ? '' : getImagePlanePath(image);
    const source = path
      ? 'saved'
      : (datasetSource === 'input' ? 'input' : 'current');
    return buildContext(source, path, true, image.getAttribute('src') || '');
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
        ? viewerMetaUrl(path, true)
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
      open('thumbnail', event.clientX, event.clientY, buildThumbnailContext(thumb));
      return;
    }

    if (target.closest('.stats-island, .viewer-panel, .right-tab-bar')) {
      return;
    }

    const imagePlaneTarget = target.closest('#preview, #viewerLightboxImg, .vp-preview, .viewer');
    if (imagePlaneTarget) {
      event.preventDefault();
      open('image-plane', event.clientX, event.clientY, buildImagePlaneContext(target));
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
