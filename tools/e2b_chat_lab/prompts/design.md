Decide ONE concrete physical pose. Return JSON, not reasoning.
Read the retrieved Danbooru tag meanings BEFORE designing. Prefer canonical action/pose words that fit the original request (e.g. carrying, struggling, walking). Use them naturally in scene_en/action_en so conversion can keep them. Never add a character, sexual element, expression or pose just because an Event Map neighbour co-occurs. A shoulder carry tag may describe a different position from carrying someone over one shoulder: read its meaning. State the carrier and carried person's roles explicitly. A carried person's legs may hang; do not make both people walk on the ground.
stance_en: standing, walking, kneeling, seated, etc. Specify foot/knee placement. Do NOT answer merely "dynamic pose".
body_en: torso orientation, balance and support. Avoid aesthetic adjectives.
left_hand_en and right_hand_en: EXACTLY where each hand contacts an object/body. Never give alternatives (or/either/maybe).
Example for a heavy long gun: left_hand_en="cradling the underside of the fore-end to support its weight"; right_hand_en="gripping the rear handle with index finger on the trigger". Both hands cannot occupy the same grip. Use this division when appropriate, preserving the user's specified handedness.
Example for a heavy crate: left_hand_en="supporting the bottom-left corner of the crate"; right_hand_en="supporting the bottom-right corner of the crate". Preserve the contents inside it.
Use "not applicable" when a hand is absent/offscreen; do not invent people or limbs.
camera_en: the user-fixed viewpoint or one chosen viewpoint. Front view alone does NOT require aiming at the viewer.
action_en: exact requested action. Firing needs visible discharge/recoil, not merely aiming. Walking stays walking.
scene_en: concise English scene including character appearance, object, pose, viewpoint, action and background. No new object types or decorative adjectives.
summary_ko: 짧은 한국어 설명에 실제 자세, 왼손 위치, 오른손 위치를 반드시 포함하세요.
preserved_ids: ALL K IDs. searches: 0-3 short tag queries for the decided scene.
Current user text and locked requirements take precedence over earlier design. Only decide unspecified dimensions; preserve appearance, object size, viewpoint, actions and exclusions. These choices are proposals, never permanent user facts.
