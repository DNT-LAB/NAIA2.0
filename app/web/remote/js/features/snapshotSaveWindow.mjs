/**
 * 스냅샷 저장 창 (결과 그림 우클릭 > [NAI] 스냅샷 저장).
 *
 * 우클릭한 **그 그림**으로 스냅샷을 담기 전에 거치는 자리다(사용자 지정 2026-10-04):
 *
 *      ┌─ 스냅샷 저장 ──────────────────────────── [—] [×] ┐
 *      │ [카테고리] [하위] │ [카드 미리보기]  이름           │
 *      │                   │                  담을 항목 ☑☑☑ │
 *      │                   │ 어디에 담는가          [저장]  │
 *      └───────────────────────────────────────────────────┘
 *
 * · 왼쪽은 Snapshot 창과 같은 두 칸이다 - 여기서 카테고리를 고르거나 만든다.
 * · 오른쪽 카드는 목록에 놓일 모양 그대로다(같은 옷 `.ia-sc-scard`). 이름 · 카테고리 · 체크를 바꾸면 따라 바뀐다.
 * · 체크를 끈 항목은 스냅샷에 **아예 담기지 않는다** - 불러올 때 목록에도 나오지 않는다.
 *
 * 떠 있는 창(draggablePanel)인 이유: **[저장] 을 누르는 순간의 설정**이 담긴다. 창을 옆에 둔 채
 * 프롬프트 · 캐릭터를 더 고친 뒤 담을 수 있어야 한다. 그림만 우클릭한 그 장으로 고정된다.
 *
 * ⚠️ 저장은 Snapshot 창의 `save` 를 빌린다. 서버가 "같은 이름이 있다" 고 되물을 때 다시 보내는 값을
 *    그쪽이 쥐고 있다 - 여기서 따로 보내면 되묻기 뒤의 재전송에서 그림 · 고른 항목이 빠진다.
 * ⚠️ 조작은 전부 `setModuleParam('snapshot', …)` 을 탄다 - 새 WS 메시지 타입을 만들지 않는다.
 */
import {createDraggablePanel} from './draggablePanel.mjs?v=20260926-childalign';
import {SNAPSHOT_PICK_ITEMS, sanitizeSnapshotName} from './snapshotPanel.mjs?v=20261005-snapnosave';

// 담을 항목의 마지막 선택. **꺼 둔 것만** 적는다 - 항목이 늘어도 새 항목은 켜진 채로 나온다.
// 처음에는 데이터셋만 꺼져 있다(크기만큼 용량을 쓴다).
const OFF_KEY = 'naia.snapshot.saveSections.v1';
// 마지막으로 담은 카테고리. 같은 자리에 잇달아 담는 일이 많다.
const FOLDER_KEY = 'naia.snapshot.saveFolder.v1';

const SAVE_TIPS = {
  prompt: '지금의 메인 프롬프트',
  negative: '지금의 네거티브 프롬프트',
  params: '모델 · 해상도 · 스텝 · CFG · 샘플러 · 시드 등',
  prompt_engineering: 'Prefix · Postfix · Auto-Hide · 전처리 옵션',
  characters: '지금 켜 둔 캐릭터의 프롬프트 · 좌표 · Connect',
  conditional: '조건부 프롬프트 규칙',
  vibe_transfer: 'Vibe Transfer 항목과 그 그림',
  character_reference: 'Character Reference 항목과 그 그림',
  search: 'Tag Filter 와 불러온 데이터셋의 사본. 데이터셋 크기만큼 용량을 씁니다',
};

const BLOCKER_TEXT = {
  mode: 'Snapshot 은 지금 NAI 모드에서만 저장할 수 있습니다',
  model: 'Snapshot 은 NAI V4.5 · V5 모델에서만 저장할 수 있습니다',
};

const SEARCH_BLOCKER_TEXT = {
  empty: '불러온 데이터셋이 없습니다',
  temporary: '임시 검색 공간에서는 데이터셋을 담을 수 없습니다',
};

export function createSnapshotSaveWindow({
  document,
  window: win = (typeof window !== 'undefined' ? window : null),
  escHtml, showToast, setModuleParam,
  // ⚠️ `window.prompt` / `window.confirm` 을 쓰지 않는다 - Electron 은 `prompt` 를 구현하지 않는다.
  showPromptDialog = null,
  showConfirmDialog = null,
  // Snapshot 창의 `save(request, {overwrite})`. 밀린 편집 flush · 되묻기 재전송이 거기 들어 있다.
  saveSnapshot,
}) {
  let panel = null;
  let lastState = null;
  let preview = null;          // 서버가 알려 준 "지금 담으면 무엇이 들어가나"
  let draft = null;            // {image, imageSrc} - 우클릭한 그 그림
  let top = '';                // 고른 카테고리. 비면 분류 없음
  let sub = '';                // 그 아래 하위
  let off = readOff();
  let busy = false;
  let awaiting = null;         // {name, before} - 보낸 저장이 목록에 나타나기를 기다린다
  let wantFolder = false;      // 방금 만든 카테고리를 기다리는 중
  let restoreFolder = '';      // 지난번에 담은 카테고리 - 목록을 받은 뒤에야 고를 수 있다
  let previewAt = 0;

  const esc = value => escHtml(String(value ?? ''));
  const $ = selector => panel?.body.querySelector(selector);

  // ── 기억(localStorage) ──────────────────────────────────────────────────
  function readOff() {
    try {
      const raw = globalThis.localStorage?.getItem(OFF_KEY);
      if (raw === null || raw === undefined) return new Set(['search']);
      const data = JSON.parse(raw);
      return new Set(Array.isArray(data) ? data.map(String) : ['search']);
    } catch (_) { return new Set(['search']); }
  }

  function writeOff() {
    try { globalThis.localStorage?.setItem(OFF_KEY, JSON.stringify([...off])); } catch (_) { /* 사생활 모드 */ }
  }

  function readFolder() {
    try { return String(globalThis.localStorage?.getItem(FOLDER_KEY) || ''); } catch (_) { return ''; }
  }

  function rememberFolder() {
    try { globalThis.localStorage?.setItem(FOLDER_KEY, sub || top); } catch (_) { /* 사생활 모드 */ }
  }

  // ── 도우미 ──────────────────────────────────────────────────────────────
  const snapshots = () => (Array.isArray(lastState?.snapshots) ? lastState.snapshots : []);
  const folders = () => (Array.isArray(lastState?.folders) ? lastState.folders : []);
  const findFolder = id => folders().find(folder => String(folder.id) === String(id));
  const findByName = name => snapshots().find(item => String(item.name).toLowerCase() === String(name).toLowerCase());

  function folderOf(item) {
    const id = String(item?.folder || '');
    return id && findFolder(id) ? id : '';
  }

  function folderLabel(id) {
    const folder = findFolder(id);
    if (!folder) return '';
    const up = folder.parent ? findFolder(folder.parent) : null;
    return up ? `${up.name} / ${folder.name}` : String(folder.name || '');
  }

  function countIn(id) {
    const subIds = new Set(folders().filter(f => String(f.parent || '') === String(id)).map(f => String(f.id)));
    return snapshots().filter(item => folderOf(item) === String(id) || subIds.has(folderOf(item))).length;
  }

  /** 고른 카테고리가 사라졌으면(다른 창에서 지웠다) 분류 없음으로 물러난다. */
  function settleFolder() {
    if (top && !findFolder(top)) { top = ''; sub = ''; }
    if (sub && !findFolder(sub)) sub = '';
  }

  function selectFolder(id) {
    const folder = findFolder(id);
    if (!folder) { top = ''; sub = ''; return; }
    if (folder.parent && findFolder(folder.parent)) { top = String(folder.parent); sub = String(folder.id); }
    else { top = String(folder.id); sub = ''; }
  }

  function searchBlocker() {
    if (!preview) return '';
    if (preview.search === null || preview.search === undefined) return 'empty';
    return String(preview.search.blocker || '');
  }

  /** 담을 항목 = 꺼 두지 않은 것. 담을 데이터셋이 없으면 데이터셋은 뺀다. */
  function pickedKeys() {
    return SNAPSHOT_PICK_ITEMS.map(([key]) => key)
      .filter(key => !off.has(key))
      .filter(key => key !== 'search' || !searchBlocker());
  }

  function countText(key) {
    if (!preview) return '';
    const number = value => (value === null || value === undefined ? '' : String(Number(value || 0)));
    if (key === 'characters') return number(preview.character_count);
    if (key === 'vibe_transfer') return number(preview.vibe_count);
    if (key === 'character_reference') return number(preview.reference_count);
    if (key === 'conditional') return preview.conditional_enabled ? '켜짐' : (preview.conditional_enabled === false ? '꺼짐' : '');
    if (key === 'search') return searchBlocker() ? '' : `${Number(preview.search?.rows || 0).toLocaleString()}행`;
    return '';
  }

  /** 카드 아래 한 줄. Snapshot 창의 카드와 같은 규칙으로 적는다 - 담지 않는 항목은 빠진다. */
  function metaBits() {
    const picked = new Set(pickedKeys());
    const bits = [];
    if (!preview) return bits;
    const chars = Number(preview.character_count || 0);
    if (picked.has('characters') && chars) bits.push(`C${chars}`);
    if (picked.has('conditional') && preview.conditional_enabled) bits.push('조건부');
    const vibes = Number(preview.vibe_count || 0);
    if (picked.has('vibe_transfer') && vibes) bits.push(`Vibe ${vibes}`);
    const refs = Number(preview.reference_count || 0);
    if (picked.has('character_reference') && refs) bits.push(`Ref ${refs}`);
    if (picked.has('search')) bits.push(`${Number(preview.search?.rows || 0).toLocaleString()}행`);
    return bits;
  }

  function blockerText() {
    const blocker = String(lastState?.save_blocker || '');
    // 'no_image' 는 여기와 상관없다 - 그림은 우클릭한 것이 따로 있다.
    return BLOCKER_TEXT[blocker] || '';
  }

  function confirmBox(message, options) {
    return (typeof showConfirmDialog === 'function')
      ? Promise.resolve(showConfirmDialog(message, options))
      : Promise.resolve(globalThis.confirm(message));
  }

  async function askText(title) {
    if (typeof showPromptDialog !== 'function') return null;
    const got = await showPromptDialog('', {title, defaultValue: '', placeholder: '', okText: '확인', cancelText: '취소'});
    if (got === null || got === undefined || got === false) return null;
    return String(got).trim();
  }

  // ── 창 ──────────────────────────────────────────────────────────────────
  function ensure() {
    if (panel) return panel;
    const vw = win?.innerWidth || document.documentElement.clientWidth || 1280;
    const width = Math.max(300, Math.min(640, vw - 12));
    panel = createDraggablePanel({
      document, window: win,
      id: 'snapshotSaveWindow',
      title: '스냅샷 저장',
      variant: 'snapsave',
      storageKey: 'snapshot-save',
      width, minWidth: Math.min(300, width), maxWidth: 640,
      escHtml,
      onClose: () => { awaiting = null; busy = false; wantFolder = false; },
    });
    // 뼈대는 한 번만 만든다. 이름 칸을 다시 그리면 한글 조합이 글자마다 끊긴다 - 칸들만 따로 갈아 끼운다.
    panel.body.innerHTML = `
      <div class="snapsave-blocker" data-ss="blocker" hidden></div>
      <div class="snapsave-grid">
        <div class="ia-sc-col ia-sc-col1" data-ss="col1"></div>
        <div class="ia-sc-col ia-sc-col2" data-ss="col2"></div>
        <div class="snapsave-main">
          <div class="snapsave-top">
            <div class="snapsave-cardbox" data-naia-title="Snapshot 목록에 이 모양으로 놓입니다">
              <div class="ia-sc-scard snap-card">
                <div class="ia-sc-sthumb"><img alt="" draggable="false" data-ss="img"><div class="snap-card-top" data-ss="chips"></div></div>
                <div class="ia-sc-sname" data-ss="card-name"></div>
                <div class="ia-sc-smeta" data-ss="card-meta"></div>
              </div>
            </div>
            <div class="snapsave-form">
              <input type="text" class="ia-sc-search snapsave-name" data-ss="name" maxlength="80"
                     autocomplete="off" placeholder="스냅샷 이름">
              <div class="snapsave-sec">담을 항목</div>
              <div class="snap-picks" data-ss="picks"></div>
            </div>
          </div>
          <div class="snapsave-foot">
            <span class="snapsave-where" data-ss="where"></span>
            <button type="button" class="ia-sc-btn is-main" data-ss-act="save">저장</button>
          </div>
        </div>
      </div>`;
    panel.body.addEventListener('click', onClick);
    panel.body.addEventListener('change', onChange);
    panel.body.addEventListener('input', onInput);
    panel.body.addEventListener('keydown', onKey);
    // 창을 옆에 둔 채 설정을 고치다 돌아온다 - 마우스가 들어올 때 수치를 다시 받는다.
    panel.el.addEventListener('pointerenter', () => requestPreview(false));
    return panel;
  }

  function requestPreview(force) {
    if (busy) return;                       // 저장 응답을 기다리는 동안은 부르지 않는다(잠금이 먼저 풀린다)
    const now = Date.now();
    if (!force && now - previewAt < 2000) return;
    previewAt = now;
    setModuleParam('snapshot', 'preview', {});
  }

  function renderCols() {
    const col1 = $('[data-ss="col1"]');
    const col2 = $('[data-ss="col2"]');
    if (!col1 || !col2) return;
    const all = snapshots();
    const row = (on, act, id, label, count) =>
      `<button type="button" class="ia-sc-item${on ? ' is-on' : ''}" data-ss-act="${act}" data-fid="${esc(id)}">`
      + `<span class="snap-item-t">${esc(label)}</span><span class="snap-item-n">${esc(count)}</span></button>`;
    const tops = folders().filter(folder => !folder.parent);
    col1.innerHTML = [
      row(!top, 'top', '', '분류 없음', all.filter(item => !folderOf(item)).length),
      ...tops.map(folder => row(top === String(folder.id), 'top', folder.id, folder.name, countIn(folder.id))),
      `<button type="button" class="ia-sc-item is-add" data-ss-act="folder-new" data-fid=""
         data-naia-title="카테고리를 만듭니다">+ 카테고리</button>`,
    ].join('');
    if (!top) {
      col2.innerHTML = '<div class="ia-sc-hint">카테고리를 고르면 그 하위가 여기에 나옵니다.</div>';
      return;
    }
    const subs = folders().filter(folder => String(folder.parent || '') === top);
    col2.innerHTML = [
      row(!sub, 'sub', '', '바로 여기에', all.filter(item => folderOf(item) === top).length),
      ...subs.map(folder => row(sub === String(folder.id), 'sub', folder.id, folder.name,
        all.filter(item => folderOf(item) === String(folder.id)).length)),
      `<button type="button" class="ia-sc-item is-add" data-ss-act="folder-new" data-fid="${esc(top)}"
         data-naia-title="이 카테고리 안에 만듭니다">+ 하위</button>`,
    ].join('');
  }

  function renderPicks() {
    const box = $('[data-ss="picks"]');
    if (!box) return;
    const blocked = searchBlocker();
    box.innerHTML = SNAPSHOT_PICK_ITEMS.map(([key, label]) => {
      const dead = key === 'search' && !!blocked;
      const tip = dead ? (SEARCH_BLOCKER_TEXT[blocked] || '지금은 데이터셋을 담을 수 없습니다') : SAVE_TIPS[key];
      const count = countText(key);
      return `<label class="snap-pick${dead ? ' is-dead' : ''}" data-naia-title="${esc(tip)}">
        <input type="checkbox" data-ss-pick="${esc(key)}"${(!off.has(key) && !dead) ? ' checked' : ''}${dead ? ' disabled' : ''}>${esc(label)}${
          count ? ` <span class="snap-pick-n">${esc(count)}</span>` : ''}</label>`;
    }).join('');
  }

  /** 카드 · 담는 자리 · 저장 단추. 체크 상자와 이름 칸은 건드리지 않는다(초점 · 조합을 지킨다). */
  function renderCard() {
    const img = $('[data-ss="img"]');
    if (img && draft && img.getAttribute('src') !== draft.imageSrc) img.setAttribute('src', draft.imageSrc);
    const chips = $('[data-ss="chips"]');
    if (chips) {
      chips.innerHTML = preview?.model_label
        ? `<span class="snap-top-chip"><span class="custom-select-model-tag" data-family="${esc(preview.model_family || '')}"`
          + ` data-variant="${esc(preview.model_variant || '')}">${esc(preview.model_label)}</span></span>`
        : '';
    }
    const name = sanitizeSnapshotName($('[data-ss="name"]')?.value || '');
    const nameEl = $('[data-ss="card-name"]');
    if (nameEl) {
      nameEl.textContent = name || '이름 없음';
      nameEl.classList.toggle('is-empty', !name);
    }
    const place = folderLabel(sub || top);
    const meta = $('[data-ss="card-meta"]');
    if (meta) meta.textContent = [place, ...metaBits()].filter(Boolean).join(' · ') || ' ';
    const where = $('[data-ss="where"]');
    if (where) {
      const exists = name && findByName(name);
      where.textContent = exists
        ? `같은 이름이 있습니다 — 덮어씁니다`
        : `${place || '분류 없음'} 에 담습니다`;
      where.classList.toggle('is-warn', !!exists);
    }
    const blocker = blockerText();
    const line = $('[data-ss="blocker"]');
    if (line) { line.hidden = !blocker; line.textContent = blocker; }
    const button = $('[data-ss-act="save"]');
    if (button) {
      button.disabled = busy || !!blocker || !pickedKeys().length;
      button.textContent = busy ? '저장 중…' : '저장';
    }
  }

  function renderAll() {
    if (!panel || !panel.isOpen()) return;
    settleFolder();
    renderCols();
    renderPicks();
    renderCard();
  }

  // ── 서버 상태 ───────────────────────────────────────────────────────────
  /** `snapshot` 모듈 상태가 올 때마다 불린다. ⚠️ app.js 는 이것을 Snapshot 창의 `render` **앞에** 부른다 -
   *  여기서 만든 카테고리의 `created_folder` 를 먼저 가져가야 그 창의 선택이 엉뚱하게 옮겨 가지 않는다. */
  function render(state) {
    if (!state) return;
    lastState = state;
    if (state.save_preview) preview = state.save_preview;
    if (wantFolder && state.created_folder?.id) {
      wantFolder = false;
      const made = state.created_folder;
      delete state.created_folder;
      if (made.parent) { top = String(made.parent); sub = String(made.id); } else { top = String(made.id); sub = ''; }
    }
    if (restoreFolder && panel?.isOpen()) { selectFolder(restoreFolder); restoreFolder = ''; }
    busy = false;
    if (awaiting) {
      const row = findByName(awaiting.name);
      if (row && String(row.saved_at || '') !== awaiting.before) {
        // 담겼다. 창을 걷는다 - 실패했으면(그림이 사라졌다 등) 열어 둔 채로 고쳐 다시 누를 수 있다.
        awaiting = null;
        rememberFolder();
        const input = $('[data-ss="name"]');
        if (input) input.value = '';
        panel?.close();
        return;
      }
    }
    renderAll();
  }

  /** 우클릭한 그림으로 연다. 이미 열려 있으면 그림만 바꾼다 - 적던 이름 · 고른 것은 그대로다. */
  function open({image, imageSrc} = {}) {
    if (!image) { showToast('저장할 이미지를 특정할 수 없습니다', 'error'); return; }
    ensure();
    const wasOpen = panel.isOpen();
    draft = {image: String(image), imageSrc: String(imageSrc || '') || `/api/viewer/image/${encodeURI(String(image))}`};
    if (!wasOpen) {
      awaiting = null;
      busy = false;
      // 목록을 아직 못 받았으면(이번 실행에서 처음 연다) 받은 뒤에 고른다 - 지금 고르면 '없는 카테고리' 로 읽힌다.
      restoreFolder = readFolder();
      if (lastState) { selectFolder(restoreFolder); restoreFolder = ''; }
    }
    panel.open();
    if (panel.isCollapsed()) panel.expand();
    renderAll();
    requestPreview(true);
    if (!wasOpen) $('[data-ss="name"]')?.focus();
  }

  function close() { panel?.close(); }

  // ── 조작 ─────────────────────────────────────────────────────────────────
  async function newFolder(parent) {
    const name = await askText(parent ? '하위 카테고리 이름' : '카테고리 이름');
    if (!name) return;
    wantFolder = true;
    setModuleParam('snapshot', 'folder_create', {name, parent: parent || ''});
  }

  async function save() {
    if (busy || !draft) return;
    const input = $('[data-ss="name"]');
    const name = sanitizeSnapshotName(input?.value || '');
    if (!name) { showToast('스냅샷 이름을 입력하세요', 'error'); input?.focus(); return; }
    if (name.startsWith('_')) { showToast('이름은 _ 로 시작할 수 없습니다', 'error'); input?.focus(); return; }
    const blocker = blockerText();
    if (blocker) { showToast(blocker, 'error'); return; }
    const sections = pickedKeys();
    if (!sections.length) { showToast('담을 항목을 하나 이상 체크하세요', 'error'); return; }
    // ⚠️ **다듬은 이름으로 견준다** - 목록의 이름은 이미 다듬어져 있다.
    const existing = findByName(name);
    if (existing) {
      const ok = await confirmBox(`"${name}" 스냅샷을 덮어씁니다. 계속할까요?`,
                                  {title: '덮어쓰기', okText: '덮어쓰기', cancelText: '취소'});
      if (!ok) return;
    }
    awaiting = {name, before: existing ? String(existing.saved_at || '') : ''};
    busy = true;
    renderCard();
    saveSnapshot({name, image: draft.image, sections, folder: sub || top, relocate: true}, {overwrite: !!existing});
  }

  function onClick(event) {
    const hit = event.target?.closest?.('[data-ss-act]');
    if (!hit || hit.disabled) return;
    const act = hit.dataset.ssAct;
    if (act === 'save') save();
    else if (act === 'top') { top = hit.dataset.fid || ''; sub = ''; renderCols(); renderCard(); }
    else if (act === 'sub') { sub = hit.dataset.fid || ''; renderCols(); renderCard(); }
    else if (act === 'folder-new') newFolder(hit.dataset.fid || '');
  }

  function onChange(event) {
    const pick = event.target?.closest?.('[data-ss-pick]');
    if (!pick) return;
    const key = pick.dataset.ssPick || '';
    if (pick.checked) off.delete(key); else off.add(key);
    writeOff();
    // ⚠️ 체크 줄은 다시 그리지 않는다 - 초점이 날아가 키보드로 이어서 고를 수 없다.
    renderCard();
  }

  function onInput(event) {
    if (event.target?.dataset?.ss === 'name') renderCard();
  }

  function onKey(event) {
    if (event.key !== 'Enter' || event.isComposing || event.target?.dataset?.ss !== 'name') return;
    event.preventDefault();
    save();
  }

  return {open, close, render, isOpen: () => !!panel && panel.isOpen()};
}
