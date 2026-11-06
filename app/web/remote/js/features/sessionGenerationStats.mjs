// 이번 세션의 생성 수. 분당 생성 속도 `(1.9/m)` 는 거뒀다(사용자 지정 2026-11-06 - "거추장스러움").
// 수는 남긴다 - 휴대폰에서는 이 알약이 히스토리 레일을 여는 단추다.
export function createSessionGenerationStats({
  statsGenCount,
}) {
  let total = 0;

  function update() {
    if (!statsGenCount) return;
    statsGenCount.textContent = String(total);
  }

  function record() {
    total += 1;
    update();
  }

  return {
    record,
    update,
  };
}
