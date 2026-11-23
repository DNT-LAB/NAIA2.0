// Output Search · History - 그림을 태그 칩으로 찾고 고르고 지우는 화면(11-22 사용자 지정).
// 범위가 둘이다(같은 칩 · 같은 손):
//   이번 세션 = 메모리 히스토리(/api/history/*) - 저장 안 된 그림도 여기에만 있다. 새 그림이 오면 바로 붙는다.
//   전체     = 디스크 색인(/api/output-index/*) - 지난 실행 · 다른 폴더까지.
// 두 목록은 섞지 않는다(같은 그림이 두 번 보이지 않게) - 범위 단추로 읽는 곳만 바꾼다.
// 같은 본문을 두 곳이 쓴다: 앱 안의 떠 있는 창(outputSearchWindow.mjs)과 외부 브라우저 화면
// (output-search.html). 진입점이 둘이라도 본문은 하나다 - 한쪽만 고치는 일이 없게.
// 히스토리 브라우저 팝업의 손은 여기로 왔다: 크게 보기(imageLightbox) · 드래그 사각형 선택 · 저장(Ctrl+S) ·
// 다른 이름 저장 · 숏컷 바인딩 · 일괄정리. 삭제 · 저장 규칙은 앱이 넘기는 session 손(resultHistory.sessionActions)이
// 레일과 한 벌로 쥔다 - 여기서 다시 만들지 않는다. 외부 브라우저에는 그 손이 없어 단순한 대체 흐름을 쓴다.
// 전체 범위의 바꾸는 요청(삭제 · 폴더 열기 · 폴더 추가)은 서버가 이 PC 에서 온 요청만 받는다 - 원격이면 그 단추를 그리지 않는다.
// 최근 검색어 · 즐겨찾기(11-23 사용자 지정)는 서버 파일 하나(/api/output-index/saved) - 앱 창 · 외부 브라우저 · 휴대폰이 같은 목록.
// 담는 것은 검색어(포함 · 제외 · 본문)뿐이다. 출처 · 폴더 칩 · 범위는 지금 화면 것을 그대로 쓴다.
import {createImageLightbox} from './imageLightbox.mjs?v=20261122-b';

const API = '/api/output-index';
const HISTORY = '/api/history';
const SAVED = '/api/output-index/saved';
const RECENT_DELAY = 1500;     // 결과를 이만큼 보고 있으면 최근 검색어로 남긴다(칩을 고치는 중간 단계는 안 남게)
const PAGE = 80;
const PREFS_KEY = 'naia.outputSearch.prefs';
const DELETE_MODE_KEY = 'naia_result_delete_mode';     // 레일 · 뷰어 설정과 같은 키(한 벌)
// 칩은 셋만 둔다(사용자 11-23: NAIA · unknown 은 보통 필요 없는 이름). 셋이 다 켜져 있으면 거르지 않는다 -
// 그래서 NAIA 표식 · 메타 없는 그림도 그때는 그대로 나온다. 하나라도 끄면 켠 것만.
const SOURCES = ['NAI', 'WEBUI', 'ComfyUI'];
// 폴더별 보기(전체) = 폴더 카드 - 한 줄에 2개 · 카드마다 견본 3장 · 더보기로 그 폴더만 펼친다(사용자 11-23).
const FOLDER_PAGE = 30;
const FOLDER_SAMPLES = 3;
const SIZES = {s: {tile: 96, thumb: 192}, m: {tile: 136, thumb: 256}, l: {tile: 190, thumb: 384}};
// 크게 보기는 앱의 떠 있는 창(10150)보다 위, 확인 창(11000)보다 아래 - 크게 보며 지울 때 확인 창이 가려지지 않게.
const LIGHTBOX_Z = 10500;

export const OUTPUT_SEARCH_STYLE = `
.osr {display:flex;flex-direction:column;min-height:0;height:100%;font-size:12px;color:var(--text-primary,#e8e8f0)}
.osr [hidden] {display:none!important}
.osr.scope-session [data-only="all"], .osr.scope-all [data-only="session"] {display:none!important}
.osr button {font:inherit;color:inherit;background:transparent;border:1px solid var(--border-dim,#2a2a3d);
  border-radius:4px;padding:2px 7px;cursor:pointer;white-space:nowrap}
.osr button:hover {border-color:var(--border-glow,#3d3d5c);background:var(--bg-hover,rgba(255,255,255,.06))}
.osr button.on {color:var(--text-primary,#e8e8f0);background:rgba(124,106,239,.22);border-color:var(--accent,#7c6aef)}
.osr button.off {color:var(--text-dim,#9ea0b4);opacity:.7}
.osr button.warn {color:#e8c46a;border-color:rgba(232,196,106,.45);cursor:default}
.osr button.danger:hover {border-color:#e05561;color:#ff8a94}
.osr-row {display:flex;align-items:center;gap:5px;padding:5px 8px;border-bottom:1px solid var(--border-dim,#2a2a3d);flex-wrap:wrap}
.osr-seg {display:inline-flex;flex:none}
.osr-seg button {border-radius:0;margin-left:-1px}
.osr-seg button:first-child {border-radius:4px 0 0 4px;margin-left:0}
.osr-seg button:last-child {border-radius:0 4px 4px 0}
.osr-seg i {font-style:normal;color:var(--text-dim,#9ea0b4);margin-left:4px}
.osr-sep {width:1px;height:16px;background:var(--border-dim,#2a2a3d);margin:0 2px}
.osr-grow {flex:1}
.osr-dim {color:var(--text-dim,#9ea0b4);font-size:11px}
.osr-link {cursor:pointer;color:var(--accent-glow,#9d8bff)}
.osr-box {position:relative;flex:1 1 240px;display:flex;flex-wrap:wrap;align-items:center;gap:4px;min-height:26px;
  padding:2px 6px;background:var(--bg-deep,#0a0a0f);border:1px solid var(--border-glow,#3d3d5c);border-radius:4px;cursor:text}
.osr-box:focus-within {border-color:var(--accent,#7c6aef)}
.osr-box input {flex:1;min-width:110px;border:0;outline:none;background:transparent;color:inherit;font:inherit;padding:2px 0}
.osr {position:relative}
/* 포함 = 초록 · 제외 = 빨강 + 취소선 · 본문 글자 = 보라 - 칩은 포함 / 제외 묶음으로 나눠 그린다(사용자 11-23: 더 직관적으로). */
.osr-chip {display:inline-flex;align-items:center;gap:4px;border:1px solid rgba(92,184,122,.6);border-radius:4px;
  padding:0 5px;background:rgba(92,184,122,.16);color:#bfeccd;cursor:pointer;line-height:18px}
.osr-chip.ex {border-color:rgba(224,85,97,.6);background:rgba(224,85,97,.16);color:#ffb3b9}
.osr-chip.ex .osr-ct {text-decoration:line-through}
.osr-chip.tx {border-color:rgba(124,106,239,.55);background:rgba(124,106,239,.18);color:inherit}
.osr-grp {display:inline-flex;align-items:center;flex-wrap:wrap;gap:3px;margin-right:4px}
.osr-grp > em {font-style:normal;font-size:10.5px;color:var(--text-dim,#9ea0b4)}
.osr .osr-mode button.on.inc {color:#bfeccd;background:rgba(92,184,122,.2);border-color:rgba(92,184,122,.75)}
.osr .osr-mode button.on.exc {color:#ffb3b9;background:rgba(224,85,97,.18);border-color:rgba(224,85,97,.75)}
.osr button.fav-on {color:#e8c46a;border-color:rgba(232,196,106,.6)}
.osr button:disabled {opacity:.45;cursor:default}
.osr-sug .osr-sr {display:flex;align-items:center;gap:2px}
.osr-sug b {font-weight:400;border:1px solid var(--border-dim,#2a2a3d);border-radius:3px;padding:0 6px;margin-left:3px;
  line-height:16px;color:var(--text-muted,#c6c6d8)}
.osr-sug b[data-ex="0"]:hover {border-color:rgba(92,184,122,.8);color:#bfeccd;background:rgba(92,184,122,.2)}
.osr-sug b[data-ex="1"]:hover {border-color:rgba(224,85,97,.8);color:#ffb3b9;background:rgba(224,85,97,.2)}
.osr-row.osr-saved {flex-wrap:nowrap;gap:6px;padding:3px 8px}
.osr-saved > .osr-lab {flex:none;width:64px;font-size:11px;color:var(--text-dim,#9ea0b4)}
.osr-pills {flex:1;min-width:0;display:flex;gap:5px;overflow:hidden;flex-wrap:nowrap}
.osr-saved.open .osr-pills {flex-wrap:wrap;max-height:30vh;overflow:auto}
.osr-pill {flex:none;max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;line-height:18px;
  border:1px solid var(--border-dim,#2a2a3d);border-radius:11px;padding:0 9px;cursor:pointer;background:var(--bg-surface,#12121a)}
.osr-pill:hover {border-color:var(--border-glow,#3d3d5c);background:var(--bg-hover,rgba(255,255,255,.06))}
.osr-pex {color:#ff9aa3;text-decoration:line-through}
.osr-pill.fav {border-color:rgba(232,196,106,.45)}
.osr-pill.on {border-color:var(--accent,#7c6aef);background:rgba(124,106,239,.22)}
.osr .osr-morebtn {flex:none;border-color:transparent;color:var(--accent-glow,#9d8bff)}
.osr-menu {position:absolute;z-index:20;min-width:160px;padding:4px 0;background:var(--bg-card,#1a1a26);
  border:1px solid var(--border-glow,#3d3d5c);border-radius:6px;box-shadow:0 6px 20px rgba(0,0,0,.45)}
.osr-menu div {padding:5px 12px;cursor:pointer;white-space:nowrap}
.osr-menu div:hover {background:rgba(124,106,239,.22)}
.osr-menu div.danger {color:#ff8a94}
.osr-menu div.dis {opacity:.4;pointer-events:none}
.osr-dlg-bg {position:absolute;inset:0;z-index:30;background:rgba(0,0,0,.4);display:flex;align-items:flex-start;
  justify-content:center;padding-top:72px}
.osr-dlg {width:min(330px,92%);background:var(--bg-card,#1a1a26);border:1px solid var(--border-glow,#3d3d5c);border-radius:8px;
  padding:12px;display:flex;flex-direction:column;gap:8px;box-shadow:0 10px 30px rgba(0,0,0,.5)}
.osr-dlg input {background:var(--bg-deep,#0a0a0f);color:inherit;font:inherit;border:1px solid var(--accent,#7c6aef);
  border-radius:4px;padding:4px 7px;outline:none}
.osr-dlg-q {font-size:11px;color:var(--text-dim,#9ea0b4);word-break:break-word}
.osr-dlg-warn {font-size:11px;color:#e8c46a}
.osr-dlg-acts {display:flex;justify-content:flex-end;gap:6px}
.osr-chip .osr-x {opacity:.6;padding:0 1px}
.osr-chip .osr-x:hover {opacity:1}
.osr-sug {position:absolute;left:-1px;right:-1px;top:calc(100% + 2px);z-index:5;max-height:260px;overflow:auto;
  background:var(--bg-card,#1a1a26);border:1px solid var(--border-glow,#3d3d5c);border-radius:4px}
.osr-sug div {display:flex;justify-content:space-between;gap:10px;padding:4px 8px;cursor:pointer}
.osr-sug div.act,.osr-sug div:hover {background:rgba(124,106,239,.22)}
.osr-sug i {font-style:normal;color:var(--text-dim,#9ea0b4)}
.osr-addroot {display:flex;gap:5px;flex:1 1 100%}
.osr-addroot input {flex:1;min-width:0;background:var(--bg-deep,#0a0a0f);color:inherit;font:inherit;
  border:1px solid var(--border-glow,#3d3d5c);border-radius:4px;padding:2px 6px;outline:none}
.osr-body {flex:1;display:flex;min-height:0}
.osr-left {flex:1;min-width:0;display:flex;flex-direction:column}
.osr-selbar {display:flex;align-items:center;gap:6px;padding:4px 8px;background:rgba(124,106,239,.12);
  border-bottom:1px solid var(--border-dim,#2a2a3d)}
.osr-list {position:relative;flex:1;min-height:0;overflow:auto;padding:4px 6px 10px;user-select:none;outline:none}
.osr-marq {position:absolute;z-index:3;border:1px solid var(--accent-glow,#9d8bff);background:rgba(124,106,239,.14);pointer-events:none}
.osr-fold {display:flex;justify-content:space-between;padding:6px 2px 3px;color:var(--text-dim,#9ea0b4);font-size:11px;
  border-bottom:1px solid var(--border-dim,#2a2a3d);margin-bottom:3px}
.osr-grid {display:grid;grid-template-columns:repeat(auto-fill,minmax(var(--osr-tile,136px),1fr));gap:3px}
.osr-th {position:relative;aspect-ratio:7/9;background:var(--bg-surface,#12121a);border:2px solid transparent;
  border-radius:3px;overflow:hidden;cursor:pointer}
.osr-th img {width:100%;height:100%;object-fit:cover;display:block;pointer-events:none}
.osr-th.sel {border-color:var(--accent-glow,#9d8bff)}
.osr-th.cur {border-color:#e8c46a}
.osr-th .osr-tick {position:absolute;top:3px;left:3px;width:14px;height:14px;border-radius:3px;font-size:10px;line-height:14px;
  text-align:center;background:var(--accent,#7c6aef);color:#fff}
.osr-th .osr-badge {position:absolute;right:3px;bottom:3px;padding:0 4px;border-radius:3px;font-size:10px;line-height:14px;
  background:rgba(232,196,106,.9);color:#2a1d00}
.osr-more {padding:10px;text-align:center;color:var(--text-dim,#9ea0b4);font-size:11px}
.osr-right {width:290px;flex:none;border-left:1px solid var(--border-dim,#2a2a3d);overflow:auto;padding:8px;
  display:flex;flex-direction:column;gap:6px}
.osr-prev {aspect-ratio:7/9;max-height:52vh;background:var(--bg-surface,#12121a);border-radius:3px;display:flex;
  align-items:center;justify-content:center;overflow:hidden;cursor:zoom-in}
.osr-prev img {max-width:100%;max-height:100%;object-fit:contain}
.osr-path {word-break:break-all;color:var(--text-dim,#9ea0b4);font-size:11px}
.osr-meta {display:flex;flex-wrap:wrap;gap:4px}
.osr-meta span {border:1px solid var(--border-dim,#2a2a3d);border-radius:3px;padding:0 5px;font-size:11px;color:var(--text-muted,#c6c6d8)}
.osr-meta span.unsaved {border-color:rgba(232,196,106,.55);color:#e8c46a}
.osr-prompt {font-size:11px;line-height:1.45;color:var(--text-muted,#c6c6d8);border:1px solid var(--border-dim,#2a2a3d);
  border-radius:3px;padding:5px 6px;background:var(--bg-deep,#0a0a0f);max-height:180px;overflow:auto;white-space:pre-wrap;word-break:break-word}
.osr-hl {background:rgba(124,106,239,.3);color:var(--text-primary,#e8e8f0);border-radius:2px}
.osr-acts {display:flex;flex-wrap:wrap;gap:4px}
.osr-note {font-size:10.5px;color:var(--text-dim,#9ea0b4)}
.osr-empty {padding:24px 10px;text-align:center;color:var(--text-dim,#9ea0b4)}
.osr.narrow .osr-right {display:none}
.osr-cards {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;align-items:start}
.osr.narrow .osr-cards {grid-template-columns:minmax(0,1fr)}
.osr-card {border:1px solid var(--border-dim,#2a2a3d);border-radius:5px;padding:5px;background:var(--bg-surface,#12121a)}
.osr-card-h {display:flex;align-items:baseline;gap:6px;padding:1px 2px 5px}
.osr-card-t {flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:pointer;font-size:12.5px}
.osr-card-t:hover {color:var(--accent-glow,#9d8bff)}
.osr-card-g {display:grid;grid-template-columns:repeat(${FOLDER_SAMPLES},minmax(0,1fr)) 58px;gap:3px}
.osr .osr-card-more {display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;padding:0;
  border:1px dashed var(--border-glow,#3d3d5c);color:var(--accent-glow,#9d8bff);font-size:11px;line-height:1.35;white-space:normal}
.osr-drill {display:flex;align-items:center;gap:8px;padding:4px 8px;border-bottom:1px solid var(--border-dim,#2a2a3d)}
.osr-drill b {font-weight:500}
/* 스크롤 막대는 흰색으로 - 어두운 판에서 안 보였다(사용자 11-23). scrollbar-color 를 주면 크로미움이 아래를 버린다. */
.osr-list::-webkit-scrollbar {width:12px;height:12px}
.osr-right::-webkit-scrollbar, .osr-prompt::-webkit-scrollbar, .osr-sug::-webkit-scrollbar, .osr-pills::-webkit-scrollbar {width:8px}
.osr-list::-webkit-scrollbar-track, .osr-right::-webkit-scrollbar-track,
.osr-prompt::-webkit-scrollbar-track, .osr-sug::-webkit-scrollbar-track, .osr-pills::-webkit-scrollbar-track {background:rgba(255,255,255,.06)}
.osr-list::-webkit-scrollbar-thumb, .osr-right::-webkit-scrollbar-thumb,
.osr-prompt::-webkit-scrollbar-thumb, .osr-sug::-webkit-scrollbar-thumb, .osr-pills::-webkit-scrollbar-thumb {
  background:rgba(255,255,255,.82);border-radius:6px;border:2px solid transparent;background-clip:padding-box;min-height:40px}
.osr-list::-webkit-scrollbar-thumb:hover, .osr-right::-webkit-scrollbar-thumb:hover,
.osr-prompt::-webkit-scrollbar-thumb:hover, .osr-sug::-webkit-scrollbar-thumb:hover,
.osr-pills::-webkit-scrollbar-thumb:hover {background-color:#fff}
`;

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[c]);
}

function fmt(n) {
  return Number(n || 0).toLocaleString('en-US');
}

function folderOf(path) {
  const i = String(path || '').lastIndexOf('/');
  return i < 0 ? '' : path.slice(0, i);
}

function nameOf(path) {
  const i = String(path || '').lastIndexOf('/');
  return i < 0 ? String(path || '') : path.slice(i + 1);
}

/** 폴더 경로를 읽기 쉽게 - 20261121_203645 -> 2026-11-21 20:36 · 20261121 -> 2026-11-21. 다른 이름은 그대로. */
export function folderLabel(rel) {
  if (!rel) return '(뿌리)';
  return String(rel).split('/').map(seg => {
    let m = /^(\d{4})(\d{2})(\d{2})[_-](\d{2})(\d{2})(\d{2})?$/.exec(seg);
    if (m) return `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}`;
    m = /^(\d{4})(\d{2})(\d{2})$/.exec(seg);
    return m ? `${m[1]}-${m[2]}-${m[3]}` : seg;
  }).join(' / ');
}

function rootLabel(r) {
  return r.kind === 'save' ? '저장 폴더' : r.kind === 'quicksave' ? '빠른 저장'
    : nameOf(String(r.path || '').replace(/\\/g, '/')) || `폴더 ${r.id}`;
}

function readPrefs(storage) {
  try {
    const raw = JSON.parse(storage?.getItem(PREFS_KEY) || '{}');
    return {
      sort: raw.sort === 'mtime_asc' ? 'mtime_asc' : 'mtime_desc',
      view: raw.view === 'flat' ? 'flat' : 'folder',
      size: SIZES[raw.size] ? raw.size : 'm',
    };
  } catch (_) {
    return {sort: 'mtime_desc', view: 'folder', size: 'm'};
  }
}

/** 칩 하나 = {kind:'tag'|'text', text, exact, ex}. 서버 문법: exact 는 `*tag`, 아니면 부분 일치. */
export function chipQuery(chips) {
  const include = [], exclude = [];
  let text = '';
  for (const chip of chips) {
    if (chip.kind === 'text') { text = chip.text; continue; }
    (chip.ex ? exclude : include).push(chip.exact ? `*${chip.text}` : chip.text);
  }
  return {include, exclude, text};
}

/** 같은 검색인지 - 칩 순서 · 대소문자는 상관없다(서버 saved_searches.query_key 와 같은 규칙). */
export function queryKey(q) {
  const tags = list => [...(list || [])].map(t => String(t).toLowerCase()).sort();
  return JSON.stringify([tags(q?.include), tags(q?.exclude), String(q?.text || '').trim().toLowerCase()]);
}

export function emptyQuery(q) {
  return !(q?.include?.length || q?.exclude?.length || String(q?.text || '').trim());
}

/** 알약에 쓰는 한 줄 - 정확히(*tag)는 그대로 · 부분은 ~ · 제외는 − · 본문은 따옴표. */
export function querySummary(q) {
  const tag = t => (String(t).startsWith('*') ? String(t).slice(1) : `~${t}`);
  const parts = [...(q?.include || []).map(tag), ...(q?.exclude || []).map(t => `−${tag(t)}`)];
  if (q?.text) parts.push(`“${q.text}”`);
  return parts.join(' · ');
}

/** 알약 안쪽 - 제외는 칩처럼 빨강 + 취소선(글자 '−~tag' 보다 한눈에 보인다). */
export function queryPillHtml(q) {
  const tag = t => (String(t).startsWith('*') ? String(t).slice(1) : `~${t}`);
  const parts = [...(q?.include || []).map(t => esc(tag(t))),
    ...(q?.exclude || []).map(t => `<span class="osr-pex">${esc(tag(t))}</span>`)];
  if (q?.text) parts.push(`“${esc(q.text)}”`);
  return parts.join(' · ');
}

/** 입력칸 글자 -> {text, ex}. 앞에 - 를 붙이면 제외, + 면 포함. 없으면 지금 고른 쪽(defaultEx).
 *  -_- 같은 태그가 있어 - 뒤에 _ · - 가 오면 표식이 아니다. */
export function typedTag(raw, defaultEx = false) {
  const value = String(raw || '').trim();
  if (/^[-−](?![_\-−])/.test(value)) return {text: value.slice(1).trim(), ex: true};
  if (/^\+(?![_+])/.test(value)) return {text: value.slice(1).trim(), ex: false};
  return {text: value, ex: Boolean(defaultEx)};
}

/** 프롬프트에서 포함 칩에 걸린 태그를 강조한다. 부분 칩은 서버가 펼친 목록(matched)으로 판정한다. */
export function highlightPrompt(prompt, chips, matched = []) {
  const exact = new Set(chips.filter(c => c.kind === 'tag' && !c.ex).map(c => c.text.toLowerCase()));
  for (const tag of matched) exact.add(String(tag).toLowerCase());
  const partial = chips.filter(c => c.kind === 'tag' && !c.ex && !c.exact).map(c => c.text.toLowerCase());
  return String(prompt || '').split(/(,)/).map(part => {
    if (part === ',') return ',';
    const bare = part.trim().toLowerCase().replace(/^[\d.]+::/, '').replace(/::$/, '').replace(/[(){}\[\]]/g, '').trim();
    const hit = bare && (exact.has(bare) || partial.some(p => bare.includes(p)));
    if (!hit) return esc(part);
    const lead = part.match(/^\s*/)[0];
    return `${lead}<span class="osr-hl">${esc(part.trim())}</span>${part.slice(lead.length + part.trim().length)}`;
  }).join('');
}

// ── 두 범위의 항목을 한 모양으로 ───────────────────────────────────────────────
function normAll(r) {
  return {
    key: `r${r.row}`, row: r.row, path: r.path || '', name: nameOf(r.path), saved: true,
    mtime: r.mtime, width: r.width, height: r.height, source: r.source, seed: r.seed, prompt: r.prompt || '',
    thumb: size => `${API}/thumb?row=${r.row}&size=${size}`,
    full: `${API}/file?row=${r.row}`,
  };
}

function normSession(r) {
  const file = String(r.file_path || '').replace(/\\/g, '/');
  const id = encodeURIComponent(r.history_id || '');
  return {
    key: r.rel_path, rel: r.rel_path, hid: r.history_id, path: file, name: file ? nameOf(file) : (r.filename || ''),
    saved: r.saved != null ? Boolean(r.saved) : Boolean(file),
    mtime: r.mtime, width: r.width, height: r.height, source: r.api_mode || r.model || '', seed: r.seed,
    prompt: r.prompt || '',
    thumb: size => `${HISTORY}/thumb/${id}?size=${size}`,
    full: `${HISTORY}/image/${id}`,
  };
}

export function createOutputSearch({
  document: doc,
  window: win,
  host,
  storage = null,
  initial = {},
  // 앱 안에서만 오는 손: 메인 프롬프트에 넣기. 없으면 [프롬프트] 단추는 복사로 동작한다.
  applyPrompt = null,
  // 앱 안에서만 오는 손: 이번 세션의 삭제 · 저장 · 메인에 띄우기 · 바인딩(resultHistory.sessionActions).
  session = null,
  openUrl = url => { win.open(url, '_blank'); return true; },
  confirmAsk = async message => win.confirm(message),
  toast = () => {},
  onStatus = () => {},
  onScope = () => {},
}) {
  const prefs = readPrefs(storage);
  const st = {
    scope: initial.scope === 'all' ? 'all' : 'session',
    chips: [],
    sources: new Set(SOURCES),
    roots: null,          // null = 전부. 아니면 켠 root id 집합
    allRoots: [],
    local: false,
    items: [], count: 0, matched: [], matchedTotal: 0,
    total: 0, unsaved: 0, pendingNew: 0,     // 이번 세션: 전체 장수 · 미저장 · 거르는 중에 온 새 그림
    loading: false, done: false, seq: 0,
    sel: new Set(), anchor: -1, current: null,
    partial: false, rows: 0,
    textMode: false,
    // 폴더 카드(전체 · 폴더별): 받은 폴더 차례 · 폴더 정보 · 그린 카드 수. 견본 그림은 items 에 들고 item.dir 로 잇는다.
    folderOrder: [], folderInfo: new Map(), folderCount: 0, cardsDrawn: 0,
    dir: null,            // 더보기로 펼친 폴더 {id, rel, root, count} - 있으면 그 폴더만 한 줄로
    ovCache: null,        // 펼치기 전 카드 목록 - 돌아갈 때 받은 자리 그대로
    mode: 'inc',          // Enter 로 넣는 태그가 갈 곳 - 'inc' 포함 · 'ex' 제외
    saved: {recent: [], favorites: []},
    open: {recent: false, fav: false},     // 더보기로 펼친 줄
  };
  for (const tag of initial.include || []) st.chips.push(parseChip(tag, false));
  for (const tag of initial.exclude || []) st.chips.push(parseChip(tag, true));
  if (initial.text) st.chips.push({kind: 'text', text: String(initial.text)});
  const lightbox = createImageLightbox({document: doc, escHtml: esc});

  function parseChip(raw, ex) {
    const text = String(raw || '').trim();
    const exact = text.startsWith('*');
    return {kind: 'tag', text: (exact ? text.slice(1) : text).toLowerCase(), exact, ex};
  }

  host.classList.add('osr');
  host.innerHTML = `
    <div class="osr-row">
      <span class="osr-seg" role="tablist" aria-label="범위">
        <button type="button" data-scope="session" title="이번 실행에 만든 그림 - 저장 안 된 것 포함">이번 세션<i data-scount></i></button>
        <button type="button" data-scope="all" title="저장된 그림 전체 - 지난 실행 · 추가한 폴더 포함">전체<i data-acount></i></button>
      </span>
      <span class="osr-seg osr-mode" aria-label="Enter 로 넣을 곳">
        <button type="button" class="inc" data-mode="inc" title="Enter 로 넣는 태그 = 포함 · 앞에 - 를 붙이면 제외 · Shift+Enter 는 반대쪽">+ 포함</button>
        <button type="button" class="exc" data-mode="ex" title="Enter 로 넣는 태그 = 제외 · 앞에 + 를 붙이면 포함 · Shift+Enter 는 반대쪽">− 제외</button>
      </span>
      <div class="osr-box" data-box>
        <span class="osr-chips" data-chips></span>
        <input data-input type="text" placeholder="태그 추가" autocomplete="off" spellcheck="false" aria-label="태그 검색">
        <div class="osr-sug" data-sug hidden></div>
      </div>
      <button type="button" data-act="fav-save" title="지금 검색어를 즐겨찾기로">☆ 저장</button>
      <button type="button" data-act="text" title="프롬프트 본문에서 글자 그대로 찾기">본문</button>
      <span class="osr-sep"></span>
      <button type="button" data-act="sort" title="정렬"></button>
      <button type="button" data-act="view" data-only="all" title="보기 방식"></button>
      <button type="button" data-size="s" title="작게">S</button>
      <button type="button" data-size="m" title="보통">M</button>
      <button type="button" data-size="l" title="크게">L</button>
    </div>
    <div class="osr-row" data-filters>
      <span data-only="all" data-sources></span>
      <span data-only="all" class="osr-sep"></span>
      <span data-only="all" data-roots></span>
      <button type="button" data-only="all" data-act="addroot" data-local title="색인할 폴더 추가 (이 PC 에서만)" hidden>+ 폴더</button>
      <button type="button" data-only="session" data-act="saveall" title="저장 안 된 그림을 모두 저장 폴더로">미저장 모두 저장</button>
      <button type="button" data-only="session" data-act="zip" title="저장 안 된 그림을 zip 으로 받기">미저장 zip</button>
      <button type="button" data-only="session" data-act="clearall" class="danger" title="히스토리를 통째로 비웁니다 — 저장된 파일은 그대로 남습니다">일괄정리</button>
      <span class="osr-grow"></span>
      <span class="osr-dim" data-count></span>
    </div>
    <div class="osr-row" data-addroot-row hidden>
      <div class="osr-addroot">
        <input data-rootpath type="text" placeholder="D:\\images\\naia_old" spellcheck="false" aria-label="폴더 경로">
        <button type="button" data-act="addroot-ok">추가</button>
        <button type="button" data-act="addroot-cancel">취소</button>
      </div>
    </div>
    <div class="osr-row osr-saved" data-saved="recent">
      <span class="osr-lab">최근</span><div class="osr-pills" data-pills="recent"></div>
      <button type="button" class="osr-morebtn" data-more="recent">더보기 ▾</button>
    </div>
    <div class="osr-row osr-saved" data-saved="fav">
      <span class="osr-lab">★ 즐겨찾기</span><div class="osr-pills" data-pills="fav"></div>
      <button type="button" class="osr-morebtn" data-more="fav">더보기 ▾</button>
    </div>
    <div class="osr-body">
      <div class="osr-left">
        <div class="osr-selbar" data-selbar hidden>
          <span data-selcount></span>
          <span class="osr-grow"></span>
          <button type="button" data-only="session" data-act="selsave" title="고른 그림을 빠른 저장 폴더로 (Ctrl+S)">저장</button>
          <button type="button" data-only="session" data-act="selsaveas" data-saveas title="고른 그림을 다른 곳에 저장">다른 이름</button>
          <button type="button" data-act="seldelete" class="danger" title="고른 그림 삭제 (Del)">삭제</button>
          <button type="button" data-act="selclear" title="선택 해제 (Esc)">해제</button>
        </div>
        <div class="osr-drill" data-drill hidden></div>
        <div class="osr-list" data-list tabindex="0"></div>
      </div>
      <div class="osr-right" data-detail></div>
    </div>`;
  const $ = sel => host.querySelector(sel);
  const input = $('[data-input]');
  const list = $('[data-list]');
  const isSession = () => st.scope === 'session';
  // 폴더 카드 판 - 전체 범위 · 폴더별 · 펼친 폴더 없음.
  const overview = () => !isSession() && prefs.view === 'folder' && !st.dir;

  // ── 요청 ──────────────────────────────────────────────────────────────────
  async function req(url, body) {
    const options = body === undefined ? {cache: 'no-store'}
      : {method: 'POST', cache: 'no-store', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)};
    const response = await win.fetch(url, options);
    let data = null;
    try { data = await response.json(); } catch (_) { data = null; }
    if (!response.ok) {
      if (response.status === 403) throw new Error('이 PC 에서 연 화면에서만 할 수 있습니다.');
      throw new Error((data && (data.error || data.detail)) || `요청 실패 (${response.status})`);
    }
    return data;
  }
  const api = (path, body) => req(API + path, body);

  let statusTimer = 0;
  async function loadStatus() {
    win.clearTimeout(statusTimer);
    let status;
    try { status = await api('/status'); } catch (_) { statusTimer = win.setTimeout(loadStatus, 5000); return; }
    const wasPartial = st.partial;
    st.partial = Boolean(status.partial);
    st.rows = status.live_rows || 0;
    st.allRoots = status.roots || [];
    // 원격 화면에는 서버가 경로를 빼서 준다 - 그것으로 '이 PC' 인지 안다.
    st.local = st.allRoots.length > 0 && st.allRoots.every(r => typeof r.path === 'string');
    host.querySelectorAll('[data-local]').forEach(node => { node.hidden = !st.local; });
    drawRoots();
    drawScope();
    onStatus({partial: st.partial, rows: st.rows, foldersDone: status.folders_done, pending: status.pending_dirs});
    if (st.partial || status.running) statusTimer = win.setTimeout(loadStatus, 2000);
    if (wasPartial && !st.partial && !isSession()) runQuery();
  }

  // ── 범위 ──────────────────────────────────────────────────────────────────
  function drawScope() {
    host.classList.toggle('scope-session', isSession());
    host.classList.toggle('scope-all', !isSession());
    host.querySelectorAll('[data-scope]').forEach(b => b.classList.toggle('on', b.dataset.scope === st.scope));
    $('[data-scount]').textContent = st.total ? fmt(st.total) : '';
    $('[data-acount]').textContent = st.rows ? fmt(st.rows) : '';
    // 다른 이름 저장은 브라우저가 파일 선택 창을 줄 때만 된다.
    host.querySelectorAll('[data-saveas]').forEach(n => { n.hidden = !(session && session.canSaveAs?.()); });
  }
  function setScope(scope) {
    if (scope === st.scope) return;
    st.scope = scope === 'all' ? 'all' : 'session';
    st.pendingNew = 0;
    st.dir = null;
    lightbox.close();
    drawScope();
    drawPrefs();
    closeSug();
    runQuery();
    // 전체 장수는 상태(status)가 준다 - 창을 연 뒤 저장된 그림을 범위를 바꿀 때 다시 센다.
    loadStatus();
    onScope(st.scope);
  }

  // ── 칩 · 후보 ─────────────────────────────────────────────────────────────
  function drawChips() {
    const one = (chip, i) => {
      const cls = chip.kind === 'text' ? 'tx' : chip.ex ? 'ex' : '';
      const mark = chip.kind === 'text' ? '“' : chip.exact ? '' : '~';
      const what = chip.exact ? '이 태그만' : '이 글자가 든 태그 전부';
      const tip = chip.kind === 'text' ? '본문 글자 검색' : `${what} · 클릭: ${chip.ex ? '포함으로' : '제외로'}`;
      return `<span class="osr-chip ${cls}" data-chip="${i}" title="${tip}">${mark}<span class="osr-ct">${esc(chip.text)}</span>`
        + `<span class="osr-x" data-rm="${i}" title="빼기">×</span></span>`;
    };
    const indexed = st.chips.map((chip, i) => [chip, i]);
    const group = (label, part) => (part.length
      ? `<span class="osr-grp"><em>${label}</em>${part.map(([c, i]) => one(c, i)).join('')}</span>` : '');
    $('[data-chips]').innerHTML = group('포함', indexed.filter(([c]) => c.kind === 'tag' && !c.ex))
      + group('제외', indexed.filter(([c]) => c.kind === 'tag' && c.ex))
      + indexed.filter(([c]) => c.kind === 'text').map(([c, i]) => one(c, i)).join('');
    $('[data-act="text"]').classList.toggle('on', st.textMode);
    host.querySelectorAll('[data-mode]').forEach(b => b.classList.toggle('on', (b.dataset.mode === 'ex') === (st.mode === 'ex')));
    input.placeholder = st.textMode ? '본문 글자 (Enter)' : st.mode === 'ex' ? '제외할 태그' : '포함할 태그';
    drawSaved();
  }
  const typed = () => typedTag(input.value, st.mode === 'ex');

  let sugSeq = 0, sugTimer = 0, sugItems = [], sugAct = -1;
  function closeSug() { $('[data-sug]').hidden = true; sugItems = []; sugAct = -1; }
  function drawSug() {
    const box = $('[data-sug]');
    const {text: q, ex} = typed();
    if (!q || st.textMode) { closeSug(); return; }
    // 줄마다 + 포함 · − 제외 - 줄 자체를 누르거나 Enter 면 지금 고른 쪽(앞에 - 를 쳤으면 제외).
    const pm = i => `<b data-sug-add="${i}" data-ex="0" title="포함">+</b><b data-sug-add="${i}" data-ex="1" title="제외">−</b>`;
    const rows = [`<div data-sug-i="-1" class="${sugAct < 0 ? 'act' : ''}"><span>~ ${esc(q)} <i>${ex ? '제외' : '포함'} 전부</i></span>`
      + `<span class="osr-sr"><i>Enter</i>${pm(-1)}</span></div>`];
    sugItems.forEach((item, i) => rows.push(
      `<div data-sug-i="${i}" class="${sugAct === i ? 'act' : ''}"><span>${esc(item.tag)}</span>`
      + `<span class="osr-sr"><i>${fmt(item.condition_count ?? item.count)}</i>${pm(i)}</span></div>`));
    box.innerHTML = rows.join('');
    box.hidden = false;
  }
  async function loadSug() {
    const q = typed().text;
    const seq = ++sugSeq;
    if (!q || st.textMode) { closeSug(); return; }
    const {include, exclude} = chipQuery(st.chips);
    const params = new URLSearchParams({q, limit: '12'});
    include.forEach(t => params.append('include', t));
    exclude.forEach(t => params.append('exclude', t));
    try {
      const data = await req(`${isSession() ? HISTORY : API}/suggest?${params.toString()}`);
      if (seq !== sugSeq) return;
      sugItems = data.items || [];
      sugAct = -1;
      drawSug();
    } catch (_) { /* 후보가 없어도 Enter 는 된다 */ }
  }
  // ex 를 안 주면 글자의 -/+ 표식 · 지금 고른 쪽으로 정한다. 같은 칩이 반대쪽에 있으면 옮긴다.
  function addChip(text, exact, ex = null) {
    if (st.textMode) {
      const body = String(text || '').trim();
      if (!body) return;
      st.chips = st.chips.filter(c => c.kind !== 'text');
      st.chips.push({kind: 'text', text: body});
      st.textMode = false;
    } else {
      let raw = String(text || '');
      if (ex == null) ({text: raw, ex} = typedTag(raw, st.mode === 'ex'));
      const value = raw.trim().toLowerCase();
      if (!value) return;
      const same = st.chips.find(c => c.kind === 'tag' && c.text === value && c.exact === exact);
      if (same) same.ex = Boolean(ex);
      else st.chips.push({kind: 'tag', text: value, exact, ex: Boolean(ex)});
    }
    input.value = '';
    closeSug();
    drawChips();
    runQuery();
  }

  // ── 최근 검색어 · 즐겨찾기 ────────────────────────────────────────────────
  const currentQuery = () => chipQuery(st.chips);
  let recentTimer = 0, recentKey = '';
  async function loadSaved() {
    try { setSaved(await req(SAVED)); } catch (_) { /* 목록이 없어도 검색은 된다 */ }
  }
  function setSaved(data) {
    st.saved = {recent: data?.recent || [], favorites: data?.favorites || []};
    drawSaved();
  }
  async function changeSaved(body, {quiet = false} = {}) {
    try { setSaved(await req(SAVED, body)); return true; } catch (error) {
      if (!quiet) toast(error.message, 'error');
      return false;
    }
  }
  // 칩을 고치는 중간 단계까지 남지 않게 - 결과를 잠깐 보고 있을 때만 남긴다.
  function scheduleRecent() {
    win.clearTimeout(recentTimer);
    const q = currentQuery();
    const key = queryKey(q);
    if (emptyQuery(q) || key === recentKey) return;
    recentTimer = win.setTimeout(() => {
      if (queryKey(currentQuery()) !== key) return;
      recentKey = key;
      changeSaved({action: 'recent', q}, {quiet: true});
    }, RECENT_DELAY);
  }
  function drawSaved() {
    const now = queryKey(currentQuery());
    const recent = st.saved.recent.map((r, i) => {
      const text = querySummary(r.q);
      return `<span class="osr-pill${queryKey(r.q) === now ? ' on' : ''}" data-recent-i="${i}" title="${esc(text)} · 우클릭: 즐겨찾기에 추가 · 지우기">${queryPillHtml(r.q)}</span>`;
    });
    const favs = st.saved.favorites.map(f => {
      const text = querySummary(f.q);
      return `<span class="osr-pill fav${queryKey(f.q) === now ? ' on' : ''}" data-fav-id="${esc(f.id)}" title="${esc(f.title)} — ${esc(text)} · 우클릭: 이름 바꾸기 · 덮어쓰기 · 삭제">${esc(f.title)}</span>`;
    });
    $('[data-pills="recent"]').innerHTML = recent.join('') || '<span class="osr-dim">검색하면 여기에 남습니다</span>';
    $('[data-pills="fav"]').innerHTML = favs.join('') || '<span class="osr-dim">☆ 저장으로 지금 검색어를 담아 둡니다</span>';
    const btn = $('[data-act="fav-save"]');
    const hit = st.saved.favorites.find(f => queryKey(f.q) === now);
    btn.disabled = emptyQuery(currentQuery());
    btn.classList.toggle('fav-on', Boolean(hit));
    btn.textContent = hit ? '★ 저장됨' : '☆ 저장';
    btn.title = hit ? `'${hit.title}' 으로 저장되어 있습니다 · 누르면 새로 하나 더` : '지금 검색어를 즐겨찾기로';
    drawMore();
  }
  // 더보기는 넘칠 때만(펼친 줄은 접기로) - 너비를 재야 하므로 창 크기가 바뀔 때도 다시 본다.
  function drawMore() {
    for (const [key, sel] of [['recent', 'recent'], ['fav', 'fav']]) {
      const row = $(`[data-saved="${sel}"]`);
      const pills = row.querySelector('.osr-pills');
      const btn = row.querySelector('[data-more]');
      row.classList.toggle('open', st.open[key]);
      btn.textContent = st.open[key] ? '접기 ▴' : '더보기 ▾';
      btn.hidden = !st.open[key] && pills.scrollWidth <= pills.clientWidth + 1;
    }
  }
  function useQuery(q) {
    st.chips = [...(q.include || []).map(t => parseChip(t, false)), ...(q.exclude || []).map(t => parseChip(t, true))];
    if (q.text) st.chips.push({kind: 'text', text: String(q.text)});
    st.textMode = false;
    input.value = '';
    closeSug();
    closeMenu();
    drawChips();
    runQuery();
  }
  // 제목을 묻는 작은 창 - 앱 창(Electron)에는 window.prompt 가 없다. 빈 제목은 받지 않는다.
  let dialogOpen = false;
  function askTitle({heading, value = '', q, note = ''}) {
    if (dialogOpen) return Promise.resolve(null);
    dialogOpen = true;
    closeMenu();
    const inc = (q.include || []).map(t => (t.startsWith('*') ? t.slice(1) : `~${t}`));
    const exc = (q.exclude || []).map(t => (t.startsWith('*') ? t.slice(1) : `~${t}`));
    const line = [`포함 ${inc.join(' · ') || '없음'}`, `제외 ${exc.join(' · ') || '없음'}`, q.text ? `본문 “${q.text}”` : ''].filter(Boolean).join(' / ');
    const bg = doc.createElement('div');
    bg.className = 'osr-dlg-bg';
    bg.innerHTML = `<div class="osr-dlg" role="dialog" aria-label="${esc(heading)}"><div>${esc(heading)}</div>`
      + `<input type="text" maxlength="60" spellcheck="false" placeholder="제목" aria-label="제목">`
      + `<div class="osr-dlg-q">${esc(line)}</div><div class="osr-dlg-warn" data-dlg-warn>${esc(note)}</div>`
      + `<div class="osr-dlg-acts"><button type="button" data-dlg="no">취소</button><button type="button" class="on" data-dlg="ok">저장</button></div></div>`;
    host.appendChild(bg);
    const field = bg.querySelector('input');
    field.value = value;
    field.focus();
    field.select();
    return new Promise(resolve => {
      const done = result => { dialogOpen = false; bg.remove(); resolve(result); };
      const ok = () => {
        const title = field.value.trim();
        if (!title) { bg.querySelector('[data-dlg-warn]').textContent = '제목을 적어 주세요.'; field.focus(); return; }
        done(title);
      };
      bg.addEventListener('click', event => {
        event.stopPropagation();
        const which = event.target.closest('[data-dlg]')?.dataset.dlg;
        if (which === 'ok') ok();
        else if (which === 'no' || event.target === bg) done(null);
      });
      // 창 · 목록 · 레일의 키(Del · Backspace · Esc · Ctrl+A)가 제목 입력을 먹지 않게 여기서 끝낸다.
      bg.addEventListener('keydown', event => {
        event.stopPropagation();
        if (event.key === 'Enter' && !event.isComposing) { event.preventDefault(); ok(); }
        else if (event.key === 'Escape') { event.preventDefault(); done(null); }
      });
    });
  }
  async function saveFavorite(q = currentQuery()) {
    if (emptyQuery(q)) { toast('먼저 검색어를 넣어 주세요.', 'info'); return; }
    const same = st.saved.favorites.find(f => queryKey(f.q) === queryKey(q));
    const title = await askTitle({heading: '즐겨찾기 이름', q, note: same ? `같은 검색이 '${same.title}' 으로 이미 있습니다.` : ''});
    if (title && await changeSaved({action: 'add', title, q})) toast(`'${title}' 을(를) 즐겨찾기에 담았습니다.`, 'success');
  }
  // 알약 우클릭 메뉴 - 창 안에 그린다(앱의 결과 메뉴와 섞이지 않게).
  let menu = null;
  function closeMenu() { menu?.remove(); menu = null; }
  function openMenu(event, entries) {
    closeMenu();
    menu = doc.createElement('div');
    menu.className = 'osr-menu';
    menu.setAttribute('role', 'menu');
    menu.innerHTML = entries.map((e, i) =>
      `<div role="menuitem" data-mi="${i}" class="${e.danger ? 'danger' : ''}${e.disabled ? ' dis' : ''}">${esc(e.label)}</div>`).join('');
    host.appendChild(menu);
    const box = host.getBoundingClientRect();
    const x = Math.min(event.clientX - box.left, host.clientWidth - menu.offsetWidth - 4);
    const y = Math.min(event.clientY - box.top, host.clientHeight - menu.offsetHeight - 4);
    menu.style.left = `${Math.max(0, x)}px`;
    menu.style.top = `${Math.max(0, y)}px`;
    menu.addEventListener('click', ev => {
      ev.stopPropagation();
      const i = ev.target.closest('[data-mi]')?.dataset.mi;
      if (i == null) return;
      const entry = entries[Number(i)];
      closeMenu();
      if (entry && !entry.disabled) entry.run();
    });
  }
  function favoriteMenu(event, fav) {
    const cur = currentQuery();
    openMenu(event, [
      {label: '이름 바꾸기', run: async () => {
        const title = await askTitle({heading: '이름 바꾸기', value: fav.title, q: fav.q});
        if (title && title !== fav.title) changeSaved({action: 'rename', id: fav.id, title});
      }},
      {label: '지금 검색어로 덮어쓰기', disabled: emptyQuery(cur) || queryKey(cur) === queryKey(fav.q), run: async () => {
        if (await confirmAsk(`'${fav.title}' 을(를) 지금 검색어로 바꿀까요?\n${querySummary(cur)}`)) {
          changeSaved({action: 'update', id: fav.id, q: cur});
        }
      }},
      {label: '삭제', danger: true, run: async () => {
        if (await confirmAsk(`즐겨찾기 '${fav.title}' 을(를) 지울까요?`)) changeSaved({action: 'delete', id: fav.id});
      }},
    ]);
  }
  function recentMenu(event, item) {
    openMenu(event, [
      {label: '즐겨찾기에 추가', run: () => saveFavorite(item.q)},
      {label: '목록에서 지우기', run: () => {
        if (queryKey(item.q) === recentKey) recentKey = '';
        changeSaved({action: 'recent_remove', q: item.q});
      }},
      {label: '최근 검색 모두 지우기', danger: true, run: async () => {
        if (await confirmAsk('최근 검색어를 모두 지울까요?')) { recentKey = ''; changeSaved({action: 'recent_clear'}); }
      }},
    ]);
  }

  // ── 거르개 줄 ─────────────────────────────────────────────────────────────
  function drawSources() {
    $('[data-sources]').innerHTML = SOURCES.map(s =>
      `<button type="button" data-src="${s}" class="${st.sources.has(s) ? 'on' : 'off'}" title="${s}">${s}</button>`).join(' ');
  }
  function drawRoots() {
    const label = rootLabel;
    $('[data-roots]').innerHTML = st.allRoots.filter(r => !r.shadowed).map(r => {
      if (r.unreachable) return `<button type="button" class="warn" title="연결 안 됨${r.path ? ' · ' + esc(r.path) : ''}">${esc(label(r))} ⚠</button>`;
      if (!r.enabled) return '';
      const on = !st.roots || st.roots.has(r.id);
      const rm = st.local && r.kind === 'user' ? `<span class="osr-x" data-rmroot="${r.id}" title="색인에서 빼기"> ×</span>` : '';
      return `<button type="button" data-root="${r.id}" class="${on ? 'on' : 'off'}" title="${esc(r.path || label(r))}">${esc(label(r))}${rm}</button>`;
    }).join(' ');
  }
  function drawCount() {
    const node = $('[data-count]');
    if (isSession()) {
      let text = st.chips.length ? `${fmt(st.count)} / ${fmt(st.total)}장` : `${fmt(st.total)}장`;
      if (st.unsaved) text += ` · 미저장 ${fmt(st.unsaved)}`;
      node.innerHTML = esc(text) + (st.pendingNew
        ? ` · <span class="osr-link" data-act="refreshq" title="다시 찾기">새 그림 ${fmt(st.pendingNew)} ↻</span>` : '');
      node.title = '이번 실행에 만든 그림';
    } else {
      let text = overview() ? `폴더 ${fmt(st.folderCount)} · ${fmt(st.count)}장` : `${fmt(st.count)}장`;
      if (st.partial) text += ` · 색인 중 ${fmt(st.rows)}`;
      node.textContent = text;
      node.title = st.matchedTotal ? `부분 일치로 펼친 태그 ${st.matchedTotal}개: ${st.matched.slice(0, 30).join(', ')}` : `${fmt(st.items.length)}장 불러옴`;
    }
    drawScope();
  }
  function drawPrefs() {
    $('[data-act="sort"]').textContent = prefs.sort === 'mtime_asc' ? '오래된순' : '최신순';
    $('[data-act="view"]').textContent = prefs.view === 'flat' ? '한 줄' : '폴더별';
    host.querySelectorAll('[data-size]').forEach(b => b.classList.toggle('on', b.dataset.size === prefs.size));
    host.style.setProperty('--osr-tile', `${SIZES[prefs.size].tile}px`);
    drawDrill();
  }
  function drawDrill() {
    const bar = $('[data-drill]');
    const d = !isSession() && st.dir;
    bar.hidden = !d;
    if (!d) { bar.innerHTML = ''; return; }
    bar.innerHTML = `<button type="button" data-act="folders-back" title="폴더 목록으로">‹ 폴더 목록</button>`
      + `<b title="${esc(d.rel || '(뿌리)')}">${esc(folderLabel(d.rel))}</b><span class="osr-dim">${fmt(d.count)}장</span>`;
  }
  function savePrefs() {
    try { storage?.setItem(PREFS_KEY, JSON.stringify(prefs)); } catch (_) { /* 기억 못 해도 화면은 된다 */ }
  }

  // ── 질의 · 무한 스크롤 ────────────────────────────────────────────────────
  function queryBody(offset) {
    const {include, exclude, text} = chipQuery(st.chips);
    const body = {include, exclude, sort: prefs.sort, offset, limit: PAGE};
    if (text) body.text = text;
    if (isSession()) return body;
    if (st.sources.size !== SOURCES.length) body.source = [...st.sources];
    if (st.roots) body.roots = [...st.roots];
    if (overview()) {
      delete body.limit;
      body.offset = st.folderOrder.length;
      body.limit = FOLDER_PAGE;
      body.samples = FOLDER_SAMPLES;
    } else if (st.dir) body.dir_id = st.dir.id;
    return body;
  }
  function resetFolders() {
    st.folderOrder = []; st.folderInfo = new Map(); st.folderCount = 0; st.cardsDrawn = 0;
  }
  // 펼친 폴더 · 돌아가기 - 카드 목록은 받은 그대로 두었다가 되살린다(다시 받으면 내려가 있던 자리를 잃는다).
  function openFolder(id) {
    const info = st.folderInfo.get(id);
    if (!info || !overview()) return;
    st.ovCache = {items: st.items, folderOrder: st.folderOrder, folderInfo: st.folderInfo, folderCount: st.folderCount,
      count: st.count, done: st.done, matched: st.matched, matchedTotal: st.matchedTotal,
      scroll: list.scrollTop, current: st.current};
    st.dir = {...info};
    lightbox.close();
    drawDrill();
    runQuery({keepCache: true});
  }
  function closeFolder() {
    if (!st.dir) return;
    const cache = st.ovCache;
    st.dir = null;
    st.ovCache = null;
    drawDrill();
    if (!cache || prefs.view !== 'folder') { runQuery(); return; }
    st.seq += 1;
    lightbox.close();
    Object.assign(st, {items: cache.items, folderOrder: cache.folderOrder, folderInfo: cache.folderInfo,
      folderCount: cache.folderCount, count: cache.count, done: cache.done, matched: cache.matched,
      matchedTotal: cache.matchedTotal, loading: false, cardsDrawn: 0});
    st.sel.clear(); st.anchor = -1; st.current = null;
    list.innerHTML = '';
    appendTiles(0);
    list.scrollTop = cache.scroll;
    if (st.items[cache.current]) select(cache.current, {});
    else { drawSel(); drawDetail(); }
    drawCount();
    list.focus({preventScroll: true});
  }
  async function runQuery({keepCache = false} = {}) {
    const seq = ++st.seq;
    scheduleRecent();
    if (!keepCache) st.ovCache = null;
    resetFolders();
    st.items = []; st.done = false; st.loading = false;
    st.sel.clear(); st.anchor = -1; st.current = null;
    st.pendingNew = 0;
    list.scrollTop = 0;
    list.innerHTML = '';
    drawSel();
    drawDetail();
    await loadMore(seq);
  }
  async function loadMore(seq = st.seq) {
    if (st.loading || st.done || seq !== st.seq) return;
    st.loading = true;
    drawTail();
    try {
      const session = isSession();
      const cards = overview();
      const data = await req(session ? `${HISTORY}/query` : cards ? `${API}/folders` : `${API}/query`,
        queryBody(st.items.length));
      if (seq !== st.seq) return;
      let items;
      if (cards) {
        items = [];
        const folders = data.folders || [];
        for (const f of folders) {
          if (st.folderInfo.has(f.dir_id)) continue;
          st.folderInfo.set(f.dir_id, {id: f.dir_id, rel: f.rel || '', root: f.root_id, count: f.count || 0});
          st.folderOrder.push(f.dir_id);
          for (const r of f.items || []) items.push({...normAll(r), dir: f.dir_id});
        }
        st.folderCount = data.folder_count || 0;
        st.done = !folders.length || st.folderOrder.length >= st.folderCount;
      } else items = (data.items || []).map(session ? normSession : normAll);
      st.count = data.count || 0;
      st.matched = data.matched || [];
      st.matchedTotal = data.matched_total || 0;
      if (session) { st.total = data.total || 0; st.unsaved = data.unsaved || 0; }
      const known = new Set(st.items.map(it => it.key));
      const start = st.items.length;
      // 이번 세션은 새 그림이 앞에 붙으며 쪽이 밀린다 - 이미 받은 것은 다시 넣지 않는다.
      st.items.push(...items.filter(it => !known.has(it.key)));
      if (!cards) st.done = items.length < PAGE || st.items.length >= st.count;
      appendTiles(start);
      if (st.current == null && st.items.length) select(0, {});
      if (!st.items.length) drawDetail();
    } catch (error) {
      if (seq === st.seq) toast(error.message, 'error');
      st.done = true;
    } finally {
      if (seq === st.seq) {
        st.loading = false; drawTail(); drawCount();
        if (lightbox.isOpen()) {
          const viewing = lightbox.currentItem()?.key;
          lightbox.setItems(lbItems(), viewing);
          // 목록의 '지금 그림' 도 큰 보기가 보는 그림으로 맞춘다(닫았을 때 그 자리로 돌아오게).
          const at = indexOfKey(viewing);
          if (at >= 0 && st.current !== at) select(at, {});
        }
      }
    }
    // 첫 장이 화면을 다 못 채우면 스크롤이 생기지 않는다 - 그때는 바로 더 부른다.
    if (seq === st.seq && !st.done && list.scrollHeight <= list.clientHeight + 40) loadMore(seq);
  }
  function tile(item, index) {
    const size = SIZES[prefs.size].thumb;
    const cls = ['osr-th', st.sel.has(index) ? 'sel' : '', st.current === index ? 'cur' : ''].join(' ');
    const ctxPath = isSession() && item.rel ? ` data-path="${esc(item.rel)}"` : '';
    return `<div class="${cls}" data-i="${index}"${ctxPath} title="${esc(item.name || item.path)}">`
      + `<img loading="lazy" decoding="async" alt="" src="${item.thumb(size)}">`
      + `${isSession() && !item.saved ? '<span class="osr-badge">미저장</span>' : ''}`
      + `${st.sel.has(index) && st.sel.size > 1 ? '<span class="osr-tick">✓</span>' : ''}</div>`;
  }
  function card(id, indices) {
    const info = st.folderInfo.get(id);
    const roots = st.allRoots.filter(r => r.enabled && !r.shadowed);
    const root = roots.length > 1 ? roots.find(r => r.id === info.root) : null;
    const rest = info.count - indices.length;
    const more = rest > 0
      ? `<button type="button" class="osr-card-more" data-open-dir="${id}" title="이 폴더 ${fmt(info.count)}장 모두 보기">+${fmt(rest)}<span>더보기</span></button>`
      : '';
    return `<div class="osr-card" data-dir="${id}"><div class="osr-card-h">`
      + `<span class="osr-card-t" data-open-dir="${id}" title="${esc(info.rel || '(뿌리)')} · 펼치기">${esc(folderLabel(info.rel))}</span>`
      + `${root ? `<span class="osr-dim">${esc(rootLabel(root))}</span>` : ''}<span class="osr-dim">${fmt(info.count)}장</span></div>`
      + `<div class="osr-card-g">${indices.map(i => tile(st.items[i], i)).join('')}${more}</div></div>`;
  }
  function appendCards() {
    let box = list.querySelector('.osr-cards');
    if (!box) {
      list.insertAdjacentHTML('afterbegin', '<div class="osr-cards"></div>');
      box = list.querySelector('.osr-cards');
    }
    const byDir = new Map();
    st.items.forEach((it, i) => {
      if (!byDir.has(it.dir)) byDir.set(it.dir, []);
      byDir.get(it.dir).push(i);
    });
    const fresh = st.folderOrder.slice(st.cardsDrawn);
    box.insertAdjacentHTML('beforeend', fresh.map(id => card(id, byDir.get(id) || [])).join(''));
    st.cardsDrawn = st.folderOrder.length;
    drawTail();
  }
  function appendTiles(start) {
    if (overview()) { appendCards(); return; }
    const html = [];
    let grid = list.lastElementChild?.matches?.('.osr-group') ? list.lastElementChild : null;
    if (!grid) grid = [...list.querySelectorAll('.osr-group')].pop() || null;
    let lastFolder = grid ? grid.dataset.folder : null;
    let chunk = [];
    const flush = () => {
      if (!chunk.length) return;
      if (grid) grid.querySelector('.osr-grid').insertAdjacentHTML('beforeend', chunk.join(''));
      else html.push(chunk.join(''));
      chunk = [];
    };
    // 이번 세션은 늘 한 줄이다 - 저장 안 된 그림은 폴더가 없고, 저장 폴더가 섞여 묶음이 잘게 쪼개진다.
    if (prefs.view === 'flat' || isSession() || st.dir) {
      if (!grid) {
        list.insertAdjacentHTML('afterbegin', '<div class="osr-group" data-folder=""><div class="osr-grid"></div></div>');
        grid = list.querySelector('.osr-group');
      }
      grid.querySelector('.osr-grid').insertAdjacentHTML('beforeend',
        st.items.slice(start).map((item, k) => tile(item, start + k)).join(''));
    } else {
      for (let i = start; i < st.items.length; i += 1) {
        const folder = folderOf(st.items[i].path);
        if (folder !== lastFolder) {
          flush();
          if (html.length) { list.insertAdjacentHTML('beforeend', html.join('')); html.length = 0; }
          const tail = list.querySelector('.osr-more');
          const markup = `<div class="osr-group" data-folder="${esc(folder)}"><div class="osr-fold"><span>${esc(folder || '(뿌리)')}</span><span data-fc>0</span></div><div class="osr-grid"></div></div>`;
          if (tail) tail.insertAdjacentHTML('beforebegin', markup); else list.insertAdjacentHTML('beforeend', markup);
          grid = [...list.querySelectorAll('.osr-group')].pop();
          lastFolder = folder;
        }
        chunk.push(tile(st.items[i], i));
      }
      flush();
      list.querySelectorAll('.osr-group').forEach(g => {
        const counter = g.querySelector('[data-fc]');
        if (counter) counter.textContent = fmt(g.querySelectorAll('.osr-th').length);
      });
    }
    drawTail();
  }
  function rebuild() {
    const top = list.scrollTop;
    list.innerHTML = '';
    st.cardsDrawn = 0;
    appendTiles(0);
    list.scrollTop = top;
  }
  function drawTail() {
    let tail = list.querySelector('.osr-more');
    if (!tail) {
      list.insertAdjacentHTML('beforeend', '<div class="osr-more" data-tail></div>');
      tail = list.querySelector('.osr-more');
    } else if (tail !== list.lastElementChild) {
      list.appendChild(tail);
    }
    if (st.loading) tail.textContent = '불러오는 중…';
    else if (!st.items.length) {
      tail.textContent = isSession()
        ? (st.chips.length ? '맞는 그림이 없습니다.' : '이번 실행에 만든 그림이 아직 없습니다.')
        : (st.partial ? '아직 색인하는 중입니다.' : '맞는 그림이 없습니다.');
    } else if (overview()) tail.textContent = st.done ? `폴더 ${fmt(st.folderOrder.length)}개` : '';
    else tail.textContent = st.done ? `${fmt(st.items.length)}장` : '';
  }
  list.addEventListener('scroll', () => {
    if (list.scrollTop + list.clientHeight >= list.scrollHeight - 400) loadMore();
  }, {passive: true});

  // ── 고르기 ────────────────────────────────────────────────────────────────
  function paintTile(index) {
    const node = list.querySelector(`.osr-th[data-i="${index}"]`);
    if (!node) return;
    node.classList.toggle('sel', st.sel.has(index));
    node.classList.toggle('cur', st.current === index);
    const tick = node.querySelector('.osr-tick');
    const want = st.sel.has(index) && st.sel.size > 1;
    if (want && !tick) node.insertAdjacentHTML('beforeend', '<span class="osr-tick">✓</span>');
    if (!want && tick) tick.remove();
  }
  function repaintAll() {
    list.querySelectorAll('.osr-th').forEach(node => paintTile(Number(node.dataset.i)));
  }
  function select(index, {ctrl = false, shift = false} = {}) {
    if (!st.items[index]) return;
    const before = st.sel.size;
    if (shift && st.anchor >= 0) {
      const [a, b] = st.anchor < index ? [st.anchor, index] : [index, st.anchor];
      if (!ctrl) st.sel.clear();
      for (let i = a; i <= b; i += 1) st.sel.add(i);
    } else if (ctrl) {
      if (st.sel.has(index)) st.sel.delete(index); else st.sel.add(index);
      st.anchor = index;
    } else {
      st.sel.clear();
      st.sel.add(index);
      st.anchor = index;
    }
    const prev = st.current;
    st.current = index;
    if (before > 1 || st.sel.size > 1 || shift) repaintAll();
    else { paintTile(prev); paintTile(index); }
    drawSel();
    drawDetail();
  }
  function drawSel() {
    const n = st.sel.size;
    $('[data-selbar]').hidden = n < 2;
    $('[data-selcount]').textContent = `${fmt(n)}장 선택`;
    // 전체 범위의 삭제는 이 PC 에서만 - 원격이면 단추를 그리지 않는다.
    $('[data-act="seldelete"]').hidden = !isSession() && !st.local;
  }
  function clearSel() {
    if (st.sel.size < 2) return;
    st.sel = new Set(st.current != null ? [st.current] : []);
    repaintAll();
    drawSel();
  }
  function chosen() {
    return [...st.sel].filter(i => st.items[i]).sort((a, b) => a - b);
  }
  function gridColumns() {
    const grid = list.querySelector('.osr-grid');
    if (!grid) return 1;
    const columns = (win.getComputedStyle(grid).gridTemplateColumns || '').trim();
    return columns && columns !== 'none' ? Math.max(1, columns.split(/\s+/).length) : 1;
  }
  function moveTo(next, shift = false) {
    if (!st.items[next]) return;
    select(next, {shift});
    list.querySelector(`.osr-th[data-i="${next}"]`)?.scrollIntoView({block: 'nearest'});
    if (next >= st.items.length - gridColumns() * 2) loadMore();
  }

  // 드래그 사각형 선택 - 빈 곳에서 끌기 시작한다(타일 위에서 누르면 그 타일 클릭이다). Ctrl 을 누르면 더한다.
  let marquee = null;
  function contentPoint(event) {
    const rect = list.getBoundingClientRect();
    return {x: event.clientX - rect.left + list.scrollLeft, y: event.clientY - rect.top + list.scrollTop};
  }
  list.addEventListener('pointerdown', event => {
    if (event.button !== 0 || event.target.closest('.osr-th') || event.target.closest('.osr-more')) return;
    // 세로 스크롤 막대를 누른 것은 끌기 선택이 아니다.
    if (event.offsetX >= list.clientWidth) return;
    const p = contentPoint(event);
    marquee = {x: p.x, y: p.y, base: event.ctrlKey || event.metaKey ? new Set(st.sel) : new Set(), node: null, moved: false};
    list.setPointerCapture?.(event.pointerId);
    list.focus({preventScroll: true});
  });
  list.addEventListener('pointermove', event => {
    if (!marquee) return;
    const p = contentPoint(event);
    const box = {l: Math.min(p.x, marquee.x), t: Math.min(p.y, marquee.y), r: Math.max(p.x, marquee.x), b: Math.max(p.y, marquee.y)};
    if (!marquee.moved && box.r - box.l + box.b - box.t < 6) return;
    marquee.moved = true;
    if (!marquee.node) {
      marquee.node = doc.createElement('div');
      marquee.node.className = 'osr-marq';
      list.appendChild(marquee.node);
    }
    Object.assign(marquee.node.style, {left: `${box.l}px`, top: `${box.t}px`, width: `${box.r - box.l}px`, height: `${box.b - box.t}px`});
    const rect = list.getBoundingClientRect();
    const next = new Set(marquee.base);
    list.querySelectorAll('.osr-th').forEach(node => {
      const r = node.getBoundingClientRect();
      const l = r.left - rect.left + list.scrollLeft, t = r.top - rect.top + list.scrollTop;
      if (l < box.r && l + r.width > box.l && t < box.b && t + r.height > box.t) next.add(Number(node.dataset.i));
    });
    st.sel = next;
    repaintAll();
    drawSel();
    // 아래 끝까지 끌면 다음 쪽을 부른다.
    if (event.clientY > rect.bottom - 30) { list.scrollTop += 20; loadMore(); }
    else if (event.clientY < rect.top + 30) list.scrollTop -= 20;
  });
  const endMarquee = () => {
    if (!marquee) return;
    const {moved, node} = marquee;
    marquee = null;
    node?.remove();
    if (!moved) return;
    const picked = [...st.sel].sort((a, b) => a - b);
    if (picked.length && !st.sel.has(st.current)) {
      const prev = st.current;
      st.current = picked[0];
      st.anchor = picked[0];
      paintTile(prev);
      paintTile(st.current);
      drawDetail();
    }
    drawSel();
  };
  list.addEventListener('pointerup', endMarquee);
  list.addEventListener('pointercancel', endMarquee);

  // ── 상세 ──────────────────────────────────────────────────────────────────
  async function fullMeta(item) {
    if (item.row != null) return api(`/meta?row=${item.row}`);
    const meta = await req(`${HISTORY}/meta/${encodeURIComponent(item.hid)}`);
    const chars = Array.isArray(meta.characters) ? meta.characters : [];
    return {...meta, characters: chars.map(c => (typeof c === 'string' ? c : (c && (c.prompt || c.caption)) || '')).filter(Boolean)};
  }
  let metaSeq = 0;
  function drawDetail() {
    const box = $('[data-detail]');
    const item = st.items[st.current];
    if (!item) { box.innerHTML = `<div class="osr-empty">${st.items.length ? '' : '그림을 고르면 여기에 보입니다.'}</div>`; return; }
    const date = new Date(item.mtime * 1000);
    const when = Number.isFinite(date.getTime()) ? date.toLocaleString() : '';
    const session = isSession();
    const canLocate = st.local && item.saved;
    const canDelete = session || st.local;
    const promptLabel = applyPrompt ? '프롬프트 넣기' : '프롬프트 복사';
    box.innerHTML = `
      <div class="osr-prev" data-act="big" title="크게 보기 (Enter)"><img alt="" src="${item.thumb(384)}"></div>
      <div class="osr-path">${esc(item.path || item.name)}</div>
      <div class="osr-meta">
        ${session && !item.saved ? '<span class="unsaved" title="아직 디스크에 없다 - 이번 실행이 끝나면 사라진다">미저장</span>' : ''}
        ${item.width ? `<span>${item.width}×${item.height}</span>` : ''}
        ${item.source ? `<span>${esc(item.source)}</span>` : ''}
        ${item.seed != null && item.seed !== '' ? `<span title="seed">${esc(item.seed)}</span>` : ''}
        ${when ? `<span>${esc(when)}</span>` : ''}
      </div>
      <div class="osr-prompt" data-prompt>${item.prompt ? highlightPrompt(item.prompt, st.chips, st.matched) : '<i class="osr-dim">불러오는 중…</i>'}</div>
      <div class="osr-acts">
        ${session && sessionHand() ? '<button type="button" data-act="main" title="메인 화면에 띄우기 - Result Info · Enhance · Sequence 가 이 그림을 따라간다">메인에 띄우기</button>' : ''}
        <button type="button" data-act="big" title="크게 보기 (Enter · 더블클릭)">크게</button>
        <button type="button" data-act="original" title="원본을 브라우저로">원본</button>
        <button type="button" data-act="prompt" title="${applyPrompt ? '프롬프트 · 네거티브를 메인에 넣기' : '프롬프트 복사'}">${promptLabel}</button>
        ${session ? '<button type="button" data-act="save" title="빠른 저장 폴더로 (Ctrl+S)">저장</button>' : ''}
        ${session && sessionHand()?.canSaveAs?.() ? '<button type="button" data-act="saveas" title="다른 곳에 저장">다른 이름</button>' : ''}
        ${canLocate ? '<button type="button" data-act="locate" title="탐색기에서 이 파일 보기">폴더 열기</button>' : ''}
        ${canDelete ? `<button type="button" data-act="delete" class="danger" title="삭제 (Del)">삭제</button>` : ''}
      </div>
      <div class="osr-note">${session ? '삭제 = 뷰어 설정(⚙)의 방식 · 히스토리에서만 / 휴지통' : (st.local ? '삭제 = 휴지통 · 늘 묻습니다' : '')}</div>`;
    // 목록의 프롬프트는 300자로 잘려 온다(이번 세션 새 그림은 비어 온다) - 그때만 전체를 따로 받는다.
    if (!item.prompt || item.prompt.length >= 300) {
      const seq = ++metaSeq;
      fullMeta(item).then(meta => {
        if (seq !== metaSeq || st.items[st.current] !== item) return;
        const node = $('[data-prompt]');
        if (!node) return;
        if (meta?.prompt) {
          if (!item.prompt) item.prompt = meta.prompt.slice(0, 300);
          node.innerHTML = highlightPrompt(meta.prompt, st.chips, st.matched);
        } else node.innerHTML = '<i class="osr-dim">메타 없음</i>';
      }).catch(() => {
        const node = $('[data-prompt]');
        if (node && st.items[st.current] === item && !item.prompt) node.innerHTML = '<i class="osr-dim">메타 없음</i>';
      });
    }
  }
  const sessionHand = () => (session && typeof session === 'object' ? session : null);

  // ── 바꾸기: 삭제 · 저장 ───────────────────────────────────────────────────
  async function deleteItems(indices) {
    const targets = [...indices].filter(i => st.items[i]).sort((a, b) => a - b).map(i => st.items[i]);
    if (!targets.length) return;
    if (isSession()) {
      const removed = sessionHand() ? await sessionHand().deletePaths(targets.map(t => t.rel)) : await plainSessionDelete(targets);
      if (Array.isArray(removed) && removed.length) removeKeys(new Set(removed));
      return;
    }
    if (!st.local) return;
    // 전체 범위는 '묻지 않기' 와 상관없이 늘 묻는다(사용자 결정 11-22) - 지난 실행 · 다른 폴더의 파일이다.
    const ok = await confirmAsk(targets.length === 1
      ? `${targets[0].name} 을(를) 휴지통으로 보낼까요?`
      : `${fmt(targets.length)}장을 휴지통으로 보낼까요?`);
    if (!ok) return;
    const deleted = new Set();
    const failed = [];
    for (let k = 0; k < targets.length; k += 200) {
      const part = targets.slice(k, k + 200);
      try {
        const data = await api('/delete', {rows: part.map(t => t.row)});
        (data.deleted || []).forEach(row => deleted.add(`r${row}`));
        failed.push(...(data.failed || []));
      } catch (error) {
        toast(error.message, 'error');
        break;
      }
    }
    if (deleted.size) removeKeys(deleted);
    if (failed.length) toast(`${fmt(failed.length)}장은 지우지 못했습니다: ${failed[0].error || ''}`, 'error');
    else if (deleted.size) toast(`${fmt(deleted.size)}장을 휴지통으로 보냈습니다.`, 'success');
  }
  // 외부 브라우저 화면(앱의 손이 없다) - 삭제 방식은 같은 키를 읽고, 늘 묻는다.
  async function plainSessionDelete(targets) {
    let toDisk = false;
    try { toDisk = storage?.getItem(DELETE_MODE_KEY) === 'disk'; } catch (_) { toDisk = false; }
    const how = toDisk ? '저장 파일은 휴지통으로 보냅니다.' : '히스토리에서만 빼고 저장 파일은 남깁니다.';
    if (!(await confirmAsk(`${fmt(targets.length)}장을 지울까요?\n${how}`))) return [];
    try {
      const data = await req(`${HISTORY}/selected/delete`, {paths: targets.map(t => t.rel), keep_file: !toDisk});
      const removed = (data.removed || []).map(r => r.rel_path).filter(Boolean);
      const failed = Array.isArray(data.failed) ? data.failed.length : 0;
      const unrescued = (data.removed || []).filter(r => r && r.rescue_failed).length;
      let text = `${fmt(removed.length)}장을 지웠습니다.`;
      if (failed) text += ` 실패 ${fmt(failed)}장.`;
      if (unrescued) text += ` ${fmt(unrescued)}장은 사본을 못 남겼습니다(복구 불가).`;
      toast(text, failed || unrescued ? (removed.length ? 'warning' : 'error') : 'success');
      return removed;
    } catch (error) {
      toast(error.message, 'error');
      return [];
    }
  }
  async function quicksave(indices) {
    const paths = indices.map(i => st.items[i]?.rel).filter(Boolean);
    if (!paths.length) return;
    if (sessionHand()) { await sessionHand().quicksavePaths(paths); markSaved(indices); return; }
    try {
      const data = await req(`${HISTORY}/selected/quicksave`, {paths});
      toast(`저장 ${fmt(data.saved || 0)}개 · ${data.directory || '빠른 저장 폴더'}`, 'success');
      markSaved(indices);
    } catch (error) {
      toast(error.message, 'error');
    }
  }
  // 빠른 저장은 미저장 표식을 지우지 않는다(자동 저장 장수와 별개다) - 다음 찾기 때 서버 값으로 맞는다.
  function markSaved() { drawCount(); }
  function removeKeys(keys) {
    if (!keys || !keys.size) return;
    const keep = st.items[st.current];
    const at = st.current ?? 0;
    const before = st.items.length;
    const selKeys = new Set([...st.sel].map(i => st.items[i]?.key).filter(Boolean));
    const goneUnsaved = isSession() ? st.items.filter(it => keys.has(it.key) && !it.saved).length : 0;
    for (const it of st.items) {
      if (!keys.has(it.key)) continue;
      const info = it.dir != null ? st.folderInfo.get(it.dir) : null;
      if (info) info.count = Math.max(0, info.count - 1);
    }
    st.items = st.items.filter(it => !keys.has(it.key));
    const gone = before - st.items.length;
    if (!gone) return;
    if (st.dir) {
      st.dir.count = Math.max(0, st.dir.count - gone);
      st.ovCache = null;      // 돌아갈 때 카드 장수 · 견본을 서버에서 새로 받는다
      drawDrill();
    }
    if (goneUnsaved) st.unsaved = Math.max(0, st.unsaved - goneUnsaved);
    st.count = Math.max(0, st.count - gone);
    // 범위 단추의 장수도 함께 줄인다 - 전체에서 지운 것은 파일째 휴지통으로 갔다.
    if (isSession()) st.total = Math.max(0, st.total - gone);
    else st.rows = Math.max(0, st.rows - gone);
    drawScope();
    // 살아남은 선택은 그대로 둔다(번호만 새로) - 다른 창에서 한 장 지웠다고 골라 둔 것이 풀리지 않게.
    st.sel = new Set();
    st.items.forEach((it, i) => { if (selKeys.has(it.key)) st.sel.add(i); });
    const stay = keep && !keys.has(keep.key) ? st.items.indexOf(keep) : Math.min(at, st.items.length - 1);
    st.current = stay >= 0 ? stay : null;
    if (st.current != null && !st.sel.size) st.sel.add(st.current);
    st.anchor = st.current ?? -1;
    rebuild();
    drawDetail();
    drawCount();
    drawSel();
    if (lightbox.isOpen()) lightbox.setItems(lbItems(), keep && !keys.has(keep.key) ? keep.key : undefined);
    if (!st.done && list.scrollHeight <= list.clientHeight + 40) loadMore();
  }

  async function doPrompt(item) {
    let meta;
    try { meta = await fullMeta(item); } catch (error) { toast(error.message, 'error'); return; }
    if (!meta?.prompt) { toast('이 그림에는 프롬프트가 없습니다.', 'info'); return; }
    if (applyPrompt) { applyPrompt({prompt: meta.prompt || '', negative: meta.negative || '', meta}); return; }
    try {
      await win.navigator.clipboard.writeText(meta.prompt || '');
      toast('프롬프트를 복사했습니다.', 'success');
    } catch (_) {
      toast('클립보드에 쓰지 못했습니다.', 'error');
    }
  }
  async function locate(item) {
    try {
      if (item.row != null) await api('/open-location', {row: item.row});
      else await req(`${HISTORY}/open-location`, {history_id: item.hid});
    } catch (error) {
      toast(error.message, 'error');
    }
  }

  // ── 크게 보기 ─────────────────────────────────────────────────────────────
  function lbItems() {
    return st.items.map(it => ({key: it.key, full: it.full, thumb: it.thumb(384), label: it.name || it.path || '',
      prompt: it.prompt, path: it.rel || ''}));
  }
  function isDeleteKey(event) {
    const ctrl = event.ctrlKey || event.metaKey;
    if (event.key === 'Delete' || event.key === 'Backspace') return !ctrl && !event.altKey;
    return ctrl && !event.altKey && !event.shiftKey && String(event.key).toLowerCase() === 'd'
      && isSession() && Boolean(sessionHand()?.deleteKeyDEnabled?.());
  }
  function indexOfKey(key) {
    return key == null ? -1 : st.items.findIndex(it => it.key === key);
  }
  // Ctrl+S - 이번 세션이면 고른 것을 빠른 저장, 전체면 안내만.
  function saveShortcut() {
    if (isSession()) quicksave(chosen());
    else toast('전체 보기에서는 Ctrl+S 저장이 없습니다.', 'info');
  }
  function isSaveKey(event) {
    return (event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey && String(event.key).toLowerCase() === 's';
  }
  function openBig(index = st.current) {
    if (!st.items[index]) return;
    sessionHand()?.loadBindings?.();
    lightbox.open(lbItems(), index, {
      footer: true,
      zIndex: LIGHTBOX_Z,
      rowStep: gridColumns,
      total: () => (overview() ? st.items.length : st.count),
      loadMore: async () => {
        await loadMore();
        lightbox.setItems(lbItems(), st.items[lightbox.current()]?.key);
      },
      onIndex: (_i, item) => {
        const i = indexOfKey(item?.key);
        if (i < 0 || st.current === i) return;
        select(i, {});
        list.querySelector(`.osr-th[data-i="${i}"]`)?.scrollIntoView({block: 'nearest'});
      },
      onKey: (event, item) => {
        const i = indexOfKey(item?.key);
        if (isDeleteKey(event)) {
          // 인페인트 편집 중에는 Del 이 캔버스의 것이다(목록 · 레일과 같은 규칙).
          if (sessionHand()?.deleteKeyClaimed?.(event)) return true;
          if (i >= 0 && (isSession() || st.local)) deleteItems(new Set([i]));
          return true;
        }
        if (isSaveKey(event)) {
          if (!isSession()) toast('전체 보기에서는 Ctrl+S 저장이 없습니다.', 'info');
          else if (i >= 0) quicksave([i]);
          return true;
        }
        if (isSession() && i >= 0 && sessionHand()?.dispatchBindingKey?.(event, st.items[i].rel)) return true;
        return false;
      },
      onClose: () => list.focus({preventScroll: true}),
    });
  }

  // ── 손 ────────────────────────────────────────────────────────────────────
  host.addEventListener('click', async event => {
    const t = event.target;
    const scope = t.closest('[data-scope]')?.dataset.scope;
    if (scope) { setScope(scope); return; }
    const mode = t.closest('[data-mode]')?.dataset.mode;
    if (mode) { st.mode = mode === 'ex' ? 'ex' : 'inc'; drawChips(); if (!$('[data-sug]').hidden) drawSug(); input.focus(); return; }
    const favId = t.closest('[data-fav-id]')?.dataset.favId;
    if (favId != null) { const fav = st.saved.favorites.find(f => f.id === favId); if (fav) useQuery(fav.q); return; }
    const recentAt = t.closest('[data-recent-i]')?.dataset.recentI;
    if (recentAt != null) { const r = st.saved.recent[Number(recentAt)]; if (r) useQuery(r.q); return; }
    const more = t.closest('[data-more]')?.dataset.more;
    if (more) { st.open[more] = !st.open[more]; drawMore(); return; }
    const rmIndex = t.closest('[data-rm]')?.dataset.rm;
    if (rmIndex != null) { st.chips.splice(Number(rmIndex), 1); drawChips(); runQuery(); return; }
    const chip = t.closest('[data-chip]');
    if (chip) {
      const c = st.chips[Number(chip.dataset.chip)];
      if (c && c.kind === 'tag') { c.ex = !c.ex; drawChips(); runQuery(); }
      return;
    }
    const sugAdd = t.closest('[data-sug-add]');
    if (sugAdd) {
      const i = Number(sugAdd.dataset.sugAdd);
      const ex = sugAdd.dataset.ex === '1';
      if (i < 0) addChip(typed().text, false, ex); else addChip(sugItems[i]?.tag, true, ex);
      input.focus();
      return;
    }
    const sug = t.closest('[data-sug-i]');
    if (sug) {
      const i = Number(sug.dataset.sugI);
      if (i < 0) addChip(input.value, false); else addChip(sugItems[i]?.tag, true, typed().ex);
      input.focus();
      return;
    }
    if (t.closest('[data-box]')) { input.focus(); return; }
    const rmRoot = t.closest('[data-rmroot]')?.dataset.rmroot;
    if (rmRoot) {
      event.stopPropagation();
      if (await confirmAsk('이 폴더를 색인에서 뺄까요? (파일은 그대로)')) {
        try { await api('/roots', {action: 'remove', root_id: Number(rmRoot)}); await loadStatus(); runQuery(); }
        catch (error) { toast(error.message, 'error'); }
      }
      return;
    }
    const src = t.closest('[data-src]')?.dataset.src;
    if (src) {
      // 전부 켜진 상태에서 하나를 누르면 '그것만' 이 사람이 바라는 것이다. 다시 누르면 전부로.
      if (st.sources.size === SOURCES.length) st.sources = new Set([src]);
      else if (st.sources.has(src) && st.sources.size === 1) st.sources = new Set(SOURCES);
      else if (st.sources.has(src)) st.sources.delete(src);
      else st.sources.add(src);
      drawSources(); runQuery(); return;
    }
    const root = t.closest('[data-root]')?.dataset.root;
    if (root) {
      const id = Number(root);
      const live = st.allRoots.filter(r => r.enabled && !r.unreachable && !r.shadowed).map(r => r.id);
      if (!st.roots) st.roots = new Set([id]);
      else if (st.roots.has(id) && st.roots.size === 1) st.roots = null;
      else if (st.roots.has(id)) st.roots.delete(id);
      else st.roots.add(id);
      if (st.roots && live.every(r => st.roots.has(r))) st.roots = null;
      drawRoots(); runQuery(); return;
    }
    const size = t.closest('[data-size]')?.dataset.size;
    if (size) { prefs.size = size; savePrefs(); drawPrefs(); runQuery(); return; }
    const openDir = t.closest('[data-open-dir]')?.dataset.openDir;
    if (openDir != null) { openFolder(Number(openDir)); return; }
    const th = t.closest('.osr-th');
    if (th) {
      select(Number(th.dataset.i), {ctrl: event.ctrlKey || event.metaKey, shift: event.shiftKey});
      list.focus({preventScroll: true});
      return;
    }
    const act = t.closest('[data-act]')?.dataset.act;
    const item = st.items[st.current];
    switch (act) {
      case 'text': st.textMode = !st.textMode; drawChips(); closeSug(); input.focus(); break;
      case 'fav-save': await saveFavorite(); break;
      case 'sort': prefs.sort = prefs.sort === 'mtime_asc' ? 'mtime_desc' : 'mtime_asc'; savePrefs(); drawPrefs(); runQuery(); break;
      case 'view': prefs.view = prefs.view === 'flat' ? 'folder' : 'flat'; st.dir = null; savePrefs(); drawPrefs(); runQuery(); break;
      case 'folders-back': closeFolder(); break;
      case 'refreshq': runQuery(); break;
      case 'addroot': $('[data-addroot-row]').hidden = false; $('[data-rootpath]').focus(); break;
      case 'addroot-cancel': $('[data-addroot-row]').hidden = true; break;
      case 'addroot-ok': await addRoot(); break;
      case 'seldelete': await deleteItems(st.sel); break;
      case 'selclear': clearSel(); break;
      case 'selsave': await quicksave(chosen()); break;
      case 'selsaveas': await sessionHand()?.saveAsPaths(chosen().map(i => st.items[i].rel)); break;
      case 'saveall': await saveAllUnsaved(); break;
      case 'zip':
        if (!openUrl(`${HISTORY}/unsaved/download`)) toast('브라우저를 열지 못했습니다.', 'error');
        break;
      case 'clearall': await clearAll(); break;
      case 'big': openBig(); break;
      case 'main': if (item) sessionHand()?.showInMain(item.rel); break;
      case 'original': if (item && !openUrl(item.full)) toast('브라우저를 열지 못했습니다.', 'error'); break;
      case 'prompt': if (item) await doPrompt(item); break;
      case 'save': if (st.current != null) await quicksave([st.current]); break;
      case 'saveas': if (item) await sessionHand()?.saveAsPaths([item.rel]); break;
      case 'locate': if (item) await locate(item); break;
      case 'delete': if (item) await deleteItems(new Set([st.current])); break;
      default: break;
    }
  });
  host.addEventListener('contextmenu', event => {
    const favNode = event.target.closest('[data-fav-id]');
    const recentNode = event.target.closest('[data-recent-i]');
    if (!favNode && !recentNode) return;
    event.preventDefault();
    event.stopPropagation();
    if (favNode) {
      const fav = st.saved.favorites.find(f => f.id === favNode.dataset.favId);
      if (fav) favoriteMenu(event, fav);
    } else {
      const item = st.saved.recent[Number(recentNode.dataset.recentI)];
      if (item) recentMenu(event, item);
    }
  });
  host.addEventListener('keydown', event => {
    if (menu && event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); closeMenu(); }
  });
  host.addEventListener('dblclick', event => {
    const th = event.target.closest('.osr-th');
    if (th) openBig(Number(th.dataset.i));
  });

  async function saveAllUnsaved() {
    try {
      const data = await req(`${HISTORY}/unsaved/save-all`, {});
      toast(`미저장 ${fmt(data.saved || 0)}장을 저장했습니다.${data.remaining ? ` · 남음 ${fmt(data.remaining)}` : ''}`, 'success');
      runQuery();
    } catch (error) {
      toast(error.message, 'error');
    }
  }
  async function clearAll() {
    // 앱 안에서는 레일과 같은 흐름(미저장 장수를 세어 경고) - 비우고 나면 viewer_cleared 알림이 목록을 다시 부른다.
    if (sessionHand()?.clearAll) { sessionHand().clearAll(); return; }
    if (!(await confirmAsk('히스토리를 통째로 비울까요?\n저장된 파일은 그대로 남고, 저장 안 된 그림은 사라집니다.'))) return;
    try { await req(`${HISTORY}/clear`, {}); runQuery(); } catch (error) { toast(error.message, 'error'); }
  }
  async function addRoot() {
    const path = $('[data-rootpath]').value.trim();
    if (!path) return;
    try {
      await api('/roots', {action: 'add', path});
      $('[data-addroot-row]').hidden = true;
      $('[data-rootpath]').value = '';
      toast('폴더를 추가했습니다. 색인이 끝나면 결과에 나옵니다.', 'success');
      await loadStatus();
    } catch (error) {
      toast(error.message, 'error');
    }
  }

  input.addEventListener('input', () => {
    win.clearTimeout(sugTimer);
    if (!input.value.trim()) { closeSug(); return; }
    drawSug();
    sugTimer = win.setTimeout(loadSug, 120);
  });
  input.addEventListener('keydown', event => {
    const sugOpen = !$('[data-sug]').hidden;
    if (event.key === 'ArrowDown' && sugOpen) { event.preventDefault(); sugAct = Math.min(sugAct + 1, sugItems.length - 1); drawSug(); }
    else if (event.key === 'ArrowUp' && sugOpen) { event.preventDefault(); sugAct = Math.max(sugAct - 1, -1); drawSug(); }
    else if (event.key === 'Enter') {
      if (event.isComposing) return;
      event.preventDefault();
      // Shift+Enter = 반대쪽(포함 <-> 제외). 본문 글자 칸이면 그대로 본문.
      const {text, ex} = typed();
      const side = event.shiftKey ? !ex : ex;
      if (st.textMode) addChip(input.value, false);
      else if (sugAct >= 0 && sugItems[sugAct]) addChip(sugItems[sugAct].tag, true, side);
      else addChip(text, false, side);
    } else if (event.key === 'Escape') { if (sugOpen) { event.stopPropagation(); closeSug(); } }
    else if (event.key === 'Backspace' && !input.value && st.chips.length) { st.chips.pop(); drawChips(); runQuery(); }
  });
  $('[data-rootpath]').addEventListener('keydown', event => {
    if (event.key === 'Enter') { event.preventDefault(); addRoot(); }
  });
  doc.addEventListener('pointerdown', event => {
    if (!event.target.closest?.('[data-box]')) closeSug();
    if (menu && !event.target.closest?.('.osr-menu')) closeMenu();
  });
  // 목록의 키는 여기서 끝낸다 - 뒤의 히스토리 레일(document 리스너)이 Del · Ctrl+A · Esc 를 자기 선택에 쓰지 않게.
  list.addEventListener('keydown', event => {
    const key = event.key;
    const ctrl = event.ctrlKey || event.metaKey;
    const own = () => { event.preventDefault(); event.stopPropagation(); };
    // 뷰어 설정(⚙)이 숏컷 입력을 기다리는 중이면 이 키는 그쪽 몫이다.
    if (sessionHand()?.isCapturing?.()) return;
    if (isSaveKey(event)) { own(); saveShortcut(); return; }
    if (isDeleteKey(event)) {
      own();
      // 인페인트 편집 중에는 Del 이 캔버스의 것이다 - 창도 아무것도 지우지 않는다(레일과 같은 규칙).
      if (sessionHand()?.deleteKeyClaimed?.(event)) return;
      if (isSession() || st.local) deleteItems(new Set(chosen()));
      return;
    }
    if (key === 'Escape') { if (st.sel.size > 1) { own(); clearSel(); } return; }
    if (ctrl && String(key).toLowerCase() === 'a') {
      own();
      st.items.forEach((_, i) => st.sel.add(i));
      repaintAll(); drawSel();
      return;
    }
    const at = st.current ?? -1;
    if (overview() && (key === 'ArrowDown' || key === 'ArrowUp')) {
      own();
      const order = st.folderOrder;
      const here = order.indexOf(st.items[at]?.dir);
      const step = key === 'ArrowDown' ? 2 : -2;       // 카드가 한 줄에 둘 - 위아래는 한 줄
      const narrow = host.classList.contains('narrow');
      const target = order[Math.max(0, Math.min(order.length - 1, here + (narrow ? step / 2 : step)))];
      const next = st.items.findIndex(it => it.dir === target);
      if (next >= 0) moveTo(next, event.shiftKey);
      else if (key === 'ArrowDown') loadMore();
      return;
    }
    const cols = gridColumns();
    if (key === 'ArrowRight') { own(); moveTo(at + 1, event.shiftKey); return; }
    if (key === 'ArrowLeft') { own(); moveTo(Math.max(0, at - 1), event.shiftKey); return; }
    // 위아래는 한 줄(열 수만큼) - 덜 찬 마지막 줄에서는 끝 그림에 붙는다.
    if (key === 'ArrowDown') { own(); moveTo(Math.min(st.items.length - 1, at + cols), event.shiftKey); return; }
    if (key === 'ArrowUp') { own(); moveTo(Math.max(0, at - cols), event.shiftKey); return; }
    if (key === 'Home') { own(); moveTo(0); return; }
    if (key === 'End') { own(); moveTo(st.items.length - 1); return; }
    if (key === 'Enter' || key === ' ') { own(); openBig(); return; }
    if (isSession() && !ctrl && st.items[st.current] && sessionHand()?.dispatchBindingKey?.(event, st.items[st.current].rel)) own();
  });

  const AUX_BUTTONS = new Set([1, 3, 4]);
  function mouseBindingPath(event) {
    if (!isSession() || !AUX_BUTTONS.has(event.button) || !sessionHand()?.dispatchMouseBinding) return '';
    if (lightbox.isOpen()) return st.items[indexOfKey(lightbox.currentItem()?.key)]?.rel || '';
    return host.contains(event.target) ? (st.items[st.current]?.rel || '') : '';
  }
  // 뒤로 · 앞으로는 브라우저가 방문 기록을 넘기려 하므로 mousedown 에서 미리 막는다(옛 팝업과 같다).
  const onAuxDown = event => {
    if (mouseBindingPath(event) && sessionHand().mouseBindingId?.(event.button)) event.preventDefault();
  };
  const onAuxClick = event => {
    const path = mouseBindingPath(event);
    if (path && sessionHand().dispatchMouseBinding(event.button, path)) event.preventDefault();
  };
  doc.addEventListener('mousedown', onAuxDown);
  doc.addEventListener('auxclick', onAuxClick);

  // 좁은 창에서는 상세를 접는다(목록이 먼저다).
  const ro = typeof win.ResizeObserver === 'function'
    ? new win.ResizeObserver(() => { host.classList.toggle('narrow', host.clientWidth < 620); drawMore(); }) : null;
  ro?.observe(host);

  drawChips();
  drawSources();
  drawPrefs();
  drawScope();
  drawDetail();
  loadStatus();
  loadSaved();
  runQuery();
  // 다른 화면(외부 브라우저 · 휴대폰)에서 바꾼 목록 - 이 창으로 돌아오면 다시 읽는다.
  const onFocus = () => loadSaved();
  win.addEventListener('focus', onFocus);

  return {
    refresh() { loadStatus(); loadSaved(); runQuery(); },
    focus() { input.focus(); },
    setScope,
    scope: () => st.scope,
    state() { return {scope: st.scope, chips: st.chips.map(c => ({...c})), count: st.count, loaded: st.items.length}; },
    externalParams() {
      const p = new URLSearchParams();
      const {include, exclude, text} = chipQuery(st.chips);
      p.set('scope', st.scope);
      include.forEach(t => p.append('inc', t));
      exclude.forEach(t => p.append('exc', t));
      if (text) p.set('text', text);
      return p.toString();
    },
    /** Ctrl+S - 앱의 단일 판정이 부른다. 이 화면에서 눌렀으면 true(우리가 처리했다). */
    handleSaveShortcut(event) {
      if (!host.contains(event.target) || lightbox.isOpen()) return false;
      if (isSession()) { quicksave(chosen()); return true; }
      toast('전체 보기에서는 Ctrl+S 저장이 없습니다.', 'info');
      return true;
    },
    /** 이번 세션의 실시간 알림(앱의 웹소켓) - 'new' · 'removed' · 'cleared'. */
    sessionEvent(type, payload = {}) {
      if (type === 'removed') {
        if (payload.rel_path && isSession()) removeKeys(new Set([payload.rel_path]));
        // 서버가 준 남은 장수가 진실이다(다른 창 · 전체 범위에서 지운 것도 여기로 온다).
        if (Number.isFinite(Number(payload.total))) { st.total = Number(payload.total); drawScope(); drawCount(); }
        return;
      }
      if (type === 'cleared') { if (isSession()) runQuery(); else { st.total = 0; drawScope(); } return; }
      if (type !== 'new' || !payload.rel_path) return;
      if (Number.isFinite(Number(payload.total))) st.total = Number(payload.total);
      const dup = isSession() && st.items.some(it => it.key === payload.rel_path);
      if (payload.source === 'memory' && !dup) st.unsaved += 1;
      if (!isSession()) { drawScope(); return; }
      if (st.items.some(it => it.key === payload.rel_path)) return;
      // 거르는 중이거나 오래된순이면 어디에 낄지 모른다 - 알리기만 하고 [새 그림 ↻] 로 다시 찾게 한다.
      if (st.chips.length || prefs.sort === 'mtime_asc') { st.pendingNew += 1; drawCount(); return; }
      st.items.unshift(normSession(payload));
      st.count += 1;
      st.sel = new Set([...st.sel].map(i => i + 1));
      if (st.current != null) st.current += 1;
      if (st.anchor >= 0) st.anchor += 1;
      rebuild();
      if (st.current == null) select(0, {});
      drawCount();
      if (lightbox.isOpen()) lightbox.setItems(lbItems(), st.items[lightbox.current() + 1]?.key);
    },
    saveShortcut,
    destroy() {
      win.clearTimeout(statusTimer); win.clearTimeout(recentTimer); ro?.disconnect(); lightbox.close(); host.innerHTML = '';
      win.removeEventListener('focus', onFocus);
      doc.removeEventListener('mousedown', onAuxDown);
      doc.removeEventListener('auxclick', onAuxClick);
    },
  };
}
