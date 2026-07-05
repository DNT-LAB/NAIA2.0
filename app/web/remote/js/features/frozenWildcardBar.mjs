// Frozen wildcard bar — top-left overlay of the Result viewer.
//
// Shows every currently frozen wildcard + character slot from the wildcard
// module's `frozen` state ({locations, legacy, characters}) so the user can
// unfreeze or re-roll them without opening the Payload popup. Purely
// presentational: render(state) is pushed from app.js; clicks fan out through
// the onUnfreeze / onReroll / onUnfreezeAll callbacks (which send the matching
// wildcard module params). Optimistic removal keeps unfreeze snappy; the
// authoritative backend broadcast re-renders on top.
//
// cache-bust marker: 20260705-multichar

const COLLAPSE_KEY = 'naia_frozen_wc_collapsed';
const VALUE_MAX = 64;

export function createFrozenWildcardBar({
  document,
  mount,
  escHtml = defaultEsc,
  onUnfreeze = () => {},
  onReroll = () => {},
  onUnfreezeAll = () => {},
} = {}) {
  if (!mount) return {render: () => {}, destroy: () => {}};

  let lastState = emptyState();
  let collapsed = readCollapsed();

  function emptyState() {
    return {locations: [], legacy: [], characters: []};
  }

  function readCollapsed() {
    try {
      return (mount.ownerDocument?.defaultView || window).localStorage?.getItem(COLLAPSE_KEY) === '1';
    } catch (error) {
      return false;
    }
  }

  function writeCollapsed(value) {
    try {
      (mount.ownerDocument?.defaultView || window).localStorage?.setItem(COLLAPSE_KEY, value ? '1' : '0');
    } catch (error) { /* private mode / storage disabled */ }
  }

  function normalize(state) {
    const src = state && typeof state === 'object' ? state : {};
    return {
      locations: Array.isArray(src.locations) ? src.locations : [],
      legacy: Array.isArray(src.legacy) ? src.legacy : [],
      characters: Array.isArray(src.characters) ? src.characters : [],
    };
  }

  function charComponents(ch) {
    return Array.isArray(ch && ch.components) ? ch.components : [];
  }

  // A character with wildcard components counts as its leaf wildcards; otherwise 1.
  function totalCount(state) {
    const charLeaves = state.characters.reduce(
      (n, ch) => n + (charComponents(ch).length || 1), 0);
    return state.locations.length + state.legacy.length + charLeaves;
  }

  function truncate(text) {
    const str = String(text ?? '');
    return str.length > VALUE_MAX ? str.slice(0, VALUE_MAX - 1) + '…' : str;
  }

  function encPayload(payload) {
    return encodeURIComponent(JSON.stringify(payload || {}));
  }

  function decPayload(value) {
    try {
      return JSON.parse(decodeURIComponent(String(value || '')));
    } catch (error) {
      return {};
    }
  }

  // Simple (location / legacy) rows — each re-picks from the wildcard pool.
  function locItems(state) {
    const items = [];
    state.locations.forEach(loc => {
      const name = String(loc.name || '');
      items.push({
        label: name,
        valueFull: String(loc.value || ''),
        valueText: truncate(loc.value),
        unfreezePayload: {kind: 'location', location: String(loc.location || ''), key: name},
        rerollPayload: {location: String(loc.location || ''), key: name},
      });
    });
    state.legacy.forEach(leg => {
      const name = String(leg.name || '');
      items.push({
        label: name,
        valueFull: String(leg.value || ''),
        valueText: truncate(leg.value),
        unfreezePayload: {name},
        rerollPayload: {key: name},
      });
    });
    return items;
  }

  function actionsHtml({reroll, unfreeze, rerollTitle}) {
    let html = '';
    if (reroll) html += `<button type="button" class="fwc-btn fwc-reroll" data-fwc-reroll="${reroll}" title="${escHtml(rerollTitle || '새로 뽑기')}">🎲</button>`;
    if (unfreeze) html += `<button type="button" class="fwc-btn fwc-unfreeze" data-fwc-unfreeze="${unfreeze}" title="고정 해제">✕</button>`;
    return `<div class="fwc-actions">${html}</div>`;
  }

  function infoHtml(label, value) {
    return `<div class="fwc-info">`
      + `<span class="fwc-name" title="${escHtml(label)}">${escHtml(label)}</span>`
      + `<span class="fwc-val" title="${escHtml(value)}">${escHtml(truncate(value))}</span></div>`;
  }

  function rowHtml(item) {
    return `<div class="fwc-row">${infoHtml(item.label, item.valueFull)}`
      + actionsHtml({
          reroll: item.rerollPayload ? encPayload(item.rerollPayload) : '',
          unfreeze: encPayload(item.unfreezePayload),
          rerollTitle: '새로 뽑기 (고정 유지)',
        })
      + `</div>`;
  }

  // A frozen character with wildcard components → a group: header (whole-character
  // 🎲 reroll-all + ✕ unfreeze) over one sub-row per component, each with its own
  // 🎲 that re-rolls ONLY that wildcard while the siblings stay pinned. A character
  // without components falls back to a single whole-character row.
  function charLabel(ch, index) {
    const raw = ch && ch.slot_label;
    const label = (raw !== undefined && raw !== null && String(raw).trim()) ? String(raw).trim() : String(index + 1);
    return `캐릭터 ${label}`;
  }

  function charBlockHtml(ch, index) {
    const slot = String(ch.slot || '');
    const label = charLabel(ch, index);
    const components = charComponents(ch);
    if (!components.length) {
      return `<div class="fwc-row fwc-row-char">${infoHtml(label, String(ch.prompt || ''))}`
        + actionsHtml({
            reroll: encPayload({kind: 'character', slot}),
            unfreeze: encPayload({kind: 'character', slot}),
            rerollTitle: '캐릭터 새로 뽑기',
          })
        + `</div>`;
    }
    const subRows = components.map(c => {
      const name = String(c.name || '');
      return `<div class="fwc-row fwc-row-sub">${infoHtml(name, String(c.value || ''))}`
        + actionsHtml({
            reroll: encPayload({kind: 'character', slot, key: name}),
            unfreeze: '',
            rerollTitle: '이 와일드카드만 새로 뽑기',
          })
        + `</div>`;
    }).join('');
    return `<div class="fwc-char-group">`
      + `<div class="fwc-char-head"><span class="fwc-char-label">${escHtml(label)}</span>`
      + actionsHtml({
          reroll: encPayload({kind: 'character', slot}),
          unfreeze: encPayload({kind: 'character', slot}),
          rerollTitle: '캐릭터 전체 새로 뽑기',
        })
      + `</div><div class="fwc-char-rows">${subRows}</div></div>`;
  }

  // Every unfreeze payload (locations/legacy leaves + one per character group).
  function allUnfreezePayloads(state) {
    const out = locItems(state).map(item => item.unfreezePayload);
    state.characters.forEach(ch => out.push({kind: 'character', slot: String(ch.slot || '')}));
    return out;
  }

  function paint() {
    const state = lastState;
    const count = totalCount(state);
    if (count === 0) {
      mount.hidden = true;
      mount.innerHTML = '';
      return;
    }
    const listHtml = locItems(state).map(rowHtml).join('')
      + state.characters.map((ch, i) => charBlockHtml(ch, i)).join('');
    mount.hidden = false;
    mount.classList.toggle('collapsed', collapsed);
    mount.innerHTML = `
      <div class="fwc-head">
        <button type="button" class="fwc-toggle" data-fwc-toggle="1" title="${collapsed ? '펼치기' : '접기'}" aria-expanded="${collapsed ? 'false' : 'true'}">
          <span class="fwc-pin">📌</span><span class="fwc-count">${count}</span><span class="fwc-caret">${collapsed ? '▸' : '▾'}</span>
        </button>
        <span class="fwc-title">고정된 와일드카드</span>
        <button type="button" class="fwc-clear" data-fwc-clear="1" title="모두 해제">모두 해제</button>
      </div>
      <div class="fwc-list">${listHtml}</div>`;
  }

  function render(state) {
    lastState = normalize(state);
    paint();
  }

  // Drop an item locally so unfreeze feels instant; the backend broadcast then
  // re-renders authoritatively on top of this.
  function optimisticRemove(payload) {
    const kind = String(payload.kind || '').toLowerCase();
    if (kind === 'character' || payload.slot) {
      const slot = String(payload.slot || '');
      lastState.characters = lastState.characters.filter(ch => String(ch.slot || '') !== slot);
    } else {
      const name = String(payload.key || payload.name || '');
      const location = String(payload.location || '');
      lastState.locations = lastState.locations.filter(
        loc => !(String(loc.name || '') === name && String(loc.location || '') === location));
      if (!location) {
        lastState.legacy = lastState.legacy.filter(leg => String(leg.name || '') !== name);
      }
    }
    paint();
  }

  function onClick(event) {
    const target = event.target;
    if (!target || typeof target.closest !== 'function') return;

    const toggle = target.closest('[data-fwc-toggle]');
    if (toggle) {
      event.stopPropagation();
      collapsed = !collapsed;
      writeCollapsed(collapsed);
      paint();
      return;
    }
    const clearBtn = target.closest('[data-fwc-clear]');
    if (clearBtn) {
      event.stopPropagation();
      const payloads = allUnfreezePayloads(lastState);
      lastState = emptyState();
      paint();
      onUnfreezeAll(payloads);
      return;
    }
    const rerollBtn = target.closest('[data-fwc-reroll]');
    if (rerollBtn) {
      event.stopPropagation();
      rerollBtn.classList.remove('rolling');
      // reflow so the animation restarts on repeated clicks
      void rerollBtn.offsetWidth;
      rerollBtn.classList.add('rolling');
      onReroll(decPayload(rerollBtn.dataset.fwcReroll));
      return;
    }
    const unfreezeBtn = target.closest('[data-fwc-unfreeze]');
    if (unfreezeBtn) {
      event.stopPropagation();
      const payload = decPayload(unfreezeBtn.dataset.fwcUnfreeze);
      optimisticRemove(payload);
      onUnfreeze(payload);
    }
  }

  mount.addEventListener('click', onClick);

  function destroy() {
    mount.removeEventListener('click', onClick);
  }

  return {render, destroy};
}

function defaultEsc(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char]);
}
