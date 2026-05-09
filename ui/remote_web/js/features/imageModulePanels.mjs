export function createImageModulePanels({
  document,
  moduleBody,
  escHtml,
  setModuleParam,
  showToast,
  openModule,
  getCurrentModuleId,
  navigatorRef = globalThis.navigator,
  fetchFn = globalThis.fetch,
  useNativeClipboardFallback = () => false,
  ImageCtor = globalThis.Image,
  FileReaderCtor = globalThis.FileReader,
  FileCtor = globalThis.File,
  setTimeoutFn = globalThis.setTimeout,
  clearTimeoutFn = globalThis.clearTimeout,
  modulePopup = null,
  positionFloatingPanel = null,
}) {
  const sliderDebounce = {};
  let storageView = null;
  let vibeClusterListOpen = false;
  let vibeClusterSaveOpen = false;
  let vibeClusterShowListAfterSave = false;
  let vibeClusterItems = [];
  let vibeClusterPendingThumb = '';
  let vibeClusterThumbTarget = '';
  const VIBE_CLUSTER_NAME_PATTERN = /^[A-Za-z0-9가-힣ㄱ-ㅎㅏ-ㅣ]+$/;
  const VIBE_CLUSTER_NAME_HINT = 'Vibe cluster name must use letters, numbers, and Korean only.';

  function getVibeClusterHost() {
    return document.body;
  }

  function getVibeClusterPanel() {
    return document.querySelector('.vibe-cluster-popover');
  }

  function getVibeClusterSavePanel() {
    return document.querySelector('.vibe-cluster-save-popover');
  }

  function queryVibeClusterPanel(selector) {
    return getVibeClusterPanel()?.querySelector(selector) || null;
  }

  function queryVibeClusterSavePanel(selector) {
    return getVibeClusterSavePanel()?.querySelector(selector) || null;
  }

  function relayoutVibeClusterPanel() {
    if (positionFloatingPanel) {
      const panels = [getVibeClusterPanel(), getVibeClusterSavePanel()].filter(Boolean);
      panels.forEach(panel => {
        if (panel.classList.contains('open')) positionFloatingPanel(panel, modulePopup);
      });
    }
  }

  function renderVibeClusterListHiddenInput() {
    return `
      <input type="file" id="vibeClusterManageThumbInput" accept="image/*" style="display:none"
        onchange="updateVibeClusterThumbnailFromFile(vibeClusterThumbTarget(),this.files[0]);this.value=''">`;
  }

  function closeVibeClusterListPanel() {
    vibeClusterListOpen = false;
    const panel = getVibeClusterPanel();
    if (panel) panel.remove();
  }

  function closeVibeClusterSavePanel(options = {}) {
    vibeClusterSaveOpen = false;
    vibeClusterShowListAfterSave = false;
    if (options.clearThumb !== false) vibeClusterPendingThumb = '';
    const panel = getVibeClusterSavePanel();
    if (panel) panel.remove();
  }

  function closeAllVibeClusterPanels() {
    closeVibeClusterListPanel();
    closeVibeClusterSavePanel();
  }

  function isValidVibeClusterName(name) {
    return VIBE_CLUSTER_NAME_PATTERN.test(String(name || ''));
  }

  function filterVibeClusterNameInput(input) {
    if (!input) return '';
    const filtered = String(input.value || '').replace(/[^A-Za-z0-9가-힣ㄱ-ㅎㅏ-ㅣ]/g, '');
    if (input.value !== filtered) input.value = filtered;
    input.classList.toggle('invalid', Boolean(input.value) && !isValidVibeClusterName(input.value));
    return input.value;
  }

  function renderVibeClusterSavePanel() {
    const existing = getVibeClusterSavePanel();
    if (existing) existing.remove();

    const panel = document.createElement('div');
    panel.className = 'vibe-cluster-save-popover open';
    panel.innerHTML = `
      <div class="vibe-cluster-header">
        <h3>Make Vibe Cluster</h3>
        <button class="mod-btn-sm" onclick="closeVibeClusterSavePanel()">Close</button>
      </div>
      <div class="vibe-cluster-save">
        <input id="vibeClusterName" class="vibe-cluster-input" type="text" placeholder="Name" spellcheck="false"
          autocomplete="off" pattern="[A-Za-z0-9가-힣ㄱ-ㅎㅏ-ㅣ]+" title="${VIBE_CLUSTER_NAME_HINT}">
        <textarea id="vibeClusterDesc" class="vibe-cluster-textarea" placeholder="Description"></textarea>
        <div class="vibe-cluster-thumb-row">
          <div class="vibe-cluster-save-thumb">${vibeClusterPendingThumb ? `<img src="${vibeClusterPendingThumb}" alt="">` : '<span>Thumb</span>'}</div>
          <button class="mod-btn-sm" onclick="document.getElementById('vibeClusterSaveThumbInput').click()">Upload Thumb</button>
          <button class="mod-btn-sm" onclick="pasteVibeClusterThumbnail()">Paste Thumb</button>
          <button class="mod-btn-upload" onclick="saveVibeCluster()">Save Current</button>
        </div>
        <input type="file" id="vibeClusterSaveThumbInput" accept="image/*" style="display:none"
          onchange="setVibeClusterSaveThumbnail(this.files[0]);this.value=''">
      </div>
    `;
    getVibeClusterHost().appendChild(panel);
    panel.querySelector('#vibeClusterName')?.addEventListener('input', event => {
      filterVibeClusterNameInput(event.currentTarget);
    });
    relayoutVibeClusterPanel();
  }

  function openVibeClusterListPanel(message = {}) {
    if (!message || !Object.keys(message).length) {
      closeVibeClusterSavePanel();
    }
    vibeClusterListOpen = true;
    renderVibeClusterPanel(message);
    if (!message || !Object.keys(message).length) {
      setModuleParam('vibe_transfer', 'cluster_list', '');
    }
  }

  function openVibeClusterSavePanel() {
    closeVibeClusterListPanel();
    vibeClusterSaveOpen = true;
    vibeClusterShowListAfterSave = false;
    vibeClusterPendingThumb = '';
    renderVibeClusterSavePanel();
  }

  async function readBrowserClipboardImageBlob() {
    if (!navigatorRef?.clipboard?.read) {
      throw new Error('Clipboard image read is unavailable');
    }
    const items = await navigatorRef.clipboard.read();
    for (const item of items) {
      const imageType = item.types.find(type => type.startsWith('image/'));
      if (!imageType) continue;
      return item.getType(imageType);
    }
    throw new Error('No image in clipboard');
  }

  async function readNativeClipboardImageBlob() {
    if (typeof fetchFn !== 'function') {
      throw new Error('Clipboard fallback is unavailable');
    }
    const response = await fetchFn('/api/clipboard/png', {cache: 'no-store'});
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || `Clipboard read failed: HTTP ${response.status}`);
    }
    return response.blob();
  }

  async function readClipboardImageBlob() {
    let browserError = null;
    if (useNativeClipboardFallback()) {
      try {
        return await readNativeClipboardImageBlob();
      } catch (error) {
        browserError = error;
      }
    }

    try {
      return await readBrowserClipboardImageBlob();
    } catch (error) {
      browserError = error;
    }

    throw browserError || new Error('No image in clipboard');
  }

  function fileFromClipboardBlob(blob, filename) {
    return new FileCtor([blob], filename, {type: blob.type || 'image/png'});
  }

  async function pasteImage(moduleId) {
    try {
      const blob = await readClipboardImageBlob();
      uploadImage(moduleId, fileFromClipboardBlob(blob, 'clipboard.png'));
    } catch (error) {
      console.error('Image clipboard paste failed', error);
      showToast(error.message || 'Clipboard access denied', 'error');
    }
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

  function readVibeClusterThumbnail(file, onDone) {
    if (!file || !file.type.startsWith('image/')) return;
    const img = new ImageCtor();
    const reader = new FileReaderCtor();
    reader.onload = () => {
      img.onload = () => {
        const canvas = document.createElement('canvas');
        canvas.width = 512;
        canvas.height = 512;
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = '#000';
        ctx.fillRect(0, 0, 512, 512);
        const scale = Math.min(512 / img.width, 512 / img.height);
        const width = Math.max(1, Math.round(img.width * scale));
        const height = Math.max(1, Math.round(img.height * scale));
        ctx.drawImage(img, Math.round((512 - width) / 2), Math.round((512 - height) / 2), width, height);
        onDone(canvas.toDataURL('image/png'));
      };
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  }

  async function pasteVibeClusterThumbnail(targetId = '') {
    try {
      const blob = await readClipboardImageBlob();
      const file = fileFromClipboardBlob(blob, 'cluster-thumbnail.png');
      if (targetId) updateVibeClusterThumbnailFromFile(targetId, file);
      else setVibeClusterSaveThumbnail(file);
    } catch (error) {
      console.error('Vibe cluster thumbnail paste failed', error);
      showToast(error.message || 'Clipboard access denied', 'error');
    }
  }

  function setVibeClusterSaveThumbnail(file) {
    readVibeClusterThumbnail(file, dataUrl => {
      vibeClusterPendingThumb = dataUrl;
      const preview = queryVibeClusterSavePanel('.vibe-cluster-save-thumb');
      if (preview) preview.innerHTML = `<img src="${dataUrl}" alt="">`;
    });
  }

  function onSlider(moduleId, key, value) {
    const debounceKey = moduleId + '.' + key;
    if (sliderDebounce[debounceKey]) clearTimeoutFn(sliderDebounce[debounceKey]);
    sliderDebounce[debounceKey] = setTimeoutFn(() => {
      setModuleParam(moduleId, key, value);
      delete sliderDebounce[debounceKey];
    }, 300);
  }

  function formatIe(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return '1.00';
    const clamped = Math.max(0.01, Math.min(1, Math.round(number * 100) / 100));
    return clamped.toFixed(2);
  }

  function getEncodedIeValues(frame) {
    return (frame.encoding_keys || [])
      .map(key => Number(key))
      .filter(Number.isFinite)
      .sort((a, b) => a - b);
  }

  function hasEncodedIe(keys, ieText) {
    const ie = Number(ieText);
    return keys.some(key => Math.abs(key - ie) < 0.000001);
  }

  function formatRefStrength(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return null;
    const clamped = Math.max(-1, Math.min(1, Math.round(number * 100) / 100));
    return clamped.toFixed(2);
  }

  function getVibeFrameElement(index) {
    return moduleBody.querySelector(`.mod-ref-frame[data-vibe-index="${index}"]`);
  }

  function getFrameEncodedKeys(frameElement) {
    return (frameElement?.dataset.encodingKeys || '')
      .split(',')
      .map(value => Number(value))
      .filter(Number.isFinite);
  }

  function updateVibeIeDraft(index, rawValue) {
    const frameElement = getVibeFrameElement(index);
    if (!frameElement) return null;
    const ieText = formatIe(Number(rawValue) / 100);
    const encodedKeys = getFrameEncodedKeys(frameElement);
    const encoded = hasEncodedIe(encodedKeys, ieText);
    const canEncode = frameElement.dataset.canEncode === 'true';
    const sliderValue = frameElement.querySelector('.mod-vibe-ie-value');
    const encodeButton = frameElement.querySelector('[data-vibe-encode-btn]');
    const status = frameElement.querySelector('[data-vibe-encode-status]');
    const chips = frameElement.querySelectorAll('.mod-ie-chip');

    frameElement.dataset.pendingIe = ieText;
    if (sliderValue) sliderValue.textContent = ieText;

    if (status) {
      status.classList.toggle('encoded', encoded);
      status.classList.toggle('pending', !encoded);
      status.textContent = encoded ? `Encoded IE ${ieText}` : `Encode required for IE ${ieText}`;
    }

    if (encodeButton) {
      encodeButton.dataset.ie = ieText;
      encodeButton.textContent = `Encode IE ${ieText}`;
      encodeButton.classList.toggle('hidden', encoded || !canEncode);
    }

    chips.forEach(chip => {
      chip.classList.toggle('active', Math.abs(Number(chip.dataset.ie) - Number(ieText)) < 0.000001);
    });
    frameElement.classList.toggle('needs-encoding', canEncode && !encoded);
    return {ieText, encoded};
  }

  function commitVibeIeDraft(index, rawValue) {
    const draft = updateVibeIeDraft(index, rawValue);
    if (draft?.encoded) {
      setModuleParam('vibe_transfer', `info_extracted_${index}`, draft.ieText);
    }
  }

  function selectVibeEncoding(index, ieValue) {
    const ieText = formatIe(ieValue);
    const frameElement = getVibeFrameElement(index);
    const slider = frameElement?.querySelector('.mod-vibe-ie-slider');
    if (slider) slider.value = String(Math.round(Number(ieText) * 100));
    updateVibeIeDraft(index, Number(ieText) * 100);
    setModuleParam('vibe_transfer', `info_extracted_${index}`, ieText);
  }

  function encodeVibeFrame(index) {
    const frameElement = getVibeFrameElement(index);
    if (!frameElement || frameElement.dataset.canEncode !== 'true') return;
    const slider = frameElement.querySelector('.mod-vibe-ie-slider');
    const ieText = frameElement.dataset.pendingIe || formatIe((Number(slider?.value) || 100) / 100);
    const encodeButton = frameElement.querySelector('[data-vibe-encode-btn]');
    if (encodeButton) {
      encodeButton.disabled = true;
      encodeButton.textContent = 'Encoding...';
    }
    setModuleParam('vibe_transfer', `encode_${index}`, ieText);
  }

  function updateVibeRefStrengthDraft(index, rawValue, source = '') {
    const frameElement = getVibeFrameElement(index);
    if (!frameElement) return null;
    const strengthText = formatRefStrength(rawValue);
    const slider = frameElement.querySelector('.mod-vibe-rs-slider');
    const input = frameElement.querySelector('.mod-vibe-rs-input');
    if (!strengthText) {
      if (input) input.classList.add('invalid');
      return null;
    }

    frameElement.dataset.pendingRs = strengthText;
    if (slider && source !== 'slider') slider.value = String(Math.round(Number(strengthText) * 100));
    if (input) {
      input.classList.remove('invalid');
      if (source !== 'input') input.value = strengthText;
    }
    return strengthText;
  }

  function commitVibeRefStrength(index, rawValue) {
    const frameElement = getVibeFrameElement(index);
    if (!frameElement) return;
    let strengthText = updateVibeRefStrengthDraft(index, rawValue);
    if (!strengthText) {
      strengthText = frameElement.dataset.pendingRs || '0.00';
      updateVibeRefStrengthDraft(index, strengthText);
    }
    setModuleParam('vibe_transfer', `ref_strength_${index}`, strengthText);
  }

  function renderVibeEncodingControls(frame, index) {
    const encodedKeys = getEncodedIeValues(frame);
    const currentIe = formatIe(frame.information_extracted);
    const hasCurrentEncoding = hasEncodedIe(encodedKeys, currentIe);
    const canEncode = !frame.is_no_image && !frame.is_naid3 && !frame.encoding_in_progress;
    const keyData = encodedKeys.map(formatIe).join(',');
    const frameFlags = [
      `data-vibe-index="${index}"`,
      `data-pending-ie="${currentIe}"`,
      `data-encoding-keys="${keyData}"`,
      `data-can-encode="${canEncode ? 'true' : 'false'}"`,
    ].join(' ');
    const encodedChips = encodedKeys.map(key => {
      const keyText = formatIe(key);
      const active = Math.abs(Number(keyText) - Number(currentIe)) < 0.000001 ? ' active' : '';
      return `<button class="mod-ie-chip${active}" data-ie="${keyText}" onclick="selectVibeEncoding(${index},${keyText})">${keyText}</button>`;
    }).join('');

    if (frame.is_no_image) {
      return {
        frameFlags,
        html: `
          <div class="mod-vibe-encode-row">
            <span class="mod-encode-status encoded">Stored encoded vibe</span>
            ${encodedChips ? `<div class="mod-ie-chip-list">${encodedChips}</div>` : ''}
          </div>`,
      };
    }

    const statusText = frame.encoding_in_progress
      ? `Encoding IE ${currentIe}...`
      : hasCurrentEncoding
        ? `Encoded IE ${currentIe}`
        : `Encode required for IE ${currentIe}`;
    const statusClass = hasCurrentEncoding ? 'encoded' : 'pending';
    const encodeHidden = hasCurrentEncoding || frame.encoding_in_progress || frame.is_naid3 ? ' hidden' : '';
    const encodeDisabled = frame.encoding_in_progress ? ' disabled' : '';

    return {
      frameFlags,
      html: `
          <div class="mod-slider-row mod-vibe-ie-row">
            <span class="mod-slider-label">Info Extracted</span>
            <input class="mod-vibe-ie-slider" type="range" min="1" max="100" step="1" value="${Math.round(Number(currentIe) * 100)}"
              oninput="onVibeIeDraft(${index},this.value)"
              onchange="commitVibeIeDraft(${index},this.value)">
            <span class="mod-slider-value mod-vibe-ie-value">${currentIe}</span>
          </div>
          <div class="mod-vibe-encode-row">
            <button class="mod-btn-sm mod-btn-encode${encodeHidden}" data-vibe-encode-btn data-ie="${currentIe}" onclick="encodeVibeFrame(${index})"${encodeDisabled}>Encode IE ${currentIe}</button>
            <span class="mod-encode-status ${statusClass}" data-vibe-encode-status>${statusText}</span>
            ${encodedChips ? `<div class="mod-ie-chip-list">${encodedChips}</div>` : ''}
          </div>`,
    };
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
      const encodingControls = renderVibeEncodingControls(frame, index);
      const needsEncoding = !frame.is_no_image && !frame.is_naid3 && !frame.has_encoding ? ' needs-encoding' : '';
      const refStrength = formatRefStrength(frame.reference_strength) || '0.00';

      return `
    <div class="mod-ref-frame ${frame.is_enabled ? '' : 'disabled'}${needsEncoding}" data-pending-rs="${refStrength}" ${encodingControls.frameFlags}>
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
          <div class="mod-slider-row mod-vibe-rs-row">
            <span class="mod-slider-label">Ref Strength</span>
            <input class="mod-vibe-rs-slider" type="range" min="-100" max="100" step="1" value="${Math.round(Number(refStrength)*100)}"
              oninput="onVibeRefStrengthDraft(${index},this.value/100,'slider')"
              onchange="commitVibeRefStrength(${index},this.value/100)">
            <input class="mod-vibe-rs-input" type="number" min="-1" max="1" step="0.01" inputmode="decimal" value="${refStrength}"
              oninput="onVibeRefStrengthDraft(${index},this.value,'input')"
              onchange="commitVibeRefStrength(${index},this.value)"
              onkeydown="if(event.key==='Enter'){event.preventDefault();this.blur()}">
          </div>
          ${encodingControls.html}
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
      <button class="mod-btn-upload mod-btn-storage" onclick="openVibeClusterListPanel()">Cluster</button>
      <span class="mod-frame-count">${message.frame_count}/${message.max_frames}</span>
    </div>
    <label class="mod-checkbox-item" style="margin-bottom:8px">
      <input type="checkbox" ${message.normalize ? 'checked' : ''}
        oninput="setModuleParam('vibe_transfer','normalize',String(this.checked))">
      <span class="mod-checkbox-label">Normalize reference strength</span>
    </label>
    ${frames.length ? frames : '<div class="mod-empty">No vibe transfers loaded</div>'}
    <div class="vibe-cluster-footer">
      <button class="mod-btn-upload mod-btn-vibe-cluster" onclick="openVibeClusterPanel()">Make Vibe Cluster</button>
    </div>
  `;
    if (vibeClusterListOpen || vibeClusterSaveOpen) relayoutVibeClusterPanel();
  }

  function openVibeClusterPanel() {
    openVibeClusterSavePanel();
  }

  function closeVibeClusterPanel() {
    closeVibeClusterListPanel();
  }

  function onVibeClusterList(message) {
    vibeClusterItems = Array.isArray(message.items) ? message.items : [];
    if (vibeClusterShowListAfterSave && message.source === 'cluster_save') {
      closeVibeClusterSavePanel();
      openVibeClusterListPanel(message);
    } else if (vibeClusterListOpen) {
      renderVibeClusterPanel(message);
    }
  }

  function clusterThumb(item) {
    if (item.thumbnail) {
      return `<img src="data:image/jpeg;base64,${item.thumbnail}" alt="">`;
    }
    return '<span>No Thumb</span>';
  }

  function renderVibeClusterPanel(message = {}) {
    const existing = getVibeClusterPanel();
    if (existing) existing.remove();

    const items = vibeClusterItems.map(item => {
      const id = escHtml(item.id);
      const name = escHtml(item.name || item.id);
      const description = escHtml(item.description || '');
      const model = escHtml(item.model || '');
      const frameCount = Number(item.frame_count || 0);
      const enabledCount = Number(item.enabled_count || 0);
      return `
        <article class="vibe-cluster-card" data-cluster-id="${id}">
          <div class="vibe-cluster-thumb">${clusterThumb(item)}</div>
          <div class="vibe-cluster-info">
            <div class="vibe-cluster-name">${name}</div>
            ${description ? `<div class="vibe-cluster-desc">${description}</div>` : ''}
            <div class="vibe-cluster-meta">${model} · ${enabledCount}/${frameCount}</div>
          </div>
          <div class="vibe-cluster-actions">
            <div class="vibe-cluster-menu-wrap">
              <button class="mod-btn-sm" onclick="toggleVibeClusterLoadMenu('${id}',event)">Load</button>
              <div class="vibe-cluster-menu" data-load-menu="${id}">
                <button onclick="loadVibeCluster('${id}','clean')">Clean</button>
                <button onclick="loadVibeCluster('${id}','append')">Append</button>
              </div>
            </div>
            <div class="vibe-cluster-menu-wrap">
              <button class="mod-btn-sm" onclick="toggleVibeClusterManageMenu('${id}',event)">Manage</button>
              <div class="vibe-cluster-menu" data-manage-menu="${id}">
                <button onclick="renameVibeCluster('${id}')">Rename</button>
                <button onclick="chooseVibeClusterThumbnail('${id}')">Change Thumb</button>
                <button class="danger" onclick="deleteVibeCluster('${id}')">Delete</button>
              </div>
            </div>
          </div>
        </article>`;
    }).join('');

    const currentCount = message.current_frame_count ?? '';
    const panel = document.createElement('div');
    panel.className = 'vibe-cluster-popover open';
    panel.innerHTML = `
      <div class="vibe-cluster-header">
        <h3>Vibe Cluster</h3>
        <button class="mod-btn-sm" onclick="closeVibeClusterPanel()">Close</button>
      </div>
      <div class="vibe-cluster-list-head">
        <span>Saved</span>
        ${currentCount !== '' ? `<span>${currentCount}/8 loaded</span>` : ''}
      </div>
      <div class="vibe-cluster-list">${items || '<div class="mod-empty">No saved clusters</div>'}</div>
      ${renderVibeClusterListHiddenInput()}
    `;
    getVibeClusterHost().appendChild(panel);
    relayoutVibeClusterPanel();
  }

  function saveVibeCluster() {
    const panel = getVibeClusterSavePanel();
    const nameInput = panel?.querySelector('#vibeClusterName');
    const name = filterVibeClusterNameInput(nameInput).trim();
    const description = panel?.querySelector('#vibeClusterDesc')?.value.trim() || '';
    if (!isValidVibeClusterName(name)) {
      nameInput?.classList.add('invalid');
      showToast?.(VIBE_CLUSTER_NAME_HINT, 'error');
      return;
    }
    vibeClusterShowListAfterSave = true;
    setModuleParam('vibe_transfer', 'cluster_save', JSON.stringify({
      name,
      description,
      thumbnail_data: vibeClusterPendingThumb,
    }));
  }

  function closeVibeClusterMenus() {
    getVibeClusterPanel()?.querySelectorAll('.vibe-cluster-menu.open').forEach(menu => menu.classList.remove('open'));
  }

  function toggleVibeClusterLoadMenu(id, event) {
    event?.stopPropagation?.();
    const menu = queryVibeClusterPanel(`[data-load-menu="${id}"]`);
    const shouldOpen = menu && !menu.classList.contains('open');
    closeVibeClusterMenus();
    if (shouldOpen) menu.classList.add('open');
  }

  function toggleVibeClusterManageMenu(id, event) {
    event?.stopPropagation?.();
    const menu = queryVibeClusterPanel(`[data-manage-menu="${id}"]`);
    const shouldOpen = menu && !menu.classList.contains('open');
    closeVibeClusterMenus();
    if (shouldOpen) menu.classList.add('open');
  }

  function loadVibeCluster(id, mode) {
    closeVibeClusterMenus();
    setModuleParam('vibe_transfer', 'cluster_load', JSON.stringify({id, mode}));
  }

  function renameVibeCluster(id) {
    closeVibeClusterMenus();
    const item = vibeClusterItems.find(entry => entry.id === id) || {};
    const name = globalThis.prompt?.('Name', item.name || '') ?? '';
    if (!name.trim()) return;
    if (!isValidVibeClusterName(name.trim())) {
      showToast?.(VIBE_CLUSTER_NAME_HINT, 'error');
      return;
    }
    const description = globalThis.prompt?.('Description', item.description || '') ?? '';
    setModuleParam('vibe_transfer', 'cluster_rename', JSON.stringify({id, name: name.trim(), description}));
  }

  function deleteVibeCluster(id) {
    closeVibeClusterMenus();
    if (globalThis.confirm && !globalThis.confirm('Delete this Vibe cluster?')) return;
    setModuleParam('vibe_transfer', 'cluster_delete', id);
  }

  function chooseVibeClusterThumbnail(id) {
    closeVibeClusterMenus();
    vibeClusterThumbTarget = id;
    document.getElementById('vibeClusterManageThumbInput')?.click();
  }

  function updateVibeClusterThumbnailFromFile(id, file) {
    if (!id) return;
    readVibeClusterThumbnail(file, dataUrl => {
      setModuleParam('vibe_transfer', 'cluster_thumbnail', JSON.stringify({
        id,
        thumbnail_data: dataUrl,
      }));
    });
  }

  function vibeClusterThumbTargetValue() {
    return vibeClusterThumbTarget;
  }

  function requestStorage(moduleId) {
    storageView = moduleId;
    setModuleParam(moduleId, 'get_storage', '');
  }

  function onStorageList(message) {
    if (message.module_id === 'character_reference') renderCharRefStorage(message);
    else if (message.module_id === 'vibe_transfer') renderVibeStorage(message);
    else if (message.module_id === 'vibe_cluster') onVibeClusterList(message);
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
      <button class="mod-btn-sm" onclick="openModule('character_reference',{forceOpen:true})">Back</button>
    </div>
    ${items.length
      ? '<div class="mod-storage-grid">' + items + '</div>'
      : '<div class="mod-empty">No saved references</div>'}
  `;
  }

  function applyCharRefStorage(fileHash) {
    setModuleParam('character_reference', 'apply_storage', fileHash);
    setTimeoutFn(() => openModule('character_reference', {forceOpen: true}), 500);
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
      <button class="mod-btn-sm" onclick="openModule('vibe_transfer',{forceOpen:true})">Back</button>
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
    updateVibeIeDraft,
    commitVibeIeDraft,
    selectVibeEncoding,
    encodeVibeFrame,
    updateVibeRefStrengthDraft,
    commitVibeRefStrength,
    renderCharacterReference,
    renderVibeTransfer,
    openVibeClusterPanel,
    openVibeClusterListPanel,
    closeVibeClusterPanel,
    closeVibeClusterSavePanel,
    closeAllVibeClusterPanels,
    saveVibeCluster,
    pasteVibeClusterThumbnail,
    setVibeClusterSaveThumbnail,
    toggleVibeClusterLoadMenu,
    toggleVibeClusterManageMenu,
    loadVibeCluster,
    renameVibeCluster,
    deleteVibeCluster,
    chooseVibeClusterThumbnail,
    updateVibeClusterThumbnailFromFile,
    vibeClusterThumbTargetValue,
    relayoutVibeClusterPanel,
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
