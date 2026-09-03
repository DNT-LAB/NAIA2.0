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
  // 지금 띄운 것. [Generate] 가 **무엇을 다시 뽑을지**를 이것으로 가른다.
  let showing = null;

  function build() {
    root = doc.createElement('div');
    root.className = 'pvw-window';
    root.id = 'preview45Window';
    root.innerHTML = `
      <div class="pvw-head">
        <span class="pvw-title" id="preview45WindowTitle">V4.5 PREVIEW</span>
        <span class="pvw-meta" id="preview45WindowMeta"></span>
        <!-- 창을 닫는 길은 **위아래 둘**이다(사용자 지정 2026-09-02). 위는 관례대로 [X]. -->
        <button type="button" class="pvw-x" data-pvw="close"
          title="닫는다 (Esc)">✕</button>
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
      if (btn.dataset.pvw === 'generate') onGenerate?.(showing);
    });
    doc.addEventListener('keydown', event => {
      if (event.key === 'Escape' && isOpen()) close();
    });
    win.addEventListener('resize', place);
  }

  function isOpen() {
    return !!(root && root.classList.contains('open'));
  }

  /**
   * **Result 스테이지(`.viewer-wrapper`) 왼쪽 끝에 붙여** 띄운다(사용자 지정 2026-09-03).
   *
   * ⚠️ 가운데가 아니다. 가운데에 두면 결과 그림을 한복판에서 가려 방금 나온 것을 못 본다
   *    - 왼쪽에 붙이면 오른쪽 절반이 그대로 남는다. 세로는 그대로 가운데다.
   *
   * ⚠️ 자리가 두 번 바뀌었다. 처음엔 여기였고, 2026-09-02 에 프롬프트 창 쪽으로
   *    옮겼다 - **창이 스테이지보다 커지면 [Close] 줄이 화면 밖으로 밀려 닫을 수
   *    없었기 때문**이다(제보: "창을 닫을 수 없게 되었습니다"). 그때 자리를 옮긴 것은
   *    증상 대증요법이었고, 진짜 고침은 그 뒤에 들어간 **뷰포트 가둠**(아래 `clamp`)과
   *    CSS 의 `max-height: calc(100vh - 16px)` 둘이다.
   *    그 둘이 있는 지금은 스테이지에 놓아도 닫기 줄이 밖으로 못 나간다 - 그래서
   *    사용자가 원래 원하던 자리로 되돌린다.
   * ⚠️ **가둠과 높이 제한을 걷어내지 마라.** 하나만 빠져도 옛 사고가 그대로 돌아온다.
   */
  function place() {
    if (!isOpen()) return;
    const anchor = doc.querySelector('.viewer-wrapper') || doc.getElementById('promptEdit');
    const rect = root.getBoundingClientRect();
    const box = anchor ? anchor.getBoundingClientRect() : null;
    const wantLeft = box && box.width > 0
      ? box.left
      : (win.innerWidth - rect.width) / 2;
    const wantTop = box && box.height > 0
      ? box.top + (box.height - rect.height) / 2
      : (win.innerHeight - rect.height) / 2;
    const clamp = (value, span, room) => Math.round(
      Math.max(8, Math.min(value, room - span - 8)));
    root.style.left = `${clamp(wantLeft, rect.width, win.innerWidth)}px`;
    root.style.top = `${clamp(wantTop, rect.height, win.innerHeight)}px`;
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
    showing = message || null;
    // ⚠️ 캐릭터 테스트 생성 결과는 **이미 저장됐다**(Results 에 있다) - [Save] 는
    //    뜻이 없어 감춘다. 프리뷰의 그림만 저장 안 된 것이다.
    const character = String(message?.kind || '') === 'character';
    // ⚠️ [Generate] 도 감춘다(사용자 지정 2026-09-02: "Generate 버튼이 거기에
    //    달려있을 필요는 없어 보이고, 상하 Close 버튼만 있으면 충분"). 이 창은
    //    이미 나간 결과를 보여 줄 뿐이고, 다시 뽑는 것은 슬롯의 [▶] 가 한다.
    //    V4.5 프리뷰에는 그대로 남는다 - 거기서는 다시 뽑는 것이 창의 쓰임새다.
    const saveBtn = root.querySelector('[data-pvw="save"]');
    if (saveBtn) saveBtn.hidden = character;
    const genBtn = root.querySelector('[data-pvw="generate"]');
    if (genBtn) genBtn.hidden = character;
    root.classList.toggle('is-character', character);
    const bytes = atob(String(message.image || ''));
    const buffer = new Uint8Array(bytes.length);
    for (let i = 0; i < bytes.length; i += 1) buffer[i] = bytes.charCodeAt(i);
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = URL.createObjectURL(new Blob([buffer], {type: 'image/webp'}));
    const img = doc.getElementById('preview45Image');
    if (img) {
      // ⚠️ **그림이 그려진 뒤에 다시 자리를 잡는다.** 지금 재면 창은 아직 옛 크기라,
      //    세로로 긴 그림이 들어와 자라면 아래쪽이 화면 밖으로 나간다 - 실측:
      //    높이 683 인데 340 으로 재고 자리를 잡아 밑변이 1103(화면 1080)이었다.
      img.addEventListener('load', place, {once: true});
      img.src = objectUrl;
    }
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
