// NAI 다중 계정(Multi Token) — 화면 두 곳을 한 모듈이 맡는다.
//
//   1) 결과 뷰어의 USAGE 배지를 누르면 뜨는 팝오버
//      통합(평균) 사용량 · 계정별 막대 · [+ Manage Account] · 부하 분산 정책 4종
//   2) API 설정 대화상자의 NAI 탭에 붙는 계정 관리 목록
//      계정 추가/삭제 · 토큰 입력 · 켬/끔  (Dev0714 PyQt 창에 있던 것)
//
// 두 화면이 같은 상태를 본다. 배지 쪽에서 정책을 바꿔도 설정 쪽 목록이 같이 갱신되고,
// 그 반대도 마찬가지다 — 서버가 변경 때마다 `nai_accounts` 스냅샷을 다시 보내기 때문.
//
// 데이터가 둘로 나뉜 이유:
//   `nai_accounts`     계정 **명부**(끈 계정 포함). 설정 화면이 이걸 그린다.
//   `nai_usage_update` **활성 계정의 사용량**. 배지/막대가 이걸 쓴다. V5 일 때만 온다.
// 명부와 사용량을 한 메시지로 합치지 않은 건, 사용량 조회가 계정 수만큼 네트워크를
// 타서 명부보다 훨씬 느리고 훨씬 자주 없기 때문이다.

const POLICY_FALLBACK = [
  { key: 'round_robin', label: '라운드 로빈', desc: '1장씩 번갈아가며 생성합니다.' },
];

export function createNaiAccountPanel({
  document,
  getWs,
  WebSocket,
  showToast,
  confirmDialog = async () => false,
  openAccountSettings = () => {},
}) {
  const byId = id => document.getElementById(id);

  const state = {
    accounts: [],           // 명부(끈 계정 포함)
    policy: 'round_robin',
    policyOptions: POLICY_FALLBACK,
    canAdd: true,
    activeCount: 0,
    balancingEffective: false,
    loaded: false,
  };
  // 계정별 사용량 — `nai_usage_update` 가 채운다. 명부와 수명이 다르다.
  //
  // ⚠️ 막대는 **이 목록**으로 그린다(명부가 아니라). 서버가 `active_accounts()` 로
  // 만든 '지금 회전에 들어 있는 계정' 이라 이쪽이 사실이다. 처음엔 명부를 걸러서
  // 그렸는데, 명부와 사용량이 따로 도착하는 탓에 계정을 막 추가한 직후처럼 둘이
  // 어긋난 순간에 행 수가 틀렸다(실측: 사용량엔 2개인데 화면엔 1줄).
  let usageRows = [];
  let totalPercent = null;
  let popOpen = false;

  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function send(payload) {
    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify(payload));
    return true;
  }

  // ⚠️ 이 모듈은 **비동기 import** 라 소켓과의 선후가 매번 다르다. 실측(2026-08-21):
  // 첫 부팅에서는 모듈이 37초에야 뜨고(소켓은 이미 열림), 새로고침에서는 모듈이 먼저
  // 뜬다(소켓이 아직 안 열림). 뒤쪽 경우에 한 번 보내고 마니까 설정 화면의 계정
  // 목록이 영영 비어 있었다. 열릴 때까지 짧게 되묻는다.
  let retryTimer = null;
  let retries = 0;

  function requestAccounts() {
    if (retryTimer) { clearTimeout(retryTimer); retryTimer = null; }
    if (send({ type: 'nai_accounts_get' })) { retries = 0; return true; }
    if (retries >= 20) return false;             // 10초쯤 시도하고 포기(화면을 열면 다시 청한다)
    retries += 1;
    retryTimer = setTimeout(() => { retryTimer = null; requestAccounts(); }, 500);
    return false;
  }

  // ---- 서버 메시지 -----------------------------------------------------

  function onAccounts(message) {
    if (!message || typeof message !== 'object') return;
    state.accounts = Array.isArray(message.accounts) ? message.accounts : [];
    state.policy = message.policy || state.policy;
    if (Array.isArray(message.policy_options) && message.policy_options.length) {
      state.policyOptions = message.policy_options;
    }
    state.canAdd = message.can_add !== false;
    state.activeCount = Number(message.active_count) || 0;
    state.balancingEffective = !!message.balancing_effective;
    state.loaded = true;
    renderPopover();
    renderSetupList();
  }

  function onAccountResult(message) {
    if (!message) return;
    if (!message.ok && message.message) showToast(message.message, 'error');
    else if (message.ok && message.message) showToast(message.message, 'info');
    setSetupBusy(false);
  }

  // 배지 메시지에서 계정별 사용량만 뽑아 둔다. 배지 자체(퍼센트/숨김)는 app.js 담당.
  function onUsageUpdate(message) {
    if (!message || !message.available) {
      usageRows = [];
      totalPercent = null;
      // 배지가 사라지면 팝오버도 같이 닫는다 - 앵커 없이 떠 있으면 유령이다.
      closePopover();
      renderPopover();
      return;
    }
    totalPercent = Number.isFinite(message.percent) ? message.percent : null;
    const rows = Array.isArray(message.accounts) ? message.accounts : [];
    if (rows.length) {
      usageRows = rows.filter(row => row && row.id);
    } else {
      // 계정이 하나면 서버는 `accounts` 를 안 붙인다(요청을 아끼려고). 그때는
      // 배지 값이 곧 그 계정의 값이므로 명부에서 활성 하나를 찾아 한 줄로 만든다.
      const only = state.accounts.find(a => a.enabled && a.has_token);
      usageRows = only ? [{
        id: only.id, label: only.label, token_preview: only.token_preview,
        available: true, percent: totalPercent || 0, is_negative: !!message.is_negative,
      }] : [];
    }
    if (message.policy) state.policy = message.policy;
    if (typeof message.balancing_effective === 'boolean') {
      state.balancingEffective = message.balancing_effective;
    }
    renderPopover();
  }

  // ---- 배지 팝오버 -----------------------------------------------------

  function popEl() {
    return byId('naiAcctPop');
  }

  function openPopover() {
    const el = popEl();
    if (!el) return;
    // 명부를 아직 못 받았으면 지금 받아 온다(배지만 보고 한 번도 안 열어본 경우).
    if (!state.loaded) requestAccounts();
    popOpen = true;
    renderPopover();
    el.classList.remove('hidden');
  }

  function closePopover() {
    popOpen = false;
    const el = popEl();
    if (el) el.classList.add('hidden');
  }

  function togglePopover() {
    if (popOpen) closePopover();
    else openPopover();
  }

  function barHtml(percent, isOut) {
    const width = Math.max(0, Math.min(100, Number(percent) || 0));
    return `<span class="nai-acct-bar${isOut ? ' is-out' : ''}"><i style="width:${width}%"></i></span>`;
  }

  function accountRowsHtml() {
    // 사용량이 왔으면 그걸 쓰고, 아직이면 명부의 활성 계정을 '—' 로 미리 그린다
    // (계정을 막 켠 직후 다음 조회까지의 공백을 빈 화면으로 두지 않는다).
    const rows = usageRows.length
      ? usageRows
      : state.accounts.filter(a => a.enabled && a.has_token)
          .map(a => ({ ...a, available: false, percent: 0 }));
    if (!rows.length) {
      return '<div class="nai-acct-empty">활성 계정이 없습니다.</div>';
    }
    return rows.map(row => {
      const known = !!row.available;
      // 사용자 표기(명세)는 토큰 앞자리 — 어느 계정인지 한눈에 구분되는 값이다.
      const name = (row.token_preview || row.label || '').toUpperCase();
      const pct = known ? `${Number(row.percent) || 0}%` : '—';
      return `<div class="nai-acct-row" title="${esc(row.label || '')}">`
        + `<span class="nai-acct-name">${esc(name)}</span>`
        + barHtml(known ? row.percent : 0, known && row.is_negative)
        + `<span class="nai-acct-pct">${esc(pct)}</span>`
        + '</div>';
    }).join('');
  }

  function policiesHtml() {
    const disabled = state.balancingEffective ? '' : ' is-idle';
    return state.policyOptions.map(option => {
      const on = option.key === state.policy;
      return `<button type="button" class="nai-acct-policy${on ? ' on' : ''}${disabled}"`
        + ` data-policy="${esc(option.key)}">`
        + `<span class="nai-acct-radio">${on ? '●' : '○'}</span>`
        + `<span class="nai-acct-policy-text">`
        + `<b>${esc(option.label)}</b>`
        + `<em>${esc(option.desc)}</em>`
        + '</span></button>';
    }).join('');
  }

  function renderPopover() {
    const el = popEl();
    if (!el || !popOpen) return;
    const total = totalPercent == null ? '—' : `${totalPercent}%`;
    el.innerHTML = ''
      + '<div class="nai-acct-head">'
      + '<span class="nai-acct-title">USAGE</span>'
      + `<span class="nai-acct-total">통합 ${esc(total)}</span>`
      + '</div>'
      + `<div class="nai-acct-rows">${accountRowsHtml()}</div>`
      + '<button type="button" class="nai-acct-manage" data-act="manage">'
      + '<span>＋</span> Manage Account</button>'
      + '<div class="nai-acct-sec">Load Balancing</div>'
      + `<div class="nai-acct-policies">${policiesHtml()}</div>`
      + (state.balancingEffective ? ''
        : '<div class="nai-acct-note">활성 계정이 2개 이상일 때 적용됩니다.</div>');
  }

  function onPopoverClick(event) {
    const manage = event.target.closest('[data-act="manage"]');
    if (manage) {
      closePopover();
      openAccountSettings();
      return;
    }
    const policy = event.target.closest('[data-policy]');
    if (policy) {
      const key = policy.getAttribute('data-policy');
      if (key === state.policy) return;
      state.policy = key;          // 낙관적 반영 - 서버 스냅샷이 곧 확정한다.
      renderPopover();
      send({ type: 'nai_account_set_policy', policy: key });
    }
  }

  // 바깥을 누르면 닫힌다. 배지 자신은 토글이므로 제외해야 **열자마자 닫히지 않는다.**
  function onDocumentPointerDown(event) {
    if (!popOpen) return;
    const el = popEl();
    const pill = byId('naiUsagePill');
    if (!el) return;
    if (el.contains(event.target)) return;
    if (pill && pill.contains(event.target)) return;
    closePopover();
  }

  // ---- 설정 대화상자의 계정 관리 ----------------------------------------

  function setSetupBusy(busy) {
    const host = byId('setupAccounts');
    if (host) host.classList.toggle('is-busy', !!busy);
  }

  function renderSetupList() {
    const list = byId('setupAccountsList');
    if (!list) return;
    if (!state.accounts.length) {
      list.innerHTML = '<div class="setup-account-empty">계정 정보를 불러오는 중…</div>';
      return;
    }
    list.innerHTML = state.accounts.map(account => {
      const idAttr = esc(account.id);
      const preview = account.has_token ? `${esc(account.token_preview)}…` : '미설정';
      // ⚠️ 메인 계정에는 토큰 칸을 **주지 않는다.** 바로 위 '영구 토큰' 칸이 같은
      // 토큰을 관리하므로, 여기에도 두면 같은 값을 넣는 입력이 화면에 둘이 된다.
      // 메인 행이 여기 있는 이유는 오직 "회전에 넣을까 뺄까" 하나다. 삭제도 없다.
      const own = !account.is_main;
      return `<div class="setup-account" data-account="${idAttr}">`
        + '<div class="setup-account-top">'
        + '<label class="setup-account-toggle">'
        + `<input type="checkbox" data-act="toggle" ${account.enabled ? 'checked' : ''}`
        + `${account.has_token ? '' : ' disabled'}>`
        + `<span>${esc(account.label)}</span></label>`
        + `<span class="setup-account-preview">${preview}</span>`
        + (own ? '<button type="button" class="setup-account-del" data-act="delete"'
          + ' title="계정 삭제">✕</button>' : '')
        + '</div>'
        + (own
          ? '<div class="setup-account-row">'
            + '<input class="setup-input setup-input-mono" type="password" data-act="token-input"'
            + ` placeholder="${account.has_token ? '저장됨 - 새 토큰을 붙여넣으면 교체됩니다' : 'NovelAI 토큰 붙여넣기'}"`
            + ' autocomplete="off" spellcheck="false">'
            + '<button type="button" class="setup-btn-primary setup-account-save"'
            + ' data-act="token-save">확인 후 저장</button>'
            + '</div>'
          : '<div class="setup-account-note">위 <b>영구 토큰</b> 칸에서 관리합니다.</div>')
        + '</div>';
    }).join('');
    const addBtn = byId('setupAccountAdd');
    if (addBtn) {
      addBtn.disabled = !state.canAdd;
      addBtn.textContent = state.canAdd ? '＋ 계정 추가' : '계정 수 상한에 도달했습니다';
    }
  }

  async function onSetupListClick(event) {
    const host = event.target.closest('[data-account]');
    if (!host) return;
    const accountId = host.getAttribute('data-account');
    const action = event.target.closest('[data-act]');
    if (!action) return;
    const act = action.getAttribute('data-act');

    if (act === 'toggle') {
      send({ type: 'nai_account_set_enabled', account_id: accountId,
             enabled: !!action.checked });
      return;
    }
    if (act === 'token-save') {
      const input = host.querySelector('[data-act="token-input"]');
      const token = input ? input.value.trim() : '';
      if (!token) {
        showToast('토큰을 먼저 붙여넣으세요.', 'error');
        return;
      }
      setSetupBusy(true);
      if (send({ type: 'nai_account_set_token', account_id: accountId, token })) {
        if (input) input.value = '';
      } else {
        setSetupBusy(false);
      }
      return;
    }
    if (act === 'delete') {
      const label = (state.accounts.find(a => a.id === accountId) || {}).label || accountId;
      const ok = await Promise.resolve(confirmDialog(
        `${label}을(를) 삭제할까요? 저장된 토큰도 함께 지워집니다.`,
        { title: '계정 삭제', okText: '삭제', cancelText: '취소' }));
      if (!ok) return;
      send({ type: 'nai_account_delete', account_id: accountId });
    }
  }

  function onAddClick() {
    if (!state.canAdd) return;
    send({ type: 'nai_account_add' });
  }

  // ---- 배선 -------------------------------------------------------------

  function bind() {
    const pill = byId('naiUsagePill');
    if (pill) {
      pill.addEventListener('click', togglePopover);
      pill.setAttribute('role', 'button');
      pill.setAttribute('tabindex', '0');
      pill.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          togglePopover();
        }
      });
    }
    const pop = popEl();
    if (pop) pop.addEventListener('click', onPopoverClick);
    document.addEventListener('pointerdown', onDocumentPointerDown, true);

    const list = byId('setupAccountsList');
    if (list) list.addEventListener('click', onSetupListClick);
    const addBtn = byId('setupAccountAdd');
    if (addBtn) addBtn.addEventListener('click', onAddClick);
  }

  bind();

  return {
    requestAccounts,
    onAccounts,
    onAccountResult,
    onUsageUpdate,
    openPopover,
    closePopover,
    togglePopover,
    renderSetupList,
  };
}
