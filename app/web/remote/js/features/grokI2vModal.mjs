// Grok I2V 모달 (제거 가능) — 이미지 우클릭 → "Grok 영상(I2V)".
//
// 좌 소스 이미지 · 우 [선행/메인/후행 프롬프트 3칸] + 길이 슬라이더 + 해상도 라디오 · 하단 [생성][닫기].
// 진행률은 WS {type:'grok_i2v_state', job_id}. 완료 시 모달 내 <video>(autoplay 없음) + output/grok_videos 자동저장.
//
// 다중 인스턴스: 생성마다 독립 인스턴스(고유 job_id) 를 만들고, 생성 시 자동 최소화 → 상단 우측에 pill 로
// 세로 스택(ID1/ID2/ID3). 각 pill 클릭 → 해당 인스턴스 모달 펼침. WS 상태는 job_id 로 해당 인스턴스에 라우팅.
// 동시 생성은 UI 한계상 최대 3개(초과 시 빨간 토스트). 생성 중 닫기/외부클릭/× 는 '최소화'(결과 유실 방지),
// 완료/미생성 시에만 실제 닫음.
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

const MAX_INSTANCES = 3;

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
  const instances = new Map(); // jobId -> instance
  let seq = 0;

  function pctFromProgress(p) {
    if (typeof p !== 'number') return null;
    const v = p <= 1 ? p * 100 : p;
    return Math.max(0, Math.min(100, Math.round(v)));
  }

  // ── 영상 첫 프레임(+▶) 캡처 → grok_animate 로 히스토리 정지썸네일 주입 (인스턴스 무관, 부가기능) ──
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
      drawPlayBadge(ctx2d, vw, vh);
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

  // Chromium 은 재생 중 <video> 를 DOM 에서 제거만 하면 미디어 세션이 남아 오디오가 계속 들린다.
  function stopVideos(root) {
    if (!root || !root.querySelectorAll) return;
    root.querySelectorAll('video').forEach((v) => {
      try { v.pause(); v.removeAttribute('src'); v.load(); } catch (error) { /* noop */ }
    });
  }

  // 상단 우측 pill 세로 스택 재배치 + ID 번호(스택 위치).
  function restackPills() {
    let i = 0;
    instances.forEach((inst) => {
      if (!inst.pill) return;
      inst.pill.style.top = `${10 + i * 42}px`;
      const idEl = inst.pill.querySelector('.grok-i2v-pill-id');
      if (idEl) idEl.textContent = `ID${i + 1}`;
      i += 1;
    });
  }

  function createInstance(context) {
    const jobId = `i2v-${++seq}`;
    const inst = { jobId, overlay: null, running: false, minimized: false, done: false, failed: false, pill: null, lastPillText: '생성 중…', lastPrompt: '', ctx: context };
    instances.set(jobId, inst);

    const pick = (sel) => (inst.overlay ? inst.overlay.querySelector(sel) : null);

    function removePill() {
      if (inst.pill) { try { inst.pill.remove(); } catch (error) { /* noop */ } inst.pill = null; }
      restackPills();
    }
    function setPill(text, done) {
      if (!inst.minimized) return;
      if (!inst.pill) {
        inst.pill = document.createElement('button');
        inst.pill.type = 'button';
        inst.pill.className = 'grok-i2v-pill';
        inst.pill.innerHTML = '<span class="grok-i2v-pill-id"></span><span class="grok-i2v-pill-ico">🎬</span><span class="grok-i2v-pill-txt"></span>';
        inst.pill.addEventListener('click', restore);
        document.body.appendChild(inst.pill);
        restackPills();
      }
      inst.pill.classList.toggle('done', !!done);
      const txt = inst.pill.querySelector('.grok-i2v-pill-txt');
      if (txt) txt.textContent = text;
    }
    function pillState() {
      if (inst.running) return { text: inst.lastPillText, done: false };
      if (inst.done) return inst.failed ? { text: '✕ 실패 (클릭하여 보기)', done: true } : { text: '✓ 완료! (클릭하여 보기)', done: true };
      return { text: '설정 (클릭하여 열기)', done: false };  // 아직 미생성 config
    }
    function minimizeBack(silent) {
      if (!inst.overlay) return;
      inst.minimized = true;
      inst.overlay.style.display = 'none';
      const s = pillState();
      setPill(s.text, s.done);
      if (!silent && inst.running) showToast('오른쪽 상단에서 진행도를 확인하세요 →', 'info');
    }
    inst.minimizeBack = minimizeBack;
    // 한 번에 하나의 모달만 표시 — 대상 외 표시 중 인스턴스는 모두 pill 로 되돌려 오버레이 중첩 방지.
    function minimizeOthers() {
      instances.forEach((other) => { if (other !== inst && other.overlay && !other.minimized) other.minimizeBack(true); });
    }
    function restore() {
      minimizeOthers();  // 다른 결과창이 떠 있으면 먼저 pill 로 → 중첩 방지(보고있던 창 닫기)
      inst.minimized = false;
      removePill();
      if (inst.overlay) inst.overlay.style.display = '';
    }
    // 생성 중에는 닫기/외부클릭/× 가 모두 '최소화'(진짜 close 하면 오버레이 소멸 → 완료 시 onState
    // early-return → showVideo/captureThumbnail 미실행 → 히스토리 누락). 완료/미생성 시에만 실제 닫음.
    function closeOrMinimize() {
      if (inst.running) { if (!inst.minimized) minimizeBack(false); return; }
      close();
    }
    function close() {
      if (inst.overlay) { stopVideos(inst.overlay); inst.overlay.remove(); inst.overlay = null; }
      if (inst.pill) { try { inst.pill.remove(); } catch (error) { /* noop */ } inst.pill = null; }
      inst.minimized = false;
      inst.running = false;
      instances.delete(jobId);
      restackPills();
    }

    function currentResolution() {
      const checked = pick('input[name="grokI2vRes"]:checked');
      return checked ? checked.value : '480p';
    }
    function savePrefs() {
      if (!inst.overlay) return;
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
    function setStatus(text, type) {
      const status = pick('.grok-i2v-status');
      if (!status) return;
      status.className = 'grok-i2i-status grok-i2v-status' + (type ? ' ' + type : '');
      status.textContent = text || '';
    }
    function setRunning(on) {
      inst.running = !!on;
      const gen = pick('.grok-i2v-generate');
      if (gen) { gen.disabled = inst.running; gen.textContent = inst.running ? '생성 중…' : '생성'; }
      const minBtn = pick('.grok-i2v-min');
      if (minBtn) minBtn.style.display = inst.running ? '' : 'none';
    }
    function generate() {
      if (inst.running || !inst.ctx) return;
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
      inst.lastPrompt = prompt;
      savePrefs();
      setRunning(true);
      inst.lastPillText = '생성중 …';
      setStatus('생성 중… (백그라운드 진행, 상단 진행률 표시)', 'info');
      ws.send(JSON.stringify({
        type: 'grok_i2v',
        job_id: jobId,
        source: inst.ctx.source || '',
        path: inst.ctx.path || '',
        file_path: inst.ctx.filePath || '',
        label: inst.ctx.label || '',
        prompt,
        duration,
        resolution,
      }));
      minimizeBack(false);  // 생성 시작과 동시에 자동 최소화 → 상단 진행률 pill
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
        // autoplay 제거: 완료가 최소화(숨겨진) 상태에서 일어나도 자동재생/오디오가 나지 않도록.
        body.innerHTML = `<div class="grok-i2v-player"><video src="/api/grok/video/${id}" controls loop playsinline controlslist="nodownload noremoteplayback" disablepictureinpicture></video></div>`;
      }
      if (actions) {
        actions.innerHTML = `
          <button type="button" class="grok-i2i-generate grok-i2v-openfolder">폴더 열기</button>
          <button type="button" class="grok-i2i-cancel grok-i2v-cancel">닫기</button>`;
        const folderBtn = actions.querySelector('.grok-i2v-openfolder');
        if (folderBtn) folderBtn.addEventListener('click', openFolder);
        const cancel = actions.querySelector('.grok-i2v-cancel');
        if (cancel) cancel.addEventListener('click', closeOrMinimize);
      }
      setStatus(savedName ? `✓ 저장됨: ${savedName}` : '완료 (자동 저장 실패 — 폴더 열기로 확인)', 'info');
    }

    inst.onState = function onState(msg) {
      if (!inst.overlay || !msg) return;
      if (msg.running) {
        setRunning(true);
        const pct = pctFromProgress(msg.progress);
        inst.lastPillText = '생성중' + (pct != null ? ` ${pct}%` : ' …');
        if (inst.minimized) setPill(inst.lastPillText, false);
        else setStatus((msg.message || '생성 중…') + (pct != null ? ` (${pct}%)` : ''), 'info');
        return;
      }
      setRunning(false);
      inst.done = true;  // 끝남(성공/실패) → MAX 초과 시 자동 종료 후보(완료 영상은 이미 히스토리 등록됨)
      if (msg.success && msg.video_id) {
        showVideo(msg.video_id, msg.saved_name || '');
        showToast('Grok 영상 저장 완료', 'success');
        captureThumbnail(msg.video_id, inst.lastPrompt);
        if (inst.minimized) setPill('✓ 완료! (클릭하여 보기)', true);
      } else {
        inst.failed = true;
        if (inst.minimized) setPill('✕ 실패 (클릭하여 보기)', true);
        setStatus(msg.message || '생성 실패', 'error');
      }
    };
    inst.close = close;  // open() 의 자동 슬롯 비우기에서 호출

    // ── 오버레이 빌드 ──
    const pre = lsGet(K_PRE, PRE_DEFAULT);
    const main = lsGet(K_MAIN, '');
    const post = lsGet(K_POST, POST_DEFAULT);
    const duration = lsGet(K_DURATION, '5');
    const resolution = lsGet(K_RESOLUTION, '480p');
    inst.overlay = document.createElement('div');
    inst.overlay.className = 'grok-i2i-overlay';
    inst.overlay.innerHTML = `
      <div class="grok-i2i-dialog grok-i2v-dialog" role="dialog" aria-label="Grok I2V 영상 생성">
        <div class="grok-i2i-header">
          <span class="grok-i2i-title">GROK · 이미지 → 영상 (I2V)</span>
          <button type="button" class="grok-i2v-min grok-i2i-x" aria-label="최소화" title="최소화 (생성은 백그라운드 진행)" style="display:none">&minus;</button>
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
    inst.overlay.addEventListener('click', (event) => { if (event.target === inst.overlay) closeOrMinimize(); });
    pick('.grok-i2v-x').addEventListener('click', closeOrMinimize);
    const minBtn = pick('.grok-i2v-min');
    if (minBtn) minBtn.addEventListener('click', () => minimizeBack(false));
    pick('.grok-i2v-cancel').addEventListener('click', closeOrMinimize);
    pick('.grok-i2v-generate').addEventListener('click', generate);
    inst.overlay.querySelectorAll('.grok-prompt').forEach((field) => field.addEventListener('input', savePrefs));
    const dur = pick('.grok-i2v-duration');
    const durVal = pick('.grok-i2v-dur-val');
    if (dur) dur.addEventListener('input', () => { if (durVal) durVal.textContent = dur.value; savePrefs(); });
    inst.overlay.querySelectorAll('input[name="grokI2vRes"]').forEach((radio) => radio.addEventListener('change', savePrefs));
    document.body.appendChild(inst.overlay);
    minimizeOthers();  // 새 설정 모달을 열 때 기존 표시 중 결과창은 pill 로 → 중첩 방지
    setTimeout(() => { const m = pick('.grok-prompt-main'); if (m) m.focus(); }, 0);
    return inst;
  }

  function open(context) {
    if (!context || !context.hasImage) { showToast('영상을 만들 이미지를 찾을 수 없습니다.', 'error'); return; }
    if (instances.size >= MAX_INSTANCES) {
      // 끝난(완료/실패) 인스턴스가 있으면 자동으로 닫아 슬롯을 비우고 진행한다. 완료 영상은 완료 시점에
      // captureThumbnail 으로 히스토리에 이미 등록됐고 mp4 도 자동저장돼 있어 닫아도 유실 없음.
      const finished = Array.from(instances.values()).filter((i) => i.done && !i.running);
      const victim = finished.find((i) => i.minimized) || finished[0];
      if (victim && victim.close) {
        victim.close();
      } else {
        showToast(`한 번에 최대 ${MAX_INSTANCES}개까지만 생성 대기열을 걸 수 있습니다. (완료된 항목이 없어 자리를 비울 수 없습니다)`, 'error');
        return;
      }
    }
    createInstance(context);
  }

  function onState(msg) {
    if (!msg) return;
    let inst = instances.get(String(msg.job_id || ''));
    // 구버전 백엔드(job_id 미전송) 폴백: 인스턴스가 정확히 1개면 그쪽으로 라우팅.
    if (!inst && !msg.job_id && instances.size === 1) inst = instances.values().next().value;
    if (inst && inst.onState) inst.onState(msg);
  }

  // 외부 호환용 close: 모든 인스턴스 닫기(현재 app.js 는 호출하지 않음).
  function close() { Array.from(instances.values()).forEach((inst) => { if (inst.overlay) { stopVideos(inst.overlay); inst.overlay.remove(); } if (inst.pill) { try { inst.pill.remove(); } catch (error) { /* noop */ } } }); instances.clear(); }

  return {open, onState, close};
}
