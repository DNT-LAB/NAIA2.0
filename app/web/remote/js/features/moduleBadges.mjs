export function createModuleBadges({
  document,
  getMode,
  estimateTokenCount,
  setCharacterPromptText,
  setCharacterTokenCount,
  updatePromptTokenEstimate,
  openModule,
  openParamsTab,
  setAnimaWeight,
  openComfyUiTools,
  getComfyEngine = () => 'external',
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
    animaWeight: '1',
    workflowHasCustom: false,
    workflowType: '',
    workflowLabel: 'Basic Workflow',
  };
  const webUiStatus = {
    enableHr: false,
    hrScale: '1',
    hiresfixAssistEnabled: true,
    hiresfixAssistTarget: 512,
  };
  let weightPopover = null;
  let weightInput = null;
  let weightAnchor = null;

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
    if (!text) return '1';
    const parsed = Number(text);
    if (!Number.isFinite(parsed)) return '1';
    return parsed.toFixed(3).replace(/0+$/, '').replace(/\.$/, '');
  }

  function normalizeBoolean(value) {
    if (typeof value === 'boolean') return value;
    const text = String(value ?? '').trim().toLowerCase();
    return text === 'true' || text === '1' || text === 'yes' || text === 'on';
  }

  function formatHiresScale(value) {
    const text = String(value ?? '').trim();
    if (!text) return '1';
    const parsed = Number(text);
    if (!Number.isFinite(parsed)) return '1';
    return parsed.toFixed(2).replace(/0+$/, '').replace(/\.$/, '');
  }

  function normalizeHiresfixAssistTarget(value) {
    return Number(value) === 768 ? 768 : 512;
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

  function closeWeightPopover() {
    if (weightPopover) weightPopover.classList.remove('open');
    weightAnchor = null;
  }

  function positionWeightPopover() {
    if (!weightPopover || !weightAnchor) return;
    const rect = weightAnchor.getBoundingClientRect();
    const popRect = weightPopover.getBoundingClientRect();
    const viewportWidth = document.documentElement.clientWidth || document.defaultView.innerWidth;
    const gap = 7;
    let left = rect.left + rect.width / 2 - popRect.width / 2;
    left = Math.max(gap, Math.min(left, viewportWidth - popRect.width - gap));
    const top = Math.max(gap, rect.top - popRect.height - gap);
    weightPopover.style.left = `${Math.round(left)}px`;
    weightPopover.style.top = `${Math.round(top)}px`;
  }

  function commitWeight(value) {
    const nextValue = String(value ?? '').trim();
    comfyUiStatus.animaWeight = formatAnimaWeight(nextValue);
    renderActivatedSummary();
    if (typeof setAnimaWeight === 'function') setAnimaWeight(nextValue);
  }

  function ensureWeightPopover() {
    if (weightPopover) return weightPopover;
    weightPopover = document.createElement('div');
    weightPopover.className = 'comfyui-weight-popover';
    weightPopover.innerHTML = `
      <input class="comfyui-weight-input" type="text" inputmode="decimal" placeholder="1" aria-label="Random prompt weight">
      <button class="comfyui-weight-apply" type="button">OK</button>
    `;
    weightInput = weightPopover.querySelector('.comfyui-weight-input');
    const applyButton = weightPopover.querySelector('.comfyui-weight-apply');
    applyButton.addEventListener('click', event => {
      event.preventDefault();
      commitWeight(weightInput.value);
      closeWeightPopover();
    });
    weightInput.addEventListener('keydown', event => {
      if (event.key === 'Enter') {
        event.preventDefault();
        commitWeight(weightInput.value);
        closeWeightPopover();
      } else if (event.key === 'Escape') {
        event.preventDefault();
        closeWeightPopover();
      }
    });
    document.body.append(weightPopover);
    document.addEventListener('pointerdown', event => {
      if (!weightPopover?.classList.contains('open')) return;
      if (weightPopover.contains(event.target) || weightAnchor?.contains(event.target)) return;
      closeWeightPopover();
    }, true);
    document.defaultView.addEventListener('resize', positionWeightPopover);
    document.defaultView.addEventListener('scroll', positionWeightPopover, true);
    return weightPopover;
  }

  function openWeightPopover(anchor) {
    const popover = ensureWeightPopover();
    weightAnchor = anchor;
    weightInput.value = comfyUiStatus.animaWeight || '';
    popover.classList.add('open');
    positionWeightPopover();
    weightInput.focus();
    weightInput.select();
  }

  function createWeightPart(text) {
    const part = document.createElement('button');
    part.type = 'button';
    part.className = 'activated-summary-part comfyui-weight';
    part.textContent = text;
    part.title = 'Random Prompt Weight';
    part.addEventListener('click', event => {
      event.stopPropagation();
      openWeightPopover(part);
    });
    return part;
  }

  function createWorkflowPart(managed = false) {
    const hasCustom = comfyUiStatus.workflowHasCustom;
    const isFree = ['bypass', 'free'].includes(String(comfyUiStatus.workflowType || '').trim().toLowerCase());
    const part = document.createElement('button');
    part.type = 'button';
    part.className = `activated-summary-part ${hasCustom && !managed ? 'comfyui-workflow-custom' : 'comfyui-workflow-basic'}`;
    // 관리형 ANIMA 엔진은 NAIA 가 고정 그래프를 쓴다 - 외부 ComfyUI 의 워크플로(기본 · 커스텀 · 바이패스)는 쓰지 않는다
    part.textContent = managed ? 'ANIMA 엔진'
      : (isFree ? 'Bypass Workflow' : (comfyUiStatus.workflowLabel || (hasCustom ? 'Custom Workflow' : 'Basic Workflow')));
    part.title = managed ? 'ANIMA 전용 도구' : 'COMFYUI 전용 도구';
    part.addEventListener('click', event => {
      event.stopPropagation();
      if (typeof openComfyUiTools === 'function') openComfyUiTools();
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
    activatedSummary.classList.remove('webui-summary');
    if (activatedFooter) activatedFooter.classList.add('has-activated');
    if (activatedWrap) activatedWrap.classList.add('has-activated-summary');

    // 관리형 ANIMA 엔진 = ANIMA 고정(사용자 지정 09-27: EPS · V-Pred 미지원) - 서버에 남은 플래그 값과 무관하다
    const managed = getComfyEngine() === 'managed';
    const isFreeWorkflow = !managed && ['bypass', 'free'].includes(String(comfyUiStatus.workflowType || '').trim().toLowerCase());
    const mode = managed ? 'anima' : normalizeSamplingMode(comfyUiStatus.samplingMode);
    activatedSummary.append(createParamsPart('comfyui-mode', `Mode : ${isFreeWorkflow ? 'Bypass' : displaySamplingMode(mode)}`));
    appendBullet();
    activatedSummary.append(createWeightPart(`가중치 : ${formatAnimaWeight(comfyUiStatus.animaWeight)}`));
    appendBullet();
    activatedSummary.append(createWorkflowPart(managed));
  }

  function renderWebUiSummary() {
    activatedSummary.replaceChildren();
    activatedSummary.classList.remove('hidden');
    activatedSummary.classList.remove('comfyui-summary');
    activatedSummary.classList.add('webui-summary');
    if (activatedFooter) activatedFooter.classList.add('has-activated');
    if (activatedWrap) activatedWrap.classList.add('has-activated-summary');

    activatedSummary.append(createParamsPart('webui-mode', 'Mode : WEBUI'));
    if (webUiStatus.enableHr) {
      appendBullet();
      activatedSummary.append(createParamsPart('webui-hires', `Hiresfix x${formatHiresScale(webUiStatus.hrScale)}`));
      appendBullet();
      activatedSummary.append(createParamsPart(
        webUiStatus.hiresfixAssistEnabled ? 'webui-hires-assist' : 'webui-hires-assist-off',
        webUiStatus.hiresfixAssistEnabled
          ? `Assist ${webUiStatus.hiresfixAssistTarget}^2`
          : 'Assist OFF'
      ));
    }
    appendBullet();
    activatedSummary.append(createWeightPart(`가중치 : ${formatAnimaWeight(comfyUiStatus.animaWeight)}`));
  }

  function renderActivatedSummary() {
    if (!activatedSummary) return;
    const modeName = getMode();
    const isNaiMode = modeName === 'NAI';

    if (modeName === 'COMFYUI') {
      renderComfyUiSummary();
      return;
    }
    if (modeName === 'WEBUI') {
      renderWebUiSummary();
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
    activatedSummary.classList.remove('webui-summary');
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

  function automationKind(m) {
    const t = String(m && m.automation_type || '').trim().toLowerCase();
    if (t === 'timer' || t === 'count' || t === 'unlimited') return t;
    const byIndex = ['unlimited', 'timer', 'count'][Number(m && m.auto_type)];
    return byIndex || 'unlimited';
  }

  function formatAutomationClock(totalSeconds) {
    const s = Math.max(0, Math.floor(Number(totalSeconds) || 0));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    const pad = n => String(n).padStart(2, '0');
    // future01 parity: MM:SS, expanding to HH:MM:SS only past the hour mark.
    return h > 0 ? `${pad(h)}:${pad(m)}:${pad(sec)}` : `${pad(m)}:${pad(sec)}`;
  }

  function automationBadgeText(m) {
    const kind = automationKind(m);
    if (kind === 'timer') {
      const rem = Number(m.remaining_seconds);
      return Number.isFinite(rem) ? formatAutomationClock(rem) : '';
    }
    if (kind === 'count') {
      const c = Number(m.remaining_count);
      return Number.isFinite(c) ? `${c}` : '';
    }
    const done = Number(m.completed_count);
    return Number.isFinite(done) && done > 0 ? `${done}` : '';
  }

  function updateAuto(m) {
    const btn = document.querySelector('.module-btn[data-module="automation"]');
    const badge = document.getElementById('badgeAuto');
    if (!badge || !btn) return;

    if (!m.is_running) {
      badge.classList.add('hidden');
      badge.textContent = '';
      btn.classList.remove('auto-active');
      return;
    }
    btn.classList.add('auto-active');

    const text = automationBadgeText(m);
    if (text) {
      badge.textContent = text;
      badge.classList.remove('hidden');
    } else {
      badge.textContent = '';
      badge.classList.add('hidden');
    }
  }

  /** 켜진 슬롯의 글 - Connect 자식은 제 글이 비어도 앞 슬롯의 글을 물려받아 나간다(Codex 09-30).
   *  📌 고정 슬롯(pinned: uuid -> {prompt, uc})은 그 값이 나가고, 자식도 그 값을 물려받는다. */
  function enabledSlotTexts(characters, pinned = null) {
    const slots = (characters || []).filter(item => item && item.enabled);
    const pinOf = item => {
      const pin = pinned && pinned[String(item.slot_uuid || '')];
      return pin ? String(typeof pin === 'object' ? pin.prompt || '' : pin).trim() : '';
    };
    const own = new Map(slots.map(item => [String(item.slot_uuid || ''),
      pinOf(item) || String(item.prompt || '').trim()]));
    return slots.map(item => {
      if (pinOf(item)) return pinOf(item);
      const link = String(item.connect_to || '').trim();
      return [link ? own.get(link) || '' : '', String(item.prompt || '').trim()].filter(Boolean).join(', ');
    }).filter(Boolean);
  }

  function updateCharacter(m) {
    const btn = document.querySelector('.module-btn[data-module="character"]');
    const badge = document.getElementById('badgeChar');
    if (!badge || !btn) return;

    // 다음 Generate 에 나가는 글로 어림한다 - 백엔드가 계산한 출처(applied.source)대로 가른다(Codex 09-30 2차: 길이로
    // 가르면 조건부 규칙이 캐릭터를 모두 뺀 빈 목록이 슬롯 글로 되살아났다):
    //   override · rolled -> 그 목록(비었으면 0) · none -> 0 · fresh -> 켜진 슬롯의 글(📌 고정은 그 값).
    // 굴려 둔 값이 없을 때 0 을 내걸면 "캐릭터가 안 들어간다" 로 읽힌다(사용자 제보 2026-09-30: Activated 2 Characters
    // 인데 Character 0). 옛 서버(applied 없음)는 굴려 둔 값 -> 없으면 슬롯 글.
    // ⚠️ 모듈이 꺼졌으면 비운다(조건부 override 는 꺼져도 나간다 - 백엔드의 첫 순위) - 토큰 칸은 개수가 0 이어도
    //    글로 다시 어림한다(Codex 09-30: 꺼졌는데 Character 5).
    const view = m.applied && typeof m.applied === 'object' ? m.applied : null;
    const source = view ? String(view.source || '') : '';
    let texts;
    if (source === 'override' || source === 'rolled') texts = view.characters || [];
    else if (source === 'none' || !m.activated) texts = [];
    else if (source === 'fresh') texts = enabledSlotTexts(m.characters, view.pinned);
    else {
      const rolled = (m.processed_characters || []).filter(Boolean);
      texts = rolled.length ? rolled : enabledSlotTexts(m.characters);
    }
    const promptText = texts.map(value => String(value || '').trim()).filter(Boolean).join(' ');
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

    // ⚠️ **나가는 수**를 센다. `active_count` 는 활성 무리의 크기라 꺼 둔 슬롯
    //    (✘)까지 포함한다 - 셋을 다 꺼 페이로드가 비어도 "3" 이라고 말하게 된다.
    //    옛 서버가 이 필드를 안 보낼 수 있으므로 그때만 active_count 로 물러난다.
    const count = (m.enabled_count != null ? m.enabled_count : m.active_count) || 0;
    activatedCounts.characters = count;
    if (!count) {
      // 슬롯을 다 꺼 두면 나가는 캐릭터가 없다 - 모듈이 꺼진 것과 같은 그림이
      // 맞다. "0" 을 내걸면 켜져 있다는 뜻으로 읽힌다.
      badge.classList.add('hidden');
      btn.classList.remove('char-active');
      renderActivatedSummary();
      updatePromptTokenEstimate();
      return;
    }
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
    if ('workflow_type' in m) {
      const workflowType = String(m.workflow_type || '');
      comfyUiStatus.workflowType = ['bypass', 'free'].includes(workflowType.trim().toLowerCase()) ? 'bypass' : workflowType;
    } else if ('comfyui_workflow_type' in m) {
      const workflowType = String(m.comfyui_workflow_type || '');
      comfyUiStatus.workflowType = ['bypass', 'free'].includes(workflowType.trim().toLowerCase()) ? 'bypass' : workflowType;
    } else if (!comfyUiStatus.workflowHasCustom) {
      comfyUiStatus.workflowType = '';
    }
    if (['bypass', 'free'].includes(String(comfyUiStatus.workflowType || '').trim().toLowerCase())) {
      comfyUiStatus.workflowLabel = 'Bypass Workflow';
    } else if (m.workflow_label) {
      comfyUiStatus.workflowLabel = String(m.workflow_label);
    } else if (m.comfyui_workflow_label) {
      comfyUiStatus.workflowLabel = String(m.comfyui_workflow_label);
    } else {
      comfyUiStatus.workflowLabel = comfyUiStatus.workflowHasCustom ? 'Custom Workflow' : 'Basic Workflow';
    }
    renderActivatedSummary();
  }

  function updateComfyUiParams(m) {
    if (!m || typeof m !== 'object') return;
    if ('sampling_mode' in m) comfyUiStatus.samplingMode = normalizeSamplingMode(m.sampling_mode);
    if ('anima_weight' in m) comfyUiStatus.animaWeight = formatAnimaWeight(m.anima_weight);
    else if ('anima_weight_raw' in m) comfyUiStatus.animaWeight = formatAnimaWeight(m.anima_weight_raw);
    if ('enable_hr' in m) webUiStatus.enableHr = normalizeBoolean(m.enable_hr);
    if ('hr_scale' in m) webUiStatus.hrScale = formatHiresScale(m.hr_scale);
    if ('webui_hiresfix_assist' in m) webUiStatus.hiresfixAssistEnabled = normalizeBoolean(m.webui_hiresfix_assist);
    if ('webui_hiresfix_assist_target' in m) {
      webUiStatus.hiresfixAssistTarget = normalizeHiresfixAssistTarget(m.webui_hiresfix_assist_target);
    }
    if (m.comfyui_workflow && typeof m.comfyui_workflow === 'object') {
      updateComfyUiWorkflowState(m.comfyui_workflow);
      return;
    }
    updateComfyUiWorkflowState(m);
    renderActivatedSummary();
  }

  function updateWebUiHiresfixAssist(m) {
    if (!m || typeof m !== 'object') return;
    if ('enabled' in m) webUiStatus.hiresfixAssistEnabled = normalizeBoolean(m.enabled);
    if ('target' in m) webUiStatus.hiresfixAssistTarget = normalizeHiresfixAssistTarget(m.target);
    renderActivatedSummary();
  }

  return {
    updateAuto,
    updateCharacter,
    updateCharacterReference,
    updateVibe,
    updateComfyUiParams,
    updateComfyUiWorkflowState,
    updateWebUiHiresfixAssist,
    updateModeState() {
      renderActivatedSummary();
      updatePromptTokenEstimate();
    },
  };
}
