// 캐릭터 프리셋 — 캐릭터마다 대표 태그를 **슬롯별로 미리 갈라** 둔다.
//
// ## 왜 미리 계산하는가
//
// 프리셋을 고르면 머리/눈·얼굴/신체 슬롯이 자동으로 채워져야 한다. 그 매핑을 런타임에
// 하면 (a) 어느 태그가 어디에도 못 들어갔는지 아무도 모르고 (b) 축 구성이 바뀌면 조용히
// 어긋난다. 미리 돌려 두면 **커버리지가 숫자로 나오고** 빠진 것을 눈으로 볼 수 있다.
//
// ## 매핑 출처
//
// `interactiveAxes.mjs` 의 `CHAR_SLOTS`(슬롯 -> 섹션 -> 축)와 `THUMB_TAGS`(축 -> 태그)를
// 역으로 뒤집어 `태그 -> 슬롯` 을 만든다. **손으로 적지 않는다** — 이 리포에서 같은 목록을
// 두 군데 적어 갈라진 사고가 여러 번 났다. 팔레트(색)와 슬라이더도 같은 방식으로 읽는다.
//
// ## 문턱 (서브에이전트 실측 근거를 그대로 따른다)
//
//   · 배타 축(팔레트·슬라이더: 머리색·눈색·길이·가슴) — 문턱 없음, 대신 **비율 최고 하나만**
//     50% 를 걸면 하츠네 미쿠의 `aqua eyes`(39.0%)가 빠진다(personal_color p10=37.8).
//     그리고 변형 레코드는 머리색을 6개까지 나열해서 그대로 넣으면 서로 싸운다.
//   · 나머지 축 — `pct >= 50`("그 캐릭터 그림의 과반"). characteristics p10=53.3 이라
//     하위 10% 만 잘린다.
//
// 문턱 아래 태그도 버리지 않고 `off` 로 함께 담는다. UI 가 체크만 꺼서 보여줄 수 있다.
//
// 사용: node tools/build_character_presets.mjs [--out data/character_presets.json]

import fs from 'fs';
import path from 'path';

const OUT = process.argv.includes('--out')
  ? process.argv[process.argv.indexOf('--out') + 1]
  : 'data/character_presets.json';

const ax = await import('../app/web/remote/js/features/interactiveAxes.mjs');
const analysis = JSON.parse(fs.readFileSync('data/character_analysis.json', 'utf8'));

// ── 태그 -> {slot, axis, kind} 역인덱스 ───────────────────────────────────────
const tagTo = new Map();
const axisKind = new Map();          // 축 -> 'thumb' | 'palette' | 'slider'
for (const slot of ax.CHAR_SLOTS) {
  for (const sec of slot.sections) {
    const ref = sec.ref;
    if (!ref || sec.kind === 'browse') continue;
    axisKind.set(ref, sec.kind);
    const pool = sec.kind === 'palette'
      ? (ax.PALETTES?.[ref] || []).map(d => d.tag)
      : sec.kind === 'slider'
        ? (ax.SLIDERS?.[ref]?.steps || [])
        : (ax.THUMB_TAGS?.[ref] || []);
    for (const t of pool) {
      const k = String(t).trim().toLowerCase();
      if (k && !tagTo.has(k)) tagTo.set(k, { slot: slot.key, axis: ref, kind: sec.kind });
    }
    // 섹션에 딸린 색 팔레트(thumb_color / thumb_extra)도 같은 슬롯으로 본다.
    for (const extra of [sec.mainPalette, sec.extraPalette]) {
      if (!extra) continue;
      axisKind.set(extra, 'palette');
      for (const d of (ax.PALETTES?.[extra] || [])) {
        const k = String(d.tag).trim().toLowerCase();
        if (k && !tagTo.has(k)) tagTo.set(k, { slot: slot.key, axis: extra, kind: 'palette' });
      }
    }
  }
}

// **배타 축**: 하나만 고를 수 있는 것. 팔레트/슬라이더가 그렇다.
const isExclusive = (axis) => axisKind.get(axis) === 'palette' || axisKind.get(axis) === 'slider';

const FEATURE_PCT = 50;

let nChar = 0, nMapped = 0, nUnmapped = 0;
const unmappedCount = new Map();
const out = {};

for (const [work, chars] of Object.entries(analysis)) {
  if (work.startsWith('_')) continue;
  for (const [name, rec] of Object.entries(chars)) {
    nChar++;
    const cand = [];
    for (const x of (rec.personal_color || [])) cand.push({ tag: x.tag, pct: x.pct, color: true });
    for (const x of (rec.characteristics || [])) cand.push({ tag: x.tag, pct: x.pct, color: false });

    const on = {};      // slot -> [{tag, pct, axis}]
    const off = [];     // 문턱 미달(버리지 않고 보관)
    const takenExclusive = new Set();
    for (const c of cand) {
      const hit = tagTo.get(String(c.tag).trim().toLowerCase());
      if (!hit) {
        nUnmapped++;
        unmappedCount.set(c.tag, (unmappedCount.get(c.tag) || 0) + 1);
        continue;
      }
      nMapped++;
      const excl = isExclusive(hit.axis);
      if (excl) {
        // 비율 최고 하나만. 후보는 pct 내림차순으로 들어오므로 처음 것이 이긴다.
        if (takenExclusive.has(hit.axis)) { off.push({ ...c, ...hit, why: 'exclusive' }); continue; }
        takenExclusive.add(hit.axis);
      } else if (c.pct < FEATURE_PCT) {
        off.push({ ...c, ...hit, why: 'below' });
        continue;
      }
      (on[hit.slot] ||= []).push({ tag: c.tag, pct: c.pct, axis: hit.axis });
    }
    out[`${work}::${name}`] = {
      work, name, rows: rec.total_rows || 0,
      slots: on,
      off: off.map(o => ({ tag: o.tag, pct: o.pct, slot: o.slot, axis: o.axis, why: o.why })),
    };
  }
}

const note = [
  '캐릭터 프리셋 — 캐릭터별 대표 태그를 슬롯으로 미리 가른 것.',
  'tools/build_character_presets.mjs 가 만든다. 매핑 출처는 interactiveAxes.mjs 의',
  'CHAR_SLOTS + THUMB_TAGS/PALETTES/SLIDERS 역인덱스다(손으로 적지 않는다).',
  'slots = 바로 넣을 것, off = 문턱 미달이라 꺼둔 것(why: below=pct<50, exclusive=배타축 중복).',
  '배타 축(팔레트/슬라이더)은 문턱 없이 비율 최고 하나만 — 50%를 걸면 미쿠의 aqua eyes(39%)가 빠지고,',
  '변형 레코드는 머리색을 6개까지 나열해서 그대로 넣으면 서로 싸운다.',
];
fs.mkdirSync(path.dirname(OUT), { recursive: true });
fs.writeFileSync(OUT, JSON.stringify({ note, count: nChar, presets: out }), 'utf8');

const top = [...unmappedCount.entries()].sort((a, b) => b[1] - a[1]).slice(0, 12);
console.log(`캐릭터 ${nChar.toLocaleString()}명 / 태그 ${(nMapped + nUnmapped).toLocaleString()}개`);
console.log(`  슬롯에 매핑 ${nMapped.toLocaleString()} (${(nMapped / (nMapped + nUnmapped) * 100).toFixed(1)}%)`);
console.log(`  매핑 실패   ${nUnmapped.toLocaleString()} / 고유 ${unmappedCount.size}종`);
console.log('  실패 상위:', top.map(([t, n]) => `${t}(${n})`).join(' · '));
const sz = fs.statSync(OUT).size;
console.log(`저장: ${OUT}  (${(sz / 1024 / 1024).toFixed(1)} MB)`);
