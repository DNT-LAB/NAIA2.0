// Extensions 관리 패널 — 확장 발견/승인(load-on-enable)/soft ON·OFF/차단 + 선언적
// 설정 폼(제네릭 렌더러). 토글은 승인/soft 전용이고 차단은 ⋯ 메뉴로 분리한다
// (설계 인스펙션 #4 — 한 토글이 상태에 따라 세 가지 일을 하면 안 된다).
export function createExtensionsPanel(deps) {
  const {document, moduleBody, escHtml, setModuleParam, showToast} = deps;

  let lastState = null;
  let confirmingId = null; // 미승인 확장 활성화 전 신뢰 경고 인라인 확인
  let openMenuId = null;

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

  function fieldHtml(ext, field) {
    if (field.type === 'action') return ''; // v1 예약 타입 — 렌더하지 않음
    const value = ext.settings && field.key in ext.settings ? ext.settings[field.key] : field.default;
    const fid = `extf-${ext.id}-${field.key}`;
    const help = field.help ? ` title="${escHtml(field.help)}"` : '';
    let input = '';
    if (field.type === 'bool') {
      input = `<input type="checkbox" id="${fid}" data-ext="${escHtml(ext.id)}" data-field="${escHtml(field.key)}" ${value ? 'checked' : ''}>`;
    } else if (field.type === 'int' || field.type === 'float') {
      const min = field.min !== undefined ? ` min="${field.min}"` : '';
      const max = field.max !== undefined ? ` max="${field.max}"` : '';
      const step = field.step !== undefined ? ` step="${field.step}"` : (field.type === 'float' ? ' step="0.1"' : '');
      input = `<input type="number" id="${fid}" data-ext="${escHtml(ext.id)}" data-field="${escHtml(field.key)}"${min}${max}${step} value="${escHtml(String(value ?? ''))}">`;
    } else if (field.type === 'select') {
      const options = (field.options || []).map(opt =>
        `<option value="${escHtml(opt)}" ${String(value) === opt ? 'selected' : ''}>${escHtml(opt)}</option>`).join('');
      input = `<select id="${fid}" data-ext="${escHtml(ext.id)}" data-field="${escHtml(field.key)}">${options}</select>`;
    } else if (field.type === 'tags') {
      const text = Array.isArray(value) ? value.join(', ') : String(value ?? '');
      input = `<input type="text" id="${fid}" class="ext-field-wide" data-ext="${escHtml(ext.id)}" data-field="${escHtml(field.key)}" value="${escHtml(text)}" placeholder="쉼표로 구분">`;
    } else { // text
      input = `<input type="text" id="${fid}" class="ext-field-wide" data-ext="${escHtml(ext.id)}" data-field="${escHtml(field.key)}" value="${escHtml(String(value ?? ''))}">`;
    }
    const error = ext.field_errors && ext.field_errors[field.key]
      ? `<div class="ext-field-error">${escHtml(ext.field_errors[field.key])}</div>` : '';
    return `<div class="ext-field"${help}><label for="${fid}">${escHtml(field.label)}${applyHint(field)}</label>${input}${error}</div>`;
  }

  function fieldsHtml(ext) {
    if (!ext.panel || !Array.isArray(ext.panel.fields) || ext.status !== 'loaded') return '';
    let html = '';
    let section = null;
    for (const field of ext.panel.fields) {
      if (field.type === 'action') continue;
      if ((field.section || '') !== section) {
        section = field.section || '';
        if (section) html += `<div class="ext-section">${escHtml(section)}</div>`;
      }
      html += fieldHtml(ext, field);
    }
    if (!html) return '';
    const disabled = !ext.active ? ' ext-fields-disabled' : '';
    return `<div class="ext-fields${disabled}">${html}</div>`;
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
        <div class="ext-controls">${toggle}<button class="ext-menu-btn" data-ext="${escHtml(ext.id)}">⋯</button></div>
      </div>
      ${confirm}${menu}${error}${fieldsHtml(ext)}
    </div>`;
  }

  function captureFocus() {
    const active = document.activeElement;
    if (!active || !moduleBody.contains(active) || !active.dataset || !active.dataset.field) return null;
    return {
      ext: active.dataset.ext,
      field: active.dataset.field,
      selStart: active.selectionStart,
      selEnd: active.selectionEnd,
    };
  }

  function restoreFocus(saved) {
    if (!saved) return;
    const el = moduleBody.querySelector(
      `[data-ext="${CSS.escape(saved.ext)}"][data-field="${CSS.escape(saved.field)}"]`);
    if (!el) return;
    el.focus();
    if (saved.selStart != null && typeof el.setSelectionRange === 'function') {
      try { el.setSelectionRange(saved.selStart, saved.selEnd); } catch (_) { /* number input 등 */ }
    }
  }

  function render(m) {
    if (!m || !m.state) return;
    lastState = m.state;
    const saved = captureFocus();
    const items = Array.isArray(m.state.extensions) ? m.state.extensions : [];
    const errors = items.filter(item => item.status === 'error').length;
    const head = `<div class="ext-head">
        <span class="ext-install-label">설치 폴더:</span>
        <code class="ext-install-path" title="${escHtml(m.state.install_dir || '')}">${escHtml(m.state.install_dir || '')}</code>
        <button class="ext-copy-install">복사</button>
        ${errors ? `<button class="ext-retry-all">오류 ${errors}건 재시도</button>` : ''}
      </div>`;
    const body = items.length
      ? items.map(rowHtml).join('')
      : `<div class="ext-empty">설치된 확장이 없습니다.<br>
           위 폴더에 <code>&lt;확장-id&gt;/extension.json + main.py</code>를 넣으면 이 목록에 나타납니다.<br>
           샘플: 릴리즈의 <code>release_assets/samples/extensions/seed_fanout</code> 폴더를 복사해 보세요.</div>`;
    moduleBody.innerHTML = `<div class="ext-panel">${head}${body}</div>`;
    bind();
    restoreFocus(saved);
    if (Array.isArray(m.state.grandfathered) && m.state.grandfathered.length) {
      showToast(`기존 확장 자동 승인됨: ${m.state.grandfathered.join(', ')} (Extensions 패널에서 관리)`, 'info');
    }
  }

  function findExt(extId) {
    return (lastState?.extensions || []).find(item => item.id === extId) || null;
  }

  function bind() {
    moduleBody.querySelectorAll('.ext-toggle').forEach(el => {
      el.addEventListener('change', () => {
        const ext = findExt(el.dataset.ext);
        if (!ext) return;
        if (ext.status === 'discovered') {
          // 승인은 신뢰 경고 인라인 확인을 거친다 — 토글은 일단 되돌린다.
          el.checked = false;
          confirmingId = ext.id;
          openMenuId = null;
          render({state: lastState});
          return;
        }
        setModuleParam('extensions', `enabled:${ext.id}`, el.checked);
      });
    });
    moduleBody.querySelectorAll('.ext-approve-btn').forEach(el => {
      el.addEventListener('click', () => {
        confirmingId = null;
        setModuleParam('extensions', `approve:${el.dataset.ext}`, true);
      });
    });
    moduleBody.querySelectorAll('.ext-cancel-btn').forEach(el => {
      el.addEventListener('click', () => { confirmingId = null; render({state: lastState}); });
    });
    moduleBody.querySelectorAll('.ext-retry-btn').forEach(el => {
      el.addEventListener('click', () => setModuleParam('extensions', `retry:${el.dataset.ext}`, true));
    });
    const retryAll = moduleBody.querySelector('.ext-retry-all');
    if (retryAll) retryAll.addEventListener('click', () => setModuleParam('extensions', 'retry_errors', true));
    moduleBody.querySelectorAll('.ext-menu-btn').forEach(el => {
      el.addEventListener('click', () => {
        openMenuId = openMenuId === el.dataset.ext ? null : el.dataset.ext;
        confirmingId = null;
        render({state: lastState});
      });
    });
    moduleBody.querySelectorAll('.ext-block-btn').forEach(el => {
      el.addEventListener('click', () => {
        openMenuId = null;
        setModuleParam('extensions', `blocked:${el.dataset.ext}`, !el.dataset.blocked);
      });
    });
    moduleBody.querySelectorAll('.ext-copy-dir-btn').forEach(el => {
      el.addEventListener('click', () => copyText(el.dataset.dir));
    });
    const copyInstall = moduleBody.querySelector('.ext-copy-install');
    if (copyInstall) {
      copyInstall.addEventListener('click', () => copyText(lastState?.install_dir || ''));
    }
    moduleBody.querySelectorAll('.ext-fields [data-field]').forEach(el => {
      el.addEventListener('change', () => {
        const value = el.type === 'checkbox' ? el.checked : el.value;
        setModuleParam('extensions', `setting:${el.dataset.ext}:${el.dataset.field}`, value);
      });
    });
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

  return {render};
}
