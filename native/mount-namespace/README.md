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
directories and files. A dead, corrupt or ambiguous owner is refused, never silently
replaced. Retired state remains a tombstone for that boot. Do not delete protection
records to force an entry. The helper requires the pidfd-capable Samsung kernel
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

Existing globally mounted Ubuntu cannot be migrated while these sessions run.
The new launcher deliberately refuses that condition. Prepare the signed APK,
install it as an update preserving app data, then let the user perform a full
reboot, regain root and open AkaTerminal. No factory reset or Ubuntu reinstall is
needed. The agent must not reboot, restart zygote or unmount the running guest.

Real cold-boot entry, Duck's seven Ubuntu mount records, interactive terminal/GUI
and DocumentsUI still require acceptance after installation. Fully private mounts
do not receive later global mount propagation; removable storage and Android
storage-service restart behavior remain unqualified. This package does not claim
to fix unrelated Duck UID, ADB or uname findings.

The candidate build reuses the installed, source-unchanged X11/PTY native libraries
through an external Gradle init script, while rebuilding app code and the new
namespace helper. The release archive records their hashes, exact source base,
patch and build tooling. Preserve that provenance when reproducing the APK.
