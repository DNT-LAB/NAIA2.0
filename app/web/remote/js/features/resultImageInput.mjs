export function createResultImageInput({
  document,
  window,
  fetch: fetchFn = window.fetch.bind(window),
  showImageActionPopup = () => {},
  showToast = () => {},
  navigatorRef = window.navigator,
  URLRef = window.URL,
  onInternalDrop = null,
}) {
  const viewer = document.querySelector('.viewer');
  let localPreviewUrl = null;
  let fileInput = null;
  let pendingFileInputOptions = {};
  const dragDepthByTarget = new WeakMap();

  function isEditableTarget(target) {
    if (!target || !(target instanceof window.Element)) return false;
    return !!target.closest('input, textarea, select, [contenteditable="true"]');
  }

  function isImageBlob(blob) {
    return !!blob && (!blob.type || blob.type.startsWith('image/'));
  }

  function getImageFileFromDataTransfer(dataTransfer) {
    if (!dataTransfer) return null;
    const files = Array.from(dataTransfer.files || []);
    const file = files.find(item => item && item.type && item.type.startsWith('image/'));
    if (file) return file;
    const items = Array.from(dataTransfer.items || []);
    const imageItem = items.find(item => item.kind === 'file' && item.type && item.type.startsWith('image/'));
    return imageItem ? imageItem.getAsFile() : null;
  }

  function readInternalDragSource(dataTransfer) {
    if (!dataTransfer) return null;
    let raw = '';
    try {
      raw = dataTransfer.getData('application/x-naia-source');
    } catch (_) {
      return null;
    }
    if (!raw) return null;
    try {
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === 'object' ? parsed : null;
    } catch (_) {
      return null;
    }
  }

  function dataTransferHasImage(dataTransfer) {
    if (!dataTransfer) return false;
    const types = Array.from(dataTransfer.types || []);
    if (types.includes('Files')) return true;
    return types.some(type => type.startsWith('image/'))
      || types.includes('text/html')
      || types.includes('text/uri-list')
      || types.includes('text/x-moz-url')
      || types.includes('text/plain');
  }

  function normalizeDroppedUrl(value) {
    const text = String(value || '').trim();
    if (!text) return '';
    if (/^data:image\//i.test(text)) return text;
    try {
      const url = new URL(text, window.location.href);
      return ['http:', 'https:', 'blob:'].includes(url.protocol) ? url.href : '';
    } catch (_) {
      return '';
    }
  }

  function firstUriFromList(value) {
    return String(value || '')
      .split(/\r?\n/)
      .map(line => line.trim())
      .find(line => line && !line.startsWith('#')) || '';
  }

  function firstSrcsetUrl(srcset) {
    return String(srcset || '')
      .split(',')
      .map(part => part.trim().split(/\s+/)[0])
      .find(Boolean) || '';
  }

  function extractImageUrlFromHtml(html) {
    if (!html) return '';
    try {
      const parser = new window.DOMParser();
      const doc = parser.parseFromString(html, 'text/html');
      const image = doc.querySelector('img[src], source[srcset], source[src]');
      if (!image) return '';
      const candidates = [
        firstSrcsetUrl(image.getAttribute('srcset')),
        image.getAttribute('src'),
        image.getAttribute('data-src'),
        image.getAttribute('data-original'),
        image.getAttribute('data-lazy-src'),
        image.getAttribute('data-url'),
        image.closest('a[href]')?.getAttribute('href'),
      ].map(normalizeDroppedUrl).filter(Boolean);
      return candidates.find(url => !url.startsWith('blob:')) || candidates[0] || '';
    } catch (_) {
      return '';
    }
  }

  function getImageUrlFromDataTransfer(dataTransfer) {
    if (!dataTransfer) return '';
    return extractImageUrlFromHtml(dataTransfer.getData('text/html'))
      || normalizeDroppedUrl(firstUriFromList(dataTransfer.getData('text/uri-list')))
      || normalizeDroppedUrl(firstUriFromList(dataTransfer.getData('text/x-moz-url')))
      || normalizeDroppedUrl(dataTransfer.getData('text/plain'));
  }

  function labelFromImageUrl(imageUrl) {
    try {
      const url = new URL(imageUrl);
      const name = decodeURIComponent(url.pathname.split('/').filter(Boolean).pop() || '');
      return name || 'Web Image';
    } catch (_) {
      return 'Web Image';
    }
  }

  async function fetchImageUrlAsBlob(imageUrl) {
    const url = String(imageUrl || '');
    let response = null;
    if (/^data:image\//i.test(url) || url.startsWith('blob:')) {
      try {
        response = await fetchFn(url);
      } catch (error) {
        throw new Error(url.startsWith('blob:')
          ? 'External blob URLs cannot be imported directly'
          : error.message);
      }
    } else {
      response = await fetchFn('/api/image/fetch', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({url}),
      });
    }
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || `HTTP ${response.status}`);
    }
    const blob = await response.blob();
    if (!isImageBlob(blob)) throw new Error('Dropped URL is not an image');
    return blob;
  }

  function createImageUrl(blob) {
    if (!isImageBlob(blob)) return '';
    if (localPreviewUrl) URLRef.revokeObjectURL(localPreviewUrl);
    localPreviewUrl = URLRef.createObjectURL(blob);
    return localPreviewUrl;
  }

  function revokeImageUrl(imageUrl) {
    if (!imageUrl || imageUrl !== localPreviewUrl) return;
    URLRef.revokeObjectURL(localPreviewUrl);
    localPreviewUrl = null;
  }

  async function extractMetadata(blob, label) {
    const response = await fetchFn('/api/metadata/extract?label=' + encodeURIComponent(label || 'Input Image'), {
      method: 'POST',
      headers: {'Content-Type': blob.type || 'application/octet-stream'},
      body: blob,
    });
    if (!response.ok) {
      const error = new Error(`HTTP ${response.status}`);
      error.status = response.status;
      throw error;
    }
    return response.json();
  }

  async function handleImageBlob(blob, label = 'Input Image') {
    if (!isImageBlob(blob)) {
      showToast('Image file required', 'error');
      return;
    }
    const imageUrl = createImageUrl(blob);
    let metadataPayload = {
      source: 'input',
      label,
      summary: {},
      raw: {},
      has_metadata: false,
    };
    try {
      metadataPayload = await extractMetadata(blob, label);
    } catch (error) {
      console.error('Input image metadata extraction failed', error);
      showToast('Metadata check failed', 'error');
    }
    showImageActionPopup({
      blob,
      imageUrl,
      label,
      metadataPayload,
      hasMetadata: Boolean(metadataPayload && metadataPayload.has_metadata),
      revokeImageUrl: () => revokeImageUrl(imageUrl),
    });
  }

  async function importImageBlob(blob, label = 'Input Image', options = {}) {
    if (!isImageBlob(blob)) {
      showToast('Image file required', 'error');
      return;
    }
    const onImageBlob = typeof options.onImageBlob === 'function'
      ? options.onImageBlob
      : handleImageBlob;
    await onImageBlob(blob, label);
  }

  async function handleImageUrl(imageUrl, label = 'Web Image', options = {}) {
    if (!imageUrl) {
      showToast('Image URL required', 'error');
      return;
    }
    try {
      const blob = await fetchImageUrlAsBlob(imageUrl);
      await importImageBlob(blob, label || labelFromImageUrl(imageUrl), options);
    } catch (error) {
      console.error('Web image import failed', error);
      showToast(error.message || 'Failed to load web image', 'error');
    }
  }

  async function readImageFromClipboard() {
    if (!navigatorRef.clipboard || typeof navigatorRef.clipboard.read !== 'function') {
      throw new Error('Clipboard image read is unavailable');
    }
    const items = await navigatorRef.clipboard.read();
    for (const item of items) {
      const imageType = item.types.find(type => type.startsWith('image/'));
      if (imageType) {
        return item.getType(imageType);
      }
    }
    return null;
  }

  async function pasteFromClipboard(options = {}) {
    try {
      const blob = await readImageFromClipboard();
      if (!blob) {
        showToast('No image in clipboard', 'error');
        return;
      }
      await importImageBlob(blob, options.label || 'Clipboard Image', options);
    } catch (error) {
      console.error('Clipboard image paste failed', error);
      showToast('Clipboard access denied', 'error');
    }
  }

  function handlePasteEvent(event) {
    if (isEditableTarget(event.target)) return;
    const file = getImageFileFromDataTransfer(event.clipboardData);
    if (!file) {
      const imageUrl = getImageUrlFromDataTransfer(event.clipboardData);
      if (!imageUrl) return;
      event.preventDefault();
      handleImageUrl(imageUrl, labelFromImageUrl(imageUrl));
      return;
    }
    event.preventDefault();
    importImageBlob(file, 'Clipboard Image');
  }

  function ensureFileInput() {
    if (fileInput && document.body.contains(fileInput)) return fileInput;
    fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.accept = 'image/*';
    fileInput.id = 'resultImageFileInput';
    fileInput.dataset.naiaImageFileInput = 'result';
    fileInput.setAttribute('aria-label', 'Import image file');
    fileInput.style.position = 'fixed';
    fileInput.style.left = '-10000px';
    fileInput.style.top = '0';
    fileInput.style.width = '1px';
    fileInput.style.height = '1px';
    fileInput.style.opacity = '0';
    fileInput.style.pointerEvents = 'none';
    fileInput.addEventListener('change', () => {
      const file = fileInput.files && fileInput.files[0];
      const options = pendingFileInputOptions || {};
      pendingFileInputOptions = {};
      fileInput.value = '';
      if (!file) return;
      importImageBlob(file, file.name || options.label || 'Input Image', options);
    });
    document.body.appendChild(fileInput);
    return fileInput;
  }

  function openImageFilePicker(options = {}) {
    const input = ensureFileInput();
    pendingFileInputOptions = options && typeof options === 'object' ? {...options} : {};
    input.click();
  }

  function setDragActive(target, active, activeClass = 'drag-over') {
    if (!target) return;
    target.classList.toggle(activeClass, active);
  }

  function updateDragDepth(target, delta) {
    if (!target) return 0;
    const nextDepth = Math.max(0, (dragDepthByTarget.get(target) || 0) + delta);
    if (nextDepth) dragDepthByTarget.set(target, nextDepth);
    else dragDepthByTarget.delete(target);
    return nextDepth;
  }

  function resetDragDepth(target) {
    if (!target) return;
    dragDepthByTarget.delete(target);
  }

  function bindDropTarget(target, options = {}) {
    if (!target) return null;
    const activeClass = options.activeClass || 'drag-over';
    const internalDropHandler = typeof options.onInternalDrop === 'function'
      ? options.onInternalDrop
      : onInternalDrop;

    const handleDragEnter = event => {
      if (!dataTransferHasImage(event.dataTransfer)) return;
      event.preventDefault();
      updateDragDepth(target, 1);
      setDragActive(target, true, activeClass);
    };

    const handleDragOver = event => {
      if (!dataTransferHasImage(event.dataTransfer)) return;
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy';
      setDragActive(target, true, activeClass);
    };

    const handleDragLeave = event => {
      if (!dataTransferHasImage(event.dataTransfer)) return;
      const nextDepth = updateDragDepth(target, -1);
      if (nextDepth === 0) setDragActive(target, false, activeClass);
    };

    const handleDrop = event => {
      if (!dataTransferHasImage(event.dataTransfer)) return;
      event.preventDefault();
      resetDragDepth(target);
      setDragActive(target, false, activeClass);
      const internal = readInternalDragSource(event.dataTransfer);
      if (internal && typeof internalDropHandler === 'function') {
        try {
          if (internalDropHandler(internal) !== false) return;
        } catch (error) {
          console.error('Internal drop handler failed', error);
        }
      }
      const file = getImageFileFromDataTransfer(event.dataTransfer);
      if (file) {
        importImageBlob(file, file.name || 'Dropped Image', options);
        return;
      }
      const imageUrl = getImageUrlFromDataTransfer(event.dataTransfer);
      if (!imageUrl) {
        showToast('Image file or image URL required', 'error');
        return;
      }
      handleImageUrl(imageUrl, labelFromImageUrl(imageUrl), options);
    };

    target.tabIndex = -1;
    target.addEventListener('dragenter', handleDragEnter);
    target.addEventListener('dragover', handleDragOver);
    target.addEventListener('dragleave', handleDragLeave);
    target.addEventListener('drop', handleDrop);

    return () => {
      resetDragDepth(target);
      setDragActive(target, false, activeClass);
      target.removeEventListener('dragenter', handleDragEnter);
      target.removeEventListener('dragover', handleDragOver);
      target.removeEventListener('dragleave', handleDragLeave);
      target.removeEventListener('drop', handleDrop);
    };
  }

  function bind() {
    ensureFileInput();
    bindDropTarget(viewer);
    document.addEventListener('paste', handlePasteEvent);
  }

  return {
    bind,
    bindDropTarget,
    pasteFromClipboard,
    openImageFilePicker,
    handleImageBlob,
  };
}
