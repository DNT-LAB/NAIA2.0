/**
 * V5 Scene 패널 (Fn > V5 Scene).
 *
 * **Event > Scene** 두 층이다(사용자 지정). 이벤트는 만화 한 편, 컷은 그 안의 한 장면.
 * 사용자는 이벤트를 먼저 만들고 그 안에 컷을 쌓는다. 담는 범위와 규약은
 * `core/v5_scene_store.py` 머리 주석. 네거티브는 담지 않는다 - 사용자의 네거티브를
 * 덮어쓰는 것이 치명적이라서다.
 *
 * 화면은 **이벤트 하나만 연다.** 목록을 통째로 펼치면 깊이가 3단이 되는데, 실제 작업은
 * "이벤트 하나를 열어놓고 컷 사이를 오가는" 모양이라 드롭다운 하나면 족하다(사용자 지정).
 *
 * ⚠️ 열린 이벤트는 **프론트가 기억한다**(localStorage). 서버가 들면 새로고침·재접속·창
 *    두 개에서 어긋난다 - 조작마다 `{event, name}` 을 실어 보내고 서버는 답만 한다.
 * ⚠️ 조작은 전부 범용 `setModuleParam('v5_scene', …)` 을 탄다 - 새 WS 메시지 타입을
 *    만들지 않기 위해서다(웹 스모크 계약이 타입을 순서대로 센다). 그림만 HTTP 다.
 */

const EVENT_KEY = 'naia.v5scene.event.v1';

export function createV5ScenePanel({
  panel, escHtml, showToast, setModuleParam,
  // ⚠️ `window.prompt` / `window.confirm` 을 쓰면 안 된다. **Electron 은 `prompt` 를
  //    구현하지 않아** 아무 일도 안 일어난다(제보: [+ 이벤트] 가 먹통). 앱 자체
  //    대화상자를 받아 쓴다 - 생김새도 나머지 화면과 같아진다.
  showPromptDialog = null,
  showConfirmDialog = null,
  requestGenerate = null,
}) {
  let lastState = null;
  let openName = '';           // 펼쳐 둔 컷
  // ── 연속 생성 ────────────────────────────────────────────────────────────
  // 컷을 순서대로 불러오며 한 장씩 낸다(사용자 지정). 와일드카드가 골칫거리라서
  // **먼저 한 컷을 불러온 뒤에만** 시작할 수 있게 한다 - 그 사이에 사용자가 자기
  // 와일드카드를 바꿔 두면 그대로 반영된다.
  let appliedName = '';        // 방금 불러온 컷(이 컷에서만 연속 생성을 켤 수 있다)
  let running = false;         // 연속 생성 진행 중
  let generatingNow = false;
  let watchdog = null;         // 생성이 시작되는지 지켜보는 타이머
  let awaitingApply = false;   // 다음 컷의 불러오기 응답을 기다리는 중
  let applyWait = null;        // 그 응답의 뒷문 타이머
  let doneWait = null;         // 완료 신호가 오는지 지켜보는 타이머

  function escAttr(value) {
    return String(value ?? '').replace(/[&<>"']/g, char => (
      {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]
    ));
  }

  /** 저장 이름을 백엔드와 **같은 규칙**으로 정제한다.
   *
   * ⚠️ SSOT 는 `core/v5_scene_store.sanitize_scene_name` 이다. 여기서 흉내 내는 이유는
   *    덮어쓰기 확인을 **저장을 보내기 전에** 해야 하기 때문이다 - 날것으로 견주면
   *    `A:B` 가 목록의 `AB` 와 안 맞아 확인 없이 덮어쓴다(실증됨). 규칙이 바뀌면 둘 다
   *    고쳐야 한다.
   */
  function sanitizeName(value) {
    return String(value ?? '')
      .replace(/[<>:"/\\|?*]/g, '')
      .trim().replace(/^\.+|\.+$/g, '')
      .replace(/^_+/, '')
      .trim();
  }

  function rememberedEvent() {
    try { return String(globalThis.localStorage?.getItem(EVENT_KEY) || ''); } catch (_) { return ''; }
  }

  function rememberEvent(name) {
    try { globalThis.localStorage?.setItem(EVENT_KEY, String(name || '')); } catch (_) { /* 사파리 프라이빗 */ }
  }

  function activeEvent() {
    return String(lastState?.event || '');
  }

  function onOpen() {
    setModuleParam('v5_scene', 'refresh', {event: rememberedEvent()});
  }

  // 컷 검색칸은 **일부러 없앴다**(사용자 지정). 한 이벤트에 컷 몇 개인 규모라 목록이
  // 한눈에 들어오고, 검색칸이 오히려 저장칸과 헷갈린다. 규모가 커지면 되살린다.

  // ── 이벤트 고르기 ────────────────────────────────────────────────────────
  // ⚠️ 네이티브 `<select>` 를 쓰면 **Windows 기본 드롭다운**이 뜬다 - 흰 바탕에 시스템
  //    폰트라 이 화면에서 혼자 튀고 글자가 안 읽힌다(사용자 제보). 캐릭터 슬롯의
  //    Connect 메뉴와 **같은 결·같은 CSS 선택자**를 쓴다(`.cq-connect-menu` 와 공유).
  // ⚠️ body 직계 + fixed 다. 패널이 `overflow-y: auto` 라 안에 그리면 잘린다.
  let eventMenuEl = null;
  let eventMenuDismiss = null;
  let menuClosedFrom = null;   // 방금 닫힌 원인이 된 버튼(아래 재열림 방지)

  function closeEventMenu() {
    if (eventMenuDismiss) {
      document.removeEventListener('mousedown', eventMenuDismiss, true);
      document.removeEventListener('keydown', eventMenuDismiss, true);
      window.removeEventListener('resize', eventMenuDismiss, true);
      window.removeEventListener('scroll', eventMenuDismiss, true);
      eventMenuDismiss = null;
    }
    eventMenuEl?.remove();
    eventMenuEl = null;
    panel?.querySelector('[data-scene-event-pick]')?.setAttribute('aria-expanded', 'false');
  }

  function openEventMenu(button) {
    closeEventMenu();
    const events = lastState?.events || [];
    if (!events.length) return;
    const active = activeEvent();
    eventMenuEl = document.createElement('div');
    eventMenuEl.className = 'cq-connect-menu scene-event-menu';
    eventMenuEl.setAttribute('role', 'listbox');
    eventMenuEl.innerHTML =
      '<div class="cq-connect-menu-head">이벤트</div>'
      + events.map(name =>
          `<button type="button" class="cq-connect-item${name === active ? ' is-on' : ''}"`
          + ` role="option" aria-selected="${name === active ? 'true' : 'false'}"`
          + ` data-scene-event-pickone="${escAttr(name)}"><b>${escHtml(name)}</b></button>`
        ).join('');
    document.body.appendChild(eventMenuEl);
    button.setAttribute('aria-expanded', 'true');

    const rect = button.getBoundingClientRect();
    const mw = eventMenuEl.offsetWidth, mh = eventMenuEl.offsetHeight;
    const margin = 6;
    // 버튼 **왼쪽 끝**에 맞춘다 - 이 버튼은 줄 왼쪽에 있어 그쪽이 자연스럽다.
    const left = Math.max(margin, Math.min(rect.left, window.innerWidth - mw - margin));
    let top = rect.bottom + 4;
    if (top + mh > window.innerHeight - margin) top = Math.max(margin, rect.top - mh - 4);
    eventMenuEl.style.left = `${Math.round(left)}px`;
    eventMenuEl.style.top = `${Math.round(top)}px`;
    // 버튼보다 좁으면 어색하다 - 최소한 버튼만큼은 벌린다.
    eventMenuEl.style.minWidth = `${Math.round(rect.width)}px`;

    eventMenuEl.addEventListener('click', event => {
      const pick = event.target.closest('[data-scene-event-pickone]');
      if (!pick) return;
      const name = pick.dataset.sceneEventPickone || '';
      closeEventMenu();
      if (name === activeEvent()) return;
      rememberEvent(name);
      openName = '';        // 남의 이벤트에서 쓰던 펼침 상태다
      // 이벤트를 넘어가며 잇지 않는다 - 다른 만화의 컷을 이어 만들 이유가 없다.
      stopRun(running ? '이벤트를 바꿔 연속 생성을 멈췄습니다' : '');
      appliedName = '';
      setModuleParam('v5_scene', 'refresh', {event: name});
    });

    eventMenuDismiss = event => {
      if (event.type === 'keydown' && event.key !== 'Escape') return;
      if (event.type === 'mousedown' && eventMenuEl?.contains(event.target)) return;
      // ⚠️ `mousedown` 은 `click` 보다 먼저다. 열린 상태에서 버튼을 다시 누르면
      //    여기서 닫히고 이어 온 click 이 **다시 연다** - 닫히지 않는 것처럼 보인다.
      //    누른 자리가 그 버튼이면 표시를 남겨 click 이 건너뛰게 한다.
      if (event.type === 'mousedown') {
        menuClosedFrom = event.target?.closest?.('[data-scene-event-pick]') || null;
      }
      closeEventMenu();
    };
    document.addEventListener('mousedown', eventMenuDismiss, true);
    document.addEventListener('keydown', eventMenuDismiss, true);
    window.addEventListener('resize', eventMenuDismiss, true);
    window.addEventListener('scroll', eventMenuDismiss, true);
  }

  function render(state) {
    if (state) {
      lastState = state;
      // 서버가 연 이벤트를 기억한다 - 처음 열 때(기억 없음)와 이벤트를 만든 직후에도 맞는다.
      if (state.event) rememberEvent(state.event);
    }
    if (!panel || !lastState) return;
    // 다시 그리면 메뉴가 가리키던 버튼이 사라진다 - 떠 있는 채로 두면 허공에 남는다.
    closeEventMenu();
    // 다음 컷의 불러오기 응답이 왔다 - 이제 내면 그 컷의 캐릭터로 나간다.
    if (running && awaitingApply && state) {
      awaitingApply = false;
      clearApplyWait();
      globalThis.setTimeout(() => { if (running) fire('다음 컷을 시작하지 못했습니다'); }, 0);
    }
    const events = lastState.events || [];
    const active = activeEvent();
    const all = lastState.scenes || [];
    const mode = String(lastState.current_mode || '');

    if (!events.length) {
      // 이벤트가 하나도 없으면 만들기 칸만 보여 준다 - 컷을 담을 곳이 없는데 저장 칸을
      // 띄우면 눌러 놓고 왜 안 되는지 모른다(사용자 지정: 이벤트를 먼저 만든다).
      panel.innerHTML = `
        <div class="scene-empty">아직 이벤트가 없습니다.<br>
          만화 한 편에 해당하는 <b>이벤트</b>를 먼저 만드세요.</div>
        <div class="scene-save">
          <input type="text" class="scene-save-name" id="sceneEventName" placeholder="새 이벤트 이름"
                 maxlength="80" autocomplete="off">
          <button type="button" class="scene-save-btn" data-scene-event-create="1">만들기</button>
        </div>`;
      return;
    }

    panel.innerHTML = `
      <div class="scene-bar">
        <button type="button" class="scene-event-pick" id="sceneEventPick" data-scene-event-pick="1"
                aria-haspopup="listbox" aria-expanded="false" data-naia-title="열어 둘 이벤트">
          <span class="scene-event-pick-t">${escHtml(active || '(이벤트 없음)')}</span>
          <span class="scene-event-pick-c" aria-hidden="true">▾</span>
        </button>
        <button type="button" class="scene-bar-btn" data-scene-event-new="1"
                data-naia-title="새 이벤트를 만듭니다">+ 이벤트</button>
        <button type="button" class="scene-bar-btn" data-scene-folder="1"
                data-naia-title="이 이벤트의 폴더를 탐색기에서 엽니다">폴더</button>
      </div>
      <div class="scene-count">${all.length} 컷 · ${escHtml(mode)}${running
        // ⚠️ 중단은 **접어도 닿아야 한다.** 컷 카드 안에만 두면 카드를 접는 순간
        //    멈출 방법이 사라진다 - 돌고 있는데 세울 수가 없다.
        ? ` <button type="button" class="scene-run is-stop is-inline"`
          + ` data-scene-run-stop="1">생성 중단</button>`
        : ''}</div>
      ${all.length
        ? `<div class="scene-list">${all.map((scene, index) =>
            sceneRow(scene, index + 1, all.length)).join('')}</div>`
        : '<div class="scene-empty">이 이벤트에는 아직 컷이 없습니다.<br>'
          + '구도를 만든 뒤 이름을 적고 <b>저장</b>을 누르세요.</div>'}
      <div class="scene-save">
        <input type="text" class="scene-save-name" id="sceneSaveName" maxlength="80" autocomplete="off"
               placeholder="이 구도를 담을 이름 (현재 메인 + 캐릭터 + 해상도 저장)">
        <button type="button" class="scene-save-btn" data-scene-save="1">저장</button>
      </div>
    `;
  }

  function sceneRow(scene, ordinal, total) {
    const name = String(scene.name || '');
    const wrongMode = scene.mode && lastState && scene.mode !== lastState.current_mode;
    const open = openName === name;
    const slots = Number(scene.character_count || 0);
    const solo = Number(scene.independent_count || 0);
    // 순번은 이제 뜻을 가진다 - 만화의 컷 순서다(사용자 지정: ↑↓ 로 바꾼다).
    return `
      <article class="scene-row${open ? ' is-open' : ''}${wrongMode ? ' is-othermode' : ''}"
               data-scene-row="${escAttr(name)}">
        <div class="scene-row-line">
          <button type="button" class="scene-row-head" data-scene-toggle="${escAttr(name)}"
                  aria-expanded="${open ? 'true' : 'false'}">
            <span class="scene-ord">${ordinal}</span>
            <span class="scene-thumb${scene.thumbnail_url ? ' is-zoom' : ''}"${scene.thumbnail_url
              ? ` data-scene-preview="1" data-preview-name="${escAttr(name)}"`
                + ' data-naia-title="크게 보기 (휠로 컷 넘기기)"'
              : ''}>${scene.thumbnail_url
              ? `<img src="${escAttr(scene.thumbnail_url)}" alt="" loading="lazy" decoding="async">`
              : '<span class="scene-thumb-none">—</span>'}</span>
            <span class="scene-row-text">
              <span class="scene-row-name">${escHtml(name)}</span>
              <span class="scene-row-meta">
                <span class="scene-slots" data-naia-title="독립 슬롯 / 전체 슬롯">${solo}/${slots}</span>
                ${scene.resolution ? `<span>${escHtml(scene.resolution)}</span>` : ''}
                ${wrongMode ? `<span class="scene-row-warn">${escHtml(scene.mode)} 전용</span>` : ''}
              </span>
              <span class="scene-row-desc">${escHtml(scene.description || '(설명 없음)')}</span>
            </span>
          </button>
          <span class="scene-move">
            <button type="button" class="scene-move-btn" data-scene-move="${escAttr(name)}"
                    data-delta="-1"${ordinal <= 1 ? ' disabled' : ''}
                    data-naia-title="앞 컷과 자리를 바꿉니다">▲</button>
            <button type="button" class="scene-move-btn" data-scene-move="${escAttr(name)}"
                    data-delta="1"${ordinal >= total ? ' disabled' : ''}
                    data-naia-title="뒤 컷과 자리를 바꿉니다">▼</button>
          </span>
        </div>
        ${open ? sceneDetail(scene, wrongMode, ordinal) : ''}
      </article>`;
  }

  function sceneDetail(scene, wrongMode, ordinal) {
    const detail = scene.detail || {};
    const characters = detail.characters || [];
    const line = (label, value) => value
      ? `<div class="scene-detail-line"><span>${escHtml(label)}</span><code>${escHtml(value)}</code></div>`
      : '';
    return `
      <div class="scene-detail">
        ${line('프롬프트', detail.prompt)}
        ${line('POS', detail.position_mode)}
        ${characters.map((item, i) => {
          const link = Number(item.connect_to || 0);
          const pos = item.position ? `${item.position.x} , ${item.position.y}` : '자동';
          return `<div class="scene-detail-char">
            <span class="scene-detail-cn">C${i + 1}${link ? ` &#128279;C${link}` : ''}</span>
            <span class="scene-detail-cp">${escHtml(item.prompt || '(비어 있음)')}</span>
            <span class="scene-detail-cpos">${escHtml(pos)}</span>
          </div>`;
        }).join('')}
        <div class="scene-detail-actions">
          <button type="button" class="scene-apply"
                  data-scene-apply="${escAttr(scene.name)}"${wrongMode ? ' disabled' : ''}>
            이 구도로 불러오기</button>
          ${runButton(scene, ordinal)}
        </div>
      </div>`;
  }

  /** 연속 생성 버튼. **불러온 컷에서만** 켜진다(사용자 지정) - 그래야 그 사이에 자기
   *  와일드카드를 손볼 틈이 있다. 돌고 있으면 중단 버튼이 된다. */
  function runButton(scene, ordinal) {
    if (running) {
      return '<button type="button" class="scene-run is-stop" data-scene-run-stop="1">'
        + '생성 중단</button>';
    }
    const armed = String(scene.name) === appliedName;
    return `<button type="button" class="scene-run"`
      + ` data-scene-run="${escAttr(scene.name)}"${armed ? '' : ' disabled'}`
      + ` data-naia-title="${armed
          ? '이 컷부터 마지막 컷까지 한 장씩 이어서 만듭니다'
          : '먼저 [이 구도로 불러오기] 를 누르세요'}">`
      + `${ordinal} 부터 연속 생성</button>`;
  }

  // ── 크게 보기 ────────────────────────────────────────────────────────────
  // 목록의 56px 로는 어느 구도인지 알아보기 어렵다(사용자 지정). 그림은 **화면에
  // 맞춘다** - 한 컷 전체가 한눈에 들어와야 어느 장면인지 알아본다.
  //
  // 휠을 굴리면 **같은 이벤트의 이웃 컷**으로 넘어간다(사용자 지정). 창을 닫았다
  // 다시 여는 것보다 컷을 훑는 데 빠르고, 만화를 넘겨 보는 동작과도 맞는다.
  //
  // ⚠️ body 에 단다. 패널이 `overflow-y: auto` 라 안에 두면 잘린다 - Connect 메뉴와
  //    같은 이유다. 닫기는 그림 칸 클릭 / Esc.
  let previewIndex = -1;
  let wheelAccum = 0;

  function openPreview(name) {
    const scenes = lastState?.scenes || [];
    const index = scenes.findIndex(scene => String(scene.name) === String(name));
    if (index < 0) return;
    closePreview();
    previewIndex = index;
    wheelAccum = 0;
    const box = document.createElement('div');
    box.className = 'scene-preview';
    box.innerHTML = `
      <div class="scene-preview-stage" data-preview-close="1">
        <img alt="">
        <div class="scene-preview-none">그림이 아직 없습니다</div>
      </div>
      <div class="scene-preview-bar">
        <span class="scene-preview-name"></span>
        <span class="scene-preview-hint">휠로 컷 넘기기</span>
        <button type="button" class="scene-apply" data-preview-apply="1">이 구도로 불러오기</button>
      </div>`;
    box.addEventListener('click', event => {
      if (event.target.closest('[data-preview-apply]')) {
        const scene = (lastState?.scenes || [])[previewIndex];
        if (!scene) return;
        setModuleParam('v5_scene', 'apply', {event: activeEvent(), name: scene.name});
        showToast(`구도를 불러왔습니다 — ${scene.name}`, 'info');
        closePreview();
        return;
      }
      // 그림 칸(빈 곳 포함)을 누르면 닫는다. 아래 줄은 닫기 영역이 아니다 -
      // 버튼을 누르려다 빗나가서 닫히면 다시 열어야 한다.
      if (event.target.closest('[data-preview-close]')) closePreview();
    });
    // ⚠️ `passive: false` 여야 `preventDefault` 가 먹는다. 안 막으면 뒤의 목록이
    //    같이 굴러가서, 창을 닫았을 때 엉뚱한 자리에 가 있다.
    box.addEventListener('wheel', onPreviewWheel, {passive: false});
    document.body.appendChild(box);
    paintPreview();
    document.addEventListener('keydown', onPreviewKey, true);
  }

  /** 지금 `previewIndex` 의 컷을 창에 그린다. 창 자체는 다시 만들지 않는다. */
  function paintPreview() {
    const box = document.querySelector('.scene-preview');
    const scene = (lastState?.scenes || [])[previewIndex];
    if (!box || !scene) return;
    const total = (lastState?.scenes || []).length;
    const img = box.querySelector('img');
    const none = box.querySelector('.scene-preview-none');
    const url = String(scene.thumbnail_url || '');
    if (url) { img.src = url; img.style.display = ''; none.style.display = 'none'; }
    else { img.removeAttribute('src'); img.style.display = 'none'; none.style.display = ''; }
    box.querySelector('.scene-preview-name').textContent =
      `${previewIndex + 1} / ${total} · ${scene.name}`;
  }

  function stepPreview(delta) {
    const total = (lastState?.scenes || []).length;
    if (!total) return;
    const next = previewIndex + delta;
    // 양 끝에서는 멈춘다. 되돌아 감기면 몇 번째를 보고 있는지 놓친다.
    if (next < 0 || next >= total) return;
    previewIndex = next;
    paintPreview();
  }

  function onPreviewWheel(event) {
    event.preventDefault();
    // 한 번 튕기면 한 컷. 트랙패드는 잘게 여러 번 오므로 모아서 문턱을 넘을 때만 옮긴다.
    wheelAccum += event.deltaY;
    if (Math.abs(wheelAccum) < 40) return;
    stepPreview(wheelAccum > 0 ? 1 : -1);
    wheelAccum = 0;
  }

  function closePreview() {
    document.querySelector('.scene-preview')?.remove();
    document.removeEventListener('keydown', onPreviewKey, true);
    previewIndex = -1;
  }

  function onPreviewKey(event) {
    // 미리보기가 떠 있는 동안의 키는 여기서 삼킨다 - 안 그러면 뒤의 탭/팝업까지 닫힌다.
    if (event.key === 'Escape') {
      event.stopPropagation(); event.preventDefault(); closePreview(); return;
    }
    // 휠과 같은 이동을 키보드로도 - 손이 마우스에 없을 때가 있다.
    const step = {ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1}[event.key];
    if (!step) return;
    event.stopPropagation(); event.preventDefault();
    stepPreview(step);
  }

  /** 새 이벤트 이름을 묻는다. 만화 한 편에 해당하니 이름이 곧 폴더 이름이 된다. */
  async function askNewEvent() {
    let name = '';
    if (typeof showPromptDialog === 'function') {
      const answer = await showPromptDialog('만화 한 편에 해당하는 이름을 적으세요.', {
        title: '새 이벤트',
        okText: '만들기',
        cancelText: '취소',
        placeholder: '예: 3컷 만화',
      });
      if (answer === null) return;            // 취소
      name = String(answer || '').trim();
    } else {
      name = String(globalThis.prompt?.('새 이벤트 이름') || '').trim();
    }
    if (!name) { showToast('이벤트 이름을 입력하세요', 'error'); return; }
    setModuleParam('v5_scene', 'event_create', {name});
    rememberEvent(name);
  }

  /** 지금 구도를 열린 이벤트의 끝에 담는다. */
  async function saveCurrent() {
    const input = panel.querySelector('#sceneSaveName');
    const name = sanitizeName(String(input?.value || ''));
    if (!name) { showToast('컷 이름을 입력하세요', 'error'); input?.focus(); return; }
    // 같은 이름이 있으면 덮어쓰기다 - 조용히 덮으면 남의 컷을 잃는다.
    // ⚠️ **정제한 이름으로 견준다.** 목록의 이름은 이미 정제돼 있는데 날것을 그대로
    //    비교하면 `A:B` 가 `AB` 와 안 맞아 확인 없이 덮어썼다(Codex 리뷰 BLOCK).
    if ((lastState?.scenes || []).some(s => String(s.name) === name)) {
      const ok = (typeof showConfirmDialog === 'function')
        ? await showConfirmDialog(`"${name}" 컷을 덮어씁니다. 계속할까요?`,
                                  {title: '덮어쓰기', okText: '덮어쓰기', cancelText: '취소'})
        : globalThis.confirm(`"${name}" 컷을 덮어씁니다. 계속할까요?`);
      if (!ok) return;
    }
    setModuleParam('v5_scene', 'save', {event: activeEvent(), name});
    if (input) input.value = '';
    showToast(`컷을 담았습니다 — ${name}`, 'info');
  }

  /** 컷 이름 -> 목록에서의 자리(0-based). 못 찾으면 -1. */
  function indexOfScene(name) {
    return (lastState?.scenes || []).findIndex(scene => String(scene.name) === String(name));
  }

  /** 한 장 요청하고 **시작됐는지 지켜본다.**
   *
   * ⚠️ 요청이 서버에서 막히면(자격증명 없음·설정 미비) 생성이 아예 시작되지 않고,
   *    그러면 완료 신호도 안 온다 - `running` 이 영영 안 풀려 중단 버튼이 박제된다.
   *    시작 신호(`setGeneratingStatus(true)`)가 제때 안 오면 스스로 선다.
   */
  function fire(failReason) {
    clearWatchdog();
    // ⚠️ **`v5_scene_request` 마커를 반드시 단다.** 이게 없으면 서버 쪽 Auto Generate
    //    연쇄가 이 완료를 평범한 생성으로 보고 **자기도 다음 장을 낸다** - 프론트 루프와
    //    합쳐 생산자가 둘이 되고, 사용자가 시키지 않은 그림에 돈이 나간다(Codex BLOCK).
    //    Interactive·Studio 가 같은 방식으로 단다(`payload.overrides`).
    if (!requestGenerate({overrides: {v5_scene_request: true}})) { stopRun(failReason); return; }
    watchdog = globalThis.setTimeout(() => {
      watchdog = null;
      if (running && !generatingNow) stopRun('생성이 시작되지 않아 연속 생성을 멈췄습니다');
    }, 8000);
  }

  function clearWatchdog() {
    if (watchdog) { globalThis.clearTimeout(watchdog); watchdog = null; }
  }

  function startRun(name) {
    if (running) return;
    if (typeof requestGenerate !== 'function') {
      showToast('이 런타임에서는 연속 생성을 쓸 수 없습니다', 'error');
      return;
    }
    if (indexOfScene(name) < 0) return;
    // ⚠️ 이미 한 장 만드는 중이면 **여기서 거절한다.** 그대로 두면 아래 `fire` 가
    //    같은 이유로 서는데, 그때 나가는 문구는 왜 막혔는지 말하지 않는다 -
    //    사용자가 원인을 스스로 찾아야 한다(실측 제보).
    if (generatingNow) {
      showToast('이미 생성 중입니다 — 끝난 뒤에 눌러 주세요', 'error');
      return;
    }
    running = true;
    render();
    // 지금 화면은 이미 그 컷이다(불러오기를 누른 직후에만 켜지므로). 바로 한 장 낸다.
    fire('생성을 시작하지 못했습니다');
  }

  /** 멈춘다. `reason` 이 있으면 왜 멈췄는지 알린다 - 조용히 서면 끝난 줄 안다. */
  function stopRun(reason) {
    clearWatchdog();
    clearApplyWait();
    clearDoneWait();
    awaitingApply = false;
    if (!running) return;
    running = false;
    render();
    if (reason) showToast(reason, 'info');
  }

  /** 한 장이 끝났다. 성공이면 다음 컷을 불러오고 또 낸다.
   *
   * ⚠️ **성공일 때만 잇는다.** 실패·큐잉도 생성 종료로 오므로, 가르지 않으면 실패한
   *    요청을 영원히 다시 보낸다(Interactive Auto Gen 이 이미 밟은 함정 - 크레딧이 탄다).
   * ⚠️ 마지막 컷에서 **반드시 선다.** 되감아 돌면 사용자가 자리를 비운 사이에 끝없이 만든다.
   */
  function notifyGenerationDone(ok) {
    if (!running) return;
    if (!ok) { stopRun('생성이 완료되지 않아 연속 생성을 멈췄습니다'); return; }
    const scenes = lastState?.scenes || [];
    const here = indexOfScene(appliedName);
    if (here < 0) { stopRun('컷을 찾지 못해 연속 생성을 멈췄습니다'); return; }
    const next = here + 1;
    if (next >= scenes.length) {
      stopRun(`연속 생성을 마쳤습니다 — ${scenes.length}컷`);
      return;
    }
    appliedName = String(scenes[next].name);
    openName = appliedName;
    // ⚠️ 불러오기는 **왕복이 필요하다.** 응답을 안 기다리고 바로 내면 이전 컷의
    //    캐릭터로 한 장이 나간다 - 그림 한 장을 헛되이 태운다.
    //    고정 지연으로 어림하지 않고 **서버가 돌려준 상태를 기다린다**(`render` 가 깨운다).
    //    다만 응답이 영영 안 오는 경우를 대비해 뒷문을 하나 둔다.
    awaitingApply = true;
    setModuleParam('v5_scene', 'apply', {event: activeEvent(), name: appliedName});
    clearApplyWait();
    applyWait = globalThis.setTimeout(() => {
      applyWait = null;
      if (running && awaitingApply) {
        awaitingApply = false;
        stopRun('불러오기 응답이 없어 연속 생성을 멈췄습니다');
      }
    }, 6000);
  }

  function clearApplyWait() {
    if (applyWait) { globalThis.clearTimeout(applyWait); applyWait = null; }
  }

  function setGeneratingStatus(next) {
    const was = generatingNow;
    generatingNow = !!next;
    if (!running) return;
    if (generatingNow) {
      // 시작됐다 - 시작 감시를 풀고 **완료 감시**로 넘긴다.
      clearWatchdog();
      clearDoneWait();
      // ⚠️ 시작 감시만으로는 모자란다. 소켓이 끊기거나 완료 프레임을 잃으면 완료 신호가
      //    영영 안 와서 `running` 이 풀리지 않는다(Codex 리뷰 CONCERN). 한 장이 이보다
      //    오래 걸릴 일은 없으니, 넘으면 이어 가지 않고 **선다** - 모르면 안 내는 쪽이 맞다.
      doneWait = globalThis.setTimeout(() => {
        doneWait = null;
        if (running) stopRun('생성 완료 신호가 오지 않아 연속 생성을 멈췄습니다');
      }, 300000);
    } else if (was) {
      clearDoneWait();
    }
  }

  function clearDoneWait() {
    if (doneWait) { globalThis.clearTimeout(doneWait); doneWait = null; }
  }

  function onClick(event) {
    const runStop = event.target.closest('[data-scene-run-stop]');
    if (runStop) { stopRun('연속 생성을 멈췄습니다'); return; }
    const run = event.target.closest('[data-scene-run]');
    if (run) { startRun(run.dataset.sceneRun || ''); return; }
    const pickBtn = event.target.closest('[data-scene-event-pick]');
    if (pickBtn) {
      const reopened = menuClosedFrom === pickBtn;
      menuClosedFrom = null;
      if (!reopened) openEventMenu(pickBtn);
      return;
    }
    menuClosedFrom = null;
    // ⚠️ 썸네일 판정이 **토글보다 먼저**다. 썸네일이 헤더 버튼 안에 있어서, 나중에
    //    보면 카드가 같이 펼쳐졌다 접혔다 한다.
    const preview = event.target.closest('[data-scene-preview]');
    if (preview) {
      event.preventDefault();
      openPreview(preview.dataset.previewName || '');
      return;
    }
    const create = event.target.closest('[data-scene-event-create]');
    if (create) {
      const input = panel.querySelector('#sceneEventName');
      const name = String(input?.value || '').trim();
      if (!name) { showToast('이벤트 이름을 입력하세요', 'error'); input?.focus(); return; }
      setModuleParam('v5_scene', 'event_create', {name});
      rememberEvent(name);
      return;
    }
    if (event.target.closest('[data-scene-event-new]')) {
      askNewEvent();
      return;
    }
    if (event.target.closest('[data-scene-folder]')) {
      setModuleParam('v5_scene', 'open_folder', {event: activeEvent()});
      return;
    }
    const move = event.target.closest('[data-scene-move]');
    if (move) {
      setModuleParam('v5_scene', 'move', {
        event: activeEvent(),
        name: move.dataset.sceneMove || '',
        delta: Number(move.dataset.delta || 0),
      });
      return;
    }
    const save = event.target.closest('[data-scene-save]');
    if (save) {
      saveCurrent();
      return;
    }
    const toggle = event.target.closest('[data-scene-toggle]');
    if (toggle) {
      const name = toggle.dataset.sceneToggle || '';
      openName = (openName === name) ? '' : name;
      render();
      return;
    }
    const apply = event.target.closest('[data-scene-apply]');
    if (apply) {
      const name = apply.dataset.sceneApply || '';
      // 한 번에 적용한다(사용자 지정). 예전엔 두 번 눌러야 했는데 - 통째 교체라
      // 잘못 누르면 작업하던 구도가 사라져서 - 컷을 잇달아 넘겨 보는 작업에서는
      // 그 한 번이 매번 거슬린다. 안전보다 손맛을 택했다.
      // ⚠️ 돌고 있는 중에 손으로 다른 컷을 부르면 **줄거리가 바뀐다.** 예전엔 그냥
      //    `appliedName` 만 갈아 끼워서, 구경하려고 5컷을 눌렀더니 다음 장부터 6컷으로
      //    이어졌다(Codex 리뷰 CONCERN). 사람이 끼어들면 자동은 물러난다.
      if (running) stopRun('다른 컷을 불러와 연속 생성을 멈췄습니다');
      setModuleParam('v5_scene', 'apply', {event: activeEvent(), name});
      showToast(`구도를 불러왔습니다 — ${name}`, 'info');
      // 이 컷에서만 연속 생성을 켤 수 있다 - 불러온 뒤에 와일드카드를 손볼 틈을 준다.
      appliedName = name;
      render();
    }
  }

  panel?.addEventListener('click', onClick);
  panel?.addEventListener('keydown', event => {
    if (event.key !== 'Enter') return;
    const target = event.target.closest('#sceneSaveName, #sceneEventName');
    if (!target) return;
    event.preventDefault();
    panel.querySelector(target.id === 'sceneSaveName'
      ? '[data-scene-save]' : '[data-scene-event-create]')?.click();
  });

  return {onOpen, render, notifyGenerationDone, setGeneratingStatus, stopRun};
}
