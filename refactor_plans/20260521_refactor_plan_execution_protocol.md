# Refactor Plan Execution Protocol

## Goal

Make active refactor plans executable in a repeatable round pattern instead of leaving them as informal intent documents.

## Protocol

Every active refactor round follows this order:

1. Plan review.
2. Gate setup or gate reuse.
3. Implementation.
4. Modification and rework if verification finds a gap.
5. Deletion only from an approved candidate group.
6. Verification and static review.
7. Post-work evaluation.
8. Targeted staging and commit when the round calls for a commit.

## Gate Setup

- Add or reuse a machine-readable manifest for the round's contract.
- Add or reuse a checker that prints JSON and exits non-zero on violations.
- Add focused tests for both current success and at least one failure case.
- Link new gates from release or layout policy manifests when the gate protects a shared boundary.

## Implementation

- Keep implementation scoped to the round's owner and When Done conditions.
- Keep source moves separate from behavior changes unless the plan explicitly allows a combined change.
- Preserve the default Python Headless Web path and optional Electron shell boundary.

## Modification

- Treat verification failures as required follow-up work inside the same round.
- Keep fixes narrow and re-run the failed gate before widening validation.
- Do not broaden the round because a nearby cleanup looks convenient.

## Deletion

- Delete only from a reviewed candidate group with owner, replacement, and required gates.
- Do not delete runtime/user data automatically.
- Do not delete legacy Desktop code until parity and explicit approval gates pass.

## Verification

- Run the round-specific checker.
- Run focused tests for changed code.
- Run static review on the changed contract and checker logic.
- Run `git diff --check` on the intended files before committing.

## Post-Work Evaluation

- Confirm whether the When Done conditions are satisfied.
- Report any intentionally deferred item and the gate that blocks it.
- Confirm whether the work changed product behavior, layout policy, release policy, or deletion candidates.
- Confirm that runtime/generated artifacts are not staged.

## When Done

- Active plans have a repeatable execution protocol.
- Gate setup, implementation, modification, deletion, verification, static review, post-work evaluation, and commit handling are represented.
- The protocol is enforced by `tools/check_refactor_plan_execution_contract.py`.
