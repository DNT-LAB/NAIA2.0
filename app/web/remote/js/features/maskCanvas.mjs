// 인페인트 마스크 캔버스 엔진 - 인스턴스 기반.
//
// img2imgPanel.mjs의 8px 그리드 모델·브러시·Bresenham·PNG export와 동일한
// 알고리즘이지만, 고정 DOM id/전역 onclick/setModuleParam 결합이 없어 여러
// 인스턴스가 공존할 수 있다. 이번 라운드 소비자는 캐릭터 생성 벤치뿐이다 -
// img2imgPanel 이관은 golden test 확보 후 별도 단계(B3, Codex 판례: 라이브
// 상태머신 이관 금지).
//
// 계약:
// - canvas 내부 해상도 = 베이스 이미지 원본 크기(width x height). 표시 크기는
//   CSS가 맡고, 포인터 좌표는 getBoundingClientRect 비율로 역산한다.
// - 셀 그리드는 8px(NAI 마스크 블록과 동일 단위). export는 풀사이즈 흑백 PNG
//   (칠함=255) - 백엔드 utils/inpaint_mask.py가 1/8로 줄이고 검증한다.
// - 우클릭(또는 mode='erase')은 지우개. contextmenu는 막는다.

const DEFAULT_CELL_SIZE = 8;
const DEFAULT_OVERLAY_COLOR = 'rgba(0, 0, 255, 0.47)';

export function createMaskEngine({
  canvas,
  width,
  height,
  cellSize = DEFAULT_CELL_SIZE,
  overlayColor = DEFAULT_OVERLAY_COLOR,
  brushSize = 48,
  mode = 'paint',
  onChange = null,
} = {}) {
  if (!canvas || typeof canvas.getContext !== 'function') {
    throw new Error('createMaskEngine requires a canvas element');
  }
  const sourceWidth = Math.max(1, Math.floor(Number(width) || 1));
  const sourceHeight = Math.max(1, Math.floor(Number(height) || 1));
  const gridWidth = Math.max(1, Math.floor(sourceWidth / cellSize));
  const gridHeight = Math.max(1, Math.floor(sourceHeight / cellSize));
  const cells = new Uint8Array(gridWidth * gridHeight);
  let currentBrush = Math.max(cellSize, Number(brushSize) || 48);
  let currentMode = mode === 'erase' ? 'erase' : 'paint';
  let drawing = false;
  let lastPoint = null;
  let detachFns = [];

  canvas.width = sourceWidth;
  canvas.height = sourceHeight;

  function notify() {
    if (typeof onChange === 'function') onChange(count());
  }

  function count() {
    let painted = 0;
    for (let i = 0; i < cells.length; i += 1) {
      if (cells[i]) painted += 1;
    }
    return painted;
  }

  function render() {
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = overlayColor;
    for (let gy = 0; gy < gridHeight; gy += 1) {
      for (let gx = 0; gx < gridWidth; gx += 1) {
        if (!cells[gy * gridWidth + gx]) continue;
        const x = gx * cellSize;
        const y = gy * cellSize;
        ctx.fillRect(
          x,
          y,
          Math.min(cellSize, sourceWidth - x),
          Math.min(cellSize, sourceHeight - y),
        );
      }
    }
  }

  function canvasPoint(event) {
    const rect = canvas.getBoundingClientRect();
    return {
      x: ((event.clientX - rect.left) / Math.max(1, rect.width)) * canvas.width,
      y: ((event.clientY - rect.top) / Math.max(1, rect.height)) * canvas.height,
    };
  }

  function pointToGrid(point) {
    return {
      x: Math.max(0, Math.min(gridWidth - 1, Math.floor(point.x / cellSize))),
      y: Math.max(0, Math.min(gridHeight - 1, Math.floor(point.y / cellSize))),
    };
  }

  function paintBrush(centerX, centerY, erase) {
    const brushGrid = Math.max(1, Math.floor(currentBrush / cellSize));
    const half = Math.floor(brushGrid / 2);
    const value = erase ? 0 : 1;
    for (let dy = -half; dy <= half; dy += 1) {
      const y = centerY + dy;
      if (y < 0 || y >= gridHeight) continue;
      for (let dx = -half; dx <= half; dx += 1) {
        const x = centerX + dx;
        if (x < 0 || x >= gridWidth) continue;
        cells[y * gridWidth + x] = value;
      }
    }
  }

  function paintLine(x0, y0, x1, y1, erase) {
    let x = x0;
    let y = y0;
    const dx = Math.abs(x1 - x0);
    const dy = Math.abs(y1 - y0);
    const sx = x0 < x1 ? 1 : -1;
    const sy = y0 < y1 ? 1 : -1;
    let error = dx - dy;
    for (;;) {
      paintBrush(x, y, erase);
      if (x === x1 && y === y1) break;
      const error2 = 2 * error;
      if (error2 > -dy) {
        error -= dy;
        x += sx;
      }
      if (error2 < dx) {
        error += dx;
        y += sy;
      }
    }
  }

  function drawPoint(point, erase) {
    const grid = pointToGrid(point);
    paintBrush(grid.x, grid.y, erase);
    render();
    notify();
  }

  function drawStroke(from, to, erase) {
    if (!from) {
      drawPoint(to, erase);
      return;
    }
    const start = pointToGrid(from);
    const end = pointToGrid(to);
    paintLine(start.x, start.y, end.x, end.y, erase);
    render();
    notify();
  }

  function attach() {
    if (detachFns.length) return;
    const on = (type, handler, options) => {
      canvas.addEventListener(type, handler, options);
      detachFns.push(() => canvas.removeEventListener(type, handler, options));
    };
    on('contextmenu', event => event.preventDefault());
    on('pointerdown', event => {
      event.preventDefault();
      drawing = true;
      lastPoint = canvasPoint(event);
      try { canvas.setPointerCapture(event.pointerId); } catch { /* noop */ }
      drawPoint(lastPoint, event.button === 2 || currentMode === 'erase');
    });
    on('pointermove', event => {
      if (!drawing) return;
      event.preventDefault();
      const point = canvasPoint(event);
      drawStroke(lastPoint, point, event.buttons === 2 || currentMode === 'erase');
      lastPoint = point;
    });
    const stop = event => {
      if (!drawing) return;
      drawing = false;
      lastPoint = null;
      if (event?.pointerId !== undefined) {
        try { canvas.releasePointerCapture(event.pointerId); } catch { /* noop */ }
      }
    };
    on('pointerup', stop);
    on('pointercancel', stop);
    on('pointerleave', () => {
      drawing = false;
      lastPoint = null;
    });
    render();
  }

  function detach() {
    detachFns.forEach(fn => fn());
    detachFns = [];
    drawing = false;
    lastPoint = null;
  }

  function clear() {
    cells.fill(0);
    render();
    notify();
  }

  /** 풀사이즈 흑백 마스크 PNG(칠함=255). 백엔드가 1/8로 줄여 검증한다. */
  function toDataUrl() {
    const out = document.createElement('canvas');
    out.width = sourceWidth;
    out.height = sourceHeight;
    const ctx = out.getContext('2d');
    const image = ctx.createImageData(sourceWidth, sourceHeight);
    for (let y = 0; y < sourceHeight; y += 1) {
      for (let x = 0; x < sourceWidth; x += 1) {
        const gx = Math.floor(x / cellSize);
        const gy = Math.floor(y / cellSize);
        const masked = gx < gridWidth && gy < gridHeight
          ? cells[gy * gridWidth + gx] > 0
          : false;
        const value = masked ? 255 : 0;
        const i = (y * sourceWidth + x) * 4;
        image.data[i] = value;
        image.data[i + 1] = value;
        image.data[i + 2] = value;
        image.data[i + 3] = 255;
      }
    }
    ctx.putImageData(image, 0, 0);
    return {dataUrl: out.toDataURL('image/png'), count: count()};
  }

  return {
    attach,
    detach,
    clear,
    count,
    toDataUrl,
    render,
    setBrushSize(value) {
      currentBrush = Math.max(cellSize, Number(value) || currentBrush);
    },
    setMode(value) {
      currentMode = value === 'erase' ? 'erase' : 'paint';
    },
    getMode() { return currentMode; },
    getBrushSize() { return currentBrush; },
    get width() { return sourceWidth; },
    get height() { return sourceHeight; },
    // 테스트 훅: 그리드에 직접 칠한다(포인터 이벤트 없이 count/export 검증).
    __testPaintCell(gx, gy, erase = false) {
      paintBrush(
        Math.max(0, Math.min(gridWidth - 1, gx)),
        Math.max(0, Math.min(gridHeight - 1, gy)),
        erase,
      );
      render();
      notify();
    },
  };
}
