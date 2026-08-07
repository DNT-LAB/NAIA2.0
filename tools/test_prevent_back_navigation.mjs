/**
 * 마우스 뒤로가기가 준비 화면으로 돌아가지 못하는지 확인한다.
 *
 * 창은 `maintenance.html` 을 먼저 띄우고 앱 주소로 넘어가므로 준비 화면이
 * 히스토리에 남는다. 그걸 비우는 것이 유일한 방어선이라, 비우는 조건이
 * 정확한지(앱 주소일 때만) 실물 대신 가짜 webContents 로 건다.
 *
 * `node tools/test_prevent_back_navigation.mjs`
 */
import assert from 'node:assert';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);

// main.cjs 는 electron 을 require 한다 — 이 검사는 그 모듈 없이 돌아야 하므로
// 최소한의 껍데기를 끼워 넣는다.
const Module = require('node:module');
const originalLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === 'electron') {
    const noop = () => {};
    const chainable = () => ({ on: noop, once: noop, handle: noop, send: noop });
    return {
      app: { on: noop, once: noop, whenReady: () => new Promise(() => {}), getPath: () => '.',
             requestSingleInstanceLock: () => true, quit: noop, isPackaged: false,
             getVersion: () => '0.0.0', setAppUserModelId: noop, commandLine: { appendSwitch: noop } },
      BrowserWindow: class { static getAllWindows() { return []; } },
      WebContentsView: class {},
      ipcMain: { on: noop, handle: noop, removeHandler: noop },
      shell: { openExternal: noop, openPath: noop, showItemInFolder: noop },
      dialog: { showOpenDialogSync: () => undefined, showMessageBoxSync: () => 0 },
      Menu: { setApplicationMenu: noop, buildFromTemplate: () => ({ popup: noop }) },
      nativeImage: { createFromPath: () => ({ isEmpty: () => true }) },
      net: chainable(),
      session: { defaultSession: { webRequest: { onBeforeSendHeaders: noop } } },
      protocol: { registerFileProtocol: noop, handle: noop },
      screen: { getPrimaryDisplay: () => ({ workAreaSize: { width: 1920, height: 1080 } }) },
    };
  }
  return originalLoad(request, parent, isMain);
};

const { __test } = require('../app/electron/main/main.cjs');
Module._load = originalLoad;

const { preventBackNavigation } = __test;
assert.ok(typeof preventBackNavigation === 'function', 'preventBackNavigation 이 노출돼야 한다');

function fakeWindow(url, { clearThrows = false, hasClear = true } = {}) {
  const calls = { cleared: 0 };
  const handlers = {};
  const wc = {
    getURL: () => url,
    on(event, fn) { (handlers[event] ||= []).push(fn); },
    fire(event) { (handlers[event] || []).forEach(fn => fn()); },
  };
  if (hasClear) {
    wc.clearHistory = () => {
      if (clearThrows) throw new Error('boom');
      calls.cleared += 1;
    };
  }
  return { webContents: wc, calls, setUrl(next) { url = next; } };
}

const results = [];
const check = (name, ok, detail = '') => {
  results.push({ name, ok });
  console.log((ok ? '  PASS  ' : '  FAIL  ') + name + (ok || !detail ? '' : ' -- ' + detail));
};

// 준비 화면(file://)에서는 비우지 않는다 — 아직 갈 곳이 없고, 곧 앱으로 넘어가며 다시 쌓인다.
{
  const w = fakeWindow('file:///C:/app/renderer/maintenance.html');
  preventBackNavigation(w);
  w.webContents.fire('did-finish-load');
  check('준비 화면에서는 히스토리를 안 비운다', w.calls.cleared === 0, String(w.calls.cleared));
}

// 앱 주소로 넘어오면 비운다 — 준비 화면 항목이 사라져 뒤로가기가 아무 일도 못 한다.
{
  const w = fakeWindow('http://127.0.0.1:7860/?naia=1');
  preventBackNavigation(w);
  w.webContents.fire('did-finish-load');
  check('앱 주소에서 히스토리를 비운다', w.calls.cleared === 1, String(w.calls.cleared));
}

// 재시작하면 준비 화면 -> 앱 순서가 다시 생긴다. 매번 비워야 한다.
{
  const w = fakeWindow('http://127.0.0.1:7860/?naia=1');
  preventBackNavigation(w);
  w.webContents.fire('did-finish-load');
  w.webContents.fire('did-finish-load');
  check('넘어올 때마다 비운다', w.calls.cleared === 2, String(w.calls.cleared));
}

// https 로 서빙되는 경우(원격 셸)도 앱이다.
{
  const w = fakeWindow('https://naia.example/?naia=1');
  preventBackNavigation(w);
  w.webContents.fire('did-finish-load');
  check('https 도 앱으로 본다', w.calls.cleared === 1);
}

// 비우다 실패해도 앱은 떠야 한다.
{
  const w = fakeWindow('http://127.0.0.1:7860/', { clearThrows: true });
  preventBackNavigation(w);
  let threw = false;
  try { w.webContents.fire('did-finish-load'); } catch (_) { threw = true; }
  check('비우기가 실패해도 던지지 않는다', !threw);
}

// clearHistory 가 없는 런타임에서도 죽지 않는다.
{
  const w = fakeWindow('http://127.0.0.1:7860/', { hasClear: false });
  preventBackNavigation(w);
  let threw = false;
  try { w.webContents.fire('did-finish-load'); } catch (_) { threw = true; }
  check('clearHistory 가 없어도 죽지 않는다', !threw);
}

// 창이 없으면 조용히 지나간다.
{
  let threw = false;
  try { preventBackNavigation(null); } catch (_) { threw = true; }
  check('창이 없으면 그냥 지나간다', !threw);
}

const failed = results.filter(r => !r.ok);
console.log();
if (failed.length) {
  console.log(`실패 ${failed.length}건: ${failed.map(r => r.name).join(', ')}`);
  process.exit(1);
}
console.log('모두 통과');
