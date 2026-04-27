export function createConditionalPromptPanel({
  document,
  escHtml,
  getSharedMode,
  getSharedCond,
  setSharedCond,
  saveSharedSession,
  onModTextEdit,
}) {
  const moduleBody = document.getElementById('modulePopupBody');

  function formatLog(log) {
    if (!log) return '<span style="color:var(--text-dim)">No log yet</span>';
    return escHtml(log).split('\n').map(line => {
      if (!line.trim()) return '';
      if (line.includes('Condition Not Met') || line.includes('Error:')) {
        return `<div style="color:#888">${line}</div>`;
      }
      if (line.includes('Condition Met')) {
        return `<div style="color:#4CAF50">${line}</div>`;
      }
      if (line.startsWith('===')) {
        return `<div style="color:#fff;font-weight:bold">${line}</div>`;
      }
      return `<div>${line}</div>`;
    }).join('');
  }

  function formatRules(text) {
    if (!text) return '<br>';
    return text.split('\n').map(line => {
      if (!line) return '<div class="cond-line"> </div>';
      let result = '';
      let i = 0;
      let inQuote = false;
      let segStart = 0;
      while (i <= line.length) {
        if (i < line.length && line[i] === '"') inQuote = !inQuote;
        if (i === line.length || (line[i] === ',' && !inQuote)) {
          const seg = line.substring(segStart, i);
          const comma = i < line.length ? ',' : '';
          const esc = escHtml(seg);
          if (seg.trimStart().startsWith('#')) {
            result += `<span class="cond-comment">${esc}</span>${escHtml(comma)}`;
          } else {
            result += esc + escHtml(comma);
          }
          segStart = i + 1;
        }
        i++;
      }
      return `<div class="cond-line">${result || ' '}</div>`;
    }).join('') + '<br>';
  }

  function onRulesInput(element) {
    const highlight = document.getElementById('condRulesHighlight');
    if (highlight) highlight.innerHTML = formatRules(element.value);
    onModTextEdit('conditional_prompt', 'rules', element.value);
  }

  function syncScroll(element) {
    const highlight = document.getElementById('condRulesHighlight');
    if (highlight) {
      highlight.scrollTop = element.scrollTop;
      highlight.scrollLeft = element.scrollLeft;
    }
  }

  function render(state) {
    const m = state;
    if (getSharedMode()) {
      const sharedCond = getSharedCond();
      if (sharedCond) {
        if (sharedCond.enabled != null) m.enabled = sharedCond.enabled;
        if (sharedCond.rules != null) m.rules = sharedCond.rules;
      }
      setSharedCond({ enabled: !!m.enabled, rules: m.rules || '' });
      saveSharedSession();
    }
    moduleBody.innerHTML = `
      <div>
        <label class="mod-checkbox-item">
          <input type="checkbox" ${m.enabled ? 'checked' : ''} oninput="setModuleParam('conditional_prompt','enabled',String(this.checked))">
          <span class="mod-checkbox-label">Enable Conditional Prompt</span>
        </label>
      </div>
      <div>
        <div class="mod-section-label">Rules</div>
        <div class="cond-rules-wrap">
          <div class="cond-rules-highlight" id="condRulesHighlight">${formatRules(m.rules)}</div>
          <textarea class="mod-textarea cond-rules-input" id="condRulesInput" placeholder="(condition):action&#10;# comment lines ignored" oninput="onCondRulesInput(this)" onscroll="syncCondScroll(this)">${escHtml(m.rules)}</textarea>
        </div>
      </div>
      <div>
        <div class="mod-section-label mod-collapsible" onclick="this.classList.toggle('open');this.nextElementSibling.classList.toggle('collapsed')">
          Syntax Guide <span class="mod-collapse-arrow">▶</span>
        </div>
        <div class="collapsed" style="font-size:10px;color:var(--text-dim);line-height:1.5;padding:6px 0">
          <b>Condition:</b> tag, ~tag (NOT), *tag (exact), e|q|s|g (rating)<br>
          <b>Logic:</b> &amp; (AND), | (OR), () grouping<br>
          <b>Actions:</b><br>
          &nbsp; tag=new_tag (replace)<br>
          &nbsp; main+=tag (append to main)<br>
          &nbsp; prefix+=tag / postfix+=tag<br>
          &nbsp; ^ = multi-tag separator<br>
          &nbsp; "quoted, tags" for comma values<br>
          <b>Example:</b> (e):prefix+=nsfw^rating:explicit,
        </div>
      </div>
      <div>
        <button class="mod-action-btn mod-start" onclick="setModuleParam('conditional_prompt','test','1')">Test Rules</button>
      </div>
      <div>
        <div class="mod-section-label">Execution Log</div>
        <div class="mod-log-viewer" id="condLogViewer">${formatLog(m.log)}</div>
      </div>
    `;
  }

  return {
    formatLog,
    formatRules,
    onRulesInput,
    syncScroll,
    render,
  };
}
