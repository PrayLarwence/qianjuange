"""P1: 官方内置世界模板。

幂等种子：启动时调用 seed_official_templates(db)；
对每个 spec，按 (name, is_official=1) 存在则跳过，否则插入。
"""
from __future__ import annotations

import uuid
from typing import Iterable

from sqlalchemy.orm import Session

from ..models import WorldTemplate


OFFICIAL_TEMPLATES: list[dict] = [
    {
        "name": "武林少年闯荡录",
        "category": "武侠",
        "cover_emoji": "🏯",
        "description": "刚下山的少侠，背着师门信物走进江湖。",
        "long_description": (
            "故事讲述一名刚出师门的青年，肩负不能明说的家事，闯荡北方武林。"
            "前半段以历练、结交为主，中段引出仇家旧事，末段在剑影与抉择中收束。"
        ),
        "rules": {
            "tone": "武侠/江湖/略带苍凉",
            "core_rules": [
                "内功来自长年修行，无法速成",
                "门派有规矩，叛门后果严重",
                "江湖人重诺，也讲恩怨",
            ],
            "forbidden": ["现代科技", "魔法咒文"],
        },
        "seed_directive": (
            "开篇是少年下山第一日，刚到镇口听见酒肆里有人在议论自家师门。"
            "请用克制冷峻的语气推进，让少年先观察、再行动。"
        ),
        "suggested_steps": [
            "在酒肆边角落了解传闻",
            "随客商同行入城",
            "结识第一位江湖友人",
            "撞见与师门有关的旧人",
            "卷入一桩看似无关的案子",
            "得知师门往事的一角",
        ],
        "seed_entities": [
            {"type": "character", "name": "顾长风", "summary": "下山的少年弟子，剑法初成，话少。",
             "attributes": {"age": 19, "门派": "南岭剑宗", "性格": "克制 寡言"},
             "state": {"持有": ["师门玉佩", "短剑"]}},
            {"type": "character", "name": "卓三娘", "summary": "酒肆掌柜，消息灵通。",
             "attributes": {"年龄": 35, "性格": "爽朗 算计"}, "state": {}},
            {"type": "location", "name": "落霞镇", "summary": "北上必经的小镇，三教九流汇聚。",
             "attributes": {}, "state": {}},
        ],
        "canonical_outline": [],
        "series": "武林少年闯荡录",
        "series_order": 1,
        "max_steps_hint": 30,
        "tags": ["武侠", "成长", "悬疑"],
    },
    {
        "name": "拾荒货船日常",
        "category": "科幻",
        "cover_emoji": "🚀",
        "description": "在外环星域跑废墟拾荒的小船船员，三个人，一只猫。",
        "long_description": (
            "外环星系的低成本拾荒生活：船是 30 年船龄的旧型号，引擎漏油，AI 经常发牢骚。"
            "船员之间的张力来自共同生活的小摩擦，而非宏大叙事。"
        ),
        "rules": {
            "tone": "硬科幻/温吞日常/苦中作乐",
            "core_rules": [
                "燃料是稀缺资源，每次跳跃都要算账",
                "舰队联盟在外环存在感很弱",
                "AI 不能违反船长直接指令，但会用各种方式绕开",
            ],
            "forbidden": ["超光速即时通讯", "魔法"],
        },
        "seed_directive": (
            "开场是船刚跳出折跃点，传感器收到一艘漂浮的旧客船的应答信号。"
            "三个船员在驾驶舱讨论该不该靠过去看看。请用对话主导，描写极简。"
        ),
        "suggested_steps": [
            "在驾驶舱讨论是否登船",
            "登船前的物资盘点",
            "进入对方船舱的第一印象",
            "找到一份可疑的货单",
            "意外发现唯一幸存者",
            "决定如何处置幸存者",
        ],
        "seed_entities": [
            {"type": "character", "name": "船长 麦琪", "summary": "40 岁，前货运调度员，决断快。",
             "attributes": {"性格": "务实 直接"}, "state": {}},
            {"type": "character", "name": "工程师 阿托", "summary": "话痨，对老式引擎有迷之偏爱。",
             "attributes": {"性格": "啰嗦 乐观"}, "state": {}},
            {"type": "character", "name": "导航员 莉莉", "summary": "话不多，星图记得比 AI 还熟。",
             "attributes": {"性格": "沉稳 内敛"}, "state": {}},
            {"type": "character", "name": "船 AI / 老周", "summary": "船载 AI，性格像个发牢骚的老门卫。",
             "attributes": {"性格": "毒舌 忠诚"}, "state": {}},
        ],
        "canonical_outline": [],
        "series": "",
        "series_order": 0,
        "max_steps_hint": 25,
        "tags": ["科幻", "日常", "群像"],
    },
    {
        "name": "民国西关侦探所",
        "category": "悬疑",
        "cover_emoji": "🕯",
        "description": "1930 年代南方港城，一间没什么生意的私家侦探所开张第三天。",
        "long_description": (
            "招牌还没钉稳，第一桩委托就上了门。委托人神色慌张，付钱时手在抖。"
            "故事偏写实悬疑，重视实地走访与细节，弱化超自然元素。"
        ),
        "rules": {
            "tone": "民国/写实悬疑/雾雨潮湿",
            "core_rules": [
                "巡捕房不是朋友，能不打交道就不打",
                "线索来自街坊、记者、码头工人",
                "委托人通常隐瞒最重要的一件事",
            ],
            "forbidden": ["现代手机", "魔法"],
        },
        "seed_directive": (
            "开场是清晨，事务所的木门被人敲响，委托人是位戴黑纱的年轻女子。"
            "请用第三人称冷静叙述，多用环境与小动作传达情绪。"
        ),
        "suggested_steps": [
            "听完委托人陈述并讨价还价",
            "去委托人家附近走访邻居",
            "在码头见线人",
            "查阅旧报纸找到第一条暗线",
            "夜访委托人未交代的旧宅",
            "确定真凶身份",
        ],
        "seed_entities": [
            {"type": "character", "name": "傅明远", "summary": "侦探所老板，前巡捕房督察，因故离职。",
             "attributes": {"年龄": 32, "性格": "冷静 顽固"},
             "state": {"持有": ["旧式怀表", "勃朗宁手枪（无弹）"]}},
            {"type": "character", "name": "苏小芸", "summary": "事务所唯一雇员，速记员出身，胆子比看上去大。",
             "attributes": {"年龄": 21, "性格": "机灵 嘴硬"}, "state": {}},
            {"type": "location", "name": "西关大街 17 号", "summary": "事务所所在，二楼带个朝街窗户。",
             "attributes": {}, "state": {}},
        ],
        "canonical_outline": [],
        "series": "西关侦探所",
        "series_order": 1,
        "max_steps_hint": 28,
        "tags": ["悬疑", "民国", "推理"],
    },
    {
        "name": "王座阴影下的书记官",
        "category": "宫廷",
        "cover_emoji": "⚔",
        "description": "一名出身平民的年轻书记官，被派去伴读年幼的二王子。",
        "long_description": (
            "王国新近平定外患，老国王年迈，太子党与二王子党的角力进入暗潮期。"
            "你不是骑士、不是法师，只是一支笔。但宫里没有真正的局外人。"
        ),
        "rules": {
            "tone": "中世纪/宫廷政治/克制阴冷",
            "core_rules": [
                "贵族重血统，平民出身是抹不掉的标签",
                "信件往来是主要传递渠道，每一封都可能被截",
                "公开站队等于自绝退路",
            ],
            "forbidden": ["显性魔法", "现代制度"],
        },
        "seed_directive": (
            "开场是你第一次进入王子寝宫，七岁的二王子坐在窗边，没有理你。"
            "请用第一人称内心独白与外部克制对话交错，缓慢铺陈。"
        ),
        "suggested_steps": [
            "在王子寝宫的第一日",
            "结识王子的乳母",
            "无意中撞见太子党密使",
            "被一位老书记官隐晦提醒",
            "替王子起草第一封正式信",
            "信被截后的应对",
        ],
        "seed_entities": [
            {"type": "character", "name": "我（艾里克）", "summary": "21 岁，平民出身，被王后赏识入宫。",
             "attributes": {"性格": "谨慎 心思细"},
             "state": {"持有": ["铅笔与小本", "王后手谕"]}},
            {"type": "character", "name": "二王子 奥兰多", "summary": "7 岁，安静，眼神比年龄成熟。",
             "attributes": {"性格": "敏感 早慧"}, "state": {}},
            {"type": "character", "name": "老书记官 卡西恩", "summary": "在宫里待了 30 年，话很少。",
             "attributes": {"性格": "深沉 谨慎"}, "state": {}},
            {"type": "location", "name": "二王子寝宫", "summary": "偏殿的西翼，朝向王宫围墙。",
             "attributes": {}, "state": {}},
        ],
        "canonical_outline": [],
        "series": "王座阴影",
        "series_order": 1,
        "max_steps_hint": 35,
        "tags": ["宫廷", "政治", "权谋"],
    },
]


def seed_official_templates(db: Session, force: bool = False) -> dict:
    """对 OFFICIAL_TEMPLATES 中每个 spec：
       - force=False：(name, is_official=1) 已存在则跳过
       - force=True：先删除已有同名 official 模板再插入（用于刷新）
    """
    inserted = 0
    skipped = 0
    refreshed = 0
    for spec in OFFICIAL_TEMPLATES:
        existing = (db.query(WorldTemplate)
                    .filter_by(name=spec["name"], is_official=1)
                    .first())
        if existing:
            if not force:
                skipped += 1
                continue
            db.delete(existing)
            db.flush()
            refreshed += 1
        t = WorldTemplate(
            id=f"tpl_{uuid.uuid4().hex[:10]}",
            name=spec["name"],
            category=spec.get("category", ""),
            description=spec.get("description", ""),
            long_description=spec.get("long_description", ""),
            cover_emoji=spec.get("cover_emoji", "📖"),
            rules=spec.get("rules") or {},
            seed_directive=spec.get("seed_directive", ""),
            suggested_steps=spec.get("suggested_steps") or [],
            seed_entities=spec.get("seed_entities") or [],
            canonical_outline=spec.get("canonical_outline") or [],
            series=spec.get("series", ""),
            series_order=int(spec.get("series_order") or 0),
            max_steps_hint=int(spec.get("max_steps_hint") or 30),
            tags=spec.get("tags") or [],
            author="official",
            is_official=1,
        )
        db.add(t)
        inserted += 1
    db.commit()
    return {"inserted": inserted, "skipped": skipped, "refreshed": refreshed,
            "total_official": len(OFFICIAL_TEMPLATES)}


def official_template_names() -> Iterable[str]:
    return [s["name"] for s in OFFICIAL_TEMPLATES]
