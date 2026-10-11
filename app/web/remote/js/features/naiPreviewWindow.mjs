/**
 * 캐릭터 '즉시 생성' 결과 창 — 방금 뽑은 한 장을 결과 스테이지 옆에 띄운다.
 *
 * 그 그림은 **평소 생성**이다(Results · 히스토리에 남는다). 이 창은 보여 주기만 한다 - 다시 뽑는 것은
 * 캐릭터 슬롯의 [▶] 가 한다(사용자 지정 2026-09-02: "상하 Close 버튼만 있으면 충분").
 *
 * ⚠️ 원래는 V4.5 프리뷰(V5 할당량을 안 쓰고 구도만 미리 보던 기능)의 창이었고 즉시 생성이 빌려 썼다.
 *    V4.5 프리뷰는 v5-medium 출시로 회수했다(사용자 지시 2026-10-11) - [Save] · [Generate] 와 그 잠금이
 *    함께 빠졌다. 서버 메시지 이름(`nai_preview_result`)과 요소 id(`preview45…`)는 그대로다.
 */
export function createNaiPreviewWindow({
  document: doc,
  window: win,
}) {
  let root = null;
  let objectUrl = '';

  function build() {
    root = doc.createElement('div');
    root.className = 'pvw-window';
    root.id = 'preview45Window';
    root.innerHTML = `
      <div class="pvw-head">
        <span class="pvw-title" id="preview45WindowTitle"></span>
        <span class="pvw-meta" id="preview45WindowMeta"></span>
        <!-- 창을 닫는 길은 **위아래 둘**이다(사용자 지정 2026-09-02). 위는 관례대로 [X]. -->
        <button type="button" class="pvw-x" data-pvw="close"
          title="닫는다 (Esc)">✕</button>
      </div>
      <div class="pvw-stage"><img class="pvw-img" id="preview45Image" alt=""></div>
      <div class="pvw-actions">
        <button type="button" class="pvw-side pvw-close" data-pvw="close">Close</button>
      </div>`;
    doc.body.appendChild(root);
    root.addEventListener('click', event => {
      if (event.target.closest('[data-pvw="close"]')) close();
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

  function close() {
    if (!root) return;
    root.classList.remove('open');
    // ⚠️ blob URL 을 안 놓으면 그림을 띄울 때마다 메모리가 는다.
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
    // 머리글 = 무엇을 뽑았는가(캐릭터 이름 · 프롬프트 앞머리).
    const title = doc.getElementById('preview45WindowTitle');
    if (title) title.textContent = String(message.title || '').trim() || 'CHARACTER';
    root.classList.add('open');
    place();
  }

  return {show, close, isOpen};
}
