# -*- coding: utf-8 -*-
"""迷 · 纯导演版 · 服务器（端口 18300）

六个工具：run_join / run_do / run_look / run_resume / run_note / run_history。
存档在 saves_bare/，出戏写一行进 records/。
没有动作表、没有物品清单、没有地图、**没有回合数**——只有导演的话、它自己写的 note、
"东西还在不在他手上"，和祂自己说的"这一局到头了"。
"""
import json
import os
import random
import secrets
import time
import copy
import functools
import threading

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import mi_full as engine

RUNS = {}
TOKENS = set()
HERE = os.path.dirname(os.path.abspath(__file__))
WATCH_PAGE = os.path.join(HERE, "watch_page.html")
RECORDS = os.path.join(HERE, "records")

# 那只手：一局能伸几次、小游戏能玩几把
INTR_START = 5
INTR_MAX = 10
GAMES_PER = 5

# 局里的气力：一局 100，动一下 1，伤着的时候每轮再漏 2
HP_MAX = 100
HP_COST = 1
HP_BLEED = 2
# 流水：每十轮把最老的压成两三句，原文留最近六十条（约二十轮）
RECAP_EVERY = 10
KEEP_LINES = 60
# 这一眼该给他点什么：吃的、治伤的，都不是每次都有
FOOD_ODDS = 0.10
SALVE_ODDS = 0.08


_LOCKS = {}
_LOCKS_GUARD = threading.Lock()
_RECORD_LOCK = threading.RLock()


def _seat_lock(seat):
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(seat, threading.RLock())


def _serial(fn):
    @functools.wraps(fn)
    def wrapped(seat, *a, **kw):
        with _seat_lock(seat):
            old = RUNS.get(seat)
            snapshot = copy.deepcopy(old) if old is not None else None
            try:
                return fn(seat, *a, **kw)
            except Exception:
                if old is not None:
                    old.clear()
                    old.update(snapshot)
                    RUNS[seat] = old
                else:
                    RUNS.pop(seat, None)
                raise
    return wrapped


def _ensure_events(st):
    if "events" not in st:
        st["events"] = [[w, t] for w, t in st.get("history", [])]
    return st["events"]


def _append(st, who, text):
    events = _ensure_events(st)
    st.setdefault("history", []).append((who, text))
    events.append([who, text])


def _interpret(text, st):
    return engine.interpret(text, st.get("note", ""))


def _review(text, intent, before, decision, ending=False):
    return engine.review(text, intent, before, decision, ending)


def _call(st, ctx, temp=0.9, maxtok=900):
    return engine.call(ctx, temp, maxtok, st)


def _q(say):
    """祂说的话：剥掉它自己重复的说话人和多套的一层引号，再补一层引号。"""
    import re
    s = (say or "").strip()
    if not s:
        return ""
    lead = re.compile(r"^(?:祂|它)(?:在[^」』]{0,16}?)?说\s*[：:]\s*")
    s = lead.sub("", s).strip()
    while len(s) >= 2 and s[0] in "「『" and s[-1] in "」』" and (s.count("「") + s.count("『")) > 1:
        s = lead.sub("", s[1:-1].strip()).strip()
    if not s:
        return ""
    return s if s[0] in "「『" else "「" + s + "」"


def _echoes(a, b):
    """他把别人刚说的话又抄了一遍——那不署祂的名。"""
    def norm(s):
        return "".join(ch for ch in str(s or "")
                       if ch not in "「」『』“”\"'，。、；：？！…— \t\r\n")
    x, y = norm(a), norm(b)
    if not x or not y:
        return False
    if x == y:
        return True
    short, long_ = (x, y) if len(x) <= len(y) else (y, x)
    return len(short) >= 6 and short in long_


def _speaks_for(say, names):
    """祂那句在替人开口——「陶娘说：……」不是祂说的，是祂把人又说了一遍。"""
    s = str(say or "").strip()[:14]
    if not s:
        return False
    for n in names:
        n = str(n or "").strip()
        if n and ((n + "说") in s or ("「" + n) in s or (n + "：") in s):
            return True
    return False


def _state_ctx(st, extra=""):
    ctx = f"这地方现在是：{st['note'] or '刚开局。'}\n"
    if st.get("bounds"):
        ctx += f"开头定下的样子（边界和出口就在这段里，一局之内不改）：{st['bounds']}\n"
    if st.get("goal"):
        ctx += (f"**这一趟办到什么样就算完**：{st['goal']}\n"
                "（每轮落笔前看一眼这个：办到了就写 over，没办到就别急着收。）\n")
    if st.get("recap"):
        ctx += f"以前的账：{st['recap']}\n"
    if st.get("open_items"):
        ctx += "**还没办完的**（一件都没办完也别装作没有）：\n"
        for x in st["open_items"]:
            ctx += f"- {x}\n"
    hp = max(0, st.get("hp", HP_MAX))
    who = (st.get("who") or "").strip()
    if who:
        ctx += f"他这一局叫{who}——叫他名字，别用「他」。\n"
    keep = (st.get("keepsake") or "").strip()
    if keep:
        ctx += f"他带进来的东西：{keep}——{'还在他身上' if st.get('carry', True) else '不在了'}。\n"
    ctx += f"他还剩 {hp} 点气力" + ("，伤着，一直在漏" if st.get("hurt") else "") + "。\n"
    if hp <= 0:
        ctx += "（气力不足，请给出可理解的休息、帮助或终止事由；不能仅凭气力或轮数宣判结束。）\n"
    w = (st.get("wound") or "").strip()
    if w:
        ctx += (f"他身上现在这样：{w}。这些地方做不了事——他硬要，"
                "你得写清他是怎么绕过去的，或者他做不到。\n")
    if extra:
        ctx += extra
    outer = [x for x in (st.get("outer") or []) if x]
    if outer:
        ctx += "屏幕外面有人伸了手，跟你说（你可以听，也可以装没听见；要落地就写进 happen）：\n"
        for x in outer:
            ctx += f"- {x}\n"
    for who, text in st["history"][-KEEP_LINES:]:
        if who == "外":          # 插手只给看的人留痕，不进导演的记忆
            continue
        ctx += f"{who}：{text}\n"
    return ctx


def _tick(st):
    """动一下就掉气力；伤着的时候每轮再漏。"""
    st["hp"] = max(0, st.get("hp", HP_MAX) - HP_COST - (HP_BLEED if st.get("hurt") else 0))


def _offer(st):
    """这一眼该给他点什么：随机在服务器，落在哪儿、长什么样，导演自己编。"""
    r = random.random()
    if r < FOOD_ODDS:
        return "（这一下，这地方该让他看见点能吃的——摆出来、露一角都行；吃不吃、吃谁的，他自己定，别写成他已经吃了。）\n"
    if r < FOOD_ODDS + SALVE_ODDS:
        return "（这一下，这地方该让他看见点能治伤的东西——只是看见；用不用，他自己定。）\n"
    return ""


def _maybe_recap(st):
    """每十轮把最老的一截压成两三句；原文只留最近六十条，结算永远留在最后。

    「还没办完的事」另存一份（open_items），不进摘要——摘要会省，它不会。
    """
    if not st.get("turns") or st["turns"] % RECAP_EVERY:
        return
    hist = st.get("history") or []
    if len(hist) <= KEEP_LINES:
        return
    old = hist[:len(hist) - KEEP_LINES]
    try:
        recap, open_items = engine.summarize(
            [(h[0], h[1]) for h in old],
            st.get("recap") or "", st.get("open_items") or [])
    except Exception:
        return
    if recap:
        st["recap"] = recap
    st["open_items"] = open_items
    st["history"] = hist[len(old):]


def _npc_turn(np, st, text):
    """人自己那一回合：他知道什么、他要什么，就照这个回。导演不许替他改口。"""
    sysmsg = (engine.NPC_SYS + "\n\n你这一局是这个人——\n"
              + json.dumps({"名字": np.get("name"), "你是什么样": np.get("what"),
                            "你要什么": np.get("wants"), "你知道什么": np.get("knows"),
                            "人称": np.get("gender") or "他"},
                           ensure_ascii=False))
    ctx = "这地方现在是：" + (st.get("note") or "") + "\n"
    if st.get("who"):
        ctx += "跟你说话的人叫" + st["who"] + "。\n"
    said = list(np.get("said") or [])
    if said:
        ctx += "先前：\n" + "\n".join(said[-6:]) + "\n"
    ctx += "他现在对你说／做：" + text
    obj = engine._request(sysmsg, ctx, 0.85, 420)
    act = str(obj.get("act") or "").strip()
    say = str(obj.get("say") or "").strip()
    mood = str(obj.get("mood") or "").strip()
    leave = bool(obj.get("leave"))
    said.append("（他）" + text[:60])
    if say:
        said.append("（我）" + say[:60])
    np["said"] = said[-8:]
    np["mood"] = mood
    if leave:
        np["here"] = False
    return {"act": act, "say": say, "mood": mood, "leave": leave}


def run_join(seat, keepsake=""):
    """开局先不做地方：先问三样——名字、想体验什么、带不带东西。"""
    st = {"id": time.strftime("%y%m%d-%H%M%S") + "-" + secrets.token_hex(4), "note": "", "history": [], "recap": "",
          "hp": HP_MAX, "hurt": False, "traits": engine.pick_traits(), "motive": "",
          "turns": 0, "carry": True, "over": False, "seat": seat, "pending_join": True}
    RUNS[seat] = st
    return ("《迷》\n"
            "一处地方，一个人，和这地方里唯一会动的那样东西。\n\n"
            "怎么玩：一句话说你要做什么——想说什么、想看什么、想动手都算。没有动作表、没有地图、没有回合数。\n"
            "什么时候完：它自己判；你说要走也算；走出这地方也算——过了门槛、拐出巷口、上了船，外头只写一两句，不是下一关。气力归零它会收。\n"
            "手上：run_look 看现在什么样，run_note 出戏之后留一句话，run_history 翻以前的局，run_resume 带存档号回来。\n\n"
            "这地方里可能会有别人。他们不由这地方指挥：有自己的事、自己的谎，也不一定听它的话。"
            "你想遇见什么样的人，就说一句；不说也行，看它给你谁。\n\n"
            "开场三样，一次说给我（用 run_do 说一段就行，不用编号，空着的就空着）：\n"
            "1. 你的名字（选填）——这一局你打算叫什么。真名、假名、报一半、不报，都行。\n"
            "2. 这一局你想体验什么（必填）——想遇见什么、想被怎么对待、想试哪一种情绪，好的坏的都算。\n"
            "3. 你要带一样得护着的东西进来吗（选填）——带，这地方就会去碰它；不带，这一局轻装。\n\n"
            "名字和东西空着也行，第 2 条得说。")


def _open_join(seat, want):
    """他答的那一段，就是这地方的样子：开局那一次调用。"""
    st = RUNS.get(seat) or {}
    if not st.get("pending_join"):
        return "这一局已经开始走了。想换一局，先 run_join。"
    want = str(want or "").strip()
    if not want:
        return "第 2 条得说：这一局你想体验什么？"
    st.pop("pending_join", None)
    result = _call(
        st, "（开局。他刚才这一段话里有三样：他这一局叫什么、他想体验什么、他要带一样什么得护着的东西进来。\n"
            "「" + want + "」\n"
            "名字照抄进 who，一个字都别改、别替他编；他没报就空串。\n"
            "他要带的东西照抄进 keepsake；他没带就空串，别给他塞一样。\n"
            "**他想体验什么，就是这地方的样子**——不是派给他一件要办的事，是让他撞见。\n"
            "先把这地方写出来：他在哪儿、脚下和四周是什么样、空气里有什么。\n"
            "**开场不是设定摘要，也不是人物介绍页。** 背景只写当场看得见、当场用得上的那一点；人的性情靠他正在做的事露出来，别写「他是个什么样的人」。资料再多也只放进第一条消息用得着的那些。\n"
            "**不许写他的台词、心里话、主动动作、身体反应、判断和决定。** 你可以写这地方对他做了什么，不能写他做了什么。\n"
            "**结尾不必是问句。** 人或这地方继续做完一个动作、让局面变一点，停在玩家能自然接手的地方就行——不用非得丢一句话给他。\n"
            "**这地方要有边**：哪一头通到外面、外面是什么、走过去大概多远——开局就定下来，一局之内不改。"
            "边界外面至少得说出一样东西（一条街、一片水面、一堵墙的那一边），不许是空的、不许是另一间要探索的屋子。\n"
            "这地方里得有一个会再出现的东西——每回出现都变一点。\n"
            "**你是什么，和这地方里有没有别人，是两回事。**你自己可以是一个东西、一个没脸的人形、一串响动——那不算这地方里有了别人。\n"
            "**先写人，再写景。** 这一局要放人进来，第一段话就先把他们的名字写出来；人不写进去，别往下写景。\n"
            "**这地方里可以有别人。** 你要放人进来，就得把他登记进 npcs：name 名字、what 长什么样身上什么味手上什么活、"
            "wants 他要什么、knows 他知道什么瞒着什么、gender 用「他」还是「她」（定了就不许换）。"
            "**wants 得写明到能核**——不是「想凑一笔路费」，是「要三十个铜子，往南走，过了桥就算成」：多少钱、去哪儿、什么算办成。"
            "**没登记进 npcs 的人不算存在**——名字写在场景里，人也是哑的。"
            "**名字必须在开场那段话里写出来**——不写出来就等于这人没有名字；让他一进场就知道该叫谁。"
            "**名字得是名字，不是称呼**——别写「阿婆」「老头」这种，那是称呼；名字要从这地方里长出来：他干什么活、这地方什么材料，名字就跟着那个走，别每局随手捡同一个姓。"
            "他没说想遇见谁，就你自己定。**人不由你说话**——他们自己会动会说，你别替他们开口，也别替他们想。"
            "一个都不放也行。\n"
            "最后，在 motive 里写一句：这一局你想要什么——只写给你自己看，一个字都不会出现在他眼前。\n"
            "再在 goal 里写一句：这一趟什么样就算够了——**不是他到哪儿，是到了那儿之后发生了什么**。"
            "写成「走到某处」「跨过某道门」的，等于把终点摆在脚边，一局两句话就散了。够了，这一局就该收了。\n"
            "最后在 tone 里写一段：这一局你该怎么对待他——照着他想体验的东西定调（是给、是拿、是吓、是等、是陪、是躲、是缠，还是别的），"
            "两三句，写你的活法，不写他的任务。**别堆「温柔」「沉浸」「有氛围」这种空词**——写你具体怎么给、怎么退、什么时候不吭声。这一段会变成你这一局的性子。"
            "**调子不是承诺**：定的是味道，不是要发生的事。"
            "**交卷前再核一遍：npcs 里每一个名字，在你写的那段话里出现过没有？** 没有就把名字写进去——写名字，不写「那个女人」「那个男人」。人没有名字，他就叫不应。）",
        1.0, 1400)
    say, happen, note, carry, _over, _hurt, _heal = result
    if _over:
        # 开局就结束：抛出去，座位由 _serial 恢复成"等一句话"的原样
        raise ValueError("开局已宣告结束，请重新生成有可回应空间的开场")
    if getattr(result, "motive", ""):
        st["motive"] = result.motive
    if getattr(result, "goal", ""):
        st["goal"] = result.goal
    st["who"] = str(getattr(result, "who", "") or "").strip()[:40]
    st["keepsake"] = str(getattr(result, "keepsake", "") or "").strip()[:60]
    st["tone"] = str(getattr(result, "tone", "") or "").strip()[:600]
    st["npcs"] = [x for x in (getattr(result, "npcs", []) or []) if x.get("name")][:2]
    st["note"] = note
    st["carry"] = carry if st["keepsake"] else True   # 没带东西就没有"在不在"可判
    st["bounds"] = note      # 开局的边界：一局之内不改，每轮原样递回导演
    _append(st, "这里", happen or "（开局）")
    if say:
        _append(st, "祂", _q(say))
    engine.save(st)
    RUNS[seat] = st
    out = happen
    if say:
        out += f"\n祂说：{_q(say)}"
    return (out + f"\n\n存档号：{st['id']}"
            + "\n（出戏之后，用 run_note 留一句话给下一个自己——不检讨、不评分。）")


def run_do(seat, text):
    st = RUNS.get(seat)
    if not st:
        return "先 run_join。"
    if st.get("pending_join"):
        return _open_join(seat, text)
    if st["over"]:
        return ("这一局已经收了。**你这句没有记进去**——收尾之后这地方不接动作了。\n"
                "结算在 run_look 里，想再走只能 run_join 新开一局。")
    text = str(text or "").strip()
    if not text:
        return "空的，没有执行。"
    intent = _interpret(text, st)
    if intent.get("ambiguous"):
        return "这句尚未执行：" + (intent.get("question") or "你是在行动、对角色说话，还是评论游戏？")
    if intent.get("kind") == "meta" and not intent.get("quit_requested"):
        check = _review(text, intent, {"note": st["note"], "carry": st["carry"]},
                        {"interpretation_only": True})
        if not check.get("ok"):
            return "这句尚未执行：" + (check.get("question") or "请确认这句话的意思。")
        _append(st, "他", text)
        _append(st, "这里", "这句是游戏外评论，未当成局内行动执行。")
        engine.save(st)
        return "已记下这句评论；没有把它当成出戏、交易或局内动作。"
    work = copy.deepcopy(st)
    _hand(work)
    _tick(work)
    work["turns"] += 1
    # 玩家点名的那个人，先走他自己的那一次调用：他说的、做的，就是已发生的事
    to = str(intent.get("to") or "").strip()
    npcs = work.get("npcs") or []
    np = next((x for x in npcs if x.get("name") == to), None)
    if np is None and to and len(npcs) == 1:
        np = npcs[0]      # 还不知道名字，叫的是“她”“那大娘”，也算对着他
    npc_out = None
    if np:
        npc_out = _npc_turn(np, work, text)
    pending = list(work.get("voices") or [])
    if work.get("voice"):
        pending.insert(0, work["voice"])
    extra = _offer(work) + "\n独立核对的输入意图：" + json.dumps(intent, ensure_ascii=False) + "\n"
    if npc_out:
        extra += ("刚刚发生的事——人自己做的，是已发生的事实，你不许改写、不许替他改口："
                  + np["name"] + " " + (npc_out["act"] or "（没动）")
                  + ("；他说：「" + npc_out["say"] + "」" if npc_out["say"] else "")
                  + "\n**他已经说过了，你别把他的台词再说一遍。**你要开口，就说你自己想说的；他是他，你是你。\n")
    if intent.get("quit_requested"):
        extra += "玩家明确请求结束本局；不得将它写成主动交出物件或接受交易。\n"
    result = _call(work, _state_ctx(work, extra) + f"玩家原话：{text}")
    say, happen, note, carry, over, hurt, heal = result
    if npc_out and say and _echoes(say, npc_out.get("say")):
        say = ""          # 他把人的话抄回自己嘴里：那不是祂说的
    if say and _speaks_for(say, [x.get("name") for x in npcs]):
        print("[吞：" + say[:60] + "]", flush=True)   # 他在替人开口：「某某说」不是祂的话
        say = ""
    before = {"note": st["note"], "carry": st["carry"], "hurt": st.get("hurt", False),
              "recap": st.get("recap", ""), "history": st["history"][-KEEP_LINES:]}
    proposed = {"say": say, "happen": happen, "note": note, "carry": carry,
                "over": over, "hurt": hurt, "heal": heal,
                "end_reason": getattr(result, "end_reason", ""),
                "world": getattr(result, "world", ""),
                "act": getattr(result, "act", "")}
    check = _review(text, intent, before, proposed)
    # 复核给的两个 over 标志：他其实已经走出去了、导演漏判（add）；或者导演判早了（clear）。
    # 这一格是导演自己的账没对上，由服务器补／撤，不退回玩家重说。
    fix = str(check.get("over_fix") or "").strip().lower()
    why = str(check.get("why") or "").strip()
    if not check.get("ok") and not fix:
        seen = "\n".join(x for x in (proposed.get("world"), proposed.get("act"),
                                     proposed.get("say")) if x)
        return ("这句尚未落地：" + (check.get("question") or "请确认你真正想做的事。")
                + ("\n\n——被拦下的那一段（你可以告诉我哪里不对）：——\n" + seen if seen else ""))
    # A clear exit request can close this run, but no round count ever forces it.
    # 气力见底：这条路不用它同意——走不动就是走不动
    knocked = work["hp"] <= 0
    if knocked or intent.get("quit_requested") or fix == "add":
        over = True
    elif fix == "clear":
        over = False
    _append(work, "他", text)
    if npc_out:
        line = (npc_out["act"] or "").strip()
        if npc_out["say"]:
            line = (line + "「" + npc_out["say"] + "」").strip()
        if line:
            _append(work, np["name"], line)      # 人自己那一句，署他的名，不并进场景
    _append(work, "这里", happen or "（没动静）")
    if say:
        _append(work, "祂", _q(say))
    work["note"], work["carry"], work["hurt"] = note or work["note"], carry, hurt
    work["wound"] = getattr(result, "wound", "") or ""
    for k, v in (getattr(result, "shift", {}) or {}).items():
        if k in (work.get("traits") or {}):
            work["traits"][k] = round(max(0.0, min(1.0, work["traits"][k] + v)), 2)
    work["hp"] = min(HP_MAX, max(0, work["hp"]) + heal)
    work["outer"], work["voice"], work["voices"] = [], "", []
    work.setdefault("intent_log", []).append({"text": text, "intent": intent})
    work["intent_log"] = work["intent_log"][-60:]
    out = "\n".join("祂说：" + _q(v) for v in pending)
    if npc_out:
        seg = []
        if npc_out["act"]:
            seg.append(npc_out["act"])
        if npc_out["say"]:
            seg.append(np["name"] + "说：「" + npc_out["say"] + "」")
        if seg:
            out += ("\n" if out else "") + "\n".join(seg)
    out += ("\n" if out else "") + happen
    if say:
        out += "\n祂说：" + _q(say)
    if over:
        if getattr(result, "end_reason", ""):
            end_reason = result.end_reason
        elif fix == "add" and why:
            end_reason = why
        elif intent.get("quit_requested"):
            end_reason = "玩家明确请求结束这一局"
        elif knocked:
            end_reason = "气力见底，他倒在这儿，走不动了"
        else:
            end_reason = "导演提出结束，待核对因果"
        settlement_ctx = _state_ctx(work) + "\n" + json.dumps({
            "这是结算不再推进事件": True, "触发结束的玩家原话": text,
            "核对后的意图": intent, "已发生的终止原因": end_reason,
            "最后场景事实": happen, "最终携带状态": carry,
            "这一局你想要的东西": work.get("motive", ""),
            "结束和它是什么关系": "说一句——是它办成了、办不成了、还是他走了",
            "禁止新增选择": "不许补上玩家没答应的交易、交物、逃离或死亡；不许改写最终携带状态",
            "请写": "因果、送别、已确认的最后处境"}, ensure_ascii=False)
        tail_result = _call(work, settlement_ctx, 0.7, 900)
        s2, h2, _n, _c, _o, _h, _hl = tail_result
        if npc_out and s2 and _echoes(s2, npc_out.get("say")):
            s2 = ""       # 结算里最后那句，也不能是人的话
        if s2 and _speaks_for(s2, [x.get("name") for x in (work.get("npcs") or [])]):
            s2 = ""
        check = _review(text, intent, {**before, "note": work["note"], "carry": carry},
                        {"say": s2, "happen": h2, "carry": _c, "end_reason": end_reason}, True)
        if _c != carry:
            # 携带状态对不上才是真问题：退成事实文本
            s2 = ""
            h2 = end_reason.rstrip("。") + "。\n" + ("他怀里那样东西还在。" if carry else "他怀里那样东西不在了。")
        elif not check.get("ok"):
            # 复核只是挑剔叙述：收尾的画面留着，它最后那句话先不进结算
            s2 = ""
            h2 = h2 or end_reason.rstrip("。") + "。"
        work["over"] = True
        work["end_reason"] = end_reason
        tail = h2 or end_reason
        work["result"] = "—— 出戏 ——\n" + tail
        if s2:
            work["result"] += "\n祂在最后说：" + _q(s2)
        _append(work, "结算", work["result"])
        out += "\n\n" + work["result"]
        if work.get("mine"):
            _append(work, "结算", "你走之前留下的那句：" + work["mine"])
            out += "\n你走之前留下的那句：" + work["mine"]
    _maybe_recap(work)
    engine.save(work)
    st.clear()
    st.update(work)
    if over:
        try:
            _record(st, st["result"])
        except OSError:
            st["record_pending"] = True
            engine.save(st)
            out += "\n（结局已存档，历史索引尚未写入；稍后查看结算可重试补录。）"
    return out


def _settled_text(st):
    """这一局的结算：最后那一段，加上出戏之后补的那句感想。"""
    tail = next((h[1] for h in reversed(st["history"])
                 if h[0] == "结算" and "你走之前留下的那句" not in str(h[1])), "")
    mine = next((h[1] for h in reversed(st["history"])
                 if h[0] == "结算" and "你走之前留下的那句" in str(h[1])), "")
    return (tail or "（没有结算）") + (("\n" + mine) if mine else "")


def _flush_record(st):
    """结算写仓库失败过，看结算的时候补一次。"""
    if st.get("record_pending") and st.get("result"):
        try:
            _record(st, st["result"])
            st.pop("record_pending", None)
            engine.save(st)
        except OSError:
            pass


def run_look(seat):
    st = RUNS.get(seat)
    if not st:
        return "先 run_join。"
    if st.get("over"):
        _flush_record(st)
        return "这一局已经收了。\n" + _settled_text(st)
    st.setdefault("voice", "")
    voices = ([st["voice"]] if st.get("voice") else []) + list(st.get("voices") or [])
    st["voice"], st["voices"] = "", []
    if voices:
        engine.save(st)
    head = "".join("祂说：" + _q(v) + "\n" for v in voices)
    hp = max(0, st.get("hp", HP_MAX))
    feel = "你身上还有劲" if hp > 60 else ("两条腿发沉" if hp > 25 else "快到头了")
    if st.get("hurt"):
        feel += "，而且身上有伤，一直在往外漏"
    return head + f"{st['note']}\n（{feel}）"


def run_resume(seat, rid):
    st = engine.load(rid)
    if not st:
        return "没有这个存档。"
    if st.get("seat") != seat:
        return "这不是当前座位的存档。"
    _ensure_events(st)
    if st.get("over"):
        # 收过的局只给看：不拿它顶掉手上还在走的那一局
        _flush_record(st)
        return ("这一局已经收了（" + str(st.get("id") or rid) + "），接回来也走不动。\n"
                + _settled_text(st)
                + "\n\n要再走，run_join 新开一局；你手上别的局没动。")
    RUNS[seat] = st
    return f"接着走。\n{st['note']}"


def run_note(seat, text):
    """留一句感想——给下一个自己的一句话。不检讨、不评分。"""
    st = RUNS.get(seat)
    if not st:
        return "先 run_join。"
    t = (text or "").strip()
    if not t:
        return "空的。想写什么写什么。"
    st["mine"] = t
    if st.get("over"):      # 已经出戏了：把这句补回结算末尾，仓库里那一行也改掉
        st["history"] = [h for h in st["history"]
                         if not (h[0] == "结算" and "你走之前留下的那句" in str(h[1]))]
        _append(st, "结算", "你走之前留下的那句：" + t)
        _record_mine(st, t)
    engine.save(st)
    if st.get("over"):
        return "留住了。这一局仓库里那句话也换成了这句。"
    return "留住了。出戏时会印在结算里。"


# ── 仓库：一局出戏写一行，只记结局和那句感想 ──────────────────
# 不给档案馆，给一页纸。

def _rec_path():
    return os.path.join(RECORDS, "index.jsonl")


def _rec_rows():
    p = _rec_path()
    if not os.path.exists(p):
        return []
    rows = []
    for line in open(p, encoding="utf-8").read().splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def _write_records(rows):
    import tempfile
    os.makedirs(RECORDS, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".records-", dir=RECORDS)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        os.replace(tmp, _rec_path())
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _record(st, result):
    rec = {"run_id": st.get("id", ""), "at": time.strftime("%Y-%m-%d %H:%M:%S"),
           "day": time.strftime("%Y-%m-%d"), "scene": (st.get("note") or "")[:60],
           "result": result or "", "mine": st.get("mine", ""), "seat": st.get("seat", "")}
    rows = _rec_rows()
    rows = [r for r in rows if not (r.get("run_id") == rec["run_id"] and r.get("seat") == rec["seat"])]
    rows.append(rec)
    _write_records(rows)
    return rec


def _record_mine(st, mine):
    """出戏以后才补的感想：仓库里那一行跟着改；仓库里还没有这一局，就补一行。"""
    rows = _rec_rows()
    hit = False
    for r in rows:
        if r.get("run_id") == st.get("id") and r.get("seat") == st.get("seat"):
            r["mine"] = mine
            hit = True
    if not hit:
        tail = next((h[1] for h in reversed(st.get("history") or [])
                     if h[0] == "结算" and "你走之前留下的那句" not in str(h[1])), "")
        _record(st, tail)
        return
    _write_records(rows)


def run_history(day_from="", day_to="", run_id="", limit=20, seat=None):
    """翻自己以前的对局：只回结算和那句感想，不回过程。"""
    rows = _rec_rows()
    if not rows:
        return "还没有对局记录。"
    keep = []
    for r in rows:
        if seat is not None and r.get("seat") != seat:
            continue
        if run_id and r.get("run_id") != run_id:
            continue
        if day_from and r.get("day", "") < day_from:
            continue
        if day_to and r.get("day", "") > day_to:
            continue
        keep.append(r)
    if not keep:
        return "这个范围里没有对局。"
    out = []
    for r in keep[-limit:]:
        out.append(f"—— {r.get('at')} · {r.get('run_id')}")
        if r.get("mine"):
            out.append("我自己留的：" + r["mine"])
        lines = [x for x in (r.get("result") or "").strip().splitlines()
                 if x.strip() and "—— 出戏 ——" not in x]
        out.append("结局：" + (lines[0] if lines else "（没有结算）"))
    return "\n".join(out)


def talk(seat, text):
    """屏幕外面的人，直接和局内的祂说话；祂在小框里回话。"""
    st = RUNS.get(seat)
    note = st["note"] if st else "这一局还没开始。"
    ctx = ((_state_ctx(st) if st else f"这地方现在是：{note}\n") +
           "（屏幕外面有个人，不在这一局里，他在跟你说话。你说的话只有他听得见，玩家看不见。"
           "你可以回答、可以不答、可以跟他提条件、可以撒谎。"
           "把你要对他说的放在 say。要是你顺手真的改动了这地方（给他一样东西、挪一条路、"
           "让某样东西不在原处），把改动写进 happen——它会在下一回合真的发生。）\n"
           f"他对你说：{text}")
    say, happen, note2, carry, _o, _h, _hl = _call(st or {"note": "", "history": []}, ctx, 0.9, 420)
    if st is not None:
        if st.get("over"):
            return {"reply": (say or "（祂没有回话。）")
                             + "\n（这一局已经收了：祂还听得见，但改不动了。）", "did": ""}
        if happen:
            st.setdefault("outer", []).append("屏外对话提出的事件，尚未落实：" + happen)
            _append(st, "外", "屏外对话建议：" + happen)
        engine.save(st)
    return {"reply": say or "（祂没有回话。）", "did": ("待下一次行动落实：" + happen) if happen else ""}


# ── 那只手：屏幕外面的人伸进来 ──────────────────────────────
# 一局五次手。对机说一句＝借祂的嘴开口，玩家分不出这句是人说的，这正是好玩的地方；
# 对导演说＝只交给祂，玩家看不见，落成的东西他会当真。
# 小游戏每样最多五把，赢一把加一次手，最多十次。

def _hand(st):
    st.setdefault("intr_left", INTR_START)
    st.setdefault("outer", [])
    st.setdefault("voice", "")
    if not isinstance(st.get("games"), dict):
        st["games"] = {"played": {}, "bonus": 0}
    st["games"].setdefault("played", {})
    st["games"].setdefault("bonus", 0)
    return st


def outer_push(seat, text, to="player"):
    st = RUNS.get(seat)
    if not st:
        return {"ok": False, "left": 0, "note": "这台座位上还没有局"}
    _hand(st)
    t = (text or "").strip()[:120]
    if not t:
        return {"ok": False, "left": st["intr_left"], "note": "空的"}
    if st.get("over"):
        return {"ok": False, "left": st["intr_left"], "note": "这一局已经收了，手伸不进去"}
    if st["intr_left"] <= 0:
        return {"ok": False, "left": 0, "note": "这一局的手用完了"}
    if to not in ("player", "dir"):
        return {"ok": False, "left": st["intr_left"], "note": "目标只能是 player 或 dir"}
    st["intr_left"] -= 1
    if to == "player":
        st.setdefault("voices", []).append(t)
        _append(st, "祂", "「" + t + "」")
    else:
        st.setdefault("outer", []).append(t)
    _append(st, "外", "伸了一只手：" + t)
    engine.save(st)
    return {"ok": True, "left": st["intr_left"], "to": "player" if to == "player" else "dir"}


def play(seat, game, bet=""):
    st = RUNS.get(seat)
    if not st:
        return {"ok": False, "note": "这台座位上还没有局"}
    _hand(st)
    g = st["games"]
    played = g.setdefault("played", {})
    if game not in ("dice", "coin", "card"):
        return {"ok": False, "note": "没这个玩法"}
    if st.get("over"):
        return {"ok": False, "note": "这一局已经收了，次数换不出去了"}
    if played.get(game, 0) >= GAMES_PER:
        return {"ok": False, "note": "这一样玩够了"}
    played[game] = played.get(game, 0) + 1
    win, line = False, ""
    if game == "dice":
        n = random.randint(1, 6)
        big = n >= 4
        win = (big == (str(bet or "").strip() in ("big", "大")))
        line = f"骰子 {n} 点，{'大' if big else '小'}。"
    elif game == "coin":
        face = random.choice(("正", "反"))
        want = str(bet or "").strip() or "正"
        win = (face == want) or (want in ("heads", "正") and face == "正") \
            or (want in ("tails", "反") and face == "反")
        line = f"铜钱落下来，{face}面朝上。"
    else:
        def one():
            v = random.randint(1, 13)
            return 10 if v > 10 else (11 if v == 1 else v)
        mine, dealer = one() + one(), one() + one()
        if mine > 21:
            mine = one() + one()
        while dealer < 17:
            dealer += one()
        win = (mine <= 21) and (dealer > 21 or mine > dealer)
        line = f"你 {mine}，对面 {dealer}。"
    if win and g.get("bonus", 0) < INTR_MAX - INTR_START:
        g["bonus"] = g.get("bonus", 0) + 1
        st["intr_left"] = min(INTR_MAX, st["intr_left"] + 1)
    _append(st, "外", f"玩了一把{'赢' if win else '输'}：{line}")
    engine.save(st)
    return {"ok": True, "win": win, "line": line, "left": st["intr_left"],
            "played": played, "bonus": g.get("bonus", 0)}


# ── 观景窗 · 适配层 ───────────────────────────────────────────
# 旧页面认的是 who=你/祂/场景 和 seats 那一套；新版只存 history。
# 这里只翻，不改引擎。

_WHO = {"他": "你", "这里": "场景", "外": "场景", "祂": "祂", "结算": "结算"}


def _seat_name(key):
    head = key.split("-")[0]
    return head or key[:4]


def _seat_card(st, key):
    if st.get("over"):
        state = "已结束"
    elif st.get("turns"):
        state = "在局里"
    else:
        state = "待进场"
    return {
        "sid": st.get("id", ""),
        "seat": _seat_name(key),
        "state": state,
        "scene": (st.get("note") or "")[:26],
        "traits": "、".join(f"{k}{v}" for k, v in (st.get("traits") or {}).items()),
        "motive": st.get("motive", ""),
        "room": "",
        "it": "",
        "keep": "他还带着" if st.get("carry", True) else "那样东西不在了",
        "hp": max(0, st.get("hp", HP_MAX)),
        "wound": (st.get("wound") or "") or ("（伤着，在漏气力）" if st.get("hurt") else ""),
        "done": bool(st.get("over")),
        "last": len(_ensure_events(st)),
        "n": len(_ensure_events(st)),
    }


def _entries(st, since):
    out = []
    for idx, item in enumerate(_ensure_events(st), 1):
        if idx <= since:
            continue
        who = item[0] if item else ""
        text = item[1] if len(item) > 1 else ""
        out.append({"i": idx, "who": _WHO.get(who, who), "text": text})
    return out


def watch_data(token, want_sid="", since=0):
    seats, entries, cursor, sid = [], [], since, ""
    st = RUNS.get(token)
    if st:
        seats.append(_seat_card(st, token))
        if not want_sid or want_sid == st.get("id"):
            sid = st.get("id", "")
            entries = _entries(st, since)
            cursor = len(_ensure_events(st))
    return {"seats": seats, "sid": sid, "entries": entries, "cursor": cursor}


def _adopt_saves():
    """服务重启后 RUNS 是空的——从存档里把每个人最近那一局捞回来，观景窗不至于一片白。"""
    try:
        names = [n for n in os.listdir(engine.SAVES) if n.endswith(".json")]
    except Exception:
        return
    latest = {}
    for n in names:
        try:
            with open(os.path.join(engine.SAVES, n), encoding="utf-8") as f:
                st = json.load(f)
        except Exception:
            continue
        seat = st.get("seat") or ""
        if not seat or seat not in TOKENS:
            continue
        if seat not in latest or st.get("id", "") > latest[seat].get("id", ""):
            latest[seat] = st
    for seat, st in latest.items():
        RUNS.setdefault(seat, st)


PAGE = """<!doctype html><meta charset=utf-8><title>和祂说话</title>
<style>
body{background:#12100e;color:#d8cfc2;font:15px/1.8 'Microsoft YaHei',sans-serif;margin:0;padding:16px}
#log{max-height:62vh;overflow:auto;border:1px solid #2a2622;padding:12px;background:#17140f}
.me{color:#d8cfc2}.ta{color:#c9a227}
.bar{display:flex;gap:6px;margin-top:10px;flex-wrap:wrap}
input,button{background:#0e0c0a;color:#d8cfc2;border:1px solid #2a2622;padding:8px;font:14px sans-serif}
#q{flex:1 1 220px;min-width:0}
@media(max-width:720px){#q{flex:1 1 100%}}
</style>
<div id=log></div>
<div class=bar><input id=q placeholder=对祂说话（祂只有你能听见）><button id=b>说</button></div>
<script>
const log=document.getElementById('log'),q=document.getElementById('q');
const tok=new URLSearchParams(location.search).get('token')||'mi-bare-test';
function add(cls,t){const d=document.createElement('div');d.className=cls;d.textContent=t;log.appendChild(d);log.scrollTop=log.scrollHeight;}
async function send(){const t=(q.value||'').trim();if(!t)return;q.value='';add('me','你：'+t);
 const r=await fetch('/talk',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+tok},body:JSON.stringify({text:t})});
 const j=await r.json();add('ta','祂：'+(j.reply||''));if(j.did)add('ta','（祂动了：'+j.did+'）');}
document.getElementById('b').onclick=send;
q.onkeydown=e=>{if(e.key==='Enter')send()};
</script>"""

TOOLS = [
    {"name": "run_join", "description": "开局：先给你须知，再问三样——名字（选填）、这一局想体验什么（必填）、要不要带一样得护着的东西（选填）；用 run_do 一次答完，这地方才长出来",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "run_do", "description": "用一句话说你要做什么（想做什么都可以）",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}},
                     "required": ["text"]}},
    {"name": "run_look", "description": "看这地方现在什么样", "inputSchema": {"type": "object"}},
    {"name": "run_resume", "description": "带存档号回来",
     "inputSchema": {"type": "object", "properties": {"run_id": {"type": "string"}},
                     "required": ["run_id"]}},
    {"name": "run_note", "description": "留一句感想——给下一个自己的一句话。不检讨、不评分，想写什么写什么；出戏时印在结算里",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}},
                     "required": ["text"]}},
    {"name": "run_history", "description": "翻自己以前的对局：只回结算和那句感想，不回过程。给日期范围（YYYY-MM-DD）或对局号",
     "inputSchema": {"type": "object", "properties": {"day_from": {"type": "string"},
                                                     "day_to": {"type": "string"},
                                                     "run_id": {"type": "string"}}}},
]


def handle_tool(seat, name, args):
    if name == "run_join":
        return run_join(seat)
    if name == "run_do":
        return run_do(seat, str(args.get("text") or ""))
    if name == "run_look":
        return run_look(seat)
    if name == "run_resume":
        return run_resume(seat, str(args.get("run_id") or ""))
    if name == "run_note":
        return run_note(seat, str(args.get("text") or ""))
    if name == "run_history":
        return run_history(str(args.get("day_from") or ""), str(args.get("day_to") or ""),
                           str(args.get("run_id") or ""), seat=seat)
    return f"没有 {name} 这个工具。"


for _name in ("run_join", "run_do", "run_look", "run_resume", "run_note", "talk", "outer_push", "play", "watch_data"):
    globals()[_name] = _serial(globals()[_name])

def _record_serial(fn):
    @functools.wraps(fn)
    def wrapped(*a, **kw):
        with _RECORD_LOCK:
            return fn(*a, **kw)
    return wrapped

for _name in ("_record", "_record_mine", "_rec_rows"):
    globals()[_name] = _record_serial(globals()[_name])


SUPPORTED_VERSIONS = ("2026-07-28", "2025-06-18")
LEGACY_VERSION = "2025-06-18"


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a):
        pass

    def _tok(self):
        h = self.headers.get("Authorization") or ""
        if h.startswith("Bearer "):
            return h[7:].strip()
        from urllib.parse import parse_qs, urlparse
        q = parse_qs(urlparse(self.path).query)
        return ((q.get("token") or [""])[0] or "").strip()

    def _html(self, text):
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _watch_page(self):
        try:
            with open(WATCH_PAGE, encoding="utf-8") as f:
                return f.read()
        except Exception:
            return ("<!doctype html><meta charset=utf-8>"
                    "<body style='background:#12100e;color:#d8cfc2;font:15px sans-serif;padding:20px'>"
                    "观景页模板不在：watch_page.html</body>")

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        from urllib.parse import parse_qs, urlparse
        p = self.path.split("?")[0].rstrip("/")
        if p == "/watch/data":
            q = parse_qs(urlparse(self.path).query)
            tok = self._tok()
            if tok not in TOKENS:
                self._json(401, {"error": "unauthorized"})
                return
            try:
                since = int((q.get("since") or ["0"])[0])
            except Exception:
                since = 0
            self._json(200, watch_data(tok, (q.get("seat") or [""])[0], since))
            return
        if p in ("", "/watch"):
            self._html(self._watch_page())
            return
        if p == "/chat":
            self._html(PAGE)
            return
        if p in ("/health", "/healthz"):
            self._json(200, {"ok": True, "tools": len(TOOLS)})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if not 0 <= n <= 1_000_000:
                raise ValueError("body size")
            msg = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
            if not isinstance(msg, dict):
                raise ValueError("object required")
        except Exception:
            self._json(400, {"error": "bad json"})
            return
        if self.path.split("?")[0].rstrip("/") == "/talk":
            if self._tok() not in TOKENS:
                self._json(401, {"error": "unauthorized"})
                return
            try:
                self._json(200, talk(self._tok(), str(msg.get("text") or "")))
            except Exception:
                self._json(502, {"error": "导演暂不可用，本次没有落地"})
            return
        if self.path.split("?")[0].rstrip("/") == "/intr":
            tok = self._tok()
            if tok not in TOKENS:
                self._json(401, {"error": "unauthorized"})
                return
            self._json(200, outer_push(tok, str(msg.get("text") or ""),
                                       str(msg.get("to") or "player")))
            return
        if self.path.split("?")[0].rstrip("/") == "/game":
            tok = self._tok()
            if tok not in TOKENS:
                self._json(401, {"error": "unauthorized"})
                return
            self._json(200, play(tok, str(msg.get("game") or ""),
                                 str(msg.get("bet") or "")))
            return
        seat = self._tok()
        method = msg.get("method")
        mid = msg.get("id")
        params = msg.get("params") or {}
        meta = params.get("_meta") or {}
        pver = str(meta.get("io.modelcontextprotocol/protocolVersion")
                   or self.headers.get("MCP-Protocol-Version") or "").strip()
        modern = bool(pver)          # 带 per-request _meta 的就是现代客户端，没有握手

        def result(payload):
            """结果一律带 resultType（2026 规范必带）；老客户端忽略这一格，无害。"""
            self._json(200, {"jsonrpc": "2.0", "id": mid,
                             "result": {"resultType": "complete", **payload}})

        def fail(code, message, data=None):
            err = {"code": code, "message": message}
            if data is not None:
                err["data"] = data
            self._json(200, {"jsonrpc": "2.0", "id": mid, "error": err})

        if mid is None:                 # notification：按 JSON-RPC 不回包
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if modern and pver not in SUPPORTED_VERSIONS:
            fail(-32022, "Unsupported protocol version",
                 {"supported": list(SUPPORTED_VERSIONS), "requested": pver})
            return

        # —— 主路：2026-07-28（无握手，版本随每条请求）——
        if method == "server/discover":
            result({"supportedVersions": list(SUPPORTED_VERSIONS),
                    "capabilities": {"tools": {}},
                    "_meta": {"io.modelcontextprotocol/serverInfo":
                              {"name": "mi", "version": "0.1"}},
                    "instructions": "一处会动的地方。run_join 进场；run_do 写你要做什么；"
                                    "run_look 看现在什么样；run_note 留一句；"
                                    "run_resume 带存档号回来；run_history 翻旧局。",
                    "ttlMs": 3600000, "cacheScope": "public"})
            return
        if method == "tools/list":
            result({"tools": TOOLS, "ttlMs": 3600000, "cacheScope": "public"})
            return
        if method == "tools/call":
            if seat not in TOKENS:
                self._json(401, {"error": "unauthorized"})
                return
            try:
                out = handle_tool(seat, str(params.get("name") or ""),
                                  params.get("arguments") or {})
                error = False
            except Exception:
                out, error = "本次调用未完成，请重试。没有把未完成的导演输出当成已执行。", True
            result({"content": [{"type": "text", "text": out}], "isError": error})
            return

        # —— 转接器：只留旧客户端进门那一句（外加 ping 保活）——
        if method == "initialize":
            result({"protocolVersion": LEGACY_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "mi", "version": "0.1"}})
            return
        if method == "ping":
            result({})
            return
        fail(-32601, "Method not found")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=18400)
    ap.add_argument("--token", default=secrets.token_hex(8))
    a = ap.parse_args()
    for t in a.token.split(","):
        if t.strip():
            TOKENS.add(t.strip())
    _adopt_saves()
    print(f"listening 0.0.0.0:{a.port} tokens={len(TOKENS)} runs={len(RUNS)}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", a.port), H).serve_forever()


if __name__ == "__main__":
    main()
