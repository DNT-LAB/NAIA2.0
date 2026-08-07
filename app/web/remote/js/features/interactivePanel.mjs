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
  CLOTH_COMBO, CLOTH_COMBO_REV, COLOR_SWATCH, AXIS_COLOR_TAGS, ADULT_SECTIONS, GLOSS_TAGS,
  VIEW_SECTIONS, META_SECTIONS, VIEW_GLOBAL_TAGS, GAZE_TARGETS,
} from './interactiveAxes.mjs?v=20260804-ax138';

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
  // 전에는 `subgroupInclude` 만 준 탐색기(트리)였다 — 그림이 한 장도 없었기 때문이다.
  // 2026-08-01 에 `view_*` 3축 80장을 만들어 그리드가 섰다. 트리는 그리드가 못 덮는
  // 나머지를 위해 남긴다(구도 서브그룹 292개 중 그림은 freq>=300 인 80개뿐이다).
  {id: 'composition', name: '구도', icon: '\u{1F5BC}', axis: 'meta',
   sections: VIEW_SECTIONS, subgroupInclude: COMPOSITION_PRIMARY},
  // 썸네일이 없는 meta 태그만 담는 트리. `effects`/`symbols`/`colors` 는 fx 축
  // 483장이 이미 덮으므로(실측 482/483 중복) 빼야 '효과' 슬롯이 둘로 보이지 않는다.
  // scan/year_tags/quality/art_style 과 1개짜리 오분류는 그림에 영향이 없다.
  // 여기도 트리뿐이었다. 사용자가 "의외로 다 구분이 가능하다"고 지적해(2026-08-01)
  // `meta_*` 4축 154장을 만들었다. 트리는 나머지(고유명·계정·화풍 등 그림으로 구분이
  // 안 되는 것들)를 위해 남긴다.
  {id: 'composition_fx', name: '기타·텍스트', icon: '\u{1F524}', axis: 'meta',
   sections: META_SECTIONS,
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
  // 성인 도감 8축. 캐릭터 슬롯(신체/의상/자세)에도 성격별로 들어가 있지만, 여기는
  // **베이스 프롬프트**로 나간다 — 사물 슬롯이 캐릭터/씬 양쪽에 있는 것과 같은 구조다.
  // 슬롯 이름이 이미 '성인'이라 탭에는 `(성인)` 을 안 붙인다.
  {id: 'adult', name: '성인', icon: '\u{1F51E}', axis: 'meta', sections: ADULT_SECTIONS},
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
  // 행은 **위쪽도 막는다.** 예전에는 아래만 봐서 `Z9` 같은 값이 들어오면 y=1.7 이
  // 그대로 NAI 로 나갔다(옛 저장분·손편집에서 실제로 만들 수 있다).
  // 0.1 단위로 반올림하는 것은 core/api_service.py 의 표(0.1~0.9)와 정확히 맞추기
  // 위해서다 — 부동소수 그대로면 0.30000000000000004 가 생성 정보에 찍힌다.
  const f = i => (!Number.isInteger(i) || i < 0 || i > 4 ? 0.5 : Math.round((0.1 + i * 0.2) * 10) / 10);
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
// 캐릭터 태그(`hatsune miku`)가 들어가는 슬롯. **어느 축에도 속하지 않는다** —
// 썸네일 축 태그 10,103개에 캐릭터는 0개라 자명한 자리가 없다. 그래서 맨 앞에 전용 슬롯을 둔다:
//   · `buildCharPrompt` 가 CHAR_SUBS 순서대로 이어 붙이므로 **캐릭터 태그가 맨 앞에 온다.**
//     NAI 캐릭터 프롬프트가 `girl, hatsune miku, ...` 이길 원하는 자리이고,
//     캐릭터 뷰어의 `build_prompt` 도 같은 순서로 만든다.
//   · 칩 표시·개수·요약·프리셋 회수가 다른 슬롯과 똑같이 공짜로 따라온다.
//     캐릭터 헤더에 따로 두면 그 UI 를 전부 새로 만들어야 한다.
// 입력은 다른 슬롯과 똑같다 — 인라인 입력창에 직접 치면 되고 자동완성이 캐릭터 태그를
// 이미 안다. 이름을 아는 캐릭터는 그냥 타이핑하고, 찾아봐야 할 때만 줄 오른쪽
// `[프리셋 선택]` 으로 검색 팝업을 연다.
// 다만 **옆 팝업(축 그리드/분류 탐색)은 띄우지 않는다**(`noPanel`) — 캐릭터는 축이 없어
// 그릴 그리드가 없고, 분류 탐색의 SLOT_GROUPS(core/interactive_browse_index.py)에도
// `character` 가 없어 빈 트리만 뜬다. 빈 상자를 띄우느니 입력창만 연다.
const CHAR_TAG_SLOT = '캐릭터';

// ALT — `alternate *` 계열. **그리드에 넣지 않는다.** 이것들은 "원작/공식과 다르다"는
// 관계형 태그라 그림 한 장으로는 서로 구분이 안 된다(`alternate costume` 을 찍으면
// 그냥 아무 의상이 나오고 `alternate hairstyle` 칸과 똑같아 보인다). 그런데 **프롬프트
// 로서는 값이 크다** — 캐릭터 태그와 같이 쓰면 NAI 가 "정규 설정에서 벗어나라"는 신호로
// 받는다(`alternate costume` 244,073건). 그래서 그림 대신 체크 목록으로 준다.
//
// 캐릭터 태그 바로 뒤에 들어간다. 어느 캐릭터의 변주인지가 붙어 있어야 의미가 산다.
const ALT_OPTIONS = [
  // 의상
  {g: '의상', tag: 'alternate costume', label: '비공식 의상', n: 244073},
  {g: '의상', tag: 'official alternate costume', label: '공식 다른버전 의상', n: 194610},
  {g: '의상', tag: 'cosplay', label: '다른 캐릭터 코스프레', n: 72527},
  {g: '의상', tag: 'adapted costume', label: '각색 의상', n: 29856},
  // 머리
  {g: '머리', tag: 'alternate hairstyle', label: '비공식 헤어스타일', n: 60753},
  {g: '머리', tag: 'official alternate hairstyle', label: '공식 다른버전 머리스타일', n: 19513},
  {g: '머리', tag: 'alternate hair length', label: '비공식 머리길이', n: 12425},
  {g: '머리', tag: 'official alternate hair length', label: '공식 다른버전 머리길이', n: 6167},
  {g: '머리', tag: 'alternate hair color', label: '비공식 머리색', n: 7531},
  {g: '머리', tag: 'alternate hair ornament', label: '비공식 머리장식', n: 655},
  // 색·신체
  {g: '색·신체', tag: 'alternate breast size', label: '비공식 가슴크기', n: 26907},
  {g: '색·신체', tag: 'alternate color', label: '비공식 전체 색', n: 11383},
  {g: '색·신체', tag: 'alternate eye color', label: '비공식 눈색', n: 8848},
  // 나이
  {g: '나이', tag: 'aged down', label: '어리게', n: 31928},
  {g: '나이', tag: 'aged up', label: '성숙하게', n: 13576},
];
const ALT_LABEL = new Map(ALT_OPTIONS.map(o => [o.tag, o.label]));
const GAZE_LABEL = new Map(GAZE_TARGETS.map(o => [o.tag, o.label]));

const CHAR_SUBS = [
  {key: CHAR_TAG_SLOT, icon: '\u{1F3AD}', axis: 'character', noPanel: true},
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
  // 이 캐릭터가 어떻게 잡히나 — 프레이밍·시점·시선. 씬 '구도' 슬롯과 **같은 축을
  // 쓰지만 들어가는 자리가 다르다**(캐릭터 프롬프트 vs 베이스 프롬프트). '사물'이
  // 씬과 캐릭터 양쪽에 있는 것과 같은 구조다.
  //
  // 여러 명일 때 의미가 산다 — `from behind` 를 char_caption 에 넣으면 그 캐릭터만
  // 뒤돌아본다. 1명이면 씬 슬롯과 결과가 같다.
  // Dev0714 는 시선만 캐릭터에 뒀는데(각도·샷은 씬 전용), 여기서는 축을 그대로
  // 공유하고 어디에 넣을지는 사용자가 고르게 한다.
  {key: '구도', icon: '\u{1F5BC}', axis: 'meta', sections: VIEW_SECTIONS,
   // 이미지 전체에만 걸리는 태그는 뺀다(`isometric`·`female pov`·`multiple views` …).
   // 씬 슬롯에는 그대로 있으니 못 쓰게 되는 것은 없다.
   excludeTags: VIEW_GLOBAL_TAGS},
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
  // 캐릭터 목록이 바뀌면 알린다(Assets 바의 캐릭터 스택이 구독).
  onRosterChange = () => {},
  queryCorpus = null,          // async ({rating, person, include, exclude, search, limit}) => payload
  // (`corpusStatus` 는 더 이상 쓰지 않는다. 이벤트 코퍼스가 없을 때 빨간 토스트를
  //  띄우는 것이 유일한 용도였는데, 그 상태를 읽는 코드가 하나도 없었고 토스트는
  //  Interactive 를 켤 때마다 축 탭을 가렸다. 동반 추천의 출처도 이제 코퍼스가
  //  아니라 게시물 원본이라 경고 자체가 사실과 맞지 않는다. app.js 가 계속 넘기므로
  //  인자는 남겨 둔다 — 나중에 진짜 상태 표시가 필요해지면 여기서 받으면 된다.)
  corpusStatus = null,         // async () => payload  (미사용)
  autocomplete = null,         // createInteractiveAutocomplete() 인스턴스 (미사용 — 팝업 검색은 자동완성 없음)
  bindTagAssist = null,        // (textarea, options) => void : 범용 자동완성을 슬롯 입력창에 바인딩
  getAutocompleteTarget = () => null,  // () => 현재 자동완성이 열린 textarea | null
  getMode = () => 'NAI',       // () => 'NAI' | 'WEBUI' | 'COMFYUI' — 캐릭터 성별 주입 분기
  // 프롬프트 엔지니어링 모듈 상태(`pre_prompt`/`post_prompt`). 베이스 프롬프트의
  // 선행·후행이 여기서 온다 — 없으면 인원 + 글로벌만 나간다.
  getPromptEngineering = () => null,
  // 반응형 생성. `isGenerating()` 이 true 면 변화를 모았다가 끝난 뒤 한 번 낸다.
  isGenerating = () => false,
  requestGeneration = () => {},
  showToast = () => {},
  onCharReference = null,      // () => void — 세션 CR 모듈 열기(없으면 버튼을 안 낸다)
  getCharacterReferenceState = () => null,   // () => {frames:[{is_enabled}], is_naid45} | null
} = {}) {
  if (!blocksMount || !panelMount) {
    return {isActive: () => false, setActive: () => {}, destroy: () => {}};
  }

  let active = false;
  let openId = null;
  /** 씬 슬롯의 빈 상태. **손으로 적지 않는다** — 예전에는 4축만 적혀 있었고
   *  나머지 4축(동물·효과기호·다인원 자세·성인)은 키가 아예 없었다. 그 탓에
   *  `importState` 가 초기 키만 훑어 저장해 둔 태그를 못 살렸고, 곧이어 빈 값으로
   *  다시 저장해 **원본까지 지웠다**(실측: 심어 둔 cat/sparkle/hug 가 새로고침
   *  한 번에 사라지고 저장값이 비었다). 목록에서 파생하면 축을 더해도 안 샌다. */
  function emptySceneSlots() {
    return Object.fromEntries(SCENE_SLOTS.map(slot => [slot.id, []]));
  }

  let queryToken = 0;
  let charSeq = 0;             // 캐릭터 고유 id 카운터(삭제해도 재사용 안 함 → id 충돌/stale panelContext 방지)

  const state = {
    rating: 's',
    person: '1girl_solo',
    chars: [newCharacter(true)],
    slots: emptySceneSlots(),
    // 어느 축에도 속하지 않는 자유 입력. **문자열 그대로** 둔다 — 태그로 쪼갰다가
    // 다시 이으면 사용자가 적은 공백·가중치·쉼표가 손상된다.
    freeText: '',
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
      // 이 슬롯에 적용된 캐릭터 프리셋과 **그때 이 프리셋이 넣은 태그**.
      // 다른 캐릭터로 갈아탈 때 이것만 정확히 회수한다(사용자가 손으로 넣은 것은 남긴다).
      // 캐릭터 슬롯마다 독립이라 C1/C2 가 서로 다른 캐릭터를 가질 수 있다.
      preset: null,      // null | {work, name, tags: {슬롯키: [태그...]}}
      // ALT — 켠 `alternate *` 태그. 캐릭터마다 독립이다(C1 만 aged down 이 가능해야 한다).
      alt: [],
      // 대상 시선. 썸네일이 없어 그리드가 아니라 체크 목록으로 고른다.
      gaze: [],
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
  /** 베이스 프롬프트 = **인원 + 선행 + 글로벌 + 후행**(사용자 지정 순서).
   *
   *  선행·후행은 프롬프트 엔지니어링 모듈의 값이다. 백엔드에서 붙일 수 없는 이유는
   *  PE 가 `post_processing` 파이프라인 훅이고 그 파이프라인은 Random 경로에서만
   *  돌기 때문이다 — Interactive 는 렌더한 프롬프트를 곧장 보내므로 훅을 못 탄다.
   *  여기서 조립하면 **입력창에 보이는 것과 실제로 나가는 것이 같아진다**(생성 정보에
   *  `1girl` 만 찍히던 이유가 그 어긋남이었다).
   *  네거티브는 기존 값을 그대로 쓴다 — 여기서 손대지 않는다. */
  function renderPrompt() {
    const parts = [];
    for (const slot of SCENE_SLOTS) {
      // 구도는 3축 콤보 태그를 자유 태그 앞에 붙인다.
      if (slot.id === 'composition') parts.push(...compTags(state.composition));
      parts.push(...(state.slots[slot.id] || []));
    }
    const pe = (typeof getPromptEngineering === 'function' && getPromptEngineering()) || {};
    // 자유 입력은 글로벌 뒤·후행 앞. 파싱해서 다시 잇지 않고 원문을 그대로 넣는다.
    return [genderCountPrefix(), String(pe.pre_prompt || '').trim(),
            parts.join(', '), String(state.freeText || '').trim(),
            String(pe.post_prompt || '').trim()]
      .map(v => v.replace(/^\s*,|,\s*$/g, '').trim())
      .filter(Boolean).join(', ');
  }

  /** 캐릭터 프롬프트. NAI 모드면 특징 앞에 girl/boy 주입(이미 명시적 girl/boy 있으면 생략). */
  function buildCharPrompt(c) {
    // ALT 는 캐릭터 태그 **바로 뒤**에 넣는다. 맨 뒤로 밀면 어느 캐릭터의 변주인지
    // 흐려지고, NAI 는 앞쪽 토큰을 더 강하게 받는다.
    const alt = (c.alt || []).filter(t => ALT_LABEL.has(t));
    // 대상 시선은 '구도' 슬롯 뒤에 붙인다 — 같은 종류(어떻게 보이나)라 붙어 있어야 한다.
    const gaze = (c.gaze || []).filter(t => GAZE_LABEL.has(t));
    const base = CHAR_SUBS.flatMap(s => {
      const own = (c.fields[s.key] || []).join(', ');
      const add = s.key === CHAR_TAG_SLOT ? alt : (s.key === '구도' ? gaze : []);
      return [own, ...add];
    }).filter(Boolean).join(', ');
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
  /** 생성에 **실제로 나가는** 캐릭터들. 공유 캔버스의 칩도, 좌표 전송도 이 하나를 본다.
   *  전에는 UI 조건이 `state.chars.length > 1` 이라 슬롯이 2개면 Position 버튼이 떴는데
   *  그중 하나가 OFF/빈 칸이면 여기서 center 가 통째로 빠졌다 — 보이는데 안 실리는 상태.
   *  목록을 하나로 합쳐 두 조건이 갈라질 수 없게 한다. */
  function positionedChars() {
    const out = [];
    for (const c of state.chars) {
      if (c.state !== 'active' || !charHasTags(c)) continue;
      if (!buildCharPrompt(c)) continue;
      out.push(c);
      if (out.length >= MAX_NAI_CHARACTERS) break;
    }
    return out;
  }

  function generationCharacters() {
    const members = positionedChars();
    // **1명이면 좌표를 보내지 않는다.** 캔버스 위치는 여러 명을 갈라 놓기 위한 것이라
    // 혼자일 때는 의미가 없다. 캔버스도 같은 조건으로 감춘다 — 같은 목록을 쓰므로
    // 갈라질 수 없다.
    // 주의: 이것이 곧 'AI Choice' 는 **아니다.** 백엔드가 char_captions 의 centers 를
    // 빈 자리에서 0.5/0.5 로 채운다(api_service.py `default_center`) — 그래서 혼자여도
    // 중앙 좌표는 결국 나간다. 여기서 정하는 것은 '사용자가 좌표를 정했는가'까지다.
    const withCenter = members.length > 1;
    // 캐릭터별 네거티브 UI 는 아직 없어 uc 는 빈 문자열. center 는 NAI V4 전용.
    return members.map(c => withCenter
      ? {prompt: buildCharPrompt(c), uc: '', center: posCenters(c.pos)}
      : {prompt: buildCharPrompt(c), uc: ''});
  }

  function emitChange() {
    reactiveOnChange();
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

  /** `del` 이 있으면 칩 오른쪽에 작은 [×] 를 붙인다 — 그 태그 하나만 빼는 길이다.
   *  예전에는 슬롯을 열어 텍스트를 고치거나 그리드에서 같은 칸을 다시 눌러야 했다. */
  function chip(text, cls, title, del) {
    const titleAttr = title ? ` title="${escHtml(title)}"` : '';
    const x = del
      ? `<button type="button" class="ia-chip-x" data-chip-del="${escHtml(text)}"
           tabindex="-1" aria-label="${escHtml(text)} 제거" title="빼기">&times;</button>`
      : '';
    return `<span class="ia-chip${cls ? ' ' + cls : ''}"${titleAttr}>` +
      `<span class="ia-chip-t">${escHtml(text)}</span>${x}</span>`;
  }

  /** opts.del      — 칩마다 [×] 를 단다(실제 태그 배열을 가진 슬롯에서만).
   *  opts.delFrom  — 이 인덱스부터만 [×] 를 단다. 구도 슬롯은 앞쪽에 3축 콤보에서
   *                  파생된 **표시용 라벨**이 붙고 그 뒤에 자유 태그가 온다 —
   *                  파생 칩은 지울 대상이 없으므로(콤보를 되돌려야 한다) 건너뛴다.
   *  opts.emphasis — 여기 든 태그는 한 단계 더 강조한다(캐릭터 슬롯의 **이름** 태그). */
  function chipRow(tags, opts = {}) {
    if (!tags || !tags.length) return '<span class="ia-chip-empty">비어 있음</span>';
    const emph = opts.emphasis;
    const from = opts.delFrom || 0;
    const shown = tags.slice(0, MAX_CHIPS).map((t, i) => {
      // 문장 칩은 전체 텍스트를 title 로(호버 확인)
      let cls = isProseChip(t) ? 'is-prose' : '';
      if (emph && emph.has(String(t).toLowerCase())) cls += (cls ? ' ' : '') + 'is-name';
      return chip(t, cls, isProseChip(t) ? t : '', opts.del && i >= from);
    });
    // `+n` 은 실제 태그가 아니라 접힘 표시다 — 지울 대상이 없으므로 [×] 를 달지 않는다.
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
  function slotBody(editing, tags, opts) {
    if (editing) {
      // 전체 태그를 쉼표 문자열로 직접 편집. 숙련자 직접 입력용.
      return `<textarea class="ia-slot-input" data-slot-input="1" rows="1" spellcheck="false" placeholder="태그 입력 (쉼표로 여러 개)">${escHtml(tags.join(', '))}</textarea>`;
    }
    return `<div class="ia-block-chips">${chipRow(tags, opts)}</div>`;
  }

  function sceneBlockHtml(slot) {
    const tags = state.slots[slot.id] || [];
    const editing = isEditing('scene', slot.id);
    // 구도 블록 미리보기(비편집)엔 3축 콤보 칩을 자유 태그 앞에 함께 보인다.
    const derived = slot.id === 'composition' ? compChips(state.composition) : [];
    const chipTags = derived.length ? [...derived, ...tags] : tags;
    const countN = editing ? tags.length : chipTags.length;
    // 파생 칩(구도 콤보)은 앞쪽에 오고 뒤가 자유 태그다 — 뒤쪽부터만 [×] 를 단다.
    const body = editing
      ? slotBody(true, tags)
      : `<div class="ia-block-chips">${chipRow(chipTags, {del: true, delFrom: derived.length})}</div>`;
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

  /** `[ALT n]` 버튼. 0개면 숫자 없이 `ALT` 만. 툴팁에 켠 것을 전부 적는다 —
   *  버튼이 좁아 이름을 못 보여주므로 호버가 유일한 확인 수단이다. */
  function altButtonHtml(c) {
    const on = (c.alt || []).filter(t => ALT_LABEL.has(t));
    const tip = on.length
      ? '적용 중: ' + on.map(t => `${ALT_LABEL.get(t)}(${t})`).join(' · ')
      : '원작과 다른 버전 — 의상·머리·나이 등을 공식 설정에서 벗어나게 합니다';
    return `<button type="button" class="ia-char-alt${on.length ? ' is-on' : ''}"
      data-charalt data-cid="${c.id}" title="${escHtml(tip)}"
      >ALT${on.length ? ` <b>${on.length}</b>` : ''}</button>`;
  }

  /** `[시선 n]` 버튼. ALT 와 같은 규칙 — 버튼이 좁아 이름은 툴팁이 맡는다. */
  function gazeButtonHtml(c) {
    const on = (c.gaze || []).filter(t => GAZE_LABEL.has(t));
    const tip = on.length
      ? '적용 중: ' + on.map(t => `${GAZE_LABEL.get(t)}(${t})`).join(' · ')
      : '누구를 보는가 — 썸네일로 구분되지 않아 목록에서 고릅니다';
    return `<button type="button" class="ia-char-gaze${on.length ? ' is-on' : ''}"
      data-chargaze data-cid="${c.id}" title="${escHtml(tip)}"
      >시선${on.length ? ` <b>${on.length}</b>` : ''}</button>`;
  }

  /** 캐릭터 슬롯에서 **진짜 이름**인 태그. 프리셋은 이름과 작품을 같이 넣는데
   *  (`gotoh hitori`, `bocchi the rock!`) 둘이 같은 모양이라 어느 쪽이 캐릭터인지
   *  구분이 안 됐다. 이름 쪽만 한 단계 더 강조한다. */
  function nameEmphasis(c) {
    const out = new Set();
    const add = v => { const s = String(v || '').trim().toLowerCase(); if (s) out.add(s); };
    add(c.preset?.name);
    add(c.name);
    return out.size ? out : null;
  }

  /** 헤더의 좌표 표시. 예전엔 `Position C3` 텍스트라 90px 을 먹었는데, 배치는 이제
   *  공유 캔버스가 맡으므로 여기서는 **어디 있는지만** 보이면 된다. 미니맵 점 + 코드로
   *  줄여 자리를 벌고, 눌러서 여는 5x5 팝업은 폴백으로 남긴다. */
  function posDotHtml(c) {
    const pos = c.pos || POS_DEFAULT;
    const ci = Math.max(0, POS_COLS.indexOf(pos[0]));
    const ri = Math.max(0, Number(pos[1]) - 1);
    return `<button type="button" class="ia-char-pos" data-charpos data-cid="${escHtml(c.id)}"
      title="캔버스 위치 ${pos} · ${posText(pos)} — 눌러서 좌표 팝업">
      <span class="ia-char-posmap"><span class="ia-char-posdot"
        style="left:${(ci + 0.5) * 20}%;top:${(ri + 0.5) * 20}%"></span></span>
      <span class="ia-char-poscode">${pos}</span></button>`;
  }

  /** 헤더의 캐릭터 프리셋 버튼. **슬롯 안에 있던 것을 여기로 옮긴 것**이다 —
   *  캐릭터 슬롯 줄은 `[칩들] [프리셋 이름] [ALT] [×]` 로 비좁았고, 게다가 이름이
   *  칩과 버튼에 **두 번** 나왔다(`akemi homura` 가 나란히 둘, 사용자 지적).
   *  여기서는 라벨을 `캐릭터` 로 고정한다 — 이름을 다시 적으면 중복이 되살아난다.
   *  적용된 프리셋은 강조 테두리와 툴팁이 알린다. 접힌 카드에서도 바로 눌린다. */
  function headPresetHtml(c) {
    const tip = c.preset
      ? `${c.preset.name} · ${c.preset.work} — 눌러서 다른 캐릭터로 바꿉니다`
      : '캐릭터 프리셋 검색 — 이름·작품·태그로 찾아 대표 태그까지 한 번에 채웁니다';
    return `<button type="button" class="ia-char-hpreset${c.preset ? ' has-preset' : ''}"
      data-charpreset data-cid="${escHtml(c.id)}"
      title="${escHtml(tip)}"><span class="ia-char-hpreset-i">\u{1F464}</span>캐릭터</button>`;
  }

  /** 이 앱은 native `title` 을 `data-naia-title`(+ aria-label)로 걷어간다(app.js `adoptTitle`).
   *  두 번째부터는 이미 있는 aria-label 을 덮지 않으므로, 갱신할 때는 셋 다 직접 맞춘다. */
  function setTip(el, text) {
    if (!el) return;
    el.dataset.naiaTitle = text;
    el.setAttribute('aria-label', text);
    el.removeAttribute('title');
  }

  /** 헤더 미니맵의 점과 코드를 제자리에서 옮긴다. renderBlocks 를 부르면
   *  편집 중 textarea 가 통째로 다시 만들어져 포커스와 팝업이 날아간다. */
  function refreshPosDot(cid) {
    const card = blocksMount.querySelector(`.ia-char[data-cid="${CSS.escape(cid)}"]`);
    const btn = card && card.querySelector('[data-charpos]');
    const c = state.chars.find(x => x.id === cid);
    if (!btn || !c) return;
    const pos = c.pos || POS_DEFAULT;
    const dot = btn.querySelector('.ia-char-posdot');
    const code = btn.querySelector('.ia-char-poscode');
    if (dot) {
      dot.style.left = (Math.max(0, POS_COLS.indexOf(pos[0])) + 0.5) * 20 + '%';
      dot.style.top = (Math.max(0, Number(pos[1]) - 1) + 0.5) * 20 + '%';
    }
    if (code) code.textContent = pos;
    setTip(btn, `캔버스 위치 ${pos} · ${posText(pos)} — 눌러서 좌표 팝업`);
  }

  /** 좌표 UI 를 받는 구성원 지문. ON/OFF 나 태그 추가는 카드 하나만 제자리로 고치는데,
   *  대상이 늘거나 줄면 그것만으로는 모자라 헤더의 좌표 점이 거짓말을 한다(껐는데 점이 남는다).
   *  구성이 실제로 바뀐 경우에만 블록을 다시 그린다 — 매번 그리면 편집 중 슬롯이 흔들린다. */
  function posSignature() {
    const isNai = String(getMode() || '').toUpperCase() === 'NAI';
    const members = isNai ? positionedChars() : [];
    return members.length > 1 ? members.map(c => c.id).join(',') : '';
  }
  let lastPosSig = null;

  function syncPosMembership() {
    if (posSignature() === lastPosSig) return false;
    renderBlocks();   // renderBlocks 가 지문을 다시 찍는다
    return true;
  }

  function charBlockHtml() {
    // Position(캔버스 좌표)은 NAI V4 char_captions 전용이라 NAI 모드에서만 노출한다.
    const isNai = String(getMode() || '').toUpperCase() === 'NAI';
    // 좌표 UI 는 **좌표가 실제로 나갈 때만** 보인다(positionedChars 참조).
    const members = isNai ? positionedChars() : [];
    const showPos = members.length > 1;
    const posIds = new Set(members.map(c => c.id));
    const rows = state.chars.map((c, i) => {
      const summary = CHAR_SUBS.flatMap(s => c.fields[s.key] || []).join(', ') || '(비어 있음)';
      const subs = CHAR_SUBS.map(s => {
        const tags = c.fields[s.key] || [];
        const editing = isEditing('char', c.id, s.key);
        // 프리셋 **선택** 버튼은 헤더로 옮겼다(headPresetHtml) — 여기 두면 칩과 이름이
        // 겹쳐 보이고 칩 자리를 좁힌다. 슬롯에는 이 슬롯을 되돌리는 [×] 와 ALT 만 남긴다.
        // '구도' 슬롯은 개수 배지 자리에 시선 버튼을 함께 둔다 — 같은 질문이라
        // 한 줄에서 끝나야 한다(다른 줄을 만들면 캐릭터 카드가 또 길어진다).
        const meta = s.key === '구도'
          ? gazeButtonHtml(c) + `<span class="ia-block-count">${tags.length || ''}</span>`
          : s.key === CHAR_TAG_SLOT
          ? altButtonHtml(c)
            + (c.preset
              ? `<button type="button" class="ia-char-preset-x" data-charpresetclear data-cid="${c.id}"
                  aria-label="프리셋 되돌리기"
                  title="${escHtml(`${c.preset.name} 프리셋이 넣은 태그만 되돌립니다`)}">&times;</button>`
              : '')
          : `<span class="ia-block-count">${tags.length || ''}</span>`;
        return `<div class="ia-sub-block${editing ? ' is-editing' : ''}${tags.length ? '' : ' is-empty'}" data-cid="${c.id}" data-sub="${s.key}">
          <div class="ia-block-label">
            <span class="ia-block-title"><span class="ia-block-icon">${s.icon}</span><span class="ia-block-name">${escHtml(subLabel(s))}</span></span>
            <span class="ia-block-axis">${s.axis}</span>
          </div>
          ${slotBody(editing, tags, {del: true, emphasis: s.key === CHAR_TAG_SLOT ? nameEmphasis(c) : null})}
          <div class="ia-block-meta">${meta}</div>
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
          ${headPresetHtml(c)}
          ${showPos && posIds.has(c.id) ? posDotHtml(c) : ''}
          <button type="button" class="ia-char-dup" data-chardup data-cid="${cid}"
            aria-label="캐릭터 복제" title="이 캐릭터를 그대로 복제합니다 (위치는 빈 칸으로)">&#10697;</button>
          ${canDelete ? `<button type="button" class="ia-char-del" data-chardel data-cid="${cid}" aria-label="캐릭터 삭제" title="이 캐릭터 슬롯 삭제">&times;</button>` : ''}
          <span class="ia-char-spring"></span>
          <button type="button" class="ia-char-state ${c.state}" data-charenable data-cid="${cid}" aria-pressed="${enabled}" title="${enabled ? '비활성화 (생성에서 제외)' : '활성화'}">${enabled ? 'ACTIVE' : 'OFF'}</button>
          <!-- 한 줄로 잘린다(CSS) — 전체는 title 로 본다. -->
          <span class="ia-char-sum" title="${escHtml(summary)}">${escHtml(summary)}</span>
        </div>
        <div class="ia-char-body">
          ${subs}
        </div>
      </div>`;
    }).join('');

    const activeCount = state.chars.filter(c => c.state === 'active').length;
    return `<div class="ia-block is-character" data-slot="character">
      <div class="ia-cblock-head">
        <span class="ia-block-icon">\u{1F464}</span>
        <span class="ia-block-name">캐릭터</span>
        <!-- '2 활성' 은 제목 **바로 옆**이다. 오른쪽 끝에 Reference 와 나란히 뒀더니
             그 버튼의 부제처럼 보여, 무엇이 2개인지 헷갈렸다(사용자 지적). -->
        <span class="ia-block-count">${activeCount} 활성</span>
        <span style="flex:1"></span>
        ${isNai ? charRefButtonHtml() : ''}
      </div>
      ${rows}
      <div class="ia-char-foot"><button type="button" class="ia-charcard-add" data-add-char="1">+ 캐릭터 슬롯</button></div>
    </div>`;
  }

  // 씬 버튼을 담는 플로트. 좁은 창에서는 blocksMount 안으로 되돌린다.
  let sceneMount = null;
  const SCENE_FLOAT_MIN = 1180;   // 이 아래는 옆에 자리가 없다

  // ---- 반응형 생성 -------------------------------------------------------
  // 슬롯을 만질 때마다 알아서 다시 그린다. 태그를 **뺐을 때도** 반응한다 —
  // 무엇을 지웠을 때 그림이 어떻게 달라지는지 보는 것이 이 기능의 절반이다.
  //
  // 생성 중에 여러 개를 바꾸면 **큐에 쌓지 않고 하나로 모은다.** 쌓으면 손이 멈춘 뒤에도
  // 남은 만큼 계속 돌아 Anlas 를 태운다 — 마지막 상태 한 장만 필요하다.
  let reactive = false;
  let reactivePending = false;      // 생성 중에 바뀐 것이 있나(개수는 세지 않는다)
  let reactiveLastPrompt = '';
  let reactiveTypingSlot = null;   // 지금 타이핑 중인 슬롯 입력창

  // 툴팁은 여러 줄이다. 이 앱은 native `title` 을 `data-naia-title` 로 걷어가
  // 자체 툴팁으로 그린다(app.js `adoptTitle`) — 그래서 렌더 뒤 title 을 넣어도
  // 곧 지워진다(실측). 처음부터 그 시스템의 규약대로 넣는다.
  const REACTIVE_TIP = [
    '슬롯을 바꿀 때마다 자동으로 생성합니다.',
    '태그를 뺐을 때도 반응합니다.',
    '생성 중에 여러 개를 바꾸면 큐에 쌓지 않고 마지막 상태 한 번만 생성합니다.',
  ].join(String.fromCharCode(10));

  function reactiveToggleHtml() {
    return '<button type="button" class="ia-reactive' + (reactive ? ' is-on' : '') + '"' +
      ' data-ia-reactive="1" role="switch" aria-checked="' + (reactive ? 'true' : 'false') + '">' +
      '<span class="ia-reactive-box">' + (reactive ? '✓' : '') + '</span> 반응형 생성</button>';
  }

  /** 렌더 직후 툴팁을 붙인다. */
  function applyReactiveTip() {
    const btn = sceneMount && sceneMount.querySelector('[data-ia-reactive]');
    if (!btn) return;
    btn.dataset.naiaTitle = REACTIVE_TIP;
    btn.setAttribute('aria-label', REACTIVE_TIP);
  }

  function setReactive(next) {
    reactive = !!next;
    reactivePending = false;
    reactiveLastPrompt = reactiveSignature();
    const btn = sceneMount && sceneMount.querySelector('[data-ia-reactive]');
    if (btn) {
      btn.classList.toggle('is-on', reactive);
      btn.setAttribute('aria-checked', reactive ? 'true' : 'false');
      const box = btn.querySelector('.ia-reactive-box');
      if (box) box.textContent = reactive ? '\u2713' : '';
    }
    showToast(reactive ? '반응형 생성 켜짐' : '반응형 생성 꺼짐', 'info');
  }

  /** 무엇이 바뀌었는지 판정하는 지문.
   *
   *  **베이스 프롬프트만 보면 안 된다.** 캐릭터 태그는 `char_captions` 로 따로
   *  나가므로 `renderPrompt()` 값이 그대로다 — 캐릭터 슬롯을 아무리 만져도 변화를
   *  못 잡는다(2026-08-05 사용자 지적: 씬 슬롯으로만 시험해서 놓쳤다).
   *  성별·활성 상태도 프롬프트에 나가므로 함께 센다. */
  function reactiveSignature() {
    const chars = state.chars
      .map(c => [c.state, c.gender, buildCharPrompt(c)].join(''))
      .join('');
    return renderPrompt() + '' + chars;
  }

  /** 슬롯이 바뀔 때마다 불린다. 실제 발화는 호스트(app.js)가 맡는다. */
  function reactiveOnChange() {
    if (!reactive || !active) return;
    // 슬롯에 **직접 타이핑하는 동안은 발화하지 않는다.** `1girl` 을 치면 여섯 번
    // 나가서 Anlas 만 태운다(사용자 합의). 지문도 갱신하지 않는다 — 그래야 blur/
    // Enter 시점에 '그동안 쌓인 변화'가 통째로 잡힌다.
    if (reactiveTypingSlot) return;
    const now = reactiveSignature();
    if (now === reactiveLastPrompt) return;   // 순서만 바뀐 재렌더는 흘린다
    reactiveLastPrompt = now;
    if (typeof isGenerating === 'function' && isGenerating()) {
      reactivePending = true;                 // **모은다.** 개수와 무관하게 한 번이다
      return;
    }
    requestGeneration();
  }

  /** 생성이 끝나면 app.js 가 부른다. 모아 둔 변화가 있으면 그때 한 번 낸다. */
  function reactiveOnGenerationDone() {
    if (!reactive || !active || !reactivePending) return;
    reactivePending = false;
    reactiveLastPrompt = reactiveSignature();
    requestGeneration();
  }

  function ensureSceneMount() {
    if (sceneMount && document.body.contains(sceneMount)) return sceneMount;
    sceneMount = document.createElement('div');
    sceneMount.className = 'ia-scene-float';
    // **슬롯 팝업과 같은 stacking context 안에 둔다.** 팝업(`.ia-panel`)은
    // `.viewer-wrapper`(z-index:0 + isolation:isolate) **안**에 있어서 그 z 2200 이
    // 바깥에서는 0 층으로 접힌다. 이 플로트를 body 직계로 두면 둘을 동시에 만족시킬
    // 값이 없다 — 1 이상이면 팝업을 뚫고, 0 이하면 wrapper 의 불투명 배경에 먹힌다.
    // 실제로 음수로 내렸다가 씬 버튼 8개와 반응형 토글이 통째로 결과 패널 뒤로
    // 사라졌다(사용자 지적). 같은 컨텍스트에 넣으면 z 로 정직하게 줄을 세울 수 있다.
    // `position: fixed` 는 그대로 뷰포트 기준이다(wrapper 에 transform 이 없다).
    (document.querySelector('.viewer-wrapper') || document.body).appendChild(sceneMount);
    sceneMount.addEventListener('mousedown', keepEditingFocus);   // 왼쪽 팝업과 동일
    // 슬롯 위에서 우클릭하면 그 슬롯의 팝업을 닫는다(사용자 편의). 브라우저 메뉴는 막는다.
    sceneMount.addEventListener('contextmenu', event => {
      const b = event.target.closest('[data-slot]');
      if (!b || !panelContext || panelContext.kind !== 'scene') return;
      if (panelContext.slotId !== b.dataset.slot) return;
      event.preventDefault();
      closePanel();
    });
    sceneMount.addEventListener('click', event => {
      const rx = event.target.closest('[data-ia-reactive]');
      if (rx) { event.preventDefault(); setReactive(!reactive); return; }
      const b = event.target.closest('[data-slot]');
      if (!b) return;
      if (isEditing('scene', b.dataset.slot)) { focusEditingInput(); return; }
      openSlot(b.dataset.slot);
    });
    return sceneMount;
  }

  // 버튼 줄 높이. 팝업이 이만큼 아래에서 시작해 서로 가리지 않는다.
  const SCENE_FLOAT_H = 30;

  /** 플로트가 뻗을 수 있는 오른쪽 한계. 히스토리 레일이 떠 있으면 그 앞에서 멈춘다. */
  function sceneRightEdge() {
    const rail = document.getElementById('viewerPanel');
    // `offsetParent` 가 null 이면 숨겨진 것이다(레일은 static 이라 이 판정이 통한다).
    if (rail && rail.offsetParent) {
      const box = rail.getBoundingClientRect();
      if (box.width > 0) return box.left;
    }
    return window.innerWidth;
  }

  function sceneFloatFits() {
    if (window.innerWidth < SCENE_FLOAT_MIN) return false;
    const box = blocksMount.getBoundingClientRect();
    // 들어갈 폭도 같은 한계로 잰다 — 레일을 뺀 자리에 한 줄이 들어가야 한다.
    return box.right + 12 + 360 <= sceneRightEdge() - 12;
  }

  // 팝업의 CSS 기본 top. 버튼 줄은 여기에 깔고 팝업을 그 아래로 내린다.
  const PANEL_TOP = 46;
  const PANEL_LEFT = 494;   // .ia-panel 의 CSS 기본 left
  // 팝업 가로. **CSS 가 아니라 여기가 실제로 정한다** — positionPopup/
  // positionPresetPanel 이 인라인 width 를 넣으므로 style.css 의 width 는 초기값일
  // 뿐이다(CSS 만 380 으로 줄였더니 화면은 560 그대로였다).
  // 560 -> 380: 팝업이 커서 생성 이미지가 안 보인다는 지적(테스터 2026-08-07).
  const PANEL_W = 380;

  // 씬 버튼 줄은 `document.body` 에 붙는 플로트라 **오른쪽 탭이 바뀌어도 그대로 남는다.**
  // Characters / Artists / Studio 탭 위에 구도·배경·성인 버튼이 겹쳐 떠 있었다(사용자 지적).
  // 이 버튼들이 여는 팝업은 Result 화면의 프롬프트 조립을 전제로 하므로 Result 에서만 뜬다.
  function resultTabActive() {
    const pane = document.getElementById('rightTabResult');
    return !!pane && !pane.hidden && pane.classList.contains('active');
  }

  // 탭 전환은 pane 의 `class`/`hidden` 만 바꾼다 — 이벤트가 없다. 감시해서 다시 판정한다.
  let sceneTabWatch = null;
  function watchResultTab() {
    if (sceneTabWatch) return;
    const pane = document.getElementById('rightTabResult');
    if (!pane) return;
    sceneTabWatch = new MutationObserver(() => { positionSceneFloat(); syncGlobalEditor(); });
    sceneTabWatch.observe(pane, { attributes: true, attributeFilter: ['class', 'hidden'] });
    watchHistoryRail();
  }

  // 히스토리 레일을 접거나 펼치면 **창 크기는 그대로**라 resize 가 오지 않는다.
  // 그런데 플로트의 오른쪽 한계는 레일 위치로 정해지므로, 폭을 직접 지켜본다 —
  // 안 그러면 접힌 채로 잰 폭이 남아 펼친 레일을 다시 덮는다.
  let sceneRailWatch = null;
  function watchHistoryRail() {
    if (sceneRailWatch || typeof ResizeObserver === 'undefined') return;
    const rail = document.getElementById('viewerPanel');
    if (!rail) return;
    // rAF 로 미루지 않는다 — 배경 탭에서는 rAF 가 스로틀돼 창을 다시 볼 때까지
    // 플로트가 옛 폭으로 남는다. ResizeObserver 콜백은 레이아웃이 끝난 뒤에 돌므로
    // 여기서 바로 재도 현재 값이 나온다.
    sceneRailWatch = new ResizeObserver(() => positionSceneFloat());
    sceneRailWatch.observe(rail);
  }

  // ── 하단 글로벌 편집기 ─────────────────────────────────────────────────
  //
  // 축별 배열이 SSOT 다. 여기서는 **보기만 하나로** 모은다 — 칩을 지우면 원래 축의
  // 배열에서 빠지고, 새로 적는 것은 자유 입력으로만 들어간다. 전체를 텍스트로 열어
  // 축으로 되돌리는 방식은 폐기했다: 같은 태그가 두 축에 있으면 소유를 정할 수 없고,
  // 이 모듈은 애초에 '블록 -> 문자열' 단방향 계약이다.

  /** 축 id -> 사람이 읽는 이름. 목록에서 파생한다(손으로 적으면 축을 더할 때 어긋난다). */
  const SCENE_LABEL = new Map(SCENE_SLOTS.map(slot => [slot.id, slot.name]));

  /** 저장 원소 하나를 칩 하나로 본다. `2::a, b ::` 는 **쪼개지 않는다** —
   *  쪼개서 되쓰면 공백·중첩·이스케이프에서 원문이 상한다. 무게만 배지로 뗀다. */
  function weightedChip(raw) {
    const m = /^\s*(-?\d+(?:\.\d+)?)\s*::\s*([\s\S]*?)\s*::\s*$/.exec(String(raw));
    return m ? {weight: m[1], text: m[2]} : {weight: null, text: String(raw)};
  }

  /** 화면에 뿌릴 평면 목록. 순서는 renderPrompt() 와 같다(= 실제 프롬프트 순서). */
  function globalChipList() {
    const out = [];
    for (const slot of SCENE_SLOTS) {
      if (slot.id === 'composition') {
        for (const t of compTags(state.composition)) {
          // 구도 3축 콤보는 파생값이다 — 여기서 지울 수 없다(콤보를 바꿔야 한다).
          out.push({raw: t, slot: 'composition', locked: true, index: -1});
        }
      }
      (state.slots[slot.id] || []).forEach((t, i) => {
        out.push({raw: t, slot: slot.id, locked: false, index: i});
      });
    }
    return out;
  }

  /** 텍스트 모드의 내용. **잠긴 칩(구도 콤보 파생)은 넣지 않는다** — 콤보에서
   *  나온 값이라 여기서 고쳐도 다시 만들어진다. 씬 슬롯이 편집 중에 파생 칩을
   *  빼는 것과 같은 규칙이다(slotBody). */
  function globalTextValue() {
    const parts = globalChipList().filter(i => !i.locked).map(i => i.raw);
    const free = String(state.freeText || '').trim();
    if (free) parts.push(free);
    return parts.join(', ');
  }

  /** 쉼표로 나누되 **NAI 가중치 묶음 안의 쉼표는 건드리지 않는다.**
   *  `parseSlotInput` 은 `/[,\n]/` 로 그냥 쪼개서 `2::hug, grabbing from behind ::`
   *  를 두 동강 낸다 — 이 자리는 가중치 묶음을 보여 주는 것이 목적이라 그대로
   *  쓸 수 없다. 여는 `::` 인지 닫는 `::` 인지는 **앞에 숫자가 붙었는지**로 가른다.
   *  닫는 짝이 없으면 남은 부분을 통째로 하나로 둔다(찢는 것보다 낫다). */
  function parseGlobalInput(value) {
    const out = [];
    const seen = new Set();
    const src = String(value || '');
    let buf = '';
    let inWeight = false;
    const push = () => {
      const t = buf.trim();
      buf = '';
      if (t && !seen.has(t.toLowerCase())) { seen.add(t.toLowerCase()); out.push(t); }
    };
    for (let i = 0; i < src.length; i++) {
      const ch = src[i];
      if (ch === ':' && src[i + 1] === ':') {
        inWeight = inWeight ? false : /-?\d+(?:\.\d+)?\s*$/.test(buf);
        buf += '::';
        i++;
        continue;
      }
      if (!inWeight && (ch === ',' || ch === '\n')) { push(); continue; }
      buf += ch;
    }
    push();
    return out;
  }

  /** 텍스트를 다시 축별 칩으로 되돌린다.
   *
   *  **원래 있던 축을 기억해서 제자리로 보낸다.** 태그 사전을 다시 뒤져 축을
   *  정하면, 여러 축에 걸친 태그가 사용자가 넣어 둔 자리에서 멋대로 옮겨간다.
   *  처음 보는 태그만 자유 입력으로 간다 — 축을 정하는 것은 위 버튼의 몫이다.
   *  텍스트에서 사라진 태그는 그대로 사라진다(그게 지우는 방법이다). */
  function commitGlobalText(value) {
    const home = new Map();
    for (const item of globalChipList()) {
      if (item.locked) continue;
      const k = item.raw.trim().toLowerCase();
      if (!home.has(k)) home.set(k, []);
      home.get(k).push(item.slot);          // 같은 글자가 두 축에 있으면 순서대로
    }
    const next = emptySceneSlots();
    const leftover = [];
    for (const tag of parseGlobalInput(value)) {
      const queue = home.get(tag.trim().toLowerCase());
      if (queue && queue.length) next[queue.shift()].push(tag);
      else leftover.push(tag);
    }
    state.slots = next;
    state.freeText = leftover.join(', ');
  }

  /** 직접 적은 것을 태그 단위로 본다. 저장은 문자열 하나지만(프롬프트에 그대로
   *  붙는 값이라 원문을 지켜야 한다) 화면과 개수는 태그 단위여야 한다. */
  function freeTagList() {
    return parseGlobalInput(state.freeText || '');
  }

  function globalEditorHtml() {
    const list = globalChipList();
    const chips = list.map(item => {
      const {weight, text} = weightedChip(item.raw);
      const label = SCENE_LABEL.get(item.slot) || item.slot;
      const tip = weight
        ? `${label} \u00b7 가중치 ${weight} \u00b7 이 묶음은 통째로만 지울 수 있습니다`
        : (item.locked ? `${label} \u00b7 구도 콤보에서 나온 값입니다` : label);
      return `<span class="ia-gchip${item.locked ? ' is-locked' : ''}" data-slot="${item.slot}"
        title="${escHtml(tip)}">
        ${weight ? `<b class="ia-gchip-w">${escHtml(weight)}\u00d7</b>` : ''}
        <span class="ia-gchip-t">${escHtml(text)}</span>
        ${item.locked ? '' :
          `<button type="button" class="ia-gchip-x" data-gslot="${item.slot}" data-gidx="${item.index}"
             aria-label="제거">\u00d7</button>`}
      </span>`;
    }).join('');
    if (globalTextMode) {
      // 텍스트 모드는 **통째로 전환**된다(사용자 지정). 칩을 같이 두면 같은 태그가
      // 두 군데 보여 어느 쪽을 고치는 건지 알 수 없다. 빠져나오면 다시 칩이 된다.
      return `
        <div class="ia-ge-box is-text" id="iaGlobalBox">
          <textarea class="ia-ge-text" id="iaGlobalText" spellcheck="false"
            placeholder="태그를 쉼표로 구분해 적습니다"
          >${escHtml(globalTextValue())}</textarea>
        </div>`;
    }
    // 직접 적은 것도 **태그마다 칩 하나**다. 한 덩어리로 두면 지울 때 통째로만
    // 지워지고, 축 칩과 같은 것을 다루면서 모양이 달라 눈에 걸린다.
    const freeChips = freeTagList().map((t, i) => {
      const {weight, text} = weightedChip(t);
      return `<span class="ia-gchip is-free" title="직접 적은 것">
        ${weight ? `<b class="ia-gchip-w">${escHtml(weight)}×</b>` : ''}
        <span class="ia-gchip-t">${escHtml(text)}</span>
        <button type="button" class="ia-gchip-x" data-gfree="${i}" aria-label="제거">×</button>
      </span>`;
    }).join('');
    const total = list.length + freeTagList().length;
    return `
      <div class="ia-ge-box" id="iaGlobalBox" title="눌러서 텍스트로 고칩니다">
        <div class="ia-ge-chips">${chips}${freeChips}</div>
        ${total ? '' : '<span class="ia-ge-empty">눌러서 적거나, 위 버튼으로 넣습니다</span>'}
      </div>`;
  }

  /** 편집기를 보일지 말지. Interactive 가 켜져 있고 결과 탭일 때만 자리를 바꾼다. */
  function syncGlobalEditor() {
    const host = document.getElementById('interactiveGlobalEditor');
    const info = document.getElementById('resultInfoContent');
    if (!host || !info) return;
    const on = active && !blocksMount.hidden && resultTabActive() && !globalEditorPeek;
    host.hidden = !on;
    // 판이 낮으면 자유 입력칸이 통째로 잘린다(실측: 판 96px → 편집기 62px 인데
    // 머리+입력만 73px 이 필요했다). 편집기가 떠 있는 동안만 바닥을 깔아 준다 —
    // 사용자가 늘려 둔 높이는 그대로 존중된다(min-height 라 더 크면 그 값이 이긴다).
    const panel = document.getElementById('resultInfoPanel');
    if (panel) panel.classList.toggle('has-ia-editor', on);
    if (!on) syncGlobalCountBadge(0);
    // 저 칸의 주인은 히스토리다 — 내용은 건드리지 않고 보이기만 바꾼다.
    info.style.display = on ? 'none' : '';
    if (on) renderGlobalEditor();
  }

  let globalEditorPeek = false;   // '생성 정보 보기'로 잠시 넘겨 둔 상태

  /** 개수는 편집기 밖(GENERATION INFO 줄)의 배지가 받는다 — 바로 위에 제목
   *  줄이 있는데 편집기가 자기 제목을 또 달아 두 번 나왔다(사용자 지적). */
  function syncGlobalCountBadge(n) {
    const badge = document.getElementById('iaGlobalCount');
    const on = !document.getElementById('interactiveGlobalEditor')?.hidden;
    // 제목도 같이 바꾼다. 이 자리가 씬 태그 편집기가 됐는데 머리는 'GENERATION
    // INFO' 인 채라 편집기를 보면서 엉뚱한 제목을 읽게 된다(사용자 지적).
    const title = document.getElementById('resultInfoTitle');
    if (title) title.textContent = on ? '씬 태그' : 'Generation Info';
    if (!badge) return;
    badge.hidden = !on;
    badge.textContent = on ? `${n}개` : '';
  }

  let globalTextMode = false;   // 칩(false) — 텍스트(true)

  function renderGlobalEditor() {
    const host = document.getElementById('interactiveGlobalEditor');
    if (!host || host.hidden) return;
    // 타이핑 중에는 다시 그리지 않는다 — 커서와 IME 조합이 날아간다.
    if (document.activeElement && document.activeElement.id === 'iaGlobalText') return;
    host.innerHTML = globalEditorHtml();
    // 배지는 **보이는 칩 전부**를 센다 — 직접 적은 것을 빼면 3개가 보이는데 0 이라
    // 적혀 서로 어긋난다(실측).
    syncGlobalCountBadge(globalChipList().length + freeTagList().length);
    bindGlobalEditor(host);
  }

  function bindGlobalEditor(host) {
    host.querySelectorAll('[data-gslot]').forEach(btn => {
      btn.addEventListener('click', () => {
        const id = btn.dataset.gslot;
        const idx = Number(btn.dataset.gidx);
        const list = state.slots[id];
        if (!Array.isArray(list) || !(idx >= 0) || idx >= list.length) return;
        list.splice(idx, 1);
        renderBlocks();          // 씬 버튼의 개수 배지도 같이 줄어야 한다
        emitChange();
      });
    });
    // 직접 적은 칩의 [×]. 저장은 문자열 하나라 지운 뒤 다시 잇는다.
    host.querySelectorAll('[data-gfree]').forEach(btn => {
      btn.addEventListener('click', () => {
        const idx = Number(btn.dataset.gfree);
        const tags = freeTagList();
        if (!(idx >= 0) || idx >= tags.length) return;
        tags.splice(idx, 1);
        state.freeText = tags.join(', ');
        renderGlobalEditor();
        emitChange();
      });
    });
    const box = host.querySelector('#iaGlobalBox');
    const text = host.querySelector('#iaGlobalText');
    // 칩 모드: 상자 아무 데나 누르면 텍스트 모드로 통째로 바뀐다. [x] 는 뺀다 —
    // 지우면서 동시에 모드가 바뀌면 방금 무엇을 지웠는지 보이지 않는다.
    if (box && !text) {
      box.addEventListener('pointerdown', event => {
        if (event.target.closest('.ia-gchip-x')) return;
        event.preventDefault();
        globalTextMode = true;
        renderGlobalEditor();
        const ta = document.getElementById('iaGlobalText');
        if (ta) { ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); }
      });
      return;
    }
    if (!text) return;
    // 표준 자동완성. e621 은 켜 두고 **캐릭터·아티스트만** 뺀다 — 여기는 그림
    // 전체에 걸리는 자리라 인물·작가는 캐릭터 슬롯이 맡는다(사용자 지정).
    if (typeof bindTagAssist === 'function') {
      try { bindTagAssist(text, {excludeCats: ['character', 'artist']}); } catch (_) {}
    }
    // 다 썼다는 신호 = 포커스를 잃거나 Esc. Enter 는 **줄바꿈으로 둔다** — 여기는
    // 슬롯 하나가 아니라 전체 목록이라 여러 줄로 정리하는 편이 읽기 쉽다.
    // 반응형 생성은 타이핑 중에 멈춘다 — 글자마다 유료 생성이 나가면 안 된다.
    // 빠져나올 때 한 번만 낸다(씬 슬롯의 flushTyping 과 같은 규칙).
    text.addEventListener('input', () => { reactiveTypingSlot = text; });
    const leave = () => {
      if (!globalTextMode) return;
      globalTextMode = false;
      commitGlobalText(text.value);
      renderBlocks();            // 씬 버튼의 개수 배지도 같이 맞춘다
      renderGlobalEditor();
      emitChange();
      if (reactiveTypingSlot === text) { reactiveTypingSlot = null; reactiveOnChange(); }
    };
    text.addEventListener('blur', leave);
    text.addEventListener('keydown', event => {
      if (event.key !== 'Escape') return;
      // 자동완성 목록이 떠 있으면 그쪽이 먼저 닫혀야 한다 — 한 번에 둘 다 닫으면
      // 목록만 지우려던 사용자가 편집기 밖으로 튕겨 나간다.
      if (document.querySelector('#tagTooltip:not([hidden])')) return;
      event.preventDefault();
      text.blur();
    });
  }

  function positionSceneFloat() {
    const host = ensureSceneMount();
    // Interactive 가 꺼져 있으면 버튼도 없어야 한다 — blocksMount 가 hidden 이면 끈다.
    if (!sceneFloatFits() || blocksMount.hidden || !resultTabActive()) {
      host.classList.remove('open');
      return;
    }
    // 세로로 쌓았더니 결과 영역을 가렸다(실사용 지적). **가로 한 줄**로 깔되,
    // blocksMount.top 에서 위로 빼면 앱 탭바를 덮는다(실측) — 팝업 기준선에 맞춘다.
    // `blocksMount.right`(465)는 좌측 컬럼의 **안쪽** 끝이라 그 기준으로 붙이면
    // 컬럼 여백을 파고든다(실측: 컬럼 바깥 끝 480). `.ia-panel` 의 CSS 기본
    // left(494)가 이미 그 여백을 감안한 값이라 하한으로 쓴다.
    const box = blocksMount.getBoundingClientRect();
    const left = Math.max(Math.round(box.right + 12), PANEL_LEFT);
    host.style.left = left + 'px';
    host.style.top = PANEL_TOP + 'px';
    // 오른쪽 끝은 **히스토리 레일 앞**까지다. 예전에는 `window.innerWidth` 에서
    // 빼서 레일 위까지 깔렸는데, 이 플로트는 `position: fixed` 라 자리 잡지 않은
    // 레일보다 위에 그려진다 — 레일의 팝업 버튼(↗)이 그 밑에 깔려 눌리지 않았고,
    // Interactive 에서 히스토리로 들어갈 길이 통째로 막혔다(사용자 지적).
    host.style.width = Math.max(0, Math.round(sceneRightEdge() - left - 12)) + 'px';
    if (host.innerHTML) host.classList.add('open');
  }

  function renderBlocks() {
    // **편집 중 textarea 는 이 함수가 통째로 다시 만든다.** 포커스가 거기 있었다면
    // 재렌더 뒤 body 로 떨어지고, 그 blur 가 '바깥 클릭' 으로 잡혀 팝업이 닫힌다.
    // 조언 플로트의 색 버튼(`black jacket`)이 renderBlocks 를 부르는 유일한 경로라
    // 색만 고르면 팝업이 닫혔다(사용자 지적). 캐럿 위치까지 그대로 되돌린다.
    const prevEl = document.activeElement;
    const keepFocus = !!(prevEl && prevEl.classList
                         && prevEl.classList.contains('ia-slot-input')
                         && blocksMount.contains(prevEl));
    let caret = null;
    if (keepFocus) {
      try { caret = [prevEl.selectionStart, prevEl.selectionEnd]; } catch (_) { caret = null; }
    }
    const floating = sceneFloatFits();
    // 편집 중인 씬 슬롯은 **인라인으로 남긴다.** 태그를 직접 치는 textarea 가 그
    // 블록 안에 있어서, 전부 버튼으로 빼면 입력창이 사라진다(실측).
    const inlineScenes = floating
      ? SCENE_SLOTS.filter(sl => isEditing('scene', sl.id))
      : SCENE_SLOTS;
    blocksMount.innerHTML = charBlockHtml() + inlineScenes.map(sceneBlockHtml).join('');
    lastPosSig = posSignature();   // 방금 그린 구성이 기준선이다
    const host = ensureSceneMount();
    host.innerHTML = floating
      ? SCENE_SLOTS.map(sceneButtonHtml).join('') + reactiveToggleHtml()
      : '';
    applyReactiveTip();
    watchResultTab();
    positionSceneFloat();
    syncGlobalEditor();
    // 초기 렌더는 `blocksMount.hidden` 이 아직 true 인 시점에 돌 수 있다(실측: 새로고침
    // 하면 버튼은 생기는데 플로트가 안 열렸다). 레이아웃이 잡힌 다음 프레임에 한 번 더
    // 판정해 순서 의존을 없앤다.
    requestAnimationFrame(positionSceneFloat);

    if (keepFocus) {
      const ta = editingEl()?.querySelector('.ia-slot-input');
      if (ta) {
        ta.focus();
        if (caret) { try { ta.setSelectionRange(caret[0], caret[1]); } catch (_) {} }
      }
    }

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
      // 그 슬롯의 팝업이 열려 있을 때 우클릭하면 닫는다(사용자 편의).
      el.addEventListener('contextmenu', event => {
        if (!panelContext || panelContext.kind !== 'char') return;
        if (panelContext.cid !== el.dataset.cid || panelContext.sub !== el.dataset.sub) return;
        event.preventDefault();
        event.stopPropagation();
        closePanel();
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
        openCharReference();
      });
    });
    blocksMount.querySelectorAll('[data-charpreset]').forEach(el => {
      el.addEventListener('click', event => {
        event.stopPropagation();
        openPresetPanel(el.dataset.cid);
      });
    });
    blocksMount.querySelectorAll('[data-chargaze]').forEach(el => {
      el.addEventListener('click', event => {
        event.stopPropagation();
        openGazePicker(el, el.dataset.cid);
      });
    });
    blocksMount.querySelectorAll('[data-charalt]').forEach(el => {
      el.addEventListener('click', event => {
        event.stopPropagation();
        openAltPicker(el, el.dataset.cid);
      });
    });
    blocksMount.querySelectorAll('[data-charpresetclear]').forEach(el => {
      el.addEventListener('click', event => {
        event.stopPropagation();
        clearCharPreset(el.dataset.cid);
      });
    });
    blocksMount.querySelectorAll('[data-charpos]').forEach(el => {
      el.addEventListener('click', event => {
        event.stopPropagation();
        openPositionPicker(el, el.dataset.cid);
      });
    });
    bindChipDeletes(blocksMount);   // 칩의 [×] — 슬롯을 열지 않고 그 태그 하나만 뺀다
    blocksMount.querySelectorAll('[data-chardup]').forEach(el => {
      el.addEventListener('click', event => {
        event.stopPropagation();
        duplicateCharacter(el.dataset.cid);
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
    notifyRoster();
  }

  /** 캐릭터 스택(Assets 바 위 세로 버튼)이 읽는 요약. 태그 전체가 아니라
   *  버튼에 그릴 것만 넘긴다 — 스택은 열기 전환용이지 편집용이 아니다. */
  function characterRoster() {
    // 좌표가 실제로 나가는 슬롯만 스택에서 POS 버튼을 받는다 — 안 그러면 OFF/빈 슬롯에도
    // 버튼이 붙어 눌러 놓은 값이 조용히 버려진다.
    const posIds = new Set(positionedChars().map(c => c.id));
    return state.chars.map((c, i) => ({
      index: i,
      id: c.id,
      label: 'C' + (i + 1),
      open: !!c.open,
      enabled: c.state === 'active',
      gender: c.gender || 'female',
      pos: c.pos || POS_DEFAULT,
      positioned: posIds.has(c.id),
      name: (c.fields?.['캐릭터'] || [])[0] || c.name || '',
    }));
  }

  function notifyRoster() {
    try { onRosterChange(characterRoster()); } catch (_) { /* 스택은 부가 UI */ }
  }

  /** 스택 버튼이 부른다. 토글이 아니라 **항상 연다** — 사용자가 그 슬롯을 보려고
   *  누른 것이므로, 이미 열려 있으면 닫는 동작은 의도와 어긋난다. */
  function openCharacterAt(index) {
    const i = Number(index);
    if (!Number.isInteger(i) || i < 0 || i >= state.chars.length) return false;
    state.chars.forEach((c, n) => { c.open = (n === i); });
    renderBlocks();
    notifyRoster();
    return true;
  }

  /** 슬롯 **id** 로 꽂는다. 인덱스는 안정적이지 않다 — 앞 슬롯이 지워지면 뒤가
   *  당겨져 같은 번호가 다른 캐릭터를 가리킨다(비동기 적용 중에 실제로 일어난다).
   *  id 는 슬롯이 살아 있는 동안 바뀌지 않으므로 이쪽이 정확하다. */
  function applySnapshotCharById(cid, row, picks) {
    const i = state.chars.findIndex(c => c.id === cid);
    if (i < 0) return false;
    return applySnapshotCharAt(i, row, picks);
  }

  /** 부분 복원의 묶음. 화면의 회색 소제목(`axis`)을 그대로 쓴다 — 슬롯이 늘어도
   *  여기를 고칠 필요가 없다. `alt`(대체 의상)와 `gaze`(시선)는 슬롯이 아니라
   *  캐릭터에 직접 달린 값이라 손으로 붙인다. */
  const RESTORE_GROUPS = [
    {key: 'identity', label: '정체성', axes: ['character', 'characteristic'], extras: []},
    {key: 'clothing', label: '의상', axes: ['clothing'], extras: ['alt']},
    {key: 'situation', label: '상황',
     axes: ['expression', 'pose_action', 'object', 'meta'], extras: ['gaze']},
  ];

  /** 복원에서 고를 수 있는 항목. 슬롯 11개 + alt/gaze. */
  function restoreItems() {
    const out = [];
    for (const g of RESTORE_GROUPS) {
      for (const sub of CHAR_SUBS) {
        if (g.axes.includes(sub.axis)) {
          out.push({key: sub.key, label: sub.key, icon: sub.icon || '', group: g.key});
        }
      }
      if (g.extras.includes('alt')) {
        out.push({key: '@alt', label: 'ALT', icon: '', group: g.key});
      }
      if (g.extras.includes('gaze')) {
        out.push({key: '@gaze', label: '시선', icon: '', group: g.key});
      }
    }
    return out;
  }

  /** 스냅샷의 **캐릭터 한 명**을 지정한 슬롯에 꽂는다(빠른 스왑).
   *  슬롯이 아직 없으면 최대치까지 만들어 채운다. 다른 슬롯은 건드리지 않는다.
   *
   *  `picks` 를 주면 **그 항목만** 덮어쓴다(캡처는 전체, 복원은 골라서 —
   *  사용자 지정 2026-08-07). 고르지 않은 항목은 대상 슬롯의 값을 그대로 둔다.
   *  `picks` 가 없으면 예전처럼 통째로 갈아끼운다. */
  function applySnapshotCharAt(index, row, picks) {
    if (!row || typeof row !== 'object') return false;
    let i = Number(index);
    if (!Number.isInteger(i) || i < 0) return false;
    if (i >= MAX_NAI_CHARACTERS) return false;
    // **있는 슬롯에만** 꽂는다. 슬롯을 늘리는 것은 [+](addCharacterSlot)의 일이다 —
    // 여기서 암묵적으로 만들면 사용자가 [+] 를 누르지 않았는데 인원이 늘고 그 캐릭터가
    // 생성 프롬프트에 끼어든다(대상이 삭제된 슬롯을 겨눈 채 적용하면 실제로 닿는다).
    if (i >= state.chars.length) return false;
    // 슬롯의 정체성(위치)은 유지한다 — 스왑은 '누구인가'를 바꾸는 것이지
    // '어디에 서는가'를 바꾸는 것이 아니다. 다인원 배치를 다시 잡게 만들면 안 된다.
    const keepPos = state.chars[i].pos || POS_DEFAULT;
    const cur = state.chars[i];
    const fields = row.fields || {};
    // 고르지 않은 항목은 **대상 슬롯의 값을 그대로** 둔다. 그래서 바탕이 다르다:
    // 전부 복원이면 새 캐릭터에서, 부분 복원이면 지금 있는 캐릭터에서 출발한다.
    // 부분인데 새 캐릭터에서 출발하면 안 고른 슬롯이 조용히 비워진다.
    const partial = picks instanceof Set;
    const take = key => !partial || picks.has(key);
    const base = partial ? cur : newCharacter(false);
    state.chars[i] = {
      ...base,
      id: cur.id,                     // id 는 그대로 — 생성 배선이 슬롯을 uuid 로 잡는다
      open: true,
      pos: keepPos,
      // 이름·프리셋·성별은 '캐릭터' 슬롯에 딸린 값이다 — 그 슬롯을 고를 때만 온다.
      name: take(CHAR_TAG_SLOT) ? String(row.name || '') : base.name,
      state: take(CHAR_TAG_SLOT)
        ? (row.state === 'disabled' ? 'disabled' : 'active') : base.state,
      gender: take(CHAR_TAG_SLOT)
        ? (row.gender === 'male' ? 'male' : 'female') : base.gender,
      preset: take(CHAR_TAG_SLOT)
        ? (row.preset ? {
            work: row.preset.work,
            name: row.preset.name,
            tags: (row.preset.tags && typeof row.preset.tags === 'object')
              ? Object.fromEntries(Object.entries(row.preset.tags)
                  .map(([k, v]) => [k, Array.isArray(v) ? [...v] : []]))
              : {},
          } : null)
        : base.preset,
      alt: take('@alt')
        ? (Array.isArray(row.alt) ? [...row.alt] : [])
        : (Array.isArray(base.alt) ? [...base.alt] : []),
      gaze: take('@gaze')
        ? (Array.isArray(row.gaze) ? [...row.gaze] : [])
        : (Array.isArray(base.gaze) ? [...base.gaze] : []),
      fields: Object.fromEntries(CHAR_SUBS.map(sub => {
        if (!take(sub.key)) {
          const kept = base.fields && base.fields[sub.key];
          return [sub.key, Array.isArray(kept) ? [...kept] : defaultFieldsFor(sub.key)];
        }
        return [sub.key,
          Array.isArray(fields[sub.key]) ? [...fields[sub.key]] : defaultFieldsFor(sub.key)];
      })),
    };
    state.chars.forEach((c, n) => { c.open = (n === i); });
    renderBlocks();
    emitChange();
    notifyRoster();
    return true;
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
    notifyRoster();
  }

  /** 성별 세그먼트 토글(female/male). 카드 하나만 in-place 갱신 — 편집 중 슬롯을 안 건드린다. */
  function setCharGender(cid, gender) {
    const c = state.chars.find(x => x.id === cid);
    const next = gender === 'male' ? 'male' : 'female';
    if (!c || c.gender === next) return;
    c.gender = next;
    notifyRoster();   // 스택 항목이 성별을 들고 있다
    const card = blocksMount.querySelector(`.ia-char[data-cid="${cid}"]`);
    if (card) {
      card.querySelectorAll('[data-gender]').forEach(b => b.classList.toggle('on', b.dataset.gender === next));
    } else {
      renderBlocks();
    }
    emitChange();
  }

  /** 붙어 있는(켜 둔) 레퍼런스 수. 없으면 0. */
  function charRefCount() {
    // Interactive 전용 패널의 개수다. 여기 켜진 것만 Interactive 생성에 실린다 —
    // NAI 모듈의 프레임 수를 세면 배지가 남의 상태를 말한다.
    const st = getCharacterReferenceState && getCharacterReferenceState();
    if (st && typeof st.count === 'number') return st.count;
    const frames = (st && Array.isArray(st.frames)) ? st.frames : [];
    return frames.length;
  }

  /** 캐릭터 헤더의 [Reference]. 붙은 것이 있으면 개수를 달고 강조한다 —
   *  예전엔 늘 같은 회색이라 켜 둔 채로 생성하는 사고가 보이지 않았다.
   *  **NAI 는 레퍼런스를 캐릭터별이 아니라 세트 단위로 받는다.** 버튼이 캐릭터
   *  헤더에 있어도 여는 것은 생성 전체에 걸리는 하나의 세트다 — 툴팁에 적어 둔다. */
  function charRefButtonHtml() {
    const n = charRefCount();
    const tip = n
      ? `캐릭터 레퍼런스 ${n}장 적용 중 — 생성 전체에 걸린다(캐릭터별이 아니다)`
      : '캐릭터 레퍼런스 — 이미지를 붙인다. 생성 전체에 걸린다(캐릭터별이 아니다)';
    return `<button type="button" class="ia-char-ref${n ? ' is-on' : ''}" data-charref` +
      ` title="${escHtml(tip)}">Reference${n ? `<span class="ia-char-ref-n">${n}</span>` : ''}</button>`;
  }

  /** Reference — **Interactive 전용** 레퍼런스 패널을 연다. NAI 캐릭터 레퍼런스
   *  모듈이 아니다(상태가 독립이다 — core/headless_interactive_reference_service.py).
   *  NAI 는 레퍼런스를 캐릭터별이 아니라 세트 단위로 받으므로 헤더에 하나만 둔다. */
  function openCharReference() {
    if (typeof onCharReference !== 'function') {
      showToast('Reference 기능을 열 수 없습니다.', 'error');
      return;
    }
    onCharReference();
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

  /** 다른 캐릭터가 선 칸 -> 그 라벨들. 위치는 본질적으로 **여러 명의 상대 배치**인데
   *  팝업은 한 명만 보여 줘서, C1 이 어디 있는지 모르고 C2 를 놓아야 했다.
   *  남들을 음영으로 깔아 두면 팝업을 여닫으며 대조할 일이 없다(사용자 제안). */
  function otherPositions(cid) {
    const map = new Map();
    positionedChars().forEach(c => {
      if (c.id === cid) return;
      const p = c.pos || POS_DEFAULT;
      if (!map.has(p)) map.set(p, []);
      map.get(p).push('C' + (state.chars.indexOf(c) + 1));
    });
    return map;
  }

  function posPopupHtml(cur, cid) {
    const others = otherPositions(cid);
    let cells = '<div class="ia-pos-hdr"></div>' +
      POS_COLS.map(col => `<div class="ia-pos-hdr">${col}</div>`).join('');
    for (let row = 1; row <= 5; row++) {
      cells += `<div class="ia-pos-hdr">${row}</div>`;
      cells += POS_COLS.map(col => {
        const p = col + row;
        const who = others.get(p);
        // 남이 선 칸에도 그대로 놓을 수 있다 — 막지 않고 보여만 준다(NAI 는 겹침을 허용한다).
        const cls = 'ia-pos-cell' + (p === cur ? ' is-on' : '') + (who ? ' has-other' : '');
        const label = who ? who.join('·') : p;
        const tip = who ? `${p} — ${who.join(', ')} 가 여기 있습니다` : p;
        return `<button type="button" class="${cls}" data-pos="${p}"
          title="${escHtml(tip)}">${escHtml(label)}</button>`;
      }).join('');
    }
    const otherLine = others.size
      ? `<div class="ia-pos-others">${[...others].map(([p, w]) =>
          `<span><b>${escHtml(w.join('·'))}</b> ${escHtml(p)}</span>`).join('')}</div>`
      : '';
    return `<div class="ia-pos-head">캔버스 위치 · NAI V4</div>
      <div class="ia-pos-wrap">
        <div class="ia-pos-grid">${cells}</div>
        <div class="ia-pos-info">
          <div class="ia-pos-cur">${escHtml(cur)}</div>
          <div class="ia-pos-map">centers<br>${escHtml(posText(cur))}</div>
          ${otherLine}
          <button type="button" class="ia-pos-reset" data-pos="${POS_DEFAULT}">중앙으로</button>
        </div>
      </div>`;
  }

  // ── ALT 선택 팝업 ───────────────────────────────────────────────────────
  let altPopup = null;
  let altPopupCid = null;

  function ensureAltPopup() {
    if (altPopup) return altPopup;
    altPopup = document.createElement('div');
    altPopup.className = 'ia-alt-popup';
    altPopup.hidden = true;
    document.body.appendChild(altPopup);
    altPopup.addEventListener('mousedown', event => event.preventDefault());
    altPopup.addEventListener('click', event => {
      const row = event.target.closest('[data-alt]');
      if (!row) return;
      event.stopPropagation();
      toggleAlt(altPopupCid, row.dataset.alt);
    });
    return altPopup;
  }

  function altPopupHtml(c) {
    const on = new Set(c.alt || []);
    let lastG = '';
    const rows = ALT_OPTIONS.map(o => {
      // 23개가 한 줄로 늘어서면 무엇을 고르는지 알 수 없다. 묶음 머리글을 넣는다.
      const head = o.g && o.g !== lastG
        ? `<div class="ia-alt-group">${escHtml(o.g)}</div>` : '';
      lastG = o.g || lastG;
      // 2열이라 영문 태그를 따로 줄 자리가 없다 -> 툴팁으로. 무엇이 프롬프트에
      // 나가는지는 여전히 확인 가능해야 한다(호버).
      return head + `<button type="button"
      class="ia-alt-row${on.has(o.tag) ? ' is-on' : ''}" data-alt="${escHtml(o.tag)}"
      title="${escHtml(`${o.tag} — ${o.n.toLocaleString()}건`)}">
      <span class="ia-alt-box"></span>
      <span class="ia-alt-label">${escHtml(o.label)}</span></button>`;
    }).join('');
    return '<div class="ia-alt-head">원작과 다른 버전 (ALT)</div>' +
      `<div class="ia-alt-list">${rows}</div>` +
      '<div class="ia-alt-foot">캐릭터 태그 바로 뒤에 들어갑니다. ' +
      '<b>비공식</b>=팬 창작, <b>공식</b>=원작에 실제로 나온 다른 모습.</div>';
  }

  function openAltPicker(anchor, cid) {
    const character = state.chars.find(x => x.id === cid);
    if (!character) return;
    if (altPopupCid === cid && altPopup && !altPopup.hidden) { closeAltPicker(); return; }
    const popup = ensureAltPopup();
    altPopupCid = cid;
    popup.innerHTML = altPopupHtml(character);
    popup.hidden = false;
    const rect = anchor.getBoundingClientRect();
    const pr = popup.getBoundingClientRect();
    const left = Math.max(8, Math.min(rect.left, window.innerWidth - pr.width - 8));
    let top = rect.bottom + 6;
    if (top + pr.height > window.innerHeight - 8) top = Math.max(8, rect.top - pr.height - 6);
    popup.style.left = `${Math.round(left)}px`;
    popup.style.top = `${Math.round(top)}px`;
    document.addEventListener('mousedown', onAltOutside, true);
    document.addEventListener('keydown', onAltKeydown, true);
  }

  function closeAltPicker() {
    altPopupCid = null;
    if (altPopup) { altPopup.hidden = true; altPopup.innerHTML = ''; }
    document.removeEventListener('mousedown', onAltOutside, true);
    document.removeEventListener('keydown', onAltKeydown, true);
  }

  function onAltOutside(event) {
    if (altPopup && altPopup.contains(event.target)) return;
    if (event.target.closest?.('[data-charalt]')) return;   // 토글은 버튼 핸들러가 처리
    closeAltPicker();
  }

  function onAltKeydown(event) {
    if (event.key === 'Escape') { event.preventDefault(); closeAltPicker(); }
  }

  /** ALT 토글 — 팝업은 열어 둔 채 버튼 라벨만 제자리에서 고친다.
   *  전체 렌더를 돌리면 편집 중이던 슬롯의 입력이 날아간다(위치 선택과 같은 이유). */
  function toggleAlt(cid, tag) {
    const c = state.chars.find(x => x.id === cid);
    if (!c || !ALT_LABEL.has(tag)) return;
    const cur = new Set(c.alt || []);
    if (cur.has(tag)) cur.delete(tag); else cur.add(tag);
    // 목록 순서를 유지한다 — 프롬프트가 클릭 순서에 따라 달라지면 재현이 안 된다.
    c.alt = ALT_OPTIONS.map(o => o.tag).filter(t => cur.has(t));
    const row = altPopup?.querySelector(`[data-alt="${CSS.escape(tag)}"]`);
    if (row) row.classList.toggle('is-on', cur.has(tag));
    const btn = blocksMount?.querySelector(`[data-charalt][data-cid="${CSS.escape(cid)}"]`);
    if (btn) {
      const tmp = document.createElement('div');
      tmp.innerHTML = altButtonHtml(c);
      const fresh = tmp.firstElementChild;
      btn.className = fresh.className;
      btn.title = fresh.title;
      btn.innerHTML = fresh.innerHTML;
    }
    emitChange();
  }

  // ── 시선 선택 팝업 ─────────────────────────────────────────────────────
  // ALT 팝업과 같은 구조다. 합치지 않은 이유: 목록 출처가 다르고(ALT 는 손으로 고른
  // 10개, 시선은 빌더 산출), 버튼이 붙는 슬롯도 다르다.
  let gazePopup = null;
  let gazePopupCid = null;

  function ensureGazePopup() {
    if (gazePopup) return gazePopup;
    gazePopup = document.createElement('div');
    gazePopup.className = 'ia-alt-popup';
    gazePopup.hidden = true;
    document.body.appendChild(gazePopup);
    gazePopup.addEventListener('mousedown', event => event.preventDefault());
    gazePopup.addEventListener('click', event => {
      const row = event.target.closest('[data-gz]');
      if (!row) return;
      event.stopPropagation();
      toggleGaze(gazePopupCid, row.dataset.gz);
    });
    return gazePopup;
  }

  function gazePopupHtml(c) {
    const on = new Set(c.gaze || []);
    const rows = GAZE_TARGETS.map(o => `<button type="button"
      class="ia-alt-row${on.has(o.tag) ? ' is-on' : ''}" data-gz="${escHtml(o.tag)}">
      <span class="ia-alt-box"></span>
      <span class="ia-alt-label">${escHtml(o.label)}</span>
      <span class="ia-alt-tag">${escHtml(o.tag)}</span>
      <span class="ia-alt-n">${o.n.toLocaleString()}</span></button>`).join('');
    return '<div class="ia-alt-head">시선 — 누구를 보는가</div>' +
      `<div class="ia-alt-list">${rows}</div>` +
      '<div class="ia-alt-foot">캐릭터 프롬프트에 들어갑니다. 그림으로 구분되지 않아 ' +
      '그리드 대신 목록입니다 — <b>상대가 화면에 있어야</b> 제대로 나옵니다.</div>';
  }

  function openGazePicker(anchor, cid) {
    const character = state.chars.find(x => x.id === cid);
    if (!character) return;
    if (gazePopupCid === cid && gazePopup && !gazePopup.hidden) { closeGazePicker(); return; }
    const popup = ensureGazePopup();
    gazePopupCid = cid;
    popup.innerHTML = gazePopupHtml(character);
    popup.hidden = false;
    const rect = anchor.getBoundingClientRect();
    const pr = popup.getBoundingClientRect();
    const left = Math.max(8, Math.min(rect.left, window.innerWidth - pr.width - 8));
    let top = rect.bottom + 6;
    if (top + pr.height > window.innerHeight - 8) top = Math.max(8, rect.top - pr.height - 6);
    popup.style.left = `${Math.round(left)}px`;
    popup.style.top = `${Math.round(top)}px`;
    document.addEventListener('mousedown', onGazeOutside, true);
    document.addEventListener('keydown', onGazeKeydown, true);
  }

  function closeGazePicker() {
    gazePopupCid = null;
    if (gazePopup) { gazePopup.hidden = true; gazePopup.innerHTML = ''; }
    document.removeEventListener('mousedown', onGazeOutside, true);
    document.removeEventListener('keydown', onGazeKeydown, true);
  }

  function onGazeOutside(event) {
    if (gazePopup && gazePopup.contains(event.target)) return;
    if (event.target.closest?.('[data-chargaze]')) return;
    closeGazePicker();
  }

  function onGazeKeydown(event) {
    if (event.key === 'Escape') { event.preventDefault(); closeGazePicker(); }
  }

  /** 시선 토글 — 팝업은 열어 둔 채 버튼 라벨만 제자리에서 고친다(ALT 와 같은 이유). */
  function toggleGaze(cid, tag) {
    const c = state.chars.find(x => x.id === cid);
    if (!c || !GAZE_LABEL.has(tag)) return;
    const cur = new Set(c.gaze || []);
    if (cur.has(tag)) cur.delete(tag); else cur.add(tag);
    // 목록 순서를 유지한다 — 클릭 순서로 프롬프트가 달라지면 재현이 안 된다.
    c.gaze = GAZE_TARGETS.map(o => o.tag).filter(t => cur.has(t));
    const row = gazePopup?.querySelector(`[data-gz="${CSS.escape(tag)}"]`);
    if (row) row.classList.toggle('is-on', cur.has(tag));
    const btn = blocksMount?.querySelector(`[data-chargaze][data-cid="${CSS.escape(cid)}"]`);
    if (btn) {
      const tmp = document.createElement('div');
      tmp.innerHTML = gazeButtonHtml(c);
      const fresh = tmp.firstElementChild;
      btn.className = fresh.className;
      btn.title = fresh.title;
      btn.innerHTML = fresh.innerHTML;
    }
    emitChange();
  }

  function openPositionPicker(anchor, cid) {
    const character = state.chars.find(x => x.id === cid);
    if (!character) return;
    if (posPopupCid === cid && posPopup && !posPopup.hidden) { closePositionPicker(); return; }
    const popup = ensurePosPopup();
    posPopupCid = cid;
    popup.innerHTML = posPopupHtml(character.pos || POS_DEFAULT, cid);
    popup.hidden = false;
    // **버튼 오른쪽**에 붙인다. 예전에는 아래로 폈는데, 이 버튼들이 화면 아래쪽
    // (Assets 스택·캐릭터 헤더)에 있어서 팝업이 결과 이미지를 가렸다(사용자 지적).
    // 오른쪽에 자리가 없으면 왼쪽으로 뒤집는다. 세로는 버튼 가운데에 맞추고 화면 안으로 clamp.
    const rect = anchor.getBoundingClientRect();
    const pr = popup.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    let left = rect.right + 8;
    if (left + pr.width > vw - 8) left = rect.left - pr.width - 8;
    left = Math.max(8, Math.min(left, vw - pr.width - 8));
    let top = rect.top + rect.height / 2 - pr.height / 2;
    top = Math.max(8, Math.min(top, vh - pr.height - 8));
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
    // 토글은 버튼 핸들러가 처리한다. Assets 스택의 POS 버튼도 같은 취급 —
    // 빠지면 mousedown 이 먼저 닫아 버려 눌러도 열리지 않는다.
    if (event.target.closest?.('[data-charpos],[data-as-pos]')) return;
    closePositionPicker();
  }

  function onPosKeydown(event) {
    if (event.key === 'Escape') { event.preventDefault(); closePositionPicker(); }
  }

  /** 위치 선택 → 캔버스 칩과 헤더 점만 in-place 갱신(편집 중 슬롯을 건드리지 않는다). */
  function setCharPosition(cid, pos) {
    const character = state.chars.find(x => x.id === cid);
    if (!character) return;
    const next = /^[A-E][1-5]$/.test(String(pos || '')) ? String(pos) : POS_DEFAULT;
    if (character.pos === next) return;
    character.pos = next;
    refreshPosDot(cid);
    if (posPopup && !posPopup.hidden) posPopup.innerHTML = posPopupHtml(next, posPopupCid);
    emitChange();
    notifyRoster();   // Assets 스택의 [POS C3] 라벨도 이 값을 쓴다
  }

  /** 칩의 [×] — 그 태그 하나만 뺀다. 태그 **문자열**로 지운다(대소문자 무시):
   *  슬롯 태그는 이미 중복 제거되어 있어 문자열이 곧 고유 키이고, 인덱스로 하면
   *  구도 슬롯처럼 앞에 파생 칩이 끼는 곳에서 어긋난다. */
  function removeChipTag(host, tag) {
    if (!host || !tag) return;
    const key = String(tag).toLowerCase();
    let list, put, character = null;
    if (host.dataset.slot) {
      const id = host.dataset.slot;
      if (!Array.isArray(state.slots[id])) return;
      list = state.slots[id];
      put = next => { state.slots[id] = next; };
    } else {
      character = state.chars.find(x => x.id === host.dataset.cid);
      const sub = host.dataset.sub;
      if (!character || !Array.isArray(character.fields[sub])) return;
      list = character.fields[sub];
      put = next => { character.fields[sub] = next; };
    }
    const next = list.filter(t => String(t).toLowerCase() !== key);
    if (next.length === list.length) return;   // 파생 칩(구도 콤보 등) — 지울 것이 없다
    put(next);
    // 프리셋이 넣었던 태그를 사용자가 뺐다면 소유 기록에서도 지운다. 안 지워도
    // 회수는 조용히 지나가지만, 기록이 사실과 달라지면 다음 사람이 헷갈린다.
    if (character?.preset?.tags) {
      for (const [slotKey, owned] of Object.entries(character.preset.tags)) {
        character.preset.tags[slotKey] = (owned || []).filter(t => String(t).toLowerCase() !== key);
      }
    }
    renderBlocks();   // 좌표 점 노출 조건(태그 유무)도 여기서 다시 잡힌다
    emitChange();
    notifyRoster();
  }

  /** 복제본을 놓을 빈 칸. 같은 줄에서 가까운 칸부터 본다 — 원본과 같은 칸에 놓으면
   *  둘이 정확히 겹쳐서 복제한 줄도 모르게 된다. */
  function freePositionCell(from) {
    const used = new Set(state.chars.map(c => c.pos || POS_DEFAULT));
    const src = String(from || POS_DEFAULT);
    const ci = Math.max(0, POS_COLS.indexOf(src[0]));
    const ri = Math.max(0, Number(src[1]) - 1);
    for (let d = 1; d < 5; d++) {
      for (const col of [ci + d, ci - d]) {
        if (col < 0 || col > 4) continue;
        const p = POS_COLS[col] + (ri + 1);
        if (!used.has(p)) return p;
      }
    }
    for (let r = 1; r <= 5; r++) {
      for (const col of POS_COLS) {
        if (!used.has(col + r)) return col + r;
      }
    }
    return POS_DEFAULT;
  }

  /** 캐릭터 복제. 다인원은 비슷한 캐릭터를 여럿 두는 경우가 많아, 처음부터 다시
   *  채우는 대신 복제하고 위치만 바꾸는 쪽이 훨씬 짧다. */
  function duplicateCharacter(cid) {
    if (state.chars.length >= MAX_NAI_CHARACTERS) {
      showToast(`캐릭터 슬롯은 최대 ${MAX_NAI_CHARACTERS}개입니다 (NAI 제한).`, 'error');
      return;
    }
    const at = state.chars.findIndex(c => c.id === cid);
    if (at < 0) return;
    const s = state.chars[at];
    const copy = {
      ...s,
      id: 'c' + (++charSeq),
      open: false,
      pos: freePositionCell(s.pos),
      // 배열·객체는 **전부 새로 만든다.** 얕은 복사로 두면 복제본에서 태그를 지울 때
      // 같은 배열을 공유하는 원본에서도 사라진다.
      alt: [...(s.alt || [])],
      gaze: [...(s.gaze || [])],
      preset: s.preset
        ? {...s.preset, tags: Object.fromEntries(
            Object.entries(s.preset.tags || {}).map(([k, v]) => [k, [...(v || [])]]))}
        : null,
      fields: Object.fromEntries(
        Object.entries(s.fields || {}).map(([k, v]) => [k, [...(v || [])]])),
    };
    state.chars.splice(at + 1, 0, copy);
    renderBlocks();
    emitChange();
    notifyRoster();
    showToast(`C${at + 1} 을 복제했습니다 · 위치 ${copy.pos}`);
  }

  /** 마지막 하나가 아니면 캐릭터 슬롯 삭제. */
  function deleteCharacter(cid) {
    if (state.chars.length <= 1) {
      showToast('마지막 캐릭터 슬롯은 삭제할 수 없습니다.', 'error');
      return;
    }
    const idx = state.chars.findIndex(c => c.id === cid);
    if (idx < 0) return;
    if (presetCid === cid) closePresetPanel();   // 사라진 슬롯을 겨냥한 팝업은 닫는다
    state.chars.splice(idx, 1);
    // 편집 팝업을 닫고(참조 슬롯이 사라졌을 수 있음) 목록을 다시 그린다(라벨 C1..Cn 재계산).
    closePanel();
    emitChange();
    notifyRoster();   // 스택에 유령 버튼이 남으면 눌러도 아무 일이 없다
  }

  /** ACTIVE <-> OFF. 카드 하나만 in-place 갱신 — 편집 중 슬롯을 안 건드린다. */
  function toggleCharEnabled(cid) {
    const c = state.chars.find(x => x.id === cid);
    if (!c) return;
    c.state = c.state === 'active' ? 'disabled' : 'active';
    const enabled = c.state === 'active';
    // 껐다 켜면 좌표 UI 대상이 바뀐다 — 바뀌었으면 통째로 다시 그리고 제자리 갱신은 건너뛴다.
    if (syncPosMembership()) {
      emitChange();
      notifyRoster();
      return;
    }
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
    notifyRoster();   // 스택이 OFF 를 흐리게 표시한다 — 안 알리면 켜진 것처럼 보인다
  }

  // ---------------------------------------------------------------- 캐릭터 프리셋
  //
  // 캐릭터 뷰어(작품 1,644 / 캐릭터 9,738)의 자산을 그대로 재사용해 슬롯을 한 번에 채운다.
  //
  //   검색(이름)  : /api/character-viewer/list?query=miku
  //   검색(작품)  : /api/character-viewer/groups?query=genshin -> list?group=<key>
  //   검색(태그)  : /api/character-viewer/list?query=*blue hair  (`*` = 태그 정확 일치, 쉼표=AND)
  //   슬롯 배정   : /api/character-preset?group=&character=
  //   썸네일      : 목록 응답이 주는 thumbnail_url 그대로(뷰어 탭과 같은 파일·같은 캐시)
  //
  // **슬롯 배정을 런타임에 계산하지 않는다.** tools/build_character_presets.mjs 가
  // interactiveAxes.mjs 의 CHAR_SLOTS + THUMB_TAGS/PALETTES/SLIDERS 를 뒤집어
  // `data/character_presets.json` 에 미리 계산해 뒀고(커버리지 98.8%), 백엔드가 거기서
  // 한 건씩 꺼내 준다. 사전이 3.9MB 라 프론트로 통째로 내리지 않는다 —
  // 이유는 core/character_viewer_service.py `character_presets()` 주석 참조.
  //
  // 목록은 **1행 2열 + 무한 스크롤**이다. 9,738명을 한 번에 그리면 무겁다.
  // 썸네일이 있는 캐릭터는 40명(0.4%)뿐이라 그림 없는 칸은 이니셜 타일로 뜬다.
  // 작품은 1,644개 중 874개(53%)가 1명짜리라 목록으로 나열하지 않는다 — 검색어에 걸린
  // 작품만 칩으로 최대 8개 보이고, 누르면 그 작품으로 좁힌다.
  //
  // 줄을 누르면 **누른 자리에 앵커된 작은 카드**가 뜬다. 태그 사전 호버 카드와 같은
  // 마크업(`tag-tooltip-*` / `char-*` 클래스)을 써서 생김새가 저절로 같다.

  // ---- 배타 축(팔레트·슬라이더) ----
  // **예전의 전체 역인덱스가 아니다.** 태그 5,850개를 훑어 슬롯을 정하던 코드는 사전 파일로
  // 옮겨 갔다. 여기 남은 것은 팔레트 3개 + 슬라이더 2개(태그 50여 개)뿐이고 쓰임새도 둘이다:
  //   1) 사전이 다루지 않는 `breast_size_top` 한 개를 제자리에 넣는 것
  //   2) 프리셋을 넣은 뒤 **사용자가 직접 적어 둔** 같은 축 태그와 부딪히는지 알리는 것
  let exclusiveTagAxis = null;

  function exclusiveAxisOf(tag) {
    if (!exclusiveTagAxis) {
      exclusiveTagAxis = new Map();
      for (const [ref, rows] of Object.entries(PALETTES || {})) {
        for (const d of (rows || [])) exclusiveTagAxis.set(String(d.tag).toLowerCase(), ref);
      }
      for (const [ref, def] of Object.entries(SLIDERS || {})) {
        for (const t of ((def || {}).steps || [])) exclusiveTagAxis.set(String(t).toLowerCase(), ref);
      }
    }
    return exclusiveTagAxis.get(String(tag || '').trim().toLowerCase()) || '';
  }

  /** 축 ref -> 그 축이 붙어 있는 슬롯 이름(CHAR_SUBS 에서 파생). */
  function slotOfAxis(axis) {
    if (!axis) return '';
    for (const slot of CHAR_SUBS) {
      for (const sec of (slot.sections || [])) {
        if (sec.ref === axis || sec.mainPalette === axis || sec.extraPalette === axis) return slot.key;
      }
    }
    return '';
  }

  // ---- 상태 ----
  const PRESET_PAGE = 40;            // 2열 x 20행. 스크롤이 끝에 닿으면 이어 붙인다.
  const PRESET_THIN_ROWS = 50;       // 근거 행수 하위 25%(실측 p25=49행)

  let presetPanel = null;      // 지연 생성 후 재사용 (.ia-panel 구조를 그대로 쓴다)
  let presetCid = null;        // 어느 캐릭터 슬롯에 넣을지
  let presetMode = 'name';     // 'name' | 'tag'
  let presetQuery = '';
  let presetGroup = '';        // 작품으로 좁혔을 때의 그룹 키
  let presetSentGroup = '';    // 실제로 서버에 보낸 값(이어받기가 같은 조건을 유지한다)
  let presetSentQuery = '';
  let presetResults = [];
  let presetGroups = [];
  let presetTotal = 0;
  let presetPage = 0;
  let presetPages = 1;
  let presetLoose = false;     // 태그 검색이 부분 일치로 물러섰나
  let presetBusy = false;
  let presetMore = false;      // 이어붙이는 중
  let presetError = '';
  let presetSeq = 0;
  let presetTimer = null;
  let presetObserver = null;   // 무한 스크롤 sentinel 관찰자

  // 앵커 카드
  let cardEl = null;
  let cardData = null;         // /api/character-preset 응답
  let cardRows = [];           // [{key, tag, pct, cls, slot, axis, on, why}]
  let cardPick = new Set();
  let cardAnchor = null;       // 마지막 앵커 사각형(칩 토글 후 자리 유지)
  let cardSeq = 0;

  function presetCharLabel() {
    const i = state.chars.findIndex(c => c.id === presetCid);
    return i >= 0 ? 'C' + (i + 1) : '';
  }

  function fmtCount(n) {
    const v = Number(n || 0);
    if (v >= 1e6) return (v / 1e6).toFixed(1).replace(/\.0$/, '') + 'M';
    if (v >= 1e3) return Math.round(v / 1e3) + 'k';
    return String(v);
  }

  async function presetFetch(url) {
    const res = await fetch(url, {cache: 'no-store'});
    const data = await res.json();
    if (!res.ok || (data && data.error)) throw new Error((data && data.error) || ('HTTP ' + res.status));
    return data;
  }

  function presetListUrl(group, query, page) {
    return '/api/character-viewer/list'
      + `?group=${encodeURIComponent(group || '__ALL__')}`
      + `&query=${encodeURIComponent(query || '')}`
      + `&page=${Number(page) || 0}&per_page=${PRESET_PAGE}&thumb_first=true`;
  }

  /** 새 검색(append=false) 또는 다음 쪽 이어받기(append=true). */
  async function presetSearch({append = false} = {}) {
    const seq = ++presetSeq;
    if (append) {
      if (presetMore || presetBusy || presetPage + 1 >= presetPages) return;
      presetMore = true;
    } else {
      presetBusy = true;
      presetError = '';
      presetLoose = false;
      presetPage = 0;
      presetPages = 1;
      renderPresetBody();
    }
    const q = presetQuery.trim();
    try {
      let data = null;
      if (append) {
        data = await presetFetch(presetListUrl(presetSentGroup, presetSentQuery, presetPage + 1));
      } else if (presetGroup) {
        presetSentGroup = presetGroup; presetSentQuery = q;
        data = await presetFetch(presetListUrl(presetSentGroup, presetSentQuery, 0));
        presetGroups = [];
      } else if (presetMode === 'tag') {
        presetSentGroup = '';
        if (!q) {
          presetResults = []; presetTotal = 0; presetGroups = [];
        } else {
          // `*` = 태그 정확 일치(쉼표로 여러 개면 AND). 조각을 치면 0건이 나오므로
          // 그때만 부분 일치로 물러서고, 그 사실을 화면에 알린다.
          presetSentQuery = '*' + q;
          data = await presetFetch(presetListUrl('', presetSentQuery, 0));
          if (seq !== presetSeq) return;
          if (!(data.total || 0)) {
            presetSentQuery = q;
            data = await presetFetch(presetListUrl('', presetSentQuery, 0));
            presetLoose = true;
          }
          presetGroups = [];
        }
      } else {
        // 이름 검색은 캐릭터명(= aliases)을, 작품 검색은 그룹 키를 본다.
        // ※ aliases 는 실측상 전원 이름과 동일하다(9,738명 중 이름과 다른 별칭 0건,
        //    data/character_analysis.json · data/copyright_groups.json 양쪽 확인).
        presetSentGroup = ''; presetSentQuery = q;
        const [list, groups] = await Promise.all([
          presetFetch(presetListUrl('', q, 0)),
          q ? presetFetch('/api/character-viewer/groups?query=' + encodeURIComponent(q))
            : Promise.resolve({items: []}),
        ]);
        if (seq !== presetSeq) return;
        data = list;
        presetGroups = (groups.items || [])
          .filter(g => g && g.key && g.key !== '__ALL__').slice(0, 8);
      }
      if (seq !== presetSeq) return;
      if (data) {
        presetPages = Math.max(1, Number(data.total_pages || 1));
        presetTotal = Number(data.total || 0);
        if (append) {
          presetPage = Number(data.page || presetPage + 1);
          const items = data.items || [];
          presetResults = presetResults.concat(items);
          presetMore = false;
          presetAppendRows(items);
          return;
        }
        presetPage = Number(data.page || 0);
        presetResults = data.items || [];
      }
    } catch (error) {
      if (seq !== presetSeq) return;
      presetMore = false;
      if (append) { renderPresetBody(); return; }
      presetResults = []; presetTotal = 0; presetGroups = [];
      presetError = '캐릭터 목록을 불러오지 못했습니다. (' + (error?.message || 'error') + ')';
    }
    if (seq !== presetSeq) return;
    presetBusy = false;
    presetMore = false;
    renderPresetBody();
  }

  function presetQueueSearch() {
    clearTimeout(presetTimer);
    presetTimer = setTimeout(() => { void presetSearch(); }, 180);
  }

  // ---- 목록 렌더 ----

  /** 그림 없는 캐릭터(99.6%)의 폴백 타일 — 이름 이니셜. */
  function presetInitial(name) {
    // 인라인 onerror 문자열에 그대로 들어가므로 영숫자만 남긴다(따옴표 유입 차단).
    const words = String(name || '').replace(/\(.*?\)/g, ' ')
      .replace(/[^0-9A-Za-z\s]/g, ' ').trim().split(/\s+/).filter(Boolean);
    if (!words.length) return '#';
    return (words[0][0] + (words[1] ? words[1][0] : '')).toUpperCase();
  }

  function presetThumbHtml(url, name) {
    if (url) {
      // 썸네일이 지워졌거나 인덱스가 어긋나면 조용히 이니셜 타일로 떨어진다.
      return `<span class="ia-cp-thumb"><img src="${escHtml(url)}" alt="" loading="lazy" decoding="async"
        onerror="this.parentNode.classList.add('is-none');this.parentNode.innerHTML='${escHtml(presetInitial(name))}';"></span>`;
    }
    return `<span class="ia-cp-thumb is-none">${escHtml(presetInitial(name))}</span>`;
  }

  function presetRowHtml(item) {
    const count = Number(item.count || 0);
    const thin = count < PRESET_THIN_ROWS;
    return `<button type="button" class="ia-cp-row"
      data-cp-g="${escHtml(item.group)}" data-cp-c="${escHtml(item.character)}"
      data-cp-t="${escHtml(item.thumbnail_url || '')}"
      title="${escHtml(item.character + ' · ' + item.group)}">
      ${presetThumbHtml(item.thumbnail_url, item.character)}
      <span class="ia-cp-info">
        <span class="ia-cp-name">${escHtml(item.character)}</span>
        <span class="ia-cp-meta">${escHtml(item.group)}
          <span class="ia-cp-rows${thin ? ' is-thin' : ''}">${count.toLocaleString()}</span></span>
      </span></button>`;
  }

  function presetSearchBodyHtml() {
    const parts = [];
    if (presetGroup) {
      parts.push(`<div class="ia-cp-scope">작품 <b>${escHtml(presetGroup)}</b>
        <button type="button" class="ia-cp-clear" data-cp-group="">전체에서 다시 찾기</button></div>`);
    } else if (presetGroups.length) {
      parts.push('<div class="ia-cp-groups">' + presetGroups.map(g =>
        `<button type="button" class="ia-cp-group" data-cp-group="${escHtml(g.key)}"
          title="이 작품의 캐릭터만 보기">${escHtml(g.name)}<span>${Number(g.count || 0)}</span></button>`
      ).join('') + '</div>');
    }
    if (presetError) {
      parts.push(`<div class="ia-axes-empty">${escHtml(presetError)}</div>`);
      return parts.join('');
    }
    if (presetLoose) {
      parts.push('<div class="ia-cp-note">정확히 그 태그를 가진 캐릭터가 없어 <b>부분 일치</b>로 찾았습니다.</div>');
    }
    if (presetBusy && !presetResults.length) {
      parts.push('<div class="ia-axes-empty">불러오는 중…</div>');
      return parts.join('');
    }
    if (!presetResults.length) {
      parts.push('<div class="ia-axes-empty">' + (presetQuery.trim()
        ? escHtml(presetQuery.trim()) + ' — 맞는 캐릭터가 없습니다.'
        : (presetMode === 'tag'
          ? '태그를 입력하세요. 예: <b>blue hair</b> · <b>twintails, blue eyes</b>'
          : '캐릭터 이름이나 작품 이름을 입력하세요. 예: <b>miku</b> · <b>genshin</b>')) + '</div>');
      return parts.join('');
    }
    parts.push(`<div class="ia-cp-count">${presetTotal.toLocaleString()}명</div>`);
    parts.push('<div class="ia-cp-list">' + presetResults.map(presetRowHtml).join('') + '</div>');
    // sentinel — 이것이 보이면 다음 쪽을 이어 붙인다(IntersectionObserver).
    if (presetPage + 1 < presetPages) parts.push('<div class="ia-cp-sentinel" id="iaCpSentinel">더 불러오는 중…</div>');
    return parts.join('');
  }

  function presetAppendRows(items) {
    const list = presetPanel && presetPanel.querySelector('.ia-cp-list');
    if (!list) { renderPresetBody(); return; }
    list.insertAdjacentHTML('beforeend', items.map(presetRowHtml).join(''));
    const sentinel = presetPanel.querySelector('#iaCpSentinel');
    if (sentinel && presetPage + 1 >= presetPages) sentinel.remove();
    presetBindSentinel();
  }

  function presetBindSentinel() {
    if (presetObserver) { presetObserver.disconnect(); presetObserver = null; }
    if (!presetPanel || typeof IntersectionObserver !== 'function') return;
    const sentinel = presetPanel.querySelector('#iaCpSentinel');
    if (!sentinel) return;
    const root = presetPanel.querySelector('.ia-panel-body');
    presetObserver = new IntersectionObserver(entries => {
      if (entries.some(e => e.isIntersecting)) void presetSearch({append: true});
    }, {root: root || null, rootMargin: '160px'});
    presetObserver.observe(sentinel);
  }

  // ---- 앵커 카드 (태그 사전 호버 카드와 같은 마크업) ----

  /** 응답 -> 칩 목록. 순서는 **태그 사전이 주는 원래 순서**(머리색·눈색 -> 특징 -> 가슴)다. */
  function cardRowsFrom(data) {
    const known = new Map();     // tag(소문자) -> {slot, axis, pct, on, why}
    for (const [slot, list] of Object.entries(data.slots || {})) {
      for (const it of (list || [])) {
        known.set(String(it.tag).toLowerCase(), {slot, axis: it.axis, pct: it.pct, on: true, why: ''});
      }
    }
    for (const it of (data.off || [])) {
      const key = String(it.tag).toLowerCase();
      if (known.has(key)) continue;
      known.set(key, {slot: it.slot, axis: it.axis, pct: it.pct, on: false, why: it.why || ''});
    }
    const rows = [];
    const seen = new Set();
    const push = (tag, pct, cls) => {
      const key = String(tag || '').trim().toLowerCase();
      if (!key || seen.has(key)) return;
      seen.add(key);
      const hit = known.get(key);
      rows.push({
        key, cls, tag: String(tag).trim(),
        pct: hit && hit.pct != null ? Number(hit.pct) : (pct == null ? null : Number(pct)),
        slot: hit ? hit.slot : '', axis: hit ? hit.axis : '',
        on: !!(hit && hit.on), why: hit ? hit.why : '',
      });
    };
    const details = (data.info && data.info.details) || {};
    (details.personal_color || []).forEach(e => push(e.tag, e.pct, 'ct-pc'));
    (details.characteristics || []).forEach(e => push(e.tag, e.pct, 'ct-ch'));
    if (details.breast_size_top) push(details.breast_size_top, null, 'ct-body');
    // 태그 사전에 캐릭터가 없으면(character_details 없음) 사전 쪽 목록으로 채운다.
    for (const list of Object.values(data.slots || {})) {
      for (const it of (list || [])) push(it.tag, it.pct, 'ct-ch');
    }
    for (const it of (data.off || [])) push(it.tag, it.pct, 'ct-ch');
    // 가슴 크기는 사전이 다루지 않는다 — build_character_presets.mjs 가
    // personal_color/characteristics 만 읽고 `breast_size` 분포는 건너뛴다.
    // 슬라이더(배타) 축이라 배정 규칙이 이미 정해져 있다: 문턱 없이 최빈값 하나.
    // 그 축이 아직 비어 있을 때만 채운다.
    for (const row of rows) {
      if (row.slot) continue;
      const axis = exclusiveAxisOf(row.tag);
      const slot = slotOfAxis(axis);
      if (!axis || !slot) continue;
      if (rows.some(o => o !== row && o.axis === axis && o.on)) continue;
      row.slot = slot; row.axis = axis; row.on = true;
    }
    return rows;
  }

  function cardPctHtml(row) {
    if (row.pct == null) return '';
    const v = row.pct >= 10 ? Math.round(row.pct) : Number(row.pct).toFixed(1);
    return ` <small>${v}%</small>`;
  }

  function cardHtml() {
    const data = cardData;
    const info = data.info || {};
    const chips = cardRows.map(row => {
      if (!row.slot) {
        return `<span class="tag-tooltip-extra-tag char-tag is-none"
          title="Interactive 슬롯에 자리가 없는 태그입니다 — 슬롯 입력창에 직접 쓸 수 있습니다.">${escHtml(row.tag)}${cardPctHtml(row)}</span>`;
      }
      const on = cardPick.has(row.key);
      const why = row.why === 'below' ? ' · 과반 미만이라 꺼 뒀습니다'
        : row.why === 'exclusive' ? ' · 같은 축에 더 흔한 값이 있습니다' : '';
      return `<span class="tag-tooltip-extra-tag char-tag ${row.cls}${on ? ' on' : ''}"
        role="button" tabindex="0" aria-pressed="${on}" data-cp-chip="${escHtml(row.key)}"
        title="${escHtml(row.slot + ' 슬롯' + why)}">${escHtml(row.tag)}${cardPctHtml(row)}</span>`;
    }).join('');
    const picked = cardRows.filter(r => r.slot && cardPick.has(r.key));
    const allTags = cardRows.map(r => r.tag).join(', ');
    const rows = Number(data.rows || 0);
    const charTags = characterTagsOf(data);
    // 카드 왼쪽에 큰 썸네일을 붙인다(사용자 요청). 목록 칸은 80px 이라 얼굴만 겨우 보이고,
    // 고를 때는 그림을 크게 봐야 한다. 소스는 목록과 같은 `thumbnail_url`(size=grid, 384px)
    // 이라 이미 받아 둔 것을 그대로 쓴다 — 새 요청이 아니다.
    // 썸네일이 없으면(사용자 것도 번들 폴백도 없을 때) 이니셜 타일로 떨어진다.
    const thumbUrl = String(data.thumbnail_url || info.thumbnail_url || '');
    const thumbHtml = '<div class="ia-cp-card-thumb">' +
      (thumbUrl
        ? `<img src="${escHtml(thumbUrl)}" alt="" decoding="async"
             onerror="this.parentNode.classList.add('is-none');this.parentNode.innerHTML='${escHtml(presetInitial(data.name || ''))}';">`
        : escHtml(presetInitial(data.name || ''))) +
      '</div>';
    return thumbHtml + '<div class="ia-cp-card-body">' +
      '<div class="tag-tooltip-main">' +
      `<span class="tag-tooltip-tag">${escHtml(data.name)}</span>` +
      (info.count ? `<span class="tag-tooltip-count">${escHtml(fmtCount(info.count))}</span>` : '') +
      (info.group ? ` <span class="tag-tooltip-group">${escHtml(info.group)}</span>` : '') +
      (info.desc ? `<span class="tag-tooltip-desc">${escHtml(info.desc)}</span>` : '') +
      '</div>' +
      '<div class="tag-tooltip-extra char-details-row">' +
        `<span class="char-copyright">${escHtml(data.work || '')}</span>${chips}</div>` +
      // 주 동작(캐릭터 태그 + 대표 태그) : 보조(캐릭터 태그만) = 2 : 1. 색으로도 갈라 둔다.
      // 숫자 배지는 **목록에서 고른 개수**다 — 캐릭터 태그는 항상 따라가므로 세지 않는다.
      '<div class="ia-cp-actions">' +
        `<button type="button" class="ia-cp-act is-primary" data-cp-apply="all"${picked.length ? '' : ' disabled'}
          title="${escHtml(charTags.join(', '))} + 고른 대표 태그를 ${escHtml(presetCharLabel())} 슬롯들에 넣습니다">전부 적용<small>${picked.length}</small></button>` +
        `<button type="button" class="ia-cp-act is-secondary" data-cp-apply="char"
          title="${escHtml(charTags.join(', '))} — 대표 태그 없이 캐릭터 태그만 넣습니다">캐릭터만</button>` +
      '</div>' +
      // Copy All 은 위 두 버튼에서 뺐다 — 클립보드로 내보내는 것은 성격이 다른 행동이라
      // 같은 줄에 두면 2:1 강조가 흐려진다. 기능은 남긴다(Interactive 밖으로 태그를
      // 꺼내는 유일한 통로다). 표본 수는 그대로 오른쪽.
      '<div class="char-copy-row">' +
        `<button type="button" class="char-copy-btn" data-cp-copy="${escHtml(allTags)}"
          title="대표 태그 전부를 클립보드로">\u{1F4CB} 복사</button>` +
        `<small class="char-sample-count${rows < PRESET_THIN_ROWS ? ' is-thin' : ''}">${rows.toLocaleString()} samples</small>` +
      '</div>' +
      '</div>';
  }

  /** `캐릭터만` 이 넣을 태그 — 캐릭터 태그 + (필요할 때만) 작품 태그.
   *
   *  Danbooru 캐릭터 태그는 `ganyu (genshin impact)` 처럼 작품을 괄호로 단 것과
   *  `hatsune miku` 처럼 안 단 것이 섞여 있다. 뒤엣것만 작품을 따로 줘야 식별된다.
   *  판정은 tools/build_character_wildcards.py 와 **같은 규칙**이다(`f"({work})" in name`).
   *
   *  프론트에서 다시 판정하는 이유: 응답에 `work`/`name` 이 이미 둘 다 들어 있어 서버가
   *  한 줄 더 계산해 보내도 사본 수는 줄지 않고(빌더 쪽 사본은 그대로 남는다), 라우트를
   *  고치면 백엔드 재시작이 또 필요하다. **규칙을 바꾸면 두 곳을 같이 고쳐라.**
   *
   *  실측(9,738명): 이름이 `(작품)` 을 그대로 단 것 2,882(29.6%) -> 작품 생략.
   *  괄호는 있지만 작품 문자열이 다른 것 1,774(18.2%)와 괄호가 없는 것 5,082(52.2%)
   *  -> 작품 추가(예: `fighter (7th dragon)` + `7th dragon (series)`). */
  function characterTagsOf(data) {
    const name = String((data && data.name) || '').trim();
    const work = String((data && data.work) || '').trim();
    if (!name) return [];
    return (work && !name.includes(`(${work})`)) ? [name, work] : [name];
  }

  function ensureCard() {
    if (cardEl && document.body.contains(cardEl)) return cardEl;
    cardEl = document.createElement('div');
    cardEl.className = 'ia-cp-card';
    cardEl.hidden = true;
    document.body.appendChild(cardEl);
    cardEl.addEventListener('click', onCardClick);
    return cardEl;
  }

  /** 앵커 팝업 자리잡기 — 좌표 팝업(openPositionPicker)과 같은 규약이다. */
  function positionPresetCard() {
    if (!cardEl || cardEl.hidden || !cardAnchor) return;
    const box = cardEl.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const left = Math.max(8, Math.min(cardAnchor.left, vw - box.width - 8));
    let top = cardAnchor.bottom + 6;
    if (top + box.height > vh - 8) top = Math.max(8, cardAnchor.top - box.height - 6);
    cardEl.style.left = Math.round(left) + 'px';
    cardEl.style.top = Math.round(top) + 'px';
  }

  async function openPresetCard(anchor, group, character, thumbUrl = '') {
    const seq = ++cardSeq;
    const rect = anchor.getBoundingClientRect();
    cardAnchor = {left: rect.left, top: rect.top, bottom: rect.bottom};
    const el = ensureCard();
    el.hidden = false;
    el.innerHTML = '<div class="tag-tooltip-desc">불러오는 중…</div>';
    positionPresetCard();
    document.addEventListener('mousedown', onCardOutside, true);
    let data;
    try {
      data = await presetFetch('/api/character-preset?group=' + encodeURIComponent(group)
        + '&character=' + encodeURIComponent(character));
    } catch (error) {
      if (seq !== cardSeq) return;
      cardData = null; cardRows = []; cardPick = new Set();
      el.innerHTML = `<div class="tag-tooltip-desc">${escHtml(error?.message || '프리셋을 불러오지 못했습니다.')}</div>`;
      positionPresetCard();
      return;
    }
    if (seq !== cardSeq) return;
    // `/api/character-preset` 은 슬롯 배정표만 준다. 큰 썸네일은 목록 줄이 이미 들고
    // 있는 URL 을 그대로 쓴다(같은 파일·같은 캐시라 추가 요청이 아니다).
    cardData = {...data, thumbnail_url: thumbUrl};
    cardRows = cardRowsFrom(data);
    cardPick = new Set(cardRows.filter(r => r.slot && r.on).map(r => r.key));
    el.innerHTML = cardHtml();
    positionPresetCard();
  }

  /** 카드를 열지 않고 프리셋을 슬롯에 바로 넣는다(Assets 바의 캐릭터 검색용).
   *  좌측 경로(슬롯 열기 -> 프리셋 -> 검색 -> 카드 -> 적용)와 **같은 함수**를 태운다 —
   *  여기서 갈라지면 이전 프리셋 회수·배타 축 교체 규약이 두 벌이 된다.
   *  kind: 'char' = 캐릭터 태그만 / 'all' = 카드가 기본으로 고르는 태그 전부. */
  async function applyCharacterPresetTo(cid, {group, character, thumb = '', kind = 'char'} = {}) {
    if (!cid || !group || !character) return false;
    if (!state.chars.some(c => c.id === cid)) return false;
    const seq = ++cardSeq;
    let data;
    try {
      data = await presetFetch('/api/character-preset?group=' + encodeURIComponent(group)
        + '&character=' + encodeURIComponent(character));
    } catch (error) {
      showToast('프리셋을 불러오지 못했습니다. (' + (error?.message || 'error') + ')', 'error');
      return false;
    }
    // 그 사이 다른 카드가 열렸으면(cardSeq 가 올랐으면) 이 응답은 남의 것을 덮어쓴다.
    if (seq !== cardSeq) return false;
    // 읽는 동안 슬롯이 지워졌을 수 있다 — 번호가 아니라 id 로 다시 확인한다.
    if (!state.chars.some(c => c.id === cid)) {
      showToast('그 캐릭터 슬롯이 없습니다.', 'error');
      return false;
    }
    presetCid = cid;
    cardData = {...data, thumbnail_url: thumb};
    cardRows = cardRowsFrom(data);
    cardPick = new Set(cardRows.filter(r => r.slot && r.on).map(r => r.key));
    presetApplyCard(kind === 'all' ? 'all' : 'char');
    return true;
  }

  function closePresetCard() {
    cardSeq++;
    cardData = null; cardRows = []; cardPick = new Set(); cardAnchor = null;
    if (cardEl) { cardEl.hidden = true; cardEl.innerHTML = ''; }
    document.removeEventListener('mousedown', onCardOutside, true);
  }

  function onCardOutside(event) {
    if (cardEl && cardEl.contains(event.target)) return;
    if (event.target.closest?.('.ia-cp-row')) return;   // 다른 줄은 그 줄로 옮겨 연다
    closePresetCard();
  }

  function onCardClick(event) {
    const chip = event.target.closest('[data-cp-chip]');
    if (chip) {
      const key = chip.getAttribute('data-cp-chip');
      if (cardPick.has(key)) {
        cardPick.delete(key);
      } else {
        cardPick.add(key);
        // 배타 축은 라디오처럼 — 같은 축의 다른 값은 꺼진다(그리드의 팔레트와 같은 규칙).
        const row = cardRows.find(r => r.key === key);
        const axis = row && (exclusiveAxisOf(row.tag) || '');
        if (axis) cardRows.forEach(r => { if (r !== row && exclusiveAxisOf(r.tag) === axis) cardPick.delete(r.key); });
      }
      cardEl.innerHTML = cardHtml();
      positionPresetCard();
      return;
    }
    const copy = event.target.closest('[data-cp-copy]');
    if (copy) {
      const text = copy.getAttribute('data-cp-copy') || '';
      try {
        void navigator.clipboard.writeText(text);
        showToast('태그를 복사했습니다.');
      } catch (_) { showToast('복사하지 못했습니다.', 'error'); }
      return;
    }
    const apply = event.target.closest('[data-cp-apply]');
    if (apply) presetApplyCard(apply.getAttribute('data-cp-apply') || 'all');
  }

  // ---- 적용 / 회수 ----

  /** 고른 태그를 캐릭터 슬롯에 넣는다.
   *
   *  **직전에 이 슬롯에 넣었던 프리셋 태그만 정확히 회수한다.** 사용자가 손으로 적은 것은
   *  건드리지 않는다 — 그래서 '축이 같으면 지운다' 같은 규칙 대신 **넣은 것을 기억**한다
   *  (`character.preset.tags`, 캐릭터 슬롯마다 독립이다).
   *  그 사이 사용자가 지운 태그는 못 찾을 뿐이니 조용히 넘어간다. */
  function presetApplyCard(kind = 'all') {
    const character = state.chars.find(c => c.id === presetCid);
    if (!character || !cardData) return;
    // `캐릭터만` = 대표 태그로 흩지 않고 캐릭터 태그 자체만 넣는다.
    // `전부 적용` = 캐릭터 태그 **+** 고른 대표 태그.
    //
    // 예전에는 `전부 적용` 이 대표 태그만 넣고 캐릭터 태그를 뺐다. 그래서 프리셋 버튼에는
    // `akemi homura` 가 떠 있는데 정작 생성 프롬프트는 `girl, long hair, black hair, ...`
    // 로 나가, 이름이 어디에도 없었다(사용자 지적 2026-08-05). 캐릭터를 골랐으면 그
    // 캐릭터가 나와야 한다 — '전부'라는 말도 그쪽이다.
    // 넣는 자리·회수 규약은 두 경로가 완전히 같다 — 여기서 갈라지면 둘을 오갈 때
    // 이전 것이 남는다.
    const charRows = characterTagsOf(cardData)
      .map(tag => ({tag, key: tag.toLowerCase(), slot: CHAR_TAG_SLOT, axis: ''}));
    const picked = kind === 'char' ? [] : cardRows.filter(r => r.slot && cardPick.has(r.key));
    // 캐릭터 태그가 먼저다 — buildCharPrompt 가 슬롯 순서대로 잇고 캐릭터 슬롯이 맨 앞이다.
    const chosen = kind === 'char' ? charRows : [...charRows, ...picked];
    if (kind === 'char' ? !charRows.length : !picked.length) {
      showToast(kind === 'char' ? '캐릭터 태그를 알 수 없습니다.' : '넣을 태그를 하나 이상 고르세요.', 'error');
      return;
    }

    const recalled = presetRecall(character);

    const bySlot = new Map();
    for (const row of chosen) {
      if (!bySlot.has(row.slot)) bySlot.set(row.slot, []);
      bySlot.get(row.slot).push(row);
    }
    // 배타 축(머리색·눈색·피부색·길이·가슴)은 **값이 하나만 유효하다.** 회수 뒤에도 그 자리에
    // 뭔가 남아 있으면(슬라이더 기본값 `long hair`·`medium breasts`, 또는 사용자가 직접 고른
    // 색) 새 값을 그냥 더할 수 없다 — `long hair, short hair` 같은 모순이 프롬프트로 나간다.
    // 그래서 배타 축에 한해 자리를 비우고 넣는다. 이건 '사용자 태그를 지우는 것'이 아니라
    // 그리드의 팔레트/슬라이더가 이미 하는 일과 같은 규칙이다(setMainColor / setExclusive).
    // 더해지는 태그(`twintails` 등)는 절대 건드리지 않는다.
    const replaced = [];
    const owned = {};
    for (const [slotKey, rows] of bySlot) {
      let kept = (character.fields[slotKey] || []).slice();
      for (const row of rows) {
        const axis = exclusiveAxisOf(row.tag);
        if (!axis) continue;
        kept = kept.filter(t => {
          if (String(t).toLowerCase() === row.key) return true;
          if (exclusiveAxisOf(t) !== axis) return true;
          replaced.push(t);
          return false;
        });
      }
      const have = new Set(kept.map(t => String(t).toLowerCase()));
      const mine = [];
      for (const row of rows) {
        const lower = row.key;
        // 이미 있던 태그는 **내 소유로 적지 않는다.** 사용자가 직접 넣었을 수 있고,
        // 그러면 다음 프리셋이 남의 것을 회수하게 된다.
        if (have.has(lower)) continue;
        have.add(lower);
        kept.push(row.tag);
        mine.push(row.tag);
      }
      character.fields[slotKey] = kept;
      if (mine.length) owned[slotKey] = mine;
    }
    character.preset = {work: cardData.work, name: cardData.name, tags: owned};
    character.name = cardData.name;

    closePresetCard();
    closePresetPanel();
    // **펼침 상태는 건드리지 않는다.** 예전에는 적용한 슬롯을 강제로 펼쳤는데, 그때는
    // 프리셋 버튼이 펼친 슬롯 안에만 있어서 이미 열려 있었다. 지금은 헤더에서도 눌리므로
    // 접어 둔 카드가 제멋대로 열린다(사용자 지적). 접힌 카드도 헤더 요약줄에 새 태그가
    // 그대로 보이고 토스트도 뜨므로, 열어 주지 않아도 결과는 확인된다.
    renderBlocks();
    emitChange();
    notifyRoster();   // 이름과 열린 슬롯이 바뀌었다 — Assets 스택이 이 값을 쓴다
    const back = recalled ? ` · 이전 프리셋 ${recalled}개 회수` : '';
    showToast(`${character.name} — 태그 ${chosen.length}개를 슬롯 ${bySlot.size}개에 넣었습니다.${back}`);
    if (replaced.length) {
      showToast(`한 자리에 하나만 들어가는 축이라 ${replaced.join(', ')} 을(를) 바꿨습니다.`);
    }
  }

  /** 이 캐릭터에 프리셋이 넣어 둔 태그를 슬롯에서 뺀다. 지워진 것은 조용히 넘어간다. */
  function presetRecall(character) {
    const prev = (character.preset && character.preset.tags) || null;
    if (!prev) return 0;
    let removed = 0;
    for (const [slotKey, tags] of Object.entries(prev)) {
      const drop = new Set((tags || []).map(t => String(t).toLowerCase()));
      if (!drop.size) continue;
      const before = (character.fields[slotKey] || []).length;
      character.fields[slotKey] = (character.fields[slotKey] || [])
        .filter(t => !drop.has(String(t).toLowerCase()));
      removed += before - character.fields[slotKey].length;
    }
    character.preset = null;
    return removed;
  }

  /** 캐릭터 헤더의 프리셋 이름 옆 [x] — 넣은 것만 되돌린다. */
  function clearCharPreset(cid) {
    const character = state.chars.find(c => c.id === cid);
    if (!character || !character.preset) return;
    const name = character.preset.name;
    const removed = presetRecall(character);
    if (character.name === name) character.name = '';
    renderBlocks();
    emitChange();
    showToast(`${name} 프리셋을 되돌렸습니다 (태그 ${removed}개).`);
  }

  // ---- 팝업 셸 ----

  function presetPanelHtml() {
    const placeholder = presetMode === 'tag'
      ? '태그로 찾기 — blue hair (쉼표로 여러 개면 모두 가진 캐릭터)'
      : '캐릭터 이름 · 작품 이름 — miku, genshin';
    return `<div class="ia-panel-head">
        <span class="ia-panel-title">캐릭터 프리셋</span>
        <span class="ia-panel-sub">${escHtml(presetCharLabel())}</span>
        <button type="button" class="ia-panel-close" data-cp-close="1">&times;</button>
      </div>
      <div class="ia-axtabs ia-cp-tabs">
        <button type="button" class="ia-axtab${presetMode === 'name' ? ' is-open' : ''}" data-cp-mode="name">
          <span class="ia-axtab-name">이름 · 작품</span></button>
        <button type="button" class="ia-axtab${presetMode === 'tag' ? ' is-open' : ''}" data-cp-mode="tag">
          <span class="ia-axtab-name">태그</span></button>
      </div>
      <div class="ia-search ia-search-top">
        <input type="text" id="iaCpInput" placeholder="${escHtml(placeholder)}" autocomplete="off"
          value="${escHtml(presetQuery)}">
        <span class="ia-search-scope">${presetMode === 'tag' ? 'tag' : 'name'}</span>
      </div>
      <div class="ia-panel-body" id="iaCpBody">${presetSearchBodyHtml()}</div>`;
  }

  /** 본문만 교체 — 검색창을 다시 만들지 않아 포커스/캐럿/IME 조합이 살아남는다. */
  function renderPresetBody() {
    if (!presetPanel) return;
    const host = presetPanel.querySelector('#iaCpBody');
    if (!host) { renderPresetPanel(); return; }
    host.innerHTML = presetSearchBodyHtml();
    presetBindSentinel();
  }

  function renderPresetPanel() {
    if (!presetPanel) return;
    presetPanel.innerHTML = presetPanelHtml();
    const input = presetPanel.querySelector('#iaCpInput');
    if (input) {
      input.addEventListener('input', () => { presetQuery = input.value; presetQueueSearch(); });
      input.addEventListener('keydown', event => {
        if (event.key === 'Escape') { event.preventDefault(); closePresetPanel(); }
      });
      input.focus();
      try { input.setSelectionRange(input.value.length, input.value.length); } catch (_) {}
    }
    // 목록이 스크롤되면 앵커 카드가 원래 줄에서 떨어진다 — 그때는 닫는다(툴팁과 같다).
    presetPanel.querySelector('.ia-panel-body')
      ?.addEventListener('scroll', () => { if (cardEl && !cardEl.hidden) closePresetCard(); }, {passive: true});
    presetBindSentinel();
    positionPresetPanel();
  }

  function ensurePresetPanel() {
    if (presetPanel && document.body.contains(presetPanel)) return presetPanel;
    presetPanel = document.createElement('div');
    // `.ia-panel` 을 그대로 입어 슬롯 팝업과 같은 틀·같은 위치를 쓴다.
    presetPanel.className = 'ia-panel ia-cp-panel';
    document.body.appendChild(presetPanel);
    presetPanel.addEventListener('click', onPresetClick);
    return presetPanel;
  }

  function onPresetClick(event) {
    const hit = sel => event.target.closest(sel);
    if (hit('[data-cp-close]')) { closePresetPanel(); return; }
    const mode = hit('[data-cp-mode]');
    if (mode) {
      const next = mode.dataset.cpMode;
      if (next === presetMode) return;
      closePresetCard();
      presetMode = next;
      presetGroup = '';
      presetResults = []; presetGroups = []; presetTotal = 0; presetError = '';
      renderPresetPanel();
      void presetSearch();
      return;
    }
    const group = hit('[data-cp-group]');
    if (group) {
      closePresetCard();
      presetGroup = group.getAttribute('data-cp-group') || '';
      void presetSearch();
      return;
    }
    const row = hit('.ia-cp-row');
    if (row) {
      void openPresetCard(row, row.getAttribute('data-cp-g') || '',
                          row.getAttribute('data-cp-c') || '',
                          row.getAttribute('data-cp-t') || '');
    }
  }

  /** 슬롯 팝업과 같은 가로 앵커. 세로는 CSS(top/bottom)에 맡긴다. */
  function positionPresetPanel() {
    if (!presetPanel || !presetPanel.classList.contains('open')) return;
    const vw = window.innerWidth;
    if (vw <= 767) {
      presetPanel.style.top = presetPanel.style.left = presetPanel.style.width = presetPanel.style.bottom = '';
      return;
    }
    const W = Math.min(PANEL_W, vw - 32);
    const host = blocksMount.getBoundingClientRect();
    let left = Math.max(host.right + 12, PANEL_LEFT);
    if (left + W > vw - 12) left = Math.max(12, vw - 12 - W);
    presetPanel.style.width = W + 'px';
    presetPanel.style.left = left + 'px';
    presetPanel.style.top = (sceneFloatFits() && !blocksMount.hidden)
      ? (PANEL_TOP + SCENE_FLOAT_H + 6) + 'px' : '';
    presetPanel.style.bottom = '';
  }

  function openPresetPanel(cid) {
    if (presetCid === cid && presetPanel && presetPanel.classList.contains('open')) {
      closePresetPanel();
      return;
    }
    // 슬롯 편집 팝업과 겹치지 않게 한다 — 둘 다 같은 자리에 뜬다.
    if (panelContext) closePanel();
    const panel = ensurePresetPanel();
    presetCid = cid;
    presetError = '';
    closePresetCard();
    panel.classList.add('open');
    renderPresetPanel();
    document.addEventListener('mousedown', onPresetOutside, true);
    document.addEventListener('keydown', onPresetKeydown, true);
    // 처음 열면 썸네일 있는 캐릭터가 먼저 온다(thumb_first) — 빈 화면을 주지 않는다.
    if (!presetResults.length) void presetSearch();
  }

  function closePresetPanel() {
    presetSeq++;                 // 진행 중인 요청 무효화
    clearTimeout(presetTimer);
    closePresetCard();
    if (presetObserver) { presetObserver.disconnect(); presetObserver = null; }
    presetCid = null;
    if (presetPanel) { presetPanel.classList.remove('open'); presetPanel.innerHTML = ''; }
    document.removeEventListener('mousedown', onPresetOutside, true);
    document.removeEventListener('keydown', onPresetKeydown, true);
  }

  function onPresetOutside(event) {
    if (presetPanel && presetPanel.contains(event.target)) return;
    if (cardEl && !cardEl.hidden && cardEl.contains(event.target)) return;
    if (event.target.closest?.('[data-charpreset]')) return;   // 토글은 버튼 핸들러가 처리
    // 좌측 슬롯 목록 안쪽(빈틈·여백 포함)은 '바깥'이 아니다 — 슬롯 팝업과 같은 규칙이다.
    // 슬롯을 눌러 편집을 시작하면 `enterEditing` 이 이 팝업을 닫으므로 둘이 겹치지 않는다.
    if (blocksMount.contains(event.target)) return;
    closePresetPanel();
  }

  function onPresetKeydown(event) {
    if (event.key !== 'Escape') return;
    event.preventDefault();
    if (cardEl && !cardEl.hidden) { closePresetCard(); return; }   // 카드부터 닫는다
    closePresetPanel();
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
    // 첫 태그가 들어오거나 마지막 태그가 빠지면 좌표 UI 대상이 달라진다.
    // **직접 타이핑 중에는 미룬다** — 그 순간 블록을 다시 그리면 IME 조합이 끊긴다.
    // 그 경우는 팝업을 닫을 때(closePanel -> renderBlocks) 따라잡는다.
    if (!opts.fromInput) syncPosMembership();
    updateEditingMeta();
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

  /** 블록 하나의 칩 줄을 다시 만든다. **renderBlocks 와 같은 옵션을 써야 한다** —
   *  예전에는 여기서 옵션 없이 그려서, 이 경로를 탄 슬롯만 [×] 와 이름 강조를 잃었다.
   *  구도 슬롯의 파생 칩도 여기서 다시 앞에 붙인다(빼면 콤보 표시가 사라진다). */
  function applyChipView(el, tags) {
    const chips = el.querySelector('.ia-block-chips');
    const count = el.querySelector('.ia-block-count');
    const derived = el.dataset.slot === 'composition' ? compChips(state.composition) : [];
    const character = el.dataset.cid ? state.chars.find(x => x.id === el.dataset.cid) : null;
    const opts = {
      del: true,
      delFrom: derived.length,
      emphasis: (character && el.dataset.sub === CHAR_TAG_SLOT) ? nameEmphasis(character) : null,
    };
    const shown = derived.length ? [...derived, ...tags] : tags;
    if (chips) {
      chips.innerHTML = chipRow(shown, opts);
      bindChipDeletes(chips);   // 새로 만든 [×] 에는 리스너가 없다
    }
    if (count) count.textContent = shown.length || '';
    el.classList.toggle('is-empty', !shown.length);
  }

  /** 칩의 [×] 배선. 슬롯 클릭(팝업 열기)보다 먼저 잡아야 하므로 stopPropagation 이 필수다. */
  function bindChipDeletes(root) {
    root.querySelectorAll('[data-chip-del]').forEach(el => {
      el.addEventListener('click', event => {
        event.stopPropagation();
        event.preventDefault();
        removeChipTag(el.closest('[data-sub],[data-slot]'), el.dataset.chipDel);
      });
    });
  }

  function openSlot(slotId) {
    const slot = SCENE_SLOTS.find(s => s.id === slotId);
    if (!slot) return;
    panelContext = {
      kind: 'scene', slotId, title: slot.name, axis: slot.axis,
      // 축 섹션을 넘기지 않아 '다인원 자세' 팝업이 통째로 비어 있었다 — 캐릭터
      // 경로(openCharSub)에만 있던 줄이다. 씬 슬롯도 sections 를 가질 수 있다.
      sections: slot.sections || null,
      excludeTags: slot.excludeTags || null,
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
      // 이 슬롯에서 감출 태그. 캐릭터 '구도' 가 이미지 전체 태그를 뺄 때 쓴다.
      excludeTags: meta.excludeTags || null,
      // 옆 팝업 없이 인라인 입력창만 여는 슬롯(캐릭터). CHAR_TAG_SLOT 주석 참조.
      noPanel: !!meta.noPanel,
    };
    enterEditing();
  }

  /** 검색창을 붙일까. 계층 탐색과 **따로** 판단한다 — 둘은 성격이 다른 도구다.
   *  검색은 썸네일 그리드를 거르므로 `thumb` 섹션만 있어도 붙는다(다인원 자세 등:
   *  축이 13개면 탭만으로는 원하는 태그를 못 찾는다). */
  function wantsSearch() {
    const secs = panelContext?.sections;
    if (!Array.isArray(secs) || !secs.length) return true;
    return secs.some(sec => sec.kind === 'browse' || sec.kind === 'thumb' || sec.kind === 'gloss');
  }


  /** 슬롯을 텍스트 입력으로 펼치고, 그 옆에 검색+탐색 팝업을 띄운다. */
  function enterEditing() {
    // 프리셋 팝업과 슬롯 팝업은 화면의 같은 자리를 쓴다 — 슬롯 편집을 시작하면 닫는다.
    // (덕분에 `onPresetOutside` 가 좌측 목록을 '바깥'에서 빼도 둘이 겹치지 않는다.)
    closePresetPanel();
    // 옆 팝업이 없는 슬롯(캐릭터) — 인라인 입력창만 연다. 축 그리드도 분류 트리도
    // 그릴 것이 없어서 팝업을 띄우면 빈 상자만 남는다.
    if (panelContext && panelContext.noPanel) {
      // 다른 슬롯에서 열려 있던 팝업·조언 플로트는 닫는다. `closePanel()` 은 못 쓴다 —
      // 그것은 방금 세운 panelContext 까지 비운다.
      if (autocomplete) autocomplete.unbind();
      panelMount.classList.remove('open');
      panelMount.innerHTML = '';
      panelMount.style.top = panelMount.style.left = panelMount.style.width = '';
      if (asideMount) { asideMount.classList.remove('open'); asideMount.innerHTML = ''; }
      openId = 'character';
      renderBlocks();            // 편집 슬롯만 textarea 로
      document.body.classList.add('interactive-editing');
      shiftResultForPopup(true);
      focusEditingInput();       // 자동완성은 bindSlotInput 의 bindTagAssist 가 붙인다
      return;
    }
    thumbScroll.clear();       // 슬롯을 바꾸면 썸네일 스크롤을 처음으로
    thumbFilter = '';          // 검색어도 슬롯 단위다 — 남기면 다음 슬롯이 걸러진 채 열린다
    // 아코디언 기본값 = 그 슬롯의 첫 썸네일 섹션(선택된 게 있으면 그 섹션을 우선 펼친다).
    openThumbAxis = firstThumbAxis();
    // 팩 인덱스는 한 번만 받고, 도착하면 축 영역만 다시 그린다(이미지 셀로 승격).
    void loadThumbIndex().then(() => { if (panelContext) refreshAxisSections(); });
    openId = panelContext.kind === 'scene' ? panelContext.slotId : 'character';
    renderBlocks();            // 편집 슬롯만 textarea 로, 나머지는 칩으로
    renderPanel();             // 검색창 + 분류 탐색
    bindPanelContextClose();
    panelMount.classList.add('open');
    // 편집 중 표시 — tagAssist 의 태그 정보 툴팁을 억제한다(팝업 위에 겹쳐 가림).
    document.body.classList.add('interactive-editing');
    shiftResultForPopup(true);
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
    positionPresetPanel();   // 프리셋 팝업은 panelContext 와 무관하게 떠 있다
    // noPanel 슬롯(캐릭터)은 옆 팝업이 없다 — positionAside 가 여기서 돌면 자리가
    // 안 나온다고 판단해 Electron 창 폭까지 넓히려 든다.
    if (!panelContext || panelContext.noPanel) return;
    positionPopup();
    positionAside();
  });

  /** 편집 중 슬롯 입력창의 포커스를 지킨다.
   *  팝업/플로트는 슬롯 textarea 의 blur 로 닫히는데, 카드 배경·라벨처럼 포커스를
   *  못 받는 곳을 누르면 activeElement 가 body 로 떨어져 '바깥 클릭' 으로 잡힌다.
   *  왼쪽 팝업은 이 핸들러 덕에 멀쩡했고 오른쪽 플로트에만 없어서, 조언 카드의
   *  빈 자리를 누르면 팝업이 통째로 닫혔다(사용자 지적). 입력창 클릭은 예외. */
  function keepEditingFocus(event) {
    if (event.target.closest('input, textarea')) return;
    event.preventDefault();
  }

  let asideMount = null;
  let lastPicked = '';    // 추천의 기준이 되는 마지막 선택 태그
  // 살펴보는 중인 태그(아직 안 고른 것). 셀 본문을 누르면 여기 들어오고,
  // 조언 플로트가 선택분 대신 이 태그를 기준으로 그려진다.
  let inspectTag = '';

  /** 살펴보기 표시만 옮긴다. 그리드를 다시 그리면 345칸 축에서 34ms 가 드는데,
   *  바뀌는 것은 테두리 하나뿐이라 그만한 값이 없다(사용자 성능 기준). */
  // 확대 미니 팝업. 썸네일을 2/3 로 줄이면서 작아서 안 보이는 칸이 생겼다 —
  // 누르면 크게 보여 준다(사용자 지시 2026-08-07). **이미지를 가리는 것은 감수한다.**
  let zoomEl = null;

  function ensureZoom() {
    if (zoomEl && document.body.contains(zoomEl)) return zoomEl;
    zoomEl = document.createElement('div');
    zoomEl.className = 'ia-zoom';
    zoomEl.hidden = true;
    document.body.appendChild(zoomEl);
    // 닫기만 받는다. **넣고 빼는 것은 칸의 [선택]/[제거] 가 한다** — 여기에도
    // 버튼을 두면 같은 일을 하는 버튼이 화면에 둘이 된다(사용자 지적 2026-08-07).
    zoomEl.addEventListener('click', event => {
      if (event.target.closest('[data-zoom-close]')) closeZoom();
    });
    return zoomEl;
  }

  function closeZoom() {
    if (zoomEl) { zoomEl.hidden = true; zoomEl.innerHTML = ''; }
  }

  /** 누른 칸을 크게 보여 준다. 팝업 오른쪽에 세워 그리드를 가리지 않는다 —
   *  고른 것과 원본을 나란히 보게 하려는 것이다. */
  function openZoom(cell, tag) {
    const el = ensureZoom();
    const img = cell.querySelector('.ia-cell-img img, .ia-aside-thumb-img img');
    const src = img ? img.getAttribute('src') : '';
    const tip = tagTip(tag) || '';
    el.innerHTML = `
      <div class="ia-zoom-head">
        <span class="ia-zoom-tag">${escHtml(tag)}</span>
        <button type="button" class="ia-zoom-x" data-zoom-close aria-label="닫기">×</button>
      </div>
      ${src ? `<img class="ia-zoom-img" src="${escHtml(src)}" alt="">`
            : '<div class="ia-zoom-none">그림이 아직 없습니다</div>'}
      ${tip && tip !== tag ? `<div class="ia-zoom-desc">${escHtml(tip)}</div>` : ''}`;
    el.hidden = false;
    // 높이를 알아야 화면 밖으로 안 나가게 가둘 수 있다 — 내용이 붙은 뒤에 잰다.
    positionZoom();
  }

  /** 가로는 팝업 바로 오른쪽, 세로는 사전 띠 바로 아래에 고정한다.
   *
   *  한때 누른 칸의 눈높이에 맞췄다. 사전이 세로 열이던 시절에는 그 오른쪽이
   *  비어 있어 괜찮았는데, 사전을 상단 띠로 눕히면서 그 자리가 이미지가 됐다 —
   *  눈높이를 맞추면 이미지 한가운데를 덮는다. 이미지는 우하단 정렬이라 띠 아래
   *  왼쪽 귀퉁이가 가장 덜 아깝다. */
  function positionZoom() {
    if (!zoomEl || zoomEl.hidden) return;
    const box = panelMount.getBoundingClientRect();
    const w = zoomEl.offsetWidth || 260;
    const h = zoomEl.offsetHeight || 300;
    // 팝업 바로 오른쪽. 사전은 그 위에 가로로 눕는 띠라 세로로 피하면 된다.
    // 자리가 없으면 왼쪽으로 뒤집는다(그래도 없으면 화면 안으로 민다).
    let left = box.right + 10;
    if (left + w > window.innerWidth - 8) left = Math.max(8, box.left - w - 10);
    zoomEl.style.left = Math.round(left) + 'px';
    // 세로는 **사전 띠 바로 아래에 붙인다.** 누른 칸의 눈높이에 맞추면 이미지
    // 한가운데를 덮는다(실측) — 띠 아래 왼쪽 귀퉁이는 이미지가 우하단 정렬이라
    // 가장 덜 아까운 자리다. 화면 밖으로는 안 나가게 가둔다.
    const aside = asideMount && asideMount.classList.contains('open')
      ? asideMount.getBoundingClientRect() : null;
    const floor = aside ? aside.bottom + 10 : Math.max(8, box.top);
    const top = Math.min(floor, window.innerHeight - h - 8);
    zoomEl.style.top = Math.round(Math.max(8, top)) + 'px';
  }

  function markInspect() {
    document.querySelectorAll('.ia-cell.is-inspect, .ia-aside-thumb.is-inspect')
      .forEach(e => e.classList.remove('is-inspect'));
    if (!inspectTag) return;
    document.querySelectorAll('[data-val], [data-advice-add]').forEach(e => {
      const t = e.getAttribute('data-val') || e.getAttribute('data-advice-add');
      if (t === inspectTag) e.classList.add('is-inspect');
    });
  }
  let asideSeq = 0;
  const adviceCache = new Map();

  function ensureAside() {
    if (asideMount && document.body.contains(asideMount)) return asideMount;
    asideMount = document.createElement('div');
    asideMount.className = 'ia-aside';
    document.body.appendChild(asideMount);
    asideMount.addEventListener('mousedown', keepEditingFocus);   // 왼쪽 팝업과 동일
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
      // '필요한 것' 버튼은 한 번에 넣는다. 그리드처럼 살펴보기를 거칠 이유가 없다 —
      // 답이 하나로 정해져 있고, 오클릭이 잦은 150칸 그리드도 아니다(색 조합과 같다).
      const nd = ev.target.closest('[data-need-add]');
      if (nd) {
        // `fromAside` — 플로트에서 넣은 것은 추천 기준(seed)을 옮기지 않는다.
        // 기준이 따라 움직이면 목록이 갈려서 방금 넣은 것을 되돌릴 수 없다.
        toggleTag(nd.getAttribute('data-need-add'), { fromAside: true });
        refreshAxisSections();     // 그리드의 '선택됨' 표시도 맞춘다
        return;
      }
      const b = ev.target.closest('[data-advice-add]');
      if (!b) return;
      const tag = b.getAttribute('data-advice-add');
      if (!ev.target.closest('.ia-cell-act')) {
        // 예전에는 여기서 **아무것도 하지 않았다.** 본문 클릭이 곧 이 플로트의
        // 기준을 바꾸는 것이라 사전이 방금 누른 칩 기준으로 다시 그려졌기
        // 때문이다 — 자기 자신을 갈아치우는 재귀였다.
        // 이제 살펴보기가 사전을 갱신하지 않으므로 그 재귀가 없다. 그리드와 같이
        // 포커스를 주고 확대해서 보여 준다(사용자 지시 2026-08-07).
        const same = inspectTag === tag;
        inspectTag = same ? '' : tag;
        markInspect();
        if (same) closeZoom();
        else openZoom(b, tag);
        // **여기서는 renderAside 를 부르지 않는다.** 이 플로트의 기준을 자기 칩으로
        // 바꾸는 것이라 자기 자신을 갈아치우는 재귀가 된다.
        return;
      }
      inspectTag = '';
      toggleTag(tag, { fromAside: true });
      // 그리드가 안 따라와서 플로트에서 넣은 태그는 그리드에서 선택 안 된 것처럼
      // 보였다(setCurrentTags 는 fromInput 일 때만 갱신한다).
      refreshAxisSections();
    });
    return asideMount;
  }

  // 태그 사전(자동완성 툴팁이 쓰는 그 데이터). 조언이 없는 태그에도 보여줄 것이 있다.
  const lookupCache = new Map();
  async function fetchLookup(tag) {
    if (!tag) return null;
    if (lookupCache.has(tag)) return lookupCache.get(tag);
    let v = null;
    try {
      const r = await fetch('/api/tag/lookup?tag=' + encodeURIComponent(tag));
      v = await r.json();
      if (v && v.error) v = null;
    } catch { v = null; }
    lookupCache.set(tag, v);
    return v;
  }

  /** 태그 사전 카드 — 함께 딸려오는 것 / 더 구체적인 것 / 함께 쓰이는 것.
   *  조언(전제조건·충돌·추천)이 없는 태그가 대부분이라 '알려드릴 것이 없습니다' 만
   *  띄우던 자리를 이것이 대신한다.
   *
   *  칩은 `recThumbsHtml` 로 그린다 — 팩에 그림이 있으면 이미지가 붙는다. 전에는 이
   *  카드만 텍스트 버튼을 써서, 그리드에는 그림이 있는 태그인데도 오른쪽에서는 이름만
   *  보였다(사용자 지적 2026-07-30). 그리드와 같은 렌더러를 쓰면 블러·선택 규칙도 함께 따라온다. */
  function lookupCardHtml(info) {
    if (!info) return '';
    // 설명·분류·빈도는 뺐다 — 설명은 셀 툴팁에 이미 나오고, 분류·빈도는 여기서
    // 결정에 쓰이지 않는다. 관계 두 줄만 남긴다(사용자 지시).
    const rows = [];
    if (info.implications && info.implications.length) {
      rows.push('<div class="ia-aside-group-label">함께 딸려오는 것</div>' +
        `<div class="ia-aside-thumbs">${recThumbsHtml(info.implications.slice(0, 8))}</div>`);
    }
    // '비슷한 것'(related = siblings + word_match)은 **내지 않는다**. 고르는 데
    // 도움이 안 된다는 판단이다(사용자 2026-08-07). 백엔드는 그대로 계산해서
    // 보내므로(`info.related`) 되살리려면 이 줄만 되돌리면 된다 — 랭커의 튜닝
    // (존재↔부재 쌍 차단 등)을 다시 만들 필요가 없다.
    // '더 구체적인 것'(children)은 '비슷한 것'과 성격이 다르다 — `sweater` 에 대한
    // `ribbed sweater` 는 유사어가 아니라 하위 종류다. 전에는 한 통에 섞였고 점수가
    // 높아 유사어를 밀어냈다(children 보유 태그의 99.94%에서 첫 칩이 children).
    // 이제 백엔드가 목록을 나눠 보내므로 줄도 나눈다.
    if (info.specific && info.specific.length) {
      rows.push('<div class="ia-aside-group-label">더 구체적인 것</div>' +
        `<div class="ia-aside-thumbs">${recThumbsHtml(info.specific.slice(0, 8))}</div>`);
    }
    // '함께 쓰이는 것'은 앞 세 줄과 출처가 다르다 — 사전의 관계가 아니라 실제 게시물
    // 449만 건의 동반 통계다. 그래서 사전에 관계가 없는 태그(freq>=1000 의 65.4%)에도
    // 붙는다. 근거가 약하면 백엔드가 아무것도 안 보낸다 — 억지로 채우지 않는 것이 설계다.
    // 4개인 것은 실측 결과다(8칸으로 늘리면 정밀도 .746 -> .574).
    if (info.companions && info.companions.length) {
      rows.push('<div class="ia-aside-group-label">함께 쓰이는 것</div>' +
        `<div class="ia-aside-thumbs">${recThumbsHtml(info.companions.slice(0, 8))}</div>`);
    }
    if (!rows.length) return '';
    // `.scroll` 이 있어야 한다 — `.ia-aside-card` 는 overflow:hidden 이라
    // 이것이 없으면 칩이 넘칠 때 스크롤 없이 잘린다(사용자 지적).
    return '<div class="ia-aside-card scroll"><div class="ia-aside-title">태그 사전' +
      `<span class="ia-aside-count">${escHtml(info.tag || '')}</span></div>` +
      rows.join('') + '</div>';
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
  /** 그리드에 그림이 있으면 그 URL. 없으면 ''. */
  function thumbSrcOf(tag) {
    const axis = Object.keys(THUMB_TAGS).find(a => THUMB_TAGS[a].includes(tag)) || '';
    if (!axis) return '';
    return (thumbHave.get(packAxisOf(axis)) || new Set()).has(tag) ? thumbUrl(axis, tag) : '';
  }

  /** 색·무늬 조합(`black pants`)을 [기준태그, 색] 으로 쪼갠다. 쪼개지지 않으면 null.
   *  `CLOTH_COMBO_REV` 만 보면 안 된다 — 사전 칩에는 조합표에 없는 `black hat`·`white dress`
   *  같은 것이 더 많이 나온다(실측 226종 1,064회 vs 조합표 83종 2,001회). 그래서 규칙으로
   *  쪼갠다: **앞 낱말이 색 이름이고 나머지가 그리드에 있는 태그일 때만.** 색 이름 목록에
   *  없는 낱말(`holding`·`implied` 등)은 조합이 아니다. */
  // 색을 입힐 수 있는 **표면 명사**. 이것들은 기준 태그 자체에 그림이 없어도
  // 색 조합으로 본다 — `striped clothes`·`black background` 처럼 색만 다른 변종이
  // 사전 칩에 줄줄이 나왔다. 기준 태그 조건을 통째로 풀면 `orange (fruit)`·
  // `orange slice` 까지 숨는다(`orange` 가 색 이름이라서). 그래서 목록으로 한정한다.
  const COLOR_SURFACE = new Set([
    'clothes', 'clothing', 'background', 'skin', 'hair', 'eyes', 'pupils', 'sclera',
    'nails', 'sleeves', 'footwear', 'headwear', 'legwear', 'handwear', 'neckwear',
    'trim', 'outline', 'gemstone', 'horns', 'wings', 'tail', 'fur', 'feathers',
  ]);

  function colorComboOf(tag) {
    const parts = String(tag).toLowerCase().split(' ');
    for (const k of [1, 2]) {
      if (parts.length <= k) break;
      const word = parts.slice(0, k).join(' ');
      if (!COLOR_SWATCH[word]) continue;
      const base = parts.slice(k).join(' ');
      const src = thumbSrcOf(base);
      if (src) return {base, src, color: COLOR_SWATCH[word], word};
      // 그림이 없어도 표면 명사면 조합이다(그림 없이 숨기기만 한다).
      if (COLOR_SURFACE.has(base)) return {base, src: '', color: COLOR_SWATCH[word], word};
    }
    return null;
  }

  /** 색·무늬·크기 태그인가 — 사전 칩에서 **뺄** 것. 팝업 상단에 팔레트와 슬라이더로
   *  이미 나오는 축이라, 여기 또 내면 같은 것을 두 군데서 고르게 된다.
   *  (한때 색 스와치·색 점으로 그려 봤지만 기준 의상 그림과 색이 따로 놀았다.) */
  function isColorOrSizeTag(tag) {
    for (const list of Object.values(PALETTES || {})) {
      if ((list || []).some(d => d.tag === tag)) return true;
    }
    for (const s of Object.values(SLIDERS || {})) {
      if ((s.steps || []).some(x => (x.tag || x) === tag)) return true;
    }
    return !!colorComboOf(tag);
  }

  function recThumbsHtml(list) {
    return list.filter(o => {
      const t = typeof o === 'string' ? o : o.tag;
      if (isColorOrSizeTag(t)) return false;
      // **그림이 없는 것은 아예 내지 않는다**(사용자 지시 2026-08-07: "숨김처리
      // 하거나 제거해주세요"). 사전 칩에 나오는 태그의 상당수는 애초에 그리드
      // 태그가 아니라 그림이 없다(실측: 빈칸 2,261종 전부가 축 밖 — 생성 누락이
      // 아니라 표시 문제였다). 예전에는 글자만 있는 칩으로 그렸는데, 옆에 그림
      // 칩이 나란히 서면 빈칸처럼 보였다.
      // 되살리려면 이 한 줄을 빼고 아래 `plain` 분기를 되돌리면 된다.
      return !!thumbSrcOf(t);
    }).map(o => {
      const t = typeof o === 'string' ? o : o.tag;
      const match = typeof o === 'object' && o.match;
      const src = thumbSrcOf(t);
      const img = `<img src="${escHtml(src)}" alt="" loading="lazy" decoding="async">`;
      const on = typeof o === 'object' && o.on;
      // 그리드와 같은 규칙 — 라벨은 항상 태그 이름이고, 행동은 호버 버튼이 맡는다.
      // 그리드 셀과 같은 블러 규칙을 적용한다. 전에는 `is-sensitive` 가 여기 안 붙어서
      // Safe Viewer 가 On 이어도 **추천 칩 쪽은 그대로 노출됐다**(Safe Viewer 를 붙이며
      // 발견, 2026-07-30). 가리는 곳이 한 군데라도 새면 가리는 의미가 없다.
      const cls = 'ia-aside-thumb'
        + (match ? ' match' : '') + (on ? ' on' : '')
        + (isSensitive(t) ? ' is-sensitive' : '')
        + (inspectTag === t ? ' is-inspect' : '');
      const tip = on ? `${t} — 이미 넣었습니다` :
        (match ? `${t} — 지금 고른 것들과도 어울립니다` : t);
      const act = `<span class="ia-cell-act" data-act="${on ? 'off' : 'on'}">${on ? '제거' : '선택'}</span>`;
      return `<div class="${cls}" data-advice-add="${escHtml(t)}"` +
        ` title="${escHtml(tip)}">` +
        `<span class="ia-aside-thumb-img">${img}${act}</span>` +
        `<span>${escHtml(t)}</span></div>`;
    }).join('');
  }

  /** 선택된 태그들의 조언을 모아 오른쪽에 그린다. */
  // ---- 의상 색 조합 ----
  // `_cloth_combo.json` 이 확정한 조합만 쓴다. 28색을 다 열면 `green shirt` 처럼 실측으로
  // 확인되지 않은 태그를 권하게 된다 — 목록에 없는 색은 슬롯 입력창에 직접 쓰면 된다.
  // 평범한 색은 칩으로 안 준다 — 사용자가 직접 친다(자동완성이 `black bow` 를 찾는다).
  // 색 칩 10개가 플로트 절반을 먹어 '함께 쓰는 것' 이 밀렸다(사용자 지적).
  // 여기 없는 수식어(줄무늬·체크 등)만 남는다 = '특별한 것'.
  const PLAIN_COLOR = new Set([
    'black', 'white', 'red', 'blue', 'green', 'yellow', 'pink', 'purple', 'orange',
    'brown', 'grey', 'gray', 'silver', 'gold', 'beige', 'aqua', 'navy', 'tan',
    'multicolored', 'two-tone', 'rainbow',
  ]);

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
    // 평범한 색은 뺀다. 지금 고른 것이 색이면 그것만은 남겨 뗄 수 있게 한다 —
    // 안 그러면 `black bow` 를 넣은 뒤 되돌릴 길이 텍스트 편집뿐이다.
    const keys = Object.keys(mods).filter(m => !PLAIN_COLOR.has(m) || m === st.mod);
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
    // 옆 팝업이 없는 슬롯(캐릭터)에서는 조언 플로트도 띄우지 않는다 — 좌표를 팝업에
    // 맞춰 잡는데 그 팝업이 닫혀 있어 자리가 어긋난다.
    if (!panelContext || panelContext.noPanel) { host.classList.remove('open'); host.innerHTML = ''; return; }
    const tags = currentTags();
    const seq = ++asideSeq;
    // 살펴보는 태그는 **아직 고르지 않은 것**이라 currentTags 에 없다. 조언을 받으려면
    // 조회 목록에는 넣되, '이미 고른 것' 판정에는 넣지 않는다.
    const inspecting = inspectTag &&
      !tags.some(x => x.toLowerCase() === inspectTag.toLowerCase()) ? inspectTag : '';
    const askTags = inspecting ? [inspecting, ...tags] : tags;
    if (!askTags.length) {
      host.classList.add('open');
      host.innerHTML = '<div class="ia-aside-card"><div class="ia-aside-title">도움말</div>' +
        '<div class="ia-aside-empty">그림을 누르면 그 태그의 설명과 어울리는 조합을 여기에 보여줍니다. ' +
        '넣는 것은 그림 위의 <b>선택</b> 버튼입니다.</div></div>';
      positionAside();
      return;
    }
    const items = await fetchAdvice(askTags);
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
    // **필요한 태그 기준으로 합친다.** 출처별로 나누면 `blazer` + `hooded jacket` 을
    // 고른 순간 `+ jacket` 이 두 줄로 겹쳐 나온다 — 넣을 것은 하나인데 두 번 권한다.
    const needMap = new Map();
    const chosenLower = new Set(tags.map(x => x.toLowerCase()));
    for (const it of items) {
      for (const r of (it.requires || [])) {
        // 판정은 **태그** 로 한다. 축으로만 보면 `blazer`(상의)를 골랐을 때
        // `military jacket` 이 요구하는 `jacket` 이 충족된 것으로 처리됐다 —
        // implication 은 문자 그대로라 다른 상의가 대신하지 못한다.
        // 태그를 모르는 경우(백엔드가 축만 준 경우)에만 예전 축 판정으로 돌아간다.
        if (r.tag ? chosenLower.has(String(r.tag).toLowerCase())
                  : chosenAxes.has(r.axis)) continue;
        // `r.tag` 가 실제로 넣어야 할 태그다(예: military jacket -> jacket).
        // 예전엔 `r.label`(축 이름 '상의')만 썼는데 그건 우리 분류지 사용자가 넣을
        // 수 있는 것이 아니다 — 무엇을 골라야 하는지 알 수 없었다.
        const key = (r.tag || '#' + r.axis).toLowerCase();
        const cur = needMap.get(key);
        if (cur) {
          if (!cur.sources.includes(it.tag)) cur.sources.push(it.tag);
          cur.strong = cur.strong || !!r.strong;   // 하나라도 필수면 필수다
          continue;
        }
        needMap.set(key, { axis: r.axis, label: r.label, tag: r.tag || '',
                           strong: !!r.strong, sources: [it.tag] });
      }
    }
    const needs = [...needMap.values()];
    // 충돌 — 전용 엔드포인트로 묻는다.
    // 태그별 conflict 목록은 화면용으로 12개까지만 잘라 보내므로, 그걸로 교집합을
    // 구하면 잘린 뒤쪽 쌍을 놓친다(실측: china dress + skirt set 이 안 잡혔다).
    const lower = new Set(tags.map(x => x.toLowerCase()));
    let clashes = [];
    try {
      const cr = await fetch('/api/interactive-advice/conflicts?tags=' +
        encodeURIComponent(askTags.slice(0, 40).join(',')));
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
      lastPicked = tags[tags.length - 1] || '';
    }
    // 살펴보는 중이면 그것이 기준이다 — 사용자가 방금 "이건 뭔가요" 하고 누른 것이다.
    const seedTag = inspecting || lastPicked;
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
    // '살펴보는 중' 상자는 뒀다가 뺐다 — 무엇을 보고 있는지는 셀의 파란 테두리와
    // 아래 '함께 쓰는 것 <태그> 기준' 머리말이 이미 말한다. 같은 말을 세 번 하게 된다.
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
      // 강한 것(없으면 제대로 안 나온다)을 위로. 각 줄은 **누를 수 있는 태그**다.
      const row = n => {
        const t = n.tag || n.label;          // tag 가 없으면 축 이름으로라도 알린다
        const can = !!n.tag;
        const btn = can
          ? `<button type="button" class="ia-aside-need-btn" data-need-add="${escHtml(t)}"` +
            ` title="${escHtml(tagTip(t))}">+ ${escHtml(t)}</button>`
          : `<span class="ia-aside-need-btn is-off">${escHtml(t)}</span>`;
        return `<div class="ia-aside-need${n.strong ? '' : ' soft'}">${btn}` +
          '<div class="ia-aside-need-why">' +
          n.sources.map(x => `<code>${escHtml(x)}</code>`).join(', ') +
          `${n.strong ? ' 에 필요합니다' : ' 에 있으면 더 좋습니다'}</div></div>`;
      };
      parts.push('<div class="ia-aside-card"><div class="ia-aside-title">필요한 것' +
        `<span class="ia-aside-count">${needs.length}</span></div>` +
        needs.filter(n => n.strong).map(row).join('') +
        needs.filter(n => !n.strong).map(row).join('') +
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
    // 조언(전제조건·충돌·추천)은 태그 대부분에 없다. 그 자리에 '알려드릴 것이
    // 없습니다' 를 띄우면 상자만 남는다 — 대신 태그 사전(implies/related)을 보여준다.
    const info = await fetchLookup(seedTag);
    if (seq !== asideSeq || !panelContext) return;
    const dict = lookupCardHtml(info);
    if (dict) parts.push(dict);
    // 그래도 아무것도 없으면 아예 닫는다. 빈 상자는 자리만 먹는다(사용자 지적).
    if (!parts.length) { host.classList.remove('open'); host.innerHTML = ''; return; }
    host.classList.add('open');
    host.innerHTML = parts.join('');
    positionAside();
  }

  /** 팝업 오른쪽에 붙인다. 자리가 안 나오면 숨긴다 — 그리드가 우선이다. */
  // ── Safe Viewer ────────────────────────────────────────────────────────
  // 민감 태그 썸네일의 기본 블러를 켜고 끈다. **모든 팝업이 이 하나를 공유한다** —
  // 슬롯마다 따로 두면 성인 축이 여러 슬롯에 걸쳐 있어(신체·의상·자세·씬) 한쪽만
  // 꺼진 상태가 생긴다. 블러 해제는 body 클래스 하나로 전역 적용한다.
  //
  // 기본은 On(가린다). 끈 상태를 기기에 기억한다 — 매번 다시 끄게 하면 그리드를
  // 훑는 작업에서 방해만 된다. 계정이 아니라 기기 단위인 이유는 localStorage 라서다.
  const SAFE_VIEWER_KEY = 'ia.safeViewer';
  let safeViewer = true;
  try { safeViewer = localStorage.getItem(SAFE_VIEWER_KEY) !== '0'; } catch { safeViewer = true; }

  function applySafeViewer() {
    document.body.classList.toggle('ia-safe-off', !safeViewer);
  }

  function setSafeViewer(on) {
    safeViewer = !!on;
    try { localStorage.setItem(SAFE_VIEWER_KEY, safeViewer ? '1' : '0'); } catch {}
    applySafeViewer();
    // 열려 있는 팝업들의 버튼 표시를 맞춘다(씬 팝업까지 한 번에).
    document.querySelectorAll('[data-safe-viewer]').forEach(b => {
      b.setAttribute('aria-pressed', String(safeViewer));
      b.classList.toggle('off', !safeViewer);
      const t = b.querySelector('.ia-safe-state');
      if (t) t.textContent = safeViewer ? 'On' : 'Off';
    });
  }

  function safeViewerBtnHtml() {
    return `<button type="button" class="ia-safe-btn${safeViewer ? '' : ' off'}"
      data-safe-viewer="1" aria-pressed="${safeViewer}"
      title="민감 썸네일의 흐림을 켜고 끕니다. 모든 창에 함께 적용됩니다.">
      Safe Viewer : <b class="ia-safe-state">${safeViewer ? 'On' : 'Off'}</b></button>`;
  }

  /** 태그 사전을 팝업 오른쪽 **남은 폭 전체를 쓰는 상단 띠**로 편다(사용자 타협안
   *  2026-08-07). 세로 열(258px)로 세우면 그만큼 그림 폭을 영구히 먹는데, 위에
   *  가로로 눕히면 그림은 아래로만 밀린다 — 세로는 그림이 남아돌던 쪽이다.
   *  칩은 4열로 깔린다(.ia-aside-thumbs). */
  function positionAside() {
    if (!asideMount) return;
    const box = panelMount.getBoundingClientRect();
    const GAP = 10;
    const left = box.right + GAP;
    const width = window.innerWidth - left - 12;
    if (width < 220) {          // 정말 좁으면 접는다 — 그리드가 우선이다
      asideMount.classList.remove('open');
      syncPopupShift();
      return;
    }
    asideMount.style.left = Math.round(left) + 'px';
    asideMount.style.width = Math.round(width) + 'px';
    asideMount.style.top = Math.round(Math.max(8, box.top)) + 'px';
    asideMount.style.bottom = 'auto';
    // 띠는 화면의 1/3 을 넘지 않는다. 내용이 짧으면 그만큼만 차지한다.
    asideMount.style.maxHeight = Math.round(
      Math.min(window.innerHeight * 0.34, window.innerHeight - box.top - 12)) + 'px';
    if (panelContext && asideMount.innerHTML) asideMount.classList.add('open');
    // 사전이 열리고 닫힐 때마다 이미지가 비켜설 자리가 달라진다.
    syncPopupShift();
  }

  // 팝업 **안**에서 우클릭해도 닫는다. 슬롯 줄에만 걸어 뒀더니 팝업이 그 줄을
  // 덮고 있어 우클릭이 팝업에 먼저 닿아 아무 일도 안 일어났다(사용자 지적).
  // 검색창·입력창에서는 브라우저 메뉴(붙여넣기 등)를 살려 둔다.
  let panelContextMenuBound = false;
  function bindPanelContextClose() {
    if (panelContextMenuBound || !panelMount) return;
    panelContextMenuBound = true;
    panelMount.addEventListener('contextmenu', event => {
      if (event.target.closest('input, textarea, [contenteditable="true"]')) return;
      event.preventDefault();
      closePanel();
    });
  }

  function closePanel() {
    document.body.classList.remove('interactive-editing');
    shiftResultForPopup(false);
    closeZoom();
    if (autocomplete) autocomplete.unbind();
    openId = null;
    panelContext = null;
    inspectTag = '';
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
      // 반응형 생성: 타이핑 중에는 발화를 멈춘다(blur/Enter 에 한 번 낸다).
      reactiveTypingSlot = ta;
      // 직접 타이핑 → 상태만 갱신, textarea 는 그대로(커서/IME 유지)
      setCurrentTags(parseSlotInput(ta.value), {fromInput: true});
    });
    // 다 썼다는 신호 = 포커스를 잃거나 Enter. 여기서 한 번만 낸다.
    const flushTyping = () => {
      if (reactiveTypingSlot !== ta) return;
      reactiveTypingSlot = null;
      reactiveOnChange();
    };
    ta.addEventListener('blur', flushTyping);
    ta.addEventListener('keydown', event => {
      // 자동완성 드롭다운이 열려 있으면 Enter/Escape 는 tagAssist(확정/닫기)에 양보한다.
      const acOpen = getAutocompleteTarget && getAutocompleteTarget() === ta;
      if (event.key === 'Escape') {
        if (acOpen) return;
        event.preventDefault(); closePanel(); return;
      }
      if (event.key === 'Enter' && !event.shiftKey) {
        if (acOpen) return;
        event.preventDefault();
        flushTyping();          // 닫기 전에 한 번 낸다 — 닫으면 blur 가 늦다
        closePanel();
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
        // 확대 미니 팝업도 body 직계라 **같은 함정에 빠졌다** — [선택]을 누르면
        // 태그는 들어가는데 그 순간 팝업이 통째로 닫혀 계속 고를 수가 없었다(실측).
        if (a && (panelMount.contains(a) || asideMount?.contains(a)
                  || zoomEl?.contains(a)
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
  // 팝업이 열려 있는 동안 히스토리 레일이 접혀 있었나. 열려 있던 것만 되돌린다 —
  // 사용자가 스스로 접어 둔 것을 팝업이 닫혔다고 펴 주면 조작을 빼앗는 것이 된다.
  let railFoldedByPopup = false;

  /** 팝업이 열리고 닫힐 때 결과 영역을 비켜 준다.
   *
   *  팝업은 화면 왼쪽(494px)부터 380px 를 차지하는데 이미지는 그 뒤에 가운데
   *  정렬로 깔린다 — 결국 아무것도 안 보였다(테스터 지적 2026-08-07).
   *  1) 히스토리 레일을 접어 오른쪽 자리를 벌고
   *  2) 이미지 영역 왼쪽에 팝업 폭만큼 여백을 줘 오른쪽으로 민다.
   *
   *  **저장은 하지 않는다**(persist=false). 팝업 때문에 잠깐 접은 것을 사용자
   *  설정으로 굳히면, 다음에 켤 때 히스토리가 사라진 채로 시작한다. */
  function shiftResultForPopup(on) {
    const rail = document.getElementById('viewerPanel');
    if (on) {
      if (!railFoldedByPopup && rail && !rail.classList.contains('collapsed')) {
        railFoldedByPopup = true;
        window.setHistoryRailCollapsed?.(true, false);
      }
    } else if (railFoldedByPopup) {
      railFoldedByPopup = false;
      window.setHistoryRailCollapsed?.(false, false);
    }
    document.body.classList.toggle('ia-popup-shift', !!on);
    syncPopupShift();
  }

  /** 이미지에 줄 왼쪽 여백을 팝업 실측으로 넣는다. 팝업 폭·위치는 화면 크기에
   *  따라 달라지므로 상수로 박지 않는다. */
  function syncPopupShift() {
    const viewer = document.getElementById('resultViewer');
    if (!viewer) return;
    if (!document.body.classList.contains('ia-popup-shift')) {
      viewer.style.removeProperty('--ia-shift');
      return;
    }
    const box = panelMount.getBoundingClientRect();
    const v = viewer.getBoundingClientRect();
    if (!box.width || !v.width) {
      viewer.style.removeProperty('--ia-shift');
      viewer.style.removeProperty('--ia-shift-top');
      return;
    }
    // 가로는 **팝업까지만** 비운다. 사전은 이제 그 오른쪽에 가로로 눕는 띠라
    // 가로를 더 먹지 않는다 — 대신 세로로 비켜 준다.
    // 이미지가 너무 좁아지면(뷰어의 3/4 초과) 포기한다: 밀어 봐야 볼 수 없을
    // 만큼 작아지면 가려지는 편이 차라리 낫다.
    const shift = Math.round(box.right + 12 - v.left);
    viewer.style.setProperty('--ia-shift',
      (shift > 0 && shift < v.width * 0.75) ? shift + 'px' : '0px');
    // 세로는 사전 띠 아래까지. 띠가 닫혀 있으면 0.
    const aside = asideMount && asideMount.classList.contains('open')
      ? asideMount.getBoundingClientRect() : null;
    const top = aside ? Math.round(aside.bottom + 10 - v.top) : 0;
    viewer.style.setProperty('--ia-shift-top',
      (top > 0 && top < v.height * 0.6) ? top + 'px' : '0px');
  }

  function positionPopup() {
    const el = editingEl();
    if (!el) return;
    const vw = window.innerWidth;
    if (vw <= 767) {
      // 모바일: 하단 시트(CSS 미디어쿼리)에 맡긴다. 인라인 앵커 좌표를 비운다.
      panelMount.style.top = panelMount.style.left = panelMount.style.width = panelMount.style.bottom = '';
      return;
    }
    const W = Math.min(PANEL_W, vw - 32);
    const host = blocksMount.getBoundingClientRect();
    let left = Math.max(host.right + 12, PANEL_LEFT);
    if (left + W > vw - 12) left = Math.max(12, vw - 12 - W);
    panelMount.style.width = W + 'px';
    panelMount.style.left = left + 'px';
    // 씬 버튼 줄이 떠 있으면 그 아래에서 시작한다 — 안 그러면 서로 가린다.
    panelMount.style.top = (sceneFloatFits() && !blocksMount.hidden)
      ? (PANEL_TOP + SCENE_FLOAT_H + 6) + 'px' : '';
    panelMount.style.bottom = '';
    syncPopupShift();   // 팝업이 움직였으면 이미지가 비켜 준 폭도 다시 잰다
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
    if (!panelContext) { panelMount.innerHTML = ''; return; }

    // 슬롯 자체가 텍스트 입력창이 되었으므로 팝업에는 '선택됨'을 두지 않는다.
    // 팝업 = 검색창(상단 통합) + 분류 탐색. 검색은 태그를 '찾아서 넣는' 보조 도구다.
    panelMount.innerHTML = `
      <div class="ia-panel-head">
        <span class="ia-panel-title">${escHtml(panelContext.title)}</span>
        <span class="ia-panel-sub">${escHtml(panelContext.axis)}</span>
        ${safeViewerBtnHtml()}
        <button type="button" class="ia-panel-close" data-close="1">&times;</button>
      </div>
      ${wantsSearch() ? `<div class="ia-search ia-search-top">
        <input type="text" id="iaTagInput"
          placeholder="태그 검색 — 아는 태그를 바로 넣습니다" autocomplete="off">
        <span class="ia-search-scope">${escHtml(panelContext.axis)}</span>
      </div>` : ''}
      <div class="ia-panel-body">
        ${panelContext.slotId === 'composition' ? compPanelHtml() : ''}
        ${axisSectionsHtml()}
      </div>`;

    panelMount.querySelector('[data-close]')?.addEventListener('click', closePanel);
    panelMount.querySelector('[data-safe-viewer]')
      ?.addEventListener('click', () => setSafeViewer(!safeViewer));
    if (panelContext.slotId === 'composition') bindCompPanel();
    bindAxisSections();
    // 계층 브라우저를 이 슬롯 축으로 마운트한다. 없으면 섹션은 비어 있다.
    const input = panelMount.querySelector('#iaTagInput');
    if (input) {
      // 팝업 검색창은 자동완성이 아니라 목록을 걸러내는 필터다. 계층 탐색기가 있으면
      // 그 트리를, 없으면(자세) 썸네일 그리드를 거른다.
      // (태그 입력용 자동완성은 슬롯 입력창 쪽에 붙어 있다.)
      const applyFilter = () => {
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
  let thumbIndexInFlight = null;

  async function loadThumbIndex() {
    if (thumbHave.size) return;
    // 프리로드와 팝업 열기가 겹칠 수 있다 — 같은 요청을 두 번 보내지 않는다.
    if (thumbIndexInFlight) return thumbIndexInFlight;
    thumbIndexInFlight = (async () => {
    try {
      const res = await fetch('/api/interactive-thumb/index', {cache: 'no-store'});
      if (!res.ok) return;
      const data = await res.json();
      for (const [axis, tags] of Object.entries(data?.axes || {})) {
        thumbHave.set(axis, new Set((tags || []).map(t => String(t))));
      }
    } catch (_) { /* 팩이 없으면 전부 텍스트 셀 */ }
    })();
    try { await thumbIndexInFlight; } finally { thumbIndexInFlight = null; }
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

  // ---- 캐릭터 에셋 프롬프트를 슬롯으로 나눠 담기 ---------------------------
  // 에셋은 NAI 캐릭터 프롬프트를 통째로 들고 있다(`girl, blue eyes, elf, bikini …`).
  // 그대로 한 칸에 부으면 Interactive 가 못 다루므로 축 정의로 갈라 넣는다.

  /** 특징 = 사람 자체. 의상 = 걸친 것. 사용자가 고른 범위를 이걸로 가른다. */
  const ASSET_FEATURE_SLOTS = ['머리', '눈·얼굴', '표정', '신체', '종족·수인'];
  const ASSET_OUTFIT_SLOTS = ['의상', '소품·장식'];
  // 성별은 슬롯 태그가 아니라 캐릭터의 성별 토글이 만든다(`renderPrompt` 가 붙인다).
  // 여기 두면 `girl, 1girl, girl` 처럼 겹친다 — 토글로 흡수하고 태그는 버린다.
  const ASSET_GENDER = new Map([
    ['girl', 'female'], ['1girl', 'female'], ['female', 'female'], ['woman', 'female'],
    ['boy', 'male'], ['1boy', 'male'], ['male', 'male'], ['man', 'male'],
  ]);

  /** 태그(소문자) -> {slot, excl}. **축 정의에서 만든다** — 별도 사전을 두면 갈라진다.
   *  `excl` 은 그 태그가 배타 축(팔레트·슬라이더) 소속일 때 같은 축의 태그 전부다 —
   *  넣을 때 나머지를 걷어내지 않으면 `long hair, short hair` 처럼 모순이 남는다. */
  let _assetSlotOf = null;
  function assetSlotOf() {
    if (_assetSlotOf) return _assetSlotOf;
    const m = new Map();
    for (const sub of CHAR_SUBS) {
      for (const sec of (sub.sections || [])) {
        let tags = [];
        let excl = null;
        if (sec.kind === 'palette') {
          tags = (PALETTES[sec.ref] || []).map(d => d.tag);
          excl = tags.map(t => String(t).toLowerCase());
        } else if (sec.kind === 'slider') {
          tags = (SLIDERS[sec.ref] || {}).steps || [];
          excl = tags.map(t => String(t).toLowerCase());
        } else {
          tags = THUMB_TAGS[sec.ref] || [];         // thumb / thumb_extra
        }
        for (const t of tags) {
          const k = String(t || '').trim().toLowerCase();
          if (k && !m.has(k)) m.set(k, {slot: sub.key, excl});
        }
      }
    }
    return (_assetSlotOf = m);
  }

  /** 프롬프트 문자열 -> 태그. NAI 가중치(`1.2::tag ::`)와 괄호를 벗긴다. */
  function assetTags(text) {
    return String(text || '')
      .split(',')
      .map(s => s.replace(/^\s*-?\d*\.?\d*\s*::/, '').replace(/::\s*$/, '')
                 .replace(/[{}\[\]]/g, '').trim())
      .filter(Boolean);
  }

  /**
   * 캐릭터 에셋의 프롬프트를 활성 캐릭터 슬롯에 나눠 넣는다.
   *
   * @param kind  'char' = 특징만 · 'all' = 특징 + 의상
   * 축에서 못 찾은 태그는 **버리지 않고** 캐릭터 슬롯에 묶음으로 보낸다(사용자 지시) —
   * 에셋 프롬프트에는 작품 고유 태그가 섞여 있어 버리면 캐릭터가 달라진다.
   */
  function applyAssetPrompt(promptText, kind = 'all') {
    // 펼쳐 둔 캐릭터가 대상이다. 없으면 첫 칸 — 슬롯이 하나뿐인 경우가 대부분이다.
    const c = state.chars.find(x => x.open) || state.chars[0];
    if (!c) { showToast('캐릭터 슬롯이 없습니다.', 'error'); return false; }
    const want = new Set(kind === 'char'
      ? ASSET_FEATURE_SLOTS
      : [...ASSET_FEATURE_SLOTS, ...ASSET_OUTFIT_SLOTS]);
    // 이건 '더하기'가 아니라 '이 슬롯의 캐릭터를 갈아치우기'다 — 앞 캐릭터의
    // 이름(`akemi homura`)이 새 캐릭터(`kisaki (blue archive)`) 와 나란히 남으면 안 된다.
    // **다만 지우는 것은 넣을 것이 확정된 뒤다.** 먼저 비웠더니, 빈 프롬프트나
    // 성별 태그뿐인 프롬프트가 오면 앞 캐릭터만 사라졌다(Codex 지적 2026-08-05).
    // 아래 파싱은 `c` 를 건드리지 않는다.
    const map = assetSlotOf();
    const add = new Map();          // slot key -> [태그]
    const bundle = [];              // 축에 없는 것
    let outOfScope = 0, gender = '';
    const seen = new Set();
    for (const tag of assetTags(promptText)) {
      const k = tag.toLowerCase();
      if (seen.has(k)) continue;
      seen.add(k);
      const g = ASSET_GENDER.get(k);
      if (g) { gender = g; continue; }            // 성별 토글이 흡수한다
      const hit = map.get(k);
      if (!hit) { bundle.push(tag); continue; }
      if (!want.has(hit.slot)) { outOfScope++; continue; }
      if (!add.has(hit.slot)) add.set(hit.slot, []);
      add.get(hit.slot).push({tag, excl: hit.excl});
    }
    // 넣을 것이 하나도 없으면 **아무것도 건드리지 않는다.** 성별만 있으면 그것만 바꾼다.
    if (!add.size && !bundle.length) {
      if (gender && c.gender !== gender) {
        c.gender = gender;
        renderBlocks(); emitChange(); notifyRoster();
        showToast('성별만 반영했습니다 (넣을 태그가 없습니다).', 'info');
        return true;
      }
      showToast('넣을 태그가 없습니다. 이전 캐릭터를 그대로 둡니다.', 'error');
      return false;
    }

    // 여기서부터 커밋. 채울 슬롯(want)과 **이름 슬롯**을 비우고, 이름의 출처인
    // 프리셋 꼬리표와 ALT(그 캐릭터의 변형 태그)도 함께 걷는다.
    // 범위 밖 슬롯은 건드리지 않는다 — '캐릭터 특징만' 을 고른 사용자가 직접 정한
    // 의상까지 지우면 고른 의미가 없어진다.
    const wipedTags = [];
    for (const key of [...want, CHAR_TAG_SLOT]) {
      const had = c.fields[key] || [];
      if (had.length) wipedTags.push(...had);
      c.fields[key] = [];
    }
    const wipedName = c.preset ? c.preset.name : (c.name || '');
    c.preset = null;
    c.name = '';
    c.alt = [];
    if (gender) c.gender = gender;
    let n = 0;
    for (const [slot, items] of add) {
      let cur = (c.fields[slot] || []).slice();
      for (const {tag, excl} of items) {
        // 배타 축(머리 길이·가슴 크기·머리색 등)은 **갈아끼운다.** 그냥 더하면
        // 기본값이 남아 `long hair, short hair` 처럼 모순된 프롬프트가 된다.
        if (excl) {
          const drop = new Set(excl);
          cur = cur.filter(t => !drop.has(t.toLowerCase()));
        }
        if (cur.some(t => t.toLowerCase() === tag.toLowerCase())) continue;
        cur.push(tag); n++;
      }
      c.fields[slot] = cur;
    }
    if (bundle.length) {
      const cur = (c.fields[CHAR_TAG_SLOT] || []).slice();
      const low = new Set(cur.map(t => t.toLowerCase()));
      for (const t of bundle) {
        if (low.has(t.toLowerCase())) continue;
        cur.push(t); low.add(t.toLowerCase());
      }
      c.fields[CHAR_TAG_SLOT] = cur;
    }
    renderBlocks();
    emitChange();
    notifyRoster();
    const parts = [`${n + bundle.length}개 넣음`];
    if (bundle.length) parts.push(`축 밖 ${bundle.length}개는 캐릭터 슬롯으로`);
    if (outOfScope) parts.push(`범위 밖 ${outOfScope}개 제외`);
    // 무엇이 걷혔는지 알려 준다 — 조용히 지우면 사용자가 넣어 둔 것이 사라진 줄 모른다.
    if (wipedTags.length) {
      parts.push(wipedName
        ? `이전 캐릭터 ${wipedName} · 태그 ${wipedTags.length}개 회수`
        : `이전 태그 ${wipedTags.length}개 회수`);
    }
    showToast(parts.join(' · '), 'success');
    return true;
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
  /** 축 전체에 거는 색·무늬 줄. `black headwear` 는 모자가 아니라 색이라
   *  그리드에 옷과 나란히 두면 `beret` 과 같은 종류로 보인다(사용자 지적).
   *  지우지 않는 이유 — Danbooru 에 `black hat` 이 없어 이것이 "검은 모자"를 말하는
   *  유일한 방법이고, CLOTH_COMBO 에도 모자·신발 베이스가 없다. */
  function axisColorRowHtml(axis) {
    const sel = currentLower();
    // 조언 플로트의 색 칩과 같은 규칙 — 평범한 색은 직접 친다. 고른 것만 예외로
    // 남겨 뗄 수 있게 한다. 한 화면에 색 UI 두 벌이 규칙이 다르면 안 된다.
    const list = ((AXIS_COLOR_TAGS || {})[axis] || []).filter(t => {
      const mod = t.split(' ').slice(0, -1).join(' ');
      return !PLAIN_COLOR.has(mod) || sel.has(t.toLowerCase());
    });
    if (!list.length) return '';
    const have = thumbHave.get(packAxisOf(axis)) || new Set();
    const cells = list.map(t => {
      const mod = t.split(' ').slice(0, -1).join(' ');
      const on = sel.has(t.toLowerCase());
      const sw = COMBO_SWATCH[mod];
      const dot = sw
        ? `<span class="ia-combo-dot" style="background:${sw}"></span>`
        : `<span class="ia-combo-dot is-${escHtml(mod)}"></span>`;
      // 이미 만들어 둔 썸네일이 그대로 살아 있다(팩 키가 축 그대로다).
      const tip = have.has(t) ? `${t} — 이 부위 전체에 겁니다` : t;
      return `<button type="button" class="ia-combo${on ? ' on' : ''}"
        data-axcolor="${escHtml(axis)}" data-axcolor-tag="${escHtml(t)}"
        title="${escHtml(tip)}">${dot}${escHtml(COMBO_LABEL[mod] || mod)}</button>`;
    }).join('');
    return `<div class="ia-axcolor"><span class="ia-axcolor-label">색·무늬</span>` +
      `<div class="ia-combo-row">${cells}</div></div>`;
  }

  /** 축 안에서 배타 — `black headwear` 와 `striped headwear` 는 동시에 못 쓴다. */
  function applyAxisColor(axis, tag) {
    const owned = new Set(((AXIS_COLOR_TAGS || {})[axis] || []).map(x => x.toLowerCase()));
    const cur = currentTags();
    const had = cur.some(x => x.toLowerCase() === tag.toLowerCase());
    const kept = cur.filter(x => !owned.has(x.toLowerCase()));
    setCurrentTags(had ? kept : kept.concat([tag]));
  }

  // 배열 -> 소문자 Set 캐시. 매 렌더마다 52개를 다시 소문자화하지 않는다.
  const EXCLUDE_CACHE = new WeakMap();

  /** 지금 열려 있는 슬롯이 빼라고 한 태그(소문자). 없으면 빈 Set. */
  function slotExcluded() {
    const list = panelContext?.excludeTags;
    if (!list || !list.length) return EMPTY_EXCLUDE;
    let cached = EXCLUDE_CACHE.get(list);
    if (!cached) {
      cached = new Set(list.map(x => String(x).toLowerCase()));
      EXCLUDE_CACHE.set(list, cached);
    }
    return cached;
  }
  const EMPTY_EXCLUDE = new Set();

  function thumbHtml(sec) {
    const axis = sec.ref;
    // 슬롯이 지정한 제외 목록을 먼저 뺀다. 캐릭터 '구도' 슬롯이 이미지 전체 태그
    // (`isometric`·`female pov`·`multiple views` …)를 감추는 데 쓴다 — 캐릭터 한 명에게
    // 걸 수 없는 것들이다. 씬 슬롯에는 그대로 있으니 못 쓰게 되는 것은 없다.
    const excluded = slotExcluded();
    const full = excluded.size
      ? (THUMB_TAGS[axis] || []).filter(x => !excluded.has(String(x).toLowerCase()))
      : (THUMB_TAGS[axis] || []);
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
      return `<div class="ia-cell${on ? ' on' : ''}${isLocked ? ' is-locked' : ''}${sens ? ' is-sensitive' : ''}${inspectTag === t ? ' is-inspect' : ''}"
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
      <div class="ia-cell-wrap">${mainPal}${extra}${axisColorRowHtml(axis)}
        <div class="ia-cell-grid" data-scroll-ax="${escHtml(axis)}">${cells}</div></div>
    </div>`};
  }

  // 이미지 없이 `태그 : 설명` 만 나열하는 섹션. `nsfw_heavy` 가 쓴다 —
  // 금기와 평상 사이의 태그들이라 썸네일을 만들어 배포하지 않기로 했다(사용자 결정
  // 2026-07-30: "이걸 이미지까지 오픈하는건 아닌거 같다"). 목록으로만 닿게 한다.
  // 선택 동작은 썸네일 셀과 같다 — `data-ax/data-ref/data-val` 을 그대로 쓴다.
  function glossHtml(sec) {
    const axis = sec.ref;
    const full = GLOSS_TAGS[axis] || [];
    const all = thumbFilter ? full.filter(([t, d]) => matchesFilter(t) || (d || '').includes(thumbFilter)) : full;
    const sel = currentLower();
    const chosenCount = all.filter(([t]) => sel.has(t.toLowerCase())).length;
    const open = thumbFilter ? all.length > 0 : openThumbAxis === axis;
    if (thumbFilter && !all.length) return {tab: '', pane: ''};
    const tab = `<button type="button" class="ia-axtab${open ? ' is-open' : ''}"
      data-acc-ax="${escHtml(axis)}" aria-selected="${open}">
      <span class="ia-axtab-name">${escHtml(sec.label)}</span>
      <span class="ia-acc-n">${thumbFilter ? `${all.length}/${full.length}` : all.length}</span>
      ${chosenCount ? `<span class="ia-acc-sel">${chosenCount}</span>` : ''}
    </button>`;
    if (!open) return {tab, pane: ''};
    const rows = all.map(([t, d]) => {
      const on = sel.has(t.toLowerCase());
      return `<div class="ia-gloss-row${on ? ' on' : ''}"
        data-ax="thumb" data-ref="${escHtml(axis)}" data-val="${escHtml(t)}"
        aria-pressed="${on}">
        <span class="ia-gloss-tag">${escHtml(t)}</span>
        <span class="ia-gloss-desc">${escHtml(d || '')}</span>
        <span class="ia-cell-act" data-act="${on ? 'off' : 'on'}">${on ? '제거' : '선택'}</span></div>`;
    }).join('');
    // 안내 문구는 뺐다(사용자 지시 2026-08-01). 목록 모양만 봐도 그림이 없다는 것이
    // 명백한데 매번 한 줄을 읽히는 값이 없다. 필요하면 sec.note 로 다시 붙는다.
    const note = sec.note ? `<p class="ia-gloss-note">${escHtml(sec.note)}</p>` : '';
    return {tab, pane: `<div class="ia-ax-row is-open"><div class="ia-cell-wrap">${note}
      <div class="ia-gloss-list">${rows}</div></div></div>`};
  }

  /** 축 구간으로 스크롤. 검색 중 탭을 누르면 그 결과 묶음으로 이동한다.
   *  스크롤 컨테이너는 `.ia-panel-body` 다 — 그리드가 아니라 본문이 움직여야 한다. */
  function scrollToAxis(axis) {
    const body = panelMount.querySelector('.ia-panel-body');
    // 축 키는 [a-z_] 뿐이라 CSS 이스케이프가 필요 없다(기존 팔레트 점프와 동일).
    const grid = panelMount.querySelector(`[data-scroll-ax="${axis}"]`);
    const row = grid?.closest('.ia-ax-row');
    if (!body || !row) return;
    // 탭 줄이 본문 위에 붙어 있으므로 그만큼 위로 더 올린다 — 안 그러면 첫 행이 가린다.
    const tabs = panelMount.querySelector('.ia-axtabs');
    const pad = (tabs ? tabs.getBoundingClientRect().height : 0) + 10;
    body.scrollTo({
      top: Math.max(0, body.scrollTop + row.getBoundingClientRect().top
                    - body.getBoundingClientRect().top - pad),
      behavior: 'smooth',
    });
    row.classList.add('is-jumped');
    setTimeout(() => row.classList.remove('is-jumped'), 900);
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
    // gloss 는 썸네일과 같은 탭 스트립에 들어간다 — 사용자에게는 같은 축 선택기다.
    const thumbs = secs.map(sec => sec.kind === 'thumb' ? thumbHtml(sec)
      : sec.kind === 'gloss' ? glossHtml(sec) : null).filter(Boolean);
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
    // 검색 중에는 여러 축이 동시에 펼쳐진다. 축마다 그리드가 자기 스크롤을 가지면
    // 화면에 스크롤 영역이 겹겹이 쌓여(사용자 표현: "복층") 아래쪽 이미지를 누르기
    // 어려워진다. 검색 중에는 그리드 상한을 풀고 **본문 하나만** 스크롤하게 한다.
    return `<div class="ia-axes${thumbFilter ? ' is-search' : ''}" id="iaAxes">${body}</div>`;
  }

  function bindAxisSections() {
    const host = panelMount.querySelector('#iaAxes');
    if (!host) return;
    host.querySelectorAll('[data-axcolor]').forEach(el => {
      el.addEventListener('click', event => {
        event.stopPropagation();
        applyAxisColor(el.dataset.axcolor, el.dataset.axcolorTag);
        refreshAxisSections();
      });
    });
    host.querySelectorAll('[data-ax]').forEach(el => {
      el.addEventListener('click', event => {
        event.stopPropagation();
        const {ax, ref, val} = el.dataset;
        if (ax === 'thumb') {
          // 셀 본문 = 살펴보기, [선택]/[제거] 버튼 = 실행. 둘을 가르는 이유는
          // 한 축이 최대 150칸이라 그리드를 훑다 스치는 클릭이 잦기 때문이다 —
          // 스쳐도 프롬프트는 안 변하고 오른쪽 설명만 바뀐다.
          if (!event.target.closest('.ia-cell-act')) {
            // 본문 클릭 = **살펴보기**. 포커스 + 확대 + **사전 갱신**이다.
            // 사전을 안 바꾸는 것은 사전 자기 칩을 눌렀을 때뿐이다(자기를
            // 갈아치우는 재귀). 여기까지 껐더니 그리드에서 눌러도 아래 설명이
            // 안 따라왔다(사용자 지적 2026-08-07).
            const same = inspectTag === val;
            inspectTag = same ? '' : val;
            markInspect();
            if (same) closeZoom();
            else openZoom(el, val);
            void renderAside();
            return;
          }
          inspectTag = '';                 // 넣었으면 그 태그가 기준이 된다
          closeZoom();
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
        // 검색 중에는 이미 전부 펼쳐져 있다 — 누르면 그 구간으로 **점프**한다.
        // 접기로 동작하면 결과가 사라져 "왜 없어졌지" 가 된다.
        if (thumbFilter) {
          scrollToAxis(axis);
          return;
        }
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

  // ---- 넣고 뺀 것을 알리는 토스트 ------------------------------------------
  // 전역 showToast 는 화면 최상단 중앙이라 이 팝업 밖에서 뜬다 — 시선이 그리드에
  // 있을 때 잘 안 보인다(사용자 지적). 그래서 **팝업 안 축 칩 행 위**에 띄운다.
  // 예전에 "토스트가 축 탭을 가린다"고 지적받은 것은 Interactive 를 켤 때마다 뜨던
  // 상주성 경고였다. 이건 1.4초짜리 행동 확인이라 성격이 다르다(사용자 판단).
  let pickToastEl = null;
  let pickToastTimer = null;

  function flashPick(tag, added) {
    const panel = document.querySelector('.ia-panel');
    if (!pickToastEl) {
      pickToastEl = document.createElement('div');
      pickToastEl.className = 'ia-pick-toast';
    }
    // 팝업 안에 두면 팝업이 어디로 움직이든 따라간다. 팝업이 없으면(그리드를 안 연
    // 상태) 화면 기준으로 떨어뜨린다 — `loose` 가 그 폴백이다.
    const host = panel || document.body;
    if (pickToastEl.parentElement !== host) host.appendChild(pickToastEl);
    pickToastEl.classList.toggle('loose', !panel);
    if (panel) {
      // 헤더 줄(Safe Viewer 가 있는 줄)에 얹는다 — 팝업에서 가장 위이면서 눈이
      // 먼저 가는 자리다(사용자 지시). 헤더가 없으면 본문 최상단(축 칩 행)으로
      // 내려간다. 높이를 재서 세로 가운데에 맞춘다.
      const head = panel.querySelector('.ia-panel-head');
      if (head) {
        const h = pickToastEl.offsetHeight || 34;
        pickToastEl.style.top =
          `${head.offsetTop + Math.max(0, Math.round((head.offsetHeight - h) / 2))}px`;
      } else {
        const body = panel.querySelector('.ia-panel-body');
        pickToastEl.style.top = `${(body ? body.offsetTop : 96) + 10}px`;
      }
    } else {
      pickToastEl.style.top = '';
    }
    // 글자는 최소로. 부호 하나와 태그면 무엇이 일어났는지 다 말한다.
    pickToastEl.textContent = `${added ? '+' : '−'} ${tag}`;
    pickToastEl.classList.toggle('off', !added);
    // 연달아 누를 때 애니메이션이 안 먹는 것을 막는 강제 reflow(전역 토스트와 같은 이유).
    pickToastEl.classList.remove('show');
    void pickToastEl.offsetWidth;
    pickToastEl.classList.add('show');
    if (pickToastTimer) clearTimeout(pickToastTimer);
    pickToastTimer = setTimeout(() => {
      pickToastEl.classList.remove('show');
      pickToastTimer = null;
    }, 1400);
  }

  /** 브라우저/추천에서의 클릭 = 토글. 있으면 제거, 없으면 추가.
   *  브라우저의 ✓(dupe) 판정이 대소문자 무시라, 제거 비교도 대소문자 무시로 맞춘다.
   *
   *  토스트는 **여기 한 곳**에 붙인다. 그리드 셀·조언 플로트의 [선택]/[제거]·
   *  '필요한 것' 버튼·탐색기가 전부 이 함수를 지나므로, 호출처마다 붙이다 하나를
   *  빠뜨리는 일이 없다. 프로그램이 부르는 경로가 생기면 `silent` 로 끈다. */
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
    if (!opts.silent) flashPick(normalized, !existing);
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

  // ------------------------------------------------------- Assets 스냅샷 입출력

  /** 백엔드에 남길 조합. UI 전용 상태(open)와 표시용 id 는 뺀다 — 같은 조합인지
   *  판정하는 해시가 프롬프트에 나가는 값만 보기 때문이다(interactive_assets_service). */
  function snapshotChars() {
    return state.chars.map(c => ({
      name: c.name || '',
      state: c.state,
      gender: c.gender || 'female',
      pos: c.pos || POS_DEFAULT,
      // tags 까지 담는다 — 이게 없으면 복원한 캐릭터에서 프리셋을 빼거나 갈아탈 때
      // presetRecall() 이 회수할 대상을 몰라 옛 태그가 그대로 남는다.
      preset: c.preset ? {
        work: c.preset.work,
        name: c.preset.name,
        tags: Object.fromEntries(
          Object.entries(c.preset.tags || {}).map(([k, v]) => [k, [...(v || [])]])),
      } : null,
      alt: [...(c.alt || [])],
      gaze: [...(c.gaze || [])],
      fields: Object.fromEntries(
        Object.entries(c.fields || {}).map(([k, v]) => [k, [...(v || [])]])),
    }));
  }

  /** 스냅샷을 캐릭터 슬롯에 되돌린다. 씬 슬롯은 건드리지 않는다 — 스냅샷은
   *  캐릭터 조합만 담고, 배경/구도는 그대로 두는 것이 사용자 기대다. */
  function applySnapshotChars(rows) {
    if (!Array.isArray(rows) || !rows.length) return false;
    state.chars = rows.slice(0, MAX_NAI_CHARACTERS).map((row, i) => {
      const base = newCharacter(i === 0);   // id 는 새로 발급(옛 id 를 되살리면 충돌한다)
      const fields = row && row.fields ? row.fields : {};
      return {
        ...base,
        name: String(row?.name || ''),
        state: row?.state === 'disabled' ? 'disabled' : 'active',
        gender: row?.gender === 'male' ? 'male' : 'female',
        // 형식을 여기서 못박는다. 예전에는 문자열이면 뭐든 통과해서 옛 저장분의
        // 이상한 값이 그대로 상태에 앉았다 — 캔버스에서는 칩이 격자 밖으로 나간다.
        pos: /^[A-E][1-5]$/.test(String(row?.pos || '')) ? String(row.pos) : POS_DEFAULT,
        preset: row?.preset ? {
          work: row.preset.work,
          name: row.preset.name,
          tags: (row.preset.tags && typeof row.preset.tags === 'object')
            ? Object.fromEntries(Object.entries(row.preset.tags)
                .map(([k, v]) => [k, Array.isArray(v) ? [...v] : []]))
            : {},
        } : null,
        alt: Array.isArray(row?.alt) ? [...row.alt] : [],
        gaze: Array.isArray(row?.gaze) ? [...row.gaze] : [],
        // 슬롯 키는 CHAR_SUBS 가 정한다 — 스냅샷에 없는 키는 기본값으로 채우고,
        // 모르는 키는 버린다(축이 바뀌어도 복원이 깨지지 않게).
        fields: Object.fromEntries(CHAR_SUBS.map(sub => [
          sub.key,
          Array.isArray(fields[sub.key]) ? [...fields[sub.key]] : defaultFieldsFor(sub.key),
        ])),
      };
    });
    renderBlocks();
    emitChange();
    notifyRoster();   // 전체 복원은 캐릭터 수를 통째로 바꾼다 — 스택도 따라가야 한다
    return true;
  }

  // 팝업 우측의 사전/조언은 백엔드가 태그 DB(17만 건)를 **첫 요청 때** 읽어 올린다.
  // 실측 2.7초. 그 대기가 사용자가 팝업을 연 순간에 걸리면 화면이 멈춘 것처럼 보인다.
  // 모드에 들어온 직후의 유휴 시간으로 옮긴다 — 화면에 아무것도 알리지 않는다.
  let asidePreloaded = false;

  function preloadAsideData() {
    if (asidePreloaded) return;
    asidePreloaded = true;
    // 빈 tags 로 부른다. 백엔드는 인덱스를 올리지만 돌려줄 항목이 없어
    // 프론트 조언 캐시가 쓰지도 않을 태그로 채워지지 않는다.
    void fetch('/api/interactive-advice/batch?tags=').catch(() => {});
    // 팩 인덱스(161KB)도 미리. 이게 있어야 그리드가 텍스트 셀 대신 그림으로 뜬다.
    void loadThumbIndex().catch(() => {});
  }

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
      closePositionPicker(); closePresetPanel(); closePanel();
      // 모드를 끄면 씬 버튼 줄도 사라져야 한다 — blocksMount 만 숨기면 플로트가 남는다.
      if (sceneMount) { sceneMount.classList.remove('open'); sceneMount.innerHTML = ''; }
    } else { renderBlocks(); preloadAsideData(); }
    onActiveChange(active);
    if (!silent && active) emitChange();
  }

  // 토글 리스너는 명명 함수로 두어 destroy 시 제거할 수 있게 한다(Codex M7).
  const onToggleClick = () => setActive(!active);
  if (toggleButton) toggleButton.addEventListener('click', onToggleClick);

  // 팝업 내부(검색창 제외)를 mousedown 할 때 기본동작을 막아 슬롯 입력창의 포커스를 지킨다.
  // 분류 탐색은 픽마다 재렌더되는데, 포커스가 눌린 버튼에 있으면 재렌더 시 body 로 떨어지고
  // blur 로 팝업이 닫히던 간헐 버그가 있었다. 조언 플로트·씬 플로트도 같은 것을 쓴다.
  const onPanelMouseDown = keepEditingFocus;
  panelMount.addEventListener('mousedown', onPanelMouseDown);
  // **좌측 슬롯 목록 안쪽도 같은 보호를 받는다.** 슬롯과 슬롯 사이의 빈틈이나 목록 아래
  // 여백처럼 포커스를 못 받는 자리를 누르면 activeElement 가 body 로 떨어지고, 그 blur 가
  // '바깥 클릭'으로 잡혀 작업 중이던 팝업이 통째로 닫혔다(사용자 지적). 팝업·조언·씬
  // 플로트는 처음부터 이 핸들러를 쓰고 있었고 좌측 목록만 빠져 있었다.
  // mousedown 기본동작만 막는 것이라 click 은 그대로 뜬다 — 다른 슬롯을 눌러 전환하는
  // 동작도, 헤더 버튼들도 영향이 없다. 입력창(textarea)은 keepEditingFocus 가 예외로 둔다.
  blocksMount.addEventListener('mousedown', onPanelMouseDown);

  blocksMount.hidden = true;

  // 로드 시 저장된 Safe Viewer 상태를 body 에 반영한다. 팝업을 열기 전이라도
  // 다른 곳(사이드 썸네일 등)의 블러가 일관되게 나온다.
  applySafeViewer();

  return {
    isActive: () => active,
    setActive,
    setContext: ({rating, person} = {}) => {
      if (rating) state.rating = rating;
      if (person) state.person = person;
    },
    getPrompt: renderPrompt,
    /** 선행·후행(프롬프트 엔지니어링)이 바뀌면 app.js 가 부른다. 슬롯은 그대로고
     *  베이스 프롬프트만 다시 조립하면 되므로 블록을 다시 그리지 않는다. */
    refreshPrompt() { if (active) emitChange(); },
    // 생성 요청용 캐릭터(활성 + 태그 보유, NAI 상한 5). app.js 가 overrides.characters/uc/
    // character_positions 로 싣는다.
    getGenerationCharacters: generationCharacters,
    // Assets(조합 스냅샷) 입출력. 생성 시 기록하고, 목록에서 고르면 되돌린다.
    getSnapshotChars: snapshotChars,
    /** 캐릭터에 속하지 않는 값(씬 슬롯 + 구도 콤보). Assets 미리보기 하단이 쓴다.
     *  캐릭터와 따로 두는 이유: 조합 카드는 캐릭터 단위로 슬롯에 꽂히는데,
     *  이건 슬롯이 아니라 그림 전체에 걸리는 설정이다. */
    getSnapshotGlobals: () => ({
      slots: Object.fromEntries(
        Object.entries(state.slots || {}).map(([k, v]) => [k, [...(v || [])]])),
      composition: {...(state.composition || {})},
      composition_tags: compTags(state.composition),
    }),
    applySnapshotChars,
    /** 작업 결과를 통째로 담는다(캐릭터 + 씬 슬롯 + 구도 콤보). Assets 스냅샷은
     *  캐릭터만 담으므로 그것만으로는 씬 태그가 사라진다. */
    exportState() {
      return {
        // v2 = freeText 가 생겼다. **키는 그대로 v1 을 쓴다**(app.js) — 키를 바꾸면
        // 기존 작업 상태가 통째로 안 보인다. 옛 저장분은 freeText 가 없어 ''.
        v: 2,
        freeText: String(state.freeText || ''),
        chars: snapshotChars(),
        slots: Object.fromEntries(
          Object.entries(state.slots || {}).map(([k, v]) => [k, [...(v || [])]])),
        composition: {...(state.composition || {})},
      };
    },
    /** 저장해 둔 작업 결과를 되돌린다. 실패해도 조용히 지나간다 —
     *  형식이 바뀐 옛 저장분 때문에 모드가 안 켜지면 안 된다. */
    importState(saved) {
      if (!saved || typeof saved !== 'object') return false;
      // 반쯤 넣다 실패하면 **되돌린다.** 예전에는 망가진 상태가 그대로 남아 다음
      // 렌더에서 또 터졌다 — '깨진 저장분은 무시한다'는 약속이 지켜지지 않았다
      // (2026-08-05 Codex 지적).
      const rollback = {
        chars: state.chars, composition: state.composition, freeText: state.freeText,
        slots: Object.fromEntries(
          Object.entries(state.slots || {}).map(([k, v]) => [k, [...(v || [])]])),
      };
      try {
        if (Array.isArray(saved.chars) && saved.chars.length) applySnapshotChars(saved.chars);
        if (saved.slots && typeof saved.slots === 'object') {
          // **아는 축 + 저장분에 있는 키**를 모두 훑는다. 아는 축만 훑으면 나중에
          // 축이 늘었을 때 옛 저장분이 조용히 잘리고, 저장분 키만 훑으면 지금
          // 있는 축이 빈 배열로 초기화되지 않아 이전 값이 남는다.
          const next = emptySceneSlots();
          for (const [key, v] of Object.entries(saved.slots)) {
            // 모르는 키도 배열이면 그대로 안고 간다 — 옛 버전으로 잠깐 돌아갔다
            // 오는 것만으로 태그가 증발하면 안 된다.
            if (Array.isArray(v)) next[key] = v.map(String);
          }
          state.slots = next;
        }
        if (saved.composition && typeof saved.composition === 'object') {
          state.composition = {...newComposition(), ...saved.composition};
        }
        // v1 저장분에는 없다 — 그때는 빈 문자열로 시작한다.
        state.freeText = typeof saved.freeText === 'string' ? saved.freeText : '';
        if (active) { renderBlocks(); emitChange(); }
        return true;
      } catch (_) {
        state.chars = rollback.chars;
        state.slots = rollback.slots;
        state.composition = rollback.composition;
        state.freeText = rollback.freeText;
        if (active) { try { renderBlocks(); } catch (__) {} }
        return false;
      }
    },
    // 빠른 스왑: 캐릭터 스택(열기 전환) + 슬롯 하나에만 꽂기
    getCharacterRoster: characterRoster,
    /** CR 모듈 상태가 바뀌면 app.js 가 부른다 — 헤더의 [Reference] 배지만 갱신한다.
     *  블록 전체를 다시 그리면 편집 중이던 슬롯의 포커스·캐럿이 날아간다. */
    refreshCharReference() {
      if (!active) return;
      blocksMount.querySelectorAll('[data-charref]').forEach(btn => {
        const n = charRefCount();
        btn.classList.toggle('is-on', n > 0);
        const badge = btn.querySelector('.ia-char-ref-n');
        if (n && badge) badge.textContent = String(n);
        else if (n && !badge) btn.insertAdjacentHTML('beforeend', `<span class="ia-char-ref-n">${n}</span>`);
        else if (!n && badge) badge.remove();
      });
    },
    applySnapshotCharById,
    // Assets 패널의 복원 선택 UI 가 쓴다. 묶음·항목 정의는 여기가 원본이다 —
    // 슬롯이 늘면 자동으로 따라가야 하므로 저쪽에 베껴 두지 않는다.
    getRestoreGroups: () => RESTORE_GROUPS.map(g => ({key: g.key, label: g.label})),
    getRestoreItems: restoreItems,
    applyCharacterPresetTo,
    applyAssetPrompt,
    /** 생성이 끝났다 — 모아 둔 변화가 있으면 그때 한 번 낸다. */
    notifyGenerationDone: reactiveOnGenerationDone,
    isReactive: () => reactive,
    // Assets 바의 [+] 가 쓴다. 좌측 [+캐릭터 슬롯] 과 같은 동작이라 상한/토스트를 공유한다.
    addCharacterSlot: addCharacter,
    // Assets 스택 옆 컨트롤이 쓴다. 좌측 헤더의 ACTIVE/[x] 와 **같은 함수**라
    // 마지막 하나는 못 지우는 규칙과 토스트가 그대로 적용된다.
    toggleCharacterEnabled: toggleCharEnabled,
    deleteCharacterById: deleteCharacter,
    /** 위치 팝업을 주어진 앵커에 연다(Assets 스택의 [POS] 버튼용).
     *  NAI 가 아니거나 1명이면 좌표 자체를 안 보내므로 열지 않는다. */
    openPositionPickerFor(anchor, cid) {
      if (!anchor || !cid) return false;
      if (String(getMode() || 'NAI').toUpperCase() !== 'NAI') return false;
      if (state.chars.length <= 1) return false;
      openPositionPicker(anchor, cid);
      return true;
    },
    /** 위치를 쓸 수 있는 상태인가(스택이 POS 버튼을 낼지 판단). */
    positionAvailable: () =>
      String(getMode() || 'NAI').toUpperCase() === 'NAI' && positionedChars().length > 1,
    openCharacterAt,
    applySnapshotCharAt,
    // 모드 전환 시 호출 — Position 버튼/Reference 는 NAI 전용이라 헤더를 다시 그려야 한다.
    onModeChanged: () => {
      if (!active) return;
      closePositionPicker();
      renderBlocks();
      // Assets 스택의 [POS] 는 NAI 일 때만 낸다 — 모드가 바뀌면 그쪽도 다시 그려야
      // 한다. 안 그러면 WEBUI 로 옮겨도 버튼이 남아 눌러도 반응이 없다.
      notifyRoster();
    },
    destroy: () => {
      // 하위 모듈의 리스너/타이머/팝업/툴팁까지 정리한다.
      if (autocomplete) { try { autocomplete.unbind(); } catch (e) {} }
      if (toggleButton) toggleButton.removeEventListener('click', onToggleClick);
      panelMount.removeEventListener('mousedown', onPanelMouseDown);
      blocksMount.removeEventListener('mousedown', onPanelMouseDown);
      closePositionPicker();
      closePresetPanel();
      document.body.classList.remove('interactive-editing');
      shiftResultForPopup(false);
      if (posPopup) { posPopup.remove(); posPopup = null; }
      if (presetPanel) { presetPanel.remove(); presetPanel = null; }
      if (cardEl) { cardEl.remove(); cardEl = null; }
      blocksMount.innerHTML = '';
      panelMount.classList.remove('open');
      panelMount.style.top = panelMount.style.left = panelMount.style.width = '';
      panelMount.innerHTML = '';
    },
  };
}
