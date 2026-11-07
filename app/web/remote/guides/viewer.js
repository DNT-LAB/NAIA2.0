'use strict';
// Stable IDs are also the public deep links. Keep existing standalone guides intact.
const pages = [
  { id: 'welcome', category: '시작하기', title: '가이드 소개', summary: 'NAIA의 설정과 사용 방법', keywords: '홈 안내 사용법' },
  { id: 'novelai-token', category: '시작하기', title: 'NovelAI 토큰 발급', summary: 'NovelAI 토큰을 발급하고 NAIA에 연결하는 방법을 안내합니다.', keywords: 'API 연결 설정 키 인증', file: 'novelai-token.html' },
  { id: 'conditional-prompt', category: '프롬프트', title: '조건부 프롬프트', summary: '조건에 따라 프롬프트를 구성하는 방법을 살펴봅니다.', keywords: '조건 태그 문법', file: 'conditional-prompt.html' },
];
const byId = id => document.getElementById(id);
let current;
let loadGeneration = 0;
let documentResize;
const expanded = new Map();
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
async function showPage() {
  const generation = ++loadGeneration;
  const requested = location.hash.slice(1);
  current = pages.find(page => page.id === requested) || pages[0];
  if (requested !== current.id) history.replaceState(null, '', `#${current.id}`);
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
    try {
      const response = await fetch(page.file);
      if (!response.ok) throw new Error('Document unavailable');
      if (generation !== loadGeneration) return;
      frame.onload = () => {
        if (generation !== loadGeneration) return;
        const doc = frame.contentDocument;
        if (!doc?.querySelector('.page')) return;
        const style = doc.createElement('link');
        style.rel = 'stylesheet';
        style.href = 'document.css?v=3';
        style.onload = () => {
          if (generation !== loadGeneration) return;
          const resize = () => { frame.style.height = `${Math.ceil(Math.max(doc.body.scrollHeight, doc.body.getBoundingClientRect().height)) + 2}px`; };
          documentResize = new ResizeObserver(resize);
          documentResize.observe(doc.body);
          resize();
          frame.style.visibility = '';
          byId('loadStatus').textContent = '';
        };
        style.onerror = () => { frame.style.visibility = ''; byId('loadStatus').textContent = ''; };
        doc.head.append(style);
      };
      frame.src = page.file;
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
}
byId('search').addEventListener('input', navigation);
byId('menu').addEventListener('click', () => setMenu(!byId('sidebar').classList.contains('open')));
byId('navigation').addEventListener('click', event => { if (event.target.closest('a')) setMenu(false); });
document.addEventListener('keydown', event => { if (event.key === 'Escape') { setMenu(false); byId('menu').focus(); } });
window.addEventListener('hashchange', showPage);
showPage();
