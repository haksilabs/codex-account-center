import json,runpy,sqlite3,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch,Mock

M=runpy.run_path(str(Path(__file__).resolve().parents[1] / 'src/codex-acc'))
G=M['get_active_or_interrupted_codex_threads'].__globals__
D=runpy.run_path(str(Path(__file__).resolve().parents[1] / 'src/codex_auto_switch.py'))

class MultiChatTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.now=int(time.time())
  self.state=sqlite3.connect(self.root/'state_5.sqlite')
  self.state.execute('CREATE TABLE threads (id TEXT PRIMARY KEY,title TEXT,cwd TEXT,sandbox_policy TEXT,approval_mode TEXT,source TEXT,thread_source TEXT,updated_at INTEGER,archived INTEGER,rollout_path TEXT)')
  self.hist=sqlite3.connect(self.root/'thread_history_1.sqlite')
  self.hist.execute('CREATE TABLE thread_turns (thread_id TEXT, turn_id TEXT, rollout_ordinal INTEGER, status TEXT,error_json TEXT,started_at INTEGER,completed_at INTEGER)')
  self.patcher=patch.dict(G,CODEX_DIR=self.root);self.patcher.start()
 def tearDown(self):
  self.patcher.stop();self.state.close();self.hist.close();self.temp.cleanup()
 def chat(self,tid,status='inProgress',ago=20,parent=None,archived=0,updated_ago=None):
  source=json.dumps({'subagent':{'thread_spawn':{'parent_thread_id':parent}}}) if parent else 'desktop'
  self.state.execute('INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?,?)',(tid,tid,'/tmp','','',source,'subagent' if parent else 'user',self.now-(updated_ago if updated_ago is not None else ago),archived,''))
  self.turn(tid,status,1,ago)
  self.state.commit()
 def turn(self,tid,status,ordinal,ago=20,error=''):
  self.hist.execute('INSERT INTO thread_turns VALUES (?,?,?,?,?,?,?)',(tid,str(ordinal),ordinal,status,error,self.now-ago,None if status=='inProgress' else self.now-ago));self.hist.commit()
 def snapshot(self):return M['get_active_or_interrupted_codex_threads']()
 def test_three_running_chats_are_captured(self):
  for tid in ['a','b','c']:self.chat(tid)
  self.assertEqual({t['thread_id'] for t in self.snapshot()},{'a','b','c'})
 def test_finished_archived_and_stale_chats_excluded(self):
  self.chat('run');self.chat('finished','completed');self.chat('archived',archived=1);self.chat('stale',ago=90000)
  self.assertEqual([t['thread_id'] for t in self.snapshot()],['run'])
 def test_latest_turn_wins_over_old_running_or_interrupted_turn(self):
  self.chat('done');self.turn('done','completed',2,ago=5)
  self.assertEqual(self.snapshot(),[])
 def test_subagents_do_not_duplicate_root_or_resurrect_finished_root(self):
  self.chat('run');self.chat('child',parent='run')
  self.chat('done','completed');self.chat('oldchild',parent='done')
  self.assertEqual([t['thread_id'] for t in self.snapshot()],['run'])
 def test_long_running_chat_with_fresh_thread_activity_is_included(self):
  self.chat('long',ago=8000,updated_ago=20)
  self.assertEqual(len(self.snapshot()),1)
 def test_all_latest_turns_checked_even_after_many_newer_completed_chats(self):
  self.chat('run',ago=1000)
  for n in range(50):self.chat(str(n),'completed',ago=5)
  self.assertEqual([t['thread_id'] for t in self.snapshot()],['run'])
 def test_recent_rate_limit_failure_is_included_but_other_failure_is_not(self):
  self.chat('limited','failed');self.turn('limited','failed',2,error='usageLimitExceeded')
  self.chat('error','failed')
  self.assertEqual([t['thread_id'] for t in self.snapshot()],['limited'])
 def test_batch_deduplicates_and_continues_after_failure_and_uncertain_delivery(self):
  calls=[]
  def resume(tid,**kw):
   calls.append(tid)
   if tid=='a':raise RuntimeError('simulated')
   return {'ok':tid=='c','thread_id':tid,'method':'ipc_desktop' if tid=='c' else 'desktop_unconfirmed'}
  with patch.dict(G,resume_codex_thread=resume):
   results=M['resume_codex_threads']([{'thread_id':tid} for tid in ['a','b','a','c']])
  self.assertEqual(calls,['a','b','c']);self.assertEqual(len(results),3);self.assertTrue(results[-1]['ok'])
 def test_daemon_captures_before_restart_and_passes_all_chats(self):
  order=[];threads=[{'thread_id':str(n)} for n in range(3)]
  accounts=[{'id_key':'a','email':'old','is_active':True},{'id_key':'b','email':'new'}]
  def capture(**kw):order.append('snapshot');return threads
  def switch(*a,**kw):order.append('switch');return {'app_ready':True}
  batch=Mock(return_value=[{'ok':True,'thread_id':t['thread_id']} for t in threads])
  mod={'list_accounts':lambda:(accounts,None),'fetch_account_limits':lambda a:{'ok':True,'allowed':True,'rem_5h':2,'rem_weekly':90},'get_active_or_interrupted_codex_threads':capture,'fetch_all_limits_parallel':lambda a:{'b':{'ok':True,'allowed':True,'rem_5h':80,'rem_weekly':90}},'is_chatgpt_app_running':lambda:True,'switch_to_account':switch,'resume_codex_threads':batch}
  with patch.dict(D['check_codex'].__globals__,emit=lambda *a,**k:None):
   D['check_codex'](mod,{'cooldown':0},True,True,0)
  self.assertEqual(order,['snapshot','snapshot','switch']);self.assertEqual(batch.call_args.args[0],threads)
 def test_snapshot_excludes_completed_chats_without_fallback(self):
  self.chat('done','completed')
  self.assertEqual(self.snapshot(),[])

if __name__=='__main__':unittest.main(verbosity=2)
