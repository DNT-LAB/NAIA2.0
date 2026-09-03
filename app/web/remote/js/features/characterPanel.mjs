/**
 * 캐릭터 워크스페이스 — [ 캐릭터 슬롯 | 작업 영역(탭) ]
 *
 * 사용자 지정 2026-09-01:
 *   "1. 기본 디자인 기조 : 메모와 유사합니다.
 *    2. 슬롯 디자인 기조 : 캐릭터 퀵 프롬프트 슬롯과 동일합니다.
 *    3. 구조는 [ 캐릭터 슬롯 | 작업 영역 (탭) ] 입니다."
 *   "캐릭터 프롬프트 모듈에서는 슬롯을 전부 펼칩니다."
 *   "[a] 왼쪽은 활성만 · Add Character 는 목록 바로 밑"
 *
 * ## 무엇이 문제였나 (실측 2026-09-01, 슬롯 8개)
 *
 *     창          420 x 696  = 뷰포트 720 의 **97%**
 *     슬롯 하나   163px      (Quick 은 같은 내용을 22~99px 로 그린다)
 *     한 화면에   **4개**
 *     스크롤      **1,086px** - 그리고 슬롯을 만들수록 끝없이 길어졌다
 *
 * 스크롤 길이가 "여태 만든 슬롯 전부" 에 비례했다. 이제 왼쪽에는 **활성만** 두므로
 * 지금 생성에 나가는 것에만 비례한다. 나머지는 **히스토리** 탭이 유일한 보관처다 - 썼던 슬롯을 최대 500개 누적한다
 * (사용자 지정 2026-09-01: 기존 비활성의 역할을 대신한다).
 *
 * ⚠️ Cold 는 **동작이 없는 세 번째 상태**였다(`is_enabled` 는 `active and not muted`
 *    뿐이라 inactive 와 하는 일이 같았다). 서랍을 파서 줄을 숨겼을 뿐이라 진짜 문제인
 *    줄 높이는 그대로였다. 이제 **그룹**으로 접는다 - 옛 `cold` 슬롯은 그룹 "Cold Storage" 로
 *    읽힌다(저장은 안 바꾼다).
 */
export function createCharacterPanel({
  document,
  escHtml,
  bindTagAssist,
  flushCharacterEdits,
  setModuleParam,
  showPromptDialog = null,
}) {
  const moduleBody = document.getElementById('modulePopupBody');

  // ⚠️ 즐겨찾기는 **그룹이 아니라 플래그**다. 그룹 탭에 한 줄로 섞어 뒀더니 사용자가
  //    그룹으로 오해했다(제보 2026-09-02: 거기서 빼면 그룹에서 빠지는 줄 알았다).
  //    히스토리 옆 **자기 탭**으로 뗀다 - 같은 목록의 다른 보기라는 뜻이 또렷해진다.
  const TABS = [
    {key: 'history', label: '히스토리'},
    {key: 'favourites', label: '즐겨찾기'},
    {key: 'assets', label: '에셋'},
    {key: 'search', label: '검색'},
    {key: 'groups', label: '그룹'},
    {key: 'tools', label: '도구'},
  ];

  let lastState = null;
  let lastRenderedStructureSignature = '';
  // 작업 영역(오른쪽 탭)의 서명. 이것이 그대로면 왼쪽만 다시 그린다.
  let lastRenderedWorkSignature = '';
  let deferredFocusedRenderState = null;
  let deferredFocusTarget = null;
  let tab = 'history';
  let query = '';
  // ⚠️ **uuid 로 잡는다.** index 는 슬롯이 무리를 옮길 때마다 밀려서, 펼쳐 둔
  //    항목이 조용히 다른 캐릭터로 바뀐다.
  const openHistory = new Set();

  /**
   * 펼친 항목을 **하나로** 유지한다 (사용자 지정 2026-09-02: "여러개의 아이템을
   * 동시에 펼칠 수 있는 문제를 수정합니다").
   *
   * ⚠️ 펼친 항목은 세 줄(프롬프트·UC·조작)을 더 차지한다. 여럿이 열리면 목록이
   *    통째로 밀려 방금 찾은 것이 화면 밖으로 나간다. 자료형은 Set 그대로 둔다 -
   *    렌더·서명이 이미 그것을 읽는다.
   */
  function openOnly(uuid) {
    openHistory.clear();
    if (uuid) openHistory.add(uuid);
  }

  // '그룹에 전달' 을 누른 히스토리 항목(uuid). 그 항목 아래에 그룹 고르기 줄이 열린다.
  let groupPickerUuid = '';
  // 그룹 탭의 검색어. **그룹 안의 항목**을 찾는다(사용자 지정 2026-09-02) - 그룹
  // 이름을 찾는 것이 아니다. 이름은 눈에 다 보이지만 안에 무엇이 들었는지는 안 보인다.
  let groupQuery = '';
  // ── 에셋 탭 ────────────────────────────────────────────────────────────
  //
  // ⚠️ 목록 라우트는 **페이지가 없다**(전체를 한 번에 준다). 그래서 한 번 받아
  //    세션에 들고, `↻` 나 담기 성공에만 다시 받는다.
  let assetRows = null;          // null = 아직 안 받음
  let assetLoading = false;
  let assetQuery = '';
  let assetPicked = '';          // 고른 캐릭터 id
  let assetVariation = '';       // 고른 변형 hash ('' = 대표)
  let assetDetail = null;        // /detail 응답
  let assetSeq = 0;              // 낡은 응답을 버리는 표
  let assetError = '';

  // ── 검색 탭 (Danbooru 도감) ────────────────────────────────────────────
  //
  // ⚠️ 도감은 **13,497명**이다(2026-09-02 실측 · 코드 주석의 9,738 은 낡았다).
  //    전부 받을 수 없으므로 40건씩 페이지로 받는다.
  let dexRows = [];
  let dexPage = 0;
  let dexPages = 1;
  let dexTotal = 0;
  let dexQuery = '';
  let dexGroup = '';            // 작품으로 좁히기('' = 전체)
  let dexGroups = [];           // 지금 걸린 것들의 작품 칩 [{key, count}]
  // [최신] - 요즘 단부루에 나타나기 시작한 캐릭터만 남긴다. 하한은 백엔드가
  // 산출물에서 읽어 함께 보낸다(지금은 2025-01 · 도감 13,497 중 833명).
  let dexRecent = false;
  let dexRecentSince = '';
  // [즐겨찾기] - 별을 켜 둔 캐릭터만 남긴다(사용자 요청 2026-09-03).
  // ⚠️ 저장소는 **백엔드 한 곳**이다(`character_viewer_favorites.json`). 캐릭터 탭과
  //    이 검색 탭이 같은 목록을 보므로, 여기서 켠 별이 저쪽에서도 보여야 한다.
  let dexFav = false;
  let dexFavCount = 0;
  let dexLoading = false;
  // 도는 중에 조건이 바뀌었는가. 끝나면 한 번 더 돈다(아래 `loadDex`).
  let dexPending = false;
  // ⚠️ 목록과 상세는 **표를 따로** 쓴다(Codex CONCERN 4). 하나를 나눠 쓰면, 더 보기가
  //    도는 중에 행을 누르는 순간 목록 응답이 낡은 것이 되어 `dexLoading` 이 참으로
  //    남고, 그 뒤 검색과 더 보기가 **영영 안 먹는다.**
  let dexSeq = 0;          // 목록
  let dexDetailSeq = 0;    // 상세
  let dexPicked = null;         // {group, character}
  let dexDetail = null;
  let dexVariant = '';
  let dexError = '';
  // ⚠️ 상세의 오류는 **따로** 담는다. 목록 오류와 한 통에 담으면 서로를 덮어,
  //    아래 칸이 이유도 없이 '불러오는 중…' 에 멈춘 것처럼 보인다.
  let dexDetailError = '';
  let dexTimer = 0;

  // 그룹 탭에서 펼쳐 둔 그룹. 키는 `g:이름` · 즐겨찾기 `fav` · 그룹 없음 `none`.
  const openGroups = new Set();
  // ⚠️ 그룹 행의 키를 **그룹 이름 그대로 쓰면 안 된다.** 사용자가 `★` 이라는 그룹을
  //    만들 수 있고(백엔드가 막지 않는다), 그러면 즐겨찾기 행과 키가 겹쳐 그 그룹의
  //    멤버가 영영 안 보이고 드롭도 즐겨찾기로 샌다(실측 재현).
  //    이름은 `g:` 뒤에만 둔다 - 그러면 어떤 이름도 `fav`/`none` 과 겹치지 않는다.
  const GRP_FAV = 'fav';
  const GRP_NONE = 'none';
  // 슬롯 칸에 놓으면 **활성으로 복원**한다. 그룹 이름이 될 수 없는 토큰이라 안전하다.
  const GRP_SLOT = 'slot';
  // 히스토리 목록 자체가 드롭 대상이다 - 슬롯을 끌어다 놓으면 ✕ 와 같은 일이 난다.
  const GRP_HIST = 'hist';
  const grpKey = name => 'g:' + name;
  const grpName = key => (String(key || '').slice(0, 2) === 'g:' ? String(key).slice(2) : '');
  // 드래그 규약은 interactiveScenePanel 과 같다: 우리 자료형 하나로 **우리 것만** 받고,
  // 끌기 도중 다시 그려져 원본이 사라지면 `dragend` 가 오지 않으므로 표를 직접 버린다.
  const DND_MIME = 'application/x-naia-charslot';
  // 워크스페이스 **밖에서** 오는 것(에셋·도감). 슬롯이 아니라 **내용**을 싣는다 -
  // 이것들은 `lastState.characters` 에 없으므로 uuid 로는 찾을 수가 없다.
  const DND_MIME_SRC = 'application/x-naia-charsource';
  let dragUuid = '';

  /** 그룹 목록은 **서버가 SSOT** 다(빈 그룹도 있어야 하므로 프레임에서 뽑지 않는다). */
  function groupsOf(state) {
    const list = Array.isArray(state?.groups) ? state.groups.map(g => String(g || '').trim()).filter(Boolean) : [];
    return [...new Set(list)];
  }


  /**
   * 커서에 붙일 **작은 칩**. 기본 고스트는 행 전체(340px)를 찍어 잘린 글자·버튼·
   * 배경이 통째로 딸려 오고, 잡은 지점에 따라 화면 밖으로 뻗는다.
   *
   * ⚠️ 화면 **밖 좌표**로 숨긴다. `display:none`·`visibility:hidden`·`opacity:0` 은
   *    빈 그림이 된다(기본 고스트로 돌아가지 않는다).
   * ⚠️ `document.body` 에 붙인다. 팝업 안에 두면 팝업의 `transform` 이 `fixed` 의
   *    기준을 바꾸고 `overflow: hidden` 이 잘라 낸다.
   * ⚠️ 한 번 만들고 **안 지운다**. dragstart 안에서 지우면 브라우저가 스냅샷을
   *    찍기 전에 사라진다(스냅샷은 핸들러가 끝난 뒤에 찍힌다).
   */
  let dragChipNode = null;
  function dragChip(text) {
    if (!dragChipNode) {
      dragChipNode = document.createElement('div');
      dragChipNode.className = 'cw-drag-chip';
      document.body.appendChild(dragChipNode);
    }
    dragChipNode.textContent = text;   // setDragImage 보다 **먼저**
    return dragChipNode;
  }

  /** 우리 자료형을 든 끌기가 그룹 행 위에 있을 때만 그 행. 파일·남의 글은 무시한다. */
  function dropTarget(event) {
    const el = event.target && event.target.closest ? event.target.closest('[data-cw-drop]') : null;
    if (!el) return null;
    const types = (event.dataTransfer && event.dataTransfer.types) || [];
    const has = name => (types.includes
      ? types.includes(name)
      : Array.prototype.indexOf.call(types, name) >= 0);
    // ⚠️ **타입으로만** 가른다(끌기 도중에는 값을 못 읽는 브라우저가 있다).
    //    바깥에서 온 것은 슬롯 칸에만 놓는다 - 그룹 행은 히스토리의 것을 옮기는 자리다.
    if (has(DND_MIME)) return el;
    if (has(DND_MIME_SRC)) return el.dataset.cwDrop === GRP_SLOT ? el : null;
    return null;
  }
  /**
   * 각 틈에 "여기 놓으면 C몇 이 된다" 를 적는다.
   *
   * ⚠️ 이미 활성인 슬롯을 **자기보다 아래로** 끌면, 자기가 빠지면서 뒤가 한 칸
   *    당겨진다(백엔드 `char_reorder_` 도 같은 보정을 한다). 그 보정을 여기서도
   *    하지 않으면 이름이 한 칸씩 거짓말을 한다.
   */
  function labelGaps() {
    const actives = (lastState?.characters || []).filter(c => slotState(c) === 'active');
    // ⚠️ 바깥에서 온 것은 목록에 **없다** - 빠지며 당겨질 자기 자리가 없으므로
    //    보정하면 안 된다(`from = -1` 이 그 뜻이다).
    const from = dragUuid
      ? actives.findIndex(c => String(c.slot_uuid || '') === dragUuid)
      : -1;
    moduleBody.querySelectorAll('.cw-slot-gap').forEach(el => {
      const ordinal = Number(el.dataset.cwGap || 0);
      const seat = from >= 0 && from < ordinal ? ordinal - 1 : ordinal;
      el.dataset.cwLabel = `C${seat + 1}`;
      // 든 것의 **바로 위·아래** 틈은 놓아도 제자리다 - 자라지도, 번호를 띄우지도
      // 않는다. 겨눌 것이 둘 줄고 거짓 목표가 사라진다.
      el.classList.toggle('is-self', from >= 0 && (ordinal === from || ordinal === from + 1));
    });
  }

  /**
   * 슬롯 칸 안에서 커서가 가리키는 **틈**. 카드 위에 있어도 가까운 쪽을 고른다.
   *
   * ⚠️ 이것이 "드래그가 둔감하다"(사용자 제보 2026-09-02)의 본체였다. 틈은 26px
   *    띠인데 카드는 100px 이 넘는다 - 나머지 위에서는 아무것도 안 잡혀 목록 위에
   *    있는데도 반응이 없었다. 이제 **카드 어디에 있어도** 위/아래 절반으로 갈라
   *    가까운 틈이 켜진다.
   * ⚠️ `getBoundingClientRect` 는 카드 **하나만** 잰다. 스물다섯 개를 재면 이벤트
   *    마다 레이아웃을 강제한다.
   */
  function slotGapAt(event) {
    const gaps = [...moduleBody.querySelectorAll('.cw-slot-gap')];
    if (!gaps.length) return null;
    const at = ordinal => gaps.find(g => Number(g.dataset.cwGap) === ordinal)
      || gaps[gaps.length - 1];
    const node = event.target && event.target.closest ? event.target : null;
    const card = node ? node.closest('.cw-slot') : null;
    if (card) {
      const box = card.getBoundingClientRect();
      const seat = [...moduleBody.querySelectorAll('.cw-slot')].indexOf(card);
      return at(seat + (event.clientY > box.top + box.height / 2 ? 1 : 0));
    }
    const onGap = node ? node.closest('.cw-slot-gap') : null;
    if (onGap) return onGap;
    // 머리줄 위쪽이면 첫 자리, 그 밖(= `+ Add Character` 아래 빈 곳)이면 마지막.
    return event.clientY < gaps[0].getBoundingClientRect().top ? gaps[0] : gaps[gaps.length - 1];
  }

  // 테스트 생성이 도는 중인가. 버튼을 잠가 연타를 막는다(Codex BLOCK 2).
  let instantBusy = false;
  let instantRelease = 0;

  function setInstantBusy(busy) {
    instantBusy = !!busy;
    moduleBody.querySelectorAll('[data-cw-test], [data-cw-gen]')
      .forEach(el => { el.disabled = !!busy; });
    if (instantRelease) { clearTimeout(instantRelease); instantRelease = 0; }
    // ⚠️ 결과 알림이 유실되면 영영 잠긴다 - 안전 타이머로 반드시 되돌린다.
    if (busy) instantRelease = setTimeout(() => setInstantBusy(false), 180000);
  }

  // 지금 끌고 있는 바깥 항목의 내용. 놓을 때 쓴다.
  let dragSource = null;
  let dragSourceSeq = 0;

  /**
   * 에셋 타일·도감 행을 든다.
   *
   * ⚠️ 프롬프트는 **아직 없다** - 둘 다 상세를 따로 받아야 안다. 표식만 먼저 싣고
   *    내용은 뒤따라 채운다(놓기까지는 시간이 넉넉하다). 못 채운 채 놓으면 아무
   *    일도 안 난다 - 조용히 빈 슬롯을 만들지 않는다.
   */
  function startSourceDrag(event, node) {
    // ⚠️ **세대를 매긴다**(Codex CONCERN 6). 앞 끌기의 늦은 응답이 도착해 지금 끌고
    //    있는 것의 내용을 덮으면, 놓았을 때 **다른 캐릭터**가 들어간다.
    const gen = ++dragSourceSeq;
    dragSource = null;
    try {
      event.dataTransfer.setData(DND_MIME_SRC, '1');
      event.dataTransfer.setData('text/plain', node.textContent.trim().slice(0, 60));
      event.dataTransfer.effectAllowed = 'copy';
      const name = node.querySelector('.cw-tile-name, .cw-dex-name');
      event.dataTransfer.setDragImage(
        dragChip((name?.textContent || '캐릭터').trim().slice(0, 40)), 12, 11);
    } catch (_) { /* 무시 */ }
    node.classList.add('is-dragging');
    moduleBody.querySelectorAll('.cw-slots, .cw-slot-gap')
      .forEach(el => el.classList.add('is-dropzone'));
    labelGaps();
    if (node.dataset.cwSrc === 'asset') {
      const id = node.dataset.cwSrcId || '';
      void fetch(`/api/character-asset/detail?id=${encodeURIComponent(id)}`)
        .then(res => res.json())
        .then(data => {
          if (gen !== dragSourceSeq) return;
          dragSource = {
            prompt: String(data.character_prompt || ''),
            uc: String(data.character_uc || ''),
            custom_name: String(data.display_name || ''),
          };
        })
        .catch(() => { if (gen === dragSourceSeq) dragSource = null; });
      return;
    }
    const group = node.dataset.cwDexGroup || '';
    const character = node.dataset.cwDexChar || '';
    void fetch('/api/character-viewer/detail', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({group, character, variant: '',
                            options: {hide_charname: false, cosplay_enabled: false}}),
    })
      .then(res => res.json())
      .then(data => {
        if (gen !== dragSourceSeq) return;
        dragSource = {prompt: String(data.prompt?.character_prompt || ''),
                      uc: '', custom_name: character};
      })
      .catch(() => { if (gen === dragSourceSeq) dragSource = null; });
  }

  /** 바깥에서 온 것을 슬롯에 꽂는다. `at` 이 없으면 맨 아래. */
  function dropSourceIntoSlots(at, seed) {
    dragSource = null;
    if (!seed || !String(seed.prompt || '').trim()) {
      showToastSafe('프롬프트를 아직 못 읽었습니다. 다시 시도해 주세요.');
      return;
    }
    const max = Number(lastState?.max_slots) || 0;
    const used = (lastState?.characters || []).filter(c => slotState(c) === 'active').length;
    if (max && used >= max) { showToastSafe(`활성 캐릭터 슬롯은 최대 ${max}개입니다.`); return; }
    const payload = {prompt: seed.prompt, uc: seed.uc || '',
                     custom_name: seed.custom_name || ''};
    if (at !== undefined) payload.at = Number(at);
    setModuleParam('character', 'add_character', JSON.stringify(payload));
  }

  /** 실제로 겨눠진 것. 슬롯 칸이면 **틈까지** 좁혀 준다. */
  function aimed(event) {
    const target = dropTarget(event);
    if (!target || target.dataset.cwDrop !== GRP_SLOT) return target;
    return slotGapAt(event) || target;
  }


  function clearDrag() {
    dragUuid = '';
    dragSource = null;
    // 세대를 넘겨 **아직 오는 중인 응답**을 무효로 만든다.
    dragSourceSeq += 1;
    const kill = ['is-dragging', 'is-drop', 'is-dropzone', 'is-self'];
    moduleBody.querySelectorAll('.' + kill.join(', .'))
      .forEach(el => el.classList.remove(...kill));
  }

  /** 이 패널은 showToast 를 주입받지 않는다 - 전역이 있으면 쓴다. */
  function showToastSafe(message) {
    if (typeof window !== 'undefined' && typeof window.showToast === 'function') {
      window.showToast(message, 'info');
    }
  }

  function escAttr(value) {
    return escHtml(String(value ?? '')).replace(/"/g, '&quot;');
  }

  function slotState(character) {
    const raw = String(character?.slot_state || '').toLowerCase();
    if (raw === 'active' || raw === 'inactive' || raw === 'cold') return raw;
    return character?.active ? 'active' : 'inactive';
  }

  /**
   * 목록 한 줄에 보일 이름. 사용자가 지은 이름이 있으면 그것이 이긴다.
   *
   * ⚠️ 히스토리에서는 **프롬프트 전문**을 쓴다(넘치면 CSS 가 자른다). 첫 태그만
   *    잘라 쓰면 `1girl` 이 여럿이라 서로 구분이 안 된다(실측: 보관 4줄 중 3줄이
   *    `1girl`/`1boy` 였다). 슬롯 쪽은 아래에 프롬프트 칸이 붙어 있으니 짧아도 된다.
   */
  function slotLabel(character, {full = false} = {}) {
    const custom = String(character?.custom_name || '').trim();
    if (custom) return custom;
    const prompt = String(character?.prompt || '').trim();
    if (!prompt) return '(비어 있음)';
    return full ? prompt : prompt.split(',')[0].trim();
  }

  /** 그룹 배경 색조. 서버가 **만들 때 무작위로** 배정해 둔 값이다. */
  function hueOf(name) {
    const map = lastState?.group_colors;
    const raw = map && Object.prototype.hasOwnProperty.call(map, name) ? map[name] : null;
    return Number.isFinite(Number(raw)) ? Number(raw) : null;
  }

  /** 색을 인라인으로 문다 - 그룹 수가 정해져 있지 않아 CSS 클래스로는 못 쓴다. */
  function hueStyle(name) {
    const hue = name ? hueOf(name) : null;
    return hue === null ? '' : ` style="--cw-grp-hue:${hue}"`;
  }

  /**
   * 사용자가 **아무것도 넣지 않은** 슬롯인가.
   *
   * ⚠️ 프롬프트만 보면 안 된다 - 이름만 붙였거나 좌표만 잡아 둔 자리표시자는
   *    사용자가 만든 것이다. 잣대는 백엔드(`_slot_is_untouched`)와 같아야 한다.
   */
  function isEmptySlot(character) {
    if (!character) return false;
    const filled = ['prompt', 'uc', 'custom_name']
      .some(key => String(character[key] || '').trim());
    return !filled && !(character.position && typeof character.position === 'object');
  }

  function groupOf(character) {
    return String(character?.group || '').trim();
  }

  // ── 편집 중 재렌더 방지 ────────────────────────────────────────────────
  //
  // ⚠️ 서버 에코가 **포커스된 textarea 를 갈아치우면** 태그 자동완성이 고르기 전에
  //    닫힌다. 구조가 그대로면 다시 그리지 않고 미뤄 둔다.

  /** 슬롯 칸이 바뀌었는가. 여기가 그대로면 왼쪽은 안 건드린다. */
  function slotsSignature(state) {
    const chars = state?.characters || [];
    return [
      state?.activated ? 1 : 0,
      Number(state?.max_slots) || 0,
      chars.length,
      chars.map(item => [
        item.slot_uuid, slotState(item), item.muted ? 1 : 0,
        item.favorite ? 1 : 0, item.custom_name || '',
      ].join(':')).join('|'),
    ].join('#');
  }

  /** 작업 영역(탭)이 바뀌었는가. */
  function workSignature(state) {
    const chars = state?.characters || [];
    return [
      tab, query, groupQuery,
      // 에셋 탭의 고른 것·검색어·불러온 수도 작업 영역의 일부다.
      assetQuery, assetPicked, assetVariation, assetLoading ? 1 : 0,
      (assetRows || []).length, assetDetail ? assetDetail.variation : '~',
      dexQuery, dexGroup, dexRows.length, dexLoading ? 1 : 0, dexVariant,
      dexRecent ? 1 : 0,
      // ⚠️ 별 상태를 **세어서** 싣는다. 켜고 끄면 목록 길이도 필터도 안 바뀌므로,
      //    이것이 없으면 서명이 안 움직여 별이 화면에서 안 갈린다
      //    ([[feedback_measure_the_response_not_the_state]] 와 같은 함정).
      dexFav ? 1 : 0, dexFavCount,
      dexRows.reduce((n, r) => n + (r.favorite ? 1 : 0), 0),
      dexPicked ? `${dexPicked.group}/${dexPicked.character}` : '',
      // ⚠️ **있다/없다로 세면 안 된다.** 변형을 바꾸면 상세만 갈리는데 이 값이
      //    1 -> 1 이라 서명이 안 움직이고, 그 뒤 렌더가 '슬롯만 갈아 끼우는' 길로
      //    빠져 아래 칸이 옛 프롬프트에 멈춘다(실측 2026-09-03: 응답은 왔는데
      //    화면만 안 바뀌었다). 에셋 탭이 `assetDetail.variation` 을 싣는 것과
      //    같은 이유다 - **응답을 세라, 상태 말고.**
      dexDetail ? `d:${dexDetail.variant || ''}` : `e:${dexDetailError}`, dexGroups.length,
      JSON.stringify(state?.group_colors || {}),
      [...openHistory].sort().join(','),
      groupsOf(state).join(','), groupPickerUuid,
      [...openGroups].sort().join(','),
      chars.length,
      chars.map(item => [
        item.slot_uuid, slotState(item), item.favorite ? 1 : 0,
        groupOf(item), item.custom_name || '',
      ].join(':')).join('|'),
    ].join('#');
  }

  function characterStructureSignature(state) {
    return [
      state?.reroll_on_generate ? 1 : 0,
      slotsSignature(state), workSignature(state),
    ].join('#');
  }

  /**
   * 지금 사람이 치고 있는 칸. 다시 그리면 그 손을 끊는다.
   *
   * ⚠️ 슬롯의 textarea 뿐 아니라 **작업 영역의 입력칸**도 본다. 히스토리·그룹
   *    검색은 이미 부분 갱신으로 피했지만, 앞으로 들어올 에셋·검색 탭의 검색칸은
   *    에코 한 번에 캐럿을 잃는다(Fable 조사 2026-09-02 · 실제로 Assets 바가 같은
   *    이유로 스크롤을 손수 넘긴다).
   */
  function focusedCharacterTextarea() {
    const active = document.activeElement;
    if (!active) return null;
    if (active.tagName === 'TEXTAREA' && active.closest('.cw-slot')) return active;
    if (active.closest && active.closest('.cw-work')
        && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA')) return active;
    return null;
  }

  function clearDeferredFocusedRender() {
    if (deferredFocusTarget) {
      deferredFocusTarget.removeEventListener('blur', flushDeferredFocusedRender);
      deferredFocusTarget = null;
    }
    deferredFocusedRenderState = null;
  }

  function queueDeferredFocusedRender(textarea, state) {
    deferredFocusedRenderState = state;
    if (deferredFocusTarget === textarea) return;
    if (deferredFocusTarget) deferredFocusTarget.removeEventListener('blur', flushDeferredFocusedRender);
    deferredFocusTarget = textarea;
    textarea.addEventListener('blur', flushDeferredFocusedRender);
  }

  function flushDeferredFocusedRender() {
    const pending = deferredFocusedRenderState;
    clearDeferredFocusedRender();
    if (pending) render(pending);
  }

  /** Quick 과 같은 규약: 최소 줄수는 지키되 넘치면 한 줄씩 늘어난다. */
  function autoGrow(element) {
    const rows = element.dataset.cwMin === 'uc' ? 1 : 2;
    const line = 1.4 * 11;                       // .cw-input 의 line-height * font-size
    const min = Math.round(rows * line) + 12;    // + 세로 패딩
    element.style.height = 'auto';
    element.style.height = Math.max(min, element.scrollHeight) + 'px';
  }

  // ── 조작 ────────────────────────────────────────────────────────────────

  function addSlot() {
    if (flushCharacterEdits) flushCharacterEdits();
    setModuleParam('character', 'add_character', 'true');
  }

  function removeSlot(index) {
    setModuleParam('character', `remove_character_${index}`, 'true');
  }

  function refreshPreview() {
    if (flushCharacterEdits) flushCharacterEdits();
    setModuleParam('character', 'preview_refresh', 'true');
  }

  function setSlotState(index, state) {
    setModuleParam('character', `char_slot_state_${index}`, state);
  }

  /**
   * 슬롯 별칭. **화면에는 버튼이 없다**(사용자 지정 2026-09-02):
   *   "이름 바꾸기는 필요없는것이, 애초에 검색을 통해 내부 컨텐츠를 읽을 수
   *    있으면 문제없기 때문입니다."
   * 히스토리 검색이 프롬프트 전문을 훑으므로 별칭 없이도 찾을 수 있다.
   * ⚠️ 함수는 남긴다 - `app.js` 의 전역 `renameCharacterSlot` 이 이것을 부르고,
   *    이미 붙어 있는 별칭은 목록에서 계속 이름으로 쓰인다(`slotLabel`).
   */
  async function renameSlot(index) {
    const character = (lastState?.characters || [])[index];
    if (!character || !showPromptDialog) return;
    const next = await showPromptDialog('이 캐릭터를 목록에서 무엇으로 부를까요? (비우면 프롬프트 앞머리)', {
      title: '슬롯 이름', defaultValue: String(character.custom_name || ''),
    });
    if (next === null) return;
    setModuleParam('character', `char_slot_name_${index}`, String(next).trim());
  }

  /**
   * 즉시 생성 - 이 캐릭터 하나만 시험 삼아 뽑는다.
   *
   * 메인 프롬프트는 서버가 만든다(**1girl|1boy** 를 맨 앞에 두고 PE 선행·후행).
   * 파라미터는 사용자의 현재 값 그대로이고, 결과는 **Results 에 남으면서**
   * 프리뷰 창에도 뜬다(캐릭터 모듈이 Result 를 덮기 때문).
   *
   * ⚠️ **슬롯을 안 건드린다.** 예전에는 이 캐릭터를 슬롯으로 복원한 뒤 평소의
   *    Generate 를 눌렀다 - 메인 프롬프트가 화면의 것 그대로 나갔고, 시험 삼아
   *    눌렀을 뿐인데 캐릭터가 슬롯에 남았다.
   * ⚠️ **uuid 로 보낸다.** index 는 요청이 닿기까지 정렬이 한 번 지나가면 남의
   *    것이 된다.
   */
  async function instantGenerate(uuid) {
    if (!uuid) return;
    // ⚠️ **연타를 막는다**(Codex BLOCK 2). 유료 설정에서 두 번 누르면 요청 둘이
    //    큐에 들어가 Anlas 를 두 번 쓴다 - 큐는 중복을 안 본다.
    //    결과(또는 오류)가 화면에 닿을 때까지 잠근다. 알림이 유실되어 영영 잠기지
    //    않게 안전 타이머도 함께 건다(프리뷰 잠금이 같은 이유로 그렇게 한다).
    if (instantBusy) { showToastSafe('테스트 생성이 이미 돌고 있습니다.'); return; }
    setInstantBusy(true);
    try {
      const res = await fetch('/api/character/instant-generate', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({uuid, requestId: String(Date.now())}),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        // 시작조차 못 했다 - 기다릴 결과가 없으므로 그 자리에서 푼다.
        setInstantBusy(false);
        showToastSafe(data.error || data.message || '즉시 생성을 시작하지 못했습니다.');
        return;
      }
      // ⚠️ 메인 프롬프트 창은 **안 건드린다**(사용자 지정 2026-09-02: "사용자는
      //    본인의 메인 프롬프트가 덮이는걸 매우 싫어합니다"). 한 번 덮으면
      //    되돌릴 길이 없다 - 무엇이 나갔는지는 프리뷰 창의 머리글·메타와
      //    저장된 이미지의 메타데이터가 말해 준다.
      showToastSafe(data.subject
        ? `테스트 생성 중… (${data.subject})`
        : '테스트 생성 중… (girl/boy 가 없어 주어를 안 넣었습니다)');
    } catch (error) {
      setInstantBusy(false);
      showToastSafe('즉시 생성 요청 실패: ' + error.message);
    }
  }

  /** 새 그룹. **내장 팝업**이 이름을 받는다(사용자 지정 2026-09-02). */
  async function createGroup() {
    if (!showPromptDialog) return;
    // ⚠️ 시그니처는 `showPromptDialog(message, options)` 다 - 객체 하나로 부르면
    //    `escHtml(object)` 에서 터진다(실측: TypeError s.replace is not a function).
    const next = await showPromptDialog('만들 그룹의 이름을 적어 주세요.', {
      title: '새 그룹', okText: '만들기', defaultValue: '',
    });
    const name = String(next ?? '').trim();
    if (!name) return;
    setModuleParam('character', 'add_group', name);
  }

  async function editGroup(index) {
    const character = (lastState?.characters || [])[index];
    if (!character || !showPromptDialog) return;
    const next = await showPromptDialog('새 그룹 이름을 적으면 만들어서 넣습니다.', {
      title: '그룹', okText: '넣기', defaultValue: groupOf(character),
    });
    if (next === null) return;
    setModuleParam('character', `char_group_${index}`, String(next).trim());
  }

  // ── 에셋 ───────────────────────────────────────────────────────────────

  /**
   * 썸네일 주소.
   *
   * ⚠️ `size` 는 **반드시 `grid`** 다. 다른 값이면 서버가 **원본 PNG 전체**(수 MB)를
   *    준다(`character_asset_routes.character_asset_thumb_payload`). 오타 하나로
   *    격자 한 화면에 수십 MB 가 흐른다.
   * ⚠️ `v=` 는 revision(파일 mtime_ns) 이다. 안 붙이면 승격·편집 뒤에도 브라우저가
   *    옛 그림을 그대로 쓴다(썸네일 캐시가 폴백을 못 덮은 사고와 같은 계열).
   */
  function assetThumbUrl(id, variation, revision) {
    const parts = [`id=${encodeURIComponent(id)}`, 'size=grid'];
    if (variation) parts.push(`variation=${encodeURIComponent(variation)}`);
    if (revision) parts.push(`v=${encodeURIComponent(String(revision))}`);
    return `/api/character-asset/thumb?${parts.join('&')}`;
  }

  function assetLabel(row) {
    return String(row?.display_name || '').trim() || String(row?.id || '').slice(0, 8);
  }

  async function loadAssets({force = false} = {}) {
    if (assetLoading) return;
    if (assetRows && !force) return;
    assetLoading = true;
    assetError = '';
    scheduleRerender();
    try {
      const res = await fetch('/api/character-asset/list');
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || '에셋 목록을 불러오지 못했습니다.');
      assetRows = Array.isArray(data.characters) ? data.characters : [];
    } catch (error) {
      assetRows = [];
      assetError = error.message || String(error);
    } finally {
      assetLoading = false;
      // 목록만 바뀐다 - 검색칸의 캐럿을 지키려면 부분 갱신이어야 한다.
      scheduleRerender();
    }
  }

  /** 고른 캐릭터(또는 변형)의 프롬프트를 받아 온다. */
  async function loadAssetDetail(id, variation) {
    const seq = ++assetSeq;
    try {
      const parts = [`id=${encodeURIComponent(id)}`];
      if (variation) parts.push(`variation=${encodeURIComponent(variation)}`);
      const res = await fetch(`/api/character-asset/detail?${parts.join('&')}`);
      const data = await res.json().catch(() => ({}));
      // ⚠️ 낡은 응답을 버린다 - 타일을 빠르게 훑으면 먼저 보낸 것이 나중에 온다.
      if (seq !== assetSeq) return;
      if (!res.ok) { assetError = data.error || '상세를 불러오지 못했습니다.'; assetDetail = null; }
      else { assetDetail = data; assetError = ''; }
    } catch (error) {
      if (seq !== assetSeq) return;
      assetDetail = null;
      assetError = error.message || String(error);
    }
    rerender();
  }

  function pickAsset(id) {
    if (assetPicked === id) return;
    assetPicked = id;
    assetVariation = '';
    assetDetail = null;
    rerender();
    void loadAssetDetail(id, '');
  }

  /** 고른 것을 **새 활성 슬롯**으로 담는다 (맨 아래). */
  async function addAssetToSlot() {
    if (!assetPicked) return;
    // 상한은 백엔드의 `add_slot` 이 **안 본다** - 여기서 먼저 막는다.
    const max = Number(lastState?.max_slots) || 0;
    const used = (lastState?.characters || []).filter(c => slotState(c) === 'active').length;
    if (max && used >= max) { showToastSafe(`활성 캐릭터 슬롯은 최대 ${max}개입니다.`); return; }
    try {
      const res = await fetch('/api/character-asset/apply', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({id: assetPicked, variation: assetVariation, mode: 'add_slot'}),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { showToastSafe(data.error || '슬롯에 담지 못했습니다.'); return; }
      showToastSafe('슬롯 맨 아래에 담았습니다.');
    } catch (error) {
      showToastSafe('담기 실패: ' + error.message);
    }
  }

  function assetMatches(row) {
    const needle = assetQuery.trim().toLowerCase();
    if (!needle) return true;
    return `${row.display_name || ''} ${row.id || ''}`.toLowerCase().includes(needle);
  }

  /** 위 칸 - 캐릭터 타일 격자. */
  function renderAssetTiles() {
    if (assetLoading && !assetRows) return '<div class="cw-empty">불러오는 중…</div>';
    if (assetError && !assetRows?.length) return `<div class="cw-empty">${escHtml(assetError)}</div>`;
    const rows = (assetRows || []).filter(assetMatches);
    if (!rows.length) {
      return `<div class="cw-empty">${assetRows?.length
        ? '조건에 맞는 에셋이 없습니다.'
        : '저장된 캐릭터 에셋이 없습니다.'}</div>`;
    }
    return rows.map(row => `
      <button type="button" class="cw-tile${row.id === assetPicked ? ' is-on' : ''}"
        draggable="true" data-cw-src="asset" data-cw-src-id="${escAttr(row.id)}"
        data-cw-asset="${escAttr(row.id)}" title="${escAttr(assetLabel(row))}">
        <img class="cw-tile-img" loading="lazy" decoding="async" alt=""
          src="${escAttr(assetThumbUrl(row.id, '', row.revision))}">
        ${row.variation_count > 0
          ? `<span class="cw-tile-badge">+${row.variation_count}</span>` : ''}
        <span class="cw-tile-name">${escHtml(assetLabel(row))}</span>
      </button>`).join('');
  }

  /** 아래 칸 - 고른 것의 그림·프롬프트·변형. */
  function renderAssetDetail() {
    if (!assetPicked) {
      return '<div class="cw-detail-hint">캐릭터를 고르면 여기에 프롬프트가 나옵니다.</div>';
    }
    const row = (assetRows || []).find(item => item.id === assetPicked);
    const name = assetLabel(row || {id: assetPicked});
    if (!assetDetail) return '<div class="cw-detail-hint">불러오는 중…</div>';
    const variations = Array.isArray(assetDetail.variations) ? assetDetail.variations : [];
    const tiles = [{hash: '', revision: assetDetail.revision}, ...variations].map(entry => `
      <button type="button" class="cw-var${entry.hash === assetVariation ? ' is-on' : ''}"
        data-cw-asset-var="${escAttr(entry.hash)}"
        title="${entry.hash ? '변형' : '대표'}">
        <img loading="lazy" decoding="async" alt=""
          src="${escAttr(assetThumbUrl(assetPicked, entry.hash, entry.revision))}">
        ${entry.hash ? '' : '<span class="cw-var-star">★</span>'}
      </button>`).join('');
    const prompt = String(assetDetail.character_prompt || '');
    const uc = String(assetDetail.character_uc || '');
    return `
      <div class="cw-detail-head">
        <span class="cw-detail-name">${escHtml(name)}</span>
        <span class="cw-detail-id">${escHtml(String(assetPicked).slice(0, 8))}</span>
        <span class="cw-sp"></span>
        <button type="button" class="cw-li-btn" data-cw-asset-copy="1"
          title="프롬프트를 복사한다">⧉</button>
        <button type="button" class="cw-chip is-go" data-cw-asset-add="1"
          ${prompt ? '' : 'disabled'}
          title="${prompt ? '새 슬롯으로 담는다 (맨 아래)' : 'NAI 캐릭터 블록이 없어 담을 수 없습니다'}">+ 슬롯</button>
      </div>
      <div class="cw-detail-body">
        <div class="cw-detail-left">
          <img class="cw-detail-img" alt="" decoding="async"
            src="${escAttr(assetThumbUrl(assetPicked, assetVariation,
              assetVariation ? (variations.find(v => v.hash === assetVariation) || {}).revision
                             : assetDetail.revision))}">
          <div class="cw-detail-vars">${tiles}</div>
        </div>
        <div class="cw-detail-fields">
          <div class="cw-li-field">${prompt
            ? escHtml(prompt)
            : '<span class="cw-dim">NAI 캐릭터 블록이 없습니다 (복구 불가)</span>'}</div>
          ${uc ? `<div class="cw-li-field is-uc">${escHtml(uc)}</div>` : ''}
        </div>
      </div>`;
  }

  function renderAssetsTab() {
    const count = (assetRows || []).filter(assetMatches).length;
    return `
      <div class="cw-filters">
        <input class="cw-search" type="search" value="${escAttr(assetQuery)}"
          placeholder="이름 · id 검색…" data-cw-asset-search="1">
        <button type="button" class="cw-chip" data-cw-asset-reload="1" title="다시 읽는다">↻</button>
        <button type="button" class="cw-chip" data-cw-assets="1" title="편집·삭제는 여기서">에셋 탭 ↗</button>
      </div>
      <div class="cw-pane">
        <div class="cw-pane-top">
          <div class="cw-tiles">${renderAssetTiles()}</div>
        </div>
        <div class="cw-pane-bot${assetPicked ? '' : ' is-folded'}">${renderAssetDetail()}</div>
      </div>
      <div class="cw-pane-count">${count}개</div>`;
  }

  // ── 검색(도감) ──────────────────────────────────────────────────────────

  const DEX_PER_PAGE = 40;

  /** 이름의 첫 글자 - 그림이 없는 캐릭터의 폴백. 도감의 97% 는 그림이 없다. */
  function dexInitial(name) {
    return String(name || '?').trim().charAt(0).toUpperCase() || '?';
  }

  async function loadDex({reset = false} = {}) {
    if (dexLoading) {
      // ⚠️ **조건이 바뀐 요청은 버리면 안 된다**(실측 2026-09-03: `더 보기` 가 도는
      //    중에 [최신] 을 누르면 칩만 켜지고 목록은 13,497 그대로였다).
      //    검색어·작품·[최신] 이 바뀐 것이라, 버리면 **화면과 목록이 어긋난 채**
      //    남는다. 지금 것이 끝나면 곧바로 다시 돈다.
      if (reset) dexPending = true;
      return;
    }
    if (reset) { dexPage = 0; dexRows = []; }
    else if (dexPage >= dexPages) return;
    dexLoading = true;
    const seq = ++dexSeq;
    try {
      const parts = [
        `group=${encodeURIComponent(dexGroup || '__ALL__')}`,
        `query=${encodeURIComponent(dexQuery.trim())}`,
        `page=${dexPage}`, `per_page=${DEX_PER_PAGE}`, 'thumb_first=true',
        `recent_only=${dexRecent ? 'true' : 'false'}`,
        `favorites_only=${dexFav ? 'true' : 'false'}`,
      ];
      const res = await fetch(`/api/character-viewer/list?${parts.join('&')}`);
      const data = await res.json().catch(() => ({}));
      // ⚠️ 낡은 응답은 버린다 - 한 글자마다 요청이 나가면 순서가 뒤집힌다.
      if (seq !== dexSeq) return;
      if (!res.ok) throw new Error(data.error || '캐릭터를 불러오지 못했습니다.');
      const items = Array.isArray(data.items) ? data.items : [];
      dexRows = reset ? items : dexRows.concat(items);
      dexTotal = Number(data.total) || dexRows.length;
      dexPages = Number(data.total_pages) || 1;
      dexPage = (Number(data.page) || 0) + 1;
      // ⚠️ 작품 칩은 **이 응답**에서 온다. 예전에는 딴 길로 따로 물었는데, 그 길은
      //    검색어를 작품 **이름**에 맞춰 봐서 캐릭터를 치면 칩이 안 떴다
      //    (실측: `elysia` -> 0개 · 지금은 honkai 계열 4개).
      dexGroups = (Array.isArray(data.scope) ? data.scope : [])
        .map(row => ({key: String(row.key || ''), count: Number(row.count) || 0}))
        .filter(row => row.key);
      dexRecentSince = String(data.recent_since || '');
      dexFavCount = Number(data.favorite_count) || 0;
      dexError = '';
    } catch (error) {
      if (seq !== dexSeq) return;
      dexError = error.message || String(error);
    } finally {
      // ⚠️ **부분 갱신**이다. 전체를 다시 그리면 검색칸이 새로 만들어져 한 글자마다
      //    커서를 잃는다(히스토리 검색이 같은 이유로 이미 이렇게 한다).
      // ⚠️ 잠금은 **언제나** 푼다. 낡은 응답이라고 안 풀면 그대로 멈춘다.
      dexLoading = false;
      if (seq === dexSeq) scheduleRerender();
      if (dexPending) { dexPending = false; void loadDex({reset: true}); }
    }
  }

  /**
   * 도감 즐겨찾기를 켜고 끈다(사용자 요청 2026-09-03).
   *
   * ⚠️ 서버 응답으로 화면을 고친다 - 낙관적으로 먼저 뒤집으면, 거절당했을 때(없는
   *    캐릭터·쓰기 실패) 화면만 별이 켜진 채로 남는다.
   * ⚠️ [즐겨찾기] 로 걸러 보는 중에 별을 끄면 그 줄은 목록에서 빠져야 한다 - 그때만
   *    다시 불러온다. 아니면 그 줄만 고쳐 스크롤을 지킨다.
   */
  async function toggleDexFavorite(group, character) {
    if (!group || !character) return;
    const row = dexRows.find(r => r.group === group && r.character === character);
    const next = !(row ? row.favorite : (dexDetail && dexDetail.favorite));
    try {
      const res = await fetch('/api/character-viewer/favorite', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({group, character, favorite: next}),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || '즐겨찾기를 바꾸지 못했습니다.');
      dexFavCount = Number(data.favorite_count) || 0;
      if (row) row.favorite = !!data.favorite;
      if (dexDetail && dexPicked
          && dexPicked.group === group && dexPicked.character === character) {
        dexDetail.favorite = !!data.favorite;
      }
      if (dexFav && !data.favorite) { void loadDex({reset: true}); return; }
      rerender();
    } catch (error) {
      showToastSafe(error.message || String(error));
    }
  }

  function scheduleDexSearch() {
    if (dexTimer) clearTimeout(dexTimer);
    // 180ms - 프리셋 패널이 쓰는 값이다(사람이 한 글자 치는 사이).
    dexTimer = setTimeout(() => {
      dexTimer = 0;
      void loadDex({reset: true});
    }, 180);
  }

  async function loadDexDetail(group, character, variant) {
    const seq = ++dexDetailSeq;
    try {
      const res = await fetch('/api/character-viewer/detail', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        // ⚠️ 옵션을 **못 박는다**. 안 넘기면 Characters 탭에 저장된 값을 읽어,
        //    거기서 `hide_charname` 을 켜 뒀으면 여기서도 이름 대신 `original` 이
        //    나온다. 워크스페이스는 늘 캐릭터 이름을 넣는다.
        body: JSON.stringify({group, character, variant: variant || '',
                              options: {hide_charname: false, cosplay_enabled: false}}),
      });
      const data = await res.json().catch(() => ({}));
      if (seq !== dexDetailSeq) return;
      if (!res.ok) { dexDetailError = data.error || '상세를 불러오지 못했습니다.'; dexDetail = null; }
      else { dexDetail = data; dexDetailError = ''; }
    } catch (error) {
      if (seq !== dexDetailSeq) return;
      dexDetail = null;
      dexDetailError = error.message || String(error);
    }
    rerender();
  }

  function pickDex(group, character) {
    dexPicked = {group, character};
    dexVariant = '';
    dexDetail = null;
    dexDetailError = '';
    rerender();
    void loadDexDetail(group, character, '');
  }

  /** 고른 캐릭터를 **새 활성 슬롯**으로 담는다 - 에셋 탭과 같은 규약. */
  function addDexToSlot() {
    const prompt = String(dexDetail?.prompt?.character_prompt || '').trim();
    if (!prompt) { showToastSafe('담을 프롬프트가 없습니다.'); return; }
    const max = Number(lastState?.max_slots) || 0;
    const used = (lastState?.characters || []).filter(c => slotState(c) === 'active').length;
    if (max && used >= max) { showToastSafe(`활성 캐릭터 슬롯은 최대 ${max}개입니다.`); return; }
    // ⚠️ **한 번**에 끝낸다. 예전처럼 빈 슬롯을 만들고 번호를 찾아 채우면, 그 사이
    //    다른 클라이언트의 에코가 끼어 남의 슬롯을 덮는다(Fable 조사).
    setModuleParam('character', 'add_character', JSON.stringify({
      prompt,
      uc: '',
      custom_name: String(dexPicked?.character || ''),
    }));
    showToastSafe('슬롯 맨 아래에 담았습니다.');
  }

  function renderDexRows() {
    if (dexError && !dexRows.length) return `<div class="cw-empty">${escHtml(dexError)}</div>`;
    if (!dexRows.length) {
      const none = dexFav
        ? '즐겨찾기가 비어 있습니다. 줄 오른쪽 ☆ 를 눌러 넣으세요.'
        : (dexRecent ? '[최신] 을 끄면 더 나옵니다.' : '맞는 캐릭터가 없습니다.');
      return `<div class="cw-empty">${dexLoading ? '찾는 중…' : none}</div>`;
    }
    const picked = dexPicked ? `${dexPicked.group}\u0000${dexPicked.character}` : '';
    return dexRows.map(row => {
      const key = `${row.group}\u0000${row.character}`;
      const thin = Number(row.count) < 50;
      return `
      <button type="button" class="cw-dex${key === picked ? ' is-on' : ''}"
        draggable="true" data-cw-src="dex"
        data-cw-dex-group="${escAttr(row.group)}" data-cw-dex-char="${escAttr(row.character)}"
        title="${escAttr(`${row.character} · ${row.group}`)}">
        ${row.thumbnail_url
          ? `<img class="cw-dex-img" loading="lazy" decoding="async" alt=""
               src="${escAttr(row.thumbnail_url)}">`
          : `<span class="cw-dex-img is-initial">${escHtml(dexInitial(row.character))}</span>`}
        <span class="cw-dex-text">
          <span class="cw-dex-name">${escHtml(row.character)}</span>
          <span class="cw-dex-sub${thin ? ' is-thin' : ''}">${escHtml(row.group)} · ${row.count}</span>
        </span>
        <!-- 별. 줄 전체가 이미 button 이라 **button 을 겹쳐 넣을 수 없다** - span 으로
             두고 위임 클릭에서 줄보다 먼저 잡는다. -->
        <span class="cw-dex-star${row.favorite ? ' is-on' : ''}" role="button" tabindex="-1"
          data-cw-dex-star="1" data-cw-dex-star-group="${escAttr(row.group)}"
          data-cw-dex-star-char="${escAttr(row.character)}"
          title="${escAttr(row.favorite ? '즐겨찾기에서 뺍니다' : '즐겨찾기에 넣습니다')}"
          >${row.favorite ? '★' : '☆'}</span>
      </button>`;
    }).join('') + (dexPage < dexPages
      ? `<button type="button" class="cw-dex-more" data-cw-dex-more="1">${
          dexLoading ? '불러오는 중…' : `더 보기 (${dexRows.length} / ${dexTotal})`}</button>`
      : '');
  }

  function renderDexDetail() {
    if (!dexPicked) return '<div class="cw-detail-hint">캐릭터를 고르면 여기에 프롬프트가 나옵니다.</div>';
    if (!dexDetail) {
      return `<div class="cw-detail-hint">${dexDetailError
        ? escHtml(dexDetailError) : '불러오는 중…'}</div>`;
    }
    const prompt = String(dexDetail.prompt?.character_prompt || '');
    const variants = Array.isArray(dexDetail.variants) ? dexDetail.variants : [];
    // ⚠️ **보내는 것은 `label`(밑줄), 보이는 것은 `name`(공백)** 이다. 백엔드의
    //    `_resolve_variant` 는 `label` 로만 찾고, 못 찾으면 KeyError -> 404 를 낸다.
    //    뒤집어 보내고 있어서 변형을 고르면 아래 칸이 영영 '불러오는 중…' 에서
    //    멈췄다 - `Default` 칩까지(그건 label 이 빈 문자열이다) 그랬다.
    //    (사용자 제보 2026-09-03 · 실측: 'miss pink elf' -> KeyError)
    const chips = variants.length > 1 ? variants.map(v => `
      <button type="button" class="cw-chip${(v.label || '') === dexVariant ? ' is-go' : ''}"
        data-cw-dex-variant="${escAttr(v.label || '')}">${escHtml(v.name || '기본')}</button>`
      ).join('') : '';
    const thumb = dexDetail.thumbnail_url || dexDetail.default_thumbnail_url || '';
    return `
      <div class="cw-detail-head">
        <span class="cw-detail-name">${escHtml(dexPicked.character)}</span>
        <span class="cw-detail-id">${escHtml(dexPicked.group)} · ${dexDetail.count || 0}</span>
        <span class="cw-sp"></span>
        <button type="button" class="cw-li-btn cw-dex-star-btn${dexDetail.favorite ? ' is-on' : ''}"
          data-cw-dex-star="1" data-cw-dex-star-group="${escAttr(dexPicked.group)}"
          data-cw-dex-star-char="${escAttr(dexPicked.character)}"
          title="${escAttr(dexDetail.favorite ? '즐겨찾기에서 뺍니다' : '즐겨찾기에 넣습니다')}"
          >${dexDetail.favorite ? '★' : '☆'}</button>
        <button type="button" class="cw-li-btn" data-cw-dex-copy="1" title="프롬프트를 복사한다">⧉</button>
        <button type="button" class="cw-chip is-go" data-cw-dex-add="1"
          ${prompt ? '' : 'disabled'} title="새 슬롯으로 담는다 (맨 아래)">+ 슬롯</button>
      </div>
      ${chips ? `<div class="cw-detail-chips">${chips}</div>` : ''}
      <div class="cw-detail-body">
        <div class="cw-detail-left">
          ${thumb
            ? `<img class="cw-detail-img" alt="" decoding="async" src="${escAttr(thumb)}">`
            : `<div class="cw-detail-img is-initial">${escHtml(dexInitial(dexPicked.character))}</div>`}
        </div>
        <div class="cw-detail-fields">
          <div class="cw-li-field">${prompt ? escHtml(prompt) : '<span class="cw-dim">프롬프트 없음</span>'}</div>
        </div>
      </div>`;
  }

  /**
   * 검색칸 아래 **한 줄** - 왼쪽에 [최신], 오른쪽에 작품(사용자 지정 2026-09-03).
   *
   * [최신] 은 '요즘 그려지기 시작한 캐릭터' 다. 도감에는 날짜가 없어서 태그
   * 코퍼스에서 **처음 나타난 달**을 미리 뽑아 뒀다(tools/build_character_debut.py).
   * 작품은 좁혀 뒀으면 **푸는 칩 하나**만 보인다.
   */
  function renderDexScopeChips() {
    const since = dexRecentSince ? `${dexRecentSince.replace('-', '.')} 이후` : '요즘';
    const recent = `<button type="button" class="cw-chip cw-dex-recent${dexRecent ? ' is-go' : ''}"
      data-cw-dex-recent="1"
      title="${escAttr(`${since} 단부루에 처음 나타난 캐릭터만 봅니다`)}">최신</button>`;
    // [즐겨찾기] - 별을 켜 둔 것만. 하나도 없으면 눌러도 빈 목록이라 수를 함께 적는다.
    const fav = `<button type="button" class="cw-chip cw-dex-fav${dexFav ? ' is-go' : ''}"
      data-cw-dex-fav="1"
      title="${escAttr('별을 켜 둔 캐릭터만 봅니다 (캐릭터 탭과 같은 목록)')}">★ ${dexFavCount}</button>`;
    const rest = dexGroup
      ? `<button type="button" class="cw-chip is-go" data-cw-dex-group-clear="1">`
        + `✕ ${escHtml(dexGroup)}</button>`
      : dexGroups.map(g => `<button type="button" class="cw-chip"
          data-cw-dex-scope="${escAttr(g.key)}"
          title="${escAttr(`${g.key} · ${g.count}명`)}">${escHtml(g.key)}</button>`).join('');
    return recent + fav + `<span class="cw-dex-scope-gap"></span>` + rest;
  }

  function renderSearchTab() {
    const scoped = renderDexScopeChips();
    return `
      <div class="cw-filters">
        <input class="cw-search" type="search" value="${escAttr(dexQuery)}"
          placeholder="캐릭터 이름 · *태그 검색…" data-cw-dex-search="1">
        <button type="button" class="cw-chip" data-cw-search-tab="1" title="썸네일 등록·옵션은 여기서">Characters ↗</button>
      </div>
      <!-- 자기 클래스를 준다. 아래 칸의 변형 칩도 cw-detail-chips 라, 같은 이름이면
           부분 갱신이 엉뚱한 줄을 갈아 끼운다. (템플릿 안 주석에 백틱 금지) -->
      <div class="cw-dex-scope-row">${scoped}</div>
      <div class="cw-pane">
        <div class="cw-pane-top"><div class="cw-dex-list">${renderDexRows()}</div></div>
        <div class="cw-pane-bot${dexPicked ? '' : ' is-folded'}">${renderDexDetail()}</div>
      </div>
      <div class="cw-pane-count">${dexRows.length} / ${dexTotal}명</div>`;
  }

  // ── 왼쪽: 활성 슬롯 (전부 펼침) ─────────────────────────────────────────

  function renderSlot(character, index, ordinal) {
    const muted = !!character.muted;
    return `
      <div class="cw-slot${muted ? ' is-muted' : ''}" data-cw-slot="${index}">
        <!-- 머리줄을 끌면 슬롯끼리 순서를 바꾼다(같은 사이 자리에 놓는다). -->
        <div class="cw-slot-row" draggable="true"
          data-cw-drag="${index}" data-cw-drag-uuid="${escAttr(character.slot_uuid || '')}">
          <button type="button" class="cw-slot-en${muted ? '' : ' is-on'}"
            data-cw-mute="${index}" title="${muted ? '이 슬롯을 켠다' : '이 슬롯을 끈다 (자리는 그대로)'}">✔</button>
          <span class="cw-slot-name">C${ordinal} · ${escHtml(slotLabel(character))}</span>
          <!-- 테스트 생성 - 이 슬롯 하나만 뽑아 본다(사용자 지정 2026-09-02).
               히스토리 항목의 [즉시 생성] 과 같은 길이다. -->
          <button type="button" class="cw-slot-btn"
            data-cw-test="${escAttr(character.slot_uuid || '')}"
            title="이 캐릭터만 시험 삼아 한 장 뽑는다">▶</button>
          <button type="button" class="cw-slot-btn${character.favorite ? ' is-star' : ''}"
            data-cw-fav="${index}" title="즐겨찾기">${character.favorite ? '★' : '☆'}</button>
          <!-- ⚠️ **지우면 히스토리로 간다**(사용자 지정 2026-09-02). 그래서 위험
               색을 쓰지 않는다 - 잃는 것이 없다. 예전의 ▼(내리기)와 ✕(삭제)가
               같은 일이 되어 컨트롤이 하나로 줄었다. -->
          <button type="button" class="cw-slot-btn" data-cw-down="${index}"
            title="히스토리로 보낸다 (거기서 다시 담을 수 있다)">✕</button>
        </div>
        <div class="cw-slot-body">
          <textarea class="cw-input" data-cw-field="char_prompt_${index}" data-cw-min="prompt"
            rows="2" placeholder="캐릭터 프롬프트">${escHtml(character.prompt || '')}</textarea>
          <textarea class="cw-input is-uc" data-cw-field="char_uc_${index}" data-cw-min="uc"
            rows="1" placeholder="캐릭터 네거티브 (UC)">${escHtml(character.uc || '')}</textarea>
        </div>
      </div>`;
  }

  function renderSlots(activeSlots, total, maxSlots) {
    // ⚠️ 상한은 **서버가 준 값**을 쓴다. 프런트가 자기 숫자를 들고 있으면 둘이
    //    어긋나 "눌리는데 안 늘어나는" 버튼이 된다(백엔드는 조용히 거절한다).
    //
    // ⚠️ **활성만 센다.** 처음엔 전체 프레임 수로 셌는데, 그러면 히스토리가 슬롯
    //    자리를 먹는다 - `1 active · 39 stored` 인데 `+ Add Character (40/25)` 로
    //    잠겨 캐릭터를 못 늘렸다(사용자 제보). 상한은 **나가는 개수**의 상한이고,
    //    히스토리는 나가지 않는다.
    const used = activeSlots.length;
    const full = maxSlots > 0 && used >= maxSlots;
    // 사이사이에 **끼워 넣을 자리**를 둔다(사용자 지정 2026-09-02). 끄는 동안에만 보인다 -
    // 늘 보이면 목록이 시끄럽고, 안 보이면 어디에 꽂히는지 알 수 없다.
    //
    // `data-cw-label` 은 여기 놓으면 **몇 번 슬롯이 되는지**다(사용자 지정: "삽입되는
    // 공간을 좀 크게 한 뒤 C2에 할당됩니다"). 여기 적는 것은 순진한 값이고, 활성 슬롯을
    // 아래로 끌 때는 한 칸 당겨지므로 `labelGaps()` 가 끌기 시작에 다시 적는다.
    const gap = ordinal => `<div class="cw-slot-gap" data-cw-drop="${GRP_SLOT}"
      data-cw-gap="${ordinal}" data-cw-label="C${ordinal + 1}"></div>`;
    const body = activeSlots.length
      ? gap(0) + activeSlots.map(({character, index}, i) =>
          renderSlot(character, index, i + 1) + gap(i + 1)).join('')
      : '<div class="cw-slots-empty">활성 슬롯이 없습니다.<br>히스토리에서 담거나 새로 추가하세요.</div>';
    return `
      <!-- ⚠️ 칸 **전체**가 드롭 대상이다(사용자 지정 2026-09-02). 프롬프트 칸 위에
           떨어뜨려도 우리가 받는다 - 안 받으면 브라우저가 uuid 를 글자로 꽂는다
           (text/plain 을 함께 싣기 때문이다). dragover 의 preventDefault 가 막는다. -->
      <div class="cw-slots" data-cw-drop="${GRP_SLOT}">
        <div class="cw-slots-head">
          <span>슬롯</span><span class="cw-sp"></span>
          <span>${used}${maxSlots ? ` / ${maxSlots}` : ''}</span>
        </div>
        <div class="cw-slots-scroll">
          ${body}
          <button type="button" class="cw-add" data-cw-add="1"${full ? ' disabled' : ''}
            title="${full ? `활성 슬롯은 최대 ${maxSlots}개입니다` : ''}">${
            full ? `+ Add Character (${used}/${maxSlots})` : '+ Add Character'}</button>
        </div>
      </div>`;
  }

  // ── 오른쪽: 작업 영역 ───────────────────────────────────────────────────

  /**
   * 히스토리·즐겨찾기 검색. **프롬프트 쪽만 본다.**
   *
   * ⚠️ 그룹 이름은 빼 뒀다(사용자 지정 2026-09-02: "히스토리에서는 그룹까지 검색하는
   *    것이 비현실적입니다"). 그룹 하나에 수십 개가 들어 있으면 그 이름을 친 순간
   *    목록이 통째로 나와, 찾으려던 캐릭터가 오히려 묻힌다. 그룹으로 좁히는 일은
   *    **그룹 탭**이 펼쳐서 한다.
   */
  function matchesQuery(character) {
    const needle = query.trim().toLowerCase();
    if (!needle) return true;
    return [character.prompt, character.uc, character.custom_name]
      .join(' ').toLowerCase().includes(needle);
  }

  /** 히스토리 한 항목. 히스토리 탭과 그룹 탭(펼친 그룹 안)이 **같은 것**을 그린다. */
  /**
   * 히스토리 한 항목. 히스토리 탭과 그룹 탭(펼친 그룹 안)이 **같은 것**을 그린다.
   *
   * @param inGroup 그룹 탭에서 그린다면 그 행의 키(`fav` · `none` · `g:이름`).
   *   ⚠️ 오른쪽 끝 버튼의 **뜻이 달라진다**(사용자 제보 2026-09-02):
   *     히스토리 -> ✕ 영구 삭제 (전체 목록이니 그것이 옳다)
   *     그룹 안  -> − 이 그룹에서 빼기 (거기 있는 것은 **한 그룹의 사본이 아니라
   *                같은 캐릭터**다 - 지우면 즐겨찾기·히스토리에서 함께 사라진다.
   *                실제로 사용자가 그렇게 잃었다.)
   */
  function renderHistoryItem(character, index, groups, inGroup) {
    const uuid = String(character.slot_uuid || '');
    const open = openHistory.has(uuid);
    return `
    <div class="cw-li${open ? ' is-open' : ''}${groupOf(character) ? ' has-hue' : ''}"
      data-cw-li="${index}"${hueStyle(groupOf(character))}>
      <!-- ⚠️ 툴팁은 **프롬프트 전문**이다(사용자 지정 2026-09-02). 조작 설명을 띄우면
           정작 궁금한 것(잘린 뒷부분)을 볼 길이 없다. -->
      <div class="cw-li-row" data-cw-toggle="${escAttr(uuid)}" draggable="true"
        data-cw-drag="${index}" data-cw-drag-uuid="${escAttr(uuid)}"
        title="${escAttr(character.prompt || '(비어 있음)')}">
        <!-- 왼쪽 끝 = 복원(사용자 지정 2026-09-02). 슬롯 맨 아래로 간다. -->
        <button type="button" class="cw-li-btn" data-cw-load="${index}"
          title="슬롯으로 복원">↩</button>
        <!-- ⚠️ 즐겨찾기는 이제 **표시**다(조작은 펼친 뒤에 있다) - 안 보이면
             위의 ★ 필터가 무엇을 거르는지 알 수 없다. -->
      <span class="cw-li-text">${character.favorite ? '<span class="cw-li-fav">★</span> ' : ''}${escHtml(slotLabel(character, {full: true}))}</span>
        <!-- ⚠️ 그룹 안에서는 칩을 안 그린다 - **머리줄이 이미 그 이름**이다.
             히스토리·즐겨찾기에는 머리줄이 없으니 거기서는 남긴다. -->
        ${!inGroup && groupOf(character)
          ? `<span class="cw-li-group">${escHtml(groupOf(character))}</span>`
          : ''}
        <!-- 오른쪽 끝 = 삭제(사용자 지정). 여기가 **영영 지우는 유일한 길**이다 -
             슬롯의 ✕ 는 히스토리로 보낼 뿐이다. -->
        ${inGroup
          ? `<button type="button" class="cw-li-btn" data-cw-ungroup="${index}"
              data-cw-ungroup-key="${escAttr(inGroup)}"
              title="${inGroup === GRP_FAV ? '즐겨찾기에서 뺀다' : '이 그룹에서 뺀다 (캐릭터는 남는다)'}">−</button>`
          : `<button type="button" class="cw-li-btn is-danger" data-cw-remove="${index}"
              title="영구 삭제">✕</button>`}
      </div>
      ${open ? `
      <div class="cw-li-body">
        <div class="cw-li-field">${escHtml(character.prompt || '(비어 있음)')}</div>
        <div class="cw-li-field is-uc">${escHtml(character.uc || '(네거티브 없음)')}</div>
        ${groupPickerUuid === uuid ? `
        <div class="cw-li-picker">
          ${groups.map(name => `<button type="button" class="cw-chip${groupOf(character) === name ? ' is-on' : ''}"
            data-cw-pick-group="${index}" data-cw-group-name="${escAttr(name)}">${escHtml(name)}</button>`).join('')}
          <button type="button" class="cw-chip" data-cw-pick-group="${index}" data-cw-group-name="">그룹 해제</button>
          <button type="button" class="cw-chip is-go" data-cw-new-group-for="${index}">+ 새 그룹</button>
        </div>` : ''}
        <div class="cw-li-actions">
          <button type="button" class="cw-li-act${groupPickerUuid === uuid ? ' is-on' : ''}" data-cw-editgroup="${index}"
            data-cw-uuid="${escAttr(uuid)}">그룹에 전달</button>
          <button type="button" class="cw-li-act${character.favorite ? ' is-on' : ''}"
            data-cw-fav="${index}">${character.favorite ? '즐겨찾기 해제' : '즐겨찾기 등록'}</button>
          <button type="button" class="cw-li-act is-go" data-cw-gen="${index}">즉시 생성</button>
        </div>
      </div>` : ''}
    </div>`;
  }

  /**
   * 히스토리 · 즐겨찾기 목록. 둘은 **같은 목록의 다른 보기**라 한 함수로 그린다.
   *
   * @param onlyFav 즐겨찾기 탭이면 true - 별을 단 것만 보이고, 오른쪽 끝 버튼이
   *   `−`(즐겨찾기 해제)가 된다. 히스토리에서만 `✕`(영구 삭제)다.
   */
  function renderHistory(storedSlots, groups, onlyFav) {
    // ⚠️ 최근에 쓴 것이 위다. 백엔드 배열 순서는 저장 순서라 그대로 두면 오래된 것이
    //    위에 남는다(index 주소는 건드리지 않는다 - 보이는 순서만 바꾼다).
    const rows = [...storedSlots]
      .sort((a, b) => (b.character.used_at || 0) - (a.character.used_at || 0))
      .filter(({character}) => !onlyFav || character.favorite)
      .filter(({character}) => matchesQuery(character));
    const empty = onlyFav
      ? (storedSlots.length ? '조건에 맞는 즐겨찾기가 없습니다.' : '즐겨찾기가 없습니다. 항목을 펼쳐 [즐겨찾기 등록] 을 누르세요.')
      : (storedSlots.length ? '조건에 맞는 캐릭터가 없습니다.' : '아직 히스토리가 없습니다. 슬롯의 ✕ 로 지우면 여기에 쌓입니다 (최대 500개).');
    const list = rows.length
      ? rows.map(({character, index}) =>
          renderHistoryItem(character, index, groups, onlyFav ? GRP_FAV : '')).join('')
      : `<div class="cw-empty">${empty}</div>`;
    return `
      <div class="cw-filters">
        <input class="cw-search" type="search" value="${escAttr(query)}"
          placeholder="프롬프트 · 태그 검색…" data-cw-search="1">
        <!-- ⚠️ 그룹 칩과 ★ 칩은 걷었다(사용자 지정 2026-09-02). 그룹은 **그룹 탭**이
             펼쳐서 보여 주고 즐겨찾기는 **자기 탭**이 있다 - 여기 두면 같은 길이
             둘이고, 늘수록 검색칸을 밀어낸다. -->
      </div>
      <!-- ⚠️ 목록 **전체**가 수납 대상이다(사용자 지정 2026-09-02: "히스토리에서는
           사실상 X버튼을 누른것과 동일하게 작동"). 즐겨찾기 탭에는 안 단다 - 거기
           놓으면 별이 없어 그 탭에서 바로 사라져 보인다. -->
      <div class="cw-list"${onlyFav ? '' : ` data-cw-drop="${GRP_HIST}"`}>${list}</div>`;
  }

  /**
   * 그룹 탭 - 만들고, 지우고, 들여다본다(사용자 지정 2026-09-02).
   *
   * ⚠️ 즐겨찾기는 **그룹처럼** 보이되 항상 맨 위다(사용자 지정). 실제로는 플래그라
   *    지울 수 없다 - 그래서 ✕ 가 없다.
   * ⚠️ Cold 는 폐기된 상태다. 옛 cold 슬롯이 있으면 "Cold Storage" 그룹이 **한 번**
   *    생기고, 그 뒤로는 다른 그룹과 똑같다 - 지우면 사라진다(사용자 지적 2026-09-02).
   */
  function renderGroups(storedSlots, groups) {
    // 최근에 쓴 것이 위 - 히스토리 탭과 같은 순서.
    const ordered = [...storedSlots]
      .sort((a, b) => (b.character.used_at || 0) - (a.character.used_at || 0));
    const needle = groupQuery.trim().toLowerCase();
    const hit = character => !needle ||
      [character.prompt, character.uc, character.custom_name]
        .join(' ').toLowerCase().includes(needle);
    const members = key => ordered.filter(({character}) =>
      groupOf(character) === grpName(key) && hit(character));
    // ⚠️ 누르면 **그 자리에서 펼친다**(사용자 지정 2026-09-02: 탭을 옮기는 것은
    //    싫다). 펼친 안쪽은 히스토리 탭과 같은 항목이라 복원·삭제·펼침이 그대로 된다.
    const row = (key, label, {pinned = false, deletable = true} = {}) => {
      const items = members(key);
      // ⚠️ 검색 중에는 **맞는 것이 든 그룹만** 보이고 자동으로 펼친다 - 접힌 채
      //    개수만 바뀌면 어디에 있는지 알 수 없어 한 번 더 눌러야 한다.
      if (needle && !items.length) return '';
      const open = needle ? true : openGroups.has(key);
      return `
      <div class="cw-grp${pinned ? ' is-pinned' : ''}${open ? ' is-open' : ''}${
        grpName(key) ? ' has-hue' : ''}"${hueStyle(grpName(key))}>
        <div class="cw-grp-row" data-cw-drop="${escAttr(key)}">
          <button type="button" class="cw-grp-open" data-cw-toggle-group="${escAttr(key)}"
            title="${open ? '접는다' : '펼친다'}">
            <span class="cw-grp-caret">${open ? '▾' : '▸'}</span>
            ${escHtml(label)}
            <span class="cw-grp-count">${items.length}</span>
          </button>
          ${deletable ? `<button type="button" class="cw-li-btn is-danger" data-cw-remove-group="${escAttr(key)}"
            title="그룹 삭제 (안의 캐릭터는 그룹 없음으로 남는다)">✕</button>` : ''}
        </div>
        ${open ? `<div class="cw-grp-items">${items.length
          ? items.map(({character, index}) => renderHistoryItem(character, index, groups, key)).join('')
          : '<div class="cw-empty">비어 있습니다.</div>'}</div>` : ''}
      </div>`;
    };
    const rows = [
      // ⚠️ 즐겨찾기는 여기 없다 - **플래그이지 그룹이 아니다**(사용자 지정 2026-09-02).
      //    자기 탭에 있다.
      ...groups.map(name => row(grpKey(name), name)),
      // 그룹 없음도 한 줄이다 - 안 그러면 34개가 어디 있는지 찾을 길이 없다.
      row(GRP_NONE, '그룹 없음', {deletable: false}),
    ].join('');
    return `
      <div class="cw-filters">
        <!-- ⚠️ 여기는 **검색**이다(사용자 지정 2026-09-02). 예전엔 새 그룹 이름을 받는
             칸이었는데, 그룹이 늘면 정작 찾을 길이 없었다. 만들기는 팝업이 받는다. -->
        <input class="cw-search" type="search" value="${escAttr(groupQuery)}"
          placeholder="그룹 안에서 검색…" data-cw-group-search="1">
        <button type="button" class="cw-chip is-go" data-cw-add-group="1">+ 만들기</button>
      </div>
      <div class="cw-list cw-list-groups">${rows}</div>`;
  }
  function renderTools(state) {
    const preview = String(state.processed_preview_text || '');
    return `
      <div class="cw-tools">
        <label class="cw-tool-row">
          <input type="checkbox" ${state.reroll_on_generate ? 'checked' : ''} data-cw-reroll="1">
          <span>Generate 버튼을 누를 때 캐릭터 와일드카드 재굴림</span>
        </label>
        <div class="cw-tool-row">
          <button type="button" class="cw-chip" data-cw-refresh="1">Refresh Preview</button>
          <button type="button" class="cw-chip" data-cw-assets="1">Assets ↗</button>
        </div>
        <div class="cw-tool-note">
          미리보기는 저장된 롤을 그대로 보여 줍니다 — 열어도 다시 굴리지 않습니다.
        </div>
        ${preview.trim()
          ? `<pre class="mod-char-preview-text">${escHtml(preview)}</pre>`
          : '<div class="cw-empty">아직 미리보기가 없습니다. [Refresh Preview] 를 누르세요.</div>'}
      </div>`;
  }

  function renderWork(state, storedSlots, groups) {
    const tabs = TABS.map(item =>
      `<button type="button" class="cw-tab${tab === item.key ? ' is-active' : ''}"
        data-cw-tab="${item.key}">${item.label}</button>`).join('');
    let body;
    if (tab === 'history') body = renderHistory(storedSlots, groups, false);
    else if (tab === 'favourites') body = renderHistory(storedSlots, groups, true);
    else if (tab === 'groups') body = renderGroups(storedSlots, groups);
    else if (tab === 'tools') body = renderTools(state);
    else if (tab === 'assets') {
      // ⚠️ **편집·삭제·C1 적용은 여기 두지 않는다**(사용자 지정: "기존 기능 제거는
      //    아님"). 워크스페이스는 **소비**하는 자리다 - 고르고, 보고, 담는다.
      //    나머지는 `[에셋 탭 ↗]` 칩이 여는 원래 화면이 한다.
      body = renderAssetsTab();
      void loadAssets();
    } else {
      body = renderSearchTab();
      if (!dexRows.length && !dexLoading && !dexError) void loadDex({reset: true});
    }
    return `<div class="cw-work"><div class="cw-tabs">${tabs}<span class="cw-tab-fill"></span></div>${body}</div>`;
  }

  /**
   * 슬롯 칸만 갈아 끼운다. 작업 영역은 손대지 않는다.
   *
   * ⚠️ 슬롯 칸 안에도 스크롤이 있다(`.cw-slots-scroll`) - 그 자리를 되돌려 준다.
   *    이벤트는 뿌리에 위임돼 있어 다시 걸 필요가 없다.
   */
  function renderSlotsOnly(state) {
    const column = moduleBody.querySelector('.cw-slots');
    if (!column) return;
    const chars = state.characters || [];
    const indexed = chars.map((character, index) => ({character, index}));
    const activeSlots = indexed.filter(item => slotState(item.character) === 'active');
    const scroller = column.querySelector('.cw-slots-scroll');
    const keep = scroller ? scroller.scrollTop : 0;
    const parsed = document.createElement('div');
    parsed.innerHTML = renderSlots(activeSlots, chars.length, Number(state.max_slots) || 0);
    const next = parsed.querySelector('.cw-slots');
    if (!next) return;
    column.innerHTML = next.innerHTML;
    const again = column.querySelector('.cw-slots-scroll');
    if (again && keep) again.scrollTop = keep;
    // 새로 만든 textarea 는 높이를 맞추고 자동완성을 다시 건다.
    column.querySelectorAll('.cw-input').forEach(element => {
      autoGrow(element);
      if (!element.classList.contains('is-uc')) bindTagAssist(element);
    });
  }

  // ── 렌더 ────────────────────────────────────────────────────────────────

  function render(state) {
    const nextState = state || {};
    const structureSignature = characterStructureSignature(nextState);
    const focusedTextarea = focusedCharacterTextarea();
    if (focusedTextarea && lastRenderedStructureSignature === structureSignature) {
      lastState = nextState;
      queueDeferredFocusedRender(focusedTextarea, nextState);
      return;
    }
    clearDeferredFocusedRender();
    // ⚠️ **작업 영역이 그대로면 왼쪽만 갈아 끼운다.** 전체를 다시 쓰면 오른쪽 탭의
    //    입력칸·이미지·무한 스크롤 감시가 에코마다 새로 만들어진다(Fable 조사).
    //    슬롯 칸은 자기 안에 스크롤을 갖고 있으므로 그 자리도 지켜 준다.
    const workSig = workSignature(nextState);
    const shell = moduleBody.querySelector('.mod-character-shell');
    const slotColumn = moduleBody.querySelector('.cw-slots');
    if (shell && slotColumn && lastRenderedWorkSignature === workSig
        && lastRenderedStructureSignature !== structureSignature) {
      lastState = nextState;
      renderSlotsOnly(nextState);
      lastRenderedStructureSignature = structureSignature;
      return;
    }
    lastState = nextState;

    const chars = nextState.characters || [];
    const indexed = chars.map((character, index) => ({character, index}));
    // ⚠️ 배열은 백엔드가 [active][inactive][cold] 로 정렬해 보낸다. 여기서 순서를
    //    다시 만들지 않는다 - 만들면 index 주소가 저장 순서와 어긋난다.
    const activeSlots = indexed.filter(item => slotState(item.character) === 'active');
    const storedSlots = indexed.filter(item => slotState(item.character) !== 'active');
    const groups = groupsOf(nextState);

    moduleBody.innerHTML = `
      <div class="mod-character-shell">
        <div class="cw-slots-head" style="border-bottom:1px solid var(--border-dim)">
          <label class="cw-tool-row" style="gap:6px">
            <input type="checkbox" ${nextState.activated ? 'checked' : ''} data-cw-activated="1">
            <span>캐릭터 프롬프트 활성화</span>
          </label>
          <span class="cw-sp"></span>
          <span>${nextState.active_count || 0} active · ${storedSlots.length} stored</span>
        </div>
        <div class="cw-body">
          ${renderSlots(activeSlots, chars.length, Number(nextState.max_slots) || 0)}
          ${renderWork(nextState, storedSlots, groups)}
        </div>
      </div>`;

    moduleBody.querySelectorAll('.cw-input').forEach(element => {
      autoGrow(element);
      if (!element.classList.contains('is-uc')) bindTagAssist(element);
    });
    bindEvents();
    lastRenderedStructureSignature = structureSignature;
    lastRenderedWorkSignature = workSig;
    if (dragUuid && !moduleBody.querySelector(`[data-cw-drag-uuid="${dragUuid.replace(/"/g, '')}"]`)) clearDrag();

  }

  // ── 이벤트 (렌더마다 새 뿌리에 건다 - innerHTML 이 옛 리스너를 함께 지운다) ──

  function bindEvents() {
    const root = moduleBody.querySelector('.mod-character-shell');
    if (!root) return;

    root.addEventListener('input', event => {
      const field = event.target.closest('[data-cw-field]');
      if (field) {
        autoGrow(field);
        setModuleParam('character', field.dataset.cwField, field.value);
        return;
      }
      const dexSearch = event.target.closest('[data-cw-dex-search]');
      if (dexSearch) { dexQuery = dexSearch.value; scheduleDexSearch(); return; }
      const assetSearch = event.target.closest('[data-cw-asset-search]');
      if (assetSearch) { assetQuery = assetSearch.value; scheduleRerender(); return; }
      const groupSearch = event.target.closest('[data-cw-group-search]');
      // ⚠️ 히스토리와 **같은 규약**이다(사용자 제보 2026-09-02: 한 글자마다 포커스가
      //    빠졌다). `rerender()` 는 입력칸까지 새로 만들어 커서를 잃는다.
      if (groupSearch) { groupQuery = groupSearch.value; scheduleRerender(); return; }
      const search = event.target.closest('[data-cw-search]');
      if (search) { query = search.value; scheduleRerender(); return; }
      const activated = event.target.closest('[data-cw-activated]');
      if (activated) { setModuleParam('character', 'activated', String(activated.checked)); return; }
      const reroll = event.target.closest('[data-cw-reroll]');
      if (reroll) setModuleParam('character', 'reroll_on_generate', String(reroll.checked));
    });

    root.addEventListener('click', event => {
      const hit = selector => event.target.closest(selector);
      const tabBtn = hit('[data-cw-tab]');
      if (tabBtn) { tab = tabBtn.dataset.cwTab; rerender(); return; }
      const add = hit('[data-cw-add]');
      if (add) {
        if (add.disabled) {
          const max = Number(lastState?.max_slots) || 0;
          showToastSafe(`활성 캐릭터 슬롯은 최대 ${max}개입니다.`);
          return;
        }
        addSlot();
        return;
      }

      const fav = hit('[data-cw-fav]');
      if (fav) {
        const index = Number(fav.dataset.cwFav);
        const character = (lastState?.characters || [])[index];
        setModuleParam('character', `char_favorite_${index}`, String(!character?.favorite));
        return;
      }
      // ── 검색 탭(도감) ──────────────────────────────────────────────────
      // ⚠️ 별은 **줄보다 먼저** 본다. 별이 줄 안에 들어 있어서, 순서를 뒤집으면
      //    별을 눌러도 줄이 먼저 걸려 캐릭터만 골라진다.
      const star = hit('[data-cw-dex-star]');
      if (star) {
        void toggleDexFavorite(star.dataset.cwDexStarGroup || '',
                               star.dataset.cwDexStarChar || '');
        return;
      }
      const dexRow = hit('[data-cw-dex-group]');
      if (dexRow) {
        pickDex(dexRow.dataset.cwDexGroup || '', dexRow.dataset.cwDexChar || '');
        return;
      }
      if (hit('[data-cw-dex-more]')) { void loadDex(); return; }
      const scope = hit('[data-cw-dex-scope]');
      if (scope) {
        dexGroup = scope.dataset.cwDexScope || '';
        dexGroups = [];
        void loadDex({reset: true});
        return;
      }
      if (hit('[data-cw-dex-fav]')) {
        dexFav = !dexFav;
        void loadDex({reset: true});
        rerender();
        return;
      }
      if (hit('[data-cw-dex-recent]')) {
        dexRecent = !dexRecent;
        // 걸러진 목록은 처음부터 다시 센다 - 페이지를 이어 붙이면 섞인다.
        void loadDex({reset: true});
        rerender();
        return;
      }
      if (hit('[data-cw-dex-group-clear]')) {
        dexGroup = '';
        void loadDex({reset: true});
        return;
      }
      const dexVar = hit('[data-cw-dex-variant]');
      if (dexVar) {
        dexVariant = dexVar.dataset.cwDexVariant || '';
        rerender();
        void loadDexDetail(dexPicked?.group || '', dexPicked?.character || '', dexVariant);
        return;
      }
      if (hit('[data-cw-dex-add]')) { addDexToSlot(); return; }
      if (hit('[data-cw-dex-copy]')) {
        const text = String(dexDetail?.prompt?.character_prompt || '');
        if (!text) { showToastSafe('복사할 프롬프트가 없습니다.'); return; }
        navigator.clipboard?.writeText(text)
          .then(() => showToastSafe('프롬프트를 복사했습니다.'))
          .catch(() => showToastSafe('복사하지 못했습니다.'));
        return;
      }
      // ── 에셋 탭 ────────────────────────────────────────────────────────
      const tile = hit('[data-cw-asset]');
      if (tile) { pickAsset(tile.dataset.cwAsset || ''); return; }
      const varTile = hit('[data-cw-asset-var]');
      if (varTile) {
        assetVariation = varTile.dataset.cwAssetVar || '';
        // 선택 표시는 **즉시**, 글은 응답 뒤 - 기존 에셋 탭과 같은 순서다.
        rerender();
        void loadAssetDetail(assetPicked, assetVariation);
        return;
      }
      if (hit('[data-cw-asset-add]')) { void addAssetToSlot(); return; }
      if (hit('[data-cw-asset-reload]')) {
        assetPicked = ''; assetVariation = ''; assetDetail = null;
        void loadAssets({force: true});
        return;
      }
      if (hit('[data-cw-asset-copy]')) {
        const text = String(assetDetail?.character_prompt || '');
        if (!text) { showToastSafe('복사할 프롬프트가 없습니다.'); return; }
        navigator.clipboard?.writeText(text)
          .then(() => showToastSafe('프롬프트를 복사했습니다.'))
          .catch(() => showToastSafe('복사하지 못했습니다.'));
        return;
      }
      const test = hit('[data-cw-test]');
      if (test) { void instantGenerate(test.dataset.cwTest || ''); return; }
      const down = hit('[data-cw-down]');
      if (down) {
        const index = Number(down.dataset.cwDown);
        // 빈 슬롯은 히스토리로 안 보낸다 - 되살려도 할 일이 없는데 자리만 차지한다
        // (사용자 지정 2026-09-02). 백엔드도 저장할 때 같은 잣대로 걷는다.
        const slot = (lastState?.characters || [])[index];
        if (slot && isEmptySlot(slot)) { setModuleParam('character', `remove_character_${index}`, 'true'); return; }
        setSlotState(index, 'inactive');
        return;
      }
      const pick = hit('[data-cw-pick-group]');
      if (pick) {
        setModuleParam('character', `char_group_${Number(pick.dataset.cwPickGroup)}`, pick.dataset.cwGroupName || '');
        groupPickerUuid = '';
        return;
      }
      const newFor = hit('[data-cw-new-group-for]');
      if (newFor) { void editGroup(Number(newFor.dataset.cwNewGroupFor)); groupPickerUuid = ''; return; }
      const group = hit('[data-cw-editgroup]');
      if (group) {
        // 그룹 목록에서 고른다 - 이름을 매번 치게 하지 않는다(사용자 지정: "편히").
        const uuid = group.dataset.cwUuid || '';
        groupPickerUuid = groupPickerUuid === uuid ? '' : uuid;
        rerender();
        return;
      }
      if (hit('[data-cw-add-group]')) { void createGroup(); return; }
      const removeGroup = hit('[data-cw-remove-group]');
      if (removeGroup) {
        // 백엔드는 **이름**을 받는다 - 화면 키(`g:이름`)를 그대로 보내면 안 지워진다.
        setModuleParam('character', 'remove_group', grpName(removeGroup.dataset.cwRemoveGroup));
        return;
      }
      const toggleGroup = hit('[data-cw-toggle-group]');
      if (toggleGroup) {
        const key = toggleGroup.dataset.cwToggleGroup;
        if (openGroups.has(key)) openGroups.delete(key);
        else openGroups.add(key);
        rerender();
        return;
      }
      const load = hit('[data-cw-load]');
      if (load) {
        // 백엔드가 이제 상한에서 거절한다(Codex BLOCK 1) - 조용히 아무 일도 안 나면
        // 사용자는 이유를 모른다. 여기서 먼저 말해 준다.
        const max = Number(lastState?.max_slots) || 0;
        const used = (lastState?.characters || []).filter(c => slotState(c) === 'active').length;
        if (max && used >= max) { showToastSafe(`활성 캐릭터 슬롯은 최대 ${max}개입니다.`); return; }
        setSlotState(Number(load.dataset.cwLoad), 'active');
        return;
      }
      const gen = hit('[data-cw-gen]');
      if (gen) {
        const index = Number(gen.dataset.cwGen);
        void instantGenerate(String((lastState?.characters || [])[index]?.slot_uuid || ''));
        return;
      }
      const ungroup = hit('[data-cw-ungroup]');
      if (ungroup) {
        const index = Number(ungroup.dataset.cwUngroup);
        // ⚠️ **빼기지 삭제가 아니다.** 캐릭터는 히스토리에 그대로 남는다.
        if (ungroup.dataset.cwUngroupKey === GRP_FAV) {
          setModuleParam('character', `char_favorite_${index}`, 'false');
        } else {
          setModuleParam('character', `char_group_${index}`, '');
        }
        return;
      }
      const remove = hit('[data-cw-remove]');
      if (remove) { removeSlot(Number(remove.dataset.cwRemove)); return; }
      const mute = hit('[data-cw-mute]');
      if (mute) {
        const index = Number(mute.dataset.cwMute);
        const character = (lastState?.characters || [])[index];
        setModuleParam('character', `char_muted_${index}`, String(!character?.muted));
        return;
      }
      // ⚠️ **펼침 토글은 맨 마지막**이다. 이 표는 행 전체에 붙어 있어서, 위의
      //    버튼들보다 먼저 보면 행 안의 버튼(↩ ✕)을 눌러도 펼쳐지기만 한다
      //    (라이브에서 삭제가 안 먹었다: 히스토리 1개 -> 눌러도 1개).
      const toggle = hit('[data-cw-toggle]');
      if (toggle) {
        const uuid = toggle.dataset.cwToggle;
        openOnly(openHistory.has(uuid) ? '' : uuid);
        // ⚠️ **부분 갱신**이다. 전체를 다시 그리면 검색 입력칸이 새로 만들어지고,
        //    무엇보다 `.cw-list` 가 스크롤 컨테이너라 자리가 맨 위로 튄다.
        scheduleRerender();
        return;
      }



      if (hit('[data-cw-refresh]')) { refreshPreview(); return; }
      if (hit('[data-cw-assets]')) { window.openCharacterAssetTab?.(); return; }
      if (hit('[data-cw-search-tab]')) window.openCharacterViewerTab?.();
    });

    // ⚠️ 버튼을 누른 채 3px 만 밀려도 브라우저는 행을 끌기 시작한다 - 그러면 그
    //    클릭이 사라진다(✕ 를 눌렀는데 아무 일도 안 나는 것으로 보인다). dragstart 의
    //    target 은 **끌리는 요소**라 거기서는 버튼을 알 수 없어, 누른 자리를 기억한다.
    let pressedButton = false;
    root.addEventListener('mousedown', event => {
      pressedButton = !!(event.target && event.target.closest && event.target.closest('button'));
    });
    root.addEventListener('dragstart', event => {
      // 바깥에서 오는 것(에셋 타일 · 도감 행) - **내용**을 싣는다.
      const src = event.target && event.target.closest
        ? event.target.closest('[data-cw-src]') : null;
      if (src) { startSourceDrag(event, src); return; }
      const row = event.target && event.target.closest ? event.target.closest('[data-cw-drag]') : null;
      if (!row) return;
      if (pressedButton) { event.preventDefault(); return; }
      dragUuid = row.dataset.cwDragUuid || '';
      try {
        // ⚠️ **uuid 를 싣는다.** index 를 실으면 끌기 도중 다른 에코가 목록을 다시
        //    정렬했을 때 그 번호가 이미 남의 것이라 **엉뚱한 캐릭터가 옮겨진다**.
        //    index 는 놓는 순간 현재 상태에서 다시 찾는다.
        event.dataTransfer.setData(DND_MIME, dragUuid);
        // 일부 브라우저는 표준 자료형이 하나도 없으면 끌기를 취소한다.
        event.dataTransfer.setData('text/plain', dragUuid);
        event.dataTransfer.effectAllowed = 'move';
        const name = row.querySelector('.cw-slot-name, .cw-li-text');
        event.dataTransfer.setDragImage(
          dragChip((name?.textContent || '캐릭터').trim().slice(0, 40)), 12, 11);
      } catch (_) { /* 무시 */ }
      row.closest('.cw-li, .cw-slot')?.classList.add('is-dragging');
      // ⚠️ 히스토리 목록은 **활성 슬롯을 끌 때만** 불이 켜진다 - 히스토리의 것을
      //    히스토리에 놓는 것은 아무 일도 아닌데 받을 것처럼 보이면 거짓말이다.
      const stowing = (lastState?.characters || []).some(
        c => String(c.slot_uuid || '') === dragUuid && slotState(c) === 'active');
      moduleBody.querySelectorAll('[data-cw-drop]').forEach(el => {
        if (el.dataset.cwDrop === GRP_HIST && !stowing) return;
        el.classList.add('is-dropzone');
      });
      labelGaps();
    });
    root.addEventListener('dragend', () => clearDrag());
    root.addEventListener('dragover', event => {
      const target = aimed(event);
      if (!target) return;
      event.preventDefault();
      // 제자리 틈은 놓아도 아무 일이 없다 - 커서로 그렇게 말한다.
      const dead = target.classList.contains('is-self');
      event.dataTransfer.dropEffect = dead ? 'none' : 'move';
      if (dead) {
        moduleBody.querySelectorAll('.is-drop').forEach(el => el.classList.remove('is-drop'));
        return;
      }
      if (!target.classList.contains('is-drop')) {
        moduleBody.querySelectorAll('.is-drop').forEach(el => el.classList.remove('is-drop'));
        target.classList.add('is-drop');
      }
    });
    root.addEventListener('dragleave', event => {
      const target = event.target && event.target.closest ? event.target.closest('[data-cw-drop]') : null;
      if (target && !target.contains(event.relatedTarget)) target.classList.remove('is-drop');
    });
    root.addEventListener('drop', event => {
      const target = aimed(event);
      if (!target) return;
      if (target.classList.contains('is-self')) { event.preventDefault(); clearDrag(); return; }
      event.preventDefault();
      let uuid = '';
      try { uuid = event.dataTransfer.getData(DND_MIME); } catch (_) { uuid = ''; }
      // 바깥에서 온 것 - 슬롯이 아니라 **내용**을 꽂는다.
      if (!uuid && dragSource) {
        const gapAt = target.dataset.cwGap;
        // ⚠️ **먼저 챙기고 지운다.** `clearDrag()` 가 `dragSource` 도 비우므로,
        //    지운 뒤에 읽으면 늘 비어 있다(실측: "프롬프트를 아직 못 읽었습니다"
        //    토스트만 뜨고 슬롯이 안 늘었다).
        const seed = dragSource;
        clearDrag();
        dropSourceIntoSlots(gapAt, seed);
        return;
      }
      const key = target.dataset.cwDrop;
      // ⚠️ 놓은 뒤 표시를 붙잡아 두는 장치는 **안 넣는다.** 서버 에코가 화면을 바꾸기까지
      //    **16ms** 다(실측 2026-09-02, 놓은 순간부터 순서가 바뀔 때까지). 데스크톱
      //    앱도 같은 기계의 백엔드와 이야기하고, 지연이 있을 모바일에서는 HTML5 끌기가
      //    아예 안 뜬다 - 붙잡을 공백 자체가 없다.
      //    (설계 상담에 내가 "300~600ms" 라고 **재지 않은 숫자**를 넘겨 이 장치를
      //     한 번 만들었다 되물렸다. 숫자를 넘기기 전에 재라.)
      clearDrag();
      // 놓는 **지금**의 상태에서 번호를 찾는다(끌던 사이에 목록이 밀렸을 수 있다).
      const index = (lastState?.characters || []).findIndex(
        item => String(item.slot_uuid || '') === uuid);
      if (!uuid || index < 0) return;
      // 슬롯 칸 -> 활성으로 복원(맨 아래로 붙는다). 그룹 행 -> 그룹 이동(`none` = 해제).
      // 즐겨찾기는 그룹이 아니라 플래그라 드롭 대상이 아니다 - 항목을 펼쳐서 켠다.
      const active = slotState((lastState?.characters || [])[index]) === 'active';
      if (key === GRP_HIST) {
        // 이미 히스토리에 있는 것을 히스토리에 놓는 것은 아무 일도 아니다.
        if (active) setSlotState(index, 'inactive');
        return;
      }
      if (key === GRP_SLOT) {
        const already = active;
        // 상한을 넘으면 백엔드가 조용히 거절한다 - 여기서 먼저 알려 준다.
        // ⚠️ 이미 활성인 것을 **자리만 옮기는** 경우는 개수가 안 늘어나니 막지 않는다.
        const max = Number(lastState?.max_slots) || 0;
        const used = (lastState?.characters || []).filter(c => slotState(c) === 'active').length;
        if (!already && max && used >= max) {
          showToastSafe(`활성 캐릭터 슬롯은 최대 ${max}개입니다.`);
          return;
        }
        // 사이 자리에 놓았으면 그 번째로, **빈 곳에 놓았으면 맨 마지막**으로.
        //
        // ⚠️ 빈 곳을 `setSlotState(index, 'active')` 로 처리하면 **이미 활성인 것은
        //    아무 일도 안 난다**(같은 상태를 다시 쓸 뿐이다). 사용자 제보 2026-09-02:
        //    "Add Character 아래에 DnD 핸들러가 가면 항상 마지막 자리에 배치할 수
        //    있도록". 그래서 두 경우를 **한 길**로 모은다 - 자리 번호만 다르다.
        const gap = target.dataset.cwGap;
        const last = String(used);   // 활성 개수 = 마지막 자리 번호
        setModuleParam('character', `char_reorder_${index}`, gap === undefined ? last : gap);
        return;
      }
      // 그룹 행 - **활성 슬롯이면 복제본**을 넣는다(사용자 지정 2026-09-02:
      // "그룹에서는 복제본을 삽입합니다"). 슬롯은 그대로 두고 조합만 챙겨 둔다.
      // 히스토리의 것을 끌었으면 예전처럼 **옮긴다**(사본이 쌓이면 안 된다).
      if (active) {
        setModuleParam('character', `char_copy_to_group_${index}`, grpName(key));
        showToastSafe(`${grpName(key) || '그룹 없음'} 에 복제본을 넣었습니다.`);
        return;
      }
      setModuleParam('character', `char_group_${index}`, grpName(key));
    });


    root.addEventListener('contextmenu', event => {
      // ⚠️ 슬롯 행에서는 아무것도 가로채지 않는다 - 이름 조작이 히스토리로 갔고,
      //    프롬프트 칸에서 우클릭하면 붙여넣기 같은 기본 메뉴가 떠야 한다.
      // 히스토리 행은 그룹의 지름길로 남긴다(버튼도 함께 보인다).
      const item = event.target.closest('[data-cw-li]');
      if (!item) return;
      event.preventDefault();
      const character = (lastState?.characters || [])[Number(item.dataset.cwLi)];
      const uuid = String(character?.slot_uuid || '');
      if (uuid) { openOnly(uuid); groupPickerUuid = uuid; scheduleRerender(); }
    });
  }

  /** 검색어처럼 서버를 안 거치는 값은 그 자리에서 다시 그린다. */
  function rerender() {
    lastRenderedStructureSignature = '';
    render(lastState || {});
  }

  // ⚠️ 검색은 글자마다 다시 그리면 입력 칸이 갈리며 커서가 튄다. 목록만 갈아 끼운다.
  function scheduleRerender() {
    const list = moduleBody.querySelector('.cw-list');
    // ⚠️ 그룹 탭도 여기로 온다. 펼친 그룹 안의 항목은 `.cw-grp-items` 안에 있고 그것은
    //    다시 `.cw-list` 안이라, 목록만 갈아 끼워도 전부 갱신된다. 전체를 다시 그리면
    //    검색 입력칸이 새로 만들어져 **한 글자마다 커서를 잃는다**(사용자 제보).
    // 검색 탭은 `.cw-dex-list` 를 갈아 끼운다 - 검색칸을 새로 만들면 캐럿을 잃는다.
    if (tab === 'search') {
      const rows = moduleBody.querySelector('.cw-dex-list');
      if (!rows) { rerender(); return; }
      const scroller = rows.parentElement;
      const keepRows = scroller ? scroller.scrollTop : 0;
      rows.innerHTML = renderDexRows();
      if (scroller && keepRows) scroller.scrollTop = keepRows;
      const dexCount = moduleBody.querySelector('.cw-pane-count');
      if (dexCount) dexCount.textContent = `${dexRows.length} / ${dexTotal}명`;
      // ⚠️ 작품 칩도 함께 고친다. 목록만 갈아 끼우면 칩은 상태만 바뀌고 화면에
      //    안 나타난다(실측: `touhou` 를 쳐도 칩이 하나도 안 떴다).
      const scopeRow = moduleBody.querySelector('.cw-dex-scope-row');
      if (scopeRow) scopeRow.innerHTML = renderDexScopeChips();
      lastRenderedWorkSignature = workSignature(lastState);
      lastRenderedStructureSignature = characterStructureSignature(lastState);
      return;
    }
    // 에셋 탭은 `.cw-list` 가 아니라 `.cw-tiles` 를 갈아 끼운다.
    if (tab === 'assets') {
      const tiles = moduleBody.querySelector('.cw-tiles');
      if (!tiles) { rerender(); return; }
      const keepTiles = tiles.parentElement ? tiles.parentElement.scrollTop : 0;
      tiles.innerHTML = renderAssetTiles();
      if (tiles.parentElement && keepTiles) tiles.parentElement.scrollTop = keepTiles;
      const count = moduleBody.querySelector('.cw-pane-count');
      if (count) count.textContent = `${(assetRows || []).filter(assetMatches).length}개`;
      // ⚠️ 아래 칸도 함께 고친다(Codex NIT 9). `↻` 는 고른 것을 지우는데 상세는
      //    그대로 남아, 보이는 [+ 슬롯] 을 눌러도 아무 일이 안 났다.
      const bot = moduleBody.querySelector('.cw-pane-bot');
      if (bot) {
        bot.innerHTML = renderAssetDetail();
        bot.classList.toggle('is-folded', !assetPicked);
      }
      lastRenderedWorkSignature = workSignature(lastState);
      lastRenderedStructureSignature = characterStructureSignature(lastState);
      return;
    }
    if (!list || (tab !== 'history' && tab !== 'favourites' && tab !== 'groups')) {
      rerender();
      return;
    }
    const chars = lastState?.characters || [];
    const indexed = chars.map((character, index) => ({character, index}));
    const storedSlots = indexed.filter(item => slotState(item.character) !== 'active');
    const groups = groupsOf(lastState);
    const html = tab === 'groups'
      ? renderGroups(storedSlots, groups)
      : renderHistory(storedSlots, groups, tab === 'favourites');
    const parsed = document.createElement('div');
    parsed.innerHTML = html;
    const nextList = parsed.querySelector('.cw-list');
    if (!nextList) return;
    // ⚠️ `.cw-list` 가 **스크롤 컨테이너**다(overflow-y: auto). innerHTML 을 갈아
    //    끼우면 브라우저가 scrollTop 을 0 으로 되돌린다 - 목록을 한참 내려간 뒤
    //    항목 하나를 눌렀는데 맨 위로 튀었다(사용자 제보 2026-09-02).
    //    내용이 줄어들면 브라우저가 알아서 clamp 하므로 그대로 되돌려 주면 된다.
    const keep = list.scrollTop;
    list.innerHTML = nextList.innerHTML;
    if (keep) list.scrollTop = keep;
    // ⚠️ 부분 갱신도 **서명을 갱신해야** 한다. 안 그러면 화면은 새것인데 기록은
    //    옛것이라, 다음 에코가 "작업 영역이 바뀌었다" 고 보고 전부 다시 그린다
    //    (실측: 검색어를 한 글자 친 뒤 슬롯을 음소거하면 오른쪽이 통째로 새로 만들어졌다).
    lastRenderedWorkSignature = workSignature(lastState);
    lastRenderedStructureSignature = characterStructureSignature(lastState);
  }

  // 다른 창(예: Image Tagger 결과)이 '어느 캐릭터에 넣을까' 를 물으려면
  // 슬롯 목록이 필요하다. 렌더 상태를 그대로 빌려준다(사본).
  const getCharacters = () => (Array.isArray(lastState?.characters) ? [...lastState.characters] : []);

  // ⚠️ Cold 서랍은 사라졌다(그룹으로 접었다). app.js 의 옛 호출부가 남아 있으므로
  //    빈 껍데기를 남겨 둔다 - 없애면 `characterPanel.hideColdPanel is not a function`.
  const noop = () => {};

  return {
    getCharacters,
    addSlot,
    removeSlot,
    refreshPreview,
    setSlotState,
    renameSlot,
    // 프리뷰 창의 [Generate] 가 같은 캐릭터로 다시 뽑을 때 부른다.
    instantGenerate,
    // 결과(또는 오류)가 화면에 닿았다 - 연타 잠금을 푼다.
    instantDone: () => setInstantBusy(false),
    render,
    toggleColdPanel: noop,
    hideColdPanel: noop,
    setColdSearch: noop,
  };
}
