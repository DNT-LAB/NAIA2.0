const PP_OPTIONS = [
  ['remove_author', 'Remove Artist'],
  ['remove_work_title', 'Remove Work Title'],
  ['remove_character_name', 'Remove Character Name'],
  ['remove_character_features', 'Remove Char Features'],
  ['remove_clothes', 'Remove Clothing'],
  ['remove_clothing_event', 'Remove Clothing Events'],
  ['remove_color', 'Remove Color Tags'],
  ['remove_location_and_background_color', 'Remove Location/BG'],
  ['remove_expression', 'Remove Expression'],
  ['remove_pose_action', 'Remove Pose/Action'],
  ['remove_meta_tags', 'Remove Meta Tags'],
  ['remove_object_tags', 'Remove Object Tags'],
  ['remove_noise_tags', 'Remove Low-freq Tags'],
  ['closed_eyes_sync', 'Closed Eyes Sync'],
  ['e621_auto_boost', 'e621 Auto-Boost'],
  ['danbooru_auto_weight', 'Danbooru Auto-Weight'],
  ['tag_implication_compression', 'Tag Implication'],
];

const PP_OPTION_TONES = {
  remove_author: 'pe-tone-yellow',
  remove_work_title: 'pe-tone-yellow',
  remove_character_name: 'pe-tone-yellow',
  closed_eyes_sync: 'pe-tone-pink',
  e621_auto_boost: 'pe-tone-pink',
  danbooru_auto_weight: 'pe-tone-teal',
  tag_implication_compression: 'pe-tone-teal',
};

// Preprocessing Options 각 항목의 700ms 호버 툴팁(간단 기능 설명).
const PP_DESCRIPTIONS = {
  remove_author: '랜덤 프롬프트에서 아티스트 태그를 제거합니다.',
  remove_work_title: '작품명(저작권) 태그를 제거합니다.',
  remove_character_name: '캐릭터 이름 태그를 제거합니다.',
  remove_character_features: '캐릭터 고유 외형 태그(머리·눈 등 식별 특징)를 제거합니다.',
  remove_clothes: '의상 태그를 제거합니다.',
  remove_clothing_event: '의상 관련 상황·이벤트 태그를 제거합니다.',
  remove_color: '색상 태그를 제거합니다.',
  remove_location_and_background_color: '장소·배경 태그를 제거합니다.',
  remove_expression: '표정 태그를 제거합니다.',
  remove_pose_action: '포즈·동작 태그를 제거합니다.',
  remove_meta_tags: '메타 태그(highres, commentary 등)를 제거합니다.',
  remove_object_tags: '사물 태그를 제거합니다.',
  remove_noise_tags: '저빈도(희귀) 노이즈 태그를 제거합니다.',
  closed_eyes_sync: '눈 감은 표정일 때 눈 관련 태그를 정합하게 맞춥니다.',
  e621_auto_boost: 'e621 태그에 자동으로 가중치를 적용합니다.',
  danbooru_auto_weight: 'Danbooru 태그에 빈도 기반 자동 가중치를 적용합니다.',
  tag_implication_compression: '상위 태그가 함의하는 중복 하위 태그를 압축(제거)합니다.',
};
const PE_PREPROCESSING_GUIDE = 'Preprocessing Options — 랜덤(Danbooru) 프롬프트에서 원치 않는 카테고리 태그를 자동으로 걸러내거나, 가중치·태그 정합을 적용해 프롬프트를 다듬습니다.\\n\\n각 항목에 마우스를 올리면 기능 설명이 나옵니다. (WC Solo 모드에서는 적용되지 않습니다)';

const PE_QUICK_PRESET_GUIDE = [
  'Quick Preset — 프롬프트 엔지니어링 설정과 생성 파라미터를 하나로 묶어 저장/불러옵니다. 드롭다운에서 고르면 즉시 적용됩니다.',
  '포함 항목: Prefix·Postfix·Auto-Hide 프롬프트, Preprocessing 옵션, 그리고 생성 파라미터(모델·스텝·CFG·샘플러·해상도 등)와 프롬프트/네거티브.',
  '[Add] 현재 설정을 새 프리셋으로 저장 · [Manage] 이름 변경·삭제·썸네일 관리. 프리셋은 API 모드(NAI/WEBUI/COMFYUI)별로 구분되어 저장됩니다.',
].join('\\n\\n');

const PE_EDITABLE_IDS = ['modPrePrompt', 'modPostPrompt', 'modAutoHide'];

// Ollama Auto Boost — readiness gating. 대상 모델은 백엔드(연결 설정)가 SSOT —
// status 쿼리에 model을 보내지 않아 커스텀 엔드포인트/모델에서도 구성된 모델 기준으로
// 판정된다. "ready" = installed && running && model_installed.
const PE_OLLAMA_POLL_MS = 5000;
const PE_OLLAMA_BOOST_GUIDE = 'Ollama가 준비됐을 때만 켤 수 있음 · 매 생성 직전 프롬프트를 자연어 배경/구도/분위기로 보강 · 저장/프리셋에 기록되지 않음(항상 OFF로 시작)';

// 섹션 헤더 우측 [ⓘ 가이드] 버튼 문구. \n\n 은 단락 구분 (툴팁 엔진이 변환).
const PE_PREFIX_GUIDE = [
  'Prefix Prompt — 랜덤 프롬프트 앞에 결합됩니다. NAI에서는 보통 아티스트 태그를 나열합니다. WEBUI/COMFYUI에서 Anima 계열 모델을 쓴다면 퀄리티 프롬프트도 여기에 포함하세요.',
  '__이름__ — 랜덤: 매번 무작위로 한 줄 선택',
  '__*이름__ — 순차: 생성할 때마다 다음 줄로 순서대로',
  '__$master:slave__ — 종속: master(순차)가 한 바퀴 돌 때마다 slave가 한 칸 전진합니다. 콜론 앞이 master, 뒤가 출력될 slave이며, master는 프롬프트에 __*master__ 형태로 존재해야 합니다.',
].join('\\n\\n');
const PE_POSTFIX_GUIDE = 'Postfix Prompt — 랜덤 프롬프트 뒤에 결합됩니다. NAI에서는 보통 퀄리티 프롬프트를 나열합니다.\\n\\n[추천 설정 적용]으로 들어가는 1.2::3d ::, 1.2::blender (medium) ::, detailed eyes, silky skin, detailed skin texture 처럼 분위기 조절용 프롬프트에도 활용할 수 있습니다. 와일드카드도 사용 가능하며, 문법은 Prefix Prompt 가이드를 참조하세요.';
const PE_AUTOHIDE_GUIDE = [
  'Auto-Hide (Filter) — 랜덤 프롬프트가 Prefix·Postfix와 결합될 때, 패턴에 맞는 태그를 결과에서 제거합니다. (WC Solo 모드에서는 미적용)',
  '텍스트 — 정확히 같은 태그만 제거',
  '__텍스트__ — 텍스트를 포함하는 모든 태그 제거 (부분일치, 가장 넓음)',
  '_텍스트_ — 밑줄을 공백으로 바꾼 " 텍스트 " 구를 포함하는 태그 제거',
  '_텍스트 — 앞에 공백이 오는 " 텍스트"로 매칭 (단어 경계)',
  '텍스트_ — 텍스트를 포함하는 태그 제거 (부분일치)',
  '~텍스트 — 보호: 텍스트를 포함하는 태그는 위 규칙으로도 제거하지 않음 (예외)',
].join('\\n\\n');

function compactPreviewText(text, limit = 420) {
  const normalized = String(text || '').replace(/\s+/g, ' ').trim();
  if (!normalized) return '';
  return normalized.length > limit ? `${normalized.slice(0, Math.max(0, limit - 3))}...` : normalized;
}

function labelForPreprocessingKey(key) {
  return String(key || '')
    .replace(/^remove_/, 'Remove ')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, char => char.toUpperCase());
}

function buildPreprocessingOptions(preprocessing) {
  const knownKeys = new Set(PP_OPTIONS.map(([key]) => key));
  const dynamicOptions = Object.keys(preprocessing || {})
    .filter(key => !knownKeys.has(key))
    .sort()
    .map(key => [key, labelForPreprocessingKey(key)]);
  return [...PP_OPTIONS, ...dynamicOptions];
}

export function createPromptEngineeringPanel({
  document,
  moduleBody,
  escHtml,
  bindTagAssist,
  setOllamaAutoBoost = () => {},
}) {
  // Ollama readiness gating state for the "Ollama Auto Boost" checkbox. We poll
  // /api/ollama/status while the PE panel is mounted and reflect ready/not-ready
  // onto the checkbox (enabled vs disabled) in-place, without a full re-render.
  let ollamaReady = false;
  let ollamaBoostOn = false;          // last-known desired state from module_state
  let ollamaPollTimer = null;
  let ollamaStatusInFlight = false;

  function isBoostCheckboxMounted() {
    const el = document.getElementById('peOllamaBoostCheckbox');
    return !!(el && el.isConnected);
  }

  function applyOllamaBoostGating() {
    const checkbox = document.getElementById('peOllamaBoostCheckbox');
    if (!checkbox) return;
    const hint = document.getElementById('peOllamaBoostHint');
    checkbox.disabled = !ollamaReady;
    // When Ollama is down the toggle can never be armed.
    checkbox.checked = ollamaReady && ollamaBoostOn;
    // Grey out the whole row inline (no style.css dependency) so it reads as
    // disabled and is not clickable while Ollama is not ready.
    checkbox.style.cursor = ollamaReady ? '' : 'not-allowed';
    const item = checkbox.closest('.mod-checkbox-item');
    if (item) {
      item.classList.toggle('mod-checkbox-disabled', !ollamaReady);
      item.style.opacity = ollamaReady ? '' : '0.4';
      item.style.cursor = ollamaReady ? '' : 'not-allowed';
    }
    if (hint) hint.style.display = ollamaReady ? 'none' : '';
  }

  async function pollOllamaStatus() {
    // Panel was closed/unmounted — stop polling to avoid needless fetches.
    if (!isBoostCheckboxMounted()) {
      stopOllamaPolling();
      return;
    }
    if (ollamaStatusInFlight) return;
    ollamaStatusInFlight = true;
    let ready = false;
    try {
      const response = await fetch('/api/ollama/status');
      const data = await response.json().catch(() => null);
      ready = !!(data && data.installed === true && data.running === true && data.model_installed === true);
    } catch (error) {
      // Treat any fetch/parse failure as "not ready" — never crash the panel.
      ready = false;
    } finally {
      ollamaStatusInFlight = false;
    }
    const wasReady = ollamaReady;
    ollamaReady = ready;
    // If it just dropped out of ready while armed, clear the backend session flag
    // once so the boost can't stay armed while Ollama is down.
    if (wasReady && !ready && ollamaBoostOn) {
      ollamaBoostOn = false;
      try { setOllamaAutoBoost(false); } catch (e) {}
    }
    applyOllamaBoostGating();
  }

  function startOllamaPolling() {
    // Kick an immediate check, then poll lightly while the panel is visible.
    void pollOllamaStatus();
    if (ollamaPollTimer) return;
    ollamaPollTimer = setInterval(() => { void pollOllamaStatus(); }, PE_OLLAMA_POLL_MS);
  }

  function stopOllamaPolling() {
    if (ollamaPollTimer) {
      clearInterval(ollamaPollTimer);
      ollamaPollTimer = null;
    }
  }

  function captureFocus() {
    const active = document.activeElement;
    if (!active || !PE_EDITABLE_IDS.includes(active.id)) return null;
    return {
      id: active.id,
      value: active.value,
      selectionStart: active.selectionStart,
      selectionEnd: active.selectionEnd,
      scrollTop: active.scrollTop,
    };
  }

  function restoreFocus(snap) {
    if (!snap) return;
    const el = document.getElementById(snap.id);
    if (!el) return;
    el.value = snap.value;
    el.scrollTop = snap.scrollTop;
    try { el.focus({ preventScroll: true }); } catch (e) { el.focus(); }
    try { el.setSelectionRange(snap.selectionStart, snap.selectionEnd); } catch (e) {}
  }

  function captureTextareaHeights() {
    const heights = {};
    PE_EDITABLE_IDS.forEach(id => {
      const el = document.getElementById(id);
      if (el && el.style.height) heights[id] = el.style.height;
    });
    return heights;
  }

  function restoreTextareaHeights(heights) {
    if (!heights) return;
    Object.entries(heights).forEach(([id, height]) => {
      const el = document.getElementById(id);
      if (el && height) el.style.height = height;
    });
  }

  function render(m) {
    const focusSnap = captureFocus();
    // While the user is actively editing one of the prompt textareas, this
    // render is almost always the echo of their own keystrokes coming back as a
    // module_state broadcast (after the input debounce). Rebuilding innerHTML
    // here replaces the focused textarea node, which dismisses the open
    // autocomplete popup and drops focus mid-word — even though we restore both
    // afterward, the popup is already gone. The local DOM already holds the
    // edited value, so skip the destructive rebuild while a prompt textarea is
    // focused; the next render after blur reflects any real state change.
    if (focusSnap) return;
    const textareaHeights = captureTextareaHeights();
    const summaryMap = new Map();
    (m.preset_summaries || []).forEach(summary => {
      if (summary && summary.name) summaryMap.set(String(summary.name), summary);
    });

    const presetOpts = (m.preset_options || [])
      .map(preset => {
        const summary = summaryMap.get(String(preset));
        const title = summary ? compactPreviewText(summary.pre_prompt_preview, 180) : '';
        const previewAttrs = summary ? [
          `data-preview-name="${escHtml(summary.name || preset)}"`,
          `data-preview-mode="${escHtml(summary.api_mode || '')}"`,
          `data-preview-prefix="${escHtml(compactPreviewText(summary.pre_prompt_preview, 1200))}"`,
          `data-preview-description="${escHtml(compactPreviewText(summary.description, 300))}"`,
          `data-preview-thumbnail="${escHtml(summary.thumbnail_url || '')}"`,
        ].join(' ') : '';
        return `<option value="${escHtml(preset)}"${preset === m.preset ? ' selected' : ''}${title ? ` title="${escHtml(title)}"` : ''} ${previewAttrs}>${escHtml(preset)}</option>`;
      })
      .join('');

    const preprocessing = m.preprocessing || {};
    const preprocessingHtml = buildPreprocessingOptions(preprocessing).map(([key, label]) => {
      const desc = PP_DESCRIPTIONS[key] || '';
      const guideAttr = desc ? ` data-naia-guide="${escHtml(desc)}"` : '';
      return `<label class="mod-checkbox-item ${PP_OPTION_TONES[key] || ''}"${guideAttr}>
      <input type="checkbox" ${preprocessing[key] ? 'checked' : ''} oninput="setPromptEngineeringOption('${key}', this.checked)">
      <span class="mod-checkbox-label">${label}</span>
    </label>`;
    }).join('');

    // Ollama Auto Boost — a SESSION-ONLY toggle rendered separately from the
    // preprocessing grid (it is NOT a preprocessing option). Backend resets it to
    // false on load, so reflect m.ollama_auto_boost as the desired state but only
    // allow it ON when Ollama is ready (gated by the polling status check below).
    ollamaBoostOn = !!m.ollama_auto_boost;
    const boostChecked = ollamaReady && ollamaBoostOn;
    const boostDisabled = ollamaReady ? '' : ' disabled';
    const boostItemStyle = ollamaReady ? '' : ' style="opacity:0.4;cursor:not-allowed"';
    const boostInputStyle = ollamaReady ? '' : ' style="cursor:not-allowed"';
    const ollamaBoostHtml = `
    <label class="mod-checkbox-item pe-tone-teal${ollamaReady ? '' : ' mod-checkbox-disabled'}"${boostItemStyle} data-naia-guide="${escHtml(PE_OLLAMA_BOOST_GUIDE)}">
      <input type="checkbox" id="peOllamaBoostCheckbox" ${boostChecked ? 'checked' : ''}${boostDisabled}${boostInputStyle} oninput="setPromptEngineeringOllamaAutoBoost(this.checked)">
      <span class="mod-checkbox-label">Ollama Auto Boost <span id="peOllamaBoostHint" style="margin-left:6px;color:var(--text-dim)${ollamaReady ? ';display:none' : ''}">(Ollama 실행·모델 준비 시 활성화)</span></span>
    </label>`;

    const presetControlHtml = `
    <div>
      <div class="mod-section-label has-actions"><span>Quick Preset</span><span class="mod-head-actions"><button type="button" class="header-guide-btn" data-naia-guide="${escHtml(PE_QUICK_PRESET_GUIDE)}">ⓘ 가이드</button></span></div>
      <div class="mod-preset-toolbar">
        <select class="mod-select mod-preset-select" id="modPreset" data-preview-kind="prompt-preset" onchange="onPromptPresetChange(this.value)">${presetOpts}</select>
        <button class="mod-btn-secondary mod-btn-compact" onclick="openPePresetAddPanel()">Add</button>
        <button class="mod-btn-secondary mod-btn-compact" onclick="openPePresetManagePanel()">Manage</button>
      </div>
    </div>
  `;

    const advancedHtml = `
    <div>
      <div class="mod-section-label">Tools</div>
      <div class="mod-inline-row">
        <button class="mod-btn-secondary" onclick="openPeE621Panel()">e621 Auto-Boost Settings</button>
        <button class="mod-btn-secondary" onclick="openPeDanbooruPanel()">Danbooru Auto-Weight Settings</button>
        <button class="mod-btn-secondary" onclick="openPeOllamaBoostPanel()">Ollama Boost Settings</button>
      </div>
    </div>
  `;

    moduleBody.innerHTML = `
    ${presetControlHtml}
    <div class="pe-prompt-stack">
      <div class="pe-prompt-field">
        <div class="mod-section-label has-actions"><span>Prefix Prompt</span><span class="mod-head-actions"><button type="button" class="header-guide-btn" data-naia-guide="${escHtml(PE_PREFIX_GUIDE)}">ⓘ 가이드</button></span></div>
        <textarea class="mod-textarea pe-textarea" id="modPrePrompt" placeholder="prefix tags..." oninput="onModTextEdit('prompt_engineering','pre_prompt',this.value)">${escHtml(m.pre_prompt)}</textarea>
      </div>
      <div class="pe-prompt-field">
        <div class="mod-section-label has-actions"><span>Postfix Prompt</span><span class="mod-head-actions"><button type="button" class="header-guide-btn" data-naia-guide="${escHtml(PE_POSTFIX_GUIDE)}">ⓘ 가이드</button></span></div>
        <textarea class="mod-textarea pe-textarea" id="modPostPrompt" placeholder="postfix tags..." oninput="onModTextEdit('prompt_engineering','post_prompt',this.value)">${escHtml(m.post_prompt)}</textarea>
      </div>
      <div class="pe-prompt-field">
        <div class="mod-section-label has-actions"><span>Auto-Hide (Filter)</span><span class="mod-head-actions"><button type="button" class="header-guide-btn" data-naia-guide="${escHtml(PE_AUTOHIDE_GUIDE)}">ⓘ 가이드</button></span></div>
        <textarea class="mod-textarea pe-textarea" id="modAutoHide" placeholder="tags to filter out..." oninput="onModTextEdit('prompt_engineering','auto_hide',this.value)">${escHtml(m.auto_hide)}</textarea>
      </div>
    </div>
    <div>
      <div class="mod-section-label has-actions"><span>Preprocessing Options</span><span class="mod-head-actions"><button type="button" class="header-action-btn" onclick="openPeDebugPanel()">Debug Snapshot</button><button type="button" class="header-guide-btn" data-naia-guide="${escHtml(PE_PREPROCESSING_GUIDE)}">ⓘ 가이드</button></span></div>
      <!-- Ollama Auto Boost를 그리드 마지막 셀로 — Tag Implication(좌) 우측 칸을 채워 균일하게. -->
      <div class="mod-checkbox-grid">${preprocessingHtml}${ollamaBoostHtml}</div>
    </div>
    ${advancedHtml}
  `;

    PE_EDITABLE_IDS.forEach(id => {
      const el = document.getElementById(id);
      if (el) bindTagAssist(el);
    });
    restoreTextareaHeights(textareaHeights);
    restoreFocus(focusSnap);
    // Reflect last-known readiness immediately on the freshly rendered checkbox,
    // then (re)start the lightweight status poll while the panel is mounted.
    applyOllamaBoostGating();
    startOllamaPolling();
  }

  return {
    render,
  };
}
