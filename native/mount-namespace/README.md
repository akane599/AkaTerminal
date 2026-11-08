# Private chroot mount namespaces (Samsung candidate)

The chroot launcher previously mounted guest `/dev`, `/proc`, `/sys` and shared
storage in Android's global mount namespace. `flux-mntns` now keeps those mounts
in one private namespace per rootfs and boot. Terminal sessions, GUI scripts,
setup, stop, uninstall and root-backed SAF file operations join the same owner.
PRoot is unchanged. This is a local Samsung candidate, not an upstream release.

## Lifecycle

The root-owned keeper copies PID 1's mount view, makes propagation recursively
private, and creates a private rootfs bind with dev/suid enabled. It never remounts
Android's `/data`. Android's existing `/dev/pts` is bound into the guest so terminal
PTYs created by the Android app remain usable. Ordinary clients hold shared
leases outside the guest; removal requires an exclusive lease and no remaining
processes in the namespace. PID/start time, boot, namespace and rootfs identity
are checked before entry. Signals and owner retirement use pidfds.

Setup cleanup preserves the verified private root bind while removing its child
mounts, so extraction and subsequent launches retain dev/suid on the guest only.
The namespace guard sets this cleanup context after verifying actual membership.
Uninstall still removes the entire guest under its exclusive lease.

State is under `/data/adb/fluxlinux/namespaces/<boot>/<device>-<inode>`, with root-only
directories and files. `ensure` reuses a healthy keeper. If its recorded PID has
actually disappeared, it first searches for the surviving private namespace and
checks its root mount anchor and rootfs identity; inode numbers alone can be
recycled immediately. It creates a replacement keeper inside that same namespace
without changing mounts or terminating clients. If no guest namespace survives,
it requires an exclusive client lease and no global guest mounts before creating
a fresh private namespace. The launcher then restores its ordinary guest mounts.

Recovery writes an exclusive, durable intent and archives the exact old owner
record before publishing a replacement. Corrupt identities, PID reuse, incomplete
recovery attempts and retired state remain refused. Publication after a crash can
be retried only under the newly committed owner identity. Do not delete protection
records to force an entry. Recovery does not explain or prevent the original
keeper death, and cannot restore processes or volatile tmpfs contents that died. The helper requires the pidfd-capable Samsung kernel
tested here; older Android kernels have not been qualified.

The guard verifies the packaged native helper hash before execution. Kotlin staging
also verifies both assets and keeps them in the existing protected root stage.
SAF uses `host-b64` to run its Android-side operations inside the guest namespace
without consuming binary stdin. Its mount checks therefore see the actual guest
mounts and retain deletion restrictions for host-backed paths.

Mount operations also take a kernel `flock` on the persistent rootfs
`.flux_mount.flock` inode. The old mkdir/PID/time lock admitted two contenders
in regression tests and was replaced in all seven launcher/stop/uninstall copies.
The `.flux_mount.lock/owner` record remains diagnostic only. Never delete the flock
file while the rootfs is in use. Android mksh requires explicit `9>&9` when passing
that lock descriptor to BusyBox; the actual device test covers exclusion and
release after owner death. Root-job cancellation is serialized so two cancel
callers cannot destroy the su client before its descendant scan finishes.

## Build and owned tests

```sh
FLUX_NDK_ROOT=/path/to/android-ndk-r27c sh native/mount-namespace/build.sh
python3 native/mount-namespace/publish.py
sudo python3 native/mount-namespace/device_test.py --owned-fixture
sudo python3 native/mount-namespace/script_device_test.py --owned-script-fixture
# Additional fault-injection binary is test-only and is never packaged:
CXX="$PWD/native/mount-namespace/fault-cxx.sh" \
  FLUX_MNTNS_OUT="$PWD/native/mount-namespace/build/flux-mntns-fault" \
  FLUX_NDK_ROOT=/path/to/android-ndk-r27c sh native/mount-namespace/build.sh
sudo python3 native/mount-namespace/recovery_device_test.py --owned-recovery-fixture
```

The native build uses host ARM clang/lld 18 with NDK r27c headers/static libraries,
Android 29, BTI/PAC, 16 KiB pages and RELRO/NOW. Tests require this phone's Android
root through `/proc/1/root` and the research `verify_runtime.py`. They create only
unique disposable guest/staging paths. Failure preserves ambiguous state for
inspection. `preflight` is read-only and checks real-root admission without creating
an owner or changing mounts. Results are saved under ignored `results/`.

Covered: owner reuse, shared clients, signals, active leases and orphan users,
malformed/stale identities, real launcher and removal functions, X11 bind refresh,
inherited Android PTY, guest UID 1000 PTY allocation, setuid execution, process-root
detection, SAF namespace entry and exact binary streams. Kernel/runtime snapshots
are compared before and after; normal activity counters must be interpreted from
the recorded delta, never silently discarded.

## Installation and remaining acceptance

The r2 owner-recovery update is compatible with a healthy r1 private keeper and
its existing record format. Update the APK while retaining app/Ubuntu data; no
planned reboot, reset or ZIP installation is required. Installing the app can
close active terminals, so the user performs the update after the agent has saved
its work. Actual recovery after an Android soft reboot remains to be accepted;
owned tests intentionally kill only fixture keepers, not the production guest.
The original r1 migration constraints below apply to global-mount installations.


Existing globally mounted Ubuntu cannot be migrated while these sessions run.
The new launcher deliberately refuses that condition. Prepare the signed APK,
install it as an update preserving app data, then let the user perform a full
reboot, regain root and open AkaTerminal. No factory reset or Ubuntu reinstall is
needed. The agent must not reboot, restart zygote or unmount the running guest.

The r1 private-mount candidate passed real cold-boot, terminal/GUI/DocumentsUI
and Duck Ubuntu-mount acceptance on this phone. The r2 recovery path needs its
own post-update real-use acceptance. Fully private mounts
do not receive later global mount propagation; removable storage and Android
storage-service restart behavior remain unqualified. This package does not claim
to fix unrelated Duck UID, ADB or uname findings.

The candidate build reuses the installed, source-unchanged X11/PTY native libraries
through an external Gradle init script, while rebuilding app code and the new
namespace helper. The release archive records their hashes, exact source base,
patch and build tooling. Preserve that provenance when reproducing the APK.

## Shared storage after Android soft reboot (Samsung r3)

`storage STATE ROOTFS` runs only inside the validated private guest namespace. It serializes with other storage repairs and the namespace lease, leaves healthy mounts alone, and repairs only a single disconnected FUSE mount (`ENOTCONN`) without descendants. With no mount, it creates the initial storage attachment. Other errors are refused; the launcher reports the problem and keeps the terminal usable.

The helper pins current user-0 storage from init, briefly visits that namespace only to obtain a detached `open_tree` clone, returns to the guest, makes the clone private with `mount_setattr`, then attaches with `move_mount`. It never changes init mounts. Ordinary bind cannot import a mount from another namespace on the tested kernel. Before detaching old storage it clones that mount for rollback; an O_PATH FD alone cannot restore a detached mount. Source validation and clone preparation happen before detaching. The two mount changes are not crash atomic. Open FDs into dead storage remain dead; newly opened paths use the replacement. No background polling or Android restart. Requires these Linux mount syscalls; unavailable operations leave the existing mount unchanged. Multi-user Android is not qualified.

`storage_fixture.c` is a disposable minimal FUSE server, not an APK asset. `storage_acceptance.py --owned-storage-fixture` verifies real disconnected storage, fresh contents, rollback injection, lock exclusion, same keeper/live client, private propagation and unchanged production health. `script_device_test.py` also exercises actual launcher recovery. Test-only source overrides and bind-fault controls compile only under `FLUX_RECOVERY_TEST` and are absent from the shipped helper.

### Cached directory attributes (r4)

The real Android FUSE mount can return cached `stat(sdcard)` after server death while lookup/readdir/statfs return ENOTCONN. r4 queries statfs for liveness. The fixture retains attributes for an hour and proves the shipped r3 helper skips the dead mount; the new helper and actual launcher repair it. A standalone exact tested r4 helper repaired the real stale /sdcard with the same keeper/namespace and all other mounts intact; UID1000 65792-byte create/read/fsync/rename/delete passed. Installed r4 APK acceptance is separate.
