# -*- coding: utf-8 -*-
"""태그 조합 추천 - 인원 그룹별 모델과 질의 서비스.

설계 근거와 실측은 `tools/reco_probe/SPEC.md` 를 보라. 요약하면:

  원천은 `data/tags/*.parquet` 다. Quick Search 의 `.tgp` 는 빌드 시점에
  의상/특징/배경 어휘가 통째로 빠져 있어(`filters_removed`) 조합 추천에 못 쓴다.

  인원 그룹마다 표본추출된 CSR 하나를 두고, 역인덱스는 적재 시 재구성한다.
  질의는 정보량 최대 부분집합으로 백오프한 뒤, 매칭 게시물에서 lift 순 상위
  N개를 투영해 튜플을 센다.

  역할(taxonomy)은 표시용 라벨이다. 후보를 거르는 데 쓰면 품질이 떨어진다(실측).
"""

from .model import ComboModel, ModelHeader
from .person import PERSON_GROUPS, person_group_of

__all__ = ["ComboModel", "ModelHeader", "PERSON_GROUPS", "person_group_of"]
