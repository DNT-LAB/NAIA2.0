/** Wire-Flow · 조건부 와일드카드(사용자 지시 2026-10-31) - 노드를 선으로 잇는 떠 있는 창.
 *
 *      ┌─ Wire-Flow · 조건부 와일드카드 ─── [모드] [저장] [—][×] ┐
 *      │ 노드 목록 │ 캔버스(끌기 · 잇기 · 휠 확대)   ┌ 워크플로우 ▲ ┐ │
 *      │  입력     │   [메인] ──▶ [Switch] ─예─▶ … │ 날씨 분기 ● │ │
 *      │  조건 …   │                    └아니오▶ … └──────────────┘ │
 *      └ 초안 · 아직 생성에 적용되지 않습니다 ──────────────────────┘
 *
 *  - 선(wire) = **실행 흐름**. 노드는 공유 상태(메인 · 캐릭터 · 네거티브 · 변수)를 고치고 다음으로 넘긴다.
 *    Switch 만 갈래가 둘(예 / 아니오). 출력 포트 하나엔 선 하나(흐름이 갈리지 않게) · 입력 포트는 여럿을 받는다.
 *  - 목록은 공용(프리셋과 무관) · 한 번에 하나만 '사용'. 저장소 = 서버 core/wireflow_store.py(노드 종류 · 포트가 계약).
 *  - 모드가 켜지면 결과 가장자리의 E · S 를 숨기고 W 를 그 자리에 띄운다 · 서버는 조건부 프롬프트를 쉰다.
 *  ⚠️ 초안: 그래프는 저장만 한다 - 생성은 아직 그래프를 실행하지 않는다(다음 단계 = 실행 엔진).
 *  ⚠️ 아래 CSS 는 템플릿 문자열 안이다 - 주석에 백틱을 쓰면 모듈 전체가 죽는다.
 */
import {createDraggablePanel} from './draggablePanel.mjs?v=20260926-childalign';

const STYLE_ID = 'wireflow-style';
const LIST_KEY = 'naia.wireflow.listCollapsed';
// 디버깅 모드(기기별) - 켜야 노드마다 Probe 가 보인다(사용자 지시 2026-10-31: 기본은 숨김).
const DEBUG_KEY = 'naia.wireflow.debug';
const PROBE_LEVELS = 3;        // 0 = 한 줄 요약 · 1 = 바뀐 것 · 2 = 그 지점의 전체 상태
function areaLabel(area) {
  if (area === 'main') return '메인';
  if (area === 'prefix') return '앞';
  if (area === 'postfix') return '뒤';
  if (area === 'neg') return '네거티브';
  if (area.startsWith('char:')) return `캐릭터 ${area.slice(5)}`;
  if (area.startsWith('uc:')) return `캐릭터 ${area.slice(3)} UC`;
  return area;
}
const SLOTS = [1, 2, 3, 4, 5, 6];

// 노드 종류 - 서버 NODE_PORTS 와 같은 이름 · 같은 포트여야 한다(다르면 저장이 거절된다).
// 노드는 '넣을 곳' 을 고르지 않는다 - 흘러온 줄기(시작한 입력 노드: 메인 / 캐릭터 N)를 읽고 고친다(사용자 결정 2026-11-01).
const NODE_TYPES = {
  input_main: {group: '입력', label: '메인 프롬프트', tone: 'in', ins: [], outs: [['out', '']],
    fields: [], note: '흐름의 시작 · 메인 태그'},
  input_character: {group: '입력', label: '캐릭터 슬롯', tone: 'in', ins: [], outs: [['out', '']],
    fields: [{key: 'slot', kind: 'select', label: '슬롯', options: SLOTS.map(n => [String(n), `캐릭터 ${n}`]), def: '1'}]},
  // if / elif / else - 위에서부터 처음 맞는 줄 하나로 나간다. 줄마다 나가는 점(b1 · b2 …) + else(사용자 지시 2026-11-01).
  // 줄 = 태그 조건(조건부 프롬프트 문법) 또는 %wet >= 1 같은 변수 비교 · 섞어 써도 된다.
  switch: {group: '조건', label: 'Switch', tone: 'cond', ins: ['in'], outs: [],
    fields: [{key: 'conds', kind: 'branches', label: '조건', def: ''}]},
  wildcard_open: {group: '처리', label: '와일드카드 열기', tone: 'proc', ins: ['in'], outs: [['out', '']],
    fields: [{key: 'wildcard', kind: 'text', label: '와일드카드', placeholder: '__weather__', def: ''},
      {key: 'capture', kind: 'text', label: '뽑기 이름', placeholder: '(선택) weather', def: ''}]},
  tag_edit: {group: '처리', label: '태그 추가·바꾸기', tone: 'proc', ins: ['in'], outs: [['out', '']],
    fields: [{key: 'op', kind: 'select', label: '동작', options: [['add', '추가'], ['replace', '바꾸기'], ['remove', '빼기']], def: 'add'},
      {key: 'tags', kind: 'text', label: '태그', placeholder: 'indoors', def: ''},
      {key: 'with', kind: 'text', label: '바꿀 태그', placeholder: '(바꾸기만)', def: ''}]},
  var_set: {group: '처리', label: '변수 저장', tone: 'var', ins: ['in'], outs: [['out', '']],
    fields: [{key: 'var', kind: 'text', label: '변수', placeholder: 'wet', def: ''},
      {key: 'op', kind: 'select', label: '동작', options: [['set', '= 넣기'], ['add', '+ 더하기']], def: 'set'},
      {key: 'value', kind: 'number', label: '값', def: 1},
      {key: 'when', kind: 'text', label: '조건', placeholder: '(선택) 뽑기에 rain', def: ''}]},
  concat: {group: '처리', label: 'Concat', tone: 'proc', ins: ['in'], outs: [['out', '']],
    fields: [{key: 'source', kind: 'text', label: '무엇을', placeholder: '__event__, @outfit, <a|b>', def: ''},
      {key: 'pos', kind: 'select', label: '위치', options: [['back', '뒤에 붙이기'], ['front', '앞에 붙이기'], ['replace', '비우고 넣기']], def: 'back'},
      {key: 'capture', kind: 'text', label: '뽑기 이름', placeholder: '(선택) event', def: ''}]},
  instant_wildcard: {group: '처리', label: '인스턴트 와일드카드', tone: 'proc', ins: ['in'], outs: [['out', '']],
    note: '흘러온 프롬프트에 한 줄을 뽑아 끼움',
    fields: [{key: 'lines', kind: 'lines', label: '후보', placeholder: 'rain, wet hair\n30:snow, breath\n__weather__, sunset', def: ''},
      {key: 'pos', kind: 'select', label: '위치', options: [['back', '뒤에 붙이기'], ['front', '앞에 붙이기']], def: 'back'},
      {key: 'capture', kind: 'text', label: '뽑기 이름', placeholder: '(선택) sky', def: ''}]},
  output_prompt: {group: '출력', label: '프롬프트', tone: 'out', ins: ['in'], outs: [['out', '']],
    note: '흘러온 프롬프트에 더함',
    fields: [{key: 'tags', kind: 'text', label: '+= 태그', placeholder: 'wet hair', def: ''}]},
  output_negative: {group: '출력', label: '네거티브', tone: 'out', ins: ['in'], outs: [['out', '']],
    note: '메인 → 메인 네거티브 · 캐릭터 N → 그 캐릭터 UC',
    fields: [{key: 'tags', kind: 'text', label: '+= 태그', placeholder: 'umbrella', def: ''}]},
  final_prompt: {group: '출력', label: 'Final Prompt', tone: 'out', ins: ['in'], outs: [],
    note: 'PE 선행 + 메인 + PE 후행 → 메인 프롬프트 대치',
    fields: [{key: 'pre', kind: 'select', label: 'PE 선행', options: [['on', '붙임'], ['off', '안 붙임']], def: 'on'},
      {key: 'post', kind: 'select', label: 'PE 후행', options: [['on', '붙임'], ['off', '안 붙임']], def: 'on'}]},
};
const GROUPS = ['입력', '조건', '처리', '출력'];
const PORT_COLOR = {branch: '#1D9E75', else: '#D85A30', out: '#8a8aa0'};
function portColor(port) {
  if (port === 'else') return PORT_COLOR.else;
  return /^b\d+$/.test(port) ? PORT_COLOR.branch : PORT_COLOR.out;
}
// Switch 의 조건 줄 - 첫 줄 = if · 나머지 = elif (서버 wireflow_store.switch_rows 와 같다)
function switchRows(node) { return String(node.params.conds ?? '').replace(/\r/g, '').split('\n'); }

function esc(value) {
  return String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
function newId(prefix) { return `${prefix}${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`; }
function readFlag(key) { try { return localStorage.getItem(key) === '1'; } catch { return false; } }
function writeFlag(key, on) { try { localStorage.setItem(key, on ? '1' : '0'); } catch { /* 기기 편의일 뿐 */ } }

async function request(path, body) {
  const res = await fetch(path, {method: body ? 'POST' : 'GET', cache: 'no-store',
    headers: {'Content-Type': 'application/json'}, body: body ? JSON.stringify(body) : undefined});
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok === false) throw new Error(data.message || `HTTP ${res.status}`);
  return data;
}

function defaultParams(type) {
  const out = {};
  for (const field of NODE_TYPES[type].fields) out[field.key] = field.def;
  return out;
}
function starterGraph() {
  return {nodes: [{id: newId('n'), type: 'input_main', x: 40, y: 60, params: {}}], edges: []};
}

export function installWireFlow({
  document: doc,
  window: win = (typeof window !== 'undefined' ? window : null),
  showToast = () => {},
  confirmDialog = null,
  promptDialog = null,
  // 테스트 입력의 기본값 - 지금 메인 · 네거티브 칸(캐릭터는 서버가 지금 캐릭터 설정에서 채운다).
  getPromptText = () => '',
  getNegativeText = () => '',
  // 모드 · 창 열림이 바뀌었다 - 런처 줄(체크 · 배지)을 다시 그린다.
  onChange = () => {},
} = {}) {
  ensureStyle(doc);

  let state = {mode_on: false, active_id: '', workflows: []};
  let panel = null;
  let graph = starterGraph();
  let currentId = '';          // 캔버스에 열린 워크플로우(빈 값 = 저장 안 된 초안)
  let dirty = false;
  let selected = null;         // {kind: 'node' | 'edge', id}
  let view = {x: 0, y: 0, z: 1};
  let listCollapsed = readFlag(LIST_KEY);
  let gesture = null;          // 끌기 하나(노드 · 화면 · 선 · 팔레트)
  let els = {};
  let debug = readFlag(DEBUG_KEY);
  let result = null;           // 마지막 테스트 실행의 응답(final · probes · visits)
  let resultStale = false;     // 테스트 뒤에 그래프를 고쳤다 - Probe 는 옛 그래프의 것
  let testing = false;
  const probeLevel = new Map(); // 노드 id -> 0 | 1 | 2

  // ── 결과 가장자리의 W 단추 ─────────────────────────────────────────────
  const wTab = doc.createElement('button');
  wTab.type = 'button';
  wTab.className = 'em-tab';
  wTab.id = 'wireflowTab';
  wTab.hidden = true;
  wTab.textContent = 'W';
  wTab.setAttribute('aria-label', 'Wire-Flow 워크플로우 펼치기');
  wTab.dataset.naiaTitle = 'Wire-Flow · 조건부 와일드카드 - 모드가 켜져 있는 동안 E · S 대신 여기 뜹니다';
  const assistTab = doc.getElementById('assistTab');
  if (assistTab?.parentNode) assistTab.parentNode.insertBefore(wTab, assistTab);
  wTab.addEventListener('click', () => toggle());

  function applyMode() {
    const on = Boolean(state.mode_on);
    if (on) doc.body.dataset.wireflow = 'on';
    else delete doc.body.dataset.wireflow;
    wTab.hidden = !on;
    wTab.setAttribute('aria-pressed', panel?.isOpen() ? 'true' : 'false');
    if (els.mode) els.mode.checked = on;
    onChange();
  }

  function takeState(data) {
    state = {mode_on: data.mode_on === true, active_id: String(data.active_id || ''),
      workflows: Array.isArray(data.workflows) ? data.workflows : []};
    // 다른 창에서 지워진 워크플로우를 열고 있었다 - 캔버스는 남기고 초안으로 돌린다(그린 것을 잃지 않게).
    if (currentId && !state.workflows.some(wf => wf.id === currentId)) { currentId = ''; dirty = true; }
    applyMode();
    paintList();
    paintStatus();
  }

  async function reload() {
    try { takeState(await request('/api/wireflow')); } catch (error) { console.warn('wireflow state', error); }
  }

  async function act(body) {
    const data = await request('/api/wireflow', body);
    takeState(data);
    return data;
  }

  async function setMode(on) {
    try { await act({action: 'mode', on: Boolean(on)}); } catch (error) {
      showToast(`Wire-Flow 모드를 바꾸지 못했습니다 — ${error.message}`, 'error');
      applyMode();
    }
  }

  // ── 창 ─────────────────────────────────────────────────────────────────
  function ensurePanel() {
    if (panel) return panel;
    panel = createDraggablePanel({
      document: doc, window: win, id: 'wireflowWindow', title: 'Wire-Flow · 조건부 와일드카드',
      variant: 'em-overlay em-window wf-window', storageKey: 'wireflow',
      width: 1000, height: 600, minWidth: 560, maxWidth: 1800, minHeight: 320, resizable: true,
      onOpen: () => {
        applyMode();
        paintAll();
        // 손대지 않은 초안이면 '사용' 중인 워크플로우를 연다 - W 를 누르면 지금 도는 흐름이 보여야 한다.
        if (!currentId && !dirty && state.active_id) loadWorkflow(state.active_id);
      },
      onClose: () => { gesture = null; applyMode(); },
    });
    panel.slot.innerHTML = `
      <span class="wf-head-note" data-wf-note></span>
      <label class="wf-mode" data-module-tooltip="켜면 조건부 프롬프트 · E · S 가 일시 해제됩니다">
        <input type="checkbox" data-wf-mode><span>모드</span></label>
      <label class="wf-mode" data-module-tooltip="켜면 노드마다 Probe(테스트 실행 결과)가 보입니다">
        <input type="checkbox" data-wf-debug><span>디버그</span></label>
      <button type="button" class="wf-btn" data-wf-save>저장</button>`;
    panel.body.innerHTML = `
      <div class="wf">
        <div class="wf-pal">
          <input class="wf-find" type="search" placeholder="노드 찾기" data-wf-find>
          <div data-wf-chips></div>
        </div>
        <div class="wf-canvas" data-wf-canvas tabindex="0" aria-label="워크플로우 캔버스 - 빈 곳을 끌면 화면 이동 · 휠 = 확대">
          <div class="wf-world" data-wf-world>
            <svg class="wf-wires" data-wf-wires width="1" height="1"></svg>
            <div data-wf-nodes></div>
          </div>
          <div class="wf-list" data-wf-list></div>
          <div class="wf-zoom"><button type="button" data-wf-fit title="화면 맞추기">맞추기</button><span data-wf-zoomval>100%</span></div>
          <div class="wf-result" data-wf-result hidden></div>
        </div>
      </div>
      <div class="wf-test">
        <span>테스트 입력</span>
        <input type="text" data-wf-test-input spellcheck="false" placeholder="비우면 지금 메인 프롬프트 · 네거티브 · 캐릭터 설정으로 돌립니다">
        <button type="button" class="wf-btn" data-wf-run>▶ 테스트 실행</button>
      </div>
      <div class="wf-foot" data-wf-status></div>`;
    const q = sel => panel.el.querySelector(sel);
    els = {mode: q('[data-wf-mode]'), save: q('[data-wf-save]'), note: q('[data-wf-note]'), find: q('[data-wf-find]'),
      chips: q('[data-wf-chips]'), canvas: q('[data-wf-canvas]'), world: q('[data-wf-world]'), wires: q('[data-wf-wires]'),
      nodes: q('[data-wf-nodes]'), list: q('[data-wf-list]'), status: q('[data-wf-status]'), zoomVal: q('[data-wf-zoomval]'),
      debug: q('[data-wf-debug]'), testInput: q('[data-wf-test-input]'), run: q('[data-wf-run]'), result: q('[data-wf-result]')};
    els.mode.addEventListener('change', () => setMode(els.mode.checked));
    els.debug.checked = debug;
    els.debug.addEventListener('change', () => {
      debug = els.debug.checked;
      writeFlag(DEBUG_KEY, debug);
      paintNodes();
    });
    els.run.addEventListener('click', () => runTest());
    els.testInput.addEventListener('keydown', event => {
      if (event.key === 'Enter' && !event.isComposing) { event.preventDefault(); runTest(); }
    });
    els.result.addEventListener('click', event => {
      if (event.target.closest('[data-wf-result-x]')) els.result.hidden = true;
    });
    els.save.addEventListener('click', () => save());
    els.find.addEventListener('input', paintPalette);
    q('[data-wf-fit]').addEventListener('click', fitView);
    els.chips.addEventListener('pointerdown', onChipDown);
    els.canvas.addEventListener('pointerdown', onCanvasDown);
    els.canvas.addEventListener('wheel', onWheel, {passive: false});
    els.nodes.addEventListener('input', onFieldInput);
    els.nodes.addEventListener('change', onFieldInput);
    els.nodes.addEventListener('click', onNodeClick);
    els.wires.addEventListener('pointerdown', onWireDown);
    els.list.addEventListener('click', onListClick);
    els.list.addEventListener('dblclick', onListDblClick);
    panel.el.addEventListener('keydown', onKeyDown);
    doc.addEventListener('pointermove', onPointerMove);
    doc.addEventListener('pointerup', onPointerUp);
    doc.addEventListener('pointercancel', onPointerUp);
    return panel;
  }

  function open() { ensurePanel().open(); applyMode(); }
  function close() { panel?.close(); }
  function toggle() { if (panel?.isOpen()) close(); else open(); }
  function isOpen() { return Boolean(panel?.isOpen()); }

  function paintAll() {
    if (!panel) return;
    paintPalette();
    paintNodes();
    paintList();
    paintStatus();
    applyView();
  }

  // ── 노드 목록(왼쪽) ─────────────────────────────────────────────────────
  function paintPalette() {
    if (!els.chips) return;
    const needle = els.find.value.trim().toLowerCase();
    els.chips.innerHTML = GROUPS.map(group => {
      const items = Object.entries(NODE_TYPES)
        .filter(([, t]) => t.group === group && (!needle || `${t.label} ${group}`.toLowerCase().includes(needle)));
      if (!items.length) return '';
      return `<div class="wf-grp">${esc(group)}</div>${items.map(([type, t]) =>
        `<button type="button" class="wf-chip wf-tone-${t.tone}" data-wf-type="${type}"
          title="끌어서 캔버스에 놓기 · 누르면 가운데에 추가">${esc(t.label)}</button>`).join('')}`;
    }).join('') || '<div class="wf-empty">맞는 노드가 없습니다</div>';
  }

  function addNode(type, x, y) {
    const node = {id: newId('n'), type, x: Math.round(x), y: Math.round(y), params: defaultParams(type)};
    graph.nodes.push(node);
    selected = {kind: 'node', id: node.id};
    markDirty();
    paintNodes();
  }

  // ── 캔버스 ──────────────────────────────────────────────────────────────
  function applyView() {
    if (!els.world) return;
    els.world.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.z})`;
    els.zoomVal.textContent = `${Math.round(view.z * 100)}%`;
  }
  function toWorld(clientX, clientY) {
    const rect = els.canvas.getBoundingClientRect();
    return {x: (clientX - rect.left - view.x) / view.z, y: (clientY - rect.top - view.y) / view.z};
  }
  function fitView() {
    if (!graph.nodes.length) { view = {x: 0, y: 0, z: 1}; applyView(); return; }
    const rect = els.canvas.getBoundingClientRect();
    const xs = graph.nodes.map(n => n.x), ys = graph.nodes.map(n => n.y);
    const minX = Math.min(...xs) - 30, minY = Math.min(...ys) - 30;
    const maxX = Math.max(...xs) + 220, maxY = Math.max(...ys) + 180;
    const z = Math.max(0.4, Math.min(1.2, Math.min(rect.width / (maxX - minX), rect.height / (maxY - minY))));
    view = {x: -minX * z, y: -minY * z, z};
    applyView();
  }

  function branchesHtml(node) {
    const rows = switchRows(node);
    const port = (name, cls) => `<span class="wf-port wf-out ${cls}" data-wf-port="${name}" data-wf-dir="out" title="끌어서 다음 노드의 왼쪽 점에 놓기"></span>`;
    return `<div class="wf-branches">${rows.map((cond, i) => `<div class="wf-br">
        <span class="wf-br-kw">${i ? 'elif' : 'if'}</span>
        <input type="text" data-wf-branch="${i}" value="${esc(cond)}" placeholder="${esc(i ? 'outdoors' : 'outdoors & rain · %wet >= 1')}" spellcheck="false" aria-label="${i ? 'elif' : 'if'} 조건">
        ${rows.length > 1 ? `<button type="button" class="wf-br-x" data-wf-branch-del="${i}" aria-label="이 줄 지우기" title="이 줄 지우기">×</button>` : '<span></span>'}
        ${port(`b${i + 1}`, 'wf-p-branch')}</div>`).join('')}
      <button type="button" class="wf-br-add" data-wf-branch-add>+ elif</button>
      <div class="wf-br wf-br-else"><span class="wf-br-kw wf-p-else">else</span><span class="wf-br-dim">나머지</span><span></span>${port('else', 'wf-p-else')}</div>
    </div>`;
  }

  function fieldHtml(node, field) {
    if (field.kind === 'branches') return branchesHtml(node);
    const value = node.params[field.key] ?? field.def;
    const attrs = `data-wf-field="${field.key}" aria-label="${esc(field.label)}"`;
    let input;
    if (field.kind === 'select') {
      input = `<select ${attrs}>${field.options.map(([v, label]) =>
        `<option value="${esc(v)}"${String(value) === String(v) ? ' selected' : ''}>${esc(label)}</option>`).join('')}</select>`;
    } else if (field.kind === 'lines') {
      // 줄 하나 = 후보 하나 · 와일드카드 파일과 같은 문법(# 주석 · 30:줄 가중치)
      const count = String(value || '').split('\n').filter(l => l.trim() && !l.trim().startsWith('#')).length;
      return `<label class="wf-field wf-field-lines"><span>${esc(field.label)} <em data-wf-count>${count}줄</em></span>
        <textarea ${attrs} rows="5" placeholder="${esc(field.placeholder || '')}" spellcheck="false">${esc(value)}</textarea></label>`;
    } else if (field.kind === 'number') {
      input = `<input type="number" step="1" ${attrs} value="${esc(value)}">`;
    } else {
      input = `<input type="text" ${attrs} value="${esc(value)}" placeholder="${esc(field.placeholder || '')}" spellcheck="false">`;
    }
    const hide = node.type === 'tag_edit' && field.key === 'with' && node.params.op !== 'replace';
    return `<label class="wf-field"${hide ? ' hidden' : ''}><span>${esc(field.label)}</span>${input}</label>`;
  }

  function nodeHtml(node) {
    const t = NODE_TYPES[node.type];
    const isSel = selected?.kind === 'node' && selected.id === node.id;
    const ins = t.ins.map(port => `<span class="wf-port wf-in" data-wf-port="${port}" data-wf-dir="in"></span>`).join('');
    const outs = t.outs.map(([port, label]) => `<div class="wf-out-row">${label ? `<span class="wf-out-label wf-p-${port}">${esc(label)}</span>` : ''}
      <span class="wf-port wf-out wf-p-${port}" data-wf-port="${port}" data-wf-dir="out" title="끌어서 다음 노드의 왼쪽 점에 놓기"></span></div>`).join('');
    const unreached = debug && result && !resultStale && !result.visits?.[node.id];
    return `<div class="wf-node wf-tone-${t.tone}${isSel ? ' is-sel' : ''}${unreached ? ' is-unreached' : ''}" data-wf-node="${node.id}" style="left:${node.x}px;top:${node.y}px">
      <div class="wf-node-head" data-wf-grab>${ins}<b>${esc(t.label)}</b>
        <button type="button" class="wf-node-x" data-wf-del aria-label="노드 지우기" title="지우기 (Delete)">×</button></div>
      ${t.note ? `<div class="wf-node-note">${esc(t.note)}</div>` : ''}
      ${t.fields.map(field => fieldHtml(node, field)).join('')}
      ${outs ? `<div class="wf-outs">${outs}</div>` : ''}
      ${debug ? probeHtml(node) : ''}
    </div>`;
  }

  // ── Probe(디버깅 모드에서만) ─────────────────────────────────────────────
  function diffLines(diff) {
    const lines = [];
    for (const [area, change] of Object.entries(diff?.areas || {})) {
      if (change.added?.length) lines.push(`<div class="wf-add">+ ${esc(areaLabel(area))}: ${esc(change.added.join(', '))}</div>`);
      if (change.removed?.length) lines.push(`<div class="wf-rm">− ${esc(areaLabel(area))}: ${esc(change.removed.join(', '))}</div>`);
    }
    for (const [name, [was, now]] of Object.entries(diff?.vars || {})) {
      lines.push(`<div class="wf-var">%${esc(name)}: ${was == null ? '없음' : esc(was)} → ${esc(now)}</div>`);
    }
    return lines.join('') || '<div class="wf-probe-dim">바뀐 것 없음</div>';
  }

  function stateLines(stateNow) {
    const lines = Object.entries(stateNow?.areas || {}).filter(([, tags]) => tags.length)
      .map(([area, tags]) => `<div><span class="wf-probe-dim">${esc(areaLabel(area))}</span> ${esc(tags.join(', '))}</div>`);
    const vars = Object.entries(stateNow?.vars || {}).map(([name, value]) => `%${esc(name)}=${esc(value)}`);
    if (vars.length) lines.push(`<div><span class="wf-probe-dim">변수</span> ${vars.join(' · ')}</div>`);
    return lines.join('') || '<div class="wf-probe-dim">모두 비어 있음</div>';
  }

  function probeHtml(node) {
    const head = text => `<div class="wf-probe" data-wf-probe title="누르면 요약 → 바뀐 것 → 전체 상태">${text}</div>`;
    if (!result) return head('<span class="wf-dot"></span><span class="wf-probe-dim">테스트 전 - 아래 [테스트 실행]</span>');
    const visits = result.probes?.[node.id] || [];
    const stale = resultStale ? '<span class="wf-probe-stale">고친 뒤 · 다시 테스트</span>' : '';
    if (!visits.length) return head(`<span class="wf-dot"></span><span class="wf-probe-dim">닿지 않음</span>${stale}`);
    const last = visits[visits.length - 1];
    if (last.skipped) return head(`<span class="wf-dot"></span><span class="wf-probe-dim">${esc(last.note)}</span>${stale}`);
    const count = result.visits?.[node.id] || visits.length;
    const added = Object.values(last.diff?.areas || {}).reduce((n, c) => n + (c.added?.length || 0), 0);
    const removed = Object.values(last.diff?.areas || {}).reduce((n, c) => n + (c.removed?.length || 0), 0);
    const bits = [`지나감${count > 1 ? ` ×${count}` : ''}`];
    if (last.port === 'else') bits.push('else');
    else if (/^b\d+$/.test(last.port || '')) bits.push(`갈래 ${last.port.slice(1)}`);
    if (added) bits.push(`+${added}`);
    if (removed) bits.push(`−${removed}`);
    const level = probeLevel.get(node.id) || 0;
    const error = String(last.note || '').startsWith('오류');
    let detail = '';
    if (level >= 1) {
      detail += `<div class="wf-probe-note">${esc(last.note || '')}</div>`;
      if (last.roll?.length) detail += `<div class="wf-probe-dim">뽑기: ${esc(last.roll.join(', '))}</div>`;
      detail += diffLines(last.diff);
    }
    if (level >= 2) detail += `<div class="wf-probe-full">${stateLines(last.state)}</div>`;
    return head(`<span class="wf-dot ${error ? 'is-err' : 'is-on'}"></span><span>${esc(bits.join(' · '))}</span>`
      + `<span class="wf-probe-lv">${['요약', '바뀐 것', '전체'][level]}</span>${stale}${detail ? `<div class="wf-probe-body">${detail}</div>` : ''}`);
  }

  function paintResult() {
    if (!els.result) return;
    if (!result) { els.result.hidden = true; return; }
    const f = result.final || {};
    const chars = (f.characters || []).map((text, i) => text ? `<div><span class="wf-probe-dim">캐릭터 ${i + 1}</span> ${esc(text)}</div>` : '').join('');
    const reached = Object.keys(result.visits || {}).length;
    const notes = (result.notes || []).map(note => `<div class="wf-rm">${esc(note)}</div>`).join('');
    // Final Prompt 가 닿았으면 이 메인이 사용자 메인 프롬프트를 대치한다 - 아니면 생성 때 PE 가 앞뒤를 붙인다.
    const finalLine = f.replaces_main
      ? `<div class="wf-add">Final Prompt · 이 메인이 메인 프롬프트를 대치 (PE 선행 ${f.pe?.pre?.length || 0} · 후행 ${f.pe?.post?.length || 0})</div>`
      : '<div class="wf-probe-dim">Final Prompt 에 닿지 않음 - 생성 땐 PE 가 선행/후행을 붙입니다</div>';
    els.result.innerHTML = `<div class="wf-result-head"><b>테스트 결과</b>${resultStale ? '<span class="wf-probe-stale">고친 뒤 · 다시 테스트</span>' : ''}
        <button type="button" data-wf-result-x aria-label="닫기">×</button></div>
      <div><span class="wf-probe-dim">메인</span> ${esc(f.main || '(비어 있음)')}</div>${finalLine}
      <div><span class="wf-probe-dim">네거티브</span> ${esc(f.negative || '(비어 있음)')}</div>${chars}${notes}
      <div class="wf-probe-dim">노드 ${graph.nodes.length} 중 ${reached} 지나감 · ${result.steps} 단계${debug ? '' : ' · 노드별 Probe 는 [디버그] 를 켜면 보입니다'}</div>`;
    els.result.hidden = false;
  }

  async function runTest() {
    if (testing) return;
    testing = true;
    els.run.disabled = true;
    const typed = els.testInput.value.trim();
    const input = {main: typed || getPromptText(), negative: getNegativeText()};
    try {
      result = await request('/api/wireflow/test', {graph: graphPayload(), input});
      resultStale = false;
      paintNodes();
      paintResult();
    } catch (error) {
      showToast(`테스트하지 못했습니다 — ${error.message}`, 'error');
    } finally {
      testing = false;
      els.run.disabled = false;
    }
  }

  function clearResult() {
    result = null;
    resultStale = false;
    probeLevel.clear();
    paintResult();
  }

  function paintNodes() {
    if (!els.nodes) return;
    els.nodes.innerHTML = graph.nodes.map(nodeHtml).join('');
    paintWires();
    paintStatus();
  }

  function nodeEl(id) { return els.nodes.querySelector(`[data-wf-node="${CSS.escape(id)}"]`); }

  function portPoint(nodeId, port, dir) {
    const node = graph.nodes.find(n => n.id === nodeId);
    const el = nodeEl(nodeId);
    const dot = el?.querySelector(`[data-wf-port="${CSS.escape(port)}"][data-wf-dir="${dir}"]`);
    if (!node || !el || !dot) return null;
    const nodeRect = el.getBoundingClientRect(), dotRect = dot.getBoundingClientRect();
    return {x: node.x + (dotRect.left + dotRect.width / 2 - nodeRect.left) / view.z,
      y: node.y + (dotRect.top + dotRect.height / 2 - nodeRect.top) / view.z};
  }

  function curve(a, b) {
    const dx = Math.max(40, Math.abs(b.x - a.x) / 2);
    return `M${a.x} ${a.y} C${a.x + dx} ${a.y} ${b.x - dx} ${b.y} ${b.x} ${b.y}`;
  }

  function paintWires(temp = null) {
    if (!els.wires) return;
    const parts = [];
    for (const edge of graph.edges) {
      const a = portPoint(edge.from.node, edge.from.port, 'out');
      const b = portPoint(edge.to.node, edge.to.port, 'in');
      if (!a || !b) continue;
      const d = curve(a, b);
      const isSel = selected?.kind === 'edge' && selected.id === edge.id;
      // 디버깅 모드 + 테스트 결과: 이번에 흐름이 타지 않은 선은 점선으로 흐리게.
      const idle = debug && result && !resultStale
        && !(result.probes?.[edge.from.node] || []).some(visit => visit.port === edge.from.port);
      parts.push(`<path class="wf-wire-hit" data-wf-edge="${esc(edge.id)}" d="${d}"></path>`
        + `<path class="wf-wire${isSel ? ' is-sel' : ''}${idle ? ' is-idle' : ''}" d="${d}" stroke="${portColor(edge.from.port)}"></path>`);
    }
    if (temp) parts.push(`<path class="wf-wire is-temp" d="${curve(temp.a, temp.b)}" stroke="${portColor(temp.port)}"></path>`);
    els.wires.innerHTML = parts.join('');
  }

  function select(next) {
    selected = next;
    els.nodes.querySelectorAll('.wf-node.is-sel').forEach(el => el.classList.remove('is-sel'));
    if (next?.kind === 'node') nodeEl(next.id)?.classList.add('is-sel');
    paintWires();
  }

  function deleteSelected() {
    if (!selected) return;
    if (selected.kind === 'node') {
      const id = selected.id;
      graph.nodes = graph.nodes.filter(n => n.id !== id);
      graph.edges = graph.edges.filter(e => e.from.node !== id && e.to.node !== id);
    } else {
      graph.edges = graph.edges.filter(e => e.id !== selected.id);
    }
    selected = null;
    markDirty();
    paintNodes();
  }

  function connect(fromNode, fromPort, toNode, toPort) {
    if (fromNode === toNode) return;
    // 출력 포트 하나엔 선 하나 - 흐름이 갈리지 않게 예전 선을 바꾼다. 입력 포트는 여럿을 받는다(합류).
    graph.edges = graph.edges.filter(e => !(e.from.node === fromNode && e.from.port === fromPort));
    graph.edges.push({id: newId('e'), from: {node: fromNode, port: fromPort}, to: {node: toNode, port: toPort}});
    markDirty();
  }

  // ── 포인터 ──────────────────────────────────────────────────────────────
  function onChipDown(event) {
    const chip = event.target.closest('[data-wf-type]');
    if (!chip || event.button !== 0) return;
    event.preventDefault();
    gesture = {kind: 'chip', type: chip.dataset.wfType, sx: event.clientX, sy: event.clientY, moved: false, ghost: null};
  }

  function onCanvasDown(event) {
    if (event.button !== 0 || event.target.closest('.wf-list, .wf-zoom')) return;
    const port = event.target.closest('[data-wf-dir="out"]');
    const nodeDiv = event.target.closest('[data-wf-node]');
    if (port && nodeDiv) {
      event.preventDefault();
      const nodeId = nodeDiv.dataset.wfNode;
      const a = portPoint(nodeId, port.dataset.wfPort, 'out');
      if (a) gesture = {kind: 'wire', node: nodeId, port: port.dataset.wfPort, a};
      return;
    }
    if (nodeDiv) {
      select({kind: 'node', id: nodeDiv.dataset.wfNode});
      // Delete 키는 창 안에 초점이 있어야 받는다 - 칸(입력)이 아닌 곳을 누르면 캔버스로 초점을 옮긴다.
      if (!event.target.closest('input, select, textarea, button')) els.canvas.focus({preventScroll: true});
      if (!event.target.closest('[data-wf-grab]') || event.target.closest('button')) return;
      event.preventDefault();
      const node = graph.nodes.find(n => n.id === nodeDiv.dataset.wfNode);
      if (node) gesture = {kind: 'node', node, el: nodeDiv, sx: event.clientX, sy: event.clientY, ox: node.x, oy: node.y, moved: false};
      return;
    }
    if (event.target.closest('[data-wf-edge]')) return;
    select(null);
    els.canvas.focus({preventScroll: true});
    gesture = {kind: 'pan', sx: event.clientX, sy: event.clientY, ox: view.x, oy: view.y};
    els.canvas.classList.add('is-panning');
  }

  function onWireDown(event) {
    const hit = event.target.closest('[data-wf-edge]');
    if (!hit) return;
    event.stopPropagation();
    select({kind: 'edge', id: hit.dataset.wfEdge});
    els.canvas.focus({preventScroll: true});
  }

  function onPointerMove(event) {
    if (!gesture) return;
    if (gesture.kind === 'pan') {
      view.x = gesture.ox + event.clientX - gesture.sx;
      view.y = gesture.oy + event.clientY - gesture.sy;
      applyView();
    } else if (gesture.kind === 'node') {
      const dx = (event.clientX - gesture.sx) / view.z, dy = (event.clientY - gesture.sy) / view.z;
      if (!gesture.moved && Math.abs(dx) + Math.abs(dy) < 3) return;
      gesture.moved = true;
      gesture.node.x = Math.round(gesture.ox + dx);
      gesture.node.y = Math.round(gesture.oy + dy);
      gesture.el.style.left = `${gesture.node.x}px`;
      gesture.el.style.top = `${gesture.node.y}px`;
      paintWires();
    } else if (gesture.kind === 'wire') {
      paintWires({a: gesture.a, b: toWorld(event.clientX, event.clientY), port: gesture.port});
    } else if (gesture.kind === 'chip') {
      if (!gesture.moved && Math.abs(event.clientX - gesture.sx) + Math.abs(event.clientY - gesture.sy) < 4) return;
      gesture.moved = true;
      if (!gesture.ghost) {
        gesture.ghost = doc.createElement('div');
        gesture.ghost.className = 'wf-ghost';
        gesture.ghost.textContent = NODE_TYPES[gesture.type].label;
        doc.body.appendChild(gesture.ghost);
      }
      gesture.ghost.style.left = `${event.clientX + 8}px`;
      gesture.ghost.style.top = `${event.clientY + 8}px`;
    }
  }

  function onPointerUp(event) {
    const g = gesture;
    if (!g) return;
    gesture = null;
    els.canvas?.classList.remove('is-panning');
    if (g.kind === 'node' && g.moved) markDirty();
    if (g.kind === 'wire') {
      const target = doc.elementFromPoint(event.clientX, event.clientY)?.closest?.('[data-wf-dir="in"]');
      const nodeDiv = target?.closest('[data-wf-node]');
      if (target && nodeDiv) connect(g.node, g.port, nodeDiv.dataset.wfNode, target.dataset.wfPort);
      paintWires();
    }
    if (g.kind === 'chip') {
      g.ghost?.remove();
      const rect = els.canvas.getBoundingClientRect();
      if (!g.moved) {
        const c = toWorld(rect.left + rect.width / 2, rect.top + rect.height / 2);
        const n = graph.nodes.length % 6;
        addNode(g.type, c.x - 70 + n * 16, c.y - 40 + n * 16);
      } else if (event.clientX >= rect.left && event.clientX <= rect.right
          && event.clientY >= rect.top && event.clientY <= rect.bottom) {
        const p = toWorld(event.clientX, event.clientY);
        addNode(g.type, p.x - 20, p.y - 12);
      }
    }
  }

  function onWheel(event) {
    if (event.target.closest('.wf-list')) return;
    const box = event.target.closest('textarea');
    if (box && box.scrollHeight > box.clientHeight) return;     // 글칸 안에서는 글칸을 굴린다(확대 아님)
    event.preventDefault();
    const rect = els.canvas.getBoundingClientRect();
    const mx = event.clientX - rect.left, my = event.clientY - rect.top;
    const z = Math.max(0.4, Math.min(2, view.z * (event.deltaY < 0 ? 1.1 : 1 / 1.1)));
    view = {x: mx - (mx - view.x) * (z / view.z), y: my - (my - view.y) * (z / view.z), z};
    applyView();
  }

  function onNodeClick(event) {
    const probe = event.target.closest('[data-wf-probe]');
    if (probe) {
      const nodeDiv = probe.closest('[data-wf-node]');
      const node = nodeDiv && graph.nodes.find(n => n.id === nodeDiv.dataset.wfNode);
      if (!node || !result) return;
      probeLevel.set(node.id, ((probeLevel.get(node.id) || 0) + 1) % PROBE_LEVELS);
      probe.outerHTML = probeHtml(node);
      paintWires();    // 노드 높이가 바뀌면 출력 점도 움직인다
      return;
    }
    const add = event.target.closest('[data-wf-branch-add]');
    const drop = event.target.closest('[data-wf-branch-del]');
    if (add || drop) {
      const nodeId = (add || drop).closest('[data-wf-node]')?.dataset.wfNode;
      const node = graph.nodes.find(n => n.id === nodeId);
      if (!node) return;
      const rows = switchRows(node);
      if (add) {
        rows.push('');
      } else {
        // 줄을 지우면 그 줄의 선도 지우고, 아래 줄의 선은 한 칸씩 올린다(b3 -> b2) - 선이 제 조건을 따라간다.
        const gone = Number(drop.dataset.wfBranchDel) + 1;
        rows.splice(gone - 1, 1);
        graph.edges = graph.edges.filter(e => !(e.from.node === nodeId && e.from.port === `b${gone}`))
          .map(e => {
            const n = e.from.node === nodeId && /^b\d+$/.test(e.from.port) ? Number(e.from.port.slice(1)) : 0;
            return n > gone ? {...e, from: {...e.from, port: `b${n - 1}`}} : e;
          });
      }
      node.params.conds = rows.join('\n');
      markDirty();
      paintNodes();
      if (add) nodeEl(nodeId)?.querySelector(`[data-wf-branch="${rows.length - 1}"]`)?.focus();
      return;
    }
    if (!event.target.closest('[data-wf-del]')) return;
    const nodeDiv = event.target.closest('[data-wf-node]');
    if (!nodeDiv) return;
    selected = {kind: 'node', id: nodeDiv.dataset.wfNode};
    deleteSelected();
  }

  function onFieldInput(event) {
    const branch = event.target.closest('[data-wf-branch]');
    if (branch) {
      const node = graph.nodes.find(n => n.id === branch.closest('[data-wf-node]')?.dataset.wfNode);
      if (!node) return;
      const rows = switchRows(node);
      rows[Number(branch.dataset.wfBranch)] = branch.value.replace(/[\r\n]+/g, ' ');
      node.params.conds = rows.join('\n');
      markDirty();
      return;
    }
    const input = event.target.closest('[data-wf-field]');
    const nodeDiv = input?.closest('[data-wf-node]');
    const node = nodeDiv && graph.nodes.find(n => n.id === nodeDiv.dataset.wfNode);
    if (!node) return;
    const key = input.dataset.wfField;
    node.params[key] = input.type === 'number' ? (Number(input.value) || 0) : input.value;
    if (input.tagName === 'TEXTAREA') {
      const count = input.closest('.wf-field')?.querySelector('[data-wf-count]');
      if (count) count.textContent = `${input.value.split('\n').filter(l => l.trim() && !l.trim().startsWith('#')).length}줄`;
    }
    if (node.type === 'tag_edit' && key === 'op') {
      const withField = nodeDiv.querySelector('[data-wf-field="with"]')?.closest('.wf-field');
      if (withField) withField.hidden = input.value !== 'replace';
      paintWires();
    }
    markDirty();
  }

  function onKeyDown(event) {
    const typing = event.target.closest?.('input, select, textarea');
    if ((event.key === 's' || event.key === 'S') && (event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey) {
      event.preventDefault();
      event.stopPropagation();   // 결과 이미지 빠른 저장(Ctrl+S)으로 가지 않게
      save();
      return;
    }
    if (typing || !selected) return;
    if (event.key === 'Delete' || event.key === 'Backspace') {
      event.preventDefault();
      event.stopPropagation();
      deleteSelected();
    }
  }

  // ── 상태 · 저장 ─────────────────────────────────────────────────────────
  function markDirty() {
    dirty = true;
    // 테스트 뒤에 고쳤다 - Probe 는 옛 그래프의 것이라 흐림 · 점선을 거두고 '다시 테스트' 를 붙인다.
    if (result && !resultStale) {
      resultStale = true;
      if (debug) {
        els.nodes.querySelectorAll('.wf-node.is-unreached').forEach(el => el.classList.remove('is-unreached'));
        els.nodes.querySelectorAll('[data-wf-probe]').forEach(el => {
          if (!el.querySelector('.wf-probe-stale')) el.insertAdjacentHTML('beforeend', '<span class="wf-probe-stale">고친 뒤 · 다시 테스트</span>');
        });
      }
      paintResult();
    }
    paintStatus();
  }

  function paintStatus() {
    if (!els.status) return;
    const name = currentId ? (state.workflows.find(wf => wf.id === currentId)?.name || '') : '저장 안 된 초안';
    els.note.textContent = state.mode_on ? '모드 켜짐 · 조건부 프롬프트 · E · S 일시 해제' : '';
    els.note.classList.toggle('is-on', state.mode_on);
    els.save.classList.toggle('is-dirty', dirty);
    const active = state.workflows.find(wf => wf.id === state.active_id);
    els.status.innerHTML = `<span class="wf-cur">${esc(name)}${dirty ? ' <i>● 고침</i>' : ''}</span>`
      + `<span>노드 ${graph.nodes.length} · 선 ${graph.edges.length}</span>`
      + `<span>사용: ${active ? esc(active.name) : '없음'}</span>`
      + '<span class="wf-draft">초안 · 아직 생성에 적용되지 않습니다(모드가 켜지면 조건부 프롬프트만 쉽니다)</span>';
  }

  function graphPayload() {
    return {nodes: graph.nodes.map(n => ({id: n.id, type: n.type, x: n.x, y: n.y, params: {...n.params}})),
      edges: graph.edges.map(e => ({id: e.id, from: {...e.from}, to: {...e.to}}))};
  }

  async function askName(title, value) {
    const text = typeof promptDialog === 'function'
      ? await promptDialog('워크플로우 이름', {title, defaultValue: value, okText: '저장', placeholder: '날씨 분기'})
      : win?.prompt?.('워크플로우 이름', value);
    const name = String(text ?? '').trim();
    return name || null;
  }

  async function save() {
    try {
      if (!currentId) {
        const name = await askName('새 워크플로우로 저장', `워크플로우 ${state.workflows.length + 1}`);
        if (!name) return false;
        const data = await act({action: 'save_new', name, graph: graphPayload()});
        currentId = data.created || '';
      } else {
        await act({action: 'save', id: currentId, graph: graphPayload()});
      }
      dirty = false;
      paintList();
      paintStatus();
      showToast('워크플로우를 저장했습니다', 'success');
      return true;
    } catch (error) {
      showToast(`저장하지 못했습니다 — ${error.message}`, 'error');
      return false;
    }
  }

  /** 고친 것이 있으면 저장할지 묻는다. 계속해도 되면 true. */
  async function settleDirty(title) {
    if (!dirty || typeof confirmDialog !== 'function') return true;
    const cur = state.workflows.find(wf => wf.id === currentId);
    const pick = await confirmDialog(cur ? `${cur.name} 에 저장하지 않은 고침이 있습니다.` : '캔버스의 초안이 저장되어 있지 않습니다.', {
      title, choices: [{key: 'save', label: cur ? '저장하고 계속' : '새로 저장하고 계속'}, {key: 'drop', label: '저장하지 않고 계속'}],
    });
    if (!pick) return false;
    if (pick === 'save') return save();
    return true;
  }

  async function loadWorkflow(id) {
    if (id === currentId && !dirty) return;
    if (!(await settleDirty('다른 워크플로우 열기'))) return;
    try {
      const data = await request(`/api/wireflow/workflow?id=${encodeURIComponent(id)}`);
      graph = {nodes: data.workflow.nodes || [], edges: data.workflow.edges || []};
      for (const node of graph.nodes) node.params = {...defaultParams(node.type), ...(node.params || {})};
      currentId = id;
      dirty = false;
      selected = null;
      clearResult();
      paintNodes();
      paintList();
      fitView();
    } catch (error) {
      showToast(`열지 못했습니다 — ${error.message}`, 'error');
    }
  }

  async function newWorkflow() {
    if (!(await settleDirty('새 워크플로우'))) return;
    const name = await askName('새 워크플로우', `워크플로우 ${state.workflows.length + 1}`);
    if (!name) return;
    const fresh = starterGraph();
    try {
      const data = await act({action: 'save_new', name, graph: fresh});
      graph = fresh;
      currentId = data.created || '';
      dirty = false;
      selected = null;
      clearResult();
      view = {x: 0, y: 0, z: 1};
      paintNodes();
      paintList();
      applyView();
    } catch (error) {
      showToast(`만들지 못했습니다 — ${error.message}`, 'error');
    }
  }

  // ── 워크플로우 목록(우상단 · 접힘) ───────────────────────────────────────
  function paintList() {
    if (!els.list) return;
    const rows = state.workflows.map(wf => {
      const isActive = wf.id === state.active_id, isOpen = wf.id === currentId;
      return `<div class="wf-row${isOpen ? ' is-open' : ''}" data-wf-open="${esc(wf.id)}" title="누르면 캔버스에 엽니다 · 두 번 누르면 이름 바꾸기">
        <span class="wf-row-name">${esc(wf.name)}</span>
        <button type="button" class="wf-use${isActive ? ' is-on' : ''}" data-wf-use="${esc(wf.id)}"
          title="${isActive ? '사용 중 - 누르면 끕니다' : '이 워크플로우를 씁니다(하나만)'}">${isActive ? '● 사용' : '꺼짐'}</button>
        <button type="button" class="wf-row-x" data-wf-remove="${esc(wf.id)}" aria-label="${esc(wf.name)} 지우기" title="지우기">×</button>
      </div>`;
    }).join('');
    els.list.innerHTML = `
      <button type="button" class="wf-list-head" data-wf-collapse aria-expanded="${listCollapsed ? 'false' : 'true'}">
        <span>워크플로우</span><span class="wf-count">${state.workflows.length}</span><span class="wf-caret">${listCollapsed ? '▼' : '▲'}</span></button>
      <div class="wf-list-body"${listCollapsed ? ' hidden' : ''}>
        ${rows || '<div class="wf-empty">저장된 워크플로우가 없습니다</div>'}
        <button type="button" class="wf-row wf-new" data-wf-new>+ 새 워크플로우</button>
      </div>`;
  }

  async function onListClick(event) {
    if (event.target.closest('[data-wf-collapse]')) {
      listCollapsed = !listCollapsed;
      writeFlag(LIST_KEY, listCollapsed);
      paintList();
      return;
    }
    if (event.target.closest('[data-wf-new]')) { newWorkflow(); return; }
    const use = event.target.closest('[data-wf-use]');
    if (use) {
      const id = use.dataset.wfUse;
      try { await act({action: 'activate', id: id === state.active_id ? '' : id}); } catch (error) {
        showToast(`바꾸지 못했습니다 — ${error.message}`, 'error');
      }
      return;
    }
    const remove = event.target.closest('[data-wf-remove]');
    if (remove) {
      const wf = state.workflows.find(w => w.id === remove.dataset.wfRemove);
      if (!wf) return;
      const ok = typeof confirmDialog === 'function' ? await confirmDialog(`워크플로우를 지웁니다: ${wf.name}`) : true;
      if (!ok) return;
      try {
        if (wf.id === currentId) currentId = '';
        await act({action: 'delete', id: wf.id});
      } catch (error) { showToast(`지우지 못했습니다 — ${error.message}`, 'error'); }
      return;
    }
    const row = event.target.closest('[data-wf-open]');
    if (row && event.detail < 2) loadWorkflow(row.dataset.wfOpen);
  }

  async function onListDblClick(event) {
    const row = event.target.closest('[data-wf-open]');
    if (!row || event.target.closest('button')) return;
    const wf = state.workflows.find(w => w.id === row.dataset.wfOpen);
    if (!wf) return;
    const name = await askName('이름 바꾸기', wf.name);
    if (!name || name === wf.name) return;
    try { await act({action: 'rename', id: wf.id, name}); } catch (error) {
      showToast(`이름을 바꾸지 못했습니다 — ${error.message}`, 'error');
    }
  }

  reload();

  return {
    open, close, toggle, isOpen, reload, setMode,
    isModeOn: () => Boolean(state.mode_on),
  };
}

function ensureStyle(doc) {
  if (doc.getElementById(STYLE_ID)) return;
  const style = doc.createElement('style');
  style.id = STYLE_ID;
  style.textContent = WF_CSS;
  doc.head.appendChild(style);
}

const WF_CSS = `
body[data-wireflow="on"] #eventMapTab,body[data-wireflow="on"] #stagingTab{display:none!important}
body[data-wireflow="on"] #stagingTab ~ #assistTab{top:calc(50% + 21px)}
#wireflowTab{background:rgba(15,110,86,.85);color:#e1f5ee;opacity:.8}
#wireflowTab:hover,#wireflowTab[aria-pressed="true"]{background:rgba(29,158,117,.95);color:#fff;opacity:1}
body[data-wireflow="on"] .module-btn[data-module="conditional_prompt"]{opacity:.5}
body[data-wireflow="on"] .module-btn[data-module="conditional_prompt"]::after{content:"일시 해제";margin-left:6px;font-size:10px;color:#fac775}
body[data-wireflow="on"] .dragpanel.cpw .dragpanel-body::before{content:"Wire-Flow 모드가 켜져 있어 조건부 프롬프트는 일시 해제되어 있습니다";display:block;padding:5px 10px;background:rgba(250,199,117,.12);color:#fac775;font-size:11px}
.module-wire-flow-row{display:flex;align-items:center;gap:6px}
.module-wire-flow-row .module-btn{flex:1;min-width:0}
.module-wire-flow-toggle{display:inline-flex;align-items:center;gap:4px;font-size:11px;color:var(--text-dim);cursor:pointer;white-space:nowrap;padding-right:6px}
.module-wire-flow-row.active .module-wire-flow-toggle{color:#5dcaa5}
.module-category-badge-wire-flow{background:rgba(29,158,117,.25);color:#9fe1cb}
.dragpanel.wf-window .dragpanel-body{display:flex;flex-direction:column;overflow:hidden;padding:0}
.dragpanel.wf-window .dragpanel-slot{justify-content:flex-end;gap:8px;align-items:center}
.wf-head-note{font-size:10.5px;color:var(--text-dim)}
.wf-head-note.is-on{color:#5dcaa5}
.wf-mode{display:inline-flex;align-items:center;gap:4px;font-size:11px;color:var(--text-primary);cursor:pointer}
.wf-btn{border:1px solid var(--border-dim);border-radius:5px;background:rgba(255,255,255,.05);color:var(--text-primary);padding:2px 10px;font:inherit;font-size:11px;cursor:pointer}
.wf-btn:hover{background:rgba(255,255,255,.1)}
.wf-btn.is-dirty{border-color:rgba(250,199,117,.6);color:#fac775}
.wf{flex:1;min-height:0;display:grid;grid-template-columns:150px minmax(0,1fr);font-size:11px;color:var(--text-primary)}
.wf-pal{border-right:1px solid var(--border-dim);padding:8px;overflow:auto;display:flex;flex-direction:column;gap:4px;background:rgba(255,255,255,.02)}
.wf-find{width:100%;box-sizing:border-box;background:var(--bg-input,#101019);border:1px solid var(--border-dim);border-radius:4px;color:var(--text-primary);font:inherit;padding:4px 6px}
.wf-grp{color:var(--text-dim);font-size:10px;margin:8px 0 3px}
/* 색 테두리가 붙은 왼쪽 모서리는 각지게 - 둥글면 강조가 { 처럼 휜다(사용자: 그 모양을 싫어함 2026-10-31). 칩 · 노드 같다. */
.wf-chip{display:block;width:100%;text-align:left;margin-bottom:4px;border:1px solid var(--border-dim);border-left-width:3px;border-radius:0 4px 4px 0;background:rgba(255,255,255,.04);color:var(--text-primary);padding:4px 7px;font:inherit;cursor:grab;touch-action:none}
.wf-chip:hover{background:rgba(255,255,255,.09)}
.wf-empty{color:var(--text-dim);padding:6px 8px}
.wf-tone-in{border-left-color:#888780}
.wf-tone-cond{border-left-color:#7f77dd}
.wf-tone-proc{border-left-color:#1d9e75}
.wf-tone-var{border-left-color:#ba7517}
.wf-tone-out{border-left-color:#d85a30}
.wf-canvas{position:relative;overflow:hidden;outline:none;cursor:default;touch-action:none;background-color:#0d0d14;background-image:radial-gradient(rgba(255,255,255,.07) 1px,transparent 1px);background-size:18px 18px}
.wf-canvas.is-panning{cursor:grabbing}
.wf-world{position:absolute;left:0;top:0;transform-origin:0 0}
.wf-wires{position:absolute;left:0;top:0;overflow:visible;pointer-events:none}
.wf-wire{fill:none;stroke-width:2;pointer-events:none}
.wf-wire.is-sel{stroke-width:3.5;filter:brightness(1.4)}
.wf-wire.is-temp{stroke-dasharray:5 4}
.wf-wire-hit{fill:none;stroke:transparent;stroke-width:12;pointer-events:stroke;cursor:pointer}
.wf-node{position:absolute;width:178px;box-sizing:border-box;border:1px solid var(--border-dim);border-left-width:3px;border-radius:0 6px 6px 0;background:rgba(24,24,36,.96);box-shadow:0 4px 14px rgba(0,0,0,.35)}
.wf-node.is-sel{outline:2px solid rgba(120,140,255,.75);outline-offset:1px}
.wf-node-head{position:relative;display:flex;align-items:center;gap:6px;padding:5px 8px 5px 12px;cursor:grab;border-bottom:1px solid rgba(255,255,255,.06)}
.wf-node-head b{flex:1;font-weight:600;font-size:11.5px;color:#e6e6f2}
.wf-node-x{border:0;background:transparent;color:var(--text-dim);font:inherit;font-size:13px;cursor:pointer;padding:0 2px;line-height:1}
.wf-node-x:hover{color:#f09595}
.wf-node-note{padding:4px 10px 0;color:var(--text-dim);font-size:10px}
.wf-field{display:grid;grid-template-columns:58px minmax(0,1fr);align-items:center;gap:6px;padding:4px 8px 0}
.wf-field[hidden]{display:none}
.wf-field-lines{grid-template-columns:minmax(0,1fr);gap:2px}
.wf-field-lines em{font-style:normal;opacity:.7;margin-left:4px}
.wf-field-lines textarea{width:100%;min-width:0;box-sizing:border-box;height:86px;resize:none;background:var(--bg-input,#101019);border:1px solid var(--border-dim);border-radius:3px;color:var(--text-primary);font:inherit;font-family:ui-monospace,Consolas,monospace;font-size:10.5px;line-height:1.45;padding:3px 5px;white-space:pre;overflow:auto}
.wf-field span{color:var(--text-dim);font-size:10px}
.wf-field input,.wf-field select{width:100%;min-width:0;box-sizing:border-box;background:var(--bg-input,#101019);border:1px solid var(--border-dim);border-radius:3px;color:var(--text-primary);font:inherit;font-size:10.5px;padding:2px 4px}
.wf-outs{padding:4px 0 6px}
.wf-out-row{display:flex;justify-content:flex-end;align-items:center;gap:6px;min-height:16px;padding-right:2px}
.wf-out-label{font-size:10px}
.wf-p-branch{color:#5dcaa5}
.wf-p-else{color:#f0997b}
.wf-branches{padding:4px 0 6px}
.wf-br{display:grid;grid-template-columns:28px minmax(0,1fr) 14px 11px;align-items:center;gap:4px;padding:2px 0 2px 8px;min-height:20px}
.wf-br-kw{font-family:ui-monospace,Consolas,monospace;font-size:10px;color:#afa9ec}
.wf-br input{width:100%;min-width:0;box-sizing:border-box;background:var(--bg-input,#101019);border:1px solid var(--border-dim);border-radius:3px;color:var(--text-primary);font:inherit;font-size:10.5px;padding:2px 4px}
.wf-br-x{border:0;background:transparent;color:var(--text-dim);cursor:pointer;padding:0;font-size:12px;line-height:1}
.wf-br-x:hover{color:#f0997b}
.wf-br-add{display:block;margin:2px 8px 2px 40px;border:1px dashed var(--border-dim);border-radius:3px;background:transparent;color:var(--text-dim);font:inherit;font-size:10px;padding:1px 6px;cursor:pointer}
.wf-br-add:hover{color:var(--text-primary)}
.wf-br-else{border-top:1px solid var(--border-dim);margin-top:3px;padding-top:4px}
.wf-br-dim{color:var(--text-dim);font-size:10px}
.wf-port{width:11px;height:11px;border-radius:50%;box-sizing:border-box;border:2px solid #8a8aa0;background:#0d0d14;cursor:crosshair}
.wf-in{position:absolute;left:-7px;top:50%;transform:translateY(-50%)}
.wf-out{margin-right:-7px}
.wf-out.wf-p-branch{border-color:#1d9e75}
.wf-out.wf-p-else{border-color:#d85a30}
.wf-port:hover{background:#dfe4ff}
.wf-list{position:absolute;top:8px;right:8px;width:210px;max-height:calc(100% - 50px);overflow:auto;border:1px solid var(--border-dim);border-radius:6px;background:rgba(18,18,28,.97);box-shadow:0 6px 18px rgba(0,0,0,.4)}
.wf-list-head{display:flex;align-items:center;gap:6px;width:100%;border:0;background:transparent;color:var(--text-primary);font:inherit;font-weight:600;padding:6px 9px;cursor:pointer;text-align:left}
.wf-count{color:var(--text-dim);font-weight:400}
.wf-caret{margin-left:auto;color:var(--text-dim);font-size:9px}
.wf-list-body[hidden]{display:none}
.wf-row{display:flex;align-items:center;gap:6px;width:100%;box-sizing:border-box;border:0;border-top:1px solid rgba(255,255,255,.06);background:transparent;color:var(--text-primary);font:inherit;padding:5px 9px;cursor:pointer;text-align:left}
.wf-row:hover{background:rgba(255,255,255,.05)}
.wf-row.is-open{background:rgba(120,140,255,.14)}
.wf-row-name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.wf-use{border:1px solid var(--border-dim);border-radius:9px;background:transparent;color:var(--text-dim);font:inherit;font-size:10px;padding:0 7px;cursor:pointer}
.wf-use.is-on{border-color:rgba(29,158,117,.7);color:#5dcaa5}
.wf-row-x{border:0;background:transparent;color:var(--text-dim);font:inherit;cursor:pointer;padding:0 2px;visibility:hidden}
.wf-row:hover .wf-row-x{visibility:visible}
.wf-row-x:hover{color:#f09595}
.wf-new{color:var(--text-dim)}
.wf-zoom{position:absolute;left:8px;bottom:8px;display:flex;align-items:center;gap:6px;color:var(--text-dim);font-size:10px}
.wf-zoom button{border:1px solid var(--border-dim);border-radius:4px;background:rgba(18,18,28,.9);color:var(--text-primary);font:inherit;font-size:10px;padding:1px 7px;cursor:pointer}
.wf-foot{display:flex;flex-wrap:wrap;gap:4px 14px;padding:5px 10px;border-top:1px solid var(--border-dim);font-size:10.5px;color:var(--text-dim)}
.wf-cur{color:var(--text-primary)}
.wf-cur i{font-style:normal;color:#fac775}
.wf-draft{margin-left:auto;color:#a8a8bc}
.wf-wire.is-idle{stroke-dasharray:5 4;opacity:.35}
.wf-node.is-unreached{opacity:.45}
.wf-probe{border-top:1px dashed rgba(255,255,255,.14);padding:4px 8px 5px;cursor:pointer;font-size:10.5px;line-height:1.5;display:flex;flex-wrap:wrap;align-items:center;gap:2px 6px;background:rgba(255,255,255,.025)}
.wf-probe:hover{background:rgba(255,255,255,.06)}
.wf-dot{width:7px;height:7px;border-radius:50%;background:#5f5e5a;flex:none}
.wf-dot.is-on{background:#1d9e75}
.wf-dot.is-err{background:#e24b4a}
.wf-probe-lv{margin-left:auto;color:var(--text-dim);font-size:9.5px}
.wf-probe-stale{flex-basis:100%;color:#fac775;font-size:9.5px}
.wf-probe-body{flex-basis:100%;margin-top:2px;overflow-wrap:anywhere}
.wf-probe-note{color:#dfe4ff}
.wf-probe-dim{color:var(--text-dim)}
.wf-probe-full{margin-top:4px;padding-top:4px;border-top:1px solid rgba(255,255,255,.06)}
.wf-add{color:#5dcaa5}
.wf-rm{color:#f09595}
.wf-var{color:#fac775}
.wf-test{display:flex;align-items:center;gap:8px;padding:5px 10px;border-top:1px solid var(--border-dim);font-size:11px;color:var(--text-dim)}
.wf-test input{flex:1;min-width:0;background:var(--bg-input,#101019);border:1px solid var(--border-dim);border-radius:4px;color:var(--text-primary);font:inherit;padding:3px 6px}
.wf-result{position:absolute;right:8px;bottom:8px;width:300px;max-height:45%;overflow:auto;border:1px solid var(--border-dim);border-radius:6px;background:rgba(18,18,28,.97);box-shadow:0 6px 18px rgba(0,0,0,.4);padding:7px 10px;font-size:10.5px;line-height:1.55;overflow-wrap:anywhere}
.wf-result[hidden]{display:none}
.wf-result-head{display:flex;align-items:center;gap:6px;margin-bottom:3px}
.wf-result-head button{margin-left:auto;border:0;background:transparent;color:var(--text-dim);font:inherit;font-size:13px;cursor:pointer;padding:0 2px}
.wf-ghost{position:fixed;z-index:100000;pointer-events:none;border:1px solid rgba(120,140,255,.6);border-radius:4px;background:rgba(24,24,36,.95);color:#dfe4ff;padding:3px 8px;font-size:11px}
`;
