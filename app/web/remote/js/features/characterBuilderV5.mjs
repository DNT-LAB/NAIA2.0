// Assets 신 사양(V5) - 캐릭터 제작.
//
// 자작 캐릭터를 일곱 블록(머리 · 눈얼굴 · 신체 · 종족수인 · 의상 · 소품장식 · 소지품)의 부품으로 짓는다.
//
// 화면은 셋이다(사용자 정정 2026-10-11 - 처음에는 제작 화면이 바로 떴다):
//   gallery   = **기본.** 캐릭터 선택. 구 사양 화면과 같은 꼴(목록 | 상세)이고 메인 프롬프트는 그대로 보인다.
//   create    = [+ 캐릭터 생성] 으로 들어가는 제작 화면. 아래의 덮개가 올라온다.
//   variation = 고른 그림을 원본 A 로 놓고 일부(시작 : 종료 사이의 가로 띠)만 다시 그리는 화면. 덮개가 올라온다.
//
// 제작 · 바리에이션 화면의 배치:
// 화면은 둘로 갈린다(사용자 승인 2026-10-11):
//   왼쪽  = 메인 프롬프트 자리를 덮는 블록 줄. 고른 부품이 **썸네일 칩**(Interactive 의 `.ia-cell` 그대로)으로 놓인다.
//   오른쪽 = Assets 창의 '신 사양' 탭. 부품 검색 · 축 탭 · 썸네일 그리드 · 시험 생성 · 보관함.
//
// 이 모드는 메인 프롬프트 글에 **쓰지 않는다.** 고른 것은 생성 요청에만 실리고, 고정 사양
// (모델 · scale · 해상도 · 메인 프롬프트 틀)은 서버가 쥔다(`core/character_builder_v5.py`).
// 그래서 Interactive 처럼 원본 프롬프트를 잡아 뒀다 되돌리는 절차가 없다 - 덮개만 걷으면 된다.
//
// 백엔드 계약(docs/ASSETS_V5_BUILDER_BACKEND_SRS_2026_10_11.md):
//   GET  /api/character-parts                    부품 카탈로그(data/character_parts.json)
//   GET  /api/character-asset/v5/spec            고정 사양(해상도 셋 · 유료 여부)
//   POST /api/character-asset/v5/generate        시험 생성
//   POST /api/character-asset/save               target.builder 에 부품 구성을 실어 저장
//   GET  /api/character-asset/list | detail      spec === 'v5' · builder_v5
//   GET  /api/character-asset/v5/candidate-check 결과가 투명 배경인가
//
// 신 사양은 **투명 배경이 전제**다(사용자 결정 2026-10-11 - 구 사양과 갈리는 선). 투명하지 않은 결과가 오면
// 경고한다(다시 생성해야 한다). 저장은 막지 않는다 - 그 그림은 **V4.5 구 사양으로** 저장된다.
// 판정은 서버가 한다(`core/character_builder_v5.transparency`). 저장을 구 사양으로 돌리는 것도 같은 함수라
// 화면의 경고와 실제로 저장되는 자리가 어긋나지 않는다(화면은 저장 응답의 `spec` 을 읽는다).
//
// 검색은 Interactive 와 같은 잣대다: 태그 이름과 한글 설명(TAG_DESC) 양쪽을 본다.
// ⚠️ 아래 import 의 `?v=` 는 interactivePanel.mjs 와 **같은 글자**여야 한다 - 다르면 2MB 모듈을 두 번 받는다.
import {TAG_DESC} from './interactiveAxes.mjs?v=20260913-gap3385';

// 앞의 일곱은 부품 카탈로그의 블록이고, 'etc'(기타)는 카탈로그가 없는 블록이다 - 직접 쓴 것만 담는다.
// 어느 블록에든 직접 쓸 수 있다(사용자 결정 2026-10-11 - Interactive 의 캐릭터 슬롯과 같은 사양).
const ETC_BLOCK = 'etc';
// 상세 화면에서 숨겨 둔 것(사용자 지시 2026-10-11 - 자리가 모자라 그림이 잘려 보였다). 지운 것이 아니다:
// 설명은 여태 쓰이지 않은 칸이라 당분간 숨기고 나중에 따로 펼치는 자리로 뺀다. 부품 구성 줄은 Character Prompt 가
// 같은 것을 말하므로 숨긴다(저장된 값 · 저장 길은 그대로다).
const SHOW_DETAIL_DESCRIPTION = false;
const SHOW_DETAIL_COMPOSITION = false;
// 네거티브(사용자 지시 2026-10-11 · NAI 전용): 여기 적은 것은 생성할 때 `-1::a, b ::` 한 묶음으로 맨 뒤에 실린다
// (묶는 일은 서버가 한다 - `core/character_builder_v5._caption_tags`). 화면은 태그만 받는다.
const NEGATIVE_BLOCK = 'negative';
const BLOCK_ORDER = ['hair', 'face', 'body', 'species', 'outfit', 'accessory', 'item', ETC_BLOCK, NEGATIVE_BLOCK];
const BLOCK_ICONS = {
  hair: '\u{1F487}', face: '\u{1F441}', body: '\u{1F9CD}', species: '\u{1F9EC}',
  outfit: '\u{1F457}', accessory: '\u{1F452}', item: '\u{1F392}', etc: '\u270F\uFE0F', negative: '\u2296',
};
// 서버(`core/character_builder_v5.free_text`)와 같은 잣대. NAIA 가 프롬프트 문법으로 읽는 글자는 못 쓴다 -
// 눌러서 400 을 받게 두지 않고 여기서 먼저 말한다.
const FREE_TEXT_FORBIDDEN = /[\u0000-\u001f\u007f<>|#$`\\"\u201c\u201d\uff02]|__/;
const FREE_TEXT_MAX = 300;
const WEIGHT_RE = /^\s*(-?\d+(?:\.\d+)?)\s*::\s*([\s\S]*?)\s*::\s*$/;
const WEIGHT_OPEN_RE = /^\s*-?\d+(?:\.\d+)?\s*::/;

/** `1.3::dark persona ::` -> {weight: '1.3', text: 'dark persona'} (Interactive 의 칩과 같은 규칙). */
function weightedPart(raw) {
  const m = WEIGHT_RE.exec(String(raw));
  return m ? {weight: m[1], text: m[2]} : {weight: null, text: String(raw)};
}

/** 카탈로그와 견줄 맨 태그: 가중치 · 강조 괄호를 뗀 것. */
function barePart(raw) {
  return weightedPart(raw).text.trim().replace(/^[{\[]+/, '').replace(/[}\]]+$/, '').trim();
}

/** 입력 칸의 글 -> 부품 목록. 쉼표 · 줄바꿈으로 자르되 가중치 묶음(`1.2::a, b ::`)은 하나로 둔다. */
function splitParts(text) {
  const out = [];
  let group = null;
  for (const raw of String(text || '').split(/[,\n]/)) {
    const piece = raw.replace(/\s+/g, ' ').trim();
    if (group) {
      if (piece) group.push(piece);
      if (piece.endsWith('::')) { out.push(group.join(', ')); group = null; }
      continue;
    }
    if (!piece) continue;
    if (WEIGHT_OPEN_RE.test(piece) && !piece.endsWith('::')) { group = [piece]; continue; }
    out.push(piece);
  }
  if (group) out.push(group.join(', '));        // 닫지 않은 묶음 - 쓴 대로 둔다
  return out.filter((item, index) => out.indexOf(item) === index);
}

/** 문장 꼴인가(칩을 기울여 구분한다 - Interactive 와 같은 잣대). */
function isProsePart(text) {
  const s = String(text || '').trim();
  return s.length >= 18 && s.split(/\s+/).length >= 3;
}
const GENDERS = [['girl', 'Female'], ['boy', 'Male'], ['other', 'Other']];
// 프롬프트의 인물 태그 -> 성별 단추. 글을 블록으로 가를 때 이것은 부품이 아니라 단추로 간다.
const PERSON_TAGS = new Map([
  ['girl', 'girl'], ['1girl', 'girl'], ['female', 'girl'],
  ['boy', 'boy'], ['1boy', 'boy'], ['male', 'boy'],
  ['other', 'other'], ['1other', 'other'],
]);
const RESOLUTION_LABEL = {standard: '표준', high: '고해상도', ultra: '초고해상도'};
const DRAFT_KEY = 'naia.assetsV5.draft';
// 시험 그림을 처음 놓는 배율의 상한(높이를 채우느라 좌우를 자르는 정도) · 휠로 키울 수 있는 끝.
const STAGE_BASE_MAX = 1.12;
const STAGE_ZOOM_MAX = 8;
// 시험 그림을 이만큼 쥔다(넘으면 가장 오래된 것부터 버린다). 서버가 쥐어 주는 수(`CANDIDATE_RETENTION_LIMIT` = 24)와
// 같다 - 예전의 8 은 후보 줄 한 줄에 맞춘 값이라, 아홉 번째를 만들면 첫 그림이 사라져 다시는 고를 수 없었다
// (사용자 제보 2026-10-11). 줄은 옆으로 굴린다.
const CANDIDATE_MAX = 24;
const SEARCH_MAX = 150;        // 검색 결과 칸 수. 넘으면 넘었다고 말한다
const SEARCH_DELAY = 150;
const BAND_MIN = 0.05;         // 다시 그릴 띠의 최소 높이(그림 높이의 5% - 서버의 문턱과 같다)

export function createCharacterBuilderV5({
  document,
  fetchFn = (...args) => globalThis.fetch(...args),
  escHtml,
  showToast,
  showAppDialog = null,
  showPromptDialog = null,
  leftMount,
  rightMount,
  isNai = () => true,
  // 화면이 바뀌어 덮개를 올리거나 내려야 할 때 부른다(바깥이 body 표식과 탭을 맞춘다).
  onViewChange = () => {},
  // [C1 + 레퍼런스 인셋 적용] 이 돌려받은 인셋 상태를 넘긴다(Result 탭의 핀 배지가 같은 상태를 본다).
  onReferenceInsetPin = () => {},
  // 앱의 태그 자동완성을 입력 칸에 붙인다(메인 프롬프트 · 캐릭터 프롬프트와 같은 것).
  bindTagAssist = () => {},
}) {
  if (!leftMount || !rightMount) return null;

  let active = false;            // 덮개가 올라와 있는가(신 사양 탭이 보이는 동안)
  let loading = null;            // 카탈로그 · 사양을 받는 중인 약속
  let loadError = '';
  let catalog = null;
  let spec = null;
  const tagInfo = new Map();     // 태그 -> {block, part(부품 정의), entry(태그 객체)}
  const blockDef = new Map();    // 블록 키 -> 블록 정의

  let draft = emptyDraft();
  let activeBlock = 'hair';
  const activePart = new Map();  // 블록 키 -> 지금 펼친 부품 키
  let query = '';
  let searchTimer = null;

  // 후보는 **객체로** 쥔다(인덱스가 아니라). 새 후보가 앞에 끼어들어도 고른 것이 안 바뀐다.
  // 제작과 바리에이션은 후보 줄을 따로 쥔다 - 화면을 오가도 서로 섞이지 않는다.
  const candidateSets = {create: [], variation: []};
  const pickedCandidate = {create: null, variation: null};
  let seedLock = false;
  let lockedSeed = null;
  let saving = false;
  let applying = false;          // [C1 + 레퍼런스 인셋 적용] 이 가 있는 동안
  // 시험 그림을 들여다보는 배율과 자리. `zoom` 이 null 이면 기본 배율(아래 `stageFit`)로 놓는다.
  // 보고 있는 그림이 바뀌면 처음으로 돌아간다 - 앞 그림에서 얼굴을 확대해 뒀다고 새 그림이 얼굴부터 보이면 안 된다.
  const stageView = {key: '', zoom: null, x: 0, y: 0};

  let view = 'gallery';          // 'gallery'(기본) | 'create' | 'variation'
  let builtView = '';            // 오른쪽 창의 뼈대를 세운 화면(바뀔 때만 다시 세운다)
  let store = [];                // 신 사양 캐릭터(spec === 'v5')
  let storeSeq = 0;
  let selectedId = '';           // 선택 화면에서 고른 캐릭터
  let selectedVar = '';          // 그 캐릭터의 고른 그림('' = 대표)
  // 바리에이션마다의 캐릭터 프롬프트(해시 -> {prompt, uc, recovered}). 대표의 것은 `detail` 에 있다.
  // 그림마다 자기 프롬프트를 갖는다 - 대표의 것을 바리에이션에 보여 주면 적용되는 글과 보이는 글이 달라진다.
  const imagePrompts = new Map();
  // [불러오기시 의상 제거] - 구 사양 화면과 **같은 설정**이다(같은 저장 키). 한쪽에서 켜면 다른 쪽에서도 켜져 있다.
  const STRIP_OUTFIT_KEY = 'naia.characterAsset.stripOutfit';
  let stripOutfitMemo = false;       // 브라우저 저장소를 못 쓸 때(사생활 모드)의 기억
  function stripOutfit() {
    try {
      const stored = globalThis.localStorage?.getItem(STRIP_OUTFIT_KEY);
      if (stored === '1' || stored === '0') stripOutfitMemo = stored === '1';
    } catch (_) { /* 사생활 모드 */ }
    return stripOutfitMemo;
  }
  function setStripOutfit(next) {
    stripOutfitMemo = !!next;
    try { globalThis.localStorage?.setItem(STRIP_OUTFIT_KEY, stripOutfitMemo ? '1' : '0'); }
    catch (_) { /* 사생활 모드 */ }
  }
  let detail = null;             // 고른 캐릭터의 상세(그림들 · 이름 · 설명 · 구성)
  let detailSeq = 0;
  let deleteArmed = '';          // 지우기는 두 번 누른다 - 한 번 눌린 단추의 표식
  // 바리에이션 작업: {id, name, source('' = 대표), width, height, paid, revision, band: {start, end}}
  let work = null;

  function emptyDraft() {
    const parts = {};
    for (const key of BLOCK_ORDER) parts[key] = [];
    return {gender: 'girl', resolution: 'standard', parts};
  }

  function newRequestId() {
    try {
      return globalThis.crypto.randomUUID().replace(/-/g, '');
    } catch {
      return `cb${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
    }
  }

  // ------------------------------------------------------------------ 통신

  async function getJson(url) {
    const response = await fetchFn(url, {cache: 'no-store'});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  }

  async function postJson(url, body) {
    const response = await fetchFn(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body || {}),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  }

  function ensureLoaded() {
    if (catalog && spec) return Promise.resolve();
    if (loading) return loading;
    loadError = '';
    loading = Promise.all([getJson('/api/character-parts'), getJson('/api/character-asset/v5/spec')])
      .then(([parts, sp]) => {
        catalog = parts;
        spec = sp;
        indexCatalog();
        restoreDraft();
      })
      .catch(error => {
        loadError = String(error?.message || error);
      })
      .finally(() => {
        loading = null;
        if (active) renderAll();
      });
    return loading;
  }

  function indexCatalog() {
    tagInfo.clear();
    blockDef.clear();
    for (const block of catalog?.blocks || []) {
      blockDef.set(block.key, block);
      for (const part of block.parts || []) {
        for (const entry of part.tags || []) tagInfo.set(entry.tag, {block: block.key, part, entry});
      }
      if (!activePart.has(block.key)) activePart.set(block.key, firstGridPart(block)?.key || '');
    }
    // '기타' 는 카탈로그에 없다 - 그리드가 없는 블록으로 끼워 둔다.
    if (blockDef.size) {
      blockDef.set(ETC_BLOCK, {key: ETC_BLOCK, label: '기타', parts: []});
      blockDef.set(NEGATIVE_BLOCK, {key: NEGATIVE_BLOCK, label: '네거티브', parts: []});
    }
  }

  /** 블록을 처음 열 때 펼칠 부품. 그림이 있는 축을 먼저 본다 - 색 · 길이는 늘 위에 함께 보이니까. */
  function firstGridPart(block) {
    const parts = block?.parts || [];
    return parts.find(part => part.kind === 'thumb') || parts[0] || null;
  }

  // ------------------------------------------------------------------ 초안

  /** 초안은 이 브라우저에만 남긴다. 탭을 떠났다 와도 고르던 것이 그대로다. */
  function saveDraft() {
    // 남기는 것은 **제작 화면의 초안**뿐이다. 바리에이션 화면의 구성은 그 그림의 것이라 초안을 덮으면 안 된다.
    if (view !== 'create') return;
    try {
      globalThis.localStorage?.setItem(DRAFT_KEY, JSON.stringify(draft));
    } catch (_) { /* 사생활 모드 */ }
  }

  function restoreDraft() {
    let raw = null;
    try { raw = JSON.parse(globalThis.localStorage?.getItem(DRAFT_KEY) || 'null'); } catch (_) { raw = null; }
    if (!raw || typeof raw !== 'object') return;
    applyBuilder(raw);
  }

  /** 저장된 구성(초안 · 보관함)을 받아들인다. 카탈로그에 없는 것도 그대로 둔다 - 직접 쓴 것일 수 있다. */
  function applyBuilder(raw) {
    const next = emptyDraft();
    if (GENDERS.some(([key]) => key === raw.gender)) next.gender = raw.gender;
    if ((spec?.resolutions || []).some(item => item.key === raw.resolution)) next.resolution = raw.resolution;
    for (const key of BLOCK_ORDER) {
      for (const item of (raw.parts && raw.parts[key]) || []) {
        const tag = (typeof item === 'string' ? item : String(item?.tag || '')).replace(/\s+/g, ' ').trim();
        if (tag && !next.parts[key].includes(tag)) next.parts[key].push(tag);
      }
    }
    draft = next;
  }

  function builderPayload(source = draft) {
    const parts = {};
    for (const key of BLOCK_ORDER) if (source.parts[key].length) parts[key] = [...source.parts[key]];
    return {version: 1, gender: source.gender, parts, resolution: source.resolution, pose_slot: ''};
  }

  const totalParts = () => BLOCK_ORDER.reduce((n, key) => n + draft.parts[key].length, 0);
  // 그릴 것(네거티브를 뺀 것). 뺄 것만 적어서는 그릴 수 없다.
  const positiveParts = () => totalParts() - draft.parts[NEGATIVE_BLOCK].length;

  // ------------------------------------------------------------------ 그리기 - 칸

  function tagTip(tag) {
    const desc = (TAG_DESC || {})[tag];
    return desc ? `${tag} · ${desc}` : String(tag);
  }

  function thumbUrl(key) {
    const cut = String(key).indexOf('/');
    return `/api/interactive-thumb?axis=${encodeURIComponent(key.slice(0, cut))}`
      + `&tag=${encodeURIComponent(key.slice(cut + 1))}`;
  }

  /** 칸의 그림 자리. 썸네일이 없는 부품은 둘뿐이다: 색(색 칸) · 단계(글자 칸). */
  function cellMedia(info) {
    const {entry, part} = info;
    if (entry.thumb) {
      return `<img src="${escHtml(thumbUrl(entry.thumb))}" alt="" loading="lazy" decoding="async">`;
    }
    if (entry.hex) return `<span class="cb5-swatch" style="background:${escHtml(entry.hex)}"></span>`;
    return `<span class="cb5-step">${escHtml(part.label)}</span>`;
  }

  /** 썸네일 칩 하나. `chosen` 은 '선택됨' 배지 · 테두리를 켠다(그리드에서만 - 왼쪽 줄은 전부 고른 것이라 안 켠다). */
  function cellHtml(tag, {chosen = false, act = 'on'} = {}) {
    const info = tagInfo.get(tag);
    if (!info) return '';
    const sensitive = !!(info.part.adult || info.entry.adult);
    const cls = `ia-cell cb5-cell${chosen ? ' on' : ''}${sensitive ? ' is-sensitive' : ''}`;
    const label = act === 'on' ? `${tag} 넣기` : `${tag} 빼기`;
    return `<div class="${cls}" data-tag="${escHtml(tag)}" data-cb-tip="${escHtml(tag)}"`
      + ` data-cb-tip-hint="${act === 'on' ? '+ 를 눌러 넣기' : '− 를 눌러 빼기'}" aria-label="${escHtml(tagTip(tag))}">`
      + `<span class="ia-cell-img">${cellMedia(info)}`
      + `${sensitive ? '<span class="ia-cell-veil">보기</span>' : ''}</span>`
      + `<span class="ia-cell-cap"><span class="ia-cell-name">${escHtml(tag)}</span>`
      + `<button type="button" class="ia-cell-act" data-act="${act}" data-cb-toggle="${escHtml(tag)}"`
      + ` aria-label="${escHtml(label)}">${act === 'on' ? '+' : '−'}</button></span></div>`;
  }

  // ------------------------------------------------------------------ 그리기 - 왼쪽

  /** 고른 부품 하나 = 글자 칩(Interactive 의 칩과 같은 마크업). 가중치는 배지로 떼고, 문장은 기울인다. */
  function chipHtml(blockKey, raw, index) {
    const {weight, text} = weightedPart(raw);
    const bare = barePart(raw);
    const prose = isProsePart(text);
    const negative = weight != null && Number(weight) < 0;
    const cls = `ia-chip${prose ? ' is-prose' : ''}${negative ? ' is-negw' : ''}`;
    return `<span class="${cls}" data-cb-tip="${escHtml(bare)}" data-cb-tip-hint="× 로 빼기 · 줄을 누르면 고쳐 쓰기">`
      + (weight ? `<b class="ia-chip-w">${escHtml(weight)}\u00d7</b>` : '')
      + `<span class="ia-chip-t">${escHtml(text)}</span>`
      + `<button type="button" class="ia-chip-x" data-cb-chip-del="${index}" data-cb-chip-block="${escHtml(blockKey)}"`
      + ` tabindex="-1" aria-label="${escHtml(text)} 빼기" title="빼기">&times;</button></span>`;
  }

  function autosizeSlotInput(input) {
    if (!input) return;
    input.style.height = 'auto';
    input.style.height = `${Math.min(160, Math.max(58, input.scrollHeight + 2))}px`;
  }

  // ------------------------------------------------------------------ 부품 툴팁(이벤트 맵의 카드)
  //
  // 이 화면에서는 자동완성의 태그 정보 판(IMPLIES · RELATED · RATING)을 띄우지 않는다 - 판이 커서 그리드를 통째로
  // 가린다(사용자 지시 2026-10-11). 대신 이벤트 맵의 툴팁과 같은 작은 카드(.em-tip)를 칸 · 칩에 댄다:
  // 이름 · 분류 · 설명 · Danbooru 게시물 수 · 썸네일. 포함 / 제외 줄은 비워 둔다(이 화면에는 그런 수가 없다).
  let tipEl = null;
  let tipOwner = null;
  const tipLooked = new Map();     // 태그 -> {desc, count} | null(조회해 봤는데 없다)
  const tipAsked = new Set();

  function ensureTip() {
    if (tipEl && document.body.contains(tipEl)) return tipEl;
    tipEl = document.createElement('div');
    tipEl.className = 'em-tip';
    document.body.appendChild(tipEl);          // body 직계 - 화면 안에 두면 overflow 에 잘린다
    return tipEl;
  }

  async function askTip(tag) {
    if (tipLooked.has(tag) || tipAsked.has(tag)) return;
    tipAsked.add(tag);
    try {
      const response = await fetchFn(`/api/tag/lookup?tag=${encodeURIComponent(tag)}`);
      const data = response.ok ? await response.json() : null;
      tipLooked.set(tag, data && data.tag ? {desc: String(data.desc || ''), count: Number(data.count) || 0} : null);
    } catch (_) {
      tipLooked.set(tag, null);
    }
    if (tipOwner && tipOwner.dataset.cbTip === tag) paintTip(tipOwner);
  }

  function paintTip(owner) {
    const tip = ensureTip();
    const tag = owner.dataset.cbTip || '';
    const info = tagInfo.get(tag) || tagInfo.get(tag.toLowerCase());
    const looked = tipLooked.get(tag);
    const source = info ? `${blockDef.get(info.block)?.label || ''} · ${partLabel(info.part)}` : '직접 쓴 것';
    const desc = (info && (TAG_DESC || {})[info.entry.tag]) || looked?.desc || '';
    const sensitive = !!(info && (info.part.adult || info.entry.adult));
    const thumb = info?.entry.thumb && !sensitive
      ? `<img class="em-tip-thumb" alt="" src="${escHtml(thumbUrl(info.entry.thumb))}">` : '';
    const waiting = !desc && looked === undefined && !isProsePart(tag);
    tip.innerHTML = `<div class="em-tip-row"><div class="em-tip-main">`
      + `<div class="em-tip-head"><span class="em-tip-tag">${escHtml(tag)}</span>`
      + `<span class="em-tip-src">${escHtml(source)}</span></div>`
      + (desc ? `<div class="em-tip-desc">${escHtml(desc)}</div>`
        : (waiting ? '<div class="em-tip-desc em-tip-wait">…</div>' : ''))
      + `<div class="em-tip-stats">${looked?.count ? `Danbooru ${looked.count.toLocaleString('en-US')}` : ''}</div>`
      + `<div class="em-tip-foot"><div class="em-tip-hint">${escHtml(owner.dataset.cbTipHint || '')}</div></div>`
      + `</div>${thumb}</div>`;
    tip.classList.add('open');
    // 이벤트 맵과 같은 자리: 대상 가운데의 살짝 오른쪽 · 바로 아래. 아래가 모자라면 위로.
    const a = owner.getBoundingClientRect();
    const b = tip.getBoundingClientRect();
    const view = document.defaultView || globalThis;
    let left = a.left + a.width * 0.5 + 16;
    left = Math.max(8, Math.min(left, view.innerWidth - b.width - 8));
    let top = a.bottom + 6;
    if (top + b.height > view.innerHeight - 8) top = a.top - b.height - 6;
    tip.style.left = `${Math.round(left)}px`;
    tip.style.top = `${Math.round(Math.max(8, top))}px`;
  }

  function showTip(owner) {
    if (!owner || owner === tipOwner) return;
    tipOwner = owner;
    const tag = owner.dataset.cbTip || '';
    if (tag && !isProsePart(tag)) void askTip(tag);     // 문장은 조회할 태그가 아니다
    paintTip(owner);
  }

  function hideTip() {
    tipOwner = null;
    if (tipEl) tipEl.classList.remove('open');
  }

  function onTipOver(event) {
    const owner = event.target.closest ? event.target.closest('[data-cb-tip]') : null;
    if (owner) showTip(owner);
  }

  function onTipOut(event) {
    const owner = event.target.closest ? event.target.closest('[data-cb-tip]') : null;
    if (!owner || owner.contains(event.relatedTarget)) return;
    if (owner === tipOwner) hideTip();
  }

  function renderLeft() {
    hideTip();           // 다시 그리면 툴팁의 주인이 사라진다
    if (!catalog) {
      leftMount.innerHTML = `<div class="cb5-empty">${escHtml(loadError
        ? `부품 목록을 불러오지 못했습니다: ${loadError}` : '부품 목록을 불러오는 중...')}</div>`;
      return;
    }
    const genders = GENDERS.map(([key, label]) =>
      `<button type="button" class="cb5-seg-btn${draft.gender === key ? ' is-on' : ''}"`
      + ` data-cb-gender="${key}" aria-pressed="${draft.gender === key}">${label}</button>`).join('');
    const rows = BLOCK_ORDER.map(key => {
      const block = blockDef.get(key);
      if (!block) return '';
      const picks = draft.parts[key];
      const open = key === activeBlock;
      // 열린 줄은 입력 칸이다(Interactive 의 슬롯과 같다) - 아는 사람은 그냥 치고, 오른쪽 그리드에서 눌러도 여기에 들어온다.
      // 닫힌 줄은 글자 칩. 썸네일은 그리드에만 둔다 - 왼쪽에 썸네일을 놓으면 몇 개만 골라도 줄이 화면 밖으로 늘어진다.
      const body = open
        ? `<textarea class="ia-slot-input" data-cb-slot-input="${escHtml(key)}" rows="1" spellcheck="false"`
          + ` placeholder="${key === NEGATIVE_BLOCK
            ? '여기에 적은 프롬프트는 자동으로 -1:: 프롬프트1, 프롬프트2, ... :: 로 처리됩니다'
            : key === ETC_BLOCK ? '태그 · 자연어를 직접 씁니다 (쉼표로 여러 개)'
              : '태그 입력 (쉼표로 여러 개) · 오른쪽에서 골라도 됩니다'}">${escHtml(picks.join(', '))}</textarea>`
        : `<div class="ia-block-chips">${picks.length
          ? picks.map((tag, index) => chipHtml(key, tag, index)).join('')
          : '<span class="ia-chip-empty">비어 있음</span>'}</div>`;
      return `<div class="ia-block cb5-block${key === NEGATIVE_BLOCK ? ' is-negative' : ''}`
        + `${open ? ' is-open is-editing' : ''}${picks.length ? '' : ' is-empty'}"`
        + ` data-cb-block="${escHtml(key)}">`
        + `<div class="ia-block-label"><span class="ia-block-title">`
        + `<span class="ia-block-icon">${BLOCK_ICONS[key] || ''}</span>`
        + `<span class="ia-block-name">${escHtml(block.label)}</span></span>`
        + `<span class="ia-block-axis">${escHtml(key)}</span></div>`
        + body
        + `<div class="ia-block-meta"><span class="ia-block-count" data-cb-count="${escHtml(key)}">`
        + `${picks.length || ''}</span></div></div>`;
    }).join('');
    leftMount.innerHTML = `<div class="cb5-head">`
      + `<span class="cb5-title">${view === 'variation'
        ? `${escHtml(work?.name || '')} · 바리에이션` : '캐릭터 제작 · V5'}</span>`
      + `<div class="cb5-seg" role="group" aria-label="인물">${genders}</div>`
      // 비우기는 새 캐릭터를 지을 때만. 바리에이션은 그 그림의 구성에서 일부만 바꾸는 일이다.
      + (view === 'create'
        ? `<button type="button" class="cb5-btn" data-cb-act="clear"${totalParts() ? '' : ' disabled'}>Clear</button>`
        : '')
      + `</div><div class="cb5-rows">${rows}</div>`;
    const slotInput = leftMount.querySelector('[data-cb-slot-input]');
    autosizeSlotInput(slotInput);
    // 고른 것은 자동완성이 칸의 글을 바꾸고 input 을 쏜다 - 친 것과 같은 길(`onLeftInput`)로 들어온다.
    if (slotInput) bindTagAssist(slotInput);
  }

  // ------------------------------------------------------------------ 자동 분류

  /** 카탈로그에서 그 태그의 블록을 찾는다(가중치 · 강조 괄호는 떼고, 대소문자는 가리지 않는다). 없으면 ''. */
  function blockOfPart(raw) {
    const bare = barePart(raw);
    return (tagInfo.get(bare) || tagInfo.get(bare.toLowerCase()))?.block || '';
  }

  /** 프롬프트 글을 블록으로 가른다(사용자 지시 2026-10-11 - 부품은 색인돼 있으니 자동으로 가를 수 있다).
   *  카탈로그에 있는 태그는 제 블록으로, 없는 것(미색인 · 자연어 · 묶음)은 '기타' 로. 인물 태그는 성별로 돌려준다. */
  function classifyParts(text) {
    const parts = {};
    for (const key of BLOCK_ORDER) parts[key] = [];
    let gender = '';
    for (const entry of splitParts(text)) {
      const person = PERSON_TAGS.get(barePart(entry).toLowerCase());
      if (person) {
        gender = gender || person;
        continue;
      }
      const key = blockOfPart(entry) || ETC_BLOCK;
      if (!parts[key].includes(entry)) parts[key].push(entry);
    }
    return {parts, gender};
  }

  /** '기타' 에 쓴 것 가운데 카탈로그의 부품은 제 블록으로 옮긴다 - 프롬프트를 통째로 붙여넣으면 알아서 갈린다.
   *  다른 블록에 직접 쓴 것은 건드리지 않는다(사람이 그 자리에 적은 것이다). 옮긴 개수를 돌려준다. */
  function sortEtcBlock() {
    const {parts, gender} = classifyParts(draft.parts[ETC_BLOCK].join(', '));
    let moved = 0;
    for (const key of BLOCK_ORDER) {
      if (key === ETC_BLOCK) continue;
      for (const entry of parts[key]) {
        moved += 1;
        if (!draft.parts[key].some(item => barePart(item) === barePart(entry))) draft.parts[key].push(entry);
      }
    }
    const personDropped = parts[ETC_BLOCK].length + moved < draft.parts[ETC_BLOCK].length;
    if (gender && personDropped) draft.gender = gender;
    if (!moved && !personDropped) return 0;
    draft.parts[ETC_BLOCK] = parts[ETC_BLOCK];
    saveDraft();
    return moved || 1;
  }

  /** 열린 줄의 입력 칸에 초점을 준다(줄을 눌러 열었을 때). 글 끝에 커서를 둔다. */
  function focusSlotInput() {
    const input = leftMount.querySelector('[data-cb-slot-input]');
    if (!input) return;
    input.focus({preventScroll: true});
    input.setSelectionRange(input.value.length, input.value.length);
  }

  // ------------------------------------------------------------------ 그리기 - 오른쪽

  function matchesQuery(tag, q) {
    if (String(tag).toLowerCase().includes(q)) return true;
    const desc = (TAG_DESC || {})[tag];
    return !!desc && String(desc).toLowerCase().includes(q);
  }

  /** 그 블록에 든 것의 **맨 태그** 모음. 가중치를 건 것(`1.2::twintails ::`)도 그 부품을 고른 것으로 친다. */
  function chosenSet(blockKey) {
    return new Set((draft.parts[blockKey] || []).map(barePart));
  }

  function partLabel(part) {
    // 신체 블록에는 '피부' 가 둘이다(그림 축과 색 팔레트). 색 쪽을 가려 부른다.
    return part.kind === 'palette' && part.key === 'skin_color' ? '피부 색' : part.label;
  }

  function searchHtml(q) {
    const groups = new Map();
    let total = 0;
    for (const [tag, info] of tagInfo) {
      if (!matchesQuery(tag, q)) continue;
      total += 1;
      if (total > SEARCH_MAX) continue;
      if (!groups.has(info.block)) groups.set(info.block, []);
      groups.get(info.block).push(tag);
    }
    if (!total) return '<div class="cb5-empty">찾는 부품이 없습니다</div>';
    const body = BLOCK_ORDER.filter(key => groups.has(key)).map(key => {
      const chosen = chosenSet(key);
      const cells = groups.get(key).map(tag =>
        cellHtml(tag, {chosen: chosen.has(tag), act: chosen.has(tag) ? 'off' : 'on'})).join('');
      return `<div class="cb5-hit-head">${escHtml(blockDef.get(key)?.label || key)}</div>`
        + `<div class="ia-cell-grid cb5-grid">${cells}</div>`;
    }).join('');
    // 자른 것은 자른다고 말한다 - 안 적으면 이것이 전부인 줄 안다.
    const more = total > SEARCH_MAX
      ? `<div class="cb5-note">${total}개 중 ${SEARCH_MAX}개만 보입니다. 더 좁혀 찾아 주세요.</div>` : '';
    return body + more;
  }

  /** 고른 블록의 그리드. 소분류(부품)는 그리드 오른쪽의 세로 목록이 고른다(사용자 지정 2026-10-11 -
   *  위에 가로로 늘어놓은 탭보다 오른쪽 목록을 선호). 접어 두는 것 없이 전부 보인다. */
  function blockHtml() {
    const block = blockDef.get(activeBlock);
    if (!block) return '';
    if (activeBlock === NEGATIVE_BLOCK) {
      return '<div class="cb5-empty">네거티브에는 고를 부품이 없습니다.<br>'
        + '왼쪽 칸에 빼고 싶은 것을 적습니다 - 생성할 때 -1:: ... :: 한 묶음으로 실립니다 (NAI 전용).</div>';
    }
    if (activeBlock === ETC_BLOCK) {
      return '<div class="cb5-empty">기타에는 고를 부품이 없습니다.<br>'
        + '왼쪽 칸에 직접 씁니다 - 색인되지 않은 태그 · 자연어 · 가중치(1.2::tag ::)를 그대로 받습니다.</div>';
    }
    const chosen = chosenSet(activeBlock);
    const part = block.parts.find(item => item.key === activePart.get(activeBlock)) || block.parts[0];
    const cells = (part?.tags || []).map(entry =>
      cellHtml(entry.tag, {chosen: chosen.has(entry.tag), act: chosen.has(entry.tag) ? 'off' : 'on'})).join('');
    return `<div class="ia-cell-grid cb5-grid">${cells}</div>`;
  }

  function partsHtml(searching) {
    const block = blockDef.get(activeBlock);
    if (!block) return '';
    const chosen = chosenSet(activeBlock);
    const open = searching ? '' : activePart.get(activeBlock);
    return block.parts.map(part => {
      const picked = part.tags.reduce((n, entry) => n + (chosen.has(entry.tag) ? 1 : 0), 0);
      return `<button type="button" class="cb5-part${part.key === open ? ' is-open' : ''}"`
        + ` data-cb-part="${escHtml(part.key)}" aria-pressed="${part.key === open}">`
        + `<span class="cb5-part-name">${escHtml(partLabel(part))}</span>`
        + `${picked ? `<span class="cb5-part-sel">${picked}</span>` : ''}`
        + `<span class="cb5-part-n">${part.tags.length}</span></button>`;
    }).join('');
  }

  function renderMain() {
    const host = rightMount.querySelector('[data-cb-role="main"]');
    if (!host) return;
    hideTip();
    const scroller = host.querySelector('.cb5-main-scroll');
    const top = scroller ? scroller.scrollTop : 0;
    const q = query.trim().toLowerCase();
    const block = blockDef.get(activeBlock);
    const part = block?.parts.find(item => item.key === activePart.get(activeBlock)) || block?.parts[0];
    host.querySelector('[data-cb-role="main-title"]').textContent = q
      ? '검색 결과' : [block?.label || '', part ? partLabel(part) : ''].filter(Boolean).join(' · ');
    scroller.innerHTML = q ? searchHtml(q) : blockHtml();
    scroller.scrollTop = top;
    host.querySelector('[data-cb-role="parts"]').innerHTML = partsHtml(!!q);
  }

  // ------------------------------------------------------------------ 주소

  function candidateImage(candidate) {
    return `/api/character-asset/candidate/image?history_id=${encodeURIComponent(candidate.historyId)}`;
  }

  function assetImage(id, hash, revision) {
    return `/api/character-asset/image?id=${encodeURIComponent(id)}`
      + `${hash ? `&variation=${encodeURIComponent(hash)}` : ''}&v=${revision || 0}`;
  }

  function assetThumb(id, hash, revision) {
    return `/api/character-asset/thumb?id=${encodeURIComponent(id)}`
      + `${hash ? `&variation=${encodeURIComponent(hash)}` : ''}&size=grid&v=${revision || 0}`;
  }

  function storeName(item) {
    return String(item?.display_name || '').trim() || String(item?.id || '').slice(0, 8);
  }

  // ------------------------------------------------------------------ 그리기 - 결과 칸(제작 · 바리에이션 공용)

  const cands = () => candidateSets[view] || [];
  const picked = () => pickedCandidate[view] || null;

  function stageHtml(candidate, emptyText) {
    if (candidate?.status === 'done') {
      // 비투명 경고: 새 캐릭터는 구 사양으로 저장되고, 바리에이션은 경고만 한다(둘 다 저장은 된다 - 사용자 결정).
      const note = view === 'variation' ? '' : '<small>저장하면 V4.5 구 사양으로 저장됩니다</small>';
      return `<img data-cb-stage-img draggable="false" src="${escHtml(candidateImage(candidate))}" alt="">`
        + (candidate.opaque
          ? `<span class="cb5-stage-warn">투명 배경이 아닙니다 · 다시 생성해 주세요${note}</span>` : '');
    }
    if (candidate?.status === 'pending') return '<span class="cb5-stage-empty">생성 중...</span>';
    if (candidate?.status === 'error') {
      return `<span class="cb5-stage-empty is-error">${escHtml(candidate.message || '생성하지 못했습니다')}</span>`;
    }
    return `<span class="cb5-stage-empty">${escHtml(emptyText)}</span>`;
  }

  function stripHtml() {
    const current = picked();
    return cands().map((candidate, index) => {
      const cls = `cb5-cand${candidate === current ? ' is-on' : ''} is-${candidate.status}`
        + `${candidate.saved ? ' is-saved' : ''}${candidate.opaque ? ' is-opaque' : ''}`;
      const inner = candidate.status === 'done'
        ? `<img src="${escHtml(candidateImage(candidate))}" alt="" loading="lazy">`
        : `<span>${candidate.status === 'pending' ? '...' : '!'}</span>`;
      return `<button type="button" class="${cls}" data-cb-cand="${index}"`
        + ` aria-label="후보 ${index + 1}">${inner}</button>`;
    }).join('');
  }

  function sideHtml() {
    const current = picked();
    const resolutions = (spec?.resolutions || []).map(item =>
      `<button type="button" class="cb5-seg-btn${draft.resolution === item.key ? ' is-on' : ''}"`
      + ` data-cb-res="${escHtml(item.key)}" aria-pressed="${draft.resolution === item.key}"`
      + ` title="${item.width} x ${item.height}">${escHtml(RESOLUTION_LABEL[item.key] || item.key)}</button>`).join('');
    const res = (spec?.resolutions || []).find(item => item.key === draft.resolution);
    // 금액 숫자는 적지 않는다(사용자 규칙) - 든다는 사실만.
    const paid = res?.paid ? '<span class="cb5-paid">Anlas 소모</span>' : '';
    const size = res ? `<span class="cb5-size">${res.width} x ${res.height}</span>` : '';
    const seedKnown = Number.isFinite(current?.seed);
    const seedText = seedLock && Number.isFinite(lockedSeed) ? String(lockedSeed) : '';
    // 투명한지 아직 모르는 동안(확인 중)에만 잠깐 막는다 - 어느 사양으로 저장되는지 말할 수 있어야 한다.
    const canSave = current?.status === 'done' && current.opaque !== null && !current.saved && !saving;
    const saveLabel = current?.saved ? '저장됨' : (current?.opaque ? '구 사양으로 저장' : '에셋으로 저장');
    // 그림 칸에는 title 을 달지 않는다 - 앱 툴팁으로 떠서, 들여다보는 내내 후보 줄을 가린다(라이브에서 봄).
    // 시드 고정은 크기 줄에 둔다. 아래 줄에 단추가 둘이라, 거기에 같이 두면 좁은 창에서 줄이 둘로 접혀 그림 칸이 깎인다.
    return `<div class="cb5-side-top"><span class="cb5-side-label">시험 생성</span>`
      + `<div class="cb5-seg" role="group" aria-label="해상도">${resolutions}</div></div>`
      + `<div class="cb5-side-sub">${size}${paid}`
      + `<label class="cb5-check"><input type="checkbox" data-cb-role="seedlock"`
      + `${seedLock ? ' checked' : ''}${seedKnown || seedLock ? '' : ' disabled'}> 시드 고정</label>`
      + `<span class="cb5-seed">${escHtml(seedText)}</span></div>`
      + `<div class="cb5-stage" data-cb-zoom="1" aria-label="시험 그림 - 휠로 확대 · 축소, 끌어서 옮기기, 두 번 눌러 처음 크기로">`
      + `${stageHtml(current, 'Generate 를 누르면 여기에 그립니다')}</div>`
      + `<div class="cb5-strip">${stripHtml()}</div>`
      + `<div class="cb5-side-bottom">`
      // 저장하기 전에 바로 써 본다: 이 그림을 만든 글을 C1 에, 그림을 레퍼런스 인셋에(사용자 지시 2026-10-11).
      + `<button type="button" class="cb5-btn" data-cb-act="cand-apply"`
      + `${current?.status === 'done' && current.historyId && !applying ? '' : ' disabled'}`
      + ` title="이 그림을 만든 프롬프트를 C1 에 넣고(쓰던 슬롯은 한 칸씩 밀려 꺼집니다) 그림을 레퍼런스 인셋으로 고정합니다">`
      + `C1 + 레퍼런스 인셋 적용</button>`
      + `<button type="button" class="cb5-btn is-primary" data-cb-act="save"${canSave ? '' : ' disabled'}>`
      + `${saveLabel}</button></div>`;
  }

  /** 바리에이션의 A|B. A = 원본(다시 그릴 띠를 시작 · 종료 선으로 정한다) · B = 인페인트 결과. */
  function abHtml() {
    const current = picked();
    const start = Math.round(work.band.start * 100);
    const end = Math.round(work.band.end * 100);
    const paid = work.paid ? '<span class="cb5-paid">Anlas 소모</span>' : '';
    const canSave = current?.status === 'done' && current.opaque !== null && !current.saved && !saving;
    return `<div class="cb5-ab-pane">`
      + `<div class="cb5-side-top"><span class="cb5-side-label">원본 A</span>`
      + `<span class="cb5-size" data-cb-role="band-text">다시 그릴 곳 ${start}% ~ ${end}%</span></div>`
      // 띠의 % 는 **그림의 행**이어야 한다. 그림 칸은 그림과 비율이 다를 수 있으므로(남는 곳이 생긴다),
      // 그림과 같은 비율의 상자를 칸 안에 꽉 차게 놓고 선 · 띠를 그 상자 기준으로 얹는다.
      + `<div class="cb5-stage cb5-band-stage">`
      + `<div class="cb5-band-box" data-cb-role="band-stage" style="--cb5-w:${work.width};--cb5-h:${work.height}">`
      + `<img src="${escHtml(assetImage(work.id, work.source, work.revision))}" alt="" draggable="false">`
      + `<div class="cb5-band" data-cb-role="band" style="top:${start}%;height:${end - start}%"></div>`
      + `<div class="cb5-band-line" data-cb-edge="start" style="top:${start}%"><span>시작</span></div>`
      + `<div class="cb5-band-line" data-cb-edge="end" style="top:${end}%"><span>종료</span></div>`
      + `</div></div>`
      + `<div class="cb5-side-bottom"><span class="cb5-size">${work.width} x ${work.height}</span>${paid}</div>`
      + `</div><div class="cb5-ab-pane">`
      + `<div class="cb5-side-top"><span class="cb5-side-label">결과 B</span></div>`
      + `<div class="cb5-stage">${stageHtml(current, 'Generate 를 누르면 띠 안을 다시 그립니다')}</div>`
      + `<div class="cb5-strip">${stripHtml()}</div>`
      + `<div class="cb5-side-bottom"><span class="cb5-seed"></span>`
      + `<button type="button" class="cb5-btn is-primary" data-cb-act="save"${canSave ? '' : ' disabled'}>`
      + `${current?.saved ? '저장됨' : '바리에이션으로 저장'}</button></div></div>`;
  }

  function renderSide() {
    const host = rightMount.querySelector('[data-cb-role="side"]');
    if (!host) return;
    if (view === 'variation' && work) host.innerHTML = abHtml();
    else if (view === 'create') host.innerHTML = sideHtml();
    syncStage();
    // 후보 줄은 한 줄로 굴린다. 고른 것이 줄 밖에 있으면 보이는 데로 민다(새 그림은 맨 앞에 온다).
    const strip = host.querySelector('.cb5-strip');
    const on = strip?.querySelector('.cb5-cand.is-on');
    if (strip && on) {
      // ⚠️ `offsetLeft` 는 줄이 아니라 위치 잡힌 조상이 기준이다 - 줄 안에서의 자리는 두 사각형의 차로 잰다.
      const stripBox = strip.getBoundingClientRect();
      const onBox = on.getBoundingClientRect();
      if (onBox.left < stripBox.left) strip.scrollLeft += onBox.left - stripBox.left;
      else if (onBox.right > stripBox.right) strip.scrollLeft += onBox.right - stripBox.right;
    }
  }

  // ------------------------------------------------------------------ 시험 그림 들여다보기(휠 · 끌기)

  /** 그림 칸과 그림의 치수. `base` = 처음 놓는 배율: 위아래가 남는 그림(폭에 맞춰진 것)은 높이를 채울 때까지 키운다 -
   *  좌우가 살짝 잘리고 인물이 크게 보인다(사용자 지시: "실제로 자르는 게 아니라 확대"). `STAGE_BASE_MAX` 를 넘기지는 않는다. */
  function stageFit(stage, img) {
    const W = stage.clientWidth;
    const H = stage.clientHeight;
    const iw = img.naturalWidth;
    const ih = img.naturalHeight;
    if (!W || !H || !iw || !ih) return null;
    const fit = Math.min(W / iw, H / ih);
    const dw = iw * fit;
    const dh = ih * fit;
    return {W, H, dw, dh, base: Math.min(STAGE_BASE_MAX, Math.max(1, H / dh))};
  }

  function placeStage(img, fit) {
    if (stageView.zoom == null) stageView.zoom = fit.base;
    const z = stageView.zoom;
    // 그림이 칸보다 큰 만큼만 옮길 수 있다 - 칸 밖으로 끌려 나가 빈 바닥만 보이는 일이 없다.
    const maxX = Math.max(0, (fit.dw * z - fit.W) / 2);
    const maxY = Math.max(0, (fit.dh * z - fit.H) / 2);
    stageView.x = Math.max(-maxX, Math.min(maxX, stageView.x));
    stageView.y = Math.max(-maxY, Math.min(maxY, stageView.y));
    img.style.transform = `translate(${stageView.x}px, ${stageView.y}px) scale(${z})`;
  }

  function zoomStage() {
    const stage = rightMount.querySelector('.cb5-stage[data-cb-zoom]');
    const img = stage?.querySelector('[data-cb-stage-img]');
    return stage && img ? {stage, img} : null;
  }

  /** 다시 그린 뒤 그림을 제자리에 놓는다. 그림이 바뀌었으면 처음 배율로. */
  function syncStage() {
    const found = zoomStage();
    if (!found) return;
    const key = picked()?.requestId || '';
    if (stageView.key !== key) Object.assign(stageView, {key, zoom: null, x: 0, y: 0});
    const place = () => {
      const fit = stageFit(found.stage, found.img);
      if (fit) placeStage(found.img, fit);
    };
    if (found.img.complete && found.img.naturalWidth) place();
    else found.img.addEventListener('load', place, {once: true});
    // 서버가 쥐는 시험 그림에도 끝이 있다(다른 화면의 후보와 한 줄을 쓴다). 사라진 것을 고르면 깨진 그림 대신 말로 알린다.
    found.img.addEventListener('error', () => {
      const candidate = picked();
      if (!candidate || candidate.status !== 'done' || (candidate.requestId || '') !== key) return;
      candidate.status = 'error';
      candidate.message = '이 시험 그림은 더 이상 남아 있지 않습니다 - 다시 생성해 주세요';
      renderSide();
    }, {once: true});
  }

  function onWheel(event) {
    // 후보 줄: 세로 휠로 옆으로 굴린다(줄이 한 줄이라 세로로 굴릴 것이 없다).
    const strip = event.target.closest('.cb5-strip');
    if (strip && strip.scrollWidth > strip.clientWidth && !event.deltaX) {
      event.preventDefault();
      strip.scrollLeft += event.deltaY;
      return;
    }
    if (!event.target.closest('.cb5-stage[data-cb-zoom]')) return;
    const found = zoomStage();
    const fit = found && stageFit(found.stage, found.img);
    if (!fit) return;
    event.preventDefault();
    const rect = found.stage.getBoundingClientRect();
    // 커서 아래의 점이 그 자리에 남게 키운다(칸의 가운데가 기준).
    const cx = event.clientX - rect.left - rect.width / 2;
    const cy = event.clientY - rect.top - rect.height / 2;
    const before = stageView.zoom ?? fit.base;
    const after = Math.max(1, Math.min(STAGE_ZOOM_MAX, before * Math.exp(-event.deltaY * 0.0015)));
    stageView.x = cx - (cx - stageView.x) * (after / before);
    stageView.y = cy - (cy - stageView.y) * (after / before);
    stageView.zoom = after;
    placeStage(found.img, fit);
  }

  function beginStageDrag(event, stage) {
    const found = zoomStage();
    const fit = found && stageFit(found.stage, found.img);
    if (!fit) return;
    event.preventDefault();
    const start = {x: event.clientX, y: event.clientY, ox: stageView.x, oy: stageView.y};
    const move = e => {
      stageView.x = start.ox + (e.clientX - start.x);
      stageView.y = start.oy + (e.clientY - start.y);
      placeStage(found.img, fit);
    };
    const stop = e => {
      stage.classList.remove('is-dragging');
      stage.removeEventListener('pointermove', move);
      stage.removeEventListener('pointerup', stop);
      stage.removeEventListener('pointercancel', stop);
      try { stage.releasePointerCapture(e.pointerId); } catch (_) { /* 이미 놓였다 */ }
    };
    try { stage.setPointerCapture(event.pointerId); } catch (_) { /* 잡지 못해도 끌 수는 있다 */ }
    stage.classList.add('is-dragging');
    stage.addEventListener('pointermove', move);
    stage.addEventListener('pointerup', stop);
    stage.addEventListener('pointercancel', stop);
  }

  function onDblClick(event) {
    if (!event.target.closest('.cb5-stage[data-cb-zoom]') || !zoomStage()) return;
    Object.assign(stageView, {zoom: null, x: 0, y: 0});
    syncStage();
  }

  // ------------------------------------------------------------------ 그리기 - 선택 화면(기본)

  /** 고른 그림('' = 대표)의 기록. 대표의 이름 · 설명은 캐릭터의 것이다. */
  function variationEntry(hash) {
    return (detail?.variations || []).find(entry => entry.hash === hash) || null;
  }

  function compositionOf(hash) {
    return (hash && variationEntry(hash)?.builder) || detail?.builder_v5 || null;
  }

  function compositionHtml(builder) {
    if (!builder) return '';
    const rows = BLOCK_ORDER.filter(key => (builder.parts?.[key] || []).length).map(key => {
      const tags = builder.parts[key].map(item => (typeof item === 'string' ? item : item?.tag)).filter(Boolean);
      return `<div class="cb5-comp-row"><b>${escHtml(blockDef.get(key)?.label || key)}</b>`
        + `<span>${escHtml(tags.join(', '))}</span></div>`;
    }).join('');
    // 구 사양에서 배경만 지워 옮긴 사본에는 부품 구성이 없다 - 빈 자리로 두지 않고 어디서 왔는지 적는다.
    const origin = builder.migrated
      ? '<div class="cb5-comp-origin">구 사양에서 이전 · 배경 제거</div>' : '';
    return rows || origin ? `<div class="cb5-comp">${origin}${rows}</div>` : '';
  }

  /** 고른 그림의 캐릭터 프롬프트. 아직 못 받았으면 null. */
  function promptOf(hash) {
    if (!detail) return null;
    if (!hash) {
      return {prompt: String(detail.character_prompt || ''), uc: String(detail.character_uc || ''),
        recovered: !!detail.recovered};
    }
    return imagePrompts.get(hash) || null;
  }

  /** 캐릭터 프롬프트 칸(구 사양 상세와 같은 꼴 - 읽기만 한다). 슬롯 · 레퍼런스 인셋에 실리는 글이 이것이다. */
  function promptHtml(hash) {
    const info = promptOf(hash);
    // [불러오기시 의상 제거] 는 구 사양 화면의 것과 같은 꼴 · 같은 문구다(`mod-btn-sm` 을 그대로 입는다).
    // 구 사양에서는 UC 라벨 줄에 있지만, 여기서는 UC 가 없는 그림이 많아 늘 있는 프롬프트 라벨 줄에 둔다.
    const strip = `<label class="mod-btn-sm char-asset-strip"`
      + ` data-naia-title="인물 태그 + 캐릭터 특징 + 악세서리/모자만 남기고 의상 태그를 뺍니다. UC 는 그대로 둡니다.">`
      + `<input type="checkbox" data-cb-role="strip-outfit"${stripOutfit() ? ' checked' : ''}>`
      + `<span>불러오기시 의상 제거</span></label>`;
    const label = `<div class="char-asset-uc-label-row"><div class="mod-section-label">Character Prompt ${
      hash ? '(바리에이션)' : '(대표)'}</div>${strip}</div>`;
    if (!info) return `<div class="char-asset-prompt-block">${label}<pre class="char-asset-pre">불러오는 중...</pre></div>`;
    const uc = info.uc
      ? `<div class="mod-section-label">Character UC</div>`
        + `<pre class="char-asset-pre char-asset-pre-uc">${escHtml(info.uc)}</pre>` : '';
    return `<div class="char-asset-prompt-block">${label}<pre class="char-asset-pre">${
      escHtml(info.prompt || '(이 그림에서는 캐릭터 프롬프트를 읽지 못했습니다)')}</pre>${uc}</div>`;
  }

  function detailHtml() {
    if (!selectedId) return '<div class="mod-empty char-asset-detail-empty">캐릭터를 선택하세요.</div>';
    if (!detail || detail.id !== selectedId) return '<div class="mod-empty char-asset-detail-empty">불러오는 중...</div>';
    const entry = selectedVar ? variationEntry(selectedVar) : null;
    const revision = entry ? entry.revision : detail.revision;
    const strip = [`<button type="button" class="char-asset-var${selectedVar ? '' : ' selected'}" data-cb-var=""`
      + ` title="대표"><img loading="lazy" src="${escHtml(assetThumb(detail.id, '', detail.revision))}" alt="">`
      + `<span class="char-asset-var-star">★</span></button>`]
      .concat((detail.variations || []).map(item =>
        `<button type="button" class="char-asset-var${item.hash === selectedVar ? ' selected' : ''}"`
        + ` data-cb-var="${escHtml(item.hash)}" title="${escHtml(item.name || '이름 없는 바리에이션')}">`
        + `<img loading="lazy" src="${escHtml(assetThumb(detail.id, item.hash, item.revision))}" alt=""></button>`))
      .join('');
    const armed = deleteArmed === `var:${selectedVar}`;
    const charArmed = deleteArmed === `char:${detail.id}`;
    // 이름 · 설명은 그림마다 자유롭게 적는다(사용자 결정). 대표의 것은 곧 캐릭터의 것이다.
    // 프롬프트를 읽지 못한 그림은 슬롯에 실을 글이 없다(서버도 거절한다) - 눌러서 실패하게 두지 않는다.
    const applyOff = promptOf(selectedVar)?.recovered ? '' : ' disabled';
    const nameValue = entry ? (entry.name || '') : (detail.display_name || '');
    const descValue = entry ? (entry.description || '') : (detail.description || '');
    return `<div class="char-asset-detail-head">`
      + `<div><span class="char-asset-detail-name">${escHtml(storeName(detail))}</span>`
      + `<span class="char-asset-detail-id">${escHtml(String(detail.id).slice(0, 16))}</span></div>`
      + `<div class="char-asset-detail-head-actions">`
      + `<button type="button" class="mod-btn-sm mod-btn-danger" data-cb-act="char-delete">`
      + `${charArmed ? '한 번 더 클릭하면 삭제' : '캐릭터 삭제'}</button></div></div>`
      + `<div class="char-asset-preview cb5-preview"><img src="${escHtml(assetImage(detail.id, selectedVar, revision))}" alt=""></div>`
      + `<div class="char-asset-var-strip">${strip}</div>`
      + `<div class="char-asset-var-actions">`
      + (selectedVar ? `<button type="button" class="mod-btn-sm mod-btn-danger" data-cb-act="var-delete">`
        + `${armed ? '한 번 더 클릭하면 삭제' : '바리에이션 삭제'}</button>` : '')
      + `<button type="button" class="mod-btn-sm char-asset-bench-btn" data-cb-act="var-new"`
      + ` title="이 그림을 원본으로 놓고 일부만 다시 그립니다">+ 바리에이션 추가</button></div>`
      + `<div class="cb5-annot">`
      + `<input type="text" class="cb5-annot-name" data-cb-field="name" maxlength="80" autocomplete="off"`
      + ` value="${escHtml(nameValue)}" placeholder="${entry ? '이 그림의 이름' : '캐릭터 이름'}">`
      + (SHOW_DETAIL_DESCRIPTION
        ? `<textarea class="cb5-annot-desc" data-cb-field="description" maxlength="4000" rows="3"`
          + ` placeholder="${entry ? '이 그림의 설명' : '캐릭터 설명'} (자유롭게 적어 둡니다)">${escHtml(descValue)}</textarea>`
        : '')
      + `</div>`
      + (SHOW_DETAIL_COMPOSITION ? compositionHtml(compositionOf(selectedVar)) : '')
      + promptHtml(selectedVar)
      + `<div class="char-asset-apply-actions">`
      + `<button type="button" class="mod-btn-sm mod-btn-encode" data-cb-act="apply-c1"${applyOff}`
      + ` data-naia-title="C1 에 넣습니다. 쓰던 캐릭터 프롬프트는 한 칸씩 밀려 꺼집니다">C1 적용 (단독)</button>`
      + `<button type="button" class="mod-btn-sm mod-btn-encode" data-cb-act="apply-c1-inset"${applyOff}`
      + ` data-naia-title="C1 에 넣고 이 그림을 레퍼런스 인셋으로 고정합니다 - 켜져 있던 Character Reference 는 꺼집니다">`
      + `C1 + 레퍼런스 인셋 적용</button></div>`;
  }

  function galleryHtml() {
    const cards = store.map(item =>
      `<button type="button" class="char-asset-card${item.id === selectedId ? ' selected' : ''}"`
      + ` data-cb-char="${escHtml(item.id)}">`
      + `<img class="char-asset-card-img" loading="lazy" src="${escHtml(assetThumb(item.id, '', item.revision))}" alt="">`
      + `<span class="char-asset-card-name">${escHtml(storeName(item))}</span>`
      + `<span class="char-asset-card-count">${item.variation_count ? `+${item.variation_count}` : ''}</span></button>`).join('');
    return `<div class="char-asset-shell cb5-gal"><div class="char-asset-columns">`
      + `<section class="char-asset-gallery">`
      + `<div class="char-asset-toolbar">`
      + `<button type="button" class="mod-btn-sm char-asset-create-btn" data-cb-act="new">+ 캐릭터 생성</button>`
      + `<button type="button" class="mod-btn-sm" data-cb-act="refresh" aria-label="새로 읽기">↻</button>`
      + `<span class="char-asset-count">${store.length} characters</span></div>`
      + `<div class="char-asset-grid">${cards
        || '<div class="mod-empty">신 사양으로 만든 캐릭터가 없습니다. [+ 캐릭터 생성] 으로 시작합니다.<br>'
          + '구 사양 캐릭터는 [구 사양 · V4.5] 탭의 [신 사양으로 이전] 으로 가져옵니다.</div>'}</div>`
      + `</section><section class="char-asset-detail" data-cb-role="detail">${detailHtml()}</section>`
      + `</div></div>`;
  }

  function renderDetail() {
    const host = rightMount.querySelector('[data-cb-role="detail"]');
    if (!host) return;
    // 이름 · 설명을 치는 중이면 다시 그리지 않는다 - 치던 글자와 초점이 날아간다.
    if (host.contains(document.activeElement) && document.activeElement?.dataset?.cbField) return;
    const top = host.scrollTop;
    host.innerHTML = detailHtml();
    host.scrollTop = top;
  }

  // ------------------------------------------------------------------ 그리기 - 오른쪽 창

  function builderShellHtml() {
    const title = view === 'variation' ? `${escHtml(work?.name || '')} · 바리에이션 만들기` : '새 캐릭터';
    // 시험 그림 칸(.cb5-side)은 **맨 위부터** 선다(사용자 지시 2026-10-11 - 그림 볼 자리가 모자랐다). 그래서 [← 목록] 줄을
    // 왼쪽 기둥(.cb5-col) 안으로 넣었다. 사양 탭 줄의 오른쪽 빈 자리까지 올라가는 것은 CSS 가 한다(`body.assets-v5-mode`).
    return `<div class="cb5-win${view === 'variation' ? ' is-ab' : ''}">`
      + `<div class="cb5-col">`
      + `<div class="cb5-bar"><button type="button" class="cb5-btn" data-cb-act="back">← 목록</button>`
      + `<span class="cb5-bar-title">${title}</span></div>`
      + `<section class="cb5-main" data-cb-role="main">`
      + `<input type="text" class="cb5-search" data-cb-role="search" autocomplete="off" spellcheck="false"`
      + ` placeholder="부품 검색 · twintails, 땋은 머리">`
      + `<div class="cb5-main-title" data-cb-role="main-title"></div>`
      + `<div class="cb5-browse"><div class="cb5-main-scroll"></div>`
      + `<nav class="cb5-parts" data-cb-role="parts" aria-label="소분류"></nav></div></section></div>`
      + `<aside class="cb5-side" data-cb-role="side"></aside></div>`;
  }

  function renderRight() {
    if (!catalog || !spec) {
      builtView = '';
      rightMount.innerHTML = `<div class="cb5-empty">${escHtml(loadError
        ? `부품 목록을 불러오지 못했습니다: ${loadError}` : '부품 목록을 불러오는 중...')}</div>`;
      return;
    }
    if (view === 'gallery') {
      builtView = 'gallery';
      rightMount.innerHTML = galleryHtml();
      return;
    }
    // 뼈대는 화면이 바뀔 때만 세운다 - 검색칸을 다시 그리면 치던 글자와 초점이 날아간다.
    const key = `${view}:${work?.id || ''}:${work?.source || ''}`;
    if (builtView !== key) {
      builtView = key;
      rightMount.innerHTML = builderShellHtml();
      rightMount.querySelector('[data-cb-role="search"]').value = query;
    }
    renderMain();
    renderSide();
  }

  function renderAll() {
    renderLeft();
    renderRight();
  }

  /** 화면을 바꾼다. 덮개(왼쪽 블록 줄)는 제작 · 바리에이션에서만 올라온다 - 바뀌면 바깥(app.js)에 알린다. */
  function setView(next) {
    view = next;
    query = '';
    deleteArmed = '';
    leftMount.hidden = !(active && view !== 'gallery');
    onViewChange();
    renderAll();
  }

  // ------------------------------------------------------------------ 조작 - 부품

  function toggleTag(tag) {
    const info = tagInfo.get(tag);
    if (!info) return;
    let list = draft.parts[info.block];
    if (list.some(item => barePart(item) === tag)) {
      list = list.filter(item => barePart(item) !== tag);     // 가중치를 건 것도 같은 부품이다
    } else {
      // 색 · 단계는 하나만 고른다 - 같은 부품의 먼저 고른 것을 밀어낸다(직접 쓴 것은 건드리지 않는다).
      if (info.part.kind !== 'thumb') list = list.filter(item => tagInfo.get(barePart(item))?.part !== info.part);
      list = [...list, tag];
    }
    draft.parts[info.block] = list;
    saveDraft();
    renderLeft();
    renderMain();
  }

  function setActiveBlock(key, {focus = false} = {}) {
    if (!blockDef.has(key)) return;
    if (key === activeBlock) {
      if (focus) focusSlotInput();
      return;
    }
    // '기타' 를 떠날 때 거기 쓴 부품을 제 블록으로 옮긴다. 치는 동안에는 옮기지 않는다 - 친 글이 눈앞에서 사라진다.
    if (activeBlock === ETC_BLOCK) announceSorted(sortEtcBlock());
    activeBlock = key;
    // 블록을 고르면 검색을 걷는다 - 검색 결과가 그리드를 덮고 있으면 눌러도 아무 일이 없어 보인다.
    if (query) {
      query = '';
      const input = rightMount.querySelector('[data-cb-role="search"]');
      if (input) input.value = '';
    }
    renderLeft();
    renderMain();
    const scroller = rightMount.querySelector('.cb5-main-scroll');
    if (scroller) scroller.scrollTop = 0;
    if (focus) focusSlotInput();
  }

  function announceSorted(moved) {
    if (moved) showToast('기타에 쓴 것 가운데 색인된 부품을 제 블록으로 옮겼습니다', 'info');
  }

  /** 못 쓰는 글자가 든 부품(없으면 ''). 서버가 400 으로 돌려보내기 전에 먼저 말한다. */
  function invalidPart() {
    for (const key of BLOCK_ORDER) {
      for (const item of draft.parts[key]) {
        if (FREE_TEXT_FORBIDDEN.test(item) || item.length > FREE_TEXT_MAX) return item;
      }
    }
    return '';
  }

  /** 네거티브에 가중치(`::`)를 쓴 항목(없으면 ''). 통째로 `-1:: ... ::` 로 묶이므로 안에 또 쓰면 묶음이 깨진다. */
  function weightedNegative() {
    return draft.parts[NEGATIVE_BLOCK].find(item => item.includes('::')) || '';
  }

  async function confirmDialog(title, message, okText) {
    if (typeof showAppDialog !== 'function') return false;
    return showAppDialog('', {
      title, messageHtml: escHtml(message), okText, cancelText: '취소',
    });
  }

  async function clearDraft() {
    if (!totalParts()) return;
    if (!await confirmDialog('캐릭터 제작', '고른 부품을 모두 비웁니다.', '비우기')) return;
    const keep = {gender: draft.gender, resolution: draft.resolution};
    draft = {...emptyDraft(), ...keep};
    saveDraft();
    renderAll();
  }

  // ------------------------------------------------------------------ 조작 - 화면 사이

  function openCreate() {
    // 제작 화면의 초안은 이 브라우저에 남아 있다. 바리에이션을 만들다 온 경우에도 그 초안으로 돌아간다.
    draft = emptyDraft();
    restoreDraft();
    setView('create');
  }

  /** 고른 그림을 원본 A 로 놓고 바리에이션 화면을 연다. 왼쪽 블록 줄에는 그 그림의 부품 구성이 실린다. */
  function openVariation() {
    if (!detail || detail.id !== selectedId) return;
    const entry = selectedVar ? variationEntry(selectedVar) : null;
    const builder = compositionOf(selectedVar);
    if (!builder) {
      showToast('이 캐릭터에는 부품 구성이 없습니다', 'error');
      return;
    }
    const width = entry ? entry.width : detail.width;
    const height = entry ? entry.height : detail.height;
    if (!width || !height || width % 64 || height % 64) {
      showToast('이 그림은 크기가 맞지 않아 바리에이션을 만들 수 없습니다 (가로 · 세로가 64 의 배수여야 합니다)', 'error');
      return;
    }
    const sameTarget = work && work.id === detail.id && work.source === selectedVar;
    if (!sameTarget) {
      candidateSets.variation = [];
      pickedCandidate.variation = null;
    }
    work = {
      id: detail.id, name: storeName(detail), source: selectedVar,
      width, height, paid: !!(entry ? entry.paid : detail.paid),
      revision: entry ? entry.revision : detail.revision,
      // 띠는 그 그림을 만들 때 쓴 것이 있으면 그것부터, 없으면 가슴 아래 전체(의상 교체의 흔한 자리).
      band: sameTarget ? work.band : {...(builder.band || {start: 0.3, end: 1})},
    };
    applyBuilder(builder);
    if (!totalParts()) {
      // 구 사양에서 옮겨 온 캐릭터에는 부품 구성이 없다. 그 그림의 캐릭터 프롬프트를 블록으로 갈라 싣는다 -
      // 줄이 전부 빈 채로 열리면 바꿀 것(의상 등)을 처음부터 다시 적어야 한다.
      const text = promptOf(selectedVar)?.prompt || detail.character_prompt || '';
      const sorted = classifyParts(text);
      draft.parts = sorted.parts;
      if (sorted.gender) draft.gender = sorted.gender;
    }
    setView('variation');
  }

  function backToGallery() {
    setView('gallery');
    void loadStore();
  }

  // ------------------------------------------------------------------ 시험 생성

  function dropOldCandidates(list, keep) {
    while (list.length > CANDIDATE_MAX) {
      // 고른 것과 아직 오고 있는 것은 버리지 않는다.
      const index = list.map((item, i) => [item, i]).reverse()
        .find(([item]) => item !== keep && item.status !== 'pending')?.[1];
      if (index === undefined) break;
      list.splice(index, 1);
    }
  }

  /** 메인 Generate 단추가 이 모드에서 부르는 문. 처리했으면 true(= 일반 생성으로 넘기지 마라).
   *  선택 화면에서는 false 다 - 거기서는 메인 프롬프트가 그대로 보이고 Generate 도 평소대로다. */
  function generate() {
    if (!active || view === 'gallery') return false;
    if (!catalog || !spec) {
      showToast('부품 목록을 아직 불러오지 못했습니다', 'error');
      return true;
    }
    if (!isNai()) {
      showToast('캐릭터 제작은 NAI 모드 전용입니다', 'error');
      return true;
    }
    if (!positiveParts()) {
      showToast('부품을 하나 이상 골라 주세요', 'error');
      return true;
    }
    const weighted = weightedNegative();
    if (weighted) {
      showToast(`네거티브에는 가중치(::)를 쓰지 않습니다 - 통째로 -1:: 로 묶입니다: ${weighted.slice(0, 40)}`, 'error');
      return true;
    }
    // '기타' 를 열어 둔 채 Generate 를 누르면 아직 안 갈린 채다 - 나가기 전에 가른다(프롬프트의 블록 차례가 달라진다).
    if (sortEtcBlock()) {
      renderLeft();
      renderMain();
    }
    const bad = invalidPart();
    if (bad) {
      showToast(bad.length > FREE_TEXT_MAX
        ? `너무 긴 항목이 있습니다 (${FREE_TEXT_MAX}자까지): ${bad.slice(0, 30)}...`
        : `쓸 수 없는 글자가 있습니다: ${bad.slice(0, 40)}  ( < > | # $ \` \\ " __ 는 못 씁니다 )`, 'error');
      return true;
    }
    const forView = view;
    const builder = builderPayload();
    const candidate = {
      requestId: newRequestId(), status: 'pending', historyId: '', seed: null, message: '',
      saved: false,
      // 투명 배경인가. null = 아직 모른다(확인 중) · false = 투명하다 · true = 투명하지 않다(다시 생성해야 한다).
      opaque: null,
      // 저장할 때는 **이 그림을 만든 구성**을 싣는다 - 그 뒤에 고친 초안이 아니라.
      builder,
      view: forView,
      target: forView === 'variation' ? {id: work.id, source: work.source, band: {...work.band}} : null,
    };
    const list = candidateSets[forView];
    list.unshift(candidate);
    if (!pickedCandidate[forView] || pickedCandidate[forView].status !== 'done') pickedCandidate[forView] = candidate;
    dropOldCandidates(list, pickedCandidate[forView]);
    renderSide();
    const common = {
      request_id: candidate.requestId, count: 1,
      gender: builder.gender, parts: builder.parts, pose_slot: builder.pose_slot,
    };
    const request = forView === 'variation'
      ? postJson('/api/character-asset/v5/variation/generate', {
        ...common, id: work.id, source: work.source, band: candidate.target.band, seed: null,
      })
      : postJson('/api/character-asset/v5/generate', {
        ...common, resolution: builder.resolution,
        seed: seedLock && Number.isFinite(lockedSeed) ? lockedSeed : null,
      });
    request.then(result => {
      if (result?.ok && (result.accepted || []).length) return;
      const reason = (result?.rejected || [])[0];
      failCandidate(candidate, reason?.message || reason?.error || '요청이 받아들여지지 않았습니다');
    }).catch(error => failCandidate(candidate, String(error?.message || error)));
    return true;
  }

  function findCandidate(requestId) {
    for (const key of Object.keys(candidateSets)) {
      const hit = candidateSets[key].find(item => item.requestId === requestId);
      if (hit) return hit;
    }
    return null;
  }

  function failCandidate(candidate, message) {
    if (candidate.status === 'done') return;
    candidate.status = 'error';
    candidate.message = message;
    showToast(`시험 생성 실패: ${message}`, 'error');
    if (candidate.view === view) renderSide();
  }

  function handleResultMeta(meta) {
    const flow = meta?.character_asset_flow;
    if (flow !== 'builder_v5' && flow !== 'builder_v5_variation') return;
    const candidate = findCandidate(String(meta.character_asset_request_id || ''));
    if (!candidate || candidate.status === 'done') return;
    candidate.status = 'done';
    candidate.historyId = String(meta.history_id || '');
    const seed = Number(meta.seed);
    candidate.seed = Number.isFinite(seed) && seed > 0 ? seed : null;
    candidate.builder.seed = candidate.seed;
    // 새 그림이 오면 **그 그림으로 넘긴다**(사용자 지시 2026-10-11). 예전에는 보던 그림을 그대로 두어서, 새 그림은
    // 후보 줄 맨 앞에 조용히 끼고 보던 것만 옆으로 밀려났다 - 방금 만든 것을 보려면 매번 눌러야 했다.
    pickedCandidate[candidate.view] = candidate;
    if (candidate.view === view) renderSide();
    void checkTransparency(candidate);
  }

  /** 신 사양의 그림은 투명 배경이어야 한다. 아니면 경고한다(다시 생성해야 한다). 저장은 막지 않는다. */
  async function checkTransparency(candidate) {
    try {
      const report = await getJson(
        `/api/character-asset/v5/candidate-check?history_id=${encodeURIComponent(candidate.historyId)}`);
      candidate.opaque = !report.ok;
    } catch (error) {
      // 확인을 못 했으면 투명하다고 치지 않는다. 어디에 저장되는지는 서버가 같은 판정으로 정한다.
      candidate.opaque = true;
      showToast(`투명 배경 확인 실패: ${error.message}`, 'error');
    }
    if (candidate.opaque) {
      showToast(candidate.view === 'variation'
        ? '투명 배경이 아닌 그림이 나왔습니다 - 다시 생성해 주세요'
        : '투명 배경이 아닌 그림이 나왔습니다 - 다시 생성해 주세요 (저장하면 V4.5 구 사양으로 저장됩니다)', 'error');
    }
    if (candidate.view === view) renderSide();
  }

  function handleGenerationError(message) {
    const candidate = findCandidate(String(message?.requestId || ''));
    if (candidate) failCandidate(candidate, String(message?.message || '생성하지 못했습니다'));
  }

  // ------------------------------------------------------------------ 저장

  async function askName(title, hint) {
    if (typeof showPromptDialog !== 'function') return '';
    const typed = await showPromptDialog(hint, {title, okText: '저장', cancelText: '취소', defaultValue: ''});
    return typed === null ? null : String(typed || '').trim();
  }

  async function saveSelected() {
    const candidate = picked();
    if (!candidate || candidate.status !== 'done' || candidate.saved || saving) return;
    const isVariation = candidate.view === 'variation';
    const name = await askName(isVariation ? '바리에이션으로 저장' : '에셋으로 저장',
      isVariation ? '이 그림의 이름을 적어 주세요 (예: 교복 · 누드). 비워 두고 나중에 붙여도 됩니다.'
        : '캐릭터 이름을 적어 주세요. 비워 두고 나중에 붙여도 됩니다.');
    if (name === null) return;
    saving = true;
    renderSide();
    try {
      const target = isVariation
        ? {kind: 'variation', character_id: candidate.target.id, builder: candidate.builder,
          band: candidate.target.band, source: candidate.target.source, name}
        : {kind: 'new', builder: candidate.builder, name};
      const result = await postJson('/api/character-asset/save', {
        source: {kind: 'history', history_id: candidate.historyId}, target,
      });
      candidate.saved = true;
      if (isVariation) {
        showToast(result?.transparent === false
          ? '바리에이션으로 저장했습니다 (투명 배경이 아닙니다)' : '바리에이션으로 저장했습니다', 'success');
        // 선택 화면으로 돌아갔을 때 새 그림이 골라져 있게 한다.
        selectedId = candidate.target.id;
        selectedVar = String(result?.variation || '');
        detail = null;
      } else if (result?.spec === 'v5') {
        showToast('새 캐릭터로 저장했습니다', 'success');
        selectedId = String(result?.character_id || '');
        selectedVar = '';
        detail = null;
      } else {
        // 서버가 구 사양으로 돌렸다(투명 배경이 아니다). 신 사양 목록에는 안 뜬다 - 구 사양 탭에 있다.
        showToast('투명 배경이 아니어서 V4.5 구 사양으로 저장했습니다 (구 사양 탭에 있습니다)', 'success');
      }
    } catch (error) {
      showToast(`저장 실패: ${error.message}`, 'error');
    } finally {
      saving = false;
      renderSide();
    }
  }

  // ------------------------------------------------------------------ 선택 화면의 일

  async function loadStore() {
    const seq = ++storeSeq;
    try {
      const data = await getJson('/api/character-asset/list');
      if (seq !== storeSeq) return;       // 더 새로운 요청이 있다
      store = (data.characters || []).filter(item => item && item.spec === 'v5');
    } catch (error) {
      if (seq !== storeSeq) return;
      store = [];
      showToast(`캐릭터 목록을 불러오지 못했습니다: ${error.message}`, 'error');
    }
    if (selectedId && !store.some(item => item.id === selectedId)) {
      selectedId = '';
      selectedVar = '';
      detail = null;
    }
    if (view === 'gallery') renderRight();
    if (selectedId && (!detail || detail.id !== selectedId)) void loadDetail();
  }

  async function loadDetail() {
    const id = selectedId;
    if (!id) return;
    const seq = ++detailSeq;
    try {
      const data = await getJson(`/api/character-asset/detail?id=${encodeURIComponent(id)}`);
      if (seq !== detailSeq || id !== selectedId) return;     // 그사이 다른 캐릭터를 골랐다
      detail = data;
      imagePrompts.clear();
      if (selectedVar && !variationEntry(selectedVar)) selectedVar = '';
      if (selectedVar) void loadImagePrompt(selectedVar);
    } catch (error) {
      if (seq !== detailSeq) return;
      detail = null;
      showToast(`불러오지 못했습니다: ${error.message}`, 'error');
    }
    if (view === 'gallery') renderDetail();
  }

  /** 고른 바리에이션의 캐릭터 프롬프트를 받는다(상세 라우트가 `variation` 으로 그 그림의 것을 준다). */
  async function loadImagePrompt(hash) {
    const id = selectedId;
    if (!id || !hash || imagePrompts.has(hash)) return;
    try {
      const data = await getJson(`/api/character-asset/detail?id=${encodeURIComponent(id)}`
        + `&variation=${encodeURIComponent(hash)}`);
      if (id !== selectedId || !detail || detail.id !== id) return;
      imagePrompts.set(hash, {
        prompt: String(data.character_prompt || ''), uc: String(data.character_uc || ''), recovered: !!data.recovered,
      });
    } catch (error) {
      if (id !== selectedId) return;
      imagePrompts.set(hash, {prompt: '', uc: '', recovered: false});
    }
    if (view === 'gallery' && selectedVar === hash) renderDetail();
  }

  function selectCharacter(id) {
    if (id === selectedId && detail?.id === id) return;
    selectedId = id;
    selectedVar = '';
    detail = null;
    deleteArmed = '';
    renderRight();
    void loadDetail();
  }

  /** 이름 · 설명을 적는다. 칸을 떠날 때(change) 한 번 보낸다 - 대표의 것은 캐릭터의 이름 · 설명이다. */
  async function annotate(field, value) {
    if (!detail) return;
    const id = detail.id;
    const variation = selectedVar;
    try {
      const result = await postJson('/api/character-asset/v5/annotate', {id, variation, [field]: value});
      if (detail?.id !== id) return;
      if (variation) {
        const entry = variationEntry(variation);
        if (entry) { entry.name = result.name; entry.description = result.description; }
      } else {
        detail.display_name = result.name;
        detail.description = result.description;
        const row = store.find(item => item.id === id);
        if (row) row.display_name = result.name;
        // 목록의 카드 이름과 머리줄만 고친다 - 통째로 다시 그리면 다음 칸으로 옮긴 초점이 날아간다.
        const card = rightMount.querySelector(`[data-cb-char="${CSS.escape(id)}"] .char-asset-card-name`);
        if (card) card.textContent = storeName(detail);
        const head = rightMount.querySelector('.char-asset-detail-name');
        if (head) head.textContent = storeName(detail);
      }
    } catch (error) {
      showToast(`적어 두지 못했습니다: ${error.message}`, 'error');
    }
  }

  async function applyC1(withInset = false) {
    if (!detail) return;
    if (!isNai()) {
      showToast('캐릭터 슬롯 적용은 NAI 모드 전용입니다', 'error');
      return;
    }
    try {
      const result = await postJson('/api/character-asset/apply', {
        id: detail.id, variation: selectedVar, mode: 'c1', with_inset: withInset, strip_outfit: stripOutfit(),
      });
      if (withInset) {
        showToast('C1 에 적용하고 레퍼런스 인셋으로 고정했습니다 - 해제 전까지 인셋으로 생성됩니다', 'success');
        if (result?.reference_inset) onReferenceInsetPin(result.reference_inset);
      } else {
        showToast('C1 에 적용했습니다', 'success');
      }
    } catch (error) {
      showToast(`적용 실패: ${error.message}`, 'error');
    }
  }

  /** 저장하기 전의 시험 그림을 바로 써 본다 - 그 그림을 만든 글을 C1 에, 그림을 레퍼런스 인셋에. */
  async function applyCandidate() {
    const candidate = picked();
    if (!candidate || candidate.status !== 'done' || !candidate.historyId || applying) return;
    if (!isNai()) {
      showToast('캐릭터 슬롯 적용은 NAI 모드 전용입니다', 'error');
      return;
    }
    applying = true;
    renderSide();
    try {
      const result = await postJson('/api/character-asset/v5/candidate/apply', {
        history_id: candidate.historyId, builder: candidate.builder, with_inset: true,
      });
      showToast('C1 에 적용하고 레퍼런스 인셋으로 고정했습니다 - 해제 전까지 인셋으로 생성됩니다', 'success');
      if (result?.reference_inset) onReferenceInsetPin(result.reference_inset);
    } catch (error) {
      showToast(`적용 실패: ${error.message}`, 'error');
    } finally {
      applying = false;
      renderSide();
    }
  }

  /** 지우기는 두 번 눌러야 한다(구 사양 화면과 같은 방식) - 한 번 누르면 단추 글이 바뀐다. */
  async function armedDelete(key, run) {
    if (deleteArmed !== key) {
      deleteArmed = key;
      renderDetail();
      return;
    }
    deleteArmed = '';
    try {
      await run();
    } catch (error) {
      showToast(`삭제 실패: ${error.message}`, 'error');
      renderDetail();
    }
  }

  function deleteVariation() {
    if (!detail || !selectedVar) return;
    const id = detail.id;
    const hash = selectedVar;
    void armedDelete(`var:${hash}`, async () => {
      await postJson('/api/character-asset/delete-variation', {id, hash});
      showToast('바리에이션을 지웠습니다', 'success');
      selectedVar = '';
      detail = null;
      await loadStore();
    });
  }

  function deleteCharacter() {
    if (!detail) return;
    const id = detail.id;
    void armedDelete(`char:${id}`, async () => {
      await postJson('/api/character-asset/delete', {id});
      showToast('캐릭터를 지웠습니다', 'success');
      if (work?.id === id) work = null;
      selectedId = '';
      selectedVar = '';
      detail = null;
      await loadStore();
    });
  }

  // ------------------------------------------------------------------ 띠(시작 : 종료)

  /** 시작 · 종료 선을 그림 위에서 끈다. 끄는 동안에는 선과 띠만 옮긴다(다시 그리지 않는다). */
  function beginBandDrag(event, edge) {
    const stage = rightMount.querySelector('[data-cb-role="band-stage"]');
    if (!stage || !work) return;
    event.preventDefault();
    const line = event.target.closest('[data-cb-edge]');
    line.setPointerCapture?.(event.pointerId);
    const move = moveEvent => {
      const rect = stage.getBoundingClientRect();
      if (!rect.height) return;
      const ratio = Math.round(Math.min(1, Math.max(0, (moveEvent.clientY - rect.top) / rect.height)) * 100) / 100;
      // 띠는 그림 높이의 5% 이상이어야 한다(서버의 문턱과 같다).
      if (edge === 'start') work.band.start = Math.min(ratio, Math.round((work.band.end - BAND_MIN) * 100) / 100);
      else work.band.end = Math.max(ratio, Math.round((work.band.start + BAND_MIN) * 100) / 100);
      const start = Math.round(work.band.start * 100);
      const end = Math.round(work.band.end * 100);
      stage.querySelector('[data-cb-edge="start"]').style.top = `${start}%`;
      stage.querySelector('[data-cb-edge="end"]').style.top = `${end}%`;
      const band = stage.querySelector('[data-cb-role="band"]');
      band.style.top = `${start}%`;
      band.style.height = `${end - start}%`;
      const text = rightMount.querySelector('[data-cb-role="band-text"]');
      if (text) text.textContent = `다시 그릴 곳 ${start}% ~ ${end}%`;
    };
    const stop = () => {
      line.removeEventListener('pointermove', move);
      line.removeEventListener('pointerup', stop);
      line.removeEventListener('pointercancel', stop);
    };
    line.addEventListener('pointermove', move);
    line.addEventListener('pointerup', stop);
    line.addEventListener('pointercancel', stop);
  }

  // ------------------------------------------------------------------ 이벤트

  function onClick(event) {
    const toggle = event.target.closest('[data-cb-toggle]');
    if (toggle) {
      event.stopPropagation();
      toggleTag(toggle.dataset.cbToggle);
      return;
    }
    const gender = event.target.closest('[data-cb-gender]');
    if (gender) {
      draft.gender = gender.dataset.cbGender;
      saveDraft();
      renderLeft();
      return;
    }
    const res = event.target.closest('[data-cb-res]');
    if (res) {
      draft.resolution = res.dataset.cbRes;
      saveDraft();
      renderSide();
      return;
    }
    const part = event.target.closest('[data-cb-part]');
    if (part) {
      activePart.set(activeBlock, part.dataset.cbPart);
      // 소분류를 누르면 검색을 걷는다 - 검색 결과가 그리드를 덮고 있으면 눌러도 아무 일이 없어 보인다.
      if (query) {
        query = '';
        const input = rightMount.querySelector('[data-cb-role="search"]');
        if (input) input.value = '';
      }
      renderMain();
      const scroller = rightMount.querySelector('.cb5-main-scroll');
      if (scroller) scroller.scrollTop = 0;
      return;
    }
    const cand = event.target.closest('[data-cb-cand]');
    if (cand) {
      pickedCandidate[view] = cands()[Number(cand.dataset.cbCand)] || picked();
      renderSide();
      return;
    }
    const character = event.target.closest('[data-cb-char]');
    if (character) {
      selectCharacter(character.dataset.cbChar);
      return;
    }
    const variation = event.target.closest('[data-cb-var]');
    if (variation) {
      selectedVar = variation.dataset.cbVar;
      deleteArmed = '';
      if (selectedVar) void loadImagePrompt(selectedVar);
      // 고른 그림이 바뀌면 이름 · 설명 칸도 그 그림의 것으로 바뀌어야 한다 - 치던 칸에서 초점을 뗀 뒤 그린다.
      if (document.activeElement?.dataset?.cbField) document.activeElement.blur();
      renderDetail();
      return;
    }
    const act = event.target.closest('[data-cb-act]');
    if (act && !act.disabled) {
      const name = act.dataset.cbAct;
      if (name === 'clear') void clearDraft();
      else if (name === 'save') void saveSelected();
      else if (name === 'cand-apply') void applyCandidate();
      else if (name === 'new') openCreate();
      else if (name === 'refresh') void loadStore();
      else if (name === 'back') backToGallery();
      else if (name === 'var-new') openVariation();
      else if (name === 'var-delete') deleteVariation();
      else if (name === 'char-delete') deleteCharacter();
      else if (name === 'apply-c1') void applyC1();
      else if (name === 'apply-c1-inset') void applyC1(true);
      return;
    }
    const chipDel = event.target.closest('[data-cb-chip-del]');
    if (chipDel) {
      const key = chipDel.dataset.cbChipBlock;
      const index = Number(chipDel.dataset.cbChipDel);
      if (draft.parts[key]) {
        draft.parts[key] = draft.parts[key].filter((_item, at) => at !== index);
        saveDraft();
        renderLeft();
        renderMain();
      }
      return;
    }
    if (event.target.closest('[data-cb-slot-input]')) return;      // 입력 칸 안의 클릭은 그대로 둔다
    const row = event.target.closest('[data-cb-block]');
    if (row) setActiveBlock(row.dataset.cbBlock, {focus: true});
  }

  /** 열린 줄의 입력 칸: 친 글이 곧 그 블록의 부품 목록이다. 치는 동안 왼쪽은 다시 그리지 않는다(커서가 날아간다). */
  let slotRenderTimer = null;
  function onLeftInput(event) {
    const input = event.target.closest('[data-cb-slot-input]');
    if (!input) return;
    const key = input.dataset.cbSlotInput;
    if (!draft.parts[key]) return;
    draft.parts[key] = splitParts(input.value);
    saveDraft();
    autosizeSlotInput(input);
    const count = leftMount.querySelector(`[data-cb-count="${key}"]`);
    if (count) count.textContent = draft.parts[key].length || '';
    const clear = leftMount.querySelector('[data-cb-act="clear"]');
    if (clear) clear.disabled = !totalParts();
    // 그리드의 '선택됨' 표시가 친 글을 따라온다.
    clearTimeout(slotRenderTimer);
    slotRenderTimer = setTimeout(renderMain, 200);
  }

  function onLeftKeydown(event) {
    // 줄바꿈은 받지 않는다(쉼표가 구분자다) - Enter 는 입력을 마치고 칩으로 접는다.
    if (event.key !== 'Enter' || event.isComposing || !event.target.closest('[data-cb-slot-input]')) return;
    // 자동완성이 Enter 로 후보를 받았으면(그쪽이 먼저 듣고 기본 동작을 막는다) 여기서는 손대지 않는다.
    if (event.defaultPrevented) return;
    event.preventDefault();
    event.target.blur();
    if (activeBlock === ETC_BLOCK) {
      const moved = sortEtcBlock();
      if (moved) {
        announceSorted(moved);
        renderLeft();
        renderMain();
      }
    }
  }

  function onChange(event) {
    const field = event.target.closest('[data-cb-field]');
    if (field) {
      void annotate(field.dataset.cbField, field.value);
      return;
    }
    const strip = event.target.closest('[data-cb-role="strip-outfit"]');
    if (strip) {
      setStripOutfit(strip.checked);
      return;
    }
    const box = event.target.closest('[data-cb-role="seedlock"]');
    if (!box) return;
    const current = picked();
    seedLock = !!box.checked;
    lockedSeed = seedLock && Number.isFinite(current?.seed) ? current.seed : (seedLock ? lockedSeed : null);
    if (seedLock && !Number.isFinite(lockedSeed)) seedLock = false;
    renderSide();
  }

  function onInput(event) {
    const input = event.target.closest('[data-cb-role="search"]');
    if (!input) return;
    query = input.value;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      renderMain();
      const scroller = rightMount.querySelector('.cb5-main-scroll');
      if (scroller) scroller.scrollTop = 0;
    }, SEARCH_DELAY);
  }

  function onPointerDown(event) {
    const line = event.target.closest('[data-cb-edge]');
    if (line) {
      beginBandDrag(event, line.dataset.cbEdge);
      return;
    }
    const stage = event.target.closest('.cb5-stage[data-cb-zoom]');
    if (stage && event.button === 0) beginStageDrag(event, stage);
  }

  leftMount.addEventListener('click', onClick);
  for (const mount of [leftMount, rightMount]) {
    mount.addEventListener('pointerover', onTipOver);
    mount.addEventListener('pointerout', onTipOut);
    mount.addEventListener('pointerdown', hideTip);
  }
  leftMount.addEventListener('input', onLeftInput);
  leftMount.addEventListener('keydown', onLeftKeydown);
  rightMount.addEventListener('click', onClick);
  rightMount.addEventListener('change', onChange);
  rightMount.addEventListener('input', onInput);
  rightMount.addEventListener('pointerdown', onPointerDown);
  rightMount.addEventListener('wheel', onWheel, {passive: false});
  rightMount.addEventListener('dblclick', onDblClick);

  return {
    /** 신 사양 탭이 보이는가. 보일 때마다 캐릭터 목록을 새로 읽는다. 덮개는 `wantsCover()` 가 따로 말한다. */
    setActive(next) {
      next = !!next;
      if (next === active) return;
      active = next;
      leftMount.hidden = !(active && view !== 'gallery');
      if (!active) return;
      renderAll();
      void ensureLoaded().then(() => { if (active && catalog) void loadStore(); });
    },
    isActive: () => active,
    /** 왼쪽 메인 프롬프트 자리를 덮어야 하는가. 선택 화면(기본)에서는 덮지 않는다. */
    wantsCover: () => active && view !== 'gallery',
    generate,
    handleResultMeta,
    handleGenerationError,
  };
}
