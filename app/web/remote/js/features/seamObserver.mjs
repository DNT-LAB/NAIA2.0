/* ============================================================
   SEAM observer (frontend) — 관측 전용 포커스-드롭 탐지기.

   두 backbone 중 **module 렌더 디스패치(app.js onModuleState)** 를 계측한다.
   재렌더 직전 포커스된 입력을 스냅샷하고, 렌더 직후(다음 animation frame) 그 입력이
   여전히 DOM 에 살아있고 포커스인지 검사한다. 사라졌으면 "어느 모듈 렌더가 #입력의
   포커스를 떨궜나" 를 기록한다.

   설계 원칙 (절대 시스템을 깨지 않는다):
     - 절대 throw 안 함 / DOM 안 건드림 / 제어 흐름 안 바꿈 (순수 관측).
     - app.js 가 ?seam=1 (또는 localStorage.naia_seam='1') 일 때만 동적 import → 끄면 로드조차 안 됨.

   누적 방지: 디스크 기록 없음. 메모리 링버퍼(최근 200)뿐이라 reload 시 비워진다.

   판독 (에이전트/개발자):
     window.__naiaSeamLog       — focus_lost 레코드 배열(최근 200)
     window.__naiaSeamManifest  — { moduleId: [소유 입력 키...] }  (= "각 모듈이 가진 하위 입력 자산")
     console.warn('[SEAM] focus_lost', ...)
   ============================================================ */

const LOG_MAX = 200;
const log = [];
const manifest = {};   // moduleId -> [inputKey...]  (read-only 인벤토리)
let _on = false;

function inputKey(el) {
  if (!el) return '?';
  if (el.id) return '#' + el.id;
  if (el.name) return `[name=${el.name}]`;
  const cls = String(el.className || '').trim().split(/\s+/).filter(Boolean).slice(0, 2).join('.');
  return el.tagName.toLowerCase() + (cls ? '.' + cls : '');
}

function isEditable(el) {
  if (!el) return false;
  const tag = el.tagName;
  if (tag === 'TEXTAREA') return true;
  if (el.isContentEditable) return true;
  if (tag === 'INPUT') {
    return !/^(button|checkbox|radio|submit|range|file|color|image|reset)$/i.test(el.type || 'text');
  }
  return false;
}

function capture() {
  const el = document.activeElement;
  if (!isEditable(el)) return null;
  let selStart = null, selEnd = null;
  try { selStart = el.selectionStart; selEnd = el.selectionEnd; } catch (_) { /* type 미지원 */ }
  return { el, key: inputKey(el), selStart, selEnd, scrollTop: el.scrollTop, scrollLeft: el.scrollLeft };
}

function record(rec) {
  rec.ts = Date.now();
  log.push(rec);
  if (log.length > LOG_MAX) log.shift();
  try { console.warn('[SEAM] ' + rec.event, rec); } catch (_) { /* noop */ }
}

export const seamObserver = {
  get enabled() { return _on; },

  init() {
    _on = true;
    window.__naiaSeamLog = log;
    window.__naiaSeamManifest = manifest;
    try {
      console.info('[SEAM] focus-drop observer ON — read window.__naiaSeamLog / window.__naiaSeamManifest');
    } catch (_) { /* noop */ }
  },

  /* onModuleState 진입부에서 1줄 호출. label=어느 디스패치, moduleId=무슨 모듈 상태인지. */
  watch(label, moduleId) {
    if (!_on) return;
    const snap = capture();
    if (!snap) return;

    // 모듈 → 소유 입력 manifest 갱신 (read-only 인벤토리)
    if (moduleId) {
      const owned = (manifest[moduleId] = manifest[moduleId] || []);
      if (!owned.includes(snap.key)) owned.push(snap.key);
    }

    // 동기 렌더가 끝난 뒤 검사
    requestAnimationFrame(() => {
      try {
        const replaced = !snap.el.isConnected;
        const lost = replaced || document.activeElement !== snap.el;
        if (!lost) return;
        record({
          event: 'focus_lost',
          bus: 'module_render',
          via: label,
          module: moduleId || null,
          input: snap.key,
          cause: replaced ? 'node-replaced' : 'blurred',
        });
      } catch (_) { /* noop */ }
    });
  },
};
