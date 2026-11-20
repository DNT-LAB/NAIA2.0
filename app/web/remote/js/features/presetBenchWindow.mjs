// 프리셋 벤치 창(사용자 지시 2026-11-19 · 목업 3안 수정판 - "확정은 아니고 일단 이대로 구현").
//
//   ┌ 왼쪽 좁은 열 ─────┐┌ 탐색(위) ───────────────────────────────┐
//   │ 기반 요약 카드     ││ 칸 이름 · 풀 · [검색]                    │
//   │ 넣을 곳            ││ 분류 칩 / seed 목록 | 세트 카드           │
//   │ 캐릭터 글 · 성별   │├ 결과 띠(아래 붙박이) ─────────────────────┤
//   │ 칸(의상·자세 …)    ││ 마지막 실행 · [이전 기록] · [이걸로 고정] │
//   │ [N장 생성 | 중지]  │└──────────────────────────────────────────┘
//   └───────────────────┘ 아래: 프롬프트 미리보기(접힘) · [복사] [메인 프롬프트로]
//
// - 인원은 고르지 않는다(사용자 11-20) - [+ 캐릭터 추가] / × 로 1 ~ 2명. 맨 앞 인원 태그(1girl · 1boy …)는
//   캐릭터 글로 서버에 물어 정한다(이름 사전 gender · 글의 girl/boy 태그 · 모르면 girl). 목록은 여성 · 남성 세트를 한데 보인다.
// - 카드 누르기 = 그 칸에 넣기 · 카드 오른쪽 위 상자 = 비교에 넣기. 한 칸에서 둘 이상 체크하면 그 칸이 '비교 축' 이다.
//   다른 칸에서 비교를 시작하면 앞 축은 풀리고 [되돌리기] 를 띄운다.
// - 기반 = 프리셋(기본 = 현재 프리셋 · **이 창에서만** 쓴다) | 직접 설정(이름 붙여 저장 · 프리셋에서 받아오기 · 프리셋으로 보내기).
//   메인 화면의 현재 프리셋 · 세션 설정은 바꾸지 않는다 - 기반 값은 요청마다 서버가 overrides 로 싣는다.
// - 조립 규칙(무엇을 메인 · 캐릭터 칸에 싣나)은 presetBenchModel.mjs 에 있다. 이 파일은 그리기 · 서버 왕복만 한다.
// - 결과는 일반 생성처럼 결과 화면 · 히스토리에도 간다. 이 창은 image_meta 의 preset_bench_* 표식으로 제 것을 알아본다.

import {createDraggablePanel} from './draggablePanel.mjs?v=20260926-childalign';
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
};
const PARAM_KEYS = ['model', 'width', 'height', 'steps', 'cfg_scale', 'cfg_rescale', 'sampler', 'scheduler'];
const MAX_ITEMS = 20;

const PBW_CSS = `
.pbw-window .dragpanel-body { display: flex; flex-direction: column; min-height: 0; padding: 0; font-size: 12px; }
/* 왼쪽 열 272px(사용자 11-20 - 긴 태그 칩이 잘렸다) · 그림 카드는 140px 까지만(크게 보기는 마우스를 올려서). */
.pbw-cols { flex: 1 1 auto; min-height: 0; display: grid; grid-template-columns: 272px minmax(0, 1fr); }
/* 왼쪽 열은 한 단계 어둡게, 캐릭터 · 칸 카드는 밝게 - 오른쪽 탐색과 갈린다(사용자 11-20 목업). */
.pbw-left { min-height: 0; overflow-y: auto; border-right: 1px solid var(--border-glow); padding: 8px; display: flex; flex-direction: column; gap: 8px;
  background: var(--bg-primary); }
.pbw-right { min-width: 0; min-height: 0; display: flex; flex-direction: column; position: relative; }
.pbw-ex { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; padding: 8px; gap: 6px; }
.pbw-rs { flex: 0 0 auto; border-top: 1px solid var(--border-dim); padding: 6px 8px; background: var(--bg-surface); max-height: 46%; overflow-y: auto; }
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
.pbw-ex2 { flex: 1 1 auto; min-height: 0; display: grid; grid-template-columns: 124px 190px minmax(0, 1fr); gap: 8px; }
.pbw-ex2.is-related { grid-template-columns: 124px 0 minmax(0, 1fr); }
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
.pbw-grid-wrap { min-height: 0; overflow-y: auto; }
.pbw-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(100px, 140px)); gap: 6px; align-content: start; grid-auto-rows: max-content; }
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
.pbw-strip { display: flex; gap: 6px; overflow-x: auto; padding: 4px 0 2px; }
.pbw-res { flex: 0 0 96px; position: relative; border: 2px solid transparent; border-radius: 6px; overflow: hidden; cursor: pointer; background: #0c0c12; }
.pbw-res.is-pick { border-color: var(--accent); }
.pbw-res img { display: block; width: 100%; aspect-ratio: 3 / 4; object-fit: cover; }
.pbw-res-box { display: flex; align-items: center; justify-content: center; width: 100%; aspect-ratio: 3 / 4; color: #888; font-size: 11px; text-align: center; padding: 4px; box-sizing: border-box; }
.pbw-res.is-error .pbw-res-box { color: #ffb4b4; }
.pbw-res.is-cancel { background: transparent; border: 1px dashed var(--border-dim); }
.pbw-res-cap { padding: 2px 4px; font-size: 11px; color: var(--text-dim); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; background: var(--bg-surface); }
.pbw-pin { position: absolute; left: 4px; right: 4px; top: 4px; padding: 2px 0; font-size: 11px; border-radius: 4px; border: 1px solid var(--accent);
  background: rgba(12,12,18,0.9); color: var(--text-primary); cursor: pointer; font-family: inherit; }
.pbw-old { margin-top: 4px; padding-top: 4px; border-top: 1px solid var(--border-dim); }
.pbw-ov { position: absolute; inset: 0; z-index: 2; background: var(--bg-elevated, var(--bg-surface)); padding: 10px 12px; overflow-y: auto; border-left: 1px solid var(--accent); }
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
    out[key] = ['model', 'sampler', 'scheduler'].includes(key) ? String(value) : Number(value);
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

export function createPresetBenchWindow({
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
    oldOpen: false,
    base: {
      mode: saved.base?.mode === 'direct' ? 'direct' : 'preset',
      preset: String(saved.base?.preset || ''),
      directName: String(saved.base?.directName || ''),
      direct: {
        prefix: String(saved.base?.direct?.prefix || ''),
        postfix: String(saved.base?.direct?.postfix || ''),
        negative_prompt: String(saved.base?.direct?.negative_prompt || ''),
        params: cleanParams(saved.base?.direct?.params),
      },
    },
    exportTarget: '',
    exportName: '',
    loadFrom: '',
    newName: '',
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
        count: st.count, target: st.target, names: st.names, picks: st.picks,
        base: {mode: st.base.mode, preset: st.base.preset, directName: st.base.directName, direct: st.base.direct},
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

  // ---------------------------------------------------------------- 창
  const panel = createDraggablePanel({
    document: doc, window: win, id: 'presetBenchWindow', title: 'Presets',
    variant: 'em-overlay em-window pbw-window', storageKey: 'preset-bench',
    width: 1060, height: 700, minWidth: 720, maxWidth: 1800, minHeight: 460, resizable: true,
    escHtml,
    onOpen: () => { void boot(); onVisibilityChange(); },
    onClose: () => { leaveCard(); onVisibilityChange(); },
  });
  panel.body.innerHTML = `
    <div class="pbw-cols">
      <div class="pbw-left">
        <div class="pbw-base" data-act="base" title="기반 설정 열기"></div>
        <div class="pbw-row"><span class="pbw-dim pbw-sm">캐릭터 넣을 곳</span>
          <span class="pbw-seg" data-role="target"><button type="button" data-target="char">캐릭터칸</button><button type="button" data-target="main">메인</button></span></div>
        <div class="pbw-chars" data-role="chars"></div>
        <button type="button" class="pbw-btn is-primary pbw-go" data-act="go"></button>
      </div>
      <div class="pbw-right">
        <div class="pbw-ex">
          <div data-role="note"></div>
          <div data-role="band"></div>
          <div class="pbw-ex-head"><b data-role="ex-title" style="font-weight:600;font-size:13px;white-space:nowrap"></b><span class="pbw-ex-ctx" data-role="ex-ctx"></span>
            <input class="pbw-input" data-role="search" placeholder="태그 · 한국어 이름 검색"></div>
          <div class="pbw-ex2" data-role="ex2"><div class="pbw-cats" data-role="cats"></div><div class="pbw-seeds" data-role="seeds"></div><div class="pbw-grid-wrap" data-role="grid"></div></div>
        </div>
        <div class="pbw-rs" data-role="results"></div>
        <div data-role="overlay"></div>
      </div>
    </div>
    <div class="pbw-pv" data-role="preview"></div>`;
  const $ = role => panel.body.querySelector(`[data-role="${role}"]`);
  const baseCard = panel.body.querySelector('[data-act="base"]');
  const goBtn = panel.body.querySelector('[data-act="go"]');
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

  function renderOverlay() {
    const box = $('overlay');
    if (!st.baseOpen) { box.innerHTML = ''; return; }
    const presets = bases?.presets || [];
    const cur = currentBase();
    const head = `<div class="pbw-row"><b style="font-weight:600">기반 설정</b>
      <span class="pbw-seg" data-role="base-mode"><button type="button" data-mode="preset" class="${st.base.mode === 'preset' ? 'is-on' : ''}">프리셋</button><button type="button" data-mode="direct" class="${st.base.mode === 'direct' ? 'is-on' : ''}">직접 설정</button></span>
      <button type="button" class="pbw-btn" data-act="base-close" style="margin-left:auto">닫기</button></div>`;
    const presetOptions = (selected, {skipCurrent = false, blank = ''} = {}) =>
      (blank ? `<option value="">${esc(blank)}</option>` : '') +
      presets.filter(p => !(skipCurrent && p.is_current)).map(p =>
        `<option value="${esc(p.name)}"${p.name === selected ? ' selected' : ''}>${p.is_current ? '현재 · ' : ''}${esc(p.name)}</option>`).join('');
    if (st.base.mode === 'preset') {
      const preset = cur.preset;
      box.innerHTML = `<div class="pbw-ov">${head}
        <div class="pbw-dim pbw-sm" style="margin-top:6px">메인 화면의 현재 프리셋은 바뀌지 않습니다 - 이 창의 생성에만 씁니다.</div>
        <div class="pbw-form">
          <span class="pbw-dim">프리셋</span><select class="pbw-select" data-role="base-preset">${presetOptions(cur.label)}</select>
          <span class="pbw-dim">설정</span><span class="pbw-sm">${esc(paramsSummary(preset?.params))}</span>
          <span class="pbw-dim">앞</span><span class="pbw-pp pbw-dim">${esc(preset?.prefix || '(없음)')}</span>
          <span class="pbw-dim">뒤</span><span class="pbw-pp pbw-dim">${esc(preset?.postfix || '(없음)')}</span>
          <span class="pbw-dim">네거티브</span><span class="pbw-pp pbw-dim">${esc(preset?.negative_prompt || '(없음)')}</span>
          <span></span><span><button type="button" class="pbw-btn" data-act="to-direct">직접 설정으로 받아오기</button></span>
        </div></div>`;
      return;
    }
    const d = st.base.direct;
    const p = d.params;
    const num = (key, label, step = 1) => `<label>${label}<input class="pbw-input" type="number" step="${step}" data-param="${key}" value="${p[key] ?? ''}" placeholder="세션"></label>`;
    const txt = (key, label) => `<label>${label}<input class="pbw-input is-wide" data-param="${key}" value="${esc(p[key] ?? '')}" placeholder="세션"></label>`;
    box.innerHTML = `<div class="pbw-ov">${head}
      <div class="pbw-form">
        <span class="pbw-dim">저장본</span>
        <span class="pbw-row"><select class="pbw-select" data-role="direct-pick" style="flex:1;min-width:120px"><option value="">(저장 안 함)</option>${directs.map(item => `<option value="${esc(item.name)}"${item.name === st.base.directName ? ' selected' : ''}>${esc(item.name)}</option>`).join('')}</select>
          <button type="button" class="pbw-btn" data-act="direct-save"${st.base.directName ? '' : ' disabled'}>저장</button>
          <button type="button" class="pbw-btn" data-act="direct-delete"${st.base.directName ? '' : ' disabled'}>삭제</button></span>
        <span class="pbw-dim">새 이름</span>
        <span class="pbw-row"><input class="pbw-input" data-role="new-name" value="${esc(st.newName)}" placeholder="이름" maxlength="60" style="flex:1"><button type="button" class="pbw-btn" data-act="direct-save-as">새 이름으로 저장</button></span>
        <span class="pbw-dim">앞</span><textarea class="pbw-text" rows="2" data-field="prefix">${esc(d.prefix)}</textarea>
        <span class="pbw-dim">뒤</span><textarea class="pbw-text" rows="2" data-field="postfix">${esc(d.postfix)}</textarea>
        <span class="pbw-dim">네거티브</span><textarea class="pbw-text" rows="2" data-field="negative_prompt">${esc(d.negative_prompt)}</textarea>
        <span class="pbw-dim">설정</span>
        <span class="pbw-params">${txt('model', '모델')}${num('width', '가로', 64)}${num('height', '세로', 64)}${num('steps', '스텝')}${num('cfg_scale', 'CFG', 0.1)}${num('cfg_rescale', 'Rescale', 0.01)}${txt('sampler', '샘플러')}${txt('scheduler', '스케줄러')}</span>
        <span class="pbw-dim">받아오기</span>
        <span class="pbw-row"><select class="pbw-select" data-role="load-from">${presetOptions(st.loadFrom, {blank: '프리셋 고르기'})}</select><button type="button" class="pbw-btn" data-act="load-from">프리셋에서 받아오기</button></span>
        <span class="pbw-dim">보내기</span>
        <span class="pbw-row"><select class="pbw-select" data-role="export-target">${presetOptions(st.exportTarget, {skipCurrent: true, blank: '새 프리셋'})}</select>
          <input class="pbw-input" data-role="export-name" value="${esc(st.exportName)}" placeholder="새 프리셋 이름" maxlength="60"${st.exportTarget ? ' hidden' : ''}>
          <button type="button" class="pbw-btn" data-act="export">프리셋으로 보내기</button></span>
        <span></span><span class="pbw-dim pbw-sm">비운 설정은 메인 화면의 세션 값을 따릅니다. 지금 쓰는 프리셋에는 보낼 수 없습니다.</span>
      </div></div>`;
  }

  async function saveDirect(name) {
    const clean = String(name || '').trim();
    if (!clean) { notify('이름을 적어 주세요', 'error'); return; }
    try {
      await sendJson(API.directOne(clean), 'PUT', {...st.base.direct});
      st.base.directName = clean;
      st.newName = '';
      directs = (await getJson(API.direct)).items || [];
      persist();
      notify(`직접 설정 '${clean}' 을 저장했습니다`, 'success');
    } catch (error) {
      notify(`저장하지 못했습니다: ${error.message}`, 'error');
    }
    renderAllBase();
  }

  async function exportDirect(overwrite = false) {
    const name = String(st.exportTarget || st.exportName || '').trim();
    if (!name) { notify('보낼 프리셋 이름을 적어 주세요', 'error'); return; }
    try {
      await sendJson(API.directExport, 'POST', {preset: name, ...st.base.direct, overwrite});
      notify(`프리셋 '${name}' 으로 보냈습니다(현재 프리셋은 그대로)`, 'success');
      st.exportName = '';
      await loadBases();
    } catch (error) {
      if (error.status === 409 && error.data?.error === 'exists' && !overwrite) {
        if (win.confirm(`프리셋 '${name}' 이 이미 있습니다. 덮어쓸까요?`)) return exportDirect(true);
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
      negative_prompt: String(preset.negative_prompt || ''), params: cleanParams(preset.params),
    };
    st.base.directName = '';
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
    panel.body.querySelectorAll('[data-subj]').forEach(el => {
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
    panel.body.querySelectorAll('[data-slots]').forEach(holder => {
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
    if (thumbStatus?.downloading && panel.isOpen()) win.setTimeout(refreshThumbStatus, 2000);
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
    $('ex-title').innerHTML = `${owner}${esc(KIND_LABELS[slot.kind])}`;
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
      ctx.textContent = `· '${view.relatedTag}' 관련 의상`;
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
    ctx.textContent = `· ${seedName}`;
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
    ctx.textContent = `· ${seedName} · ${sets.length}세트`;
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

  // ---------------------------------------------------------------- 결과 띠
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

  function renderResults() {
    const box = $('results');
    // 첫 생성 전에는 띠를 두지 않는다(안내 한 줄이 자리만 차지했다) - 생성하면 미리보기 위로 펼쳐진다.
    box.hidden = !st.runs.length;
    if (!st.runs.length) { box.innerHTML = ''; return; }
    const last = st.runs[st.runs.length - 1];
    const older = st.runs.slice(0, -1).reverse();
    const runHead = run => `<b style="font-weight:600">${esc(run.label)}</b><span class="pbw-dim">· ${run.items.length}장 · ${esc(run.base)}</span>`;
    box.innerHTML = `<div class="pbw-row">${runHead(last)}${older.length ? `<a class="pbw-dim pbw-sm" data-act="old" style="margin-left:auto;cursor:pointer">이전 기록 ${older.length} ${st.oldOpen ? '▴' : '▾'}</a>` : ''}</div>
      <div class="pbw-strip">${last.items.map((_, i) => resultCard(last, i)).join('')}</div>` +
      (st.oldOpen ? older.map(run => `<div class="pbw-old"><div class="pbw-row pbw-sm">${runHead(run)}</div><div class="pbw-strip">${run.items.map((_, i) => resultCard(run, i)).join('')}</div></div>`).join('') : '');
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
  panel.body.addEventListener('click', event => {
    const t = event.target;
    const act = t.closest('[data-act]')?.dataset.act;
    if (act === 'base') { st.baseOpen = !st.baseOpen; renderAllBase(); return; }
    if (act === 'base-close') { st.baseOpen = false; renderAllBase(); return; }
    if (act === 'go') { void generate(); return; }
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
    if (act === 'old') { st.oldOpen = !st.oldOpen; renderResults(); return; }
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
    if (act === 'direct-save-as') { void saveDirect(st.newName); return; }
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
    if (act === 'load-from') {
      if (copyPresetToDirect(st.loadFrom)) { notify(`'${st.loadFrom}' 의 값을 받아왔습니다(아직 저장 안 함)`, 'success'); renderAllBase(); }
      return;
    }
    if (act === 'export') { void exportDirect(false); return; }

    const tg = t.closest('[data-target]');
    if (tg) { st.target = tg.dataset.target; persist(); renderLeftControls(); renderPreview(); return; }
    const mode = t.closest('[data-mode]');
    if (mode) { st.base.mode = mode.dataset.mode; persist(); renderAllBase(); return; }
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
        panel.body.querySelectorAll(`.pbw-ck[data-check="${CSS.escape(set.id)}"]`).forEach(el => {
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
      if (set) { putIntoSlot(st.cur, set); renderSlots(); renderPreview(); panel.body.querySelectorAll('.pbw-card').forEach(el => el.classList.toggle('is-sel', el.dataset.set === set.id)); }
      return;
    }
    const res = t.closest('.pbw-res');
    if (res && !res.classList.contains('is-cancel')) {
      st.pick = [res.dataset.run, Number(res.dataset.index)];
      st.pvOpen = true;
      renderResults();
      renderPreview();
    }
  });

  panel.body.addEventListener('change', event => {
    const t = event.target;
    if (t.dataset.role === 'base-preset') { st.base.preset = t.value; persist(); renderAllBase(); return; }
    if (t.dataset.role === 'direct-pick') {
      const item = directs.find(row => row.name === t.value);
      st.base.directName = item ? item.name : '';
      if (item) {
        st.base.direct = {prefix: item.prefix || '', postfix: item.postfix || '', negative_prompt: item.negative_prompt || '', params: cleanParams(item.params)};
      }
      persist();
      renderAllBase();
      return;
    }
    if (t.dataset.role === 'load-from') { st.loadFrom = t.value; return; }
    if (t.dataset.role === 'export-target') { st.exportTarget = t.value; renderOverlay(); return; }
  });

  panel.body.addEventListener('input', event => {
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
    if (t.dataset.param) {
      const key = t.dataset.param;
      if (t.value === '') delete st.base.direct.params[key];
      else st.base.direct.params[key] = ['model', 'sampler', 'scheduler'].includes(key) ? t.value : Number(t.value);
      persist();
      renderBaseCard();
      return;
    }
    if (t.dataset.role === 'new-name') { st.newName = t.value; return; }
    if (t.dataset.role === 'export-name') { st.exportName = t.value; return; }
  });

  // ---------------------------------------------------------------- 올리면 창 옆에 크게
  const HOVER_DELAY_MS = 140;      // 리모컨 · 아티스트 태그 관리 창과 같은 뜸 - 지나가는 마우스에는 안 뜬다
  let hoverCard = null;
  let hoverTimer = null;

  function leaveCard() {
    if (hoverTimer) { win.clearTimeout(hoverTimer); hoverTimer = null; }
    if (hoverCard) { hoverCard = null; hideZoom(); }
  }

  panel.body.addEventListener('mouseover', event => {
    const card = event.target?.closest?.('.pbw-card');
    if (card === hoverCard) return;
    leaveCard();
    const src = card?.querySelector('img.pbw-th')?.getAttribute('src');
    if (!src || typeof showZoom !== 'function') return;     // '미생성' 칸은 띄울 것이 없다
    hoverCard = card;
    hoverTimer = win.setTimeout(() => {
      hoverTimer = null;
      if (hoverCard !== card || !panel.isOpen()) return;
      const set = shownSets.get(card.dataset.set);
      const badge = set ? (POOL_BADGES[set.pool] || (LINK_POOLS[set.pool]?.badge ?? '')) : '';
      showZoom(card, {
        src,
        title: (set?.tags || []).join(', '),
        note: [badge, set?.seed].filter(Boolean).join(' · '),
      }, panel.el.getBoundingClientRect());
    }, HOVER_DELAY_MS);
  });
  panel.body.addEventListener('mouseleave', leaveCard);
  panel.body.addEventListener('scroll', leaveCard, true);
  panel.el.addEventListener('dragpanel-move', leaveCard);

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
    if (panel.isOpen()) { renderResults(); renderLeftControls(); }
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
    if (panel.isOpen()) { renderResults(); renderLeftControls(); }
    return true;
  }

  return {
    open: () => panel.open(),
    close: () => panel.close(),
    toggle: () => panel.toggle(),
    isOpen: () => panel.isOpen(),
    handleResultMeta,
    handleGenerationError,
  };
}

export {variantLabel};
