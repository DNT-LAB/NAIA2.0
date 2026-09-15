/** `<anchor:ID>` 문법 — **백엔드(`core/artist_anchor.py`)의 거울**.
 *
 *  ⚠️ `ANCHOR_PATTERN_SOURCE` 는 파이썬 쪽과 **글자 하나까지 같아야 한다**. 계약 시험이
 *     두 파일의 문자열을 직접 대조한다. 문법이 둘이면 화면은 "표식 멀쩡" 이라 하는데
 *     서버는 못 알아보고 지운다(또는 그 반대) - 빨간불이 켜져야 할 때 안 켜진다.
 *
 *  엄격 파싱이다. `< anchor:1 >`·`<anchor: 1>`·`<Anchor:1>` 은 **앵커가 아니다**.
 *  사용자가 표식을 건드려 깨뜨린 것을 잡아내는 게 이 규칙의 일이라, 봐주면 안 된다.
 */

export const ANCHOR_PATTERN_SOURCE = '<anchor:([A-Za-z0-9_-]{1,32})>';
export const ANCHOR_ID_SOURCE = '^[A-Za-z0-9_-]{1,32}$';

const idRe = new RegExp(ANCHOR_ID_SOURCE);

/** ⚠️ `g` 플래그 정규식은 `lastIndex` 를 들고 다닌다 - 공유하면 한 번 걸러 한 번씩
 *  놓친다. 쓸 때마다 새로 만든다. */
const anchorRe = () => new RegExp(ANCHOR_PATTERN_SOURCE, 'g');

export function anchorToken(anchorId) {
  const text = String(anchorId ?? '').trim();
  if (!idRe.test(text)) throw new Error(`invalid anchor id: ${text}`);
  return `<anchor:${text}>`;
}

/** 글에 나온 순서대로. 같은 아이디가 두 번이면 두 번 들어 있다. */
export function findAnchorIds(text) {
  return [...String(text ?? '').matchAll(anchorRe())].map(m => m[1]);
}

export function hasAnchorId(text, anchorId) {
  const want = String(anchorId ?? '');
  return findAnchorIds(text).includes(want);
}

/** 이미 쓰인 아이디를 피해 다음 번호를 고른다. 사람이 읽는 번호라 1 부터 센다. */
export function nextAnchorId(used) {
  const taken = new Set([...(used || [])].map(v => String(v)));
  for (let n = 1; n < 1000; n += 1) {
    if (!taken.has(String(n))) return String(n);
  }
  throw new Error('no anchor id left');
}

/** 표식을 글 **맨 뒤**에 붙인다(사용자 지정: 추가하면 prefix 끝에 들어간다).
 *  이미 있으면 그대로 둔다 - 두 번 붙으면 같은 그룹이 두 자리에서 펼쳐진다. */
export function appendAnchor(text, anchorId) {
  const body = String(text ?? '').trim().replace(/,\s*$/, '');
  const token = anchorToken(anchorId);
  if (hasAnchorId(body, anchorId)) return body;
  return body ? `${body}, ${token}` : token;
}

/** 표식 하나만 걷어낸다. 앞뒤로 남는 쉼표도 같이 정리한다. */
export function removeAnchor(text, anchorId) {
  const token = anchorToken(anchorId);
  const out = String(text ?? '')
    .split(',')
    .map(part => part.trim())
    .filter(part => part && part !== token)
    .map(part => part.split(token).join('').trim())   // 태그 안에 섞여 있던 경우
    .filter(Boolean)
    .join(', ');
  return out;
}
