"""Display groups, not safety/rating filters. Never removes or hides a tag.

The old NSFW/category labels mix acts, anatomy and exposure. Resolve specific
tag semantics first; do not treat NSFW, genitals, nudity or a suggestive pose
as evidence of a sexual act. This module is an offline exporter input only.
"""
import re


def words(text):
    return frozenset(t.strip() for t in text.split("|") if t.strip())


# Reviewed exceptions to otherwise ambiguous English words/category labels.
ACTS = words("""
anal | vaginal | oral | missionary | amazon position | mating press |
prone bone | suspended congress | reverse suspended congress | upright straddle |
reverse upright straddle | spitroast | reverse spitroast | male spitroast |
upright 69 | reverse amazon position | anvil position | rusty trombone |
just the tip | pull out | fisting | sounding | knotting | frottage | grinding |
cooperative grinding | humping | dry humping | pillow humping | table humping |
bestiality | orgy | chikan | molestation | sleep molestation | foreplay |
clitoral stimulation | clitoral stimulation through clothing | clitoris tweak |
prostate milking | g-spot stimulation | cunnilingus | anilingus | autofacial |
bukkake | gokkun | felching | irrumatio | tribadism | pegging | deepthroat |
naizuri | caressing testicles | squeezing testicles | testicle grab |
biting nipple | breast biting | breast fondle | breast sucking through clothes |
mutual breast sucking | sucking own breasts | licking own nipple |
nipple biting | nipple flick | nipple stimulation | nipple tweak | nipple pull |
teasing nipples | tweaking own nipple | nipple rub | clitoris pull |
breast sucking | double breast sucking | self breast sucking |
sucking both nipples | sucking male nipple | licking nipple | licking penis |
licking testicle | testicle sucking | kissing penis | licking breast |
grabbing another's penis | penis grab | hand on another's penis |
hand on own penis | hands on penis | hand in own panties |
asymmetrical docking | symmetrical docking | hug and suck |
all the way through | after anal | after vaginal | imminent anal |
imminent vaginal | double anal | multiple anal | triple anal |
double vaginal | multiple vaginal | oral sandwich | oral invitation |
egg implantation | female fertilization | artificial insemination |
penis on pussy | penis on tongue | penis in eye | tail in ass |
dildo riding | vibrator under panties | public vibrator | licking dildo |
breast pull | slapping breasts | breast smother | grabbed breast over shoulder |
autoarousal | ass worship | zoophilia | 69 | dildo under clothes |
electrostimulation | drinking from condom | public use | bulge to face
""")

# These terms refer to acts (or their explicit context), with whole-token
# matching: cum must not match cummerbund/cumulonimbus, sex not mixed-sex.
ACT_PATTERN = re.compile(
    r"(?:^| )(?:sex|sexual intercourse|masturbat(?:ion|ing|e)|"
    r"ejaculat(?:ion|ing|e)|orgasm|"
    r"fellatio|autofellatio|cunnilingus|autocunnilingus|anilingus|"
    r"paizuri|autopaizuri|naizuri|tribadism|irrumatio|deepthroat|"
    r"fingering|fisting|gangbang|threesome|foursome|fivesome|rape|"
    r"doggystyle|(?:reverse )?cowgirl position|"
    r"(?:hand|foot|butt|thigh|blow|boob|breast|tit|tail|tentacle|"
    r"tongue|hair|armpit|belly|glans|shoe|boot|sock|sleeve|face|"
    r"pussy|pec|talon)job)(?: |$)"
)
FLUID_PATTERN = re.compile(r"(?:^| )(?:cum|cumdrip|cumshot|precum|creampie|pussy juice)(?: |$)")
# Insertion/penetration alone also covers wounds, body horror and comedy.
# Only reviewed sexual uses may cross groups. Unknown compounds stay in their
# source group; they must not acquire a sexual meaning from one English word.
PENETRATION_ACTS = words("""
accidental penetration | after double penetration | after insertion |
after tail insertion | anal object insertion | animal insertion |
ass-to-ass penetration | assisted object insertion | autopenetration |
ball insertion | cable insertion | cervical penetration | clear insertion |
clitoral hood insertion | clitoral penetration | covered penetration |
deep anal object insertion | deep penetration | dilation insertion |
double insertion | double penetration | fallopian tube insertion |
food insertion | foot insertion | foreskin insertion | guided penetration |
imminent double penetration | imminent object insertion | imminent penetration |
imminent urethral insertion | implied after insertion | implied double penetration |
implied object insertion | implied penetration | implied urethral insertion |
instrument insertion | large insertion | male penetrated | multiple insertions |
multiple penetration | mutual penetration | nipple object insertion |
nipple penetration | nipple penetration invitation | object insertion |
object insertion from behind | penetration after ejaculation |
penetration through barrier | penetration through clothes |
penetration while penetrated | poke ball insertion | prepuce insertion |
quadruple penetration | reverse nipple object insertion | reverse nipple penetration |
reverse penetration | shared object insertion | standing double penetration |
tail insertion | triple insertion | triple penetration | unusual insertion |
urethral insertion | urethral penetration | vaginal object insertion
""")

# A word in a title, meme, diagram or educational tag is not the depicted act.
NON_ACTS = words("""
sex hair | sex ed | sex education | sex machine | sex toy | sex toys |
holding sex toy | too many sex toys | wireless sex toy controller |
rape face | fingering gesture | cunnilingus gesture | fellatio gesture |
handjob gesture | handjob gesture (not ok) | paizuri gesture |
penetration gesture | masturbation day | navel fingering | ear insertion |
mouth insertion | brain injection | blowjob (drink) | sex on the beach (drink) |
sex pistols (stand) (cosplay) | sex reassignment surgery | sex shop |
international sex workers' day | i don't need sex because... |
cuddling to sex 2koma (tcn tancha) | gun fellatio (shingeki no kyojin) |
chainsaw man's handjob scene | paizuri day | wound fingering |
nasal object insertion | nose insertion | fingering gesture (not ok)
""")

# Simple exposure/anatomy: keep visible under body/clothing/action.
BODY = words("""
anus | nipples | penis | pussy | testicles | pubic hair | erection |
animal penis | dog penis | clitoral hood | cervix | ovum | phimosis | urethra |
no pussy | sparse pubic hair | female pubic hair | male pubic hair |
black pubic hair | stray pubic hair | veiny breasts | underpec |
absurdly fat mons | penis head | penis nipples | vagina dentata |
disembodied breast | disembodied penis | mole on pussy | tampon string |
animal genitalia on humanoid | between testicles | blood from vagina |
blue anus | blue penis | blue pussy | cat penis | censored anus | colored anus |
colored penis | colored saliva | curved penis | deformed anus | dolphin penis |
green penis | green pussy | hair on penis | horse pussy | large clitoris |
mechanical penis | mechanical pussy | misplaced genitals | mole on testicles |
no genitals | non-pubic inmon | ovum with heart | penis bow | penis focus |
penis tattoo | penis to navel | pig penis | purple penis | purple pussy |
red penis | smelly penis | tail anus | testicle hair | testicle tattoo |
triangular anus | cleft anus | extra pussies | null bulge | sagging testicles |
penis chart | penis face | penis out of frame | tail pussy | futa without balls |
male futanari | implied futanari | intravaginal futanari | twitching penis |
bouncing flat chest | floating breasts | breasts apart | breasts on glass |
breast drop | rectal prolapse | uterine prolapse | vaginal prolapse |
anal prolapse | saliva | saliva on breasts | breast milk in container |
excessive lactation | implied breast milk | implied lactation | male lactation |
menstrual blood | pee puddle | pee stain | anal fluid | hickey |
bite mark on breast | breast piercing | nipple bells | dydoe | lorum piercing |
mismatched nipple piercing | lipstick mark on testicles | lipstick ring |
lipstick mark on pussy | blood on pussy | testicles touching |
penis and testicles touching | twisted breasts
""")
EXPOSURE = words("""
nude | completely nude | implied nudity | nude cover | bottomless | topless |
topless female | topless male | bare pectorals | breasts out | one breast out |
breast slip | areola slip | ass visible through thighs | pectoral cleavage |
penis peek | pussy peek | abs peek | bulge peek | labia slip | perineum peek |
ass peek | testicle peek | clitoris slip | male underwear peek |
clothes between exposed breasts | pubic tattoo visible through clothes |
naked towel | naked boots | naked dress | naked gloves | naked poncho |
naked tape | naked belt | naked ascot | nearly naked shirt |
clothed female nude male | clothed male nude female | cameltoe |
covered navel | covered nipples | no bra | no panties | see-through clothes |
sideboob | underboob | skindentation | zettai ryouiki | pantyshot |
implied pantyshot | extended downblouse | downblouse | leotard peek |
through panties | through clothes | up sleeve | crotchless shorts |
clitoris cutout | trefoil | bikini around one leg | buruma around one leg |
panties under shorts | panty bulge | bandaids on nipples | bandaid on pussy |
tape on nipples | tape on pussy | maebari | heart maebari | fuck-me pasties |
fuck-me clothes | necktie between breasts | penis in panties | penis in glove |
penis in pantyhose | penis in swimsuit | penis in thighhigh | penis under mask |
panties on penis | sock on penis | convenient tail | zenra
""")
EXPOSURE_ACTIONS = words("""
clothing aside | clothes lift | pants pull | panty pull | pantyhose pull |
panty spread | bikini top lift | buruma lift | leotard aside | swimsuit aside |
bikini bottom aside | panties aside | loincloth aside | skirt aside |
buruma aside | panty lift | thong aside | sports bra pull |
covering another's nipples | covering anus | presenting ass | presenting pussy |
presenting own pussy | presenting own anus | presenting own ass |
presenting own breasts | presenting penis | presenting anus | presenting |
presenting another | half-spread pussy | spread pussy under clothes |
spreading another's pussy | spreading own pussy | spread anus |
spread anus under clothes | spreading own anus | spreading another's anus |
spreading own ass | spreading another's ass | spread ass | kupaa |
assisted exposure | mooning | streaking | stealth flashing | strip mahjong |
strip poker | reverse strip game | hand under clothes | holding own breasts
""")
POSES = words("""
bent over | folded | m legs | mounting | girl on top | boy on top |
scissorhold | all fours | straddling | spread legs | on back | lying
""")
SEXUAL_OBJECTS = words("""
dragon dildo | dildo reveal | glory wall | condom in mouth | condom on nipples |
padlocked chastity cage | revealing chastity cage | stuffed gag
""")

# Second-pass decisions based on definitions, not the original NSFW labels.
# Keep exact exceptions ahead of the first-pass word lists so rebuilds preserve
# the reviewed distinction between an act, contact, a trace, and a visual motif.
REVIEWED_SPECIAL_CASES = {
    "asymmetrical docking": ("action", "접촉·상호작용"),
    "symmetrical docking": ("action", "접촉·상호작용"),
    "breast pull": ("action", "손·팔 동작"),
    "breast smother": ("action", "접촉·상호작용"),
    "hand in own panties": ("action", "옷 다루기"),
    "hand on another's penis": ("action", "접촉·상호작용"),
    "hand on own penis": ("action", "손·팔 동작"),
    "hands on penis": ("action", "손·팔 동작"),
    "navel insertion": ("action", "사물 사용"),
    "comedic object insertion": ("action", "사물 사용"),
    "twisted breasts": ("action", "손·팔 동작"),
    "scissorhold": ("action", "접촉·상호작용"),
    "mounting": ("adult", "행위·체위"),
    "through clothes": ("adult", "행위·체위"),
    "through panties": ("adult", "행위·체위"),
    "penis in glove": ("adult", "행위·체위"),
    "penis under mask": ("adult", "행위·체위"),
    "breast piercing": ("adult", "행위·체위"),
    "lipstick ring": ("adult", "행위·체위"),
    "lipstick mark on pussy": ("adult", "행위·체위"),
    "lipstick mark on testicles": ("adult", "행위·체위"),
    "penis and testicles touching": ("adult", "행위·체위"),
    "penis to navel": ("adult", "행위·체위"),
    "testicles touching": ("adult", "행위·체위"),
    "autoarousal": ("adult", "체액"),
    "fellatio mask": ("adult", "용품"),
    "orgasm beam": ("adult", "용품"),
    "breast drop": ("clothing", "착의·노출 상태"),
    "underpec": ("clothing", "착의·노출 상태"),
    "pee stain": ("clothing", "착의·노출 상태"),
    "nipple bells": ("clothing", "장신구·소품"),
    "penis bow": ("clothing", "장신구·소품"),
    "penis focus": ("cast", "구도·강조"),
    "penis out of frame": ("cast", "구도·강조"),
    "ass visible through thighs": ("cast", "구도·강조"),
    "penis chart": ("meta", "구성·형식"),
    "kupaa": ("meta", "문자·기호"),
    "convenient tail": ("meta", "품질·제작"),
    "zenra": ("situation", "설정·능력"),
    "pectoral cleavage": ("body", "체형·부위"),
    "penis face": ("body", "피부·표식"),
}

# First-pass moves whose definitions could not be established. Preserve the
# ORIGINAL group (not an inferred sexual group), keep the entry and mark its
# subcategory pending. These are searchable tags, never candidate exclusions.
PENDING_GROUP_REVIEWS = words("""
armpit insertion | bamboo insertion | eye penetration | gill insertion |
high heels insertion | imminent insertion | navel penetration | neck penetration |
nose penetration | pelvic penetration | penetration by water |
penetration through body | rod insertion | wound penetration |
orgasm count | sex counter | penis in pantyhose | penis in thighhigh
""")
BODY_FLUIDS = words("""
anal fluid | blood from vagina | blood on pussy | breast milk in container |
colored saliva | excessive lactation | implied breast milk | implied lactation |
male lactation | menstrual blood | pee puddle | saliva | saliva on breasts
""")


def resolve(tag, row):
    """Return (group, semantic subcategory input, rule), or no override.

    Exposure exceptions are checked first because the source labels themselves
    are unreliable. Do not bulk-move a category called 성행위/NSFW/노출.
    """
    name = " ".join(tag.replace("_", " ").casefold().split())
    if name in APPROVED_AUDIT_OVERRIDES:
        group, sub = APPROVED_AUDIT_OVERRIDES[name]
        return group, sub, "approved-audit-20261006"
    if name in PENDING_GROUP_REVIEWS:
        return row["group"], "__pending__", "definition-pending"
    if name in REVIEWED_SPECIAL_CASES:
        group, sub = REVIEWED_SPECIAL_CASES[name]
        return group, sub, "definition-reviewed"
    if name in BODY_FLUIDS:
        return "body", "체액·분비", "nonsexual-body-fluid"
    if name in EXPOSURE_ACTIONS:
        return "action", "옷 다루기" if re.search(r"clothes|pant|bikini|buruma|leotard|swimsuit|skirt|bra|thong|loincloth", name) else "자세·이동", "exposure-action"
    if name in EXPOSURE:
        return "clothing", "착의·노출 상태", "exposure-only"
    if name in BODY:
        sub = "피부·표식" if re.search(r"hair|mole|tattoo|mark|piercing", name) else "체형·부위"
        return "body", sub, "anatomy-only"
    if name in POSES:
        return "action", "자세·이동", "nonsexual-pose"
    if name == "nude beach":
        return "scene", "해변", "exposure-location"
    if name == "naked school attendance":
        return "situation", "활동", "exposure-situation"
    if name in NON_ACTS or name.endswith("(meme)") or "gesture" in name.split() or row["group"] == "franchise":
        return None
    if FLUID_PATTERN.search(name):
        return "adult", "체액", "sexual-fluid"
    if name in SEXUAL_OBJECTS or re.search(r"(?:^| )sex (?:toy|toys|machine|tool|sleeve)(?: |$)", name):
        return "adult", "용품", "sexual-object"
    if name in ACTS or ACT_PATTERN.search(name) or name in PENETRATION_ACTS:
        return "adult", "행위·체위", "sexual-act"
    return None


# BEGIN APPROVED CATEGORY AUDIT 2026-10-06
# Exact reviewed corrections; offline exporter input, not keyword inference.
APPROVED_AUDIT_OVERRIDES = {
    'against fence': ('scene', '실내·건축'),
    'ahoge': ('body', '체형·부위'),
    'alchemist': ('situation', '직업·역할'),
    'alternate hairstyle': ('body', '머리카락'),
    'ama usa an uniform': ('clothing', '제복·코스튬'),
    'anal tail': ('adult', '구속·용품'),
    'anchor tattoo': ('body', '피부·표식'),
    'animal ear fluff': ('body', '체형·부위'),
    'animal ears': ('body', '종족·특징'),
    'ant girl': ('body', '종족·특징'),
    'anteater tail': ('body', '종족·특징'),
    'antenna hair': ('body', '머리카락'),
    'anzio school uniform': ('clothing', '제복·코스튬'),
    'aqua eyes': ('body', '눈·얼굴'),
    'arched back': ('action', '자세·이동'),
    'arched bangs': ('body', '머리카락'),
    'aria gakuen school uniform': ('clothing', '제복·코스튬'),
    "arm around another's back": ('action', '접촉·상호작용'),
    "arm around another's waist": ('action', '손·팔 동작'),
    'arm at side': ('action', '손·팔 동작'),
    'arm behind back': ('action', '손·팔 동작'),
    'arm behind head': ('action', '손·팔 동작'),
    "arm on another's shoulder": ('action', '접촉·상호작용'),
    'arm support': ('action', '손·팔 동작'),
    'arm under breasts': ('action', '손·팔 동작'),
    'arm up': ('action', '손·팔 동작'),
    'armadillo tail': ('body', '종족·특징'),
    'armpit stubble': ('body', '피부·표식'),
    'arms at sides': ('action', '손·팔 동작'),
    'arms behind back': ('action', '손·팔 동작'),
    'arms behind head': ('action', '손·팔 동작'),
    'arms up': ('action', '손·팔 동작'),
    'artificial vagina': ('adult', '구속·용품'),
    'back slit': ('clothing', '디테일·스타일'),
    'back-to-back': ('action', '접촉·상호작용'),
    'badger ears': ('body', '종족·특징'),
    'badger tail': ('body', '종족·특징'),
    'bald girl': ('body', '종족·특징'),
    'bar censor': ('meta', '품질·제작'),
    'bar counter': ('scene', '실내·건축'),
    'bat tattoo': ('body', '피부·표식'),
    'bathtub': ('scene', '기타 소분류'),
    'bee boy': ('body', '종족·특징'),
    'bee wings': ('body', '종족·특징'),
    'bikini bottom pull': ('action', '자세·이동'),
    'bilingual text': ('meta', '문자·기호'),
    'billboard': ('scene', '기타 소분류'),
    'biting glove': ('action', '옷 다루기'),
    'black eyes': ('body', '눈·얼굴'),
    'bleeding from forehead': ('body', '피부·표식'),
    'blocked senses': ('situation', '상태·변화'),
    'blue eyes': ('body', '눈·얼굴'),
    'blueberry academy school uniform': ('clothing', '제복·코스튬'),
    'blunt bangs': ('body', '머리카락'),
    'boar ears': ('body', '종족·특징'),
    'bob cut': ('body', '머리카락'),
    'body horror': ('meta', '화풍·표현'),
    'body modification': ('body', '체형·부위'),
    'body switch': ('situation', '상태·변화'),
    'braid': ('body', '머리카락'),
    'braided base': ('body', '머리카락'),
    'braided sidelocks': ('body', '머리카락'),
    'braided tail': ('body', '머리카락'),
    'branded': ('body', '피부·표식'),
    'broken leg': ('body', '체형·부위'),
    'brown eyes': ('body', '눈·얼굴'),
    'butcher': ('situation', '직업·역할'),
    'butterfly girl': ('body', '종족·특징'),
    'buzz cut': ('body', '머리카락'),
    'camel ears': ('body', '종족·특징'),
    'card between fingers': ('action', '사물 사용'),
    'carpet': ('scene', '기타 소분류'),
    'cat ears': ('body', '종족·특징'),
    'cat feet': ('body', '체형·부위'),
    'cat girl': ('body', '종족·특징'),
    'cat tail': ('body', '종족·특징'),
    'ceiling light': ('scene', '실내·건축'),
    'censored': ('meta', '품질·제작'),
    'censored by text': ('meta', '품질·제작'),
    'censored feet': ('meta', '품질·제작'),
    'censored nipples': ('meta', '품질·제작'),
    'centipede girl': ('body', '종족·특징'),
    'chain-link fence': ('scene', '실내·건축'),
    'chalkboard': ('scene', '기타 소분류'),
    'character censor': ('meta', '품질·제작'),
    'character watermark': ('meta', '품질·제작'),
    'cheetah ears': ('body', '종족·특징'),
    'cheetah tail': ('body', '종족·특징'),
    'chest mouth': ('body', '눈·얼굴'),
    'claw pose': ('action', '손·팔 동작'),
    'clenched hand': ('action', '손·팔 동작'),
    'clenched hands': ('action', '손·팔 동작'),
    'clothes on floor': ('scene', '실내·건축'),
    'cloud hair': ('body', '머리카락'),
    'clover-shaped pupils': ('body', '눈·얼굴'),
    'cock docking': ('adult', '행위·체위'),
    'colored armpit hair': ('body', '피부·표식'),
    'colored inner hair': ('body', '머리카락'),
    'comic sans': ('meta', '문자·기호'),
    'concrete': ('scene', '실내·건축'),
    'contrapposto': ('action', '자세·이동'),
    'convenient breasts': ('situation', '상태·변화'),
    'covering own mouth': ('action', '손·팔 동작'),
    'cowboy western': ('meta', '화풍·표현'),
    'crab girl': ('body', '종족·특징'),
    'crew cut': ('body', '머리카락'),
    'crossed arms': ('action', '손·팔 동작'),
    'crossed bangs': ('body', '머리카락'),
    'crossed legs': ('action', '자세·이동'),
    'crying with eyes open': ('expression', '감정·반응'),
    'crystal tail': ('body', '종족·특징'),
    'dark-skinned female': ('body', '피부·표식'),
    'dark-skinned male': ('body', '피부·표식'),
    'demon girl': ('body', '종족·특징'),
    'dilation tape': ('adult', '구속·용품'),
    'dildo': ('adult', '구속·용품'),
    'dildo gag': ('adult', '구속·용품'),
    'dinosaur boy': ('body', '종족·특징'),
    'dinosaur girl': ('body', '종족·특징'),
    'disembodied tongue': ('body', '체형·부위'),
    'disheveled': ('situation', '상태·변화'),
    'donkey tail': ('body', '종족·특징'),
    'double bun': ('body', '머리카락'),
    'double cheek kiss': ('action', '접촉·상호작용'),
    'double dildo': ('adult', '구속·용품'),
    'double v': ('action', '손·팔 동작'),
    'doughnut hair bun': ('body', '머리카락'),
    'dragon girl': ('body', '종족·특징'),
    'drawn horns': ('meta', '화풍·표현'),
    'dreadlocks': ('body', '체형·부위'),
    'drill hair': ('body', '머리카락'),
    'drill ponytail': ('body', '머리카락'),
    'dyed bangs': ('body', '머리카락'),
    'ears back': ('body', '종족·특징'),
    'eel girl': ('body', '종족·특징'),
    'eevee tail': ('body', '종족·특징'),
    'egg vibrator': ('adult', '구속·용품'),
    'elephant tail': ('body', '종족·특징'),
    'elf': ('body', '종족·특징'),
    'emoji censor': ('meta', '품질·제작'),
    'engrish text': ('meta', '문자·기호'),
    'enpera': ('body', '머리카락'),
    'evo grim': ('franchise', '인물·그룹'),
    'extra tails': ('body', '종족·특징'),
    'eye contact': ('action', '시선·얼굴'),
    'eyelashes': ('body', '눈·얼굴'),
    'facial hair': ('body', '머리카락'),
    'facial mark': ('body', '피부·표식'),
    'facing away': ('cast', '자세·방향'),
    'fang': ('body', '눈·얼굴'),
    'fangs': ('body', '눈·얼굴'),
    'fantasy': ('meta', '화풍·표현'),
    'female pov': ('cast', '시점·거리'),
    'fence': ('scene', '실내·건축'),
    'ferret tail': ('body', '종족·특징'),
    'fighting stance': ('action', '전투·스포츠'),
    'finger to mouth': ('action', '손·팔 동작'),
    'first high school uniform': ('clothing', '제복·코스튬'),
    'flat chastity cage': ('adult', '구속·용품'),
    'floating': ('action', '자세·이동'),
    'floating hair': ('body', '머리카락'),
    'floating rock': ('scene', '기타 소분류'),
    'floral background': ('scene', '배경 표현'),
    'flower censor': ('meta', '품질·제작'),
    'fourth east high school uniform': ('clothing', '제복·코스튬'),
    'fox ears': ('body', '종족·특징'),
    'fox girl': ('body', '종족·특징'),
    'fox tail': ('body', '종족·특징'),
    'furry': ('body', '종족·특징'),
    'furry female': ('body', '종족·특징'),
    'fusuma': ('scene', '실내·건축'),
    'futa with futa': ('adult', '행위·체위'),
    'futanari pov': ('cast', '시점·거리'),
    'gazelle horns': ('body', '종족·특징'),
    'gazelle tail': ('body', '종족·특징'),
    'gem uniform \\(houseki no kuni\\)': ('clothing', '제복·코스튬'),
    'german text': ('meta', '문자·기호'),
    'ginkgo guild uniform': ('clothing', '제복·코스튬'),
    'giraffe tail': ('body', '종족·특징'),
    'glitch censor': ('meta', '품질·제작'),
    'glutton': ('situation', '상태·변화'),
    'gold rose': ('object', '식물·자연물'),
    'grabbed by tentacles': ('action', '접촉·상호작용'),
    "grabbing another's shoulder": ('action', '접촉·상호작용'),
    "grabbing another's sleeve": ('action', '옷 다루기'),
    "grabbing another's thighs": ('action', '접촉·상호작용'),
    'graph': ('meta', '구성·형식'),
    'greek text': ('meta', '문자·기호'),
    'green eyes': ('body', '눈·얼굴'),
    'grey eyes': ('body', '눈·얼굴'),
    'gym challenge uniform': ('clothing', '제복·코스튬'),
    'hair behind eyewear': ('body', '머리카락'),
    'hair between eyes': ('body', '머리카락'),
    'hair blush': ('expression', '감정·반응'),
    'hair bun': ('body', '머리카락'),
    'hair flaps': ('body', '머리카락'),
    'hair intakes': ('body', '머리카락'),
    'hair over one eye': ('body', '머리카락'),
    'hair over shoulder': ('body', '머리카락'),
    'hair rings': ('body', '머리카락'),
    'half updo': ('body', '체형·부위'),
    'hand between legs': ('action', '손·팔 동작'),
    'hand between own legs': ('action', '손·팔 동작'),
    "hand in another's pants": ('action', '옷 다루기'),
    'hand in bra': ('action', '옷 다루기'),
    'hand in own hair': ('action', '손·팔 동작'),
    'hand in pocket': ('action', '손·팔 동작'),
    "hand on another's head": ('action', '손·팔 동작'),
    "hand on another's shoulder": ('action', '손·팔 동작'),
    'hand on chair': ('action', '사물 사용'),
    'hand on own back': ('action', '손·팔 동작'),
    'hand on own cheek': ('action', '손·팔 동작'),
    'hand on own chest': ('action', '손·팔 동작'),
    'hand on own chin': ('action', '손·팔 동작'),
    'hand on own face': ('action', '손·팔 동작'),
    'hand on own head': ('action', '손·팔 동작'),
    'hand on own hip': ('action', '손·팔 동작'),
    'hand on own nose': ('action', '손·팔 동작'),
    'hand on own tail': ('action', '손·팔 동작'),
    'hand to own mouth': ('action', '손·팔 동작'),
    'hand up': ('action', '손·팔 동작'),
    'hands in pockets': ('action', '손·팔 동작'),
    'hands on own breasts': ('action', '손·팔 동작'),
    'hands on own chest': ('action', '손·팔 동작'),
    'hands on own face': ('action', '손·팔 동작'),
    'hands on own hips': ('action', '손·팔 동작'),
    'hands on own neck': ('action', '손·팔 동작'),
    'hands on own shoulders': ('action', '손·팔 동작'),
    'hands on stomach': ('action', '손·팔 동작'),
    'hands up': ('action', '손·팔 동작'),
    'hanging scroll': ('object', '가구·생활용품'),
    'hangover': ('situation', '상태·변화'),
    'hatsuboshi gakuen school uniform': ('clothing', '제복·코스튬'),
    'head rest': ('action', '시선·얼굴'),
    'head tilt': ('action', '시선·얼굴'),
    'head under clothes': ('action', '옷 다루기'),
    'headache': ('situation', '상태·변화'),
    'heart censor': ('meta', '품질·제작'),
    'heart hair': ('body', '머리카락'),
    'heart hands': ('action', '손·팔 동작'),
    'heart-shaped mouth': ('expression', '입·미소'),
    'heterochromia': ('body', '체형·부위'),
    'high ponytail': ('body', '머리카락'),
    'holding': ('action', '사물 사용'),
    'holding bag': ('action', '사물 사용'),
    'holding candy apple': ('action', '사물 사용'),
    'holding cross': ('action', '사물 사용'),
    'holding fish': ('action', '사물 사용'),
    'holding flower': ('action', '사물 사용'),
    'holding food': ('action', '사물 사용'),
    'holding glowstick': ('action', '사물 사용'),
    'holding goggles': ('action', '사물 사용'),
    'holding hands': ('action', '접촉·상호작용'),
    'holding knife': ('action', '사물 사용'),
    'holding mirror': ('action', '사물 사용'),
    'holding own dress': ('action', '옷 다루기'),
    'holding own skirt': ('action', '옷 다루기'),
    'holding pendant': ('action', '사물 사용'),
    'holding photo': ('action', '사물 사용'),
    'holding quill': ('action', '사물 사용'),
    'holding rock': ('action', '사물 사용'),
    'holding screwdriver': ('action', '사물 사용'),
    'holding shovel': ('action', '사물 사용'),
    'holding skewer': ('action', '사물 사용'),
    'holding spatula': ('action', '사물 사용'),
    'holding staff': ('action', '사물 사용'),
    'holding sword': ('action', '사물 사용'),
    'holding ticket': ('action', '사물 사용'),
    'holding umbrella': ('action', '사물 사용'),
    'holding unworn clothes': ('action', '옷 다루기'),
    'holding walkie-talkie': ('action', '사물 사용'),
    'holding watermelon': ('action', '사물 사용'),
    'holding weapon': ('action', '사물 사용'),
    'hole in face': ('body', '체형·부위'),
    'hole in head': ('body', '체형·부위'),
    'hollow mouth': ('body', '눈·얼굴'),
    'hololive dance practice uniform': ('clothing', '제복·코스튬'),
    'horns': ('body', '종족·특징'),
    'horse dildo': ('adult', '구속·용품'),
    'horse ears': ('body', '종족·특징'),
    'horse girl': ('body', '종족·특징'),
    'hug': ('action', '접촉·상호작용'),
    'hug from behind': ('action', '접촉·상호작용'),
    'huge dildo': ('adult', '구속·용품'),
    'hugging object': ('action', '사물 사용'),
    'hugging tail': ('action', '접촉·상호작용'),
    'hyena boy': ('body', '종족·특징'),
    'identity censor': ('meta', '품질·제작'),
    'implied anal': ('adult', '행위·체위'),
    'implied vibrator': ('adult', '구속·용품'),
    'index finger raised': ('action', '손·팔 동작'),
    'indian style': ('action', '자세·이동'),
    'interface censor': ('meta', '품질·제작'),
    'interlocked fingers': ('action', '손·팔 동작'),
    'invisible chair': ('action', '자세·이동'),
    'italian text': ('meta', '문자·기호'),
    'jellyfish girl': ('body', '종족·특징'),
    'jewel butt plug': ('adult', '구속·용품'),
    'jumping': ('action', '자세·이동'),
    'kissing animal': ('action', '접촉·상호작용'),
    'kitauji high school uniform': ('clothing', '제복·코스튬'),
    'knee up': ('action', '자세·이동'),
    'kneeling': ('action', '자세·이동'),
    'knees together feet apart': ('action', '자세·이동'),
    'knees up': ('action', '자세·이동'),
    'knights of blood uniform \\(sao\\)': ('clothing', '제복·코스튬'),
    'komainu girl': ('body', '종족·특징'),
    'kuromorimine military uniform': ('clothing', '제복·코스튬'),
    'lamia boy': ('body', '종족·특징'),
    'lamppost': ('scene', '실내·건축'),
    'large wings': ('body', '종족·특징'),
    'leaf censor': ('meta', '품질·제작'),
    'leaning back': ('action', '자세·이동'),
    'leaning forward': ('action', '자세·이동'),
    'leg lift': ('action', '자세·이동'),
    'leg up': ('action', '자세·이동'),
    'leg wings': ('body', '종족·특징'),
    'legs apart': ('action', '자세·이동'),
    'legs together': ('action', '자세·이동'),
    'legs up': ('action', '자세·이동'),
    'lemur ears': ('body', '종족·특징'),
    'lemur tail': ('body', '종족·특징'),
    'licking lips': ('action', '시선·얼굴'),
    'lips': ('body', '눈·얼굴'),
    'lipstick mark on ass': ('body', '피부·표식'),
    'locked legs': ('action', '자세·이동'),
    'lone nape hair': ('body', '머리카락'),
    'long hair': ('body', '머리카락'),
    'looking afar': ('action', '시선·얼굴'),
    'looking ahead': ('action', '시선·얼굴'),
    'looking at hand': ('action', '시선·얼굴'),
    'looking back': ('action', '시선·얼굴'),
    'looking up': ('action', '시선·얼굴'),
    'love handles': ('body', '체형·부위'),
    'low ponytail': ('body', '머리카락'),
    'low twintails': ('body', '머리카락'),
    'low-tied long hair': ('body', '머리카락'),
    'low-tied sidelocks': ('body', '머리카락'),
    'lower body': ('body', '체형·부위'),
    'lycoris uniform': ('clothing', '제복·코스튬'),
    'lying on ball': ('action', '자세·이동'),
    'mahou shoujo ni akogarete': ('franchise', '작품·시리즈'),
    'male underwear pull': ('action', '자세·이동'),
    'maple leaf print': ('clothing', '무늬·재질'),
    'mariachi': ('situation', '직업·역할'),
    'market stall': ('scene', '실내·건축'),
    'masturbation day': ('situation', '행사·문화'),
    'mecha': ('object', '전자·기계'),
    'mechanical hair': ('body', '머리카락'),
    'medium hair': ('body', '머리카락'),
    'meerkat tail': ('body', '종족·특징'),
    'megurigaoka high school uniform': ('clothing', '제복·코스튬'),
    'merfolk': ('body', '종족·특징'),
    'messy hair': ('body', '머리카락'),
    'metal chastity cage': ('adult', '구속·용품'),
    'mihama private academy school uniform': ('clothing', '제복·코스튬'),
    'minoseki academy school uniform': ('clothing', '제복·코스튬'),
    'minoseki gakuin uniform': ('clothing', '제복·코스튬'),
    "mizuna girls' academy school uniform": ('clothing', '제복·코스튬'),
    'mizura': ('body', '머리카락'),
    'mole on areola': ('body', '피부·표식'),
    'mole on back': ('body', '피부·표식'),
    'mole on ear': ('body', '피부·표식'),
    'mole on forehead': ('body', '피부·표식'),
    'mole on nose': ('body', '피부·표식'),
    'money-shaped pupils': ('body', '눈·얼굴'),
    'monster girl': ('body', '종족·특징'),
    'moose tail': ('body', '종족·특징'),
    'mosaic censoring': ('meta', '품질·제작'),
    'mosquito girl': ('body', '종족·특징'),
    'mouth hold': ('action', '사물 사용'),
    'multiple animal ears': ('body', '종족·특징'),
    'multiple hands': ('body', '체형·부위'),
    'muscular child': ('body', '체형·부위'),
    'mute': ('situation', '상태·변화'),
    'mystic eyes of death perception': ('situation', '설정·능력'),
    'naoetsu high school uniform': ('clothing', '제복·코스튬'),
    'national shin ooshima school uniform': ('clothing', '제복·코스튬'),
    'neon lights': ('scene', '실내·건축'),
    'nijisanji idol uniform': ('clothing', '제복·코스튬'),
    'no anus': ('body', '체형·부위'),
    'no freckles': ('body', '체형·부위'),
    'no hands': ('body', '체형·부위'),
    'no tattoo': ('body', '피부·표식'),
    'novelty censor': ('meta', '품질·제작'),
    'nudist beach uniform': ('clothing', '제복·코스튬'),
    'official alternate hairstyle': ('body', '머리카락'),
    'okapi tail': ('body', '종족·특징'),
    'on bed': ('action', '자세·이동'),
    'on chair': ('action', '자세·이동'),
    'on floor': ('action', '자세·이동'),
    'on head': ('action', '접촉·상호작용'),
    'on side': ('action', '자세·이동'),
    'on stomach': ('action', '자세·이동'),
    'onahole': ('adult', '구속·용품'),
    'one side up': ('body', '체형·부위'),
    'ooarai naval school uniform': ('clothing', '제복·코스튬'),
    'open hand': ('action', '손·팔 동작'),
    'open window': ('scene', '실내·건축'),
    'orange eyes': ('body', '눈·얼굴'),
    'otonokizaka school uniform': ('clothing', '제복·코스튬'),
    'out-of-frame censoring': ('meta', '품질·제작'),
    'outstretched arm': ('action', '손·팔 동작'),
    'outstretched arms': ('action', '손·팔 동작'),
    'outstretched hand': ('action', '손·팔 동작'),
    'own hands together': ('action', '손·팔 동작'),
    'ox girl': ('body', '종족·특징'),
    'panda tail': ('body', '종족·특징'),
    'pangolin ears': ('body', '종족·특징'),
    'pangolin tail': ('body', '종족·특징'),
    'panther boy': ('body', '종족·특징'),
    'parted bangs': ('body', '머리카락'),
    'paw pose': ('action', '손·팔 동작'),
    'peg leg': ('body', '체형·부위'),
    'pencil mustache': ('body', '눈·얼굴'),
    'penis milking': ('adult', '행위·체위'),
    'persona eyes': ('meta', '화풍·표현'),
    'petal censor': ('meta', '품질·제작'),
    'pikachu ears': ('body', '종족·특징'),
    'pikachu tail': ('body', '종족·특징'),
    'pink eyes': ('body', '눈·얼굴'),
    'plant wings': ('body', '종족·특징'),
    'pointing': ('action', '손·팔 동작'),
    'pointless censoring': ('meta', '품질·제작'),
    'pointy ears': ('body', '종족·특징'),
    'ponytail': ('body', '머리카락'),
    'pope': ('situation', '직업·역할'),
    'porcupine ears': ('body', '종족·특징'),
    'power lines': ('scene', '실내·건축'),
    'prehensile ribbon': ('body', '종족·특징'),
    'presenting own armpit': ('action', '자세·이동'),
    'presenting own body': ('action', '자세·이동'),
    'presenting own foot': ('action', '자세·이동'),
    'pseudo-tokyo school uniform': ('clothing', '제복·코스튬'),
    'puffy lips': ('body', '눈·얼굴'),
    'purple eyes': ('body', '눈·얼굴'),
    'quiff': ('body', '머리카락'),
    'rabbit ears': ('body', '종족·특징'),
    'rabbit vibrator': ('adult', '구속·용품'),
    'railing': ('scene', '실내·건축'),
    'railroad crossing': ('scene', '실내·건축'),
    'railroad tracks': ('scene', '실내·건축'),
    'rainbow hair': ('body', '머리카락'),
    'reaching': ('action', '손·팔 동작'),
    'reaching towards viewer': ('action', '손·팔 동작'),
    'rectangular cage': ('object', '도구·의료'),
    'red eyes': ('body', '눈·얼굴'),
    'remote control vibrator': ('adult', '구속·용품'),
    'rhinoceros girl': ('body', '종족·특징'),
    'ribbon hair': ('body', '머리카락'),
    'rouman academy school uniform': ('clothing', '제복·코스튬'),
    'rubble': ('scene', '기타 소분류'),
    'running': ('action', '자세·이동'),
    'sailor senshi uniform': ('clothing', '제복·코스튬'),
    'scar on ass': ('body', '피부·표식'),
    'scorpion girl': ('body', '종족·특징'),
    'scorpion tattoo': ('body', '피부·표식'),
    'seiren academy school uniform': ('clothing', '제복·코스튬'),
    'seiza': ('action', '자세·이동'),
    'severed finger': ('body', '체형·부위'),
    'sex machine': ('adult', '구속·용품'),
    'shadow censor': ('meta', '품질·제작'),
    'shelf': ('scene', '실내·건축'),
    'shino \\(comic penguin club\\)': ('franchise', '인물·그룹'),
    'short hair': ('body', '머리카락'),
    'short hair with long locks': ('body', '머리카락'),
    'short side ponytail': ('body', '머리카락'),
    'short sidetail': ('body', '종족·특징'),
    'short twintails': ('body', '머리카락'),
    'side braid': ('body', '머리카락'),
    'side ponytail': ('body', '머리카락'),
    'side up bun': ('body', '머리카락'),
    'sidelocks': ('body', '머리카락'),
    'single blank eye': ('body', '눈·얼굴'),
    'single braid': ('body', '머리카락'),
    'single hair bun': ('body', '머리카락'),
    'sink': ('scene', '실내·건축'),
    'sitting': ('action', '자세·이동'),
    'sitting backwards': ('action', '자세·이동'),
    'sitting on person': ('action', '접촉·상호작용'),
    'sitting on water': ('action', '자세·이동'),
    'skeletal tail': ('body', '종족·특징'),
    'skirt hold': ('action', '옷 다루기'),
    'skunk girl': ('body', '종족·특징'),
    'skunk tail': ('body', '종족·특징'),
    'slap mark on face': ('body', '피부·표식'),
    'slice of life': ('situation', '활동·사건'),
    'slime censor': ('meta', '품질·제작'),
    'slingshot tan': ('body', '피부·표식'),
    'small hands': ('body', '체형·부위'),
    'small head': ('body', '체형·부위'),
    'snail girl': ('body', '종족·특징'),
    'soul patch': ('body', '눈·얼굴'),
    'speech bubble censor': ('meta', '품질·제작'),
    'spider boy': ('body', '종족·특징'),
    'spider web tattoo': ('body', '피부·표식'),
    'spiked dildo': ('adult', '구속·용품'),
    'spiked hair': ('body', '머리카락'),
    'spiked horns': ('body', '종족·특징'),
    'spiked wings': ('body', '종족·특징'),
    'spoken blush': ('meta', '문자·기호'),
    'spoken heart': ('meta', '문자·기호'),
    'spread arms': ('action', '손·팔 동작'),
    'spread pussy': ('action', '자세·이동'),
    'spy': ('situation', '직업·역할'),
    'squatting': ('action', '자세·이동'),
    'squid girl': ('body', '종족·특징'),
    'squirrel boy': ('body', '종족·특징'),
    'stage curtains': ('scene', '실내·건축'),
    'stage lights': ('scene', '실내·건축'),
    'stained glass': ('scene', '실내·건축'),
    'stairs': ('scene', '실내·건축'),
    'standing': ('action', '자세·이동'),
    'standing on chair': ('action', '자세·이동'),
    'standing on one leg': ('action', '자세·이동'),
    'standing on three legs': ('action', '자세·이동'),
    'star censor': ('meta', '품질·제작'),
    'stay fresh (pose)': ('action', '자세·이동'),
    'steampunk': ('meta', '화풍·표현'),
    'stitched eye': ('body', '눈·얼굴'),
    'stomach (organ)': ('body', '체형·부위'),
    'stomach ache': ('situation', '상태·변화'),
    'straight hair': ('body', '머리카락'),
    'strap-on': ('adult', '구속·용품'),
    'stretched limb': ('body', '체형·부위'),
    'subdermal port': ('body', '종족·특징'),
    'suction cup dildo': ('adult', '구속·용품'),
    'super robot': ('meta', '화풍·표현'),
    'swept bangs': ('body', '머리카락'),
    'sword of the creator': ('object', '무기·장비'),
    'symbol-shaped pupils': ('body', '눈·얼굴'),
    'tail': ('body', '종족·특징'),
    'tail censor': ('meta', '품질·제작'),
    'tamandua tail': ('body', '종족·특징'),
    'tape censor': ('meta', '품질·제작'),
    'tasmanian devil tail': ('body', '종족·특징'),
    'team magma uniform': ('clothing', '제복·코스튬'),
    'team rocket uniform': ('clothing', '제복·코스튬'),
    'teeth': ('body', '눈·얼굴'),
    'tenga': ('adult', '구속·용품'),
    'thick eyebrows': ('body', '눈·얼굴'),
    'tied beard': ('body', '눈·얼굴'),
    'tiles': ('scene', '실내·건축'),
    'time signature': ('meta', '문자·기호'),
    'tokiwadai school uniform': ('clothing', '제복·코스튬'),
    'tokusatsu': ('meta', '화풍·표현'),
    'too many sex toys': ('adult', '구속·용품'),
    'top-down bottom-up': ('action', '자세·이동'),
    'tracen school uniform': ('clothing', '제복·코스튬'),
    'trimmed tail': ('body', '종족·특징'),
    'triple amputee': ('body', '체형·부위'),
    'triple bun': ('body', '머리카락'),
    'tsukumihara academy uniform \\(fate/extra\\)': ('clothing', '제복·코스튬'),
    'twiddling fingers': ('action', '손·팔 동작'),
    'twin braids': ('body', '머리카락'),
    'twin drills': ('body', '체형·부위'),
    'twintails': ('body', '머리카락'),
    'two side up': ('body', '체형·부위'),
    'u.a. gym uniform': ('clothing', '제복·코스튬'),
    'uncensored': ('meta', '품질·제작'),
    'unconventional mermaid': ('body', '종족·특징'),
    'unworn pants': ('scene', '기타 소분류'),
    'upside-down': ('action', '자세·이동'),
    'upward dog': ('action', '자세·이동'),
    'utility pole': ('scene', '실내·건축'),
    'v': ('action', '손·팔 동작'),
    'v arms': ('action', '손·팔 동작'),
    'very long hair': ('body', '머리카락'),
    'vibrator': ('adult', '구속·용품'),
    'vibrator cord': ('adult', '구속·용품'),
    'walking': ('action', '자세·이동'),
    'wall of text': ('meta', '문자·기호'),
    'wariza': ('action', '자세·이동'),
    'warming hands': ('action', '손·팔 동작'),
    'washing another': ('action', '접촉·상호작용'),
    'water censor': ('meta', '품질·제작'),
    'waving': ('action', '손·팔 동작'),
    'wavy hair': ('body', '머리카락'),
    'wheel o feet': ('meta', '화풍·표현'),
    'wind turbine': ('scene', '실내·건축'),
    'window': ('scene', '실내·건축'),
    'windowsill': ('scene', '실내·건축'),
    'windsock': ('object', '가구·생활용품'),
    'wing censor': ('meta', '품질·제작'),
    'wing tattoo': ('body', '피부·표식'),
    'wings': ('body', '종족·특징'),
    'wireless sex toy controller': ('adult', '구속·용품'),
    'wolf cut': ('body', '머리카락'),
    'wooden fence': ('scene', '실내·건축'),
    'wooden floor': ('scene', '실내·건축'),
    'wooden wall': ('scene', '실내·건축'),
    'wreckage': ('scene', '기타 소분류'),
    'x-ray': ('meta', '화풍·표현'),
    'yamaku high school uniform': ('clothing', '제복·코스튬'),
    'yasogami school uniform': ('clothing', '제복·코스튬'),
    'yellow eyes': ('body', '눈·얼굴'),
    'yokozuwari': ('action', '자세·이동'),
    'yuigaoka school uniform': ('clothing', '제복·코스튬'),
    'yurigaoka girls academy school uniform': ('clothing', '제복·코스튬'),
    'zebra tail': ('body', '종족·특징'),
}

# Exact KR fallback names absent from the source mapping.
APPROVED_AUDIT_FALLBACKS = ('gem uniform \\(houseki no kuni\\)', 'knights of blood uniform \\(sao\\)', 'mahou shoujo ni akogarete', 'shino \\(comic penguin club\\)', 'tsukumihara academy uniform \\(fate/extra\\)')


# BEGIN SUBCATEGORY DEFINITION REVIEW 2026-10-06
# Explicit definition checks supersede the earlier name-based assignments.
REVIEWED_SUBCATEGORY_CORRECTIONS = {
    'ahoge': ('body', '머리카락'),
    'animal ear fluff': ('body', '종족·특징'),
    "arm around another's waist": ('action', '접촉·상호작용'),
    'bald girl': ('body', '머리카락'),
    'bathtub': ('scene', '실내·건축'),
    'bikini bottom pull': ('action', '옷 다루기'),
    'braided tail': ('body', '종족·특징'),
    'carpet': ('scene', '실내·건축'),
    'chalkboard': ('scene', '실내·건축'),
    'chest mouth': ('body', '체형·부위'),
    'dreadlocks': ('body', '머리카락'),
    'facial hair': ('body', '눈·얼굴'),
    'glutton': ('situation', '관계·감정'),
    'half updo': ('body', '머리카락'),
    'heterochromia': ('body', '눈·얼굴'),
    'hole in face': ('body', '눈·얼굴'),
    'male underwear pull': ('action', '옷 다루기'),
    'no freckles': ('body', '피부·표식'),
    'one side up': ('body', '머리카락'),
    'short sidetail': ('body', '머리카락'),
    'too many sex toys': ('adult', '상황·취향'),
    'twin drills': ('body', '머리카락'),
    'two side up': ('body', '머리카락'),
}
APPROVED_AUDIT_OVERRIDES.update(REVIEWED_SUBCATEGORY_CORRECTIONS)
