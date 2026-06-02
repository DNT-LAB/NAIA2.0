---
name: naia-release
description: Build and publish a NAIA Electron portable release (Windows) to GitHub. Use when the user asks to cut/ship/publish a new NAIA version, run the release/deploy process, or bump+build+publish. Codifies the validated gate→artifacts→verify→publish flow on the future02 branch, the version-bump SSOT, and every hard-won build gotcha.
disable-model-invocation: false
user-invocable: true
allowed-tools: Bash, Read, Write, Edit, Grep, Glob, AskUserQuestion
argument-hint: [target version, e.g. 2.0.13]
---

# naia-release — NAIA Electron portable release

Ship a Windows portable release of NAIA to GitHub Releases. Branch is **`future02`**; assets are **`NAIA-Portable.zip` + `SHA256SUMS.txt` only**. Publishing as `--latest` is **irreversible** (existing installs auto-update since 2.0.4) — confirm before that step.

> Run the phases in order. Do NOT skip the version bump, the `release_ready` check, the **zip-internal version verification**, or the `--latest` confirmation.

---

## Phase 0 — Pre-flight
1. Confirm branch: `git rev-parse --abbrev-ref HEAD` → must be `future02`.
2. Make sure all intended changes are committed (`git status --short`). Untracked files you didn't create (e.g. `tools/codex_image_exec_smoke.py`) stay untracked — don't add them. Tests under `tests/` are gitignored.
3. Decide the target version `X.Y.Z` (the user usually says it, or it's the next patch). The previous version is the current `package.json` value: `grep '"version"' app/electron/package.json`.

## Phase 1 — Version bump (6 SSOT files) → commit
The version + UA strings live in **exactly six files**. Bump `OLD` → `NEW`:
```bash
OLD=2.0.11 NEW=2.0.12   # set these
for f in __init__.py app/electron/package.json app/electron/package-lock.json \
         core/artist_thumbnail_service.py core/event_preset_download_service.py \
         core/runtime_install_manager.py; do
  sed -i "s/${OLD//./\\.}/$NEW/g" "$f"
done
# verify: no stray OLD left in those 6 files, JSON still valid
grep -l "$OLD" __init__.py app/electron/package.json app/electron/package-lock.json \
  core/artist_thumbnail_service.py core/event_preset_download_service.py core/runtime_install_manager.py || echo "clean"
python -c "import json; json.load(open('app/electron/package.json')); json.load(open('app/electron/package-lock.json')); print('json ok')"
```
What each file holds (so you can sanity-check the diff):
- `__init__.py` — `__version__ = "X"` **and** `'User-Agent': 'NAIA/X (https://github.com/naia-project)'`
- `app/electron/package.json` — `"version": "X"`
- `app/electron/package-lock.json` — **two** `"version": "X"` (root + `packages[""]`)
- `core/artist_thumbnail_service.py` — `"NAIA/X ArtistThumb Headless"`
- `core/event_preset_download_service.py` — `"NAIA/X EventPreset Module"` **and** `"NAIA/X EventPreset Thumbnail"`
- `core/runtime_install_manager.py` — `"NAIA/X RuntimeInstallManager"`

Commit as its own commit (repo convention):
```bash
git add __init__.py app/electron/package.json app/electron/package-lock.json \
  core/artist_thumbnail_service.py core/event_preset_download_service.py core/runtime_install_manager.py
git commit -m "Bump version $OLD -> $NEW

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```
(Feature/fix commits should already exist; the bump is the last commit before building.)

## Phase 2 — Build gate (the comprehensive release gate)
Run the canonical gate. **Run it as the SOLE command in a background shell** (no trailing `; echo; tail`) — otherwise the background exit code is the trailing command's, masking a real gate failure as "exit 0".
```bash
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 python tools/run_final_electron_release_gate.py \
  --execute --build-clean-python-runtime --python-runtime-version 3.12 \
  --require-bundled-python --run-electron-cdp --electron-timeout 600 \
  --defender-scan --require-defender-scan > /tmp/naia_build.log 2>&1
```
- `--electron-timeout 600` is REQUIRED (the script default 180 is too short; tag-data DL ~346 s).
- ~10 min. On exit 0, confirm: `grep -m1 '"release_ready": true' /tmp/naia_build.log`.
- **Do NOT run concurrent builds** (`app/electron/dist` conflict).

### CDP-smoke flake (common, transient — NOT a regression)
Symptom: build fails with `TimeoutError: CDP target not available: <urlopen error timed out>` from `smoke_electron_cdp._wait_for_target` (polls `127.0.0.1:9336/json/list`). The build itself succeeded (backend reached generation); only the CDP target wait timed out under machine load.
- Diagnose: confirm `main.cjs`/CDP path unchanged vs the last passing build (then it's not a regression). Check nothing is bound to `9336` and there's no leftover build Electron (distinguish from the user's portable `NAIA.exe` and the cTerm terminal `electron.exe` — **never kill those**).
- Fix: **retry on a clean machine.** Ask the user to close the running portable + other heavy apps; competing Electron instances starve the CDP startup. It typically passes on a clean retry (seen 2 flakes → pass).

## Phase 3 — Artifacts
```bash
PYTHONUTF8=1 python tools/prepare_github_release_artifacts.py --require-final-gate --force
```
- Output dir: `app/electron/dist/github-release/`. Expect `violations: []`.
- Keep only **`NAIA-Portable.zip` + `SHA256SUMS.txt`**; the script also emits evidence `.json`/`.md` and a `GITHUB_RELEASE_BODY.md` — **exclude those from the release** (user preference).

## Phase 4 — VERIFY the zip's internal version (do NOT skip)
`app/electron/dist/win-unpacked` is **STALE** — it can show an ancient version (e.g. `2.0.3`) and the gate does NOT use it (it builds in a temp workspace `…/Temp/claude/naia-electron-portable-*`). Verify the **actual zip**:
```bash
GH=app/electron/dist/github-release
unzip -p "$GH/NAIA-Portable.zip" "NAIA-Portable/resources/app.asar" > /tmp/zip.asar
rm -rf /tmp/zip_x && npx --yes asar extract /tmp/zip.asar /tmp/zip_x
grep -m1 '"version"' /tmp/zip_x/package.json          # MUST equal target X.Y.Z
# also confirm the headline fix/feature marker is present, e.g.:
# grep -c "<some new IPC / string>" /tmp/zip_x/main/main.cjs
cat "$GH/SHA256SUMS.txt"                               # zip sha for the release notes
```
If the version is wrong, STOP — do not publish.

## Phase 5 — Push
```bash
git push origin future02
```
(`gh release create --target future02` tags the **remote** tip, so the commit must be pushed first.)

## Phase 6 — Confirm `--latest` (irreversible)
`--latest` makes every existing install auto-update. Confirm with the user (AskUserQuestion: publish now / draft+prerelease first / hold) unless they've just explicitly authorized this exact publish.

## Phase 7 — Publish
Write concise notes (feature/fix highlights + download + expected SHA-256 + unsigned-Windows notice), then:
```bash
gh release create vX.Y.Z --target future02 --latest \
  --title "NAIA X.Y.Z" \
  --notes-file <notes.md> \
  app/electron/dist/github-release/NAIA-Portable.zip \
  app/electron/dist/github-release/SHA256SUMS.txt
```
Pre-check no clash: `gh release view vX.Y.Z` should be "release not found".

## Phase 8 — Verify + record
```bash
gh release view vX.Y.Z --json tagName,isDraft,isPrerelease,targetCommitish,assets \
  --jq '{tag:.tagName,draft:.isDraft,prerelease:.isPrerelease,target:.targetCommitish,assets:[.assets[].name]}'
git ls-remote --tags origin vX.Y.Z          # tag → expected commit
gh release list --limit 3                    # the new one shows "Latest"
```
Expect: tag→bump commit, `draft/prerelease=false`, exactly the 2 assets, marked Latest.
Then update memory: `MEMORY.md` "현재 Latest" line + add a `project_release_history.md` entry (version, sha, commits, gotchas).

---

## Gotchas checklist (each cost a debugging cycle)
- **Background exit-code masking** → run the build gate as a SOLE command.
- **CDP smoke flake** (`9336` urlopen timeout) → transient machine load; retry on a clean machine; not a regression if `main.cjs`/CDP path unchanged.
- **`win-unpacked` is stale** → verify the version **inside the zip's `app.asar`**, never `dist/win-unpacked`.
- **Assets = zip + SHA256SUMS only** (exclude evidence json/md).
- **`--latest` is irreversible** (auto-update) → confirm before publishing.
- **Never broad-kill processes** during a build: the user's portable is `NAIA.exe` (cmdline under the portable path), the terminal is `electron.exe` under `C:\AI\cTerm`, the build's Electron lives under `…/Temp/claude/naia-electron-portable-*`. Kill only a precisely-identified leftover, by PID.
- **Updating a local portable via robocopy** (if asked): `/MIR /XD` mis-detects EXTRA dirs under a Korean locale (output is localized) → risks deleting `user-data` (~15 GB). Prefer a manual `cp` loop that skips `user-data`, and confirm its size before/after.

## Appendix — asar hot-patch (test a fix before a full build)
The portable's Electron main lives **inside `resources/app.asar` (packed)**, identical 1:1 to the source `app/electron/{main/main.cjs, preload/preload.cjs}`. The Python backend (`resources/naia-backend/`) is **loose**.
- **Loose files** (backend `.py`, `app/web/remote/**`): `cp` straight into `resources/naia-backend/<same path>`; frontend = reload, backend `.py` = restart the portable.
- **main.cjs / preload.cjs**: repack the asar (`asar` v3.2.0 is available):
  ```bash
  ASAR=<portable>/resources/app.asar
  cp "$ASAR" "$ASAR.bak"
  rm -rf /tmp/x && npx --yes asar extract "$ASAR" /tmp/x
  cp app/electron/main/main.cjs /tmp/x/main/main.cjs
  cp app/electron/preload/preload.cjs /tmp/x/preload/preload.cjs
  npx --yes asar pack /tmp/x "$ASAR"
  npx --yes asar extract "$ASAR" /tmp/verify && grep -c "<new marker>" /tmp/verify/main/main.cjs
  ```
  Then fully restart the portable. The official build packs a clean asar from source, so this repack is for pre-build testing only; the user can delete `app.asar.bak` after confirming.
