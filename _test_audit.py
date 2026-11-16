"""Contract / concurrency / local HTTP tests. Model reasoning is mocked, not proven here."""
import copy
import json
import os
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import mi_full as e
import mi_server as s


def intent(text="向前走", kind="act", quit=False):
    return {"kind": kind, "intent": text, "ambiguous": False, "question": "", "quit_requested": quit}


def decision(note="仍在门边，物件还在", over=False, carry=True, reason="", happen="你停在门边。"):
    return e.Decision(("我在。", happen, note, carry, over, False, 0), reason)


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        s.RUNS.clear(); s.TOKENS.clear(); s.TOKENS.add("a")
        for obj, key, value in [(e,"SAVES",os.path.join(self.tmp.name,"saves")),
                               (s,"RECORDS",os.path.join(self.tmp.name,"records")),
                               (s,"_interpret",lambda text, st:intent(text)),
                               (s,"_review",lambda *args, **kw:{"ok":True}),
                               (s,"_call",lambda *args, **kw:decision()),
                               (e,"summarize",lambda rows, prev_recap="", prev_open=None:
                                ("旧事与未完成目标仍待继续。", ["还没办完的那件事"]))]:
            p=patch.object(obj,key,value);p.start();self.addCleanup(p.stop)
        s.run_join("a")
        s.run_do("a","我想在门口等一会儿")
        self.st=s.RUNS["a"]

    def test_join_keeps_goal_and_replays_it(self):
        g=e.Decision(("我在。","门在左边。","门边",True,False,False,0),
                     motive="想留下他",goal="把铜书签挂到门环上")
        with patch.object(s,"_call",lambda *a,**kw:g):
            s.run_join("a")
            s.run_do("a","我想在门口等一会儿")
        self.assertEqual("把铜书签挂到门环上",s.RUNS["a"].get("goal"))
        self.assertIn("把铜书签挂到门环上",s._state_ctx(s.RUNS["a"]))

    def test_join_records_bounds_and_replays_them(self):
        self.assertEqual("仍在门边，物件还在", self.st.get("bounds"))
        with patch.object(s,"_interpret",lambda text, st:intent(text)), \
             patch.object(s,"_review",lambda *args, **kw:{"ok":True}):
            s.run_do("a","我往门边看一眼")
        self.assertEqual("仍在门边，物件还在", self.st.get("bounds"))

    def test_meta_statement_does_not_quit(self):
        before=(self.st["turns"],self.st["hp"],self.st["carry"])
        with patch.object(s,"_interpret",return_value=intent("只相信实际执行过的动作",kind="meta")), patch.object(s,"_call") as call:
            out=s.run_do("a","我只相信我自己做过的动作")
        self.assertIn("评论",out);call.assert_not_called()
        self.assertFalse(self.st["over"])
        self.assertEqual(before,(self.st["turns"],self.st["hp"],self.st["carry"]))

    def test_wrong_quit_interpretation_can_be_rejected(self):
        with patch.object(s,"_interpret",return_value=intent("退出",quit=True)),patch.object(s,"_review",return_value={"ok":False,"question":"你只是评论规则，对吗？"}):
            out=s.run_do("a","我只相信我自己做过的动作")
        self.assertIn("尚未落地",out);self.assertFalse(self.st["over"])

    def test_bandage_does_not_commit_trade_when_reviewer_rejects(self):
        before=copy.deepcopy(self.st)
        checks=iter([{"ok":False,"question":"包扎并未授权交易"}])
        with patch.object(s,"_call",return_value=decision(carry=False,happen="你答应交换。")),patch.object(s,"_review",side_effect=lambda *a,**k:next(checks)):
            out=s.run_do("a","我只包扎，不答应交易")
        self.assertIn("尚未落地",out);self.assertEqual(before,self.st)

    def test_hold_and_walk_not_silently_drop(self):
        checks=iter([{"ok":False,"question":"你没有同意放下"}])
        with patch.object(s,"_call",return_value=decision(carry=False)),patch.object(s,"_review",side_effect=lambda *a,**k:next(checks)):
            s.run_do("a","我抱着它往前走")
        self.assertTrue(self.st["carry"])

    def test_ambiguous_question_does_not_spend(self):
        before=copy.deepcopy(self.st)
        value=intent();value.update(ambiguous=True,question="你是对祂说还是在行动？")
        with patch.object(s,"_interpret",return_value=value):out=s.run_do("a","随便吧")
        self.assertIn("尚未执行",out);self.assertEqual(before,self.st)

    def test_model_failure_keeps_pending_voice_and_hp(self):
        s.outer_push("a","别回头","player");s.outer_push("a","让他听见海浪","dir")
        before=copy.deepcopy(self.st)
        with patch.object(s,"_call",side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):s.run_do("a","走")
        self.assertEqual(before,self.st)
        self.assertEqual(json.loads(json.dumps(before)),e.load(self.st["id"]))

    def test_ending_failure_does_not_leave_half_closed_run(self):
        before=copy.deepcopy(self.st)
        with patch.object(s,"_call",side_effect=[decision(over=True,reason="已经越过出口"),TimeoutError()]):
            with self.assertRaises(TimeoutError):s.run_do("a","走出去")
        self.assertEqual(before,self.st);self.assertFalse(self.st["over"])

    def test_false_string_is_not_truthy_end(self):
        obj={"say":"","happen":"","note":"","carry":True,"over":"false","hurt":False,"heal":0}
        with patch.object(e,"_request",return_value=obj):
            with self.assertRaises(ValueError):e.call("走")

    def test_end_requires_explicit_reason(self):
        obj={"carry":True,"over":True,"hurt":False,"heal":0}
        with patch.object(e,"_request",return_value=obj):
            with self.assertRaisesRegex(ValueError,"因果"):e.call("走")

    def test_opening_cannot_close_without_play(self):
        s.run_join("b")
        with patch.object(s,"_call",return_value=decision(over=True,reason="到了")):
            with self.assertRaises(ValueError):s.run_do("b","我想在这儿待一会儿")
        self.assertTrue(s.RUNS.get("b",{}).get("pending_join"),
                        "开局失败后座位应停在等一句话，不留半局")

    def test_no_round_limit(self):
        self.st["turns"]=500
        s.run_do("a","再看看")
        self.assertFalse(self.st["over"]);self.assertEqual(501,self.st["turns"])

    def test_zero_hp_closes_by_body_but_never_negative(self):
        # 体力是终局的一条路（梵音 11-15 定）：气力归零就收，理由是走不动了，
        # 但不许写成死亡、不许变成负数。
        self.st["hp"]=0;self.st["hurt"]=True
        s.run_do("a","歇一会")
        self.assertEqual(0,self.st["hp"])
        self.assertTrue(self.st["over"])
        self.assertIn("气力见底", self.st.get("end_reason",""))
        self.assertNotIn("死", self.st.get("end_reason",""))

    def test_explicit_quit_can_close_without_surrendering_item(self):
        with patch.object(s,"_interpret",return_value=intent("结束本局",quit=True)):
            out=s.run_do("a","请结束这局")
        self.assertTrue(self.st["over"]);self.assertTrue(self.st["carry"]);self.assertIn("出戏",out)

    def test_ending_context_has_original_and_recent_evidence(self):
        contexts=[]
        def call(st,ctx,*a):
            contexts.append(ctx)
            return decision(over=True,reason="玩家已越过出口",happen="已越过出口。")
        with patch.object(s,"_call",side_effect=call):s.run_do("a","我抱着书签走出去，不交换")
        self.assertIn("我抱着书签走出去，不交换",contexts[-1])
        self.assertIn("最终携带状态",contexts[-1]);self.assertIn("禁止新增选择",contexts[-1])

    def test_final_carry_disagreement_uses_factual_fallback(self):
        with patch.object(s,"_call",side_effect=[decision(over=True,reason="走出门"),decision(carry=False,happen="你把书签留在门槛。")]):
            out=s.run_do("a","我抱着书签出去")
        self.assertNotIn("你把书签留在门槛",out);self.assertIn("那样东西还在",out)

    def test_three_player_voices_are_not_overwritten(self):
        for x in ("第一句","第二句","第三句"):s.outer_push("a",x,"player")
        out=s.run_look("a")
        for x in ("第一句","第二句","第三句"):self.assertIn(x,out)
        self.assertNotIn("第一句",s.run_look("a"))
        self.assertFalse(e.load(self.st["id"]).get("voices"))

    def test_context_building_does_not_consume_director_hand(self):
        s.outer_push("a","一阵风","dir")
        self.assertIn("一阵风",s._state_ctx(self.st));self.assertIn("一阵风",s._state_ctx(self.st))
        s.run_do("a","走")
        self.assertEqual([],self.st["outer"])

    def test_more_than_three_director_hands_not_truncated(self):
        for n in range(5):s.outer_push("a",str(n),"dir")
        self.assertEqual([str(n) for n in range(5)],self.st["outer"])

    def test_invalid_intr_target_does_not_spend(self):
        out=s.outer_push("a","hello","wrong")
        self.assertFalse(out["ok"]);self.assertEqual(s.INTR_START,self.st["intr_left"])

    def test_talk_proposal_is_pending_not_immediate_note(self):
        before=self.st["note"]
        with patch.object(s,"_call",return_value=decision(note="物件消失",carry=False,happen="挪动一扇门")):
            out=s.talk("a","挪门")
        self.assertEqual(before,self.st["note"]);self.assertTrue(self.st["carry"])
        self.assertIn("待下一次",out["did"]);self.assertIn("挪动",self.st["outer"][0])

    def test_closed_talk_cannot_modify_state(self):
        self.st["over"]=True;before=copy.deepcopy(self.st)
        s.talk("a","改一下")
        self.assertEqual(before,self.st)

    def test_same_seat_is_serialized(self):
        def call(*a,**k):time.sleep(.01);return decision()
        with patch.object(s,"_call",side_effect=call):
            with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(lambda n:s.run_do("a",str(n)),range(8)))
        self.assertEqual(8,self.st["turns"]);self.assertEqual(92,self.st["hp"])
        self.assertEqual(8,len([h for h in self.st["history"] if h[0]=="他"]))

    def test_new_run_ids_differ_in_same_second(self):
        one=self.st["id"];s.run_join("b");self.assertNotEqual(one,s.RUNS["b"]["id"])

    def test_resume_wrong_seat_refused(self):
        out=s.run_resume("b",self.st["id"])
        self.assertIn("不是当前座位",out);self.assertNotIn("b",s.RUNS)

    def test_save_path_traversal_refused(self):
        with self.assertRaises(ValueError):e.load("../secrets")

    def test_restore_ignores_revoked_seat(self):
        s.run_join("b");s.RUNS.clear();s._adopt_saves()
        self.assertIn("a",s.RUNS);self.assertNotIn("b",s.RUNS)

    def test_watch_keeps_original_lines_after_recap(self):
        for n in range(35):s.run_do("a",f"第{n}次看")
        self.assertTrue(self.st["recap"])
        self.assertLess(len(self.st["history"]),len(self.st["events"]))
        data=s.watch_data("a")
        self.assertEqual(len(self.st["events"]),data["cursor"])
        self.assertTrue(any(x["text"]=="第0次看" for x in data["entries"]))
        cursor=data["cursor"];s.run_do("a","最后看一眼")
        delta=s.watch_data("a",self.st["id"],cursor)
        self.assertGreater(delta["cursor"],cursor);self.assertEqual(3,len(delta["entries"]))

    def test_old_save_gets_events_on_first_read(self):
        self.st.pop("events",None)
        data=s.watch_data("a");self.assertEqual(len(self.st["history"]),data["cursor"])

    def test_record_is_idempotent(self):
        s._record(self.st,"结果一");s._record(self.st,"结果二")
        rows=s._rec_rows();self.assertEqual(1,len(rows));self.assertEqual("结果二",rows[0]["result"])

    def test_history_tool_only_returns_own_seat(self):
        s._record(self.st,"甲的结局");s.run_join("b");s._record(s.RUNS["b"],"乙的结局")
        out=s.handle_tool("a","run_history",{})
        self.assertIn("甲的结局",out);self.assertNotIn("乙的结局",out)

    def test_note_updates_preserve_watch_history(self):
        self.st["over"]=True
        s.run_note("a","第一稿");s.run_note("a","第二稿")
        entries=s.watch_data("a")["entries"]
        self.assertTrue(any("第一稿" in x["text"] for x in entries))
        self.assertTrue(any("第二稿" in x["text"] for x in entries))

    def test_unauthed_http_talk_and_mcp_rejected(self):
        from http.server import ThreadingHTTPServer
        import urllib.request,urllib.error
        server=ThreadingHTTPServer(("127.0.0.1",0),s.H)
        th=threading.Thread(target=server.serve_forever,daemon=True);th.start()
        try:
            for path,obj in (("/talk",{"text":"hi"}),
                             ("/mcp",{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"run_join"}})):
                req=urllib.request.Request(f"http://127.0.0.1:{server.server_port}"+path,
                    data=json.dumps(obj).encode(),headers={"Content-Type":"application/json"})
                with self.assertRaises(urllib.error.HTTPError) as caught:urllib.request.urlopen(req,timeout=2)
                self.assertEqual(401,caught.exception.code)
        finally:server.shutdown();server.server_close();th.join(2)

    def test_server_discover_answers_new_clients(self):
        from http.server import ThreadingHTTPServer
        import urllib.request
        server=ThreadingHTTPServer(("127.0.0.1",0),s.H)
        th=threading.Thread(target=server.serve_forever,daemon=True);th.start()
        try:
            req=urllib.request.Request(f"http://127.0.0.1:{server.server_port}/mcp",
                data=json.dumps({"jsonrpc":"2.0","id":"d1","method":"server/discover",
                                 "params":{"_meta":{}}}).encode(),
                headers={"Content-Type":"application/json"})
            with urllib.request.urlopen(req,timeout=2) as response: body=json.loads(response.read())
            result=body["result"]
            self.assertEqual("complete",result["resultType"])
            self.assertIn("2025-06-18",result["supportedVersions"])
            self.assertIn("tools",result["capabilities"])
            self.assertEqual("mi",result["_meta"]["io.modelcontextprotocol/serverInfo"]["name"])
        finally:server.shutdown();server.server_close();th.join(2)

    def test_notification_gets_no_rpc_reply(self):
        from http.server import ThreadingHTTPServer
        import urllib.request
        server=ThreadingHTTPServer(("127.0.0.1",0),s.H)
        th=threading.Thread(target=server.serve_forever,daemon=True);th.start()
        try:
            req=urllib.request.Request(f"http://127.0.0.1:{server.server_port}/mcp",
                data=json.dumps({"jsonrpc":"2.0","method":"notifications/initialized"}).encode(),
                headers={"Content-Type":"application/json"})
            with urllib.request.urlopen(req,timeout=2) as response:
                self.assertEqual(202,response.status)
                self.assertEqual(b"",response.read())
        finally:server.shutdown();server.server_close();th.join(2)

    def test_production_interpret_schema_rejects_invalid_mode(self):
        with patch.object(e,"_request",return_value={"kind":"exchange","intent":"包扎","ambiguous":False,"quit_requested":False}):
            with self.assertRaises(ValueError):e.interpret("包扎")

    def test_production_review_requires_boolean(self):
        with patch.object(e,"_request",return_value={"ok":"false"}):
            with self.assertRaises(ValueError):e.review("走",{}, {},{})

    def test_production_call_carries_reason_and_clamps_heal(self):
        with patch.object(e,"_request",return_value={"carry":True,"over":True,"hurt":False,"heal":100,"end_reason":"走出出口"}):
            r=e.call("走")
        self.assertEqual(40,r[6]);self.assertEqual("走出出口",r.end_reason)

    def test_all_three_production_stages_reject_invented_trade(self):
        responses=[intent("包扎伤口，不交换"),
                   {"say":"好","happen":"你答应交换书签。","note":"书签交出", "carry":False,"over":False,"hurt":False,"heal":0},
                   {"ok":False,"question":"你并没有答应交易，是否只包扎？"}]
        with patch.object(s,"_interpret",side_effect=lambda text,st:e.interpret(text,st["note"])), \
             patch.object(s,"_call",side_effect=lambda st,ctx,*a:e.call(ctx)), \
             patch.object(s,"_review",side_effect=e.review), \
             patch.object(e,"_request",side_effect=responses) as request:
            out=s.run_do("a","我包扎，不交换书签")
        self.assertIn("尚未落地",out)
        self.assertEqual(3,request.call_count);self.assertTrue(self.st["carry"])
        self.assertEqual(0,self.st["turns"])

    def test_sixth_hand_cannot_overwrite_five_queued_messages(self):
        for n in range(5):self.assertTrue(s.outer_push("a",str(n))["ok"])
        self.assertFalse(s.outer_push("a","第六句")["ok"])
        self.assertEqual([str(n) for n in range(5)],self.st["voices"])

    def test_bonus_is_limited_over_whole_run_not_only_current_balance(self):
        s._hand(self.st);self.st["games"]["bonus"]=5;self.st["intr_left"]=1
        with patch.object(s.random,"randint",return_value=6):r=s.play("a","dice","big")
        self.assertTrue(r["win"]);self.assertEqual(1,self.st["intr_left"])

    def test_actual_http_model_failure_returns_json_without_mutation(self):
        from http.server import ThreadingHTTPServer
        import urllib.request
        server=ThreadingHTTPServer(("127.0.0.1",0),s.H)
        th=threading.Thread(target=server.serve_forever,daemon=True);th.start()
        before=copy.deepcopy(self.st)
        try:
            request=urllib.request.Request(f"http://127.0.0.1:{server.server_port}/mcp",
                data=json.dumps({"jsonrpc":"2.0","id":9,"method":"tools/call","params":{"name":"run_do","arguments":{"text":"走"}}}).encode(),
                headers={"Authorization":"Bearer a","Content-Type":"application/json"})
            with patch.object(s,"_call",side_effect=TimeoutError),urllib.request.urlopen(request,timeout=2) as response:
                result=json.load(response)
            self.assertTrue(result["result"]["isError"])
            self.assertEqual(before,self.st)
        finally:server.shutdown();server.server_close();th.join(2)

    def test_record_failure_leaves_saved_ending_and_can_retry(self):
        with patch.object(s,"_call",return_value=decision(over=True,reason="已经到出口")),patch.object(s,"_record",side_effect=OSError("disk busy")):
            out=s.run_do("a","走出去")
        self.assertIn("索引尚未写入",out)
        self.assertTrue(self.st["over"]);self.assertTrue(e.load(self.st["id"])["record_pending"])
        s.run_look("a")
        self.assertNotIn("record_pending",self.st)
        self.assertEqual(1,len(s._rec_rows()))


if __name__=="__main__":unittest.main()
