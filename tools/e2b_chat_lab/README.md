# E2B Chat Lab

NAIA의 검색 자산을 사용하는 독립 로컬 실험 WebUI. 기존 `OllamaChatAgent`, Assist, 생성 파이프라인을 실행하지 않는다.

## 실행

저장소 루트의 PowerShell에서:

```powershell
powershell -ExecutionPolicy Bypass -File tools/e2b_chat_lab/run.ps1
```

브라우저: http://127.0.0.1:7362/

기본 Ollama endpoint는 `http://127.0.0.1:11435`, 모델은 설치되어 있던 `gemma4:e2b-it-qat`다. 기존 NAIA의 11434와 별도 포트를 쓴다. launcher는 설치된 Ollama만 실행하며 패키지·모델 다운로드나 설치를 하지 않는다. venv의 FastAPI, uvicorn, requests, pandas, pyarrow 및 NAIA 기존 의존성을 사용한다.

직접 실행하거나 다른 설치된 E2B를 선택하려면:

```powershell
venv/Scripts/python.exe -X utf8 tools/e2b_chat_lab/server.py --ollama http://127.0.0.1:11435 --model gemma4:e2b-it-qat
```

`--user-data`로 검색할 NAIA user-data 디렉터리, `--event-map`으로 `.naiamap` 경로, `--state-dir`로 선호 저장 위치를 지정한다. 기본 자산 경로는 로컬 NAIA-Portable/user-data와 저장소 data다. NAIA 웹 서버가 실행되어 있을 필요는 없다. 모델을 바꾸어도 모든 호출의 think는 false다.

## 동작 (creative-grounding-v9)

1. **해석과 장면 제안**: `intent.md`는 먼저 원문의 관계·외형·시점 등 유지 조건을 영어로 해석하고, `scene_proposal_en`에 구체적 자세와 조명·색감·배경을 제안한다. `must_keep`에는 사용자 조건만 넣도록 지시하며 제안은 조건이나 선호로 승격하지 않는다. 원문은 서버가 그대로 보존한다.
2. **원문과 제안 검색**: 한국어 원문 자체를 먼저 독립 조회하고, 모델의 핵심 개념·창의적 세부 묘사 검색어를 함께 사용한다. 태그 검색은 최대 6회이며 Event Map 2회분을 예약한다. 다른 조회가 있으면 태그 호출 수를 줄인다. 가능한 경우 동작+물체, 장소+내용물 조합으로 Event Map을 조회한다. 첫 교집합이 비면 단일 pin 재시도를 우선한다. 유효한 pin·자산이 없으면 조회 불가를 명시한다.
3. **발견 후보 허용**: 원문과 단어가 겹치지 않는다는 이유로 조명·배경·구체적 과일 등을 버리지 않는다. `creative_retrieval.py`는 핵심 후보 공간과 검색별 확장 후보 공간을 나누어 최대 14개를 전달한다. 명시적 제외 후보는 거르고, 원문에 직접 대응하는 고유 사전 키워드를 보존한다. 설명·group/subgroup을 함께 읽고 의미 적합성은 모델이 판단한다. 후보나 taxonomy 링크, 이벤트 공출현만으로 적합성이 보증되지는 않는다.
4. **시각적 구성**: `answer.md`가 제안·검색 근거·원문을 받아 한국어 구성 설명 + 영어 프롬프트를 작성한다. 구체적 재질, 색 대비, 배경 깊이, 빛 방향과 동작을 활용하도록 지시한다. 적합한 Danbooru 태그와 관계를 표현하는 영어 문장을 조합하며 최종 문구 전체가 검증된 태그라고 주장하지 않는다.
5. **원문 조건 점검**: `review.md`는 선택적 장식의 추가를 허용하고, 명시적 사용자 조건과의 실제 충돌만 찾는다. 잘못된 번역을 그대로 재사용하지 않고 원문과 고유 사전 대응어를 검토에 전달한다. 수정 의견은 실제 사용자 원문에 있는 짧은 근거 인용을 동반해야 자동 수정에 쓰인다. 수정은 최대 한 번이며 미해결/점검 불가를 표시한다. 작은 모델은 실제 오류도 놓칠 수 있으므로 ‘발견된 문제 없음’은 정확성 보증이 아니다.
6. **실패와 기억**: 의도 JSON이 실패하면 원문으로 일반 답변을 한 번 재생성한다. 장면 요청에는 가능한 검색과 Event Map을 수행하고 최종 검증 미완료를 표시한다. 취소·새 대화·시간 초과·연결 실패·필수 문맥 초과는 새 fallback 추론을 시작하지 않는다. 매 라운드 원문 기반 압축을 수행하며 직전 사용자/답변 전체는 라우터·일반 대화·fallback에서 읽는다. 장면 답변은 현재 해석과 원문을 사용하고 이전 답변 문구를 그대로 재생하지 않는다.

정상 장면은 모델 4회(해석·답변·점검·압축), 한 번 수정하면 6회다. 일반 대화는 기본 3회이며 검색/점검을 강제하지 않는다. 답변·수정·fallback의 temperature는 **0.65**, 해석·점검·압축은 **0.15**다. 도구 최대 8회, 전체 300초, 개별 HTTP read timeout 최대 120초다. 모든 호출은 `think:false`와 선택한 `options.num_ctx`를 사용한다. 별도 thinking 필드는 거부하며, 내부 계산 자체가 없다는 뜻은 아니다.

`pipeline.py`의 v7 설계/변환 helpers와 `retrieval.py`의 v8 필터는 이전 실험 재현용이다. v9 실행은 `relations.py`, `creative_retrieval.py`, `intent.md`, `answer.md`, `review.md`, `fallback.md`, `compact.md`를 사용한다.

## 컨텍스트 크기와 예산

우측 컨텍스트 선택에서 **8K(기본), 16K, 32K**만 허용한다. `POST /api/settings`의 `context_size`도 같은 정수 세 개만 받는다. 선택값은 `--state-dir/settings.json`에 저장되어 새 대화와 서버 재실행 후에도 유지된다. 사용자 선호와 별도의 실행 설정이며 대화 원문을 저장하지 않는다. 답변 생성 중 변경은 UI에서 비활성화되고 API에서도 409로 거부된다. 한 라운드의 모든 모델 호출은 시작 시 선택한 크기를 사용한다. 다음 메시지의 첫 모델 호출에서 Ollama가 해당 크기를 적용하므로 모델 재로딩 지연이 생길 수 있다.

각 호출은 선택한 크기에서 출력 예약(최대 1,400토큰)과 여유 792토큰을 뺀 입력 예산을 사용한다. 메시지·도구 정의·스키마·프레이밍을 포함한 **UTF-8 기반 보수적 토큰 추정**이며 실제 tokenizer 측정이나 넘침 방지의 수학적 보장은 아니다. 정확한 입력 수는 호출 후 Ollama의 `prompt_eval_count`로 표시한다. 예산이 크면 이전 요약·중복 문맥과 도구 결과 목록을 먼저 줄이고 생략을 표시한다. 직전 대화 원문·현재 요청·시스템 프롬프트는 하네스가 잘라내지 않는다. 필수 내용만으로도 추정 예산을 넘으면 모델을 호출하지 않고 크기 변경/새 대화를 안내한다.

근거: [Ollama context length](https://docs.ollama.com/context-length), [API num_ctx 설정](https://docs.ollama.com/faq#how-can-i-specify-the-context-window-size), [chat API와 prompt_eval_count](https://docs.ollama.com/api/chat).

매 대화의 라우팅과 응답은 다음을 조합한다:

```text
System prompt
  + UserPreferences.md (저장된 사용자 선호)
  + last_exchange (직전 사용자 발화와 최종 답변 원문)
  + Memory.md (직전 원문과 중복되는 경우 전송 생략)
  + Compacted conversation
  + 직전보다 오래된 최근 2개 라운드의 사용자 발췌
  + 이전 장면의 구체적인 자세 설정 및 관련 라운드의 원문
  + 현재 사용자 메시지
  + 필요한 도구 결과 / seek로 회수한 원문
```

검색 결과나 과거 메시지를 system 역할로 올리지 않는다. 도구명 allowlist와 인자 schema를 서버에서 검사한다. 문맥 예산은 선택한 크기에 맞추며, 원문 대화는 프롬프트 압축과 별도로 세션에서 보존한다.

### 영어 설명과 검증 범위

`--glossary`로 `combined_english_descriptions.jsonl`을 지정할 수 있다. 기본값은 로컬 DEV의 `NAIA-Event-Map-Handoff-20260911` 번역 자산이다. 없으면 NAIA 원래 설명을 유지하고 영어 설명 부재를 표시한다. 정규화 중복은 선택하지 않고, 품질 flag 및 현재 한국어 정의와의 차이를 도구 결과에 붙인다. 번역 자산을 NAIA 데이터에 덮어쓰지 않는다.

이번 구현은 영어 의도 구조와 영문 정의를 연결한 단계다. 선호 문서·원문 기억·seek까지 모두 영어로 변환하는 완전한 영어 전용 경로는 아니다. 원문 기억의 의미 보존을 위해 한국어 인용을 유지한다.

형식 검사와 원문 조건 점검은 **모든 의미가 보존됐다는 증명이 아니다.** 작은 모델이 조건을 빠뜨리거나 단어를 잘못 번역할 가능성은 남는다. v9 실제 E2B 테스트에서도 오크/참나무 혼동과 빈 유지 조건으로 인한 fallback이 관측됐다. 태그 존재, 장면 구성의 타당성, 실제 생성 이미지의 품질은 별개다. 이 실험은 이미지를 생성하지 않는다. 이전 `scene.py`·`router.md`·design/compose 프롬프트는 과거 실험 참고 파일이다.

## 자산과 도구

| 도구 | 실제 소유 코드 |
|---|---|
| search_tags | `core.tag_search_index.TagSearchIndex.search_semantic`; canonical loader로 한국어·영어 자산 병합 |
| fast_search | `app.backend.server.fast_search_routes.SEARCHERS`; tag/artist/character/wildcard/preset/event |
| event_map | `core.event_map.service.EventMapService.explore` |
| seek_conversation | 이 실험 세션의 원문 저장소; 키워드 또는 round_id로 검색 |

Fast Search 이벤트는 bundled 구형 catalog가 아니라 실제 `.naiamap`의 `core.event_map.quick_search`를 읽는다. 정확한 영문 태그는 먼저 pin으로 확정하므로 `hug`를 `huge...` 접두어 후보와 섞지 않는다. 관측 수, 표본 여부, rating/person을 결과에 보존한다.

태그 검색은 정확한 태그를 우선한다. 복합 질의가 비면 canonical 태그에 해당하는 가장 긴 명사구 끝부분으로 보완하고 fallback_queries에 기록한다. 예를 들어 giant sniper rifle에서 sniper rifle을 찾되 giant를 잘라 giantess로 검색하지 않는다. girl/boy는 태그 검색 시 1girl/1boy로 정규화한다.

## 기억의 수명

| 데이터 | 위치 | 새 대화 | 서버 재시작 |
|---|---|---|---|
| 시스템 프롬프트 | prompts/system.md | 유지 | 유지 |
| 사용자 선호 | codex_out/e2b_chat_lab/state/UserPreferences.md | 유지 | 유지 |
| 컨텍스트 크기 | codex_out/e2b_chat_lab/state/settings.json | 유지 | 유지 |
| Memory.md | 서버 메모리의 가상 Markdown 문서 | 비움 | 비움 |
| 압축 대화 | 서버 메모리 | 비움 | 비움 |
| 원문·도구 기록 | 서버 메모리 | 비움 | 비움 |

모델은 명시적 사용자 발언의 정확한 인용을 포함한 선호 후보를 제안할 수 있다. 사용자가 “선호에 저장”을 누르거나 오른쪽 문서를 직접 저장해야 지속된다. 일회성 장면 조건을 성격으로 자동 기록하지 않는다.

원문은 압축 후에도 남는다. 도구는 1000자씩 정확한 발췌를 반환하며 next_offset으로 뒤를 읽을 수 있다. 화면의 이전 라운드 찾기는 전체 원문을 보여준다. 키워드 검색은 lexical search이며 임베딩 의미 검색은 아니다. 최대 300라운드의 단일 사용자 실험 세션이고, 여러 탭은 같은 세션을 공유한다.

새 대화를 실행 중 누르면 현재 세션을 즉시 무효화하고 기억을 비운다. 이전 모델 응답이 돌아와도 새 세션에 반영되지 않는다. 현재 Ollama HTTP 호출이 끝날 때까지 새 전송은 대기한다. 중단 버튼도 후속 실행과 결과 반영을 멈추며, 이미 실행 중인 Ollama 계산을 즉시 종료한다고 보장하지 않는다.

## 시스템 프롬프트 제안

실제로 사용하는 기본 프롬프트는 `prompts/system.md`다. 첫 문장에서 Stable Diffusion 기반 애니 이미지 프롬프트 전문가임을 명시한다. 단계별 지시는 `intent.md`, `answer.md`, `review.md`, `fallback.md`, 압축 지시는 `compact.md`로 분리했다. 영어 처리와 한국어 설명, 최신 원문 우선, 고정 조건 보존, 읽기 전용 도구 범위를 규정한다.

사용자 의도 원문을 우선하고, 과거 요약과 선호는 참조 데이터로 사용한다. 태그 검색 결과의 존재와 의미 적합성을 구분하며, 이전 대화의 정확한 문구는 seek로 찾고, 일반 대화에는 검색을 강요하지 않는다.

## 검증

```powershell
venv/Scripts/python.exe -X utf8 -m pytest tests/headless/test_e2b_chat_lab.py tests/headless/test_e2b_chat_context.py tests/headless/test_e2b_chat_retrieval.py -q
node --check tools/e2b_chat_lab/web/app.js
```

2026-09-14의 실제 모델 검사와 Chrome 검사 스크립트·결과는 `codex_out/e2b_chat_lab/`에 있다. 이 폴더의 live_results.json은 개발용 시험 대화 캡처이며, 런타임이 사용자 대화를 저장하는 기능은 아니다.

실험 범위: 검색·대화·기억. NAIA 프롬프트 적용, 이미지 생성, 외부 웹 검색, shell, 임의 파일 접근, 다운로드 도구는 제공하지 않는다. 개인 성향의 자동 추론 정확도나 모든 한국어 복합 의도 해석의 완전성을 검증한 것은 아니다.
