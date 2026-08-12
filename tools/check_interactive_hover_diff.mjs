// 호버 diff 의 개수 비교(multiset)를 검사한다.
//
// **범위**: 배포 파일에서 계산 부분을 그대로 떼어 DOM 없이 돌린다. 계산 자체는
// 진짜로 검사하지만, `tagRow()` 가 그 계산에 인자를 옳게 넘기는지(mine/cur 를
// 바꿔 넣지 않았는지)와 HTML 조립·`currentScene()` 연동까지는 보지 못한다 —
// 그쪽은 라이브 확인이 필요하다(Codex 11차 지적).
//
// 소스를 못 찾거나 떼어 온 조각이 안 돌면 **큰 소리로 실패한다**.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

// 경로는 **이 파일 기준**이다. 절대경로로 박아 두면 다른 clone 에서 못 돌거나,
// 더 나쁘게는 그 자리에 남은 옛 checkout 을 검사한다(Codex 11차).
const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(HERE, '..', 'app', 'web', 'remote', 'js', 'features',
                      'interactiveScenePanel.mjs');
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
