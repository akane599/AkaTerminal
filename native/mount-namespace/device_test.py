"""Real Android owned-fixture test. Root required; never invoke production assets.

Stages only this helper. Every mount happens through its owned private namespace;
the real Ubuntu root is only used in a negative 'already globally mounted' check.
"""
from pathlib import Path
import hashlib, json, os, shutil, signal, subprocess, sys, time, uuid

HERE = Path(__file__).resolve().parent
ANDROID = Path('/proc/1/root')
RESEARCH = Path('/home/akane/research/duck-mount-20261106')
sys.path.insert(0, str(RESEARCH / 'native-family-order'))
sys.path.insert(0, '/home/akane/research/duck-mount-20261106/native-generation-r1')
from capture_live import snapshot
from verify_runtime import same

def main():
    assert os.geteuid() == 0 and sys.argv[1:] == ['--owned-fixture']
    tag = 'codex-ns-fixture-' + uuid.uuid4().hex[:12]
    host = ANDROID / 'data/local/tmp' / tag
    guest = host / 'guest'
    state = ANDROID / 'data/adb/fluxlinux' / tag
    stage = host / 'flux-mntns'
    android_path = lambda p: str(p).removeprefix('/proc/1/root')
    before = snapshot()
    global_before = Path('/proc/1/mountinfo').read_bytes()
    parent_before = Path('/proc/self/mountinfo').read_bytes()
    checks, calls = {}, []
    processes = []
    owner = None
    failure = None

    def call(mode, *args, root=None, scope=None, expected=0):
        argv = ['chroot', '/proc/1/root', android_path(stage), mode,
                android_path(scope or state), android_path(root or guest), *args]
        r = subprocess.run(argv, capture_output=True, text=True, timeout=20)
        calls.append({'mode': mode, 'args': list(args), 'exit': r.returncode,
                      'stdout': r.stdout, 'stderr': r.stderr})
        assert r.returncode == expected, calls[-1]
        return r

    def shell(text, *, mode='run', expected=0):
        return call(mode, '--', '/system/bin/sh', '-c', text, 'fixture',
                    android_path(guest), android_path(stage), android_path(state), expected=expected)

    def live_owner():
        return json.loads(call('inspect').stdout)

    try:
        host.mkdir(mode=0o700)
        guest.mkdir(mode=0o700)
        (guest / 'mnt').mkdir(mode=0o700)
        shutil.copyfile(HERE / 'build/flux-mntns', stage)
        stage.chmod(0o700)
        subprocess.run(['chroot', '/proc/1/root', '/system/bin/chcon',
                        'u:object_r:system_file:s0', android_path(stage)], check=True)
        # Read-only probe, even on a future boot where Ubuntu is already private.
        # Never call 'create' on a real guest as part of a test.
        badstate = state.parent / (tag + '-global-refusal')
        real_root = '/data/local/tmp/chrootUbuntu'
        globally_mounted = any(line.split()[4] == real_root or line.split()[4].startswith(real_root + '/')
                               for line in global_before.decode().splitlines())
        call('preflight', root=ANDROID / real_root.lstrip('/'), scope=badstate, expected=125 if globally_mounted else 0)
        checks['global_preflight_read_only_and_matches_observation'] = not badstate.exists()
        call('create')
        owner = live_owner()
        checks['owner_namespace_distinct'] = owner['namespace'] != os.stat('/proc/1/ns/mnt').st_ino
        call('create')
        checks['create_idempotent'] = live_owner() == owner
        shell('mount -t tmpfs -o size=1m,nodev,nosuid,noexec flux-owned "$1/mnt" && printf first > "$1/mnt/marker"')
        checks['mount_not_propagated'] = list((guest / 'mnt').iterdir()) == []
        checks['second_client_sees_state'] = shell('cat "$1/mnt/marker"').stdout == 'first'
        shell('printf second > "$1/mnt/marker"')
        checks['third_client_sees_update'] = shell('cat "$1/mnt/marker"').stdout == 'second'
        nested = shell('"$2" run "$3" "$1" -- /system/bin/cat "$1/mnt/marker"')
        checks['nested_client_works'] = nested.stdout == 'second'
        shell('exit 37', expected=37)
        checks['exit_status_preserved'] = True

        argv = ['chroot', '/proc/1/root', android_path(stage), 'run', android_path(state),
                android_path(guest), '--', '/system/bin/sh', '-c',
                'echo ready > "$1/active"; exec /system/bin/sleep 20', 'fixture', android_path(guest)]
        active = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        processes.append(active)
        deadline = time.monotonic() + 5
        while not (guest / 'active').exists() and active.poll() is None and time.monotonic() < deadline:
            time.sleep(.03)
        assert (guest / 'active').read_text().strip() == 'ready'
        shell('echo must-not-run > "$1/forbidden"', mode='exclusive', expected=125)
        call('retire', expected=125)
        call('create')
        checks['active_lease_blocks_exclusive_and_retire'] = not (guest / 'forbidden').exists()
        checks['create_with_active_session_is_idempotent'] = live_owner() == owner
        active.send_signal(signal.SIGTERM)
        out, err = active.communicate(timeout=5)
        checks['termination_forwarded'] = active.returncode == 143
        processes.remove(active)

        # A daemonized guest outlives the lease monitor. Namespace enumeration
        # must still prevent destructive operations while it is alive.
        shell('/system/bin/sleep 3 </dev/null >/dev/null 2>&1 &')
        shell('echo must-not-run > "$1/forbidden"', mode='exclusive', expected=125)
        checks['orphan_namespace_user_blocks_exclusive'] = not (guest / 'forbidden').exists()
        time.sleep(3.2)
        shell('test -r "$1/mnt/marker"', mode='exclusive')
        checks['exclusive_after_last_session'] = True

        original = (state / 'owner').read_bytes()
        (state / 'owner').write_text('invalid owner\n')
        try:
            call('inspect', expected=125)
            call('create', expected=125)
            checks['malformed_owner_is_not_replaced'] = (state / 'owner').read_text() == 'invalid owner\n'
        finally:
            (state / 'owner').write_bytes(original)
        moved = host / 'guest-moved'
        guest.rename(moved)
        guest.mkdir(mode=0o700)
        try:
            call('inspect', expected=125)
            call('create', expected=125)
            checks['rootfs_replacement_refused'] = True
        finally:
            guest.rmdir()
            moved.rename(guest)
        call('retire')
        checks['retirement_record_preserved'] = (state / 'retired').exists() and not (state / 'owner').exists()
        call('create', expected=125)
        checks['retired_state_not_silently_reused'] = not (state / 'owner').exists()
        owner = None
    except BaseException:
        import traceback
        failure = traceback.format_exc()
    finally:
        for p in processes:
            if p.poll() is None:
                p.terminate()
            p.communicate(timeout=6)
        if owner is None and (state / 'owner').exists():
            try:
                owner = live_owner()
            except BaseException:
                owner = {'unknown': True}
        if owner:
            # Retire only our exact owner through the validated helper. If this
            # refuses, preserve the fixture and state for inspection.
            try:
                time.sleep(3.2)
                call('retire')
                owner = None
            except BaseException:
                pass
        checks['global_mountinfo_identical'] = Path('/proc/1/mountinfo').read_bytes() == global_before
        checks['parent_mountinfo_identical'] = Path('/proc/self/mountinfo').read_bytes() == parent_before
        # No recursive delete. Fixture has only known regular files/directories.
        cleanup_safe = owner is None and (not (state / 'creating').exists() or (state / 'retired').exists())
        if cleanup_safe:
            for p in sorted(host.rglob('*'), key=lambda p: len(p.parts), reverse=True):
                if p.is_symlink() or p.is_file():
                    p.unlink()
                else:
                    p.rmdir()
            host.rmdir()
            for base in [state, state.parent / (tag + '-global-refusal')]:
                if base.exists():
                    for p in base.iterdir():
                        assert p.name in ['gate.lock', 'creating', 'owner.new', 'retired'] and not p.is_symlink()
                        p.unlink()
                    base.rmdir()
        checks['fixtures_removed'] = not host.exists() and not state.exists()
        after = snapshot()
        checks.update({'health_' + k: v for k, v in same(before, after).items()})
        report = {'passed': failure is None and all(checks.values()), 'checks': checks,
                  'failure': failure, 'calls': calls, 'before': before, 'after': after,
                  'binary_sha256': hashlib.sha256((HERE / 'build/flux-mntns').read_bytes()).hexdigest(),
                  'fixture': str(host), 'state': str(state)}
        out = HERE / 'results'
        out.mkdir(exist_ok=True)
        result = out / (tag + '.json')
        result.write_text(json.dumps(report, indent=2) + '\n')
        os.chown(result, 1000, 1000)
    print(json.dumps({'passed': report['passed'], 'checks': checks, 'failure': failure, 'result': str(result)}))
    assert report['passed']

if __name__ == '__main__':
    main()
