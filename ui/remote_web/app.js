/* ============================================================
   NAIA Remote — client-side logic
   ============================================================ */

let ws, blobUrl = null, generating = false, drawerOpen = false;
const escHtml = s => s ? s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/'/g,'&#39;').replace(/"/g,'&quot;') : '';
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
        else if (m.type === 'prompt_generated') updatePromptOnly(m.prompt, m.source);
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
        else if (m.type === 'tag_search_result') onTagSearchResult(m);
        else if (m.type === 'tag_lookup_result') onTagLookupResult(m);
        else if (m.type === 'autocomplete_result') onAutocompleteResult(m);
        else if (m.type === 'storage_list') onStorageList(m);
        else if (m.type === 'wildcard_manager') onWildcardManager(m);
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

function updatePromptOnly(prompt, source) {
  if (!prompt) return;
  // Generate 트리거 시에는 웹 프롬프트를 덮어쓰지 않음 (사용자 편집 보존)
  if (source === 'random') {
    syncingPrompt = true;
    promptEdit.value = prompt;
    syncingPrompt = false;
    updatePromptHighlight();
    // Show new-content dot if drawer is closed
    if (!drawerOpen) promptNewDot.classList.remove('hidden');
  }
  // Random 완료 → 버튼 복원 (source 무관)
  btnRnd.disabled = false;
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
  updatePromptHighlight();
}

function onPromptEdit() {
  if (syncingPrompt) return;
  updatePromptHighlight();
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

// ---- NAI weight syntax highlight (main prompt only) ----
const promptHighlight = $('promptHighlight');
const promptWrap = promptHighlight ? promptHighlight.parentElement : null;
let currentMode = 'NAI';

function formatNaiHighlight(text) {
  if (!text) return '<br>';
  let html = '';
  let pos = 0;
  const re = /(-?\d+(?:\.\d+)?)(::)([\s\S]*?)(::)/g;
  let m;
  while ((m = re.exec(text)) !== null) {
    html += escHtml(text.substring(pos, m.index));
    const w = parseFloat(m[1]);
    const cls = w < 1.0 ? 'nai-wt-blue' : w > 1.0 ? 'nai-wt-red' : '';
    const mark = '<span class="nai-wt-mark">::</span>';
    if (cls) {
      html += `<span class="${cls}"><span class="nai-wt-open">${escHtml(m[1])}</span>${mark}${escHtml(m[3])}${mark}</span>`;
    } else {
      html += escHtml(m[1]) + mark + escHtml(m[3]) + mark;
    }
    pos = m.index + m[0].length;
  }
  html += escHtml(text.substring(pos));
  return html + '<br>';
}

function updatePromptHighlight() {
  if (!promptHighlight || currentMode !== 'NAI') return;
  promptHighlight.innerHTML = formatNaiHighlight(promptEdit.value);
}

function syncPromptHighlight() {
  if (promptHighlight) {
    promptHighlight.scrollTop = promptEdit.scrollTop;
    promptHighlight.scrollLeft = promptEdit.scrollLeft;
  }
}

function setNaiHighlightMode(mode) {
  currentMode = mode;
  if (promptWrap) {
    if (mode === 'NAI') {
      promptWrap.classList.add('nai-hl');
      updatePromptHighlight();
    } else {
      promptWrap.classList.remove('nai-hl');
    }
  }
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

// ---- Mobile keyboard detection ----
// Hide bottom controls when virtual keyboard opens to maximize editing space
if (window.visualViewport) {
  const vv = window.visualViewport;
  const bottomCtrl = document.querySelector('.bottom-controls');
  const toggleBarEl = document.querySelector('.prompt-toggle-bar');
  let fullHeight = vv.height;
  // Update fullHeight when not focused (no keyboard)
  vv.addEventListener('resize', () => {
    if (isPC.matches) return;
    const shrink = fullHeight - vv.height;
    const kbOpen = shrink > 100; // >100px shrink = keyboard
    if (kbOpen) {
      bottomCtrl.classList.add('kb-open');
      toggleBarEl.style.display = 'none';
    } else {
      fullHeight = vv.height; // recalibrate
      bottomCtrl.classList.remove('kb-open');
      toggleBarEl.style.display = '';
    }
  });
}

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
  setNaiHighlightMode(mode);
  // NAI 전용 모듈 버튼 비활성화
  const isNai = mode === 'NAI';
  document.querySelectorAll('.module-btn[data-module="character_reference"], .module-btn[data-module="vibe_transfer"]').forEach(btn => {
    btn.classList.toggle('nai-only-disabled', !isNai);
  });
  // 비NAI 모드에서 열려있는 NAI 전용 모듈 닫기
  if (!isNai && (currentModuleId === 'character_reference' || currentModuleId === 'vibe_transfer')) {
    closeModule();
  }
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
  // NAI 전용 모듈 가드
  if ((moduleId === 'character_reference' || moduleId === 'vibe_transfer') && modeSelect.value !== 'NAI') {
    showToast('This module is only available in NAI mode', 'error');
    return;
  }
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
    character_reference: 'Character Reference',
    vibe_transfer: 'Vibe Transfer',
    conditional_prompt: 'Conditional Prompt',
    wildcard: 'Wildcard',
    chunk: 'Chunk',
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
  chunkTriggerInfo = null;
  updateModuleBtnState();
}

function updateModuleBtnState() {
  document.querySelectorAll('.module-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.module === currentModuleId);
  });
}

function onModuleState(m) {
  // Update status badges regardless of panel open state
  if (m.module_id === 'automation') updateAutoBadge(m);
  else if (m.module_id === 'character') updateCharBadge(m);
  else if (m.module_id === 'character_reference') updateCharRefBadge(m);
  else if (m.module_id === 'vibe_transfer') updateVibeBadge(m);

  if (m.module_id !== currentModuleId) return;
  if (m.module_id === 'prompt_engineering') renderPromptEngineering(m);
  else if (m.module_id === 'automation') renderAutomation(m);
  else if (m.module_id === 'character') renderCharacter(m);
  else if (m.module_id === 'conditional_prompt') renderConditionalPrompt(m);
  else if (m.module_id === 'character_reference') renderCharacterReference(m);
  else if (m.module_id === 'vibe_transfer') renderVibeTransfer(m);
  else if (m.module_id === 'wildcard') renderWildcard(m);
  else if (m.module_id === 'chunk') renderChunk(m);
}

// ---- Module button inline badges ----
function updateAutoBadge(m) {
  const btn = document.querySelector('.module-btn[data-module="automation"]');
  const badge = document.getElementById('badgeAuto');
  if (!badge || !btn) return;
  const isRunning = m.is_running;

  if (!isRunning) {
    badge.classList.add('hidden');
    btn.classList.remove('auto-active');
    return;
  }
  btn.classList.add('auto-active');
  badge.classList.remove('hidden');

  const delayInfo = m.delay_info || '';
  const repeatInfo = m.repeat_info || '';
  const status = m.status || '';

  // Priority: delay countdown > repeat > count/timer from status
  if (delayInfo) {
    const dMatch = delayInfo.match(/([\d.]+)\s*s/i) || delayInfo.match(/([\d.:]+)/);
    badge.textContent = dMatch ? dMatch[1] : '…';
  } else if (repeatInfo) {
    const rMatch = repeatInfo.match(/(\d+\/\d+)/);
    badge.textContent = rMatch ? rMatch[1] : '…';
  } else {
    const numMatch = status.match(/(\d+[:/]?\d*)/);
    if (numMatch) badge.textContent = numMatch[1];
    else badge.classList.add('hidden');
  }
}

function updateCharBadge(m) {
  const btn = document.querySelector('.module-btn[data-module="character"]');
  const badge = document.getElementById('badgeChar');
  if (!badge || !btn) return;
  if (!m.activated) {
    badge.classList.add('hidden');
    btn.classList.remove('char-active');
    return;
  }
  const count = m.active_count || 0;
  btn.classList.add('char-active');
  badge.classList.remove('hidden');
  badge.classList.add('char');
  badge.textContent = count;
}

function updateCharRefBadge(m) {
  const btn = document.querySelector('.module-btn[data-module="character_reference"]');
  const badge = document.getElementById('badgeCharRef');
  if (!badge || !btn) return;
  const enabledCount = (m.frames || []).filter(f => f.is_enabled).length;
  if (!enabledCount) {
    badge.classList.add('hidden');
    btn.classList.remove('charref-active');
    return;
  }
  btn.classList.add('charref-active');
  badge.classList.remove('hidden');
  badge.textContent = enabledCount;
}

function updateVibeBadge(m) {
  const btn = document.querySelector('.module-btn[data-module="vibe_transfer"]');
  const badge = document.getElementById('badgeVibe');
  if (!badge || !btn) return;
  const enabledCount = (m.frames || []).filter(f => f.is_enabled).length;
  if (!enabledCount) {
    badge.classList.add('hidden');
    btn.classList.remove('vibe-active');
    return;
  }
  btn.classList.add('vibe-active');
  badge.classList.remove('hidden');
  badge.textContent = enabledCount;
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
  // Bind autocomplete to pre/post prompt textareas
  ['modPrePrompt', 'modPostPrompt'].forEach(id => {
    const el = document.getElementById(id);
    if (el) bindTagAssist(el);
  });
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
  // Bind autocomplete to character prompt textareas (not UC)
  moduleBody.querySelectorAll('.mod-textarea:not(.mod-uc)').forEach(el => bindTagAssist(el));
}

// ---- Conditional Prompt module ----
function formatCondLog(log) {
  if (!log) return '<span style="color:var(--text-dim)">No log yet</span>';
  return escHtml(log).split('\n').map(line => {
    if (!line.trim()) return '';
    if (line.includes('Condition Not Met') || line.includes('Error:'))
      return `<div style="color:#888">${line}</div>`;
    if (line.includes('Condition Met'))
      return `<div style="color:#4CAF50">${line}</div>`;
    if (line.startsWith('==='))
      return `<div style="color:#fff;font-weight:bold">${line}</div>`;
    return `<div>${line}</div>`;
  }).join('');
}

function formatCondRules(text) {
  if (!text) return '<br>';
  return text.split('\n').map(line => {
    if (!line) return '<div class="cond-line"> </div>';
    // 콤마 구분 엔트리별 # 주석 하이라이트
    let result = '';
    let i = 0, inQuote = false;
    let segStart = 0;
    while (i <= line.length) {
      if (i < line.length && line[i] === '"') inQuote = !inQuote;
      if (i === line.length || (line[i] === ',' && !inQuote)) {
        const seg = line.substring(segStart, i);
        const comma = i < line.length ? ',' : '';
        const esc = escHtml(seg);
        if (seg.trimStart().startsWith('#')) {
          result += `<span class="cond-comment">${esc}</span>${escHtml(comma)}`;
        } else {
          result += esc + escHtml(comma);
        }
        segStart = i + 1;
      }
      i++;
    }
    return `<div class="cond-line">${result || ' '}</div>`;
  }).join('') + '<br>';
}
function onCondRulesInput(el) {
  const hl = document.getElementById('condRulesHighlight');
  if (hl) hl.innerHTML = formatCondRules(el.value);
  onModTextEdit('conditional_prompt', 'rules', el.value);
}
function syncCondScroll(el) {
  const hl = document.getElementById('condRulesHighlight');
  if (hl) { hl.scrollTop = el.scrollTop; hl.scrollLeft = el.scrollLeft; }
}

function renderConditionalPrompt(m) {
  moduleBody.innerHTML = `
    <div>
      <label class="mod-checkbox-item">
        <input type="checkbox" ${m.enabled ? 'checked' : ''} onchange="setModuleParam('conditional_prompt','enabled',String(this.checked))">
        <span class="mod-checkbox-label">Enable Conditional Prompt</span>
      </label>
    </div>
    <div>
      <div class="mod-section-label">Rules</div>
      <div class="cond-rules-wrap">
        <div class="cond-rules-highlight" id="condRulesHighlight">${formatCondRules(m.rules)}</div>
        <textarea class="mod-textarea cond-rules-input" id="condRulesInput" placeholder="(condition):action&#10;# comment lines ignored" oninput="onCondRulesInput(this)" onscroll="syncCondScroll(this)">${escHtml(m.rules)}</textarea>
      </div>
    </div>
    <div>
      <div class="mod-section-label mod-collapsible" onclick="this.classList.toggle('open');this.nextElementSibling.classList.toggle('collapsed')">
        Syntax Guide <span class="mod-collapse-arrow">▶</span>
      </div>
      <div class="collapsed" style="font-size:10px;color:var(--text-dim);line-height:1.5;padding:6px 0">
        <b>Condition:</b> tag, ~tag (NOT), *tag (exact), e|q|s|g (rating)<br>
        <b>Logic:</b> &amp; (AND), | (OR), () grouping<br>
        <b>Actions:</b><br>
        &nbsp; tag=new_tag (replace)<br>
        &nbsp; main+=tag (append to main)<br>
        &nbsp; prefix+=tag / postfix+=tag<br>
        &nbsp; ^ = multi-tag separator<br>
        &nbsp; "quoted, tags" for comma values<br>
        <b>Example:</b> (e):prefix+=nsfw^rating:explicit,
      </div>
    </div>
    <div>
      <button class="mod-action-btn mod-start" onclick="setModuleParam('conditional_prompt','test','1')">Test Rules</button>
    </div>
    <div>
      <div class="mod-section-label">Execution Log</div>
      <div class="mod-log-viewer" id="condLogViewer">${formatCondLog(m.log)}</div>
    </div>
  `;
}

// ---- Wildcard Module ----
function renderWildcard(m) {
  // History
  let historyHtml = '';
  if (m.history && m.history.length) {
    historyHtml = m.history.map(h => {
      const n = escHtml(h.name), v = escHtml(h.value);
      return `<div>▶ ${n}: ${v}</div>`;
    }).join('');
  } else {
    historyHtml = '<div class="mod-empty">No wildcards used</div>';
  }

  // Sequential/Dependent state
  let stateHtml = '';
  if (m.state && m.state.length) {
    stateHtml = m.state.map(s => `<div>▶ ${escHtml(s.name)}: ${s.current} / ${s.total}</div>`).join('');
  } else {
    stateHtml = '<div class="mod-empty">No active sequential wildcards</div>';
  }

  // Instant wildcard groups
  let instantHtml = '';
  if (m.instant_groups && m.instant_groups.length) {
    instantHtml = m.instant_groups.map(g => {
      const keys = (g.keys || []).map(k => escHtml(k)).join(', ');
      const more = g.count > 20 ? ` <span style="color:var(--text-dim)">+${g.count - 20} more</span>` : '';
      return `<div class="mod-wc-group">
        <div class="mod-wc-group-header">$${escHtml(g.name)} <span style="color:var(--text-dim)">(${g.count})</span></div>
        <div class="mod-wc-group-keys">${keys}${more}</div>
      </div>`;
    }).join('');
  } else {
    instantHtml = '<div class="mod-empty">No instant wildcards</div>';
  }

  moduleBody.innerHTML = `
    <div class="mod-section">
      <div class="mod-section-label">Used Wildcards</div>
      <div class="mod-wc-history">${historyHtml}</div>
    </div>
    <div class="mod-section">
      <div class="mod-section-label">Sequential / Dependent State</div>
      <div class="mod-wc-state">${stateHtml}</div>
    </div>
    <div class="mod-section">
      <div class="mod-section-label">Instant Wildcards</div>
      <div class="mod-wc-instant">${instantHtml}</div>
    </div>
    <div class="mod-section">
      <label class="mod-check-row">
        <input type="checkbox" ${m.prompt_squeeze ? 'checked' : ''} onchange="setModuleParam('wildcard','prompt_squeeze',String(this.checked))">
        <span style="font-size:12px">NovelAI 403 Prevention</span>
      </label>
    </div>
    <div class="mod-section" style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
      <button class="mod-btn-sm" onclick="wcOpenBrowser()">Browse Files</button>
      <button class="mod-btn-sm" onclick="setModuleParam('wildcard','reset_sequential','')">Reset Seq</button>
      <button class="mod-btn-sm" onclick="setModuleParam('wildcard','reload','')">Reload</button>
      <span style="color:var(--text-dim);font-size:11px;margin-left:auto">Loaded: ${m.wildcard_count || 0}</span>
    </div>
  `;
}

// ---- Chunk Module (instant wildcard tree browser) ----
let chunkTriggerInfo = null;  // {raw, stripped, start, end} — 삽입 위치

function renderChunk(m) {
  const groups = m.groups || [];
  if (!groups.length) {
    moduleBody.innerHTML = '<div class="mod-empty">No instant wildcards found.<br>Add them via the desktop Instant Wildcard module.</div>';
    return;
  }
  let html = '<div class="chunk-hint">Select an item to insert at cursor. Type <code>$</code> or <code>@</code> in prompt to trigger.</div>';
  html += '<div class="chunk-tree">';
  for (const g of groups) {
    html += `<div class="chunk-group">`;
    html += `<div class="chunk-group-name" onclick="chunkToggleGroup(this.parentElement)">📁 ${escHtml(g.name)} <span class="wc-count">(${g.items.length})</span></div>`;
    html += '<div class="chunk-group-items">';
    for (const item of g.items) {
      const preview = item.value.length > 80 ? item.value.substring(0, 80) + '…' : item.value;
      html += `<div class="chunk-item" onclick="chunkInsert(this)" data-value="${escHtml(item.value)}">`;
      html += `<div class="chunk-item-key">${escHtml(item.key)}</div>`;
      html += `<div class="chunk-item-preview">${escHtml(preview)}</div>`;
      html += `</div>`;
    }
    html += '</div></div>';
  }
  html += '</div>';
  moduleBody.innerHTML = html;
}

function chunkToggleGroup(groupEl) {
  const wasOpen = groupEl.classList.contains('open');
  // 다른 그룹 모두 닫기
  groupEl.parentElement.querySelectorAll('.chunk-group.open').forEach(g => g.classList.remove('open'));
  if (!wasOpen) groupEl.classList.add('open');
}

function chunkInsert(el) {
  const value = el.dataset.value;
  if (!value) return;
  const target = acTarget || promptEdit;
  target.focus();
  if (chunkTriggerInfo) {
    // $/@로 트리거된 경우 — 트리거 문자 교체
    target.selectionStart = chunkTriggerInfo.start;
    target.selectionEnd = chunkTriggerInfo.end;
    document.execCommand('insertText', false, value);
    chunkTriggerInfo = null;
  } else {
    // 모듈 버튼으로 열린 경우 — 커서 위치에 삽입
    const pos = target.selectionStart != null ? target.selectionStart : target.value.length;
    const text = target.value;
    const before = text.substring(0, pos);
    // 앞에 콤마+공백 필요 여부
    const sep = before.length > 0 && !before.endsWith(', ') && !before.endsWith(',') ? ', ' : '';
    target.selectionStart = target.selectionEnd = pos;
    document.execCommand('insertText', false, sep + value);
  }
  if (target === promptEdit) onPromptEdit();
  // 자동 닫기
  closeModule();
}

// ---- Wildcard Manager (file browser + editor + generator) ----
let wcCurrentPath = '';
let wcEditMode = false;

function wcOpenBrowser() {
  setModuleParam('wildcard', 'get_file_tree', '');
}

function onWildcardManager(m) {
  if (m.action === 'file_tree') wcRenderTree(m.tree);
  else if (m.action === 'file_content') wcRenderEditor(m.path, m.content);
  else if (m.action === 'preview_result') wcShowPreview(m.name, m.result);
  else if (m.action === 'save_ok') showToast('File saved', 'success');
  else if (m.action === 'file_deleted') { showToast('File deleted', 'success'); wcCurrentPath = ''; }
}

function wcRenderTree(tree) {
  let html = '<div class="mod-section" style="display:flex;gap:6px;margin-bottom:8px">'
    + '<button class="mod-btn-sm" onclick="openModule(\'wildcard\')">← Back</button>'
    + '<button class="mod-btn-sm" onclick="wcPromptNewFile()">+ New File</button>'
    + '<button class="mod-btn-sm" onclick="setModuleParam(\'wildcard\',\'get_file_tree\',\'\')">Refresh</button>'
    + '</div>';
  html += '<div class="mod-wc-tree">';
  if (!tree || !tree.length) {
    html += '<div class="mod-empty">No wildcard files found</div>';
  } else {
    for (const item of tree) {
      if (item.type === 'folder') {
        html += `<div class="wc-folder"><div class="wc-folder-name" onclick="this.parentElement.classList.toggle('open')">📁 ${escHtml(item.name)} <span class="wc-count">(${item.files.length})</span></div>`;
        html += '<div class="wc-folder-children">';
        for (const f of item.files) {
          html += `<div class="wc-file" onclick="setModuleParam('wildcard','read_file','${escHtml(f.path)}')">📄 ${escHtml(f.name)} <span class="wc-count">${f.lines}L</span></div>`;
        }
        html += '</div></div>';
      } else {
        html += `<div class="wc-file" onclick="setModuleParam('wildcard','read_file','${escHtml(item.path)}')">📄 ${escHtml(item.name)} <span class="wc-count">${item.lines}L</span></div>`;
      }
    }
  }
  html += '</div>';
  // Generator guide
  html += `<div class="mod-section" style="margin-top:10px">
    <div class="mod-section-label">Wildcard Syntax Guide</div>
    <div class="wc-syntax-guide">
      <div><code>__name__</code> — Random pick from <code>name.txt</code></div>
      <div><code>__*name__</code> — Sequential (ordered)</div>
      <div><code>__*master__</code> + <code>__$master:slave__</code> — Dependent</div>
      <div><code>200:text</code> — Weighted entry (default 100)</div>
      <div><code>__folder/name__</code> — Subfolder path</div>
    </div>
  </div>`;
  moduleBody.innerHTML = html;
}

function wcRenderEditor(path, content) {
  wcCurrentPath = path;
  wcEditMode = false;
  const fname = path.split('/').pop();
  const wcName = fname.replace('.txt', '');
  moduleBody.innerHTML = `
    <div class="mod-section" style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
      <button class="mod-btn-sm" onclick="setModuleParam('wildcard','get_file_tree','')">← Tree</button>
      <span class="wc-file-path">${escHtml(path)}</span>
      <span style="flex:1"></span>
      <button class="mod-btn-sm" id="wcEditBtn" onclick="wcToggleEdit()">Edit</button>
      <button class="mod-btn-sm mod-btn-danger" onclick="wcDeleteFile()">Delete</button>
    </div>
    <div class="mod-section">
      <textarea class="wc-editor" id="wcEditor" readonly>${escHtml(content)}</textarea>
    </div>
    <div class="mod-section" id="wcEditActions" style="display:none;gap:6px;flex-wrap:wrap">
      <button class="mod-btn-sm" style="background:#4CAF50;color:#fff" onclick="wcSaveFile()">Save</button>
      <button class="mod-btn-sm" onclick="wcCancelEdit()">Cancel</button>
    </div>
    <div class="mod-section">
      <div class="mod-section-label">Quick Add Entry</div>
      <div style="display:flex;gap:6px;align-items:center">
        <input type="text" class="wc-add-input" id="wcAddText" placeholder="tag or prompt text">
        <button class="mod-btn-sm" onclick="wcAddEntry()">Add</button>
      </div>
    </div>
    <div class="mod-section">
      <div class="mod-section-label">Preview <code>__${escHtml(wcName)}__</code></div>
      <div style="display:flex;gap:6px;align-items:center">
        <button class="mod-btn-sm" onclick="setModuleParam('wildcard','preview_wildcard','${escHtml(wcName)}')">Roll ×5</button>
        <div class="wc-preview" id="wcPreview"></div>
      </div>
    </div>
  `;
}

function wcToggleEdit() {
  const editor = document.getElementById('wcEditor');
  const actions = document.getElementById('wcEditActions');
  const btn = document.getElementById('wcEditBtn');
  if (!editor) return;
  wcEditMode = !wcEditMode;
  editor.readOnly = !wcEditMode;
  editor.classList.toggle('editing', wcEditMode);
  actions.style.display = wcEditMode ? 'flex' : 'none';
  btn.textContent = wcEditMode ? 'Cancel' : 'Edit';
}

function wcCancelEdit() {
  // Reload file to discard changes
  if (wcCurrentPath) setModuleParam('wildcard', 'read_file', wcCurrentPath);
}

function wcSaveFile() {
  const editor = document.getElementById('wcEditor');
  if (!editor || !wcCurrentPath) return;
  setModuleParam('wildcard', 'save_file', JSON.stringify({path: wcCurrentPath, content: editor.value}));
}

function wcDeleteFile() {
  if (!wcCurrentPath) return;
  if (!confirm('Delete ' + wcCurrentPath + '?')) return;
  setModuleParam('wildcard', 'delete_file', wcCurrentPath);
  setModuleParam('wildcard', 'get_file_tree', '');
}

function wcAddEntry() {
  const text = document.getElementById('wcAddText');
  const editor = document.getElementById('wcEditor');
  if (!text || !editor || !text.value.trim()) return;
  const line = text.value.trim();
  // Append to editor
  const current = editor.value;
  editor.value = current ? current + '\n' + line : line;
  text.value = '';
  // Auto-enable edit mode and save
  if (!wcEditMode) {
    wcEditMode = true;
    editor.readOnly = false;
    editor.classList.add('editing');
    const actions = document.getElementById('wcEditActions');
    if (actions) actions.style.display = 'flex';
    const btn = document.getElementById('wcEditBtn');
    if (btn) btn.textContent = 'Cancel';
  }
}

function wcShowPreview(name, result) {
  const el = document.getElementById('wcPreview');
  if (el) el.innerHTML = escHtml(result).replace(/\n/g, '<br>');
}

function wcPromptNewFile() {
  const name = prompt('New wildcard filename (e.g. "my_tags" or "folder/my_tags"):');
  if (!name || !name.trim()) return;
  setModuleParam('wildcard', 'create_file', name.trim());
}

// ---- Image upload helper ----
function uploadModuleImage(moduleId, file) {
  if (!file || !file.type.startsWith('image/')) return;
  const body = document.getElementById('modulePopupBody');
  if (body) {
    const ind = document.createElement('div');
    ind.className = 'mod-upload-indicator';
    ind.textContent = 'Uploading...';
    ind.id = 'uploadIndicator';
    body.prepend(ind);
  }
  // Client-side resize to max 2048px to save bandwidth
  const img = new Image();
  const reader = new FileReader();
  reader.onload = () => {
    img.onload = () => {
      let w = img.width, h = img.height;
      const MAX = 2048;
      if (w > MAX || h > MAX) {
        if (w > h) { h = Math.round(h * MAX / w); w = MAX; }
        else { w = Math.round(w * MAX / h); h = MAX; }
      }
      const canvas = document.createElement('canvas');
      canvas.width = w; canvas.height = h;
      canvas.getContext('2d').drawImage(img, 0, 0, w, h);
      const dataUrl = canvas.toDataURL('image/png');
      const b64 = dataUrl.split(',')[1];
      setModuleParam(moduleId, 'upload_image', b64);
    };
    img.src = reader.result;
  };
  reader.readAsDataURL(file);
}

// ---- Slider debounce for image modules ----
let _sliderDebounce = {};
function onModSlider(moduleId, key, value) {
  const k = moduleId + '.' + key;
  if (_sliderDebounce[k]) clearTimeout(_sliderDebounce[k]);
  _sliderDebounce[k] = setTimeout(() => {
    setModuleParam(moduleId, key, value);
    delete _sliderDebounce[k];
  }, 300);
}

// ---- Character Reference module ----
let _storageView = null; // tracks which storage is open

function renderCharacterReference(m) {
  if (!m.is_naid45) {
    moduleBody.innerHTML = '<div class="mod-notice">Character Reference requires NAID4.5F/C model</div>';
    return;
  }
  const frames = (m.frames || []).map((f, i) => `
    <div class="mod-ref-frame ${f.is_enabled ? '' : 'disabled'}">
      <div class="mod-ref-header">
        <img class="mod-ref-thumb" src="data:image/jpeg;base64,${f.thumbnail}" alt="${escHtml(f.file_name)}">
        <div class="mod-ref-controls">
          <div class="mod-ref-controls-row">
            <label class="mod-checkbox-item">
              <input type="checkbox" ${f.is_enabled ? 'checked' : ''}
                onchange="setModuleParam('character_reference','enable_${i}',String(this.checked))">
              <span class="mod-checkbox-label">Enable</span>
            </label>
            <select class="mod-select-sm"
              onchange="setModuleParam('character_reference','ref_type_${i}',this.value)">
              <option value="character&style" ${f.reference_type==='character&style'?'selected':''}>Char & Style</option>
              <option value="character" ${f.reference_type==='character'?'selected':''}>Character</option>
              <option value="style" ${f.reference_type==='style'?'selected':''}>Style</option>
            </select>
            <button class="mod-btn-sm mod-btn-danger" onclick="setModuleParam('character_reference','remove_frame_${i}','')">Remove</button>
          </div>
          <div class="mod-slider-row">
            <span class="mod-slider-label">Strength</span>
            <input type="range" min="0" max="20" step="1" value="${Math.round(f.strength*20)}"
              oninput="this.nextElementSibling.textContent=(this.value/20).toFixed(2);onModSlider('character_reference','strength_${i}',(this.value/20).toFixed(2))">
            <span class="mod-slider-value">${f.strength.toFixed(2)}</span>
          </div>
          <div class="mod-slider-row">
            <span class="mod-slider-label">Fidelity</span>
            <input type="range" min="0" max="20" step="1" value="${Math.round(f.fidelity*20)}"
              oninput="this.nextElementSibling.textContent=(this.value/20).toFixed(2);onModSlider('character_reference','fidelity_${i}',(this.value/20).toFixed(2))">
            <span class="mod-slider-value">${f.fidelity.toFixed(2)}</span>
          </div>
        </div>
      </div>
    </div>
  `).join('');

  moduleBody.innerHTML = `
    <div class="mod-upload-bar">
      <button class="mod-btn-upload" onclick="document.getElementById('charRefFileInput').click()">Upload</button>
      <input type="file" id="charRefFileInput" accept="image/*" style="display:none"
        onchange="uploadModuleImage('character_reference',this.files[0]);this.value=''">
      <button class="mod-btn-upload mod-btn-storage" onclick="requestStorage('character_reference')">Storage</button>
    </div>
    ${frames.length ? frames : '<div class="mod-empty">No character references loaded</div>'}
  `;
}

// ---- Vibe Transfer module ----
function renderVibeTransfer(m) {
  const frames = (m.frames || []).map((f, i) => {
    const thumbHtml = f.is_no_image
      ? '<div class="mod-ref-noimage">No Image</div>'
      : `<img class="mod-ref-thumb" src="data:image/jpeg;base64,${f.thumbnail}" alt="${escHtml(f.file_name)}">`;

    const encHtml = f.is_no_image ? '' : `
      <div class="mod-ref-encoding">
        ${f.has_encoding
          ? '<span class="mod-encode-status encoded">Encoded</span>'
          : `<button class="mod-btn-sm mod-btn-encode" onclick="setModuleParam('vibe_transfer','encode_${i}','')">Encode (2 Anlas)</button>`}
        ${f.encoding_keys.length ? `<span class="mod-encode-keys">IE: ${f.encoding_keys.map(k=>Number(k).toFixed(2)).join(', ')}</span>` : ''}
      </div>`;

    return `
    <div class="mod-ref-frame ${f.is_enabled ? '' : 'disabled'}">
      <div class="mod-ref-header">
        ${thumbHtml}
        <div class="mod-ref-controls">
          <div class="mod-ref-controls-row">
            <label class="mod-checkbox-item">
              <input type="checkbox" ${f.is_enabled ? 'checked' : ''}
                onchange="setModuleParam('vibe_transfer','enable_${i}',String(this.checked))">
              <span class="mod-checkbox-label">Enable</span>
            </label>
            <button class="mod-btn-sm mod-btn-danger" onclick="setModuleParam('vibe_transfer','remove_frame_${i}','')">Remove</button>
          </div>
          <div class="mod-slider-row">
            <span class="mod-slider-label">Ref Strength</span>
            <input type="range" min="-100" max="100" step="1" value="${Math.round(f.reference_strength*100)}"
              oninput="this.nextElementSibling.textContent=(this.value/100).toFixed(2);onModSlider('vibe_transfer','ref_strength_${i}',(this.value/100).toFixed(2))">
            <span class="mod-slider-value">${f.reference_strength.toFixed(2)}</span>
          </div>
          <div class="mod-slider-row">
            <span class="mod-slider-label">Info Extracted</span>
            <input type="range" min="1" max="100" step="1" value="${Math.round(f.information_extracted*100)}"
              oninput="this.nextElementSibling.textContent=(this.value/100).toFixed(2);onModSlider('vibe_transfer','info_extracted_${i}',(this.value/100).toFixed(2))">
            <span class="mod-slider-value">${f.information_extracted.toFixed(2)}</span>
          </div>
          ${encHtml}
        </div>
      </div>
    </div>`;
  }).join('');

  moduleBody.innerHTML = `
    <div class="mod-upload-bar">
      <button class="mod-btn-upload" onclick="document.getElementById('vibeFileInput').click()">Upload</button>
      <input type="file" id="vibeFileInput" accept="image/*" style="display:none"
        onchange="uploadModuleImage('vibe_transfer',this.files[0]);this.value=''">
      <button class="mod-btn-upload mod-btn-storage" onclick="requestStorage('vibe_transfer')">Storage</button>
      <span class="mod-frame-count">${m.frame_count}/${m.max_frames}</span>
    </div>
    <label class="mod-checkbox-item" style="margin-bottom:8px">
      <input type="checkbox" ${m.normalize ? 'checked' : ''}
        onchange="setModuleParam('vibe_transfer','normalize',String(this.checked))">
      <span class="mod-checkbox-label">Normalize reference strength</span>
    </label>
    ${frames.length ? frames : '<div class="mod-empty">No vibe transfers loaded</div>'}
  `;
}

// ---- Storage view ----
function requestStorage(moduleId) {
  _storageView = moduleId;
  setModuleParam(moduleId, 'get_storage', '');
}

function onStorageList(m) {
  if (m.module_id === 'character_reference') renderCharRefStorage(m);
  else if (m.module_id === 'vibe_transfer') renderVibeStorage(m);
}

function renderCharRefStorage(m) {
  if (currentModuleId !== 'character_reference') return;
  const items = (m.items || []).map(it => `
    <div class="mod-storage-item" onclick="applyCharRefStorage('${escHtml(it.file_hash)}')" title="${escHtml(it.file_name)}">
      <img class="mod-storage-thumb" src="data:image/jpeg;base64,${it.thumbnail}" alt="">
      <span class="mod-storage-name">${escHtml(it.character_name || it.file_name)}</span>
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
  // 적용 후 메인 뷰로 복귀
  setTimeout(() => openModule('character_reference'), 500);
}

function renderVibeStorage(m) {
  if (currentModuleId !== 'vibe_transfer') return;
  const modelNames = Object.keys(m.models || {});
  const currentModel = m.current_model || '';

  // Build tabs
  const tabBtns = modelNames.map(name =>
    `<button class="mod-btn-sm mod-storage-tab ${name===currentModel?'active':''}" onclick="showVibeStorageTab(this,'${escHtml(name)}')">${escHtml(name)}</button>`
  ).join('');

  // Build tab contents
  const tabContents = modelNames.map(name => {
    const items = (m.models[name] || []).map(it => {
      const ieKeys = (it.encoding_keys || []);
      const defaultIe = ieKeys.length ? ieKeys[0] : 1.0;
      return `
        <div class="mod-storage-item" onclick="applyVibeStorage('${escHtml(name)}','${escHtml(it.file_hash)}',${defaultIe})" title="${escHtml(it.file_name)}">
          <img class="mod-storage-thumb" src="data:image/jpeg;base64,${it.thumbnail}" alt="">
          <span class="mod-storage-name">${escHtml(it.file_name)}</span>
          ${ieKeys.length ? `<span class="mod-encode-keys">IE: ${ieKeys.map(k=>Number(k).toFixed(2)).join(', ')}</span>` : ''}
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
  // Toggle tab buttons
  btn.parentElement.querySelectorAll('.mod-storage-tab').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  // Toggle content
  moduleBody.querySelectorAll('.mod-vibe-tab').forEach(el => {
    el.style.display = el.dataset.model === model ? '' : 'none';
  });
}

function applyVibeStorage(model, fileHash, ieValue) {
  setModuleParam('vibe_transfer', 'apply_storage', model + '|' + fileHash + '|' + ieValue);
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
        <button class="mod-action-btn mod-refine" onclick="openRefine()">Refine</button>
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
    // 먼저 현재 상태 요청 (이미 열려있을 수 있음)
    ws.send(JSON.stringify({type: 'get_depth_state'}));
    // 열려있지 않으면 open 요청 → 서버가 tab_added 시그널로 자동 브로드캐스트
    ws.send(JSON.stringify({type: 'depth_action', action: 'open'}));
  }
}

function closeRefine() {
  refineOpen = false;
  refinePanel.classList.remove('open');
}

function onDepthState(m) {
  if (!refineOpen) return;
  if (!m.open) {
    const msg = m.error === 'no_search_results'
      ? 'No search results loaded.<br><span style="font-size:10px">Run a search first</span>'
      : 'Preparing data...';
    refinePanel.querySelector('.refine-body').innerHTML =
      `<div style="text-align:center;color:var(--text-dim);padding:20px">${msg}</div>`;
    return;
  }
  const body = refinePanel.querySelector('.refine-body');
  // 카운트만 업데이트 (입력 필드가 이미 있으면 리빌드 방지)
  const existing = body.querySelector('#depthQuery');
  if (existing) {
    const counts = body.querySelectorAll('.search-count-display');
    if (counts[0]) counts[0].textContent = m.count || 0;
    if (counts[1]) counts[1].textContent = m.original || 0;
    // 스테이징 카운트 갱신
    const sc = body.querySelector('.depth-staging-count');
    if (sc) sc.textContent = m.staging_count || 0;
    return;
  }
  const r = m.ratings || {e:true,q:true,s:true,g:true};
  const f = m.filters || {};
  const ck = (name, def) => { const v = f[name]; return v ? v.enabled : def; };
  const fv = (name, def) => { const v = f[name]; return v ? escHtml(v.value) : def; };
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
    <div>
      <div class="mod-section-label">Ratings</div>
      <div class="mod-checkbox-grid">
        <label class="mod-checkbox-item"><input type="checkbox" id="dr_e" ${r.e?'checked':''}><span class="mod-checkbox-label">E</span></label>
        <label class="mod-checkbox-item"><input type="checkbox" id="dr_q" ${r.q?'checked':''}><span class="mod-checkbox-label">Q</span></label>
        <label class="mod-checkbox-item"><input type="checkbox" id="dr_s" ${r.s?'checked':''}><span class="mod-checkbox-label">S</span></label>
        <label class="mod-checkbox-item"><input type="checkbox" id="dr_g" ${r.g?'checked':''}><span class="mod-checkbox-label">G</span></label>
      </div>
    </div>
    <div class="mod-section-label" style="margin-top:4px">Numeric Filters</div>
    <div class="depth-filter-grid">
      <label class="mod-checkbox-item"><input type="checkbox" id="df_token_min" ${ck('token_min',false)?'checked':''}><span class="mod-checkbox-label">Tokens ≥</span></label>
      <input class="mod-input mod-input-sm" id="dfv_token_min" type="number" value="${fv('token_min','0')}">
      <label class="mod-checkbox-item"><input type="checkbox" id="df_token_max" ${ck('token_max',false)?'checked':''}><span class="mod-checkbox-label">Tokens ≤</span></label>
      <input class="mod-input mod-input-sm" id="dfv_token_max" type="number" value="${fv('token_max','150')}">
      <label class="mod-checkbox-item"><input type="checkbox" id="df_id_min" ${ck('id_min',false)?'checked':''}><span class="mod-checkbox-label">ID ≥</span></label>
      <input class="mod-input mod-input-sm" id="dfv_id_min" type="number" value="${fv('id_min','0')}">
      <label class="mod-checkbox-item"><input type="checkbox" id="df_id_max" ${ck('id_max',false)?'checked':''}><span class="mod-checkbox-label">ID ≤</span></label>
      <input class="mod-input mod-input-sm" id="dfv_id_max" type="number" value="${fv('id_max','99999999')}">
      <label class="mod-checkbox-item"><input type="checkbox" id="df_score_min" ${ck('score_min',false)?'checked':''}><span class="mod-checkbox-label">Score ≥</span></label>
      <input class="mod-input mod-input-sm" id="dfv_score_min" type="number" value="${fv('score_min','0')}">
    </div>
    <div class="mod-checkbox-grid" style="margin-top:4px">
      <label class="mod-checkbox-item"><input type="checkbox" id="df_rem_char" ${f.rem_char?'checked':''}><span class="mod-checkbox-label">Has Character</span></label>
      <label class="mod-checkbox-item"><input type="checkbox" id="df_only_empty_char" ${f.only_empty_char?'checked':''}><span class="mod-checkbox-label">No Character</span></label>
    </div>
    <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:6px">
      <button class="mod-action-btn mod-start" style="flex:1" onclick="depthFilter()">Filtered Search</button>
      <button class="mod-action-btn mod-restore" style="flex:1" onclick="depthAction('restore')">Restore</button>
    </div>
    <div style="display:flex;gap:6px;flex-wrap:wrap">
      <button class="mod-action-btn mod-start" style="flex:1;background:var(--accent)" onclick="depthAction('assign')">Assign to Main</button>
      <button class="mod-action-btn mod-refine" style="flex:1" onclick="depthAction('promote')" title="Set current filtered results as the new baseline">Set as Baseline</button>
    </div>
    <div class="mod-section-label mod-collapsible" onclick="this.classList.toggle('open');this.nextElementSibling.classList.toggle('collapsed')" style="margin-top:6px">
      Staging & Export <span class="mod-collapse-arrow">▶</span>
    </div>
    <div class="collapsed" style="display:flex;flex-direction:column;gap:6px">
      <div style="display:flex;gap:6px;align-items:center">
        <button class="mod-action-btn" style="flex:1" onclick="depthAction('stage')">+ Stage Current</button>
        <span style="font-family:var(--font-mono);font-size:10px;color:var(--text-dim)">Staged: <span class="depth-staging-count">${m.staging_count||0}</span></span>
      </div>
      <div style="display:flex;gap:6px">
        <button class="mod-action-btn" style="flex:1" onclick="depthAction('merge_staging')">Merge Staged</button>
        <button class="mod-action-btn mod-restore" style="flex:1" onclick="depthAction('clear_staging')">Clear</button>
      </div>
      <button class="mod-action-btn" style="width:100%" onclick="depthAction('export')">Export to Custom Parquet</button>
    </div>
  `;
}

function depthFilter() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  const query = ($('depthQuery') || {}).value || '';
  const exclude = ($('depthExclude') || {}).value || '';
  const ratings = {};
  for (const k of ['e','q','s','g']) {
    const el = $('dr_' + k);
    ratings[k] = el ? el.checked : true;
  }
  const filters = {};
  for (const name of ['token_min','token_max','id_min','id_max','score_min']) {
    const check = $('df_' + name);
    const inp = $('dfv_' + name);
    if (check && inp) filters[name] = {enabled: check.checked, value: inp.value};
  }
  filters.rem_char = ($('df_rem_char') || {}).checked || false;
  filters.only_empty_char = ($('df_only_empty_char') || {}).checked || false;
  ws.send(JSON.stringify({type: 'depth_action', action: 'filter', query, exclude, ratings, filters}));
}

function depthAction(action) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({type: 'depth_action', action}));
}

// ---- Tag search (KR/EN) ----
const tagSearchInput = $('tagSearchInput');
const tagSearchResults = $('tagSearchResults');
let tagSearchTimer = null;

let tagComposing = false;
tagSearchInput.addEventListener('compositionstart', () => { tagComposing = true; });
tagSearchInput.addEventListener('compositionend', () => {
  tagComposing = false;
  fireTagSearch();
});
tagSearchInput.addEventListener('input', () => {
  if (!tagComposing) fireTagSearch();
});
function fireTagSearch() {
  clearTimeout(tagSearchTimer);
  const q = tagSearchInput.value.trim();
  if (!q) { tagSearchResults.classList.remove('open'); return; }
  tagSearchTimer = setTimeout(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({type: 'tag_search', query: q}));
    }
  }, 150);  // 150ms — 실시간 체감
}

// 외부 클릭 시 결과 닫기
document.addEventListener('click', e => {
  if (!e.target.closest('.tag-search-bar')) tagSearchResults.classList.remove('open');
});

function onTagSearchResult(m) {
  // 입력이 이미 지워졌으면 (태그 삽입 후) 무시
  if (!tagSearchInput.value.trim()) { tagSearchResults.classList.remove('open'); return; }
  if (!m.results || !m.results.length) {
    tagSearchResults.classList.remove('open');
    return;
  }
  const fmtCount = n => n >= 1e6 ? (n/1e6).toFixed(1)+'M' : n >= 1e3 ? (n/1e3).toFixed(0)+'k' : String(n);
  tagSearchResults.innerHTML = m.results.map((r, i) =>
    `<div class="tag-result-item" data-idx="${i}">
      <span class="tag-result-tag">${escHtml(r.tag)}</span>
      <span class="tag-result-desc">${escHtml(r.desc || r.group || '')}</span>
      <span class="tag-result-count">${fmtCount(r.count)}</span>
    </div>`
  ).join('');
  // data 속성 + addEventListener로 XSS 방지
  tagSearchResults.querySelectorAll('.tag-result-item').forEach(el => {
    const idx = +el.dataset.idx;
    el.addEventListener('click', () => insertTag(m.results[idx].tag));
  });
  tagSearchResults.classList.add('open');
}

function insertTag(tag) {
  const pe = promptEdit;
  const cur = pe.value;
  const start = pe.selectionStart != null ? pe.selectionStart : cur.length;
  // 커서 앞 문자 기준으로 쉼표 구분 판단
  const before = cur.substring(0, start);
  const needSep = before.length > 0 && !before.endsWith(', ') && !before.endsWith(',') && before.trim().length > 0;
  const sep = needSep ? ', ' : '';
  pe.value = before + sep + tag + ', ' + cur.substring(start);
  pe.focus();
  const newPos = start + sep.length + tag.length + 2;
  pe.selectionStart = pe.selectionEnd = newPos;
  onPromptEdit();
  clearTimeout(tagSearchTimer);
  tagSearchInput.value = '';
  tagSearchResults.classList.remove('open');
}

// ---- Tag tooltip + Autocomplete system ----
const tagTooltip = $('tagTooltip');
let lastLookupTag = '';
let tagLookupTimer = null;
// Autocomplete state
let acMode = false;
let acResults = [];
let acSel = -1;
let acTimer = null;
let lastAcQuery = '';
let acTarget = null; // active textarea for autocomplete/hint
let acComposing = false; // IME composition guard

const fmtCount = n => n >= 1e6 ? (n/1e6).toFixed(1)+'M' : n >= 1e3 ? (n/1e3).toFixed(0)+'k' : String(n);
const CAT_COLORS = { artist: '#d4736a', copyright: '#a87fd4', character: '#6abf7b', e621: '#d4c36a', wildcard: '#6ac4d4' };
function catStyle(cat) { return cat && CAT_COLORS[cat] ? ` style="color:${CAT_COLORS[cat]}"` : ''; }

// Extract active token info at cursor (comma-delimited, NAI weight/bracket aware)
function getActiveTokenInfo(textarea) {
  const text = textarea.value;
  const pos = textarea.selectionStart != null ? textarea.selectionStart : -1;
  if (pos < 0 || text.length === 0) return null;
  let start = text.lastIndexOf(',', pos - 1) + 1;
  let end = text.indexOf(',', pos);
  if (end === -1) end = text.length;
  while (start < end && text[start] === ' ') start++;
  let rawEnd = end;
  while (rawEnd > start && text[rawEnd - 1] === ' ') rawEnd--;
  const raw = text.substring(start, rawEnd);
  if (!raw || raw.startsWith('#')) return null;
  let stripped = raw;
  stripped = stripped.replace(/^-?\(+/, '');
  stripped = stripped.replace(/(?::[\d.]+)?\)+$/, '');
  stripped = stripped.replace(/^\d+(?:\.\d+)?::/, '');
  stripped = stripped.replace(/\s*::$/, '');
  stripped = stripped.trim();
  if (!stripped) return null;
  return { raw, stripped, start, end: rawEnd };
}

function getTagAtCursor(textarea) {
  const info = getActiveTokenInfo(textarea);
  return info ? info.stripped : '';
}

// ---- Info mode (tag_lookup) ----
function checkTagHint() {
  if (acMode) return;
  const target = acTarget || promptEdit;
  const tag = getTagAtCursor(target);
  if (tag === lastLookupTag) return;
  lastLookupTag = tag;
  if (!tag) { tagTooltip.classList.remove('open', 'ac-mode'); return; }
  tagTooltip.classList.remove('open', 'ac-mode');
  clearTimeout(tagLookupTimer);
  tagLookupTimer = setTimeout(() => {
    if (ws && ws.readyState === WebSocket.OPEN)
      ws.send(JSON.stringify({type: 'tag_lookup', tag}));
  }, 200);
}

function onTagLookupResult(m) {
  if (acMode) return;
  if (!m.tag) { tagTooltip.classList.remove('open', 'ac-mode'); return; }
  if (m.tag.toLowerCase() !== lastLookupTag.toLowerCase()) return;
  const groupText = [m.group, m.subgroup].filter(Boolean).join(' / ');
  let html = '<div class="tag-tooltip-main">' +
    `<span class="tag-tooltip-tag"${catStyle(m.cat)}>${escHtml(m.tag)}</span>` +
    `<span class="tag-tooltip-count">${fmtCount(m.count||0)}</span>` +
    (groupText ? ` <span class="tag-tooltip-group">${escHtml(groupText)}</span>` : '') +
    (m.desc ? `<span class="tag-tooltip-desc">${escHtml(m.desc)}</span>` : '') +
    '</div>';
  if (m.implications && m.implications.length) {
    html += '<div class="tag-tooltip-extra"><span class="tag-tooltip-extra-label">implies</span>' +
      m.implications.map(t => `<span class="tag-tooltip-extra-tag" data-insert="${escHtml(t)}">${escHtml(t)}</span>`).join('') + '</div>';
  }
  if (m.related && m.related.length) {
    html += '<div class="tag-tooltip-extra"><span class="tag-tooltip-extra-label">related</span>' +
      m.related.map(t => `<span class="tag-tooltip-extra-tag" data-insert="${escHtml(t)}">${escHtml(t)}</span>`).join('') + '</div>';
  }
  tagTooltip.innerHTML = html;
  tagTooltip.classList.remove('ac-mode');
  tagTooltip.classList.add('open');
  // Click on related/implies tag → insert next to current token in active textarea
  tagTooltip.querySelectorAll('.tag-tooltip-extra-tag[data-insert]').forEach(el => {
    el.addEventListener('mousedown', e => {
      e.preventDefault();
      const target = acTarget || promptEdit;
      const tag = el.dataset.insert;
      const info = getActiveTokenInfo(target);
      if (!info) return;
      const text = target.value;
      target.value = text.substring(0, info.end) + ', ' + tag + text.substring(info.end);
      const newPos = info.end + 2 + tag.length;
      target.selectionStart = target.selectionEnd = newPos;
      target.focus();
      if (target === promptEdit) onPromptEdit();
      else _fireModuleOninput(target);
      lastLookupTag = '';
      checkTagHint();
    });
  });
}

// ---- Autocomplete mode ----
function scheduleAutocomplete() {
  const target = acTarget || promptEdit;
  const info = getActiveTokenInfo(target);
  if (!info || info.stripped.length < 2) {
    hideAutocomplete();
    checkTagHint();
    return;
  }
  if (info.stripped === lastAcQuery) return;
  lastAcQuery = info.stripped;
  clearTimeout(acTimer);
  clearTimeout(tagLookupTimer);
  acTimer = setTimeout(() => {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const s = info.stripped;
    if (s.startsWith('__')) {
      // Wildcard autocomplete: __keyword → search wildcard names
      const q = s.replace(/^_+/, '').replace(/_+$/, '');
      if (q.length >= 1) ws.send(JSON.stringify({type: 'autocomplete_wildcard', query: q}));
    } else if (s.startsWith('$') || s.startsWith('@')) {
      // Chunk trigger: open Chunk module panel
      clearTimeout(acTimer);
      chunkTriggerInfo = info;  // 삽입 위치 기억
      openModule('chunk');
      return;
    } else {
      ws.send(JSON.stringify({type: 'autocomplete', query: s}));
    }
  }, 150);
}

function onAutocompleteResult(m) {
  // Accept results for wildcard queries too
  const q = lastAcQuery;
  const matchesWc = q && q.startsWith('__') && m.query === q.replace(/^_+/, '').replace(/_+$/, '');
  if (!matchesWc && m.query !== q) return;
  if (!m.results || !m.results.length) {
    hideAutocomplete();
    checkTagHint();
    return;
  }
  acResults = m.results;
  acSel = -1;
  acMode = true;
  renderAutocomplete();
}

function renderAutocomplete() {
  let html = '<div class="tag-ac-list">';
  acResults.forEach((r, i) => {
    const sel = i === acSel ? ' selected' : '';
    const wcType = r._wc_type;
    const tagColor = wcType ? catStyle(wcType) : catStyle(r.cat);
    const prefix = wcType === 'wildcard' ? '__' : '';
    const suffix = wcType === 'wildcard' ? '__' : '';
    html += `<div class="tag-ac-item${sel}" data-idx="${i}">` +
      `<span class="tag-ac-tag"${tagColor}>${escHtml(prefix + r.tag + suffix)}</span>` +
      `<span class="tag-ac-group">${escHtml(r.group || '')}</span>` +
      `<span class="tag-ac-count">${wcType ? escHtml(r.desc || '') : fmtCount(r.count)}</span>` +
      '</div>';
  });
  html += '</div>';
  tagTooltip.innerHTML = html;
  tagTooltip.classList.add('open', 'ac-mode');
  tagTooltip.querySelectorAll('.tag-ac-item').forEach(el => {
    el.addEventListener('mousedown', e => {
      e.preventDefault();
      selectAutocomplete(+el.dataset.idx);
    });
  });
}

function selectAutocomplete(idx) {
  const r = acResults[idx];
  if (!r) return;
  const target = acTarget || promptEdit;
  const info = getActiveTokenInfo(target);
  if (!info) return;
  let newTag = r.tag;
  // Wildcard result: wrap with __name__
  if (r._wc_type === 'wildcard') {
    newTag = '__' + r.tag + '__';
    swapToken(target, info, newTag);
    hideAutocomplete();
    return;
  }
  // 비NAI 모드: () → \(\) 이스케이프 (A1111/ComfyUI 가중치 구문 충돌 방지)
  if (modeSelect.value !== 'NAI') {
    newTag = newTag.replace(/\(/g, '\\(').replace(/\)/g, '\\)');
  }
  // Preserve prefix (artist:, character:) if present in original token
  const rawLower = info.raw.toLowerCase();
  for (const pfx of ['artist:', 'character:']) {
    if (rawLower.startsWith(pfx) && !newTag.toLowerCase().startsWith(pfx)) {
      newTag = pfx + newTag;
      break;
    }
  }
  swapToken(target, info, newTag);
  hideAutocomplete();
  lastLookupTag = newTag;
  if (ws && ws.readyState === WebSocket.OPEN)
    ws.send(JSON.stringify({type: 'tag_lookup', tag: r.tag}));
}

function swapToken(textarea, tokenInfo, newTag) {
  const text = textarea.value;
  const raw = tokenInfo.raw;
  const stripped = tokenInfo.stripped;
  const rawLower = raw.toLowerCase();
  const strippedLower = stripped.toLowerCase();
  const idx = rawLower.indexOf(strippedLower);
  let prefix = '', suffix = '';
  if (idx >= 0) {
    prefix = raw.substring(0, idx);
    suffix = raw.substring(idx + stripped.length);
  }
  const replacement = prefix + newTag + suffix;
  textarea.value = text.substring(0, tokenInfo.start) + replacement + text.substring(tokenInfo.end);
  const newPos = tokenInfo.start + replacement.length;
  textarea.selectionStart = textarea.selectionEnd = newPos;
  textarea.focus();
  if (textarea === promptEdit) onPromptEdit();
  else _fireModuleOninput(textarea);
}

// Trigger the module oninput handler for non-main textareas
function _fireModuleOninput(el) {
  const handler = el.getAttribute('oninput');
  if (handler) new Function('event', handler).call(el, {target: el});
}

function hideAutocomplete() {
  acMode = false;
  acResults = [];
  acSel = -1;
  lastAcQuery = '';
  clearTimeout(acTimer);
  tagTooltip.classList.remove('open', 'ac-mode');
}

// ---- Bind autocomplete/hint to a textarea ----
function bindTagAssist(textarea) {
  let composing = false;
  textarea.addEventListener('compositionstart', () => { composing = true; });
  textarea.addEventListener('compositionend', () => {
    composing = false;
    scheduleAutocomplete();
  });
  textarea.addEventListener('input', () => {
    acTarget = textarea;
    if (!composing) scheduleAutocomplete();
  });
  textarea.addEventListener('click', () => {
    acTarget = textarea;
    if (acMode) hideAutocomplete();
    checkTagHint();
  });
  textarea.addEventListener('keyup', e => {
    if (['ArrowLeft','ArrowRight','Home','End'].includes(e.key)) {
      if (acMode) hideAutocomplete();
      checkTagHint();
    }
  });
  textarea.addEventListener('focus', () => {
    acTarget = textarea;
    if (!acMode) checkTagHint();
  });
  textarea.addEventListener('blur', () => {
    setTimeout(() => {
      if (document.activeElement !== textarea) {
        hideAutocomplete();
        tagTooltip.classList.remove('open', 'ac-mode');
      }
    }, 200);
  });
  textarea.addEventListener('keydown', e => {
    if (!acMode || !acResults.length) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      acSel = Math.min(acSel + 1, acResults.length - 1);
      renderAutocomplete();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      acSel = Math.max(acSel - 1, -1);
      renderAutocomplete();
    } else if ((e.key === 'Enter' || e.key === 'Tab') && acSel >= 0) {
      e.preventDefault();
      e.stopPropagation();
      selectAutocomplete(acSel);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      hideAutocomplete();
      checkTagHint();
    }
  });
}

// Bind main prompt textarea
bindTagAssist(promptEdit);
// Main prompt also syncs to server
promptEdit.addEventListener('compositionend', () => { onPromptEdit(); });
promptEdit.addEventListener('input', () => { onPromptEdit(); });

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
negEdit.addEventListener('input', onPromptEdit);

connect();
