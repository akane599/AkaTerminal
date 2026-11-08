"""Owned private FUSE fixture; no Android restart or production mount changes."""
from pathlib import Path
import json,os,shutil,subprocess,signal,select,time,uuid,traceback,sys,hashlib
HERE=Path(__file__).resolve().parent
ANDROID=Path('/proc/1/root')
def path(p):return str(p).removeprefix('/proc/1/root')
class Fixture:
 def __init__(self):
  self.tag='codex-storage-'+uuid.uuid4().hex[:10];self.host=ANDROID/'data/local/tmp'/self.tag;self.root=self.host/'guest';self.state=ANDROID/'data/adb/fluxlinux'/self.tag;self.daemons=[];self.calls=[]
  self.root.mkdir(parents=True,mode=0o700);self.host.chmod(0o700)
  for p in ['sdcard','fresh','spare']:(self.root/p).mkdir()
  for p in ['flux-mntns','storage-fixture','flux-mntns-fault']:
   if (HERE/'build'/p).exists():shutil.copyfile(HERE/'build'/p,self.host/p);(self.host/p).chmod(0o700)
  self.call('ensure');self.initial=json.loads(self.call('inspect').stdout)
 def command(self,mode,*args):return ['nsenter','--target','1','--mount','--root','--wd','--',path(self.host/'flux-mntns'),mode,path(self.state),path(self.root),*args]
 def call(self,mode,*args,expected=0):
  p=subprocess.run(self.command(mode,*args),capture_output=True,text=True,timeout=20);self.calls.append({'mode':mode,'args':args,'rc':p.returncode,'out':p.stdout,'err':p.stderr});assert p.returncode==expected,self.calls[-1];return p
 def shell(self,s,expected=0):return self.call('run','--','/system/bin/sh','-c',s,'fixture',path(self.root),path(self.host),path(self.state),expected=expected)
 def server(self,where,content):
  p=subprocess.Popen(self.command('run','--',path(self.host/'storage-fixture'),path(self.root/where),content),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
  assert select.select([p.stdout],[],[],5)[0],'FUSE ready timeout'
  line=p.stdout.readline();assert line.startswith('READY '),(line,p.stderr.read() if p.poll() is not None else '')
  pid=int(line.split()[1]);start=Path('/proc',str(pid),'stat').read_text().rsplit(')',1)[1].split()[19];fd=os.pidfd_open(pid)
  self.daemons.append((p,pid,start,fd));return len(self.daemons)-1
 def kill(self,i):
  p,pid,start,fd=self.daemons[i];assert Path('/proc',str(pid),'stat').read_text().rsplit(')',1)[1].split()[19]==start
  signal.pidfd_send_signal(fd,signal.SIGKILL);p.communicate(timeout=6);os.close(fd);self.daemons[i]=None
 def cleanup(self):
  for i,d in enumerate(self.daemons):
   if d is not None:self.kill(i)
  self.call('retire');shutil.rmtree(self.host);shutil.rmtree(self.state)
