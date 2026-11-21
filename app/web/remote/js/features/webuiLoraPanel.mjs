// 떠 있는 창(draggablePanel) - 다른 창과 같은 URL(?v=)로 불러온다(다르면 창끼리 겹침 순서가 깨진다).
import {createDraggablePanel} from './draggablePanel.mjs?v=20260926-childalign';

const API = '/api/webui/loras';
const FAVORITES = Symbol('favorites');

const STYLE = `
.dragpanel.webui-lora-win .dragpanel-body {padding:0;gap:0;overflow:hidden}
.dragpanel.webui-lora-win .dragpanel-slot {justify-content:flex-end;gap:4px}
.dragpanel.webui-lora-win .tagsearch-status {margin-right:auto;color:var(--text-dim);font-size:11px}
.webui-lora-popup {position:relative;flex:1 1 auto;min-height:0;display:flex;flex-direction:column}
.webui-lora-popup [hidden] {display:none!important}
.webui-lora-win .tagsearch-act {height:22px;padding:0 8px;font-size:11px}
.wlr-body {flex:1;display:flex;min-height:0}
.wlr-folders {width:120px;box-sizing:border-box;flex:none;overflow:auto;padding:5px 0;border-right:1px solid var(--border-dim)}
.wlr-folders button {width:100%;display:flex;gap:5px;padding:5px 7px 5px calc(8px + var(--depth,0)*10px);
  border:0;background:transparent;color:var(--text-muted);text-align:left;font-size:11px;cursor:pointer}
.wlr-folders button[aria-pressed=true],.wlr-folders button:hover {color:var(--text-primary);background:rgba(96,120,255,.16)}
.wlr-folders span,.wlr-name {overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.wlr-folders small {margin-left:auto;color:var(--text-dim)}
.wlr-main {min-width:0;flex:1;display:flex;flex-direction:column}
.wlr-main .tagsearch-input {height:26px}
.wlr-cards,.wlr-history {overflow:auto;min-height:0}
.wlr-card {display:flex;align-items:center;gap:9px;padding:7px 10px;border-bottom:1px solid var(--border-dim)}
.wlr-thumb {width:44px;height:44px;flex:none;border:1px dashed var(--border-glow);border-radius:5px;
  overflow:hidden;padding:0;background:rgba(0,0,0,.25);color:var(--text-dim);font-size:10px;cursor:pointer}
.wlr-thumb img,.wlr-grid img {width:100%;height:100%;object-fit:cover;display:block}
.wlr-info {min-width:0;flex:1;display:grid;gap:4px}
.wlr-top,.wlr-triggers,.wlr-controls {display:flex;align-items:center;gap:5px}
.wlr-name {font:600 12px var(--font-editor);color:var(--text-primary)}
.wlr-star {background:none;border:0;color:var(--text-dim);padding:0 4px;cursor:pointer}
.wlr-star[aria-pressed=true] {color:#f5d36e}
.wlr-triggers,.wlr-controls {flex-wrap:wrap;color:var(--text-muted);font-size:10px}
.wlr-chip {border:1px solid rgba(130,150,255,.32);border-radius:4px;padding:1px 5px;
  overflow-wrap:anywhere;background:rgba(96,120,255,.12);color:var(--text-primary)}
.wlr-controls label {display:inline-flex;align-items:center;gap:5px}
.wlr-number {width:56px;padding:2px 3px;color:var(--text-primary);background:var(--bg-input,#181824);
  border:1px solid var(--border-dim);border-radius:4px;font:11px var(--font-mono)}
.wlr-controls button {margin-left:auto}
.wlr-empty,.wlr-message {padding:8px 10px;font-size:11px;color:var(--text-muted)}
.wlr-message {color:#f5d36e}
.wlr-picker {position:absolute;inset:0;display:flex;flex-direction:column;background:var(--bg-panel,#171720)}
.wlr-picker header {display:flex;align-items:center;gap:6px;min-height:32px;padding:0 10px;font-size:11px;color:var(--text-primary)}
.wlr-picker header b {flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.wlr-history {padding:6px 10px}
.wlr-history h4 {margin:5px 0;font-size:11px;color:var(--text-muted)}
.wlr-grid {display:grid;grid-template-columns:repeat(auto-fill,minmax(65px,1fr));gap:5px}
.wlr-grid button {aspect-ratio:1;padding:0;background:none;border:1px solid var(--border-dim);border-radius:4px;overflow:hidden;cursor:pointer}
`;

function esc(value) {
  return String(value).replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'})[c]);
}

// Keep offsets in the original textarea, including equal tokens at different positions.
export function promptTokens(text) {
  const pattern = /__[^\n]*?__|<lora:([^:<>\r\n]+):([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?)>/gi;
  return Array.from(text.matchAll(pattern)).filter(m => m[1] !== undefined)
    .map(m => ({raw:m[0], index:m.index, name:m[1], weight:m[2]}));
}

export function insertToken(text, name, strength) {
  if (promptTokens(text).some(t => t.name.toLowerCase() === name.toLowerCase())) return text;
  const separator = !text.trim() ? '' : /,\s*$/.test(text) ? (/\s$/.test(text) ? '' : ' ') : ', ';
  return text + separator + `<lora:${name}:${strength}>`;
}

export function createWebuiLoraPanel({document, window: win, promptEdit, showToast, zoom, onStateChange,
  createPanel = options => createDraggablePanel({document, window: win, ...options})}) {
  // shell = 떠 있는 창(머리줄 · 끌기 · 크기 · 접기 · 자리 기억) · popup = 그 안의 본문
  // 프롬프트 밑 강도 줄은 두지 않는다(11-21 사용자 결정) - WEBUI 는 <lora:이름:강도> 글자가 곧 상태라
  // 프롬프트에서 숫자를 고치면 된다. 이 창은 찾기 · 미리보기 · 트리거 · 넣기만 한다.
  let mode = '', shell, popup;
  let entries = [], category = '', picker = null, revision = 0;
  let zoomTimer, zoomTarget, zoomShown = false;
  let writes = Promise.resolve();
  const style = document.createElement('style');
  style.textContent = STYLE;
  document.head.appendChild(style);
  // 머리줄의 단추(폴더 열기 · 새로고침 · 개수)도 찾도록 창 전체에서 찾는다.
  const find = selector => shell.el.querySelector(selector);
  const isOpen = () => Boolean(shell?.isOpen());
  const byName = name => entries.find(item => item.name === name);
  const query = name => '?name=' + encodeURIComponent(name);

  async function request(path = '', method = 'GET', body) {
    const options = {method, cache:'no-store'};
    if (body) {
      options.headers = {'Content-Type':'application/json'};
      options.body = JSON.stringify(body);
    }
    const response = await win.fetch(API + path, options);
    const data = await response.json();
    if (!response.ok || data.ok === false) {
      throw new Error(data.message || data.warnings?.[0] || (typeof data.detail === 'string' && data.detail) || `요청 실패 (${response.status})`);
    }
    return data;
  }

  function write(work) {
    writes = writes.then(work).catch(error => showToast(error.message, 'error'));
    return writes;
  }

  function setPrompt(text) {
    if (mode !== 'WEBUI' || text === promptEdit.value) return;
    if (promptEdit.readOnly || promptEdit.disabled) {
      showToast('현재 메인 프롬프트를 편집할 수 없습니다.', 'info');
      return;
    }
    promptEdit.value = text;
    promptEdit.dispatchEvent(new Event('input', {bubbles:true}));
  }

  function folders() {
    const counts = new Map();
    for (const {folder} of entries) {
      let path = '';
      for (const part of folder.split('/').filter(Boolean)) {
        path = path ? path + '/' + part : part;
        counts.set(path, (counts.get(path) || 0) + 1);
      }
    }
    if (typeof category === 'string' && category && !counts.has(category)) category = '';
    const row = (attr, label, count, selected, depth = 0) =>
      `<button ${attr} aria-pressed="${selected}" style="--depth:${depth}"><span>${esc(label)}</span><small>${count}</small></button>`;
    find('nav').innerHTML = row('data-folder=""', '전체', entries.length, category === '')
      + row('data-favorites', '★ 즐겨찾기', entries.filter(e => e.favorite).length, category === FAVORITES)
      + [...counts.keys()].sort().map(path => {
        const parts = path.split('/');
        return row(`data-folder="${esc(path)}"`, parts.at(-1), counts.get(path), category === path, parts.length - 1);
      }).join('');
  }

  function cards() {
    hideZoom();
    const term = find('[type=search]').value.trim().toLowerCase();
    const visible = entries.filter(e => (category === FAVORITES ? e.favorite
      : !category || e.folder === category || e.folder.startsWith(category + '/'))
      && [e.name, ...e.triggers].some(word => word.toLowerCase().includes(term)));
    find('.wlr-cards').innerHTML = visible.map(e => {
      const name = esc(e.name), thumb = esc(e.thumb_url);
      return `<article class="wlr-card" data-name="${name}"><button class="wlr-thumb" data-picker
          aria-label="${name} 히스토리에서 고르기" ${thumb ? `data-zoom="${thumb}"` : ''}>${thumb ? `<img src="${thumb}" loading="lazy" alt="">` : 'PNG'}</button>
        <div class="wlr-info"><div class="wlr-top"><strong class="wlr-name" title="${name}">${name}</strong>
          <button class="wlr-star" data-star aria-pressed="${e.favorite}" aria-label="즐겨찾기">${e.favorite ? '★' : '☆'}</button></div>
        <div class="wlr-triggers">트리거 ${e.triggers.length ? e.triggers.map(t => `<span class="wlr-chip">${esc(t)}</span>`).join('') : '없음'}</div>
        <div class="wlr-controls"><label>기본 강도 <input class="wlr-number" data-default type="number" min="-2" max="2" step="any"
          value="${formatStrength(e.default_strength)}"></label><button class="tagsearch-act" data-add>넣기</button></div></div></article>`;
    }).join('') || '<div class="wlr-empty">표시할 LoRA가 없습니다.</div>';
  }

  function formatStrength(value) {
    const fixed = value.toFixed(2);
    return Number(fixed) === value ? fixed : String(value);
  }

  async function load(refresh = false) {
    const seq = ++revision;
    const message = find('.wlr-message');
    message.hidden = true;
    find('.tagsearch-status').textContent = '불러오는 중…';
    find('.wlr-body').inert = true;
    find('[data-reload]').disabled = true;
    try {
      await writes;
      const data = await request(refresh ? '?refresh=1' : '');
      if (seq !== revision) return;
      entries = data.available;
      message.textContent = data.warnings.join(' · ');
    } catch (err) {
      if (seq !== revision) return;
      entries = [];
      message.textContent = err.message;
    }
    if (seq !== revision) return;
    message.hidden = !message.textContent;
    find('.tagsearch-status').textContent = entries.length + '개';
    folders();
    cards();
    find('.wlr-body').inert = false;
    find('[data-reload]').disabled = false;
  }

  function hideZoom() {
    win.clearTimeout(zoomTimer);
    zoomTarget = null;
    if (zoomShown) zoom.hide();
    zoomShown = false;
  }

  function closePicker() {
    picker = null;
    hideZoom();
    const panel = find('.wlr-picker');
    panel.hidden = true;
    panel.replaceChildren();
  }

  async function pick(name) {
    hideZoom();
    const current = picker = {name};
    const panel = find('.wlr-picker');
    panel.hidden = false;
    panel.innerHTML = `<header>PNG 고르기 · <b>${esc(name)}</b>${byName(name).has_saved_thumb
      ? '<button class="tagsearch-act" data-reset>저장 썸네일 지우기</button>' : ''}
      <button class="tagsearch-x" data-back aria-label="닫기">×</button></header><div class="wlr-history">불러오는 중…</div>`;
    const body = find('.wlr-history');
    try {
      const {candidates} = await request('/history' + query(name));
      if (current !== picker) return;
      const grid = rows => `<div class="wlr-grid">${rows.map(row => `<button data-history="${esc(row.history_id)}"
        data-zoom="${esc(row.zoom_url || row.thumb_url)}" aria-label="썸네일 선택"><img loading="lazy" src="${esc(row.thumb_url)}" alt=""></button>`).join('')}</div>`;
      const used = candidates.filter(row => row.used), other = candidates.filter(row => !row.used);
      body.innerHTML = (used.length ? '<h4>이 LoRA를 켜고 만든 그림</h4>' + grid(used) : '')
        + (other.length ? (used.length ? '<h4>다른 그림</h4>' : '') + grid(other) : '');
      if (!candidates.length) body.textContent = '히스토리에 그림이 없습니다.';
    } catch (err) { if (current === picker) body.textContent = err.message; }
  }

  async function changeThumb(button) {
    const current = picker;
    if (!current || current.busy) return;
    current.busy = true;
    try {
      const {name} = current;
      if (button.hasAttribute('data-reset')) await request('/thumb' + query(name), 'DELETE');
      else await request('/thumb/history', 'POST', {name, history_id:button.dataset.history});
      if (picker === current) closePicker();
      if (isOpen()) await load();
    } catch (err) { showToast(err.message, 'error'); }
    finally { current.busy = false; }
  }

  function saveMeta(entry, field, value, control) {
    control.disabled = true;
    write(async () => {
      try {
        const result = await request('/meta', 'PUT', {name:entry.name, [field]:value});
        entry[field] = result[field];
        if (!isOpen() || entry !== byName(entry.name)) return;
        if (field === 'favorite') { folders(); cards(); }
      } finally {
        control.disabled = false;
        if (field === 'default_strength') control.value = formatStrength(entry.default_strength);
      }
    });
  }

  function click(e) {
    const b = e.target.closest('button');
    if (!b || mode !== 'WEBUI') return;
    const d = b.dataset;
    if ('reload' in d) { closePicker(); return load(true); }
    if ('openFolder' in d) return request('/open-folder', 'POST', {}).catch(err => showToast(err.message, 'error'));
    if ('back' in d) return closePicker();
    if ('history' in d || 'reset' in d) return changeThumb(b);
    if ('folder' in d || 'favorites' in d) {
      category = d.folder ?? FAVORITES;
      folders();
      return cards();
    }
    const entry = byName(b.closest('[data-name]')?.dataset.name);
    if (!entry) return;
    if ('picker' in d) return pick(entry.name);
    if ('star' in d) return saveMeta(entry, 'favorite', !entry.favorite, b);
    if ('add' in d) {
      const input = b.closest('article').querySelector('[data-default]');
      if (!input.value || !input.validity.valid) return;
      const text = insertToken(promptEdit.value, entry.name, Number(input.value));
      if (text === promptEdit.value) showToast('이미 들어 있습니다', 'info');
      else setPrompt(text);
    }
  }

  function build() {
    const vw = win.innerWidth || 1280, vh = win.innerHeight || 800;
    shell = createPanel({
      title: 'LoRA · WEBUI',
      variant: 'webui-lora-win',
      storageKey: 'webui-lora',
      width: Math.max(360, Math.min(620, vw - 16)),
      minWidth: 360,
      maxWidth: 960,
      height: Math.max(240, Math.min(470, vh - 70)),
      minHeight: 220,
      resizable: true,
      escHtml: esc,
      onClose: closed,
    });
    shell.slot.innerHTML = `<span class="tagsearch-status"></span>
      <button type="button" class="tagsearch-act" data-open-folder>폴더 열기</button>
      <button type="button" class="tagsearch-act" data-reload aria-label="새로고침" title="새로고침">↻</button>`;
    popup = document.createElement('section');
    popup.className = 'webui-lora-popup';
    popup.innerHTML = `<div class="wlr-body"><nav class="wlr-folders" aria-label="LoRA 폴더"></nav><div class="wlr-main">
      <div class="tagsearch-searchrow"><input type="search" class="tagsearch-input" placeholder="LoRA 찾기 (이름 · 트리거 워드)" aria-label="LoRA 찾기"></div>
      <div class="wlr-cards"></div></div></div><div class="wlr-message" role="status" hidden></div>
      <div class="wlr-picker" role="dialog" aria-label="히스토리에서 PNG 고르기" hidden></div>`;
    shell.body.appendChild(popup);
    shell.el.addEventListener('click', click);
    find('[type=search]').addEventListener('input', cards);
    popup.addEventListener('change', e => {
      const input = e.target;
      if (!input.hasAttribute('data-default')) return;
      const entry = byName(input.closest('article').dataset.name);
      if (input.value && input.validity.valid) saveMeta(entry, 'default_strength', Number(input.value), input);
      else { input.value = formatStrength(entry.default_strength); showToast('강도는 -2 ~ 2 사이로 적어 주세요.', 'error'); }
    });
    shell.el.addEventListener('keydown', e => {
      if (e.key === 'Escape') { e.preventDefault(); picker ? closePicker() : close(); }
    });
    popup.addEventListener('pointerover', e => {
      if (e.pointerType === 'touch') return;
      const target = e.target.closest('[data-zoom]');
      if (target === zoomTarget) return;
      hideZoom();
      if (!target) return;
      zoomTarget = target;
      zoomTimer = win.setTimeout(() => {
        if (!popup.contains(target) || zoomTarget !== target) return;
        zoomShown = true;
        zoom.show(target, {src:target.dataset.zoom, title:picker?.name || target.closest('article').dataset.name}, shell.el.getBoundingClientRect());
      }, 140);
    });
    popup.addEventListener('pointerout', e => {
      if (!zoomTarget?.contains(e.relatedTarget)) hideZoom();
    });
  }

  function open() {
    if (mode !== 'WEBUI') return;
    if (!shell) build();
    if (isOpen()) {
      // 이미 떠 있다 - 접혀 있으면 펴서 앞으로 가져온다(다시 불러오지는 않는다)
      if (shell.isCollapsed?.()) shell.expand?.();
      shell.raise?.();
      return;
    }
    shell.open();
    shell.bringIntoView?.();
    onStateChange();
    return load();
  }

  // 창이 닫힌 뒤의 정리 - × · Esc · 런처 · 모드 전환 모두 여기로 온다(창의 onClose).
  function closed() {
    ++revision;
    closePicker();
    onStateChange();
  }

  function close() {
    if (isOpen()) shell.close();
  }

  function setMode(next) {
    mode = next;
    if (mode !== 'WEBUI') close();
  }
  // 런처 단추: 떠 있고 펴져 있으면 닫고, 접혀 있으면 편다.
  const toggle = () => isOpen() && !shell.isCollapsed?.() ? close() : open();
  return {open, close, toggle, isOpen, setMode};
}
