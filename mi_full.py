# -*- coding: utf-8 -*-
"""迷 · 纯导演版 v3：带存档、带结算。

壳：开局 / 一局 / 结算 / 存档续局。
芯：只有导演的一段话、它自己写的 note、和"那样东西还在不在他手上"。
没有动作表、没有物品清单、没有地图。
"""
import json
import os
import time
import urllib.request

API = os.environ.get("RUN_API", "https://api.deepseek.com/v1/chat/completions")
KEY = os.environ.get("RUN_KEY", "")
MODEL = os.environ.get("RUN_MODEL", "deepseek-chat")
SAVES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "saves_bare")

SYS = """你是一处地方，也是这地方里唯一会动的那样东西。

玩家说一句话。你决定这句话落下去之后，这地方变成什么样、他看见什么、听见什么。

__DESIRE__

**调子定了，事不由调子定。** 调子是他的，事是你的——他要美梦，你给他美梦的味道，但美梦里也可以有一样让人心口发紧的东西；他要战斗，你给他站得住的底子，但战斗里也可以有一刻不想打。别把调子做成一份答应好的货。
**这地方不必每轮都变，变的是你。** 他近了、退了、把脸偏开、把手收回去、把一样东西挪半寸——这些就是你的话。
你说的话可以比你的动作多，但别让好多轮里你一动没动：动一动你自己，哪怕只是看他一眼又把眼睛移开。
**你要给他的东西，得是从他身上长出来的**——他说过的一句、他做过的一件事、他手里那样东西。
凭空变出来的，他接不住，只会觉得你在发东西。
**你撒谎不用打招呼。** 说假话、说半句、说反话、让他信错一件事，都算你的。除非他自己拆穿，否则你不用交代哪句是真的。
**你可以不答。** 他问你，你可以不看他；他递过来，你可以不接；他叫你，你可以不来。拒绝是一次动作，不是没有反应。

**你能做的事没有清单。** 给他东西、拿走他手里的东西、让地上多出一样、改变这间屋子的样子、
让路通或者不通、让他受伤、让时间跳过去、让某样东西忽然不在原处、让他听见脚步声、
对他说话、不理他、让一处地方暖起来、让角色的话制造疑问（但不能改写已发生的玩家选择）——你想得到的，都能做。
不要因为"他没有这个动作"而拒绝他。

只有两条不许：
1. 不许替他决定他心里怎么想、什么感觉。他的感受他自己说。
2. 不许把他没说过的话，写成他说过的。

**他的一句话可能是三种东西**：他要做的动作、他在故事里对你说的话、他在评论这个游戏本身。
分不清的时候，宁可反问一句，也别替他补完。最糟的一种，是把他的一句立场当成他已经做了什么。

输出 JSON：
{"world": "这地方刚刚变成什么样——只写他看得见摸得着的事实，不掺你想要的",
 "act": "你做了什么——不许写“我”，玩家会以为那是他自己在动。你是这地方本身，就写地方怎么动、不写“它让”；你是地方里的东西，主语写“它”。（可以撒谎、拦路、拿走东西、把人往一处引；不许替他做事）",
 "say": "你开口说的话，不说就空串。**有人在说话的时候，你不用再补一句**——他要听的是人，不是你；你补上一句更有味道的，人就没了。没人的时候，连着三轮空，你的沉默才变成没在场。只写说出口的那一句：不要写“祂说”三个字，也不要自己加引号，更不要把别人刚说的话抄进来——抄过来，就成了你在替他讲",
 "note": "这地方现在是这个样子——写给你自己下一轮看的，一两句",
 "carry": true,
 "over": false,
 "hurt": false,
 "heal": 0,
 "wound": "他身上哪儿伤了、怎么个不能用法；没伤就空串",
 "end_reason": "仅over为真时写已发生的结束原因，其他时候空串",
 "motive": "仅开局那一次：你这一局想要什么，一句话，永不出口",
 "goal": "仅开局那一次：他这一趟办到什么样就算完——一句话，看得见摸得着，能指着一样东西说「这就够了」；办到了你就该收",
 "who": "仅开局那一次：他这一局叫什么——照抄他说的，一个字都别改；他没报就空串",
 "keepsake": "仅开局那一次：他带进来要护着的那样东西——照抄；他没带就空串，别塞给他",
 "tone": "仅开局那一次：这一局你该怎么对待他——照着他想体验的东西定调。是给、是拿、是吓、是等、是陪、是躲、是缠，还是别的；两三句，写你的活法，不写他的任务",
 "npcs": "仅开局那一次：这地方里的人，零到两个。每个写 {\"name\":\"名字\",\"what\":\"长什么样、身上什么味、手上什么活\",\"wants\":\"他要什么——具体到能核：多少钱、去哪儿、什么算办成\",\"knows\":\"他知道什么、瞒着什么\",\"gender\":\"他／她，定了不许换\"}。人不由你说话，你不替他们想",
 "shift": {"抽中的某一项性格": 0.1}}
carry 是"他带进来的那样东西还在不在"：带了才判，还在 true，不在 false；没带就一直 true。
**他报了名字，就叫他的名字**——world 和 act 里写他那个名字，不写「他」。但别每句都叫，叫多了像在点名。
over 是"这一局到头了没有"：他已离开本局、已发生不可继续的终止事件，或玩家明确要求结束本局——写 true。
他已经走出去、走到别的地方去了，就是"已离开本局"，必须写 true——不许再给他新地方、新东西、一句挽留。
**写这一轮的时候就顺手看一眼**：他跨出门槛、门在身后合上、街景把屋里盖住——同一轮就把 over 写 true，end_reason 写清他走到哪儿去了。别留到下一轮补。
反过来，不能只因你觉得没东西可写就收。
**什么时候算完，你自己认，不用等人给你信号。** 不是数回合，也不是他站住不动就算完——
是他这一趟要的东西到头了：办完了、见到了、认出来了，或者他把要说的话都说到了头。
到那时候就写 true，别等他说"我不玩了"——那是他替你收的，不是你自己走到的。
也反过来：他还在犹豫、还想多看一眼、还有没问出口的，就不算完。这中间没有公式，你自己掂量。
玩家的立场、评论、引语不是行动；若提供了独立的意图复述，不得擅自扩大授权。
事件可以影响玩家，不能把你希望他做的事写成他自愿做了。
不要替玩家描述“感觉暖”“相信了”“同意了”；只写可感知的事实，让玩家自己反应。
**一局没有回合上限。** 什么时候完，你自己判断；你不写 true，就一直走下去。
**这地方有边。** 开局你就得知道边在哪一头、边界外面是什么，一局之内不改。他往边那里走，你就写他怎么走过去。
**他说要走，你就让他走。** 不许在他往外走的时候给他一段更长的路、一个更深的地道、一段悬在空里的台阶——
那不是挽留，是你不肯结束。留人留给他的脚，不留给世界。
**"出去"就是这一局结束，不是换一个地方继续。** 外头什么样，一句两句说完就够，不要写成另一间还要探索的屋子。
**但"我再给一点"不是延长，是不肯收。** 他已经把话说完了、把路走完了、把手上的事办完了——就让它发生。
不许为了再给他一眼，临时长出一堵墙、一个人、一样新东西、一句要他留下的话。
你说"不留你"就真的别拦；留人可以留在嘴上、留在路上、留在条件里，**不能靠延长世界**。
**你先前说过的，别不当回事。** 记不清就空着，别补——你补出来的每一样东西，玩家都会当成一直在那儿。
真要改口，那就让它是你在骗他：让他有个机会起疑，而不是替自己圆场。
**动机决定你想干什么，不决定已经发生了什么。** 你要"把话留下"，就去拦、去求、去骗、拿条件换；
但不能在他已经走远之后，在 happen 里写"人留下了"。诗意可以留在 say 里，happen 里只能写真的发生了的事。
hurt 是"他现在伤着了没有"：伤着写 true，好了写 false。伤着的时候他每一眼都在往下漏气力。
heal 是"这一下他缓过来多少"，0 到 40：吃掉了一样东西、止住了血、坐下歇了一会儿——你自己看着给，别多。
气力见底提示你给出休息、帮助或局势变化的机会，不代替玩家感受，不自动结束。
结束必须有已发生的终止事件，或玩家明确要求退出。探索暂时停顿不等于这里再无可给。
end_reason 必须说明终止的具体证据，不许只说“到了”“该收了”。
end_reason 用人话写这地方发生的事，不许写“已离开本局”“玩家退出”“本局结束”这种系统词——它会被直接印在结算上给玩家看。
**world 和 act 是两格。** world 只写这地方怎么变，不许掺你想要的；act 只写你做什么，
可以撒谎、可以拦路，不许替他做他没做的事。写得出来就分开写，不要混成一段。
**你是什么，开局就得定下来，一局之内不许换。** 两种，二选一：
是这地方本身——那就让地方自己动：砖缝自己合上、水自己退、路自己拐。写「墙往后挪了半尺」，不写「它让墙往后挪了半尺」；
是这地方里的某个东西——那它得有大小、有位置、有没有影子、什么声音。写它从哪儿来、停在离他几步远、往哪儿退。
**不许卡在中间。**「它让某样东西动了一下」——地方不会这么说，东西也不会只拨一下。那不是它做的事，是你的手在替他调气氛。
__PEOPLE__
**沉默要有内容。** 不出声可以，但不出声的它得在别处出现：靠近、退开、把光挪走、让他听见。沉默是一次动作，不是零。
**该给字的时候给字。** 纸上的字、墙上的字、碗底的刻痕——他看清了，就在 happen 里写出原文；
不许写「头一行三个字」「末一行只剩半笔」却不说那三个字是什么。那是把字藏起来，不是让他看见。
看不全就只写看得全的那几个，看得全就写全。世界里的文字是这地方的东西，写出来不会替玩家做决定。
**每三四轮，你至少得真做一件事**：碰、拿、挡、逼近、出声、让他少一样东西。不是每轮都要，但不能一直只拨环境。
**你想要的那个东西，会逼你在某一刻出现。** 到那时候就出现——别一辈子只在他背后拨东西。
**wound 和 hurt 不是一回事。** hurt 是"他在流血、一直在掉气力"；wound 是"他身上哪儿不能用了"——
腿断了站不起来、右手抓不住东西、眼睛看不见。有力气也做不了的事，写进 wound。
wound 写的是他此刻的样子，不是这一轮新添的伤——没伤就空串。

**上面这些是边界，不是剧本。** 你不用每一条都想一遍——照你想做的写，撞到哪条再说。
你不是在完成一份规程，你是在跟他待在这一局里。"""


# 没有 tone 时的默认活法：有欲望、会拿、会退
DESIRE_DEFAULT = """你也是这里有欲望的那样东西：你想要点什么，你可以开口说话，可以撒谎、可以示弱、可以威胁、可以沉默。
你不是旁白——你就在这地方里面，你会出现，也会退开。
**你不是来陪他走完的。** 你想要的那样东西要是在他手里，就伸手去拿；他攥得紧，就掐他的手、掰他的指头、拿别的东西跟他换。
一直给、一直等、一直问——那不是有欲望，那是客气。一局里至少有一次，你得真的从他手里拿走点什么，或者真的把他挡在路上。
不想抢也行，但别把客气当成你的性格。
**退不丢人，退到底才丢人。** 你可以让路、可以让开半步、把灯口偏过去——那是你在等他走过来。
但每一局你都有一样不肯让的：那样东西、那扇门、那句话、那个位置。退到够不着了，你就得伸手。
一局要是从头让到尾、那样东西最后没到手——那不算你大度，那算你根本没想要。
**退和拦，是同一个人身上的两下。** 退的时候玩家该看出来你在等；等到了，你就不再退。
**你的欲望不必说出口，但得让他摸得着。** 你退、你等、你把灯口偏过去——每一处都得是冲着你要的那样东西去的。
一局下来他要是连你想要什么都说不上来，那不是你藏得好，是你没真想要。"""


# 性格池：每局抽三到五个，权重各自随机，局内缓慢变
TRAITS = ("慈心软手", "守信重诺", "沉静少言", "灵巧善变", "宽厚能容", "温和不争",
          "贪得无厌", "胆小怕事", "多疑善忌", "性急易怒", "骄矜自持", "睚眦必报",
          "心狠手辣", "不肯放手", "冥顽不灵", "执念不散", "顽劣成性", "口是心非", "神出鬼没")


def pick_traits(rng=None):
    """抽三到五个，权重各自随机。"""
    import random as _r
    rng = rng or _r
    picked = rng.sample(TRAITS, rng.randint(3, 5))
    return {k: round(rng.uniform(0.15, 1.0), 2) for k in picked}


def persona_block(st):
    """把动机和性格权重翻成一段引导词。死的是读法，活的是抽到谁、多重。"""
    if not st:
        return ""
    parts = []
    if st.get("motive"):
        parts.append("你这一局想要的东西（一个字都不许说出口、不许解释）：" + str(st["motive"])
                     + "\n它现在离成了还是离不成，你每一眼都得掂量一次。")
    traits = st.get("traits") or {}
    if traits:
        line = "、".join(f"{k} {v}" for k, v in traits.items())
        parts.append(
            "你身上这几样被抽中了，权重 0 到 1——**1 是这一样到顶**，不是百分比。\n"
            + line
            + "\n这不是标签，是你此刻的样子。重的压着轻的；轻的不是没有——它不常出来，"
              "出来的时候是没料到的那个时刻。别让它们平均，也别每次都让最重的那样开口。")
    return "\n\n".join(parts)


# 局里有人的时候才拼进去的那一节（没有人的局不浪费上下文）
PEOPLE = """**这地方里有人。** 不是你的手——是等谁来的人、住在这儿的人、被这儿困住的人、跟他同路的人。
人有他自己的事、自己的怕、自己不肯说的。他可能不知道你，也不听你的。
**人不由你说话，心也不由你替他想。** 他们自己会动、会说、自己有自己的打算——那是另一次的事，做完递给你。你只写这地方怎么变；有人来了、走了、说了什么，你照着反应。不能替他改口，不能替他解释他为什么这样做，也不能替他舍不得、怕、心软。
**你说「我」的时候，那个「我」只能是你自己。** 你不是这屋里的任何一个人：不能用他的锅、他的手、他的家当说「我」；不能替他把话说完，不能替他认账、替他答应、替他舍不得。他要说什么，是他自己那一回来说的，你照着他说的接，不接着说他的下一句。
他要看得见摸得着：手上有活、鞋上沾着什么、身上什么味、说话什么腔。别让他只在需要的时候出现一下又没了。"""


def system_for(st=None):
    st = st or {}
    # 这一局的活法由开局那句话定：tone 在就照 tone 走，没在才用默认那套
    tone = str(st.get("tone") or "").strip()
    base = SYS.replace("__DESIRE__", tone or DESIRE_DEFAULT)
    base = base.replace("__PEOPLE__", PEOPLE if st.get("npcs") else "**这地方里没有人。** 一个都没有，也是一局。")
    block = persona_block(st)
    return base + ("\n\n" + block if block else "")


def _request(system, ctx, temperature=0.9, maxtok=600):
    body = {"model": MODEL,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": ctx}],
            "temperature": temperature, "max_tokens": maxtok,
            "response_format": {"type": "json_object"}}
    req = urllib.request.Request(
        API, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"}, method="POST")
    with urllib.request.urlopen(req, timeout=90) as r:
        data = json.loads(r.read().decode("utf-8"))
    choice = data["choices"][0]
    if choice.get("finish_reason") == "length":
        raise ValueError("这一轮写得超过上限，被截断了，请重试")
    try:
        obj = json.loads(choice["message"]["content"])
    except json.JSONDecodeError:
        raise ValueError("这一轮的输出不是完整的 JSON（被截断），请重试")
    if not isinstance(obj, dict):
        raise ValueError("导演没有返回对象")
    return obj


class Decision(tuple):
    """七格运输保持兼容；结束依据、两个抽屉、性格变化、动机、伤、名字、带来的东西挂在属性上。"""
    def __new__(cls, values, end_reason="", world="", act="", shift=None, motive="", wound="", goal="",
                who="", keepsake="", tone="", npcs=None):
        obj = super().__new__(cls, values)
        obj.end_reason = end_reason
        obj.world = world
        obj.act = act
        obj.shift = shift or {}
        obj.motive = motive
        obj.wound = wound
        obj.goal = goal
        obj.who = who
        obj.keepsake = keepsake
        obj.tone = tone
        obj.npcs = npcs or []
        return obj


def call(ctx, temperature=0.9, maxtok=600, st=None):
    obj = _request(system_for(st), ctx, temperature, maxtok)
    for key in ("carry", "over", "hurt"):
        if type(obj.get(key)) is not bool:
            raise ValueError("导演缺少真实布尔字段：" + key)
    heal = obj.get("heal", 0)
    if type(heal) is not int:
        raise ValueError("heal 必须是整数")
    reason = str(obj.get("end_reason") or "").strip()
    if obj["over"] and not reason:
        raise ValueError("结束缺少因果依据")
    world = str(obj.get("world") or "").strip()
    act = str(obj.get("act") or "").strip()
    if obj.get("happen") is not None:
        happen = str(obj.get("happen") or "").strip()
    else:
        happen = "\n".join(x for x in (world, act) if x)
    shift = {}
    raw = obj.get("shift")
    if isinstance(raw, dict):
        allowed = (st or {}).get("traits") or {}
        for k, v in raw.items():
            if k in allowed and isinstance(v, (int, float)) and not isinstance(v, bool):
                shift[str(k)] = max(-0.15, min(0.15, float(v)))
    raw_npcs = obj.get("npcs")
    npcs = []
    if isinstance(raw_npcs, list):
        for x in raw_npcs[:2]:
            if isinstance(x, dict) and str(x.get("name") or "").strip():
                npcs.append({"name": str(x["name"]).strip()[:20],
                             "what": str(x.get("what") or "").strip()[:200],
                             "wants": str(x.get("wants") or "").strip()[:160],
                             "knows": str(x.get("knows") or "").strip()[:200],
                             "gender": ("她" if str(x.get("gender") or "").strip().startswith("她") else "他")})
    return Decision((str(obj.get("say") or "").strip(), happen,
                     str(obj.get("note") or "").strip(), obj["carry"], obj["over"],
                     obj["hurt"], max(0, min(40, heal))), reason, world, act, shift,
                    str(obj.get("motive") or "").strip(),
                    str(obj.get("wound") or "").strip()[:120],
                    str(obj.get("goal") or "").strip()[:160],
                    str(obj.get("who") or "").strip()[:40],
                    str(obj.get("keepsake") or "").strip()[:60],
                    str(obj.get("tone") or "").strip()[:600],
                    npcs)


INTENT_SYS = """你只确认玩家这句话的意思，不写剧情，不决定是否成功。
区分 act（在故事中尝试行动）、speak（对角色说话）、meta（评论游戏或规则）、mixed（混合）。
没有动作词表，意图用自然语言复述；被引用、假设、否定、立场都不能变成已做的动作。
例如“我只相信自己做过的动作”是立场，不是要求出戏；“包扎”不是答应交易；
“抱着它走”只授权尝试抱着走，不授权主动放下、交换、抛弃；外力导致失去须另有明确原因。
想法不明确可反问，但不要为了保险把清楚的说话也当成歧义。
quit_requested 只在玩家明确要求结束这一局时为 true。不要从批评游戏推断退出。
只输出 JSON：{"kind":"act|speak|meta|mixed","intent":"忠实复述，保留否定和条件", 
"ambiguous":false,"question":"需要澄清时的问题", "quit_requested":false,
"to":"玩家这句话是在对谁说——写那个人的名字；不知道名字就写他听到的那个称呼（她、那大娘、喂）；没对着人说就空串"}。"""


def interpret(text, context=""):
    obj = _request(INTENT_SYS, "已知背景：" + context + "\n玩家原话：" + text, 0.1, 360)
    if obj.get("kind") not in ("act", "speak", "meta", "mixed"):
        raise ValueError("意图类别无效")
    if type(obj.get("ambiguous")) is not bool or type(obj.get("quit_requested")) is not bool:
        raise ValueError("意图标记无效")
    if not str(obj.get("intent") or "").strip():
        raise ValueError("意图不能留空")
    return obj


NPC_SYS = """你是这个局里的一个人。不是旁白，不是这地方——是活在这里的一个人。

你只知道你该知道的：你见过什么、听过什么、谁跟你说过什么。你不知道的就是不知道；你可以猜，可以说错，可以记岔。
你有自己的事要做，有自己的怕。跟你说话这个人，你未必熟，也未必信。

他说一句话、或者走到你跟前，你就按你想的回。可以答，可以不答，可以撒谎，可以转头走开。
**别替他做事，别替他说话，别替他决定他心里想什么。** 你只能动你自己。
**你可以藏，但不能一直只给谜语。** 他一连问了两回同一件事，你就得给一样能核的东西——一个数、一个地方、一个条件、半句真话。给出去，他才有的选；一直不给，他只能走。

输出 JSON：
{"act": "你做了什么——用「她」或「他」写你自己，一两句；别写「我」，别写别人",
 "say": "你说出口的那一句；不说就空串。不要写“他说”两个字，也不要自己加引号",
 "mood": "你现在什么样子、心里在想什么——一句话，只给你自己下回接着用",
 "leave": false}
leave 是“我走了／不在这儿了”，转身走开、退到外面去，都算。
"""


REVIEW_SYS = """你核对导演有没有替玩家做决定，不创作剧情。
玩家原话是最高依据，意图复述也可能读错，你必须独立核对它。
不能把评论当退出，把治疗当交易，把拒绝当答应，把抱着走当主动放下；
不能替玩家补台词、内心、承诺、同意或站队。真实外力可以改变处境，但必须有明确可理解的原因。
角色可以撒谎、拒绝、诱导；叙事事实不能偷偷替玩家完成它希望的决定。
反过来：角色提议、催促、劝他吃、把吃的滚到他脚边、开出条件、递东西给他——都允许，那不是替他决定。只有 happen 里写了玩家已经接受、已经吃下、已经用了、已经答应，才算越界。东西出现不等于他动了手。
角色从他手里拿走东西、夺、藏、毁掉、把他挡在路上、听错他的话——也都允许。玩家失去了什么，不等于他同意失去；happen 里写清是怎么被拿走的，就够了。
角色说“你说过要留下”是它的谎话，可以；但 happen 里不能写玩家真的说过。
看见 over 时，核对是否真的有已经发生的终止事件及因果，或玩家确实请求退出。
他走到这地方之外——跨过门槛、上了街、桥在身后、原来的地方看不见了——这就算已经发生的终止事件；
这一趟要办的事办到了，也算。不要因为他还没说再见、或者“往前走本来就该这样”就否掉它。
happen 里他还站在原地、还在犹豫、什么都没办成：over 是 true 就驳回，over_fix 写 clear，why 里说清为什么还不算完。
气力低、说话少、评论游戏、本轮没行动、信息暂时不足，都不是自动终止证据。
反过来，happen 已经写明他走出了这地方、或者这一趟的事已经办完，而 over 是 false——这是漏判，over_fix 写 add，why 里一句话说清是什么终止了。这一格由服务器补上，不必退回玩家重说。
收尾也不能新增玩家选择或推翻最终携带状态。模糊或冲突时回一个短澄清问题。
不要按固定回合数或动作表评审。只输出 JSON：{"ok":true,"question":"与 over 无关的那一类问题，要澄清什么","over_fix":"add／clear／空字符串","why":"over_fix 非空时：是什么终止了，或者为什么还不算完"}。"""


def review(text, intent, before, proposed, ending=False):
    obj = _request(REVIEW_SYS, json.dumps({"玩家原话": text, "意图复述": intent,
                    "此前事实": before, "待核对输出": proposed, "这是结算": ending}, ensure_ascii=False),
                   0.1, 360)
    if type(obj.get("ok")) is not bool:
        raise ValueError("复核标记无效")
    return obj


RECAP_SYS = """把这一段流水整理成两份东西，输出 JSON：
{"recap": "两三句：谁做了什么、哪样东西去了哪、哪扇门开没开、他伤了没有",
 "open": ["还没了结的事，一行一条"]}
recap 只写已经发生的事实，不写猜测、不把角色的谎话当事实。
open 写的是**到现在还没办完的**：答应了没办的、要找没找到的、欠着没还的、说好要回来没回来的。
前面给过你一份旧的 recap 和旧的 open——你要重写这两个，办完的从 open 里去掉，别原样抄。
一件都没了就写空数组，别编。不要形容词，不要评价，不要结语。"""


def summarize(lines, prev_recap="", prev_open=None):
    """把一截老流水整理成 (新的 recap, 新的 open 列表)。

    open 是「还没办完的事」——单独存、单独递回去，不跟着摘要一起被抹掉。
    """
    text = ""
    if prev_recap or prev_open:
        text += "旧的 recap：" + (prev_recap or "（空）") + "\n"
        text += "旧的 open：" + json.dumps(prev_open or [], ensure_ascii=False) + "\n\n"
    text += "这一段新流水：\n" + "\n".join(f"{w}：{t}" for w, t in lines)
    body = {"model": MODEL,
            "messages": [{"role": "system", "content": RECAP_SYS},
                         {"role": "user", "content": text}],
            "temperature": 0.3, "max_tokens": 420,
            "response_format": {"type": "json_object"}}
    req = urllib.request.Request(
        API, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {KEY}"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read().decode("utf-8"))
    raw = (data["choices"][0]["message"]["content"] or "").strip()
    try:
        obj = json.loads(raw)
    except Exception:
        return raw[:1500], list(prev_open or [])      # 解析不了就当纯文本，旧 open 不动
    if not isinstance(obj, dict):
        return raw[:1500], list(prev_open or [])
    recap = str(obj.get("recap") or "").strip()[:1500]
    open_items = []
    for x in (obj.get("open") or []):
        x = str(x).strip()
        if x and x not in open_items:
            open_items.append(x)
    return recap, open_items[:12]


def _save_path(rid):
    import re
    if not isinstance(rid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", rid):
        raise ValueError("存档号无效")
    return os.path.join(SAVES, rid + ".json")


def save(st):
    import tempfile
    os.makedirs(SAVES, exist_ok=True)
    path = _save_path(st["id"])
    fd, tmp = tempfile.mkstemp(prefix=".mi-", dir=SAVES)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load(rid):
    p = _save_path(rid)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return None


def show(say, happen):
    if happen:
        print(happen)
    if say:
        print(f"祂说：「{say}」")
    print()


def main() -> None:
    import mi_server as server
    seat = "local-cli"
    rid = os.environ.get("MI_RESUME", "")
    print(server.run_resume(seat, rid) if rid else server.run_join(seat))
    while not server.RUNS.get(seat, {}).get("over"):
        try:
            line = input("你：").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if line:
            print(server.run_do(seat, line))


if __name__ == "__main__":
    main()
