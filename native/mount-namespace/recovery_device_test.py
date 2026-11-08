"""Kill only disposable test owners; never touches real guest/owner/state."""
from pathlib import Path
import concurrent.futures,fcntl,hashlib,json,os,select,shutil,signal,subprocess,sys,time,traceback,uuid
HERE=Path(__file__).resolve().parent
ANDROID=Path('/proc/1/root');RESEARCH=Path('/home/akane/research/duck-mount-20261106')
sys.path.insert(0,str(RESEARCH/'native-generation-r1'))
from capture_live import snapshot
from verify_runtime import same
assert os.geteuid()==0 and sys.argv[1:]==['--owned-recovery-fixture']
checks={};calls=[];fixtures=[];before=snapshot();global_before=Path('/proc/1/mountinfo').read_bytes();parent_before=Path('/proc/self/mountinfo').read_bytes()
def check(n,v=True):assert v,n;checks[n]=True
def path(p):return str(p).removeprefix('/proc/1/root')
def wait_for(fn):
 end=time.monotonic()+6
 while not fn():
  assert time.monotonic()<end,'owned fixture deadline'
  time.sleep(.03)
class Fixture:
 def __init__(self):
  self.tag='codex-owner-recovery-'+uuid.uuid4().hex[:10];self.host=ANDROID/'data/local/tmp'/self.tag;self.root=self.host/'guest';self.state=ANDROID/'data/adb/fluxlinux'/self.tag
  self.host.mkdir(mode=0o700);self.root.mkdir(mode=0o700);(self.root/'mnt').mkdir();self.actors=[];self.known=[];fixtures.append(self)
  for name in ['flux-mntns','flux-mntns-fault']:
   shutil.copyfile(HERE/'build'/name,self.host/name);(self.host/name).chmod(0o700)
  self.call('ensure');self.initial=self.owner();self.original=(self.state/'owner').read_bytes();self.latch=(self.state/'creating').read_bytes()
 def command(self,mode,*args,fault=None):
  binary='flux-mntns-fault' if fault else 'flux-mntns'
  env=['/system/bin/env','FLUX_RECOVERY_FAULT='+fault] if fault else []
  return ['chroot',str(ANDROID),*env,path(self.host/binary),mode,path(self.state),path(self.root),*args]
 def call(self,mode,*args,expected=0,fault=None):
  p=subprocess.run(self.command(mode,*args,fault=fault),capture_output=True,text=True,timeout=20)
  calls.append({'fixture':self.tag,'mode':mode,'args':args,'fault':fault,'exit':p.returncode,'stdout':p.stdout,'stderr':p.stderr})
  assert p.returncode==expected,calls[-1]
  return p
 def owner(self):
  r=json.loads(self.call('inspect').stdout);self.known.append(r);return r
 def shell(self,s):return self.call('run','--','/system/bin/sh','-c',s,'fixture',path(self.root),path(self.host/'flux-mntns'),path(self.state))
 def kill_owner(self):
  r=self.owner();p=Path('/proc')/str(r['pid']);st=int((p/'stat').read_text().rsplit(')',1)[1].split()[19]);assert st==r['start']
  assert path(self.host).encode() in (p/'cmdline').read_bytes()
  fd=os.pidfd_open(r['pid']);signal.pidfd_send_signal(fd,signal.SIGKILL);poll=select.poll();poll.register(fd,select.POLLIN);assert poll.poll(5000);os.close(fd)
  wait_for(lambda:not p.exists());return r
 def client(self):
  cmd=self.command('run','--','/system/bin/sh','-c','echo $$ > "$1/client"; while [ ! -f "$1/release" ]; do sleep 0.1; done','fixture',path(self.root))
  p=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True);self.actors.append(p);wait_for(lambda:(self.root/'client').exists());return p,int((self.root/'client').read_text())
 def stop_clients(self):
  for p in self.actors:
   if p.poll() is None:p.terminate()
   p.communicate(timeout=6)
  self.actors=[]
  if (self.state/'owner').exists():
   words=(self.state/'owner').read_text().split()
   if len(words)==8:
    owner_pid=int(words[2]);ns=int(words[5])
    def no_remaining_clients():
     for proc in Path('/proc').glob('[0-9]*'):
      if int(proc.name)==owner_pid:continue
      try:
       if (proc/'ns/mnt').stat().st_ino==ns and any(line.split()[4]==path(self.root) for line in (proc/'mountinfo').read_text().splitlines()):return False
      except OSError:pass
     return True
    wait_for(no_remaining_clients)
 def cleanup(self):
  self.stop_clients()
  # Only current test keeper is eligible for retirement. Otherwise verify all
  # recorded keeper PIDs have exited before removing disposable fixture files.
  q=subprocess.run(self.command('inspect'),capture_output=True,text=True,timeout=10)
  if q.returncode==0:
   owner=json.loads(q.stdout);self.known.append(owner);self.call('retire');wait_for(lambda:not Path('/proc',str(owner['pid'])).exists())
  for r in self.known:
   p=Path('/proc',str(r['pid']))
   if p.exists():assert int((p/'stat').read_text().rsplit(')',1)[1].split()[19])!=r['start'],'owned keeper still alive'
  assert not any(line.split()[4].startswith(path(self.host)) for line in Path('/proc/1/mountinfo').read_text().splitlines())
  history={p.name:p.read_text() for p in self.state.iterdir() if p.is_file() and p.stat().st_size}
  shutil.rmtree(self.host);shutil.rmtree(self.state);return history
failure=None;histories={}
try:
 f=Fixture();check('healthy_ensure_reuses_owner',f.owner()==f.initial)
 f.shell('mount -t tmpfs -o size=1m,nodev,nosuid,noexec owned-recovery "$1/mnt"; printf preserve > "$1/mnt/marker"; printf persistent > "$1/persistent"')
 client,pid=f.client();start=int(Path('/proc',str(pid),'stat').read_text().rsplit(')',1)[1].split()[19]);old=f.kill_owner();f.call('inside',expected=4)
 nested=subprocess.run(['chroot',str(ANDROID),'/system/bin/nsenter','-t',str(pid),'-m','--',path(f.host/'flux-mntns'),'inside',path(f.state),path(f.root)],capture_output=True,text=True,timeout=10)
 check('already_inside_remains_usable_after_owner_death',nested.returncode==0)
 f.call('ensure');new=f.owner();check('surviving_namespace_reused',new['pid']!=old['pid'] and new['namespace']==old['namespace'])
 check('live_client_survived',client.poll() is None and int(Path('/proc',str(pid),'stat').read_text().rsplit(')',1)[1].split()[19])==start)
 check('private_mount_contents_preserved',f.shell('cat "$1/mnt/marker"').stdout=='preserve')
 check('global_guest_did_not_gain_private_mount',not(f.root/'mnt/marker').exists())
 check('old_record_archived_exactly',any(p.read_bytes()==f.original for p in f.state.glob('*.history')))
 check('original_creation_latch_preserved',(f.state/'creating').read_bytes()==f.latch)
 f.stop_clients();old=f.kill_owner();f.call('ensure');new=f.owner();check('empty_namespace_recreated',new['pid']!=old['pid'] and any(p.read_text().startswith('fresh\n') for p in f.state.glob('*.intent')))
 check('persistent_guest_data_preserved',f.shell('cat "$1/persistent"').stdout=='persistent')
 check('old_tmpfs_not_fabricated',f.shell('test ! -e "$1/mnt/marker"').returncode==0)
 check('two_recovery_histories',len(list(f.state.glob('*.history')))==2)
 old=f.kill_owner();other=Fixture();other_before=other.owner()
 # Model namespace inode recycling deterministically, regardless of allocator timing.
 words=(f.state/'owner').read_text().split();words[5]=str(other_before['namespace']);(f.state/'owner').write_text(' '.join(words)+'\n')
 for mode,expected in [('inside',4),('run',125)]:
  args=['--','/system/bin/true'] if mode=='run' else []
  q=subprocess.run(['chroot',str(ANDROID),'/system/bin/nsenter','-t',str(other_before['pid']),'-m','--',path(f.host/'flux-mntns'),mode,path(f.state),path(f.root),*args],capture_output=True,text=True,timeout=10)
  check('recycled_namespace_'+mode+'_not_admitted',q.returncode==expected)
 f.call('ensure');f.owner()
 check('unrelated_namespace_not_adopted',other.owner()==other_before and f.owner()['namespace']!=other_before['namespace'])
 # An exclusive operation excludes even otherwise-idempotent ensure.
 gate=open(f.state/'gate.lock','r+');fcntl.flock(gate,fcntl.LOCK_EX|fcntl.LOCK_NB);f.call('ensure',expected=125);gate.close();check('exclusive_operation_blocks_ensure')
 old=f.kill_owner();record=(f.state/'owner').read_bytes();count=len(list(f.state.glob('*.intent')))
 gate=open(f.state/'gate.lock','r+');fcntl.flock(gate,fcntl.LOCK_SH|fcntl.LOCK_NB);f.call('ensure',expected=125);gate.close()
 check('empty_recovery_requires_exclusive_lease',(f.state/'owner').read_bytes()==record and len(list(f.state.glob('*.intent')))==count)
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
  responses=list(pool.map(lambda _:subprocess.run(f.command('ensure'),capture_output=True,text=True,timeout=20),range(4)))
 check('racing_recovery_has_success_and_only_bounded_refusals',any(p.returncode==0 for p in responses) and all(p.returncode in [0,125] for p in responses))
 new=f.owner();check('racing_recovery_publishes_once',new['pid']!=old['pid'] and len(list(f.state.glob('*.intent')))==count+1)
 original=(f.state/'owner').read_bytes();parts=original.decode().split();parts[3]=str(int(parts[3])+1);(f.state/'owner').write_text(' '.join(parts)+'\n');f.call('ensure',expected=125)
 check('PID_start_mismatch_refused',(f.state/'owner').read_text()==' '.join(parts)+'\n');(f.state/'owner').write_bytes(original)
 (f.state/'owner').write_text('broken\n');f.call('ensure',expected=125);check('corruption_not_recovered',(f.state/'owner').read_text()=='broken\n');(f.state/'owner').write_bytes(original)
 f.call('retire');f.call('ensure',expected=125);check('retired_not_reused',not(f.state/'owner').exists())
 for fault in ['after-intent','after-history','before-publish']:
  f=Fixture();f.kill_owner();original=(f.state/'owner').read_bytes()
  f.call('ensure',fault=fault,expected=86 if fault!='before-publish' else 125)
  image={p.name:p.read_bytes() for p in f.state.iterdir() if p.is_file()};f.call('ensure',expected=125)
  check(fault+'_stays_latched',(f.state/'owner').read_bytes()==original and image=={p.name:p.read_bytes() for p in f.state.iterdir() if p.is_file()})
 # Published new identity is authoritative even if readiness reply was lost.
 f=Fixture();f.kill_owner();f.call('ensure',fault='after-publish',expected=125)
 parts=(f.state/'owner').read_text().split();pid=int(parts[2]);wait_for(lambda:not Path('/proc',str(pid)).exists());f.call('ensure');f.owner()
 check('committed_dead_replacement_recovers_under_new_identity',len(list(f.state.glob('*.history')))==2)
 # A failed same-namespace replacement never discards the live guest.
 f=Fixture();f.shell('mount -t tmpfs -o size=1m owned-recovery "$1/mnt"; printf keep > "$1/mnt/marker"');client,pid=f.client();f.kill_owner();f.call('ensure',fault='before-publish',expected=125);f.call('ensure',expected=125)
 check('interrupted_reuse_keeps_existing_client',client.poll() is None)
 probe=subprocess.run(['chroot',str(ANDROID),'/system/bin/nsenter','-t',str(pid),'-m','--','/system/bin/cat',path(f.root/'mnt/marker')],capture_output=True,text=True,timeout=10)
 check('interrupted_reuse_preserves_mounts',probe.returncode==0 and probe.stdout=='keep')
except BaseException:failure=traceback.format_exc()
finally:
 for f in fixtures:
  try:histories[f.tag]=f.cleanup()
  except BaseException:
   if not failure:failure=traceback.format_exc()
 checks['global_mountinfo_identical']=Path('/proc/1/mountinfo').read_bytes()==global_before
 checks['parent_mountinfo_identical']=Path('/proc/self/mountinfo').read_bytes()==parent_before
 after=snapshot();checks.update({'health_'+k:v for k,v in same(before,after).items()})
 result={'passed':failure is None and all(checks.values()),'checks':checks,'failure':failure,'calls':calls,'histories':histories,'before':before,'after':after,'sha256':hashlib.sha256((HERE/'build/flux-mntns').read_bytes()).hexdigest(),'scope':'Actual Android fixture keepers killed via exact pidfd; production Ubuntu/native/FUSE untouched. No Android restart or power-loss test.'}
 out=HERE/'results';out.mkdir(exist_ok=True);p=out/('recovery-'+uuid.uuid4().hex[:12]+'.json');p.write_text(json.dumps(result,indent=2)+'\n');os.chown(p,1000,1000)
 print(json.dumps({'passed':result['passed'],'checks':checks,'failure':failure,'result':str(p)}))
 if not result['passed']:sys.exit(1)
