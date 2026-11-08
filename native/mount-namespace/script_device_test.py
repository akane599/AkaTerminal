"""Exercise actual launcher and uninstall functions on a disposable empty rootfs.
No real guest entry, package manager, UI callback, production staging, or reboot.
"""
from pathlib import Path
import base64, fcntl, hashlib, json, os, select, shutil, signal, struct, subprocess, sys, time, traceback, uuid

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parents[1] / 'app/src/main/assets/scripts/chroot'
ANDROID = Path('/proc/1/root')
sys.path.insert(0, '/home/akane/research/duck-mount-20261106/native-family-order')
sys.path.insert(0, '/home/akane/research/duck-mount-20261106/native-generation-r1')
from capture_live import snapshot
from verify_runtime import same

def main():
    assert os.geteuid() == 0 and sys.argv[1:] == ['--owned-script-fixture']
    tag = uuid.uuid4().hex[:12]
    guest = ANDROID / ('data/local/tmp/chrootFluxFixture' + tag)
    stage = ANDROID / ('data/adb/fluxlinux/codex-script-fixture-' + tag)
    hosttmp = stage / 'host/tmp'
    path = lambda p: str(p).removeprefix('/proc/1/root')
    before = snapshot()
    checks, calls = {}, []
    failure, state = None, None
    retired = False
    active = None
    master = None

    def run(argv, expected=0):
        r = subprocess.run(['chroot', '/proc/1/root', '/system/bin/env',
                            'FLUX_CHROOT=' + path(guest), 'FLUX_PREFIX=' + path(stage / 'host'),
                            'FLUX_HOST_TMP=' + path(hosttmp), *argv],
                           capture_output=True, text=True, timeout=35)
        calls.append({'argv': argv, 'exit': r.returncode, 'stdout': r.stdout, 'stderr': r.stderr})
        assert r.returncode == expected, calls[-1]
        return r

    try:
        stage.mkdir(mode=0o700)
        guest.mkdir(mode=0o755)
        (guest / '.flux_configured').touch()
        hosttmp.mkdir(mode=0o700, parents=True)
        for name in ['flux-mntns', 'flux_namespace.sh', 'fluxlinux_chroot.sh',
                     'resolve_bb.sh', 'uninstall_guest_chroot.sh', 'setup_guest_chroot.sh',
                     'setup_debian13_chroot.sh', 'setup_alpine_chroot.sh']:
            shutil.copyfile(ASSETS / name, stage / name)
            # Match RootShell's production staging: 0600, default SELinux label.
            # The hash-verified guard makes only the native helper executable.
            (stage / name).chmod(0o600)
        for name in ['probe', 'suid-probe']:
            shutil.copyfile(HERE / 'build/guest-probe', guest / name)
            (guest / name).chmod(0o4755 if name == 'suid-probe' else 0o755)
        boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        st = guest.stat()
        state = ANDROID / f'data/adb/fluxlinux/namespaces/{boot}/{st.st_dev}-{st.st_ino}'
        assert not state.exists()
        run(['/system/bin/sh', path(stage / 'fluxlinux_chroot.sh'), 'mount'])
        checks['actual_launcher_mount_succeeded'] = True
        owner = json.loads(run([path(stage / 'flux-mntns'), 'inspect', path(state), path(guest)]).stdout)
        checks['actual_launcher_private_namespace'] = owner['namespace'] != os.stat('/proc/1/ns/mnt').st_ino
        def inside(command):
            return run([path(stage / 'flux-mntns'), 'run', path(state), path(guest), '--',
                        '/system/bin/sh', '-c', command, 'fixture', path(guest)])
        mountinfo = inside('cat /proc/self/mountinfo').stdout
        mounts = [line for line in mountinfo.splitlines() if line.split()[4].startswith(path(guest))]
        checks['root_bind_plus_seven_mounts'] = len(mounts) == 8
        rootline = next(line for line in mounts if line.split()[4] == path(guest))
        flags = set(rootline.split()[5].split(','))
        checks['dev_suid_on_private_root_only'] = not (flags & {'nodev', 'nosuid', 'noexec'})
        checks['no_private_mounts_visible_globally'] = path(guest) not in Path('/proc/1/mountinfo').read_text()
        checks['guest_devices_available_privately'] = inside('test -c "$1/dev/null" && test -c "$1/dev/pts/ptmx" && test -r "$1/proc/self/mountinfo"').returncode == 0
        # Reproduce the real soft-reboot storage failure on this owned root only.
        shutil.copyfile(HERE / 'build/storage-fixture', stage / 'storage-fixture')
        (stage / 'storage-fixture').chmod(0o700)
        inside('umount "$1/sdcard"')
        server = subprocess.Popen(['chroot', '/proc/1/root', path(stage / 'flux-mntns'),
            'run', path(state), path(guest), '--', path(stage / 'storage-fixture'),
            path(guest / 'sdcard'), 'owned1'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        assert select.select([server.stdout], [], [], 5)[0]
        ready = server.stdout.readline(); assert ready.startswith('READY '), ready
        server_pid = int(ready.split()[1])
        server_fd = os.pidfd_open(server_pid)
        assert path(stage / 'storage-fixture').encode() in Path('/proc',str(server_pid),'cmdline').read_bytes()
        inside('stat "$1/sdcard"')
        signal.pidfd_send_signal(server_fd, signal.SIGKILL)
        server.communicate(timeout=6); os.close(server_fd)
        checks['actual_launcher_cached_stat_after_death'] = inside('stat "$1/sdcard"').returncode == 0
        broken = inside('stat -f "$1/sdcard" 2>&1 || true').stdout
        checks['actual_launcher_ENOTCONN_reproduced'] = 'Transport endpoint is not connected' in broken
        run(['/system/bin/sh', path(stage / 'fluxlinux_chroot.sh'), 'mount'])
        checks['actual_launcher_repairs_storage'] = inside('test -r "$1/sdcard/Download/Samsung-C5-Yedek/README.md"').returncode == 0
        checks['actual_launcher_repair_preserves_owner'] = json.loads(run([path(stage / 'flux-mntns'), 'inspect', path(state), path(guest)]).stdout) == owner
        # Use the Android app-side PTY, not this Ubuntu session's existing PTY mount.
        master = os.open(ANDROID / 'dev/ptmx', os.O_RDWR | os.O_NOCTTY)
        fcntl.ioctl(master, 0x40045431, struct.pack('i', 0)) # TIOCSPTLCK
        number = struct.unpack('I', fcntl.ioctl(master, 0x80045430, bytes(4)))[0] # TIOCGPTN
        slave = os.open(ANDROID / f'dev/pts/{number}', os.O_RDWR | os.O_NOCTTY)
        command = ['chroot', '/proc/1/root', path(stage / 'flux-mntns'), 'run', path(state), path(guest), '--',
                   '/system/bin/sh', '-c', '. "$1/resolve_bb.sh"; resolve_bb && exec "$BB" chroot "$2" /probe --pty',
                   'fixture', path(stage), path(guest)]
        active = subprocess.Popen(command, stdin=slave, stdout=slave, stderr=slave)
        os.close(slave)
        output = b''
        deadline = time.monotonic() + 6
        while b'PTY_OK' not in output and time.monotonic() < deadline:
            if select.select([master], [], [], .2)[0]: output += os.read(master, 4096)
            if active.poll() is not None: break
        assert b'PTY_OK' in output, output.decode(errors='replace')
        probe_pid = int(output.decode().split('pid=')[1].split()[0])
        checks['inherited_android_pty_resolves_in_guest'] = True
        checks['guest_user_creates_new_pty'] = b'uid=1000' in output
        checks['guest_process_root_remains_detectable'] = os.readlink(f'/proc/{probe_pid}/root') == path(guest)
        calls.append({'pty_output': output.decode(errors='replace')})
        # Kill only this fixture keeper; keep the actual guest PTY client alive.
        def kill_fixture_owner(record):
            proc = Path('/proc') / str(record['pid'])
            assert int((proc / 'stat').read_text().rsplit(')', 1)[1].split()[19]) == record['start']
            assert path(guest).encode() in (proc / 'cmdline').read_bytes()
            fd = os.pidfd_open(record['pid'])
            signal.pidfd_send_signal(fd, signal.SIGKILL)
            poller = select.poll(); poller.register(fd, select.POLLIN)
            assert poller.poll(5000)
            os.close(fd)
            deadline = time.monotonic() + 5
            while proc.exists():
                assert time.monotonic() < deadline
                time.sleep(.03)
        old_owner = owner
        kill_fixture_owner(owner)
        run(['/system/bin/sh', path(stage / 'fluxlinux_chroot.sh'), 'mount'])
        owner = json.loads(run([path(stage / 'flux-mntns'), 'inspect', path(state), path(guest)]).stdout)
        checks['launcher_recovers_live_guest_namespace'] = owner['pid'] != old_owner['pid'] and owner['namespace'] == old_owner['namespace']
        checks['launcher_recovery_preserves_live_pty'] = active.poll() is None and Path('/proc', str(probe_pid)).exists()
        checks['launcher_recovery_retains_guest_mounts'] = len([line for line in inside('cat /proc/self/mountinfo').stdout.splitlines() if line.split()[4].startswith(path(guest))]) == 8
        active.send_signal(signal.SIGTERM)
        assert active.wait(timeout=5) == 143
        active = None
        os.close(master); master = None
        old_owner = owner
        kill_fixture_owner(owner)
        run(['/system/bin/sh', path(stage / 'fluxlinux_chroot.sh'), 'mount'])
        owner = json.loads(run([path(stage / 'flux-mntns'), 'inspect', path(state), path(guest)]).stdout)
        checks['launcher_recreates_empty_guest_namespace'] = owner['pid'] != old_owner['pid'] and any(p.read_text().startswith('fresh\n') for p in state.glob('*.intent'))
        checks['launcher_rebuilds_all_guest_mounts'] = len([line for line in inside('cat /proc/self/mountinfo').stdout.splitlines() if line.split()[4].startswith(path(guest))]) == 8
        suid = inside('. "'+path(stage)+'/resolve_bb.sh"; resolve_bb && "$BB" chroot "$1" /probe --suid')
        checks['guest_setuid_exec_preserved'] = suid.stdout.strip() == 'uid=1000 euid=0'
        host_payload = base64.b64encode(b'/system/bin/readlink /proc/self/ns/mnt').decode()
        host_view = run(['/system/bin/sh', path(stage / 'fluxlinux_chroot.sh'), 'host-b64', '--', host_payload])
        checks['saf_host_command_uses_guest_namespace'] = host_view.stdout.strip() == f"mnt:[{owner['namespace']}]"
        raw = bytes(range(256)) * 257
        pipe = subprocess.run(['chroot', '/proc/1/root', '/system/bin/env',
                               'FLUX_CHROOT=' + path(guest), 'FLUX_PREFIX=' + path(stage / 'host'),
                               'FLUX_HOST_TMP=' + path(hosttmp), '/system/bin/sh',
                               path(stage / 'fluxlinux_chroot.sh'), 'host-b64', '--',
                               base64.b64encode(b'/system/bin/cat').decode()],
                              input=raw, capture_output=True, timeout=20)
        checks['saf_binary_stdin_stdout_preserved'] = pipe.returncode == 0 and pipe.stdout == raw
        run(['/system/bin/sh', path(stage / 'fluxlinux_chroot.sh'), 'mount'])
        checks['second_launcher_uses_same_namespace'] = json.loads(run([path(stage / 'flux-mntns'), 'inspect', path(state), path(guest)]).stdout) == owner
        run(['/system/bin/sh', path(stage / 'fluxlinux_chroot.sh'), 'mount', '--x11'])
        x11 = inside('cat /proc/self/mountinfo').stdout
        checks['x11_bind_in_same_private_namespace'] = any(line.split()[4] == path(guest / 'tmp/.X11-unix') for line in x11.splitlines())
        run(['/system/bin/sh', path(stage / 'fluxlinux_chroot.sh'), 'mount', '--x11'])
        again = inside('cat /proc/self/mountinfo').stdout
        checks['x11_refresh_does_not_stack'] = sum(line.split()[4] == path(guest / 'tmp/.X11-unix') for line in again.splitlines()) == 1
        # Android mksh closes saved FDs on exec unless explicitly redirected.
        # Exercise real BusyBox flock exclusion and release on owner death.
        launcher = (ASSETS / 'fluxlinux_chroot.sh').read_text()
        locklib = stage / 'lock-library.sh'
        locklib.write_text(launcher[launcher.index('# --- mount lock (M16)'):launcher.index('# --- end mount lock')])
        locklib.chmod(0o600)
        lockcommand = '. "$1/resolve_bb.sh"; resolve_bb && . "$1/lock-library.sh" && mount_lock "$2" && echo LOCKED; read -r done'
        active = subprocess.Popen(['chroot', '/proc/1/root', path(stage / 'flux-mntns'), 'run', path(state), path(guest), '--',
                                   '/system/bin/sh', '-c', lockcommand, 'fixture', path(stage), path(guest)],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert select.select([active.stdout], [], [], 6)[0], 'lock owner readiness timeout'
        assert active.stdout.readline().strip() == b'LOCKED'
        flockcmd = '. "'+path(stage)+'/resolve_bb.sh"; resolve_bb; exec 9>> "$1/.flux_mount.flock"; "$BB" flock -xn 9 9>&9'
        inside('if ('+flockcmd+'); then exit 77; fi')
        checks['android_flock_excludes_second_owner'] = True
        active.send_signal(signal.SIGTERM)
        assert active.wait(timeout=6) == 143
        active = None
        inside(flockcmd)
        checks['android_flock_released_after_owner_death'] = True
        for setup in ['setup_guest_chroot.sh', 'setup_debian13_chroot.sh', 'setup_alpine_chroot.sh']:
            # Source actual setup helpers only; no downloads, extraction or package changes.
            command = ('FLUX_SETUP_LIB=1; . "'+path(stage / setup)+'"; '
                       'GUESTPATH="$FLUX_CHROOT"; DEBIANPATH="$FLUX_CHROOT"; ALPINEPATH="$FLUX_CHROOT"; '
                       'cleanup_mounts')
            payload = base64.b64encode(command.encode()).decode()
            run(['/system/bin/sh', path(stage / 'fluxlinux_chroot.sh'), 'host-b64', '--', payload])
            after_cleanup = inside('cat /proc/self/mountinfo').stdout
            retained = [line for line in after_cleanup.splitlines() if line.split()[4].startswith(path(guest))]
            assert len(retained) == 1 and retained[0].split()[4] == path(guest), retained
            assert not (set(retained[0].split()[5].split(',')) & {'nodev', 'nosuid', 'noexec'})
            checks[setup + '_cleanup_preserves_private_root_only'] = True
            run(['/system/bin/sh', path(stage / 'fluxlinux_chroot.sh'), 'mount'])
        harness = stage / 'remove-fixture.sh'
        harness.write_text('''#!/system/bin/sh
. "$(dirname "$0")/flux_namespace.sh" || exit 125
flux_namespace_enter remove "$FLUX_CHROOT" "$@"
. "$(dirname "$0")/resolve_bb.sh" || exit 125
resolve_bb || exit 125
FLUX_UNINSTALL_LIB=1
. "$(dirname "$0")/uninstall_guest_chroot.sh" || exit 125
remove_rootfs "$FLUX_CHROOT"
''')
        harness.chmod(0o600)
        run(['/system/bin/sh', path(harness)])
        retired = (state / 'retired').exists() and not (state / 'owner').exists()
        checks['actual_uninstall_functions_removed_only_fixture'] = not guest.exists()
        checks['successful_remove_retires_owner'] = retired
        checks['no_fixture_tombstones_left'] = not list(guest.parent.glob(guest.name + '.deleting.*'))
    except BaseException:
        failure = traceback.format_exc()
    finally:
        if active is not None and active.poll() is None:
            active.terminate()
            active.wait(timeout=6)
        if master is not None: os.close(master)
        # Never delete an unretired fixture after a failure. Preserve it for inspection.
        if retired:
            for p in sorted(stage.rglob('*'), key=lambda p: len(p.parts), reverse=True):
                if p.is_symlink() or p.is_file(): p.unlink()
                else: p.rmdir()
            stage.rmdir()
            for p in state.iterdir():
                assert (p.name in ['gate.lock', 'creating', 'retired', 'recovery.lock', 'storage.lock'] or (p.name.startswith('recover-') and p.name.endswith('.intent')) or (p.name.startswith('owner-') and p.name.endswith('.history'))) and p.is_file() and not p.is_symlink()
                p.unlink()
            state.rmdir()
        checks['owned_files_cleaned'] = not guest.exists() and not stage.exists() and (state is None or not state.exists())
        after = snapshot()
        checks.update({'health_' + k: v for k,v in same(before, after).items()})
        report = {'passed': failure is None and all(checks.values()), 'checks': checks, 'failure': failure,
                  'calls': calls, 'before': before, 'after': after, 'guest': path(guest), 'stage': path(stage),
                  'source_hashes': {n: hashlib.sha256((ASSETS / n).read_bytes()).hexdigest() for n in
                                    ['flux-mntns','flux_namespace.sh','fluxlinux_chroot.sh','uninstall_guest_chroot.sh',
                                     'setup_guest_chroot.sh','setup_debian13_chroot.sh','setup_alpine_chroot.sh']}}
        out = HERE / 'results'
        out.mkdir(exist_ok=True)
        result = out / ('scripts-' + tag + '.json')
        result.write_text(json.dumps(report, indent=2) + '\n')
        os.chown(result, 1000, 1000)
    print(json.dumps({'passed': report['passed'], 'checks': checks, 'failure': failure, 'result': str(result)}))
    assert report['passed']

if __name__ == '__main__': main()
