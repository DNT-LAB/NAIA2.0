/**
 * Event Corpus Search — 프론트 WS 클라이언트.
 *
 * 백엔드 계약: app/backend/server/event_corpus_commands.py
 *   요청  event_corpus_status  {requestId}
 *         event_corpus_query   {requestId, rating, person, include[], exclude[], search, offset, limit}
 *   응답  event_corpus_status_result / event_corpus_query_result
 *
 * 백엔드가 이미 stale-send guard 로 superseded 응답을 버린다(연결별 seq guard). 여기서
 * requestId 를 다시 비교하는 것은 2차 방어선이다 — 재연결 직후 이전 연결의 응답이 남아 있거나,
 * 여러 패널이 같은 소켓을 공유하는 경우를 막는다.
 *
 * 이 모듈은 상태를 소유하지 않는다. 호출자가 rating/person/include/exclude 를 들고 있고,
 * 여기서는 in-flight 추적과 응답 라우팅만 한다.
 */

const PENDING = new Map();       // requestId -> {resolve, reject, kind}
let seqCounter = 0;
let latestQueryId = '';

function nextRequestId(kind) {
  seqCounter += 1;
  return `ec_${kind}_${seqCounter}`;
}

function settle(requestId, payload) {
  const entry = PENDING.get(requestId);
  if (!entry) return false;
  PENDING.delete(requestId);
  if (payload && payload.ok === false) {
    const error = new Error(payload.message || payload.code || 'event corpus error');
    error.code = payload.code || 'unknown';
    error.payload = payload;
    entry.reject(error);
  } else {
    entry.resolve(payload);
  }
  return true;
}

/**
 * 소켓이 끊기면 대기 중인 약속을 전부 정리한다. 정리하지 않으면 재연결 후에도
 * 영원히 pending 인 Promise 가 남아 호출자의 로딩 상태가 풀리지 않는다.
 */
export function resetEventCorpusClient(reason = 'disconnected') {
  for (const [, entry] of PENDING) {
    const error = new Error(reason);
    error.code = 'disconnected';
    entry.reject(error);
  }
  PENDING.clear();
  latestQueryId = '';
}

export function requestEventCorpusStatus(send) {
  const requestId = nextRequestId('status');
  return new Promise((resolve, reject) => {
    PENDING.set(requestId, { resolve, reject, kind: 'status' });
    try {
      send({ type: 'event_corpus_status', requestId });
    } catch (error) {
      PENDING.delete(requestId);
      reject(error);
    }
  });
}

/**
 * @param {function} send  WS 송신 함수
 * @param {object} params  {rating, person, include, exclude, search, offset, limit}
 */
export function requestEventCorpusQuery(send, params = {}) {
  const requestId = nextRequestId('query');
  latestQueryId = requestId;

  // 이전 in-flight 질의는 버린다. 백엔드도 superseded 를 안 보내지만, 사용자가 칩을
  // 연타하면 응답이 오기 전에 여러 Promise 가 쌓이므로 호출자 쪽도 정리해준다.
  for (const [id, entry] of [...PENDING]) {
    if (entry.kind === 'query' && id !== requestId) {
      PENDING.delete(id);
      const error = new Error('superseded');
      error.code = 'superseded';
      entry.reject(error);
    }
  }

  const payload = {
    type: 'event_corpus_query',
    requestId,
    rating: String(params.rating || 's'),
    person: String(params.person || '1girl_solo'),
    include: Array.isArray(params.include) ? params.include : [],
    exclude: Array.isArray(params.exclude) ? params.exclude : [],
    search: String(params.search || ''),
    offset: Number.isFinite(params.offset) ? Math.max(0, params.offset | 0) : 0,
    limit: Number.isFinite(params.limit) ? params.limit | 0 : 60,
  };

  return new Promise((resolve, reject) => {
    PENDING.set(requestId, { resolve, reject, kind: 'query' });
    try {
      send(payload);
    } catch (error) {
      PENDING.delete(requestId);
      reject(error);
    }
  });
}

export function onEventCorpusStatusResult(message) {
  settle(String(message?.requestId || ''), message);
}

export function onEventCorpusQueryResult(message) {
  const requestId = String(message?.requestId || '');
  // 2차 방어선: 최신 질의가 아니면 버린다.
  if (requestId && latestQueryId && requestId !== latestQueryId) {
    PENDING.delete(requestId);
    return;
  }
  settle(requestId, message);
}

/** app.js 의 WS 핸들러 맵에 펼쳐 넣는다. */
export const EVENT_CORPUS_WS_HANDLERS = {
  event_corpus_status_result: onEventCorpusStatusResult,
  event_corpus_query_result: onEventCorpusQueryResult,
};

/** 사용자에게 보일 오류 문구. 백엔드 code 와 1:1. */
export const EVENT_CORPUS_ERROR_TEXT = {
  corpus_unavailable: '이벤트 코퍼스 데이터가 설치되지 않았습니다.',
  partition_unavailable: '선택한 등급/인원 조합의 데이터가 없습니다.',
  unknown_include_tags: '포함 태그 중 사전에 없는 태그가 있습니다.',
  conflicting_tags: '같은 태그를 포함과 제외에 동시에 넣을 수 없습니다.',
  invalid_request: '요청 값이 올바르지 않습니다.',
  numpy_unavailable: '서버에서 numpy를 사용할 수 없습니다.',
  internal_error: '코퍼스 조회 중 오류가 발생했습니다.',
};
