// Interactive Assets — 조합 스냅샷 컨트롤 패널.
//
// 결과 영역 좌하단(Generation Info 바로 위)에 붙는 가로 바다. Interactive 모드일
// 때만 보인다. 스냅샷은 **생성할 때** 남는다(app.js 가 record 를 부른다) — 만들다 만
// 조합으로 목록이 더러워지지 않게.
//
// 백엔드 계약(app/backend/server/interactive_assets_routes.py):
//   GET  /api/interactive-assets/snapshots?query=&origin=&favorite=&limit=
//   GET  /api/interactive-assets/snapshot?id=          조합 본문
//   GET  /api/interactive-assets/snapshot/thumb?id=    384px WEBP
//   POST /api/interactive-assets/snapshot   {chars}    기록(직전과 같으면 시각만 갱신)
//   POST /api/interactive-assets/favorite   {type,ref,label}
export function createInteractiveAssetsPanel({
  document,
  escHtml,
  showToast,
  showAppDialog,     // 삭제 확인용
  getPanel,          // () => interactivePanel (복원 대상)
}) {
  const root = document.getElementById('interactiveAssets');
  if (!root) return null;

  const LIMIT = 60;
  let open = false;          // 목록 펼침
  let visible = false;       // Interactive 모드 여부
  let busy = false;
  let rows = [];
  let origin = '';           // '' | 'original' | 'known'
  let favoriteOnly = false;
  let query = '';
  let searchTimer = null;
  let loadSeq = 0;           // 늦게 도착한 응답이 최신 목록을 덮지 않게
  let roster = [];           // 캐릭터 스택(패널이 알려 준다)
  // 조합을 꽂을 대상 슬롯. **기본 0(C1)** — 항상 대상이 있어야 칩 클릭이 바로 먹는다.
  let targetSlot = 0;
  // 카드를 누르면 **왼쪽에 미리보기 팝업**이 뜬다. 예전에는 카드 안에서 캐릭터 칩을
  // 펼쳤는데, 그때마다 목록 전체를 다시 그려 팝업이 통째로 깜빡였고(busy -> 렌더,
  // 응답 -> 렌더) 펼친 내용도 이름 칩 몇 개뿐이었다(사용자 지적 2026-08-05).
  // 이제 목록은 건드리지 않고 팝업만 갱신한다.
  let previewId = '';        // 미리보기를 연 조합
  let previewBody = null;    // 그 본문 {chars, globals}
  let previewBusy = false;
  let previewSeq = 0;        // 늦게 온 응답이 다른 카드의 미리보기를 덮지 않게
  // 무엇을 꽂을지. 카드를 누르면 여기 담기고, [적용] 을 눌러야 슬롯에 들어간다 —
  // 클릭 즉시 반영은 "무엇이 어디로 갔는지" 보이지 않아 직관적이지 않았다.
  let picked = null;         // {id, charIndex, label}
  // 캐릭터 검색 — 조합(스냅샷)과 별개다. 조합은 '전에 만든 것'이고 이쪽은
  // '캐릭터 도감에서 새로 고르는 것'이라 검색 대상도 결과도 겹치지 않는다.
  let charQuery = '';
  let charRows = [];
  let charBusy = false;
  let charSeq = 0;
  let charTimer = null;
  let charGroup = '';        // 작품으로 좁혔을 때의 그룹 키
  let charGroups = [];       // 검색어에 걸린 작품들
  let charShown = null;      // 지금 화면의 결과를 만든 조건 — 낡았는지 판단한다
  let charTotal = 0;         // 조건에 걸린 전체 인원
  let charPage = 0;
  let charPages = 1;
  let charMore = false;      // 다음 쪽을 이어붙이는 중
  let charObserver = null;   // 무한 스크롤 sentinel 관찰자
  // 고른 캐릭터를 **어떻게** 넣을지 묻는 팝업. 누르자마자 넣으면 되돌릴 수 없는
  // 프리셋 교체가 실수 한 번으로 일어난다.
  let ask = null;            // {index, slotId, slotLabel, name}
  let askEl = null;
  const CHAR_PAGE = 16;
  const CHAR_THIN = 50;      // 근거 행수 하위 25%(좌측 패널 PRESET_THIN_ROWS 와 같은 값)

  /** 삭제 확인. 다이얼로그를 못 받았으면 막는다 — 조용히 지우는 것보다 안 지우는 게 낫다. */
  async function confirmDelete(label) {
    if (typeof showAppDialog !== 'function') return false;
    return showAppDialog('', {
      title: '조합 삭제',
      messageHtml: `${escHtml(label || '이 조합')}<br>${escHtml('되돌릴 수 없습니다.')}`,
      okText: '삭제', cancelText: '취소',
    });
  }

  // ------------------------------------------------------------------ 통신

  async function fetchList() {
    const seq = ++loadSeq;
    const qs = new URLSearchParams({limit: String(LIMIT)});
    if (query) qs.set('query', query);
    if (origin) qs.set('origin', origin);
    if (favoriteOnly) qs.set('favorite', 'true');
    try {
      const r = await fetch('/api/interactive-assets/snapshots?' + qs.toString());
      const d = await r.json();
      if (seq !== loadSeq) return;              // 더 새로운 요청이 있다
      if (!r.ok) throw new Error(d.error || '목록을 불러오지 못했습니다');
      rows = Array.isArray(d.snapshots) ? d.snapshots : [];
    } catch (err) {
      if (seq !== loadSeq) return;
      rows = [];
      showToast('Assets 목록 실패: ' + err.message, 'error');
    }
    renderGrid();
  }

  function charListUrl(group, query, page) {
    return '/api/character-viewer/list'
      + '?group=' + encodeURIComponent(group || '__ALL__')
      + '&query=' + encodeURIComponent(query || '')
      + '&page=' + (Number(page) || 0) + '&per_page=' + CHAR_PAGE + '&thumb_first=true';
  }

  /** 캐릭터 도감 검색. 좌측 프리셋 패널과 **같은 라우트**를 쓴다 —
   *  결과가 갈라지면 "패널에선 나오는데 여기선 안 나온다"가 된다. */
  async function fetchChars() {
    const q = charQuery.trim();
    const seq = ++charSeq;
    const want = q + '\u0000' + charGroup;
    if (!q && !charGroup) {
      charRows = []; charGroups = []; charTotal = 0; charBusy = false; charShown = want;
      renderCharHits();
      return;
    }
    charBusy = true;
    charMore = false;
    renderCharHits();
    try {
      // 이름 검색만으로는 **작품이 통째로 샌다** — 서버 필터가 캐릭터명과 태그만 보고
      // 작품 키는 안 보기 때문이다(실측: touhou 이름검색 32명 / 작품 실제 182명).
      // 그래서 좌측 프리셋 패널과 똑같이 작품 목록도 같이 물어 칩으로 낸다.
      const [list, groups] = await Promise.all([
        fetch(charListUrl(charGroup, q, 0), {cache: 'no-store'}).then(r => r.json()),
        (!charGroup && q)
          ? fetch('/api/character-viewer/groups?query=' + encodeURIComponent(q),
                  {cache: 'no-store'}).then(r => r.json())
          : Promise.resolve({items: []}),
      ]);
      if (seq !== charSeq) return;                 // 더 새로운 요청이 있다
      if (list.error) throw new Error(list.error);
      charRows = Array.isArray(list.items) ? list.items : [];
      charTotal = Number(list.total || 0);
      charPage = Number(list.page || 0);
      charPages = Math.max(1, Number(list.total_pages || 1));
      charGroups = (groups.items || [])
        .filter(g => g && g.key && g.key !== '__ALL__').slice(0, 4);
    } catch (err) {
      if (seq !== charSeq) return;
      charRows = []; charGroups = []; charTotal = 0; charPage = 0; charPages = 1;
      showToast('캐릭터 검색 실패: ' + err.message, 'error');
    }
    charBusy = false;
    charShown = want;
    renderCharHits();
  }

  /** 목록 끝이 보이면 다음 쪽을 이어붙인다. 검색 조건이 바뀌면(`charSeq`) 버린다 —
   *  이전 조건의 뒷쪽이 새 목록에 섞이면 화면과 다른 캐릭터가 눌린다. */
  async function fetchCharsMore() {
    if (charBusy || charMore || charStale()) return;
    if (charPage + 1 >= charPages) return;
    const seq = charSeq;
    charMore = true;
    try {
      const d = await fetch(charListUrl(charGroup, charQuery.trim(), charPage + 1),
                            {cache: 'no-store'}).then(r => r.json());
      if (seq !== charSeq) return;
      if (d.error) throw new Error(d.error);
      charPage = Number(d.page || charPage + 1);
      charPages = Math.max(1, Number(d.total_pages || charPages));
      const items = Array.isArray(d.items) ? d.items : [];
      const base = charRows.length;
      charRows = charRows.concat(items);
      appendCharRows(items, base);
    } catch (err) {
      if (seq !== charSeq) return;
      showToast('더 불러오지 못했습니다: ' + err.message, 'error');
    } finally {
      if (seq === charSeq) charMore = false;
    }
  }

  /** 찾은 캐릭터를 대상 슬롯에 꽂는다. 슬롯은 **id** 로 잡는다 —
   *  프리셋을 읽는 동안 앞 슬롯이 지워지면 번호가 다른 캐릭터를 가리킨다. */
  async function applyCharHit(item, kind, slotId, slotLabel) {
    if (busy || !item || !slotId) return;
    const panel = getPanel && getPanel();
    if (!panel || typeof panel.applyCharacterPresetTo !== 'function') {
      showToast('Interactive 패널이 준비되지 않았습니다', 'error');
      return;
    }
    busy = true;
    renderGrid();
    try {
      // 성공 토스트는 패널이 띄운다(넣은 태그 수·회수한 프리셋까지 알려 준다).
      const ok = await panel.applyCharacterPresetTo(slotId, {
        group: item.group, character: item.character,
        thumb: item.thumbnail_url || '', kind,
      });
      if (!ok) showToast(`${slotLabel} 에 넣지 못했습니다`, 'error');
    } finally {
      busy = false;
      renderGrid();
    }
  }

  /** 생성 직전에 부른다. **캐릭터 한 명이 에셋 하나**라 id 가 여럿 나온다.
   *  app.js 가 이걸 생성 요청에 실으면 백엔드가 결과 이미지로 384px 썸네일을
   *  전부에 붙인다(그림은 한 장뿐이다). 실패해도 생성은 진행한다. */
  async function record(chars, globals) {
    if (!Array.isArray(chars) || !chars.length) return [];
    try {
      const r = await fetch('/api/interactive-assets/snapshot', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        // globals = 씬 슬롯·구도. 미리보기 하단이 이걸 보여 준다.
        body: JSON.stringify({chars, globals: globals || {}}),
      });
      const d = await r.json();
      if (!r.ok) return [];
      const list = Array.isArray(d.snapshots) ? d.snapshots
        : (d.snapshot ? [d.snapshot] : []);       // 옛 응답도 받는다
      return list.map(s => String((s && s.id) || '')).filter(Boolean);
    } catch (_) {
      return [];   // 조합 기록 실패가 생성을 막으면 안 된다
    }
  }

  async function toggleFavorite(id, label) {
    try {
      const r = await fetch('/api/interactive-assets/favorite', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({type: 'snapshot', ref: id, label: label || ''}),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || '즐겨찾기 실패');
      const row = rows.find(x => x.id === id);
      if (row) row.favorite = !!d.on;
      // 즐겨찾기만 보는 중이라면 해제된 항목은 목록에서 빠져야 한다.
      if (favoriteOnly && !d.on) rows = rows.filter(x => x.id !== id);
      renderGrid();
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  async function remove(id) {
    const row = rows.find(x => x.id === id);
    const label = row ? row.summary : '';
    // 되돌릴 수 없으니 한 번 묻는다. 조합은 다시 만들 수 있지만 썸네일은 그 그림뿐이다.
    const ok = await confirmDelete(label);
    if (!ok) return;
    try {
      const r = await fetch('/api/interactive-assets/snapshot/delete', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({id}),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || '삭제 실패');
      rows = rows.filter(x => x.id !== id);
      renderGrid();                      // 먼저 화면에서 치워 반응을 즉시 보여 주고
      showToast(d.removed ? '조합 삭제' : '이미 없는 조합입니다', d.removed ? 'success' : 'info');
      // 다시 읽는다 — 목록은 LIMIT 개만 가져오므로 지운 만큼 뒤에서 채워져야 한다.
      // removed 여부와 무관하다: 이미 로컬 행을 뺐으므로 어느 쪽이든 서버와 맞춰야 한다
      // (다른 탭이 먼저 지웠으면 removed=false 인데 화면만 한 칸 줄어든 채 남는다).
      fetchList();
    } catch (err) {
      showToast('삭제 실패: ' + err.message, 'error');
    }
  }

  /** 고른 것을 대상 슬롯에 꽂는다. [적용] 버튼만 이걸 부른다 —
   *  본문은 목록에 없으므로 그때 읽는다(조합은 갱신될 수 있어 캐시하지 않는다). */
  async function applyPicked() {
    if (busy || !picked) return;
    const {id, charIndex} = picked;
    // 대상도 **누른 시점에 고정**한다. 본문을 읽는 동안 대상 칸을 바꾸면
    // 사용자가 확정한 슬롯이 아니라 나중 슬롯에 들어간다.
    // 번호가 아니라 **슬롯 id** 로 잡는다 — 그 사이 앞 슬롯이 지워지면 뒤가 당겨져
    // 같은 번호가 다른 캐릭터를 가리킨다(엉뚱한 슬롯을 덮어쓴다).
    const slot = targetSlot;
    const slotId = roster[slot] ? roster[slot].id : '';
    const slotLabel = roster[slot] ? roster[slot].label : `C${slot + 1}`;
    busy = true;
    renderGrid();
    try {
      const r = await fetch('/api/interactive-assets/snapshot?id=' + encodeURIComponent(id));
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || '조합을 불러오지 못했습니다');
      const row = Array.isArray(d.chars) ? d.chars[Number(charIndex)] : null;
      if (!row) throw new Error('그 캐릭터가 없습니다');
      const panel = getPanel && getPanel();
      if (!panel || typeof panel.applySnapshotCharById !== 'function') {
        throw new Error('Interactive 패널이 준비되지 않았습니다');
      }
      // 그 슬롯이 아직 살아 있는지 id 로 확인한다(지워졌으면 조용히 남의 자리에
      // 꽂지 않고 실패로 알린다).
      if (!slotId || !roster.some(c => c.id === slotId)) {
        throw new Error(`${slotLabel} 슬롯이 없습니다`);
      }
      if (!panel.applySnapshotCharById(slotId, row)) throw new Error('슬롯에 꽂을 수 없습니다');
      showToast(`${slotLabel} <- ${charLabel(row)}`, 'success');
    } catch (err) {
      showToast('적용 실패: ' + err.message, 'error');
    } finally {
      busy = false;
      renderGrid();
    }
  }

  /** 카드/칩을 고른다(아직 적용하지 않는다). 같은 것을 다시 누르면 해제. */
  function pick(id, charIndex, label) {
    const same = picked && picked.id === id && picked.charIndex === Number(charIndex);
    picked = same ? null : {id, charIndex: Number(charIndex), label: label || ''};
    renderGrid();
  }

  /** 대상 슬롯의 활성/비활성을 뒤집는다. 좌측 헤더 ACTIVE 버튼과 같은 동작. */
  function toggleOpenChar() {
    const cur = roster[targetSlot];
    const panel = getPanel && getPanel();
    if (!cur || !panel || typeof panel.toggleCharacterEnabled !== 'function') return;
    panel.toggleCharacterEnabled(cur.id);
  }

  /** 대상 슬롯을 지운다. 라벨(C1..Cn)은 index 로 계산되므로 지운 뒤 뒤 슬롯이
   *  자동으로 당겨진다 — C1 을 지우면 C2 가 C1 이 된다. */
  function deleteOpenChar() {
    const cur = roster[targetSlot];
    const panel = getPanel && getPanel();
    if (!cur || !panel || typeof panel.deleteCharacterById !== 'function') return;
    panel.deleteCharacterById(cur.id);
  }

  /** 캐릭터 슬롯을 하나 늘린다. 좌측 [+캐릭터 슬롯] 과 같은 동작(상한·토스트 공유).
   *  새로 생긴 칸을 곧바로 대상으로 잡는다 — 늘린 이유가 거기 꽂으려는 것이다. */
  function addSlot() {
    const panel = getPanel && getPanel();
    if (!panel || typeof panel.addCharacterSlot !== 'function') return;
    const before = roster.length;
    panel.addCharacterSlot();
    // addCharacterSlot 이 notifyRoster -> setRoster -> render 까지 이미 돌린 뒤다.
    // 대상만 바꾸면 화면에 안 실리므로 다시 그린다.
    if (before < 5 && roster.length > before) {
      targetSlot = before;
      render();
    }
  }

  /** 카드를 눌렀을 때 여는 미리보기. **목록은 다시 그리지 않는다** — 그리면
   *  팝업 전체가 깜빡인다(예전 동작). 팝업 노드 하나만 갈아 끼운다. */
  async function openPreview(id) {
    if (previewId === id) { closePreview(); return; }
    previewId = id;
    previewBody = null;
    previewBusy = true;
    const seq = ++previewSeq;
    markPreviewCard();
    renderPreview();
    try {
      const r = await fetch('/api/interactive-assets/snapshot?id=' + encodeURIComponent(id));
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || '조합을 불러오지 못했습니다');
      if (seq !== previewSeq) return;        // 그 사이 다른 카드를 눌렀다
      previewBody = d;
    } catch (err) {
      if (seq === previewSeq) showToast('불러오기 실패: ' + err.message, 'error');
    } finally {
      if (seq === previewSeq) { previewBusy = false; renderPreview(); }
    }
  }

  function closePreview() {
    previewId = '';
    previewBody = null;
    previewBusy = false;
    previewSeq++;                            // 진행 중인 응답을 버린다
    markPreviewCard();
    renderPreview();
  }

  /** 어느 카드를 보고 있는지 표시만 옮긴다 — 목록을 다시 그리지 않는다. */
  function markPreviewCard() {
    root.querySelectorAll('.ia-as-card').forEach(el => {
      el.classList.toggle('is-preview', !!previewId && el.dataset.asId === previewId);
    });
  }

  // ---- 미리보기 팝업 ------------------------------------------------------

  let previewEl = null;

  function ensurePreviewEl() {
    if (previewEl && document.body.contains(previewEl)) return previewEl;
    previewEl = document.createElement('div');
    previewEl.className = 'ia-as-preview';
    previewEl.hidden = true;
    // **body 직계**로 둔다. `.ia-assets` 안에 넣었더니 `.viewer-wrapper`
    // (z-index:0 + isolation:isolate) 안에 갇혀, 이 팝업이 결과 패널 왼쪽으로 나가는
    // 순간 좌측 컬럼의 컨트롤이 그 위를 덮었다(실측: 프롬프트 도구 줄이 뚫고 올라옴).
    // 바깥 클릭 판정은 root 와 이 노드를 **둘 다** 본다(onOutside).
    document.body.appendChild(previewEl);
    // 위임 리스너는 root 에 걸려 있는데 이 노드는 root 밖이다 — 따로 걸어 준다.
    // (안 걸면 팝업 안의 [적용]·[삭제] 가 아무 반응이 없다. 실측으로 걸렸다.)
    previewEl.addEventListener('click', onClick);
    return previewEl;
  }

  function tagChips(list) {
    const arr = (Array.isArray(list) ? list : []).map(t => String(t || '').trim()).filter(Boolean);
    if (!arr.length) return '';
    return arr.map(t => `<span class="ia-as-pv-tag">${escHtml(t)}</span>`).join('');
  }

  /** 캐릭터 한 명 — 이름 + 슬롯별 태그 + [적용]. */
  function previewCharHtml(row, i) {
    const label = charLabel(row);
    const fields = (row && row.fields) || {};
    const lines = Object.entries(fields)
      .map(([k, v]) => [k, (Array.isArray(v) ? v : []).filter(Boolean)])
      .filter(([, v]) => v.length)
      .map(([k, v]) => `<div class="ia-as-pv-line">
        <span class="ia-as-pv-key">${escHtml(k)}</span>
        <span class="ia-as-pv-tags">${tagChips(v)}</span></div>`).join('');
    const target = roster[targetSlot];
    const tLabel = target ? target.label : `C${targetSlot + 1}`;
    const off = row && row.state === 'disabled';
    return `<div class="ia-as-pv-char${off ? ' is-off' : ''}">
      <div class="ia-as-pv-charhead">
        <span class="ia-as-pv-cn">${escHtml(label)}</span>
        ${off ? '<span class="ia-as-pv-off">OFF</span>' : ''}
        ${row && row.pos ? `<span class="ia-as-pv-pos">${escHtml(row.pos)}</span>` : ''}
        <span class="ia-as-pv-spring"></span>
        <button type="button" class="ia-as-pv-btn" data-as-pvapply="${i}"
          title="이 캐릭터를 ${escHtml(tLabel)} 슬롯에 꽂습니다">${escHtml(tLabel)}에 적용</button>
      </div>
      ${lines || '<div class="ia-as-pv-none">태그 없음</div>'}
    </div>`;
  }

  /** 캐릭터에 속하지 않는 값(씬 슬롯 + 구도). 옛 조합에는 없다 — 그때는 줄을 내지 않는다. */
  function previewGlobalsHtml(g) {
    if (!g || typeof g !== 'object') return '';
    const slots = (g.slots && typeof g.slots === 'object') ? g.slots : {};
    const lines = Object.entries(slots)
      .map(([k, v]) => [k, (Array.isArray(v) ? v : []).filter(Boolean)])
      .filter(([, v]) => v.length)
      .map(([k, v]) => `<div class="ia-as-pv-line">
        <span class="ia-as-pv-key">${escHtml(k)}</span>
        <span class="ia-as-pv-tags">${tagChips(v)}</span></div>`);
    const comp = Array.isArray(g.composition_tags) ? g.composition_tags.filter(Boolean) : [];
    if (comp.length) {
      lines.unshift(`<div class="ia-as-pv-line">
        <span class="ia-as-pv-key">구도</span>
        <span class="ia-as-pv-tags">${tagChips(comp)}</span></div>`);
    }
    if (!lines.length) return '';
    return `<div class="ia-as-pv-globals">
      <div class="ia-as-pv-sect">글로벌</div>${lines.join('')}</div>`;
  }

  function renderPreview() {
    const el = ensurePreviewEl();
    if (!previewId || !open) { el.hidden = true; el.innerHTML = ''; return; }
    // 즐겨찾기를 누르면 목록이 다시 오고 여기까지 다시 그린다 — 훑던 자리를 잃지 않게.
    const keep = el.querySelector('.ia-as-pv-body')?.scrollTop || 0;
    const meta = rows.find(x => x.id === previewId);
    const chars = (previewBody && Array.isArray(previewBody.chars)) ? previewBody.chars : [];
    const body = previewBusy
      ? '<div class="ia-as-pv-none">불러오는 중…</div>'
      : (chars.length
          ? chars.map(previewCharHtml).join('') +
            previewGlobalsHtml(previewBody && previewBody.globals)
          : '<div class="ia-as-pv-none">빈 조합입니다</div>');
    const fav = !!(meta && meta.favorite);
    el.innerHTML = `
      <div class="ia-as-pv-head">
        <span class="ia-as-pv-title">조합 미리보기</span>
        <span class="ia-as-pv-meta">${chars.length ? `캐릭터 ${chars.length}` : ''}</span>
        <button type="button" class="ia-as-pv-x" data-as-pvclose="1" aria-label="닫기">&times;</button>
      </div>
      <div class="ia-as-pv-body">
        ${meta && meta.thumb
          ? `<div class="ia-as-pv-shot"><img alt="" loading="lazy"
               src="/api/interactive-assets/snapshot/thumb?id=${encodeURIComponent(previewId)}"></div>`
          : '<div class="ia-as-pv-shot is-empty">이 조합으로 생성해야 그림이 붙습니다</div>'}
        ${body}
      </div>
      <div class="ia-as-pv-foot">
        <button type="button" class="ia-as-pv-btn" data-as-pvrestore="1"
          title="모든 캐릭터 슬롯을 이 조합으로 덮어씁니다">전체 복원</button>
        <span class="ia-as-pv-spring"></span>
        <button type="button" class="ia-as-pv-btn${fav ? ' is-fav' : ''}" data-as-pvfav="1"
          title="${fav ? '즐겨찾기 해제' : '즐겨찾기'}">${fav ? '★' : '☆'}</button>
        <button type="button" class="ia-as-pv-btn is-del" data-as-pvdel="1"
          title="이 조합을 지웁니다 (되돌릴 수 없습니다)">삭제</button>
      </div>`;
    el.hidden = false;
    const bodyEl = el.querySelector('.ia-as-pv-body');
    if (bodyEl && keep) bodyEl.scrollTop = keep;
    positionPreview();
  }

  /** Assets 패널 **왼쪽**에 붙인다. 자리가 모자라면 오른쪽으로 넘긴다.
   *  `position: fixed` 라 패널이 뷰어 안에 있어도 그 밖으로 나갈 수 있다. */
  function positionPreview() {
    if (!previewEl || previewEl.hidden) return;
    const anchor = root.getBoundingClientRect();
    const box = previewEl.getBoundingClientRect();
    const gap = 10;
    let left = anchor.left - box.width - gap;
    if (left < 8) {
      const right = anchor.right + gap;
      left = (right + box.width <= window.innerWidth - 8) ? right : Math.max(8, anchor.left);
    }
    let top = Math.min(anchor.bottom - box.height, window.innerHeight - box.height - 8);
    previewEl.style.left = Math.round(left) + 'px';
    previewEl.style.top = Math.round(Math.max(8, top)) + 'px';
  }

  /** 칩에 쓸 이름. 캐릭터명이 없으면 첫 태그로 대신한다(빈 칩을 만들지 않는다). */
  function charLabel(row) {
    const f = (row && row.fields) || {};
    const name = (f['캐릭터'] || [])[0];
    if (name) return String(name);
    for (const k of Object.keys(f)) {
      const v = (f[k] || [])[0];
      if (v) return String(v);
    }
    return row && row.gender === 'male' ? '남성' : '여성';
  }

  async function restore(id) {
    if (busy) return;
    busy = true;
    renderGrid();
    try {
      const r = await fetch('/api/interactive-assets/snapshot?id=' + encodeURIComponent(id));
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || '조합을 불러오지 못했습니다');
      const chars = Array.isArray(d.chars) ? d.chars : null;
      if (!chars || !chars.length) throw new Error('빈 조합입니다');
      const panel = getPanel && getPanel();
      if (!panel || typeof panel.applySnapshotChars !== 'function') {
        throw new Error('Interactive 패널이 준비되지 않았습니다');
      }
      if (!panel.applySnapshotChars(chars)) throw new Error('복원할 수 없는 조합입니다');
      showToast(`조합 복원 (캐릭터 ${chars.length}명)`, 'success');
    } catch (err) {
      showToast('복원 실패: ' + err.message, 'error');
    } finally {
      busy = false;
      renderGrid();
    }
  }

  // ------------------------------------------------------------------ 렌더

  function tabBtn(value, label) {
    const on = origin === value;
    return `<button type="button" class="ia-as-tab${on ? ' is-on' : ''}"
             data-as-origin="${escHtml(value)}">${escHtml(label)}</button>`;
  }

  /** 캐릭터 스택 — Assets 바 **위**에 세로로 쌓인다(아래가 C1). 누르면 좌측
   *  아코디언이 그 슬롯으로 열린다. 여는 것만 한다 — 추가/삭제는 좌측이 소유. */
  function stackHtml() {
    if (!roster.length) return '';
    // 아래에서 위로 쌓이므로 뒤집는다. C1 이 바 바로 위에 붙어야 손이 짧다.
    // 조작 버튼은 **스택 아래 고정 줄**에 둔다.
    //   - 캐릭터 줄 옆에 붙이면 선택을 옮길 때마다 버튼이 따라 움직여 불편하다.
    //   - 스택 전체 옆에 하나만 두면 늘 맨 아래(C1) 옆에 걸려, C2 를 껐는데
    //     C1 이 꺼진 것처럼 읽힌다.
    // 어느 줄과도 나란하지 않은 자리에 두고 라벨에 번호를 실어 대상을 밝힌다.
    // 위치는 **캐릭터마다 다르고 서로 비교해야** 하므로 각 줄에 둔다(조작 버튼과 반대).
    // NAI 가 아니거나 1명이면 좌표를 안 보내므로 버튼도 내지 않는다.
    const panel = getPanel && getPanel();
    const posOn = !!(panel && typeof panel.positionAvailable === 'function'
                     && panel.positionAvailable());
    return '<div class="ia-as-stack">' + [...roster].reverse().map(c =>
      '<div class="ia-as-stackline">' +
      `<button type="button" class="ia-as-slot${c.open ? ' is-open' : ''}` +
      `${c.enabled ? '' : ' is-off'}" data-as-open="${c.index}"` +
      ` title="${escHtml(c.name || c.label)}${c.enabled ? '' : ' (비활성)'}">` +
      `${escHtml(c.label)}</button>` +
      (posOn && c.positioned !== false
        ? `<button type="button" class="ia-as-pos" data-as-pos="${escHtml(c.id)}"` +
          ` title="${escHtml(c.label)} 캔버스 위치 (NAI V4 centers)">` +
          `POS ${escHtml(c.pos || 'C3')}</button>`
        : '') +
      '</div>').join('') + '</div>' + slotCtlHtml();
  }

  /** 열린 캐릭터에 거는 조작 — 활성/비활성 토글과 삭제.
   *  **슬롯이 2개 이상이고 목록을 펼쳤을 때만** 낸다(사용자 지정): 하나뿐이면 지울 수
   *  없고, 접힌 바에서는 스택만 있으면 충분하다. */
  /** 스택 아래 고정 줄. 대상은 라벨의 번호로 밝힌다. */
  function slotCtlHtml() {
    if (!open || roster.length < 2) return '';
    // 대상은 **대상 슬롯**이다(스택 클릭도 이 값을 옮긴다). 예전에는 '열린 캐릭터'를
    // 따로 봤는데, 아코디언은 사용자가 다시 눌러 닫을 수 있어 열린 것이 없는 순간이
    // 생기고 그때 'C? 제거' 같은 표시가 떴다. 또 대상 칸은 [1] 인데 버튼은 C2 를
    // 가리키는 불일치가 났다 — 두 개념을 하나로 합쳤다.
    const cur = roster[targetSlot];
    if (!cur) return '';
    const enTip = `${cur.label} ${cur.enabled ? '비활성화 (생성에서 제외)' : '활성화'}`;
    return '<div class="ia-as-slotctl">' +
      `<button type="button" class="ia-as-slotbtn${cur.enabled ? ' is-on' : ''}"` +
      ` data-as-enable="1" title="${escHtml(enTip)}">` +
      `${escHtml(cur.label)} ${cur.enabled ? 'ACTIVE' : 'OFF'}</button>` +
      `<button type="button" class="ia-as-slotbtn is-del" data-as-delchar="1"` +
      ` title="${escHtml(cur.label)} 슬롯 삭제">${escHtml(cur.label)} 제거</button>` +
      '</div>';
  }

  /** 대상 슬롯 선택 — ASSETS 라벨 옆 가로 칸. 조합을 어디에 꽂을지 정한다.
   *  칸은 최대치(5)만큼 그리되 **없는 슬롯은 비워 둔다** — 몇 명까지 되는지 보인다.
   *  **목록이 펼쳐졌을 때만** 낸다 — 접혀 있으면 꽂을 카드가 없어 쓸 데가 없다. */
  function targetHtml() {
    const max = 5;
    const out = [];
    for (let i = 0; i < max; i++) {
      const exists = i < roster.length;
      // 만들 수 있는 것은 **바로 다음 칸 하나뿐**이다. 건너뛰어 고르게 하면 중간
      // 슬롯이 빈 채로 활성 생성되어 인원수와 프롬프트에 끼어든다.
      const canMake = i === roster.length && roster.length < max;
      const locked = !exists && !canMake;
      const on = i === targetSlot;
      if (canMake) {
        // 다음 칸은 **[+] 슬롯 추가**다. 여기서 인원을 늘리고 바로 그 칸을 겨눈다.
        out.push('<button type="button" class="ia-as-target is-add" data-as-addslot="1"' +
          (busy ? ' disabled' : '') +
          ` title="캐릭터 슬롯 추가 (C${i + 1})">+</button>`);
        continue;
      }
      const tip = exists ? `C${i + 1} 에 꽂기` : `C${roster.length + 1} 부터 채워야 합니다`;
      out.push(`<button type="button" class="ia-as-target${on ? ' is-on' : ''}` +
        `${exists ? '' : ' is-empty'}${locked ? ' is-locked' : ''}"` +
        ` data-as-target="${i}"${locked || busy ? ' disabled' : ''}` +
        ` title="${escHtml(tip)}">${exists ? i + 1 : ''}</button>`);
    }
    const label = picked
      ? `C${targetSlot + 1} 에 적용`
      : '카드를 먼저 고르세요';
    return '<div class="ia-as-targets">' + out.join('') + '</div>' +
      `<button type="button" class="ia-as-apply${picked ? ' is-ready' : ''}"` +
      ` data-as-apply="1"${picked ? '' : ' disabled'} title="${escHtml(label)}">적용</button>`;
  }

  // -------------------------------------------------------------- 확인 팝업

  function ensureAsk() {
    if (askEl && document.body.contains(askEl)) return askEl;
    askEl = document.createElement('div');
    askEl.className = 'ia-as-ask';
    askEl.hidden = true;
    document.body.appendChild(askEl);
    askEl.addEventListener('click', onAskClick);
    return askEl;
  }

  /** 목록의 그 줄에 붙여 연다. 아래로 펼치되 화면 밖이면 위로 뒤집는다
   *  (좌표 팝업·프리셋 카드와 같은 규약). */
  function openAsk(index, anchor) {
    const item = charRows[Number(index)];
    const cur = roster[targetSlot];
    if (!item || !cur || !anchor) return;
    // 슬롯도 캐릭터도 **연 시점에 고정**한다. 번호로 들고 있으면 그 사이 목록이
    // 갈리면 다른 줄을 가리킨다 — 고른 것 자체를 잡아 둔다.
    ask = {
      item, slotId: cur.id, slotLabel: cur.label,
      name: String(item.character || ''),
    };
    const el = ensureAsk();
    el.hidden = false;
    el.innerHTML = askHtml();
    const r = anchor.getBoundingClientRect();
    const box = el.getBoundingClientRect();
    const left = Math.max(8, Math.min(r.left, window.innerWidth - box.width - 8));
    let top = r.bottom + 6;
    if (top + box.height > window.innerHeight - 8) {
      top = Math.max(8, r.top - box.height - 6);
    }
    el.style.left = Math.round(left) + 'px';
    el.style.top = Math.round(top) + 'px';
    document.addEventListener('mousedown', onAskOutside, true);
    document.addEventListener('keydown', onAskKey, true);
  }

  function closeAsk() {
    ask = null;
    if (askEl) { askEl.hidden = true; askEl.innerHTML = ''; }
    document.removeEventListener('mousedown', onAskOutside, true);
    document.removeEventListener('keydown', onAskKey, true);
  }

  function askHtml() {
    if (!ask) return '';
    return '<button type="button" class="ia-as-askclose" data-as-askclose="1"' +
      ' title="닫기" aria-label="닫기">✕</button>' +
      `<div class="ia-as-askname">${escHtml(ask.name)}</div>` +
      `<div class="ia-as-asksub">${escHtml(ask.slotLabel)} 에 넣습니다</div>` +
      '<div class="ia-as-askbtns">' +
      '<button type="button" class="ia-as-askbtn" data-as-askkind="char"' +
      ' title="캐릭터 태그만 바꿉니다">캐릭터만</button>' +
      '<button type="button" class="ia-as-askbtn is-all" data-as-askkind="all"' +
      ' title="외형 태그까지 슬롯에 나눠 넣습니다">전부</button>' +
      '</div>';
  }

  function onAskClick(event) {
    const t = event.target.closest('[data-as-askclose],[data-as-askkind]');
    if (!t) return;
    event.preventDefault();
    if (t.dataset.asAskclose || !ask) { closeAsk(); return; }
    const {item, slotId, slotLabel} = ask;
    const kind = t.dataset.asAskkind === 'all' ? 'all' : 'char';
    closeAsk();
    applyCharHit(item, kind, slotId, slotLabel);
  }

  function onAskOutside(event) {
    if (askEl && askEl.contains(event.target)) return;
    closeAsk();
  }

  function onAskKey(event) {
    if (event.key === 'Escape') { event.stopPropagation(); closeAsk(); }
  }

  /** 그림 없는 캐릭터가 대부분이다 — 이름 이니셜로 채운다(좌측 프리셋과 같은 규칙). */
  function charInitial(name) {
    const words = String(name || '').replace(/\(.*?\)/g, ' ')
      .replace(/[^0-9A-Za-z\s]/g, ' ').trim().split(/\s+/).filter(Boolean);
    if (!words.length) return '#';
    return (words[0][0] + (words[1] ? words[1][0] : '')).toUpperCase();
  }

  /** 화면의 결과가 지금 조건보다 낡았나. 디바운스 220ms 동안 이전 결과가 그대로
   *  남는데, 클릭 한 번이 곧 프리셋 교체라 그 사이에 눌리면 **화면과 다른 캐릭터**가
   *  들어간다. 낡은 동안은 흐리게 두고 못 누르게 한다. */
  function charStale() {
    return charShown !== null && charShown !== (charQuery.trim() + '\u0000' + charGroup);
  }

  function charGroupsHtml() {
    const inner = charGroup
      ? `<button type="button" class="ia-as-chargroup is-scope" data-as-chargroup=""` +
        ` title="전체에서 다시 찾기">✕ ${escHtml(charGroup)}</button>`
      : charGroups.map(g =>
          `<button type="button" class="ia-as-chargroup" data-as-chargroup="${escHtml(g.key)}"` +
          ` title="이 작품의 캐릭터만 보기">${escHtml(g.name || g.key)}` +
          `<span>${Number(g.count || 0)}</span></button>`).join('');
    return inner ? `<div class="ia-as-charhead">${inner}</div>` : '';
  }

  /** 좌측 프리셋 목록의 **축소판**이다 — 썸네일 + 이름 + 작품·근거건수, 2열 그리드.
   *  가로 칩 한 줄로 냈더니 "작동은 하는데 쓰기 불편하다"(사용자)였다: 이름이 잘리고,
   *  가로 스크롤은 훑기 어렵고, 좌측에서 익힌 읽는 법이 여기서 안 통했다. */
  function charHitsHtml() {
    if (charBusy) return '<div class="ia-as-charnote">찾는 중…</div>';
    if (!charQuery.trim() && !charGroup) {
      return '<div class="ia-as-charnote">이름이나 작품을 입력하세요. 예: miku · genshin</div>';
    }
    const head = charGroupsHtml();
    if (!charRows.length) {
      return head +
        `<div class="ia-as-charnote">${escHtml(charQuery.trim() || charGroup)} — 맞는 캐릭터가 없습니다.</div>`;
    }
    const more = charTotal > charRows.length
      ? `<span class="ia-as-charmore">${charTotal.toLocaleString()}명 중 ${charRows.length}</span>`
      : `<span class="ia-as-charmore">${charTotal.toLocaleString()}명</span>`;
    const list = charRows.map(charItemHtml).join('') + charSentinelHtml();
    return head + `<div class="ia-as-charcount">${more}</div>` +
      `<div class="ia-as-charlist">${list}</div>`;
  }

  function charSentinelHtml() {
    // 이것이 보이면 다음 쪽을 이어붙인다(IntersectionObserver).
    return charPage + 1 < charPages
      ? '<div class="ia-as-charsentinel">더 불러오는 중…</div>' : '';
  }

  function charItemHtml(item, i) {
    const name = String(item.character || '');
      // 이름이 이미 `(작품)` 을 달고 있으면 작품 줄은 같은 말을 두 번 하는 것이다
      // (실측 9,738명 중 2,882명). 태그를 만들 때도 같은 판정을 쓴다
      // (interactivePanel.characterTagsOf).
      const raw = String(item.group || '');
      const work = (raw && !name.includes(`(${raw})`)) ? raw : '';
      const count = Number(item.count || 0);
      const thumb = item.thumbnail_url
        ? `<span class="ia-as-charthumb"><img src="${escHtml(item.thumbnail_url)}" alt=""
             loading="lazy" decoding="async"></span>`
        : `<span class="ia-as-charthumb is-none">${escHtml(charInitial(name))}</span>`;
      return `<button type="button" class="ia-as-charitem" data-as-charhit="${i}"` +
        `${busy || charStale() ? ' disabled' : ''}>` +
        thumb +
        '<span class="ia-as-charinfo">' +
        `<span class="ia-as-charname">${escHtml(name)}</span>` +
        '<span class="ia-as-charmeta">' + (work ? escHtml(work) : '') +
        // 근거가 적은 캐릭터는 프리셋이 부실하다 — 좌측 목록과 같은 경고 색.
        `<span class="ia-as-charnum${count < CHAR_THIN ? ' is-thin' : ''}">` +
        `${count.toLocaleString()}</span></span></span></button>`;
  }

  /** 조합 검색 줄 아래. 대상 슬롯이 어디인지 라벨로 밝힌다 — 클릭 한 번에
   *  그 슬롯이 바뀌므로 어디로 가는지 보이지 않으면 위험하다. */
  function charRowHtml() {
    const cur = roster[targetSlot];
    const to = cur ? cur.label : 'C1';
    // 어떻게 넣을지는 고른 **뒤에** 팝업이 묻는다 — 미리 정해 두는 토글은 지금 어느
    // 모드인지 늘 확인해야 해서 오히려 손이 갔다.
    return `
      <div class="ia-as-charrow">
        <input class="ia-as-charq" type="search" data-as-charq="1"
               placeholder="캐릭터 검색 — ${escHtml(to)} 에 넣을 캐릭터"
               value="${escHtml(charQuery)}">
      </div>
      <div class="ia-as-charhits">${charHitsHtml()}</div>`;
  }

  /** 결과만 갈아 끼운다 — 전체 render() 는 입력창 노드를 바꿔 타이핑 중 캐럿이 날아간다. */
  function renderCharHits() {
    const host = root.querySelector('.ia-as-charhits');
    if (!host) { if (visible && open) render(); return; }
    host.innerHTML = charHitsHtml();
    host.classList.toggle('is-stale', charStale());
    charObserve();
  }

  /** 목록을 통째로 다시 그리지 않고 뒤에 붙인다 — 다시 그리면 스크롤이 맨 위로 튄다. */
  function appendCharRows(items, base) {
    const list = root.querySelector('.ia-as-charlist');
    if (!list) { renderCharHits(); return; }
    const sentinel = list.querySelector('.ia-as-charsentinel');
    const html = items.map((item, k) => charItemHtml(item, base + k)).join('');
    if (sentinel) sentinel.insertAdjacentHTML('beforebegin', html);
    else list.insertAdjacentHTML('beforeend', html);
    if (sentinel && charPage + 1 >= charPages) sentinel.remove();
    const count = root.querySelector('.ia-as-charcount');
    if (count) {
      count.innerHTML = charTotal > charRows.length
        ? `<span class="ia-as-charmore">${charTotal.toLocaleString()}명 중 ${charRows.length}</span>`
        : `<span class="ia-as-charmore">${charTotal.toLocaleString()}명</span>`;
    }
    charObserve();
  }

  function charObserve() {
    if (charObserver) { charObserver.disconnect(); charObserver = null; }
    if (typeof IntersectionObserver !== 'function') return;
    const list = root.querySelector('.ia-as-charlist');
    const sentinel = list && list.querySelector('.ia-as-charsentinel');
    if (!list || !sentinel) return;
    charObserver = new IntersectionObserver(entries => {
      if (entries.some(e => e.isIntersecting)) void fetchCharsMore();
    }, {root: list, rootMargin: '80px'});
    charObserver.observe(sentinel);
  }

  function card(row) {
    const id = escHtml(String(row.id || ''));
    const summary = String(row.summary || '(빈 조합)');
    const thumb = row.thumb
      ? `<img class="ia-as-thumb" loading="lazy" alt=""
              src="/api/interactive-assets/snapshot/thumb?id=${encodeURIComponent(row.id)}">`
      // 썸네일은 그 조합으로 생성해야 붙는다 — 아직이면 자리를 비워 둔다.
      : `<span class="ia-as-thumb is-empty" aria-hidden="true">…</span>`;
    // 카드는 **여는 것만** 한다. 적용·즐겨찾기·삭제는 미리보기 팝업이 맡는다 —
    // 작은 카드에 버튼 셋을 얹으니 오조작이 잦고, 펼침 칩은 목록을 재배치해 깜빡였다.
    // 즐겨찾기는 별 표시로만 남긴다(누르는 것은 팝업에서).
    return `<div class="ia-as-card${row.favorite ? ' is-fav' : ''}` +
      `${previewId === row.id ? ' is-preview' : ''}" data-as-id="${id}"
              title="${escHtml(summary)}">
      <button type="button" class="ia-as-pick" data-as-preview="${id}">
        ${thumb}
        <span class="ia-as-summary">${escHtml(summary)}</span>
      </button>
      ${row.favorite ? '<span class="ia-as-star is-mark" aria-label="즐겨찾기">★</span>' : ''}
    </div>`;
  }

  /** 목록만 다시 그린다. 전체 render() 는 검색창 노드를 갈아치워 입력 중 포커스와
   *  캐럿이 날아간다 — 응답이 220ms 뒤에 오므로 타이핑 도중에 정확히 걸린다. */
  function renderGrid() {
    // 고른 카드가 목록에서 빠졌으면(즐겨찾기 해제·삭제·필터) 선택을 놓는다 —
    // 화면에 없는 것이 적용되면 무엇이 들어갔는지 알 수 없다.
    if (picked && !rows.some(x => x.id === picked.id)) picked = null;
    // 미리보기로 보던 조합이 목록에서 사라졌으면(삭제·필터) 팝업도 닫는다 —
    // 없는 것을 보여 주면서 [적용]/[삭제] 를 내놓을 수는 없다.
    if (previewId && !rows.some(x => x.id === previewId)) closePreview();
    const grid = root.querySelector('.ia-as-grid');
    if (!grid) { render(); return; }
    grid.innerHTML = busy
      ? '<div class="ia-as-empty">불러오는 중…</div>'
      : (rows.length ? rows.map(card).join('')
                     : '<div class="ia-as-empty">저장된 조합이 없습니다. 생성하면 남습니다.</div>');
    const count = root.querySelector('.ia-as-count');
    if (count) count.textContent = rows.length || '';
    // 탭 활성 표시도 여기서 맞춘다. 전체 render() 를 부르면 검색창 노드가 바뀌어
    // 입력 중 포커스가 날아가므로, 클래스만 손으로 동기화한다.
    root.querySelectorAll('[data-as-origin]').forEach(btn => {
      btn.classList.toggle('is-on', (btn.dataset.asOrigin || '') === origin);
    });
    const favBtn = root.querySelector('[data-as-favonly]');
    if (favBtn) favBtn.classList.toggle('is-on', favoriteOnly);
    // 미리보기 발치의 ★ 도 목록에서 읽는다 — 여기서 안 맞추면 카드만 별이 켜지고
    // 팝업은 ☆ 인 채로 남는다(실측).
    renderPreview();
    root.querySelectorAll('[data-as-target],[data-as-addslot]').forEach(btn => {
      // 적용 중에는 대상을 못 바꾼다 — 어차피 시작 시점으로 고정되므로 UI 도 맞춘다.
      if (busy) btn.disabled = true;
      else if (!btn.classList.contains('is-locked')) btn.disabled = false;
    });
    // 슬롯 구성을 바꾸는 것들도 함께 잠근다 — 적용 중 삭제하면 뒤 슬롯이 당겨져
    // 사용자가 고르지 않은 캐릭터가 덮어써진다.
    root.querySelectorAll('[data-as-enable],[data-as-delchar],[data-as-pos]')
      .forEach(btn => { btn.disabled = busy; });
    // 결과 칩은 적용 중 말고 **낡았을 때도** 못 누른다(charStale 주석 참조).
    root.querySelectorAll('[data-as-charhit],[data-as-chargroup]')
      .forEach(btn => { btn.disabled = busy || charStale(); });
    const apply = root.querySelector('[data-as-apply]');
    if (apply) {
      apply.disabled = !picked || busy;
      apply.classList.toggle('is-ready', !!picked);
      // 앱이 title 을 data-naia-title 로 흡수해 자체 툴팁을 띄운다(app.js).
      // title 만 고치면 흡수가 끝난 뒤라 아무 데도 안 보인다.
      const tip = picked ? `C${targetSlot + 1} 에 적용` : '카드를 먼저 고르세요';
      apply.setAttribute('data-naia-title', tip);
      apply.setAttribute('aria-label', tip);
    }
  }

  function render() {
    root.hidden = !visible;
    if (!visible) { root.innerHTML = ''; return; }
    root.classList.toggle('is-open', open);
    const keepScroll = root.querySelector('.ia-as-charlist')?.scrollTop || 0;

    // 검색줄·캐릭터줄·그리드는 테두리를 이어 붙여 **한 덩어리**로 보이게 만든 것이라
    // 사이가 벌어지면 안 된다. 예전에는 셋 다 `.ia-assets` 직계여서 그 flex gap(6px)이
    // 사이사이를 갈라 놨고, 그 틈으로 생성 이미지가 그대로 비쳤다(사용자 지적).
    const list = !open ? '' : `
      <div class="ia-as-list">
        <div class="ia-as-controls">
          <input class="ia-as-search" type="search" placeholder="조합 검색"
                 value="${escHtml(query)}" data-as-search="1">
          <div class="ia-as-tabs">
            ${tabBtn('', '전체')}${tabBtn('original', '오리지널')}${tabBtn('known', '기존 캐릭터')}
            <button type="button" class="ia-as-tab is-star${favoriteOnly ? ' is-on' : ''}"
                    data-as-favonly="1" title="즐겨찾기만">★</button>
          </div>
        </div>
        ${charRowHtml()}
        <div class="ia-as-grid">
          ${busy ? '<div class="ia-as-empty">불러오는 중…</div>'
                 : (rows.length ? rows.map(card).join('')
                                : '<div class="ia-as-empty">저장된 조합이 없습니다. 생성하면 남습니다.</div>')}
        </div>
        <div class="ia-as-foot">
          <span class="ia-as-foothint">카드를 누르면 왼쪽에 미리보기가 열립니다</span>
          <button type="button" class="ia-as-fold" data-as-fold="1"
                  title="Assets 목록을 접습니다 (바깥을 눌러도 접힙니다)">접기</button>
        </div>
      </div>`;

    root.innerHTML = `
      ${stackHtml()}
      <div class="ia-as-bar">
        <button type="button" class="ia-as-toggle" data-as-toggle="1"
                aria-expanded="${open ? 'true' : 'false'}">
          <span class="ia-as-caret">${open ? '▾' : '▸'}</span>
          <span class="ia-as-title">Assets</span>
          <span class="ia-as-count">${rows.length || ''}</span>
        </button>
        ${open ? targetHtml() : ''}
      </div>
      ${list}`;

    // 캐릭터를 꽂을 때마다 roster 가 바뀌어 여기까지 전체 렌더가 돈다. 목록 노드가
    // 통째로 갈리므로 훑던 자리를 잃고 맨 위로 튄다 — 스크롤을 넘겨받는다.
    // 관찰자도 사라진 sentinel 을 보고 있으니 다시 붙인다(안 그러면 이어받기가 죽는다).
    const nextList = root.querySelector('.ia-as-charlist');
    if (nextList && keepScroll) nextList.scrollTop = keepScroll;
    charObserve();
    renderPreview();   // 위치·내용을 패널 재렌더에 맞춘다(노드는 body 직계라 살아 있다)
  }

  // ------------------------------------------------------------------ 입력

  function onClick(event) {
    const t = event.target.closest('[data-as-toggle],[data-as-origin],[data-as-favonly],' +
      '[data-as-restore],[data-as-fav],[data-as-del],[data-as-open],[data-as-target],' +
      '[data-as-preview],[data-as-pick],[data-as-apply],[data-as-addslot],' +
      '[data-as-fold],[data-as-pvclose],[data-as-pvapply],[data-as-pvrestore],' +
      '[data-as-pvfav],[data-as-pvdel],' +
      '[data-as-enable],[data-as-delchar],[data-as-pos],' +
      '[data-as-charhit],[data-as-chargroup]');
    if (!t) return;
    event.preventDefault();
    if (t.dataset.asToggle) { setOpen(!open); return; }
    if (t.dataset.asOrigin !== undefined) {
      origin = t.dataset.asOrigin || '';
      fetchList();
      return;
    }
    if (t.dataset.asFavonly) {
      favoriteOnly = !favoriteOnly;
      fetchList();
      return;
    }
    if (t.dataset.asOpen !== undefined) {
      // 스택은 '지금 다루는 캐릭터'를 고르는 것이다 — 좌측을 열고 대상도 그리로 옮긴다.
      // 둘을 갈라 두면 대상 칸은 [1] 인데 조작 버튼은 C2 를 가리키는 상태가 된다.
      const i = Number(t.dataset.asOpen);
      if (ask) closeAsk();
      const panel = getPanel && getPanel();
      if (panel && typeof panel.openCharacterAt === 'function') panel.openCharacterAt(i);
      if (i < roster.length) { targetSlot = i; render(); }
      return;
    }
    if (t.dataset.asTarget !== undefined) {
      const i = Number(t.dataset.asTarget);
      // 팝업은 열릴 때의 슬롯을 들고 있다 — 대상이 바뀌면 화면과 어긋나므로 닫는다.
      if (ask) closeAsk();
      targetSlot = i;
      // 대상 칸도 같은 뜻이다 — 그 캐릭터를 좌측에서 열어 준다.
      const panel = getPanel && getPanel();
      if (panel && typeof panel.openCharacterAt === 'function') panel.openCharacterAt(i);
      render();   // [적용] 라벨과 조작 버튼이 대상 번호를 담는다
      return;
    }
    // 적용이 도는 중에는 슬롯 구성을 못 바꾼다(disabled 를 우회한 클릭 방어).
    if (busy && (t.dataset.asEnable || t.dataset.asDelchar || t.dataset.asPos
                 || t.dataset.asTarget !== undefined || t.dataset.asAddslot
                 || t.dataset.asCharhit !== undefined
                 || t.dataset.asChargroup !== undefined)) return;
    if (t.dataset.asChargroup !== undefined) {
      if (busy || charStale()) return;
      if (ask) closeAsk();
      charGroup = t.dataset.asChargroup || '';
      // 검색어는 그대로 두고 **작품과 AND 로 교차**한다(사용자 지정) — 작품을 좁힌 뒤
      // 그 안에서 다시 이름으로 찾는 것이 이어지는 동작이다. 입력창의 글자와 `✕ 작품`
      // 칩이 나란히 보이므로 두 조건이 함께 걸린 것이 화면에 드러난다.
      if (charTimer) clearTimeout(charTimer);
      void fetchChars();
      return;
    }
    if (t.dataset.asCharhit !== undefined) {
      if (charStale()) return;
      openAsk(t.dataset.asCharhit, t);
      return;
    }
    if (t.dataset.asPos) {
      const panel = getPanel && getPanel();
      if (panel && typeof panel.openPositionPickerFor === 'function') {
        panel.openPositionPickerFor(t, t.dataset.asPos);
      }
      return;
    }
    if (t.dataset.asEnable) { toggleOpenChar(); return; }
    if (t.dataset.asDelchar) { deleteOpenChar(); return; }
    if (t.dataset.asAddslot) { addSlot(); return; }
    if (t.dataset.asApply) { applyPicked(); return; }
    if (t.dataset.asFold) { setOpen(false); return; }
    if (t.dataset.asPreview) { openPreview(t.dataset.asPreview); return; }
    if (t.dataset.asPvclose) { closePreview(); return; }
    if (t.dataset.asPvapply !== undefined) { applyPreviewChar(Number(t.dataset.asPvapply)); return; }
    if (t.dataset.asPvrestore) { if (previewId) restore(previewId); return; }
    if (t.dataset.asPvdel) { if (previewId) remove(previewId); return; }
    if (t.dataset.asPvfav) {
      if (!previewId) return;
      const row = rows.find(x => x.id === previewId);
      toggleFavorite(previewId, row ? row.summary : '');
      return;
    }
    if (t.dataset.asPick) { pick(t.dataset.asPick, t.dataset.asCi, t.dataset.asLabel); return; }
    if (t.dataset.asDel) { remove(t.dataset.asDel); return; }
    if (t.dataset.asRestore) { restore(t.dataset.asRestore); return; }
    if (t.dataset.asFav) {
      const row = rows.find(x => x.id === t.dataset.asFav);
      toggleFavorite(t.dataset.asFav, row ? row.summary : '');
    }
  }

  /** 펼침/접힘을 한 곳에서 바꾼다 — 바깥 클릭·[접기]·토글 버튼이 모두 이걸 쓴다. */
  function setOpen(next) {
    if (open === next) return;
    open = next;
    if (!open) closePreview();     // 접으면 미리보기도 같이 닫는다
    render();
    if (open) fetchList();
  }

  /** 미리보기에서 캐릭터 하나를 대상 슬롯에 꽂는다. 본문은 이미 읽어 뒀다 —
   *  `applyPicked` 와 달리 다시 받아오지 않으므로 눌렀을 때 바로 들어간다. */
  function applyPreviewChar(index) {
    const chars = (previewBody && Array.isArray(previewBody.chars)) ? previewBody.chars : [];
    const row = chars[index];
    if (!row) { showToast('그 캐릭터가 없습니다.', 'error'); return; }
    // 대상은 **누른 시점의 슬롯 id** 로 잡는다 — 번호는 앞 슬롯이 지워지면 밀린다.
    const target = roster[targetSlot];
    if (!target) { showToast(`C${targetSlot + 1} 슬롯이 없습니다.`, 'error'); return; }
    const panel = getPanel && getPanel();
    if (!panel || typeof panel.applySnapshotCharById !== 'function') {
      showToast('Interactive 패널이 준비되지 않았습니다.', 'error');
      return;
    }
    if (!panel.applySnapshotCharById(target.id, row)) {
      showToast('슬롯에 꽂을 수 없습니다.', 'error');
      return;
    }
    showToast(`${target.label} <- ${charLabel(row)}`, 'success');
  }

  /** 바깥(주로 결과 이미지)을 누르면 접는다. 예전에는 Assets 버튼을 다시 찾아
   *  누르는 것 말고는 닫을 길이 없었다(사용자 지적). */
  function onOutside(event) {
    if (!open) return;
    if (root.contains(event.target)) return;
    if (previewEl && previewEl.contains(event.target)) return;   // body 직계라 따로 본다
    // 이 패널이 띄운 바깥 팝업들(좌표 픽커·캐릭터 확인)은 닫지 않는다.
    if (event.target.closest?.('.ia-pos-popup, .ia-as-ask')) return;
    setOpen(false);
  }

  function onInput(event) {
    const charInput = event.target.closest('[data-as-charq]');
    if (charInput) {
      charQuery = String(charInput.value || '');
      if (ask) closeAsk();   // 고른 줄이 곧 사라진다
      // 검색어가 바뀌는 순간 화면의 결과는 낡은 것이 된다. 디바운스가 끝나기 전에
      // 눌리면 화면과 다른 캐릭터가 슬롯에 들어가므로 바로 흐리게 잠근다.
      renderCharHits();
      if (charTimer) clearTimeout(charTimer);
      charTimer = setTimeout(fetchChars, 220);
      return;
    }
    const input = event.target.closest('[data-as-search]');
    if (!input) return;
    query = String(input.value || '').trim();
    if (searchTimer) clearTimeout(searchTimer);
    searchTimer = setTimeout(fetchList, 220);
  }

  root.addEventListener('click', onClick);
  root.addEventListener('input', onInput);
  // 바깥 클릭으로 접기. 캡처 단계로 잡아, 눌린 곳이 자기 핸들러에서 노드를 지워도
  // (그러면 root.contains 가 false 가 되어 엉뚱하게 접힌다) 판정이 먼저 끝나게 한다.
  document.addEventListener('mousedown', onOutside, true);
  // 패널이 뷰어 안에 붙어 있어 스크롤·리사이즈로 위치가 밀린다 — 미리보기를 따라 붙인다.
  window.addEventListener('resize', positionPreview);

  // ------------------------------------------------------------------ 공개

  return {
    /** Interactive 모드 on/off 를 그대로 따른다 — 이 패널은 그 모드의 도구다. */
    setVisible(on) {
      const next = !!on;
      if (next === visible) return;
      visible = next;
      if (!visible) { open = false; closeAsk(); closePreview(); }
      render();
    },
    /** 패널이 캐릭터 목록 변화를 알려 준다. 스택과 대상 칸이 이걸로 그려진다. */
    setRoster(next) {
      roster = Array.isArray(next) ? next : [];
      // 좌측 아코디언에서 캐릭터를 열어도 '지금 다루는 캐릭터'가 바뀐 것이다 —
      // 대상을 그리로 옮긴다. 이쪽을 빼면 스택은 C2 를 가리키는데 조작·적용은
      // C1 에 걸리는 상태가 된다(방향이 한쪽뿐이었다).
      const opened = roster.findIndex(c => c.open);
      if (opened >= 0) targetSlot = opened;
      // 대상은 **있는 슬롯**만이다. 그 다음 자리는 [+] 버튼이 차지하므로 겨눌 수 없다.
      // 캐릭터가 줄면 마지막 슬롯으로 당긴다 — 안 그러면 [+] 자리를 겨눈 채 적용해
      // 누르지도 않은 슬롯이 생긴다.
      if (targetSlot >= roster.length) targetSlot = Math.max(0, roster.length - 1);
      if (visible) render();
    },
    record,
    /** 생성이 끝난 뒤 썸네일이 붙었을 수 있다 — 열려 있을 때만 다시 읽는다. */
    refresh() { if (visible && open) fetchList(); },
    destroy() {
      root.removeEventListener('click', onClick);
      root.removeEventListener('input', onInput);
      if (searchTimer) clearTimeout(searchTimer);
      if (charTimer) clearTimeout(charTimer);
      if (charObserver) { charObserver.disconnect(); charObserver = null; }
      closeAsk();
      if (askEl) { askEl.remove(); askEl = null; }
      root.innerHTML = '';
      root.hidden = true;
    },
  };
}
