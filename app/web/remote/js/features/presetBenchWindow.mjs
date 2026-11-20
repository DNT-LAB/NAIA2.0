// 프리셋 벤치(사용자 지시 2026-11-19 · 11-20 "사이즈상 메인 UI 로" - 떠 있는 창을 걷고 메인 화면에 싣는다).
//
//   ┌ 메인 왼쪽 열(#pbBlocks) ┐┌ 오른쪽 Presets 탭(#presetBenchRoot) ─────────────────┐
//   │ Presets 벤치 [← 프롬프트]││ 칸 이름 · 맥락 · [검색] [결과]                          │
//   │ 기반 요약 카드           ││ 대분류 | 소분류 · 시드 | 세트 카드(위에 결과 판이 뜬다) │
//   │ 넣을 곳 · 캐릭터 카드    ││                                                         │
//   │ [N장 생성 | 중지]        │├ 프롬프트 미리보기 · [복사] [메인 프롬프트로] ───────────┤
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

import {
  MAX_CHARACTERS, normalizeCast, KIND_LABELS, LINK_POOLS, linkMismatch, slotsFor, previewRows, buildItems, variantLabel, formatPosts,
} from './presetBenchModel.mjs?v=20261120-ui4';

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
};
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
.pbw-main { flex: 1 1 auto; min-height: 0; display: flex; padding: 8px; }
.pbw-gcol { flex: 0 0 45%; min-width: 220px; min-height: 0; display: flex; flex-direction: column; gap: 6px; }
.pbw-split { flex: 0 0 11px; cursor: col-resize; position: relative; touch-action: none; }
.pbw-split::after { content: ""; position: absolute; left: 5px; top: 0; bottom: 0; width: 1px; background: var(--border-dim); }
.pbw-split:hover::after, .pbw-split.is-drag::after { left: 4px; width: 3px; background: var(--accent); }
.pbw-rcol { flex: 1 1 0; min-width: 260px; min-height: 0; display: flex; flex-direction: column; }
.pbw-lhead { display: flex; align-items: center; gap: 8px; }
.pbw-lhead b { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.pbw-lhead .pbw-btn { margin-left: auto; }
.pbw-right { flex: 1 1 auto; min-width: 0; min-height: 0; display: flex; flex-direction: column; position: relative; }
.pbw-ex { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; padding: 8px; gap: 6px; }
.pbw-pv { flex: 0 0 auto; border-top: 1px solid var(--border-dim); padding: 5px 10px; }
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
.pbw-base { border: 1px solid var(--border-dim); border-radius: 6px; padding: 5px 7px; cursor: pointer; }
.pbw-base:hover, .pbw-base.is-on { border-color: var(--accent); }
.pbw-base-sum { font-size: 11px; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.pbw-seg { display: inline-flex; border: 1px solid var(--border-dim); border-radius: 5px; overflow: hidden; }
.pbw-seg button { border: 0; background: transparent; color: var(--text-dim); padding: 2px 8px; font-family: inherit; font-size: 11px; cursor: pointer; }
.pbw-seg button.is-on { background: var(--bg-hover); color: var(--text-primary); box-shadow: inset 0 -2px 0 var(--accent); }
.pbw-chars { display: flex; flex-direction: column; gap: 8px; }
.pbw-solos { display: flex; flex-direction: column; gap: 8px; }
.pbw-ccard { background: var(--bg-card); border: 1px solid var(--border-dim); border-radius: 7px; overflow: hidden; }
.pbw-chead { display: flex; align-items: center; gap: 6px; padding: 5px 8px; font-size: 12px; font-weight: 600; color: var(--text-primary);
  border-bottom: 1px solid var(--border-dim); }
.pbw-ccard > .pbw-text { display: block; margin: 6px 8px; width: calc(100% - 16px); }
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
.pbw-slot + .pbw-slot { border-top: 1px solid rgba(255,255,255,0.04); }
.pbw-slot:hover { background: var(--bg-hover); }
.pbw-slot.is-cur { background: rgba(124,106,239,0.16); }
.pbw-slot.is-cur::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--accent); }
.pbw-slot-k { font-size: 11px; color: var(--text-muted); padding-top: 2px; line-height: 1.25; }
.pbw-slot-k small { display: block; font-size: 10px; color: var(--text-dim); }
.pbw-slot.is-cur .pbw-slot-k { color: var(--accent-light); }
.pbw-ccard.is-solo .pbw-slot-k { color: var(--text-primary); font-weight: 600; }
.pbw-ccard.is-solo .pbw-slot.is-cur .pbw-slot-k { color: var(--accent-light); }
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
  color: var(--text-muted); font-size: 12px; cursor: pointer; background: transparent; font-family: inherit; text-align: left; }
.pbw-cat small { font-size: 10px; color: var(--text-dim); }
.pbw-cat:hover { color: var(--text-primary); }
.pbw-cat { position: relative; }
/* 고른 칸 표시는 곧은 막대로 - inset 그림자는 둥근 모서리를 따라 휘어 { 처럼 보인다(사용자 지시 2026-11-20). */
.pbw-cat.is-on { color: var(--text-primary); background: var(--bg-hover); }
.pbw-cat.is-on::before { content: ""; position: absolute; left: 0; top: 3px; bottom: 3px; width: 2px; background: var(--accent); }
/* 소분류 머리글이 항목보다 위로 읽히게 - 굵게 · 밝게 · 아래 선. */
.pbw-sub { font-size: 11px; font-weight: 600; color: var(--text-muted); padding: 8px 5px 3px; margin: 0 2px 2px; border-bottom: 1px solid var(--border-dim); }
.pbw-sub:first-child { padding-top: 0; }
.pbw-ex2 { flex: 1 1 auto; min-height: 0; display: grid; grid-template-columns: 124px minmax(0, 1fr); gap: 8px; }
.pbw-ex2.is-related { grid-template-columns: minmax(0, 1fr) 0; }
.pbw-seeds { min-height: 0; overflow-y: auto; border-right: 1px solid var(--border-dim); padding-right: 6px; }
.pbw-ex2.is-related .pbw-seeds { border-right: 0; padding-right: 0; }
.pbw-seed { display: flex; justify-content: space-between; gap: 6px; padding: 2px 5px 2px 9px; border-radius: 4px; cursor: pointer; color: var(--text-muted); font-size: 12px; }
/* 글자를 한 단계 밝게(사용자 지시 11-20) - 이름은 text-muted, 수는 한 단계 낮게 */
.pbw-seed span:last-child { flex: none; font-family: var(--font-mono); font-size: 10px; color: var(--text-dim); }
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
.pbw-grid-wrap { flex: 1 1 auto; min-height: 0; overflow-y: auto; }
/* 그림 칸이 넓어진 만큼 카드도 키운다 - 칸 너비 500px 이면 한 줄 2장(약 240px). */
.pbw-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 6px; align-content: start; grid-auto-rows: max-content; }
.pbw-sec { font-size: 11px; color: var(--text-dim); margin: 6px 0 3px; }
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
.pbw-rl-head { flex: none; display: flex; align-items: center; gap: 6px; min-width: 0; padding: 4px 4px 4px 10px; border-bottom: 1px solid var(--border-dim); }
.pbw-rl-head > .pbw-dim { min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.pbw-rl-nav { margin-left: auto; display: inline-flex; align-items: center; gap: 4px; flex: none; }
.pbw-rl-nav .pbw-btn { padding: 0 7px; font-size: 13px; line-height: 20px; }
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
.pbw-bs-size { display: flex; align-items: center; justify-content: flex-end; gap: 4px; }
.pbw-bs-size .param-input { flex: 0 0 52px; }
.pbw-bs-src { margin-top: 6px; font-size: 10.5px; color: var(--text-dim); }
.pbw-bs-src > span:first-child { flex: none; }
.pbw-bs-badge { color: #f0c674; font-weight: 600; }
.pbw-form { display: grid; grid-template-columns: 70px minmax(0, 1fr); gap: 6px 8px; align-items: start; margin-top: 8px; }
.pbw-form > .pbw-dim { padding-top: 4px; }
.pbw-params { display: flex; flex-wrap: wrap; gap: 6px; }
.pbw-params label { display: flex; flex-direction: column; gap: 2px; font-size: 11px; color: var(--text-dim); }
.pbw-params input { width: 84px; }
.pbw-params input.is-wide { width: 150px; }
.pbw-pp { font-family: var(--font-mono); font-size: 11px; line-height: 1.6; word-break: break-word; }
.pbw-pr { display: grid; grid-template-columns: 58px minmax(0, 1fr); gap: 8px; border-top: 1px solid var(--border-dim); padding: 2px 0; }
.pbw-pr:first-child { border-top: 0; }
.pbw-src { color: var(--text-dim); }
.pbw-hl { color: var(--accent); }
.pbw-pv-line { flex: 1 1 auto; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.pbw-band { padding: 6px 8px; border: 1px solid rgba(240,198,116,0.45); border-radius: 6px; font-size: 11px; display: flex; gap: 8px; align-items: center; }
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
  parts.push(p.width && p.height ? `${p.width}x${p.height}` : '크기 = 세션');
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
  // [메인 프롬프트로] - 가운데 몫을 메인 프롬프트 칸에 넣는다(app.js applyPromptText).
  applyMainPrompt = null,
  notify = () => {},
  onVisibilityChange = () => {},
  // 기반 설정 판(사용자 11-20) - 메인 Params 탭의 지금 값 · 고를 목록(모델 · 샘플러 · 스케줄러) · PE 프리셋 요약(모델 배지 · 미리보기) ·
  // 이름 묻기(앱 표준 대화 상자). 없으면 빈 값 · 빈 목록 · 브라우저 prompt.
  getSessionParams = () => ({}),
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
    target: saved.target === 'main' ? 'main' : 'char',
    names: Array.isArray(saved.names) ? saved.names.slice(0, 2).map(String) : ['', ''],
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
    pvOpen: false,
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
        count: st.count, target: st.target, names: st.names, picks: st.picks, split: st.split,
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
  const viewOf = id => (st.views[id] ||= {cat: '', seed: '', mode: 'browse', q: '', hits: [], related: null, relatedTag: '', hitSet: ''});
  const axisSets = () => (st.axis && st.chk[st.axis] ? [...st.chk[st.axis].values()] : []);
  const running = () => st.runs.some(run => run.items.some(item => item.status === 'pending'));

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
        <div class="pbw-lhead"><b>Presets 벤치</b><button type="button" class="pbw-btn" data-act="leave" title="메인 프롬프트로 돌아갑니다(Result 탭)">← 프롬프트</button></div>
        <div class="pbw-ledit">
          <div class="pbw-base" data-act="base" title="기반 설정 열기"></div>
          <div class="pbw-row"><span class="pbw-dim pbw-sm">캐릭터 넣을 곳</span>
            <span class="pbw-seg" data-role="target"><button type="button" data-target="char">캐릭터칸</button><button type="button" data-target="main">메인</button></span></div>
          <div class="pbw-chars" data-role="chars"></div>
        </div>
        <div class="pbw-pick">
          <div data-role="note"></div>
          <div class="pbw-ex-head"><b data-role="ex-title" style="font-weight:600;font-size:13px;white-space:nowrap"></b>
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
            <div class="pbw-ex-head"><span class="pbw-ex-ctx" data-role="ex-ctx"></span></div>
            <div class="pbw-grid-wrap" data-role="grid"></div>
          </div>
          <div class="pbw-split" data-role="split" title="끌어서 너비 조정 · 두 번 누르면 처음대로"></div>
          <div class="pbw-rcol"><div class="pbw-rl" data-role="results"></div></div>
        </div>
        <div data-role="overlay"></div>
      </div>
      <div class="pbw-pv" data-role="preview"></div>`;
  const $ = role => qs(`[data-role="${role}"]`);
  const baseCard = qs('[data-act="base"]');
  const goBtn = qs('[data-act="go"]');
  const searchInput = $('search');

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
    baseCard.innerHTML = `<div class="pbw-row"><span class="pbw-dim pbw-sm">기반 · ${st.base.mode === 'direct' ? '직접 설정' : '프리셋'}</span>
      <span class="pbw-dim pbw-sm" style="margin-left:auto">설정 ›</span></div>
      <div class="pbw-base-sum" title="${esc(base.label)}">${esc(base.label)}</div>
      <div class="pbw-base-sum pbw-dim">${esc(paramsSummary(base.params))}</div>`;
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
  const PARAM_ROWS = [['model', 'Model'], ['sampler', 'Sampler'], ['scheduler', 'Scheduler'], ['size', 'Resolution'],
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
        const text = key === 'size'
          ? (shown('width') && shown('height') ? `${shown('width')} x ${shown('height')}` : '-')
          : String(shown(key) === '' ? '-' : shown(key));
        body = `<span class="pbw-bs-val">${esc(text)}${sesTag(key === 'size' ? 'width' : key)}</span>`;
      } else if (key === 'size') {
        const box = side => `<input class="param-input" type="number" step="64" min="64" max="2048" data-param="${side}" value="${own(side) ?? ''}" placeholder="${ses[side] ?? ''}">`;
        body = `<span class="pbw-bs-size">${box('width')}<span class="pbw-dim">x</span>${box('height')}</span>`;
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
    renderPreview();
  }

  // ---------------------------------------------------------------- 왼쪽 열
  // 캐릭터마다 카드 하나 [머리(캐릭터 N · 성별 표지 · ×) + 이름 칸 + 그 캐릭터의 칸 줄]. 캐릭터 밖 칸(2명일 때 2인 이상 자세 ·
  // 배경)은 칸 이름이 곧 카드 제목인 작은 카드로 따로 - 묶음 이름('함께')을 두지 않는다(사용자 11-20).
  // 이름 칸은 캐릭터 수가 바뀔 때만 새로 만든다(자동완성 붙이기 · 치는 중 초점을 지킨다) -
  // 칸 줄은 renderSlots 가, 성별 표지는 renderSubjects 가 제자리만 다시 그린다.
  function renderChars() {
    const box = $('chars');
    const count = st.count;
    box.innerHTML = Array.from({length: count}, (_, i) => `<div class="pbw-ccard"><div class="pbw-chead"><span>캐릭터 ${i + 1}</span><span class="pbw-subj" data-subj="${i}"></span>
        ${i > 0 ? `<button type="button" class="pbw-slot-x" style="margin-left:auto" data-act="char-remove" data-index="${i}" title="캐릭터 ${i + 1} 빼기" aria-label="캐릭터 ${i + 1} 빼기">×</button>` : ''}</div>
      <textarea class="pbw-text" rows="1" data-name="${i}" placeholder="캐릭터 이름 또는 프롬프트">${esc(st.names[i] || '')}</textarea>
      <div data-slots="${i + 1}"></div></div>`).join('') +
      (count < MAX_CHARACTERS ? '<button type="button" class="pbw-addc" data-act="char-add" title="둘째 캐릭터를 넣습니다 - 칸이 캐릭터마다 의상 · 표정으로 바뀌고 1인 자세는 빠집니다">+ 캐릭터 추가</button>' : '') +
      '<div class="pbw-solos" data-slots="0"></div>';
    box.querySelectorAll('textarea[data-name]').forEach(area => {
      if (typeof bindTagAssist === 'function') bindTagAssist(area, {});
    });
    renderSubjects();
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
      renderPreview();
    }, delay);
  }

  // 캐릭터 수 바꾸기. 칸 id 가 같은 칸(o1 · e1 · scene)은 고른 것 · 비교 · 탐색 자리를 그대로 둔다(풀이 같다).
  function setCount(count) {
    st.count = normalizeCast({count}).count;
    if (st.count < 2) {
      st.names[1] = '';
      st.subjects[1] = {gender: '', source: '', name: ''};
    }
    const keep = new Set(slots().map(slot => slot.id));
    for (const bag of [st.picks, st.chk, st.views]) for (const id of Object.keys(bag)) if (!keep.has(id)) delete bag[id];
    if (st.axis && !keep.has(st.axis)) st.axis = null;
    if (st.memo && !keep.has(st.memo.slotId)) { st.memo = null; st.note = ''; }
    st.pick = null;
    if (!keep.has(st.cur)) st.cur = 'o1';
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
      const label = slot.kind === 'link' ? '자세<small>2인 이상</small>' : esc(KIND_LABELS[slot.kind]);
      let marks = '';
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
        : `<span class="pbw-slot-empty">${cur ? '고르는 중 →' : '+ 고르기'}</span>`;
      const clear = pick?.tags?.length || axis
        ? `<button type="button" class="pbw-slot-x" data-clear="${slot.id}" title="비우기" aria-label="비우기">×</button>` : '<span></span>';
      return `<div class="pbw-slot${cur ? ' is-cur' : ''}${axis ? ' is-axis' : ''}" data-slot="${slot.id}">
        <span class="pbw-slot-k">${label}</span><span class="pbw-slot-v">${marks}${chips}</span>${clear}</div>`;
    };
    qsa('[data-slots]').forEach(holder => {
      const owner = Number(holder.dataset.slots);
      const mine = list.filter(slot => slot.owner === owner);
      // 캐릭터 밖 칸은 칸마다 작은 카드(칸 이름 = 카드 제목).
      holder.innerHTML = owner === 0
        ? mine.map(slot => `<div class="pbw-ccard is-solo">${slotHtml(slot)}</div>`).join('')
        : mine.map(slotHtml).join('');
    });
  }

  function renderLeftControls() {
    $('target').querySelectorAll('button').forEach(btn => btn.classList.toggle('is-on', btn.dataset.target === st.target));
    const n = st.axis ? axisSets().length : 1;
    goBtn.textContent = running() ? '■ 중지' : `▶ ${n}장 생성`;
    goBtn.title = running() ? '아직 대기 중인 생성을 큐에서 뺍니다(그리는 중인 한 장은 끝까지 갑니다)' : '기반 + 고른 칸으로 생성합니다';
  }

  // ---------------------------------------------------------------- 탐색
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
      ${badge}${picture}<div class="pbw-cap">${esc((set.tags || []).join(', '))}</div></div>`;
  }

  // 지금 그리드에 보이는 세트(id -> 세트) - 카드 누르기 · 체크가 세트 요약을 찾는다.
  let shownSets = new Map();

  async function renderExplorer() {
    const slot = slotById(st.cur) || slots()[0];
    st.cur = slot.id;
    const view = viewOf(slot.id);
    const owner = st.count > 1 && slot.owner > 0 ? `<span class="pbw-ex-own">캐릭터 ${slot.owner} ›</span> ` : '';
    $('ex-title').innerHTML = `${owner}${esc(KIND_LABELS[slot.kind])} 고르기`;
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
    cats.innerHTML = groups.map(group => `<button type="button" class="pbw-cat${view.mode === 'browse' && group.slot === view.cat ? ' is-on' : ''}" data-cat="${esc(group.slot)}"><span>${esc(group.label || group.slot)}</span><small>${(group.seeds || []).length}</small></button>`).join('');

    let seeds;
    if (view.mode === 'search') {
      seeds = view.hits;
      seedsBox.innerHTML = seeds.length
        ? `<div class="pbw-dim pbw-sm" style="padding:2px 5px">검색 '${esc(view.q)}' · ${seeds.length}</div>` + seeds.map(hit => `<div class="pbw-seed${hit.seed === view.seed ? ' is-on' : ''}" data-seed="${esc(hit.seed)}" title="${esc(hit.matched === hit.seed ? hit.seed : `${hit.seed} · 찾은 태그 ${hit.matched}`)}"><span>${esc(hit.ko || hit.seed)}</span><span>${hit.count}</span></div>`).join('')
        : `<div class="pbw-empty">'${esc(view.q)}' 결과 없음</div>`;
    } else {
      const group = groups.find(item => item.slot === view.cat);
      seeds = group?.seeds || [];
      // 소분류 머리글 + Danbooru 게시물 수. 표에 아직 없는 시드('분류 전')는 posts 가 없어 세트 수를 보인다.
      // 이름은 한글만(사용자 지시 11-20) - 영문 태그는 툴팁 첫 줄. 사전에 이름이 없으면 영문 그대로.
      const row = seed => {
        const shown = seed.posts != null ? formatPosts(seed.posts) : seed.sets;
        const tip = seed.posts != null ? `Danbooru 게시물 ${Number(seed.posts).toLocaleString()} · 세트 ${seed.sets}` : `세트 ${seed.sets}`;
        return `<div class="pbw-seed${seed.seed === view.seed ? ' is-on' : ''}" data-seed="${esc(seed.seed)}" title="${esc(`${seed.seed} · ${tip}`)}"><span>${esc(seed.ko || seed.seed)}</span><span>${shown}</span></div>`;
      };
      seedsBox.innerHTML = group?.subs
        ? group.subs.map(sub => `<div class="pbw-sub">${esc(sub.name)}</div>${sub.seeds.map(row).join('')}`).join('')
        : seeds.map(row).join('');
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
      sets = await setsOf(slot.kind, slot.pool, view.seed);
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

  async function runSearch(q) {
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
    if (viewOf(slot.id).q !== q) return;      // 그사이 다시 쳤다
    const bySeed = new Map();
    for (const row of Array.isArray(rows) ? rows : []) {
      if (slot.pool && row.pool !== slot.pool) continue;   // 칸 pool '' = 모든 풀
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
    const run = shownRun();
    if (!run) {
      box.innerHTML = '<div class="pbw-empty">[생성] 결과가 여기에 남습니다<br><span class="pbw-sm">그림 칸에서 2개 이상 체크하면 비교 생성 - 결과가 격자로 나옵니다</span></div>';
      return;
    }
    const at = st.runs.indexOf(run);
    const nav = st.runs.length > 1
      ? `<button type="button" class="pbw-btn" data-act="res-prev" title="앞선 생성"${at <= 0 ? ' disabled' : ''}>‹</button>
         <span class="pbw-dim pbw-sm">${at + 1} / ${st.runs.length}</span>
         <button type="button" class="pbw-btn" data-act="res-next" title="다음 생성"${at >= st.runs.length - 1 ? ' disabled' : ''}>›</button>` : '';
    const one = run.items.length === 1;
    box.innerHTML = `<div class="pbw-rl-head"><b style="font-weight:600;white-space:nowrap">${esc(run.label)}</b><span class="pbw-dim pbw-sm">· ${run.items.length}장 · ${esc(run.base)}</span>
        <span class="pbw-rl-nav">${nav}</span></div>
      <div class="pbw-rl-body${one ? ' is-one' : ''}">${one ? bigResult(run.items[0]) : `<div class="pbw-rgrid">${run.items.map((_, i) => resultCard(run, i)).join('')}</div>`}</div>
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
    const hadPick = Boolean(st.pick);
    st.pick = null;
    leaveCard();
    renderResults();
    if (hadPick) renderPreview();
  }

  // ---------------------------------------------------------------- 미리보기
  function renderPreview() {
    const box = $('preview');
    let variant = null;
    let title = '프롬프트 미리보기';
    if (st.pick) {
      const run = st.runs.find(r => r.id === st.pick[0]);
      const item = run?.items[st.pick[1]];
      if (run && item) {
        if (run.axis && item.set) variant = {slotId: run.axis, tags: item.set.tags, pool: item.set.pool};
        title = `고른 결과 · ${item.label}`;
      }
    }
    const axisSlot = slotById(st.axis);
    const rows = previewRows({
      cast: castNow(), target: st.target, names: st.names, picks: picksTags(), variant,
      axis: axisSlot ? {slotId: axisSlot.id, label: KIND_LABELS[axisSlot.kind], count: axisSets().length} : null,
    });
    const base = currentBase();
    const front = `<span class="pbw-src">[${esc(base.short)} 앞]</span>`;
    const back = `<span class="pbw-src">[${esc(base.short)} 뒤]</span>`;
    const hl = text => esc(text).replace(/\{[^}]*×\d+\}/g, m => `<span class="pbw-hl">${m}</span>`);
    const mainHtml = [front, hl(rows[0].text), back].filter(Boolean).join(', ');
    const lines = [{label: '메인', html: mainHtml}, ...rows.slice(1).map(row => ({label: row.label, html: hl(row.text) || '<span class="pbw-src">(비어 있음)</span>'})),
      {label: '네거티브', html: `<span class="pbw-src">[${esc(base.short)} 네거티브]</span>`}];
    box.innerHTML = `<div class="pbw-row"><a data-act="pv" style="cursor:pointer">${st.pvOpen ? '▾' : '▸'} <b style="font-weight:600">${esc(title)}</b></a>
      ${st.pvOpen ? '' : `<span class="pbw-pp pbw-dim pbw-pv-line">${mainHtml}</span>`}
      <span class="pbw-row" style="margin-left:auto"><button type="button" class="pbw-btn" data-act="copy">복사</button><button type="button" class="pbw-btn" data-act="to-main" title="가운데 몫(기반 앞뒤 제외)을 메인 프롬프트 칸에 넣습니다">메인 프롬프트로</button></span></div>` +
      (st.pvOpen ? `<div class="pbw-pp" style="margin-top:4px">${lines.map(line => `<div class="pbw-pr"><span class="pbw-dim" style="font-family:inherit">${line.label}</span><span>${line.html}</span></div>`).join('')}</div>` : '');
  }

  function previewText() {
    let variant = null;
    if (st.pick) {
      const run = st.runs.find(r => r.id === st.pick[0]);
      const item = run?.items[st.pick[1]];
      if (run?.axis && item?.set) variant = {slotId: run.axis, tags: item.set.tags, pool: item.set.pool};
    }
    const rows = previewRows({cast: castNow(), target: st.target, names: st.names, picks: picksTags(), variant});
    return rows;
  }

  // ---------------------------------------------------------------- 생성
  async function generate() {
    if (running()) return stop();
    const slotsNow = slots();
    const axisSlot = slotById(st.axis);
    const axis = axisSlot ? {slotId: axisSlot.id, sets: axisSets()} : null;
    const items = buildItems({cast: castNow(), target: st.target, names: st.names, picks: picksTags(), axis});
    if (items.length > MAX_ITEMS) { notify(`한 번에 ${MAX_ITEMS}장까지입니다 - 비교 체크를 줄여 주세요`, 'error'); return; }
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
      base: currentBase().label,
      items: items.map(item => ({label: item.label, set: item.set, status: 'pending', historyId: '', queueId: '', message: ''})),
    };
    void slotsNow;
    st.runs.push(run);
    if (st.runs.length > 30) st.runs.splice(0, st.runs.length - 30);
    st.pick = null;
    st.resRun = run.id;
    renderResults();
    renderLeftControls();
    renderPreview();
    try {
      const data = await sendJson(API.generate, 'POST', {
        request_id: requestId, base,
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
    st.picks[slotId] = {id: set.id, tags: [...(set.tags || [])], key: set.key, has_thumb: !!set.has_thumb, seed: set.seed, pool: set.pool || ''};
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
    renderNote();
    renderBand();
    void renderExplorer();
    renderResults();
    renderOverlay();
    renderPreview();
  }

  let booted = false;
  async function boot() {
    if (!booted) {
      booted = true;
      renderChars();
      for (let i = 0; i < st.count; i += 1) refreshSubject(i, 0);
    }
    renderAll();
    await Promise.all([loadBases(), refreshThumbStatus()]);
    renderAllBase();
  }

  // ---------------------------------------------------------------- 이벤트
  listen('click', event => {
    const t = event.target;
    const act = t.closest('[data-act]')?.dataset.act;
    if (act === 'res-go') { showRun(t.closest('[data-run]').dataset.run); return; }
    if (act === 'res-prev' || act === 'res-next') {
      const at = st.runs.indexOf(shownRun()) + (act === 'res-prev' ? -1 : 1);
      if (st.runs[at]) showRun(st.runs[at].id);
      return;
    }
    if (act === 'base') { st.baseOpen = !st.baseOpen; renderAllBase(); return; }
    if (act === 'base-close') { st.baseOpen = false; renderAllBase(); return; }
    if (act === 'go') { void generate(); return; }
    if (act === 'leave') { onLeave(); return; }
    if (act === 'char-add') { setCount(st.count + 1); return; }
    if (act === 'char-remove') { setCount(st.count - 1); return; }
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
    if (act === 'pv') { st.pvOpen = !st.pvOpen; renderPreview(); return; }
    if (act === 'related-back') { viewOf(st.cur).mode = viewOf(st.cur).q ? 'search' : 'browse'; void renderExplorer(); return; }
    if (act === 'thumb-dl') {
      sendJson(API.thumbDownload, 'POST', {}).then(() => refreshThumbStatus())
        .catch(error => notify(`받기를 시작하지 못했습니다: ${error.message}`, 'error'));
      return;
    }
    if (act === 'copy') {
      const rows = previewText();
      const base = currentBase();
      const text = rows.map(row => `${row.label}: ${row.key === 'main' ? [base.preset?.prefix || st.base.direct.prefix, row.text, base.preset?.postfix || st.base.direct.postfix].filter(Boolean).join(', ') : row.text}`).join('\n');
      win.navigator?.clipboard?.writeText?.(text).then(() => notify('복사했습니다', 'success'), () => notify('복사하지 못했습니다', 'error'));
      return;
    }
    if (act === 'to-main') {
      const rows = previewText();
      if (typeof applyMainPrompt === 'function') {
        applyMainPrompt(rows[0].text);
        notify(rows.length > 1 ? '메인 프롬프트에 넣었습니다 - 캐릭터 칸 몫은 옮기지 않았습니다' : '메인 프롬프트에 넣었습니다', 'success');
      }
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

    const tg = t.closest('[data-target]');
    if (tg) { st.target = tg.dataset.target; persist(); renderLeftControls(); renderPreview(); return; }
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
    const cat = t.closest('[data-cat]');
    if (cat) {
      const view = viewOf(st.cur);
      view.cat = cat.dataset.cat;
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
        renderPreview();
      }
      return;
    }
    const card = t.closest('[data-set]');
    if (card) {
      const set = shownSets.get(card.dataset.set);
      if (set) { putIntoSlot(st.cur, set); renderSlots(); renderPreview(); qsa('.pbw-card').forEach(el => el.classList.toggle('is-sel', el.dataset.set === set.id)); }
      return;
    }
    const res = t.closest('.pbw-rgrid .pbw-res');
    if (res && !res.classList.contains('is-cancel')) {
      st.pick = [res.dataset.run, Number(res.dataset.index)];
      st.pvOpen = true;
      renderResults();
      renderPreview();
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
    if (t.dataset.param) { setDirectParam(t); return; }
  });

  listen('input', event => {
    const t = event.target;
    if (t.dataset.name !== undefined) {
      st.names[Number(t.dataset.name)] = t.value;
      persist();
      renderPreview();
      refreshSubject(Number(t.dataset.name));
      return;
    }
    if (t === searchInput) {
      win.clearTimeout(searchTimer);
      const q = t.value;
      searchTimer = win.setTimeout(() => { void runSearch(q); }, 280);
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
        title: (set?.tags || []).join(', '),
        note: [badge, set?.seed].filter(Boolean).join(' · '),
      }, card.getBoundingClientRect());
    }, HOVER_DELAY_MS);
  });
  listen('mouseleave', leaveCard);
  listen('scroll', leaveCard, true);

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
  if (win.ResizeObserver) new win.ResizeObserver(() => fitResults()).observe($('results'));

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
    else leaveCard();
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
