/** 보기(벤치) 설정 창 — 보기 하나를 보고 고친다. 창은 **하나**를 돌려 쓴다.
 *
 *  **한 화면**이다(사용자 지정 2026-09-26 - 요약과 편집이 공존할 필요가 없다. 바로 고치고 [저장]).
 *  글 칸(prefix/postfix/negative · 캐릭터)은 넓게. 캐릭터는 [메인 캐릭터 프롬프트 | 독립 캐릭터 프롬프트]
 *  토글 - 메인이면 생성 순간 메인 화면의 캐릭터, 독립이면 보기의 캐릭터(+ 캐릭터 는 독립일 때만).
 *  prefix · postfix · 캐릭터 칸은 메인 프롬프트와 같은 자동완성을 쓴다(`bindTagAssist`).
 *  새 구도는 바로 만들어 연다 - 글은 지금 PE 프리셋에서, 이름은 `새 구도`, `새 구도 2` ….
 *
 *  ⚠️ 작업본(저장 전 입력)은 조용히 사라지면 안 된다(Codex 감사 2026-09-26: 이미 고른 [편집] 탭을 다시
 *     누르면 입력이 초기화됐다). 고치는 중에는 다른 곳의 변경으로 다시 그리지 않고, 다른 보기로 넘어가면
 *     먼저 묻는다. 다시 그릴 때(캐릭터 넣고 빼기)는 스크롤 자리를 지킨다.
 *  ⚠️ 자동완성 목록은 캐럿 자리에 `fixed` 로 뜬다 - 이 창이 안에서 스크롤되면 목록만 허공에 남는다.
 *     목록이 떠 있는 채로 스크롤되면 칸의 초점을 풀어 목록을 닫는다.
 *
 *  ⚠️ `window.prompt()` 를 쓰지 않는다(Electron 렌더러에 없다) - 이름은 창 안의 칸으로 받는다.
 *  ⚠️ 삭제는 두 번 눌러야 한다(그룹 창과 같은 규칙). 뽑아 둔 그림 파일은 서버가 지우지 않는다.
 */
import {createDraggablePanel} from './draggablePanel.mjs?v=20260919-headdrag';

const MAX_CHARACTERS = 6;

export function createArtistBenchViewWindow({
  document: doc,
  window: win = (typeof window !== 'undefined' ? window : null),
  store,
  escHtml = v => String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'),
  showToast = () => {},
  confirmDialog = null,
  bindTagAssist = null,       // (textarea, options) => void  메인 프롬프트와 같은 자동완성
} = {}) {
  let panel = null;
  let viewId = '';
  let draft = null;           // 작업본(저장 전)
  let dirty = false;          // 작업본을 사용자가 고쳤는가 - 고쳤으면 다시 그려 덮지 않는다
  let unsub = null;

  function ensurePanel() {
    if (panel) return panel;
    panel = createDraggablePanel({
      document: doc, window: win, title: '보기 설정', variant: 'abv', storageKey: 'bench-view',
      width: 440, minWidth: 320, maxWidth: 820, height: 700, resizable: true,
      initial: {x: 340, y: 90}, escHtml,
      onClose: () => { viewId = ''; draft = null; dirty = false; },
    });
    panel.el.setAttribute('data-rctl-companion', '');   // 리모컨의 '바깥 누름' 에서 안쪽
    panel.body.addEventListener('click', onClick);
    panel.body.addEventListener('input', onInput);
    panel.body.addEventListener('change', onInput);
    panel.body.addEventListener('keydown', event => event.stopPropagation());   // 전역 단축키가 새지 않게
    unsub = store.subscribe((_data, reason) => {
      if (!panel.isOpen()) return;
      if (viewId && !store.get(viewId)) { panel.close(); return; }          // 다른 곳에서 지워졌다
      if (!dirty) { draft = null; render(); }                                // 고치는 중이면 덮지 않는다
    });
    return panel;
  }

  // ── 열기 ──────────────────────────────────────────────────────────────
  async function open(id, {parentPanel = null} = {}) {
    ensurePanel();
    // 저장하지 않은 입력이 있는데 **다른** 보기로 넘어간다 - 먼저 묻는다(조용히 버리지 않는다).
    if (dirty && viewId && viewId !== id && panel.isOpen()) {
      const ok = await Promise.resolve(confirmDialog ? confirmDialog(
        `'${view()?.name || '이 보기'}' 에 저장하지 않은 변경이 있습니다. 버리고 넘어갈까요?`,
        {title: '저장하지 않은 변경'}) : true);
      if (!ok) { panel.raise(); return; }
    }
    if (viewId !== id) { draft = null; dirty = false; }
    viewId = id;
    panel.open(); panel.raise();
    render();
  }

  /** 겹치지 않는 자동 이름 - `새 구도`, `새 구도 2`, … (서버는 같은 이름을 409 로 거절한다). */
  function freshName() {
    const taken = new Set(store.views().map(v => String(v.name).toLocaleLowerCase()));
    for (let i = 1; i < 1000; i += 1) {
      const name = i === 1 ? '새 구도' : `새 구도 ${i}`;
      if (!taken.has(name.toLocaleLowerCase())) return name;
    }
    return `새 구도 ${Date.now()}`;
  }

  /** 바로 만들고 [편집] 탭으로 연다. 그룹에서 불렀으면 그 그룹이 곧바로 고른다. */
  async function openNew(groupId = '', {parentPanel = null} = {}) {
    try {
      const current = await store.refreshCurrent();
      if (!current) throw new Error('지금 설정을 읽지 못했습니다');
      // 글(prefix/postfix/negative)은 **지금 보고 있는 PE 프리셋**에서(사용자 지정 2026-09-26 - 비워 두니
      // 휑해서 오히려 어렵다). 작가 태그·믹스 표식은 서버가 이미 걷어 냈다. 캐릭터는 비운다.
      const spec = {...current, characters: [], character_mode: 'main'};
      delete spec.stripped;
      const created = await store.create(freshName(), spec);
      if (groupId) await store.select(groupId, created.id);
      await open(created.id, {parentPanel});
    } catch (error) {
      showToast(error.message || '보기를 만들지 못했습니다.', 'error');
    }
  }

  // ── 그리기 ────────────────────────────────────────────────────────────
  const view = () => (viewId ? store.get(viewId) : null);

  function render() {
    if (!panel) return;
    const v = view();
    if (!v) { panel.close(); return; }
    panel.setTitle(`보기 · ${v.name}`);
    if (!draft) draft = draftFrom(v);
    // 다시 그려도(캐릭터 넣고 빼기) 보던 자리에 머문다.
    const keepTop = panel.body.querySelector('.abv-scroll')?.scrollTop || 0;
    panel.body.innerHTML = `<div class="abv-scroll">${editorHtml(draft)}</div>
      <div class="abv-actions">
        <button type="button" class="abv-btn primary" data-abv-act="save">저장</button>
        <button type="button" class="abv-btn" data-abv-act="revert" title="저장하지 않은 변경을 버립니다">되돌리기</button>
        <button type="button" class="abv-btn" data-abv-act="refresh"
                title="메인 화면의 지금 설정(PE 글 · 해상도 · 생성 설정)으로 이 보기를 덮습니다">지금 설정으로 갱신</button>
        <span class="abv-spacer"></span>
        <button type="button" class="abv-btn danger" data-abv-act="delete">삭제</button>
      </div>`;
    const scroll = panel.body.querySelector('.abv-scroll');
    scroll.scrollTop = keepTop;
    // 자동완성 - prefix · postfix · 캐릭터 칸(사용자 지정). 다시 그리면 칸이 새것이라 다시 붙인다.
    if (typeof bindTagAssist === 'function') {
      panel.body.querySelectorAll('[data-abv-field="prefix"], [data-abv-field="postfix"], [data-abv-char-field="prompt"]')
        .forEach(el => bindTagAssist(el));
    }
    // 목록이 떠 있는 채로 스크롤되면 닫는다 - 목록은 캐럿 자리에 fixed 라 칸을 따라오지 않는다.
    scroll.addEventListener('scroll', () => {
      const active = doc.activeElement;
      if (active && panel.body.contains(active) && doc.getElementById('tagTooltip')?.classList.contains('open')) active.blur();
    }, {passive: true});
  }

  function selectHtml(field, value, choices) {
    const list = [...new Set([...(choices || []), value].filter(v => v !== undefined && v !== null && v !== ''))];
    // `abv-select` - 공용 드롭다운(customSelects)이 `custom-abv-select` 로 옮겨 입는 옷 이름.
    return `<select class="abv-select" data-abv-field="${field}">${list.map(c =>
      `<option value="${escHtml(c)}"${c === value ? ' selected' : ''}>${escHtml(c)}</option>`).join('')}</select>`;
  }

  function editorHtml(d) {
    const s = d.settings || {};
    const o = store.options() || {};
    const area = (field, label, rows = 3, note = '') => `
      <label class="abv-field"><span>${label}${note ? `<em class="abv-hint">${note}</em>` : ''}</span>
        <textarea data-abv-field="${field}" rows="${rows}" spellcheck="false">${escHtml(d[field] || '')}</textarea></label>`;
    const own = d.character_mode !== 'main';
    const chars = (d.characters || []).map((c, i) => `
      <div class="abv-char" data-abv-char="${i}">
        <div class="abv-char-head"><span>캐릭터 ${i + 1}</span>
          <button type="button" class="abv-x" data-abv-act="char-remove" data-index="${i}" title="이 캐릭터 빼기">×</button></div>
        <textarea data-abv-char-field="prompt" rows="3" spellcheck="false" placeholder="캐릭터 프롬프트">${escHtml(c.prompt)}</textarea>
        <input type="text" data-abv-char-field="uc" spellcheck="false" placeholder="캐릭터 네거티브(선택)" value="${escHtml(c.uc || '')}">
      </div>`).join('');
    const fixed = Boolean(d.seedFixed);
    return `
      <label class="abv-field"><span>이름<em class="abv-hint">${escHtml(String(d.api_mode || ''))}${d.source_preset ? ` · ${escHtml(String(d.source_preset))} 에서` : ''}</em></span>
        <input type="text" data-abv-field="name" maxlength="40" spellcheck="false" value="${escHtml(d.name || '')}"></label>
      ${area('prefix', 'prefix', 5, '작가 태그는 맨 앞에 붙습니다')}${area('postfix', 'postfix', 5)}${area('negative', 'negative', 4)}
      <div class="abv-group"><div class="abv-group-head">
        <div class="abv-toggle" role="group" aria-label="캐릭터 프롬프트">
          <button type="button" class="${own ? '' : 'is-on'}" data-abv-act="char-mode" data-mode="main"
                  aria-pressed="${!own}" title="생성 순간 메인 화면의 캐릭터 프롬프트를 씁니다">메인 캐릭터 프롬프트</button>
          <button type="button" class="${own ? 'is-on' : ''}" data-abv-act="char-mode" data-mode="own"
                  aria-pressed="${own}" title="이 보기만의 캐릭터 프롬프트를 씁니다">독립 캐릭터 프롬프트</button>
        </div>
        <button type="button" class="abv-btn" data-abv-act="char-add"${!own || (d.characters || []).length >= MAX_CHARACTERS ? ' disabled' : ''}>+ 캐릭터</button></div>
        ${own
          ? (chars || '<div class="abv-empty small">캐릭터 없음 - 메인 화면의 캐릭터는 섞이지 않습니다.</div>')
          : '<div class="abv-empty small">생성할 때 메인 화면의 캐릭터 프롬프트를 그대로 씁니다.</div>'}</div>
      <div class="abv-grid">
        <label class="abv-field"><span>너비</span><input type="number" step="64" min="64" max="4096" data-abv-field="width" value="${d.width}"></label>
        <label class="abv-field"><span>높이</span><input type="number" step="64" min="64" max="4096" data-abv-field="height" value="${d.height}"></label>
        <label class="abv-field wide"><span>모델</span>${selectHtml('settings.model', s.model, o.model)}</label>
        <label class="abv-field"><span>샘플러</span>${selectHtml('settings.sampler', s.sampler, o.sampler)}</label>
        <label class="abv-field"><span>스케줄러</span>${selectHtml('settings.scheduler', s.scheduler, o.scheduler)}</label>
        <label class="abv-field"><span>스텝</span><input type="number" min="1" max="1000" data-abv-field="settings.steps" value="${s.steps ?? ''}"></label>
        <label class="abv-field"><span>CFG</span><input type="number" step="0.1" min="0" max="100" data-abv-field="settings.scale" value="${s.scale ?? ''}"></label>
        <label class="abv-field"><span>리스케일</span><input type="number" step="0.05" min="0" max="1" data-abv-field="settings.cfg_rescale" value="${s.cfg_rescale ?? ''}"></label>
        <div class="abv-field wide"><span>시드<em class="abv-hint">고정을 끄면 매번 랜덤</em></span>
          <div class="abv-seed${fixed ? '' : ' is-loose'}">
            <input type="number" min="0" max="4294967295" data-abv-field="seed" value="${escHtml(String(d.seedValue ?? ''))}" placeholder="숫자">
            <button type="button" class="abv-btn" data-abv-act="seed-roll" title="무작위 시드를 넣고 고정합니다">🎲 랜덤</button>
            <button type="button" class="abv-btn${fixed ? ' is-on' : ''}" data-abv-act="seed-fix"
                    aria-pressed="${fixed}" title="켜면 이 시드로 고정, 끄면 매번 랜덤">시드 고정</button>
          </div></div>
      </div>`;
  }

  // ── 편집 작업본 ────────────────────────────────────────────────────────
  function onInput(event) {
    if (!draft) return;
    const el = event.target;
    if (el.dataset?.abvField || el.dataset?.abvCharField) dirty = true;
    const field = el.dataset?.abvField;
    const charField = el.dataset?.abvCharField;
    if (charField) {
      const index = Number(el.closest('[data-abv-char]')?.dataset.abvChar);
      if (draft.characters?.[index]) draft.characters[index][charField] = el.value;
      return;
    }
    if (!field) return;
    if (field === 'seed') {
      draft.seedValue = el.value === '' ? '' : Math.max(0, Math.trunc(Number(el.value) || 0));
      if (el.value !== '' && !draft.seedFixed) { draft.seedFixed = true; paintSeed(); }
      return;
    }
    if (field.startsWith('settings.')) {
      const key = field.slice(9);
      const numeric = ['steps', 'scale', 'cfg_rescale'].includes(key);
      draft.settings = {...(draft.settings || {}), [key]: numeric ? Number(el.value) : el.value};
      return;
    }
    draft[field] = ['width', 'height'].includes(field) ? Number(el.value) : el.value;
  }

  /** 시드 줄만 다시 칠한다 - 쓰던 칸을 다시 그리면 커서가 날아간다. */
  function paintSeed() {
    const row = panel.body.querySelector('.abv-seed');
    if (!row || !draft) return;
    row.classList.toggle('is-loose', !draft.seedFixed);
    const fix = row.querySelector('[data-abv-act="seed-fix"]');
    fix.classList.toggle('is-on', Boolean(draft.seedFixed));
    fix.setAttribute('aria-pressed', String(Boolean(draft.seedFixed)));
    const input = row.querySelector('[data-abv-field="seed"]');
    if (String(input.value) !== String(draft.seedValue ?? '')) input.value = draft.seedValue ?? '';
  }

  /** 보기 -> 편집 작업본. 시드는 '값' 과 '고정 여부' 로 나눠 든다 - 고정을 꺼도 적어 둔 숫자는 남는다. */
  function draftFrom(v) {
    const d = structuredClone(v);
    d.seedFixed = Number(v.seed) >= 0;
    d.seedValue = Number(v.seed) >= 0 ? Number(v.seed) : '';
    return d;
  }

  function specFrom(d) {
    return {
      api_mode: d.api_mode, prefix: d.prefix, postfix: d.postfix, negative: d.negative,
      characters: (d.characters || []).filter(c => String(c.prompt || '').trim()),
      character_mode: d.character_mode === 'main' ? 'main' : 'own',
      source_preset: d.source_preset, width: d.width, height: d.height, settings: d.settings,
      seed: d.seedFixed && d.seedValue !== '' ? Number(d.seedValue) : -1,
    };
  }

  // ── 단추 ──────────────────────────────────────────────────────────────
  async function onClick(event) {
    const act = event.target.closest('[data-abv-act]')?.dataset.abvAct;
    if (!act) return;
    const v = view();
    try {
      if (act === 'refresh' && v) {
        const current = await store.refreshCurrent();
        if (current?.api_mode && current.api_mode !== v.api_mode) {
          showToast(`지금 모드(${current.api_mode})가 이 보기(${v.api_mode})와 다릅니다.`, 'error');
          return;
        }
        const ok = await Promise.resolve(confirmDialog ? confirmDialog(
          `'${v.name}' 보기를 지금 설정으로 덮습니다${dirty ? '(저장하지 않은 변경도 버립니다)' : ''}. 이미 뽑은 그림은 그대로 남습니다(옛 조건의 그림).`,
          {title: '지금 설정으로 갱신'}) : true);
        if (!ok) return;
        dirty = false;
        draft = null;
        // 캐릭터를 어디서 가져오는지는 사용자의 선택이다 - 갱신이 뒤집지 않는다.
        await store.update(v.id, {...current, character_mode: v.character_mode || 'own'});
        showToast(`'${v.name}' 을(를) 지금 설정으로 갱신했습니다.`, 'success');
      } else if (act === 'delete' && v) {
        const btn = event.target.closest('[data-abv-act]');
        if (btn.dataset.armed !== '1') {
          btn.dataset.armed = '1';
          btn.textContent = '정말 삭제';
          setTimeout(() => { if (btn.isConnected) { btn.dataset.armed = ''; btn.textContent = '삭제'; } }, 2500);
          return;
        }
        await store.remove(v.id);
        showToast(`'${v.name}' 보기를 지웠습니다.`, 'info');
        panel.close();
      } else if (act === 'save' && v && draft) {
        const name = String(draft.name || '').trim();
        const spec = specFrom(draft);
        // ⚠️ 작업본은 **성공한 뒤에** 내린다(Codex 리뷰 2026-09-26 #8: 먼저 내렸더니 서버가 거절한 저장 -
        //    예: NAI 해상도 833 - 에서 작업본을 잃고, 고쳐서 다시 [저장] 해도 draft 가 없어 아무 일도 없었다).
        //    고치는 중(dirty)이라 저장이 알리는 갱신은 다시 그리지 않는다 - 성공하면 아래에서 새 판으로 그린다.
        if (name && name !== v.name) await store.rename(v.id, name);
        await store.update(v.id, spec);
        dirty = false;
        draft = null;
        render();
        showToast('보기를 저장했습니다.', 'success');
      } else if (act === 'revert') {
        draft = null;
        dirty = false;
        render();
      } else if (act === 'char-mode' && draft) {
        const mode = event.target.closest('[data-abv-act]').dataset.mode === 'main' ? 'main' : 'own';
        if (draft.character_mode !== mode) { draft.character_mode = mode; dirty = true; render(); }
      } else if (act === 'seed-roll' && draft) {
        // NAI 시드 범위(0 ~ 2^32-1). 굴렸다는 것은 그 시드로 보겠다는 뜻이라 고정도 켠다.
        draft.seedValue = Math.floor(Math.random() * 4294967295);
        draft.seedFixed = true;
        dirty = true;
        paintSeed();
      } else if (act === 'seed-fix' && draft) {
        draft.seedFixed = !draft.seedFixed;
        if (draft.seedFixed && draft.seedValue === '') draft.seedValue = Math.floor(Math.random() * 4294967295);
        dirty = true;
        paintSeed();
      } else if (act === 'char-add' && draft) {
        if (draft.character_mode === 'main') return;
        draft.characters = [...(draft.characters || []), {prompt: '', uc: ''}].slice(0, MAX_CHARACTERS);
        dirty = true;
        render();
      } else if (act === 'char-remove' && draft) {
        draft.characters.splice(Number(event.target.closest('[data-abv-act]').dataset.index), 1);
        dirty = true;
        render();
      }
    } catch (error) {
      showToast(error.message || '보기를 바꾸지 못했습니다.', 'error');
    }
  }

  return {
    open,
    openNew,
    close: () => panel?.close(),
    isOpen: () => Boolean(panel?.isOpen()),
    destroy() { unsub?.(); panel?.destroy(); panel = null; },
  };
}
