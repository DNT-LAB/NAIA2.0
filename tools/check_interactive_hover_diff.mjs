// 배포된 파일에서 tagRow 의 diff 계산 부분을 **그대로 떼어** 돌린다.
// (DOM 없이 로직만 본다 — 문자열이 실제 소스와 같은지도 함께 확인한다.)
import fs from 'node:fs';

const SRC = 'C:/VNR/DEV/NAIA2.0/app/web/remote/js/features/interactiveScenePanel.mjs';
const src = fs.readFileSync(SRC, 'utf8');

const START = 'const left = new Map();';
const END = 'if (!list.length && !gone.length) return \'\';';
const i = src.indexOf(START);
const j = src.indexOf(END);
if (i < 0 || j < 0 || j < i) { console.log('FAIL 소스에서 못 찾음'); process.exit(1); }
const body = src.slice(i, j);
console.log('떼어 온 줄 수:', body.trim().split('\n').length);

const diff = new Function('list', 'now', 'cmp', `
  ${body}
  return {isAdd, gone};
`);

let fails = 0;
const ck = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log((ok ? '  ok    ' : '  FAIL  ') + label
    + (ok ? '' : `   ${JSON.stringify(got)} != ${JSON.stringify(want)}`));
  if (!ok) fails++;
};

// Codex 가 짚은 그 경우 — 지금 판에 rain 이 둘, 카드에 하나
let r = diff(['rain'], ['rain', 'rain'], true);
ck('중복 2개 중 1개가 빠지는 것을 잡는다', r.gone, ['rain']);
ck('  남는 하나는 추가로 안 센다', r.isAdd, [false]);

// 반대 — 카드에 둘, 판에 하나
r = diff(['rain', 'rain'], ['rain'], true);
ck('카드가 하나 더 가지면 그 하나만 추가', r.isAdd, [false, true]);
ck('  제거는 없다', r.gone, []);

// 개수가 같으면 아무 표시도 없다
r = diff(['rain', 'rain'], ['rain', 'rain'], true);
ck('개수가 같으면 조용하다', [r.isAdd, r.gone], [[false, false], []]);

// 순서만 달라도 조용하다
r = diff(['a', 'b'], ['b', 'a'], true);
ck('순서만 다르면 조용하다', [r.isAdd, r.gone], [[false, false], []]);

// 완전히 다른 경우
r = diff(['a'], ['b'], true);
ck('서로 다르면 추가 1 · 제거 1', [r.isAdd, r.gone], [[true], ['b']]);

// 비교를 끄면(cmp=false) 아무것도 강조하지 않는다
r = diff(['a'], ['b'], false);
ck('비교를 끄면 표시 없음', [r.isAdd, r.gone], [[false], []]);

console.log();
console.log(fails ? `실패 ${fails}건` : '전부 통과');
process.exit(fails ? 1 : 0);
