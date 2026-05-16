const MODULE_REGISTRY = {
  prompt_engineering: {
    label: '프롬프트 엔지니어링',
    title: '프롬프트 엔지니어링',
    action: 'module',
  },
  e621_event: {
    label: 'E621 연구모듈',
    title: 'E621 연구모듈',
    category: 'prompt_tools',
    action: 'module',
  },
  danbooru_browser: {
    label: '📦 Danbooru',
    title: 'Danbooru 웹 (Qt) 별도 창 열기',
    category: 'prompt_tools',
    action: 'danbooru_browser',
    className: 'module-detached-tool',
  },
  wildcard: {
    label: '와일드카드 관리',
    title: '와일드카드 관리',
    category: 'prompt_tools',
    action: 'module',
  },
  chunk: {
    label: '와일드카드 청크',
    title: '와일드카드 청크',
    category: 'prompt_tools',
    action: 'chunk',
  },
  conditional_prompt: {
    label: '조건부 프롬프트',
    title: '조건부 프롬프트',
    category: 'prompt_tools',
    action: 'module',
  },
  event_stream: {
    label: '이벤트 스트림 설정',
    title: '이벤트 스트림 설정',
    category: 'prompt_tools',
    action: 'module',
  },
  character: {
    label: 'Character',
    title: 'NAID4 Character',
    category: 'character_tools',
    action: 'module',
    modes: ['NAI'],
    badgeId: 'badgeChar',
    categoryBadgeLabel: 'C',
    categoryBadgeClass: 'char',
  },
  character_reference: {
    label: 'Char Ref',
    title: 'Character Reference',
    category: 'character_tools',
    action: 'module',
    modes: ['NAI'],
    badgeId: 'badgeCharRef',
    categoryBadgeLabel: 'R',
    categoryBadgeClass: 'ref',
  },
  vibe_transfer: {
    label: 'Vibe',
    title: 'Vibe Transfer',
    category: 'character_tools',
    action: 'module',
    modes: ['NAI'],
    badgeId: 'badgeVibe',
    categoryBadgeLabel: 'V',
    categoryBadgeClass: 'vibe',
  },
  comfyui_workflow_default: {
    label: '기본 워크플로우 전환',
    title: '기본 ComfyUI 워크플로우로 전환',
    category: 'comfyui_tools',
    action: 'comfyui_workflow_default',
    modes: ['COMFYUI'],
  },
  comfyui_workflow_upload: {
    label: '커스텀 워크플로우',
    title: 'ComfyUI 워크플로우 PNG 업로드',
    category: 'comfyui_tools',
    action: 'comfyui_workflow_upload',
    modes: ['COMFYUI'],
  },
  comfyui_open_web: {
    label: 'ComfyUI 웹 열기',
    title: '외부 브라우저에서 ComfyUI 열기',
    category: 'comfyui_tools',
    action: 'comfyui_open_web',
    modes: ['COMFYUI'],
    className: 'module-comfyui-tool',
  },
  webui_tools_unavailable: {
    label: '사용 가능한 도구 없음',
    title: 'WEBUI 전용 도구는 현재 기본 사용 불가',
    category: 'webui_tools',
    action: 'placeholder',
    modes: ['WEBUI'],
    disabled: true,
    disabledReason: '현재 기본 사용 불가',
  },
  ollama: {
    label: 'Ollama',
    title: 'Ollama',
    category: 'assistant_tools',
    action: 'module',
  },
  automation: {
    label: 'Automation',
    title: 'Automation',
    category: 'assistant_tools',
    action: 'module',
    badgeId: 'badgeAuto',
  },
};

const CATEGORY_REGISTRY = [
  {
    id: 'prompt_tools',
    label: '프롬프트 도구',
    title: '프롬프트 도구',
    moduleIds: ['event_stream', 'e621_event', 'wildcard', 'chunk', 'conditional_prompt', 'danbooru_browser'],
  },
  {
    id: 'character_tools',
    label: 'NAI 전용 도구',
    title: 'NAI 전용 도구 (다른 모드에서 차단)',
    moduleIds: ['character', 'character_reference', 'vibe_transfer'],
    splitBadges: true,
  },
  {
    id: 'comfyui_tools',
    label: 'COMFYUI 전용 도구',
    title: 'COMFYUI 전용 도구',
    moduleIds: ['comfyui_workflow_default', 'comfyui_workflow_upload', 'comfyui_open_web'],
  },
  {
    id: 'webui_tools',
    label: 'WEBUI 전용 도구',
    title: 'WEBUI 전용 도구 (기본 사용 불가)',
    moduleIds: ['webui_tools_unavailable'],
  },
  {
    id: 'assistant_tools',
    label: '자동화 / 고급 기능',
    title: '자동화 / 고급 기능',
    moduleIds: ['ollama', 'automation'],
  },
];

export function createModuleLauncher({
  document,
  getMode,
  getCurrentModuleId,
  isModulePopupOpen,
  isChunkOpen,
  openModule,
  openChunkPanel,
  openDanbooruBrowser,
  getComfyUiWorkflowState,
  switchComfyUiWorkflowDefault,
  uploadComfyUiWorkflow,
  openComfyUiWeb,
  setModuleParam,
}) {
  const root = document.getElementById('moduleLauncher');
  let observer = null;
  let updateQueued = false;
  let tooltipEl = null;
  let tooltipOwner = null;
  let eventStreamState = {active: false};

  function tooltipAttr(text) {
    return String(text || '')
      .replace(/&/g, '&amp;')
      .replace(/"/g, '&quot;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  function ensureTooltip() {
    if (tooltipEl) return tooltipEl;
    tooltipEl = document.createElement('div');
    tooltipEl.className = 'module-tooltip';
    document.body.append(tooltipEl);
    return tooltipEl;
  }

  function positionTooltip(target) {
    if (!tooltipEl || !target) return;
    const win = document.defaultView;
    const viewportWidth = document.documentElement.clientWidth || win.innerWidth;
    const viewportHeight = document.documentElement.clientHeight || win.innerHeight;
    const rect = target.getBoundingClientRect();
    const tipRect = tooltipEl.getBoundingClientRect();
    const gap = 8;
    let left = rect.left + rect.width / 2 - tipRect.width / 2;
    left = Math.max(gap, Math.min(left, viewportWidth - tipRect.width - gap));
    let top = rect.top - tipRect.height - gap;
    if (top < gap) top = rect.bottom + gap;
    top = Math.max(gap, Math.min(top, viewportHeight - tipRect.height - gap));
    tooltipEl.style.left = `${Math.round(left)}px`;
    tooltipEl.style.top = `${Math.round(top)}px`;
  }

  function showTooltip(target) {
    if (!target || !root?.contains(target)) return;
    const text = target.dataset.moduleTooltip || '';
    if (!text.trim()) return;
    const tooltip = ensureTooltip();
    tooltipOwner = target;
    tooltip.textContent = text;
    tooltip.classList.add('open');
    document.defaultView.requestAnimationFrame(() => {
      if (tooltipOwner === target) positionTooltip(target);
    });
  }

  function hideTooltip(target = null) {
    if (target && tooltipOwner && target !== tooltipOwner) return;
    tooltipOwner = null;
    if (tooltipEl) tooltipEl.classList.remove('open');
  }

  function findTooltipTarget(target) {
    const tooltipTarget = target?.closest?.('[data-module-tooltip]');
    return tooltipTarget && root?.contains(tooltipTarget) ? tooltipTarget : null;
  }

  function moduleTitle(moduleId) {
    return MODULE_REGISTRY[moduleId]?.title || moduleId;
  }

  function isBlocked(moduleId) {
    const config = MODULE_REGISTRY[moduleId];
    if (!config) return false;
    if (!isVisibleInMode(moduleId)) return true;
    if (config.disabled) return true;
    if (moduleId === 'comfyui_workflow_default') {
      const state = typeof getComfyUiWorkflowState === 'function' ? getComfyUiWorkflowState() : null;
      return !Boolean(state?.has_custom);
    }
    return false;
  }

  function isActiveWorkflowMode(moduleId) {
    const state = typeof getComfyUiWorkflowState === 'function' ? getComfyUiWorkflowState() : null;
    const hasCustom = Boolean(state?.has_custom);
    return (moduleId === 'comfyui_workflow_default' && !hasCustom)
      || (moduleId === 'comfyui_workflow_upload' && hasCustom);
  }

  function isVisibleInMode(moduleId) {
    const config = MODULE_REGISTRY[moduleId];
    if (!config) return false;
    if (!Array.isArray(config.modes) || !config.modes.length) return true;
    return config.modes.includes(getMode());
  }

  function visibleCategoryModules(category) {
    return category.moduleIds.filter(isVisibleInMode);
  }

  function renderModuleButton(moduleId, extraClass = '') {
    const config = MODULE_REGISTRY[moduleId];
    if (!config) return '';
    if (moduleId === 'event_stream') {
      const tooltip = tooltipAttr(config.title);
      return `
        <div class="module-event-stream-row" data-module-event-stream>
          <button type="button" class="module-btn module-menu-item module-event-stream-settings" data-module="event_stream" aria-label="${tooltip}" data-module-tooltip="${tooltip}" data-module-static-disabled="0">
            <span>${config.label}</span>
          </button>
          <label class="module-event-stream-toggle" data-module-tooltip="이벤트 스트림 활성">
            <input type="checkbox" data-event-stream-toggle aria-label="이벤트 스트림 활성">
            <span>활성</span>
          </label>
        </div>
      `;
    }
    const badge = config.badgeId
      ? `<span class="module-badge hidden" id="${config.badgeId}"></span>`
      : '';
    const className = ['module-btn', extraClass, config.className || ''].filter(Boolean).join(' ');
    const disabledReason = config.disabledReason ? ` — ${config.disabledReason}` : '';
    const tooltip = tooltipAttr(`${config.title}${disabledReason}`);
    return `
      <button type="button" class="${className}" data-module="${moduleId}" aria-label="${tooltip}" data-module-tooltip="${tooltip}" data-module-static-disabled="${config.disabled ? '1' : '0'}">
        <span>${config.label}</span>${badge}
      </button>
    `;
  }

  function renderCategory(category) {
    const items = category.moduleIds.map(moduleId => renderModuleButton(moduleId, 'module-menu-item')).join('');
    return `
      <div class="module-category" data-module-category="${category.id}">
        <button type="button" class="module-btn module-category-btn" data-category-toggle="${category.id}" aria-label="${tooltipAttr(category.title)}" data-module-tooltip="${tooltipAttr(category.title)}">
          <span class="module-category-label">${category.label}</span><span class="module-category-badges hidden"></span>
        </button>
        <div class="module-category-menu" role="menu" aria-label="${category.title}">
          <div class="module-category-title">${category.title}</div>
          ${items}
        </div>
      </div>
    `;
  }

  function render() {
    if (!root) return;
    root.innerHTML = [
      renderModuleButton('prompt_engineering', 'module-primary-btn'),
      ...CATEGORY_REGISTRY.map(renderCategory),
    ].join('');
  }

  function closeMenus(exceptCategory = '') {
    if (!root) return;
    root.querySelectorAll('.module-category.menu-open').forEach(category => {
      if (category.dataset.moduleCategory !== exceptCategory) {
        category.classList.remove('menu-open');
      }
    });
    hideTooltip();
  }

  function toggleCategory(categoryId) {
    if (!root) return;
    const category = root.querySelector(`.module-category[data-module-category="${categoryId}"]`);
    if (!category || category.classList.contains('hidden')) return;
    const willOpen = !category.classList.contains('menu-open');
    closeMenus(categoryId);
    category.classList.toggle('menu-open', willOpen);
    updateState();
  }

  function launchModule(moduleId) {
    const config = MODULE_REGISTRY[moduleId];
    if (!config || isBlocked(moduleId)) return;
    closeMenus();
    if (config.action === 'chunk') {
      openChunkPanel(null, true);
    } else if (config.action === 'danbooru_browser') {
      openDanbooruBrowser?.();
    } else if (config.action === 'comfyui_workflow_default') {
      switchComfyUiWorkflowDefault?.();
    } else if (config.action === 'comfyui_workflow_upload') {
      uploadComfyUiWorkflow?.();
    } else if (config.action === 'comfyui_open_web') {
      openComfyUiWeb?.();
    } else {
      openModule(moduleId);
    }
    updateState();
  }

  function visibleBadges(category) {
    return category.moduleIds
      .map(moduleId => {
        const config = MODULE_REGISTRY[moduleId];
        const badge = config?.badgeId ? document.getElementById(config.badgeId) : null;
        if (!badge || badge.classList.contains('hidden') || !badge.textContent.trim()) return null;
        return {
          moduleId,
          label: config.categoryBadgeLabel || config.label,
          className: config.categoryBadgeClass || '',
          title: config.title,
          value: badge.textContent.trim(),
        };
      })
      .filter(Boolean);
  }

  function applyCategoryBadge(category, categoryEl) {
    const badgeGroup = categoryEl.querySelector('.module-category-badges');
    if (!badgeGroup) return;
    const badges = visibleBadges(category);
    if (!badges.length) {
      if (badgeGroup.dataset.badgeSignature === '' && badgeGroup.classList.contains('hidden')) return;
      badgeGroup.dataset.badgeSignature = '';
      badgeGroup.classList.add('hidden');
      badgeGroup.replaceChildren();
      return;
    }
    const signature = category.splitBadges
      ? badges.map(badge => `${badge.moduleId}:${badge.value}`).join('|')
      : badges.map(badge => badge.value).join('|');
    if (badgeGroup.dataset.badgeSignature === signature && !badgeGroup.classList.contains('hidden')) return;
    badgeGroup.dataset.badgeSignature = signature;
    badgeGroup.replaceChildren();
    if (category.splitBadges) {
      badges.forEach(badge => {
        const chip = document.createElement('span');
        chip.className = `module-category-badge module-category-badge-${badge.className || badge.moduleId}`;
        chip.textContent = `${badge.label}${badge.value}`;
        chip.setAttribute('aria-label', `${badge.title}: ${badge.value}`);
        chip.dataset.moduleTooltip = `${badge.title}: ${badge.value}`;
        badgeGroup.append(chip);
      });
      badgeGroup.classList.remove('hidden');
      return;
    }
    const values = badges.map(badge => badge.value);
    const numericValues = values.map(value => Number(value)).filter(value => Number.isFinite(value));
    const chip = document.createElement('span');
    chip.className = 'module-category-badge';
    chip.textContent = numericValues.length === values.length
      ? String(numericValues.reduce((sum, value) => sum + value, 0))
      : (values.length === 1 ? values[0] : String(values.length));
    badgeGroup.append(chip);
    badgeGroup.classList.remove('hidden');
  }

  function moduleIsActive(moduleId) {
    if (moduleId === 'chunk') return isChunkOpen();
    if (MODULE_REGISTRY[moduleId]?.action === 'danbooru_browser') return false;
    return isModulePopupOpen() && getCurrentModuleId() === moduleId;
  }

  function updateState() {
    if (!root) return;
    root.querySelectorAll('.module-btn[data-module]').forEach(button => {
      const moduleId = button.dataset.module;
      const visible = isVisibleInMode(moduleId);
      const blocked = isBlocked(moduleId);
      button.classList.toggle('hidden', !visible);
      button.classList.toggle('nai-only-disabled', blocked);
      button.classList.toggle('module-static-disabled', button.dataset.moduleStaticDisabled === '1');
      button.classList.toggle('module-workflow-active', visible && isActiveWorkflowMode(moduleId));
      button.classList.toggle('event-stream-enabled', moduleId === 'event_stream' && Boolean(eventStreamState.active));
      button.disabled = blocked;
      button.classList.toggle('active', visible && moduleIsActive(moduleId));
    });
    root.querySelectorAll('[data-module-event-stream]').forEach(row => {
      row.classList.toggle('active', Boolean(eventStreamState.active));
      const checkbox = row.querySelector('[data-event-stream-toggle]');
      if (checkbox && checkbox.checked !== Boolean(eventStreamState.active)) {
        checkbox.checked = Boolean(eventStreamState.active);
      }
    });

    CATEGORY_REGISTRY.forEach(category => {
      const categoryEl = root.querySelector(`.module-category[data-module-category="${category.id}"]`);
      if (!categoryEl) return;
      const button = categoryEl.querySelector('.module-category-btn');
      const visibleModules = visibleCategoryModules(category);
      const visible = visibleModules.length > 0;
      categoryEl.classList.toggle('hidden', !visible);
      if (!visible) {
        categoryEl.classList.remove('menu-open');
        return;
      }
      const anyActive = visibleModules.some(moduleIsActive);
      const allBlocked = visibleModules.length > 0 && visibleModules.every(isBlocked);
      const hasStatus = visibleModules.some(moduleId => {
        if (moduleId === 'event_stream' && eventStreamState.active) return true;
        const leaf = root.querySelector(`.module-btn[data-module="${moduleId}"]`);
        return leaf?.classList.contains('auto-active')
          || leaf?.classList.contains('char-active')
          || leaf?.classList.contains('charref-active')
          || leaf?.classList.contains('vibe-active');
      });
      categoryEl.classList.toggle('category-active', anyActive);
      categoryEl.classList.toggle('category-blocked', allBlocked);
      categoryEl.classList.toggle('category-status', hasStatus);
      if (button) {
        button.classList.toggle('active', anyActive || categoryEl.classList.contains('menu-open'));
        button.classList.toggle('module-category-disabled', allBlocked);
        button.classList.toggle('category-status', hasStatus);
        button.disabled = false;
      }
      applyCategoryBadge(category, categoryEl);
    });
  }

  function scheduleUpdateState() {
    if (updateQueued) return;
    updateQueued = true;
    document.defaultView.requestAnimationFrame(() => {
      updateQueued = false;
      updateState();
    });
  }

  function bind() {
    if (!root) return;
    root.addEventListener('click', event => {
      if (event.target.closest('[data-event-stream-toggle]')) return;
      const categoryToggle = event.target.closest('[data-category-toggle]');
      if (categoryToggle && root.contains(categoryToggle)) {
        event.preventDefault();
        toggleCategory(categoryToggle.dataset.categoryToggle);
        return;
      }
      const moduleButton = event.target.closest('.module-btn[data-module]');
      if (moduleButton && root.contains(moduleButton)) {
        event.preventDefault();
        launchModule(moduleButton.dataset.module);
      }
    });
    root.addEventListener('change', event => {
      const toggle = event.target.closest('[data-event-stream-toggle]');
      if (!toggle || !root.contains(toggle)) return;
      event.preventDefault();
      eventStreamState = {...eventStreamState, active: Boolean(toggle.checked)};
      updateState();
      if (typeof setModuleParam === 'function') {
        setModuleParam('event_stream', 'active', String(Boolean(toggle.checked)));
      } else if (typeof globalThis.setModuleParam === 'function') {
        globalThis.setModuleParam('event_stream', 'active', String(Boolean(toggle.checked)));
      }
    });
    document.addEventListener('pointerdown', event => {
      if (!root.contains(event.target)) closeMenus();
    }, true);
    root.addEventListener('pointerover', event => {
      const target = findTooltipTarget(event.target);
      if (target) showTooltip(target);
    });
    root.addEventListener('pointermove', () => {
      if (tooltipOwner) positionTooltip(tooltipOwner);
    });
    root.addEventListener('pointerout', event => {
      if (tooltipOwner && !tooltipOwner.contains(event.relatedTarget)) hideTooltip(tooltipOwner);
    });
    root.addEventListener('focusin', event => {
      const target = findTooltipTarget(event.target);
      if (target) showTooltip(target);
    });
    root.addEventListener('focusout', event => {
      const target = findTooltipTarget(event.target);
      if (target) hideTooltip(target);
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape') closeMenus();
    });
    observer = new MutationObserver(scheduleUpdateState);
    observer.observe(root, {
      subtree: true,
      attributes: true,
      childList: true,
      characterData: true,
      attributeFilter: ['class', 'disabled'],
    });
    updateState();
  }

  function cleanup() {
    if (observer) observer.disconnect();
    observer = null;
    hideTooltip();
    tooltipEl?.remove();
    tooltipEl = null;
  }

  return {
    render,
    bind,
    cleanup,
    closeMenus,
    openCategory: toggleCategory,
    updateState,
    updateEventStreamState(state = {}) {
      eventStreamState = {...eventStreamState, ...state, active: Boolean(state.active)};
      updateState();
    },
    moduleTitle,
  };
}
