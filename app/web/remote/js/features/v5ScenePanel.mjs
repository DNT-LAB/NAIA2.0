/**
 * V5 Scene 패널 (Fn > V5 Scene).
 *
 * 씬 = **구도**를 한 벌로 담은 것: 메인 프롬프트/네거티브 · 캐릭터(프롬프트·UC·좌표·
 * Connect) · 해상도 · POS 모드. 담는 범위와 규약은 `core/v5_scene_store.py` 머리 주석.
 *
 * 지금 지원하는 것은 **검색 · 저장 · 폴더 열기** 셋뿐이다(사용자 지정). 삭제·이름변경은
 * 백엔드에 있지만 버튼을 두지 않는다 - 대신 폴더를 열어 파일을 직접 다루면 된다.
 *
 * 카드는 [썸네일 | 독립/총 슬롯 수 · 해상도 · 설명] 만 보여 주고, **누르면 세부가
 * 펼쳐진다**(사용자 지정). 목록에서 훑을 때 필요한 것과 하나를 고른 뒤 확인할 것이
 * 다르다.
 *
 * ⚠️ 조작은 전부 범용 `setModuleParam('v5_scene', …)` 을 탄다 - 새 WS 메시지 타입을
 *    만들지 않기 위해서다(웹 스모크 계약이 타입을 순서대로 센다). 그림만 HTTP 다.
 */

export function createV5ScenePanel({panel, escHtml, showToast, setModuleParam}) {
  let lastState = null;
  let query = '';
  let openName = '';           // 펼쳐 둔 카드
  let pendingApply = '';       // 확인 대기(두 번 눌러야 적용)

  function escAttr(value) {
    return String(value ?? '').replace(/[&<>"']/g, char => (
      {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]
    ));
  }

  function onOpen() {
    setModuleParam('v5_scene', 'refresh', '');
  }

  /** 검색은 이름·설명·요약을 함께 본다 - 이름을 잊어도 "2koma" 나 "blonde" 로 찾힌다. */
  function matches(scene) {
    if (!query) return true;
    const hay = [scene.name, scene.description, scene.summary, scene.resolution]
      .map(v => String(v || '').toLowerCase()).join(' ');
    return query.toLowerCase().split(/\s+/).filter(Boolean).every(part => hay.includes(part));
  }

  function render(state) {
    if (state) lastState = state;
    if (!panel || !lastState) return;
    const all = lastState.scenes || [];
    const shown = all.filter(matches);
    const mode = String(lastState.current_mode || '');
    // ⚠️ 검색어는 마크업에 넣지 않고 렌더 뒤 `.value` 로 채운다 - 사용자가 적은
    //    `<`·따옴표가 마크업으로 새지 않게(이 앱의 다른 입력 표면과 같은 규약).
    panel.innerHTML = `
      <div class="scene-bar">
        <input type="text" class="scene-search" id="sceneSearch" placeholder="씬 검색 (이름 · 태그)"
               autocomplete="off">
        <button type="button" class="scene-bar-btn" data-scene-folder="1"
                data-naia-title="씬 폴더를 탐색기에서 엽니다">폴더 열기</button>
      </div>
      <div class="scene-save">
        <input type="text" class="scene-save-name" id="sceneSaveName" placeholder="이 구도를 담을 이름"
               maxlength="80" autocomplete="off">
        <button type="button" class="scene-save-btn" data-scene-save="1">저장</button>
      </div>
      <div class="scene-count">${shown.length}${
        shown.length !== all.length ? ` / ${all.length}` : ''} scene · ${escHtml(mode)}</div>
      ${shown.length
        ? `<div class="scene-list">${shown.map(sceneRow).join('')}</div>`
        : `<div class="scene-empty">${all.length
            ? '검색과 맞는 씬이 없습니다.'
            : '아직 담아 둔 씬이 없습니다.<br>구도를 만든 뒤 이름을 적고 <b>저장</b>을 누르세요.'}</div>`}
    `;
    const search = panel.querySelector('#sceneSearch');
    if (search) search.value = query;
  }

  function sceneRow(scene) {
    const name = String(scene.name || '');
    const wrongMode = scene.mode && lastState && scene.mode !== lastState.current_mode;
    const open = openName === name;
    const confirming = pendingApply === name;
    const total = Number(scene.character_count || 0);
    const solo = Number(scene.independent_count || 0);
    return `
      <article class="scene-row${open ? ' is-open' : ''}${wrongMode ? ' is-othermode' : ''}"
               data-scene-row="${escAttr(name)}">
        <button type="button" class="scene-row-head" data-scene-toggle="${escAttr(name)}"
                aria-expanded="${open ? 'true' : 'false'}">
          <span class="scene-thumb">${scene.thumbnail_url
            ? `<img src="${escAttr(scene.thumbnail_url)}" alt="" loading="lazy" decoding="async">`
            : '<span class="scene-thumb-none">—</span>'}</span>
          <span class="scene-row-text">
            <span class="scene-row-name">${escHtml(name)}</span>
            <span class="scene-row-meta">
              <span class="scene-slots" data-naia-title="독립 슬롯 / 전체 슬롯">${solo}/${total}</span>
              ${scene.resolution ? `<span>${escHtml(scene.resolution)}</span>` : ''}
              ${wrongMode ? `<span class="scene-row-warn">${escHtml(scene.mode)} 전용</span>` : ''}
            </span>
            <span class="scene-row-desc">${escHtml(scene.description || '(설명 없음)')}</span>
          </span>
        </button>
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
        ${line('네거티브', detail.negative)}
        ${line('POS', detail.position_mode)}
        ${characters.map((item, i) => {
          const link = Number(item.connect_to || 0);
          const pos = item.position
            ? `${item.position.x} , ${item.position.y}`
            : '자동';
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

  function onClick(event) {
    if (event.target.closest('[data-scene-folder]')) {
      setModuleParam('v5_scene', 'open_folder', '');
      return;
    }
    const save = event.target.closest('[data-scene-save]');
    if (save) {
      const input = panel.querySelector('#sceneSaveName');
      const name = String(input?.value || '').trim();
      if (!name) { showToast('씬 이름을 입력하세요', 'error'); input?.focus(); return; }
      // 같은 이름이 있으면 덮어쓰기다 - 조용히 덮으면 남의 씬을 잃는다.
      const exists = (lastState?.scenes || []).some(s => String(s.name) === name);
      if (exists && !window.confirm(`"${name}" 씬을 덮어씁니다. 계속할까요?`)) return;
      setModuleParam('v5_scene', 'save', name);
      if (input) input.value = '';
      showToast(`씬을 담았습니다 — ${name}`, 'info');
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
      setModuleParam('v5_scene', 'apply', name);
      showToast(`씬을 불러왔습니다 — ${name}`, 'info');
    }
  }

  panel?.addEventListener('click', onClick);
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
    if (!event.target.closest('#sceneSaveName')) return;
    event.preventDefault();
    panel.querySelector('[data-scene-save]')?.click();
  });

  return {onOpen, render};
}
