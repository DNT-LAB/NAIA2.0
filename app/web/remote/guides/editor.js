'use strict';
// 가이드 편집기(개발 전용). viewer.js 가 /api/guide-editor/status 를 확인한 뒤에만 싣는다.
// - 본문: iframe 문서의 <main class="page"> 를 그 자리에서 고친다(contentEditable).
// - Ctrl+V 그림: 서버가 긴 변 1600px · WebP 로 다시 인코딩해 assets/ 에 둔다.
// - 제목 · 요약 · 분류 · 순서 · 새 문서: catalog.json 에 쓴다.
(() => {
  const guide = window.NaiaGuide;
  if (!guide || guide.editorLoaded) return;
  guide.editorLoaded = true;

  const EDIT_KEY = 'naia.guide.edit';
  const byId = id => document.getElementById(id);
  const readEditing = () => { try { return sessionStorage.getItem(EDIT_KEY) === '1'; } catch { return false; } };
  const writeEditing = on => { try { sessionStorage.setItem(EDIT_KEY, on ? '1' : '0'); } catch { /* 탭 상태만 잃는다 */ } };

  let editing = readEditing();
  let dirty = false;
  let catalogDirty = false;
  let uploading = 0;
  let frameDoc = null;
  let page = null;

  const style = document.createElement('style');
  style.textContent = `
    .edit-toggle { margin-left: auto; padding: 2px 8px; border: 0; border-radius: 4px; background: none; color: rgba(55,53,47,.65); font-size: 14px; }
    .reader-bar a:not([hidden]) + .edit-toggle { margin-left: 8px; }
    .edit-toggle:hover { background: rgba(55,53,47,.06); color: #37352f; }
    .edit-toggle[aria-pressed=true] { background: rgba(255,193,7,.18); color: #0e1117; }
    #guideEditBar { position: sticky; top: 0; z-index: 4; max-width: 708px; margin: 8px auto 0; display: flex; flex-wrap: wrap; align-items: center; gap: 4px 6px;
      padding: 6px 8px; background: #fff; border: 1px solid #e9e9e7; border-radius: 8px; font-size: 13px; color: #37352f; }
    #guideEditBar .badge { padding: 2px 8px; border-radius: 4px; background: rgba(255,193,7,.18); color: #0e1117; font-weight: 600; }
    #guideEditBar button, #guideEditBar select { height: 26px; padding: 0 8px; border: 0; border-radius: 4px; background: none; color: #37352f; font-size: 13px; }
    #guideEditBar button:hover, #guideEditBar select:hover { background: rgba(55,53,47,.08); }
    #guideEditBar .sep { width: 1px; height: 16px; background: #e9e9e7; margin: 0 2px; }
    #guideEditBar .group { display: inline-flex; align-items: center; gap: 4px; margin-left: auto; }
    #guideEditBar .primary { background: #37352f; color: #fff; }
    #guideEditBar .primary:hover { background: #2a2925; }
    #guideEditStatus { width: 100%; padding: 2px 4px 0; color: rgba(55,53,47,.65); font-size: 12px; }
    #guideEditStatus.error { color: #d44c47; }
    #guideEditStatus:empty { display: none; }
    #documentFrame.editing { outline: 1px dashed #c7c6c2; outline-offset: 10px; border-radius: 2px; }
    #title[contenteditable=plaintext-only], #summary[contenteditable=plaintext-only] { outline: none; border-radius: 4px; }
    #title[contenteditable=plaintext-only]:hover, #summary[contenteditable=plaintext-only]:hover { background: rgba(55,53,47,.04); }
    .new-doc { margin: 8px 2px 0; }
    .new-doc > button { width: 100%; height: 28px; padding: 0 10px; border: 0; border-radius: 6px; background: none; color: rgba(55,53,47,.65); font-size: 14px; text-align: left; }
    .new-doc > button:hover { background: rgba(55,53,47,.06); color: #37352f; }
    .new-doc form { display: grid; gap: 6px; padding: 8px; background: #fff; border: 1px solid #e9e9e7; border-radius: 8px; font-size: 13px; }
    .new-doc label { display: grid; gap: 2px; color: rgba(55,53,47,.65); font-size: 12px; }
    .new-doc input { height: 28px; padding: 0 8px; border: 1px solid #e9e9e7; border-radius: 4px; font-size: 13px; color: #37352f; }
    .new-doc .row { display: flex; gap: 6px; justify-content: flex-end; }
    .new-doc .row button { height: 26px; padding: 0 10px; border: 0; border-radius: 4px; background: rgba(55,53,47,.06); font-size: 13px; }
    .new-doc .row button[type=submit] { background: #37352f; color: #fff; }
    .new-doc .err { color: #d44c47; font-size: 12px; }
  `;
  document.head.append(style);

  // ── 위 막대의 [편집] ─────────────────────────────────────────────────────────
  const toggle = document.createElement('button');
  toggle.type = 'button';
  toggle.className = 'edit-toggle';
  toggle.textContent = '편집';
  toggle.title = '가이드 편집 (개발 서버 전용)';
  document.querySelector('.reader-bar').append(toggle);
  toggle.addEventListener('click', () => {
    if (editing && dirty && !confirm('저장하지 않은 변경이 있습니다. 버리고 편집을 끌까요?')) return;
    editing = !editing;
    writeEditing(editing);
    dirty = false;
    catalogDirty = false;
    guide.reload({ fresh: true });
  });

  // ── 편집 막대 ────────────────────────────────────────────────────────────────
  const bar = document.createElement('div');
  bar.id = 'guideEditBar';
  bar.hidden = true;
  bar.innerHTML = `
    <span class="badge">편집 중</span>
    <span class="sep"></span>
    <button type="button" data-block="p" title="본문 (Ctrl+Alt+0)">본문</button>
    <button type="button" data-block="h2" title="소제목 (Ctrl+Alt+2)">소제목</button>
    <button type="button" data-block="h3" title="작은 제목 (Ctrl+Alt+3)">작은 제목</button>
    <button type="button" data-cmd="insertUnorderedList" title="글머리 목록">목록</button>
    <button type="button" data-cmd="bold" title="굵게 (Ctrl+B)"><b>B</b></button>
    <button type="button" data-link title="링크 (Ctrl+K) - 새 브라우저 탭에서 열립니다">링크</button>
    <span class="sep"></span>
    <button type="button" data-box="callout good" title="문단을 녹색 상자로">녹색 상자</button>
    <button type="button" data-box="callout warn" title="문단을 노란 상자로">노란 상자</button>
    <button type="button" data-unbox title="상자를 풀어 본문으로">상자 풀기</button>
    <span class="group">
      <select data-category title="이 문서의 분류"></select>
      <button type="button" data-move="-1" title="목차에서 위로">↑</button>
      <button type="button" data-move="1" title="목차에서 아래로">↓</button>
      <span class="sep"></span>
      <button type="button" data-cancel>취소</button>
      <button type="button" class="primary" data-save title="저장 (Ctrl+S)">저장</button>
    </span>
    <div id="guideEditStatus" role="status"></div>`;
  document.querySelector('.document-heading').after(bar);
  const statusEl = byId('guideEditStatus');
  const setStatus = (text, error = false) => { statusEl.textContent = text; statusEl.classList.toggle('error', error); };
  const kb = bytes => (bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)}MB` : `${Math.max(1, Math.round(bytes / 1024))}KB`);

  function markDirty() {
    if (!dirty) { dirty = true; setStatus('저장 안 된 변경이 있습니다.'); }
  }

  // 편집 막대의 단추는 누를 때 초점을 뺏지 않는다 - iframe 의 커서 자리를 지킨다.
  bar.addEventListener('mousedown', event => { if (event.target.closest('button')) event.preventDefault(); });
  bar.addEventListener('click', event => {
    const button = event.target.closest('button');
    if (!button || !frameDoc) return;
    if (button.dataset.block) { frameDoc.execCommand('formatBlock', false, button.dataset.block); markDirty(); }
    else if (button.dataset.cmd) {
      frameDoc.execCommand(button.dataset.cmd, false);
      if (button.dataset.cmd === 'insertUnorderedList') { stripListMarks(frameDoc); liftLists(mainOf(frameDoc)); }
      markDirty();
    }
    else if (button.dataset.box) wrapInBox(button.dataset.box);
    else if ('unbox' in button.dataset) unwrapBox();
    else if ('link' in button.dataset) editLink();
    else if (button.dataset.move) moveInCatalog(Number(button.dataset.move));
    else if ('cancel' in button.dataset) cancelEdits();
    else if ('save' in button.dataset) save();
  });
  bar.querySelector('[data-category]').addEventListener('change', event => changeCategory(event.target));

  // ── iframe 본문 ──────────────────────────────────────────────────────────────
  const mainOf = doc => doc?.querySelector('main.page');
  const CONTAINERS = 'main.page, section, article, .step-copy, .steps';

  function blockAtCaret(doc) {
    const main = mainOf(doc);
    const selection = doc.getSelection();
    let node = selection && selection.rangeCount ? selection.getRangeAt(0).endContainer : null;
    if (!node || !main.contains(node)) return null;
    let el = node.nodeType === 1 ? node : node.parentElement;
    while (el && el !== main && !(el.parentElement && el.parentElement.matches(CONTAINERS))) el = el.parentElement;
    return el && el !== main ? el : null;
  }

  function placeCaretIn(doc, el) {
    const range = doc.createRange();
    range.selectNodeContents(el);
    range.collapse(true);
    const selection = doc.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  }

  function wrapInBox(className) {
    const block = blockAtCaret(frameDoc);
    if (!block) { setStatus('상자로 감쌀 문단에 커서를 두세요.', true); return; }
    if (block.matches('.callout, .notice, .final')) { block.className = className; markDirty(); return; }
    const box = frameDoc.createElement('div');
    box.className = className;
    block.before(box);
    box.append(block);
    markDirty();
  }

  function unwrapBox() {
    const block = blockAtCaret(frameDoc);
    const box = block?.closest('.callout, .notice, .final');
    if (!box || box.tagName === 'SPAN') { setStatus('커서가 상자 안에 있지 않습니다.', true); return; }
    box.replaceWith(...box.childNodes);
    markDirty();
  }

  async function insertImage(file) {
    const doc = frameDoc;
    const main = mainOf(doc);
    const block = blockAtCaret(doc);
    const figure = doc.createElement('figure');
    figure.className = 'image-wrap guide-uploading';
    figure.contentEditable = 'false';
    figure.textContent = `그림 올리는 중… (${kb(file.size)})`;
    if (block) block.after(figure); else main.append(figure);
    const next = doc.createElement('p');
    next.append(doc.createElement('br'));
    figure.after(next);
    placeCaretIn(doc, next);
    markDirty();
    uploading++;
    setStatus(`그림 올리는 중… (${kb(file.size)})`);
    try {
      const response = await fetch(`/api/guide-editor/assets?doc=${encodeURIComponent(page.id)}`, {
        method: 'POST', headers: { 'Content-Type': file.type || 'application/octet-stream' }, body: file,
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || !result.ok) throw new Error(result.error || `HTTP ${response.status}`);
      if (frameDoc !== doc) return;   // 그사이 다른 문서로 갔다 - 파일만 남는다
      const img = doc.createElement('img');
      img.src = result.path;
      img.alt = '';
      img.width = result.width;
      img.height = result.height;
      figure.replaceChildren(img);
      figure.classList.remove('guide-uploading');
      const resized = result.original_width !== result.width ? ` · ${result.original_width}→${result.width}px` : '';
      setStatus(`그림 넣음 · ${kb(result.bytes_in)} → ${kb(result.bytes_out)} (${result.mode === 'lossless' ? '무손실' : '손실'} WebP${resized}) · 두 번 누르면 설명(alt)을 적습니다.`);
    } catch (error) {
      figure.remove();
      setStatus(`그림을 올리지 못했습니다: ${error.message}`, true);
    } finally {
      uploading--;
    }
  }

  function onPaste(event) {
    const items = [...(event.clipboardData?.items || [])];
    const image = items.find(item => item.kind === 'file' && item.type.startsWith('image/'))?.getAsFile();
    if (image) { event.preventDefault(); insertImage(image); return; }
    // 다른 곳에서 복사한 서식(글꼴 · 색 · 배경)이 문서에 묻지 않게 글자만 넣는다.
    const text = event.clipboardData?.getData('text/plain');
    if (!text) return;
    event.preventDefault();
    // 주소 하나를 붙여넣으면 링크 - 글자를 골라 두었으면 그 글자에, 아니면 주소 그대로.
    const url = text.trim();
    const selection = frameDoc.getSelection();
    if (LINK_RE.test(url) && selection?.rangeCount) {
      if (selection.isCollapsed) insertLink(frameDoc, url);
      else wrapSelectionInLink(frameDoc, url);
      markDirty();
      setStatus(`링크를 걸었습니다 · ${url} · 새 탭에서 열립니다.`);
      return;
    }
    frameDoc.execCommand('insertText', false, text);
  }

  function onKeydown(event) {
    if (autoList(event)) return;
    const mod = event.ctrlKey || event.metaKey;
    if (mod && event.key.toLowerCase() === 's') { event.preventDefault(); save(); return; }
    if (mod && event.key.toLowerCase() === 'k' && frameDoc) { event.preventDefault(); editLink(); return; }
    if (mod && event.altKey && ['0', '2', '3'].includes(event.key) && frameDoc) {
      event.preventDefault();
      frameDoc.execCommand('formatBlock', false, event.key === '0' ? 'p' : `h${event.key}`);
      markDirty();
    }
  }

  function onDoubleClick(event) {
    const img = event.target.closest('img');
    if (!img) return;
    const alt = prompt('그림 설명(alt) - 화면 읽기 프로그램이 읽습니다.', img.alt || '');
    if (alt === null) return;
    img.alt = alt.trim();
    markDirty();
  }

  // ── 목록 - 문단 맨 앞에 '* ' · '- ' 를 치면 글머리 목록, '1. ' 이면 번호 목록 (Notion 과 같음) ──
  const LIST_MARK_RE = /^\s*[*\-•]\s+/;

  // 크롬은 문단 안에서 목록을 만들면 <p><ul>…</ul></p> 로 둔다 - 저장하면 HTML 이 깨지므로 문단 밖으로 꺼낸다.
  function liftLists(root) {
    const doc = root.ownerDocument;
    const selection = doc.getSelection();
    const caret = selection?.rangeCount ? [selection.anchorNode, selection.anchorOffset] : null;
    let moved = false;
    for (const list of [...root.querySelectorAll('p > ul, p > ol')]) {
      const para = list.parentElement;
      const rest = doc.createElement('p');
      while (list.nextSibling) rest.append(list.nextSibling);
      para.after(list);
      if (rest.textContent.trim() || rest.querySelector('img')) list.after(rest);
      if (!para.textContent.trim() && !para.querySelector('img')) para.remove();
      moved = true;
    }
    if (moved && caret && root.contains(caret[0])) {
      const range = doc.createRange();
      range.setStart(caret[0], Math.min(caret[1], caret[0].length ?? caret[0].childNodes.length));
      range.collapse(true);
      selection.removeAllRanges();
      selection.addRange(range);
    }
  }

  // [목록] 단추로 바꾼 문단에 손으로 친 '* ' 가 남아 있으면 지운다.
  function stripListMarks(doc) {
    const selection = doc.getSelection();
    if (!selection?.rangeCount) return;
    const range = selection.getRangeAt(0);
    for (const li of mainOf(doc).querySelectorAll('li')) {
      if (!range.intersectsNode(li)) continue;
      const first = doc.createTreeWalker(li, NodeFilter.SHOW_TEXT).nextNode();
      if (first && LIST_MARK_RE.test(first.data)) first.data = first.data.replace(LIST_MARK_RE, '');
    }
  }

  function autoList(event) {
    if (event.key !== ' ' || event.ctrlKey || event.metaKey || event.altKey) return false;
    if (!frameDoc || event.target?.ownerDocument !== frameDoc) return false;
    const selection = frameDoc.getSelection();
    if (!selection?.isCollapsed || !selection.rangeCount) return false;
    const block = blockAtCaret(frameDoc);
    if (!block || block.tagName !== 'P') return false;
    const marker = frameDoc.createRange();
    marker.setStart(block, 0);
    marker.setEnd(selection.anchorNode, selection.anchorOffset);
    const typed = marker.toString();
    const command = ['*', '-', '•'].includes(typed) ? 'insertUnorderedList' : typed === '1.' ? 'insertOrderedList' : '';
    if (!command) return false;
    event.preventDefault();
    selection.removeAllRanges();
    selection.addRange(marker);
    frameDoc.execCommand('delete');
    frameDoc.execCommand(command);
    liftLists(mainOf(frameDoc));
    markDirty();
    return true;
  }

  // ── 링크 (Ctrl+K) - 늘 새 브라우저 탭에서 열린다 ──────────────────────────────
  const LINK_RE = /^https?:\/\/\S+$/i;
  const decorateLink = a => { a.target = '_blank'; a.rel = 'noopener noreferrer'; };

  function linkAtCaret(doc) {
    const node = doc.getSelection()?.anchorNode;
    const el = node && (node.nodeType === 1 ? node : node.parentElement);
    return el?.closest('main.page a') || null;
  }

  const escapeHtml = text => text.replace(/[&<>"]/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch]));

  // execCommand 로 넣는다 - 그래야 Ctrl+Z 로 되돌릴 수 있다.
  function insertLink(doc, href) {
    // 뒤에 빈칸을 하나 둔다 - 이어 치는 글자가 링크 안으로 들어가지 않게.
    const html = `<a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer">${escapeHtml(href)}</a>&nbsp;`;
    doc.execCommand('insertHTML', false, html);
    // 브라우저가 속성을 떨굴 수 있으니 한 번 더 단다.
    mainOf(doc).querySelectorAll('a').forEach(a => { if (a.getAttribute('href') === href) decorateLink(a); });
  }

  function wrapSelectionInLink(doc, href) {
    doc.execCommand('createLink', false, href);
    mainOf(doc).querySelectorAll('a').forEach(a => { if (a.getAttribute('href') === href) decorateLink(a); });
  }

  function editLink() {
    const doc = frameDoc;
    if (!doc) return;
    const selection = doc.getSelection();
    if (!selection?.rangeCount || !mainOf(doc).contains(selection.anchorNode)) {
      setStatus('링크를 걸 글자를 고르거나 그 자리에 커서를 두세요.', true);
      return;
    }
    const existing = linkAtCaret(doc);
    const range = selection.getRangeAt(0).cloneRange();
    const answer = prompt(existing ? '링크 주소 - 비우면 링크를 풉니다' : '링크 주소 (http:// 또는 https://)', existing?.getAttribute('href') || 'https://');
    if (answer === null) return;
    selection.removeAllRanges();
    selection.addRange(range);
    const href = answer.trim();
    if (!href || href === 'https://') {
      if (existing) { existing.replaceWith(...existing.childNodes); markDirty(); setStatus('링크를 풀었습니다.'); }
      return;
    }
    if (!LINK_RE.test(href)) { setStatus('http:// 또는 https:// 로 시작하는 주소만 걸 수 있습니다.', true); return; }
    if (existing) { existing.href = href; decorateLink(existing); }
    else if (range.collapsed) insertLink(doc, href);
    else wrapSelectionInLink(doc, href);
    markDirty();
    setStatus(`링크를 걸었습니다 · ${href} · 새 탭에서 열립니다.`);
  }

  function attachFrame(doc) {
    frameDoc = doc;
    const main = mainOf(doc);
    main.contentEditable = 'true';
    main.spellcheck = false;
    main.querySelectorAll('figure').forEach(figure => { figure.contentEditable = 'false'; });
    try { doc.execCommand('defaultParagraphSeparator', false, 'p'); } catch { /* 옛 브라우저 */ }
    const frameStyle = doc.createElement('style');
    frameStyle.textContent = `main.page[contenteditable] { outline: none; caret-color: #37352f; }
      main.page[contenteditable] img { cursor: pointer; }
      .guide-uploading { padding: 32px 16px; text-align: center; color: rgba(55,53,47,.65); font-size: 14px; background: #f7f7f5; }
      div.callout > p:last-child, .final > p:last-child, .notice > p:last-child { margin-bottom: 0; }`;
    frameStyle.dataset.guideEditor = '1';
    doc.head.append(frameStyle);
    main.addEventListener('input', markDirty);
    main.addEventListener('paste', onPaste);
    main.addEventListener('dblclick', onDoubleClick);
    doc.addEventListener('keydown', onKeydown);
  }

  // ── 제목 · 요약 (catalog.json) ───────────────────────────────────────────────
  const titleEl = byId('title');
  const summaryEl = byId('summary');
  for (const el of [titleEl, summaryEl]) {
    el.addEventListener('input', () => { if (el.isContentEditable) { catalogDirty = true; markDirty(); } });
    el.addEventListener('keydown', event => { if (event.key === 'Enter' && el.isContentEditable) event.preventDefault(); });
  }

  const catalogPages = () => guide.pages.slice(1).map(entry => ({ ...entry }));

  async function putCatalog(pages) {
    const response = await fetch('/api/guide-editor/catalog', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pages }),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok || !result.ok) throw new Error(result.error || `HTTP ${response.status}`);
    guide.setCatalog(result.catalog.pages);
    return result.catalog;
  }

  function fillCategories() {
    const select = bar.querySelector('[data-category]');
    select.replaceChildren();
    select.append(new Option('(분류 없음 · 맨 위)', '', false, !page?.category));
    const categories = [...new Set(guide.pages.slice(1).map(entry => entry.category).filter(Boolean))];
    for (const category of categories) select.append(new Option(category, category, false, category === page?.category));
    select.append(new Option('새 분류…', '__new__'));
  }

  async function moveInCatalog(step) {
    const pages = catalogPages();
    const index = pages.findIndex(entry => entry.id === page.id);
    let target = index + step;
    while (target >= 0 && target < pages.length && pages[target].category !== page.category) target += step;
    if (index < 0 || target < 0 || target >= pages.length) { setStatus('이 분류의 맨 끝입니다.'); return; }
    [pages[index], pages[target]] = [pages[target], pages[index]];
    try { await putCatalog(pages); setStatus('목차 순서를 저장했습니다.'); } catch (error) { setStatus(`목차를 저장하지 못했습니다: ${error.message}`, true); }
  }

  async function changeCategory(select) {
    let category = select.value;
    if (category === '__new__') {
      category = (prompt('새 분류 이름') || '').trim();
      if (!category) { fillCategories(); return; }
    }
    if (category === page.category) return;
    const pages = catalogPages();
    const index = pages.findIndex(entry => entry.id === page.id);
    const [moved] = pages.splice(index, 1);
    moved.category = category;
    const lastOfCategory = pages.map(entry => entry.category).lastIndexOf(category);
    pages.splice(lastOfCategory >= 0 ? lastOfCategory + 1 : pages.length, 0, moved);
    try {
      await putCatalog(pages);
      page = guide.pages.find(entry => entry.id === moved.id);
      byId('breadcrumb').textContent = ['가이드', page.category, page.title].filter(Boolean).join(' / ');
      fillCategories();
      setStatus(category ? `분류를 '${category}' 로 옮겼습니다.` : '분류 없이 목차 맨 위로 옮겼습니다.');
    } catch (error) {
      fillCategories();
      setStatus(`목차를 저장하지 못했습니다: ${error.message}`, true);
    }
  }

  // ── 저장 · 취소 ──────────────────────────────────────────────────────────────
  async function save() {
    if (!editing || !page?.file || !frameDoc) return;
    if (uploading) { setStatus('그림을 올리는 중입니다. 끝난 뒤 저장하세요.', true); return; }
    const clone = mainOf(frameDoc).cloneNode(true);
    clone.querySelectorAll('[contenteditable]').forEach(el => el.removeAttribute('contenteditable'));
    clone.querySelectorAll('[spellcheck]').forEach(el => el.removeAttribute('spellcheck'));
    clone.querySelectorAll('.guide-uploading').forEach(el => el.remove());
    liftLists(clone);
    clone.querySelectorAll('a[href]').forEach(a => { if (!a.getAttribute('href').startsWith('#')) decorateLink(a); });
    // 문단마다 줄을 바꿔 둔다 - 한 줄로 이어 쓰면 git diff 를 읽을 수 없다.
    for (const parent of [clone, ...clone.querySelectorAll('section, article, .steps, .step-copy, div.callout, .notice, .final, ul, ol')]) {
      for (const child of [...parent.children]) {
        if (child.previousSibling?.nodeType === 1 || (child === parent.firstChild)) child.before('\n');
      }
    }
    setStatus('저장 중…');
    try {
      const response = await fetch(`/api/guide-editor/docs/${encodeURIComponent(page.id)}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ html: clone.innerHTML }),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || !result.ok) throw new Error(result.error || `HTTP ${response.status}`);
      if (catalogDirty) {
        const pages = catalogPages();
        const entry = pages.find(item => item.id === page.id);
        entry.title = titleEl.textContent.trim() || entry.title;
        entry.summary = summaryEl.textContent.trim();
        await putCatalog(pages);
      }
      dirty = false;
      catalogDirty = false;
      guide.reload({ fresh: true });
      setStatus(`저장했습니다 · ${page.file}`);
    } catch (error) {
      setStatus(`저장하지 못했습니다: ${error.message}`, true);
    }
  }

  function cancelEdits() {
    if (dirty && !confirm('저장하지 않은 변경을 버릴까요?')) return;
    dirty = false;
    catalogDirty = false;
    guide.reload({ fresh: true });
    setStatus('변경을 버렸습니다.');
  }

  // ── 새 문서 ──────────────────────────────────────────────────────────────────
  const newDoc = document.createElement('div');
  newDoc.className = 'new-doc';
  newDoc.hidden = true;
  newDoc.innerHTML = `
    <button type="button" data-open>+ 새 문서</button>
    <form hidden>
      <label>제목<input name="title" required maxlength="80" placeholder="와일드카드 기초"></label>
      <label>문서 이름 (주소 · 파일 이름)<input name="id" required maxlength="64" pattern="[a-z0-9][a-z0-9\\-]*" placeholder="wildcard-basics"></label>
      <label>분류 (비우면 맨 위)<input name="category" maxlength="40" list="guideCategories"></label>
      <label>요약<input name="summary" maxlength="300" placeholder="한 줄 설명"></label>
      <datalist id="guideCategories"></datalist>
      <div class="err" role="alert"></div>
      <div class="row"><button type="button" data-close>닫기</button><button type="submit">만들기</button></div>
    </form>`;
  byId('sidebar').append(newDoc);
  const form = newDoc.querySelector('form');
  newDoc.querySelector('[data-open]').addEventListener('click', () => {
    if (dirty && !confirm('저장하지 않은 변경이 있습니다. 버리고 새 문서를 만들까요?')) return;
    const list = newDoc.querySelector('datalist');
    list.replaceChildren(...[...new Set(guide.pages.slice(1).map(entry => entry.category).filter(Boolean))].map(category => new Option(category)));
    form.category.value = page?.category && page.id !== 'welcome' ? page.category : '';
    form.hidden = false;
    form.title.focus();
  });
  newDoc.querySelector('[data-close]').addEventListener('click', () => { form.hidden = true; });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const error = form.querySelector('.err');
    error.textContent = '';
    const payload = Object.fromEntries(new FormData(form));
    try {
      const response = await fetch('/api/guide-editor/docs', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || !result.ok) throw new Error(result.error || `HTTP ${response.status}`);
      dirty = false;
      catalogDirty = false;
      guide.setCatalog(result.catalog.pages);
      form.reset();
      form.hidden = true;
      location.hash = `#${result.id}`;
    } catch (err) {
      error.textContent = err.message;
    }
  });

  // ── 뷰어와 잇기 ──────────────────────────────────────────────────────────────
  guide.beforeLeave = () => {
    if (!dirty) return true;
    if (!confirm('저장하지 않은 변경이 있습니다. 버리고 이동할까요?')) return false;
    dirty = false;
    catalogDirty = false;
    return true;
  };
  window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
  document.addEventListener('keydown', onKeydown);

  guide.onShown = shown => {
    page = shown;
    frameDoc = null;
    if (guide.showHidden !== editing) { guide.showHidden = editing; guide.refreshNavigation(); }
    const editable = editing && !!shown.file;
    toggle.setAttribute('aria-pressed', String(editing));
    toggle.textContent = editing ? '편집 끄기' : '편집';
    bar.hidden = !editable;
    newDoc.hidden = !editing;
    byId('documentFrame').classList.toggle('editing', editable);
    for (const el of [titleEl, summaryEl]) {
      if (editable) el.setAttribute('contenteditable', 'plaintext-only'); else el.removeAttribute('contenteditable');
    }
    if (editable) { summaryEl.hidden = false; fillCategories(); }
    if (editing && !shown.file) setStatus('');
  };
  guide.onFrameReady = (shown, doc) => {
    if (editing && shown === page && shown.file) attachFrame(doc);
  };

  // 편집기는 첫 화면을 그린 뒤에 실린다 - 지금 화면에 다시 붙는다.
  if (editing) guide.reload({ fresh: true }); else guide.onShown(guide.current);
})();
