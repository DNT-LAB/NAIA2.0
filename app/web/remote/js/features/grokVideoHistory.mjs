// Grok 영상 히스토리 클릭→재생 (제거 가능, grok 전용 — 결과 뷰어 코드 무수정).
//
// 백엔드가 영상 첫 프레임(+▶)을 일반 이미지 결과로 히스토리에 넣고, grok_video_registered 로
// rel_path↔video_id 를 알려준다. 이 모듈은 그 썸네일 클릭을 capture 단계에서 가로채(=기존
// 이미지 라이트박스보다 먼저) 실제 mp4 를 <video> 로 재생한다. 등록 안 된 썸네일은 그대로 둔다.
//
// 제거: 이 파일 + app.js 의 grokVideoHistory 배선 + WS grok_video_registered 항목 삭제.

export function createGrokVideoHistory({document, fetch: fetchFn = (...args) => window.fetch(...args)}) {
  const map = new Map(); // rel_path -> video_id
  let overlay = null;

  function register(relPath, videoId) {
    if (!relPath || !videoId) return;
    map.set(String(relPath), String(videoId));
  }

  function closePlayer() {
    if (overlay) { overlay.remove(); overlay = null; }
  }

  function openFolder() {
    fetchFn('/api/grok/videos/open', {method: 'POST'}).catch(() => {});
  }

  function play(videoId) {
    closePlayer();
    const id = encodeURIComponent(String(videoId));
    overlay = document.createElement('div');
    overlay.className = 'grok-i2i-overlay grok-vplay-overlay';
    // controlslist=nodownload + disablepictureinpicture: Electron 에서 동작 안 하는 네이티브
    // 다운로드/PIP 메뉴 제거. 영상은 이미 output/grok_videos 에 자동저장돼 있으니 [폴더 열기] 제공.
    overlay.innerHTML = `
      <div class="grok-vplay-dialog" role="dialog" aria-label="Grok 영상 재생">
        <button type="button" class="grok-vplay-close" aria-label="닫기">&times;</button>
        <video src="/api/grok/video/${id}" controls autoplay loop playsinline controlslist="nodownload noremoteplayback" disablepictureinpicture></video>
        <div class="grok-vplay-actions">
          <button type="button" class="grok-vplay-folder">저장 폴더 열기</button>
        </div>
      </div>`;
    overlay.addEventListener('click', (event) => { if (event.target === overlay) closePlayer(); });
    const closeBtn = overlay.querySelector('.grok-vplay-close');
    if (closeBtn) closeBtn.addEventListener('click', closePlayer);
    const folderBtn = overlay.querySelector('.grok-vplay-folder');
    if (folderBtn) folderBtn.addEventListener('click', openFolder);
    document.body.appendChild(overlay);
  }

  function onClickCapture(event) {
    const target = event.target;
    if (!target || typeof target.closest !== 'function') return;
    const thumb = target.closest('.viewer-thumb[data-path]');
    if (!thumb) return;
    const videoId = map.get(String(thumb.dataset.path || ''));
    if (!videoId) return;
    // capture 단계에서 stopPropagation → 기존 thumbClick(이미지 라이트박스)보다 먼저 가로챔.
    event.stopPropagation();
    event.preventDefault();
    play(videoId);
  }

  function bind() {
    document.addEventListener('click', onClickCapture, true);
    document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closePlayer(); });
  }

  return {register, play, bind, closePlayer};
}
