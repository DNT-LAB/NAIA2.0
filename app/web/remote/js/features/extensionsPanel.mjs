// Extensions UI 통합 컨트롤러.
// 노출 계약(사용자 지정):
// - Settings 탭 ▸ Extension = 전역 설정 전담: 승인/ON·OFF/차단/퀵 버튼 위치 +
//   scope:"global" 필드(저장 경로 등). 실제 동작(어떻게 생성할 것인지) 요소는
//   여기에 그리지 않는다.
// - 퀵 버튼 팝업 = 개별 모듈 UI: Activate This Script + scope:"module"(기본)
//   필드. 전역 요소(버튼 위치 등)는 여기에 그리지 않는다.
// - 꺼짐(enabled=false)이면 퀵 버튼을 비활성 표시가 아니라 **아예 숨긴다** —
//   Settings에서 다시 켜야 보인다.
// 토글은 승인/soft 전용, 차단은 ⋯ 메뉴로 분리(설계 인스펙션 #4).
export function createExtensionsUi(deps) {
  const {document, escHtml, setModuleParam, showToast, requestState, setLauncherItems} = deps;

  // 퀵 버튼 배치 선택지 — 도구바(독립 바) / 자동화·고급 기능 카테고리 / 없음.
  const PLACEMENT_OPTIONS = [
    ['tools', '도구바 (Tools)'],
    ['assistant_tools', '자동화 / 고급 기능'],
    ['none', '없음'],
  ];

  let lastState = null;
  let confirmingId = null; // 미승인 확장 활성화 전 신뢰 경고 인라인 확인
  let openMenuId = null;
  let quickPopupId = null; // 열려 있는 퀵 팝업의 확장 id
  let navBound = false;

  // ── 공용: 칩/필드 렌더러 (설정 페이지·퀵 팝업 공유) ──────────
  function chipFor(ext) {
    if (ext.status === 'loading') return ['로딩 중…', 'ext-chip-loading'];
    if (ext.status === 'manifest_error') return ['매니페스트 오류', 'ext-chip-error'];
    if (ext.status === 'error') return ['오류', 'ext-chip-error'];
    if (ext.blocked) {
      return [ext.status === 'loaded' ? '차단됨 (재시작 시 완전 차단)' : '차단됨', 'ext-chip-muted'];
    }
    if (ext.status === 'discovered') return ['미승인', 'ext-chip-muted'];
    if (ext.status === 'loaded') {
      return ext.enabled ? ['활성', 'ext-chip-on'] : ['꺼짐', 'ext-chip-off'];
    }
    return [ext.status, 'ext-chip-muted'];
  }

  function applyHint(field) {
    if (field.apply === 'restart-required') return '<span class="ext-apply-chip">재시작 필요</span>';
    if (field.apply === 'next-generation') return '<span class="ext-apply-hint">다음 생성부터</span>';
    return '';
  }

  function fieldHtml(ext, field, idPrefix, suppressApply) {
    if (field.type === 'action') {
      // 버튼: 클릭 → 백엔드가 확장의 on_action(key) 호출(설정 저장 없음).
      const helpAttr = field.help ? ` title="${escHtml(field.help)}"` : '';
      return `<div class="ext-field ext-field-action">
        <button type="button" class="ext-action-btn" data-ext="${escHtml(ext.id)}"
          data-action-field="${escHtml(field.key)}"${helpAttr}>${escHtml(field.label)}</button>
      </div>`;
    }
    const value = ext.settings && field.key in ext.settings ? ext.settings[field.key] : field.default;
    const fid = `${idPrefix}-${ext.id}-${field.key}`;
    const common = `id="${fid}" data-ext="${escHtml(ext.id)}" data-field="${escHtml(field.key)}"`;
    const ph = field.placeholder ? ` placeholder="${escHtml(field.placeholder)}"` : '';
    let input = '';
    if (field.type === 'bool') {
      input = `<input type="checkbox" ${common} ${value ? 'checked' : ''}>`;
    } else if (field.type === 'int' || field.type === 'float') {
      const min = field.min !== undefined ? ` min="${field.min}"` : '';
      const max = field.max !== undefined ? ` max="${field.max}"` : '';
      const step = field.step !== undefined ? ` step="${field.step}"` : (field.type === 'float' ? ' step="0.1"' : '');
      input = `<input type="number" ${common}${min}${max}${step}${ph} value="${escHtml(String(value ?? ''))}">`;
    } else if (field.type === 'select') {
      const options = (field.options || []).map(opt =>
        `<option value="${escHtml(opt)}" ${String(value) === opt ? 'selected' : ''}>${escHtml(opt)}</option>`).join('');
      input = `<select class="ext-select" ${common}>${options}</select>`;
    } else if (field.type === 'tags') {
      const text = Array.isArray(value) ? value.join(', ') : String(value ?? '');
      input = `<input type="text" class="ext-field-wide" ${common} value="${escHtml(text)}"${ph || ' placeholder="쉼표로 구분"'}>`;
    } else { // text
      input = `<input type="text" class="ext-field-wide" ${common}${ph} value="${escHtml(String(value ?? ''))}">`;
    }
    // 도움말은 숨은 row 툴팁 대신 라벨 옆 ⓘ 마커로 발견 가능하게.
    const helpMark = field.help
      ? ` <span class="ext-help-mark" title="${escHtml(field.help)}">ⓘ</span>` : '';
    const error = ext.field_errors && ext.field_errors[field.key]
      ? `<div class="ext-field-error">${escHtml(ext.field_errors[field.key])}</div>` : '';
    return `<div class="ext-field"><label for="${fid}">${escHtml(field.label)}${helpMark}${suppressApply ? '' : applyHint(field)}</label>${input}${error}</div>`;
  }

  function fieldValue(ext, key) {
    if (ext.settings && key in ext.settings) return ext.settings[key];
    const def = (ext.panel?.fields || []).find(f => f.key === key);
    return def ? def.default : undefined;
  }

  function fieldVisible(ext, field, seen) {
    const cond = field.visible_when;
    if (!cond || !cond.field) return true;
    // 계단식: 컨트롤러 필드 자신이 숨어 있으면 종속 필드도 숨는다
    // (예: 모드≠X/Y면 x_axis가 숨고, x_axis에 묶인 인자 칸들도 연쇄로 숨음).
    const visited = seen || new Set();
    if (visited.has(field.key)) return true; // 순환 선언 보호
    visited.add(field.key);
    const controller = (ext.panel?.fields || []).find(f => f.key === cond.field);
    if (controller && !fieldVisible(ext, controller, visited)) return false;
    const current = String(fieldValue(ext, cond.field) ?? '');
    return (cond.in || []).map(String).includes(current);
  }

  function columnHtml(ext, fields, idPrefix, suppressApply) {
    let html = '';
    let section = null;
    for (const field of fields) {
      if ((field.section || '') !== section) {
        section = field.section || '';
        if (section) html += `<div class="ext-section">${escHtml(section)}</div>`;
      }
      html += fieldHtml(ext, field, idPrefix, suppressApply);
    }
    return html;
  }

  const APPLY_NOTES = {
    'next-generation': '변경은 다음 생성부터 적용됩니다',
    'restart-required': '변경은 재시작 후 적용됩니다',
  };

  function scopeOf(field) {
    return field.scope === 'global' ? 'global' : 'module';
  }

  function fieldsHtml(ext, idPrefix, scope) {
    if (!ext.panel || !Array.isArray(ext.panel.fields) || ext.status !== 'loaded') return '';
    // 노출 계약(scope) → visible_when 평가(설정값 기반 — 값 변경은 브로드캐스트
    // 재렌더로 반영) → left/right 칼럼 분리. right가 있으면 2단(복잡 모드 패널).
    const visible = ext.panel.fields.filter(field =>
      scopeOf(field) === scope && fieldVisible(ext, field));
    // 표시 필드의 apply가 모두 같으면 라벨마다 칩을 반복하지 않고 하단 1줄로 집약.
    // (action 버튼은 "적용 시점" 개념이 없으므로 판정에서 제외)
    const applyModes = new Set(
      visible.filter(field => field.type !== 'action').map(field => field.apply || 'immediate'));
    const uniformApply = applyModes.size === 1 ? [...applyModes][0] : '';
    const suppressApply = Boolean(APPLY_NOTES[uniformApply]);
    const note = suppressApply ? `<div class="ext-fields-note">${APPLY_NOTES[uniformApply]}</div>` : '';
    const left = visible.filter(field => field.column !== 'right');
    const right = visible.filter(field => field.column === 'right');
    const leftHtml = columnHtml(ext, left, idPrefix, suppressApply);
    const rightHtml = columnHtml(ext, right, idPrefix, suppressApply);
    if (!leftHtml && !rightHtml) return '';
    const disabled = !ext.active ? ' ext-fields-disabled' : '';
    if (!rightHtml) return `<div class="ext-fields${disabled}">${leftHtml}</div>${note}`;
    return `<div class="ext-fields ext-fields-two-col${disabled}">
      <div class="ext-fields-col">${leftHtml}</div>
      <div class="ext-fields-col ext-fields-col-right">${rightHtml}</div>
    </div>${note}`;
  }

  function hasRightColumn(ext) {
    if (!ext?.panel || ext.status !== 'loaded') return false;
    return ext.panel.fields.some(field =>
      field.column === 'right' && scopeOf(field) === 'module' && fieldVisible(ext, field));
  }

  function bindFields(root) {
    root.querySelectorAll('.ext-fields [data-field]').forEach(el => {
      el.addEventListener('change', () => {
        const value = el.type === 'checkbox' ? el.checked : el.value;
        setModuleParam('extensions', `setting:${el.dataset.ext}:${el.dataset.field}`, value);
      });
    });
    root.querySelectorAll('.ext-action-btn[data-action-field]').forEach(el => {
      el.addEventListener('click', () => {
        setModuleParam('extensions', `setting:${el.dataset.ext}:${el.dataset.actionField}`, true);
      });
    });
  }

  function findExt(extId) {
    return (lastState?.extensions || []).find(item => item.id === extId) || null;
  }

  // ── Settings ▸ Extension 페이지 ──────────────────────────────
  function pane() {
    return document.getElementById('settingsExtensionPane');
  }

  function placementOptionsHtml(ext) {
    return PLACEMENT_OPTIONS.map(([val, label]) =>
      `<option value="${val}" ${ext.placement === val ? 'selected' : ''}>${label}</option>`).join('');
  }

  function placementSelect(ext) {
    if (ext.status !== 'loaded') return '';
    return `<label class="ext-placement"><span>퀵 버튼 위치</span>
      <select class="ext-select ext-placement-select" data-ext="${escHtml(ext.id)}">${placementOptionsHtml(ext)}</select></label>`;
  }

  function rowHtml(ext) {
    const [chipLabel, chipClass] = chipFor(ext);
    const showToggle = !['manifest_error', 'error'].includes(ext.status) && !ext.blocked;
    const toggleChecked = ext.status === 'loaded' ? ext.enabled : false;
    const toggleDisabled = ext.status === 'loading';
    const toggle = showToggle
      ? `<label class="ext-switch" title="${ext.status === 'discovered' ? '활성화(승인 필요)' : '켜기/끄기 (즉시)'}">
           <input type="checkbox" class="ext-toggle" data-ext="${escHtml(ext.id)}" ${toggleChecked ? 'checked' : ''} ${toggleDisabled ? 'disabled' : ''}>
           <span class="ext-slider"></span>
         </label>`
      : (ext.status === 'error'
        ? `<button class="ext-retry-btn" data-ext="${escHtml(ext.id)}">재시도</button>` : '');
    const home = ext.homepage
      ? ` · <a href="${escHtml(ext.homepage)}" target="_blank" rel="noopener">홈페이지</a>` : '';
    const desc = ext.description || home
      ? `<div class="ext-desc">${escHtml(ext.description || '')}${home}</div>` : '';
    const error = ext.error
      ? `<div class="ext-error" title="${escHtml(ext.error)}">${escHtml(ext.error)}${ext.status === 'error' ? ' — 수정 후 재시도하거나 재시작' : ''}</div>` : '';
    const confirm = confirmingId === ext.id
      ? `<div class="ext-confirm">⚠️ 이 확장은 NAIA와 같은 권한으로 <b>임의 Python 코드</b>를 실행하며
           생성 파이프라인과 API 토큰 등 자격증명에 접근할 수 있습니다. 제작자를 신뢰할 때만 활성화하세요.
           <div class="ext-confirm-actions">
             <button class="ext-approve-btn" data-ext="${escHtml(ext.id)}">신뢰하고 활성화</button>
             <button class="ext-cancel-btn" data-ext="${escHtml(ext.id)}">취소</button>
           </div></div>` : '';
    const menu = openMenuId === ext.id
      ? `<div class="ext-menu">
           <button class="ext-block-btn" data-ext="${escHtml(ext.id)}" data-blocked="${ext.blocked ? '1' : ''}">${ext.blocked ? '차단 해제 (재시작 후 로드)' : '차단 (import 금지)'}</button>
           <button class="ext-copy-dir-btn" data-dir="${escHtml(ext.directory || '')}">폴더 경로 복사</button>
         </div>` : '';
    return `<div class="ext-row" data-ext="${escHtml(ext.id)}">
      <div class="ext-row-main">
        <div class="ext-info">
          <span class="ext-name">${escHtml(ext.name || ext.id)} <span class="ext-ver">${escHtml(ext.version ? 'v' + ext.version : '')}</span>
            <span class="ext-chip ${chipClass}" ${ext.error ? `title="${escHtml(ext.error)}"` : ''}>${chipLabel}</span></span>
          ${desc}
        </div>
        <div class="ext-controls">${placementSelect(ext)}${toggle}<button class="ext-menu-btn" data-ext="${escHtml(ext.id)}">⋯</button></div>
      </div>
      ${confirm}${menu}${error}${fieldsHtml(ext, 'extset', 'global')}
    </div>`;
  }

  function captureFocus(root) {
    const active = document.activeElement;
    if (!active || !root || !root.contains(active) || !active.dataset || !active.dataset.field) return null;
    return {
      ext: active.dataset.ext,
      field: active.dataset.field,
      selStart: active.selectionStart,
      selEnd: active.selectionEnd,
    };
  }

  function restoreFocus(root, saved) {
    if (!saved || !root) return;
    const el = root.querySelector(
      `[data-ext="${CSS.escape(saved.ext)}"][data-field="${CSS.escape(saved.field)}"]`);
    if (!el) return;
    el.focus();
    if (saved.selStart != null && typeof el.setSelectionRange === 'function') {
      try { el.setSelectionRange(saved.selStart, saved.selEnd); } catch (_) { /* number input 등 */ }
    }
  }

  function renderSettingsPane() {
    const root = pane();
    if (!root || !lastState) return;
    const saved = captureFocus(root);
    const items = Array.isArray(lastState.extensions) ? lastState.extensions : [];
    const errors = items.filter(item => item.status === 'error').length;
    const head = `<div class="ext-head">
        <span class="ext-install-label">설치 폴더:</span>
        <code class="ext-install-path" title="${escHtml(lastState.install_dir || '')}">${escHtml(lastState.install_dir || '')}</code>
        <button class="ext-copy-install">복사</button>
        ${errors ? `<button class="ext-retry-all">오류 ${errors}건 재시도</button>` : ''}
      </div>`;
    const body = items.length
      ? items.map(rowHtml).join('')
      : `<div class="ext-empty">설치된 확장이 없습니다.<br>
           위 폴더에 <code>&lt;확장-id&gt;/extension.json + main.py</code>를 넣으면 이 목록에 나타납니다.<br>
           샘플: 릴리즈의 <code>release_assets/samples/extensions/seed_fanout</code> 폴더를 복사해 보세요.</div>`;
    root.innerHTML = `<div class="ext-panel">${head}${body}</div>`;
    bindSettingsPane(root);
    restoreFocus(root, saved);
  }

  function bindSettingsPane(root) {
    root.querySelectorAll('.ext-toggle').forEach(el => {
      el.addEventListener('change', () => {
        const ext = findExt(el.dataset.ext);
        if (!ext) return;
        if (ext.status === 'discovered') {
          el.checked = false; // 승인은 신뢰 경고 인라인 확인을 거친다.
          confirmingId = ext.id;
          openMenuId = null;
          renderSettingsPane();
          return;
        }
        setModuleParam('extensions', `enabled:${ext.id}`, el.checked);
      });
    });
    root.querySelectorAll('.ext-approve-btn').forEach(el => {
      el.addEventListener('click', () => {
        confirmingId = null;
        setModuleParam('extensions', `approve:${el.dataset.ext}`, true);
      });
    });
    root.querySelectorAll('.ext-cancel-btn').forEach(el => {
      el.addEventListener('click', () => { confirmingId = null; renderSettingsPane(); });
    });
    root.querySelectorAll('.ext-retry-btn').forEach(el => {
      el.addEventListener('click', () => setModuleParam('extensions', `retry:${el.dataset.ext}`, true));
    });
    const retryAll = root.querySelector('.ext-retry-all');
    if (retryAll) retryAll.addEventListener('click', () => setModuleParam('extensions', 'retry_errors', true));
    root.querySelectorAll('.ext-menu-btn').forEach(el => {
      el.addEventListener('click', () => {
        openMenuId = openMenuId === el.dataset.ext ? null : el.dataset.ext;
        confirmingId = null;
        renderSettingsPane();
      });
    });
    root.querySelectorAll('.ext-block-btn').forEach(el => {
      el.addEventListener('click', () => {
        openMenuId = null;
        setModuleParam('extensions', `blocked:${el.dataset.ext}`, !el.dataset.blocked);
      });
    });
    root.querySelectorAll('.ext-copy-dir-btn').forEach(el => {
      el.addEventListener('click', () => copyText(el.dataset.dir));
    });
    const copyInstall = root.querySelector('.ext-copy-install');
    if (copyInstall) copyInstall.addEventListener('click', () => copyText(lastState?.install_dir || ''));
    root.querySelectorAll('.ext-placement-select').forEach(el => {
      el.addEventListener('change', () => {
        setModuleParam('extensions', `placement:${el.dataset.ext}`, el.value);
      });
    });
    bindFields(root);
  }

  // ── Settings 좌측 네비 (Global / Extension) ──────────────────
  function bindNav() {
    if (navBound) return;
    const nav = document.getElementById('settingsNav');
    if (!nav) return;
    navBound = true;
    nav.querySelectorAll('.settings-nav-item').forEach(btn => {
      btn.addEventListener('click', () => {
        nav.querySelectorAll('.settings-nav-item').forEach(b =>
          b.classList.toggle('active', b === btn));
        document.querySelectorAll('[data-settings-page-content]').forEach(page => {
          page.classList.toggle('active', page.dataset.settingsPageContent === btn.dataset.settingsPage);
        });
        if (btn.dataset.settingsPage === 'extension' && typeof requestState === 'function') {
          requestState(); // 페이지 진입 시 재발견(새 설치 즉시 반영)
        }
      });
    });
  }

  // ── 메인 UI 퀵 버튼 (도구바 / 자동화·고급 기능) ──────────────
  function quickEligible(ext) {
    // 꺼짐(enabled=false)은 비활성 표시가 아니라 미노출 — Settings에서 켜야 보인다.
    return ext.status === 'loaded' && !ext.blocked && ext.enabled && ext.placement !== 'none';
  }

  function syncQuickButtons() {
    const items = (lastState?.extensions || []).filter(quickEligible);
    // 도구바: #moduleLauncher 바로 뒤의 전용 컨테이너(런처 render()가 innerHTML을
    // 다시 쓰므로 내부에 끼어들지 않는다).
    const launcher = document.getElementById('moduleLauncher');
    if (launcher) {
      let bar = document.getElementById('extToolsBar');
      const toolItems = items.filter(ext => ext.placement === 'tools');
      if (!toolItems.length) {
        if (bar) bar.remove();
      } else {
        if (!bar) {
          bar = document.createElement('div');
          bar.id = 'extToolsBar';
          bar.className = 'module-bar ext-tools-bar';
          launcher.insertAdjacentElement('afterend', bar);
        }
        bar.innerHTML = toolItems.map(ext =>
          `<button type="button" class="module-btn ext-tool-btn"
             data-ext="${escHtml(ext.id)}" title="${escHtml(ext.description || ext.name)}">
             <span>🧩</span><span>${escHtml(ext.name || ext.id)}</span></button>`).join('');
        bar.querySelectorAll('.ext-tool-btn').forEach(el => {
          el.addEventListener('click', event => openQuickPopup(el.dataset.ext, event.currentTarget));
        });
      }
    }
    // 자동화·고급 기능 카테고리 플라이아웃에 주입. moduleLauncher는 메뉴를 닫기
    // 전에 항목 rect를 캡처해 넘긴다(닫힌 뒤 측정하면 0,0 → 팝업이 좌상단행).
    if (typeof setLauncherItems === 'function') {
      setLauncherItems(
        items
          .filter(ext => ext.placement === 'assistant_tools')
          .map(ext => ({
            id: ext.id,
            label: ext.name || ext.id,
            title: ext.description || ext.name || ext.id,
            category: 'assistant_tools',
          })),
        openQuickPopup,
      );
    }
  }

  // ── 퀵 팝업: Activate 스위치 + 확장 선언 폼 ──────────────────
  function quickPopupEl() {
    let el = document.getElementById('extQuickPopup');
    if (!el) {
      el = document.createElement('div');
      el.id = 'extQuickPopup';
      el.className = 'ext-quick-popup';
      el.style.display = 'none';
      document.body.appendChild(el);
      document.addEventListener('mousedown', event => {
        // customSelects 메뉴는 body 직속 오버레이 — 옵션 클릭을 외부클릭으로
        // 오인해 팝업을 닫으면 안 된다(축 select 선택 시 창 닫힘 버그).
        if (el.style.display !== 'none' && !el.contains(event.target)
            && !event.target.closest?.('.ext-tool-btn') && !event.target.closest?.('.ext-launcher-item')
            && !event.target.closest?.('.custom-select, .custom-select-menu')) {
          closeQuickPopup();
        }
      });
    }
    return el;
  }

  function openQuickPopup(extId, anchorOrRect) {
    if (quickPopupId === extId && quickPopupEl().style.display !== 'none') {
      closeQuickPopup();
      return;
    }
    // 앵커 엘리먼트는 직후 메뉴 닫힘 등으로 rect가 0이 될 수 있다 — 진입 즉시 확정.
    const rect = anchorOrRect && typeof anchorOrRect.getBoundingClientRect === 'function'
      ? anchorOrRect.getBoundingClientRect()
      : anchorOrRect;
    quickPopupId = extId;
    renderQuickPopup();
    positionQuickPopup(rect);
  }

  function closeQuickPopup() {
    quickPopupId = null;
    const el = document.getElementById('extQuickPopup');
    if (el) el.style.display = 'none';
  }

  function renderQuickPopup() {
    if (!quickPopupId) return;
    const ext = findExt(quickPopupId);
    const el = quickPopupEl();
    if (!ext || !quickEligible(ext)) { closeQuickPopup(); return; }
    const saved = captureFocus(el);
    // 모듈 UI 전담: scope:"module" 필드만. 전역 요소(버튼 위치 등)는 Settings 전담.
    const fields = fieldsHtml(ext, 'extquick', 'module')
      || '<div class="ext-quick-nofields">이 확장은 설정 항목을 선언하지 않았습니다.</div>';
    el.innerHTML = `
      <div class="ext-quick-head">
        <span class="ext-quick-title">
          <span class="ext-quick-icon" aria-hidden="true">🧩</span>
          <span>${escHtml(ext.name || ext.id)}</span>
        </span>
        <button type="button" class="ext-quick-close" title="닫기">×</button>
      </div>
      <div class="ext-quick-body">
        <label class="ext-quick-activate">
          <span class="ext-quick-activate-label">Activate This Script</span>
          <span class="ext-switch">
            <input type="checkbox" class="ext-quick-toggle" ${ext.enabled ? 'checked' : ''}>
            <span class="ext-slider"></span>
          </span>
        </label>
        ${fields}
      </div>
      <div class="ext-quick-foot">관리: Settings ▸ Extension</div>`;
    // 복잡 모드(우측 칼럼 표시) 시 팝업을 넓힌다.
    el.classList.toggle('ext-quick-popup-wide', hasRightColumn(ext));
    el.style.display = 'block';
    el.querySelector('.ext-quick-close').addEventListener('click', closeQuickPopup);
    el.querySelector('.ext-quick-toggle').addEventListener('change', event => {
      // 끄면 노출 계약에 따라 퀵 버튼·팝업이 함께 사라진다(재활성화는 Settings).
      setModuleParam('extensions', `enabled:${ext.id}`, event.target.checked);
    });
    bindFields(el);
    restoreFocus(el, saved);
  }

  function positionQuickPopup(anchorRect) {
    const el = quickPopupEl();
    // rect가 비정상(0,0 — 닫힌 메뉴에서 측정된 경우 등)이면 화면 좌중단 폴백.
    const usable = anchorRect
      && (anchorRect.width > 0 || anchorRect.height > 0 || anchorRect.left > 0 || anchorRect.top > 0);
    const rect = usable ? anchorRect : {left: 80, bottom: 120, top: 120};
    // 일단 표시 후 실측으로 클램프(적정 사이즈 = 내용 기반, max-width는 CSS).
    const width = el.offsetWidth;
    const height = el.offsetHeight;
    let left = rect.left;
    let top = rect.bottom + 8;
    if (top + height > window.innerHeight - 8) top = Math.max(8, rect.top - height - 8);
    if (left + width > window.innerWidth - 8) left = Math.max(8, window.innerWidth - 8 - width);
    el.style.left = `${left}px`;
    el.style.top = `${top}px`;
  }

  // ── 진입점: module_state 브로드캐스트 ───────────────────────
  function onState(m) {
    if (!m || !m.state) return;
    lastState = m.state;
    bindNav();
    renderSettingsPane();
    syncQuickButtons();
    if (quickPopupId) renderQuickPopup(); // 열려 있으면 라이브 동기화
    if (Array.isArray(m.state.grandfathered) && m.state.grandfathered.length) {
      showToast(`기존 확장 자동 승인됨: ${m.state.grandfathered.join(', ')} (Settings ▸ Extension에서 관리)`, 'info');
    }
  }

  function copyText(text) {
    if (!text) return;
    try {
      navigator.clipboard.writeText(text);
      showToast('경로를 복사했습니다', 'success');
    } catch (_) {
      showToast('복사 실패 — 직접 선택해 복사하세요', 'error');
    }
  }

  return {onState, bindNav};
}
