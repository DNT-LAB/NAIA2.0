// Interactive Mode — 프롬프트를 의미 슬롯(블록)으로 분해해 편집하는 뷰.
//
// 좌측은 "보기": 블록당 1행, 선택한 태그를 칩으로 압축 표시. 클릭이 유일한 인터랙션.
// 우측은 "작업": 검색 / 선택됨 / 사전 탐색. 실제 편집은 전부 여기서 일어난다.
//
// 상태 모델(INTERACTIVE_QUICKFILTER_PLAN.md 참조):
//   블록 배열이 편집 SSOT, 프롬프트 문자열은 렌더 결과다. 블록 -> 문자열은 항상 결정론적이고,
//   문자열 -> 블록 역파싱은 하지 않는다(외부 프롬프트 들여오기는 제공하지 않기로 확정).
//
// 캐릭터 블록은 NAI 캐릭터 슬롯(character_frames)으로 나가므로 메인 프롬프트 문자열에
// 들어가지 않는다. 나머지 블록만 결합된다.
//
// cache-bust marker: 20260723-ia1

// 구도(meta)는 실제 구도 태그와 보조 효과가 섞여 있어(Codex 조사) 두 섹션으로 나눈다.
// '구도'=PRIMARY subgroup 만, '효과'=나머지. 두 슬롯 모두 meta 축이라 프롬프트엔 함께 나간다.
// focus_tags 는 subgroup 채로는 구도에 남고(ass focus 등 초점), 캐릭터 특징 10개만 태그 단위로
// 특징으로 이동(Codex 감사). 그래서 focus_tags 는 구도 PRIMARY 로 유지.
const COMPOSITION_PRIMARY = ['image_composition', 'composition', 'framing', 'focus_tags', 'focus', 'count'];
const SCENE_SLOTS = [
  {id: 'composition', name: '구도', icon: '\u{1F5BC}', axis: 'meta', subgroupInclude: COMPOSITION_PRIMARY},
  {id: 'composition_fx', name: '효과', icon: '✨', axis: 'meta', subgroupExclude: COMPOSITION_PRIMARY},
  {id: 'background', name: '배경', icon: '\u{1F3DE}', axis: 'location'},
  {id: 'etc', name: '사물', icon: '⚙', axis: 'object'},   // Food_Object 전용 — '기타'보다 '사물'이 정확(Codex 조사)
];

// ---------- 구도 3축 콤보 프리셋 (Dev0714 composition_block.py 이식/복원) ----------
// 각 항목 = [긴 라벨(콤보용, 초보자), 짧은 라벨(칩용), 실제 프롬프트 태그]. index 0 = 미설정.
const COMP_AXES = [
  {key: 'x', label: 'X · 수평 시점', items: [
    ['정의하지 않음', '—', ''],
    ['정면', '정면', 'front view'],
    ['강한 정면', '강한 정면', 'front view, 0.5::straight-on ::'],
    ['측면(옆모습)', '측면', 'side view, 0.5::from side ::'],
    ['3/4(반측면)', '3/4', 'three-quarter view'],
    ['후면(등)', '후면', 'rear view, 0.5::from behind ::'],
  ]},
  {key: 'y', label: 'Y · 상하 시점', items: [
    ['정의하지 않음(중앙)', '—', ''],
    ['정확히 위에서 내려다보기(탑다운)', '탑다운', "bird's-eye view, 0.5::from above ::"],
    ['약간 위에서 내려다보기', '하이앵글', 'high-angle view, 0.5::from above ::'],
    ['약간 아래에서 올려다보기', '로우앵글', 'low-angle view, 0.5::from below ::'],
    ['정확히 아래에서 올려다보기(바닥시점)', '바닥시점', "worm's-eye view, 0.5::from below ::"],
  ]},
  {key: 'z', label: 'Z · 거리 / 샷 크기', items: [
    ['정의하지 않음', '—', ''],
    ['초근접(얼굴 위주)', '초근접', 'close-up'],
    ['상반신(가슴~머리)', '상반신', 'upper body'],
    ['반신(허리 위)', '반신', 'half body'],
    ['카우보이 샷(허벅지/무릎 위)', '카우보이', 'cowboy shot'],
    ['전신', '전신', 'full body'],
    ['원거리(배경 많이)', '원거리', 'wide shot'],
  ]},
];
const COMP_SPECIALS = [
  ['뒤집기', 'upside-down'], ['90도', 'sideways'], ['원근감', 'perspective'],
  ['기울임', 'dutch angle'], ['역동감', 'foreshortening'],
];
const COMP_POV = 'pov, first person view';

function newComposition() { return {x: 0, y: 0, z: 0, pov: false, specials: []}; }

// ---------- 캐릭터 캔버스 위치 (NAI V4 char_captions[].centers) ----------
// core/api_service.py 매핑을 따른다: A-E -> x 0.1~0.9, 1-5 -> y 0.1~0.9. 미지정 fallback = 중앙.
const POS_COLS = ['A', 'B', 'C', 'D', 'E'];
const POS_DEFAULT = 'C3';

function posCenters(pos) {
  const raw = String(pos || POS_DEFAULT);
  const cx = POS_COLS.indexOf(raw[0]);
  const cy = Number(raw[1]) - 1;
  const f = i => (i < 0 || Number.isNaN(i) ? 0.5 : 0.1 + i * 0.2);
  return {x: f(cx), y: f(cy)};
}

function posText(pos) {
  const c = posCenters(pos);
  return `x ${c.x.toFixed(1)} · y ${c.y.toFixed(1)}`;
}

/** 축 선택 -> 실제 프롬프트에 나가는 태그들. */
function compTags(comp) {
  if (!comp) return [];
  const out = [];
  if (comp.pov) out.push(COMP_POV);
  COMP_AXES.forEach(ax => {
    const item = ax.items[comp[ax.key] || 0];
    if (item && item[2]) out.push(item[2]);
  });
  (comp.specials || []).forEach(t => out.push(t));
  return out;
}

/** 좌측 블록에 보일 짧은 칩 라벨(표시 전용). */
function compChips(comp) {
  if (!comp) return [];
  const out = [];
  if (comp.pov) out.push('POV');
  COMP_AXES.forEach(ax => {
    const i = comp[ax.key] || 0;
    if (i > 0) out.push(ax.key.toUpperCase() + ' ' + ax.items[i][1]);
  });
  (comp.specials || []).forEach(t => {
    const s = COMP_SPECIALS.find(x => x[1] === t);
    if (s) out.push(s[0]);
  });
  return out;
}

const CHAR_SUBS = [
  {key: '특징', icon: '\u{1F9EC}', axis: 'characteristic'},
  {key: '의상', icon: '\u{1F457}', axis: 'clothing'},
  {key: '액션', icon: '\u{1F3C3}', axis: 'pose_action'},
  {key: '표정', icon: '\u{1F60A}', axis: 'expression'},
  {key: '사물', icon: '⚙', axis: 'object'},   // 캐릭터가 든 무기/소품 등
];

const MAX_CHIPS = 6;
// NAI char_captions 상한. core/generation_request.py NAICharacterData 가 5 초과를 거부하므로
// 슬롯도 5 로 맞춘다(6 을 허용하면 생성 시 조용히 하나가 드롭된다).
const MAX_NAI_CHARACTERS = 5;

export function createInteractivePanel({
  document,
  blocksMount,
  panelMount,
  toggleButton,
  escHtml = value => String(value == null ? '' : value),
  onPromptChange = () => {},
  onActiveChange = () => {},
  queryCorpus = null,          // async ({rating, person, include, exclude, search, limit}) => payload
  corpusStatus = null,         // async () => payload
  autocomplete = null,         // createInteractiveAutocomplete() 인스턴스 (미사용 — 팝업 검색은 자동완성 없음)
  browse = null,               // createInteractiveBrowse() 인스턴스 (선택)
  bindTagAssist = null,        // (textarea, options) => void : 범용 자동완성을 슬롯 입력창에 바인딩
  getAutocompleteTarget = () => null,  // () => 현재 자동완성이 열린 textarea | null
  getMode = () => 'NAI',       // () => 'NAI' | 'WEBUI' | 'COMFYUI' — 캐릭터 성별 주입 분기
  showToast = () => {},
} = {}) {
  if (!blocksMount || !panelMount) {
    return {isActive: () => false, setActive: () => {}, destroy: () => {}};
  }

  let active = false;
  let openId = null;
  let corpusState = null;      // 최근 status 응답
  let queryToken = 0;
  let charSeq = 0;             // 캐릭터 고유 id 카운터(삭제해도 재사용 안 함 → id 충돌/stale panelContext 방지)

  const state = {
    rating: 's',
    person: '1girl_solo',
    chars: [newCharacter(true)],
    slots: {composition: [], composition_fx: [], background: [], etc: []},
    composition: newComposition(),   // 구도 3축 콤보 상태(자유 태그와 별도, 프롬프트에선 합쳐짐)
  };

  function newCharacter(open) {
    // id 는 안정적 고유값(표시 라벨 C1..Cn 은 렌더 시 index 로 계산). gender 기본 female.
    return {
      id: 'c' + (++charSeq),
      name: '',
      open: !!open,
      state: 'active',   // 'active' | 'disabled'
      gender: 'female',  // 'female' | 'male'
      pos: POS_DEFAULT,  // 캔버스 위치(NAI 전용). 'A1'~'E5', 기본 중앙 C3
      fields: {'특징': [], '의상': [], '액션': [], '표정': [], '사물': []},
    };
  }

  // ---------------------------------------------------------------- prompt

  /** 활성 캐릭터 성별 카운트 프리픽스: 1girl / 2girls, 1boy / ... (solo 는 붙이지 않음). */
  function genderCountPrefix() {
    let f = 0, m = 0;
    for (const c of state.chars) {
      if (c.state !== 'active') continue;         // 비활성(OFF)은 세지 않는다
      if (c.gender === 'male') m++; else f++;
    }
    const tokens = [];
    if (f === 1) tokens.push('1girl'); else if (f >= 2) tokens.push(`${f}girls`);
    if (m === 1) tokens.push('1boy'); else if (m >= 2) tokens.push(`${m}boys`);
    return tokens.join(', ');
  }

  /** 블록 -> 메인 프롬프트 문자열. 맨 앞에 성별 카운트 프리픽스(공통). 캐릭터는 별도. */
  function renderPrompt() {
    const parts = [];
    for (const slot of SCENE_SLOTS) {
      // 구도는 3축 콤보 태그를 자유 태그 앞에 붙인다.
      if (slot.id === 'composition') parts.push(...compTags(state.composition));
      parts.push(...(state.slots[slot.id] || []));
    }
    return [genderCountPrefix(), parts.join(', ')].filter(Boolean).join(', ');
  }

  /** 캐릭터 프롬프트. NAI 모드면 특징 앞에 girl/boy 주입(이미 명시적 girl/boy 있으면 생략). */
  function buildCharPrompt(c) {
    const base = CHAR_SUBS.map(s => (c.fields[s.key] || []).join(', '))
      .filter(Boolean).join(', ');
    if (String(getMode() || '').toUpperCase() !== 'NAI') return base;
    const tokens = CHAR_SUBS.flatMap(s => c.fields[s.key] || [])
      .map(t => String(t).trim().toLowerCase());
    if (tokens.includes('girl') || tokens.includes('boy')) return base;  // 재삽입 안 함
    const g = c.gender === 'male' ? 'boy' : 'girl';
    return base ? `${g}, ${base}` : g;
  }

  /** 캐릭터에 실제 태그가 하나라도 있나(성별 주입은 태그로 세지 않는다). */
  function charHasTags(c) {
    return CHAR_SUBS.some(s => (c.fields[s.key] || []).length > 0);
  }

  /** 생성 요청에 실을 캐릭터. 활성 + 태그가 있는 것만, NAI 상한(5)까지.
   *  비어 있는 활성 슬롯까지 보내면 내용 없는 char_caption("girl")이 생기므로 제외한다.
   *  메인 프롬프트의 1girl/1boy 카운트는 별도로 계산되므로 여기서 빠져도 인원수는 유지된다. */
  function generationCharacters() {
    const rows = [];
    for (const c of state.chars) {
      if (c.state !== 'active' || !charHasTags(c)) continue;
      const prompt = buildCharPrompt(c);
      if (!prompt) continue;
      // 캐릭터별 네거티브 UI 는 아직 없어 uc 는 빈 문자열. center 는 NAI V4 전용.
      rows.push({prompt, uc: '', center: posCenters(c.pos)});
      if (rows.length >= MAX_NAI_CHARACTERS) break;
    }
    return rows;
  }

  function emitChange() {
    onPromptChange(renderPrompt(), {
      characters: state.chars.map((c, i) => ({
        id: c.id,
        label: 'C' + (i + 1),
        name: c.name,
        state: c.state,
        enabled: c.state === 'active',
        gender: c.gender || 'female',
        pos: c.pos || POS_DEFAULT,
        prompt: buildCharPrompt(c),
      })),
    });
  }

  // ---------------------------------------------------------------- render

  /** 자연어(문장) 구절인지 — 태그 칩과 시각 구분용. 프롬프트 결과엔 영향 없음(표시 스타일만).
   *  통합 칩: 짧은 건 태그 칩, 3단어 이상 + 긴 건 '문장 칩'으로 렌더한다. */
  function isProseChip(text) {
    const s = String(text || '').trim();
    return s.length >= 18 && s.split(/\s+/).length >= 3;
  }

  function chip(text, cls, title) {
    const titleAttr = title ? ` title="${escHtml(title)}"` : '';
    return `<span class="ia-chip${cls ? ' ' + cls : ''}"${titleAttr}>${escHtml(text)}</span>`;
  }

  function chipRow(tags) {
    if (!tags || !tags.length) return '<span class="ia-chip-empty">비어 있음</span>';
    const shown = tags.slice(0, MAX_CHIPS).map(t =>
      isProseChip(t) ? chip(t, 'is-prose', t) : chip(t));   // 문장 칩은 전체 텍스트를 title 로(호버 확인)
    if (tags.length > MAX_CHIPS) shown.push(chip(`+${tags.length - MAX_CHIPS}`, 'is-more'));
    return shown.join('');
  }

  /** 이 슬롯이 지금 편집(텍스트 입력) 중인가. */
  function isEditing(kind, id, sub) {
    if (!panelContext || panelContext.kind !== kind) return false;
    if (kind === 'scene') return panelContext.slotId === id;
    return panelContext.cid === id && panelContext.sub === sub;
  }

  /** 편집 중이면 텍스트 입력창, 아니면 칩. 슬롯 몸통(chips 자리)만 만든다. */
  function slotBody(editing, tags) {
    if (editing) {
      // 전체 태그를 쉼표 문자열로 직접 편집. 숙련자 직접 입력용.
      return `<textarea class="ia-slot-input" data-slot-input="1" rows="1" spellcheck="false" placeholder="태그 입력 (쉼표로 여러 개)">${escHtml(tags.join(', '))}</textarea>`;
    }
    return `<div class="ia-block-chips">${chipRow(tags)}</div>`;
  }

  function sceneBlockHtml(slot) {
    const tags = state.slots[slot.id] || [];
    const editing = isEditing('scene', slot.id);
    // 구도 블록 미리보기(비편집)엔 3축 콤보 칩을 자유 태그 앞에 함께 보인다.
    const chipTags = slot.id === 'composition' ? [...compChips(state.composition), ...tags] : tags;
    const countN = editing ? tags.length : chipTags.length;
    const body = editing
      ? slotBody(true, tags)
      : `<div class="ia-block-chips">${chipRow(chipTags)}</div>`;
    return `<div class="ia-block${editing ? ' is-open is-editing' : ''}${chipTags.length ? '' : ' is-empty'}" data-slot="${slot.id}">
      <div class="ia-block-label">
        <span class="ia-block-title"><span class="ia-block-icon">${slot.icon}</span><span class="ia-block-name">${slot.name}</span></span>
        <span class="ia-block-axis">${slot.axis}</span>
      </div>
      ${body}
      <div class="ia-block-meta"><span class="ia-block-count">${countN || ''}</span></div>
    </div>`;
  }

  function charBlockHtml() {
    // Position(캔버스 좌표)은 NAI V4 char_captions 전용이라 NAI 모드에서만 노출한다.
    const isNai = String(getMode() || '').toUpperCase() === 'NAI';
    const rows = state.chars.map((c, i) => {
      const summary = CHAR_SUBS.flatMap(s => c.fields[s.key] || []).join(', ') || '(비어 있음)';
      const subs = CHAR_SUBS.map(s => {
        const tags = c.fields[s.key] || [];
        const editing = isEditing('char', c.id, s.key);
        return `<div class="ia-sub-block${editing ? ' is-editing' : ''}${tags.length ? '' : ' is-empty'}" data-cid="${c.id}" data-sub="${s.key}">
          <div class="ia-block-label">
            <span class="ia-block-title"><span class="ia-block-icon">${s.icon}</span><span class="ia-block-name">${s.key}</span></span>
            <span class="ia-block-axis">${s.axis}</span>
          </div>
          ${slotBody(editing, tags)}
          <div class="ia-block-meta"><span class="ia-block-count">${tags.length || ''}</span></div>
        </div>`;
      }).join('');
      const enabled = c.state === 'active';
      const label = 'C' + (i + 1);
      const g = c.gender === 'male' ? 'male' : 'female';
      const canDelete = state.chars.length > 1;
      const cid = escHtml(c.id);
      return `<div class="ia-char${c.open ? ' is-open' : ''}${enabled ? '' : ' is-disabled'}" data-char="${i}" data-cid="${cid}">
        <div class="ia-char-head">
          <span class="ia-char-caret">&#9654;</span>
          <span class="ia-char-id">${escHtml(label)}</span>
          <div class="ia-char-gender" role="group" aria-label="성별">
            <button type="button" class="ia-genbtn${g === 'male' ? ' on' : ''}" data-gender="male" data-cid="${cid}">Male</button>
            <button type="button" class="ia-genbtn${g === 'female' ? ' on' : ''}" data-gender="female" data-cid="${cid}">Female</button>
          </div>
          ${isNai ? `<button type="button" class="ia-char-pos" data-charpos data-cid="${cid}" title="캔버스 위치 (NAI V4 centers)">Position ${escHtml(c.pos || POS_DEFAULT)}</button>` : ''}
          ${canDelete ? `<button type="button" class="ia-char-del" data-chardel data-cid="${cid}" aria-label="캐릭터 삭제" title="이 캐릭터 슬롯 삭제">&times;</button>` : ''}
          <span class="ia-char-spring"></span>
          <button type="button" class="ia-char-state ${c.state}" data-charenable data-cid="${cid}" aria-pressed="${enabled}" title="${enabled ? '비활성화 (생성에서 제외)' : '활성화'}">${enabled ? 'ACTIVE' : 'OFF'}</button>
          <span class="ia-char-sum">${escHtml(summary)}</span>
        </div>
        <div class="ia-char-body">${subs}</div>
      </div>`;
    }).join('');

    const activeCount = state.chars.filter(c => c.state === 'active').length;
    return `<div class="ia-block is-character" data-slot="character">
      <div class="ia-cblock-head">
        <span class="ia-block-icon">\u{1F464}</span>
        <span class="ia-block-name">캐릭터</span>
        <span style="flex:1"></span>
        ${isNai ? '<button type="button" class="ia-char-ref" data-charref title="레퍼런스 이미지 (준비 중) — NAI 는 캐릭터별이 아니라 세트 단위로 받는다">Reference</button>' : ''}
        <span class="ia-block-count">${activeCount} 활성</span>
      </div>
      ${rows}
      <div class="ia-char-foot"><button type="button" class="ia-charcard-add" data-add-char="1">+ 캐릭터 슬롯</button></div>
    </div>`;
  }

  function renderBlocks() {
    blocksMount.innerHTML = charBlockHtml() + SCENE_SLOTS.map(sceneBlockHtml).join('');

    blocksMount.querySelectorAll('.ia-block:not(.is-character)').forEach(el => {
      el.addEventListener('click', event => {
        if (event.target.closest('.ia-slot-input')) return;              // 입력창 클릭은 편집 유지
        if (isEditing('scene', el.dataset.slot)) { focusEditingInput(); return; }
        openSlot(el.dataset.slot);
      });
    });
    blocksMount.querySelectorAll('.ia-char-head').forEach(el => {
      el.addEventListener('click', event => {
        event.stopPropagation();
        toggleChar(Number(el.parentElement.dataset.char));
      });
    });
    blocksMount.querySelectorAll('.ia-sub-block').forEach(el => {
      el.addEventListener('click', event => {
        event.stopPropagation();
        if (event.target.closest('.ia-slot-input')) return;
        if (isEditing('char', el.dataset.cid, el.dataset.sub)) { focusEditingInput(); return; }
        openCharSub(el.dataset.cid, el.dataset.sub);
      });
    });
    blocksMount.querySelectorAll('.ia-slot-input').forEach(bindSlotInput);
    // 캐릭터 헤더 버튼들 — 헤더 클릭(펼치기/접기)로 전파되지 않게 stopPropagation.
    blocksMount.querySelectorAll('[data-gender]').forEach(el => {
      el.addEventListener('click', event => {
        event.stopPropagation();
        setCharGender(el.dataset.cid, el.dataset.gender);
      });
    });
    blocksMount.querySelectorAll('[data-charref]').forEach(el => {
      el.addEventListener('click', event => {
        event.stopPropagation();
        onCharReference();
      });
    });
    blocksMount.querySelectorAll('[data-charpos]').forEach(el => {
      el.addEventListener('click', event => {
        event.stopPropagation();
        openPositionPicker(el, el.dataset.cid);
      });
    });
    blocksMount.querySelectorAll('[data-chardel]').forEach(el => {
      el.addEventListener('click', event => {
        event.stopPropagation();
        deleteCharacter(el.dataset.cid);
      });
    });
    blocksMount.querySelectorAll('[data-charenable]').forEach(el => {
      el.addEventListener('click', event => {
        event.stopPropagation();
        toggleCharEnabled(el.dataset.cid);
      });
    });
    const addBtn = blocksMount.querySelector('[data-add-char]');
    if (addBtn) {
      addBtn.addEventListener('click', event => {
        event.stopPropagation();
        addCharacter();
      });
    }
  }

  // ---------------------------------------------------------------- actions

  function toggleChar(index) {
    const willOpen = !state.chars[index].open;
    state.chars.forEach((c, i) => { c.open = (i === index) && willOpen; });
    renderBlocks();
  }

  function addCharacter() {
    if (state.chars.length >= MAX_NAI_CHARACTERS) {
      showToast(`캐릭터 슬롯은 최대 ${MAX_NAI_CHARACTERS}개입니다 (NAI 제한).`, 'error');
      return;
    }
    const next = newCharacter(true);
    state.chars.forEach(c => { c.open = false; });
    state.chars.push(next);
    renderBlocks();
    emitChange();
  }

  /** 성별 세그먼트 토글(female/male). 카드 하나만 in-place 갱신 — 편집 중 슬롯을 안 건드린다. */
  function setCharGender(cid, gender) {
    const c = state.chars.find(x => x.id === cid);
    const next = gender === 'male' ? 'male' : 'female';
    if (!c || c.gender === next) return;
    c.gender = next;
    const card = blocksMount.querySelector(`.ia-char[data-cid="${cid}"]`);
    if (card) {
      card.querySelectorAll('[data-gender]').forEach(b => b.classList.toggle('on', b.dataset.gender === next));
    } else {
      renderBlocks();
    }
    emitChange();
  }

  /** Reference — 목업 버튼(추후 레퍼런스 이미지 연결). NAI 는 캐릭터별이 아니라 세트 단위라
   *  캐릭터 블록 헤더에 하나만 둔다. */
  function onCharReference() {
    showToast('Reference 기능은 준비 중입니다.');
  }

  // ---- 캔버스 위치(Position) 팝업 — 5x5 그리드 ----

  let posPopup = null;      // 지연 생성 후 재사용
  let posPopupCid = null;

  function ensurePosPopup() {
    if (posPopup) return posPopup;
    posPopup = document.createElement('div');
    posPopup.className = 'ia-pos-popup';
    posPopup.hidden = true;
    document.body.appendChild(posPopup);
    // 팝업 내부 mousedown 기본동작을 막아 헤더 클릭(펼치기)이나 포커스 이동을 유발하지 않는다.
    posPopup.addEventListener('mousedown', event => event.preventDefault());
    posPopup.addEventListener('click', event => {
      const cell = event.target.closest('[data-pos]');
      if (!cell) return;
      event.stopPropagation();
      setCharPosition(posPopupCid, cell.dataset.pos);
    });
    return posPopup;
  }

  function posPopupHtml(cur) {
    let cells = '<div class="ia-pos-hdr"></div>' +
      POS_COLS.map(col => `<div class="ia-pos-hdr">${col}</div>`).join('');
    for (let row = 1; row <= 5; row++) {
      cells += `<div class="ia-pos-hdr">${row}</div>`;
      cells += POS_COLS.map(col => {
        const p = col + row;
        return `<button type="button" class="ia-pos-cell${p === cur ? ' is-on' : ''}" data-pos="${p}">${p}</button>`;
      }).join('');
    }
    return `<div class="ia-pos-head">캔버스 위치 · NAI V4</div>
      <div class="ia-pos-wrap">
        <div class="ia-pos-grid">${cells}</div>
        <div class="ia-pos-info">
          <div class="ia-pos-cur">${escHtml(cur)}</div>
          <div class="ia-pos-map">centers<br>${escHtml(posText(cur))}</div>
          <button type="button" class="ia-pos-reset" data-pos="${POS_DEFAULT}">중앙으로</button>
        </div>
      </div>`;
  }

  function openPositionPicker(anchor, cid) {
    const character = state.chars.find(x => x.id === cid);
    if (!character) return;
    if (posPopupCid === cid && posPopup && !posPopup.hidden) { closePositionPicker(); return; }
    const popup = ensurePosPopup();
    posPopupCid = cid;
    popup.innerHTML = posPopupHtml(character.pos || POS_DEFAULT);
    popup.hidden = false;
    // 버튼 아래에 앵커. 화면 밖으로 넘치면 안쪽으로 clamp(위로 뒤집기 포함).
    const rect = anchor.getBoundingClientRect();
    const pr = popup.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    let left = Math.max(8, Math.min(rect.left, vw - pr.width - 8));
    let top = rect.bottom + 6;
    if (top + pr.height > vh - 8) top = Math.max(8, rect.top - pr.height - 6);
    popup.style.left = `${Math.round(left)}px`;
    popup.style.top = `${Math.round(top)}px`;
    document.addEventListener('mousedown', onPosOutside, true);
    document.addEventListener('keydown', onPosKeydown, true);
  }

  function closePositionPicker() {
    posPopupCid = null;
    if (posPopup) { posPopup.hidden = true; posPopup.innerHTML = ''; }
    document.removeEventListener('mousedown', onPosOutside, true);
    document.removeEventListener('keydown', onPosKeydown, true);
  }

  function onPosOutside(event) {
    if (posPopup && posPopup.contains(event.target)) return;
    if (event.target.closest?.('[data-charpos]')) return;   // 토글은 버튼 핸들러가 처리
    closePositionPicker();
  }

  function onPosKeydown(event) {
    if (event.key === 'Escape') { event.preventDefault(); closePositionPicker(); }
  }

  /** 위치 선택 → 버튼 라벨만 in-place 갱신(편집 중 슬롯을 건드리지 않는다). */
  function setCharPosition(cid, pos) {
    const character = state.chars.find(x => x.id === cid);
    if (!character) return;
    const next = /^[A-E][1-5]$/.test(String(pos || '')) ? String(pos) : POS_DEFAULT;
    character.pos = next;
    const btn = blocksMount.querySelector(`.ia-char[data-cid="${cid}"] [data-charpos]`);
    if (btn) btn.textContent = `Position ${next}`;
    if (posPopup && !posPopup.hidden) posPopup.innerHTML = posPopupHtml(next);
    emitChange();
  }

  /** 마지막 하나가 아니면 캐릭터 슬롯 삭제. */
  function deleteCharacter(cid) {
    if (state.chars.length <= 1) {
      showToast('마지막 캐릭터 슬롯은 삭제할 수 없습니다.', 'error');
      return;
    }
    const idx = state.chars.findIndex(c => c.id === cid);
    if (idx < 0) return;
    state.chars.splice(idx, 1);
    // 편집 팝업을 닫고(참조 슬롯이 사라졌을 수 있음) 목록을 다시 그린다(라벨 C1..Cn 재계산).
    closePanel();
    emitChange();
  }

  /** ACTIVE <-> OFF. 카드 하나만 in-place 갱신 — 편집 중 슬롯을 안 건드린다. */
  function toggleCharEnabled(cid) {
    const c = state.chars.find(x => x.id === cid);
    if (!c) return;
    c.state = c.state === 'active' ? 'disabled' : 'active';
    const enabled = c.state === 'active';
    const card = blocksMount.querySelector(`.ia-char[data-cid="${cid}"]`);
    if (card) {
      card.classList.toggle('is-disabled', !enabled);
      const btn = card.querySelector('[data-charenable]');
      if (btn) {
        btn.className = `ia-char-state ${c.state}`;
        btn.setAttribute('aria-pressed', enabled ? 'true' : 'false');
        btn.textContent = enabled ? 'ACTIVE' : 'OFF';
        btn.title = enabled ? '비활성화 (생성에서 제외)' : '활성화';
      }
    } else {
      renderBlocks();
    }
    const activeCount = state.chars.filter(x => x.state === 'active').length;
    const badge = blocksMount.querySelector('.ia-cblock-head .ia-block-count');
    if (badge) badge.textContent = `${activeCount} 활성`;
    emitChange();
  }

  // ---------------------------------------------------------------- panel

  let panelContext = null;   // {kind:'scene', slotId} | {kind:'char', cid, sub}

  function currentTags() {
    if (!panelContext) return [];
    if (panelContext.kind === 'scene') return state.slots[panelContext.slotId] || [];
    const c = state.chars.find(x => x.id === panelContext.cid);
    return (c && c.fields[panelContext.sub]) || [];
  }

  function setCurrentTags(tags, opts = {}) {
    if (!panelContext) return;
    if (panelContext.kind === 'scene') {
      state.slots[panelContext.slotId] = tags;
    } else {
      const c = state.chars.find(x => x.id === panelContext.cid);
      if (c) c.fields[panelContext.sub] = tags;
    }
    // 편집 슬롯은 textarea 가 진실의 원천이다. 브라우저/자동완성 픽(fromInput 아님)은
    // textarea 값을 갱신하지만, 사용자가 직접 타이핑한 경우(fromInput)는 건드리지 않는다
    // — 커서/IME 조합이 끊기기 때문이다.
    if (!opts.fromInput) syncEditingInput();
    updateEditingMeta();
    if (browse) browse.refreshDupes();   // 브라우저의 '있음' 표시 갱신(재요청 없음)
    emitChange();
  }

  /** 지금 편집 중인 슬롯의 DOM 노드. */
  function editingEl() {
    if (!panelContext) return null;
    if (panelContext.kind === 'scene') {
      return blocksMount.querySelector(`.ia-block[data-slot="${panelContext.slotId}"]`);
    }
    return blocksMount.querySelector(
      `.ia-sub-block[data-cid="${panelContext.cid}"][data-sub="${panelContext.sub}"]`
    );
  }

  /** 픽 결과를 편집 중 textarea 에 반영(직접 타이핑 중이면 호출하지 않는다). */
  function syncEditingInput() {
    const el = editingEl();
    const ta = el && el.querySelector('.ia-slot-input');
    if (!ta) return;
    const v = currentTags().join(', ');
    if (ta.value !== v) { ta.value = v; autoGrow(ta); }
  }

  /** 카운트/비어있음/캐릭터 요약만 갱신 — textarea 는 건드리지 않는다. */
  function updateEditingMeta() {
    const el = editingEl();
    if (!el) return;
    const tags = currentTags();
    const count = el.querySelector('.ia-block-count');
    if (count) count.textContent = tags.length || '';
    el.classList.toggle('is-empty', !tags.length);
    if (panelContext.kind === 'char') {
      const character = state.chars.find(x => x.id === panelContext.cid);
      const summary = el.closest('.ia-char')?.querySelector('.ia-char-sum');
      if (summary && character) {
        summary.textContent =
          CHAR_SUBS.flatMap(s => character.fields[s.key] || []).join(', ') || '(비어 있음)';
      }
    }
  }

  /** 변경된 블록 하나만 갱신. 구조가 바뀌지 않았을 때만 쓴다. */
  function updateBlockView(context) {
    if (!context) return;
    if (context.kind === 'scene') {
      const el = blocksMount.querySelector(`.ia-block[data-slot="${context.slotId}"]`);
      if (!el) { renderBlocks(); return; }
      applyChipView(el, state.slots[context.slotId] || []);
      return;
    }
    const character = state.chars.find(x => x.id === context.cid);
    const sub = blocksMount.querySelector(
      `.ia-sub-block[data-cid="${context.cid}"][data-sub="${context.sub}"]`
    );
    if (!character || !sub) { renderBlocks(); return; }
    applyChipView(sub, character.fields[context.sub] || []);
    // 접었을 때 보이는 요약 줄도 같은 캐릭터 안에서만 갱신한다.
    const summary = sub.closest('.ia-char')?.querySelector('.ia-char-sum');
    if (summary) {
      summary.textContent =
        CHAR_SUBS.flatMap(s => character.fields[s.key] || []).join(', ') || '(비어 있음)';
    }
  }

  function applyChipView(el, tags) {
    const chips = el.querySelector('.ia-block-chips');
    const count = el.querySelector('.ia-block-count');
    if (chips) chips.innerHTML = chipRow(tags);
    if (count) count.textContent = tags.length || '';
    el.classList.toggle('is-empty', !tags.length);
  }

  function openSlot(slotId) {
    const slot = SCENE_SLOTS.find(s => s.id === slotId);
    if (!slot) return;
    panelContext = {
      kind: 'scene', slotId, title: slot.name, axis: slot.axis,
      subgroupInclude: slot.subgroupInclude || null,
      subgroupExclude: slot.subgroupExclude || null,
    };
    enterEditing();
  }

  function openCharSub(cid, sub) {
    const meta = CHAR_SUBS.find(s => s.key === sub);
    if (!meta) return;
    panelContext = {kind: 'char', cid, sub, title: `${cid} · ${sub}`, axis: meta.axis};
    enterEditing();
  }

  /** 슬롯을 텍스트 입력으로 펼치고, 그 옆에 검색+탐색 팝업을 띄운다. */
  function enterEditing() {
    openId = panelContext.kind === 'scene' ? panelContext.slotId : 'character';
    renderBlocks();            // 편집 슬롯만 textarea 로, 나머지는 칩으로
    renderPanel();             // 검색창 + 분류 탐색
    panelMount.classList.add('open');
    focusEditingInput();       // 슬롯 textarea 포커스(끝으로)
    positionPopup();           // 편집 슬롯 옆에 앵커
  }

  function closePanel() {
    if (autocomplete) autocomplete.unbind();
    if (browse) browse.detach();
    openId = null;
    panelContext = null;
    panelMount.classList.remove('open');
    panelMount.innerHTML = '';
    panelMount.style.top = panelMount.style.left = panelMount.style.width = '';
    renderBlocks();            // 편집 중이던 슬롯을 칩으로 되돌린다
  }

  // ---- 슬롯 인라인 텍스트 편집 ----

  /** 쉼표/줄바꿈으로 나누고 대소문자 무시로 중복 제거(순서 보존). */
  function parseSlotInput(value) {
    const out = [];
    const seen = new Set();
    for (const part of String(value || '').split(/[,\n]/)) {
      const t = part.trim();
      if (t && !seen.has(t.toLowerCase())) { seen.add(t.toLowerCase()); out.push(t); }
    }
    return out;
  }

  function autoGrow(ta) {
    // 편집 중에는 최소 3줄(58px)을 확보하고, 내용이 늘면 160px 까지 커진다.
    ta.style.height = 'auto';
    ta.style.height = Math.min(Math.max(ta.scrollHeight, 58), 160) + 'px';
  }

  function focusEditingInput() {
    const el = editingEl();
    const ta = el && el.querySelector('.ia-slot-input');
    if (!ta) return null;
    autoGrow(ta);
    ta.focus();
    const n = ta.value.length;
    try { ta.setSelectionRange(n, n); } catch (_) {}
    return ta;
  }

  function bindSlotInput(ta) {
    ta.addEventListener('input', () => {
      autoGrow(ta);
      // 직접 타이핑 → 상태만 갱신, textarea 는 그대로(커서/IME 유지)
      setCurrentTags(parseSlotInput(ta.value), {fromInput: true});
    });
    ta.addEventListener('keydown', event => {
      // 자동완성 드롭다운이 열려 있으면 Enter/Escape 는 tagAssist(확정/닫기)에 양보한다.
      const acOpen = getAutocompleteTarget && getAutocompleteTarget() === ta;
      if (event.key === 'Escape') {
        if (acOpen) return;
        event.preventDefault(); closePanel(); return;
      }
      if (event.key === 'Enter' && !event.shiftKey) {
        if (acOpen) return;
        event.preventDefault(); closePanel();
      }
    });
    ta.addEventListener('blur', () => {
      const ctx = panelContext;
      // 팝업(검색/탐색)이나 다른 슬롯으로 포커스가 옮겨간 경우는 닫지 않는다.
      setTimeout(() => {
        if (panelContext !== ctx) return;                 // 슬롯 전환됨 — 새 편집이 관리
        const a = document.activeElement;
        if (a && (panelMount.contains(a) || a.classList?.contains('ia-slot-input'))) return;
        // 자동완성 드롭다운(외부 #tagTooltip)과 상호작용 중이면 닫지 않는다.
        if (getAutocompleteTarget && getAutocompleteTarget() === ta) return;
        closePanel();
      }, 130);
    });
    // 범용 자동완성(토큰 인식 + IME)을 슬롯 입력창에 붙인다. 커밋 시 tagAssist 가
    // 버블 input 이벤트를 쏘므로 위의 input 핸들러가 상태를 동기화한다.
    // ※ 내 keydown 리스너를 먼저 등록한 뒤 바인딩해야 acOpen 양보 순서가 맞다.
    if (typeof bindTagAssist === 'function') {
      try { bindTagAssist(ta, {}); } catch (_) {}
    }
  }

  /** 팝업을 편집 슬롯 오른쪽(공간 없으면 화면 안으로 clamp)에 앵커한다. */
  function positionPopup() {
    const el = editingEl();
    if (!el) return;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    if (vw <= 767) {
      // 모바일: 하단 시트(CSS 미디어쿼리)에 맡긴다. 인라인 앵커 좌표를 비운다.
      panelMount.style.top = panelMount.style.left = panelMount.style.width = panelMount.style.bottom = '';
      return;
    }
    const W = Math.min(560, vw - 32);
    const host = blocksMount.getBoundingClientRect();
    const rect = el.getBoundingClientRect();
    let left = host.right + 12;
    if (left + W > vw - 12) left = Math.max(12, vw - 12 - W);
    panelMount.style.width = W + 'px';
    panelMount.style.left = left + 'px';
    panelMount.style.top = Math.max(12, rect.top) + 'px';
    panelMount.style.bottom = 'auto';
    // 실제 높이 측정 후 아래로 넘치면 위로 당긴다.
    requestAnimationFrame(() => {
      if (!panelContext) return;
      const ph = panelMount.getBoundingClientRect().height;
      let top = Math.max(12, rect.top);
      if (top + ph > vh - 12) top = Math.max(12, vh - 12 - ph);
      panelMount.style.top = top + 'px';
    });
  }

  let recommendations = [];
  let recommendationNote = '';

  function selectedHtml() {
    const tags = currentTags();
    return tags.length
      ? tags.map(t => `<span class="ia-tag">${escHtml(t)}<button type="button" class="ia-tag-x" data-remove="${escHtml(t)}">&times;</button></span>`).join('')
      : '<span class="ia-chip-empty">아직 선택된 태그가 없습니다</span>';
  }

  function recommendationsHtml() {
    return recommendations.length
      ? recommendations.map(row =>
          `<button type="button" class="ia-grid-tag" data-add="${escHtml(row.tag)}">${escHtml(row.tag)}<span class="ia-grid-kr">${row.count || ''}</span></button>`
        ).join('')
      : `<span class="ia-chip-empty">${escHtml(recommendationNote || '추천 태그가 없습니다')}</span>`;
  }

  /** 선택됨 영역만 교체. 입력창은 건드리지 않아 포커스/IME 조합이 유지된다. */
  function updateSelectedView() {
    const host = panelMount.querySelector('.ia-selected');
    if (!host) { renderPanel(); return; }
    host.innerHTML = selectedHtml();
    bindSelectedHandlers(host);
  }

  /** 추천 영역만 교체. */
  function updateRecommendationsView() {
    const host = panelMount.querySelector('.ia-grid');
    if (!host) { renderPanel(); return; }
    host.innerHTML = recommendationsHtml();
    bindRecommendationHandlers(host);
  }

  function bindSelectedHandlers(host) {
    host.querySelectorAll('[data-remove]').forEach(el => {
      el.addEventListener('click', () => {
        setCurrentTags(currentTags().filter(t => t !== el.dataset.remove));
      });
    });
  }

  function bindRecommendationHandlers(host) {
    host.querySelectorAll('[data-add]').forEach(el => {
      el.addEventListener('click', () => addTags([el.dataset.add]));
    });
  }

  function renderPanel() {
    // 이전 input 의 리스너를 떼어낸다. innerHTML 교체로 노드는 사라지지만, 모듈이 잡고 있는
    // IME 타이머와 팝업 상태는 명시적으로 정리해야 한다.
    if (autocomplete) autocomplete.unbind();
    if (browse) browse.detach();
    if (!panelContext) { panelMount.innerHTML = ''; return; }

    // 슬롯 자체가 텍스트 입력창이 되었으므로 팝업에는 '선택됨'을 두지 않는다.
    // 팝업 = 검색창(상단 통합) + 분류 탐색. 검색은 태그를 '찾아서 넣는' 보조 도구다.
    panelMount.innerHTML = `
      <div class="ia-panel-head">
        <span class="ia-panel-title">${escHtml(panelContext.title)}</span>
        <span class="ia-panel-sub">${escHtml(panelContext.axis)}</span>
        <button type="button" class="ia-panel-close" data-close="1">&times;</button>
      </div>
      <div class="ia-search ia-search-top">
        <input type="text" id="iaTagInput" placeholder="분류·태그 검색 (아래 목록 필터)" autocomplete="off">
        <span class="ia-search-scope">${escHtml(panelContext.axis)}</span>
      </div>
      <div class="ia-panel-body">
        ${panelContext.slotId === 'composition' ? compPanelHtml() : ''}
        <div class="ia-browse-mount" id="iaBrowseMount"></div>
      </div>`;

    panelMount.querySelector('[data-close]')?.addEventListener('click', closePanel);
    if (panelContext.slotId === 'composition') bindCompPanel();
    // 계층 브라우저를 이 슬롯 축으로 마운트한다. 없으면 섹션은 비어 있다.
    if (browse) {
      const browseMount = panelMount.querySelector('#iaBrowseMount');
      if (browseMount) {
        browse.attach(browseMount, {
          axis: panelContext.axis,
          // 섹션 스코프(구도 vs 효과) — Depth1 subgroup 목록을 필터한다.
          subgroupInclude: panelContext.subgroupInclude,
          subgroupExclude: panelContext.subgroupExclude,
          // 브라우저 항목 클릭은 토글이다 — 이미 슬롯에 있으면(✓ 표시) 제거, 없으면 추가.
          // 탐색기 안에서 넣은 걸 탐색기 안에서 뺄 수 있어야 한다.
          onPick: tag => toggleTag(tag),
          getExisting: () => currentTags(),
        });
      }
    }
    const input = panelMount.querySelector('#iaTagInput');
    if (input) {
      // 팝업 검색창은 자동완성이 아니라 아래 '분류 탐색' 목록을 걸러내는 필터다.
      // (태그 입력용 자동완성은 슬롯 입력창 쪽에 붙어 있다.)
      const applyFilter = () => { if (browse) browse.setFilter(input.value); };
      input.addEventListener('input', applyFilter);
      input.addEventListener('keydown', event => {
        if (event.key === 'Escape') { event.preventDefault(); input.value = ''; applyFilter(); }
      });
    }
  }

  // ---- 구도 3축 콤보 프리셋 패널 (Dev0714 복원) ----

  function compPanelHtml() {
    const comp = state.composition;
    const selects = COMP_AXES.map(ax =>
      `<div class="ia-comp-row">
        <span class="ia-comp-lbl">${ax.label}</span>
        <select class="ia-comp-select" data-axis="${ax.key}">
          ${ax.items.map((it, i) =>
            `<option value="${i}"${i === (comp[ax.key] || 0) ? ' selected' : ''}>${escHtml(it[0])}</option>`).join('')}
        </select>
      </div>`).join('');
    const specials = COMP_SPECIALS.map(([label, tag]) =>
      `<button type="button" class="ia-comp-cat${comp.specials.includes(tag) ? ' is-on' : ''}" data-special="${escHtml(tag)}">${escHtml(label)}</button>`).join('');
    const emitted = compTags(comp);
    return `<div class="ia-comp-panel" id="iaCompPanel">
      <div class="ia-sec-label">축 설정 (구도 프리셋)</div>
      ${selects}
      <div class="ia-comp-row">
        <span class="ia-comp-lbl">1인칭</span>
        <button type="button" class="ia-comp-cat${comp.pov ? ' is-on' : ''}" data-pov="1">POV</button>
      </div>
      <div class="ia-comp-row ia-comp-row-top">
        <span class="ia-comp-lbl">스페셜</span>
        <div class="ia-comp-cats">${specials}</div>
      </div>
      <div class="ia-comp-out">${emitted.length ? escHtml(emitted.join(', ')) : '축 미설정 — 태그 없음'}</div>
    </div>`;
  }

  function bindCompPanel() {
    const host = panelMount.querySelector('#iaCompPanel');
    if (!host) return;
    host.querySelectorAll('.ia-comp-select').forEach(el => {
      el.addEventListener('change', () => {
        state.composition[el.dataset.axis] = Number(el.value) || 0;
        onCompChange();
      });
    });
    const pov = host.querySelector('[data-pov]');
    if (pov) pov.addEventListener('click', () => { state.composition.pov = !state.composition.pov; onCompChange(); });
    host.querySelectorAll('[data-special]').forEach(el => {
      el.addEventListener('click', () => {
        const tag = el.dataset.special;
        const arr = state.composition.specials;
        const i = arr.indexOf(tag);
        if (i >= 0) arr.splice(i, 1); else arr.push(tag);
        onCompChange();
      });
    });
  }

  /** 콤보 변경 → 콤보 패널만 다시 그리고(검색/브라우저 유지) 프롬프트 반영. */
  function onCompChange() {
    const host = panelMount.querySelector('#iaCompPanel');
    if (host) { host.outerHTML = compPanelHtml(); bindCompPanel(); }
    emitChange();
  }

  function addTags(tags) {
    const current = currentTags();
    const merged = current.slice();
    // 중복 판정은 대소문자 무시로 통일한다(toggleTag / dupe(✓) 표시와 같은 규칙).
    // 안 그러면 "Dress"가 이미 있는데 "dress"를 넣으면 두 항목이 생긴다(Codex M9).
    const lower = new Set(merged.map(t => t.toLowerCase()));
    for (const tag of tags) {
      const normalized = String(tag || '').trim();
      if (normalized && !lower.has(normalized.toLowerCase())) {
        merged.push(normalized);
        lower.add(normalized.toLowerCase());
      }
    }
    setCurrentTags(merged);
  }

  /** 브라우저/추천에서의 클릭 = 토글. 있으면 제거, 없으면 추가.
   *  브라우저의 ✓(dupe) 판정이 대소문자 무시라, 제거 비교도 대소문자 무시로 맞춘다. */
  function toggleTag(tag) {
    const normalized = String(tag || '').trim();
    if (!normalized) return;
    const current = currentTags();
    const lower = normalized.toLowerCase();
    const existing = current.find(t => t.toLowerCase() === lower);
    if (existing) {
      setCurrentTags(current.filter(t => t !== existing));
    } else {
      setCurrentTags(current.concat([normalized]));
    }
  }

  // ---------------------------------------------------------------- corpus

  async function refreshRecommendations() {
    if (!panelContext || typeof queryCorpus !== 'function') {
      recommendations = [];
      recommendationNote = '이벤트 코퍼스 연결이 없습니다.';
      updateRecommendationsView();
      return;
    }
    const token = ++queryToken;
    recommendationNote = '불러오는 중…';
    try {
      // 현재 슬롯의 태그를 include 로 넣어 그 조합에서 자주 같이 나오는 태그를 받는다.
      const payload = await queryCorpus({
        rating: state.rating,
        person: state.person,
        include: currentTags(),
        exclude: [],
        search: '',
        limit: 40,
      });
      if (token !== queryToken) return;            // superseded
      recommendations = Array.isArray(payload?.tags) ? payload.tags : [];
      recommendationNote = recommendations.length ? '' : '매칭되는 이벤트가 없습니다.';
    } catch (error) {
      if (token !== queryToken) return;
      recommendations = [];
      if (error?.code === 'superseded' || error?.code === 'disconnected') return;
      recommendationNote = corpusMessage(error);
    }
    // 추천 영역만 교체한다. 패널 전체를 다시 그리면 입력 중이던 태그와 포커스가 날아간다.
    updateRecommendationsView();
  }

  function corpusMessage(error) {
    const code = error?.code || '';
    if (code === 'corpus_unavailable' || code === 'partition_unavailable') {
      return '이벤트 코퍼스 데이터가 설치되지 않았습니다. 직접 입력은 그대로 사용할 수 있습니다.';
    }
    if (code === 'unknown_include_tags') {
      return '선택한 태그 중 코퍼스에 없는 것이 있어 추천을 계산할 수 없습니다.';
    }
    return '추천을 불러오지 못했습니다.';
  }

  // ---------------------------------------------------------------- toggle

  function setActive(next, {silent = false} = {}) {
    const value = !!next;
    if (value === active) return;
    active = value;
    if (toggleButton) {
      toggleButton.classList.toggle('is-on', active);
      toggleButton.setAttribute('aria-pressed', active ? 'true' : 'false');
    }
    blocksMount.hidden = !active;
    if (!active) { closePositionPicker(); closePanel(); }
    else { renderBlocks(); void probeStatus(); }
    onActiveChange(active);
    if (!silent && active) emitChange();
  }

  async function probeStatus() {
    if (typeof corpusStatus !== 'function' || corpusState) return;
    try {
      corpusState = await corpusStatus();
      if (corpusState?.state && corpusState.state !== 'ready') {
        showToast('이벤트 코퍼스 데이터가 없어 추천 태그는 비활성입니다. 직접 입력은 가능합니다.', 'error');
      }
    } catch (error) {
      corpusState = {state: 'missing'};
    }
  }

  // 토글 리스너는 명명 함수로 두어 destroy 시 제거할 수 있게 한다(Codex M7).
  const onToggleClick = () => setActive(!active);
  if (toggleButton) toggleButton.addEventListener('click', onToggleClick);

  // 팝업 내부(검색창 제외)를 mousedown 할 때 기본동작을 막아 슬롯 입력창의 포커스를 지킨다.
  // 분류 탐색은 픽마다 재렌더되는데, 포커스가 눌린 버튼에 있으면 재렌더 시 body 로 떨어지고
  // blur 로 팝업이 닫히던 간헐 버그가 있었다. 입력창(input/textarea) 클릭은 예외.
  const onPanelMouseDown = event => {
    if (event.target.closest('input, textarea')) return;
    event.preventDefault();
  };
  panelMount.addEventListener('mousedown', onPanelMouseDown);

  blocksMount.hidden = true;

  return {
    isActive: () => active,
    setActive,
    setContext: ({rating, person} = {}) => {
      if (rating) state.rating = rating;
      if (person) state.person = person;
    },
    getPrompt: renderPrompt,
    // 생성 요청용 캐릭터(활성 + 태그 보유, NAI 상한 5). app.js 가 overrides.characters/uc/
    // character_positions 로 싣는다.
    getGenerationCharacters: generationCharacters,
    // 모드 전환 시 호출 — Position 버튼/Reference 는 NAI 전용이라 헤더를 다시 그려야 한다.
    onModeChanged: () => { if (active) { closePositionPicker(); renderBlocks(); } },
    destroy: () => {
      // 하위 모듈의 리스너/타이머/팝업/툴팁까지 정리한다.
      if (autocomplete) { try { autocomplete.unbind(); } catch (e) {} }
      if (browse) { try { browse.destroy(); } catch (e) {} }
      if (toggleButton) toggleButton.removeEventListener('click', onToggleClick);
      panelMount.removeEventListener('mousedown', onPanelMouseDown);
      closePositionPicker();
      if (posPopup) { posPopup.remove(); posPopup = null; }
      blocksMount.innerHTML = '';
      panelMount.classList.remove('open');
      panelMount.style.top = panelMount.style.left = panelMount.style.width = '';
      panelMount.innerHTML = '';
    },
  };
}
