# Desktop App decommission boundary

## What Has Been Removed From Remote Web

The headless Remote Web path no longer needs these desktop objects for the core NAI workflow:

- `QApplication`
- `ModernMainWindow`
- `ImageWindow`
- `MiddleSectionController`
- `TabController`
- `RemoteBridge`
- PyQt tab/module widget construction

This applies to the `NAIA_web_headless.py` entrypoint and the core Remote Web flow:

- API setup/status
- Random prompt
- NAI Generate
- WebP preview broadcast
- PNG export
- in-memory history

## What Still Exists

The Desktop App still exists and still works:

- `NAIA_cold_v4.py`
- Desktop window and PyQt widgets
- Desktop tabs under `tabs/`
- Desktop middle modules under `modules/`
- Desktop-backed WebShell compatibility mode

This is not a contradiction in the completed Headless Web Session roadmap. It is the remaining scope for a separate Desktop App decommission roadmap.

The execution roadmap is `refactor_plans/desktop_app_decommission_roadmap.md`.

## Decommission Gate

Desktop App removal is complete only when:

- Supported launch flows no longer start `NAIA_cold_v4.py`.
- Supported runtime dependencies no longer require `PyQt6`.
- Desktop-only tabs/modules are migrated, retired, archived, or split into a separate optional package.
- Remote Web has browser/CDP validation for every supported workflow after Desktop fallback removal.
- Packaging and documentation no longer present Desktop App as a supported main runtime.
