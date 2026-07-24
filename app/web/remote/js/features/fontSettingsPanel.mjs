// Settings > Global > 폰트
//
// 프롬프트/네거티브를 포함한 자유 텍스트 입력창의 폰트(--font-editor)를 고른다.
// 폰트 선택은 기기별 취향이라 localStorage 에 남고, 업로드한 폰트 파일 자체는
// 백엔드(ui_assets/fonts)에 저장돼 다른 접속 기기에서도 목록에 나타난다.
//
// 적용 결과가 첫 페인트 전에 필요하므로(FOUC 방지) 선택 항목은 "적용에 필요한
// 전부"(폰트 스택 + @font-face 규칙)를 통째로 직렬화해 둔다. index.html 의 인라인
// 부트 스크립트가 이 값만 읽고 동기적으로 복원한다. 아래 STORAGE_KEY / FACE_STYLE_ID /
// 페이로드 모양을 바꾸면 index.html 부트 스크립트도 같이 고쳐야 한다.

export const STORAGE_KEY = 'naia_font_editor';
export const FACE_STYLE_ID = 'naiaFontEditorFace';

const CUSTOM_FACE_STYLE_ID = 'naiaFontCustomFaces';
const SCALED_FAMILY = 'naia-editor-scaled';
// 선택 폰트에 글리프가 없을 때(한글 등) 떨어질 곳. 항상 뒤에 붙인다.
const FALLBACK_STACK = '"Malgun Gothic", "Apple SD Gothic Neo", sans-serif';

const MIN_SCALE = 85;
const MAX_SCALE = 130;

const PREVIEW_TEXT = [
  '1girl, masterpiece, best quality, {artist:ixy}, 1.2::detailed eyes::',
  '다람쥐 헌 쳇바퀴에 타고파 — 0O1lI, {}[]()<>',
].join('\n');

// queryLocalFonts() 를 못 쓰는 환경(모바일 브라우저 등)에서 폭 측정으로 탐지할 후보.
// 설치돼 있는 것만 목록에 남는다.
const FONT_CANDIDATES = [
  'Pretendard', 'Pretendard Variable', 'Pretendard JP',
  'Malgun Gothic', '맑은 고딕',
  'Apple SD Gothic Neo', 'AppleGothic',
  'Noto Sans KR', 'Noto Sans CJK KR', 'Noto Serif KR',
  'Nanum Gothic', '나눔고딕', 'NanumBarunGothic', 'NanumSquare', 'NanumSquareRound',
  'Spoqa Han Sans Neo', 'IBM Plex Sans KR', 'Gothic A1', 'SUIT', 'S-Core Dream',
  'KoPubWorld Dotum', 'KoPubWorld Batang',
  'Gulim', '굴림', 'Dotum', '돋움', 'Batang', '바탕',
  'D2Coding', 'D2Coding ligature',
  'JetBrains Mono', 'Cascadia Code', 'Cascadia Mono', 'Consolas',
  'Fira Code', 'Source Code Pro', 'IBM Plex Mono', 'SF Mono', 'Menlo', 'Monaco',
  'Segoe UI', 'Inter', 'Roboto', 'Outfit', 'Arial', 'Helvetica Neue', 'Georgia',
];

const FORMAT_BY_SUFFIX = {
  otf: 'opentype',
  ttf: 'truetype',
  ttc: 'collection',
  woff: 'woff',
  woff2: 'woff2',
};

function cssQuote(value) {
  return `"${String(value ?? '').replace(/["\\]/g, '\\$&')}"`;
}

function formatForUrl(url) {
  // 서버가 캐시 무효화를 위해 `?v=<mtime>` 를 붙이므로 쿼리/프래그먼트를 먼저 떼어낸다.
  // 안 떼면 확장자가 "otf?v=1a2b" 가 돼 format() 이 항상 기본값으로 떨어진다.
  const path = String(url || '').split(/[?#]/)[0];
  const suffix = path.split('.').pop().toLowerCase();
  return FORMAT_BY_SUFFIX[suffix] || 'opentype';
}

function humanSize(bytes) {
  const value = Number(bytes) || 0;
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)}MB`;
  if (value >= 1024) return `${Math.round(value / 1024)}KB`;
  return `${value}B`;
}

/** 시스템 폰트를 `local()` 로 참조할 후보 이름들.
 *
 *  `local()` 은 **PostScript 명 / 전체 이름**으로 매칭되고 패밀리명으로는 매칭되지 않는다.
 *  실측: `local("Pretendard")` = 로드 실패(스케일 미적용), `local("Pretendard-Regular")` = 성공.
 *  fullName 이 family 와 같은 폰트(Malgun Gothic 등)도 있어서 family 자체도 후보에 남긴다.
 *  src 는 쉼표 목록을 앞에서부터 시도하므로, 아는 이름을 앞에 두고 추측을 뒤에 붙인다. */
export function localSrcCandidates(family, postscript = '', fullName = '') {
  const compact = String(family || '').replace(/\s+/g, '');
  const names = [postscript, fullName, family, `${family} Regular`,
                 `${compact}-Regular`, `${compact}Regular`];
  const seen = new Set();
  return names
    .map(name => String(name || '').trim())
    .filter(name => name && !seen.has(name) && seen.add(name))
    .map(name => `local(${cssQuote(name)})`)
    .join(', ');
}

/** 저장된 선택으로부터 실제 적용값(스택 + @font-face)을 만든다.
 *  부트 스크립트와 동작이 갈리면 안 되므로 이 함수 하나만 진실의 원천으로 둔다. */
export function buildSelection({kind = 'default', family = '', url = '', label = '', scale = 100,
                                postscript = '', fullName = ''} = {}) {
  const safeScale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, Math.round(Number(scale) || 100)));
  if (kind === 'default' || (!family && !url)) {
    return {kind: 'default', family: '', url: '', label: '기본 (JetBrains Mono)', scale: 100, stack: '', face: ''};
  }

  if (kind === 'custom' && url) {
    // 업로드 폰트는 어차피 @font-face 가 필요하므로 size-adjust 를 여기에 얹는다.
    const adjust = safeScale === 100 ? '' : `size-adjust:${safeScale}%;`;
    const face = `@font-face{font-family:${cssQuote(family)};`
      + `src:url(${cssQuote(url)}) format(${cssQuote(formatForUrl(url))});`
      + `font-display:swap;${adjust}}`;
    return {
      kind: 'custom', family, url, label: label || family, scale: safeScale,
      stack: `${cssQuote(family)}, ${FALLBACK_STACK}`,
      face,
    };
  }

  // 시스템 폰트. 100% 일 때는 @font-face 없이 곧바로 쓴다(local() 매칭 실패 위험 회피).
  if (safeScale === 100) {
    return {
      kind: 'system', family, url: '', label: label || family, scale: 100,
      postscript, fullName,
      stack: `${cssQuote(family)}, ${FALLBACK_STACK}`,
      face: '',
    };
  }
  // 크기를 조정할 때만 local() 기반 합성 페이스를 앞에 세운다.
  // 후보 중 하나라도 맞으면 스케일이 걸리고, 전부 실패해도 뒤의 실제 패밀리가
  // 받아주므로 글자가 사라지지는 않는다(대신 스케일만 무시된다 → 패널이 안내).
  const face = `@font-face{font-family:${cssQuote(SCALED_FAMILY)};`
    + `src:${localSrcCandidates(family, postscript, fullName)};`
    + `font-display:swap;size-adjust:${safeScale}%;}`;
  return {
    kind: 'system', family, url: '', label: label || family, scale: safeScale,
    postscript, fullName,
    stack: `${cssQuote(SCALED_FAMILY)}, ${cssQuote(family)}, ${FALLBACK_STACK}`,
    face,
  };
}

/** 저장된 선택을 문서에 적용한다. 설정 UI 가 없는 문서(분리된 모듈 창 등)도
 *  이 경로만으로 폰트를 따라가야 하므로 패널과 분리해 둔다. */
export function applyStoredFont(document, localStorage) {
  let selection;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    selection = raw ? buildSelection(JSON.parse(raw)) : buildSelection({kind: 'default'});
  } catch (error) {
    selection = buildSelection({kind: 'default'});
  }
  let tag = document.getElementById(FACE_STYLE_ID);
  if (!tag) {
    tag = document.createElement('style');
    tag.id = FACE_STYLE_ID;
    document.head.appendChild(tag);
  }
  tag.textContent = selection.face || '';
  setFontVars(document.documentElement, selection.stack);
  return selection;
}

/** 폰트 변수 두 개를 함께 세팅한다.
 *  --font-editor          : 원래 --font-mono 였던 입력창
 *  --font-editor-inherit  : 원래 본문 폰트를 상속하던 입력창(Grok/Director)
 *  후자는 미설정 시 inherit 로 남아야 기존 화면이 그대로다. */
export function setFontVars(rootEl, stack) {
  if (stack) {
    rootEl.style.setProperty('--font-editor', stack);
    rootEl.style.setProperty('--font-editor-inherit', stack);
  } else {
    rootEl.style.removeProperty('--font-editor');
    rootEl.style.removeProperty('--font-editor-inherit');
  }
}

export function createFontSettingsPanel({
  document,
  fetch: fetchFn = window.fetch.bind(window),
  localStorage = window.localStorage,
  showToast = () => {},
  escHtml = value => String(value ?? ''),
  confirmDialog = null,
} = {}) {
  const win = document.defaultView || window;
  const root = document.getElementById('fontSettings');

  // 분리된 모듈 창은 같은 origin 의 별도 document 라 localStorage 를 공유한다.
  // 이미 열려 있는 창이 폰트 변경을 따라가려면 storage 이벤트를 들어야 한다
  // (부트 스크립트는 로드 시점만 처리하므로 그것만으로는 stale 이 남는다).
  win.addEventListener('storage', event => {
    if (event.key !== null && event.key !== STORAGE_KEY) return;
    applyStoredFont(document, localStorage);
    if (root) {
      selection = readSelection();
      render();
    }
  });

  if (!root) {
    // 설정 UI 가 없는 문서: 적용과 동기화만 담당한다.
    return {
      init() { applyStoredFont(document, localStorage); },
      refresh() {},
    };
  }
  let customFonts = [];
  let systemFonts = [];
  let systemLoaded = false;
  let addOpen = false;
  let filterText = '';
  let listGeneration = 0;   // /api/fonts 조회 경합 판별용(늦게 온 옛 응답 무시)
  let selection = readSelection();

  // ---- 저장/적용 ----

  function readSelection() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return buildSelection({kind: 'default'});
      const parsed = JSON.parse(raw);
      return buildSelection(parsed);
    } catch (error) {
      return buildSelection({kind: 'default'});
    }
  }

  function styleTag(id) {
    let tag = document.getElementById(id);
    if (!tag) {
      tag = document.createElement('style');
      tag.id = id;
      document.head.appendChild(tag);
    }
    return tag;
  }

  function applySelection(next) {
    selection = next;
    styleTag(FACE_STYLE_ID).textContent = next.face || '';
    setFontVars(document.documentElement, next.stack);
    try {
      if (next.kind === 'default') localStorage.removeItem(STORAGE_KEY);
      else {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({
          kind: next.kind, family: next.family, url: next.url,
          label: next.label, scale: next.scale,
          postscript: next.postscript || '', fullName: next.fullName || '',
          stack: next.stack, face: next.face,
        }));
      }
    } catch (error) { /* 저장 실패는 비치명 - 이번 세션에만 적용된다 */ }
  }

  function select(patch) {
    applySelection(buildSelection({...selectionSeed(), ...patch}));
    render();
    verifyScaleApplied();
  }

  let scaleWarnedFor = '';
  /** 시스템 폰트의 크기 보정은 `local()` 로 그 폰트를 다시 잡아야 성립한다.
   *  이름 후보가 전부 빗나가면 스케일만 조용히 무시되므로(글자는 정상 표시)
   *  사용자가 "슬라이더가 안 먹는다"고 느낀다. 실제 로드 여부를 확인해 알린다. */
  function verifyScaleApplied() {
    if (selection.kind !== 'system' || selection.scale === 100) return;
    const key = `${selection.family}@${selection.scale}`;
    if (scaleWarnedFor === key) return;
    const check = () => {
      let loaded = false;
      try { loaded = document.fonts.check(`12px "${SCALED_FAMILY}"`); } catch (error) { loaded = true; }
      if (loaded) { scaleWarnedFor = ''; return; }
      scaleWarnedFor = key;
      showToast(`'${selection.family}' 은(는) 크기 보정을 적용할 수 없습니다. `
        + '폰트 파일을 직접 추가하면 크기 보정이 동작합니다.', 'error');
    };
    if (document.fonts?.ready?.then) document.fonts.ready.then(check).catch(() => {});
    else check();
  }

  function selectionSeed() {
    // postscript/fullName 도 반드시 실어야 한다 - 빠지면 크기 보정 시
    // local() 후보가 패밀리명 추측으로만 만들어져 스케일이 안 먹을 수 있다.
    return {kind: selection.kind, family: selection.family, url: selection.url,
            label: selection.label, scale: selection.scale,
            postscript: selection.postscript || '', fullName: selection.fullName || ''};
  }

  // 목록의 각 행을 해당 폰트로 렌더하기 위한 미리보기 전용 페이스.
  // 선택된 폰트와 반드시 다른 패밀리명을 써야 한다 - 같은 이름으로 다시 선언하면
  // size-adjust 가 붙은 선택 페이스를 나중에 선언된 이쪽이 덮어써서 크기 보정이 먹지 않는다.
  function previewFamilyOf(font) {
    return `naia-fontpreview-${font.id}`;
  }

  function refreshCustomFaces() {
    const css = customFonts
      .map(font => `@font-face{font-family:${cssQuote(previewFamilyOf(font))};`
        + `src:url(${cssQuote(font.url)}) format(${cssQuote(formatForUrl(font.url))});font-display:swap;}`)
      .join('\n');
    styleTag(CUSTOM_FACE_STYLE_ID).textContent = css;
  }

  // ---- 폰트 목록 ----

  async function loadCustomFonts() {
    try {
      // 초기화 / 패널 열기 / 업로드 / 삭제가 각각 독립적으로 조회를 시작한다.
      // 세대 번호가 없으면 **오래된 응답이 마지막에 도착**했을 때 방금 업로드해
      // 선택한 폰트를 "목록에 없음 = 삭제됨"으로 오판해 기본값으로 되돌린다.
      const generation = ++listGeneration;
      const response = await fetchFn('/api/fonts');
      if (!response.ok) return false;
      const data = await response.json();
      if (generation !== listGeneration) return false;  // 더 최신 조회가 이미 반영됨
      customFonts = Array.isArray(data?.fonts) ? data.fonts : [];
      refreshCustomFaces();
      return reconcileSelection();
    } catch (error) {
      // 네트워크 오류로 목록을 못 받은 것을 "폰트가 삭제됐다"로 오해하면 안 된다.
      // 기존 선택과 customFonts 를 그대로 두고 다음 기회에 다시 맞춘다.
      return false;
    }
  }

  /** 서버 목록과 저장된 선택을 맞춘다.
   *  - 다른 기기에서 지운 폰트를 계속 선택 중이면 URL 이 404 라 실제로는 폴백 폰트가
   *    보이는데 UI 만 그 이름을 붙들고 있으므로 기본값으로 되돌린다.
   *  - 같은 이름으로 교체된 폰트는 family 는 같고 URL 의 ?v= 만 바뀐다. 저장된 URL 을
   *    갱신하지 않으면 24시간 캐시 때문에 옛 바이트를 계속 쓴다.
   *  반환값: UI 를 다시 그려야 하면 true. */
  function reconcileSelection() {
    if (selection.kind !== 'custom') return false;
    const match = customFonts.find(font => font.family === selection.family);
    if (!match) {
      applySelection(buildSelection({kind: 'default'}));
      showToast('선택했던 폰트가 삭제되어 기본 폰트로 되돌렸습니다.', 'info');
      return true;
    }
    if (match.url !== selection.url) {
      applySelection(buildSelection({...selectionSeed(), url: match.url, label: match.label}));
      return true;
    }
    return false;
  }

  /** 폭 측정으로 설치 여부를 판별한다(queryLocalFonts 미지원 환경 폴백). */
  function detectInstalledFonts(candidates) {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    if (!ctx) return [];
    const probe = 'mmmmmmmmmmlliWWWW가나다라1234';
    const bases = ['monospace', 'serif', 'sans-serif'];
    const baseline = bases.map(base => {
      ctx.font = `72px ${base}`;
      return ctx.measureText(probe).width;
    });
    const found = [];
    for (const family of candidates) {
      const differs = bases.some((base, index) => {
        ctx.font = `72px ${cssQuote(family)}, ${base}`;
        return Math.abs(ctx.measureText(probe).width - baseline[index]) > 0.5;
      });
      if (differs) found.push(family);
    }
    return found;
  }

  async function loadSystemFonts() {
    // Local Font Access API: 보안 컨텍스트 + 사용자 제스처 + 권한 승인이 필요하다.
    // Electron/데스크톱 Chrome 에서는 전체 목록을, 그 외에는 폭 측정 결과를 쓴다.
    if (typeof win.queryLocalFonts === 'function') {
      try {
        const fonts = await win.queryLocalFonts();
        // 패밀리당 Regular 계열 한 벌의 PostScript/전체 이름을 같이 붙든다.
        // 크기 보정용 @font-face 의 local() 이 이 이름으로만 매칭되기 때문이다.
        const byFamily = new Map();
        for (const item of fonts) {
          if (!item?.family) continue;
          const prior = byFamily.get(item.family);
          const isRegular = /regular|book|normal/i.test(item.style || '')
            || !/(bold|italic|light|thin|black|medium|semi|extra|oblique)/i.test(item.style || '');
          if (!prior || (isRegular && !prior.isRegular)) {
            byFamily.set(item.family, {
              family: item.family,
              postscript: item.postscriptName || '',
              fullName: item.fullName || '',
              isRegular,
            });
          }
        }
        if (byFamily.size) {
          systemFonts = [...byFamily.values()].sort((a, b) => a.family.localeCompare(b.family, 'ko'));
          systemLoaded = true;
          return;
        }
      } catch (error) {
        // 권한 거부/미지원 → 폴백으로 진행
      }
    }
    // 폭 측정 폴백은 패밀리명만 알 수 있다. localSrcCandidates() 가 이름을 추측한다.
    systemFonts = detectInstalledFonts(FONT_CANDIDATES)
      .map(family => ({family, postscript: '', fullName: '', isRegular: true}));
    systemLoaded = true;
    if (!systemFonts.length) showToast('설치된 폰트를 찾지 못했습니다.', 'error');
  }

  // ---- 업로드 / 삭제 ----

  async function uploadFontFile(file) {
    if (!file) return;
    showToast(`폰트 업로드 중: ${file.name}`, 'info');
    try {
      const response = await fetchFn(`/api/fonts/upload?filename=${encodeURIComponent(file.name)}`, {
        method: 'POST',
        headers: {'Content-Type': 'application/octet-stream'},
        body: file,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data?.ok) {
        showToast(data?.error || '폰트 업로드에 실패했습니다.', 'error');
        return;
      }
      await loadCustomFonts();
      const font = data.font;
      // 방금 올린 폰트를 바로 적용해 준다 - 확인하려고 다시 고르게 만들 이유가 없다.
      select({kind: 'custom', family: font.family, url: font.url, label: font.label});
      showToast(`폰트 추가됨: ${font.label}`, 'success');
    } catch (error) {
      showToast('폰트 업로드에 실패했습니다.', 'error');
    }
  }

  async function deleteFont(fontId) {
    const target = customFonts.find(font => font.id === fontId);
    if (!target) return;
    // 업로드 폰트는 서버에 보관돼 다른 기기와 공유되는 사용자 자산이고 되돌릴 수단이
    // 없다. 리포의 wildcard/vibe 삭제와 동일하게 확인을 받는다.
    if (typeof confirmDialog === 'function') {
      const ok = await confirmDialog(
        `'${target.label}' 폰트를 삭제할까요? 서버에서 파일이 지워지며 다른 기기에서도 사라집니다.`,
        {title: '폰트 삭제', okText: '삭제', cancelText: '취소'},
      );
      if (!ok) return;
    }
    try {
      const response = await fetchFn(`/api/fonts/${encodeURIComponent(fontId)}`, {method: 'DELETE'});
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data?.ok) {
        showToast(data?.error || '폰트 삭제에 실패했습니다.', 'error');
        return;
      }
      // 삭제한 폰트를 쓰고 있었다면 기본값으로 되돌린다(빈 스택 방지).
      if (selection.kind === 'custom' && selection.family === target.family) {
        applySelection(buildSelection({kind: 'default'}));
      }
      await loadCustomFonts();
      render();
      showToast(`폰트 삭제됨: ${target.label}`, 'success');
    } catch (error) {
      showToast('폰트 삭제에 실패했습니다.', 'error');
    }
  }

  // ---- 렌더 ----

  function currentLabel() {
    if (selection.kind === 'default') return '기본 (JetBrains Mono)';
    const suffix = selection.scale !== 100 ? ` · ${selection.scale}%` : '';
    return `${selection.label}${suffix}`;
  }

  function matchesFilter(value) {
    if (!filterText) return true;
    return String(value).toLowerCase().includes(filterText.toLowerCase());
  }

  function customRowsHtml() {
    const custom = customFonts.filter(font => matchesFilter(font.label));
    return custom.length
      ? custom.map(font => `
        <li class="font-row" style="font-family:${escHtml(cssQuote(previewFamilyOf(font)))}, ${FALLBACK_STACK}">
          <span class="font-row-name">${escHtml(font.label)}</span>
          <span class="font-row-meta">${escHtml(humanSize(font.size))}</span>
          <button type="button" class="font-row-btn" data-font-use-custom="${escHtml(font.id)}">사용</button>
          <button type="button" class="font-row-btn danger" data-font-delete="${escHtml(font.id)}">삭제</button>
        </li>`).join('')
      : '<li class="font-row empty">업로드한 폰트가 없습니다.</li>';
  }

  function systemRowsHtml() {
    const system = systemFonts.filter(item => matchesFilter(item.family)).slice(0, 300);
    return !systemLoaded
      ? '<li class="font-row empty">‘시스템 폰트 불러오기’를 눌러 목록을 가져오세요.</li>'
      : (system.length
        ? system.map(item => `
          <li class="font-row" style="font-family:${escHtml(cssQuote(item.family))}, ${FALLBACK_STACK}">
            <span class="font-row-name">${escHtml(item.family)}</span>
            <button type="button" class="font-row-btn" data-font-use-system="${escHtml(item.family)}">사용</button>
          </li>`).join('')
        : '<li class="font-row empty">일치하는 폰트가 없습니다.</li>');
  }

  function addPanelHtml() {
    if (!addOpen) return '';
    return `
      <div class="font-add-panel">
        <div class="font-add-actions">
          <button type="button" class="mod-btn-secondary" data-font-action="load-system">시스템 폰트 불러오기</button>
          <button type="button" class="mod-btn-secondary" data-font-action="pick-file">폰트 파일 추가…</button>
          <input type="file" accept=".otf,.ttf,.ttc,.woff,.woff2,font/otf,font/ttf,font/woff,font/woff2"
                 data-font-file hidden>
        </div>
        <input type="text" class="font-add-filter" data-font-filter placeholder="폰트 이름 검색…"
               value="${escHtml(filterText)}">
        <div class="font-add-section">
          <h4>내가 추가한 폰트</h4>
          <ul class="font-list" data-font-list="custom">${customRowsHtml()}</ul>
        </div>
        <div class="font-add-section">
          <h4 data-font-system-title>시스템 폰트${systemLoaded ? ` (${systemFonts.length})` : ''}</h4>
          <ul class="font-list" data-font-list="system">${systemRowsHtml()}</ul>
        </div>
      </div>`;
  }

  /** 검색어 변경 시 목록만 갈아 끼운다.
   *  render() 로 전체를 다시 그리면 root.innerHTML 교체로 검색 input 자체가 파괴돼
   *  **한글 IME 조합이 취소된다**(자모 단위로 확정되거나 입력이 끊김).
   *  입력 요소는 그대로 두고 <ul> 내용만 바꿔야 조합이 유지된다. */
  function renderLists() {
    const custom = root.querySelector('[data-font-list="custom"]');
    if (custom) custom.innerHTML = customRowsHtml();
    const system = root.querySelector('[data-font-list="system"]');
    if (system) system.innerHTML = systemRowsHtml();
    const title = root.querySelector('[data-font-system-title]');
    if (title) title.textContent = `시스템 폰트${systemLoaded ? ` (${systemFonts.length})` : ''}`;
  }

  function render() {
    const isDefault = selection.kind === 'default';
    root.innerHTML = `
      <div class="font-settings-row">
        <span class="font-current" title="${escHtml(currentLabel())}">${escHtml(currentLabel())}</span>
        <button type="button" class="mod-btn-secondary" data-font-action="toggle-add">
          ${addOpen ? '닫기' : '폰트 추가 / 변경'}
        </button>
        <button type="button" class="mod-btn-secondary" data-font-action="reset" ${isDefault ? 'disabled' : ''}>
          기본값
        </button>
      </div>
      <div class="font-scale-row">
        <label for="fontEditorScale">크기 보정</label>
        <input type="range" id="fontEditorScale" min="${MIN_SCALE}" max="${MAX_SCALE}" step="1"
               value="${selection.scale}" ${isDefault ? 'disabled' : ''} data-font-scale>
        <span class="font-scale-value">${selection.scale}%</span>
      </div>
      <div class="font-preview" data-font-preview>${escHtml(PREVIEW_TEXT)}</div>
      ${addPanelHtml()}`;

    // 미리보기는 --font-editor 를 그대로 상속받으므로 별도 지정이 필요 없다.
    const filterInput = root.querySelector('[data-font-filter]');
    if (filterInput && addOpen) {
      // 목록만 갱신한다 - 입력 요소를 살려 둬야 한글 조합이 끊기지 않는다.
      filterInput.addEventListener('input', () => {
        filterText = filterInput.value;
        renderLists();
      });
    }
  }

  // ---- 이벤트 ----

  root.addEventListener('click', event => {
    const useCustom = event.target.closest('[data-font-use-custom]');
    if (useCustom) {
      const font = customFonts.find(item => item.id === useCustom.dataset.fontUseCustom);
      if (font) select({kind: 'custom', family: font.family, url: font.url, label: font.label});
      return;
    }
    const useSystem = event.target.closest('[data-font-use-system]');
    if (useSystem) {
      const family = useSystem.dataset.fontUseSystem;
      const entry = systemFonts.find(item => item.family === family);
      select({
        kind: 'system', family, url: '', label: family,
        postscript: entry?.postscript || '', fullName: entry?.fullName || '',
      });
      return;
    }
    const del = event.target.closest('[data-font-delete]');
    if (del) {
      deleteFont(del.dataset.fontDelete);
      return;
    }
    const action = event.target.closest('[data-font-action]');
    if (!action) return;
    const kind = action.dataset.fontAction;
    if (kind === 'toggle-add') {
      addOpen = !addOpen;
      render();
      // 목록은 서버(다른 기기와 공유)에 있으므로 열 때마다 다시 받는다.
      // storage 이벤트는 같은 브라우저 안에서만 전파돼 다른 기기의 업로드·삭제를
      // 알려주지 못한다. 비어 있을 때만 받으면 그 변경이 영영 반영되지 않는다.
      if (addOpen) loadCustomFonts().then(render);
    } else if (kind === 'reset') {
      applySelection(buildSelection({kind: 'default'}));
      render();
    } else if (kind === 'load-system') {
      action.disabled = true;
      action.textContent = '불러오는 중…';
      loadSystemFonts().finally(render);
    } else if (kind === 'pick-file') {
      root.querySelector('[data-font-file]')?.click();
    }
  });

  root.addEventListener('change', event => {
    const file = event.target.closest('[data-font-file]');
    if (file && file.files && file.files[0]) {
      const picked = file.files[0];
      file.value = '';
      uploadFontFile(picked);
    }
  });

  root.addEventListener('input', event => {
    const scale = event.target.closest('[data-font-scale]');
    if (!scale) return;
    const next = buildSelection({...selectionSeed(), scale: scale.value});
    applySelection(next);
    // 드래그 중에는 re-render 하지 않는다(슬라이더 DOM 이 날아가 드래그가 끊긴다).
    // 대신 값이 걸린 텍스트만 직접 갱신한다.
    const value = root.querySelector('.font-scale-value');
    if (value) value.textContent = `${next.scale}%`;
    const current = root.querySelector('.font-current');
    if (current) {
      current.textContent = currentLabel();
      current.title = currentLabel();
    }
    verifyScaleApplied();
  });

  return {
    init() {
      applySelection(selection);
      render();
      // 목록을 받은 뒤 선택이 조정되면(삭제됨 / URL 갱신) 패널 표시도 따라가야 한다.
      // addOpen 일 때만 다시 그리면, 실제 폰트는 기본값인데 화면에는 삭제된 폰트명과
      // 활성화된 '기본값' 버튼이 남는다.
      loadCustomFonts().then(() => render());
    },
    refresh() {
      loadCustomFonts().then(render);
    },
  };
}
