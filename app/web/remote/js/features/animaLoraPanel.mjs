// ANIMA 전용 도구 > LoRA 창 — 관리형 엔진의 LoRA 컨테이너(사용자 지정 2026-09-27: 백엔드보다 먼저 화면).
// "COMFYUI 전용 도구" 자리에 ANIMA 전용 도구[해상도 프리셋 · LoRA]를 두고 LoRA 는 따로 뜨는 창으로.
// LoRA 컨테이너 규칙(사용자 지정): ① 폴더 열기로 LoRA 폴더에 접근 ② LoRA 마다 PNG 1장 칸 + 스키마 칸
//   (스키마는 복잡한 걸 보이지 않고 트리거 워드가 있으면 알려 준다) ③ 썸네일 채우기 = [히스토리](09-29 사용자 지정 -
//   Artist Thumbnail 의 조합 저장처럼 생성 히스토리에서 고른다, 이 LoRA 를 켜고 만든 그림이 앞). PNG 칸 · 후보에 올리면
//   크게 본다 - Artist Thumbnail(리모컨)의 확대 보기를 그대로 빌린다(zoom.show · zoom.hide, 창 옆 같은 자리 규칙).
// 창은 Memo 처럼 Tag Search 의 뼈대(tagsearch-*)를 입는다 — 컴팩트 팝업 규약(Memo · Tagger).
// 관리형 여부(COMFYUI 모드 + comfyui_engine 'managed' + 설치 준비됨)도 여기서 판단해 런처에 알린다(isManaged).
// 계약 = docs/ANIMA_MANAGED_ENGINE_CONTRACT_2026_09_27.md §3.3 · §8.3 · §8.4:
//   GET /loras -> {available: [{name, size, source, conflict, triggers, thumb}], chain, warnings}
//   PUT /loras {chain: [{name, strength, enabled}]} · GET/PUT/DELETE /loras/thumb?name= · POST /loras/open-folder {name?}
//   GET /loras/history?name= -> {candidates: [{history_id, thumb_url, zoom_url, used}]} · POST /loras/thumb/history {name, history_id}
//   PUT /loras/keyword {name, keyword} -> {name, keyword} (빈 값 = 지우기 · 겹치면 409 · 모양이 틀리면 422)
// 예약어(09-30 사용자 지정): 카드에서 정한다. 프롬프트에 `<` 없이 lora:예약어:강도 로 적으면 그 생성에서 켜지고(서버
//   core/anima_engine/prompt_loras.py), 태그 도우미의 lora: 자동완성이 loraKeywords() 로 목록을 읽는다.
// 적힌 순서대로 LoraLoaderModelOnly 사슬이 된다 — 정렬하지 않는다. 끈 항목은 그래프에서만 빠지고 목록 · 순서는 남는다.
// 서버는 생성을 큐에 넣는 순간의 체인을 요청에 박는다(여기서 바꿔도 이미 대기 중인 생성은 그대로).
// 서버가 돌려준 체인이 정본이다 — 거절(422)되면 이유를 보이고 서버 것을 다시 읽는다(몰래 고치지 않는다).
// style.css 는 건드리지 않는다(아래 STYLE — 새 클래스의 CSS 를 같은 파일에 둔다).
// 하위 폴더(09-30 사용자 지정): 왼쪽 = 카테고리(하위 폴더, 기본 '전체') · 오른쪽 = 보기(적용 순서 + 카드). 이름은 LoRA 폴더
//   기준 상대 경로(style/anime/a.safetensors, 슬래시) 그대로 - 카테고리는 그 앞부분이다(폴더를 고르면 그 아래 폴더까지).
//   엔진(ComfyUI)은 Windows 에서 역슬래시 이름을 쓰는데, 바꾸는 것은 서버가 그래프에 적을 때 한 번뿐이다(profile.py).
// 끌어다 놓기(09-30 사용자 지정: Artist Thumbnail 처럼) - 카드를 적용 순서에 놓으면 그 자리에 넣고, 체인 줄(번호 · 이름)을
//   끌면 순서를 바꾼다. 끌기는 창을 건너는 유일한 길인 dragBroker(포인터 + 유령, HTML5 끌기 아님)를 app.js 가 넘긴다.

const API = '/api/anima-engine';
const STYLE_ID = 'animaLoraStyle';
const BADGE_ID = 'badgeAnimaLora';   // 런처의 LoRA 항목 배지(카테고리 칩 "L{켜진 수}")
const DOCK_FOLD_KEY = 'naia.animaLoraDock.folded';   // 프롬프트 밑 LoRA 줄을 접었는가(기기마다)
const MAX_CHAIN = 32;                // 계약서 §3.3 — 요청 크기 보호용 상한(임의의 4개 같은 상한은 두지 않는다)
const STRENGTH_MIN = -2;
const STRENGTH_MAX = 2;
const SLIDER_MAX = 2;               // 슬라이더는 0 ~ 2(흔히 쓰는 쪽) - 음수는 칸에 적는다
const STEP = 0.05;
const WHEEL_SAVE_MS = 400;          // 휠은 멈춘 뒤 한 번 저장한다(돌리는 동안 매번 보내지 않는다)
const DOCK_ID = 'animaLoraDock';    // 프롬프트 밑 LoRA 줄(Estimated Tokens 위)
const RECHECK_MS = 5000;             // params 에코마다 상태를 다시 묻지 않는다
const MAX_THUMB_BYTES = 10 * 1024 * 1024;
const FLASH_MS = 1600;
const REMOTE_FOLDER = '폴더 열기는 NAIA 를 켠 PC 에서만 할 수 있습니다.';
const ZOOM_DELAY_MS = 140;           // 리모컨 확대 보기와 같다 - 훑고 지나갈 때 번쩍이지 않게
const ALL = '';                      // 카테고리 '전체'(기본)
const TOP = '.';                     // 하위 폴더 밖(LoRA 폴더 바로 아래) - 이름 조각에 '.' 은 없다(서버 resolve_lora 가 거절)
const STYLE = `
.anima-lora-popup { width: min(700px, calc(100vw - 16px)); height: min(600px, calc(100vh - 16px)); }
.anima-lora-popup .alr-headbtn { height: 22px; padding: 0 8px; font-size: 10px; flex: none; }
/* 왼쪽 = 카테고리(하위 폴더) · 오른쪽 = 보기(적용 순서 + 찾기 + 카드). 폴더 칸은 깊이만큼 들여 쓴다. */
.anima-lora-popup .alr-body { flex: 1; min-height: 0; display: flex; }
.anima-lora-popup .alr-cats { flex: none; width: 148px; overflow-y: auto; display: flex; flex-direction: column; gap: 1px;
  padding: 6px 0; border-right: 1px solid var(--border-dim); }
.anima-lora-popup .alr-cat { display: flex; align-items: center; gap: 6px; width: 100%; flex: none;
  padding: 4px 8px 4px calc(10px + var(--depth, 0) * 12px); background: none; border: 0; color: var(--text-muted);
  font-size: 11px; text-align: left; cursor: pointer; }
.anima-lora-popup .alr-cat:hover { background: rgba(96,120,255,0.08); color: var(--text-primary); }
.anima-lora-popup .alr-cat.on { background: rgba(96,120,255,0.18); color: var(--text-primary); }
.anima-lora-popup .alr-cat:focus-visible { outline: 1px solid var(--accent); outline-offset: -1px; }
.anima-lora-popup .alr-cat-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.anima-lora-popup .alr-cat-n { flex: none; font-family: var(--font-mono); font-size: 9.5px; color: var(--text-dim); }
.anima-lora-popup .alr-main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
/* 적용 순서 = 끌어다 놓는 자리. 머리줄 위에 놓아도 맨 앞으로 들어간다. 넣을 자리는 줄 위/아래 선으로 보인다. */
.anima-lora-popup .alr-chainbox { flex: none; display: flex; flex-direction: column; min-height: 0; }
.anima-lora-popup .alr-chainbox.is-drop-hover { background: rgba(124,106,239,0.07);
  box-shadow: inset 0 0 0 1px rgba(124,106,239,0.55); }
.anima-lora-popup .alr-chainbox.is-drop-hover .alr-item.drop-before { box-shadow: inset 0 2px 0 var(--accent); }
.anima-lora-popup .alr-chainbox.is-drop-hover .alr-item.drop-after { box-shadow: inset 0 -2px 0 var(--accent); }
.anima-lora-popup .alr-sec-hint { margin-left: auto; letter-spacing: 0; font-size: 9px; opacity: 0.85; }
.anima-lora-popup .alr-sec { display: flex; align-items: center; gap: 6px; padding: 5px 10px 4px;
  font-family: var(--font-mono); font-size: 9.5px; letter-spacing: 0.4px; color: var(--text-dim);
  border-bottom: 1px solid rgba(42,42,61,0.5); }
.anima-lora-popup .alr-chain { flex: 0 1 auto; max-height: 186px; min-height: 0; overflow-y: auto;
  border-bottom: 1px solid var(--border-dim); }
.anima-lora-popup .alr-item { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; row-gap: 3px; padding: 5px 10px;
  border-bottom: 1px solid rgba(42,42,61,0.5); }
/* 강도는 이름 밑 둘째 줄 - 순서 단추(↑↓)가 강도 칸 바로 옆에 있어 강도를 올리고 내리는 단추로 읽혔다
   (사용자 지적 09-29 "가중치 조절이 비직관적"). */
.anima-lora-popup .alr-item > .alr-strength { flex-basis: 100%; padding-left: 44px; }
.anima-lora-popup .alr-item:last-child { border-bottom: 0; }
.anima-lora-popup .alr-item.off .alr-name, .anima-lora-popup .alr-item.off .alr-strength { opacity: 0.45; }
.anima-lora-popup .alr-item[data-lora-row] .alr-idx, .anima-lora-popup .alr-item[data-lora-row] .alr-name { cursor: grab; }
/* 터치 - 끌기 전에 브라우저가 스크롤로 가져가면(pointercancel) 끌기가 취소된다. 손잡이(체인 번호 · 이름, 카드의 PNG 칸)만
   막는다 - 목록은 그 밖을 쓸면 그대로 굴러간다(Codex 리뷰 F6). */
.anima-lora-popup .alr-item[data-lora-row] .alr-idx, .anima-lora-popup .alr-item[data-lora-row] .alr-name,
.anima-lora-popup .alr-card[data-lora-card] .alr-png { touch-action: none; }
.anima-lora-popup .alr-dir { color: var(--text-dim); font-weight: 400; }
.anima-lora-popup .alr-item input[type=checkbox] { accent-color: var(--accent); cursor: pointer; margin: 0; flex: none; }
.anima-lora-popup .alr-idx { font-family: var(--font-mono); font-size: 9px; color: var(--text-dim); width: 14px; text-align: right; flex: none; }
.anima-lora-popup .alr-name { flex: 1; min-width: 0; font-family: var(--font-editor); font-size: 11.5px; color: var(--text-primary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.anima-lora-popup .alr-badge { font-family: var(--font-mono); font-size: 9px; padding: 0 5px; border-radius: 3px; flex: none;
  background: rgba(240,64,64,0.16); color: #f07070; }
/* 강도 - 슬라이더(0~2 · 0.05)로 끌고, 칸에는 정확한 값(-2~2, 음수 포함). 창과 프롬프트 밑 LoRA 줄이 같이 쓴다. */
.alr-strength { display: flex; align-items: center; gap: 8px; min-width: 0; }
.alr-strength input[type=range] { flex: 1; min-width: 60px; height: 16px; margin: 0; accent-color: var(--accent);
  cursor: pointer; background: transparent; }
.alr-strength input[type=range]:disabled { cursor: default; opacity: 0.5; }
.alr-strength .alr-w { width: 52px; flex: none; font-family: var(--font-mono); font-size: 11px; color: var(--text-muted);
  text-align: right; background: rgba(0,0,0,0.28); border: 1px solid var(--border-dim); border-radius: 5px; padding: 2px 5px;
  height: 22px; outline: none; }
.alr-strength .alr-w:focus { border-color: var(--accent); color: var(--accent-glow); }
/* 프롬프트 밑 LoRA 줄(사용자 지정 09-29) - Estimated Tokens 바로 위. 켜고 끄기 · 강도만, 순서 · 넣기 · 빼기는 창([편집]).
   부모(.prompt-token-footer)가 pointer-events:none 이라 여기서 다시 연다. 입력칸은 그 높이만큼 아래를 비운다. */
.anima-lora-dock { align-self: stretch; pointer-events: auto; display: flex; flex-direction: column; gap: 3px;
  padding: 0 0 5px; margin-bottom: 2px; border-bottom: 1px solid rgba(232,232,240,0.08); max-height: 104px; overflow-y: auto; }
.anima-lora-dock[hidden] { display: none !important; }
.anima-lora-dock .ald-head { display: flex; align-items: center; gap: 8px; font-size: 9.5px; letter-spacing: 0.4px;
  color: var(--text-dim); }
.anima-lora-dock .ald-head b { color: var(--accent-glow); font-weight: 600; }
.anima-lora-dock .ald-fold { display: inline-flex; align-items: center; gap: 5px; padding: 0; background: none; border: 0;
  font: inherit; letter-spacing: inherit; color: inherit; cursor: pointer; }
.anima-lora-dock .ald-fold:hover { color: var(--text-primary); }
.anima-lora-dock .ald-caret { width: 8px; font-size: 9px; }
.anima-lora-dock .ald-edit { margin-left: auto; height: 18px; padding: 0 8px; font-family: var(--font-mono); font-size: 9.5px;
  color: var(--text-muted); background: rgba(96,120,255,0.1); border: 1px solid rgba(130,150,255,0.3); border-radius: 5px;
  cursor: pointer; }
.anima-lora-dock .ald-edit:hover { color: var(--text-primary); background: rgba(96,120,255,0.2); }
.anima-lora-dock .ald-row { display: flex; align-items: center; gap: 8px; min-width: 0; }
.anima-lora-dock .ald-row input[type=checkbox] { accent-color: var(--accent); cursor: pointer; margin: 0; flex: none; }
.anima-lora-dock .ald-name { flex: 0 1 36%; min-width: 0; font-family: var(--font-editor); font-size: 11px;
  color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.anima-lora-dock .ald-row > .alr-strength { flex: 1; }
.anima-lora-dock .ald-row.off .ald-name, .anima-lora-dock .ald-row.off .alr-strength { opacity: 0.45; }
.prompt-highlight-wrap.has-anima-lora-dock .prompt-edit,
.prompt-highlight-wrap.has-anima-lora-dock .prompt-highlight { padding-bottom: calc(66px + var(--anima-lora-dock-h, 0px)); }
.anima-lora-popup .alr-btns { display: inline-flex; gap: 1px; flex: none; }
.anima-lora-popup .alr-btns button { background: none; border: 0; color: var(--text-dim); cursor: pointer; font-size: 10px;
  width: 20px; height: 22px; padding: 0; border-radius: 4px; line-height: 22px; }
.anima-lora-popup .alr-btns button:hover:not(:disabled) { color: var(--text-primary); background: rgba(96,120,255,0.14); }
.anima-lora-popup .alr-btns button[data-lora-rm]:hover:not(:disabled) { color: #f07070; background: rgba(255,90,90,0.14); }
.anima-lora-popup .alr-btns button:disabled { opacity: 0.25; cursor: default; }
.anima-lora-popup .alr-searchrow { padding: 6px 10px; }
.anima-lora-popup .alr-searchrow .tagsearch-input { height: 26px; font-size: 11px; }
.anima-lora-popup .alr-lib { flex: 1; min-height: 0; overflow-y: auto; }
.anima-lora-popup .alr-card { display: flex; gap: 10px; padding: 7px 10px; border-bottom: 1px solid rgba(42,42,61,0.5); }
.anima-lora-popup .alr-card.in-chain { background: rgba(96,120,255,0.07); }
.anima-lora-popup .alr-card[data-lora-card] { cursor: grab; }
.anima-lora-popup .alr-card-dir { font-family: var(--font-mono); font-size: 9px; color: var(--text-dim);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.anima-lora-popup .alr-png { position: relative; flex: none; width: 54px; height: 72px; border-radius: 6px; overflow: hidden;
  border: 1px dashed var(--border-glow); background: rgba(0,0,0,0.28); cursor: pointer; padding: 0;
  display: flex; align-items: center; justify-content: center; color: var(--text-dim); font-family: var(--font-mono); font-size: 9px; }
.anima-lora-popup .alr-png.has-img { border-style: solid; border-color: var(--border-dim); }
.anima-lora-popup .alr-png.drop { border-color: var(--accent); background: rgba(124,106,239,0.16); }
.anima-lora-popup .alr-png img { width: 100%; height: 100%; object-fit: cover; display: block; }
.anima-lora-popup .alr-card-body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.anima-lora-popup .alr-card-top { display: flex; align-items: baseline; gap: 6px; min-width: 0; }
.anima-lora-popup .alr-card-name { flex: 1; min-width: 0; font-family: var(--font-editor); font-size: 11.5px; font-weight: 600;
  color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.anima-lora-popup .alr-card-meta { flex: none; font-family: var(--font-mono); font-size: 9px; color: var(--text-dim); }
.anima-lora-popup .alr-trig { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; font-size: 10px; color: var(--text-dim); }
.anima-lora-popup .alr-chip { font-family: var(--font-editor); font-size: 10.5px; padding: 1px 6px; border-radius: 4px; cursor: pointer;
  border: 1px solid rgba(130,150,255,0.36); background: rgba(96,120,255,0.12); color: var(--text-primary); }
.anima-lora-popup .alr-chip:hover { background: rgba(96,120,255,0.24); }
.anima-lora-popup .alr-guess { font-size: 9px; color: #f5df8b; }
.anima-lora-popup .alr-card-acts { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: auto; }
/* 예약어 - 정해 두면 lora:예약어 칩(누르면 고치기), 고치는 동안은 그 줄이 입력칸이 된다 */
.anima-lora-popup .alr-kw-chip { font-family: var(--font-mono); font-size: 10px; }
.anima-lora-popup .alr-kw-edit { gap: 4px; font-family: var(--font-mono); font-size: 10.5px; color: var(--text-dim); }
.anima-lora-popup .alr-kw-input { width: 150px; height: 22px; padding: 0 6px; font-family: var(--font-mono); font-size: 11px;
  color: var(--text-primary); background: rgba(0,0,0,0.28); border: 1px solid var(--border-dim); border-radius: 5px; outline: none; }
.anima-lora-popup .alr-kw-input:focus { border-color: var(--accent); }
.anima-lora-popup .alr-kw-err { font-size: 10px; color: #f07070; line-height: 1.4; }
.anima-lora-popup .alr-card-acts .tagsearch-act { height: 22px; padding: 0 8px; font-size: 10px; }
.anima-lora-popup .alr-inchain { font-family: var(--font-mono); font-size: 9.5px; color: var(--accent-glow); }
.anima-lora-popup .alr-mini { background: none; border: 0; padding: 0; color: var(--text-dim); cursor: pointer; font-size: 10px; }
.anima-lora-popup .alr-mini:hover { color: var(--text-primary); text-decoration: underline; }
.anima-lora-popup .alr-empty { padding: 16px 12px; text-align: center; font-size: 11px; color: var(--text-dim); line-height: 1.6; }
.anima-lora-popup .alr-foot { padding: 6px 10px; border-top: 1px solid var(--border-dim); display: flex; flex-direction: column; gap: 3px; }
.anima-lora-popup .alr-note { font-size: 10px; color: var(--text-dim); line-height: 1.5; }
.anima-lora-popup .alr-warn { font-size: 10px; color: #f5df8b; line-height: 1.5; }
.anima-lora-popup .alr-error { font-size: 10px; color: #f07070; line-height: 1.5; }
.anima-lora-popup .alr-link { background: none; border: 0; padding: 0; color: var(--accent-glow); cursor: pointer; font-size: inherit; }
.anima-lora-popup .alr-link:hover { text-decoration: underline; }
/* [히스토리] - 창 몸통을 덮는 판(머리줄은 남긴다). 창이 overflow:hidden 이라 모서리가 따라 깎인다. */
.anima-lora-popup .alr-pick { position: absolute; left: 0; right: 0; bottom: 0; top: 33px; z-index: 2;
  display: flex; flex-direction: column; background: rgba(15,15,23,0.99); }
.anima-lora-popup .alr-pick[hidden] { display: none; }
.anima-lora-popup .alr-pick-head { display: flex; align-items: center; gap: 6px; padding: 5px 8px 5px 10px; min-width: 0;
  font-size: 10.5px; color: var(--text-dim); border-bottom: 1px solid rgba(42,42,61,0.5); }
.anima-lora-popup .alr-pick-head b { min-width: 0; font-family: var(--font-editor); font-size: 11.5px; font-weight: 600;
  color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.anima-lora-popup .alr-pick-head .tagsearch-x { margin-left: auto; }
.anima-lora-popup .alr-pick-body { flex: 1; min-height: 0; overflow-y: auto; padding: 8px 10px 10px; }
.anima-lora-popup .alr-pick-label { font-family: var(--font-mono); font-size: 9.5px; letter-spacing: 0.4px; color: var(--text-dim);
  margin: 0 0 6px; }
.anima-lora-popup .alr-pick-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(78px, 1fr)); gap: 6px;
  margin-bottom: 10px; }
.anima-lora-popup .alr-pick-cell { aspect-ratio: 3 / 4; padding: 0; border: 1px solid var(--border-dim); border-radius: 6px;
  overflow: hidden; background: rgba(0,0,0,0.28); cursor: pointer; }
.anima-lora-popup .alr-pick-cell:hover:not(:disabled) { border-color: var(--accent); }
.anima-lora-popup .alr-pick-cell:disabled { opacity: 0.5; cursor: default; }
.anima-lora-popup .alr-pick-cell img { width: 100%; height: 100%; object-fit: cover; display: block; }
.anima-lora-popup .alr-pick-note { padding: 18px 6px; text-align: center; font-size: 11px; color: var(--text-dim); line-height: 1.6; }
.anima-lora-popup .alr-pick-error { font-size: 10px; color: #f07070; line-height: 1.5; margin-bottom: 6px; }
/* 좁은 화면(폰) - 카테고리는 몸통 위의 한 줄(옆으로 넘긴다) */
@media (max-width: 600px) {
  .anima-lora-popup .alr-body { flex-direction: column; }
  .anima-lora-popup .alr-cats { width: auto; flex-direction: row; overflow-x: auto; overflow-y: hidden;
    border-right: 0; border-bottom: 1px solid var(--border-dim); padding: 4px 6px; }
  .anima-lora-popup .alr-cat { width: auto; padding: 3px 8px; white-space: nowrap; }
}
`;

export function createAnimaLoraPanel({ document, window: win = window, fetch: fetchFn = win.fetch.bind(win),
  onOpenSetup = () => {}, onStateChange = () => {}, zoom = {}, broker = null }) {
  let mode = '';
  let managed = false;       // 관리형 + 준비됨 — 런처가 ANIMA 전용 도구를 보일지 여기로 묻는다
  let checkedAt = 0;
  let checking = null;       // 진행 중인 상태 확인(Promise) — 겹쳐 묻지 않는다
  let available = [];
  let chain = [];
  let warnings = [];
  let error = '';
  let busy = false;
  let filter = '';
  let flashText = '';
  let flashTimer = 0;
  let pngTarget = '';        // 파일 고르기 창을 연 카드의 LoRA 이름
  let popup = null;
  let onResize = null;
  let dock = null;           // 프롬프트 밑 LoRA 줄 - 켜진 관리형 체인이 있을 때만 보인다
  let dockFolded = readDockFold();   // 그 줄을 머리(LoRA 켜짐 수 · [편집])만 남기고 접었는가
  let dragging = false;      // 강도 슬라이더를 끄는 중 - 그동안 줄을 다시 그리지 않는다(손잡이가 사라진다)
  let dragPointer = null;    // 끌기를 시작한 포인터(pointerId) - 다른 포인터(펜 hover · 다른 손가락)는 이 끌기를 끝내지 않는다
  let wheelTimer = 0;
  let windowRelease = false;   // 창(window)의 pointerup 도 듣는가 - 줄 · LoRA 창 밖에서 놓아도 끌기는 끝났다
  // 휠로 바꾸고 아직 저장하지 않은 강도 - LoRA 이름별. 행 번호로 쥐면 그사이 순서를 바꾸거나 뺀 뒤 다른 LoRA 에 들어갔다.
  const wheelEdits = new Map();
  let picker = null;         // [히스토리] 판 - {name, rows: null(불러오는 중) | [...], error}
  let pickerSeq = 0;         // 다시 열면 앞서 연 판의 늦은 목록을 버린다(닫았으면 picker 가 없다)
  let zoomTarget = null;     // 크게 보려고 올린 칸
  let zoomTimer = 0;
  let zoomShown = false;     // 내가 띄운 확대 보기만 걷는다
  let category = ALL;        // 왼쪽 카테고리(하위 폴더) - 창을 닫았다 열어도 그대로, 새로 켜면 '전체'
  let chainZone = null;      // 적용 순서를 끌어다 놓는 자리로 올렸는가(dragBroker)
  let kwEdit = null;         // 예약어를 고치는 카드 - {name, value, error, saving}

  const esc = value => String(value == null ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const shortName = name => String(name || '').replace(/\.safetensors$/i, '');
  const fmtStrength = value => (Number.isFinite(Number(value)) ? Number(value).toFixed(2) : '1.00');
  const shownStrength = item => (wheelEdits.has(item.name) ? wheelEdits.get(item.name) : item.strength);
  const fmtSize = bytes => (Number(bytes) >= 1048576 ? `${Math.round(Number(bytes) / 1048576)}MB` : `${Math.max(1, Math.round((Number(bytes) || 0) / 1024))}KB`);
  const pick = selector => (popup ? popup.querySelector(selector) : null);
  const thumbUrl = item => `${API}/loras/thumb?name=${encodeURIComponent(item.name)}&v=${encodeURIComponent(item.thumb.version ?? '')}`;
  // 이름 = LoRA 폴더 기준 상대 경로(슬래시). 폴더 = 마지막 / 앞, 보이는 이름 = 그 뒤(확장자 뺌)
  const folderOf = name => { const s = String(name || ''); const at = s.lastIndexOf('/'); return at < 0 ? '' : s.slice(0, at); };
  const baseName = name => shortName(String(name || '').slice(String(name || '').lastIndexOf('/') + 1));
  const dirHtml = name => (folderOf(name) ? `<span class="alr-dir">${esc(folderOf(name))}/</span>` : '');
  // 처음 정할 때 채워 두는 예약어 - 보이는 이름을 소문자로, 서버가 받는 글자(글자 · 숫자 · _ . -)만
  const suggestKeyword = name => baseName(name).normalize('NFC').toLowerCase()
    .replace(/[^\p{L}\p{N}_.\-]+/gu, '_').replace(/^_+|_+$/g, '').slice(0, 48);

  function ensureStyle() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = STYLE;
    document.head.appendChild(style);
  }

  async function call(method, path, body) {
    const init = { method, cache: 'no-store' };
    if (body !== undefined) {
      init.headers = { 'Content-Type': 'application/json' };
      init.body = JSON.stringify(body);
    }
    const res = await fetchFn(`${API}${path}`, init);
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) {
      const err = new Error(data.error || `요청 실패 (${res.status})`);
      err.status = res.status;
      err.code = data.code || '';
      throw err;
    }
    return data;
  }

  function flash(text) {
    flashText = text;
    win.clearTimeout?.(flashTimer);
    flashTimer = win.setTimeout?.(() => { flashText = ''; paintStatus(); }, FLASH_MS);
    paintStatus();
  }

  // ---- 관리형인가(런처가 묻는다) ----

  function isManaged() {
    return managed && mode === 'COMFYUI';
  }

  function check() {
    if (checking) return checking;
    checking = (async () => {
      const before = isManaged();
      try {
        const st = await call('GET', '/status');
        managed = st.comfyui_engine === 'managed' && ((st.install || {}).state === 'ready');
      } catch (err) {
        managed = false;          // 백엔드가 없는 판(404) · 끊김 — ANIMA 전용 도구를 숨긴다
      }
      checkedAt = Date.now();
      checking = null;
      if (isManaged()) await load();
      else paintOutside();
      if (before !== isManaged()) onStateChange();
    })();
    return checking;
  }

  function setMode(next) {
    const before = isManaged();
    mode = String(next || '').toUpperCase();
    if (mode === 'COMFYUI' && Date.now() - checkedAt > RECHECK_MS) check();
    if (before !== isManaged()) {
      if (!isManaged()) close();
      onStateChange();
    }
    paintOutside();
  }

  function refresh() {
    checkedAt = 0;
    if (mode === 'COMFYUI') return check();
    return Promise.resolve();
  }

  // ---- 서버 ----

  async function load() {
    try {
      const data = await call('GET', '/loras');
      available = Array.isArray(data.available) ? data.available : [];
      chain = Array.isArray(data.chain) ? data.chain : [];
      warnings = Array.isArray(data.warnings) ? data.warnings : [];
    } catch (err) {
      error = err.message;
    }
    render();
  }

  async function save(next) {
    // 휠로 돌려 두고 아직 저장하지 않은 강도를 이번 저장에 이름으로 싣는다. 따로 늦게 보내면 옛 목록이 이겨, 그사이
    // 끈 LoRA 를 다시 켜거나 순서를 바꾼 뒤 다른 LoRA 에 강도가 들어갔다(Codex 09-29).
    win.clearTimeout?.(wheelTimer);
    if (wheelEdits.size) {
      next = next.map(item => (wheelEdits.has(item.name) ? { ...item, strength: wheelEdits.get(item.name) } : item));
      wheelEdits.clear();
    }
    busy = true;
    error = '';
    render(next);
    try {
      const data = await call('PUT', '/loras', {
        chain: next.map(item => ({ name: item.name, strength: Number(item.strength), enabled: item.enabled !== false })),
      });
      chain = Array.isArray(data.chain) ? data.chain : next;
      busy = false;
      render();
    } catch (err) {
      busy = false;
      error = err.message;
      await load();                // 거절됐다 — 서버가 들고 있는 체인으로 되돌린다
    }
  }

  // LoRA 마다 PNG 한 장(계약서 §8.4) — 받은 바이트를 그대로 보내고 서버가 시그니처 · 크기를 다시 본다.
  async function uploadThumb(name, file) {
    if (!name || !file) return;
    if (file.type !== 'image/png' || Number(file.size) > MAX_THUMB_BYTES) {
      error = 'PNG 파일만 넣을 수 있습니다(10MB 이하).';
      render();
      return;
    }
    busy = true;
    error = '';
    render();
    try {
      const res = await fetchFn(`${API}/loras/thumb?name=${encodeURIComponent(name)}`, {
        method: 'PUT', headers: { 'Content-Type': 'image/png' }, body: await file.arrayBuffer(), cache: 'no-store',
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) throw new Error(data.error || `요청 실패 (${res.status})`);
      flash('PNG 를 넣었습니다');
    } catch (err) {
      error = err.message;
    }
    busy = false;
    await load();
  }

  async function deleteThumb(name) {
    busy = true;
    render();
    try {
      await call('DELETE', `/loras/thumb?name=${encodeURIComponent(name)}`);
    } catch (err) {
      error = err.message;
    }
    busy = false;
    await load();
  }

  async function openFolder(name) {
    try {
      await call('POST', '/loras/open-folder', name ? { name } : {});
      flash('폴더를 열었습니다');
    } catch (err) {
      error = err.status === 403 ? REMOTE_FOLDER : err.message;
      render();
    }
  }

  // ---- 그리기 ----

  // 런처 LoRA 항목의 배지 — 켜진 LoRA 수(0 이면 숨김). 카테고리 칩은 런처가 "L{n}" 으로 모은다.
  function paintBadge() {
    const badge = document.getElementById(BADGE_ID);
    if (!badge) return;
    const on = isManaged() ? chain.filter(item => item.enabled !== false).length : 0;
    const text = on ? String(on) : '';
    if (badge.textContent !== text) badge.textContent = text;
    badge.classList.toggle('hidden', !on);
  }

  // 창 밖에 보이는 것 - 런처 배지와 프롬프트 밑 LoRA 줄
  function paintOutside(view = chain) {
    paintBadge();
    paintDock(view);
  }

  // 강도 - 슬라이더(0~2)로 끌고 칸에는 정확한 값을 적는다(-2~2, 음수 포함). 놓을 때 한 번 저장한다.
  // 더블클릭 = 1.00 · 휠 = ±0.05(Shift ±0.25). 음수면 슬라이더는 0 에 서 있다(칸이 정본).
  function strengthHtml(i, strength) {
    const value = Number.isFinite(Number(strength)) ? Number(strength) : 1;
    const slider = Math.min(SLIDER_MAX, Math.max(0, value));
    return `<span class="alr-strength" title="강도 · 더블클릭 = 1.00 · 휠 = ±0.05 · 음수는 칸에 적습니다">
        <input type="range" data-lora-slider="${i}" min="0" max="${SLIDER_MAX}" step="${STEP}" value="${slider}"
               aria-label="강도"${busy ? ' disabled' : ''}>
        <input class="alr-w" data-lora-w="${i}" type="number" step="${STEP}" min="${STRENGTH_MIN}" max="${STRENGTH_MAX}"
               value="${fmtStrength(strength)}" aria-label="강도"${busy ? ' disabled' : ''}></span>`;
  }

  // 다시 그린 뒤 초점을 같은 조작으로 돌려놓는다 - 칸만이 아니라 슬라이더도(키보드 ←→ 로 연달아 움직일 때 저장마다
  // 줄이 새로 그려져 초점이 사라졌다, 라이브 09-29). ⚠️ 저장하는 동안(busy)은 조작이 잠겨 초점을 받지 못한다 - 그때는
  // 자리를 기억해 두고 다음 그리기(저장이 끝난 뒤)에서 준다. 그사이 사람이 다른 곳을 눌렀으면 그쪽이 이긴다.
  const pendingFocus = new WeakMap();

  function focusKey(container) {
    const active = document.activeElement;
    if (active && container.contains?.(active)) {
      for (const attr of ['data-lora-w', 'data-lora-slider']) {
        const index = active.getAttribute?.(attr);
        if (index != null) return [attr, index];
      }
      return null;
    }
    return !active || active === document.body ? pendingFocus.get(container) || null : null;
  }

  function restoreFocus(container, key) {
    pendingFocus.delete(container);
    const target = key ? container.querySelector?.(`[${key[0]}="${key[1]}"]`) : null;
    if (!target) return;
    if (target.disabled) pendingFocus.set(container, key);
    else target.focus?.();
  }

  function ensureDock() {
    if (dock) return dock;
    const footer = document.getElementById('promptTokenFooter');
    if (!footer || typeof footer.insertBefore !== 'function') return null;
    dock = document.createElement('div');
    dock.className = 'anima-lora-dock';
    dock.id = DOCK_ID;
    dock.hidden = true;
    footer.insertBefore(dock, footer.firstChild);   // Estimated Tokens 줄 바로 위
    listen(dock);
    return dock;
  }

  // 접기(사용자 지정 09-30) - 기기마다 기억한다(localStorage). 못 쓰는 브라우저면 이번 화면에서만 접힌다.
  function readDockFold() {
    try { return win.localStorage?.getItem(DOCK_FOLD_KEY) === '1'; } catch (_) { return false; }
  }

  function saveDockFold() {
    try { win.localStorage?.setItem(DOCK_FOLD_KEY, dockFolded ? '1' : '0'); } catch (_) { /* 저장 못 해도 접힌다 */ }
  }

  // 프롬프트 밑 LoRA 줄(사용자 지정 09-29) - 관리형 ANIMA 이고 체인이 있을 때만. 켜기 · 강도만 여기서, 순서 · 넣기 ·
  // 빼기는 창([편집]). 체인은 창과 하나다(같은 save) - 어느 쪽에서 바꿔도 둘 다 다시 그린다.
  // 머리 줄(LoRA n / m)을 누르면 접고 편다(09-30) - 접으면 줄들을 빼고, 입력칸이 비워 둔 아래도 그만큼 준다.
  function paintDock(view = chain) {
    const el = ensureDock();
    if (!el) return;
    const wrap = typeof el.closest === 'function' ? el.closest('.prompt-highlight-wrap') : null;
    if (!isManaged() || !view.length) {
      el.hidden = true;
      el.innerHTML = '';
      wrap?.classList.remove('has-anima-lora-dock');
      return;
    }
    if (dragging) return;
    const on = view.filter(item => item.enabled !== false).length;
    const focused = focusKey(el);
    // 접힌 동안 무엇이 켜져 있는지는 머리 줄에 올리면 보인다
    const onNames = view.filter(item => item.enabled !== false)
      .map(item => `${baseName(item.name)} ${fmtStrength(shownStrength(item))}`).join(', ');
    const foldTitle = dockFolded ? `펼치기${onNames ? ` — 켜짐: ${onNames}` : ''}` : '접기';
    el.innerHTML = `<div class="ald-head"><button type="button" class="ald-fold" data-lora-act="fold"
          aria-expanded="${dockFolded ? 'false' : 'true'}" title="${esc(foldTitle)}"><span class="ald-caret">${
          dockFolded ? '▸' : '▾'}</span>LoRA <b>${on} / ${view.length}</b></button>
        <button type="button" class="ald-edit" data-lora-act="open" title="LoRA 창 - 넣기 · 빼기 · 순서">편집</button></div>
      ${dockFolded ? '' : view.map((item, i) => `<div class="ald-row${item.enabled === false ? ' off' : ''}">
        <input type="checkbox" data-lora-on="${i}"${item.enabled === false ? '' : ' checked'}${busy ? ' disabled' : ''}
               title="켜기 / 끄기">
        <span class="ald-name" title="${esc(item.name)}">${esc(baseName(item.name))}</span>
        ${strengthHtml(i, shownStrength(item))}</div>`).join('')}`;
    el.hidden = false;
    restoreFocus(el, focused);
    wrap?.classList.add('has-anima-lora-dock');
    wrap?.style?.setProperty?.('--anima-lora-dock-h', `${Math.ceil(el.offsetHeight || 0) + 2}px`);
  }

  function paintStatus(view = chain) {
    const status = pick('.tagsearch-status');
    if (!status) return;
    const on = view.filter(item => item.enabled !== false).length;
    status.textContent = busy ? '저장 중…' : flashText || (view.length ? `켜짐 ${on} / ${view.length}` : '');
    status.className = `tagsearch-status${busy ? ' busy' : flashText ? ' ok' : ''}`;
  }

  function chainHtml(view) {
    const names = new Map(available.map(item => [item.name, item]));
    if (!view.length) {
      return `<div class="alr-empty">체인이 비어 있습니다 — ${broker ? '아래 카드를 여기로 끌어다 놓거나 ' : '아래 목록에서 '}[+ 체인] 으로 넣으세요.</div>`;
    }
    return view.map((item, i) => {
      const meta = names.get(item.name);
      const badge = !meta ? '<span class="alr-badge" title="폴더에 이 파일이 없습니다 — 생성이 거절됩니다">없음</span>'
        : meta.conflict ? '<span class="alr-badge" title="같은 이름의 파일이 여러 폴더에 있습니다">이름 겹침</span>' : '';
      return `<div class="alr-item${item.enabled === false ? ' off' : ''}"${broker ? ` data-lora-row="${i}"` : ''}>
        <input type="checkbox" data-lora-on="${i}"${item.enabled === false ? '' : ' checked'}${busy ? ' disabled' : ''}
               title="켜기 / 끄기(끈 항목은 사슬에서 빠지고 자리는 남습니다)">
        <span class="alr-idx">${i + 1}</span>
        <span class="alr-name" title="${esc(item.name)}">${dirHtml(item.name)}${esc(baseName(item.name))}</span>${badge}
        <span class="alr-btns">
          <button type="button" data-lora-up="${i}" title="적용 순서 위로"${busy || i === 0 ? ' disabled' : ''}>↑</button>
          <button type="button" data-lora-down="${i}" title="적용 순서 아래로"${busy || i === view.length - 1 ? ' disabled' : ''}>↓</button>
          <button type="button" data-lora-rm="${i}" title="체인에서 빼기"${busy ? ' disabled' : ''}>✕</button>
        </span>
        ${strengthHtml(i, shownStrength(item))}</div>`;
    }).join('');
  }

  // 스키마 칸 — 복잡한 건 보이지 않는다: 트리거 워드가 있으면 그것만(누르면 복사), 캡션 추정은 "추정" 표시.
  function triggerHtml(item) {
    const triggers = Array.isArray(item.triggers) ? item.triggers : [];
    if (!triggers.length) return '<div class="alr-trig">트리거 워드 없음</div>';
    const guessed = triggers.some(t => t.source === 'caption');
    return `<div class="alr-trig">트리거 ${triggers.map(t => `<button type="button" class="alr-chip" data-lora-copy="${
      esc(t.word)}" title="눌러서 복사">${esc(t.word)}</button>`).join('')}${
      guessed ? '<span class="alr-guess" title="학습 캡션에서 추정했습니다">추정</span>' : ''}</div>`;
  }

  // ---- 카테고리(하위 폴더) ----

  // 폴더마다 LoRA 수(그 아래 폴더까지 센다). 중간 폴더도 칸이 된다(a/b/x 면 a · a/b). 이름 순, 숫자는 크기대로.
  function categories() {
    const counts = new Map();
    let top = 0;
    for (const item of available) {
      const folder = folderOf(item.name);
      if (!folder) { top += 1; continue; }
      const parts = folder.split('/');
      for (let i = 1; i <= parts.length; i += 1) {
        const path = parts.slice(0, i).join('/');
        counts.set(path, (counts.get(path) || 0) + 1);
      }
    }
    const byParts = (a, b) => {
      const x = a.split('/');
      const y = b.split('/');
      for (let i = 0; i < Math.min(x.length, y.length); i += 1) {
        const c = x[i].localeCompare(y[i], undefined, { sensitivity: 'base', numeric: true });
        if (c) return c;
      }
      return x.length - y.length;
    };
    const folders = [...counts.keys()].sort(byParts)
      .map(path => ({ path, depth: path.split('/').length - 1, label: path.split('/').pop(), count: counts.get(path) }));
    return { top, folders };
  }

  function inCategory(item) {
    if (category === ALL) return true;
    const folder = folderOf(item.name);
    if (category === TOP) return !folder;
    return folder === category || folder.startsWith(`${category}/`);
  }

  // 고른 칸이 사라졌으면(폴더를 비웠다 · 다른 기기에서 옮겼다) '전체' 로 - 빈 목록 앞에 세워 두지 않는다.
  // '최상위' 는 하위 폴더가 있을 때만 칸이 된다(없으면 '전체' 와 같다).
  function catsHtml() {
    const { top, folders } = categories();
    const exists = category === TOP ? Boolean(top && folders.length) : folders.some(f => f.path === category);
    if (category !== ALL && !exists) category = ALL;
    const row = (key, label, count, depth, title) => `<button type="button" class="alr-cat${key === category ? ' on' : ''}"
        data-lora-cat="${esc(key)}" style="--depth:${depth}" title="${esc(title)}"${key === category ? ' aria-current="true"' : ''}>
        <span class="alr-cat-name">${esc(label)}</span><span class="alr-cat-n">${count}</span></button>`;
    return [row(ALL, '전체', available.length, 0, '모든 LoRA'),
      top && folders.length ? row(TOP, '최상위', top, 0, 'LoRA 폴더 바로 아래(하위 폴더 밖)') : '',
      ...folders.map(f => row(f.path, f.label, f.count, f.depth, f.path))].join('');
  }

  // 다시 그리면 초점을 가진 단추가 사라진다 - 키보드로 고르던 자리(같은 칸, 사라졌으면 고른 칸)로 돌려준다(Codex 리뷰 F8)
  function paintCats() {
    const el = pick('.alr-cats');
    if (!el) return;
    const active = document.activeElement;
    const focused = active && el.contains?.(active) ? active.getAttribute?.('data-lora-cat') : null;
    el.innerHTML = isManaged() ? catsHtml() : '';
    if (focused == null) return;
    const buttons = [...(el.querySelectorAll?.('[data-lora-cat]') || [])];
    (buttons.find(b => b.getAttribute('data-lora-cat') === focused) || el.querySelector?.('.alr-cat.on'))?.focus?.();
  }

  // 예약어를 고치는 줄 - Enter = 저장 · Esc = 그만두기(창은 안 닫힌다) · 빈 값으로 저장하거나 [지우기] = 지우기
  function kwEditHtml(item) {
    const off = kwEdit.saving ? ' disabled' : '';
    return `<div class="alr-card-acts alr-kw-edit">lora:<input class="alr-kw-input" data-lora-kwinput="${esc(item.name)}"
        value="${esc(kwEdit.value)}" maxlength="48" spellcheck="false" autocomplete="off" aria-label="예약어"${off}>
        <button type="button" class="tagsearch-act" data-lora-kwsave="${esc(item.name)}"${off}>저장</button>
        ${item.keyword ? `<button type="button" class="alr-mini" data-lora-kwclear="${esc(item.name)}"${off}>지우기</button>` : ''}
        <button type="button" class="alr-mini" data-lora-kwcancel${off}>취소</button></div>${
      kwEdit.error ? `<div class="alr-kw-err">${esc(kwEdit.error)}</div>` : ''}`;
  }

  // 보기를 다시 그린다 - 예약어를 치던 중이면 새 입력칸으로 초점과 캐럿(끝)을 돌려준다
  function paintLib(focusKw = false) {
    const libEl = pick('.alr-lib');
    if (!libEl) return;
    const active = document.activeElement;
    const inField = Boolean(active && active.getAttribute?.('data-lora-kwinput') != null && libEl.contains?.(active));
    const typing = focusKw || inField;
    // 치던 자리 - 가운데를 고치는 중에 다른 저장 · 목록 다시 읽기가 끝나도 캐럿이 끝으로 튀지 않게(Codex 09-30)
    const sel = inField && Number.isInteger(active.selectionStart)
      ? [active.selectionStart, active.selectionEnd, active.selectionDirection || 'none'] : null;
    libEl.innerHTML = libraryHtml();
    if (!typing || !kwEdit) return;
    const input = libEl.querySelector?.('[data-lora-kwinput]');
    if (!input || input.disabled) return;
    input.focus?.();
    const end = String(input.value || '').length;
    if (sel) input.setSelectionRange?.(Math.min(sel[0], end), Math.min(sel[1], end), sel[2]);
    else input.setSelectionRange?.(end, end);
  }

  function startKwEdit(name) {
    const item = available.find(x => x.name === name);
    if (!item || item.conflict) return;
    kwEdit = { name, value: item.keyword || suggestKeyword(name), error: '', saving: false };
    paintLib(true);
    pick('[data-lora-kwinput]')?.select?.();
  }

  function cancelKwEdit() {
    if (!kwEdit || kwEdit.saving) return;
    kwEdit = null;
    paintLib();
  }

  // 서버가 정본이다 - 겹침(409) · 모양(422)이면 그 줄에 이유를 두고 계속 고친다
  async function saveKeyword(name, value) {
    if (!kwEdit || kwEdit.name !== name || kwEdit.saving) return;
    kwEdit.saving = true;
    kwEdit.error = '';
    paintLib();
    try {
      const data = await call('PUT', '/loras/keyword', { name, keyword: String(value || '').trim() });
      const item = available.find(x => x.name === name);
      if (item) item.keyword = data.keyword || '';
      if (kwEdit && kwEdit.name === name) kwEdit = null;
      flash(data.keyword ? `예약어: lora:${data.keyword}` : '예약어를 지웠습니다');
      paintLib();
    } catch (err) {
      if (kwEdit && kwEdit.name === name) {
        kwEdit.saving = false;
        kwEdit.error = err.message;
      }
      paintLib(true);
    }
  }

  // 태그 도우미의 lora: 자동완성이 읽는다 - 관리형이 아니면 null(그러면 `lora:` 는 그냥 글이다)
  function loraKeywords() {
    if (!isManaged()) return null;
    return available.filter(item => item.keyword && !item.conflict)
      .map(item => ({ keyword: item.keyword, name: item.name, label: baseName(item.name), folder: folderOf(item.name) }));
  }

  function libraryHtml() {
    if (!available.length) {
      return `<div class="alr-empty">LoRA 파일이 없습니다.<br>
        <button type="button" class="alr-link" data-lora-act="folder">폴더 열기</button> 로 넣거나
        <button type="button" class="alr-link" data-lora-act="setup">API 설정 › ANIMA</button> 에서 LoRA 폴더를 추가하세요.</div>`;
    }
    const needle = filter.trim().toLowerCase();
    const shown = available.filter(item => inCategory(item) && (!needle || item.name.toLowerCase().includes(needle)
      || (item.triggers || []).some(t => String(t.word).toLowerCase().includes(needle))));
    if (!shown.length) return `<div class="alr-empty">${needle ? '찾는 LoRA 가 없습니다.' : '이 폴더에 LoRA 가 없습니다.'}</div>`;
    const full = chain.length >= MAX_CHAIN;
    return shown.map(item => {
      const at = chain.findIndex(c => c.name === item.name);
      const thumb = item.thumb && item.thumb.kind;
      const png = thumb
        ? `<img src="${esc(thumbUrl(item))}" alt="">`
        : 'PNG';
      const acts = [
        item.conflict ? '<span class="alr-badge">이름 겹침</span>'
          : at >= 0 ? `<span class="alr-inchain">체인 ${at + 1}번</span>`
            : `<button type="button" class="tagsearch-act" data-lora-addname="${esc(item.name)}"${busy || full ? ' disabled' : ''}>+ 체인</button>`,
        item.conflict ? '' : item.keyword
          ? `<button type="button" class="alr-chip alr-kw-chip" data-lora-kwedit="${esc(item.name)}"
              title="예약어 - 프롬프트에 lora:${esc(item.keyword)}:1.0 처럼 적으면 이 LoRA 가 켜집니다 · 눌러서 바꾸기">lora:${esc(item.keyword)}</button>`
          : `<button type="button" class="alr-mini" data-lora-kwedit="${esc(item.name)}"
              title="예약어를 정하면 프롬프트에 lora:예약어:1.0 처럼 적어 이 LoRA 를 켤 수 있습니다">+ 예약어</button>`,
        item.conflict ? ''
          : `<button type="button" class="alr-mini" data-lora-history="${esc(item.name)}" title="생성 히스토리에서 PNG 고르기"${
            busy ? ' disabled' : ''}>히스토리</button>`,
        item.thumb && item.thumb.kind === 'naia'
          ? `<button type="button" class="alr-mini" data-lora-thumbdel="${esc(item.name)}"${busy ? ' disabled' : ''}>PNG 지우기</button>` : '',
        `<button type="button" class="alr-mini" data-lora-reveal="${esc(item.name)}" title="이 LoRA 가 든 폴더를 엽니다">폴더</button>`,
      ].join('');
      // 그림이 있는 PNG 칸은 올리면 크게 본다 - 말풍선(title)은 그 위에 겹쳐(라이브 09-29) 안내를 크게 보기의 캡션으로 옮긴다
      // 폴더 표시 - 고른 칸과 다른 폴더(전체에서 본 하위 폴더 · 더 깊은 폴더)일 때만
      const dir = folderOf(item.name) && folderOf(item.name) !== category
        ? `<div class="alr-card-dir" title="폴더">${esc(folderOf(item.name))}</div>` : '';
      return `<div class="alr-card${at >= 0 ? ' in-chain' : ''}"${broker && !item.conflict ? ` data-lora-card="${esc(item.name)}"` : ''}>
        <button type="button" class="alr-png${thumb ? ' has-img' : ''}" data-lora-png="${esc(item.name)}"${thumb
          ? ` data-lora-zoom="${esc(thumbUrl(item))}" data-lora-zoom-title="${esc(baseName(item.name))}"
                data-lora-zoom-note="눌러서 바꾸기" aria-label="PNG 바꾸기 — 누르거나 끌어다 놓으세요"`
          : ' title="PNG 넣기 — 누르거나 끌어다 놓으세요"'}${busy ? ' disabled' : ''}>${png}</button>
        <div class="alr-card-body">
          <div class="alr-card-top"><span class="alr-card-name" title="${esc(item.name)}">${esc(baseName(item.name))}</span>
            <span class="alr-card-meta">${fmtSize(item.size)}</span></div>
          ${dir}${triggerHtml(item)}
          ${kwEdit && kwEdit.name === item.name ? kwEditHtml(item) : `<div class="alr-card-acts">${acts}</div>`}
        </div></div>`;
    }).join('');
  }

  function render(view = chain) {
    paintOutside(view);
    if (!popup) return;
    paintStatus(view);
    paintCats();
    const chainEl = pick('.alr-chain');
    const libEl = pick('.alr-lib');
    if (chainEl) {
      const focused = focusKey(chainEl);
      if (!dragging) chainEl.innerHTML = isManaged() ? chainHtml(view) : '';
      restoreFocus(chainEl, focused);
    }
    if (libEl && isManaged()) paintLib();
    else if (libEl) {
      libEl.innerHTML = `<div class="alr-empty">ANIMA 관리형 엔진이 준비되지 않았습니다.<br>
          <button type="button" class="alr-link" data-lora-act="setup">API 설정 › ANIMA</button> 에서 설치하고 고르세요.</div>`;
    }
    if (zoomTarget && !popup.contains?.(zoomTarget)) hideZoom();   // 올려 둔 칸이 다시 그려져 사라졌다
    const foot = pick('.alr-foot');
    if (foot) {
      const notes = [];
      if (isManaged() && view.length) notes.push('<div class="alr-note">위에서부터 차례로 적용합니다 · 끈 항목은 빠집니다</div>');
      warnings.forEach(w => notes.push(`<div class="alr-warn">⚠ ${esc(w.message || w)}</div>`));
      if (error) notes.push(`<div class="alr-error">${esc(error)}</div>`);
      foot.innerHTML = notes.join('');
      foot.style.display = notes.length ? '' : 'none';
    }
  }

  // ---- [히스토리] 판 · 크게 보기 ----

  function pickerHtml() {
    const rows = picker.rows;
    if (rows == null) return '<div class="alr-pick-note">불러오는 중…</div>';
    const error = picker.error ? `<div class="alr-pick-error">${esc(picker.error)}</div>` : '';
    if (!rows.length) return `${error}<div class="alr-pick-note">히스토리에 그림이 없습니다 — 생성하면 여기서 고를 수 있습니다.</div>`;
    const cell = row => `<button type="button" class="alr-pick-cell" data-lora-pickhist="${esc(row.history_id)}"
        data-lora-zoom="${esc(row.zoom_url || row.thumb_url)}"${busy ? ' disabled' : ''}><img src="${esc(row.thumb_url)}" alt=""
        loading="lazy"></button>`;
    const grid = list => `<div class="alr-pick-grid">${list.map(cell).join('')}</div>`;
    const used = rows.filter(row => row.used);
    const other = rows.filter(row => !row.used);
    if (!used.length) return error + grid(other);
    return `${error}<div class="alr-pick-label">이 LoRA 를 켜고 만든 그림</div>${grid(used)}${
      other.length ? `<div class="alr-pick-label">다른 그림</div>${grid(other)}` : ''}`;
  }

  function paintPicker() {
    const el = pick('.alr-pick');
    if (!el) return;
    if (!picker) {
      el.hidden = true;
      el.innerHTML = '';
      return;
    }
    const head = pick('.tagsearch-head');
    if (head?.offsetHeight) el.style.top = `${head.offsetHeight}px`;
    el.innerHTML = `<div class="alr-pick-head">PNG 고르기 · <b title="${esc(picker.name)}">${esc(shortName(picker.name))}</b>
        <button type="button" class="tagsearch-x" data-lora-pickclose aria-label="닫기">&times;</button></div>
      <div class="alr-pick-body">${pickerHtml()}</div>`;
    el.hidden = false;
    if (zoomTarget && !popup.contains?.(zoomTarget)) hideZoom();
  }

  async function openPicker(name) {
    hideZoom();
    const seq = ++pickerSeq;
    picker = { name, rows: null, error: '' };
    paintPicker();
    try {
      const data = await call('GET', `/loras/history?name=${encodeURIComponent(name)}`);
      if (seq !== pickerSeq || !picker) return;
      picker.rows = Array.isArray(data.candidates) ? data.candidates : [];
    } catch (err) {
      if (seq !== pickerSeq || !picker) return;
      picker.rows = [];
      picker.error = err.message;
    }
    paintPicker();
  }

  function closePicker() {
    if (!picker) return;
    picker = null;
    hideZoom();
    paintPicker();
  }

  // 고른 그림을 이 LoRA 의 PNG 로 - 서버가 히스토리 그림을 PNG(768 안쪽)로 줄여 PNG 넣기와 같은 자리에 쓴다.
  // 실패하면 판에 이유를 두고 닫지 않는다(그사이 히스토리에서 밀려난 그림이면 다른 것을 고른다).
  async function pickFromHistory(historyId) {
    if (!picker || busy) return;
    const { name } = picker;
    const seq = pickerSeq;
    busy = true;
    error = '';
    picker.error = '';
    hideZoom();
    render();
    paintPicker();
    try {
      await call('POST', '/loras/thumb/history', { name, history_id: historyId });
      busy = false;
      if (seq === pickerSeq) closePicker();
      flash('PNG 를 넣었습니다');
    } catch (err) {
      busy = false;
      if (seq === pickerSeq && picker) {
        picker.error = err.message;
        paintPicker();
      } else {
        error = err.message;
      }
    }
    await load();
  }

  function hideZoom() {
    zoomTarget = null;
    win.clearTimeout?.(zoomTimer);
    if (zoomShown) {
      zoomShown = false;
      zoom.hide?.();
    }
  }

  // PNG 칸 · 후보 칸에 올리면 창 옆에 크게(리모컨 확대 보기 그대로). 손가락은 hover 가 없다 - 누를 칸을 가린다.
  function onZoomOver(event) {
    if (event.pointerType === 'touch' || broker?.isDragging?.()) return;
    const target = event.target?.closest?.('[data-lora-zoom]') || null;
    if (target === zoomTarget) return;
    hideZoom();
    if (!target) return;
    zoomTarget = target;
    zoomTimer = win.setTimeout?.(() => {
      if (zoomTarget !== target || !popup?.contains?.(target)) return;
      zoomShown = true;
      // 그림을 받은 뒤에 그리는 것은 확대 보기(리모컨 showZoom)가 한다 - 걷으면(zoom.hide) 받는 중인 것도 버린다
      zoom.show?.(target, { src: target.getAttribute('data-lora-zoom'), title: target.getAttribute('data-lora-zoom-title') || '',
        note: target.getAttribute('data-lora-zoom-note') || '' }, popup.getBoundingClientRect());
    }, ZOOM_DELAY_MS);
  }

  function onZoomOut(event) {
    const next = event.relatedTarget;
    if (!next || !popup?.contains?.(next)) hideZoom();
  }

  // ---- 창 ----

  // Memo · Tag Search 와 같은 자리(결과 이미지 영역 좌하단) — 스테이지 안으로 실측해서 가둔다.
  function position() {
    if (!popup) return;
    const margin = 10;
    const pw = popup.offsetWidth || 700;
    const ph = popup.offsetHeight || 600;
    const host = document.getElementById('resultViewer')
      || document.getElementById('rightTabResult')
      || document.querySelector('.right-tab-pane.active');
    const rect = host ? host.getBoundingClientRect() : null;
    let left;
    let top;
    if (rect && rect.width > pw + margin * 2 && rect.height > ph + margin * 2) {
      left = rect.left + margin;
      top = rect.bottom - ph - margin;
    } else {
      left = margin;
      top = win.innerHeight - ph - margin;
    }
    left = Math.max(margin, Math.min(left, win.innerWidth - pw - margin));
    top = Math.max(margin, Math.min(top, win.innerHeight - ph - margin));
    popup.style.left = `${Math.round(left)}px`;
    popup.style.top = `${Math.round(top)}px`;
  }

  function build() {
    popup = document.createElement('div');
    // Tag Search 의 뼈대를 그대로 쓴다(Memo 와 같은 규약). anima-lora-popup 은 크기 · 칸만 손보는 갈고리다.
    popup.className = 'tagsearch-popup anima-lora-popup';
    popup.innerHTML = `
      <div class="tagsearch-head">
        <span class="tagsearch-title">LoRA · ANIMA</span>
        <span class="tagsearch-status"></span>
        <button type="button" class="tagsearch-act alr-headbtn" data-lora-act="folder" title="LoRA 폴더를 탐색기로 엽니다">폴더 열기</button>
        <button type="button" class="tagsearch-act alr-headbtn" data-lora-act="reload" title="LoRA 폴더를 다시 읽습니다">↻</button>
        <button type="button" class="tagsearch-x" data-lora-act="close" aria-label="닫기">&times;</button>
      </div>
      <div class="alr-body">
        <nav class="alr-cats" aria-label="LoRA 폴더"></nav>
        <div class="alr-main">
          <div class="alr-chainbox">
            <div class="alr-sec">적용 순서${broker ? '<span class="alr-sec-hint">카드를 끌어다 놓아 넣기 · 번호를 끌어 순서 바꾸기</span>' : ''}</div>
            <div class="alr-chain"></div>
          </div>
          <div class="tagsearch-searchrow alr-searchrow">
            <input class="tagsearch-input" type="search" data-lora-filter autocomplete="off" spellcheck="false"
                   placeholder="LoRA 찾기 (이름 · 트리거 워드)">
          </div>
          <div class="alr-lib"></div>
        </div>
      </div>
      <div class="alr-foot"></div>
      <div class="alr-pick" role="dialog" aria-label="히스토리에서 PNG 고르기" hidden></div>
      <input type="file" accept="image/png" data-lora-file hidden>
    `;
    document.body.appendChild(popup);
    listen(popup);
    popup.addEventListener('pointerdown', onArm);
    popup.addEventListener('dragover', onDragOver);
    popup.addEventListener('dragleave', onDragLeave);
    popup.addEventListener('drop', onDrop);
    popup.addEventListener('pointerover', onZoomOver);
    popup.addEventListener('pointerout', onZoomOut);
    popup.addEventListener('keydown', event => {
      // 예약어 칸 - Enter = 저장, Esc = 그 칸만 그만둔다(창은 그대로)
      const kwInput = event.target?.closest?.('[data-lora-kwinput]');
      if (kwInput && (event.key === 'Enter' || event.key === 'Escape')) {
        event.preventDefault();
        event.stopPropagation?.();
        if (event.isComposing) return;           // 한글 조합 중의 Enter 는 글자를 마치는 것이다
        if (event.key === 'Enter') saveKeyword(kwInput.getAttribute('data-lora-kwinput'), kwInput.value);
        else cancelKwEdit();
        return;
      }
      // Esc 는 [히스토리] 판부터 닫는다 - 창까지 한 번에 닫히면 고르던 자리를 잃는다
      if (event.key === 'Escape') { event.preventDefault(); if (picker) closePicker(); else close(); }
    });
    wireDrop();
  }

  // 창과 LoRA 줄이 같은 조작을 듣는다(켜기 · 강도 · 편집)
  function listen(el) {
    el.addEventListener('click', onClick);
    el.addEventListener('change', onChange);
    el.addEventListener('input', onInput);
    el.addEventListener('dblclick', onDblClick);
    el.addEventListener('wheel', onWheel, { passive: false });
    el.addEventListener('pointerdown', event => {
      if (event.target?.closest?.('[data-lora-slider]')) { dragging = true; dragPointer = event.pointerId ?? null; }
    });
    el.addEventListener('pointerup', endDrag);
    el.addEventListener('pointercancel', endDrag);
    if (!windowRelease) {
      windowRelease = true;
      win.addEventListener?.('pointerup', endDrag, true);
      win.addEventListener?.('pointercancel', endDrag, true);
      // 놓은 것이 아예 안 왔다(브라우저 밖에서 놓았다 등) - 끌던 포인터가 눌린 버튼 없이 움직이면 끌기는 끝났다(Codex 확인
      // 리뷰 09-29: 그대로면 휠 저장이 무기한 미뤄졌다). blur 로는 끊지 않는다 - 창을 잠깐 떠났다 와도 누른 채면 이어진다.
      win.addEventListener?.('pointermove', event => { if (dragging && event.buttons === 0) endDrag(event); }, true);
    }
  }

  // 끌기가 끝났다. 다른 포인터의 놓기 · 움직임이면 무시한다 - 마우스로 끄는 중에 펜이 지나가면(hover) 끝난 줄 알고 휠 값을
  // 보내, 놓은 값이 저장 중이라 버려졌다(Codex 확인 리뷰 09-29). pointerId 가 없는 이벤트는 끝으로 본다.
  function endDrag(event) {
    if (event && dragPointer != null && event.pointerId != null && event.pointerId !== dragPointer) return;
    dragging = false;
    dragPointer = null;
  }

  function isOpen() {
    return Boolean(popup) && popup.style.display !== 'none';
  }

  function open() {
    if (!popup) build();
    popup.style.display = 'flex';
    render();
    onResize = () => position();
    win.addEventListener('resize', onResize);
    position();
    win.requestAnimationFrame?.(() => position());
    onStateChange();
    // 목록은 열 때마다 다시 받는다 — 다른 기기에서 바꿨거나 폴더에 파일을 넣었을 수 있다.
    if (isManaged()) load();
    else refresh();
  }

  function close() {
    if (!isOpen()) return;
    closePicker();
    hideZoom();
    if (onResize) { win.removeEventListener('resize', onResize); onResize = null; }
    popup.style.display = 'none';
    onStateChange();
  }

  function toggle() {
    if (isOpen()) close();
    else open();
  }

  // ---- 조작 ----

  function move(index, delta) {
    const next = chain.slice();
    const to = index + delta;
    if (to < 0 || to >= next.length) return null;
    [next[index], next[to]] = [next[to], next[index]];
    return next;
  }

  function onClick(event) {
    const act = event.target.closest('[data-lora-act]');
    if (act) {
      const which = act.getAttribute('data-lora-act');
      if (which === 'close') close();
      else if (which === 'open') open();
      else if (which === 'fold') { dockFolded = !dockFolded; saveDockFold(); paintDock(); }
      else if (which === 'setup') onOpenSetup();
      else if (which === 'folder') openFolder('');
      else if (which === 'reload' && !busy) { error = ''; refresh(); }
      return;
    }
    const copy = event.target.closest('[data-lora-copy]');
    if (copy) {
      const word = copy.getAttribute('data-lora-copy');
      Promise.resolve(win.navigator?.clipboard?.writeText(word))
        .then(() => flash(`복사했습니다: ${word}`))
        .catch(() => { error = '복사하지 못했습니다'; render(); });
      return;
    }
    const reveal = event.target.closest('[data-lora-reveal]');
    if (reveal) { openFolder(reveal.getAttribute('data-lora-reveal')); return; }
    if (event.target.closest('[data-lora-pickclose]')) { closePicker(); return; }
    const kwEditBtn = event.target.closest('[data-lora-kwedit]');
    if (kwEditBtn) { startKwEdit(kwEditBtn.getAttribute('data-lora-kwedit')); return; }
    const kwSave = event.target.closest('[data-lora-kwsave]');
    if (kwSave) {
      const name = kwSave.getAttribute('data-lora-kwsave');
      saveKeyword(name, kwEdit && kwEdit.name === name ? kwEdit.value : '');
      return;
    }
    const kwClear = event.target.closest('[data-lora-kwclear]');
    if (kwClear) { saveKeyword(kwClear.getAttribute('data-lora-kwclear'), ''); return; }
    if (event.target.closest('[data-lora-kwcancel]')) { cancelKwEdit(); return; }
    const cat = event.target.closest('[data-lora-cat]');
    if (cat) {
      if (kwEdit && !kwEdit.saving) kwEdit = null;   // 다른 칸으로 가면 고치던 예약어는 그만둔다
      category = cat.getAttribute('data-lora-cat') || ALL;
      hideZoom();
      paintCats();
      const libEl = pick('.alr-lib');
      if (libEl && isManaged()) { libEl.innerHTML = libraryHtml(); libEl.scrollTop = 0; }
      return;
    }
    if (busy) return;
    const history = event.target.closest('[data-lora-history]');
    if (history) { openPicker(history.getAttribute('data-lora-history')); return; }
    const picked = event.target.closest('[data-lora-pickhist]');
    if (picked) { pickFromHistory(picked.getAttribute('data-lora-pickhist')); return; }
    const png = event.target.closest('[data-lora-png]');
    if (png) {
      pngTarget = png.getAttribute('data-lora-png');
      const input = pick('[data-lora-file]');
      if (input) { input.value = ''; input.click(); }
      return;
    }
    const thumbDel = event.target.closest('[data-lora-thumbdel]');
    if (thumbDel) { deleteThumb(thumbDel.getAttribute('data-lora-thumbdel')); return; }
    const addName = event.target.closest('[data-lora-addname]');
    if (addName) {
      if (chain.length >= MAX_CHAIN) return;
      save([...chain, { name: addName.getAttribute('data-lora-addname'), strength: 1, enabled: true }]);
      return;
    }
    const up = event.target.closest('[data-lora-up]');
    const down = event.target.closest('[data-lora-down]');
    const rm = event.target.closest('[data-lora-rm]');
    let next = null;
    if (up) next = move(Number(up.getAttribute('data-lora-up')), -1);
    else if (down) next = move(Number(down.getAttribute('data-lora-down')), 1);
    else if (rm) {
      next = chain.slice();
      next.splice(Number(rm.getAttribute('data-lora-rm')), 1);
    }
    if (next) save(next);
  }

  function onChange(event) {
    const fileInput = event.target.closest('[data-lora-file]');
    if (fileInput) {
      const file = fileInput.files && fileInput.files[0];
      uploadThumb(pngTarget, file);
      return;
    }
    if (busy) return;
    const toggleBox = event.target.closest('[data-lora-on]');
    if (toggleBox) {
      const index = Number(toggleBox.getAttribute('data-lora-on'));
      save(chain.map((item, i) => (i === index ? { ...item, enabled: toggleBox.checked } : item)));
      return;
    }
    const slider = event.target.closest('[data-lora-slider]');
    if (slider) {                  // 놓았다 - 한 번 저장한다
      endDrag();
      setStrength(Number(slider.getAttribute('data-lora-slider')), Number(slider.value));
      return;
    }
    const weight = event.target.closest('[data-lora-w]');
    if (weight) setStrength(Number(weight.getAttribute('data-lora-w')), Number(weight.value));
  }

  function setStrength(index, value) {
    if (!chain[index]) return;
    const dropped = wheelEdits.delete(chain[index].name);   // 손으로 정한 값이 앞서 휠로 돌려 둔 값보다 나중이다
    if (!Number.isFinite(value) || value < STRENGTH_MIN || value > STRENGTH_MAX) {
      error = `강도는 ${STRENGTH_MIN} ~ ${STRENGTH_MAX} 사이로 적어 주세요.`;
      render();                    // 틀린 값은 저장하지 않고 원래 값으로 되돌린다(조용히 자르지 않는다)
      return;
    }
    const next = Math.round(value * 100) / 100;
    if (Number(chain[index].strength) === next) {
      // 저장된 값 그대로다(휠로 1.05 를 돌려 둔 뒤 더블클릭 1.00 등). 칸 · 슬라이더에는 버린 휠 값이 남아 있다 - 저장된
      // 값으로 다시 그린다. 안 그러면 다음 휠이 남은 값에서 이어 1.10 을 저장했다(Codex 재리뷰 09-29).
      if (dropped) render();
      return;
    }
    save(chain.map((item, i) => (i === index ? { ...item, strength: next } : item)));
  }

  // 슬라이더와 칸을 함께 맞춘다(저장 없이) - 끄는 동안 · 휠을 돌리는 동안
  function showStrength(control, value) {
    const box = control.parentElement?.querySelector?.('[data-lora-w]');
    const bar = control.parentElement?.querySelector?.('[data-lora-slider]');
    if (box) box.value = fmtStrength(value);
    if (bar) bar.value = String(Math.min(SLIDER_MAX, Math.max(0, value)));
  }

  function onDblClick(event) {
    const slider = event.target.closest('[data-lora-slider]');
    if (!slider || busy) return;
    event.preventDefault?.();
    endDrag();
    setStrength(Number(slider.getAttribute('data-lora-slider')), 1);
  }

  function onWheel(event) {
    const control = event.target.closest('[data-lora-slider], [data-lora-w]');
    if (!control || busy || control.disabled) return;
    const index = Number(control.getAttribute('data-lora-slider') ?? control.getAttribute('data-lora-w'));
    const item = chain[index];
    if (!item) return;
    event.preventDefault?.();      // 휠이 강도 위에 있으면 목록 · 입력칸을 굴리지 않는다
    const shown = wheelEdits.has(item.name) ? wheelEdits.get(item.name)
      : Number(control.parentElement?.querySelector?.('[data-lora-w]')?.value ?? item.strength);
    const delta = (event.shiftKey ? 0.25 : STEP) * (event.deltaY < 0 ? 1 : -1);
    const value = Math.min(STRENGTH_MAX, Math.max(STRENGTH_MIN, Math.round(((Number.isFinite(shown) ? shown : 1) + delta) * 100) / 100));
    showStrength(control, value);
    wheelEdits.set(item.name, value);
    win.clearTimeout?.(wheelTimer);
    wheelTimer = win.setTimeout?.(flushWheel, WHEEL_SAVE_MS);
  }

  // 휠이 멈췄다 - 모아 둔 강도를 한 번에 저장한다(여러 LoRA 를 돌렸어도 하나도 버리지 않는다). 다른 저장이 도는
  // 중이면 그게 끝난 뒤에 - 겹쳐 보내면 먼저 떠난 옛 목록이 뒤에 도착해 이긴다. 슬라이더를 끄는 중이어도 뒤로 -
  // 그사이 저장이 돌면 놓을 때의 값(change)이 저장 중이라 버려졌다(Codex 재리뷰 09-29). 놓으면 그 저장에 실려 간다.
  function flushWheel() {
    if (!wheelEdits.size) return;
    if (busy || dragging) { wheelTimer = win.setTimeout?.(flushWheel, WHEEL_SAVE_MS); return; }
    if (chain.every(item => !wheelEdits.has(item.name) || Number(item.strength) === wheelEdits.get(item.name))) {
      wheelEdits.clear();
      return;
    }
    save(chain.slice());
  }

  function onInput(event) {
    const slider = event.target.closest('[data-lora-slider]');
    if (slider) {                  // 끄는 동안 칸만 따라 바꾼다 - 저장은 놓을 때(change)
      dragging = true;
      showStrength(slider, Number(slider.value));
      return;
    }
    const kwInput = event.target.closest('[data-lora-kwinput]');
    if (kwInput) {
      if (kwEdit && kwEdit.name === kwInput.getAttribute('data-lora-kwinput')) kwEdit.value = kwInput.value;
      return;
    }
    const box = event.target.closest('[data-lora-filter]');
    if (!box) return;
    filter = box.value;
    const libEl = pick('.alr-lib');
    if (libEl && isManaged()) libEl.innerHTML = libraryHtml();   // 목록만 다시 — 찾기 칸 글자는 그대로
  }

  // PNG 칸에 끌어다 놓기
  function onDragOver(event) {
    const slot = event.target.closest?.('[data-lora-png]');
    if (!slot || busy) return;
    event.preventDefault();
    slot.classList?.add('drop');
  }

  function onDragLeave(event) {
    event.target.closest?.('[data-lora-png]')?.classList?.remove('drop');
  }

  function onDrop(event) {
    const slot = event.target.closest?.('[data-lora-png]');
    if (!slot) return;
    event.preventDefault();
    slot.classList?.remove('drop');
    if (busy) return;
    const file = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
    uploadThumb(slot.getAttribute('data-lora-png'), file);
  }

  // ---- 끌어다 놓기(dragBroker - Artist Thumbnail 의 격자 -> 믹스 큐 · 그룹 창과 같은 길) ----

  function chainRows() {
    const el = pick('.alr-chain');
    return el?.querySelectorAll ? [...el.querySelectorAll('.alr-item')] : [];
  }

  // 포인터 높이 -> 몇 번째 앞에 넣을지(줄의 가운데를 넘으면 그 뒤). 머리줄 위면 맨 앞 - 체인 본문보다 위면 줄을 세지
  // 않는다: 체인을 굴려 두면 가려진 위쪽 줄의 가운데도 머리줄보다 위라 세어져 중간에 들어갔다(Codex 리뷰 F7).
  function dropIndex(point) {
    const top = pick('.alr-chain')?.getBoundingClientRect?.().top;
    if (Number.isFinite(top) && point.y < top) return 0;
    const rows = chainRows();
    for (let i = 0; i < rows.length; i += 1) {
      const r = rows[i].getBoundingClientRect();
      if (point.y < r.top + r.height / 2) return i;
    }
    return rows.length;
  }

  function paintDropMark(index) {
    const rows = chainRows();
    rows.forEach((row, i) => {
      row.classList.toggle('drop-before', i === index);
      row.classList.toggle('drop-after', index === rows.length && i === rows.length - 1);
    });
  }

  // 놓았다 - 이미 체인에 있으면 그 자리로 옮기고(카드에서 끌었든 체인 줄을 끌었든 같다), 없으면 그 자리에 넣는다
  // (강도 1 · 켜짐 - [+ 체인] 과 같다). 저장은 늘 쓰던 save 하나 - 휠로 돌려 둔 강도도 이름으로 함께 실린다.
  function dropOnChain(payload, at) {
    if (busy || !isManaged()) return false;
    const name = payload?.name;
    const from = chain.findIndex(item => item.name === name);
    const next = chain.slice();
    if (from >= 0) {
      const to = at > from ? at - 1 : at;
      if (to === from) return true;           // 제자리
      next.splice(to, 0, ...next.splice(from, 1));
    } else {
      const meta = available.find(item => item.name === name);
      if (!meta || meta.conflict) return false;
      if (chain.length >= MAX_CHAIN) {
        error = `체인에는 ${MAX_CHAIN}개까지 넣을 수 있습니다.`;
        render();
        return false;
      }
      next.splice(Math.min(Math.max(0, at), next.length), 0, { name, strength: 1, enabled: true });
    }
    save(next);
    return true;
  }

  // 적용 순서(머리줄 포함)를 받는 쪽으로 한 번 올린다. 줄은 다시 그려져도 상자는 그대로라 등록도 그대로다.
  function wireDrop() {
    if (!broker || chainZone) return;
    const box = pick('.alr-chainbox');
    if (!box) return;
    chainZone = broker.registerZone(box, {
      kind: 'anima-lora',
      canAccept: payload => payload?.kind === 'anima-lora' && Boolean(payload.name) && isManaged() && !busy,
      hover: (payload, point) => paintDropMark(dropIndex(point)),
      accept: (payload, point) => dropOnChain(payload, dropIndex(point)),
    });
    broker.subscribe?.(state => { if (state === 'end') paintDropMark(-1); });
  }

  // 끌기의 시작점 - 카드는 어디서든(누르기만 하면 늘 하던 단추 · PNG 칸이다), 체인 줄은 번호 · 이름에서만(체크 · 강도 ·
  // 순서 단추는 제 일을 한다). 문턱(4px)을 넘기 전에는 아무 일도 없다 - 누름은 그대로 클릭이다(중개자 규약).
  function onArm(event) {
    if (!broker || busy || !isManaged() || picker || event.button !== 0) return;
    if (event.target?.closest?.('input, textarea, select')) return;
    const card = event.target?.closest?.('[data-lora-card]');
    let name = card ? card.getAttribute('data-lora-card') : '';
    if (!card) {
      const row = event.target?.closest?.('.alr-idx, .alr-name')?.closest?.('[data-lora-row]');
      name = row ? chain[Number(row.getAttribute('data-lora-row'))]?.name || '' : '';
    }
    if (!name) return;
    const meta = available.find(item => item.name === name);
    broker.arm(event, {
      kind: 'anima-lora', name, label: baseName(name),
      image: meta?.thumb?.kind ? thumbUrl(meta) : '',
    }, { onStart: () => hideZoom() });
  }

  function init() {
    ensureStyle();
  }

  return { init, setMode, refresh, isManaged, open, close, toggle, isOpen, paintBadge, loraKeywords };
}
