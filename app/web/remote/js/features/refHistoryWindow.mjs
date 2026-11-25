/**
 * 히스토리 그림의 '레퍼런스 정보' 창(사용자 2026-11-25) - 결과 우클릭 › 레퍼런스 정보.
 *
 * - 무엇을 실었나: CR 모듈 칸(`_executed_reference_slots`) · 프롬프트 `ref:` 호출(`ref_prompt_picks`).
 *   둘 다 생성 때 서버가 남긴 짧은 기록이다(그림 base64 없음). 이 세션의 히스토리 그림만 가진다 -
 *   기록이 없는 그림은 메뉴가 안 뜬다(사용자 지정: 바깥 그림은 신경 쓰지 않는다).
 * - 줄마다: 썸네일 · 어디서(CR 칸 N / ref: 메인 / ref: 캐릭터 Cn) · 이름 · 유형 · 강도 · Fidelity · 넣은 글 ·
 *   못 간 까닭. [보관함] = REFERENCE 창에서 그 그림을 찾는다 · 머리줄 [Reference] = REFERENCE 창을 연다.
 * - 떠 있는 창은 draggablePanel 로(사용자 지정 사양).
 */

const TYPE_LABEL = {
  costume: 'Outfit', style: 'Style', 'character&style': 'Char&Style', 'character&style_anyoutfit': 'Char&Style',
  character: 'Character', character_mainoutfit: 'Character',
};
const SAME_OUTFIT_OFF = new Set(['character&style_anyoutfit', 'character']);

function num(value, digits = 2) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '';
  return Number.isInteger(n) ? n.toFixed(1) : String(Math.round(n * 10 ** digits) / 10 ** digits);
}

/** 기록 두 가지를 보여 줄 줄로 - 모듈 칸 먼저(요청에 실리는 차례와 같다). */
export function referenceRows(params) {
  const source = params && typeof params === 'object' ? params : {};
  const rows = [];
  for (const slot of Array.isArray(source._executed_reference_slots) ? source._executed_reference_slots : []) {
    if (!slot || typeof slot !== 'object') continue;
    const type = String(slot.reference_type || '');
    rows.push({
      where: `CR 칸 ${slot.slot ?? '?'}`,
      name: String(slot.name || String(slot.file_hash || '').slice(0, 16)),
      fileHash: String(slot.file_hash || ''),
      group: type === 'costume' ? 'outfit' : (type === 'style' ? 'style' : 'character'),
      type, strength: slot.strength, fidelity: slot.fidelity,
      blocked: String(slot.blocked || ''),
      module: true,
    });
  }
  for (const pick of Array.isArray(source.ref_prompt_picks) ? source.ref_prompt_picks : []) {
    if (!pick || typeof pick !== 'object') continue;
    const where = pick.scope === 'char' ? `ref: 캐릭터 C${Number(pick.slot || 0) + 1}` : 'ref: 메인';
    const wild = pick.mode === 'random' || pick.mode === 'sequential';
    rows.push({
      where,
      // 막혀서 고르지 않은 호출은 그림이 없다 - 부른 글 그대로
      name: String(pick.name || pick.token || ''),
      folder: pick.name ? String(pick.folder || '') : '',
      fileHash: String(pick.file_hash || ''),
      group: String(pick.group || ''),
      type: String(pick.reference_type || ''),
      strength: pick.strength, fidelity: pick.fidelity,
      blocked: String(pick.blocked || ''),
      token: String(pick.token || ''),
      wild: wild ? (pick.mode === 'sequential' ? '차례로' : '무작위') : '',
      prompt: String(pick.prompt || ''),
      uc: String(pick.uc || ''),
      promptApplied: Boolean(pick.prompt_applied),
    });
  }
  return rows;
}

export function createRefHistoryWindow({
  document: doc,
  window: win = globalThis.window,
  escHtml,
  loadDraggablePanel,          // () => Promise<module with createDraggablePanel>
  openReference = () => {},    // ({group, fileHash} | null) => void - REFERENCE 창
}) {
  let panel = null;
  let ready = null;
  let rows = [];

  function ensurePanel() {
    if (ready) return ready;
    ready = loadDraggablePanel().then(({createDraggablePanel}) => {
      panel = createDraggablePanel({
        document: doc, window: win, title: '레퍼런스 정보', variant: 'rhw', storageKey: 'ref-history',
        width: 380, height: 380, minWidth: 300, minHeight: 160, maxWidth: 640, resizable: true, escHtml,
      });
      panel.slot.innerHTML = `<span class="rhw-count" data-rhw-count></span>`
        + `<button type="button" class="rhw-open" data-rhw-open data-naia-title="REFERENCE 창(Char Ref 보관함)을 엽니다">Reference</button>`;
      panel.el.addEventListener('click', onClick);
      return panel;
    });
    return ready;
  }

  function thumbUrl(fileHash) {
    return `/api/module-storage/character-reference/thumb?${new URLSearchParams({file_hash: fileHash})}`;
  }

  function rowHtml(row, index) {
    const title = row.folder ? `${row.folder} · ${row.name}` : row.name;
    const meta = [];
    if (row.wild) meta.push(`${row.token} 에서 ${row.wild}`);
    if (row.type) meta.push(TYPE_LABEL[row.type] || row.type);
    if (row.strength != null && num(row.strength)) meta.push(`강도 ${num(row.strength)}`);
    if (row.fidelity != null && num(row.fidelity)) meta.push(`Fidelity ${num(row.fidelity)}`);
    let lines = `<div class="rhw-meta">${escHtml(meta.join(' · '))}</div>`;
    if (row.blocked) {
      lines += `<div class="rhw-line is-blocked">안 감 - ${escHtml(row.blocked)}</div>`;
    } else if (row.module) {
      lines += '<div class="rhw-line is-dim">넣는 글 없음(모듈 칸)</div>';
    } else if (!row.promptApplied) {
      lines += '<div class="rhw-line is-dim">넣는 글 없음 - 그림만 갔습니다</div>';
    } else {
      if (row.prompt) lines += `<div class="rhw-line">${escHtml(row.prompt)}</div>`;
      if (row.uc) lines += `<div class="rhw-line is-uc">UC: ${escHtml(row.uc)}</div>`;
    }
    if (!row.blocked && SAME_OUTFIT_OFF.has(row.type)) lines += '<div class="rhw-line is-dim">같은 옷 유지 끔</div>';
    const thumb = row.fileHash
      ? `<img class="rhw-thumb" src="${escHtml(thumbUrl(row.fileHash))}" alt="" draggable="false" loading="lazy" data-rhw-img>`
      : '<span class="rhw-thumb is-empty" aria-hidden="true"></span>';
    const find = row.fileHash
      ? `<button type="button" class="rhw-find" data-rhw-find="${index}" data-naia-title="REFERENCE 보관함에서 이 그림을 찾습니다">보관함</button>`
      : '';
    return `<div class="rhw-row${row.blocked ? ' is-blocked' : ''}">${thumb}`
      + `<div class="rhw-body"><div class="rhw-title"><span class="rhw-where">${escHtml(row.where)}</span>`
      + `<span class="rhw-name">${escHtml(title)}</span></div>${lines}</div>${find}</div>`;
  }

  function render() {
    if (!panel) return;
    const sent = rows.filter(row => !row.blocked).length;
    const count = panel.slot.querySelector('[data-rhw-count]');
    if (count) count.textContent = rows.length === sent ? `${rows.length}개` : `${rows.length}개 · ${sent}개 감`;
    panel.body.innerHTML = rows.length
      ? `<div class="rhw-list">${rows.map(rowHtml).join('')}</div>`
      : '<div class="rhw-empty">이 그림에는 레퍼런스 기록이 없습니다.</div>';
    // 보관함에서 지운 그림은 썸네일이 안 온다 - 빈 칸으로
    panel.body.querySelectorAll('[data-rhw-img]').forEach(img => {
      img.addEventListener('error', () => img.classList.add('is-empty'), {once: true});
    });
  }

  function onClick(event) {
    const target = event.target instanceof win.Element ? event.target : null;
    if (!target) return;
    if (target.closest('[data-rhw-open]')) { openReference(null); return; }
    const find = target.closest('[data-rhw-find]');
    if (find) {
      const row = rows[Number(find.dataset.rhwFind)];
      if (row) openReference({group: row.group || 'character', fileHash: row.fileHash});
    }
  }

  async function open(params) {
    rows = referenceRows(params);
    await ensurePanel();
    render();
    panel.open();
  }

  return {open, close: () => panel?.close(), isOpen: () => !!panel?.isOpen()};
}
