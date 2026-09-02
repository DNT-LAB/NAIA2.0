/**
 * V4.5 프리뷰 창 — 뽑은 구도를 띄우고, 마음에 들면 진짜로 생성한다.
 *
 * 사용자 지정 2026-09-01:
 *   "Action은 [ Save | Generate | Close ] 입니다. Generate 버튼이 크고, 나머지 버튼은
 *    좌우 구석에 작게 박힙니다."
 *
 * ⚠️ 이 그림은 **저장되지 않는다**(사용자 지정). 서버가 결과 저장소에서 빼고 디스크에도
 *    안 쓴다 - [Save] 를 눌렀을 때만 쓴다. 그래서 창을 닫으면 그림은 사라진다.
 *
 * ⚠️ [Generate] 는 **4.5 재생성**이다(사용자 지정 2026-09-01) - 프롬프트를 고쳐 가며
 *    다시 보는 것이 이 창의 쓰임새다. V5 로 진짜 생성하는 버튼이 **아니다**.
 *    그래서 눌러도 창을 닫지 않는다 - 새 그림이 같은 자리에 갈린다.
 */
export function createNaiPreviewWindow({
  document: doc,
  window: win,
  showToast,
  onGenerate,
}) {
  let root = null;
  let objectUrl = '';

  function build() {
    root = doc.createElement('div');
    root.className = 'pvw-window';
    root.id = 'preview45Window';
    root.innerHTML = `
      <div class="pvw-head">
        <span class="pvw-title" id="preview45WindowTitle">V4.5 PREVIEW</span>
        <span class="pvw-meta" id="preview45WindowMeta"></span>
      </div>
      <div class="pvw-stage"><img class="pvw-img" id="preview45Image" alt=""></div>
      <div class="pvw-actions">
        <button type="button" class="pvw-side" data-pvw="save">Save</button>
        <button type="button" class="pvw-main" data-pvw="generate">Generate</button>
        <button type="button" class="pvw-side pvw-close" data-pvw="close">Close</button>
      </div>`;
    doc.body.appendChild(root);
    root.addEventListener('click', event => {
      const btn = event.target.closest('[data-pvw]');
      if (!btn) return;
      if (btn.dataset.pvw === 'close') { close(); return; }
      if (btn.dataset.pvw === 'save') { void save(btn); return; }
      // ⚠️ 닫지 않는다 - 같은 자리에서 새 프리뷰로 갈린다(재테스트 루프).
      if (btn.dataset.pvw === 'generate') onGenerate?.();
    });
    doc.addEventListener('keydown', event => {
      if (event.key === 'Escape' && isOpen()) close();
    });
    win.addEventListener('resize', place);
  }

  function isOpen() {
    return !!(root && root.classList.contains('open'));
  }

  /** 결과 스테이지 **안에** 가둔다 - 밖으로 나가면 다른 패널을 덮는다. */
  function place() {
    if (!isOpen()) return;
    const stage = doc.querySelector('.viewer-wrapper');
    if (!stage) return;
    const box = stage.getBoundingClientRect();
    if (box.width <= 0 || box.height <= 0) return;
    const rect = root.getBoundingClientRect();
    const left = box.left + (box.width - rect.width) / 2;
    const top = box.top + (box.height - rect.height) / 2;
    root.style.left = `${Math.round(Math.max(box.left + 8, left))}px`;
    root.style.top = `${Math.round(Math.max(box.top + 8, top))}px`;
  }

  async function save(btn) {
    btn.disabled = true;
    try {
      const res = await fetch('/api/nai-preview/save', {method: 'POST'});
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { showToast(data.error || '프리뷰를 저장하지 못했습니다.', 'error'); return; }
      showToast('프리뷰를 저장했습니다.', 'success');
    } catch (error) {
      showToast('프리뷰 저장 실패: ' + error.message, 'error');
    } finally {
      btn.disabled = false;
    }
  }

  function close() {
    if (!root) return;
    root.classList.remove('open');
    // ⚠️ blob URL 을 안 놓으면 프리뷰를 뽑을 때마다 메모리가 는다.
    if (objectUrl) { URL.revokeObjectURL(objectUrl); objectUrl = ''; }
  }

  /** 서버가 보낸 `nai_preview_result` 를 받아 띄운다. */
  function show(message) {
    if (!root) build();
    const bytes = atob(String(message.image || ''));
    const buffer = new Uint8Array(bytes.length);
    for (let i = 0; i < bytes.length; i += 1) buffer[i] = bytes.charCodeAt(i);
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = URL.createObjectURL(new Blob([buffer], {type: 'image/webp'}));
    const img = doc.getElementById('preview45Image');
    if (img) img.src = objectUrl;
    const meta = doc.getElementById('preview45WindowMeta');
    // 실려 나간 캐릭터 수를 함께 적는다 - 0 이면 캐릭터가 빠진 것이고, 그것은
    // 화면만 봐서는 알 수 없다(예전에 조용히 사라지던 자리다).
    const cast = Array.isArray(message.characters) ? message.characters.length : 0;
    if (meta) {
      meta.textContent = `${message.width}x${message.height} · ${message.steps} steps`
        + ` · ${message.model}` + (cast ? ` · ${cast} char` : '');
      meta.title = (message.characters || []).join(' | ');
    }
    // 프리뷰와 캐릭터 즉시 생성이 **같은 창**을 쓴다 - 무엇을 보고 있는지 말해 준다.
    const title = doc.getElementById('preview45WindowTitle');
    if (title) title.textContent = String(message.title || '').trim() || 'V4.5 PREVIEW';
    root.classList.add('open');
    place();
  }

  /** 재생성이 도는 동안 [Generate] 를 잠근다 - 연타하면 요청이 쌓인다. */
  function setBusy(busy) {
    const btn = root && root.querySelector('[data-pvw="generate"]');
    if (!btn) return;
    btn.disabled = !!busy;
    btn.textContent = busy ? '생성 중…' : 'Generate';
  }

  return {show, close, isOpen, setBusy};
}
