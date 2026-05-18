# WebSession Unsupported PyQt Tabs

These desktop PyQt surfaces are outside the Remote Web Session contract and must stay out of WebSession startup/import paths.

## Runtime blocked

- `TurboEventSequenceTabModule`
  - Desktop entrypoint remains for now.
  - Hidden WebSession runtime blocks dynamic import/creation through `TabController`.
  - Direct Turbo dialog selection also no-ops in hidden WebSession runtime.

## Removed guards

- `HookerTabModule`
- `StorytellerTabModule`
- `AssetsTabModule`

These modules are treated as not implemented for the current Remote Web Session surface unless a future web-native feature contract is added.
