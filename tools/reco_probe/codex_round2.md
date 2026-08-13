# Round-2 verdict

**Your bounded lift-ranked projection replicates. My round-1 rejection was based on the wrong extraction algorithm, so I retract the recommendation to mine a general offline bundle catalog.**

The revised architecture should be:

1. one sampled CSR + rebuilt inverted index per person group;
2. query-time bounded tuple extraction for ordinary contexts;
3. exact precomputation only for expensive head single-tag contexts;
4. implication/same-family adjacency precomputed offline, not recomputed per query;
5. taxonomy used to label/output roles, not as a hard candidate gate.

I ran your two probes unchanged, then wrote additional measurement scripts only under `C:\VNR\DEV\codex_ws`. Nothing under the NAIA repositories was modified.

---

## R0. Accepted decisions

No disagreement. I am not reopening:

- removal of content/age/adult gates;
- soft rather than hard statistical exclusivity;
- `"" → other`;
- rating as a feature;
- the rejection of `PRIMARY_AXES == main identity`.

---

# R1. Exact combination extraction

## Reproduction

Running `claude_probe_combo.py` unchanged reproduced your headline supports exactly:

| Context | Matches | Top tuple support |
|---|---:|---:|
| `office lady` | 2,122 | **48** |
| `maid` | 14,031 | **722** |
| `beach, smile` | 4,741 | **68** |
| `school uniform, classroom` | 1,125 | **162** |
| `kimono, festival` | 99 | **6** |

The actual tuples also matched exactly.

My round-1 “maximum support 6” statement was correct only for whole residual-set fingerprints. Applying it to your bounded top-four projection was wrong.

## Support distribution of exact four-tuples

Measured on the same 731,150-post sample and exact algorithm:

| Context | Distinct 4-tuples | Support 1 | Support ≤2 | Support ≥6 | Support ≥10 | Maximum |
|---|---:|---:|---:|---:|---:|---:|
| `office lady` | 1,309 | 76.6% | 91.4% | 23 | 13 | **48** |
| `maid` | 3,201 | 66.1% | 81.8% | 255 | 142 | **722** |
| `beach, smile` | 2,613 | 72.4% | 88.0% | 85 | 36 | **68** |
| `school uniform, classroom` | 494 | 73.5% | 88.1% | 24 | 15 | **162** |
| `kimono, festival` | 77 | 85.7% | 94.8% | 1 | 0 | **6** |
| `sword` | 3,862 | 66.8% | 81.5% | 320 | 204 | **1,701** |

Most distinct tuples still have support one, but that is no longer dispositive: those tuples are discarded by the output support floor, while tens or hundreds of repeatable tuples remain for supported contexts.

## Revised mining recommendation

**No, a general offline bundle mine is no longer justified.**

Use your contextual query-time projection, with two bounded precomputations:

- exact results for expensive head single-tag contexts;
- implication/same-family adjacency needed during tuple construction.

Do not build the 250,000-bundle/context catalog I proposed in round 1. Your algorithm derives a context-specific tuple vocabulary cheaply enough for non-head contexts and avoids freezing arbitrary context keys into a mined catalog.

## Internal deduplication result

Your second-stage implication/same-family experiment also reproduced:

| Context | Original | Deduplicated | Mean tuple surprisal |
|---|---:|---:|---:|
| `sword` | 155 ms | **2,532 ms** | 23.2 → 25.4 bits |
| `maid` | 109 ms | **2,095 ms** | 25.1 → 25.2 bits |
| `office lady` | 20 ms | **1,428 ms** | 35.2 → 34.6 bits |
| `beach, smile` | 46 ms | **1,653 ms** | 22.4 → 22.4 bits |

The semantic fix is necessary, but the present implementation is unsuitable for runtime because it recomputes pair intersections among all candidates.

**Alternative:** precompute a local-tag adjacency containing:

- confidence ≥0.95 implication pairs;
- same-family IDs;
- literal contradiction edges.

Then per-post selection only checks adjacency against at most three already-picked tags.

---

# R1b. Reconciliation of the remaining measurements

## Measurements that replicated exactly

### Corpus census

My full 150-shard census produced:

- physical parquet rows: **7,543,144**
- usable non-null `general` rows: **7,541,410**
- null/empty `general`: **1,734**
- `1girl_solo`: **3,935,088**
- vocabulary at frequency ≥20: **23,122**
- nnz: **125,944,397**

Thus your 7,541,410 count means usable posts, while 7,543,144 is the physical row count. Both are correct with that distinction.

The other group counts also replicated exactly.

### Metric probe

Running `claude_probe_metric.py` unchanged reproduced every reported value:

| Method | P@8 | P@8_info | Surprisal | Empty |
|---|---:|---:|---:|---:|
| corpus head | 0.548 | 0.000 | 0.044 | 0 |
| raw count | 0.627 | 0.065 | 0.110 | 63 |
| lift ≥2 | 0.297 | 0.131 | 0.156 | 3 |
| lift ≥1 | 0.334 | 0.126 | 0.160 | 0 |

Your metric results are correct.

### Query latency

Supports matched exactly. Timing varied:

- `office lady`: your 58 ms; my three-run median **19.0 ms**
- `maid`: your 138 ms; mine **105.7 ms**
- `beach, smile`: 43 ms versus **42.2 ms**
- school/classroom: 12 ms versus **11.3 ms**

This is warm-state/runtime variation, not an algorithm disagreement. For planning, retain your slower 138 ms figure until controlled p95 measurements exist.

## Where I still disagree: rarest-tag backoff

I compared your “drop the rarest” backoff with my round-1 recommendation: select the supported subset retaining maximum total prompt surprisal.

Same 600 cases, seed, metric and lift scorer:

| Backoff | P@8_info | Surprisal | Info recall | Empty |
|---|---:|---:|---:|---:|
| none | 0.1504 | 0.1187 | 0.0543 | 177 |
| drop rarest | 0.1307 | 0.1557 | 0.0704 | **3** |
| maximum-information subset | **0.1446** | **0.1694** | **0.0777** | 4 |

So your broad conclusion is correct—backoff matters—but **dropping the rarest tag is the wrong backoff policy**:

- P@8_info: **+10.6% relative**
- surprisal: **+8.8% relative**
- information recall: **+10.4% relative**

The cost is one additional empty answer in 600.

Use the most specific subset meeting the support floor; among equal-size subsets, maximize retained prompt surprisal.

## Where your inference is premature: 731k as the final production cap

Your single-tag metric saturates around 731k, but that does not prove combination coverage saturates there.

At 731k, `kimono, festival` had:

- 99 matches;
- 77 four-tuples;
- 66/77 support one;
- only **one** tuple reaching support six.

Therefore 731k is a valid current memory target, but not yet a settled corpus cap. Run the sampling curve again using exact size-3/4 bundle completion and rare-context coverage. Your reported `+0.001 P@8_info` from doubling does not answer that question.

I did not rerun your full sampling or per-group threshold curves; my round-1 measurements did not contradict them.

---

# R2. Disk format

## Recommendation: one raw, sectioned, memory-mappable file per group

Use a custom little-endian `NCSR1` file, not pickle, LZMA, Parquet or an Arrow object graph:

```text
header:
  magic/version
  person-group
  post_count, vocab_count, nnz
  section offsets and lengths
  model/taxonomy/source hashes

sections:
  local_to_global_tag_id   uint32[vocab]
  event_tag_indices        uint16[nnz]
  event_tag_indptr         uint32[posts+1]
  post_rating              uint8[posts]
  tag_rating_counts        uint32[vocab,4]
  head_context_index
  head_context_tuples
```

The shared global vocabulary holds strings. All sections should be page-aligned.

Store only the forward CSR incidence orientation on disk.

## Measured sizes

For the actual 731,150-post sample:

| Stored component | Bytes |
|---|---:|
| `indices.u16` | 47,311,522 |
| `indptr.u32` | 2,924,732 |
| frequency + manifest | 46,926 |
| **Measured files** | **50,283,180** |

Adding the proposed rating data, local/global map and aligned header gives approximately **51.2 MB** on disk.

The rebuilt inverted postings require another:

- postings: **94,622,788 bytes**
- bounds: **46,752 bytes**

Final resident model is therefore approximately **145 MB**, agreeing with your sampling-curve measurement.

For comparison, the uncapped full `1girl_solo` corpus computes to:

- one-copy CSR disk: **267,721,638 bytes**
- full resident CSR + inverted representation: **771,591,718 bytes**

Across all full groups I measured:

- one-copy CSR disk: **526,607,686 bytes**
- resident representation: **1,518,927,906 bytes**

## Rebuild the inverted index; do not store it

Storing it would add about **94.7 MB** to the 50.3 MB sampled model, almost tripling per-group disk incidence storage.

Measured on 23,655,697 nnz:

| Operation | Time |
|---|---:|
| mmap open | 14.9 ms |
| warm sequential touch | 25.2 ms |
| correct stable argsort | 0.384–1.537 s |
| SciPy CSR→CSC conversion | **134.7 ms** |

The CSR→CSC conversion produced sorted posting lists with zero order violations.

A default unstable argsort produced **11,806,424 descending adjacent posting pairs**, so it cannot be used with `np.intersect1d(..., assume_unique=True)`. Your probes use stable argsort, so your 0.6-second result is plausible and not wrong.

Use SciPy’s linear CSR→CSC conversion instead of argsort. Measured warm load/rebuild is approximately:

- 15 ms mapping
- 25 ms page touch
- 135 ms inversion
- **about 0.18 seconds total**

True cold-storage page-in remains **unmeasured**. It must be benchmarked after building the final aligned file.

Use a byte-budgeted LRU and evict the old model before materializing the new inverted index. Do not let two 145 MB models overlap merely because the LRU is entry-count based.

---

# R3. Rating

**Feature, not partition and not filter.**

My census replicated the skew:

### `1girl_1boy`

- g: 159,412
- s: 136,243
- q: 47,957
- e: 340,113

Explicit is **49.75%**. Partitioning leaves the q model **14.3× smaller** than the aggregate model.

### `1boy_solo`

- g: 262,926
- s: 106,415
- q: 15,114
- e: 15,469

General is **65.74%**. The e partition would be **25.9× smaller** than the aggregate.

Hard query-time rating filtering has the same sparsity problem as partitioning, just later.

Store:

- one rating byte per sampled post;
- four marginal counts per tag;
- four support counts per returned tuple.

Rank using the aggregate conditional as the prior and a shrunk rating-specific conditional:

\[
\hat P(B\mid S,r)=
\frac{n(S,B,r)+\alpha P(B\mid S)}
     {n(S,r)+\alpha}
\]

`α` remains unmeasured and should be selected on temporal validation. Rating must change rank, never candidate eligibility.

---

# R4. Main versus auxiliary

I ran the requested ablation on the exact metric probe:

- same 242,798 training posts;
- same 31,724 holdout posts;
- same 600 masked cases;
- same scorer and backoff;
- only candidate-role eligibility changed.

Policies:

1. **fixed taxonomy:** only your seven MAIN groups;
2. **promotion-only:** candidate confidence >0.9;
3. **hybrid:** taxonomy MAIN, plus non-MAIN candidates over 0.9;
4. **all tags:** no role-based eligibility gate.

| Policy | P@8_info | Surprisal | Info recall | Empty | Mean outputs |
|---|---:|---:|---:|---:|---:|
| all tags | **0.1307** | **0.1557** | **0.0704** | 3 | 7.943 |
| fixed taxonomy | 0.1053 | 0.1209 | 0.0562 | 3 | 7.870 |
| promotion-only | **0.3048** | 0.0340 | 0.0121 | **362** | 0.585 |
| fixed + promotion | 0.1102 | 0.1275 | 0.0589 | 3 | 7.877 |

## Decision

Promotion-only appears to win P@8_info, but it does so by returning almost nothing:

- **60.3% empty**
- only 0.585 outputs per case
- information recall **0.0121**
- surprisal **0.034**

This exposes an abstention loophole in `P@8_info`: its denominator is `len(R)`, not `8 × cases`.

For a usable system:

- fixed taxonomy beats promotion-only;
- hybrid beats fixed taxonomy;
- **all-tags retrieval beats both**.

Therefore:

- do not use taxonomy or confidence as a hard retrieval gate;
- retrieve all legitimate informative candidates;
- use taxonomy as the initial display role;
- use >0.9 confidence to promote a tag within the returned tuple;
- evaluate semantic MAIN/AUX accuracy against a human-labelled audit, because held-out tag recovery has no ground-truth concept of “mainness.”

Also report information recall or fixed-denominator P@8_info so abstention cannot manufacture a win.

---

# R5. Single-common-tag query

## Choose exact head-context precomputation

Measured non-deduplicated query times:

| Context | Matches | Median |
|---|---:|---:|
| `office lady` | 2,122 | 19.0 ms |
| `beach, smile` | 4,741 | 42.2 ms |
| `maid` | 14,031 | 105.7 ms |
| `sword` | 16,797 | 118.3 ms |
| `smile` | 269,645 | 1,043 ms |
| `looking at viewer` | 459,484 | 1,734 ms |

A measured breakpoint around **5,000 matched posts** is reasonable: the observed queries below it stayed under 50 ms; those materially above it did not.

In the 731k model:

- **662** tags have frequency ≥5,000.
- Storing top 20 four-tag tuples per head context in a compact 16-byte record costs a computed **217,136 bytes**.
- A Python dictionary lookup over the generated cache measured approximately **80.5 ns** per lookup. The final mmap lookup is unmeasured but will be negligible relative to extraction.

For `maid`, the cache stores the exact result of the full 14,031-post computation. It is not sampled, so:

- top-five agreement: exact by construction;
- support values: unchanged;
- P@8_info cost: **zero by construction** for the same model snapshot.

Rebuild the cache whenever the model is rebuilt. If rating can reorder results, store the union of aggregate and four rating-specific top lists; even a fivefold 217 KB envelope remains small.

Do **not** sample head matched sets unless the exact cache becomes unexpectedly large. There is no reason to accept sampling variance when exact precomputation is this small.

---

# R6. Three cheapest falsification experiments

## 1. Exact bundle completion, not tag completion

Run first.

Using the existing 600 temporal cases, return five actual size-3/4 tuples and score:

\[
\text{ExactBundleHit@5}
=
1[\exists B \text{ where } B \subseteq H]
\]

Compare against:

- unconditional tuple head;
- four independently ranked tags grouped after ranking;
- raw-count tuples.

Use paired bootstrap confidence intervals. **Stop if the bounded tuple model does not beat the best baseline.**

This is the cheapest critical test because the current P@8_info can reward individually correct tags without proving that the recommended combination is correct. The promotion-only result—P@8_info 0.305 while returning 0.585 tags—already demonstrates that loophole.

Also repeat the 25%/50%/100%/200% sampling curve on this metric. Until then, 731k is not a settled combination-model cap.

## 2. Character/franchise-disjoint repetition

Build no new algorithm. Change only the split:

- no character or copyright identity may occur in both train and test;
- apply the existing character-concentration and duplicate filters;
- rerun ExactBundleHit@5 and P@8_info.

**Stop if the improvement over baselines falls to zero on the disjoint split.** That would show that apparent clothing/accessory compatibility is mostly memorized character design.

Outcome is currently **unmeasured**.

## 3. Blind assembled-prompt audit

Only after the first two automated tests pass.

Audit complete returned prompts, not isolated tuples, with balanced slices:

- common single-tag contexts;
- rare multi-tag contexts;
- multi-person groups;
- explicit/taboo combinations;
- ordinary non-adult contexts.

Blindly compare:

1. bounded tuple output;
2. independent single-tag ranking;
3. raw-count output.

Judge:

- combination coherence;
- topical usefulness;
- MAIN/AUX assignment;
- duplicate/implication waste;
- actor-scope errors.

**Stop if bounded tuples are not preferred over independent tags, or if MAIN/AUX labels cannot be judged consistently without extensive exceptions.**

The necessary audit size is **unmeasured**; determine it from a small pilot disagreement rate rather than choosing an arbitrary large sample.