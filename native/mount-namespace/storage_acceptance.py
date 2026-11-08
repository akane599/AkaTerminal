from storage_test_support import *
import fcntl
assert os.geteuid()==0 and sys.argv[1:]==['--owned-storage-fixture']
sys.path.insert(0,'/home/akane/research/duck-mount-20261106/native-generation-r1')
from capture_live import snapshot
from verify_runtime import same
checks={};before=snapshot();global_before=Path('/proc/1/mountinfo').read_bytes();parent_before=Path('/proc/self/mountinfo').read_bytes();f=None;failure=None;client=None

def check(name,value=True):assert value,name;checks[name]=True
try:
 f=Fixture()
 def repair(source=None,fail=False,expected=0,release=False):
  env=[]
  if source is not None:env+=['FLUX_STORAGE_SOURCE='+source]
  if fail:env+=['FLUX_STORAGE_FAIL_BIND=1']
  return f.call('run','--','/system/bin/env',*env,path(f.host/('flux-mntns' if release else 'flux-mntns-fault')),'storage',path(f.state),path(f.root),expected=expected)
 def mounts():return f.shell('cat /proc/self/mountinfo').stdout
 def cardrow():return [x for x in mounts().splitlines() if x.split()[4]==path(f.root/'sdcard')]
 f.call('storage',expected=125);check('outside_owned_namespace_refused')
 repair(release=True);check('initial_mount_from_current_android_storage',f.shell('test -r "$1/sdcard/Download/Samsung-C5-Yedek/README.md"').returncode==0);f.shell('umount "$1/sdcard"')
 old=f.server('sdcard','old123');fresh=f.server('fresh','new456');source=path(f.root/'fresh')
 initial=mounts();repair('/missing');check('healthy_noop_even_source_unavailable',mounts()==initial)
 check('old_marker_visible',f.shell('cat "$1/sdcard/marker"').stdout=='old123')
 client=subprocess.Popen(f.command('run','--','/system/bin/sh','-c','echo $$; read unused'),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
 clientpid=int(client.stdout.readline());clientstart=Path('/proc',str(clientpid),'stat').read_text().rsplit(')',1)[1].split()[19]
 f.shell('stat "$1/sdcard"');f.kill(old);check('cached_stat_still_succeeds_after_server_death',f.shell('stat "$1/sdcard"').returncode==0);dead=mounts();check('real_ENOTCONN_reproduced','Transport endpoint is not connected' in f.shell('stat -f "$1/sdcard"',expected=1).stderr)
 baseline=HERE.parents[3]/'ubuntu-storage-recovery-r3/source/native/mount-namespace/build/flux-mntns'
 assert hashlib.sha256(baseline.read_bytes()).hexdigest()=='2561ea45585c68b1953e973cda8e82fabe2311e6d411ce159d27134b324021cc'
 shutil.copyfile(baseline,f.host/'old-r3');(f.host/'old-r3').chmod(0o700)
 f.call('run','--',path(f.host/'old-r3'),'storage',path(f.state),path(f.root))
 check('old_r3_bug_reproduced_unchanged_dead_mount',mounts()==dead and 'Transport endpoint is not connected' in f.shell('stat -f "$1/sdcard"',expected=1).stderr)
 repair('/missing',expected=125);check('unavailable_source_leaves_mounts_identical',mounts()==dead)
 repair(path(f.root/'spare'),expected=125);check('nonfuse_source_refused_before_mutation',mounts()==dead)
 lock=open(f.state/'storage.lock','r+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);repair(source,expected=125);lock.close();check('concurrent_repair_refused_unchanged',mounts()==dead)
 repair(source,fail=True,expected=125)
 check('rollback_restores_disconnected_mount',len(cardrow())==1 and cardrow()[0].split()[2]==[x for x in dead.splitlines() if x.split()[4]==path(f.root/'sdcard')][0].split()[2] and 'Transport endpoint is not connected' in f.shell('stat -f "$1/sdcard"',expected=1).stderr)
 repair(source);check('repair_reads_fresh_contents',f.shell('cat "$1/sdcard/marker"').stdout=='new456')
 repaired=mounts();repair(source);check('repeat_healthy_noop',mounts()==repaired)
 check('keeper_record_unchanged',json.loads(f.call('inspect').stdout)==f.initial)
 check('live_client_preserved',client.poll() is None and Path('/proc',str(clientpid),'stat').read_text().rsplit(')',1)[1].split()[19]==clientstart)
 check('unrelated_mount_rows_identical',[x for x in initial.splitlines() if x.split()[4]!=path(f.root/'sdcard')]==[x for x in repaired.splitlines() if x.split()[4]!=path(f.root/'sdcard')])
 f.kill(fresh);repair('/missing',release=True)
 check('release_ignores_test_source_and_binds_current_android_storage',f.shell('test -r "$1/sdcard/Download/Samsung-C5-Yedek/README.md"').returncode==0)
 check('release_not_test_enabled',b'FLUX_STORAGE_SOURCE' not in (HERE/'build/flux-mntns').read_bytes())
 # A nested mount must never be detached together with storage.
 f.shell('mount --bind "$1/spare" "$1/sdcard"');stack=mounts();repair(source,expected=125);check('stacked_mounts_refused',mounts()==stack)
 f.shell('umount "$1/sdcard"; umount "$1/sdcard"; mount -t tmpfs -o size=1m owned-storage "$1/sdcard"');other=mounts();repair(source,expected=125);check('nonfuse_target_refused',mounts()==other)
 f.shell('mkdir "$1/sdcard/child"; mount --bind "$1/spare" "$1/sdcard/child"');nested=mounts();repair(source,expected=125);check('nested_mounts_refused',mounts()==nested)
 f.shell('umount "$1/sdcard/child"; umount "$1/sdcard"; rmdir "$1/sdcard"; ln -s spare "$1/sdcard"');symlink=mounts();repair(release=True,expected=125);check('symlink_destination_refused',mounts()==symlink)
 client.stdin.write('done\n');client.stdin.flush();client.communicate(timeout=6);client=None
except BaseException:failure=traceback.format_exc()
finally:
 if client is not None:
  client.stdin.write('done\n');client.stdin.flush();client.communicate(timeout=6)
 calls=f.calls if f else []
 if f:
  try:f.cleanup()
  except BaseException:failure=(failure or '')+traceback.format_exc()
 checks['global_mountinfo_identical']=Path('/proc/1/mountinfo').read_bytes()==global_before
 checks['parent_mountinfo_identical']=Path('/proc/self/mountinfo').read_bytes()==parent_before
 after=snapshot();checks.update({'health_'+k:v for k,v in same(before,after).items()})
 result={'passed':failure is None and all(checks.values()),'checks':checks,'failure':failure,'calls':calls,'before':before,'after':after,'sha256':hashlib.sha256((HERE/'build/flux-mntns').read_bytes()).hexdigest()}
 out=HERE/'results';out.mkdir(exist_ok=True);p=out/('storage-'+uuid.uuid4().hex[:12]+'.json');p.write_text(json.dumps(result,indent=2));os.chown(p,1000,1000)
 print(json.dumps({'passed':result['passed'],'checks':checks,'failure':failure,'result':str(p)}));sys.exit(0 if result['passed'] else 1)
