export function createTokenDisplay({
  promptEdit,
  negEdit,
  promptTokenLabel,
  negativeTokenLabel,
  modeSelect,
  getCurrentMode,
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

  function formatPromptTokenLabel(main, character, mode) {
    if (mode === 'NAI') {
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
