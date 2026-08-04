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
  confirmDialog = async () => false,
  promptDialog = async () => null,
  // Interactive 패널 접근자. 캐릭터 에셋의 프롬프트를 슬롯으로 나눠 넣을 때만 쓴다.
  getInteractivePanel = () => null,
}) {
  const sliderDebounce = {};
  // 미커밋 IE draft 보존: 사용자가 IE 슬라이더를 드래그했지만 아직 인코딩(2 Anlas)하지 않은 값을
  // 보관한다. Ref Strength 조정/패널 재오픈으로 module_state가 재렌더돼도 IE가 백엔드 저장값(보통
  // 1.00)으로 스냅백되지 않게 한다. 생성은 항상 vibe_encodings를 쓰므로 이 draft는 순수 표시용이고
  // IE↔인코딩 불일치를 만들지 않는다.
  //   key   = frame index (제거 외에는 재렌더 간 안정 — 백엔드가 vibe 프레임을 재정렬하지 않음)
  //   value = { ie, hash, baseIe }
  //     hash   = frame.file_hash. index가 다른 프레임을 가리키게 되면(프레임 제거로 시프트) 무효화.
  //              동일 이미지 2회 추가(같은 hash·다른 index)도 index 키라 교차 오염되지 않는다.
  //     baseIe = draft 생성 시점의 백엔드 IE. 이후 백엔드 IE가 달라지면(인코딩 완료/외부 세션 변경)
  //              draft를 해소해 정당한 백엔드 값이 가려지지 않게 한다.
  const vibeIeDrafts = new Map();
  let storageView = null;
  let vibeClusterListOpen = false;
  let vibeClusterSaveOpen = false;
  let vibeClusterShowListAfterSave = false;
  let vibeClusterItems = [];
  let vibeClusterCanWrite = true;
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
    if (vibeClusterCanWrite === false) {
      showToast?.('Vibe cluster editing is not available in the headless runtime.', 'info');
      return;
    }
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

  // 재렌더 시 frame(index)에 적용할 IE draft를 해소한다. 다음이면 draft를 버리고 백엔드 값을 쓴다:
  //  - index가 다른 프레임을 가리킴(제거로 시프트) → hash 불일치
  //  - 백엔드 IE가 draft 생성 시점(baseIe)과 달라짐 → 인코딩 완료 또는 외부 변경 → 해소
  // 그 외(백엔드 IE 불변)에는 미커밋 draft를 유지해 스냅백을 막는다.
  function resolveVibeIeDraft(frame, index, backendIe) {
    const entry = vibeIeDrafts.get(index);
    if (!entry) return '';
    if (entry.hash !== String(frame?.file_hash || '') || backendIe !== entry.baseIe) {
      vibeIeDrafts.delete(index);
      return '';
    }
    return entry.ie;
  }

  function updateVibeIeDraft(index, rawValue) {
    const frameElement = getVibeFrameElement(index);
    if (!frameElement) return null;
    const ieText = formatIe(Number(rawValue) / 100);
    const encodedKeys = getFrameEncodedKeys(frameElement);
    const encoded = hasEncodedIe(encodedKeys, ieText);
    // 인코딩된 값은 commitVibeIeDraft가 백엔드로 커밋 → 백엔드 IE가 곧 보유하므로 draft 불필요.
    // 미인코딩 값만 재렌더 대비 보존(생성 시점 백엔드 IE=baseIe로 외부 변경 감지).
    if (encoded) {
      vibeIeDrafts.delete(index);
    } else {
      vibeIeDrafts.set(index, {
        ie: ieText,
        hash: frameElement.dataset.fileHash || '',
        baseIe: frameElement.dataset.backendIe || '',
      });
    }
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
      status.textContent = encoded
        ? `Encoded IE ${ieText}`
        : (canEncode ? `Encode required for IE ${ieText}` : 'Use stored encoded Vibe entries');
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
    vibeIeDrafts.delete(index);  // 인코딩된 칩을 명시 선택 → 백엔드로 커밋되므로 draft 폐기
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
    const backendIe = formatIe(frame.information_extracted);
    // locked 분기(이미지 없음 / no_source 번들)는 IE가 인코딩에 고정 → draft를 적용하지 않고
    // 항상 backendIe를 쓴다(슬라이더가 없어 draft가 생성될 일도 없지만 방어적으로 차단).
    // 편집 가능한 정상 vibe만 미커밋 draft를 우선 표시해 스냅백을 막는다.
    const isLocked = frame.is_no_image || (frame.no_source && encodedKeys.length > 0);
    const currentIe = (!isLocked && resolveVibeIeDraft(frame, index, backendIe)) || backendIe;
    const hasCurrentEncoding = hasEncodedIe(encodedKeys, currentIe);
    const canEncode = frame.can_encode !== false && !frame.is_no_image && !frame.is_naid3 && !frame.encoding_in_progress;
    const keyData = encodedKeys.map(formatIe).join(',');
    const frameFlags = [
      `data-vibe-index="${index}"`,
      `data-file-hash="${escHtml(String(frame.file_hash || ''))}"`,
      `data-backend-ie="${backendIe}"`,
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

    // 원본 이미지 없는(번들 placeholder) vibe만 IE 잠금: 재인코딩이 불가능해 슬라이더로 IE를
    // 바꾸면 인코딩↔IE 불일치로 깨진 이미지가 나온다. 값은 보여주되 슬라이더 disabled + 인코딩된
    // 칩 중에서만 선택. 정상 업로드/이미지 포함 vibe(no_source=false)는 아래의 조정 가능한
    // 슬라이더 + 인코딩(Anlas) 흐름을 그대로 유지한다.
    if (frame.no_source && encodedKeys.length > 0) {
      return {
        frameFlags,
        html: `
          <div class="mod-slider-row mod-vibe-ie-row">
            <span class="mod-slider-label">Info Extracted</span>
            <input class="mod-vibe-ie-slider" type="range" min="1" max="100" step="1" value="${Math.round(Number(currentIe) * 100)}" disabled title="원본 이미지가 없는 vibe는 재인코딩이 불가해 IE가 고정됩니다 (인코딩된 값만 사용)">
            <span class="mod-slider-value mod-vibe-ie-value">${currentIe}</span>
          </div>
          <div class="mod-vibe-encode-row">
            <span class="mod-encode-status encoded">Encoded IE ${currentIe}</span>
            ${encodedKeys.length > 1 && encodedChips ? `<div class="mod-ie-chip-list">${encodedChips}</div>` : ''}
          </div>`,
      };
    }

    const statusText = frame.can_encode === false && !hasCurrentEncoding
      ? 'Use stored encoded Vibe entries'
      : frame.encoding_in_progress
      ? `Encoding IE ${currentIe}...`
      : hasCurrentEncoding
        ? `Encoded IE ${currentIe}`
        : `Encode required for IE ${currentIe}`;
    const statusClass = hasCurrentEncoding ? 'encoded' : 'pending';
    const encodeHidden = hasCurrentEncoding || !canEncode ? ' hidden' : '';
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
      <button class="mod-btn-upload mod-btn-danger" onclick="setModuleParam('character_reference','clear_frames','')"
        title="로드된 레퍼런스 프레임을 모두 비웁니다 (Storage 보관본은 유지)">Clear</button>
    </div>
    ${frames.length ? frames : '<div class="mod-empty">No character references loaded</div>'}
  `;
  }

  function renderVibeTransfer(message) {
    vibeClusterCanWrite = message.can_write_clusters !== false;
    // stale IE draft 정리: 해당 index에 프레임이 없거나(제거) 다른 프레임이 와 있으면(제거로 시프트)
    // 폐기. 메모리는 동시 프레임 수(≤MAX)로 bounded.
    // 알려진 LOW 잔여 엣지: 동일 이미지를 2개 프레임으로 올린 뒤 앞쪽을 제거하면, 뒤 프레임이 같은
    // index로 시프트되며 hash·baseIe가 모두 같을 경우 제거된 프레임의 draft가 살아남아 엉뚱한
    // 프레임에 표시될 수 있다. 표시 전용·자가치유(슬라이더 조작/인코딩/백엔드 IE 변경 시 해소)이며
    // 생성(vibe_encodings)에는 영향 없음. 프레임 instance 식별이 불가능한 프론트 한계 — 완전 차단은
    // 백엔드 안정 frame id 필요(사용자 결정으로 미적용).
    const liveFrames = message.frames || [];
    for (const [index, entry] of [...vibeIeDrafts.entries()]) {
      const frame = liveFrames[index];
      if (!frame || String(frame.file_hash || '') !== entry.hash) vibeIeDrafts.delete(index);
    }
    const frames = liveFrames.map((frame, index) => {
      const thumbHtml = frame.is_no_image
        ? '<div class="mod-ref-noimage">No Image</div>'
        : `<img class="mod-ref-thumb" src="data:image/jpeg;base64,${frame.thumbnail}" alt="${escHtml(frame.file_name)}">`;
      const encodingControls = renderVibeEncodingControls(frame, index);
      const canEncodeFrame = frame.can_encode !== false && !frame.is_no_image && !frame.is_naid3;
      const needsEncoding = canEncodeFrame && !frame.has_encoding ? ' needs-encoding' : '';
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
    const enabledCount = Number(message.enabled_count || 0);
    const includedFrames = Number(message.included_frames || 4);
    const extraCostCount = Number(message.extra_cost_count || 0);
    const strengthTotal = Number(message.strength_total || 0);
    const vibeNotice = extraCostCount > 0
      ? `<div class="mod-notice">5+ active Vibe references may cost extra Anlas (${extraCostCount} extra). Keep total strength &lt;= 1.0 or enable Normalize.</div>`
      : '';
    const strengthNotice = message.strength_warning
      ? `<div class="mod-notice">Active Vibe strength total is ${strengthTotal.toFixed(2)}. Enable Normalize or lower strengths for predictable Multivibe results.</div>`
      : '';

    moduleBody.innerHTML = `
    <div class="mod-upload-bar">
      <button class="mod-btn-upload" onclick="document.getElementById('vibeFileInput').click()">Upload</button>
      <button class="mod-btn-upload" onclick="pasteModuleImage('vibe_transfer')">Paste</button>
      <input type="file" id="vibeFileInput" accept="image/*" style="display:none"
        onchange="uploadModuleImage('vibe_transfer',this.files[0]);this.value=''">
      <button class="mod-btn-upload mod-btn-storage" onclick="requestStorage('vibe_transfer')">Storage</button>
      <button class="mod-btn-upload mod-btn-storage" onclick="openVibeClusterListPanel()">Cluster</button>
      <span class="mod-frame-count">${message.frame_count}/${message.max_frames}</span>
      ${enabledCount > includedFrames ? `<span class="mod-frame-count">${enabledCount} active</span>` : ''}
    </div>
    <div class="mod-upload-bar">
      <button class="mod-btn-upload" style="flex:1;background:color-mix(in srgb, var(--accent) 64%, #14122a 36%)" title="단일 NAI vibe 파일(.naiv4vibe) 가져오기 · 사전 인코딩 · Anlas 0" onclick="document.getElementById('vibeSingleInput').click()">Import .naiv4vibe</button>
      <input type="file" id="vibeSingleInput" accept=".naiv4vibe,application/json" style="display:none"
        onchange="importVibeFile(this.files[0]);this.value=''">
      <button class="mod-btn-upload" style="flex:1;background:color-mix(in srgb, var(--accent) 64%, #14122a 36%)" title="NAI vibe 번들(.naiv4vibebundle) 가져오기 · 사전 인코딩 · Anlas 0" onclick="document.getElementById('vibeBundleInput').click()">Import .naiv4vibebundle</button>
      <input type="file" id="vibeBundleInput" accept=".naiv4vibebundle,application/json" style="display:none"
        onchange="importVibeFile(this.files[0]);this.value=''">
    </div>
    <label class="mod-checkbox-item" style="margin-bottom:8px">
      <input type="checkbox" ${message.normalize ? 'checked' : ''}
        oninput="setModuleParam('vibe_transfer','normalize',String(this.checked))">
      <span class="mod-checkbox-label">Normalize reference strength</span>
    </label>
    ${vibeNotice}
    ${strengthNotice}
    ${frames.length ? frames : '<div class="mod-empty">No vibe transfers loaded</div>'}
    ${vibeClusterCanWrite ? `<div class="vibe-cluster-footer">
      <button class="mod-btn-upload mod-btn-vibe-cluster" onclick="openVibeClusterPanel()">Make Vibe Cluster</button>
    </div>` : ''}
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
    if (Object.prototype.hasOwnProperty.call(message, 'can_write_clusters')) {
      vibeClusterCanWrite = message.can_write_clusters !== false;
    }
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
    const canWriteClusters = message.can_write_clusters !== false && vibeClusterCanWrite !== false;

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
            ${canWriteClusters ? `<div class="vibe-cluster-menu-wrap">
              <button class="mod-btn-sm" onclick="toggleVibeClusterManageMenu('${id}',event)">Manage</button>
              <div class="vibe-cluster-menu" data-manage-menu="${id}">
                <button onclick="renameVibeCluster('${id}')">Rename</button>
                <button onclick="chooseVibeClusterThumbnail('${id}')">Change Thumb</button>
                <button class="danger" onclick="deleteVibeCluster('${id}')">Delete</button>
              </div>
            </div>` : ''}
          </div>
        </article>`;
    }).join('');

    const currentCount = message.current_frame_count ?? '';
    const maxFrames = message.max_frames ?? 16;
    const panel = document.createElement('div');
    panel.className = 'vibe-cluster-popover open';
    panel.innerHTML = `
      <div class="vibe-cluster-header">
        <h3>Vibe Cluster</h3>
        <button class="mod-btn-sm" onclick="closeVibeClusterPanel()">Close</button>
      </div>
      <div class="vibe-cluster-list-head">
        <span>Saved</span>
        ${currentCount !== '' ? `<span>${currentCount}/${maxFrames} loaded</span>` : ''}
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

  async function renameVibeCluster(id) {
    closeVibeClusterMenus();
    const item = vibeClusterItems.find(entry => entry.id === id) || {};
    const name = await Promise.resolve(promptDialog('Name', {
      title: 'Rename Vibe cluster',
      okText: '저장',
      cancelText: '취소',
      defaultValue: item.name || '',
    }));
    if (!name || !name.trim()) return;
    if (!isValidVibeClusterName(name.trim())) {
      showToast?.(VIBE_CLUSTER_NAME_HINT, 'error');
      return;
    }
    const description = await Promise.resolve(promptDialog('Description', {
      title: 'Rename Vibe cluster',
      okText: '저장',
      cancelText: '취소',
      defaultValue: item.description || '',
    }));
    if (description === null || description === undefined) return;
    setModuleParam('vibe_transfer', 'cluster_rename', JSON.stringify({id, name: name.trim(), description}));
  }

  async function deleteVibeCluster(id) {
    closeVibeClusterMenus();
    const confirmed = await Promise.resolve(confirmDialog('Delete this Vibe cluster?', {
      title: 'Delete Vibe cluster',
      okText: '삭제',
      cancelText: '취소',
    }));
    if (!confirmed) return;
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

  // 레퍼런스를 고르는 소스는 둘이다. 예전엔 보관함 하나뿐이라, 사용자가 Assets 탭에
  // 쌓아 둔 **캐릭터 에셋**을 레퍼런스로 쓰려면 한 번 슬롯에 적용(= 프롬프트까지 덮어씀)
  // 하는 길밖에 없었다. Interactive 에서는 그 길이 아예 막혀 있다(캐릭터 블록이 프롬프트를
  // 소유한다). 탭으로 갈라 에셋에서 바로 집게 한다.
  let charRefStorageMessage = null;     // 마지막 보관함 응답(탭을 오갈 때 다시 안 묻는다)


  function charRefStorageShell(inner, refresh) {
    return `
    <div class="mod-upload-bar">
      <button class="mod-btn-upload" onclick="${refresh}">Refresh</button>
      <button class="mod-btn-sm" onclick="openModule('character_reference',{forceOpen:true})">Back</button>
    </div>
    ${inner}`;
  }

  function renderCharRefStorage(message) {
    if (getCurrentModuleId() !== 'character_reference') return;
    if (message) charRefStorageMessage = message;
    const items = ((charRefStorageMessage || {}).items || []).map(item => `
    <div class="mod-storage-item" onclick="applyCharRefStorage('${escHtml(item.file_hash)}')" title="${escHtml(item.file_name)}">
      ${storageThumbMarkup(item)}
      <span class="mod-storage-name">${escHtml(item.character_name || item.file_name)}</span>
    </div>
  `).join('');
    moduleBody.innerHTML = charRefStorageShell(
      items.length
        ? '<div class="mod-storage-grid">' + items + '</div>'
        : '<div class="mod-empty">No saved references</div>',
      "setModuleParam('character_reference','get_storage','')");
  }



  // ---- 에셋을 가져올 때 프롬프트도 함께 가져올지 묻는다 --------------------
  // 에셋은 NAI 캐릭터 프롬프트를 통째로 들고 있다. 이미지만 필요할 때도 있고
  // 외형까지 통째로 가져오고 싶을 때도 있어서 **누를 때 고르게** 한다.
  // 버튼 방식은 Assets 바의 캐릭터 검색 팝업과 같은 규약이다.




  // Storage 항목 클릭 적용은 ~500ms 지연돼 반영되므로, 같은 항목을 빠르게 다시
  // 누르면(더블클릭) 중복 프레임이 올라온다. 같은 키의 재적용을 짧게 디바운스한다.
  let _lastStorageApply = {key: '', t: 0};
  function _storageApplyGuard(key) {
    const now = Date.now();
    if (key === _lastStorageApply.key && now - _lastStorageApply.t < 800) return false;
    _lastStorageApply = {key, t: now};
    return true;
  }

  function applyCharRefStorage(fileHash) {
    if (!_storageApplyGuard('cr:' + fileHash)) return;
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
        const isNew = !!item.session_new;  // 이번 세션 import분 → 흰 테두리+이름 강조
        return `
        <div class="mod-storage-item" ${isNew ? 'style="outline:2px solid #ffffff;outline-offset:-1px"' : ''} onclick="applyVibeStorage('${escHtml(name)}','${escHtml(item.file_hash)}',${defaultIe})" oncontextmenu="showVibeStorageMenu(event,'${escHtml(name)}','${escHtml(item.file_hash)}');return false" title="${escHtml(item.file_name)}">
          ${storageThumbMarkup(item)}
          <span class="mod-storage-name" ${isNew ? 'style="color:#ffffff;font-weight:700"' : ''}>${escHtml(item.file_name)}</span>
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
    if (!_storageApplyGuard('vt:' + model + '|' + fileHash + '|' + ieValue)) return;
    setModuleParam('vibe_transfer', 'apply_storage', model + '|' + fileHash + '|' + ieValue);
  }

  function storageThumbMarkup(item = {}) {
    if (item.thumbnail_url) {
      return `<img class="mod-storage-thumb" src="${escHtml(item.thumbnail_url)}" alt="" loading="lazy" decoding="async">`;
    }
    if (item.thumbnail) {
      return `<img class="mod-storage-thumb" src="data:image/jpeg;base64,${item.thumbnail}" alt="" loading="lazy" decoding="async">`;
    }
    return '<div class="mod-storage-thumb mod-storage-thumb-empty">No Thumb</div>';
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
