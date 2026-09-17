/** 아티스트 그룹 — 화면 쪽 **단일 소유자**.
 *
 *  그룹 창·우클릭 메뉴·믹스 큐가 모두 이 한 곳에서 읽고, 바꾸면 구독자 전부가 다시
 *  그린다. ⚠️ 창마다 목록을 따로 들고 있으면 "메뉴로 등록했는데 열린 창은 그대로" 가
 *  첫 제보가 된다(상태가 두 곳이면 갈린다 - 이 저장소에서 여러 번 밟았다).
 *
 *  두 종류:
 *    - 저장 그룹  id `g_…` — 서버(`/api/artist-groups`, `artist_groups.json`)
 *    - 임시 그룹  id `t_…` — 이번 실행만(sessionStorage). 새로고침엔 살고 앱을 다시
 *      켜면 사라진다(창 크기와 같은 수명). [이름 붙여 저장] 으로 저장 그룹이 된다.
 *
 *  ⚠️ 정리 규칙(대소문자 무시 중복 제거·`artist:` 떼기·공백 접기)은 **백엔드
 *     `core/artist_groups.py` 와 같아야 한다**. 임시 그룹은 서버를 안 거치므로 여기서
 *     같은 규칙을 지키지 않으면 임시 창과 저장 창의 동작이 갈린다.
 */

const TEMP_KEY = 'naia.artistgroups.temp';
const API = '/api/artist-groups';

export function cleanArtistName(value) {
  let name = String(value ?? '').split(/\s+/).filter(Boolean).join(' ');
  if (name.toLowerCase().startsWith('artist:')) name = name.slice(7).trim();
  return name.length > 200 ? '' : name;
}

function cleanItem(raw) {
  const src = typeof raw === 'string' ? {artist: raw} : (raw || {});
  const artist = cleanArtistName(src.artist);
  if (!artist) return null;
  const item = {artist};
  const w = Number.parseFloat(src.weight);
  if (Number.isFinite(w) && w !== 1) item.weight = Math.round(Math.max(-5, Math.min(5, w)) * 100) / 100;
  return item;
}

/** 이미 있는 작가는 **자리를 지키고** 건너뛴다(백엔드 `add` 와 같은 규칙). */
function mergeItems(existing, incoming) {
  const have = new Set(existing.map(i => i.artist.toLocaleLowerCase()));
  const fresh = [];
  for (const raw of incoming) {
    const item = cleanItem(raw);
    if (!item) continue;
    const key = item.artist.toLocaleLowerCase();
    if (have.has(key)) continue;
    have.add(key);
    fresh.push(item);
  }
  return {items: existing.concat(fresh), added: fresh.length, skipped: incoming.length - fresh.length};
}

export function createArtistGroupsStore({
  fetch: fetchImpl = (typeof fetch !== 'undefined' ? fetch.bind(globalThis) : null),
  storage = (typeof sessionStorage !== 'undefined' ? sessionStorage : null),
} = {}) {
  let saved = [];
  let temps = readTemps();
  let loaded = false;
  const subs = new Set();

  function readTemps() {
    try {
      const parsed = JSON.parse(storage?.getItem(TEMP_KEY) || '[]');
      return Array.isArray(parsed) ? parsed.filter(g => g && String(g.id || '').startsWith('t_')) : [];
    } catch { return []; }
  }

  function writeTemps() {
    try { storage?.setItem(TEMP_KEY, JSON.stringify(temps)); } catch { /* 저장 못 해도 이번 화면은 산다 */ }
  }

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

  function adoptSaved(data) {
    if (Array.isArray(data?.groups)) saved = data.groups;
  }

  const isTemp = id => String(id || '').startsWith('t_');
  const all = () => [...saved, ...temps];
  const get = id => all().find(g => g.id === id) || null;

  async function load() {
    adoptSaved(await call('GET'));
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
    adoptSaved(data);
    notify('create');
    return data.group;
  }

  function createTemp(items = []) {
    const group = {
      id: `t_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`,
      name: '',
      temp: true,
      items: mergeItems([], items).items,
    };
    temps = [...temps, group];
    writeTemps();
    notify('create-temp');
    return group;
  }

  /** 들어간 수·건너뛴 수를 돌려준다 - "이미 있습니다" 를 알릴 근거다. */
  async function add(id, items) {
    const list = Array.isArray(items) ? items : [items];
    if (isTemp(id)) {
      const group = temps.find(g => g.id === id);
      if (!group) throw new Error('임시 창을 찾지 못했습니다');
      const merged = mergeItems(group.items || [], list);
      group.items = merged.items;
      writeTemps();
      notify('add');
      return {group, added: merged.added, skipped: merged.skipped};
    }
    const data = await call('POST', {op: 'add', id, items: list});
    adoptSaved(data);
    notify('add');
    return {group: data.group, added: data.added || 0, skipped: data.skipped || 0};
  }

  async function remove(id, artists) {
    const names = (Array.isArray(artists) ? artists : [artists]).map(cleanArtistName).filter(Boolean);
    if (isTemp(id)) {
      const group = temps.find(g => g.id === id);
      if (!group) return null;
      const drop = new Set(names.map(n => n.toLocaleLowerCase()));
      group.items = group.items.filter(i => !drop.has(i.artist.toLocaleLowerCase()));
      writeTemps();
      notify('remove');
      return group;
    }
    const data = await call('POST', {op: 'remove', id, artists: names});
    adoptSaved(data);
    notify('remove');
    return data.group;
  }

  async function reorder(id, artists) {
    if (isTemp(id)) {
      const group = temps.find(g => g.id === id);
      if (!group) return null;
      const byKey = new Map(group.items.map(i => [i.artist.toLocaleLowerCase(), i]));
      const head = [];
      for (const name of artists) {
        const key = cleanArtistName(name).toLocaleLowerCase();
        if (byKey.has(key)) { head.push(byKey.get(key)); byKey.delete(key); }
      }
      group.items = head.concat(group.items.filter(i => byKey.has(i.artist.toLocaleLowerCase())));
      writeTemps();
      notify('reorder');
      return group;
    }
    const data = await call('POST', {op: 'reorder', id, artists});
    adoptSaved(data);
    notify('reorder');
    return data.group;
  }

  async function rename(id, name) {
    const data = await call('POST', {op: 'rename', id, name});
    adoptSaved(data);
    notify('rename');
    return data.group;
  }

  async function destroy(id) {
    if (isTemp(id)) {
      temps = temps.filter(g => g.id !== id);
      writeTemps();
      notify('delete');
      return;
    }
    adoptSaved(await call('POST', {op: 'delete', id}));
    notify('delete');
  }

  /** 임시 그룹에 이름을 붙여 **저장 그룹으로 승격**. 성공한 뒤에만 임시본을 지운다. */
  async function promote(id, name) {
    const temp = temps.find(g => g.id === id);
    if (!temp) throw new Error('임시 창을 찾지 못했습니다');
    const group = await create(name, temp.items);
    temps = temps.filter(g => g.id !== id);
    writeTemps();
    notify('promote');
    return group;
  }

  function subscribe(fn) {
    subs.add(fn);
    return () => subs.delete(fn);
  }

  return {
    load, ensureLoaded, all, get, isTemp,
    create, createTemp, add, remove, reorder, rename, destroy, promote,
    subscribe,
  };
}
