// Interactive 슬롯 계층 브라우저 — [ 분류 | 태그 | 하위 ] 3단 드릴다운.
//
// 타이핑 없이 카테고리를 훑어 태그를 찾는다(Dev0714 TagViewer 구조). 자동완성(타이핑)과
// 공존한다 — 입력창은 그대로 두고, 그 아래 이 브라우저가 붙는다.
//
// 항목 조작:
//   [ ☐ 체크박스 ] 클릭 -> 그 태그를 슬롯에 넣거나 뺀다(토글). "dress" 같은 상위 태그도 선택 가능.
//   [ 라벨 ] 클릭      -> children 있으면 하위 탐색(드릴/펼침), 없으면(잎) 선택 토글.
//
// 계층 깊이는 최대 4단(subgroup -> 태그 -> children -> grandchildren). 컬럼은 3개 고정,
// Depth3(하위) 열은 인라인 확장 트리라 4단+를 담는다.
//
// 백엔드 계약: interactive_browse {axis, subgroup?, parent?, offset?, limit?}
//
// cache-bust marker: 20260724-iab4

export function createInteractiveBrowse({
  document,
  escHtml = value => String(value == null ? '' : value),
  send,
} = {}) {
  let mount = null;
  let onPick = () => {};
  let getExisting = () => [];

  let axis = '';
  let reqSeq = 0;
  let uidSeq = 0;
  let tip = null;

  let d1 = emptyCol();
  let d2 = {...emptyCol(), subgroup: '', hasMore: false, offset: 0};
  let d3 = {roots: [], parent: '', loading: false};

  // 진행 중 요청. 열 단위(d1/d2/d3root)는 "최신 요청 id" 하나만 유효(Codex H2) — 그 열의
  // 이전 요청 응답은 폐기. inline(트리 노드)은 노드 객체에 reqId 를 심어 개별 추적.
  const latest = {d1: '', d2: '', d3root: ''};
  const pending = new Map();   // requestId -> {kind, ...}
  const uidMap = new Map();    // uid -> tree node (H5: tag 아닌 고유 id 로 노드 식별)

  function emptyCol() { return {items: [], sel: '', loading: false}; }

  function makeNode(item) {
    const uid = `n${++uidSeq}`;
    const node = {
      uid, tag: item.tag, count: item.count || 0, desc: item.desc || '',
      hasChildren: !!item.hasChildren, expanded: false, loading: false,
      reqId: '', children: [],
    };
    uidMap.set(uid, node);
    return node;
  }

  // ---------------------------------------------------------------- requests

  function issue(kind, payload, extra = {}) {
    if (typeof send !== 'function' || !mount) return null;
    const requestId = `iab_${++reqSeq}`;
    pending.set(requestId, {kind, ...extra});
    if (kind in latest) latest[kind] = requestId;
    try { send({type: 'interactive_browse', axis, ...payload, requestId}); return requestId; }
    catch (error) { pending.delete(requestId); return null; }
  }

  function loadSubgroups() {
    if (!mount) return;
    d1.loading = true; render();
    if (!issue('d1', {})) { d1.loading = false; render(); }
  }
  function loadTags(subgroup, offset = 0) {
    if (d2.loading) return;   // M8: 중복 요청 방지
    d2.loading = true; render();
    if (!issue('d2', {subgroup, offset}, {subgroup, offset})) { d2.loading = false; render(); }
  }
  function loadD3Root(parentTag) {
    d3.loading = true; render();
    if (!issue('d3root', {parent: parentTag}, {parent: parentTag})) { d3.loading = false; render(); }
  }
  function loadInline(node) {
    if (node.loading) return;   // M8
    node.loading = true; render();
    const rid = issue('inline', {parent: node.tag}, {uid: node.uid});
    if (rid) node.reqId = rid; else { node.loading = false; render(); }
  }

  function onResult(message) {
    const rid = String(message?.requestId || '');
    const ctx = pending.get(rid);
    if (!ctx) return;
    pending.delete(rid);
    const items = Array.isArray(message?.items) ? message.items : [];

    if (ctx.kind === 'd1') {
      if (latest.d1 !== rid) return;   // superseded
      d1.items = items; d1.loading = false;
    } else if (ctx.kind === 'd2') {
      if (latest.d2 !== rid) return;
      // 응답이 현재 선택된 subgroup 것인지 재확인(A->B 전환 중 A 응답 방지, H2).
      if (String(message.subgroup || ctx.subgroup) !== d2.subgroup) return;
      d2.items = ctx.offset > 0 ? d2.items.concat(items) : items;
      d2.hasMore = !!message.hasMore;
      d2.offset = (ctx.offset || 0) + items.length;
      d2.loading = false;
    } else if (ctx.kind === 'd3root') {
      if (latest.d3root !== rid) return;
      if (String(message.parent || ctx.parent) !== d3.parent) return;
      d3.roots = items.map(makeNode); d3.loading = false;
    } else { // inline
      const node = uidMap.get(ctx.uid);
      if (!node || node.reqId !== rid) return;   // 노드가 사라졌거나 더 새로운 요청이 있음
      node.children = items.map(makeNode); node.expanded = true; node.loading = false; node.reqId = '';
    }
    render();
  }

  // ---------------------------------------------------------------- render

  function checkbox(tag) {
    const on = new Set((getExisting() || []).map(t => String(t).toLowerCase())).has(String(tag).toLowerCase());
    return `<button type="button" class="ia-brz-check${on ? ' on' : ''}" data-check="${escHtml(tag)}" ` +
      `aria-label="${on ? '선택 해제' : '선택'}" role="checkbox" aria-checked="${on}">${on ? '☑' : '☐'}</button>`;
  }

  function subgroupRow(item) {
    return `<button type="button" class="ia-brz-item ia-brz-drillrow${item.id === d1.sel ? ' selected' : ''}" ` +
      `data-sub="${escHtml(item.id)}">` +
      `<span class="ia-brz-label">${escHtml(item.label)}</span><span class="ia-brz-count">${item.count}</span></button>`;
  }

  function tagRow(item) {
    // 라벨 클릭 = children 있으면 드릴(Depth3), 없으면 선택.
    const descAttr = item.desc ? ` data-desc="${escHtml(item.desc)}"` : '';
    const cls = item.hasChildren ? 'ia-brz-drill-label' : 'ia-brz-pick-label';
    const arrow = item.hasChildren ? '<span class="ia-brz-arrow">▸</span>' : '';
    return `<div class="ia-brz-row">${checkbox(item.tag)}` +
      `<button type="button" class="ia-brz-rowlabel ${cls}${item.hasChildren ? ' is-drill' : ''}" ` +
      `data-tag="${escHtml(item.tag)}" data-haschildren="${item.hasChildren ? 1 : 0}"${descAttr}>` +
      `<span class="ia-brz-label">${escHtml(item.tag)}</span>${arrow}</button></div>`;
  }

  function treeNode(node, depth) {
    const descAttr = node.desc ? ` data-desc="${escHtml(node.desc)}"` : '';
    const caret = node.hasChildren
      ? `<button type="button" class="ia-brz-caret${node.expanded ? ' open' : ''}" data-caret="${node.uid}" aria-label="펼치기">${node.loading ? '…' : '▸'}</button>`
      : '<span class="ia-brz-caret-spacer"></span>';
    const label = `<button type="button" class="ia-brz-rowlabel${node.hasChildren ? ' is-drill' : ''}" ` +
      `data-tnode="${node.uid}"${descAttr}><span class="ia-brz-label">${escHtml(node.tag)}</span></button>`;
    let html = `<div class="ia-brz-tnode" style="padding-left:${depth * 12}px">${caret}${checkbox(node.tag)}${label}</div>`;
    if (node.expanded && node.children.length) {
      html += node.children.map(ch => treeNode(ch, depth + 1)).join('');
    }
    return html;
  }

  function colBody(loading, items, renderItem, emptyText, more) {
    if (loading && !items.length) return '<div class="ia-brz-empty">불러오는 중…</div>';
    if (!items.length) return `<div class="ia-brz-empty">${escHtml(emptyText)}</div>`;
    let html = items.map(renderItem).join('');
    if (more) html += '<button type="button" class="ia-brz-more" data-more="1">더 보기</button>';
    return html;
  }

  function render() {
    if (!mount) return;
    // 스크롤 보존: innerHTML 교체는 각 컬럼의 scrollTop 을 0 으로 리셋한다(선택 토글마다
    // 목록이 위로 튀는 원인). 교체 전 저장하고 후에 복원한다.
    const scrolls = {};
    mount.querySelectorAll('.ia-brz-col-body').forEach(b => {
      scrolls[b.parentElement.dataset.colkey] = b.scrollTop;
    });

    const d2title = d2.subgroup ? subgroupLabel(d2.subgroup) : '태그';
    const d3title = d3.parent || '하위';
    const d3body = (d3.loading && !d3.roots.length) ? '<div class="ia-brz-empty">불러오는 중…</div>'
      : (!d3.roots.length ? '<div class="ia-brz-empty">태그 라벨을 클릭하면 하위가 열립니다</div>'
      : d3.roots.map(n => treeNode(n, 0)).join(''));

    mount.innerHTML = `<div class="ia-brz">
      <div class="ia-brz-col" data-colkey="d1">
        <div class="ia-brz-col-title">분류</div>
        <div class="ia-brz-col-body">${colBody(d1.loading, d1.items, subgroupRow, '분류 없음')}</div>
      </div>
      <div class="ia-brz-col" data-colkey="d2">
        <div class="ia-brz-col-title">${escHtml(d2title)}</div>
        <div class="ia-brz-col-body">${colBody(d2.loading, d2.items, tagRow, '분류를 선택하세요', d2.hasMore && !d2.loading)}</div>
      </div>
      <div class="ia-brz-col" data-colkey="d3">
        <div class="ia-brz-col-title">${escHtml(d3title)}</div>
        <div class="ia-brz-col-body">${d3body}</div>
      </div>
    </div>`;

    mount.querySelectorAll('.ia-brz-col-body').forEach(b => {
      const s = scrolls[b.parentElement.dataset.colkey];
      if (s) b.scrollTop = s;
    });
    bind();
  }

  function subgroupLabel(id) {
    const found = d1.items.find(i => i.id === id);
    return found ? found.label : id;
  }

  function bind() {
    if (!mount) return;
    mount.querySelectorAll('.ia-brz-drillrow').forEach(el => {
      el.addEventListener('click', () => onSubgroup(el.dataset.sub));
    });
    mount.querySelectorAll('[data-check]').forEach(el => {
      el.addEventListener('click', e => { e.stopPropagation(); onPick(el.dataset.check); });
    });
    // d2 라벨: children 있으면 드릴, 없으면 선택
    mount.querySelectorAll('.ia-brz-col[data-colkey="d2"] [data-tag]').forEach(el => {
      el.addEventListener('click', () => {
        if (el.dataset.haschildren === '1') onDrillToD3(el.dataset.tag);
        else onPick(el.dataset.tag);
      });
      bindHover(el);
    });
    // d3 트리 라벨: children 있으면 인라인 펼침, 없으면 선택
    mount.querySelectorAll('[data-tnode]').forEach(el => {
      el.addEventListener('click', () => {
        const node = uidMap.get(el.dataset.tnode);
        if (node && node.hasChildren) onToggleTree(node.uid);
        else if (node) onPick(node.tag);
      });
      bindHover(el);
    });
    mount.querySelectorAll('[data-caret]').forEach(el => {
      el.addEventListener('click', e => { e.stopPropagation(); onToggleTree(el.dataset.caret); });
    });
    const more = mount.querySelector('[data-more]');
    if (more) more.addEventListener('click', () => loadTags(d2.subgroup, d2.offset));
  }

  function bindHover(el) {
    if (!el.dataset.desc) return;
    el.addEventListener('mouseenter', () => showTip(el, el.dataset.desc));
    el.addEventListener('mouseleave', hideTip);
  }

  // ---------------------------------------------------------------- actions

  function onSubgroup(id) {
    d1.sel = id;
    d2 = {...emptyCol(), subgroup: id, hasMore: false, offset: 0};
    d3 = {roots: [], parent: '', loading: false};
    uidMap.clear();
    loadTags(id);
  }

  function onDrillToD3(tag) {
    d2.sel = tag;
    d3 = {roots: [], parent: tag, loading: false};
    uidMap.clear();
    loadD3Root(tag);
  }

  function onToggleTree(uid) {
    const node = uidMap.get(uid);
    if (!node || !node.hasChildren) return;
    if (node.expanded) { node.expanded = false; render(); return; }
    if (node.children.length) { node.expanded = true; render(); return; }
    loadInline(node);
  }

  // ---------------------------------------------------------------- tooltip

  function ensureTip() {
    if (tip) return tip;
    tip = document.createElement('div');
    tip.className = 'ia-brz-tip';
    tip.hidden = true;
    document.body.appendChild(tip);
    return tip;
  }
  function showTip(el, desc) {
    ensureTip();
    tip.textContent = desc; tip.hidden = false;
    const r = el.getBoundingClientRect();
    const w = tip.offsetWidth;
    const view = (document.defaultView || window);
    let left = r.right + 8;
    if (left + w > view.innerWidth - 8) left = Math.max(8, r.left - w - 8);
    tip.style.left = `${Math.round(left)}px`;
    tip.style.top = `${Math.round(r.top)}px`;
  }
  function hideTip() { if (tip) tip.hidden = true; }

  // ---------------------------------------------------------------- api

  function attach(nextMount, {axis: nextAxis = '', onPick: pick = () => {}, getExisting: existing = () => []} = {}) {
    detach();
    mount = nextMount || null;
    onPick = typeof pick === 'function' ? pick : () => {};
    getExisting = typeof existing === 'function' ? existing : () => [];
    axis = String(nextAxis || '');
    reset();
  }
  function detach() {
    mount = null; pending.clear(); uidMap.clear(); hideTip();
    latest.d1 = latest.d2 = latest.d3root = '';
  }
  function reset() {
    d1 = emptyCol();
    d2 = {...emptyCol(), subgroup: '', hasMore: false, offset: 0};
    d3 = {roots: [], parent: '', loading: false};
    pending.clear(); uidMap.clear();
    latest.d1 = latest.d2 = latest.d3root = '';
    if (axis && mount) loadSubgroups();
    else render();
  }
  function refreshDupes() { render(); }

  return {attach, detach, reset, onResult, refreshDupes,
    destroy: () => { detach(); if (tip) { tip.remove(); tip = null; } }};
}
