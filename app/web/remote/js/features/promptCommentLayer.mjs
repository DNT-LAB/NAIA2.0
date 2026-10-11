/**
 * 캐릭터 프롬프트 칸의 `#주석` 을 연노랑으로 그리는 층.
 *
 * 사용자 지정 2026-10-11: "캐릭터 프롬프트에도 주석을 지원합니다. 주석은 연노랑색으로 강조됩니다."
 *
 * 무엇이 주석인가 - 백엔드와 **같은 규칙**이어야 한다(`core/character_settings.strip_comment_tags` ·
 * `_expand_character_text`). 화면이 주석이라고 칠한 것이 실제로는 태그로 나가면 강조가 거짓말이 된다.
 *
 *   - 쉼표로 가른 토막의 앞뒤 공백 · 개행을 떼고 `#` 로 시작하면 주석이다(메인 프롬프트와 같다).
 *   - `<...>` 안의 쉼표는 경계가 아니다(`split_tags_smart` - 표정 태그 `:<` `>_<` 의 꺾쇠는 블록이 아니다).
 *   - Connect 마커(`&connect:` · `&end`)는 토막의 경계다 - 백엔드가 세 구간을 따로 전개한다.
 *
 * 어떻게 칠하는가 - 메인 프롬프트와 같은 방식이다. 주석이 있는 칸만 칸(textarea)의 글자를 투명하게 하고,
 * 칸 위에 얹은 층이 같은 글을 그리되 주석만 연노랑으로 그린다(`.has-cmt` - style.css 의 `.pc-cmt`). 주석이 없는 칸은
 * 층을 비우고 칸이 평소대로 제 글을 그린다.
 *
 * ⚠️ 층이 글을 대신 그리는 동안에는 **층이 낡으면 틀린 글이 보인다.** 그래서
 *   - `.has-cmt` 는 층을 다 칠한 뒤에 붙이고, 칠하다 실패하면 떼고 층을 비운다(칸이 다시 제 글을 그린다).
 *   - 칸의 값이 바뀌는 길은 전부 칠하기로 와야 한다: 타이핑 · 자동완성(input 이벤트를 낸다) · 서버 값 · 다시 그리기.
 *     부르는 쪽(퀵 패널의 `paintConnectHighlight` · 워크스페이스의 `autoGrow`)이 그 자리들이다.
 * ⚠️ 층은 칸 **뒤**의 형제여야 한다(색을 고르는 선택자가 `칸 ~ .pc-cmt` 다). 치수는 칸과 한 글자도 다르면 안 된다.
 */

// 파이썬이 공백으로 보는 글자들(`str.strip()` · `re` 의 `\s` = `str.isspace`). JS 의 `trim()` · `\s` 와 조금 다르다:
// JS 는 U+FEFF 를 떼고 U+0085 · U+001C~1F 는 안 뗀다. 백엔드가 떼는 대로 떼야 화면의 주석과 실제가 같다
// (Codex 리뷰 2026-10-11 3차: `girl, \uFEFF#memo` 를 화면만 주석이라 했다).
const PY_WS = '\\t\\n\\v\\f\\r\\x1c-\\x1f \\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000';
const PY_LEAD_RE = new RegExp(`^[${PY_WS}]+`);
const PY_TRAIL_RE = new RegExp(`[${PY_WS}]+$`);
const pyTrimStart = text => text.replace(PY_LEAD_RE, '');
const pyTrim = text => text.replace(PY_LEAD_RE, '').replace(PY_TRAIL_RE, '');

const CONNECT_OPEN_RE = new RegExp(`&connect[${PY_WS}]*:?`, 'i');
const CONNECT_CLOSE_RE = /&end/i;

/** `<` 바로 뒤가 쉼표나 끝인가 - 그러면 블록을 여는 것이 아니라 태그의 끝 글자다(`:<`). */
function angleEndsTag(text, index) {
  const rest = pyTrimStart(text.slice(index + 1));
  return !rest || rest[0] === ',';
}

/** `>` 가 `>_<` 꼴 표정 태그의 머리인가 - 그러면 블록을 닫지 않는다.
 *  ⚠️ 앞보기는 **글자(코드포인트) 둘**이다 - 백엔드가 그렇게 센다. UTF-16 단위로 세면 이모지 하나가 두 칸을 다 먹는다. */
function angleStartsEmoticon(text, index) {
  let pos = index + 1;
  for (let step = 0; step < 2; step += 1) {
    if (pos >= text.length || text[pos] === ',' || text[pos] === '>') return false;
    if (text[pos] === '<') return angleEndsTag(text, pos);
    pos += text.codePointAt(pos) > 0xffff ? 2 : 1;
  }
  return false;
}

/** 쉼표로 가른 토막의 구간 `[start, end)` 목록. 글자를 자르지 않고 구간만 낸다. */
export function tagRanges(text) {
  const out = [];
  let depth = 0;
  let start = 0;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (char === '<') {
      if (!angleEndsTag(text, index)) depth += 1;
    } else if (char === '>') {
      if (!angleStartsEmoticon(text, index)) depth = Math.max(0, depth - 1);
    } else if (char === ',' && depth === 0) {
      out.push([start, index]);
      start = index + 1;
    }
  }
  out.push([start, text.length]);
  return out;
}

/** 첫 Connect 마커 한 쌍으로 가른 구간 `[이 글에서의 시작, 글]` 목록. 마커가 없으면 통째로 하나. */
function splitConnectOnce(source) {
  const opened = source.match(CONNECT_OPEN_RE);
  if (!opened) return [[0, source]];
  const restStart = opened.index + opened[0].length;
  const rest = source.slice(restStart);
  const closed = rest.match(CONNECT_CLOSE_RE);
  if (!closed) return [[0, source.slice(0, opened.index)], [restStart, rest]];
  const tailStart = restStart + closed.index + closed[0].length;
  return [
    [0, source.slice(0, opened.index)],
    [restStart, rest.slice(0, closed.index)],
    [tailStart, source.slice(tailStart)],
  ];
}

/** 구간 안의 마커(한 쌍)를 **같은 길이의 쉼표 + 빈칸**으로 바꾼다. 글자 수가 그대로라 구간의 좌표가 안 밀린다.
 *
 *  백엔드는 구간 안에 마커가 또 있으면 그 앞뒤를 `, ` 로 이어 붙인 뒤 가른다(`strip_connect_markers`) - 두 번째
 *  마커는 **쉼표와 같고**, 꺾쇠 깊이는 그 너머로 이어진다. `<a &connect: #memo, b>` 는 블록 하나라 `#memo` 는
 *  주석이 아니다(Codex 2차 리뷰: 여기를 구간 나누기로 옮겼다가 화면과 실제가 갈렸다). */
function maskInnerMarkers(part) {
  const opened = part.match(CONNECT_OPEN_RE);
  if (!opened) return part;
  const comma = token => ',' + ' '.repeat(token.length - 1);
  const rest = part.slice(opened.index + opened[0].length);
  const closed = rest.match(CONNECT_CLOSE_RE);
  const tail = closed
    ? rest.slice(0, closed.index) + comma(closed[0]) + rest.slice(closed.index + closed[0].length)
    : rest;
  return part.slice(0, opened.index) + comma(opened[0]) + tail;
}

/** 나갈 토막 `{start, end, core}` 목록(원문 좌표 · 앞뒤 공백을 뗀 것 · 빈 토막 제외).
 *
 *  ⚠️ 백엔드 `core/character_settings._comment_pieces` 와 **같은 순서**로 가른다:
 *     1. 첫 마커 한 쌍으로 구간을 나눈다(구간은 따로 전개된다 - 꺾쇠 깊이가 넘어가지 않는다).
 *     2. 구간 안의 두 번째 마커는 쉼표로 본다(`maskInnerMarkers`).
 *     3. 쉼표로 가른다(`tagRanges`). */
export function promptPieces(text) {
  const source = String(text || '');
  const out = [];
  for (const [offset, part] of splitConnectOnce(source)) {
    const masked = maskInnerMarkers(part);
    for (const [start, end] of tagRanges(masked)) {
      const piece = masked.slice(start, end);
      const core = pyTrim(piece);
      if (!core) continue;
      const lead = piece.length - pyTrimStart(piece).length;
      out.push({start: offset + start + lead, end: offset + start + lead + core.length, core});
    }
  }
  return out;
}

/** 주석 토막의 구간 `[start, end)` 목록(원문 좌표 · 앞뒤 공백은 뺀다). */
export function commentRanges(text) {
  const source = String(text || '');
  if (!source.includes('#')) return [];
  return promptPieces(source).filter(piece => piece.core.startsWith('#')).map(piece => [piece.start, piece.end]);
}

/** 나갈 태그가 하나도 없는 글인가 - 비었거나 주석뿐이다. 백엔드 `character_text_is_blank` 와 같은 판정이다
 *  (주석이 없는 글은 예전 그대로: 빈칸이 아니면 빈 글이 아니다). */
export function commentTextIsBlank(text) {
  const source = String(text || '');
  if (!pyTrim(source)) return true;
  if (!source.includes('#')) return false;
  return !promptPieces(source).some(piece => !piece.core.startsWith('#'));
}

/** 주석을 걷은 글. 주석이 없으면 **원문 그대로**(백엔드 `strip_comment_tags` 와 같은 규칙).
 *  화면이 '나갈 글' 로 무언가를 셈할 때 쓴다 - 슬롯 글을 그대로 이어 붙이면 앞 슬롯의 주석이 뒤 슬롯의 글까지
 *  한 토막으로 삼킨다(토큰 어림이 `#memo` + `girl` 을 0 으로 냈다 - Codex 리뷰 2026-10-11 3차). */
export function stripCommentText(text) {
  const source = String(text || '');
  if (!source.includes('#')) return source;
  const pieces = promptPieces(source);
  if (!pieces.some(piece => piece.core.startsWith('#'))) return source;
  return pieces.filter(piece => !piece.core.startsWith('#')).map(piece => piece.core).join(', ');
}

/** 층에 넣을 HTML. 주석이 없으면 빈 문자열(층을 비운다). 글은 원문과 한 글자도 다르지 않다. */
export function commentLayerHtml(text, escHtml) {
  const source = String(text || '');
  const ranges = commentRanges(source);
  if (!ranges.length) return '';
  let html = '';
  let cursor = 0;
  for (const [start, end] of ranges) {
    html += escHtml(source.slice(cursor, start))
      + `<span class="pc-cmt-on">${escHtml(source.slice(start, end))}</span>`;
    cursor = end;
  }
  return html + escHtml(source.slice(cursor));
}

// 층에 마지막으로 넣은 HTML. `innerHTML` 을 되읽어 견주면 브라우저가 고쳐 쓴 꼴과 달라 매번 다시 넣게 된다.
const painted = new WeakMap();

/** 칸 하나의 주석 층을 다시 칠한다. 층은 칸과 **같은 부모** 안의 `.pc-cmt` 다(없으면 아무 일도 없다). */
export function paintCommentLayer(element, escHtml) {
  const parent = element && element.parentElement;
  const layer = parent && typeof parent.querySelector === 'function' ? parent.querySelector('.pc-cmt') : null;
  if (!layer) return;
  try {
    const html = commentLayerHtml(element.value, escHtml);
    if (painted.get(layer) !== html) {
      layer.innerHTML = html;
      painted.set(layer, html);
    }
    // 다 칠한 **뒤에** 칸의 글자를 숨긴다 - 거꾸로면 칠하다 넘어졌을 때 칸이 빈 것처럼 보인다.
    parent.classList.toggle('has-cmt', !!html);
    layer.scrollTop = element.scrollTop;
  } catch (error) {
    parent.classList.remove('has-cmt');
    painted.delete(layer);
    layer.textContent = '';
    console.error('comment layer paint failed', error);
  }
}
