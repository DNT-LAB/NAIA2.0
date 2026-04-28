export function createMetadataViewer({
  document,
  fetch,
  escHtml,
  showToast,
  onApplyPrompt = null,
  onApplySettings = null,
  onApplyCharacterSettings = null,
  onSendImg2Img = null,
  onRestoreVibeTransfer = null,
}) {
  const statusEl = document.getElementById('metadataStatus');
  const titleEl = document.getElementById('metadataTitle');
  const previewEl = document.getElementById('metadataPreview');
  const previewEmptyEl = document.getElementById('metadataPreviewEmpty');
  const imageInfoEl = document.getElementById('metadataImageInfo');
  const modelInfoEl = document.getElementById('metadataModelInfo');
  const promptEl = document.getElementById('metadataPrompt');
  const negativeEl = document.getElementById('metadataNegative');
  const charactersTitleEl = document.getElementById('metadataCharactersTitle');
  const charactersEl = document.getElementById('metadataCharacters');
  const paramsEl = document.getElementById('metadataParams');
  const rawEl = document.getElementById('metadataRaw');
  const refreshBtn = document.getElementById('metadataRefreshBtn');
  const applyPromptBtn = document.getElementById('metadataApplyPromptBtn');
  const applySettingsBtn = document.getElementById('metadataApplySettingsBtn');
  const applyCharacterSettingsBtn = document.getElementById('metadataApplyCharacterSettingsBtn');
  const restoreVibeBtn = document.getElementById('metadataRestoreVibeBtn');
  const sendImg2ImgBtn = document.getElementById('metadataSendImg2ImgBtn');

  const EMPTY_SOURCE = {kind: 'empty', path: ''};
  let currentSource = EMPTY_SOURCE;
  let currentActionPayload = null;
  let activeImageCleanup = null;
  let loading = false;
  let requestSerial = 0;

  function setStatus(text, tone = '') {
    if (!statusEl) return;
    statusEl.textContent = text || '';
    statusEl.dataset.tone = tone;
  }

  function safeText(value) {
    if (value == null || value === '') return '';
    if (typeof value === 'string') return value;
    return JSON.stringify(value, null, 2);
  }

  function tryParseJson(value) {
    if (typeof value !== 'string') return value;
    const trimmed = value.trim();
    if (!trimmed || !/^[{[]/.test(trimmed)) return value;
    try {
      return JSON.parse(trimmed);
    } catch (_) {
      return value;
    }
  }

  function isObject(value) {
    return !!value && typeof value === 'object' && !Array.isArray(value);
  }

  function isPresent(value) {
    return value !== undefined && value !== null && value !== '';
  }

  function normalizeArray(value) {
    if (!isPresent(value)) return [];
    if (Array.isArray(value)) return value.filter(isPresent);
    return [value];
  }

  function normalizeStringList(value) {
    const parsed = tryParseJson(value);
    if (!isPresent(parsed)) return [];
    const items = Array.isArray(parsed) ? parsed : [parsed];
    return items
      .map(item => String(item ?? '').trim())
      .filter(Boolean);
  }

  function normalizeNumberList(value) {
    const parsed = tryParseJson(value);
    if (!isPresent(parsed)) return [];
    const items = Array.isArray(parsed) ? parsed : [parsed];
    return items
      .map(item => Number(item))
      .filter(item => Number.isFinite(item));
  }

  function normalizeBoolean(value) {
    if (typeof value === 'boolean') return value;
    if (typeof value === 'number') return value !== 0;
    const text = String(value ?? '').trim().toLowerCase();
    return !['', '0', 'false', 'none', 'null', 'undefined'].includes(text);
  }

  function modelFromSource(source) {
    const text = String(source || '');
    const modelMap = [
      ['NovelAI Diffusion V4.5 4BDE2A90', 'NAID4.5F'],
      ['NovelAI Diffusion V4.5 C02D4F98', 'NAID4.5C'],
      ['NovelAI Diffusion V4 7ABFFA2A', 'NAID4.0C'],
      ['NovelAI Diffusion V4 37442FCA', 'NAID4.0F'],
    ];
    const matched = modelMap.find(([needle]) => text.includes(needle));
    return matched ? matched[1] : '';
  }

  function alignNumberList(values, count, fallback) {
    return Array.from({length: count}, (_, index) => (
      Number.isFinite(values[index]) ? values[index] : fallback
    ));
  }

  function releaseOwnedImage() {
    if (typeof activeImageCleanup === 'function') activeImageCleanup();
    activeImageCleanup = null;
  }

  function getRaw(data) {
    if (!data || typeof data !== 'object') return data;
    return Object.prototype.hasOwnProperty.call(data, 'raw') ? data.raw : data;
  }

  function metadataSources(data) {
    const summary = isObject(data?.summary) ? data.summary : {};
    const raw = getRaw(data);
    const extracted = isObject(raw?.extracted_metadata) ? raw.extracted_metadata : {};
    const generationParams = isObject(raw?.generation_params) ? raw.generation_params : {};
    const promptContext = isObject(raw?.prompt_context) ? raw.prompt_context : {};
    const apiMetadata = isObject(raw?.api_metadata) ? raw.api_metadata : {};
    const rawAsMetadata = isObject(raw) && !raw.extracted_metadata ? raw : {};
    const comment = tryParseJson(extracted.Comment || extracted.comment || rawAsMetadata.Comment || rawAsMetadata.comment);
    const extractedParams = isObject(extracted.parameters) ? extracted.parameters : {};
    const rawParams = isObject(rawAsMetadata.parameters) ? rawAsMetadata.parameters : {};
    return [
      summary,
      extracted,
      rawAsMetadata,
      isObject(comment) ? comment : {},
      extractedParams,
      rawParams,
      generationParams,
      apiMetadata,
      promptContext,
      isObject(raw?.image) ? raw.image : {},
    ].filter(source => isObject(source) && Object.keys(source).length > 0);
  }

  function findValue(data, aliases) {
    const sources = metadataSources(data);
    for (const source of sources) {
      for (const alias of aliases) {
        if (isPresent(source[alias])) return source[alias];
      }
    }
    return '';
  }

  function getPrompt(data) {
    const summaryPrompt = data?.summary?.prompt;
    return isPresent(summaryPrompt)
      ? summaryPrompt
      : findValue(data, ['prompt', 'input', '_raw_input', 'Description', 'description']);
  }

  function getNegative(data) {
    const summaryNegative = data?.summary?.negative;
    return isPresent(summaryNegative)
      ? summaryNegative
      : findValue(data, ['uc', 'negative', 'negative_prompt']);
  }

  function extractCharCaptions(promptData) {
    const parsed = tryParseJson(promptData);
    const captions = parsed?.caption?.char_captions;
    if (!Array.isArray(captions)) return [];
    return captions.map(item => {
      if (typeof item === 'string') return item;
      if (isObject(item)) return item.char_caption || '';
      return '';
    }).filter(isPresent);
  }

  function getCharacters(data) {
    const direct = normalizeArray(findValue(data, ['characters', 'char_captions']));
    if (direct.length) return direct;
    return extractCharCaptions(findValue(data, ['v4_prompt']));
  }

  function getCharacterNegatives(data) {
    const direct = normalizeArray(findValue(data, ['characters_uc', 'char_captions_uc']));
    if (direct.length) return direct;
    return extractCharCaptions(findValue(data, ['v4_negative_prompt']));
  }

  function formatCharacterPrompts(data) {
    const characters = getCharacters(data);
    const negatives = getCharacterNegatives(data);
    return characters.map((character, index) => {
      const lines = [`C${index + 1} Prompt: ${safeText(character)}`];
      if (isPresent(negatives[index])) lines.push(`C${index + 1} Negative: ${safeText(negatives[index])}`);
      return lines.join('\n');
    }).join('\n\n');
  }

  function getDimensions(data) {
    const width = findValue(data, ['width']);
    const height = findValue(data, ['height']);
    return {width, height};
  }

  function getModelInfo(data) {
    const software = findValue(data, ['Software', 'software']);
    const source = findValue(data, ['Source', 'source']);
    if (software === 'NovelAI' && source) return source;
    return source || findValue(data, ['model', 'Model', 'model_name', 'checkpoint']) || software || '';
  }

  function getVibeTransferData(data) {
    const referenceImages = normalizeStringList(findValue(data, ['reference_image_multiple']));
    if (!referenceImages.length) return null;

    const source = findValue(data, ['Source', 'source']);
    const sourceModel = modelFromSource(source);
    if (!sourceModel) return null;

    const strengths = alignNumberList(
      normalizeNumberList(findValue(data, ['reference_strength_multiple'])),
      referenceImages.length,
      0.6
    );
    const informationExtracted = normalizeNumberList(
      findValue(data, ['reference_information_extracted_multiple'])
    );
    const normalizeValue = findValue(data, ['normalize_reference_strength_multiple']);

    return {
      source,
      source_model: sourceModel,
      reference_image_multiple: referenceImages,
      reference_strength_multiple: strengths,
      reference_information_extracted_multiple: informationExtracted,
      normalize_reference_strength_multiple: isPresent(normalizeValue) ? normalizeBoolean(normalizeValue) : false,
    };
  }

  function formatParamValue(value) {
    if (typeof value === 'boolean') return value ? 'true' : 'false';
    if (Array.isArray(value)) return value.map(item => safeText(item)).join(', ');
    return safeText(value);
  }

  function buildParams(data, vibeTransfer = null) {
    const {width, height} = getDimensions(data);
    const resolution = width && height ? `${width} x ${height}` : findValue(data, ['resolution']);
    const fields = [
      {key: 'resolution', label: 'Resolution', value: resolution},
      {key: 'steps', label: 'Steps', value: findValue(data, ['steps'])},
      {key: 'cfg_scale', label: 'CFG Scale', value: findValue(data, ['cfg_scale', 'scale', 'cfg'])},
      {key: 'uncond_scale', label: 'UC Strength', value: findValue(data, ['uncond_scale', 'uc_strength'])},
      {key: 'cfg_rescale', label: 'CFG Rescale', value: findValue(data, ['cfg_rescale'])},
      {key: 'seed', label: 'Seed', value: findValue(data, ['seed'])},
      {key: 'sampler', label: 'Sampler', value: findValue(data, ['sampler', 'sampler_name'])},
      {key: 'scheduler', label: 'Scheduler', value: findValue(data, ['noise_schedule', 'scheduler'])},
      {key: 'sm', label: 'SMEA', value: findValue(data, ['sm'])},
      {key: 'sm_dyn', label: 'SMEA+DYN', value: findValue(data, ['sm_dyn'])},
      {key: 'VAR+', label: 'VAR+', value: findValue(data, ['VAR+', 'skip_cfg_above_sigma'])},
      {key: 'model', label: 'Model', value: findValue(data, ['model', 'Model', 'model_name', 'checkpoint'])},
      {key: 'Software', label: 'Software', value: findValue(data, ['Software', 'software'])},
      {key: 'Source', label: 'Source', value: findValue(data, ['Source', 'source'])},
      {key: 'Title', label: 'Title', value: findValue(data, ['Title', 'title'])},
      {key: 'Description', label: 'Description', value: findValue(data, ['Description', 'description'])},
      {
        key: 'vibe_transfer',
        label: 'Vibe Transfer',
        value: vibeTransfer
          ? `${vibeTransfer.reference_image_multiple.length} (${vibeTransfer.source_model})`
          : '',
      },
    ];
    const rows = fields.filter(field => isPresent(field.value));
    const canonical = {};
    rows.forEach(field => {
      canonical[field.key] = field.value;
    });
    return {rows, canonical};
  }

  function renderEmpty(message) {
    releaseOwnedImage();
    currentActionPayload = null;
    if (titleEl) titleEl.textContent = 'Metadata Viewer';
    if (previewEl) {
      previewEl.removeAttribute('src');
      previewEl.classList.remove('show');
    }
    if (previewEmptyEl) previewEmptyEl.textContent = 'No image selected';
    if (imageInfoEl) imageInfoEl.textContent = '';
    if (modelInfoEl) modelInfoEl.textContent = '';
    if (promptEl) promptEl.innerHTML = `<span class="metadata-empty">${escHtml(message)}</span>`;
    if (negativeEl) negativeEl.innerHTML = '';
    if (charactersTitleEl) charactersTitleEl.style.display = 'none';
    if (charactersEl) {
      charactersEl.style.display = 'none';
      charactersEl.innerHTML = '';
    }
    if (paramsEl) paramsEl.innerHTML = '';
    if (rawEl) rawEl.textContent = '';
    updateActionButtons();
  }

  function imageUrlForSource(source) {
    if (source.imageUrl) return source.imageUrl;
    if (source.kind === 'saved' && source.path) return '/api/viewer/image/' + encodeURI(source.path);
    return '';
  }

  function renderPreview(data, source) {
    const imageUrl = imageUrlForSource(source);
    const nextImageCleanup = source.revokeImageUrl || null;
    if (activeImageCleanup && activeImageCleanup !== nextImageCleanup) releaseOwnedImage();
    if (previewEl && imageUrl) {
      previewEl.src = imageUrl;
      previewEl.classList.add('show');
      activeImageCleanup = nextImageCleanup;
    } else if (previewEl) {
      previewEl.removeAttribute('src');
      previewEl.classList.remove('show');
      if (nextImageCleanup) releaseOwnedImage();
    }
    if (previewEmptyEl) previewEmptyEl.textContent = imageUrl ? '' : 'No image selected';

    const {width, height} = getDimensions(data);
    if (imageInfoEl) {
      if (width && height) {
        const ratio = Number(height) ? (Number(width) / Number(height)).toFixed(2) : '';
        imageInfoEl.textContent = `크기: ${width} x ${height}${ratio ? ` | 비율: ${ratio}` : ''}`;
      } else {
        imageInfoEl.textContent = '';
      }
    }

    if (modelInfoEl) {
      const modelInfo = getModelInfo(data);
      modelInfoEl.textContent = modelInfo ? `🤖 모델: ${modelInfo}` : '';
    }
    return imageUrl;
  }

  function renderPromptBlock(el, value, emptyText) {
    if (!el) return;
    const text = safeText(value);
    el.innerHTML = text
      ? escHtml(text)
      : `<span class="metadata-empty">${escHtml(emptyText)}</span>`;
  }

  function renderCharacters(data) {
    const text = formatCharacterPrompts(data);
    const hasCharacters = Boolean(text);
    if (charactersTitleEl) charactersTitleEl.style.display = hasCharacters ? '' : 'none';
    if (charactersEl) {
      charactersEl.style.display = hasCharacters ? '' : 'none';
      charactersEl.textContent = text;
    }
    return getCharacters(data);
  }

  function renderParams(paramRows) {
    if (!paramsEl) return;
    if (!paramRows.length) {
      paramsEl.innerHTML = '<span class="metadata-empty">No generation parameters</span>';
      return;
    }
    paramsEl.innerHTML = paramRows.map(field => {
      const valueText = formatParamValue(field.value);
      const classes = ['metadata-param-value'];
      if (typeof field.value === 'boolean') classes.push('boolean');
      if (valueText.length > 80 || valueText.includes('\n')) classes.push('long');
      return `
        <div class="metadata-param-key">${escHtml(field.label)}</div>
        <div class="${classes.join(' ')}">${escHtml(valueText)}</div>
      `;
    }).join('');
  }

  function renderRaw(data) {
    if (!rawEl) return;
    const raw = getRaw(data);
    const hasRaw = raw && (typeof raw !== 'object' || Object.keys(raw).length > 0);
    rawEl.textContent = hasRaw
      ? (typeof raw === 'string' ? raw : JSON.stringify(raw, null, 2))
      : 'No raw metadata';
  }

  function updateActionButtons() {
    const hasPayload = Boolean(currentActionPayload);
    const hasPrompt = hasPayload && (currentActionPayload.prompt || currentActionPayload.negative);
    const hasParams = hasPayload && Object.keys(currentActionPayload.params || {}).length > 0;
    const hasCharacters = hasPayload && (currentActionPayload.characters || []).length > 0;
    const hasVibeTransfer = hasPayload && Boolean(currentActionPayload.vibeTransfer);
    const hasImageActionSource = hasPayload && (currentActionPayload.blob || currentActionPayload.imageUrl);
    if (applyCharacterSettingsBtn) applyCharacterSettingsBtn.style.display = hasCharacters ? '' : 'none';
    if (restoreVibeBtn) {
      restoreVibeBtn.style.display = hasVibeTransfer ? '' : 'none';
      restoreVibeBtn.textContent = hasVibeTransfer
        ? `📦 Vibe Transfer 복원 (${currentActionPayload.vibeTransfer.source_model})`
        : '📦 Vibe Transfer 복원';
    }
    [
      [applyPromptBtn, typeof onApplyPrompt === 'function' && hasPrompt],
      [applySettingsBtn, typeof onApplySettings === 'function' && hasParams],
      [applyCharacterSettingsBtn, typeof onApplyCharacterSettings === 'function' && hasParams && hasCharacters],
      [restoreVibeBtn, typeof onRestoreVibeTransfer === 'function' && hasVibeTransfer],
      [sendImg2ImgBtn, typeof onSendImg2Img === 'function' && hasImageActionSource],
    ].forEach(([button, enabled]) => {
      if (!button) return;
      button.disabled = !enabled;
      button.title = enabled ? '' : 'Not connected yet';
    });
  }

  function render(data, source = currentSource) {
    const payload = data && typeof data === 'object' ? data : {};
    const label = payload.label || source.label || source.path || 'Input Image';
    const prompt = getPrompt(payload);
    const negative = getNegative(payload);
    const characters = renderCharacters(payload);
    const charactersUc = getCharacterNegatives(payload);
    const vibeTransfer = getVibeTransferData(payload);
    const {rows, canonical} = buildParams(payload, vibeTransfer);
    if (titleEl) titleEl.textContent = label;
    const imageUrl = renderPreview(payload, source);
    renderPromptBlock(promptEl, prompt, 'No prompt metadata');
    renderPromptBlock(negativeEl, negative, 'No negative metadata');
    renderParams(rows);
    renderRaw(payload);
    currentActionPayload = {
      data: payload,
      source,
      label,
      blob: source.blob || null,
      imageUrl,
      prompt,
      negative,
      params: canonical,
      characters,
      charactersUc,
      vibeTransfer,
    };
    updateActionButtons();
    setStatus(payload.has_metadata === false ? 'No metadata' : 'Loaded', payload.has_metadata === false ? 'muted' : 'ok');
  }

  function buildRequest(source) {
    if (source.kind === 'payload' && source.payload) {
      return {
        payload: source.payload,
      };
    }
    if (source.kind === 'saved' && source.path) {
      return {
        url: '/api/viewer/meta/' + encodeURI(source.path) + '?full=1',
        init: {},
      };
    }
    if (source.kind === 'input' && source.blob) {
      const label = encodeURIComponent(source.label || 'Input Image');
      return {
        url: '/api/metadata/extract?label=' + label,
        init: {
          method: 'POST',
          headers: {'Content-Type': source.blob.type || 'application/octet-stream'},
          body: source.blob,
        },
      };
    }
    return null;
  }

  function unavailableMessage(source) {
    if (source.kind === 'saved') return 'Metadata unavailable';
    if (source.kind === 'input') return 'Input image metadata unavailable';
    return 'No image selected';
  }

  async function loadSource(source = currentSource, options = {}) {
    const requestId = ++requestSerial;
    const nextSource = source || EMPTY_SOURCE;
    loading = true;
    currentSource = nextSource;
    if (refreshBtn) refreshBtn.disabled = true;
    if (!options.silent) setStatus('Loading...', 'busy');

    try {
      const request = buildRequest(nextSource);
      if (!request) {
        renderEmpty(unavailableMessage(nextSource));
        setStatus('Idle', 'muted');
        return;
      }
      if (request.payload) {
        if (requestId !== requestSerial) return;
        render(request.payload, nextSource);
        return;
      }
      const response = await fetch(request.url, request.init);
      if (!response.ok) {
        const error = new Error(`HTTP ${response.status}`);
        error.status = response.status;
        throw error;
      }
      const data = await response.json();
      if (requestId !== requestSerial) return;
      if (nextSource.kind === 'saved' && nextSource.path && data && typeof data === 'object') {
        data.label = nextSource.path;
        data.source = 'saved';
      } else if (nextSource.kind === 'input' && data && typeof data === 'object') {
        data.label = nextSource.label || data.label || 'Input Image';
        data.source = 'input';
      }
      render(data, nextSource);
    } catch (error) {
      if (requestId !== requestSerial) return;
      renderEmpty(unavailableMessage(nextSource));
      setStatus('Unavailable', 'error');
      if (!options.silent && showToast) showToast('Failed to load metadata', 'error');
    } finally {
      if (requestId === requestSerial) {
        loading = false;
        if (refreshBtn) refreshBtn.disabled = false;
      }
    }
  }

  function loadCurrent(options = {}) {
    return loadSource(EMPTY_SOURCE, options);
  }

  function loadSaved(path, options = {}) {
    if (!path) return loadSource(EMPTY_SOURCE, options);
    return loadSource({kind: 'saved', path}, options);
  }

  function loadImageBlob(blob, label = 'Input Image', options = {}) {
    if (!blob) return Promise.resolve();
    return loadSource({
      kind: 'input',
      path: '',
      label,
      blob,
      imageUrl: options.imageUrl || '',
      revokeImageUrl: options.revokeImageUrl || null,
    }, options);
  }

  function displayPayload(data, options = {}) {
    if (!data) return Promise.resolve(false);
    const payload = {...data};
    if (options.label) payload.label = options.label;
    loadSource({
      kind: 'payload',
      path: '',
      label: payload.label || 'Input Image',
      payload,
      blob: options.blob || null,
      imageUrl: options.imageUrl || '',
      revokeImageUrl: options.revokeImageUrl || null,
    }, {silent: true});
    return Promise.resolve(true);
  }

  function refresh() {
    return loadSource(currentSource || EMPTY_SOURCE, {silent: false});
  }

  function switchDetailTab(tabName) {
    document.querySelectorAll('[data-metadata-detail-tab]').forEach(button => {
      button.classList.toggle('active', button.dataset.metadataDetailTab === tabName);
    });
    document.querySelectorAll('[data-metadata-detail-pane]').forEach(pane => {
      pane.classList.toggle('active', pane.dataset.metadataDetailPane === tabName);
    });
  }

  function bindDetailTabs() {
    document.querySelectorAll('[data-metadata-detail-tab]').forEach(button => {
      button.addEventListener('click', () => switchDetailTab(button.dataset.metadataDetailTab || 'params'));
    });
  }

  function bindAction(button, handler) {
    if (!button) return;
    button.addEventListener('click', () => {
      if (button.disabled || !currentActionPayload || typeof handler !== 'function') return;
      handler(currentActionPayload);
    });
  }

  bindDetailTabs();
  bindAction(applyPromptBtn, onApplyPrompt);
  bindAction(applySettingsBtn, onApplySettings);
  bindAction(applyCharacterSettingsBtn, onApplyCharacterSettings);
  bindAction(restoreVibeBtn, onRestoreVibeTransfer);
  bindAction(sendImg2ImgBtn, onSendImg2Img);
  renderEmpty('No image selected');
  setStatus('Idle', 'muted');

  return {
    loadCurrent,
    loadSaved,
    loadImageBlob,
    displayPayload,
    refresh,
  };
}
