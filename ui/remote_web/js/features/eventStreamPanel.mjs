export function createEventStreamPanel({
  document,
  escHtml,
  setModuleParam,
}) {
  const moduleBody = document.getElementById('modulePopupBody');
  let currentState = null;

  const sendModuleParam = setModuleParam || ((moduleId, key, value) => {
    if (typeof globalThis.setModuleParam === 'function') {
      globalThis.setModuleParam(moduleId, key, value);
    }
  });

  function safe(value) {
    return escHtml ? escHtml(String(value ?? '')) : String(value ?? '');
  }

  function bool(value) {
    if (typeof value === 'boolean') return value;
    if (typeof value === 'string') return value.toLowerCase() === 'true';
    return Boolean(value);
  }

  function statusTone(state) {
    if (state?.error) return 'error';
    return bool(state?.active) ? 'ok' : 'idle';
  }

  function nodeLabel(state) {
    const node = state?.current_node || null;
    if (!node) return 'Current Search';
    return node.name || node.node_id || 'Current Search';
  }

  function renderNodeList(nodes = []) {
    const list = Array.isArray(nodes) && nodes.length
      ? nodes
      : [{node_id: 'node.default', name: 'Current Search', source: 'current_search'}];
    return list.map((node, index) => `
      <div class="event-stream-node">
        <span class="event-stream-node-index">${index + 1}</span>
        <span class="event-stream-node-name">${safe(node.name || node.node_id || 'Node')}</span>
        <span class="event-stream-node-source">${safe(node.source || 'current_search')}</span>
      </div>
    `).join('');
  }

  function render(state = {}) {
    currentState = state;
    if (!moduleBody) return;
    const active = bool(state.active);
    const tone = statusTone(state);
    const runId = state.run_id || '-';
    const frameIndex = Number.isFinite(Number(state.frame_index)) ? Number(state.frame_index) : 0;
    const nodeCount = Number.isFinite(Number(state.node_count)) ? Number(state.node_count) : 0;
    const traceCount = Number.isFinite(Number(state.trace_count)) ? Number(state.trace_count) : 0;

    moduleBody.innerHTML = `
      <div class="event-stream-panel" data-event-stream-panel>
        <div class="event-stream-head">
          <div>
            <div class="event-stream-kicker">EVENT STREAM</div>
            <div class="event-stream-title">${active ? 'Active' : 'Inactive'}</div>
          </div>
          <label class="event-stream-main-toggle">
            <input id="eventStreamActiveCheck" type="checkbox" ${active ? 'checked' : ''}>
            <span>이벤트 스트림 활성</span>
          </label>
        </div>

        <div class="event-stream-status" data-tone="${tone}">
          <span>${active ? 'ON' : 'OFF'}</span>
          <strong>${safe(nodeLabel(state))}</strong>
        </div>

        <div class="event-stream-grid">
          <div class="event-stream-field"><span>Run</span><strong>${safe(runId)}</strong></div>
          <div class="event-stream-field"><span>Frame</span><strong>${frameIndex}</strong></div>
          <div class="event-stream-field"><span>Nodes</span><strong>${nodeCount || 1}</strong></div>
          <div class="event-stream-field"><span>Trace</span><strong>${traceCount}</strong></div>
        </div>

        <div class="event-stream-section">
          <div class="event-stream-section-title">Freeze</div>
          <div class="event-stream-freeze-list">
            <span>Wildcard</span>
            <span>Character</span>
            <span>Prompt Eng.</span>
          </div>
        </div>

        <div class="event-stream-section">
          <div class="event-stream-section-title">Node Sequence</div>
          <div class="event-stream-node-list">
            ${renderNodeList(state.nodes)}
          </div>
        </div>

        <div class="event-stream-actions">
          <button type="button" class="mod-btn-secondary" id="eventStreamRestartBtn">기본 시퀀스 재시작</button>
        </div>
      </div>
    `;
  }

  function bind() {
    document.addEventListener('change', event => {
      if (event.target?.id !== 'eventStreamActiveCheck') return;
      sendModuleParam('event_stream', 'active', String(Boolean(event.target.checked)));
    });
    document.addEventListener('click', event => {
      if (event.target?.id !== 'eventStreamRestartBtn') return;
      sendModuleParam('event_stream', 'restart', '1');
    });
  }

  bind();

  return {
    render,
    setState(state = {}) {
      currentState = state;
      if (document.querySelector('[data-event-stream-panel]')) render(state);
    },
    getState() {
      return currentState;
    },
  };
}
