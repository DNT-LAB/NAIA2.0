export function createModuleBadges({
  document,
  getMode,
  estimateTokenCount,
  setCharacterPromptText,
  setCharacterTokenCount,
  updatePromptTokenEstimate,
  openModule,
  openParamsTab,
}) {
  const activatedSummary = document.getElementById('activatedSummary');
  const activatedFooter = document.getElementById('promptTokenFooter');
  const activatedWrap = activatedSummary ? activatedSummary.closest('.prompt-highlight-wrap') : null;
  const activatedCounts = {
    characters: 0,
    vibe: 0,
    reference: 0,
  };
  const comfyUiStatus = {
    samplingMode: 'eps',
    animaWeight: '0.75',
    workflowHasCustom: false,
  };

  function normalizeSamplingMode(value) {
    const mode = String(value || '').trim().toLowerCase();
    if (mode === 'v_prediction' || mode === 'v-pred' || mode === 'vpred') return 'v_prediction';
    if (mode === 'anima') return 'anima';
    return 'eps';
  }

  function displaySamplingMode(value) {
    const mode = normalizeSamplingMode(value);
    if (mode === 'anima') return 'ANIMA';
    if (mode === 'v_prediction') return 'V-Pred';
    return 'EPS';
  }

  function formatAnimaWeight(value) {
    const text = String(value ?? '').trim();
    if (!text) return '0.75';
    const parsed = Number(text);
    if (!Number.isFinite(parsed)) return '0.75';
    return parsed.toFixed(3).replace(/0+$/, '').replace(/\.$/, '');
  }

  function getActivatedTone() {
    if (activatedCounts.characters > 0) return 'character';
    if (activatedCounts.vibe > 0) return 'vibe';
    if (activatedCounts.reference > 0) return 'pref';
    return '';
  }

  function createActivatedPart(className, text, moduleId) {
    const part = document.createElement('button');
    part.type = 'button';
    part.className = `activated-summary-part ${className}`;
    part.textContent = text;
    part.title = `Open ${text.replace(/^\d+\s+/, '')}`;
    part.addEventListener('click', event => {
      event.stopPropagation();
      if (typeof openModule === 'function') openModule(moduleId);
    });
    return part;
  }

  function createParamsPart(className, text) {
    const part = document.createElement('button');
    part.type = 'button';
    part.className = `activated-summary-part ${className}`;
    part.textContent = text;
    part.title = 'Open Params';
    part.addEventListener('click', event => {
      event.stopPropagation();
      if (typeof openParamsTab === 'function') openParamsTab();
    });
    return part;
  }

  function appendBullet() {
    const bullet = document.createElement('span');
    bullet.className = 'activated-summary-bullet';
    bullet.textContent = ' ● ';
    activatedSummary.append(bullet);
  }

  function renderComfyUiSummary() {
    activatedSummary.replaceChildren();
    activatedSummary.classList.remove('hidden');
    activatedSummary.classList.add('comfyui-summary');
    if (activatedFooter) activatedFooter.classList.add('has-activated');
    if (activatedWrap) activatedWrap.classList.add('has-activated-summary');

    const mode = normalizeSamplingMode(comfyUiStatus.samplingMode);
    activatedSummary.append(createParamsPart('comfyui-mode', `Mode : ${displaySamplingMode(mode)}`));
    if (mode === 'anima') {
      appendBullet();
      const weight = document.createElement('span');
      weight.className = 'activated-summary-static comfyui-weight';
      weight.textContent = `가중치 : ${formatAnimaWeight(comfyUiStatus.animaWeight)}`;
      activatedSummary.append(weight);
    }
    appendBullet();
    const workflow = document.createElement('span');
    workflow.className = `activated-summary-static ${comfyUiStatus.workflowHasCustom ? 'comfyui-workflow-custom' : 'comfyui-workflow-basic'}`;
    workflow.textContent = comfyUiStatus.workflowHasCustom ? 'Custom Workflow' : 'Basic Workflow';
    activatedSummary.append(workflow);
  }

  function renderActivatedSummary() {
    if (!activatedSummary) return;
    const modeName = getMode();
    const isNaiMode = modeName === 'NAI';

    if (modeName === 'COMFYUI') {
      renderComfyUiSummary();
      return;
    }

    const parts = [];
    if (isNaiMode && activatedCounts.characters > 0) {
      parts.push({
        className: 'character',
        moduleId: 'character',
        text: `${activatedCounts.characters} Characters`,
      });
    }
    if (isNaiMode && activatedCounts.vibe > 0) {
      parts.push({
        className: 'vibe',
        moduleId: 'vibe_transfer',
        text: `${activatedCounts.vibe} Vibe Transfer`,
      });
    }
    if (isNaiMode && activatedCounts.reference > 0) {
      parts.push({
        className: 'pref',
        moduleId: 'character_reference',
        text: `${activatedCounts.reference} P.Reference`,
      });
    }

    const hasActivated = parts.length > 0;
    activatedSummary.replaceChildren();
    activatedSummary.classList.remove('comfyui-summary');
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
      activatedSummary.append(createActivatedPart(part.className, part.text, part.moduleId));
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

  function updateComfyUiWorkflowState(m) {
    if (!m || typeof m !== 'object') return;
    if ('has_custom' in m) {
      comfyUiStatus.workflowHasCustom = Boolean(m.has_custom);
    } else if ('comfyui_workflow_has_custom' in m) {
      comfyUiStatus.workflowHasCustom = Boolean(m.comfyui_workflow_has_custom);
    }
    renderActivatedSummary();
  }

  function updateComfyUiParams(m) {
    if (!m || typeof m !== 'object') return;
    if ('sampling_mode' in m) comfyUiStatus.samplingMode = normalizeSamplingMode(m.sampling_mode);
    if ('anima_weight' in m) comfyUiStatus.animaWeight = formatAnimaWeight(m.anima_weight);
    else if ('anima_weight_raw' in m) comfyUiStatus.animaWeight = formatAnimaWeight(m.anima_weight_raw);
    if (m.comfyui_workflow && typeof m.comfyui_workflow === 'object') {
      updateComfyUiWorkflowState(m.comfyui_workflow);
      return;
    }
    updateComfyUiWorkflowState(m);
    renderActivatedSummary();
  }

  return {
    updateAuto,
    updateCharacter,
    updateCharacterReference,
    updateVibe,
    updateComfyUiParams,
    updateComfyUiWorkflowState,
    updateModeState() {
      renderActivatedSummary();
      updatePromptTokenEstimate();
    },
  };
}
