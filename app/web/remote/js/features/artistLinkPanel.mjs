/**
 * 결과 화면 작가 패널(사용자 지정 2026-11-03).
 *
 * [메인 랜덤 버튼 연결] 이 켜져 있으면 결과 화면 왼쪽 아래(시드 고정 알약 오른쪽)에 **늘** 뜬다.
 * 다루는 작가 = **보이는 그림에 붙은 작가**(히스토리 `linked_artist`). Auto Gen 은 다음 컷을 미리 만들므로
 * '마지막으로 뽑힌 작가' 를 쓰면 엉뚱한 작가를 숨긴다.
 *
 *   [그림 · 이름 × 가중치] [고정] [임시] [숨김] [그룹 ▴]
 *
 * - [고정] = 다음 Random 도 이 작가. [생성 버튼 → 랜덤 아티스트](상위 정책)를 서버가 **빌려** 끄고, 풀면 돌려준다
 *   (`ArtistThumbnailService.link_pin`). 정책이 원래 꺼져 있으면 늘 고정이라 단추는 켜진 채 말만 한다.
 * - [임시] = 패널 전용 그룹 한 칸(`랜덤 임시`) - 와일드카드로 바로 쓰이고 재시작해도 남는다. 이름을 붙이면 저장.
 * - [숨김] = 제외 작가. 고정해 둔 작가를 숨기면 정책이 돌아온다.
 * - [그룹] = 관심 작가 + 저장된 그룹. 누르면 넣고 빼기.
 * ⚠️ 상태는 서버가 주인이다 - 조작 응답과 `artist_random_tools` 알림으로만 그린다(다른 탭 · 아티스트 창과 같은 값).
 */
export function installArtistLinkPanel({document, fetch = window.fetch.bind(window), showToast, escHtml}) {
  const el = document.getElementById('artistLinkPanel');
  const seedPill = document.getElementById('seedLockPill');
  if (!el) return null;
  const esc = typeof escHtml === 'function' ? escHtml : (value => String(value ?? '').replace(/[&<>"']/g, c => (
    {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c])));

  let tools = null;          // 서버의 랜덤 도구(main_link · gen_pick · pin_hold · focus …)
  let artist = '';           // 보이는 그림의 작가
  let weight = null;
  let info = null;           // GET /api/artist-thumb/link-panel 답(그림 · 숨김 · 임시 · 그룹)
  let infoSeq = 0;
  let busy = false;
  let refreshTimer = null;

  const menu = document.createElement('div');
  menu.className = 'artist-link-menu';
  menu.hidden = true;
  menu.setAttribute('role', 'menu');
  el.after(menu);

  const formatWeight = value => {
    const n = Number(value);
    if (!Number.isFinite(n) || Math.abs(n - 1) < 1e-9) return '';
    return String(Math.round(n * 100) / 100);
  };
  const seedShown = () => Boolean(seedPill && seedPill.offsetParent !== null && seedPill.offsetWidth > 0);
  const pinnedHere = () => Boolean(tools && artist && !tools.gen_pick && tools.focus === artist);
  // 정책이 원래 꺼져 있다(빌린 것이 아니다) = 늘 고른 작가가 붙는다.
  const policyFixed = () => pinnedHere() && !tools.pin_hold;

  function place() {
    if (el.hidden || !seedPill) return;
    el.style.left = `${seedPill.offsetLeft + seedPill.offsetWidth + 6}px`;
    if (!menu.hidden) {
      menu.style.left = `${el.offsetLeft}px`;
    }
  }

  function render() {
    const show = Boolean(tools?.main_link) && seedShown();
    el.hidden = !show;
    if (!show) { closeMenu(); return; }
    if (!artist) {
      el.innerHTML = '<span class="alp-empty" title="이 그림은 메인 Random 이 작가를 붙이지 않았습니다">붙은 작가 없음</span>';
      closeMenu();
      place();
      return;
    }
    const w = formatWeight(weight);
    const image = info?.artist === artist ? info.image_url : '';
    const pin = pinnedHere();
    const slot = info?.artist === artist ? info.slot : null;
    const banned = info?.artist === artist && info.banned;
    const pinTitle = policyFixed()
      ? '리모컨의 [생성 버튼 → 랜덤 아티스트] 가 꺼져 있어 늘 이 작가가 붙습니다'
      : (pin ? '고정 해제 - 다시 무작위로 뽑습니다' : '다음 Random 에도 이 작가를 붙입니다');
    el.innerHTML = `
      <span class="alp-who" title="${esc(artist)}${w ? ` × ${esc(w)}` : ''}">
        ${image ? `<img class="alp-thumb" src="${esc(image)}" alt="" loading="lazy">`
    : `<span class="alp-thumb alp-thumb-blank" aria-hidden="true">${esc(artist.slice(0, 1).toUpperCase())}</span>`}
        <span class="alp-name">${esc(artist)}</span>${w ? `<span class="alp-weight">× ${esc(w)}</span>` : ''}
      </span>
      <button type="button" class="alp-btn${pin ? ' is-on' : ''}" data-alp="pin" aria-pressed="${pin}" title="${esc(pinTitle)}">고정</button>
      <button type="button" class="alp-btn${slot?.has ? ' is-on' : ''}" data-alp="slot" aria-pressed="${Boolean(slot?.has)}"
        title="${esc(`${slot?.name || '랜덤 임시'} 에 ${slot?.has ? '서 뺍니다' : '담습니다'} - 와일드카드로 쓰이고 재시작해도 남습니다. 그룹 창에서 이름을 붙이면 저장됩니다.`)}">임시</button>
      <button type="button" class="alp-btn alp-ban${banned ? ' is-on' : ''}" data-alp="ban" aria-pressed="${Boolean(banned)}"
        title="${banned ? '제외 작가에서 뺍니다' : '제외 작가로 - 다음부터 뽑히지 않습니다'}">숨김</button>
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
    try {
      const res = await fetch('/api/artist-thumb/link-panel', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({op: name, artist, weight, ...extra}),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      infoSeq += 1;                                    // 늦게 온 옛 조회가 덮지 않게
      if (data.tools) tools = data.tools;
      if (data.artist === artist) info = data;
      render();
      if (!menu.hidden) renderMenu();
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
    menu.innerHTML = `
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
    renderMenu();
    menu.hidden = false;
    menu.style.left = `${el.offsetLeft}px`;
    el.querySelector('[data-alp="group"]')?.setAttribute('aria-expanded', 'true');
    void loadInfo();                                   // 그룹 창에서 바뀐 것까지 - 열 때 새로 받는다
  }

  function closeMenu() {
    if (menu.hidden) return;
    menu.hidden = true;
    el.querySelector('[data-alp="group"]')?.setAttribute('aria-expanded', 'false');
  }

  el.addEventListener('click', async event => {
    const button = event.target.closest('[data-alp]');
    if (!button) return;
    const action = button.dataset.alp;
    if (action === 'group') {
      if (menu.hidden) openMenu(); else closeMenu();
      return;
    }
    if (action === 'pin') {
      if (policyFixed()) {
        showToast?.('리모컨의 [생성 버튼 → 랜덤 아티스트] 가 꺼져 있어 늘 이 작가가 붙습니다.', 'info');
        return;
      }
      const wasPinned = pinnedHere();
      const data = await op(wasPinned ? 'unpin' : 'pin');
      if (data) showToast?.(wasPinned ? '고정을 풀었습니다 - 다시 무작위로 뽑습니다.' : `다음 Random 에도 ${artist} 를 붙입니다.`, 'info');
      return;
    }
    if (action === 'slot') {
      const data = await op('slot');
      if (data?.slot) {
        showToast?.(data.slot.has ? `${data.slot.name} 에 담았습니다(${data.slot.count}명).` : `${data.slot.name} 에서 뺐습니다.`, 'info');
      }
      return;
    }
    if (action === 'ban') {
      const wasBanned = Boolean(info?.artist === artist && info.banned);
      const data = await op(wasBanned ? 'unban' : 'ban');
      if (data) showToast?.(wasBanned ? `${artist} 를 제외 작가에서 뺐습니다.` : `${artist} 를 숨겼습니다 - 다음부터 뽑히지 않습니다.`, 'info');
    }
  });

  menu.addEventListener('click', async event => {
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
    const input = form.querySelector('input');
    const name = String(input?.value || '').trim();
    if (!name) { input?.focus(); return; }
    const data = await op('group_new', {name});
    if (data) showToast?.(`${name} 그룹을 만들어 담았습니다.`, 'info');
  });

  document.addEventListener('pointerdown', event => {
    if (menu.hidden || menu.contains(event.target) || el.contains(event.target)) return;
    closeMenu();
  }, true);
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !menu.hidden) { closeMenu(); event.stopPropagation(); }
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
      if (next === artist && nextWeight === weight) return;
      artist = next;
      weight = nextWeight;
      info = null;
      closeMenu();
      render();
      scheduleRefresh(0);
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
