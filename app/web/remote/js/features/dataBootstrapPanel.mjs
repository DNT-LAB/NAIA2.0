// Owns the "태그 데이터" section inside the Setup overlay.
//
// New installs need the multi-GB Hugging Face tag corpus before search/
// autocomplete work properly. This panel checks ``/api/install-manager`` and
// surfaces two paths so users do not have to learn about the migration flow
// just to skip a heavy download:
//
//   1. ``허깅페이스에서 다운로드`` — POSTs to ``/api/install-manager/tag-archive/download``
//      and polls the snapshot for progress.
//   2. ``NAIA2.0에서 가져오기`` — delegates to the existing data migration
//      popup (which now exposes a ``data/tags`` bucket).

const POLL_MS = 750;

export function createDataBootstrapPanel({
  document,
  fetch: fetchFn = window.fetch.bind(window),
  showToast = () => {},
  onOpenMigration = () => {},
}) {
  const section = document.getElementById('setupDataBootstrapSection');
  if (!section) {
    return {init() {}, refresh() {}, openMigration: onOpenMigration};
  }

  const elStatus = section.querySelector('[data-bootstrap-status]');
  const elSub = section.querySelector('[data-bootstrap-sub]');
  const elActions = section.querySelector('[data-bootstrap-actions]');
  const elProgress = section.querySelector('[data-bootstrap-progress]');
  const elProgressFill = section.querySelector('[data-bootstrap-progress-fill]');
  const elProgressText = section.querySelector('[data-bootstrap-progress-text]');
  const elResult = section.querySelector('[data-bootstrap-result]');

  const btnDownload = section.querySelector('[data-bootstrap-download]');
  const btnMigrate = section.querySelector('[data-bootstrap-migrate]');
  const btnCancel = section.querySelector('[data-bootstrap-cancel]');

  let pollTimer = 0;
  let lastState = null;

  function setResult(message, kind) {
    if (!elResult) return;
    elResult.textContent = message || '';
    elResult.className = 'setup-result' + (kind ? ` ${kind}` : '');
  }

  function setProgress(active, percent, downloadedMb, totalMb, message) {
    if (!elProgress) return;
    if (!active) {
      elProgress.classList.add('hidden');
      return;
    }
    elProgress.classList.remove('hidden');
    if (elProgressFill) elProgressFill.style.width = `${Math.max(0, Math.min(100, percent || 0))}%`;
    if (elProgressText) {
      const sizeStr = totalMb ? `${downloadedMb.toFixed(1)} / ${totalMb.toFixed(1)} MB` : `${downloadedMb.toFixed(1)} MB`;
      elProgressText.textContent = `${message || '다운로드 중'} · ${sizeStr}`;
    }
  }

  function render(state) {
    lastState = state || {};
    const archive = (state && state.tag_archive) || {};
    const download = archive.download || {};
    const ready = !!archive.ready;
    const downloadable = !!archive.downloadable;
    const active = !!download.active;
    const fileCount = Number(archive.file_count || 0);
    const expectedCount = Number(archive.expected_count || 0);
    const missing = Math.max(0, Number(archive.missing_count || 0));

    if (elStatus) {
      if (ready) elStatus.textContent = `설치 완료 (${fileCount}개)`;
      else if (active) elStatus.textContent = '다운로드 중…';
      else if (fileCount > 0) elStatus.textContent = `부분 설치 (${fileCount} / ${expectedCount || '?'})`;
      else elStatus.textContent = '미설치';
    }
    if (elSub) {
      elSub.textContent = ready
        ? `태그 데이터가 준비되어 있습니다 (${fileCount}개 파일).`
        : `검색·자동완성에 필요한 태그 데이터입니다. 허깅페이스에서 새로 받거나, 이전 NAIA2.0 설치에서 그대로 가져올 수 있습니다 (약 ${expectedCount || 150}개 파일, ~1.4 GB).`;
    }
    if (elActions) elActions.classList.toggle('hidden', ready);

    if (btnDownload) {
      btnDownload.classList.toggle('hidden', ready || active);
      btnDownload.disabled = !downloadable;
    }
    if (btnMigrate) btnMigrate.classList.toggle('hidden', ready);
    if (btnCancel) btnCancel.classList.toggle('hidden', !active);

    setProgress(
      active,
      Number(download.percent || 0),
      Number(download.downloaded_mb || 0),
      Number(download.total_mb || 0),
      download.message || '',
    );

    if (download.error) setResult(download.error, 'error');
    else if (download.done && ready) setResult('태그 데이터 다운로드가 완료되었습니다.', 'success');
    else if (active) setResult('', '');
    else if (ready) setResult('', 'success');
    else if (missing > 0) setResult(`${missing}개 파일이 누락되어 있습니다.`, 'warning');
    else setResult('', '');
  }

  async function refresh() {
    try {
      const res = await fetchFn('/api/install-manager', {cache: 'no-store'});
      const data = await res.json();
      render(data);
      // If a download is already in flight when this panel mounts or is
      // re-opened, attach the polling loop so the user sees live progress.
      // Without this the UI would render once with the active payload then
      // never refresh until the user clicks something.
      const downloadActive = !!(data && data.tag_archive && data.tag_archive.download && data.tag_archive.download.active);
      if (downloadActive && !pollTimer) startPolling();
      return data;
    } catch (err) {
      console.warn('install-manager refresh failed', err);
      return null;
    }
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = 0;
    }
  }

  function startPolling() {
    stopPolling();
    pollTimer = setInterval(async () => {
      const data = await refresh();
      const archive = data && data.tag_archive;
      const download = (archive && archive.download) || {};
      if (!download.active) stopPolling();
    }, POLL_MS);
  }

  async function downloadTags() {
    if (lastState && lastState.tag_archive && lastState.tag_archive.ready) return;
    setResult('태그 데이터 다운로드를 시작합니다…', '');
    try {
      const res = await fetchFn('/api/install-manager/tag-archive/download', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: '{}',
      });
      const data = await res.json();
      if (!res.ok || (data && data.ok === false)) {
        setResult(data?.error || '태그 데이터 다운로드 시작에 실패했습니다.', 'error');
        showToast('태그 데이터 다운로드 실패', 'error');
        return;
      }
      render({tag_archive: data});
      startPolling();
    } catch (err) {
      setResult(`다운로드 실패: ${err?.message || err}`, 'error');
      showToast('태그 데이터 다운로드 실패', 'error');
    }
  }

  async function cancelDownload() {
    try {
      const res = await fetchFn('/api/install-manager/tag-archive/download/cancel', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: '{}',
      });
      const data = await res.json();
      render({tag_archive: data});
    } catch (err) {
      showToast(`다운로드 취소 실패: ${err?.message || err}`, 'error');
    }
  }

  function openMigration() {
    onOpenMigration();
  }

  function init() {
    if (btnDownload) btnDownload.addEventListener('click', downloadTags);
    if (btnMigrate) btnMigrate.addEventListener('click', openMigration);
    if (btnCancel) btnCancel.addEventListener('click', cancelDownload);
    refresh();
  }

  return {init, refresh, openMigration};
}
