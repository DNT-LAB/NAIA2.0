from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT_DIR / "data" / "location_preset_prompt_manifest.json"
VALIDATION_PATH = ROOT_DIR / "data" / "location_preset_validation_report.json"
COVERAGE_PATH = ROOT_DIR / "data" / "location_preset_coverage_analysis.json"
OUTPUT_PATH = ROOT_DIR / "data" / "location_preset_webview.html"


HTML_TEMPLATE = """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Location Preset Webview</title>
  <style>
    :root {{
      --bg: #f2ede4;
      --paper: rgba(255, 251, 244, 0.94);
      --ink: #1d1b18;
      --muted: #6b655c;
      --line: rgba(42, 34, 26, 0.12);
      --accent: #004f4a;
      --accent-soft: #d9ece8;
      --accent-2: #b1451b;
      --chip: #f7efe1;
      --shadow: 0 16px 40px rgba(46, 34, 18, 0.12);
    }}

    * {{ box-sizing: border-box; }}
    html, body {{ height: 100%; }}
    body {{
      margin: 0;
      font-family: "Pretendard", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(0, 79, 74, 0.12), transparent 28%),
        radial-gradient(circle at bottom right, rgba(177, 69, 27, 0.12), transparent 24%),
        linear-gradient(180deg, #f8f2e8 0%, #efe6d9 100%);
    }}

    .shell {{
      display: grid;
      grid-template-columns: 320px minmax(360px, 1.1fr) minmax(420px, 1.2fr);
      gap: 18px;
      min-height: 100vh;
      padding: 20px;
    }}

    .panel {{
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 24px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(12px);
      overflow: hidden;
    }}

    .sidebar {{
      display: flex;
      flex-direction: column;
      min-width: 0;
    }}

    .section {{
      padding: 18px 18px 0 18px;
    }}

    .section:last-child {{
      padding-bottom: 18px;
    }}

    .eyebrow {{
      font-size: 12px;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 8px;
    }}

    h1, h2, h3, p {{
      margin: 0;
    }}

    h1 {{
      font-size: 30px;
      line-height: 1.05;
      letter-spacing: -0.04em;
    }}

    .lede {{
      margin-top: 10px;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.55;
    }}

    .stat-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-top: 14px;
    }}

    .stat {{
      background: rgba(255, 255, 255, 0.66);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 12px 14px;
    }}

    .stat .label {{
      font-size: 12px;
      color: var(--muted);
      margin-bottom: 6px;
    }}

    .stat .value {{
      font-size: 24px;
      font-weight: 700;
      letter-spacing: -0.04em;
    }}

    .field {{
      display: flex;
      flex-direction: column;
      gap: 8px;
      margin-top: 12px;
    }}

    .field label {{
      font-size: 12px;
      color: var(--muted);
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}

    input, select {{
      width: 100%;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.82);
      color: var(--ink);
      border-radius: 14px;
      padding: 12px 14px;
      font: inherit;
      outline: none;
    }}

    input:focus, select:focus {{
      border-color: rgba(0, 79, 74, 0.42);
      box-shadow: 0 0 0 3px rgba(0, 79, 74, 0.12);
    }}

    .coverage-list {{
      display: grid;
      gap: 8px;
      margin-top: 12px;
    }}

    .coverage-row {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 10px 12px;
      background: rgba(255, 255, 255, 0.66);
      border: 1px solid var(--line);
      border-radius: 14px;
      font-size: 13px;
    }}

    .coverage-row strong {{
      font-size: 15px;
    }}

    .preset-list-panel {{
      display: flex;
      flex-direction: column;
      min-width: 0;
    }}

    .list-toolbar {{
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 12px;
      padding: 18px;
      border-bottom: 1px solid var(--line);
      background: linear-gradient(180deg, rgba(255,255,255,0.55), rgba(255,255,255,0.2));
    }}

    .list-toolbar h2 {{
      font-size: 22px;
      letter-spacing: -0.04em;
    }}

    .list-count {{
      color: var(--muted);
      font-size: 13px;
    }}

    .preset-list {{
      overflow: auto;
      padding: 16px;
      display: grid;
      gap: 12px;
      align-content: start;
    }}

    .preset-card {{
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 14px;
      background: rgba(255, 255, 255, 0.74);
      cursor: pointer;
      transition: transform 140ms ease, border-color 140ms ease, box-shadow 140ms ease;
    }}

    .preset-card:hover {{
      transform: translateY(-1px);
      border-color: rgba(0, 79, 74, 0.28);
      box-shadow: 0 8px 18px rgba(46, 34, 18, 0.08);
    }}

    .preset-card.active {{
      border-color: rgba(0, 79, 74, 0.54);
      box-shadow: 0 10px 24px rgba(0, 79, 74, 0.14);
      background: linear-gradient(180deg, rgba(217,236,232,0.66), rgba(255,255,255,0.9));
    }}

    .card-top {{
      display: flex;
      align-items: start;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 10px;
    }}

    .card-title {{
      font-size: 19px;
      line-height: 1.1;
      letter-spacing: -0.04em;
    }}

    .card-sub {{
      margin-top: 4px;
      color: var(--muted);
      font-size: 12px;
    }}

    .pill-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }}

    .pill {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: var(--chip);
      border: 1px solid rgba(59, 43, 25, 0.08);
      border-radius: 999px;
      padding: 6px 10px;
      font-size: 12px;
      color: var(--ink);
    }}

    .pill.env {{
      background: var(--accent-soft);
      color: var(--accent);
      border-color: rgba(0, 79, 74, 0.14);
    }}

    .pill.tier {{
      background: rgba(177, 69, 27, 0.08);
      color: var(--accent-2);
      border-color: rgba(177, 69, 27, 0.16);
    }}

    .micro {{
      margin-top: 10px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
    }}

    .detail {{
      display: flex;
      flex-direction: column;
      min-width: 0;
    }}

    .detail-head {{
      padding: 20px 20px 18px 20px;
      border-bottom: 1px solid var(--line);
      background:
        radial-gradient(circle at top right, rgba(0,79,74,0.12), transparent 38%),
        linear-gradient(180deg, rgba(255,255,255,0.75), rgba(255,255,255,0.3));
    }}

    .detail-title {{
      font-size: 34px;
      line-height: 0.98;
      letter-spacing: -0.05em;
    }}

    .detail-sub {{
      margin-top: 10px;
      color: var(--muted);
      font-size: 14px;
    }}

    .detail-body {{
      overflow: auto;
      padding: 18px 20px 24px 20px;
      display: grid;
      gap: 16px;
      align-content: start;
    }}

    .prompt-box {{
      border: 1px solid var(--line);
      border-radius: 20px;
      background: rgba(255,255,255,0.76);
      overflow: hidden;
    }}

    .prompt-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      background: rgba(0,0,0,0.02);
    }}

    .prompt-head h3 {{
      font-size: 14px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: var(--muted);
    }}

    button {{
      border: 0;
      border-radius: 999px;
      background: var(--accent);
      color: white;
      padding: 10px 14px;
      font: inherit;
      cursor: pointer;
    }}

    button.secondary {{
      background: rgba(29, 27, 24, 0.08);
      color: var(--ink);
    }}

    pre {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      padding: 16px;
      font-family: "Cascadia Code", "Consolas", monospace;
      font-size: 13px;
      line-height: 1.6;
    }}

    .detail-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
    }}

    .tag-panel {{
      border: 1px solid var(--line);
      border-radius: 20px;
      background: rgba(255,255,255,0.72);
      padding: 14px;
    }}

    .tag-panel h3 {{
      font-size: 14px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--muted);
      margin-bottom: 10px;
    }}

    .tag-wrap {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}

    .tag {{
      padding: 7px 10px;
      border-radius: 12px;
      background: rgba(0,0,0,0.04);
      border: 1px solid rgba(0,0,0,0.06);
      font-size: 13px;
    }}

    .muted {{
      color: var(--muted);
    }}

    .empty {{
      padding: 36px;
      text-align: center;
      color: var(--muted);
      border: 1px dashed var(--line);
      border-radius: 20px;
      background: rgba(255,255,255,0.48);
    }}

    .footer-note {{
      font-size: 12px;
      color: var(--muted);
      line-height: 1.5;
    }}

    @media (max-width: 1380px) {{
      .shell {{
        grid-template-columns: 280px minmax(320px, 1fr) minmax(360px, 1.1fr);
      }}
    }}

    @media (max-width: 1120px) {{
      .shell {{
        grid-template-columns: 1fr;
      }}
      .detail-grid, .stat-grid {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <aside class="panel sidebar">
      <div class="section">
        <div class="eyebrow">NAIA 2.0</div>
        <h1>Location Preset<br>Webview</h1>
        <p class="lede">위치 프리셋 매니페스트를 브라우저에서 바로 확인하기 위한 self-contained HTML입니다. 기본 프롬프트는 구조 상태 전체를 포함하고, Full 프롬프트는 기본 세트에 효과 상태를 얹습니다.</p>
        <div class="stat-grid">
          <div class="stat">
            <div class="label">Preset</div>
            <div class="value" id="stat-preset-count">0</div>
          </div>
          <div class="stat">
            <div class="label">Background Combos</div>
            <div class="value" id="stat-combo-count">0</div>
          </div>
          <div class="stat">
            <div class="label">Structure Tags</div>
            <div class="value" id="stat-structure-count">0</div>
          </div>
          <div class="stat">
            <div class="label">Effect Groups</div>
            <div class="value" id="stat-effect-group-count">0</div>
          </div>
        </div>
      </div>

      <div class="section">
        <div class="field">
          <label for="search">Search</label>
          <input id="search" type="search" placeholder="place / tag / prompt">
        </div>
        <div class="field">
          <label for="environment">Environment</label>
          <select id="environment">
            <option value="">All</option>
          </select>
        </div>
        <div class="field">
          <label for="tier">Support Tier</label>
          <select id="tier">
            <option value="">All</option>
          </select>
        </div>
        <div class="field">
          <label for="sort">Sort</label>
          <select id="sort">
            <option value="frequency-desc">Place Frequency ↓</option>
            <option value="frequency-asc">Place Frequency ↑</option>
            <option value="name-asc">Place Name A-Z</option>
            <option value="name-desc">Place Name Z-A</option>
          </select>
        </div>
      </div>

      <div class="section">
        <div class="eyebrow">Coverage Snapshot</div>
        <div class="coverage-list" id="coverage-list"></div>
      </div>

      <div class="section">
        <p class="footer-note">생성 시 기본값은 <strong>Default Prompt</strong>를 사용하고, 변주 샘플은 <strong>Full Prompt</strong>를 사용하면 됩니다. 이 HTML은 생성 시점의 JSON을 내부에 포함하므로 `file://`로 바로 열 수 있습니다.</p>
      </div>
    </aside>

    <section class="panel preset-list-panel">
      <div class="list-toolbar">
        <div>
          <div class="eyebrow">Preset Browser</div>
          <h2>Prompt Presets</h2>
        </div>
        <div class="list-count" id="list-count">0 items</div>
      </div>
      <div class="preset-list" id="preset-list"></div>
    </section>

    <section class="panel detail">
      <div class="detail-head">
        <div class="eyebrow">Selected Preset</div>
        <div class="detail-title" id="detail-title">Select a preset</div>
        <div class="detail-sub" id="detail-sub">좌측 리스트에서 프리셋을 선택하세요.</div>
      </div>
      <div class="detail-body" id="detail-body">
        <div class="empty">프리셋을 선택하면 기본 프롬프트, 풀 프롬프트, 구조 태그, 효과 태그를 여기에서 확인할 수 있습니다.</div>
      </div>
    </section>
  </div>

  <script>
    const MANIFEST = __MANIFEST_JSON__;
    const VALIDATION = __VALIDATION_JSON__;
    const COVERAGE = __COVERAGE_JSON__;

    const state = {{
      selectedId: "",
      search: "",
      environment: "",
      tier: "",
      sort: "frequency-desc",
    }};

    const els = {{
      presetList: document.getElementById("preset-list"),
      listCount: document.getElementById("list-count"),
      detailTitle: document.getElementById("detail-title"),
      detailSub: document.getElementById("detail-sub"),
      detailBody: document.getElementById("detail-body"),
      search: document.getElementById("search"),
      environment: document.getElementById("environment"),
      tier: document.getElementById("tier"),
      sort: document.getElementById("sort"),
      coverageList: document.getElementById("coverage-list"),
      statPresetCount: document.getElementById("stat-preset-count"),
      statComboCount: document.getElementById("stat-combo-count"),
      statStructureCount: document.getElementById("stat-structure-count"),
      statEffectGroupCount: document.getElementById("stat-effect-group-count"),
    }};

    function escapeHtml(value) {{
      return String(value).replace(/[&<>"]/g, (char) => ({{
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
      }})[char]);
    }}

    function fmt(num) {{
      return Number(num || 0).toLocaleString("ko-KR");
    }}

    function unique(values) {{
      return [...new Set(values)];
    }}

    function copyText(value) {{
      if (navigator.clipboard && navigator.clipboard.writeText) {{
        navigator.clipboard.writeText(value);
        return;
      }}
      const area = document.createElement("textarea");
      area.value = value;
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      area.remove();
    }}

    function buildTagChips(tags) {{
      if (!tags.length) {{
        return '<div class="muted">없음</div>';
      }}
      return `<div class="tag-wrap">${{tags.map((tag) => `<span class="tag">${{escapeHtml(tag)}}</span>`).join("")}}</div>`;
    }}

    function renderCoverage() {{
      const interesting = new Set([1000, 5000, 10000]);
      const rows = COVERAGE.coverage_by_threshold.filter((row) => interesting.has(row.min_count));
      els.coverageList.innerHTML = rows.map((row) => `
        <div class="coverage-row">
          <div>
            <div class="muted">count ≥ ${{fmt(row.min_count)}}</div>
            <strong>${{row.coverage_pct}}%</strong>
          </div>
          <div class="muted">${{row.covered_count}} / ${{row.tag_total}}</div>
        </div>
      `).join("");
    }}

    function populateFilters() {{
      const presets = MANIFEST.presets;
      const envs = unique(presets.map((item) => item.environment)).sort();
      const tiers = unique(presets.map((item) => item.support_tier)).sort();

      els.environment.innerHTML = '<option value="">All</option>' + envs.map((env) => `<option value="${{env}}">${{env}}</option>`).join("");
      els.tier.innerHTML = '<option value="">All</option>' + tiers.map((tier) => `<option value="${{tier}}">${{tier}}</option>`).join("");
    }}

    function getFilteredPresets() {{
      const query = state.search.trim().toLowerCase();
      const presets = MANIFEST.presets.filter((preset) => {{
        if (state.environment && preset.environment !== state.environment) return false;
        if (state.tier && preset.support_tier !== state.tier) return false;
        if (!query) return true;

        const haystack = [
          preset.id,
          preset.place,
          preset.environment,
          preset.default_prompt,
          preset.full_prompt,
          ...preset.structure_tags,
          ...preset.recommended_effect_tags,
        ].join(" ").toLowerCase();

        return haystack.includes(query);
      }});

      presets.sort((a, b) => {{
        switch (state.sort) {{
          case "frequency-asc":
            return a.place_frequency - b.place_frequency;
          case "name-asc":
            return a.place.localeCompare(b.place);
          case "name-desc":
            return b.place.localeCompare(a.place);
          case "frequency-desc":
          default:
            return b.place_frequency - a.place_frequency;
        }}
      }});

      return presets;
    }}

    function renderList() {{
      const presets = getFilteredPresets();
      els.listCount.textContent = `${{fmt(presets.length)}} items`;

      if (!presets.length) {{
        els.presetList.innerHTML = '<div class="empty">조건에 맞는 프리셋이 없습니다.</div>';
        els.detailTitle.textContent = "No preset";
        els.detailSub.textContent = "검색 조건을 조정하세요.";
        els.detailBody.innerHTML = '<div class="empty">표시할 프리셋이 없습니다.</div>';
        return;
      }}

      if (!presets.some((item) => item.id === state.selectedId)) {{
        state.selectedId = presets[0].id;
      }}

      els.presetList.innerHTML = presets.map((preset) => `
        <article class="preset-card ${{preset.id === state.selectedId ? 'active' : ''}}" data-id="${{escapeHtml(preset.id)}}">
          <div class="card-top">
            <div>
              <div class="card-title">${{escapeHtml(preset.place)}}</div>
              <div class="card-sub">${{escapeHtml(preset.id)}}</div>
            </div>
            <div class="pill-row">
              <span class="pill env">${{escapeHtml(preset.environment)}}</span>
              <span class="pill tier">${{escapeHtml(preset.support_tier)}}</span>
            </div>
          </div>
          <div class="pill-row">
            <span class="pill">freq ${{fmt(preset.place_frequency)}}</span>
            <span class="pill">core ${{fmt(preset.core_structure_tags.length)}}</span>
            <span class="pill">optional ${{fmt(preset.optional_structure_tags.length)}}</span>
            <span class="pill">effects ${{fmt(preset.recommended_effect_tags.length)}}</span>
          </div>
          <div class="micro">${{escapeHtml(preset.default_prompt)}}</div>
        </article>
      `).join("");

      els.presetList.querySelectorAll(".preset-card").forEach((node) => {{
        node.addEventListener("click", () => {{
          state.selectedId = node.dataset.id || "";
          renderList();
          renderDetail();
        }});
      }});

      renderDetail();
    }}

    function renderDetail() {{
      const preset = MANIFEST.presets.find((item) => item.id === state.selectedId);
      if (!preset) return;

      els.detailTitle.textContent = preset.place;
      els.detailSub.textContent = `${{preset.environment}} | frequency ${{fmt(preset.place_frequency)}} | tier ${{preset.support_tier}} | effect min support ${{preset.effect_min_support_used}}`;

      els.detailBody.innerHTML = `
        <div class="pill-row">
          <span class="pill env">${{escapeHtml(preset.environment)}}</span>
          <span class="pill tier">${{escapeHtml(preset.support_tier)}}</span>
          <span class="pill">base ${{fmt(preset.base_tags.length)}}</span>
          <span class="pill">core ${{fmt(preset.core_structure_tags.length)}}</span>
          <span class="pill">optional ${{fmt(preset.optional_structure_tags.length)}}</span>
          <span class="pill">effects ${{fmt(preset.recommended_effect_tags.length)}}</span>
        </div>

        <section class="prompt-box">
          <div class="prompt-head">
            <h3>Default Prompt</h3>
            <button type="button" data-copy="${{escapeHtml(preset.default_prompt)}}">Copy</button>
          </div>
          <pre>${{escapeHtml(preset.default_prompt)}}</pre>
        </section>

        <section class="prompt-box">
          <div class="prompt-head">
            <h3>Full Prompt</h3>
            <button type="button" data-copy="${{escapeHtml(preset.full_prompt)}}">Copy</button>
          </div>
          <pre>${{escapeHtml(preset.full_prompt)}}</pre>
        </section>

        <div class="detail-grid">
          <section class="tag-panel">
            <h3>Core Structure Tags</h3>
            ${{buildTagChips(preset.core_structure_tags)}}
          </section>
          <section class="tag-panel">
            <h3>Recommended Effects</h3>
            ${{buildTagChips(preset.recommended_effect_tags)}}
          </section>
        </div>

        <div class="detail-grid">
          <section class="tag-panel">
            <h3>Optional Structure Tags</h3>
            ${{buildTagChips(preset.optional_structure_tags)}}
          </section>
          <section class="tag-panel">
            <h3>Default Effect Tags</h3>
            ${{buildTagChips(preset.default_effect_tags)}}
          </section>
        </div>

        <section class="tag-panel">
          <h3>All Structure Tags</h3>
          ${{buildTagChips(preset.structure_tags)}}
        </section>
      `;

      els.detailBody.querySelectorAll("[data-copy]").forEach((button) => {{
        button.addEventListener("click", () => {{
          copyText(button.getAttribute("data-copy") || "");
          const original = button.textContent;
          button.textContent = "Copied";
          setTimeout(() => {{
            button.textContent = original;
          }}, 900);
        }});
      }});
    }}

    function bind() {{
      els.search.addEventListener("input", (event) => {{
        state.search = event.target.value || "";
        renderList();
      }});
      els.environment.addEventListener("change", (event) => {{
        state.environment = event.target.value || "";
        renderList();
      }});
      els.tier.addEventListener("change", (event) => {{
        state.tier = event.target.value || "";
        renderList();
      }});
      els.sort.addEventListener("change", (event) => {{
        state.sort = event.target.value || "frequency-desc";
        renderList();
      }});
    }}

    function init() {{
      els.statPresetCount.textContent = fmt(MANIFEST.summary.preset_count);
      els.statComboCount.textContent = fmt(VALIDATION.coverage.background_combo_total);
      els.statStructureCount.textContent = fmt(VALIDATION.coverage.structure_state_total);
      els.statEffectGroupCount.textContent = fmt(MANIFEST.presets.length ? new Set(MANIFEST.presets.flatMap((item) => item.recommended_effect_tags)).size : 0);
      populateFilters();
      renderCoverage();
      bind();
      renderList();
    }}

    init();
  </script>
</body>
</html>
"""


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    manifest = load_json(MANIFEST_PATH)
    validation = load_json(VALIDATION_PATH)
    coverage = load_json(COVERAGE_PATH)

    html = HTML_TEMPLATE.replace("{{", "{").replace("}}", "}")
    html = html.replace("__MANIFEST_JSON__", json.dumps(manifest, ensure_ascii=False))
    html = html.replace("__VALIDATION_JSON__", json.dumps(validation, ensure_ascii=False))
    html = html.replace("__COVERAGE_JSON__", json.dumps(coverage, ensure_ascii=False))

    OUTPUT_PATH.write_text(html, encoding="utf-8")
    print(
      json.dumps(
        {
          "output": str(OUTPUT_PATH),
          "generated_at": datetime.now(timezone.utc).isoformat(),
          "preset_count": manifest.get("summary", {}).get("preset_count", 0),
        },
        ensure_ascii=False,
        indent=2,
      )
    )


if __name__ == "__main__":
    main()
