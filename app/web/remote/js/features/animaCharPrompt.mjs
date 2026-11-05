/** ANIMA 참조 줄의 캐릭터 프롬프트 [불러오기](사용자 지시 2026-11-05).
 *
 *  그림마다 저장한 캐릭터 프롬프트를 선행 고정(prefix) 칸 끝에 한 덩어리로 붙인다:
 *    (character at center: girl, pink eyes, … :0.8)
 *  - 가중치는 ANIMA 에서 0.8 고정(사용자 지정). ComfyUI 는 괄호 안 마지막 ':' 뒤를 가중치로 읽는다(원격 실측 11-05).
 *  - 같은 그림의 덩어리를 다시 불러오면 **앞의 것을 바꿔 끼운다** - 겹쳐 쌓이지 않는다. 앞의 것 = 지난번에 넣은 글
 *    그대로(사용자가 그 덩어리를 손으로 고쳤으면 찾지 못하므로 새로 붙인다 - 고친 글을 지우지 않는다).
 */

export const ANIMA_CHARACTER_WEIGHT = '0.8';

/** 저장된 캐릭터 프롬프트 -> 붙일 덩어리. 비었으면 ''. 줄바꿈 · 앞뒤 쉼표는 걷는다. */
export function characterBlock(prompt) {
  const body = String(prompt || '')
    .replace(/\s*[\r\n]+\s*/g, ' ')
    .replace(/^[\s,]+|[\s,]+$/g, '');
  return body ? `(character at center: ${body}:${ANIMA_CHARACTER_WEIGHT})` : '';
}

/** prefix 에 덩어리를 넣은 글. previous = 같은 그림으로 지난번에 넣은 덩어리(없으면 '').
 *  돌려줌 {text, action}: action = 'replaced' | 'appended' | 'same'(이미 그대로 들어 있다). */
export function placeCharacterBlock(prefix, block, previous = '') {
  const text = String(prefix || '');
  if (!block) return {text, action: 'same'};
  if (previous && previous !== block && text.includes(previous)) {
    return {text: text.replace(previous, () => block), action: 'replaced'};
  }
  if (text.includes(block)) return {text, action: 'same'};
  const head = text.replace(/[\s,]+$/, '');
  const tail = /,\s*$/.test(text) ? ',' : '';
  return {text: head ? `${head}, ${block}${tail}` : `${block}${tail}`, action: 'appended'};
}
