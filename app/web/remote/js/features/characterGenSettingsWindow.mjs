/** 캐릭터 생성 설정 창 - Find 의 ⚙ 가 연다(사용자 지시 2026-10-21: "생성 설정 버튼에 브릿지 · Characters 탭에
 *  들어가지 않고 선행/후행 조작" · 모양 = Prompt Engineering 떠 있는 창처럼 따로 뺀다).
 *
 *      ┌⠿ Character 생성 설정 ───── ↗ ─ × ┐
 *      │ ▾ prefix                   117자 │
 *      │ [masterpiece, best quality, …  ] │
 *      │ ▾ postfix                   24자 │
 *      │ [year 2024, …                  ] │
 *      │ 저장 안 함이 켜져 있어 …(있을 때만) │
 *      └──────────────────────────────────┘
 *
 *  값 = Characters 탭의 Prefix · Postfix 와 **같은 값**(`/api/character-viewer/options` · 모든 캐릭터 공통).
 *  Find [생성] · Characters 탭 생성이 함께 쓴다. 서버의 저장은 넘긴 키만 바꾼다 - 여기서는 그 둘만 보낸다.
 *
 *  ⚠️ 판은 PE 창의 것(`peQuickEdit`)을 그대로 쓴다 - 칸을 벗어날 때 저장 · Esc 저장하고 접기 · 강조 · 자동완성.
 *     프리셋 도장은 없다(`getPreset` = '').
 *  ⚠️ 탭 쪽 칸과 서로 맞춘다: 여기서 저장하면 `onSaved` 로 탭 칸을, 탭에서 저장하면 `sync()` 로 이 창을 고친다.
 *     안 그러면 한쪽에 남은 옛 글이 다음 저장 때 다른 쪽의 새 글을 덮는다.
 */

const KEYS = {pre_prompt: 'prefix', post_prompt: 'postfix'};
// Characters 탭 Detail 의 옵션도 이 창으로(사용자 결정 2026-10-22: 옮기되 Find 와 같은 인프라 - Find ⚙ 도 같은 창).
// 값 = `/api/character-viewer/options` 의 같은 키(넘긴 키만 저장). 탭의 체크와 서로 맞춘다(onSaved / sync).
const OPTION_CHECKS = [
  ['auto_copyright', 'copyright 자동 추가'],
  ['auto_characteristics', 'characteristics 자동 추가'],
  ['hide_charname', '캐릭터명 숨김'],
  ['no_save', '썸네일로 저장 안 함'],
];

export function createCharacterGenSettingsWindow({
  document: doc,
  window: win,
  escHtml,
  showToast = () => {},
  loadPeQuickEdit,              // () => Promise<createPeQuickEdit>
  loadDraggablePanel,           // () => Promise<createDraggablePanel>
  attachHighlight = null,
  bindAssist = null,
  onSaved = () => {},           // (options) => void   서버가 돌려준 저장본 - 탭 칸을 맞춘다
  openCharacterPage = () => {}, // [↗] 나머지 옵션은 Characters 탭에서
  getActions = () => ({}),      // 퀵 패널 손잡이 - generateThumb(group, character, body)(Find [생성] 과 같은 길 · 결과 소식도 같이)
  onMoved = () => {},           // ('window' | 'drawer') 조각이 옮겨 갔다 - 다른 쪽(서랍)은 닫는다
} = {}) {
  let options = null;           // 서버 저장본(prefix · postfix · no_save …)
  let quick = null;
  let panel = null;
  let opening = null;
  let warnEl = null;
  let optsEl = null;
  let saveSeq = 0;               // 마지막 저장 요청의 번호 - 겹친 저장의 늦은 응답이 최신 값을 되돌리지 않게(Codex 리뷰)
  let saveChain = Promise.resolve();

  // ── 가상 캐릭터 슬롯 1개(사용자 결정 2026-10-22) ─────────────────────────────────
  // 메인 캐릭터 슬롯과 따로 논다. 캐릭터 프롬프트 = 고를 때마다 그 캐릭터의 줄로 바뀐다(고칠 수 있지만 다음 고름에 버린다).
  // 추가 프롬프트 = 직접 적는 칸 · 캐릭터를 바꿔도 남는다(서버 옵션 `character_extra`) · 캐릭터 줄 뒤에 붙는다(Find [생성] 도).
  // 위치(POS) 없음. [생성] = prefix + (캐릭터 + 추가) + postfix 한 장 - 그 캐릭터의 썸네일로 저장(막는 옵션이 꺼져 있으면).
  const slot = {group: '', character: '', prompt: '', uc: '', seq: 0, busy: false, loading: null};
  let slotEl = null;
  // 줄을 바꾸는 옵션 - 바뀌면 슬롯 줄을 그 옵션으로 다시 만든다. 안 그러면 코스프레로 만든 B 의 줄이 코스프레를 끈 뒤
  // A 의 썸네일로 저장된다(Codex 리뷰 P1).
  const LINE_OPTIONS = new Set(['auto_copyright', 'auto_characteristics', 'hide_charname', 'cosplay_enabled', 'cosplay_name']);

  function paintSlot() {
    if (!slotEl) return;
    const has = !!slot.character;
    slotEl.querySelector('[data-cqgen-slotname]').innerHTML = has
      ? `<b>${escHtml(slot.character)}</b><span>${escHtml(slot.group)}</span>`
      : '<span class="cqgen-hint">Characters 창이나 Find 에서 캐릭터를 고르면 여기 담깁니다</span>';
    slotEl.querySelector('[data-cqgen-clear]').hidden = !has;
    const prompt = slotEl.querySelector('[data-cqgen-prompt]');
    if (doc.activeElement !== prompt) prompt.value = slot.prompt;

    // 줄을 받는 동안은 고치지도 생성하지도 못한다 - 받은 줄이 친 글을 덮거나, 빈 네거티브로 나가지 않게(Codex 리뷰).
    prompt.readOnly = !!slot.loading;
    const extra = slotEl.querySelector('[data-cqgen-extra]');
    if (doc.activeElement !== extra) extra.value = String((options || {}).character_extra || '');

  }

  /** 고른 캐릭터를 담는다 - 줄은 저장된 옵션(작품명 · 특징 · 코스프레 …)으로 서버가 만든다. */
  function setCharacter(group, character) {
    if (!group || !character) return Promise.resolve(false);
    const mine = ++slot.seq;
    Object.assign(slot, {group, character, prompt: '', uc: ''});
    slot.loading = fillSlot(group, character, mine);
    paintSlot();
    return slot.loading;
  }

  /** 줄 · 네거티브를 받아 채운다. 그사이 다른 캐릭터를 골랐으면 버린다. 성공하면 true. */
  async function fillSlot(group, character, mine) {
    let ok = false;
    try {
      const res = await fetch('/api/character-viewer/detail', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({group, character, variant: ''}),
      });
      const data = await res.json().catch(() => ({}));
      if (mine !== slot.seq) return;                // 그사이 다른 캐릭터를 골랐다
      if (!res.ok) throw new Error(data.error || '캐릭터 줄을 만들지 못했습니다.');
      slot.prompt = String(data.prompt?.character_prompt || '').trim();
      const excluded = data.prompt?.cosplay_excluded_pc;
      slot.uc = Array.isArray(excluded) ? excluded.join(', ') : '';
      ok = !!slot.prompt;
    } catch (error) {
      if (mine === slot.seq) showToast(error.message || String(error), 'error');
    } finally {
      if (mine === slot.seq) { slot.loading = null; paintSlot(); }
    }
    return ok && mine === slot.seq;
  }

  async function generate() {
    if (!slot.character || slot.busy || slot.loading) return;
    if (!slot.prompt.trim()) { showToast('캐릭터 줄이 비어 있습니다 - 캐릭터를 다시 고르세요.', 'info'); return; }
    // 이 순간의 슬롯을 잡아 둔다 - 저장을 기다리는 사이 다른 캐릭터를 골라도 잡은 캐릭터 · 줄로 나간다.
    const target = {group: slot.group, character: slot.character, prompt: slot.prompt, uc: slot.uc, seq: slot.seq};
    slot.busy = true;
    paintSlot();
    try {
      // 방금 고친 prefix · postfix · 추가 프롬프트 · 옵션이 저장된 **뒤에** 보낸다(서버는 저장본으로 만든다 - Codex 리뷰).
      quick?.flush();
      const extra = slotEl?.querySelector('[data-cqgen-extra]');
      if (extra && extra.value !== String((options || {}).character_extra || '')) saveOption('character_extra', extra.value);
      await saveChain.catch(() => {});
      const fn = (getActions() || {}).generateThumb;
      if (typeof fn !== 'function') throw new Error('캐릭터 패널을 아직 불러오지 못했습니다.');
      await fn(target.group, target.character, {character_prompt: target.prompt, character_uc: target.uc});
    } catch (error) {
      showToast(error.message || String(error), 'error');
    } finally {
      slot.busy = false;
      paintSlot();
    }
  }

  function buildSlot() {
    slotEl = doc.createElement('div');
    slotEl.className = 'cqgen-slot';
    // 칸 이름은 늘 보이게(placeholder 만 두면 값이 들어간 뒤 무슨 칸인지 사라진다 - Codex 리뷰).
    slotEl.innerHTML = `<div class="cqgen-slot-top"><span class="cqgen-pill">캐릭터 1</span>`
      + `<span class="cqgen-slotname" data-cqgen-slotname></span>`
      + `<button type="button" class="cqgen-clear" data-cqgen-clear hidden>비우기</button></div>`
      + `<label class="cqgen-lab" for="cqgenPrompt">캐릭터 프롬프트</label>`
      + `<textarea class="cqgen-ta" id="cqgenPrompt" data-cqgen-prompt rows="2" spellcheck="false"></textarea>`
      + `<label class="cqgen-lab" for="cqgenExtra">추가 프롬프트</label>`
      + `<textarea class="cqgen-ta is-extra" id="cqgenExtra" data-cqgen-extra rows="1" spellcheck="false"></textarea>`

      ;
    slotEl.addEventListener('input', event => {
      if (event.target.closest('[data-cqgen-prompt]')) slot.prompt = event.target.value;

    });
    slotEl.addEventListener('focusout', event => {
      const extra = event.target.closest('[data-cqgen-extra]');
      if (extra) commitExtra(extra);
    });
    slotEl.addEventListener('click', event => {
      if (event.target.closest('[data-cqgen-clear]')) {
        Object.assign(slot, {group: '', character: '', prompt: '', uc: '', loading: null});
        slot.seq += 1;
        paintSlot();
      }

    });
    // prefix 와 postfix 사이에 - 나가는 글의 차례 그대로 보인다.
    const post = quick.el.querySelector('[data-peq-key="post_prompt"]');
    if (post) post.before(slotEl); else quick.el.appendChild(slotEl);
    paintSlot();
  }

  function commitExtra(extra) {
    if (extra.value !== String((options || {}).character_extra || '')) saveOption('character_extra', extra.value);
  }

  /** 옮기거나 닫기 전에 친 글을 전부 저장 줄에 올린다 - 옮기는 동안 칸이 초점을 잃어도 focusout 을 믿지 않는다. */
  function flushAll() {
    quick?.flush();
    const extra = slotEl?.querySelector('[data-cqgen-extra]');
    if (extra) commitExtra(extra);
  }

  function paintOptions() {
    if (!optsEl) return;
    const o = options || {};
    optsEl.querySelectorAll('[data-cqgen-opt]').forEach(box => { box.checked = !!o[box.dataset.cqgenOpt]; });
  }
  let loading = null;

  function paintWarn() {
    if (!warnEl) return;
    const o = options || {};
    const why = [o.no_save && '저장 안 함', o.hide_charname && '캐릭터명 숨김', o.cosplay_enabled && '코스프레'].filter(Boolean);
    warnEl.hidden = !why.length;
    warnEl.textContent = why.length ? `${why.join(' · ')} 이(가) 켜져 있어 Find [생성] 그림이 썸네일로 남지 않습니다.` : '';
  }

  function load() {
    if (loading) return loading;
    loading = (async () => {
      // 기다리는 사이 저장이 더 붙었으면 그것까지 기다린다 - 기다린 저장과 잰 번호가 같아야 한다(Codex 재리뷰).
      let sentAt;
      do { sentAt = saveSeq; await saveChain.catch(() => {}); } while (sentAt !== saveSeq);
      const data = await (await fetch('/api/character-viewer/state', {cache: 'no-store'})).json();
      return {sentAt, data};
    })()
      .then(({sentAt, data}) => {
        if (sentAt === saveSeq) {
          if (data && data.options) options = data.options;
          quick?.sync();
        }
        paintWarn();
        paintOptions();
        paintSlot();
      })
      .catch(() => {})
      .finally(() => { loading = null; });
    return loading;
  }

  function save(key, text) {
    const name = KEYS[key];
    if (!name) return;
    saveOption(name, text);
  }

  function saveOption(name, value) {
    options = {...(options || {}), [name]: value};
    paintOptions();
    const mine = ++saveSeq;
    // 차례대로 보낸다 - 겹쳐 보내면 서버의 읽기 -> 쓰기가 서로를 덮을 수 있다(서버에도 잠금이 있다 · 이중 방어).
    saveChain = saveChain.catch(() => {}).then(() => fetch('/api/character-viewer/options', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({[name]: value}),
    }))
      .then(async res => {
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
        if (mine !== saveSeq) return;          // 뒤에 보낸 저장이 있다 - 그 응답이 최신이다
        options = data;
        paintWarn();
        paintOptions();
        // 줄을 바꾸는 옵션이 바뀌었으면 슬롯 줄을 다시 만든다(고친 글은 버린다 - 옵션이 우선).
        if (LINE_OPTIONS.has(name) && slot.character) void setCharacter(slot.group, slot.character);
        else paintSlot();
        try { onSaved(data); } catch (_) {}
      })
      .catch(error => showToast(`생성 설정 저장 실패 — ${error.message || error}`, 'error'));
  }

  let contentEl = null;
  let contentReady = null;
  let moveSeq = 0;               // 조각 이동(떠 있는 창 <-> 서랍) 요청 번호 - 마지막 요청만 끝까지 간다
  let mountSeq = 0;              // 서랍 열기 번호 - 서랍을 닫으면 기다리는 서랍 열기만 무른다
  async function ensureContent() {
    if (contentEl) return contentEl;
    if (contentReady) return contentReady;
    contentReady = (async () => {
      const createPeQuickEdit = await loadPeQuickEdit();
      quick = createPeQuickEdit({
        document: doc, escHtml, showToast, attachHighlight, bindAssist,
        getField: key => String((options || {})[KEYS[key]] ?? ''),
        setField: (key, text) => save(key, text),
        getPreset: () => '',
        requestState: () => { void load(); },
      });
      contentEl = doc.createElement('div');
      contentEl.className = 'cqgen-content';
      contentEl.appendChild(quick.el);
      buildSlot();
      buildOptions();
      return contentEl;
    })();
    try { return await contentReady; } finally { contentReady = null; }
  }

  async function ensure() {
    if (panel) return panel;
    if (opening) return opening;
    opening = (async () => {
      const [createDraggablePanel] = await Promise.all([loadDraggablePanel(), ensureContent()]);
      panel = createDraggablePanel({
        document: doc, window: win,
        variant: 'pewin cqgen',
        title: 'Character 생성 설정',
        storageKey: 'cq-gen-settings',
        width: 340, height: 520, minWidth: 260, maxWidth: 720, minHeight: 200,
        resizable: true,
        escHtml,
        // 펼친 채 닫으면 마지막 편집이 날아간다 - 칸을 벗어난 것과 같이 친다.
        onClose: () => { flushAll(); },
      });
      const more = doc.createElement('button');
      more.type = 'button';
      more.className = 'cqgen-more';
      more.textContent = '↗';
      more.title = '나머지 옵션(copyright 자동 추가 · 저장 안 함 …)은 Characters 탭에서';
      more.addEventListener('click', () => { quick?.flush(); openCharacterPage(); });
      panel.slot.appendChild(more);
      return panel;
    })();
    try { return await opening; } finally { opening = null; }
  }

  function buildOptions() {
    optsEl = doc.createElement('div');
    optsEl.className = 'cqgen-opts';
    optsEl.innerHTML = OPTION_CHECKS.map(([key, label]) =>
      `<label><input type="checkbox" data-cqgen-opt="${key}"><span>${escHtml(label)}</span></label>`).join('');
    optsEl.addEventListener('change', event => {
      const box = event.target.closest('[data-cqgen-opt]');
      if (box) saveOption(box.dataset.cqgenOpt, !!box.checked);
    });
    contentEl.appendChild(optsEl);
    warnEl = doc.createElement('div');
    warnEl.className = 'cqgen-warn';
    warnEl.hidden = true;
    contentEl.appendChild(warnEl);
    const note = doc.createElement('div');
    note.className = 'cqgen-note';
    note.textContent = '이 창의 설정은 Character 윈도우 내부/Find 생성에만 적용됩니다';
    contentEl.appendChild(note);
    paintOptions();
  }

  /** 두 칸을 함께 편다 - 창이 둘을 보여 주는 자리다(PE 창의 '한 칸씩' 탭 규칙은 머리줄 단추용). */
  function openBoth() {
    quick.openField('pre_prompt');
    const post = quick.el.querySelector('[data-peq-key="post_prompt"]');
    if (post && post.querySelector('.peq-box').hidden) post.querySelector('.peq-head').click();
    quick.el.querySelector('[data-peq-key="pre_prompt"] .peq-text')?.focus();
  }

  return {
    async toggle() {
      const mine = ++moveSeq;
      const p = await ensure();
      if (mine !== moveSeq) return;
      if (p.isOpen() && contentEl.parentElement === p.body) { p.close(); return; }
      flushAll();                              // 옮기기 전에 친 글을 저장 줄에 올린다 - load 는 그 저장 뒤에 읽는다
      p.body.appendChild(contentEl);           // 서랍에 가 있었으면 이리로 옮긴다(한 벌)
      try { onMoved('window'); } catch (_) {}
      await load();
      if (mine !== moveSeq || contentEl.parentElement !== p.body) return;
      p.open();
      p.raise?.();
      openBoth();
    },
    /** Characters 창 서랍에 붙인다(사용자 지시 2026-10-22: 창 안의 떠 있는 카드). 떠 있는 창에 있었으면 그 창은 닫는다. */
    async mountInto(container) {
      const mine = ++moveSeq;
      const myMount = ++mountSeq;
      const el = await ensureContent();
      if (mine !== moveSeq || myMount !== mountSeq) return;
      flushAll();
      if (panel && el.parentElement === panel.body) panel.close();
      container.appendChild(el);
      try { onMoved('drawer'); } catch (_) {}
      await load();
      if (mine !== moveSeq || myMount !== mountSeq || el.parentElement !== container) return;
      openBoth();
    },
    /** 서랍을 닫았다 - 아직 기다리는 서랍 열기를 무른다. */
    cancelMount() { mountSeq++; },              // 서랍 열기만 무른다 - 진행 중인 떠 있는 창 열기는 그대로(Codex 재리뷰)
    isOpen: () => !!(panel && panel.isOpen()),
    /** 캐릭터를 골랐다(Characters 창 · Find [생성]) - 창이 닫혀 있어도 담아 둔다. */
    setCharacter: (group, character) => setCharacter(group, character),
    /** Characters 창 [생성] - 그 캐릭터가 아직 안 담겼으면 담고(줄을 기다린다) 가상 슬롯으로 한 장. */
    async generateFor(group, character) {
      const ready = (slot.group !== group || slot.character !== character) ? setCharacter(group, character)
        : (slot.loading || Promise.resolve(true));
      const ok = await ready;
      // 기다리는 사이 다른 캐릭터를 골랐으면 그 캐릭터로 나가지 않는다(Codex 리뷰).
      if (!ok || slot.group !== group || slot.character !== character) return;
      await generate();
    },
    /** Characters 탭에서 저장됐다 - 치는 중인 칸은 그대로 두고(판의 `sync` 규칙) 나머지를 맞춘다. */
    sync(next) {
      const before = options || {};
      if (next && typeof next === 'object') options = {...before, ...next};
      quick?.sync();
      paintWarn();
      paintOptions();
      // Characters 탭에서 줄을 바꾸는 옵션(코스프레 등)을 바꿨으면 슬롯 줄도 다시(창에서 바꾼 때와 같은 규칙).
      const lineChanged = [...LINE_OPTIONS].some(key => next && key in next && next[key] !== before[key]);
      if (lineChanged && slot.character) void setCharacter(slot.group, slot.character);
      else paintSlot();
    },
  };
}
