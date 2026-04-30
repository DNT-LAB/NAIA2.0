export function createImageActionPopup({
  document,
  window,
  escHtml,
  showToast = () => {},
  getMode = () => '',
  onMetadata = () => {},
  onImg2Img = null,
  onInpaint = null,
  onDanbooru = null,
  onVibeTransfer = null,
}) {
  const REMOTE_IMG2IMG_ACTIONS_ENABLED = false;
  let root = null;
  let activePayload = null;

  function close({releaseImageUrl = true} = {}) {
    if (!root) return;
    if (releaseImageUrl && activePayload && typeof activePayload.revokeImageUrl === 'function') {
      activePayload.revokeImageUrl();
    }
    root.remove();
    root = null;
    activePayload = null;
  }

  function escapeText(value) {
    return escHtml(String(value ?? ''));
  }

  function actionButton({action, label, icon = '', tone = '', disabled = false}) {
    const disabledAttr = disabled ? ' disabled aria-disabled="true"' : '';
    const iconHtml = icon ? `<span class="image-action-btn-icon">${escapeText(icon)}</span>` : '';
    return `
      <button type="button" class="image-action-btn ${tone}" data-action="${escapeText(action)}"${disabledAttr}>
        ${iconHtml}<span>${escapeText(label)}</span>
      </button>`;
  }

  function unsupported(label) {
    showToast(`${label} is not connected yet`, 'error');
  }

  function runOptional(handler, label) {
    if (typeof handler === 'function') {
      handler(activePayload);
      close();
      return;
    }
    unsupported(label);
  }

  function bindActions() {
    if (!root) return;
    root.querySelectorAll('[data-action]').forEach(button => {
      button.addEventListener('click', event => {
        event.preventDefault();
        event.stopPropagation();
        if (button.disabled) return;
        const action = button.dataset.action;
        if (action === 'close') {
          close();
        } else if (action === 'metadata') {
          const handled = onMetadata(activePayload);
          close({releaseImageUrl: !handled});
        } else if (action === 'img2img') {
          runOptional(onImg2Img, 'Img2Img');
        } else if (action === 'inpaint') {
          runOptional(onInpaint, 'Inpaint');
        } else if (action === 'danbooru') {
          runOptional(onDanbooru, 'Danbooru tag analysis');
        } else if (action === 'vibe') {
          runOptional(onVibeTransfer, 'Import Vibe Transfer');
        }
      });
    });
    root.addEventListener('mousedown', event => {
      if (!(event.target instanceof window.Element)) return;
      if (event.target.classList.contains('image-action-backdrop')) close();
    });
  }

  function open(payload) {
    if (!payload || !payload.imageUrl) return;
    close();
    activePayload = payload;

    const mode = String(getMode() || '').toUpperCase();
    const showVibe = mode === 'NAI';
    const metadata = payload.metadataPayload || {};
    const hasMetadata = Boolean(metadata.has_metadata);
    const summary = metadata.summary || {};
    const sizeText = summary.width && summary.height ? `${summary.width} x ${summary.height}` : '';

    root = document.createElement('div');
    root.className = 'image-action-popup-root';
    root.innerHTML = `
      <div class="image-action-backdrop"></div>
      <section class="image-action-popup" role="dialog" aria-modal="true" aria-label="Detected image actions">
        <header class="image-action-header">
          <div>
            <div class="image-action-kicker">Detected Image</div>
            <div class="image-action-title">이미지가 감지되었습니다.</div>
          </div>
          <button type="button" class="image-action-close" data-action="close" aria-label="Close">×</button>
        </header>
        <div class="image-action-preview">
          <img src="${escapeText(payload.imageUrl)}" alt="">
          ${sizeText ? `<div class="image-action-meta">${escapeText(sizeText)}</div>` : ''}
        </div>
        <div class="image-action-buttons">
          ${REMOTE_IMG2IMG_ACTIONS_ENABLED ? actionButton({action: 'img2img', icon: '↗', label: 'Img2Img 전송', tone: 'primary'}) : ''}
          ${REMOTE_IMG2IMG_ACTIONS_ENABLED ? actionButton({action: 'inpaint', icon: '✎', label: 'Inpaint 전송'}) : ''}
          ${hasMetadata ? actionButton({action: 'metadata', icon: '▤', label: '메타데이터', tone: 'metadata'}) : ''}
          ${actionButton({action: 'danbooru', icon: '#', label: 'Danbooru 분석', tone: 'danbooru'})}
          ${showVibe ? actionButton({action: 'vibe', icon: '◇', label: 'Vibe Transfer', tone: 'vibe'}) : ''}
        </div>
      </section>`;
    document.body.appendChild(root);
    bindActions();
  }

  function bind() {
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape') close();
    });
  }

  return {
    bind,
    open,
    close,
  };
}
