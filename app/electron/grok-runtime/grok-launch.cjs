// Grok 런처 (제거 가능) — resources/progrok-runtime/grok-launch.cjs 로 배포된다.
//
// NAIA.exe 를 Node 로 실행하면(ELECTRON_RUN_AS_NODE) commander 가 process.versions.electron
// 을 감지해 argv 를 잘못 슬라이스(스크립트 경로를 command 로 오인)한다. process.defaultApp 을
// 표시하면 commander 가 node 식 slice(2) 로 복귀해 progrok 서브커맨드(proxy/login/status)가
// 정상 파싱된다. progrok dist 는 top-level await ESM 이라 require() 불가 → 동적 import().
//
// 배포: 이 파일 + `npm i progrok` 결과(node_modules) 를 resources/progrok-runtime/ 에 둔다.
//   resources/progrok-runtime/
//     ├── grok-launch.cjs            (이 파일)
//     └── node_modules/progrok/...   (npm install <progrok tgz> 결과)
process.defaultApp = true;
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const entry = path.join(__dirname, "node_modules", "progrok", "dist", "index.js");
import(pathToFileURL(entry).href).catch((error) => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
});
