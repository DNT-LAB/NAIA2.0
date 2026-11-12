/* Draft 칩 카드(사용자 결정 2026-11-12) - 포함 · 제외 칩을 누르면 칩 메뉴와 함께 뜨는 태그 카드.
 *
 *  · 모양은 메인 프롬프트의 태그 카드(#tagTooltip · tagAssist.mjs 의 onTagLookupResult)를 따른다 - 클래스도 `.tag-tooltip` 계열을
 *    그대로 달고, Draft 전용 조정만 `.drc-*`. #tagTooltip 요소 · tagAssist 의 코드는 건드리지 않는다(순수 함수만 import).
 *  · 내용(위에서 아래): 머리(태그 · 전체 수 · 갈래 · 한글 설명) → 걸린 것(텍스트 칩만) → 유형별 추천 줄(없으면 옛 related 줄) → RATING.
 *  · 칩마다 '넣으면 남는 게시물 수'(POST /api/event-map/draft/counts). 이름을 먼저 그리고 수는 뒤따라 채운다.
 *    add 칩 = counts[tag](지금 조건에 더하면) · replace 칩(대안) · 걸린 것 칩 = replace[tag] / matched[].count(이 칩을 그것으로 바꾸면).
 *    0 = 흐리게 + 누르지 못한다(is-zero) · 모름(null) = 수 없이 그대로.
 *  · 누르기: add = 누른 칩과 같은 칸에 `*tag` · 포함 칩 카드의 우클릭 = 제외 칸에 `*tag`. replace · 걸린 것 = 새 칩을 넣고 **성공하면**
 *    원래 칩을 지운다(먼저 지우면 넣기가 실패했을 때 칩이 사라진다). 넣거나 바꾼 뒤에는 카드(와 메뉴)를 닫는다 - 수가 낡는다.
 *  · 닫기: 칩 메뉴가 닫힐 때(draftMode 의 closeMenu) · 다른 칩 · Esc · 카드와 메뉴 바깥 pointerdown · Draft 끔 · 칩이 사라짐 ·
 *    조건(derived.cond)이 바뀜. 닫힌 뒤 늦게 온 응답은 그리지 않는다(일련번호 + AbortController).
 *  · 자리 = #tagTooltip 이 뜨는 결과 화면 왼쪽 위. '남은 태그' 창(.drf-win)이 열려 있으면 그 창의 오른쪽.
 */

import { ratingCountsHtml } from './tagAssist.mjs?v=20261107-acset3';
import { normalizePromptTag, recommendRowsHtml } from './tagRecommendRows.mjs?v=20260927-nohint2';

const MAX_COUNT_TAGS = 160;     // 서버 한도(/draft/counts)
const MATCHED_LIMIT = 40;
const REQUEST_TIMEOUT_MS = 30000;
const ZERO_TITLE = '이 조건에서는 남는 게시물이 없습니다';

export function initDraftChipCard({
  esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])),
  fmt = n => (Number.isFinite(n) ? Number(n).toLocaleString('en-US') : ''),
  showToast = () => {},
  isActive = () => false,
  getSnapshot = () => null,      // draftMode 의 마지막 스냅숏
  addChip = async () => { throw new Error('Draft 가 준비되지 않았습니다'); },     // (zone, text) => Promise<data> · 실패는 던진다
  replaceChip = async () => { throw new Error('Draft 가 준비되지 않았습니다'); }, // (id, text) => Promise<data> · 실패는 던진다
  onDone = () => {},             // 넣기 · 바꾸기를 마쳤다 - 칩 메뉴도 닫는다(draftMode 의 closeMenu)
  isMenuTarget = () => false,    // (node) => bool - 칩 메뉴 안인가(바깥 누르기 판정)
} = {}) {
  const card = document.createElement('div');
  card.className = 'tag-tooltip drc-card';
  card.hidden = true;
  card.setAttribute('role', 'dialog');
  card.setAttribute('aria-label', '칩 태그 카드');
  document.body.appendChild(card);

  let cur = null;          // 열린 카드의 칩 {id, zone, text, exact, cond}
  let seq = 0;
  let ctl = null;
  let timer = 0;
  let acting = false;      // 넣기 · 바꾸기가 가는 중 - 연타로 두 번 보내지 않는다

  const condOf = snap => snap?.derived?.cond ?? null;
  function findChip(snap, id) {
    const st = snap?.state || {};
    for (const zone of ['include', 'exclude']) {
      const chip = (st[zone] || []).find(c => c.id === id);
      if (chip) return { zone, chip };
    }
    return null;
  }
  /** 지금 포함 · 제외 칩 중 퍼펙트 칩의 태그 - 추천에서 뺀다(prompt_tags · present). */
  function perfectTags(snap) {
    const st = snap?.state || {};
    return [...(st.include || []), ...(st.exclude || [])].filter(c => c.exact)
      .map(c => String(c.text || '').trim()).filter(Boolean);
  }
  function hitsOf(snap, zone, id) {
    const d = (snap?.derived?.[zone] || []).find(x => x.id === id);
    return Number.isFinite(d?.hits) ? d.hits : null;
  }

  // ---- 열기 · 닫기 ----
  function close() {
    seq++;
    try { ctl?.abort(); } catch (_) {}
    ctl = null;
    clearTimeout(timer);
    timer = 0;
    cur = null;
    acting = false;
    if (card.hidden) return;
    card.hidden = true;
    card.classList.remove('open', 'is-busy');
    card.innerHTML = '';
  }
  function open(_anchor, chip, zone) {
    close();
    if (!isActive() || !chip?.id || (zone !== 'include' && zone !== 'exclude')) return;
    const snap = getSnapshot();
    cur = { id: chip.id, zone, text: String(chip.text || ''), exact: !!chip.exact, cond: condOf(snap) };
    const mine = seq;
    const ac = new AbortController();
    ctl = ac;
    timer = setTimeout(() => { try { ac.abort(); } catch (_) {} }, REQUEST_TIMEOUT_MS);
    card.innerHTML = headHtml(null, snap) + '<div class="drc-wait">불러오는 중…</div>';
    card.hidden = false;
    card.classList.add('open');
    card.scrollTop = 0;
    place();
    void load(mine, ac, snap);
  }

  // ---- 서버 ----
  async function load(mine, ac, snap) {
    const have = perfectTags(snap);
    let m = null;
    try {
      const params = new URLSearchParams({ tag: cur.text, recommend: '1', prompt_tags: have.join(',') });
      const res = await fetch(`/api/tag/lookup?${params}`, { cache: 'no-store', signal: ac.signal });
      m = res.ok ? await res.json().catch(() => null) : null;
    } catch (_) { m = null; }
    if (mine !== seq || !cur) return;
    paint(m && m.tag ? m : null, snap, have);
    const tags = candidateTags();
    if (!tags.length && cur.exact) return;     // 셀 것이 없다(텍스트 칩은 걸린 것을 받으러 간다)
    let data = null;
    try {
      const res = await fetch('/api/event-map/draft/counts', {
        method: 'POST', cache: 'no-store', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tags, zone: cur.zone, id: cur.id }), signal: ac.signal,
      });
      data = await res.json().catch(() => null);
      if (!res.ok || !data || data.ok === false) data = null;
    } catch (_) { data = null; }
    if (mine !== seq || !cur || !data) return;
    // 옛 조건의 수는 버린다 - 지금 스냅숏의 조건 지문과 같을 때만
    const nowCond = condOf(getSnapshot());
    if (data.cond != null && nowCond != null && data.cond !== nowCond) return;
    applyCounts(data);
  }

  // ---- 그리기 ----
  function headHtml(m, snap) {
    if (m) {
      const group = [m.group, m.subgroup].filter(Boolean).join(' / ');
      return '<div class="tag-tooltip-main">'
        + `<span class="tag-tooltip-tag">${esc(m.tag)}</span>`
        + `<span class="tag-tooltip-count">${esc(fmt(Number(m.count) || 0))}</span>`
        + (group ? ` <span class="tag-tooltip-group">${esc(group)}</span>` : '')
        + (cur.exact ? '' : hitsHtml(hitsOf(snap, cur.zone, cur.id)))
        + (m.desc ? `<span class="tag-tooltip-desc">${esc(m.desc)}</span>` : '')
        + '</div>';
    }
    // 사전에 없다(또는 아직 모른다) - 칩의 글만. 텍스트 칩은 ≈N태그.
    return '<div class="tag-tooltip-main">'
      + `<span class="tag-tooltip-tag">${esc((cur.exact ? '*' : '') + cur.text)}</span>`
      + (cur.exact ? '' : hitsHtml(hitsOf(snap, cur.zone, cur.id)))
      + '</div>';
  }
  function hitsHtml(n) {
    return `<span class="drc-hits" data-drc-hits title="이름에 이 글이 든 태그를 함께 셉니다">${n == null ? '' : `≈${esc(fmt(n))}태그`}</span>`;
  }
  /** tagAssist 의 renderTooltipExtraTag 와 같은 꼴의 칩. 설명은 title(앱이 커스텀 툴팁으로 옮긴다). */
  function chipHtml(tag, infoMap, extraClass = '', extraAttrs = '') {
    const text = String(tag || '');
    const info = infoMap ? (infoMap[text] || infoMap[text.toLowerCase()] || null) : null;
    const desc = info?.desc || '';
    const classes = ['tag-tooltip-extra-tag'];
    if (extraClass) classes.push(extraClass);
    if (desc) classes.push('has-hover-info');
    return `<span class="${classes.join(' ')}" data-insert="${esc(text)}"${extraAttrs ? ` ${extraAttrs}` : ''}`
      + `${desc ? ` title="${esc(desc)}"` : ''}>${esc(text)}</span>`;
  }
  function paint(m, snap, have) {
    let html = headHtml(m, snap);
    // 걸린 것 줄 자리(텍스트 칩만) - 수 응답이 오면 채운다. 비어 있으면 `.tag-tooltip-extra:empty` 가 숨긴다.
    if (!cur.exact) html += '<div class="tag-tooltip-extra drc-matched" data-drc-matched></div>';
    if (m) {
      const info = m.extra_tag_info || {};
      const present = new Set(have.map(normalizePromptTag).filter(Boolean));
      const reco = Array.isArray(m.recommend?.groups)
        ? recommendRowsHtml(m.recommend.groups, {
          present, current: m.tag, fill: m.recommend?.fill,
          renderChip: (t, cls, attrs) => chipHtml(t, info, cls, attrs),
        })
        : '';
      if (reco) html += reco;
      else if (Array.isArray(m.related) && m.related.length) {
        html += '<div class="tag-tooltip-extra"><span class="tag-tooltip-extra-label">related</span>'
          + m.related.map(t => chipHtml(t, info, '', 'data-op="add"')).join('') + '</div>';
      }
      html += ratingCountsHtml(m.rating_counts, fmt);
    } else if (cur.exact) {
      html += '<div class="drc-wait">사전에 정보가 없는 태그입니다</div>';
    }
    card.innerHTML = html;
    place();
  }
  /** 수를 셀 칩의 태그(중복 없이 · 서버 한도까지). [모두 넣기] 는 여러 태그라 세지 않는다. */
  function candidateTags() {
    const out = [];
    const seen = new Set();
    card.querySelectorAll('[data-insert]').forEach(el => {
      if (el.classList.contains('reco-fill-all') || el.hasAttribute('data-drc-match')) return;
      const tag = el.dataset.insert;
      if (!tag || seen.has(tag) || out.length >= MAX_COUNT_TAGS) return;
      seen.add(tag);
      out.push(tag);
    });
    return out;
  }
  function setCount(el, n) {
    el.querySelector('.drc-n')?.remove();
    el.classList.remove('is-zero');
    el.removeAttribute('aria-disabled');
    if (n === null) { el.dataset.drcN = 'none'; return; }   // 맵에 없다 - 수 없이 그대로
    if (!Number.isFinite(n)) return;
    el.dataset.drcN = String(n);
    const span = document.createElement('span');
    span.className = 'drc-n';
    span.textContent = fmt(n);
    el.appendChild(span);
    if (n === 0) {
      el.classList.add('is-zero');
      el.setAttribute('aria-disabled', 'true');
      el.title = ZERO_TITLE;
    }
  }
  function applyCounts(data) {
    // 걸린 것(텍스트 칩) - 누르면 이 칩을 그 태그 하나의 퍼펙트 칩으로 바꾼다
    const slot = card.querySelector('[data-drc-matched]');
    if (slot && Array.isArray(data.matched) && data.matched.length) {
      const rows = data.matched.slice(0, MATCHED_LIMIT);
      const total = Number(data.matched_total);
      const more = Number.isFinite(total) && total > rows.length
        ? `<span class="drc-more">+${esc(fmt(total - rows.length))}</span>` : '';
      slot.innerHTML = '<span class="tag-tooltip-extra-label">걸린 것</span>'
        + rows.map(r => chipHtml(r.tag, null, 'is-replace', 'data-op="replace" data-drc-match')).join('') + more;
      slot.querySelectorAll('[data-drc-match]').forEach((el, i) => {
        const n = rows[i]?.count;
        setCount(el, n === null ? null : Number(n));
      });
    }
    const hits = card.querySelector('[data-drc-hits]');
    if (hits && Number.isFinite(Number(data.matched_total)) && data.matched_total != null) {
      hits.textContent = `≈${fmt(Number(data.matched_total))}태그`;
    }
    const pick = (map, tag) => (map && Object.prototype.hasOwnProperty.call(map, tag) ? map[tag] : undefined);
    card.querySelectorAll('[data-insert]').forEach(el => {
      if (el.classList.contains('reco-fill-all') || el.hasAttribute('data-drc-match')) return;
      const tag = el.dataset.insert;
      const n = el.dataset.op === 'replace' ? pick(data.replace, tag) : pick(data.counts, tag);
      if (n === undefined) return;
      setCount(el, n === null ? null : Number(n));
    });
    place();
  }

  // ---- 자리: #tagTooltip 의 PC 자리(결과 화면 왼쪽 위 · 탭 줄 아래). '남은 태그' 창이 열려 있으면 그 오른쪽 ----
  function place() {
    if (card.hidden) return;
    const vw = window.innerWidth, vh = window.innerHeight;
    const gap = 10, side = 22;
    const tab = document.querySelector('.right-tab-bar')?.getBoundingClientRect();
    const top = Math.max(gap, tab && tab.height ? tab.bottom + gap : 44);
    let left, maxWidth;
    if (vw < 768) {
      left = 8;
      maxWidth = vw - 16;
    } else {
      const viewer = document.querySelector('.viewer-wrapper')?.getBoundingClientRect();
      const hasViewer = !!(viewer && viewer.width > 0);
      left = hasViewer ? viewer.left + side : 494;
      const finder = document.querySelector('.drf-win');
      if (finder && !finder.hidden) {
        const f = finder.getBoundingClientRect();
        if (f.width > 0) left = Math.max(left, f.right + 12);
      }
      left = Math.max(gap, Math.min(left, vw - 320 - gap));
      const right = hasViewer ? Math.min(viewer.right - side, vw - gap) : vw - gap;
      maxWidth = Math.max(280, Math.min(680, right - left, vw - gap - left));
    }
    card.style.left = `${Math.round(left)}px`;
    card.style.top = `${Math.round(top)}px`;
    card.style.maxWidth = `${Math.round(maxWidth)}px`;
    card.style.maxHeight = `${Math.round(Math.max(180, vh - top - gap))}px`;
  }
  window.addEventListener('resize', place);

  // ---- 넣기 · 바꾸기 ----
  async function act(el, intoZone) {
    if (!cur || acting) return;
    if (el.classList.contains('is-zero')) return;
    const { id, zone } = cur;
    const replace = intoZone === zone && el.dataset.op === 'replace';
    const tags = String(el.dataset.insert || '').split(',').map(t => t.trim()).filter(Boolean);
    if (!tags.length) return;
    if (replace && el.dataset.drcN === 'none') {
      // 맵에 없는 태그로 바꾸면 그 글은 Extra 로 가고 원래 칩만 사라진다 - 막는다
      showToast('이벤트 맵에 없는 태그라 이 칩을 바꿀 수 없습니다', 'warning');
      return;
    }
    acting = true;
    card.classList.add('is-busy');
    let changed = false;
    try {
      if (replace) {
        // 바꾸기는 서버의 한 요청이다(op replace). 넣고 → 지우는 두 요청으로 하면 사이가 끊길 때 두 칩이 남거나 둘 다
        // 사라졌고, 기다리는 사이 카드가 바뀌면 남의 칩을 되살리려 했다(Codex 리뷰 2026-11-12 5차). 실패하면 판은 그대로다.
        try {
          await replaceChip(id, `*${tags[0]}`);
          changed = true;
        } catch (error) {
          showToast(error?.message || '칩을 바꾸지 못했습니다', 'warning');
        }
        return;
      }
      for (const tag of tags) {
        let data;
        try { data = await addChip(intoZone, `*${tag}`); }
        catch (error) { showToast(error?.message || '칩을 넣지 못했습니다', 'warning'); return; }
        changed = true;
        if (data?.routed === 'extra') showToast(`'${tag}' 은(는) 이벤트 맵에 없어 Extra 로 보냈습니다`, 'info');
      }
    } finally {
      acting = false;
      card.classList.remove('is-busy');
      // 조건이 바뀌었다(수가 낡는다 · 원래 칩이 없어졌을 수 있다) - 카드와 메뉴를 닫는다
      if (changed) { close(); onDone(); }
    }
  }

  // ---- 손 ----
  // 칩 · 단추를 눌러도 초점은 그대로(판의 입력칸 등)
  card.addEventListener('mousedown', event => {
    if (event.target.closest?.('[data-insert], [data-reco-tab]')) event.preventDefault();
  });
  card.addEventListener('click', event => {
    const tabBtn = event.target.closest('[data-reco-tab]');
    if (tabBtn) {
      // tagAssist 와 같다 - 누른 유형의 칸만 연다 · 다시 누르면 접는다
      event.preventDefault();
      const box = tabBtn.closest('.tag-reco');
      if (!box) return;
      const openIt = !tabBtn.classList.contains('is-active');
      const key = tabBtn.dataset.recoTab;
      box.querySelectorAll('[data-reco-tab]').forEach(t => t.classList.toggle('is-active', openIt && t === tabBtn));
      box.querySelectorAll('[data-reco-panel]').forEach(p => p.classList.toggle('is-open', openIt && p.dataset.recoPanel === key));
      place();
      return;
    }
    const chip = event.target.closest('[data-insert]');
    if (chip && cur) void act(chip, cur.zone);
  });
  card.addEventListener('contextmenu', event => {
    // 포함 칩의 카드에서만 - 제외 칸에 넣는다. 제외 칩의 카드는 우클릭 동작이 없다.
    const chip = event.target.closest('[data-insert]');
    if (!chip || !cur || cur.zone !== 'include') return;
    event.preventDefault();
    void act(chip, 'exclude');
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !card.hidden && !event.isComposing) close();
  });
  document.addEventListener('pointerdown', event => {
    if (card.hidden) return;
    const t = event.target;
    if (card.contains(t) || isMenuTarget(t)) return;
    close();
  }, true);

  /** draftMode 가 스냅숏을 받을 때마다 부른다. */
  function sync(snap) {
    if (card.hidden && !cur) return;
    if (!snap?.state?.active || !cur) { close(); return; }
    const found = findChip(snap, cur.id);
    if (!found || found.zone !== cur.zone) { close(); return; }
    const cond = condOf(snap);
    if (cur.cond != null && cond != null && cond !== cur.cond) close();
  }

  return {
    open, close, sync, place,
    isOpen: () => !card.hidden,
    contains: node => !!node && card.contains(node),
  };
}
