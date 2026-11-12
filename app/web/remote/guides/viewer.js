'use strict';
// 목차는 catalog.json 이 원본이다(개발 전용 편집기가 고쳐 쓴다). id 는 공개 딥링크이므로 바꾸지 않는다.
// - category 가 빈 문서는 분류 없이 목차 맨 위에 둔다.
// - hide_when: 'nai_configured' 문서는 NAI 토큰이 이미 저장돼 있으면 목차에서 숨긴다(주소로는 열린다).
// catalog.json 을 못 읽으면 아래 기본 목록으로 연다.
const WELCOME = { id: 'welcome', category: '', title: '목차', summary: 'NAIA의 설정과 사용 방법', keywords: '홈 안내 사용법 가이드 소개' };
const FALLBACK_PAGES = [
  { id: 'novelai-token', category: '', title: 'NovelAI 토큰 발급', summary: 'NovelAI 토큰을 발급하고 NAIA에 연결하는 방법을 안내합니다.', keywords: 'API 연결 설정 키 인증', file: 'novelai-token.html', hide_when: 'nai_configured' },
  { id: 'conditional-prompt', category: '2. 프롬프트', title: '조건부 프롬프트 (AI 생성)', summary: '조건에 따라 프롬프트를 구성하는 방법을 살펴봅니다.', keywords: '조건 태그 문법', file: 'conditional-prompt.html' },
];
let pages = [WELCOME, ...FALLBACK_PAGES];
const facts = { nai_configured: false };
const byId = id => document.getElementById(id);
let current;
let lastHash = '';
let loadGeneration = 0;
let documentResize;
const expanded = new Map();

// 편집기(editor.js)가 끼어드는 자리. 편집기가 없으면 아무 일도 하지 않는다.
const guide = window.NaiaGuide = {
  get pages() { return pages; },
  get current() { return current; },
  showHidden: false,     // 편집 중에는 숨긴 문서도 목차에 보인다
  setCatalog(catalogPages) { pages = [WELCOME, ...catalogPages]; renderWelcome(); navigation(); },
  refreshNavigation: () => { renderWelcome(); navigation(); },
  reload: (options) => showPage(options),
  beforeLeave: null,     // () => boolean - false 면 페이지를 떠나지 않는다
  onShown: null,         // (page) => void - 머리글 · 목차를 다 그린 뒤
  onFrameReady: null,    // (page, doc) => void - iframe 문서에 읽기 스타일까지 입힌 뒤
};

const isHidden = page => !guide.showHidden && !!page.hide_when && !!facts[page.hide_when];
const visiblePages = () => pages.filter(page => !isHidden(page));
const categoriesOf = list => [...new Set(list.map(page => page.category).filter(Boolean))];

function pageLink(page) {
  const link = document.createElement('a');
  link.href = `#${page.id}`;
  link.textContent = page.title;
  return link;
}

function renderWelcome() {
  const article = byId('article');
  article.replaceChildren();
  const intro = document.createElement('p');
  intro.textContent = 'NAIA의 설정과 사용 방법을 정리한 문서입니다. 왼쪽 목차에서 읽을 문서를 선택할 수 있습니다.';
  article.append(intro);
  const shown = visiblePages().filter(page => page !== WELCOME);
  const list = entries => {
    const ul = document.createElement('ul');
    for (const page of entries) {
      const item = document.createElement('li');
      item.append(pageLink(page));
      if (page.summary) item.append(` — ${page.summary}`);
      ul.append(item);
    }
    return ul;
  };
  const topLevel = shown.filter(page => !page.category);
  if (topLevel.length) article.append(list(topLevel));
  for (const category of categoriesOf(shown)) {
    const heading = document.createElement('h2');
    heading.textContent = category;
    article.append(heading, list(shown.filter(page => page.category === category)));
  }
}

function navigation() {
  const query = byId('search').value.trim().toLocaleLowerCase();
  const nav = byId('navigation');
  nav.replaceChildren();
  const matching = visiblePages().filter(page => `${page.category} ${page.title} ${page.summary} ${page.keywords}`.toLocaleLowerCase().includes(query));
  const mark = (link, page) => { if (page.id === current?.id) link.setAttribute('aria-current', 'page'); return link; };
  for (const page of matching.filter(entry => !entry.category)) {
    const link = mark(pageLink(page), page);
    link.className = 'top-link';
    nav.append(link);
  }
  for (const category of categoriesOf(matching)) {
    const group = document.createElement('details');
    group.open = query ? true : expanded.get(category) !== false;
    group.addEventListener('toggle', () => { if (!byId('search').value.trim()) expanded.set(category, group.open); });
    const label = document.createElement('summary');
    label.textContent = category;
    group.append(label);
    for (const page of matching.filter(entry => entry.category === category)) group.append(mark(pageLink(page), page));
    nav.append(group);
  }
  byId('empty').hidden = matching.length > 0;
}

function setMenu(open) {
  byId('sidebar').classList.toggle('open', open);
  byId('menu').setAttribute('aria-expanded', String(open));
  byId('menu').setAttribute('aria-label', open ? '목차 닫기' : '목차 열기');
}

async function showPage({ fresh = false } = {}) {
  const generation = ++loadGeneration;
  const requested = location.hash.slice(1);
  current = pages.find(page => page.id === requested) || pages[0];
  if (requested !== current.id) history.replaceState(null, '', `#${current.id}`);
  lastHash = location.hash;
  const page = current;
  document.title = `${page.title} · NAIA Guide`;
  byId('title').textContent = page.heading || page.title;
  byId('breadcrumb').textContent = ['가이드', page.category, page.title].filter(Boolean).join(' / ');
  byId('summary').textContent = page.summary;
  byId('summary').hidden = !page.file;
  byId('article').hidden = !!page.file;
  byId('embedded').hidden = !page.file;
  byId('original').hidden = !page.file;
  const frame = byId('documentFrame');
  documentResize?.disconnect();
  frame.style.height = '420px';
  frame.hidden = true;
  frame.removeAttribute('src');
  frame.onload = null;
  if (page.file) {
    byId('original').href = page.file;
    byId('loadStatus').textContent = '문서를 불러오는 중…';
    frame.title = page.title;
    // 편집 뒤에는 캐시를 건너뛴다 - 방금 저장한 본문을 읽어야 한다.
    const source = fresh ? `${page.file}?t=${Date.now()}` : page.file;
    try {
      const response = await fetch(source, fresh ? { cache: 'no-store' } : undefined);
      if (!response.ok) throw new Error('Document unavailable');
      if (generation !== loadGeneration) return;
      frame.onload = () => {
        if (generation !== loadGeneration) return;
        const doc = frame.contentDocument;
        if (!doc?.querySelector('.page')) return;
        // 링크는 늘 새 브라우저 탭에서 - 문서 안 # 이동만 제자리.
        doc.querySelectorAll('a[href]').forEach(a => {
          if (a.getAttribute('href').startsWith('#')) return;
          a.target = '_blank';
          a.rel = 'noopener noreferrer';
        });
        const style = doc.createElement('link');
        style.rel = 'stylesheet';
        style.href = 'document.css?v=5';
        const ready = () => {
          if (generation !== loadGeneration) return;
          const resize = () => { frame.style.height = `${Math.ceil(Math.max(doc.body.scrollHeight, doc.body.getBoundingClientRect().height)) + 2}px`; };
          documentResize = new ResizeObserver(resize);
          documentResize.observe(doc.body);
          resize();
          frame.style.visibility = '';
          byId('loadStatus').textContent = '';
          try { guide.onFrameReady?.(page, doc); } catch (error) { console.error(error); }
        };
        style.onload = ready;
        style.onerror = ready;
        doc.head.append(style);
      };
      frame.src = source;
      frame.style.visibility = 'hidden';
      frame.hidden = false;
    } catch {
      if (generation === loadGeneration) byId('loadStatus').textContent = '문서를 불러오지 못했습니다. 새로고침하거나 위의 별도 페이지 링크를 이용해 주세요.';
    }
  }
  // 이전 · 다음은 목차에 보이는 차례대로 - 숨긴 문서는 건너뛴다.
  const order = visiblePages();
  const index = order.indexOf(page);
  for (const [id, step, prefix] of [['previous', -1, '← 이전 · '], ['next', 1, '다음 · ']]) {
    const neighbor = index >= 0 ? order[index + step] : undefined;
    const link = byId(id);
    link.hidden = !neighbor;
    if (neighbor) { link.href = `#${neighbor.id}`; link.textContent = prefix + neighbor.title; }
  }
  if (page.category) expanded.set(page.category, true);
  navigation();
  setMenu(false);
  window.scrollTo(0, 0);
  try { guide.onShown?.(page); } catch (error) { console.error(error); }
}

function onHashChange() {
  if (guide.beforeLeave && location.hash !== lastHash && !guide.beforeLeave()) {
    history.replaceState(null, '', lastHash || '#welcome');
    return;
  }
  showPage();
}

async function loadCatalog() {
  try {
    const response = await fetch('catalog.json', { cache: 'no-store' });
    if (!response.ok) return;
    const catalog = await response.json();
    if (Array.isArray(catalog?.pages) && catalog.pages.length) pages = [WELCOME, ...catalog.pages];
  } catch { /* 기본 목록으로 연다 */ }
}

// NAI 토큰이 저장돼 있는가 - NAIA 서버가 아니면(정적 서버 등) 모른다고 보고 다 보인다.
async function loadFacts() {
  try {
    const response = await fetch('/api/status', { cache: 'no-store' });
    if (!response.ok) return;
    const status = await response.json();
    facts.nai_configured = status?.nai_configured === true;
  } catch { /* 모두 보인다 */ }
}

// 개발 서버에서만 편집기를 싣는다 - 포터블 · 릴리즈에는 이 라우트가 없어 404 다.
async function loadEditor() {
  try {
    const response = await fetch('/api/guide-editor/status', { cache: 'no-store' });
    if (!response.ok) return;
    const status = await response.json();
    if (!status?.enabled) return;
  } catch { return; }
  const script = document.createElement('script');
  script.src = 'editor.js?v=8';
  document.head.append(script);
}

byId('search').addEventListener('input', navigation);
byId('menu').addEventListener('click', () => setMenu(!byId('sidebar').classList.contains('open')));
byId('navigation').addEventListener('click', event => { if (event.target.closest('a')) setMenu(false); });
document.addEventListener('keydown', event => { if (event.key === 'Escape') { setMenu(false); byId('menu').focus(); } });
window.addEventListener('hashchange', onHashChange);
Promise.all([loadCatalog(), loadFacts()]).then(() => { renderWelcome(); showPage(); loadEditor(); });
