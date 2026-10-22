"""Build the reviewed Korean group labels; development only, never imported by runtime.

Run with PYTHONUTF8=1. pandas/pyarrow are needed only to read the development
dictionary. The runtime consumes the small, prebuilt JSON, not these sources.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIN_CHARACTERS = 3
SOURCE_ORDER = ("dict", "kr_tags", "v2")
HANGUL = re.compile(r"[가-힣]")
ANGLE = re.compile(r"<([^>]+)>")
# Repetition across distinct normalized tags is evidence of a category, not a
# license to use it as a title. Unique genre/metadata labels are excluded too.
CATEGORY_WORDS = set("""
저작권 작품 작품명 시리즈 시리즈명 개념그룹 캐릭터 캐릭터그룹 게임 게임이름 게임타이틀
게임시리즈 게임작품 만화 애니 애니메이션 애니시리즈 애니메이션시리즈 소설 소설시리즈
라이트노벨 비주얼노벨 비주얼노벨시리즈 미연시 에로게 모바일게임 리듬게임 격투게임
버튜버 버튜버그룹 버튜버소속 버튜버소속사 버튜버채널 그룹 인물그룹 작가 아티스트
코믹스 보이스로이드 음성합성엔진 소프트웨어 아이돌프로젝트 음악프로젝트 미디어믹스
오리지널 설정 세계관 설정집 의인화 하렘 모험 격투 액션 초능력 러브코미디 취주악
이세계 일상 FPS SF SRPG RPG TCG TRPG VTuber VTuber그룹 primary
한글명 별명/애칭 원작 제작사 감독 테마파크 기업로고 상점 브랜드 프랜차이즈 특촬물
웹툰 메카무스메 과학어드벤처 웹소설시리즈 중국애니 일본애니 웹애니메이션 창작기획
창작시리즈 프리큐어시리즈 시카노코시리즈 산리오게임 미국만화 미국애니 FPS게임 함선의인화
스트리트파이터시리즈 2024년애니
""".split())
PLAIN_CATEGORIES = {"버추얼 아이돌 그룹", "애니메이션 영화", "걸 그룹", "게임작품",
                    "러브라이브시리즈", "어드벤처 게임", "추리 게임"}

# Explicit editorial decisions are kept here so rebuilding cannot silently undo
# the review. A value of None means hold, even if a dictionary offers a candidate.
REVIEWED_NAMES: dict[str, str | None] = {
    "2.5 jigen no ririsa": "2.5차원의 유혹",
    "9-nine-": "나인",
    "aa megami-sama": "오! 나의 여신님",
    "ace attorney": "역전재판",
    "ai the somnium files": "AI: 솜니움 파일",
    "alice in wonderland": "이상한 나라의 앨리스",
    "angel beats!": "엔젤 비트!",
    "arms (game)": "암즈",
    "baldur's gate": "발더스 게이트",
    "bang dream!": "뱅드림!",
    "blend s": "블렌드 S",
    "bocchi the rock!": "봇치 더 록!",
    "boku no hero academia": "나의 히어로 아카데미아",
    "bungou stray dogs": "문호 스트레이독스",
    "bural chingu": "불알친구",
    "chainsaw man": "체인소 맨",
    "chaos;child": "카오스 차일드",
    "chaos;head": "카오스 헤드",
    "choukou (alicesoft)": "초앙 시리즈",
    "cinderella series": "아이돌마스터 신데렐라 걸즈",
    "cthulhu mythos": "크툴루 신화",
    "d4dj": "디포디제이",
    "danganronpa (series)": "단간론파",
    "danny phantom": "대니 팬텀",
    "darkstalkers": "다크스토커즈",
    "deltarune": "델타룬",
    "dokyuu hentai hxeros": "초급편대 에그제로스",
    "dragon ball": "드래곤볼",
    "dumbbell nan kilo moteru?": "덤벨 몇 킬로까지 들 수 있어?",
    "dungeon and fighter": "던전앤파이터",
    "ensemble stars!": "앙상블 스타즈!",
    "elf-san wa yaserarenai.": "엘프 씨는 살을 뺄 수 없어.",
    "eureka seven (series)": "교향시편 유레카 세븐",
    "fate/grand order": "페이트/그랜드 오더",
    "fate/kaleid liner prisma illya": "페이트/칼레이드 라이너 프리즈마 이리야",
    "fate/strange fake": "페이트 스트레인지 페이크",
    "final fantasy": "파이널 판타지",
    "flip flappers": "플립 플래퍼즈",
    "frame arms girl": "프레임 암즈 걸",
    "free!": "프리!",
    "gabriel dropout": "가브릴 드롭아웃",
    "gakuen idolmaster": "학원 아이돌마스터",
    "getsuyoubi no tawawa": "월요일의 타와와",
    "gfriend": "여자친구",
    "girlfriend (kari)": "걸 프렌드(베타)",
    "girls band cry": "걸즈 밴드 크라이",
    "girls und panzer": "걸즈 앤 판처",
    "girls' frontline": "소녀전선",
    "goddess of victory: nikke": "승리의 여신: 니케",
    "granblue fantasy": "그랑블루 판타지",
    "guilty gear": "길티기어",
    "gundam": "건담",
    "hai to gensou no grimgar": "재와 환상의 그림갈",
    "hapymaher": "하피메아",
    "hataraku saibou": "일하는 세포",
    "hazbin hotel": "해즈빈 호텔",
    "helluva boss": "헬루바 보스",
    "hibi wa sugiredo meshi umashi": "흘러가는 나날, 밥은 맛있어",
    "hitoribocchi no marumaru seikatsu": "히토리 봇치의 ○○생활",
    "holostars": "홀로스타즈",
    "honkai impact 3rd": "붕괴3rd",
    "honkai: star rail": "붕괴: 스타레일",
    "ichigo mashimaro": "딸기 마시마로",
    "inazuma eleven (series)": "썬더 일레븐",
    "indie utaite": "개인 우타이테",
    "indie virtual youtuber": "개인 버튜버",
    "jojo no kimyou na bouken": "죠죠의 기묘한 모험",
    "k-on!": "케이온!",
    "kagerou project": "카게로우 프로젝트",
    "kanojo mo kanojo": "그녀도 여친",
    "kanojo okarishimasu": "여친, 빌리겠습니다",
    "kemono friends": "케모노 프렌즈",
    "keroro gunsou": "개구리 중사 케로로",
    "kidou keisatsu patlabor": "기동경찰 패트레이버",
    "kimi no koto ga dai dai dai dai daisuki na 100-nin no kanojo": "너를 너무너무너무너무너무 좋아하는 100명의 그녀",
    "kimi to idol precure": "너와 아이돌 프리큐어♪",
    "kin-iro loveriche": "금빛 러브리체",
    "koisuru asteroid": "사랑하는 소행성",
    "kono subarashii sekai ni shukufuku wo!": "이 멋진 세계에 축복을!",
    "kuro no kiseki (series)": "여의 궤적",
    "kuroko no basuke": "쿠로코의 농구",
    "kyoukaisenjou no horizon": "경계선상의 호라이즌",
    "limbus company": "림버스 컴퍼니",
    "lord of the mysteries": "신비의 제왕",
    "lovebrush chronicles": "시공의 여행자",
    "luo xiaohei zhanji": "나소흑전기",
    "lycoris recoil": "리코리스 리코일",
    "lyrical nanoha": "마법소녀 리리컬 나노하",
    "mahou shoujo madoka magica": "마법소녀 마도카☆마기카",
    "mahou shoujo no majo saiban": "마법소녀의 마녀재판",
    "marvel": "마블",
    "mashiroiro symphony": "마시로이로 심포니",
    "mawaru penguindrum": "돌아가는 펭귄드럼",
    "mega man (series)": "록맨",
    "minecraft youtube": "마인크래프트 유튜버",
    "miside": "미사이드",
    "mitsuboshi colors": "별 셋 컬러즈",
    "mono (afro)": "모노",
    "monogatari (series)": "이야기 시리즈",
    "mortal kombat (series)": "모탈 컴뱃",
    "murder drones": "머더 드론",
    "my little pony": "마이 리틀 포니",
    "nanatsu no taizai": "일곱 개의 대죄",
    "naruto (series)": "나루토",
    "nichijou": "일상",
    "nijisanji": "니지산지",
    "non non biyori": "논논비요리",
    "nyanko daisensou": "냥코 대전쟁",
    "ojamajo doremi": "꼬마마법사 레미",
    "onii-chan wa oshimai!": "오빠는 끝!",
    "ore twintail ni narimasu": "저, 트윈테일이 됩니다",
    "original": "오리지널",
    "otome domain": "오토메 도메인",
    "overwatch": "오버워치",
    "pixiv fantasia": "픽시브 판타지아",
    "powerpuff girls z": "나왔다! 파워퍼프걸Z",
    "precure": "프리큐어",
    "pretty series": "프리티 시리즈",
    "princess connect!": "프린세스 커넥트!",
    "pripara": "프리파라",
    "project kv": "프로젝트 KV",
    "project moon": "프로젝트 문",
    "project sekai": "프로젝트 세카이",
    "punishing: gray raven": "퍼니싱: 그레이 레이븐",
    "ragnarok online": "라그나로크 온라인",
    "rainbow six siege": "레인보우 식스 시즈",
    "re:zero kara hajimeru isekai seikatsu": "Re:제로부터 시작하는 이세계 생활",
    "ruri no houseki": "루리의 보석",
    "saki (manga)": "사키",
    "sakura no uta": "사쿠라의 시",
    "sanrio": "산리오",
    "sayonara zetsubou sensei": "안녕 절망선생",
    "science adventure": "과학 어드벤처",
    "scp foundation": "SCP 재단",
    "seishun buta yarou": "청춘 돼지 시리즈",
    "shenmue": "쉔무",
    "shikanoko nokonoko koshitantan": "사슴 아이 어슬렁어슬렁 호시탐탐",
    "shinrabanshou": "신라만상",
    "shoujo kageki revue starlight": "소녀☆가극 레뷰 스타라이트",
    "show by rock!!": "쇼 바이 락!!",
    "shugo chara!": "캐릭캐릭 체인지",
    "silent hill (series)": "사일런트 힐",
    "snowbreak: containment zone": "스노우 브레이크: 포비든 존",
    "sousou no frieren": "장송의 프리렌",
    "stella sora": "스텔라 소라",
    "steven universe": "스티븐 유니버스",
    "street fighter": "스트리트 파이터",
    "street fighter iv (series)": "스트리트 파이터 4",
    "subarashiki hibi": "멋진 나날들",
    "suisei no gargantia": "취성의 가르간티아",
    "super cub": "슈퍼 커브",
    "suzumiya haruhi no yuuutsu": "스즈미야 하루히의 우울",
    "sword art online": "소드 아트 온라인",
    "tales of (series)": "테일즈 오브 시리즈",
    "the hundred line -last defense academy-": "헌드레드 라인 -최종방위학원-",
    "the loud house": "링컨의 집은 시끌벅적해",
    "toaru majutsu no index": "어떤 마술의 금서목록",
    "tokyo 7th sisters": "도쿄 세븐스 시스터즈",
    "tokyo mew mew": "베리베리 뮤우뮤우",
    "touhou": "동방 프로젝트",
    "touken ranbu": "도검난무",
    "transformers": "트랜스포머",
    "trickcal": "트릭컬",
    "utdr (toby fox)": "언더테일·델타룬",
    "voiceroid": "보이스로이드",
    "wake up girls!": "웨이크 업, 걸즈!",
    "warship girls r": "전함소녀 R",
    "world dai star": "월드 다이 스타",
    "world witches series": "월드 위치스 시리즈",
    "wuthering waves": "명조: 워더링 웨이브",
    "xenoblade chronicles (series)": "제노블레이드 크로니클스",
    "yama no susume": "야마노스스메",
    "yoru no kurage wa oyogenai": "밤의 해파리는 헤엄칠 수 없어",
    "youkoso jitsuryoku shijou shugi no kyoushitsu e": "어서 오세요 실력지상주의 교실에",
    "zenless zone zero": "젠레스 존 제로",
}
REVIEW_REASONS: dict[str, str] = {
    "girls' frontline": "사용자 지정. 반복 꺾쇠라도 실제 작품명인 소녀전선을 검수해 채택; 소전은 약칭.",
    "original": "사용자 지정 일반어 오리지널. 다른 태그의 분류어로도 등장하므로 명시적으로 선택.",
    "lord of the mysteries": "사전의 심해의 군주를 채택하지 않음. 한국어 유통 제목 신비의 제왕 확인.",
    "utdr (toby fox)": "언더테일 단독 작품이 아니라 언더테일과 델타룬의 묶음.",
    "hai to gensou no grimgar": "사전의 아랍 문자 혼입 오자 수정.",
    "hibi wa sugiredo meshi umashi": "제목 내부 쉼표를 동의어 구분자로 잘라내지 않음.",
    "kanojo okarishimasu": "제목 내부 쉼표를 동의어 구분자로 잘라내지 않음.",
    "ore twintail ni narimasu": "제목 내부 쉼표를 동의어 구분자로 잘라내지 않음.",
    "wake up girls!": "제목 내부 쉼표를 동의어 구분자로 잘라내지 않음.",
    "pretty series": "프리파라 단독 제목으로 좁히지 않고 프리티 시리즈 범위를 보존.",
    "seishun buta yarou": "시리즈를 첫 권 부제인 바니걸 선배의 꿈을 꾸지 않는다로 좁히지 않음.",
    "yama no susume": "사전의 무관한 동의어 여기는 잘나가는 파출소를 제외.",
}
REVIEW_LINKS: dict[str, str] = {
    "2.5 jigen no ririsa": "https://member.kpa21.or.kr/wp-content/uploads/sites/2/2020/12/2020%EB%85%84-11%EC%9B%94%EC%9D%98-%EC%8B%A0%EA%B0%84.pdf",
    "ai the somnium files": "https://gfn.co.kr/ko/games/ai-the-somnium-files-nirvana-initiative/",
    "kin-iro loveriche": "https://namu.moe/w/금빛%20러브리체",
    "dokyuu hentai hxeros": "https://www.namu.moe/w/초급편대%20에그제로스",
    "elf-san wa yaserarenai.": "https://www.tving.com/contents/P001760958",
    "hapymaher": "https://www.gamemeca.com/view.php?gid=1110542",
    "hitoribocchi no marumaru seikatsu": "https://m.namu.moe/w/히토리%20봇치의%20○○생활",
    "lord of the mysteries": "https://m01.mrblue.com/novel/detail/KOCM0054",
    "mahou shoujo no majo saiban": "https://www.inven.co.kr/webzine/news/?iskin=78&news=320741",
    "mitsuboshi colors": "https://series.naver.com/comic/detail.series?productNo=3687966",
    "ruri no houseki": "https://series.naver.com/comic/detail.series?productNo=14347751",
    "stella sora": "https://play.google.com/store/apps/details?id=com.YoStarKR.StellaSora",
    "the hundred line -last defense academy-": "https://www.arcsystemworks.asia/bbs/board.php?bo_table=notice&wr_id=906",
    "trickcal": "https://tr.triple-lab.com/",
}

# Unconfirmed Korean usage / dubious dictionary literal translations. Do not
# invent transliterations merely to make the coverage number larger.
for _group in (
    "a.i. voice", "akb0048", "bishoujo (game)", "boku to koi suru ponkotsu akuma.",
    "chromashift", "ef (visual novel)", "everlasting summer", "gakkou de seishun!",
    "kouyoku senki exs-tia", "mahou reiki magisphere", "moe! ninja girls",
    "nukigee mitai na shima ni sunderu watashi wa dou surya ii desu ka?",
    "one - kagayaku kisetsu e", "project tokyo dolls", "pronant symphony",
    "shadow slave", "shoujo ramune", "tatakau ni atai suru", "vallure",
    "vampire (game)", "vedal ai", "vee (vtuber)", "vinesauce", "vyugen", "yuuwaku",
):
    REVIEWED_NAMES[_group] = None
    REVIEW_REASONS[_group] = "정식·통용 한국어 이름을 확정하지 못함. 사전의 분류어·직역·다른 고유명사를 자동 채택하지 않음."
REVIEW_REASONS["chromashift"] = "v2 후보 아이돌 코프는 다른 그룹 키에도 있음. 개명/그룹 동일성과 한국어 표기를 확정하지 못함."
REVIEW_REASONS["vee (vtuber)"] = "사전의 소니 뮤직은 운영사명. 그룹 VEE의 한국어 표기 미확정."
REVIEW_REASONS["vampire (game)"] = "괄호가 붙은 별도 그룹. darkstalkers와 임의 병합하지 않음; 한국어 표기 미확정."

# 추가 소속(data/character_group_membership.json)으로 3명이 된 새 그룹(2026-10-22 · 한 캐릭터가 여러 그룹).
# 사전 후보가 분류어 · 상위 시리즈명(예: '나루토시리즈' · '축구' · '수집형 RPG')이거나 표기가 들쭉날쭉한 것만 고쳤다.
# 시리즈 번호는 아라비아 숫자, 기존 그룹명과 같은 표기(러브라이브 · 페이트/…)를 따른다.
MEMBERSHIP_REVIEWED_NAMES: dict[str, str | None] = {
    ".hack//g.u.": "닷핵 G.U.",
    "aikatsu friends!": "아이카츠 프렌즈!",
    "aikatsu stars!": "아이카츠 스타즈!",
    "ar tonelico ii": "아르토네리코 2",
    "bang dream! it's mygo!!!!!": "뱅드림! It's MyGO!!!!!",
    "boruto: naruto next generations": "보루토: 나루토 넥스트 제너레이션즈",
    "bravely second: end layer": "브레이블리 세컨드 엔드 레이어",
    "cinderella girls gekijou": "신데렐라 걸즈 극장",
    "code geass: lost stories": "코드 기어스: 로스트 스토리즈",
    "dead or alive xtreme venus vacation": "데드 오어 얼라이브 익스트림 비너스 버케이션",
    "devil may cry 5": "데빌 메이 크라이 5",
    "digimon liberator": "디지몬 리버레이터",
    "digimon story: cyber sleuth": "디지몬 스토리 사이버 슬루스",
    "drag-on dragoon 3": "드래그 온 드라군 3",
    "dragon musume ni naritakunai!": None,
    "dragon quest iv": "드래곤 퀘스트 4",
    "dragon quest vii": "드래곤 퀘스트 7",
    "dream c club": "드림 C 클럽",
    "duel masters play's": "듀얼 마스터즈 플레이스",
    "elden ring: shadow of the erdtree": "엘든 링 황금 나무의 그림자",
    "equestria girls: rainbow rocks": "마이 리틀 포니: 이퀘스트리아 걸스 레인보우 록스",
    "eureka seven": "교향시편 유레카 세븐",
    "fate/apocrypha": "페이트/아포크리파",
    "fate/extra": "페이트/엑스트라",
    "fate/extra ccc": "페이트/엑스트라 CCC",
    "fate/hollow ataraxia": "페이트/할로우 아타락시아",
    "fate/prototype: fragments of blue and silver": "페이트/프로토타입 창은의 프래그먼츠",
    "fate/samurai remnant": "페이트/사무라이 렘넌트",
    "fate/stay night": "페이트/스테이 나이트",
    "final fantasy ix": "파이널 판타지 9",
    "final fantasy vii remake": "파이널 판타지 7 리메이크",
    "final fantasy xv": "파이널 판타지 15",
    "final fantasy xvi": "파이널 판타지 16",
    "fire emblem fates": "파이어 엠블렘 if",
    "fire emblem: genealogy of the holy war": "파이어 엠블렘 성전의 계보",
    "fire emblem: new mystery of the emblem": "파이어 엠블렘 신 문장의 수수께끼",
    "fire emblem: the blazing blade": "파이어 엠블렘 열화의 검",
    "girls und panzer ribbon no musha": "걸즈 앤 판처 리본의 무사",
    "god eater 2: rage burst": "갓 이터 2 레이지 버스트",
    "gundam 00": "기동전사 건담 00",
    "gundam build fighters try": "건담 빌드 파이터즈 트라이",
    "gundam gquuuuuux": "기동전사 건담 지쿠악스",
    "gundam seed destiny": "기동전사 건담 SEED DESTINY",
    "gundam seed freedom": "기동전사 건담 SEED FREEDOM",
    "hachigatsu no cinderella nine": "8월의 신데렐라 나인",
    "hades 2": "하데스 2",
    "hollow knight: silksong": "할로우 나이트: 실크송",
    "hololive dev is": "홀로라이브 DEV_IS",
    "hololive english": "홀로라이브 English",
    "holostars english": "홀로스타즈 English",
    "idol time pripara": "아이돌 타임 프리파라",
    "idolmaster cinderella girls": "아이돌마스터 신데렐라 걸즈",
    "idolmaster cinderella girls starlight stage": "아이돌마스터 신데렐라 걸즈 스타라이트 스테이지",
    "inazuma eleven go": "이나즈마 일레븐 GO",
    "kage no jitsuryokusha ni naritakute! master of garden": "어둠의 실력자가 되고 싶어서! 마스터 오브 가든",
    "kai no kiseki": "영웅전설 계의 궤적",
    "kai-ri-sei million arthur": "괴리성 밀리언 아서",
    "kaitou tenshi twin angel": "괴도천사 트윈엔젤",
    "link! like! love live!": "링크! 라이크! 러브라이브!",
    "love live! nijigasaki high school idol club": "러브라이브! 니지가사키 학원 스쿨 아이돌 동호회",
    "love live! school idol project": "러브라이브! 스쿨 아이돌 프로젝트",
    "love live! sunshine!!": "러브라이브! 선샤인!!",
    "love live! superstar!!": "러브라이브! 슈퍼스타!!",
    "macross delta": "마크로스 델타",
    "mahou shoujo ikusei keikaku unmarked": "마법소녀 육성계획 unmarked",
    "mahou shoujo lyrical nanoha detonation": "마법소녀 리리컬 나노하 Detonation",
    "mahou shoujo madoka magica (anime)": "마법소녀 마도카☆마기카 (애니메이션)",
    "mahou shoujo madoka magica: hangyaku no monogatari": "마법소녀 마도카☆마기카 반역의 이야기",
    "mega man legends": "록맨 DASH",
    "mega man legends (series)": "록맨 DASH 시리즈",
    "mega man zx": "록맨 ZX",
    "monster hunter: world": "몬스터 헌터: 월드",
    "mortal kombat 9": "모탈 컴뱃 9",
    "nier:automata": "니어 오토마타",
    "nijiura maids": None,
    "osomatsu (series)": "오소마츠 시리즈",
    "persona 3": "페르소나 3",
    "pokemon (anime)": "포켓몬스터 (애니메이션)",
    "pokemon pokopia": "포켓몬 포코피아",
    "portrait of exotic girls": None,
    "rune factory: guardians of azuma": None,
    "saki achiga-hen": "사키 아치가편",
    "sakura taisen ii": "사쿠라 대전 2",
    "scott pilgrim takes off": "스콧 필그림 테이크 오프",
    "senran kagura estival versus": "섬란 카구라 ESTIVAL VERSUS",
    "senran kagura new wave": "섬란 카구라 NEW WAVE",
    "shin jigen game neptune vii": "신차원게임 넵튠 VII",
    "shin megami tensei v: vengeance": "진 여신전생 5 벤전스",
    "shining resonance": "샤이닝 레조넌스",
    "sonic the hedgehog (idw)": "소닉 더 헤지혹 (IDW)",
    "spider-man: into the spider-verse": "스파이더맨: 뉴 유니버스",
    "splatoon 2": "스플래툰 2",
    "steins;gate 0": "슈타인즈 게이트 제로",
    "street fighter 6": "스트리트 파이터 6",
    "summon night 3": "서몬나이트 3",
    "sword art online: alicization": "소드 아트 온라인 앨리시제이션",
    "tales of arise": "테일즈 오브 어라이즈",
    "tales of graces": "테일즈 오브 그레이스",
    "the king of fighters xv": "더 킹 오브 파이터즈 XV",
    "the legend of zelda: breath of the wild": "젤다의 전설 야생의 숨결",
    "thor (marvel) (series)": "토르",
    "to love-ru darkness": "투 러브 트러블 다크니스",
    "toaru majutsu no index: old testament": "어떤 마술의 금서목록 구약",
    "tokyo mirage sessions fe": "환영이문록 #FE",
    "waccha primagi!": "왓챠 프리마지!",
    "vspo! en": "브이스포! EN",
    "witches of africa": None,
    "xenoblade chronicles 2": "제노블레이드 크로니클스 2",
    "xenoblade chronicles 3: future redeemed": "제노블레이드 크로니클스 3 새로운 미래",
    "zero escape: toki no dilemma": None,
}
for _group, _name in MEMBERSHIP_REVIEWED_NAMES.items():
    REVIEWED_NAMES.setdefault(_group, _name)
    if _name is None:
        REVIEW_REASONS.setdefault(_group, "사전 후보가 분류어 · 상위 시리즈명뿐이고 정식 한국어 표기를 확정하지 못함.")


def normalize_tag(value: str) -> str:
    return " ".join(value.replace("_", " ").replace(r"\(", "(")
                    .replace(r"\)", ")").split()).casefold()


def is_category(word: str) -> bool:
    compact = word.replace(" ", "")
    return compact in CATEGORY_WORDS or compact.endswith(("그룹", "게임시리즈"))


def prepare_source(rows):
    """Count angle labels over the WHOLE source, including out-of-scope tags."""
    index = defaultdict(list)
    labels = defaultdict(set)
    for tag, keywords in rows:
        if not isinstance(tag, str) or not isinstance(keywords, str):
            continue
        tag = normalize_tag(tag)
        if keywords not in index[tag]:
            index[tag].append(keywords)
        for label in ANGLE.findall(keywords):
            labels[label.strip()].add(tag)
    return dict(index), {label: len(tags) for label, tags in labels.items()}


def keyword_names(keywords: str, label_counts: dict[str, int]) -> list[str]:
    result = []
    # A comma inside <a title, with punctuation> is not a separator.
    for token in re.findall(r"(?:<[^>]*>|[^,<>])+", keywords):
        token = token.strip()
        if not token:
            continue
        angle = ANGLE.fullmatch(token)
        if angle:
            token = angle[1].strip()
            if label_counts.get(token, 0) > 1 or is_category(token):
                continue
        elif ANGLE.search(token):
            # Prefix syntax such as <primary>:명일방주.
            token = ANGLE.sub("", token).lstrip(" :：")
        token = re.sub(r"^(?:한글명|작품명)\s*[:：]\s*", "", token)
        token = token.strip().strip("[]").strip()
        if (not HANGUL.search(token) or is_category(token)
                or token in PLAIN_CATEGORIES or re.match(r"^(?:약칭|감독|제작사)\s*:", token)):
            continue
        if token not in result:
            result.append(token)
    return result


def group_sizes(analysis, membership=None):
    """그룹 -> 인원. 추가 소속(`data/character_group_membership.json` 의 extra)도 센다 - 추가 소속만으로
    3명이 되는 새 그룹(예: steins;gate 0)도 이름을 받는다(사용자 결정 2026-10-22: 한 캐릭터가 여러 그룹)."""
    sizes = Counter({group: len(characters) for group, characters in analysis.items()
                     if isinstance(characters, dict)})
    extra = (membership or {}).get("extra") if isinstance(membership, dict) else None
    for groups in (extra or {}).values():
        for group in groups or []:
            sizes[group] += 1
    return sizes


def build_names(analysis, sources, reviewed=None, membership=None):
    prepared = {source: prepare_source(rows) for source, rows in sources.items()}
    reviewed = REVIEWED_NAMES if reviewed is None else reviewed
    names, records = {}, {}
    sizes = group_sizes(analysis, membership)
    for group, size in sorted(sizes.items()):
        if size < MIN_CHARACTERS:
            continue
        key = normalize_tag(group)
        # A missing suffix may be resolved, but an explicit disambiguator is
        # never stripped (e.g. vampire (game) is not automatically darkstalkers).
        lookup = (key, key + " (series)") if not key.endswith(" (series)") else (key,)
        candidates = []
        reviewed_sources = []
        for source in SOURCE_ORDER:
            index, counts = prepared.get(source, ({}, {}))
            matched = next((tag for tag in lookup if tag in index), None)
            if matched is None:
                continue
            for keywords in index[matched]:
                for name in keyword_names(keywords, counts):
                    candidates.append((name, source, matched))
                # An explicit reviewed choice may restore a genuine title whose
                # angle label was shared with other tags (e.g. 소녀전선).
                if group in reviewed and reviewed[group]:
                    raw_tokens = [t.strip().strip("<>[]").strip()
                                  for t in re.findall(r"(?:<[^>]*>|[^,<>])+", keywords)]
                    if reviewed[group] in raw_tokens:
                        reviewed_sources.append(source)
        chosen = candidates[0][0] if candidates else None
        if group in reviewed:
            chosen = reviewed[group]
        source = (reviewed_sources[0] if reviewed_sources else
                  next((src for name, src, _ in candidates if name == chosen), "직접")) if chosen else ""
        if chosen:
            names[group] = chosen
        records[group] = {"count": size, "name": chosen or "", "source": source,
                          "candidates": candidates,
                          "reason": REVIEW_REASONS.get(group, "한국어 이름 미확정" if not chosen else
                              "대표 이름 선택 / 통용명·띄어쓰기 보정" if group in reviewed else ""),
                          "link": REVIEW_LINKS.get(group, "")}
    return names, records, {s: counts for s, (_, counts) in prepared.items()}


def read_sources(interactive: Path, parquet: Path, v2: Path):
    import pandas as pd

    data = json.loads(interactive.read_text(encoding="utf-8"))
    sources = {"dict": [(k, v.get("keywords_kr", "")) for k, v in data.items() if isinstance(v, dict)]}
    frame = pd.read_parquet(parquet, columns=["tag", "keywords"])
    sources["kr_tags"] = list(frame.itertuples(index=False, name=None))
    sources["v2"] = []
    with v2.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.reader(handle):
            if len(row) >= 4 and "키워드:" in row[3]:
                keywords = row[3].split("키워드:", 1)[1].split("|", 1)[0].strip()
                sources["v2"].append((row[0], keywords))
    return sources


def write_preserving_newlines(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    newline = "\r\n" if path.exists() and b"\r\n" in path.read_bytes() else "\n"
    path.write_bytes(text.replace("\n", newline).encode("utf-8"))


def write_review(path, records, counts, inputs):
    def cell(text):
        return str(text).replace("|", r"\|").replace("\n", " ")

    filled = Counter(r["source"] for r in records.values() if r["name"])
    lines = ["# Characters 그룹 한글명 검수 — 2026-10-22", "",
             f"대상: 캐릭터 {MIN_CHARACTERS}명 이상 {len(records)}개. 채움 {sum(filled.values())}개. "
             f"보류 {len(records) - sum(filled.values())}개. 2명 이하 그룹은 제외.", "",
             "출처별: " + " · ".join(f"{s} {filled[s]}" for s in (*SOURCE_ORDER, "직접")), "",
             "사전은 후보의 근거이며 정식 한국어판 제목을 보증하지 않는다. 출처는 선택한 이름의 근거다. "
             f"띄어쓰기·정식명 보정 및 직접 결정은 `직접`으로 표시했다. 아래 표는 {len(records)}개 전체를 검수할 수 있는 결과이며, "
             "모든 항목을 외부 공식 출처와 대조했다는 뜻은 아니다.", "",
             "빌더: `tools/build_character_group_ko.py` (런타임 import 없음). "
             "같은 이름이 여러 사전에 있으면 dict → kr_tags → v2 순으로 출처를 선택한다.", "",
             "## 입력", ""]
    lines += [f"- `{p}`" for p in inputs]
    lines += ["", "## 분류어 판정", "",
              "각 사전 전체에서 `<…>`를 공유하는 서로 다른 정규화 태그 수를 센다. "
              "2개 이상이면 자동 대표어로 사용하지 않고 뒤의 한국어 후보를 찾는다. "
              "유일한 분류어도 장르/유형 목록으로 제외한다. 실제 작품명이 반복되어 제외되는 경우는 명시적으로 검수한다.", "",
              "| 사전 | 꺾쇠 내용 | 공유 태그 수 |", "|---|---|---:|"]
    for source in SOURCE_ORDER:
        for label in ("저작권", "작품", "시리즈", "소녀전선"):
            if label in counts.get(source, {}):
                lines.append(f"| {source} | {label} | {counts[source][label]} |")
    lines += ["", "## 전체 결과", "", "| 그룹 | 캐릭터 수 | 한글 | 출처 |", "|---|---:|---|---|"]
    for group, row in records.items():
        lines.append(f"| {cell(group)} | {row['count']} | {cell(row['name']) or '보류'} | {row['source'] or '—'} |")
    lines += ["", "## 보류 목록", "", "| 그룹 | 캐릭터 수 | 사유 |", "|---|---:|---|"]
    for group, row in records.items():
        if not row["name"]:
            lines.append(f"| {cell(group)} | {row['count']} | {cell(row['reason'])} |")
    lines += ["", "## 명시적 검수 및 외부 확인", "", "| 그룹 | 결정 | 근거 / 사유 |", "|---|---|---|"]
    for group, row in records.items():
        if group in REVIEWED_NAMES or row["link"]:
            detail = row["reason"]
            if row["link"]:
                detail += f" [확인 출처]({row['link']})"
            lines.append(f"| {cell(group)} | {cell(row['name']) or '보류'} | {cell(detail)} |")
    write_preserving_newlines(path, "\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path, default=ROOT / "data/character_analysis.json")
    parser.add_argument("--interactive", type=Path, default=ROOT / "data/interactive_tags.json")
    parser.add_argument("--kr-tags", type=Path, default=ROOT / "data/KR_tags.parquet")
    parser.add_argument("--v2", type=Path, default=ROOT.parent / "KR_danbooru_tags_with_description-20260907-v2.csv")
    parser.add_argument("--membership", type=Path, default=ROOT / "data/character_group_membership.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/character_group_ko.json")
    parser.add_argument("--review", type=Path, default=ROOT / "docs/character_group_ko_review_2026_10_22.md")
    args = parser.parse_args()
    analysis = json.loads(args.analysis.read_text(encoding="utf-8"))
    sources = read_sources(args.interactive, args.kr_tags, args.v2)
    membership = json.loads(args.membership.read_text(encoding="utf-8")) if args.membership.exists() else None
    names, records, counts = build_names(analysis, sources, membership=membership)
    payload = {"note": ["캐릭터 3명 이상 그룹만 수록. 미확정 이름과 2명 이하 그룹은 제외.",
                        "사전 후보와 직접 검수한 한국어 이름. 검수표: docs/character_group_ko_review_2026_10_22.md",
                        "개발 도구 tools/build_character_group_ko.py로 생성. 런타임은 이 JSON만 읽음."],
               "names": names}
    write_preserving_newlines(args.output, json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    write_review(args.review, records, counts, (args.analysis, args.interactive, args.kr_tags, args.v2))
    print(json.dumps({"filled": len(names), "eligible": len(records),
                      "sources": dict(Counter(r["source"] for r in records.values() if r["name"])),
                      "held": [g for g, r in records.items() if not r["name"]]}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
