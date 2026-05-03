export function createResultImageActions({
  document,
  window,
  fetch,
  showToast,
  getMode = () => 'NAI',
  getWs = () => null,
  getLatestResultBlob = () => null,
  useNativeClipboard = () => false,
  getPreviewImageUrl = () => '',
  getMetadataViewer = () => null,
  getQueuePanel = () => null,
  discardPendingModuleEdit = () => {},
  openModule = () => {},
  onLoadPrompt = () => {},
  applyMetadataSettings = () => {},
  switchRightTab = () => {},
}) {
  let dragSourceBound = false;
  let currentDragImageCache = null;
  let currentDragImagePromise = null;

  function isMetadataActionObject(value) {
    return !!value && typeof value === 'object' && !Array.isArray(value);
  }

  function isMetadataActionPresent(value) {
    return value !== undefined && value !== null && value !== '';
  }

  function currentMode() {
    return String(getMode() || '').toUpperCase();
  }

  function isDesktopImg2ImgAction(action) {
    return action === 'img2img' || action === 'inpaint';
  }

  function ensureNaiDesktopImg2ImgAction(action) {
    if (!isDesktopImg2ImgAction(action)) return true;
    if (currentMode() === 'NAI') return true;
    const label = action === 'inpaint' ? 'Inpaint' : 'Img2Img';
    showToast(`${label} is available in NAI mode only`, 'error');
    return false;
  }

  function tryParseMetadataActionJson(value) {
    if (typeof value !== 'string') return value;
    const trimmed = value.trim();
    if (!trimmed || !/^[{[]/.test(trimmed)) return value;
    try {
      return JSON.parse(trimmed);
    } catch (_) {
      return value;
    }
  }

  function getMetadataActionRaw(data) {
    if (!data || typeof data !== 'object') return data;
    return Object.prototype.hasOwnProperty.call(data, 'raw') ? data.raw : data;
  }

  function getMetadataActionSources(data) {
    const summary = isMetadataActionObject(data?.summary) ? data.summary : {};
    const raw = getMetadataActionRaw(data);
    const extracted = isMetadataActionObject(raw?.extracted_metadata) ? raw.extracted_metadata : {};
    const generationParams = isMetadataActionObject(raw?.generation_params) ? raw.generation_params : {};
    const promptContext = isMetadataActionObject(raw?.prompt_context) ? raw.prompt_context : {};
    const apiMetadata = isMetadataActionObject(raw?.api_metadata) ? raw.api_metadata : {};
    const rawAsMetadata = isMetadataActionObject(raw) && !raw.extracted_metadata ? raw : {};
    const comment = tryParseMetadataActionJson(extracted.Comment || extracted.comment || rawAsMetadata.Comment || rawAsMetadata.comment);
    const extractedParams = isMetadataActionObject(extracted.parameters) ? extracted.parameters : {};
    const rawParams = isMetadataActionObject(rawAsMetadata.parameters) ? rawAsMetadata.parameters : {};
    return [
      promptContext,
      summary,
      generationParams,
      extracted,
      rawAsMetadata,
      isMetadataActionObject(comment) ? comment : {},
      extractedParams,
      rawParams,
      apiMetadata,
      isMetadataActionObject(raw?.image) ? raw.image : {},
    ].filter(source => isMetadataActionObject(source) && Object.keys(source).length > 0);
  }

  function findMetadataActionValue(data, aliases) {
    const sources = getMetadataActionSources(data);
    for (const source of sources) {
      for (const alias of aliases) {
        if (isMetadataActionPresent(source[alias])) return source[alias];
      }
    }
    return '';
  }

  function buildMetadataActionPayload(data, context = {}) {
    const width = findMetadataActionValue(data, ['width']);
    const height = findMetadataActionValue(data, ['height']);
    const resolution = width && height
      ? `${width} x ${height}`
      : findMetadataActionValue(data, ['resolution']);
    const params = {};
    [
      ['resolution', resolution],
      ['steps', findMetadataActionValue(data, ['steps'])],
      ['cfg_scale', findMetadataActionValue(data, ['cfg_scale', 'scale', 'cfg'])],
      ['cfg_rescale', findMetadataActionValue(data, ['cfg_rescale'])],
      ['seed', findMetadataActionValue(data, ['seed'])],
      ['sampler', findMetadataActionValue(data, ['sampler', 'sampler_name'])],
      ['scheduler', findMetadataActionValue(data, ['noise_schedule', 'scheduler'])],
      ['sm', findMetadataActionValue(data, ['sm'])],
      ['sm_dyn', findMetadataActionValue(data, ['sm_dyn'])],
      ['VAR+', findMetadataActionValue(data, ['VAR+', 'skip_cfg_above_sigma'])],
      ['model', findMetadataActionValue(data, ['model', 'Model', 'model_name', 'checkpoint'])],
    ].forEach(([key, value]) => {
      if (isMetadataActionPresent(value)) params[key] = value;
    });
    return {
      data,
      source: context,
      prompt: findMetadataActionValue(data, ['main_prompt', 'final_prompt', 'prompt', 'input', '_raw_input', 'Description', 'description']),
      negative: findMetadataActionValue(data, ['uc', 'negative', 'negative_prompt']),
      params,
    };
  }

  async function loadContextMetadataPayload(context = {}) {
    const path = context.path || '';
    const url = context.metadataUrl
      || (path ? `/api/viewer/meta?path=${encodeURIComponent(path)}&full=1` : '/api/result/metadata');
    const response = await fetch(url);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }

  async function requestPopupImageAction(payload, action) {
    if (!ensureNaiDesktopImg2ImgAction(action)) {
      return;
    }
    if (!payload || !payload.blob) {
      showToast('Image data is unavailable', 'error');
      return;
    }
    try {
      if (isDesktopImg2ImgAction(action)) {
        discardPendingModuleEdit('img2img');
      }
      const label = encodeURIComponent(payload.label || 'Input Image');
      const response = await fetch(`/api/image-action/${encodeURIComponent(action)}?label=${label}`, {
        method: 'POST',
        headers: {'Content-Type': payload.blob.type || 'application/octet-stream'},
        body: payload.blob,
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || `HTTP ${response.status}`);
      }
      if (isDesktopImg2ImgAction(action)) {
        showToast(`${action === 'inpaint' ? 'Inpaint' : 'Img2Img'} opened on desktop`, 'success');
      } else if (action === 'vibe' && currentMode() === 'NAI') {
        openModule('vibe_transfer');
      }
    } catch (error) {
      console.error('Image action request failed', error);
      showToast(error.message || 'Image action failed', 'error');
    }
  }

  async function requestMetadataImageAction(payload, action) {
    const label = payload?.label || payload?.source?.label || payload?.source?.path || 'Metadata Image';
    let blob = payload?.blob || null;
    try {
      if (!blob) {
        const imageUrl = payload?.imageUrl || '';
        if (!imageUrl) {
          showToast('Metadata image is unavailable', 'error');
          return;
        }
        const response = await fetch(imageUrl);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        blob = await response.blob();
      }
      await requestPopupImageAction({blob, label}, action);
    } catch (error) {
      console.error('Metadata image action failed', error);
      showToast(error.message || 'Metadata image action failed', 'error');
    }
  }

  async function loadPromptFromContext(context = {}) {
    try {
      const data = await loadContextMetadataPayload(context);
      const payload = buildMetadataActionPayload(data, context);
      const prompt = String(payload.prompt || '').trim();
      if (!prompt) {
        showToast('No prompt metadata found', 'error');
        return;
      }
      onLoadPrompt(prompt);
    } catch (error) {
      console.error('Load prompt from context failed', error);
      showToast(error.message || 'Load prompt failed', 'error');
    }
  }

  async function restoreSettingsFromContext(context = {}) {
    try {
      const data = await loadContextMetadataPayload(context);
      const payload = buildMetadataActionPayload(data, context);
      applyMetadataSettings(payload);
    } catch (error) {
      console.error('Restore settings from context failed', error);
      showToast(error.message || 'Restore settings failed', 'error');
    }
  }

  async function rerollPromptFromContext(context = {}) {
    if (!context?.capabilities?.reroll) {
      showToast('Reroll source is unavailable', 'error');
      return;
    }
    try {
      const response = await fetch('/api/result/action/reroll', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          source: context.source || '',
          path: context.path || '',
          file_path: context.filePath || '',
        }),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || `HTTP ${response.status}`);
      }
      showToast('Prompt reroll requested', 'success');
    } catch (error) {
      console.error('Prompt reroll failed', error);
      showToast(error.message || 'Prompt reroll failed', 'error');
    }
  }

  async function queueResultFromContext(context = {}, options = {}) {
    if (!context?.capabilities?.queue) {
      showToast('Queue source is unavailable', 'error');
      return;
    }
    try {
      const queuePanel = getQueuePanel();
      if (queuePanel && typeof queuePanel.wake === 'function') queuePanel.wake();
      const response = await fetch('/api/result/action/queue', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          source: context.source || '',
          path: context.path || '',
          file_path: context.filePath || '',
          label: context.label || '',
          position: options.position || 'back',
          queue_mode: options.mode || 'original',
        }),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || `HTTP ${response.status}`);
      }
      if (queuePanel) window.setTimeout(() => queuePanel.refresh(), 180);
      const modeLabel = options.mode === 'reopen'
        ? 'P.Eng / WC'
        : options.mode === 'current_character'
          ? 'current character'
          : 'original';
      showToast(`${modeLabel} queued ${options.position === 'front' ? 'at front' : 'at back'}`, 'success');
    } catch (error) {
      console.error('Queue result failed', error);
      showToast(error.message || 'Queue result failed', 'error');
    }
  }

  async function openLocationFromContext(context = {}) {
    try {
      const response = await fetch('/api/result/open-location', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          source: context.source || '',
          path: context.path || '',
        }),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || `HTTP ${response.status}`);
      }
      showToast('Opened image location', 'success');
    } catch (error) {
      console.error('Open image location failed', error);
      showToast(error.message || 'Open image location failed', 'error');
    }
  }

  function contextImageUrl(context = {}) {
    if (context.imageSrc) return context.imageSrc;
    if (context.path) return '/api/viewer/image/' + encodeURI(context.path);
    if (context.source === 'current') {
      return getPreviewImageUrl() || '/api/latest-image';
    }
    return '';
  }

  function contextImagePngUrl(context = {}) {
    const params = new URLSearchParams();
    const source = String(context.source || (context.path ? 'saved' : 'current')).trim() || 'current';
    params.set('source', source);
    if (context.path) params.set('path', context.path);
    return '/api/result/image/png?' + params.toString();
  }

  function contextImageOriginalUrl(context = {}) {
    const params = new URLSearchParams();
    const source = String(context.source || (context.path ? 'saved' : 'current')).trim() || 'current';
    params.set('source', source);
    if (context.path) params.set('path', context.path);
    return '/api/result/image/original?' + params.toString();
  }

  function absoluteAppUrl(url) {
    try {
      return new URL(url, window.location.href).href;
    } catch (_) {
      return String(url || '');
    }
  }

  function mimeTypeForFilename(filename) {
    const lower = String(filename || '').toLowerCase();
    if (lower.endsWith('.webp')) return 'image/webp';
    if (lower.endsWith('.jpg') || lower.endsWith('.jpeg')) return 'image/jpeg';
    if (lower.endsWith('.gif')) return 'image/gif';
    if (lower.endsWith('.bmp')) return 'image/bmp';
    return 'image/png';
  }

  function escapeDragAttribute(value) {
    return String(value || '').replace(/[&<>"']/g, char => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    })[char]);
  }

  function filenameFromDragPayload(payload = {}) {
    const name = String(payload.path || payload.filePath || payload.label || '')
      .split(/[\\/]/)
      .pop()
      .replace(/[<>:"/\\|?*\x00-\x1F]/g, '_')
      .trim();
    if (name) return name;
    return 'naia-result.png';
  }

  function pngFilename(filename) {
    const base = String(filename || 'naia-result.png').replace(/\.[^.\\/]+$/, '').trim();
    return `${base || 'naia-result'}.png`;
  }

  function addDragFile(dataTransfer, file) {
    if (!dataTransfer || !file || !dataTransfer.items || typeof dataTransfer.items.add !== 'function') {
      return false;
    }
    try {
      dataTransfer.items.add(file);
      return true;
    } catch (error) {
      console.warn('Could not attach drag image file', error);
      return false;
    }
  }

  function cachedDragFileForPayload(payload = {}) {
    const source = payload.source || (payload.path ? 'saved' : 'current');
    if (source !== 'current' || payload.path || !currentDragImageCache) return null;
    return currentDragImageCache.file || null;
  }

  function applyOriginalImageDragData(dataTransfer, payload = {}) {
    if (!dataTransfer) return;
    const source = payload.source || (payload.path ? 'saved' : 'current');
    const usePngExport = source === 'current' && !payload.path;
    const dragUrl = usePngExport
      ? contextImagePngUrl({source: 'current'})
      : contextImageOriginalUrl({source, path: payload.path || ''});
    const originalUrl = absoluteAppUrl(dragUrl);
    const filename = usePngExport
      ? pngFilename(filenameFromDragPayload(payload))
      : filenameFromDragPayload(payload);
    const mimeType = mimeTypeForFilename(filename);
    try { dataTransfer.clearData(); } catch (_) { /* noop */ }
    try { dataTransfer.effectAllowed = 'copy'; } catch (_) { /* noop */ }
    addDragFile(dataTransfer, cachedDragFileForPayload(payload));
    try { dataTransfer.setData('text/uri-list', originalUrl); } catch (_) { /* noop */ }
    try { dataTransfer.setData('text/plain', originalUrl); } catch (_) { /* noop */ }
    try {
      dataTransfer.setData(
        'text/html',
        `<img src="${escapeDragAttribute(originalUrl)}" alt="${escapeDragAttribute(filename)}">`
      );
    } catch (_) { /* noop */ }
    try { dataTransfer.setData('DownloadURL', `${mimeType}:${filename}:${originalUrl}`); } catch (_) { /* noop */ }
  }

  async function prepareCurrentDragImage(options = {}) {
    if (options.force) {
      currentDragImageCache = null;
      currentDragImagePromise = null;
    }
    if (currentDragImageCache) return currentDragImageCache;
    if (currentDragImagePromise) return currentDragImagePromise;
    const context = {source: 'current', label: options.label || 'naia-result'};
    currentDragImagePromise = fetchContextImageBlob(context, {format: 'png'})
      .then(blob => {
        const filename = filenameFromContext(context, 'png');
        const file = new window.File([blob], filename, {type: 'image/png'});
        currentDragImageCache = {blob, file, filename};
        return currentDragImageCache;
      })
      .catch(error => {
        console.warn('Current result drag image preparation failed', error);
        currentDragImageCache = null;
        return null;
      })
      .finally(() => {
        currentDragImagePromise = null;
      });
    return currentDragImagePromise;
  }

  async function fetchContextImageBlob(context = {}, options = {}) {
    const format = String(options.format || '').toLowerCase();
    if (format === 'original') {
      const response = await fetch(contextImageOriginalUrl(context), {cache: 'no-store'});
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || `HTTP ${response.status}`);
      }
      return response.blob();
    }
    if (format === 'png') {
      const response = await fetch(contextImagePngUrl(context), {cache: 'no-store'});
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || `HTTP ${response.status}`);
      }
      return response.blob();
    }
    const imageUrl = contextImageUrl(context);
    if (!imageUrl) throw new Error('Result image is unavailable');
    const latestResultBlob = getLatestResultBlob();
    if (imageUrl.startsWith('blob:') && latestResultBlob) return latestResultBlob;
    const response = await fetch(imageUrl);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.blob();
  }

  function filenameFromContext(context = {}, fallbackExt = 'png') {
    const rawName = String(context.label || context.path || 'naia-result')
      .split(/[\\/]/)
      .pop()
      .replace(/\.[^.]+$/, '')
      .replace(/[<>:"/\\|?*\x00-\x1F]/g, '_')
      .trim();
    return `${rawName || 'naia-result'}.${fallbackExt}`;
  }

  function downloadBlob(blob, filename) {
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => window.URL.revokeObjectURL(url), 1000);
  }

  async function pickPngSaveHandle(filename) {
    if (typeof window.showSaveFilePicker !== 'function') return false;
    try {
      return await window.showSaveFilePicker({
        suggestedName: filename,
        types: [{
          description: 'PNG image',
          accept: {'image/png': ['.png']},
        }],
      });
    } catch (error) {
      if (error?.name === 'AbortError') return null;
      throw error;
    }
  }

  async function writeBlobToFileHandle(handle, blob) {
    const writable = await handle.createWritable();
    try {
      await writable.write(blob);
    } finally {
      await writable.close();
    }
  }

  async function saveImageFromContext(context = {}) {
    try {
      const filename = filenameFromContext(context, 'png');
      const saveHandle = await pickPngSaveHandle(filename);
      if (saveHandle === null) return;
      const blob = await fetchContextImageBlob(context, {format: 'png'});
      if (saveHandle) {
        await writeBlobToFileHandle(saveHandle, blob);
        showToast('Image saved', 'success');
        return;
      }
      downloadBlob(blob, filename);
      showToast('Image download started', 'success');
    } catch (error) {
      console.error('Save image failed', error);
      showToast(error.message || 'Save image failed', 'error');
    }
  }

  function blobMatchesMime(blob, mimeType) {
    return String(blob?.type || '').toLowerCase() === String(mimeType || '').toLowerCase();
  }

  async function copyPngViaNativeClipboard(context = {}) {
    const response = await fetch('/api/result/clipboard/png', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(resultContextCommandPayload(context)),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || `HTTP ${response.status}`);
    }
    const data = await response.json().catch(() => ({}));
    showToast(data.filename ? `PNG copied to clipboard: ${data.filename}` : 'PNG copied to clipboard', 'success');
  }

  async function copyImageFromContext(context = {}, format = 'png') {
    const normalizedFormat = String(format || 'png').toLowerCase();
    if (normalizedFormat !== 'png') {
      showToast('Only PNG clipboard copy is supported', 'error');
      return;
    }
    try {
      if (useNativeClipboard()) {
        await copyPngViaNativeClipboard(context);
        return;
      }
      if (!window.navigator.clipboard?.write || !window.ClipboardItem) {
        showToast('Image clipboard is not supported by this browser', 'error');
        return;
      }
      const mimeType = 'image/png';
      let originalBlob = null;
      try {
        originalBlob = await fetchContextImageBlob(context, {format: 'original'});
      } catch (originalError) {
        originalBlob = await fetchContextImageBlob(context, {format: 'png'});
      }
      const clipboardBlob = blobMatchesMime(originalBlob, mimeType)
        ? originalBlob
        : await fetchContextImageBlob(context, {format: 'png'});
      await window.navigator.clipboard.write([
        new window.ClipboardItem({[mimeType]: clipboardBlob}),
      ]);
      showToast('PNG blob copied to clipboard', 'success');
    } catch (error) {
      console.error('Copy image failed', error);
      showToast(error.message || 'Copy image failed', 'error');
    }
  }

  function upscaleFromContext(context = {}) {
    if (currentMode() !== 'NAI') {
      showToast('NAI upscale is only available in NAI mode', 'error');
      return;
    }
    const ws = getWs();
    if (!ws || ws.readyState !== window.WebSocket.OPEN) {
      showToast('Remote connection is not open', 'error');
      return;
    }
    try {
      ws.send(JSON.stringify({
        type: 'result_upscale',
        source: context.source || '',
        path: context.source === 'current' ? '' : (context.path || ''),
      }));
      showToast('NAI 2x upscale requested', 'success');
    } catch (error) {
      console.error('NAI upscale request failed', error);
      showToast('NAI upscale request failed', 'error');
    }
  }

  function resultContextCommandPayload(context = {}) {
    return {
      source: context.source || '',
      path: context.source === 'current' ? '' : (context.path || ''),
      file_path: context.filePath || '',
      label: context.label || context.path || context.filePath || 'Result Image',
    };
  }

  async function requestContextImageAction(context, action) {
    if (!ensureNaiDesktopImg2ImgAction(action)) {
      return;
    }
    if (isDesktopImg2ImgAction(action) && context?.source !== 'input') {
      const ws = getWs();
      if (!ws || ws.readyState !== window.WebSocket.OPEN) {
        showToast('Remote connection is not open', 'error');
        return;
      }
      try {
        discardPendingModuleEdit('img2img');
        ws.send(JSON.stringify({
          type: 'result_image_action',
          action,
          ...resultContextCommandPayload(context || {}),
        }));
        showToast(`${action === 'inpaint' ? 'Inpaint' : 'Img2Img'} desktop surface requested`, 'success');
      } catch (error) {
        console.error('Context image action request failed', error);
        showToast(`${action === 'inpaint' ? 'Inpaint' : 'Img2Img'} request failed`, 'error');
      }
      return;
    }

    let imageUrl = context?.imageSrc || '';
    const label = context?.path || context?.filePath || 'Result Image';
    if (!imageUrl && context?.path) {
      imageUrl = '/api/viewer/image/' + encodeURI(context.path);
    }
    if (!imageUrl && context?.source === 'current') {
      imageUrl = getPreviewImageUrl();
    }
    if (!imageUrl) {
      showToast('Result image is unavailable', 'error');
      return;
    }
    try {
      const response = await fetch(imageUrl);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const blob = await response.blob();
      await requestPopupImageAction({blob, label}, action);
    } catch (error) {
      console.error('Context image action failed', error);
      showToast(error.message || 'Context image action failed', 'error');
    }
  }

  async function loadMetadataFromContextImage(context = {}) {
    const metadataViewer = getMetadataViewer();
    const imageUrl = context.imageSrc || '';
    const label = context.label || context.path || context.filePath || 'Result Image';
    try {
      let blob = context.blob || null;
      const latestResultBlob = getLatestResultBlob();
      if (!blob && context.source === 'current' && latestResultBlob) blob = latestResultBlob;
      if (!blob && imageUrl.startsWith('blob:') && latestResultBlob) blob = latestResultBlob;
      if (!blob) {
        if (!imageUrl) {
          showToast('Image data is unavailable', 'error');
          return;
        }
        const response = await fetch(imageUrl);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        blob = await response.blob();
      }
      await metadataViewer.loadImageBlob(blob, label, {imageUrl});
    } catch (error) {
      console.error('Context metadata image extraction failed', error);
      showToast(error.message || 'Failed to load metadata', 'error');
    }
  }

  function showMetadataInTab(context = {}) {
    const metadataViewer = getMetadataViewer();
    if (!metadataViewer) {
      showToast('Metadata viewer is not ready', 'error');
      return false;
    }
    if (context.source === 'current') {
      metadataViewer.loadCurrent({silent: false});
    } else if (context.path) {
      metadataViewer.loadSaved(context.path, {silent: false});
    } else if (context.hasImage || context.imageSrc || context.blob) {
      loadMetadataFromContextImage(context);
    } else {
      return false;
    }
    switchRightTab('pngInfo', {skipMetadataRefresh: true});
    return true;
  }

  function handleInternalImageDrop(info) {
    if (!info || typeof info !== 'object') return false;
    const path = typeof info.path === 'string' ? info.path : '';
    const source = typeof info.source === 'string' ? info.source : '';
    if (path) {
      return showMetadataInTab({path, source: source || 'saved'});
    }
    if (source === 'current') {
      return showMetadataInTab({source: 'current', hasImage: true});
    }
    return false;
  }

  function bindDragSource() {
    if (dragSourceBound) return;
    dragSourceBound = true;
    document.addEventListener('dragstart', event => {
      const target = event.target;
      if (!(target instanceof window.Element)) return;
      let payload = null;
      if (target.id === 'preview') {
        payload = {
          type: 'preview',
          source: target.dataset.source || '',
          path: target.dataset.path || '',
        };
      } else if (target.classList && target.classList.contains('viewer-thumb')) {
        payload = {
          type: 'history',
          source: 'saved',
          path: target.dataset.path || '',
        };
      }
      if (!payload || !event.dataTransfer) return;
      if (payload.source === 'current' && !payload.path && !currentDragImageCache) {
        prepareCurrentDragImage();
      }
      applyOriginalImageDragData(event.dataTransfer, payload);
      try {
        event.dataTransfer.setData('application/x-naia-source', JSON.stringify(payload));
      } catch (_) { /* noop */ }
    }, true);
  }

  return {
    bindDragSource,
    requestPopupImageAction,
    requestMetadataImageAction,
    loadPromptFromContext,
    restoreSettingsFromContext,
    rerollPromptFromContext,
    queueResultFromContext,
    openLocationFromContext,
    saveImageFromContext,
    copyImageFromContext,
    upscaleFromContext,
    requestContextImageAction,
    showMetadataInTab,
    handleInternalImageDrop,
    prepareCurrentDragImage,
  };
}
