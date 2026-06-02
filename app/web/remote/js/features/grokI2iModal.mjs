// Grok I2I 모달 (제거 가능) — 이미지 우클릭 → "Grok 변형(I2I)".
//
// 좌 소스 이미지 · 우 [메인 프롬프트 1칸 + 고품질 + 추가 참조 이미지(여러 장)] · 하단 [생성][닫기].
// xAI edits API 다중 이미지 지원 → 소스 + 추가 이미지들을 함께 보낸다(1장=image, 여러장=images).
// 메인 프롬프트/고품질은 localStorage 영속, 추가 이미지는 세션 한정(파일선택·드래그·붙여넣기, 최대 5장).
// 생성 = WS {type:'grok_i2i', ..., prompt, quality, extra_images:[dataURL,...]} → 결과는 메인 결과창 주입.
//
// 제거: 이 파일 + resultContextMenu 의 Grok 항목 + app.js wiring + 백엔드 grok_i2i_commands 삭제.

const K_PROMPT = 'naia_grok_i2i_prompt';
const K_QUALITY = 'naia_grok_i2i_quality';
const MAX_EXTRA = 5;

function lsGet(key, fallback) {
  try { const value = localStorage.getItem(key); return value === null ? fallback : value; }
  catch (error) { return fallback; }
}
function lsSet(key, value) { try { localStorage.setItem(key, value); } catch (error) { /* 비치명 */ } }

export function createGrokI2iModal({document, getWs, WebSocket, showToast = () => {}, escHtml = (value) => String(value)}) {
  let overlay = null;
  let ctx = null;
  let running = false;
  let extraImages = []; // 추가 참조 이미지 (압축된 data URL), 세션 한정

  function pick(selector) { return overlay ? overlay.querySelector(selector) : null; }

  function savePrefs() {
    if (!overlay) return;
    const main = pick('.grok-prompt-main');
    const quality = pick('.grok-i2i-quality-cb');
    if (main) lsSet(K_PROMPT, main.value || '');
    if (quality) lsSet(K_QUALITY, quality.checked ? '1' : '0');
  }

  function close() {
    if (overlay) { overlay.remove(); overlay = null; }
    ctx = null;
    running = false;
    extraImages = [];
  }

  function setStatus(text, type) {
    const status = pick('.grok-i2i-status');
    if (!status) return;
    status.className = 'grok-i2i-status' + (type ? ' ' + type : '');
    status.textContent = text || '';
  }

  function setLoading(loading) {
    const gen = pick('.grok-i2i-generate');
    if (gen) { gen.disabled = !!loading; gen.textContent = loading ? '생성 중…' : '생성'; }
  }

  // 큰 참조 이미지는 전송 전 최대 1024px / jpeg 0.85 로 압축해 WS 페이로드를 제한한다.
  function compressImage(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = reject;
      reader.onload = () => {
        const img = new Image();
        img.onerror = reject;
        img.onload = () => {
          const max = 1024;
          const scale = Math.min(1, max / Math.max(img.naturalWidth || 1, img.naturalHeight || 1));
          const w = Math.max(1, Math.round((img.naturalWidth || 1) * scale));
          const h = Math.max(1, Math.round((img.naturalHeight || 1) * scale));
          const canvas = document.createElement('canvas');
          canvas.width = w; canvas.height = h;
          canvas.getContext('2d').drawImage(img, 0, 0, w, h);
          resolve(canvas.toDataURL('image/jpeg', 0.85));
        };
        img.src = reader.result;
      };
      reader.readAsDataURL(file);
    });
  }

  function renderExtras() {
    const strip = pick('.grok-i2i-extras');
    if (!strip) return;
    if (!extraImages.length) {
      strip.innerHTML = '<span class="grok-extra-hint">+ 이미지 추가 · 드래그 · 붙여넣기 (참조용, 최대 5장)</span>';
      return;
    }
    strip.innerHTML = extraImages.map((url, i) =>
      `<div class="grok-extra-thumb"><img src="${escHtml(url)}" alt=""><button type="button" class="grok-extra-x" data-i="${i}" aria-label="제거">&times;</button></div>`
    ).join('');
    strip.querySelectorAll('.grok-extra-x').forEach((btn) => {
      btn.addEventListener('click', () => { extraImages.splice(Number(btn.dataset.i), 1); renderExtras(); });
    });
  }

  async function addFiles(fileList) {
    const files = Array.from(fileList || []).filter((f) => f && f.type && f.type.startsWith('image/'));
    for (const f of files) {
      if (extraImages.length >= MAX_EXTRA) { showToast(`참조 이미지는 최대 ${MAX_EXTRA}장입니다.`, 'warning'); break; }
      try { extraImages.push(await compressImage(f)); } catch (error) { /* 스킵 */ }
    }
    renderExtras();
  }

  function generate() {
    if (running || !ctx) return;
    const main = pick('.grok-prompt-main');
    const prompt = ((main && main.value) || '').trim();
    if (!prompt) { setStatus('프롬프트를 입력하세요.', 'error'); if (main) main.focus(); return; }
    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) { setStatus('서버에 연결되어 있지 않습니다.', 'error'); return; }
    const qualityCb = pick('.grok-i2i-quality-cb');
    const quality = qualityCb && qualityCb.checked ? 'high' : '';
    savePrefs();
    running = true;
    setLoading(true);
    setStatus('생성 중… (수 초~수십 초)', 'info');
    ws.send(JSON.stringify({
      type: 'grok_i2i',
      source: ctx.source || '',
      path: ctx.path || '',
      file_path: ctx.filePath || '',
      label: ctx.label || '',
      prompt,
      quality,
      extra_images: extraImages.slice(0, MAX_EXTRA),
    }));
  }

  function onPaste(event) {
    // 모달이 열린 동안 paste 는 모달이 소유 → 메인 윈도우의 이미지-감지 paste 핸들러로 전파 차단.
    // (메인 핸들러는 document 버블 단계라 오버레이에서 stopPropagation 하면 도달 안 함.)
    event.stopPropagation();
    const files = event.clipboardData && event.clipboardData.files;
    if (!files || !files.length) return;
    const imgs = Array.from(files).filter((f) => f.type && f.type.startsWith('image/'));
    if (imgs.length) { event.preventDefault(); addFiles(imgs); }
  }

  function open(context) {
    if (!context || !context.hasImage) { showToast('변형할 이미지를 찾을 수 없습니다.', 'error'); return; }
    close();
    ctx = context;
    extraImages = [];
    const prompt = lsGet(K_PROMPT, lsGet('naia_grok_i2i_main', ''));
    const quality = lsGet(K_QUALITY, '0') === '1';
    overlay = document.createElement('div');
    overlay.className = 'grok-i2i-overlay';
    overlay.innerHTML = `
      <div class="grok-i2i-dialog" role="dialog" aria-label="Grok I2I 이미지 변형">
        <div class="grok-i2i-header">
          <span class="grok-i2i-title">GROK · 이미지 변형 (I2I)</span>
          <button type="button" class="grok-i2i-x" aria-label="닫기">&times;</button>
        </div>
        <div class="grok-i2i-body">
          <div class="grok-i2i-image"><img src="${escHtml(context.imageSrc || '')}" alt=""></div>
          <div class="grok-i2i-side grok-side-3">
            <label class="grok-prompt-label">메인 프롬프트 <span class="grok-i2i-hint">네거티브 없음 — 변형 지시만</span></label>
            <textarea class="grok-prompt grok-prompt-main" spellcheck="false" placeholder="예: 눈 내리는 밤 풍경으로 / make it a watercolor painting">${escHtml(prompt)}</textarea>
            <label class="grok-i2i-quality"><input type="checkbox" class="grok-i2i-quality-cb" ${quality ? 'checked' : ''}> 고품질 (느림)</label>
            <div class="grok-i2i-extra-block">
              <div class="grok-extra-head">
                <span class="grok-prompt-label">추가 참조 이미지</span>
                <button type="button" class="grok-extra-add">+ 이미지 추가</button>
              </div>
              <div class="grok-i2i-extras grok-extra-drop"></div>
              <input type="file" class="grok-extra-file" accept="image/*" multiple hidden>
              <p class="grok-extra-note">* 2장 이상 입력 시 400 에러(NSFW 콘텐츠 모더레이션)가 발생할 가능성이 높습니다.</p>
            </div>
          </div>
        </div>
        <div class="grok-i2i-actions">
          <button type="button" class="grok-i2i-generate">생성</button>
          <button type="button" class="grok-i2i-cancel">닫기</button>
        </div>
        <div class="grok-i2i-status"></div>
      </div>`;
    overlay.addEventListener('click', (event) => { if (event.target === overlay) close(); });
    overlay.addEventListener('paste', onPaste);
    pick('.grok-i2i-x').addEventListener('click', close);
    pick('.grok-i2i-cancel').addEventListener('click', close);
    pick('.grok-i2i-generate').addEventListener('click', generate);
    pick('.grok-prompt-main').addEventListener('input', savePrefs);
    const qualityCb = pick('.grok-i2i-quality-cb');
    if (qualityCb) qualityCb.addEventListener('change', savePrefs);
    const fileInput = pick('.grok-extra-file');
    pick('.grok-extra-add').addEventListener('click', () => fileInput && fileInput.click());
    if (fileInput) fileInput.addEventListener('change', () => { addFiles(fileInput.files); fileInput.value = ''; });
    const drop = pick('.grok-extra-drop');
    if (drop) {
      drop.addEventListener('dragover', (event) => { event.preventDefault(); drop.classList.add('drag'); });
      drop.addEventListener('dragleave', () => drop.classList.remove('drag'));
      drop.addEventListener('drop', (event) => { event.preventDefault(); drop.classList.remove('drag'); addFiles(event.dataTransfer && event.dataTransfer.files); });
    }
    renderExtras();
    document.body.appendChild(overlay);
    setTimeout(() => { const m = pick('.grok-prompt-main'); if (m) m.focus(); }, 0);
  }

  function onState(msg) {
    if (!overlay) return;
    if (msg && msg.running) { running = true; setLoading(true); setStatus(msg.message || '생성 중…', 'info'); return; }
    running = false;
    setLoading(false);
    if (msg && msg.success) {
      showToast(msg.message || 'Grok I2I 완료', 'success');
      close(); // 결과는 메인 결과창/히스토리에 표시됨
    } else {
      setStatus((msg && msg.message) || '생성 실패', 'error'); // 모달 유지 → 재시도 가능
    }
  }

  return {open, close, onState};
}
