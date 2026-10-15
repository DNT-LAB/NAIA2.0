// PE 디버그 오버레이 - Result 화면 오른쪽 위의 읽기 전용 글 상자(사용자 지시 2026-10-15: PE 개편 3단계).
//
// 동영상 플레이어의 '통계' 창처럼 흰 글자 + 색 글자로, **지금 보이는 그림**이 어떻게 만들어졌는지 보인다:
//   - WC: 와일드카드 전개(Prefix · Main · Postfix · 캐릭터 슬롯마다 '키 → 뽑힌 값', 순차 · 종속 진행)
//   - 단계별 제거 / 추가(파이프라인 로그 - 후처리 단계가 PE 의 걸러내기다)
// 프리뷰(Setting & Preview)와 같은 기능이 아니다 - 누르는 것은 닫기(×)뿐이고, 보호 · 필터 편집은 거기서 한다(결정 D5).
// 계획: docs/PE_WINDOW_REDESIGN_2026_10_15.md §4.
//
// 데이터는 그림마다 이미 저장돼 있다(prompt_context.wildcards · pipeline_trace) - 결과 우클릭의 '파이프라인 로그' ·
// '적용된 와일드카드' 와 같은 데이터, 같은 주소다. 서버는 고치지 않는다.
// 어느 그림인가는 메인 뷰어의 #preview 가 말한다(data-source = current | saved · data-path · src) - 그것을 지켜본다.
// 꺼져 있으면 아무것도 읽지 않는다.

const STORAGE_KEY = 'naia.pe.debugOverlay';
const MAX_WC_ROWS = 8;
const MAX_STAGE_ROWS = 6;
const MAX_TAGS = 8;
const MAX_ADDED_NAMES = 4;
const MAX_VALUE = 80;
// 와일드카드 줄이 따로 보이므로 그 단계의 추가 / 제거(키 -> 값 바꿔치기)는 단계 줄에 다시 적지 않는다.
const SKIP_STAGES = new Set(['wildcard_expand']);
const LOC_LABELS = {prefix: 'Prefix', main: 'Main', postfix: 'Postfix'};
const LOC_ORDER = {prefix: 0, main: 1, postfix: 2, character: 3};

export function createPeDebugOverlay({
  document: doc,
  viewer,
  preview,
  storage = (typeof localStorage !== 'undefined' ? localStorage : null),
  fetchFn = (...args) => fetch(...args),
  escHtml,
  // 켜짐이 바뀌었다 - PE 창의 [디버그] 단추가 눌림 표시를 맞춘다.
  onChange = () => {},
}) {
  let on = false;
  try { on = storage?.getItem(STORAGE_KEY) === '1'; } catch (error) { /* 못 읽으면 꺼진 채로 */ }

  const box = doc.createElement('div');
  box.className = 'pe-dbg';
  box.hidden = true;
  box.setAttribute('aria-live', 'off');
  box.innerHTML = '<div class="pe-dbg-head"><span>PE 디버그</span>'
    + '<button type="button" class="pe-dbg-x" aria-label="PE 디버그 닫기" title="닫기">×</button></div>'
    + '<div class="pe-dbg-body"></div>';
  viewer.appendChild(box);
  const body = box.querySelector('.pe-dbg-body');
  box.querySelector('.pe-dbg-x').addEventListener('click', () => setOn(false));

  let seq = 0;
  let shownKey = '';      // 본문이 지금 그리고 있는 그림
  let pendingKey = '';    // 지금 읽고 있는 그림(답을 기다리는 중)
  let timer = 0;

  /** 지금 보이는 그림의 메타 주소. 없으면(빈 화면 · 생성 중 중간 그림) ''. */
  function currentTarget() {
    if (!preview || !preview.classList.contains('show') || !preview.getAttribute('src')) return null;
    const source = preview.dataset.source || '';
    if (source === 'preview') return {key: 'streaming', url: ''};      // 생성 중 - 결과가 오면 다시 잰다
    let path = source === 'saved' ? String(preview.dataset.path || '') : '';
    if (!path) path = pathFromSrc(preview.getAttribute('src'));
    if (path) {
      const params = new URLSearchParams({path, full: '1'});
      return {key: `path:${path}`, url: `/api/viewer/meta?${params.toString()}`};
    }
    if (source === 'current') return {key: `current:${preview.getAttribute('src')}`, url: '/api/result/metadata'};
    return null;
  }

  /** 사용량 배지 · 모바일 통계 섬 아래에 앉는다(같은 모서리를 쓴다). */
  function place() {
    let top = 10;
    for (const id of ['naiUsagePill', 'statsIsland']) {
      const el = doc.getElementById(id);
      if (!el || el.classList.contains('hidden') || !el.getClientRects().length) continue;
      const rect = el.getBoundingClientRect();
      const host = viewer.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) top = Math.max(top, Math.round(rect.bottom - host.top + 6));
    }
    box.style.top = `${top}px`;
  }

  async function refresh() {
    clearTimeout(timer);
    timer = 0;
    if (!on) return;
    const target = currentTarget();
    if (!target) {
      seq += 1;                                          // 날아오는 답은 버린다 - 보일 그림이 없다
      box.hidden = true;
      shownKey = '';
      pendingKey = '';
      return;
    }
    if (target.key === 'streaming') return;              // 중간 그림 동안은 앞 그림의 것을 둔다
    box.hidden = false;
    place();
    // ⚠️ 이미 그리고 있거나 읽고 있는 그림이면 그대로 둔다. 다른 그림이면 새로 읽는다 - 이때 shownKey 를 비운다:
    //    본문이 '불러오는 중' 으로 바뀌므로 더 이상 그 그림을 그리고 있지 않다. 안 비우면 A -> B(느린 답) -> A 로 돌아올 때
    //    A 로 여겨 조기 반환하고, B 의 늦은 답이 차례 번호를 통과해 A 위에 B 의 기록이 남는다(Codex 리뷰).
    if (target.key === shownKey || target.key === pendingKey) return;
    const mine = ++seq;
    pendingKey = target.key;
    shownKey = '';
    body.innerHTML = '<div class="pe-dbg-dim">불러오는 중…</div>';
    let data = null;
    try {
      const response = await fetchFn(target.url, {cache: 'no-store'});
      data = response.ok ? await response.json() : null;
    } catch (error) {
      data = null;
    }
    if (mine !== seq || !on) return;                     // 그 사이 그림이 바뀌었거나 꺼졌다
    pendingKey = '';
    shownKey = target.key;
    body.innerHTML = renderBody(promptContextOf(data));
    place();
  }

  function schedule() {
    if (!on) return;
    clearTimeout(timer);
    timer = setTimeout(() => { void refresh(); }, 120);
  }

  function setOn(next) {
    next = Boolean(next);
    if (on === next) return;
    on = next;
    try { storage?.setItem(STORAGE_KEY, on ? '1' : '0'); } catch (error) { /* 이번 실행에만 산다 */ }
    if (!on) {
      seq += 1;
      box.hidden = true;
      shownKey = '';
      pendingKey = '';
    } else {
      void refresh();
    }
    onChange(on);
  }

  function renderBody(promptContext) {
    const rows = [...wildcardRows(promptContext.wildcards), ...stageRows(promptContext.pipeline_trace)];
    if (!rows.length) return '<div class="pe-dbg-dim">이 그림에는 PE 기록이 없습니다</div>';
    return rows.join('');
  }

  function row(key, valueHtml) {
    return `<div class="pe-dbg-row"><span class="pe-dbg-k">${escHtml(key)}</span><span class="pe-dbg-v">${valueHtml}</span></div>`;
  }

  function wildcardRows(wildcards) {
    const history = Array.isArray(wildcards?.history) ? wildcards.history : [];
    const state = Array.isArray(wildcards?.state) ? wildcards.state : [];
    const sorted = history.slice().sort((a, b) => (LOC_ORDER[a.location] ?? 9) - (LOC_ORDER[b.location] ?? 9));
    const rows = sorted.slice(0, MAX_WC_ROWS).map((entry, index) => {
      const where = locationLabel(entry);
      const value = `<span class="pe-dbg-dim">${escHtml(where)}</span> ${escHtml(clip(entry.name))} → `
        + `<span class="pe-dbg-wc">${escHtml(clip(entry.value))}</span>`;
      return row(index === 0 ? 'WC' : '', value);
    });
    if (sorted.length > MAX_WC_ROWS) rows.push(row('', `<span class="pe-dbg-dim">… 외 ${sorted.length - MAX_WC_ROWS}</span>`));
    if (state.length) {
      const text = state.slice(0, 4).map(entry => `${escHtml(clip(entry.name, 40))} `
        + `<span class="pe-dbg-wc">${escHtml(String(entry.current))}/${escHtml(String(entry.total))}</span>`
        + (entry.dependent ? ' <span class="pe-dbg-dim">(종속)</span>' : '')).join(' · ');
      rows.push(row(rows.length ? '' : 'WC', `<span class="pe-dbg-dim">순차</span> ${text}`));
    }
    return rows;
  }

  function stageRows(stages) {
    if (!Array.isArray(stages)) return [];
    const rows = [];
    for (const stage of stages) {
      if (!stage || SKIP_STAGES.has(stage.stage)) continue;
      const removed = Array.isArray(stage.removed) ? stage.removed : [];
      const added = Array.isArray(stage.added) ? stage.added : [];
      if (!removed.length && !added.length && !stage.note) continue;
      const parts = [];
      if (removed.length) {
        const count = removed.length + Number(stage.removed_more || 0);
        parts.push(`<span class="pe-dbg-rm">−${count} ${escHtml(tagList(removed, stage.removed_more))}</span>`);
      }
      if (added.length) {
        // 더해진 것은 대개 Prefix · Postfix 가 합쳐진 것이다(후처리 단계 - 수십 개). 개수만 적고, 몇 개뿐일 때만 이름을 적는다.
        const count = added.length + Number(stage.added_more || 0);
        const names = count <= MAX_ADDED_NAMES ? ` ${escHtml(tagList(added, stage.added_more))}` : '';
        parts.push(`<span class="pe-dbg-add">+${count}${names}</span>`);
      }
      if (stage.note) parts.push(`<span class="pe-dbg-dim">${escHtml(clip(stage.note))}</span>`);
      rows.push(row(stageLabel(stage), parts.join(' ')));
      if (rows.length >= MAX_STAGE_ROWS) break;
    }
    return rows;
  }

  // 그림이 바뀌면 다시 읽는다. 앱 안을 고치지 않고 #preview 의 표식만 본다.
  // ⚠️ 그림 주소(src · data-*)가 다시 설정되면 **같은 경로여도** 다시 읽는다 - 그 자리의 파일이 바뀌었을 수 있다(`?v=2` 처럼
  //    주소만 달라지거나 같은 주소를 다시 넣는다 - Codex 리뷰). `class` 만 바뀐 알림은 같은 그림이라 다시 읽지 않는다.
  if (preview && typeof MutationObserver !== 'undefined') {
    new MutationObserver(records => {
      const rerender = !records || records.some(record => record.attributeName !== 'class');
      if (rerender) {
        seq += 1;          // 진행 중인 요청도 바로 무효로 - 그 답이 묶음 대기(120ms) 사이에 와서 옛 기록을 다시 채우지 않게(Codex 리뷰)
        shownKey = '';
        pendingKey = '';
      }
      schedule();
    }).observe(preview, {
      attributes: true, attributeFilter: ['src', 'data-source', 'data-path', 'class'],
    });
  }
  // 화면 폭이 바뀌면(767px 아래에서는 모바일 통계 단추가 같은 모서리에 나타난다) 자리만 다시 잡는다(Codex 리뷰).
  doc.defaultView?.addEventListener?.('resize', () => { if (on && !box.hidden) place(); });
  // 사용량 배지가 나타나거나 사라지면 자리만 다시 잡는다.
  const pill = doc.getElementById('naiUsagePill');
  if (pill && typeof MutationObserver !== 'undefined') {
    new MutationObserver(() => { if (on && !box.hidden) place(); }).observe(pill, {attributes: true, attributeFilter: ['class']});
  }

  if (on) void refresh();

  return {
    el: box,
    isOn: () => on,
    setOn,
    toggle: () => setOn(!on),
    refresh: () => { shownKey = ''; pendingKey = ''; return refresh(); },
  };
}

function promptContextOf(data) {
  const raw = data && typeof data === 'object' && 'raw' in data ? data.raw : data;
  const context = raw && typeof raw === 'object' ? raw.prompt_context : null;
  return context && typeof context === 'object' ? context : {};
}

function pathFromSrc(src) {
  try {
    const url = new URL(src, typeof location !== 'undefined' ? location.href : 'http://localhost/');
    const prefix = '/api/viewer/image/';
    return url.pathname.startsWith(prefix) ? decodeURIComponent(url.pathname.slice(prefix.length)) : '';
  } catch (error) {
    return '';
  }
}

function locationLabel(entry) {
  const loc = entry?.location || '';
  if (loc === 'character') {
    const label = entry.slot_label ?? entry.slot;
    return label != null && label !== '' ? `C${label}` : '캐릭터';
  }
  return LOC_LABELS[loc] || loc || '기타';
}

function stageLabel(stage) {
  // '후처리 (post)' -> '후처리' - 괄호 속 영문 단계 이름은 줄을 길게만 한다.
  return String(stage.label || stage.stage || '').replace(/\s*\([^)]*\)\s*$/, '') || '단계';
}

function clip(value, limit = MAX_VALUE) {
  const text = String(value ?? '').replace(/\s+/g, ' ').trim();
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

function tagList(tags, more = 0) {
  const shown = tags.slice(0, MAX_TAGS).map(tag => clip(tag, 40));
  const rest = tags.length - shown.length + Number(more || 0);
  return shown.join(', ') + (rest > 0 ? ` … 외 ${rest}` : '');
}
