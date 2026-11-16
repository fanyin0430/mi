# -*- coding: utf-8 -*-
"""观景窗接线自测：假局塞进 RUNS，起服务，逐条验。

牌走 Authorization 头，不走 URL——地址栏永远是干净的 /watch。
"""
import json
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import mi_server as s

TOKEN = "test-token"


def get(path, token=None):
    req = urllib.request.Request("http://127.0.0.1:18999" + path)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        r = urllib.request.urlopen(req, timeout=5)
        return r.status, r.read().decode("utf-8"), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8"), e.headers.get("Content-Type", "")


def post(path, obj, token=None):
    data = json.dumps(obj).encode("utf-8")
    req = urllib.request.Request("http://127.0.0.1:18999" + path, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        r = urllib.request.urlopen(req, timeout=5)
        return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def main():
    s.RECORDS = tempfile.mkdtemp(prefix="mi_rec_")
    s.engine.SAVES = tempfile.mkdtemp(prefix="mi_watch_saves_")
    s.TOKENS.add(TOKEN)
    check_empty = "还没有对局记录" in s.run_history()
    s.RUNS[TOKEN] = {
        "id": "1115-090000",
        "note": "一条潮得发黑的长廊，脚下是水。",
        "history": [("这里", "长廊，水没过鞋底。"),
                    ("祂", "「别应。」"),
                    ("他", "我应了。"),
                    ("这里", "有人在盒子里喊你的名字。")],
        "turns": 2, "carry": False, "over": False, "seat": TOKEN,
    }
    srv = ThreadingHTTPServer(("127.0.0.1", 18999), s.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    ok = True

    def check(name, cond, extra=""):
        nonlocal ok
        print(("  OK  " if cond else " FAIL ") + name + (("  → " + extra) if extra and not cond else ""))
        ok = ok and cond

    st, body, ct = get("/health")
    check("/health", st == 200 and '"tools": 6' in body, body[:120])

    # 地址干净：不带任何参数，直接就是页面
    st, body, ct = get("/watch")
    check("/watch 无参数 200", st == 200 and "观景窗" in body, ct)
    check("/watch 页面不烧进任何牌", TOKEN not in body, body[:80])
    check("/watch 页面不带 token 参数", "watch/data?token=" not in body, "")

    st, body, ct = get("/")
    check("/ 同一扇窗", st == 200 and "观景窗" in body, body[:80])

    st, body, ct = get("/watch/data?since=0")
    check("无牌拉数据 401", st == 401, body[:80])

    st, body, ct = get("/watch/data?since=0", TOKEN)
    d = json.loads(body) if st == 200 else {}
    seats = d.get("seats") or []
    check("/watch/data 带牌 200", st == 200, body[:120])
    check("seat 名取牌号前半", bool(seats) and seats[0].get("seat") == TOKEN.split("-")[0], str(seats))
    check("sid", d.get("sid") == "1115-090000", str(d.get("sid")))
    entries = d.get("entries") or []
    check("entries 4 条", len(entries) == 4, str(len(entries)))
    whos = [e["who"] for e in entries]
    check("who 映射 场景/祂/你", whos == ["场景", "祂", "你", "场景"], str(whos))
    check("keep 文案 false", seats and "那样东西不在了" in seats[0].get("keep", ""), str(seats))
    check("不再报动作剩", "acts" not in (seats[0] if seats else {}), str(seats))
    check("cursor=4", d.get("cursor") == 4, str(d.get("cursor")))

    st, body, ct = get("/watch/data?since=3", TOKEN)
    d2 = json.loads(body)
    check("游标增量只给 1 条", len(d2.get("entries") or []) == 1, str(d2.get("entries")))

    st, body, ct = get("/watch/data?seat=9999-000000&since=0", TOKEN)
    d3 = json.loads(body)
    check("sid 不匹配时不给日志", (d3.get("entries") or []) == [], str(d3)[:120])

    st, body, ct = get("/watch/data?since=0", "nope-1234")
    check("错牌 401", st == 401, body[:80])

    st, body, ct = get("/chat", TOKEN)
    check("/chat 和祂说话", st == 200 and "和祂说话" in body, body[:80])

    # ── 那只手 ──────────────────────────────────────────────
    st, body = post("/intr", {"text": "别回头", "to": "player"})
    check("/intr 无牌 401", st == 401, body[:80])

    st, body = post("/intr", {"text": "别回头", "to": "player"}, TOKEN)
    j = json.loads(body)
    check("/intr 对机 ok", st == 200 and j.get("ok") and j.get("left") == 4, body[:120])
    check("话进了祂的嘴", ["祂", "「别回头」"] in [list(x) for x in s.RUNS[TOKEN]["history"]], "")

    look = s.run_look(TOKEN)
    check("run_look 吐出那句", "祂说：「别回头」" in look, look[:120])
    check("吐一次就没了", "别回头" not in s.run_look(TOKEN), "")

    st, body = post("/intr", {"text": "让他听见水声", "to": "dir"}, TOKEN)
    j = json.loads(body)
    check("/intr 对导演 ok", st == 200 and j.get("ok") and j.get("to") == "dir", body[:120])
    check("导演那条进了 outer", s.RUNS[TOKEN].get("outer") == ["让他听见水声"],
          str(s.RUNS[TOKEN].get("outer")))
    ctx = s._state_ctx(s.RUNS[TOKEN])
    check("context 里有外人的手", "让他听见水声" in ctx, ctx[:160])
    check("context 里没有插手留痕", "伸了一只手" not in ctx, "")

    st, body = post("/intr", {"text": "", "to": "player"}, TOKEN)
    check("/intr 空话不扣次数", json.loads(body).get("ok") is False and
          s.RUNS[TOKEN]["intr_left"] == 3, body[:120])

    for _ in range(3):
        post("/intr", {"text": "再说一句", "to": "player"}, TOKEN)
    st, body = post("/intr", {"text": "第六次", "to": "player"}, TOKEN)
    j = json.loads(body)
    check("五次用完就关门", j.get("ok") is False and "用完" in (j.get("note") or ""), body[:120])

    st, body = post("/game", {"game": "dice", "bet": "big"}, TOKEN)
    j = json.loads(body)
    check("/game 赌大小", st == 200 and j.get("ok") and "骰子" in (j.get("line") or ""), body[:140])
    check("/game 报剩余次数", isinstance(j.get("left"), int), body[:140])

    st, body = post("/game", {"game": "card", "bet": ""}, TOKEN)
    check("/game 21点", json.loads(body).get("ok") is True, body[:140])

    st, body = post("/game", {"game": "老虎机", "bet": ""}, TOKEN)
    check("/game 没这个玩法", json.loads(body).get("ok") is False, body[:120])

    played_now = s.RUNS[TOKEN]["games"]["played"]
    for _ in range(s.GAMES_PER - played_now.get("coin", 0)):
        post("/game", {"game": "coin", "bet": "正"}, TOKEN)
    st, body = post("/game", {"game": "coin", "bet": "正"}, TOKEN)
    j = json.loads(body)
    check("同一样五把封顶", j.get("ok") is False and "玩够" in (j.get("note") or ""), body[:120])

    st, body, ct = get("/watch/data?since=0", TOKEN)
    whos = [e["who"] for e in json.loads(body).get("entries") or []]
    check("插手在观景窗里是灰的", "外" not in whos and "场景" in whos, str(whos))

    # ── 感想 ──────────────────────────────────────────────
    s.RUNS[TOKEN]["outer"] = ["只递一次"]
    s._state_ctx(s.RUNS[TOKEN])
    check("构造上下文不提前清掉待递消息", s._state_ctx(s.RUNS[TOKEN]).count("只递一次") == 1, "")

    s.RUNS[TOKEN]["over"] = True
    st2, body = post("/intr", {"text": "还能伸手吗", "to": "player"}, TOKEN)
    j = json.loads(body)
    check("收了之后手伸不进去", j.get("ok") is False and "收了" in (j.get("note") or ""), body[:120])
    st2, body = post("/game", {"game": "dice", "bet": "big"}, TOKEN)
    j = json.loads(body)
    check("收了之后换不出次数", j.get("ok") is False and "收了" in (j.get("note") or ""), body[:120])
    s.RUNS[TOKEN]["over"] = True

    msg = s.run_note(TOKEN, "灯灭了以后我没回头。")
    check("run_note 留住了", s.RUNS[TOKEN].get("mine") == "灯灭了以后我没回头。", msg)
    check("出戏后补进结算", any(h[0] == "结算" and "你走之前留下的那句：灯灭了以后我没回头。" in h[1]
                              for h in s.RUNS[TOKEN]["history"]), "")
    s.run_note(TOKEN, "改一句。")
    hits = [h for h in s.RUNS[TOKEN]["history"]
            if h[0] == "结算" and "你走之前留下的那句" in h[1]]
    check("重写不重复", len(hits) == 1 and "改一句" in hits[0][1], str(len(hits)))
    check("空感想不收", "空的" in s.run_note(TOKEN, "  "), "")

    # ── 仓库 · 对局记录 ────────────────────────────────────
    check("还没局时仓库是空的", check_empty, "")
    s.RUNS[TOKEN]["id"] = "1115-070001"          # 库里还什么都没有的一局，靠感想补录
    s.run_note(TOKEN, "空仓库也要能补进去")
    check("空仓库时靠感想补录", "1115-070001" in s.run_history(run_id="1115-070001"),
          s.run_history())
    s._record({"id": "1115-070000", "note": "一条潮得发黑的长廊", "mine": "记住灯灭那一下",
               "seat": TOKEN}, "—— 出戏 ——\n门在他背后合上。")
    h = s.run_history(run_id="1115-070000")
    check("按对局号翻得到", "1115-070000" in h and "记住灯灭那一下" in h and "门在他背后合上" in h,
          h[:140])
    check("只回结算不回过程", "长廊" not in h, h[:140])
    check("范围外翻不到", "没有对局" in s.run_history(day_from="2099-01-01"), "")
    check("日期范围翻得到", "1115-070000" in s.run_history(day_from="2026-11-01", day_to="2026-12-31"), "")
    n = len(s._rec_rows())
    s._record({"id": "1115-070000", "note": "同一天", "mine": "", "seat": TOKEN}, "第二条")
    check("同号不重复写", len(s._rec_rows()) == n, str(len(s._rec_rows())))

    srv.shutdown()
    print("\n整体：" + ("通过" if ok else "有失败"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
