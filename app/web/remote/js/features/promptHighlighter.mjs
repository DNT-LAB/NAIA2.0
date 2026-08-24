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

  // The overlay used to render the highlighted prompt as inline <span> tokens.
  // Problem: `word-break: break-all` breaks across inline-box boundaries
  // differently than across the <textarea>'s continuous plain text, so the span
  // overlay wrapped into MORE visual lines than the textarea — every line below
  // the divergence shifted, and clicks (which land on the transparent textarea)
  // hit a different character than the glyph the user saw. Verified: the SAME text
  // as a plain text node wraps identically to the textarea.
  // Fix: keep the existing tokenizer, but project its span markup onto PLAIN text
  // in the overlay and paint colours via the CSS Custom Highlight API (ranges add
  // zero layout). Falls back to the old span markup when the API is unavailable.
  const HIGHLIGHT_API = typeof Highlight !== 'undefined'
    && typeof CSS !== 'undefined' && CSS && !!CSS.highlights;
  let scratch = null;            // off-screen element; reuses format() to tokenize
  let dynamicStyle = null;       // holds the generated ::highlight() rules
  const registeredHighlightNames = [];

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
    // `-태그` 는 생성 직전에 **네거티브로 옮겨진다**
    // (headless_generation_service._expand_input_wildcards). 여기서 알려 주지 않으면
    // 사용자는 그 태그가 포지티브에 남아 있는 줄 안다(사용자 지적).
    // ⚠️ `::` 가 있으면 NAI 음수 가중치이지 이동이 아니다 - 백엔드와 같은 판정.
    if (core.length > 1 && core.startsWith('-') && !core.includes('::')) {
      return escHtml(leading) +
        `<span class="prompt-token-minus">${escHtml(core)}</span>` +
        escHtml(trailing);
    }
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

  function ensureScratch() {
    if (!scratch) {
      scratch = document.createElement('div');
      scratch.setAttribute('aria-hidden', 'true');
      // Off-screen but IN the document so getComputedStyle resolves token colours
      // from the cascade (.prompt-token-* / .nai-wt-* / .webui-* in style.css).
      scratch.style.cssText = 'position:absolute;left:-99999px;top:0;width:1px;'
        + 'height:1px;overflow:hidden;visibility:hidden;pointer-events:none;';
    }
    if (!scratch.isConnected && document.body) document.body.appendChild(scratch);
    if (!dynamicStyle) {
      dynamicStyle = document.createElement('style');
      dynamicStyle.setAttribute('data-prompt-highlight', 'dynamic');
      document.head.appendChild(dynamicStyle);
    }
  }

  function clearCustomHighlights() {
    if (!HIGHLIGHT_API) return;
    for (const name of registeredHighlightNames) CSS.highlights.delete(name);
    registeredHighlightNames.length = 0;
    if (dynamicStyle) dynamicStyle.textContent = '';
  }

  // Reuse the existing span tokenizer, then re-express it as plain text + painted
  // ranges so the overlay wraps exactly like the textarea (see note above).
  function paintWithHighlights(value) {
    ensureScratch();
    scratch.innerHTML = format(value);
    const walker = document.createTreeWalker(scratch, NodeFilter.SHOW_TEXT);
    let plain = '';
    const colorRanges = new Map();   // computed color   -> [[start,end], ...]
    const bgRanges = new Map();      // computed bgColor  -> {depth, spans:[...]}
    // `-태그`(네거티브로 빠지는 것)는 **취소선**으로 알린다. 색상(hue)은 이미 artist/
    // character/preset 이 나눠 갖고 있어 하나 더 끼면 서로 흐려진다 - 아무도 안 쓰는
    // 채널을 쓴다(사용자 지적: "아티스트 태그가 이미 붉은색을 점유").
    // ⚠️ `::highlight()` 가 `text-decoration` 을 받는지 이 런타임에서 실측 확인했다
    //    (Chrome 151: `text-decoration: line-through rgb(...)` 로 보존됨).
    const decoRanges = new Map();    // "line|color|thickness" -> [[start,end], ...]
    const styleCache = new Map();
    const computed = (el) => {
      let cs = styleCache.get(el);
      if (!cs) { cs = getComputedStyle(el); styleCache.set(el, cs); }
      return cs;
    };
    let node;
    while ((node = walker.nextNode())) {
      const start = plain.length;
      plain += node.nodeValue;
      const end = plain.length;
      if (end === start) continue;
      const parent = node.parentElement;
      if (parent && parent !== scratch) {
        const color = computed(parent).color;
        if (color) {
          let arr = colorRanges.get(color);
          if (!arr) { arr = []; colorRanges.set(color, arr); }
          arr.push([start, end]);
        }
        const line = computed(parent).textDecorationLine;
        if (line && line !== 'none') {
          const deco = {
            line,
            color: computed(parent).textDecorationColor || 'currentcolor',
            thickness: computed(parent).textDecorationThickness || 'auto',
          };
          // 값을 키에 이어 붙여 인코딩하지 않는다 - 구분자가 없으면 서로 다른 조합이
          // 같은 키가 될 수 있다. 키는 식별용이고 값은 레코드에 담는다.
          const key = `${deco.line}|${deco.color}|${deco.thickness}`;
          let rec = decoRanges.get(key);
          if (!rec) { rec = {...deco, spans: []}; decoRanges.set(key, rec); }
          rec.spans.push([start, end]);
        }
        let el = parent;
        let depth = 0;
        while (el && el !== scratch) {
          const bg = computed(el).backgroundColor;
          if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') {
            let rec = bgRanges.get(bg);
            if (!rec) { rec = {depth, spans: []}; bgRanges.set(bg, rec); }
            rec.spans.push([start, end]);
          }
          el = el.parentElement;
          depth += 1;
        }
      }
    }
    clearCustomHighlights();
    // Plain text MUST equal the textarea value so wrapping (and the caret) match.
    // If the tokenizer ever altered the text, fall back to span markup rather than
    // desync the caret.
    if (plain !== value) {
      highlight.innerHTML = format(value);
      return;
    }
    highlight.textContent = plain;
    const textNode = highlight.firstChild;
    if (!textNode) return;
    const makeRange = (s, e) => {
      const r = document.createRange();
      r.setStart(textNode, s);
      r.setEnd(textNode, e);
      return r;
    };
    let css = '';
    let ci = 0;
    for (const [color, spans] of colorRanges) {
      const name = 'naia-phc-' + ci;
      ci += 1;
      const h = new Highlight();
      for (const [s, e] of spans) h.add(makeRange(s, e));
      h.priority = 100;
      CSS.highlights.set(name, h);
      registeredHighlightNames.push(name);
      css += `::highlight(${name}){color:${color};}`;
    }
    let bi = 0;
    for (const [bg, rec] of bgRanges) {
      const name = 'naia-phb-' + bi;
      bi += 1;
      const h = new Highlight();
      for (const [s, e] of rec.spans) h.add(makeRange(s, e));
      h.priority = rec.depth;   // nested group backgrounds composite by depth
      CSS.highlights.set(name, h);
      registeredHighlightNames.push(name);
      css += `::highlight(${name}){background-color:${bg};}`;
    }
    let di = 0;
    for (const rec of decoRanges.values()) {
      const name = 'naia-phd-' + di;
      di += 1;
      const h = new Highlight();
      for (const [s, e] of rec.spans) h.add(makeRange(s, e));
      // 색·배경보다 위에 얹는다 - 선은 글자를 덮는 것이 아니라 함께 보여야 한다.
      h.priority = 200;
      CSS.highlights.set(name, h);
      registeredHighlightNames.push(name);
      css += `::highlight(${name}){text-decoration:${rec.line};`
        + `text-decoration-color:${rec.color};text-decoration-thickness:${rec.thickness};}`;
    }
    if (dynamicStyle) dynamicStyle.textContent = css;
  }

  function update() {
    if (!highlight || !supports()) return;
    if (HIGHLIGHT_API) paintWithHighlights(promptEdit.value);
    else highlight.innerHTML = format(promptEdit.value);
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
