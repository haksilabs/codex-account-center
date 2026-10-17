import os,json,runpy,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
M=runpy.run_path(str(Path(__file__).resolve().parents[1] / 'src/codex-acc'),run_name='matrix_launch_test')
G=M['_desktop_launch_environment'].__globals__
D=runpy.run_path(str(Path(__file__).resolve().parents[1] / 'src/codex_auto_switch.py'))
class Clock:
 def __init__(self):self.now=0
 def monotonic(self):return self.now
 def sleep(self,delta):self.now+=delta
class LaunchTests(unittest.TestCase):
 def test_boot_service_imports_current_desktop_environment(self):
  manager=SimpleNamespace(stdout='WAYLAND_DISPLAY=wayland-1\nDISPLAY=:0\nHYPRLAND_INSTANCE_SIGNATURE=current\nOTHER_SECRET=should-not-import\n',returncode=0)
  with patch.dict(os.environ,{'ELECTRON_RUN_AS_NODE':'1'},clear=True),patch.object(G['subprocess'],'run',return_value=manager),patch.object(Path,'is_socket',return_value=True):
   env=M['_desktop_launch_environment']()
  self.assertEqual(env['WAYLAND_DISPLAY'],'wayland-1');self.assertEqual(env['DISPLAY'],':0');self.assertEqual(env['HYPRLAND_INSTANCE_SIGNATURE'],'current')
  self.assertNotIn('OTHER_SECRET',env);self.assertNotIn('ELECTRON_RUN_AS_NODE',env)
 def test_stale_display_is_replaced_with_existing_runtime_socket(self):
  with tempfile.TemporaryDirectory() as td:
   import socket
   sock=socket.socket(socket.AF_UNIX);sock.bind(td+'/wayland-3')
   try:
    with patch.dict(os.environ,{'XDG_RUNTIME_DIR':td,'WAYLAND_DISPLAY':'wayland-0'},clear=True),patch.object(G['subprocess'],'run',return_value=SimpleNamespace(stdout='',returncode=1)):
     env=M['_desktop_launch_environment']()
    self.assertEqual(env['WAYLAND_DISPLAY'],'wayland-3')
   finally:sock.close()
 def switch(self,restart=True,start=False,fail=False):
  td=tempfile.TemporaryDirectory();root=Path(td.name);src=root/'account.json';src.write_text('{"tokens":{}}');auth=root/'auth.json';auth.write_text('{}')
  events=[]
  def stop():events.append('stop')
  def sync():events.append('sync')
  def launch(env):
   events.append('launch');self.assertEqual(auth.read_text(),src.read_text())
   if fail:raise RuntimeError('no window')
   return {'ok':True,'app_ready':True}
  with patch.dict(G,CODEX_DIR=root,AUTH_FILE=auth,_desktop_launch_environment=lambda:{'DISPLAY':':0'},_stop_chatgpt_app=stop,sync_current_auth=sync,_launch_chatgpt_and_wait=launch),patch.object(G['subprocess'],'Popen') as notify:
   if fail:
    with self.assertRaisesRegex(RuntimeError,'Account selected, but Codex could not open'):M['switch_to_account']({'file_path':str(src),'email':'test'},restart_app=restart,start_app_if_closed=start)
    self.assertEqual(notify.call_count,0);result=None
   else:result=M['switch_to_account']({'file_path':str(src),'email':'test'},restart_app=restart,start_app_if_closed=start)
  td.cleanup();return events,result
 def test_closed_app_is_launched_when_restart_option_enabled(self):
  events,result=self.switch();self.assertEqual(events,['stop','sync','launch']);self.assertTrue(result['app_ready'])
 def test_success_notification_requires_verified_launch(self):self.switch(fail=True)
 def test_intentionally_disabled_restart_stays_disabled(self):
  events,result=self.switch(restart=False);self.assertEqual(events,['sync']);self.assertFalse(result['app_ready'])
 def test_force_start_opens_closed_app_even_with_restart_disabled(self):
  events,result=self.switch(restart=False,start=True);self.assertEqual(events,['stop','sync','launch']);self.assertTrue(result['app_ready'])
 def test_main_process_alone_is_not_launch_success(self):
  clock=Clock()
  with tempfile.TemporaryDirectory() as td,patch.object(Path,'home',return_value=Path(td)),patch.dict(G,is_chatgpt_app_running=lambda:True,_desktop_ipc_ready=lambda:False,_desktop_window_ready=lambda env:True),patch.object(G['time'],'monotonic',clock.monotonic),patch.object(G['time'],'sleep',clock.sleep),patch.object(G['subprocess'],'Popen',return_value=Mock(poll=lambda:None)):
   with self.assertRaisesRegex(RuntimeError,'did not become ready'):M['_launch_chatgpt_and_wait']({},timeout=1)
 def test_ready_ipc_without_window_is_not_launch_success(self):
  clock=Clock()
  with tempfile.TemporaryDirectory() as td,patch.object(Path,'home',return_value=Path(td)),patch.dict(G,is_chatgpt_app_running=lambda:True,_desktop_ipc_ready=lambda:True,_desktop_window_ready=lambda env:False),patch.object(G['time'],'monotonic',clock.monotonic),patch.object(G['time'],'sleep',clock.sleep),patch.object(G['subprocess'],'Popen',return_value=Mock(poll=lambda:None)):
   with self.assertRaisesRegex(RuntimeError,'did not become ready'):M['_launch_chatgpt_and_wait']({},timeout=1)
 def test_ready_window_and_ipc_confirm_launch(self):
  with tempfile.TemporaryDirectory() as td,patch.object(Path,'home',return_value=Path(td)),patch.dict(G,is_chatgpt_app_running=lambda:True,_desktop_ipc_ready=lambda:True,_desktop_window_ready=lambda env:True),patch.object(G['subprocess'],'Popen',return_value=Mock(poll=lambda:None)):
   self.assertTrue(M['_launch_chatgpt_and_wait']({})['app_ready'])
if __name__=='__main__':unittest.main(verbosity=2)
