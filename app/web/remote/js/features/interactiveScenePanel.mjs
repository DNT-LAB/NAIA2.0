// Interactive Scene — 씬(이벤트) 기록 컨트롤 패널.
//
// 결과 영역 **우하단**에 붙는 가로 바다(좌=캐릭터 Assets, 우=씬 — 사용자 지정
// 2026-08-11). Interactive 모드일 때만 보인다.
//
// 2단이다(사용자 지정):
//   최근 씬   생성할 때마다 자동으로 쌓인다. 500 한도, 오래된 것부터 사라진다.
//   저장한 씬 [저장]을 누른 것만. 이름·폴더를 갖고 지우기 전엔 사라지지 않는다.
//
// 좋은 씬은 만들 때 알아보지 못한다 — 열 장 뽑고 나서 세 번째가 제일 좋았다는 걸
// 안다. 자동 기록은 그 안전망이고, 저장은 그중에서 골라 남기는 행위다.
//
// 바에는 최근 씬만 둔다. 저장한 씬은 폴더 줄 + 카드 그리드가 필요해서 바에 넣으면
// 둘 다 좁아진다 — [저장한 씬] 버튼이 전용 팝업을 연다(캐릭터 쪽 Assets 바 vs
// Assets 탭과 같은 갈래).
//
// 백엔드 계약(app/backend/server/interactive_assets_routes.py):
//   GET  /api/interactive-assets/scenes?tier=auto|saved&folder=&query=&favorite=
//   GET  /api/interactive-assets/scene?id=            본문(복원용)
//   GET  /api/interactive-assets/scene/thumb?id=      384px WEBP
//   POST /api/interactive-assets/scene       {globals, chars}   기록
//   POST /api/interactive-assets/scene/save  {id, name, folder} | {id, on:false}
//   POST /api/interactive-assets/scene/update {id, name?, folder?}
//   POST /api/interactive-assets/scene/delete {id}
//   GET/POST /api/interactive-assets/scene/folders   op = create|rename|delete
export function createInteractiveScenePanel({
  document,
  escHtml,
  showToast,
  showAppDialog,     // 이름 입력 · 삭제 확인
  getPanel,          // () => interactivePanel (복원 대상)
}) {
  const root = document.getElementById('interactiveScene');
  if (!root) return null;

  const RECENT_LIMIT = 12;      // 바에 거는 최근 카드 수
  const SAVED_LIMIT = 200;

  let visible = false;
  let open = false;             // 최근 스트립 펼침
  let recent = [];
  let busy = false;
  let loadSeq = 0;              // 늦게 온 응답이 최신 목록을 덮지 않게

  // ---- 팝업(저장한 씬) 상태 ----
  let popEl = null;
  let popOpen = false;
  let folders = [];
  let savedRows = [];
  // Finder 3열의 선택 상태. `curTop` 이 대카테고리, `curSub` 이 그 아래 소카테고리다.
  // 둘 다 비면 전체. `curNone` 은 '폴더 없음'(아직 정리하지 않은 것)만 보는 상태 —
  // 빈 문자열로는 '전체'와 구분할 수 없어서 따로 둔다.
  let curTop = '';
  let curSub = '';
  let curNone = false;
  let query = '';
  let searchTimer = null;

  // ---------------------------------------------------------------- 통신
  async function api(path, payload) {
    const opt = payload === undefined ? {} : {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    };
    const res = await fetch('/api/interactive-assets' + path, opt);
    let body = null;
    try { body = await res.json(); } catch (_) { body = null; }
    if (!res.ok) throw new Error((body && body.error) || `HTTP ${res.status}`);
    return body || {};
  }

  function thumbUrl(row) {
    // 썸네일은 생성이 끝난 뒤 붙는다 — 없으면 회색 판으로 둔다(빈 img 는 깨진
    // 아이콘이 뜬다). `created_at` 을 붙여 갱신된 카드의 옛 그림이 캐시에 남지 않게.
    return row && row.thumb
      ? `/api/interactive-assets/scene/thumb?id=${encodeURIComponent(row.id)}&v=${row.created_at || 0}`
      : '';
  }

  // ---------------------------------------------------------------- 최근 바
  async function fetchRecent() {
    const seq = ++loadSeq;
    try {
      const r = await api(`/scenes?tier=auto&limit=${RECENT_LIMIT}`);
      if (seq !== loadSeq) return;
      recent = Array.isArray(r.scenes) ? r.scenes : [];
    } catch (_) {
      if (seq !== loadSeq) return;
      recent = [];
    }
    render();
  }

  function cardHtml(row) {
    const name = String(row.name || '') || String(row.summary || '');
    const n = Number(row.char_count || 0);
    return `<div class="ia-sc-card" data-scid="${escHtml(row.id)}">
      <div class="ia-sc-thumb">${row.thumb
        ? `<img src="${escHtml(thumbUrl(row))}" alt="" loading="lazy">` : ''}</div>
      <div class="ia-sc-body">
        <div class="ia-sc-name" title="${escHtml(name)}">${escHtml(name || '이름 없음')}</div>
        <div class="ia-sc-meta">${n ? `<span class="ia-sc-n">${n}인</span>` : ''}</div>
      </div>
      <div class="ia-sc-acts">
        <button type="button" class="ia-sc-btn" data-scact="apply" data-scid="${escHtml(row.id)}"
          data-naia-title="이 씬을 지금 캐릭터에게 입힙니다">적용</button>
        <button type="button" class="ia-sc-btn" data-scact="save" data-scid="${escHtml(row.id)}"
          data-naia-title="저장한 씬으로 올립니다 (이름은 나중에 붙여도 됩니다)">저장</button>
      </div>
    </div>`;
  }

  function render() {
    if (!visible) { root.hidden = true; root.innerHTML = ''; return; }
    root.hidden = false;
    root.classList.toggle('is-open', open);
    const head = `<div class="ia-sc-head">
      <button type="button" class="ia-sc-toggle" data-scact="toggle"
        data-naia-title="최근에 그린 씬을 펼칩니다">
        <span class="ia-sc-caret">${open ? '▾' : '▸'}</span>
        <span>Scene</span>${recent.length ? `<span class="ia-sc-count">${recent.length}</span>` : ''}
      </button>
      <button type="button" class="ia-sc-toggle" data-scact="open-saved"
        data-naia-title="이름과 폴더로 정리한 씬을 엽니다">저장한 씬</button>
    </div>`;
    const list = open
      ? `<div class="ia-sc-list">${
          recent.length ? recent.map(cardHtml).join('')
                        : '<div class="ia-sc-empty">아직 기록된 씬이 없습니다.</div>'}</div>`
      : '';
    root.innerHTML = head + list;
  }

  // ---------------------------------------------------------------- 팝업
  function ensurePop() {
    if (popEl && document.body.contains(popEl)) return popEl;
    popEl = document.createElement('div');
    popEl.className = 'ia-sc-pop';
    popEl.hidden = true;
    // **body 직계**로 둔다. `.viewer-wrapper` 는 `z-index:0 + isolation:isolate` 라
    // 그 안에 넣으면 이 팝업의 z 가 0 층으로 접혀 좌측 컨트롤이 위를 덮는다
    // (캐릭터 패널·칩 툴팁·씬 플로트에서 세 번 겪었다).
    document.body.appendChild(popEl);
    // 위임 리스너는 root 에 걸려 있는데 이 노드는 root 밖이다 — 따로 건다.
    popEl.addEventListener('click', onClick);
    popEl.addEventListener('input', onInput);
    return popEl;
  }

  async function loadSaved() {
    const q = query ? `&query=${encodeURIComponent(query)}` : '';
    // 소카테고리를 골랐으면 그것만, 아니면 대카테고리 전체(백엔드가 아래까지 푼다).
    const want = curNone ? 'none' : (curSub || curTop);
    const f = want ? `&folder=${encodeURIComponent(want)}` : '';
    try {
      const [fr, sr] = await Promise.all([
        api('/scene/folders'),
        api(`/scenes?tier=saved&limit=${SAVED_LIMIT}${q}${f}`),
      ]);
      folders = Array.isArray(fr.folders) ? fr.folders : [];
      savedRows = Array.isArray(sr.scenes) ? sr.scenes : [];
    } catch (exc) {
      folders = []; savedRows = [];
      showToast(`저장한 씬을 읽지 못했습니다: ${exc.message}`, 'error');
    }
    renderPop();
  }

  /** 카드에 보여줄 폴더 이름. 소카테고리면 `대 / 소` 로 짚어 준다 — 컨텐츠에는
   *  대카테고리 전부가 깔리므로, 이름만 보면 어느 하위인지 알 수 없다. */
  function folderLabel(fid) {
    const f = folders.find(x => x.id === fid);
    if (!f) return '폴더 없음';
    const up = f.parent ? folders.find(x => x.id === f.parent) : null;
    return up ? `${up.name} / ${f.name}` : f.name;
  }

  function savedCardHtml(row) {
    const name = String(row.name || '') || String(row.summary || '');
    const n = Number(row.char_count || 0);
    const bits = [row.folder ? folderLabel(row.folder) : '', n ? `${n}인` : ''].filter(Boolean);
    return `<div class="ia-sc-scard" data-scid="${escHtml(row.id)}">
      <div class="ia-sc-sthumb">${row.thumb
        ? `<img src="${escHtml(thumbUrl(row))}" alt="" loading="lazy">` : ''}</div>
      <div class="ia-sc-sname" title="${escHtml(name)}">${escHtml(name || '이름 없음')}</div>
      <div class="ia-sc-smeta">${escHtml(bits.join(' · '))}</div>
      <div class="ia-sc-sacts">
        <button type="button" class="ia-sc-btn is-main" data-scact="apply"
          data-scid="${escHtml(row.id)}">적용</button>
        <button type="button" class="ia-sc-btn" data-scact="rename"
          data-scid="${escHtml(row.id)}" data-naia-title="이름 바꾸기">이름</button>
        <button type="button" class="ia-sc-btn" data-scact="move"
          data-scid="${escHtml(row.id)}" data-naia-title="폴더 옮기기">폴더</button>
        <button type="button" class="ia-sc-btn is-danger" data-scact="unsave"
          data-scid="${escHtml(row.id)}" data-naia-title="수집에서 내립니다 (지우지 않습니다)">내리기</button>
      </div>
    </div>`;
  }

  /** Finder 3열(사용자 지정 2026-08-12): [대카테고리][소카테고리][컨텐츠].
   *
   *  대카테고리를 고르면 **그 안의 모든 아이템**이 컨텐츠에 깔린다 — 소카테고리에
   *  든 것까지 포함이다(백엔드가 `folder=대` 를 그 아래까지로 푼다). 소카테고리
   *  칸에는 **[전체보기]가 항상 있다** — 그게 곧 '대카테고리 전부' 상태다. */
  function renderPop() {
    const el = ensurePop();
    if (!popOpen) { el.hidden = true; el.innerHTML = ''; return; }
    el.hidden = false;

    const tops = folders.filter(f => !f.parent);
    const subs = curTop ? folders.filter(f => f.parent === curTop) : [];
    const row = (on, act, id, label, extra) =>
      `<button type="button" class="ia-sc-item${on ? ' is-on' : ''}${extra || ''}"
         data-scact="${act}" data-fid="${escHtml(id)}">${escHtml(label)}</button>`;

    const col1 = [
      row(!curTop && !curNone, 'top', '', '전체'),
      ...tops.map(f => row(curTop === f.id, 'top', f.id, f.name)),
      row(curNone, 'top', 'none', '폴더 없음'),
      `<button type="button" class="ia-sc-item is-add" data-scact="folder-new"
         data-fid="" data-naia-title="대카테고리를 만듭니다">+ 카테고리</button>`,
    ].join('');

    // **소카테고리 칸은 쓰기 전엔 안 보인다**(사용자 지정 2026-08-12).
    // 저장한 씬은 현실적으로 수십 장 규모라, 항상 세 칸을 띄우면 쓰지도 않는 층이
    // 썸네일 자리를 300px 먹는다. 하나라도 만들면 그때 칸이 생긴다 - 데이터는
    // 그대로이므로 나중에 많아져도 되돌릴 일이 없다.
    const showSub = !!curTop && subs.length > 0;
    const col2 = showSub
      ? [
          row(!curSub, 'sub', '', '전체보기'),
          ...subs.map(f => row(curSub === f.id, 'sub', f.id, f.name)),
          `<button type="button" class="ia-sc-item is-add" data-scact="folder-new"
             data-fid="${escHtml(curTop)}" data-naia-title="이 카테고리 안에 만듭니다">+ 하위</button>`,
        ].join('')
      : '';

    const target = curSub || curTop;
    const tools = target
      ? // 칸이 접혀 있으면 [+ 하위]를 여기 둔다 - 없으면 첫 소카테고리를 만들 길이 없다.
        (showSub ? '' : `<button type="button" class="ia-sc-btn" data-scact="folder-new"
           data-fid="${escHtml(curTop)}"
           data-naia-title="이 카테고리 안에 하위를 만듭니다">+ 하위</button>`)
        + `<button type="button" class="ia-sc-btn" data-scact="folder-rename">이름</button>
         <button type="button" class="ia-sc-btn is-danger" data-scact="folder-del"
           data-naia-title="폴더만 지웁니다 — 안의 씬은 남습니다">삭제</button>`
      : '';

    el.innerHTML = `<div class="ia-sc-pop-box">
      <div class="ia-sc-pop-head">
        <span class="ia-sc-pop-title">저장한 씬</span>
        <input type="text" class="ia-sc-search" data-scsearch placeholder="이름·태그로 찾기"
          value="${escHtml(query)}">
        ${tools}
        <button type="button" class="ia-sc-btn" data-scact="close-saved">닫기</button>
      </div>
      <div class="ia-sc-finder${showSub ? '' : ' is-2col'}">
        <div class="ia-sc-col ia-sc-col1">${col1}</div>
        ${showSub ? `<div class="ia-sc-col ia-sc-col2">${col2}</div>` : ''}
        <div class="ia-sc-col ia-sc-content">
          <div class="ia-sc-grid">${
            savedRows.length ? savedRows.map(savedCardHtml).join('')
              : `<div class="ia-sc-empty">${query || curTop || curNone
                  ? '조건에 맞는 씬이 없습니다.'
                  : '아직 저장한 씬이 없습니다. 최근 씬에서 [저장]을 누르세요.'}</div>`}</div>
        </div>
      </div>
    </div>`;
  }

  // ---------------------------------------------------------------- 동작
  async function applyScene(id) {
    const panel = getPanel && getPanel();
    if (!panel || !panel.applySceneSnapshot) return;
    try {
      const body = await api(`/scene?id=${encodeURIComponent(id)}`);
      const ok = panel.applySceneSnapshot(body);
      if (!ok) { showToast('씬을 되돌리지 못했습니다.', 'error'); return; }
      showToast('씬을 적용했습니다.', 'info');
      closeSaved();
    } catch (exc) {
      showToast(`씬을 읽지 못했습니다: ${exc.message}`, 'error');
    }
  }

  async function saveScene(id) {
    try {
      await api('/scene/save', {id});
      showToast('저장한 씬으로 올렸습니다. 이름은 [저장한 씬]에서 붙일 수 있습니다.', 'info');
      fetchRecent();
      if (popOpen) loadSaved();
    } catch (exc) {
      showToast(`저장하지 못했습니다: ${exc.message}`, 'error');
    }
  }

  async function askText(title, initial) {
    if (typeof showAppDialog !== 'function') return null;
    const got = await showAppDialog({
      title, prompt: true, value: initial || '',
      confirmLabel: '확인', cancelLabel: '취소',
    });
    if (got === null || got === undefined || got === false) return null;
    return String(typeof got === 'string' ? got : (got.value || '')).trim();
  }

  function openSaved() {
    popOpen = true;
    loadSaved();
    document.addEventListener('keydown', onKey, true);
  }

  function closeSaved() {
    if (!popOpen) return;
    popOpen = false;
    document.removeEventListener('keydown', onKey, true);
    renderPop();
  }

  function onKey(e) {
    if (e.key === 'Escape' && popOpen) { e.stopPropagation(); closeSaved(); }
  }

  function onInput(e) {
    const el = e.target;
    if (!el || !el.hasAttribute || !el.hasAttribute('data-scsearch')) return;
    query = String(el.value || '');
    if (searchTimer) clearTimeout(searchTimer);
    // 한 글자마다 부르면 목록이 깜빡인다 — 캐릭터 패널과 같은 간격.
    searchTimer = setTimeout(() => { if (popOpen) loadSaved(); }, 220);
  }

  async function onClick(e) {
    const btn = e.target && e.target.closest ? e.target.closest('[data-scact]') : null;
    if (!btn) return;
    e.preventDefault();
    e.stopPropagation();
    if (busy) return;
    const act = btn.dataset.scact;
    const id = btn.dataset.scid || '';
    busy = true;
    try {
      if (act === 'toggle') { open = !open; render(); if (open) await fetchRecent(); }
      else if (act === 'open-saved') openSaved();
      else if (act === 'close-saved') closeSaved();
      else if (act === 'apply') await applyScene(id);
      else if (act === 'save') await saveScene(id);
      else if (act === 'top') {
        const fid = btn.dataset.fid || '';
        curNone = fid === 'none';
        curTop = curNone ? '' : fid;
        curSub = '';               // 대카테고리를 바꾸면 소카테고리 선택은 버린다
        await loadSaved();
      } else if (act === 'sub') {
        curSub = btn.dataset.fid || '';
        await loadSaved();
      } else if (act === 'folder-new') {
        // 1열의 [+ 카테고리]는 부모 없이, 2열의 [+ 하위]는 지금 대카테고리 밑으로.
        const parent = btn.dataset.fid || '';
        const name = await askText(parent ? '하위 카테고리 이름' : '카테고리 이름', '');
        if (name) {
          const r = await api('/scene/folders', {op: 'create', name, parent});
          if (r && r.folder) {
            if (parent) curSub = r.folder.id;
            else { curTop = r.folder.id; curSub = ''; curNone = false; }
          }
          await loadSaved();
        }
      } else if (act === 'folder-rename') {
        const target = curSub || curTop;
        if (!target) { showToast('이름을 바꿀 폴더를 고르세요.', 'info'); }
        else {
          const cur = folders.find(f => f.id === target);
          const name = await askText('폴더 이름', cur ? cur.name : '');
          if (name) {
            await api('/scene/folders', {op: 'rename', id: target, name});
            await loadSaved();
          }
        }
      } else if (act === 'folder-del') {
        const target = curSub || curTop;
        if (!target) { showToast('지울 폴더를 고르세요.', 'info'); }
        else {
          // 폴더만 지운다 — 안의 씬은 남는다. 대카테고리면 소카테고리도 함께
          // 사라지므로 그 사실까지 문구로 못박는다.
          const deep = !curSub && folders.some(f => f.parent === curTop);
          const ok = typeof showAppDialog === 'function'
            ? await showAppDialog({
                title: '폴더를 지울까요?',
                message: (deep ? '하위 카테고리도 함께 사라집니다. ' : '')
                  + '폴더만 지웁니다 — 안에 든 씬은 사라지지 않고 폴더 없음으로 옮겨집니다.',
                confirmLabel: '지우기', cancelLabel: '취소', danger: true})
            : true;
          if (ok) {
            await api('/scene/folders', {op: 'delete', id: target});
            if (curSub) curSub = '';
            else { curTop = ''; curSub = ''; }
            await loadSaved();
          }
        }
      } else if (act === 'rename') {
        const row = savedRows.find(r => r.id === id);
        const name = await askText('씬 이름', row ? (row.name || '') : '');
        if (name !== null) { await api('/scene/update', {id, name}); await loadSaved(); }
      } else if (act === 'move') {
        if (!folders.length) { showToast('먼저 카테고리를 만드세요.', 'info'); }
        else {
          // 폴더가 몇 개 안 되므로 순환으로 옮긴다 — 고르는 창을 하나 더 띄우는 것보다 빠르다.
          // 순서는 **화면과 같게** 대카테고리 다음에 그 소카테고리다. 평면으로 돌면
          // 남의 카테고리 밑을 헤매게 된다.
          const order = [''];
          for (const t of folders.filter(f => !f.parent)) {
            order.push(t.id);
            for (const s of folders.filter(f => f.parent === t.id)) order.push(s.id);
          }
          const row = savedRows.find(r => r.id === id);
          const at = order.indexOf(String((row && row.folder) || ''));
          const next = order[(at + 1) % order.length];
          await api('/scene/update', {id, folder: next});
          showToast(`${folderLabel(next)} 으로 옮겼습니다.`, 'info');
          await loadSaved();
        }
      } else if (act === 'unsave') {
        await api('/scene/save', {id, on: false});
        showToast('수집에서 내렸습니다. 최근 씬에는 남아 있습니다.', 'info');
        await loadSaved();
        fetchRecent();
      }
    } catch (exc) {
      showToast(`처리하지 못했습니다: ${exc.message}`, 'error');
    } finally {
      busy = false;
    }
  }

  root.addEventListener('click', onClick);
  root.addEventListener('input', onInput);

  return {
    /** Interactive 모드 on/off 를 그대로 따른다 — 이 패널은 그 모드의 도구다. */
    setVisible(on) {
      const next = !!on;
      if (next === visible) return;
      visible = next;
      if (!visible) { open = false; closeSaved(); }
      render();
      if (visible) fetchRecent();
    },
    /** 생성 직전에 app.js 가 부른다. 값어치가 없으면 백엔드가 건너뛰고 null 을 준다. */
    async record(globals, chars) {
      try {
        const r = await api('/scene', {globals, chars});
        // 라우트는 `{ok, scene}` 을 준다 — `scene` 이 null 이면 값어치 없는 씬이라
        // 기록하지 않은 것이다(오류가 아니다). 그때는 붙일 카드가 없다.
        return r && r.scene ? r.scene : null;
      } catch (_) {
        return null;                 // 기록 실패가 생성을 막지 않는다
      }
    },
    /** 생성이 끝나면 썸네일이 붙었을 수 있다 — 열려 있을 때만 다시 읽는다. */
    refresh() {
      if (!visible) return;
      if (open) fetchRecent();
      if (popOpen) loadSaved();
    },
    destroy() {
      root.removeEventListener('click', onClick);
      root.removeEventListener('input', onInput);
      document.removeEventListener('keydown', onKey, true);
      if (searchTimer) clearTimeout(searchTimer);
      if (popEl && popEl.parentNode) popEl.parentNode.removeChild(popEl);
      popEl = null;
    },
  };
}
