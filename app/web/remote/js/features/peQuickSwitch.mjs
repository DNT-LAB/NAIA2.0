/**
 * [NAI] Quick PE - 즐겨찾기한 PE 프리셋으로 바로 바꾸는 판(사용자 지시 2026-10-23).
 *
 *   메인 [프롬프트 엔지니어링] 옆 [Quick] → 단추 **위로** 2단 판:
 *     ┌ NAI5F   2 ┬ 260501 · 수채            − ┐
 *     │ NAI4.5F 1 │ ● 260428                 − │   ● = 지금 프리셋 · 올리면 미니 썸네일
 *     └ ETC     1 ┴────────────────────────────┘
 *
 * - 목록 = PE 상태의 `quick_favorites`(서버가 이름 변경 · 삭제를 따라 고친다 - 여기서는 받은 대로 그린다).
 *   카테고리도 서버가 프리셋의 모델로 매번 정한다(NAI5F · NAI5M · NAI5C · NAI4.5F · NAI4.5C · ETC).
 * - 고르면 그 프리셋으로 바꾸고 닫는다. [−] 는 빼기만 하고 판은 열어 둔다(연달아 뺄 수 있게 - 사용자 결정).
 * - NAI 모드가 아니면 단추를 숨긴다(NAI 프리셋만 다룬다). 단추의 보임은 `body[data-pe-quick-state]` 로 건다 -
 *   런처가 다시 그려도(확장 목록 갱신 등) 상태가 살아 있게.
 */
const DEFAULT_CATEGORIES = ['NAI5F', 'NAI5M', 'NAI5C', 'NAI4.5F', 'NAI4.5C', 'ETC'];

export function createPeQuickSwitch({
  document: doc = document,
  escHtml = value => String(value ?? ''),
  getState = () => null,           // 마지막 PE 상태(module_state prompt_engineering)
  selectPreset = () => {},         // (name) - Quick Preset 콤보와 같은 길
  removeFavorite = () => {},       // (name) - preset_quick_remove
} = {}) {
  let open = false;
  let category = '';
  let pop = null;

  function state() {
    const s = getState();
    return s && typeof s === 'object' ? s : null;
  }

  function isNai(s) {
    return String(s?.api_mode || '').toUpperCase() === 'NAI';
  }

  function favorites(s) {
    return isNai(s) && Array.isArray(s.quick_favorites)
      ? s.quick_favorites.filter(f => f && f.name)
      : [];
  }

  function categories(s) {
    const order = Array.isArray(s?.quick_categories) && s.quick_categories.length ? s.quick_categories : DEFAULT_CATEGORIES;
    const groups = new Map(order.map(key => [String(key), []]));
    favorites(s).forEach(f => {
      const key = groups.has(String(f.category)) ? String(f.category) : 'ETC';
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(f);
    });
    return [...groups].filter(([, items]) => items.length);
  }

  function button() {
    return doc.querySelector('button[data-pe-quick]');
  }

  function paintButton(s) {
    const mode = !isNai(s) ? 'off' : (favorites(s).length ? 'ready' : 'empty');
    if (doc.body.dataset.peQuickState !== mode) doc.body.dataset.peQuickState = mode;
    const btn = button();
    if (btn) btn.setAttribute('aria-expanded', open ? 'true' : 'false');
  }

  function pickCategory(s, groups) {
    if (groups.some(([key]) => key === category)) return category;
    const current = favorites(s).find(f => f.name === s?.preset);
    if (current && groups.some(([key]) => key === current.category)) return current.category;
    return groups[0]?.[0] || '';
  }

  function render() {
    const s = state();
    const btn = button();
    if (!open || !btn) { close(); return; }
    const host = btn.closest('.module-pe-wrap') || btn.parentElement;
    if (!pop || !host.contains(pop)) {
      pop = doc.createElement('div');
      pop.className = 'peq-pop';
      pop.setAttribute('role', 'dialog');
      pop.setAttribute('aria-label', 'Quick PE');
      host.appendChild(pop);
    }
    const groups = categories(s);
    category = pickCategory(s, groups);
    const items = (groups.find(([key]) => key === category) || [, []])[1];
    const current = String(s?.preset || '');
    const html = !groups.length
      ? '<div class="peq-empty">즐겨찾기한 프리셋이 없습니다 — 프롬프트 엔지니어링 창 Prefix Prompt 옆 ☆ 로 등록하세요</div>'
      : `<div class="peq-cats">${groups.map(([key, list]) => `<button type="button" class="peq-cat${key === category ? ' is-sel' : ''}"`
          + ` data-peq-cat="${escHtml(key)}">${escHtml(key)}<span class="peq-n">${list.length}</span></button>`).join('')}</div>`
        + `<div class="peq-items">${items.map(f => `<div class="peq-item${f.name === current ? ' is-cur' : ''}" data-peq-name="${escHtml(f.name)}"`
          + ` data-peq-thumb="${escHtml(f.thumbnail_url || '')}" title="${escHtml(f.name)}">`
          + `<span class="peq-name">${escHtml(f.name)}</span>`
          + `<button type="button" class="peq-rm" data-peq-rm="${escHtml(f.name)}" title="Quick 에서 빼기" aria-label="Quick 에서 빼기">−</button></div>`).join('')}</div>`
        + '<div class="peq-thumb" hidden><img alt=""></div>';
    if (pop._html !== html) { pop._html = html; pop.innerHTML = html; }
    placePop(host);
    paintButton(s);
  }

  /** 판의 왼쪽 = '프롬프트 엔지니어링' 의 마지막 글자('링') 위(사용자 지정 2026-10-23). 글자 폭은 글꼴 · 확대에 따라 달라 잰다. */
  function placePop(host) {
    const label = host.querySelector('.module-primary-btn > span');
    const text = label?.firstChild;
    let left = 0;
    if (text && text.nodeType === 3 && text.length) {
      const range = doc.createRange();
      range.setStart(text, text.length - 1);
      range.setEnd(text, text.length);
      left = range.getBoundingClientRect().left - host.getBoundingClientRect().left;
    }
    const room = doc.documentElement.clientWidth - host.getBoundingClientRect().left - pop.offsetWidth - 8;
    pop.style.left = `${Math.max(0, Math.min(Math.round(left), Math.round(room)))}px`;
  }

  function close() {
    open = false;
    if (pop) { pop.remove(); pop = null; }
    paintButton(state());
  }

  function showThumb(item) {
    const box = pop?.querySelector('.peq-thumb');
    if (!box) return;
    const url = item?.dataset.peqThumb || '';
    if (!url) { box.hidden = true; return; }
    const img = box.querySelector('img');
    if (img.getAttribute('src') !== url) img.setAttribute('src', url);
    box.hidden = false;
  }

  function onClick(event) {
    const btn = event.target.closest('button[data-pe-quick]');
    if (btn) {
      event.preventDefault();
      event.stopPropagation();
      open = !open;
      if (open) render(); else close();
      return;
    }
    if (!pop || !pop.contains(event.target)) return;
    const cat = event.target.closest('[data-peq-cat]');
    if (cat) { category = cat.dataset.peqCat; render(); return; }
    const rm = event.target.closest('[data-peq-rm]');
    if (rm) { removeFavorite(rm.dataset.peqRm); return; }
    const item = event.target.closest('[data-peq-name]');
    if (item) {
      selectPreset(item.dataset.peqName);
      close();
    }
  }

  function onPointerDown(event) {
    if (!open) return;
    if (pop?.contains(event.target) || event.target.closest?.('button[data-pe-quick]')) return;
    close();
  }

  function onKeyDown(event) {
    if (open && event.key === 'Escape') close();
  }

  function onOver(event) {
    if (!pop) return;
    const item = event.target.closest?.('[data-peq-name]');
    showThumb(item && pop.contains(item) ? item : null);
  }

  doc.addEventListener('click', onClick, true);
  doc.addEventListener('pointerdown', onPointerDown, true);
  doc.addEventListener('keydown', onKeyDown);
  doc.addEventListener('pointerover', onOver);

  return {
    /** PE 상태가 바뀔 때마다 - 단추 보임 · 열린 판 다시 그리기. */
    sync() {
      const s = state();
      paintButton(s);
      if (open) {
        if (!isNai(s)) close(); else render();
      }
    },
    close,
  };
}
