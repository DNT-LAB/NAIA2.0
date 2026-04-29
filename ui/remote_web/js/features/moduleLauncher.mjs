const MODULE_REGISTRY = {
  prompt_engineering: {
    label: '프롬프트 엔지니어링',
    title: '프롬프트 엔지니어링',
    action: 'module',
  },
  e621_event: {
    label: 'E621',
    title: 'E621 Event',
    category: 'prompt_tools',
    action: 'module',
  },
  wildcard: {
    label: 'WC',
    title: 'Wildcard',
    category: 'prompt_tools',
    action: 'module',
  },
  chunk: {
    label: 'Chunk',
    title: 'Chunk',
    category: 'prompt_tools',
    action: 'chunk',
  },
  conditional_prompt: {
    label: 'Cond',
    title: 'Conditional Prompt',
    category: 'prompt_tools',
    action: 'module',
  },
  character: {
    label: 'Character',
    title: 'NAID4 Character',
    category: 'character_tools',
    action: 'module',
    naiOnly: true,
    badgeId: 'badgeChar',
    categoryBadgeLabel: 'C',
    categoryBadgeClass: 'char',
  },
  character_reference: {
    label: 'Char Ref',
    title: 'Character Reference',
    category: 'character_tools',
    action: 'module',
    naiOnly: true,
    badgeId: 'badgeCharRef',
    categoryBadgeLabel: 'R',
    categoryBadgeClass: 'ref',
  },
  vibe_transfer: {
    label: 'Vibe',
    title: 'Vibe Transfer',
    category: 'character_tools',
    action: 'module',
    naiOnly: true,
    badgeId: 'badgeVibe',
    categoryBadgeLabel: 'V',
    categoryBadgeClass: 'vibe',
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
    moduleIds: ['e621_event', 'wildcard', 'chunk', 'conditional_prompt'],
  },
  {
    id: 'character_tools',
    label: 'NAI 전용 도구',
    title: 'NAI 전용 도구 (다른 모드에서 차단)',
    moduleIds: ['character', 'character_reference', 'vibe_transfer'],
    splitBadges: true,
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
}) {
  const root = document.getElementById('moduleLauncher');
  let observer = null;
  let updateQueued = false;

  function moduleTitle(moduleId) {
    return MODULE_REGISTRY[moduleId]?.title || moduleId;
  }

  function isBlocked(moduleId) {
    const config = MODULE_REGISTRY[moduleId];
    if (!config) return false;
    if (config.naiOnly && getMode() !== 'NAI') return true;
    return false;
  }

  function renderModuleButton(moduleId, extraClass = '') {
    const config = MODULE_REGISTRY[moduleId];
    if (!config) return '';
    const badge = config.badgeId
      ? `<span class="module-badge hidden" id="${config.badgeId}"></span>`
      : '';
    return `
      <button type="button" class="module-btn ${extraClass}" data-module="${moduleId}" title="${config.title}">
        <span>${config.label}</span>${badge}
      </button>
    `;
  }

  function renderCategory(category) {
    const items = category.moduleIds.map(moduleId => renderModuleButton(moduleId, 'module-menu-item')).join('');
    return `
      <div class="module-category" data-module-category="${category.id}">
        <button type="button" class="module-btn module-category-btn" data-category-toggle="${category.id}" title="${category.title}">
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
  }

  function toggleCategory(categoryId) {
    if (!root) return;
    const category = root.querySelector(`.module-category[data-module-category="${categoryId}"]`);
    if (!category) return;
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
        chip.title = `${badge.title}: ${badge.value}`;
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
    return isModulePopupOpen() && getCurrentModuleId() === moduleId;
  }

  function updateState() {
    if (!root) return;
    root.querySelectorAll('.module-btn[data-module]').forEach(button => {
      const moduleId = button.dataset.module;
      const blocked = isBlocked(moduleId);
      button.classList.toggle('nai-only-disabled', blocked);
      button.disabled = blocked;
      button.classList.toggle('active', moduleIsActive(moduleId));
    });

    CATEGORY_REGISTRY.forEach(category => {
      const categoryEl = root.querySelector(`.module-category[data-module-category="${category.id}"]`);
      if (!categoryEl) return;
      const button = categoryEl.querySelector('.module-category-btn');
      const anyActive = category.moduleIds.some(moduleIsActive);
      const allBlocked = category.moduleIds.every(isBlocked);
      const hasStatus = category.moduleIds.some(moduleId => {
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
        button.classList.toggle('nai-only-disabled', allBlocked);
        button.classList.toggle('category-status', hasStatus);
        button.disabled = allBlocked;
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
    document.addEventListener('pointerdown', event => {
      if (!root.contains(event.target)) closeMenus();
    }, true);
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
  }

  return {
    render,
    bind,
    cleanup,
    closeMenus,
    updateState,
    moduleTitle,
  };
}
