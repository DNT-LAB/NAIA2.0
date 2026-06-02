// Grok I2V 모달 (제거 가능) — 이미지 우클릭 → "Grok 영상(I2V)".
//
// 좌 소스 이미지 · 우 [선행/메인/후행 프롬프트 3칸] + 길이 슬라이더 + 해상도 라디오 · 하단 [생성][닫기].
// 3칸은 각각 localStorage 에 영속(재시작 후 유지). 전송 시 선행→메인→후행 순으로 합쳐 prompt 로 보냄.
// 진행률은 WS {type:'grok_i2v_state'}. 완료 시 모달 내 <video> 재생 + output/grok_videos 자동저장 → [폴더 열기].
//
// 제거: 이 파일 + resultContextMenu Grok 영상 항목 + app.js wiring + 백엔드 grok_i2v_commands/비디오 라우트.

const K_PRE = 'naia_grok_i2v_pre';
const K_MAIN = 'naia_grok_i2v_main';
const K_POST = 'naia_grok_i2v_post';
const K_DURATION = 'naia_grok_i2v_duration';
const K_RESOLUTION = 'naia_grok_i2v_resolution';

// 선행/후행 기본 템플릿 (사용자가 편집하면 그 값이 영속되어 다음부터 우선).
const PRE_DEFAULT = `Create a smooth 60fps anime animation based exactly on the reference image.

Strictly maintain the exact same art style, character design, face angle, facial expression, body pose, and worn clothing position as the reference image at all times. Perfect consistency, strong reference adherence, zero style drift.

Use only very slow and gentle movements with calm and controlled motion: subtle rhythmic swaying, soft breathing animation, minimal hip rocking, slight hair flow, light natural body movement. Keep the overall motion relaxed and elegant, avoid fast or exaggerated actions.`;

const POST_DEFAULT = `Masterpiece, best quality, ultra detailed, perfect anatomy, glossy skin, cinematic lighting, depth of field.

Avoid: fast motion, excessive movement, style change, deformed anatomy, bad hands, clothing shift, face angle change, blurry frames, low consistency, strong style drift.`;

function lsGet(key, fallback) {
  try { const value = localStorage.getItem(key); return value === null ? fallback : value; }
  catch (error) { return fallback; }
}
function lsSet(key, value) { try { localStorage.setItem(key, value); } catch (error) { /* 비치명 */ } }

function combinePrompt(pre, main, post) {
  return [pre, main, post].map((part) => String(part || '').trim()).filter(Boolean).join('\n\n');
}

export function createGrokI2vModal({
  document,
  getWs,
  WebSocket,
  showToast = () => {},
  escHtml = (value) => String(value),
  fetch: fetchFn = (...args) => window.fetch(...args),
}) {
  let overlay = null;
  let ctx = null;
  let running = false;
  let lastPrompt = '';

  function pick(selector) { return overlay ? overlay.querySelector(selector) : null; }

  // 영상 완료 후, (브라우저가 이미 디코딩한) mp4 에서 프레임을 떠 백엔드로 보내면
  // Pillow 가 애니메이션 WebP 를 만들어 이미지 히스토리에 무음 프리뷰로 넣는다. 부가기능(실패 무시).
  function seekTo(video, time) {
    return new Promise((resolve) => {
      let done = false;
      const finish = () => { if (done) return; done = true; video.removeEventListener('seeked', finish); resolve(); };
      video.addEventListener('seeked', finish);
      setTimeout(finish, 1500);
      try { video.currentTime = time; } catch (error) { finish(); }
    });
  }

  function drawPlayBadge(ctx, w, h) {
    const r = Math.max(26, Math.min(w, h) * 0.13);
    const cx = w / 2, cy = h / 2;
    ctx.save();
    ctx.fillStyle = 'rgba(0,0,0,0.5)';
    ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = 'rgba(255,255,255,0.95)';
    const t = r * 0.6;
    ctx.beginPath();
    ctx.moveTo(cx - t * 0.45, cy - t * 0.85);
    ctx.lineTo(cx - t * 0.45, cy + t * 0.85);
    ctx.lineTo(cx + t, cy);
    ctx.closePath(); ctx.fill();
    ctx.restore();
  }

  async function captureFirstFrame(src) {
    const video = document.createElement('video');
    video.muted = true; video.preload = 'auto'; video.playsInline = true;
    video.style.cssText = 'position:fixed;left:-9999px;width:2px;height:2px;opacity:0;pointer-events:none';
    video.src = src;
    document.body.appendChild(video);
    try {
      await new Promise((resolve, reject) => {
        let done = false;
        const ok = () => { if (done) return; done = true; resolve(); };
        video.addEventListener('loadeddata', ok, {once: true});
        video.addEventListener('error', () => reject(new Error('video load error')), {once: true});
        setTimeout(ok, 4000);
        video.load();
      });
      await seekTo(video, 0);
      const vw = video.videoWidth || 320;
      const vh = video.videoHeight || 240;
      const canvas = document.createElement('canvas');
      canvas.width = vw; canvas.height = vh;
      const ctx2d = canvas.getContext('2d');
      ctx2d.drawImage(video, 0, 0, vw, vh);
      drawPlayBadge(ctx2d, vw, vh); // ▶ 합성 → 영상 썸네일임을 표시
      return canvas.toDataURL('image/jpeg', 0.92);
    } finally {
      try { video.removeAttribute('src'); video.load(); video.remove(); } catch (error) { /* noop */ }
    }
  }

  async function captureThumbnail(videoId, prompt) {
    try {
      const frame = await captureFirstFrame(`/api/grok/video/${encodeURIComponent(videoId)}`);
      if (!frame) return;
      const ws = getWs();
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      ws.send(JSON.stringify({type: 'grok_animate', video_id: videoId, frames: [frame], prompt: prompt || '', label: 'Grok 영상'}));
    } catch (error) { /* 부가기능 — 무시 */ }
  }
  function currentResolution() {
    const checked = pick('input[name="grokI2vRes"]:checked');
    return checked ? checked.value : '480p';
  }

  function savePrefs() {
    if (!overlay) return;
    const pre = pick('.grok-prompt-pre');
    const main = pick('.grok-prompt-main');
    const post = pick('.grok-prompt-post');
    const dur = pick('.grok-i2v-duration');
    if (pre) lsSet(K_PRE, pre.value || '');
    if (main) lsSet(K_MAIN, main.value || '');
    if (post) lsSet(K_POST, post.value || '');
    if (dur) lsSet(K_DURATION, String(dur.value || '5'));
    lsSet(K_RESOLUTION, currentResolution());
  }

  function close() {
    if (overlay) { overlay.remove(); overlay = null; }
    ctx = null;
    running = false;
  }

  function setStatus(text, type) {
    const status = pick('.grok-i2v-status');
    if (!status) return;
    status.className = 'grok-i2i-status grok-i2v-status' + (type ? ' ' + type : '');
    status.textContent = text || '';
  }

  function setRunning(on) {
    running = !!on;
    const gen = pick('.grok-i2v-generate');
    if (gen) { gen.disabled = running; gen.textContent = running ? '생성 중…' : '생성'; }
  }

  function generate() {
    if (running || !ctx) return;
    const pre = (pick('.grok-prompt-pre') || {}).value || '';
    const main = (pick('.grok-prompt-main') || {}).value || '';
    const post = (pick('.grok-prompt-post') || {}).value || '';
    const prompt = combinePrompt(pre, main, post);
    if (!prompt) { setStatus('프롬프트를 입력하세요 (메인 프롬프트 등).', 'error'); const m = pick('.grok-prompt-main'); if (m) m.focus(); return; }
    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) { setStatus('서버에 연결되어 있지 않습니다.', 'error'); return; }
    let duration = parseInt(((pick('.grok-i2v-duration') || {}).value), 10);
    if (!Number.isFinite(duration)) duration = 5;
    duration = Math.max(1, Math.min(15, duration));
    const resolution = currentResolution();
    lastPrompt = prompt;
    savePrefs();
    setRunning(true);
    setStatus('영상 생성 중… 완료까지 창을 열어두세요 (수십 초~수 분).', 'info');
    ws.send(JSON.stringify({
      type: 'grok_i2v',
      source: ctx.source || '',
      path: ctx.path || '',
      file_path: ctx.filePath || '',
      label: ctx.label || '',
      prompt,
      duration,
      resolution,
    }));
  }

  function open(context) {
    if (!context || !context.hasImage) { showToast('영상을 만들 이미지를 찾을 수 없습니다.', 'error'); return; }
    close();
    ctx = context;
    const pre = lsGet(K_PRE, PRE_DEFAULT);
    const main = lsGet(K_MAIN, '');
    const post = lsGet(K_POST, POST_DEFAULT);
    const duration = lsGet(K_DURATION, '5');
    const resolution = lsGet(K_RESOLUTION, '480p');
    overlay = document.createElement('div');
    overlay.className = 'grok-i2i-overlay';
    overlay.innerHTML = `
      <div class="grok-i2i-dialog grok-i2v-dialog" role="dialog" aria-label="Grok I2V 영상 생성">
        <div class="grok-i2i-header">
          <span class="grok-i2i-title">GROK · 이미지 → 영상 (I2V)</span>
          <button type="button" class="grok-i2v-x grok-i2i-x" aria-label="닫기">&times;</button>
        </div>
        <div class="grok-i2i-body grok-i2v-body">
          <div class="grok-i2i-image grok-i2v-source"><img src="${escHtml(context.imageSrc || '')}" alt=""></div>
          <div class="grok-i2i-side grok-side-3">
            <label class="grok-prompt-label">선행 프롬프트</label>
            <textarea class="grok-prompt grok-prompt-pre" spellcheck="false">${escHtml(pre)}</textarea>
            <label class="grok-prompt-label">메인 프롬프트</label>
            <textarea class="grok-prompt grok-prompt-main" spellcheck="false" placeholder="여기에 핵심 지시를 입력 (예: 카메라가 천천히 줌인)">${escHtml(main)}</textarea>
            <label class="grok-prompt-label">후행 프롬프트</label>
            <textarea class="grok-prompt grok-prompt-post" spellcheck="false">${escHtml(post)}</textarea>
            <div class="grok-i2v-params">
              <div class="grok-i2v-param grok-i2v-param-dur">
                <label class="grok-i2v-param-label">길이 <span class="grok-i2v-dur-val">${escHtml(duration)}</span>초</label>
                <input type="range" class="grok-i2v-duration" min="1" max="15" step="1" value="${escHtml(duration)}">
              </div>
              <div class="grok-i2v-param">
                <label class="grok-i2v-param-label">해상도</label>
                <div class="grok-i2v-res-group" role="radiogroup">
                  <label class="grok-i2v-res-opt"><input type="radio" name="grokI2vRes" value="480p" ${resolution === '480p' ? 'checked' : ''}><span>480p</span></label>
                  <label class="grok-i2v-res-opt"><input type="radio" name="grokI2vRes" value="720p" ${resolution === '720p' ? 'checked' : ''}><span>720p</span></label>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div class="grok-i2i-actions grok-i2v-actions">
          <button type="button" class="grok-i2i-generate grok-i2v-generate">생성</button>
          <button type="button" class="grok-i2i-cancel grok-i2v-cancel">닫기</button>
        </div>
        <div class="grok-i2i-status grok-i2v-status"></div>
      </div>`;
    overlay.addEventListener('click', (event) => { if (event.target === overlay) close(); });
    pick('.grok-i2v-x').addEventListener('click', close);
    pick('.grok-i2v-cancel').addEventListener('click', close);
    pick('.grok-i2v-generate').addEventListener('click', generate);
    overlay.querySelectorAll('.grok-prompt').forEach((field) => field.addEventListener('input', savePrefs));
    const dur = pick('.grok-i2v-duration');
    const durVal = pick('.grok-i2v-dur-val');
    if (dur) dur.addEventListener('input', () => { if (durVal) durVal.textContent = dur.value; savePrefs(); });
    overlay.querySelectorAll('input[name="grokI2vRes"]').forEach((radio) => radio.addEventListener('change', savePrefs));
    document.body.appendChild(overlay);
    setTimeout(() => { const m = pick('.grok-prompt-main'); if (m) m.focus(); }, 0);
  }

  function openFolder() {
    fetchFn('/api/grok/videos/open', {method: 'POST'}).catch(() => {});
  }

  function showVideo(videoId, savedName) {
    const body = pick('.grok-i2v-body');
    const actions = pick('.grok-i2v-actions');
    const id = encodeURIComponent(videoId);
    if (body) {
      body.className = 'grok-i2i-body grok-i2v-body grok-i2v-done';
      body.innerHTML = `<div class="grok-i2v-player"><video src="/api/grok/video/${id}" controls autoplay loop playsinline controlslist="nodownload noremoteplayback" disablepictureinpicture></video></div>`;
    }
    if (actions) {
      actions.innerHTML = `
        <button type="button" class="grok-i2i-generate grok-i2v-openfolder">폴더 열기</button>
        <button type="button" class="grok-i2i-cancel grok-i2v-cancel">닫기</button>`;
      const folderBtn = actions.querySelector('.grok-i2v-openfolder');
      if (folderBtn) folderBtn.addEventListener('click', openFolder);
      const cancel = actions.querySelector('.grok-i2v-cancel');
      if (cancel) cancel.addEventListener('click', close);
    }
    setStatus(savedName ? `✓ 저장됨: ${savedName}` : '완료 (자동 저장 실패 — 폴더 열기로 확인)', 'info');
  }

  function onState(msg) {
    if (!overlay || !msg) return;
    if (msg.running) {
      setRunning(true);
      let pct = '';
      if (typeof msg.progress === 'number') {
        const value = msg.progress <= 1 ? msg.progress * 100 : msg.progress;
        pct = ` (${Math.round(value)}%)`;
      }
      setStatus((msg.message || '생성 중…') + pct, 'info');
      return;
    }
    setRunning(false);
    if (msg.success && msg.video_id) {
      showVideo(msg.video_id, msg.saved_name || '');
      showToast('Grok 영상 저장 완료', 'success');
      captureThumbnail(msg.video_id, lastPrompt); // 비동기: 히스토리에 선명한 정지썸네일(+▶) 추가
    } else {
      setStatus(msg.message || '생성 실패', 'error');
    }
  }

  return {open, close, onState};
}
