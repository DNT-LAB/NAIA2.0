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

// 축 정의(팔레트/슬라이더/썸네일/탐색) — wildcards/thumb 에서 생성된 파생 모듈.
import {
  CHAR_SLOTS, PALETTES, SLIDERS, THUMB_TAGS, THUMB_FRAMING, PALETTE_SHAPE, AXIS_RULES, TAG_DESC,
  PACK_AXIS, SENSITIVE_TAGS, POSE_MULTI_SECTIONS, LOC_SECTIONS,
  OBJ_SECTIONS, ANI_SECTIONS, FX_SECTIONS,
  CLOTH_COMBO, CLOTH_COMBO_REV,
} from './interactiveAxes.mjs?v=20260728-ax93';

// 구도(meta)는 실제 구도 태그와 보조 효과가 섞여 있어(Codex 조사) 두 섹션으로 나눈다.
// '구도'=PRIMARY subgroup 만, '효과'=나머지. 두 슬롯 모두 meta 축이라 프롬프트엔 함께 나간다.
// focus_tags 는 subgroup 채로는 구도에 남고(ass focus 등 초점), 캐릭터 특징 10개만 태그 단위로
// 특징으로 이동(Codex 감사). 그래서 focus_tags 는 구도 PRIMARY 로 유지.
const COMPOSITION_PRIMARY = ['image_composition', 'composition', 'framing', 'focus_tags', 'focus', 'count'];
// 2명 이상이 필요한 자세. 캐릭터별 슬롯에 두면 1명짜리 그림에서 모델이 유령 상대를
// 그려내 그림이 망가진다 — 그래서 이미지 전체에 적용되는 씬 슬롯이 담당한다.
// 목록은 interactiveAxes.mjs 가 준다(POSE_MULTI_SECTIONS). 여기에 손으로 적어 뒀더니
// 신설 `pose_leg_m`·`pose_body_touch_m` 36개가 빠져 찍어도 안 보이는 상태였다.

const SCENE_SLOTS = [
  {id: 'composition', name: '구도', icon: '\u{1F5BC}', axis: 'meta', subgroupInclude: COMPOSITION_PRIMARY},
  // 썸네일이 없는 meta 태그만 담는 트리. `effects`/`symbols`/`colors` 는 fx 축
  // 483장이 이미 덮으므로(실측 482/483 중복) 빼야 '효과' 슬롯이 둘로 보이지 않는다.
  // scan/year_tags/quality/art_style 과 1개짜리 오분류는 그림에 영향이 없다.
  {id: 'composition_fx', name: '기타·텍스트', icon: '\u{1F524}', axis: 'meta',
   subgroupExclude: [...COMPOSITION_PRIMARY, 'effects', 'symbols', 'colors',
                     'scan', 'year_tags', 'quality', 'art_style',
                     'birds', 'cats', 'hands']},
  // 배경도 썸네일 슬롯이 됐다(295장 8축). 사람이 주인공이 아니라 프레이밍 전제가
  // 다르다 — 실내는 `scenery` 를 빼야 살고 날씨는 있어야 산다(파일럿 25장).
  {id: 'background', name: '배경', icon: '\u{1F3DE}', axis: 'location',
   sections: LOC_SECTIONS},
  // 사물도 썸네일 슬롯이 됐다(995장 9축). food 를 별도 축으로 갈랐다 —
  // 다른 축에 거는 `-1:: food ::` 상쇄가 음식 181개를 죽이기 때문이다.
  {id: 'etc', name: '사물', icon: '⚙', axis: 'object', sections: OBJ_SECTIONS},
  // 동물은 축이 아예 없어 소품 탐색기가 유일한 경로였다(animal 61,629).
  {id: 'animal', name: '동물', icon: '\u{1F43E}', axis: 'object', sections: ANI_SECTIONS},
  // 효과·기호·색조. 구도(콤보 프리셋)와 인원(캐릭터 헤더)은 여기 넣지 않는다.
  {id: 'fx', name: '효과·기호', icon: '✨', axis: 'meta', sections: FX_SECTIONS},
  {id: 'pose_multi', name: '다인원 자세', icon: '\u{1F46F}', axis: 'pose_action',
   sections: POSE_MULTI_SECTIONS},
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

/** 하위 슬롯 표시명. key 는 상태 필드명(짧고 셀렉터 안전), label 은 화면 표기. */
function subLabel(meta) { return (meta && (meta.label || meta.key)) || ''; }

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

// 특징은 5개 슬롯으로 나뉜다. 각 슬롯은 팝업에서 여러 '축'(팔레트/슬라이더/썸네일/탐색)을
// 모아 보여준다 — 팝업이 무거운 일을 하므로 좌측 슬롯 수를 늘리지 않는다.
// 슬롯/축 정의는 interactiveAxes.mjs(와일드카드에서 생성)가 SSOT.
const CHAR_SUBS = [
  ...CHAR_SLOTS,
  // 의상/소품·장식도 CHAR_SLOTS(생성 파일)로 옮겼다 — 썸네일 축 22개 + 탐색기를
  // 함께 가지므로 sections 가 필요하다. 여기에 리터럴로 남기면 슬롯이 중복된다.
  // 액션 -> '자세' 로 CHAR_SLOTS(생성 파일)에 옮겼다. 썸네일 18축을 가지므로
  // sections 가 필요하고, 여기 리터럴로 남기면 슬롯이 중복된다.
  // 표정은 CHAR_SLOTS(생성 파일)로 옮겼다 — 썸네일 축(홍조·눈물·땀 27장)과
  // 탐색기를 함께 가지므로 sections 가 필요하다.
  // 캐릭터가 든 무기/소품 등. 씬 '사물'과 같은 축을 쓰지만 들어가는 자리가 다르다
  // (캐릭터 프롬프트 vs 베이스 프롬프트). 원래 탐색기 전용이었는데, 그 트리
  // 3,204개 중 1,955개가 이 썸네일 축들과 정확히 같았다 — 만들어 둔 그림을
  // 놔두고 같은 태그를 텍스트 트리로 다시 보여주고 있었다.
  {key: '사물', icon: '⚙', axis: 'object', sections: OBJ_SECTIONS},
];

/** 팔레트/슬라이더는 축 안에서 하나만 유효하다 — 그 축의 모든 태그(소문자). */
function axisTagSet(kind, ref) {
  if (kind === 'palette') return (PALETTES[ref] || []).map(d => d.tag.toLowerCase());
  if (kind === 'slider') return ((SLIDERS[ref] || {}).steps || []).map(t => t.toLowerCase());
  return [];
}

/** 슬라이더 기본값(예: 머리 길이 = medium hair)을 새 캐릭터 필드에 미리 넣는다.
 *  slot key -> [태그...]. 기본값이 없는 축은 비어 있다. */
function defaultFieldsFor(slotKey) {
  const slot = CHAR_SLOTS.find(s => s.key === slotKey);
  if (!slot || !Array.isArray(slot.sections)) return [];
  const out = [];
  for (const sec of slot.sections) {
    if (sec.kind !== 'slider') continue;
    const def = (SLIDERS[sec.ref] || {}).default;
    if (def) out.push(def);
  }
  return out;
}

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
      // 하위 슬롯 목록에서 파생 — CHAR_SUBS 를 늘릴 때 여기를 같이 고칠 필요가 없다.
      // 슬라이더 기본값(머리 길이=medium)은 미리 채워, 초보자가 비워둬도 합리적 결과가 나온다.
      fields: Object.fromEntries(CHAR_SUBS.map(s => [s.key, defaultFieldsFor(s.key)])),
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

  /** 씬 슬롯의 플로팅 버튼 마크업. 전폭 행이 아니라 아이콘+이름+개수의 압축형이다. */
  function sceneButtonHtml(slot) {
    const tags = state.slots[slot.id] || [];
    const chipTags = slot.id === 'composition'
      ? [...compChips(state.composition), ...tags] : tags;
    const on = isEditing('scene', slot.id);
    return `<button type="button" class="ia-scene-btn${on ? ' is-open' : ''}${chipTags.length ? ' has-tags' : ''}"
      data-slot="${slot.id}" title="${escHtml(slot.name)}">
      <span class="ia-block-icon">${slot.icon}</span>
      <span class="ia-scene-btn-name">${escHtml(slot.name)}</span>
      ${chipTags.length ? `<span class="ia-scene-btn-n">${chipTags.length}</span>` : ''}
    </button>`;
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
            <span class="ia-block-title"><span class="ia-block-icon">${s.icon}</span><span class="ia-block-name">${escHtml(subLabel(s))}</span></span>
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
        <div class="ia-char-body">
          <div class="ia-char-preset-row">
            <button type="button" class="ia-char-preset" data-charpreset data-cid="${cid}"
              title="캐릭터 프리셋 (준비 중) — 머리/눈/체형을 한 번에 채우는 프리셋">캐릭터 프리셋</button>
          </div>
          ${subs}
        </div>
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

  // 씬 버튼을 담는 플로트. 좁은 창에서는 blocksMount 안으로 되돌린다.
  let sceneMount = null;
  const SCENE_FLOAT_MIN = 1180;   // 이 아래는 옆에 자리가 없다

  function ensureSceneMount() {
    if (sceneMount && document.body.contains(sceneMount)) return sceneMount;
    sceneMount = document.createElement('div');
    sceneMount.className = 'ia-scene-float';
    document.body.appendChild(sceneMount);
    sceneMount.addEventListener('click', event => {
      const b = event.target.closest('[data-slot]');
      if (!b) return;
      if (isEditing('scene', b.dataset.slot)) { focusEditingInput(); return; }
      openSlot(b.dataset.slot);
    });
    return sceneMount;
  }

  // 버튼 줄 높이. 팝업이 이만큼 아래에서 시작해 서로 가리지 않는다.
  const SCENE_FLOAT_H = 30;

  function sceneFloatFits() {
    if (window.innerWidth < SCENE_FLOAT_MIN) return false;
    const box = blocksMount.getBoundingClientRect();
    return box.right + 12 + 360 <= window.innerWidth - 12;   // 가로 한 줄이 들어갈 폭
  }

  // 팝업의 CSS 기본 top. 버튼 줄은 여기에 깔고 팝업을 그 아래로 내린다.
  const PANEL_TOP = 46;
  const PANEL_LEFT = 494;   // .ia-panel 의 CSS 기본 left

  function positionSceneFloat() {
    const host = ensureSceneMount();
    // Interactive 가 꺼져 있으면 버튼도 없어야 한다 — blocksMount 가 hidden 이면 끈다.
    if (!sceneFloatFits() || blocksMount.hidden) { host.classList.remove('open'); return; }
    // 세로로 쌓았더니 결과 영역을 가렸다(실사용 지적). **가로 한 줄**로 깔되,
    // blocksMount.top 에서 위로 빼면 앱 탭바를 덮는다(실측) — 팝업 기준선에 맞춘다.
    // `blocksMount.right`(465)는 좌측 컬럼의 **안쪽** 끝이라 그 기준으로 붙이면
    // 컬럼 여백을 파고든다(실측: 컬럼 바깥 끝 480). `.ia-panel` 의 CSS 기본
    // left(494)가 이미 그 여백을 감안한 값이라 하한으로 쓴다.
    const box = blocksMount.getBoundingClientRect();
    const left = Math.max(Math.round(box.right + 12), PANEL_LEFT);
    host.style.left = left + 'px';
    host.style.top = PANEL_TOP + 'px';
    host.style.width = Math.round(window.innerWidth - left - 12) + 'px';
    if (host.innerHTML) host.classList.add('open');
  }

  function renderBlocks() {
    const floating = sceneFloatFits();
    // 편집 중인 씬 슬롯은 **인라인으로 남긴다.** 태그를 직접 치는 textarea 가 그
    // 블록 안에 있어서, 전부 버튼으로 빼면 입력창이 사라진다(실측).
    const inlineScenes = floating
      ? SCENE_SLOTS.filter(sl => isEditing('scene', sl.id))
      : SCENE_SLOTS;
    blocksMount.innerHTML = charBlockHtml() + inlineScenes.map(sceneBlockHtml).join('');
    const host = ensureSceneMount();
    host.innerHTML = floating ? SCENE_SLOTS.map(sceneButtonHtml).join('') : '';
    positionSceneFloat();
    // 초기 렌더는 `blocksMount.hidden` 이 아직 true 인 시점에 돌 수 있다(실측: 새로고침
    // 하면 버튼은 생기는데 플로트가 안 열렸다). 레이아웃이 잡힌 다음 프레임에 한 번 더
    // 판정해 순서 의존을 없앤다.
    requestAnimationFrame(positionSceneFloat);

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
    blocksMount.querySelectorAll('[data-charpreset]').forEach(el => {
      el.addEventListener('click', event => {
        event.stopPropagation();
        showToast('캐릭터 프리셋은 준비 중입니다.');
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
    // 직접 타이핑으로 축 값이 바뀐 경우에도 팔레트/슬라이더 선택 표시를 맞춘다.
    if (opts.fromInput) refreshAxisSections();
    void renderAside();   // 오른쪽 조언 플로트 — 선택이 바뀔 때마다 다시 계산
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
      // 축 섹션을 넘기지 않아 '다인원 자세' 팝업이 통째로 비어 있었다 — 캐릭터
      // 경로(openCharSub)에만 있던 줄이다. 씬 슬롯도 sections 를 가질 수 있다.
      sections: slot.sections || null,
      subgroupInclude: slot.subgroupInclude || browseScopeOf(slot) || null,
      subgroupExclude: slot.subgroupExclude || null,
    };
    enterEditing();
  }

  function openCharSub(cid, sub) {
    const meta = CHAR_SUBS.find(s => s.key === sub);
    if (!meta) return;
    // 표시 라벨은 C1..Cn (내부 id 는 c1/c2.. 안정 고유값이라 사용자에게 보여주지 않는다).
    const index = state.chars.findIndex(c => c.id === cid);
    const label = index >= 0 ? 'C' + (index + 1) : cid;
    panelContext = {
      kind: 'char', cid, sub,
      title: `${label} · ${subLabel(meta)}`,
      axis: meta.axis,
      // 축 섹션(팔레트/슬라이더/썸네일/탐색). 없으면 기존 검색+탐색 팝업.
      sections: meta.sections || null,
      // 하위 슬롯이 subgroup 스코프를 가지면 분류 탐색을 그 범위로 좁힌다(구도/효과와 동일 기법).
      // sections 가 있으면 browse 섹션의 subgroups 를 스코프로 쓴다.
      subgroupInclude: meta.subgroups || browseScopeOf(meta) || null,
      subgroupExclude: meta.subgroupsExclude || null,
    };
    enterEditing();
  }

  /** 이 슬롯에 전체 태그 탐색기(3단 계층 + 검색)를 붙일까.
   *  축 섹션(팔레트/슬라이더/썸네일)만으로 충분한 슬롯(예: 머리)에서는 숨긴다 —
   *  sections 가 없는 기존 슬롯(의상/액션/표정/사물)과 browse 섹션을 가진 슬롯만 붙인다. */
  function wantsBrowse() {
    const secs = panelContext?.sections;
    if (!Array.isArray(secs) || !secs.length) return true;          // 기존 슬롯 = 탐색기 전용
    return secs.some(sec => sec.kind === 'browse');
  }

  /** 검색창을 붙일까. 계층 탐색과 **따로** 판단한다 — 둘은 성격이 다른 도구다.
   *  검색은 썸네일 그리드를 거르므로 `thumb` 섹션만 있어도 붙는다(다인원 자세 등:
   *  축이 13개면 탭만으로는 원하는 태그를 못 찾는다). */
  function wantsSearch() {
    const secs = panelContext?.sections;
    if (!Array.isArray(secs) || !secs.length) return true;
    return secs.some(sec => sec.kind === 'browse' || sec.kind === 'thumb');
  }

  /** sections 의 browse 섹션이 지정한 subgroup 을 트리 스코프로 쓴다. */
  function browseScopeOf(meta) {
    if (!meta || !Array.isArray(meta.sections)) return null;
    const out = [];
    for (const sec of meta.sections) {
      if (sec.kind === 'browse' && Array.isArray(sec.subgroups)) out.push(...sec.subgroups);
    }
    return out.length ? out : null;
  }

  /** 슬롯을 텍스트 입력으로 펼치고, 그 옆에 검색+탐색 팝업을 띄운다. */
  function enterEditing() {
    thumbScroll.clear();       // 슬롯을 바꾸면 썸네일 스크롤을 처음으로
    thumbFilter = '';          // 검색어도 슬롯 단위다 — 남기면 다음 슬롯이 걸러진 채 열린다
    // 아코디언 기본값 = 그 슬롯의 첫 썸네일 섹션(선택된 게 있으면 그 섹션을 우선 펼친다).
    openThumbAxis = firstThumbAxis();
    // 팩 인덱스는 한 번만 받고, 도착하면 축 영역만 다시 그린다(이미지 셀로 승격).
    void loadThumbIndex().then(() => { if (panelContext) refreshAxisSections(); });
    openId = panelContext.kind === 'scene' ? panelContext.slotId : 'character';
    renderBlocks();            // 편집 슬롯만 textarea 로, 나머지는 칩으로
    renderPanel();             // 검색창 + 분류 탐색
    panelMount.classList.add('open');
    // 편집 중 표시 — tagAssist 의 태그 정보 툴팁을 억제한다(팝업 위에 겹쳐 가림).
    document.body.classList.add('interactive-editing');
    focusEditingInput();       // 슬롯 textarea 포커스(끝으로)
    positionPopup();           // 편집 슬롯 옆에 앵커
    void renderAside();        // 오른쪽 조언 플로트
  }


  /** 받침 유무로 조사를 고른다. 한글 라벨(축 이름)에만 쓴다 — 영문 태그 뒤에는
   *  발음을 따져야 해서(`tail 이` vs `set 이`) 아예 조사가 안 붙는 문장을 쓴다. */
  function josa(word, withJong, withoutJong) {
    const ch = String(word || '').trim().slice(-1);
    const code = ch.charCodeAt(0);
    if (!(code >= 0xac00 && code <= 0xd7a3)) return withoutJong;
    return (code - 0xac00) % 28 ? withJong : withoutJong;
  }

  // ---- 조언 플로트 (팝업 오른쪽) ----
  // 그리드가 팝업 폭을 다 쓰고 오른쪽이 비어 있어서 전제조건·충돌·추천을 거기 띄운다.
  // 데이터는 /api/interactive-advice — 근거가 전부 실측이다(공식 tag implications +
  // 의상 프리셋 gsq_1girl_solo 파티션 통계).
  // 창 크기가 바뀌면 팝업·플로트 좌표가 어긋난다(둘 다 fixed + 인라인 좌표).
  // 원래 리사이즈 대응이 아예 없어서 팝업이 화면 밖으로 나가기도 했다.
  window.addEventListener('resize', () => {
    // 씬 플로트는 팝업과 무관하게 항상 따라가야 한다 — 창을 좁히면 인라인으로
    // 되돌려야 하므로 renderBlocks 까지 다시 돈다.
    renderBlocks();
    if (!panelContext) return;
    positionPopup();
    positionAside();
  });

  let asideMount = null;
  let lastPicked = '';    // 추천의 기준이 되는 마지막 선택 태그
  let asideSeq = 0;
  const adviceCache = new Map();

  function ensureAside() {
    if (asideMount && document.body.contains(asideMount)) return asideMount;
    asideMount = document.createElement('div');
    asideMount.className = 'ia-aside';
    document.body.appendChild(asideMount);
    // 한 번 누르면 '살펴보기'(강조만), 한 번 더 누르면 적용한다.
    // 썸네일이 작아 오클릭이 잦은데 바로 프롬프트에 들어가면 되돌리기가 번거롭다.
    asideMount.addEventListener('click', ev => {
      // 색 조합은 한 번 눌러 적용한다. 추천 썸네일의 두 번 클릭은 150칸 그리드에서
      // 오클릭이 잦아 넣은 것인데, 색은 3~10개짜리 라벨 버튼이라 그럴 위험이 없다.
      const c = ev.target.closest('[data-combo-mod]');
      if (c) {
        applyCombo(c.getAttribute('data-combo-base'), c.getAttribute('data-combo-mod'));
        renderBlocks();
        refreshAxisSections();
        void renderAside();
        return;
      }
      const b = ev.target.closest('[data-advice-add]');
      if (!b) return;
      // 그리드와 같은 규칙 — 버튼을 눌렀을 때만 실행한다.
      if (!ev.target.closest('.ia-cell-act')) return;
      toggleTag(b.getAttribute('data-advice-add'), { fromAside: true });
    });
    return asideMount;
  }

  async function fetchAdvice(tags) {
    const want = tags.filter(t => !adviceCache.has(t));
    if (want.length) {
      try {
        const r = await fetch('/api/interactive-advice/batch?tags=' +
          encodeURIComponent(want.slice(0, 40).join(',')));
        const j = await r.json();
        (j.items || []).forEach(it => adviceCache.set(it.tag, it));
      } catch { want.forEach(t => adviceCache.set(t, null)); }
    }
    return tags.map(t => adviceCache.get(t)).filter(Boolean);
  }

  function chipsHtml(list, cls) {
    const cur = new Set(currentTags().map(x => x.toLowerCase()));
    return list.map(t =>
      `<button type="button" class="ia-aside-chip ${cur.has(String(t).toLowerCase()) ? 'on' : (cls || '')}"` +
      ` data-advice-add="${escHtml(t)}">${escHtml(t)}</button>`).join('');
  }

  /** 추천 칩을 썸네일 셀로 그린다(2열). 팩에 이미지가 없으면 이름만 나온다. */
  function recThumbsHtml(list) {
    return list.map(o => {
      const t = typeof o === 'string' ? o : o.tag;
      const match = typeof o === 'object' && o.match;
      const axis = Object.keys(THUMB_TAGS).find(a => THUMB_TAGS[a].includes(t)) || '';
      const has = axis && (thumbHave.get(packAxisOf(axis)) || new Set()).has(t);
      const img = has
        ? `<img src="${escHtml(thumbUrl(axis, t))}" alt="" loading="lazy" decoding="async">`
        : '<span class="ia-aside-thumb-none"></span>';
      const on = typeof o === 'object' && o.on;
      // 그리드와 같은 규칙 — 라벨은 항상 태그 이름이고, 행동은 호버 버튼이 맡는다.
      const cls = 'ia-aside-thumb' + (match ? ' match' : '') + (on ? ' on' : '');
      const tip = on ? `${t} — 이미 넣었습니다` :
        (match ? `${t} — 지금 고른 것들과도 어울립니다` : t);
      const act = `<span class="ia-cell-act" data-act="${on ? 'off' : 'on'}">${on ? '제거' : '선택'}</span>`;
      return `<div class="${cls}" data-advice-add="${escHtml(t)}"` +
        ` title="${escHtml(tip)}"><span class="ia-aside-thumb-img">${img}${act}</span>` +
        `<span>${escHtml(t)}</span></div>`;
    }).join('');
  }

  /** 선택된 태그들의 조언을 모아 오른쪽에 그린다. */
  // ---- 의상 색 조합 ----
  // `_cloth_combo.json` 이 확정한 조합만 쓴다. 28색을 다 열면 `green shirt` 처럼 실측으로
  // 확인되지 않은 태그를 권하게 된다 — 목록에 없는 색은 슬롯 입력창에 직접 쓰면 된다.
  const COMBO_SWATCH = {
    black: '#1b1b20', white: '#f2f2f4', red: '#c0392b', blue: '#2f6fc0', green: '#3a8f4e',
    yellow: '#d8b933', pink: '#e08bb0', purple: '#8158b8', orange: '#d8853a', brown: '#7a5638',
    grey: '#8a8a92', gray: '#8a8a92',
  };
  const COMBO_LABEL = {
    black: '검정', white: '흰색', red: '빨강', blue: '파랑', green: '초록', yellow: '노랑',
    pink: '분홍', purple: '보라', orange: '주황', brown: '갈색', grey: '회색', gray: '회색',
    striped: '줄무늬', multicolored: '여러 색',
  };

  /** seed 태그의 (base, 현재 색). 조합 태그면 분해하고, 베이스면 색 없음으로 본다. */
  function comboStateOf(tag) {
    const t = String(tag || '');
    const rev = (CLOTH_COMBO_REV || {})[t];
    if (rev) return { base: rev[0], mod: rev[1] };
    if ((CLOTH_COMBO || {})[t]) return { base: t, mod: '' };
    return null;
  }

  function comboRowHtml(seedTag) {
    const st = comboStateOf(seedTag);
    if (!st) return '';
    const mods = (CLOTH_COMBO || {})[st.base] || {};
    const keys = Object.keys(mods);
    if (!keys.length) return '';
    const cells = keys.map(mod => {
      const on = mod === st.mod;
      const sw = COMBO_SWATCH[mod];
      const chip = sw
        ? `<span class="ia-combo-dot" style="background:${sw}"></span>`
        : `<span class="ia-combo-dot is-${escHtml(mod)}"></span>`;
      return `<button type="button" class="ia-combo${on ? ' on' : ''}"
        data-combo-base="${escHtml(st.base)}" data-combo-mod="${escHtml(mod)}"
        title="${escHtml(mods[mod])}">${chip}${escHtml(COMBO_LABEL[mod] || mod)}</button>`;
    }).join('');
    return '<div class="ia-aside-card"><div class="ia-aside-title">색·무늬' +
      `<span class="ia-aside-count">${escHtml(st.base)}</span></div>` +
      `<div class="ia-combo-row">${cells}</div>` +
      (st.mod ? '<div class="ia-aside-hint soft">누르면 색을 뗍니다.</div>' : '') +
      '</div>';
  }

  /** 색을 붙이거나(base -> `white shirt`) 바꾸거나 뗀다. 슬롯에서 한 자리만 차지한다. */
  function applyCombo(base, mod) {
    const mods = (CLOTH_COMBO || {})[base] || {};
    const target = mods[mod];
    if (!target) return;
    const cur = currentTags();
    const owned = new Set([base.toLowerCase(), ...Object.values(mods).map(t => t.toLowerCase())]);
    const kept = cur.filter(t => !owned.has(t.toLowerCase()));
    const wasOn = cur.some(t => t.toLowerCase() === target.toLowerCase());
    const next = wasOn ? base : target;      // 같은 색을 다시 누르면 색만 뗀다
    // 원래 자리를 지킨다 — 뒤에 붙이면 프롬프트 순서가 바뀌어 그림이 달라진다.
    const at = cur.findIndex(t => owned.has(t.toLowerCase()));
    kept.splice(at < 0 ? kept.length : at, 0, next);
    setCurrentTags(kept);
    lastPicked = next;
  }

  async function renderAside() {
    const host = ensureAside();
    if (!panelContext) { host.classList.remove('open'); host.innerHTML = ''; return; }
    const tags = currentTags();
    const seq = ++asideSeq;
    if (!tags.length) {
      host.classList.add('open');
      host.innerHTML = '<div class="ia-aside-card"><div class="ia-aside-title">도움말</div>' +
        '<div class="ia-aside-empty">태그를 고르면 필요한 것과 어울리는 조합을 여기에 보여줍니다.</div></div>';
      positionAside();
      return;
    }
    const items = await fetchAdvice(tags);
    if (seq !== asideSeq || !panelContext) return;   // 그 사이 슬롯이 바뀌었다

    // 전제조건 — 아직 안 고른 축만 알린다. 이미 골랐으면 안내할 이유가 없다.
    const chosenAxes = new Set();
    for (const t of tags) {
      for (const [ax, list] of Object.entries(THUMB_TAGS)) {
        if (list.includes(t)) chosenAxes.add(ax);
      }
    }
    // `...r` 를 뒤에 펼치면 r.tag(부모 태그)가 it.tag(고른 태그)를 덮어써서
    // "skirt lift 가 필요합니다" 대신 "skirt 가 필요합니다" 로 나온다. source 로 분리한다.
    const needs = [];
    const needSeen = new Set();
    for (const it of items) {
      for (const r of (it.requires || [])) {
        if (chosenAxes.has(r.axis)) continue;
        const key = r.axis + '|' + it.tag;
        if (needSeen.has(key)) continue;      // 같은 축을 두 번 안내하지 않는다
        needSeen.add(key);
        needs.push({ axis: r.axis, label: r.label, strong: r.strong, source: it.tag });
      }
    }
    // 충돌 — 전용 엔드포인트로 묻는다.
    // 태그별 conflict 목록은 화면용으로 12개까지만 잘라 보내므로, 그걸로 교집합을
    // 구하면 잘린 뒤쪽 쌍을 놓친다(실측: china dress + skirt set 이 안 잡혔다).
    const lower = new Set(tags.map(x => x.toLowerCase()));
    let clashes = [];
    try {
      const cr = await fetch('/api/interactive-advice/conflicts?tags=' +
        encodeURIComponent(tags.slice(0, 40).join(',')));
      const cj = await cr.json();
      clashes = (cj.pairs || []).map(p => [p.a, p.b]);
    } catch { clashes = []; }
    if (seq !== asideSeq || !panelContext) return;
    // 추천은 **부위별로 나눠** 보여준다. 점수 순 상위만 쓰면 같은 부위 변형이 줄줄이
    // 나온다 — `sweater` 를 고르면 ribbed/turtleneck/off-shoulder sweater 로 8칸이 찬다.
    // 서로 다른 부위를 보여줘야 다음에 뭘 고를지 알려주는 값이 있다.
    // 추천은 **마지막에 고른 태그** 하나를 기준으로 낸다.
    // 선택한 것 전부의 추천을 합쳤더니 잡탕이 됐다 — `heart-shaped eyewear` + `bikini`
    // + `bandage on face` 를 고르면 서로 무관한 것이 뒤섞여 무엇과 어울린다는 건지
    // 알 수 없었다. 기준이 하나여야 "이것과 어울리는 것"이라는 말이 성립한다.
    // 기준을 한 번 정하면 고정한다. "목록의 마지막"으로 폴백만 하면 플로트에서
    // 추가할 때마다 그 태그가 기준이 되어 목록이 갈리고, 방금 넣은 것을 되돌릴 수 없다.
    // 기준이 목록에서 빠졌을 때만(직접 지웠을 때) 다시 잡는다.
    if (!lastPicked || !lower.has(lastPicked.toLowerCase())) {
      lastPicked = tags[tags.length - 1];
    }
    const seedTag = lastPicked;
    const seed = items.find(it => it.tag === seedTag) || items[items.length - 1];
    // 나머지 선택분도 추천하는 것 = 옷 전체와 어울리는 것 -> 강조한다.
    const others = new Set();
    for (const it of items) {
      if (!it || it === seed) continue;
      for (const t of (it.recommend || [])) others.add(String(t).toLowerCase());
    }
    const byRegion = new Map();
    for (const g of (seed?.recommendGroups || [])) {
      const cur = byRegion.get(g.label) || [];
      for (const t of g.tags) {
        // 이미 고른 것도 남긴다. 목록에서 빼면 '제외'로 되돌릴 방법이 없어진다.
        if (!cur.some(x => x.tag === t)) {
          cur.push({ tag: t, match: others.has(String(t).toLowerCase()),
                     on: lower.has(String(t).toLowerCase()) });
        }
      }
      byRegion.set(g.label, cur);
    }
    const recGroups = [...byRegion.entries()]
      .filter(([, v]) => v.length)
      .sort((a, b) => b[1].length - a[1].length)
      .slice(0, 3)                       // 화면에는 3개 부위까지
      .map(([label, tags]) => ({ label, tags: tags.slice(0, 6) }));
    const seedLabel = seed ? seed.tag : '';

    const parts = [];
    // 색 조합. `white shirt`(541,974) 처럼 `<색> <옷>` 은 분해해 뒀는데 색을 고를 곳이
    // 없어서, 계층 탐색기가 유일한 경로였다. **마지막에 고른 옷 하나**에만 붙인다 —
    // 슬롯 전체에 색 팔레트를 두면 shirt + skirt 를 고른 뒤 흰색을 눌렀을 때 어느 쪽이
    // 흰색인지 정할 수 없다.
    const colorRow = comboRowHtml(seedTag);
    if (colorRow) parts.push(colorRow);
    if (clashes.length) {
      parts.push('<div class="ia-aside-card"><div class="ia-aside-title">같이 쓰지 않습니다' +
        `<span class="ia-aside-count">${clashes.length}</span></div>` +
        clashes.map(([a, b]) =>
          `<div class="ia-aside-warn">${escHtml(a)} + ${escHtml(b)}<br>실제 이미지에서 함께 쓰인 적이 없습니다.</div>`).join('') +
        '</div>');
    }
    if (needs.length) {
      const strong = needs.filter(n => n.strong);
      const soft = needs.filter(n => !n.strong);
      parts.push('<div class="ia-aside-card"><div class="ia-aside-title">필요한 것' +
        `<span class="ia-aside-count">${needs.length}</span></div>` +
        strong.map(n => `<div class="ia-aside-hint"><code>${escHtml(n.source)}</code>` +
          ` — <b>${escHtml(n.label)}</b>${josa(n.label, '을', '를')} 함께 골라야 제대로 나옵니다.</div>`).join('') +
        soft.map(n => `<div class="ia-aside-hint soft"><code>${escHtml(n.source)}</code>` +
          ` — ${escHtml(n.label)}${josa(n.label, '을', '를')} 함께 고르면 더 잘 나옵니다.</div>`).join('') +
        '</div>');
    }
    // '잘 안 어울립니다'(비권장)는 뺐다 — 초보자에게 하지 말라는 목록은 부담만 주고,
    // 실제로 고를 것을 보여주는 쪽이 값이 크다. 데이터는 그대로 있으니 되살리기 쉽다.
    if (recGroups.length) {
      parts.push('<div class="ia-aside-card scroll"><div class="ia-aside-title">함께 쓰는 것' +
        `<span class="ia-aside-count">${escHtml(seedLabel)} 기준</span></div>` +
        recGroups.map(g =>
          `<div class="ia-aside-group"><div class="ia-aside-group-label">${escHtml(g.label)}</div>` +
          `<div class="ia-aside-thumbs">${recThumbsHtml(g.tags)}</div></div>`).join('') +
        '</div>');
    }
    if (!parts.length) {
      parts.push('<div class="ia-aside-card"><div class="ia-aside-title">도움말</div>' +
        '<div class="ia-aside-empty">이 조합에 대해 알려드릴 것이 없습니다. 그대로 쓰셔도 됩니다.</div></div>');
    }
    host.classList.add('open');
    host.innerHTML = parts.join('');
    positionAside();
  }

  /** 팝업 오른쪽에 붙인다. 자리가 안 나오면 숨긴다 — 그리드가 우선이다. */
  function positionAside() {
    if (!asideMount) return;
    const vw = window.innerWidth;
    const box = panelMount.getBoundingClientRect();
    const W = 258, GAP = 12;
    const left = box.right + GAP;
    // 떼기만 하고 다시 붙이지 않아서, 한 번 좁아지면 창을 넓혀도 플로트가 돌아오지
    // 않았다(다음 renderAside 까지). 색 조합이 이 플로트에 있으니 옷 색을 고를 길이
    // 아예 막힌다 — 들어갈 자리가 생기면 다시 붙인다.
    if (vw < 1280 || left + W > vw - 12) { asideMount.classList.remove('open'); return; }
    asideMount.style.left = left + 'px';
    asideMount.style.top = Math.max(12, box.top) + 'px';
    asideMount.style.bottom = Math.max(12, window.innerHeight - box.bottom) + 'px';
    if (panelContext && asideMount.innerHTML) asideMount.classList.add('open');
  }

  function closePanel() {
    document.body.classList.remove('interactive-editing');
    if (autocomplete) autocomplete.unbind();
    if (browse) browse.detach();
    openId = null;
    panelContext = null;
    panelMount.classList.remove('open');
    panelMount.innerHTML = '';
    if (asideMount) { asideMount.classList.remove('open'); asideMount.innerHTML = ''; }
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
        // 조언 플로트는 팝업 DOM 밖에 있어서(fixed 별도 마운트) 여기서 빼면
        // 추천 칩을 누르는 순간 팝업이 닫힌다.
        if (a && (panelMount.contains(a) || asideMount?.contains(a)
                  || a.classList?.contains('ia-slot-input'))) return;
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

  /** 팝업을 슬롯 목록 오른쪽(공간 없으면 화면 안으로 clamp)에 앵커한다.
   *
   *  **세로 위치는 슬롯을 따라가지 않고 화면 상단에 고정한다.**
   *  처음에는 편집 중인 슬롯에 맞췄다가, 아래쪽 슬롯을 열면 팝업이 그만큼 짧아져
   *  바닥이 잘렸다. 그래서 '그 캐릭터의 첫 슬롯' 기준으로 바꿨는데, 캐릭터가 여러 명이면
   *  두 번째 캐릭터부터 여전히 아래에서 시작하고 위쪽 공간이 통째로 비었다.
   *  높이를 최대로 쓰는 것이 그리드에 이득이라 세로는 CSS 기본값(top:46px/bottom:14px)에
   *  맡기고, 여기서는 가로만 잡는다.
   */
  function positionPopup() {
    const el = editingEl();
    if (!el) return;
    const vw = window.innerWidth;
    if (vw <= 767) {
      // 모바일: 하단 시트(CSS 미디어쿼리)에 맡긴다. 인라인 앵커 좌표를 비운다.
      panelMount.style.top = panelMount.style.left = panelMount.style.width = panelMount.style.bottom = '';
      return;
    }
    const W = Math.min(560, vw - 32);
    const host = blocksMount.getBoundingClientRect();
    let left = Math.max(host.right + 12, PANEL_LEFT);
    if (left + W > vw - 12) left = Math.max(12, vw - 12 - W);
    panelMount.style.width = W + 'px';
    panelMount.style.left = left + 'px';
    // 씬 버튼 줄이 떠 있으면 그 아래에서 시작한다 — 안 그러면 서로 가린다.
    panelMount.style.top = (sceneFloatFits() && !blocksMount.hidden)
      ? (PANEL_TOP + SCENE_FLOAT_H + 6) + 'px' : '';
    panelMount.style.bottom = '';
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
      ${wantsSearch() ? `<div class="ia-search ia-search-top">
        <input type="text" id="iaTagInput" placeholder="${wantsBrowse()
          ? '분류·태그 검색 (아래 목록 필터)' : '태그 검색 — 아는 태그를 바로 넣습니다'}" autocomplete="off">
        <span class="ia-search-scope">${escHtml(panelContext.axis)}</span>
      </div>` : ''}
      <div class="ia-panel-body">
        ${panelContext.slotId === 'composition' ? compPanelHtml() : ''}
        ${axisSectionsHtml()}
        ${wantsBrowse() ? '<div class="ia-browse-mount" id="iaBrowseMount"></div>' : ''}
      </div>`;

    panelMount.querySelector('[data-close]')?.addEventListener('click', closePanel);
    if (panelContext.slotId === 'composition') bindCompPanel();
    bindAxisSections();
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
      // 팝업 검색창은 자동완성이 아니라 목록을 걸러내는 필터다. 계층 탐색기가 있으면
      // 그 트리를, 없으면(자세) 썸네일 그리드를 거른다.
      // (태그 입력용 자동완성은 슬롯 입력창 쪽에 붙어 있다.)
      const applyFilter = () => {
        if (wantsBrowse()) { if (browse) browse.setFilter(input.value); return; }
        const next = String(input.value || '').trim().toLowerCase();
        if (next === thumbFilter) return;
        thumbFilter = next;
        refreshAxisSections();
      };
      input.addEventListener('input', applyFilter);
      input.addEventListener('keydown', event => {
        if (event.key === 'Escape') { event.preventDefault(); input.value = ''; applyFilter(); }
      });
    }
  }

  // ---- 축 섹션 (팔레트 / 슬라이더 / 썸네일) ----

  const thumbHave = new Map();       // axisKey -> Set(썸네일 이미지가 있는 태그)
  const thumbScroll = new Map();     // axisKey -> scrollTop (재렌더 시 복원)
  let openThumbAxis = null;          // 아코디언 — 썸네일 섹션은 한 번에 하나만 펼친다
  let thumbFilter = '';              // 검색창이 그리드를 거를 때의 질의(트리 없는 슬롯)

  /** 태그명과 한글 설명 양쪽을 본다 — 사용자가 `앉` 으로 `sitting` 을 찾을 수 있어야 한다. */
  function matchesFilter(tag) {
    const q = thumbFilter;
    if (!q) return true;
    if (String(tag).toLowerCase().includes(q)) return true;
    const desc = (TAG_DESC || {})[tag];
    return !!desc && String(desc).toLowerCase().includes(q);
  }

  // 민감 태그(신체 결손/봉합/혈흔 등)는 썸네일을 블러하고 호버 시에만 보여준다.
  const SENSITIVE = new Set((SENSITIVE_TAGS || []).map(t => String(t).toLowerCase()));
  const isSensitive = tag => SENSITIVE.has(String(tag).toLowerCase());

  /** 호버 툴팁 문구: 태그 + 설명. 설명이 없으면 태그만. */
  function tagTip(tag) {
    const desc = (TAG_DESC || {})[tag];
    return desc ? `${tag} · ${desc}` : String(tag);
  }

  /** 이 슬롯에서 기본으로 펼칠 썸네일 축 — 선택된 값이 있는 축을 우선, 없으면 첫 축. */
  function firstThumbAxis() {
    const secs = panelContext?.sections;
    if (!Array.isArray(secs)) return null;
    const thumbs = secs.filter(s => s.kind === 'thumb').map(s => s.ref);
    if (!thumbs.length) return null;
    const sel = currentLower();
    const withSel = thumbs.find(axis =>
      (THUMB_TAGS[axis] || []).some(t => sel.has(t.toLowerCase())));
    return withSel || thumbs[0];
  }

  /** 팩 인덱스를 한 번 받아, 이미지가 있는 태그만 <img> 로 그린다(없으면 텍스트 셀). */
  async function loadThumbIndex() {
    if (thumbHave.size) return;
    try {
      const res = await fetch('/api/interactive-thumb/index', {cache: 'no-store'});
      if (!res.ok) return;
      const data = await res.json();
      for (const [axis, tags] of Object.entries(data?.axes || {})) {
        thumbHave.set(axis, new Set((tags || []).map(t => String(t))));
      }
    } catch (_) { /* 팩이 없으면 전부 텍스트 셀 */ }
  }

  /** 표시 축 -> 팩 축. 얼굴은 생성이 face.txt 한 파일이라 표시 그룹이 달라도 이미지는 face/* 다. */
  function packAxisOf(axis) { return (PACK_AXIS || {})[axis] || axis; }

  function thumbUrl(axis, tag) {
    const pa = packAxisOf(axis);
    return `/api/interactive-thumb?axis=${encodeURIComponent(pa)}&tag=${encodeURIComponent(tag)}`;
  }

  /** 현재 슬롯 태그를 소문자 Set 으로. */
  function currentLower() {
    return new Set(currentTags().map(t => String(t).toLowerCase()));
  }

  // ---- 축 규칙: 부모 태그 자동 배정 / 팔레트 다중 선택 전환 ----

  /** 슬롯에 들어 있는 이 팔레트 소속 태그들을 '순서대로' 돌려준다.
   *  첫 번째 = 주 색상, 나머지 = 추가 색상. 순서가 역할을 encode 하므로 별도 상태가 없다. */
  function paletteChosen(paletteRef) {
    const family = new Set((PALETTES[paletteRef] || []).map(d => d.tag.toLowerCase()));
    return currentTags().filter(t => family.has(String(t).toLowerCase()));
  }

  /** 추가 색상 팔레트를 보여줄까.
   *  패턴(멀티컬러)이 붙어 있거나, 이미 색이 2개 이상이면(숨은 상태 방지) 보여준다. */
  function extraPaletteVisible(paletteRef) {
    const on = Object.entries(AXIS_RULES || {})
      .some(([axisRef, rule]) => rule.multiPalette === paletteRef && multiRuleOn(axisRef, rule));
    return on || paletteChosen(paletteRef).length > 1;
  }

  /** 추가 색상을 허용하는 '규칙 조건'만 판정한다(이미 여러 색이 골라져 있는지는 보지 않는다).
   *  정리(clear) 판단에서 쓰므로 '색이 2개 이상이면 보여준다'는 예외를 섞으면 안 된다. */
  function multiRuleOn(axisRef, rule) {
    // 'any'  = 그 축의 아무 태그든(예: heterochromia)
    // 'tags' = 명시한 태그가 붙어 있을 때만(예: multicolored skin)
    // 기본   = 부모 태그가 붙어 있을 때
    if (rule.multiOn === 'any') return axisHasAny(axisRef);
    if (rule.multiOn === 'tags') return anySelected(rule.multiTags);
    return !!rule.parent && currentLower().has(rule.parent.toLowerCase());
  }

  /** 주 색상 팔레트를 조건부로 보여주는 축(피부)이 있다 — 머리/눈처럼 상시 노출이 아니다.
   *  colored skin 처럼 '색을 지정해야 의미가 생기는' 태그가 붙었을 때만 띄운다. */
  function mainPaletteVisible(paletteRef) {
    return Object.values(AXIS_RULES || {}).some(rule =>
      rule.mainPalette === paletteRef && anySelected(rule.mainOn))
      || paletteChosen(paletteRef).length > 0;
  }

  function anySelected(tags) {
    if (!Array.isArray(tags) || !tags.length) return false;
    const sel = currentLower();
    return tags.some(t => sel.has(String(t).toLowerCase()));
  }

  /** 주 색상 = 첫 번째 항목만 교체한다. 추가 색상은 건드리지 않는다. */
  function setMainColor(paletteRef, tag) {
    const chosen = paletteChosen(paletteRef);
    const main = chosen[0];
    if (main && main.toLowerCase() === String(tag).toLowerCase()) {
      setCurrentTags(currentTags().filter(t => t !== main));   // 같은 색 재클릭 = 해제
      return;
    }
    if (!main) { addTags([tag]); return; }
    setCurrentTags(currentTags().map(t => (t === main ? tag : t)));   // 자리를 유지하며 교체
  }

  /** 추가 색상 = 주 색상을 제외하고 n개 토글. */
  function toggleExtraColor(paletteRef, tag) {
    const chosen = paletteChosen(paletteRef);
    const main = chosen[0];
    if (main && main.toLowerCase() === String(tag).toLowerCase()) {
      showToast('주 색상입니다. 위쪽 색 팔레트에서 변경하세요.', 'error');
      return;
    }
    toggleTag(tag);
  }

  /** 이 축의 부모 태그가 지금 잠겨 있나(하위 항목이 하나라도 선택됨). */
  function parentLocked(axisRef) {
    const rule = (AXIS_RULES || {})[axisRef];
    if (!rule || !rule.parent) return false;
    const sel = currentLower();
    const parentLower = rule.parent.toLowerCase();
    const needs = Array.isArray(rule.parentFor)
      ? rule.parentFor.map(t => t.toLowerCase())
      : (THUMB_TAGS[axisRef] || []).map(t => t.toLowerCase()).filter(t => t !== parentLower);
    return needs.some(t => sel.has(t));
  }

  /** 이 축에 선택된 태그가 하나라도 있나(부모 포함). */
  function axisHasAny(axisRef) {
    const sel = currentLower();
    return (THUMB_TAGS[axisRef] || []).some(t => sel.has(t.toLowerCase()));
  }

  /** 썸네일 축 클릭. 부모 태그 규칙(자동 배정/해제 금지)을 적용한다. */
  function pickThumb(axisRef, tag) {
    const rule = (AXIS_RULES || {})[axisRef];
    if (!rule || !rule.parent) { toggleTag(tag); return; }
    const parent = rule.parent;
    const isParent = String(tag).toLowerCase() === parent.toLowerCase();
    if (isParent && parentLocked(axisRef)) {
      showToast(rule.parentLockedHint || '하위 항목이 선택돼 있어 해제할 수 없습니다.', 'error');
      return;
    }
    toggleTag(tag);
    if (!isParent && parentLocked(axisRef)) {
      addTags([parent]);   // 하위 패턴을 골랐으면 부모를 자동으로 붙인다
      return;
    }
    // 조건부 주 팔레트(피부): 트리거가 전부 빠지면 팔레트가 사라지므로 색도 전부 비운다.
    // 안 비우면 UI 에서 안 보이는 색 태그가 프롬프트에 남는다.
    if (rule.mainPalette && Array.isArray(rule.mainOn) && !anySelected(rule.mainOn)) {
      clearAllColors(rule.mainPalette);
      return;
    }
    // 패턴이 완전히 해제됐으면 추가 색상도 함께 비운다 —
    // 멀티컬러가 아닌데 색이 여러 개 남아 있으면 프롬프트가 모순된다.
    if (rule.multiPalette && !multiRuleOn(axisRef, rule)) clearExtraColors(rule.multiPalette);
  }

  /** 팔레트 소속 색을 전부 제거한다(조건부 팔레트가 닫힐 때). */
  function clearAllColors(paletteRef) {
    const chosen = paletteChosen(paletteRef);
    if (!chosen.length) return;
    const drop = new Set(chosen);
    setCurrentTags(currentTags().filter(t => !drop.has(t)));
    showToast(`색 지정을 해제해 색상 ${drop.size}개도 함께 해제했습니다.`);
  }

  /** 주 색상(첫 번째)만 남기고 같은 팔레트의 나머지 색을 제거한다. */
  function clearExtraColors(paletteRef) {
    const chosen = paletteChosen(paletteRef);
    if (chosen.length <= 1) return;
    const drop = new Set(chosen.slice(1));
    setCurrentTags(currentTags().filter(t => !drop.has(t)));
    showToast(`패턴을 해제해 추가 색상 ${drop.size}개도 함께 해제했습니다.`);
  }

  /** 축 안에서 하나만 유효 — 같은 축의 다른 값은 지우고 하나를 넣는다(없으면 해제). */
  function setExclusive(kind, ref, tag) {
    const family = new Set(axisTagSet(kind, ref));
    const kept = currentTags().filter(t => !family.has(String(t).toLowerCase()));
    const lower = String(tag || '').toLowerCase();
    const already = currentLower().has(lower);
    setCurrentTags(already ? kept : [...kept, tag]);   // 같은 값 재클릭 = 해제
  }

  /** 주 색상 팔레트(항상 하나) / 추가 색상 팔레트(n개) — 같은 스와치 UI 의 미러. */
  function paletteHtml(sec, {extra = false} = {}) {
    const rows = PALETTES[sec.ref] || [];
    if (extra && !extraPaletteVisible(sec.ref)) return '';
    const chosen = paletteChosen(sec.ref);
    const main = (chosen[0] || '').toLowerCase();
    const extras = new Set(chosen.slice(1).map(t => t.toLowerCase()));
    const cells = rows.map(d => {
      const lower = d.tag.toLowerCase();
      const isMain = lower === main;
      const on = extra ? extras.has(lower) : isMain;
      // 추가 팔레트에서 주 색상 칸은 '이미 주 색상'임을 표시하고 선택 대상에서 뺀다.
      const dim = extra && isMain;
      return `<button type="button" class="ia-sw${on ? ' on' : ''}${dim ? ' is-main' : ''}"
        style="background:${d.hex}"
        data-ax="${extra ? 'palette_extra' : 'palette'}" data-ref="${escHtml(sec.ref)}" data-val="${escHtml(d.tag)}"
        title="${escHtml(tagTip(d.tag))}${dim ? ' (주 색상)' : ''}" aria-label="${escHtml(d.tag)}" aria-pressed="${on}"></button>`;
    }).join('');
    const cols = rows.filter(d => d.row !== 2).length || rows.length;
    const hint = extra
      ? `<span class="ia-ax-multi">n개 가능${extras.size ? ` · ${extras.size}` : ''}</span>` : '';
    // 추가 색상 위에 '메인 색상 : [스와치]' 한 줄. 누르면 주 색상 팔레트로 스크롤한다.
    let head = '';
    if (extra) {
      const mainRow = rows.find(d => d.tag.toLowerCase() === main);
      const chip = mainRow
        ? `<span class="ia-mainsw" style="background:${mainRow.hex}"></span><span class="ia-maintag">${escHtml(mainRow.tag)}</span>`
        : '<span class="ia-maintag is-none">미지정</span>';
      head = `<button type="button" class="ia-main-line" data-goto-main="${escHtml(sec.ref)}"
        title="주 색상 팔레트로 이동">메인 색상 : ${chip}</button>`;
    }
    return `<div class="ia-ax-row"><span class="ia-ax-lbl">${escHtml(sec.label)}${hint}</span>
      <div class="ia-sw-col">${head}
        <div class="ia-sw-grid${extra ? ' is-extra' : ''}" style="grid-template-columns:repeat(${cols},1fr)">${cells}</div>
      </div></div>`;
  }

  function sliderHtml(sec) {
    const def = SLIDERS[sec.ref] || {steps: []};
    const steps = def.steps || [];
    const sel = currentLower();
    const at = steps.findIndex(t => sel.has(t.toLowerCase()));
    const cells = steps.map((t, i) =>
      `<button type="button" class="ia-step${i === at ? ' on' : ''}"
        data-ax="slider" data-ref="${escHtml(sec.ref)}" data-val="${escHtml(t)}"
        title="${escHtml(tagTip(t))}" aria-pressed="${i === at}">${i + 1}</button>`).join('');
    const cur = at >= 0 ? steps[at] : '미지정';
    return `<div class="ia-ax-row"><span class="ia-ax-lbl">${escHtml(sec.label)}</span>
      <div class="ia-step-wrap"><div class="ia-steps">${cells}</div>
      <span class="ia-step-cur">${escHtml(cur)}</span></div></div>`;
  }

  /** 3열 그리드 박스 + 아코디언. 한 번에 하나의 썸네일 섹션만 펼친다(시각 소음 감소).
   *  펼친 섹션은 3줄 높이만 보이고 나머지는 박스 안에서 스크롤한다(우측 스크롤바). */
  function thumbHtml(sec) {
    const axis = sec.ref;
    const full = THUMB_TAGS[axis] || [];
    // 계층 탐색기가 없는 슬롯(자세)에서는 검색창이 **그리드를 거른다**. 트리를 떼고
    // 검색만 남겼으니 걸러줄 대상이 그리드여야 한다 — 아니면 죽은 입력창이 된다.
    const all = thumbFilter ? full.filter(t => matchesFilter(t)) : full;
    const sel = currentLower();
    const chosenCount = all.filter(t => sel.has(t.toLowerCase())).length;
    // 검색 중에는 결과가 있는 축을 모두 펼친다 — 아코디언 하나만 열면 다른 축의
    // 일치 항목을 찾을 수 없다.
    const open = thumbFilter ? all.length > 0 : openThumbAxis === axis;
    if (thumbFilter && !all.length) return {tab: '', pane: ''};
    // 탭 버튼(상단 그리드에 깔린다). 캐럿은 없앴다 — 접힘/펼침이 아니라 선택이다.
    const tab = `<button type="button" class="ia-axtab${open ? ' is-open' : ''}"
      data-acc-ax="${escHtml(axis)}" aria-selected="${open}">
      <span class="ia-axtab-name">${escHtml(sec.label)}</span>
      <span class="ia-acc-n">${thumbFilter ? `${all.length}/${full.length}` : all.length}</span>
      ${chosenCount ? `<span class="ia-acc-sel">${chosenCount}</span>` : ''}
    </button>`;
    if (!open) return {tab, pane: ''};
    const have = thumbHave.get(packAxisOf(axis)) || new Set();
    // 부모 태그(예: multicolored hair)는 하위 패턴이 선택된 동안 자동 배정 + 해제 불가.
    const rule = (AXIS_RULES || {})[axis] || {};
    const locked = rule.parent && parentLocked(axis) ? rule.parent.toLowerCase() : '';
    const cells = all.map(t => {
      const on = sel.has(t.toLowerCase());
      const isLocked = locked && t.toLowerCase() === locked;
      const media = have.has(t)
        ? `<img src="${escHtml(thumbUrl(axis, t))}" alt="" loading="lazy" decoding="async">`
        : '<span class="ia-cell-none">준비 중</span>';
      const sens = isSensitive(t);
      // 조언 플로트와 같은 두 번 클릭. 한 번 누르면 캡션이 `{태그} 추가/제외` 버튼이
      // 되고 한 번 더 눌러야 실행된다. 한 축이 최대 150칸이라 오클릭이 잦다.
      // 잠긴 셀(부모 자동 배정)은 어차피 해제가 안 되므로 예외로 둔다.
      // 행동은 호버 시 뜨는 버튼이 맡는다. 캡션은 **항상 태그 이름**이다 —
      // 이중 클릭 시절에는 캡션이 상태와 행동을 번갈아 맡아 읽기 어려웠다.
      const act = isLocked ? '' :
        `<span class="ia-cell-act" data-act="${on ? 'off' : 'on'}">${on ? '제거' : '선택'}</span>`;
      return `<div class="ia-cell${on ? ' on' : ''}${isLocked ? ' is-locked' : ''}${sens ? ' is-sensitive' : ''}"
        data-ax="thumb" data-ref="${escHtml(axis)}" data-val="${escHtml(t)}"
        aria-pressed="${on}" title="${escHtml(tagTip(t))}${isLocked ? ' (자동 · 해제 불가)' : ''}">
        <span class="ia-cell-img">${media}${sens ? '<span class="ia-cell-veil">보기</span>' : ''}${act}</span>
        <span class="ia-cell-cap">${isLocked ? '\u{1F512} ' : ''}${escHtml(t)}</span></div>`;
    }).join('');
    // 색 팔레트는 그리드 '위'에 둔다 — 아래에 두면 3줄 그리드에 가려 안 보인다.
    // 피부처럼 주 색상 팔레트 자체가 조건부인 축은 여기서 함께 렌더한다.
    const mainPal = sec.mainPalette && mainPaletteVisible(sec.mainPalette)
      ? paletteHtml({ref: sec.mainPalette, label: '피부 색'})
      : '';
    const extra = sec.extraPalette && extraPaletteVisible(sec.extraPalette)
      ? paletteHtml({ref: sec.extraPalette, label: '추가 색상'}, {extra: true})
      : '';
    return {tab, pane: `<div class="ia-ax-row is-open">
      <div class="ia-cell-wrap">${mainPal}${extra}
        <div class="ia-cell-grid" data-scroll-ax="${escHtml(axis)}">${cells}</div></div>
    </div>`};
  }

  function axisSectionsHtml() {
    const secs = panelContext?.sections;
    if (!Array.isArray(secs) || !secs.length) return '';
    // 팔레트·슬라이더는 축이 아니라 값 입력기라 탭에 넣지 않고 위에 그대로 둔다.
    const lead = secs.map(sec => {
      if (sec.kind === 'palette') return paletteHtml(sec);
      // palette_extra 는 독립 섹션이 아니라 패턴 썸네일 섹션 안(그리드 위)에 붙는다(thumbHtml).
      if (sec.kind === 'slider') return sliderHtml(sec);
      return '';   // browse 는 렌더하지 않는다 (트리는 아래 탐색 섹션이 담당)
    }).filter(Boolean).join('');
    const thumbs = secs.filter(sec => sec.kind === 'thumb').map(thumbHtml);
    const tabs = thumbs.map(x => x.tab).filter(Boolean).join('');
    const panes = thumbs.map(x => x.pane).filter(Boolean).join('');
    const body = lead
      + (tabs ? `<div class="ia-axtabs">${tabs}</div>` : '')
      + panes;
    // 검색 결과가 0건이어도 컨테이너는 남겨야 한다. refreshAxisSections 가 `#iaAxes` 를
    // outerHTML 로 갈아치우므로, 빈 문자열을 돌려주면 호스트가 사라져 검색어를 지워도
    // 되돌아오지 않는다.
    if (!body) {
      if (!thumbFilter) return '';
      return `<div class="ia-axes" id="iaAxes"><div class="ia-axes-empty">`
        + `${escHtml(thumbFilter)} — 맞는 태그가 없습니다.</div></div>`;
    }
    return `<div class="ia-axes" id="iaAxes">${body}</div>`;
  }

  function bindAxisSections() {
    const host = panelMount.querySelector('#iaAxes');
    if (!host) return;
    host.querySelectorAll('[data-ax]').forEach(el => {
      el.addEventListener('click', event => {
        event.stopPropagation();
        const {ax, ref, val} = el.dataset;
        if (ax === 'thumb') {
          // **[선택]/[제거] 버튼을 눌렀을 때만** 실행한다. 셀의 나머지(그림·이름)를
          // 눌러도 아무 일이 없다 — 한 축이 최대 150칸이라 그리드를 훑다 스치는
          // 클릭이 잦고, 그걸 막으려고 넣었던 이중 클릭은 오히려 불편했다.
          if (!event.target.closest('.ia-cell-act')) return;
          pickThumb(ref, val);                                   // 조합 가능(+부모 태그 규칙)
        }
        else if (ax === 'palette') setMainColor(ref, val);       // 주 색상 = 항상 하나
        else if (ax === 'palette_extra') toggleExtraColor(ref, val);  // 추가 색상 = n개
        else setExclusive(ax, ref, val);                         // 슬라이더는 축 내 배타
        refreshAxisSections();
      });
    });
    // 아코디언 헤더 — 누른 섹션만 펼치고 나머지는 접는다(같은 걸 누르면 접기).
    host.querySelectorAll('[data-acc-ax]').forEach(el => {
      el.addEventListener('click', event => {
        event.stopPropagation();
        const axis = el.dataset.accAx;
        openThumbAxis = (openThumbAxis === axis) ? null : axis;
        refreshAxisSections();
      });
    });
    // '메인 색상 : [ ]' 클릭 -> 주 색상 팔레트로 스크롤(팝업 본문이 스크롤 컨테이너).
    host.querySelectorAll('[data-goto-main]').forEach(el => {
      el.addEventListener('click', event => {
        event.stopPropagation();
        const ref = el.dataset.gotoMain;
        const target = host.querySelector(`[data-ax="palette"][data-ref="${ref}"]`);
        const row = target?.closest('.ia-ax-row');
        if (!row) return;
        row.scrollIntoView({behavior: 'smooth', block: 'center'});
        row.classList.add('is-flash');
        setTimeout(() => row.classList.remove('is-flash'), 900);
      });
    });
    // 스크롤 박스: 위치를 계속 기억해 재렌더(선택 토글) 때 위로 튀지 않게 한다.
    host.querySelectorAll('[data-scroll-ax]').forEach(box => {
      const axis = box.dataset.scrollAx;
      const saved = thumbScroll.get(axis);
      // `if (saved)` 였다가 **scrollTop 0 이 falsy** 라서, 맨 위에 있을 때만
      // 복원을 건너뛰고 scrollSelectedIntoView 가 돌았다. 첫 행 셀을 누르면
      // 스크롤이 살짝 내려가는 버그의 원인이다.
      if (saved !== undefined) box.scrollTop = saved;
      else scrollSelectedIntoView(box);      // 첫 렌더에 선택 항목이 있으면 거기로
      box.addEventListener('scroll', () => { thumbScroll.set(axis, box.scrollTop); }, {passive: true});
    });
  }

  /** 선택된 셀이 박스 밖이면 보이는 위치로 맞춘다(스크롤바 점프 없이). */
  function scrollSelectedIntoView(box) {
    const on = box.querySelector('.ia-cell.on');
    if (!on) return;
    const top = on.offsetTop - box.clientHeight / 2 + on.offsetHeight / 2;
    box.scrollTop = Math.max(0, top);
  }

  /** 방금 누른 셀이 스크롤 박스 안에 온전히 보이게 최소한만 움직인다.
   *
   *  한 번 누르면 캡션 자리가 `{태그} 추가` 버튼이 되는데, 그 셀이 박스 아래쪽에
   *  걸쳐 있으면 정작 그 버튼이 잘려 안 보인다. 무엇을 누르라는 건지 알 수 없다.
   *  화면 가운데로 끌어오지는 않는다 — 주변 셀을 훑던 시선이 끊긴다. */
  function ensureCellVisible(axis, val) {
    const box = panelMount.querySelector(`[data-scroll-ax="${cssEsc(axis)}"]`);
    if (!box) return;
    const cell = box.querySelector(`.ia-cell[data-val="${cssEsc(val)}"]`);
    if (!cell) return;
    const pad = 6;
    const over = (cell.offsetTop + cell.offsetHeight + pad)
      - (box.scrollTop + box.clientHeight);
    const under = box.scrollTop - (cell.offsetTop - pad);
    let next = box.scrollTop;
    if (over > 0) next += over;
    else if (under > 0) next -= under;
    if (next !== box.scrollTop) {
      box.scrollTop = Math.max(0, next);
      thumbScroll.set(axis, box.scrollTop);   // 재렌더 때 되돌아가지 않게
    }
  }

  /** querySelector 용 이스케이프. 태그에 따옴표·괄호가 들어간다(`pom pom (clothes)`). */
  function cssEsc(v) {
    return window.CSS && CSS.escape ? CSS.escape(v) : String(v).replace(/["\\]/g, '\\$&');
  }

  /** 축 영역만 다시 그린다 — 검색창/브라우저는 건드리지 않는다.
   *  outerHTML 교체는 스크롤 박스를 새로 만들므로 위치를 먼저 저장한다. */
  function refreshAxisSections() {
    const host = panelMount.querySelector('#iaAxes');
    if (!host) return;
    host.querySelectorAll('[data-scroll-ax]').forEach(box => {
      thumbScroll.set(box.dataset.scrollAx, box.scrollTop);
    });
    host.outerHTML = axisSectionsHtml();
    bindAxisSections();
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
  function toggleTag(tag, opts = {}) {
    const normalized = String(tag || '').trim();
    if (!normalized) return;
    // 조언 플로트의 추천 기준. **플로트에서 고를 때는 바꾸지 않는다** —
    // 기준이 따라 움직이면 목록이 통째로 갈려서 방금 넣은 것을 되돌릴 수 없다.
    // 기준은 그리드·탐색기에서 고른 것으로만 바뀐다.
    if (!opts.fromAside) lastPicked = normalized;
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
    if (!active) {
      closePositionPicker(); closePanel();
      // 모드를 끄면 씬 버튼 줄도 사라져야 한다 — blocksMount 만 숨기면 플로트가 남는다.
      if (sceneMount) { sceneMount.classList.remove('open'); sceneMount.innerHTML = ''; }
    } else { renderBlocks(); void probeStatus(); }
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
      document.body.classList.remove('interactive-editing');
      if (posPopup) { posPopup.remove(); posPopup = null; }
      blocksMount.innerHTML = '';
      panelMount.classList.remove('open');
      panelMount.style.top = panelMount.style.left = panelMount.style.width = '';
      panelMount.innerHTML = '';
    },
  };
}
