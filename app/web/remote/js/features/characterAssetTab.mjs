// Character Asset tab — persistent image-based character library (web port of
// the desktop character asset storage, Dev0714). Gallery + detail + standard
// reference generation. Server state is the source of truth; the whole pane is
// re-rendered from fetched data and events are bound once via delegation.

import {
  appendBenchCandidateBatch,
  benchModeBadge,
  findBenchRequestCandidate,
} from './benchCandidates.mjs?v=20260717-benchcand4';
import {createCharacterCreationBench} from './characterCreationBench.mjs?v=20260718-fix1';

// 캐릭터 생성 벤치도 같은 계약을 쓰므로 재수출한다(기존 import 경로 호환).
export {appendBenchCandidateBatch, benchModeBadge, findBenchRequestCandidate};

const API = {
  list: '/api/character-asset/list',
  // variation을 넘기면 그 바리에이션 자신의 프롬프트/UC가 돌아온다.
  detail: (id, variation = '') =>
    `/api/character-asset/detail?id=${encodeURIComponent(id)}`
    + (variation ? `&variation=${encodeURIComponent(variation)}` : ''),
  thumb: (id, revision) => `/api/character-asset/thumb?id=${encodeURIComponent(id)}&size=grid&v=${revision || 0}`,
  variationThumb: (id, hash, revision) =>
    `/api/character-asset/thumb?id=${encodeURIComponent(id)}&variation=${encodeURIComponent(hash)}&size=grid&v=${revision || 0}`,
  image: (id, hash, revision) =>
    `/api/character-asset/image?id=${encodeURIComponent(id)}${hash ? `&variation=${encodeURIComponent(hash)}` : ''}&v=${revision || 0}`,
  save: '/api/character-asset/save',
  apply: '/api/character-asset/apply',
  rename: '/api/character-asset/rename',
  updatePrompt: '/api/character-asset/update-prompt',
  remove: '/api/character-asset/delete',
  removeVariation: '/api/character-asset/delete-variation',
  promote: '/api/character-asset/promote',
  generate: '/api/character-asset/generate',
  historyThumb: id => `/api/history/thumb/${encodeURIComponent(id)}`,
  // 벤치 후보는 리스가 붙잡고 있으므로 히스토리 퇴출 후에도 이 경로로 살아있다.
  historyImage: id => `/api/character-asset/candidate/image?history_id=${encodeURIComponent(id)}`,
  benchDefaults: id => `/api/character-asset/bench/defaults?id=${encodeURIComponent(id)}`,
  benchGenerate: '/api/character-asset/bench/generate',
  benchEnhance: '/api/character-asset/bench/enhance',
  benchSave: '/api/character-asset/bench/save',
  randomOutfit: '/api/character-asset/random-outfit',
};

const GENERATE_MAX = 8;

export function createCharacterAssetTabController({
  document,
  fetch,
  escHtml,
  showToast,
  showPromptDialog = null,
  bindTagAssist = () => {},
  getGenerationMode,
  getCharacterState = null,
  getCharacterReferenceState = null,
  onReferenceInsetPin = () => {},
}) {
  const root = document.getElementById('charAssetRoot');
  let active = false;
  let loadedOnce = false;
  let loading = false;
  let characters = [];
  let selectedId = '';
  let selectedVariation = '';
  let detail = null;
  let detailLoading = false;
  let staged = null;              // {source:{kind,...}, label}
  let deleteArmed = '';           // 'char:<id>' | 'variation:<hash>' (2-step confirm)
  let deleteArmTimer = null;
  let busy = false;
  let promptEditOpen = false;
  let promptDraft = '';
  // [불러오기시 의상 제거] - 켠 채로 두는 사람이 많을 설정이라 브라우저에 기억한다.
  const STRIP_OUTFIT_KEY = 'naia.characterAsset.stripOutfit';
  let stripOutfit = (() => {
    try { return globalThis.localStorage?.getItem(STRIP_OUTFIT_KEY) === '1'; }
    catch (_) { return false; }
  })();
  let promptUcDraft = '';
  // 생성 벤치는 탭 컨트롤러당 싱글턴 - 닫아도 후보/requestId를 보존해야 진행 중
  // 결과가 미아가 되지 않는다(Codex 수명 계약).
  let creationBench = null;

  function escAttr(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/"/g, '&quot;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  function isNai() {
    try {
      return String(getGenerationMode ? getGenerationMode() : 'NAI').toUpperCase() === 'NAI';
    } catch {
      return false;
    }
  }

  function newRequestId() {
    try {
      return globalThis.crypto.randomUUID().replace(/-/g, '');
    } catch {
      return `ca${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
    }
  }

  async function api(url, options = null) {
    const response = await fetch(url, options || undefined);
    let payload = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    if (!response.ok) {
      throw new Error(String(payload?.error || `HTTP ${response.status}`));
    }
    return payload || {};
  }

  function postJson(url, body) {
    return api(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body || {}),
    });
  }

  function summaryName(entry) {
    const custom = String(entry?.display_name || '').trim();
    if (custom) return custom;
    return String(entry?.id || '').slice(0, 8);
  }

  function disarmDelete() {
    deleteArmed = '';
    if (deleteArmTimer) {
      globalThis.clearTimeout(deleteArmTimer);
      deleteArmTimer = null;
    }
  }

  function armDelete(key) {
    disarmDelete();
    deleteArmed = key;
    deleteArmTimer = globalThis.setTimeout(() => {
      deleteArmed = '';
      deleteArmTimer = null;
      render();
    }, 3000);
  }

  // ------------------------------------------------------------- data loads

  async function load(force = false) {
    if (loading) return;
    if (loadedOnce && !force && characters.length) {
      render();
      return;
    }
    loading = true;
    render();
    try {
      const state = await api(API.list);
      characters = Array.isArray(state?.characters) ? state.characters : [];
      loadedOnce = true;
      if (selectedId && !characters.some(entry => entry.id === selectedId)) {
        selectedId = '';
        selectedVariation = '';
        detail = null;
      }
    } catch (error) {
      console.error('Character Asset list failed', error);
      showToast(`에셋 목록 로드 실패: ${error.message}`, 'error');
    } finally {
      loading = false;
      render();
    }
  }

  let selectToken = 0;

  function revisionFor(id) {
    const entry = characters.find(item => item.id === id);
    return entry?.revision || 0;
  }

  function previewUrlFor(hash) {
    if (!detail) return '';
    if (hash) {
      const variation = (detail.variations || []).find(item => item.hash === hash);
      return API.image(detail.id, hash, variation?.revision || 0);
    }
    return API.image(detail.id, '', detail.revision || revisionFor(detail.id));
  }

  function updateGridSelection() {
    root?.querySelectorAll('.char-asset-card').forEach(card => {
      card.classList.toggle('selected', card.dataset.id === selectedId);
    });
  }

  function swapPreviewImage(url) {
    // 기존 <img>를 유지한 채 새 이미지를 프리로드 후 src만 교체 - 디코딩이
    // 끝나기 전까지 이전 이미지가 그대로 보여 깜빡임이 없다.
    const img = root?.querySelector('[data-role="preview-img"]');
    if (!img || !url) return;
    if (img.getAttribute('src') === url) return;
    img.dataset.pendingSrc = url;
    const probe = new Image();
    probe.onload = () => {
      if (img.isConnected && img.dataset.pendingSrc === url) img.src = url;
    };
    probe.src = url;
  }

  function updateApplyButtons() {
    const enabled = isNai() && !busy && !!detail?.recovered;
    ['apply-c1', 'apply-c1-cr', 'apply-c1-inset', 'apply-add'].forEach(action => {
      const button = root?.querySelector(`[data-action="${action}"]`);
      if (!button) return;
      button.disabled = !enabled;
      if (!detail?.recovered) {
        button.title = '이 이미지에는 NAI 캐릭터 블록이 없습니다';
      } else if (!isNai()) {
        button.title = 'NAI 모드 전용';
      } else {
        button.title = action === 'apply-c1-cr'
          ? 'C1 슬롯 적용 + 이 이미지를 Character Reference로 등록 (해상도는 자동 정규화)'
          : '';
      }
    });
  }

  function patchDetail() {
    // 카드 전환용 부분 갱신 - pane 구조는 유지하고 내용만 바꾼다(전체
    // innerHTML 재구성은 UI가 재설정되며 깜빡인다).
    const nameEl = root?.querySelector('[data-role="detail-name"]');
    const zone = root?.querySelector('[data-role="variations-zone"]');
    if (!nameEl || !zone || !detail) {
      render();
      return;
    }
    const entry = characters.find(item => item.id === selectedId);
    nameEl.textContent = summaryName({...entry, id: selectedId, display_name: detail.display_name});
    const idEl = root.querySelector('[data-role="detail-id"]');
    if (idEl) idEl.textContent = selectedId;
    const promptEl = root.querySelector('[data-role="prompt-pre"]');
    if (promptEl) promptEl.textContent = detail.character_prompt || '(empty)';
    const ucEl = root.querySelector('[data-role="uc-pre"]');
    if (ucEl) ucEl.textContent = detail.character_uc || '(empty)';
    // 프롬프트는 선택된 이미지(대표/바리에이션) 것 - 표시 범위를 함께 갱신한다.
    const scopeEl = root.querySelector('[data-role="prompt-scope"]');
    if (scopeEl) scopeEl.textContent = selectedVariation ? '(바리에이션)' : '(대표)';
    const warnEl = root.querySelector('[data-role="recover-warn"]');
    if (warnEl) warnEl.hidden = !!detail.recovered;
    zone.innerHTML = renderVariationsZone();
    const deleteBtn = root.querySelector('[data-action="delete-character"]');
    if (deleteBtn) deleteBtn.textContent = '캐릭터 삭제';
    updateApplyButtons();
    swapPreviewImage(previewUrlFor(selectedVariation));
  }

  async function select(id, variation = '') {
    const token = ++selectToken;
    promptEditOpen = false;
    promptDraft = '';
    promptUcDraft = '';
    selectedId = String(id || '');
    selectedVariation = String(variation || '');
    disarmDelete();
    if (!selectedId) {
      detail = null;
      render();
      return;
    }
    const detailMounted = !!root?.querySelector('[data-role="detail-head"]');
    if (detailMounted) {
      // in-place 경로: 선택 표시와 뷰어 이미지를 즉시 갱신하고, 상세 데이터가
      // 도착하면 텍스트/스트립만 패치한다. 이전 상세 텍스트는 그동안 유지.
      updateGridSelection();
      swapPreviewImage(API.image(selectedId, selectedVariation, revisionFor(selectedId)));
    } else {
      detail = null;
      detailLoading = true;
      render();
    }
    try {
      const next = await api(API.detail(selectedId, selectedVariation));
      if (token !== selectToken) return;
      detail = next;
    } catch (error) {
      if (token !== selectToken) return;
      console.error('Character Asset detail failed', error);
      showToast(`에셋 상세 로드 실패: ${error.message}`, 'error');
      detail = null;
    } finally {
      if (token === selectToken) {
        detailLoading = false;
        if (detailMounted && detail && detail.id === selectedId) patchDetail();
        else render();
      }
    }
  }

  async function selectVariationInPlace(hash) {
    // 스트립 하이라이트/뷰어는 즉시(깜빡임 방지), 프롬프트는 detail 재조회로 갱신.
    // 재조회 없이는 CHARACTER PROMPT가 항상 (대표)에 고정된다(사용자 제보).
    selectedVariation = String(hash || '');
    disarmDelete();
    const zone = root?.querySelector('[data-role="variations-zone"]');
    if (!zone || !detail) {
      render();
      if (selectedId) await select(selectedId, selectedVariation);
      return;
    }
    zone.querySelectorAll('.char-asset-var').forEach(item => {
      item.classList.toggle('selected', String(item.dataset.hash || '') === selectedVariation);
    });
    const actions = zone.querySelector('.char-asset-var-actions');
    if (actions) {
      // 행 전체가 아니라 승격/삭제 span만 토글 - 행을 숨기면 상시 노출이어야
      // 하는 [+ 바리에이션 추가] 버튼까지 사라진다.
      const variationOnly = actions.querySelector('span');
      if (variationOnly) variationOnly.hidden = !selectedVariation;
      const deleteBtn = actions.querySelector('[data-action="delete-variation"]');
      if (deleteBtn) deleteBtn.textContent = '바리에이션 삭제';
    }
    swapPreviewImage(previewUrlFor(selectedVariation));
    // 선택한 이미지(대표/바리에이션) 자신의 프롬프트/UC를 가져와 텍스트만 패치.
    const token = ++selectToken;
    const wasEditing = promptEditOpen;
    promptEditOpen = false;
    promptDraft = '';
    promptUcDraft = '';
    try {
      const next = await api(API.detail(selectedId, selectedVariation));
      if (token !== selectToken) return;
      detail = next;
    } catch (error) {
      if (token !== selectToken) return;
      console.error('Character Asset variation detail failed', error);
      showToast(`바리에이션 상세 로드 실패: ${error.message}`, 'error');
      return;
    }
    if (wasEditing) {
      // 편집 폼이 열려 있었다면 pre 요소가 DOM에 없다 - 전체 재렌더로 폼을 닫는다.
      render();
      return;
    }
    const promptEl = root.querySelector('[data-role="prompt-pre"]');
    if (promptEl) promptEl.textContent = detail.character_prompt || '(empty)';
    const ucEl = root.querySelector('[data-role="uc-pre"]');
    if (ucEl) ucEl.textContent = detail.character_uc || '(empty)';
    const scopeEl = root.querySelector('[data-role="prompt-scope"]');
    if (scopeEl) scopeEl.textContent = selectedVariation ? '(바리에이션)' : '(대표)';
    const warnEl = root.querySelector('[data-role="recover-warn"]');
    if (warnEl) warnEl.hidden = !!detail.recovered;
    updateApplyButtons();
  }

  async function refreshAll({keepSelection = true} = {}) {
    const keptId = keepSelection ? selectedId : '';
    const keptVariation = keepSelection ? selectedVariation : '';
    await load(true);
    if (keptId && characters.some(entry => entry.id === keptId)) {
      await select(keptId, keptVariation);
    }
  }

  function openCreationBench() {
    if (!creationBench) {
      creationBench = createCharacterCreationBench({
        document,
        api,
        postJson,
        escHtml,
        escAttr,
        showToast,
        bindTagAssist,
        isNai,
        newRequestId,
        getCharacterState,
        getCharacterReferenceState,
        getSelectedDetail: () => detail,
        onSaved: async characterId => {
          await load(true);
          if (characterId && characters.some(entry => entry.id === characterId)) {
            await select(characterId);
          } else {
            render();
          }
        },
      });
    }
    creationBench.open();
  }

  // ---------------------------------------------------------------- actions

  async function saveStaged(target) {
    if (!staged || busy) return;
    busy = true;
    render();
    try {
      const result = await postJson(API.save, {source: staged.source, target});
      staged = null;
      if (result.character_prompt_recovered === false) {
        showToast('저장됨 - 단, 이 이미지에는 NAI 캐릭터 블록이 없어 C1 적용은 불가합니다', 'warning');
      } else {
        showToast(target?.kind === 'variation' ? '바리에이션으로 저장됨' : '캐릭터 에셋으로 저장됨', 'success');
      }
      busy = false;
      await load(true);
      await select(result.character_id || '');
    } catch (error) {
      busy = false;
      showToast(`에셋 저장 실패: ${error.message}`, 'error');
      render();
    }
  }

  async function applySlot(mode, withReference = false, withInset = false) {
    if (!selectedId || busy) return;
    if (!isNai()) {
      showToast('캐릭터 슬롯 적용은 NAI 모드 전용입니다', 'error');
      return;
    }
    busy = true;
    render();
    try {
      const result = await postJson(API.apply, {
        id: selectedId,
        variation: selectedVariation,
        mode,
        with_reference: withReference,
        with_inset: withInset,
        strip_outfit: stripOutfit,
      });
      if (withInset) {
        showToast('C1 슬롯 적용 + 레퍼런스 인셋 고정됨 - 해제 전까지 1152x896 인셋으로 생성됩니다', 'success');
        // Result 탭 좌상단 핀 배지 갱신(앱 셸 소유)
        if (result.reference_inset) onReferenceInsetPin(result.reference_inset);
      } else if (withReference) {
        if (result.reference_attached) {
          showToast('C1 슬롯 + Character Reference 적용됨', 'success');
        } else {
          showToast('C1 슬롯은 적용됐지만 Character Reference 등록에 실패했습니다', 'warning');
        }
      } else if (mode === 'add_slot') {
        showToast('새 캐릭터 슬롯으로 추가됨', 'success');
      } else {
        // C1 단독 = CR 없는 깨끗한 상태가 계약 - 켜져 있던 CR이 있었으면 알린다.
        showToast(
          result.references_disabled
            ? 'C1 슬롯에 적용됨 - 기존 Character Reference는 비활성화했습니다'
            : 'C1 슬롯에 적용됨',
          'success',
        );
      }
    } catch (error) {
      showToast(`슬롯 적용 실패: ${error.message}`, 'error');
    } finally {
      busy = false;
      render();
    }
  }

  async function renameSelected() {
    if (!selectedId || !showPromptDialog) return;
    const current = String(detail?.display_name || '');
    const next = await showPromptDialog('표시 이름을 입력하세요. 비우면 id 요약을 사용합니다.', {
      title: 'Character Asset',
      okText: 'Apply',
      cancelText: 'Cancel',
      defaultValue: current,
    });
    if (next === null) return;
    try {
      await postJson(API.rename, {id: selectedId, display_name: next.trim()});
      showToast('이름이 변경되었습니다', 'success');
      if (benchChar?.id === selectedId) {
        // rename은 revision을 바꾸지 않아 fast path가 놓친다 - 유지 벤치 제목 동기화.
        benchChar.name = summaryName({id: selectedId, display_name: next.trim()});
        if (benchLayer?.childElementCount) renderBenchPreservingFocusedInput();
      }
      await refreshAll();
    } catch (error) {
      showToast(`이름 변경 실패: ${error.message}`, 'error');
    }
  }

  function beginPromptEdit() {
    if (!detail || busy) return;
    promptDraft = String(detail.character_prompt || '');
    promptUcDraft = String(detail.character_uc || '');
    promptEditOpen = true;
    render();
  }

  function cancelPromptEdit() {
    promptEditOpen = false;
    promptDraft = '';
    promptUcDraft = '';
    render();
  }

  async function savePromptEdit() {
    if (!selectedId || !detail || busy) return;
    const prompt = promptDraft.trim();
    if (!prompt) {
      showToast('Character Prompt는 비워둘 수 없습니다', 'error');
      return;
    }
    const editingId = selectedId;
    // 보정은 "지금 보고 있는 이미지"에 대한 것 - 바리에이션을 보고 있으면 그
    // 바리에이션에만 적용된다(대표 이미지 프롬프트를 덮어쓰지 않는다).
    const editingVariation = selectedVariation;
    busy = true;
    render();
    try {
      const result = await postJson(API.updatePrompt, {
        id: editingId,
        variation: editingVariation,
        character_prompt: prompt,
        character_uc: promptUcDraft.trim(),
      });
      if (
        selectedId === editingId
        && selectedVariation === editingVariation
        && detail?.id === editingId
      ) {
        detail.character_prompt = String(result.character_prompt || prompt);
        detail.character_uc = String(result.character_uc || '');
        detail.recovered = true;
      }
      // 벤치는 대표 이미지(A) 기준이라 primary 보정만 반영한다.
      if (!editingVariation && benchChar?.id === editingId) {
        benchChar.prompt = String(result.character_prompt || prompt);
        benchChar.uc = String(result.character_uc || '');
        // 유지 중인(숨김 포함) 벤치 DOM의 textarea에도 저장값을 반영.
        if (benchLayer?.childElementCount) renderBench();
      }
      promptEditOpen = false;
      promptDraft = '';
      promptUcDraft = '';
      showToast('캐릭터 프롬프트를 저장했습니다', 'success');
    } catch (error) {
      showToast(`프롬프트 저장 실패: ${error.message}`, 'error');
    } finally {
      busy = false;
      render();
    }
  }

  async function deleteSelected() {
    if (!selectedId || busy) return;
    const key = `char:${selectedId}`;
    if (deleteArmed !== key) {
      armDelete(key);
      render();
      return;
    }
    disarmDelete();
    busy = true;
    render();
    try {
      await postJson(API.remove, {id: selectedId});
      showToast('캐릭터가 삭제되었습니다', 'success');
      if (benchChar?.id === selectedId) {
        // 삭제된 캐릭터의 유지 벤치는 파기(재오픈 시 404 저장 방지).
        benchChar = null;
        benchCandidates = [];
        benchSelected = -1;
        benchRequestId = '';
        renderBench();
      }
      selectedId = '';
      selectedVariation = '';
      detail = null;
      busy = false;
      await load(true);
    } catch (error) {
      busy = false;
      showToast(`삭제 실패: ${error.message}`, 'error');
      render();
    }
  }

  async function deleteSelectedVariation() {
    if (!selectedId || !selectedVariation || busy) return;
    const key = `variation:${selectedVariation}`;
    if (deleteArmed !== key) {
      armDelete(key);
      render();
      return;
    }
    disarmDelete();
    try {
      await postJson(API.removeVariation, {id: selectedId, hash: selectedVariation});
      showToast('바리에이션이 삭제되었습니다', 'success');
      await refreshAll({keepSelection: true});
      selectedVariation = '';
      await select(selectedId);
    } catch (error) {
      showToast(`바리에이션 삭제 실패: ${error.message}`, 'error');
    }
  }

  async function promoteSelectedVariation() {
    if (!selectedId || !selectedVariation || busy) return;
    try {
      await postJson(API.promote, {id: selectedId, hash: selectedVariation});
      showToast('대표 이미지로 승격되었습니다', 'success');
      selectedVariation = '';
      await refreshAll();
    } catch (error) {
      showToast(`승격 실패: ${error.message}`, 'error');
    }
  }

  function handleResultMeta(meta) {
    if (!meta || typeof meta !== 'object') return;
    if (!meta.character_asset_request) return;
    const requestId = String(meta.character_asset_request_id || '');
    if (meta.character_asset_bench) {
      if (!benchRequestId || requestId !== benchRequestId) return;
      const candidate = findBenchRequestCandidate(
        benchCandidates, requestId, meta.character_asset_candidate
      );
      if (!candidate || candidate.status === 'done') return;
      candidate.status = 'done';
      candidate.historyId = String(meta.history_id || '');
      if (benchSelected < 0) benchSelected = candidate.index;
      // Enhance 결과: 원본 후보를 보고 있던 사용자를 결과로 이동시켜 바로 확인/저장.
      else if (candidate.enhanceSource !== undefined && benchSelected === candidate.enhanceSource) {
        benchSelected = candidate.index;
      }
      // 닫혀 있어도 유지된 DOM에 결과를 동기화한다(숨김 렌더) - 재오픈 즉시 복원.
      if (benchChar) renderBenchPreservingFocusedInput();
      return;
    }
    // 바리에이션 벤치 소유가 아니면 생성 벤치에 넘긴다(각자 자기 requestId만 처리).
    creationBench?.handleResultMeta(meta);
  }

  function handleGenerationError(message) {
    if (!message || typeof message !== 'object') return;
    const requestId = String(message.requestId || '');
    if (benchRequestId && requestId === benchRequestId) {
      const candidate = findBenchRequestCandidate(
        benchCandidates, requestId, message.candidate
      );
      if (!candidate || candidate.status === 'done') return;
      candidate.status = 'error';
      candidate.message = String(message.message || 'generation failed');
      // 닫혀 있어도 유지된 DOM에 결과를 동기화한다(숨김 렌더) - 재오픈 즉시 복원.
      if (benchChar) renderBenchPreservingFocusedInput();
      return;
    }
    creationBench?.handleGenerationError(message);
  }

  function handleHistoryRemoved(message) {
    // 히스토리 퇴출만으로 만료시키지 않는다 - 캐릭터 에셋 후보는 백엔드 리스가
    // 붙잡고 있어 저장/미리보기가 모두 살아있다(퇴출로 만료시키면 과금된 결과를
    // UI가 스스로 막는다 - Codex). 리스에서까지 밀려난 경우는 저장/이미지 404로
    // 드러나며 그 때 markCandidateExpiredFromError가 확정한다.
    void message;
  }

  // ------------------------------------------------------- variation bench

  let benchLayer = null;
  let benchOpen = false;
  let benchChar = null;          // {id, name, prompt, uc, revision}
  let benchMode = 'char_reference'; // 'inpaint' | 'char_reference' - 기본은 CR(사용자 지시 2026-07-17)
  let benchReferenceType = 'character'; // 기본 CR 스펙 = Character (사용자 지시 2026-07-17)
  let benchReferenceStrength = 0.8; // 기본 S 0.8 (사용자 지시 2026-07-17)
  let benchReferenceFidelity = 0.9; // 기본 F 0.9
  let benchPromptSource = 'primary';
  let benchPromptPreset = '';
  let benchPromptProfileCharacterId = '';
  let benchPromptProfiles = {primary: null, current: null, presets: []};
  // CUSTOM: 선택 프로파일을 시드로 일부 값(PREFIX/POSTFIX/CFG/샘플러 등)을 고쳐
  // 이 벤치의 생성에만 일시 적용한다. 영구 저장 없음(사용자 계약 - 영구 변경은
  // 원본 이미지 교체). benchCustom = 적용 스냅샷, Draft = 패널 편집값.
  let benchCustom = null;
  let benchCustomDraft = null;
  let benchCustomOpen = false;
  // Main Prompt / 추가 Negative는 생성 모드별로 따로 관리된다.
  const benchFields = {
    inpaint: {main: '', negative: ''},
    char_reference: {main: '', negative: ''},
  };
  let benchCount = 1;
  let benchDefaultsLoaded = false;
  let benchRequestId = '';
  let benchCandidates = [];      // {index, status, historyId, message, saved}
  let benchSelected = -1;
  let benchBusy = false;
  let benchRenderEpoch = 0;
  let benchDeferredRender = false;
  let benchDeferredTarget = null;
  let benchDeferredPolling = false;
  // 의상 랜덤: 슬롯이 넣은 의상 태그를 기억해 재굴림 때 정확히 회수한다(어휘
  // 밖의 태그도 있으므로 어휘 제거만으로는 부족하다).
  let outfitBusy = false;
  let outfitOwned = [];

  function benchRenderBlocker() {
    const focused = document.activeElement;
    if (
      focused
      && benchLayer?.contains(focused)
      && focused.matches?.([
        '.char-bench-form textarea[data-field]',
        // CUSTOM 패널(원본 A 영역)도 입력 중 재렌더로 파기되면 안 된다.
        '.char-bench-custom-panel textarea[data-field]',
        '.char-bench-custom-panel input[data-field]',
      ].join(', '))
    ) {
      return focused;
    }
    // 열린 custom select(프리셋 콤보 등)를 재렌더로 파기하면 플로팅 미리보기가
    // 강제로 닫힌다(Codex CONCERN) - 닫힐 때까지 폴링으로 보류.
    if (benchLayer?.querySelector('.custom-select.is-open')) return 'select-open';
    return null;
  }

  function flushDeferredBenchRender() {
    const scheduledEpoch = benchRenderEpoch;
    benchDeferredTarget = null;
    globalThis.setTimeout(() => {
      if (!benchDeferredRender || benchRenderEpoch !== scheduledEpoch) return;
      renderBenchPreservingFocusedInput();
    }, 0);
  }

  function scheduleBenchDeferredRecheck() {
    if (benchDeferredPolling) return;
    benchDeferredPolling = true;
    const scheduledEpoch = benchRenderEpoch;
    globalThis.setTimeout(() => {
      benchDeferredPolling = false;
      if (!benchDeferredRender || benchRenderEpoch !== scheduledEpoch) return;
      renderBenchPreservingFocusedInput();
    }, 400);
  }

  function renderBenchPreservingFocusedInput() {
    const blocker = benchRenderBlocker();
    if (!blocker) {
      renderBench();
      return;
    }
    benchDeferredRender = true;
    if (blocker === 'select-open') {
      scheduleBenchDeferredRecheck();
      return;
    }
    if (benchDeferredTarget === blocker) return;
    benchDeferredTarget = blocker;
    blocker.addEventListener('blur', flushDeferredBenchRender, {once: true});
  }

  function bindBenchTagAssist() {
    if (!benchLayer) return;
    benchLayer.querySelectorAll([
      'textarea[data-field="bench-prompt"]',
      'textarea[data-field="bench-main"]',
      'textarea[data-field="bench-negative"]',
    ].join(', ')).forEach(element => bindTagAssist(element));
  }

  function ensureBenchLayer() {
    if (benchLayer) return benchLayer;
    benchLayer = document.createElement('div');
    benchLayer.className = 'char-bench-layer';
    document.body.append(benchLayer);
    benchLayer.addEventListener('click', event => {
      const button = event.target.closest('[data-action]');
      if (!button || button.disabled) return;
      const action = button.dataset.action;
      if (action === 'bench-close') closeBench();
      else if (action === 'bench-mode') {
        const nextMode = button.dataset.mode === 'char_reference' ? 'char_reference' : 'inpaint';
        if (nextMode !== benchMode) {
          benchMode = nextMode;
          renderBench();
        }
      }
      else if (action === 'bench-prompt-source') {
        const source = ['primary', 'current', 'preset'].includes(button.dataset.source)
          ? button.dataset.source
          : 'current';
        benchPromptSource = source;
        if (source === 'preset' && !benchPromptPreset) {
          benchPromptPreset = String(benchPromptProfiles.presets?.[0]?.name || '');
        }
        renderBench();
      }
      else if (action === 'bench-custom-open') openBenchCustomPanel();
      else if (action === 'bench-custom-close') {
        benchCustomOpen = false;
        renderBench();
      }
      else if (action === 'bench-custom-apply') applyBenchCustom();
      else if (action === 'bench-custom-fold') {
        if (benchCustomDraft) {
          const slot = String(button.dataset.slot || '');
          benchCustomDraft.fold[slot] = !benchCustomDraft.fold[slot];
          renderBench();
        }
      }
      else if (action === 'bench-custom-reset') {
        // 해제 = 일시 프로파일 폐기 후 표준 소스로 복귀(영구 저장이 없으므로
        // 되돌릴 것도 없다).
        benchCustom = null;
        benchCustomOpen = false;
        if (benchPromptSource === 'custom') {
          benchPromptSource = benchPromptProfiles.primary?.available ? 'primary' : 'current';
        }
        renderBench();
      }
      else if (action === 'bench-generate') benchGenerate();
      else if (action === 'bench-save') benchSave();
      else if (action === 'bench-enhance') benchEnhance();
      else if (action === 'bench-random-outfit') benchRandomOutfit();
      else if (action === 'bench-discard') benchDiscard();
      else if (action === 'bench-pick') {
        benchSelected = Number(button.dataset.index);
        renderBench();
      }
    });
    benchLayer.addEventListener('input', event => {
      const field = event.target.closest('[data-field]');
      if (!field) return;
      if (field.dataset.field === 'bench-prompt' && benchChar) benchChar.prompt = field.value;
      else if (field.dataset.field === 'bench-uc' && benchChar) benchChar.uc = field.value;
      else if (field.dataset.field === 'bench-main') benchFields[benchMode].main = field.value;
      else if (field.dataset.field === 'bench-negative') benchFields[benchMode].negative = field.value;
      else if (field.dataset.field === 'bench-prompt-preset') {
        // 미리보기는 콤보박스 플로팅 팝업이 담당 — 재렌더 불필요(셀렉트 파괴 방지).
        benchPromptPreset = String(field.value || '');
      }
      else if (field.dataset.field === 'bench-reference-type') {
        benchReferenceType = field.value === 'character' ? 'character' : 'character&style';
      }
      else if (field.dataset.field === 'bench-reference-strength') {
        benchReferenceStrength = Math.max(0, Math.min(1, Number(field.value) / 20));
        const value = benchLayer.querySelector('[data-role="bench-reference-strength-value"]');
        if (value) value.textContent = benchReferenceStrength.toFixed(2);
      }
      else if (field.dataset.field === 'bench-reference-fidelity') {
        benchReferenceFidelity = Math.max(0, Math.min(1, Number(field.value) / 20));
        const value = benchLayer.querySelector('[data-role="bench-reference-fidelity-value"]');
        if (value) value.textContent = benchReferenceFidelity.toFixed(2);
      }
      else if (field.dataset.field === 'bench-count') benchCount = Number(field.value) || 1;
      else if (benchCustomDraft && field.dataset.field === 'bench-custom-prefix') benchCustomDraft.prefix = field.value;
      else if (benchCustomDraft && field.dataset.field === 'bench-custom-postfix') benchCustomDraft.postfix = field.value;
      else if (benchCustomDraft && field.dataset.field === 'bench-custom-negative') benchCustomDraft.negative_prompt = field.value;
      else if (benchCustomDraft && field.dataset.field === 'bench-custom-cfg') benchCustomDraft.cfg_scale = field.value;
      else if (benchCustomDraft && field.dataset.field === 'bench-custom-rescale') benchCustomDraft.cfg_rescale = field.value;
      else if (benchCustomDraft && field.dataset.field === 'bench-custom-sampler') benchCustomDraft.sampler = String(field.value || '');
      else if (benchCustomDraft && field.dataset.field === 'bench-custom-scheduler') benchCustomDraft.scheduler = String(field.value || '');
      else if (benchCustomDraft && field.dataset.field === 'bench-custom-varplus') benchCustomDraft.varplus = !!field.checked;
    });
    return benchLayer;
  }

  async function refreshBenchDefaultsAndProfiles(characterId) {
    // PRIMARY/PRESET 프로파일 재조회 + 소스 유효성 재검증. fast path 재오픈에서도
    // 항상 호출된다 - 닫힌 사이 프리셋 삭제/승격으로 stale 400이 나가면 안 된다
    // (Codex BLOCK). 변경 여부를 반환해 불필요한 재렌더를 피한다.
    const before = JSON.stringify(benchPromptProfiles)
      + `|${benchPromptSource}|${benchPromptPreset}|${benchDefaultsLoaded}`;
    try {
      const defaults = await api(API.benchDefaults(characterId));
      // 캐릭터 전환 경합 가드(Codex BLOCK): A 벤치의 늦은 응답이 B의 프로파일을
      // 덮어쓰면 CUSTOM 시드까지 오염된다 - 완료 시점의 벤치 캐릭터로 검증.
      if (!benchChar || benchChar.id !== characterId) return false;
      if (!benchDefaultsLoaded) {
        for (const mode of ['inpaint', 'char_reference']) {
          const block = defaults?.[mode];
          if (block && typeof block === 'object') {
            benchFields[mode].main = String(block.main_prompt || '');
            benchFields[mode].negative = String(block.extra_negative || '');
          }
        }
        // 구버전 flat 응답 호환
        if (typeof defaults?.main_prompt === 'string') {
          benchFields.inpaint.main = defaults.main_prompt;
          benchFields.inpaint.negative = String(defaults.extra_negative || '');
        }
        benchDefaultsLoaded = true;
      }
      const profiles = defaults?.prompt_profiles;
      if (profiles && typeof profiles === 'object') {
        benchPromptProfiles = {
          primary: profiles.primary || null,
          current: profiles.current || null,
          presets: Array.isArray(profiles.presets) ? profiles.presets : [],
        };
        if (benchPromptProfileCharacterId !== characterId) {
          benchPromptProfileCharacterId = characterId;
          benchPromptSource = benchPromptProfiles.primary?.available ? 'primary' : 'current';
          benchPromptPreset = String(benchPromptProfiles.presets[0]?.name || '');
        } else if (
          benchPromptPreset
          && !benchPromptProfiles.presets.some(profile => profile.name === benchPromptPreset)
        ) {
          benchPromptPreset = String(benchPromptProfiles.presets[0]?.name || '');
        }
        // 선택 소스가 무효해졌으면 폴백 (프리셋 전부 삭제 / primary 피벗 소실)
        if (benchPromptSource === 'primary' && !benchPromptProfiles.primary?.available) {
          benchPromptSource = 'current';
        }
        if (benchPromptSource === 'preset' && !benchPromptProfiles.presets.length) {
          benchPromptSource = 'current';
        }
        if (benchPromptSource === 'preset' && !benchPromptPreset) {
          benchPromptPreset = String(benchPromptProfiles.presets[0]?.name || '');
        }
      }
    } catch (error) {
      console.error('bench defaults/profile load failed', error);
      return false;
    }
    return (
      JSON.stringify(benchPromptProfiles)
      + `|${benchPromptSource}|${benchPromptPreset}|${benchDefaultsLoaded}`
    ) !== before;
  }

  async function openBench() {
    if (!detail || !detail.recovered) {
      showToast('캐릭터 프롬프트를 복구할 수 없는 에셋입니다', 'error');
      return;
    }
    if (benchChar && benchChar.id === detail.id && benchLayer?.childElementCount) {
      // 동일 캐릭터 재오픈: 유지된 DOM을 즉시 다시 노출(입력·후보 복원)하되,
      // 프로파일은 백그라운드로 재조회해 변경 시에만 조용히 재렌더.
      benchOpen = true;
      benchChar.name = summaryName({id: detail.id, display_name: detail.display_name});
      const revisionChanged = (detail.revision || 0) !== benchChar.revision;
      if (revisionChanged) benchChar.revision = detail.revision || 0;
      if (revisionChanged) renderBench();
      else benchLayer.hidden = false;
      refreshBenchDefaultsAndProfiles(benchChar.id).then(changed => {
        if (changed && benchChar) renderBenchPreservingFocusedInput();
      });
      return;
    }
    if (benchChar && benchChar.id !== detail.id) {
      if (benchCandidates.some(candidate => candidate.status === 'pending')) {
        // 진행 중 배치의 request_id를 버리면 이미 과금된 결과가 미아가 된다 -
        // 전환을 막고 기존 캐릭터의 벤치를 다시 연다.
        showToast('진행 중인 생성 배치가 있어 캐릭터 전환이 불가합니다 - 기존 벤치를 엽니다', 'warning');
        benchOpen = true;
        renderBench();
        return;
      }
      // 다른 캐릭터로 전환 - 종료된 배치 상관관계는 폐기
      benchCandidates = [];
      benchSelected = -1;
      benchRequestId = '';
      outfitOwned = [];
      // CUSTOM은 캐릭터(시드 프로파일)에 결부된 일시값 - 함께 폐기
      benchCustom = null;
      benchCustomDraft = null;
      benchCustomOpen = false;
      if (benchPromptSource === 'custom') benchPromptSource = 'primary';
    }
    benchChar = {
      id: detail.id,
      name: summaryName({id: detail.id, display_name: detail.display_name}),
      prompt: String(detail.character_prompt || ''),
      uc: String(detail.character_uc || ''),
      revision: detail.revision || 0,
    };
    await refreshBenchDefaultsAndProfiles(detail.id);
    benchOpen = true;
    renderBench();
  }

  function closeBench() {
    // DOM을 파기하지 않는다 - 다른 id의 캐릭터를 새로 띄울 때만 재구축.
    benchOpen = false;
    const pendingSync = benchDeferredRender;
    benchRenderEpoch += 1;
    benchDeferredRender = false;
    benchDeferredTarget = null;
    if (pendingSync && benchChar) renderBench();
    else if (benchLayer) benchLayer.hidden = true;
  }

  async function benchGenerate() {
    if (benchBusy || !benchChar) return;
    if (!isNai()) {
      showToast('바리에이션 생성은 NAI 모드 전용입니다', 'error');
      return;
    }
    if (benchCandidates.some(candidate => candidate.status === 'pending')) {
      showToast('이전 생성 배치가 아직 진행 중입니다', 'error');
      return;
    }
    const prompt = String(benchChar.prompt || '').trim();
    if (!prompt) {
      showToast('캐릭터 프롬프트를 입력하세요', 'error');
      return;
    }
    benchBusy = true;
    const count = Math.max(1, Math.min(GENERATE_MAX, Number(benchCount) || 1));
    const requestId = newRequestId();
    benchRequestId = requestId;
    // Completed candidates are a working history for this bench. Append each
    // new batch instead of replacing the strip; requestCandidate remains the
    // server correlation index while index is stable across all batches.
    benchCandidates = appendBenchCandidateBatch(
      benchCandidates, count, requestId, benchMode
    );
    benchSelected = -1;
    renderBench();
    try {
      const result = await postJson(API.benchGenerate, {
        id: benchChar.id,
        generation_mode: benchMode,
        reference_type: benchReferenceType,
        reference_strength: benchReferenceStrength,
        reference_fidelity: benchReferenceFidelity,
        prompt_source: benchPromptSource,
        prompt_preset: benchPromptSource === 'preset' ? benchPromptPreset : '',
        // CUSTOM은 저장소가 없다 - 적용 스냅샷을 요청에 실어 보낸다(일시 적용).
        ...(benchPromptSource === 'custom' && benchCustom ? {custom_profile: benchCustom} : {}),
        character_prompt: prompt,
        character_uc: String(benchChar.uc || '').trim(),
        main_prompt: benchFields[benchMode].main,
        extra_negative: benchFields[benchMode].negative,
        count,
        request_id: requestId,
      });
      const accepted = new Set(result?.accepted || []);
      (result?.rejected || []).forEach(rejection => {
        const candidate = findBenchRequestCandidate(
          benchCandidates, requestId, rejection?.candidate
        );
        if (candidate) {
          candidate.status = 'error';
          candidate.message = String(rejection?.message || rejection?.reason || 'rejected');
        }
      });
      if (!accepted.size) showToast('생성 요청이 큐에 들어가지 못했습니다', 'error');
      else showToast(`바리에이션 생성 ${accepted.size}건 요청됨`, 'success');
    } catch (error) {
      benchCandidates.forEach(candidate => {
        if (candidate.status === 'pending') {
          candidate.status = 'error';
          candidate.message = error.message;
        }
      });
      showToast(`생성 요청 실패: ${error.message}`, 'error');
    }
    benchBusy = false;
    renderBench();
  }

  function benchSelectedCandidate() {
    return benchCandidates.find(candidate => candidate.index === benchSelected) || null;
  }

  function markCandidateExpiredFromError(candidate, error) {
    // 404 = 리스 밖으로 밀려난 후보. 버튼 disable만으로는 stale DOM 클릭이나
    // 다른 호출 경로를 막지 못하므로 실패 응답에서 상태를 확정한다.
    if (!/404|not found|evicted/i.test(String(error?.message || ''))) return false;
    candidate.status = 'expired';
    candidate.message = '히스토리에서 만료됨 - 저장할 수 없습니다';
    return true;
  }

  async function benchSaveCandidate(candidate) {
    // 상태 계약을 저장 함수 자체에서 강제한다(렌더된 버튼 상태에 의존 금지).
    if (!candidate?.historyId || candidate.saved || !benchChar) return;
    if (candidate.status !== 'done') {
      showToast(
        candidate.status === 'expired'
          ? '히스토리에서 만료된 후보는 저장할 수 없습니다'
          : '완료된 후보만 저장할 수 있습니다',
        'error',
      );
      return;
    }
    benchBusy = true;
    renderBench();
    try {
      await postJson(API.benchSave, {id: benchChar.id, history_id: candidate.historyId});
      candidate.saved = true;
      showToast(candidate.mode === 'enhance' ? 'Enhance 저장 완료' : '바리에이션으로 저장됨', 'success');
      refreshAll().catch(() => {});
    } catch (error) {
      markCandidateExpiredFromError(candidate, error);
      showToast(`바리에이션 저장 실패: ${error.message}`, 'error');
    }
    benchBusy = false;
    renderBench();
  }

  async function benchSave() {
    if (benchBusy) return;
    await benchSaveCandidate(benchSelectedCandidate());
  }

  async function benchRandomOutfit() {
    // 어휘 판정(clothes_list - HEAD_NECK_FACE)은 백엔드에만 있으므로 프롬프트를
    // 보내고 교체된 결과를 받는다. 생성 벤치의 슬롯과 같은 소유권 규칙.
    if (outfitBusy || !benchChar) return;
    outfitBusy = true;
    renderBench();
    try {
      const result = await postJson(API.randomOutfit, {
        prompt: String(benchChar.prompt || ''),
        owned: outfitOwned,
      });
      benchChar.prompt = String(result?.prompt || benchChar.prompt);
      outfitOwned = Array.isArray(result?.outfit) ? result.outfit : [];
    } catch (error) {
      showToast(`의상 랜덤 실패: ${error.message}`, 'error');
    }
    outfitBusy = false;
    renderBench();
  }

  async function benchEnhance() {
    // Dev0714 "Save with Enhance"의 Enhance 패스만: 인페인트 후보를 crop ->
    // NAI img2img 1패스(0.3/0.0/1.5x) -> 새 후보로 적재. 저장 여부는 사용자가
    // 결과를 보고 결정한다. 한 번에 하나만(배치 pending 중 불가).
    const source = benchSelectedCandidate();
    if (!source?.historyId || source.mode !== 'inpaint' || benchBusy || !benchChar) return;
    if (source.status !== 'done') {
      showToast('완료된 인페인트 후보만 Enhance할 수 있습니다', 'error');
      return;
    }
    if (benchCandidates.some(candidate => candidate.status === 'pending')) return;
    if (!isNai()) {
      showToast('Enhance는 NAI 모드 전용입니다', 'error');
      return;
    }
    benchBusy = true;
    const requestId = newRequestId();
    benchRequestId = requestId;
    benchCandidates = appendBenchCandidateBatch(benchCandidates, 1, requestId, 'enhance');
    const pendingCandidate = benchCandidates[benchCandidates.length - 1];
    // 결과 도착 시 사용자가 아직 원본 후보를 보고 있으면 결과로 옮겨준다
    // (다른 후보로 이동했다면 방해하지 않는다).
    pendingCandidate.enhanceSource = source.index;
    renderBench();
    try {
      await postJson(API.benchEnhance, {
        id: benchChar.id,
        history_id: source.historyId,
        request_id: requestId,
      });
    } catch (error) {
      pendingCandidate.status = 'error';
      pendingCandidate.message = String(error.message || 'enhance failed');
      showToast(`Enhance 실패: ${error.message}`, 'error');
    }
    benchBusy = false;
    renderBench();
  }

  function benchDiscard() {
    const position = benchCandidates.findIndex(candidate => candidate.index === benchSelected);
    if (position < 0) return;
    benchCandidates.splice(position, 1);
    const nextDone = benchCandidates.find(candidate => candidate.status === 'done');
    benchSelected = nextDone ? nextDone.index : -1;
    renderBench();
  }

  function benchCropImg(historyId) {
    // 1152x896 캔버스 결과에서 512x896 편집영역(576..1088)만 CSS로 크롭 표시.
    // 컨테이너 폭 W 기준: 이미지 폭 = 1152/512 * W = 2.25W, 좌측 오프셋 = 576/512 * W.
    return `
      <div class="char-bench-crop">
        <img src="${API.historyImage(historyId)}" alt="">
      </div>
    `;
  }

  function benchResultImg(candidate) {
    // char_reference/enhance 결과는 이미 완성본(768x1344) - 크롭 없이 그대로 표시.
    if (candidate?.mode === 'char_reference' || candidate?.mode === 'enhance') {
      return `
        <div class="char-bench-crop plain">
          <img class="char-bench-plain-img" src="${API.historyImage(candidate.historyId)}" alt="">
        </div>
      `;
    }
    return benchCropImg(candidate.historyId);
  }

  function selectedBenchProfile() {
    if (benchPromptSource === 'custom') return benchCustom;
    if (benchPromptSource === 'primary') return benchPromptProfiles.primary;
    if (benchPromptSource === 'preset') {
      return benchPromptProfiles.presets.find(profile => profile.name === benchPromptPreset) || null;
    }
    return benchPromptProfiles.current;
  }

  // NAI 공식 UI 순서. ⚠️ 백엔드 core/nai_model_contract.NAI_SAMPLER_OPTIONS 와
  // **같은 목록이어야 한다** - tests/test_nai_sampler_options.py 가 어긋나면 잡는다.
  const NAI_SAMPLER_OPTIONS = ['k_euler_ancestral', 'k_euler', 'k_dpmpp_2s_ancestral', 'k_dpmpp_2m_sde', 'k_dpmpp_2m', 'k_dpmpp_sde', 'ddim'];
  const NAI_SCHEDULER_OPTIONS = ['karras', 'native', 'exponential', 'polyexponential'];

  function openBenchCustomPanel() {
    // 시드 = 마지막 적용 CUSTOM(재편집) 또는 현재 선택 프로파일. 빈 값은
    // "세션 값 상속"을 뜻하므로 그대로 빈 채 둔다.
    const seed = benchCustom
      || (benchPromptSource === 'custom' ? benchPromptProfiles.current : selectedBenchProfile())
      || benchPromptProfiles.current
      || {};
    const params = seed.params || {};
    benchCustomDraft = {
      // 프롬프트 3슬롯은 기본 접힘 - 패널 공간 확보(사용자 지시). 값은 draft에
      // 살아 있으므로 접혀 있어도 적용에 그대로 실린다.
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
    benchCustomOpen = true;
    renderBench();
  }

  function applyBenchCustom() {
    const draft = benchCustomDraft;
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
    benchCustom = {
      prefix: draft.prefix.trim(),
      postfix: draft.postfix.trim(),
      negative_prompt: draft.negative_prompt,
      cr_capable: draft.cr_capable,
      params,
    };
    benchPromptSource = 'custom';
    benchCustomOpen = false;
    showToast('CUSTOM 프로파일 적용됨 - 이 벤치의 생성에만 일시적으로 유효합니다', 'success');
    renderBench();
  }

  function renderCustomPromptSlot(fieldPrefix, slot, label, draft) {
    // 접힘 상태에서도 값은 draft에 살아 있다 - textarea를 DOM에서 떼어 공간 확보.
    const value = slot === 'negative' ? draft.negative_prompt : draft[slot];
    const open = !!draft.fold?.[slot];
    const items = String(value || '').split(',').map(part => part.trim()).filter(Boolean).length;
    return `
      <button class="char-bench-custom-fold ${open ? 'open' : ''}"
        data-action="bench-custom-fold" data-slot="${slot}">
        <span>${open ? '&#9662;' : '&#9656;'} ${label}</span>
        <span class="char-bench-custom-fold-count">${items ? `${items} 항목` : '비어 있음'}</span>
      </button>
      ${open ? `
        <textarea class="mod-textarea ${slot === 'negative' ? 'mod-uc char-bench-custom-ta-sm' : 'char-bench-custom-ta'}"
          data-field="${fieldPrefix}-${slot}">${escHtml(value || '')}</textarea>
      ` : ''}
    `;
  }

  function renderBenchCustomPanel() {
    if (!benchCustomOpen || !benchCustomDraft) return '';
    const draft = benchCustomDraft;
    const samplerOptions = [...new Set([draft.sampler, ...NAI_SAMPLER_OPTIONS])].filter(Boolean);
    const schedulerOptions = [...new Set([draft.scheduler, ...NAI_SCHEDULER_OPTIONS])].filter(Boolean);
    const selectOptions = (options, value) => ['', ...options].map(option => `
      <option value="${escAttr(option)}" ${option === value ? 'selected' : ''}>${option ? escHtml(option) : '(세션 값 상속)'}</option>
    `).join('');
    return `
      <div class="char-bench-custom-panel">
        <div class="char-bench-float-panel-head">CUSTOM - 세부 프리셋 설정
          <button class="module-popup-icon-btn" data-action="bench-custom-close" aria-label="닫기">x</button></div>
        ${renderCustomPromptSlot('bench-custom', 'prefix', 'PREFIX (pre prompt)', draft)}
        ${renderCustomPromptSlot('bench-custom', 'postfix', 'POSTFIX (post prompt)', draft)}
        ${renderCustomPromptSlot('bench-custom', 'negative', 'NEGATIVE (추가 Negative는 뒤에 이어붙음)', draft)}
        <div class="char-bench-custom-grid">
          <label>CFG Scale
            <input type="number" step="0.1" min="0" max="30" placeholder="상속"
              value="${escAttr(String(draft.cfg_scale ?? ''))}" data-field="bench-custom-cfg"></label>
          <label>CFG Rescale
            <input type="number" step="0.05" min="0" max="1" placeholder="상속"
              value="${escAttr(String(draft.cfg_rescale ?? ''))}" data-field="bench-custom-rescale"></label>
          <label>Sampler
            <select class="mod-select-sm" data-field="bench-custom-sampler">${selectOptions(samplerOptions, draft.sampler)}</select></label>
          <label>Scheduler
            <select class="mod-select-sm" data-field="bench-custom-scheduler">${selectOptions(schedulerOptions, draft.scheduler)}</select></label>
          <label class="mod-checkbox-item char-bench-custom-varplus">
            <input type="checkbox" ${draft.varplus ? 'checked' : ''} data-field="bench-custom-varplus">
            <span class="mod-checkbox-label">VAR+ (Variety)</span></label>
        </div>
        <div class="char-bench-custom-model">Model: ${escHtml(draft.model || '(라이브 모델 상속)')} <span>- 출력 전용</span></div>
        <div class="char-bench-custom-hint">빈 값은 세션 값을 상속합니다. 적용은 일시적이며 영구 변경은 원본 이미지를 교체해야 합니다.</div>
        <div class="char-bench-custom-actions">
          <button class="mod-btn-sm mod-btn-encode" data-action="bench-custom-apply">CUSTOM에 적용</button>
          ${benchCustom ? '<button class="mod-btn-sm" data-action="bench-custom-reset">CUSTOM 해제</button>' : ''}
        </div>
      </div>
    `;
  }

  function renderBenchPromptProfile() {
    const primaryAvailable = !!benchPromptProfiles.primary?.available;
    const presetAvailable = benchPromptProfiles.presets.length > 0;
    // Quick Preset 미리보기 스펙 공유: data-preview-kind="prompt-preset"이면
    // customSelects가 콤보박스를 연 동안에만 우측 플로팅 미리보기(썸네일+PREFIX)를
    // 띄운다(z 10110 — 벤치 모달 9000 위). 인라인 미리보기는 두지 않는다.
    const presetOptions = benchPromptProfiles.presets.map(profile => `
      <option value="${escAttr(profile.name)}" ${profile.name === benchPromptPreset ? 'selected' : ''}
        data-preview-name="${escAttr(profile.name)}"
        data-preview-mode="NAI"
        data-preview-prefix="${escAttr(profile.prefix || '')}"
        data-preview-description="${escAttr(profile.description || '')}"
        data-preview-thumbnail="${escAttr(profile.thumbnail_url || '')}">${escHtml(profile.name)}</option>
    `).join('');
    return `
      <div class="mod-section-label">프롬프트 엔지니어링 모듈 프리셋</div>
      <div class="char-bench-profile-toggle">
        <button class="char-bench-profile-btn ${benchPromptSource === 'primary' ? 'active' : ''}"
          data-action="bench-prompt-source" data-source="primary"
          ${primaryAvailable ? '' : `disabled title="${escAttr(benchPromptProfiles.primary?.reason || 'PRIMARY 메타데이터 없음')}"`}>PRIMARY</button>
        <button class="char-bench-profile-btn ${benchPromptSource === 'current' ? 'active' : ''}"
          data-action="bench-prompt-source" data-source="current">CURRENT</button>
        <button class="char-bench-profile-btn ${benchPromptSource === 'preset' ? 'active' : ''}"
          data-action="bench-prompt-source" data-source="preset"
          ${presetAvailable ? '' : 'disabled title="NAI Quick Preset 없음"'}>PRESET</button>
      </div>
      ${benchPromptSource === 'preset' ? `
        <select class="mod-select char-bench-preset-select" data-field="bench-prompt-preset"
          data-preview-kind="prompt-preset">${presetOptions}</select>
      ` : ''}
      <button class="char-bench-custom-btn ${benchPromptSource === 'custom' ? 'active' : ''}"
        data-action="bench-custom-open"
        title="선택한 프로파일을 시드로 PREFIX/POSTFIX/CFG/샘플러 등을 일시 수정합니다 (영구 저장 없음)">
        CUSTOM : 세부 프리셋 설정값 수정 &gt;${benchPromptSource === 'custom' ? ' (적용 중)' : ''}</button>
    `;
  }

  function renderBench() {
    benchRenderEpoch += 1;
    benchDeferredRender = false;
    benchDeferredTarget = null;
    const layer = ensureBenchLayer();
    if (!benchChar) {
      layer.innerHTML = '';
      layer.hidden = true;
      return;
    }
    // X로 닫힌 동안에도 DOM은 유지(hidden)하고 상태 변화를 계속 반영한다 -
    // 동일 캐릭터 재오픈 시 입력/후보/스크롤이 그대로 복원되도록.
    layer.hidden = !benchOpen;
    // innerHTML 전면 교체는 스크롤을 0으로 되돌린다 - 후보 선택/결과 도착마다
    // 스트립과 좌측 폼이 맨 위로 튀지 않도록 위치를 보존한다.
    const keepScroll = {
      strip: layer.querySelector('.char-bench-strip-body')?.scrollTop || 0,
      form: layer.querySelector('.char-bench-form-scroll')?.scrollTop || 0,
    };
    const nai = isNai();
    const pendingCount = benchCandidates.filter(candidate => candidate.status === 'pending').length;
    const selected = benchSelectedCandidate();
    // 최신 후보가 위로 오도록 역순 나열(index는 상관관계용이라 순서와 무관).
    const strip = [...benchCandidates].reverse().map(candidate => {
      const badge = benchModeBadge(candidate.mode);
      const badgeHtml = badge
        ? `<span class="char-bench-mode-badge mode-${escAttr(candidate.mode)}">${badge}</span>`
        : '';
      if (candidate.status === 'pending') {
        return `<div class="char-bench-thumb pending">${candidate.mode === 'enhance' ? 'Enhance 중...' : '생성 중...'}${badgeHtml}</div>`;
      }
      if (candidate.status === 'error') {
        return `<div class="char-bench-thumb error" title="${escAttr(candidate.message)}">실패${badgeHtml}</div>`;
      }
      if (candidate.status === 'expired') {
        return `<div class="char-bench-thumb error" title="${escAttr(candidate.message)}">만료됨${badgeHtml}</div>`;
      }
      return `
        <button class="char-bench-thumb done ${candidate.index === benchSelected ? 'selected' : ''} ${candidate.saved ? 'saved' : ''}"
          data-action="bench-pick" data-index="${candidate.index}">
          ${benchResultImg(candidate)}
          ${badgeHtml}
          ${candidate.saved ? '<span class="char-bench-saved-badge">저장됨</span>' : ''}
        </button>
      `;
    }).join('');
    layer.innerHTML = `
      <div class="char-bench-backdrop"></div>
      <div class="char-bench" role="dialog" aria-label="바리에이션 제작 벤치">
        <header class="char-bench-header">
          <img class="char-bench-head-thumb" src="${API.thumb(benchChar.id, benchChar.revision)}" alt="">
          <div class="char-bench-title">바리에이션 제작 - ${escHtml(benchChar.name)}
            <span class="char-asset-detail-id">${escHtml(benchChar.id)}</span></div>
          <button class="module-popup-icon-btn" data-action="bench-close" aria-label="닫기">x</button>
        </header>
        <div class="char-bench-body">
          <section class="char-bench-form">
            <div class="char-bench-form-scroll">
              <div class="char-bench-random-island">
                <div class="mod-section-label">랜덤 슬롯</div>
                <div class="char-bench-random-row">
                  <span class="char-bench-random-hint">의상만 교체 (외형·머리 장식 유지)</span>
                  <button class="mod-btn-sm mod-btn-encode char-bench-random-btn" data-action="bench-random-outfit"
                    ${outfitBusy ? 'disabled' : ''}
                    title="기존 의상 태그를 걷어내고 새 의상을 굴립니다 - 외형/머리 장식은 남습니다">${outfitBusy ? '...' : '의상 랜덤'}</button>
                </div>
              </div>
              <div class="mod-section-label">Character Prompt (의상/악세서리/디테일)</div>
              <textarea class="mod-textarea char-bench-ta" data-field="bench-prompt">${escHtml(benchChar.prompt)}</textarea>
              <div class="mod-section-label">Character UC</div>
              <textarea class="mod-textarea mod-uc char-bench-ta-sm" data-field="bench-uc">${escHtml(benchChar.uc)}</textarea>
              <div class="mod-section-label">Generation Mode</div>
              <div class="char-bench-mode-toggle">
                <button class="char-bench-mode-btn ${benchMode === 'inpaint' ? 'active' : ''}"
                  data-action="bench-mode" data-mode="inpaint">1/2 Inpaint</button>
                <button class="char-bench-mode-btn ${benchMode === 'char_reference' ? 'active' : ''}"
                  data-action="bench-mode" data-mode="char_reference">Char Reference</button>
              </div>
              ${benchMode === 'char_reference' && selectedBenchProfile()?.cr_capable === false
                ? '<div class="mod-notice">선택한 프로파일이 NAI 4.5가 아닌 모델을 강제합니다 - Char Reference 생성이 거부됩니다</div>'
                : ''}
              ${benchMode === 'char_reference' ? `
                <div class="mod-section-label">Reference Type (NAIA)</div>
                <select class="mod-select" data-field="bench-reference-type">
                  <option value="character&style" ${benchReferenceType === 'character&style' ? 'selected' : ''}>Char & Style</option>
                  <option value="character" ${benchReferenceType === 'character' ? 'selected' : ''}>Character</option>
                </select>
                <div class="mod-slider-row">
                  <span class="mod-slider-label">Strength</span>
                  <input type="range" min="0" max="20" step="1"
                    value="${Math.round(benchReferenceStrength * 20)}" data-field="bench-reference-strength">
                  <span class="mod-slider-value" data-role="bench-reference-strength-value">${benchReferenceStrength.toFixed(2)}</span>
                </div>
                <div class="mod-slider-row">
                  <span class="mod-slider-label">Fidelity</span>
                  <input type="range" min="0" max="20" step="1"
                    value="${Math.round(benchReferenceFidelity * 20)}" data-field="bench-reference-fidelity">
                  <span class="mod-slider-value" data-role="bench-reference-fidelity-value">${benchReferenceFidelity.toFixed(2)}</span>
                </div>
              ` : ''}
              ${renderBenchPromptProfile()}
              <div class="mod-section-label">Main Prompt ${benchMode === 'char_reference' ? '(자세/배경 - 모드별 별도 저장)' : '(자세/배경만)'}</div>
              <textarea class="mod-textarea char-bench-ta-sm" data-field="bench-main">${escHtml(benchFields[benchMode].main)}</textarea>
              <div class="mod-section-label">추가 Negative (메인 네거티브에 이어붙임)</div>
              <textarea class="mod-textarea mod-uc char-bench-ta-sm" data-field="bench-negative">${escHtml(benchFields[benchMode].negative)}</textarea>
              <div class="char-asset-count">${benchMode === 'char_reference'
                ? 'Char Reference: 원본(A) late-binding / 768x1344 / {1girl|1boy} + PREFIX + MAIN + solo·자세 스캐폴드 + POSTFIX'
                : '인페인트 고정: strength 1.0 / noise 0.0 / 좁은 마스크(512x896) / {1girl|1boy} + MAIN + PREFIX + solo·자세 스캐폴드 + POSTFIX'}</div>
            </div>
            <div class="char-bench-form-footer">
              <div class="char-bench-gen-row">
                <label class="char-asset-gen-count">횟수
                  <input type="number" min="1" max="${GENERATE_MAX}" value="${Number(benchCount) || 1}" data-field="bench-count">
                </label>
                <button class="mod-btn-sm mod-btn-encode char-bench-generate-btn" data-action="bench-generate"
                  ${nai && !benchBusy && !pendingCount ? '' : 'disabled'}
                  ${nai ? '' : 'title="NAI 모드 전용"'}>${pendingCount ? `생성 중... (${pendingCount})` : '바리에이션 생성'}</button>
              </div>
            </div>
          </section>
          <section class="char-bench-compare">
            <div class="char-bench-pane">
              <div class="mod-section-label">원본 (A)</div>
              <div class="char-bench-fit">
                <div class="char-bench-a"><img src="${API.image(benchChar.id, '', benchChar.revision)}" alt=""></div>
                ${renderBenchCustomPanel()}
              </div>
            </div>
            <div class="char-bench-pane">
              <div class="mod-section-label">생성 결과 (B)</div>
              <div class="char-bench-fit">
                ${selected?.historyId
                  ? benchResultImg(selected)
                  : '<div class="char-bench-crop empty"><div class="mod-empty">생성된 결과가 여기 표시됩니다.</div></div>'}
              </div>
              <div class="char-bench-save-row">
                <button class="mod-btn-sm mod-btn-encode char-bench-save-btn" data-action="bench-save"
                  ${selected?.historyId && !selected.saved && !benchBusy && selected.status !== 'expired' ? '' : 'disabled'}
                  ${selected?.status === 'expired' ? 'title="히스토리에서 만료됨 - 저장 불가"' : ''}>
                  ${selected?.saved ? '저장됨' : (selected?.status === 'expired' ? '만료됨' : '바리에이션으로 저장')}</button>
                ${selected?.mode === 'inpaint' ? `
                  <button class="mod-btn-sm mod-btn-encode char-bench-enhance-btn" data-action="bench-enhance"
                    ${nai && selected?.historyId && !benchBusy && !pendingCount && selected.status !== 'expired' ? '' : 'disabled'}
                    title="NAI img2img 1패스(0.3/1.5x)로 768x1344 선명화 - 결과는 새 후보로 추가${nai ? '' : ' (NAI 모드 전용)'}">✨ Enhance</button>
                ` : ''}
                <button class="mod-btn-sm" data-action="bench-discard" ${selected ? '' : 'disabled'}>버리기</button>
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
    const stripBody = layer.querySelector('.char-bench-strip-body');
    if (stripBody) stripBody.scrollTop = keepScroll.strip;
    const formScroll = layer.querySelector('.char-bench-form-scroll');
    if (formScroll) formScroll.scrollTop = keepScroll.form;
    // renderBench() replaces every textarea. Re-bind the shared Tag Assist to
    // positive prompts and the main negative field; Character UC follows the
    // existing Character/Img2Img convention and stays unbound.
    bindBenchTagAssist();
  }

  // ---------------------------------------------------------------- staging

  function stageFromContext(context = {}) {
    // The caller must pin a stable path (history rel_path or saved rel_path) at
    // click time - a floating "current result" reference could save a different
    // image if a new result lands before the user picks a save target.
    const path = String(context?.path || '');
    if (!path) {
      showToast('저장할 이미지를 특정할 수 없습니다', 'error');
      return;
    }
    staged = {source: {kind: 'viewer', rel_path: path}, label: String(context?.label || path)};
    creationBench?.close();
    render();
  }

  // --------------------------------------------------------------- rendering

  function renderStagedBanner() {
    if (!staged) return '';
    const variationDisabled = !selectedId ? 'disabled' : '';
    return `
      <div class="char-asset-banner">
        <div class="char-asset-banner-label">저장 대기: ${escHtml(staged.label)}</div>
        <div class="char-asset-banner-actions">
          <button class="mod-btn-sm" data-action="staged-new" ${busy ? 'disabled' : ''}>새 캐릭터로 저장</button>
          <button class="mod-btn-sm" data-action="staged-variation" ${variationDisabled || (busy ? 'disabled' : '')}
            title="${selectedId ? '' : '갤러리에서 대상 캐릭터를 먼저 선택하세요'}">선택 캐릭터의 바리에이션으로</button>
          <button class="mod-btn-sm" data-action="staged-cancel">취소</button>
        </div>
      </div>
    `;
  }

  function renderGrid() {
    const cards = characters.map(entry => `
      <button class="char-asset-card ${entry.id === selectedId ? 'selected' : ''}" data-action="select" data-id="${escAttr(entry.id)}">
        <img class="char-asset-card-img" loading="lazy" src="${API.thumb(entry.id, entry.revision)}" alt="">
        <span class="char-asset-card-name">${escHtml(summaryName(entry))}</span>
        <span class="char-asset-card-count">${entry.variation_count ? `+${entry.variation_count}` : ''}</span>
      </button>
    `).join('');
    return `
      <div class="char-asset-toolbar">
        <button class="mod-btn-sm char-asset-create-btn" data-action="open-create">+ 캐릭터 생성</button>
        <button class="mod-btn-sm" data-action="refresh">↻</button>
        <span class="char-asset-count">${characters.length} characters</span>
      </div>
      <div class="char-asset-grid">
        ${loading ? '<div class="mod-empty">Loading...</div>' : (cards || '<div class="mod-empty">저장된 캐릭터 에셋이 없습니다. 결과 이미지 우클릭 → "캐릭터 에셋으로 저장" 또는 표준 레퍼런스 생성으로 시작하세요.</div>')}
      </div>
    `;
  }

  function renderVariationStrip() {
    if (!detail) return '';
    const primarySelected = !selectedVariation;
    const primary = `
      <button class="char-asset-var ${primarySelected ? 'selected' : ''}" data-action="select-variation" data-hash="">
        <img loading="lazy" src="${API.thumb(detail.id, detail.revision)}" alt="">
        <span class="char-asset-var-star">★</span>
      </button>
    `;
    const variations = (detail.variations || []).map(variation => `
      <button class="char-asset-var ${variation.hash === selectedVariation ? 'selected' : ''}"
        data-action="select-variation" data-hash="${escAttr(variation.hash)}">
        <img loading="lazy" src="${API.variationThumb(detail.id, variation.hash, variation.revision)}" alt="">
      </button>
    `).join('');
    return `<div class="char-asset-var-strip">${primary}${variations}</div>`;
  }

  function renderVariationsZone() {
    const variationDeleteArmed = deleteArmed === `variation:${selectedVariation}`;
    const benchDisabled = detail?.recovered ? '' : 'disabled title="캐릭터 프롬프트를 복구할 수 없는 에셋입니다"';
    return `
      ${renderVariationStrip()}
      <div class="char-asset-var-actions">
        <span ${selectedVariation ? '' : 'hidden'}>
          <button class="mod-btn-sm" data-action="promote">★ 대표로 승격</button>
          <button class="mod-btn-sm mod-btn-danger" data-action="delete-variation">
            ${variationDeleteArmed ? '한 번 더 클릭하면 삭제' : '바리에이션 삭제'}
          </button>
        </span>
        <button class="mod-btn-sm char-asset-bench-btn" data-action="open-bench" ${benchDisabled}>+ 바리에이션 추가</button>
      </div>
    `;
  }

  function renderDetail() {
    if (!selectedId) {
      return '<div class="mod-empty char-asset-detail-empty">캐릭터를 선택하세요.</div>';
    }
    if (detailLoading || !detail) {
      return '<div class="mod-empty char-asset-detail-empty">Loading...</div>';
    }
    const nai = isNai();
    const naiTitle = nai ? '' : 'title="NAI 모드 전용"';
    const naiDisabled = nai && !busy ? '' : 'disabled';
    const applyDisabled = detail.recovered ? naiDisabled : 'disabled';
    const applyTitle = detail.recovered ? naiTitle : 'title="이 이미지에는 NAI 캐릭터 블록이 없습니다"';
    const revision = detail.revision || 0;
    const charDeleteArmed = deleteArmed === `char:${selectedId}`;
    const entry = characters.find(item => item.id === selectedId);
    const editButton = promptEditOpen ? '' : `
      <button class="mod-btn-sm char-asset-edit-btn" data-action="prompt-edit" ${busy ? 'disabled' : ''}>[ EDIT ]</button>
    `;
    const promptContent = promptEditOpen ? `
      <textarea class="mod-textarea char-asset-edit-prompt" data-field="asset-prompt-edit"
        placeholder="character prompt...">${escHtml(promptDraft)}</textarea>
      <div class="mod-section-label">Character UC</div>
      <textarea class="mod-textarea mod-uc char-asset-edit-uc" data-field="asset-uc-edit"
        placeholder="character UC (optional)...">${escHtml(promptUcDraft)}</textarea>
      <div class="char-asset-prompt-edit-actions">
        <button class="mod-btn-sm mod-btn-encode" data-action="prompt-edit-save" ${busy ? 'disabled' : ''}>저장</button>
        <button class="mod-btn-sm" data-action="prompt-edit-cancel" ${busy ? 'disabled' : ''}>취소</button>
      </div>
    ` : `
      <pre class="char-asset-pre" data-role="prompt-pre">${escHtml(detail.character_prompt || '(empty)')}</pre>
      <div class="mod-section-label">Character UC</div>
      <pre class="char-asset-pre char-asset-pre-uc" data-role="uc-pre">${escHtml(detail.character_uc || '(empty)')}</pre>
    `;
    return `
      <div class="char-asset-detail-head" data-role="detail-head">
        <div class="char-asset-detail-name"><span data-role="detail-name">${escHtml(summaryName({...entry, display_name: detail.display_name}))}</span>
          <span class="char-asset-detail-id" data-role="detail-id">${escHtml(selectedId)}</span>
        </div>
        <div class="char-asset-detail-head-actions">
          <button class="mod-btn-sm" data-action="rename">이름변경</button>
          <button class="mod-btn-sm mod-btn-danger" data-action="delete-character" ${busy ? 'disabled' : ''}>
            ${charDeleteArmed ? '한 번 더 클릭하면 삭제' : '캐릭터 삭제'}
          </button>
        </div>
      </div>
      <div class="char-asset-preview">
        <img data-role="preview-img" src="${API.image(detail.id, selectedVariation, revision)}" alt="">
      </div>
      <div data-role="variations-zone">${renderVariationsZone()}</div>
      <div class="char-asset-prompt-block">
        <div class="char-asset-prompt-label-row">
          <div class="mod-section-label">Character Prompt <span data-role="prompt-scope">${selectedVariation ? '(바리에이션)' : '(대표)'}</span> <span class="char-asset-warn" data-role="recover-warn" ${detail.recovered ? 'hidden' : ''}>(복구 불가 - NAI 캐릭터 블록 없음)</span></div>
          ${editButton}
        </div>
        ${promptContent}
      </div>
      <div class="char-asset-apply-actions">
        <button class="mod-btn-sm mod-btn-encode" data-action="apply-c1" ${applyDisabled} ${applyTitle}>C1 적용 (단독)</button>
        <button class="mod-btn-sm mod-btn-encode" data-action="apply-c1-cr" ${applyDisabled} ${applyTitle}
          title="C1 슬롯 적용 + 이 이미지를 Character Reference로 등록 (해상도는 자동 정규화)">C1 + CR 적용</button>
        <button class="mod-btn-sm mod-btn-encode" data-action="apply-c1-inset" ${applyDisabled} ${applyTitle}
          title="C1 슬롯 적용 + 이 이미지를 레퍼런스 인셋(1152x896)으로 고정 - 기존 CR은 전부 비활성화">C1 + 레퍼런스 인셋 적용</button>
        <button class="mod-btn-sm" data-action="apply-add" ${applyDisabled} ${applyTitle}>새 슬롯으로 추가</button>
        <!-- 같은 캐릭터를 다른 옷으로 입힐 때 쓴다(사용자 지정). 인물 태그 + 캐릭터 특징
             + 악세서리/모자만 남기고 의상을 걷어낸다. UC 는 건드리지 않는다. -->
        <label class="char-asset-strip" data-naia-title="인물 태그 + 캐릭터 특징 + 악세서리/모자만 남기고 의상 태그를 뺍니다. UC 는 그대로 둡니다.">
          <input type="checkbox" data-action="toggle-strip"${stripOutfit ? ' checked' : ''}>
          <span>불러오기시 의상 제거</span>
        </label>
      </div>
    `;
  }

  function render() {
    if (!root) return;
    root.innerHTML = `
      <div class="char-asset-shell">
        ${renderStagedBanner()}
        <div class="char-asset-columns">
          <section class="char-asset-gallery">${renderGrid()}</section>
          <section class="char-asset-detail">${renderDetail()}</section>
        </div>
      </div>
    `;
    const editPrompt = root.querySelector('textarea[data-field="asset-prompt-edit"]');
    if (editPrompt) bindTagAssist(editPrompt);
  }

  // ---------------------------------------------------------------- events

  if (root) {
    root.addEventListener('click', event => {
      const button = event.target.closest('[data-action]');
      if (!button || button.disabled) return;
      const action = button.dataset.action;
      if (action === 'select') select(button.dataset.id || '');
      else if (action === 'select-variation') selectVariationInPlace(button.dataset.hash || '');
      else if (action === 'refresh') refreshAll();
      else if (action === 'open-create') openCreationBench();
      else if (action === 'staged-new') saveStaged({kind: 'new'});
      else if (action === 'staged-variation') saveStaged({kind: 'variation', character_id: selectedId});
      else if (action === 'staged-cancel') { staged = null; render(); }
      else if (action === 'apply-c1') applySlot('c1');
      else if (action === 'apply-c1-cr') applySlot('c1', true);
      else if (action === 'apply-c1-inset') applySlot('c1', false, true);
      else if (action === 'apply-add') applySlot('add_slot');
      else if (action === 'rename') renameSelected();
      else if (action === 'prompt-edit') beginPromptEdit();
      else if (action === 'prompt-edit-save') savePromptEdit();
      else if (action === 'prompt-edit-cancel') cancelPromptEdit();
      else if (action === 'delete-character') deleteSelected();
      else if (action === 'delete-variation') deleteSelectedVariation();
      else if (action === 'promote') promoteSelectedVariation();
      else if (action === 'open-bench') openBench();
    });
    root.addEventListener('change', event => {
      const box = event.target.closest('[data-action="toggle-strip"]');
      if (!box) return;
      stripOutfit = !!box.checked;
      try { globalThis.localStorage?.setItem(STRIP_OUTFIT_KEY, stripOutfit ? '1' : '0'); }
      catch (_) { /* 사생활 모드 */ }
    });
    root.addEventListener('input', event => {
      const field = event.target.closest('[data-field]');
      if (!field) return;
      if (field.dataset.field === 'asset-prompt-edit') promptDraft = field.value;
      else if (field.dataset.field === 'asset-uc-edit') promptUcDraft = field.value;
    });
  }

  return {
    setActive(next) {
      active = !!next;
      if (!active) disarmDelete();
    },
    load: () => load(false),
    handleResultMeta,
    handleGenerationError,
    handleHistoryRemoved,
    stageFromContext,
  };
}
