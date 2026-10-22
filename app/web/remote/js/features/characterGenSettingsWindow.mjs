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
} = {}) {
  let options = null;           // 서버 저장본(prefix · postfix · no_save …)
  let quick = null;
  let panel = null;
  let opening = null;
  let warnEl = null;
  let optsEl = null;
  let saveSeq = 0;               // 마지막 저장 요청의 번호 - 겹친 저장의 늦은 응답이 최신 값을 되돌리지 않게(Codex 리뷰)
  let saveChain = Promise.resolve();

  function paintOptions() {
    if (!optsEl) return;
    const o = options || {};
    optsEl.querySelectorAll('[data-cqgen-opt]').forEach(box => { box.checked = !!o[box.dataset.cqgenOpt]; });
    const cos = optsEl.querySelector('[data-cqgen-cos]');
    if (cos && doc.activeElement !== cos) cos.value = String(o.cosplay_name || '');
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
    loading = fetch('/api/character-viewer/state', {cache: 'no-store'})
      .then(res => res.json())
      .then(data => {
        if (data && data.options) options = data.options;
        quick?.sync();
        paintWarn();
        paintOptions();
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
        try { onSaved(data); } catch (_) {}
      })
      .catch(error => showToast(`생성 설정 저장 실패 — ${error.message || error}`, 'error'));
  }

  async function ensure() {
    if (panel) return panel;
    if (opening) return opening;
    opening = (async () => {
      const [createPeQuickEdit, createDraggablePanel] = await Promise.all([loadPeQuickEdit(), loadDraggablePanel()]);
      quick = createPeQuickEdit({
        document: doc, escHtml, showToast, attachHighlight, bindAssist,
        getField: key => String((options || {})[KEYS[key]] ?? ''),
        setField: (key, text) => save(key, text),
        getPreset: () => '',
        requestState: () => { void load(); },
      });
      panel = createDraggablePanel({
        document: doc, window: win,
        variant: 'pewin cqgen',
        title: 'Character 생성 설정',
        storageKey: 'cq-gen-settings',
        width: 320, height: 250, minWidth: 240, maxWidth: 720, minHeight: 120,
        resizable: true,
        escHtml,
        // 펼친 채 닫으면 마지막 편집이 날아간다 - 칸을 벗어난 것과 같이 친다.
        onClose: () => { quick?.flush(); },
      });
      const more = doc.createElement('button');
      more.type = 'button';
      more.className = 'cqgen-more';
      more.textContent = '↗';
      more.title = '나머지 옵션(copyright 자동 추가 · 저장 안 함 …)은 Characters 탭에서';
      more.addEventListener('click', () => { quick?.flush(); openCharacterPage(); });
      panel.slot.appendChild(more);
      panel.body.appendChild(quick.el);
      optsEl = doc.createElement('div');
      optsEl.className = 'cqgen-opts';
      optsEl.innerHTML = OPTION_CHECKS.map(([key, label]) =>
        `<label><input type="checkbox" data-cqgen-opt="${key}"><span>${escHtml(label)}</span></label>`).join('')
        + `<label class="is-cos"><input type="checkbox" data-cqgen-opt="cosplay_enabled"><span>코스프레</span>`
        + `<input type="text" class="cqgen-cos" data-cqgen-cos placeholder="코스프레할 캐릭터 이름" spellcheck="false"></label>`;
      optsEl.addEventListener('change', event => {
        const box = event.target.closest('[data-cqgen-opt]');
        if (box) saveOption(box.dataset.cqgenOpt, !!box.checked);
      });
      // 이름 칸은 벗어날 때 저장(한 글자마다 보내지 않는다).
      optsEl.addEventListener('focusout', event => {
        const input = event.target.closest('[data-cqgen-cos]');
        if (input && input.value !== String((options || {}).cosplay_name || '')) saveOption('cosplay_name', input.value);
      });
      panel.body.appendChild(optsEl);
      warnEl = doc.createElement('div');
      warnEl.className = 'cqgen-warn';
      warnEl.hidden = true;
      panel.body.appendChild(warnEl);
      paintOptions();
      return panel;
    })();
    try { return await opening; } finally { opening = null; }
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
      const p = await ensure();
      if (p.isOpen()) { p.close(); return; }
      await load();
      p.open();
      p.raise?.();
      openBoth();
    },
    isOpen: () => !!(panel && panel.isOpen()),
    /** Characters 탭에서 저장됐다 - 치는 중인 칸은 그대로 두고(판의 `sync` 규칙) 나머지를 맞춘다. */
    sync(next) {
      if (next && typeof next === 'object') options = {...(options || {}), ...next};
      quick?.sync();
      paintWarn();
      paintOptions();
    },
  };
}
