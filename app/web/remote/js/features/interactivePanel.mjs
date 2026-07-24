// Interactive Mode — 프롬프트를 의미 슬롯(블록)으로 분해해 편집하는 뷰.
//
// 좌측은 "보기": 블록당 1행, 선택한 태그를 칩으로 압축 표시. 클릭이 유일한 인터랙션.
// 우측은 "작업": 검색 / 선택됨 / 사전 탐색. 실제 편집은 전부 여기서 일어난다.
//
// 상태 모델(INTERACTIVE_QUICKFILTER_PLAN.md 참조):
//   블록 배열이 편집 SSOT, 프롬프트 문자열은 렌더 결과다. 블록 -> 문자열은 항상 결정론적이고,
//   문자열 -> 블록 역파싱은 하지 않는다(외부 프롬프트 들여오기는 제공하지 않기로 확정).
//
// 캐릭터 블록은 NAI 캐릭터 슬롯(character_frames)으로 나가므로 메인 프롬프트 문자열에
// 들어가지 않는다. 나머지 블록만 결합된다.
//
// cache-bust marker: 20260723-ia1

const SCENE_SLOTS = [
  {id: 'composition', name: '구도', icon: '\u{1F5BC}', axis: 'meta'},
  {id: 'background', name: '배경', icon: '\u{1F3DE}', axis: 'location'},
  {id: 'etc', name: '기타', icon: '⚙', axis: 'object'},
];

const CHAR_SUBS = [
  {key: '특징', icon: '\u{1F9EC}', axis: 'characteristic'},
  {key: '의상', icon: '\u{1F457}', axis: 'clothing'},
  {key: '액션', icon: '\u{1F3C3}', axis: 'pose_action'},
  {key: '표정', icon: '\u{1F60A}', axis: 'expression'},
];

const MAX_CHIPS = 6;

export function createInteractivePanel({
  document,
  blocksMount,
  panelMount,
  toggleButton,
  escHtml = value => String(value == null ? '' : value),
  onPromptChange = () => {},
  onActiveChange = () => {},
  queryCorpus = null,          // async ({rating, person, include, exclude, search, limit}) => payload
  corpusStatus = null,         // async () => payload
  autocomplete = null,         // createInteractiveAutocomplete() 인스턴스 (선택)
  browse = null,               // createInteractiveBrowse() 인스턴스 (선택)
  showToast = () => {},
} = {}) {
  if (!blocksMount || !panelMount) {
    return {isActive: () => false, setActive: () => {}, destroy: () => {}};
  }

  let active = false;
  let openId = null;
  let corpusState = null;      // 최근 status 응답
  let queryToken = 0;

  const state = {
    rating: 's',
    person: '1girl_solo',
    chars: [newCharacter('C1', true)],
    slots: {composition: [], background: [], etc: []},
  };

  function newCharacter(id, open) {
    return {
      id,
      name: '',
      open: !!open,
      state: 'active',
      fields: {'특징': [], '의상': [], '액션': [], '표정': []},
    };
  }

  // ---------------------------------------------------------------- prompt

  /** 블록 -> 프롬프트 문자열. 캐릭터는 별도 슬롯으로 나가므로 제외. */
  function renderPrompt() {
    const parts = [];
    for (const slot of SCENE_SLOTS) parts.push(...(state.slots[slot.id] || []));
    return parts.join(', ');
  }

  function emitChange() {
    onPromptChange(renderPrompt(), {
      characters: state.chars.map(c => ({
        id: c.id,
        name: c.name,
        state: c.state,
        prompt: CHAR_SUBS.map(s => (c.fields[s.key] || []).join(', '))
          .filter(Boolean).join(', '),
      })),
    });
  }

  // ---------------------------------------------------------------- render

  function chip(text, cls) {
    return `<span class="ia-chip${cls ? ' ' + cls : ''}">${escHtml(text)}</span>`;
  }

  function chipRow(tags) {
    if (!tags || !tags.length) return '<span class="ia-chip-empty">비어 있음</span>';
    const shown = tags.slice(0, MAX_CHIPS).map(t => chip(t));
    if (tags.length > MAX_CHIPS) shown.push(chip(`+${tags.length - MAX_CHIPS}`, 'is-more'));
    return shown.join('');
  }

  function sceneBlockHtml(slot) {
    const tags = state.slots[slot.id] || [];
    return `<div class="ia-block${openId === slot.id ? ' is-open' : ''}${tags.length ? '' : ' is-empty'}" data-slot="${slot.id}">
      <div class="ia-block-label">
        <span class="ia-block-title"><span class="ia-block-icon">${slot.icon}</span><span class="ia-block-name">${slot.name}</span></span>
        <span class="ia-block-axis">${slot.axis}</span>
      </div>
      <div class="ia-block-chips">${chipRow(tags)}</div>
      <div class="ia-block-meta"><span class="ia-block-count">${tags.length || ''}</span></div>
    </div>`;
  }

  function charBlockHtml() {
    const rows = state.chars.map((c, i) => {
      const summary = CHAR_SUBS.flatMap(s => c.fields[s.key] || []).join(', ') || '(비어 있음)';
      const subs = CHAR_SUBS.map(s => {
        const tags = c.fields[s.key] || [];
        return `<div class="ia-sub-block${tags.length ? '' : ' is-empty'}" data-cid="${c.id}" data-sub="${s.key}">
          <div class="ia-block-label">
            <span class="ia-block-title"><span class="ia-block-icon">${s.icon}</span><span class="ia-block-name">${s.key}</span></span>
            <span class="ia-block-axis">${s.axis}</span>
          </div>
          <div class="ia-block-chips">${chipRow(tags)}</div>
          <div class="ia-block-meta"><span class="ia-block-count">${tags.length || ''}</span></div>
        </div>`;
      }).join('');
      return `<div class="ia-char${c.open ? ' is-open' : ''}" data-char="${i}">
        <div class="ia-char-head">
          <span class="ia-char-caret">&#9654;</span>
          <span class="ia-char-id">${escHtml(c.id)}</span>
          <span class="ia-char-sum">${escHtml(summary)}</span>
          <span class="ia-char-state ${c.state}">${c.state}</span>
        </div>
        <div class="ia-char-body">${subs}</div>
      </div>`;
    }).join('');

    const activeCount = state.chars.filter(c => c.state === 'active').length;
    return `<div class="ia-block is-character" data-slot="character">
      <div class="ia-cblock-head">
        <span class="ia-block-icon">\u{1F464}</span>
        <span class="ia-block-name">캐릭터</span>
        <span style="flex:1"></span>
        <span class="ia-block-count">${activeCount} 활성</span>
      </div>
      ${rows}
      <div class="ia-char-foot"><button type="button" class="ia-charcard-add" data-add-char="1">+ 캐릭터 슬롯</button></div>
    </div>`;
  }

  function renderBlocks() {
    blocksMount.innerHTML = charBlockHtml() + SCENE_SLOTS.map(sceneBlockHtml).join('');

    blocksMount.querySelectorAll('.ia-block:not(.is-character)').forEach(el => {
      el.addEventListener('click', () => openSlot(el.dataset.slot));
    });
    blocksMount.querySelectorAll('.ia-char-head').forEach(el => {
      el.addEventListener('click', event => {
        event.stopPropagation();
        toggleChar(Number(el.parentElement.dataset.char));
      });
    });
    blocksMount.querySelectorAll('.ia-sub-block').forEach(el => {
      el.addEventListener('click', event => {
        event.stopPropagation();
        openCharSub(el.dataset.cid, el.dataset.sub);
      });
    });
    const addBtn = blocksMount.querySelector('[data-add-char]');
    if (addBtn) {
      addBtn.addEventListener('click', event => {
        event.stopPropagation();
        addCharacter();
      });
    }
  }

  // ---------------------------------------------------------------- actions

  function toggleChar(index) {
    const willOpen = !state.chars[index].open;
    state.chars.forEach((c, i) => { c.open = (i === index) && willOpen; });
    renderBlocks();
  }

  function addCharacter() {
    if (state.chars.length >= 6) {
      showToast('캐릭터 슬롯은 최대 6개입니다.', 'error');
      return;
    }
    const next = newCharacter(`C${state.chars.length + 1}`, true);
    state.chars.forEach(c => { c.open = false; });
    state.chars.push(next);
    renderBlocks();
    emitChange();
  }

  // ---------------------------------------------------------------- panel

  let panelContext = null;   // {kind:'scene', slotId} | {kind:'char', cid, sub}

  function currentTags() {
    if (!panelContext) return [];
    if (panelContext.kind === 'scene') return state.slots[panelContext.slotId] || [];
    const c = state.chars.find(x => x.id === panelContext.cid);
    return (c && c.fields[panelContext.sub]) || [];
  }

  function setCurrentTags(tags) {
    if (!panelContext) return;
    if (panelContext.kind === 'scene') {
      state.slots[panelContext.slotId] = tags;
    } else {
      const c = state.chars.find(x => x.id === panelContext.cid);
      if (c) c.fields[panelContext.sub] = tags;
    }
    // 전체 재렌더(renderBlocks/renderPanel)를 하지 않는다. innerHTML 을 통째로 갈아끼우면
    // 좌측 블록 전체가 깜빡이고, 우측 입력창이 재생성되면서 포커스와 IME 조합이 끊긴다.
    updateBlockView(panelContext);
    updateSelectedView();
    if (browse) browse.refreshDupes();   // 브라우저의 '있음' 표시 갱신(재요청 없음)
    emitChange();
  }

  /** 변경된 블록 하나만 갱신. 구조가 바뀌지 않았을 때만 쓴다. */
  function updateBlockView(context) {
    if (!context) return;
    if (context.kind === 'scene') {
      const el = blocksMount.querySelector(`.ia-block[data-slot="${context.slotId}"]`);
      if (!el) { renderBlocks(); return; }
      applyChipView(el, state.slots[context.slotId] || []);
      return;
    }
    const character = state.chars.find(x => x.id === context.cid);
    const sub = blocksMount.querySelector(
      `.ia-sub-block[data-cid="${context.cid}"][data-sub="${context.sub}"]`
    );
    if (!character || !sub) { renderBlocks(); return; }
    applyChipView(sub, character.fields[context.sub] || []);
    // 접었을 때 보이는 요약 줄도 같은 캐릭터 안에서만 갱신한다.
    const summary = sub.closest('.ia-char')?.querySelector('.ia-char-sum');
    if (summary) {
      summary.textContent =
        CHAR_SUBS.flatMap(s => character.fields[s.key] || []).join(', ') || '(비어 있음)';
    }
  }

  function applyChipView(el, tags) {
    const chips = el.querySelector('.ia-block-chips');
    const count = el.querySelector('.ia-block-count');
    if (chips) chips.innerHTML = chipRow(tags);
    if (count) count.textContent = tags.length || '';
    el.classList.toggle('is-empty', !tags.length);
  }

  function openSlot(slotId) {
    const slot = SCENE_SLOTS.find(s => s.id === slotId);
    if (!slot) return;
    openId = slotId;
    panelContext = {kind: 'scene', slotId, title: slot.name, axis: slot.axis};
    panelMount.classList.add('open');
    updateOpenHighlight();
    renderPanel();   // renderPanel 이 browse.attach 로 Depth1 을 로드한다
  }

  function openCharSub(cid, sub) {
    const meta = CHAR_SUBS.find(s => s.key === sub);
    if (!meta) return;
    openId = 'character';
    panelContext = {kind: 'char', cid, sub, title: `${cid} · ${sub}`, axis: meta.axis};
    panelMount.classList.add('open');
    updateOpenHighlight();
    renderPanel();
  }

  /** 선택 하이라이트만 옮긴다. 슬롯을 바꿀 때마다 전체를 다시 그리면 목록이 깜빡인다. */
  function updateOpenHighlight() {
    blocksMount.querySelectorAll('.ia-block[data-slot]').forEach(el => {
      el.classList.toggle('is-open', el.dataset.slot === openId);
    });
    const cid = panelContext?.kind === 'char' ? panelContext.cid : null;
    const sub = panelContext?.kind === 'char' ? panelContext.sub : null;
    blocksMount.querySelectorAll('.ia-sub-block').forEach(el => {
      el.classList.toggle('is-open', el.dataset.cid === cid && el.dataset.sub === sub);
    });
  }

  function closePanel() {
    if (autocomplete) autocomplete.unbind();
    if (browse) browse.detach();
    openId = null;
    panelContext = null;
    panelMount.classList.remove('open');
    panelMount.innerHTML = '';
    updateOpenHighlight();
  }

  let recommendations = [];
  let recommendationNote = '';

  function selectedHtml() {
    const tags = currentTags();
    return tags.length
      ? tags.map(t => `<span class="ia-tag">${escHtml(t)}<button type="button" class="ia-tag-x" data-remove="${escHtml(t)}">&times;</button></span>`).join('')
      : '<span class="ia-chip-empty">아직 선택된 태그가 없습니다</span>';
  }

  function recommendationsHtml() {
    return recommendations.length
      ? recommendations.map(row =>
          `<button type="button" class="ia-grid-tag" data-add="${escHtml(row.tag)}">${escHtml(row.tag)}<span class="ia-grid-kr">${row.count || ''}</span></button>`
        ).join('')
      : `<span class="ia-chip-empty">${escHtml(recommendationNote || '추천 태그가 없습니다')}</span>`;
  }

  /** 선택됨 영역만 교체. 입력창은 건드리지 않아 포커스/IME 조합이 유지된다. */
  function updateSelectedView() {
    const host = panelMount.querySelector('.ia-selected');
    if (!host) { renderPanel(); return; }
    host.innerHTML = selectedHtml();
    bindSelectedHandlers(host);
  }

  /** 추천 영역만 교체. */
  function updateRecommendationsView() {
    const host = panelMount.querySelector('.ia-grid');
    if (!host) { renderPanel(); return; }
    host.innerHTML = recommendationsHtml();
    bindRecommendationHandlers(host);
  }

  function bindSelectedHandlers(host) {
    host.querySelectorAll('[data-remove]').forEach(el => {
      el.addEventListener('click', () => {
        setCurrentTags(currentTags().filter(t => t !== el.dataset.remove));
      });
    });
  }

  function bindRecommendationHandlers(host) {
    host.querySelectorAll('[data-add]').forEach(el => {
      el.addEventListener('click', () => addTags([el.dataset.add]));
    });
  }

  function renderPanel() {
    // 이전 input 의 리스너를 떼어낸다. innerHTML 교체로 노드는 사라지지만, 모듈이 잡고 있는
    // IME 타이머와 팝업 상태는 명시적으로 정리해야 한다.
    if (autocomplete) autocomplete.unbind();
    if (browse) browse.detach();
    if (!panelContext) { panelMount.innerHTML = ''; return; }
    const selected = selectedHtml();
    const recs = recommendationsHtml();

    panelMount.innerHTML = `
      <div class="ia-panel-head">
        <span class="ia-panel-title">${escHtml(panelContext.title)}</span>
        <span class="ia-panel-sub">${escHtml(panelContext.axis)}</span>
        <button type="button" class="ia-panel-close" data-close="1">&times;</button>
      </div>
      <div class="ia-panel-body">
        <section>
          <div class="ia-sec-label">직접 입력</div>
          <div class="ia-search">
            <input type="text" id="iaTagInput" placeholder="태그 입력 후 Enter (쉼표로 여러 개)" autocomplete="off">
            <span class="ia-search-scope">${escHtml(panelContext.axis)}</span>
          </div>
        </section>
        <section>
          <div class="ia-sec-label">선택됨</div>
          <div class="ia-selected">${selected}</div>
        </section>
        <section>
          <div class="ia-sec-label">분류 탐색</div>
          <div class="ia-browse-mount" id="iaBrowseMount"></div>
        </section>
      </div>`;

    panelMount.querySelector('[data-close]')?.addEventListener('click', closePanel);
    const selectedHost = panelMount.querySelector('.ia-selected');
    if (selectedHost) bindSelectedHandlers(selectedHost);
    // 계층 브라우저를 이 슬롯 축으로 마운트한다. 없으면 섹션은 비어 있다.
    if (browse) {
      const browseMount = panelMount.querySelector('#iaBrowseMount');
      if (browseMount) {
        browse.attach(browseMount, {
          axis: panelContext.axis,
          // 브라우저 항목 클릭은 토글이다 — 이미 슬롯에 있으면(✓ 표시) 제거, 없으면 추가.
          // 탐색기 안에서 넣은 걸 탐색기 안에서 뺄 수 있어야 한다.
          onPick: tag => toggleTag(tag),
          getExisting: () => currentTags(),
        });
      }
    }
    const input = panelMount.querySelector('#iaTagInput');
    if (input) {
      if (autocomplete) {
        // 축 스코프 자동완성 + IME 조합 처리 + 관계 추천을 모듈에 위임한다.
        autocomplete.bind(input, {
          axis: panelContext.axis,
          onCommit: tag => addTags([tag]),
          getExisting: () => currentTags(),
        });
      } else {
        // 폴백: 자동완성 모듈이 없으면 Enter 로 자유 입력만 받는다.
        input.addEventListener('keydown', event => {
          if (event.key !== 'Enter') return;
          event.preventDefault();
          const parts = String(input.value || '').split(',').map(s => s.trim()).filter(Boolean);
          if (parts.length) { input.value = ''; addTags(parts); }
        });
      }
    }
  }

  function addTags(tags) {
    const current = currentTags();
    const merged = current.slice();
    // 중복 판정은 대소문자 무시로 통일한다(toggleTag / dupe(✓) 표시와 같은 규칙).
    // 안 그러면 "Dress"가 이미 있는데 "dress"를 넣으면 두 항목이 생긴다(Codex M9).
    const lower = new Set(merged.map(t => t.toLowerCase()));
    for (const tag of tags) {
      const normalized = String(tag || '').trim();
      if (normalized && !lower.has(normalized.toLowerCase())) {
        merged.push(normalized);
        lower.add(normalized.toLowerCase());
      }
    }
    setCurrentTags(merged);
  }

  /** 브라우저/추천에서의 클릭 = 토글. 있으면 제거, 없으면 추가.
   *  브라우저의 ✓(dupe) 판정이 대소문자 무시라, 제거 비교도 대소문자 무시로 맞춘다. */
  function toggleTag(tag) {
    const normalized = String(tag || '').trim();
    if (!normalized) return;
    const current = currentTags();
    const lower = normalized.toLowerCase();
    const existing = current.find(t => t.toLowerCase() === lower);
    if (existing) {
      setCurrentTags(current.filter(t => t !== existing));
    } else {
      setCurrentTags(current.concat([normalized]));
    }
  }

  // ---------------------------------------------------------------- corpus

  async function refreshRecommendations() {
    if (!panelContext || typeof queryCorpus !== 'function') {
      recommendations = [];
      recommendationNote = '이벤트 코퍼스 연결이 없습니다.';
      updateRecommendationsView();
      return;
    }
    const token = ++queryToken;
    recommendationNote = '불러오는 중…';
    try {
      // 현재 슬롯의 태그를 include 로 넣어 그 조합에서 자주 같이 나오는 태그를 받는다.
      const payload = await queryCorpus({
        rating: state.rating,
        person: state.person,
        include: currentTags(),
        exclude: [],
        search: '',
        limit: 40,
      });
      if (token !== queryToken) return;            // superseded
      recommendations = Array.isArray(payload?.tags) ? payload.tags : [];
      recommendationNote = recommendations.length ? '' : '매칭되는 이벤트가 없습니다.';
    } catch (error) {
      if (token !== queryToken) return;
      recommendations = [];
      if (error?.code === 'superseded' || error?.code === 'disconnected') return;
      recommendationNote = corpusMessage(error);
    }
    // 추천 영역만 교체한다. 패널 전체를 다시 그리면 입력 중이던 태그와 포커스가 날아간다.
    updateRecommendationsView();
  }

  function corpusMessage(error) {
    const code = error?.code || '';
    if (code === 'corpus_unavailable' || code === 'partition_unavailable') {
      return '이벤트 코퍼스 데이터가 설치되지 않았습니다. 직접 입력은 그대로 사용할 수 있습니다.';
    }
    if (code === 'unknown_include_tags') {
      return '선택한 태그 중 코퍼스에 없는 것이 있어 추천을 계산할 수 없습니다.';
    }
    return '추천을 불러오지 못했습니다.';
  }

  // ---------------------------------------------------------------- toggle

  function setActive(next, {silent = false} = {}) {
    const value = !!next;
    if (value === active) return;
    active = value;
    if (toggleButton) {
      toggleButton.classList.toggle('is-on', active);
      toggleButton.setAttribute('aria-pressed', active ? 'true' : 'false');
    }
    blocksMount.hidden = !active;
    if (!active) closePanel();
    else { renderBlocks(); void probeStatus(); }
    onActiveChange(active);
    if (!silent && active) emitChange();
  }

  async function probeStatus() {
    if (typeof corpusStatus !== 'function' || corpusState) return;
    try {
      corpusState = await corpusStatus();
      if (corpusState?.state && corpusState.state !== 'ready') {
        showToast('이벤트 코퍼스 데이터가 없어 추천 태그는 비활성입니다. 직접 입력은 가능합니다.', 'error');
      }
    } catch (error) {
      corpusState = {state: 'missing'};
    }
  }

  // 토글 리스너는 명명 함수로 두어 destroy 시 제거할 수 있게 한다(Codex M7).
  const onToggleClick = () => setActive(!active);
  if (toggleButton) toggleButton.addEventListener('click', onToggleClick);

  blocksMount.hidden = true;

  return {
    isActive: () => active,
    setActive,
    setContext: ({rating, person} = {}) => {
      if (rating) state.rating = rating;
      if (person) state.person = person;
    },
    getPrompt: renderPrompt,
    destroy: () => {
      // 하위 모듈의 리스너/타이머/팝업/툴팁까지 정리한다.
      if (autocomplete) { try { autocomplete.unbind(); } catch (e) {} }
      if (browse) { try { browse.destroy(); } catch (e) {} }
      if (toggleButton) toggleButton.removeEventListener('click', onToggleClick);
      blocksMount.innerHTML = '';
      panelMount.innerHTML = '';
    },
  };
}
