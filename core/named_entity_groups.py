"""고유명(named-entity) KR 카테고리 판별 공용 화이트리스트 — 검색 인덱스/리트리버/
어시스트가 공유한다.

배경(실측 감사, 2026-06-12): 세 곳(llm_search_index `_excluded`, tag_candidate_retriever
`score_concept_candidate`, ollama_tag_assist_service `_PROPER_NOUN_CATEGORY_PREFIXES`)이
KR 카테고리에 "캐릭터" 마커가 들어가면 고유명으로 보고 배제한다. 그런데 NAIA의 KR
택소노미는 "캐릭터"를 *인물 전반*의 상위 카테고리로 쓴다 — `캐릭터 > 포켓몬/원신`(named
캐릭터, 정상 배제)뿐 아니라 `캐릭터 > 직업/종족/유형/속성/관계/...`(generic 인물·생물·
속성: cheerleader/nurse/ninja/futanari/dark elf/demon/twins/yandere 등 ~150 태그)까지 같은
"캐릭터" 접두라 통째 오배제됐다(사용자 SFW 치어리더 테스트가 노출).

핵심 안전성: generic 하위그룹(직업/유형/종족/...)은 *대부분* named 캐릭터가 안 섞인다
(프랜차이즈는 `캐릭터 > <작품명>`으로 분리). 단 소수 franchise 오염(super saiyan/au ra/
os-tan 등 6종, Codex R2 실증)이 generic leaf 안에 있어 `_FRANCHISE_IN_GENERIC_LEAVES`
tag 디나이리스트로 추가 차단한다. leaf 화이트리스트 + tag 디나이 → named 누출 0으로
generic 태그(cheerleader/nurse/futanari/dark elf 등 ~171) recall을 회복한다.

이 모듈은 stdlib만 의존(순수) — llm_search_index의 무의존 테스트성을 깨지 않는다.
각 호출부는 자기 마커 목록을 유지하되 "캐릭터" 케이스에서만 이 헬퍼를 참조한다.
"""
from __future__ import annotations

from typing import Any

__all__ = ["GENERIC_CHAR_LEAVES", "is_generic_char_attribute", "is_denylisted_franchise_tag"]

# "캐릭터 > <leaf>"(또는 "캐릭터 종족 > <leaf>", 단독 "캐릭터 X")에서 leaf가 이들이면
# generic 인물/생물/속성 카테고리 — 고유명이 아니다. 실측 감사로 named 캐릭터 0% 확인.
# franchise 타이틀(포켓몬/Fate/원신/스플래툰/…)은 여기 없으므로 그대로 배제된다.
GENERIC_CHAR_LEAVES = frozenset({
    # 인물 속성/직업/역할/관계
    "직업", "역할", "성격", "성별", "연령", "체형", "크기", "관계", "상태", "특징", "속성",
    # 종족/생물 유형(요정/악마/엘프/수인/몬스터/동물 등)
    "종족", "유형", "비인간", "인외", "수인", "몬스터", "동물", "의인화", "동물의인화",
    "동물귀", "신화", "판타지", "아인", "변신생물", "로봇", "유령", "왕족",
    # 캐릭터 메타(고유명 아님 — 상호작용 포즈/그룹/정보)
    "캐릭터 유형", "캐릭터 수", "캐릭터 간", "캐릭터 특징", "캐릭터 속성",
    "캐릭터 정보", "캐릭터 해석", "캐릭터 그룹",
})


# generic leaf 안에 섞인 franchise/named 소수 오염(파생 데이터 실증, Codex R1) — leaf
# 화이트리스트만으론 못 거른다. 이들은 괄호도 없어(괄호형 genderswap (mtf)/mouse (animal)
# 등은 기존 괄호 규칙이 처리) 별도 디나이가 필요하다. 정규화형(소문자·밑줄→공백).
_FRANCHISE_IN_GENERIC_LEAVES = frozenset({
    "super saiyan",        # 드래곤볼 (캐릭터 > 상태)
    "au ra",               # 파이널 판타지 XIV 종족 (캐릭터 > 종족)
    "os-tan", "3.1-tan",   # OS 의인화 밈 (캐릭터 > 의인화)
    "evolutionary line",   # 포켓몬 메타 (캐릭터 > 특징)
    "indie utaite",        # 우타이트 커뮤니티 메타 (캐릭터 > 유형)
})


def is_generic_char_attribute(group: Any, tag: Any = None) -> bool:
    """KR 카테고리가 "캐릭터" 계열이면서 generic 인물/생물/속성 하위(고유명 아님)인지.

    leaf = '>' 기준 마지막 세그먼트. "캐릭터 > 직업"→"직업"(✓), "캐릭터 종족 > 왕족"→
    "왕족"(✓), "캐릭터 > 포켓몬"→"포켓몬"(✗ franchise), "게임 > 캐릭터"→"캐릭터"(✗ named).
    단독 "캐릭터"(혼합 그룹: clone + pulchra fellini)는 leaf="캐릭터"라 화이트리스트
    밖 → 보수적으로 배제 유지.

    `tag`이 주어지면 generic leaf 안의 franchise 오염(super saiyan/au ra/os-tan 등)을
    디나이리스트로 추가 차단한다(Codex R1: leaf-only는 named 0% 전제가 데이터로 반증됨).
    """
    g = str(group or "").strip().lower()
    if "캐릭터" not in g:          # "캐릭터" 계열이 아니면 이 면제는 무관(저작권>직업 등 방어)
        return False
    leaf = g.rsplit(">", 1)[-1].strip()
    if leaf not in GENERIC_CHAR_LEAVES:
        return False
    if tag is not None:
        t = " ".join(str(tag).replace("_", " ").strip().lower().split())
        if t in _FRANCHISE_IN_GENERIC_LEAVES:
            return False
    return True


def is_denylisted_franchise_tag(tag: Any) -> bool:
    """generic leaf 안의 franchise 오염 디나이 태그인지(super saiyan/au ra/os-tan 등).
    회수 경로(_recover_tag)가 이들을 다른 태그로 *치환*하지 않고 드롭하도록 호출부가
    사용한다(Codex R2: 디나이 입력의 검색 치환이 super saiyan→super crown으로 샜다)."""
    t = " ".join(str(tag or "").replace("_", " ").strip().lower().split())
    return t in _FRANCHISE_IN_GENERIC_LEAVES
