const ACTION_METADATA = 'show_metadata';
const ACTION_SHOW_PAYLOAD = 'show_payload';     // 우측 팝업: 풀 페이로드를 읽기좋은 HTML로
const ACTION_SHOW_WILDCARDS = 'show_wildcards';  // 우측 팝업: 블록별 적용 와일드카드(없으면 숨김)
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
const ACTION_OUTPAINT = 'outpaint';
const ACTION_METADATA_DETACHED = 'show_metadata_detached';
const ACTION_WEBUI_ENHANCE = 'webui_enhance';
const ACTION_DELETE_RESULT = 'delete_result';
const ACTION_SET_DELETE_MODE = 'set_delete_mode';
const ACTION_GROK_I2I = 'grok_i2i'; // Grok 변형 (제거 가능)
const ACTION_GROK_I2V = 'grok_i2v'; // Grok 영상 (제거 가능)
const ACTION_DIRECTOR = 'nai_director_tool'; // NAI Director Tools (제거 가능)
const ACTION_SET_CHAR_REF = 'set_character_reference'; // 결과 이미지를 Character Reference 창에 할당
const ACTION_SET_VIBE = 'set_vibe_transfer';           // 결과 이미지를 Vibe Transfer 창에 할당
const ACTION_SAVE_CHAR_ASSET = 'save_character_asset'; // 결과 이미지를 캐릭터 에셋 라이브러리에 저장

const DEFAULT_CAPABILITIES = {
  load_prompt: false,
  reroll: false,
  queue: false,
  restore_params: false,
  metadata: false,
  has_wildcards: false,
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
  {label: '파일 위치 열기', action: ACTION_OPEN_LOCATION, capability: 'open_file'},
  {label: '이미지 저장', action: ACTION_SAVE_IMAGE, capability: 'save_image'},
  {label: '클립보드 복사', action: ACTION_COPY_IMAGE, capability: 'copy_png', copyFormat: 'png', badge: 'PNG', badgeTone: 'blue'},
  {type: 'separator'},
];

const THUMBNAIL_IMAGE_ACTIONS = [
  {label: '파일 위치 열기', action: ACTION_OPEN_LOCATION, capability: 'open_file'},
  {label: '이미지 저장', action: ACTION_SAVE_IMAGE, capability: 'save_image'},
  {label: '클립보드 복사', action: ACTION_COPY_IMAGE, capability: 'copy_png', copyFormat: 'png', badge: 'PNG', badgeTone: 'blue'},
  {type: 'separator'},
];

// 디스크 모드일 때 "이미지 삭제" 우측에 붙는 경고 라벨 (모드 전환 시 라이브로 추가/제거).
const DISK_BADGE_HTML = '<span class="result-context-badge danger" data-disk-badge="1">디스크</span>';

// 컨텍스트 메뉴 최하단 ⚙ 삭제 설정 — 삭제 모드(히스토리 전용 / 디스크 파일까지)를 고른다.
// children 인프라 재사용. 선택은 메뉴를 닫지 않고 active 표시만 갱신(아래 bindActions 특수 처리).
const DELETE_SETTINGS_MENU_ITEM = {
  label: '⚙ 삭제 설정',
  alwaysEnabled: true,
  children: [
    {label: '히스토리에서만 제거', action: ACTION_SET_DELETE_MODE, deleteMode: 'history', alwaysEnabled: true},
    {label: '디스크 파일까지 삭제', action: ACTION_SET_DELETE_MODE, deleteMode: 'disk', alwaysEnabled: true, danger: true},
  ],
};

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
      {label: '탭에서 보기', action: ACTION_METADATA, desktopTabOnly: true},
      {label: '새 창으로 열기', action: ACTION_METADATA_DETACHED},
    ],
  },
  {label: 'Payload 확인', action: ACTION_SHOW_PAYLOAD, capability: 'metadata'},
  {label: '와일드카드', action: ACTION_SHOW_WILDCARDS, capability: 'has_wildcards', hideWhenDisabled: true},
  {type: 'separator'},
  {
    label: 'NAI 도구',
    modes: ['NAI'],
    children: [
      {label: 'NAI 2x 업스케일', action: ACTION_UPSCALE_NAI, capability: 'upscale_nai', modes: ['NAI']},
      {label: 'Director Tools', action: ACTION_DIRECTOR, modes: ['NAI']},
      {label: 'Send to img2img', action: ACTION_IMAGE_ACTION, imageAction: 'img2img', capability: 'image_action', desktopImg2Img: true, modes: ['NAI']},
      {label: 'Send to Inpaint', action: ACTION_IMAGE_ACTION, imageAction: 'inpaint', capability: 'inpaint', desktopImg2Img: true, modes: ['NAI']},
      {label: 'Instant Outpaint Request', action: ACTION_OUTPAINT, capability: 'image_action', modes: ['NAI']},
      {label: 'Send to Outpainting'},
      {label: 'Use as outpainting base'},
      {label: 'Set as Character Reference', action: ACTION_SET_CHAR_REF, modes: ['NAI']},
      {label: 'Set as Vibe Transfer', action: ACTION_SET_VIBE, modes: ['NAI']},
      {label: '캐릭터 에셋으로 저장', action: ACTION_SAVE_CHAR_ASSET, modes: ['NAI']},
    ],
  },
  {type: 'separator'},
  {label: '리모트에 이벤트 저장'},
  {type: 'separator'},
  {label: 'Grok 변형 (I2I)', action: ACTION_GROK_I2I, grokGated: true},
  {label: 'Grok 영상 (I2V)', action: ACTION_GROK_I2V, grokGated: true},
  {type: 'separator'},
  {label: '이미지 삭제', action: ACTION_DELETE_RESULT, capability: 'delete', danger: true},
  DELETE_SETTINGS_MENU_ITEM,
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
      {label: '탭에서 보기', action: ACTION_METADATA, requiresPath: true, desktopTabOnly: true},
      {label: '새 창으로 열기', action: ACTION_METADATA_DETACHED, requiresPath: true},
    ],
  },
  {label: 'Payload 확인', action: ACTION_SHOW_PAYLOAD, capability: 'metadata'},
  {label: '와일드카드', action: ACTION_SHOW_WILDCARDS, capability: 'has_wildcards', hideWhenDisabled: true},
  {
    label: 'NAI 도구',
    modes: ['NAI'],
    children: [
      {label: 'NAI 2x 업스케일', action: ACTION_UPSCALE_NAI, capability: 'upscale_nai', modes: ['NAI']},
      {label: 'Director Tools', action: ACTION_DIRECTOR, modes: ['NAI']},
      {label: 'Send to img2img', action: ACTION_IMAGE_ACTION, imageAction: 'img2img', capability: 'image_action', desktopImg2Img: true, modes: ['NAI']},
      {label: 'Set as Character Reference', action: ACTION_SET_CHAR_REF, modes: ['NAI']},
      {label: 'Set as Vibe Transfer', action: ACTION_SET_VIBE, modes: ['NAI']},
      {label: '캐릭터 에셋으로 저장', action: ACTION_SAVE_CHAR_ASSET, modes: ['NAI']},
    ],
  },
  {type: 'separator'},
  {label: '리모트에 이벤트 저장'},
  {type: 'separator'},
  {label: 'Grok 변형 (I2I)', action: ACTION_GROK_I2I, grokGated: true},
  {label: 'Grok 영상 (I2V)', action: ACTION_GROK_I2V, grokGated: true},
  {type: 'separator'},
  {label: '이미지 삭제', action: ACTION_DELETE_RESULT, capability: 'delete', danger: true},
  DELETE_SETTINGS_MENU_ITEM,
];

export function buildCharacterFreezePayload({
  slot = '',
  slotLabel = '',
  rows = [],
  executedCharacters = [],
  executedUcs = [],
  executedIds = [],
} = {}) {
  const ids = Array.isArray(executedIds)
    ? executedIds.map(value => String(value || '')) : [];
  let index = ids.indexOf(String(slot || ''));
  if (index < 0 && slotLabel != null && String(slotLabel).trim()) {
    const parsed = Number.parseInt(String(slotLabel), 10);
    if (Number.isFinite(parsed) && parsed > 0) index = parsed - 1;
  }
  if (index < 0 || index >= executedCharacters.length) return null;
  const prompt = String(executedCharacters[index] || '').trim();
  if (!prompt) return null;

  // The selected result's prompt_context is the provenance boundary. Always
  // include an explicit components array (even empty) so the backend never
  // falls back to the latest generation's current_prompt_context.
  const componentMap = new Map();
  (Array.isArray(rows) ? rows : []).forEach(row => {
    if (!row || typeof row !== 'object') return;
    const name = String(row.name ?? row.key ?? '').trim();
    if (!name || name === '(frozen)') return;
    componentMap.set(name, String(row.value ?? ''));
  });
  const resolvedLabel = slotLabel != null && String(slotLabel).trim()
    ? slotLabel : index + 1;
  return {
    kind: 'character',
    slot: String(slot || ids[index] || slotLabel || index + 1),
    slot_label: resolvedLabel,
    prompt,
    uc: String((Array.isArray(executedUcs) ? executedUcs[index] : '') || ''),
    components: Array.from(componentMap, ([name, value]) => ({name, value})),
  };
}

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
  onInstantOutpaint = null,
  onWebUiEnhance = null,
  onGrokI2I = null,
  onGrokI2V = null,
  onDirector = null,
  onSetCharacterReference = null,
  onSetVibeTransfer = null,
  onSaveCharacterAsset = null,
  onDelete = null,
  getWildcardFreezeState = () => ({}),
  setWildcardFreezeState = null,
  onToggleWildcardFreeze = null,
  getMode = () => '',
  getCurrentSavedPath = () => '',
  canUseDesktopImg2Img = () => true,
  canUseTabView = () => true,
  canOpenLocalFiles = () => false,
  isGrokReady = () => false,
}) {
  let menu = null;
  let metadataModal = null;
  let sidePopup = null;
  let popupWildcardFreezeState = null;
  let menuVersion = 0;
  const submenuCloseTimers = new WeakMap();
  const DELETE_MODE_KEY = 'naia_result_delete_mode';
  let deleteMode = readDeleteMode();

  function readDeleteMode() {
    try {
      return window.localStorage?.getItem(DELETE_MODE_KEY) === 'disk' ? 'disk' : 'history';
    } catch (error) {
      return 'history';
    }
  }

  function setDeleteMode(mode) {
    deleteMode = mode === 'disk' ? 'disk' : 'history';
    try { window.localStorage?.setItem(DELETE_MODE_KEY, deleteMode); } catch (error) {}
  }

  // 모드 선택 시 메뉴를 닫지 않고 ✓ active 표시만 라이브 갱신한다.
  function updateDeleteModeActiveState() {
    if (!menu) return;
    menu.querySelectorAll('[data-delete-mode]').forEach(button => {
      const active = button.dataset.deleteMode === deleteMode;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-checked', active ? 'true' : 'false');
      const labelSpan = button.querySelector('span');
      if (labelSpan) {
        const base = button.dataset.deleteLabel ?? labelSpan.textContent;
        button.dataset.deleteLabel = base;
        labelSpan.textContent = (active ? '✓ ' : '') + base;
      }
    });
    // "이미지 삭제" 우측 [디스크] 라벨도 현재 모드에 맞춰 라이브 갱신
    const delBtn = menu.querySelector('[data-action="' + ACTION_DELETE_RESULT + '"]');
    const tail = delBtn ? delBtn.querySelector('.result-context-item-tail') : null;
    if (tail) {
      const existing = tail.querySelector('[data-disk-badge]');
      if (deleteMode === 'disk' && !existing) {
        tail.insertAdjacentHTML('afterbegin', DISK_BADGE_HTML);
      } else if (deleteMode !== 'disk' && existing) {
        existing.remove();
      }
    }
  }

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

  function canUseFileLocation() {
    return typeof canOpenLocalFiles === 'function' && canOpenLocalFiles();
  }

  function itemModeAllowed(item) {
    return !item.modes || item.modes.includes(currentMode());
  }

  function isItemEnabled(item, context) {
    if (!itemModeAllowed(item)) return false;
    if (item.desktopImg2Img && !(typeof canUseDesktopImg2Img === 'function' && canUseDesktopImg2Img())) return false;
    // 모바일은 우측 탭 스트립이 없어 '탭에서 보기'가 무의미 — 항목 자체를 숨긴다.
    if (item.desktopTabOnly && !(typeof canUseTabView === 'function' && canUseTabView())) return false;
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
    if (item.action === ACTION_SHOW_PAYLOAD) {
      return hasCapability(context, 'metadata');
    }
    if (item.action === ACTION_SHOW_WILDCARDS) {
      return hasCapability(context, 'has_wildcards');
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
    if (item.action === ACTION_OUTPAINT) {
      return typeof onInstantOutpaint === 'function' && hasCapability(context, 'image_action');
    }
    if (item.action === ACTION_WEBUI_ENHANCE) {
      return typeof onWebUiEnhance === 'function';
    }
    if (item.action === ACTION_IMAGE_ACTION) {
      if (!hasCapability(context, 'image_action')) return false;
      return typeof onImageAction === 'function';
    }
    if (item.action === ACTION_GROK_I2I) {
      return typeof onGrokI2I === 'function' && Boolean(context?.hasImage)
        && (typeof isGrokReady === 'function' && isGrokReady());
    }
    if (item.action === ACTION_GROK_I2V) {
      return typeof onGrokI2V === 'function' && Boolean(context?.hasImage)
        && (typeof isGrokReady === 'function' && isGrokReady());
    }
    if (item.action === ACTION_DIRECTOR) {
      return typeof onDirector === 'function' && Boolean(context?.hasImage);
    }
    if (item.action === ACTION_SET_CHAR_REF) {
      return typeof onSetCharacterReference === 'function' && Boolean(context?.hasImage);
    }
    if (item.action === ACTION_SET_VIBE) {
      return typeof onSetVibeTransfer === 'function' && Boolean(context?.hasImage);
    }
    if (item.action === ACTION_SAVE_CHAR_ASSET) {
      return typeof onSaveCharacterAsset === 'function' && Boolean(context?.hasImage);
    }
    if (item.action === ACTION_DELETE_RESULT) {
      // capability 'delete'는 위에서 이미 검증됨 (백엔드 asset이 history item 존재 시 true).
      return typeof onDelete === 'function';
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
    if (item.desktopTabOnly && !(typeof canUseTabView === 'function' && canUseTabView())) {
      return '';
    }
    // Grok 변형/영상은 progrok 로그인(ready) 시에만 노출 — 미로그인/순수 브라우저에선 항목 자체를 숨긴다.
    if (item.grokGated && !(typeof isGrokReady === 'function' && isGrokReady())) {
      return '';
    }
    if (item.type === 'separator') {
      return '<div class="result-context-separator"></div>';
    }
    const hasChildren = Array.isArray(item.children) && item.children.length > 0;
    const danger = item.danger ? ' danger' : '';
    const enabled = isItemEnabled(item, context);
    // '와일드카드'처럼 데이터 없을 땐 비활성 대신 항목 자체를 숨긴다(사용자 요청: 없으면 숨김).
    if (item.hideWhenDisabled && !enabled) return '';
    const disabledAttr = enabled ? '' : ' disabled aria-disabled="true"';
    const actionAttr = item.action ? ` data-action="${item.action}"` : '';
    const imageActionAttr = item.imageAction ? ` data-image-action="${item.imageAction}"` : '';
    const copyFormatAttr = item.copyFormat ? ` data-copy-format="${item.copyFormat}"` : '';
    const queuePositionAttr = item.queuePosition ? ` data-queue-position="${item.queuePosition}"` : '';
    const queueModeAttr = item.queueMode ? ` data-queue-mode="${item.queueMode}"` : '';
    const isDeleteModeItem = item.action === ACTION_SET_DELETE_MODE;
    const deleteModeAttr = isDeleteModeItem && item.deleteMode ? ` data-delete-mode="${item.deleteMode}"` : '';
    const deleteModeActive = isDeleteModeItem && item.deleteMode === deleteMode;
    const deleteModeActiveCls = deleteModeActive ? ' is-active' : '';
    const deleteLabelAttr = isDeleteModeItem ? ` data-delete-label="${escapeText(item.label)}"` : '';
    const labelText = deleteModeActive ? `✓ ${item.label}` : item.label;
    const submenuAttr = hasChildren ? ' data-submenu-trigger="true" aria-haspopup="menu" aria-expanded="false"' : '';
    const badgeClass = item.badgeTone ? ` ${item.badgeTone}` : '';
    const badgeHtml = item.badge
      ? `<span class="result-context-badge${badgeClass}">${escapeText(item.badge)}</span>`
      : '';
    const diskBadgeHtml = (item.action === ACTION_DELETE_RESULT && deleteMode === 'disk') ? DISK_BADGE_HTML : '';
    const childHtml = hasChildren
      ? `<div class="result-context-children" role="menu">${item.children.map(child => renderItem(child, context)).join('')}</div>`
      : '';
    return `
      <div class="result-context-group${hasChildren ? ' has-children' : ''}">
        <button type="button" class="result-context-item${danger}${deleteModeActiveCls}${hasChildren ? ' has-children' : ''}"${actionAttr}${imageActionAttr}${copyFormatAttr}${queuePositionAttr}${queueModeAttr}${deleteModeAttr}${deleteLabelAttr}${submenuAttr}${disabledAttr}>
          <span>${escapeText(labelText)}</span><span class="result-context-item-tail">${diskBadgeHtml}${badgeHtml}${hasChildren ? '<span class="result-context-arrow" aria-hidden="true">›</span>' : ''}</span>
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
        if (action === ACTION_SET_DELETE_MODE) {
          // 삭제 모드만 변경하고 메뉴는 닫지 않는다 (active ✓ 라이브 갱신).
          setDeleteMode(button.dataset.deleteMode === 'disk' ? 'disk' : 'history');
          updateDeleteModeActiveState();
          return;
        }
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
        } else if (action === ACTION_SHOW_PAYLOAD) {
          showPayload(context);
        } else if (action === ACTION_SHOW_WILDCARDS) {
          showWildcards(context);
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
        } else if (action === ACTION_OUTPAINT) {
          if (typeof onInstantOutpaint === 'function') onInstantOutpaint(context);
        } else if (action === ACTION_WEBUI_ENHANCE) {
          onWebUiEnhance(context);
        } else if (action === ACTION_IMAGE_ACTION) {
          onImageAction(context, button.dataset.imageAction || '');
        } else if (action === ACTION_GROK_I2I) {
          if (typeof onGrokI2I === 'function') onGrokI2I(context);
        } else if (action === ACTION_GROK_I2V) {
          if (typeof onGrokI2V === 'function') onGrokI2V(context);
        } else if (action === ACTION_DIRECTOR) {
          if (typeof onDirector === 'function') onDirector(context);
        } else if (action === ACTION_SET_CHAR_REF) {
          if (typeof onSetCharacterReference === 'function') onSetCharacterReference(context);
        } else if (action === ACTION_SET_VIBE) {
          if (typeof onSetVibeTransfer === 'function') onSetVibeTransfer(context);
        } else if (action === ACTION_SAVE_CHAR_ASSET) {
          if (typeof onSaveCharacterAsset === 'function') onSaveCharacterAsset(context);
        } else if (action === ACTION_DELETE_RESULT) {
          if (typeof onDelete === 'function') onDelete(context, deleteMode);
        }
      });
    });
  }

  function open(kind, x, y, context = {}) {
    // 삭제 방식은 이 메뉴 말고 뷰어 설정 판에서도 바꾼다. 만들 때 한 번 읽고 마는
    // 값이라 그쪽에서 바꾸면 여기 ✓ 가 어긋난 채로 남았다 — 열 때마다 다시 읽는다.
    deleteMode = readDeleteMode();
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
        open_file: canUseFileLocation() && isSaved && Boolean(path),
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
    capabilities.open_file = canUseFileLocation() && Boolean(capabilities.open_file);
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

  // ===== 우측 모듈형 팝업 (Payload / 와일드카드) =====
  // 데이터는 JSON(SSOT) 그대로 받고, 표시는 HTML로 렌더한다(앱 전체 패널과 동일 패턴).
  function closeSidePopup() {
    if (!sidePopup) return;
    sidePopup.remove();
    sidePopup = null;
  }

  function openSidePopup(title, bodyHtml) {
    closeSidePopup();
    sidePopup = document.createElement('div');
    sidePopup.className = 'result-side-popup';
    sidePopup.innerHTML = `
      <div class="result-side-popup-header">
        <span class="result-side-popup-title">${escapeText(title)}</span>
        <button type="button" class="result-side-popup-close" data-close="side" aria-label="Close">×</button>
      </div>
      <div class="result-side-popup-body">${bodyHtml}</div>`;
    document.body.appendChild(sidePopup);
    // 오른쪽에서 슬라이드 인.
    window.requestAnimationFrame(() => { if (sidePopup) sidePopup.classList.add('open'); });
    sidePopup.addEventListener('click', event => {
      if (!(event.target instanceof window.Element)) return;
      const freezeButton = event.target.closest('[data-wc-freeze]');
      if (freezeButton) {
        event.preventDefault();
        handleWildcardFreezeClick(freezeButton);
        return;
      }
      if (event.target.closest('[data-close="side"]')) {
        closeSidePopup();
      }
    });
  }

  async function fetchFullMeta(context) {
    const path = context && context.path ? context.path : '';
    const useCurrent = !path && context && context.source === 'current';
    if (!path && !useCurrent) return null;
    const url = path ? viewerMetaUrl(path, true) : '/api/result/metadata';
    const response = await fetchFn(url);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.json();
  }

  function rawFromMeta(data) {
    if (data && typeof data === 'object' && 'raw' in data) return data.raw && typeof data.raw === 'object' ? data.raw : {};
    return data && typeof data === 'object' ? data : {};
  }

  function normalizeWildcardFreezeState(state) {
    const src = state && typeof state === 'object' ? state : {};
    return {
      locations: Array.isArray(src.locations) ? src.locations.slice() : [],
      legacy: Array.isArray(src.legacy) ? src.legacy.slice() : [],
      characters: Array.isArray(src.characters) ? src.characters.slice() : [],
    };
  }

  function setPopupWildcardFreezeState(state) {
    popupWildcardFreezeState = normalizeWildcardFreezeState(state);
    if (typeof setWildcardFreezeState === 'function') {
      setWildcardFreezeState(popupWildcardFreezeState);
    }
  }

  function syncWildcardFreezeStateFromMeta(data) {
    if (data && typeof data === 'object' && data.frozen && typeof data.frozen === 'object') {
      setPopupWildcardFreezeState(data.frozen);
    }
  }

  function currentWildcardFreezeState() {
    if (popupWildcardFreezeState) return popupWildcardFreezeState;
    try {
      const state = typeof getWildcardFreezeState === 'function' ? getWildcardFreezeState() : {};
      return normalizeWildcardFreezeState(state);
    } catch (error) {
      return normalizeWildcardFreezeState({});
    }
  }

  function applyWildcardFreezeMutation(payload, frozen) {
    const next = normalizeWildcardFreezeState(currentWildcardFreezeState());
    const kind = String(payload?.kind || payload?.type || '').toLowerCase();
    if (kind === 'character' || payload?.slot) {
      const slot = String(payload?.slot || '');
      next.characters = next.characters.filter(item => String(item.slot || '') !== slot);
      if (frozen && slot) {
        next.characters.push({
          slot,
          prompt: String(payload?.prompt || ''),
          uc: String(payload?.uc || ''),
        });
      }
      setPopupWildcardFreezeState(next);
      return;
    }
    const location = String(payload?.location || '');
    const name = String(payload?.key || payload?.name || '');
    next.locations = next.locations.filter(item => !(String(item.location || '') === location && String(item.name || '') === name));
    if (frozen && location && name) {
      next.locations.push({location, name, value: String(payload?.value || '')});
    }
    setPopupWildcardFreezeState(next);
  }

  function isLocationFrozen(entry) {
    const state = currentWildcardFreezeState();
    const locations = Array.isArray(state.locations) ? state.locations : [];
    return locations.some(item => String(item.location || '') === String(entry.location || '')
      && String(item.name || '') === String(entry.name || ''));
  }

  function isCharacterFrozen(slot) {
    const state = currentWildcardFreezeState();
    const characters = Array.isArray(state.characters) ? state.characters : [];
    return characters.some(item => String(item.slot || '') === String(slot || ''));
  }

  function encodeFreezePayload(payload) {
    return encodeURIComponent(JSON.stringify(payload || {}));
  }

  function decodeFreezePayload(value) {
    try {
      return JSON.parse(decodeURIComponent(String(value || '')));
    } catch (error) {
      return {};
    }
  }

  function freezeButtonHtml(payload, frozen, title) {
    const pressed = frozen ? 'true' : 'false';
    return `<button type="button" class="wc-pin-toggle${frozen ? ' active' : ''}" data-wc-freeze="${encodeFreezePayload(payload)}" data-wc-frozen="${frozen ? '1' : '0'}" aria-pressed="${pressed}" title="${escapeText(title || 'Freeze')}">📌</button>`;
  }

  function updateFreezeButton(button, frozen) {
    button.dataset.wcFrozen = frozen ? '1' : '0';
    button.setAttribute('aria-pressed', frozen ? 'true' : 'false');
    button.classList.toggle('active', frozen);
  }

  function handleWildcardFreezeClick(button) {
    const payload = decodeFreezePayload(button.dataset.wcFreeze || '');
    const nextFrozen = button.dataset.wcFrozen !== '1';
    if (typeof onToggleWildcardFreeze === 'function') {
      onToggleWildcardFreeze(payload, nextFrozen);
    }
    applyWildcardFreezeMutation(payload, nextFrozen);
    updateFreezeButton(button, nextFrozen);
    showToast(nextFrozen ? 'Wildcard freeze enabled' : 'Wildcard freeze cleared', 'success');
  }

  async function showPayload(context) {
    try {
      const data = await fetchFullMeta(context);
      if (!data) { showToast('No image is selected', 'error'); return; }
      syncWildcardFreezeStateFromMeta(data);
      openSidePopup('Payload', renderPayloadHtml(data));
    } catch (error) {
      console.error('Failed to load payload', error);
      showToast('Failed to load payload', 'error');
    }
  }

  async function showWildcards(context) {
    try {
      const data = await fetchFullMeta(context);
      if (!data) { showToast('No image is selected', 'error'); return; }
      syncWildcardFreezeStateFromMeta(data);
      const raw = rawFromMeta(data);
      const promptContext = raw.prompt_context || {};
      const generationParams = raw.generation_params || {};
      openSidePopup('적용된 와일드카드', renderWildcardsHtml(promptContext, generationParams));
    } catch (error) {
      console.error('Failed to load wildcards', error);
      showToast('Failed to load wildcards', 'error');
    }
  }

  function plSection(title, html, open) {
    return `<details class="pl-section"${open ? ' open' : ''}><summary>${escapeText(title)}</summary>`
      + `<div class="pl-section-body">${html}</div></details>`;
  }

  // 제네릭 JSON→HTML 재귀 렌더러(저유지보수: 새 필드 자동 노출). depth 캡으로 폭주 방지.
  function jsonToHtml(value, depth = 0) {
    if (value === null || value === undefined) return '<span class="j-null">null</span>';
    if (depth > 8) return `<span class="j-str">${escapeText(JSON.stringify(value))}</span>`;
    const type = typeof value;
    if (type === 'string') return `<span class="j-str">${escapeText(value)}</span>`;
    if (type === 'number' || type === 'boolean') return `<span class="j-num">${escapeText(String(value))}</span>`;
    if (Array.isArray(value)) {
      if (!value.length) return '<span class="j-empty">[]</span>';
      return '<div class="j-arr">' + value.map((entry, index) =>
        `<div class="j-row"><span class="j-key">${index}</span>${jsonToHtml(entry, depth + 1)}</div>`).join('') + '</div>';
    }
    if (type === 'object') {
      const keys = Object.keys(value);
      if (!keys.length) return '<span class="j-empty">{}</span>';
      return '<div class="j-obj">' + keys.map(key =>
        `<div class="j-row"><span class="j-key">${escapeText(key)}</span>${jsonToHtml(value[key], depth + 1)}</div>`).join('') + '</div>';
    }
    return `<span class="j-str">${escapeText(String(value))}</span>`;
  }

  // 파이프라인 단계 델타(추가/제거/롤/노트) — Hooker 대체 읽기전용 로그.
  function renderPipelineTraceHtml(stages) {
    if (!Array.isArray(stages) || !stages.length) return '';
    return '<div class="trace-list">' + stages.map(stage => {
      const added = Array.isArray(stage.added) ? stage.added : [];
      const removed = Array.isArray(stage.removed) ? stage.removed : [];
      const rolls = Array.isArray(stage.rolls) ? stage.rolls : [];
      const changed = stage.changed && (added.length || removed.length || rolls.length || stage.note);
      let body = '';
      if (added.length) body += `<div class="trace-added">+ ${added.map(escapeText).join(', ')}</div>`;
      if (removed.length) body += `<div class="trace-removed">− ${removed.map(escapeText).join(', ')}</div>`;
      if (rolls.length) body += `<div class="trace-rolls">${rolls.map(roll => `${escapeText(roll.from)} → ${escapeText(roll.to)}`).join(', ')}</div>`;
      if (!changed && !body) body = '<div class="trace-nochange">변경 없음</div>';
      const note = stage.note ? `<span class="trace-note">${escapeText(stage.note)}</span>` : '';
      return `<div class="trace-stage${changed ? '' : ' unchanged'}">`
        + `<div class="trace-stage-head"><span class="trace-stage-label">${escapeText(stage.label || stage.stage || '')}</span>${note}</div>`
        + body + '</div>';
    }).join('') + '</div>';
  }

  // 블록별(prefix/postfix/main/character[+slot]) 적용 와일드카드.
  function renderWildcardsHtml(promptContext, generationParams = {}) {
    const wildcards = (promptContext && promptContext.wildcards) || {};
    const history = Array.isArray(wildcards.history) ? wildcards.history : [];
    const state = Array.isArray(wildcards.state) ? wildcards.state : [];
    if (!history.length && !state.length) {
      return '<div class="result-side-empty">이 이미지에 적용된 와일드카드가 없습니다.</div>';
    }
    const LOC_LABELS = {prefix: 'Prefix', postfix: 'Postfix', main: 'Main 프롬프트'};
    const LOC_ORDER = {prefix: 0, main: 1, postfix: 2, character: 3};
    const executedCharacters = Array.isArray(generationParams._executed_characters)
      ? generationParams._executed_characters : [];
    const executedUcs = Array.isArray(generationParams._executed_characters_uc)
      ? generationParams._executed_characters_uc : [];
    const executedIds = Array.isArray(generationParams._executed_character_ids)
      ? generationParams._executed_character_ids.map(value => String(value || '')) : [];
    const blockLabel = entry => {
      const loc = entry.location || '기타';
      if (loc === 'character') {
        const label = entry.slot_label != null ? entry.slot_label : entry.slot;
        return label != null ? `캐릭터 ${label}` : '캐릭터';
      }
      return LOC_LABELS[loc] || loc;
    };
    const blocks = new Map();
    history.forEach(entry => {
      const label = blockLabel(entry);
      const key = entry.location === 'character'
        ? `character:${entry.slot ?? entry.slot_label ?? label}`
        : `location:${entry.location || 'other'}`;
      if (!blocks.has(key)) {
        blocks.set(key, {
          label,
          order: LOC_ORDER[entry.location] ?? 9,
          slot: entry.slot ?? '',
          slotLabel: entry.slot_label ?? '',
          location: entry.location || '',
          rows: [],
        });
      }
      blocks.get(key).rows.push(entry);
    });
    const ordered = Array.from(blocks.values()).sort((a, b) =>
      (a.order - b.order) || String(a.slotLabel || a.slot).localeCompare(String(b.slotLabel || b.slot))
        || a.label.localeCompare(b.label));
    let html = '';
    ordered.forEach(info => {
      const charFreezePayload = info.location === 'character'
        ? buildCharacterFreezePayload({
            slot: info.slot,
            slotLabel: info.slotLabel,
            rows: info.rows,
            executedCharacters,
            executedUcs,
            executedIds,
          })
        : null;
      const titlePin = charFreezePayload
        ? freezeButtonHtml(charFreezePayload, isCharacterFrozen(charFreezePayload.slot), '캐릭터 블럭 freeze')
        : '';
      html += `<div class="wc-block"><div class="wc-block-title-row">${titlePin}<div class="wc-block-title">${escapeText(info.label)}</div></div>`;
      info.rows.forEach(entry => {
        const rowPin = entry.location && entry.location !== 'character'
          ? freezeButtonHtml({kind: 'location', location: entry.location, key: entry.name, value: entry.value}, isLocationFrozen(entry), '와일드카드 freeze')
          : '';
        html += `<div class="wc-row">${rowPin}<span class="wc-name">${escapeText(entry.name)}</span>`
          + `<span class="wc-arrow">→</span><span class="wc-val">${escapeText(entry.value)}</span></div>`;
      });
      html += '</div>';
    });
    if (state.length) {
      html += '<div class="wc-block"><div class="wc-block-title-row"><div class="wc-block-title">순차 / 종속 상태</div></div>';
      state.forEach(entry => {
        const dep = entry.dependent ? ` <span class="wc-dep">(종속${entry.master ? ' · ' + escapeText(entry.master) : ''})</span>` : '';
        html += `<div class="wc-row"><span class="wc-name">${escapeText(entry.name)}</span>`
          + `<span class="wc-val">${escapeText(String(entry.current))}/${escapeText(String(entry.total))}${dep}</span></div>`;
      });
      html += '</div>';
    }
    return html;
  }

  function renderPayloadHtml(data) {
    const raw = rawFromMeta(data);
    const gen = (raw && raw.generation_params) || {};
    const promptContext = (raw && raw.prompt_context) || {};
    const apiMeta = (raw && raw.api_metadata) || {};
    const sections = [];

    // 프롬프트 + 캐릭터
    const mainPrompt = promptContext.main_prompt || promptContext.final_prompt || gen.input || gen.prompt || '';
    const negPrompt = gen.negative_prompt || gen.uc || promptContext.negative_prompt || '';
    let promptHtml = '';
    if (mainPrompt) promptHtml += `<div class="pl-field"><div class="pl-label">Prompt</div><div class="pl-text">${escapeText(mainPrompt)}</div></div>`;
    if (negPrompt) promptHtml += `<div class="pl-field"><div class="pl-label">Negative</div><div class="pl-text">${escapeText(negPrompt)}</div></div>`;
    const chars = Array.isArray(gen._executed_characters) ? gen._executed_characters
      : (Array.isArray(promptContext.characters) ? promptContext.characters : []);
    if (chars.length) {
      promptHtml += '<div class="pl-field"><div class="pl-label">캐릭터</div>';
      chars.forEach((entry, index) => {
        const text = typeof entry === 'string' ? entry : JSON.stringify(entry);
        promptHtml += `<div class="pl-text"><b>Character ${index + 1}</b> ${escapeText(text)}</div>`;
      });
      promptHtml += '</div>';
    }
    if (promptHtml) sections.push(plSection('프롬프트', promptHtml, true));

    const traceHtml = renderPipelineTraceHtml(promptContext.pipeline_trace);
    if (traceHtml) sections.push(plSection('파이프라인 로그', traceHtml, true));

    const wc = promptContext.wildcards;
    if (wc && ((Array.isArray(wc.history) && wc.history.length) || (Array.isArray(wc.state) && wc.state.length))) {
      sections.push(plSection('와일드카드', renderWildcardsHtml(promptContext, gen), true));
    }

    if (gen && Object.keys(gen).length) sections.push(plSection('생성 파라미터', jsonToHtml(gen), false));
    if (apiMeta && Object.keys(apiMeta).length) sections.push(plSection('API 메타데이터', jsonToHtml(apiMeta), false));

    const hasRaw = raw && Object.keys(raw).length;
    if (hasRaw) {
      sections.push(`<details class="result-side-raw"><summary>raw JSON</summary>`
        + `<pre>${escapeText(JSON.stringify(raw, null, 2))}</pre></details>`);
    }
    if (!sections.length) return '<div class="result-side-empty">메타데이터가 없습니다.</div>';
    return sections.join('');
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

    if (target.closest('.stats-island, .viewer-panel, .right-tab-bar, .frozen-wc-bar')) {
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
        closeSidePopup();
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

// cache-bust marker: 20260705-frozenwcbar (skip .frozen-wc-bar in image context menu)
function defaultEscHtml(value) {
  return String(value).replace(/[&<>"']/g, char => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  })[char]);
}
