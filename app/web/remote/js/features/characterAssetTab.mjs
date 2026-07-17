// Character Asset tab — persistent image-based character library (web port of
// the desktop character asset storage, Dev0714). Gallery + detail + standard
// reference generation. Server state is the source of truth; the whole pane is
// re-rendered from fetched data and events are bound once via delegation.

const API = {
  list: '/api/character-asset/list',
  detail: id => `/api/character-asset/detail?id=${encodeURIComponent(id)}`,
  thumb: (id, revision) => `/api/character-asset/thumb?id=${encodeURIComponent(id)}&size=grid&v=${revision || 0}`,
  variationThumb: (id, hash, revision) =>
    `/api/character-asset/thumb?id=${encodeURIComponent(id)}&variation=${encodeURIComponent(hash)}&size=grid&v=${revision || 0}`,
  image: (id, hash, revision) =>
    `/api/character-asset/image?id=${encodeURIComponent(id)}${hash ? `&variation=${encodeURIComponent(hash)}` : ''}&v=${revision || 0}`,
  save: '/api/character-asset/save',
  apply: '/api/character-asset/apply',
  rename: '/api/character-asset/rename',
  remove: '/api/character-asset/delete',
  removeVariation: '/api/character-asset/delete-variation',
  promote: '/api/character-asset/promote',
  generate: '/api/character-asset/generate',
  historyThumb: id => `/api/history/thumb/${encodeURIComponent(id)}`,
  historyImage: id => `/api/history/image/${encodeURIComponent(id)}`,
  benchDefaults: '/api/character-asset/bench/defaults',
  benchGenerate: '/api/character-asset/bench/generate',
  benchSave: '/api/character-asset/bench/save',
};

const GENERATE_MAX = 8;

export function createCharacterAssetTabController({
  document,
  fetch,
  escHtml,
  showToast,
  showPromptDialog = null,
  getGenerationMode,
  getCharacterState = null,
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
  let generateOpen = false;
  let genPrompt = '';
  let genUc = '';
  let genCount = 4;
  let genRequestId = '';
  let genCandidates = [];         // [{index, status:'pending'|'done'|'error', historyId, message}]
  let busy = false;

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
    ['apply-c1', 'apply-c1-cr', 'apply-add'].forEach(action => {
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
      const next = await api(API.detail(selectedId));
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

  async function refreshAll({keepSelection = true} = {}) {
    const keptId = keepSelection ? selectedId : '';
    const keptVariation = keepSelection ? selectedVariation : '';
    await load(true);
    if (keptId && characters.some(entry => entry.id === keptId)) {
      await select(keptId, keptVariation);
    }
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

  async function saveCandidate(candidate, target) {
    if (!candidate?.historyId || busy) return;
    busy = true;
    render();
    try {
      const result = await postJson(API.save, {
        source: {kind: 'history', history_id: candidate.historyId},
        target,
      });
      showToast(target?.kind === 'variation' ? '바리에이션으로 저장됨' : '캐릭터 에셋으로 저장됨', 'success');
      candidate.saved = true;
      busy = false;
      await load(true);
      await select(result.character_id || selectedId);
    } catch (error) {
      busy = false;
      showToast(`후보 저장 실패: ${error.message}`, 'error');
      render();
    }
  }

  async function applySlot(mode, withReference = false) {
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
      });
      if (withReference) {
        if (result.reference_attached) {
          showToast('C1 슬롯 + Character Reference 적용됨', 'success');
        } else {
          showToast('C1 슬롯은 적용됐지만 Character Reference 등록에 실패했습니다', 'warning');
        }
      } else {
        showToast(mode === 'add_slot' ? '새 캐릭터 슬롯으로 추가됨' : 'C1 슬롯에 적용됨', 'success');
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
      await refreshAll();
    } catch (error) {
      showToast(`이름 변경 실패: ${error.message}`, 'error');
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

  // ------------------------------------------------------------- generation

  function prefillFromC1() {
    const state = typeof getCharacterState === 'function' ? getCharacterState() : null;
    const frames = Array.isArray(state?.characters) ? state.characters : [];
    const c1 = frames[0];
    if (!c1 || !String(c1.prompt || '').trim()) {
      showToast('C1 슬롯이 비어 있거나 캐릭터 모듈 상태를 아직 받지 못했습니다', 'error');
      return;
    }
    genPrompt = String(c1.prompt || '');
    genUc = String(c1.uc || '');
    render();
  }

  function prefillFromSelected() {
    if (!detail || !detail.recovered) {
      showToast('선택된 에셋에서 캐릭터 프롬프트를 복구할 수 없습니다', 'error');
      return;
    }
    genPrompt = String(detail.character_prompt || '');
    genUc = String(detail.character_uc || '');
    render();
  }

  async function startGeneration() {
    if (busy) return;
    if (!isNai()) {
      showToast('표준 레퍼런스 생성은 NAI 모드 전용입니다', 'error');
      return;
    }
    if (genCandidates.some(candidate => candidate.status === 'pending')) {
      // 이미 과금된 이전 배치의 request_id를 교체하면 그 결과들이 영영 매칭되지
      // 않는다 - 모든 후보가 terminal 상태가 될 때까지 재실행을 막는다.
      showToast('이전 생성 배치가 아직 진행 중입니다', 'error');
      return;
    }
    const prompt = genPrompt.trim();
    if (!prompt) {
      showToast('캐릭터 프롬프트를 입력하세요', 'error');
      return;
    }
    busy = true;
    const count = Math.max(1, Math.min(GENERATE_MAX, Number(genCount) || 1));
    genRequestId = newRequestId();
    genCandidates = Array.from({length: count}, (_, index) => ({
      index,
      status: 'pending',
      historyId: '',
      message: '',
      saved: false,
    }));
    render();
    try {
      const result = await postJson(API.generate, {
        character_prompt: prompt,
        character_uc: genUc.trim(),
        count,
        request_id: genRequestId,
      });
      const accepted = new Set(result?.accepted || []);
      (result?.rejected || []).forEach(rejection => {
        const candidate = genCandidates[Number(rejection?.candidate)];
        if (candidate) {
          candidate.status = 'error';
          candidate.message = String(rejection?.message || rejection?.reason || 'rejected');
        }
      });
      if (!accepted.size) {
        showToast('생성 요청이 큐에 들어가지 못했습니다', 'error');
      } else {
        showToast(`표준 레퍼런스 생성 ${accepted.size}건 요청됨`, 'success');
      }
    } catch (error) {
      genCandidates.forEach(candidate => {
        if (candidate.status === 'pending') {
          candidate.status = 'error';
          candidate.message = error.message;
        }
      });
      showToast(`생성 요청 실패: ${error.message}`, 'error');
    }
    busy = false;
    render();
  }

  function handleResultMeta(meta) {
    if (!meta || typeof meta !== 'object') return;
    if (!meta.character_asset_request) return;
    const requestId = String(meta.character_asset_request_id || '');
    if (meta.character_asset_bench) {
      if (!benchRequestId || requestId !== benchRequestId) return;
      // stable candidate.index lookup - benchDiscard() splices the array, so
      // positional access would rebind results to the wrong candidate.
      const candidate = benchCandidates.find(
        item => item.index === Number(meta.character_asset_candidate)
      );
      if (!candidate || candidate.status === 'done') return;
      candidate.status = 'done';
      candidate.historyId = String(meta.history_id || '');
      if (benchSelected < 0) benchSelected = candidate.index;
      if (benchOpen) renderBench();
      return;
    }
    if (requestId !== genRequestId || !genRequestId) return;
    const candidate = genCandidates[Number(meta.character_asset_candidate)];
    if (!candidate || candidate.status === 'done') return;
    candidate.status = 'done';
    candidate.historyId = String(meta.history_id || '');
    render();
  }

  function handleGenerationError(message) {
    if (!message || typeof message !== 'object') return;
    const requestId = String(message.requestId || '');
    if (benchRequestId && requestId === benchRequestId) {
      const candidate = benchCandidates.find(item => item.index === Number(message.candidate));
      if (!candidate || candidate.status === 'done') return;
      candidate.status = 'error';
      candidate.message = String(message.message || 'generation failed');
      if (benchOpen) renderBench();
      return;
    }
    if (requestId !== genRequestId || !genRequestId) return;
    const candidate = genCandidates[Number(message.candidate)];
    if (!candidate || candidate.status === 'done') return;
    candidate.status = 'error';
    candidate.message = String(message.message || 'generation failed');
    render();
  }

  // ------------------------------------------------------- variation bench

  let benchLayer = null;
  let benchOpen = false;
  let benchChar = null;          // {id, name, prompt, uc, revision}
  let benchMain = '';
  let benchNegative = '';
  let benchCount = 2;
  let benchDefaultsLoaded = false;
  let benchRequestId = '';
  let benchCandidates = [];      // {index, status, historyId, message, saved}
  let benchSelected = -1;
  let benchBusy = false;

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
      else if (action === 'bench-generate') benchGenerate();
      else if (action === 'bench-save') benchSave();
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
      else if (field.dataset.field === 'bench-main') benchMain = field.value;
      else if (field.dataset.field === 'bench-negative') benchNegative = field.value;
      else if (field.dataset.field === 'bench-count') benchCount = Number(field.value) || 1;
    });
    return benchLayer;
  }

  async function openBench() {
    if (!detail || !detail.recovered) {
      showToast('캐릭터 프롬프트를 복구할 수 없는 에셋입니다', 'error');
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
    }
    benchChar = {
      id: detail.id,
      name: summaryName({id: detail.id, display_name: detail.display_name}),
      prompt: String(detail.character_prompt || ''),
      uc: String(detail.character_uc || ''),
      revision: detail.revision || 0,
    };
    if (!benchDefaultsLoaded) {
      try {
        const defaults = await api(API.benchDefaults);
        benchMain = String(defaults.main_prompt || '');
        benchNegative = String(defaults.extra_negative || '');
        benchDefaultsLoaded = true;
      } catch (error) {
        console.error('bench defaults load failed', error);
      }
    }
    benchOpen = true;
    renderBench();
  }

  function closeBench() {
    benchOpen = false;
    if (benchLayer) benchLayer.innerHTML = '';
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
    benchRequestId = newRequestId();
    benchCandidates = Array.from({length: count}, (_, index) => ({
      index, status: 'pending', historyId: '', message: '', saved: false,
    }));
    benchSelected = -1;
    renderBench();
    try {
      const result = await postJson(API.benchGenerate, {
        id: benchChar.id,
        character_prompt: prompt,
        character_uc: String(benchChar.uc || '').trim(),
        main_prompt: benchMain,
        extra_negative: benchNegative,
        count,
        request_id: benchRequestId,
      });
      const accepted = new Set(result?.accepted || []);
      (result?.rejected || []).forEach(rejection => {
        const candidate = benchCandidates.find(
          item => item.index === Number(rejection?.candidate)
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

  async function benchSave() {
    const candidate = benchSelectedCandidate();
    if (!candidate?.historyId || candidate.saved || benchBusy || !benchChar) return;
    benchBusy = true;
    renderBench();
    try {
      await postJson(API.benchSave, {id: benchChar.id, history_id: candidate.historyId});
      candidate.saved = true;
      showToast('바리에이션으로 저장됨', 'success');
      refreshAll().catch(() => {});
    } catch (error) {
      showToast(`바리에이션 저장 실패: ${error.message}`, 'error');
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

  function renderBench() {
    const layer = ensureBenchLayer();
    if (!benchOpen || !benchChar) {
      layer.innerHTML = '';
      return;
    }
    const nai = isNai();
    const pendingCount = benchCandidates.filter(candidate => candidate.status === 'pending').length;
    const selected = benchSelectedCandidate();
    const strip = benchCandidates.map(candidate => {
      if (candidate.status === 'pending') {
        return `<div class="char-bench-thumb pending">생성 중...</div>`;
      }
      if (candidate.status === 'error') {
        return `<div class="char-bench-thumb error" title="${escAttr(candidate.message)}">실패</div>`;
      }
      return `
        <button class="char-bench-thumb done ${candidate.index === benchSelected ? 'selected' : ''} ${candidate.saved ? 'saved' : ''}"
          data-action="bench-pick" data-index="${candidate.index}">
          ${benchCropImg(candidate.historyId)}
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
            <div class="mod-section-label">Character Prompt (의상/악세서리/디테일)</div>
            <textarea class="mod-textarea char-bench-ta" data-field="bench-prompt">${escHtml(benchChar.prompt)}</textarea>
            <div class="mod-section-label">Character UC</div>
            <textarea class="mod-textarea mod-uc char-bench-ta-sm" data-field="bench-uc">${escHtml(benchChar.uc)}</textarea>
            <div class="mod-section-label">Main Prompt (자세/배경만)</div>
            <textarea class="mod-textarea char-bench-ta-sm" data-field="bench-main">${escHtml(benchMain)}</textarea>
            <div class="mod-section-label">추가 Negative (메인 네거티브에 이어붙임)</div>
            <textarea class="mod-textarea mod-uc char-bench-ta-sm" data-field="bench-negative">${escHtml(benchNegative)}</textarea>
            <div class="char-bench-gen-row">
              <label class="char-asset-gen-count">횟수
                <input type="number" min="1" max="${GENERATE_MAX}" value="${Number(benchCount) || 1}" data-field="bench-count">
              </label>
              <button class="mod-btn-sm mod-btn-encode char-bench-generate-btn" data-action="bench-generate"
                ${nai && !benchBusy && !pendingCount ? '' : 'disabled'}
                ${nai ? '' : 'title="NAI 모드 전용"'}>${pendingCount ? `생성 중... (${pendingCount})` : '바리에이션 생성'}</button>
            </div>
            <div class="char-asset-count">인페인트 고정: strength 1.0 / noise 0.0 / 좁은 마스크(512x896)</div>
          </section>
          <section class="char-bench-compare">
            <div class="char-bench-pane">
              <div class="mod-section-label">원본 (A)</div>
              <div class="char-bench-fit">
                <div class="char-bench-a"><img src="${API.image(benchChar.id, '', benchChar.revision)}" alt=""></div>
              </div>
            </div>
            <div class="char-bench-pane">
              <div class="mod-section-label">생성 결과 (B)</div>
              <div class="char-bench-fit">
                ${selected?.historyId
                  ? benchCropImg(selected.historyId)
                  : '<div class="char-bench-crop empty"><div class="mod-empty">생성된 결과가 여기 표시됩니다.</div></div>'}
              </div>
              <div class="char-bench-save-row">
                <button class="mod-btn-sm mod-btn-encode char-bench-save-btn" data-action="bench-save"
                  ${selected?.historyId && !selected.saved && !benchBusy ? '' : 'disabled'}>
                  ${selected?.saved ? '저장됨' : '바리에이션으로 저장'}</button>
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
    generateOpen = false;
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
        <button class="mod-btn-sm ${generateOpen ? 'active' : ''}" data-action="toggle-generate">+ 표준 레퍼런스 생성</button>
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
        <div class="mod-section-label">Character Prompt <span class="char-asset-warn" data-role="recover-warn" ${detail.recovered ? 'hidden' : ''}>(복구 불가 - NAI 캐릭터 블록 없음)</span></div>
        <pre class="char-asset-pre" data-role="prompt-pre">${escHtml(detail.character_prompt || '(empty)')}</pre>
        <div class="mod-section-label">Character UC</div>
        <pre class="char-asset-pre" data-role="uc-pre">${escHtml(detail.character_uc || '(empty)')}</pre>
      </div>
      <div class="char-asset-apply-actions">
        <button class="mod-btn-sm mod-btn-encode" data-action="apply-c1" ${applyDisabled} ${applyTitle}>C1 적용 (단독)</button>
        <button class="mod-btn-sm mod-btn-encode" data-action="apply-c1-cr" ${applyDisabled} ${applyTitle}
          title="C1 슬롯 적용 + 이 이미지를 Character Reference로 등록 (해상도는 자동 정규화)">C1 + CR 적용</button>
        <button class="mod-btn-sm" data-action="apply-add" ${applyDisabled} ${applyTitle}>새 슬롯으로 추가</button>
      </div>
    `;
  }

  function renderCandidates() {
    if (!genCandidates.length) return '';
    const cards = genCandidates.map(candidate => {
      if (candidate.status === 'pending') {
        return `<div class="char-asset-candidate pending"><div class="char-asset-candidate-body">생성 중...</div></div>`;
      }
      if (candidate.status === 'error') {
        return `<div class="char-asset-candidate error"><div class="char-asset-candidate-body" title="${escAttr(candidate.message)}">실패</div></div>`;
      }
      return `
        <div class="char-asset-candidate done ${candidate.saved ? 'saved' : ''}">
          <img loading="lazy" src="${API.historyThumb(candidate.historyId)}" alt="">
          <div class="char-asset-candidate-actions">
            <button class="mod-btn-sm" data-action="candidate-new" data-index="${candidate.index}" ${busy ? 'disabled' : ''}>새 캐릭터</button>
            <button class="mod-btn-sm" data-action="candidate-variation" data-index="${candidate.index}"
              ${selectedId && !busy ? '' : 'disabled'} title="${selectedId ? '' : '대상 캐릭터를 먼저 선택하세요'}">바리에이션</button>
          </div>
        </div>
      `;
    }).join('');
    return `<div class="char-asset-candidate-strip">${cards}</div>`;
  }

  function renderGenerateForm() {
    if (!generateOpen) return '';
    const nai = isNai();
    return `
      <div class="char-asset-generate">
        <div class="mod-section-label">표준 레퍼런스 생성 - 고정 전신 스캐폴드(768x1344) + 캐릭터 프롬프트</div>
        <textarea class="mod-textarea char-asset-gen-prompt" data-field="gen-prompt" placeholder="character prompt...">${escHtml(genPrompt)}</textarea>
        <textarea class="mod-textarea mod-uc char-asset-gen-uc" data-field="gen-uc" placeholder="character UC (optional)...">${escHtml(genUc)}</textarea>
        <div class="char-asset-gen-controls">
          <button class="mod-btn-sm" data-action="prefill-c1">C1에서 가져오기</button>
          <button class="mod-btn-sm" data-action="prefill-selected" ${detail?.recovered ? '' : 'disabled'}>선택 에셋에서</button>
          <label class="char-asset-gen-count">횟수
            <input type="number" min="1" max="${GENERATE_MAX}" value="${Number(genCount) || 1}" data-field="gen-count">
          </label>
          <button class="mod-btn-sm mod-btn-encode" data-action="generate-start" ${nai && !busy ? '' : 'disabled'}
            ${nai ? '' : 'title="NAI 모드 전용"'}>생성 시작</button>
        </div>
        ${renderCandidates()}
      </div>
    `;
  }

  function render() {
    if (!root) return;
    root.innerHTML = `
      <div class="char-asset-shell">
        ${renderStagedBanner()}
        ${renderGenerateForm()}
        <div class="char-asset-columns">
          <section class="char-asset-gallery">${renderGrid()}</section>
          <section class="char-asset-detail">${renderDetail()}</section>
        </div>
      </div>
    `;
  }

  // ---------------------------------------------------------------- events

  if (root) {
    root.addEventListener('click', event => {
      const button = event.target.closest('[data-action]');
      if (!button || button.disabled) return;
      const action = button.dataset.action;
      if (action === 'select') select(button.dataset.id || '');
      else if (action === 'select-variation') {
        selectedVariation = button.dataset.hash || '';
        disarmDelete();
        const zone = root.querySelector('[data-role="variations-zone"]');
        if (zone && detail) {
          // 스트립 선택 표시와 뷰어 이미지만 갱신 - 전체 재렌더 깜빡임 방지.
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
        } else {
          render();
        }
      }
      else if (action === 'refresh') refreshAll();
      else if (action === 'toggle-generate') {
        generateOpen = !generateOpen;
        render();
      }
      else if (action === 'staged-new') saveStaged({kind: 'new'});
      else if (action === 'staged-variation') saveStaged({kind: 'variation', character_id: selectedId});
      else if (action === 'staged-cancel') { staged = null; render(); }
      else if (action === 'apply-c1') applySlot('c1');
      else if (action === 'apply-c1-cr') applySlot('c1', true);
      else if (action === 'apply-add') applySlot('add_slot');
      else if (action === 'rename') renameSelected();
      else if (action === 'delete-character') deleteSelected();
      else if (action === 'delete-variation') deleteSelectedVariation();
      else if (action === 'promote') promoteSelectedVariation();
      else if (action === 'open-bench') openBench();
      else if (action === 'prefill-c1') prefillFromC1();
      else if (action === 'prefill-selected') prefillFromSelected();
      else if (action === 'generate-start') startGeneration();
      else if (action === 'candidate-new') {
        const candidate = genCandidates[Number(button.dataset.index)];
        saveCandidate(candidate, {kind: 'new'});
      }
      else if (action === 'candidate-variation') {
        const candidate = genCandidates[Number(button.dataset.index)];
        saveCandidate(candidate, {kind: 'variation', character_id: selectedId});
      }
    });
    root.addEventListener('input', event => {
      const field = event.target.closest('[data-field]');
      if (!field) return;
      if (field.dataset.field === 'gen-prompt') genPrompt = field.value;
      else if (field.dataset.field === 'gen-uc') genUc = field.value;
      else if (field.dataset.field === 'gen-count') genCount = Number(field.value) || 1;
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
    stageFromContext,
  };
}
