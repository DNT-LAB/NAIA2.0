export function createModuleBadges({
  document,
  getMode,
  estimateTokenCount,
  setCharacterPromptText,
  setCharacterTokenCount,
  updatePromptTokenEstimate,
}) {
  const activatedSummary = document.getElementById('activatedSummary');
  const activatedFooter = document.getElementById('promptTokenFooter');
  const activatedWrap = activatedSummary ? activatedSummary.closest('.prompt-highlight-wrap') : null;
  const activatedCounts = {
    characters: 0,
    vibe: 0,
    reference: 0,
  };

  function getActivatedTone() {
    if (activatedCounts.characters > 0) return 'character';
    if (activatedCounts.vibe > 0) return 'vibe';
    if (activatedCounts.reference > 0) return 'pref';
    return '';
  }

  function createActivatedPart(className, text) {
    const part = document.createElement('span');
    part.className = `activated-summary-part ${className}`;
    part.textContent = text;
    return part;
  }

  function renderActivatedSummary() {
    if (!activatedSummary) return;

    const parts = [];
    if (activatedCounts.characters > 0) {
      parts.push({className: 'character', text: `${activatedCounts.characters} Characters`});
    }
    if (activatedCounts.vibe > 0) {
      parts.push({className: 'vibe', text: `${activatedCounts.vibe} Vibe Transfer`});
    }
    if (activatedCounts.reference > 0) {
      parts.push({className: 'pref', text: `${activatedCounts.reference} P.Reference`});
    }

    const hasActivated = parts.length > 0;
    activatedSummary.replaceChildren();
    activatedSummary.classList.toggle('hidden', !hasActivated);
    if (activatedFooter) activatedFooter.classList.toggle('has-activated', hasActivated);
    if (activatedWrap) activatedWrap.classList.toggle('has-activated-summary', hasActivated);
    if (!hasActivated) return;

    const tone = getActivatedTone();
    const label = document.createElement('span');
    label.className = `activated-summary-label ${tone}`;
    label.textContent = 'Activated :';
    activatedSummary.append(label, document.createTextNode(' '));

    parts.forEach((part, index) => {
      if (index > 0) {
        const separator = document.createElement('span');
        separator.className = 'activated-summary-separator';
        separator.textContent = ', ';
        activatedSummary.append(separator);
      }
      activatedSummary.append(createActivatedPart(part.className, part.text));
    });
  }

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
      activatedCounts.characters = 0;
      badge.classList.add('hidden');
      btn.classList.remove('char-active');
      renderActivatedSummary();
      updatePromptTokenEstimate();
      return;
    }

    const count = m.active_count || 0;
    activatedCounts.characters = count;
    btn.classList.add('char-active');
    badge.classList.remove('hidden');
    badge.classList.add('char');
    badge.textContent = count;
    renderActivatedSummary();
    updatePromptTokenEstimate();
  }

  function updateCharacterReference(m) {
    const btn = document.querySelector('.module-btn[data-module="character_reference"]');
    const badge = document.getElementById('badgeCharRef');
    if (!badge || !btn) return;

    const enabledCount = (m.frames || []).filter(frame => frame.is_enabled).length;
    activatedCounts.reference = enabledCount;
    if (!enabledCount) {
      badge.classList.add('hidden');
      btn.classList.remove('charref-active');
      renderActivatedSummary();
      return;
    }

    btn.classList.add('charref-active');
    badge.classList.remove('hidden');
    badge.textContent = enabledCount;
    renderActivatedSummary();
  }

  function updateVibe(m) {
    const btn = document.querySelector('.module-btn[data-module="vibe_transfer"]');
    const badge = document.getElementById('badgeVibe');
    if (!badge || !btn) return;

    const enabledCount = (m.frames || []).filter(frame => frame.is_enabled).length;
    activatedCounts.vibe = enabledCount;
    if (!enabledCount) {
      badge.classList.add('hidden');
      btn.classList.remove('vibe-active');
      renderActivatedSummary();
      return;
    }

    btn.classList.add('vibe-active');
    badge.classList.remove('hidden');
    badge.textContent = enabledCount;
    renderActivatedSummary();
  }

  return {
    updateAuto,
    updateCharacter,
    updateCharacterReference,
    updateVibe,
  };
}
