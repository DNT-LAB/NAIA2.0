// Grok(xAI) API 연동 패널 — 제거 가능 모듈 (ima2 패턴: 번들 progrok OAuth + 관리 프록시).
//
// 사용자에겐 "Grok 로그인" 버튼 + 상태만 노출한다(프록시/URL/테스트 등 내부 잡다는 숨김).
// Electron main 이 progrok 프록시를 관리하고, naiaShell.grokLogin() 이 OAuth(브라우저) 로그인을 띄운다.
// 상태는 naiaShell.grokState()/onGrokStateChanged 로 받아 표시한다.
//
// 제거: 이 파일 + index.html grok pane + app.js grok 전역 + main/preload grok 블록 + 번들 progrok 삭제.

export function createGrokConnectPanel({document, fetch: fetchFn, showToast = () => {}}) {
  const byId = id => document.getElementById(id);
  const dot = () => byId('setupDotGrok');
  const navSub = () => byId('setupNavSubGrok');
  const statusEl = () => byId('setupGrokStatus');
  const resultEl = () => byId('setupResultGrok');
  const loginBtn = () => byId('setupBtnGrokLogin');

  const shell = () => (typeof window !== 'undefined' ? window.naiaShell : null);
  const hasOAuth = () => { const s = shell(); return !!(s && typeof s.grokLogin === 'function'); };

  function setDot(state) {
    const el = dot();
    if (!el) return;
    let cls = 'setup-nav-dot';
    if (state === 'ok') cls += ' ok';
    else if (state === 'err') cls += ' err';
    else if (state === 'warn') cls += ' warn';
    el.className = cls;
  }

  function setResult(message, type) {
    const el = resultEl();
    if (!el) return;
    const cls = (type === 'info' || type === 'warning' || type === 'error') ? type : '';
    el.className = 'setup-result ' + cls;
    el.textContent = message || '';
  }

  function setStatus(text) { const el = statusEl(); if (el) el.textContent = text || ''; }
  function setNavSub(text) { const el = navSub(); if (el) el.textContent = text || ''; }

  function setLoginLoading(loading) {
    const b = loginBtn();
    if (b) {
      b.disabled = !!loading;
      b.textContent = loading ? '로그인 중...' : 'Grok 로그인';
    }
  }

  // Electron main 의 연결 상태 → 상태줄 + 좌측 nav 서브 + dot (사용자 친화 문구, 내부 용어 숨김).
  function applyShellState(state) {
    if (!state) { setStatus('Electron 앱에서만 사용 가능'); setNavSub('사용 불가'); setDot('err'); return; }
    // 상시 활성 토글을 실제 설정에 맞춘다(서버가 SSOT - 화면이 앞서 나가면 안 된다).
    const toggle = byId('setupGrokAlwaysActive');
    if (toggle) toggle.checked = state.alwaysActive === true;
    // 꺼져 있으면 로그인 버튼을 눌러도 프록시가 안 뜬다 - 먼저 켜라고 말한다.
    const login = loginBtn();
    if (login) login.disabled = state.alwaysActive !== true;
    if (state.alwaysActive !== true) {
      setStatus('꺼져 있습니다 — 사용하려면 상시 활성을 켜세요');
      setNavSub('꺼짐');
      setDot('warn');
      return;
    }
    const map = {
      ready: ['연결됨 (로그인 완료)', '로그인됨', 'ok'],
      starting: ['연결 중…', '연결 중', 'warn'],
      auth_required: ['로그인이 필요합니다 — Grok 로그인을 눌러주세요', '로그인 필요', 'warn'],
      offline: ['연결이 끊겼습니다 — 다시 로그인하세요', '연결 끊김', 'err'],
      unavailable: ['사용할 수 없습니다', '사용 불가', 'err'],
      stopped: ['대기 중', '대기', 'warn'],
    };
    const [text, sub, tone] = map[state.proxyState] || [String(state.proxyState || ''), '', 'warn'];
    setStatus(text);
    setNavSub(sub);
    setDot(tone);
  }

  async function setAlwaysActive(enabled) {
    const s = shell();
    if (!s || typeof s.grokSetAlwaysActive !== 'function') {
      showToast('Electron 앱에서만 변경할 수 있습니다.', 'error');
      return;
    }
    try {
      applyShellState(await s.grokSetAlwaysActive(!!enabled));
      showToast(enabled ? 'Grok 상시 활성을 켰습니다.' : 'Grok 을 껐습니다.', 'success');
    } catch (error) {
      showToast('Grok 설정을 바꾸지 못했습니다.', 'error');
    }
  }

  async function refreshShellState() {
    const s = shell();
    if (!s || typeof s.grokState !== 'function') {
      setStatus('OAuth 로그인은 Electron 앱에서만 가능');
      setNavSub('사용 불가');
      setDot('err');
      return;
    }
    try { applyShellState(await s.grokState()); } catch (error) { /* 비치명 */ }
  }

  // 로그인 직후 모델 목록까지 확인해 결과줄에 "연결됨 — 모델 N개" 를 보여준다(내부 /api/grok/test).
  async function confirmConnection() {
    try {
      const r = await fetchFn('/api/grok/test', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({}),
      });
      const data = await r.json();
      if (data && data.ok) { setDot('ok'); setResult(data.message || '연결됨', 'info'); return true; }
      setDot('err');
      setResult((data && data.message) || '연결 실패', data && data.status === 'offline' ? 'warning' : 'error');
      return false;
    } catch (error) {
      setDot('err');
      setResult('연결 확인 실패: ' + error.message, 'error');
      return false;
    }
  }

  async function login() {
    if (!hasOAuth()) {
      setResult('Grok 로그인은 Electron 앱에서만 가능합니다.', 'warning');
      return;
    }
    setLoginLoading(true);
    setResult('브라우저가 열립니다 — xAI 로그인을 완료하세요…', 'info');
    try {
      const res = await shell().grokLogin();
      setLoginLoading(false);
      await refreshShellState();
      if (res && res.ok) {
        setResult('로그인 완료 — 연결 확인 중…', 'info');
        showToast('Grok 로그인 완료', 'success');
        await confirmConnection();
      } else {
        setResult((res && res.message) || '로그인 실패', 'error');
      }
    } catch (error) {
      setLoginLoading(false);
      setResult('로그인 오류: ' + error.message, 'error');
    }
  }

  // 로그아웃 = 저장된 xAI 자격증명 제거(progrok logout = ~/.progrok/auth.json 삭제) + 프록시 재기동.
  // 계정 전환용. 이후 상태는 '로그인 필요' 로 떨어진다.
  async function logout() {
    const btn = byId('setupBtnGrokLogout');
    if (btn) btn.disabled = true;
    setResult('로그아웃 중…', 'info');
    try {
      const r = await fetchFn('/api/grok/logout', {method: 'POST'});
      const data = await r.json().catch(() => ({}));
      if (!(data && data.ok)) { setResult((data && data.message) || '로그아웃 실패', 'error'); return; }
      const s = shell();
      if (s && typeof s.grokRestartProxy === 'function') { try { await s.grokRestartProxy(); } catch (error) { /* 비치명 */ } }
      await refreshShellState();
      setResult('로그아웃되었습니다 — 다른 계정으로 로그인할 수 있습니다.', 'info');
      showToast('Grok 로그아웃', 'success');
    } catch (error) {
      setResult('로그아웃 오류: ' + error.message, 'error');
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  if (hasOAuth()) {
    refreshShellState();
    try { shell().onGrokStateChanged(applyShellState); } catch (error) { /* 비치명 */ }
  } else {
    setStatus('OAuth 로그인은 Electron 앱에서만 가능');
    setNavSub('사용 불가');
  }

  return {login, logout, refreshShellState, setAlwaysActive};
}
