export function createAutomationPanel({
  document,
  setModuleParam,
}) {
  const moduleBody = document.getElementById('modulePopupBody');
  let lastState = null;

  function onTypeChange(value) {
    setModuleParam('automation', 'auto_type', value);
    if (lastState) {
      lastState.auto_type = parseInt(value, 10);
      render(lastState);
    }
  }

  // Patch only the status line so the live countdown can tick without a full
  // re-render (which would steal focus from the inputs).
  function setLiveStatus(text) {
    const statusEl = moduleBody.querySelector('.mod-status');
    if (statusEl) statusEl.textContent = text || '';
  }

  function render(state) {
    lastState = state;
    const typeLabels = ['무제한', '타이머', '횟수'];
    const typeRadios = typeLabels.map((label, index) =>
      `<label class="mod-checkbox-item">
        <input type="radio" name="autoType" value="${index}" ${state.auto_type === index ? 'checked' : ''} onchange="onAutoTypeChange(this.value)">
        <span class="mod-checkbox-label">${label}</span>
      </label>`
    ).join('');

    const isRunning = state.is_running;
    const isAvailable = state.available !== false;
    moduleBody.innerHTML = `
      <div>
        <div class="mod-section-label" data-naia-guide="각 생성 사이의 대기 시간(초)입니다.\\n\\n무작위 ±50%를 켜면 설정값의 50~150% 범위에서 흔들어 생성 간격 패턴을 깹니다.">딜레이 (초)</div>
        <div style="display:flex;gap:8px;align-items:center">
          <input class="mod-input" type="text" value="${state.delay || '0'}" onchange="setModuleParam('automation','delay',this.value)" style="flex:1">
          <label class="mod-checkbox-item" style="margin:0">
            <input type="checkbox" ${state.random_delay ? 'checked' : ''} oninput="setModuleParam('automation','random_delay',String(this.checked))">
            <span class="mod-checkbox-label">무작위 ±50%</span>
          </label>
        </div>
      </div>
      <div>
        <div class="mod-section-label" data-naia-guide="같은 프롬프트로 N회 생성한 뒤 다음 프롬프트로 넘어갑니다(시드는 매번 재랜덤화되어 변주가 생깁니다).\\n\\n자동 생성(자동화 시작) 상태에서만 동작하며, 값은 저장되지 않고 항상 1로 시작합니다.">반복 횟수</div>
        <input class="mod-input" type="text" value="${state.repeat || '1'}" onchange="setModuleParam('automation','repeat',this.value)">
      </div>
      <div>
        <div class="mod-section-label" data-naia-guide="자동화 종료 조건입니다.\\n\\n무제한 = 수동 정지까지 계속 / 타이머 = 지정한 시간이 지나면 종료 / 횟수 = 지정한 장수를 생성하면 종료.">종료 조건</div>
        <div class="mod-checkbox-grid" style="grid-template-columns:1fr 1fr 1fr">${typeRadios}</div>
      </div>
      ${state.auto_type === 1 ? `<div>
        <div class="mod-section-label" data-naia-guide="타이머 모드에서 자동화가 돌아갈 시간(분)입니다. 경과하면 자동 생성이 멈춥니다.">타이머 (분)</div>
        <input class="mod-input" type="text" value="${state.timer_minutes || '30'}" onchange="setModuleParam('automation','timer_minutes',this.value)">
      </div>` : ''}
      ${state.auto_type === 2 ? `<div>
        <div class="mod-section-label" data-naia-guide="횟수 모드에서 생성할 이미지 장수입니다. 도달하면 자동 생성이 멈춥니다(반복 장도 포함).">횟수 제한</div>
        <input class="mod-input" type="text" value="${state.count_limit || '100'}" onchange="setModuleParam('automation','count_limit',this.value)">
      </div>` : ''}
      <div>
        <label class="mod-checkbox-item" data-naia-guide="자동화가 종료될 때 완료 토스트 알림을 표시합니다.">
          <input type="checkbox" ${state.notify ? 'checked' : ''} oninput="setModuleParam('automation','notify',String(this.checked))">
          <span class="mod-checkbox-label">완료 시 알림</span>
        </label>
      </div>
      <div>
        <label class="mod-checkbox-item" data-naia-guide="완료(횟수/타이머 도달)로 멈춘 뒤 같은 설정으로 자동화를 다시 시작해 계속 돌립니다.\\n\\n[정지]를 누르면 실제로 멈추며, 이 체크는 직접 끌 때까지 유지됩니다(오류로 멈춘 경우엔 재시작하지 않습니다).">
          <input type="checkbox" ${state.persist_automation ? 'checked' : ''} oninput="setModuleParam('automation','persist_automation',String(this.checked))">
          <span class="mod-checkbox-label">지속 자동화 (자동 재무장)</span>
        </label>
      </div>
      <div style="display:flex;gap:8px">
        <button class="mod-action-btn mod-start" ${isRunning || !isAvailable ? 'disabled' : ''} onclick="setModuleParam('automation','start','1')">시작</button>
        <button class="mod-action-btn mod-stop" ${!isRunning ? 'disabled' : ''} onclick="setModuleParam('automation','stop','1')">정지</button>
      </div>
      <div class="mod-status">${state.status || ''}</div>
    `;
  }

  return {
    onTypeChange,
    render,
    setLiveStatus,
  };
}
