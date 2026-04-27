export function createModuleBadges({
  document,
  getMode,
  estimateTokenCount,
  setCharacterPromptText,
  setCharacterTokenCount,
  updatePromptTokenEstimate,
}) {
  function updateAuto(m) {
    const btn = document.querySelector('.module-btn[data-module="automation"]');
    const badge = document.getElementById('badgeAuto');
    if (!badge || !btn) return;
    const isRunning = m.is_running;

    if (!isRunning) {
      badge.classList.add('hidden');
      btn.classList.remove('auto-active');
      return;
    }
    btn.classList.add('auto-active');
    badge.classList.remove('hidden');

    const delayInfo = m.delay_info || '';
    const repeatInfo = m.repeat_info || '';
    const status = m.status || '';

    if (delayInfo) {
      const dMatch = delayInfo.match(/([\d.]+)\s*s/i) || delayInfo.match(/([\d.:]+)/);
      badge.textContent = dMatch ? dMatch[1] : '\u2026';
    } else if (repeatInfo) {
      const rMatch = repeatInfo.match(/(\d+\/\d+)/);
      badge.textContent = rMatch ? rMatch[1] : '\u2026';
    } else {
      const numMatch = status.match(/(\d+[:/]?\d*)/);
      if (numMatch) badge.textContent = numMatch[1];
      else badge.classList.add('hidden');
    }
  }

  function updateCharacter(m) {
    const btn = document.querySelector('.module-btn[data-module="character"]');
    const badge = document.getElementById('badgeChar');
    if (!badge || !btn) return;

    const promptText = (m.processed_characters || []).filter(Boolean).join(' ');
    const tokenCount = Number.isFinite(Number(m.character_token_count))
      ? Number(m.character_token_count)
      : estimateTokenCount(promptText, getMode());

    setCharacterPromptText(promptText);
    setCharacterTokenCount(tokenCount);

    if (!m.activated) {
      setCharacterTokenCount(0);
      badge.classList.add('hidden');
      btn.classList.remove('char-active');
      updatePromptTokenEstimate();
      return;
    }

    const count = m.active_count || 0;
    btn.classList.add('char-active');
    badge.classList.remove('hidden');
    badge.classList.add('char');
    badge.textContent = count;
    updatePromptTokenEstimate();
  }

  function updateCharacterReference(m) {
    const btn = document.querySelector('.module-btn[data-module="character_reference"]');
    const badge = document.getElementById('badgeCharRef');
    if (!badge || !btn) return;

    const enabledCount = (m.frames || []).filter(frame => frame.is_enabled).length;
    if (!enabledCount) {
      badge.classList.add('hidden');
      btn.classList.remove('charref-active');
      return;
    }

    btn.classList.add('charref-active');
    badge.classList.remove('hidden');
    badge.textContent = enabledCount;
  }

  function updateVibe(m) {
    const btn = document.querySelector('.module-btn[data-module="vibe_transfer"]');
    const badge = document.getElementById('badgeVibe');
    if (!badge || !btn) return;

    const enabledCount = (m.frames || []).filter(frame => frame.is_enabled).length;
    if (!enabledCount) {
      badge.classList.add('hidden');
      btn.classList.remove('vibe-active');
      return;
    }

    btn.classList.add('vibe-active');
    badge.classList.remove('hidden');
    badge.textContent = enabledCount;
  }

  return {
    updateAuto,
    updateCharacter,
    updateCharacterReference,
    updateVibe,
  };
}
