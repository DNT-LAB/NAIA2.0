/** ANIMA 참조 줄 - 선행 고정에 남은 옛 캐릭터 덩어리 찾기 · 걷기(사용자 지시 2026-11-06).
 *
 *  11-05 판의 [불러오기] 는 칸의 캐릭터 프롬프트를 선행 고정(prefix) 끝에 붙였다:
 *    (character at center: girl, pink eyes, … :0.8)
 *  11-06 부터는 생성할 때 백엔드가 프롬프트 끝에 싣는다(core/anima_engine/reference.py · 여러 장이면 left/right 문장).
 *  선행 고정에 옛 덩어리가 남아 있으면 같은 캐릭터가 두 번 들어가고, 여러 장일 때는 'center' 가 자리를 흐린다 -
 *  창이 알려 주고 [지우기] 로 걷는다. 덩어리 안의 괄호 한 겹((artist) 등)까지 한 덩어리로 본다.
 */

const OLD_BLOCK = /\(character at center:(?:[^()]|\([^()]*\))*:0\.8\)/g;

/** prefix 안의 옛 덩어리들(없으면 []). */
export function findOldBlocks(prefix) {
  return String(prefix || '').match(OLD_BLOCK) || [];
}

/** 옛 덩어리를 걷은 prefix - 덩어리 앞의 쉼표 하나와 사이 공백도 같이 걷는다. 끝 쉼표는 원래 있던 그대로. */
export function stripOldBlocks(prefix) {
  const text = String(prefix || '');
  const tail = /,\s*$/.test(text) ? ',' : '';
  const out = text
    .replace(new RegExp(`\\s*,?\\s*${OLD_BLOCK.source}`, 'g'), '')
    .replace(/^[\s,]+/, '')
    .replace(/[\s,]+$/, '');
  return out ? out + tail : '';
}
