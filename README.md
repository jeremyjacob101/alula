# alula

A macOS browser project based on Chromium. Current customization: lowercase
**alula** app/product branding, including About and Settings text. The current
development build has been compiled and manually tested locally on Apple M5.
Sidebar/workspaces and a native Swift bridge are future work.

This repository contains alula-owned source, Chromium patches, version pins,
and build scripts. Chromium itself and all generated output stay on your Mac.

## Layout

```text
alula/                 # future alula-owned Swift/C++ UI and feature source
chromium.lock.json     # exact upstream Chromium + depot_tools revisions
config/args.gn         # lean Apple Silicon development build settings
patches/               # committed changes applied to pinned Chromium
scripts/               # setup, patch checks, and patch export
build_alula.py         # guarded build launcher
src/                   # local Chromium checkout; ignored by this repository
depot_tools/           # local build tools; ignored
build-logs/            # local build/monitor logs; ignored
```

The parent repo uses `main`; local edits to Chromium live on `src`'s separate
`alula` branch. A patch commit in `src` is not backed up to GitHub until it is
exported and committed to this parent repository. Never add `src` as a submodule
or upload `src/out`, browser profiles, binaries, or caches.

## Existing working checkout

From the repository root (the existing `Codebase-v1` directory):

```sh
python3 scripts/setup_chromium.py --check
python3 build_alula.py --self-test
python3 build_alula.py --check
```

These checks do not fetch Chromium or compile it.

## Fresh setup on another Apple Silicon Mac

Requires full Xcode, Git, Python 3, an APFS volume, a path without spaces, and a
working Metal Toolchain. Install the latter if needed:

```sh
xcodebuild -downloadComponent MetalToolchain
```

Ensure Git has your name/email configured (needed for local patch commits).
Allow at least 75 GB immediately free for setup, plus additional build space;
100+ GB free is a more useful starting budget. The existing lean source and
build occupied roughly 42 GB together, but versions/settings change that.

```sh
git clone https://github.com/jeremyjacob101/alula.git
cd alula
python3 scripts/setup_chromium.py --fetch
python3 build_alula.py --self-test
python3 build_alula.py --check
```

Setup fetches only the pinned stable version and shallow dependencies, runs
their setup hooks, applies the patch series, and generates build files. It does
not compile the browser. It refuses to reset an existing `src` checkout.
Setup stops for disk space below 25 GB, over 50 GB additional disk consumption,
critical memory pressure, 4 GB swap, monitoring errors, or a step over 2 hours.
Its progress log is `build-logs/setup.log`.

The fresh-fetch path is scripted but has not yet been tested from an entirely
fresh checkout on another Mac. Patch replay and the existing checkout are
validated separately; do not treat this as a tested release installer.

## Build and launch

Quit the existing browser before rebuilding. Keep the Mac connected to power,
lid open, and the build Terminal window open:

```sh
python3 build_alula.py
```

The launcher uses 4 parallel jobs, prevents idle sleep, and logs status every
30 seconds. It stops at 25 GB free disk, a 75 GB build-output folder, 4 GB system
swap, 15 seconds of critical memory pressure, 12 hours, or monitoring failure.
Checks are sampled, not a filesystem quota. Ctrl-C stops the owned build tree.
Readiness checks validate prerequisites; they cannot guarantee a full build.

```sh
cat build-logs/latest/status.txt
tail -f build-logs/latest/build.log
```

After `SUCCESS`:

```sh
open src/out/Alula/alula.app
```

Leave this component development build in place: the app depends on nearby
build files and is not a distributable app bundle yet. The Chromium icon,
bundle identifier/profile location, and `Chromium Safe Storage` identity are
still upstream values. Rebuilds may prompt for Keychain access.

## Make and preserve changes

Edit Chromium normally in `src`, build/test, then commit only the intended
source changes there:

```sh
git -C src status
git -C src add path/to/changed/file
git -C src commit -m "Describe the browser change"
python3 scripts/export_patches.py
python3 scripts/apply_patches.py
git diff
git add patches chromium.lock.json
git commit -m "Update alula Chromium patch series"
git push
```

New alula-owned components can live directly in `alula/`; integration patches
will connect them to the Chromium build as those components are implemented.
Keep `config/args.gn` synchronized if intentionally changing build settings.
The allowlist `.gitignore` deliberately excludes unknown root-level files;
update it explicitly when adding a new project-owned directory.

## Chromium updates and distribution

`chromium.lock.json` pins a reproducible snapshot, not automatic security
updates. For each new stable version, save/export local work, update the pin,
sync matching dependencies, adapt/reapply patches, rebuild, and retest. Both
patch repos and full forks need conflict resolution as upstream changes.
Never overwrite a working checkout as a shortcut for updating it.

Sharing with friends needs a standalone release build, packaging, and suitable
signing/notarization. A Swift bridge is not required for sharing; it is a
separate future UI architecture decision. No binary installer, auto-update
system, CI browser build, or Swift bridge is supplied by this initial repo.

## Upstream license

Chromium-derived changes retain upstream copyright and licensing; see
`LICENSE.chromium`. Chromium dependencies have their own licenses in the local
checkout. This repository does not select a new license for original alula
code or redistribute compiled Chromium dependencies.
