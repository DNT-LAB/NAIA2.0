export function createImageModulePanels({
  document,
  moduleBody,
  escHtml,
  setModuleParam,
  showToast,
  openModule,
  getCurrentModuleId,
  navigatorRef = globalThis.navigator,
  ImageCtor = globalThis.Image,
  FileReaderCtor = globalThis.FileReader,
  FileCtor = globalThis.File,
  setTimeoutFn = globalThis.setTimeout,
  clearTimeoutFn = globalThis.clearTimeout,
}) {
  const sliderDebounce = {};
  let storageView = null;

  function pasteImage(moduleId) {
    navigatorRef.clipboard.read().then(items => {
      for (const item of items) {
        const imageType = item.types.find(type => type.startsWith('image/'));
        if (imageType) {
          item.getType(imageType).then(blob => {
            uploadImage(moduleId, new FileCtor([blob], 'clipboard.png', { type: blob.type }));
          });
          return;
        }
      }
      showToast('No image in clipboard', 'error');
    }).catch(() => showToast('Clipboard access denied', 'error'));
  }

  function uploadImage(moduleId, file) {
    if (!file || !file.type.startsWith('image/')) return;
    const body = document.getElementById('modulePopupBody') || moduleBody;
    if (body) {
      const indicator = document.createElement('div');
      indicator.className = 'mod-upload-indicator';
      indicator.textContent = 'Uploading...';
      indicator.id = 'uploadIndicator';
      body.prepend(indicator);
    }

    const img = new ImageCtor();
    const reader = new FileReaderCtor();
    reader.onload = () => {
      img.onload = () => {
        let width = img.width;
        let height = img.height;
        const maxSize = 2048;
        if (width > maxSize || height > maxSize) {
          if (width > height) {
            height = Math.round(height * maxSize / width);
            width = maxSize;
          } else {
            width = Math.round(width * maxSize / height);
            height = maxSize;
          }
        }
        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = height;
        canvas.getContext('2d').drawImage(img, 0, 0, width, height);
        const dataUrl = canvas.toDataURL('image/png');
        const b64 = dataUrl.split(',')[1];
        setModuleParam(moduleId, 'upload_image', b64);
      };
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  }

  function onSlider(moduleId, key, value) {
    const debounceKey = moduleId + '.' + key;
    if (sliderDebounce[debounceKey]) clearTimeoutFn(sliderDebounce[debounceKey]);
    sliderDebounce[debounceKey] = setTimeoutFn(() => {
      setModuleParam(moduleId, key, value);
      delete sliderDebounce[debounceKey];
    }, 300);
  }

  function renderCharacterReference(message) {
    if (!message.is_naid45) {
      moduleBody.innerHTML = '<div class="mod-notice">Character Reference requires NAID4.5F/C model</div>';
      return;
    }
    const frames = (message.frames || []).map((frame, index) => `
    <div class="mod-ref-frame ${frame.is_enabled ? '' : 'disabled'}">
      <div class="mod-ref-header">
        <img class="mod-ref-thumb" src="data:image/jpeg;base64,${frame.thumbnail}" alt="${escHtml(frame.file_name)}">
        <div class="mod-ref-controls">
          <div class="mod-ref-controls-row">
            <label class="mod-checkbox-item">
              <input type="checkbox" ${frame.is_enabled ? 'checked' : ''}
                oninput="setModuleParam('character_reference','enable_${index}',String(this.checked))">
              <span class="mod-checkbox-label">Enable</span>
            </label>
            <select class="mod-select-sm"
              onchange="setModuleParam('character_reference','ref_type_${index}',this.value)">
              <option value="character&style" ${frame.reference_type==='character&style'?'selected':''}>Char & Style</option>
              <option value="character" ${frame.reference_type==='character'?'selected':''}>Character</option>
              <option value="style" ${frame.reference_type==='style'?'selected':''}>Style</option>
            </select>
            <button class="mod-btn-sm mod-btn-danger" onclick="setModuleParam('character_reference','remove_frame_${index}','')">Remove</button>
          </div>
          <div class="mod-slider-row">
            <span class="mod-slider-label">Strength</span>
            <input type="range" min="0" max="20" step="1" value="${Math.round(frame.strength*20)}"
              oninput="this.nextElementSibling.textContent=(this.value/20).toFixed(2);onModSlider('character_reference','strength_${index}',(this.value/20).toFixed(2))">
            <span class="mod-slider-value">${frame.strength.toFixed(2)}</span>
          </div>
          <div class="mod-slider-row">
            <span class="mod-slider-label">Fidelity</span>
            <input type="range" min="0" max="20" step="1" value="${Math.round(frame.fidelity*20)}"
              oninput="this.nextElementSibling.textContent=(this.value/20).toFixed(2);onModSlider('character_reference','fidelity_${index}',(this.value/20).toFixed(2))">
            <span class="mod-slider-value">${frame.fidelity.toFixed(2)}</span>
          </div>
        </div>
      </div>
    </div>
  `).join('');

    moduleBody.innerHTML = `
    <div class="mod-upload-bar">
      <button class="mod-btn-upload" onclick="document.getElementById('charRefFileInput').click()">Upload</button>
      <button class="mod-btn-upload" onclick="pasteModuleImage('character_reference')">Paste</button>
      <input type="file" id="charRefFileInput" accept="image/*" style="display:none"
        onchange="uploadModuleImage('character_reference',this.files[0]);this.value=''">
      <button class="mod-btn-upload mod-btn-storage" onclick="requestStorage('character_reference')">Storage</button>
    </div>
    ${frames.length ? frames : '<div class="mod-empty">No character references loaded</div>'}
  `;
  }

  function renderVibeTransfer(message) {
    const frames = (message.frames || []).map((frame, index) => {
      const thumbHtml = frame.is_no_image
        ? '<div class="mod-ref-noimage">No Image</div>'
        : `<img class="mod-ref-thumb" src="data:image/jpeg;base64,${frame.thumbnail}" alt="${escHtml(frame.file_name)}">`;

      const encHtml = frame.is_no_image ? '' : `
      <div class="mod-ref-encoding">
        ${frame.has_encoding
          ? '<span class="mod-encode-status encoded">Encoded</span>'
          : `<button class="mod-btn-sm mod-btn-encode" onclick="setModuleParam('vibe_transfer','encode_${index}','')">Encode (2 Anlas)</button>`}
        ${frame.encoding_keys.length ? `<span class="mod-encode-keys">IE: ${frame.encoding_keys.map(key => Number(key).toFixed(2)).join(', ')}</span>` : ''}
      </div>`;

      return `
    <div class="mod-ref-frame ${frame.is_enabled ? '' : 'disabled'}">
      <div class="mod-ref-header">
        ${thumbHtml}
        <div class="mod-ref-controls">
          <div class="mod-ref-controls-row">
            <label class="mod-checkbox-item">
              <input type="checkbox" ${frame.is_enabled ? 'checked' : ''}
                oninput="setModuleParam('vibe_transfer','enable_${index}',String(this.checked))">
              <span class="mod-checkbox-label">Enable</span>
            </label>
            <button class="mod-btn-sm mod-btn-danger" onclick="setModuleParam('vibe_transfer','remove_frame_${index}','')">Remove</button>
          </div>
          <div class="mod-slider-row">
            <span class="mod-slider-label">Ref Strength</span>
            <input type="range" min="-100" max="100" step="1" value="${Math.round(frame.reference_strength*100)}"
              oninput="this.nextElementSibling.textContent=(this.value/100).toFixed(2);onModSlider('vibe_transfer','ref_strength_${index}',(this.value/100).toFixed(2))">
            <span class="mod-slider-value">${frame.reference_strength.toFixed(2)}</span>
          </div>
          <div class="mod-slider-row">
            <span class="mod-slider-label">Info Extracted</span>
            <input type="range" min="1" max="100" step="1" value="${Math.round(frame.information_extracted*100)}"
              oninput="this.nextElementSibling.textContent=(this.value/100).toFixed(2);onModSlider('vibe_transfer','info_extracted_${index}',(this.value/100).toFixed(2))">
            <span class="mod-slider-value">${frame.information_extracted.toFixed(2)}</span>
          </div>
          ${encHtml}
        </div>
      </div>
    </div>`;
    }).join('');

    moduleBody.innerHTML = `
    <div class="mod-upload-bar">
      <button class="mod-btn-upload" onclick="document.getElementById('vibeFileInput').click()">Upload</button>
      <button class="mod-btn-upload" onclick="pasteModuleImage('vibe_transfer')">Paste</button>
      <input type="file" id="vibeFileInput" accept="image/*" style="display:none"
        onchange="uploadModuleImage('vibe_transfer',this.files[0]);this.value=''">
      <button class="mod-btn-upload mod-btn-storage" onclick="requestStorage('vibe_transfer')">Storage</button>
      <span class="mod-frame-count">${message.frame_count}/${message.max_frames}</span>
    </div>
    <label class="mod-checkbox-item" style="margin-bottom:8px">
      <input type="checkbox" ${message.normalize ? 'checked' : ''}
        oninput="setModuleParam('vibe_transfer','normalize',String(this.checked))">
      <span class="mod-checkbox-label">Normalize reference strength</span>
    </label>
    ${frames.length ? frames : '<div class="mod-empty">No vibe transfers loaded</div>'}
  `;
  }

  function requestStorage(moduleId) {
    storageView = moduleId;
    setModuleParam(moduleId, 'get_storage', '');
  }

  function onStorageList(message) {
    if (message.module_id === 'character_reference') renderCharRefStorage(message);
    else if (message.module_id === 'vibe_transfer') renderVibeStorage(message);
  }

  function renderCharRefStorage(message) {
    if (getCurrentModuleId() !== 'character_reference') return;
    const items = (message.items || []).map(item => `
    <div class="mod-storage-item" onclick="applyCharRefStorage('${escHtml(item.file_hash)}')" title="${escHtml(item.file_name)}">
      <img class="mod-storage-thumb" src="data:image/jpeg;base64,${item.thumbnail}" alt="">
      <span class="mod-storage-name">${escHtml(item.character_name || item.file_name)}</span>
    </div>
  `).join('');

    moduleBody.innerHTML = `
    <div class="mod-upload-bar">
      <button class="mod-btn-upload" onclick="setModuleParam('character_reference','get_storage','');/* refresh */">Refresh</button>
      <button class="mod-btn-sm" onclick="openModule('character_reference')">Back</button>
    </div>
    ${items.length
      ? '<div class="mod-storage-grid">' + items + '</div>'
      : '<div class="mod-empty">No saved references</div>'}
  `;
  }

  function applyCharRefStorage(fileHash) {
    setModuleParam('character_reference', 'apply_storage', fileHash);
    setTimeoutFn(() => openModule('character_reference'), 500);
  }

  function renderVibeStorage(message) {
    if (getCurrentModuleId() !== 'vibe_transfer') return;
    const modelNames = Object.keys(message.models || {});
    const currentModel = message.current_model || '';

    const tabBtns = modelNames.map(name =>
      `<button class="mod-btn-sm mod-storage-tab ${name===currentModel?'active':''}" onclick="showVibeStorageTab(this,'${escHtml(name)}')">${escHtml(name)}</button>`
    ).join('');

    const tabContents = modelNames.map(name => {
      const items = (message.models[name] || []).map(item => {
        const ieKeys = (item.encoding_keys || []);
        const defaultIe = ieKeys.length ? ieKeys[0] : 1.0;
        return `
        <div class="mod-storage-item" onclick="applyVibeStorage('${escHtml(name)}','${escHtml(item.file_hash)}',${defaultIe})" title="${escHtml(item.file_name)}">
          <img class="mod-storage-thumb" src="data:image/jpeg;base64,${item.thumbnail}" alt="">
          <span class="mod-storage-name">${escHtml(item.file_name)}</span>
          ${ieKeys.length ? `<span class="mod-encode-keys">IE: ${ieKeys.map(key => Number(key).toFixed(2)).join(', ')}</span>` : ''}
        </div>`;
      }).join('');
      const vis = name === currentModel ? '' : 'style="display:none"';
      return `<div class="mod-storage-grid mod-vibe-tab" data-model="${escHtml(name)}" ${vis}>${items || '<div class="mod-empty">Empty</div>'}</div>`;
    }).join('');

    moduleBody.innerHTML = `
    <div class="mod-upload-bar">
      <button class="mod-btn-upload" onclick="setModuleParam('vibe_transfer','get_storage','')">Refresh</button>
      <button class="mod-btn-sm" onclick="openModule('vibe_transfer')">Back</button>
    </div>
    <div class="mod-storage-tabs">${tabBtns}</div>
    ${tabContents || '<div class="mod-empty">No saved vibes</div>'}
  `;
  }

  function showVibeStorageTab(btn, model) {
    btn.parentElement.querySelectorAll('.mod-storage-tab').forEach(button => button.classList.remove('active'));
    btn.classList.add('active');
    moduleBody.querySelectorAll('.mod-vibe-tab').forEach(element => {
      element.style.display = element.dataset.model === model ? '' : 'none';
    });
  }

  function applyVibeStorage(model, fileHash, ieValue) {
    setModuleParam('vibe_transfer', 'apply_storage', model + '|' + fileHash + '|' + ieValue);
  }

  function getStorageView() {
    return storageView;
  }

  return {
    pasteImage,
    uploadImage,
    onSlider,
    renderCharacterReference,
    renderVibeTransfer,
    requestStorage,
    onStorageList,
    renderCharRefStorage,
    applyCharRefStorage,
    renderVibeStorage,
    showVibeStorageTab,
    applyVibeStorage,
    getStorageView,
  };
}
