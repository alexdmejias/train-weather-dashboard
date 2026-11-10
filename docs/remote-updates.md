# Updating the Pi remotely with CI

**Goal:** push to GitHub, CI tests the change, and the dashboard on the wall
updates itself, with no laptop, `rsync` or `ssh` involved.

## Constraints that shape the choice

| Constraint | Consequence |
|---|---|
| **Small Pi** (Pi 3, 1 GB; originally a Pi Zero W) | A Pi 3 *could* host GitHub's self-hosted Actions runner (a Zero W can't — ARMv6), but it would eat the RAM and CPU the animations use, and it gives CI a way into the home network. Docker images and balena-style OS agents are heavy for it too. |
| **Behind home NAT**, no public IP | CI can't reach the Pi unless it gets a tunnel/VPN. Anything the Pi *pulls* works with no extra setup. |
| **Repo is public** | The Pi can `git fetch` anonymously, with no deploy key or token on the device. |
| **Plain Python, no build step** | The "artifact" is just the source tree. `git` is the simplest transport. |
| **Already a systemd service** with `Restart=always` | Restarting and checking health is easy. |
| `config.toml` is **gitignored**, caches live in `~/.cache` | `git reset --hard` never loses local settings. |
| CI can test headlessly | `pytest` plus `tools/render.py` (SDL dummy driver) renders every scenario, which catches import errors and layout crashes before they reach the screen. |

## Options considered

### 1. Pull: Pi polls a CI-gated branch ✅ recommended
CI runs tests on every push. When the default branch is green, CI moves a
`deploy` branch to that commit. A systemd timer on the Pi runs `git fetch`
every 5 min and, if `deploy` moved, checks it out, restarts the service,
health-checks it, and **rolls back automatically** if it crash-loops.

- **+** No inbound access, no secrets in CI or on the Pi, no extra services.
- **+** Works across reboots and flaky Wi-Fi: it simply catches up on the next tick.
- **+** Rollback is `git revert` (or re-run the workflow on an older commit).
- **−** Up to ~5 min latency. Polling costs one tiny HTTPS request every 5 min.

### 2. Push: CI SSHes in over Tailscale
Install Tailscale on the Pi. The workflow uses `tailscale/github-action` to
join the tailnet as an ephemeral node, then runs the same `rsync` + restart
that `sync.sh` does.

- **+** Instant, and the run shows deploy success or failure in GitHub.
- **−** Needs secrets in GitHub (Tailscale OAuth client and an SSH private key)
  that grant shell access to a device on your home network.
- **−** Tailscale on a small Pi costs noticeable CPU/RAM. If the Pi is offline
  when CI runs, the deploy just fails, and nothing retries.
- Worth it if you **already use Tailscale**. It also gives you remote `ssh`
  and screenshots from anywhere.

### 3. Pull GitHub Release tarballs
CI builds a tarball and attaches it to a Release. The Pi downloads the latest
one into `releases/<ver>/` and swaps a `current` symlink.

- **+** Atomic swap, and the Pi doesn't need git.
- **−** More moving parts (versioning, asset upload, cleanup) for no real gain,
  since there is nothing to build.

### 4. Self-hosted runner on the Pi ❌
Not possible: the runner doesn't support ARMv6.

### 5. Fleet tools (balena, Mender, Ansible-pull) ❌ overkill
balena replaces the OS and Mender needs a server, both for a single device.
`ansible-pull` is the same idea as option 1 but needs Ansible on a 512 MB Pi.

## What's implemented (option 1)

```
.github/workflows/ci.yml        test (py3.11 + 3.13) → render screenshots → promote to `deploy`
deploy/update.sh                fetch `deploy` → reset → (reinstall) → restart → health check / rollback
deploy/dashboard-update.service oneshot that runs update.sh as the Pi user
deploy/dashboard-update.timer   every 5 min (+2 min after boot, ±30 s jitter)
deploy/install.sh --auto-update installs git + the timer
```

```
 push ──► CI: pytest + render ──green──► deploy branch ◄──git fetch / 5 min── Pi
           (PRs: test only)                                 │
                                                     reset → restart → 35 s check
                                                            └─ crash-loop? roll back,
                                                               skip that commit
```

**Details**

- **What gets deployed:** pushes to the repo's *default branch* (currently
  `claude/scaffold-dashboard`), once tests pass. *Actions → CI → Run workflow*
  on any branch tests it and deploys it. Use this to try a branch on the real
  screen, or to roll back to an older commit.
- **Health check:** after a restart, the service must still be `active`
  with the **same PID** 30 s later. `Restart=always` would otherwise mask a
  crash loop. If the check fails, `update.sh` resets to the previous commit,
  restarts, and records the bad SHA in `.git/update-bad-rev` so it isn't
  retried every 5 min. The next new commit on `deploy` is tried normally.
- **Dependencies:** if `requirements.txt`, `install.sh` or a unit file
  changed, `update.sh` re-runs `install.sh` (apt and pip) before restarting.
- **Self-update safety:** `update.sh` wraps everything in `main()`, so bash
  has parsed the whole file before `git reset` overwrites it.
- **Permissions:** the timer runs as the Pi user with no terminal, so
  `sudo` must work **without a password**. Raspberry Pi OS sets this up for
  its default user, but not always for users you create yourself, or when
  Imager is told to require a password. Check with `sudo -k; sudo -n true && echo ok`.
  If it isn't set up, choose one:

  ```bash
  # Full (same as the default Pi user). Needed for updates that change
  # requirements.txt, install.sh or a unit file, since those re-run install.sh.
  echo "$USER ALL=(ALL) NOPASSWD: ALL" | sudo tee /etc/sudoers.d/010_$USER-nopasswd
  sudo chmod 440 /etc/sudoers.d/010_$USER-nopasswd

  # Narrow: only lets the updater restart the dashboard. Updates that need
  # install.sh wait (and log why) until you run it by hand.
  echo "$USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart dashboard" \
    | sudo tee /etc/sudoers.d/020_dashboard-restart
  sudo chmod 440 /etc/sudoers.d/020_dashboard-restart
  ```

  `update.sh` checks this **before** checking out a new commit. If sudo would
  prompt, it leaves the old commit in place and logs why, then tries again on
  the next tick. `install.sh --auto-update` warns at the end if it's missing.
  A restart that fails, or that leaves the same PID running, counts as a
  failed health check, so the update is rolled back.
- The workflow only needs `contents: write` (to move `deploy`). No secrets.
- **Is the screen up to date?** The bottom-left corner shows the running
  build (`Build 214` = the number of commits, so it only goes up) with a dot:
  green = the newest commit on `deploy`, blue = a newer one is installing,
  amber = the newer one failed its health check and was rolled back. The
  **Settings** page header spells it out: build, status, commit, when it was
  built and when the updater last checked. It compares `HEAD` with `.git/FETCH_HEAD`, which `update.sh` refreshes every
  5 min, so it makes no network requests of its own.

### Switching an existing Pi over

The README's setup copies files with `rsync --exclude .git`, so the Pi has no
repo. Make it a clone once (your `config.toml` and `settings.json` are kept):

```bash
ssh pi@dashboard.local
```

```bash
cd ~ && git clone -b deploy https://github.com/alexdmejias/train-weather-dashboard.git twd-new \
  && cp train-weather-dashboard/{config.toml,settings.json} twd-new/ 2>/dev/null; \
  mv train-weather-dashboard train-weather-dashboard.old && mv twd-new train-weather-dashboard
```

```bash
cd ~/train-weather-dashboard && bash deploy/install.sh --auto-update
```

If it ends with a ⚠ about passwordless sudo, follow the **Permissions** note
above, or updates will download but never restart the dashboard.

The `deploy` branch exists after the first green CI run on the default branch.

**Useful commands on the Pi**

```bash
journalctl -u dashboard-update -n 50          # what the updater did
sudo systemctl start dashboard-update         # check now instead of waiting
systemctl list-timers dashboard-update.timer  # next run
sudo systemctl disable --now dashboard-update.timer   # pause auto-updates
```

### Caveats / follow-ups

- `sync.sh` and auto-update both write to the same folder. While iterating
  live with `sync.sh`, pause the timer, or the next tick will `reset --hard`
  your uncommitted edits back to `deploy`.
- The health check only catches crashes. It doesn't catch "runs but draws the
  wrong thing". The CI screenshot artifact is there for a visual check before
  merging.
- Optional upgrade: the updater could report its status back (for example,
  a heartbeat to healthchecks.io or ntfy.sh) so you'd know if the Pi stopped
  updating.
