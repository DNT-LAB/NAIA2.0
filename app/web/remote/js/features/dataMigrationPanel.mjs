// Import a previous NAIA install's user data into the current data folder.
// Picks a folder (Electron native dialog when available, else a path prompt),
// previews per-bucket counts via /api/data-migration/preview, then copies via
// /api/data-migration/import. Non-destructive: the backend only ever copies.

export function createDataMigrationPanel({document, showToast}) {
  const toast = (msg, kind) => {
    if (typeof showToast === 'function') showToast(msg, kind);
    else if (typeof globalThis.showToast === 'function') globalThis.showToast(msg, kind);
  };
  const byId = id => document.getElementById(id);
  let currentSource = '';
  let busy = false;

  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function fmtBytes(n) {
    const bytes = Number(n) || 0;
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1073741824) return `${(bytes / 1048576).toFixed(1)} MB`;
    return `${(bytes / 1073741824).toFixed(2)} GB`;
  }

  async function pickFolder() {
    const shell = globalThis.naiaShell;
    if (shell && typeof shell.pickDirectory === 'function') {
      try {
        return await shell.pickDirectory();
      } catch {
        return null;
      }
    }
    // Browser fallback: ask for an absolute path.
    const entered = globalThis.prompt?.('이전 NAIA 폴더의 전체 경로를 입력하세요 (예: C:\\NAIA_future01)');
    return entered ? String(entered).trim() : null;
  }

  function setResult(message, kind) {
    const el = byId('setupMigrationResult');
    if (!el) return;
    el.textContent = message || '';
    el.className = 'setup-result' + (kind ? ` ${kind}` : '');
  }

  function renderPreview(preview) {
    const body = byId('setupMigrationBody');
    if (!body) return;
    if (!preview || preview.error) {
      body.classList.add('hidden');
      body.innerHTML = '';
      setResult(preview?.error || '미리보기에 실패했습니다.', 'error');
      return;
    }
    const buckets = Array.isArray(preview.buckets) ? preview.buckets : [];
    const present = buckets.filter(b => b.present && b.file_count > 0);
    if (!preview.plausible || present.length === 0) {
      body.classList.add('hidden');
      body.innerHTML = '';
      setResult('선택한 폴더에서 가져올 NAIA 데이터를 찾지 못했습니다.', 'error');
      return;
    }
    const rows = present.map(b => `
      <label class="setup-meta-line" style="cursor:pointer;gap:8px">
        <span style="display:flex;align-items:center;gap:6px">
          <input type="checkbox" class="cond-mig-bucket" data-bucket="${esc(b.bucket)}" checked>
          ${esc(b.label)} <span class="setup-meta-val">(${b.file_count}개 · ${fmtBytes(b.total_bytes)})</span>
        </span>
        <span class="setup-meta-val">${b.conflict_count > 0 ? `중복 ${b.conflict_count}` : '신규'}</span>
      </label>`).join('');
    const credNote = preview.credentials?.present
      ? `<p class="setup-sub" style="color:var(--text-dim)">⚠ ${esc(preview.credentials.note)}</p>`
      : '';
    body.innerHTML = `
      <div class="setup-meta-line"><span>가져올 위치</span><span class="setup-meta-val" title="${esc(preview.source)}">${esc(preview.source)}</span></div>
      <div class="setup-meta-line"><span>대상</span><span class="setup-meta-val" title="${esc(preview.user_root)}">${esc(preview.user_root)}</span></div>
      ${rows}
      ${credNote}
      <label class="setup-meta-line" style="gap:8px"><span>중복 파일</span>
        <select id="setupMigrationConflict" class="setup-meta-val">
          <option value="skip" selected>기존 유지 (건너뛰기)</option>
          <option value="overwrite">덮어쓰기</option>
        </select>
      </label>
      <div class="setup-cloudflared-actions">
        <button class="setup-btn-primary" id="setupMigrationRun" type="button">가져오기 실행</button>
      </div>`;
    body.classList.remove('hidden');
    setResult('가져올 항목을 확인하고 "가져오기 실행"을 누르세요.', '');
    const runBtn = byId('setupMigrationRun');
    if (runBtn) runBtn.addEventListener('click', runImport);
  }

  async function open() {
    if (busy) return;
    const folder = await pickFolder();
    if (!folder) return;
    currentSource = folder;
    busy = true;
    setResult('미리보기 중…', '');
    try {
      const res = await fetch('/api/data-migration/preview', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({source: folder}),
      });
      const data = await res.json();
      renderPreview(data);
    } catch (err) {
      setResult(`미리보기 실패: ${err}`, 'error');
    } finally {
      busy = false;
    }
  }

  async function runImport() {
    if (busy || !currentSource) return;
    const include = Array.from(document.querySelectorAll('.cond-mig-bucket'))
      .filter(el => el.checked)
      .map(el => el.dataset.bucket);
    if (include.length === 0) {
      setResult('가져올 항목을 하나 이상 선택하세요.', 'error');
      return;
    }
    const conflict = byId('setupMigrationConflict')?.value || 'skip';
    busy = true;
    const runBtn = byId('setupMigrationRun');
    if (runBtn) { runBtn.disabled = true; runBtn.textContent = '가져오는 중…'; }
    setResult('데이터를 가져오는 중…', '');
    try {
      const res = await fetch('/api/data-migration/import', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({source: currentSource, conflict, include}),
      });
      const data = await res.json();
      if (!data.ok) {
        setResult(data.error || '가져오기에 실패했습니다.', 'error');
        toast(data.error || '가져오기 실패', 'error');
        return;
      }
      const parts = [`${data.total_files}개 파일 복사`];
      if (data.skipped_existing) parts.push(`${data.skipped_existing}개 건너뜀`);
      if (data.overwritten) parts.push(`${data.overwritten}개 덮어씀`);
      const msg = `가져오기 완료 — ${parts.join(' · ')}. 변경 사항은 재시작 후 적용됩니다.`;
      setResult(msg, 'success');
      toast(msg, 'success');
    } catch (err) {
      setResult(`가져오기 실패: ${err}`, 'error');
      toast(`가져오기 실패: ${err}`, 'error');
    } finally {
      busy = false;
      if (runBtn) { runBtn.disabled = false; runBtn.textContent = '가져오기 실행'; }
    }
  }

  function openDataFolder() {
    const shell = globalThis.naiaShell;
    if (shell && typeof shell.openDataFolder === 'function') {
      shell.openDataFolder();
    } else {
      toast('데이터 폴더 열기는 데스크톱 앱에서만 지원됩니다.', 'info');
    }
  }

  return {open, openDataFolder};
}
