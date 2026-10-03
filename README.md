# sliderCMS

`sliderCMS` is a single Django project for managing and displaying slide-based digital signage content.

It includes:
- authenticated admin and standard-user workflows
- slide upload and library management
- slideshow playback for images, video, rich text, HTML, YouTube, Google Slides, weather, calendar, and Dateline content
- Raspberry Pi kiosk launch support
- site migration import/export

## Project Layout

- `sliderCMS/` – Django project settings, URLs, WSGI/ASGI, and Celery bootstrap
- `posts/` – slide models, media processing, slideshow views, generated-slide settings, weather, calendar, migration tools, and tests
- `accounts/` – authentication and account-management views/forms
- `templates/` – shared admin UI plus slideshow and generated-slide templates
- `data/` – private runtime files on new installs (database, media, logs, backups)
- `install.sh` – local setup for macOS or Debian/Ubuntu
- `launch_kiosk.sh` – compatibility wrapper for the main kiosk start script
- `scripts/deploy.sh` – rsync-based deploy helper for pushing the project to the remote server
- `scripts/start_slidercms.sh` – starts Redis, Django, Celery, and the kiosk session
- `scripts/stop_slidercms.sh` – stops the local kiosk/runtime processes
- `scripts/build_and_run.sh` – lightweight local background launcher used in this workspace

## Mobile Transit

The transit display and paused preview include a QR link to `/transit/mobile/`.
The phone view lets visitors select active routes for the map, bus markers, stop
arrivals, and incoming-campus ETAs. Choices are stored in that browser only and
do not change the shared slideshow configuration. Map animation and slideshow
navigation are disabled in the mobile view.

The QR destination defaults to `http://pi-serv.rex-powan.ts.net/transit/mobile/`.
Change **Settings > Site Settings > Public Base URL** to change the destination
without restarting Django. It is stored in the database and included in site
exports. Phones must be able to reach that host (including Tailscale access for
the default hostname).

`posts.qr_codes.qr_variants(text)` generates reusable PNG variants locally, with
integer-pixel modules and a four-module quiet zone. Variants cover compact and
desktop slots across common display densities up to 8K. The browser chooses the
smallest sufficient raster, never upscales, and aligns modules to device pixels.
Generation uses a bounded memory cache, and URL revisions invalidate old QR
images when the destination changes.
After deploying this feature, install the updated requirements to add `qrcode`:

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python manage.py migrate
```

## Rich Text QR Codes

The **Add Slide > Rich Text** toolbar includes an Insert QR Code button. It accepts
text or a URL and small, medium, or large sizing. Slides store portable QR
descriptors, not image uploads; the editor and display generate density-aware
PNGs locally using the shared QR helper. Existing rich text remains sanitized.

## Local Setup

Superusers can review **Settings > Activity Log** for timestamped operator actions
and outcomes, including slide changes, settings, account actions, and site
imports/exports. Recording starts after migration `0044`; previous actions cannot
be reconstructed. History stays local to the installation and is not replaced by
site imports. Passwords, reset tokens, QR contents, and automatic display polling
are excluded. The table is paginated to keep Settings fast on a Raspberry Pi.

```bash
./install.sh --migrate
```

If you prefer the current fallback Python environment used in this workspace, the active backup virtualenv is:

```bash
.venv311
```

## Run Locally

```bash
./scripts/start_slidercms.sh
```

Stop the kiosk/runtime stack:

```bash
./scripts/stop_slidercms.sh
```

For a lighter local-only dev launch:

```bash
./scripts/build_and_run.sh
```

## Deploy

### First Install From GitHub

Use a **public repository** containing `manage.py` at its root. Replace `OWNER/REPO`
below with your own repository; the old remote is not automatically trusted for updates.

```bash
git clone https://github.com/OWNER/REPO.git sliderCMS
cd sliderCMS
./install.sh --repository OWNER/REPO --branch main --enable-updates
./scripts/start_slidercms.sh
```

The installer installs system/Python dependencies, creates a private `.env`, runs
all database migrations, and prompts interactively for the first administrator's
username and password. The password is hashed by Django and never placed in `.env`.
Rerunning it preserves existing administrator credentials and content. For an
additional administrator, pass `--createsuperuser`. For setup without installing
dependencies again, run `.venv/bin/python manage.py setup_site`.

On Raspberry Pi OS Lite, the installer also sets up Chromium, X11/openbox, Redis
and CEC tools. Launch the kiosk locally on tty1; SSH starts the backend only when
no local display is running. macOS developers can use `--without-kiosk-stack`.

### Publish Code Without Private Content

`.gitignore` excludes databases and SQLite sidecars, uploads/renditions, `.env`,
local signing keys, Dateline cache, logs, backups, site exports, virtualenvs and
compiled Python. Source static assets and Django migrations remain publishable.
Run `.venv/bin/python scripts/check_publish.py` before publishing; CI also checks
the current tracked file list. This is an artifact check, not a general secret scanner.

**Important:** the old Git history contains previously tracked database/media and
an old hard-coded Django signing key. Untracking them does not erase history.
Do not push that history into a new public repository. Export a clean source tree:

```bash
.venv/bin/python scripts/export_source.py /tmp/sliderCMS-source
```

Initialize a new repository in that exported directory and publish it with fresh
history. Existing public history needs a separate reviewed history cleanup.
New installations generate a unique private `.secret_key` (or use
`SLIDERCMS_SECRET_KEY`); existing sessions will be signed out once when switching
from the old hard-coded key. Do not reuse the published key.

### Built-In Updates

After a superuser logs in, **Home** and **Settings** show Software Updates.
GitHub's public commits API is checked with a five-minute cache. The selected
branch's commit is displayed before installation; ordinary users cannot check or
install updates. Configuration lives in the server's private `.env`:

```dotenv
SLIDERCMS_UPDATE_REPOSITORY=OWNER/REPO
SLIDERCMS_UPDATE_BRANCH=main
SLIDERCMS_UPDATES_ENABLED=1
```

Only a clean Git clone launched by `scripts/start_slidercms.sh` supports one-click
installation. It refuses local changes, tracked private content, divergent history,
and a branch that changed after approval. A file lock prevents simultaneous updates.
The detached updater fetches the approved commit, stops the managed Django/Celery
processes (leaving Chromium/X11 running), backs up SQLite, performs a fast-forward,
installs Python requirements, checks Django, migrates, collects static files, then
restarts the backend on the same host/port. It never imports or replaces site media.
Only trust repository maintainers allowed to deploy code to your server.

The update creates a brief outage. Refresh the dashboard after completion. Progress,
errors, previous commit and database backups are under `data/updates/` (or
`updates/` on legacy installs). If an install/migration fails after shutdown, the
backend stays stopped rather than serving a partially migrated application.
Inspect `update.log`; fix the cause, finish migrations, and start the backend again.
To recover older code, use a separate checkout of the saved `revision.txt` and its
matching database backup; do not run old code against a partially migrated database.
Backups are retained for manual review/removal. System package changes still require
rerunning `install.sh`; the web updater never runs sudo.

### Transition From Rsync

Existing installs keep their database/media locations. New installs use `data/`;
`SLIDERCMS_DATA_DIR` can instead point to an absolute writable directory outside
the checkout. Do not change this path without transferring the existing runtime
files while services are stopped.

For the first Git-based deployment, export the old site in Settings, stop the old
server, clone the newly published source into a **new** directory, run the installer,
then restore the site archive there. Keep the old directory as a backup. The new
administrator is created during installation; site archives are not database/user
account backups. Afterwards use the built-in updater. An rsynced folder without
Git history will not be overwritten or converted automatically.

The included runtime uses Django's development server for the existing VPN/kiosk
workflow. For an Internet-facing deployment, use a production WSGI service and a
separately supervised deployment procedure; that topology is not managed by this updater.

### Legacy Rsync Helper

```bash
./scripts/deploy.sh
```

On first run it will ask for:
- SSH username
- server host

Those values are stored in `.env` as:
- `DEPLOY_SSH_USER`
- `DEPLOY_SERVER_HOST`

The SSH password is not stored and is requested on every deploy.

## Configuration

### Screen Power On Raspberry Pi 4 / Debian Bookworm

`python manage.py runserver` starts only the web server. Scheduled screen power
also requires Redis, a Celery worker, and Celery Beat. The lightweight
`scripts/build_and_run.sh` is likewise a web-only development launcher.

After deploying the updated code, stop the manually started `runserver` with
Ctrl-C. Then, from the Pi's project directory, install dependencies/migrate and
start the managed backend:

```bash
cd ~/sliderCMS
./install.sh --with-redis --without-kiosk-stack
./scripts/start_slidercms.sh --backend-only
```

In an existing desktop startup script, replace the `python manage.py runserver`
line with `./scripts/start_slidercms.sh --backend-only`. Keep your existing
display/browser setup separate, or omit `--backend-only` to use the managed kiosk.
Do not run a second manual Django/Beat instance on the same port/project.
The startup helper runs the services in the background; inspect its printed logs.
It does not configure boot-time service supervision, so retain your desktop
autostart entry. Future logins start it again. To stop the managed stack use
`./scripts/stop_slidercms.sh` (this also stops the managed browser/X11 session).

**Settings > Screen Power Schedule** shows the schedule's timezone, scheduler
heartbeat, confirmed TV power changes, and the last CEC error. Save different on
and off times and enable the schedule. Allow one minute for the first Beat tick.
The desired state is applied even after a missed scheduled minute or restart;
starting the backend during the off period may therefore put the TV in standby.
Each daily boundary is acknowledged only after the TV reports the expected state.
Failures retry after five minutes. Overnight schedules are supported. A repeated
DST hour uses its first occurrence; a skipped time moves to the first valid minute.
The default timezone is America/New_York; set `SLIDERCMS_TIME_ZONE` in `.env` and
restart the backend to change it.

Read-only diagnostics (no power-on, standby or input-switch command):

```bash
.venv/bin/python manage.py screen_power_status --query-tv
cec-client -l
ls -l /dev/cec*
id
```

On a Pi 4, libCEC can detect both HDMI connectors. Set `CEC_ADAPTER` in `.env` to
the **com port** listed for the connected display, such as `/dev/cec0` or
`/dev/cec1`; do not assume the index without checking. If several adapters are
found, the helper refuses to guess. `cec-ctl -d /dev/cec0` (from `v4l-utils`) can
show driver/physical-address information without switching power; an invalid
`f.f.f.f` physical address suggests a disconnected/unavailable HDMI link.
Restart the backend after changing CEC settings in `.env`; already running Celery
workers retain their environment until restarted.

The runtime user needs read/write permission on the selected device. If `ls -l`
shows group `video` and `id` does not include it, run `sudo usermod -aG video "$USER"`,
then log out/in or reboot and restart the backend. Use the actual device group
if different; do not chmod the device world-writable or run Django as root.
Enable CEC in the TV's settings (often named Anynet+, Simplink, Bravia Sync, etc.).
Some computer monitors, cables, splitters and adapters do not support CEC.

When ready to deliberately switch the TV, test the shared controller directly:

```bash
.venv/bin/python scripts/cec_on.py
.venv/bin/python scripts/cec_off.py
```

These commands load the same `.env` as Celery. They serialize access to the CEC
adapter, use the playback device type, bound each client invocation, detect
reported libCEC errors even with exit status zero, and query the TV to verify
power. A monitor that never answers power-status queries is reported as unconfirmed,
not falsely logged as successful. `CEC_POWER_ON_SETTLE_SECONDS` and
`CEC_POWER_OFF_SETTLE_SECONDS` can be increased for slow displays. Optional
`CEC_HDMI_PORT` selects the **TV input number**, not the Pi connector; leave it
unset to use the physical address detected from the HDMI connection. Do not
blindly copy a hard-coded HDMI-2 address from an older script.

See the [Celery periodic-task requirements](https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html)
and [Debian Bookworm CEC adapter documentation](https://manpages.debian.org/bookworm/v4l-utils/cec-ctl.1.en.html).

The project reads runtime settings from `.env` where present. Notable variables include:
- `SLIDERCMS_ALLOWED_HOSTS`
- `SLIDERCMS_CSRF_TRUSTED_ORIGINS`
- `DEPLOY_SSH_USER`
- `DEPLOY_SERVER_HOST`
- `DEPLOY_REMOTE_ROOT`

## Notes

- The active Django project name is `sliderCMS`.
- If `git status` still shows deleted legacy package paths, that is Git reporting removals that are ready to be committed, not live project files.
