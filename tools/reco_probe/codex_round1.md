# Verdict

**Mine—but do not mine closed itemsets, and do not mine whole projected post sets.**

The right architecture is a **bounded, role-templated bundle index with context-subset backoff**. It should mine 2–4-tag core bundles offline, store conditional evidence for one- and two-tag contexts, and attach auxiliary tags separately.

Query-time extraction from matched posts is acceptable for diagnostics or a tail fallback, but not as the primary runtime: common prompts make pair extraction too slow, while exact whole-set extraction is fast only because almost every result is a support-1 fragment.

## Measurement scope

I inspected the specified old/current code and assets. My parquet benchmark used seven time-stratified shards:

- Shards: 0, 25, 50, 75, 100, 125, 149
- Dates represented: January 2016 through September 2025
- Posts read: **363,782**, or **4.82%** of the 7,543,144-post archive
- `1girl_solo`: **188,150**
- Extrapolations below use `864,892 / 188,150 = 4.597` for the requested `s_1girl_solo` scale.

All extrapolations are labelled. Full-build duration and final mined-bundle cardinality remain **unmeasured**.

---

# 1. What is wrong with the straw-man

## 1.1 Closed itemsets are the wrong object

A projected post is not a coherent recommendation bundle. It is a union of:

- action,
- pose,
- expression,
- clothing layers,
- accessories,
- location,
- framing,
- sexual state,
- incidental depiction tags.

Using the straw-man’s approximate MAIN groups—`Expression_Action`, `Clothing_Wear`, `Location_Background`, and `NSFW`—gave:

- vocabulary: **8,568**
- observed in the seven-shard sample: **7,551**
- mean MAIN tags/post: **14.76**
- median: **14**
- p90: **24**
- p99: **36**

That is far too large to regard the whole set as one “combo.” Closed mining will mostly encode arbitrary post fingerprints, while bounded subsets will explode combinatorially.

The existing Event Preset archive already demonstrates the fragmentation even after restricting identity to event tags:

- `s_1girl_solo` combo rows: **64,325**
- support 1: **29,525 / 64,325 = 45.9%**
- support ≤2: **63.3%**
- median support: **2**
- median combo size: **4**

Closedness removes redundant subsets; it does not make the surviving sets semantically coherent.

## 1.2 The proposed roles do not correspond to the actual axis registry

`core/tag_axis_registry.py:13-30` defines:

- PRIMARY: expression, pose/action, location, **meta, object, clothing, characteristic, sexual/NSFW**
- AUXILIARY: **person_count, person_focus**

So `PRIMARY_AXES` does not mean “main recommendation identity,” and `AUXILIARY_AXES` does not mean colors/hair/body/meta. The straw-man is assigning semantics the registry does not have.

Likewise, `interactive_tags.json` is a useful taxonomy, but its nine broad groups are not bundle roles. For example, `Clothing_Wear` mixes garments, states, accessories, and decorations. A hair ornament can be:

- core in an accessory set,
- auxiliary to a pose,
- a required component of a character design.

A global tag→MAIN/AUX assignment cannot represent this.

## 1.3 Event Preset’s 0.9 rule is not a competing global taxonomy

The archive contains a per-event attachment promotion rule, not a universal definition of mainness. In the actual `s_1girl_solo` partition:

- expression promoted for **178 / 2,811 events = 6.33%**
- clothing promoted for **438 / 2,811 = 15.58%**

That rule answers “is this attachment almost inseparable from this event?” It does not answer “is clothing globally MAIN?”

The correct conclusion is not “choose roles or 0.9.” Use:

- **role templates** to define what kind of bundle is being constructed;
- **empirical stability/confidence** to decide whether a tag is core or attached within that bundle.

## 1.4 Applying the existing noise stack wholesale violates the product constraint

This is the most serious defect.

The current builder:

- removes candidates matching `danger_age_hits` at `tools/build_tag_cooccurrence.py:579-580`;
- excludes adult vocabulary from non-adult anchors at `592-594`;
- has `nude`, `completely nude`, and `spread legs` in `STOP`;
- hard-removes statistically “exclusive” pairs at `585-586`.

Those policies belong to another surface. They cannot be inherited into this recommender.

In particular, `tag_exclusive_pairs.json` means lift ≤0.35 with frequency/support gates. It is statistical negative association, **not logical impossibility**. Hard-rejecting such pairs would suppress unusual and taboo combinations precisely when the prompt requests them.

Reuse only the noise mechanisms that remove corpus artifacts:

- confidence/lift/support scoring,
- character concentration,
- era instability,
- artist/character/meta leakage,
- duplicate/re-upload removal,
- implication typing,
- same-family redundancy.

Do **not** reuse content gating, age gating, or statistical exclusivity as censorship. Literal negation such as `no X` versus `X` can remain a semantic conflict.

## 1.5 Strict supersets remain brittle

The old implementation explicitly returns zero for an unknown required tag (`Dev0714:ui/interactive/quick_search_data.py:80-92`) and intersects Python sets for every requirement (`97-106`). The UI then counts and ranks individual tags by raw frequency (`quick_search_block.py:886-909`).

Replacing its vocabulary without changing retrieval semantics only postpones the failure. Exact supersets become tiny for ordinary 3–4-tag prompts, and one out-of-vocabulary tag still destroys the query.

## 1.6 “One pass” is an unjustified constraint

Reliable lift, rating shrinkage, character concentration, era stability, and bounded bundle extension naturally want at least:

1. a marginal/deduplication pass;
2. a candidate-counting pass.

A forced single-pass algorithm either retains far too many candidates or uses approximate sketches. Full build time is currently **unmeasured**, so there is no evidence that a second sequential parquet scan is the bottleneck.

## 1.7 “Next-post prediction” is the wrong evaluation story

These are not user sessions or temporal state transitions. There is no meaningful “next post” for a prompt.

The implementable task is **held-out prompt completion**: reveal some tags from a held-out post and evaluate whether recommended bundles are contained in the withheld portion.

Also, an unconditional head baseline will not score approximately zero on ordinary hit rate. I measured that it scores surprisingly high; see Q6.

## 1.8 The person classifier needs one explicit decision

The priority chain in `core/preset_input_bridge.py:298-322` returns `""` when no known person signature matches, whereas `PERSON_PARTITION_ORDER` contains `other`.

The builder must explicitly map the empty result to `other`; merely saying “use the predicate” leaves a fourteenth accidental bucket.

---

# 2. Counter-proposal

## 2.1 Model: Contextual Bundle Index

Build one model per person group, with all ratings retained inside it.

### Core bundle types

Mine bounded bundles of **2–4 core tags**, using typed templates rather than arbitrary itemsets. Examples:

- **action bundle:** pose/action + related action/expression;
- **outfit bundle:** compatible Region6 garment components;
- **accessory bundle:** garment or style anchor + accessories;
- **scene bundle:** location/background + scene object/effect;
- **sexual/event bundle:** action/state/accessory combinations, with no content exclusion.

For multi-person groups, records also need an `actor_scope`:

- character 1,
- character 2,
- shared/common,
- unknown.

The raw `general` column cannot reliably infer actor ownership, so `unknown/shared` must be allowed rather than pretending pooled actions belong to a particular character.

### Mining algorithm

Use bounded Apriori-style extension:

1. Count cleaned tag marginals, rating histograms, era buckets, and character concentration.
2. Count valid typed pairs.
3. Extend only retained pairs into valid triples and, where justified, quadruples.
4. Never enumerate arbitrary 14–36-tag post subsets.
5. Keep context-conditioned candidates for:
   - every retained single-tag context;
   - sufficiently supported two-tag contexts;
   - selected exact triples only where they add held-out gain.

This is still mining, but its cardinality is bounded by product semantics and depth.

### Core versus attachment

Store two outputs per recommendation:

```text
CORE:
    bundle tags, role signature, actor scope

ATTACHMENTS:
    expression, color, body/characteristic, dependency, accessory, meta/style
```

A tag is not permanently MAIN or AUX. Its role is relative to a bundle.

Promotion should use several empirical signals:

- conditional confidence,
- lift/information gain,
- stability across time/rating/character folds,
- whether removing it degrades held-out bundle prediction,
- dependency status.

The existing 0.9 value can be a feature or high-precision seed, not the final universal threshold.

## 2.2 Retrieval: evidence backoff, not document similarity

Given normalized prompt tags \(Q\):

1. Keep all known prompt tags as retrieval evidence; do not project AUX away.
2. Retrieve candidates for the most specific stored context subsets:
   - exact 2–3-tag context first;
   - all query pairs next;
   - then individual tags.
3. Unknown tags contribute no retrieval evidence, but **do not zero the query**.
4. Combine evidence for the same bundle.
5. Reject literal prompt contradictions and duplicate/same-family clutter.
6. Return core bundle plus typed attachments.

For context subset \(S\) and bundle \(B\), use a shrunk conditional estimate:

\[
\hat P(B\mid S)=
\frac{n(S,B)+\alpha P(B)}
     {n(S)+\alpha}
\]

Then rank approximately by:

\[
\text{coverage}(S,Q)
\times \hat P(B\mid S)
\times \min(\log_2 \text{lift}(S,B),3)
\times \text{stability}
\times \text{rating affinity}
\]

minus redundancy and genuine semantic-conflict penalties.

`α` and the mixing weights are **unmeasured** and should be fitted on validation data.

This is different from generic weighted soft matching. It backs off among observed, interpretable context subsets rather than finding vaguely similar posts.

## 2.3 Noise policy

### Retain

- support and candidate-frequency floors;
- confidence × capped log-lift ranking;
- `P(B)` background cap;
- implication detection, but type the tag as a dependency rather than silently losing it;
- same-family de-duplication;
- era stability;
- character concentration;
- exact/near-duplicate post suppression;
- artist/character/copyright/meta-output exclusion.

### Remove or change

- no adult-vocabulary gate;
- no age/taboo gate;
- no sexual semantic tags in global STOP;
- statistical exclusive pairs become a **soft warning/penalty**, not a hard ban;
- hard exclusion only for literal contradictions or curated logical conflicts.

## 2.4 Concrete serving format

Use an immutable, versioned, little-endian, memory-mapped directory per person group:

```text
manifest.json
bundle_records.bin
bundle_tags.u32
context_records.bin
context_keys.u32
candidate_records.bin
attachment_records.bin
rating_stats.bin
checksums.json
```

Use `uint32` tag and bundle IDs. Keep strings in one shared global vocabulary, not duplicated across 13 models.

Suggested records:

- bundle: tag offset/count, role signature, core mask, actor scope, support, four rating counts, era stability, character concentration;
- context: context-tag offset/count, candidate offset/count;
- candidate: bundle ID, quantized score/statistics;
- attachment: tag ID, attachment type, confidence/lift/support.

No pickle, no LZMA, no Python object graph, and no eager deserialization. Opening a model should map files and validate headers/checksums.

### Computed design envelope

For a proposed—not yet measured—upper envelope of:

- 250,000 bundles,
- 200,000 context keys,
- 16 candidates/context,
- six attachments/bundle,

a compact layout is approximately:

- bundle records: **8 MB**
- average three uint32 core tags: **3 MB**
- contexts: **3.2 MB**
- context candidates: **19.2 MB**
- attachments: **12 MB**

Total: about **45 MB plus shared vocabulary and indexes**.

That is a computed capacity plan, not an observed final model size. The full one-group prototype must measure whether those caps preserve niche-context coverage. The caps must be per-context/evidence based, never content based.

---

# 3. Answers to Q1–Q6

## Q1. Mine or do not mine?

**Mine bounded typed bundles offline. Do not mine closed sets, and do not extract all candidate bundles from matched posts on every query.**

### Measured query benchmark

I built an in-memory uint32 posting index over the 188,150 sampled `1girl_solo` posts. Query intersection used NumPy sorted-array intersection. Outputs were projected onto the 8,568-tag straw-man MAIN vocabulary.

| Query | Matches | Intersection | Whole residual-set counting | Residual pair counting |
|---|---:|---:|---:|---:|
| `sitting, smile` | 8,701 | 0.386 ms | 10.24 ms | 304.5 ms |
| `school uniform, pleated skirt, standing` | 1,411 | 0.239 ms | 1.70 ms | 46.4 ms |
| `lying, bed, looking at viewer` | 453 | 0.351 ms | 0.44 ms | 10.0 ms |
| four-tag school/outdoor scene | 86 | 0.484 ms | 0.10 ms | 3.22 ms |
| `nude, spread legs` | 815 | 0.030 ms | 0.77 ms | 13.1 ms |

These are medians from repeated runs.

The common two-tag query produced:

- **8,366** distinct whole residual sets from 8,701 posts;
- **8,060 / 8,366 = 96.3%** had support 1;
- highest residual-set support was only **6**.

For the school query, **97.8%** of distinct residual sets had support 1.

So whole-set extraction is fast but useless as a popularity model. Pair extraction finds repeatable structure, but the common query generated **287,556 distinct pairs** and cost 304.5 ms before lift, noise filtering, or ranking.

### `s_1girl_solo` extrapolation

Using the measured 4.597 scale factor:

- common-query whole-set extraction: approximately **47 ms**
- common-query pair extraction: approximately **1.40 seconds**
- school-query pair extraction: approximately **213 ms**
- four-tag scene pair extraction: approximately **14.8 ms**

These are linear extrapolations from Python measurements, not direct full-partition measurements. An optimized native kernel would improve them by an **unmeasured** amount, but it would not fix support-1 fragmentation or broad-query candidate explosion.

Therefore:

- posting intersection is cheap;
- on-query combinatorial extraction is the expensive and unstable part;
- bounded offline bundle mining is the correct trade.

A capped matched-post fallback can remain for contexts absent from the mined context table, but it should be explicitly labelled low-confidence and sampled, not the normal path.

---

## Q2. What partial-match retrieval model?

Use **support-adaptive subset backoff**.

Not strict AND alone:

- two common tags matched **4.62%** of sampled `1girl_solo`;
- the school triple matched **0.750%**;
- the bed triple matched **0.241%**;
- the four-tag scene matched **0.0457%**.

And not unrestricted soft post similarity: it tends to reward head-tag overlap and makes it difficult to explain why a bundle was retrieved.

### Recommended order

1. Exact stored context, if it has enough effective support.
2. All high-information query pairs.
3. Individual query tags.
4. Blend evidence, rewarding:
   - IDF-weighted query coverage;
   - agreement among multiple subsets;
   - conditional confidence/lift;
   - rating and temporal stability.
5. Never fail because one query tag is absent from the model.

Do not simply drop the rarest query tag until AND succeeds. Rare tags are often the most informative. Backoff should prefer subsets with maximum total information weight, not maximum raw frequency.

---

## Q3. Role-typed split or Event Preset promotion?

**Neither alone. Use role-templated cores plus empirical per-bundle attachment promotion.**

The fixed role split is too broad:

- 14.76 projected MAIN tags/post;
- p90 24;
- whole-set support-1 rates above 96% for the measured queries.

The 0.9 rule is too conservative to define all cores:

- expression promotion: 6.33% of events;
- clothing promotion: 15.58%.

It is good evidence of inseparability, not a complete ontology.

### How to measure the alternatives

Run three ablations over the same temporal test cases:

1. fixed role-only core;
2. 0.9 promotion-only core;
3. hybrid role template + empirical promotion.

Score separately:

- exact core-bundle Hit/MRR;
- attachment Precision@K and Recall@K;
- size-2 versus size-3+ bundle performance;
- stability across rating, era, frequency, and adult/tag-category slices;
- character-held-out performance.

Data-only evaluation cannot fully determine perceptual “mainness.” Add a human-labelled core-versus-attachment audit using actual returned prompts. The necessary audit size is **unmeasured**; determine it from disagreement rates in a pilot rather than inventing a sample size.

---

## Q4. Memory and latency budget

### Old asset, remeasured

Actual `s_1girl_solo.tgp`:

- disk: **44,985,086 bytes**
- events: **864,892**
- nnz: **24,990,787**
- load: **2.54 s**
- stored NumPy arrays: **156,863,862 bytes = 149.60 MiB**
  - forward CSR/count arrays: **54.26 MiB**
  - inverted posting arrays: **95.33 MiB**

This matches the source: LZMA+pickle followed by copies into uint16/int32 arrays and a second inverted representation (`Dev0714:quick_search_data.py:44-60`).

### CSR alternative

At the measured 14.76 projected MAIN tags/post, an `864,892`-post uint32 forward CSR computes to:

- tag IDs: included below
- offsets: uint32
- total: **54,522,188 bytes = 52.00 MiB**

A uint32 MAIN inverted index computes to another:

- **51,062,616 bytes = 48.70 MiB**

Keeping both would therefore still be about **100.7 MiB**, before auxiliary data and Python overhead. Merely rebuilding CSR is not enough.

### Posting-only diagnostic

The sample had 5,880,692 occurrences across all general-tag query postings:

- raw uint32 postings: **23.52 MB**
- delta-varint postings: **6.93 MB**
- skip entry every 128 postings: **0.554 MB**

Extrapolated to 864,892 posts:

- raw: **108.13 MB / 103.12 MiB**
- delta-varint: **31.84 MB / 30.36 MiB**
- skip table: **2.55 MB / 2.43 MiB**

Vocabulary strings and full-archive tail growth are **unmeasured**.

A raw NumPy mmap test over 23.9 MB of arrays opened in:

- first open: **27.7 ms**
- subsequent opens: **0.88–1.16 ms**

That measures mapping/metadata setup, not genuine cold-disk page-in.

### Recommendation

The chosen serving model should contain **no per-post CSR at all**. Store mined bundles and context adjacency as flat mmapped tables. The computed 45 MB envelope above is a defensible starting point, with:

- proposed resident target: **<64 MiB per active group, unmeasured**
- proposed warm p95 query target: **<50 ms, unmeasured**
- proposed first-query target: **<250 ms, unmeasured**

These are acceptance targets, not achieved measurements. A full `1girl_solo` prototype must validate them before the architecture is frozen.

Also note that one all-rating `1girl_solo` group extrapolates to approximately **3.90 million posts** from the stratified sample. A per-person raw post index would therefore be much larger than the requested old `s_1girl_solo` comparison.

---

## Q5. Rating

**Rating should be a feature with stored sufficient statistics, not a partition dimension and not a hard content filter.**

Sampled `1girl_solo` distribution:

| Rating | Posts | Share |
|---|---:|---:|
| g | 54,723 | 29.08% |
| s | 101,439 | 53.91% |
| q | 23,503 | 12.49% |
| e | 8,485 | 4.51% |

The sparsity cost is not uniformly “4×.” In this sample, `s` has almost **12×** as many posts as `e`.

For each bundle and context edge, store four rating counts. At query time:

- use the aggregate evidence as the prior;
- adjust with a shrunk rating-specific affinity;
- never remove a candidate solely because of rating;
- if the user’s tags strongly support explicit/taboo content, that evidence must override the weak rating prior.

This preserves statistical strength and still learns that some combinations are rating-associated.

---

## Q6. Concrete evaluation metric

First, rename the task **held-out prompt completion**, not next-post prediction.

### Dataset construction

For every person group:

1. Split by `created_at`: train, validation, final temporal test.
2. Put exact and near-duplicate posts in only one split.
3. Audit separately with character-held-out and era-held-out slices.
4. From each eligible test post:
   - remove person-count, rating, artist, character, copyright, and non-prompt metadata;
   - create deterministic prompt masks exposing 2–4 tags;
   - withhold the remaining bundle-eligible tags;
   - create multiple role-stratified masks where possible.
5. Preserve all adult/taboo cases; report them as slices, not exclusions.

Let:

- \(Q_i\): visible prompt tags;
- \(H_i\): withheld tags;
- \(C_{ij}\): the core of recommendation \(j\), size 2–4.

A recommendation is an exact bundle hit when:

\[
C_{ij}\cap Q_i=\varnothing
\quad\text{and}\quad
C_{ij}\subseteq H_i
\]

### Primary metric

Use paired improvement over the unconditional popularity baseline:

\[
\Delta Hit@5 =
\frac1N\sum_i
\left[
Hit_i(\text{model},5)-Hit_i(\text{head baseline},5)
\right]
\]

Macro-average this across:

- bundle role;
- bundle size 2 versus 3+;
- tag frequency;
- rating;
- adult/taboo versus other;
- person group.

The head baseline predicts globally frequent valid typed bundles after removing prompt overlaps.

A system that merely returns corpus heads gets **exactly 0** on this delta metric by construction. That is the correct way to enforce the user’s desired “stub ≈ 0.”

Also report absolute:

- ExactBundle Hit@1/5/10;
- MRR@10;
- exact predicted-bundle Precision@K;
- size-3+ Hit@K;
- catalog/context coverage;
- abstention rate;
- p50/p95/p99 latency and mapped/resident bytes.

### Measured trivial baseline

I measured a preliminary pair-bundle version using:

- training: five stratified historical shards, **119,373** eligible `1girl_solo` posts;
- test: shards 125 and 149, **61,402** posts;
- deterministic masked cases: **20,000**;
- no removal of `nude`, `completely nude`, or `spread legs`.

The unconditional global-pair baseline scored:

| Metric | Score |
|---|---:|
| Hit@1 | 11.26% |
| Hit@5 | 28.97% |
| Hit@10 | 36.57% |
| MRR@5 | 0.172 |
| MRR@10 | 0.182 |
| predicted-pair precision@5 | 8.96% |
| predicted-pair precision@10 | 7.37% |

Therefore an absolute held-out Hit@K cannot make a head stub score near zero. Common pairs such as `blush + smile` genuinely occur in many held-out posts. The paired delta is necessary.

---

# 4. Three biggest risks and early falsification

## Risk 1: The taxonomy still does not identify coherent bundles

Even bounded mining can produce statistically strong but semantically shapeless pairs such as `blush + shirt`. Multi-person posts add unresolved actor ownership.

**Falsify early:**

- build only one full person group first;
- inspect the most frequent and highest-lift bundles by role;
- run the role-only, 0.9-only, and hybrid ablations;
- audit actual assembled prompts, not isolated tag pairs;
- for multi-person groups, measure how often actor scope is genuinely recoverable. This is currently **unmeasured**.

If bundles cannot be assigned a coherent role without hand-authored exceptions, stop expanding mining and strengthen the templates.

## Risk 2: Character design and era leakage masquerade as compatibility

A high held-out score can still come from the same character/franchise appearing in train and test, or from adjacent time slices sharing fashions.

**Falsify early:**

- compare ordinary temporal test with character-held-out test;
- compare full-history with era-balanced scores;
- measure the score change after character-concentration filtering;
- manually audit the highest-loss relations.

If most gain disappears on character-held-out data, the model has learned character wardrobes, not general combinations.

## Risk 3: Context/bundle cardinality breaks the memory budget—or caps erase niche content

The proposed 45 MB layout is a computed envelope. Actual context and bundle counts are unmeasured. Global top caps would disproportionately delete rare, including taboo, contexts.

**Falsify early:**

- build the full all-rating `1girl_solo` model;
- publish counts by context frequency and content slice;
- measure mapped bytes, working-set bytes, cold/warm load, and p95 query latency;
- compare held-out gain before and after each cap;
- require per-context coverage reporting, especially rare and adult/taboo slices.

If the model exceeds budget, reduce context depth or quantize statistics before reducing content categories. Do not solve cardinality by reinstating adult/age filters.

