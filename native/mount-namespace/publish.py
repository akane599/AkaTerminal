"""Publish the tested native helper and pin its bytes in the APK shell asset."""
from pathlib import Path
import hashlib, re, shutil

root = Path(__file__).resolve().parents[2]
source = Path(__file__).resolve().parent / 'build/flux-mntns'
assets = root / 'app/src/main/assets/scripts/chroot'
digest = hashlib.sha256(source.read_bytes()).hexdigest()
guard = assets / 'flux_namespace.sh'
text, count = re.subn(r"FLUX_MNTNS_SHA256='[^']*'", f"FLUX_MNTNS_SHA256='{digest}'", guard.read_text())
assert count == 1
shutil.copyfile(source, assets / 'flux-mntns')
(assets / 'flux-mntns').chmod(0o644)
guard.write_text(text)
print(digest)
