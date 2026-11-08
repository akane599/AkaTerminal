#!/system/bin/sh
# Source from a root-staged lifecycle script, before any mount/chroot/removal.
# The native hash is updated only by native/mount-namespace/publish.py.
FLUX_MNTNS_SHA256='622124b83202974ecc56a324a21a0cc8de7a3d0eec52e14a30416c3490ed1f14'

flux_namespace_enter() {
    unset FLUX_PRIVATE_ROOT_MOUNT
    _flux_ns_operation="$1"
    _flux_ns_root="$2"
    shift 2
    [ "$(id -u)" = 0 ] || { echo 'FluxLinux: root required for chroot namespace' >&2; exit 125; }
    case "$_flux_ns_operation" in run|setup|remove) ;; *) exit 125 ;; esac
    case "$_flux_ns_root" in /data/local/tmp/chroot*) ;; *)
        echo 'FluxLinux: invalid chroot namespace path' >&2; exit 125 ;;
    esac
    case "${_flux_ns_root#/data/local/tmp/}" in *[!A-Za-z0-9_-]*) exit 125 ;; esac
    # Missing uninstall targets retain the original script's no-op handling.
    if [ "$_flux_ns_operation" = remove ] && [ ! -e "$_flux_ns_root" ]; then return 0; fi
    if [ "$_flux_ns_operation" = setup ] && [ ! -e "$_flux_ns_root" ]; then
        (umask 077; mkdir "$_flux_ns_root") || exit 125
    fi
    _flux_ns_bin="$(dirname "$0")/flux-mntns"
    case "$_flux_ns_bin" in /data/adb/fluxlinux/*/flux-mntns) ;; *)
        echo 'FluxLinux: namespace helper must be in the protected root stage' >&2; exit 125 ;;
    esac
    [ ! -L "$_flux_ns_bin" ] && [ -f "$_flux_ns_bin" ] || exit 125
    _flux_ns_sha=$(sha256sum "$_flux_ns_bin" 2>/dev/null) || exit 125
    [ "${_flux_ns_sha%% *}" = "$FLUX_MNTNS_SHA256" ] || {
        echo 'FluxLinux: namespace helper failed its APK hash check' >&2; exit 125;
    }
    chmod 0700 "$_flux_ns_bin" || exit 125
    _flux_ns_boot=$(cat /proc/sys/kernel/random/boot_id) || exit 125
    _flux_ns_root_id=$(stat -c '%d-%i' "$_flux_ns_root") || exit 125
    case "$_flux_ns_boot/$_flux_ns_root_id" in *[!0-9a-f/-]*) exit 125 ;; esac
    _flux_ns_state="/data/adb/fluxlinux/namespaces/$_flux_ns_boot/$_flux_ns_root_id"
    "$_flux_ns_bin" inside "$_flux_ns_state" "$_flux_ns_root"
    _flux_ns_rc=$?
    case "$_flux_ns_rc" in
        0) FLUX_PRIVATE_ROOT_MOUNT=1; export FLUX_PRIVATE_ROOT_MOUNT; return 0 ;;
        3|4) ;;
        *) exit "$_flux_ns_rc" ;;
    esac
    "$_flux_ns_bin" ensure "$_flux_ns_state" "$_flux_ns_root" || exit $?
    case "$_flux_ns_operation" in setup) _flux_ns_operation=run ;; esac
    exec "$_flux_ns_bin" "$_flux_ns_operation" "$_flux_ns_state" "$_flux_ns_root" \
        -- /system/bin/sh "$0" "$@"
    exit 125
}
