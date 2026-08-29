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
  // 인페인트 진입 해상도 옵션(⚙ 미니 팝업). 기본은 켜짐 = 기존 동작.
  getInpaintResize1mp = () => true,
  getMetadataViewer = () => null,
  getQueuePanel = () => null,
  discardPendingModuleEdit = () => {},
  flushPendingModuleEdit = () => {},
  openModule = () => {},
  openImg2ImgSessionSurface = () => openModule('img2img', {forceOpen: true}),
  // V5 인페인트 세션이 열렸다 - 화면이 그것을 보여 주게 한다.
  onCanvasSession = () => {},
  // 세션을 요청했지만 아직 계열을 모른다 - 상태가 도착하면 화면이 고른다.
  onCanvasSessionPending = () => {},
  onLoadPrompt = () => {},
  applyMetadataSettings = () => {},
  switchRightTab = () => {},
}) {
  let dragSourceBound = false;
  const dragGhostSize = 50;
  let compactDragImage = null;
  let lastDragPointer = {type: '', time: 0};

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
      ['enable_hr', findMetadataActionValue(data, ['enable_hr'])],
      ['hr_scale', findMetadataActionValue(data, ['hr_scale'])],
      ['hr_upscaler', findMetadataActionValue(data, ['hr_upscaler', 'hires_upscaler'])],
      ['denoising_strength', findMetadataActionValue(data, ['denoising_strength', 'denoise'])],
      ['hires_steps', findMetadataActionValue(data, ['hires_steps', 'hr_second_pass_steps'])],
      ['hr_cfg', findMetadataActionValue(data, ['hr_cfg'])],
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
        // ⚠️ **버리지 않고 보낸다.** 예전에는 여기서 버렸는데, 그러면 방금 친
        //    프롬프트가 백엔드에 영영 안 닿아 세션이 `user_edited` 로 서지
        //    않는다 - 덮어쓰기 경고가 안 뜨고 작업이 조용히 사라진다
        //    (Codex HIGH 2026-08-28). 옛 세션으로 먼저 흘려보낸 뒤 연다.
        flushPendingModuleEdit('img2img');
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
      const data = await response.json().catch(() => ({}));
      if (isDesktopImg2ImgAction(action)) {
        // V5 인페인트는 팝업을 열지 않는다 - Result 안 가상 캔버스에서 바로 고친다
        // (사용자 지정 2026-08-26). 백엔드가 세션을 열면서 계열을 판정하므로
        // 여기서 모델 표를 한 벌 더 들고 있지 않는다.
        if (data && data.state && data.state.canvas_active) {
          // ⚠️ 토스트만 띄우고 끝내면 안 된다. 도크가 접혀 있거나 직전 세션이
          //    `결과 보기` 로 끝났으면 화면에 아무 변화가 없어 "버튼이 안 먹는다" 가
          //    된다(사용자 제보 2026-08-26).
          onCanvasSession();
          showToast('Result 안 가상 캔버스에서 편집하세요', 'success');
        } else {
          openImg2ImgSessionSurface();
          showToast(data.message || `${action === 'inpaint' ? 'Inpaint' : 'Img2Img'} session ready`, 'success');
        }
      } else if (action === 'vibe' && currentMode() === 'NAI') {
        openModule('vibe_transfer');
        showToast(data.message || 'Vibe Transfer image added', 'success');
      } else if (action === 'character_reference' && currentMode() === 'NAI') {
        openModule('character_reference');
        showToast(data.message || 'Character Reference image added', 'success');
      }
    } catch (error) {
      console.error('Image action request failed', error);
      showToast(error.message || 'Image action failed', 'error');
    }
  }

  // 외부 이미지(붙여넣기/드롭/감지)를 프롬프트 없이 결과 히스토리에 삽입한다.
  // 삽입된 이미지는 우클릭 → Grok I2I/I2V (및 NAI Img2Img/Inpaint/Vibe) 진입점으로 쓸 수 있다.
  // 반환값: 성공 true / 실패 false (Danbooru 등 호출부가 성공 시에만 후속 동작을 하도록).
  async function insertExternalToHistory(payload) {
    if (!payload || !payload.blob) {
      showToast('이미지 데이터를 찾을 수 없습니다.', 'error');
      return false;
    }
    try {
      const label = encodeURIComponent(payload.label || 'Imported Image');
      const response = await fetch(`/api/image/insert-history?label=${label}`, {
        method: 'POST',
        headers: {'Content-Type': payload.blob.type || 'application/octet-stream'},
        body: payload.blob,
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || `HTTP ${response.status}`);
      }
      const data = await response.json().catch(() => ({}));
      showToast(data.message || '이미지를 히스토리에 추가했습니다.', 'success');
      return true;
    } catch (error) {
      console.error('Insert external image to history failed', error);
      showToast(error.message || '히스토리 추가 실패', 'error');
      return false;
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

  function applyOriginalImageDragData(dataTransfer, payload = {}) {
    if (!dataTransfer) return;
    const source = payload.source || (payload.path ? 'saved' : 'current');
    const dragUrl = contextImagePngUrl({source, path: payload.path || ''});
    const originalUrl = absoluteAppUrl(dragUrl);
    const filename = pngFilename(filenameFromDragPayload(payload));
    const mimeType = mimeTypeForFilename(filename);
    try { dataTransfer.clearData(); } catch (_) { /* noop */ }
    try { dataTransfer.effectAllowed = 'copy'; } catch (_) { /* noop */ }
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

  function traceRoundedRect(ctx, x, y, width, height, radius) {
    const clampedRadius = Math.max(0, Math.min(radius, width / 2, height / 2));
    ctx.beginPath();
    ctx.moveTo(x + clampedRadius, y);
    ctx.lineTo(x + width - clampedRadius, y);
    ctx.quadraticCurveTo(x + width, y, x + width, y + clampedRadius);
    ctx.lineTo(x + width, y + height - clampedRadius);
    ctx.quadraticCurveTo(x + width, y + height, x + width - clampedRadius, y + height);
    ctx.lineTo(x + clampedRadius, y + height);
    ctx.quadraticCurveTo(x, y + height, x, y + height - clampedRadius);
    ctx.lineTo(x, y + clampedRadius);
    ctx.quadraticCurveTo(x, y, x + clampedRadius, y);
    ctx.closePath();
  }

  function getCompactDragImage(sourceImage) {
    if (!compactDragImage) {
      compactDragImage = document.createElement('canvas');
      compactDragImage.width = dragGhostSize;
      compactDragImage.height = dragGhostSize;
    }
    const canvas = compactDragImage;
    const ctx = canvas.getContext('2d');
    if (!ctx) return canvas;

    ctx.clearRect(0, 0, dragGhostSize, dragGhostSize);
    ctx.save();
    traceRoundedRect(ctx, 0, 0, dragGhostSize, dragGhostSize, 8);
    ctx.fillStyle = 'rgba(18, 16, 28, 0.92)';
    ctx.fill();
    ctx.clip();

    const imageWidth = sourceImage?.naturalWidth || sourceImage?.videoWidth || sourceImage?.width || 0;
    const imageHeight = sourceImage?.naturalHeight || sourceImage?.videoHeight || sourceImage?.height || 0;
    if (sourceImage && imageWidth > 0 && imageHeight > 0) {
      const scale = Math.max(dragGhostSize / imageWidth, dragGhostSize / imageHeight);
      const drawWidth = imageWidth * scale;
      const drawHeight = imageHeight * scale;
      try {
        ctx.drawImage(
          sourceImage,
          (dragGhostSize - drawWidth) / 2,
          (dragGhostSize - drawHeight) / 2,
          drawWidth,
          drawHeight
        );
      } catch (_) { /* noop */ }
    }
    ctx.restore();

    ctx.save();
    traceRoundedRect(ctx, 1, 1, dragGhostSize - 2, dragGhostSize - 2, 7);
    ctx.strokeStyle = 'rgba(185, 164, 255, 0.9)';
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.restore();
    return canvas;
  }

  function setCompactDragPreview(dataTransfer, sourceImage) {
    if (!dataTransfer || typeof dataTransfer.setDragImage !== 'function') return;
    try {
      const offset = Math.floor(dragGhostSize / 2);
      dataTransfer.setDragImage(getCompactDragImage(sourceImage), offset, offset);
    } catch (_) { /* noop */ }
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
      // 일부 모바일/인앱(WebView) 환경은 picker를 노출만 하고 호출 시 거부한다.
      // 예외를 삼키고 false를 반환해 downloadBlob 폴백을 타게 한다.
      console.warn('showSaveFilePicker unavailable, falling back to download', error);
      return false;
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
        try {
          await writeBlobToFileHandle(saveHandle, blob);
          showToast('Image saved', 'success');
          return;
        } catch (writeError) {
          if (writeError?.name === 'AbortError') return;
          // createWritable/write가 플랫폼에 막힌 경우(인앱 브라우저/WebView 등) 일반 다운로드로 폴백.
          console.warn('File write unavailable, falling back to download', writeError);
        }
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

  async function copyImageFromContext(context = {}, format = 'png') {
    const normalizedFormat = String(format || 'png').toLowerCase();
    if (normalizedFormat !== 'png') {
      showToast('Only PNG clipboard copy is supported', 'error');
      return;
    }
    try {
      // 네이티브 백엔드 클립보드 경로는 헤드리스 런타임에서 스텁이므로 사용하지 않는다.
      // Electron 렌더러와 localhost 브라우저 모두 secure context라 브라우저 ClipboardItem이 동작한다.
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

  function outpaintFromContext(context = {}) {
    if (currentMode() !== 'NAI') {
      showToast('Outpaint is only available in NAI mode', 'error');
      return;
    }
    const ws = getWs();
    if (!ws || ws.readyState !== window.WebSocket.OPEN) {
      showToast('Remote connection is not open', 'error');
      return;
    }
    try {
      ws.send(JSON.stringify({
        type: 'result_outpaint',
        source: context.source || '',
        path: context.source === 'current' ? '' : (context.path || ''),
      }));
      showToast('Outpaint 요청됨', 'success');
    } catch (error) {
      console.error('Outpaint request failed', error);
      showToast('Outpaint request failed', 'error');
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
        // ⚠️ **버리지 않고 보낸다.** 예전에는 여기서 버렸는데, 그러면 방금 친
        //    프롬프트가 백엔드에 영영 안 닿아 세션이 `user_edited` 로 서지
        //    않는다 - 덮어쓰기 경고가 안 뜨고 작업이 조용히 사라진다
        //    (Codex HIGH 2026-08-28). 옛 세션으로 먼저 흘려보낸 뒤 연다.
        flushPendingModuleEdit('img2img');
        ws.send(JSON.stringify({
          type: 'result_image_action',
          action,
          // 진입 해상도 옵션(⚙). 안 보내면 백엔드가 기존 동작(강제 1MP)을 쓴다.
          resize_1mp: getInpaintResize1mp() ? 'true' : 'false',
          ...resultContextCommandPayload(context || {}),
        }));
        // ⚠️ 여기서 팝업을 바로 열면 안 된다. 이 경로는 WS 명령이라 응답이 없어 계열을
        //    모르고, V5 에서는 팝업과 캔버스가 함께 떠 **두 경로가 한 세션을 만진다**
        //    (Codex 리뷰 BLOCK 3). 표만 세워 두고 상태가 도착하면 그때 고른다.
        onCanvasSessionPending();
        showToast(`${action === 'inpaint' ? 'Inpaint' : 'Img2Img'} session requested`, 'success');
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

  function isResultDragSourceTarget(target) {
    if (!(target instanceof window.Element)) return false;
    return target.id === 'preview'
      || Boolean(target.closest('.viewer'))
      || Boolean(target.classList && target.classList.contains('viewer-thumb'));
  }

  function rememberDragPointer(event) {
    if (!isResultDragSourceTarget(event.target)) return;
    lastDragPointer = {
      type: String(event.pointerType || ''),
      time: Date.now(),
    };
  }

  function isMobileInitiatedDrag() {
    const elapsed = Date.now() - (lastDragPointer.time || 0);
    if (elapsed >= 0 && elapsed < 2500 && lastDragPointer.type) {
      return lastDragPointer.type !== 'mouse';
    }
    const mediaQuery = window.matchMedia?.('(hover: none), (pointer: coarse)');
    return Boolean(mediaQuery?.matches);
  }

  function bindDragSource() {
    if (dragSourceBound) return;
    dragSourceBound = true;
    const viewer = document.querySelector('.viewer');
    const preview = document.getElementById('preview');
    if (preview) preview.draggable = false;
    if (viewer) viewer.draggable = true;
    document.addEventListener('pointerdown', rememberDragPointer, true);
    document.addEventListener('dragstart', event => {
      const target = event.target;
      if (!(target instanceof window.Element)) return;
      // V5 인페인트 가상 캔버스가 뷰어를 차지하고 있으면 결과를 끌어내지 않는다.
      //
      // ⚠️ `.viewer` **자체**가 draggable 이라, 캔버스 어디를 끌어도 dragstart 는 여기로
      //    들어온다(그때 `event.target` 은 캔버스가 아니라 `.viewer` 다 - 자식에
      //    `draggable="false"` 를 붙여도 막히지 않는다). 그리고 그렇게 실려 나가는 것은
      //    편집 중이라 **숨겨져 있는 예전 결과**다 - 메타데이터 뷰어에 엉뚱한 그림이
      //    도착한다(사용자 제보 2026-08-26).
      //
      // 결과 보기 모드에서는 막지 않는다 - 거기서는 진짜 결과가 화면에 있고,
      // 끌어내는 것이 맞다.
      if (document.querySelector('.viewer.ic-editing')) {
        event.preventDefault();
        return;
      }
      if (isResultDragSourceTarget(target) && isMobileInitiatedDrag()) {
        event.preventDefault();
        return;
      }
      let payload = null;
      let dragImageSource = null;
      if (target.id === 'preview') {
        dragImageSource = target;
        payload = {
          type: 'preview',
          source: target.dataset.source || '',
          path: target.dataset.path || '',
        };
      } else if (target.closest('.viewer')) {
        const preview = document.getElementById('preview');
        if (preview && preview.classList.contains('show')) {
          dragImageSource = preview;
          payload = {
            type: 'preview',
            source: preview.dataset.source || 'current',
            path: preview.dataset.path || '',
          };
        }
      } else if (target.classList && target.classList.contains('viewer-thumb')) {
        dragImageSource = target;
        payload = {
          type: 'history',
          source: 'saved',
          path: target.dataset.path || '',
        };
      }
      if (!payload || !event.dataTransfer) return;
      setCompactDragPreview(event.dataTransfer, dragImageSource);
      applyOriginalImageDragData(event.dataTransfer, payload);
      try {
        event.dataTransfer.setData('application/x-naia-source', JSON.stringify(payload));
      } catch (_) { /* noop */ }
    }, true);
  }

  return {
    bindDragSource,
    requestPopupImageAction,
    insertExternalToHistory,
    requestMetadataImageAction,
    loadPromptFromContext,
    restoreSettingsFromContext,
    rerollPromptFromContext,
    queueResultFromContext,
    openLocationFromContext,
    saveImageFromContext,
    copyImageFromContext,
    upscaleFromContext,
    outpaintFromContext,
    requestContextImageAction,
    showMetadataInTab,
    handleInternalImageDrop,
  };
}
