// Wires the standalone first-run migration page (bootstrap.html). Reuses the
// real dataMigrationPanel so behavior matches the in-app Setup migration: pick
// a previous install, preview buckets, import, then the run button becomes the
// red "NAIA 재시작" which restarts the backend and lets the install gate finish
// — at which point the Electron shell loads the real app in an expanded window.
import { createDataMigrationPanel } from './dataMigrationPanel.mjs?v=20260606-migration7';

const toastEl = document.getElementById('bootstrapToast');

function showToast(message, kind) {
  if (!toastEl) return;
  toastEl.textContent = message || '';
  toastEl.style.color = kind === 'error'
    ? '#f0a0a0'
    : kind === 'success'
      ? '#9ad0a0'
      : '';
}

const skipBtn = document.getElementById('bootstrapSkipToDownload');
let importCompleted = false;

function retireEscapeHatch() {
  // Once a copy is committed, the only valid next step is the clean restart.
  // Switching to the Hugging Face download would clear the migration handshake
  // and load the app WITHOUT restarting, leaving copied state half-applied — so
  // remove the escape entirely. Retired at import *start* (not just completion)
  // so it cannot be clicked mid-copy of a large bucket like data/tags.
  importCompleted = true;
  if (skipBtn) skipBtn.remove();
}

const panel = createDataMigrationPanel({
  document,
  showToast,
  onImportStarted: retireEscapeHatch,
  onImported: retireEscapeHatch,
});

const pickBtn = document.getElementById('setupMigrationPick');
if (pickBtn) pickBtn.addEventListener('click', () => panel.open());

const openFolderBtn = document.getElementById('setupMigrationOpenFolder');
if (openFolderBtn) openFolderBtn.addEventListener('click', () => panel.openDataFolder());

// Escape hatch: the user picked "import" but has no previous install — let them
// switch to the Hugging Face download without relaunching. The shell clears the
// migration handshake and shows download progress back in the maintenance view.
// Only available BEFORE an import completes (see retireEscapeHatch).
if (skipBtn) {
  skipBtn.addEventListener('click', async () => {
    if (importCompleted) return;  // defensive: button is removed on import, but never bypass the restart
    const shell = globalThis.naiaShell;
    if (!shell || typeof shell.startTagDownload !== 'function') {
      showToast('다운로드는 데스크톱 앱에서만 가능합니다.', 'info');
      return;
    }
    skipBtn.disabled = true;
    showToast('태그 데이터 다운로드로 전환합니다…', '');
    try {
      const result = await shell.startTagDownload();
      if (result && result.ok === false) {
        showToast(`다운로드 시작 실패: ${result.error || ''}`, 'error');
        skipBtn.disabled = false;
      }
    } catch (error) {
      showToast(`다운로드 시작 실패: ${error?.message || error}`, 'error');
      skipBtn.disabled = false;
    }
  });
}
