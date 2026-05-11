const ENABLE_PREVIEW = true;
const SUPPORTED_MODES = new Set(['NAI', 'WEBUI', 'COMFYUI']);
const EMPTY_SET = new Set();
const NAMESPACE_RE = /^(artist|character|copyright|general|meta):(.+)$/i;
const NAI_WEIGHT_PREFIX_RE = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)::\s*/;
const NAI_WEIGHT_SUFFIX_RE = /\s*::\s*$/;
const PRESET_TOKEN_STYLES = [
  {prefix: 'preset:events', className: 'prompt-token-preset-events'},
  {prefix: 'preset:clothes', className: 'prompt-token-preset-clothes'},
  {prefix: 'preset:expressions', className: 'prompt-token-preset-expressions'},
];

function makeLookupSet(values) {
  if (!values) return EMPTY_SET;
  if (values instanceof Set) {
    return new Set([...values].map(normalizeTagLookup).filter(Boolean));
  }
  if (Array.isArray(values)) {
    return new Set(values.map(normalizeTagLookup).filter(Boolean));
  }
  if (typeof values === 'object') {
    return new Set(Object.keys(values).map(normalizeTagLookup).filter(Boolean));
  }
  return EMPTY_SET;
}

function normalizeTagLookup(value) {
  return String(value || '')
    .replace(/\\([()])/g, '$1')
    .replace(/_/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();
}

export function normalizePromptTagToken(raw) {
  let text = String(raw || '').trim();
  if (!text) return null;
  if (text.startsWith('#')) {
    return {tag: text, namespace: 'comment', isComment: true};
  }

  while (NAI_WEIGHT_PREFIX_RE.test(text)) {
    text = text.replace(NAI_WEIGHT_PREFIX_RE, '').trim();
  }
  text = text.replace(NAI_WEIGHT_SUFFIX_RE, '').trim();

  if (!text || text.startsWith('$') || text.startsWith('__')) return null;

  let namespace = '';
  if (text.startsWith('@')) {
    namespace = 'artist';
    text = text.slice(1).trim();
  } else {
    const namespaceMatch = text.match(NAMESPACE_RE);
    if (namespaceMatch) {
      namespace = namespaceMatch[1].toLowerCase();
      text = namespaceMatch[2].trim();
    }
  }

  const tag = normalizeTagLookup(text);
  return tag ? {tag, namespace, isComment: false} : null;
}

export function createPromptTagClassifier(index = {}) {
  let highValueTags = makeLookupSet(index.highValueTags);
  let midValueTags = makeLookupSet(index.midValueTags);
  let knownTags = makeLookupSet(index.knownTags);
  let artistTags = makeLookupSet(index.artistTags);
  let characterTags = makeLookupSet(index.characterTags);
  let copyrightTags = makeLookupSet(index.copyrightTags);

  function setIndex(nextIndex = {}) {
    highValueTags = makeLookupSet(nextIndex.highValueTags);
    midValueTags = makeLookupSet(nextIndex.midValueTags);
    knownTags = makeLookupSet(nextIndex.knownTags);
    artistTags = makeLookupSet(nextIndex.artistTags);
    characterTags = makeLookupSet(nextIndex.characterTags);
    copyrightTags = makeLookupSet(nextIndex.copyrightTags);
  }

  function classify(raw) {
    const parsed = normalizePromptTagToken(raw);
    if (!parsed) return {kind: 'plain', className: ''};
    if (parsed.isComment) return {kind: 'comment', className: 'prompt-token-comment'};

    const {tag, namespace} = parsed;
    if (namespace === 'artist' || artistTags.has(tag)) {
      return {kind: 'artist', className: 'prompt-token-artist', tag};
    }
    if (namespace === 'character' || characterTags.has(tag)) {
      return {kind: 'character', className: 'prompt-token-character', tag};
    }
    if (namespace === 'copyright' || copyrightTags.has(tag)) {
      return {kind: 'copyright', className: 'prompt-token-copyright', tag};
    }
    if (highValueTags.has(tag)) {
      return {kind: 'high', className: 'prompt-token-high', tag};
    }
    if (midValueTags.has(tag)) {
      return {kind: 'mid', className: 'prompt-token-mid', tag};
    }
    if (/^year \d{4}$/.test(tag)) {
      return {kind: 'low', className: 'prompt-token-low', tag};
    }
    if (knownTags.has(tag)) {
      return {kind: 'low', className: 'prompt-token-low', tag};
    }
    return {kind: 'unknown', className: 'prompt-token-unknown', tag};
  }

  function summarize(text) {
    const counts = {plain: 0, comment: 0, artist: 0, character: 0, copyright: 0, high: 0, mid: 0, low: 0, unknown: 0};
    splitPromptTextForClassification(text).forEach(token => {
      const result = classify(token);
      counts[result.kind] = (counts[result.kind] || 0) + 1;
    });
    return counts;
  }

  return {
    classify,
    setIndex,
    summarize,
  };
}

export function splitPromptTextForClassification(text) {
  return String(text || '')
    .split(/[,\n]/)
    .map(part => part.trim())
    .filter(Boolean);
}

function presetTokenStyle(core) {
  const text = String(core || '');
  const lower = text.toLowerCase();
  return PRESET_TOKEN_STYLES.find(style => {
    if (!lower.startsWith(style.prefix)) return false;
    const next = lower[style.prefix.length] || '';
    return !next || next === '/' || next === '(' || next === '&';
  }) || null;
}

function matchPresetPromptToken(text, index) {
  const previous = index > 0 ? text[index - 1] : '';
  if (previous && !/[\s,([{]/.test(previous)) return null;
  if (!presetTokenStyle(String(text || '').slice(index))) return null;
  let end = text.length;
  for (let cursor = index; cursor < text.length; cursor += 1) {
    if (text[cursor] === ',' || text[cursor] === '\n') {
      end = cursor;
      break;
    }
  }
  return text.substring(index, end);
}

export function createPromptHighlighter({document, promptEdit, escHtml}) {
  const highlight = document.getElementById('promptHighlight');
  const wrap = highlight ? highlight.parentElement : null;
  const tagClassifier = createPromptTagClassifier();
  let mode = '';
  let state = 'disabled';

  function supports(nextMode = mode) {
    return SUPPORTED_MODES.has(nextMode);
  }

  function formatTaggedText(text) {
    if (!text) return '';
    let html = '';
    let start = 0;
    const re = /[,\n]/g;
    let match;
    while ((match = re.exec(text)) !== null) {
      html += formatTagTokenSegment(text.substring(start, match.index));
      html += escHtml(match[0]);
      start = match.index + match[0].length;
    }
    html += formatTagTokenSegment(text.substring(start));
    return html;
  }

  function formatTagTokenSegment(segment) {
    if (!segment) return '';
    const leading = segment.match(/^\s*/)?.[0] || '';
    const trailing = segment.match(/\s*$/)?.[0] || '';
    const core = segment.substring(leading.length, segment.length - trailing.length);
    if (!core) return escHtml(segment);
    const presetStyle = presetTokenStyle(core);
    if (presetStyle) {
      return escHtml(leading) +
        formatPresetPromptToken(core, presetStyle) +
        escHtml(trailing);
    }
    const classification = tagClassifier.classify(core);
    if (!classification.className) return escHtml(segment);
    return escHtml(leading) +
      `<span class="${classification.className}">${escHtml(core)}</span>` +
      escHtml(trailing);
  }

  function formatPresetPromptToken(core, presetStyle) {
    const splitIndex = (() => {
      const slash = core.indexOf('/');
      const amp = core.indexOf('&');
      if (slash < 0) return amp < 0 ? core.length : amp;
      if (amp < 0) return slash;
      return Math.min(slash, amp);
    })();
    const head = core.substring(0, splitIndex);
    const tail = core.substring(splitIndex);
    const contextIndex = head.indexOf('(');
    const axis = contextIndex >= 0 ? head.substring(0, contextIndex) : head;
    const context = contextIndex >= 0 ? head.substring(contextIndex) : '';
    return `<span class="${presetStyle.className} prompt-token-preset-axis">${escHtml(axis)}</span>` +
      (context ? `<span class="prompt-token-preset-context">${escHtml(context)}</span>` : '') +
      formatPresetTail(tail, presetStyle.className);
  }

  function formatPresetTail(tail, axisClassName) {
    if (!tail) return '';
    let html = '';
    let start = 0;
    for (let index = 0; index < tail.length; index += 1) {
      const ch = tail[index];
      if (ch !== '/' && ch !== '&') continue;
      if (index > start) {
        html += `<span class="${axisClassName} prompt-token-preset-part">${escHtml(tail.substring(start, index))}</span>`;
      }
      html += `<span class="prompt-token-preset-separator">${escHtml(ch)}</span>`;
      start = index + 1;
    }
    if (start < tail.length) {
      html += `<span class="${axisClassName} prompt-token-preset-part">${escHtml(tail.substring(start))}</span>`;
    }
    return html;
  }

  function formatNai(text) {
    if (!text) return '<br>';
    let html = '';
    let pos = 0;
    const re = /([+-]?(?:\d+(?:\.\d*)?|\.\d+))(::)([\s\S]*?)(::)/g;
    let match;
    while ((match = re.exec(text)) !== null) {
      html += formatTaggedText(text.substring(pos, match.index));
      const weight = parseFloat(match[1]);
      const cls = weight < 1.0 ? 'nai-wt-blue' : weight > 1.0 ? 'nai-wt-red' : '';
      const mark = '<span class="nai-wt-mark">::</span>';
      const inner = formatTaggedText(match[3]);
      if (cls) {
        html += `<span class="${cls}"><span class="nai-wt-open">${escHtml(match[1])}</span>${mark}${inner}${mark}</span>`;
      } else {
        html += escHtml(match[1]) + mark + inner + mark;
      }
      pos = match.index + match[0].length;
    }
    html += formatTaggedText(text.substring(pos));
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
    let textBuffer = '';

    function flushTextBuffer() {
      if (!textBuffer) return;
      html += formatTaggedText(textBuffer);
      textBuffer = '';
    }

    while (cursor < text.length) {
      const ch = text[cursor];

      if (closingChar && ch === closingChar) {
        flushTextBuffer();
        return {html, index: cursor + 1, closed: true, explicitWeight};
      }

      if (ch === '\\' && cursor + 1 < text.length) {
        flushTextBuffer();
        html += `<span class="webui-escape">${escHtml(text.substring(cursor, cursor + 2))}</span>`;
        cursor += 2;
        continue;
      }

      const angleToken = matchWebAngleToken(text, cursor);
      if (angleToken) {
        flushTextBuffer();
        html += `<span class="webui-angle">${escHtml(angleToken)}</span>`;
        cursor += angleToken.length;
        continue;
      }

      const presetToken = matchPresetPromptToken(text, cursor);
      if (presetToken) {
        flushTextBuffer();
        html += formatTagTokenSegment(presetToken);
        cursor += presetToken.length;
        continue;
      }

      if (ch === '(' || ch === '[') {
        flushTextBuffer();
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
          flushTextBuffer();
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
        flushTextBuffer();
        const tone = ch === ')' ? 'webui-up-bracket' : 'webui-down-bracket';
        html += `<span class="webui-bracket ${tone}">${escHtml(ch)}</span>`;
        cursor += 1;
        continue;
      }

      textBuffer += ch;
      cursor += 1;
    }

    flushTextBuffer();
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

  function setTagClassificationIndex(index) {
    tagClassifier.setIndex(index);
    update();
  }

  return {
    setMode,
    setTagClassificationIndex,
    classifyPromptTag: tagClassifier.classify,
    summarizeTagClasses: tagClassifier.summarize,
    update,
    syncScroll,
    applyState,
    format,
  };
}
