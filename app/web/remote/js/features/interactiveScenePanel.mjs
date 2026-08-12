// Interactive Scene — 씬(이벤트) 기록 컨트롤 패널.
//
// 결과 영역 **우하단**에 붙는 가로 바다(좌=캐릭터 Assets, 우=씬 — 사용자 지정
// 2026-08-11). Interactive 모드일 때만 보인다.
//
// 2단이다(사용자 지정):
//   최근 씬   생성할 때마다 자동으로 쌓인다. 500 한도, 오래된 것부터 사라진다.
//   Scene     [저장]을 누른 것만. 이름·폴더를 갖고 지우기 전엔 사라지지 않는다.
//
// 좋은 씬은 만들 때 알아보지 못한다 — 열 장 뽑고 나서 세 번째가 제일 좋았다는 걸
// 안다. 자동 기록은 그 안전망이고, 저장은 그중에서 골라 남기는 행위다.
//
// 바에는 Recent(자동 기록)만 둔다. Scene 은 폴더 줄 + 카드 그리드가 필요해서 바에
// 넣으면 둘 다 좁아진다 — [Scene] 버튼이 전용 팝업을 연다(캐릭터 쪽 Assets 바 vs
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
  generateScene,     // (body) => 작업판을 건드리지 않고 이 씬으로 한 장
  generateNow,       // () => 지금 작업판 그대로 생성(적용 + 생성)
}) {
  const root = document.getElementById('interactiveScene');
  if (!root) return null;

  // 끌어 옮길 때 싣는 자료형. **우리 것만 받는다** - 파일이나 다른 앱의 글을
  // 떨어뜨렸을 때 폴더가 반응하면 안 된다(사용자 지정 2026-08-12).
  const DND_MIME = 'application/x-naia-scene';

  const RECENT_LIMIT = 12;      // 바에 거는 최근 카드 수
  // 저장소 한도(500)와 같게 둔다 - 그보다 많을 수 없으므로 잘려서 안 보이는 일이
  // 없다. 페이지 나눔은 두지 않는다(수십 장 규모라 아직 값을 못 한다).
  const SAVED_LIMIT = 500;

  let visible = false;
  let open = false;             // 최근 스트립 펼침
  let recent = [];
  let busy = false;
  let loadSeq = 0;              // 늦게 온 응답이 최신 목록을 덮지 않게

  // ---- 팝업(Scene) 상태 ----
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
  // 오른쪽 미리보기. 카드를 누르면 그 씬의 본문을 읽어 여기 편다(사용자 지정
  // 2026-08-12). 목록은 건드리지 않는다 - 다시 그리면 카드가 깜빡인다.
  let previewId = '';
  let previewBody = null;
  let previewBusy = false;
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
        <div class="ia-sc-name">${escHtml(name || '이름 없음')}</div>
        <div class="ia-sc-meta">${n ? `<span class="ia-sc-n">${n}인</span>` : ''}</div>
      </div>
      <div class="ia-sc-acts">
        <button type="button" class="ia-sc-btn" data-scact="apply" data-scid="${escHtml(row.id)}"
          data-naia-title="그릴 때의 상태로 되돌립니다">복원</button>
        <button type="button" class="ia-sc-btn" data-scact="save" data-scid="${escHtml(row.id)}"
          data-naia-title="Scene 으로 올립니다 — 올리지 않으면 다음에 열 때 사라질 수 있습니다"
          >저장</button>
      </div>
    </div>`;
  }

  function render() {
    if (!visible) { root.hidden = true; root.innerHTML = ''; return; }
    root.hidden = false;
    root.classList.toggle('is-open', open);
    const head = `<div class="ia-sc-head">
      <button type="button" class="ia-sc-toggle" data-scact="toggle"
        data-naia-title="방금 그린 씬입니다. 저장하지 않은 것은 다음에 열 때 마지막 몇 개만 남습니다">
        <span class="ia-sc-caret">${open ? '▾' : '▸'}</span>
        <span>Recent</span>${recent.length ? `<span class="ia-sc-count">${recent.length}</span>` : ''}
      </button>
      <button type="button" class="ia-sc-toggle is-main" data-scact="open-saved"
        data-naia-title="이름과 폴더로 정리한 씬을 엽니다">Scene</button>
    </div>`;
    const list = open
      ? `<div class="ia-sc-list">${
          recent.length ? recent.map(cardHtml).join('')
                        : '<div class="ia-sc-empty">아직 기록된 씬이 없습니다.</div>'}</div>`
      : '';
    root.innerHTML = head + list;
    hideHover();          // 목록이 갈리면 가리키던 카드가 사라질 수 있다
    fitStrip();
  }

  /** 스트립 상자를 **실제로 들어가는 열 수**에 맞춘다.
   *
   *  `width: max-content` 는 '한 줄에 전부'를 재고, `max-width` 가 그걸 무대의
   *  절반으로 자른다. 그런데 줄바꿈은 그 폭 안에서 일어나므로 **상자는 늘 절반
   *  폭인데 카드는 그보다 적게 들어간다** — 왼쪽에 34~100px 이 빈 채로 남았다
   *  (실측: 창 1200 에서 100px · 1600 에서 84px). 사용자 지적 2026-08-12.
   *
   *  CSS 로는 '몇 열이 들어갔는가'를 되먹일 수 없어 여기서 잰다. 줄이기만 하므로
   *  다시 접히는 일은 없다(폭을 줄여도 같은 열 수가 유지된다).
   */
  function fitStrip() {
    if (!open) return;
    const list = root.querySelector('.ia-sc-list');
    const card = list && list.querySelector('.ia-sc-card');
    if (!list || !card) return;
    list.style.width = '';                     // 먼저 원래 한도로 되돌려 다시 잰다
    const cs = getComputedStyle(list);
    const gap = parseFloat(cs.columnGap) || 0;
    const border = parseFloat(cs.borderLeftWidth) + parseFloat(cs.borderRightWidth);
    const frame = parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight) + border;
    const cw = card.getBoundingClientRect().width;
    if (!cw) return;
    // **세로 스크롤바 폭을 셈에 넣는다.** 줄이 2.5줄을 넘으면 스크롤바가 생겨
    // 안쪽이 그만큼 좁아지고, 그러면 열이 하나 더 떨어져 나가 줄이 더 늘고 -
    // 되먹이가 돌아 결국 한 줄에 한 장이 됐다(실측: 창 1100~1200).
    // `clientWidth` 는 스크롤바를 뺀 값이라 둘의 차이가 곧 스크롤바 폭이다.
    const sbw = Math.max(0, list.offsetWidth - list.clientWidth - border);
    const inner = list.clientWidth - (frame - border);
    const n = list.querySelectorAll('.ia-sc-card').length;
    const cols = Math.max(1, Math.min(n, Math.floor((inner + gap + 0.5) / (cw + gap))));
    // **올림 + 1px.** 카드 폭·간격이 소수라 딱 맞게 주면 마지막 열이
    // 1px 모자라 떨어져 나간다(실측: 창 1100 에서 2열 -> 1열).
    list.style.width =
      `${Math.ceil(cols * cw + (cols - 1) * gap + frame + sbw) + 1}px`;
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
    popEl.addEventListener('contextmenu', onContextMenu);
    popEl.addEventListener('dragstart', onDragStart);
    popEl.addEventListener('dragend', onDragEnd);
    popEl.addEventListener('dragover', onDragOver);
    popEl.addEventListener('dragleave', onDragLeave);
    popEl.addEventListener('drop', onDrop);
    return popEl;
  }

  let savedSeq = 0;              // 늦게 온 응답이 최신 목록을 덮지 않게

  async function loadSaved() {
    const seq = ++savedSeq;
    const q = query ? `&query=${encodeURIComponent(query)}` : '';
    // 소카테고리를 골랐으면 그것만, 아니면 대카테고리 전체(백엔드가 아래까지 푼다).
    const want = curNone ? 'none' : (curSub || curTop);
    const f = want ? `&folder=${encodeURIComponent(want)}` : '';
    try {
      const [fr, sr] = await Promise.all([
        api('/scene/folders'),
        api(`/scenes?tier=saved&limit=${SAVED_LIMIT}${q}${f}`),
      ]);
      if (seq !== savedSeq) return;      // 더 새 질의가 이미 떠났다
      folders = Array.isArray(fr.folders) ? fr.folders : [];
      savedRows = Array.isArray(sr.scenes) ? sr.scenes : [];
    } catch (exc) {
      if (seq !== savedSeq) return;
      folders = []; savedRows = [];
      showToast(`Scene 을 읽지 못했습니다: ${exc.message}`, 'error');
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

  /** '장소 으로' 처럼 조사가 어긋나지 않게, 받침을 따지지 않아도 되는 문구로. */
  const movedMsg = fid =>
    (fid ? `${folderLabel(fid)} 폴더로 옮겼습니다.` : '폴더 분류를 풀었습니다.');

  /** 태그 몇 개를 칩 줄로. 빈 목록이면 아무것도 그리지 않는다(빈 제목만 남으면
   *  '여기 뭔가 있어야 하는데 없다'로 읽힌다). */
  function pvRow(label, list) {
    const arr = (Array.isArray(list) ? list : [])
      .map(t => String(t || '').trim()).filter(Boolean);
    if (!arr.length) return '';
    return `<div class="ia-sc-pv-row">
      <span class="ia-sc-pv-lab">${escHtml(label)}</span>
      <span class="ia-sc-pv-tags">${
        arr.map(t => `<span class="ia-sc-pv-tag">${escHtml(t)}</span>`).join('')}</span>
    </div>`;
  }

  /** 미리보기 — 위는 확대 그림, 아래는 씬 프롬프트와 캐릭터별 프롬프트.
   *
   *  **캐릭터 특징은 애초에 없다.** 씬 본문은 정체성(캐릭터·머리·눈얼굴·신체·
   *  종족)을 걷어낸 뒤 저장되므로, 여기 나열되는 것은 상황(의상·자세·표정·사물·
   *  구도·ALT·시선)뿐이다 - 따로 거를 필요가 없다. */
  function previewHtml() {
    if (!previewId) {
      return '<div class="ia-sc-hint">카드를 누르면 여기에서 자세히 볼 수 있습니다.</div>';
    }
    if (previewBusy || !previewBody) {
      return '<div class="ia-sc-hint">읽는 중…</div>';
    }
    const row = savedRows.find(r => r.id === previewId) || {};
    const g = previewBody.globals || {};
    const slots = g.slots || {};
    const sceneTags = Object.keys(slots).flatMap(k => slots[k] || []);
    const rating = ((g.rating || {}).picks || []).filter(p => p && p !== 'none');
    const chars = Array.isArray(previewBody.chars) ? previewBody.chars : [];
    const name = String(row.name || '') || String(row.summary || '') || '이름 없음';

    const charBlocks = chars.map((c, i) => {
      const fields = c.fields || {};
      const neg = c.neg || {};
      const pos = Object.keys(fields).flatMap(k => fields[k] || []);
      const ng = Object.keys(neg).flatMap(k => neg[k] || []);
      const extra = [...(c.alt || []), ...(c.gaze || [])];
      const body = [
        pvRow('프롬프트', pos),
        pvRow('ALT·시선', extra),
        pvRow('네거티브', ng),
      ].join('');
      return `<div class="ia-sc-pv-char">
        <div class="ia-sc-pv-chead">C${i + 1}
          <span class="ia-sc-pv-sub">${escHtml(
            (c.gender === 'male' ? 'boy' : 'girl') + ' · ' + (c.pos || 'C3'))}</span></div>
        ${body || '<div class="ia-sc-pv-empty">상황 태그 없음</div>'}
      </div>`;
    }).join('');

    // 적용 바는 **본문 밖**에 둔다 - 안에 두면 태그가 많은 씬에서 스크롤을 끝까지
    // 내려야 나온다. 미리보기를 보다가 곧바로 누르는 자리다(사용자 지정 2026-08-12).
    const sid = escHtml(previewId);
    // 셋의 차이는 '작업판을 바꾸는가'와 '지금 뽑는가' 두 축이다(사용자 지정 2026-08-12).
    //   즉시 생성   작업판 그대로 · 지금 뽑는다   (지금 캐릭터 + 저장한 상황)
    //   적용        작업판을 바꾼다 · 안 뽑는다
    //   적용 + 생성 작업판을 바꾸고 · 뽑는다
    const foot = `<div class="ia-sc-pv-foot">
      <button type="button" class="ia-sc-btn is-wide" data-scact="gen-now" data-scid="${sid}"
        data-naia-title="작업판을 그대로 두고 이 씬으로 한 장 뽑습니다">즉시 생성</button>
      <button type="button" class="ia-sc-btn is-main is-wide" data-scact="apply"
        data-scid="${sid}" data-naia-title="이 씬을 지금 캐릭터에게 입힙니다">적용</button>
      <button type="button" class="ia-sc-btn is-wide" data-scact="apply-gen" data-scid="${sid}"
        data-naia-title="입힌 다음 바로 생성합니다">적용 + 생성</button>
      <button type="button" class="ia-sc-btn" data-scact="rename" data-scid="${sid}">이름</button>
      <button type="button" class="ia-sc-btn" data-scact="move" data-scid="${sid}"
        data-naia-title="다음 폴더로 옮깁니다">폴더</button>
      <button type="button" class="ia-sc-btn is-danger" data-scact="unsave" data-scid="${sid}"
        data-naia-title="Scene 에서 내립니다 (지우지 않습니다)">내리기</button>
    </div>`;

    return `<div class="ia-sc-pv-img">${row.thumb
      ? `<img src="${escHtml(thumbUrl(row))}" alt="">`
      : '<span class="ia-sc-pv-noimg">생성하면 그림이 붙습니다</span>'}</div>
      <div class="ia-sc-pv-body">
        <div class="ia-sc-pv-title">${escHtml(name)}</div>
        <div class="ia-sc-pv-sec">씬</div>
        ${pvRow('씬 태그', sceneTags)}
        ${pvRow('구도', g.composition_tags)}
        ${pvRow('Rating', rating)}
        ${g.free_text ? pvRow('자유 입력', [g.free_text]) : ''}
        ${g.fast_negative ? pvRow('전역 네거티브', [g.fast_negative]) : ''}
        ${chars.length ? `<div class="ia-sc-pv-sec">캐릭터 ${chars.length}명
          <span class="ia-sc-pv-note">특징(이름·머리·눈얼굴·신체·종족)은 씬에 담기지 않습니다</span>
          </div>${charBlocks}` : ''}
      </div>
      ${foot}`;
  }

  /** 목록이 갈리면 미리보기를 비운다 - 목록에 없는 카드를 계속 펼쳐 두면
   *  이름·썸네일을 못 찾아 반쪽으로 보인다. */
  function clearPreview() {
    previewId = '';
    previewBody = null;
    previewBusy = false;
  }

  async function openPreview(id) {
    if (previewId === id) { previewId = ''; previewBody = null; renderPop(); return; }
    previewId = id;
    previewBody = null;
    previewBusy = true;
    renderPop();
    try {
      previewBody = await api(`/scene?id=${encodeURIComponent(id)}`);
    } catch (exc) {
      previewBody = null;
      showToast(`씬을 읽지 못했습니다: ${exc.message}`, 'error');
    }
    previewBusy = false;
    if (popOpen) renderPop();
  }

  function savedCardHtml(row) {
    const name = String(row.name || '') || String(row.summary || '');
    const n = Number(row.char_count || 0);
    const bits = [row.folder ? folderLabel(row.folder) : '', n ? `${n}인` : ''].filter(Boolean);
    // 카드에는 **버튼을 두지 않는다**(사용자 지정 2026-08-12). 넷을 붙였더니
    // 미리보기 아래 버튼 바와 그대로 겹쳤고, 카드가 좁아져 썸네일이 죽었다.
    // 대신 오른쪽 클릭 - 카드를 보고 그 자리에서 바로 부르는 게 목적이다.
    return `<div class="ia-sc-scard${previewId === row.id ? ' is-preview' : ''}"
      draggable="true" data-scact="preview" data-scid="${escHtml(row.id)}"
      data-naia-title="왼쪽: 미리보기 · 오른쪽: 메뉴 · 끌어서 카테고리로">
      <div class="ia-sc-sthumb">${row.thumb
        ? `<img src="${escHtml(thumbUrl(row))}" alt="" loading="lazy">` : ''}</div>
      <div class="ia-sc-sname" title="${escHtml(name)}">${escHtml(name || '이름 없음')}</div>
      <div class="ia-sc-smeta">${escHtml(bits.join(' · '))}</div>
    </div>`;
  }

  /** Finder 3열(사용자 지정 2026-08-12): [대카테고리][소카테고리][컨텐츠].
   *
   *  대카테고리를 고르면 **그 안의 모든 아이템**이 컨텐츠에 깔린다 — 소카테고리에
   *  든 것까지 포함이다(백엔드가 `folder=대` 를 그 아래까지로 푼다). 소카테고리
   *  칸에는 **[전체보기]가 항상 있다** — 그게 곧 '대카테고리 전부' 상태다. */
  function renderPop() {
    // 목록이 갈리면 메뉴가 가리키던 카드가 사라질 수 있다 - 먼저 닫는다.
    closeMenu();
    // 끌던 원본이 이 렌더로 사라지면 `dragend` 가 오지 않는다 - 여기서 버린다.
    dragId = '';
    stopEdge();
    const el = ensurePop();
    if (!popOpen) { el.hidden = true; el.innerHTML = ''; return; }
    el.hidden = false;
    // 이 함수는 팝업을 통째로 다시 그린다 - **치던 검색칸이 사라진다**.
    // 디바운스가 끝나는 순간 포커스가 날아가 한 글자 치고 다시 클릭해야 했다
    // (Codex 8차). 캐럿 자리까지 되살린다.
    const prev = document.activeElement;
    const keepSearch = !!(prev && prev.hasAttribute
                          && prev.hasAttribute('data-scsearch') && el.contains(prev));
    const caret = keepSearch ? [prev.selectionStart, prev.selectionEnd] : null;

    const tops = folders.filter(f => !f.parent);
    const subs = curTop ? folders.filter(f => f.parent === curTop) : [];
    // `drop` 을 붙이면 그 자리에 카드를 떨어뜨려 옮길 수 있다. '전체'는 담는 곳이
    // 아니라 **보기**라서 뺀다 - 거기 떨어뜨렸을 때 어디로 가야 할지가 없다.
    // '폴더 없음'은 진짜 목적지다(분류를 푸는 자리).
    const row = (on, act, id, label, extra, drop) =>
      `<button type="button" class="ia-sc-item${on ? ' is-on' : ''}${extra || ''}"
         data-scact="${act}" data-fid="${escHtml(id)}"${
           drop ? ` data-scdrop="${escHtml(drop)}"` : ''}>${escHtml(label)}</button>`;

    const col1 = [
      row(!curTop && !curNone, 'top', '', '전체'),
      ...tops.map(f => row(curTop === f.id, 'top', f.id, f.name, '', f.id)),
      row(curNone, 'top', 'none', '폴더 없음', '', 'none'),
      `<button type="button" class="ia-sc-item is-add" data-scact="folder-new"
         data-fid="" data-naia-title="대카테고리를 만듭니다">+ 카테고리</button>`,
    ].join('');

    // **소카테고리 칸은 쓰기 전엔 안 보인다**(사용자 지정 2026-08-12).
    // Scene 은 현실적으로 수십 장 규모라, 항상 세 칸을 띄우면 쓰지도 않는 층이
    // 썸네일 자리를 300px 먹는다. 하나라도 만들면 그때 칸이 생긴다 - 데이터는
    // 그대로이므로 나중에 많아져도 되돌릴 일이 없다.
    const showSub = !!curTop && subs.length > 0;
    const col2 = showSub
      ? [
          row(!curSub, 'sub', '', '전체보기'),
          ...subs.map(f => row(curSub === f.id, 'sub', f.id, f.name, '', f.id)),
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
        <span class="ia-sc-pop-title">Scene</span>
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
                  : '아직 모아 둔 씬이 없습니다. Recent 에서 [저장]을 누르세요.'}</div>`}</div>
        </div>
        <div class="ia-sc-col ia-sc-preview">${previewHtml()}</div>
      </div>
    </div>`;
    if (keepSearch) {
      const next = el.querySelector('[data-scsearch]');
      if (next) {
        next.focus();
        try { next.setSelectionRange(caret[0], caret[1]); } catch (_) { /* 무시 */ }
      }
    }
  }

  // 바깥을 누르면 접는다 — 캐릭터 쪽 Assets 와 같은 규약(사용자 지정 2026-08-12).
  //
  // **click(버블)이다.** `pointerdown` 으로 걸면 카드/버튼의 제 핸들러보다 먼저
  // 돌아 방금 연 것을 자기가 닫는다(패널 쪽에서 겪은 함정).
  // '바깥'에서 빼는 것: 이 바 전체(토글·카드·버튼), Scene 팝업과 그 메뉴.
  const BAR_KEEP_OPEN = '.ia-sc-pop, .ia-sc-menu, .ia-sc-hover';

  // 결과 무대 아래 바는 둘뿐이다(왼쪽 Assets · 오른쪽 Scene). 좁은 화면에서 둘 다
  // 펴면 겹치므로(실측: 무대 766px 에 523 + 557 -> 338x173) 하나가 펴지면 다른
  // 하나는 접는다. 서로를 모른 채 문서 이벤트 하나만 주고받는다(사용자 지적).
  const IA_BAR_OPEN = 'naia:ia-bar-open';

  function announceOpen() {
    try {
      document.dispatchEvent(new CustomEvent(IA_BAR_OPEN, {detail: {who: 'scene'}}));
    } catch (_) { /* 무시 */ }
  }

  function onOtherBarOpen(event) {
    const who = event && event.detail ? event.detail.who : '';
    if (!who || who === 'scene') return;
    if (!open) return;
    open = false;                  // 접기만 한다 - 되받아 알리지 않는다
    hideHover();
    render();
  }

  function onBarOutside(event) {
    if (!open) return;
    const t = event.target;
    if (!t || !t.closest) return;
    // **문서에서 떨어져 나간 노드는 '바깥'이 아니다.** [Recent]를 누르면 그
    // 핸들러가 render() 로 바를 통째로 갈아 끼우고 그 뒤에야 클릭이 문서까지
    // 올라온다 - 그때 target 의 조상은 이미 없어서 아래 검사가 전부 빗나가고
    // 방금 편 것을 자기가 닫는다.
    if (!document.contains(t)) return;
    if (root.contains(t)) return;
    if (t.closest(BAR_KEEP_OPEN)) return;
    open = false;
    hideHover();
    render();
  }

  // ---------------------------------------------------------------- 호버 상세
  //
  // 바의 카드는 이름 한 줄이 전부라 **무엇이 든 씬인지 알 수가 없었다**(사용자
  // 지적). 납작한 프롬프트 한 줄을 툴팁으로 띄우던 것으로는 지금 판과 무엇이
  // 다른지가 안 보인다. 올리면 **지금 장전된 씬과의 차이**를 보여준다:
  // 이 카드에만 있는 태그는 강조하고, 지금 판에 있는데 이 카드엔 없는 것은
  // 줄 뒤에 `제거됨:` 으로 단다. 즉 "이걸 적용하면 무엇이 달라지는가"다.
  //
  // Scene 팝업 카드에는 안 단다 - 거기는 누르면 오른쪽에 전체 미리보기가 열린다.
  const HOVER_DELAY = 220;      // 지나가다 스치는 것으로는 안 뜬다
  // id -> 본문. 같은 id 의 본문은 내용이 안 바뀌므로(해시가 곧 id 다) 한 번만
  // 읽는다. 다만 긴 세션에서 무한히 자라지 않게 오래된 것부터 버린다 - Map 은
  // 넣은 순서를 지키므로 첫 키가 가장 오래된 것이다(Codex 10차 P3).
  const BODY_CACHE_MAX = 60;
  const bodyCache = new Map();
  let hoverEl = null;
  let hoverTimer = 0;
  let hoverId = '';
  let hoverSeq = 0;

  function ensureHover() {
    if (hoverEl && document.body.contains(hoverEl)) return hoverEl;
    hoverEl = document.createElement('div');
    hoverEl.className = 'ia-sc-hover';
    hoverEl.hidden = true;
    document.body.appendChild(hoverEl);   // 팝업과 같은 이유로 body 직계
    return hoverEl;
  }

  function hideHover() {
    if (hoverTimer) { clearTimeout(hoverTimer); hoverTimer = 0; }
    hoverId = '';
    hoverSeq += 1;                        // 늦게 온 본문이 다시 띄우지 못하게
    if (hoverEl && !hoverEl.hidden) { hoverEl.hidden = true; hoverEl.innerHTML = ''; }
  }

  const flat = obj => Object.keys(obj || {}).flatMap(k => (obj || {})[k] || []);

  /** 지금 장전된 씬. 패널이 없거나 아직 준비 전이면 비교를 접는다(전부 '같음'
   *  으로 두면 차이가 없다고 거짓말을 하게 된다 - 아예 표시를 안 한다). */
  function currentScene() {
    const panel = typeof getPanel === 'function' ? getPanel() : null;
    if (!panel || typeof panel.getSceneGlobals !== 'function') return null;
    try {
      return {globals: panel.getSceneGlobals() || {},
              chars: panel.getSceneChars() || []};
    } catch (_) {
      return null;
    }
  }

  function tagRow(label, mine, cur, cmp) {
    const list = (Array.isArray(mine) ? mine : []).filter(Boolean);
    const now = (Array.isArray(cur) ? cur : []).filter(Boolean);
    // **개수로 센다.** 집합으로 보면 같은 태그가 지금 판의 두 슬롯에 있고 카드엔
    // 하나뿐일 때 '하나 빠진다'를 놓친다(Codex 10차 P3). 남은 개수를 깎아 가며
    // 짝을 맞추고, 못 맞춘 것만 추가/제거로 센다.
    const left = new Map();
    for (const t of now) left.set(t, (left.get(t) || 0) + 1);
    const isAdd = [];
    for (const t of list) {
      const n = left.get(t) || 0;
      isAdd.push(cmp && n <= 0);
      if (n > 0) left.set(t, n - 1);
    }
    const gone = [];
    if (cmp) for (const [t, n] of left) for (let i = 0; i < n; i++) gone.push(t);
    if (!list.length && !gone.length) return '';
    const chips = list.map((t, i) =>
      `<span class="ia-sc-hchip${isAdd[i] ? ' is-add' : ''}"
        >${escHtml(t)}</span>`).join('');
    const del = gone.length
      ? `<span class="ia-sc-hgone">제거됨:</span>` + gone.map(t =>
          `<span class="ia-sc-hchip is-del">${escHtml(t)}</span>`).join('')
      : '';
    return `<div class="ia-sc-hrow"><span class="ia-sc-hlabel">${escHtml(label)}</span>
      <span class="ia-sc-hval">${chips}${del}</span></div>`;
  }

  function hoverHtml(row, body) {
    const name0 = String(row.name || '') || String(row.summary || '') || '이름 없음';
    // **본문을 못 읽었으면 비교하지 않는다.** 빈 본문과 견주면 지금 판의 것이
    // 전부 '제거됨'으로 뜬다 - 정작 [복원]은 본문이 없어 동작도 못 하므로
    // 화면이 거짓말을 한다(Codex 10차 P2 · 재현).
    if (!body) {
      return `<div class="ia-sc-htitle">${escHtml(name0)}</div>
        <div class="ia-sc-hnote">이 씬의 내용을 읽지 못했습니다 — 차이를 낼 수 없습니다</div>`;
    }
    const cur = currentScene();
    const cmp = !!cur;
    const g = (body && body.globals) || {};
    const cg = (cur && cur.globals) || {};
    const chars = Array.isArray(body && body.chars) ? body.chars : [];
    const cchars = (cur && Array.isArray(cur.chars)) ? cur.chars : [];
    const pick = o => (((o || {}).rating || {}).picks || []).filter(p => p && p !== 'none');
    const head = `<div class="ia-sc-htitle">${escHtml(name0)}</div>${
      cmp ? '' : '<div class="ia-sc-hnote">지금 씬을 읽을 수 없어 차이를 못 냅니다</div>'}`;
    const globalRows = [
      tagRow('씬 태그', flat(g.slots), flat(cg.slots), cmp),
      tagRow('구도', g.composition_tags, cg.composition_tags, cmp),
      tagRow('Rating', pick(g), pick(cg), cmp),
      tagRow('자유 입력', g.free_text ? [g.free_text] : [],
             cg.free_text ? [cg.free_text] : [], cmp),
      tagRow('전역 네거티브', g.fast_negative ? [g.fast_negative] : [],
             cg.fast_negative ? [cg.fast_negative] : [], cmp),
    ].join('');

    const charRows = chars.map((c, i) => {
      const o = cchars[i] || {};
      const isNew = cmp && i >= cchars.length;
      const rows = [
        tagRow('프롬프트', flat(c.fields), flat(o.fields), cmp && !isNew),
        tagRow('ALT·시선', [...(c.alt || []), ...(c.gaze || [])],
               [...(o.alt || []), ...(o.gaze || [])], cmp && !isNew),
        tagRow('네거티브', flat(c.neg), flat(o.neg), cmp && !isNew),
      ].join('');
      return `<div class="ia-sc-hchar"><div class="ia-sc-hchead">C${i + 1}
        <span class="ia-sc-hsub">${escHtml(
          (c.gender === 'male' ? 'boy' : 'girl') + ' · ' + (c.pos || 'C3'))}</span>${
        isNew ? '<span class="ia-sc-hnew">새 캐릭터</span>' : ''}</div>
        ${rows || '<div class="ia-sc-hempty">상황 태그 없음</div>'}</div>`;
    }).join('');

    // 지금 판에만 있는 캐릭터 - 적용하면 사라진다.
    const dropped = cmp && cchars.length > chars.length
      ? `<div class="ia-sc-hchar is-drop">C${chars.length + 1}${
          cchars.length > chars.length + 1 ? `~C${cchars.length}` : ''} 제거됨</div>`
      : '';
    return head + globalRows + charRows + dropped;
  }

  function placeHover(card) {
    const el = ensureHover();
    const r = card.getBoundingClientRect();
    const b = el.getBoundingClientRect();
    // 카드 위쪽에 띄운다(바가 화면 아래에 붙어 있다). 자리가 없으면 아래로.
    let y = r.top - b.height - 8;
    if (y < 6) y = Math.min(r.bottom + 8, window.innerHeight - b.height - 6);
    const x = Math.max(6, Math.min(r.left, window.innerWidth - b.width - 6));
    el.style.left = `${x}px`;
    el.style.top = `${Math.max(6, y)}px`;
  }

  async function showHover(card) {
    const id = card.dataset.scid;
    const row = recent.find(r => r.id === id);
    if (!id || !row) return;
    const seq = ++hoverSeq;
    hoverId = id;
    let body = bodyCache.get(id);
    if (body === undefined) {
      try {
        body = await api(`/scene?id=${encodeURIComponent(id)}`);
        bodyCache.set(id, body);
        while (bodyCache.size > BODY_CACHE_MAX) {
          bodyCache.delete(bodyCache.keys().next().value);
        }
      } catch (_) {
        body = null;      // 캐시하지 않는다 - 다음에 올리면 다시 읽어 본다
      }
    }
    if (seq !== hoverSeq || hoverId !== id) return;   // 그새 다른 데로 갔다
    const el = ensureHover();
    el.innerHTML = hoverHtml(row, body);
    el.hidden = false;
    placeHover(card);
  }

  function onOver(event) {
    const card = event.target && event.target.closest
      ? event.target.closest('.ia-sc-card') : null;
    if (!card || !card.dataset.scid) return;
    if (card.dataset.scid === hoverId) return;        // 같은 카드 안에서 움직인 것
    hideHover();
    hoverTimer = setTimeout(() => { hoverTimer = 0; showHover(card); }, HOVER_DELAY);
  }

  function onOut(event) {
    const card = event.target && event.target.closest
      ? event.target.closest('.ia-sc-card') : null;
    if (!card) return;
    const to = event.relatedTarget;
    if (to && card.contains(to)) return;              // 카드 안에서 옮겨 다닌 것
    hideHover();
  }

  // ---------------------------------------------------------------- 우클릭 메뉴
  //
  // 카드에서 버튼을 걷어낸 대가로 여기가 **유일한 손잡이**가 된다. 미리보기를 열고
  // 아래 버튼 바까지 마우스를 내리는 것과, 카드를 보고 그 자리에서 뽑는 것은 다른
  // 동작이다(사용자 지정 2026-08-12).
  //
  // 팝업과 마찬가지로 **body 직계**다 - `.viewer-wrapper` 안에 넣으면 z 가 접힌다.
  let menuEl = null;

  function ensureMenu() {
    if (menuEl && document.body.contains(menuEl)) return menuEl;
    menuEl = document.createElement('div');
    menuEl.className = 'ia-sc-menu';
    menuEl.hidden = true;
    document.body.appendChild(menuEl);
    // 메뉴 항목도 `data-scact` 를 달고 있으므로 같은 처리기로 보낸다.
    menuEl.addEventListener('click', onMenuClick);
    menuEl.addEventListener('contextmenu', e => e.preventDefault());
    return menuEl;
  }

  function menuHtml(id) {
    const row = savedRows.find(r => r.id === id) || {};
    const sid = escHtml(id);
    const item = (act, label, cls, hint) =>
      `<button type="button" class="ia-sc-mi${cls || ''}" data-scact="${act}"
         data-scid="${sid}">${escHtml(label)}${
           hint ? `<span class="ia-sc-mhint">${escHtml(hint)}</span>` : ''}</button>`;
    // **폴더는 여기 담지 않는다**(사용자 결정 2026-08-12). 폴더 목록을 펼쳐 두면
    // 몇 개 안 될 때만 편하고, 스무 개쯤 되면 메뉴가 스크롤 덩어리가 된다.
    // 분류는 끌기 하나로 통일한다 - 지금 폴더는 카드 밑에 이미 적혀 있다.
    return `<div class="ia-sc-mname">${escHtml(
              String(row.name || '') || String(row.summary || '') || '이름 없음')}</div>
      ${item('gen-now', '즉시 생성', '', '작업판 그대로')}
      ${item('apply', '적용', ' is-main')}
      ${item('apply-gen', '적용 + 생성')}
      <div class="ia-sc-msep"></div>
      ${item('rename', '이름 바꾸기…')}
      ${item('unsave', 'Scene 에서 내리기', ' is-danger', '지우지 않습니다')}`;
  }

  function openMenu(id, px, py) {
    const el = ensureMenu();
    el.innerHTML = menuHtml(id);
    el.hidden = false;
    // 그린 뒤에야 크기를 알 수 있다 - 화면 밖으로 나가면 안쪽으로 당긴다.
    const r = el.getBoundingClientRect();
    const x = Math.max(6, Math.min(px, window.innerWidth - r.width - 6));
    const y = Math.max(6, Math.min(py, window.innerHeight - r.height - 6));
    el.style.left = `${x}px`;
    el.style.top = `${y}px`;
    document.addEventListener('pointerdown', onDocDown, true);
    window.addEventListener('resize', closeMenu);
    // 목록을 굴리면 메뉴만 제자리에 떠 있게 된다 - 그때는 닫는다.
    window.addEventListener('scroll', closeMenu, true);
  }

  function closeMenu() {
    if (!menuEl || menuEl.hidden) return;
    menuEl.hidden = true;
    menuEl.innerHTML = '';
    document.removeEventListener('pointerdown', onDocDown, true);
    window.removeEventListener('resize', closeMenu);
    window.removeEventListener('scroll', closeMenu, true);
  }

  function onDocDown(e) {
    if (menuEl && menuEl.contains(e.target)) return;
    closeMenu();
  }

  function onMenuClick(e) {
    const btn = e.target && e.target.closest ? e.target.closest('[data-scact]') : null;
    closeMenu();                 // 무엇을 눌렀든 메뉴는 닫는다
    if (btn) onClick(e);
  }

  function onContextMenu(e) {
    const card = e.target && e.target.closest ? e.target.closest('.ia-sc-scard') : null;
    if (!card || !card.dataset.scid) return;
    e.preventDefault();
    e.stopPropagation();
    openMenu(card.dataset.scid, e.clientX, e.clientY);
  }

  // ---------------------------------------------------------------- 끌어 옮기기
  //
  // 카드를 카테고리 칸에 떨어뜨리면 그 폴더로 옮긴다. `renderPop()` 이 팝업을
  // 통째로 다시 그리므로 **위임**으로 건다 - 노드마다 걸면 다음 렌더에서 사라진다.
  let dragId = '';

  function onDragStart(event) {
    const card = event.target && event.target.closest
      ? event.target.closest('.ia-sc-scard') : null;
    if (!card || !card.dataset.scid) return;
    dragId = card.dataset.scid;
    closeMenu();
    hideHover();
    markZones(true);
    try {
      event.dataTransfer.setData(DND_MIME, dragId);
      // 일부 브라우저는 표준 자료형이 하나도 없으면 끌기를 취소한다.
      event.dataTransfer.setData('text/plain', dragId);
      event.dataTransfer.effectAllowed = 'move';
    } catch (_) { /* 무시 - dragId 로도 동작한다 */ }
    card.classList.add('is-dragging');
  }

  function markZones(on) {
    if (!popEl) return;
    popEl.querySelectorAll('.ia-sc-col1, .ia-sc-col2')
      .forEach(el => el.classList.toggle('is-dropzone', !!on));
  }

  function onDragEnd() {
    dragId = '';
    stopEdge();
    markZones(false);
    if (!popEl) return;
    popEl.querySelectorAll('.is-dragging').forEach(el => el.classList.remove('is-dragging'));
    popEl.querySelectorAll('.is-drop').forEach(el => el.classList.remove('is-drop'));
  }

  function dropTarget(event) {
    const el = event.target && event.target.closest
      ? event.target.closest('[data-scdrop]') : null;
    if (!el) return null;
    // **우리 것만 받는다.** 파일이나 다른 앱의 글을 떨어뜨렸을 때 폴더가 반응하면
    // 안 된다. 끌기 중에는 `types` 만 볼 수 있고 값은 drop 에서야 읽힌다.
    //
    // 판별은 **자료형만으로** 한다. `dragId` 를 통행증으로 쓰면, 끌기 도중 목록이
    // 다시 그려져 원본 카드가 사라졌을 때 `dragend` 가 오지 않아 값이 남고, 그
    // 뒤 남의 파일/글이 이 검사를 통과해 **이전에 끌던 씬이 옮겨진다**
    // (Codex 9차, 실측 재현). `dragId` 는 값을 못 읽었을 때의 보루로만 쓴다.
    const types = (event.dataTransfer && event.dataTransfer.types) || [];
    const mine = types.includes ? types.includes(DND_MIME)
      : Array.prototype.indexOf.call(types, DND_MIME) >= 0;
    return mine ? el : null;
  }

  // 가장자리 자동 스크롤. `dragover` 는 멈춰 있어도 계속 오지만 간격이 들쭉날쭉해
  // 이벤트마다 조금씩 미는 방식은 끊긴다 - 타이머로 일정하게 굴린다.
  let edgeTimer = 0;

  function stopEdge() {
    if (edgeTimer) { clearInterval(edgeTimer); edgeTimer = 0; }
  }

  function edgeScroll(event) {
    const col = event.target && event.target.closest
      ? event.target.closest('.ia-sc-col1, .ia-sc-col2') : null;
    stopEdge();
    if (!col || col.scrollHeight <= col.clientHeight) return;
    const r = col.getBoundingClientRect();
    const EDGE = 34;
    const dir = event.clientY < r.top + EDGE ? -1
      : (event.clientY > r.bottom - EDGE ? 1 : 0);
    if (!dir) return;
    edgeTimer = setInterval(() => { col.scrollTop += dir * 12; }, 30);
  }

  function onDragOver(event) {
    const el = dropTarget(event);
    if (el || dragId) edgeScroll(event);     // 목적지 사이 빈틈에서도 굴러가야 한다
    if (!el) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
    el.classList.add('is-drop');
  }

  function onDragLeave(event) {
    const el = event.target && event.target.closest
      ? event.target.closest('[data-scdrop]') : null;
    if (el) el.classList.remove('is-drop');
    // 칸을 벗어나면 굴리기를 멈춘다. `dragover` 는 창 밖으로 나가면 더 오지
    // 않으므로, 여기서 안 끄면 계속 굴러간다(Codex 10차 P3).
    if (event.target && event.target.closest
        && event.target.closest('.ia-sc-col1, .ia-sc-col2')) stopEdge();
  }

  async function onDrop(event) {
    const el = dropTarget(event);
    if (!el) return;
    event.preventDefault();
    stopEdge();
    markZones(false);
    el.classList.remove('is-drop');
    let id = dragId;
    try { id = event.dataTransfer.getData(DND_MIME) || id; } catch (_) { /* dragId 로 */ }
    const target = el.dataset.scdrop === 'none' ? '' : el.dataset.scdrop;
    dragId = '';
    if (!id) return;
    const row = savedRows.find(r => r.id === id);
    if (row && String(row.folder || '') === target) return;   // 제자리면 아무것도 안 한다
    // 앞선 이동이 아직 돌아오지 않았는데 또 떨어뜨리면, 두 요청의 끝나는 순서에
    // 따라 최종 폴더와 토스트 순서가 뒤집힌다 - 버튼 경로와 같은 빗장을 건다
    // (Codex 9차). 카드가 여전히 화면에 남아 있어 실제로 두 번 떨어뜨릴 수 있다.
    if (busy) return;
    busy = true;
    try {
      await api('/scene/update', {id, folder: target});
      showToast(movedMsg(target), 'info');
      await loadSaved();
    } catch (exc) {
      showToast(`옮기지 못했습니다: ${exc.message}`, 'error');
    } finally {
      busy = false;
    }
  }

  // ---------------------------------------------------------------- 동작
  /** 본문을 읽는다. 미리보기로 이미 읽어 뒀으면 그것을 쓴다(같은 것을 두 번 부르지 않게). */
  async function sceneBody(id) {
    if (previewId === id && previewBody) return previewBody;
    return api(`/scene?id=${encodeURIComponent(id)}`);
  }

  async function applyScene(id, andGenerate) {
    const panel = getPanel && getPanel();
    if (!panel || !panel.applySceneSnapshot) return;
    try {
      const body = await sceneBody(id);
      const ok = panel.applySceneSnapshot(body);
      if (!ok) { showToast('씬을 되돌리지 못했습니다.', 'error'); return; }
      closeSaved();
      if (andGenerate && typeof generateNow === 'function') {
        showToast('씬을 적용하고 생성합니다.', 'info');
        generateNow();
      } else {
        showToast('씬을 적용했습니다.', 'info');
      }
    } catch (exc) {
      showToast(`씬을 읽지 못했습니다: ${exc.message}`, 'error');
    }
  }

  /** 작업판을 건드리지 않고 이 씬으로 한 장 뽑는다. 계산은 패널이, 발화는 app.js 가 한다. */
  async function generateSceneOnly(id) {
    if (typeof generateScene !== 'function') {
      showToast('이 화면에서는 즉시 생성을 쓸 수 없습니다.', 'error');
      return;
    }
    try {
      const body = await sceneBody(id);
      const sent = await generateScene(body);
      if (sent === false) {
        // 생성 중이거나 연결이 끊겼을 때다 - 팝업은 닫지 않는다(다시 누를 수 있게).
        showToast('지금은 생성할 수 없습니다.', 'error');
        return;
      }
      showToast('작업판은 그대로 두고 이 씬으로 생성합니다.', 'info');
      closeSaved();
    } catch (exc) {
      showToast(`생성하지 못했습니다: ${exc.message}`, 'error');
    }
  }

  async function saveScene(id) {
    try {
      await api('/scene/save', {id});
      showToast('Scene 으로 올렸습니다. 이름은 [Scene]에서 붙일 수 있습니다.', 'info');
      fetchRecent();
      if (popOpen) loadSaved();
    } catch (exc) {
      showToast(`저장하지 못했습니다: ${exc.message}`, 'error');
    }
  }

  /** 한 줄 입력. **`showAppDialog(message, options)` 다** — 첫 인자가 문자열이고
   *  옵션은 `{type, title, okText, cancelText, defaultValue}` 다. 객체를 첫 인자로
   *  넘겼더니 안에서 `escHtml(message)` 가 `s.replace is not a function` 으로 터져
   *  이름·폴더 버튼이 전부 죽었다(사용자 지적 2026-08-12 · 계약을 안 보고 지어냈다).
   *  prompt 는 문자열(취소면 null)을, confirm 은 true/false 를 준다. */
  async function askText(title, initial) {
    if (typeof showAppDialog !== 'function') return null;
    const got = await showAppDialog('', {
      type: 'prompt', title,
      defaultValue: String(initial || ''),
      okText: '확인', cancelText: '취소',
    });
    if (got === null || got === undefined || got === false) return null;
    return String(got).trim();
  }

  function openSaved() {
    popOpen = true;
    loadSaved();
    document.addEventListener('keydown', onKey, true);
  }

  function closeSaved() {
    if (!popOpen) return;
    popOpen = false;
    closeMenu();
    dragId = '';
    stopEdge();
    clearPreview();
    document.removeEventListener('keydown', onKey, true);
    renderPop();
  }

  function onKey(e) {
    if (e.key !== 'Escape') return;
    // 메뉴가 떠 있으면 **그것만** 닫는다 - 한 번에 둘이 닫히면 되돌릴 길이 없다.
    if (menuEl && !menuEl.hidden) { e.stopPropagation(); closeMenu(); return; }
    if (popOpen) { e.stopPropagation(); closeSaved(); }
  }

  function onInput(e) {
    const el = e.target;
    if (!el || !el.hasAttribute || !el.hasAttribute('data-scsearch')) return;
    query = String(el.value || '');
    if (searchTimer) clearTimeout(searchTimer);
    // 한 글자마다 부르면 목록이 깜빡인다 — 캐릭터 패널과 같은 간격.
    searchTimer = setTimeout(() => {
      if (popOpen) { clearPreview(); loadSaved(); }
    }, 220);
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
      if (act === 'toggle') {
        open = !open;
        render();
        if (open) { announceOpen(); await fetchRecent(); }
      }
      else if (act === 'open-saved') openSaved();
      else if (act === 'close-saved') closeSaved();
      else if (act === 'preview') await openPreview(id);
      else if (act === 'apply') await applyScene(id, false);
      else if (act === 'apply-gen') await applyScene(id, true);
      else if (act === 'gen-now') await generateSceneOnly(id);
      else if (act === 'save') await saveScene(id);
      else if (act === 'top') {
        const fid = btn.dataset.fid || '';
        curNone = fid === 'none';
        curTop = curNone ? '' : fid;
        curSub = '';               // 대카테고리를 바꾸면 소카테고리 선택은 버린다
        clearPreview();
        await loadSaved();
      } else if (act === 'sub') {
        curSub = btn.dataset.fid || '';
        clearPreview();
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
            ? await showAppDialog(
                (deep ? '하위 카테고리도 함께 사라집니다. ' : '')
                + '폴더만 지웁니다 — 안에 든 씬은 사라지지 않고 폴더 없음으로 옮겨집니다.',
                {type: 'confirm', title: '폴더를 지울까요?',
                 okText: '지우기', cancelText: '취소'})
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
          showToast(movedMsg(next), 'info');
          await loadSaved();
        }
      } else if (act === 'unsave') {
        await api('/scene/save', {id, on: false});
        showToast('Scene 에서 내렸습니다. Recent 에는 남아 있습니다.', 'info');
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
  root.addEventListener('mouseover', onOver);
  root.addEventListener('mouseout', onOut);
  // 스크롤·창 크기 변경이면 카드가 마우스 밑에서 빠져나간다 - 따라다니지 않고 닫는다.
  window.addEventListener('scroll', hideHover, true);
  window.addEventListener('resize', hideHover);
  window.addEventListener('resize', fitStrip);
  document.addEventListener('click', onBarOutside);
  document.addEventListener(IA_BAR_OPEN, onOtherBarOpen);

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
      closeMenu();
      hideHover();
      stopEdge();
      markZones(false);
      if (hoverEl && hoverEl.parentNode) hoverEl.parentNode.removeChild(hoverEl);
      hoverEl = null;
      window.removeEventListener('scroll', hideHover, true);
      window.removeEventListener('resize', hideHover);
      window.removeEventListener('resize', fitStrip);
      document.removeEventListener('click', onBarOutside);
      document.removeEventListener(IA_BAR_OPEN, onOtherBarOpen);
      root.removeEventListener('mouseover', onOver);
      root.removeEventListener('mouseout', onOut);
      if (menuEl && menuEl.parentNode) menuEl.parentNode.removeChild(menuEl);
      menuEl = null;
      root.removeEventListener('click', onClick);
      root.removeEventListener('input', onInput);
      document.removeEventListener('keydown', onKey, true);
      if (searchTimer) clearTimeout(searchTimer);
      if (popEl && popEl.parentNode) popEl.parentNode.removeChild(popEl);
      popEl = null;
    },
  };
}
