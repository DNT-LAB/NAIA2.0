// 캐릭터 생성 벤치 — 새 캐릭터를 만드는 오버레이(구 "표준 레퍼런스 생성" 인라인 폼 대체).
//
// 바리에이션 벤치와 상태 머신을 공유하지 않는다(그쪽은 라이브 검증 중이라 이관하지
// 않는다 — Codex 계획 리뷰). 공유하는 것은 benchCandidates.mjs의 순수 함수뿐이다.
//
// 수명 계약(Codex 2라운드 §1): 탭 컨트롤러당 싱글턴. 닫기는 hidden 처리만 하고
// 후보·requestId를 보존한다. 최상위 컨트롤러가 성공/오류를 두 벤치에 fan-out하고,
// 각 벤치는 자기 requestId의 것만 처리한다.

import {
  appendBenchCandidateBatch,
  applyRandomCharacterSlot,
  benchModeBadge,
  findBenchRequestCandidate,
} from './benchCandidates.mjs?v=20260717-benchcand4';
import {createMaskEngine} from './maskCanvas.mjs?v=20260717-mask1';

const GENERATE_MAX = 8;

export function createCharacterCreationBench({
  document,
  window: windowRef = globalThis,
  navigator: navigatorRef = globalThis.navigator,
  api,
  postJson,
  fetchFn = (...args) => globalThis.fetch(...args),
  escHtml,
  escAttr,
  showToast,
  bindTagAssist = () => {},
  isNai,
  newRequestId,
  getCharacterState = null,
  getCharacterReferenceState = null,
  getSelectedDetail = null,
  onSaved = () => {},
}) {
  const navigator = navigatorRef;
  const API = {
    defaults: '/api/character-asset/bench/defaults',
    generate: '/api/character-asset/generate',
    save: '/api/character-asset/save',
    // 후보 이미지는 리스 인지 라우트로 - 히스토리 퇴출 후에도 저장 가능한 동안
    // 미리보기가 유지된다(저장은 되는데 그림은 깨지는 모순 방지).
    historyImage: id => `/api/character-asset/candidate/image?history_id=${encodeURIComponent(id)}`,
    referenceUpload: '/api/character-asset/reference/upload',
    referenceStorage: '/api/character-asset/reference/storage',
    candidatePin: '/api/character-asset/candidate/pin',
    candidateUnpin: '/api/character-asset/candidate/unpin',
    pinImage: id => `/api/character-asset/candidate/pin-image?pin_id=${encodeURIComponent(id)}`,
    randomCharacter: (parts, gender) =>
      `/api/character-asset/random-character?parts=${encodeURIComponent(parts.join(','))}`
      + `&gender=${encodeURIComponent(gender)}`,
  };
  const REFERENCE_TYPES = [
    ['character&style', 'Char & Style'],
    ['character', 'Character'],
  ];

  let layer = null;
  let open = false;
  let prompt = '';
  let uc = '';
  let count = 1;
  // 생성 방식(base mode)은 폼 토글이 아니라 플로팅 도구가 결정한다:
  // 인페인트 핀이 살아 있으면 inpaint, 아니면 scaffold. 레퍼런스는 모드가
  // 아니라 얹는 레이어다(2축: base x reference).
  let referenceOpen = false;
  // 벤치 소유 레퍼런스 - 세션 CR 프레임(character_reference_frames)과 무관하다.
  // {file_hash, file_name, thumbnail, reference_type, strength, fidelity, enabled}
  let references = [];
  let referenceStorage = [];
  let referenceStorageOpen = false;
  let referenceBusy = false;
  // 인페인트: 서버 핀(pin_candidate)이 원본 PNG를 붙잡는다. 핀은 포커스와
  // 별개로 사용자가 [핀 해제]할 때까지 고정(사용자 계약). 마스크 편집기는
  // 벤치 render()의 innerHTML 교체에서 살아남아야 하므로 별도 sibling DOM.
  let inpaintPin = null;        // {pinId, historyId, width, height}
  let maskLayer = null;         // persistent sibling - 벤치 재렌더와 무관
  let maskEngine = null;        // createMaskEngine 인스턴스(핀 당 1개)
  let maskEditorOpen = false;
  let maskBusy = false;
  let maskBrush = 48;
  // 랜덤 슬롯: 슬롯이 직접 넣어준 태그를 기억한다. 굴리지 않은 카테고리의 태그는
  // 그대로 유지되고, 굴린 카테고리만 제거 후 재삽입된다(사용자 계약).
  let randomGender = 'girl';
  let randomUseAppearance = true;
  let randomUseOutfit = true;
  let randomBusy = false;
  let randomOwned = {gender: '', appearance: [], outfit: []};
  let promptSource = 'current';          // 'current' | 'preset' | 'custom'
  let promptPreset = '';
  let profiles = {primary: null, current: null, presets: []};
  // CUSTOM: 선택 프로파일을 시드로 PREFIX/POSTFIX/NEGATIVE/CFG/샘플러 등을 일시
  // 수정(영구 저장 없음 - 영구 변경은 원본 이미지 교체). 생성 벤치는 추가
  // Negative 입력이 없으므로 NEGATIVE도 여기서 편집한다(사용자 지시).
  let customProfile = null;
  let customDraft = null;
  let customOpen = false;
  let profilesLoaded = false;
  let requestId = '';
  let candidates = [];
  let selected = -1;
  let busy = false;
  let renderEpoch = 0;
  let deferredRender = false;
  let deferredTarget = null;
  let deferredPolling = false;

  function selectedCandidate() {
    return candidates.find(candidate => candidate.index === selected) || null;
  }

  function selectedProfile() {
    if (promptSource === 'custom') return customProfile;
    if (promptSource === 'preset') {
      return profiles.presets.find(profile => profile.name === promptPreset) || null;
    }
    return profiles.current;
  }

  const NAI_SAMPLER_OPTIONS = ['k_euler_ancestral', 'k_euler', 'k_dpmpp_2m', 'ddim'];
  const NAI_SCHEDULER_OPTIONS = ['karras', 'native', 'exponential', 'polyexponential'];

  function openCustomPanel() {
    const seed = customProfile
      || (promptSource === 'custom' ? profiles.current : selectedProfile())
      || profiles.current
      || {};
    const params = seed.params || {};
    customDraft = {
      // 프롬프트 3슬롯은 기본 접힘 - 패널 공간 확보(사용자 지시).
      fold: {prefix: false, postfix: false, negative: false},
      prefix: String(seed.prefix || ''),
      postfix: String(seed.postfix || ''),
      negative_prompt: String(seed.negative_prompt || ''),
      cr_capable: typeof seed.cr_capable === 'boolean' ? seed.cr_capable : null,
      model: String(params.model || ''),
      cfg_scale: params.cfg_scale ?? '',
      cfg_rescale: params.cfg_rescale ?? '',
      sampler: String(params.sampler || ''),
      scheduler: String(params.scheduler || ''),
      varplus: !!params['VAR+'],
    };
    customOpen = true;
    referenceOpen = false; // 같은 영역 오버레이 - 동시 노출 방지
    render();
  }

  function applyCustom() {
    const draft = customDraft;
    if (!draft) return;
    const params = {};
    if (draft.model) params.model = draft.model;
    if (draft.sampler) params.sampler = draft.sampler;
    if (draft.scheduler) params.scheduler = draft.scheduler;
    for (const [key, low, high, label] of [['cfg_scale', 0, 30, 'CFG Scale'], ['cfg_rescale', 0, 1, 'CFG Rescale']]) {
      const raw = draft[key];
      if (raw === '' || raw === null || raw === undefined) continue;
      const value = Number(raw);
      if (!Number.isFinite(value) || value < low || value > high) {
        showToast(`${label} 값이 올바르지 않습니다 (${low}~${high})`, 'error');
        return;
      }
      params[key] = value;
    }
    // False도 명시 전달 - 생략하면 라이브 세션 VAR+가 상속돼 체크 해제가 무력(Codex).
    params['VAR+'] = !!draft.varplus;
    customProfile = {
      prefix: draft.prefix.trim(),
      postfix: draft.postfix.trim(),
      negative_prompt: draft.negative_prompt.trim(),
      cr_capable: draft.cr_capable,
      params,
    };
    promptSource = 'custom';
    customOpen = false;
    showToast('CUSTOM 프로파일 적용됨 - 이 벤치의 생성에만 일시적으로 유효합니다', 'success');
    render();
  }

  function renderCustomPromptSlot(fieldPrefix, slot, label, draft) {
    // 접힘 상태에서도 값은 draft에 살아 있다 - textarea를 DOM에서 떼어 공간 확보.
    const value = slot === 'negative' ? draft.negative_prompt : draft[slot];
    const open = !!draft.fold?.[slot];
    const items = String(value || '').split(',').map(part => part.trim()).filter(Boolean).length;
    return `
      <button class="char-bench-custom-fold ${open ? 'open' : ''}"
        data-action="create-custom-fold" data-slot="${slot}">
        <span>${open ? '&#9662;' : '&#9656;'} ${label}</span>
        <span class="char-bench-custom-fold-count">${items ? `${items} 항목` : '비어 있음'}</span>
      </button>
      ${open ? `
        <textarea class="mod-textarea ${slot === 'negative' ? 'mod-uc char-bench-custom-ta-sm' : 'char-bench-custom-ta'}"
          data-field="${fieldPrefix}-${slot}">${escHtml(value || '')}</textarea>
      ` : ''}
    `;
  }

  function renderCustomPanel() {
    if (!customOpen || !customDraft) return '';
    const draft = customDraft;
    const samplerOptions = [...new Set([draft.sampler, ...NAI_SAMPLER_OPTIONS])].filter(Boolean);
    const schedulerOptions = [...new Set([draft.scheduler, ...NAI_SCHEDULER_OPTIONS])].filter(Boolean);
    const selectOptions = (options, value) => ['', ...options].map(option => `
      <option value="${escAttr(option)}" ${option === value ? 'selected' : ''}>${option ? escHtml(option) : '(세션 값 상속)'}</option>
    `).join('');
    return `
      <div class="char-bench-custom-panel">
        <div class="char-bench-float-panel-head">CUSTOM - 세부 프리셋 설정
          <button class="module-popup-icon-btn" data-action="create-custom-close" aria-label="닫기">x</button></div>
        ${renderCustomPromptSlot('create-custom', 'prefix', 'PREFIX (pre prompt)', draft)}
        ${renderCustomPromptSlot('create-custom', 'postfix', 'POSTFIX (post prompt)', draft)}
        ${renderCustomPromptSlot('create-custom', 'negative', 'NEGATIVE', draft)}
        <div class="char-bench-custom-grid">
          <label>CFG Scale
            <input type="number" step="0.1" min="0" max="30" placeholder="상속"
              value="${escAttr(String(draft.cfg_scale ?? ''))}" data-field="create-custom-cfg"></label>
          <label>CFG Rescale
            <input type="number" step="0.05" min="0" max="1" placeholder="상속"
              value="${escAttr(String(draft.cfg_rescale ?? ''))}" data-field="create-custom-rescale"></label>
          <label>Sampler
            <select class="mod-select-sm" data-field="create-custom-sampler">${selectOptions(samplerOptions, draft.sampler)}</select></label>
          <label>Scheduler
            <select class="mod-select-sm" data-field="create-custom-scheduler">${selectOptions(schedulerOptions, draft.scheduler)}</select></label>
          <label class="mod-checkbox-item char-bench-custom-varplus">
            <input type="checkbox" ${draft.varplus ? 'checked' : ''} data-field="create-custom-varplus">
            <span class="mod-checkbox-label">VAR+ (Variety)</span></label>
        </div>
        <div class="char-bench-custom-model">Model: ${escHtml(draft.model || '(라이브 모델 상속)')} <span>- 출력 전용</span></div>
        <div class="char-bench-custom-hint">빈 값은 세션 값을 상속합니다. 적용은 일시적이며 영구 변경은 원본 이미지를 교체해야 합니다.</div>
        <div class="char-bench-custom-actions">
          <button class="mod-btn-sm mod-btn-encode" data-action="create-custom-apply">CUSTOM에 적용</button>
          ${customProfile ? '<button class="mod-btn-sm" data-action="create-custom-reset">CUSTOM 해제</button>' : ''}
        </div>
      </div>
    `;
  }

  function activeReferences() {
    return references.filter(reference => reference.enabled);
  }

  function isNaid45() {
    // capability는 CR 모듈 상태 캐시에서 읽는다(모듈 팝업을 열지 않아도 캐시된다).
    // 단 생성 가능 여부의 최종 권위는 백엔드의 effective-model 게이트다.
    const state = typeof getCharacterReferenceState === 'function' ? getCharacterReferenceState() : null;
    return state ? state.is_naid45 !== false : true;
  }

  function crCapable() {
    // effective model 기준(Codex RC): 선택한 프로파일이 model을 덮어쓰면
    // (PRESET params.model) 그 판정이 라이브 모델보다 우선한다.
    const profile = selectedProfile();
    if (profile && typeof profile.cr_capable === 'boolean') return profile.cr_capable;
    return isNaid45();
  }

  // ------------------------------------------------------------ 재렌더 보류
  function renderBlocker() {
    const focused = document.activeElement;
    if (
      focused
      && layer?.contains(focused)
      && focused.matches?.([
        '.char-bench-form textarea[data-field]',
        // CUSTOM 패널(결과 영역 오버레이) 입력도 재렌더로 파기되면 안 된다.
        '.char-bench-custom-panel textarea[data-field]',
        '.char-bench-custom-panel input[data-field]',
      ].join(', '))
    ) {
      return focused;
    }
    // 열린 custom select를 재렌더로 파기하면 플로팅 미리보기가 강제로 닫힌다.
    if (layer?.querySelector('.custom-select.is-open')) return 'select-open';
    return null;
  }

  function flushDeferredRender() {
    const scheduledEpoch = renderEpoch;
    deferredTarget = null;
    globalThis.setTimeout(() => {
      if (!deferredRender || renderEpoch !== scheduledEpoch) return;
      renderPreservingFocus();
    }, 0);
  }

  function scheduleDeferredRecheck() {
    if (deferredPolling) return;
    deferredPolling = true;
    const scheduledEpoch = renderEpoch;
    globalThis.setTimeout(() => {
      deferredPolling = false;
      if (!deferredRender || renderEpoch !== scheduledEpoch) return;
      renderPreservingFocus();
    }, 400);
  }

  function renderPreservingFocus() {
    const blocker = renderBlocker();
    if (!blocker) {
      render();
      return;
    }
    deferredRender = true;
    if (blocker === 'select-open') {
      scheduleDeferredRecheck();
      return;
    }
    if (deferredTarget === blocker) return;
    deferredTarget = blocker;
    blocker.addEventListener('blur', flushDeferredRender, {once: true});
  }

  // ------------------------------------------------------------------ layer
  function ensureLayer() {
    if (layer) return layer;
    layer = document.createElement('div');
    layer.className = 'char-bench-layer';
    document.body.append(layer);
    layer.addEventListener('click', event => {
      const button = event.target.closest('[data-action]');
      if (!button || button.disabled) return;
      const action = button.dataset.action;
      if (action === 'create-close') close();
      else if (action === 'create-open-reference') {
        referenceOpen = !referenceOpen;
        referenceStorageOpen = false;
        customOpen = false; // 같은 영역 오버레이 - 동시 노출 방지
        render();
      }
      else if (action === 'create-custom-open') openCustomPanel();
      else if (action === 'create-custom-close') {
        customOpen = false;
        render();
      }
      else if (action === 'create-custom-apply') applyCustom();
      else if (action === 'create-custom-fold') {
        if (customDraft) {
          const slot = String(button.dataset.slot || '');
          customDraft.fold[slot] = !customDraft.fold[slot];
          render();
        }
      }
      else if (action === 'create-custom-reset') {
        customProfile = null;
        customOpen = false;
        if (promptSource === 'custom') promptSource = 'current';
        render();
      }
      else if (action === 'create-ref-upload') pickReferenceFile();
      else if (action === 'create-ref-paste') pasteReference();
      else if (action === 'create-ref-storage') openReferenceStorage();
      else if (action === 'create-ref-storage-back') {
        referenceStorageOpen = false;
        render();
      }
      else if (action === 'create-ref-pick') {
        const item = referenceStorage.find(entry => entry.file_hash === button.dataset.hash);
        if (item) addReference(item);
        referenceStorageOpen = false;
        render();
      }
      else if (action === 'create-ref-remove') {
        references.splice(Number(button.dataset.index), 1);
        render();
      }
      else if (action === 'create-open-inpaint') openInpaint();
      else if (action === 'create-pin-unpin') unpinInpaint();
      else if (action === 'create-prompt-source') {
        promptSource = button.dataset.source === 'preset' ? 'preset' : 'current';
        if (promptSource === 'preset' && !promptPreset) {
          promptPreset = String(profiles.presets?.[0]?.name || '');
        }
        customOpen = false;
        render();
      }
      else if (action === 'create-random-gender') {
        randomGender = button.dataset.gender === 'boy' ? 'boy' : 'girl';
        render();
      }
      else if (action === 'create-random-roll') rollRandomCharacter();
      else if (action === 'create-random-generate') rollRandomAndGenerate();
      else if (action === 'create-prefill-c1') prefillFromC1();
      else if (action === 'create-prefill-selected') prefillFromSelected();
      else if (action === 'create-generate') generate();
      else if (action === 'create-save') save({kind: 'new'});
      else if (action === 'create-save-variation') {
        const detail = typeof getSelectedDetail === 'function' ? getSelectedDetail() : null;
        if (detail?.id) save({kind: 'variation', character_id: detail.id});
      }
      else if (action === 'create-discard') discard();
      else if (action === 'create-pick') {
        selected = Number(button.dataset.index);
        render();
      }
    });
    layer.addEventListener('input', event => {
      const field = event.target.closest('[data-field]');
      if (!field) return;
      if (field.dataset.field === 'create-random-appearance') randomUseAppearance = !!field.checked;
      else if (field.dataset.field === 'create-random-outfit') randomUseOutfit = !!field.checked;
      else if (field.dataset.field === 'create-prompt') prompt = field.value;
      else if (field.dataset.field === 'create-uc') uc = field.value;
      else if (field.dataset.field === 'create-count') count = Number(field.value) || 1;
      else if (customDraft && field.dataset.field === 'create-custom-prefix') customDraft.prefix = field.value;
      else if (customDraft && field.dataset.field === 'create-custom-postfix') customDraft.postfix = field.value;
      else if (customDraft && field.dataset.field === 'create-custom-negative') customDraft.negative_prompt = field.value;
      else if (customDraft && field.dataset.field === 'create-custom-cfg') customDraft.cfg_scale = field.value;
      else if (customDraft && field.dataset.field === 'create-custom-rescale') customDraft.cfg_rescale = field.value;
      else if (customDraft && field.dataset.field === 'create-custom-sampler') customDraft.sampler = String(field.value || '');
      else if (customDraft && field.dataset.field === 'create-custom-scheduler') customDraft.scheduler = String(field.value || '');
      else if (customDraft && field.dataset.field === 'create-custom-varplus') customDraft.varplus = !!field.checked;
      else if (field.dataset.field === 'create-preset') promptPreset = String(field.value || '');
      else if (field.dataset.field === 'create-ref-enable') {
        const reference = references[Number(field.dataset.index)];
        if (reference) reference.enabled = !!field.checked;
        // 버튼 배지(활성 개수)를 갱신해야 하므로 재렌더 - 슬라이더와 달리 드래그가 아니다.
        render();
      }
      else if (field.dataset.field === 'create-ref-type') {
        const reference = references[Number(field.dataset.index)];
        if (reference) reference.reference_type = field.value === 'character' ? 'character' : 'character&style';
      }
      else if (field.dataset.field === 'create-ref-strength' || field.dataset.field === 'create-ref-fidelity') {
        // 드래그 중 재렌더하면 슬라이더가 파기된다 - 상태만 즉시 반영하고 값 라벨만 패치.
        const index = Number(field.dataset.index);
        const reference = references[index];
        if (!reference) return;
        const value = Math.max(0, Math.min(1, Number(field.value) / 20));
        const isStrength = field.dataset.field === 'create-ref-strength';
        if (isStrength) reference.strength = value;
        else reference.fidelity = value;
        const label = layer.querySelector(
          `[data-role="create-ref-${isStrength ? 'strength' : 'fidelity'}-${index}"]`,
        );
        if (label) label.textContent = value.toFixed(2);
      }
    });
    return layer;
  }

  async function refreshProfiles() {
    // id 없이 호출한다 - 생성 벤치엔 캐릭터가 없으므로 PRIMARY는 unavailable로
    // 내려오고 CURRENT/PRESET만 쓴다.
    const before = JSON.stringify(profiles) + `|${promptSource}|${promptPreset}`;
    try {
      const defaults = await api(API.defaults);
      const next = defaults?.prompt_profiles;
      if (next && typeof next === 'object') {
        profiles = {
          primary: next.primary || null,
          current: next.current || null,
          presets: Array.isArray(next.presets) ? next.presets : [],
        };
        if (!profilesLoaded) {
          profilesLoaded = true;
          promptPreset = String(profiles.presets[0]?.name || '');
        } else if (promptPreset && !profiles.presets.some(entry => entry.name === promptPreset)) {
          promptPreset = String(profiles.presets[0]?.name || '');
        }
        // 프리셋이 전부 사라졌으면 CURRENT로 폴백(stale 400 방지)
        if (promptSource === 'preset' && !profiles.presets.length) promptSource = 'current';
        if (promptSource === 'preset' && !promptPreset) {
          promptPreset = String(profiles.presets[0]?.name || '');
        }
      }
    } catch (error) {
      console.error('creation bench profile load failed', error);
      return false;
    }
    return (JSON.stringify(profiles) + `|${promptSource}|${promptPreset}`) !== before;
  }

  function openBench() {
    open = true;
    if (layer?.childElementCount) {
      // 유지된 DOM 재노출(입력/후보 복원) 후 프로파일만 백그라운드 재검증.
      layer.hidden = false;
      refreshProfiles().then(changed => {
        if (changed) renderPreservingFocus();
      });
      return;
    }
    render();
    refreshProfiles().then(() => render());
  }

  function close() {
    // DOM을 파기하지 않는다 - 후보와 requestId를 보존해야 진행 중 결과가 미아가
    // 되지 않는다(수명 계약). 마스크 편집기도 함께 숨긴다(핀과 마스크 초안은
    // 유지 - 다시 열면 이어서 편집).
    open = false;
    maskEditorOpen = false;
    syncMaskLayer();
    const pendingSync = deferredRender;
    renderEpoch += 1;
    deferredRender = false;
    deferredTarget = null;
    if (pendingSync) render();
    else if (layer) layer.hidden = true;
  }

  function pickReferenceFile() {
    // 파일 입력은 벤치 레이어 안에서 매번 새로 만든다 - 전역 고정 id(charRefFileInput)를
    // 재사용하면 CR 모듈 패널과 충돌한다.
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/*';
    input.hidden = true;
    input.addEventListener('change', () => {
      const file = input.files?.[0];
      input.remove();
      if (file) uploadReferenceBytes(file);
    }, {once: true});
    layer?.append(input);
    input.click();
  }

  async function pasteReference() {
    try {
      const items = await navigator.clipboard.read();
      for (const item of items) {
        const type = item.types.find(entry => entry.startsWith('image/'));
        if (!type) continue;
        await uploadReferenceBytes(await item.getType(type));
        return;
      }
      showToast('클립보드에 이미지가 없습니다', 'error');
    } catch (error) {
      showToast(`붙여넣기 실패: ${error.message}`, 'error');
    }
  }

  // ---------------------------------------------------------- 랜덤 슬롯
  async function rollRandomAndGenerate() {
    // 슬롯머신: 매 생성 전에 랜덤을 굴린다(횟수 N -> 서로 다른 캐릭터 N명).
    // 굴림이 하나라도 실패하면 생성하지 않는다(옛 프롬프트로 과금되면 안 된다).
    if (randomBusy || busy) return;
    const batchCount = Math.max(1, Math.min(GENERATE_MAX, Number(count) || 1));
    const rolledPrompts = [];
    for (let index = 0; index < batchCount; index += 1) {
      if (!await rollRandomCharacter()) return;
      rolledPrompts.push(prompt);
    }
    await generate(rolledPrompts);
  }

  async function rollRandomCharacter() {
    if (randomBusy) return false;
    const parts = [];
    if (randomUseAppearance) parts.push('appearance');
    if (randomUseOutfit) parts.push('outfit');
    randomBusy = true;
    render();
    let rolled = false;
    try {
      const roll = await api(API.randomCharacter(parts, randomGender));
      // 굴리지 않은 카테고리는 null을 넘겨 기존 태그를 유지시킨다.
      const applied = applyRandomCharacterSlot(prompt, randomOwned, {
        gender: String(roll?.gender || randomGender),
        appearance: randomUseAppearance ? (roll?.appearance || []) : null,
        outfit: randomUseOutfit ? (roll?.outfit || []) : null,
      });
      prompt = applied.prompt;
      randomOwned = applied.owned;
      rolled = true;
    } catch (error) {
      showToast(`랜덤 생성 실패: ${error.message}`, 'error');
    }
    randomBusy = false;
    render();
    return rolled;
  }

  function renderRandomSlot() {
    return `
      <div class="char-bench-random-island">
      <div class="mod-section-label">랜덤 슬롯</div>
      <div class="char-bench-random-row">
        <div class="char-bench-mode-toggle char-bench-gender-toggle">
          ${['girl', 'boy'].map(value => `
            <button class="char-bench-mode-btn ${randomGender === value ? 'active' : ''}"
              data-action="create-random-gender" data-gender="${value}">${value}</button>
          `).join('')}
        </div>
        <label class="mod-checkbox-item">
          <input type="checkbox" ${randomUseAppearance ? 'checked' : ''} data-field="create-random-appearance">
          <span class="mod-checkbox-label">외형</span>
        </label>
        <label class="mod-checkbox-item">
          <input type="checkbox" ${randomUseOutfit ? 'checked' : ''} data-field="create-random-outfit">
          <span class="mod-checkbox-label">의상</span>
        </label>
        <button class="mod-btn-sm mod-btn-encode char-bench-random-btn" data-action="create-random-roll"
          ${randomBusy ? 'disabled' : ''}
          title="선택한 항목만 다시 굴립니다 - 끈 항목의 태그는 그대로 유지됩니다">${randomBusy ? '...' : '랜덤생성'}</button>
      </div>
      </div>
    `;
  }

  // ------------------------------------------------------------- prefill
  function prefillFromC1() {
    const state = typeof getCharacterState === 'function' ? getCharacterState() : null;
    const frames = Array.isArray(state?.characters) ? state.characters : [];
    const c1 = frames[0];
    if (!c1 || !String(c1.prompt || '').trim()) {
      showToast('C1 슬롯이 비어 있거나 캐릭터 모듈 상태를 아직 받지 못했습니다', 'error');
      return;
    }
    prompt = String(c1.prompt || '');
    // 프롬프트가 통째로 갈렸다 - 옛 소유권을 들고 있으면 다음 굴림이
    // 새 프롬프트의 태그를 남의 것으로 지운다(Codex).
    randomOwned = {gender: '', appearance: [], outfit: []};
    uc = String(c1.uc || '');
    render();
  }

  function prefillFromSelected() {
    const detail = typeof getSelectedDetail === 'function' ? getSelectedDetail() : null;
    if (!detail || !detail.recovered) {
      showToast('선택된 에셋에서 캐릭터 프롬프트를 복구할 수 없습니다', 'error');
      return;
    }
    prompt = String(detail.character_prompt || '');
    // 프롬프트가 통째로 갈렸다 - 옛 소유권을 들고 있으면 다음 굴림이
    // 새 프롬프트의 태그를 남의 것으로 지운다(Codex).
    randomOwned = {gender: '', appearance: [], outfit: []};
    uc = String(detail.character_uc || '');
    render();
  }

  // ------------------------------------------------------------- inpaint
  async function openInpaint() {
    if (inpaintPin) {
      // 핀은 유지한 채 편집기만 여닫는다 - 해제는 [핀 해제] 버튼뿐.
      maskEditorOpen = !maskEditorOpen;
      syncMaskLayer();
      render();
      return;
    }
    const current = selectedCandidate();
    if (!current?.historyId || current.status !== 'done' || maskBusy) return;
    maskBusy = true;
    render();
    try {
      const result = await postJson(API.candidatePin, {history_id: current.historyId});
      inpaintPin = {
        pinId: String(result?.pin_id || ''),
        historyId: String(result?.history_id || current.historyId),
        width: Number(result?.width) || 0,
        height: Number(result?.height) || 0,
      };
      maskEditorOpen = true;
      buildMaskLayer();
      showToast('인페인트 대상이 고정되었습니다 - 해제할 때까지 유지됩니다', 'success');
    } catch (error) {
      showToast(`인페인트 핀 실패: ${error.message}`, 'error');
    }
    maskBusy = false;
    render();
  }

  async function unpinInpaint() {
    const pin = inpaintPin;
    if (!pin) return;
    if (pin.pinId) {
      try {
        await postJson(API.candidateUnpin, {pin_id: pin.pinId});
      } catch (error) {
        // 로컬 상태를 먼저 지우면 pin_id를 영영 잃어 서버 핀이 고아가 된다
        // (Codex BLOCK) - 해제 확인 전에는 핀을 유지하고 재시도를 유도한다.
        showToast(`핀 해제 실패 - 다시 시도하세요: ${error.message}`, 'error');
        return;
      }
    }
    inpaintPin = null;
    maskEditorOpen = false;
    maskEngine?.detach();
    maskEngine = null;
    if (maskLayer) {
      // 숨김이 아니라 제거 - 고아 DOM 노드를 남기지 않는다(Codex).
      maskLayer.remove();
      maskLayer = null;
    }
    render();
  }

  function syncMaskLayer() {
    if (maskLayer) maskLayer.hidden = !maskEditorOpen;
  }

  function buildMaskLayer() {
    // 벤치 render()는 host.innerHTML을 통째로 교체한다 - 캔버스/포인터 리스너/
    // 마스크 초안이 파기되지 않도록 편집기는 벤치 밖 sibling DOM에 산다(Codex).
    if (!maskLayer) {
      maskLayer = document.createElement('div');
      maskLayer.className = 'char-bench-mask-layer';
      document.body.append(maskLayer);
      maskLayer.addEventListener('click', event => {
        if (event.target.classList?.contains('char-bench-mask-backdrop')) {
          maskEditorOpen = false;
          syncMaskLayer();
          render();
          return;
        }
        const button = event.target.closest('[data-action]');
        if (!button || button.disabled) return;
        const action = button.dataset.action;
        if (action === 'create-mask-close') {
          maskEditorOpen = false;
          syncMaskLayer();
          render();
        }
        else if (action === 'create-mask-clear') maskEngine?.clear();
        else if (action === 'create-mask-mode') {
          const nextMode = button.dataset.mode === 'erase' ? 'erase' : 'paint';
          maskEngine?.setMode(nextMode);
          maskLayer.querySelectorAll('[data-action="create-mask-mode"]').forEach(entry => {
            entry.classList.toggle('active', entry.dataset.mode === nextMode);
          });
        }
        else if (action === 'create-mask-unpin') unpinInpaint();
      });
      maskLayer.addEventListener('input', event => {
        const field = event.target.closest('[data-field]');
        if (!field) return;
        if (field.dataset.field === 'create-mask-brush') {
          maskBrush = Number(field.value) || maskBrush;
          maskEngine?.setBrushSize(maskBrush);
          const label = maskLayer.querySelector('[data-role="create-mask-brush-value"]');
          if (label) label.textContent = String(maskBrush);
        }
      });
    }
    maskEngine?.detach();
    maskLayer.innerHTML = `
      <div class="char-bench-mask-backdrop"></div>
      <div class="char-bench-mask-dialog" role="dialog" aria-label="인페인트 마스크 편집">
        <header class="char-bench-mask-head">
          <div class="char-bench-title">인페인트 마스크
            <span class="char-asset-detail-id">칠한 영역만 다시 그립니다</span></div>
          <button class="module-popup-icon-btn" data-action="create-mask-close" aria-label="닫기">x</button>
        </header>
        <div class="char-bench-mask-tools">
          <button class="mod-btn-sm active" data-action="create-mask-mode" data-mode="paint">칠하기</button>
          <button class="mod-btn-sm" data-action="create-mask-mode" data-mode="erase">지우기</button>
          <button class="mod-btn-sm" data-action="create-mask-clear">초기화</button>
          <label class="char-bench-mask-brush">브러시
            <input type="range" min="8" max="160" step="8" value="${Number(maskBrush) || 48}" data-field="create-mask-brush">
            <strong data-role="create-mask-brush-value">${Number(maskBrush) || 48}</strong>
          </label>
          <button class="mod-btn-sm mod-btn-danger" data-action="create-mask-unpin"
            title="핀을 해제하면 일반 스캐폴드 생성으로 돌아갑니다">핀 해제</button>
        </div>
        <div class="char-bench-mask-stage">
          <div class="char-bench-mask-frame">
            <img src="${escAttr(API.pinImage(inpaintPin.pinId))}" alt="">
            <canvas class="char-bench-mask-canvas" aria-label="인페인트 마스크"></canvas>
          </div>
        </div>
        <div class="char-bench-mask-foot">마스크를 그린 뒤 [캐릭터 생성]을 누르면 인페인트로 생성됩니다.</div>
      </div>
    `;
    const canvas = maskLayer.querySelector('canvas');
    maskEngine = createMaskEngine({
      canvas,
      width: inpaintPin.width,
      height: inpaintPin.height,
      brushSize: maskBrush,
    });
    maskEngine.attach();
    syncMaskLayer();
  }

  // ------------------------------------------------------------ generation
  async function generate(perCandidatePrompts = null) {
    if (busy) return;
    if (!isNai()) {
      showToast('캐릭터 생성은 NAI 모드 전용입니다', 'error');
      return;
    }
    if (candidates.some(candidate => candidate.status === 'pending')) {
      showToast('진행 중인 생성 배치가 끝난 뒤에 다시 시도하세요', 'warning');
      return;
    }
    const text = prompt.trim();
    if (!text) {
      showToast('Character Prompt를 입력하세요', 'error');
      return;
    }
    // 핀이 살아 있으면 이 생성은 인페인트다(핀 계약: 해제 전까지 고정).
    // 마스크 검증은 후보 append 같은 부수효과 전에 - 빈 마스크로 과금되면 안 된다.
    let inpaintPayload = null;
    if (inpaintPin) {
      const mask = maskEngine?.toDataUrl?.();
      if (!mask || mask.count <= 0) {
        // 마스크를 안 칠한 핀 = 인페인트 의사 없음 - 자동 해제 후 일반 생성(사용자 지시)
        showToast('마스크가 비어 있어 핀을 해제하고 일반 생성합니다', 'warning');
        await unpinInpaint();
        if (inpaintPin) return; // 서버 해제 실패 - 핀 유지 상태로는 진행하지 않는다
      } else {
        inpaintPayload = {source_pin_id: inpaintPin.pinId, mask_png: mask.dataUrl};
      }
    }
    const baseMode = inpaintPin ? 'inpaint' : 'scaffold';
    busy = true;
    const batchRequestId = newRequestId();
    requestId = batchRequestId;
    const batchCount = perCandidatePrompts
      ? perCandidatePrompts.length
      : Math.max(1, Math.min(GENERATE_MAX, Number(count) || 1));
    // 완료 후보는 이 벤치의 작업 이력 - 배치를 append 한다(구 인라인 폼은 배치마다
    // 전멸시켰다). 서버 candidate는 요청마다 0부터라 (requestId, requestCandidate)로 찾는다.
    candidates = appendBenchCandidateBatch(candidates, batchCount, batchRequestId, baseMode);
    // Generate 시점의 레퍼런스를 request-local 스냅샷으로 고정한다 - pending 중
    // 슬라이더/enable을 바꿔도 이미 요청된 후보의 표시가 흔들리면 안 된다(Codex).
    const referenceSnapshot = activeReferences().map(reference => ({
      file_hash: reference.file_hash,
      reference_type: reference.reference_type,
      strength: reference.strength,
      fidelity: reference.fidelity,
    }));
    for (const candidate of candidates) {
      if (candidate.requestId === batchRequestId) candidate.hasReference = referenceSnapshot.length > 0;
    }
    render();
    try {
      const result = await postJson(API.generate, {
        character_prompt: text,
        // 슬롯머신 경로: 후보마다 다른 랜덤 프롬프트(길이 = count).
        ...(perCandidatePrompts ? {character_prompts: perCandidatePrompts} : {}),
        character_uc: uc.trim(),
        generation_mode: baseMode,
        ...(inpaintPayload ? {inpaint: inpaintPayload} : {}),
        references: referenceSnapshot,
        prompt_source: promptSource,
        prompt_preset: promptSource === 'preset' ? promptPreset : '',
        // CUSTOM은 저장소가 없다 - 적용 스냅샷(negative 포함)을 요청에 실어 보낸다.
        ...(promptSource === 'custom' && customProfile ? {custom_profile: customProfile} : {}),
        count: batchCount,
        request_id: batchRequestId,
      });
      const accepted = new Set(result?.accepted || []);
      (result?.rejected || []).forEach(rejection => {
        const candidate = findBenchRequestCandidate(candidates, batchRequestId, rejection?.candidate);
        if (candidate) {
          candidate.status = 'error';
          candidate.message = String(rejection?.message || rejection?.reason || 'rejected');
        }
      });
      if (!accepted.size) showToast('생성 요청이 큐에 들어가지 못했습니다', 'error');
      else showToast(`캐릭터 생성 ${accepted.size}건 요청됨`, 'success');
    } catch (error) {
      candidates.forEach(candidate => {
        if (candidate.requestId === batchRequestId && candidate.status === 'pending') {
          candidate.status = 'error';
          candidate.message = error.message;
        }
      });
      showToast(`생성 요청 실패: ${error.message}`, 'error');
    }
    busy = false;
    render();
  }

  async function save(target) {
    const candidate = selectedCandidate();
    if (!candidate?.historyId || busy) return;
    // 상태 계약은 저장 함수가 강제한다(렌더된 disabled에 의존 금지).
    if (candidate.status !== 'done' || candidate.saved) {
      if (candidate.status === 'expired') showToast('히스토리에서 만료된 후보입니다', 'error');
      return;
    }
    busy = true;
    render();
    try {
      const result = await postJson(API.save, {
        source: {kind: 'history', history_id: candidate.historyId},
        target,
      });
      candidate.saved = true;
      showToast(
        target?.kind === 'variation' ? '바리에이션으로 저장됨' : '새 캐릭터로 저장됨',
        'success',
      );
      onSaved(result?.character_id || '');
    } catch (error) {
      if (/404|not found|evicted/i.test(String(error?.message || ''))) {
        candidate.status = 'expired';
        candidate.message = '히스토리에서 만료됨 - 저장할 수 없습니다';
      }
      showToast(`후보 저장 실패: ${error.message}`, 'error');
    }
    busy = false;
    render();
  }

  function discard() {
    const position = candidates.findIndex(candidate => candidate.index === selected);
    if (position < 0) return;
    candidates.splice(position, 1);
    const nextDone = candidates.find(candidate => candidate.status === 'done');
    selected = nextDone ? nextDone.index : -1;
    render();
  }

  // ------------------------------------------------------- 이벤트 fan-out
  function handleResultMeta(meta) {
    // 자기 requestId의 것만 처리한다(바리에이션 벤치와 동시 pending 가능).
    if (!meta?.character_asset_request) return false;
    if (meta.character_asset_bench) return false;   // 바리에이션 벤치 소유
    const incoming = String(meta.character_asset_request_id || '');
    if (!requestId || incoming !== requestId) return false;
    const candidate = findBenchRequestCandidate(candidates, incoming, meta.character_asset_candidate);
    if (!candidate || candidate.status === 'done') return true;
    candidate.status = 'done';
    candidate.historyId = String(meta.history_id || '');
    // 새 결과가 오면 포커스는 무조건 그쪽으로 옮긴다(사용자 지시). 인페인트 대상
    // 핀(inpaintPin)은 포커스와 별개라 여기서 건드리지 않는다.
    selected = candidate.index;
    renderPreservingFocus();
    return true;
  }

  function handleGenerationError(message) {
    if (!message || typeof message !== 'object') return false;
    const incoming = String(message.requestId || '');
    if (!requestId || incoming !== requestId) return false;
    const candidate = findBenchRequestCandidate(candidates, incoming, message.candidate);
    if (!candidate || candidate.status === 'done') return true;
    candidate.status = 'error';
    candidate.message = String(message.message || 'generation failed');
    renderPreservingFocus();
    return true;
  }

  function handleHistoryRemoved(message) {
    // 리스가 후보를 붙잡고 있으므로 퇴출 통지로 만료시키지 않는다 - 실제 404만이
    // 만료의 근거다(save()가 확정한다).
    void message;
  }

  // ---------------------------------------------------------------- render
  // -------------------------------------------------- 캐릭터 레퍼런스 패널
  async function uploadReferenceBytes(blob) {
    if (!blob) return;
    referenceBusy = true;
    render();
    try {
      const response = await fetchFn(API.referenceUpload, {method: 'POST', body: blob});
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data?.ok === false) throw new Error(data?.error || `HTTP ${response.status}`);
      addReference(data);
      showToast('레퍼런스를 추가했습니다', 'success');
    } catch (error) {
      showToast(`레퍼런스 업로드 실패: ${error.message}`, 'error');
    }
    referenceBusy = false;
    render();
  }

  function addReference(entry) {
    const fileHash = String(entry?.file_hash || '');
    if (!fileHash) return;
    const existing = references.find(reference => reference.file_hash === fileHash);
    if (existing) {
      existing.enabled = true;
      return;
    }
    references.push({
      file_hash: fileHash,
      file_name: String(entry.file_name || ''),
      thumbnail: String(entry.thumbnail || ''),
      thumbnail_url: String(entry.thumbnail_url || ''),
      reference_type: 'character&style',
      strength: 1,
      fidelity: 0.8,
      enabled: true,
    });
  }

  async function openReferenceStorage() {
    referenceStorageOpen = true;
    render();
    try {
      const data = await api(API.referenceStorage);
      referenceStorage = Array.isArray(data?.items) ? data.items : [];
    } catch (error) {
      showToast(`레퍼런스 목록 로드 실패: ${error.message}`, 'error');
      referenceStorage = [];
    }
    render();
  }

  function referenceThumbSrc(reference) {
    if (reference.thumbnail) return `data:image/jpeg;base64,${reference.thumbnail}`;
    return reference.thumbnail_url || '';
  }

  function renderReferencePanel() {
    if (!referenceOpen) return '';
    if (!crCapable()) {
      const profile = selectedProfile();
      const notice = profile && profile.cr_capable === false
        ? '선택한 프리셋이 NAI 4.5가 아닌 모델을 강제합니다 - 프리셋을 바꾸거나 CURRENT로 전환하세요'
        : 'Character Reference requires a NAID4.5F/C model';
      return `
        <div class="char-bench-float-panel">
          <div class="char-bench-float-panel-head">캐릭터 레퍼런스
            <button class="module-popup-icon-btn" data-action="create-open-reference" aria-label="닫기">x</button></div>
          <div class="mod-notice">${escHtml(notice)}</div>
        </div>
      `;
    }
    if (referenceStorageOpen) {
      const items = referenceStorage.map(item => `
        <button class="char-bench-ref-storage-item" data-action="create-ref-pick"
          data-hash="${escAttr(item.file_hash)}" title="${escAttr(item.file_name || item.file_hash)}">
          <img loading="lazy" src="${escAttr(item.thumbnail_url || '')}" alt="">
        </button>
      `).join('');
      return `
        <div class="char-bench-float-panel">
          <div class="char-bench-float-panel-head">레퍼런스 라이브러리
            <button class="mod-btn-sm" data-action="create-ref-storage-back">뒤로</button></div>
          <div class="char-bench-ref-storage">
            ${items || '<div class="mod-empty">보관된 레퍼런스 이미지가 없습니다.</div>'}
          </div>
        </div>
      `;
    }
    const cards = references.map((reference, index) => `
      <div class="mod-ref-frame ${reference.enabled ? '' : 'disabled'}">
        <div class="mod-ref-header">
          <img class="mod-ref-thumb" src="${escAttr(referenceThumbSrc(reference))}" alt="">
          <div class="mod-ref-controls">
            <div class="mod-ref-controls-row">
              <label class="mod-checkbox-item">
                <input type="checkbox" ${reference.enabled ? 'checked' : ''}
                  data-field="create-ref-enable" data-index="${index}">
                <span class="mod-checkbox-label">Enable</span>
              </label>
              <button class="mod-btn-sm mod-btn-danger" data-action="create-ref-remove" data-index="${index}">Remove</button>
            </div>
            <select class="mod-select-sm" data-field="create-ref-type" data-index="${index}">
              ${REFERENCE_TYPES.map(([value, label]) => `
                <option value="${escAttr(value)}" ${reference.reference_type === value ? 'selected' : ''}>${escHtml(label)}</option>
              `).join('')}
            </select>
            <div class="mod-slider-row">
              <span class="mod-slider-label">Strength</span>
              <input type="range" min="0" max="20" step="1" value="${Math.round(reference.strength * 20)}"
                data-field="create-ref-strength" data-index="${index}">
              <span class="mod-slider-value" data-role="create-ref-strength-${index}">${reference.strength.toFixed(2)}</span>
            </div>
            <div class="mod-slider-row">
              <span class="mod-slider-label">Fidelity</span>
              <input type="range" min="0" max="20" step="1" value="${Math.round(reference.fidelity * 20)}"
                data-field="create-ref-fidelity" data-index="${index}">
              <span class="mod-slider-value" data-role="create-ref-fidelity-${index}">${reference.fidelity.toFixed(2)}</span>
            </div>
          </div>
        </div>
      </div>
    `).join('');
    return `
      <div class="char-bench-float-panel">
        <div class="char-bench-float-panel-head">캐릭터 레퍼런스
          <button class="module-popup-icon-btn" data-action="create-open-reference" aria-label="닫기">x</button></div>
        <div class="mod-upload-bar">
          <button class="mod-btn-upload" data-action="create-ref-upload" ${referenceBusy ? 'disabled' : ''}>Upload</button>
          <button class="mod-btn-upload" data-action="create-ref-paste" ${referenceBusy ? 'disabled' : ''}>Paste</button>
          <button class="mod-btn-upload mod-btn-storage" data-action="create-ref-storage">Storage</button>
        </div>
        ${cards || '<div class="mod-empty">레퍼런스를 붙이면 이 생성에만 적용됩니다.</div>'}
      </div>
    `;
  }

  function renderProfileBlock() {
    const presetAvailable = profiles.presets.length > 0;
    const options = profiles.presets.map(profile => `
      <option value="${escAttr(profile.name)}" ${profile.name === promptPreset ? 'selected' : ''}
        data-preview-name="${escAttr(profile.name)}"
        data-preview-mode="NAI"
        data-preview-prefix="${escAttr(profile.prefix || '')}"
        data-preview-description="${escAttr(profile.description || '')}"
        data-preview-thumbnail="${escAttr(profile.thumbnail_url || '')}">${escHtml(profile.name)}</option>
    `).join('');
    return `
      <div class="mod-section-label">프롬프트 엔지니어링 모듈 프리셋</div>
      <div class="char-bench-profile-toggle">
        <button class="char-bench-profile-btn ${promptSource === 'current' ? 'active' : ''}"
          data-action="create-prompt-source" data-source="current">CURRENT</button>
        <button class="char-bench-profile-btn ${promptSource === 'preset' ? 'active' : ''}"
          data-action="create-prompt-source" data-source="preset"
          ${presetAvailable ? '' : 'disabled title="NAI Quick Preset 없음"'}>PRESET</button>
      </div>
      ${promptSource === 'preset' ? `
        <select class="mod-select char-bench-preset-select" data-field="create-preset"
          data-preview-kind="prompt-preset">${options}</select>
      ` : ''}
      <button class="char-bench-custom-btn ${promptSource === 'custom' ? 'active' : ''}"
        data-action="create-custom-open"
        title="선택한 프로파일을 시드로 PREFIX/POSTFIX/NEGATIVE/CFG/샘플러 등을 일시 수정합니다 (영구 저장 없음)">
        CUSTOM : 세부 프리셋 설정값 수정 &gt;${promptSource === 'custom' ? ' (적용 중)' : ''}</button>
    `;
  }

  function render() {
    renderEpoch += 1;
    deferredRender = false;
    deferredTarget = null;
    const host = ensureLayer();
    host.hidden = !open;
    const keepScroll = {
      strip: host.querySelector('.char-bench-strip-body')?.scrollTop || 0,
      form: host.querySelector('.char-bench-form-scroll')?.scrollTop || 0,
    };
    const nai = isNai();
    const pendingCount = candidates.filter(candidate => candidate.status === 'pending').length;
    const current = selectedCandidate();
    const detail = typeof getSelectedDetail === 'function' ? getSelectedDetail() : null;
    // 최신 후보가 위로(생성 순서 역순) - index는 상관관계용이라 순서와 무관.
    const strip = [...candidates].reverse().map(candidate => {
      const badge = benchModeBadge(candidate.mode, candidate.hasReference);
      const badgeHtml = badge ? `<span class="char-bench-mode-badge mode-${escAttr(candidate.mode)}">${badge}</span>` : '';
      if (candidate.status === 'pending') {
        return `<div class="char-bench-thumb pending">생성 중...${badgeHtml}</div>`;
      }
      if (candidate.status === 'error') {
        return `<div class="char-bench-thumb error" title="${escAttr(candidate.message)}">실패${badgeHtml}</div>`;
      }
      if (candidate.status === 'expired') {
        return `<div class="char-bench-thumb error" title="${escAttr(candidate.message)}">만료됨${badgeHtml}</div>`;
      }
      return `
        <button class="char-bench-thumb done ${candidate.index === selected ? 'selected' : ''} ${candidate.saved ? 'saved' : ''}"
          data-action="create-pick" data-index="${candidate.index}">
          <div class="char-bench-crop plain">
            <img class="char-bench-plain-img" src="${API.historyImage(candidate.historyId)}" alt="">
          </div>
          ${badgeHtml}
          ${candidate.saved ? '<span class="char-bench-saved-badge">저장됨</span>' : ''}
        </button>
      `;
    }).join('');

    host.innerHTML = `
      <div class="char-bench-backdrop"></div>
      <div class="char-bench" role="dialog" aria-label="캐릭터 생성 벤치">
        <header class="char-bench-header">
          <div class="char-bench-title">캐릭터 생성
            <span class="char-asset-detail-id">고정 전신 스캐폴드 768x1344</span></div>
          <button class="module-popup-icon-btn" data-action="create-close" aria-label="닫기">x</button>
        </header>
        <div class="char-bench-body">
          <section class="char-bench-form">
            <div class="char-bench-form-scroll">
              ${renderRandomSlot()}
              <div class="mod-section-label">Character Prompt (외형/의상/디테일)</div>
              <textarea class="mod-textarea char-bench-ta char-bench-create-ta" data-field="create-prompt"
                placeholder="girl, blonde hair, blue eyes...">${escHtml(prompt)}</textarea>
              <div class="char-bench-prefill-row">
                <button class="mod-btn-sm" data-action="create-prefill-c1">C1에서 가져오기</button>
                <button class="mod-btn-sm" data-action="create-prefill-selected"
                  ${detail?.recovered ? '' : 'disabled'}>선택 에셋에서</button>
              </div>
              <div class="mod-section-label">Character UC</div>
              <textarea class="mod-textarea mod-uc char-bench-ta-sm char-bench-create-uc" data-field="create-uc"
                placeholder="character UC (optional)...">${escHtml(uc)}</textarea>
              ${renderProfileBlock()}
              <div class="char-asset-count">${inpaintPin
                ? '인페인트 고정: 핀 이미지 위에 마스크 영역만 재생성 / strength 1.0 / 프롬프트 조합은 스캐폴드와 동일'
                : '고정 스캐폴드: {1girl|1boy} + PREFIX + 전신 레퍼런스 태그 + POSTFIX / 768x1344 / 후보를 골라 저장'}</div>
            </div>
            <div class="char-bench-form-footer">
              <div class="char-bench-gen-row">
                <label class="char-asset-gen-count">횟수
                  <input type="number" min="1" max="${GENERATE_MAX}" value="${Number(count) || 1}" data-field="create-count">
                </label>
                <button class="mod-btn-sm mod-btn-encode char-bench-generate-btn" data-action="create-generate"
                  ${nai && !busy && !pendingCount ? '' : 'disabled'}
                  ${nai ? '' : 'title="NAI 모드 전용"'}>${pendingCount
                    ? `생성 중... (${pendingCount})`
                    : (inpaintPin ? '인페인트 생성' : '캐릭터 생성')}</button>
                <button class="mod-btn-sm mod-btn-encode char-bench-slot-btn" data-action="create-random-generate"
                  ${nai && !busy && !randomBusy && !pendingCount ? '' : 'disabled'}
                  title="랜덤을 한 번 굴린 뒤 바로 생성합니다">🎰</button>
              </div>
            </div>
          </section>
          <section class="char-bench-compare char-bench-compare-single">
            <div class="char-bench-pane">
              <div class="mod-section-label">생성 결과</div>
              <div class="char-bench-fit">
                <!-- 결과 영역 좌상단 플로팅 도구 - 창 크기와 무관하게 캔버스에 고정 -->
                <div class="char-bench-float-tools">
                  <!-- 툴팁(title) 금지: 플로팅 버튼은 재렌더가 잦아 전역 툴팁이
                       mouseleave를 놓치고 화면에 눌어붙는다(사용자 제보). -->
                  <button class="char-bench-float-btn tone-reference ${referenceOpen ? 'active' : ''}"
                    data-action="create-open-reference">캐릭터 레퍼런스${activeReferences().length ? ` (${activeReferences().length})` : ''}</button>
                  <button class="char-bench-float-btn tone-inpaint ${inpaintPin ? 'active' : ''}"
                    data-action="create-open-inpaint"
                    ${inpaintPin || (current?.historyId && current.status === 'done' && !maskBusy) ? '' : 'disabled'}>${
                      inpaintPin ? '인페인트 (핀 고정)' : (maskBusy ? '핀 고정 중...' : '인페인트 모드')}</button>
                  ${inpaintPin ? `
                    <div class="char-bench-pin-thumb">
                      <button class="char-bench-pin-open" data-action="create-open-inpaint">
                        <img src="${escAttr(API.pinImage(inpaintPin.pinId))}" alt="인페인트 핀">
                      </button>
                      <button class="char-bench-pin-x" data-action="create-pin-unpin"
                        aria-label="핀 해제">x</button>
                    </div>
                  ` : ''}
                </div>
                ${renderReferencePanel()}
                ${renderCustomPanel()}
                ${current?.historyId ? `
                  <div class="char-bench-crop plain">
                    <img class="char-bench-plain-img" src="${API.historyImage(current.historyId)}" alt="">
                  </div>
                ` : '<div class="char-bench-crop empty"><div class="mod-empty">생성된 결과가 여기 표시됩니다.</div></div>'}
              </div>
              <div class="char-bench-save-row">
                <button class="mod-btn-sm mod-btn-encode char-bench-save-btn" data-action="create-save"
                  ${current?.historyId && !current.saved && !busy && current.status === 'done' ? '' : 'disabled'}
                  ${current?.status === 'expired' ? 'title="히스토리에서 만료됨 - 저장 불가"' : ''}>
                  ${current?.saved ? '저장됨' : (current?.status === 'expired' ? '만료됨' : '새 캐릭터로 저장')}</button>
                <button class="mod-btn-sm" data-action="create-save-variation"
                  ${current?.historyId && !current.saved && !busy && current.status === 'done' && detail?.id ? '' : 'disabled'}
                  title="${detail?.id ? '선택한 캐릭터의 바리에이션으로 저장' : '대상 캐릭터를 먼저 선택하세요'}">바리에이션으로</button>
                <button class="mod-btn-sm" data-action="create-discard" ${current ? '' : 'disabled'}>버리기</button>
              </div>
            </div>
          </section>
          <aside class="char-bench-strip">
            <div class="mod-section-label">후보</div>
            <div class="char-bench-strip-body">
              ${strip || '<div class="mod-empty char-bench-strip-empty">아직 후보가 없습니다.<br>좌측에서 생성을 시작하세요.</div>'}
            </div>
          </aside>
        </div>
      </div>
    `;
    const stripBody = host.querySelector('.char-bench-strip-body');
    if (stripBody) stripBody.scrollTop = keepScroll.strip;
    const formScroll = host.querySelector('.char-bench-form-scroll');
    if (formScroll) formScroll.scrollTop = keepScroll.form;
    // Character UC는 기존 Character/Img2Img 규칙대로 Tag Assist 제외.
    host.querySelectorAll([
      'textarea[data-field="create-prompt"]',
      'textarea[data-field="create-custom-prefix"]',
      'textarea[data-field="create-custom-postfix"]',
      'textarea[data-field="create-custom-negative"]',
    ].join(', ')).forEach(element => bindTagAssist(element));
  }

  return {
    open: openBench,
    close,
    handleResultMeta,
    handleGenerationError,
    handleHistoryRemoved,
    hasPending: () => candidates.some(candidate => candidate.status === 'pending'),
    // 회귀 테스트 전용 훅(tests/_character_creation_bench_check.mjs): 이벤트 위임은
    // DOM 없이 구동할 수 없어 액션 함수를 직접 호출한다.
    __testGenerate: (batch = 1, perCandidatePrompts = null) => {
      prompt = prompt || 'girl, blue hair';
      count = batch;
      return generate(perCandidatePrompts);
    },
    __testSave: target => save(target),
    __testSelect: index => { selected = index; },
    __testCandidates: () => candidates,
    // 인페인트 회귀용: DOM 캔버스 없이 핀+가짜 엔진을 주입해 generate payload를 검증.
    __testSetPin: (pin, engine = null) => {
      inpaintPin = pin;
      maskEngine = engine;
    },
    __testPin: () => inpaintPin,
  };
}
