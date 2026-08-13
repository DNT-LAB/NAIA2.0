## Findings

1. **BLOCK — V1 falsification evidence is not reproducible.**  
   `tools/reco_probe/SPEC.md:391-422`, `tools/reco_probe/probe_bundle_hit.py:229-268`  
   The two named scripts, `probe_bundle_hit2.py` and `probe_char_disjoint.py`, do not exist in `HEAD`, any tracked path, or repository history. The only committed bundle probe measures the uncorrected metric. Re-running it produced:

   - head: `0.814`
   - independent: `0.269`
   - raw-count: `0.917`
   - proposal: `0.199`
   - proposal delta: `-0.7188`, CI `[-0.7500, -0.6850]`

   These reproduce the SPEC’s original failed experiment, not `Hit_i@5`, the `0.000` trivial baselines, or the character-disjoint result. A clean reviewer cannot reproduce either claimed gate.

2. **BLOCK — V2 shipped query does not implement the measured probe.**  
   `core/tag_combo/query.py:49-51`, `core/tag_combo/query.py:220-241`, `core/tag_combo/query.py:244-268`, `tools/reco_probe/probe_bundle_hit.py:153-187`  
   Maximum-information backoff itself matched on all 120 measured cases. The remaining algorithm does not:
   - production relaxes gates to `(1.5, 0.50)` and `(1.2, 0.80)`;
   - production applies character filtering;
   - production backs bundle size down to 2;
   - production applies head-word deduplication and different final scoring/order.

   On 120 deterministic real-model prompts, only **24/120** result sets matched the strict probe algorithm; production returned results for **15** cases where the probe returned empty. For `1girl_1boy/hetero`, production returned five weak tuples while the probe returned none. The claimed V1 figures therefore do not describe the shipped path.

3. **BLOCK — V3 head cache is not zero-loss or byte-identical.**  
   `tools/build_tag_combo_head_cache.py:41-43`, `tools/build_tag_combo_head_cache.py:57-69`, `core/tag_combo/query.py:175-187`, `core/tag_combo/query.py:257-268`  
   The builder mines with `top_k=20`, score-sorts that larger pool, and stores it. An uncached normal query stops after five support-ranked candidates before score-sorting. I found mismatches in **15 of the first 41 cached tags checked**. Example: `multiple_boys/open clothes` returns a `batman symbol + bat signal + taut bodysuit` tuple from cache, while the uncached result instead contains `jacket + white shirt + open jacket`.

   Recursion prevention itself works: `_head` is emptied before mining, so the builder does not read its own cache.

4. **BLOCK — V4 the LRU permits the exact two-large-model overlap it claims to prevent.**  
   `core/tag_combo/service.py:40-61`, `core/tag_combo/model.py:154-160`  
   Sequential measurement with the default 400 MiB budget:

   - `1girl_solo`: reported `160,548,886` bytes
   - after loading `2girls`: both remained resident, reported total `324,857,120` bytes
   - process working set peaked at **544,387,072 bytes**

   The pre-eviction condition is `resident > budget * 0.6`; one 161 MB model does not cross that 240 MiB threshold, so the second is materialized alongside it. `_resident_bytes()` also undercounts: it omits `post_char`, understating these two models by **6,074,200 bytes**, before Python metadata/cache overhead. Concurrent in-flight queries can retain evicted models as well.

5. **BLOCK — V6 person routing disagrees on inputs accepted by the preset bridge.**  
   `core/tag_combo/person.py:32-63`, `core/preset_input_bridge.py:291-303`, `core/tag_combo/service.py:65-68`  
   The canonical eight-tag powerset passed: 256 subsets, 254 non-empty bridge results, zero disagreements. But the bridge lowercases and converts underscores to spaces while `person_group_of()` does neither:
   - underscore powerset: **200/254 disagreements**
   - uppercase powerset: **254/254 disagreements**

   Concrete example: `1girl,multiple_boys` routes presets to `1girl_multiple_boys` but combos to `1girl`. These are normal Danbooru-style/API inputs and select different models.

6. **BLOCK — V8 the feature has no clean-checkout data path.**  
   `app/backend/server/tag_combo_routes.py:27-35`, `core/tag_combo/service.py:49-74`  
   `git ls-files data/tag_combo` and `git ls-files data/tags` both return nothing. No release/runtime-download reference to `tag_combo` exists. On a clean checkout the route points at an empty directory and every recommendation returns `model not built`; the source data needed to run the builder is absent too.

7. **CONCERN — V8 backoff is exponential up to the route’s 24-tag limit.**  
   `app/backend/server/tag_combo_routes.py:22-45`, `core/tag_combo/query.py:119-131`  
   `sorted(combinations(...))` enumerates every subset when intersections remain below the floor. Synthetic disjoint-tag measurements:

   - 16 tags: 0.961 s
   - 18 tags: 3.404 s
   - 20 tags: 15.244 s

   The accepted 24-tag case has 16,777,215 subsets and can occupy a worker for minutes while materializing large combination lists.

8. **CONCERN — V8 `_char_share` has uncapped candidate×character state.**  
   `core/tag_combo/query.py:142-168`, `core/tag_combo/query.py:220-221`  
   A real `hetero` query processed 391,524 matched posts and 964 candidates. It added **60.0 MB RSS**; Python allocation peak was 36.4 MB. Normal execution took about 4.3 s. There is no cap on candidate counters or distinct character IDs, so concurrent broad queries can multiply this overhead.

9. **CONCERN — V8 key tests are missing or vacuous.**  
   `tests/test_tag_combo.py:110-149`, `tests/test_tag_combo.py:235-266`  
   There are no tests for probe parity, cache equivalence, LRU byte accounting, clean-data availability, or exhaustive bridge parity. The character-concentration test returned **zero combos** before its assertion loop, so it passes without exercising the character filter. Pytest reached 15 passes; the remaining 12 tests were blocked at setup by the environment’s `tmp_path` ACL, not by code failures.

10. **CONCERN — Route failures are converted to unlogged HTTP 200 responses.**  
    `app/backend/server/tag_combo_routes.py:49-66`  
    Model corruption or sidecar parsing failures become `{"error":"ExceptionType"}` with no logging, traceback, detail, or non-2xx status. Operationally, the server records no evidence explaining why recommendations disappeared.

## V1–V8 status

- **V1: NOT REPLICATED — BLOCK.** Required probe sources are absent.
- **V2: NOT REPLICATED — BLOCK.** Backoff matched, but only 24/120 full results matched.
- **V3: NOT REPLICATED — BLOCK.** 15/41 sampled cached tags differed.
- **V4: NOT REPLICATED — BLOCK.** Two ~161 MB models coexisted; peak RSS 544.4 MB.
- **V5: REPLICATED.** All 13 files had exact expected section sizes, including `post_char`; vocab bounds held. Across **131,034 tag postings**, there were zero ordering violations, duplicates, or frequency mismatches.
- **V6: PARTIAL/FAIL — BLOCK.** Canonical powerset passed; normalized inputs supported by the bridge did not.
- **V7: REPLICATED, informational.** Using the repository’s 723-tag adult vocabulary:
  - inferred `other`: **0/4 tuples**, **0/11 candidate tags**
  - forced `1girl_solo`: **0/12 tuples**, **0/36 candidate tags**
  
  No adult candidate appeared for `school uniform,classroom`, `beach,smile`, or `kimono,festival`.
- **V8: FAIL.** `scan_cap=0` is complete—no production override was found—but clean-data availability, exponential backoff, `_char_share` memory, test coverage, and silent route failures remain.

## Overall verdict: **BLOCK**

Repository files were not modified.

