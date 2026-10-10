/** 하단 옵션 줄의 톱니 단추 > **확장 기능** 팝업.
 *
 *  사용자 지시(2026-10-10): "하단에 3종 버튼이 있는데 여기 오른쪽 끝에 톱니바퀴 버튼을 하나 추가하고, 누르면
 *  Alternative 세션의 ALT 툴팁 팝업처럼 확장 기능을 나열" - 자주 쓰지 않는 생성 옵션이 사는 자리다.
 *
 *      ┌ 확장 기능 ────────────────────┐
 *      │ ☐ 랜덤을 누를 때 생성합니다      │   ← 체크해도 팝업은 열린 채
 *      │ Auto Gen 이 꺼져 있을 때 …      │
 *      └───────────────────────────────┘
 *      [Prompt Fixed] [Auto Gen] [WC Solo] [⚙]
 *
 *  ⚠️ **옷은 Interactive 의 ALT 팝업 것을 그대로 입는다**(`.ia-alt-popup` · `.ia-alt-row` …) - 시선 팝업 ·
 *     인원 팝업이 이미 그렇게 빌려 쓴다. 모양을 여기서 다시 만들지 않는다.
 *  ⚠️ **체크 줄은 옵션 통로의 control 이다.** 만들자마자 부르는 쪽의 `optBoxes` 에 등록한다(`registerOption`) -
 *     켜고 끄기 · 서버 동기 · 다른 창과의 맞춤이 세 단추와 같은 길(`toggleOptionButton` -> `set_option` ->
 *     `options` -> `applyOptionState`)로 간다. 그 길이 줄에 `is-on` 을 붙이고 떼므로 여기서는 칠하지 않는다.
 *     그래서 팝업 요소는 **닫아도 지우지 않는다**(지우면 등록된 control 이 문서 밖의 노드가 된다).
 *  ⚠️ 줄에 툴팁을 달지 않는다 - 설명은 아래 줄(`FOOT`)에 있고, 툴팁이 뜨면 바로 그 줄을 덮는다(실측).
 *  ⚠️ 여기 사는 옵션은 닫혀 있으면 안 보인다 - 하나라도 켜져 있으면 톱니 단추가 물든다(`paint`).
 *
 *  항목은 지금 하나다(사용자: "한 줄로 시작합니다"). 늘어나면 `ITEMS` 에 줄을 더한다 - 묶음 머리글은
 *  ALT 팝업의 `.ia-alt-group` 을 쓰면 된다.
 */

const ITEMS = [
  {
    key: 'generate_on_random',
    label: '랜덤을 누를 때 생성합니다',
  },
];
const FOOT = 'Auto Gen 이 꺼져 있을 때, Random 을 누르면 프롬프트를 굴린 뒤 곧바로 <b>한 장</b> 생성합니다. '
  + '프로그램을 다시 켜면 꺼집니다.';

export function createOptionExtras({
  document: doc,
  window: win,
  button,                        // `#optExtrasBtn`
  registerOption = () => {},     // (key, control) => void   부르는 쪽의 optBoxes 에 넣는다
  toggleOption = () => {},       // (key) => void            세 단추와 같은 길
  isChecked = () => false,       // (key) => bool
} = {}) {
  if (!doc || !button) return null;
  const keys = new Set(ITEMS.map(item => item.key));

  const popup = doc.createElement('div');
  popup.className = 'ia-alt-popup opt-extras-popup';
  popup.hidden = true;
  popup.setAttribute('role', 'dialog');
  popup.setAttribute('aria-label', '확장 기능');
  popup.innerHTML = '<div class="ia-alt-head">확장 기능</div>'
    + '<div class="ia-alt-list">'
    + ITEMS.map(item => `<button type="button" class="ia-alt-row" data-option="${item.key}" `
      + 'data-checked="false" aria-pressed="false">'
      + `<span class="ia-alt-box"></span><span class="ia-alt-label">${item.label}</span></button>`).join('')
    + '</div>'
    + `<div class="ia-alt-foot">${FOOT}</div>`;
  doc.body.appendChild(popup);
  ITEMS.forEach(item => registerOption(item.key, popup.querySelector(`[data-option="${item.key}"]`)));

  function paint() {
    button.classList.toggle('has-on', ITEMS.some(item => isChecked(item.key)));
  }

  function place() {
    const rect = button.getBoundingClientRect();
    const size = popup.getBoundingClientRect();
    const vw = win.innerWidth;
    const vh = win.innerHeight;
    // 단추의 오른쪽 끝에 맞춰 **위로** 연다(단추가 화면 아래에 있다). 위가 모자라면 아래로.
    const left = Math.max(8, Math.min(rect.right - size.width, vw - size.width - 8));
    let top = rect.top - size.height - 6;
    if (top < 8) top = Math.min(vh - size.height - 8, rect.bottom + 6);
    popup.style.left = `${Math.round(left)}px`;
    popup.style.top = `${Math.round(Math.max(8, top))}px`;
  }

  function isOpen() { return !popup.hidden; }

  function open() {
    if (isOpen()) return;
    popup.hidden = false;
    button.setAttribute('aria-expanded', 'true');
    place();
    doc.addEventListener('mousedown', onOutside, true);
    doc.addEventListener('keydown', onKeydown, true);
    win.addEventListener('resize', close);
  }

  function close() {
    if (!isOpen()) return;
    popup.hidden = true;
    button.setAttribute('aria-expanded', 'false');
    doc.removeEventListener('mousedown', onOutside, true);
    doc.removeEventListener('keydown', onKeydown, true);
    win.removeEventListener('resize', close);
  }

  function onOutside(event) {
    if (popup.contains(event.target) || button.contains(event.target)) return;   // 단추는 제 손이 처리한다
    close();
  }

  function onKeydown(event) {
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(); }
  }

  button.addEventListener('click', () => { if (isOpen()) close(); else open(); });
  // 체크해도 팝업은 열린 채 둔다(ALT 팝업과 같다). 초점이 줄로 옮겨 가지 않게 mousedown 을 막는다.
  popup.addEventListener('mousedown', event => event.preventDefault());
  popup.addEventListener('click', event => {
    const row = event.target.closest('[data-option]');
    if (!row || !keys.has(row.dataset.option)) return;
    event.stopPropagation();
    toggleOption(row.dataset.option);
  });

  paint();
  return {
    owns: key => keys.has(key),
    paint,
    open,
    close,
    isOpen,
  };
}
