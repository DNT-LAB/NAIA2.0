# Round 39 cutover review

Generated: 2026-05-19

## Measurement commands

Desktop-backed WebShell:

```powershell
python tools\measure_web_session_startup.py --entrypoint desktop --port 7292 --cdp-port 9392 --include-generate --startup-timeout 240 --browser-timeout 90 --action-timeout 120 --output-json logs\round39_desktop_measurement.json --write-summary refactor_docs\round_39_desktop_measurement.md
```

Headless Remote Web:

```powershell
python tools\measure_web_session_startup.py --entrypoint headless --port 7291 --cdp-port 9391 --include-generate --output-json logs\round39_headless_measurement.json --write-summary refactor_docs\round_39_headless_measurement.md
```

The headless measurement disables actual image API execution only for the dispatch timing measurement with `NAIA_HEADLESS_DISABLE_GENERATION_EXECUTION=1`. Real result execution was separately validated by CDP in Round 36.

## Timing comparison

| Metric | Desktop-backed | Headless | Change |
| --- | ---: | ---: | ---: |
| FastAPI listen | 11.438s | 1.438s | -10.000s |
| `/api/status` 200 | 11.469s | 1.485s | -9.984s |
| Remote Web first paint | 14.188s | 2.360s | -11.828s |
| Random click to prompt update | 3.641s | 6.062s | +2.421s |
| Generate click to dispatch | 0.204s | 0.094s | -0.110s |

## RSS comparison

| Checkpoint | Desktop-backed | Headless | Change |
| --- | ---: | ---: | ---: |
| After listen | 1459.41 MB | 118.60 MB | -1340.81 MB |
| After status | 1479.35 MB | 118.89 MB | -1360.46 MB |
| After first paint | 1772.54 MB | 123.48 MB | -1649.06 MB |
| After action-ready | 1802.22 MB | 124.11 MB | -1678.11 MB |
| After first Random | 1895.82 MB | 1345.80 MB | -550.02 MB |
| After Generate dispatch | 1896.27 MB | 1345.81 MB | -550.46 MB |

## Dependency audit

| Signal | Desktop-backed | Headless |
| --- | --- | --- |
| `PyQt6` imported | true | false |
| `core.remote_api_server` imported | true | false |
| `core.middle_section_controller` imported | true | false |
| `ModernMainWindow` constructed | true | false |
| `ImageWindow` constructed | true | false |
| `RemoteBridge` constructed | true | false |
| Middle module imports | 2 | 0 |

## CDP coverage

- API setup modal: validated in Round 33 against the headless API config service.
- Random: validated in Round 34 and measured again in Round 39.
- Generate dispatch: validated in Round 35 and measured again in Round 39.
- Actual NAI result display/history: validated in Round 36 with real Remote Web Generate button click.
- Desktop-only import isolation: validated in Round 38 fresh-process import audit.

## Decision

The headless entrypoint is ready as the preferred Remote Web path for the core workflow:

- API setup/status
- Random prompt
- NAI Generate
- WebP result broadcast
- `/api/latest-image`
- PNG export
- in-memory history

The desktop-backed WebShell should remain as compatibility mode for optional desktop surfaces until those features receive web-native services:

- Studio
- Turbo Sequence
- Depth/Tag tooling beyond current placeholders
- result enhance/upscale actions
- advanced conditional prompt editor/preset management
- WEBUI/COMFYUI full execution parity beyond request normalization

The remaining measured bottleneck is first Random. Headless startup is fast, but first Random still lazy-loads wildcard/filter/parquet data and jumps RSS by about 1.2 GB. That is now isolated to first use instead of startup, so the next optimization should target search-result fallback size, filter data loading, and prompt runtime data caching rather than PyQt removal.
