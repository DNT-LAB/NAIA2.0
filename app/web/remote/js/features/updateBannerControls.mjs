// App auto-update banner (Electron shell only). Drives the setup-modal
// "앱 업데이트" section from window.naiaShell shell-state: check for a newer
// GitHub release, download + verify it, and apply on restart. The Electron main
// process owns the actual download/verify/swap; this module is the UI surface.
//
// In a plain browser session (no naiaShell) the section stays hidden — auto-update
// is a packaged-desktop concern only.

export function createUpdateBanner({document, showToast, confirmDialog}) {
  const toast = (msg, kind) => {
    if (typeof showToast === 'function') showToast(msg, kind);
    else if (typeof globalThis.showToast === 'function') globalThis.showToast(msg, kind);
  };
  const confirm = async (msg, opts) => {
    if (typeof confirmDialog === 'function') return confirmDialog(msg, opts);
    return Promise.resolve(globalThis.confirm ? globalThis.confirm(msg) : true);
  };
  const byId = id => document.getElementById(id);
  const shell = () => globalThis.naiaShell || null;
  let lastNotifiedVersion = '';
  let busy = false;

  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function setStatus(text) {
    const el = byId('setupUpdateStatus');
    if (el) el.textContent = text || '';
  }

  function setSub(html) {
    const el = byId('setupUpdateSub');
    if (!el) return;
    el.innerHTML = html || '';
  }

  function setResult(message, kind) {
    const el = byId('setupUpdateResult');
    if (!el) return;
    if (!message) {
      el.classList.add('hidden');
      el.textContent = '';
      return;
    }
    el.classList.remove('hidden');
    el.textContent = message;
    el.className = 'setup-result' + (kind ? ` ${kind}` : '');
  }

  function show(id, visible) {
    const el = byId(id);
    if (el) el.classList.toggle('hidden', !visible);
  }

  function setProgress(percent, text) {
    const wrap = byId('setupUpdateProgress');
    const fill = byId('setupUpdateProgressFill');
    const label = byId('setupUpdateProgressText');
    if (wrap) wrap.classList.toggle('hidden', percent == null);
    if (percent != null) {
      if (fill) fill.style.width = `${Math.max(0, Math.min(100, percent))}%`;
      if (label) label.textContent = text || `${percent}%`;
    }
  }

  function notesSnippet(notes) {
    const text = String(notes || '').trim();
    return text ? text.split(/\r?\n/).slice(0, 3).join(' ').slice(0, 220) : '';
  }

  function render(update, appVersion) {
    const section = byId('setupUpdateSection');
    if (!section) return;
    section.classList.remove('hidden'); // Electron: surface the section.
    const u = update || {};
    const phase = u.phase || 'idle';
    const current = u.currentVersion || appVersion || '';
    const latest = u.latestVersion || '';

    // Reset transient affordances; each phase opts back in.
    show('setupUpdateRelease', false);
    show('setupUpdateDownload', false);
    show('setupUpdateInstall', false);
    setProgress(null);
    const recheck = byId('setupUpdateRecheck');
    if (recheck) recheck.disabled = (phase === 'checking' || phase === 'downloading');

    if (phase === 'checking' || phase === 'idle') {
      setStatus('확인 중…');
      setSub('최신 버전을 확인하는 중입니다.');
      setResult('');
      return;
    }
    if (phase === 'error') {
      setStatus('확인 실패');
      setSub(current ? `현재 버전 v${esc(current)}.` : '');
      setResult(u.error || '업데이트 확인에 실패했습니다.', 'error');
      show('setupUpdateRelease', true);
      if (latest && compareNewer(latest, current)) show('setupUpdateDownload', true);
      return;
    }
    if (phase === 'up-to-date') {
      setStatus(current ? `최신 버전 · v${esc(current)}` : '최신 버전');
      setSub('설치된 버전이 최신입니다.');
      setResult('');
      return;
    }
    if (phase === 'available') {
      setStatus(`업데이트 가능 · v${esc(latest)}`);
      const snippet = notesSnippet(u.releaseNotes);
      setSub(`현재 v${esc(current)} → 최신 <strong>v${esc(latest)}</strong>${snippet ? ` — ${esc(snippet)}` : ''}`);
      setResult('');
      show('setupUpdateDownload', true);
      show('setupUpdateRelease', true);
      if (latest && latest !== lastNotifiedVersion) {
        lastNotifiedVersion = latest;
        toast(`새 버전 v${latest} 사용 가능`, 'info');
      }
      return;
    }
    if (phase === 'downloading') {
      setStatus(`다운로드 중 · v${esc(latest)}`);
      setSub('업데이트를 내려받고 무결성을 검증합니다.');
      setResult('');
      setProgress(Number(u.downloadPercent) || 0, `${Number(u.downloadPercent) || 0}%`);
      return;
    }
    if (phase === 'downloaded') {
      setStatus(`설치 준비 완료 · v${esc(latest)}`);
      setSub('다운로드와 체크섬 검증이 끝났습니다. 설치하면 앱이 종료된 뒤 새 버전으로 다시 시작됩니다.');
      setResult('검증 완료 — 데이터는 그대로 보존됩니다.', 'success');
      show('setupUpdateInstall', true);
      return;
    }
    setStatus(phase);
  }

  // Local mirror of the main-process compare (used only to decide whether a
  // failed-check still has a known newer tag worth offering a manual download).
  function compareNewer(a, b) {
    const parts = (v) => String(v || '').replace(/^v/i, '').split(/[-+]/)[0].split('.').map(n => parseInt(n, 10) || 0);
    const pa = parts(a), pb = parts(b);
    for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
      if ((pa[i] || 0) > (pb[i] || 0)) return true;
      if ((pa[i] || 0) < (pb[i] || 0)) return false;
    }
    return false;
  }

  async function recheck() {
    const s = shell();
    if (!s || typeof s.checkUpdate !== 'function' || busy) return;
    busy = true;
    setStatus('확인 중…');
    try {
      const state = await s.checkUpdate();
      render(state, state && state.currentVersion);
    } catch (err) {
      setResult(`확인 실패: ${err}`, 'error');
    } finally {
      busy = false;
    }
  }

  async function download() {
    const s = shell();
    if (!s || typeof s.downloadUpdate !== 'function' || busy) return;
    busy = true;
    setStatus('다운로드 중…');
    setProgress(0, '0%');
    try {
      const state = await s.downloadUpdate();
      render(state, state && state.currentVersion);
      if (state && state.phase === 'error') toast(state.error || '다운로드 실패', 'error');
    } catch (err) {
      setResult(`다운로드 실패: ${err}`, 'error');
      toast(`다운로드 실패: ${err}`, 'error');
    } finally {
      busy = false;
    }
  }

  async function install() {
    const s = shell();
    if (!s || typeof s.applyUpdate !== 'function' || busy) return;
    const ok = await confirm(
      '업데이트를 설치하면 앱이 종료된 뒤 새 버전으로 다시 시작됩니다. 저장된 데이터(설정·프리셋·이미지)는 그대로 보존됩니다. 계속할까요?',
      {confirmText: '설치하고 재시작', cancelText: '취소'},
    );
    if (!ok) return;
    busy = true;
    setStatus('적용 중…');
    setSub('앱을 종료하고 업데이트를 적용합니다. 잠시 후 자동으로 다시 시작됩니다.');
    setResult('', '');
    try {
      const res = await s.applyUpdate();
      if (res && res.phase === 'error') {
        render(res, res.currentVersion);
        toast(res.error || '업데이트 적용 실패', 'error');
        busy = false;
      }
      // On success the app is quitting; no further UI update needed.
    } catch (err) {
      setResult(`적용 실패: ${err}`, 'error');
      toast(`적용 실패: ${err}`, 'error');
      busy = false;
    }
  }

  function openReleasePage() {
    const s = shell();
    if (s && typeof s.openReleasePage === 'function') s.openReleasePage();
  }

  function init() {
    const s = shell();
    if (!s) return; // Plain browser session — keep the section hidden.
    const releaseBtn = byId('setupUpdateRelease');
    if (releaseBtn) releaseBtn.addEventListener('click', openReleasePage);
    const recheckBtn = byId('setupUpdateRecheck');
    if (recheckBtn) recheckBtn.addEventListener('click', recheck);
    const downloadBtn = byId('setupUpdateDownload');
    if (downloadBtn) downloadBtn.addEventListener('click', download);
    const installBtn = byId('setupUpdateInstall');
    if (installBtn) installBtn.addEventListener('click', install);
    if (typeof s.onStateChanged === 'function') {
      s.onStateChanged(state => {
        if (state && state.update) render(state.update, state.appVersion);
      });
    }
    // Prime current state, then kick off a fresh check.
    if (typeof s.getState === 'function') {
      Promise.resolve(s.getState())
        .then(state => { if (state) render(state.update, state.appVersion); })
        .catch(() => {});
    }
    recheck();
  }

  return {init, render, openReleasePage, download, install};
}
