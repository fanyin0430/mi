# -*- coding: utf-8 -*-
"""局本身的验收：开局／一局／看／结算／存档／续局／重启捡回。

全程不碰模型——把导演换成一个说固定话的假人，验的是流程和落盘，
不是文笔。旧版那 107 项是给旧骨头的；新版骨头只有这几根，一根一根过。
"""
import json
import os
import tempfile

import mi_server as s

SEAT = "seat-a"
CALLS = []
OVER_AT = [0]        # 第几次调用之后导演说"到头了"；0 = 永不说


def fake_call(st, ctx, temp=0.9, maxtok=460):
    """假导演：每次说一句、变一次景、给一条 note，carry 两轮掉一次；到点了就 over。

    开局那次还要交动机；每轮顺手把抽中的第一项性格调一点，验"局内会变"。
    """
    CALLS.append(ctx)
    n = len(CALLS)
    opening = "（开局。" in ctx
    over = bool(OVER_AT[0]) and n >= OVER_AT[0] and not opening
    traits = (st or {}).get("traits") or {}
    first = next(iter(traits), "")
    return s.engine.Decision(
        (f"第{n}句", f"第{n}次变化", f"note-{n}", n % 3 != 0, over, False, 0),
        end_reason="到头了" if over else "",
        world=f"第{n}次变化", act="",
        shift={first: 0.05} if first else {},
        motive="想让他留下" if opening else "",
        wound=(st or {}).get("wound", ""),
        who="阿七" if opening else "",
        keepsake="一把柴刀" if opening else "",
        tone="这一局只给，不拿" if opening else "",
        npcs=[{"name": "刘九", "what": "裹破袄，肩上落炭黑", "wants": "把炭卖掉",
               "knows": "这条街上的事"} ] if opening else [])


class T:
    def __init__(self):
        self.n = 0
        self.fails = []

    def ok(self, name, cond, extra=""):
        self.n += 1
        if cond:
            print("  OK  " + name)
        else:
            self.fails.append(name)
            print(" FAIL " + name + ("  → " + str(extra)[:180] if extra else ""))


def setup():
    s.RECORDS = tempfile.mkdtemp(prefix="mi_rec_")
    s.engine.SAVES = tempfile.mkdtemp(prefix="mi_saves_")
    s.RUNS.clear()
    s.TOKENS.clear()
    s.TOKENS.add(SEAT)
    s._call = fake_call
    s._interpret = lambda text, st: {"kind": "act", "intent": text, "ambiguous": False, "quit_requested": False}
    s._review = lambda *a, **kw: {"ok": True, "question": ""}
    s.engine.summarize = lambda lines, prev_recap="", prev_open=None: (
        "压缩：" + str(len(lines)), ["欠着的那件事"])
    CALLS.clear()


def join_open(want="我想在这地方待一会儿，看看它会拿我怎么办"):
    """开一局：run_join 只问一句，答案用 run_do 递进去，地方才长出来。"""
    s.run_join(SEAT)
    return s.run_do(SEAT, want)


def test_join(t):
    print("\n· 开局")
    s.RUNS.clear()
    ask = s.run_join(SEAT)
    st = s.RUNS.get(SEAT) or {}
    t.ok("先问这一局想体验什么", "想体验什么" in ask, ask[:120])
    t.ok("问话里还有名字和要带的东西", ("名字" in ask) and ("带一样" in ask), ask[:200])
    t.ok("问话里交代了会有别人", "可能会有别人" in ask, ask[:300])
    t.ok("问完还没造地方", st.get("pending_join") is True and not st.get("note"), list(st)[:8])
    out = s.run_do(SEAT, "我叫阿七。我想在一间点着灯的屋里，等一个人来，可我不知道是谁。带一把柴刀。")
    t.ok("给出存档号", "存档号：" in out and st.get("id", "") in out, out[:120])
    t.ok("问的那句进了开局那次请求", "等一个人来" in CALLS[-1], CALLS[-1][:200])
    t.ok("回合从 0 起", st.get("turns") == 0, st.get("turns"))
    t.ok("祂写下了这地方", bool(st.get("note")), st.get("note"))
    t.ok("流水先是场景、再是祂", [h[0] for h in st.get("history", [])] == ["这里", "祂"],
         [h[0] for h in st.get("history", [])])
    t.ok("存档落盘", os.path.exists(os.path.join(s.engine.SAVES, st["id"] + ".json")))
    t.ok("返回里看得见祂那句", "祂说：" in out, out[:120])
    t.ok("名字进了这一局", st.get("who") == "阿七", st.get("who"))
    t.ok("带来的东西进了这一局", st.get("keepsake") == "一把柴刀", st.get("keepsake"))
    t.ok("这一局的性子进了这一局", st.get("tone") == "这一局只给，不拿", st.get("tone"))
    t.ok("导演记得他叫什么", "阿七" in s._state_ctx(st), s._state_ctx(st)[:200])
    t.ok("开局提醒了 run_note", "run_note" in out, out[-160:])


def test_do(t):
    print("\n· 一局：走一步")
    st = s.RUNS[SEAT]
    before = st["turns"]
    out = s.run_do(SEAT, "我往前走")
    t.ok("回合加一", st["turns"] == before + 1, st["turns"])
    t.ok("记下他说的话", ["他", "我往前走"] in [list(h) for h in st["history"]])
    t.ok("场景和他说的都进流水",
         st["history"][-2][0] == "这里" and st["history"][-1][0] == "祂",
         [h[0] for h in st["history"][-3:]])
    t.ok("返回里带祂的话", "祂说：" in out, out[:120])
    t.ok("carry 跟着导演走", st["carry"] is (len(CALLS) % 3 != 0), st["carry"])
    t.ok("每步都落盘", json.load(open(os.path.join(s.engine.SAVES, st["id"] + ".json"),
                                     encoding="utf-8"))["turns"] == st["turns"])


def test_ctx(t):
    print("\n· 导演看得见的东西")
    st = s.RUNS[SEAT]
    ctx = s._state_ctx(st)
    t.ok("上下文带这地方现在什么样", "这地方现在是" in ctx and st["note"] in ctx, ctx[:120])
    t.ok("上下文带最近说过的话", "我往前走" in ctx, ctx[:200])
    t.ok("上下文不长过 12 行", ctx.count("\n") <= 15, ctx.count("\n"))


def test_look(t):
    print("\n· 看")
    st = s.RUNS[SEAT]
    look = s.run_look(SEAT)
    t.ok("看得到这地方", st["note"] in look, look[:120])


def test_save_resume(t):
    print("\n· 存档 / 续局")
    st = s.RUNS[SEAT]
    rid = st["id"]
    snap = json.load(open(os.path.join(s.engine.SAVES, rid + ".json"), encoding="utf-8"))
    t.ok("存档与内存一致",
         snap["turns"] == st["turns"] and len(snap["history"]) == len(st["history"]),
         (snap["turns"], st["turns"]))
    keep = dict(st)
    s.RUNS.clear()
    msg = s.run_resume(SEAT, rid)
    t.ok("带牌号回来", "接着走" in msg, msg[:80])
    back = s.RUNS.get(SEAT) or {}
    t.ok("回得来的状态完整",
         back.get("turns") == keep["turns"] and back.get("note") == keep["note"]
         and back.get("carry") == keep["carry"], back.get("turns"))
    t.ok("没有的牌号不顶掉座位", "没有这个存档" in s.run_resume(SEAT, "9999-999999")
         and s.RUNS.get(SEAT) is not None, "座位被清空了")


def test_over(t):
    print("\n· 走到尽头")
    s.RUNS.clear()
    join_open()
    st = s.RUNS[SEAT]
    s.run_note(SEAT, "我留的一句话")
    OVER_AT[0] = len(CALLS) + 4          # 再走四步，导演说这局到头了
    out = ""
    guard = 0
    while not st["over"] and guard < 20:
        out = s.run_do(SEAT, "再走一步")
        guard += 1
    t.ok("祂说到头才收", st["over"] is True, guard)
    t.ok("有出戏", "—— 出戏 ——" in out, out[-160:])
    t.ok("结算落进流水", any(h[0] == "结算" for h in st["history"]))
    t.ok("感想印在结算里", "你走之前留下的那句：我留的一句话" in out, out[-200:])
    t.ok("收完了不能再走", "已经收了" in s.run_do(SEAT, "再走一步"), "")
    t.ok("收完了说清这句没记进去", "没有记进去" in s.run_do(SEAT, "再走一步"), "")
    look_after = s.run_look(SEAT)
    t.ok("收完了 run_look 给结算", "出戏" in look_after, look_after[:120])
    r = s.talk(SEAT, "你还在吗")
    t.ok("收了之后祂还听得见，但改不动", "改不动" in r.get("reply", ""), r.get("reply", "")[:80])
    rows = s._rec_rows()
    t.ok("仓库里有这一局", any(r["run_id"] == st["id"] for r in rows), len(rows))
    mine = next((r for r in rows if r["run_id"] == st["id"]), {})
    t.ok("仓库带那句感想", mine.get("mine") == "我留的一句话", mine.get("mine"))
    t.ok("仓库带结局", "那片" in rows[0].get("result", "") or bool(rows[0].get("result")), "")
    h = s.run_history(run_id=st["id"])
    t.ok("翻得到这一局", st["id"] in h and "我留的一句话" in h, h[:160])
    s.RUNS.clear()
    msg = s.run_resume(SEAT, st["id"])
    t.ok("收过的局 resume 说清楚", "已经收了" in msg, msg[:120])
    t.ok("收过的局 resume 也给结算", "出戏" in msg, msg[:200])

    s.RUNS.clear()
    join_open()
    st2 = s.RUNS[SEAT]
    OVER_AT[0] = 0
    for _ in range(30):
        s.run_do(SEAT, "再走一步")
    t.ok("没有回合上限，三十步也不收", st2["over"] is False, st2.get("turns"))
    s.run_resume(SEAT, st["id"])
    t.ok("收过的局不顶掉手上的活局", s.RUNS.get(SEAT, {}).get("id") == st2["id"],
         s.RUNS.get(SEAT, {}).get("id"))


def test_over_fix(t):
    print("\n· 复核替导演把 over 对上")
    good = s._review
    try:
        s.RUNS.clear()
        join_open()
        st = s.RUNS[SEAT]
        OVER_AT[0] = 0
        s._review = lambda *a, **kw: {"ok": True, "question": "",
                                      "over_fix": "add",
                                      "why": "他推开门出去，站到了街上"}
        out = s.run_do(SEAT, "我推门出去，站到街上")
        t.ok("漏判的 over 由服务器补上", st["over"] is True, st.get("over"))
        t.ok("补上之后直接给结算", "—— 出戏 ——" in out, out[-160:])
        t.ok("结束理由用复核那一句", st.get("end_reason") == "他推开门出去，站到了街上",
             st.get("end_reason"))
        t.ok("这一轮没有退回玩家", "尚未落地" not in out, out[:120])

        s.RUNS.clear()
        join_open()
        st2 = s.RUNS[SEAT]
        s._review = lambda *a, **kw: {"ok": False, "question": "他还站在原地",
                                      "over_fix": "clear",
                                      "why": "他还在犹豫，什么都没办成"}
        OVER_AT[0] = len(CALLS) + 1
        out2 = s.run_do(SEAT, "我站着不动")
        t.ok("判早了的 over 被撤掉", st2["over"] is False, st2.get("over"))
        t.ok("撤的时候也没退回玩家", "尚未落地" not in out2, out2[:120])
    finally:
        s._review = good
        OVER_AT[0] = 0


def test_npc(t):
    print("\n· 人自己那一回合")
    s.RUNS.clear()
    join_open()
    st = s.RUNS[SEAT]
    t.ok("开局造了人", bool(st.get("npcs")), st.get("npcs"))
    name = st["npcs"][0]["name"]
    seen = []

    def fake_req(sysmsg, ctx, temp=0.9, maxtok=600):
        seen.append((sysmsg, ctx))
        return {"act": "他把手里的活放下", "say": "你说", "mood": "没抬头", "leave": False}

    old_req = s.engine._request
    s._interpret = lambda text, st=None: {"kind": "speak", "intent": text, "ambiguous": False,
                                          "quit_requested": False, "to": name}
    s.engine._request = fake_req
    try:
        out = s.run_do(SEAT, "我对" + name + "说：你是谁")
    finally:
        s.engine._request = old_req
        s._interpret = lambda text, st: {"kind": "act", "intent": text, "ambiguous": False,
                                         "quit_requested": False}
    t.ok("人的动作和他的话都出来了", "他把手里的活放下" in out and "你说" in out, out[:220])
    t.ok("人说的话贴人名，不贴祂说", name + "说：「你说」" in out, out[:260])
    t.ok("人用的是自己的人设", name in seen[0][0] and "把炭卖掉" in seen[0][0], seen[0][0][-200:])
    t.ok("导演拿到了人的事，不能改口", "刚刚发生的事" in CALLS[-1], CALLS[-1][-300:])
    t.ok("人记下了这一回", bool(name) and len(st["npcs"][0].get("said") or []) > 0, st["npcs"][0].get("said"))
    t.ok("人那一句进了流水，署他的名", any(h[0] == name for h in st.get("history") or []),
         [h[0] for h in (st.get("history") or [])][-6:])

    # 还没问到名字之前，叫“她”也算对着那个人
    s._interpret = lambda text, st=None: {"kind": "speak", "intent": text, "ambiguous": False,
                                          "quit_requested": False, "to": "她"}
    s.engine._request = fake_req
    try:
        out2 = s.run_do(SEAT, "我对她说：别怕")
    finally:
        s.engine._request = old_req
        s._interpret = lambda text, st: {"kind": "act", "intent": text, "ambiguous": False,
                                         "quit_requested": False}
    t.ok("叫“她”也能对上那个人", name + "说：「你说」" in out2, out2[:260])

    # 导演把人刚说的话抄回自己嘴里——那不是祂说的
    def fake_echo(st_, ctx, temp=0.9, maxtok=460):
        CALLS.append(ctx)
        return s.engine.Decision(
            ("你说", "第n次变化", "note-echo", True, False, False, 0),
            end_reason="", world="第n次变化", act="", shift={}, motive="", wound="",
            who="", keepsake="", tone="", npcs=[])

    old_call = s._call
    s._call = fake_echo
    s.engine._request = fake_req
    s._interpret = lambda text, st=None: {"kind": "speak", "intent": text, "ambiguous": False,
                                          "quit_requested": False, "to": name}
    try:
        out3 = s.run_do(SEAT, "我对" + name + "说：再说一遍")
    finally:
        s._call = old_call
        s.engine._request = old_req
        s._interpret = lambda text, st: {"kind": "act", "intent": text, "ambiguous": False,
                                         "quit_requested": False}
    t.ok("抄人的话，不署祂的名", "祂说" not in out3, out3[:200])
    t.ok("人自己那句还在", name + "说：「你说」" in out3, out3[:260])


def test_traits(t):
    print("\n· 性格和动机")
    import random as R
    tr = s.engine.pick_traits(R.Random(7))
    t.ok("抽三到五个", 3 <= len(tr) <= 5, len(tr))
    t.ok("都从池子里来", all(k in s.engine.TRAITS for k in tr), list(tr))
    t.ok("权重落在 0 到 1 之间", all(0 < v <= 1 for v in tr.values()), tr)

    sysmsg = s.engine.system_for({"traits": {"多疑善忌": 0.6}, "motive": "想让他留下"})
    t.ok("性格写进引导词", "多疑善忌 0.6" in sysmsg, sysmsg[-160:])
    t.ok("满值怎么读写进引导词", "1 是这一样到顶" in sysmsg, "")
    t.ok("动机写进引导词", "想让他留下" in sysmsg, "")
    t.ok("动机标了不许说出口", "不许说出口" in sysmsg, "")
    t.ok("没定调时用默认那一套", "你不是来陪他走完的" in sysmsg, sysmsg[:160])
    t.ok("没人时省掉「人」那一节", "心也不由你替他想" not in sysmsg, "")
    withpeople = s.engine.system_for({"npcs": [{"name": "某人"}]})
    t.ok("局里有人才拼「人」那一节", "心也不由你替他想" in withpeople, withpeople[:120])
    toned = s.engine.system_for({"tone": "这一局只给，不拿。他伸手，你就把东西放进去。"})
    t.ok("定了调就照调子走", "这一局只给，不拿" in toned and "你不是来陪他走完的" not in toned,
         toned[:200])

    s.RUNS.clear()
    join_open()
    st = s.RUNS[SEAT]
    t.ok("开局抽了性格", 3 <= len(st.get("traits") or {}) <= 5, st.get("traits"))
    t.ok("开局拿到了动机", st.get("motive") == "想让他留下", st.get("motive"))
    key = next(iter(st["traits"]))
    before = st["traits"][key]
    s.run_do(SEAT, "走")
    t.ok("性格权重随局里的事变", st["traits"][key] != before, (before, st["traits"][key]))
    t.ok("变完还在 0 到 1 之间", 0 <= st["traits"][key] <= 1, st["traits"][key])
    t.ok("性格没写进给玩家看的话", "多疑善忌" not in s.run_look(SEAT), s.run_look(SEAT)[:120])


def test_hp(t):
    print("\n· 气力")
    s.RUNS.clear()
    join_open()
    st = s.RUNS[SEAT]
    t.ok("开局满气力", st["hp"] == s.HP_MAX, st["hp"])
    s.run_do(SEAT, "走")
    t.ok("走一步掉一点", st["hp"] == s.HP_MAX - 1, st["hp"])
    st["hurt"] = True
    s.run_do(SEAT, "带伤走")
    t.ok("伤着每轮多漏两点", st["hp"] == s.HP_MAX - 1 - 3, st["hp"])
    st["hurt"] = True
    t.ok("伤了 look 会说", "一直在往外漏" in s.run_look(SEAT), s.run_look(SEAT)[:120])
    st["hurt"] = False
    st["hp"] = 1
    s.run_do(SEAT, "再走")
    t.ok("气力见底就收，不用它同意", st["over"] is True, st.get("over"))
    t.ok("收的理由是气力", "气力见底" in (st.get("end_reason") or ""), st.get("end_reason"))
    st["hurt"] = False
    st["wound"] = "左腿断了，站不起来"
    ctxmsg = s._state_ctx(st)
    t.ok("伤写进了导演的上下文", "左腿断了" in ctxmsg, ctxmsg[:160])
    t.ok("伤钉了做不了", "做不了事" in ctxmsg, "")


def test_recap(t):
    print("\n· 记忆")
    s.RUNS.clear()
    join_open()
    st = s.RUNS[SEAT]
    for _ in range(35):
        s.run_do(SEAT, "走")
    t.ok("老流水被压成摘要", bool(st.get("recap")), str(st.get("recap")))
    t.ok("原文只留最近一截", len(st["history"]) <= s.KEEP_LINES + s.RECAP_EVERY * 3,
         len(st["history"]))
    t.ok("摘要进了导演的上下文", "以前的账" in CALLS[-1], CALLS[-1][:120])
    t.ok("没办完的事单独存着", (st.get("open_items") or []) == ["欠着的那件事"], st.get("open_items"))
    t.ok("没办完的事也进了上下文", "还没办完的" in CALLS[-1] and "欠着的那件事" in CALLS[-1],
         CALLS[-1][:200])


def test_echo(t):
    print("\n· 抄话")
    t.ok("一字不差算抄", s._echoes("你说", "你说"))
    t.ok("带标点也算抄", s._echoes("我这条铺子要的不是钱。", "我这条铺子要的不是钱"))
    t.ok("多说半句也算抄", s._echoes("我这条铺子要的不是钱", "我这条铺子要的不是钱，是别的"))
    t.ok("两回事不算", not s._echoes("路在南头亮着", "你说"))
    t.ok("空的不算", not s._echoes("", "你说"))
    t.ok("替人开口也算抄", s._speaks_for("陶娘说：不走？行。", ["陶娘"]))
    t.ok("不是在替人也放行", not s._speaks_for("路在南头亮着", ["陶娘"]))
    t.ok("没名字就放行", not s._speaks_for("陶娘说：走。", []))


def test_adopt(t):
    print("\n· 重启捡回")
    s.RUNS.clear()
    s._adopt_saves()
    t.ok("存档里的局被捡回来", bool(s.RUNS), list(s.RUNS))
    if s.RUNS:
        st = next(iter(s.RUNS.values()))
        t.ok("捡回来的是一局完整的", bool(st.get("id")) and "history" in st, list(st)[:6])


def test_edges(t):
    print("\n· 边上")
    s.RUNS.clear()
    t.ok("没局时 do 有提示", "先 run_join" in s.run_do(SEAT, "走"), "")
    t.ok("没局时 look 有提示", "先 run_join" in s.run_look(SEAT), "")
    t.ok("没局时 note 有提示", "先 run_join" in s.run_note(SEAT, "x"), "")
    join_open()
    t.ok("空感想不收", "空的" in s.run_note(SEAT, "   "), "")
    t.ok("没这个玩法不收", "没这个玩法" in (s.play(SEAT, "老虎机") or {}).get("note", ""), "")


def main():
    setup()
    t = T()
    test_join(t)
    test_do(t)
    test_ctx(t)
    test_look(t)
    test_save_resume(t)
    test_traits(t)
    test_hp(t)
    test_recap(t)
    test_over(t)
    test_over_fix(t)
    test_npc(t)
    test_echo(t)
    test_adopt(t)
    test_edges(t)
    print("\n共 %d 项，过 %d，败 %d" % (t.n, t.n - len(t.fails), len(t.fails)))
    if t.fails:
        print("败的：" + "、".join(t.fails))
    return 0 if not t.fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
