// 떠 있는 창(draggablePanel) - 다른 창과 같은 URL(?v=)로 불러온다(다르면 창끼리 겹침 순서가 깨진다).
import {createDraggablePanel} from './draggablePanel.mjs?v=20260926-childalign';

const STYLE = `
.dragpanel.webui-payload-win .dragpanel-body { padding: 0; gap: 0; overflow: hidden; }
.dragpanel.webui-payload-win .webui-custom-payload-popbody { flex: 1 1 auto; min-height: 0; height: auto; overflow-y: auto; }
.dragpanel.webui-payload-win .webui-custom-payload-popbody[hidden] { display: none !important; }
#webuiPayloadReview { overflow: auto; max-height: 38%; }
#webuiPayloadReview table { width: 100%; border-collapse: collapse; text-align: left; font-size: 12px; }
#webuiPayloadReview th, #webuiPayloadReview td { padding: 3px 6px; overflow-wrap: anywhere; }
#webuiPayloadIssues { font-size: 12px; }
#webuiPayloadIssues .error { color: #ff8888; }
#webuiPayloadIssues .warn { color: #e9bf60; }`;

const labels = {
  present: '있음 ✓', missing: '설치 안 됨 · 빠짐 ✗', not_alwayson: 'alwayson 아님',
  too_many_args: '있음 ✓ · args 초과', unknown: '확인 못 함',
};

function localCheck(text) {
  const issues = [{level: 'warn', message: '검사 서버에 연결하지 못해 JSON만 확인했습니다.'}];
  try {
    const parsed = JSON.parse(text);
    const block = parsed && Object.hasOwn(parsed, 'alwayson_scripts') ? parsed.alwayson_scripts : parsed;
    const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
    if (!object(block)) throw Error('스크립트 목록은 JSON 객체여야 합니다.');
    const scripts = Object.entries(block).map(([name, script]) => {
      if (!object(script) || ('args' in script && !Array.isArray(script.args))) {
        throw Error(`${name} 스크립트의 설정 또는 args 형식을 확인하세요.`);
      }
      return {name, args_count: script.args?.length || 0, webui: 'unknown', script_args_max: null};
    });
    return {ok: true, canonical: JSON.stringify(block, null, 2), scripts, issues};
  } catch (error) {
    issues.push({level: 'error', message: error.message});
    return {ok: false, issues, scripts: []};
  }
}

export function createPayloadEditor({save, onClose = () => {}}) {
  const host = document.getElementById('webuiCustomPayloadPopup');
  const el = document.getElementById('pWebuiCustomPayload');
  const table = document.getElementById('webuiPayloadTable');
  const rows = table.tBodies[0];
  const issues = document.getElementById('webuiPayloadIssues');
  const style = document.createElement('style');
  style.textContent = STYLE;
  document.head.append(style);

  let current, timer, disabled;
  const choices = new Map();

  const vw = window.innerWidth || 1280, vh = window.innerHeight || 800;
  const shell = createDraggablePanel({
    document, window,
    title: 'Custom Payload — alwayson_scripts',
    variant: 'webui-payload-win',
    storageKey: 'webui-custom-payload',
    width: Math.max(340, Math.min(560, vw - 16)),
    minWidth: 340,
    maxWidth: 900,
    height: Math.max(300, Math.min(640, vh - 70)),
    minHeight: 300,
    resizable: true,
    // × · Cancel · Esc 어디로 닫아도 진행 중인 검사를 거둔다.
    // 초점이 숨은 창 안에 남지 않게 먼저 놓는다(Edit 단추가 다른 탭에 있어 초점을 못 받을 때가 있다).
    onClose: () => {
      invalidate();
      if (shell.el.contains(document.activeElement)) document.activeElement.blur();
      onClose();
    },
  });
  shell.body.appendChild(host);
  host.hidden = false;
  host.style.display = '';   // 페이지에 놓여 있는 동안 숨기던 인라인(index.html)을 푼다
  shell.el.addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.preventDefault(); shell.close(); }
  });

  function render(info) {
    rows.replaceChildren();
    table.hidden = !info.scripts.length;
    for (const script of info.scripts) {
      const row = rows.insertRow();
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.setAttribute('aria-label', script.name);
      checkbox.checked = choices.get(script.name) ?? (
        !disabled.has(script.name.toLowerCase()) && !['missing', 'not_alwayson'].includes(script.webui)
      );
      checkbox.onchange = () => choices.set(script.name, checkbox.checked);
      row.insertCell().append(checkbox);
      row.insertCell().textContent = script.name;
      row.insertCell().textContent = labels[script.webui];
      row.insertCell().textContent = script.script_args_max == null
        ? script.args_count : `${script.args_count} / ${script.script_args_max}`;
    }
    issues.replaceChildren(...info.issues.map(issue => {
      const line = document.createElement('div');
      line.className = issue.level;
      line.textContent = (issue.script ? issue.script + ' · ' : '') + issue.message;
      return line;
    }));
  }

  function invalidate() {
    clearTimeout(timer);
    current?.controller.abort();
    current = null;
  }

  async function check() {
    clearTimeout(timer);
    if (current?.text === el.value) return current.promise;
    invalidate();
    const task = current = {text: el.value, controller: new AbortController()};
    task.promise = (async () => {
      let info;
      try {
        const response = await fetch('/api/webui/custom-payload/check', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({text: task.text}), signal: task.controller.signal,
        });
        if (!response.ok) throw Error();
        info = await response.json();
      } catch {
        if (task.controller.signal.aborted) return null;
        info = localCheck(task.text);
      }
      if (current !== task || el.value !== task.text) return null;
      render(info);
      return info;
    })();
    return task.promise;
  }

  return {
    isOpen: () => shell.isOpen(),
    open(text, disabledNames) {
      // 이미 떠 있으면 적던 글을 지키고 앞으로만 가져온다(Edit 를 다시 눌렀다).
      if (shell.isOpen()) {
        if (shell.isCollapsed()) shell.expand();
        shell.raise();
        el.focus();
        return current?.promise;
      }
      shell.open();
      shell.bringIntoView?.();
      invalidate();
      choices.clear();
      disabled = new Set(disabledNames.map(name => name.toLowerCase()));
      el.value = text;
      table.hidden = true;
      issues.replaceChildren();
      el.focus();
      return check();
    },
    close: () => shell.close(),
    input() {
      invalidate();
      table.hidden = true;
      issues.replaceChildren();
      timer = setTimeout(check, 400);
    },
    async apply(previewOnly = false) {
      // 빈 칸 = 비우기. 정본 '{}' 대신 빈 글을 저장해 배지가 Edit · 0 이 아니라 비어 보이게 한다.
      if (!el.value.trim()) {
        if (!previewOnly) save('', [], 0);
        return;
      }
      const info = await check();
      if (!info?.ok) return;
      const unchecked = info.scripts.filter((_, i) => !rows.rows[i].querySelector('input').checked)
        .map(script => script.name);
      el.value = info.canonical;
      current.text = info.canonical;
      if (!previewOnly) save(info.canonical, unchecked, info.scripts.length);
    },
  };
}
