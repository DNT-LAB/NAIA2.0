/* ============================================================
   NAIA Remote — client-side logic
   ============================================================ */

let ws, blobUrl = null, generating = false, drawerOpen = false;
const escHtml = s => s ? s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;') : '';
let reconnTimer = null, genTimer = null, genStartTime = 0;
let syncingOptions = false, syncingPrompt = false, promptSendTimer = null;

// ---- History ----
const HISTORY_MAX = 200;
const imageHistory = [];  // [{blobUrl, meta}]
let historyIdx = -1; // currently viewed index (-1 = latest live)
let pendingMeta = null; // meta arrives before blob

const $ = id => document.getElementById(id);
const preview      = $('preview');
const emptyMsg     = $('emptyMsg');
const connDot      = $('connDot');
const connText     = $('connText');
const btnGen       = $('btnGen');
const btnRnd       = $('btnRnd');
const promptEdit   = $('promptEdit');
const negEdit      = $('negEdit');
const metaRow      = $('metaRow');
const paramFlags   = $('paramFlags');
const paramEls = {
  model: $('pModel'), sampler: $('pSampler'), scheduler: $('pScheduler'),
  resolution: $('pResolution'), steps: $('pSteps'), cfg_scale: $('pCfgScale'),
  cfg_rescale: $('pCfgRescale'), seed: $('pSeed'),
};
const qResolution = $('qResolution');
const qRndRes = $('qRndRes');
const qAutoRes = $('qAutoRes');
let syncingParams = false;
const historyTab     = $('historyTab');
const histCounter    = $('histCounter');
const historyPanel   = $('historyPanel');
const historyOverlay = $('historyOverlay');
const historyGrid    = $('historyGrid');
const promptDrawer = $('promptDrawer');
const toggleArrow  = $('toggleArrow');
const toggleArrow2 = $('toggleArrow2');
const toggleLabel  = $('toggleLabel');
const promptNewDot = $('promptNewDot');
const toggleBar    = document.querySelector('.prompt-toggle-bar');
const viewerHistActions = $('viewerHistActions');
const optBoxes = {
  prompt_fixed: $('optPromptFixed'),
  auto_generate: $('optAutoGen'),
  wildcard_standalone: $('optWcStandalone'),
};

// ---- WebSocket ----

function connect() {
  if (reconnTimer) { clearTimeout(reconnTimer); reconnTimer = null; }
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(`${proto}//${location.host}/ws`);
  ws.binaryType = 'blob';

  ws.onopen = () => {
    connDot.classList.add('on'); connText.textContent = 'connected';
    ws.send(JSON.stringify({type: 'get_search_state'}));
  };
  ws.onclose = () => {
    connDot.classList.remove('on'); connText.textContent = 'reconnecting';
    reconnTimer = setTimeout(connect, 3000);
  };
  ws.onerror = () => ws.close();

  ws.onmessage = e => {
    if (e.data instanceof Blob) {
      const url = URL.createObjectURL(e.data);
      addHistory(url, pendingMeta);
      pendingMeta = null;
      showLatest();
      setGen(false);
    } else {
      try {
        const m = JSON.parse(e.data);
        if (m.type === 'image_meta') { pendingMeta = m; updateMeta(m); }
        else if (m.type === 'status') setGen(m.is_generating);
        else if (m.type === 'prompt_generated') updatePromptOnly(m.prompt);
        else if (m.type === 'prompt_sync') syncPrompts(m);
        else if (m.type === 'options') syncOptions(m);
        else if (m.type === 'params') updateParams(m);
        else if (m.type === 'mode') syncMode(m.mode);
        else if (m.type === 'mode_result') onModeResult(m);
        else if (m.type === 'api_status') updateApiStatus(m);
        else if (m.type === 'api_config_result') onApiConfigResult(m);
        else if (m.type === 'api_test_result') onApiTestResult(m);
        else if (m.type === 'module_state') onModuleState(m);
        else if (m.type === 'search_state') onSearchState(m);
        else if (m.type === 'search_progress') onSearchProgress(m);
        else if (m.type === 'depth_state') onDepthState(m);
        // Update search count from prompt_generated
        if (m.type === 'prompt_generated' && 'remaining' in m) updateSearchCount(m.remaining);
      } catch(_) {}
    }
  };
}

// ---- Meta / Prompt display ----

function updateMetaChips(m) {
  const chips = [];
  if (m.model) chips.push(`<b>model</b> ${m.model}`);
  if (m.width && m.height) chips.push(`<b>res</b> ${m.width}x${m.height}`);
  if (m.seed) chips.push(`<b>seed</b> ${m.seed}`);
  if (m.steps) chips.push(`<b>steps</b> ${m.steps}`);
  if (m.cfg_scale) chips.push(`<b>cfg</b> ${m.cfg_scale}`);
  if (m.sampler) chips.push(`<b>sampler</b> ${m.sampler}`);
  if (m.size_kb) chips.push(`<b>file</b> ${m.size_kb}KB`);
  if (chips.length) metaRow.innerHTML = chips.map(c => `<span class="chip">${c}</span>`).join('');
}

function updateMeta(m) {
  // Don't overwrite prompt/negative — preserves user's comments (#) and line breaks
  updateMetaChips(m);
}

function updatePromptOnly(prompt) {
  if (prompt) {
    syncingPrompt = true;
    promptEdit.value = prompt;
    syncingPrompt = false;
    // Random 완료 -> 버튼 복원
    btnRnd.disabled = false;
    // Show new-content dot if drawer is closed
    if (!drawerOpen) promptNewDot.classList.remove('hidden');
  }
}

// ---- Params ----

function populateSelect(el, options, current) {
  if (options && options.length) {
    const existing = Array.from(el.options).map(o => o.value);
    if (existing.length !== options.length || existing.some((v, i) => v !== options[i])) {
      el.innerHTML = options.map(o => `<option value="${o}">${o}</option>`).join('');
    }
  }
  if (current !== undefined) el.value = current;
}

function updateParams(m) {
  syncingParams = true;
  populateSelect(paramEls.model, m.options_model, m.model);
  populateSelect(paramEls.sampler, m.options_sampler, m.sampler);
  populateSelect(paramEls.scheduler, m.options_scheduler, m.scheduler);
  populateSelect(paramEls.resolution, m.options_resolution, m.resolution);
  // Quick controls 동기화
  populateSelect(qResolution, m.options_resolution, m.resolution);
  if (m.steps !== undefined) paramEls.steps.value = m.steps;
  if (m.cfg_scale !== undefined) paramEls.cfg_scale.value = m.cfg_scale;
  if (m.cfg_rescale !== undefined) paramEls.cfg_rescale.value = m.cfg_rescale;
  if (m.seed !== undefined) paramEls.seed.value = m.seed;
  if (m.steps_range) {
    paramEls.steps.min = m.steps_range[0];
    paramEls.steps.max = m.steps_range[1];
  }
  // 모드별 표시/숨김
  const mode = m.api_mode || '';
  document.querySelectorAll('.mode-nai').forEach(el => el.style.display = mode === 'NAI' ? '' : 'none');
  $('webuiParams').style.display = mode === 'WEBUI' ? '' : 'none';
  $('comfyuiParams').style.display = mode === 'COMFYUI' ? '' : 'none';

  // 플래그 (공통 + NAI)
  const flags = [];
  const naiFlagsEnabled = m.nai_flags_enabled || {};
  if (mode === 'NAI') {
    for (const key of ['SMEA', 'DYN', 'VAR+', 'DECRISP']) {
      if (key in m) flags.push({key, name: key, on: m[key], enabled: naiFlagsEnabled[key] !== false});
    }
  }
  if ('seed_fixed' in m) flags.push({key: 'seed_fixed', name: 'Seed Fix', on: m.seed_fixed, enabled: true});
  if ('random_resolution' in m) flags.push({key: 'random_resolution', name: 'Rnd Res', on: m.random_resolution, enabled: true});
  if ('auto_fit_resolution' in m) flags.push({key: 'auto_fit_resolution', name: 'Auto Res', on: m.auto_fit_resolution, enabled: true});
  paramFlags.innerHTML = flags.map(f =>
    `<span class="param-flag${f.on ? ' on' : ''}${f.enabled ? '' : ' disabled'}" data-key="${f.key}" onclick="${f.enabled ? 'toggleFlag(this)' : ''}">${f.name}</span>`
  ).join('');
  // Quick flags 동기화
  if ('random_resolution' in m) qRndRes.classList.toggle('on', m.random_resolution);
  if ('auto_fit_resolution' in m) qAutoRes.classList.toggle('on', m.auto_fit_resolution);

  // WEBUI HR
  if (mode === 'WEBUI') {
    if ('enable_hr' in m) $('pEnableHr').checked = m.enable_hr;
    if ('hr_scale' in m) $('pHrScale').value = m.hr_scale;
    populateSelect($('pHrUpscaler'), m.options_hr_upscaler, m.hr_upscaler);
    if ('denoising_strength' in m) $('pDenoise').value = m.denoising_strength;
    if ('hires_steps' in m) $('pHiresSteps').value = m.hires_steps;
    if ('hr_cfg' in m) $('pHrCfg').value = m.hr_cfg;
  }

  // ComfyUI sampling mode
  if (mode === 'COMFYUI') {
    const sm = m.sampling_mode || 'eps';
    $('flagEps').classList.toggle('on', sm === 'eps');
    $('flagVpred').classList.toggle('on', sm === 'v_prediction');
    $('flagAnima').classList.toggle('on', sm === 'anima');
    $('comfyuiRescaleRow').style.display = sm === 'anima' ? '' : 'none';
    if ('rescale_cfg' in m) $('pRescaleCfg').value = m.rescale_cfg;
  }
  syncingParams = false;
}

function setParam(key, value) {
  if (syncingParams) return;
  // Quick ↔ Params 탭 양방향 동기화
  if (key === 'resolution') {
    paramEls.resolution.value = value;
    qResolution.value = value;
  }
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({type: 'set_param', key, value}));
  }
}

function toggleFlag(el) {
  if (el.classList.contains('disabled')) return;
  const key = el.dataset.key;
  const isOn = el.classList.contains('on');
  el.classList.toggle('on', !isOn);
  setParam(key, String(!isOn));
  // Quick flags 동기화 (Params → Quick)
  if (key === 'random_resolution') qRndRes.classList.toggle('on', !isOn);
  if (key === 'auto_fit_resolution') qAutoRes.classList.toggle('on', !isOn);
}

function toggleQuickFlag(el, key) {
  const isOn = el.classList.contains('on');
  el.classList.toggle('on', !isOn);
  setParam(key, String(!isOn));
  // Params 탭 내 플래그도 동기화
  const paramEl = paramFlags.querySelector(`[data-key="${key}"]`);
  if (paramEl) paramEl.classList.toggle('on', !isOn);
}

function setSamplingMode(mode) {
  $('flagEps').classList.toggle('on', mode === 'eps');
  $('flagVpred').classList.toggle('on', mode === 'v_prediction');
  $('flagAnima').classList.toggle('on', mode === 'anima');
  $('comfyuiRescaleRow').style.display = mode === 'anima' ? '' : 'none';
  setParam('sampling_mode', mode);
}

// ---- Prompt sync ----

function syncPrompts(m) {
  syncingPrompt = true;
  if ('prompt' in m) promptEdit.value = m.prompt;
  if ('negative_prompt' in m) negEdit.value = m.negative_prompt;
  syncingPrompt = false;
  updateMetaChips(m);
}

function onPromptEdit() {
  if (syncingPrompt) return;
  if (promptSendTimer) clearTimeout(promptSendTimer);
  promptSendTimer = setTimeout(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({
        type: 'set_prompt',
        prompt: promptEdit.value,
        negative_prompt: negEdit.value,
      }));
    }
  }, 500);
}

// ---- History ----
let historyOpen = false;

let historySaving = false;

function addHistory(url, meta) {
  if (historySaving) { URL.revokeObjectURL(url); return; }
  const entry = { blobUrl: url, meta: meta || {} };
  imageHistory.push(entry);

  if (imageHistory.length > HISTORY_MAX) {
    const action = ($('histLimitAction') || {}).value || 'never_mind';
    if (action === 'stop') {
      // 최신 이미지를 추가하지 않고 되돌림
      imageHistory.pop();
      URL.revokeObjectURL(url);
      return;
    } else if (action === 'save_all_clear') {
      // 최신 제외하고 전부 저장 후 클리어
      const latest = imageHistory.pop();
      historySaving = true;
      saveAllHistory().then(() => {
        for (const e of imageHistory) URL.revokeObjectURL(e.blobUrl);
        imageHistory.length = 0;
        historyGrid.innerHTML = '';
        imageHistory.push(latest);
        historyIdx = 0;
        const img = document.createElement('img');
        img.className = 'hist-thumb';
        img.src = latest.blobUrl;
        img.onclick = () => viewHistory(0);
        historyGrid.appendChild(img);
        updateHistCounter();
        historySaving = false;
      }).catch(() => { historySaving = false; });
      historyTab.classList.add('visible');
      updateHistCounter();
      return;
    }
    // never_mind: 기존 동작 — 가장 오래된 것 제거
    const old = imageHistory.shift();
    URL.revokeObjectURL(old.blobUrl);
    historyGrid.removeChild(historyGrid.firstElementChild);
    if (historyIdx > 0) historyIdx--;
    else if (historyIdx === 0) historyIdx = -1;
  }

  const img = document.createElement('img');
  img.className = 'hist-thumb';
  img.src = url;
  img.onclick = () => viewHistory(imageHistory.indexOf(entry));
  historyGrid.appendChild(img);

  historyTab.classList.add('visible');
  updateHistCounter();

  if (historyOpen) {
    requestAnimationFrame(() => {
      historyGrid.scrollTop = historyGrid.scrollHeight;
    });
  }
}

function viewHistory(idx) {
  if (idx < 0 || idx >= imageHistory.length) return;
  historyIdx = idx;
  const entry = imageHistory[idx];
  blobUrl = entry.blobUrl;
  preview.src = blobUrl;
  preview.classList.add('show');
  emptyMsg.style.display = 'none';
  if (entry.meta) updateMetaChips(entry.meta);
  viewerHistActions.classList.add('visible');
  updateActiveThumb();
}

function showLatest() {
  if (imageHistory.length === 0) return;
  historyIdx = imageHistory.length - 1;
  const entry = imageHistory[historyIdx];
  blobUrl = entry.blobUrl;
  preview.src = blobUrl;
  preview.classList.add('show');
  emptyMsg.style.display = 'none';
  viewerHistActions.classList.remove('visible');
  updateActiveThumb();
}

function updateActiveThumb() {
  historyGrid.querySelectorAll('.hist-thumb')
    .forEach((t, i) => t.classList.toggle('active', i === historyIdx));
  updateHistCounter();
}

function updateHistCounter() {
  histCounter.textContent = `${imageHistory.length > 0 ? historyIdx + 1 : 0} / ${imageHistory.length}`;
}

function toggleHistory() {
  historyOpen = !historyOpen;
  historyPanel.classList.toggle('open', historyOpen);
  historyTab.style.opacity = historyOpen ? '0' : '';
  historyTab.style.pointerEvents = historyOpen ? 'none' : '';
  if (historyOpen) {
    // 현재 이미지 포커스 → Save/Delete 표시 + 썸네일 스크롤
    if (historyIdx >= 0 && historyIdx < imageHistory.length) {
      viewHistory(historyIdx);
      requestAnimationFrame(() => {
        const thumbs = historyGrid.querySelectorAll('.hist-thumb');
        if (thumbs[historyIdx]) thumbs[historyIdx].scrollIntoView({block: 'center'});
      });
    } else {
      updateActiveThumb();
    }
  } else {
    viewerHistActions.classList.remove('visible');
  }
}

function navHistory(dir) {
  const next = historyIdx + dir;
  if (next >= 0 && next < imageHistory.length) viewHistory(next);
}

function saveCurrentHistoryItem() {
  if (historyIdx < 0 || historyIdx >= imageHistory.length) return;
  const entry = imageHistory[historyIdx];
  const a = document.createElement('a');
  a.href = entry.blobUrl;
  a.download = `naia_${String(historyIdx + 1).padStart(4, '0')}.webp`;
  a.click();
}

function deleteCurrentHistoryItem() {
  if (historyIdx < 0 || historyIdx >= imageHistory.length) return;
  const entry = imageHistory[historyIdx];
  URL.revokeObjectURL(entry.blobUrl);
  imageHistory.splice(historyIdx, 1);
  // 그리드 썸네일 제거
  const thumbs = historyGrid.querySelectorAll('.hist-thumb');
  if (thumbs[historyIdx]) thumbs[historyIdx].remove();
  // 다음 이미지 또는 이전 이미지 표시
  if (imageHistory.length === 0) {
    historyIdx = -1;
    preview.classList.remove('show');
    preview.src = '';
    emptyMsg.style.display = '';
    blobUrl = null;
    metaRow.innerHTML = '';
    viewerHistActions.classList.remove('visible');
    historyTab.classList.remove('visible');
  } else {
    if (historyIdx >= imageHistory.length) historyIdx = imageHistory.length - 1;
    viewHistory(historyIdx);
  }
  updateHistCounter();
}

async function saveAllHistory() {
  if (imageHistory.length === 0) return;
  const { default: JSZip } = await import('https://cdn.jsdelivr.net/npm/jszip@3/+esm');
  const zip = new JSZip();
  for (let i = 0; i < imageHistory.length; i++) {
    const resp = await fetch(imageHistory[i].blobUrl);
    const blob = await resp.blob();
    zip.file(`naia_${String(i + 1).padStart(4, '0')}.webp`, blob);
  }
  const content = await zip.generateAsync({type: 'blob'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(content);
  a.download = `naia_history_${Date.now()}.zip`;
  a.click();
  URL.revokeObjectURL(a.href);
}

function clearHistory() {
  if (!confirm(`Clear all ${imageHistory.length} images?`)) return;
  for (const entry of imageHistory) URL.revokeObjectURL(entry.blobUrl);
  imageHistory.length = 0;
  historyIdx = -1;
  historyGrid.innerHTML = '';
  preview.classList.remove('show');
  preview.src = '';
  emptyMsg.style.display = '';
  blobUrl = null;
  metaRow.innerHTML = '';
  updateHistCounter();
  toggleHistory(); // 창 닫기
  historyTab.classList.remove('visible');
}

// ---- Drawer & Tabs ----
const isPC = window.matchMedia('(min-width: 768px)');

function toggleDrawer() {
  if (isPC.matches) return;
  drawerOpen = !drawerOpen;
  promptDrawer.classList.toggle('open', drawerOpen);
  toggleBar.classList.toggle('open', drawerOpen);
  toggleArrow.classList.toggle('open', drawerOpen);
  toggleArrow2.classList.toggle('open', drawerOpen);
  toggleArrow.innerHTML = drawerOpen ? '&#9660;' : '&#9650;';
  toggleArrow2.innerHTML = drawerOpen ? '&#9660;' : '&#9650;';
  if (drawerOpen) {
    promptNewDot.classList.add('hidden');
    if (ws && ws.readyState === WebSocket.OPEN) ws.send('sync');
  }
}

isPC.addEventListener('change', () => {
  if (isPC.matches) {
    promptDrawer.classList.remove('open');
    drawerOpen = false;
  }
});

function switchTab(name) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  document.querySelectorAll('.tab-page').forEach(p => p.classList.remove('active'));
  $('tab' + name.charAt(0).toUpperCase() + name.slice(1)).classList.add('active');
}

// ---- Controls ----
function send(cmd) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  if (cmd === 'generate') {
    if (generating) return;
    if (promptSendTimer) { clearTimeout(promptSendTimer); promptSendTimer = null; }
    ws.send(JSON.stringify({
      type: 'generate',
      prompt: promptEdit.value,
      negative_prompt: negEdit.value,
    }));
    return;
  }
  if (cmd === 'random') {
    btnRnd.disabled = true;
  }
  ws.send(cmd);
}

function setGen(v) {
  generating = v;
  btnGen.disabled = v;
  if (v) {
    genStartTime = Date.now();
    btnGen.classList.add('generating');
    startGenTimer();
  } else {
    btnGen.classList.remove('generating');
    stopGenTimer();
    btnGen.innerHTML = '<span class="shortcut-hint">CTRL + ENTER</span>Generate';
  }
}

function startGenTimer() {
  stopGenTimer();
  genTimer = setInterval(() => {
    const elapsed = ((Date.now() - genStartTime) / 1000).toFixed(1);
    btnGen.innerHTML = `<span class="shortcut-hint">CTRL + ENTER</span>${elapsed}s`;
  }, 100);
}

function stopGenTimer() {
  if (genTimer) { clearInterval(genTimer); genTimer = null; }
}

// ---- Options sync ----
function syncOptions(m) {
  syncingOptions = true;
  for (const [key, cb] of Object.entries(optBoxes)) {
    if (key in m) cb.checked = m[key];
  }
  syncingOptions = false;
}

function setOption(key, value) {
  if (syncingOptions) return;
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({type: 'set_option', key, value}));
  }
}

// ---- Mode sync ----
const modeSelect = $('modeSelect');
const uiLock = $('uiLock');
const toastEl = $('toast');
let syncingMode = false;
let prevMode = modeSelect.value;
let toastTimer = null;

function syncMode(mode) {
  syncingMode = true;
  modeSelect.value = mode;
  prevMode = mode;
  syncingMode = false;
}

function setMode(mode) {
  if (syncingMode) return;
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  uiLock.classList.add('active');
  modeSelect.disabled = true;
  ws.send(JSON.stringify({type: 'set_mode', mode}));
}

function onModeResult(m) {
  uiLock.classList.remove('active');
  modeSelect.disabled = false;
  if (m.success) {
    prevMode = m.mode;
    syncMode(m.mode);
    showToast(m.message || `${m.mode} mode active`, 'success');
  } else {
    syncMode(prevMode);
    showToast(m.message || 'Mode change failed', 'error', true);
  }
}

function showToast(msg, type, showConfigure) {
  if (toastTimer) clearTimeout(toastTimer);
  if (showConfigure) {
    toastEl.innerHTML = `${msg} — <a href="#" onclick="openApiPopup();return false" style="color:inherit;text-decoration:underline">Configure</a>`;
  } else {
    toastEl.textContent = msg;
  }
  toastEl.className = `toast ${type}`;
  requestAnimationFrame(() => toastEl.classList.add('show'));
  toastTimer = setTimeout(() => {
    toastEl.classList.remove('show');
  }, showConfigure ? 4000 : 2500);
}

// ---- API Config popup ----
const apiPopupOverlay = $('apiPopupOverlay');
const apiWebuiUrl = $('apiWebuiUrl');
const apiComfyuiUrl = $('apiComfyuiUrl');
const apiDots = { NAI: $('apiDotNai'), WEBUI: $('apiDotWebui'), COMFYUI: $('apiDotComfyui') };

function openApiPopup() {
  apiPopupOverlay.classList.add('open');
  if (ws && ws.readyState === WebSocket.OPEN) ws.send('sync');
}

function closeApiPopup() {
  apiPopupOverlay.classList.remove('open');
  saveUrlIfChanged('WEBUI', apiWebuiUrl);
  saveUrlIfChanged('COMFYUI', apiComfyuiUrl);
}

function saveUrlIfChanged(mode, input) {
  const val = input.value.trim();
  const key = mode === 'WEBUI' ? '_lastWebuiUrl' : '_lastComfyuiUrl';
  if (val && val !== (saveUrlIfChanged[key] || '')) {
    saveUrlIfChanged[key] = val;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({type: 'set_api_url', mode, url: val}));
    }
  }
}

function testApi(mode) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  const input = mode === 'WEBUI' ? apiWebuiUrl : apiComfyuiUrl;
  const val = input.value.trim();
  if (val) {
    ws.send(JSON.stringify({type: 'set_api_url', mode, url: val}));
  }
  const btn = mode === 'WEBUI' ? $('apiWebuiTest') : $('apiComfyuiTest');
  btn.disabled = true;
  btn.textContent = '...';
  btn.classList.add('testing');
  ws.send(JSON.stringify({type: 'test_api', mode}));
}

function updateApiStatus(m) {
  const naiDot = apiDots.NAI;
  const naiStatus = $('apiNaiStatus');
  if (m.nai_configured) {
    naiDot.className = 'api-status-dot ok';
    naiStatus.textContent = 'Token configured';
  } else {
    naiDot.className = 'api-status-dot fail';
    naiStatus.textContent = 'Token not set — configure in NAIA API Management tab';
  }
  if (m.webui_url) {
    apiWebuiUrl.value = m.webui_url.replace(/^https?:\/\//, '');
    saveUrlIfChanged._lastWebuiUrl = apiWebuiUrl.value;
  }
  if (m.comfyui_url) {
    apiComfyuiUrl.value = m.comfyui_url.replace(/^https?:\/\//, '');
    saveUrlIfChanged._lastComfyuiUrl = apiComfyuiUrl.value;
  }
}

function onApiConfigResult(m) {
  const statusEl = m.mode === 'WEBUI' ? $('apiWebuiStatus') : $('apiComfyuiStatus');
  if (statusEl) {
    statusEl.textContent = m.message;
    statusEl.style.color = m.success ? 'var(--success)' : '#f04040';
  }
}

function onApiTestResult(m) {
  const btn = m.mode === 'WEBUI' ? $('apiWebuiTest') : $('apiComfyuiTest');
  const dot = apiDots[m.mode];
  const statusEl = m.mode === 'WEBUI' ? $('apiWebuiStatus') : $('apiComfyuiStatus');
  btn.disabled = false;
  btn.textContent = 'Test';
  btn.classList.remove('testing');
  if (dot) dot.className = `api-status-dot ${m.success ? 'ok' : 'fail'}`;
  if (statusEl) {
    statusEl.textContent = m.message;
    statusEl.style.color = m.success ? 'var(--success)' : '#f04040';
  }
}

// ---- Module floating panel ----
const modulePopup = $('modulePopup');
const moduleTitle = $('modulePopupTitle');
const moduleBody = $('modulePopupBody');
let currentModuleId = null;
let moduleSendTimer = null;

// Preprocessing option definitions (key → display label)
const PP_OPTIONS = [
  ['remove_author', 'Remove Artist'],
  ['remove_work_title', 'Remove Work Title'],
  ['remove_character_name', 'Remove Character Name'],
  ['remove_character_features', 'Remove Char Features'],
  ['remove_clothes', 'Remove Clothing'],
  ['remove_color', 'Remove Color Tags'],
  ['remove_location_and_background_color', 'Remove Location/BG'],
  ['remove_expression', 'Remove Expression'],
  ['remove_pose_action', 'Remove Pose/Action'],
  ['remove_meta_tags', 'Remove Meta Tags'],
  ['remove_object_tags', 'Remove Object Tags'],
  ['remove_noise_tags', 'Remove Low-freq Tags'],
  ['e621_auto_boost', 'e621 Auto-Boost'],
  ['danbooru_auto_weight', 'Danbooru Auto-Weight'],
  ['tag_implication_compression', 'Tag Implication'],
];

function openModule(moduleId) {
  // Toggle: same module clicked again → close
  if (currentModuleId === moduleId && modulePopup.classList.contains('open')) {
    closeModule();
    return;
  }
  currentModuleId = moduleId;
  modulePopup.classList.add('open');
  updateModuleBtnState();
  moduleBody.innerHTML = '<div style="text-align:center;color:var(--text-dim);padding:20px">Loading...</div>';
  const titles = {
    search: 'Prompt Search',
    prompt_engineering: 'Prompt Engineering',
    automation: 'Automation',
    character: 'NAID4 Character',
  };
  moduleTitle.textContent = titles[moduleId] || moduleId;
  if (ws && ws.readyState === WebSocket.OPEN) {
    if (moduleId === 'search') {
      ws.send(JSON.stringify({type: 'get_search_state'}));
    } else {
      ws.send(JSON.stringify({type: 'get_module_state', module_id: moduleId}));
    }
  }
}

function closeModule() {
  modulePopup.classList.remove('open');
  currentModuleId = null;
  updateModuleBtnState();
}

function updateModuleBtnState() {
  document.querySelectorAll('.module-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.module === currentModuleId);
  });
}

function onModuleState(m) {
  if (m.module_id !== currentModuleId) return;
  if (m.module_id === 'prompt_engineering') renderPromptEngineering(m);
  else if (m.module_id === 'automation') renderAutomation(m);
  else if (m.module_id === 'character') renderCharacter(m);
}

function renderPromptEngineering(m) {
  // Build preset options
  const presetOpts = (m.preset_options || [])
    .map(p => `<option value="${p}"${p === m.preset ? ' selected' : ''}>${p}</option>`).join('');

  // Build preprocessing checkboxes
  const pp = m.preprocessing || {};
  const ppHtml = PP_OPTIONS.map(([key, label]) =>
    `<label class="mod-checkbox-item">
      <input type="checkbox" ${pp[key] ? 'checked' : ''} onchange="setModuleParam('prompt_engineering','pp_${key}',String(this.checked))">
      <span class="mod-checkbox-label">${label}</span>
    </label>`
  ).join('');

  moduleBody.innerHTML = `
    <div>
      <div class="mod-section-label">Preset</div>
      <select class="mod-select" id="modPreset" onchange="setModuleParam('prompt_engineering','preset',this.value)">${presetOpts}</select>
    </div>
    <div>
      <div class="mod-section-label">Prefix Prompt</div>
      <textarea class="mod-textarea mod-textarea-lg" id="modPrePrompt" placeholder="prefix tags..." oninput="onModTextEdit('prompt_engineering','pre_prompt',this.value)">${escHtml(m.pre_prompt)}</textarea>
    </div>
    <div>
      <div class="mod-section-label">Postfix Prompt</div>
      <textarea class="mod-textarea mod-textarea-lg" id="modPostPrompt" placeholder="postfix tags..." oninput="onModTextEdit('prompt_engineering','post_prompt',this.value)">${escHtml(m.post_prompt)}</textarea>
    </div>
    <div>
      <div class="mod-section-label mod-collapsible" onclick="this.classList.toggle('open');this.nextElementSibling.classList.toggle('collapsed')">Auto-Hide (Filter) <span class="mod-collapse-arrow">▶</span></div>
      <textarea class="mod-textarea collapsed" id="modAutoHide" placeholder="tags to filter out..." oninput="onModTextEdit('prompt_engineering','auto_hide',this.value)">${escHtml(m.auto_hide)}</textarea>
    </div>
    <div>
      <div class="mod-section-label">Preprocessing Options</div>
      <div class="mod-checkbox-grid">${ppHtml}</div>
    </div>
  `;
}

function setModuleParam(moduleId, key, value) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({type: 'set_module_param', module_id: moduleId, key, value}));
  }
}

function onModTextEdit(moduleId, key, value) {
  if (moduleSendTimer) clearTimeout(moduleSendTimer);
  moduleSendTimer = setTimeout(() => setModuleParam(moduleId, key, value), 500);
}

// ---- Automation module ----
let lastAutoState = null;
function onAutoTypeChange(val) {
  setModuleParam('automation', 'auto_type', val);
  if (lastAutoState) {
    lastAutoState.auto_type = parseInt(val);
    renderAutomation(lastAutoState);
  }
}
function renderAutomation(m) {
  lastAutoState = m;
  const typeLabels = ['Unlimited', 'Timer', 'Count'];
  const typeRadios = typeLabels.map((label, i) =>
    `<label class="mod-checkbox-item">
      <input type="radio" name="autoType" value="${i}" ${m.auto_type === i ? 'checked' : ''} onchange="onAutoTypeChange(this.value)">
      <span class="mod-checkbox-label">${label}</span>
    </label>`
  ).join('');

  const isRunning = m.is_running;
  moduleBody.innerHTML = `
    <div>
      <div class="mod-section-label">Delay (seconds)</div>
      <div style="display:flex;gap:8px;align-items:center">
        <input class="mod-input" type="text" value="${m.delay || '0'}" onchange="setModuleParam('automation','delay',this.value)" style="flex:1">
        <label class="mod-checkbox-item" style="margin:0">
          <input type="checkbox" ${m.random_delay ? 'checked' : ''} onchange="setModuleParam('automation','random_delay',String(this.checked))">
          <span class="mod-checkbox-label">Random ±50%</span>
        </label>
      </div>
    </div>
    <div>
      <div class="mod-section-label">Repeat Count</div>
      <input class="mod-input" type="text" value="${m.repeat || '1'}" onchange="setModuleParam('automation','repeat',this.value)">
    </div>
    <div>
      <div class="mod-section-label">Termination</div>
      <div class="mod-checkbox-grid" style="grid-template-columns:1fr 1fr 1fr">${typeRadios}</div>
    </div>
    ${m.auto_type === 1 ? `<div>
      <div class="mod-section-label">Timer (minutes)</div>
      <input class="mod-input" type="text" value="${m.timer_minutes || '30'}" onchange="setModuleParam('automation','timer_minutes',this.value)">
    </div>` : ''}
    ${m.auto_type === 2 ? `<div>
      <div class="mod-section-label">Count Limit</div>
      <input class="mod-input" type="text" value="${m.count_limit || '100'}" onchange="setModuleParam('automation','count_limit',this.value)">
    </div>` : ''}
    <div>
      <label class="mod-checkbox-item">
        <input type="checkbox" ${m.notify ? 'checked' : ''} onchange="setModuleParam('automation','notify',String(this.checked))">
        <span class="mod-checkbox-label">Notify on completion</span>
      </label>
    </div>
    <div style="display:flex;gap:8px">
      <button class="mod-action-btn mod-start" ${isRunning ? 'disabled' : ''} onclick="setModuleParam('automation','start','1')">Start</button>
      <button class="mod-action-btn mod-stop" ${!isRunning ? 'disabled' : ''} onclick="setModuleParam('automation','stop','1')">Stop</button>
    </div>
    <div class="mod-status">${m.status || ''}</div>
  `;
}

// ---- Character module ----
function renderCharacter(m) {
  const chars = m.characters || [];
  const charsHtml = chars.map((c, i) => `
    <div class="mod-char-block">
      <div class="mod-char-header">
        <label class="mod-checkbox-item" style="margin:0">
          <input type="checkbox" ${c.active ? 'checked' : ''} onchange="setModuleParam('character','char_active_${i}',String(this.checked))">
          <span class="mod-checkbox-label">C${c.id}</span>
        </label>
      </div>
      <textarea class="mod-textarea" placeholder="character prompt..." oninput="onModTextEdit('character','char_prompt_${i}',this.value)">${escHtml(c.prompt)}</textarea>
      <textarea class="mod-textarea mod-uc" placeholder="negative prompt (UC)..." oninput="onModTextEdit('character','char_uc_${i}',this.value)">${escHtml(c.uc)}</textarea>
    </div>
  `).join('');

  moduleBody.innerHTML = `
    <div>
      <label class="mod-checkbox-item">
        <input type="checkbox" ${m.activated ? 'checked' : ''} onchange="setModuleParam('character','activated',String(this.checked))">
        <span class="mod-checkbox-label">Enable Character Prompts (NAID4+)</span>
      </label>
    </div>
    <div>
      <label class="mod-checkbox-item">
        <input type="checkbox" ${m.reroll_on_generate ? 'checked' : ''} onchange="setModuleParam('character','reroll_on_generate',String(this.checked))">
        <span class="mod-checkbox-label">Process wildcards on Generate</span>
      </label>
    </div>
    ${charsHtml}
  `;
}

// ---- Search system ----
const searchCountEl = $('searchCount');
let searchingActive = false;

function updateSearchCount(count) {
  searchCountEl.textContent = count;
}

function onSearchState(m) {
  updateSearchCount(m.count || 0);
  searchingActive = false;
  if (currentModuleId === 'search') renderSearch(m);
}

function onSearchProgress(m) {
  if (currentModuleId === 'search') {
    const prog = moduleBody.querySelector('.search-progress');
    if (prog) prog.textContent = `Searching... ${m.completed}/${m.total}`;
  }
}

function renderSearch(m) {
  const ratings = m.ratings || {e: true, q: true, s: true, g: true};
  const ratingItems = [
    ['e', 'Explicit'], ['q', 'NSFW'], ['s', 'Sensitive'], ['g', 'General']
  ].map(([k, label]) =>
    `<label class="mod-checkbox-item">
      <input type="checkbox" id="sr_${k}" ${ratings[k] ? 'checked' : ''}>
      <span class="mod-checkbox-label">${label}</span>
    </label>`
  ).join('');

  const parquets = (m.parquets || []).map(f =>
    `<div class="search-parquet-item" onclick="loadParquet('${escHtml(f)}')">${escHtml(f)}</div>`
  ).join('');

  moduleBody.innerHTML = `
    <div class="search-top-row">
      <div>
        <div class="mod-section-label">Remaining</div>
        <div class="search-count-display">${m.count || 0}</div>
      </div>
      <div class="search-top-actions">
        <button class="mod-action-btn mod-refine" onclick="openRefine()" style="display:none">Refine</button>
        <button class="mod-action-btn mod-restore" onclick="restoreSnapshot()">Restore</button>
      </div>
    </div>
    <div>
      <div class="mod-section-label">Search Keyword</div>
      <input class="mod-input" id="searchQuery" type="text" value="${escHtml(m.query)}" placeholder="tags, keywords...">
    </div>
    <div>
      <div class="mod-section-label">Exclude Keyword</div>
      <input class="mod-input" id="searchExclude" type="text" value="${escHtml(m.exclude)}" placeholder="exclude tags...">
    </div>
    <div>
      <div class="mod-section-label">Ratings</div>
      <div class="mod-checkbox-grid">${ratingItems}</div>
    </div>
    <div style="display:flex;gap:8px;align-items:center">
      <button class="mod-action-btn mod-start" onclick="doSearch()" ${searchingActive ? 'disabled' : ''}>Search</button>
      <span class="search-progress" style="font-family:var(--font-mono);font-size:10px;color:var(--text-dim)"></span>
    </div>
    ${parquets.length ? `<div>
      <div class="mod-section-label mod-collapsible" onclick="this.classList.toggle('open');this.nextElementSibling.classList.toggle('collapsed')">
        Custom Parquets (${m.parquets.length}) <span class="mod-collapse-arrow">▶</span>
      </div>
      <div class="search-parquet-list collapsed">${parquets}</div>
    </div>` : ''}
  `;
}

function doSearch() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  const query = (document.getElementById('searchQuery') || {}).value || '';
  const exclude = (document.getElementById('searchExclude') || {}).value || '';
  const ratings = {};
  for (const k of ['e','q','s','g']) {
    const el = document.getElementById('sr_' + k);
    ratings['rating_' + k] = el ? el.checked : true;
  }
  searchingActive = true;
  ws.send(JSON.stringify({type: 'search', query, exclude, ...ratings}));
  const prog = moduleBody.querySelector('.search-progress');
  if (prog) prog.textContent = 'Starting...';
  const btn = moduleBody.querySelector('.mod-start');
  if (btn) btn.disabled = true;
}

function loadParquet(filename) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({type: 'load_parquet', filename}));
}

function restoreSnapshot() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({type: 'restore_snapshot'}));
}

// ---- Refine (Depth Search) panel ----
const refinePanel = $('refinePanel');
let refineOpen = false;

function openRefine() {
  if (refineOpen) { closeRefine(); return; }
  refineOpen = true;
  refinePanel.classList.add('open');
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({type: 'depth_action', action: 'open'}));
    // Request state after a delay (tab needs time to prepare)
    setTimeout(() => {
      if (ws && ws.readyState === WebSocket.OPEN)
        ws.send(JSON.stringify({type: 'get_depth_state'}));
    }, 2500);
  }
}

function closeRefine() {
  refineOpen = false;
  refinePanel.classList.remove('open');
}

function onDepthState(m) {
  if (!refineOpen) return;
  if (!m.open) {
    refinePanel.querySelector('.refine-body').innerHTML =
      '<div style="text-align:center;color:var(--text-dim);padding:20px">Preparing data...</div>';
    return;
  }
  const body = refinePanel.querySelector('.refine-body');
  body.innerHTML = `
    <div class="search-top-row">
      <div>
        <div class="mod-section-label">Filtered</div>
        <div class="search-count-display" style="font-size:18px">${m.count || 0}</div>
      </div>
      <div>
        <div class="mod-section-label">Original</div>
        <div class="search-count-display" style="font-size:18px;color:var(--text-muted)">${m.original || 0}</div>
      </div>
    </div>
    <div>
      <div class="mod-section-label">Filter Tags</div>
      <input class="mod-input" id="depthQuery" type="text" value="${escHtml(m.query)}" placeholder="filter tags...">
    </div>
    <div>
      <div class="mod-section-label">Exclude Tags</div>
      <input class="mod-input" id="depthExclude" type="text" value="${escHtml(m.exclude)}" placeholder="exclude tags...">
    </div>
    <div style="display:flex;gap:6px;flex-wrap:wrap">
      <button class="mod-action-btn mod-start" style="flex:1" onclick="depthFilter()">Filter</button>
      <button class="mod-action-btn mod-refine" style="flex:1" onclick="depthAction('promote')">Promote</button>
    </div>
    <div style="display:flex;gap:6px;flex-wrap:wrap">
      <button class="mod-action-btn mod-start" style="flex:1;background:var(--accent)" onclick="depthAction('assign')">Assign to Main</button>
      <button class="mod-action-btn mod-restore" style="flex:1" onclick="depthAction('restore')">Reset</button>
    </div>
  `;
}

function depthFilter() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  const query = (document.getElementById('depthQuery') || {}).value || '';
  const exclude = (document.getElementById('depthExclude') || {}).value || '';
  ws.send(JSON.stringify({type: 'depth_action', action: 'filter', query, exclude}));
}

function depthAction(action) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({type: 'depth_action', action}));
}

// ---- Keyboard shortcuts ----
document.addEventListener('keydown', e => {
  if (e.key === 'Enter' && e.ctrlKey && !e.shiftKey && !e.altKey) {
    e.preventDefault();
    send('generate');
  } else if (e.key === 'Enter' && e.altKey && !e.ctrlKey && !e.shiftKey) {
    e.preventDefault();
    send('random');
  }
});

// ---- Init ----
promptEdit.addEventListener('input', onPromptEdit);
negEdit.addEventListener('input', onPromptEdit);

connect();
