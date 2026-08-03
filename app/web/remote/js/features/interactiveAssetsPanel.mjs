// Interactive Assets — 조합 스냅샷 컨트롤 패널.
//
// 결과 영역 좌하단(Generation Info 바로 위)에 붙는 가로 바다. Interactive 모드일
// 때만 보인다. 스냅샷은 **생성할 때** 남는다(app.js 가 record 를 부른다) — 만들다 만
// 조합으로 목록이 더러워지지 않게.
//
// 백엔드 계약(app/backend/server/interactive_assets_routes.py):
//   GET  /api/interactive-assets/snapshots?query=&origin=&favorite=&limit=
//   GET  /api/interactive-assets/snapshot?id=          조합 본문
//   GET  /api/interactive-assets/snapshot/thumb?id=    384px WEBP
//   POST /api/interactive-assets/snapshot   {chars}    기록(직전과 같으면 시각만 갱신)
//   POST /api/interactive-assets/favorite   {type,ref,label}
export function createInteractiveAssetsPanel({
  document,
  escHtml,
  showToast,
  showAppDialog,     // 삭제 확인용
  getPanel,          // () => interactivePanel (복원 대상)
}) {
  const root = document.getElementById('interactiveAssets');
  if (!root) return null;

  const LIMIT = 60;
  let open = false;          // 목록 펼침
  let visible = false;       // Interactive 모드 여부
  let busy = false;
  let rows = [];
  let origin = '';           // '' | 'original' | 'known'
  let favoriteOnly = false;
  let query = '';
  let searchTimer = null;
  let loadSeq = 0;           // 늦게 도착한 응답이 최신 목록을 덮지 않게
  let roster = [];           // 캐릭터 스택(패널이 알려 준다)
  // 조합을 꽂을 대상 슬롯. **기본 0(C1)** — 항상 대상이 있어야 칩 클릭이 바로 먹는다.
  let targetSlot = 0;
  let expandedId = '';       // 캐릭터 칩을 펼친 카드

  /** 삭제 확인. 다이얼로그를 못 받았으면 막는다 — 조용히 지우는 것보다 안 지우는 게 낫다. */
  async function confirmDelete(label) {
    if (typeof showAppDialog !== 'function') return false;
    return showAppDialog('', {
      title: '조합 삭제',
      messageHtml: `${escHtml(label || '이 조합')}<br>${escHtml('되돌릴 수 없습니다.')}`,
      okText: '삭제', cancelText: '취소',
    });
  }

  // ------------------------------------------------------------------ 통신

  async function fetchList() {
    const seq = ++loadSeq;
    const qs = new URLSearchParams({limit: String(LIMIT)});
    if (query) qs.set('query', query);
    if (origin) qs.set('origin', origin);
    if (favoriteOnly) qs.set('favorite', 'true');
    try {
      const r = await fetch('/api/interactive-assets/snapshots?' + qs.toString());
      const d = await r.json();
      if (seq !== loadSeq) return;              // 더 새로운 요청이 있다
      if (!r.ok) throw new Error(d.error || '목록을 불러오지 못했습니다');
      rows = Array.isArray(d.snapshots) ? d.snapshots : [];
    } catch (err) {
      if (seq !== loadSeq) return;
      rows = [];
      showToast('Assets 목록 실패: ' + err.message, 'error');
    }
    renderGrid();
  }

  /** 생성 직전에 부른다. 스냅샷 id 를 돌려주면 app.js 가 생성 요청에 실어,
   *  백엔드가 결과 이미지로 384px 썸네일을 붙인다. 실패해도 생성은 진행한다. */
  async function record(chars) {
    if (!Array.isArray(chars) || !chars.length) return '';
    try {
      const r = await fetch('/api/interactive-assets/snapshot', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({chars}),
      });
      const d = await r.json();
      if (!r.ok || !d.snapshot) return '';
      return String(d.snapshot.id || '');
    } catch (_) {
      return '';   // 조합 기록 실패가 생성을 막으면 안 된다
    }
  }

  async function toggleFavorite(id, label) {
    try {
      const r = await fetch('/api/interactive-assets/favorite', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({type: 'snapshot', ref: id, label: label || ''}),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || '즐겨찾기 실패');
      const row = rows.find(x => x.id === id);
      if (row) row.favorite = !!d.on;
      // 즐겨찾기만 보는 중이라면 해제된 항목은 목록에서 빠져야 한다.
      if (favoriteOnly && !d.on) rows = rows.filter(x => x.id !== id);
      renderGrid();
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  async function remove(id) {
    const row = rows.find(x => x.id === id);
    const label = row ? row.summary : '';
    // 되돌릴 수 없으니 한 번 묻는다. 조합은 다시 만들 수 있지만 썸네일은 그 그림뿐이다.
    const ok = await confirmDelete(label);
    if (!ok) return;
    try {
      const r = await fetch('/api/interactive-assets/snapshot/delete', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({id}),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || '삭제 실패');
      rows = rows.filter(x => x.id !== id);
      renderGrid();                      // 먼저 화면에서 치워 반응을 즉시 보여 주고
      showToast(d.removed ? '조합 삭제' : '이미 없는 조합입니다', d.removed ? 'success' : 'info');
      // 다시 읽는다 — 목록은 LIMIT 개만 가져오므로 지운 만큼 뒤에서 채워져야 한다.
      // removed 여부와 무관하다: 이미 로컬 행을 뺐으므로 어느 쪽이든 서버와 맞춰야 한다
      // (다른 탭이 먼저 지웠으면 removed=false 인데 화면만 한 칸 줄어든 채 남는다).
      fetchList();
    } catch (err) {
      showToast('삭제 실패: ' + err.message, 'error');
    }
  }

  /** 카드 안의 캐릭터 칩 하나를 대상 슬롯에 꽂는다(빠른 스왑).
   *  본문은 목록에 없으므로 그때 읽는다 — 캐시하지 않는다(조합은 갱신될 수 있다). */
  async function swapInto(id, charIndex) {
    if (busy) return;
    busy = true;
    renderGrid();
    try {
      const r = await fetch('/api/interactive-assets/snapshot?id=' + encodeURIComponent(id));
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || '조합을 불러오지 못했습니다');
      const row = Array.isArray(d.chars) ? d.chars[Number(charIndex)] : null;
      if (!row) throw new Error('그 캐릭터가 없습니다');
      const panel = getPanel && getPanel();
      if (!panel || typeof panel.applySnapshotCharAt !== 'function') {
        throw new Error('Interactive 패널이 준비되지 않았습니다');
      }
      if (!panel.applySnapshotCharAt(targetSlot, row)) throw new Error('슬롯에 꽂을 수 없습니다');
      showToast(`C${targetSlot + 1} <- ${charLabel(row)}`, 'success');
    } catch (err) {
      showToast('스왑 실패: ' + err.message, 'error');
    } finally {
      busy = false;
      renderGrid();
    }
  }

  /** 카드를 펼쳐 그 조합의 캐릭터 칩을 띄운다. 본문을 읽어야 하므로 비동기다.
   *  **1명짜리 조합은 펼치지 않고 바로 꽂는다** — 칩 하나를 또 누르게 하면 헛수고다. */
  async function expandCard(id) {
    if (busy) return;
    const row = rows.find(x => x.id === id);
    if (row && Number(row.char_count) === 1) { swapInto(id, 0); return; }
    if (expandedId === id) { expandedId = ''; renderGrid(); return; }
    busy = true;
    renderGrid();
    try {
      const r = await fetch('/api/interactive-assets/snapshot?id=' + encodeURIComponent(id));
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || '조합을 불러오지 못했습니다');
      const chars = Array.isArray(d.chars) ? d.chars : [];
      if (chars.length === 1) { busy = false; swapInto(id, 0); return; }
      const hit = rows.find(x => x.id === id);
      if (hit) hit._chars = chars.map(charLabel);
      expandedId = id;
    } catch (err) {
      showToast('불러오기 실패: ' + err.message, 'error');
    } finally {
      busy = false;
      renderGrid();
    }
  }

  /** 칩에 쓸 이름. 캐릭터명이 없으면 첫 태그로 대신한다(빈 칩을 만들지 않는다). */
  function charLabel(row) {
    const f = (row && row.fields) || {};
    const name = (f['캐릭터'] || [])[0];
    if (name) return String(name);
    for (const k of Object.keys(f)) {
      const v = (f[k] || [])[0];
      if (v) return String(v);
    }
    return row && row.gender === 'male' ? '남성' : '여성';
  }

  async function restore(id) {
    if (busy) return;
    busy = true;
    renderGrid();
    try {
      const r = await fetch('/api/interactive-assets/snapshot?id=' + encodeURIComponent(id));
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || '조합을 불러오지 못했습니다');
      const chars = Array.isArray(d.chars) ? d.chars : null;
      if (!chars || !chars.length) throw new Error('빈 조합입니다');
      const panel = getPanel && getPanel();
      if (!panel || typeof panel.applySnapshotChars !== 'function') {
        throw new Error('Interactive 패널이 준비되지 않았습니다');
      }
      if (!panel.applySnapshotChars(chars)) throw new Error('복원할 수 없는 조합입니다');
      showToast(`조합 복원 (캐릭터 ${chars.length}명)`, 'success');
    } catch (err) {
      showToast('복원 실패: ' + err.message, 'error');
    } finally {
      busy = false;
      renderGrid();
    }
  }

  // ------------------------------------------------------------------ 렌더

  function tabBtn(value, label) {
    const on = origin === value;
    return `<button type="button" class="ia-as-tab${on ? ' is-on' : ''}"
             data-as-origin="${escHtml(value)}">${escHtml(label)}</button>`;
  }

  /** 캐릭터 스택 — Assets 바 **위**에 세로로 쌓인다(아래가 C1). 누르면 좌측
   *  아코디언이 그 슬롯으로 열린다. 여는 것만 한다 — 추가/삭제는 좌측이 소유. */
  function stackHtml() {
    if (!roster.length) return '';
    // 아래에서 위로 쌓이므로 뒤집는다. C1 이 바 바로 위에 붙어야 손이 짧다.
    return '<div class="ia-as-stack">' + [...roster].reverse().map(c =>
      `<button type="button" class="ia-as-slot${c.open ? ' is-open' : ''}` +
      `${c.enabled ? '' : ' is-off'}" data-as-open="${c.index}"` +
      ` title="${escHtml(c.name || c.label)}${c.enabled ? '' : ' (비활성)'}">` +
      `${escHtml(c.label)}</button>`).join('') + '</div>';
  }

  /** 대상 슬롯 선택 — ASSETS 라벨 옆 가로 칸. 조합을 어디에 꽂을지 정한다.
   *  칸은 최대치(5)만큼 그리되 **없는 슬롯은 비워 둔다** — 몇 명까지 되는지 보인다.
   *  **목록이 펼쳐졌을 때만** 낸다 — 접혀 있으면 꽂을 카드가 없어 쓸 데가 없다. */
  function targetHtml() {
    const max = 5;
    const out = [];
    for (let i = 0; i < max; i++) {
      const exists = i < roster.length;
      // 만들 수 있는 것은 **바로 다음 칸 하나뿐**이다. 건너뛰어 고르게 하면 중간
      // 슬롯이 빈 채로 활성 생성되어 인원수와 프롬프트에 끼어든다.
      const canMake = i === roster.length && roster.length < max;
      const locked = !exists && !canMake;
      const on = i === targetSlot;
      const tip = exists ? `C${i + 1} 에 꽂기`
        : (canMake ? `C${i + 1} 슬롯을 만들어 꽂기`
                   : `C${roster.length + 1} 부터 채워야 합니다`);
      out.push(`<button type="button" class="ia-as-target${on ? ' is-on' : ''}` +
        `${exists ? '' : ' is-empty'}${locked ? ' is-locked' : ''}"` +
        ` data-as-target="${i}"${locked ? ' disabled' : ''}` +
        ` title="${escHtml(tip)}">${exists ? i + 1 : ''}</button>`);
    }
    return '<div class="ia-as-targets">' + out.join('') + '</div>';
  }

  function card(row) {
    const id = escHtml(String(row.id || ''));
    const summary = String(row.summary || '(빈 조합)');
    const thumb = row.thumb
      ? `<img class="ia-as-thumb" loading="lazy" alt=""
              src="/api/interactive-assets/snapshot/thumb?id=${encodeURIComponent(row.id)}">`
      // 썸네일은 그 조합으로 생성해야 붙는다 — 아직이면 자리를 비워 둔다.
      : `<span class="ia-as-thumb is-empty" aria-hidden="true">…</span>`;
    const chips = (expandedId === row.id && Array.isArray(row._chars))
      ? '<div class="ia-as-chips">' + row._chars.map((nm, i) =>
          `<button type="button" class="ia-as-chip" data-as-swap="${id}" data-as-ci="${i}"` +
          ` title="C${targetSlot + 1} 에 꽂기">${escHtml(nm)}</button>`).join('') + '</div>'
      : '';
    return `<div class="ia-as-card${row.favorite ? ' is-fav' : ''}` +
      `${expandedId === row.id ? ' is-expanded' : ''}" data-as-id="${id}"
              title="${escHtml(summary)}">
      <button type="button" class="ia-as-pick" data-as-expand="${id}">
        ${thumb}
        <span class="ia-as-summary">${escHtml(summary)}</span>
      </button>
      ${chips}
      <button type="button" class="ia-as-restore" data-as-restore="${id}"
              title="조합 전체를 복원 (모든 캐릭터 슬롯을 덮어씀)" aria-label="전체 복원">&#8635;</button>
      <button type="button" class="ia-as-star" data-as-fav="${id}"
              title="${row.favorite ? '즐겨찾기 해제' : '즐겨찾기'}"
              aria-label="즐겨찾기">${row.favorite ? '★' : '☆'}</button>
      <button type="button" class="ia-as-del" data-as-del="${id}"
              title="이 조합 삭제" aria-label="삭제">✕</button>
    </div>`;
  }

  /** 목록만 다시 그린다. 전체 render() 는 검색창 노드를 갈아치워 입력 중 포커스와
   *  캐럿이 날아간다 — 응답이 220ms 뒤에 오므로 타이핑 도중에 정확히 걸린다. */
  function renderGrid() {
    const grid = root.querySelector('.ia-as-grid');
    if (!grid) { render(); return; }
    grid.innerHTML = busy
      ? '<div class="ia-as-empty">불러오는 중…</div>'
      : (rows.length ? rows.map(card).join('')
                     : '<div class="ia-as-empty">저장된 조합이 없습니다. 생성하면 남습니다.</div>');
    const count = root.querySelector('.ia-as-count');
    if (count) count.textContent = rows.length || '';
    // 탭 활성 표시도 여기서 맞춘다. 전체 render() 를 부르면 검색창 노드가 바뀌어
    // 입력 중 포커스가 날아가므로, 클래스만 손으로 동기화한다.
    root.querySelectorAll('[data-as-origin]').forEach(btn => {
      btn.classList.toggle('is-on', (btn.dataset.asOrigin || '') === origin);
    });
    const favBtn = root.querySelector('[data-as-favonly]');
    if (favBtn) favBtn.classList.toggle('is-on', favoriteOnly);
  }

  function render() {
    root.hidden = !visible;
    if (!visible) { root.innerHTML = ''; return; }
    root.classList.toggle('is-open', open);

    const list = !open ? '' : `
      <div class="ia-as-controls">
        <input class="ia-as-search" type="search" placeholder="조합 검색"
               value="${escHtml(query)}" data-as-search="1">
        <div class="ia-as-tabs">
          ${tabBtn('', '전체')}${tabBtn('original', '오리지널')}${tabBtn('known', '기존 캐릭터')}
          <button type="button" class="ia-as-tab is-star${favoriteOnly ? ' is-on' : ''}"
                  data-as-favonly="1" title="즐겨찾기만">★</button>
        </div>
      </div>
      <div class="ia-as-grid">
        ${busy ? '<div class="ia-as-empty">불러오는 중…</div>'
               : (rows.length ? rows.map(card).join('')
                              : '<div class="ia-as-empty">저장된 조합이 없습니다. 생성하면 남습니다.</div>')}
      </div>`;

    root.innerHTML = `
      ${stackHtml()}
      <div class="ia-as-bar">
        <button type="button" class="ia-as-toggle" data-as-toggle="1"
                aria-expanded="${open ? 'true' : 'false'}">
          <span class="ia-as-caret">${open ? '▾' : '▸'}</span>
          <span class="ia-as-title">Assets</span>
          <span class="ia-as-count">${rows.length || ''}</span>
        </button>
        ${open ? targetHtml() : ''}
      </div>
      ${list}`;
  }

  // ------------------------------------------------------------------ 입력

  function onClick(event) {
    const t = event.target.closest('[data-as-toggle],[data-as-origin],[data-as-favonly],' +
      '[data-as-restore],[data-as-fav],[data-as-del],[data-as-open],[data-as-target],' +
      '[data-as-expand],[data-as-swap]');
    if (!t) return;
    event.preventDefault();
    if (t.dataset.asToggle) {
      open = !open;
      render();
      if (open) fetchList();
      return;
    }
    if (t.dataset.asOrigin !== undefined) {
      origin = t.dataset.asOrigin || '';
      fetchList();
      return;
    }
    if (t.dataset.asFavonly) {
      favoriteOnly = !favoriteOnly;
      fetchList();
      return;
    }
    if (t.dataset.asOpen !== undefined) {
      const panel = getPanel && getPanel();
      if (panel && typeof panel.openCharacterAt === 'function') {
        panel.openCharacterAt(Number(t.dataset.asOpen));
      }
      return;
    }
    if (t.dataset.asTarget !== undefined) {
      targetSlot = Number(t.dataset.asTarget);
      render();
      return;
    }
    if (t.dataset.asExpand) { expandCard(t.dataset.asExpand); return; }
    if (t.dataset.asSwap) { swapInto(t.dataset.asSwap, t.dataset.asCi); return; }
    if (t.dataset.asDel) { remove(t.dataset.asDel); return; }
    if (t.dataset.asRestore) { restore(t.dataset.asRestore); return; }
    if (t.dataset.asFav) {
      const row = rows.find(x => x.id === t.dataset.asFav);
      toggleFavorite(t.dataset.asFav, row ? row.summary : '');
    }
  }

  function onInput(event) {
    const input = event.target.closest('[data-as-search]');
    if (!input) return;
    query = String(input.value || '').trim();
    if (searchTimer) clearTimeout(searchTimer);
    searchTimer = setTimeout(fetchList, 220);
  }

  root.addEventListener('click', onClick);
  root.addEventListener('input', onInput);

  // ------------------------------------------------------------------ 공개

  return {
    /** Interactive 모드 on/off 를 그대로 따른다 — 이 패널은 그 모드의 도구다. */
    setVisible(on) {
      const next = !!on;
      if (next === visible) return;
      visible = next;
      if (!visible) open = false;
      render();
    },
    /** 패널이 캐릭터 목록 변화를 알려 준다. 스택과 대상 칸이 이걸로 그려진다. */
    setRoster(next) {
      roster = Array.isArray(next) ? next : [];
      // 캐릭터가 줄면 대상이 '만들 수 없는 칸'을 겨눌 수 있다 — 다음 칸까지로 당긴다.
      if (targetSlot > roster.length || targetSlot >= 5) {
        targetSlot = Math.min(roster.length, 4);
      }
      if (visible) render();
    },
    record,
    /** 생성이 끝난 뒤 썸네일이 붙었을 수 있다 — 열려 있을 때만 다시 읽는다. */
    refresh() { if (visible && open) fetchList(); },
    destroy() {
      root.removeEventListener('click', onClick);
      root.removeEventListener('input', onInput);
      if (searchTimer) clearTimeout(searchTimer);
      root.innerHTML = '';
      root.hidden = true;
    },
  };
}
