# Repository merge

This repository absorbed the separate `t560-music-assistant-panel` repository.
It now holds the Home Assistant integration and both of its clients.

## Why the layout looks like this

The three components share one thing: the entity and service contract in
[CONTRACT.md](CONTRACT.md). Before the merge, a contract change meant two
repositories, two pull requests, and no way to see whether the clients had
caught up. Now a contract change and every consumer of it land in one commit.

## Frozen paths

These paths are baked into installations that already exist. **Do not move
them, and do not "tidy" them into `clients/`:**

| Path | Why it cannot move |
| --- | --- |
| `custom_components/media_controller/` | HACS resolves the integration by this path. |
| `firmware/media-controller.yaml` | Named in the `packages:` block of every flashed device. |
| `firmware/assets/` | Fetched at compile time through `asset_base_url`, a raw GitHub URL. |
| `hacs.json` | Must stay at the repository root. |

The tablet panel had no such constraint — it is installed over SSH from a local
checkout — so it is the component that moved, into `clients/t560/`.

The repository rename from `music-assistant-esp32s34848s040-controller` to
`ha-media-controller` already happened. GitHub redirects the old URLs, and
tracked files were updated to the new name in commit `984c27d`. Devices pinned
to an old `ref` keep working through the redirect; new documentation always
uses the new name.

## Current state of this working tree

The panel files are present in `clients/t560/` but **nothing has been
committed**. Choose one of the two procedures below.

### Option A — history-preserving import (recommended)

The panel carries the whole TB-* ticket history. To keep it, discard the plain
copy and import with `git subtree` instead:

```bash
git -C /d/Sources/ha-media-controller rm -r --cached clients/t560 2>/dev/null || true
rm -rf /d/Sources/ha-media-controller/clients/t560
cd /d/Sources/ha-media-controller
git subtree add --prefix=clients/t560 https://github.com/VahaC/t560-music-assistant-panel.git main
```

`git subtree add` creates a commit. Afterwards re-apply the five adjustments
that the plain copy already contains:

1. `clients/t560/.gitignore` — add `t560-panel`, `__pycache__/`, `*.py[cod]`,
   `*.d`.
2. `git rm --cached clients/t560/t560-panel` — the compiled ARMv7 binary was
   tracked and must not be.
3. `git rm -r --cached clients/t560/scripts/__pycache__
   clients/t560/tests/__pycache__` — tracked `.pyc` files.
4. `clients/t560/packaging/APKBUILD` — `url=` points at this repository.
5. `clients/t560/README.md` and `clients/t560/docs/BUILD_AND_INSTALL.md` —
   cross-repository links became relative links, and the Windows source path
   became `D:\Sources\ha-media-controller\clients\t560`.

### Option B — plain copy

Keep what is already in the working tree. The panel history stays in the old
repository, which is then archived rather than deleted, so the TB-* commits
remain readable.

```bash
cd /d/Sources/ha-media-controller
git add .
git status
```

Review `git status` before committing: the compiled binary and `__pycache__`
directories were deliberately left out of the copy and must stay out.

## After the merge

1. Archive `VahaC/t560-music-assistant-panel` on GitHub — do not delete it.
   Put a line at the top of its README pointing at
   `https://github.com/VahaC/ha-media-controller`.
2. Update the GitHub description and topics of this repository: it is no longer
   only an ESP32 project. Suggested topics: `home-assistant`, `music-assistant`,
   `hacs`, `esphome`, `esp32-s3`, `lvgl`, `gtk3`, `postmarketos`.
3. Check that HACS still resolves the integration after the first push. The
   extra top-level directories do not affect it — HACS downloads only
   `custom_components/media_controller` — but confirm once.
4. Run `esphome config firmware/media-controller.yaml` once against the pushed
   `main` to prove `packages:` and `asset_base_url` still resolve.
5. Update the vahac.com write-up link if it names the old repository.
6. Cut the first tags of the new scheme: `integration-v0.7.2`,
   `firmware-v0.7.1`, `panel-v0.1.0`. The integration is at `0.7.2` because the
   brand images changed; the firmware is untouched at `0.7.1`.
7. Optional: submit `custom_components/media_controller/brand/` unchanged to the
   legacy `custom_integrations/media_controller/` folder of
   <https://github.com/home-assistant/brands>. Home Assistant 2026.3+ already
   serves the local copies, but the HACS store listing still reads the CDN. See
   the brand images section of [INTEGRATION.md](INTEGRATION.md).

## Deliberately not done

- **The `t560-` prefix was not renamed.** Binaries, scripts, the desktop entry,
  the icon name, the config directory, and the deployment scripts all use it,
  and it is installed under that name on a live tablet. Renaming it to something
  hardware-neutral is worth doing when a second panel target appears, not during
  a move.
- **The ESP32 firmware was not moved to `clients/esp32/`.** It would be
  symmetric and it would break every device in the field. See the frozen paths
  above.
- **The two test suites were not merged.** `tests/` is the integration's;
  `clients/t560/tests/` is the panel's. They run on different toolchains.
