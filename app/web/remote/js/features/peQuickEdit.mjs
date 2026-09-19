/** Prompt Engineering 빠른 수정 — 믹스 모드 판 아래에 붙는 접이식 칸 둘.
 *
 *  `/pe` 의 prefix·postfix 임시 편집창과 **같은 값의 다른 창**이다(사용자: "부분 미러").
 *  다른 점은 수명뿐 - 슬래시 쪽은 바깥을 누르면 사라지는 일회성이고, 이쪽은 떠 있는
 *  창에 상주하며 접었다 편다. 저장은 **칸을 벗어날 때 자동**(사용자 지정).
 *
 *  ⚠️ 리모컨 머리줄의 [prefix]/[postfix] 가 `openField()` 로 이 칸들을 **탭처럼** 연다 -
 *     한 번에 한 칸만 펴는 이유는 창이 좁아 둘을 펴면 각각이 쓸모없이 낮아지기 때문이다.
 *
 *      ┌ 믹스 모드 ──────────┐
 *      │  … 큐 …             │
 *      └─────────────────────┘
 *      ┌─────────────────────┐
 *      │ ▾ prefix      358자 │  ← 누르면 접힌다
 *      │ [                 ] │
 *      │ ▸ postfix  비어 있음│
 *      └─────────────────────┘
 *
 *  ⚠️ 값을 직접 만들지 않는다. 읽기도 쓰기도 주입받은 `getField`/`setField` 를 거친다 -
 *     쓰기에는 **프리셋 도장**이 필요한데, 그 규칙이 두 곳에 있으면 프리셋 전환과
 *     경합할 때 한쪽이 조용히 엉뚱한 프리셋에 쓴다.
 *
 *  강조와 자동완성도 **만들지 않고 빌린다**(사용자 지정: "메인 프롬프트의 artist 강조를
 *  동일하게"). 색과 분류 색인은 메인 프롬프트를 칠하는 바로 그 모듈이 쥐고 있어,
 *  여기서 흉내 내면 언젠가 두 화면의 색이 갈린다.
 */

/** 글자가 겹쳐 보이려면 오버레이와 칸의 **글자 상자가 같아야** 한다 - 글꼴·크기·줄높이·
 *  안쪽 여백·테두리 두께·줄바꿈 규칙까지. 옷은 `.peq-hl` 이 `.peq-text` 를 그대로 베낀다
 *  (style.css). 하나라도 어긋나면 줄바꿈이 달라져 그 아래가 통째로 밀린다. */
const FIELDS = [
  {key: 'pre_prompt', label: 'prefix', title: 'Prefix Prompt'},
  {key: 'post_prompt', label: 'postfix', title: 'Postfix Prompt'},
];

export function createPeQuickEdit({
  document: doc,
  escHtml = value => String(value ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'),
  getField = () => '',        // (key) => string
  setField = () => {},        // (key, text, seenPreset) => void   ⚠️ 도장은 이 안에서 찍힌다
  getPreset = () => '',       // 지금 프리셋 이름
  requestState = () => {},    // 상태 캐시가 비어 있을 때 한 번 청한다
  showToast = () => {},
  // (textarea, overlay) => Promise<손잡이|null>   메인 프롬프트와 **같은** 강조
  attachHighlight = null,
  // (textarea) => void   메인 프롬프트와 **같은** 자동완성
  bindAssist = null,
} = {}) {
  const el = doc.createElement('div');
  el.className = 'peq';
  el.innerHTML = FIELDS.map(f => `
    <div class="peq-row" data-peq-key="${escHtml(f.key)}">
      <button type="button" class="peq-head" aria-expanded="false" title="${escHtml(f.title)}">
        <span class="peq-caret">▸</span><span class="peq-label">${escHtml(f.label)}</span>
        <span class="peq-len"></span>
      </button>
      <div class="peq-box" hidden>
        <div class="peq-hl" aria-hidden="true"></div>
        <textarea class="peq-text" rows="3" spellcheck="false"
                  aria-label="${escHtml(f.title)}"></textarea>
      </div>
    </div>`).join('');

  const rowFor = key => el.querySelector(`[data-peq-key="${CSS.escape(key)}"]`);
  const readField = key => { try { return String(getField(key) ?? ''); } catch (_) { return ''; } };
  const readPreset = () => { try { return String(getPreset() ?? ''); } catch (_) { return ''; } };
  const isOpen = row => !row.querySelector('.peq-box').hidden;

  /** 칸마다 강조 하나. 비동기로 붙으므로 없을 수도 있다 - 없으면 그냥 평범한 칸이다. */
  const highlights = new Map();   // key -> 강조 손잡이
  const repaint = key => { try { highlights.get(key)?.update(); } catch (_) {} };
  const restate = key => { try { highlights.get(key)?.applyState(); } catch (_) {} };

  /** 접힌 줄에도 '들어 있는지' 는 보여야 한다 - 안 그러면 열어 봐야만 알 수 있다. */
  function paintLen(row, text) {
    const len = String(text || '').trim().length;
    row.querySelector('.peq-len').textContent = len ? `${len}자` : '비어 있음';
    row.classList.toggle('is-empty', !len);
  }

  /** 칸을 서버 값으로 채우고 **그때 무엇을 보고 있었는지**까지 적어 둔다.
   *
   *  ⚠️ 이 `peqPreset` 이 도장이 된다. 저장하는 순간의 프리셋을 찍으면 도장이 무의미해진다 -
   *     A 를 보고 치다가 B 로 바꾼 뒤 칸을 벗어나면 그 글이 B 에 찍혀 들어간다.
   *     서버는 '보고 친 프리셋 ≠ 지금 프리셋' 인 편집을 버리게 되어 있다.
   */
  function fill(row, value = null) {
    const text = row.querySelector('.peq-text');
    const next = value == null ? readField(row.dataset.peqKey) : String(value);
    text.value = next;
    text.dataset.peqSaved = next;
    text.dataset.peqPreset = readPreset();
    paintLen(row, next);
    repaint(row.dataset.peqKey);
    return next;
  }

  /** 저장은 **바뀐 것만**. 안 그러면 칸을 스쳐 지나가기만 해도 도장이 새로 찍혀
   *  프리셋 전환 직후의 값을 옛 글로 되돌린다. */
  function commit(row) {
    const text = row.querySelector('.peq-text');
    if (!isOpen(row)) return false;
    const next = text.value;
    if (next === (text.dataset.peqSaved ?? '')) return false;
    try {
      setField(row.dataset.peqKey, next, text.dataset.peqPreset ?? '');
      text.dataset.peqSaved = next;
      paintLen(row, next);
      return true;
    } catch (error) {
      showToast(`저장 실패 — ${error?.message || error}`, 'error');
      return false;
    }
  }

  function setOpen(row, open) {
    const text = row.querySelector('.peq-text');
    if (open) {
      // 펼치는 순간 최신값을 다시 읽는다 - 접혀 있는 동안 프리셋이 바뀌었을 수 있다.
      if (!fill(row)) requestState();   // 비어 있으면 캐시가 아직 안 찼을 수도 있다
    } else {
      commit(row);
    }
    row.querySelector('.peq-box').hidden = !open;
    row.querySelector('.peq-head').setAttribute('aria-expanded', open ? 'true' : 'false');
    row.querySelector('.peq-caret').textContent = open ? '▾' : '▸';
    if (open) text.focus();
    restate(row.dataset.peqKey);
  }

  el.addEventListener('click', event => {
    const head = event.target.closest('.peq-head');
    if (!head) return;
    const row = head.closest('.peq-row');
    setOpen(row, !isOpen(row));
  });

  // 칸을 벗어나면 저장(사용자 지정). 접기·리모컨 닫기도 같은 문을 쓴다.
  el.addEventListener('focusout', event => {
    const row = event.target.closest?.('.peq-row');
    if (row && !row.contains(event.relatedTarget)) commit(row);
  });

  // 글이 바뀌면 색도 따라간다. 자동완성이 넣은 값도 이 길로 온다 - tagAssist 가
  // 프로그램적 변경 뒤에 진짜 `input` 을 쏘기 때문이다(`fireModuleOninput`).
  el.addEventListener('input', event => {
    const row = event.target.closest?.('.peq-row');
    if (row) repaint(row.dataset.peqKey);
  });
  // 칸이 굴러가면 색도 같이 굴러야 한다.
  el.addEventListener('scroll', event => {
    const row = event.target.closest?.('.peq-row');
    if (row) { try { highlights.get(row.dataset.peqKey)?.syncScroll(); } catch (_) {} }
  }, true);
  // 초점이 들고 날 때 미리보기/편집 상태가 갈린다(메인 프롬프트와 같은 규칙).
  for (const type of ['focusin', 'focusout']) {
    el.addEventListener(type, event => {
      const row = event.target.closest?.('.peq-row');
      if (row) restate(row.dataset.peqKey);
    });
  }

  // ⚠️ 글로벌 단축키는 document 의 **버블** 단계에 붙어 있다 - 전파를 끊지 않으면
  //    Ctrl+Enter 가 여기서도 Generate 를 누른다(슬래시 편집창에서 난 제보와 같은 자리).
  el.addEventListener('keydown', event => {
    const text = event.target.closest?.('.peq-text');
    if (!text) return;
    // ⚠️ 한글 조합 중의 Esc·Enter 는 **조합** 의 것이다(IME 가 먼저 먹는다).
    //    여기서 받으면 글자를 지우려던 손이 편집 전체를 되돌린다.
    if (event.isComposing || event.keyCode === 229) return;
    if (event.key === 'Escape') {
      // ⚠️ 자동완성 팝업이 먼저 먹은 Esc 다(tagAssist 가 칸에 직접 걸어 둔 손이
      //    버블보다 앞선다). 그것까지 되돌리면 후보를 물리려다 **글이 통째로**
      //    옛것으로 돌아가고 칸이 접힌다. 팝업이 막아 둔 키는 팝업의 것이다.
      if (event.defaultPrevented) return;
      event.preventDefault();
      event.stopPropagation();
      text.value = text.dataset.peqSaved ?? '';   // 되돌리고 접는다
      setOpen(text.closest('.peq-row'), false);
      return;
    }
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      event.stopPropagation();
      commit(text.closest('.peq-row'));
    }
  });

  // 강조와 자동완성은 **빌려 온다**. 둘 다 없어도 칸은 그대로 동작한다.
  FIELDS.forEach(f => {
    const row = rowFor(f.key);
    const text = row.querySelector('.peq-text');
    if (typeof bindAssist === 'function') {
      // 청크 다리는 메인 프롬프트의 것이다 - 여기서 열리면 리모컨 뒤로 숨는다.
      try { bindAssist(text, {disableChunkBridge: true}); } catch (_) { /* 없어도 산다 */ }
    }
    if (typeof attachHighlight === 'function') {
      Promise.resolve(attachHighlight(text, row.querySelector('.peq-hl')))
        .then(handle => {
          if (!handle) return;
          highlights.set(f.key, handle);
          handle.applyState();
          handle.update();
        })
        .catch(() => { /* 색이 없을 뿐이다 */ });
    }
  });

  FIELDS.forEach(f => paintLen(rowFor(f.key), readField(f.key)));
  // ⚠️ PE 상태는 그 모듈을 한 번 열어야 캐시에 든다 - 펼칠 때까지 기다리면 접힌 줄이
  //    "비어 있음" 이라고 거짓말을 한다(사용자 제보). 만들자마자 한 번 청해 둔다.
  //    답이 오면 `sync()` 가 줄을 다시 그린다.
  requestState();

  return {
    el,
    /** 머리줄 단추가 부른다 - 그 칸만 펴고 나머지는 접는다(탭). 이미 펴져 있으면
     *  초점만 옮긴다(단추를 두 번 눌렀다고 방금 친 글을 접어 버리면 안 된다). */
    openField(key) {
      const row = rowFor(key);
      if (!row) return false;
      FIELDS.forEach(f => {
        const other = rowFor(f.key);
        if (other !== row && isOpen(other)) setOpen(other, false);
      });
      if (!isOpen(row)) setOpen(row, true);
      else row.querySelector('.peq-text').focus();
      return true;
    },
    /** 지금 펴져 있는 칸(없으면 ''). 머리줄 단추의 눌림 표시가 이걸 읽는다. */
    openKey: () => (FIELDS.find(f => isOpen(rowFor(f.key)))?.key || ''),
    /** 바깥에서 값이 바뀌었을 때(프리셋 전환 등). **치는 중인 칸은 건드리지 않는다** -
     *  사용자가 쓰고 있는 글을 서버 에코가 지우면 그게 제일 나쁜 종류의 버그다.
     *
     *  ⚠️ 지키는 것은 '초점' 이 아니라 **안 저장된 편집**이다. 초점으로 재면 첫 상태가
     *     영영 안 들어온다 - 펼치는 순간 초점이 가고, 상태는 바로 그 펼침이 청해서
     *     **그 다음에** 오기 때문이다(실측: 상태 30키가 와 있는데 칸은 빈 채였다). */
    sync() {
      FIELDS.forEach(f => {
        const row = rowFor(f.key);
        const text = row.querySelector('.peq-text');
        const dirty = !text.hidden && text.value !== (text.dataset.peqSaved ?? '');
        if (dirty) return;
        fill(row);
      });
    },
    /** 판이 내려가기 전에 불린다 - 펼친 채 닫으면 마지막 편집이 날아간다. */
    flush() {
      FIELDS.forEach(f => commit(rowFor(f.key)));
    },
  };
}
