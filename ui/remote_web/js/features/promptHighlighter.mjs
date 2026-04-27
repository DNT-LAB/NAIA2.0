const ENABLE_PREVIEW = true;
const SUPPORTED_MODES = new Set(['NAI', 'WEBUI', 'COMFYUI']);

export function createPromptHighlighter({document, promptEdit, escHtml}) {
  const highlight = document.getElementById('promptHighlight');
  const wrap = highlight ? highlight.parentElement : null;
  let mode = '';
  let state = 'disabled';

  function supports(nextMode = mode) {
    return SUPPORTED_MODES.has(nextMode);
  }

  function formatNai(text) {
    if (!text) return '<br>';
    let html = '';
    let pos = 0;
    const re = /(-?\d+(?:\.\d+)?)(::)([\s\S]*?)(::)/g;
    let match;
    while ((match = re.exec(text)) !== null) {
      html += escHtml(text.substring(pos, match.index));
      const weight = parseFloat(match[1]);
      const cls = weight < 1.0 ? 'nai-wt-blue' : weight > 1.0 ? 'nai-wt-red' : '';
      const mark = '<span class="nai-wt-mark">::</span>';
      if (cls) {
        html += `<span class="${cls}"><span class="nai-wt-open">${escHtml(match[1])}</span>${mark}${escHtml(match[3])}${mark}</span>`;
      } else {
        html += escHtml(match[1]) + mark + escHtml(match[3]) + mark;
      }
      pos = match.index + match[0].length;
    }
    html += escHtml(text.substring(pos));
    return html + '<br>';
  }

  function matchWebAngleToken(text, index) {
    if (text[index] !== '<') return null;
    const end = text.indexOf('>', index + 1);
    if (end === -1) return null;
    const token = text.substring(index, end + 1);
    return /^<(?:lora|lyco|hypernet|embedding):[^>\n]+>$/.test(token) ? token : null;
  }

  function formatWebSegment(text, index = 0, closingChar = '', depth = 0) {
    let html = '';
    let cursor = index;
    let explicitWeight = null;
    while (cursor < text.length) {
      const ch = text[cursor];

      if (closingChar && ch === closingChar) {
        return {html, index: cursor + 1, closed: true, explicitWeight};
      }

      if (ch === '\\' && cursor + 1 < text.length) {
        html += `<span class="webui-escape">${escHtml(text.substring(cursor, cursor + 2))}</span>`;
        cursor += 2;
        continue;
      }

      const angleToken = matchWebAngleToken(text, cursor);
      if (angleToken) {
        html += `<span class="webui-angle">${escHtml(angleToken)}</span>`;
        cursor += angleToken.length;
        continue;
      }

      if (ch === '(' || ch === '[') {
        const close = ch === '(' ? ')' : ']';
        let tone = ch === '(' ? 'webui-up' : 'webui-down';
        const depthClass = `webui-depth-${(depth % 3) + 1}`;
        const inner = formatWebSegment(text, cursor + 1, close, depth + 1);
        if (ch === '(' && inner.explicitWeight != null) {
          tone = inner.explicitWeight < 1 ? 'webui-down' : inner.explicitWeight > 1 ? 'webui-up' : 'webui-neutral';
        }
        const openBracket = `<span class="webui-bracket ${tone}-bracket">${escHtml(ch)}</span>`;
        if (inner.closed) {
          const closeBracket = `<span class="webui-bracket ${tone}-bracket">${escHtml(close)}</span>`;
          html += `<span class="webui-group ${tone} ${depthClass}">${openBracket}${inner.html}${closeBracket}</span>`;
        } else {
          html += `${openBracket}${inner.html}`;
        }
        cursor = inner.index;
        continue;
      }

      if (closingChar === ')' && ch === ':') {
        const weightMatch = text.slice(cursor).match(/^:\s*-?(?:\d+(?:\.\d+)?|\.\d+)(?=\))/);
        if (weightMatch) {
          const weightText = weightMatch[0];
          const weightValue = parseFloat(weightText.slice(1));
          explicitWeight = weightValue;
          const tone = weightValue < 1 ? 'webui-weight-down' : weightValue > 1 ? 'webui-weight-up' : 'webui-weight-neutral';
          html += `<span class="webui-weight ${tone}">${escHtml(weightText)}</span>`;
          cursor += weightText.length;
          continue;
        }
      }

      if (!closingChar && (ch === ')' || ch === ']')) {
        const tone = ch === ')' ? 'webui-up-bracket' : 'webui-down-bracket';
        html += `<span class="webui-bracket ${tone}">${escHtml(ch)}</span>`;
        cursor += 1;
        continue;
      }

      html += escHtml(ch);
      cursor += 1;
    }

    return {html, index: cursor, closed: false, explicitWeight};
  }

  function formatWeb(text) {
    if (!text) return '<br>';
    return formatWebSegment(text).html + '<br>';
  }

  function format(text, nextMode = mode) {
    if (nextMode === 'NAI') return formatNai(text);
    if (nextMode === 'WEBUI' || nextMode === 'COMFYUI') return formatWeb(text);
    return escHtml(text || '') + '<br>';
  }

  function syncScroll() {
    if (highlight && state !== 'disabled') {
      highlight.scrollTop = promptEdit.scrollTop;
      highlight.scrollLeft = promptEdit.scrollLeft;
    }
  }

  function update() {
    if (!highlight || !supports()) return;
    highlight.innerHTML = format(promptEdit.value);
    if (state !== 'disabled') syncScroll();
  }

  function desiredState() {
    if (!ENABLE_PREVIEW || !wrap || !supports()) return 'disabled';
    return document.activeElement === promptEdit ? 'editing' : 'preview';
  }

  function applyState() {
    if (!wrap) return;
    state = desiredState();
    wrap.classList.toggle('nai-preview', state === 'preview');
    wrap.classList.toggle('is-editing', state === 'editing');
    if (state === 'preview') update();
  }

  function setMode(nextMode) {
    mode = nextMode;
    applyState();
  }

  return {
    setMode,
    update,
    syncScroll,
    applyState,
    format,
  };
}
