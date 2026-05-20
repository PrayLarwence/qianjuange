"""HP 七部曲骨架模板 seed。

只填：世界观规则、公开人物身份卡、地点功能、章节段落标题（如开学/寒假/期末）。
不填：具体情节节点、场景描写、对白、原文段落。
具体剧情节点请用户在 UI 模板编辑器里手动填入。

用法：
  cd backend
  python -m scripts.seed_hp           # 幂等插入或更新
  python -m scripts.seed_hp --reset   # 删除后重插
"""
from __future__ import annotations
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import init_db, SessionLocal, WorldTemplate

SERIES = "哈利波特"
CATEGORY = "魔法奇幻 · 哈利波特"

COMMON_CORE_RULES = [
    "麻瓜世界与巫师世界平行存在，魔法部维持隔离",
    "霍格沃茨四学院：格兰芬多 / 斯莱特林 / 拉文克劳 / 赫奇帕奇",
    "魁地奇是巫师世界的主流体育运动",
    "巫师货币：金加隆 / 银西可 / 铜纳特",
    "魔法浓度高的场所电子产品会失灵",
    "魔杖材质与杖芯决定使用者的契合度",
]

COMMON_FORBIDDEN = [
    "禁止照搬或微改原文段落、对白、独特表述",
    "AI 生成的所有叙事必须是全新原创句子",
    "禁止违反魔法世界基本设定（麻瓜不可随意得知魔法）",
]

CHAPTER_LIKE_OUTLINE = [
    {"beat": "暑假在麻瓜世界"},
    {"beat": "前往学校"},
    {"beat": "开学典礼"},
    {"beat": "课程与日常"},
    {"beat": "万圣节"},
    {"beat": "魁地奇赛季"},
    {"beat": "圣诞假期"},
    {"beat": "新学期"},
    {"beat": "复活节"},
    {"beat": "期末高潮事件"},
    {"beat": "学年结束"},
]


def make_tpl(idx: int, **kw) -> dict:
    return {
        "series": SERIES, "series_order": idx,
        "category": CATEGORY, "is_official": True,
        "tags": ["哈利波特", "魔法奇幻", f"HP{idx}"] + kw.pop("extra_tags", []),
        "max_steps_hint": kw.pop("max_steps_hint", 25),
        "canonical_outline": kw.pop("canonical_outline", CHAPTER_LIKE_OUTLINE),
        **kw,
    }


CORE_CHARS = [
    {"type": "character", "name": "哈利·波特",
     "summary": "主角，绿眼睛黑发男孩，额头有闪电形伤疤。",
     "attributes": {"魔杖": "冬青木 凤凰羽毛芯", "学院": "格兰芬多"}},
    {"type": "character", "name": "罗恩·韦斯莱",
     "summary": "哈利的好友，红头发雀斑，纯血巫师家族出身。",
     "attributes": {"学院": "格兰芬多"}},
    {"type": "character", "name": "赫敏·格兰杰",
     "summary": "哈利的好友，麻瓜出身，成绩优异。",
     "attributes": {"学院": "格兰芬多"}},
    {"type": "character", "name": "阿不思·邓布利多",
     "summary": "霍格沃茨校长，巫师界德高望重的人物。",
     "attributes": {}},
    {"type": "character", "name": "西弗勒斯·斯内普",
     "summary": "霍格沃茨教授，黑发钩鼻、阴沉。",
     "attributes": {}},
    {"type": "character", "name": "米勒娃·麦格",
     "summary": "霍格沃茨副校长兼变形术教授。",
     "attributes": {"学院": "格兰芬多"}},
    {"type": "character", "name": "鲁伯·海格",
     "summary": "霍格沃茨钥匙保管员与场地看守，半巨人。",
     "attributes": {}},
    {"type": "character", "name": "德拉科·马尔福",
     "summary": "斯莱特林学生，纯血贵族家族出身。",
     "attributes": {"学院": "斯莱特林"}},
    {"type": "character", "name": "纳威·隆巴顿",
     "summary": "格兰芬多学生，胆小，由祖母抚养长大。",
     "attributes": {"学院": "格兰芬多"}},
    {"type": "character", "name": "金妮·韦斯莱",
     "summary": "罗恩的妹妹，韦斯莱家最小的孩子。",
     "attributes": {"学院": "格兰芬多"}},
    {"type": "character", "name": "弗雷德与乔治·韦斯莱",
     "summary": "罗恩的双胞胎哥哥，恶作剧高手。",
     "attributes": {"学院": "格兰芬多"}},
]

CORE_LOCATIONS = [
    {"type": "location", "name": "霍格沃茨魔法学校",
     "summary": "苏格兰高地的魔法寄宿学校，四学院制。",
     "attributes": {"特征": "活动楼梯、画中人会串门、有求必应屋、黑湖、禁林"}},
    {"type": "location", "name": "对角巷",
     "summary": "伦敦的隐藏巫师商业街，需通过破釜酒吧后院进入。",
     "attributes": {}},
    {"type": "location", "name": "9¾ 站台",
     "summary": "国王十字车站的隐藏巫师月台，前往学校的列车从此发车。",
     "attributes": {}},
    {"type": "location", "name": "霍格莫德村",
     "summary": "学校附近的全巫师村庄，三年级以上学生周末可去。",
     "attributes": {}},
    {"type": "location", "name": "魔法部",
     "summary": "英国魔法管理机构，位于伦敦地下。",
     "attributes": {}},
]


def book(idx: int, name: str, emoji: str, year: str, tone: str,
         description: str, long_description: str,
         extra_rules=None, extra_forbidden=None, extra_chars=None) -> dict:
    rules = {
        "tone": tone,
        "language": "中文",
        "core_rules": COMMON_CORE_RULES + (extra_rules or []),
        "forbidden": COMMON_FORBIDDEN + (extra_forbidden or []),
        "notes": "称呼用通行中译名。",
    }
    return make_tpl(idx,
        name=name, cover_emoji=emoji,
        description=description,
        long_description=f"原作时间设定：{year}。\n\n{long_description}",
        rules=rules,
        seed_directive="（请在模板编辑器里填写本部的开局指令；或直接在推演框里输入想要的开场。）",
        suggested_steps=[],
        seed_entities=CORE_CHARS + CORE_LOCATIONS + (extra_chars or []),
    )


HP1 = book(1, "哈利波特 1：魔法石", "🪄", "1991-1992 学年",
    tone="童趣 / 初探奇境 / 温暖友情",
    description="哈利第一次踏进魔法世界，与罗恩、赫敏建立友情，初探霍格沃茨的奇景。",
    long_description=(
        "调性偏童趣温暖，邪恶的阴影遥远。"
        "这是初探魔法世界的篇章，重点是新奇感、初识朋友、初识老师。\n\n"
        "用法建议：把节点目录改成你想要的具体事件，"
        "或留空让 AI 自由创作开学到学年末的故事。"
    ),
    extra_rules=["哈利此时 11 岁，霍格沃茨一年级新生"],
    extra_forbidden=["哈利此时魔法实力很弱，常摔下扫帚"],
)

HP2 = book(2, "哈利波特 2：密室", "🐍", "1992-1993 学年",
    tone="悬疑 / 古老恐惧 / 校园秘事",
    description="二年级。学校古老黑历史浮出水面，悬疑氛围浓重。",
    long_description=(
        "调性比第一部更阴森，恐惧从无名走向具象。"
        "悬疑路线为主，校园生活为辅。"
    ),
    extra_rules=["哈利二年级", "蛇佬腔（与蛇说话）被巫师视为黑巫师标志"],
)

HP3 = book(3, "哈利波特 3：阿兹卡班的囚徒", "🦌", "1993-1994 学年",
    tone="阴郁 / 内省 / 父辈秘密",
    description="三年级。哈利开始真正接触父辈的过往，故事进入更深的情感层。",
    long_description=(
        "调性更内省、阴郁。本部首次大量铺开父辈线索，"
        "开始触及'谁是真正的朋友、谁是真正的敌人'的复杂判断。"
    ),
    extra_rules=[
        "哈利三年级，可周末去霍格莫德",
        "摄魂怪：阿兹卡班的守卫，吸食快乐情绪",
        "守护神咒（呼神护卫）是抵御摄魂怪的标准咒语",
        "阿尼马格斯：能变成动物形态的注册巫师",
    ],
)

HP4 = book(4, "哈利波特 4：火焰杯", "🔥", "1994-1995 学年",
    tone="国际盛事 / 紧张转折 / 黑暗回归",
    description="四年级。三巫斗法大赛 + 国际魔法社群，结尾迎来重大转折。",
    long_description=(
        "调性从校园冒险扩展到国际魔法社群。"
        "前半段是盛事与少年情愫，后半段陡转。"
        "这是整个系列的转折点。"
    ),
    extra_rules=[
        "哈利四年级",
        "三巫斗法大赛：每七年一次的三所巫师学校竞赛",
        "三所学校：霍格沃茨 / 布斯巴顿 / 德姆斯特朗",
        "不可饶恕咒（夺魂、钻心、阿瓦达索命）使用违法",
    ],
)

HP5 = book(5, "哈利波特 5：凤凰社", "🦅", "1995-1996 学年",
    tone="压抑 / 反抗 / 制度之恶",
    description="五年级。魔法部插手学校，哈利在压抑中组织地下社团。",
    long_description=(
        "调性最压抑、最愤怒的一部。"
        "外部威胁是隐藏的，更直接的对抗来自掌权者的麻木与打压。"
        "学生开始自发组织反抗，凤凰社作为成年人的抵抗组织也活跃起来。"
    ),
    extra_rules=[
        "哈利五年级，是 OWL 考试年",
        "凤凰社：邓布利多领导的反抗组织",
        "魔法部正在通过媒体抹黑哈利与邓布利多",
        "预言厅藏有大量预言球",
    ],
)

HP6 = book(6, "哈利波特 6：混血王子", "💍", "1996-1997 学年",
    tone="哀伤的成长 / 私密回忆 / 阴影逼近",
    description="六年级。哈利通过冥想盆深入研究敌人的过去，朋友们各有心事。",
    long_description=(
        "调性沉静哀伤，本部更多是'之前章节信息的整理与揭开'。"
        "校园里少年情愫成熟，校园外的战争阴影越来越近。"
    ),
    extra_rules=[
        "哈利六年级",
        "冥想盆可让人进入他人记忆",
        "魂器：将灵魂分割并寄存于物品的黑魔法",
    ],
)

HP7 = book(7, "哈利波特 7：死亡圣器", "⚰️", "1997-1998 年",
    tone="逃亡 / 抉择 / 终局",
    description="第七部。三人离开学校踏上漫长的追寻与逃亡之旅，迎来终局之战。",
    long_description=(
        "调性是公路片式的逃亡 + 终局对决。"
        "故事大部分时间不在学校。"
        "重点是抉择、信任、牺牲，以及童话级别的'死亡圣器'传说。"
    ),
    extra_rules=[
        "本部主体不在霍格沃茨发生，主角们在外漂泊",
        "魔法部已被敌方渗透",
        "死亡圣器：传说中的三件神器（老魔杖 / 复活石 / 隐形衣）",
    ],
)

ALL_TEMPLATES = [HP1, HP2, HP3, HP4, HP5, HP6, HP7]


def upsert(db, payload: dict, *, reset_only: bool = False) -> str:
    existing = db.query(WorldTemplate).filter_by(
        series=SERIES, series_order=payload["series_order"], is_official=1,
    ).first()
    if reset_only:
        if existing:
            db.delete(existing)
            return f"删除 {payload['name']}"
        return f"跳过 {payload['name']}（不存在）"
    if existing:
        for k in ("name", "description", "long_description", "cover_emoji", "rules",
                  "seed_directive", "suggested_steps", "seed_entities",
                  "canonical_outline", "max_steps_hint", "tags",
                  "category", "series", "series_order"):
            setattr(existing, k, payload.get(k, getattr(existing, k)))
        existing.is_official = 1
        return f"更新 {payload['name']} ({existing.id})"
    t = WorldTemplate(
        id=f"tpl_{uuid.uuid4().hex[:10]}",
        name=payload["name"], category=payload["category"],
        description=payload["description"], long_description=payload["long_description"],
        cover_emoji=payload["cover_emoji"], rules=payload["rules"],
        seed_directive=payload["seed_directive"],
        suggested_steps=payload["suggested_steps"],
        seed_entities=payload["seed_entities"],
        canonical_outline=payload["canonical_outline"],
        series=payload["series"], series_order=payload["series_order"],
        max_steps_hint=payload["max_steps_hint"],
        tags=payload["tags"], author="system", is_official=1,
    )
    db.add(t)
    return f"插入 {payload['name']} ({t.id})"


def main():
    reset = "--reset" in sys.argv
    init_db()
    db = SessionLocal()
    try:
        if reset:
            for tpl_data in ALL_TEMPLATES:
                print("  ", upsert(db, tpl_data, reset_only=True))
            db.commit()
            db = SessionLocal()
        for tpl_data in ALL_TEMPLATES:
            print("  ", upsert(db, tpl_data, reset_only=False))
        db.commit()
        print(f"\n完成。共 {len(ALL_TEMPLATES)} 个模板。")
    finally:
        db.close()


if __name__ == "__main__":
    main()
