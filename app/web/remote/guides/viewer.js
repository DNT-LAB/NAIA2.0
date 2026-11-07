'use strict';
// 목차는 catalog.json 이 원본이다(개발 전용 편집기가 고쳐 쓴다). id 는 공개 딥링크이므로 바꾸지 않는다.
// catalog.json 을 못 읽으면 아래 기본 목록으로 연다.
const WELCOME = { id: 'welcome', category: '시작하기', title: '가이드 소개', summary: 'NAIA의 설정과 사용 방법', keywords: '홈 안내 사용법' };
const FALLBACK_PAGES = [
  { id: 'novelai-token', category: '시작하기', title: 'NovelAI 토큰 발급', summary: 'NovelAI 토큰을 발급하고 NAIA에 연결하는 방법을 안내합니다.', keywords: 'API 연결 설정 키 인증', file: 'novelai-token.html' },
  { id: 'conditional-prompt', category: '프롬프트', title: '조건부 프롬프트', summary: '조건에 따라 프롬프트를 구성하는 방법을 살펴봅니다.', keywords: '조건 태그 문법', file: 'conditional-prompt.html' },
];
let pages = [WELCOME, ...FALLBACK_PAGES];
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
  setCatalog(catalogPages) { pages = [WELCOME, ...catalogPages]; renderWelcome(); navigation(); },
  reload: (options) => showPage(options),
  beforeLeave: null,     // () => boolean - false 면 페이지를 떠나지 않는다
  onShown: null,         // (page) => void - 머리글 · 목차를 다 그린 뒤
  onFrameReady: null,    // (page, doc) => void - iframe 문서에 읽기 스타일까지 입힌 뒤
};

function renderWelcome() {
  const article = byId('article');
  article.replaceChildren();
  const intro = document.createElement('p');
  intro.textContent = 'NAIA의 설정과 사용 방법을 정리한 문서입니다. 왼쪽 목차에서 읽을 문서를 선택할 수 있습니다.';
  article.append(intro);
  for (const category of new Set(pages.slice(1).map(page => page.category))) {
    const heading = document.createElement('h2');
    heading.textContent = category;
    const list = document.createElement('ul');
    for (const page of pages.slice(1).filter(entry => entry.category === category)) {
      const item = document.createElement('li');
      const link = document.createElement('a');
      link.href = `#${page.id}`;
      link.textContent = page.title;
      item.append(link);
      if (page.summary) item.append(` — ${page.summary}`);
      list.append(item);
    }
    article.append(heading, list);
  }
}

function navigation() {
  const query = byId('search').value.trim().toLocaleLowerCase();
  const nav = byId('navigation');
  nav.replaceChildren();
  let matches = 0;
  for (const category of new Set(pages.map(page => page.category))) {
    const entries = pages.filter(page => page.category === category && `${page.category} ${page.title} ${page.summary} ${page.keywords}`.toLocaleLowerCase().includes(query));
    if (!entries.length) continue;
    const group = document.createElement('details');
    group.open = query ? true : expanded.get(category) !== false;
    group.addEventListener('toggle', () => { if (!byId('search').value.trim()) expanded.set(category, group.open); });
    const label = document.createElement('summary');
    label.textContent = category;
    group.append(label);
    for (const page of entries) {
      const link = document.createElement('a');
      link.href = `#${page.id}`;
      link.textContent = page.title;
      if (page.id === current?.id) link.setAttribute('aria-current', 'page');
      group.append(link);
      matches++;
    }
    nav.append(group);
  }
  byId('empty').hidden = matches > 0;
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
  byId('breadcrumb').textContent = `가이드 / ${page.category} / ${page.title}`;
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
        const style = doc.createElement('link');
        style.rel = 'stylesheet';
        style.href = 'document.css?v=4';
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
  const index = pages.indexOf(page);
  for (const [id, neighbor, prefix] of [['previous', pages[index - 1], '← 이전 · '], ['next', pages[index + 1], '다음 · ']]) {
    const link = byId(id);
    link.hidden = !neighbor;
    if (neighbor) { link.href = `#${neighbor.id}`; link.textContent = prefix + neighbor.title; }
  }
  expanded.set(page.category, true);
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

// 개발 서버에서만 편집기를 싣는다 - 포터블 · 릴리즈에는 이 라우트가 없어 404 다.
async function loadEditor() {
  try {
    const response = await fetch('/api/guide-editor/status', { cache: 'no-store' });
    if (!response.ok) return;
    const status = await response.json();
    if (!status?.enabled) return;
  } catch { return; }
  const script = document.createElement('script');
  script.src = 'editor.js?v=3';
  document.head.append(script);
}

byId('search').addEventListener('input', navigation);
byId('menu').addEventListener('click', () => setMenu(!byId('sidebar').classList.contains('open')));
byId('navigation').addEventListener('click', event => { if (event.target.closest('a')) setMenu(false); });
document.addEventListener('keydown', event => { if (event.key === 'Escape') { setMenu(false); byId('menu').focus(); } });
window.addEventListener('hashchange', onHashChange);
loadCatalog().then(() => { renderWelcome(); showPage(); loadEditor(); });
