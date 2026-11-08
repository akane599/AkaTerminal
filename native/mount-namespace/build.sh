#!/bin/sh
# Phone-compatible, single compiler invocation; no Gradle/JVM.
set -eu
: "${FLUX_NDK_ROOT:?Set FLUX_NDK_ROOT to an Android NDK root}"
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
NDK_LLVM="$FLUX_NDK_ROOT/toolchains/llvm/prebuilt/linux-x86_64"
OUT="${FLUX_MNTNS_OUT:-$HERE/build/flux-mntns}"
mkdir -p "$(dirname -- "$OUT")"
"${CXX:-clang++-18}" --target=aarch64-linux-android29 --sysroot="$NDK_LLVM/sysroot" \
  -resource-dir="$NDK_LLVM/lib/clang/18" -std=c++17 -O2 -Wall -Wextra -Werror \
  -stdlib=libc++ -nostdlib++ -fPIE -pie -fno-addrsig -mbranch-protection=standard \
  -fvisibility=hidden -fvisibility-inlines-hidden -fuse-ld=lld-18 \
  --rtlib=compiler-rt --unwindlib=none -Wl,-z,max-page-size=16384,-z,relro,-z,now \
  "$HERE/namespace.cpp" -o "$OUT" -Wl,--start-group \
  "$NDK_LLVM/sysroot/usr/lib/aarch64-linux-android/libc++_static.a" \
  "$NDK_LLVM/sysroot/usr/lib/aarch64-linux-android/libc++abi.a" \
  "$NDK_LLVM/lib/clang/18/lib/linux/aarch64/libunwind.a" -Wl,--end-group -lm
"${CC:-clang-18}" --target=aarch64-linux-android29 --sysroot="$NDK_LLVM/sysroot" \
  -resource-dir="$NDK_LLVM/lib/clang/18" -std=c11 -O2 -Wall -Wextra -Werror \
  -static -mbranch-protection=standard -fuse-ld=lld-18 --rtlib=compiler-rt \
  -Wl,-z,max-page-size=16384 "$HERE/guest_probe.c" -o "$(dirname "$OUT")/guest-probe"

"${CC:-clang-18}" --target=aarch64-linux-android29 --sysroot="$NDK_LLVM/sysroot" \
  -resource-dir="$NDK_LLVM/lib/clang/18" -std=c11 -O2 -Wall -Wextra -Werror \
  -static -mbranch-protection=standard -fuse-ld=lld-18 --rtlib=compiler-rt \
  -Wl,-z,max-page-size=16384 "$HERE/storage_fixture.c" -o "$(dirname "$OUT")/storage-fixture"
