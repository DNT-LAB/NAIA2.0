// NAI 다중 계정(Multi Token) — 화면 두 곳을 한 모듈이 맡는다.
//
//   1) 결과 뷰어의 USAGE 배지를 누르면 뜨는 팝오버
//      통합(평균) 사용량 · 계정별 막대 · [+ Manage Account] · 부하 분산 정책 4종
//   2) API 설정 대화상자의 NAI 탭에 붙는 계정 관리 목록
//      계정 추가/삭제 · 토큰 입력 · 켬/끔  (Dev0714 PyQt 창에 있던 것)
//
// 두 화면이 같은 상태를 본다. 배지 쪽에서 정책을 바꿔도 설정 쪽 목록이 같이 갱신되고,
// 그 반대도 마찬가지다 — 서버가 변경 때마다 `nai_accounts` 스냅샷을 다시 보내기 때문.
//
// 데이터가 둘로 나뉜 이유:
//   `nai_accounts`     계정 **명부**(끈 계정 포함). 설정 화면이 이걸 그린다.
//   `nai_usage_update` **활성 계정의 사용량**. 배지/막대가 이걸 쓴다. V5 일 때만 온다.
// 명부와 사용량을 한 메시지로 합치지 않은 건, 사용량 조회가 계정 수만큼 네트워크를
// 타서 명부보다 훨씬 느리고 훨씬 자주 없기 때문이다.

const POLICY_FALLBACK = [
  { key: 'round_robin', label: '라운드 로빈', desc: '1장씩 번갈아가며 생성합니다.' },
];

// 퍼센트를 장수로 옮기는 상수.
//
// ⚠️ **API 는 장수를 보내지 않는다.** 구독 응답의 usage 는 정확히 세 값뿐이다
// (실측 2026-08-21, 두 계정 응답 전수 확인):
//     {"percent": 97, "isNegative": false, "timeUntilNextPercent": 7888}
// NAI 웹이 보여 주는 "~1730 images" 는 저쪽 프런트가 상수를 곱해 만든 값이다.
// 그 상수를 NAI 자신의 표시에서 역산했다:
//     86400 / 7888        = 10.95 %/일   -> NAI 표시 "11% per day"      (일치)
//     190 / 10.95         = 17.3 장/1%
//     17.3 x 100          = 1730 장      -> NAI 표시 "~1730 images"     (일치)
// 반올림 자리까지 맞으므로 상수는 17.3 으로 본다.
//
// ⚠️ 이 장수는 **무료 기준 생성에서만** 맞다 - NAI 안내문 그대로 "normal
// resolutions and up to 28 steps"(1MP 이하 · 28스텝 이하). 해상도나 스텝을 올리면
// 같은 예산을 더 빨리 먹으므로 **상한**으로만 읽어야 한다. 그래서 어디서나 `≈` 를
// 붙이고 기준을 함께 적는다.
//
// NAI 가 이 상수를 바꾸면 어긋난다. 그때는 회복률(86400/timeUntilNextPercent)과
// NAI 표시 장수를 다시 나눠 보면 새 값이 나온다.
const IMAGES_PER_PERCENT = 17.3;
const IMAGE_BASIS_NOTE = '1MP · 28스텝 기준';

function imageCount(percent) {
  return Math.round(Math.max(0, Number(percent) || 0) * IMAGES_PER_PERCENT);
}

function formatImages(percent) {
  return imageCount(percent).toLocaleString();
}

export function createNaiAccountPanel({
  document,
  getWs,
  WebSocket,
  showToast,
  confirmDialog = async () => false,
  openAccountSettings = () => {},
}) {
  const byId = id => document.getElementById(id);

  const state = {
    accounts: [],           // 명부(끈 계정 포함)
    policy: 'round_robin',
    policyOptions: POLICY_FALLBACK,
    canAdd: true,
    activeCount: 0,
    balancingEffective: false,
    // 모든 계정이 0% 에 닿으면 Auto Gen 을 스스로 끈다(사용자 지정 2026-08-24).
    stopOnExhausted: false,
    // 사용자가 **직접 고른 계정**(사용자 지정 2026-08-27). 비어 있으면 부하 분산.
    // ⚠️ 서버가 '지금 쓸 수 있는지' 를 걸러 보내 준다 - 고른 계정을 꺼 버리면
    //    빈 값으로 돌아온다. 화면이 실제 동작과 어긋나지 않게 하는 유일한 길이다.
    forcedAccount: '',
    loaded: false,
  };
  // 계정별 사용량 — `nai_usage_update` 가 채운다. 명부와 수명이 다르다.
  //
  // ⚠️ 막대는 **이 목록**으로 그린다(명부가 아니라). 서버가 `active_accounts()` 로
  // 만든 '지금 회전에 들어 있는 계정' 이라 이쪽이 사실이다. 처음엔 명부를 걸러서
  // 그렸는데, 명부와 사용량이 따로 도착하는 탓에 계정을 막 추가한 직후처럼 둘이
  // 어긋난 순간에 행 수가 틀렸다(실측: 사용량엔 2개인데 화면엔 1줄).
  let usageRows = [];
  let totalPercent = null;
  // 이번 세션 요약(생성 장수 · 실행 시간). 비V5 에서 퍼센트 게이지를 대신한다.
  let session = { free: 0, total: 0, elapsed: 0, onV5: true };
  // 지금 설정으로 생성하면 Anlas 를 무는가(29스텝 이상 또는 1MP 초과). 그러면 V5
  // 무료 사용량 퍼센트는 **답이 아니다** - 깎이는 것은 Anlas 다. 그래서 패널의
  // 기준을 통째로 Anlas 로 바꾼다(사용자 지정 2026-08-28).
  //
  // ⚠️ **V5 에서만** 바꾼다. 4.5 이하는 애초에 이 무료 풀을 안 쓰므로 화면이 이미
  //    다른 것(세션 장수/실행 시간)을 보여 주고 있다 - 거기에 또 손대면 전파가 된다.
  let paidMode = false;

  /** 지금 Anlas 기준으로 보여 줄 때인가. */
  function onAnlasBasis() {
    return session.onV5 && paidMode;
  }

  /** 유료 여부가 바뀌면 다시 그린다(app.js 가 파라미터 변경마다 부른다). */
  function setPaidMode(next) {
    const value = !!next;
    if (value === paidMode) return;
    paidMode = value;
    renderPopover();
  }
  // 지금 부하 분산 묶음의 진행도. `target === 1` 이면 교체가 매 장이라 뜻이 없다.
  let rotation = { current: 0, target: 1 };
  let popOpen = false;
  // 핀. 켜면 바깥을 눌러도 안 닫힌다 - 생성하는 동안 어느 계정이 도는지 계속
  // 보려고 둔 것이다(테스트용, 사용자 요청 2026-08-21). 세션 안에서만 기억한다.
  let pinned = false;

  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function send(payload) {
    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify(payload));
    return true;
  }

  // ⚠️ 이 모듈은 **비동기 import** 라 소켓과의 선후가 매번 다르다. 실측(2026-08-21):
  // 첫 부팅에서는 모듈이 37초에야 뜨고(소켓은 이미 열림), 새로고침에서는 모듈이 먼저
  // 뜬다(소켓이 아직 안 열림). 뒤쪽 경우에 한 번 보내고 마니까 설정 화면의 계정
  // 목록이 영영 비어 있었다. 열릴 때까지 짧게 되묻는다.
  let retryTimer = null;
  let retries = 0;

  function requestAccounts() {
    if (retryTimer) { clearTimeout(retryTimer); retryTimer = null; }
    if (send({ type: 'nai_accounts_get' })) { retries = 0; return true; }
    if (retries >= 20) return false;             // 10초쯤 시도하고 포기(화면을 열면 다시 청한다)
    retries += 1;
    retryTimer = setTimeout(() => { retryTimer = null; requestAccounts(); }, 500);
    return false;
  }

  // ---- 서버 메시지 -----------------------------------------------------

  function onAccounts(message) {
    if (!message || typeof message !== 'object') return;
    state.accounts = Array.isArray(message.accounts) ? message.accounts : [];
    state.policy = message.policy || state.policy;
    if (Array.isArray(message.policy_options) && message.policy_options.length) {
      state.policyOptions = message.policy_options;
    }
    state.canAdd = message.can_add !== false;
    state.activeCount = Number(message.active_count) || 0;
    state.balancingEffective = !!message.balancing_effective;
    if (typeof message.stop_auto_gen_on_exhausted === 'boolean') {
      state.stopOnExhausted = message.stop_auto_gen_on_exhausted;
    }
    if (typeof message.forced_account_id === 'string') {
      state.forcedAccount = message.forced_account_id;
    }
    state.loaded = true;
    renderPopover();
    renderSetupList();
  }

  function onAccountResult(message) {
    if (!message) return;
    // 성공이어도 경고할 게 있을 수 있다(계정은 지웠는데 토큰이 남은 경우).
    // 서버가 `level` 을 주면 그걸 따른다.
    if (message.message) {
      showToast(message.message, message.level || (message.ok ? 'info' : 'error'));
    }
    setSetupBusy(false);
  }

  // 배지 메시지에서 계정별 사용량만 뽑아 둔다. 배지 자체(퍼센트/숨김)는 app.js 담당.
  function onUsageUpdate(message) {
    if (!message || !message.available) {
      usageRows = [];
      totalPercent = null;
      // 배지가 사라지면 팝오버도 같이 닫는다 - 앵커 없이 떠 있으면 유령이다.
      closePopover();
      renderPopover();
      return;
    }
    totalPercent = Number.isFinite(message.percent) ? message.percent : null;
    session = {
      free: Number(message.free_generations) || 0,
      // ⚠️ 비V5 화면은 **이 값**을 쓴다. 무료 카운터를 띄웠더니 V4.5 생성은 정의상
      // 무료가 아니라 숫자가 영영 안 움직였다(사용자 지적 2026-08-21).
      total: Number(message.session_generations) || 0,
      elapsed: Number(message.elapsed_seconds) || 0,
      onV5: message.uses_usage_limit !== false,
    };
    // 지금 묶음의 진행도(라운드 로빈-10 / 80~120 / 400~500). 1이면 게이지를 안 그린다.
    rotation = {
      current: Number(message.rotation_current) || 0,
      target: Math.max(1, Number(message.rotation_target) || 1),
    };
    // 정책 목록은 **모델 계열마다 다르다** - 모델을 바꾸면 이 메시지로 함께 온다.
    if (Array.isArray(message.policy_options) && message.policy_options.length) {
      state.policyOptions = message.policy_options;
    }
    const rows = Array.isArray(message.accounts) ? message.accounts : [];
    if (rows.length) {
      usageRows = rows.filter(row => row && row.id);
    } else {
      // 계정이 하나면 서버는 `accounts` 를 안 붙인다(요청을 아끼려고). 그때는
      // 배지 값이 곧 그 계정의 값이므로 명부에서 활성 하나를 찾아 한 줄로 만든다.
      const only = state.accounts.find(a => a.enabled && a.has_token);
      usageRows = only ? [{
        id: only.id, label: only.label, token_preview: only.token_preview,
        available: true, percent: totalPercent || 0, is_negative: !!message.is_negative,
      }] : [];
    }
    if (message.policy) state.policy = message.policy;
    if (typeof message.balancing_effective === 'boolean') {
      state.balancingEffective = message.balancing_effective;
    }
    renderPopover();
  }

  // ---- 배지 팝오버 -----------------------------------------------------

  function popEl() {
    return byId('naiAcctPop');
  }

  function openPopover() {
    const el = popEl();
    if (!el) return;
    // 명부를 아직 못 받았으면 지금 받아 온다(배지만 보고 한 번도 안 열어본 경우).
    if (!state.loaded) requestAccounts();
    popOpen = true;
    renderPopover();
    el.classList.remove('hidden');
  }

  function closePopover() {
    popOpen = false;
    const el = popEl();
    if (el) el.classList.add('hidden');
  }

  function togglePopover() {
    if (popOpen) closePopover();
    else openPopover();
  }

  function barHtml(percent, isOut) {
    const width = Math.max(0, Math.min(100, Number(percent) || 0));
    return `<span class="nai-acct-bar${isOut ? ' is-out' : ''}"><i style="width:${width}%"></i></span>`;
  }

  /** 지금 묶음의 진행 게이지(연노랑). 사용자 요청 2026-08-21. */
  function blockBarHtml() {
    const width = Math.max(0, Math.min(100, (rotation.current / rotation.target) * 100));
    return `<span class="nai-acct-bar is-block"><i style="width:${width}%"></i></span>`;
  }

  /**
   * 계정 한 줄의 회전 상태 문구.
   *
   * 명세(사용자 2026-08-21): `( 목표 : *장, 현재 : *장 | 총 ****장 )`,
   * 쉬고 있으면 `( 대기중 | 총 ****장 )`.
   *
   * ⚠️ 목표/현재는 **묶음형 정책에서만** 뜻이 있다. 라운드 로빈(1장)이나 동적 할당은
   * 매 장 교체라 목표가 늘 1이고 현재가 늘 0이어서, 그대로 적으면 고장 난 것처럼
   * 보인다. 그때는 '사용중' 으로만 적는다.
   */
  function rotationText(row) {
    const total = `총 ${(Number(row.session_count) || 0).toLocaleString()}장`;
    if (!row.is_next) return `대기중 | ${total}`;
    if (rotation.target <= 1) return `사용중 | ${total}`;
    return `목표 ${rotation.target.toLocaleString()}장 · `
      + `현재 ${rotation.current.toLocaleString()}장 | ${total}`;
  }

  /** 초 -> `1시간 23분` / `12분` / `48초`. 세션이 얼마나 돌았는지 한눈에. */
  function formatElapsed(seconds) {
    const total = Math.max(0, Math.floor(Number(seconds) || 0));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    if (h) return `${h}시간 ${m}분`;
    if (m) return `${m}분`;
    return `${total}초`;
  }

  // 막대와 헤더 합계가 **같은 목록**을 봐야 한다 - 갈라 두면 언젠가 어긋난다.
  function accountUsageRows() {
    // 사용량이 왔으면 그걸 쓰고, 아직이면 명부의 활성 계정을 '—' 로 미리 그린다
    // (계정을 막 켠 직후 다음 조회까지의 공백을 빈 화면으로 두지 않는다).
    return usageRows.length
      ? usageRows
      : state.accounts.filter(a => a.enabled && a.has_token)
          .map(a => ({ ...a, available: false, percent: 0 }));
  }

  /**
   * 재결제까지 남은 일수의 급함(사용자 지정 2026-09-03).
   *
   *   8일 이상 → 기본(약간 덜 밝은 흰색) · 4~7 → 연노랑 · 2~3 → 연주황 · 1 → 주황 ·
   *   0 → 빨강에 가까운 주황
   *
   * ⚠️ 경계를 **아래에서 위로** 본다. 위에서부터 `>= 8` 로 시작하면 음수가 기본색으로
   *    빠진다 - 백엔드가 0 으로 깎아 보내지만 이 함수만 따로 쓰이면 그때 무너진다.
   */
  function renewClass(days) {
    if (days <= 0) return ' is-due';      // 오늘 빠진다
    if (days <= 1) return ' is-d1';
    if (days <= 3) return ' is-d3';
    if (days <= 7) return ' is-d7';
    return '';                            // 8일 이상 - 아직 급하지 않다
  }

  function accountRowsHtml() {
    const rows = accountUsageRows();
    if (!rows.length) {
      return '<div class="nai-acct-empty">활성 계정이 없습니다.</div>';
    }
    // Anlas 기준일 때 게이지의 분모. **계정 중 가장 많은 쪽**을 100% 로 둔다.
    //
    // ⚠️ '전체 합계 대비 점유율' 로 하면 계정 넷이 고르게 남았을 때 전부 25% 라
    //    막대가 다 같아 보여 아무것도 못 읽는다. 이 패널이 답해야 하는 질문은
    //    "어느 계정이 말랐나" 이므로 **가장 많은 계정 대비**가 맞다.
    const anlasMax = Math.max(
      1, ...rows.map(r => (Number.isFinite(r.anlas) ? r.anlas : 0)));
    return rows.map(row => {
      const known = !!row.available;
      // 사용자 표기(명세)는 토큰 앞자리 — 어느 계정인지 한눈에 구분되는 값이다.
      const name = (row.token_preview || row.label || '').toUpperCase();
      const pct = known ? `${Number(row.percent) || 0}%` : '—';
      // ⚠️ 툴팁은 쓰지 않는다. 계정 이름을 띄웠더니 바로 옆 칸이 이미 같은 말을
      // 하고 있어 순수 낭비였다(사용자 지적). 숫자는 게이지 **아래에 직접** 적는다.
      const anlas = Number.isFinite(row.anlas) ? row.anlas.toLocaleString() : '—';
      const remain = known && !row.is_negative
        ? `~${formatImages(row.percent)}`
        : (row.is_negative ? '소진' : '—');
      // ⚠️ **사용량 게이지와 퍼센트는 V5 에서만 그린다**(사용자 지시 2026-08-21).
      // V4.5 이하는 이 무료 풀을 쓰지 않으므로 퍼센트를 띄우면 거짓말이 된다 -
      // 그 자리에는 지금 묶음의 진행 게이지(연노랑)를 그린다.
      const showBlock = !session.onV5 && row.is_next && rotation.target > 1;
      // ⚠️ 계정이 하나뿐이면 고를 것이 없다 - 눌러도 아무 일이 없는 자리를 만들지
      //    않는다. 둘 이상일 때만 누를 수 있게 하고, 고른 줄은 표시가 남는다.
      const pickable = rows.length > 1;
      const forced = pickable && row.id === state.forcedAccount;
      const cls = `nai-acct-row${row.is_next ? ' is-next' : ''}`
        + `${pickable ? ' is-pick' : ''}${forced ? ' is-forced' : ''}`;
      const open = pickable
        ? `<button type="button" class="${cls}" data-pick-account="${esc(row.id)}"`
          + ` aria-pressed="${forced ? 'true' : 'false'}"`
          + ` title="${forced ? '이 계정만 사용 - 해제하려면 다시 누르세요'
            : '이 계정만 사용합니다 (부하 분산 해제)'}">`
        : `<div class="${cls}">`;
      return open
        + '<div class="nai-acct-line">'
        + `<span class="nai-acct-name">${esc(name)}</span>`
        + (onAnlasBasis()
          ? barHtml(Number.isFinite(row.anlas) ? (row.anlas / anlasMax) * 100 : 0,
            Number.isFinite(row.anlas) && row.anlas <= 0)
            + `<span class="nai-acct-pct">${esc(anlas)}</span>`
          : session.onV5
            ? barHtml(known ? row.percent : 0, known && row.is_negative)
              + `<span class="nai-acct-pct">${esc(pct)}</span>`
            : (showBlock
              ? blockBarHtml()
                + `<span class="nai-acct-pct">${rotation.current}/${rotation.target}</span>`
              : '<span class="nai-acct-spacer"></span>'))
        + '</div>'
        + '<div class="nai-acct-sub">'
        // Anlas 기준일 때는 오른쪽 라벨이 이미 Anlas 다 - 여기서 또 말하면 같은
        // 숫자를 두 번 하는 꼴이라(2026-08-21 지적의 그 문제) 무료 잔량을 대신
        // 적어 "이만큼은 아직 공짜" 를 남긴다.
        + (onAnlasBasis()
          ? `<span>무료 ${esc(remain)}장</span>`
          : `<span>Anlas ${esc(anlas)}</span>`)
        + (onAnlasBasis()
          ? ''
          : session.onV5
            ? `<i>|</i><span>NAID5 Remain : ${esc(remain)}</span>`
            : `<i>|</i><span>${esc(rotationText(row))}</span>`)
        // 재결제까지 남은 일수(사용자 요청 2026-09-03). 줄 오른쪽 빈자리에 붙는다.
        // 백엔드가 **내림**한 정수를 주므로 시간 단위로 남으면 "0일" 이다 - 정확한
        // 시각은 일부러 안 보여 준다. 모르면(null) 칸을 비운다.
        + (Number.isInteger(row.renews_in_days)
          ? `<span class="nai-acct-renew${renewClass(row.renews_in_days)}">`
            + `갱신 ${row.renews_in_days}일</span>`
          : '')
        + '</div>'
        + (forced ? '<span class="nai-acct-only">이 계정만 사용</span>' : '')
        + (pickable ? '</button>' : '</div>');
    }).join('');
  }

  function policiesHtml() {
    // ⚠️ 계정을 지목했으면 **아무 정책도 켜지지 않는다**(사용자 지정 2026-08-27).
    //    지목은 "나눠 쓰지 마라" 는 뜻이라, 라디오가 켜진 채로 두면 둘 다 도는
    //    것처럼 읽힌다. 정책을 다시 누르면 지목이 풀린다.
    const forced = !!state.forcedAccount;
    const disabled = (state.balancingEffective && !forced) ? '' : ' is-idle';
    return state.policyOptions.map(option => {
      const on = !forced && option.key === state.policy;
      return `<button type="button" class="nai-acct-policy${on ? ' on' : ''}${disabled}"`
        + ` data-policy="${esc(option.key)}">`
        + `<span class="nai-acct-radio">${on ? '●' : '○'}</span>`
        + `<span class="nai-acct-policy-text">`
        + `<b>${esc(option.label)}</b>`
        + `<em>${esc(option.desc)}</em>`
        + '</span></button>';
    }).join('');
  }

  /** 무료 사용량이 다 마르면 Auto Gen 을 스스로 끄는 스위치(사용자 지정 2026-08-24).
   *
   *  ⚠️ **V5 에서만 그린다.** 무료 풀이 없는 계열에는 퍼센트가 없어 판정 자체가 서지
   *     않고, 백엔드도 같은 조건으로 물러난다 - 안 듣는 스위치를 그리면 거짓말이다.
   *  ⚠️ '완전히 0' 이 아니라 **모두 0%** 다. 하나라도 남아 있으면 부하 분산이 그쪽으로
   *     옮겨 계속 무료로 생성한다.
   */
  function guardHtml() {
    const on = !!state.stopOnExhausted;
    // ⚠️ **기준이 상태에 따라 달라진다.** 계정을 하나 지목하면 생성이 그 계정으로만
    //    나가므로 백엔드도 그 계정 하나로 판정한다(`generation_quota_exhausted`).
    //    설명이 '모든 계정' 이라고 계속 말하면 거짓말이 된다 - 바뀐 자리를 눈에
    //    띄게 적어 준다(사용자 지정 2026-08-27).
    const narrow = !!state.forcedAccount;
    const basis = narrow ? '(선택 계정 사용량 0% 기준)' : '(모든 계정 사용량 0% 기준)';
    return '<div class="nai-acct-sec">Safety</div>'
      + `<button type="button" class="nai-acct-policy nai-acct-guard${on ? ' on' : ''}"`
      + ` data-act="guard" aria-pressed="${on ? 'true' : 'false'}">`
      + `<span class="nai-acct-check">${on ? '✔' : ''}</span>`
      + '<span class="nai-acct-policy-text">'
      + '<b>사용량 0% 도달 시 자동 생성 해제</b>'
      + '<em>Auto Gen 을 끕니다. Automation 정책보다 우선합니다. '
      + `<span class="nai-acct-basis${narrow ? ' is-narrow' : ''}">${basis}</span></em>`
      + '</span></button>';
  }

  function renderPopover() {
    const el = popEl();
    if (!el || !popOpen) return;
    // ⚠️ **V5 와 비V5 는 다른 화면이다**(사용자 지시 2026-08-21).
    //   V5   : 퍼센트/게이지 그대로 - 그 무료 풀을 실제로 쓰고 있으니 잔량이 답이다.
    //   비V5 : 퍼센트가 뜻이 없다(그 풀을 안 쓴다). 대신 **이번 세션 무료 생성 수 +
    //          실행 시간** 을 보여 준다. V5 에서는 이 값이 가치가 없다 - 잔량이 이미
    //          같은 질문에 더 정확히 답한다.
    const rows = accountUsageRows();
    const live = rows.filter(r => r.available && !r.is_negative);
    const sumImages = live.reduce((s, r) => s + imageCount(r.percent), 0);
    const sumAnlas = rows.reduce((s, r) => s + (Number.isFinite(r.anlas) ? r.anlas : 0), 0);
    const total = totalPercent == null ? '—' : `${totalPercent}%`;
    el.innerHTML = ''
      + '<div class="nai-acct-head">'
      + '<span class="nai-acct-title">USAGE</span>'
      + `<button type="button" class="nai-acct-pin${pinned ? ' on' : ''}" data-act="pin"`
      + ` aria-pressed="${pinned ? 'true' : 'false'}"`
      + ` title="${pinned ? '고정 해제' : '열어 둔 채 고정'}">${pinned ? '📌' : '📍'}</button>`
      // ⚠️ 세 자리가 **같은 숫자를 세 번** 말하면 안 된다(사용자 지적 2026-08-21:
      // "USAGE 137, USAGE 137장, 이번 세션 생성 137장 이렇게 3번 연달아 나온다").
      // 배지 = 총 장수 · 헤더 = 무료/총 · 세션 줄 = Anlas 로 나간 장수. 각자 다른
      // 사실을 말한다.
      + (onAnlasBasis()
        ? `<span class="nai-acct-total is-anlas">Anlas ${sumAnlas.toLocaleString()}</span>`
        : session.onV5
          ? `<span class="nai-acct-total">통합 ${esc(total)}</span>`
          : `<span class="nai-acct-total">무료 ${session.free.toLocaleString()}`
            + `<i> / ${session.total.toLocaleString()}장</i></span>`)
      + '</div>'
      // ⚠️ 'Anlas 소비 N장' 과 무료 조건 안내는 뺐다(사용자 지시 2026-08-21:
      // "정보량이 과다하게 많아 그냥 치웁시다"). 헤더의 `무료 130 / 137장` 이
      // 이미 같은 것을 말하고, 조건 안내는 배지 툴팁에 남아 있다.
      + (session.onV5 ? ''
        : '<div class="nai-acct-session">'
          + `<em>실행 ${esc(formatElapsed(session.elapsed))}</em></div>`)
      + (rows.length > 1
        ? '<div class="nai-acct-sum">'
          // Anlas 기준일 때 헤더가 이미 같은 합계를 말한다 - 여기서 또 적으면
          // 한 화면이 같은 숫자를 두 번 하는 꼴이다(2026-08-21 지적).
          + (onAnlasBasis() ? '' : `<span>Anlas ${sumAnlas.toLocaleString()}</span>`)
          + (onAnlasBasis()
            ? `<span>무료 ~${sumImages.toLocaleString()}장 남음</span>`
              + '<em>지금 설정은 Anlas 를 씁니다</em>'
            : session.onV5
              ? `<i>|</i><span>NAID5 Remain : ~${sumImages.toLocaleString()}</span>`
                + `<em>${esc(IMAGE_BASIS_NOTE)}</em>`
              : '')
          + '</div>'
        : '')
      + `<div class="nai-acct-rows">${accountRowsHtml()}</div>`
      + '<button type="button" class="nai-acct-manage" data-act="manage">'
      + '<span>＋</span> Manage Account</button>'
      // ⚠️ 정책 **위**에 둔다. 아래에 두면 정책 설명 4개 뒤라 스크롤에 묻히는데,
      //    이건 돈이 새는 것을 막는 스위치라 눈에 보여야 한다(실측: 팝오버가
      //    scrollHeight 631 / clientHeight 534 로 잘려 있었다).
      + (session.onV5 ? guardHtml() : '')
      + '<div class="nai-acct-sec">Load Balancing</div>'
      + `<div class="nai-acct-policies">${policiesHtml()}</div>`
      + (state.forcedAccount
        ? '<div class="nai-acct-note">계정을 직접 고른 상태입니다. '
          + '정책을 누르면 다시 부하 분산으로 돌아갑니다.</div>'
        : (state.balancingEffective ? ''
          : '<div class="nai-acct-note">활성 계정이 2개 이상일 때 적용됩니다.</div>'));
  }

  function onPopoverClick(event) {
    const pin = event.target.closest('[data-act="pin"]');
    if (pin) {
      pinned = !pinned;
      renderPopover();
      return;
    }
    const manage = event.target.closest('[data-act="manage"]');
    if (manage) {
      closePopover();
      openAccountSettings();
      return;
    }
    const guard = event.target.closest('[data-act="guard"]');
    if (guard) {
      state.stopOnExhausted = !state.stopOnExhausted;  // 낙관적 - 서버 스냅샷이 확정한다
      renderPopover();
      send({ type: 'nai_account_set_stop_on_exhausted', enabled: state.stopOnExhausted });
      return;
    }
    // 계정 줄을 누르면 그 계정만 쓴다. 이미 고른 줄을 다시 누르면 해제된다 -
    // 되돌리는 길이 정책 라디오 하나뿐이면 "어떻게 푸는지" 를 알 수 없다.
    // ⚠️ `data-pick-account` 다. `data-account` 는 설정 페이지의 계정 목록이 쓰는
    //    이름이라 같은 이름을 두 뜻으로 쓰지 않는다.
    const account = event.target.closest('[data-pick-account]');
    if (account) {
      const id = account.getAttribute('data-pick-account');
      const next = state.forcedAccount === id ? '' : id;
      state.forcedAccount = next;  // 낙관적 반영 - 서버 스냅샷이 곧 확정한다.
      renderPopover();
      send({ type: 'nai_account_set_forced', account_id: next });
      return;
    }
    const policy = event.target.closest('[data-policy]');
    if (policy) {
      const key = policy.getAttribute('data-policy');
      // ⚠️ **커맨드는 하나다.** 예전에는 `set_forced('')` 를 먼저 보내고 이어서
      //    `set_policy` 를 보냈는데, 그 사이는 원자적이지 않다 - 틈에 Auto Gen 이
      //    토큰을 고르면 화면은 새 정책인데 실제 이미지는 옛 지목 계정으로 나간다
      //    (Codex 리뷰 2026-08-27). 이제 서버의 `set_policy` 가 한 잠금 안에서
      //    지목까지 푼다. 같은 정책을 다시 눌러도 보내는 이유가 그것이다.
      const wasForced = !!state.forcedAccount;
      state.forcedAccount = '';    // 낙관적 반영 - 서버 스냅샷이 곧 확정한다.
      if (key === state.policy && !wasForced) { renderPopover(); return; }
      state.policy = key;
      renderPopover();
      send({ type: 'nai_account_set_policy', policy: key });
    }
  }

  // 바깥을 누르면 닫힌다. 배지 자신은 토글이므로 제외해야 **열자마자 닫히지 않는다.**
  // 핀이 켜져 있으면 바깥 클릭으로는 안 닫는다(배지를 다시 누르면 닫힌다).
  function onDocumentPointerDown(event) {
    if (!popOpen || pinned) return;
    const el = popEl();
    const pill = byId('naiUsagePill');
    if (!el) return;
    if (el.contains(event.target)) return;
    if (pill && pill.contains(event.target)) return;
    closePopover();
  }

  // ---- 설정 대화상자의 계정 관리 ----------------------------------------

  function setSetupBusy(busy) {
    const host = byId('setupAccounts');
    if (host) host.classList.toggle('is-busy', !!busy);
  }

  function renderSetupList() {
    const list = byId('setupAccountsList');
    if (!list) return;
    if (!state.accounts.length) {
      list.innerHTML = '<div class="setup-account-empty">계정 정보를 불러오는 중…</div>';
      return;
    }
    list.innerHTML = state.accounts.map(account => {
      const idAttr = esc(account.id);
      const preview = account.has_token ? `${esc(account.token_preview)}…` : '미설정';
      // ⚠️ 메인 계정에는 토큰 칸을 **주지 않는다.** 바로 위 '영구 토큰' 칸이 같은
      // 토큰을 관리하므로, 여기에도 두면 같은 값을 넣는 입력이 화면에 둘이 된다.
      // 메인 행이 여기 있는 이유는 오직 "회전에 넣을까 뺄까" 하나다. 삭제도 없다.
      const own = !account.is_main;
      return `<div class="setup-account" data-account="${idAttr}">`
        + '<div class="setup-account-top">'
        + '<label class="setup-account-toggle">'
        + `<input type="checkbox" data-act="toggle" ${account.enabled ? 'checked' : ''}`
        + `${account.has_token ? '' : ' disabled'}>`
        + `<span>${esc(account.label)}</span></label>`
        // 중복은 입력 단계에서 막지만, 메인 토큰은 위쪽 '영구 토큰' 칸으로도
        // 바뀌므로 이미 겹쳐 있는 상태가 생길 수 있다. 그때는 말이라도 해 준다.
        + (account.duplicate_of
          ? `<span class="setup-account-dupe" data-naia-title="${esc(account.duplicate_of)}와(과) 같은 토큰입니다 - 사용량 한도는 늘지 않습니다">중복</span>`
          : '')
        + `<span class="setup-account-preview">${preview}</span>`
        + (own ? '<button type="button" class="setup-account-del" data-act="delete"'
          + ' title="계정 삭제">✕</button>' : '')
        + '</div>'
        + (own
          ? '<div class="setup-account-row">'
            + '<input class="setup-input setup-input-mono" type="password" data-act="token-input"'
            + ` placeholder="${account.has_token ? '저장됨 - 새 토큰을 붙여넣으면 교체됩니다' : 'NovelAI 토큰 붙여넣기'}"`
            + ' autocomplete="off" spellcheck="false">'
            + '<button type="button" class="setup-btn-primary setup-account-save"'
            + ' data-act="token-save">확인 후 저장</button>'
            + '</div>'
          : '<div class="setup-account-note">위 <b>영구 토큰</b> 칸에서 관리합니다.</div>')
        + '</div>';
    }).join('');
    const addBtn = byId('setupAccountAdd');
    if (addBtn) {
      addBtn.disabled = !state.canAdd;
      addBtn.textContent = state.canAdd ? '＋ 계정 추가' : '계정 수 상한에 도달했습니다';
    }
  }

  async function onSetupListClick(event) {
    const host = event.target.closest('[data-account]');
    if (!host) return;
    const accountId = host.getAttribute('data-account');
    const action = event.target.closest('[data-act]');
    if (!action) return;
    const act = action.getAttribute('data-act');

    if (act === 'toggle') {
      send({ type: 'nai_account_set_enabled', account_id: accountId,
             enabled: !!action.checked });
      return;
    }
    if (act === 'token-save') {
      const input = host.querySelector('[data-act="token-input"]');
      const token = input ? input.value.trim() : '';
      if (!token) {
        showToast('토큰을 먼저 붙여넣으세요.', 'error');
        return;
      }
      setSetupBusy(true);
      if (send({ type: 'nai_account_set_token', account_id: accountId, token })) {
        if (input) input.value = '';
      } else {
        setSetupBusy(false);
      }
      return;
    }
    if (act === 'delete') {
      const label = (state.accounts.find(a => a.id === accountId) || {}).label || accountId;
      const ok = await Promise.resolve(confirmDialog(
        `${label}을(를) 삭제할까요? 저장된 토큰도 함께 지워집니다.`,
        { title: '계정 삭제', okText: '삭제', cancelText: '취소' }));
      if (!ok) return;
      send({ type: 'nai_account_delete', account_id: accountId });
    }
  }

  function onAddClick() {
    if (!state.canAdd) return;
    send({ type: 'nai_account_add' });
  }

  // ---- 배선 -------------------------------------------------------------

  function bind() {
    const pill = byId('naiUsagePill');
    if (pill) {
      pill.addEventListener('click', togglePopover);
      pill.setAttribute('role', 'button');
      pill.setAttribute('tabindex', '0');
      pill.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          togglePopover();
        }
      });
    }
    const pop = popEl();
    if (pop) pop.addEventListener('click', onPopoverClick);
    document.addEventListener('pointerdown', onDocumentPointerDown, true);

    const list = byId('setupAccountsList');
    if (list) list.addEventListener('click', onSetupListClick);
    const addBtn = byId('setupAccountAdd');
    if (addBtn) addBtn.addEventListener('click', onAddClick);
  }

  bind();

  return {
    requestAccounts,
    onAccounts,
    onAccountResult,
    onUsageUpdate,
    openPopover,
    closePopover,
    togglePopover,
    renderSetupList,
    setPaidMode,
  };
}
