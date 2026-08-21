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

// 프리셋 검색창도 여기 넣는다. render() 는 이 목록 중 하나가 포커스를 쥐고 있으면
// 통째로 다시 그리기를 건너뛴다 — 안 넣으면 한 글자 칠 때마다 오는 module_state
// 브로드캐스트가 입력창을 새 노드로 갈아 끼워 포커스가 날아간다.
const PE_EDITABLE_IDS = ['modPrePrompt', 'modPostPrompt', 'modAutoHide', 'modPresetSearch'];
// 그중 태그 자동완성을 붙일 칸(검색창은 제외).
const PE_TAG_ASSIST_IDS = ['modPrePrompt', 'modPostPrompt', 'modAutoHide'];

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
  '__텍스트__ 또는 _텍스트_ — 텍스트를 포함하는 모든 태그 제거 (부분일치, 밑줄 개수 무관)',
  '_텍스트 또는 __텍스트 — 앞에 공백이 오는 " 텍스트"로 매칭 (단어 경계)',
  '텍스트_ — 텍스트를 포함하는 태그 제거 (부분일치)',
  '중간 밑줄은 공백으로 취급 — blue_eyes 는 "blue eyes"와 같음 (Danbooru 표기 복붙 호환)',
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

  // ---- Quick Preset 검색 ----
  // 현재 API 모드의 프리셋 중, 입력한 문자열을 **본문에 포함하는** 것만 남긴다.
  // 쉼표로 여러 개를 주면 **모두** 포함해야 남는다(좁혀 가는 필터). 매칭은 단순
  // 부분 문자열(대소문자 무시) — 토큰 경계나 와일드카드는 보지 않는다.
  let presetQuery = '';
  let presetHaystack = new Map();     // 프리셋 이름 -> 검색 대상 문자열(소문자)
  let presetAllOptions = null;        // 필터 전 원본 <option> 들

  function presetTerms(raw) {
    return String(raw || '').split(',').map(t => t.trim().toLowerCase()).filter(Boolean);
  }

  /** `<option>` 을 **지웠다 되돌린다.** `hidden` 은 듣지 않는다 — 네이티브 select 는
   *  커스텀 위젯으로 대체되는데(customSelects.mjs) 그 메뉴는 `select.options` 를
   *  통째로 훑고 `hidden` 을 보지 않는다. 대신 select 를 MutationObserver 로
   *  지켜보고 있어서, 자식을 갈아 끼우면 메뉴가 알아서 다시 그려진다. */
  function applyPresetFilter() {
    const select = document.getElementById('modPreset');
    if (!select) return;
    if (!presetAllOptions) presetAllOptions = Array.from(select.options);
    const terms = presetTerms(presetQuery);
    const current = select.value;
    // 갈래 필터(ALL/NAI5/NAI4.5/ETC)는 검색과 **AND** 로 걸린다 — 좁혀 가는 도구
    // 둘이니 서로를 무르면 안 된다.
    const group = String(select.dataset.optionFilterActive || 'all');
    const inGroup = opt => group === 'all'
      || String(opt.dataset.modelGroup || 'etc') === group;
    const hits = opt => {
      if (!terms.length) return false;
      const hay = presetHaystack.get(opt.value);
      return hay !== undefined && terms.every(t => hay.includes(t));
    };
    const keep = presetAllOptions.filter(opt => {
      const hit = hits(opt);
      // 실제로 걸린 것에만 표시를 남긴다 — 미리보기가 **매치**를 짚게 하려는 것이다.
      // 이게 없으면 '늘 남기는 현재 프리셋' 이 목록 앞에 있을 때 그쪽이 열려,
      // 검색해 놓고 검색어가 안 칠해진 화면을 본다(Codex 리뷰 2026-08-08).
      if (hit) opt.dataset.searchHit = '1'; else delete opt.dataset.searchHit;
      // 지금 고른 프리셋은 **항상 남긴다.** 지워 버리면 select 의 값이 조용히
      // 다른 프리셋으로 바뀌고, 검색만 했는데 적용된 프리셋이 갈린다.
      if (opt.value === current) return true;
      if (!inGroup(opt)) return false;
      if (!terms.length) return true;
      return hit;
    });
    // **몇 개 걸렸는지 적는다.** 접힌 select 는 검색을 해도 계속 고른 프리셋을
    // 보여주므로(늘 남기는 규칙), 드롭다운을 열기 전에는 걸렸는지조차 알 수 없다 —
    // 아무 일도 안 일어난 것처럼 보인다(사용자 지적 2026-08-08).
    // 세는 것은 **실제로 걸린 것**이다: 늘 남기는 현재 프리셋은 안 맞으면 빼고 센다.
    // 갈래 필터를 먹인 뒤를 모수로 센다 — ALL 이 아닌데 전체 개수를 보이면
    // "걸렀는데 숫자가 안 준다" 로 보인다.
    const pool = presetAllOptions.filter(inGroup);
    const matched = terms.length
      ? pool.filter(opt => {
          const hay = presetHaystack.get(opt.value);
          return hay !== undefined && terms.every(t => hay.includes(t));
        }).length
      : pool.length;
    const badge = document.getElementById('modPresetCount');
    if (badge) {
      const narrowed = terms.length > 0 || group !== 'all';
      badge.textContent = narrowed ? `${matched} / ${presetAllOptions.length}` : '';
      badge.classList.toggle('is-none', narrowed && matched === 0);
    }

    // 미리보기에서 형광펜으로 칠할 말들. 줄바꿈으로 넘긴다(검색어에 쉼표가
    // 들어갈 수 있어 쉼표로는 못 가른다).
    select.dataset.previewHighlight = terms.join('\n');

    const same = keep.length === select.options.length
      && keep.every((opt, i) => select.options[i] === opt);
    if (!same) {
      select.replaceChildren(...keep);
      if (select.value !== current) select.value = current;
    }

    // **검색하면 목록이 저절로 열린다.** 따로 눌러야 결과가 보이면 걸렀는지조차
    // 알 수 없다(사용자 지정 2026-08-08). 여는 쪽은 포커스를 옮기지 않으므로
    // 검색창에서 계속 칠 수 있다. 검색어를 지우면 닫는다.
    select.dispatchEvent(new CustomEvent(
      terms.length ? 'naia:select-open' : 'naia:select-close'));
  }

  // 갈래 필터의 마지막 선택. 세션이 아니라 **다음 실행까지** 기억한다(사용자 지정).
  const PRESET_GROUP_KEY = 'naia.pe.presetGroup';

  function readPresetGroup() {
    try { return String(localStorage.getItem(PRESET_GROUP_KEY) || 'all'); }
    catch (_) { return 'all'; }        // 프라이빗 모드 등 - 기본값으로 조용히 산다
  }

  function writePresetGroup(key) {
    try { localStorage.setItem(PRESET_GROUP_KEY, String(key || 'all')); } catch (_) {}
  }

  function bindPresetGroupFilter() {
    const select = document.getElementById('modPreset');
    if (!select || select.dataset.groupBound === '1') return;
    select.dataset.groupBound = '1';
    // customSelects 가 목록 맨 위 바에서 쏜다. 무엇을 거를지는 여기서 정한다.
    select.addEventListener('naia:option-filter', event => {
      writePresetGroup(event.detail?.key);
      applyPresetFilter();
    });
  }

  function bindPresetSearch() {
    const input = document.getElementById('modPresetSearch');
    if (!input || input.dataset.bound === '1') return;
    input.dataset.bound = '1';
    input.addEventListener('input', () => {
      presetQuery = input.value;
      applyPresetFilter();
    });
    // 검색어를 지우는 것은 '전체로 되돌리기'다 — search 입력의 ✕ 도 여기로 온다.
    input.addEventListener('search', () => {
      presetQuery = input.value;
      applyPresetFilter();
    });
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

    // 프리셋 검색 색인. 현재 API 모드의 프리셋만 담긴다 — `preset_options` 자체가
    // `store.preset_options()`(현재 모드) 이라 여기서 따로 거를 것이 없다.
    presetHaystack = new Map();
    // 이 렌더가 select 를 새로 만든다 — 원본 option 캐시는 여기서 버린다.
    // 안 버리면 옛 노드를 붙잡고 있어, 프리셋을 추가·삭제해도 목록이 낡은 채로 남는다.
    presetAllOptions = null;
    (m.preset_summaries || []).forEach(s => {
      if (!s || !s.name) return;
      // auto-hide 는 **넣지 않는다.** 대개 프리셋끼리 같은 값을 공유해서, 넣으면
      // 거기 있는 태그로 검색할 때 전부가 걸려 필터가 무뎌진다(사용자 지적).
      presetHaystack.set(String(s.name), [
        s.name, s.description, s.pre_prompt_preview, s.post_prompt_preview,
      ].map(v => String(v || '')).join('\n').toLowerCase());
    });

    const presetOpts = (m.preset_options || [])
      .map(preset => {
        const summary = summaryMap.get(String(preset));
        const title = summary ? compactPreviewText(summary.pre_prompt_preview, 180) : '';
        const previewAttrs = summary ? [
          `data-preview-name="${escHtml(summary.name || preset)}"`,
          `data-preview-mode="${escHtml(summary.api_mode || '')}"`,
          `data-preview-prefix="${escHtml(compactPreviewText(summary.pre_prompt_preview, 1200))}"`,
          // Postfix 도 실어 준다 — 검색이 postfix 까지 훑으므로, 무엇이 걸렸는지
          // 미리보기에서 확인할 수 있어야 한다(사용자 지적 2026-08-08).
          `data-preview-postfix="${escHtml(compactPreviewText(summary.post_prompt_preview, 1200))}"`,
          `data-preview-description="${escHtml(compactPreviewText(summary.description, 300))}"`,
          `data-preview-thumbnail="${escHtml(summary.thumbnail_url || '')}"`,
        ].join(' ') : '';
        // 모델 배지(`[NAI4.5C]`)와 갈래. customSelects 가 이 둘로 라벨을 색칠하고,
        // 아래 필터가 `modelGroup` 으로 목록을 좁힌다. 옵션 **텍스트에는 넣지 않는다** -
        // 넣으면 프리셋 검색(본문 부분 문자열)이 배지까지 훑어 무뎌진다.
        const badgeAttrs = summary && summary.model_label ? [
          `data-model-label="${escHtml(summary.model_label)}"`,
          `data-model-family="${escHtml(summary.model_family || '')}"`,
        ].join(' ') : '';
        const groupAttr = summary ? ` data-model-group="${escHtml(summary.model_group || 'etc')}"` : '';
        return `<option value="${escHtml(preset)}"${preset === m.preset ? ' selected' : ''}${title ? ` title="${escHtml(title)}"` : ''}${groupAttr} ${previewAttrs} ${badgeAttrs}>${escHtml(preset)}</option>`;
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

    // 갈래 필터 바는 **NAI 모드에서만** 뜬다 — 백엔드가 그때만 목록을 준다.
    // 마지막 선택은 기억한다(사용자 지정 2026-08-21). 저장된 갈래가 이번 목록에
    // 없으면(모드가 바뀌었다든지) 조용히 ALL 로 되돌린다 - 안 그러면 아무것도
    // 안 걸리는 필터가 켜진 채 "프리셋이 사라졌다" 가 된다.
    const filterGroups = Array.isArray(m.preset_filter_groups) ? m.preset_filter_groups : [];
    let activeGroup = readPresetGroup();
    if (!filterGroups.some(g => g && g.key === activeGroup)) activeGroup = 'all';
    const presetFilterAttrs = filterGroups.length >= 2
      ? ` data-option-filters="${escHtml(JSON.stringify(filterGroups))}"`
        + ` data-option-filter-active="${escHtml(activeGroup)}"`
      : '';

    const presetControlHtml = `
    <div>
      <div class="mod-section-label has-actions"><span>Quick Preset<input type="search" class="pe-preset-search" id="modPresetSearch" placeholder="검색 — 쉼표로 여러 개" value="${escHtml(presetQuery)}" autocomplete="off" spellcheck="false"><span class="pe-preset-count" id="modPresetCount"></span></span><span class="mod-head-actions"><button type="button" class="header-guide-btn" data-naia-guide="${escHtml(PE_QUICK_PRESET_GUIDE)}">ⓘ 가이드</button></span></div>
      <div class="mod-preset-toolbar">
        <select class="mod-select mod-preset-select" id="modPreset" data-preview-kind="prompt-preset"${presetFilterAttrs} onchange="onPromptPresetChange(this.value)">${presetOpts}</select>
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
      <div class="mod-section-label has-actions"><span>Preprocessing Options</span><span class="mod-head-actions"><button type="button" class="header-action-btn" onclick="openPeDebugPanel()">Setting &amp; Preview</button><button type="button" class="header-guide-btn" data-naia-guide="${escHtml(PE_PREPROCESSING_GUIDE)}">ⓘ 가이드</button></span></div>
      <!-- Ollama Auto Boost를 그리드 마지막 셀로 — Tag Implication(좌) 우측 칸을 채워 균일하게. -->
      <div class="mod-checkbox-grid">${preprocessingHtml}${ollamaBoostHtml}</div>
    </div>
    ${advancedHtml}
  `;

    // 태그 자동완성은 **프롬프트 칸에만** 건다. 프리셋 검색창은 태그를 치는 자리가
    // 아니라 프리셋 본문을 훑는 자리라, 붙이면 엉뚱한 태그 목록이 뜬다.
    PE_TAG_ASSIST_IDS.forEach(id => {
      const el = document.getElementById(id);
      if (el) bindTagAssist(el);
    });
    bindPresetSearch();
    bindPresetGroupFilter();
    applyPresetFilter();
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
