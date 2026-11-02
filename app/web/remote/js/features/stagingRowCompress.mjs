/* S 줄 압축 창(사용자 결정 2026-11-02).
 *
 * 펼친 스테이징 줄의 [추가 프롬프트] 줄 오른쪽 = [압축](압축 전) · [압축 관리] [압축 해제](압축한 줄). [압축] · [압축 관리] 를
 * 누르면 S 창 옆에 압축 창이 붙어 뜬다 - 이벤트 맵 압축 판과 같은 구성(기준 축 · 게시물 → 이벤트 · 태그 수 · 빈도 슬라이더 ·
 * 출력 · 살펴보기). 줄 안에 펼치면 판이 줄 목록을 밀어내 불편했다(사용자 지적). 창이 열려 있을 때만 [랜덤 선택] [랜덤+생성]
 * (창에서 고른 압축으로 - 적용 전 시험). [압축 해제] 는 줄의 찾기 조건을 남긴다(S 줄의 찾기는 줄 설정이다).
 * 창이 열린 동안 S 창은 다른 줄로 옮길 수 없다 - 줄마다 등급 · 인원이 달라(위 줄은 E, 아래 줄은 G) 다른 줄 조건으로 고른
 * 축이 섞이면 안 된다(사용자 결정). 막는 쪽은 eventMapStaging.mjs.
 *
 * 저장 모양은 맵과 같다: compress = 기준 축이 **아닌** 갈래 id · compress_cut · compress_output('axes' 일 때만).
 * 수 · 분포는 /api/event-map/sample?hist=1 (맵 판과 같은 물음).
 */
import { createDraggablePanel } from './draggablePanel.mjs?v=20260926-childalign';

const IDS = ['clothing', 'body', 'cast', 'expression', 'action', 'adult', 'scene', 'object', 'situation', 'meta'];
// 서버 갈래 이름(/api/event-map/state groups) - 상태를 못 받았을 때만 쓴다
const LABELS = { clothing: '의상', body: '신체·외형', cast: '인원·구도', expression: '표정', action: '행위·자세', adult: '성적',
  scene: '배경·장소', object: '사물', situation: '상황·상태', meta: '메타·연출' };
const CUT_KEYS = ['min_tags', 'max_tags', 'min_freq', 'max_freq'];
const DRAFT_KEY = 'naia.em.compressAxes';   // 맵 판과 같은 기억({axes, cut}) - 마지막에 고른 기준 축으로 연다
const FREQ_BINS = 32;
const BROWSE_N = 20;

const fmt = n => Number(n || 0).toLocaleString('en-US');
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const axesOf = removed => IDS.filter(id => !removed.includes(id));
const removedOf = axes => IDS.filter(id => !axes.includes(id));
/** 압축이 되는 고름 = 기준 축이 하나 이상, 열 개 전부는 아니다. */
const usable = removed => removed.length > 0 && removed.length < IDS.length;
const cutText = cut => (CUT_KEYS.some(k => cut?.[k] != null) ? CUT_KEYS.map(k => cut?.[k] ?? '').join(',') : '');
function cleanCut(raw) {
  const out = {};
  for (const k of CUT_KEYS) {
    const n = Number(raw?.[k]);
    if (raw?.[k] !== '' && raw?.[k] != null && Number.isInteger(n) && n >= 0) out[k] = n;
  }
  return out;
}
/** '태그 8–22 · 빈도 402–1' - 정한 쪽만. */
export function cutSummary(cut) {
  const part = (name, lo, hi) => (lo == null && hi == null ? '' : `${name} ${lo == null ? '…' : fmt(lo)}–${hi == null ? '…' : fmt(hi)}`);
  return [part('태그', cut?.min_tags, cut?.max_tags), part('빈도', cut?.max_freq, cut?.min_freq)].filter(Boolean).join(' · ');
}

/**
 * getRow(id) = 지금 스테이징 줄 · repaint() = 줄을 다시 그린다 · apply(id, patch) = 줄의 압축을 바꾼다(Promise) ·
 * draw(id, selection, andGenerate) = 판에서 고른 압축으로 랜덤 · getParent() = 살펴보기 창을 붙일 스테이징 창.
 */
export function createRowCompress({ getRow, repaint, apply, draw, getParent, request }) {
  let st = null;          // { id, cond, groups, cut, output, info, error, loadingKey, seq, locked(null = 묻는 중), pinKey }
  let labels = null, labelsAsked = false, timer = 0, win = null;
  let browse = null, browseState = null, browseTimer = 0;

  const label = id => labels?.[id] || LABELS[id] || id;
  async function loadLabels() {
    if (labelsAsked) return;
    labelsAsked = true;
    try {
      const body = await request('/api/event-map/state');
      labels = Object.fromEntries((body.groups || []).map(g => [g.id, g.label]));
      paint();
    } catch { /* 기본 이름 */ }
  }
  const selOf = row => row?.selection || {};
  // 수를 물을 조건(줄의 핀 · 제외 · 등급 · 인원 · 찾기) - 판의 기준 축 · 컷만 바꿔 묻는다
  function params(row, groups, cut, extra = {}) {
    const s = selOf(row);
    const p = { pins: (s.pins || []).join(','), exclude: (s.exclude || []).join(','), ratings: (s.ratings || []).join(','),
      persons: (s.persons || []).join(','), compress: groups.join(','), ...extra };
    if (cutText(cut)) p.compress_cut = cutText(cut);
    if (s.filters?.length) p.filters = JSON.stringify(s.filters);
    return new URLSearchParams(p);
  }
  // 열쇠: 줄의 조건(서버가 바꾸면 다시 센다) + 기준 축 [+ 컷]
  const condKey = row => JSON.stringify([(selOf(row).pins || []), selOf(row).exclude, selOf(row).ratings, selOf(row).persons, selOf(row).filters || []]);
  const baseKey = (row, groups) => `${condKey(row)}|${groups.join(',')}`;
  const fullKey = (row, groups, cut) => `${baseKey(row, groups)}|${cutText(cut)}`;
  const lockedAxes = () => st?.locked || [];
  // 줄에 저장된 압축 - 다른 창이 바꾸면 [다시 압축] 켜짐 · 단추 글자가 달라진다(Codex 리뷰)
  const savedKey = row => JSON.stringify([selOf(row).compress || [], cutText(cleanCut(selOf(row).compress_cut)), selOf(row).compress_output || '']);
  /** 지금 보여야 하는 숫자의 열쇠 - 창에서 고른 기준 축 · 컷. */
  const wantedKey = () => (st ? fullKey(getRow(st.id), st.groups, st.cut) : '');

  function lastDraft() {
    try {
      const saved = JSON.parse(localStorage.getItem(DRAFT_KEY) || 'null');
      const axes = Array.isArray(saved?.axes) ? saved.axes.filter(id => IDS.includes(id)) : [];
      return { groups: removedOf(axes), cut: cleanCut(saved?.cut) };
    } catch { return { groups: IDS.slice(), cut: {} }; }
  }
  function remember() {
    try { localStorage.setItem(DRAFT_KEY, JSON.stringify({ axes: axesOf(st.groups), cut: st.cut })); } catch { /* 이 창에서만 */ }
  }

  function openFor(id) {
    const row = getRow(id);
    if (!row) return;
    const s = selOf(row);
    const from = s.compress?.length ? { groups: s.compress.filter(g => IDS.includes(g)), cut: cleanCut(s.compress_cut) } : lastDraft();
    st = { id, cond: condKey(row), saved: savedKey(row), drawing: false, groups: from.groups, cut: from.cut, output: s.compress_output === 'axes' ? 'axes' : 'full',
      info: null, error: '', loadingKey: '', seq: 0, locked: null, pinKey: '' };
    void loadLabels();
    void loadLocked();
    schedule(0);
    ensureWin().open();
    paint();
    repaint();   // S 창: 이 줄 표시 · 다른 줄 잠금
  }
  /** quiet = S 창을 다시 그리지 않는다(S 창이 그리는 중에 부를 때). */
  function close(quiet = false) {
    if (!st) return;
    st = null;
    clearTimeout(timer);
    browse?.close();
    if (win?.isOpen()) win.close();
    if (!quiet) repaint();
  }
  function ensureWin() {
    if (win) return win;
    win = createDraggablePanel({
      document, window, id: 'stCompressWindow', title: '압축', variant: 'em-overlay em-window st-cmp-window',
      storageKey: 'staging-compress', width: 380, minWidth: 320, maxWidth: 640,
      parentPanel: getParent?.() || null,   // S 창의 자식 - 옆에 붙어 뜬다
      onClose: () => close(),
    });
    win.body.addEventListener('click', event => { if (st) void onClick(event.target, getRow(st.id)); });
    win.body.addEventListener('pointerdown', event => { onPointerDown(event, win.body); });
    win.body.addEventListener('keydown', event => { event.stopPropagation(); onKeyDown(event, win.body); });
    return win;
  }
  /** 창 내용 - 축 · 컷 · 수가 바뀔 때. 키보드로 옮기던 슬라이더 손잡이의 초점을 되돌린다. */
  function paint() {
    if (!st || !win?.isOpen()) return;
    const row = getRow(st.id);
    if (!row) return;
    win.setTitle(`압축 · ${(selOf(row).pins || []).join(', ')}`);
    const a = win.body.contains(document.activeElement) ? document.activeElement.dataset : null;
    win.body.innerHTML = panelHtml(row);
    if (a?.stcSlider) win.body.querySelector(`[data-stc-slider="${a.stcSlider}"][data-stc-edge="${a.stcEdge}"]`)?.focus();
  }
  /** 핀이 든 축 - 판에서 끌 수 없다(맵 판과 같다). 모르는 동안 [압축 적용] 을 막는다. */
  async function loadLocked() {
    const mine = st, row = getRow(st.id), key = (selOf(row).pins || []).join(',');
    let axes = [];
    try {
      const body = await request(`/api/event-map/resolve?${new URLSearchParams({ tags: key })}`);
      axes = IDS.filter(id => (body.items || []).some(item => item.group === id));
    } catch { /* 못 물으면 잠그지 않는다 - 서버는 핀을 늘 남긴다 */ }
    if (st !== mine) return;
    st.locked = axes; st.pinKey = key;
    if (st.groups.some(id => axes.includes(id))) { st.groups = st.groups.filter(id => !axes.includes(id)); changed(0); }
    else paint();
  }
  function changed(delay = 250) {
    remember();
    paint();
    schedule(delay);
    scheduleBrowse(delay);
  }
  function schedule(delay = 250) {
    clearTimeout(timer);
    if (!st || !usable(st.groups)) return;
    const row = getRow(st.id);
    const key = fullKey(row, st.groups, st.cut);
    if (st.info?.key === key || st.loadingKey === key || st.errorKey === key) return;   // 실패한 열쇠는 조건이 바뀔 때까지 다시 묻지 않는다
    timer = setTimeout(async () => {
      if (!st) return;
      const mine = st, seq = ++st.seq, groups = st.groups.slice(), cut = { ...st.cut };
      st.loadingKey = key; st.error = ''; st.errorKey = '';
      try {
        const body = await request(`/api/event-map/sample?${params(row, groups, cut, { n: '1', seed: '1', hist: '1' })}`);
        if (st !== mine || seq !== st.seq) return;
        // 그 사이 이미 센 조건으로 돌아왔으면 그 숫자를 지킨다(A -> B -> A 의 늦은 B 답 - Codex 리뷰)
        if (key === wantedKey() || st.info?.key !== wantedKey()) {
          st.info = { key, base: baseKey(row, groups), posts: body.observed_posts || 0, events: body.events || 0,
            eventsIn: body.events_in || 0, hist: body.hist || {}, freqHist: body.freq_hist || {}, sampled: body.sampled || null };
        }
      } catch (error) {
        if (st !== mine || seq !== st.seq) return;
        st.error = error.message; st.errorKey = key;
      }
      st.loadingKey = '';
      paint();
      if (key !== wantedKey()) schedule(0);   // 지금 조건의 숫자가 없으면 이어서 센다
    }, delay);
  }

  // ── 슬라이더(맵 판 · Quick Filter 압축 창과 같은 .ecw-cut-* 두 손잡이) ─────────────────────
  //   태그 수: 왼쪽 = min_tags · 오른쪽 = max_tags. 빈도(로그 눈금 · 흔함 → 희귀): 왼쪽 = max_freq · 오른쪽 = min_freq.
  //   손잡이를 끝에 두면 null(끝까지).
  function cutInfo() {
    if (!st?.info) return null;
    return st.info.base === baseKey(getRow(st.id), st.groups) ? st.info : null;
  }
  function sliderVals(kind) {
    const info = cutInfo();
    if (!info) return [];
    if (kind === 'freq') return Object.keys(info.freqHist).map(Number).sort((a, b) => b - a);
    const keys = Object.keys(info.hist).map(Number);
    if (!keys.length) return [];
    const vals = [];
    for (let v = Math.min(...keys); v <= Math.max(...keys); v += 1) vals.push(v);
    return vals;
  }
  function edgeIndex(kind, edge, vals = sliderVals(kind)) {
    const last = vals.length - 1, cut = st.cut;
    if (last < 0) return 0;
    if (kind === 'tags') {
      if (edge === 'lo') { const i = cut.min_tags == null ? 0 : vals.findIndex(v => v >= cut.min_tags); return i < 0 ? last : i; }
      if (cut.max_tags == null) return last;
      let i = last;
      while (i > 0 && vals[i] > cut.max_tags) i -= 1;
      return i;
    }
    if (edge === 'lo') { const i = cut.max_freq == null ? 0 : vals.findIndex(v => v <= cut.max_freq); return i < 0 ? last : i; }
    if (cut.min_freq == null) return last;
    let i = last;
    while (i > 0 && vals[i] < cut.min_freq) i -= 1;
    return i;
  }
  function setEdgeIndex(kind, edge, index) {
    const vals = sliderVals(kind);
    const last = vals.length - 1;
    if (last < 0) return;
    let i = Math.max(0, Math.min(last, Math.round(index)));
    if (edge === 'lo') i = Math.min(i, edgeIndex(kind, 'hi', vals)); else i = Math.max(i, edgeIndex(kind, 'lo', vals));
    const key = kind === 'tags' ? (edge === 'lo' ? 'min_tags' : 'max_tags') : (edge === 'lo' ? 'max_freq' : 'min_freq');
    if ((edge === 'lo' && i === 0) || (edge === 'hi' && i === last)) delete st.cut[key]; else st.cut[key] = vals[i];
  }
  function posOf(kind, i, vals = sliderVals(kind)) {
    const last = vals.length - 1;
    if (last <= 0) return 0;
    if (kind !== 'freq') return i / last;
    const top = Math.log(Math.max(1, vals[0]));
    const span = top - Math.log(Math.max(1, vals[last]));
    return span > 0 ? (top - Math.log(Math.max(1, vals[i]))) / span : i / last;
  }
  function sliderHtml(kind) {
    const vals = sliderVals(kind);
    const head = kind === 'freq' ? '빈도' : '태그 수';
    const cls = kind === 'freq' ? 'ecw-cut-one is-freq' : 'ecw-cut-one';
    if (vals.length < 2) return `<div class="${cls}"><div class="ecw-cut-head"><span>${head}</span><span class="ecw-dim">—</span></div></div>`;
    const info = cutInfo();
    const counts = kind === 'freq' ? info.freqHist : info.hist;
    const last = vals.length - 1;
    const lo = edgeIndex(kind, 'lo', vals), hi = edgeIndex(kind, 'hi', vals);
    const pct = i => posOf(kind, i, vals) * 100;
    let cols;
    if (kind === 'freq') {
      const nb = Math.min(vals.length, FREQ_BINS);
      const bins = Array.from({ length: nb }, () => ({ c: 0, a: -1, b: -1 }));
      vals.forEach((v, i) => {
        const bin = bins[Math.min(nb - 1, Math.floor(posOf(kind, i, vals) * nb))];
        bin.c += Number(counts[v]) || 0;
        if (bin.a < 0) bin.a = i;
        bin.b = i;
      });
      cols = bins.map((bin, k) => {
        if (bin.a < 0) { const mid = ((k + 0.5) / nb) * 100; return { c: 0, inn: mid >= pct(lo) && mid <= pct(hi), tip: '' }; }
        const range = bin.a === bin.b ? fmt(vals[bin.a]) : `${fmt(vals[bin.b])}–${fmt(vals[bin.a])}`;
        return { c: bin.c, inn: bin.b >= lo && bin.a <= hi, tip: `이벤트 ${range}개에 나오는 태그 · ${fmt(bin.c)}개` };
      });
    } else {
      cols = vals.map((v, i) => { const c = Number(counts[v]) || 0; return { c, inn: i >= lo && i <= hi, tip: `세는 태그 ${v}개 · ${fmt(c)} 이벤트` }; });
    }
    const top = Math.max(1, ...cols.map(col => col.c));
    const bars = cols.map(col => `<span class="${col.inn ? 'is-in' : ''}" style="height:${col.c ? Math.max(6, Math.round(Math.sqrt(col.c / top) * 100)) : 0}%"${col.tip ? ` title="${col.tip}"` : ''}></span>`).join('');
    const lab = v => (kind === 'freq' ? fmt(v) : String(v));
    const ends = kind === 'freq' ? `<span>흔함 ${lab(vals[0])}</span><span>희귀 ${lab(vals[last])}</span>` : `<span>${vals[0]}</span><span>${vals[last]}</span>`;
    return `<div class="${cls}"><div class="ecw-cut-head"><span>${head}</span><span class="ecw-cut-range">${lab(vals[lo])} – ${lab(vals[hi])}</span></div>`
      + `<div class="ecw-cut-bars">${bars}</div>`
      + `<div class="ecw-cut-track" data-stc-track="${kind}"><div class="ecw-cut-fill" style="left:${pct(lo)}%;right:${100 - pct(hi)}%"></div>`
      + `<div class="ecw-cut-handle" data-stc-slider="${kind}" data-stc-edge="lo" tabindex="0" style="left:${pct(lo)}%"></div>`
      + `<div class="ecw-cut-handle" data-stc-slider="${kind}" data-stc-edge="hi" tabindex="0" style="left:${pct(hi)}%"></div></div>`
      + `<div class="ecw-cut-ends">${ends}</div></div>`;
  }
  const slidersHtml = () => (cutInfo() ? sliderHtml('tags') + sliderHtml('freq') : '');
  /** 끄는 동안은 슬라이더만 다시 그린다(줄 전체를 다시 그리면 손잡이 초점 · 다른 칸이 흔들린다). */
  function paintSliders(root) {
    const el = root?.querySelector('[data-stc-cut]');
    if (!el) return;
    const a = el.contains(document.activeElement) ? document.activeElement.dataset : null;
    el.innerHTML = slidersHtml();
    if (a?.stcSlider) el.querySelector(`[data-stc-slider="${a.stcSlider}"][data-stc-edge="${a.stcEdge}"]`)?.focus();
  }
  function indexAt(root, kind, clientX) {
    const track = root.querySelector(`[data-stc-track="${kind}"]`);
    if (!track) return 0;
    const rect = track.getBoundingClientRect();
    const f = Math.max(0, Math.min(1, (clientX - rect.left) / Math.max(1, rect.width)));
    const vals = sliderVals(kind);
    if (kind !== 'freq') return f * Math.max(0, vals.length - 1);
    let best = 0;
    for (let i = 1; i < vals.length; i += 1) if (Math.abs(posOf(kind, i, vals) - f) < Math.abs(posOf(kind, best, vals) - f)) best = i;
    return best;
  }
  function onPointerDown(event, root) {
    const handle = event.target.closest('[data-stc-edge]');
    if (!handle || !st) return false;
    event.preventDefault();
    handle.focus();
    const kind = handle.dataset.stcSlider, edge = handle.dataset.stcEdge;
    const move = e => { setEdgeIndex(kind, edge, indexAt(root, kind, e.clientX)); paintSliders(root); };
    const up = () => {
      document.removeEventListener('pointermove', move);
      document.removeEventListener('pointerup', up);
      document.removeEventListener('pointercancel', up);
      if (st) changed(0);
    };
    document.addEventListener('pointermove', move);
    document.addEventListener('pointerup', up);
    document.addEventListener('pointercancel', up);
    return true;
  }
  function onKeyDown(event, root) {
    const handle = event.target.closest('[data-stc-edge]');
    if (!handle || !st || (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight')) return false;
    event.preventDefault();
    const kind = handle.dataset.stcSlider, edge = handle.dataset.stcEdge;
    setEdgeIndex(kind, edge, edgeIndex(kind, edge) + (event.key === 'ArrowLeft' ? -1 : 1));
    paintSliders(root);
    changed();
    return true;
  }

  // ── 그리기 ─────────────────────────────────────────────────────────────
  function summary(row) {
    if (!usable(st.groups)) {
      return `<span class="emc-dim">${st.groups.length ? '기준으로 삼을 축을 고르세요' : '축을 전부 고르면 압축이 아닙니다 - 기준에서 뺄 축을 끄세요'}</span>`;
    }
    const info = st.info?.key === fullKey(row, st.groups, st.cut) ? st.info : null;
    if (st.error && !info) return `<span class="emc-err">세지 못했습니다 - ${esc(st.error)}</span>`;
    if (!info) return '<span class="emc-dim">이벤트를 세는 중…</span>';
    const posts = info.sampled ? `${fmt(info.posts)} 중 ${fmt(info.sampled.used)}` : fmt(info.posts);
    const inside = cutText(st.cut) ? ` · 슬라이더 안 <b>${fmt(info.eventsIn)}</b>` : '';
    return `게시물 ${posts} → 이벤트 ${cutText(st.cut) ? fmt(info.events) : `<b>${fmt(info.events)}</b>`}${inside}`;
  }
  /** 같은 압축이면 [다시 압축] 을 끈다. */
  function sameAsRow(row) {
    const s = selOf(row);
    return Boolean(s.compress?.length) && s.compress.join(',') === st.groups.join(',')
      && cutText(cleanCut(s.compress_cut)) === cutText(st.cut) && (s.compress_output === 'axes' ? 'axes' : 'full') === st.output;
  }
  /** [추가 프롬프트] 줄 오른쪽 단추. */
  function buttonsHtml(row) {
    const on = Boolean(selOf(row).compress?.length), editing = st?.id === row.id;
    return on
      ? `<button type="button" class="st-cmp-btn${editing ? ' is-on' : ''}" data-stc-manage aria-expanded="${editing}" title="기준 축 · 슬라이더 · 출력을 바꿉니다">압축 관리${editing ? ' ▸' : ''}</button><button
          type="button" data-stc-release title="압축을 풀고 게시물 단위 랜덤으로 - 찾기 조건은 남습니다">압축 해제</button>`
      : `<button type="button" class="st-cmp-btn${editing ? ' is-on' : ''}" data-stc-manage aria-expanded="${editing}"
          title="기준 축의 태그가 같은 게시물끼리 묶어 이벤트 단위로 뽑습니다">압축${editing ? ' ▸' : ''}</button>`;
  }
  /** 창 내용 - 연 줄의 것. */
  function panelHtml(row) {
    if (st?.id !== row.id) return '';
    const locked = lockedAxes(), on = Boolean(selOf(row).compress?.length), ok = usable(st.groups);
    const grid = IDS.map(id => {
      const axis = !st.groups.includes(id), lock = locked.includes(id);
      return `<button type="button" class="emc-g${axis ? ' is-on' : ''}${lock ? ' is-locked' : ''}" data-stc-g="${id}" aria-pressed="${axis}"
        ${lock ? `aria-disabled="true" title="핀(${esc((selOf(row).pins || []).join(', '))})이 든 축 - 끌 수 없습니다"` : ''}>${esc(label(id))}${lock ? '<span class="emc-lock">핀</span>' : ''}</button>`;
    }).join('');
    const out = `<span class="emc-out" role="group" aria-label="출력"><span class="emc-out-l">출력</span>${[
      ['full', '프롬프트 전체', '이벤트로 묶인 게시물 하나의 태그를 전부 씁니다'],
      ['axes', '선택한 축만', '기준 축의 태그(+ 핀 · 인원)만 씁니다'],
    ].map(([id, text, tip]) => `<button type="button" data-stc-out="${id}" class="${st.output === id ? 'is-on' : ''}"
      aria-pressed="${st.output === id}" title="${tip}">${text}</button>`).join('')}</span>`;
    const browseOn = Boolean(browse?.isOpen());
    const draw = ok && !st.drawing ? '' : 'disabled';
    return `<div class="em-compress-panel st-cmp-panel">
      <div class="emc-hint">기준 축 - 이 축들의 태그가 같은 게시물끼리 이벤트 하나로 묶습니다</div>
      <div class="emc-grid">${grid}</div>
      <div class="emc-sum-row"><div class="emc-sum">${summary(row)}</div><button type="button" data-stc-browse class="${browseOn ? 'is-on' : ''}"
        aria-pressed="${browseOn}" title="랜덤과 같은 규칙으로 뽑은 이벤트를 따로 창에서 봅니다">살펴보기</button></div>
      <div class="ecw-cut emc-cut" data-stc-cut>${slidersHtml()}</div>
      <div class="emc-act"><span class="emc-act-l">${out}</span><span class="emc-act-r"><span class="emc-rand"><button type="button"
        data-stc-random="select" ${draw} title="판에서 고른 압축으로 이벤트 하나를 뽑아 메인 프롬프트에(압축은 아직 적용하지 않습니다)">랜덤 선택</button><button
        type="button" data-stc-random="generate" ${draw} title="랜덤 선택 뒤 바로 Generate">랜덤+생성</button></span><button type="button"
        data-stc-close>닫기</button><button type="button" class="is-primary" data-stc-apply
        ${ok && st.locked !== null && !sameAsRow(row) ? '' : 'disabled'}>${on ? '다시 압축' : '압축 적용'}</button></span></div>
    </div>`;
  }
  /** 판에서 고른 압축(적용 전)을 얹은 줄 조합. */
  const draftSelection = row => ({ ...selOf(row), compress: st.groups.slice(), compress_cut: { ...st.cut },
    ...(st.output === 'axes' ? { compress_output: 'axes' } : { compress_output: undefined }) });

  /** 누른 것이 판 · 압축 단추면 처리하고 true. */
  async function onClick(t, row) {
    if (!row) return false;
    if (t.closest('[data-stc-manage]')) { if (st?.id === row.id) close(); else openFor(row.id); return true; }
    if (t.closest('[data-stc-release]')) {
      if (st?.id === row.id) close();
      await apply(row.id, { compress: [] }, `압축을 풀었습니다 - 랜덤은 게시물 단위${selOf(row).filters?.length ? ' · 찾기 조건은 그대로' : ''}`);
      return true;
    }
    if (st?.id !== row.id) return false;
    const g = t.closest('[data-stc-g]');
    if (g) {
      const id = g.dataset.stcG;
      if (lockedAxes().includes(id)) return true;
      // 칩 켜짐 = 기준 축 = 저장 모양에서 빠진다
      st.groups = st.groups.includes(id) ? st.groups.filter(x => x !== id) : IDS.filter(x => x === id || st.groups.includes(x));
      changed();
      return true;
    }
    const out = t.closest('[data-stc-out]');
    if (out) { st.output = out.dataset.stcOut === 'axes' ? 'axes' : 'full'; paint(); scheduleBrowse(0); return true; }
    if (t.closest('[data-stc-browse]')) { toggleBrowse(); return true; }
    if (t.closest('[data-stc-close]')) { close(); return true; }
    const rnd = t.closest('[data-stc-random]');
    if (rnd && usable(st.groups)) {
      if (st.drawing) return true;   // 창은 S 창의 inert 밖이다 - 겹쳐 뽑지 않게(Codex 리뷰)
      const mine = st;
      mine.drawing = true; paint();
      try { await draw(row.id, draftSelection(row), rnd.dataset.stcRandom === 'generate'); } finally {
        mine.drawing = false;
        if (st === mine) paint();
      }
      return true;
    }
    if (t.closest('[data-stc-apply]') && st.locked !== null && usable(st.groups)) {
      const groups = st.groups.filter(id => !lockedAxes().includes(id));
      if (!usable(groups)) return true;
      const patch = { compress: groups, compress_cut: { ...st.cut }, compress_output: st.output === 'axes' ? 'axes' : '' };
      const msg = `압축 - 기준 ${axesOf(groups).map(label).join(' · ')} · 랜덤은 이벤트 단위`;
      close();
      await apply(row.id, patch, msg);
      return true;
    }
    return t.closest('.st-cmp-panel') != null;
  }
  /** 줄이 사라졌거나(빼기 · 다른 창의 프리셋) 접혔으면 창을 닫는다 - S 창이 그릴 때 부른다.
   *  줄 조건이 바뀌었으면(줄 찾기 · 분할 · 다른 창) 다시 센다. */
  function sync(openRowId) {
    if (!st) return;
    const row = getRow(st.id);
    if (!row || st.id !== openRowId) { close(true); return; }
    const cond = condKey(row), saved = savedKey(row);
    if (cond === st.cond && saved === st.saved) return;
    st.saved = saved;
    if (cond === st.cond) { paint(); return; }   // 저장된 압축만 바뀌었다 - 고르던 것은 두고 단추만
    st.cond = cond;
    paint();
    schedule(0);
    scheduleBrowse(0);
  }

  // ── [살펴보기] 창(맵 판과 같은 모양 · 같은 물음) ───────────────────────────
  function ensureBrowse() {
    if (browse) return browse;
    browse = createDraggablePanel({
      document, window, id: 'stCompressBrowse', title: '압축 살펴보기', variant: 'em-overlay em-window emc-browse-window',
      storageKey: 'staging-compress-browse', width: 460, height: 420, minWidth: 300, minHeight: 200, maxWidth: 1200,
      parentPanel: win || getParent?.() || null, resizable: true,
      onClose: () => { clearTimeout(browseTimer); paint(); },
    });
    browse.body.innerHTML = `<div class="emc-bhead"><span class="emc-bnote"></span><button type="button" data-stc-reroll>다시 뽑기</button></div>
      <div class="emc-blist"></div>`;
    browse.body.addEventListener('click', event => { if (event.target.closest('[data-stc-reroll]')) void drawBrowse(); });
    return browse;
  }
  function toggleBrowse() {
    ensureBrowse();
    if (browse.isOpen()) { browse.close(); return; }
    browse.open();
    paint();
    void drawBrowse();
  }
  function scheduleBrowse(delay = 250) {
    if (!browse?.isOpen()) return;
    clearTimeout(browseTimer);
    browseTimer = setTimeout(() => void drawBrowse(), delay);
  }
  async function drawBrowse() {
    if (!browse?.isOpen() || !st) return;
    clearTimeout(browseTimer);
    const row = getRow(st.id);
    const groups = st.groups.slice(), cut = { ...st.cut }, output = st.output;
    const key = `${fullKey(row, groups, cut)}|${output}|${Date.now()}`;
    browseState = { key, row, groups, cut, output, loading: usable(groups) };
    paintBrowse();
    if (!usable(groups)) return;
    try {
      const body = await request(`/api/event-map/sample?${params(row, groups, cut, { n: String(BROWSE_N),
        seed: String(Date.now() % 1000003), ...(output === 'axes' ? { compress_output: 'axes' } : {}) })}`);
      if (browseState?.key !== key) return;
      browseState = { ...browseState, loading: false, rows: body.samples || [], events: body.events_in ?? body.events };
    } catch (error) {
      if (browseState?.key !== key) return;
      browseState = { ...browseState, loading: false, error: error.message };
    }
    paintBrowse();
  }
  function paintBrowse() {
    if (!browse?.isOpen()) return;
    const pv = browseState || { groups: [], cut: {} };
    const s = selOf(pv.row);
    browse.setTitle(pv.events != null ? `압축 살펴보기 · ${fmt(pv.events)}` : '압축 살펴보기');
    browse.body.querySelector('.emc-bnote').textContent = [(s.pins || []).join(', '),
      usable(pv.groups) ? `기준 ${axesOf(pv.groups).map(label).join(' · ')}` : '', cutSummary(pv.cut),
      usable(pv.groups) ? (pv.output === 'axes' ? '선택한 축만' : '프롬프트 전체') : ''].filter(Boolean).join(' · ');
    browse.body.querySelector('[data-stc-reroll]').disabled = !usable(pv.groups) || Boolean(pv.loading);
    let html;
    if (!usable(pv.groups)) html = '<div class="emc-bmsg">압축 판에서 기준으로 삼을 축을 고르세요</div>';
    else if (pv.loading) html = '<div class="emc-bmsg">뽑는 중…</div>';
    else if (pv.error) html = `<div class="emc-bmsg emc-err">${esc(pv.error)}</div>`;
    else if (!pv.rows.length) html = '<div class="emc-bmsg">슬라이더 안에 이벤트가 없습니다</div>';
    else {
      html = pv.rows.map(r => {
        const off = new Set(r.uncounted || []);
        const tags = r.tags.filter(t => !off.has(t)).map(esc)
          .concat(r.tags.filter(t => off.has(t)).map(t => `<i title="기준 축 밖이거나 빈도 범위 밖 - 태그 수에 세지 않습니다(프롬프트엔 남는다)">${esc(t)}</i>`));
        return `<div class="emc-brow"><span>${tags.join(', ')}</span><b title="이 이벤트로 묶인 게시물">×${fmt(r.event_posts)}</b></div>`;
      }).join('');
    }
    browse.body.querySelector('.emc-blist').innerHTML = html;
  }

  return {
    close, sync, onClick, buttonsHtml, label,
    axesText: removed => axesOf(removed || []).map(label),
    isOpen: () => Boolean(st),
    isOpenFor: id => st?.id === id,
  };
}
