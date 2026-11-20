// 프리셋 벤치(사용자 지시 2026-11-19 · 11-20 "사이즈상 메인 UI 로" - 떠 있는 창을 걷고 메인 화면에 싣는다).
//
//   ┌ 메인 왼쪽 열(#pbBlocks) ┐┌ 오른쪽 Presets 탭(#presetBenchRoot) ─────────────────┐
//   │ Presets 벤치 [← 프롬프트]││ 칸 이름 · 맥락 · [검색] [결과]                          │
//   │ 기반 요약 카드           ││ 대분류 | 소분류 · 시드 | 세트 카드(위에 결과 판이 뜬다) │
//   │ 넣을 곳 · 캐릭터 카드    ││                                                         │
//   │ [N장 생성 | 중지]        ││                                     [해상도 ▾] (떠 있음) │
//   └─────────────────────────┘└─────────────────────────────────────────────────────────┘
//
// - 덮개는 Assets 신 사양과 같은 방식이다: body.preset-bench-mode 가 메인 프롬프트 · 도구 줄 · 아래 조작줄을 가린다
//   (값은 건드리지 않는다 - 클래스를 떼면 원래 화면이 그대로). 탭을 떠나면 덮개가 걷힌다(app.js syncPresetBenchMode).
// - 인원은 고르지 않는다(사용자 11-20) - [+ 캐릭터 추가] / × 로 1 ~ 2명. 맨 앞 인원 태그(1girl · 1boy …)는
//   캐릭터 글로 서버에 물어 정한다(이름 사전 gender · 글의 girl/boy 태그 · 모르면 girl). 목록은 여성 · 남성 세트를 한데 보인다.
// - 카드 누르기 = 그 칸에 넣기 · 카드 오른쪽 위 상자 = 비교에 넣기. 한 칸에서 둘 이상 체크하면 그 칸이 '비교 축' 이다.
//   다른 칸에서 비교를 시작하면 앞 축은 풀리고 [되돌리기] 를 띄운다.
// - 기반 = 프리셋(기본 = 현재 프리셋 · **이 창에서만** 쓴다) | 직접 설정(이름 붙여 저장 · 프리셋에서 받아오기 · 프리셋으로 보내기).
//   메인 화면의 현재 프리셋 · 세션 설정은 바꾸지 않는다 - 기반 값은 요청마다 서버가 overrides 로 싣는다.
// - 조립 규칙(무엇을 메인 · 캐릭터 칸에 싣나)은 presetBenchModel.mjs 에 있다. 이 파일은 그리기 · 서버 왕복만 한다.
// - 결과는 일반 생성처럼 결과 화면 · 히스토리에도 간다. 이 창은 image_meta 의 preset_bench_* 표식으로 제 것을 알아본다.
// - 캐릭터 불러오기(사용자 11-20): 캐릭터 카드(머리 · 글 칸 - 누르거나 Tab 으로 들어오면)를 고르면 아래 고르기가
//   '캐릭터 N 고르기' + [캐릭터 검색 | 에셋 | 캐릭터 레퍼런스] 한 줄 + 그 아래 검색칸으로 바뀐다(의상 · 자세 줄과 같은 규칙).
//   캐릭터 검색은 Characters 창과 같다 - 같은 라우트 · 이름 · 한글 · 초성 · work: · 작품을 골라도 검색어는 남아 그 안에서 · ★.
//   DB = Characters 창의 캐릭터(옷 태그는 뺀다 - 의상 칸이 따로) · 에셋 = 캐릭터 프롬프트 + UC (+ 그 그림을 REF 로) ·
//   REF = 보관함 그림을 그 카드의 REF 줄에. REF 는 이 요청에만 실린다(세션 REF 창 · 목록은 안 바꾼다).
//   NAI 의 Character Reference 는 그림 한 장 전체에 걸린다 - 2명이면 경고만 하고 나누지 않는다. 한 번에 4장까지.
// - 해상도(사용자 11-20) = 결과 열 오른쪽 아래 드롭다운(1024² 묶음 7가지 · 기본 832 x 1216) - 기반의 크기 대신 늘 이것.
//   프롬프트 미리보기 줄 · 결과 머리 줄은 걷었다(자리를 그림에). Presets 는 Fn 메뉴에서 연다(탭 단추는 숨김).

import {
  MAX_CHARACTERS, normalizeCast, KIND_LABELS, LINK_POOLS, linkMismatch, slotsFor, buildItems, variantLabel, formatPosts,
} from './presetBenchModel.mjs?v=20261120-co1';

const STYLE_ID = 'pbw-style';
const STORE_KEY = 'naia.presetBench.state';
const API = {
  subject: text => `/api/presets/bench/subject?text=${encodeURIComponent(text)}`,
  catalog: (kind, pool) => `/api/presets/catalog?kind=${encodeURIComponent(kind)}&pool=${encodeURIComponent(pool)}`,
  sets: (kind, pool, seed) => `/api/presets/sets?kind=${encodeURIComponent(kind)}&pool=${encodeURIComponent(pool)}&seed=${encodeURIComponent(seed)}`,
  search: (q, kind) => `/api/presets/search?q=${encodeURIComponent(q)}&kind=${encodeURIComponent(kind)}`,
  related: (tag, pool, ctx) => `/api/presets/outfit-related?tag=${encodeURIComponent(tag)}&pool=${encodeURIComponent(pool)}&ctx=${encodeURIComponent(ctx)}`,
  thumb: key => `/api/presets/thumb/${encodeURIComponent(key)}`,
  thumbStatus: '/api/presets/thumb-pack/status',
  thumbDownload: '/api/install-manager/preset-thumbs/download',
  bases: '/api/presets/bench/bases',
  direct: '/api/presets/bench/direct',
  directOne: name => `/api/presets/bench/direct/${encodeURIComponent(name)}`,
  directExport: '/api/presets/bench/direct/export',
  generate: '/api/presets/bench/generate',
  queueAction: '/api/queue/action',
  historyThumb: id => `/api/history/thumb/${encodeURIComponent(id)}?size=320`,
  historyImage: id => `/api/history/image/${encodeURIComponent(id)}`,
  // 캐릭터 불러오기 - Characters 창 · Assets V5 · REF 창의 라우트를 그대로(읽기만).
  dbGroups: gender => `/api/character-viewer/groups?offset=0&limit=5000${gender ? `&gender=${encodeURIComponent(gender)}` : ''}`,
  // Characters 창(characterWindow listParams)과 같은 꼴 - group · query(이름 · 한글 · 초성 · work:) · gender · favorites_only.
  dbList: (group, q, gender, fav) => {
    const p = new URLSearchParams({offset: '0', limit: String(DB_LIST_LIMIT)});
    if (group && group !== '__ALL__') p.set('group', group);
    if (q) p.set('query', q);
    if (fav) p.set('favorites_only', 'true');
    if (gender) p.append('gender', gender);
    return `/api/character-viewer/list?${p}`;
  },
  dbCharacter: (group, character, variant) => `/api/presets/bench/db-character?${new URLSearchParams({group, character, variant})}`,
  assetList: '/api/character-asset/list',
  assetDetail: (id, variation) => `/api/character-asset/detail?${new URLSearchParams({id, variation})}`,
  assetThumb: (id, variation, rev) => `/api/character-asset/thumb?${new URLSearchParams({id, variation, size: 'grid', v: String(rev || '')})}`,
  refLibrary: (filter, categoryId, q) => {
    const p = new URLSearchParams({kind: 'character_reference', sort: 'recent', offset: '0', limit: '200', filter});
    if (filter === 'category' && categoryId) p.set('category_id', categoryId);
    if (q) p.set('q', q);
    return `/api/ref-vibe/library?${p}`;
  },
};
const DB_LIST_LIMIT = 300;
// 벤치 해상도 = 메인과 분리된 사양(사용자 11-20) - 1024² 묶음 + 768 x 1344(세로만). 서버 BENCH_SIZES 와 짝.
const BENCH_SIZES = ['1024 x 1024', '960 x 1088', '896 x 1152', '832 x 1216', '768 x 1344', '1088 x 960', '1152 x 896', '1216 x 832'];
const DEFAULT_SIZE = '832 x 1216';
const MAX_REFS = 4;
const REF_TYPES = ['character&style', 'character', 'style'];
const REF_TYPE_SHORT = {'character&style': 'C&S', character: 'C', style: 'S'};
// 에셋 그림을 REF 로 붙일 때 - Assets V5 변형 벤치와 같은 기본값.
const ASSET_REF_DEFAULT = {reference_type: 'character&style', strength: 0.8, fidelity: 0.9};
const GROUP_ETC = '__ETC__';

function cleanRef(raw) {
  if (!raw || typeof raw !== 'object' || !['storage', 'asset'].includes(raw.source)) return null;
  if (raw.source === 'storage' ? !raw.file_hash : !raw.id) return null;
  const unit = (v, d) => (Number.isFinite(Number(v)) ? Math.min(1, Math.max(0, Number(v))) : d);
  return {
    source: raw.source, file_hash: String(raw.file_hash || ''), id: String(raw.id || ''), variation: String(raw.variation || ''),
    label: String(raw.label || ''), thumb: String(raw.thumb || ''),
    reference_type: REF_TYPES.includes(raw.reference_type) ? raw.reference_type : 'character&style',
    strength: unit(raw.strength, 1), fidelity: unit(raw.fidelity, 0.8), auto: Boolean(raw.auto),
  };
}

// 기반 모델이 Character Reference 를 못 쓰나(NAID4.5 · V5 만 쓴다). 모르는 이름(커스텀)은 서버가 정한다.
function crUnsupported(model) {
  const m = String(model || '').toLowerCase();
  if (!m || m.includes('diffusion-4-5') || m.includes('diffusion-5') || m.includes('naid4.5') || m.includes('naid5')) return false;
  return /^nai-diffusion|^naid[0-9]/.test(m);
}
const PARAM_KEYS = ['model', 'width', 'height', 'steps', 'cfg_scale', 'cfg_rescale', 'sampler', 'scheduler'];
const MAX_ITEMS = 20;

const PBW_CSS = `
/* 메인 화면 덮개(사용자 11-20) - Assets 신 사양(body.assets-v5-mode)과 같은 자리를 가린다. 이 모드의 생성은 왼쪽 [N장 생성] 이라
   아래 조작줄(Generate · Random · 해상도 · 옵션)도 통째로 걷는다. Ctrl+Enter 는 app.js generateAction 이 이 벤치로 돌린다. */
body.preset-bench-mode #tabPrompt > .prompt-highlight-wrap,
body.preset-bench-mode #tabPrompt > .section-label,
body.preset-bench-mode #tabPrompt > #promptInpaintBadge,
body.preset-bench-mode #iaBlocks,
body.preset-bench-mode #cbBlocks,
body.preset-bench-mode .prompt-inner > .tab-bar,
body.preset-bench-mode .assistants-section,
body.preset-bench-mode #moduleLauncher,
body.preset-bench-mode .bottom-controls { display: none !important; }
#pbBlocks { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; font-size: 12px; }
#pbBlocks[hidden] { display: none; }
#presetBenchRoot { flex: 1 1 auto; min-width: 0; min-height: 0; display: flex; flex-direction: column; font-size: 12px; }
/* 3단(사용자 11-20): 왼쪽 열 = 칸 편집(위 · 넘치면 스크롤) + 고르기(아래 · 열 높이의 절반 이상) + [N장 생성].
   오른쪽 탭 = 그림 칸 | 끄는 경계 | 생성 결과(남는다 - 마지막 결과 크게 + 아래 줄에 이전 생성). */
.pbw-left { flex: 1 1 auto; min-height: 0; overflow: hidden; padding: 0 2px 2px 0; display: flex; flex-direction: column; gap: 8px; }
.pbw-ledit { flex: 0 1 auto; min-height: 90px; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; padding-right: 2px; }
.pbw-pick { flex: 1 0 50%; min-height: 0; display: flex; flex-direction: column; gap: 6px; border-top: 1px solid var(--border-dim); padding-top: 8px; }
/* 캐릭터 1명 = 칸 편집이 줄지 않고 다 보인다(고르기는 남는 자리 · 창이 아주 낮을 때만 편집이 스크롤). 2명부터 위 규칙(고르기 절반 이상 · 편집 스크롤).
   스크롤이 생기면 오른쪽 막대를 흰색으로 - 아래에 칸이 더 있다는 표시(사용자 11-20). */
.pbw-left.is-solo .pbw-pick { flex: 1 1 0; min-height: 200px; }
.pbw-ledit { scrollbar-width: thin; scrollbar-color: rgba(255,255,255,0.8) transparent; }
.pbw-ledit::-webkit-scrollbar { width: 8px; }
.pbw-ledit::-webkit-scrollbar-track { background: rgba(255,255,255,0.06); border-radius: 4px; }
.pbw-ledit::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.8); border-radius: 4px; }
.pbw-ledit::-webkit-scrollbar-thumb:hover { background: #fff; }
.pbw-main { flex: 1 1 auto; min-height: 0; display: flex; padding: 8px; }
.pbw-gcol { flex: 0 0 45%; min-width: 220px; min-height: 0; display: flex; flex-direction: column; gap: 6px; }
.pbw-split { flex: 0 0 11px; cursor: col-resize; position: relative; touch-action: none; }
.pbw-split::after { content: ""; position: absolute; left: 5px; top: 0; bottom: 0; width: 1px; background: var(--border-dim); }
.pbw-split:hover::after, .pbw-split.is-drag::after { left: 4px; width: 3px; background: var(--accent); }
.pbw-rcol { flex: 1 1 0; min-width: 260px; min-height: 0; display: flex; flex-direction: column; }
.pbw-lhead { display: flex; align-items: center; gap: 8px; }
.pbw-lhead b { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.pbw-lhead .pbw-btn { margin-left: auto; }
.pbw-basecur { flex: 1 1 auto; min-width: 0; font-size: 11px; color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.pbw-basecur b { font-weight: 600; color: var(--text-primary); }
.pbw-right { flex: 1 1 auto; min-width: 0; min-height: 0; display: flex; flex-direction: column; position: relative; }
.pbw-ex { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; padding: 8px; gap: 6px; }
.pbw-row { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.pbw-dim { color: var(--text-dim); }
.pbw-sm { font-size: 11px; }
.pbw-btn { padding: 3px 9px; border: 1px solid var(--border-dim); border-radius: 5px; background: transparent; color: var(--text-primary);
  font-family: inherit; font-size: 12px; cursor: pointer; }
.pbw-btn:hover:not(:disabled) { border-color: var(--accent); }
.pbw-btn:disabled { color: var(--text-dim); cursor: default; }
.pbw-btn.is-primary { border-color: var(--accent); }
.pbw-input, .pbw-select, .pbw-text { background: var(--bg-surface); color: var(--text-primary); border: 1px solid var(--border-dim);
  border-radius: 5px; font-family: inherit; font-size: 12px; padding: 3px 6px; min-width: 0; }
.pbw-text { width: 100%; box-sizing: border-box; resize: vertical; min-height: 26px; font-family: var(--font-mono); font-size: 11px; }
/* 기반 = 머리 줄의 보라 [프리셋 설정] 단추(사용자 11-20 - 기반 카드를 걷어 아래 칸이 더 보이게). 기반 이름 · 요약은 툴팁. */
.pbw-base { border: 1px solid var(--accent); border-radius: 6px; padding: 3px 10px; cursor: pointer; background: var(--accent); color: #fff;
  font-family: inherit; font-size: 12px; font-weight: 600; white-space: nowrap; }
.pbw-base:hover { background: var(--accent-glow); border-color: var(--accent-glow); }
.pbw-base.is-on { box-shadow: inset 0 0 0 2px rgba(255,255,255,0.55); }
.pbw-seg { display: inline-flex; border: 1px solid var(--border-dim); border-radius: 5px; overflow: hidden; }
.pbw-seg button { border: 0; background: transparent; color: var(--text-dim); padding: 2px 8px; font-family: inherit; font-size: 11px; cursor: pointer; }
.pbw-seg button.is-on { background: var(--bg-hover); color: var(--text-primary); box-shadow: inset 0 -2px 0 var(--accent); }
.pbw-chars { display: flex; flex-direction: column; gap: 8px; }
.pbw-solos { display: flex; flex-direction: column; gap: 8px; }
/* 칸 테두리는 조금 밝게 - 칸 사이가 잘 갈리게(사용자 11-20). */
.pbw-ccard { background: var(--bg-card); border: 1px solid rgba(255,255,255,0.16); border-radius: 7px; overflow: hidden; }
.pbw-chead { display: flex; align-items: center; gap: 6px; padding: 5px 8px; font-size: 12px; font-weight: 600; color: var(--text-primary);
  border-bottom: 1px solid rgba(255,255,255,0.12); }
.pbw-ccard > .pbw-text { display: block; margin: 6px 8px; width: calc(100% - 16px); }
/* 캐릭터 프롬프트 칸 = 그 캐릭터를 고르는 중일 때만 네 줄(사용자 11-20) - 다른 칸을 고르면 한 줄로 돌아간다(rows 는 renderSlots). */
.pbw-ccard > .pbw-text { line-height: 1.5; padding: 4px 6px; }
.pbw-subj { padding: 0 5px; border: 1px solid var(--border-glow); border-radius: 4px; font-size: 10.5px; font-weight: 400; color: var(--text-primary); }
.pbw-subj.is-guess { color: var(--text-dim); border-style: dashed; }
.pbw-addc { border: 1px dashed var(--border-glow); border-radius: 6px; background: transparent; color: var(--text-muted); padding: 4px;
  font-family: inherit; font-size: 11px; cursor: pointer; }
.pbw-addc:hover { border-color: var(--accent); color: var(--text-primary); }
.pbw-pool { position: absolute; left: 3px; top: 3px; z-index: 1; padding: 0 4px; border-radius: 3px; font-size: 10px; line-height: 15px;
  background: rgba(0, 0, 0, 0.6); color: #fff; pointer-events: none; }
/* 칸 = 한 줄 [이름 | 고른 태그 | ×]. 빈 칸은 흐린 '+ 고르기' 라 채운 칸만 밝게 튄다.
   지금 칸 = 옅은 보라 바탕 + 왼쪽 곧은 막대(둥근 모서리를 따라 휘는 강조는 쓰지 않는다). */
.pbw-slot { position: relative; display: grid; grid-template-columns: 46px minmax(0, 1fr) auto; gap: 4px; align-items: start;
  padding: 4px 8px; cursor: pointer; }
.pbw-slot + .pbw-slot { border-top: 1px solid rgba(255,255,255,0.10); }
.pbw-slot:hover { background: var(--bg-hover); }
.pbw-slot.is-cur { background: rgba(124,106,239,0.16); }
.pbw-slot.is-cur::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--accent); }
.pbw-slot-k { font-size: 11px; color: var(--text-muted); padding-top: 2px; line-height: 1.25; }
.pbw-slot-k small { display: block; font-size: 10px; color: var(--text-dim); }
.pbw-slot.is-cur .pbw-slot-k { color: var(--accent-light); }
.pbw-ccard.is-solo .pbw-slot-k { color: var(--text-primary); font-weight: 600; }
.pbw-ccard.is-solo .pbw-slot.is-cur .pbw-slot-k { color: var(--accent-light); }
/* 자세 (2인 이상) = 배경 위 붉은 카드(사용자 11-20 - 주로 NSFW 갈래라 눈에 띄게). 고르는 중이면 위 보라 규칙이 덧칠한다. */
.pbw-ccard.is-link { background: rgba(226,75,74,0.10); border-color: rgba(226,75,74,0.5); }
.pbw-ccard.is-link .pbw-slot-k, .pbw-ccard.is-link .pbw-slot-k small { color: #f09595; }
/* 추가 프롬프트 - 캐릭터 카드의 표정 아래(그 캐릭터 몫) · 배경 아래 카드(메인 몫).
   기본은 접힌 한 줄(칸 줄과 같은 [이름 | 글 | ×]) - 누르면 펼치고(rows 4) 초점이 떠나면 다시 한 줄(사용자 11-20). */
.pbw-extra { display: grid; grid-template-columns: 46px minmax(0, 1fr) auto; gap: 4px; align-items: start; padding: 3px 8px;
  border-top: 1px solid rgba(255,255,255,0.10); background: rgba(93,202,165,0.08); }
.pbw-extra .pbw-slot-k { color: #7fd8b9; }
.pbw-ccard.is-extra { border-color: rgba(93,202,165,0.35); }
/* 2인 이상 자세 - 이름은 '자세' 한 줄, '2인 이상' 은 값 칸 앞 표지로(사용자 11-20 - 세로 자리를 아낀다). */
.pbw-l2 { display: inline-block; padding: 0 4px; margin: 2px 4px 0 0; border-radius: 3px; font-size: 10px; line-height: 16px;
  background: rgba(226,75,74,0.22); color: #f09595; vertical-align: top; }
.pbw-extra .pbw-text { min-height: 0; resize: none; overflow: hidden; line-height: 1.45; padding: 1px 6px; border-color: transparent;
  background: transparent; cursor: text; }
.pbw-extra .pbw-text:hover { border-color: var(--border-dim); }
.pbw-extra .pbw-text:focus { overflow-y: auto; border-color: var(--accent); background: var(--bg-surface); }
.pbw-extra .pbw-text::placeholder { color: var(--text-dim); font-family: inherit; }
.pbw-extra:not(.has-text) .pbw-slot-x { visibility: hidden; }
.pbw-ccard.is-extra .pbw-extra { border-top: 0; }
.pbw-ccard.is-extra .pbw-slot-k { color: #7fd8b9; font-weight: 600; }
.pbw-slot-v { min-width: 0; }
.pbw-slot-empty { display: inline-block; font-size: 11px; color: var(--text-dim); padding-top: 2px; }
.pbw-slot.is-cur .pbw-slot-empty { color: var(--accent-light); }
.pbw-lpool { display: inline-block; padding: 0 4px; margin: 2px 3px 0 0; border-radius: 3px; font-size: 10px; line-height: 16px;
  background: rgba(124,106,239,0.24); color: var(--accent-light); vertical-align: top; }
.pbw-warn { display: inline-block; padding: 0 4px; margin: 2px 3px 0 0; border-radius: 3px; font-size: 10px; line-height: 16px;
  background: rgba(240,198,116,0.2); color: #f0c674; vertical-align: top; cursor: help; }
.pbw-slot-x { border: 0; background: transparent; color: var(--text-dim); cursor: pointer; font-size: 13px; line-height: 1; padding: 2px; }
.pbw-slot-x:hover { color: var(--text-primary); }
.pbw-chip { display: inline-block; max-width: 100%; padding: 0 5px; margin: 2px 3px 0 0; border: 1px solid var(--border-dim); border-radius: 4px;
  font-size: 11px; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; vertical-align: top; cursor: pointer; }
.pbw-chip:hover { border-color: var(--accent); }
.pbw-cmp { color: var(--accent); border-color: var(--accent); cursor: default; }
/* 이 창의 주 동작 - 하나뿐인 채운 단추. */
.pbw-btn.pbw-go { margin-top: auto; padding: 7px; font-size: 13px; font-weight: 600; background: var(--accent); border-color: var(--accent); color: #fff; }
.pbw-btn.pbw-go:hover:not(:disabled) { background: var(--accent-glow); border-color: var(--accent-glow); }
.pbw-note { display: flex; gap: 8px; align-items: center; padding: 4px 8px; border-radius: 5px; background: var(--bg-hover); font-size: 11px; }
.pbw-note a { color: var(--accent); cursor: pointer; }
/* 탐색 세 칸(대분류 | 소분류 · 시드 | 그림) 사이에 세로 선 - 상자는 씌우지 않는다. */
.pbw-cats { display: flex; flex-direction: column; gap: 1px; min-height: 0; overflow-y: auto; border-right: 1px solid var(--border-dim); padding-right: 6px; }
.pbw-cat { display: flex; justify-content: space-between; align-items: baseline; gap: 4px; padding: 3px 7px; border: 0; border-radius: 4px;
  color: var(--text-muted); font-size: 14px; cursor: pointer; background: transparent; font-family: inherit; text-align: left; }
.pbw-cat small { font-size: 11px; color: var(--text-dim); }
.pbw-cat:hover { color: var(--text-primary); }
.pbw-cat { position: relative; }
/* 고른 칸 표시는 곧은 막대로 - inset 그림자는 둥근 모서리를 따라 휘어 { 처럼 보인다(사용자 지시 2026-11-20). */
.pbw-cat.is-on { color: var(--text-primary); background: var(--bg-hover); }
.pbw-cat.is-on::before { content: ""; position: absolute; left: 0; top: 3px; bottom: 3px; width: 2px; background: var(--accent); }
/* 소분류 머리글이 항목보다 위로 읽히게 - 굵게 · 밝게 · 아래 선. */
/* 소분류 머리글 = 강조색 바탕 띠(사용자 11-20 - 하위 그룹이 한눈에). */
.pbw-sub { font-size: 13px; font-weight: 600; color: var(--text-primary); padding: 3px 7px; margin: 8px 0 2px;
  border-radius: 4px; background: color-mix(in srgb, var(--accent) 22%, transparent); }
.pbw-sub:first-child { margin-top: 0; }
.pbw-ex2 { flex: 1 1 auto; min-height: 0; display: grid; grid-template-columns: 180px minmax(0, 1fr); gap: 8px; }
/* 고른 대분류 아래 소분류 나무(사용자 11-20) - 들여쓰기 + 왼쪽 가는 줄 · 글은 대분류보다 한 단계 작게. 누르면 그 소분류만. */
.pbw-csubs { display: flex; flex-direction: column; gap: 1px; margin: 1px 0 5px 9px; border-left: 1px solid rgba(255,255,255,0.14); flex: none; }
.pbw-csub { display: flex; justify-content: space-between; align-items: baseline; gap: 4px; margin-left: 5px; padding: 2px 7px; border: 0; border-radius: 4px;
  background: transparent; color: var(--text-muted); font-family: inherit; font-size: 12px; text-align: left; cursor: pointer; position: relative; }
.pbw-csub small { font-size: 10px; color: var(--text-dim); }
.pbw-csub:hover { color: var(--text-primary); }
.pbw-csub.is-on { color: var(--text-primary); background: color-mix(in srgb, var(--accent) 22%, transparent); }
.pbw-csub.is-on::before { content: ""; position: absolute; left: 0; top: 3px; bottom: 3px; width: 2px; background: var(--accent); }
.pbw-ex2.is-related { grid-template-columns: minmax(0, 1fr) 0; }
.pbw-seeds { min-height: 0; overflow-y: auto; border-right: 1px solid var(--border-dim); padding-right: 6px; }
.pbw-ex2.is-related .pbw-seeds { border-right: 0; padding-right: 0; }
.pbw-seed { display: flex; justify-content: space-between; align-items: baseline; gap: 6px; padding: 2px 5px 2px 9px; border-radius: 4px; cursor: pointer;
  color: var(--text-primary); font-size: 14px; }
/* 한글 이름은 밝게 · 옆 영문 태그는 2px 작고 어둡게 · 오른쪽 수 = 고를 수 있는 세트 수(사용자 11-20). */
.pbw-seed span:first-child small { margin-left: 5px; font-size: 12px; color: var(--text-dim); }
.pbw-seed span:last-child { flex: none; font-family: var(--font-mono); font-size: 11px; color: var(--text-dim); }
.pbw-seed.is-all { font-weight: 600; margin-bottom: 2px; }
.pbw-seed.is-on span:last-child, .pbw-seed:hover span:last-child { color: inherit; }
.pbw-seed span:first-child { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pbw-seed:hover { color: var(--text-primary); }
.pbw-seed { position: relative; }
.pbw-seed.is-on { background: var(--bg-hover); color: var(--text-primary); }
.pbw-seed.is-on::before { content: ""; position: absolute; left: 0; top: 3px; bottom: 3px; width: 2px; background: var(--accent); }
.pbw-ex-head { display: flex; align-items: center; gap: 8px; min-width: 0; }
.pbw-ex-own { color: var(--text-dim); }
.pbw-ex-ctx { min-width: 0; color: var(--text-dim); font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.pbw-ex-head .pbw-input { margin-left: auto; flex: 0 1 220px; min-width: 120px; }
.pbw-gcol .pbw-ex-ctx { font-size: 12px; color: var(--text-muted); }
.pbw-grid-wrap { flex: 1 1 auto; min-height: 0; overflow-y: auto; padding-right: 4px; }
/* 덧붙는 몸 태그(메인에 함께 싣는다 - 사용자 11-20) = 흐린 '+태그'. */
.pbw-chip.pbw-add { opacity: 0.6; border-style: dashed; cursor: default; }
.pbw-cap-add { color: var(--text-dim); }
/* 가운데 그림 칸 스크롤바 = 잘 보이게(사용자 11-20). 세트가 수백이면 칸이 4만 px 라 막대가 10px 로 줄어 안 보였다 -
   막대 최소 높이 48px. scrollbar-color 를 주면 크로미움이 ::-webkit-scrollbar 를 통째로 무시하므로 쓰지 않는다. */
.pbw-grid-wrap::-webkit-scrollbar { width: 10px; }
.pbw-grid-wrap::-webkit-scrollbar-track { background: rgba(255,255,255,0.07); border-radius: 5px; }
.pbw-grid-wrap::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.8); border-radius: 5px; min-height: 48px; }
.pbw-grid-wrap::-webkit-scrollbar-thumb:hover { background: #fff; }
/* 그림 칸 = 너비와 무관하게 한 줄 2장(사용자 11-20 - 스크롤당 볼 것이 많지 않다). */
.pbw-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px; align-content: start; grid-auto-rows: max-content; }
/* 캐릭터 고르기(DB · 에셋 · REF)는 한 줄 3장(사용자 11-20) - 칸 고르기는 2장 그대로. */
.pbw-grid.is-3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
/* 판이 넓으면(3장으로 나눠도 칸이 크게 보기의 80% 이상) 칸 고르기도 한 줄 3장(사용자 11-20) - 판 너비를 재서 붙인다(fitGridCols). */
.pbw-grid-wrap.is-w3 .pbw-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.pbw-sec { font-size: 12px; color: var(--text-muted); margin: 8px 0 3px; }
.pbw-sec:first-child { margin-top: 0; }
.pbw-sec small { margin-left: 4px; color: var(--text-dim); }
.pbw-card { position: relative; border: 1px solid var(--border-dim); border-radius: 6px; overflow: hidden; cursor: pointer; background: var(--bg-surface); }
.pbw-card:hover { border-color: var(--accent); }
.pbw-card.is-sel { outline: 2px solid var(--accent); outline-offset: -2px; }
.pbw-card.is-hit { box-shadow: 0 0 0 2px #f0c674 inset; }
.pbw-th { display: block; width: 100%; aspect-ratio: 1; object-fit: cover; background: #0c0c12; }
.pbw-th.is-tall { aspect-ratio: 525 / 768; }
.pbw-none { display: flex; align-items: center; justify-content: center; color: #777; font-size: 11px; }
.pbw-cap { padding: 2px 5px 3px; font-size: 11px; color: var(--text-dim); line-height: 1.35;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.pbw-ck { position: absolute; top: 4px; right: 4px; width: 18px; height: 18px; border-radius: 4px; border: 1px solid var(--border-dim);
  background: rgba(12,12,18,0.85); color: var(--accent); font-size: 12px; line-height: 16px; text-align: center; cursor: pointer; }
.pbw-ck.is-on { border-color: var(--accent); }
.pbw-empty { margin: auto; padding: 20px; text-align: center; color: var(--text-dim); font-size: 12px; line-height: 1.6; }
/* 생성 결과 열 - 닫지 않는다. 한 장 = 원본을 칸에 맞춰 크게, 비교 = 격자. 아래 줄 = 이전 생성(누르면 그 생성을 본다). */
.pbw-rl { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; background: var(--bg-surface);
  border: 1px solid var(--border-dim); border-radius: 6px; overflow: hidden; }
.pbw-rl > .pbw-empty { margin: auto; }
.pbw-rl-hist { flex: none; display: flex; gap: 4px; overflow-x: auto; padding: 6px 8px; border-top: 1px solid var(--border-dim); }
.pbw-rl-h { position: relative; flex: 0 0 56px; height: 56px; padding: 0; border: 2px solid transparent; border-radius: 5px; overflow: hidden;
  cursor: pointer; background: #0c0c12; }
.pbw-rl-h:hover { border-color: var(--border-glow); }
.pbw-rl-h.is-on { border-color: var(--accent); }
.pbw-rl-h img { display: block; width: 100%; height: 100%; object-fit: cover; }
.pbw-rl-h .pbw-res-box { height: 100%; aspect-ratio: auto; }
.pbw-rl-h span { position: absolute; right: 2px; bottom: 2px; padding: 0 3px; border-radius: 3px; font-size: 10px; line-height: 14px;
  background: rgba(0, 0, 0, 0.65); color: #fff; }
/* 해상도 - 결과 열 오른쪽 아래에 떠 있는 표준 드롭다운(customSelects 가 quick-select 를 감싼다). 이전 생성 줄이 있으면 그 위로. */
.pbw-rcol { position: relative; }
.pbw-resfloat { position: absolute; right: 10px; bottom: 10px; z-index: 3; }
/* 해상도 단추 = 반투명 바탕(사용자 11-20 - 투명이면 그림 위에서 안 읽힌다). */
.pbw-resfloat .param-select.quick-select { background-color: rgba(12, 12, 18, 0.62); border: 1px solid rgba(255,255,255,0.18);
  border-radius: 6px; color: var(--text-primary); backdrop-filter: blur(4px); }
.pbw-resfloat .param-select.quick-select:hover { background-color: rgba(12, 12, 18, 0.8); }
.pbw-rcol.has-hist .pbw-resfloat { bottom: 80px; }
.pbw-rl-body { flex: 1 1 auto; min-height: 0; overflow-y: auto; padding: 8px; }
.pbw-rl-body.is-one { display: flex; overflow: hidden; }
.pbw-rl-one { flex: 1 1 auto; min-width: 0; min-height: 0; display: flex; align-items: center; justify-content: center; }
.pbw-rl-one img { display: block; max-width: 100%; max-height: 100%; object-fit: contain; border-radius: 4px; }
.pbw-rl-one .pbw-res-box { width: auto; aspect-ratio: auto; font-size: 13px; }
.pbw-rl-one.is-error .pbw-res-box { color: #ffb4b4; }
.pbw-rgrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(110px, 1fr)); gap: 8px; align-content: start; }
.pbw-res { position: relative; border: 2px solid transparent; border-radius: 6px; overflow: hidden; cursor: pointer; background: #0c0c12; }
.pbw-res:hover { border-color: var(--border-glow); }
.pbw-res.is-pick { border-color: var(--accent); }
.pbw-res img { display: block; width: 100%; aspect-ratio: 3 / 4; object-fit: contain; }
.pbw-res-box { display: flex; align-items: center; justify-content: center; width: 100%; aspect-ratio: 3 / 4; color: #888; font-size: 11px; text-align: center; padding: 4px; box-sizing: border-box; }
.pbw-res.is-error .pbw-res-box { color: #ffb4b4; }
.pbw-res.is-cancel { background: transparent; border: 1px dashed var(--border-dim); }
.pbw-res-cap { padding: 2px 4px; font-size: 11px; color: var(--text-dim); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; background: var(--bg-surface); }
.pbw-pin { position: absolute; left: 4px; right: 4px; top: 4px; padding: 2px 0; font-size: 11px; border-radius: 4px; border: 1px solid var(--accent);
  background: rgba(12,12,18,0.9); color: var(--text-primary); cursor: pointer; font-family: inherit; }
.pbw-ov { position: absolute; inset: 0; z-index: 2; background: var(--bg-elevated, var(--bg-surface)); padding: 10px 12px; overflow-y: auto; border-left: 1px solid var(--accent); }
/* 기반 설정 판 - NAIA 표준(사용자 11-20): 칸 이름 = mod-section-label · 글 칸 = mod-textarea · 설정 = Params 탭의 params-grid ·
   프리셋 고르기 = PE Quick Preset 과 같은 표준 드롭다운(mod-select mod-preset-select - 모델 배지 · 짚으면 미리보기). */
/* 판 높이에 맞춘다(사용자 11-20 "빈 공간 자동 fitting"): 두 칸 모두 세로 flex - 글 칸(.pbw-bs-ro · mod-textarea)이 남는 높이를 나눠 갖는다.
   왼쪽 = 앞 · 뒤, 오른쪽 = Params 아래 Negative. 판이 낮으면 글 칸 최소 높이에서 멈추고 판이 스크롤된다. */
.pbw-bs { padding: 10px 16px 16px; font-family: var(--font-mono); font-size: 11px; color: var(--text-muted); display: flex; flex-direction: column; box-sizing: border-box; }
.pbw-bs-head { display: flex; align-items: center; gap: 10px; flex: none; }
.pbw-bs-head b { font: 600 13px var(--font-display); color: var(--text-primary); }
.pbw-bs-cols { display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(260px, 1fr); gap: 18px; margin-top: 4px; flex: 1 0 auto; }
.pbw-bs-cols > div { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
.pbw-bs-cols > div > * { flex: none; }
.pbw-bs-cols > div > .pbw-bs-ro, .pbw-bs-cols > div > .mod-textarea { flex: 1 1 0; min-height: 90px; max-height: none; }
.pbw-bs .mod-section-label { margin-top: 12px; display: flex; align-items: baseline; gap: 8px; }
.pbw-bs-note { font: 400 10px var(--font-mono); letter-spacing: 0; text-transform: none; color: var(--text-dim); line-height: 1.5; }
.pbw-bs-line { display: flex; align-items: center; gap: 6px; min-width: 0; }
.pbw-bs-line > select, .pbw-bs-line > .custom-select { flex: 1 1 auto; min-width: 0; }
.pbw-bs-btn { flex: none; padding: 5px 12px; border: 1px solid var(--border-dim); border-radius: 6px; background: var(--bg-elevated, var(--bg-card));
  color: var(--text-primary); font: 500 11px var(--font-mono); cursor: pointer; white-space: nowrap; }
.pbw-bs-btn:hover { border-color: var(--accent); }
.pbw-bs-btn.is-danger { background: rgba(244, 67, 54, 0.12); color: #ff8a80; border-color: rgba(244, 67, 54, 0.32); }
.pbw-bs-ro { background: var(--bg-deep); border: 1px solid var(--border-dim); border-radius: 6px; padding: 8px 10px; color: var(--text-muted);
  font-family: var(--font-editor, var(--font-mono)); font-size: 11px; line-height: 1.45; word-break: break-word; max-height: 150px; overflow-y: auto; }
.pbw-bs .mod-textarea { display: block; box-sizing: border-box; resize: vertical; min-height: 96px; }
.pbw-bs-val { font: 500 12px var(--font-mono); color: var(--text-muted); text-align: right; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pbw-bs-ses { margin-left: 6px; padding: 0 4px; border: 1px dashed var(--border-dim); border-radius: 3px; font-size: 9.5px; color: var(--text-dim); }
.pbw-bs .param-row { padding: 4px 12px; min-height: 32px; gap: 8px; }
.pbw-bs .param-input::placeholder { color: var(--text-dim); opacity: 0.8; }
.pbw-bs-src { margin-top: 6px; font-size: 10.5px; color: var(--text-dim); }
.pbw-bs-src > span:first-child { flex: none; }
.pbw-bs-badge { color: #f0c674; font-weight: 600; }
.pbw-form { display: grid; grid-template-columns: 70px minmax(0, 1fr); gap: 6px 8px; align-items: start; margin-top: 8px; }
.pbw-form > .pbw-dim { padding-top: 4px; }
.pbw-params { display: flex; flex-wrap: wrap; gap: 6px; }
.pbw-params label { display: flex; flex-direction: column; gap: 2px; font-size: 11px; color: var(--text-dim); }
.pbw-params input { width: 84px; }
.pbw-params input.is-wide { width: 150px; }
.pbw-band { padding: 6px 8px; border: 1px solid rgba(240,198,116,0.45); border-radius: 6px; font-size: 11px; display: flex; gap: 8px; align-items: center; }
/* 캐릭터 카드 = 칸 - 머리 · 글 칸을 누르면 고르기가 그 캐릭터로. 고르는 중 = 칸과 같은 옅은 보라 + 곧은 막대 + 테두리. */
.pbw-ex-head { flex-wrap: wrap; }
.pbw-chead[data-act="char-pick"] { cursor: pointer; position: relative; }
.pbw-chead[data-act="char-pick"]:hover { background: var(--bg-hover); }
.pbw-chead > .pbw-gap { flex: 1 1 auto; }
.pbw-cpick { display: none; font-size: 10.5px; font-weight: 400; color: var(--accent-light); white-space: nowrap; }
.pbw-ccard.is-picking { border-color: var(--accent); }
.pbw-ccard.is-picking > .pbw-chead { background: rgba(124,106,239,0.16); }
.pbw-ccard.is-picking > .pbw-chead::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--accent); }
.pbw-ccard.is-picking .pbw-cpick { display: inline; }
/* 캐릭터 고르기 머리 = 제목 / 세 갈래 한 줄(폭 전체) / 검색칸(폭 전체) - 사용자 11-20 "검색은 토글 줄 아래로". */
.pbw-ex-src:empty { display: none; }
.pbw-ex-head.is-char { flex-direction: column; align-items: stretch; gap: 6px; }
.pbw-ex-head.is-char .pbw-input { margin-left: 0; flex: none; width: 100%; min-width: 0; }
.pbw-ex-src .pbw-seg { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); width: 100%; }
.pbw-ex-src .pbw-seg button { padding: 5px 4px; font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.pbw-cats > .pbw-cfilter { display: flex; gap: 4px; align-items: center; flex: none; margin: 0 0 4px 2px; }
.pbw-cats > .pbw-cfilter > .pbw-seg { margin: 0; }
.pbw-fav { border: 1px solid var(--border-dim); border-radius: 5px; background: transparent; color: var(--text-dim); font-size: 11px;
  padding: 2px 7px; cursor: pointer; font-family: inherit; }
.pbw-fav.is-on { color: #f0c674; border-color: rgba(240,198,116,0.6); }
.pbw-cmeta { padding: 0 8px; }
.pbw-cmeta:empty { display: none; }
.pbw-cfrom { display: flex; align-items: center; gap: 4px; min-width: 0; margin: -2px 0 5px; font-size: 10.5px; color: var(--text-dim); }
.pbw-cfrom > span:first-child { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pbw-uc { flex: none; padding: 0 4px; border: 1px solid var(--border-dim); border-radius: 3px; color: var(--text-muted); cursor: help; }
.pbw-crefs { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; margin: 0 0 5px; }
.pbw-crefs-k { flex: none; width: 28px; font-size: 10.5px; color: var(--text-muted); }
.pbw-ref { display: inline-flex; align-items: center; gap: 4px; max-width: 100%; padding: 1px 1px 1px 1px; border: 1px solid var(--border-dim);
  border-radius: 4px; font-size: 10.5px; color: var(--text-primary); white-space: nowrap; }
.pbw-ref img { width: 22px; height: 22px; object-fit: cover; border-radius: 3px; background: #0c0c12; }
.pbw-ref .pbw-slot-x { font-size: 12px; padding: 0 3px; }
.pbw-cwarn { margin: 0 0 5px; font-size: 10.5px; line-height: 1.4; color: #f0c674; }
.pbw-attach { display: inline-flex; align-items: center; gap: 4px; flex: none; font-size: 11px; color: var(--text-muted); white-space: nowrap; cursor: pointer; }
.pbw-tools { margin-left: auto; display: inline-flex; align-items: center; gap: 6px; }
.pbw-tools:empty { display: none; }
.pbw-hint { padding: 3px 5px; font-size: 11px; line-height: 1.5; color: var(--text-dim); }
.pbw-cats > .pbw-seg { flex: none; align-self: flex-start; margin: 0 0 4px 2px; }
`;

function ensureStyle(doc) {
  if (doc.getElementById(STYLE_ID)) return;
  const style = doc.createElement('style');
  style.id = STYLE_ID;
  style.textContent = PBW_CSS;
  doc.head.appendChild(style);
}

function makeId() {
  return `pb-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function cleanParams(raw) {
  const out = {};
  const source = raw && typeof raw === 'object' ? raw : {};
  for (const key of PARAM_KEYS) {
    const value = source[key];
    if (value === undefined || value === null || value === '') continue;
    if (['model', 'sampler', 'scheduler'].includes(key)) { out[key] = String(value); continue; }
    const number = Number(value);
    if (Number.isFinite(number)) out[key] = number;
  }
  return out;
}

function paramsSummary(params) {
  const p = params || {};
  const parts = [];
  if (p.model) parts.push(String(p.model));
  if (p.steps) parts.push(`${p.steps}스텝`);
  if (p.cfg_scale !== undefined) parts.push(`CFG ${p.cfg_scale}`);
  if (p.sampler) parts.push(String(p.sampler));
  return parts.join(' · ');
}

export function createPresetBench({
  document: doc,
  window: win = (typeof window !== 'undefined' ? window : null),
  fetch: fetchFn = win.fetch.bind(win),
  escHtml = v => String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'),
  // 그림 카드에 마우스를 올리면 창 옆에 크게 - 아티스트 썸네일 · 아티스트 태그 관리 창과 같은 문
  // (app.js 의 remoteController.showZoomBeside / hideZoom - 자리 규칙이 한 곳). 없으면 크게 보기 없이.
  showZoom = null,
  hideZoom = () => {},
  // 캐릭터 글 칸에 태그 자동완성을 붙인다(app.js bindTagAssist). 없으면 그냥 글 칸.
  bindTagAssist = null,
  notify = () => {},
  onVisibilityChange = () => {},
  // 기반 설정 판(사용자 11-20) - 메인 Params 탭의 지금 값 · 고를 목록(모델 · 샘플러 · 스케줄러) · PE 프리셋 요약(모델 배지 · 미리보기) ·
  // 이름 묻기(앱 표준 대화 상자). 없으면 빈 값 · 빈 목록 · 브라우저 prompt.
  getSessionParams = () => ({}),
  getApiMode = () => 'NAI',             // 지금 API 모드(NAI · WEBUI · COMFYUI) - 캐릭터를 어디에 싣나를 정한다
  getParamChoices = () => ({}),
  getPresetSummaries = () => [],
  askText = null,
  // 메인 화면의 두 자리 - 왼쪽 프롬프트 열 안(#pbBlocks) · 오른쪽 Presets 탭 안(#presetBenchRoot).
  leftMount,
  rightMount,
  // [← 프롬프트] - 탭을 떠난다(app.js 가 덮개를 걷는다).
  onLeave = () => {},
  storage = (() => { try { return win.localStorage; } catch (_) { return null; } })(),
}) {
  ensureStyle(doc);
  const esc = escHtml;

  // ---------------------------------------------------------------- 상태
  const saved = (() => {
    try { return JSON.parse(storage?.getItem(STORE_KEY) || '{}') || {}; } catch (_) { return {}; }
  })();
  const st = {
    // 캐릭터 수. 옛 저장값(castId)의 2인 인원(gb · gg · bb)은 2명으로 옮긴다.
    count: normalizeCast({count: saved.count ?? (['gb', 'gg', 'bb'].includes(saved.castId) ? 2 : 1)}).count,
    // 캐릭터마다 서버가 정한 성별(저장하지 않는다 - 창을 열 때 글로 다시 묻는다).
    subjects: Array.from({length: MAX_CHARACTERS}, () => ({gender: '', source: '', name: ''})),
    names: Array.isArray(saved.names) ? saved.names.slice(0, 2).map(String) : ['', ''],
    // 추가 프롬프트 - 캐릭터마다(그 캐릭터 몫 끝) · 메인(메인 끝).
    extras: Array.from({length: MAX_CHARACTERS}, (_, i) => String(saved.extras?.[i] || '')),
    // 처음 상태(저장값에 아직 없음)는 'full body'(사용자 11-20) - 비우면 빈 채로 기억한다.
    extraMain: saved.extraMain === undefined ? 'full body' : String(saved.extraMain || ''),
    size: BENCH_SIZES.includes(saved.size) ? saved.size : DEFAULT_SIZE,     // 벤치 해상도(기반의 크기 대신)
    // 캐릭터마다 - 에셋에서 불러온 UC · 어디서 불러왔나(카드 아래 한 줄) · REF 줄.
    ucs: Array.from({length: MAX_CHARACTERS}, (_, i) => String(saved.ucs?.[i] || '')),
    loaded: Array.from({length: MAX_CHARACTERS}, (_, i) => (saved.loaded?.[i]?.label
      ? {src: String(saved.loaded[i].src || ''), key: String(saved.loaded[i].key || ''), label: String(saved.loaded[i].label)} : null)),
    refs: Array.from({length: MAX_CHARACTERS}, (_, i) => (Array.isArray(saved.refs?.[i]) ? saved.refs[i].map(cleanRef).filter(Boolean) : [])),
    // 캐릭터 고르기(st.cur = 'char1' · 'char2') - 출처 · 에셋 그림을 REF 로도 붙이나 · 출처마다 탐색 자리.
    cv: {
      src: ['db', 'asset', 'ref'].includes(saved.cv?.src) ? saved.cv.src : 'db',
      attach: saved.cv?.attach !== false,
      db: {group: '__ALL__', gender: '', q: '', fav: false},
      asset: {cat: 'v5', q: '', sel: ''},
      ref: {filter: 'all', cat: '', q: ''},
    },
    picks: saved.picks && typeof saved.picks === 'object' ? saved.picks : {},   // 칸 id -> 세트 요약
    cur: 'o1',
    views: {},            // 칸 id -> {cat, seed, mode: browse|search|related, q, hits, related, relatedTag}
    chk: {},              // 칸 id -> Map(set id -> 세트)
    axis: null,
    memo: null,
    note: '',
    runs: [],
    pick: null,           // [run id, item index]
    baseOpen: false,
    resRun: '',           // 결과 열이 보여 주는 생성(run id) - 비면 마지막 생성
    // 그림 칸 : 결과 열 너비(그림 칸 몫 0.25~0.75) - 경계를 끌어 바꾸고 기억한다. 두 번 누르면 0.45.
    split: Math.min(0.75, Math.max(0.25, Number(saved.split) || 0.45)),
    base: {
      mode: saved.base?.mode === 'direct' ? 'direct' : 'preset',
      preset: String(saved.base?.preset || ''),
      directName: String(saved.base?.directName || ''),
      directFrom: String(saved.base?.directFrom || ''),     // 직접 설정 값을 불러온 프리셋 이름
      direct: {
        prefix: String(saved.base?.direct?.prefix || ''),
        postfix: String(saved.base?.direct?.postfix || ''),
        negative_prompt: String(saved.base?.direct?.negative_prompt || ''),
        params: cleanParams(saved.base?.direct?.params),
      },
    },
    exportTarget: '',
  };
  let bases = null;        // {current, presets: [...]}
  let directs = [];        // [{name, prefix, postfix, negative_prompt, params}]
  let thumbStatus = null;
  const catalogCache = new Map();
  const setsCache = new Map();
  let searchTimer = 0;
  let searchSerial = 0;

  function persist() {
    try {
      storage?.setItem(STORE_KEY, JSON.stringify({
        count: st.count, names: st.names, picks: st.picks, split: st.split, size: st.size,
        extras: st.extras, extraMain: st.extraMain,
        ucs: st.ucs, loaded: st.loaded, refs: st.refs, cv: {src: st.cv.src, attach: st.cv.attach},
        base: {mode: st.base.mode, preset: st.base.preset, directName: st.base.directName, directFrom: st.base.directFrom, direct: st.base.direct},
      }));
    } catch (_) { /* 이번 실행만 */ }
  }

  const slots = () => slotsFor(st.count);
  // linkPool = 2인 이상 자세 칸에 든 세트의 풀 - 캐릭터가 1명이면 맨 앞 인원 태그를 정한다(상대는 이름 없이).
  const castNow = () => ({count: st.count, genders: st.subjects.slice(0, st.count).map(row => row.gender),
    linkPool: st.picks.link?.pool || ''});
  const slotById = id => slots().find(slot => slot.id === id) || null;
  const picksTags = () => Object.fromEntries(slots().map(slot => [slot.id, st.picks[slot.id]?.tags || []]));
  // 고른 세트의 덧붙는 몸 태그 · 성인 표식(서버 요약 add · adult) - 조립이 메인에 싣는다.
  const picksMeta = () => Object.fromEntries(slots().map(slot => [slot.id, {add: st.picks[slot.id]?.add || [], adult: !!st.picks[slot.id]?.adult}]));
  const viewOf = id => (st.views[id] ||= {cat: '', sub: '', pool: '', seed: '', mode: 'browse', q: '', hits: [], related: null, relatedTag: '', hitSet: ''});
  const axisSets = () => (st.axis && st.chk[st.axis] ? [...st.chk[st.axis].values()] : []);
  const running = () => st.runs.some(run => run.items.some(item => item.status === 'pending'));
  // 고르는 중인 캐릭터(0 · 1) - 칸을 고르는 중이면 -1.
  const charIndex = () => (/^char[12]$/.test(st.cur) && Number(st.cur.slice(4)) <= st.count ? Number(st.cur.slice(4)) - 1 : -1);
  const activeRefs = () => st.refs.slice(0, st.count).flat();

  // ---------------------------------------------------------------- 두 자리(왼쪽 덮개 · 오른쪽 탭)
  let active = false;
  const roots = [leftMount, rightMount];
  const qs = selector => leftMount.querySelector(selector) || rightMount.querySelector(selector);
  const qsa = selector => roots.flatMap(root => [...root.querySelectorAll(selector)]);
  const listen = (type, handler, options) => roots.forEach(root => root.addEventListener(type, handler, options));
  const inside = target => roots.some(root => root.contains(target));
  leftMount.hidden = true;
  leftMount.innerHTML = `
      <div class="pbw-left">
        <div class="pbw-lhead"><b>Presets 벤치</b><button type="button" class="pbw-base" data-act="base">프리셋 설정</button><span class="pbw-basecur" data-role="basecur"></span>
          <button type="button" class="pbw-btn" data-act="leave" title="메인 프롬프트로 돌아갑니다(Result 탭)">← 프롬프트</button></div>
        <div class="pbw-ledit">
          <div class="pbw-chars" data-role="chars"></div>
        </div>
        <div class="pbw-pick">
          <div data-role="note"></div>
          <div class="pbw-ex-head" data-role="ex-head"><b data-role="ex-title" style="font-weight:600;font-size:13px;white-space:nowrap"></b>
            <div class="pbw-ex-src" data-role="ex-src"></div>
            <input class="pbw-input" data-role="search" placeholder="태그 · 한국어 이름 검색"></div>
          <div class="pbw-ex2" data-role="ex2"><div class="pbw-cats" data-role="cats"></div><div class="pbw-seeds" data-role="seeds"></div></div>
        </div>
        <button type="button" class="pbw-btn is-primary pbw-go" data-act="go"></button>
      </div>`;
  rightMount.innerHTML = `
      <div class="pbw-right">
        <div class="pbw-main" data-role="main">
          <div class="pbw-gcol" data-role="gcol">
            <div data-role="band"></div>
            <div class="pbw-ex-head"><span class="pbw-ex-ctx" data-role="ex-ctx"></span><span class="pbw-tools" data-role="ex-tools"></span></div>
            <div class="pbw-grid-wrap" data-role="grid"></div>
          </div>
          <div class="pbw-split" data-role="split" title="끌어서 너비 조정 · 두 번 누르면 처음대로"></div>
          <div class="pbw-rcol" data-role="rcol"><div class="pbw-rl" data-role="results"></div>
            <div class="pbw-resfloat" title="벤치 생성 해상도 - 기반 프리셋의 크기 대신 이것으로 그립니다"><select class="param-select quick-select" data-role="res">${BENCH_SIZES.map(size => `<option value="${size}">${size}</option>`).join('')}</select></div></div>
        </div>
        <div data-role="overlay"></div>
      </div>`;
  const $ = role => qs(`[data-role="${role}"]`);
  const baseCard = qs('[data-act="base"]');
  const goBtn = qs('[data-act="go"]');
  const searchInput = $('search');
  $('res').value = st.size;

  async function getJson(url, options) {
    const response = await fetchFn(url, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(String(data?.error || data?.detail || data?.message || `HTTP ${response.status}`));
      error.status = response.status;
      error.data = data;
      throw error;
    }
    return data;
  }
  const sendJson = (url, method, body) => getJson(url, {method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});

  // ---------------------------------------------------------------- 기반
  function currentBase() {
    if (st.base.mode === 'direct') {
      return {label: st.base.directName || '직접 설정(저장 안 함)', params: st.base.direct.params, short: st.base.directName || '직접'};
    }
    const presets = bases?.presets || [];
    const name = st.base.preset && presets.some(p => p.name === st.base.preset) ? st.base.preset : (bases?.current || '');
    const preset = presets.find(p => p.name === name) || null;
    return {label: name || '(프리셋 없음)', params: preset?.params || {}, short: name || '프리셋', preset};
  }

  function renderBaseCard() {
    const base = currentBase();
    baseCard.classList.toggle('is-on', st.baseOpen);
    baseCard.title = `기반 · ${st.base.mode === 'direct' ? '직접 설정' : '프리셋'} · ${base.label}\n${paramsSummary(base.params)}\n누르면 기반 설정을 엽니다`;
    baseCard.setAttribute('aria-label', '프리셋 설정');
    // 단추 오른쪽 미리보기 - '현재 : 직접 설정 모드' / '현재 : <프리셋 이름>'(길면 말줄임 · 전체는 툴팁).
    const cur = $('basecur');
    if (cur) {
      cur.innerHTML = `현재 : <b>${esc(st.base.mode === 'direct' ? '직접 설정 모드' : base.label)}</b>`;
      cur.title = `${base.label} · ${paramsSummary(base.params)}`;
    }   // 앱 툴팁이 title 을 옮기며 첫 값으로 박아 두는 것을 막는다
  }

  async function loadBases() {
    try {
      bases = await getJson(API.bases);
    } catch (error) {
      bases = {current: '', presets: []};
      notify(`프리셋 목록을 읽지 못했습니다: ${error.message}`, 'error');
    }
    try {
      directs = (await getJson(API.direct)).items || [];
    } catch (_) {
      directs = [];
    }
  }

  // ---- 기반 설정 판(사용자 11-20 - NAIA 표준 · 직접 설정은 현재 값을 채워서)
  // 해상도는 여기 없다 - 결과 열의 해상도 드롭다운이 정한다(사용자 11-20).
  const PARAM_ROWS = [['model', 'Model'], ['sampler', 'Sampler'], ['scheduler', 'Scheduler'],
    ['steps', 'Steps'], ['cfg_scale', 'CFG Scale'], ['cfg_rescale', 'CFG Rescale']];
  const sessionParams = () => cleanParams(getSessionParams() || {});
  const presetSummary = name => (getPresetSummaries() || []).find(row => row && row.name === name) || null;
  const directIsEmpty = () => {
    const d = st.base.direct;
    return !d.prefix && !d.postfix && !d.negative_prompt && !Object.keys(d.params || {}).length;
  };

  // PE Quick Preset 과 같은 옵션 속성 - customSelects 가 모델 배지와 '짚으면 미리보기' 를 그린다(inpaintPromptSwap 과 같은 이름).
  function presetOption(preset, selected) {
    const summary = presetSummary(preset.name) || {};
    const clip = (text, limit) => {
      const flat = String(text || '').replace(/\s+/g, ' ').trim();
      return flat.length > limit ? `${flat.slice(0, limit - 3)}...` : flat;
    };
    const attr = (name, value) => ` ${name}="${esc(String(value ?? ''))}"`;
    return '<option' + attr('value', preset.name) + (selected ? ' selected' : '')
      + attr('data-preview-name', preset.name) + attr('data-preview-mode', 'NAI')
      + attr('data-preview-prefix', clip(summary.pre_prompt_preview ?? preset.prefix, 1200))
      + attr('data-preview-postfix', clip(summary.post_prompt_preview ?? preset.postfix, 1200))
      + attr('data-preview-description', clip(summary.description, 300))
      + attr('data-preview-thumbnail', summary.thumbnail_url || '')
      + (summary.model_label ? attr('data-model-label', summary.model_label) + attr('data-model-family', summary.model_family || '')
        + attr('data-model-variant', summary.model_variant || '') : '')
      + `>${esc(preset.name)}${preset.is_current ? ' · 현재' : ''}</option>`;
  }

  // Params 탭과 같은 줄(params-grid · param-row). 프리셋에 없는 값은 메인 화면 세션 값을 보이고 '세션' 표지를 단다.
  function paramRows(params, editable) {
    const ses = sessionParams();
    const own = key => params?.[key];
    const shown = key => own(key) ?? ses[key] ?? '';
    const sesTag = key => (own(key) === undefined ? '<span class="pbw-bs-ses" title="이 값은 메인 화면의 세션 값을 따릅니다">세션</span>' : '');
    const choices = getParamChoices() || {};
    return PARAM_ROWS.map(([key, label]) => {
      let body;
      if (!editable) {
        const text = String(shown(key) === '' ? '-' : shown(key));
        body = `<span class="pbw-bs-val">${esc(text)}${sesTag(key)}</span>`;
      } else if (key === 'model' || key === 'sampler' || key === 'scheduler') {
        const list = [...(choices[key] || [])];
        const cur = String(shown(key) || '');
        if (cur && !list.some(option => option.value === cur)) list.unshift({value: cur, label: cur});
        body = `<select class="param-select" data-param="${key}">${list.map(option =>
          `<option value="${esc(option.value)}"${option.value === cur ? ' selected' : ''}>${esc(option.label)}</option>`).join('')}</select>`;
      } else {
        const step = key === 'steps' ? 1 : (key === 'cfg_scale' ? 0.1 : 0.01);
        body = `<input class="param-input" type="number" step="${step}" data-param="${key}" value="${own(key) ?? ''}" placeholder="${ses[key] ?? ''}">`;
      }
      return `<div class="param-row"><span class="param-label">${label}</span>${body}</div>`;
    }).join('');
  }

  function renderOverlay() {
    const box = $('overlay');
    if (!st.baseOpen) { box.innerHTML = ''; return; }
    const presets = bases?.presets || [];
    const cur = currentBase();
    const head = `<div class="pbw-bs-head"><b>기반 설정</b>
      <span class="pbw-seg" data-role="base-mode"><button type="button" data-mode="preset" class="${st.base.mode === 'preset' ? 'is-on' : ''}">프리셋</button><button type="button" data-mode="direct" class="${st.base.mode === 'direct' ? 'is-on' : ''}">직접 설정</button></span>
      <button type="button" class="pbw-bs-btn" data-act="base-close" style="margin-left:auto">닫기</button></div>`;
    const presetSelect = (role, selected, blank = '') => `<select class="mod-select mod-preset-select" data-role="${role}" data-preview-kind="prompt-preset" data-preset-detail="1">`
      + (blank ? `<option value="">${esc(blank)}</option>` : '') + presets.map(p => presetOption(p, p.name === selected)).join('') + '</select>';
    if (st.base.mode === 'preset') {
      const preset = cur.preset;
      const ro = text => `<div class="pbw-bs-ro">${esc(text || '(없음)')}</div>`;
      box.innerHTML = `<div class="pbw-ov pbw-bs">${head}<div class="pbw-bs-cols"><div>
          <div class="mod-section-label">Quick preset <span class="pbw-bs-note">메인 화면의 현재 프리셋은 그대로 - 이 벤치의 생성에만 씁니다</span></div>
          <div class="pbw-bs-line">${presetSelect('base-preset', cur.label)}
            <button type="button" class="pbw-bs-btn" data-act="to-direct" title="이 프리셋의 값을 직접 설정으로 옮겨 고칩니다">이 값으로 직접 설정 ›</button></div>
          <div class="mod-section-label">Prefix prompt</div>${ro(preset?.prefix)}
          <div class="mod-section-label">Postfix prompt</div>${ro(preset?.postfix)}
        </div><div>
          <div class="mod-section-label">Params</div><div class="params-grid">${paramRows(preset?.params || {}, false)}</div>
          <div class="mod-section-label">Negative</div>${ro(preset?.negative_prompt)}
        </div></div></div>`;
      return;
    }
    const d = st.base.direct;
    const fromSummary = presetSummary(st.base.directFrom);
    const from = st.base.directFrom
      ? `${fromSummary?.model_label ? `<span class="pbw-bs-badge">[${esc(fromSummary.model_label)}]</span> ` : ''}${esc(st.base.directFrom)}`
      : (st.base.directName ? `저장본 '${esc(st.base.directName)}'` : '(빈 값)');
    const named = Boolean(st.base.directName);
    box.innerHTML = `<div class="pbw-ov pbw-bs">${head}<div class="pbw-bs-cols"><div>
        <div class="mod-section-label">저장본</div>
        <div class="pbw-bs-line"><select class="mod-select" data-role="direct-pick"><option value="">(저장 안 함)</option>${directs.map(item =>
          `<option value="${esc(item.name)}"${item.name === st.base.directName ? ' selected' : ''}>${esc(item.name)}</option>`).join('')}</select>
          ${named ? '<button type="button" class="pbw-bs-btn" data-act="direct-save">저장</button>' : ''}
          <button type="button" class="pbw-bs-btn" data-act="direct-save-as">${named ? '다른 이름으로' : '이름 붙여 저장'}</button>
          ${named ? '<button type="button" class="pbw-bs-btn is-danger" data-act="direct-delete">삭제</button>' : ''}</div>
        <div class="pbw-bs-line pbw-bs-src"><span>불러온 값 · ${from}</span>${presetSelect('load-from', '', '다른 프리셋에서 불러오기')}</div>
        <div class="mod-section-label">Prefix prompt</div><textarea class="mod-textarea" data-field="prefix" spellcheck="false">${esc(d.prefix)}</textarea>
        <div class="mod-section-label">Postfix prompt</div><textarea class="mod-textarea" data-field="postfix" spellcheck="false">${esc(d.postfix)}</textarea>
      </div><div>
        <div class="mod-section-label">Params <span class="pbw-bs-note">비운 칸 = 메인 화면 세션 값(흐린 글자)</span></div>
        <div class="params-grid">${paramRows(d.params, true)}</div>
        <div class="mod-section-label">프리셋으로 보내기</div>
        <div class="pbw-bs-line"><select class="mod-select" data-role="export-target"><option value="">새 프리셋</option>${presets.filter(p => !p.is_current).map(p =>
          `<option value="${esc(p.name)}"${p.name === st.exportTarget ? ' selected' : ''}>${esc(p.name)}</option>`).join('')}</select>
          <button type="button" class="pbw-bs-btn" data-act="export">보내기</button></div>
        <div class="pbw-bs-note" style="margin-top:4px">지금 쓰는 프리셋${bases?.current ? `(${esc(bases.current)})` : ''}에는 보낼 수 없습니다.</div>
        <div class="mod-section-label">Negative</div><textarea class="mod-textarea" data-field="negative_prompt" spellcheck="false">${esc(d.negative_prompt)}</textarea>
      </div></div></div>`;
  }

  // 이름 묻기 - 앱 표준 대화 상자(app.js showPromptDialog). 취소 = 빈 글.
  async function askName(message, value = '') {
    if (typeof askText === 'function') {
      const answer = await askText(message, {defaultValue: value, placeholder: '이름'});
      return answer === null || answer === undefined || answer === false ? '' : String(answer).trim();
    }
    return String(win.prompt(message, value) || '').trim();
  }

  async function saveDirectAs() {
    const name = await askName('직접 설정을 저장할 이름', st.base.directName || st.base.directFrom || '');
    if (name) await saveDirect(name);
  }

  async function saveDirect(name) {
    const clean = String(name || '').trim();
    if (!clean) { notify('이름을 적어 주세요', 'error'); return; }
    try {
      await sendJson(API.directOne(clean), 'PUT', {...st.base.direct});
      st.base.directName = clean;
      directs = (await getJson(API.direct)).items || [];
      persist();
      notify(`직접 설정 '${clean}' 을 저장했습니다`, 'success');
    } catch (error) {
      notify(`저장하지 못했습니다: ${error.message}`, 'error');
    }
    renderAllBase();
  }

  async function exportDirect(overwrite = false) {
    const name = String(st.exportTarget || '').trim() || await askName('새 프리셋 이름', '');
    if (!name) return;
    try {
      await sendJson(API.directExport, 'POST', {preset: name, ...st.base.direct, overwrite});
      notify(`프리셋 '${name}' 으로 보냈습니다(현재 프리셋은 그대로)`, 'success');
      await loadBases();
    } catch (error) {
      if (error.status === 409 && error.data?.error === 'exists' && !overwrite) {
        if (win.confirm(`프리셋 '${name}' 이 이미 있습니다. 덮어쓸까요?`)) { st.exportTarget = name; return exportDirect(true); }
        return;
      }
      notify(`보내지 못했습니다: ${error.message}`, 'error');
    }
    renderAllBase();
  }

  function copyPresetToDirect(name) {
    const preset = (bases?.presets || []).find(p => p.name === name);
    if (!preset) { notify('프리셋을 골라 주세요', 'error'); return false; }
    st.base.direct = {
      prefix: String(preset.prefix || ''), postfix: String(preset.postfix || ''),
      negative_prompt: String(preset.negative_prompt || ''), params: {...sessionParams(), ...cleanParams(preset.params)},
    };
    st.base.directName = '';
    st.base.directFrom = preset.name;
    persist();
    return true;
  }

  function renderAllBase() {
    renderBaseCard();
    renderOverlay();
    renderCharMeta();
  }

  // ---------------------------------------------------------------- 왼쪽 열
  // 캐릭터마다 카드 하나 [머리(캐릭터 N · 성별 표지 · ×) + 이름 칸 + 그 캐릭터의 칸 줄]. 캐릭터 밖 칸(2명일 때 2인 이상 자세 ·
  // 배경)은 칸 이름이 곧 카드 제목인 작은 카드로 따로 - 묶음 이름('함께')을 두지 않는다(사용자 11-20).
  // 이름 칸은 캐릭터 수가 바뀔 때만 새로 만든다(자동완성 붙이기 · 치는 중 초점을 지킨다) -
  // 칸 줄은 renderSlots 가, 성별 표지는 renderSubjects 가 제자리만 다시 그린다.
  // 추가 프롬프트 칸 - key = 캐릭터 번호(0 · 1) 또는 'main'. 쓰는 대로 저장한다(생성 때 읽는다).
  function extraBox(key, label, hint, value) {
    return `<div class="pbw-extra${value ? ' has-text' : ''}" data-extra-box="${key}"><span class="pbw-slot-k">${label}</span>
      <textarea class="pbw-text" rows="1" data-extra="${key}" placeholder="${hint}">${esc(value || '')}</textarea>
      <button type="button" class="pbw-slot-x" data-act="extra-x" data-extra-key="${key}" title="비우기" aria-label="추가 프롬프트 비우기">×</button></div>`;
  }

  function renderChars() {
    const box = $('chars');
    const count = st.count;
    // 카드가 곧 칸이다 - 머리 · 글 칸을 누르면(글 칸은 Tab 초점도) 아래 고르기가 그 캐릭터의 캐릭터 검색 · 에셋 · 캐릭터 레퍼런스로.
    box.innerHTML = Array.from({length: count}, (_, i) => `<div class="pbw-ccard" data-ccard="${i}"><div class="pbw-chead" data-act="char-pick" data-index="${i}" title="누르면 아래에서 캐릭터 검색 · 에셋 · 캐릭터 레퍼런스로 고릅니다"><span>캐릭터 ${i + 1}</span><span class="pbw-subj" data-subj="${i}"></span>
        <span class="pbw-gap"></span><span class="pbw-cpick">고르는 중</span>
        ${i > 0 ? `<button type="button" class="pbw-slot-x" data-act="char-remove" data-index="${i}" title="캐릭터 ${i + 1} 빼기" aria-label="캐릭터 ${i + 1} 빼기">×</button>` : ''}</div>
      <textarea class="pbw-text" rows="1" data-name="${i}" placeholder="캐릭터 이름 또는 프롬프트">${esc(st.names[i] || '')}</textarea>
      <div class="pbw-cmeta" data-cmeta="${i}"></div>
      <div data-slots="${i + 1}"></div>
      ${extraBox(i, '추가', '+ 추가 프롬프트 - 이 캐릭터 끝에 더할 태그', st.extras[i])}</div>`).join('') +
      (count < MAX_CHARACTERS ? '<button type="button" class="pbw-addc" data-act="char-add" title="둘째 캐릭터를 넣습니다 - 칸이 캐릭터마다 의상 · 표정으로 바뀌고 1인 자세는 빠집니다">+ 캐릭터 추가</button>' : '') +
      '<div class="pbw-solos" data-slots="0"></div>' +
      `<div class="pbw-ccard is-solo is-extra">${extraBox('main', '추가', '+ 추가 프롬프트 - 메인 프롬프트 끝에 더할 태그', st.extraMain)}</div>`;
    qs('.pbw-left')?.classList.toggle('is-solo', count < 2);
    box.querySelectorAll('textarea[data-name], textarea[data-extra]').forEach(area => {
      if (typeof bindTagAssist === 'function') bindTagAssist(area, {});
    });
    renderSubjects();
    renderCharMeta();
  }

  // 카드 아래 두 줄 - '불러온 것 · DB 블루 아카이브 › mika · 기본' [UC] [×] · REF 줄(그림 · 종류 · S · F · ×) + 경고.
  function renderCharMeta() {
    const total = activeRefs().length;
    const model = baseModel();
    // 경고는 REF 가 있는 첫 카드에만 한 번(REF 는 그림 전체 몫이라 카드마다 되풀이하지 않는다).
    const warnAt = st.refs.slice(0, st.count).findIndex(list => list.length);
    qsa('[data-cmeta]').forEach(box => {
      const i = Number(box.dataset.cmeta);
      const loaded = st.loaded[i];
      const uc = st.ucs[i];
      const refs = st.refs[i] || [];
      let html = '';
      if (loaded || uc) {
        html += `<div class="pbw-cfrom"><span title="${esc(loaded?.label || '')}">${loaded ? `불러온 것 · ${esc(loaded.label)}` : ''}</span>
          ${uc ? `<span class="pbw-uc" title="${esc(`캐릭터 UC(캐릭터 칸에 실립니다): ${uc}`)}">UC</span>` : ''}
          <button type="button" class="pbw-slot-x" data-act="load-x" data-index="${i}" title="불러온 표시 · UC 를 지웁니다(글은 그대로)" aria-label="불러온 표시 지우기">×</button></div>`;
      }
      if (refs.length) {
        html += `<div class="pbw-crefs"><span class="pbw-crefs-k">REF</span>${refs.map((ref, j) => {
          const tip = `${ref.label || ''} · ${ref.reference_type} · Strength ${ref.strength} · Fidelity ${ref.fidelity}${ref.auto ? ' · 에셋 그림' : ''}`;
          return `<span class="pbw-ref" title="${esc(tip)}">${ref.thumb ? `<img src="${esc(ref.thumb)}" alt="">` : ''}<span>${REF_TYPE_SHORT[ref.reference_type] || ''} · S ${ref.strength} · F ${ref.fidelity}</span>
            <button type="button" class="pbw-slot-x" data-act="ref-x" data-index="${i}" data-ref="${j}" title="이 REF 빼기" aria-label="REF 빼기">×</button></span>`;
        }).join('')}</div>`;
        const warns = [];
        if (i !== warnAt) { box.innerHTML = html; return; }
        if (st.count > 1) warns.push('레퍼런스는 그림 전체에 걸립니다(NAI 제약) - 캐릭터별로 나뉘지 않습니다');
        if (total > MAX_REFS) warns.push(`레퍼런스는 한 번에 ${MAX_REFS}장까지 - 지금 ${total}장이라 생성이 막힙니다`);
        if (crUnsupported(model)) warns.push(`기반 모델(${model})은 Character Reference 를 못 씁니다 - 생성이 막힙니다`);
        html += warns.map(text => `<div class="pbw-cwarn">${esc(text)}</div>`).join('');
      }
      box.innerHTML = html;
    });
  }

  // 기반 모델 - 기반에 없으면 세션 값(서버도 같은 순서로 정한다).
  function baseModel() { return String(currentBase().params?.model || sessionParams().model || ''); }

  // 캐릭터를 어디에 싣나 - 고르지 않는다(사용자 11-20: "NAI 는 전부 캐릭터칸, 나머지는 메인으로 자동").
  // NAI 라도 V3(NAID3 · nai-diffusion-3) 는 캐릭터 칸이 없어 메인으로(서버가 V3 + 캐릭터 칸을 409 로 막는다).
  function autoTarget() {
    if (String(getApiMode() || 'NAI').toUpperCase() !== 'NAI') return 'main';
    return /naid3|diffusion-3|furry-3/i.test(baseModel()) ? 'main' : 'char';
  }

  // 캐릭터 글 칸을 바꾼다(불러오기) - 치는 것과 같게 저장 · 성별 다시 묻기.
  function setCharText(i, text) {
    st.names[i] = String(text || '');
    const area = qs(`textarea[data-name="${i}"]`);
    if (area) area.value = st.names[i];
    refreshSubject(i, 0);
  }

  // 성별 표지: 'girl · 자동'(이름 사전) · 'boy · 태그'(글에 쓴 1boy) · 'girl · 기본'(모름 - girl 로 본다).
  function renderSubjects() {
    qsa('[data-subj]').forEach(el => {
      const row = st.subjects[Number(el.dataset.subj)] || {};
      const gender = row.gender || 'girl';
      const how = row.source === 'character' ? '자동' : row.source === 'tags' ? '태그' : '기본';
      el.textContent = `${gender} · ${how}`;
      el.classList.toggle('is-guess', !row.source);
      el.title = row.source === 'character' ? `캐릭터 사전: ${row.name} -> ${gender}`
        : row.source === 'tags' ? `글에 쓴 인원 태그 -> ${gender}`
          : '이름으로 성별을 몰라 girl 로 봅니다 - 글에 1boy 를 쓰면 boy 가 됩니다';
    });
  }

  const subjectTimers = [];
  const subjectSerial = [];
  function refreshSubject(i, delay = 350) {
    win.clearTimeout(subjectTimers[i]);
    subjectTimers[i] = win.setTimeout(async () => {
      const text = String(st.names[i] || '').trim();
      const serial = (subjectSerial[i] = (subjectSerial[i] || 0) + 1);
      let row = {gender: '', source: '', name: ''};
      if (text) {
        try { row = await getJson(API.subject(text)); } catch (_) { /* 모르면 girl 로 본다 */ }
      }
      if (serial !== subjectSerial[i]) return;   // 그사이 다시 쳤다
      st.subjects[i] = {gender: String(row.gender || ''), source: String(row.source || ''), name: String(row.name || '')};
      renderSubjects();
      renderSlots();      // 2인 이상 자세의 성별 어긋남 표지
    }, delay);
  }

  // 캐릭터 수 바꾸기. 칸 id 가 같은 칸(o1 · e1 · scene)은 고른 것 · 비교 · 탐색 자리를 그대로 둔다(풀이 같다).
  function setCount(count) {
    st.count = normalizeCast({count}).count;
    if (st.count < 2) {
      st.names[1] = '';
      st.subjects[1] = {gender: '', source: '', name: ''};
      st.ucs[1] = '';
      st.loaded[1] = null;
      st.refs[1] = [];
    }
    const keep = new Set(slots().map(slot => slot.id));
    for (const bag of [st.picks, st.chk, st.views]) for (const id of Object.keys(bag)) if (!keep.has(id)) delete bag[id];
    if (st.axis && !keep.has(st.axis)) st.axis = null;
    if (st.memo && !keep.has(st.memo.slotId)) { st.memo = null; st.note = ''; }
    st.pick = null;
    if (!keep.has(st.cur) && charIndex() < 0) st.cur = 'o1';
    persist();
    renderChars();
    renderAll();
  }

  function renderSlots() {
    const list = slots();
    const slotHtml = slot => {
      const pick = st.picks[slot.id];
      const axis = st.axis === slot.id;
      const cur = slot.id === st.cur;
      const label = slot.kind === 'link' ? '자세' : esc(KIND_LABELS[slot.kind]);
      let marks = slot.kind === 'link' ? '<span class="pbw-l2">2인 이상</span>' : '';
      if (slot.kind === 'link' && pick?.tags?.length && LINK_POOLS[pick.pool]) {
        marks += `<span class="pbw-lpool" title="${esc(pick.pool)} 세트">${LINK_POOLS[pick.pool].badge}</span>`;
        // 캐릭터 1명이면 인원 태그는 이 세트의 풀을 따른다 - 캐릭터 성별과 어긋나면 알려 준다.
        if (st.count === 1 && linkMismatch(st.subjects[0]?.gender, pick.pool)) {
          marks += `<span class="pbw-warn" title="캐릭터 1 은 ${esc(st.subjects[0]?.gender || 'girl')} 인데 ${LINK_POOLS[pick.pool].badge} 세트 - 맨 앞 인원 태그는 세트를 따라 '${LINK_POOLS[pick.pool].head}'">성별 확인</span>`;
        }
      }
      if (axis) marks += `<span class="pbw-chip pbw-cmp">비교 ${axisSets().length}</span>`;
      const chips = pick?.tags?.length
        ? pick.tags.map(tag => `<span class="pbw-chip" data-chip="${esc(tag)}" data-from="${slot.id}" title="${slot.kind === 'outfit' ? '관련 의상 보기' : '이 태그로 찾기'}">${esc(tag)}</span>`).join('')
          + (pick.add || []).map(tag => `<span class="pbw-chip pbw-add" title="이 세트와 거의 늘 함께 나오는 태그 - 메인 프롬프트에 함께 싣는다">+${esc(tag)}</span>`).join('')
        : `<span class="pbw-slot-empty">${cur ? '고르는 중 →' : '+ 고르기'}</span>`;
      const clear = pick?.tags?.length || axis
        ? `<button type="button" class="pbw-slot-x" data-clear="${slot.id}" title="비우기" aria-label="비우기">×</button>` : '<span></span>';
      return `<div class="pbw-slot${cur ? ' is-cur' : ''}${axis ? ' is-axis' : ''}" data-slot="${slot.id}">
        <span class="pbw-slot-k">${label}</span><span class="pbw-slot-v">${marks}${chips}</span>${clear}</div>`;
    };
    qsa('[data-ccard]').forEach(card => {
      const picking = charIndex() === Number(card.dataset.ccard);
      card.classList.toggle('is-picking', picking);
      const area = card.querySelector('textarea[data-name]');
      const rows = picking ? 4 : 1;
      // 손으로 늘린 높이(style.height)는 고르기가 바뀔 때 걷는다 - 줄 수 규칙이 다시 보이게.
      if (area && area.rows !== rows) { area.rows = rows; area.style.height = ''; }
    });
    qsa('[data-slots]').forEach(holder => {
      const owner = Number(holder.dataset.slots);
      const mine = list.filter(slot => slot.owner === owner);
      // 캐릭터 밖 칸은 칸마다 작은 카드(칸 이름 = 카드 제목).
      holder.innerHTML = owner === 0
        ? mine.map(slot => `<div class="pbw-ccard is-solo${slot.kind === 'link' ? ' is-link' : ''}">${slotHtml(slot)}</div>`).join('')
        : mine.map(slotHtml).join('');
    });
  }

  function renderLeftControls() {
    const n = st.axis ? axisSets().length : 1;
    goBtn.textContent = running() ? '■ 중지' : `▶ ${n}장 생성`;
    goBtn.title = running() ? '아직 대기 중인 생성을 큐에서 뺍니다(그리는 중인 한 장은 끝까지 갑니다)' : '기반 + 고른 칸으로 생성합니다';
  }

  // ---------------------------------------------------------------- 탐색
  const setTotal = seeds => (seeds || []).reduce((sum, seed) => sum + Number(seed.sets || 0), 0);
  // 시드 이름 칸 = 한글 + 작은 영문 태그(한글이 없으면 영문만).
  const seedLabel = seed => (seed.ko && seed.ko !== seed.seed
    ? `<span>${esc(seed.ko)}<small>${esc(seed.seed)}</small></span>`
    : `<span>${esc(seed.seed)}</span>`);

  async function catalogOf(kind, pool) {
    const key = `${kind}|${pool}`;
    if (!catalogCache.has(key)) catalogCache.set(key, getJson(API.catalog(kind, pool)).catch(error => { catalogCache.delete(key); throw error; }));
    return catalogCache.get(key);
  }
  async function setsOf(kind, pool, seed) {
    const key = `${kind}|${pool}|${seed}`;
    if (!setsCache.has(key)) setsCache.set(key, getJson(API.sets(kind, pool, seed)).then(data => data.sets || []).catch(error => { setsCache.delete(key); throw error; }));
    return setsCache.get(key);
  }

  function renderNote() {
    $('note').innerHTML = st.note
      ? `<div class="pbw-note"><span>${st.note}</span>${st.memo ? '<a data-act="undo">되돌리기</a>' : ''}<a data-act="note-x" style="margin-left:auto">×</a></div>` : '';
  }

  function renderBand() {
    const box = $('band');
    const s = thumbStatus;
    if (!s || s.installed) { box.innerHTML = ''; return; }
    const busy = s.downloading;
    const pct = Number(s.progress?.percent ?? s.progress ?? 0);
    box.innerHTML = `<div class="pbw-band"><span>썸네일 팩이 없어 그림이 검은 칸으로 보입니다(약 414MB).</span>
      ${busy ? `<span class="pbw-dim">받는 중 ${Number.isFinite(pct) ? Math.round(pct) + '%' : ''}</span>` : '<button type="button" class="pbw-btn" data-act="thumb-dl">받기</button>'}</div>`;
  }

  async function refreshThumbStatus() {
    try { thumbStatus = await getJson(API.thumbStatus); } catch (_) { thumbStatus = null; }
    renderBand();
    if (thumbStatus?.downloading && active) win.setTimeout(refreshThumbStatus, 2000);
    else if (thumbStatus?.installed) { catalogCache.clear(); setsCache.clear(); }
  }

  // 기본 풀이 아닌 세트에 작은 표지(목록은 여성 · girl_boy 세트가 먼저 온다).
  const POOL_BADGES = {male: '남', girl_girl: '여여', boy_boy: '남남'};
  function cardHtml(slot, set, {hit = false} = {}) {
    const selected = st.picks[slot.id]?.id === set.id;
    const badge = POOL_BADGES[set.pool] ? `<span class="pbw-pool" title="${esc(set.pool)} 세트">${POOL_BADGES[set.pool]}</span>` : '';
    const checked = st.chk[slot.id]?.has(set.id);
    const tall = slot.kind === 'outfit' ? ' is-tall' : '';
    const picture = set.has_thumb
      ? `<img class="pbw-th${tall}" loading="lazy" src="${API.thumb(set.key)}" alt="">`
      : `<div class="pbw-th${tall} pbw-none">미생성</div>`;
    return `<div class="pbw-card${selected ? ' is-sel' : ''}${hit ? ' is-hit' : ''}" data-set="${esc(set.id)}" title="${esc((set.tags || []).join(', '))}">
      <span class="pbw-ck${checked ? ' is-on' : ''}" data-check="${esc(set.id)}" role="checkbox" aria-checked="${checked ? 'true' : 'false'}" title="비교에 넣기">${checked ? '✓' : ''}</span>
      ${badge}${picture}<div class="pbw-cap">${esc((set.tags || []).join(', '))}${(set.add || []).length ? ` <span class="pbw-cap-add" title="메인 프롬프트에 함께 싣는 태그">+${esc(set.add.join(', +'))}</span>` : ''}</div></div>`;
  }

  // 지금 그리드에 보이는 세트(id -> 세트) - 카드 누르기 · 체크가 세트 요약을 찾는다.
  let shownSets = new Map();

  // 캐릭터 카드를 고른다(머리 · 글 칸 · Tab) - 이미 고르는 중이면 아무것도 다시 그리지 않는다(치는 중 초점 · 스크롤을 지킨다).
  function pickChar(i) {
    const id = `char${i + 1}`;
    if (!(i >= 0 && i < st.count) || st.cur === id) return;
    st.cur = id;
    st.baseOpen = false;
    renderSlots();
    renderOverlay();
    renderBaseCard();
    countSources();
    void renderExplorer();
  }

  async function renderExplorer() {
    if (/^char[12]$/.test(st.cur)) {
      if (charIndex() >= 0) { await renderCharExplorer(); return; }
      st.cur = 'o1';
    }
    const slot = slotById(st.cur) || slots()[0];
    st.cur = slot.id;
    const view = viewOf(slot.id);
    searchInput.placeholder = '태그 · 한국어 이름 검색';
    $('ex-tools').innerHTML = '';
    const owner = st.count > 1 && slot.owner > 0 ? `<span class="pbw-ex-own">캐릭터 ${slot.owner} ›</span> ` : '';
    $('ex-title').innerHTML = `${owner}${esc(KIND_LABELS[slot.kind])} 고르기`;
    $('ex-head').classList.remove('is-char');
    $('ex-src').innerHTML = '';
    const ctx = $('ex-ctx');
    ctx.textContent = '';
    if (searchInput.value !== view.q && doc.activeElement !== searchInput) searchInput.value = view.q;
    const cats = $('cats');
    const seedsBox = $('seeds');
    const grid = $('grid');
    const serial = ++searchSerial;
    $('ex2').classList.toggle('is-related', view.mode === 'related');

    if (view.mode === 'related') {
      cats.innerHTML = `<button type="button" class="pbw-cat is-on" data-act="related-back">← 분류로</button><span class="pbw-dim pbw-sm">'${esc(view.relatedTag)}' 관련</span>`;
      ctx.textContent = `'${view.relatedTag}' 관련 의상`;
      seedsBox.innerHTML = '';
      const data = view.related;
      if (!data) { grid.innerHTML = '<div class="pbw-empty">찾는 중…</div>'; return; }
      shownSets = new Map();
      const sections = (data.groups || []).filter(group => (group.sets || []).length);
      grid.innerHTML = sections.length ? sections.map(group => {
        group.sets.forEach(set => shownSets.set(set.id, set));
        return `<div class="pbw-sec">${esc(group.label)} · ${group.sets.length}</div><div class="pbw-grid">${group.sets.map(set => cardHtml(slot, set)).join('')}</div>`;
      }).join('') : '<div class="pbw-empty">관련 의상이 없습니다</div>';
      return;
    }

    let catalog;
    try {
      catalog = await catalogOf(slot.kind, slot.pool);
    } catch (error) {
      if (serial !== searchSerial) return;
      grid.innerHTML = `<div class="pbw-empty">목록을 읽지 못했습니다: ${esc(error.message)}</div>`;
      return;
    }
    if (serial !== searchSerial) return;
    // 대분류 차례 · 이름은 서버의 탐색 분류표 그대로(갈래 다섯 모두).
    const groups = catalog.groups || [];
    if (!view.cat || !groups.some(group => group.slot === view.cat)) view.cat = groups[0]?.slot || '';
    const curGroup = groups.find(item => item.slot === view.cat);
    if (view.sub && !(curGroup?.subs || []).some(sub => sub.name === view.sub)) view.sub = '';
    // 따로 뺀 풀의 대분류(2인 자세 '남남' - 사용자 11-20)는 그 풀로 세트를 받는다. 검색도 이 풀을 따른다.
    if (view.mode === 'browse') view.pool = curGroup?.pool || '';
    const pool = view.pool || slot.pool;
    // 고른 대분류(둘러보기 중) 아래에 소분류를 들여 나열한다 - 소분류가 둘 이상일 때만(하나뿐이면 대분류와 같다).
    const subTree = group => (view.mode === 'browse' && group.slot === view.cat && (group.subs || []).length > 1
      ? `<div class="pbw-csubs">${group.subs.map(sub => `<button type="button" class="pbw-csub${sub.name === view.sub ? ' is-on' : ''}" data-csub="${esc(sub.name)}"><span>${esc(sub.name)}</span><small>${setTotal(sub.seeds)}</small></button>`).join('')}</div>`
      : '');
    cats.innerHTML = groups.map(group => `<button type="button" class="pbw-cat${view.mode === 'browse' && group.slot === view.cat ? ' is-on' : ''}" data-cat="${esc(group.slot)}"><span>${esc(group.label || group.slot)}</span><small>${setTotal(group.seeds)}</small></button>${subTree(group)}`).join('');

    let seeds;
    if (view.mode === 'search') {
      seeds = view.hits;
      seedsBox.innerHTML = seeds.length
        ? `<div class="pbw-dim pbw-sm" style="padding:2px 5px">검색 '${esc(view.q)}' · ${seeds.length}</div>` + seeds.map(hit => `<div class="pbw-seed${hit.seed === view.seed ? ' is-on' : ''}" data-seed="${esc(hit.seed)}" data-pbw-tip="${esc(hit.seed)}" data-pbw-tip-src="검색" data-pbw-tip-sets="${hit.count}"${hit.matched === hit.seed ? '' : ` data-pbw-tip-hint="찾은 태그 ${esc(hit.matched)}"`}>${seedLabel(hit)}<span>${hit.count}</span></div>`).join('')
        : `<div class="pbw-empty">'${esc(view.q)}' 결과 없음</div>`;
    } else {
      const group = curGroup;
      const sub = view.sub ? group.subs.find(item => item.name === view.sub) : null;
      seeds = sub ? sub.seeds : (group?.seeds || []);
      // 소분류 머리글 + 오른쪽 수 = 고를 수 있는 세트 수(사용자 11-20 - 게시물 수는 툴팁으로).
      // 이름 = 한글 + 옆에 작은 영문 태그(사용자 11-20). 사전에 이름이 없으면 영문만.
      // 줄에 올리면 태그 카드(이름 · 분류 경로 · 한글 설명 · 세트 수 · 게시물 · 썸네일 - 사용자 11-20).
      const subOf = new Map();
      for (const item of group?.subs || []) for (const one of item.seeds) if (!subOf.has(one.seed)) subOf.set(one.seed, item.name);
      const row = seed => {
        const where = [group?.label, subOf.get(seed.seed)].filter((name, i, all) => name && all.indexOf(name) === i).join(' › ');
        return `<div class="pbw-seed${seed.seed === view.seed ? ' is-on' : ''}" data-seed="${esc(seed.seed)}" data-pbw-tip="${esc(seed.seed)}" data-pbw-tip-src="${esc(where)}" data-pbw-tip-sets="${seed.sets}"${seed.posts != null ? ` data-pbw-tip-posts="${Number(seed.posts)}"` : ''}>${seedLabel(seed)}<span>${seed.sets}</span></div>`;
      };
      // 맨 위 줄 = 대분류(또는 고른 소분류)를 누른 상태 - 그 안의 세트를 다 나열(사용자 11-20 "첫 그룹을 고르지 말고 전체").
      const all = `<div class="pbw-seed is-all${view.seed ? '' : ' is-on'}" data-seed="" title="이 분류의 세트를 모두 나열합니다"><span>${sub ? esc(sub.name) : '전체'}</span><span>${setTotal(seeds)}</span></div>`;
      seedsBox.innerHTML = all + (sub
        ? seeds.map(row).join('')
        : group?.subs
          ? group.subs.map(item => `<div class="pbw-sub">${esc(item.name)}</div>${item.seeds.map(row).join('')}`).join('')
          : seeds.map(row).join(''));
      if (view.seed && !seeds.some(seed => seed.seed === view.seed)) view.seed = '';
      const label = sub ? `${group?.label || ''} › ${sub.name}` : `${group?.label || ''} 전체`;
      if (!view.seed) { await renderCategorySets(slot, pool, label, seeds, serial); return; }
    }
    if (!view.seed || !seeds.some(seed => seed.seed === view.seed)) view.seed = seeds[0]?.seed || '';
    seedsBox.querySelectorAll('.pbw-seed').forEach(row => row.classList.toggle('is-on', row.dataset.seed === view.seed));
    if (!view.seed) { grid.innerHTML = ''; shownSets = new Map(); return; }
    // 맥락 줄: '· 잠자기 sleeping' (세트 수는 세트를 받은 뒤)
    const curSeed = seeds.find(seed => seed.seed === view.seed);
    const seedName = curSeed?.ko && curSeed.ko !== view.seed ? `${curSeed.ko} ${view.seed}` : view.seed;
    ctx.textContent = seedName;
    let sets;
    try {
      sets = await setsOf(slot.kind, pool, view.seed);
    } catch (error) {
      if (serial !== searchSerial) return;
      grid.innerHTML = `<div class="pbw-empty">세트를 읽지 못했습니다: ${esc(error.message)}</div>`;
      return;
    }
    if (serial !== searchSerial) return;
    shownSets = new Map(sets.map(set => [set.id, set]));
    ctx.textContent = `${seedName} · ${sets.length}세트`;
    grid.innerHTML = `<div class="pbw-grid">${sets.map(set => cardHtml(slot, set, {hit: set.id === view.hitSet})).join('')}</div>`;
  }

  // 대분류 전체 - 시드마다 세트를 받아(시드 하나 고를 때와 같은 캐시) 시드별 머리글 아래 나열한다.
  async function renderCategorySets(slot, pool, label, seeds, serial) {
    const ctx = $('ex-ctx');
    const grid = $('grid');
    ctx.textContent = label;
    grid.innerHTML = '<div class="pbw-empty">불러오는 중…</div>';
    let lists;
    try {
      lists = await Promise.all(seeds.map(seed => setsOf(slot.kind, pool, seed.seed)));
    } catch (error) {
      if (serial !== searchSerial) return;
      grid.innerHTML = `<div class="pbw-empty">세트를 읽지 못했습니다: ${esc(error.message)}</div>`;
      return;
    }
    if (serial !== searchSerial) return;
    shownSets = new Map();
    let total = 0;
    grid.innerHTML = seeds.map((seed, i) => {
      const sets = lists[i] || [];
      if (!sets.length) return '';
      total += sets.length;
      sets.forEach(set => shownSets.set(set.id, set));
      const en = seed.ko && seed.ko !== seed.seed ? `<small>${esc(seed.seed)}</small>` : '';
      return `<div class="pbw-sec">${esc(seed.ko || seed.seed)}${en} · ${sets.length}</div><div class="pbw-grid">${sets.map(set => cardHtml(slot, set)).join('')}</div>`;
    }).join('') || '<div class="pbw-empty">세트가 없습니다</div>';
    ctx.textContent = `${label} · ${total}세트`;
  }

  async function runSearch(q) {
    if (charIndex() >= 0) {
      const box = st.cv[st.cv.src];
      box.q = q;
      await renderExplorer();
      return;
    }
    const slot = slotById(st.cur);
    if (!slot) return;
    const view = viewOf(slot.id);
    view.q = q;
    if (!q.trim()) { view.mode = 'browse'; view.hits = []; view.hitSet = ''; await renderExplorer(); return; }
    // 연결 갈래는 서버 kind 가 'link'
    let rows = [];
    try {
      rows = await getJson(API.search(q.trim(), slot.kind));
    } catch (error) {
      notify(`검색하지 못했습니다: ${error.message}`, 'error');
    }
    // 따로 뺀 풀(남남)은 그 대분류를 보고 있을 때만 찾는다 - 다른 대분류에선 빼고, 거기선 그 풀만(사용자 11-20).
    let apart = new Set();
    try { apart = new Set(((await catalogOf(slot.kind, slot.pool)).groups || []).map(g => g.pool).filter(Boolean)); } catch (_) {}
    if (viewOf(slot.id).q !== q) return;      // 그사이 다시 쳤다
    const bySeed = new Map();
    for (const row of Array.isArray(rows) ? rows : []) {
      if (slot.pool && row.pool !== slot.pool) continue;   // 칸 pool '' = 모든 풀
      if (view.pool ? row.pool !== view.pool : apart.has(row.pool)) continue;
      const hit = bySeed.get(row.seed) || {seed: row.seed, ko: row.ko || '', matched: row.matched, count: 0, first: row.set_id};
      hit.count += 1;
      bySeed.set(row.seed, hit);
    }
    view.mode = 'search';
    view.hits = [...bySeed.values()];
    view.seed = view.hits[0]?.seed || '';
    view.hitSet = view.hits[0]?.first || '';
    await renderExplorer();
  }

  async function openRelated(slotId, tag) {
    const slot = slotById(slotId);
    if (!slot) return;
    st.cur = slotId;
    const view = viewOf(slotId);
    if (slot.kind !== 'outfit') {
      searchInput.value = tag;
      renderSlots();
      await runSearch(tag);
      return;
    }
    view.mode = 'related';
    view.relatedTag = tag;
    view.related = null;
    renderSlots();
    void renderExplorer();
    const ctx = (st.picks[slotId]?.tags || []).filter(t => t !== tag).join('|');
    try {
      // 관련 의상은 풀마다 따로 센다 - 그 칸에 든 세트의 풀(옛 저장값엔 없다 -> female).
      view.related = await getJson(API.related(tag, st.picks[slotId]?.pool || slot.pool || 'female', ctx));
    } catch (error) {
      view.related = {groups: []};
      notify(error.status === 404 ? `'${tag}' 의 관련 의상 정보가 없습니다` : `관련 의상을 읽지 못했습니다: ${error.message}`, error.status === 404 ? 'info' : 'error');
    }
    if (st.cur === slotId && view.mode === 'related') await renderExplorer();
  }

  // ---------------------------------------------------------------- 캐릭터 고르기(DB · 에셋 · REF)
  const dbGroupsCache = new Map();     // 성별 -> 그룹 목록(All · original · etc · 작품)
  const dbListCache = new Map();       // 그룹|검색|성별 -> 캐릭터 줄
  let assetListPromise = null;
  let refTotal = null;
  let dbRows = [];                     // 지금 그림 칸의 캐릭터(카드 누르기가 찾는다)
  let dbGroupKo = {};
  let assetRows = [];
  let refRows = new Map();             // file_hash -> 보관함 항목

  const cached = (map, key, load) => {
    if (!map.has(key)) {
      if (map.size > 40) map.delete(map.keys().next().value);
      map.set(key, load().catch(error => { map.delete(key); throw error; }));
    }
    return map.get(key);
  };
  const dbGroupLabel = key => (key === '__ALL__' ? '전체' : key === GROUP_ETC ? 'etc' : (dbGroupKo[key] || key));
  // 'mika (blue archive)' 처럼 작품 이름이 붙은 캐릭터는 이름만 - 툴팁에 전체 이름.
  const dbShortName = (character, group) => {
    const name = String(character || '').replace(/_/g, ' ');
    const tail = ` (${String(group || '')})`.toLowerCase();
    return group && name.toLowerCase().endsWith(tail) && name.length > tail.length ? name.slice(0, -tail.length) : name;
  };
  const assetName = row => row.display_name || `(이름 없음) ${String(row.id).slice(0, 8)}`;

  async function dbGroupsOf(gender) {
    return cached(dbGroupsCache, gender, async () => {
      const data = await getJson(API.dbGroups(gender));
      const items = Array.isArray(data.items) ? data.items : [];
      items.forEach(g => { if (g?.ko) dbGroupKo[g.key] = String(g.ko); });
      // Characters 창과 같은 차례 - All · original · etc(1명짜리 작품) · 작품(인원 순). 고른 성별이 0명인 작품은 감춘다.
      const size = g => Number(g.total ?? g.count ?? 0);
      const all = items.filter(g => g.key === '__ALL__');
      const pinned = items.filter(g => g.key === 'original');
      const singles = items.filter(g => g.key !== '__ALL__' && g.key !== 'original' && size(g) === 1);
      const etcCount = singles.reduce((sum, g) => sum + Number(g.count || 0), 0);
      const rest = items.filter(g => g.key !== '__ALL__' && g.key !== 'original' && size(g) > 1 && Number(g.count || 0) > 0)
        .sort((a, b) => Number(b.count || 0) - Number(a.count || 0));
      return [...all, ...pinned, ...(singles.length ? [{key: GROUP_ETC, count: etcCount}] : []), ...rest];
    });
  }
  function assetListOf(fresh = false) {
    if (fresh || !assetListPromise) {
      assetListPromise = getJson(API.assetList).then(data => (Array.isArray(data.characters) ? data.characters : []))
        .catch(error => { assetListPromise = null; throw error; });
    }
    return assetListPromise;
  }

  // 출처 단추의 수(에셋 N · REF N) - 처음 열 때 한 번 센다.
  function countSources() {
    assetListOf().then(rows => { assetRows = rows; renderCharTitle(); }).catch(() => {});
    if (refTotal === null) {
      getJson(API.refLibrary('all', '', '')).then(data => { refTotal = Number(data.total || 0); renderCharTitle(); }).catch(() => {});
    }
  }

  function renderCharTitle() {
    const i = charIndex();
    if (i < 0) return;
    const n = value => (value === null || value === undefined ? '' : ` ${value}`);
    const srcs = [['db', '캐릭터 검색', 'Characters 창의 캐릭터 DB - 옷 태그는 뺍니다'],
      ['asset', `에셋${n(assetListPromise ? assetRows.length : null)}`, 'Assets 의 캐릭터 에셋 - 프롬프트 + UC (+ 그림을 REF 로)'],
      ['ref', `캐릭터 레퍼런스${n(refTotal)}`, 'REF 보관함의 그림 - 이 벤치 생성에만 실립니다']];
    $('ex-head').classList.add('is-char');
    $('ex-title').textContent = `캐릭터 ${i + 1} 고르기`;
    $('ex-src').innerHTML = `<span class="pbw-seg">${srcs.map(([key, label, tip]) => `<button type="button" class="${st.cv.src === key ? 'is-on' : ''}" data-csrc="${key}" title="${esc(tip)}">${esc(label)}</button>`).join('')}</span>`;
  }

  async function renderCharExplorer() {
    const i = charIndex();
    const src = st.cv.src;
    const serial = ++searchSerial;
    shownSets = new Map();
    $('ex2').classList.remove('is-related');      // DB 만 한 열(작품)로 쓴다 - 아래에서 다시 붙인다
    renderCharTitle();
    searchInput.placeholder = src === 'db' ? '이름 · 한글 · 초성 · work:작품' : src === 'asset' ? '에셋 이름' : '보관함 이름';
    if (doc.activeElement !== searchInput && searchInput.value !== st.cv[src].q) searchInput.value = st.cv[src].q;
    const cats = $('cats');
    const seedsBox = $('seeds');
    const grid = $('grid');
    const ctx = $('ex-ctx');
    const tools = $('ex-tools');
    tools.innerHTML = '';
    const fail = error => { if (serial === searchSerial) grid.innerHTML = `<div class="pbw-empty">읽지 못했습니다: ${esc(error.message)}</div>`; };

    // DB = 왼쪽은 작품(한 열 - 성별 · 작품), 그림 칸은 캐릭터 한 명당 카드 한 장. 누르면 바로 그 캐릭터 칸에(옷 태그는 뺀다).
    // 변형은 따로 고르지 않는다 - DB 에서 'reisa (magical)' 처럼 제 이름으로 따로 있어 검색으로 찾는다(사용자 11-20).
    if (src === 'db') {
      const db = st.cv.db;
      $('ex2').classList.add('is-related');
      seedsBox.innerHTML = '';
      let groups;
      try { groups = await dbGroupsOf(db.gender); } catch (error) { fail(error); return; }
      if (serial !== searchSerial) return;
      if (!groups.some(g => g.key === db.group)) db.group = '__ALL__';
      const genders = [['', '전체'], ['girl', '여'], ['boy', '남']];
      cats.innerHTML = `<div class="pbw-cfilter"><span class="pbw-seg">${genders.map(([g, label]) => `<button type="button" class="${db.gender === g ? 'is-on' : ''}" data-cgender="${g}">${label}</button>`).join('')}</span>
        <button type="button" class="pbw-fav${db.fav ? ' is-on' : ''}" data-cfav title="즐겨찾기만(Characters 창의 ★)">★</button></div>` +
        groups.map(g => `<button type="button" class="pbw-cat${g.key === db.group ? ' is-on' : ''}" data-cgroup="${esc(g.key)}" title="${esc(g.key)}"><span>${esc(dbGroupLabel(g.key))}</span><small>${formatPosts(g.count)}</small></button>`).join('');
      const q = db.q.trim();
      ctx.textContent = '찾는 중…';
      let rows;
      try {
        rows = await cached(dbListCache, `${db.group}|${q}|${db.gender}|${db.fav ? 1 : 0}`, () => getJson(API.dbList(db.group, q, db.gender, db.fav)).then(data => ({
          rows: Array.isArray(data.items) ? data.items : [], total: Number(data.total || 0)})));
      } catch (error) { fail(error); return; }
      if (serial !== searchSerial) return;
      dbRows = rows.rows;
      // 여러 작품이 섞인 목록(전체 · etc · 검색)은 이름 옆에 작품을 흐리게 - 같은 이름(hoshino ai)을 가른다.
      const mixed = db.group === '__ALL__' || db.group === GROUP_ETC || Boolean(q);
      const shown = rows.total > dbRows.length ? `${dbRows.length} / ${rows.total.toLocaleString()}명 - 검색으로 좁히세요` : `${rows.total.toLocaleString()}명`;
      ctx.textContent = `${q ? `${db.group === '__ALL__' ? '' : `${dbGroupLabel(db.group)} 안 `}검색 '${q}'` : dbGroupLabel(db.group)} · ${shown} · 누르면 캐릭터 ${i + 1} 칸에(옷 태그는 뺍니다)`;
      const mine = st.loaded[i]?.src === 'db' ? st.loaded[i].key : '';
      grid.innerHTML = dbRows.length ? `<div class="pbw-grid is-3">${dbRows.map((row, k) => {
        const name = dbShortName(row.character, row.group);
        const picture = row.has_thumbnail && row.thumbnail_url
          ? `<img class="pbw-th is-tall" loading="lazy" src="${esc(row.thumbnail_url)}" alt="">`
          : '<div class="pbw-th is-tall pbw-none">썸네일 없음</div>';
        return `<div class="pbw-card${mine === `${row.group}|${row.character}` ? ' is-sel' : ''}" data-cchar="${k}" data-zt="${esc(`${row.character} · ${dbGroupLabel(row.group)}`)}" title="${esc(`${row.character} · ${dbGroupLabel(row.group)} · 데이터 ${Number(row.count || 0).toLocaleString()}장 - 누르면 캐릭터 ${i + 1} 칸에`)}">
          ${picture}<div class="pbw-cap">${esc(name)}${mixed ? ` <span class="pbw-dim">${esc(dbGroupLabel(row.group))}</span>` : ''} · ${formatPosts(row.count)}</div></div>`;
      }).join('')}</div>` : `<div class="pbw-empty">${q ? `'${esc(q)}' 결과 없음` : db.fav ? '즐겨찾기한 캐릭터가 없습니다' : '캐릭터가 없습니다'}${
        q && db.group !== '__ALL__' ? `<br><button type="button" class="pbw-btn" data-cgroup="__ALL__" style="margin-top:8px">전체 작품에서 찾기</button>` : ''}</div>`;
      return;
    }

    if (src === 'asset') {
      const box = st.cv.asset;
      try { assetRows = await assetListOf(); } catch (error) { fail(error); return; }
      if (serial !== searchSerial) return;
      renderCharTitle();
      const specs = [['v5', '신 사양 V5'], ['legacy', '구 사양']];
      const ofSpec = spec => assetRows.filter(row => (row.spec === 'legacy' ? 'legacy' : 'v5') === spec);
      cats.innerHTML = specs.map(([key, label]) => `<button type="button" class="pbw-cat${box.cat === key ? ' is-on' : ''}" data-acat="${key}"><span>${label}</span><small>${ofSpec(key).length}</small></button>`).join('');
      const q = box.q.trim().toLowerCase();
      const rows = ofSpec(box.cat).filter(row => !q || assetName(row).toLowerCase().includes(q) || String(row.id).includes(q));
      if (!rows.some(row => row.id === box.sel)) box.sel = rows[0]?.id || '';
      seedsBox.innerHTML = rows.length
        ? rows.map(row => `<div class="pbw-seed${row.id === box.sel ? ' is-on' : ''}" data-aid="${esc(row.id)}" title="${esc(`${assetName(row)} · 그림 ${Number(row.variation_count || 0) + 1}장`)}"><span>${esc(assetName(row))}</span><span>${Number(row.variation_count || 0) + 1}</span></div>`).join('')
        : `<div class="pbw-empty">${q ? `'${esc(box.q)}' 결과 없음` : '에셋이 없습니다'}</div>`;
      tools.innerHTML = `<label class="pbw-attach" title="에셋을 불러올 때 그 그림을 캐릭터 레퍼런스(S ${ASSET_REF_DEFAULT.strength} · F ${ASSET_REF_DEFAULT.fidelity})로도 붙입니다"><input type="checkbox" data-role="attach"${st.cv.attach ? ' checked' : ''}> 그림을 REF 로도</label>`;
      const row = rows.find(item => item.id === box.sel);
      if (!row) { grid.innerHTML = ''; ctx.textContent = ''; return; }
      ctx.textContent = assetName(row);
      let detail;
      try { detail = await getJson(API.assetDetail(row.id, '')); } catch (error) { fail(error); return; }
      if (serial !== searchSerial) return;
      const pics = [{hash: '', name: '대표', revision: detail.revision}, ...(detail.variations || []).map((v, k) => ({hash: v.hash, name: v.name || `변형 ${k + 1}`, revision: v.revision}))];
      ctx.textContent = `${assetName(row)} · 그림 ${pics.length} · 누르면 캐릭터 ${i + 1} 칸에(프롬프트 + UC)`;
      grid.innerHTML = `<div class="pbw-grid is-3">${pics.map(pic => `<div class="pbw-card" data-avar="${esc(pic.hash)}" data-aid="${esc(row.id)}" data-zt="${esc(`${assetName(row)} · ${pic.name}`)}" title="${esc(`${pic.name} - 누르면 캐릭터 ${i + 1} 칸에`)}">
          <img class="pbw-th is-tall" loading="lazy" src="${esc(API.assetThumb(row.id, pic.hash, pic.revision))}" alt="">
          <div class="pbw-cap">${esc(pic.name)}</div></div>`).join('')}</div>`;
      return;
    }

    // REF 보관함
    const box = st.cv.ref;
    let data;
    try { data = await getJson(API.refLibrary(box.filter, box.cat, box.q.trim())); } catch (error) { fail(error); return; }
    if (serial !== searchSerial) return;
    const counts = data.counts || {};
    if (box.filter === 'all' && !box.q.trim()) { refTotal = Number(data.total || 0); renderCharTitle(); }
    const catRows = [['all', '', '전체', counts.all], ['favorite', '', '즐겨찾기', counts.favorite], ['uncategorized', '', '미분류', counts.uncategorized],
      ...(Array.isArray(data.categories) ? data.categories : []).map(g => ['category', g.id, g.name, counts.categories?.[g.id]])];
    cats.innerHTML = catRows.map(([filter, id, label, count]) => `<button type="button" class="pbw-cat${box.filter === filter && box.cat === id ? ' is-on' : ''}" data-rcat="${filter}" data-rid="${esc(id)}"><span>${esc(label)}</span><small>${Number(count || 0)}</small></button>`).join('');
    seedsBox.innerHTML = `<div class="pbw-hint">그림을 누르면 캐릭터 ${i + 1} 의 REF 줄에 붙습니다 - 다시 누르면 뺍니다.<br>종류 · Strength · Fidelity 는 보관함 설정 그대로.<br>REF 는 이 벤치 생성에만 실립니다.</div>`;
    const items = Array.isArray(data.items) ? data.items.filter(item => item.has_image !== false) : [];
    refRows = new Map(items.map(item => [item.file_hash, item]));
    ctx.textContent = `REF 보관함 · ${items.length}장`;
    const mine = new Set((st.refs[i] || []).filter(ref => ref.source === 'storage').map(ref => ref.file_hash));
    grid.innerHTML = items.length ? `<div class="pbw-grid is-3">${items.map(item => {
      const s = item.settings || {};
      const name = item.name || item.display_name || item.file_hash;
      return `<div class="pbw-card${mine.has(item.file_hash) ? ' is-sel' : ''}" data-rhash="${esc(item.file_hash)}" data-zt="${esc(name)}" title="${esc(`${name} · ${s.reference_type || ''} · Strength ${s.strength} · Fidelity ${s.fidelity}`)}">
        <img class="pbw-th" loading="lazy" src="${esc(item.thumbnail_url || '')}" alt="">
        <div class="pbw-cap">${esc(name)} · ${REF_TYPE_SHORT[s.reference_type] || ''} S ${s.strength ?? ''} F ${s.fidelity ?? ''}</div></div>`;
    }).join('')}</div>` : `<div class="pbw-empty">${box.q.trim() ? `'${esc(box.q)}' 결과 없음` : '보관함이 비었습니다 - REF 창에서 그림을 넣어 두세요'}</div>`;
  }

  // 불러오기 - 앞서 에셋을 불러오며 저절로 붙은 REF 는 걷는다(다른 캐릭터의 그림이 남지 않게).
  function startLoad(i, loaded, text, uc) {
    setCharText(i, text);
    st.ucs[i] = String(uc || '');
    st.loaded[i] = loaded;
    st.refs[i] = (st.refs[i] || []).filter(ref => !ref.auto);
  }
  function afterLoad() {
    persist();
    renderCharMeta();
  }

  async function loadDb(i, group, character, card) {
    try {
      const data = await getJson(API.dbCharacter(group, character, ''));
      startLoad(i, {src: 'db', key: `${group}|${character}`, label: `DB ${dbGroupLabel(group)} › ${dbShortName(character, group)}`}, data.prompt, '');
      afterLoad();
      qsa('.pbw-card[data-cchar]').forEach(el => el.classList.toggle('is-sel', el === card));
      const removed = Array.isArray(data.removed) ? data.removed : [];
      notify(removed.length ? `캐릭터 ${i + 1} 에 넣었습니다 - 옷 태그 ${removed.length}개(${removed.slice(0, 3).join(', ')}${removed.length > 3 ? ' …' : ''})는 뺐습니다` : `캐릭터 ${i + 1} 에 넣었습니다`, 'success');
    } catch (error) {
      notify(`캐릭터를 불러오지 못했습니다: ${error.message}`, 'error');
    }
  }

  async function loadAsset(i, id, variation) {
    const row = assetRows.find(item => item.id === id);
    try {
      const detail = await getJson(API.assetDetail(id, variation));
      const pics = [{hash: '', revision: detail.revision}, ...(detail.variations || [])];
      const at = Math.max(0, pics.findIndex(pic => pic.hash === variation));
      const picName = variation ? (pics[at]?.name || `변형 ${at}`) : '대표';
      const name = row ? assetName(row) : (detail.display_name || id.slice(0, 8));
      startLoad(i, {src: 'asset', label: `에셋 ${name} · ${picName}`}, detail.character_prompt, detail.character_uc);
      let attached = false;
      if (st.cv.attach) {
        if (activeRefs().length >= MAX_REFS) {
          notify(`레퍼런스는 한 번에 ${MAX_REFS}장까지라 그림은 붙이지 않았습니다`, 'info');
        } else {
          st.refs[i].push(cleanRef({source: 'asset', id, variation, label: `${name} · ${picName}`, thumb: API.assetThumb(id, variation, pics[at]?.revision),
            ...ASSET_REF_DEFAULT, auto: true}));
          attached = true;
        }
      }
      afterLoad();
      if (!String(detail.character_prompt || '').trim()) notify('이 에셋엔 캐릭터 프롬프트가 없습니다', 'info');
      else notify(`캐릭터 ${i + 1} 에 넣었습니다${detail.character_uc ? ' · UC 포함' : ''}${attached ? ' · 그림을 REF 로' : ''}`, 'success');
    } catch (error) {
      notify(`에셋을 불러오지 못했습니다: ${error.message}`, 'error');
    }
  }

  // 보관함 그림 하나를 그 캐릭터의 REF 줄에 넣거나 뺀다. 고르기 칸은 다시 그리지 않는다(스크롤 자리를 지킨다).
  function toggleStorageRef(i, hash) {
    const item = refRows.get(hash);
    const list = st.refs[i] || (st.refs[i] = []);
    const at = list.findIndex(ref => ref.source === 'storage' && ref.file_hash === hash);
    if (at >= 0) {
      list.splice(at, 1);
    } else {
      if (!item) return;
      if (activeRefs().length >= MAX_REFS) { notify(`레퍼런스는 한 번에 ${MAX_REFS}장까지입니다`, 'error'); return; }
      const s = item.settings || {};
      list.push(cleanRef({source: 'storage', file_hash: hash, label: item.name || item.display_name || hash, thumb: item.thumbnail_url,
        reference_type: s.reference_type, strength: s.strength, fidelity: s.fidelity}));
    }
    const on = at < 0;
    qsa(`.pbw-card[data-rhash="${CSS.escape(hash)}"]`).forEach(el => el.classList.toggle('is-sel', on));
    persist();
    renderCharMeta();
  }

  // ---------------------------------------------------------------- 결과 열(오른쪽 - 남는다)
  function resultCard(run, index) {
    const item = run.items[index];
    const picked = st.pick && st.pick[0] === run.id && st.pick[1] === index;
    const cls = item.status === 'error' ? ' is-error' : (item.status === 'cancelled' ? ' is-cancel' : '');
    const body = item.status === 'done' && item.historyId
      ? `<img loading="lazy" src="${API.historyThumb(item.historyId)}" alt="">`
      : `<div class="pbw-res-box">${item.status === 'pending' ? '대기' : item.status === 'error' ? esc(item.message || '실패') : item.status === 'cancelled' ? '취소' : '사라짐'}</div>`;
    // 이미 그 칸에 든 세트면 단추를 띄우지 않는다(고정한 뒤에도 남아 있었다).
    const pin = picked && run.axis && item.set && item.status === 'done' && st.picks[run.axis]?.id !== item.set.id
      ? '<button type="button" class="pbw-pin" data-act="pin">이걸로 고정</button>' : '';
    return `<div class="pbw-res${picked ? ' is-pick' : ''}${cls}" data-run="${esc(run.id)}" data-index="${index}" title="${esc(item.label)}">${pin}${body}<div class="pbw-res-cap">${esc(item.label)}</div></div>`;
  }

  // 한 장 = 판 크기에 맞춰 원본을 크게. 고르기 · 고정은 비교(여러 장)에만 있다.
  function bigResult(item) {
    if (item.status === 'done' && item.historyId) {
      return `<div class="pbw-rl-one"><img src="${API.historyImage(item.historyId)}" alt=""></div>`;
    }
    const text = item.status === 'pending' ? '그리는 중…' : item.status === 'error' ? esc(item.message || '실패') : item.status === 'cancelled' ? '취소' : '사라짐';
    return `<div class="pbw-rl-one${item.status === 'error' ? ' is-error' : ''}"><div class="pbw-res-box">${text}</div></div>`;
  }

  const shownRun = () => st.runs.find(run => run.id === st.resRun) || st.runs[st.runs.length - 1] || null;

  // 이전 생성 줄의 한 칸 - 그 생성의 첫 결과 그림 · 여러 장이면 장 수.
  function historyCard(run, current) {
    const item = run.items.find(row => row.status === 'done' && row.historyId) || run.items[0];
    const picture = item?.status === 'done' && item.historyId
      ? `<img loading="lazy" src="${API.historyThumb(item.historyId)}" alt="">`
      : `<div class="pbw-res-box">${item?.status === 'pending' ? '…' : '×'}</div>`;
    return `<button type="button" class="pbw-rl-h${run === current ? ' is-on' : ''}" data-act="res-go" data-run="${esc(run.id)}"
      title="${esc(`${run.label} · ${run.items.length}장 · ${run.base}`)}">${picture}${run.items.length > 1 ? `<span>${run.items.length}</span>` : ''}</button>`;
  }

  function renderResults() {
    const box = $('results');
    $('rcol').classList.toggle('has-hist', st.runs.length > 1);
    const run = shownRun();
    if (!run) {
      box.innerHTML = '<div class="pbw-empty">[생성] 결과가 여기에 남습니다<br><span class="pbw-sm">그림 칸에서 2개 이상 체크하면 비교 생성 - 결과가 격자로 나옵니다</span></div>';
      return;
    }
    const one = run.items.length === 1;
    box.innerHTML = `<div class="pbw-rl-body${one ? ' is-one' : ''}">${one ? bigResult(run.items[0]) : `<div class="pbw-rgrid">${run.items.map((_, i) => resultCard(run, i)).join('')}</div>`}</div>
      ${st.runs.length > 1 ? `<div class="pbw-rl-hist">${[...st.runs].reverse().map(row => historyCard(row, run)).join('')}</div>` : ''}`;
    fitResults();
  }

  // 비교 격자를 결과 열에 맞춘다 - 모든 장이 한눈에 들어오는 가장 큰 칸(3:4 + 이름 줄). 너무 작아지면(90px) 스크롤.
  function fitResults() {
    const body = $('results')?.querySelector('.pbw-rl-body');
    const grid = body?.querySelector('.pbw-rgrid');
    if (!grid || !body.clientWidth) return;
    const count = grid.children.length;
    const width = body.clientWidth - 16;
    const height = body.clientHeight - 16;
    const gap = 8;
    const caption = 22;
    let bestCols = 1;
    let bestSize = 0;
    for (let cols = 1; cols <= count; cols += 1) {
      const rows = Math.ceil(count / cols);
      const size = Math.min((width - gap * (cols - 1)) / cols, ((height - gap * (rows - 1)) / rows - caption) * 3 / 4);
      if (size > bestSize) { bestSize = size; bestCols = cols; }
    }
    grid.style.gridTemplateColumns = `repeat(${bestCols}, ${Math.max(90, Math.floor(bestSize))}px)`;
    grid.style.justifyContent = 'center';
  }

  // 다른 생성을 본다 - 고른 결과는 풀린다(미리보기 줄이 지금 조합으로 돌아온다).
  function showRun(runId) {
    if (!st.runs.some(run => run.id === runId)) return;
    st.resRun = runId;
    st.pick = null;
    leaveCard();
    renderResults();
  }


  // ---------------------------------------------------------------- 생성
  async function generate() {
    if (running()) return stop();
    const slotsNow = slots();
    const axisSlot = slotById(st.axis);
    const axis = axisSlot ? {slotId: axisSlot.id, sets: axisSets()} : null;
    const items = buildItems({cast: castNow(), target: autoTarget(), names: st.names, picks: picksTags(), meta: picksMeta(), axis, ucs: st.ucs,
      extras: st.extras.slice(0, st.count), extraMain: st.extraMain});
    if (items.length > MAX_ITEMS) { notify(`한 번에 ${MAX_ITEMS}장까지입니다 - 비교 체크를 줄여 주세요`, 'error'); return; }
    // REF 는 조용히 빼지 않는다 - 못 싣는 경우는 보내기 전에 막는다(서버도 같은 이유로 거부한다).
    const refs = activeRefs();
    if (refs.length > MAX_REFS) { notify(`레퍼런스는 한 번에 ${MAX_REFS}장까지입니다 - 캐릭터 카드의 REF 줄에서 빼 주세요`, 'error'); return; }
    if (refs.length && crUnsupported(baseModel())) {
      notify(`기반 모델(${baseModel()})은 Character Reference 를 못 씁니다 - 기반 모델을 바꾸거나 REF 를 빼 주세요`, 'error');
      return;
    }
    const references = refs.map(ref => ({
      source: ref.source, ...(ref.source === 'storage' ? {file_hash: ref.file_hash} : {id: ref.id, variation: ref.variation}),
      reference_type: ref.reference_type, strength: ref.strength, fidelity: ref.fidelity,
    }));
    let base;
    if (st.base.mode === 'direct') {
      base = {mode: 'direct', ...st.base.direct};
    } else {
      const name = currentBase().preset?.name || '';
      if (!name) { notify('기반 프리셋이 없습니다 - 기반 설정을 열어 고르세요', 'error'); return; }
      base = {mode: 'preset', name};
    }
    const requestId = makeId();
    const run = {
      id: requestId, axis: axisSlot ? axisSlot.id : null,
      label: axisSlot ? `${KIND_LABELS[axisSlot.kind]} 비교` : '한 장',
      base: `${currentBase().label} · ${st.size}` + (refs.length ? ` · REF ${refs.length}` : ''),
      items: items.map(item => ({label: item.label, set: item.set, status: 'pending', historyId: '', queueId: '', message: ''})),
    };
    void slotsNow;
    st.runs.push(run);
    if (st.runs.length > 30) st.runs.splice(0, st.runs.length - 30);
    st.pick = null;
    st.resRun = run.id;
    renderResults();
    renderLeftControls();
    try {
      const data = await sendJson(API.generate, 'POST', {
        request_id: requestId, base, references, size: st.size,
        items: items.map(item => ({label: item.label, main: item.main, characters: item.characters})),
      });
      (data.requests || []).forEach(row => {
        const item = run.items[Number(row.candidate)];
        if (item) item.queueId = String(row.request_id || row.generation_request_id || '');
      });
      const queued = Number(data.queued ?? run.items.length);
      run.items.slice(queued).forEach(item => { if (item.status === 'pending') { item.status = 'error'; item.message = '큐에 못 넣음'; } });
    } catch (error) {
      const queued = Number(error.data?.queued || 0);
      run.items.slice(queued).forEach(item => { if (item.status === 'pending') { item.status = 'error'; item.message = '보내지 못함'; } });
      notify(`생성을 보내지 못했습니다: ${error.message}`, 'error');
    }
    renderResults();
    renderLeftControls();
  }

  async function stop() {
    const pending = st.runs.flatMap(run => run.items.filter(item => item.status === 'pending'));
    for (const item of pending) {
      if (!item.queueId) continue;
      try {
        await sendJson(API.queueAction, 'POST', {action: 'remove', request_id: item.queueId});
        item.status = 'cancelled';
      } catch (_) {
        // 404 = 이미 그리는 중이거나 끝났다 - 결과가 오면 채워진다.
      }
    }
    renderResults();
    renderLeftControls();
  }

  // ---------------------------------------------------------------- 칸 조작
  function putIntoSlot(slotId, set) {
    st.picks[slotId] = {id: set.id, tags: [...(set.tags || [])], key: set.key, has_thumb: !!set.has_thumb, seed: set.seed, pool: set.pool || '',
      add: [...(set.add || [])], adult: !!set.adult};
    persist();
  }

  function toggleCompare(slotId, set) {
    const map = st.chk[slotId] || (st.chk[slotId] = new Map());
    if (map.has(set.id)) {
      map.delete(set.id);
    } else {
      map.set(set.id, {id: set.id, tags: [...(set.tags || [])], key: set.key, has_thumb: !!set.has_thumb, seed: set.seed});
      if (map.size >= 2 && st.axis && st.axis !== slotId) {
        st.memo = {slotId: st.axis, map: st.chk[st.axis]};
        st.note = `비교: ${esc(KIND_LABELS[slotById(st.axis)?.kind] || '')} → ${esc(KIND_LABELS[slotById(slotId)?.kind] || '')}`;
        delete st.chk[st.axis];
        st.axis = null;
      }
    }
    if (map.size >= 2) st.axis = slotId;
    else if (st.axis === slotId) st.axis = null;
  }

  function renderAll() {
    renderBaseCard();
    renderLeftControls();
    renderSlots();
    renderCharMeta();
    renderNote();
    renderBand();
    void renderExplorer();
    renderResults();
    renderOverlay();
  }

  let booted = false;
  async function boot() {
    if (!booted) {
      booted = true;
      renderChars();
      for (let i = 0; i < st.count; i += 1) refreshSubject(i, 0);
    }
    renderAll();
    await Promise.all([loadBases(), refreshThumbStatus(), fillPickMeta()]);
    renderAllBase();
  }

  // 11-20 이전에 저장한 픽에는 add · adult 가 없다 - 그 세트의 요약을 다시 받아 채운다(실패하면 그대로).
  async function fillPickMeta() {
    const stale = slots().filter(slot => st.picks[slot.id]?.id && !('adult' in st.picks[slot.id]));
    if (!stale.length) return;
    await Promise.all(stale.map(async slot => {
      const pick = st.picks[slot.id];
      try {
        const set = (await setsOf(slot.kind, pick.pool || slot.pool, pick.seed)).find(row => row.id === pick.id);
        if (set && st.picks[slot.id] === pick) Object.assign(pick, {add: [...(set.add || [])], adult: !!set.adult});
      } catch (_) { /* 다음에 고를 때 채워진다 */ }
    }));
    persist();
    renderSlots();
  }

  // ---------------------------------------------------------------- 이벤트
  // 캐릭터 글 칸에 Tab 으로 들어와도 그 캐릭터를 고른다(누르기와 같은 규칙).
  listen('focusin', event => {
    const area = event.target.closest?.('textarea[data-name]');
    if (area && inside(area)) pickChar(Number(area.dataset.name));
    const extra = event.target.closest?.('textarea[data-extra]');
    if (extra && inside(extra)) extra.rows = 4;          // 누르면 펼친다
  });
  listen('focusout', event => {
    const extra = event.target.closest?.('textarea[data-extra]');
    if (extra && inside(extra)) { extra.rows = 1; extra.scrollTop = 0; }    // 떠나면 다시 한 줄
  });

  listen('click', event => {
    const t = event.target;
    const act = t.closest('[data-act]')?.dataset.act;
    if (act === 'res-go') { showRun(t.closest('[data-run]').dataset.run); return; }
    if (act === 'base') { st.baseOpen = !st.baseOpen; renderAllBase(); return; }
    if (act === 'base-close') { st.baseOpen = false; renderAllBase(); return; }
    if (act === 'go') { void generate(); return; }
    if (act === 'leave') { onLeave(); return; }
    if (act === 'char-add') { setCount(st.count + 1); return; }
    if (act === 'char-remove') { setCount(st.count - 1); return; }
    if (act === 'extra-x') {
      const key = t.closest('[data-extra-key]').dataset.extraKey;
      if (key === 'main') st.extraMain = ''; else st.extras[Number(key)] = '';
      const area = qs(`textarea[data-extra="${key}"]`);
      if (area) { area.value = ''; area.closest('.pbw-extra')?.classList.remove('has-text'); }
      persist();
      return;
    }
    if (act === 'char-pick') {
      pickChar(Number(t.closest('[data-index]').dataset.index));
      return;
    }
    if (act === 'load-x') {
      const i = Number(t.closest('[data-index]').dataset.index);
      st.loaded[i] = null;
      st.ucs[i] = '';
      afterLoad();
      return;
    }
    if (act === 'ref-x') {
      const el = t.closest('[data-ref]');
      const i = Number(el.dataset.index);
      const [gone] = (st.refs[i] || []).splice(Number(el.dataset.ref), 1);
      if (gone?.source === 'storage') qsa(`.pbw-card[data-rhash="${CSS.escape(gone.file_hash)}"]`).forEach(card => card.classList.remove('is-sel'));
      persist();
      renderCharMeta();
      return;
    }
    if (act === 'undo') {
      if (st.memo) {
        if (st.axis) delete st.chk[st.axis];
        st.chk[st.memo.slotId] = st.memo.map;
        st.axis = st.memo.slotId;
        st.memo = null;
        st.note = '';
      }
      renderAll();
      return;
    }
    if (act === 'note-x') { st.note = ''; st.memo = null; renderNote(); return; }
    if (act === 'related-back') { viewOf(st.cur).mode = viewOf(st.cur).q ? 'search' : 'browse'; void renderExplorer(); return; }
    if (act === 'thumb-dl') {
      sendJson(API.thumbDownload, 'POST', {}).then(() => refreshThumbStatus())
        .catch(error => notify(`받기를 시작하지 못했습니다: ${error.message}`, 'error'));
      return;
    }
    if (act === 'pin') {
      const run = st.runs.find(r => r.id === st.pick?.[0]);
      const item = run?.items[st.pick[1]];
      if (run?.axis && item?.set && slotById(run.axis)) {
        putIntoSlot(run.axis, item.set);
        delete st.chk[run.axis];
        if (st.axis === run.axis) st.axis = null;
        st.cur = run.axis;
        st.memo = null;
        st.pick = null;
        leaveCard();
        st.note = `${esc(KIND_LABELS[slotById(run.axis).kind])} = '${esc(item.label)}' 로 고정 · 이제 다른 칸을 비교해 보세요`;
        renderAll();
      }
      return;
    }
    if (act === 'to-direct') {
      const name = currentBase().preset?.name;
      if (name && copyPresetToDirect(name)) { st.base.mode = 'direct'; persist(); renderAllBase(); }
      return;
    }
    if (act === 'direct-save') { void saveDirect(st.base.directName); return; }
    if (act === 'direct-save-as') { void saveDirectAs(); return; }
    if (act === 'direct-delete') {
      const name = st.base.directName;
      if (!name || !win.confirm(`직접 설정 '${name}' 을 지울까요?`)) return;
      sendJson(API.directOne(name), 'DELETE', {}).then(async () => {
        st.base.directName = '';
        directs = (await getJson(API.direct)).items || [];
        persist();
        renderAllBase();
      }).catch(error => notify(`지우지 못했습니다: ${error.message}`, 'error'));
      return;
    }
    if (act === 'export') { void exportDirect(false); return; }

    const mode = t.closest('[data-mode]');
    if (mode) {
      // 직접 설정으로 처음 넘어갈 때(저장본 없음 · 빈 값)는 지금 고른 프리셋의 값을 채워서 연다(사용자 11-20).
      const fromPreset = st.base.mode === 'preset' ? currentBase().preset?.name : (bases?.current || '');
      st.base.mode = mode.dataset.mode === 'direct' ? 'direct' : 'preset';
      if (st.base.mode === 'direct' && !st.base.directName && directIsEmpty() && fromPreset) copyPresetToDirect(fromPreset);
      persist();
      renderAllBase();
      return;
    }
    const clear = t.closest('[data-clear]');
    if (clear) {
      const id = clear.dataset.clear;
      delete st.picks[id];
      delete st.chk[id];
      if (st.axis === id) st.axis = null;
      persist();
      renderAll();
      return;
    }
    const chip = t.closest('[data-chip]');
    if (chip) { st.note = ''; st.memo = null; renderNote(); void openRelated(chip.dataset.from, chip.dataset.chip); return; }
    // 카드의 나머지 자리(글 칸 · 불러온 줄)도 그 캐릭터를 고른다 - 단추 · 칩 · 칸 줄은 위에서 제 일을 했다.
    const ccard = t.closest('[data-ccard]');
    if (ccard && !t.closest('[data-slots], button, a, [data-ref], .pbw-uc, .pbw-extra')) { pickChar(Number(ccard.dataset.ccard)); return; }
    const slotEl = t.closest('[data-slot]');
    if (slotEl) {
      st.cur = slotEl.dataset.slot;
      st.baseOpen = false;
      renderSlots();
      renderOverlay();
      renderBaseCard();
      void renderExplorer();
      return;
    }
    // 캐릭터 고르기(DB · 에셋 · REF)
    const ci = charIndex();
    if (ci >= 0) {
      const csrc = t.closest('[data-csrc]');
      if (csrc) {
        st.cv.src = csrc.dataset.csrc;
        if (st.cv.src === 'asset') assetListOf(true).catch(() => {});      // 에셋 창에서 새로 만든 것이 보이게
        persist();
        searchInput.value = st.cv[st.cv.src].q;
        void renderExplorer();
        return;
      }
      const cg = t.closest('[data-cgender]');
      if (cg) { st.cv.db.gender = cg.dataset.cgender; void renderExplorer(); return; }
      const cgroup = t.closest('[data-cgroup]');
      if (cgroup) { st.cv.db.group = cgroup.dataset.cgroup; void renderExplorer(); return; }
      if (t.closest('[data-cfav]')) { st.cv.db.fav = !st.cv.db.fav; void renderExplorer(); return; }
      const cchar = t.closest('[data-cchar]');
      if (cchar) {
        const row = dbRows[Number(cchar.dataset.cchar)];
        if (row) void loadDb(ci, row.group, row.character, cchar);
        return;
      }
      const acat = t.closest('[data-acat]');
      if (acat) { st.cv.asset.cat = acat.dataset.acat; st.cv.asset.sel = ''; void renderExplorer(); return; }
      const avar = t.closest('[data-avar]');
      if (avar) { void loadAsset(ci, avar.dataset.aid, avar.dataset.avar); return; }
      const aid = t.closest('[data-aid]');
      if (aid) { st.cv.asset.sel = aid.dataset.aid; void renderExplorer(); return; }
      const rcat = t.closest('[data-rcat]');
      if (rcat) { st.cv.ref.filter = rcat.dataset.rcat; st.cv.ref.cat = rcat.dataset.rid || ''; void renderExplorer(); return; }
      const rhash = t.closest('[data-rhash]');
      if (rhash) { toggleStorageRef(ci, rhash.dataset.rhash); return; }
    }
    const csub = t.closest('[data-csub]');
    if (csub) {
      const view = viewOf(st.cur);
      view.sub = view.sub === csub.dataset.csub ? '' : csub.dataset.csub;
      view.seed = '';
      view.hitSet = '';
      void renderExplorer();
      return;
    }
    const cat = t.closest('[data-cat]');
    if (cat) {
      const view = viewOf(st.cur);
      view.cat = cat.dataset.cat;
      view.sub = '';
      view.seed = '';
      view.mode = 'browse';
      view.q = '';
      view.hitSet = '';
      searchInput.value = '';
      void renderExplorer();
      return;
    }
    const seed = t.closest('[data-seed]');
    if (seed) { viewOf(st.cur).seed = seed.dataset.seed; viewOf(st.cur).hitSet = ''; void renderExplorer(); return; }
    const check = t.closest('[data-check]');
    if (check) {
      const set = shownSets.get(check.dataset.check);
      if (set) {
        toggleCompare(st.cur, set);
        // 탐색 칸은 다시 그리지 않는다(긴 목록의 스크롤 자리를 지킨다) - 체크 상자만 바꾼다.
        const on = Boolean(st.chk[st.cur]?.has(set.id));
        qsa(`.pbw-ck[data-check="${CSS.escape(set.id)}"]`).forEach(el => {
          el.classList.toggle('is-on', on);
          el.textContent = on ? '✓' : '';
          el.setAttribute('aria-checked', on ? 'true' : 'false');
        });
        renderLeftControls();
        renderSlots();
        renderNote();
      }
      return;
    }
    const card = t.closest('[data-set]');
    if (card) {
      const set = shownSets.get(card.dataset.set);
      if (set) { putIntoSlot(st.cur, set); renderSlots(); qsa('.pbw-card').forEach(el => el.classList.toggle('is-sel', el.dataset.set === set.id)); }
      return;
    }
    const res = t.closest('.pbw-rgrid .pbw-res');
    if (res && !res.classList.contains('is-cancel')) {
      st.pick = [res.dataset.run, Number(res.dataset.index)];
      renderResults();
    }
  });

  listen('change', event => {
    const t = event.target;
    if (t.dataset.role === 'base-preset') { st.base.preset = t.value; persist(); renderAllBase(); return; }
    if (t.dataset.role === 'direct-pick') {
      const item = directs.find(row => row.name === t.value);
      st.base.directName = item ? item.name : '';
      if (item) {
        st.base.direct = {prefix: item.prefix || '', postfix: item.postfix || '', negative_prompt: item.negative_prompt || '', params: cleanParams(item.params)};
        st.base.directFrom = '';
      }
      persist();
      renderAllBase();
      return;
    }
    if (t.dataset.role === 'load-from') {
      if (t.value && copyPresetToDirect(t.value)) { notify(`'${t.value}' 의 값을 불러왔습니다(아직 저장 안 함)`, 'success'); renderAllBase(); }
      return;
    }
    if (t.dataset.role === 'export-target') { st.exportTarget = t.value; return; }
    if (t.dataset.role === 'attach') { st.cv.attach = t.checked; persist(); return; }
    if (t.dataset.role === 'res') { if (BENCH_SIZES.includes(t.value)) { st.size = t.value; persist(); } return; }
    if (t.dataset.param) { setDirectParam(t); return; }
  });

  listen('input', event => {
    const t = event.target;
    if (t.dataset.extra !== undefined) {
      if (t.dataset.extra === 'main') st.extraMain = t.value; else st.extras[Number(t.dataset.extra)] = t.value;
      t.closest('.pbw-extra')?.classList.toggle('has-text', Boolean(t.value));
      persist();
      return;
    }
    if (t.dataset.name !== undefined) {
      const i = Number(t.dataset.name);
      st.names[i] = t.value;
      // 글을 다 지우면 불러온 표시 · UC 도 걷는다(REF 줄은 따로 뺀다).
      if (!t.value.trim() && (st.loaded[i] || st.ucs[i])) { st.loaded[i] = null; st.ucs[i] = ''; renderCharMeta(); }
      persist();
      refreshSubject(Number(t.dataset.name));
      return;
    }
    if (t === searchInput) {
      win.clearTimeout(searchTimer);
      const q = t.value;
      // 캐릭터 검색은 Characters 창과 같은 150ms(가벼운 색인) - 칸 검색(세트 찾기)은 280ms.
      const delay = charIndex() >= 0 && st.cv.src === 'db' ? 150 : 280;
      searchTimer = win.setTimeout(() => { void runSearch(q); }, delay);
      return;
    }
    if (t.dataset.field) { st.base.direct[t.dataset.field] = t.value; persist(); return; }
    if (t.dataset.param) { setDirectParam(t); return; }
  });

  // 직접 설정의 설정 칸 - 비우면 세션 값을 따른다. 고르는 칸(모델 · 샘플러 · 스케줄러)은 change 로, 숫자 칸은 input 으로 온다.
  function setDirectParam(t) {
    const key = t.dataset.param;
    if (t.value === '') delete st.base.direct.params[key];
    else if (['model', 'sampler', 'scheduler'].includes(key)) st.base.direct.params[key] = t.value;
    else if (Number.isFinite(Number(t.value))) st.base.direct.params[key] = Number(t.value);
    persist();
    renderBaseCard();
  }

  // ---------------------------------------------------------------- 올리면 창 옆에 크게
  const HOVER_DELAY_MS = 140;      // 리모컨 · 아티스트 태그 관리 창과 같은 뜸 - 지나가는 마우스에는 안 뜬다
  let hoverCard = null;
  let hoverTimer = null;
  // 크게 보기 상자 너비 = style.css .rctl-zoom (320px · 최대 42vw). 칸이 이보다 크면 크게 보기가 뜻이 없다.
  const zoomWidth = () => Math.min(320, (win.innerWidth || 1600) * 0.42);
  // 칸이 크게 보기의 80% 에 닿으면 크게 보기를 띄우지 않는다(사용자 11-20 "한 80% 정도 도달하면").
  const ZOOM_SKIP_RATIO = 0.8;

  function leaveCard() {
    if (hoverTimer) { win.clearTimeout(hoverTimer); hoverTimer = null; }
    if (hoverCard) { hoverCard = null; hideZoom(); }
  }

  listen('mouseover', event => {
    const card = event.target?.closest?.('.pbw-card, .pbw-rgrid .pbw-res');
    if (card === hoverCard) return;
    leaveCard();
    const src = card?.querySelector('img')?.getAttribute('src');
    if (!src || typeof showZoom !== 'function') return;     // '미생성' 칸은 띄울 것이 없다
    // 칸이 크게 보기의 80% 이상이면 띄우지 않는다(사용자 11-20 - 비슷한 크기로 겹쳐 가리기만 한다).
    if (card.getBoundingClientRect().width >= zoomWidth() * ZOOM_SKIP_RATIO) return;
    hoverCard = card;
    hoverTimer = win.setTimeout(() => {
      hoverTimer = null;
      if (hoverCard !== card || !active) return;
      if (card.classList.contains('pbw-res')) {
        const item = st.runs.find(run => run.id === card.dataset.run)?.items[Number(card.dataset.index)];
        showZoom(card, {src, title: item?.label || '', note: ''}, card.getBoundingClientRect());
        return;
      }
      const set = shownSets.get(card.dataset.set);
      const badge = set ? (POOL_BADGES[set.pool] || (LINK_POOLS[set.pool]?.badge ?? '')) : '';
      showZoom(card, {
        src,
        title: set ? (set.tags || []).join(', ') : (card.dataset.zt || ''),
        note: [badge, set?.seed].filter(Boolean).join(' · '),
      }, card.getBoundingClientRect());
    }, HOVER_DELAY_MS);
  });
  listen('mouseleave', leaveCard);
  listen('scroll', leaveCard, true);

  // ---------------------------------------------------------------- 시드 줄 = 태그 카드
  // 이벤트 맵의 툴팁과 같은 작은 카드(.em-tip - 사용자 11-20 '그림 3'): 이름 · 분류 경로 · 한글 설명(/api/tag/lookup)
  // · 세트 수 · Danbooru 게시물 · 썸네일(Interactive 썸네일 축에 있는 태그만). 조회는 태그마다 한 번.
  let tipEl = null;
  let tipOwner = null;
  let thumbAxis = null;
  let thumbAsked = false;
  const tipLooked = new Map();     // 태그 -> {desc, count} | null(조회해 봤는데 없다)
  const tipAsked = new Set();

  function ensureTip(doc) {
    if (tipEl && tipEl.ownerDocument === doc && doc.body.contains(tipEl)) return tipEl;
    tipEl?.remove();
    tipEl = doc.createElement('div');
    tipEl.className = 'em-tip';
    doc.body.appendChild(tipEl);           // body 직계 - 칸 안에 두면 overflow 에 잘린다
    return tipEl;
  }

  async function askTip(tag) {
    if (tipLooked.has(tag) || tipAsked.has(tag)) return;
    tipAsked.add(tag);
    try {
      const data = await getJson(`/api/tag/lookup?tag=${encodeURIComponent(tag)}`);
      tipLooked.set(tag, data && data.tag ? {desc: String(data.desc || ''), count: Number(data.count) || 0} : null);
    } catch (_) {
      tipLooked.set(tag, null);
    }
    if (tipOwner?.dataset.pbwTip === tag) paintTip(tipOwner);
  }

  async function askThumbAxis() {
    if (thumbAxis || thumbAsked) return;
    thumbAsked = true;
    try {
      const axes = (await getJson('/api/interactive-thumb/index')).axes || {};
      thumbAxis = new Map();
      for (const [axis, tags] of Object.entries(axes)) for (const tag of tags) if (!thumbAxis.has(tag)) thumbAxis.set(tag, axis);
    } catch (_) {
      thumbAxis = new Map();
    }
    if (tipOwner) paintTip(tipOwner);
  }

  function paintTip(owner) {
    if (!owner.isConnected) { hideTip(); return; }
    const doc = owner.ownerDocument;
    const view = doc.defaultView || win;
    const tip = ensureTip(doc);
    const tag = owner.dataset.pbwTip || '';
    const looked = tipLooked.get(tag);
    const axis = thumbAxis?.get(tag);
    const thumb = axis ? `<img class="em-tip-thumb" alt="" src="/api/interactive-thumb?axis=${encodeURIComponent(axis)}&tag=${encodeURIComponent(tag)}">` : '';
    const posts = owner.dataset.pbwTipPosts ? Number(owner.dataset.pbwTipPosts) : (looked?.count || 0);
    const stats = [`세트 ${owner.dataset.pbwTipSets || 0}`, posts ? `Danbooru ${posts.toLocaleString('en-US')}` : ''].filter(Boolean).join(' · ');
    tip.innerHTML = `<div class="em-tip-row"><div class="em-tip-main">`
      + `<div class="em-tip-head"><span class="em-tip-tag">${esc(tag)}</span><span class="em-tip-src">${esc(owner.dataset.pbwTipSrc || '')}</span></div>`
      + (looked?.desc ? `<div class="em-tip-desc">${esc(looked.desc)}</div>` : (looked === undefined ? '<div class="em-tip-desc em-tip-wait">…</div>' : ''))
      + `<div class="em-tip-stats">${esc(stats)}</div>`
      + `<div class="em-tip-foot"><div class="em-tip-hint">${esc(owner.dataset.pbwTipHint || '클릭 = 이 태그의 세트 보기')}</div></div>`
      + `</div>${thumb}</div>`;
    tip.classList.add('open');
    // 이벤트 맵과 같은 자리: 줄 가운데의 살짝 오른쪽 · 바로 아래. 아래가 모자라면 위로.
    const a = owner.getBoundingClientRect();
    const b = tip.getBoundingClientRect();
    let left = a.left + a.width * 0.5 + 16;
    left = Math.max(8, Math.min(left, view.innerWidth - b.width - 8));
    let top = a.bottom + 6;
    if (top + b.height > view.innerHeight - 8) top = a.top - b.height - 6;
    tip.style.left = `${Math.round(left)}px`;
    tip.style.top = `${Math.round(Math.max(8, top))}px`;
  }

  function showTip(owner) {
    if (owner === tipOwner) return;
    tipOwner = owner;
    void askTip(owner.dataset.pbwTip || '');
    void askThumbAxis();
    paintTip(owner);
  }

  function hideTip() {
    tipOwner = null;
    tipEl?.classList.remove('open');
  }

  listen('mouseover', event => {
    const owner = event.target?.closest?.('[data-pbw-tip]');
    if (owner) showTip(owner);
    else if (tipOwner) hideTip();
  });
  listen('mouseleave', hideTip);
  listen('scroll', hideTip, true);
  listen('pointerdown', hideTip, true);     // 누르면 목록이 다시 그려진다 - 떠난 줄의 카드를 남기지 않는다

  // 그림 칸 : 결과 열 경계 - 끌어서 너비를 바꾸고 기억한다(두 번 누르면 처음대로).
  function applySplit() { $('gcol').style.flexBasis = `${Math.round(st.split * 1000) / 10}%`; }
  const splitBar = $('split');
  splitBar.addEventListener('pointerdown', event => {
    if (event.button !== 0) return;
    event.preventDefault();
    const rect = $('main').getBoundingClientRect();
    const usable = Math.max(1, rect.width - 16 - splitBar.offsetWidth);
    splitBar.setPointerCapture?.(event.pointerId);
    splitBar.classList.add('is-drag');
    const move = ev => { st.split = Math.min(0.75, Math.max(0.25, (ev.clientX - rect.left - 8) / usable)); applySplit(); };
    const up = () => {
      splitBar.classList.remove('is-drag');
      splitBar.removeEventListener('pointermove', move);
      splitBar.removeEventListener('pointerup', up);
      splitBar.removeEventListener('pointercancel', up);
      persist();
    };
    splitBar.addEventListener('pointermove', move);
    splitBar.addEventListener('pointerup', up);
    splitBar.addEventListener('pointercancel', up);
  });
  splitBar.addEventListener('dblclick', () => { st.split = 0.45; applySplit(); persist(); });
  applySplit();
  // 칸 고르기 그림 판 - 한 줄 3장으로 나눠도 칸이 크게 보기의 80% 이상이면 3장(사용자 11-20 "3줄 조건을 약화" -
  // 처음 x 2.95 에서 낮춤 · 크게 보기 320px 면 판 780px 남짓부터). 캐릭터 고르기(is-3)는 늘 3장.
  function fitGridCols() {
    const wrap = $('grid');
    if (wrap) wrap.classList.toggle('is-w3', wrap.clientWidth >= zoomWidth() * ZOOM_SKIP_RATIO * 3 + 12);
  }
  if (win.ResizeObserver) {
    new win.ResizeObserver(() => fitResults()).observe($('results'));
    new win.ResizeObserver(() => fitGridCols()).observe($('grid'));
  }
  fitGridCols();

  // ---------------------------------------------------------------- 결과 수신(app.js 가 부른다)
  function handleResultMeta(meta) {
    if (!meta?.preset_bench_request) return false;
    const run = st.runs.find(r => r.id === String(meta.preset_bench_request_id || ''));
    if (!run) return false;
    const item = run.items[Number(meta.preset_bench_candidate)];
    if (item) {
      item.status = 'done';
      item.historyId = String(meta.history_id || '');
    }
    if (active) { renderResults(); renderLeftControls(); }
    return true;
  }

  function handleGenerationError(message) {
    const run = st.runs.find(r => r.id === String(message?.requestId || ''));
    if (!run) return false;
    const item = run.items[Number(message.candidate)];
    if (item && item.status === 'pending') {
      item.status = 'error';
      item.message = String(message.message || '실패');
    }
    if (active) { renderResults(); renderLeftControls(); }
    return true;
  }

  // 탭에 들어오면 덮개를 올리고(왼쪽 칸) 처음이면 불러온다. 떠나면 결과 판 · 크게 보기를 걷는다.
  function setActive(next) {
    const want = Boolean(next);
    if (want === active) return;
    active = want;
    leftMount.hidden = !want;
    if (want) void boot();
    else { leaveCard(); hideTip(); }
    onVisibilityChange();
  }

  // Ctrl+Enter(app.js generateAction) - 덮개가 올라와 있으면 이 벤치의 [N장 생성 | 중지] 와 같다.
  function generateFromShortcut() {
    if (!active) return false;
    void generate();
    return true;
  }

  return {
    setActive,
    isActive: () => active,
    generate: generateFromShortcut,
    handleResultMeta,
    handleGenerationError,
  };
}

export {variantLabel};
