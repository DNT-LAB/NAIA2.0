export function createOllamaPanel({
  document,
  escHtml,
  setModuleParam,
  bindTagAssist,
  showToast,
}) {
  const moduleBody = document.getElementById('modulePopupBody');
  let lastState = null;

  function attr(value) {
    return escHtml(String(value ?? ''));
  }

  function renderModelOption(model, selected, availableModels) {
    const available = availableModels.includes(model) || availableModels.some(item => item.split(':')[0] === model.split(':')[0]);
    return `<option value="${attr(model)}" ${model === selected ? 'selected' : ''}>${escHtml(model)}${available ? ' *' : ''}</option>`;
  }

  function renderCreativityOption(option, selected) {
    const value = Number(option.value);
    return `<option value="${value}" ${value === Number(selected) ? 'selected' : ''}>${value.toFixed(1)} - ${escHtml(option.label)}</option>`;
  }

  function renderStages(stages) {
    if (!stages || !stages.length) return '<div class="mod-empty">No debug output</div>';
    return stages.map(stage => `<details class="ollama-stage">
      <summary>${escHtml(stage.stage || '')}</summary>
      <pre>${escHtml(stage.content || '')}</pre>
    </details>`).join('');
  }

  function bindRenderedInputs() {
    const input = document.getElementById('ollamaInput');
    if (input && bindTagAssist) bindTagAssist(input);
  }

  function render(state) {
    lastState = state;
    const availableModels = state.available_models || [];
    const supportedModels = state.supported_models || [];
    const modelOptions = supportedModels.map(model => renderModelOption(model, state.selected_model, availableModels)).join('');
    const creativityOptions = (state.creativity_options || []).map(option => renderCreativityOption(option, state.creativity)).join('');
    const statusClass = state.server_running ? 'online' : (state.installed ? 'idle' : 'offline');
    const statusText = state.server_running
      ? `Server online (${availableModels.length} models)`
      : (state.installed ? 'Installed / server off' : 'Ollama not installed');
    const canConvert = state.server_running && !state.is_running;

    moduleBody.innerHTML = `
      <div class="ollama-panel">
        <div class="ollama-status-card ${statusClass}">
          <div>
            <strong>${escHtml(statusText)}</strong>
            <small>${escHtml(state.status || '')}</small>
          </div>
          <div class="ollama-status-actions">
            <button class="mod-btn-sm" onclick="ollamaRefresh()">Refresh</button>
            <button class="mod-btn-sm" onclick="ollamaServerAction('${state.server_running ? 'stop' : 'start'}')" ${state.installed ? '' : 'disabled'}>${state.server_running ? 'Stop' : 'Start'}</button>
          </div>
        </div>

        <div class="ollama-grid">
          <label class="mod-field">
            <span class="mod-field-label">Model</span>
            <select class="mod-select" onchange="setModuleParam('ollama','model',this.value)">${modelOptions}</select>
          </label>
          <label class="mod-field">
            <span class="mod-field-label">Creativity</span>
            <select class="mod-select" onchange="setModuleParam('ollama','creativity',this.value)">${creativityOptions}</select>
          </label>
        </div>

        <div class="ollama-options">
          <label class="mod-checkbox-item">
            <input type="checkbox" ${state.load_model ? 'checked' : ''} oninput="setModuleParam('ollama','load_model',String(this.checked))" ${state.server_running ? '' : 'disabled'}>
            <span class="mod-checkbox-label">LOAD</span>
          </label>
          <label class="mod-checkbox-item">
            <input type="checkbox" ${state.auto_offload ? 'checked' : ''} oninput="setModuleParam('ollama','auto_offload',String(this.checked))">
            <span class="mod-checkbox-label">Auto offload</span>
          </label>
          <label class="mod-checkbox-item">
            <input type="checkbox" ${state.e621_nsfw_boost ? 'checked' : ''} oninput="setModuleParam('ollama','e621_nsfw_boost',String(this.checked))">
            <span class="mod-checkbox-label">e621 NSFW Boost</span>
          </label>
          <span class="ollama-tagdb">${state.tag_db_loaded ? `${state.tag_count} tags` : 'Tag DB not loaded'}</span>
        </div>

        <div class="mod-section-label">Natural Language Prompt</div>
        <textarea class="mod-textarea mod-textarea-lg" id="ollamaInput" oninput="ollamaInputChanged(this)">${escHtml(state.input || '')}</textarea>

        <div class="ollama-actions">
          <button class="mod-action-btn mod-start" onclick="ollamaConvert()" ${canConvert ? '' : 'disabled'}>${state.is_running ? 'Running...' : 'Convert'}</button>
          <button class="mod-btn-sm" onclick="ollamaCancel()" ${state.is_running ? '' : 'disabled'}>Cancel</button>
          <button class="mod-btn-sm" onclick="ollamaCopyOutput()" ${state.output ? '' : 'disabled'}>Copy Output</button>
        </div>

        <div class="ollama-progress">
          <div class="ollama-progress-bar" style="width:${Math.max(0, Math.min(100, state.progress || 0))}%"></div>
        </div>

        <div class="mod-section-label">Converted Tag Prompt</div>
        <textarea class="mod-textarea mod-textarea-lg" id="ollamaOutput" readonly>${escHtml(state.output || '')}</textarea>

        <div class="mod-section-label">Debug Stages</div>
        <div class="ollama-stage-list">${renderStages(state.stages)}</div>
      </div>
    `;
    bindRenderedInputs();
  }

  function refresh() {
    setModuleParam('ollama', 'refresh', '1');
  }

  function serverAction(action) {
    setModuleParam('ollama', 'server_action', action);
  }

  function inputChanged(element) {
    setModuleParam('ollama', 'input', element.value);
  }

  function convert() {
    const input = document.getElementById('ollamaInput');
    const value = input ? input.value.trim() : '';
    if (!value) {
      if (showToast) showToast('Ollama prompt is empty', 'error');
      return;
    }
    setModuleParam('ollama', 'convert', value);
  }

  function cancel() {
    setModuleParam('ollama', 'cancel', '1');
  }

  function copyOutput() {
    setModuleParam('ollama', 'copy_output', '1');
  }

  return {
    render,
    refresh,
    serverAction,
    inputChanged,
    convert,
    cancel,
    copyOutput,
  };
}
