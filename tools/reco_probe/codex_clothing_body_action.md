# Verdict

The user problem is real, but the brief overstates what is missing and frames three different relations as one causal implication problem.

## Framing problems found

1. **The probe does not measure “exposure” specifically.**  
   `CLOTH`, `BODY`, and `POSE` are broad unions (`C:\VNR\DEV\codex_ws\claude_probe_exposure.py:32-35`). Consequently, `BODY` includes hair and breast-size attributes, while `POSE` includes gaze, holding, combat, and clothing interaction. Of 1,326 focused garment→visibility pairs at confidence ≥0.30, **763 were merely `-> breasts`**.

2. **The headline exemplar is excluded from the aggregate scan.**  
   `see-through` belongs to `fx_effect`, not a `cloth*` axis (`data/interactive_axis_tags.json:4050`), so the reported 4,388 clothing→body pairs never include it.

3. **`see-through -> nipples` contradicts the probe’s own definition of an implication.**  
   Confidence is only **0.118**, below the probe’s “usually holds” threshold of 0.30 (`claude_probe_exposure.py:44,71`). In 88.2% of `see-through` posts, explicit `nipples` is absent.

4. **The fixed pair gate is not the runtime.**  
   Runtime first returns precomputed head tuples (`core/tag_combo/query.py:215-231`) and otherwise backs off through `(2.0,.30)`, `(1.5,.50)`, `(1.2,.80)` (`query.py:45-51,247-289`). The probe applies only 2.0/0.30 and never assembles tuples.

5. **Actual runtime already recovers important cases:**

   | Query | Current top result |
   |---|---|
   | `crop top` | `navel + stomach + midriff`, support 563 |
   | `thighhighs` | `black thighhighs + miniskirt + zettai ryouiki`, support 898 |
   | `see-through` | includes `bra visible through clothes` and `covered nipples` tuples |
   | `garter belt` | `lingerie` appears in tuple ranks 2 and 3 |

   Thus “garter belt never reaches the top-3 tuple slots” is false for the actual current model, and `thighhighs -> zettai ryouiki` is already recovered as the correct three-way relationship.

6. **The legacy path is not in this checkout.**  
   `C:\VNR\DEV\NAIA2.0\.experimental\2025\state_system` does not exist. I inspected the surviving copy at `C:\VNR\NAIA2.0\.experimental\2025\state_system`. The SPEC nevertheless refers to it as a reusable local asset (`tools/reco_probe/SPEC.md:469-470`).

---

# Q1. Is this one relation or three?

**One user job, but at least three inference types—and the clothing/action arrow is largely backwards.**

Focused scans on the same 800,000-post model:

| Typed scan | eligible seeds | confidence ≥0.30 pairs | observation |
|---|---:|---:|---|
| garment → visibility | 846 | 1,326 | 763 pairs, 57.5%, end in `breasts` |
| garment state → visibility | 133 | 308 | more concentrated, but still 132 `breasts` pairs |
| pure pose → visibility | 122 | 212 | foot/sole/toe relationships dominate the strongest results |
| clothing → clothing action | 1,102 | **0** | only 49 pairs even at confidence ≥0.10 |

The legacy curated dependencies make the direction clearer:

- **55** clothing-action tags imply a garment, e.g. `bra pull -> bra`.
- **34** imply a generic action, e.g. `dress lift -> clothes lift`.
- Only **1** rule goes from a clothing-axis child to a clothing action.

Therefore:

1. **Garment/state → visibility**: material, cut, coverage, and clothing-state semantics.
2. **Action → required/affected garment**: prerequisite relation, usually the reverse of the brief’s arrow.
3. **Pose + camera + occlusion → visibility**: scene/render constraint, not pose alone.

Person groups should calibrate probabilities, but not own 13 separate physical ontologies. For example:

- `see-through -> nipples`: confidence **0.018–0.463**, lift **1.11–5.09** across groups.
- `crop top -> navel`: confidence **0.365–0.655**, consistently positive.
- `thighhighs -> zettai ryouiki`: confidence **0.030–0.131**, despite lift **6.41–46.14**.

That variation reflects rating, actor mixture, and annotation conventions. In multi-person groups the rule also needs an actor scope; a group-level co-occurrence cannot say whose garment exposes whose body.

---

# Q2. Learn it, or read it?

**Read/curate the semantics; use statistics for candidate discovery and calibration. The proposed existing-asset composition is not presently derivable.**

Measured asset contents:

- `clothing_regions.json`: **429 unique tags**, seven coarse regions.
- `clothing_event.json`: **316 records**, whose only fields are `tag`, `garment_noun`, and `region`.
- Records with any body/exposure/visibility output field: **0**.
- Event tags overlapping `cloth_state`: **93/316**.
- Current official clothing→visibility implications: **0**.
- Legacy `_dependency_rules` matching the seven named target pairs: **0/7**.

Target classification also exposes the problem:

| Tag | Existing classification |
|---|---|
| `see-through` | `fx_effect`, STYLE region; no garment region |
| `see-through shirt` | `cloth_revealing`, UPPER_BODY |
| `crop top` | `cloth_top`, UPPER_BODY |
| `thighhighs` | `cloth_legwear`, LEGS |
| `zettai ryouiki` | **`cloth_legwear`**, not body exposure |
| `navel`, `midriff`, `thighs`, `collarbone` | `body_expose` |
| `nipples` | absent from the axis file |

Concrete failures:

- **Crop top** exposes an adjacent region below its coverage. `UPPER_BODY` does not encode “short hem exposes midriff.”
- **See-through** needs both a base garment and a material/state modifier. Generic `see-through` has no region.
- **Zettai ryouiki** is a relationship among thighhighs, exposed thigh, and usually a short skirt—not “the LEGS region becomes exposed.”
- **Sleeveless shirt → collarbone is empirically wrong**: confidence 0.112, lift 0.81. Better consequences are `bare shoulders` (confidence 0.456, lift 2.66), `bare arms` (0.090, 3.28), and `armpits` (0.107, 2.61).

So the literal existing composition reproduces **0/5** central pairs (`crop top`’s three outputs, `see-through -> nipples`, `thighhighs -> zettai ryouiki`). Making it work requires adding new knowledge such as garment boundaries, transparent material behavior, and relational gaps. That is a new ontology, not a cross-product of current files.

---

# Q3. What statistically separates causation from background?

## Tests that failed

| Test | `see-through -> nipples` | `turtleneck leotard -> large breasts` | Result |
|---|---:|---:|---|
| lift | 1.8216 | 1.8232 | no separation |
| reverse confidence | 0.0344 | 0.000896 | false pair looks more asymmetric |
| P(B\|not A) | 0.0639 | 0.2427 | expected from different marginals |
| risk ratio vs not-A | 1.851 | 1.824 | no separation |
| same-region comparator | 1.97 (`see-through shirt`) | 1.84 | no separation |

“Condition out corpus background per body tag” is already what lift does:

\[
P(B|A) / P(B)
\]

The proposed necessity test using only `not A` is also nearly equivalent for rare garments. Neither creates a causal intervention.

## Test worth keeping: within-base modifier contrasts

Hold the base garment approximately constant and vary the modifier:

| Contrast | Outcome | treatment rate | base-control rate | RR |
|---|---|---:|---:|---:|
| see-through shirt vs other shirts | nipples | 0.081 | 0.029 | **2.76** |
| see-through dress vs other dresses | nipples | 0.095 | 0.018 | **5.43** |
| see-through leotard vs other leotards | nipples | 0.105 | 0.043 | **2.45** |
| turtleneck shirt vs other shirts | large breasts | 0.175 | 0.180 | **0.97** |
| turtleneck dress vs other dresses | large breasts | 0.239 | 0.202 | **1.19** |
| turtleneck leotard vs other leotards | large breasts | 0.443 | 0.415 | **1.07** |

This separates the headline pair from the negative control much better. It also generalizes across eight see-through garment bases, with RR **1.56–7.08**.

However, it remains observational. Annotation can be reverse-causal: an artist shows an underlayer, then annotators add `see-through`. Use this test to **mine candidates**, followed by semantic review—not as proof of physics.

For unmodified garments, use functional substitutes:

- `crop top` vs other upper tops: `navel` RR **6.40**, `midriff` RR **16.37**.
- `thighhighs` vs other legwear: `zettai ryouiki` RR **374**, but confidence is only **0.101**.
- `sleeveless shirt` vs other shirts: `collarbone` RR **0.94**, disproving the proposed relationship.

Also note the reverse implication for zettai ryouiki: **95.2%** of its posts contain `thighhighs`, but only **10.1%** of thighhigh posts contain zettai ryouiki. It is an optional construction, not an automatic consequence.

---

# Q4. What should the user see?

Use a **person-scoped consequence/consistency slot**, not a warning and not silent auto-add.

Example:

> **예상 노출 상태 — Character 1**  
> Crop top usually produces visible midriff/navel.  
> `[배꼽·복부 보이기]` `[가려진 상태 유지]` `[결정하지 않음]`

Behavior:

1. Show one coherent state proposal with its reason, not another unstructured tag list.
2. Accepting it writes explicit tags into the prompt/preset.
3. Save that decision—including actor scope and provenance—for reuse.
4. Rejection is also useful state: do not repeatedly propose the same consequence.
5. Never block contradictory or unusual requests; present alternatives without filtering.
6. For two or more people, require `Character 1`, `Character 2`, or `shared/unknown`.
7. Only auto-fill when the user explicitly enables a “lock consistency” mode and the rule has passed a curated precision gate.

A “warning” suggests prohibition and will create alert fatigue. Silent auto-add is unsafe: `see-through -> nipples` is present only 11.8% of the time, while `see-through shirt` more strongly predicts `bra visible through clothes` than explicit nipples. The UI should resolve intent, not pretend the inference is certain.

---

# Q5. What is reusable from state_system?

The useful pieces are narrower than the brief suggests.

| Legacy asset | Reuse verdict |
|---|---|
| `clothes_preset_lookup.json` | Region/conflict data only; already represented by the current 3,917-row mapping and 5,246 conflicts inside `core/clothes_preset/naia_clothes_preset` |
| `pose_clothing_affinity.json::_dependency_rules` | All **1,026/1,026** child-parent pairs already exist in current `interactive_preset_facts.json`; no incremental data |
| `compound_tags.json` | **Useful:** 310 typed action→affected-garment records such as `shirt lift -> shirt` |
| `clothing_normalizer.py` | **Useful transform:** base-garment extraction; but it strips `see-through` (`clothing_normalizer.py:12-22,49`) and therefore must preserve the modifier separately |
| `clothing_state_graphs.json` | Useful as a vocabulary of 10 garment state sequences, not as validated exposure logic |
| `state_engine.py` body sets | Useful as seed vocabulary: body visibility/state tags (`state_engine.py:23-52`) |
| transition/co-change data | Do not reuse for exposure semantics; the old audit found 82.4% incidental |
| explicit composition overrides | Do not reuse: they jump to topless/bottomless/nude rather than infer visibility (`state_engine.py:573-613`) |

The ten state graphs contain only **six** outputs overlapping the old body/state vocabulary, mostly `no shirt`, `topless`, `no pants`, `no bra`, and `no panties`; none cover the named crop-top, see-through, thighhigh, or sleeveless relationships.

Most importantly, these files are absent from the DEV checkout. Any genuinely reusable subset needs to be promoted into a tracked/generated current asset rather than loaded from the sibling legacy tree.

---

# Q6. Cheapest experiment that can kill the whole direction

Run a **Wizard-of-Oz oracle UI test before building inference**.

- Five target users.
- Twelve balanced prompt tasks each: four garment/visibility, four action/prerequisite, four pose/camera/visibility.
- Include solo, two-person, multi-person, general, and explicit examples.
- Compare:
  1. current tag-selection flow;
  2. the proposed structured consequence slot populated by a human with perfect suggestions.
- No recommendation engine and no server work are needed; use fixed target-image/reference cards.

Predeclare the stop gate:

- median time-to-final-prompt improves by **less than 20%**, or
- intended visible-state accuracy improves by **less than 15 percentage points**, or
- users undo/reject more than **10%** of even the oracle suggestions, or
- saved decisions do not improve the second/reuse task.

If a perfect oracle does not help, statistics and ontology work cannot rescue the product direction. If it does help, the next cheapest gate is a blind labeled-pair benchmark for the within-base contrast miner.

Repository files were not modified; analysis scripts were written only under `C:\VNR\DEV\codex_ws`.