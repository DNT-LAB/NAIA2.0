export function createResultImageInput({
  document,
  window,
  fetch: fetchFn = window.fetch.bind(window),
  showImageActionPopup = () => {},
  showToast = () => {},
  navigatorRef = window.navigator,
  URLRef = window.URL,
}) {
  const viewer = document.querySelector('.viewer');
  let localPreviewUrl = null;
  let dragDepth = 0;

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

  function dataTransferHasImage(dataTransfer) {
    if (!dataTransfer) return false;
    const types = Array.from(dataTransfer.types || []);
    if (types.includes('Files')) return true;
    return types.some(type => type.startsWith('image/'));
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

  async function pasteFromClipboard() {
    try {
      const blob = await readImageFromClipboard();
      if (!blob) {
        showToast('No image in clipboard', 'error');
        return;
      }
      await handleImageBlob(blob, 'Clipboard Image');
    } catch (error) {
      console.error('Clipboard image paste failed', error);
      showToast('Clipboard access denied', 'error');
    }
  }

  function handlePasteEvent(event) {
    if (isEditableTarget(event.target)) return;
    const file = getImageFileFromDataTransfer(event.clipboardData);
    if (!file) return;
    event.preventDefault();
    handleImageBlob(file, 'Clipboard Image');
  }

  function setDragActive(active) {
    if (!viewer) return;
    viewer.classList.toggle('drag-over', active);
  }

  function handleDragEnter(event) {
    if (!dataTransferHasImage(event.dataTransfer)) return;
    event.preventDefault();
    dragDepth += 1;
    setDragActive(true);
  }

  function handleDragOver(event) {
    if (!dataTransferHasImage(event.dataTransfer)) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy';
    setDragActive(true);
  }

  function handleDragLeave(event) {
    if (!dataTransferHasImage(event.dataTransfer)) return;
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) setDragActive(false);
  }

  function handleDrop(event) {
    if (!dataTransferHasImage(event.dataTransfer)) return;
    event.preventDefault();
    dragDepth = 0;
    setDragActive(false);
    const file = getImageFileFromDataTransfer(event.dataTransfer);
    if (!file) {
      showToast('Image file required', 'error');
      return;
    }
    handleImageBlob(file, file.name || 'Dropped Image');
  }

  function bind() {
    if (viewer) {
      viewer.tabIndex = 0;
      viewer.addEventListener('pointerdown', () => viewer.focus({preventScroll: true}));
      viewer.addEventListener('dragenter', handleDragEnter);
      viewer.addEventListener('dragover', handleDragOver);
      viewer.addEventListener('dragleave', handleDragLeave);
      viewer.addEventListener('drop', handleDrop);
    }
    document.addEventListener('paste', handlePasteEvent);
  }

  return {
    bind,
    pasteFromClipboard,
    handleImageBlob,
  };
}
