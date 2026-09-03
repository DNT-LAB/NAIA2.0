export function createTokenDisplay({
  promptEdit,
  negEdit,
  promptTokenLabel,
  negativeTokenLabel,
  modeSelect,
  getCurrentMode,
  // 지금 고른 NAI 모델이 V5 인가. ⚠️ 판정을 여기서 다시 짜지 않는다 - 호스트의
  //    `naiModelIsV5()` 하나가 답한다(사용자 등록 모델도 그것으로 갈린다).
  isNaiV5 = () => false,
}) {
  let lastCharacterTokenCount = 0;
  let lastCharacterPromptText = '';
  let lastMainTokenCount = null;
  let lastMainTokenSourceText = '';
  let lastMainTokenMode = '';
  let lastNegativeTokenCount = null;
  let lastNegativeTokenSourceText = '';
  let lastNegativeTokenMode = '';

  function currentMode() {
    return getCurrentMode() || modeSelect.value || 'NAI';
  }

  function cleanPromptForTokenEstimate(text, mode) {
    let cleaned = (text || '')
      .split(',')
      .map(part => part.trim())
      .filter(part => part && !part.startsWith('#'))
      .join(', ');
    if (mode === 'NAI') {
      cleaned = cleaned.replace(/-?\d+(?:\.\d+)?::/g, '').replace(/::/g, '');
    } else if (mode === 'WEBUI' || mode === 'COMFYUI') {
      cleaned = cleaned
        .replace(/\\[()]/g, ' ')
        .replace(/\(([^()]+?)(?::[+-]?\d*\.?\d+)?\)/g, '$1');
    }
    return cleaned.replace(/\s+/g, ' ').replace(/\s+,/g, ',').replace(/,+/g, ',').trim();
  }

  function estimateTokenCount(text, mode) {
    const cleaned = cleanPromptForTokenEstimate(text, mode);
    if (!cleaned) return 0;
    const base = Math.ceil(cleaned.length / 5);
    const correction = mode === 'NAI' ? 1.12 : 0.99;
    return Math.max(1, Math.ceil(base * correction));
  }

  // V5 에서만 짧게 쓴다(사용자 지정 2026-09-01). 이 줄이 길어서 옆에 무엇도 못 놓는
  // 상태였고, 자리를 만드는 것이 목적이었다.
  // ⚠️ 2026-09-03: 속칭 `M`·`C` 는 **다시 `Main`·`Char`** 다(사용자 지정). 한 글자는
  //    아낀 폭에 비해 읽는 값이 너무 컸다.
  // ⚠️ 이름 뒤의 **콜론은 뺀다.** `(Main : 153, Char : 0)` 은 1280x720 에서 237px 인데
  //    자리가 235px 라 `Char : …` 로 **값이 잘려 나갔다**(실측). 콜론 둘을 빼면 211px 로
  //    24px 이 남고 세 자리(224px)까지 들어간다. 긴 이름 쪽도 원래 콜론이 없다.
  // ⚠️ V5 **만** 이다. 다른 모드/모델은 익숙한 긴 이름을 그대로 둔다.
  function formatPromptTokenLabel(main, character, mode) {
    if (mode === 'NAI') {
      if (isNaiV5()) {
        return `E.tokens : ${main + character} (Main ${main}, Char ${character})`;
      }
      return `Estimated Tokens : ${main + character} (Main ${main} + Character ${character})`;
    }
    return `Estimated Tokens : ${main}`;
  }

  function formatNegativeTokenLabel(count) {
    return `Estimated Tokens : ${count}`;
  }

  function updateNegativeTokenEstimate() {
    if (!negativeTokenLabel) return;
    const mode = currentMode();
    const hasExactNegative = lastNegativeTokenCount !== null
      && lastNegativeTokenSourceText === negEdit.value
      && lastNegativeTokenMode === mode;
    const negative = hasExactNegative ? lastNegativeTokenCount : estimateTokenCount(negEdit.value, mode);
    negativeTokenLabel.textContent = formatNegativeTokenLabel(negative);
  }

  function updatePromptTokenEstimate() {
    const mode = currentMode();
    if (promptTokenLabel) {
      const hasExactMain = lastMainTokenCount !== null
        && lastMainTokenSourceText === promptEdit.value
        && lastMainTokenMode === mode;
      const main = hasExactMain ? lastMainTokenCount : estimateTokenCount(promptEdit.value, mode);
      const character = mode === 'NAI'
        ? (lastCharacterTokenCount || estimateTokenCount(lastCharacterPromptText, mode))
        : 0;
      promptTokenLabel.textContent = formatPromptTokenLabel(main, character, mode);
    }
    updateNegativeTokenEstimate();
  }

  function applyNegativeTokenPayload(message) {
    if (!negativeTokenLabel) return;
    if (Number.isFinite(Number(message.negative_token_count))) {
      const mode = currentMode();
      lastNegativeTokenCount = Number(message.negative_token_count);
      lastNegativeTokenSourceText = typeof message.negative_prompt === 'string' ? message.negative_prompt : negEdit.value;
      lastNegativeTokenMode = mode;
      negativeTokenLabel.textContent = formatNegativeTokenLabel(lastNegativeTokenCount);
      return;
    }
    updateNegativeTokenEstimate();
  }

  function applyPromptTokenPayload(message) {
    applyNegativeTokenPayload(message);
    if (!promptTokenLabel) return;
    if (message.prompt_token_label) {
      promptTokenLabel.textContent = message.prompt_token_label;
      if (message.prompt_token_counts) {
        if (Number.isFinite(Number(message.prompt_token_counts.main))) {
          lastMainTokenCount = Number(message.prompt_token_counts.main);
          lastMainTokenSourceText = typeof message.prompt === 'string' ? message.prompt : promptEdit.value;
          lastMainTokenMode = currentMode();
        }
        if (Number.isFinite(Number(message.prompt_token_counts.character))) {
          lastCharacterTokenCount = Number(message.prompt_token_counts.character);
        }
      }
      return;
    }
    if (message.prompt_token_counts) {
      const counts = message.prompt_token_counts;
      const main = Number(counts.main) || 0;
      const character = Number(counts.character) || 0;
      lastMainTokenCount = main;
      lastMainTokenSourceText = typeof message.prompt === 'string' ? message.prompt : promptEdit.value;
      lastMainTokenMode = currentMode();
      lastCharacterTokenCount = character;
      promptTokenLabel.textContent = formatPromptTokenLabel(main, character, currentMode());
      return;
    }
    updatePromptTokenEstimate();
  }

  function invalidatePromptCounts() {
    lastMainTokenCount = null;
    lastNegativeTokenCount = null;
  }

  function setCharacterPromptText(value) {
    lastCharacterPromptText = value;
  }

  function setCharacterTokenCount(value) {
    lastCharacterTokenCount = value;
  }

  return {
    cleanPromptForTokenEstimate,
    estimateTokenCount,
    updateNegativeTokenEstimate,
    updatePromptTokenEstimate,
    applyNegativeTokenPayload,
    applyPromptTokenPayload,
    invalidatePromptCounts,
    setCharacterPromptText,
    setCharacterTokenCount,
  };
}
