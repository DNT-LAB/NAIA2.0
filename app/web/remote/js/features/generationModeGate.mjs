// 그림에서 프롬프트 · 설정 · 캐릭터 · Vibe 를 불러오기 전에 보는 모드 문(11-23 사용자 지정).
//
// - 다른 모드에서 만든 그림은 불러오지 않는다. ANIMA(내장 관리형 ComfyUI)와 외부 ComfyUI 도 다른 모드다.
// - 어느 모드에서 만들었는지 모르면 **모두 막는다**(메타가 없거나 형식을 못 알아본 그림).
// - 그림의 모드는 백엔드가 메타 응답마다 `generation_mode`(NAI · WEBUI · COMFYUI · ANIMA · '')로 싣는다
//   (core/generation_mode.py). 지금 모드는 화면이 안다 - ANIMA 는 COMFYUI + 관리형 엔진이다.

export const MODE_LABELS = {NAI: 'NAI', WEBUI: 'WEBUI', COMFYUI: 'ComfyUI', ANIMA: 'ANIMA'};

function norm(mode) {
  const value = String(mode ?? '').trim().toUpperCase();
  return Object.prototype.hasOwnProperty.call(MODE_LABELS, value) ? value : '';
}

export function modeLabel(mode) {
  return MODE_LABELS[norm(mode)] || '알 수 없음';
}

// 메타 응답에서 그림의 모드를 읽는다. 위에 없으면 summary 안을 본다(요약만 받은 응답).
export function imageGenerationMode(data) {
  if (!data || typeof data !== 'object') return '';
  if (typeof data.generation_mode === 'string') return norm(data.generation_mode);
  const summary = data.summary && typeof data.summary === 'object' ? data.summary : null;
  return summary ? norm(summary.generation_mode) : '';
}

// 막아야 하면 사용자에게 보일 까닭을, 불러와도 되면 '' 를 돌려준다.
export function loadBlockReason(imageMode, currentMode) {
  const image = norm(imageMode);
  const current = norm(currentMode);
  if (!image) return '어느 모드에서 만든 그림인지 알 수 없어 불러올 수 없습니다.';
  if (!current) return '지금 모드를 알 수 없어 불러올 수 없습니다.';
  if (image !== current) {
    return `${modeLabel(image)} 에서 만든 그림입니다 - 지금 모드(${modeLabel(current)})에서는 불러올 수 없습니다.`;
  }
  return '';
}

// 메뉴 · 상태 줄처럼 좁은 자리에 쓰는 짧은 말.
export function shortBlockReason(imageMode, currentMode) {
  if (!loadBlockReason(imageMode, currentMode)) return '';
  const image = norm(imageMode);
  return image ? `${modeLabel(image)} 그림 · 불러오기 막힘` : '모드 불명 · 불러오기 막힘';
}
