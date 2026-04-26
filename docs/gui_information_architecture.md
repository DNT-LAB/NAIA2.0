# NAIA GUI Information Architecture

Date: 2026-04-26
Branch: `future01`

## Purpose

This document defines the current NAIA Desktop GUI information architecture so
the GUI can be refactored without losing the application's workflow model.

The current PyQt layout may be replaced by a Desktop Web Shell and the Remote
Session may receive a different responsive layout. Those renderers must still
preserve the same product structure, state model, and user actions unless a
separate migration decision changes the contract.

## Core Model

NAIA is a two-surface generation workspace:

- **Control Surface**: prompt, search, modules, generation parameters, and
  generation commands.
- **Result Workspace**: generated image viewer, history, metadata, reference
  tools, and settings.

The current desktop app renders these surfaces as a horizontal split view:

```text
ModernMainWindow
└─ QSplitter(horizontal)
   ├─ Left Control Column
   │  ├─ Scroll Area
   │  │  ├─ Search / Filter / API Management
   │  │  ├─ Search Result Summary
   │  │  ├─ Prompt Editor
   │  │  ├─ Img2Img Panel
   │  │  └─ Middle Module Stack
   │  ├─ Generation Parameters Drawer
   │  └─ Fixed Generate Footer
   └─ Right Result Workspace
      └─ Tab Workspace
         ├─ Generated Image
         ├─ Danbooru
         ├─ PNG Info
         ├─ Thumb
         ├─ Artists
         ├─ Studio
         └─ Settings
```

## Web Shell Renderer

The first Desktop Web Shell path is:

```text
QApplication
├─ ModernMainWindow hidden backend
│  ├─ AppContext
│  ├─ Prompt / generation controllers
│  └─ RemoteBridge signal slots
└─ WebWrapperWindow
   └─ QWebEngineView
      └─ http://127.0.0.1:<port>/?desktop_shell=1
         ├─ ui/remote_web/index.html
         ├─ ui/remote_web/style.css
         └─ ui/remote_web/app.js
```

This intentionally reuses the Remote Web Session protocol instead of creating a
second QWebChannel-only bridge. The FastAPI/WebSocket layer in
`core/remote_api_server.py` remains the shared contract for:

- desktop-local QWebEngine rendering,
- browser-based Remote Session,
- mobile Remote Session,
- Cloudflared shared sessions.

Renderer-specific behavior must be handled in the web client through capability
or query flags such as `desktop_shell=1`; state names, command names, and payload
shape should stay aligned with `RemoteBridge`.

## Source Ownership

| Area | Current owner | Notes |
| --- | --- | --- |
| Main desktop shell | `NAIA_cold_v4.py::ModernMainWindow` | Owns top-level layout, controller wiring, search/prompt/params/generate UI, and several workflow handlers. |
| Left module stack | `core/middle_section_controller.py` | Dynamically loads `modules/*_module.py`, wraps modules with `EnhancedCollapsibleBox`, manages detaching and mode visibility. |
| Middle module contract | `interfaces/base_module.py` | Defines `get_title`, `create_widget`, `get_order`, parameters, pipeline hooks, and mode compatibility flags. |
| Mode-aware module contract | `interfaces/mode_aware_module.py` | Defines per-mode settings persistence and visibility. |
| Right workspace shell | `ui/right_view.py` | Hosts `EnhancedTabWidget`, forwards tab signals to `ModernMainWindow`, supports detached tabs. |
| Right tab controller | `core/tab_controller.py` | Owns tab registry, lazy startup tabs, dynamic closable tabs, and removed tab filtering. |
| Right tab contract | `interfaces/base_tab_module.py` | Defines tab title, widget creation, order/type, close behavior, and common tab signals. |
| Generated image tab | `tabs/image_window.py` | Owns image viewer, toolbar, history side panel, metadata display, save/enhance/history behavior. |
| Theme tokens | `ui/theme.py` | Current PyQt QSS token source. This is a legacy renderer detail, not the IA contract. |

## Current Desktop Regions

### 1. Main Shell

Current code: `NAIA_cold_v4.py::init_ui`

Responsibilities:

- Create the horizontal split between control and result areas.
- Install the status bar.
- Create the left control column through `create_left_panel`.
- Create the right result workspace through `create_right_panel`.
- Maintain initial minimum widths and splitter behavior.

State:

- Window size and splitter state.
- Desktop visibility state for Web Session.

Migration requirement:

- Desktop Web Shell should preserve the two-surface model on wide screens.
- The exact PyQt `QSplitter` behavior does not need to be preserved.

### 2. Search / Filter / API Management

Current code: `NAIA_cold_v4.py::_build_search_section`

Responsibilities:

- Select API mode: `NAI`, `WEBUI`, `COMFYUI`.
- Display Anlas for NAI.
- Enter include/exclude search keywords.
- Select rating filters and dataset/search mode.
- Start search.
- Open API management.

Primary state:

- `api_mode`
- `search_keyword`
- `exclude_keyword`
- `ratings`
- `search_dataset_mode`
- `anlas`
- `search_progress`

Primary actions:

- `setApiMode(mode)`
- `searchPrompts(query, exclude, ratings, datasetMode)`
- `openApiManagement()`
- `restoreSearchResults()`
- `loadCustomDataset()`
- `mergeCustomDataset()`
- `exportDataset()`

Remote requirement:

- This area can be a compact toolbar on desktop/tablet Remote.
- On mobile, API mode and filters should move behind a filter/settings sheet,
  while search keyword remains close to prompt generation flow.

### 3. Search Result Summary

Current code: `NAIA_cold_v4.py::_build_search_result_frame`

Responsibilities:

- Show search result count and remaining result count.
- Save current settings.
- Restore/load/merge/export search result data.
- Open depth search.

Primary state:

- `result_count`
- `remaining_count`
- `search_snapshot_available`

Primary actions:

- `saveCurrentSettings()`
- `restoreSearchResults()`
- `openDepthSearch()`

Remote requirement:

- This should remain visible near search context on wide layouts.
- On mobile, it can collapse into a small result counter row.

### 4. Prompt Editor

Current code: `NAIA_cold_v4.py::_build_prompt_section`

Responsibilities:

- Edit main prompt.
- Edit negative prompt.
- Provide CLI prompt input.
- Show estimated token counts.
- Open prompt-related tools through corner actions.
- Detach prompt editor into a separate window in the PyQt renderer.

Primary state:

- `main_prompt`
- `negative_prompt`
- `prompt_tab`
- `token_count`
- `negative_token_count`
- `prompt_tools_open_state`

Primary actions:

- `setMainPrompt(text)`
- `setNegativePrompt(text)`
- `applyPromptFromMetadata(prompt, negative)`
- `translatePrompt()`
- `openPromptTool(toolId)`
- `detachPromptEditor()` for PyQt legacy only

Remote requirement:

- Prompt editing is the primary mobile workflow and must not be buried.
- Mobile should expose main prompt first, then negative prompt as a secondary
  tab or sheet.
- CLI can remain desktop-only unless explicitly required.

### 5. Img2Img Panel

Current code: `NAIA_cold_v4.py` creates `Img2ImgPanel(self)` and inserts it in
the left scroll stack.

Responsibilities:

- Host image-to-image / inpaint related controls that are tied to generation
  setup.

Primary state:

- `img2img_source`
- `inpaint_source`
- `img2img_parameters`

Primary actions:

- `activateImg2Img(image)`
- `activateInpaint(image)`
- `clearImg2ImgSource()`

Remote requirement:

- On wide layouts, this can remain in the Control Surface.
- On mobile, this should be a source attachment panel or generation-mode sheet.

### 6. Middle Module Stack

Current code: `core/middle_section_controller.py`

Responsibilities:

- Discover and load `modules/*_module.py`.
- Sort modules by `get_order()`.
- Wrap each module in a detachable collapsible panel.
- Handle accordion behavior.
- Apply API-mode visibility.
- Register pipeline hooks.
- Register `ModeAwareModule` instances with `AppContext.mode_manager`.

Current module examples:

- Prompt Engineering / Automation / Preset
- Automation Settings
- NAID4 Character
- Wildcard Module
- E621 Research Module V2
- Ollama
- Vibe Transfer
- Instant Wildcard
- Character Reference
- Reference Inset Protect
- Conditional Prompt

Primary state:

- `module_visibility`
- `module_expanded_state`
- `module_detached_state`
- `module_settings_by_mode`
- `pipeline_hook_registration`

Primary actions:

- `toggleModule(moduleId)`
- `detachModule(moduleId)` for PyQt legacy only
- `setModuleVisibility(moduleId, visible)`
- `applyModuleSettings(moduleId, settings)`

Remote requirement:

- Modules should become contract-driven panels.
- Wide Remote can mirror the desktop stack.
- Mobile should group modules under categories instead of showing a long
  vertical stack by default.

### 7. Generation Parameters Drawer

Current code: `NAIA_cold_v4.py::_build_params_toggle_area`

Responsibilities:

- Show and hide detailed generation parameters.
- Manage NAI, WebUI, and ComfyUI parameter controls.
- Switch visible parameter groups according to API mode.
- Host custom/override API parameters.

Primary state:

- `params_expanded`
- `model`
- `scheduler`
- `resolution`
- `random_resolution`
- `sampler`
- `steps`
- `cfg_scale`
- `cfg_rescale`
- `seed`
- `seed_fixed`
- `auto_fit_resolution`
- `nai_options`
- `webui_hires_options`
- `comfyui_sampling_options`
- `custom_api_parameters`

Primary actions:

- `toggleParamsDrawer()`
- `setGenerationParam(key, value)`
- `openResolutionManager()`
- `loadComfyWorkflowFromImage()`
- `toggleCustomApiParameters()`

Remote requirement:

- Wide layout can keep this as a drawer.
- Mobile should treat this as a full-screen or bottom-sheet "Params" page.
- Parameter schema must be shared across Desktop Web Shell and Remote.

### 8. Fixed Generate Footer

Current code: `NAIA_cold_v4.py::_build_generation_controls`

Responsibilities:

- Trigger random/next prompt.
- Trigger image generation.
- Toggle generation flags.

Primary state:

- `prompt_fixed`
- `auto_generate`
- `turbo_options`
- `wildcard_solo_mode`
- `queue_state`

Primary actions:

- `randomPrompt()`
- `generateImage()`
- `togglePromptFixed()`
- `toggleAutoGenerate()`
- `toggleTurboOption()`
- `toggleWildcardSoloMode()`

Remote requirement:

- This is a primary action area and must remain quickly accessible.
- On mobile, `Generate` should be sticky at the bottom or part of the primary
  navigation action bar.

### 9. Right Tab Workspace

Current code: `ui/right_view.py`, `core/tab_controller.py`

Responsibilities:

- Render result/reference/settings tabs.
- Lazy-load heavy tabs when selected.
- Forward tab signals to the main window.
- Support detached tabs in the PyQt renderer.

Current core tabs:

| Tab | Current class | Startup behavior | Responsibility |
| --- | --- | --- | --- |
| Generated Image | `ImageViewerModule` | eager | View generated image, history, metadata, save/enhance controls. |
| Danbooru | `BrowserTabModule` | lazy | Browse/search Danbooru and request generation from image/reference data. |
| PNG Info | `PngInfoTabModule` | lazy | Inspect image metadata and apply prompt/settings. |
| Thumb | `ThumbnailsTabModule` | lazy | Thumbnail-oriented image review. |
| Artists | `ArtistThumbModule` | lazy | Artist/reference browsing. |
| Studio | `StudioTab` | lazy | Studio workflow surface. |
| Settings | `SettingsTabModule` | eager | App settings, Web Session, tab/module visibility. |

Dynamic / closable tabs:

- API Management
- Depth Search
- Img2Img
- API WebView
- Turbo Sequence

Primary state:

- `active_tab`
- `loaded_tabs`
- `tab_visibility`
- `detached_tabs`

Primary actions:

- `setActiveResultTab(tabId)`
- `loadTab(tabId)`
- `setTabVisibility(tabId, visible)`
- `closeDynamicTab(tabId)`
- `detachTab(tabId)` for PyQt legacy only

Remote requirement:

- Wide Remote should keep this as the Result Workspace tab strip.
- Mobile should not render a desktop tab strip. It should expose viewer,
  history, metadata, and references through bottom navigation or sheets.

### 10. Generated Image Workspace

Current code: `tabs/image_window.py`

Responsibilities:

- Display generated image.
- Manage image toolbar actions: save, auto-save, WEBP, folder open, advanced,
  view.
- Maintain image history side panel.
- Display generation information / metadata.
- Emit reuse actions: load prompt, reroll, img2img, inpaint, outpaint, remote
  event save.

Primary state:

- `current_image`
- `current_history_item`
- `history_items`
- `auto_save`
- `save_as_webp`
- `generation_info`
- `image_metadata`
- `enhance_settings`

Primary actions:

- `saveImage()`
- `openOutputFolder()`
- `setAutoSave(enabled)`
- `setSaveAsWebp(enabled)`
- `selectHistoryItem(id)`
- `loadPromptFromHistory(id)`
- `rerollFromHistory(id)`
- `sendToImg2Img(id)`
- `sendToInpaint(id)`
- `saveHistoryItemToRemoteEvent(id)`

Remote requirement:

- Viewer and history are separate conceptual panels even if currently rendered
  in one PyQt tab.
- Mobile should prioritize the viewer, with history as a drawer/sheet.

## Shared UI Contract

The next renderer should not bind directly to PyQt widgets. It should consume
and mutate shared state objects through bridge actions.

### State Objects

```text
AppShellState
- api_mode
- active_control_panel
- active_result_tab
- desktop_window_visible

SearchState
- keyword
- exclude_keyword
- ratings
- dataset_mode
- result_count
- remaining_count
- progress

PromptState
- main_prompt
- negative_prompt
- active_prompt_tab
- token_count
- negative_token_count

GenerationParamsState
- model
- scheduler
- resolution
- sampler
- steps
- cfg_scale
- cfg_rescale
- seed
- seed_fixed
- random_resolution
- auto_fit_resolution
- mode_specific_options
- custom_api_parameters

ModuleStackState
- modules[]
  - id
  - title
  - visible
  - expanded
  - compatible_modes
  - settings

GenerationActionState
- prompt_fixed
- auto_generate
- turbo_options
- wildcard_solo_mode
- queue_state

ViewerState
- current_image
- current_history_item_id
- generation_info
- metadata
- auto_save
- save_as_webp

HistoryState
- items[]
  - id
  - thumbnail
  - prompt
  - negative_prompt
  - backend_type
  - created_at
  - filepath
```

### Action Groups

```text
SearchActions
- search
- restore
- loadDataset
- mergeDataset
- exportDataset
- openDepthSearch

PromptActions
- setMainPrompt
- setNegativePrompt
- translatePrompt
- applyMetadataPrompt

ParamsActions
- setParam
- setModeSpecificParam
- toggleParamsExpanded
- openResolutionManager
- loadWorkflowFromImage

ModuleActions
- setModuleExpanded
- setModuleVisible
- updateModuleSettings

GenerationActions
- randomPrompt
- generate
- enqueue
- pauseQueue
- resumeQueue

ViewerActions
- saveImage
- openFolder
- selectHistoryItem
- loadPromptFromHistory
- rerollHistoryItem
- sendToImg2Img
- sendToInpaint
- saveToRemoteEvent

WorkspaceActions
- setActiveResultTab
- setTabVisible
- openDynamicTab
- closeDynamicTab
```

## Renderer Mapping

### Desktop PyQt Legacy

The current renderer uses:

- `QSplitter` for two-pane layout.
- `QScrollArea` for the left Control Surface.
- `QTabWidget` for prompt tabs and right workspace tabs.
- `EnhancedCollapsibleBox` for middle modules.
- `FixedBox` for the prompt editor height behavior.

This renderer is allowed to keep PyQt-only affordances:

- detachable prompt editor
- detachable middle modules
- detachable right tabs

These are renderer capabilities, not core IA requirements.

### Desktop Web Shell

Recommended structure:

```text
Desktop Web Shell
├─ Control Column
│  ├─ Search/API Header
│  ├─ Prompt Editor
│  ├─ Module Stack
│  ├─ Params Drawer
│  └─ Generate Footer
└─ Result Workspace
   ├─ Result Tabs
   ├─ Viewer
   ├─ History Rail
   └─ Metadata Panel
```

Desktop Web Shell should keep the current wide-screen mental model but should
not replicate PyQt fixed sizes or QSS styling.

### Remote Desktop / Tablet

Remote wide layout can share most of the Desktop Web Shell arrangement:

- Control Surface left or as a slide-over panel.
- Result Workspace right.
- Result tabs remain visible.
- Params can stay as a drawer.

### Remote Mobile

Mobile should not shrink the desktop two-pane view.

Recommended structure:

```text
Mobile Remote
├─ Primary view: Prompt
├─ Sticky action: Generate
├─ Bottom navigation
│  ├─ Prompt
│  ├─ Params
│  ├─ Modules
│  ├─ Viewer
│  └─ History
└─ Sheets
   ├─ Search filters
   ├─ API mode/settings
   ├─ Metadata
   └─ Reference tools
```

Mobile must optimize for short loops:

1. edit prompt
2. generate
3. inspect image
4. reuse/reroll

## Migration Boundaries

Must preserve:

- Control Surface vs Result Workspace split.
- Prompt-first generation workflow.
- Params as detailed/secondary controls.
- Module stack as optional workflow extensions.
- Generated image, history, and metadata as separate conceptual panels.
- Shared API mode and mode-aware visibility behavior.

Can change:

- Exact pixel sizes.
- PyQt tab styling.
- CollapsibleBox visual treatment.
- Detach behavior in web/mobile renderers.
- Whether modules are shown as accordion, drawer, or categorized panels.
- Whether right workspace tabs become navigation items on mobile.

Should be removed from the core IA:

- PyQt-specific fixed sizes.
- QSS-specific visual tokens.
- DPI/scaling compatibility assumptions.
- Renderer-only detach behavior as a required product feature.

## Immediate Follow-Up Work

1. Audit the current Remote Session layout against this IA.
2. Define the bridge payloads for the shared state objects.
3. Decide whether Remote and Desktop Web Shell share one frontend package or
   share only the state/action contract.
4. Create low-fidelity Desktop Web Shell and Mobile Remote wireframes from this
   IA before changing runtime behavior.
