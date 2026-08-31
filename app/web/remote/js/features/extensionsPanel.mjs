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
  const {document, escHtml, setModuleParam, showToast, requestState, setLauncherItems,
    openExternalUrl} = deps;

  // 퀵 버튼 배치 선택지 — 도구바(독립 바) / 자동화·고급 기능 카테고리 / 없음.
  const PLACEMENT_OPTIONS = [
    ['tools', '도구바 (Tools)'],
    ['assistant_tools', '자동화 / 고급 기능'],
    ['none', '없음'],
  ];
  // 전역 정책: 시작 동작 / 입력 필드 기억.
  const STARTUP_OPTIONS = [
    ['remember', '종료 상태 기억'],
    ['auto_off', '자동 OFF'],
    ['auto_on', '자동 ON'],
  ];
  const REMEMBER_INPUTS_OPTIONS = [
    ['on', '입력 기억 ON'],
    ['off', '입력 기억 OFF'],
  ];
  const ERROR_STATUSES = new Set(['error', 'dependency_error']);

  // 설치할 수 있는 확장 목록 — **앱에 박아 둔 고정 인덱스**(사용자 지정 2026-08-31).
  // A1111 은 위키 URL 을 받아오지만, 여기서는 원격 의존 없이 오프라인에서도 뜨게 한다.
  // 항목을 늘리려면 이 배열에 한 줄 더 넣으면 된다.
  const AVAILABLE_EXTENSIONS = [
    {
      name: 'NAIA-EXten',
      // 설치되면 이 id 로 잡힌다(`extension.json` 이 정한다). ⚠️ 주소만으로는 못
      // 알아본다 - 이 확장의 매니페스트에는 `homepage`/`source_url` 이 없어서
      // 설치 후에도 레코드의 주소가 빈 문자열이다(실측 2026-08-31).
      id: 'naia_exten',
      url: 'https://github.com/okawaritsuika/NAIA-EXten',
      description: 'NAIA 2.0 편의 기능 종합 확장 — 검색 모듈 개선(Parquet 실시간 동기화 · '
        + '확률 분배), 프롬프트 엔지니어링(PromptServer 연동), 만화 생성(Comic Maker), '
        + '개발 핫리로드. 상세 설명 : https://arca.live/b/aiart/181547591',
    },
  ];

  // 이미 깔린 것은 다시 설치하지 않는다. GitHub 주소로 대조한다 - 확장 id 는
  // 저장소 이름과 다를 수 있어서(extension.json 이 정한다) 주소가 유일한 공통 열쇠다.
  function normalizeRepoUrl(url) {
    return String(url || '').trim().toLowerCase()
      .replace(/^https?:\/\//, '').replace(/^www\./, '')
      .replace(/\.git$/, '').replace(/\/+$/, '');
  }

  function installedRepoUrls() {
    const items = (lastState && Array.isArray(lastState.extensions)) ? lastState.extensions : [];
    return new Set(items
      .map(item => normalizeRepoUrl(item && (item.source_url || item.homepage || item.repository)))
      .filter(Boolean));
  }

  function installedIds() {
    const items = (lastState && Array.isArray(lastState.extensions)) ? lastState.extensions : [];
    return new Set(items.map(item => String((item && item.id) || '')).filter(Boolean));
  }

  // 이미 깔렸는가. **id 를 먼저** 본다 - 매니페스트에 주소가 없는 확장이 있어서
  // 주소만으로는 설치 후에도 '설치' 로 남는다. 주소 대조는 id 가 바뀐 경우의 폴백.
  function isAlreadyInstalled(entry, ids, urls) {
    if (entry.id && ids.has(entry.id)) return true;
    return urls.has(normalizeRepoUrl(entry.url));
  }

  let lastState = null;
  let confirmingId = null; // 미승인 확장 활성화 전 신뢰 경고 인라인 확인
  let openMenuId = null;
  let quickPopupId = null; // 열려 있는 퀵 팝업의 확장 id
  let navBound = false;
  // GitHub URL 설치(REST /api/extensions/install) 진행 상태 + 입력 드래프트.
  let installState = null;
  let installUrlDraft = '';
  let installPollTimer = null;
  // 섹션 접힘 상태 — **기본은 전부 펼침**(사용자 지정 2026-08-31).
  // ⚠️ `renderSettingsPane()` 이 innerHTML 을 통째로 다시 그린다. DOM 에 두면
  //    상태 갱신(설치 진행·토글 등)마다 도로 펼쳐진다.
  const collapsed = {installed: false, available: false};

  // ── 공용: 칩/필드 렌더러 (설정 페이지·퀵 팝업 공유) ──────────
  function chipFor(ext) {
    if (ext.status === 'loading') return ['로딩 중…', 'ext-chip-loading'];
    if (ext.status === 'installing_deps') return ['의존성 설치 중…', 'ext-chip-loading'];
    if (ext.status === 'manifest_error') return ['매니페스트 오류', 'ext-chip-error'];
    if (ext.status === 'dependency_error') return ['의존성 오류', 'ext-chip-error'];
    if (ext.status === 'error') return ['오류', 'ext-chip-error'];
    if (ext.blocked) {
      return [ext.status === 'loaded' ? '차단됨 (재시작 시 완전 차단)' : '차단됨', 'ext-chip-muted'];
    }
    if (ext.status === 'discovered') {
      // 의존성이 선언됐는데 미설치면 "승인 시 설치"를 알린다.
      if (Array.isArray(ext.requirements) && ext.requirements.length && !ext.deps_ready) {
        return [`미승인 · 의존성 ${ext.requirements.length}`, 'ext-chip-muted'];
      }
      return ['미승인', 'ext-chip-muted'];
    }
    if (ext.status === 'loaded') {
      if (!ext.enabled) return ['꺼짐', 'ext-chip-off'];
      // enabled인데 armed가 아니면: 노출은 되지만 작동은 멈춘 상태(팝업 Activate OFF).
      return ext.armed === false ? ['활성 · 작동 OFF', 'ext-chip-muted'] : ['활성', 'ext-chip-on'];
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
    } else if (field.type === 'multiselect') {
      // 픽커 패턴: 선택된 항목은 ×로 제거 가능한 칩, 추가는 콤보박스 —
      // WEBUI/ComfyUI 실측 샘플러처럼 옵션이 20개를 넘어도 UI가 밀리지 않는다.
      const current = (Array.isArray(value) ? value : []).map(String);
      const chips = current.map(item =>
        `<span class="ext-ms-sel" data-value="${escHtml(item)}">${escHtml(item)}
           <button type="button" class="ext-ms-remove" title="제거">×</button></span>`).join('');
      const remaining = (field.options || []).filter(opt => !current.includes(opt));
      const addOptions = ['<option value="">+ 추가…</option>']
        .concat(remaining.map(opt => `<option value="${escHtml(opt)}">${escHtml(opt)}</option>`))
        .join('');
      input = `<div class="ext-multiselect" ${common}>
        <div class="ext-ms-chips">${chips || '<span class="ext-ms-empty">선택 없음</span>'}</div>
        <select class="ext-select ext-ms-add"${remaining.length ? '' : ' disabled'}>${addOptions}</select>
      </div>`;
    } else if (field.type === 'list') {
      // 동적 행 목록(예: 스왑 Step들) — [추가 +]로 행을 늘리고 ✕로 제거.
      // multiline이면 행을 textarea로(쉼표 섞인 긴 프롬프트 구문 입력용).
      const items = Array.isArray(value) ? value.map(String) : [];
      const rowInput = (item, index) => field.multiline
        ? `<textarea data-list-index="${index}" rows="2"${ph}>${escHtml(item)}</textarea>`
        : `<input type="text" data-list-index="${index}" value="${escHtml(item)}"${ph}>`;
      const rows = items.map((item, index) =>
        `<div class="ext-list-row${field.multiline ? ' ext-list-row-multi' : ''}">
           <span class="ext-list-step">Step ${index + 1}</span>
           ${rowInput(item, index)}
           <button type="button" class="ext-list-remove" data-remove-index="${index}" title="삭제">×</button>
         </div>`).join('');
      input = `<div class="ext-list${field.multiline ? ' ext-list-multi' : ''}" ${common}>${rows}
        <button type="button" class="ext-list-add">추가 +</button></div>`;
    } else if (field.type === 'tags') {
      const text = Array.isArray(value) ? value.join(', ') : String(value ?? '');
      input = `<input type="text" class="ext-field-wide" ${common} value="${escHtml(text)}"${ph || ' placeholder="쉼표로 구분"'}>`;
    } else if (field.multiline) { // 여러 줄 text — 긴 프롬프트 구문 입력용
      input = `<textarea class="ext-field-wide ext-textarea" ${common} rows="2"${ph}>${escHtml(String(value ?? ''))}</textarea>`;
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

  // hide_arm_when(패널 메타): 현재 설정값이 일치하면 "Activate This Script"(armed)
  // 토글을 숨기고 작동을 끈다 — 그 모드가 action 버튼 전용일 때(예: X/Y Plot).
  function armHidden(ext) {
    const cond = ext.panel?.hide_arm_when;
    if (!cond || !cond.field) return false;
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
    const left = visible.filter(field => !field.column || field.column === 'left');
    const right = visible.filter(field => field.column === 'right');
    const extra = visible.filter(field => field.column === 'extra');
    const leftHtml = columnHtml(ext, left, idPrefix, suppressApply);
    const rightHtml = columnHtml(ext, right, idPrefix, suppressApply);
    const extraHtml = columnHtml(ext, extra, idPrefix, suppressApply);
    if (!leftHtml && !rightHtml && !extraHtml) return '';
    // 딤 처리는 Settings(전역) 화면에서 soft-off일 때만. 팝업(module)은 작동
    // OFF(armed=false) 상태에서도 설정을 편집할 수 있어야 한다(켜기 전 구성).
    const softOff = !(ext.status === 'loaded' && ext.enabled && !ext.blocked);
    const disabled = scope === 'global' && softOff ? ' ext-fields-disabled' : '';
    if (!rightHtml && !extraHtml) return `<div class="ext-fields${disabled}">${leftHtml}</div>${note}`;
    const extraCol = extraHtml
      ? `<div class="ext-fields-col ext-fields-col-extra">${extraHtml}</div>` : '';
    const colClass = extraHtml ? ' ext-fields-three-col' : '';
    return `<div class="ext-fields ext-fields-two-col${colClass}${disabled}">
      <div class="ext-fields-col">${leftHtml}</div>
      <div class="ext-fields-col ext-fields-col-right">${rightHtml}</div>
      ${extraCol}
    </div>${note}`;
  }

  function visibleColumns(ext) {
    if (!ext?.panel || ext.status !== 'loaded') return new Set();
    const cols = new Set();
    ext.panel.fields.forEach(field => {
      if (scopeOf(field) === 'module' && fieldVisible(ext, field)) cols.add(field.column || 'left');
    });
    return cols;
  }

  function listValues(container) {
    return [...container.querySelectorAll('input[type=text], textarea')]
      .map(input => input.value.trim()).filter(Boolean);
  }

  function bindFields(root) {
    root.querySelectorAll('.ext-fields [data-field]').forEach(el => {
      el.addEventListener('change', event => {
        let value;
        if (el.classList.contains('ext-multiselect')) {
          // 현재 칩 목록 + (추가 콤보에서 막 고른 값) = 새 선택 배열.
          value = [...el.querySelectorAll('.ext-ms-sel')].map(chip => chip.dataset.value);
          const addSel = el.querySelector('.ext-ms-add');
          if (event && event.target === addSel && addSel.value && !value.includes(addSel.value)) {
            value.push(addSel.value);
          }
        } else if (el.classList.contains('ext-list')) {
          value = listValues(el);
        } else {
          value = el.type === 'checkbox' ? el.checked : el.value;
        }
        setModuleParam('extensions', `setting:${el.dataset.ext}:${el.dataset.field}`, value);
      });
      if (el.classList.contains('ext-multiselect')) {
        el.querySelectorAll('.ext-ms-remove').forEach(btn => {
          btn.addEventListener('click', () => {
            btn.closest('.ext-ms-sel')?.remove();
            el.dispatchEvent(new Event('change'));
          });
        });
      }
      if (el.classList.contains('ext-list')) {
        // [추가 +]는 로컬로 빈 행만 늘린다(값 전송은 입력 후 change에서 —
        // 빈 행은 저장 시 걸러지므로 브로드캐스트 재렌더에 휘발되지 않게
        // 즉시 포커스를 준다). ✕는 행 제거 후 곧바로 전송.
        el.querySelector('.ext-list-add')?.addEventListener('click', () => {
          const addBtn = el.querySelector('.ext-list-add');
          const index = el.querySelectorAll('.ext-list-row').length;
          const multi = el.classList.contains('ext-list-multi');
          const row = document.createElement('div');
          row.className = `ext-list-row${multi ? ' ext-list-row-multi' : ''}`;
          row.innerHTML = `<span class="ext-list-step">Step ${index + 1}</span>
            ${multi ? `<textarea data-list-index="${index}" rows="2"></textarea>`
                    : `<input type="text" data-list-index="${index}">`}
            <button type="button" class="ext-list-remove" title="삭제">×</button>`;
          addBtn.before(row);
          row.querySelector('.ext-list-remove').addEventListener('click', () => {
            row.remove();
            el.dispatchEvent(new Event('change'));
          });
          const rowInput = row.querySelector('input, textarea');
          rowInput.addEventListener('keydown', event => {
            // 신규 행도 Ctrl+Enter 선커밋(R6-#2) — bindFields 이후 생성되므로 직접 부착.
            if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
              rowInput.dispatchEvent(new Event('change', {bubbles: true}));
            }
          });
          rowInput.focus();
        });
        el.querySelectorAll('.ext-list-remove').forEach(btn => {
          btn.addEventListener('click', () => {
            btn.closest('.ext-list-row')?.remove();
            el.dispatchEvent(new Event('change'));
          });
        });
      }
    });
    root.querySelectorAll('.ext-action-btn[data-action-field]').forEach(el => {
      el.addEventListener('click', () => {
        setModuleParam('extensions', `setting:${el.dataset.ext}:${el.dataset.actionField}`, true);
      });
    });
    // Ctrl+Enter 생성 단축키와의 경합(Codex R6-#2): textarea/input은 blur(change)
    // 시에만 커밋되므로, 포커스를 둔 채 Ctrl+Enter로 생성하면 스테일 값으로
    // 돈다 — 단축키가 버블링되기 전에 change를 강제 발화해 먼저 커밋한다
    // (같은 WS 커넥션이라 setting 메시지가 generate보다 먼저 도착).
    root.querySelectorAll('.ext-fields input, .ext-fields textarea').forEach(el => {
      el.addEventListener('keydown', event => {
        if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
          el.dispatchEvent(new Event('change', {bubbles: true}));
        }
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

  function startupOptionsHtml(ext) {
    const current = ext.startup || 'remember';
    return STARTUP_OPTIONS.map(([val, label]) =>
      `<option value="${val}" ${current === val ? 'selected' : ''}>${label}</option>`).join('');
  }

  function rememberInputsOptionsHtml(ext) {
    const current = ext.remember_inputs === false ? 'off' : 'on';
    return REMEMBER_INPUTS_OPTIONS.map(([val, label]) =>
      `<option value="${val}" ${current === val ? 'selected' : ''}>${label}</option>`).join('');
  }

  function placementSelect(ext) {
    if (ext.status !== 'loaded') return '';
    // 퀵 버튼 위치 + 그 아래 전역 정책 콤보(시작 동작 / 입력 필드 기억).
    return `<div class="ext-policies">
      <label class="ext-placement"><span>퀵 버튼 위치</span>
        <select class="ext-select ext-placement-select" data-ext="${escHtml(ext.id)}">${placementOptionsHtml(ext)}</select></label>
      <label class="ext-placement"><span>시작 동작</span>
        <select class="ext-select ext-startup-select" data-ext="${escHtml(ext.id)}"
          title="다음 시작부터 적용 — 종료 상태 기억 / 자동 OFF / 자동 ON">${startupOptionsHtml(ext)}</select></label>
      <label class="ext-placement"><span>입력 필드</span>
        <select class="ext-select ext-remember-inputs-select" data-ext="${escHtml(ext.id)}"
          title="OFF면 시작 시 설정값이 기본값으로 초기화됩니다">${rememberInputsOptionsHtml(ext)}</select></label>
    </div>`;
  }

  function rowHtml(ext) {
    const [chipLabel, chipClass] = chipFor(ext);
    const hasRecoverableError = ERROR_STATUSES.has(ext.status);
    const showToggle = !['manifest_error', 'error', 'dependency_error'].includes(ext.status) && !ext.blocked;
    const toggleChecked = ext.status === 'loaded' ? ext.enabled : false;
    const toggleDisabled = ext.status === 'loading' || ext.status === 'installing_deps';
    const toggle = showToggle
      ? `<label class="ext-switch" title="${ext.status === 'discovered' ? '활성화(승인 필요)' : '켜기/끄기 (즉시)'}">
           <input type="checkbox" class="ext-toggle" data-ext="${escHtml(ext.id)}" ${toggleChecked ? 'checked' : ''} ${toggleDisabled ? 'disabled' : ''}>
           <span class="ext-slider"></span>
         </label>`
      : (hasRecoverableError
        ? `<button class="ext-retry-btn" data-ext="${escHtml(ext.id)}">재시도</button>` : '');
    // 홈페이지: Electron 셸에선 기본 a[target=_blank]가 내부 팝업(새 NAIA 창)을
    // 띄우므로, 클릭을 가로채 시스템 브라우저로 연다(웹에선 새 탭). data-ext-home에
    // URL을 담아 bindSettingsPane이 핸들러를 건다.
    const home = ext.homepage
      ? ` · <a href="${escHtml(ext.homepage)}" class="ext-home-link" data-ext-home="${escHtml(ext.homepage)}" target="_blank" rel="noopener noreferrer">홈페이지</a>` : '';
    const desc = ext.description || home
      ? `<div class="ext-desc">${escHtml(ext.description || '')}${home}</div>` : '';
    const error = ext.error
      ? `<div class="ext-error" title="${escHtml(ext.error)}">${escHtml(ext.error)}${hasRecoverableError ? ' — 수정 후 재시도하거나 재시작' : ''}</div>` : '';
    const needsDeps = Array.isArray(ext.requirements) && ext.requirements.length && !ext.deps_ready;
    const depsNote = needsDeps
      ? `<div class="ext-confirm-deps">📦 의존성 ${ext.requirements.length}개를 격리 설치합니다(본체 미오염·미리 빌드된 wheel만):
           <code>${escHtml(ext.requirements.join(', '))}</code></div>` : '';
    const confirm = confirmingId === ext.id
      ? `<div class="ext-confirm">⚠️ 이 확장은 NAIA와 같은 권한으로 <b>임의 Python 코드</b>를 실행하며
           생성 파이프라인과 API 토큰 등 자격증명에 접근할 수 있습니다. 제작자를 신뢰할 때만 활성화하세요.
           ${depsNote}
           <div class="ext-confirm-actions">
             <button class="ext-approve-btn" data-ext="${escHtml(ext.id)}">${needsDeps ? '신뢰하고 설치·활성화' : '신뢰하고 활성화'}</button>
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
    if (!active || !root || !root.contains(active)) return null;
    // list 행 입력: 컨테이너(data-field)+행 인덱스로 복원 좌표를 잡는다.
    const listBox = active.closest?.('.ext-list[data-field]');
    if (listBox && active.dataset && active.dataset.listIndex != null) {
      return {
        ext: listBox.dataset.ext,
        field: listBox.dataset.field,
        listIndex: active.dataset.listIndex,
        selStart: active.selectionStart,
        selEnd: active.selectionEnd,
      };
    }
    if (!active.dataset || !active.dataset.field) return null;
    return {
      ext: active.dataset.ext,
      field: active.dataset.field,
      selStart: active.selectionStart,
      selEnd: active.selectionEnd,
    };
  }

  function restoreFocus(root, saved) {
    if (!saved || !root) return;
    let el = root.querySelector(
      `[data-ext="${CSS.escape(saved.ext)}"][data-field="${CSS.escape(saved.field)}"]`);
    if (el && saved.listIndex != null) {
      el = el.querySelector(`[data-list-index="${CSS.escape(saved.listIndex)}"]`)
        || el.querySelector('input[type=text], textarea');
    }
    if (!el) return;
    el.focus();
    if (saved.selStart != null && typeof el.setSelectionRange === 'function') {
      try { el.setSelectionRange(saved.selStart, saved.selEnd); } catch (_) { /* number input 등 */ }
    }
  }

  // ── GitHub URL 설치 (REST + 진행률 폴링) ─────────────────────
  function installFormHtml() {
    const active = installState && installState.active;
    if (active) {
      const pct = Math.max(0, Math.min(100, installState.percent || 0));
      return `<div class="ext-install-github ext-install-running">
        <div class="ext-install-progress">
          <div class="ext-install-bar" style="width:${pct}%"></div>
        </div>
        <span class="ext-install-msg">${escHtml(installState.message || '설치 중...')}</span>
        <button type="button" class="ext-install-cancel">취소</button>
      </div>`;
    }
    const note = installState && installState.error
      ? `<div class="ext-install-note ext-install-error">${escHtml(installState.error)}</div>`
      : (installState && installState.done && installState.installed_name
        ? `<div class="ext-install-note ext-install-ok">'${escHtml(installState.installed_name)}' 설치됨 — 아래에서 승인하세요.</div>`
        : '');
    return `<div class="ext-install-github">
      <input type="text" class="ext-install-url" placeholder="https://github.com/owner/repo"
        value="${escHtml(installUrlDraft)}" spellcheck="false">
      <button type="button" class="ext-install-btn">GitHub에서 설치</button>
    </div>${note}`;
  }

  async function postInstall(path, body) {
    const res = await fetch(`/api/extensions/install${path}`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body || {}),
    });
    return res.json();
  }

  // 번들 샘플(seed_fanout) 원클릭 설치 — 폴더를 손으로 옮기지 않아도 됨. 설치 후엔
  // 재발견되어 discovered(미승인)로 뜨므로, 사용자는 기존대로 신뢰 승인을 거친다.
  async function installSample() {
    let state;
    try {
      state = await postInstall('/sample', {sample: 'seed_fanout'});
    } catch (error) {
      state = {ok: false, error: String(error)};
    }
    if (!state || state.ok === false || state.error) {
      const msg = (state && state.error) || '샘플 설치 실패';
      installState = (state && state.error) ? state : installState;
      showToast(msg, 'error');
      renderSettingsPane();
      return;
    }
    installState = state;
    if (state.installed_name) {
      showToast(`'${state.installed_name}' 설치됨 — 아래에서 승인하세요.`, 'success');
    }
    if (typeof requestState === 'function') requestState(); // 재발견 + 패널 갱신
    renderSettingsPane();
  }

  function stopInstallPoll() {
    if (installPollTimer) { clearInterval(installPollTimer); installPollTimer = null; }
  }

  function startInstallPoll() {
    stopInstallPoll();
    installPollTimer = setInterval(async () => {
      try {
        const res = await fetch('/api/extensions/install');
        const state = await res.json();
        installState = state;
        if (!state.active) {
          stopInstallPoll();
          if (state.done && state.installed_id) {
            installUrlDraft = '';
            showToast(`확장 '${state.installed_name || state.installed_id}' 설치됨 — 승인하면 사용됩니다.`, 'success');
            if (typeof requestState === 'function') requestState(); // 재발견(미승인 등록)
          } else if (state.error) {
            showToast(`설치 실패: ${state.error}`, 'error');
          }
        }
        renderSettingsPane();
      } catch (_) { /* 폴링 실패는 다음 틱에 복구 */ }
    }, 600);
  }

  async function startInstall(url) {
    const target = String(url || '').trim();
    if (!target) { showToast('GitHub 주소를 입력하세요.', 'error'); return; }
    installState = {active: true, percent: 0, message: '설치 준비 중...', error: '', done: false};
    renderSettingsPane();
    try {
      const state = await postInstall('', {url: target});
      if (state && state.ok === false) {
        installState = {active: false, error: state.error || '설치 시작 실패', done: false};
        showToast(state.error || '설치 시작 실패', 'error');
        renderSettingsPane();
        return;
      }
      installState = state;
      startInstallPoll();
      renderSettingsPane();
    } catch (error) {
      installState = {active: false, error: String(error), done: false};
      renderSettingsPane();
    }
  }

  // 접고 펼치는 섹션 머리. 개수를 함께 보여 줘 접어 둔 채로도 몇 개인지 알 수 있게 한다.
  function sectionHeadHtml(key, title, count) {
    const isOpen = !collapsed[key];
    return `<button type="button" class="ext-section-head" data-section="${key}"
      aria-expanded="${isOpen ? 'true' : 'false'}">
      <span class="ext-section-caret">${isOpen ? '▾' : '▸'}</span>
      <span class="ext-section-title">${escHtml(title)}</span>
      ${count == null ? '' : `<span class="ext-section-count">${count}</span>`}
    </button>`;
  }

  // 설치 가능한 확장 표 — [ 이름 | 설명 | GitHub 링크 ] [ 설치 ] (사용자 지정 구조).
  function availableExtensionsHtml() {
    const urls = installedRepoUrls();
    const ids = installedIds();
    const rows = AVAILABLE_EXTENSIONS.map((entry) => {
      const already = isAlreadyInstalled(entry, ids, urls);
      const busy = !!(installState && installState.active);
      // ⚠️ 설명 안의 링크는 **텍스트로 이스케이프한 뒤** 앵커로 바꾼다. 원문을 그대로
      //    넣으면 확장 작성자가 쓴 문자열이 마크업이 된다.
      const described = escHtml(entry.description).replace(
        /(https?:\/\/[^\s<]+)/g,
        '<a href="$1" class="ext-avail-inline-link" target="_blank" rel="noopener noreferrer">$1</a>');
      return `<div class="ext-avail-row">
        <div class="ext-avail-main">
          <div class="ext-avail-name">${escHtml(entry.name)}</div>
          <div class="ext-avail-desc">${described}</div>
          <a class="ext-avail-link" href="${escHtml(entry.url)}" target="_blank" rel="noopener noreferrer">${escHtml(entry.url)}</a>
        </div>
        <button type="button" class="ext-avail-install" data-url="${escHtml(entry.url)}"
          ${already || busy ? 'disabled' : ''}>${already ? '설치됨' : '설치'}</button>
      </div>`;
    }).join('');
    return `<div class="ext-avail">
      ${sectionHeadHtml('available', '설치할 수 있는 확장', AVAILABLE_EXTENSIONS.length)}
      ${collapsed.available ? '' : rows}
    </div>`;
  }

  function renderSettingsPane() {
    const root = pane();
    if (!root || !lastState) return;
    const saved = captureFocus(root);
    const items = Array.isArray(lastState.extensions) ? lastState.extensions : [];
    const errors = items.filter(item => ERROR_STATUSES.has(item.status)).length;
    const head = `<div class="ext-head">
        <span class="ext-install-label">설치 폴더:</span>
        <code class="ext-install-path" title="${escHtml(lastState.install_dir || '')}">${escHtml(lastState.install_dir || '')}</code>
        <button class="ext-copy-install">복사</button>
        ${errors ? `<button class="ext-retry-all">오류 ${errors}건 재시도</button>` : ''}
      </div>${installFormHtml()}`;
    const listHtml = items.length
      ? items.map(rowHtml).join('')
      : `<div class="ext-empty">설치된 확장이 없습니다.<br>
           위 폴더에 <code>&lt;확장-id&gt;/extension.json + main.py</code>를 넣으면 이 목록에 나타납니다.<br>
           샘플 <code>seed_fanout</code>(여러장 생성-X/Y Plot)을 한 번에 설치할 수 있습니다.
           <div class="ext-empty-cta">
             <button type="button" class="ext-install-sample">샘플 바로 사용하기</button>
           </div></div>`;
    const body = `<div class="ext-installed">
      ${sectionHeadHtml('installed', '설치된 확장', items.length)}
      ${collapsed.installed ? '' : listHtml}
    </div>`;
    root.innerHTML = `<div class="ext-panel">${head}${body}${availableExtensionsHtml()}</div>`;
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
    const sampleBtn = root.querySelector('.ext-install-sample');
    if (sampleBtn) sampleBtn.addEventListener('click', () => installSample());
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
    // GitHub URL 설치 폼.
    const urlInput = root.querySelector('.ext-install-url');
    if (urlInput) {
      urlInput.addEventListener('input', () => { installUrlDraft = urlInput.value; });
      urlInput.addEventListener('keydown', event => {
        if (event.key === 'Enter') { event.preventDefault(); startInstall(urlInput.value); }
      });
    }
    root.querySelectorAll('.ext-section-head').forEach((btn) => {
      btn.addEventListener('click', () => {
        const key = btn.dataset.section;
        if (!(key in collapsed)) return;
        collapsed[key] = !collapsed[key];
        renderSettingsPane();
      });
    });
    root.querySelectorAll('.ext-avail-install').forEach((btn) => {
      btn.addEventListener('click', () => {
        if (btn.disabled) return;
        // 기존 GitHub 설치 경로를 그대로 쓴다 - 설치 로직을 두 벌로 만들지 않는다.
        startInstall(btn.dataset.url || '');
      });
    });
    const installBtn = root.querySelector('.ext-install-btn');
    if (installBtn) installBtn.addEventListener('click', () =>
      startInstall(root.querySelector('.ext-install-url')?.value || installUrlDraft));
    const cancelBtn = root.querySelector('.ext-install-cancel');
    if (cancelBtn) cancelBtn.addEventListener('click', async () => {
      await postInstall('/cancel', {});
    });
    root.querySelectorAll('.ext-placement-select').forEach(el => {
      el.addEventListener('change', () => {
        setModuleParam('extensions', `placement:${el.dataset.ext}`, el.value);
      });
    });
    root.querySelectorAll('.ext-startup-select').forEach(el => {
      el.addEventListener('change', () => {
        setModuleParam('extensions', `startup:${el.dataset.ext}`, el.value);
      });
    });
    root.querySelectorAll('.ext-remember-inputs-select').forEach(el => {
      el.addEventListener('change', () => {
        setModuleParam('extensions', `remember_inputs:${el.dataset.ext}`, el.value === 'on');
      });
    });
    root.querySelectorAll('.ext-home-link[data-ext-home]').forEach(el => {
      el.addEventListener('click', event => {
        // 시스템 브라우저로 — 헬퍼가 없으면 기본 동작(웹: 새 탭) 유지.
        if (typeof openExternalUrl === 'function') {
          event.preventDefault();
          openExternalUrl(el.dataset.extHome);
        }
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
          `<button type="button" class="module-btn ext-tool-btn${ext.armed === false ? ' ext-armed-off' : ''}"
             data-ext="${escHtml(ext.id)}" title="${escHtml(ext.description || ext.name)}${ext.armed === false ? ' (작동 꺼짐)' : ''}">
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
            title: (ext.description || ext.name || ext.id) + (ext.armed === false ? ' (작동 꺼짐)' : ''),
            category: 'assistant_tools',
            armedOff: ext.armed === false,
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
    // 모드 전환 후 첫 오픈 등 stale 옵션(샘플러 목록 등) 대비 — 백엔드 상태를
    // 재요청하면 브로드캐스트 재렌더가 열린 팝업을 라이브 갱신한다.
    if (typeof requestState === 'function') requestState();
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
    const hideArm = armHidden(ext);
    const activateRow = hideArm ? '' : `
        <label class="ext-quick-activate" title="작동만 켜고 끕니다 — 꺼도 버튼은 남습니다. 숨김까지 끄려면 Settings ▸ Extension">
          <span class="ext-quick-activate-label">Activate This Script</span>
          <span class="ext-switch">
            <input type="checkbox" class="ext-quick-toggle" ${ext.armed === false ? '' : 'checked'}>
            <span class="ext-slider"></span>
          </span>
        </label>`;
    el.innerHTML = `
      <div class="ext-quick-head">
        <span class="ext-quick-title">
          <span class="ext-quick-icon" aria-hidden="true">🧩</span>
          <span>${escHtml(ext.name || ext.id)}</span>
        </span>
        <button type="button" class="ext-quick-close" title="닫기">×</button>
      </div>
      <div class="ext-quick-body">
        ${activateRow}
        ${fields}
      </div>
      <div class="ext-quick-foot">관리: Settings ▸ Extension</div>`;
    // 복잡 모드(우측/3번째 칼럼 표시) 시 팝업을 단계적으로 넓힌다.
    const cols = visibleColumns(ext);
    el.classList.toggle('ext-quick-popup-wide', cols.has('right') || cols.has('extra'));
    el.classList.toggle('ext-quick-popup-xwide', cols.has('extra'));
    // 'flex'로 표시해야 CSS의 column 레이아웃(높이 상한 + 바디 스크롤,
    // 055337ee)이 산다 — 'block'이면 인라인 스타일이 flex를 무효화해 바디가
    // 줄지 않고 푸터가 잘린다.
    el.style.display = 'flex';
    el.querySelector('.ext-quick-close').addEventListener('click', closeQuickPopup);
    const armToggle = el.querySelector('.ext-quick-toggle');
    if (armToggle) {
      armToggle.addEventListener('change', event => {
        // 모듈 작동 스위치(armed): 작동만 멈추고 버튼·팝업은 유지된다.
        // 노출까지 끄는 것은 Settings ▸ Extension의 토글(enabled) 전담.
        setModuleParam('extensions', `armed:${ext.id}`, event.target.checked);
      });
    }
    // hide_arm_when 모드(예: X/Y Plot)는 action 버튼 전용 — 작동(armed)을 자동으로 끈다
    // (passive 가로채기 방지). idempotent: armed===false면 재전송 안 함(재렌더 루프 방지).
    if (hideArm && ext.armed !== false) {
      setModuleParam('extensions', `armed:${ext.id}`, false);
    }
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

  // ── 글로벌 정책: API 모드 전환 ───────────────────────────────
  // 모드가 바뀌면 열려 있는 퀵 팝업은 stale(모드별 선택지·NAI 전용 축 등) —
  // 닫고 상태를 재요청해 다음 오픈이 새 모드의 패널로 그려지게 한다.
  function onApiModeChanged() {
    if (quickPopupId) closeQuickPopup();
    if (typeof requestState === 'function') requestState();
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

  return {onState, bindNav, onApiModeChanged};
}
