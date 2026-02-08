"""
Ollama (GPU Only) Module - 자연어 프롬프트를 태그 기반 프롬프트로 변환

Tag Prompt Engine v2를 활용하여 한국어/영어 자연어 입력을
danbooru 스타일 태그 프롬프트로 변환합니다.

Pipeline v2 (Tool Calling 제거 → 후보 제시 + 선택 방식):
  Stage 0: 번역 (Google Translate)
  Stage 1: 의도 분해 (LLM) - 문장을 카테고리별 시각 개념으로 분해
  Stage 2: 후보 검색 (Code) - 개념별 TagDatabase 검색, Danbooru Only
  Stage 2.5: e621 NSFW Boost (선택)
  Stage 3: 태그 선택 (LLM) - 후보에서 최적 태그 선택
  Stage 4: 자연어 생성 (LLM) - 보충 묘사 생성
  Stage 5: 태그 확장 (LLM) - Creativity에 따라 보충 태그 추가
  Stage 6: 자연어 확장 (LLM) - Creativity에 따라 묘사 수정/확장

요구사항:
- Ollama 로컬 설치 (GPU 필수)
- Qwen 모델 (4b 또는 8b)
"""

import subprocess
import sys
import math
import json
import re
import requests
from pathlib import Path
from typing import Optional, List, Dict, Set, Tuple
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTextEdit, QComboBox, QMessageBox, QGroupBox, QApplication, QCheckBox,
    QScrollArea, QFrame, QDialog, QProgressBar
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices

from interfaces.base_module import BaseMiddleModule
from utils.translator import korean_to_english
from ui.theme import DARK_COLORS, get_dynamic_styles
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from ui.modern_menu import setModernStyle


# Ollama API 기본 URL
OLLAMA_BASE_URL = "http://localhost:11434"

# 지원 모델 목록 (4b, 8b만)
SUPPORTED_MODELS = [
    "huihui_ai/qwen3-vl-abliterated:8b-instruct",
    "huihui_ai/qwen3-vl-abliterated:4b-instruct",
]

# 데이터 파일 경로
DATA_DIR = Path(__file__).parent.parent
E621_DATA_PATH = DATA_DIR / "data" / "e621_data"
DANBOORU_DATA_PATH = DATA_DIR / "ui" / "interactive" / "interactive"


def normalize_tag(tag: str) -> str:
    """태그 정규화: 소문자 + 언더스코어→공백 + strip"""
    return tag.lower().replace("_", " ").strip()


# 의도 분해 카테고리
INTENT_CATEGORIES = [
    "CHARACTER", "APPEARANCE", "EXPRESSION", "ACTION",
    "CLOTHING", "OBJECT", "SETTING",
    "BODY_EXPOSURE", "SEXUAL_ACT", "RESTRAINT"
]

# 명시적 언급이 필요한 카테고리 (LLM 추론만으로는 후보 검색 안 함)
EXPLICIT_REQUIRED_CATEGORIES = {"APPEARANCE"}

# e621 NSFW Boost: NSFW 특화 카테고리 (외형/의상/범용감정 제외)
E621_NSFW_BOOST_CATEGORIES = {"ACTION", "SEXUAL_ACT", "BODY_EXPOSURE", "RESTRAINT"}

# e621 NSFW Boost: 결과에서 제외할 외형 패턴 (의류는 torn_dress 등 허용 위해 제거)
E621_NSFW_BOOST_EXCLUDE_PATTERNS = {
    'hair', 'eyes', 'eye', 'skin', 'tan', 'pale', 'freckles', 'mole', 'scar',
    'ears', 'tail', 'horns', 'wings',
    'hat', 'helmet', 'glasses', 'ribbon',
}

# e621 Wiki 텍스트 인덱싱용 스톱워드
E621_WIKI_STOPWORDS = frozenset({
    'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
    'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
    'should', 'may', 'might', 'shall', 'can', 'must',
    'i', 'you', 'he', 'she', 'it', 'we', 'they', 'me', 'him', 'her', 'us', 'them',
    'my', 'your', 'his', 'its', 'our', 'their',
    'this', 'that', 'these', 'those',
    'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'from', 'up', 'about',
    'into', 'through', 'during', 'before', 'after', 'above', 'below', 'between',
    'out', 'off', 'over', 'under', 'again', 'further', 'then', 'once',
    'and', 'but', 'or', 'nor', 'not', 'no', 'so', 'if', 'than', 'too', 'very',
    'just', 'also', 'more', 'most', 'such', 'only', 'own', 'same', 'both', 'each',
    'all', 'any', 'few', 'other', 'some', 'many', 'much', 'every',
    'here', 'there', 'when', 'where', 'why', 'how', 'what', 'which', 'who', 'whom',
    'as', 'while', 'because', 'although', 'though', 'even', 'still',
    'thumb', 'section', 'see', 'also', 'related', 'tags', 'tag', 'group',
    'confused', 'example', 'examples', 'note', 'notes',
    'http', 'https', 'www', 'com', 'org', 'wikipedia',
    'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten',
    'first', 'second', 'third', 'last', 'next', 'new', 'old', 'good', 'bad',
    'get', 'got', 'make', 'made', 'take', 'taken', 'come', 'came', 'went',
    'know', 'known', 'think', 'thought', 'say', 'said', 'tell', 'told',
    'look', 'give', 'given', 'use', 'used', 'find', 'found', 'want', 'need',
    'seem', 'become', 'leave', 'left', 'keep', 'kept', 'let', 'put', 'set',
    'show', 'shown', 'try', 'ask', 'work', 'call', 'called',
    'like', 'well', 'back', 'way', 'part', 'long', 'great', 'little',
    'right', 'often', 'usually', 'sometimes', 'however',
    'type', 'types', 'form', 'forms', 'kind', 'kinds',
    'generally', 'typically', 'commonly',
    'refers', 'refer', 'describing', 'describe', 'described',
    'feature', 'features', 'featuring', 'include', 'includes', 'including',
    'character', 'characters', 'image', 'images', 'post', 'posts',
    'added', 'seen', 'depicted', 'appears', 'appearing',
})

# Creativity 프로파일 (0.1~0.9, 0.2 단위)
# temps = (stage1_의도분해, stage3_태그선택, stage4_자연어)
CREATIVITY_PROFILES = {
    0.1: {"label": "보수적", "temps": (0.15, 0.15, 0.25), "tag_mult": 0.5,  "nat_mult": 0.5,  "nat_words": (4, 8),
           "enhance_tags": (0, 0),   "enhance_nl": "none"},
    0.3: {"label": "절제",   "temps": (0.22, 0.22, 0.32), "tag_mult": 0.7,  "nat_mult": 0.7,  "nat_words": (5, 10),
           "enhance_tags": (1, 2),   "enhance_nl": "none"},
    0.5: {"label": "기본",   "temps": (0.30, 0.30, 0.42), "tag_mult": 1.0,  "nat_mult": 1.0,  "nat_words": (6, 12),
           "enhance_tags": (3, 5),   "enhance_nl": "light"},
    0.7: {"label": "창의적", "temps": (0.40, 0.40, 0.55), "tag_mult": 1.4,  "nat_mult": 1.5,  "nat_words": (8, 16),
           "enhance_tags": (5, 10),  "enhance_nl": "moderate"},
    0.9: {"label": "대담",   "temps": (0.55, 0.55, 0.70), "tag_mult": 1.8,  "nat_mult": 2.0,  "nat_words": (10, 20),
           "enhance_tags": (6, 14),  "enhance_nl": "strong"},
}


# ======================================================================
# TagDatabase
# ======================================================================

class TagDatabase:
    """태그 데이터베이스 (e621 + danbooru) - Enhanced Search"""

    def __init__(self):
        self.e621_tags: Dict[str, dict] = {}
        self.danbooru_tags: Dict[str, dict] = {}
        self.all_tags: Set[str] = set()
        # 정규화된 태그 → 원본 태그 매핑 (빠른 exact match용)
        self._normalized_to_original: Dict[str, str] = {}
        # 한국어 키워드 → 태그 매핑
        self._kr_keyword_to_tags: Dict[str, List[str]] = {}
        # e621 인덱스 (load() 시 빌드)
        self._e621_siblings: Dict[str, List[str]] = {}
        self._e621_wiki_links: Dict[str, List[str]] = {}
        self._e621_wiki_text_index: Dict[str, List[str]] = {}
        self._e621_tag_name_index: Dict[str, List[str]] = {}
        self._e621_nsfw_tag_set: Set[str] = set()  # NSFW+Danger 카테고리 태그
        self.is_loaded = False

    def load(self) -> bool:
        if self.is_loaded:
            return True

        try:
            if E621_DATA_PATH.exists():
                with open(E621_DATA_PATH, 'r', encoding='utf-8') as f:
                    e621_data = json.load(f)
                self._e621_raw_data = e621_data  # 계층 구조 보존
                self._parse_e621_data(e621_data)

            if DANBOORU_DATA_PATH.exists():
                with open(DANBOORU_DATA_PATH, 'r', encoding='utf-8') as f:
                    self.danbooru_tags = json.load(f)
                self.all_tags.update(self.danbooru_tags.keys())

            # 인덱스 빌드
            self._build_indexes()

            self.is_loaded = True
            return True
        except Exception as e:
            print(f"[TagDB] 로드 실패: {e}")
            return False

    def _parse_e621_data(self, data: dict):
        def collect_tags(obj):
            if isinstance(obj, list):
                for item in obj:
                    if isinstance(item, dict) and "tag" in item:
                        tag = item["tag"]
                        self.e621_tags[tag] = item
                        self.all_tags.add(tag)
            elif isinstance(obj, dict):
                for value in obj.values():
                    collect_tags(value)
        collect_tags(data)

    def _build_indexes(self):
        """검색 인덱스 빌드"""
        # 정규화 인덱스 (e621 먼저, danbooru 나중 → danbooru가 충돌 시 우선)
        for tag in self.e621_tags:
            self._normalized_to_original[normalize_tag(tag)] = tag
        for tag in self.danbooru_tags:
            self._normalized_to_original[normalize_tag(tag)] = tag  # danbooru가 덮어씀

        # 한국어 키워드 인덱스
        for tag, info in self.danbooru_tags.items():
            keywords_kr = info.get("keywords_kr", "")
            if not keywords_kr:
                continue
            parts = keywords_kr.split(",")
            for part in parts:
                kw = part.strip()
                if kw.startswith("<") and kw.endswith(">"):
                    continue
                kw = re.sub(r'\[.*?\]', '', kw).strip()
                if len(kw) >= 2:
                    if kw not in self._kr_keyword_to_tags:
                        self._kr_keyword_to_tags[kw] = []
                    self._kr_keyword_to_tags[kw].append(tag)

        # e621 계층/wiki 인덱스
        self._build_e621_indexes()

        print(f"[TagDB] 인덱스 빌드 완료: {len(self._normalized_to_original)} 정규화, "
              f"{len(self._kr_keyword_to_tags)} 한국어 키워드")

    def search(self, query: str, limit: int = 20, nsfw_priority: bool = False) -> List[dict]:
        """기본 검색 (하위 호환성 유지)"""
        query_normalized = query.lower().replace("_", " ").strip()
        results = []

        for tag in self.all_tags:
            tag_normalized = tag.lower().replace("_", " ")
            if query_normalized in tag_normalized:
                if tag in self.danbooru_tags:
                    info = self.danbooru_tags[tag]
                    is_nsfw_group = info.get("group", "").upper() == "NSFW"
                    results.append({
                        "tag": tag,
                        "count": info.get("freq", 0),
                        "group": info.get("group", ""),
                        "source": "danbooru",
                        "is_nsfw": is_nsfw_group
                    })
                elif tag in self.e621_tags:
                    info = self.e621_tags[tag]
                    results.append({
                        "tag": tag,
                        "count": info.get("count", 0),
                        "group": info.get("group", ""),
                        "source": "e621",
                        "is_nsfw": True
                    })

        if nsfw_priority:
            def sort_key(x):
                if x["source"] == "danbooru" and x.get("is_nsfw"):
                    return (0, -x["count"])
                elif x["source"] == "e621":
                    return (1, -x["count"])
                else:
                    return (2, -x["count"])
            results.sort(key=sort_key)
        else:
            results.sort(key=lambda x: x["count"], reverse=True)

        return results[:limit]

    def search_enhanced(self, query: str, limit: int = 15,
                        nsfw_priority: bool = False,
                        danbooru_only: bool = False) -> List[dict]:
        """4단계 매칭 + 관련성 스코어링 검색"""
        query_norm = query.lower().replace("_", " ").strip()
        if not query_norm:
            return []

        search_pool = self.danbooru_tags.keys() if danbooru_only else self.all_tags

        scored_results: Dict[str, Tuple[float, dict]] = {}
        query_words = set(query_norm.split())

        for tag in search_pool:
            tag_norm = tag.lower().replace("_", " ")

            score = 0.0
            if tag_norm == query_norm:
                score = 1.0
            elif tag_norm.startswith(query_norm):
                score = 0.8
            else:
                tag_words = set(tag_norm.split())
                if query_words.issubset(tag_words):
                    score = 0.6
                elif query_norm in tag_norm:
                    score = 0.4

            if score == 0.0:
                continue

            info = self._get_tag_info(tag, danbooru_only=danbooru_only)
            if not info:
                continue

            freq = info.get("count", 0)
            final_score = score + min(freq / 5_000_000, 0.3)

            if tag not in scored_results or scored_results[tag][0] < final_score:
                scored_results[tag] = (final_score, info)

        sorted_results = sorted(
            scored_results.items(),
            key=lambda x: (-x[1][0], -x[1][1].get("count", 0))
        )

        results = []
        for tag, (score, info) in sorted_results[:limit]:
            entry = dict(info)
            entry["match_score"] = round(score, 2)
            results.append(entry)

        return results

    def search_korean(self, kr_text: str, limit: int = 10,
                      danbooru_only: bool = False) -> List[dict]:
        """한국어 텍스트에서 직접 태그 매칭 (keywords_kr 인덱스 활용)"""
        found_tags = set()

        for kw, tags in self._kr_keyword_to_tags.items():
            if kw in kr_text:
                for tag in tags:
                    found_tags.add(tag)

        results = []
        for tag in found_tags:
            info = self._get_tag_info(tag, danbooru_only=danbooru_only)
            if info:
                results.append(info)

        results.sort(key=lambda x: x.get("count", 0), reverse=True)
        return results[:limit]

    def search_by_group(self, group: str, limit: int = 30) -> List[dict]:
        """그룹별 태그 검색 (하위 호환성)"""
        results = []
        group_lower = group.lower()
        for tag, info in self.danbooru_tags.items():
            if info.get("group", "").lower() == group_lower:
                results.append({"tag": tag, "subgroup": info.get("subgroup", "")})
        return results[:limit]

    def get_tag_info(self, tag_name: str) -> Optional[dict]:
        """태그 상세 정보 조회 (하위 호환성)"""
        normalized_space = tag_name.lower().replace("_", " ").strip()
        normalized_underscore = tag_name.lower().replace(" ", "_").strip()
        if normalized_space in self.danbooru_tags:
            return {"tag": normalized_space, **self.danbooru_tags[normalized_space]}
        if normalized_space in self.e621_tags:
            return {"tag": normalized_space, **self.e621_tags[normalized_space]}
        if normalized_underscore in self.e621_tags:
            return {"tag": normalized_underscore, **self.e621_tags[normalized_underscore]}
        return None

    def get_siblings(self, tag: str, limit: int = 5) -> List[str]:
        """태그의 siblings (관련 태그) 반환"""
        info = self.danbooru_tags.get(tag, {})
        relations = info.get("relations", {})
        siblings = relations.get("siblings", [])
        return siblings[:limit]

    def _get_tag_info(self, tag: str, danbooru_only: bool = False) -> Optional[dict]:
        """태그 정보 조회 (danbooru/e621 통합)"""
        if tag in self.danbooru_tags:
            info = self.danbooru_tags[tag]
            return {
                "tag": tag,
                "count": info.get("freq", 0),
                "group": info.get("group", ""),
                "source": "danbooru",
                "is_nsfw": info.get("group", "").upper() == "NSFW"
            }
        elif not danbooru_only and tag in self.e621_tags:
            info = self.e621_tags[tag]
            return {
                "tag": tag,
                "count": info.get("count", 0),
                "group": info.get("group", ""),
                "source": "e621",
                "is_nsfw": True
            }
        return None

    # ===== e621 Cross-Reference =====

    def _build_e621_indexes(self):
        """e621 계층 siblings + wiki [[link]] + wiki text keyword 인덱스 빌드"""
        self._e621_siblings: Dict[str, List[str]] = {}
        self._e621_wiki_links: Dict[str, List[str]] = {}
        self._e621_wiki_text_index: Dict[str, List[str]] = {}

        if not hasattr(self, '_e621_raw_data'):
            print("[TagDB] e621 원본 데이터 없음 → 인덱스 생략")
            return

        # 1) wiki 링크 파싱
        for tag, info in self.e621_tags.items():
            wiki = info.get("wiki_body", "")
            if not wiki:
                continue
            links = re.findall(r'\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]', wiki)
            cleaned = []
            for link in links:
                link = link.strip().lower().replace(" ", "_")
                if link != tag and len(link) >= 2:
                    cleaned.append(link)
            if cleaned:
                self._e621_wiki_links[tag] = cleaned

        # 2) 계층 siblings 수집 (깊이 제한 + 상한)
        self._traverse_e621_siblings(self._e621_raw_data, depth=0)

        # 3) wiki text keyword 역인덱스
        self._build_wiki_text_index()

        # 4) 태그 이름 토큰 역인덱스
        self._build_tag_name_index()

        # 5) NSFW + Danger 카테고리 태그 셋 (Phase 1c 필터용)
        self._build_nsfw_tag_set()

        if self._e621_siblings:
            avg_sib = sum(len(v) for v in self._e621_siblings.values()) / len(self._e621_siblings)
        else:
            avg_sib = 0
        wiki_text_keys = len(self._e621_wiki_text_index)
        tag_name_keys = len(self._e621_tag_name_index)
        print(f"[TagDB] e621 인덱스: {len(self._e621_wiki_links)} wiki-linked, "
              f"{len(self._e621_siblings)} sibling-mapped (avg {avg_sib:.1f}/tag), "
              f"{wiki_text_keys} wiki-text keywords, {tag_name_keys} tag-name keywords, "
              f"{len(self._e621_nsfw_tag_set)} nsfw-category")

    _SIBLING_MIN_DEPTH = 2
    _SIBLING_MAX_CHILDREN = 50

    def _traverse_e621_siblings(self, obj, depth: int = 0):
        """e621 계층 순회 → 같은 부모의 자식 태그끼리 siblings 등록"""
        if not isinstance(obj, dict):
            return

        child_tags = []
        for key, value in obj.items():
            if key.startswith("_Self"):
                if isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict) and "tag" in item:
                            child_tags.append(item["tag"])
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict) and "tag" in item:
                        child_tags.append(item["tag"])
            elif isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    if sub_key.startswith("_Self") and isinstance(sub_value, list):
                        for item in sub_value:
                            if isinstance(item, dict) and "tag" in item:
                                child_tags.append(item["tag"])

        if (depth >= self._SIBLING_MIN_DEPTH
                and 2 <= len(child_tags) <= self._SIBLING_MAX_CHILDREN):
            for tag in child_tags:
                self._e621_siblings[tag] = [t for t in child_tags if t != tag]

        for key, value in obj.items():
            if isinstance(value, dict):
                self._traverse_e621_siblings(value, depth=depth + 1)

    def _build_wiki_text_index(self):
        """e621 wiki_body 텍스트에서 키워드 역인덱스 빌드"""
        raw_index: Dict[str, set] = {}

        for tag, info in self.e621_tags.items():
            wiki = info.get("wiki_body", "")
            if not wiki or len(wiki) < 20:
                continue

            # 마크업 제거
            text = re.sub(r'\[\[([^\]|]+?)\|([^\]]+?)\]\]', r'\2', wiki)
            text = re.sub(r'\[\[([^\]]+?)\]\]', r'\1', text)
            text = re.sub(r'\[/?(?:section|b|i|u|quote|code|spoiler)[^\]]*\]', ' ', text)
            text = re.sub(r'thumb\s*#\d+', ' ', text)
            text = re.sub(r'h[1-6]\.', ' ', text)
            text = re.sub(r'https?://\S+', ' ', text)
            text = re.sub(r'\*+', ' ', text)

            tokens = re.findall(r'[a-z]{3,}', text.lower())
            for token in tokens:
                if token in E621_WIKI_STOPWORDS or len(token) > 25:
                    continue
                if token not in raw_index:
                    raw_index[token] = set()
                raw_index[token].add(tag)

        for keyword, tag_set in raw_index.items():
            if 2 <= len(tag_set) <= 500:
                self._e621_wiki_text_index[keyword] = list(tag_set)

    def _build_tag_name_index(self):
        """e621 태그 이름 토큰 → 태그 역인덱스
        예: arms_bound_behind_back → tokens: [arms, bound, behind, back]
        """
        raw_index: Dict[str, set] = {}
        for tag in self.e621_tags:
            tokens = re.split(r'[_\s]+', tag.lower())
            tokens = [t for t in tokens if len(t) >= 3 and t not in E621_WIKI_STOPWORDS]
            for token in tokens:
                if token not in raw_index:
                    raw_index[token] = set()
                raw_index[token].add(tag)
        for keyword, tag_set in raw_index.items():
            if len(tag_set) <= 200:
                self._e621_tag_name_index[keyword] = list(tag_set)

    def _build_nsfw_tag_set(self):
        """e621 General/NSFW + General/Danger 하위 모든 태그를 수집하여 Phase 1c 필터로 사용"""
        if not hasattr(self, '_e621_raw_data'):
            return

        def collect_tags_recursive(obj):
            tags = set()
            if isinstance(obj, list):
                for item in obj:
                    if isinstance(item, dict) and "tag" in item:
                        tags.add(item["tag"])
            elif isinstance(obj, dict):
                for value in obj.values():
                    tags.update(collect_tags_recursive(value))
            return tags

        general = self._e621_raw_data.get("General", {})
        for category_key in ("NSFW", "Danger"):
            category_data = general.get(category_key, {})
            self._e621_nsfw_tag_set.update(collect_tags_recursive(category_data))

    def e621_cross_reference(self, source_tags: List[str], limit: int = 20,
                             min_freq: int = 1000) -> List[dict]:
        """e621 관계를 활용한 danbooru 태그 크로스 레퍼런스

        관련성 스코어링: score = link_count^1.5 * log10(freq)
        """
        boost_links: Dict[str, int] = {}
        source_norm = {t.lower().replace(" ", "_") for t in source_tags}

        for tag in source_tags:
            tag_e621 = tag.lower().replace(" ", "_")
            for sib in self._e621_siblings.get(tag_e621, []):
                if sib not in source_norm:
                    boost_links[sib] = boost_links.get(sib, 0) + 1
            for link in self._e621_wiki_links.get(tag_e621, []):
                if link not in source_norm:
                    boost_links[link] = boost_links.get(link, 0) + 1

        results = []
        for candidate, link_count in boost_links.items():
            tag_space = candidate.replace("_", " ")
            tag_under = candidate.replace(" ", "_")

            if tag_space in self.danbooru_tags:
                info = self._get_tag_info(tag_space, danbooru_only=True)
            elif tag_under in self.danbooru_tags:
                info = self._get_tag_info(tag_under, danbooru_only=True)
            else:
                continue

            if info and info.get("count", 0) >= min_freq:
                freq = info["count"]
                relevance = (link_count ** 1.5) * math.log10(max(freq, 1))
                info["_link_count"] = link_count
                info["_relevance"] = relevance
                results.append(info)

        results.sort(key=lambda x: x.get("_relevance", 0), reverse=True)
        return results[:limit]

    def e621_nsfw_boost(
        self,
        intents: Dict[str, List[str]],
        existing_tags: set,
        target_categories: set = None,
        limit: int = 20,
        min_danbooru_freq: int = 100,
        e621_only_limit: int = 5,
    ) -> List[dict]:
        """e621 wiki 기반 NSFW 특화 태그 부스트

        Stage 1 의도 개념(ACTION, SEXUAL_ACT, BODY_EXPOSURE, RESTRAINT)을 e621에서
        검색하여 NSFW 전문 태그(bondage, restraint, sexual acts, body exposure)를 반환.

        Phase 1a: Direct match (개념 → e621 태그명)
        Phase 1c: Tag name index (개념 word → 태그 이름 토큰 역인덱스)
        Phase 2: Wiki link expansion (매치된 태그 → [[link]] + siblings)
        Phase 3: Wiki text search (개념 키워드 → wiki_body 역인덱스)

        danbooru 교차 매칭 태그 + e621 전용 고스코어 태그를 함께 반환.
        """
        if target_categories is None:
            target_categories = E621_NSFW_BOOST_CATEGORIES

        concepts: List[str] = []
        for cat, cat_concepts in intents.items():
            if cat in target_categories:
                concepts.extend(cat_concepts)

        if not concepts:
            return []

        existing_norm = {t.lower().replace("_", " ") for t in existing_tags}

        # score 누적: tag_norm → {original, score, sources}
        scored: Dict[str, Dict] = {}

        def _add_score(tag: str, points: float, source: str):
            tag_norm = tag.lower().replace("_", " ")
            if tag_norm in existing_norm:
                return
            if any(pat in tag_norm for pat in E621_NSFW_BOOST_EXCLUDE_PATTERNS):
                return
            if tag_norm not in scored:
                scored[tag_norm] = {"original": tag, "score": 0.0, "sources": set()}
            scored[tag_norm]["score"] += points
            scored[tag_norm]["sources"].add(source)

        for concept in concepts:
            concept_norm = concept.lower().strip()
            concept_underscore = concept_norm.replace(" ", "_")
            concept_words = [
                w for w in concept_norm.split()
                if len(w) >= 3 and w not in E621_WIKI_STOPWORDS
            ]

            # Phase 1a: Direct e621 tag match
            for tag_form in (concept_underscore, concept_norm):
                if tag_form in self.e621_tags:
                    _add_score(tag_form, 3.0, "direct")
                    break

            # Phase 1c: Tag name index search (NSFW/Danger 카테고리만)
            for word in concept_words:
                for tag in self._e621_tag_name_index.get(word, []):
                    if tag in self._e621_nsfw_tag_set:
                        _add_score(tag, 2.0, "tag_name")

            # Phase 2: Wiki link expansion + siblings
            for tag_form in (concept_underscore, concept_norm):
                for linked_tag in self._e621_wiki_links.get(tag_form, []):
                    _add_score(linked_tag, 2.0, "wiki_link")
                for sib in self._e621_siblings.get(tag_form, []):
                    _add_score(sib, 1.5, "sibling")

            # Phase 3: Wiki text keyword search
            for word in concept_words:
                for tag in self._e621_wiki_text_index.get(word, []):
                    _add_score(tag, 1.0, "text_keyword")

            # Multi-word compound bonus
            if len(concept_words) >= 2:
                word_hits: Dict[str, int] = {}
                for word in concept_words:
                    for tag in self._e621_wiki_text_index.get(word, []):
                        tag_norm = tag.lower().replace("_", " ")
                        word_hits[tag_norm] = word_hits.get(tag_norm, 0) + 1
                for tag_norm, hit_count in word_hits.items():
                    if hit_count >= 2 and tag_norm in scored:
                        scored[tag_norm]["score"] += 0.5 * (hit_count - 1)

        # danbooru 교차 검증 + e621 전용 태그 수집
        results = []
        e621_only = []
        for tag_norm, entry in scored.items():
            tag_space = entry["original"].replace("_", " ")
            tag_under = entry["original"].replace(" ", "_")

            danbooru_info = None
            for variant in (tag_space, tag_under):
                if variant in self.danbooru_tags:
                    danbooru_info = self._get_tag_info(variant, danbooru_only=True)
                    break

            base_score = entry["score"]

            if danbooru_info:
                freq = danbooru_info.get("count", 0)
                if freq < min_danbooru_freq:
                    continue
                freq_weight = math.log10(max(freq, 10)) / 4.0
                final_score = base_score * freq_weight
                danbooru_info["_relevance"] = round(final_score, 3)
                danbooru_info["_boost_sources"] = list(entry["sources"])
                danbooru_info["_base_score"] = round(base_score, 2)
                results.append(danbooru_info)
            else:
                # e621 전용 태그: danbooru에 없지만 고스코어
                e621_info = self._get_tag_info(tag_under, danbooru_only=False)
                if not e621_info:
                    e621_info = self._get_tag_info(tag_space, danbooru_only=False)
                if e621_info and base_score >= 2.0:
                    e621_info["_relevance"] = round(base_score, 3)
                    e621_info["_boost_sources"] = list(entry["sources"])
                    e621_info["_base_score"] = round(base_score, 2)
                    e621_info["_e621_only"] = True
                    e621_only.append(e621_info)

        results.sort(key=lambda x: x.get("_relevance", 0), reverse=True)
        e621_only.sort(key=lambda x: x.get("_relevance", 0), reverse=True)

        # danbooru 매칭 결과 + e621 전용 고스코어 태그 혼합
        combined = results[:limit]
        combined.extend(e621_only[:e621_only_limit])
        return combined

    def validate_tag(self, tag: str) -> Optional[str]:
        """태그 유효성 검증 - 정규화된 형태로 반환"""
        normed = normalize_tag(tag)
        if normed in self._normalized_to_original:
            return self._normalized_to_original[normed]
        if tag in self.danbooru_tags or tag in self.e621_tags:
            return tag
        tag_under = tag.lower().replace(" ", "_").strip()
        if tag_under in self.danbooru_tags or tag_under in self.e621_tags:
            return tag_under
        return None

    @property
    def tag_count(self) -> int:
        return len(self.all_tags)


# ======================================================================
# DebugPanel (QDialog - C/C++ 안전)
# ======================================================================

class DebugPanel(QDialog):
    """디버그 정보 표시 패널 (QDialog 기반, C/C++ 안전)"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)  # 닫아도 삭제 안 함
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.Tool)
        self.setWindowTitle("Ollama Debug Panel")
        self.setMinimumSize(get_scaled_size(500), get_scaled_size(400))
        self.resize(get_scaled_size(600), get_scaled_size(700))
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            get_scaled_size(6), get_scaled_size(6),
            get_scaled_size(6), get_scaled_size(6)
        )
        layout.setSpacing(get_scaled_size(4))

        # 헤더 행
        header_row = QHBoxLayout()
        header_row.setSpacing(get_scaled_size(8))

        header = QLabel("Debug Panel")
        header.setStyleSheet(f"""
            font-size: {get_scaled_font_size(17)}px;
            font-weight: bold;
            color: #00ff00;
        """)
        header_row.addWidget(header)
        header_row.addStretch()

        clear_btn = QPushButton("Clear")
        clear_btn.setStyleSheet(get_dynamic_styles()['secondary_button'])
        clear_btn.clicked.connect(self.clear)
        header_row.addWidget(clear_btn)

        layout.addLayout(header_row)

        # 스크롤 영역
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(f"""
            QScrollArea {{
                border: 1px solid {DARK_COLORS['border']};
                background-color: {DARK_COLORS['bg_primary']};
            }}
        """)

        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.content_layout.setSpacing(get_scaled_size(6))

        self._scroll.setWidget(self.content_widget)
        layout.addWidget(self._scroll)

        # 다크 테마
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
            }}
        """)

    def add_stage(self, stage_name: str, content: str, color: str = "#ffffff"):
        """스테이지 출력 추가"""
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: #1a1a1a;
                border: 1px solid {color};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(4)}px;
            }}
        """)

        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(
            get_scaled_size(4), get_scaled_size(4),
            get_scaled_size(4), get_scaled_size(4)
        )
        frame_layout.setSpacing(get_scaled_size(2))

        title = QLabel(f"▶ {stage_name}")
        title.setStyleSheet(f"""
            color: {color};
            font-weight: bold;
            font-size: {get_scaled_font_size(15)}px;
        """)
        frame_layout.addWidget(title)

        timestamp = QLabel(datetime.now().strftime("%H:%M:%S.%f")[:-3])
        timestamp.setStyleSheet(f"""
            color: {DARK_COLORS['text_disabled']};
            font-size: {get_scaled_font_size(12)}px;
        """)
        frame_layout.addWidget(timestamp)

        content_edit = QTextEdit()
        content_edit.setPlainText(content)
        content_edit.setReadOnly(True)
        content_edit.setMaximumHeight(get_scaled_size(300))
        content_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: #111111;
                color: {DARK_COLORS['text_secondary']};
                border: none;
                font-family: Consolas, monospace;
                font-size: {get_scaled_font_size(13)}px;
            }}
        """)
        frame_layout.addWidget(content_edit)

        self.content_layout.addWidget(frame)

        # QTimer로 스크롤 (processEvents 사용 금지 → C/C++ 안전)
        QTimer.singleShot(0, lambda: self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum()
        ))

    def clear(self):
        """모든 디버그 내용 클리어"""
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()


# ======================================================================
# OllamaStatusCheckWorker (비동기 상태 확인)
# ======================================================================

class OllamaStatusCheckWorker(QThread):
    """Ollama 설치/서버 상태를 비동기로 확인하는 워커"""
    check_completed = pyqtSignal(dict)
    # Emits: {"installed": bool, "server_running": bool, "models": list}

    def run(self):
        result = {"installed": False, "server_running": False, "models": []}

        # Phase 1: HTTP 체크 (서버 실행 중이면 <100ms에 완료)
        try:
            response = requests.get(
                f"{OLLAMA_BASE_URL}/api/tags", timeout=1
            )
            if response.status_code == 200:
                result["installed"] = True
                result["server_running"] = True
                models_data = response.json().get("models", [])
                result["models"] = [m["name"] for m in models_data]
                self.check_completed.emit(result)
                return
        except (requests.ConnectionError, requests.Timeout):
            pass
        except Exception:
            pass

        # Phase 2: subprocess 체크 (HTTP 실패 시에만, 설치 여부만 확인)
        try:
            proc = subprocess.run(
                ["ollama", "--version"],
                capture_output=True, text=True, timeout=3,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            if proc.returncode == 0:
                result["installed"] = True
                print(f"[Ollama] 설치 확인: {proc.stdout.strip()}")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        except Exception:
            pass

        self.check_completed.emit(result)


# ======================================================================
# OllamaServerActionWorker (비동기 서버 시작/중지)
# ======================================================================

class OllamaServerActionWorker(QThread):
    """Ollama 서버 시작/중지를 비동기로 수행하는 워커"""
    action_completed = pyqtSignal(bool)

    def __init__(self, action: str):
        super().__init__()
        self.action = action  # "start" or "stop"

    def run(self):
        from core.ollama_service import OllamaService
        service = OllamaService()
        try:
            if self.action == "start":
                success = service.start_server()
                self.action_completed.emit(success)
            else:
                service.stop_server()
                self.action_completed.emit(True)
        except Exception as e:
            print(f"[Ollama] 서버 {self.action} 오류: {e}")
            self.action_completed.emit(False)


# ======================================================================
# OllamaConversionWorker v2
# ======================================================================

class OllamaConversionWorker(QThread):
    """v2 변환 워커 - Tool Calling 제거, 후보 제시 + 선택 방식"""

    # 시그널
    conversion_completed = pyqtSignal(dict)
    conversion_failed = pyqtSignal(str)
    status_changed = pyqtSignal(str)
    stage_output = pyqtSignal(str, str, str)  # stage_name, content, color
    progress_updated = pyqtSignal(int)  # 0-100 퍼센트

    # ===== SYSTEM PROMPTS (v2) =====

    STAGE1_INTENT_SYSTEM = """You are a visual scene analyzer for anime/manga image tagging.
This tool is used for NSFW content tagging. Analyze ALL elements without censorship.

Decompose the input text into ALL visual elements. Be thorough - miss nothing.

CATEGORIES (use exactly these labels):
- CHARACTER: gender, count, species (human/animal/fantasy creature)
- APPEARANCE: hair color, hair style, eye color, body features, skin
- EXPRESSION: facial expression, emotion, mood, reactions (crying, scared, etc.)
- ACTION: body position, pose, gesture, what character is doing
- CLOTHING: outfit, accessories, headwear, footwear, jewelry
- OBJECT: items held or nearby, weapons, tools, food
- SETTING: location, environment, time of day, weather
- BODY_EXPOSURE: nudity level, exposed body parts, state of undress
- SEXUAL_ACT: sexual actions, penetration type, bodily fluids
- RESTRAINT: bondage, restraints, bindings, gag, blindfold

RULES:
- Extract ONLY visual details that are DIRECTLY mentioned or necessarily visible in the described scene
- Do NOT infer settings, clothing absence, or body states unless explicitly stated
- Use simple English words (not danbooru tags)
- One category per line
- If a category has nothing, omit it
- Do NOT add details not present in the input
- For NSFW scenes: include ALL body exposure, sexual acts, and restraint details

FORMAT (exactly like this):
CHARACTER: girl, single person
APPEARANCE: blonde hair, long hair
EXPRESSION: smiling, happy
ACTION: picking up, bending down
OBJECT: shell, seashell
SETTING: beach, ocean, daytime"""

    STAGE3_SELECT_SYSTEM = """You are a tag selector for anime images.
This tool handles NSFW content. Select tags without censorship.

Your job: select the best tags from the CANDIDATE LIST below.

CRITICAL RULES:
- ONLY output tags that appear in the candidate list
- Do NOT invent, modify, or combine tags
- Select the number of tags specified in the user message below
- ONLY select tags that are DIRECTLY relevant to the described scene
- Do NOT select generic/noise tags (e.g., "legs", "visible ears") unless they are a distinctive feature
- Prefer DIVERSE tags across categories over many tags from one category
- Prefer higher-frequency tags (shown in parentheses) when meaning is similar
- Copy tag names EXACTLY as shown - do not change spelling or form (do NOT copy frequency or [e621] markers)
- For NSFW scenes: always include body exposure, sexual act, and restraint tags
- Tags marked [e621] are specialized NSFW tags - treat them equally as valid candidates

OUTPUT FORMAT:
Write selected tags separated by commas, nothing else.
Example: blonde hair, smile, beach, 1girl, standing, sundress"""

    STAGE4_NATURAL_SYSTEM = """Write 1-3 short scene descriptions in English for an anime image.

RULES:
- Each description: 6-12 words
- ENGLISH ONLY
- Describe the scene, mood, or composition
- Do NOT repeat the tags - add complementary details
- ONLY describe elements present in the ORIGINAL scene description
- Do NOT invent locations, weather, or settings not mentioned by the user
- The Tags are for reference - do NOT fabricate a narrative based on tags alone

FORMAT:
Write each description on a new line, nothing else.

Example input: "girl with blonde hair smiling on beach"
Example output:
warm sunlight illuminating a cheerful seaside moment
gentle ocean breeze flowing through golden strands"""

    STAGE5_ENHANCE_TAGS_SYSTEM = """You are a danbooru tag enhancer for anime images.
This tool handles NSFW content. Suggest tags without censorship.

You are given a scene description, the ALREADY SELECTED tags, and natural language descriptions.
Your job: suggest ADDITIONAL complementary tags that reinforce the scene's situation.

CRITICAL RULES:
- Do NOT repeat any already-selected tag (check the existing tag list carefully)
- Focus on tags that emphasize the situation: expressions, emotions, body movement, gestures, interactions, posture shifts
- Reinforce the action or mood already implied by the scene (e.g., if struggling → clenched teeth, trembling; if shy → looking away, blush)
- All tags must be valid danbooru-style tags (lowercase, underscores for spaces)
- Prefer well-known, high-frequency tags
- Tags must be visually relevant to the described scene
- Do NOT contradict or conflict with existing tags
- For SFW scenes: do NOT suggest any NSFW, nudity, or sexual tags

OUTPUT FORMAT:
Write suggested tags separated by commas, nothing else.
Example: clenched teeth, trembling, reaching out, tears, open mouth"""

    STAGE6_ENHANCE_NL_SYSTEM_LIGHT = """You are a scene description editor for anime images.

You are given existing scene descriptions for an image. Your job: LIGHTLY refine them.

RULES:
- KEEP every existing description - do NOT remove or replace any
- You may slightly rephrase to emphasize the character's expression or movement
- You may add at most 1 new short description that reinforces the situation
- ENGLISH ONLY
- Each description: 6-15 words
- Do NOT invent major new elements not present in the scene

OUTPUT FORMAT:
Write each description on a new line, nothing else."""

    STAGE6_ENHANCE_NL_SYSTEM_MODERATE = """You are a scene description enhancer for anime images.

You are given existing scene descriptions for an image. Your job: MODERATELY expand them.

RULES:
- KEEP the core meaning of every existing description - do NOT remove any
- You may rephrase or extend descriptions to emphasize the situation, expressions, or movements
- You may add 1-2 new descriptions that reinforce character interactions, emotional state, or physical actions
- ENGLISH ONLY
- Each description: 6-18 words
- Stay faithful to the original scene - only add details that logically fit

OUTPUT FORMAT:
Write each description on a new line, nothing else."""

    STAGE6_ENHANCE_NL_SYSTEM_STRONG = """You are a scene description enhancer for anime images.

You are given existing scene descriptions for an image. Your job: STRONGLY expand and enrich them.

RULES:
- PRESERVE the meaning of every existing description - do NOT remove any
- Actively emphasize the situation: reinforce expressions, body language, gestures, and character interactions
- Add 2-3 new descriptions that deepen the emotional intensity, physical movement, or dramatic tension of the scene
- ENGLISH ONLY
- Each description: 6-22 words
- Be creative but stay consistent with the scene's situation and characters

OUTPUT FORMAT:
Write each description on a new line, nothing else."""

    STAGE6_ENHANCE_NL_SYSTEM_MAX = """You are a scene description enhancer for anime images.

You are given existing scene descriptions for an image. Your job: MAXIMALLY expand and transform them into rich, detailed scene fragments.

RULES:
- PRESERVE the core idea of every existing description - do NOT remove any
- Dramatically emphasize the situation: vivid expressions, intense body language, dynamic movements, emotional reactions, character interactions
- Add 3-5 new descriptions that amplify the scene's dramatic weight, physical details of actions, and emotional undertones
- ENGLISH ONLY
- Each description: 8-25 words
- Be bold and creative - fully convey the intensity and emotion of the scene, but stay coherent

OUTPUT FORMAT:
Write each description on a new line, nothing else."""

    # LLM 카테고리 변형 → 정규 카테고리 매핑
    _CATEGORY_ALIASES = {
        "CHARACTERS": "CHARACTER", "CHAR": "CHARACTER",
        "APPEARANCES": "APPEARANCE", "LOOK": "APPEARANCE", "LOOKS": "APPEARANCE",
        "EXPRESSIONS": "EXPRESSION", "EMOTION": "EXPRESSION", "EMOTIONS": "EXPRESSION",
        "ACTIONS": "ACTION", "POSE": "ACTION", "POSES": "ACTION",
        "CLOTHES": "CLOTHING", "OUTFIT": "CLOTHING", "OUTFITS": "CLOTHING",
        "OBJECTS": "OBJECT", "ITEM": "OBJECT", "ITEMS": "OBJECT",
        "SETTINGS": "SETTING", "LOCATION": "SETTING", "ENVIRONMENT": "SETTING",
        "BODY": "BODY_EXPOSURE", "NUDITY": "BODY_EXPOSURE", "EXPOSURE": "BODY_EXPOSURE",
        "SEXUAL": "SEXUAL_ACT", "SEX": "SEXUAL_ACT", "SEXUAL_ACTS": "SEXUAL_ACT",
        "BONDAGE": "RESTRAINT", "RESTRAINTS": "RESTRAINT", "BINDING": "RESTRAINT",
    }

    def __init__(self, prompt: str, model: str, tag_db: TagDatabase,
                 auto_offload: bool = True, e621_nsfw_boost: bool = False,
                 creativity: float = 0.5):
        super().__init__()
        self.prompt = prompt
        self.model = model
        self.tag_db = tag_db
        self.auto_offload = auto_offload
        self.e621_nsfw_boost = e621_nsfw_boost
        self.creativity = creativity
        self._profile = CREATIVITY_PROFILES.get(creativity, CREATIVITY_PROFILES[0.5])
        self._is_cancelled = False
        self._is_nsfw = False
        self._detected_imminent_tags: List[str] = []

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        """v2 파이프라인 실행"""
        if not self.prompt:
            self.conversion_failed.emit("프롬프트가 비어있습니다.")
            return

        try:
            self.stage_output.emit("시작",
                f"입력: {self.prompt}\n모델: {self.model}\n"
                f"Creativity: {self.creativity} ({self._profile['label']})",
                "#00ffff")

            # 스케일 결정
            input_length = len(self.prompt)
            if input_length < 15:
                self._output_scale = "minimal"
            elif input_length < 40:
                self._output_scale = "short"
            elif input_length < 80:
                self._output_scale = "medium"
            else:
                self._output_scale = "long"

            # Explicit 영어 태그 추출 + NSFW 판정
            explicit_tags_raw = self._extract_explicit_english_tags(self.prompt)
            explicit_tags, self._is_nsfw = self._validate_explicit_tags(explicit_tags_raw)

            self.stage_output.emit("Pre: Explicit Tags",
                f"원본: {explicit_tags_raw}\n검증됨: {explicit_tags}\nNSFW: {self._is_nsfw}",
                "#ff00ff")
            self.progress_updated.emit(5)  # Pre: 5%

            if self._is_cancelled:
                return

            # ===== STAGE 0: 번역 =====
            self.status_changed.emit("Stage 0: 번역 중...")
            translation = self._stage0_translate()

            self.stage_output.emit("Stage 0: 번역",
                f"원문: {self.prompt}\n번역: {translation}",
                "#888888")
            self.progress_updated.emit(10)  # Stage 0: 10%

            if self._is_cancelled:
                return

            # ===== STAGE 1: 의도 분해 (LLM) =====
            self.status_changed.emit("Stage 1: 의도 분해 중...")
            intents = self._stage1_decompose_intents(translation)

            intent_display = "\n".join(
                f"  {cat}: {', '.join(concepts)}"
                for cat, concepts in intents.items()
            )
            self.stage_output.emit("Stage 1: 의도 분해 (LLM)",
                f"카테고리별 개념:\n{intent_display}",
                "#ffff00")
            self.progress_updated.emit(25)  # Stage 1: 25%

            if self._is_cancelled:
                return

            # ===== STAGE 2: 후보 검색 (Code) =====
            self.status_changed.emit("Stage 2: 후보 검색 중...")
            candidates, search_log = self._stage2_retrieve_candidates(
                intents, self.prompt, translation, explicit_tags)

            candidates_display = ""
            for cat, tags in candidates.items():
                tag_strs = [f"{t['tag']} ({t['count']:,})" for t in tags[:8]]
                candidates_display += f"  [{cat}] {', '.join(tag_strs)}\n"

            self.stage_output.emit("Stage 2: 후보 검색 (Code)",
                f"검색 로그:\n{search_log}\n\n후보 태그:\n{candidates_display}",
                "#00ff00")
            self.progress_updated.emit(35)  # Stage 2: 35%

            if self._is_cancelled:
                return

            # ===== STAGE 2.5: e621 NSFW Boost =====
            if self.e621_nsfw_boost:
                existing_candidate_tags = set()
                for tags in candidates.values():
                    for t in tags:
                        existing_candidate_tags.add(t["tag"])

                e621_hints = self.tag_db.e621_nsfw_boost(
                    intents=intents,
                    existing_tags=existing_candidate_tags,
                    limit=20,
                    min_danbooru_freq=100,
                    e621_only_limit=15,
                )

                if e621_hints:
                    candidates["E621_NSFW_BOOST"] = e621_hints

                    danbooru_hints = [h for h in e621_hints if not h.get("_e621_only")]
                    e621_only_hints = [h for h in e621_hints if h.get("_e621_only")]

                    hint_display = ", ".join(
                        f"{h['tag']}({h.get('_base_score', 0):.1f}/{h['count']:,})"
                        for h in danbooru_hints[:10]
                    )
                    if e621_only_hints:
                        hint_display += "\n[e621 전용] " + ", ".join(
                            f"{h['tag'].replace('_', ' ')}({h.get('_base_score', 0):.1f})"
                            for h in e621_only_hints
                        )

                    source_cats = [c for c in intents if c in E621_NSFW_BOOST_CATEGORIES]
                    self.stage_output.emit("Stage 2.5: e621 NSFW Boost",
                        f"소스 카테고리: {source_cats}\n"
                        f"의도 개념 {sum(len(intents.get(c, [])) for c in E621_NSFW_BOOST_CATEGORIES)}개 "
                        f"-> danbooru {len(danbooru_hints)}개 + e621 전용 {len(e621_only_hints)}개\n\n{hint_display}",
                        "#ff66ff")
                else:
                    self.stage_output.emit("Stage 2.5: e621 NSFW Boost",
                        "NSFW 부스트 결과 없음",
                        "#ff66ff")

            self.progress_updated.emit(40)  # Stage 2.5: 40%

            if self._is_cancelled:
                return

            # ===== STAGE 3: 태그 선택 (LLM) =====
            self.status_changed.emit("Stage 3: 태그 선택 중...")

            # imminent 감지 시: explicit_tags의 raw 동사를 imminent 형태로 교체
            if self._detected_imminent_tags:
                _VERB_TO_NOUN = {
                    "penetrate": "penetration", "rape": "rape",
                    "kiss": "kiss", "hug": "hug", "bite": "bite",
                    "punch": "punch", "kill": "death", "die": "death",
                    "finger": "fingering", "lick": "cunnilingus",
                    "suck": "fellatio", "fuck": "sex",
                }
                imminent_norm = {t.lower().replace("_", " ") for t in self._detected_imminent_tags}
                new_explicit = []
                for et in explicit_tags:
                    et_lower = et.lower().replace("_", " ")
                    noun = _VERB_TO_NOUN.get(et_lower, et_lower)
                    imminent_form = f"imminent {noun}"
                    if imminent_form in imminent_norm:
                        new_explicit.append(imminent_form)
                    else:
                        new_explicit.append(et)
                explicit_tags = new_explicit

            selected_tags = self._stage3_select_tags(translation, candidates, explicit_tags)

            self.stage_output.emit("Stage 3: 태그 선택 (LLM)",
                f"선택된 태그 ({len(selected_tags)}개):\n{', '.join(selected_tags)}",
                "#ff8800")
            self.progress_updated.emit(55)  # Stage 3: 55%

            if self._is_cancelled:
                return

            # ===== STAGE 4: 자연어 생성 (LLM) =====
            self.status_changed.emit("Stage 4: 자연어 생성 중...")
            natural_parts = self._stage4_generate_natural(selected_tags, translation)

            self.stage_output.emit("Stage 4: 자연어 (LLM)",
                f"생성된 자연어:\n" + "\n".join(natural_parts),
                "#00ffff")
            self.progress_updated.emit(70)  # Stage 4: 70%

            if self._is_cancelled:
                return

            # ===== STAGE 5: 태그 확장 (LLM) =====
            # e621 힌트 추출 + 중복 제거 (Stage 5에서 맥락에 맞는 것만 LLM이 선별)
            e621_hint_tags = []
            if self.e621_nsfw_boost and "E621_NSFW_BOOST" in candidates:
                e621_only_items = [
                    t for t in candidates["E621_NSFW_BOOST"]
                    if t.get("_e621_only")
                ]
                e621_hint_tags = self._deduplicate_e621_hints(e621_only_items)

            enhance_tags_range = self._profile.get("enhance_tags", (0, 0))
            if enhance_tags_range[1] > 0:
                self.status_changed.emit("Stage 5: 태그 확장 중...")
                added_tags = self._stage5_enhance_tags(
                    translation, selected_tags, natural_parts, e621_hint_tags)

                if added_tags:
                    self.stage_output.emit("Stage 5: 태그 확장 (LLM)",
                        f"추가 태그 ({len(added_tags)}개):\n{', '.join(added_tags)}",
                        "#ff66cc")
                    selected_tags = selected_tags + added_tags
                else:
                    self.stage_output.emit("Stage 5: 태그 확장 (LLM)",
                        "추가 태그 없음", "#ff66cc")
            else:
                self.stage_output.emit("Stage 5: 태그 확장",
                    "스킵 (보수적 모드)", "#ff66cc")

            self.progress_updated.emit(80)  # Stage 5: 80%

            if self._is_cancelled:
                return

            # ===== STAGE 6: 자연어 확장 (LLM) =====
            nl_mode = self._profile.get("enhance_nl", "none")
            if nl_mode != "none":
                self.status_changed.emit("Stage 6: 자연어 확장 중...")
                enhanced_parts = self._stage6_enhance_natural(
                    translation, selected_tags, natural_parts)

                if enhanced_parts != natural_parts:
                    self.stage_output.emit("Stage 6: 자연어 확장 (LLM)",
                        f"확장된 자연어 ({len(enhanced_parts)}개):\n" + "\n".join(enhanced_parts),
                        "#66ffcc")
                    natural_parts = enhanced_parts
                else:
                    self.stage_output.emit("Stage 6: 자연어 확장 (LLM)",
                        "변경 없음 (원본 유지)", "#66ffcc")
            else:
                self.stage_output.emit("Stage 6: 자연어 확장",
                    "스킵 (보수적 모드)", "#66ffcc")

            self.progress_updated.emit(90)  # Stage 6: 90%

            if self._is_cancelled:
                return

            # 결과 정리
            result = self._finalize_result(selected_tags, natural_parts)

            self.stage_output.emit("최종 결과",
                f"태그: {len(result['tags'])}개\n자연어: {len(result['natural_parts'])}개\n\n{result['combined_prompt']}",
                "#ffffff")
            self.progress_updated.emit(100)

            self.conversion_completed.emit(result)

        except Exception as e:
            import traceback
            error_msg = f"{str(e)}\n\n{traceback.format_exc()}"
            self.stage_output.emit("오류", error_msg, "#ff0000")
            self.conversion_failed.emit(str(e))

    # ===== STAGE 0: Translation =====

    def _stage0_translate(self) -> str:
        """Google Translate로 한국어 → 영어 번역"""
        if self._contains_korean(self.prompt):
            translation = korean_to_english(self.prompt)
            return translation if translation else self.prompt
        return self.prompt

    # ===== STAGE 1: Intent Decomposition (LLM) =====

    def _stage1_decompose_intents(self, translation: str) -> Dict[str, List[str]]:
        """문장을 카테고리별 시각 개념으로 분해"""
        system_content = self.STAGE1_INTENT_SYSTEM
        if not self._is_nsfw:
            system_content += """

NOTE: This is a SFW (non-NSFW) scene. Do NOT add BODY_EXPOSURE, SEXUAL_ACT, or RESTRAINT categories unless explicitly described in the input. Do NOT imply nudity or undress."""

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": f"Analyze this scene:\n{translation}"}
        ]

        response = self._ollama_chat(messages, temperature=self._profile["temps"][0])
        content = response.get("message", {}).get("content", "")

        intents = self._parse_intent_output(content)

        total_concepts = sum(len(v) for v in intents.values())
        if total_concepts == 0:
            intents = self._fallback_intent_extract(translation)

        return intents

    def _parse_intent_output(self, content: str) -> Dict[str, List[str]]:
        """LLM 출력에서 카테고리별 개념 파싱"""
        intents: Dict[str, List[str]] = {}

        for line in content.strip().split("\n"):
            line = line.strip()
            if not line:
                continue

            match = re.match(r'^([A-Za-z_ ]+)\s*:\s*(.+)$', line)
            if match:
                raw_category = match.group(1).strip().upper().replace(" ", "_")
                category = self._resolve_category(raw_category)
                if category:
                    concepts = [c.strip() for c in match.group(2).split(",") if c.strip()]
                    if concepts:
                        if category in intents:
                            intents[category].extend(concepts)
                        else:
                            intents[category] = concepts

        return intents

    def _resolve_category(self, raw: str) -> Optional[str]:
        """LLM 출력 카테고리명을 정규 카테고리로 변환"""
        if raw in INTENT_CATEGORIES:
            return raw
        if raw in self._CATEGORY_ALIASES:
            return self._CATEGORY_ALIASES[raw]
        if raw.endswith("S") and raw[:-1] in INTENT_CATEGORIES:
            return raw[:-1]
        return None

    def _fallback_intent_extract(self, translation: str) -> Dict[str, List[str]]:
        """Fallback: 규칙 기반 의도 추출"""
        intents: Dict[str, List[str]] = {}

        KEYWORD_MAP = {
            "CHARACTER": ["girl", "boy", "woman", "man", "person", "child", "female", "male"],
            "APPEARANCE": ["blonde", "brunette", "redhead", "silver", "black hair", "white hair",
                          "long hair", "short hair", "ponytail", "twintails", "blue eyes",
                          "red eyes", "green eyes"],
            "EXPRESSION": ["smile", "smiling", "crying", "angry", "blush", "blushing",
                          "happy", "sad", "surprised", "scared", "embarrassed",
                          "tears", "trembling", "fear"],
            "ACTION": ["sitting", "standing", "lying", "running", "walking", "holding",
                      "looking", "eating", "drinking", "sleeping", "fighting", "dancing",
                      "kneeling", "crouching", "bending"],
            "CLOTHING": ["dress", "uniform", "bikini", "swimsuit", "armor", "maid",
                        "skirt", "shirt", "hat", "glasses", "ribbon", "boots"],
            "OBJECT": ["sword", "gun", "book", "flower", "umbrella", "phone",
                      "food", "cup", "staff", "shield", "bag"],
            "SETTING": ["beach", "forest", "school", "city", "room", "outdoor",
                       "indoor", "night", "sunset", "rain", "snow", "sky",
                       "ocean", "mountain", "garden", "cafe"],
            "BODY_EXPOSURE": ["nude", "naked", "topless", "bottomless", "exposed",
                             "nipples", "breasts", "pussy", "penis", "bare feet",
                             "barefoot", "undressed"],
            "SEXUAL_ACT": ["sex", "penetration", "oral", "anal", "vaginal",
                          "fellatio", "cum", "ejaculation", "masturbation"],
            "RESTRAINT": ["bondage", "bound", "tied", "handcuffs", "rope",
                         "blindfold", "gag", "chains", "restrained"]
        }

        text_lower = translation.lower()
        for category, keywords in KEYWORD_MAP.items():
            found = [kw for kw in keywords if kw in text_lower]
            if found:
                intents[category] = found

        return intents

    # ===== STAGE 2: Candidate Tag Retrieval (Code) =====

    def _is_concept_explicit(self, concept: str, original: str, translation: str) -> bool:
        """개념이 사용자 입력에 명시적으로 언급되었는지 확인"""
        words = [w for w in concept.lower().split() if len(w) >= 4]
        if not words:
            return True
        combined = f"{original} {translation}".lower()
        return any(re.search(r'\b' + re.escape(w) + r'\b', combined) for w in words)

    def _stage2_retrieve_candidates(self, intents: Dict[str, List[str]],
                                     original_prompt: str,
                                     translation: str = "",
                                     explicit_tags: List[str] = None) -> Tuple[Dict[str, List[dict]], str]:
        """코드 기반 후보 태그 검색 - LLM 없음, Danbooru Only"""
        candidates: Dict[str, List[dict]] = {}
        search_log_lines = []
        seen_tags = set()

        def _collect_results(query: str, category: str, category_tags: list):
            results = self.tag_db.search_enhanced(
                query, limit=10, nsfw_priority=self._is_nsfw,
                danbooru_only=True
            )
            new_results = []
            for r in results:
                tag_key = r["tag"].lower().replace("_", " ")
                if tag_key not in seen_tags:
                    seen_tags.add(tag_key)
                    new_results.append(r)
            category_tags.extend(new_results)
            return new_results

        # 1. 각 카테고리의 각 개념에 대해 어절 분해 + enhanced search
        for category, concepts in intents.items():
            category_tags = []

            for concept in concepts:
                # APPEARANCE 필터
                if category in EXPLICIT_REQUIRED_CATEGORIES:
                    if not self._is_concept_explicit(concept, original_prompt, translation):
                        search_log_lines.append(
                            f"  [{category}] \"{concept}\" -> FILTERED (not explicit)")
                        continue

                new_results = _collect_results(concept, category, category_tags)
                found_tags = [r["tag"] for r in new_results[:5]]
                search_log_lines.append(
                    f"  [{category}] \"{concept}\" -> {found_tags}"
                )

                # 어절 분해
                words = concept.strip().split()
                if len(words) >= 2:
                    for word in words:
                        word = word.strip()
                        if len(word) < 2:
                            continue
                        sub_results = _collect_results(word, category, category_tags)
                        if sub_results:
                            sub_tags = [r["tag"] for r in sub_results[:3]]
                            search_log_lines.append(
                                f"    -> word \"{word}\" -> {sub_tags}"
                            )

            category_tags.sort(key=lambda x: x.get("count", 0), reverse=True)
            if category_tags:
                candidates[category] = category_tags[:15]

        # 1.3. Explicit tags 후보 검색 (사용자 직접 입력 영어 태그)
        if explicit_tags:
            explicit_category_tags = []
            for et in explicit_tags:
                new_results = _collect_results(et, "EXPLICIT", explicit_category_tags)
                if new_results:
                    found_tags = [r["tag"] for r in new_results[:5]]
                    search_log_lines.append(
                        f"  [EXPLICIT] \"{et}\" -> {found_tags}")
            if explicit_category_tags:
                explicit_category_tags.sort(key=lambda x: x.get("count", 0), reverse=True)
                candidates["EXPLICIT"] = explicit_category_tags[:15]

        # 1.5. Imminent 패턴 감지
        _VERB_TO_NOUN = {
            "penetrate": "penetration", "rape": "rape",
            "kiss": "kiss", "hug": "hug", "bite": "bite",
            "punch": "punch", "kill": "death", "die": "death",
            "finger": "fingering", "lick": "cunnilingus",
            "suck": "fellatio", "fuck": "sex",
        }
        combined_text = f"{original_prompt} {translation}".lower()
        imminent_patterns = [
            r'(?:trying|about|going|ready)\s+to\s+(\w+)',
            r'(\S+)\s*하려[고는]',
        ]
        imminent_candidates = []
        for pat in imminent_patterns:
            for m in re.finditer(pat, combined_text):
                action = m.group(1).strip()
                action_noun = _VERB_TO_NOUN.get(action, action)
                queries = {f"imminent {action_noun}"}
                if action_noun != action:
                    queries.add(f"imminent {action}")

                for imminent_query in queries:
                    results = self.tag_db.search_enhanced(
                        imminent_query, limit=5, nsfw_priority=self._is_nsfw,
                        danbooru_only=True
                    )
                    for r in results:
                        tag_key = r["tag"].lower().replace("_", " ")
                        if tag_key not in seen_tags:
                            seen_tags.add(tag_key)
                            imminent_candidates.append(r)
                    if results:
                        found = [r["tag"] for r in results[:3]]
                        search_log_lines.append(
                            f"  [IMMINENT] \"{imminent_query}\" -> {found}"
                        )
        if imminent_candidates:
            imminent_candidates.sort(key=lambda x: x.get("count", 0), reverse=True)
            if "ACTION" in candidates:
                candidates["ACTION"].extend(imminent_candidates[:5])
            else:
                candidates["ACTION"] = imminent_candidates[:5]
            self._detected_imminent_tags = [r["tag"] for r in imminent_candidates[:5]]
        else:
            self._detected_imminent_tags = []

        # 2. 한국어 원문에서 직접 태그 검색 (보충, danbooru only)
        if self._contains_korean(original_prompt):
            kr_results = self.tag_db.search_korean(
                original_prompt, limit=10, danbooru_only=True
            )
            kr_tags = []
            for r in kr_results:
                tag_key = r["tag"].lower().replace("_", " ")
                if tag_key not in seen_tags:
                    seen_tags.add(tag_key)
                    kr_tags.append(r)

            if kr_tags:
                candidates["KR_DIRECT"] = kr_tags
                kr_tag_names = [r["tag"] for r in kr_tags[:5]]
                search_log_lines.append(
                    f"  [KR_DIRECT] 한국어 직접 매칭 -> {kr_tag_names}"
                )

        # 3. 후보가 너무 적으면 siblings 확장 (danbooru only)
        total_candidates = sum(len(v) for v in candidates.values())
        if total_candidates < 10:
            search_log_lines.append("  [EXPAND] 후보 부족 -> siblings 확장")
            for category, tags in list(candidates.items()):
                for tag_info in tags[:3]:
                    siblings = self.tag_db.get_siblings(tag_info["tag"], limit=3)
                    for sib in siblings:
                        sib_key = sib.lower().replace("_", " ")
                        if sib_key not in seen_tags:
                            sib_info = self.tag_db._get_tag_info(sib, danbooru_only=True)
                            if sib_info:
                                seen_tags.add(sib_key)
                                candidates.setdefault(category, []).append(sib_info)

        search_log = "\n".join(search_log_lines)
        return candidates, search_log

    # ===== STAGE 3: Tag Selection (LLM) =====

    def _stage3_select_tags(self, translation: str,
                            candidates: Dict[str, List[dict]],
                            explicit_tags: List[str]) -> List[str]:
        """후보에서 최적 태그 선택 (LLM)"""
        base_counts = {
            "minimal": (5, 8), "short": (6, 10),
            "medium": (8, 14), "long": (10, 18)
        }
        base_min, base_max = base_counts.get(self._output_scale, (10, 18))
        mult = self._profile["tag_mult"]
        min_tags = max(4, int(base_min * mult))
        max_tags = max(6, int(base_max * mult))

        candidate_text = self._format_candidates_for_llm(candidates)

        explicit_str = ""
        if explicit_tags:
            explicit_str = f"\nMUST INCLUDE these tags: {', '.join(explicit_tags)}"

        imminent_hint = ""
        if self._detected_imminent_tags:
            imminent_list = ', '.join(self._detected_imminent_tags[:3])
            imminent_hint = f"\nIMPORTANT: The scene describes an action ABOUT TO happen. Prefer 'imminent' tags ({imminent_list}) over raw verb forms."

        user_content = f"""Scene: {translation}
{explicit_str}{imminent_hint}
CANDIDATE TAGS:
{candidate_text}
Select {min_tags}-{max_tags} tags from the candidates above.
Output only the selected tags, separated by commas:"""

        system_content = self.STAGE3_SELECT_SYSTEM
        if not self._is_nsfw:
            system_content += """

IMPORTANT - SFW SCENE:
- This scene is NOT flagged as NSFW
- Do NOT select any nudity, sexual, or body exposure tags (nude, naked, topless, no bra, no panties, etc.)
- If a character wears clothing (bikini, swimsuit, etc.), do NOT imply nudity
- Do NOT select negation tags implying undress (no shoes, no shirt, etc.) unless explicitly stated"""

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content}
        ]

        response = self._ollama_chat(messages, temperature=self._profile["temps"][1])
        content = response.get("message", {}).get("content", "")

        selected = self._parse_comma_tags(content)

        all_candidate_tags = set()
        for tags in candidates.values():
            for t in tags:
                all_candidate_tags.add(t["tag"].lower().replace("_", " "))
                all_candidate_tags.add(t["tag"].lower())

        validated = []
        for tag in selected:
            tag_lower = tag.lower().replace("_", " ").strip()
            if tag_lower in all_candidate_tags:
                valid = self.tag_db.validate_tag(tag)
                validated.append(valid if valid else tag)
            else:
                best = self._fuzzy_find_in_candidates(tag, candidates)
                if best:
                    validated.append(best)

        validated_lower = {v.lower().replace("_", " ") for v in validated}
        for et in explicit_tags:
            et_lower = et.lower().replace("_", " ")
            if et_lower not in validated_lower:
                validated.insert(0, et)
                validated_lower.add(et_lower)

        validated = self._remove_duplicates(validated)

        return validated

    def _format_candidates_for_llm(self, candidates: Dict[str, List[dict]]) -> str:
        """후보 태그를 LLM에 제시할 포맷으로 변환"""
        lines = []
        e621_lines = []

        for category, tags in candidates.items():
            if not tags:
                continue
            tag_strs = []
            max_items = 12 if category != "E621_NSFW_BOOST" else 15
            for t in tags[:max_items]:
                name = t["tag"].replace("_", " ")
                freq = t.get("count", 0)
                if freq >= 1_000_000:
                    freq_str = f"{freq/1_000_000:.1f}M"
                elif freq >= 1_000:
                    freq_str = f"{freq/1_000:.0f}K"
                else:
                    freq_str = str(freq)
                suffix = " [e621]" if t.get("_e621_only") else ""
                tag_strs.append(f"{name} ({freq_str}){suffix}")

            line = f"[{category}] {', '.join(tag_strs)}"
            if category == "E621_NSFW_BOOST":
                e621_lines.append(line)
            else:
                lines.append(line)

        result = "\n".join(lines)
        if e621_lines:
            result += "\n\n--- NSFW TAGS (MUST consider for NSFW scenes) ---\n"
            result += "These tags describe specific NSFW details. You MUST select relevant ones from this section for NSFW scenes.\n"
            result += "\n".join(e621_lines)
        return result

    def _fuzzy_find_in_candidates(self, query: str,
                                   candidates: Dict[str, List[dict]]) -> Optional[str]:
        """후보 풀에서 가장 유사한 태그 찾기"""
        query_norm = query.lower().replace("_", " ").strip()
        best_match = None
        best_score = 0

        for tags in candidates.values():
            for t in tags:
                tag_norm = t["tag"].lower().replace("_", " ")
                if query_norm in tag_norm or tag_norm in query_norm:
                    score = len(query_norm) / max(len(tag_norm), 1)
                    if score > best_score:
                        best_score = score
                        best_match = t["tag"]

        return best_match if best_score > 0.5 else None

    # ===== STAGE 4: Natural Language Generation (LLM) =====

    def _stage4_generate_natural(self, tags: List[str], translation: str) -> List[str]:
        """자연어 묘사 생성"""
        base_counts = {"minimal": 1, "short": 2, "medium": 2, "long": 3}
        base_n = base_counts.get(self._output_scale, 2)
        nat_n = max(1, int(base_n * self._profile["nat_mult"]))
        desc_range = str(nat_n) if nat_n <= 1 else f"{nat_n-1}-{nat_n}"

        word_min, word_max = self._profile.get("nat_words", (6, 12))

        readable_tags = [t.replace("_", " ") for t in tags]

        user_content = f"""Scene: {translation}
Tags: {', '.join(readable_tags)}

Write {desc_range} scene descriptions ({word_min}-{word_max} words each).
Output only the descriptions, one per line:"""

        system_content = self.STAGE4_NATURAL_SYSTEM.replace(
            "6-12 words", f"{word_min}-{word_max} words"
        ).replace(
            "1-3 short", f"{desc_range} short" if nat_n > 1 else "1 short"
        )

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content}
        ]

        response = self._ollama_chat(messages, temperature=self._profile["temps"][2])
        content = response.get("message", {}).get("content", "")

        parts = self._parse_natural_output(content)
        return parts

    def _parse_natural_output(self, content: str) -> List[str]:
        """자연어 출력 파싱 (줄바꿈 구분)"""
        parts = []
        for line in content.strip().split("\n"):
            line = line.strip()
            line = re.sub(r'^[\d\.\-\*\•]+\s*', '', line).strip()
            if not line or len(line) < 5:
                continue
            if self._contains_korean(line):
                continue
            if any(kw in line.lower() for kw in ["example", "output:", "description:"]):
                continue
            parts.append(line)
        return parts

    # ===== e621 Hint Deduplication =====

    def _deduplicate_e621_hints(self, e621_items: list) -> List[str]:
        """유사 e621 힌트 중복 제거 — 핵심 단어를 공유하는 태그 그룹에서 최고 점수만 유지

        예: extreme_penetration, urethral_penetration, ear_penetration, large_penetration
        → 모두 "penetration" 공유 → 최고 점수 1개만 유지
        """
        if not e621_items:
            return []

        MIN_TOKEN_LEN = 4  # 짧은 전치사/관사 무시 (in, on, of, etc.)

        entries = []
        for item in e621_items:
            tag = item["tag"].replace("_", " ")
            tokens = frozenset(w for w in tag.split() if len(w) >= MIN_TOKEN_LEN)
            entries.append({
                "tag": tag,
                "score": item.get("_relevance", 0),
                "tokens": tokens,
            })

        # 토큰 공유 기반 그룹핑
        groups: list = []  # List[List[dict]]
        for entry in entries:
            merged_idx = None
            for i, group in enumerate(groups):
                for member in group:
                    if entry["tokens"] & member["tokens"]:  # 교집합 존재
                        merged_idx = i
                        break
                if merged_idx is not None:
                    break
            if merged_idx is not None:
                groups[merged_idx].append(entry)
            else:
                groups.append([entry])

        # 각 그룹에서 최고 점수 태그만 선택
        result = []
        for group in groups:
            best = max(group, key=lambda e: e["score"])
            result.append((best["tag"], best["score"]))

        # 점수 내림차순 정렬
        result.sort(key=lambda x: x[1], reverse=True)
        return [tag for tag, _ in result]

    # ===== STAGE 5: Tag Enhancement (LLM) =====

    def _stage5_enhance_tags(self, translation: str, existing_tags: List[str],
                              natural_parts: List[str],
                              e621_hints: List[str] = None) -> List[str]:
        """창의성 설정에 따라 추가 태그 제안 (기존 태그 보존, e621 힌트 활용)"""
        enhance_range = self._profile.get("enhance_tags", (0, 0))
        min_add, max_add = enhance_range
        if max_add <= 0:
            return []

        readable_tags = [t.replace("_", " ") for t in existing_tags]
        nl_text = "\n".join(natural_parts) if natural_parts else "(none)"

        system_content = self.STAGE5_ENHANCE_TAGS_SYSTEM
        if not self._is_nsfw:
            system_content += "\n\nIMPORTANT - SFW SCENE: Do NOT suggest any nudity, sexual, or body exposure tags."

        # e621 부스트 활성 시 시스템 프롬프트 강화
        if e621_hints:
            system_content += """

e621 INTEGRATION MODE (ACTIVE):
You are provided with curated e621 tags as hints below.
These are specialized NSFW/fetish tags from e621 that describe specific actions, restraints, or body interactions.
RULES:
- You MUST include at least 1-2 e621 hint tags in your output if they match the scene context
- e621 tags use underscores (e.g., legs_tied, ball_gag) — output them as-is
- Prefer e621 tags that directly describe physical actions, restraints, or interactions depicted in the scene
- Do NOT ignore the e621 hint section"""

        # e621 힌트 섹션
        e621_section = ""
        if e621_hints:
            e621_list = ", ".join(e621_hints)
            e621_section = f"""

=== e621 SPECIALIZED TAGS (PRIORITY — pick 1-2 that match) ===
{e621_list}
You MUST select at least 1 tag from this list if it matches the scene."""

        user_content = f"""Scene: {translation}

Existing tags: {', '.join(readable_tags)}
Existing descriptions:
{nl_text}{e621_section}

Suggest {min_add}-{max_add} additional complementary tags.
Output only the suggested tags, separated by commas:"""

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content}
        ]

        response = self._ollama_chat(messages, temperature=self._profile["temps"][2])
        content = response.get("message", {}).get("content", "")

        raw_tags = self._parse_comma_tags(content)

        # 기존 태그 중복 제거 + DB 검증 (e621 힌트는 DB에 없어도 허용)
        existing_norm = {normalize_tag(t) for t in existing_tags}
        e621_hint_norm = {normalize_tag(t) for t in (e621_hints or [])}
        validated = []
        for tag in raw_tags:
            tag_norm = normalize_tag(tag)
            if tag_norm in existing_norm:
                continue
            valid = self.tag_db.validate_tag(tag)
            if valid:
                existing_norm.add(normalize_tag(valid))
                validated.append(valid)
            elif tag_norm in e621_hint_norm:
                # e621 힌트에서 온 태그는 DB에 없어도 허용
                existing_norm.add(tag_norm)
                validated.append(tag)

        return validated[:max_add]

    # ===== STAGE 6: Natural Language Enhancement (LLM) =====

    def _stage6_enhance_natural(self, translation: str, all_tags: List[str],
                                 existing_parts: List[str]) -> List[str]:
        """창의성 설정에 따라 자연어 묘사 수정/확장 (기존 묘사 보존)"""
        nl_mode = self._profile.get("enhance_nl", "none")
        if nl_mode == "none":
            return existing_parts

        system_map = {
            "light": self.STAGE6_ENHANCE_NL_SYSTEM_LIGHT,
            "moderate": self.STAGE6_ENHANCE_NL_SYSTEM_MODERATE,
            "strong": self.STAGE6_ENHANCE_NL_SYSTEM_STRONG,
            "max": self.STAGE6_ENHANCE_NL_SYSTEM_MAX,
        }
        system_content = system_map.get(nl_mode, self.STAGE6_ENHANCE_NL_SYSTEM_MODERATE)

        if not self._is_nsfw:
            system_content += "\n\nIMPORTANT - SFW SCENE: Keep all descriptions appropriate. Do NOT add any sexual or explicit content."

        readable_tags = [t.replace("_", " ") for t in all_tags]
        existing_text = "\n".join(f"- {p}" for p in existing_parts) if existing_parts else "(none)"

        user_content = f"""Scene: {translation}
Tags: {', '.join(readable_tags)}

Existing descriptions (MUST preserve all):
{existing_text}

Enhance the descriptions according to your instructions.
Output only the descriptions, one per line:"""

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content}
        ]

        response = self._ollama_chat(messages, temperature=self._profile["temps"][2])
        content = response.get("message", {}).get("content", "")

        enhanced = self._parse_natural_output(content)

        # 안전장치: LLM이 기존 묘사를 누락한 경우 원본 반환
        if not enhanced or len(enhanced) < len(existing_parts):
            return existing_parts

        return enhanced

    # ===== Ollama API =====

    def _ollama_chat(self, messages: list, temperature: float = None) -> dict:
        """Ollama /api/chat 호출 (tool calling 없음)

        Session 관리 + 에러 핸들링 포함.
        """
        options = {"num_predict": 2048}
        if temperature is not None:
            options["temperature"] = temperature

        keep_alive = 0 if self.auto_offload else -1

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": options,
            "keep_alive": keep_alive
        }

        try:
            with requests.Session() as session:
                response = session.post(
                    f"{OLLAMA_BASE_URL}/api/chat",
                    json=payload,
                    timeout=180
                )
                session.close()

                # 어댑터 정리 (Dummy 스레드 방지)
                if hasattr(session, 'adapters'):
                    for adapter in session.adapters.values():
                        if hasattr(adapter, 'poolmanager') and adapter.poolmanager:
                            adapter.poolmanager.clear()

            if response.status_code != 200:
                error_text = response.text[:200]
                raise RuntimeError(
                    f"Ollama API 오류 (HTTP {response.status_code}): {error_text}")

            return response.json()

        except requests.ConnectionError:
            raise RuntimeError("Ollama 서버에 연결할 수 없습니다. 서버가 실행 중인지 확인하세요.")
        except requests.Timeout:
            raise RuntimeError("Ollama 응답 시간 초과 (180초). 모델이 로드 중이거나 서버가 과부하일 수 있습니다.")

    # ===== 유틸리티 =====

    def _contains_korean(self, text: str) -> bool:
        return bool(re.search(r'[\uAC00-\uD7AF\u1100-\u11FF]', text))

    def _extract_explicit_english_tags(self, prompt: str) -> List[str]:
        """사용자 입력에서 영어 태그/단어 추출"""
        english_spans = re.findall(r'[a-zA-Z][a-zA-Z0-9_ ]*[a-zA-Z0-9]', prompt)

        skip_words = {'the', 'a', 'an', 'is', 'are', 'in', 'on', 'at', 'to', 'of',
                      'and', 'or', 'but', 'with', 'for', 'from', 'by', 'it', 'this',
                      'that', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had',
                      'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may',
                      'might', 'shall', 'can', 'not', 'no', 'so', 'if', 'then'}

        explicit = []
        seen = set()

        for span in english_spans:
            words = [w.strip().lower() for w in re.split(r'[\s_,]+', span) if w.strip()]
            words = [w for w in words if len(w) >= 2 and w not in skip_words]

            for w in words:
                if w not in seen:
                    seen.add(w)
                    explicit.append(w)

            for i in range(len(words) - 1):
                bigram = f"{words[i]} {words[i+1]}"
                if bigram not in seen:
                    seen.add(bigram)
                    explicit.append(bigram)

        return explicit

    def _validate_explicit_tags(self, explicit_tags: List[str]) -> Tuple[List[str], bool]:
        """Explicit tags DB 검증 + NSFW 판정"""
        nsfw_keywords = {
            'penis', 'pussy', 'vagina', 'sex', 'cum', 'nude', 'naked',
            'breasts', 'nipples', 'ass', 'anus', 'penetration',
            'oral', 'anal', 'vaginal', 'fellatio',
            'horse penis', 'tentacle', 'breeding', 'gangbang',
        }

        validated_tags = []
        is_nsfw = False

        for tag in explicit_tags:
            tag_lower = tag.lower().replace("_", " ")
            if any(kw in tag_lower for kw in nsfw_keywords):
                is_nsfw = True

            valid = self.tag_db.validate_tag(tag)
            if valid:
                if valid not in validated_tags:
                    validated_tags.append(valid)
            else:
                if tag not in validated_tags:
                    validated_tags.append(tag)

        return validated_tags, is_nsfw

    def _parse_comma_tags(self, content: str) -> List[str]:
        """콤마 구분 태그 파싱"""
        if "{" in content:
            try:
                start = content.index("{")
                end = content.rindex("}") + 1
                data = json.loads(content[start:end])
                tags = data.get("tags", data.get("selected_tags", data.get("validated_tags", [])))
                if isinstance(tags, list) and tags:
                    return [str(t).strip() for t in tags if str(t).strip()]
            except (json.JSONDecodeError, ValueError):
                pass

        content = re.sub(r'```[^`]*```', '', content)
        content = re.sub(r'`[^`]*`', '', content)

        for prefix in ["selected tags:", "tags:", "output:", "result:"]:
            idx = content.lower().find(prefix)
            if idx >= 0:
                content = content[idx + len(prefix):]
                break

        parts = re.split(r'[,\n]+', content)
        tags = []
        for part in parts:
            tag = part.strip().strip('"').strip("'").strip('-').strip('*').strip()
            tag = re.sub(r'^\d+\.\s*', '', tag)
            tag = re.sub(r'\s*\[e621\]\s*$', '', tag)  # [e621] 마커 제거
            tag = re.sub(r'\s*\([^)]*[KMkm]\)\s*$', '', tag)
            tag = re.sub(r'\s*\(\d[\d,]*\)\s*$', '', tag)
            if tag and len(tag) >= 2 and not self._contains_korean(tag):
                tags.append(tag)
        return tags

    def _remove_duplicates(self, tags: List[str]) -> List[str]:
        seen = set()
        result = []
        for tag in tags:
            t = normalize_tag(tag)
            if t and t not in seen:
                seen.add(t)
                result.append(tag)
        return result

    def _remove_person_count_tags(self, tags: List[str]) -> List[str]:
        person_tags_to_remove = {
            "1boy", "2boys", "3boys", "4boys", "5boys", "6+boys",
            "1 boy", "2 boys", "3 boys", "4 boys", "5 boys", "6+ boys",
            "1girl", "2girls", "3girls", "4girls", "5girls", "6+girls",
            "1 girl", "2 girls", "3 girls", "4 girls", "5 girls", "6+ girls",
            "1other", "2others", "3others", "4others", "5others", "6+others",
            "girl", "boy", "other",
        }
        result = []
        for tag in tags:
            if normalize_tag(tag) not in person_tags_to_remove:
                result.append(tag)
        return result

    def _finalize_result(self, tags: List[str], natural_parts: List[str]) -> dict:
        base_tag_limits = {"minimal": 8, "short": 10, "medium": 14, "long": 18}
        base_nat_limits = {"minimal": 2, "short": 3, "medium": 3, "long": 4}

        mult = self._profile["tag_mult"]
        nat_mult = self._profile["nat_mult"]
        max_tags = max(6, int(base_tag_limits.get(self._output_scale, 18) * mult))
        max_natural = max(1, int(base_nat_limits.get(self._output_scale, 3) * nat_mult))

        tags = self._remove_person_count_tags(tags)

        # SFW 안전장치: NSFW/부정 태그 필터링
        if not self._is_nsfw:
            _NSFW_BLOCKLIST = {
                'nude', 'naked', 'topless', 'bottomless', 'nipples', 'pussy',
                'penis', 'anus', 'no bra', 'no panties', 'no underwear',
                'cum', 'sex', 'penetration', 'fellatio', 'oral',
                'completely nude', 'partially nude',
                'no pants', 'no shirt', 'no skirt', 'no socks',
                'partially undressed', 'undressing',
            }
            tags = [t for t in tags if normalize_tag(t) not in _NSFW_BLOCKLIST]

        tags = tags[:max_tags]
        natural_parts = natural_parts[:max_natural]

        # 언더스코어 → 공백
        tags = [t.replace("_", " ") for t in tags]

        all_parts = tags + natural_parts
        combined = ", ".join(all_parts)

        # 전체 소문자 + 쉼표 앞 온점 제거 + em dash → 쉼표
        combined = combined.lower()
        combined = re.sub(r'\s*—\s*', ', ', combined)
        combined = re.sub(r'\.(\s*,)', r'\1', combined)

        tags = [t.lower() for t in tags]
        natural_parts = [re.sub(r'\.(\s*,)', r'\1', p.lower()) for p in natural_parts]
        if natural_parts:
            natural_parts[-1] = natural_parts[-1].rstrip('.')
        combined = combined.rstrip('.')

        return {
            "tags": tags,
            "natural_parts": natural_parts,
            "combined_prompt": combined
        }


# ======================================================================
# OllamaModule (UI)
# ======================================================================

class OllamaModule(BaseMiddleModule):
    """Ollama 기반 자연어 → 태그 변환 모듈 (GPU Only)"""

    def __init__(self):
        super().__init__()

        self.NAI_compatibility = True
        self.WEBUI_compatibility = True
        self.COMFYUI_compatibility = True

        self.ollama_installed = False
        self.ollama_server_running = False
        self.available_models: List[str] = []

        self.tag_db = TagDatabase()

        self.selected_model = SUPPORTED_MODELS[0]

        # UI 위젯
        self.widget = None
        self.input_text = None
        self.output_text = None
        self.status_label = None
        self.convert_btn = None
        self.copy_btn = None
        self.model_combo = None
        self.load_checkbox = None
        self.offload_checkbox = None
        self.creativity_combo = None
        self.e621_nsfw_boost_checkbox = None
        self.debug_btn = None
        self.debug_panel = None  # DebugPanel (QDialog, lazy 생성)

        # Lazy init / Session control / Progress
        self._status_check_worker = None
        self._server_action_worker = None
        self.install_guide_row = None
        self.server_toggle_btn = None
        self.server_status_indicator = None
        self.server_control_row = None
        self.vram_status_label = None
        self.progress_bar = None

        self.worker: Optional[OllamaConversionWorker] = None

    def get_title(self) -> str:
        return "🦙 Ollama (GPU Only)"

    def get_order(self) -> int:
        return 6

    def initialize_with_context(self, context):
        self.app_context = context

    def create_widget(self, parent=None) -> QWidget:
        if self.widget:
            return self.widget

        self.widget = QWidget(parent)
        main_layout = QVBoxLayout(self.widget)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(get_scaled_size(8))

        ollama_group = self._create_ollama_group()
        main_layout.addWidget(ollama_group)

        input_layout = self._create_input_layout()
        main_layout.addLayout(input_layout)

        button_layout = self._create_button_layout()
        main_layout.addLayout(button_layout)

        # Progress bar (변환 중에만 표시)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(get_scaled_size(20))
        self.progress_bar.setFormat("%v% - 대기 중")
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                background-color: {DARK_COLORS['bg_secondary']};
                text-align: center;
                font-size: {get_scaled_font_size(12)}px;
                color: {DARK_COLORS['text_primary']};
            }}
            QProgressBar::chunk {{
                background-color: {DARK_COLORS['accent_blue']};
                border-radius: {get_scaled_size(3)}px;
            }}
        """)
        main_layout.addWidget(self.progress_bar)

        output_layout = self._create_output_layout()
        main_layout.addLayout(output_layout)

        # Lazy 초기화: UI 렌더 완료 후 비동기 상태 확인
        QTimer.singleShot(0, self._start_status_check)
        QTimer.singleShot(100, self._load_resources)

        return self.widget

    def _load_resources(self):
        """태그 DB 로드"""
        if self.tag_db.load():
            e621_sib = len(getattr(self.tag_db, '_e621_siblings', {}))
            e621_wiki = len(getattr(self.tag_db, '_e621_wiki_links', {}))
            print(f"[Ollama] 태그 DB 로드 완료: {self.tag_db.tag_count:,}개 "
                  f"(danbooru: {len(self.tag_db.danbooru_tags):,}, "
                  f"e621: {len(self.tag_db.e621_tags):,}, "
                  f"e621 siblings: {e621_sib:,}, wiki-links: {e621_wiki:,})")

    def _create_ollama_group(self) -> QGroupBox:
        group = QGroupBox("🤖 Ollama API")
        group.setStyleSheet(f"""
            QGroupBox {{
                font-size: {get_scaled_font_size(16)}px;
                font-weight: bold;
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding-top: {get_scaled_size(12)}px;
                margin-top: {get_scaled_size(8)}px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: {get_scaled_size(8)}px;
                padding: 0 {get_scaled_size(4)}px;
            }}
            QGroupBox QLabel {{
                border: none;
            }}
        """)

        layout = QVBoxLayout(group)
        layout.setSpacing(6)

        # 상태 행: [status_label] [stretch] [디버그 패널] [새로고침]
        status_row = QHBoxLayout()
        status_row.setSpacing(get_scaled_size(8))

        self.status_label = QLabel("⚪ 확인 중...")
        self.status_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(14)}px;
            color: {DARK_COLORS['text_secondary']};
        """)
        status_row.addWidget(self.status_label)
        status_row.addStretch()

        # 디버그 패널 버튼 (새로고침 왼쪽)
        self.debug_btn = QPushButton("🔍 디버그")
        self.debug_btn.setStyleSheet(get_dynamic_styles()['secondary_button'])
        self.debug_btn.setToolTip("변환 과정의 각 스테이지 출력을 확인합니다")
        self.debug_btn.clicked.connect(self._toggle_debug_panel)
        status_row.addWidget(self.debug_btn)

        refresh_btn = QPushButton("🔄 새로고침")
        refresh_btn.setStyleSheet(get_dynamic_styles()['secondary_button'])
        refresh_btn.clicked.connect(self._check_ollama_installed)
        status_row.addWidget(refresh_btn)

        layout.addLayout(status_row)

        # 설치 안내 행 (미설치 시만 표시)
        self.install_guide_row = QWidget()
        install_row_layout = QHBoxLayout(self.install_guide_row)
        install_row_layout.setContentsMargins(0, 0, 0, 0)
        install_row_layout.setSpacing(get_scaled_size(8))

        install_btn = QPushButton("📥 Ollama 설치하러 가기")
        install_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['accent_blue']};
                color: {DARK_COLORS['text_primary']};
                border: none;
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(6)}px {get_scaled_size(12)}px;
                font-size: {get_scaled_font_size(13)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['accent_blue_hover']};
            }}
        """)
        install_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        install_btn.clicked.connect(self._open_ollama_download_page)
        install_row_layout.addWidget(install_btn)

        verify_btn = QPushButton("🔍 설치 확인")
        verify_btn.setStyleSheet(get_dynamic_styles()['secondary_button'])
        verify_btn.clicked.connect(self._start_status_check)
        install_row_layout.addWidget(verify_btn)

        install_row_layout.addStretch()
        self.install_guide_row.setVisible(False)
        layout.addWidget(self.install_guide_row)

        # 서버 제어 행 (설치 시만 표시)
        self.server_control_row = QWidget()
        server_row_layout = QHBoxLayout(self.server_control_row)
        server_row_layout.setContentsMargins(0, 0, 0, 0)
        server_row_layout.setSpacing(get_scaled_size(8))

        self.server_status_indicator = QLabel("●")
        self.server_status_indicator.setFixedWidth(get_scaled_size(16))
        self.server_status_indicator.setStyleSheet(f"""
            font-size: {get_scaled_font_size(14)}px;
            color: {DARK_COLORS['text_disabled']};
        """)
        server_row_layout.addWidget(self.server_status_indicator)

        server_label = QLabel("서버:")
        server_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(13)}px;
            color: {DARK_COLORS['text_secondary']};
        """)
        server_row_layout.addWidget(server_label)

        self.server_toggle_btn = QPushButton("▶ 서버 시작")
        self.server_toggle_btn.setStyleSheet(get_dynamic_styles()['secondary_button'])
        self.server_toggle_btn.setToolTip("Ollama 서버를 시작하거나 중지합니다 (VRAM 해제)")
        self.server_toggle_btn.clicked.connect(self._on_toggle_server)
        server_row_layout.addWidget(self.server_toggle_btn)

        self.vram_status_label = QLabel("")
        self.vram_status_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(12)}px;
            color: {DARK_COLORS['text_disabled']};
        """)
        server_row_layout.addWidget(self.vram_status_label)

        server_row_layout.addStretch()
        self.server_control_row.setVisible(False)
        layout.addWidget(self.server_control_row)

        # 모델 선택 행
        model_layout = QHBoxLayout()
        model_layout.setSpacing(get_scaled_size(8))

        model_label = QLabel("모델:")
        model_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(13)}px;
            color: {DARK_COLORS['text_secondary']};
        """)
        model_layout.addWidget(model_label)

        self.model_combo = QComboBox()
        self.model_combo.addItems(SUPPORTED_MODELS)
        self.model_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(4)}px {get_scaled_size(6)}px;
                font-size: {get_scaled_font_size(13)}px;
            }}
            QComboBox:hover {{
                border-color: {DARK_COLORS['accent_blue']};
            }}
            QComboBox::drop-down {{
                border: none;
                width: {get_scaled_size(20)}px;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 6px solid {DARK_COLORS['text_secondary']};
                margin-right: {get_scaled_size(6)}px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                selection-background-color: {DARK_COLORS['accent_blue']};
            }}
        """)
        self.model_combo.currentTextChanged.connect(self._on_model_changed)
        model_layout.addWidget(self.model_combo, stretch=1)

        self.load_checkbox = QCheckBox("LOAD")
        self.load_checkbox.setStyleSheet(f"""
            QCheckBox {{
                font-size: {get_scaled_font_size(13)}px;
                color: {DARK_COLORS['text_primary']};
                spacing: {get_scaled_size(4)}px;
            }}
        """)
        self.load_checkbox.setToolTip("체크 시 모델을 VRAM에 미리 로드합니다")
        self.load_checkbox.stateChanged.connect(self._on_load_checkbox_changed)
        model_layout.addWidget(self.load_checkbox)

        layout.addLayout(model_layout)

        # Offload 체크박스
        self.offload_checkbox = QCheckBox("프롬프트 생성 후 자동으로 VRAM에서 Offload 합니다")
        self.offload_checkbox.setStyleSheet(f"""
            QCheckBox {{
                font-size: {get_scaled_font_size(12)}px;
                color: {DARK_COLORS['text_secondary']};
                spacing: {get_scaled_size(4)}px;
            }}
        """)
        self.offload_checkbox.setChecked(True)
        layout.addWidget(self.offload_checkbox)

        # Creativity + e621 Boost 행
        creativity_row = QHBoxLayout()
        creativity_row.setSpacing(get_scaled_size(8))

        creativity_label = QLabel("Creativity:")
        creativity_label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(13)}px;
            color: {DARK_COLORS['text_secondary']};
        """)
        creativity_row.addWidget(creativity_label)

        self.creativity_combo = QComboBox()
        for val, profile in sorted(CREATIVITY_PROFILES.items()):
            self.creativity_combo.addItem(f"{val:.1f} - {profile['label']}", val)
        self.creativity_combo.setCurrentIndex(2)  # 0.5 (기본)
        self.creativity_combo.setToolTip(
            "낮을수록 보수적 (적은 태그, 짧은 자연어)\n"
            "높을수록 창의적 (많은 태그, 긴 자연어, 높은 temperature)")
        self.creativity_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(4)}px {get_scaled_size(6)}px;
                font-size: {get_scaled_font_size(13)}px;
            }}
            QComboBox:hover {{
                border-color: {DARK_COLORS['accent_blue']};
            }}
            QComboBox::drop-down {{
                border: none;
                width: {get_scaled_size(20)}px;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 6px solid {DARK_COLORS['text_secondary']};
                margin-right: {get_scaled_size(6)}px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                selection-background-color: {DARK_COLORS['accent_blue']};
            }}
        """)
        creativity_row.addWidget(self.creativity_combo)

        self.e621_nsfw_boost_checkbox = QCheckBox("e621 NSFW Boost")
        self.e621_nsfw_boost_checkbox.setChecked(False)
        self.e621_nsfw_boost_checkbox.setToolTip(
            "e621 NSFW 전문 태그(bondage, restraint, sexual acts, body exposure)를 LLM에 전달")
        self.e621_nsfw_boost_checkbox.setStyleSheet(f"""
            QCheckBox {{
                font-size: {get_scaled_font_size(12)}px;
                color: {DARK_COLORS['text_secondary']};
                spacing: {get_scaled_size(4)}px;
            }}
        """)
        creativity_row.addWidget(self.e621_nsfw_boost_checkbox)
        creativity_row.addStretch()

        layout.addLayout(creativity_row)

        return group

    def _create_input_layout(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setSpacing(get_scaled_size(4))

        label = QLabel("자연어 프롬프트 (한국어/영어)")
        label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(14)}px;
            font-weight: bold;
            color: {DARK_COLORS['text_primary']};
        """)
        layout.addWidget(label)

        self.input_text = QTextEdit()
        self.input_text.setPlaceholderText("예: 해변에서 조개를 줍는 금발 소녀")
        self.input_text.setMinimumHeight(get_scaled_size(120))
        self.input_text.setMaximumHeight(get_scaled_size(200))
        self.input_text.setStyleSheet(get_dynamic_styles()['compact_textedit'])
        setModernStyle(self.input_text)
        layout.addWidget(self.input_text)

        return layout

    def _create_button_layout(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setSpacing(get_scaled_size(8))

        self.convert_btn = QPushButton("🔄 변환")
        self.convert_btn.setStyleSheet(get_dynamic_styles()['primary_button'])
        self.convert_btn.clicked.connect(self._on_convert)
        self.convert_btn.setEnabled(False)
        layout.addWidget(self.convert_btn)

        self.copy_btn = QPushButton("📋 클립보드에 복사")
        self.copy_btn.setStyleSheet(get_dynamic_styles()['secondary_button'])
        self.copy_btn.clicked.connect(self._on_copy)
        self.copy_btn.setEnabled(False)
        layout.addWidget(self.copy_btn)

        layout.addStretch()

        return layout

    def _create_output_layout(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setSpacing(get_scaled_size(4))

        label = QLabel("변환된 태그 프롬프트")
        label.setStyleSheet(f"""
            font-size: {get_scaled_font_size(14)}px;
            font-weight: bold;
            color: {DARK_COLORS['text_primary']};
        """)
        layout.addWidget(label)

        self.output_text = QTextEdit()
        self.output_text.setPlaceholderText("변환 결과가 여기에 표시됩니다...")
        self.output_text.setMinimumHeight(get_scaled_size(120))
        self.output_text.setStyleSheet(get_dynamic_styles()['compact_textedit'])
        self.output_text.setReadOnly(True)
        setModernStyle(self.output_text)
        layout.addWidget(self.output_text)

        return layout

    # ===== Ollama 상태 확인 (Lazy / 비동기) =====

    def _start_status_check(self):
        """비동기 상태 확인 워커 시작"""
        if self._status_check_worker and self._status_check_worker.isRunning():
            return
        self.status_label.setText("⚪ 확인 중...")
        self._status_check_worker = OllamaStatusCheckWorker()
        self._status_check_worker.check_completed.connect(self._on_status_check_complete)
        self._status_check_worker.finished.connect(self._status_check_worker.deleteLater)
        self._status_check_worker.start()

    def _on_status_check_complete(self, result: dict):
        """상태 확인 결과 처리 (UI 스레드에서 실행)"""
        self._status_check_worker = None
        self.ollama_installed = result["installed"]
        self.ollama_server_running = result["server_running"]
        self.available_models = result["models"]

        if not self.ollama_installed:
            self._set_status("🔴 Ollama 미설치", False)
            self._show_install_guide(True)
            self._update_session_controls()
        elif not self.ollama_server_running:
            self._set_status("🟡 설치됨 / 서버 OFF", False)
            self._show_install_guide(False)
            self._update_session_controls()
        else:
            self._set_status(
                f"🟢 서버 연결됨 ({len(self.available_models)} 모델)", True)
            self._show_install_guide(False)
            self._update_session_controls()

    def _check_ollama_installed(self):
        """새로고침 버튼 호환용 래퍼"""
        self._start_status_check()

    def _set_status(self, text: str, enable_convert: bool):
        if self.status_label:
            self.status_label.setText(text)
        if self.convert_btn:
            self.convert_btn.setEnabled(enable_convert)

    def _show_install_guide(self, show: bool):
        """설치 안내 행 가시성 제어"""
        if self.install_guide_row:
            self.install_guide_row.setVisible(show)

    def _open_ollama_download_page(self):
        """Ollama 다운로드 페이지 열기"""
        QDesktopServices.openUrl(QUrl("https://ollama.com/download"))

    def _on_toggle_server(self):
        """서버 시작/중지 토글"""
        if self.ollama_server_running:
            self._stop_server()
        else:
            self._start_server()

    def _start_server(self):
        """서버 비동기 시작"""
        if not self.ollama_installed:
            return
        self.server_toggle_btn.setEnabled(False)
        self.server_toggle_btn.setText("⏳ 시작 중...")
        self._server_action_worker = OllamaServerActionWorker(action="start")
        self._server_action_worker.action_completed.connect(self._on_server_action_complete)
        self._server_action_worker.finished.connect(self._server_action_worker.deleteLater)
        self._server_action_worker.start()

    def _stop_server(self):
        """서버 비동기 중지 (VRAM 해제)"""
        self.server_toggle_btn.setEnabled(False)
        self.server_toggle_btn.setText("⏳ 중지 중...")
        self._server_action_worker = OllamaServerActionWorker(action="stop")
        self._server_action_worker.action_completed.connect(self._on_server_action_complete)
        self._server_action_worker.finished.connect(self._server_action_worker.deleteLater)
        self._server_action_worker.start()

    def _on_server_action_complete(self, success: bool):
        """서버 액션 완료 → 상태 재확인"""
        self._server_action_worker = None
        if self.server_toggle_btn:
            self.server_toggle_btn.setEnabled(True)
        self._start_status_check()

    def _update_session_controls(self):
        """서버 제어 행 UI 갱신"""
        if not self.ollama_installed:
            if self.server_control_row:
                self.server_control_row.setVisible(False)
            return

        if self.server_control_row:
            self.server_control_row.setVisible(True)

        if self.ollama_server_running:
            if self.server_toggle_btn:
                self.server_toggle_btn.setText("⏹ 서버 중지")
                self.server_toggle_btn.setToolTip("Ollama 서버를 중지합니다 (모든 VRAM 해제)")
            if self.server_status_indicator:
                self.server_status_indicator.setStyleSheet(f"""
                    font-size: {get_scaled_font_size(14)}px;
                    color: {DARK_COLORS['success']};
                """)
        else:
            if self.server_toggle_btn:
                self.server_toggle_btn.setText("▶ 서버 시작")
                self.server_toggle_btn.setToolTip("Ollama 서버를 시작합니다")
            if self.server_status_indicator:
                self.server_status_indicator.setStyleSheet(f"""
                    font-size: {get_scaled_font_size(14)}px;
                    color: {DARK_COLORS['error']};
                """)
            if self.vram_status_label:
                self.vram_status_label.setText("")
            # 서버 꺼지면 LOAD 해제
            if self.load_checkbox and self.load_checkbox.isChecked():
                self.load_checkbox.blockSignals(True)
                self.load_checkbox.setChecked(False)
                self.load_checkbox.blockSignals(False)

    # ===== 이벤트 핸들러 =====

    def _on_model_changed(self, model_name: str):
        self.selected_model = model_name
        print(f"[Ollama] 모델 선택: {model_name}")

    def _on_load_checkbox_changed(self, state):
        if state == Qt.CheckState.Checked.value:
            self._preload_model()
        else:
            self._unload_model()

    def _preload_model(self):
        if not self.ollama_server_running:
            self.load_checkbox.setChecked(False)
            return

        try:
            self.status_label.setText("⏳ 모델 로딩 중...")
            url = f"{OLLAMA_BASE_URL}/api/chat"
            payload = {
                "model": self.selected_model,
                "messages": [{"role": "user", "content": "test"}],
                "stream": False,
                "keep_alive": -1
            }
            response = requests.post(url, json=payload, timeout=120)
            if response.status_code == 200:
                self._set_status("🟢 모델 로드됨", True)
                if self.vram_status_label:
                    self.vram_status_label.setText("VRAM 로드됨")
                    self.vram_status_label.setStyleSheet(f"""
                        font-size: {get_scaled_font_size(12)}px;
                        color: {DARK_COLORS['success']};
                    """)
                print(f"[Ollama] 모델 VRAM 로드 완료: {self.selected_model}")
            else:
                self.load_checkbox.setChecked(False)
                self._set_status("🟡 로드 실패", True)
        except Exception as e:
            self.load_checkbox.setChecked(False)
            self._set_status(f"🟡 로드 실패: {str(e)[:15]}", True)
            print(f"[Ollama] 모델 로드 실패: {e}")

    def _unload_model(self):
        if not self.ollama_server_running:
            return

        try:
            url = f"{OLLAMA_BASE_URL}/api/chat"
            payload = {
                "model": self.selected_model,
                "messages": [{"role": "user", "content": ""}],
                "stream": False,
                "keep_alive": 0
            }
            requests.post(url, json=payload, timeout=10)
            if self.vram_status_label:
                self.vram_status_label.setText("")
            self._start_status_check()
            print(f"[Ollama] 모델 VRAM 언로드: {self.selected_model}")
        except Exception as e:
            print(f"[Ollama] 모델 언로드 실패: {e}")

    def _toggle_debug_panel(self):
        """디버그 패널 토글 (lazy 생성, hide/show 재사용)"""
        try:
            if self.debug_panel is not None and self.debug_panel.isVisible():
                self.debug_panel.hide()
                return
        except RuntimeError:
            # C/C++ object deleted - 재생성 필요
            self.debug_panel = None

        if self.debug_panel is None:
            self.debug_panel = DebugPanel(self.widget)

        self.debug_panel.show()
        self.debug_panel.raise_()
        self.debug_panel.activateWindow()

    def _on_stage_output(self, stage_name: str, content: str, color: str):
        """디버그 패널에 스테이지 출력 전달"""
        try:
            if self.debug_panel is not None and self.debug_panel.isVisible():
                self.debug_panel.add_stage(stage_name, content, color)
        except RuntimeError:
            pass

    def _on_convert(self):
        prompt = self.input_text.toPlainText().strip()
        if not prompt:
            QMessageBox.warning(self.widget, "경고", "프롬프트를 입력해주세요.")
            return

        if not self.ollama_server_running:
            QMessageBox.warning(
                self.widget,
                "Ollama 서버 필요",
                "Ollama 서버가 실행되지 않았습니다.\n서버 시작 버튼을 눌러주세요."
            )
            return

        self.convert_btn.setEnabled(False)
        self.convert_btn.setText("⏳ 변환 중...")
        self.output_text.clear()

        # Progress bar 표시
        if self.progress_bar:
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("0% - 시작 중...")
            self.progress_bar.setVisible(True)

        # 디버그 패널 클리어
        try:
            if self.debug_panel is not None and self.debug_panel.isVisible():
                self.debug_panel.clear()
        except RuntimeError:
            pass

        auto_offload = self.offload_checkbox.isChecked()
        e621_nsfw_boost = self.e621_nsfw_boost_checkbox.isChecked()
        creativity = self.creativity_combo.currentData()

        self.worker = OllamaConversionWorker(
            prompt=prompt,
            model=self.selected_model,
            tag_db=self.tag_db,
            auto_offload=auto_offload,
            e621_nsfw_boost=e621_nsfw_boost,
            creativity=creativity
        )
        self.worker.conversion_completed.connect(self._on_conversion_complete)
        self.worker.conversion_failed.connect(self._on_conversion_failed)
        self.worker.status_changed.connect(self._on_status_changed)
        self.worker.stage_output.connect(self._on_stage_output)
        self.worker.progress_updated.connect(self._on_progress_updated)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.start()

    def _on_conversion_complete(self, result: dict):
        self.copy_btn.setEnabled(True)

        combined = result.get("combined_prompt", "")
        tags = result.get("tags", [])
        natural = result.get("natural_parts", [])

        self.output_text.setPlainText(combined)
        print(f"[Ollama] 변환 완료: {len(tags)}개 태그, {len(natural)}개 자연어")

    def _on_conversion_failed(self, error: str):
        QMessageBox.critical(self.widget, "변환 오류", error)

    def _on_status_changed(self, status: str):
        if self.status_label:
            self.status_label.setText(f"⏳ {status}")

    def _on_progress_updated(self, percent: int):
        """Progress bar 업데이트"""
        if not self.progress_bar:
            return
        self.progress_bar.setValue(percent)
        if percent <= 5:
            self.progress_bar.setFormat(f"{percent}% - 전처리...")
        elif percent <= 15:
            self.progress_bar.setFormat(f"{percent}% - 번역 중...")
        elif percent <= 35:
            self.progress_bar.setFormat(f"{percent}% - 의도 분해 중...")
        elif percent <= 50:
            self.progress_bar.setFormat(f"{percent}% - 후보 검색 중...")
        elif percent <= 55:
            self.progress_bar.setFormat(f"{percent}% - e621 보강...")
        elif percent <= 80:
            self.progress_bar.setFormat(f"{percent}% - 태그 선택 중...")
        elif percent <= 95:
            self.progress_bar.setFormat(f"{percent}% - 자연어 생성 중...")
        else:
            self.progress_bar.setFormat(f"{percent}% - 완료!")

    def _on_worker_finished(self):
        self.convert_btn.setEnabled(True)
        self.convert_btn.setText("🔄 변환")
        self._start_status_check()

        # Progress bar: 100% 잠시 보여준 후 숨김
        if self.progress_bar:
            QTimer.singleShot(1500, lambda: self.progress_bar.setVisible(False)
                              if self.progress_bar else None)

        if self.worker:
            self.worker.deleteLater()
            self.worker = None

    def _on_copy(self):
        result = self.output_text.toPlainText().strip()
        if result:
            clipboard = QApplication.clipboard()
            clipboard.setText(result)

            original_text = self.copy_btn.text()
            self.copy_btn.setText("✅ 복사됨!")
            QTimer.singleShot(1500, lambda: self.copy_btn.setText(original_text))

    def cleanup(self):
        print("[OllamaModule] 리소스 정리 중...")

        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.quit()
            self.worker.wait(2000)
            self.worker.deleteLater()
            self.worker = None

        # Status check worker 정리
        if self._status_check_worker and self._status_check_worker.isRunning():
            self._status_check_worker.quit()
            self._status_check_worker.wait(1000)
        self._status_check_worker = None

        # Server action worker 정리
        if self._server_action_worker and self._server_action_worker.isRunning():
            self._server_action_worker.quit()
            self._server_action_worker.wait(1000)
        self._server_action_worker = None

        # Debug panel 안전 정리
        if self.debug_panel is not None:
            try:
                self.debug_panel.hide()
                self.debug_panel.deleteLater()
            except RuntimeError:
                pass
            self.debug_panel = None
