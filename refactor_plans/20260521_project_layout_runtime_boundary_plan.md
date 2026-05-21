# Plan - Project Layout and Runtime Boundary Stabilization

## Goal

NAIA2의 기준 제품 경로를 `Python Headless Web`으로 고정하고, Electron은 선택적 desktop shell/release path로 격리한다. PyQt6 Desktop은 reference/quarantine으로 유지하되 새 기능 기준선으로 사용하지 않는다.

이번 계획의 핵심은 대규모 재작성이나 즉시 삭제가 아니다. 먼저 프로젝트 경계, canonical source path, runtime/build 산출물 위치, 검증 gate를 고정해서 이후 정리를 작고 안전한 move-only round로 수행할 수 있게 만드는 것이다.

## Product Runtime Decision

기준 실행 모델:

- 기본 제품: Python + FastAPI + Remote Web.
- 기본 사용자 요구사항: Python 설치와 pip dependency 설치.
- 기본 실행: `NAIA_web_headless.py`, `run_NAIA_web.bat`, `run_NAIA_web.command`.
- 선택 제품: Electron shell. 같은 Python backend와 같은 Remote Web UI를 감싸는 release/portable shell이다.
- 참조 제품: Legacy PyQt6/QWebApplication Desktop. 기능 이식 reference이며 product baseline이 아니다.

## Execution Protocol

Every round in this plan must follow the same execution pattern:

- Plan review: confirm the current round, current worktree status, and active runtime boundary before editing.
- Gate setup: add or reuse manifest-backed checks before declaring a boundary stable.
- Implementation: change only the owner surface named by the round.
- Modification: repair failed checks inside the same round before broadening scope.
- Deletion: delete only from a reviewed candidate group with explicit approval and required gates.
- Verification: run focused tests, the round checker, static review, and `git diff --check`.
- Post-work evaluation: compare the result against When Done, record deferred items, and confirm source/runtime artifacts were not staged.
- Commit: stage only intended files and create a round-scoped commit when the user has requested commit-level completion.

## Implementation Status - 2026-05-21

First executable slice completed:

- `PROJECT_LAYOUT_POLICY.md` added as the layout/runtime ownership policy.
- `release_assets/manifests/project_layout_policy.json` added as the machine-readable policy contract.
- `tools/check_project_layout_policy.py` added as the layout/runtime boundary gate.
- `tests/test_project_layout_policy.py` added.
- `AGENTS.md` updated to point layout/runtime work at the policy and checker.
- `release_assets/manifests/remote_web_feature_contract.json` updated to include install-manager routes.

Round 0 through Round 9 completion evidence added:

- `release_assets/manifests/project_layout_round_completion.json` records Round 0~9 evidence.
- `release_assets/manifests/project_cleanup_candidates.json` records non-destructive cleanup/delete candidates.
- `tools/check_project_layout_round_completion.py` validates that Round 0~9 evidence is complete.
- `tools/check_project_cleanup_candidates.py` validates that cleanup candidates require explicit delete approval.
- `tests/test_project_layout_round_completion.py` and `tests/test_project_cleanup_candidates.py` cover those gates.

Round completion status:

| Round | Status | Evidence Boundary |
| --- | --- | --- |
| 0 | Complete | Baseline product/runtime policy fixed to Python Headless Web. |
| 1 | Complete | Human and machine-readable project layout policy added. |
| 2 | Complete | Canonical Remote Web source fixed to `app/web/remote`. |
| 3 | Complete | Electron documented and gated as optional shell/release path. |
| 4 | Complete | Runtime/generated roots quarantined through manifests and gates. |
| 5 | Complete | PyQt6 Desktop frozen as reference/quarantine path. |
| 6 | Complete as policy gate | Move-only rule and source layout contract are active; broad source moves are deferred to focused ownership rounds. |
| 7 | Complete | Layout, source, headless, remote feature, runtime asset, and runtime write gates are wired. |
| 8 | Complete | Clone-user, release-user, and maintainer paths are split in release manifests. |
| 9 | Complete non-destructively | Cleanup/delete candidates are inventoried; actual deletion is deferred until explicit approval by candidate group. |

Known remaining cleanup candidates:

- Root-level `main.cjs` was removed in the first cleanup step after confirming `app/electron/main/main.cjs` is the active Electron main source.
- The older `ui/remote_web` source directory was removed after direct test references moved to `app/web/remote` and the Remote Web contract stopped listing it as a compatibility static source.
- Runtime/local state directories and sample/debug assets are excluded or listed as cleanup candidates. They are not deleted automatically.

Current execution-pattern gate:

- `release_assets/manifests/refactor_plan_execution_contract.json` records active executable refactor plans.
- `tools/check_refactor_plan_execution_contract.py` validates gate setup, implementation, modification, deletion, verification, static review, post-work evaluation, and commit handling coverage.
- `tests/test_refactor_plan_execution_contract.py` covers current success and contract failure cases.

명시적 비목표:

- 일반 clone 사용자가 npm, Electron, Docker를 요구받게 만들지 않는다.
- Electron을 새 main app architecture로 승격하지 않는다.
- PyQt6 Desktop을 기능 parity 확인 전에 급하게 삭제하지 않는다.
- 폴더를 예쁘게 보이게 하려고 기능 변경과 파일 이동을 섞지 않는다.

## Post-Work Evaluation

After each round:

- Confirm the round's When Done conditions are satisfied or explicitly blocked.
- Confirm whether the round changed product behavior, layout policy, release policy, deletion candidates, or only validation/docs.
- Confirm deletion work was candidate-scoped and approval-gated.
- Confirm runtime/generated artifacts remain ignored and unstaged.
- Record the validation commands that passed and any deferred gate.

## Target Layout Policy

목표 경계:

```text
NAIA2.0/
  core/                  # Python domain/service core, PyQt-free headless runtime
  app/
    backend/             # optional shell/launcher backend adapter
    web/remote/          # canonical Remote Web UI source
    electron/            # optional Electron shell only
  legacy_desktop/        # PyQt6 reference/quarantine only
  release_package/       # reusable packaging scripts/templates/docs
  release_assets/        # manifests/contracts/release gates
  tests/
    headless/
    electron_shell/
    legacy_desktop/
```

## Round 0 - Baseline Freeze

### Goal

현재 상태를 더 흐트러뜨리지 않기 위해 실행 경로와 변경 금지선을 먼저 고정한다.

### Checklist

- [ ] 기본 실행 경로를 `Python Headless Web`으로 선언한다.
- [ ] Electron을 optional shell/release path로 선언한다.
- [ ] PyQt6 Desktop을 reference/quarantine으로 선언한다.
- [ ] 새 기능 수정은 `core` + canonical Remote Web source + headless FastAPI path에만 적용한다.
- [ ] dirty tree에서 build/runtime/generated artifact와 source change를 분리해 목록화한다.

### When Done

- 새 작업을 시작할 때 "기준 앱이 PyQt인지 Electron인지 Web인지" 혼동하지 않는다.
- npm/Electron/Docker는 일반 clone 실행 요구사항이 아니라 release maintainer path로만 문서화된다.
- 이후 라운드가 기능 변경인지 move-only cleanup인지 명확히 구분된다.

## Round 1 - Project Layout Policy Document

### Goal

프로젝트 경로 정책을 문서로 고정하고, 사람과 agent가 같은 기준으로 파일을 배치하게 한다.

### Checklist

- [ ] `PROJECT_LAYOUT_POLICY.md` 또는 동등 문서를 작성한다.
- [ ] `core`, `app/backend`, `app/web/remote`, `app/electron`, `legacy_desktop`, `release_package`, `release_assets`, `tests/*`의 역할을 명시한다.
- [ ] root에 새 runtime/build/generated directory를 만들지 않는 규칙을 명시한다.
- [ ] Electron 관련 파일은 `app/electron` 또는 `release_package` 아래로 제한한다.
- [ ] Web UI canonical source를 하나로 지정한다.

### When Done

- 새 파일을 어디에 둬야 하는지 문서만 보고 판단할 수 있다.
- `app/`가 혼란 요소가 아니라 optional app layer임이 명확해진다.
- layout 정책 위반을 검사 스크립트로 만들 수 있을 만큼 규칙이 구체적이다.

## Round 2 - Canonical Remote Web Source

### Goal

`ui/remote_web`와 `app/web/remote`의 중복 상태를 정리하고 canonical Web UI source를 하나로 고정한다.

### Checklist

- [ ] 현재 서버가 실제로 서빙하는 Remote Web path를 확인한다.
- [ ] canonical source를 `app/web/remote`로 둘지, 기존 `ui/remote_web`를 유지할지 최종 결정한다.
- [ ] 비-canonical path는 mirror, compatibility shim, delete candidate 중 하나로 분류한다.
- [ ] Web UI 수정 규칙을 AGENTS 또는 layout policy에 반영한다.
- [ ] cache busting, static route, Electron shell load path가 canonical path를 사용하도록 맞춘다.

### When Done

- Web UI 수정 시 같은 변경을 두 디렉터리에 중복 적용하지 않는다.
- FastAPI source mode와 Electron shell mode가 같은 Web UI artifact를 사용한다.
- 비-canonical Web UI path의 역할이 명시되어 있다.

## Round 3 - Optional Electron Boundary

### Goal

Electron을 선택적 shell로 격리하고, 일반 clone 사용자의 Python Web 실행 경로에서 npm 의존을 제거한다.

### Checklist

- [ ] Electron shell source는 `app/electron` 아래로만 둔다.
- [ ] Electron packaging/build helper는 `release_package` 아래로 둔다.
- [ ] 일반 실행 문서에서 npm install을 요구하지 않는다.
- [ ] Electron build 문서에는 npm, Node, optional Docker/CI 사용 조건을 별도로 명시한다.
- [ ] Electron shell이 backend lifecycle, maintenance view, logs, data folder open, app window만 담당하도록 범위를 제한한다.

### When Done

- `git clone -> Python setup -> Web 실행` 경로가 Electron 없이 동작한다.
- Electron artifact가 없어도 Remote Web 기능이 줄어들지 않는다.
- Electron은 같은 backend와 같은 web artifact를 감싸는 shell로만 남는다.

## Round 4 - Runtime Data and Generated Artifact Quarantine

### Goal

source tree와 runtime/user/build data를 분리해서 프로젝트 경로가 다시 오염되지 않게 한다.

### Checklist

- [ ] `logs`, `output`, `user-data`, `portable-workspace`, build output, `node_modules`, generated cache를 source policy에서 제외한다.
- [ ] release/package artifact output root를 명확히 정한다.
- [ ] downloaded data는 runtime root 또는 user data root로만 이동한다.
- [ ] source checkout compatibility fallback과 packaged runtime behavior를 분리한다.
- [ ] `.gitignore`, release manifest, runtime path resolver가 같은 정책을 따르게 한다.

### When Done

- clean source tree에는 제품 source와 reviewed bootstrap/sample만 남는다.
- first run download/cache/output이 source layout 판단을 흐리지 않는다.
- packaged release가 개발자의 local data를 우연히 포함하지 않는다.

## Round 5 - Legacy PyQt6 Reference Freeze

### Goal

PyQt6/QWebApplication Desktop을 삭제 전에 reference-only 상태로 고정한다.

### Checklist

- [ ] `legacy_desktop`의 역할을 migration reference로 문서화한다.
- [ ] 새 기능과 bug fix가 legacy desktop path로 들어가지 않게 한다.
- [ ] headless runtime에서 `legacy_desktop` 또는 PyQt runtime import가 발생하지 않도록 gate를 유지한다.
- [ ] Desktop-only tests는 `tests/legacy_desktop` 또는 explicit legacy manifest로 분리한다.
- [ ] 아직 WebSession에 이식되지 않은 feature는 delete candidate가 아니라 migration candidate로 표시한다.

### When Done

- PyQt6 Desktop은 active product code로 취급되지 않는다.
- legacy code가 남아 있어도 headless/runtime dependency를 오염시키지 않는다.
- 삭제 여부는 기능 parity gate 이후에만 판단된다.

## Round 6 - Move-Only Source Reorganization

### Goal

기능 변경 없이 파일 위치와 import 경계만 정리한다.

### Checklist

- [ ] 한 라운드에서는 한 ownership group만 이동한다.
- [ ] move-only round에서는 behavior change, bug fix, new feature를 금지한다.
- [ ] compatibility import shim은 한 라운드만 유지하고 다음 라운드에서 제거한다.
- [ ] 이동 전후 focused tests와 import smoke를 실행한다.
- [ ] 이동된 경로를 release manifest와 test path에 반영한다.

### When Done

- 파일 위치만 바뀌었고 사용자-visible behavior는 동일하다.
- import path가 target layout policy와 일치한다.
- 회귀가 발생하면 해당 ownership group 단위로 되돌릴 수 있다.

## Round 7 - Contract Gates

### Goal

정리 작업을 사람의 기억이 아니라 검사 스크립트로 통제한다.

### Checklist

- [ ] layout policy gate를 추가한다.
- [ ] headless core boundary gate를 유지한다.
- [ ] Remote Web route/feature contract gate를 유지한다.
- [ ] runtime asset classification gate를 유지한다.
- [ ] Electron optional shell gate를 추가하거나 기존 release gate에 반영한다.
- [ ] source mode와 packaged mode smoke matrix를 분리한다.

### When Done

- 잘못된 위치에 새 파일이 생기면 CI 또는 local check에서 잡힌다.
- Electron 관련 변경이 기본 Python Web 실행 경로를 침범하면 잡힌다.
- runtime/generated data가 release source에 섞이면 잡힌다.

## Round 8 - Release Path Simplification

### Goal

일반 사용자와 release maintainer의 설치/실행 경험을 분리해서 문서와 packaging을 단순화한다.

### Checklist

- [ ] 일반 clone 사용자 문서: Python setup + headless web 실행만 설명한다.
- [ ] release 사용자 문서: portable app 실행과 first-run installer flow만 설명한다.
- [ ] release maintainer 문서: Electron/npm/build/runtime staging을 별도 설명한다.
- [ ] Docker는 optional reproducible build/CI 후보로만 문서화한다.
- [ ] packaged release에는 reviewed bootstrap/sample과 installer만 포함한다.

### When Done

- 사용자는 자신이 clone user인지 portable release user인지 헷갈리지 않는다.
- maintainer-only build dependency가 일반 사용자 설치 절차에 나타나지 않는다.
- release package가 source tree 구조를 오염시키지 않는다.

## Round 9 - Cleanup and Delete Candidates

### Goal

경계와 gate가 안정된 뒤 실제 중복/죽은 코드를 제거한다.

### Checklist

- [ ] delete candidate list를 owner, replacement, test gate와 함께 만든다.
- [ ] 비-canonical Web UI path 제거 또는 mirror 자동화 제거를 결정한다.
- [ ] root-level Electron/packaging residue를 제거한다.
- [ ] runtime/generated artifact를 source tree 밖으로 이동하거나 ignore 처리한다.
- [ ] legacy desktop 삭제는 WebSession feature parity gate 통과 후 별도 결정한다.

### When Done

- 삭제는 정책과 gate에 근거해 수행된다.
- 기본 Python Headless Web 실행이 유지된다.
- optional Electron release shell 실행이 유지된다.
- supported WebSession 기능이 회귀하지 않는다.

## First Implementation Slice

다음 구현은 Round 1과 Round 2를 먼저 수행한다.

1. `PROJECT_LAYOUT_POLICY.md` 작성.
2. canonical Remote Web source 결정.
3. layout policy check script 초안 작성.
4. Electron/npm이 기본 실행 경로에 들어오지 않는지 검사.
5. 문서와 gate만 먼저 통과시킨 뒤 파일 이동은 별도 move-only round로 진행.
