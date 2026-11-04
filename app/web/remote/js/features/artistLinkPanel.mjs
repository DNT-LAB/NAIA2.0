/**
 * 결과 화면 작가 패널(사용자 지정 2026-11-03).
 *
 * [메인 랜덤 버튼 연결] 이 켜져 있으면 결과 화면 왼쪽 아래(시드 고정 알약 오른쪽)에 **늘** 뜬다.
 * 다루는 작가 = **보이는 그림에 붙은 작가**(히스토리 `linked_artist`). Auto Gen 은 다음 컷을 미리 만들므로
 * '마지막으로 뽑힌 작가' 를 쓰면 엉뚱한 작가를 숨긴다.
 *
 *   [그림 · 이름 × 가중치] [고정] [기억] [숨김] [삽입 ▴] [그룹 ▴]
 *
 * - [× 가중치] = 누르면 위에 손잡이(휠 0.01씩). 바꾸면 **랜덤 작가 가중치**(아티스트 창 손잡이)에 바로 반영한다 -
 *   고정하지 않는다(사용자 지정 2026-11-03 · 처음엔 '그 값으로 고정' 이었다). 고정 중이면 고정 작가도 그 값을 쓴다.
 * - [고정] = 다음 Random 도 이 작가 · 이 가중치. [생성 버튼 → 랜덤 아티스트](상위 정책)를 서버가 **빌려** 끄고,
 *   풀면 돌려준다(`ArtistThumbnailService.link_pin`).
 * - [기억] = 패널 전용 그룹 한 칸(`임시 그룹`) - 와일드카드로 바로 쓰이고 재시작해도 남는다. 이름을 붙이면 저장.
 *   사람이 있으면 [그룹 ▴] 맨 위에 그 칸이 뜨고, 누르면 아티스트 그룹 창으로 연다.
 * - [숨김] = 제외 작가. 고정해 둔 작가를 숨기면 정책이 돌아온다.
 * - [삽입 ▴] = 이 작가를 지금 가중치로 PE Prefix 맨 앞 / Postfix 맨 뒤에(사용자 지정 2026-11-04). 이미 있으면 가중치만
 *   바꾼다. 넣은 작가는 위의 삽입 그룹 판(`artistInsertTray.mjs`)이 추적한다.
 * - [그룹] = 관심 작가 + 저장된 그룹. 누르면 넣고 빼기.
 * ⚠️ 상태는 서버가 주인이다 - 조작 응답과 `artist_random_tools` 알림으로만 그린다(다른 탭 · 아티스트 창과 같은 값).
 */
export function installArtistLinkPanel({
  document, fetch = window.fetch.bind(window), showToast, escHtml,
  openGroupWindow = null,          // (groupId) => 그 그룹을 아티스트 그룹 창으로 연다
  onGroupsChanged = null,          // () => 패널이 그룹을 바꿨다 - 열린 그룹 창이 새로 읽는다
  onInsert = null,                 // ({artist, weight}) => PE Prefix 맨 앞에 넣는다(있으면 가중치만)
}) {
  const el = document.getElementById('artistLinkPanel');
  const seedPill = document.getElementById('seedLockPill');
  if (!el) return null;
  const esc = typeof escHtml === 'function' ? escHtml : (value => String(value ?? '').replace(/[&<>"']/g, c => (
    {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c])));

  let tools = null;          // 서버의 랜덤 도구(main_link · link_pin · pin_hold · focus …)
  let artist = '';           // 보이는 그림의 작가
  let weight = null;
  let info = null;           // GET /api/artist-thumb/link-panel 답(그림 · 숨김 · 임시 · 그룹)
  let infoSeq = 0;
  let busy = false;
  // 보이는 그림이 막 바뀌었고 그 그림의 작가를 아직 모른다 - 그동안 단추는 옛 그림의 작가를 다루므로 막는다(Codex 리뷰 P1).
  let stale = false;
  let assetGen = 0;                // 보이는 그림이 바뀔 때마다 오른다 - 기다린 클릭이 다른 그림에 걸리지 않게
  let refreshTimer = null;

  const menu = document.createElement('div');
  menu.className = 'artist-link-menu';
  menu.hidden = true;
  menu.setAttribute('role', 'menu');
  el.after(menu);

  // 가중치 손잡이 - 칩을 누르면 위에 뜬다. 바꾸면 곧바로 랜덤 작가 가중치가 된다(휠은 손잡이 위에서만 받는다).
  const WEIGHT_MIN = 0, WEIGHT_MAX = 2, WEIGHT_STEP = 0.01;
  const weightPop = document.createElement('div');
  weightPop.className = 'artist-link-weight';
  weightPop.hidden = true;
  weightPop.innerHTML = `
    <div class="alp-weight-head"><span class="alp-weight-who"></span><span class="alp-weight-value"></span></div>
    <input type="range" min="${WEIGHT_MIN}" max="${WEIGHT_MAX}" step="${WEIGHT_STEP}" aria-label="가중치">
    <div class="alp-weight-foot">휠 ${WEIGHT_STEP}씩 · 랜덤 가중치에 바로 반영</div>`;
  menu.after(weightPop);

  // [삽입 ▴] - Prefix 맨 앞 / Postfix 맨 뒤 중 고른다(사용자 지정 2026-11-04). 넣은 작가는 삽입 그룹 판이 추적한다.
  const insertMenu = document.createElement('div');
  insertMenu.className = 'artist-link-menu artist-link-insert';
  insertMenu.hidden = true;
  insertMenu.setAttribute('role', 'menu');
  insertMenu.innerHTML = `
    <button type="button" class="alp-menu-item" data-alp-insert="pre" role="menuitem">Prefix 맨 앞에</button>
    <button type="button" class="alp-menu-item" data-alp-insert="post" role="menuitem">Postfix 맨 뒤에</button>`;
  weightPop.after(insertMenu);
  const weightRange = weightPop.querySelector('input');
  let weightTimer = null;
  let weightSaving = null;         // 도는 중인 가중치 저장(다른 단추는 이것을 기다린다 - busy 에 버려지지 않게)
  let weightTicket = 0;            // 버린 가중치 저장 표(연결이 꺼지면 오른다 - 이미 기다리는 저장도 멈춘다)

  const formatWeight = value => {
    const n = Number(value);
    if (!Number.isFinite(n) || Math.abs(n - 1) < 1e-9) return '';
    return String(Math.round(n * 100) / 100);
  };
  const seedShown = () => Boolean(seedPill && seedPill.offsetParent !== null && seedPill.offsetWidth > 0);
  // 메인 Random 은 늘 뽑는다 - [고정](`link_pin`) 중일 때만 그 작가(`focus`)를 붙인다(사용자 지시 2026-11-03).
  const pinnedHere = () => Boolean(tools && artist && tools.link_pin && tools.focus === artist);
  const weightNumber = () => (Number.isFinite(Number(weight)) && weight !== null ? Number(weight) : 1);
  const weightLabel = () => formatWeight(weightNumber()) || '1';

  function place() {
    if (el.hidden || !seedPill) return;
    el.style.left = `${seedPill.offsetLeft + seedPill.offsetWidth + 6}px`;
    if (!menu.hidden) {
      menu.style.left = `${el.offsetLeft}px`;
    }
    if (!weightPop.hidden) {
      const chip = el.querySelector('[data-alp="weight"]');
      weightPop.style.left = `${el.offsetLeft + (chip ? chip.offsetLeft : 0)}px`;
    }
  }

  function render() {
    const show = Boolean(tools?.main_link) && seedShown();
    el.hidden = !show;
    if (!show) { closeMenu(); closeInsert(); closeWeight({commit: false}); return; }
    if (!artist) {
      el.innerHTML = '<span class="alp-empty" title="이 그림은 메인 Random 이 작가를 붙이지 않았습니다">붙은 작가 없음</span>';
      closeMenu();
      closeInsert();
      closeWeight();
      place();
      return;
    }
    const w = weightLabel();
    const image = info?.artist === artist ? info.image_url : '';
    const pin = pinnedHere();
    const slot = info?.artist === artist ? info.slot : null;
    const banned = info?.artist === artist && info.banned;
    const pinTitle = pin ? '고정 해제 - 다시 무작위로 뽑습니다' : '다음 Random 에도 이 작가를 붙입니다';
    el.innerHTML = `
      <span class="alp-who" title="${esc(artist)} × ${esc(w)}">
        ${image ? `<img class="alp-thumb" src="${esc(image)}" alt="" loading="lazy">`
    : `<span class="alp-thumb alp-thumb-blank" aria-hidden="true">${esc(artist.slice(0, 1).toUpperCase())}</span>`}
        <span class="alp-name">${esc(artist)}</span>
      </span>
      <button type="button" class="alp-weight${weightPop.hidden ? '' : ' is-open'}" data-alp="weight"
        aria-expanded="${!weightPop.hidden}" title="가중치 조절 - 바꾸면 랜덤 작가 가중치에 바로 반영합니다">× ${esc(w)}</button>
      <button type="button" class="alp-btn${pin ? ' is-on' : ''}" data-alp="pin" aria-pressed="${pin}" title="${esc(pinTitle)}">고정</button>
      <button type="button" class="alp-btn${slot?.has ? ' is-on' : ''}" data-alp="slot" aria-pressed="${Boolean(slot?.has)}"
        title="${esc(`${slot?.name || '임시 그룹'} 에${slot?.has ? '서 뺍니다' : ' 담습니다'} - 와일드카드로 쓰이고 재시작해도 남습니다. [그룹 ▴] 에서 열어 이름을 붙이면 저장됩니다.`)}">기억</button>
      <button type="button" class="alp-btn alp-ban${banned ? ' is-on' : ''}" data-alp="ban" aria-pressed="${Boolean(banned)}"
        title="${banned ? '제외 작가에서 뺍니다' : '제외 작가로 - 다음부터 뽑히지 않습니다'}">숨김</button>
      <button type="button" class="alp-btn" data-alp="insert" aria-haspopup="menu" aria-expanded="${!insertMenu.hidden}"
        title="${esc(`× ${w} 로 Prefix 맨 앞 · Postfix 맨 뒤에 넣습니다 - 이미 있으면 가중치만 바꾸고, 위의 삽입 그룹에서 추적합니다`)}">삽입 ▴</button>
      <button type="button" class="alp-btn" data-alp="group" aria-haspopup="menu" aria-expanded="${!menu.hidden}" title="그룹에 담기">그룹 ▴</button>`;
    place();
  }

  async function loadInfo() {
    const seq = ++infoSeq;
    const target = artist;
    try {
      const res = await fetch(`/api/artist-thumb/link-panel?artist=${encodeURIComponent(target)}`, {cache: 'no-store'});
      const data = await res.json().catch(() => ({}));
      if (seq !== infoSeq || !res.ok) return;
      if (data.tools) tools = data.tools;
      info = target ? data : null;
      render();
      if (!menu.hidden) renderMenu();
    } catch (_) { /* 다음 알림 때 다시 */ }
  }

  function scheduleRefresh(delay = 150) {
    if (refreshTimer) clearTimeout(refreshTimer);
    refreshTimer = setTimeout(() => { refreshTimer = null; void loadInfo(); }, delay);
  }

  async function op(name, extra = {}) {
    if (busy || !artist) return null;
    busy = true;
    el.classList.add('is-busy');
    const target = artist;
    try {
      const res = await fetch('/api/artist-thumb/link-panel', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({op: name, artist, weight, ...extra}),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      if (data.tools) tools = data.tools;
      if (artist === target) {
        infoSeq += 1;                                  // 늦게 온 옛 조회가 덮지 않게
        if (data.artist === artist) info = data;
      } else {
        scheduleRefresh();                             // 그사이 그림이 바뀌었다 - 그 그림의 조회는 살려 두고 새로 받는다
      }
      render();
      if (!menu.hidden) renderMenu();
      if (name === 'slot' || name === 'group' || name === 'group_new') onGroupsChanged?.();
      return data;
    } catch (error) {
      showToast?.(error.message || '작가 패널 조작에 실패했습니다.', 'error');
      return null;
    } finally {
      busy = false;
      el.classList.remove('is-busy');
    }
  }

  // ── 그룹 메뉴 ──────────────────────────────────────────────────────────
  function renderMenu() {
    const groups = info?.artist === artist ? (info.groups || []) : [];
    const slot = info?.artist === artist ? info.slot : null;
    // [기억] 칸에 사람이 있으면 맨 위에 - 누르면 그 칸을 아티스트 그룹 창으로 연다(넣고 빼기는 [기억] 단추).
    const slotRow = slot?.id && slot.count > 0 ? `
      <button type="button" class="alp-menu-item alp-menu-slot" data-alp-slot-open="${esc(slot.id)}" role="menuitem"
        title="${esc(slot.name)} 창을 엽니다"><span class="alp-check" aria-hidden="true">${slot.has ? '✓' : ''}</span>
        <span>${esc(slot.name)}</span><span class="alp-menu-count">${Number(slot.count)}명 ↗</span></button>
      <div class="alp-menu-sep" role="separator"></div>` : '';
    menu.innerHTML = `${slotRow}
      ${groups.map(g => `
        <button type="button" class="alp-menu-item${g.has ? ' is-on' : ''}" data-alp-group="${esc(g.id)}" role="menuitemcheckbox"
          aria-checked="${Boolean(g.has)}"><span class="alp-check" aria-hidden="true">${g.has ? '✓' : ''}</span><span>${esc(g.name)}</span></button>`).join('')}
      <div class="alp-menu-sep" role="separator"></div>
      <form class="alp-menu-new" data-alp-new>
        <input type="text" maxlength="40" placeholder="새 그룹 이름" aria-label="새 그룹 이름">
        <button type="submit" class="alp-btn">만들기</button>
      </form>`;
  }

  function openMenu() {
    closeInsert();
    renderMenu();
    menu.hidden = false;
    menu.style.left = `${el.offsetLeft}px`;
    el.querySelector('[data-alp="group"]')?.setAttribute('aria-expanded', 'true');
    void loadInfo();                                   // 그룹 창에서 바뀐 것까지 - 열 때 새로 받는다
  }

  function openInsert(button) {
    closeMenu();
    insertMenu.hidden = false;
    insertMenu.style.left = `${el.offsetLeft + (button ? button.offsetLeft : 0)}px`;
    el.querySelector('[data-alp="insert"]')?.setAttribute('aria-expanded', 'true');
  }

  function closeInsert() {
    if (insertMenu.hidden) return;
    insertMenu.hidden = true;
    el.querySelector('[data-alp="insert"]')?.setAttribute('aria-expanded', 'false');
  }

  function closeMenu() {
    if (menu.hidden) return;
    menu.hidden = true;
    el.querySelector('[data-alp="group"]')?.setAttribute('aria-expanded', 'false');
  }

  // ── 가중치 손잡이 ──────────────────────────────────────────────────────
  function paintWeight() {
    const w = weightLabel();
    const chip = el.querySelector('[data-alp="weight"]');
    if (chip) chip.textContent = `× ${w}`;
    weightPop.querySelector('.alp-weight-who').textContent = artist;
    weightPop.querySelector('.alp-weight-value').textContent = weightNumber().toFixed(2);
  }

  function openWeight() {
    closeMenu();
    weightRange.value = String(weightNumber());
    weightPop.hidden = false;
    paintWeight();
    render();
    weightRange.focus({preventScroll: true});
  }

  /** 손잡이를 닫는다. `commit` = 대기 중인 값을 지금 보낸다(아니면 버린다). 돌려주는 값 = 도는 가중치 저장. */
  function closeWeight({commit = true} = {}) {
    if (!commit) weightTicket += 1;
    if (weightTimer) {
      clearTimeout(weightTimer);
      weightTimer = null;
      if (commit) startWeightCommit();
    }
    if (!weightPop.hidden) {
      weightPop.hidden = true;
      el.querySelector('[data-alp="weight"]')?.classList.remove('is-open');
      el.querySelector('[data-alp="weight"]')?.setAttribute('aria-expanded', 'false');
    }
    return weightSaving || Promise.resolve();
  }

  function startWeightCommit() {
    const saving = commitWeight(artist);
    weightSaving = saving;
    saving.finally(() => { if (weightSaving === saving) weightSaving = null; });
    return saving;
  }

  function setWeight(value) {
    const n = Math.min(WEIGHT_MAX, Math.max(WEIGHT_MIN, Math.round(Number(value) / WEIGHT_STEP) * WEIGHT_STEP));
    if (!Number.isFinite(n)) return;
    weight = Math.round(n * 100) / 100;
    weightRange.value = String(weight);
    paintWeight();
    if (weightTimer) clearTimeout(weightTimer);
    weightTimer = setTimeout(() => { weightTimer = null; startWeightCommit(); }, 150);   // 휠 한 칸마다 쓰지 않게만
  }

  // 바꾼 값을 랜덤 작가 가중치로 보낸다(고정은 건드리지 않는다). 다른 조작이 도는 중이면 끝난 뒤에.
  async function commitWeight(target) {
    const ticket = weightTicket;
    while (busy) await new Promise(resolve => setTimeout(resolve, 80));
    if (ticket !== weightTicket) return;                // 기다리는 사이 연결이 꺼졌다 - 보내지 않는다
    if (!artist || artist !== target) return;          // 기다리는 사이 그림이 바뀌었다 - 옛 손잡이 값은 버린다
    await op('weight');
  }

  // 패널은 결과 뷰어(`.viewer`, draggable) 안에 산다 - 슬라이더 · 단추를 끌면 뷰어 끌기(→ 메타데이터 뷰어)가 시작된다.
  // 자식의 draggable="false" 로는 안 막힌다(dragstart 의 target 이 뷰어다). 누르는 동안만 감싼 끌기를 끈다.
  const holdAncestorDrag = event => {
    const host = event.currentTarget.parentElement?.closest('[draggable="true"]');
    if (!host) return;
    host.draggable = false;
    const restore = () => {
      host.draggable = true;
      window.removeEventListener('pointerup', restore, true);
      window.removeEventListener('pointercancel', restore, true);
    };
    window.addEventListener('pointerup', restore, true);
    window.addEventListener('pointercancel', restore, true);
  };
  for (const node of [el, menu, weightPop, insertMenu]) node.addEventListener('pointerdown', holdAncestorDrag);

  weightRange.addEventListener('input', () => setWeight(weightRange.value));
  weightPop.addEventListener('wheel', event => {
    event.preventDefault();
    setWeight(weightNumber() + (event.deltaY < 0 ? WEIGHT_STEP : -WEIGHT_STEP));
  }, {passive: false});

  el.addEventListener('click', async event => {
    const button = event.target.closest('[data-alp]');
    if (!button || stale) return;
    const action = button.dataset.alp;
    if (action === 'weight') {
      if (weightPop.hidden) openWeight(); else closeWeight();
      return;
    }
    const gen = assetGen;
    await closeWeight();
    if (stale || gen !== assetGen) return;             // 저장을 기다리는 사이 그림이 바뀌었다 - 새 그림의 작가에 걸지 않는다
    if (action === 'group') {
      if (menu.hidden) openMenu(); else closeMenu();
      return;
    }
    if (action === 'pin') {
      const wasPinned = pinnedHere();
      const data = await op(wasPinned ? 'unpin' : 'pin');
      if (data) showToast?.(wasPinned ? '고정을 풀었습니다 - 다시 무작위로 뽑습니다.' : `다음 Random 에도 ${artist} 를 붙입니다.`, 'info');
      return;
    }
    if (action === 'slot') {
      const data = await op('slot');
      if (data?.slot) {
        showToast?.(data.slot.has ? `${data.slot.name} 에 기억했습니다(${data.slot.count}명).` : `${data.slot.name} 에서 뺐습니다.`, 'info');
      }
      return;
    }
    if (action === 'insert') {
      if (insertMenu.hidden) openInsert(button); else closeInsert();
      return;
    }
    if (action === 'ban') {
      const wasBanned = Boolean(info?.artist === artist && info.banned);
      const data = await op(wasBanned ? 'unban' : 'ban');
      if (data) showToast?.(wasBanned ? `${artist} 를 제외 작가에서 뺐습니다.` : `${artist} 를 숨겼습니다 - 다음부터 뽑히지 않습니다.`, 'info');
    }
  });

  menu.addEventListener('click', async event => {
    if (stale) return;
    const slotOpen = event.target.closest('[data-alp-slot-open]');
    if (slotOpen) {
      closeMenu();
      if (openGroupWindow) await openGroupWindow(slotOpen.dataset.alpSlotOpen);
      return;
    }
    const item = event.target.closest('[data-alp-group]');
    if (!item) return;
    const group = (info?.groups || []).find(g => g.id === item.dataset.alpGroup);
    if (!group) return;
    const data = await op('group', {group_id: group.id, add: !group.has});
    if (data) showToast?.(group.has ? `${group.name} 에서 뺐습니다.` : `${group.name} 에 담았습니다.`, 'info');
  });

  menu.addEventListener('submit', async event => {
    const form = event.target.closest('[data-alp-new]');
    if (!form) return;
    event.preventDefault();
    if (stale) return;
    const input = form.querySelector('input');
    const name = String(input?.value || '').trim();
    if (!name) { input?.focus(); return; }
    const data = await op('group_new', {name});
    if (data) showToast?.(`${name} 그룹을 만들어 담았습니다.`, 'info');
  });

  insertMenu.addEventListener('click', async event => {
    const item = event.target.closest('[data-alp-insert]');
    if (!item || stale) return;
    const gen = assetGen;
    closeInsert();
    if (gen !== assetGen) return;
    await onInsert?.({artist, weight: weightNumber(), slot: item.dataset.alpInsert === 'post' ? 'post' : 'pre'});
  });

  document.addEventListener('pointerdown', event => {
    if (el.contains(event.target)) return;
    if (!insertMenu.hidden && !insertMenu.contains(event.target)) closeInsert();
    if (!menu.hidden && !menu.contains(event.target)) closeMenu();
    if (!weightPop.hidden && !weightPop.contains(event.target)) closeWeight();
  }, true);
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    if (!menu.hidden) { closeMenu(); event.stopPropagation(); }
    if (!insertMenu.hidden) { closeInsert(); event.stopPropagation(); }
    if (!weightPop.hidden) { closeWeight(); event.stopPropagation(); }
  }, true);

  // 시드 알약 폭이 바뀌면(고정 켜고 끔 · 시드 번호) 옆자리를 따라간다 - [아티스트 탭 연동됨] 알약과 같은 방식.
  if (seedPill) {
    // 보임이 바뀔 때만 다시 그린다 - 폭만 바뀌면 자리만 옮긴다(그림이 깜박이지 않게).
    const later = () => {
      const show = Boolean(tools?.main_link) && seedShown();
      if (show === el.hidden) render(); else place();
    };
    if (typeof ResizeObserver === 'function') new ResizeObserver(later).observe(seedPill);
    if (typeof MutationObserver === 'function') {
      new MutationObserver(later).observe(seedPill, {attributes: true, childList: true, characterData: true, subtree: true});
    }
  }
  // 앱을 켠 직후 - 연결 상태를 안다(가벼운 조회 · 잠깐 뒤에).
  setTimeout(() => { if (!tools) void loadInfo(); }, 1500);

  return {
    /** 결과 화면에 보이는 그림이 바뀌었다 - 그 그림의 `linked_artist` 를 다룬다. */
    setAsset(asset) {
      const linked = asset && typeof asset === 'object' ? asset.linked_artist : null;
      const next = String(linked?.artist || '').trim();
      const nextWeight = linked && Number.isFinite(Number(linked.weight)) ? Number(linked.weight) : null;
      if (stale) { stale = false; el.classList.remove('is-stale'); }
      if (next === artist && nextWeight === weight) return;
      assetGen += 1;
      closeWeight();                                   // 손잡이로 바꾼 값은 옛 그림의 작가에 먼저 고정한다
      artist = next;
      weight = nextWeight;
      info = null;
      closeMenu();
      render();
      scheduleRefresh(0);
    },
    /** 보이는 그림이 바뀌기 시작했다(그 그림의 작가는 곧 `setAsset` 으로 온다) - 그때까지 단추를 막는다. */
    markStale() {
      assetGen += 1;
      stale = true;
      el.classList.add('is-stale');
      closeMenu();
    },
    /** 서버 알림(`artist_random_tools`) - 아티스트 창 · 다른 탭이 바꾼 고정 · 숨김도 따라간다. */
    receiveTools(next) {
      if (!next || typeof next !== 'object') return;
      tools = next;
      render();
      if (artist) scheduleRefresh();
    },
    refresh: () => loadInfo(),
  };
}
