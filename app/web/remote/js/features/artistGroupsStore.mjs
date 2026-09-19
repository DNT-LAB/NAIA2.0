/** 아티스트 그룹 — 화면 쪽 **단일 소유자**.
 *
 *  그룹 창·우클릭 메뉴·믹스 큐가 모두 이 한 곳에서 읽고, 바꾸면 구독자 전부가 다시
 *  그린다. ⚠️ 창마다 목록을 따로 들고 있으면 "메뉴로 등록했는데 열린 창은 그대로" 가
 *  첫 제보가 된다(상태가 두 곳이면 갈린다 - 이 저장소에서 여러 번 밟았다).
 *
 *  그룹은 **한 종류**다(사용자 결정 2026-09-19). 전부 서버(`/api/artist-groups`,
 *  `artist_groups.json`)에 살고, '임시 창' 은 아직 **이름을 안 붙인** 그룹일 뿐이다
 *  (`temp: true`, 이름은 서버가 `임시 창 N` 으로 붙여 둔다). 헤더의 ✎ 로 이름을
 *  고치면 그 표가 떨어지고 평범한 그룹이 된다.
 *
 *  ⚠️ 전에는 임시 그룹만 sessionStorage 에 따로 살아서 이 파일의 거의 모든 함수가
 *     `if (isTemp(id))` 로 갈라졌다 - '임시 창에서만 안 되는 것' 이라는 부류의 결함
 *     자리였다. 갈랫길은 다시 만들지 말 것.
 *
 *  ⚠️ 정리 규칙(대소문자 무시 중복 제거·`artist:` 떼기·공백 접기)은 **백엔드
 *     `core/artist_groups.py` 와 같아야 한다** - 화면이 먼저 거르고 서버가 다시 거른다.
 */

const API = '/api/artist-groups';

export function cleanArtistName(value) {
  let name = String(value ?? '').split(/\s+/).filter(Boolean).join(' ');
  if (name.toLowerCase().startsWith('artist:')) name = name.slice(7).trim();
  return name.length > 200 ? '' : name;
}

export function createArtistGroupsStore({
  fetch: fetchImpl = (typeof fetch !== 'undefined' ? fetch.bind(globalThis) : null),
} = {}) {
  let groups = [];
  let loaded = false;
  const subs = new Set();

  function notify(reason) {
    const snap = all();
    for (const fn of [...subs]) {
      try { fn(snap, reason); } catch (error) { console.error('artist groups subscriber failed', error); }
    }
  }

  async function call(method, body) {
    if (!fetchImpl) throw new Error('fetch 가 없습니다');
    const res = await fetchImpl(API, {
      method,
      headers: body ? {'Content-Type': 'application/json'} : undefined,
      body: body ? JSON.stringify(body) : undefined,
      cache: 'no-store',
    });
    let data = null;
    try { data = await res.json(); } catch { /* 본문 없는 오류 */ }
    if (!res.ok) throw new Error(data?.error || `HTTP ${res.status}`);
    return data || {};
  }

  function adopt(data) {
    if (Array.isArray(data?.groups)) groups = data.groups;
  }

  const all = () => groups;
  const get = id => groups.find(g => g.id === id) || null;
  /** ⚠️ **레코드**를 보고 판단한다. 아이디 앞머리로 재던 때가 있었는데, 이름을 붙여
   *  저장해도 아이디는 그대로라 그 방식으로는 승격을 알아볼 수가 없다. */
  const isTemp = id => !!get(id)?.temp;

  async function load() {
    adopt(await call('GET'));
    loaded = true;
    notify('load');
    return all();
  }

  async function ensureLoaded() {
    if (!loaded) await load();
    return all();
  }

  async function create(name, items = []) {
    const data = await call('POST', {op: 'create', name, items});
    adopt(data);
    notify('create');
    return data.group;
  }

  /** 이름 없는 그룹(임시 창). **이름은 서버가 붙인다**(`임시 창 N`) - 화면에서 지으면
   *  두 창이 같은 이름을 갖는 경합이 생기고, 이름이 비면 옛 판이 레코드를 버린다. */
  async function createTemp(items = []) {
    const data = await call('POST', {op: 'create', temp: true, items});
    adopt(data);
    notify('create');
    return data.group;
  }

  /** 들어간 수·건너뛴 수를 돌려준다 - "이미 있습니다" 를 알릴 근거다. */
  async function add(id, items) {
    const list = Array.isArray(items) ? items : [items];
    const data = await call('POST', {op: 'add', id, items: list});
    adopt(data);
    notify('add');
    return {group: data.group, added: data.added || 0, skipped: data.skipped || 0};
  }

  async function remove(id, artists) {
    const names = (Array.isArray(artists) ? artists : [artists]).map(cleanArtistName).filter(Boolean);
    const data = await call('POST', {op: 'remove', id, artists: names});
    adopt(data);
    notify('remove');
    return data.group;
  }

  async function reorder(id, artists) {
    const data = await call('POST', {op: 'reorder', id, artists});
    adopt(data);
    notify('reorder');
    return data.group;
  }

  /** 이름을 붙이는 것이 곧 **저장**이다 - 서버가 `temp` 표를 떼므로 임시 창 목록에서
   *  빠지고 아이디는 그대로 남는다(창을 다시 띄울 필요가 없다). */
  async function rename(id, name) {
    const data = await call('POST', {op: 'rename', id, name});
    adopt(data);
    notify('rename');
    return data.group;
  }

  async function destroy(id) {
    adopt(await call('POST', {op: 'delete', id}));
    notify('delete');
  }

  function subscribe(fn) {
    subs.add(fn);
    return () => subs.delete(fn);
  }

  return {
    load, ensureLoaded, all, get, isTemp,
    create, createTemp, add, remove, reorder, rename, destroy,
    subscribe,
  };
}
