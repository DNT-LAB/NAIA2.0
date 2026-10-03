export function createE621EventPanel({
  document,
  escHtml,
  setModuleParam,
  bindTagAssist,
  showToast,
  // 그릴 자리. 메인 화면은 떠 있는 창(e621Window)의 본문을 넘긴다. 없으면 예전처럼 모듈 팝업 본문
  // (별도 브라우저 창으로 떼어 낸 모듈은 그 창 전체가 모듈 팝업이다).
  moduleBody: host = null,
}) {
  const moduleBody = host || document.getElementById('modulePopupBody');
  ensureStyle(document);
  bindDelegates();
  let lastState = null;
  let lastRenderedStructureSignature = '';
  let deferredFocusedRenderState = null;
  let deferredFocusTarget = null;

  function attr(value) {
    return escHtml(String(value ?? ''));
  }

  function selectedTagName() {
    return lastState && lastState.selected ? lastState.selected.tag : '';
  }

  function renderCategoryButton(category) {
    const classes = [
      'e621-chip',
      category.selected ? 'selected' : '',
      category.matched ? 'matched' : '',
      category.starred_count > 0 ? 'has-starred' : '',
    ].filter(Boolean).join(' ');
    const subtitle = `${category.section} · ${category.tag_count}`;
    return `<button class="${classes}" data-category="${attr(category.name)}" onclick="e621SelectCategory(this)">
      <span>${escHtml(category.name.replace(/_/g, ' '))}</span>
      <small>${escHtml(subtitle)}${category.starred_count ? ` · *${category.starred_count}` : ''}</small>
    </button>`;
  }

  function renderFolderButton(folder) {
    return `<button class="e621-list-item${folder.selected ? ' selected' : ''}" data-folder="${attr(folder.name)}" onclick="e621SelectFolder(this)">
      <span>${escHtml(folder.display)}</span>
      <small>${folder.tag_count}</small>
    </button>`;
  }

  // 검색이 어디서 맞았나(2단계 응답 계약 docs/e621_stage2_response_contract.ko.md). 짧은 칩으로 보인다 -
  // 글자를 읽게 하지 않는다. 이름이 통째로 같으면(match_grade 0) '정확' 하나로 대신한다.
  const MATCH_LABELS = {
    tag_name: '이름',
    korean_name: '한국어 이름',
    korean_keywords: '검색어',
    korean_description: '한국어 설명',
    stored_body: '본문',
  };

  function matchFieldsOf(tag) {
    if (Array.isArray(tag.match_fields)) return tag.match_fields;
    // 옛 백엔드(필드 배열이 없다) - 예전 두 bool 로 대신한다.
    return [tag.matched_in_korean ? 'korean_name' : '', tag.matched_in_wiki ? 'stored_body' : ''].filter(Boolean);
  }

  function renderMatchChips(tag) {
    const fields = matchFieldsOf(tag);
    if (!fields.length) return '';
    const compact = new Set(Array.isArray(tag.match_compact_fields) ? tag.match_compact_fields : []);
    return fields.map(field => {
      const exact = field === 'tag_name' && tag.match_grade === 0;
      const label = exact ? '정확' : (MATCH_LABELS[field] || field);
      const classes = ['e621-match-chip', exact ? 'exact' : '', field === 'stored_body' ? 'body' : '',
        compact.has(field) ? 'compact' : ''].filter(Boolean).join(' ');
      const title = exact ? '태그 이름과 통째로 같습니다'
        : compact.has(field) ? `${label} - 띄어쓰기를 빼고 맞았습니다` : `${label}에서 맞았습니다`;
      return `<span class="${classes}" title="${attr(title)}">${escHtml(label)}</span>`;
    }).join('');
  }

  // ── 생성용 선택 태그(selected_tags) · 관계 · 추천 ──────────────────────────────
  // 응답 계약 = docs/e621_stage2_response_contract.ko.md(선택 태그 절) · docs/e621_relations_contract.ko.md.
  // 클릭은 data-e621-act 로 위임해 받는다(bindDelegates) - 공용 app.js 에 전역 함수를 늘리지 않는다.
  function selectionSet() {
    return new Set((lastState?.selected_tags || []).map(row => row.exact_tag));
  }

  function weightLimits() {
    // 서버가 모드별 한도를 준다(지금은 세 모드 모두 0~2). 화면은 모드를 따로 들고 있지 않아 NAI 값을 쓴다.
    const limits = lastState?.weight_limits || {};
    return limits.NAI || {min: 0, max: 2, default: 1};
  }

  function formatWeight(value) {
    return String(Math.round(Number(value) * 100) / 100);
  }

  // 관계 · 추천 칩: 이름을 누르면 그 태그로 간다, + 는 생성용 선택에 더한다(이미 있으면 ✓).
  function renderRelationChip(item, extra = '') {
    const title = [item.kor, item.count ? `${item.count.toLocaleString()} posts` : ''].filter(Boolean).join(' · ');
    const add = item.in_selection
      ? '<span class="e621-rel-added" title="이미 선택에 있습니다">✓</span>'
      : `<button class="e621-rel-add" data-e621-act="add" data-tag="${attr(item.tag)}" title="선택에 추가">+</button>`;
    return `<span class="e621-rel-chip${item.in_selection ? ' in-selection' : ''}">`
      + `<button class="e621-rel-name" data-e621-act="open" data-tag="${attr(item.tag)}" title="${attr(title)}">${escHtml(item.display || item.tag)}${extra}</button>`
      + `${add}</span>`;
  }

  function renderRelations(relations) {
    if (!relations) return '';
    const head = `<div class="mod-section-label">관계${relations.snapshot ? ` <small class="e621-rel-snapshot">e621 ${escHtml(relations.snapshot)}</small>` : ''}</div>`;
    if (relations.status !== 'available') {
      return `<section class="e621-research-section e621-relations">${head}<div class="mod-empty">관계 데이터가 없습니다.</div></section>`;
    }
    const row = (label, title, chips, more = '') => chips ? `<div class="e621-rel-row"><span class="e621-rel-label" title="${attr(title)}">${escHtml(label)}</span><span class="e621-rel-chips">${chips}${more}</span></div>` : '';
    const broader = (relations.broader || []).map(item => renderRelationChip(item)).join('');
    const narrower = (relations.narrower || []).map(item => renderRelationChip(item)).join('');
    const narrowerMore = (relations.narrower_total || 0) > (relations.narrower || []).length
      ? `<span class="e621-rel-more">외 ${(relations.narrower_total - relations.narrower.length).toLocaleString()}</span>` : '';
    const aliases = (relations.aliases || []).map(item => `<span class="e621-rel-alias">${escHtml(item.from)} → ${escHtml(item.to)}</span>`).join('');
    const together = (relations.cooccurrences || []).map(item => renderRelationChip(item, ` <small>${Number(item.pair_count || 0).toLocaleString()}</small>`)).join('');
    const rows = row('상위', '이 태그가 붙으면 함께 붙는 상위 태그(e621 포함 관계)', broader)
      + row('하위', '이 태그를 포함하는 하위 태그(e621 포함 관계)', narrower, narrowerMore)
      + row('별칭', 'e621 별칭 - 입력 정규화 제안', aliases)
      + row('함께', '같은 게시물에 자주 함께 붙은 태그와 그 게시물 수(관측일 뿐 의미 관계가 아님)', together);
    return `<section class="e621-research-section e621-relations">${head}${rows || '<div class="mod-empty">기록된 관계가 없습니다.</div>'}</section>`;
  }

  function renderSelectionChip(row) {
    const limits = weightLimits();
    const weight = Number(row.weight);
    const tone = weight > 1 ? ' up' : weight < 1 ? ' down' : '';
    const title = [row.kor, '끌어서 순서를 바꿉니다'].filter(Boolean).join(' · ');
    return `<span class="e621-sel-chip${tone}" draggable="true" data-sel-tag="${attr(row.exact_tag)}" title="${attr(title)}">`
      + `<button class="e621-sel-name" data-e621-act="open" data-tag="${attr(row.exact_tag)}">${escHtml(row.display || row.exact_tag)}</button>`
      + `<button class="e621-sel-step" data-e621-act="weight-down" data-tag="${attr(row.exact_tag)}" aria-label="가중치 내리기">−</button>`
      + `<input class="e621-sel-weight" type="number" min="${limits.min}" max="${limits.max}" step="0.05" value="${formatWeight(weight)}" data-e621-weight="${attr(row.exact_tag)}" aria-label="가중치">`
      + `<button class="e621-sel-step" data-e621-act="weight-up" data-tag="${attr(row.exact_tag)}" aria-label="가중치 올리기">+</button>`
      + `<button class="e621-sel-x" data-e621-act="remove" data-tag="${attr(row.exact_tag)}" aria-label="선택에서 빼기">×</button>`
      + '</span>';
  }

  function renderGenerationCard(state) {
    const rows = state.selected_tags || [];
    const chips = rows.length ? rows.map(renderSelectionChip).join('')
      : '<span class="e621-sel-empty">태그를 고르고 [+ 선택] 을 누르세요</span>';
    const suggestions = state.selection_suggestions?.candidates || [];
    const suggest = suggestions.length
      ? `<div class="e621-suggest"><span class="e621-rel-label" title="고른 태그들과 같은 게시물에 자주 함께 붙은 태그 - 쌍 관측의 합이라 근사입니다">함께 쓰임</span><span class="e621-rel-chips">${
        suggestions.map(item => renderRelationChip(item, item.matched_anchor_count > 1 ? ` <small>×${item.matched_anchor_count}</small>` : '')).join('')}</span></div>`
      : '';
    return `
          <section class="e621-detail-card e621-gen-card">
            <div class="e621-gen-head">
              <div class="mod-section-label">생성 테스트 · 선택 ${rows.length}</div>
              <label class="mod-check-row e621-pipeline-toggle" title="메인 프롬프트의 접두 · 접미 · 와일드카드를 함께 씁니다">
                <input type="checkbox" data-e621-pipeline ${state.use_main_pipeline === false ? '' : 'checked'}>
                <span>메인 프롬프트 설정 사용</span>
              </label>
              <button class="mod-btn-sm" data-e621-act="clear" ${rows.length ? '' : 'disabled'}>비우기</button>
            </div>
            <div class="e621-selection">${chips}</div>
            ${suggest}
            <div class="e621-testbench-row">
              <textarea class="mod-textarea" id="e621Testbench" rows="1" placeholder="{{selected_tags}} 자리에 선택 태그가 들어갑니다(없으면 맨 뒤)" oninput="e621OnTestbenchInput(this)">${escHtml(state.testbench || '')}</textarea>
              <button class="mod-action-btn mod-start" onclick="e621Generate()">생성</button>
            </div>
          </section>`;
  }

  function bindDelegates() {
    // 떼어 낸 창에서는 모듈 팝업 본문(다른 모듈도 그리는 곳)에 걸린다 - data-e621-* 표식이 있는 것만 받는다.
    if (!moduleBody || typeof moduleBody.addEventListener !== 'function' || moduleBody.dataset?.e621Delegated) return;
    if (moduleBody.dataset) moduleBody.dataset.e621Delegated = '1';
    const send = (key, value) => setModuleParam('e621_event', key, value);
    const clampWeight = value => {
      const limits = weightLimits();
      return Math.min(limits.max, Math.max(limits.min, Math.round(value * 100) / 100));
    };
    moduleBody.addEventListener('click', event => {
      const target = event.target?.closest?.('[data-e621-act]');
      if (!target || !moduleBody.contains(target)) return;
      const tag = target.dataset.tag || '';
      const act = target.dataset.e621Act;
      const current = (lastState?.selected_tags || []).find(row => row.exact_tag === tag);
      if (act === 'open') send('selected_tag', tag);
      else if (act === 'add') send('selected_tags_add', {exact_tag: tag});
      else if (act === 'remove') send('selected_tags_remove', {exact_tag: tag});
      else if (act === 'toggle-selection') send(selectionSet().has(tag) ? 'selected_tags_remove' : 'selected_tags_add', {exact_tag: tag});
      else if (act === 'clear') send('selected_tags_clear', null);
      else if ((act === 'weight-up' || act === 'weight-down') && current) {
        send('selected_tags_weight', {exact_tag: tag, weight: clampWeight(Number(current.weight) + (act === 'weight-up' ? 0.1 : -0.1))});
      }
    });
    moduleBody.addEventListener('change', event => {
      const input = event.target;
      if (input?.dataset?.e621Weight !== undefined && input.dataset.e621Weight) {
        const value = Number(input.value);
        if (Number.isFinite(value)) send('selected_tags_weight', {exact_tag: input.dataset.e621Weight, weight: clampWeight(value)});
      } else if (input?.matches?.('[data-e621-pipeline]')) {
        send('use_main_pipeline', Boolean(input.checked));
      }
    });
    // 선택 태그 순서 = 생성 순서. 칩을 끌어 다른 칩 위에 놓으면 그 자리로 옮긴다.
    let dragging = '';
    moduleBody.addEventListener('dragstart', event => {
      const chip = event.target?.closest?.('[data-sel-tag]');
      if (!chip) return;
      dragging = chip.dataset.selTag;
      event.dataTransfer?.setData?.('text/plain', dragging);
      chip.classList.add('dragging');
    });
    moduleBody.addEventListener('dragover', event => {
      if (dragging && event.target?.closest?.('[data-sel-tag]')) event.preventDefault();
    });
    moduleBody.addEventListener('drop', event => {
      const chip = event.target?.closest?.('[data-sel-tag]');
      if (!dragging || !chip) return;
      event.preventDefault();
      const order = (lastState?.selected_tags || []).map(row => row.exact_tag);
      const index = order.indexOf(chip.dataset.selTag);
      if (index >= 0 && chip.dataset.selTag !== dragging) send('selected_tags_move', {exact_tag: dragging, index});
      dragging = '';
    });
    moduleBody.addEventListener('dragend', () => {
      dragging = '';
      moduleBody.querySelectorAll?.('.e621-sel-chip.dragging').forEach(el => el.classList.remove('dragging'));
    });
  }

  function renderTagButton(tag) {
    const selected = lastState && lastState.selected && lastState.selected.tag === tag.tag;
    const fields = matchFieldsOf(tag);
    const classes = [
      'e621-list-item',
      'e621-tag-item',
      selected ? 'selected' : '',
      tag.starred ? 'starred' : '',
      selectionSet().has(tag.tag) ? 'in-selection' : '',
      fields.length && fields.every(field => field === 'stored_body') ? 'wiki-match' : '',
    ].filter(Boolean).join(' ');
    const meta = `${tag.count_label || ''}${tag.starred ? ' ★' : ''}`;
    const coverage = [
      tag.has_body ? '본문' : '',
      tag.has_korean_description ? '한국어 설명' : '',
      tag.has_korean_search && !tag.has_korean_description ? '한글 검색어' : '',
    ].filter(Boolean).join(' · ') || (tag.review_status === 'metadata_unavailable' ? '설명 확인 불가' : '설명 없음');
    const koreanLabel = !lastState?.disable_translation && tag.kor
      ? `<span class="e621-tag-korean">${escHtml(tag.kor)}</span>` : '';
    // 검색 중이면 둘째 줄은 '어디서 맞았나', 아니면 '무슨 설명이 있나'.
    const second = fields.length
      ? `<span class="e621-match">${renderMatchChips(tag)}</span>`
      : `<span>${escHtml(coverage)}</span>`;
    return `<button class="${classes}" data-tag="${attr(tag.tag)}" onclick="e621SelectTag(this)">
      <span class="e621-tag-name"><span>${escHtml(tag.display)}</span>${koreanLabel}</span>
      <small class="e621-tag-status"><span>${escHtml(meta)}</span>${second}</small>
    </button>`;
  }

  function renderResearchDetails(state) {
    if (!state.selected) return '<div class="mod-empty e621-detail-empty">태그를 고르면 여기에 번역과 설명이 보입니다.</div>';
    const research = state.selected.research || {};
    const status = research.review_label || state.selected.review_label || '미검토';
    const source = research.description_source ? `<small>${escHtml(research.description_source)}</small>` : '';
    const missingKorean = research.review_status === 'metadata_unavailable'
      ? '한국어 설명 사전을 확인할 수 없습니다.' : '등록된 한국어 설명이 없습니다.';
    const descriptionEvidence = (research.description_evidence || []).map(item => `
      <small>${escHtml([item.site, item.retrieved_at?.slice(0, 10)].filter(Boolean).join(' · '))}</small>
      <pre class="e621-research-text">${escHtml(item.quote || '')}</pre>`).join('');
    const searchEvidence = (research.search_evidence || []).map(item => `
      <small>${escHtml(item.site || 'e621')}</small>
      <pre class="e621-research-text">${escHtml(item.quote || '')}</pre>`).join('');
    // 번역이 맨 위다(사용자 지정 2026-10-03 - 아래 띠에 눌려 늘 스크롤해야 보였다). 검토 상태는 번역 밑의 작은 줄.
    const korean = state.disable_translation ? '' : `
      <section class="e621-research-section e621-korean-section">
        ${research.korean_label ? `<strong class="e621-korean-label">${escHtml(research.korean_label)}</strong>` : ''}
        <pre class="e621-research-text e621-korean-text">${escHtml(research.korean_description || missingKorean)}</pre>
        ${research.korean_keywords ? `<small>검색어: ${escHtml(research.korean_keywords)}</small>` : ''}
        <div class="e621-research-meta e621-review-line"><span>${escHtml(status)}</span>${source}</div>
        ${research.search_review_status === 'reviewed_search_terms' ? '<small>한국어 검색어 · 직접 정의 대조 완료</small>' : ''}
        ${research.search_source_label ? `<small>${escHtml(research.search_source_label)}</small>` : ''}
        ${research.search_review_status === 'stale_evidence' ? '<small>한국어 검색어 · 근거 변경으로 적용 보류</small>' : ''}
        ${descriptionEvidence ? `<details><summary>설명 근거 발췌</summary>${descriptionEvidence}</details>` : ''}
        ${searchEvidence ? `<details><summary>검색어 근거 발췌</summary>${searchEvidence}</details>` : ''}
      </section>`;
    const body = state.wiki?.body ?? state.wiki?.text ?? '';
    const crosslinks = (research.cross_site_links || []).map(link => `
      <div class="e621-cross-site-card">
        <strong>${escHtml(`${link.site || 'danbooru'} · ${link.tag || ''}`)}</strong>
        <small>${escHtml([link.relation_label || link.relation, link.status_label || link.status].filter(Boolean).join(' · '))}</small>
        ${link.reason ? `<p>${escHtml(link.reason)}</p>` : ''}
        ${(link.sources || []).length ? `<details><summary>대조한 정의 발췌</summary>${link.sources.map(item => `
          <small>${escHtml(`${item.site || ''} · ${item.exact_tag || ''}`)}</small>
          <pre class="e621-research-text">${escHtml(item.quote || '')}</pre>`).join('')}</details>` : ''}
      </div>`).join('');
    const matchChips = renderMatchChips(state.selected);
    return `
      ${matchChips ? `<div class="e621-research-meta e621-selected-match"><span>검색 일치</span><span class="e621-match">${matchChips}</span></div>` : ''}
      ${korean}
      ${renderRelations(state.selected.relations)}
      <section class="e621-research-section">
        <div class="mod-section-label">저장된 위키 본문</div>
        <pre class="e621-research-text">${escHtml(body || '저장된 본문이 없습니다.')}</pre>
      </section>
      <section class="e621-research-section">
        <div class="mod-section-label">다른 사이트의 개념 연결</div>
        ${crosslinks || '<div class="mod-empty">등록된 연결이 없습니다.</div>'}
        ${crosslinks ? '<div class="e621-muted">연결 관계와 검토 상태를 참고용으로 표시합니다.</div>' : ''}
      </section>`;
  }

  function renderHiddenList(state) {
    if (!state.hidden_items || !state.hidden_items.length) {
      return '<div class="mod-empty">숨긴 태그 없음</div>';
    }
    return state.hidden_items.map(tag => `<button class="e621-hidden-item" data-tag="${attr(tag)}" onclick="e621RestoreHidden(this)">
      <span>${escHtml(tag.replace(/_/g, ' '))}</span>
      <small>복원</small>
    </button>`).join('');
  }

  function bindRenderedInputs() {
    const testbench = document.getElementById('e621Testbench');
    if (testbench && bindTagAssist) {
      bindTagAssist(testbench);
    }
  }

  function focusedE621Testbench() {
    const active = document.activeElement;
    if (!active || !moduleBody || !moduleBody.contains(active)) return null;
    if (active.tagName !== 'TEXTAREA' || active.id !== 'e621Testbench') return null;
    return active;
  }

  function e621StructureSignature(state) {
    if (!state || !state.data_loaded) return JSON.stringify({loaded: false, path: state?.data_path || ''});
    // Everything EXCEPT the testbench text (echoed per-keystroke by onTestbenchInput)
    // so a server echo for a local testbench edit keeps the same signature and never
    // replaces the focused #e621Testbench textarea.
    const rest = {...state};
    delete rest.testbench;
    return JSON.stringify(rest);
  }

  function clearDeferredE621Render() {
    if (deferredFocusTarget) deferredFocusTarget.removeEventListener('blur', flushDeferredE621Render);
    deferredFocusTarget = null;
    deferredFocusedRenderState = null;
  }

  function queueDeferredE621Render(textarea, state) {
    deferredFocusedRenderState = state;
    if (deferredFocusTarget === textarea) return;
    if (deferredFocusTarget) deferredFocusTarget.removeEventListener('blur', flushDeferredE621Render);
    deferredFocusTarget = textarea;
    textarea.addEventListener('blur', flushDeferredE621Render, {once: true});
  }

  function flushDeferredE621Render() {
    const pendingState = deferredFocusedRenderState;
    deferredFocusTarget = null;
    deferredFocusedRenderState = null;
    if (!pendingState) return;
    globalThis.setTimeout(() => { if (!focusedE621Testbench()) render(pendingState); }, 0);
  }

  function render(state) {
    // A server echo for a local testbench edit must not rebuild moduleBody.innerHTML
    // while the testbench is focused — replacing it drops focus and collapses tag
    // autocomplete (same regression fixed for Character/Img2Img: 38d3898 / c9edf4b).
    const structureSignature = e621StructureSignature(state);
    const focusedTextarea = focusedE621Testbench();
    if (focusedTextarea && lastRenderedStructureSignature === structureSignature) {
      lastState = state;
      queueDeferredE621Render(focusedTextarea, state);
      return;
    }
    clearDeferredE621Render();
    lastRenderedStructureSignature = structureSignature;
    lastState = state;
    if (!state.data_loaded) {
      moduleBody.innerHTML = `
        <div class="mod-section">
          <div class="mod-section-label">E621 Event Module</div>
          <div class="mod-empty">E621 데이터가 로드되지 않았습니다.</div>
          <div class="mod-status">${escHtml(state.data_path || '')}</div>
        </div>
      `;
      return;
    }

    const categories = state.categories || [];
    const general = categories.filter(item => item.section === 'General').map(renderCategoryButton).join('');
    const species = categories.filter(item => item.section === 'Species').map(renderCategoryButton).join('');
    const folders = state.folders && state.folders.length
      ? state.folders.map(renderFolderButton).join('')
      : '<div class="mod-empty">카테고리를 선택하세요</div>';
    const tags = state.tags && state.tags.length
      ? state.tags.map(renderTagButton).join('')
      : '<div class="mod-empty">태그 없음</div>';
    const selected = state.selected;
    const selectedName = selected ? selected.display : '선택된 태그 없음';
    const selectedMeta = selected
      ? `${selected.count_label}${selected.starred ? ' · starred' : ''}`
      : '';
    const offset = Number(state.tag_offset) || 0;
    const pageSize = Number(state.tag_page_size || state.tag_limit) || 300;
    const total = Number(state.tag_total) || 0;
    const shown = state.tags?.length || 0;
    const truncated = `<span class="e621-muted">${total ? `${offset + 1}–${offset + shown} / ${total}` : '0'} tags</span>`;
    const pagination = `
      <div class="e621-pagination">
        <button class="mod-btn-sm" ${state.has_previous ? '' : 'disabled'} onclick="setModuleParam('e621_event','tag_offset','${Math.max(0, offset - pageSize)}')" aria-label="이전 태그 페이지">이전</button>
        <span class="e621-muted">${total ? Math.floor(offset / pageSize) + 1 : 0} / ${Math.ceil(total / pageSize)}</span>
        <button class="mod-btn-sm" ${state.has_next ? '' : 'disabled'} onclick="setModuleParam('e621_event','tag_offset','${offset + pageSize}')" aria-label="다음 태그 페이지">다음</button>
      </div>`;
    const contentFilter = state.content_filter || 'all';
    const summary = state.research_summary || {};
    const noDescriptionLabel = summary.metadata_available === false ? '설명 미확인' : '설명 없음';
    const filterOptions = [['all', '전체 설명 상태'], ['with_body', '저장된 본문 있음'], ['with_korean', '한국어 설명 있음'], ['with_korean_search', '한글 검색어 있음'], ['without_description', noDescriptionLabel]]
      .map(([value, label]) => `<option value="${value}" ${contentFilter === value ? 'selected' : ''}>${label}</option>`).join('');
    const summaryText = Object.hasOwn(summary, 'total')
      ? `고유 태그 ${summary.total} · 저장된 본문 ${summary.with_body || 0} · 한글 검색 ${summary.with_korean_search || 0} · 한국어 설명 ${summary.with_korean_description || 0} · ${noDescriptionLabel} ${summary.without_description || 0}` : '';
    const translationControl = state.translation_control_visible === false ? '' : `
          <label class="mod-check-row">
            <input type="checkbox" ${state.disable_translation ? 'checked' : ''} oninput="setModuleParam('e621_event','disable_translation',String(this.checked))">
            <span>한국어 설명 숨김</span>
          </label>`;
    const wikiSearchControl = state.wiki_search_control_visible === false ? '' : `
          <label class="mod-check-row">
            <input type="checkbox" ${state.disable_wiki_search ? 'checked' : ''} oninput="setModuleParam('e621_event','disable_wiki_search',String(this.checked))">
            <span>저장된 본문 검색 제외</span>
          </label>`;
    const promptTestbench = state.prompt_testbench_visible === false ? '' : renderGenerationCard(state);
    const inSelection = selected ? selectionSet().has(selected.tag) : false;

    moduleBody.innerHTML = `
      <div class="e621-panel">
        <div class="e621-toolbar">
          <input class="mod-input" id="e621SearchInput" type="text" value="${attr(state.search_text || '')}" placeholder="영문 태그 · 한국어 이름과 설명 검색" onkeydown="if(event.key==='Enter')e621Search()">
          <button class="mod-btn-sm" onclick="e621Search()">검색</button>
          <button class="mod-btn-sm" onclick="e621Reset()">초기화</button>
        </div>

        <div class="e621-toolbar compact">
          <button class="mod-btn-sm${state.view_mode === 'default' ? ' active' : ''}" onclick="e621SetViewMode('default')">기본</button>
          <button class="mod-btn-sm${state.view_mode === 'starred' ? ' active' : ''}" onclick="e621SetViewMode('starred')">즐겨찾기</button>
          <label class="e621-description-filter">설명 상태
            <select class="mod-input" id="e621ContentFilter" data-native-select aria-label="설명 상태" onchange="setModuleParam('e621_event','content_filter',this.value)">${filterOptions}</select>
          </label>
${translationControl}
${wikiSearchControl}
          <div class="e621-research-summary">${escHtml(summaryText)}${summary.warning ? `<span>${escHtml(summary.warning)}</span>` : ''}</div>
        </div>

        <div class="e621-layout has-detail">
          <section class="e621-column categories">
            <div class="mod-section-label">General</div>
            <div class="e621-chip-grid">${general}</div>
            <div class="mod-section-label">Species</div>
            <div class="e621-chip-grid">${species}</div>
          </section>

          <section class="e621-column">
            <div class="mod-section-label">Folders</div>
            <div class="e621-scroll-list">${folders}</div>
          </section>

          <section class="e621-column">
            <div class="mod-section-label">Tags ${truncated}</div>
            <div class="e621-scroll-list">${tags}</div>
            ${pagination}
          </section>

          <section class="e621-column detail">
            <div class="mod-section-label">선택한 태그</div>
            <div class="e621-detail-card">
              <div class="e621-selected-head">
                <div>
                  <strong>${escHtml(selectedName)}</strong>
                  <small>${escHtml(selectedMeta)}</small>
                </div>
                <div class="e621-selected-actions">
                  <button class="mod-btn-sm e621-select-toggle${inSelection ? ' active' : ''}" data-e621-act="toggle-selection" data-tag="${attr(selected?.tag || '')}" ${selected ? '' : 'disabled'} title="생성 테스트의 선택 태그">${inSelection ? '✓ 선택됨' : '+ 선택'}</button>
                  <button class="mod-btn-sm" onclick="e621ToggleStar()" ${selected ? '' : 'disabled'}>${selected && selected.starred ? '즐겨찾기 해제' : '즐겨찾기'}</button>
                  <button class="mod-btn-sm danger" onclick="e621HideSelected()" ${selected ? '' : 'disabled'}>숨김</button>
                </div>
              </div>
              <div class="e621-research-details">${renderResearchDetails(state)}</div>
            </div>
          </section>
        </div>

        <div class="e621-bottom${promptTestbench ? '' : ' no-testbench'}">
${promptTestbench}
          <section class="e621-detail-card e621-hidden-card">
            <div class="e621-hidden-head">
              <div class="mod-section-label">숨긴 태그</div>
              <small>${state.hidden_total || 0}</small>
            </div>
            <div class="e621-hidden-list">${renderHiddenList(state)}</div>
          </section>
        </div>
      </div>
    `;
    bindRenderedInputs();
  }

  function search() {
    const input = document.getElementById('e621SearchInput');
    setModuleParam('e621_event', 'search', input ? input.value : '');
  }

  function reset() {
    setModuleParam('e621_event', 'reset', '1');
  }

  function setViewMode(value) {
    setModuleParam('e621_event', 'view_mode', value);
  }

  function selectCategory(element) {
    setModuleParam('e621_event', 'category', element.dataset.category || '');
  }

  function selectFolder(element) {
    setModuleParam('e621_event', 'level2', element.dataset.folder || '');
  }

  function selectTag(element) {
    setModuleParam('e621_event', 'selected_tag', element.dataset.tag || '');
  }

  function toggleStar() {
    const tag = selectedTagName();
    if (!tag) {
      if (showToast) showToast('Select a tag first', 'error');
      return;
    }
    setModuleParam('e621_event', 'toggle_star', tag);
  }

  function hideSelected() {
    const tag = selectedTagName();
    if (!tag) {
      if (showToast) showToast('Select a tag first', 'error');
      return;
    }
    setModuleParam('e621_event', 'hide', tag);
  }

  function restoreHidden(element) {
    setModuleParam('e621_event', 'restore', element.dataset.tag || '');
  }

  function onTestbenchInput(element) {
    setModuleParam('e621_event', 'testbench', element.value);
  }

  function generate() {
    const testbench = document.getElementById('e621Testbench');
    const value = testbench ? testbench.value : '';
    setModuleParam('e621_event', 'generate', value);
  }

  return {
    render,
    search,
    reset,
    setViewMode,
    selectCategory,
    selectFolder,
    selectTag,
    toggleStar,
    hideSelected,
    restoreHidden,
    onTestbenchInput,
    generate,
  };
}

// 패널 스타일은 style.css 가 아니라 패널과 함께 싣는다 - 패널이 그리는 곳(떠 있는 창 · 떼어 낸 창의 모듈 팝업)
// 어디서나 같아야 한다.
const STYLE_ID = 'e621-panel-style';
// 배치(사용자 지정 2026-10-03): [카테고리 | 폴더 | 태그 | 선택한 태그] + 아래 낮은 띠 [테스트벤치 | 숨긴 태그].
// 선택한 태그 칸이 창 높이를 다 쓴다 - 고른 태그 바로 옆에서 번역 · 본문 · (다음 단계의) 관계를 읽는다.
// 떼어 낸 창의 옛 모듈 팝업(style.css 의 .module-popup-e621 규칙)에도 같은 골격이 서도록 여기서 덮는다.
// ⚠️ 떠 있는 창(e621Window)의 규칙과 같은 속성을 다룰 때 그쪽이 한 단계 더 굵다 - 두 <style> 의 순서와 무관하게.
const PANEL_CSS = `
.e621-panel .e621-layout.has-detail{grid-template-columns:minmax(140px,0.75fr) minmax(110px,0.5fr) minmax(200px,1fr) minmax(250px,1.2fr)}
.e621-column.detail{display:flex;flex-direction:column;min-width:0;min-height:0}
.e621-column.detail .e621-detail-card{flex:1 1 auto;min-height:0;display:flex;flex-direction:column}
.e621-column.detail .e621-research-details{flex:1 1 auto;min-height:0;overflow:auto;margin-top:6px}
.e621-detail-empty{padding:18px 8px;text-align:center}
.e621-research-section.e621-korean-section{margin-top:6px;padding-top:0;border-top:none}
.e621-korean-label{display:block;color:var(--text-primary);font-size:13px;font-weight:700;line-height:1.35}
.e621-research-text.e621-korean-text{color:var(--text-primary);font-size:11.5px}
.e621-review-line{margin-top:4px;font-size:10px}
/* 상세의 작은 줄(검색어 · 검토 상태 · 근거 출처). <small> 이 기본 글꼴을 물려받아 13.3px - 이름(13px)보다 컸다. */
.e621-research-details small{display:block;margin-top:3px;color:var(--text-muted);font-size:10px;line-height:1.45}
.e621-bottom{display:grid;grid-template-columns:minmax(0,1fr) minmax(170px,0.38fr);gap:8px;min-height:0}
.e621-bottom.no-testbench{grid-template-columns:minmax(0,1fr)}
.e621-bottom .e621-detail-card{display:flex;flex-direction:column;min-height:0}
.e621-testbench-row{flex:1 1 auto;min-height:0;display:flex;gap:6px;align-items:stretch}
.e621-testbench-row #e621Testbench{flex:1 1 auto;min-width:0;height:auto;min-height:28px;resize:none}
.e621-testbench-row .mod-start{flex:0 0 auto;width:auto;height:auto;margin:0;padding:0 16px}
/* 아래 띠는 내용 높이(생성 테스트 카드)를 따른다 - 숨긴 태그 목록이 띠를 키우지 않게 상한을 둔다. */
.e621-hidden-card .e621-hidden-list{flex:1 1 auto;min-height:0;max-height:116px}
.module-popup-e621 .e621-panel{grid-template-rows:auto auto minmax(0,1fr) auto}

/* 생성 테스트: 머리줄 · 선택 태그 칩(가중치) · 함께 쓰임 추천 · 템플릿 + [생성] */
.e621-gen-card{gap:5px}
.e621-gen-head{display:flex;align-items:center;gap:8px}
.e621-gen-head .mod-section-label{flex:1 1 auto;padding:0}
.e621-gen-head .e621-pipeline-toggle{min-height:22px;padding:0;font-size:10.5px}
.e621-selection{display:flex;flex-wrap:wrap;gap:4px;max-height:58px;overflow:auto;padding:1px 0}
.e621-sel-empty{padding:3px 0;color:var(--text-dim);font-size:10.5px}
.e621-sel-chip{display:inline-flex;align-items:center;height:24px;border:1px solid var(--border-dim);border-radius:5px;
  background:rgba(255,255,255,0.03);overflow:hidden;cursor:grab}
.e621-sel-chip.up{border-color:rgba(232,180,106,0.55)}
.e621-sel-chip.down{border-color:rgba(110,170,230,0.55)}
.e621-sel-chip.dragging{opacity:0.45}
.e621-sel-chip button{height:100%;padding:0 5px;border:none;background:transparent;color:var(--text-muted);font-size:11px;cursor:pointer}
.e621-sel-chip button:hover{background:rgba(255,255,255,0.06);color:var(--text-primary)}
.e621-sel-chip .e621-sel-name{max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  color:var(--text-primary);font-family:var(--font-mono);font-size:10.5px}
.e621-sel-chip .e621-sel-weight{width:40px;height:100%;padding:0;border:none;border-left:1px solid var(--border-dim);
  border-right:1px solid var(--border-dim);background:rgba(0,0,0,0.25);color:var(--text-primary);font-family:var(--font-mono);
  font-size:10.5px;text-align:center;-moz-appearance:textfield;appearance:textfield}
.e621-sel-chip .e621-sel-weight::-webkit-inner-spin-button,.e621-sel-chip .e621-sel-weight::-webkit-outer-spin-button{-webkit-appearance:none;margin:0}
.e621-sel-chip.up .e621-sel-weight{color:#f0c987}
.e621-sel-chip.down .e621-sel-weight{color:#9cc8f0}
.e621-sel-chip .e621-sel-x{font-size:13px}
.e621-sel-chip .e621-sel-x:hover{color:#ff8a8a}
.e621-suggest{display:flex;align-items:flex-start;gap:6px;max-height:48px;overflow:auto}

/* 관계(선택한 태그 칸) · 추천 칩: 이름 = 그 태그로 가기, + = 선택에 추가 */
.e621-relations .mod-section-label .e621-rel-snapshot{display:inline;margin:0 0 0 4px;color:var(--text-dim);font-size:9px;font-weight:400}
.e621-rel-row{display:flex;align-items:flex-start;gap:6px;margin-top:4px}
.e621-rel-label{flex:0 0 auto;min-width:30px;padding-top:3px;color:var(--text-dim);font-size:10px;font-weight:700;cursor:help}
.e621-rel-chips{display:flex;flex-wrap:wrap;gap:3px;min-width:0}
.e621-rel-chip{display:inline-flex;align-items:center;height:20px;border:1px solid var(--border-dim);border-radius:4px;
  background:rgba(255,255,255,0.02);overflow:hidden}
.e621-rel-chip.in-selection{border-color:rgba(157,223,168,0.45)}
.e621-rel-chip button{height:100%;padding:0 6px;border:none;background:transparent;color:var(--text-muted);
  font-family:var(--font-mono);font-size:10px;cursor:pointer}
.e621-rel-chip button:hover{background:rgba(255,255,255,0.06);color:var(--text-primary)}
.e621-rel-chip .e621-rel-add{padding:0 5px;border-left:1px solid var(--border-dim);font-size:12px}
.e621-research-details .e621-rel-chip small,.e621-rel-chip small{display:inline;margin:0;color:var(--text-dim);font-size:9px}
.e621-rel-added{padding:0 5px;color:#9ddfa8;font-size:10px}
.e621-rel-more,.e621-rel-alias{padding:3px 2px 0;color:var(--text-dim);font-size:10px}
.e621-tag-item.in-selection{box-shadow:inset 3px 0 0 rgba(157,223,168,0.75)}
.e621-selected-actions .e621-select-toggle.active{border-color:rgba(157,223,168,0.6);color:#9ddfa8}
@media (max-width: 767px){
  .e621-panel .e621-layout.has-detail,.e621-bottom{grid-template-columns:minmax(0,1fr)}
  .e621-column.detail .e621-research-details{max-height:320px}
}
`;
// 일치 이유 칩: 초록 = 이름 · 한국어에서 맞음, 보라 = 이름이 통째로 같음, 회색 = 본문에서만 맞음, 점선 = 띄어쓰기를 빼고 맞음.
const MATCH_CSS = `
.e621-tag-status > .e621-match,.e621-selected-match .e621-match{display:inline-flex;flex-wrap:wrap;justify-content:flex-end;gap:3px}
.e621-selected-match{margin-top:4px}
.e621-selected-match .e621-match{justify-content:flex-start}
.e621-match-chip{display:inline-block;padding:0 5px;border:1px solid rgba(144,238,144,0.38);border-radius:3px;
  background:rgba(144,238,144,0.07);color:#b9e3b9;font-family:var(--font-display);font-size:9px;font-weight:600;line-height:15px;white-space:nowrap}
.e621-match-chip.exact{border-color:rgba(157,139,255,0.6);background:rgba(157,139,255,0.14);color:#d2c9ff}
.e621-match-chip.body{border-color:rgba(170,170,170,0.32);background:transparent;color:#a8a8a8}
.e621-match-chip.compact{border-style:dashed}
`;

function ensureStyle(doc) {
  // 시험용 가짜 document(head · createElement 없음)에서도 패널은 살아야 한다.
  if (!doc || !doc.head || typeof doc.createElement !== 'function' || doc.getElementById(STYLE_ID)) return;
  const style = doc.createElement('style');
  style.id = STYLE_ID;
  style.textContent = PANEL_CSS + MATCH_CSS;
  doc.head.appendChild(style);
}
