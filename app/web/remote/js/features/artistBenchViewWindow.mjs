/** 보기(벤치) 설정 창 — 보기 하나를 보고 고친다. 창은 **하나**를 돌려 쓴다.
 *
 *  탭 둘(사용자 지정 2026-09-26 - '1 + 2 를 탭으로'):
 *   - [요약] 조건을 한눈에 · [지금 설정으로 갱신](메인 화면에서 맞춘 뒤 누른다) · 이름 · 삭제
 *   - [편집] 전용 편집기: prefix/postfix/네거티브 · 캐릭터 프롬프트 · 해상도 · 모델/샘플러/
 *            스케줄러 · 스텝/CFG/리스케일 · 시드
 *  새 보기는 **바로 만들고 [편집] 탭으로 연다**(사용자 지정 2026-09-26 - '지금 설정으로…' 를 미리
 *  요구할 필요가 없다. 보기를 먼저 만들고 보기에서 직접 설정한다). 이름은 `새 보기`, `새 보기 2` … 로
 *  붙이고 편집 탭 맨 위 칸에서 고친다. 처음 값: 글·캐릭터는 **비우고**, 생성 설정(해상도·모델·샘플러·
 *  스텝·CFG)만 지금 값 - 빈칸이면 생성할 수 없어서다. PE 글까지 떠 오려면 [요약] 의 [지금 설정으로 갱신].
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
} = {}) {
  let panel = null;
  let viewId = '';
  let tab = 'summary';
  let draft = null;           // 편집 탭의 작업본(저장 전)
  let unsub = null;

  function ensurePanel() {
    if (panel) return panel;
    panel = createDraggablePanel({
      document: doc, window: win, title: '보기 설정', variant: 'abv', storageKey: 'bench-view',
      width: 380, minWidth: 300, maxWidth: 720, height: 560, resizable: true,
      initial: {x: 340, y: 90}, escHtml,
      onClose: () => { viewId = ''; draft = null; },
    });
    panel.el.setAttribute('data-rctl-companion', '');   // 리모컨의 '바깥 누름' 에서 안쪽
    panel.body.addEventListener('click', onClick);
    panel.body.addEventListener('input', onInput);
    panel.body.addEventListener('change', onInput);
    panel.body.addEventListener('keydown', event => event.stopPropagation());   // 전역 단축키가 새지 않게
    unsub = store.subscribe((_data, reason) => {
      if (!panel.isOpen()) return;
      if (viewId && !store.get(viewId)) { panel.close(); return; }          // 다른 곳에서 지워졌다
      if (reason !== 'update' || tab !== 'edit') render();                   // 쓰는 중인 편집칸은 덮지 않는다
    });
    return panel;
  }

  // ── 열기 ──────────────────────────────────────────────────────────────
  async function open(id, {tab: startTab = 'summary'} = {}) {
    ensurePanel();
    viewId = id;
    tab = startTab;
    draft = null;
    panel.open(); panel.raise();
    render();
  }

  /** 겹치지 않는 자동 이름 - `새 보기`, `새 보기 2`, … (서버는 같은 이름을 409 로 거절한다). */
  function freshName() {
    const taken = new Set(store.views().map(v => String(v.name).toLocaleLowerCase()));
    for (let i = 1; i < 1000; i += 1) {
      const name = i === 1 ? '새 보기' : `새 보기 ${i}`;
      if (!taken.has(name.toLocaleLowerCase())) return name;
    }
    return `새 보기 ${Date.now()}`;
  }

  /** 바로 만들고 [편집] 탭으로 연다. 그룹에서 불렀으면 그 그룹이 곧바로 고른다. */
  async function openNew(groupId = '') {
    try {
      const current = await store.refreshCurrent();
      if (!current) throw new Error('지금 설정을 읽지 못했습니다');
      const spec = {...current, prefix: '', postfix: '', negative: '', characters: [], source_preset: ''};
      delete spec.stripped;
      const created = await store.create(freshName(), spec);
      if (groupId) await store.select(groupId, created.id);
      await open(created.id, {tab: 'edit'});
    } catch (error) {
      showToast(error.message || '보기를 만들지 못했습니다.', 'error');
    }
  }

  // ── 그리기 ────────────────────────────────────────────────────────────
  const view = () => (viewId ? store.get(viewId) : null);

  function seedText(seed) { return Number(seed) < 0 ? '랜덤' : String(seed); }

  function summaryHtml(spec) {
    const s = spec.settings || {};
    const rows = [
      ['백엔드', spec.api_mode],
      ['PE 프리셋', spec.source_preset || '—'],
      ['모델', s.model || '—'],
      ['샘플러', [s.sampler, s.scheduler].filter(Boolean).join(' · ') || '—'],
      ['스텝 · CFG', `${s.steps ?? '—'} · ${s.scale ?? '—'}${s.cfg_rescale ? ` · rescale ${s.cfg_rescale}` : ''}`],
      ['해상도', `${spec.width} x ${spec.height}`],
      ['시드', seedText(spec.seed)],
      ['캐릭터', (spec.characters || []).length ? `${spec.characters.length}명` : '없음'],
    ];
    const text = (label, value) => `
      <div class="abv-text"><span>${label}</span><div>${value ? escHtml(value) : '<i>비어 있음</i>'}</div></div>`;
    return `
      <dl class="abv-facts">${rows.map(([k, v]) => `<dt>${k}</dt><dd>${escHtml(String(v))}</dd>`).join('')}</dl>
      ${text('prefix', spec.prefix)}${text('postfix', spec.postfix)}${text('negative', spec.negative)}
      ${(spec.characters || []).map((c, i) => text(`캐릭터 ${i + 1}`, c.prompt + (c.uc ? `  ⊘ ${c.uc}` : ''))).join('')}`;
  }

  function render() {
    if (!panel) return;
    const v = view();
    if (!v) { panel.close(); return; }
    panel.setTitle(`보기 · ${v.name}`);
    const tabs = `
      <div class="abv-tabs" role="tablist">
        <button type="button" data-abv-tab="summary" class="${tab === 'summary' ? 'is-on' : ''}">요약</button>
        <button type="button" data-abv-tab="edit" class="${tab === 'edit' ? 'is-on' : ''}">편집</button>
      </div>`;
    if (tab === 'summary') {
      panel.body.innerHTML = `${tabs}
        <div class="abv-scroll">${summaryHtml(v)}</div>
        <form class="abv-rename" hidden>
          <input type="text" maxlength="40" spellcheck="false" value="${escHtml(v.name)}">
          <button type="submit" class="abv-btn">확인</button>
          <button type="button" class="abv-btn" data-abv-act="rename-cancel">취소</button>
        </form>
        <div class="abv-actions">
          <button type="button" class="abv-btn primary" data-abv-act="refresh"
                  title="메인 화면의 지금 설정(PE 글 · 캐릭터 · 해상도 · 생성 설정)으로 이 보기를 덮습니다">지금 설정으로 갱신</button>
          <button type="button" class="abv-btn" data-abv-act="rename">이름 바꾸기</button>
          <span class="abv-spacer"></span>
          <button type="button" class="abv-btn danger" data-abv-act="delete">삭제</button>
        </div>`;
      return;
    }
    if (!draft) draft = structuredClone(v);
    panel.body.innerHTML = `${tabs}<div class="abv-scroll">${editorHtml(draft)}</div>
      <div class="abv-actions">
        <button type="button" class="abv-btn primary" data-abv-act="save">저장</button>
        <button type="button" class="abv-btn" data-abv-act="revert">되돌리기</button>
      </div>`;
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
    const area = (field, label, rows = 3) => `
      <label class="abv-field"><span>${label}</span>
        <textarea data-abv-field="${field}" rows="${rows}" spellcheck="false">${escHtml(d[field] || '')}</textarea></label>`;
    const chars = (d.characters || []).map((c, i) => `
      <div class="abv-char" data-abv-char="${i}">
        <div class="abv-char-head"><span>캐릭터 ${i + 1}</span>
          <button type="button" class="abv-x" data-abv-act="char-remove" data-index="${i}" title="이 캐릭터 빼기">×</button></div>
        <textarea data-abv-char-field="prompt" rows="2" spellcheck="false" placeholder="캐릭터 프롬프트">${escHtml(c.prompt)}</textarea>
        <input type="text" data-abv-char-field="uc" spellcheck="false" placeholder="캐릭터 네거티브(선택)" value="${escHtml(c.uc || '')}">
      </div>`).join('');
    const random = Number(d.seed) < 0;
    return `
      <label class="abv-field"><span>이름</span>
        <input type="text" data-abv-field="name" maxlength="40" spellcheck="false" value="${escHtml(d.name || '')}"></label>
      ${area('prefix', 'prefix')}${area('postfix', 'postfix')}${area('negative', 'negative', 2)}
      <div class="abv-group"><div class="abv-group-head"><span>캐릭터 프롬프트</span>
        <button type="button" class="abv-btn" data-abv-act="char-add"${(d.characters || []).length >= MAX_CHARACTERS ? ' disabled' : ''}>+ 캐릭터</button></div>
        ${chars || '<div class="abv-empty small">캐릭터 없음 - 메인 화면의 캐릭터는 섞이지 않습니다.</div>'}</div>
      <div class="abv-grid">
        <label class="abv-field"><span>너비</span><input type="number" step="64" min="64" max="4096" data-abv-field="width" value="${d.width}"></label>
        <label class="abv-field"><span>높이</span><input type="number" step="64" min="64" max="4096" data-abv-field="height" value="${d.height}"></label>
        <label class="abv-field wide"><span>모델</span>${selectHtml('settings.model', s.model, o.model)}</label>
        <label class="abv-field"><span>샘플러</span>${selectHtml('settings.sampler', s.sampler, o.sampler)}</label>
        <label class="abv-field"><span>스케줄러</span>${selectHtml('settings.scheduler', s.scheduler, o.scheduler)}</label>
        <label class="abv-field"><span>스텝</span><input type="number" min="1" max="1000" data-abv-field="settings.steps" value="${s.steps ?? ''}"></label>
        <label class="abv-field"><span>CFG</span><input type="number" step="0.1" min="0" max="100" data-abv-field="settings.scale" value="${s.scale ?? ''}"></label>
        <label class="abv-field"><span>리스케일</span><input type="number" step="0.05" min="0" max="1" data-abv-field="settings.cfg_rescale" value="${s.cfg_rescale ?? ''}"></label>
        <label class="abv-field"><span>시드</span><input type="number" min="0" data-abv-field="seed" value="${random ? '' : d.seed}"${random ? ' disabled' : ''}></label>
        <label class="abv-check"><input type="checkbox" data-abv-field="seed-random"${random ? ' checked' : ''}> 매번 랜덤</label>
      </div>`;
  }

  // ── 편집 작업본 ────────────────────────────────────────────────────────
  function onInput(event) {
    if (!draft) return;
    const el = event.target;
    const field = el.dataset?.abvField;
    const charField = el.dataset?.abvCharField;
    if (charField) {
      const index = Number(el.closest('[data-abv-char]')?.dataset.abvChar);
      if (draft.characters?.[index]) draft.characters[index][charField] = el.value;
      return;
    }
    if (!field) return;
    if (field === 'seed-random') {
      draft.seed = el.checked ? -1 : Math.max(0, Number(panel.body.querySelector('[data-abv-field="seed"]')?.value) || 0);
      if (event.type === 'change') render();
      return;
    }
    if (field.startsWith('settings.')) {
      const key = field.slice(9);
      const numeric = ['steps', 'scale', 'cfg_rescale'].includes(key);
      draft.settings = {...(draft.settings || {}), [key]: numeric ? Number(el.value) : el.value};
      return;
    }
    draft[field] = ['width', 'height', 'seed'].includes(field) ? Number(el.value) : el.value;
  }

  function specFrom(d) {
    return {
      api_mode: d.api_mode, prefix: d.prefix, postfix: d.postfix, negative: d.negative,
      characters: (d.characters || []).filter(c => String(c.prompt || '').trim()),
      source_preset: d.source_preset, width: d.width, height: d.height, settings: d.settings, seed: d.seed,
    };
  }

  // ── 단추 ──────────────────────────────────────────────────────────────
  async function onClick(event) {
    const tabBtn = event.target.closest('[data-abv-tab]');
    if (tabBtn) { tab = tabBtn.dataset.abvTab; if (tab === 'edit') draft = null; render(); return; }
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
          `'${v.name}' 보기를 지금 설정으로 덮습니다. 이미 뽑은 그림은 그대로 남습니다(옛 조건의 그림).`,
          {title: '지금 설정으로 갱신'}) : true);
        if (!ok) return;
        await store.update(v.id, current);
        showToast(`'${v.name}' 을(를) 지금 설정으로 갱신했습니다.`, 'success');
      } else if (act === 'rename') {
        const form = panel.body.querySelector('.abv-rename');
        form.hidden = false;
        form.querySelector('input').select();
        form.onsubmit = async submit => {
          submit.preventDefault();
          const name = form.querySelector('input').value.trim();
          if (!name) return;
          try { await store.rename(v.id, name); } catch (error) { showToast(error.message, 'error'); }
        };
      } else if (act === 'rename-cancel') {
        panel.body.querySelector('.abv-rename').hidden = true;
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
        if (name && name !== v.name) await store.rename(v.id, name);
        await store.update(v.id, specFrom(draft));
        draft = null;
        tab = 'summary';
        render();
        showToast('보기를 저장했습니다.', 'success');
      } else if (act === 'revert') {
        draft = null;
        render();
      } else if (act === 'char-add' && draft) {
        draft.characters = [...(draft.characters || []), {prompt: '', uc: ''}].slice(0, MAX_CHARACTERS);
        render();
      } else if (act === 'char-remove' && draft) {
        draft.characters.splice(Number(event.target.closest('[data-abv-act]').dataset.index), 1);
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
