"""カフェガチャの固定カタログと抽選テーブル。"""

from __future__ import annotations

from collections.abc import Set
from dataclasses import dataclass
from typing import Literal

type Rarity = Literal["C", "UC", "R", "SR", "SSR"]

PAID_DRAW_COST_XP = 20
MAX_HOURLY_DRAWS = 10
TOTAL_WEIGHT = 10_000
UNOWNED_WEIGHT_MULTIPLIER = 2
ENDGAME_PITY_MIN_COLLECTED = 90
ENDGAME_PITY_DUPLICATE_DRAWS = 100
RARITY_ORDER: tuple[Rarity, ...] = ("C", "UC", "R", "SR", "SSR")
RARITY_TOTAL_WEIGHTS: dict[Rarity, int] = {
    "C": 6500,
    "UC": 2400,
    "R": 800,
    "SR": 250,
    "SSR": 50,
}
DRAW_REWARD_XP_BY_RARITY: dict[Rarity, int] = {
    "C": 25,
    "UC": 30,
    "R": 60,
    "SR": 150,
    "SSR": 500,
}
RARITY_LABELS: dict[str, str] = {
    "C": "N",
    "UC": "HN",
}


def rarity_label(rarity: str) -> str:
    return RARITY_LABELS.get(rarity, rarity)


@dataclass(frozen=True)
class CafeCard:
    key: str
    name: str
    rarity: Rarity
    weight: int
    description: str
    image_filename: str

    @property
    def exchange_xp(self) -> int:
        """重複交換時も獲得時と同額のXPを返す。"""
        return self.draw_reward_xp

    @property
    def draw_reward_xp(self) -> int:
        return DRAW_REWARD_XP_BY_RARITY[self.rarity]


def _card(
    key: str,
    name: str,
    rarity: Rarity,
    weight: int,
    description: str,
) -> CafeCard:
    return CafeCard(key, name, rarity, weight, description, f"{key}.jpg")


CARDS: tuple[CafeCard, ...] = (
    # N: 代用品・見切り品・ちょっと残念な一杯（25種 / 65%）
    _card(
        "spent-tea",
        "出がらし",
        "C",
        260,
        "二煎目か三煎目かは、もう誰も数えていない。",
    ),
    _card(
        "cold-black-tea",
        "すっかり冷めた紅茶",
        "C",
        260,
        "温め直すほどでもないので、そのままどうぞ。",
    ),
    _card(
        "k-pan",
        "Kブロート",
        "C",
        260,
        "ジャガイモでかさ増し。パンだと言い張る気持ちはある。",
    ),
    _card(
        "sunflower-coffee",
        "ひまわりコーヒー",
        "C",
        260,
        "豆は不在。でも香ばしさは出席している。",
    ),
    _card(
        "acorn-coffee",
        "どんぐりコーヒー",
        "C",
        260,
        "森から届いた、コーヒーっぽい何か。",
    ),
    _card(
        "100-yen-black-tea",
        "百円ショップの徳用紅茶",
        "C",
        260,
        "百円でたっぷり。香りは一瞬だけ立ち寄った。",
    ),
    _card(
        "sale-tea-bags",
        "賞味期限間近の特売紅茶",
        "C",
        260,
        "赤い値札は、どんな茶葉より目を引く。",
    ),
    _card(
        "convenience-coffee",
        "冷めかけのコンビニコーヒー",
        "C",
        260,
        "ふたを開けたころには、だいたい飲みごろを過ぎている。",
    ),
    _card(
        "instant-coffee",
        "目分量のインスタントコーヒー",
        "C",
        260,
        "スプーン山盛り一杯。今日だけ妙に濃い。",
    ),
    _card(
        "discount-roll-cake",
        "半額ロールケーキ",
        "C",
        260,
        "値引きシール込みで、いちばん輝いて見える。",
    ),
    _card(
        "100-yen-cookie",
        "袋の底の割れクッキー",
        "C",
        260,
        "一枚分あるかは、並べてから考える。",
    ),
    _card(
        "convenience-anpan",
        "少しつぶれたコンビニあんぱん",
        "C",
        260,
        "味は同じ。見た目だけが通勤ラッシュを知っている。",
    ),
    _card(
        "hardtack",
        "ハードタック",
        "C",
        260,
        "保存性に全振り。歯の耐久試験もついてくる。",
    ),
    _card(
        "national-loaf",
        "ナショナル・ローフ",
        "C",
        260,
        "灰褐色でずっしり。華やかさは配給対象外。",
    ),
    _card(
        "jam-toast",
        "ジャムの薄いトースト",
        "C",
        260,
        "向こう側が透けそうな一層に、希望を託す。",
    ),
    _card(
        "mugicha",
        "昨日の麦茶",
        "C",
        260,
        "冷蔵庫の奥で、香ばしさより冷たさを磨いていた。",
    ),
    _card(
        "kommissbrot",
        "コミスブロート",
        "C",
        260,
        "ライ麦と小麦をぎゅっと焼成。愛想より日持ち。",
    ),
    _card(
        "dandelion-coffee",
        "たんぽぽコーヒー",
        "C",
        260,
        "根っこ由来の、コーヒー席の代理出席者。",
    ),
    _card(
        "woolton-pie",
        "ウールトンパイ",
        "C",
        260,
        "肉は欠席。野菜だけでパイの重責を担う。",
    ),
    _card(
        "rooibos-tea",
        "いただきもののルイボスティー",
        "C",
        260,
        "健康によいらしい。誰から来たかは覚えていない。",
    ),
    _card(
        "honey-tea",
        "はちみつを入れすぎた紅茶",
        "C",
        260,
        "甘さが先頭を走り、紅茶は後ろからついてくる。",
    ),
    _card(
        "mint-tea",
        "庭で増えすぎたミントティー",
        "C",
        260,
        "一杯いれても、庭のミントは減った気がしない。",
    ),
    _card(
        "cocoa",
        "底に粉が残ったココア",
        "C",
        260,
        "最後のひと口だけ、急に濃厚。",
    ),
    _card(
        "sachet-chai",
        "お湯多めの粉末チャイ",
        "C",
        260,
        "節約した一杯。スパイスは遠くで応援している。",
    ),
    _card(
        "drink-bar-coffee",
        "閉店前のドリンクバーコーヒー",
        "C",
        260,
        "煮詰まった香りに、今日一日の貫禄がある。",
    ),
    # HN: 定番茶と喫茶店の軽食（25種 / 24%）
    _card(
        "barley-chicory-coffee",
        "麦とチコリの代用珈琲",
        "UC",
        96,
        "麦の香ばしさとチコリのほろ苦さ。",
    ),
    _card("genmaicha", "玄米茶", "UC", 96, "湯気の向こうに、炒り米のやさしい香り。"),
    _card("scone", "スコーン", "UC", 96, "狼藉を働かず、まずはクロテッドクリームを。"),
    _card(
        "english-breakfast",
        "イングリッシュブレックファスト",
        "UC",
        96,
        "ミルクにも負けない、朝の力強いブレンド。",
    ),
    _card(
        "butter-toast",
        "厚切りバタートースト",
        "UC",
        96,
        "格子状の焼き目へ、溶けたバターがしみていく。",
    ),
    _card(
        "assam-ctc",
        "アッサムCTC",
        "UC",
        96,
        "粒状の茶葉から濃く早く出る、ミルクティー向き。",
    ),
    _card(
        "egg-salad-sandwich",
        "たまごサンド",
        "UC",
        96,
        "ふんわりパンと、やさしい味のたまごフィリング。",
    ),
    _card(
        "coffee-jelly",
        "コーヒーゼリー",
        "UC",
        96,
        "ほろ苦い角切りゼリーに、白いクリームをひとまわし。",
    ),
    _card(
        "jasmine-tea",
        "ジャスミン茶",
        "UC",
        96,
        "花香をまとった茶葉が、すっと気分をほどく。",
    ),
    _card("sencha", "煎茶", "UC", 96, "青い香りとほどよい渋み、日本茶のまんなか。"),
    _card("hojicha", "ほうじ茶", "UC", 96, "焙じた茶葉の香りが、部屋まであたためる。"),
    _card(
        "custard-pudding",
        "喫茶店のプリン",
        "UC",
        96,
        "固めのプリンに、ほろ苦いカラメルをたっぷり。",
    ),
    _card(
        "dorayaki", "どら焼き", "UC", 96, "ふっくら焼いた皮で、粒あんをやさしく挟んだ。"
    ),
    _card(
        "masala-chai",
        "マサラチャイ",
        "UC",
        96,
        "茶葉とミルクにスパイスを煮込んだ熱い一杯。",
    ),
    _card(
        "teh-tarik",
        "テータリック",
        "UC",
        96,
        "高く引いて泡立てる、マレーシアの甘いミルクティー。",
    ),
    _card(
        "thai-iced-tea",
        "タイアイスティー",
        "UC",
        96,
        "氷とミルクで仕上げる、鮮やかで甘い紅茶。",
    ),
    _card(
        "hong-kong-milk-tea",
        "香港式ミルクティー",
        "UC",
        96,
        "濃く抽出した紅茶へミルクをたっぷり。",
    ),
    _card(
        "vietnamese-iced-coffee",
        "ベトナムアイスコーヒー",
        "UC",
        96,
        "濃い珈琲と練乳を氷の上でゆっくり混ぜる。",
    ),
    _card(
        "turkish-coffee",
        "トルココーヒー",
        "UC",
        96,
        "細挽き豆を煮出し、粉ごと味わう濃密な一杯。",
    ),
    _card(
        "vietnamese-egg-coffee",
        "ベトナムエッグコーヒー",
        "UC",
        96,
        "卵のふわふわしたクリームを濃い珈琲へ。",
    ),
    _card(
        "moroccan-mint-tea",
        "モロッコミントティー",
        "UC",
        96,
        "緑茶とミントを甘く淹れ、高い位置から注ぐ。",
    ),
    _card(
        "tibetan-butter-tea",
        "チベットのバター茶",
        "UC",
        96,
        "茶にバターと塩を合わせた、体を支える一杯。",
    ),
    _card(
        "cinnamon-roll",
        "シナモンロール",
        "UC",
        96,
        "渦巻く生地から、シナモンと砂糖が甘く香る。",
    ),
    _card(
        "kaya-toast",
        "カヤトースト",
        "UC",
        96,
        "薄焼きトーストに、カヤジャムとバターを挟んだ朝食。",
    ),
    _card(
        "kopi-joss",
        "コピ・ジョス",
        "UC",
        96,
        "熱い炭を落として仕上げる、ジョグジャカルタの珈琲。",
    ),
    # R: 産地銘柄・発酵茶・専門店スイーツ（25種 / 8%）
    _card("earl-grey", "アールグレイ", "R", 32, "ベルガモットが華やぐ午後の定番。"),
    _card(
        "hojicha-latte", "ほうじ茶ラテ", "R", 32, "焙じ香とミルクがほどける夜の一杯。"
    ),
    _card(
        "house-blend",
        "店主の特製ブレンド",
        "R",
        32,
        "配合は秘密。今日の気分だけが隠し味。",
    ),
    _card(
        "brazil-santos-no2",
        "ブラジル サントスNo.2",
        "R",
        32,
        "穏やかな苦みとナッツ感を備えた定番銘柄。",
    ),
    _card(
        "brazil-yellow-bourbon",
        "ブラジル イエローブルボン",
        "R",
        32,
        "丸い甘みと香ばしさを楽しむ黄色い実の珈琲。",
    ),
    _card(
        "colombia-supremo",
        "コロンビア スプレモ",
        "R",
        32,
        "大粒豆らしい豊かな香りと均整の取れた酸味。",
    ),
    _card(
        "guatemala-antigua",
        "グアテマラ アンティグア",
        "R",
        32,
        "火山性土壌が育む、香ばしく厚みのある味。",
    ),
    _card(
        "canele",
        "カヌレ",
        "R",
        32,
        "香ばしい殻の中に、ラム香るもっちり生地。",
    ),
    _card(
        "costa-rica-tarrazu",
        "コスタリカ タラス",
        "R",
        32,
        "澄んだ酸味と甘い香りがきれいに重なる。",
    ),
    _card(
        "basque-cheesecake",
        "バスクチーズケーキ",
        "R",
        32,
        "焦げた表面の奥に、濃厚でなめらかなチーズ生地。",
    ),
    _card(
        "mont-blanc",
        "モンブラン",
        "R",
        32,
        "栗のクリームを細く重ねた、秋色のケーキ。",
    ),
    _card(
        "ethiopia-yirgacheffe-g1",
        "エチオピア イルガチェフェG1",
        "R",
        32,
        "花や柑橘を思わせる、透明感のある香り。",
    ),
    _card(
        "ethiopia-sidamo-g1",
        "エチオピア シダモG1",
        "R",
        32,
        "果実の甘酸っぱさと華やかな余韻。",
    ),
    _card(
        "ethiopia-harrar",
        "エチオピア ハラー",
        "R",
        32,
        "乾いた果実やスパイスを思わせる野性味。",
    ),
    _card(
        "kenya-aa", "ケニアAA", "R", 32, "大粒豆がもたらす、鮮やかな酸味と力強いこく。"
    ),
    _card(
        "tanzania-kilimanjaro-aa",
        "タンザニア キリマンジャロAA",
        "R",
        32,
        "高地の明るい酸味と、すっきりした後味。",
    ),
    _card(
        "lemon-drizzle-cake",
        "レモンドリズルケーキ",
        "R",
        32,
        "レモンシロップがしみた、きゅっと爽やかな焼き菓子。",
    ),
    _card(
        "sumatra-mandheling-g1",
        "スマトラ マンデリンG1",
        "R",
        32,
        "重厚なこくとハーブを思わせる個性的な香り。",
    ),
    _card(
        "sulawesi-toraja",
        "スラウェシ トラジャ",
        "R",
        32,
        "深いこくと穏やかな苦みが長く続く。",
    ),
    _card(
        "fruit-tart",
        "季節のフルーツタルト",
        "R",
        32,
        "さくさくの台へ、色とりどりの果物をきれいに並べて。",
    ),
    _card(
        "tea-sandwiches",
        "ティーサンドイッチ",
        "R",
        32,
        "きゅうりや卵を薄いパンで挟んだ、小さな軽食。",
    ),
    _card(
        "monsooned-malabar",
        "モンスーン・マラバール",
        "R",
        32,
        "季節風にさらして生まれる、低い酸味と独特の熟成香。",
    ),
    _card(
        "goishicha",
        "碁石茶",
        "R",
        32,
        "二段階発酵で仕上げる、高知に伝わる酸味のある茶。",
    ),
    _card(
        "awabancha",
        "阿波晩茶",
        "R",
        32,
        "桶で乳酸発酵させる、徳島生まれのすっきりした茶。",
    ),
    _card(
        "batabatacha",
        "バタバタ茶",
        "R",
        32,
        "発酵茶を茶筅で泡立てて味わう富山の習わし。",
    ),
    # SR: 特級銘柄・名茶・上質菓子（21種 / 2.5%）
    _card("blooming-tea", "工芸茶", "SR", 12, "ポットの中で花ひらく、小さな茶会。"),
    _card(
        "afternoon-tea-set",
        "アフタヌーンティーセット",
        "SR",
        12,
        "三段重ねに甘味と会話を盛りつけて。",
    ),
    _card(
        "jamaica-blue-mountain-no1",
        "ジャマイカ ブルーマウンテンNo.1",
        "SR",
        12,
        "香り・酸味・こくが端正に調和する名高い珈琲。",
    ),
    _card(
        "hawaii-kona-extra-fancy",
        "ハワイ コナ エクストラファンシー",
        "SR",
        12,
        "大粒で整った豆が生む、明るく上品な味わい。",
    ),
    _card(
        "yemen-mocha-matari",
        "イエメン モカマタリ",
        "SR",
        12,
        "乾いた果実と香辛料を思わせる古典的なモカ。",
    ),
    _card(
        "panama-geisha",
        "パナマ ゲイシャ",
        "SR",
        12,
        "ジャスミンや柑橘を思わせる、際立って華やかな珈琲。",
    ),
    _card(
        "kenya-sl28",
        "ケニア SL28",
        "SR",
        12,
        "カシスを思わせる鮮烈な果実味で知られる品種。",
    ),
    _card(
        "wagashi-assortment",
        "上生菓子の盛り合わせ",
        "SR",
        12,
        "季節の景色を、小さな練り切りに映したひと皿。",
    ),
    _card(
        "darjeeling-first-flush",
        "ダージリン ファーストフラッシュ",
        "SR",
        12,
        "春摘みらしい若葉の香りと軽やかな渋み。",
    ),
    _card(
        "darjeeling-second-flush",
        "ダージリン セカンドフラッシュ",
        "SR",
        12,
        "夏摘みの熟した香りとマスカテルの余韻。",
    ),
    _card(
        "sachertorte",
        "ザッハトルテ",
        "SR",
        12,
        "艶やかなチョコレートと杏ジャムを重ねた濃厚な一切れ。",
    ),
    _card(
        "ceylon-uva",
        "セイロン ウバ",
        "SR",
        12,
        "涼風の季節に際立つ、爽快な香気ときりっとした渋み。",
    ),
    _card(
        "opera-cake",
        "オペラ",
        "SR",
        12,
        "珈琲とチョコレートの層を端正に重ねたフランス菓子。",
    ),
    _card(
        "keemun",
        "祁門紅茶",
        "SR",
        12,
        "蜜や花を思わせる香りを持つ、中国を代表する紅茶。",
    ),
    _card(
        "lapsang-souchong",
        "正山小種",
        "SR",
        12,
        "松煙香が深く残る、個性豊かな中国紅茶。",
    ),
    _card(
        "longjing", "西湖龍井", "SR", 12, "扁平な茶葉から栗を思わせる香りが立つ名緑茶。"
    ),
    _card(
        "mille-feuille",
        "ミルフィーユ",
        "SR",
        12,
        "薄いパイとカスタードを、崩れそうなほど繊細に重ねて。",
    ),
    _card(
        "kouign-amann",
        "クイニーアマン",
        "SR",
        12,
        "幾層ものバター生地を、砂糖でぱりっとキャラメリゼ。",
    ),
    _card(
        "tieguanyin", "安渓鉄観音", "SR", 12, "蘭を思わせる香りと厚みある甘さの烏龍茶。"
    ),
    _card(
        "da-hong-pao", "大紅袍", "SR", 11, "岩肌の茶園が育む、焙煎香と長い余韻の岩茶。"
    ),
    _card(
        "hon-gyokuro", "本玉露", "SR", 11, "覆い香と濃いうま味を一滴ずつ味わう日本茶。"
    ),
    # SSR: 店の伝説と現実の珍品（4種 / 0.5%）
    _card(
        "legendary-tea-leaves",
        "幻の茶葉",
        "SSR",
        13,
        "店主でさえ滅多に封を切らない秘蔵品。",
    ),
    _card(
        "golden-tea-set",
        "黄金のティーセット",
        "SSR",
        13,
        "茶会そのものが伝説になる眩い一式。",
    ),
    _card(
        "wild-kopi-luwak",
        "野生由来のコピ・ルアク",
        "SSR",
        12,
        "森で採取された豆だけを選ぶ、希少なシベットコーヒー。",
    ),
    _card(
        "elephant-coffee",
        "象が選んだ発酵コーヒー",
        "SSR",
        12,
        "象の消化過程を経た豆を丁寧に精製する珍しい珈琲。",
    ),
)
CARDS_BY_KEY = {card.key: card for card in CARDS}
FOOD_CARD_KEYS = frozenset(
    {
        "k-pan",
        "discount-roll-cake",
        "100-yen-cookie",
        "convenience-anpan",
        "hardtack",
        "national-loaf",
        "jam-toast",
        "kommissbrot",
        "woolton-pie",
        "scone",
        "butter-toast",
        "egg-salad-sandwich",
        "coffee-jelly",
        "custard-pudding",
        "dorayaki",
        "cinnamon-roll",
        "kaya-toast",
        "canele",
        "basque-cheesecake",
        "mont-blanc",
        "lemon-drizzle-cake",
        "fruit-tart",
        "tea-sandwiches",
        "afternoon-tea-set",
        "wagashi-assortment",
        "sachertorte",
        "opera-cake",
        "mille-feuille",
        "kouign-amann",
    }
)
CARDS_BY_RARITY: dict[Rarity, tuple[CafeCard, ...]] = {
    rarity: tuple(card for card in CARDS if card.rarity == rarity)
    for rarity in RARITY_ORDER
}

if len(CARDS) != 100:
    raise RuntimeError("cafe gacha catalog must contain exactly 100 cards")
if len(CARDS_BY_KEY) != len(CARDS):
    raise RuntimeError("cafe gacha card keys must be unique")
if len(FOOD_CARD_KEYS) != 29 or not CARDS_BY_KEY.keys() >= FOOD_CARD_KEYS:
    raise RuntimeError("cafe gacha catalog must contain exactly 29 food cards")
if sum(card.weight for card in CARDS) != TOTAL_WEIGHT:
    raise RuntimeError("cafe gacha weights must total 10,000")
if {
    rarity: sum(card.weight for card in CARDS_BY_RARITY[rarity])
    for rarity in RARITY_ORDER
} != RARITY_TOTAL_WEIGHTS:
    raise RuntimeError("cafe gacha rarity weights must match configured totals")


def _validate_draw_value(value: int) -> None:
    if not 0 <= value < TOTAL_WEIGHT:
        msg = f"value must be between 0 and {TOTAL_WEIGHT - 1}"
        raise ValueError(msg)


def select_card(value: int) -> CafeCard:
    """0..9999 の値を固定抽選表へ写像する。境界テスト用の純粋関数。"""
    _validate_draw_value(value)
    cursor = 0
    for card in CARDS:
        cursor += card.weight
        if value < cursor:
            return card
    raise AssertionError("unreachable catalog boundary")


def select_card_for_collection(value: int, collected_keys: Set[str]) -> CafeCard:
    """レアリティ率を保ったまま、同一レアリティの未所持を2倍優遇する。"""
    _validate_draw_value(value)
    rarity_start = 0
    for rarity in RARITY_ORDER:
        rarity_weight = RARITY_TOTAL_WEIGHTS[rarity]
        if value >= rarity_start + rarity_weight:
            rarity_start += rarity_weight
            continue

        cards = CARDS_BY_RARITY[rarity]
        boosted_weights = tuple(
            card.weight
            * (UNOWNED_WEIGHT_MULTIPLIER if card.key not in collected_keys else 1)
            for card in cards
        )
        boosted_total = sum(boosted_weights)
        within_rarity = value - rarity_start
        boosted_value = within_rarity * boosted_total // rarity_weight
        cursor = 0
        for card, weight in zip(cards, boosted_weights, strict=True):
            cursor += weight
            if boosted_value < cursor:
                return card
        raise AssertionError("unreachable boosted catalog boundary")
    raise AssertionError("unreachable rarity boundary")


def select_unowned_card(value: int, collected_keys: Set[str]) -> CafeCard:
    """元の重み比を保ちながら、未所持カードだけから1枚選ぶ。"""
    _validate_draw_value(value)
    unowned = tuple(card for card in CARDS if card.key not in collected_keys)
    if not unowned:
        return select_card_for_collection(value, collected_keys)
    unowned_weight = sum(card.weight for card in unowned)
    normalized_value = value * unowned_weight // TOTAL_WEIGHT
    cursor = 0
    for card in unowned:
        cursor += card.weight
        if normalized_value < cursor:
            return card
    raise AssertionError("unreachable unowned catalog boundary")
