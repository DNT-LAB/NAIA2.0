/** 그룹 보기(벤치) — 화면 쪽 **단일 소유자**.
 *
 *  보기 = 작가 썸네일을 뽑는 벤치 조건 한 벌(글 · 캐릭터 · 해상도 · 생성 설정 · 시드). **공용**이라
 *  어느 그룹에서든 고르고, 그룹은 마지막으로 고른 보기만 기억한다(사용자 결정 2026-09-26).
 *  서버(`/api/artist-bench-views`, `artist_bench_views.json`)가 원본이고 이 저장소는 그 사본 하나를
 *  들고 구독자(그룹 창들 · 보기 설정 창)에게 알린다 - 창마다 따로 들면 갈린다.
 */

const API = '/api/artist-bench-views';

export function createArtistBenchViewsStore({
  fetch: fetchImpl = (typeof fetch !== 'undefined' ? fetch.bind(globalThis) : null),
} = {}) {
  let data = {views: [], group_views: {}, current: null, options: {model: [], sampler: [], scheduler: []}};
  let loaded = false;
  const subs = new Set();

  function notify(reason) {
    for (const fn of [...subs]) {
      try { fn(data, reason); } catch (error) { console.error('bench views subscriber failed', error); }
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
    let payload = null;
    try { payload = await res.json(); } catch { /* 본문 없는 오류 */ }
    if (!res.ok) throw new Error(payload?.error || `HTTP ${res.status}`);
    return payload || {};
  }

  /** 서버 답의 views/group_views 만 갈아 끼운다. current/options 는 GET 만 준다. */
  function adopt(payload) {
    if (Array.isArray(payload?.views)) data = {...data, views: payload.views};
    if (payload?.group_views && typeof payload.group_views === 'object') data = {...data, group_views: payload.group_views};
    if (payload?.current) data = {...data, current: payload.current};
    if (payload?.options) data = {...data, options: payload.options};
  }

  async function load() {
    adopt(await call('GET'));
    loaded = true;
    notify('load');
    return data;
  }

  async function ensureLoaded() {
    if (!loaded) await load();
    return data;
  }

  const views = () => data.views;
  const get = id => data.views.find(v => v.id === id) || null;
  /** 그룹이 고른 보기. 없거나 지워졌으면 '' = 기본 썸네일. */
  const viewOf = groupId => {
    const id = data.group_views?.[groupId] || '';
    return id && get(id) ? id : '';
  };

  async function mutate(body, reason) {
    const payload = await call('POST', body);
    adopt(payload);
    notify(reason);
    return payload;
  }

  /** spec 을 안 주면 서버가 **지금 설정**을 뜬다(PE 글 · 캐릭터 · 해상도 · 설정). */
  const create = (name, spec) => mutate(spec ? {op: 'create', name, spec} : {op: 'create', name}, 'create').then(p => p.view);
  const update = (id, spec) => mutate({op: 'update', id, spec}, 'update').then(p => p.view);
  const rename = (id, name) => mutate({op: 'rename', id, name}, 'rename').then(p => p.view);
  const remove = id => mutate({op: 'delete', id}, 'delete');
  const select = (groupId, id) => mutate({op: 'select', group: groupId, id: id || ''}, 'select');

  /** '지금 설정' 을 새로 받는다(갱신 단추 앞에서 - 메인 화면을 고친 뒤일 수 있다). */
  async function refreshCurrent() {
    adopt(await call('GET'));
    return data.current;
  }

  function subscribe(fn) {
    subs.add(fn);
    return () => subs.delete(fn);
  }

  return {
    load, ensureLoaded, views, get, viewOf, create, update, rename, remove, select, refreshCurrent,
    current: () => data.current, options: () => data.options, subscribe,
  };
}
