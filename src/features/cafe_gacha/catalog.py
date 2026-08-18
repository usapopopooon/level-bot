"""カフェガチャの固定カタログと抽選テーブル。"""

from __future__ import annotations

from collections.abc import Set
from dataclasses import dataclass, replace
from typing import Literal

type Rarity = Literal["C", "UC", "R", "SR", "SSR", "UR", "MYTHIC"]
type CafeCardTag = Literal["coffee", "tea", "sweets", "culture"]

PAID_DRAW_COST_XP = 20
MAX_HOURLY_DRAWS = 10
TOTAL_WEIGHT = 150_000
UNOWNED_WEIGHT_MULTIPLIER = 2
ENDGAME_PITY_MIN_COLLECTED = 166
ENDGAME_PITY_DUPLICATE_DRAWS = 100
RARITY_ORDER: tuple[Rarity, ...] = (
    "C",
    "UC",
    "R",
    "SR",
    "SSR",
    "UR",
    "MYTHIC",
)
RARITY_TOTAL_WEIGHTS: dict[Rarity, int] = {
    "C": 97_500,
    "UC": 36_000,
    "R": 12_000,
    "SR": 3_750,
    "SSR": 600,
    "UR": 120,
    "MYTHIC": 30,
}
LEGACY_RARITY_TOTAL_WEIGHTS: dict[Rarity, int] = {
    "C": 6_500,
    "UC": 2_400,
    "R": 800,
    "SR": 250,
}
LEGACY_WEIGHT_SCALE = 15
DRAW_REWARD_XP_BY_RARITY: dict[Rarity, int] = {
    "C": 25,
    "UC": 30,
    "R": 60,
    "SR": 150,
    "SSR": 500,
    "UR": 1_500,
    "MYTHIC": 5_000,
}
EXCHANGE_XP_BY_RARITY: dict[Rarity, int] = {
    "C": 5,
    "UC": 10,
    "R": 20,
    "SR": 50,
    "SSR": 150,
    "UR": 500,
    "MYTHIC": 1_500,
}
RARITY_LABELS: dict[str, str] = {
    "C": "N",
    "UC": "HN",
    "MYTHIC": "幻",
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
        """重複交換時のXPを返す。"""
        return EXCHANGE_XP_BY_RARITY[self.rarity]

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
    # N: 代用品・見切り品・ちょっと残念な一杯（51種 / 65%）
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
    # HN: 定番茶と喫茶店の軽食（49種 / 24%）
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
    # R: 産地銘柄・発酵茶・専門店スイーツ（44種 / 8%）
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
    # SR: 特級銘柄・名茶・上質菓子（34種 / 2.5%）
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
    # SSR: 店の伝説と現実の珍品（6種 / 0.4%）
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
    # 追加常設: 飢饉食・軍用食・地域の喫茶史（20種）
    _card(
        "pettuleipa",
        "ペットゥレイパ",
        "C",
        1,
        "凶作時のフィンランドで、ライ麦へ松の内皮粉を混ぜた救荒パン。",
    ),
    _card(
        "horsebread",
        "ホースブレッド",
        "C",
        1,
        "豆やふすまを固めた中世の安価な馬用パン。困窮時には人も食べた。",
    ),
    _card(
        "turnip-winter-stew",
        "蕪の冬のスープ",
        "C",
        1,
        "ジャガイモも欠乏した1916〜17年のドイツを支えた蕪料理。",
    ),
    _card(
        "nettle-soup",
        "イラクサのスープ",
        "C",
        1,
        "畑の外で摘める若葉を煮た、農村の素朴な野草スープ。",
    ),
    _card(
        "water-gruel",
        "水でのばしたグルーエル",
        "C",
        1,
        "わずかな穀物を水で長く煮て量を増やした、薄い粥。",
    ),
    _card(
        "chestnut-polenta",
        "栗粉のポレンタ",
        "C",
        1,
        "穀物の乏しいコルシカ山地で、栗粉を主食へ変えた一皿。",
    ),
    _card(
        "tsampa",
        "ツァンパ",
        "UC",
        1,
        "炒った大麦粉を茶などで練る、火を使わず食べられるチベットの携行食。",
    ),
    _card(
        "mamaliga",
        "ママリガ",
        "UC",
        1,
        "固く練れば糸で切り分けられる、ルーマニアの農村のトウモロコシ粥。",
    ),
    _card(
        "migas",
        "羊飼いのミガス",
        "UC",
        1,
        "固くなったパンを崩して炒め、無駄なく食べ切るイベリアの料理。",
    ),
    _card(
        "portable-soup",
        "ポータブル・スープ",
        "UC",
        1,
        "肉の煮汁を板状に乾かした、18世紀英国海軍の携帯スープ。",
    ),
    _card(
        "posca",
        "ポスカ",
        "UC",
        1,
        "酢になった葡萄酒を水で割った、古代ローマ兵にも馴染み深い飲み物。",
    ),
    _card(
        "qishr",
        "キシル",
        "R",
        1,
        "乾燥させたコーヒーチェリーの果皮を生姜と煮出すイエメンの飲み物。",
    ),
    _card(
        "mazagran",
        "マザグラン",
        "R",
        1,
        "19世紀のアルジェリアからフランスへ広がった、背高グラスの冷たい珈琲。",
    ),
    _card(
        "cafe-de-olla",
        "カフェ・デ・オジャ",
        "R",
        1,
        "土鍋で黒糖やシナモンと煮出す、メキシコの香り高い珈琲。",
    ),
    _card(
        "bicerin",
        "ビチェリン",
        "R",
        1,
        "珈琲・チョコレート・クリームを層にした、トリノの歴史的な一杯。",
    ),
    _card(
        "east-frisian-tea",
        "東フリースラントの茶席",
        "SR",
        1,
        "氷砂糖とクリームの雲を混ぜずに味わう、約300年続く北海沿岸の茶文化。",
    ),
    _card(
        "einspanner",
        "アインシュペナー",
        "SR",
        1,
        "一頭立て馬車の御者に名を取る、クリームを厚く載せたウィーン珈琲。",
    ),
    _card(
        "wiener-melange",
        "ウィンナー・メランジェ",
        "SR",
        1,
        "珈琲と泡立てたミルクを合わせる、新聞の似合うウィーンの定番。",
    ),
    _card(
        "cafe-touba",
        "カフェ・トゥーバ",
        "SR",
        1,
        "ギニアペッパーの香りを重ねる、セネガルで親しまれる香辛料珈琲。",
    ),
    _card(
        "st-helena-bourbon",
        "セントヘレナ・グリーンチップ・バーボン",
        "SSR",
        1,
        "18世紀にイエメンから孤島へ渡り、隔絶した環境で守られた希少な珈琲。",
    ),
    # 追加常設: 身近な商品の面影を独自の言葉遊びにした喫茶ネタ（12種）
    _card(
        "morning-tea",
        "午前の紅茶",
        "C",
        1,
        "午後まで待てなかった。時計だけが、ずっと午前を指している。",
    ),
    _card(
        "moss-cola",
        "苔コーラ",
        "C",
        1,
        "底の丸いものは、まりもではないらしい。",
    ),
    _card(
        "red-cow-energy",
        "赤べこエナジー",
        "C",
        1,
        "飲むと首だけが小刻みに元気になる。",
    ),
    _card(
        "shimeji-hill",
        "しめじの丘",
        "C",
        1,
        "焼き菓子だと説明された。土に見える部分も食べられるらしい。",
    ),
    _card(
        "chikuwa-village",
        "竹輪の里",
        "C",
        1,
        "たけのこを用意できなかった村の苦肉の策。",
    ),
    _card(
        "unbroken-biscuit-sticks",
        "ポキッとしなかった棒菓子",
        "C",
        1,
        "湿気に負けたが、心までは折れていない。",
    ),
    _card(
        "capybara-break",
        "カピバラの休憩",
        "UC",
        1,
        "行進する気配がまったくない、くつろぎすぎた焼き菓子。",
    ),
    _card(
        "mistaken-donuts",
        "ミスしたドーナツ",
        "UC",
        1,
        "穴の位置も形も自由。店主は全部ドーナツだと言っている。",
    ),
    _card(
        "sure-to-break-wafer",
        "きっと割れるウエハース",
        "UC",
        1,
        "願望ではなく、持ち運び上の注意である。",
    ),
    _card(
        "first-love-soda",
        "白い初恋ソーダ",
        "R",
        1,
        "添えられた手紙に差出人はいない。味だけは甘酸っぱい。",
    ),
    _card(
        "stardust-cream-latte",
        "星屑クリームラテ",
        "R",
        1,
        "金色の粒は食用らしい。星屑かどうかは聞かないでほしい。",
    ),
    _card(
        "emperors-rich-cup",
        "皇帝の濃厚カップ",
        "SR",
        1,
        "王冠は飴細工らしい。誰が皇帝なのかは教えてもらえなかった。",
    ),
    # 追加常設: 世相や仕組みを喫茶メニューへ落とし込んだ風刺ネタ（22種）
    _card(
        "shrinkflation-sandwich",
        "実質据え置きサンド",
        "C",
        1,
        "パンの厚さは据え置き。具材だけが、ひと足先にスリムになった。",
    ),
    _card(
        "payday-eve-blend",
        "給料日前ブレンド",
        "C",
        1,
        "豆は三粒、ビスケットは半分。給料日はまだ湯気の向こう。",
    ),
    _card(
        "self-help-soup",
        "自助努力スープ",
        "C",
        1,
        "具材はそろえました。あとはお客様の自助努力で完成です。",
    ),
    _card(
        "meeting-cooled-coffee",
        "会議で冷めた珈琲",
        "C",
        1,
        "二時間の会議で決まったのは、次の会議の日程だけ。珈琲はとっくに冷めていた。",
    ),
    _card(
        "ad-supported-water",
        "広告つき天然水",
        "C",
        1,
        "無料の一杯。味わう前に、卓上広告を何枚かご覧ください。",
    ),
    _card(
        "pending-breakfast",
        "検討中のモーニング",
        "C",
        1,
        "パンと卵の是非を慎重に検討中。珈琲だけ先に冷めていく。",
    ),
    _card(
        "downsized-cream-puff",
        "中身を見直したシュークリーム",
        "C",
        1,
        "おいしさはそのまま。中身だけ、見直しました。",
    ),
    _card(
        "sentiment-boost-latte",
        "お気持ち増量ラテ",
        "C",
        1,
        "増えたのは泡ひとさじと、たいへん丁寧なお気持ち。",
    ),
    _card(
        "uncancellable-tea",
        "解約ページの見つからない紅茶",
        "UC",
        1,
        "一杯で始められるが、飲み終えるには長い手続きがいるらしい。",
    ),
    _card(
        "subscription-sugar-cube",
        "定額制角砂糖",
        "UC",
        1,
        "今月分は角砂糖一個。追加分は次回更新までお待ちください。",
    ),
    _card(
        "ai-manager-blend",
        "AI店長のおすすめブレンド",
        "UC",
        1,
        "三案を分析した結果、どれも同じ味に最適化された。",
    ),
    _card(
        "five-star-hot-water",
        "口コミ星五つの白湯",
        "UC",
        1,
        "星は五つ、味は白湯。評価欄だけがよく温まっている。",
    ),
    _card(
        "mindful-instant-potage",
        "丁寧な暮らしの即席ポタージュ",
        "UC",
        1,
        "粉末一袋を、花と銀皿と深呼吸で丁寧に仕上げた。",
    ),
    _card(
        "compliance-cookie",
        "コンプライアンス・クッキー",
        "UC",
        1,
        "角を落とし、長さを測り、誰にも引っかからない味になった。",
    ),
    _card(
        "hollowed-out-mille-feuille",
        "中抜きミルフィーユ",
        "R",
        1,
        "外周は立派。切ってみると、中央だけ効率よく抜かれている。",
    ),
    _card(
        "trickle-down-coffee",
        "トリクルダウン・コーヒー",
        "R",
        1,
        "上のポットは満杯。下のカップには、いつか一滴が届く予定。",
    ),
    _card(
        "invisible-hand-kneaded-bread",
        "見えざる手ごねパン",
        "R",
        1,
        "店主は触っていないと言う。粉の手形も、そう言っている。",
    ),
    _card(
        "rating-economy-latte",
        "評価経済ラテ",
        "R",
        1,
        "星を五つ浮かべれば、味の説明は短くて済む。",
    ),
    _card(
        "outrage-roast-coffee",
        "炎上焙煎珈琲",
        "R",
        1,
        "少し焦げた話題を、いちばん熱いうちにどうぞ。",
    ),
    _card(
        "endless-growth-pancakes",
        "無限成長パンケーキ",
        "SR",
        1,
        "前の皿より高く積めば、成長していることになるらしい。",
    ),
    _card(
        "authority-approved-hot-water",
        "世界的権威監修の白湯",
        "SR",
        1,
        "三人の権威が監修した、たいへん根拠のあるお湯。",
    ),
    _card(
        "premium-ordinary-water",
        "プレミアム普通水",
        "SR",
        1,
        "箱とリボンと証明書を外すと、よく冷えた普通の水。",
    ),
    # 追加常設: 世界の喫茶文化と、忘れられた一杯・一皿（30種）
    _card(
        "toast-water",
        "トースト・ウォーター",
        "C",
        1,
        "焼いたパンを湯に浸して香りを移す。珈琲豆は最後まで来なかった。",
    ),
    _card(
        "fig-coffee",
        "いちじくコーヒー",
        "C",
        1,
        "焙煎した乾燥いちじくを煮出す。豆なし珈琲界にも果実派がいた。",
    ),
    _card(
        "bark-bread",
        "樹皮パン",
        "C",
        1,
        "穀粉に内樹皮の粉を混ぜた、北方の暮らしを支えたパン。",
    ),
    _card(
        "yesterday-bread-pudding",
        "昨日のパンプディング",
        "C",
        1,
        "固くなったパンを卵液で再雇用。二日目にして、やっと主役になった。",
    ),
    _card(
        "katemeshi",
        "かて飯",
        "C",
        1,
        "貴重な米を野菜でかさ増し。具だくさんということにした。",
    ),
    _card(
        "suiton",
        "すいとん",
        "C",
        1,
        "季節の野菜と小麦団子。鍋ひとつで主食と汁物を兼任する。",
    ),
    _card(
        "lemon-barley-water",
        "レモン・バーリーウォーター",
        "UC",
        1,
        "大麦を煮出してレモンを搾る。麦茶とは似ていそうで別の道を歩んだ。",
    ),
    _card(
        "coffee-leaf-tea",
        "コーヒーリーフティー",
        "UC",
        1,
        "実ではなく葉を淹れる。コーヒーノキには、もう一つの飲み方がある。",
    ),
    _card(
        "cacao-husk-tea",
        "カカオハスクティー",
        "UC",
        1,
        "カカオ豆を包んでいた殻を煮出す、軽やかで香ばしい一杯。",
    ),
    _card(
        "boza",
        "ボザ",
        "UC",
        1,
        "穀物を発酵させた、とろりと甘酸っぱいバルカンの飲み物。",
    ),
    _card(
        "egyptian-sobia",
        "エジプトのソビア",
        "UC",
        1,
        "米とココナッツの白い甘味。暑い日のグラスに涼しさを満たす。",
    ),
    _card(
        "sikhye",
        "シッケ",
        "UC",
        1,
        "麦芽の甘みに米粒が浮かぶ、韓国の冷たい伝統飲料。",
    ),
    _card(
        "mors",
        "モルス",
        "UC",
        1,
        "ベリーを煮出した、北東ヨーロッパのルビー色の一杯。",
    ),
    _card(
        "pease-pudding",
        "ピーズ・プディング",
        "UC",
        1,
        "割りえんどう豆を柔らかく煮固める。甘くない方のプディング。",
    ),
    _card(
        "acquacotta",
        "アクアコッタ",
        "UC",
        1,
        "野菜とパンと卵を重ねる、名は『煮た水』のトスカーナ料理。",
    ),
    _card(
        "panzanella",
        "パンツァネッラ",
        "UC",
        1,
        "固くなったパンにトマトとオリーブ油。昨日を夏の一皿へ戻す。",
    ),
    _card(
        "kaffeost",
        "カフェオスト",
        "R",
        1,
        "角切りチーズへ熱い珈琲を注ぐ。最後の一片までスプーンの出番。",
    ),
    _card(
        "champurrado",
        "チャンプラード",
        "R",
        1,
        "カカオとトウモロコシでとろみをつける、メキシコの温かな一杯。",
    ),
    _card(
        "terere",
        "テレレ",
        "R",
        1,
        "冷水と薬草で淹れるマテ茶。暑い日に回し飲むパラグアイの習慣。",
    ),
    _card(
        "noon-chai",
        "ノーンチャイ",
        "R",
        1,
        "塩とミルクを合わせる、カシミール生まれの桃色の茶。",
    ),
    _card(
        "kashmiri-kahwa",
        "カシミール・カフワ",
        "R",
        1,
        "サフランと香辛料、砕いたアーモンドを浮かべた黄金色の茶。",
    ),
    _card(
        "oriental-beauty-tea",
        "東方美人茶",
        "R",
        1,
        "ウンカに吸汁された茶葉が、蜂蜜を思わせる香りへ変わる。",
    ),
    _card(
        "mock-turtle-soup",
        "モックタートルスープ",
        "R",
        1,
        "亀を使わず仔牛などで名物を再現した、英国生まれの模倣スープ。",
    ),
    _card(
        "syllabub",
        "シラバブ",
        "R",
        1,
        "クリームと酒と柑橘を泡立てた、グラスで供する英国の古い甘味。",
    ),
    _card(
        "aged-liubao-tea",
        "陳年六堡茶",
        "SR",
        1,
        "籠で歳月を重ねた黒茶。深い琥珀色に木と土の香りがほどける。",
    ),
    _card(
        "nilgiri-frost-tea",
        "ニルギリ・フロストティー",
        "SR",
        1,
        "南インドの高地で寒期に摘まれる、清涼な香りの希少な紅茶。",
    ),
    _card(
        "old-brown-java",
        "オールド・ブラウン・ジャワ",
        "SR",
        1,
        "長期熟成で豆を褐色へ変えた、丸く深い味わいのジャワ珈琲。",
    ),
    _card(
        "ecuador-typica-mejorado",
        "エクアドル ティピカ・メホラード",
        "SR",
        1,
        "花と果実を思わせる香りで知られる、エクアドル育ちの希少品種。",
    ),
    _card(
        "nesselrode-pudding",
        "ネッセルロード・プディング",
        "SR",
        1,
        "栗とクリームと果実を凍らせた、外交官の名を持つ優雅な冷菓。",
    ),
    _card(
        "pompeii-panis-quadratus",
        "復元・パニス・クアドラトゥス",
        "SSR",
        1,
        "ポンペイに残った炭化パンを手がかりに蘇る、八つ割りの円形パン。",
    ),
    # UR: 史料に残る人物と一杯・ひと皿（5種 / 0.08%）
    _card(
        "beethoven-sixty-bean-coffee",
        "ベートーヴェンの六十粒珈琲",
        "UR",
        1,
        "一杯ぶんの豆を六十粒ずつ数えたと伝わる、作曲家の几帳面な珈琲。",
    ),
    _card(
        "louis-xv-hot-chocolate",
        "ルイ15世の自家製ショコラ",
        "UR",
        1,
        "王自身が作ることもあったという、卵を用いた濃厚なショコラ。",
    ),
    _card(
        "jefferson-manuscript-ice-cream",
        "ジェファーソン手稿のアイスクリーム",
        "UR",
        1,
        "本人の筆跡で処方が残った、バニラと卵黄のアイスクリーム。",
    ),
    _card(
        "dickinson-window-gingerbread",
        "ディキンソンの窓辺のジンジャーブレッド",
        "UR",
        1,
        "近所の子どもたちへ籠で下ろしたという、詩人の生姜菓子。",
    ),
    _card(
        "balzac-midnight-coffee",
        "バルザックの夜更かし珈琲",
        "UR",
        1,
        "珈琲の効き目を自ら論じた、小説家の夜を支えた濃い一杯。",
    ),
    # 幻: 現物が収蔵・保存された一度きりの食の遺物（3種 / 0.02%）
    _card(
        "last-mother-tree-da-hong-pao",
        "最後の母樹大紅袍・二十グラム",
        "MYTHIC",
        1,
        "2005年の最終摘採品から、国家博物館へ収蔵された二十グラム。",
    ),
    _card(
        "boston-harbor-tea-vial",
        "ボストン港から拾われた茶葉",
        "MYTHIC",
        1,
        "1773年の翌朝に拾われたと伝わる、小瓶の茶葉。真偽ごと歴史になった。",
    ),
    _card(
        "antarctic-century-fruitcake",
        "南極に眠る百年フルーツケーキ",
        "MYTHIC",
        1,
        "スコット隊ゆかりとみられる、缶と氷雪に守られた約百年前の菓子。",
    ),
)


def _rebalance_card_weights(cards: tuple[CafeCard, ...]) -> tuple[CafeCard, ...]:
    """レアリティ率を変えず、同一レアリティ内をほぼ均等に配分する。"""
    balanced: list[CafeCard] = []
    for rarity in RARITY_ORDER:
        group = [card for card in cards if card.rarity == rarity]
        if rarity in LEGACY_RARITY_TOTAL_WEIGHTS:
            base, remainder = divmod(LEGACY_RARITY_TOTAL_WEIGHTS[rarity], len(group))
            scale = LEGACY_WEIGHT_SCALE
        else:
            base, remainder = divmod(RARITY_TOTAL_WEIGHTS[rarity], len(group))
            scale = 1
        balanced.extend(
            replace(card, weight=(base + (index < remainder)) * scale)
            for index, card in enumerate(group)
        )
    return tuple(balanced)


CARDS = _rebalance_card_weights(CARDS)
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
        "pettuleipa",
        "horsebread",
        "turnip-winter-stew",
        "nettle-soup",
        "water-gruel",
        "chestnut-polenta",
        "tsampa",
        "mamaliga",
        "migas",
        "portable-soup",
        "shimeji-hill",
        "chikuwa-village",
        "unbroken-biscuit-sticks",
        "capybara-break",
        "mistaken-donuts",
        "sure-to-break-wafer",
        "emperors-rich-cup",
        "shrinkflation-sandwich",
        "self-help-soup",
        "pending-breakfast",
        "downsized-cream-puff",
        "subscription-sugar-cube",
        "mindful-instant-potage",
        "compliance-cookie",
        "hollowed-out-mille-feuille",
        "invisible-hand-kneaded-bread",
        "endless-growth-pancakes",
        "bark-bread",
        "yesterday-bread-pudding",
        "katemeshi",
        "suiton",
        "pease-pudding",
        "acquacotta",
        "panzanella",
        "mock-turtle-soup",
        "syllabub",
        "nesselrode-pudding",
        "pompeii-panis-quadratus",
        "jefferson-manuscript-ice-cream",
        "dickinson-window-gingerbread",
        "antarctic-century-fruitcake",
    }
)
CARD_KEYS_BY_TAG: dict[CafeCardTag, frozenset[str]] = {
    "coffee": frozenset(
        {
            "sunflower-coffee",
            "acorn-coffee",
            "convenience-coffee",
            "instant-coffee",
            "dandelion-coffee",
            "drink-bar-coffee",
            "payday-eve-blend",
            "meeting-cooled-coffee",
            "sentiment-boost-latte",
            "fig-coffee",
            "barley-chicory-coffee",
            "vietnamese-iced-coffee",
            "turkish-coffee",
            "vietnamese-egg-coffee",
            "kopi-joss",
            "ai-manager-blend",
            "coffee-leaf-tea",
            "house-blend",
            "brazil-santos-no2",
            "brazil-yellow-bourbon",
            "colombia-supremo",
            "guatemala-antigua",
            "costa-rica-tarrazu",
            "ethiopia-yirgacheffe-g1",
            "ethiopia-sidamo-g1",
            "ethiopia-harrar",
            "kenya-aa",
            "tanzania-kilimanjaro-aa",
            "sumatra-mandheling-g1",
            "sulawesi-toraja",
            "monsooned-malabar",
            "qishr",
            "mazagran",
            "cafe-de-olla",
            "bicerin",
            "stardust-cream-latte",
            "trickle-down-coffee",
            "rating-economy-latte",
            "outrage-roast-coffee",
            "kaffeost",
            "jamaica-blue-mountain-no1",
            "hawaii-kona-extra-fancy",
            "yemen-mocha-matari",
            "panama-geisha",
            "kenya-sl28",
            "einspanner",
            "wiener-melange",
            "cafe-touba",
            "old-brown-java",
            "ecuador-typica-mejorado",
            "wild-kopi-luwak",
            "elephant-coffee",
            "st-helena-bourbon",
            "beethoven-sixty-bean-coffee",
            "balzac-midnight-coffee",
        }
    ),
    "tea": frozenset(
        {
            "spent-tea",
            "cold-black-tea",
            "100-yen-black-tea",
            "sale-tea-bags",
            "mugicha",
            "rooibos-tea",
            "honey-tea",
            "mint-tea",
            "sachet-chai",
            "morning-tea",
            "genmaicha",
            "english-breakfast",
            "assam-ctc",
            "jasmine-tea",
            "sencha",
            "hojicha",
            "masala-chai",
            "teh-tarik",
            "thai-iced-tea",
            "hong-kong-milk-tea",
            "moroccan-mint-tea",
            "tibetan-butter-tea",
            "uncancellable-tea",
            "coffee-leaf-tea",
            "cacao-husk-tea",
            "earl-grey",
            "hojicha-latte",
            "goishicha",
            "awabancha",
            "batabatacha",
            "terere",
            "noon-chai",
            "kashmiri-kahwa",
            "oriental-beauty-tea",
            "blooming-tea",
            "darjeeling-first-flush",
            "darjeeling-second-flush",
            "ceylon-uva",
            "keemun",
            "lapsang-souchong",
            "longjing",
            "tieguanyin",
            "da-hong-pao",
            "hon-gyokuro",
            "east-frisian-tea",
            "aged-liubao-tea",
            "nilgiri-frost-tea",
            "legendary-tea-leaves",
            "golden-tea-set",
            "last-mother-tree-da-hong-pao",
            "boston-harbor-tea-vial",
        }
    ),
    "sweets": frozenset(
        {
            "discount-roll-cake",
            "100-yen-cookie",
            "convenience-anpan",
            "jam-toast",
            "unbroken-biscuit-sticks",
            "downsized-cream-puff",
            "scone",
            "coffee-jelly",
            "custard-pudding",
            "dorayaki",
            "cinnamon-roll",
            "mistaken-donuts",
            "sure-to-break-wafer",
            "subscription-sugar-cube",
            "compliance-cookie",
            "canele",
            "basque-cheesecake",
            "mont-blanc",
            "lemon-drizzle-cake",
            "fruit-tart",
            "hollowed-out-mille-feuille",
            "syllabub",
            "afternoon-tea-set",
            "wagashi-assortment",
            "sachertorte",
            "opera-cake",
            "mille-feuille",
            "kouign-amann",
            "emperors-rich-cup",
            "endless-growth-pancakes",
            "nesselrode-pudding",
            "jefferson-manuscript-ice-cream",
            "dickinson-window-gingerbread",
            "antarctic-century-fruitcake",
        }
    ),
    "culture": frozenset(
        {
            "k-pan",
            "sunflower-coffee",
            "acorn-coffee",
            "hardtack",
            "national-loaf",
            "kommissbrot",
            "dandelion-coffee",
            "woolton-pie",
            "pettuleipa",
            "horsebread",
            "turnip-winter-stew",
            "nettle-soup",
            "water-gruel",
            "chestnut-polenta",
            "toast-water",
            "fig-coffee",
            "bark-bread",
            "yesterday-bread-pudding",
            "katemeshi",
            "suiton",
            "barley-chicory-coffee",
            "masala-chai",
            "teh-tarik",
            "thai-iced-tea",
            "hong-kong-milk-tea",
            "vietnamese-iced-coffee",
            "turkish-coffee",
            "vietnamese-egg-coffee",
            "moroccan-mint-tea",
            "tibetan-butter-tea",
            "kaya-toast",
            "kopi-joss",
            "tsampa",
            "mamaliga",
            "migas",
            "portable-soup",
            "posca",
            "lemon-barley-water",
            "coffee-leaf-tea",
            "cacao-husk-tea",
            "boza",
            "egyptian-sobia",
            "sikhye",
            "mors",
            "pease-pudding",
            "acquacotta",
            "panzanella",
            "monsooned-malabar",
            "goishicha",
            "awabancha",
            "batabatacha",
            "qishr",
            "mazagran",
            "cafe-de-olla",
            "bicerin",
            "kaffeost",
            "champurrado",
            "terere",
            "noon-chai",
            "kashmiri-kahwa",
            "oriental-beauty-tea",
            "mock-turtle-soup",
            "syllabub",
            "afternoon-tea-set",
            "yemen-mocha-matari",
            "east-frisian-tea",
            "einspanner",
            "wiener-melange",
            "cafe-touba",
            "aged-liubao-tea",
            "old-brown-java",
            "nesselrode-pudding",
            "st-helena-bourbon",
            "pompeii-panis-quadratus",
            "beethoven-sixty-bean-coffee",
            "louis-xv-hot-chocolate",
            "jefferson-manuscript-ice-cream",
            "dickinson-window-gingerbread",
            "balzac-midnight-coffee",
            "last-mother-tree-da-hong-pao",
            "boston-harbor-tea-vial",
            "antarctic-century-fruitcake",
        }
    ),
}
CARD_TAGS_BY_KEY: dict[str, frozenset[CafeCardTag]] = {
    key: frozenset(tag for tag, keys in CARD_KEYS_BY_TAG.items() if key in keys)
    for key in CARDS_BY_KEY
}
CARDS_BY_RARITY: dict[Rarity, tuple[CafeCard, ...]] = {
    rarity: tuple(card for card in CARDS if card.rarity == rarity)
    for rarity in RARITY_ORDER
}

if len(CARDS) != 192:
    raise RuntimeError("cafe gacha catalog must contain exactly 192 cards")
if len(CARDS_BY_KEY) != len(CARDS):
    raise RuntimeError("cafe gacha card keys must be unique")
if len(FOOD_CARD_KEYS) != 70 or not CARDS_BY_KEY.keys() >= FOOD_CARD_KEYS:
    raise RuntimeError("cafe gacha catalog must contain exactly 70 food cards")
if any(not CARDS_BY_KEY.keys() >= keys for keys in CARD_KEYS_BY_TAG.values()):
    raise RuntimeError("cafe gacha card tags must reference existing cards")
if sum(card.weight for card in CARDS) != TOTAL_WEIGHT:
    raise RuntimeError("cafe gacha weights must total 150,000")
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
    """0..149999 の値を固定抽選表へ写像する。境界テスト用の純粋関数。"""
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
