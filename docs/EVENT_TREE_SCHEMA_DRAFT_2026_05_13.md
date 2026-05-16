# Event Tree Schema Draft

> 목적: NAIA 1.5 Storyteller/Turbo의 이벤트 순환, delta 기반 변형, 사람 작성 논리를 NAIA 2.0에서 명시적이고 추적 가능한 Directed Tree 스키마로 재정의한다.

## 1. Design Boundary

### Goals

- Directed Tree 구조를 기본 모델로 둔다. DAG 병합은 v1에서 금지한다.
- 사람의 논리는 node 사이의 `transition_policy`로 표현한다.
- 프롬프트, negative, seed, reference/vibe, generation mode 변경은 모두 trace에 남긴다.
- 1.5 Turbo의 하드코딩된 이벤트 변화 적용을 일반화된 rule/action으로 대체한다.
- 기존 `PromptProcessor`는 최종 프롬프트 조립 엔진으로 유지하고, Event Tree는 그 앞단의 orchestration layer로 둔다.

### Non-Goals

- raw Python/code injection 지원 안 함.
- NAIA 1.5 Turbo NSFW 고정 로직을 그대로 이식하지 않음.
- v1에서 graph merge, loop, back-edge, arbitrary retry graph를 지원하지 않음.
- 기존 Conditional Prompt DSL을 즉시 흡수하지 않음. 단, condition/action 모델은 유사하게 설계한다.

## 2. Top-Level Document

```json
{
  "schema_version": 1,
  "kind": "naia.event_tree",
  "id": "event_tree.example",
  "name": "Example Event Tree",
  "description": "",
  "entry_node_id": "node.start",
  "engine_options": {
    "max_frames": 32,
    "stop_on_generation_error": true,
    "trace_level": "full",
    "random_seed": null
  },
  "variables": {},
  "safety": {
    "allow_raw_code": false,
    "require_trace": true,
    "unknown_action": "error",
    "unknown_condition_source": "error"
  },
  "nodes": [],
  "templates": {}
}
```

### Required Invariants

- `schema_version <= supported_schema_version`.
- `kind == "naia.event_tree"`.
- `entry_node_id` must exist.
- Every non-entry node has exactly one parent edge.
- No cycles.
- No child node may be targeted by more than one parent. This keeps v1 as Directed Tree, not DAG.
- Every rule/action/condition kind must be known before execution.

## 3. Node Schema

```json
{
  "id": "node.start",
  "name": "Start",
  "kind": "event",
  "enabled": true,
  "selector": {
    "kind": "bucket",
    "source": "current_search",
    "rating": ["s", "q", "e"],
    "include_tags": ["standing"],
    "exclude_tags": [],
    "pick": {
      "strategy": "random_without_replacement",
      "max_candidates": 200
    }
  },
  "prompt_policy": {
    "base": "source_row.general",
    "carry": {
      "clothes": "from_previous",
      "background": "from_previous",
      "characters": "from_previous"
    },
    "wildcards": {
      "enabled": true,
      "preserve_sequential_counters": true
    }
  },
  "transition_policy": {
    "delta_from": "previous_frame",
    "rules": []
  },
  "generation_policy": {
    "mode": "txt2img",
    "seed": {
      "strategy": "random"
    },
    "reference": {
      "strategy": "none"
    },
    "resolution": {
      "strategy": "source_row_recommended"
    }
  },
  "children": []
}
```

### Node Kinds

| kind | 의미 |
|---|---|
| `event` | bucket에서 source row를 선택하고 prompt를 만든다. |
| `manual` | 사용자가 직접 지정한 prompt/source를 사용한다. |
| `retry` | 이전 frame을 기반으로 재시도한다. |
| `terminal` | 실행을 종료한다. generation request를 만들지 않는다. |

### Selector Kinds

| kind | 의미 |
|---|---|
| `bucket` | 검색 결과 또는 event dataset을 조건으로 필터링한다. |
| `source_row_ref` | 이전 frame의 source row를 재사용한다. |
| `manual_prompt` | 사용자가 입력한 prompt를 사용한다. |
| `none` | terminal node용. |

### Selector Sources

| source | 의미 |
|---|---|
| `current_search` | 현재 2.0 검색 결과 `SearchResultModel` 기반. |
| `event_dataset` | Turbo Event Sequence의 parquet event dataset 기반. |
| `preset_event` | Event Preset service 결과 기반. |
| `manual_rows` | 사용자가 넣은 row 목록 기반. |

## 4. Transition Policy

`transition_policy`는 1.5 Turbo의 하드코딩 개입을 대체하는 핵심 영역이다. 이 레이어는 prompt와 generation request를 변경할 수 있지만, 모든 변경은 `TraceRecord`에 남겨야 한다.

```json
{
  "delta_from": "previous_frame",
  "rules": [
    {
      "id": "rule.fix_seed_on_small_delta",
      "name": "Small delta keeps seed",
      "enabled": true,
      "priority": 100,
      "phase": "before_generation",
      "when": {
        "kind": "leaf",
        "source": "delta.difference_count",
        "op": "lt",
        "value": 12
      },
      "actions": [
        {
          "kind": "set_seed_policy",
          "strategy": "fixed_from_previous"
        }
      ]
    }
  ]
}
```

### Rule Phases

| phase | 실행 시점 |
|---|---|
| `after_select` | source row 선택 직후. |
| `before_prompt` | `PromptContext` 생성 전. |
| `after_prompt` | `PromptProcessor` 실행 후. |
| `before_generation` | generation request 생성 직전. |
| `after_result` | 생성 완료 또는 실패 후. branch 선택 전에 실행. |

### Condition Schema

Condition은 raw expression string이 아니라 구조화된 JSON이다.

```json
{
  "kind": "group",
  "logical": "AND",
  "children": [
    {
      "kind": "leaf",
      "source": "delta.added_tags",
      "op": "contains",
      "value": "looking at viewer"
    },
    {
      "kind": "leaf",
      "source": "source_row.rating",
      "op": "in",
      "value": ["s", "q"]
    }
  ]
}
```

#### Condition Sources

| source | 예시 의미 |
|---|---|
| `source_row.general` | 현재 선택 row의 general prompt 문자열. |
| `source_row.rating` | 현재 선택 row의 rating. |
| `prompt.tags` | 현재 prompt tag 목록. |
| `negative.tags` | 현재 negative tag 목록. |
| `delta.added_tags` | 이전 frame 대비 추가된 tag. |
| `delta.removed_tags` | 이전 frame 대비 제거된 tag. |
| `delta.difference_count` | added + removed 개수. |
| `run.frame_index` | 현재 실행 순번. |
| `variables.<name>` | tree-level mutable variable. |
| `result.status` | `success`, `error`, `cancelled`, `rejected`. |

#### Operators

| op | 대상 |
|---|---|
| `eq`, `ne` | scalar |
| `lt`, `lte`, `gt`, `gte` | number |
| `contains`, `not_contains` | list/string |
| `in`, `not_in` | scalar in list |
| `empty`, `not_empty` | list/string |
| `starts_with`, `ends_with` | string |

`regex`는 v1에서 제외한다. 필요하면 v2에서 안전한 제한 정규식만 추가한다.

## 5. Action Schema

Action은 prompt mutation, policy mutation, run variable mutation으로 나눈다.

### Prompt Actions

```json
{
  "kind": "add_tags",
  "target": "main",
  "tags": ["closed eyes"],
  "position": "append"
}
```

| kind | 의미 |
|---|---|
| `add_tags` | prompt/negative에 tag 추가. |
| `remove_tags` | tag 제거. |
| `move_tags` | tag 위치 이동. |
| `emphasize_tags` | weight 증가. |
| `deemphasize_tags` | weight 감소. |
| `add_negative_from_delta_removed` | `delta.removed_tags`를 negative에 추가. 1.5 Turbo의 rem 처리 대체. |

### Generation Policy Actions

```json
{
  "kind": "scale_reference_strength",
  "information_extracted_scale": 0.7,
  "reference_strength_scale": 0.5
}
```

| kind | 의미 |
|---|---|
| `set_seed_policy` | `random`, `fixed_from_previous`, `fixed_value`로 seed 전략 변경. |
| `set_resolution_policy` | source row, fixed, inherited 등으로 해상도 전략 변경. |
| `set_generation_mode` | `txt2img`, `img2img`, `inpaint` 지정. |
| `scale_reference_strength` | reference/vibe 강도 조절. |
| `set_reference_policy` | reference source와 carry 전략 지정. |
| `set_retry_limit` | retry node에서 사용할 최대 횟수 지정. |

### Run Variable Actions

```json
{
  "kind": "set_variable",
  "name": "last_scene_mood",
  "value_from": "delta.added_tags"
}
```

| kind | 의미 |
|---|---|
| `set_variable` | tree-level variable 저장. |
| `append_variable` | list variable에 추가. |
| `clear_variable` | variable 삭제. |

## 6. Edge / Branch Schema

Branch는 각 node의 `children`에 둔다. child는 하나의 parent에서만 참조될 수 있다.

```json
{
  "id": "edge.start.to.quiet",
  "to": "node.quiet_scene",
  "priority": 100,
  "when": {
    "kind": "leaf",
    "source": "delta.difference_count",
    "op": "lt",
    "value": 8
  },
  "fallback": false
}
```

### Edge Rules

- `children`은 `priority` 오름차순으로 평가한다.
- 처음 match된 edge로 이동한다.
- match가 없고 `fallback: true` edge가 있으면 fallback으로 이동한다.
- match도 fallback도 없으면 run을 정상 종료한다.
- 같은 node 안에서 fallback edge는 최대 하나만 허용한다.

## 7. Runtime Frame

Tree 실행은 immutable-ish `RunFrame` 목록으로 기록한다. UI는 이 frame을 보여주면 된다.

```json
{
  "frame_id": "frame.0003",
  "run_id": "run.2026-05-13T12-00-00",
  "frame_index": 3,
  "node_id": "node.quiet_scene",
  "parent_frame_id": "frame.0002",
  "selected_source": {
    "kind": "source_row",
    "row_id": 12345,
    "rating": "q",
    "source": "event_dataset"
  },
  "event_delta": {
    "from_frame_id": "frame.0002",
    "added_tags": ["closed eyes"],
    "removed_tags": ["looking at viewer"],
    "retained_tags": [],
    "difference_count": 2
  },
  "prompt_snapshot_before": {
    "positive": [],
    "negative": []
  },
  "prompt_snapshot_after": {
    "positive": [],
    "negative": []
  },
  "matched_rules": [],
  "generation_request_ref": null,
  "generation_result_ref": null,
  "selected_edge_id": null
}
```

## 8. Trace Record

`TraceRecord`는 사람이 넣은 논리와 시스템 변형을 분리해서 보여주기 위한 최소 단위다.

```json
{
  "trace_id": "trace.0003.002",
  "run_id": "run.2026-05-13T12-00-00",
  "frame_id": "frame.0003",
  "node_id": "node.quiet_scene",
  "phase": "before_generation",
  "rule_id": "rule.fix_seed_on_small_delta",
  "action_kind": "set_seed_policy",
  "input_digest": "sha256:...",
  "output_digest": "sha256:...",
  "prompt_delta": {
    "added_tags": [],
    "removed_tags": [],
    "negative_added": []
  },
  "policy_delta": {
    "seed.strategy": {
      "before": "random",
      "after": "fixed_from_previous"
    }
  },
  "warnings": []
}
```

## 9. Example: Linear Storyteller Cycle

```json
{
  "schema_version": 1,
  "kind": "naia.event_tree",
  "id": "event_tree.linear_storyteller",
  "name": "Linear Storyteller",
  "entry_node_id": "node.step_1",
  "engine_options": {
    "max_frames": 3,
    "stop_on_generation_error": true,
    "trace_level": "full",
    "random_seed": null
  },
  "variables": {},
  "safety": {
    "allow_raw_code": false,
    "require_trace": true,
    "unknown_action": "error",
    "unknown_condition_source": "error"
  },
  "nodes": [
    {
      "id": "node.step_1",
      "name": "Node 1",
      "kind": "event",
      "enabled": true,
      "selector": {
        "kind": "bucket",
        "source": "current_search",
        "rating": ["s", "q"],
        "include_tags": [],
        "exclude_tags": [],
        "pick": {
          "strategy": "random_without_replacement",
          "max_candidates": 100
        }
      },
      "prompt_policy": {
        "base": "source_row.general",
        "carry": {
          "clothes": "none",
          "background": "none",
          "characters": "none"
        },
        "wildcards": {
          "enabled": true,
          "preserve_sequential_counters": true
        }
      },
      "transition_policy": {
        "delta_from": "none",
        "rules": []
      },
      "generation_policy": {
        "mode": "txt2img",
        "seed": {
          "strategy": "random"
        },
        "reference": {
          "strategy": "none"
        },
        "resolution": {
          "strategy": "source_row_recommended"
        }
      },
      "children": [
        {
          "id": "edge.step_1.to.step_2",
          "to": "node.step_2",
          "priority": 100,
          "when": {
            "kind": "leaf",
            "source": "result.status",
            "op": "eq",
            "value": "success"
          },
          "fallback": true
        }
      ]
    },
    {
      "id": "node.step_2",
      "name": "Node 2",
      "kind": "event",
      "enabled": true,
      "selector": {
        "kind": "bucket",
        "source": "current_search",
        "rating": ["s", "q"],
        "include_tags": ["looking at viewer"],
        "exclude_tags": [],
        "pick": {
          "strategy": "random_without_replacement",
          "max_candidates": 100
        }
      },
      "prompt_policy": {
        "base": "source_row.general",
        "carry": {
          "clothes": "from_previous",
          "background": "from_previous",
          "characters": "from_previous"
        },
        "wildcards": {
          "enabled": true,
          "preserve_sequential_counters": true
        }
      },
      "transition_policy": {
        "delta_from": "previous_frame",
        "rules": [
          {
            "id": "rule.negative_removed_tags",
            "name": "Removed tags move to negative",
            "enabled": true,
            "priority": 100,
            "phase": "before_generation",
            "when": {
              "kind": "leaf",
              "source": "delta.removed_tags",
              "op": "not_empty",
              "value": null
            },
            "actions": [
              {
                "kind": "add_negative_from_delta_removed"
              }
            ]
          }
        ]
      },
      "generation_policy": {
        "mode": "txt2img",
        "seed": {
          "strategy": "random"
        },
        "reference": {
          "strategy": "none"
        },
        "resolution": {
          "strategy": "source_row_recommended"
        }
      },
      "children": []
    }
  ],
  "templates": {}
}
```

## 10. Implementation Shape

초기 구현은 UI보다 core 계약을 먼저 두는 것이 안전하다.

```text
core/event_tree/
  schema.py        # dataclass / TypedDict / schema constants
  validator.py     # tree invariant, known action/condition validation
  rule_engine.py   # structured condition evaluation + action dispatch
  run_controller.py
  trace.py

save/event_trees/
data/event_trees_bundled/
```

### Integration Points

- `SearchResultModel`: `selector.source == "current_search"`일 때 후보 row 공급.
- `PromptGenerationController`: v1에서는 `source_row_override`로 선택 row를 주입한다.
- `PromptProcessor`: prompt 조립과 기존 hook 실행을 담당한다.
- `Turbo Event Sequence EventSearcher`: `selector.source == "event_dataset"`일 때 재사용 후보.
- `Conditional Prompt` block model: condition/action editor UI 패턴을 참고하되, Event Tree용 condition source/action kind는 별도 화이트리스트로 둔다.

## 11. Open Decisions

1. Tree 저장 단위는 `save/event_trees/*.json`으로 시작한다.
2. v1 실행은 `single active run`만 지원한다. concurrent run은 v2.
3. branch condition은 `after_result` 이후 평가를 기본으로 한다. prompt-only branch가 필요하면 node option으로 `branch_phase: "after_prompt"`를 추가한다.
4. NSFW Turbo류 기능은 별도 hardcoded mode가 아니라 `template` 또는 bundled event tree로 표현한다.
5. UI는 먼저 JSON preview + dry-run trace viewer를 만들고, node graph editor는 나중에 붙인다.

## 12. MVP Implementation Strategy

처음부터 전체 Event Tree 엔진을 만들지 않는다. 계약은 확장 가능하게 유지하되, 구현은 NAIA 1.5 Storyteller/Turbo 스펙 중 선형 실행에 필요한 기능만 먼저 살린다.

축별 carry / delta / prompt assembly는 별도 계약 문서 `docs/EVENT_STREAM_AXIS_CONTRACT_2026_05_16.md`를 따른다. 이 문서는 raw prompt 문자열 carry 대신 `AxisSnapshot`, `AxisDelta`, `AxisCarryPolicy`를 사용한다.

### Phase 0: Legacy Spec Capture

목표는 1.5의 실제 동작을 2.0 용어로 고정하는 것이다.

| 1.5 개념 | 2.0 MVP 대응 |
|---|---|
| `storyteller` step dict | `LegacyStoryNodeSpec` |
| `storyteller_df[current]` | node별 `CompiledBucket` |
| `wildcard_preopen_repeat/current` | `LinearCycleState.total/current_index` |
| `event_current[index].add/rem/difference` | `AxisDelta` 기반 `EventDeltaSummary` |
| `event_option.fix_seed` | `SeedPolicy.fixed_when_delta_below` |
| `event_reorder_checkbox` | `LegacyDeltaTransform.enabled` |
| node별 `negative/cond/cond_neg/depth_search/resolution` | `NodePromptPolicy` |

### Phase 1: Linear Storyteller Runner

Directed Tree 전체가 아니라 단일 root에서 step을 순서대로 실행하는 runner를 만든다.

```text
LegacyStoryNodeSpec[]
  -> compile buckets
  -> pick row for current node
  -> resolve current AxisSnapshot
  -> apply AxisCarryPolicy against previous AxisSnapshot
  -> compute AxisDelta
  -> build PromptContext
  -> run PromptProcessor
  -> apply legacy delta transforms
  -> emit generation request
  -> advance current_index
```

이 단계에서 필요한 최소 기능:

- node별 bucket compile: rating/include/exclude 기반.
- node별 random row pick.
- node 순환: `0 -> 1 -> 2 -> ... -> end`.
- 현재/이전 축 상태 비교로 `AxisDelta` 생성.
- node별 negative, conditional positive, conditional negative 적용.
- node별 resolution override.
- 이전 node에서 제거된 action/expression/pose 계열 tag를 negative 후보에 넣는 legacy transform.
- delta 차이가 작을 때 seed 고정 옵션.
- trace log: selected row, delta, 적용된 legacy transform, generation request 요약.

이 단계에서 제외할 것:

- branch node.
- visual graph editor.
- arbitrary condition/action rule editor.
- raw expression.
- result 기반 retry branch.
- DAG merge.

### Phase 2: Legacy Turbo Randomized Compatibility

1.5 Turbo mode 3의 Randomized 성격을 MVP runner 위에 올린다. 단, NSFW hardcoded split 로직은 직접 이식하지 않고 event delta/reorder/reference 정책만 먼저 지원한다.

포함:

- parent/child event dataset에서 sequence 선택.
- node별 prompt difference 계산.
- `difference`가 큰 경우 reference/vibe 강도 약화.
- 생성 완료 후 reference list 갱신.
- max multivibe 개수 제한.
- 이전 prompt 반복 방지.

제외:

- `make_turbo_prompt()`의 고정 NSFW split tag recipe.
- transform line 기반 자동 후속 생성.
- inpaint/reopen 자동화.

### Phase 3: Directed Tree Activation

Linear runner의 `LegacyStoryNodeSpec`를 정식 `NodeSpec`로 승격한다. 이때 기존 MVP 자료 구조는 폐기하지 않고 tree의 subset으로 해석한다.

```text
LegacyStoryNodeSpec[] -> EventTreeDocument
node[i].next = node[i + 1]
last node = terminal
```

추가:

- `children[]` edge 평가.
- structured condition evaluator.
- fallback edge.
- `after_result` branch phase.
- dry-run validator.

### Phase 4: Human Logic Editor

사람이 직접 논리를 결합하는 UI는 마지막에 붙인다. 초기에는 JSON/preview 기반으로 충분하다.

추가:

- transition rule list editor.
- condition block editor.
- action whitelist editor.
- per-frame trace viewer.
- legacy import/export.

## 13. MVP File Shape

초기 구현 파일은 전체 `core/event_tree`보다 더 좁게 시작해도 된다.

```text
core/event_tree/
  axis_schema.py         # AxisTag, AxisSnapshot, AxisDelta, AxisCarryPolicy
  axis_resolver.py       # source/preset/cooccurrence -> axis tags
  axis_carry.py          # previous + current + policy -> next snapshot
  axis_assembler.py      # AxisSnapshot -> PromptContext input tags
  legacy_schema.py       # LegacyStoryNodeSpec, LinearCycleState
  legacy_compiler.py     # 1.5-style step spec -> compiled buckets
  legacy_runner.py       # linear execution only
  trace.py               # MVP trace record
```

나중에 tree 기능이 켜질 때 `schema.py`, `validator.py`, `rule_engine.py`, `run_controller.py`를 추가한다.

## 14. MVP Success Criteria

- NAIA 1.5 Storyteller의 node별 bucket 순환을 2.0에서 재현할 수 있다.
- 한 node의 선택 row, axis snapshot, axis delta, negative 변경이 trace로 보인다.
- 기존 랜덤 생성의 `pop_random_row()` 경로를 직접 오염시키지 않는다.
- `PromptProcessor`는 계속 최종 prompt 조립을 담당한다.
- Directed Tree 확장을 위해 MVP data model을 버리지 않아도 된다.

## 15. MVP Execution Checklist

이 체크리스트는 Phase 1 Linear Storyteller Runner를 실제 구현 단위로 자른다. 12장의 Phase 범위와 충돌하면 12장과 `docs/EVENT_STREAM_AXIS_CONTRACT_2026_05_16.md`를 우선한다.

### C-ES-01: Prompt Tool Entry Point

- [ ] Remote Web `[프롬프트 도구]` 안에 `이벤트 스트림 설정`과 `이벤트 스트림 활성`을 유지한다.
- [ ] `이벤트 스트림 활성`은 runtime flag만 바꾼다.
- [ ] `이벤트 스트림 설정`은 작은 runtime monitor가 아니라 Event Stream Builder를 연다.
- [ ] Event Stream 활성 중 wildcard, character prompt, prompt engineering side effect는 freeze된다.
- [ ] 활성화 실패, validate 실패, empty bucket은 toast 또는 panel 상태로 명확히 보인다.

### C-ES-02: Event Stream Builder MVP

- [ ] Builder는 node list와 selected node inspector를 제공한다.
- [ ] Node 추가, 삭제, 이름 변경, 순서 변경을 지원한다.
- [ ] Node inspector는 rating, include tags, exclude tags, resolution policy를 편집한다.
- [ ] Node inspector는 MVP carry toggle로 `apparel`, `scene`만 노출한다.
- [ ] Builder는 node별 candidate count와 preview를 보여준다.
- [ ] `Validate Node`, `Validate All` 액션을 제공한다.
- [ ] 모든 enabled node가 validate되기 전에는 compiled run을 활성화하지 않는다.

### C-ES-03: Legacy Node Contract

- [ ] `LegacyStoryNodeSpec`는 `storyteller` step dict의 MVP subset을 표현한다.
- [ ] `storyteller_df[current]` 대응은 node별 `CompiledBucket`으로 둔다.
- [ ] `wildcard_preopen_repeat/current` 대응은 `LinearCycleState.total/current_index`로 둔다.
- [ ] Node selector는 rating/include/exclude 기반으로 bucket을 compile한다.
- [ ] Node prompt policy는 negative, conditional positive, conditional negative, resolution override를 표현할 수 있다.
- [ ] MVP settings 저장은 draft spec 중심으로 하고, heavy DataFrame payload는 저장하지 않는다.

### C-ES-04: Linear Runtime

- [ ] Runtime은 compiled nodes만 실행한다.
- [ ] Runtime은 `0 -> 1 -> 2 -> ... -> end -> 0` 순서로 순환한다.
- [ ] 각 frame은 current node에서 row를 하나 선택한다.
- [ ] 선택 row가 없으면 generation을 진행하지 않고 명확한 error state를 남긴다.
- [ ] Runtime은 기존 random prompt 경로를 직접 변형하지 않고 request override/context metadata로 연결한다.
- [ ] `PromptProcessor`는 최종 prompt assembly 권한을 계속 가진다.

### C-ES-05: Axis Carry MVP

- [ ] Node 간 carry는 raw prompt string이 아니라 `AxisSnapshot`과 `AxisCarryPolicy`로 계산한다.
- [ ] MVP는 `apparel`, `scene`, `action_bundle`, `expression`, `pose`, `gesture`, `interaction`, `camera`, `misc` 축을 trace 가능한 형태로 둔다.
- [ ] 첫 carry UI는 `apparel`, `scene`만 직접 노출한다.
- [ ] `apparel`은 node override가 없으면 유지된다.
- [ ] `scene`은 새 location/background가 없으면 유지된다.
- [ ] `action_bundle`, `pose`, `gesture`, `interaction`, `expression`은 기본적으로 node마다 교체된다.
- [ ] removed action/expression/pose 계열 tag만 negative 후보가 된다.
- [ ] removed apparel은 기본 negative 후보가 아니다.
- [ ] unknown tag는 `misc`로 가고 기본 carry되지 않는다.

### C-ES-06: Trace and Validation

- [ ] Trace는 run id, frame index, node id, selected row를 기록한다.
- [ ] Trace는 axis snapshot, axis delta, negative candidate summary를 기록한다.
- [ ] Trace는 최종 generation request 요약을 기록한다.
- [ ] Builder preview와 runtime trace는 같은 compiled node spec을 기준으로 한다.
- [ ] UI refresh 후에도 draft/compiled/active 상태가 구분되어 보인다.

### C-ES-07: Explicitly Deferred

- [ ] Branch node는 MVP에서 구현하지 않는다.
- [ ] Directed Tree visual graph editor는 MVP에서 구현하지 않는다.
- [ ] Arbitrary condition/action rule editor는 MVP에서 구현하지 않는다.
- [ ] Legacy Turbo `make_turbo_prompt()` hardcoded NSFW recipe는 이식하지 않는다.
- [ ] Vibe/reference image 자동 누적은 MVP에서 구현하지 않는다.
- [ ] Inpaint/reopen 자동화는 MVP에서 구현하지 않는다.
- [ ] Legacy import/export 전체 호환은 MVP에서 구현하지 않는다.

## 16. When Done

MVP는 아래 조건을 모두 만족할 때 완료로 본다.

- [ ] 사용자가 Builder에서 2개 이상의 node를 만들고 validate할 수 있다.
- [ ] `이벤트 스트림 활성`을 켜면 compiled node sequence가 random prompt 버튼에서 순환 실행된다.
- [ ] 활성 중 wildcard, character prompt, prompt engineering side effect가 freeze되는 것이 확인된다.
- [ ] Node별 rating/include/exclude가 실제 candidate bucket에 반영된다.
- [ ] Node별 resolution override가 generation request에 반영된다.
- [ ] `apparel`, `scene` carry가 raw prompt string mutation 없이 axis 단위로 적용된다.
- [ ] Empty bucket, invalid node, missing compiled run은 generation 전에 차단된다.
- [ ] Runtime trace에서 selected row, axis delta, negative candidate, generation request summary를 확인할 수 있다.
- [ ] 기존 Event Preset, Clothes Preset, Expression Preset, Conditional Prompt 동작을 깨지 않는다.
- [ ] 관련 unit test와 좁은 Remote Web smoke test가 통과한다.
