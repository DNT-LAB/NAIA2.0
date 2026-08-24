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
}) {
  let lastState = null;
  let query = '';
  let openName = '';           // 펼쳐 둔 컷
  let pendingApply = '';       // 확인 대기(두 번 눌러야 적용)

  function escAttr(value) {
    return String(value ?? '').replace(/[&<>"']/g, char => (
      {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]
    ));
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

  /** 검색은 이름·설명·요약을 함께 본다 - 이름을 잊어도 "2koma" 나 "blonde" 로 찾힌다. */
  function matches(scene) {
    if (!query) return true;
    const hay = [scene.name, scene.description, scene.summary, scene.resolution]
      .map(v => String(v || '').toLowerCase()).join(' ');
    return query.toLowerCase().split(/\s+/).filter(Boolean).every(part => hay.includes(part));
  }

  function render(state) {
    if (state) {
      lastState = state;
      // 서버가 연 이벤트를 기억한다 - 처음 열 때(기억 없음)와 이벤트를 만든 직후에도 맞는다.
      if (state.event) rememberEvent(state.event);
    }
    if (!panel || !lastState) return;
    const events = lastState.events || [];
    const active = activeEvent();
    const all = lastState.scenes || [];
    const shown = all.filter(matches);
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

    // ⚠️ 검색어·이름은 마크업에 넣지 않고 렌더 뒤 `.value` 로 채운다 - 사용자가 적은
    //    `<`·따옴표가 마크업으로 새지 않게(이 앱의 다른 입력 표면과 같은 규약).
    panel.innerHTML = `
      <div class="scene-bar">
        <select class="scene-event-pick" id="sceneEventPick" data-native-select
                data-naia-title="열어 둘 이벤트">
          ${events.map(name => `<option value="${escAttr(name)}"${
            name === active ? ' selected' : ''}>${escHtml(name)}</option>`).join('')}
        </select>
        <button type="button" class="scene-bar-btn" data-scene-event-new="1"
                data-naia-title="새 이벤트를 만듭니다">+ 이벤트</button>
        <button type="button" class="scene-bar-btn" data-scene-folder="1"
                data-naia-title="이 이벤트의 폴더를 탐색기에서 엽니다">폴더</button>
      </div>
      <div class="scene-count">${shown.length}${
        shown.length !== all.length ? ` / ${all.length}` : ''} 컷 · ${escHtml(mode)}</div>
      <div class="scene-bar">
        <input type="text" class="scene-search" id="sceneSearch" placeholder="컷 검색 (이름 · 태그)"
               autocomplete="off">
      </div>
      ${shown.length
        ? `<div class="scene-list">${shown.map((scene, index) =>
            sceneRow(scene, all.indexOf(scene) + 1, all.length)).join('')}</div>`
        : `<div class="scene-empty">${all.length
            ? '검색과 맞는 컷이 없습니다.'
            : '이 이벤트에는 아직 컷이 없습니다.<br>구도를 만든 뒤 이름을 적고 <b>저장</b>을 누르세요.'}</div>`}
      <div class="scene-save">
        <input type="text" class="scene-save-name" id="sceneSaveName" placeholder="이 구도를 담을 이름"
               maxlength="80" autocomplete="off">
        <button type="button" class="scene-save-btn" data-scene-save="1">저장</button>
      </div>
    `;
    const search = panel.querySelector('#sceneSearch');
    if (search) search.value = query;
  }

  function sceneRow(scene, ordinal, total) {
    const name = String(scene.name || '');
    const wrongMode = scene.mode && lastState && scene.mode !== lastState.current_mode;
    const open = openName === name;
    const confirming = pendingApply === name;
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
              ? ` data-scene-preview="${escAttr(scene.thumbnail_url)}" data-preview-name="${escAttr(name)}"`
                + ' data-naia-title="크게 보기"'
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
        ${open ? sceneDetail(scene, confirming, wrongMode) : ''}
      </article>`;
  }

  function sceneDetail(scene, confirming, wrongMode) {
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
          <button type="button" class="scene-apply${confirming ? ' is-confirm' : ''}"
                  data-scene-apply="${escAttr(scene.name)}"${wrongMode ? ' disabled' : ''}>
            ${confirming ? '한 번 더 누르면 적용' : '이 구도로 불러오기'}</button>
        </div>
      </div>`;
  }

  /** 썸네일 크게 보기. 목록의 56px 로는 어느 구도인지 알아보기 어렵다(사용자 지정).
   *
   * ⚠️ body 에 단다. 패널이 `overflow-y: auto` 라 안에 두면 잘린다 - Connect 메뉴와
   *    같은 이유다. 닫기는 아무 데나 클릭 / Esc.
   */
  function openPreview(url, name) {
    closePreview();
    const box = document.createElement('div');
    box.className = 'scene-preview';
    box.innerHTML = `
      <div class="scene-preview-inner">
        <img src="${escAttr(url)}" alt="">
        <div class="scene-preview-name">${escHtml(name || '')}</div>
      </div>`;
    box.addEventListener('click', closePreview);
    document.body.appendChild(box);
    document.addEventListener('keydown', onPreviewKey, true);
  }

  function closePreview() {
    document.querySelector('.scene-preview')?.remove();
    document.removeEventListener('keydown', onPreviewKey, true);
  }

  function onPreviewKey(event) {
    if (event.key !== 'Escape') return;
    // 미리보기가 떠 있는 동안의 Esc 는 여기서 삼킨다 - 안 그러면 뒤의 탭/팝업까지 닫힌다.
    event.stopPropagation();
    event.preventDefault();
    closePreview();
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
    const name = String(input?.value || '').trim();
    if (!name) { showToast('컷 이름을 입력하세요', 'error'); input?.focus(); return; }
    // 같은 이름이 있으면 덮어쓰기다 - 조용히 덮으면 남의 컷을 잃는다.
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

  function onClick(event) {
    // ⚠️ 썸네일 판정이 **토글보다 먼저**다. 썸네일이 헤더 버튼 안에 있어서, 나중에
    //    보면 카드가 같이 펼쳐졌다 접혔다 한다.
    const preview = event.target.closest('[data-scene-preview]');
    if (preview) {
      event.preventDefault();
      openPreview(preview.dataset.scenePreview || '', preview.dataset.previewName || '');
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
      pendingApply = '';
      render();
      return;
    }
    const apply = event.target.closest('[data-scene-apply]');
    if (apply) {
      const name = apply.dataset.sceneApply || '';
      // ⚠️ **두 번 눌러야 적용한다.** 적용은 지금 프롬프트와 캐릭터를 통째로 갈아치운다 -
      //    목록을 훑다 잘못 누르면 작업하던 구도가 화면에서 사라진다(기존 캐릭터는
      //    비활성으로 남아 되살릴 수 있지만, 그걸 아는 것과 놀라지 않는 것은 다르다).
      if (pendingApply !== name) {
        pendingApply = name;
        render();
        globalThis.setTimeout(() => {
          if (pendingApply === name) { pendingApply = ''; render(); }
        }, 4000);
        return;
      }
      pendingApply = '';
      setModuleParam('v5_scene', 'apply', {event: activeEvent(), name});
      showToast(`구도를 불러왔습니다 — ${name}`, 'info');
    }
  }

  panel?.addEventListener('click', onClick);
  panel?.addEventListener('change', event => {
    if (!event.target.closest('#sceneEventPick')) return;
    const name = String(event.target.value || '');
    rememberEvent(name);
    // 이벤트를 바꾸면 검색·펼침은 초기화한다 - 남의 이벤트에서 쓰던 상태다.
    query = ''; openName = ''; pendingApply = '';
    setModuleParam('v5_scene', 'refresh', {event: name});
  });
  panel?.addEventListener('input', event => {
    if (!event.target.closest('#sceneSearch')) return;
    query = String(event.target.value || '');
    render();
    // 다시 그리면 포커스가 빠진다 - 검색은 계속 치는 칸이라 캐럿까지 되돌린다.
    const search = panel.querySelector('#sceneSearch');
    if (search) { search.focus(); search.setSelectionRange(query.length, query.length); }
  });
  panel?.addEventListener('keydown', event => {
    if (event.key !== 'Enter') return;
    const target = event.target.closest('#sceneSaveName, #sceneEventName');
    if (!target) return;
    event.preventDefault();
    panel.querySelector(target.id === 'sceneSaveName'
      ? '[data-scene-save]' : '[data-scene-event-create]')?.click();
  });

  return {onOpen, render};
}
