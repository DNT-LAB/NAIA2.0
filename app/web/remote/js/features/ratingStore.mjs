// Single source of truth for the two DISTINCT rating concepts the Search
// subsystem juggles. They are not the same user intent, so the store keeps them
// as separate fields managed together rather than collapsing them:
//
//   active — the generation-pool / live-filter ratings (toolbar + Tag Filter
//            G/S/Q/E, sent via `set_active_ratings`). Drives which rows are
//            eligible to pop during generation and the live result filter.
//   search — the search-EXECUTION ratings (the `sr_*` checkboxes, sent as the
//            `search` command's `rating_g/s/q/e`). Decides which rows a keyword
//            search returns; used only inside run_search_command on the backend.
//
// Both Search panel and the Quick/Tag Filter consume this one store instead of
// reaching into each other's state by reference.
export const RATING_KEYS = ['g', 's', 'q', 'e'];

export function createRatingStore({
  active = { g: true, s: true, q: true, e: false },
  search = { g: true, s: true, q: true, e: false },
} = {}) {
  const activeState = { g: !!active.g, s: !!active.s, q: !!active.q, e: !!active.e };
  const searchState = { g: !!search.g, s: !!search.s, q: !!search.q, e: !!search.e };
  const listeners = new Set();
  const emit = () => {
    listeners.forEach(fn => {
      try { fn(); } catch (_) { /* listener errors must not break a rating change */ }
    });
  };

  return {
    RATING_KEYS,
    // Live objects — aliased by call sites that read/write ratingState[k] in place.
    active: activeState,
    search: searchState,

    // active (generation pool) ----------------------------------------------
    getActiveList: () => RATING_KEYS.filter(key => activeState[key]),
    isActive: key => !!activeState[key],
    toggleActive: key => { activeState[key] = !activeState[key]; emit(); },
    setActiveFromList: list => {
      if (!Array.isArray(list)) return;
      for (const key of RATING_KEYS) activeState[key] = list.includes(key);
      emit();
    },

    // search (search execution) ---------------------------------------------
    getSearchList: () => RATING_KEYS.filter(key => searchState[key]),
    setSearch: (key, value) => { searchState[key] = !!value; emit(); },
    setSearchFromMap: map => {
      if (!map || typeof map !== 'object') return;
      for (const key of RATING_KEYS) if (key in map) searchState[key] = !!map[key];
      emit();
    },

    subscribe: fn => { listeners.add(fn); return () => listeners.delete(fn); },
  };
}
