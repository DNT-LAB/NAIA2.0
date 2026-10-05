/**
 * Snapshot 창 (Tools & Assistants 줄의 [Snapshot] 단추).
 *
 * 스냅샷 = 지금 NAI 모드의 설정을 **원샷으로** 담은 프로젝트 한 벌이다:
 * Quick Preset 이 담던 것(프롬프트 엔지니어링 · 생성 설정 · 프롬프트 · 네거티브) +
 * 캐릭터(프롬프트 · 좌표) + 조건부 프롬프트 + Vibe Transfer · Character Reference +
 * 그림 한 장(필수) + 고르면 Tag Filter 와 데이터셋 사본.
 * 계약은 `docs/SNAPSHOT_SRS_2026_10_04.md` §5 · §6 · §10 · §11 · §12.
 *
 * ⚠️ **이 창은 담지 않는다**(사용자 지정 2026-10-05). 저장은 결과 그림 우클릭 > [NAI] 스냅샷 저장이 여는
 *    저장 창(`snapshotSaveWindow.mjs`) 한 길뿐이다 - 여기는 찾고 · 정리하고 · 불러오는 자리다.
 *    다만 저장을 **보내는 입구**(`save`)는 여기 있다: "같은 이름이 있다" 되묻기의 재전송을 이 창이 쥔다.
 *
 * 화면은 Interactive 의 Scene 창과 **같은 Finder 배치**다(사용자 지정 2026-10-04):
 *   [카테고리][하위 카테고리][카드][상세]
 * 카테고리는 둘 다 사용자가 만든다. 모델(V4.5 · V5)은 카테고리가 아니라 **카드 위의 칩**이다.
 * 생김새도 그 창의 것(`.ia-sc-*`)을 그대로 입는다 - 같은 손놀림이면 같은 모양이어야 한다.
 * V5 Scene(Fn > V5 Scene) · Interactive Scene 과는 **별개 기능**이다 - 저장소도, 입구도 따로다.
 *
 * 불러오기:
 *   · 카드를 누르면 오른쪽 상세에 **든 항목이 체크 목록으로** 나온다. 체크한 것만 불러오고,
 *     스냅샷마다 마지막 선택을 기억한다.
 *   · 프롬프트 · 네거티브 · 생성 설정 · 프롬프트 엔지니어링 가운데 하나라도 불러오면 현재
 *     프리셋은 `*snapshot` 이라는 임시 항목이 된다 - 떠나는 프리셋은 서버가 저장한 뒤에 넘긴다.
 *
 * ⚠️ 조작은 전부 범용 `setModuleParam('snapshot', …)` 을 탄다 - 새 WS 메시지 타입을
 *    만들지 않는다(웹 스모크 계약이 타입을 순서대로 센다). 그림만 HTTP 다.
 * ⚠️ 창은 **body 직계**다. `.viewer-wrapper` 는 `z-index:0 + isolation:isolate` 라 그 안에
 *    넣으면 좌측 컨트롤이 위를 덮는다(Scene 창이 세 번 겪은 함정).
 */

// 스냅샷마다 **마지막으로 체크해 둔 항목**을 기억한다(사용자 지정 2026-10-04). 꺼 둔 것만 적는다 -
// 나중에 항목이 늘어도 새 항목은 켜진 채로 나온다. 화면의 선택이라 서버가 아니라 여기 둔다.
const PICKS_KEY = 'naia.snapshot.picks.v1';
// 끌어 옮길 때 싣는 자료형. **우리 것만 받는다** - 파일이나 다른 창의 카드(Scene 등)를
// 떨어뜨렸을 때 카테고리가 반응하면 안 된다.
const DND_MIME = 'application/x-naia-snapshot';

// 불러올 때 고르는 항목. 차례 = 화면 차례. 키는 백엔드의 `sections` 와 같다(SRS §10).
export const SNAPSHOT_PICK_ITEMS = [
  ['prompt', '프롬프트', '메인 프롬프트를 이 스냅샷의 것으로 바꿉니다'],
  ['negative', '네거티브', '네거티브 프롬프트를 이 스냅샷의 것으로 바꿉니다'],
  ['params', '생성 설정', '모델 · 해상도 · 스텝 · CFG · 샘플러 · 시드 등'],
  ['prompt_engineering', '프롬프트 엔지니어링', 'Prefix · Postfix · Auto-Hide · 전처리 옵션'],
  ['characters', '캐릭터', '캐릭터 프롬프트 · 좌표 · Connect. 지금 켜 둔 슬롯은 비활성으로 내려갑니다'],
  ['conditional', '조건부', '조건부 프롬프트 규칙. 지금 규칙은 저장해 두고 넘어갑니다'],
  ['vibe_transfer', 'Vibe', 'Vibe Transfer. 스냅샷에 없는 지금 항목은 지우지 않고 끕니다'],
  ['character_reference', 'Reference', 'Character Reference. 스냅샷에 없는 지금 항목은 지우지 않고 끕니다'],
  ['search', '데이터셋', 'Tag Filter 와 데이터셋 사본. 지금 불러온 데이터셋이 이것으로 바뀝니다'],
];
const PICK_ITEMS = SNAPSHOT_PICK_ITEMS;
// 옛 판 백엔드는 프리셋 넷을 `preset` 하나로 알려 준다 - 넷으로 펴서 읽는다.
const PRESET_PARTS = ['prompt', 'negative', 'params', 'prompt_engineering'];

const SECTION_LABELS = {
  preset: '프리셋',
  ...Object.fromEntries(PICK_ITEMS.map(([key, label]) => [key, label])),
};

/** 저장 이름을 백엔드와 **같은 규칙**으로 다듬는다. 저장 창(snapshotSaveWindow)도 이것을 쓴다.
 *
 * ⚠️ SSOT 는 `core/snapshot_store` 다. 여기서 흉내 내는 이유는 덮어쓰기 확인을
 *    **보내기 전에** 하려는 것이다. 어긋나도 서버가 `overwrite_prompt` 로 되묻는다.
 */
export function sanitizeSnapshotName(value) {
  return String(value ?? '')
    .replace(/[<>:"/\\|?*]/g, '')
    .trim().replace(/[.\s]+$/g, '')
    .trim();
}

export function createSnapshotPanel({
  document,
  escHtml, showToast, setModuleParam,
  // ⚠️ `window.prompt` / `window.confirm` 을 쓰지 않는다 - Electron 은 `prompt` 를 구현하지
  //    않아 아무 일도 안 일어난다(V5 Scene 이 밟은 함정). 앱 자체 대화상자를 받아 쓴다.
  showPromptDialog = null,
  showConfirmDialog = null,
  // 저장 · 불러오기 직전에 **아직 안 보낸 편집**(디바운스 중인 프롬프트 · Prefix)을 밀어 보낸다.
  // 한 소켓에서 순서대로 처리되므로, 이게 먼저 도착해야 스냅샷이 화면과 같은 것을 담고
  // 떠나는 프리셋이 마지막 편집까지 저장된다(프리셋 전환이 같은 일을 한다).
  flushEdits = null,
}) {
  let lastState = null;
  let popEl = null;
  let popOpen = false;
  let menuEl = null;
  // Finder 의 선택. `curTop` 이 카테고리, `curSub` 이 그 아래 하위 카테고리. 둘 다 비면 전체.
  // `curNone` 은 '분류 없음'(아직 정리하지 않은 것)만 보는 상태 - 빈 문자열로는 '전체' 와
  // 구분할 수 없어서 따로 둔다.
  let curTop = '';
  let curSub = '';
  let curNone = false;
  let query = '';
  let previewName = '';        // 오른쪽 상세에 편 스냅샷
  // 서버가 "같은 이름이 있다" 고 되물었을 때 다시 보낼 값. 이름 다듬기가 서버와 어긋나
  // 화면의 확인을 그냥 지나친 경우의 뒷문이다.
  let pendingSave = null;
  let pendingSelect = '';      // 방금 담은 이름 - 목록에 나타나면 그 카드를 편다
  let dragName = '';
  let edgeTimer = 0;

  const esc = value => escHtml(String(value ?? ''));

  // ── 기억(localStorage) ──────────────────────────────────────────────────
  function readPicks() {
    try {
      const data = JSON.parse(globalThis.localStorage?.getItem(PICKS_KEY) || '{}');
      return (data && typeof data === 'object' && !Array.isArray(data)) ? data : {};
    } catch (_) { return {}; }
  }

  function writePicks(data) {
    try { globalThis.localStorage?.setItem(PICKS_KEY, JSON.stringify(data)); } catch (_) { /* 사생활 모드 */ }
  }

  /** 이 스냅샷에 실제로 든 항목(화면 차례). */
  function availableKeys(item) {
    const raw = new Set(Array.isArray(item?.sections) ? item.sections.map(String) : []);
    if (raw.has('preset')) PRESET_PARTS.forEach(key => raw.add(key));
    return PICK_ITEMS.map(([key]) => key).filter(key => raw.has(key));
  }

  /** 불러올 항목 = 든 것 가운데 꺼 두지 않은 것. 처음 여는 스냅샷은 전부 켜져 있다. */
  function pickedKeys(item) {
    const off = readPicks()[String(item?.name || '')];
    const offSet = new Set(Array.isArray(off) ? off.map(String) : []);
    return availableKeys(item).filter(key => !offSet.has(key));
  }

  function rememberPick(name, key, on) {
    const data = readPicks();
    const off = new Set(Array.isArray(data[name]) ? data[name].map(String) : []);
    if (on) off.delete(key); else off.add(key);
    if (off.size) data[name] = [...off]; else delete data[name];
    writePicks(data);
  }

  /** 그 이름의 기억을 지운다. 지웠거나 같은 이름으로 다시 담으면 **다른 스냅샷**이다 -
   *  옛 체크가 되살아나면 사용자가 고른 적 없는 선택으로 불러오게 된다. */
  function forgetPicks(name) {
    const data = readPicks();
    if (!(name in data)) return;
    delete data[name];
    writePicks(data);
  }

  /** 이름을 바꾸면 기억도 따라간다 - 같은 스냅샷이다. */
  function movePicks(from, to) {
    const data = readPicks();
    if (!(from in data)) return;
    data[to] = data[from];
    delete data[from];
    writePicks(data);
  }

  // ── 도우미 ──────────────────────────────────────────────────────────────
  const sanitizeName = sanitizeSnapshotName;

  const snapshots = () => (Array.isArray(lastState?.snapshots) ? lastState.snapshots : []);
  const folders = () => (Array.isArray(lastState?.folders) ? lastState.folders : []);
  const findSnapshot = name => snapshots().find(item => String(item.name) === String(name));
  const findFolder = id => folders().find(folder => String(folder.id) === String(id));

  /** 스냅샷의 카테고리 id. 지워진 카테고리를 가리키면 '분류 없음' 으로 읽는다 -
   *  카테고리를 지워도 스냅샷은 남는다(표식일 뿐이다). */
  function folderOf(item) {
    const id = String(item?.folder || '');
    return id && findFolder(id) ? id : '';
  }

  /** `대 / 소` 로 짚어 준다 - 카테고리를 고르면 하위까지 다 깔리므로 이름만으로는 어느 하위인지 모른다. */
  function folderLabel(id) {
    const folder = findFolder(id);
    if (!folder) return '';
    const up = folder.parent ? findFolder(folder.parent) : null;
    return up ? `${up.name} / ${folder.name}` : String(folder.name || '');
  }

  function searchText(item) {
    const info = item.detail || {};
    const chars = Array.isArray(info.characters) ? info.characters.map(entry => entry?.prompt || '') : [];
    return [item.name, item.description, item.model_label, info.prompt, info.pre_prompt, info.post_prompt, ...chars]
      .map(value => String(value || '')).join('\n').toLowerCase();
  }

  /** 지금 칸에 깔 스냅샷. 카테고리를 고르면 **그 하위까지** 다 깔린다. */
  function visibleSnapshots() {
    const words = query.toLowerCase().split(/[,\s]+/).map(word => word.trim()).filter(Boolean);
    const subIds = curTop ? new Set(folders().filter(f => String(f.parent || '') === curTop).map(f => String(f.id))) : null;
    return snapshots().filter(item => {
      const fid = folderOf(item);
      if (curNone) { if (fid) return false; }
      else if (curSub) { if (fid !== curSub) return false; }
      else if (curTop) { if (fid !== curTop && !subIds.has(fid)) return false; }
      if (!words.length) return true;
      const text = searchText(item);
      return words.every(word => text.includes(word));
    });
  }

  function countIn(id) {
    const subIds = new Set(folders().filter(f => String(f.parent || '') === String(id)).map(f => String(f.id)));
    return snapshots().filter(item => {
      const fid = folderOf(item);
      return fid === String(id) || subIds.has(fid);
    }).length;
  }

  function confirmBox(message, options) {
    return (typeof showConfirmDialog === 'function')
      ? Promise.resolve(showConfirmDialog(message, options))
      : Promise.resolve(globalThis.confirm(message));
  }

  async function askText(title, initial, placeholder) {
    if (typeof showPromptDialog !== 'function') return null;
    const got = await showPromptDialog('', {
      title, defaultValue: String(initial || ''), placeholder: placeholder || '',
      okText: '확인', cancelText: '취소',
    });
    if (got === null || got === undefined || got === false) return null;
    return String(got).trim();
  }

  function flush() {
    try { if (typeof flushEdits === 'function') flushEdits(); } catch (_) { /* 저장을 막지 않는다 */ }
  }

  /** `MM-DD HH:mm`(이 기기의 시각). 서버는 UTC 로 적는다 - 글자를 그대로 자르면 9시간 어긋난다. */
  function shortDate(iso) {
    const when = new Date(String(iso || ''));
    if (Number.isNaN(when.getTime())) return '';
    const two = value => String(value).padStart(2, '0');
    return `${two(when.getMonth() + 1)}-${two(when.getDate())} ${two(when.getHours())}:${two(when.getMinutes())}`;
  }

  function sizeText(bytes) {
    const n = Number(bytes || 0);
    if (!(n > 0)) return '';
    if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(n >= 100 * 1024 * 1024 ? 0 : 1)}MB`;
    return `${Math.max(1, Math.round(n / 1024))}KB`;
  }

  /** 모델 배지. Quick Preset 목록과 같은 옷(`.custom-select-model-tag`)을 입는다. */
  function modelTag(item) {
    if (!item?.model_label) return '';
    return `<span class="custom-select-model-tag" data-family="${esc(item.model_family || '')}"`
      + ` data-variant="${esc(item.model_variant || '')}">${esc(item.model_label)}</span>`;
  }

  /** 카드 아래 한 줄 - 프리셋 말고 **무엇이 더 들었나**. */
  function metaBits(item) {
    const bits = [];
    const chars = Number(item.character_count || 0);
    if (chars) bits.push(`C${chars}`);
    if (item.conditional_enabled) bits.push('조건부');
    const vibes = Number(item.vibe_count || 0);
    if (vibes) bits.push(`Vibe ${vibes}`);
    const refs = Number(item.reference_count || 0);
    if (refs) bits.push(`Ref ${refs}`);
    if (item.search) bits.push(`${Number(item.search.rows || 0).toLocaleString()}행`);
    return bits;
  }

  // ── 창 ──────────────────────────────────────────────────────────────────
  function ensurePop() {
    if (popEl && document.body.contains(popEl)) return popEl;
    popEl = document.createElement('div');
    popEl.className = 'ia-sc-pop snap-pop';
    popEl.hidden = true;
    document.body.appendChild(popEl);
    popEl.addEventListener('click', onClick);
    popEl.addEventListener('input', onInput);
    popEl.addEventListener('change', onChange);
    popEl.addEventListener('contextmenu', onContextMenu);
    popEl.addEventListener('dragstart', onDragStart);
    popEl.addEventListener('dragend', onDragEnd);
    popEl.addEventListener('dragover', onDragOver);
    popEl.addEventListener('dragleave', onDragLeave);
    popEl.addEventListener('drop', onDrop);
    return popEl;
  }

  function cardHtml(item) {
    const name = String(item.name || '');
    const active = name && name === String(lastState?.active || '');
    const fid = folderOf(item);
    const bits = [fid ? folderLabel(fid) : '', ...metaBits(item)].filter(Boolean);
    // 카드에는 **단추를 두지 않는다**(Scene 창과 같은 결정). 왼쪽 클릭은 상세, 오른쪽 클릭은
    // 메뉴, 끌면 카테고리로 간다. 모델은 그림 위의 칩이다(사용자 지정).
    return `<div class="ia-sc-scard snap-card${previewName === name ? ' is-preview' : ''}${active ? ' is-active' : ''}"
      draggable="true" data-snap-act="preview" data-snap-name="${esc(name)}"
      data-naia-title="왼쪽: 자세히 · 오른쪽: 메뉴 · 끌어서 카테고리로">
      <div class="ia-sc-sthumb">${item.thumbnail_url
        ? `<img src="${esc(item.thumbnail_url)}" alt="" loading="lazy" decoding="async" draggable="false">` : ''}
        <div class="snap-card-top">${item.model_label ? `<span class="snap-top-chip">${modelTag(item)}</span>` : ''}${active
          ? '<span class="snap-top-chip is-active">불러옴</span>' : ''}</div>
      </div>
      <div class="ia-sc-sname" title="${esc(name)}">${esc(name)}</div>
      <div class="ia-sc-smeta">${esc(bits.join(' · ')) || '&nbsp;'}</div>
    </div>`;
  }

  function line(label, value) {
    const text = String(value || '');
    return text
      ? `<div class="snap-pv-line"><span class="ia-sc-pv-lab">${esc(label)}</span><code>${esc(text)}</code></div>`
      : '';
  }

  function previewHtml() {
    const item = previewName ? findSnapshot(previewName) : null;
    if (!item) {
      return '<div class="ia-sc-hint">카드를 누르면 여기에서 자세히 보고, 불러올 항목을 고릅니다.</div>';
    }
    const name = String(item.name || '');
    const info = item.detail || {};
    const characters = Array.isArray(info.characters) ? info.characters : [];
    const wrongMode = !!(item.mode && item.mode !== lastState?.current_mode);
    const active = name === String(lastState?.active || '');
    const available = availableKeys(item);
    const picked = new Set(pickedKeys(item));
    // 셋은 **0 도 적는다.** 비어 있는 채로 담긴 구역도 불러올 수 있고, 그건 "지금 켜진 것을 끈다" 는
    // 뜻이다(스냅샷에 없는 항목은 꺼진다) - 숫자가 없으면 무엇이 들었는지 모르고 체크하게 된다.
    const counts = {
      characters: String(Number(item.character_count || 0)),
      vibe_transfer: String(Number(item.vibe_count || 0)),
      character_reference: String(Number(item.reference_count || 0)),
      search: item.search
        ? `${Number(item.search.rows || 0).toLocaleString()}행${sizeText(item.search.bytes) ? ` · ${sizeText(item.search.bytes)}` : ''}`
        : '',
    };
    const picks = PICK_ITEMS.filter(([key]) => available.includes(key)).map(([key, label, tip]) => `
        <label class="snap-pick" data-naia-title="${esc(tip)}">
          <input type="checkbox" data-snap-pick="${esc(key)}"${picked.has(key) ? ' checked' : ''}>${esc(label)}${counts[key]
            ? ` <span class="snap-pick-n">${esc(counts[key])}</span>` : ''}</label>`).join('');
    const charBlocks = characters.map((entry, i) => {
      const link = Number(entry.connect_to || 0);
      const pos = entry.position ? `${entry.position.x} , ${entry.position.y}` : '자동';
      return `<div class="snap-pv-line"><span class="ia-sc-pv-lab">C${i + 1}${link ? ` → C${link}` : ''}<br>${esc(pos)}</span>`
        + `<code>${esc(entry.prompt || '(비어 있음)')}</code></div>`;
    }).join('');
    const sub = [
      item.resolution, item.steps ? `${item.steps} steps` : '', item.sampler,
      shortDate(item.saved_at || item.created_at),
      folderOf(item) ? folderLabel(folderOf(item)) : '',
    ].filter(Boolean).join(' · ');
    const sid = esc(name);
    // 불러오기 바는 **본문 밖**이다 - 안에 두면 프롬프트가 긴 스냅샷에서 끝까지 굴려야 나온다.
    return `<div class="ia-sc-pv-img">${item.thumbnail_url
        ? `<img src="${esc(item.thumbnail_url)}" alt="">`
        : '<span class="ia-sc-pv-noimg">그림이 없습니다</span>'}</div>
      <div class="ia-sc-pv-body">
        <div class="ia-sc-pv-title">${modelTag(item)} ${esc(name)}${active
          ? ' <span class="snap-active-tag" data-naia-title="지금 이 스냅샷을 불러온 상태입니다 (*snapshot)">불러옴</span>' : ''}</div>
        ${sub ? `<div class="snap-pv-sub">${esc(sub)}</div>` : ''}
        ${wrongMode ? `<div class="snap-blocker">${esc(item.mode)} 모드의 스냅샷입니다 — 지금 모드에서는 불러올 수 없습니다</div>` : ''}
        ${line('프롬프트', info.prompt)}
        ${line('네거티브', info.negative)}
        ${line('Prefix', info.pre_prompt)}
        ${line('Postfix', info.post_prompt)}
        ${charBlocks}
      </div>
      <div class="snap-pv-pickbox">
        <div class="ia-sc-pv-sec">불러올 항목</div>
        <div class="snap-picks" data-snap-picks="${sid}">${picks}</div>
      </div>
      <div class="ia-sc-pv-foot">
        <button type="button" class="ia-sc-btn is-main is-wide" data-snap-act="apply" data-snap-name="${sid}"${(wrongMode || !picked.size) ? ' disabled' : ''}
          data-naia-title="체크한 항목만 이 스냅샷의 값으로 바뀝니다. 프롬프트 · 네거티브 · 생성 설정 · 프롬프트 엔지니어링 가운데 하나라도 불러오면 지금 프리셋을 저장한 뒤 *snapshot 으로 넘어갑니다.">체크한 항목 불러오기</button>
        <button type="button" class="ia-sc-btn" data-snap-act="rename" data-snap-name="${sid}">이름</button>
        <button type="button" class="ia-sc-btn is-danger" data-snap-act="delete" data-snap-name="${sid}"
          data-naia-title="이 스냅샷을 폴더째 지웁니다 (되돌릴 수 없습니다)">삭제</button>
      </div>`;
  }

  /** 다시 그릴 때 들고 넘어갈 입력칸(치던 글 · 캐럿). 창을 통째로 다시 그리기 때문에
   *  안 챙기면 다른 창의 저장이 상태를 밀어 보내는 순간 글이 사라진다. */
  function captureInputs(el) {
    const keep = {};
    for (const key of ['snapSearch']) {
      const input = el.querySelector(`#${key}`);
      if (!input) continue;
      keep[key] = {
        value: input.value, focused: document.activeElement === input,
        start: input.selectionStart, end: input.selectionEnd,
      };
    }
    return keep;
  }

  function restoreInputs(el, keep) {
    for (const [key, saved] of Object.entries(keep)) {
      const input = el.querySelector(`#${key}`);
      if (!input) continue;
      if (saved.focused) {
        input.focus();
        try { input.setSelectionRange(saved.start, saved.end); } catch (_) { /* 범위를 못 쓰는 입력 */ }
      }
    }
  }

  function renderPop() {
    // 목록이 갈리면 메뉴가 가리키던 카드가 사라질 수 있다 - 먼저 닫는다.
    closeMenu();
    // 끌던 원본이 이 렌더로 사라지면 `dragend` 가 오지 않는다 - 여기서 버린다.
    dragName = '';
    stopEdge();
    const el = ensurePop();
    if (!popOpen) { el.hidden = true; el.innerHTML = ''; return; }
    el.hidden = false;
    const keep = captureInputs(el);
    const gridScroll = el.querySelector('.ia-sc-content')?.scrollTop || 0;
    const bodyScroll = el.querySelector('.ia-sc-pv-body')?.scrollTop || 0;
    const sameBody = el.querySelector('[data-snap-picks]')?.dataset.snapPicks === previewName;

    // 지워진 카테고리를 보고 있었으면 전체로 물러난다.
    if (curTop && !findFolder(curTop)) { curTop = ''; curSub = ''; }
    if (curSub && !findFolder(curSub)) curSub = '';
    if (previewName && !findSnapshot(previewName)) previewName = '';

    const all = snapshots();
    const tops = folders().filter(folder => !folder.parent);
    const subs = curTop ? folders().filter(folder => String(folder.parent || '') === curTop) : [];
    const noneCount = all.filter(item => !folderOf(item)).length;
    // `drop` 을 붙이면 그 자리에 카드를 떨어뜨려 옮길 수 있다. '전체' 는 담는 곳이 아니라
    // **보기**라서 뺀다. '분류 없음' 은 진짜 목적지다(분류를 푸는 자리).
    const row = (on, act, id, label, count, drop) =>
      `<button type="button" class="ia-sc-item${on ? ' is-on' : ''}" data-snap-act="${act}" data-fid="${esc(id)}"${
        drop ? ` data-snap-drop="${esc(drop)}"` : ''}><span class="snap-item-t">${esc(label)}</span>${
        count === '' ? '' : `<span class="snap-item-n">${esc(count)}</span>`}</button>`;

    const col1 = [
      row(!curTop && !curNone, 'top', '', '전체', all.length),
      ...tops.map(folder => row(curTop === String(folder.id), 'top', folder.id, folder.name, countIn(folder.id), folder.id)),
      row(curNone, 'top', 'none', '분류 없음', noneCount, 'none'),
      `<button type="button" class="ia-sc-item is-add" data-snap-act="folder-new" data-fid=""
         data-naia-title="카테고리를 만듭니다">+ 카테고리</button>`,
    ].join('');

    // 하위 칸은 **늘 자리를 지킨다**(사용자 지정 2026-10-04: 카테고리 · 하위 · 컨텐츠 세 칸).
    // 카테고리를 고르기 전에는 넣을 것이 없으니 안내만 둔다 - 칸이 생겼다 사라지면 카드가 출렁인다.
    const col2 = curTop
      ? [
          row(!curSub, 'sub', '', '전체보기', countIn(curTop)),
          ...subs.map(folder => row(curSub === String(folder.id), 'sub', folder.id, folder.name,
            all.filter(item => folderOf(item) === String(folder.id)).length, folder.id)),
          `<button type="button" class="ia-sc-item is-add" data-snap-act="folder-new" data-fid="${esc(curTop)}"
             data-naia-title="이 카테고리 안에 만듭니다">+ 하위</button>`,
        ].join('')
      : '<div class="ia-sc-hint">카테고리를 고르면 그 하위가 여기에 나옵니다.</div>';

    const target = curSub || curTop;
    const tools = target
      ? `<button type="button" class="ia-sc-btn" data-snap-act="folder-rename"
           data-naia-title="고른 카테고리의 이름을 바꿉니다">카테고리 이름</button>
         <button type="button" class="ia-sc-btn is-danger" data-snap-act="folder-del"
           data-naia-title="카테고리만 지웁니다 — 안의 스냅샷은 남습니다">카테고리 삭제</button>`
      : '';

    const rows = visibleSnapshots();
    el.innerHTML = `<div class="ia-sc-pop-box">
      <div class="ia-sc-pop-head">
        <span class="ia-sc-pop-title">Snapshot <span class="snap-title-hint">- 저장은 히스토리 이미지 우클릭 - [NAI] 스냅샷 저장 버튼을 누르세요.</span></span>
        <input type="text" class="ia-sc-search" id="snapSearch" placeholder="이름·태그로 찾기" value="${esc(query)}" autocomplete="off">
        ${tools}
        <button type="button" class="ia-sc-btn" data-snap-act="open-folder"
          data-naia-title="Snapshot 폴더를 탐색기에서 엽니다">폴더</button>
        <button type="button" class="ia-sc-btn" data-snap-act="close">닫기</button>
      </div>
      <div class="ia-sc-finder">
        <div class="ia-sc-col ia-sc-col1">${col1}</div>
        <div class="ia-sc-col ia-sc-col2">${col2}</div>
        <div class="ia-sc-col ia-sc-content">
          <div class="ia-sc-grid">${
            rows.length ? rows.map(cardHtml).join('')
              : `<div class="ia-sc-empty">${all.length
                  ? '조건에 맞는 스냅샷이 없습니다.'
                  : '아직 스냅샷이 없습니다. 히스토리 이미지를 우클릭해 [NAI] 스냅샷 저장을 누르면 지금 설정이 담깁니다.'}</div>`}</div>
        </div>
        <div class="ia-sc-col ia-sc-preview">${previewHtml()}</div>
      </div>
    </div>`;

    restoreInputs(el, keep);
    const content = el.querySelector('.ia-sc-content');
    if (content) content.scrollTop = gridScroll;
    // 같은 스냅샷을 다시 그린 것이면(상태 밀림) 읽던 자리를 지킨다. 다른 카드로 넘어갔으면 맨 위다.
    const body = el.querySelector('.ia-sc-pv-body');
    if (body && sameBody) body.scrollTop = bodyScroll;
  }

  /** 응답에 **한 번만** 실려 오는 값들. 다음 상태에는 없으므로 받은 자리에서 쓴다. */
  function consumeOneShots(state) {
    const prompt = state.overwrite_prompt;
    // 되묻기는 저장을 보낸 그 연결로만 온다. 보낸 요청을 모르면(그림 · 고른 항목이 없다) 다시 보낼 것이 없다.
    if (prompt && prompt.name && pendingSave) {
      // **그때의 요청 그대로**(그림 · 고른 항목 · 카테고리) 다시 보낸다.
      const retry = pendingSave;
      pendingSave = null;
      confirmBox(`"${String(prompt.name)}" 스냅샷을 덮어씁니다. 계속할까요?`,
                 {title: '덮어쓰기', okText: '덮어쓰기', cancelText: '취소'})
        .then(ok => { if (ok) sendSave(retry, true); });
    }
    const report = state.apply_report;
    const skipped = Array.isArray(report?.skipped) ? report.skipped : [];
    if (skipped.length) {
      const names = skipped.map(entry => SECTION_LABELS[entry?.section] || String(entry?.section || '')).filter(Boolean);
      showToast(`되돌리지 못한 항목 ${skipped.length}개 — ${[...new Set(names)].join(', ')}`, 'error');
    }
    // 방금 만든 카테고리로 옮겨 간다 - 만들고 나서 다시 찾아 누르게 하지 않는다.
    const made = state.created_folder;
    if (made && made.id) {
      if (made.parent) { curTop = String(made.parent); curSub = String(made.id); }
      else { curTop = String(made.id); curSub = ''; }
      curNone = false;
    }
    // 방금 담은 스냅샷이 목록에 나타났으면 그 카드를 편다.
    if (pendingSelect && (state.snapshots || []).some(item => String(item.name) === pendingSelect)) {
      previewName = pendingSelect;
      pendingSelect = '';
    }
  }

  /** 서버 상태가 왔다. 창이 닫혀 있어도 받아 둔다 - 다음에 열 때 곧바로 보인다. */
  function render(state) {
    if (state) {
      lastState = state;
      consumeOneShots(state);
    }
    if (popOpen) renderPop();
  }

  function open() {
    if (popOpen) return;
    popOpen = true;
    renderPop();
    document.addEventListener('keydown', onKey, true);
    // 열 때마다 목록을 다시 받는다 - 저장할 수 있는지(마지막 그림 · 모델)도 그때 갱신된다.
    setModuleParam('snapshot', 'refresh', {});
  }

  function close() {
    if (!popOpen) return;
    popOpen = false;
    closeMenu();
    dragName = '';
    stopEdge();
    document.removeEventListener('keydown', onKey, true);
    renderPop();
  }

  function onKey(event) {
    if (event.key !== 'Escape' || !popOpen) return;
    // 앱 대화상자(이름 묻기 · 확인)가 떠 있으면 그것이 Esc 를 가진다.
    if (document.querySelector('.app-confirm-overlay')) return;
    // 메뉴가 떠 있으면 **그것만** 닫는다 - 한 번에 둘이 닫히면 되돌릴 길이 없다.
    event.stopPropagation();
    if (menuEl && !menuEl.hidden) { closeMenu(); return; }
    close();
  }

  // ── 우클릭 메뉴 ─────────────────────────────────────────────────────────
  // 카드에서 단추를 걷어낸 대신 여기가 손잡이다. 카테고리는 여기 담지 않는다 - 분류는 끌기
  // 하나로 통일한다(Scene 창과 같은 결정: 카테고리가 스무 개면 메뉴가 스크롤 덩어리가 된다).
  function ensureMenu() {
    if (menuEl && document.body.contains(menuEl)) return menuEl;
    menuEl = document.createElement('div');
    menuEl.className = 'ia-sc-menu snap-menu';
    menuEl.hidden = true;
    document.body.appendChild(menuEl);
    menuEl.addEventListener('click', event => {
      const hit = event.target?.closest?.('[data-snap-act]');
      closeMenu();                 // 무엇을 눌렀든 메뉴는 닫는다
      if (hit) onClick(event, hit);
    });
    menuEl.addEventListener('contextmenu', event => event.preventDefault());
    return menuEl;
  }

  function openMenu(name, px, py) {
    const item = findSnapshot(name);
    if (!item) return;
    const el = ensureMenu();
    const sid = esc(name);
    const mi = (act, label, cls, hint) =>
      `<button type="button" class="ia-sc-mi${cls || ''}" data-snap-act="${act}" data-snap-name="${sid}">${esc(label)}${
        hint ? `<span class="ia-sc-mhint">${esc(hint)}</span>` : ''}</button>`;
    el.innerHTML = `<div class="ia-sc-mname">${sid}</div>
      ${mi('preview-open', '불러올 항목 고르기', ' is-main')}
      <div class="ia-sc-msep"></div>
      ${mi('rename', '이름 바꾸기…')}
      ${folderOf(item) ? mi('unfile', '분류 풀기', '', '분류 없음으로') : ''}
      ${mi('delete', '삭제', ' is-danger', '되돌릴 수 없습니다')}`;
    el.hidden = false;
    // 그린 뒤에야 크기를 알 수 있다 - 화면 밖으로 나가면 안쪽으로 당긴다.
    const rect = el.getBoundingClientRect();
    el.style.left = `${Math.max(6, Math.min(px, window.innerWidth - rect.width - 6))}px`;
    el.style.top = `${Math.max(6, Math.min(py, window.innerHeight - rect.height - 6))}px`;
    document.addEventListener('pointerdown', onDocDown, true);
    window.addEventListener('resize', closeMenu);
    window.addEventListener('scroll', closeMenu, true);
  }

  function closeMenu() {
    if (!menuEl || menuEl.hidden) return;
    menuEl.hidden = true;
    menuEl.innerHTML = '';
    document.removeEventListener('pointerdown', onDocDown, true);
    window.removeEventListener('resize', closeMenu);
    window.removeEventListener('scroll', closeMenu, true);
  }

  function onDocDown(event) {
    if (menuEl && menuEl.contains(event.target)) return;
    closeMenu();
  }

  function onContextMenu(event) {
    const card = event.target?.closest?.('.snap-card');
    if (!card || !card.dataset.snapName) return;
    event.preventDefault();
    event.stopPropagation();
    openMenu(card.dataset.snapName, event.clientX, event.clientY);
  }

  // ── 끌어 옮기기 ─────────────────────────────────────────────────────────
  // 카드를 카테고리 칸에 떨어뜨리면 그 카테고리로 옮긴다. 창을 통째로 다시 그리므로 위임으로 건다.
  function onDragStart(event) {
    const card = event.target?.closest?.('.snap-card');
    if (!card || !card.dataset.snapName) return;
    dragName = card.dataset.snapName;
    closeMenu();
    markZones(true);
    try {
      event.dataTransfer.setData(DND_MIME, dragName);
      // 일부 브라우저는 표준 자료형이 하나도 없으면 끌기를 취소한다.
      event.dataTransfer.setData('text/plain', dragName);
      event.dataTransfer.effectAllowed = 'move';
    } catch (_) { /* dragName 으로도 동작한다 */ }
    card.classList.add('is-dragging');
  }

  function markZones(on) {
    popEl?.querySelectorAll('.ia-sc-col1, .ia-sc-col2').forEach(col => col.classList.toggle('is-dropzone', !!on));
  }

  function onDragEnd() {
    dragName = '';
    stopEdge();
    markZones(false);
    popEl?.querySelectorAll('.is-dragging').forEach(node => node.classList.remove('is-dragging'));
    popEl?.querySelectorAll('.is-drop').forEach(node => node.classList.remove('is-drop'));
  }

  function dropTarget(event) {
    const zone = event.target?.closest?.('[data-snap-drop]');
    if (!zone) return null;
    // ⚠️ 판별은 **자료형만으로** 한다. `dragName` 을 통행증으로 쓰면, 끌기 도중 목록이 다시
    //    그려져 `dragend` 가 안 왔을 때 값이 남고, 그 뒤 남의 파일이 이 검사를 통과해 이전에
    //    끌던 것이 옮겨진다(Scene 창에서 실측된 결함).
    const types = event.dataTransfer?.types || [];
    const mine = types.includes ? types.includes(DND_MIME) : Array.prototype.indexOf.call(types, DND_MIME) >= 0;
    return mine ? zone : null;
  }

  function stopEdge() {
    if (edgeTimer) { clearInterval(edgeTimer); edgeTimer = 0; }
  }

  /** 가장자리 자동 스크롤. `dragover` 는 간격이 들쭉날쭉해 타이머로 일정하게 굴린다. */
  function edgeScroll(event) {
    const col = event.target?.closest?.('.ia-sc-col1, .ia-sc-col2');
    stopEdge();
    if (!col || col.scrollHeight <= col.clientHeight) return;
    const rect = col.getBoundingClientRect();
    const dir = event.clientY < rect.top + 34 ? -1 : (event.clientY > rect.bottom - 34 ? 1 : 0);
    if (!dir) return;
    edgeTimer = setInterval(() => { col.scrollTop += dir * 12; }, 30);
  }

  function onDragOver(event) {
    const zone = dropTarget(event);
    if (zone || dragName) edgeScroll(event);
    if (!zone) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
    zone.classList.add('is-drop');
  }

  function onDragLeave(event) {
    event.target?.closest?.('[data-snap-drop]')?.classList.remove('is-drop');
    if (event.target?.closest?.('.ia-sc-col1, .ia-sc-col2')) stopEdge();
  }

  function onDrop(event) {
    const zone = dropTarget(event);
    if (!zone) return;
    event.preventDefault();
    stopEdge();
    markZones(false);
    zone.classList.remove('is-drop');
    let name = dragName;
    try { name = event.dataTransfer.getData(DND_MIME) || name; } catch (_) { /* dragName 으로 */ }
    dragName = '';
    const target = zone.dataset.snapDrop === 'none' ? '' : String(zone.dataset.snapDrop || '');
    moveSnapshot(name, target);
  }

  // ── 조작 ─────────────────────────────────────────────────────────────────
  function moveSnapshot(name, folder) {
    const item = findSnapshot(name);
    if (!item) return;
    if (folderOf(item) === folder) return;        // 제자리면 아무것도 안 한다
    setModuleParam('snapshot', 'move', {name: String(item.name), folder});
    showToast(folder ? `${folderLabel(folder)} (으)로 옮겼습니다.` : '분류를 풀었습니다.', 'info');
  }

  /** 저장을 보낸다. `request` = {name, include_search, folder, image?, sections?, relocate?}.
   *
   *  `image` · `sections` · `relocate` 는 저장 창(우클릭 > [NAI] 스냅샷 저장)이 싣는다: 우클릭한 그 그림,
   *  고른 항목만, 덮어쓸 때도 고른 카테고리로. 저장을 보내는 곳은 이제 그 창뿐이다.
   */
  function sendSave(request, overwrite) {
    const name = String(request.name || '');
    const picked = Array.isArray(request.sections) ? request.sections.map(String) : null;
    const withSearch = picked ? picked.includes('search') : !!request.include_search;
    const folder = String(request.folder || '');
    pendingSave = {...request, name, folder};
    pendingSelect = name;
    flush();
    // 데이터셋 사본은 풀 크기만큼 걸린다(수백 MB 면 수 초 이상). 답이 올 때까지 아무 표시가 없으면
    // 안 눌린 줄 알고 다시 누른다 - 누른 순간 알린다. 끝나면 서버의 저장 토스트가 온다.
    if (withSearch) showToast('데이터셋 사본을 담는 중입니다 — 크기에 따라 시간이 걸립니다', 'info');
    setModuleParam('snapshot', 'save', {
      name, include_search: withSearch, overwrite: !!overwrite,
      ...(request.image ? {image: String(request.image)} : {}),
      ...(picked ? {sections: picked} : {}),
      // 지금 보고 있는 카테고리에 담는다. 덮어쓸 때는 보내지 않는다 - 원래 자리를 지킨다.
      // 저장 창은 카테고리를 **직접 골랐으므로** 덮어쓸 때도 그 자리로 옮긴다(relocate).
      ...((!overwrite || request.relocate) ? {folder} : {}),
      ...((overwrite && request.relocate) ? {relocate: true} : {}),
    });
  }

  /** 저장 창이 빌려 쓰는 입구. 덮어쓰기 확인은 부른 쪽이 이미 했다. */
  function saveFromOutside(request, {overwrite = false} = {}) {
    // 같은 이름으로 다시 담으면 내용이 다른 스냅샷이다 - 옛 체크를 잊는다.
    forgetPicks(String(request?.name || ''));
    sendSave(request || {}, overwrite);
  }

  function applySnapshot(name) {
    const item = findSnapshot(name);
    if (!item) return;
    const sections = pickedKeys(item);
    if (!sections.length) { showToast('불러올 항목을 하나 이상 체크하세요', 'error'); return; }
    // 떠나는 프리셋은 서버가 저장한 뒤 넘기므로 잃는 것이 없다 - 그 저장에 마지막 편집까지
    // 실리도록 먼저 밀어 보낸다.
    flush();
    if (sections.includes('search')) showToast('데이터셋을 불러오는 중입니다 — 크기에 따라 시간이 걸립니다', 'info');
    setModuleParam('snapshot', 'apply', {name: String(item.name), sections});
    // 불러왔으면 창을 걷는다 - 바뀐 프롬프트 · 설정이 이 창 뒤에 있다.
    close();
  }

  async function renameSnapshot(name) {
    const item = findSnapshot(name);
    if (!item) return;
    const got = await askText('스냅샷 이름', item.name);
    if (got === null) return;
    const next = sanitizeName(got);
    if (!next || next === String(item.name)) return;
    if (next.startsWith('_')) { showToast('이름은 _ 로 시작할 수 없습니다', 'error'); return; }
    if (snapshots().some(other => String(other.name).toLowerCase() === next.toLowerCase())) {
      showToast(`이미 있는 이름입니다: ${next}`, 'error');
      return;
    }
    movePicks(String(item.name), next);
    if (previewName === String(item.name)) previewName = next;
    setModuleParam('snapshot', 'rename', {old: String(item.name), new: next});
  }

  async function deleteSnapshot(name) {
    if (!name) return;
    const ok = await confirmBox(`"${name}" 스냅샷을 폴더째 지웁니다. 되돌릴 수 없습니다.`,
                                {title: '스냅샷 삭제', okText: '지우기', cancelText: '취소'});
    if (!ok) return;
    if (previewName === name) previewName = '';
    forgetPicks(name);
    setModuleParam('snapshot', 'delete', {name});
  }

  async function newFolder(parent) {
    const name = await askText(parent ? '하위 카테고리 이름' : '카테고리 이름', '');
    if (!name) return;
    setModuleParam('snapshot', 'folder_create', {name, parent: parent || ''});
  }

  async function renameFolder() {
    const target = curSub || curTop;
    const folder = findFolder(target);
    if (!folder) return;
    const name = await askText('카테고리 이름', folder.name);
    if (!name || name === String(folder.name)) return;
    setModuleParam('snapshot', 'folder_rename', {id: target, name});
  }

  async function deleteFolder() {
    const target = curSub || curTop;
    if (!findFolder(target)) return;
    // 카테고리만 지운다 - 안의 스냅샷은 남는다. 상위면 하위도 함께 사라지므로 그 사실까지 적는다.
    const deep = !curSub && folders().some(folder => String(folder.parent || '') === curTop);
    const ok = await confirmBox(
      (deep ? '하위 카테고리도 함께 사라집니다. ' : '')
        + '카테고리만 지웁니다 — 안에 든 스냅샷은 사라지지 않고 분류 없음으로 옮겨집니다.',
      {title: '카테고리를 지울까요?', okText: '지우기', cancelText: '취소'});
    if (!ok) return;
    if (curSub) curSub = ''; else { curTop = ''; curSub = ''; }
    setModuleParam('snapshot', 'folder_delete', {id: target});
  }

  function onClick(event, forced) {
    const hit = forced || event.target?.closest?.('[data-snap-act]');
    if (!hit) return;
    // 카드 안의 체크 상자 · 입력은 건드리지 않는다(여기까지 오지 않지만 방어).
    if (event.target?.closest?.('input, label')) return;
    const act = hit.dataset.snapAct;
    const name = hit.dataset.snapName || '';
    if (hit.disabled) return;
    if (act === 'close') close();
    else if (act === 'open-folder') setModuleParam('snapshot', 'open_folder', {});
    else if (act === 'preview') {
      // 같은 카드를 다시 누르면 접는다.
      previewName = (previewName === name) ? '' : name;
      renderPop();
    } else if (act === 'preview-open') {
      previewName = name;
      renderPop();
    } else if (act === 'apply') applySnapshot(name);
    else if (act === 'rename') renameSnapshot(name);
    else if (act === 'delete') deleteSnapshot(name);
    else if (act === 'unfile') moveSnapshot(name, '');
    else if (act === 'top') {
      const fid = hit.dataset.fid || '';
      curNone = fid === 'none';
      curTop = curNone ? '' : fid;
      curSub = '';                 // 카테고리를 바꾸면 하위 선택은 버린다
      renderPop();
    } else if (act === 'sub') {
      curSub = hit.dataset.fid || '';
      renderPop();
    } else if (act === 'folder-new') newFolder(hit.dataset.fid || '');
    else if (act === 'folder-rename') renameFolder();
    else if (act === 'folder-del') deleteFolder();
  }

  function onInput(event) {
    if (event.target?.id !== 'snapSearch') return;
    query = String(event.target.value || '');
    // 걸러 내는 것은 화면 안의 일이다(목록이 통째로 와 있다) - 서버를 부르지 않는다.
    // ⚠️ **카드 칸만** 다시 그린다. 창을 통째로 갈면 검색칸이 새 노드가 되어 한글 조합이
    //    글자마다 끊긴다(조합 중인 입력칸을 갈아 끼우면 IME 가 그 글자를 확정해 버린다).
    renderGrid();
  }

  function renderGrid() {
    const grid = popEl?.querySelector('.ia-sc-grid');
    if (!grid) return;
    const rows = visibleSnapshots();
    grid.innerHTML = rows.length ? rows.map(cardHtml).join('')
      : `<div class="ia-sc-empty">${snapshots().length
          ? '조건에 맞는 스냅샷이 없습니다.'
          : '아직 스냅샷이 없습니다. 히스토리 이미지를 우클릭해 [NAI] 스냅샷 저장을 누르면 지금 설정이 담깁니다.'}</div>`;
  }

  function onChange(event) {
    const pick = event.target?.closest?.('[data-snap-pick]');
    if (!pick) return;
    const box = pick.closest('[data-snap-picks]');
    const name = box?.dataset.snapPicks || '';
    if (!name) return;
    rememberPick(name, pick.dataset.snapPick || '', pick.checked);
    // ⚠️ 통째로 다시 그리지 않는다 - 체크 상자의 초점이 날아가 키보드로 이어서 고를 수 없다.
    //    불러오기 단추의 잠금만 맞춘다.
    const item = findSnapshot(name);
    const button = popEl?.querySelector('[data-snap-act="apply"]');
    const wrongMode = !!(item?.mode && item.mode !== lastState?.current_mode);
    if (button) button.disabled = wrongMode || !box.querySelector('[data-snap-pick]:checked');
  }

  return {open, close, render, isOpen: () => popOpen, save: saveFromOutside};
}
