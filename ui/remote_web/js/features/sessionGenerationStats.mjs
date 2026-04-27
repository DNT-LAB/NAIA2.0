export function createSessionGenerationStats({
  statsGenCount,
  now = () => Date.now(),
}) {
  let total = 0;
  const timestamps = [];

  function update() {
    if (!statsGenCount) return;
    const current = now();
    while (timestamps.length > 0 && timestamps[0] < current - 3600000) {
      timestamps.shift();
    }

    const tenMinAgo = current - 600000;
    const recent = timestamps.filter(timestamp => timestamp > tenMinAgo);
    let rateStr = '';
    if (recent.length >= 2) {
      const windowMs = current - recent[0];
      if (windowMs >= 60000) {
        rateStr = ' (' + (recent.length / (windowMs / 60000)).toFixed(1) + '/m)';
      }
    }
    statsGenCount.textContent = total + rateStr;
  }

  function record() {
    total += 1;
    timestamps.push(now());
    update();
  }

  return {
    record,
    update,
  };
}
