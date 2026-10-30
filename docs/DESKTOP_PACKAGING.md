# Desktop packaging

Project Moah's supported user experience is a desktop window. Each package carries the React assets, Python API, migrations, and SQLite support together. Opening the application starts its local service automatically; running the app never requires a terminal or separate browser. There are three packages: a Windows installer, a `.deb` for Debian and Ubuntu, and a Flatpak for Fedora, Bazzite and every other Linux. There is no `.rpm`: Fedora users get the Flatpak.

## Install and launch

| Platform | Package | Open the app |
| --- | --- | --- |
| Windows 10 and 11 (x64) | `ProjectMoah-Setup-x64.exe` | Run the installer, then choose **Project Moah** in the Start menu. It is not code-signed yet, so SmartScreen asks once (**More info**, **Run anyway**). |
| Debian 12+, Ubuntu 22.04+ (x86-64) | `ProjectMoah-amd64.deb` | `sudo apt install ./ProjectMoah-amd64.deb`, then choose **Project Moah** in the application menu. |
| Fedora, Bazzite, any Linux with Flatpak (x86-64) | `ProjectMoah-x86_64.flatpak` | Open the bundle in a Flatpak-capable software center, select **Install**, then choose **Project Moah** in the application menu. |

File names carry no version number, so the README can link straight to the newest release (`releases/latest/download/<file>`); the release title says the version. There is no portable Windows `.exe`: it unpacks itself to a temporary folder on every start, so the path agents use to start the MCP server would stop working whenever the app is closed.

The app knows which package it came from (`installKind()` in `desktop/main.cjs` for the window, `agent_launch()` in `backend/app/services/system.py` for agents). Help pages and setup commands use that, so a Windows user never sees Flatpak steps. Help text marks system-specific parts with `{{only flatpak deb}}` … `{{end}}`.

The Flatpak is one downloadable application bundle, but the Flatpak runtime is a separate dependency. The software center may download that runtime when installing the bundle. A runtime already present can be reused. [Flatpak's single-file bundle documentation](https://docs.flatpak.org/en/latest/single-file-bundles.html) explains this limitation. No terminal is needed to launch the installed app.

Build artifacts are placed under `desktop/dist/`; the Linux bundle is `desktop/dist/ProjectMoah-x86_64.flatpak`. The desktop build workflow can also upload an artifact ZIP. Generated bundles are ignored by source control. The release identity currently uses `io.github.projectbrain.ProjectBrain` as its local Flatpak app ID; a public store submission must confirm ownership of the ID before publication.

## Local data

The database persists outside the installed program:

| Platform | Default database file |
| --- | --- |
| Linux Flatpak | `~/.var/app/io.github.projectbrain.ProjectBrain/data/project-brain/project-brain.db` |
| Windows | `%LOCALAPPDATA%\project-brain\project-brain.db` |
| Linux `.deb` and source development | `${XDG_DATA_HOME:-~/.local/share}/project-brain/project-brain.db` |

Close Project Moah before copying the database file for a backup. Removing or replacing the executable does not erase this per-user database. A Flatpak uninstall can offer a separate option to delete app data; leave that option unselected if the records should remain.

## Agent command per package

| Package | What agents run |
| --- | --- |
| Flatpak | `flatpak run --command=project-moah-mcp io.github.projectbrain.ProjectBrain` |
| `.deb` | `project-moah-mcp` (installed as `/usr/bin/project-moah-mcp`, a two-line wrapper around the bundled backend) |
| Windows | the bundled `resources\bin\project-brain-backend.exe --mcp`, with its full installed path |

## Staying offline

The app never goes online, and no package has automatic updates (`"publish": null` in `desktop/package.json`). Chromium would download spelling dictionaries from Google on Linux, so spell checking is off on Linux; Windows uses the system's own checker. The build workflow records Chromium's network log while it opens the installed app and fails if any address is not this computer.

The Flatpak has no broad access to the host filesystem and no network permission. Its window and backend talk over loopback inside the sandbox. A repository folder is shared with the app by choosing it with **Choose folder**, which uses the system file chooser and grants access to just that folder. The bundle includes Git (built from the official 2.52.0 source, checksum pinned in the manifest) because the runtime has none. Agents start the local MCP server with `flatpak run --command=project-moah-mcp io.github.projectbrain.ProjectBrain --agent <name> --project <slug>`, which shares the app's data and needs no network. A path typed by hand into a sandboxed app is not visible to it unless it was chosen through the chooser. [Flatpak sandbox permissions](https://docs.flatpak.org/en/latest/sandbox-permissions.html) document the data location and access rules.

## Build from source

The commands in this section are for people making packages. Package users only install and launch from the desktop UI. Build the Python sidecar on each target operating system; [PyInstaller cannot cross-compile it](https://pyinstaller.org/en/latest/). The Python script writes `desktop/bin/project-brain-backend` on Linux or `desktop/bin/project-brain-backend.exe` on Windows. Electron then includes that binary in the package. Build the frontend first: PyInstaller embeds the Vite output in the backend executable, and the sidecar script rejects frontend output older than its source.

### Linux (Flatpak)

Use Node.js/npm, `flatpak`, and either a host `flatpak-builder` or the `org.flatpak.Builder` Flatpak. Install the Flatpak 25.08 runtime and SDK before the build. Build the Python sidecar inside the matching SDK so it links against libraries available in the installed Flatpak. The local build environment needs access to Flathub for the SDK and to GitHub for the pinned Zypak source.

```bash
flatpak remote-add --if-not-exists --user flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install --user flathub org.freedesktop.Platform//25.08 org.freedesktop.Sdk//25.08 org.flatpak.Builder
npm ci --prefix frontend
npm run build --prefix frontend
flatpak run --share=network --filesystem="$PWD" --cwd="$PWD" --command=sh org.freedesktop.Sdk//25.08 -c '
  python3 -m venv .venv-flatpak
  .venv-flatpak/bin/python -m pip install -e ./backend pyinstaller
  .venv-flatpak/bin/python scripts/build-backend-sidecar.py
'
npm ci --prefix desktop
npm run build:linux --prefix desktop
```

The Linux target is `desktop/dist/ProjectMoah-x86_64.flatpak`. The build stages an unpacked Electron app, compiles a pinned [Zypak](https://github.com/refi64/zypak) sandbox helper in the Flatpak SDK, and exports a single-file bundle. The installed app needs the declared Flatpak 25.08 runtime; it does not need a system Electron, Python, or Node.js installation. See [Flatpak's Electron guide](https://docs.flatpak.org/en/latest/electron.html) for the sandbox model.

### Debian and Ubuntu (.deb)

Build on the oldest system the package should run on. The sidecar links against the build machine's C library (glibc), and one newer than the user's can stop it from starting: Ubuntu 24.04 has glibc 2.39, Debian 12 has 2.36. The workflow builds on Ubuntu 22.04 (glibc 2.35) and then checks the package in a Debian 12 container.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ./backend pyinstaller
npm ci --prefix frontend
npm run build --prefix frontend
.venv/bin/python scripts/build-backend-sidecar.py
npm ci --prefix desktop
npm run build:deb --prefix desktop
```

The package is `desktop/dist/ProjectMoah-amd64.deb`. It installs the app to `/opt/Project Moah/`, adds `/usr/bin/project-moah-mcp` for agents (from `desktop/linux/project-moah-mcp`), and recommends `git`.

### Windows

Run this on Windows with Python 3.12+, Node.js/npm, and the platform's build prerequisites. Use PowerShell from the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .\backend pyinstaller
npm ci --prefix frontend
npm run build --prefix frontend
.\.venv\Scripts\python.exe scripts\build-backend-sidecar.py
npm ci --prefix desktop
npm run build:windows --prefix desktop
```

The Windows installer appears in `desktop/dist/`. Building the Windows Python binary on a Windows runner is required even if Electron's own packaging tools can target another operating system.

## Build workflow and verification

The [desktop workflow](../.github/workflows/desktop.yml) builds the Flatpak, the `.deb` and the Windows installer in separate jobs. Each job builds the frontend and its own native Python sidecar and runs its package command. The `.deb` and Windows jobs then install what they built and check it:

- `scripts/check-agent-launch.py` runs the installed agent command: the session brief, an MCP handshake, and that `brain_context_pack` is offered. The `.deb` is also installed and checked this way in a clean Debian 12 container.
- `scripts/check-desktop-window.cjs` opens the installed app, checks its window and that it knows how it was installed, opens Help, fails if a non-Flatpak install shows Flatpak steps, and fails if Chromium's network log shows any address outside this computer. Screenshots and the network log are uploaded with the run.

A version tag publishes all three packages to a GitHub Release, only when every job passed. These checks cover start-up and the agent connection; the hand check below still applies before calling a release verified.

The desktop acceptance check is: open the package through its launcher; create and switch projects; archive and restore one; close and reopen the app; confirm records persist and the backend process stops when the window exits. Keep a startup failure in the desktop window with an actionable message instead of exposing a terminal. The Flatpak launcher (`desktop/flatpak/project-brain.sh`) removes Chromium's stale single-instance lock files when no other instance holds its per-app lock, so a crash or forced stop cannot block the next launch.
