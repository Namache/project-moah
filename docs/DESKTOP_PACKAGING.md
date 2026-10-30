# Desktop packaging

Project Moah's supported user experience is a desktop window. The Linux Flatpak carries the React assets, Python API, migrations, and SQLite support together. Opening the application starts its local service automatically; running the app never requires a terminal or separate browser. Windows packaging is deferred.

## Install and launch

| Platform | Package | Open the app |
| --- | --- | --- |
| Linux (x86-64), any distribution with Flatpak | `ProjectMoah-0.1.0-x86_64.flatpak` | Open the bundle in a Flatpak-capable software center, select **Install**, then choose **Project Moah** in the application menu. |
| Windows (x64, deferred) | Setup and portable `.exe` targets | Build and runtime verification remain to be done on Windows. |

The Flatpak is one downloadable application bundle, but the Flatpak runtime is a separate dependency. The software center may download that runtime when installing the bundle. A runtime already present can be reused. [Flatpak's single-file bundle documentation](https://docs.flatpak.org/en/latest/single-file-bundles.html) explains this limitation. No terminal is needed to launch the installed app.

Build artifacts are placed under `desktop/dist/`; the Linux bundle is `desktop/dist/ProjectMoah-0.1.0-x86_64.flatpak`. The desktop build workflow can also upload an artifact ZIP. Generated bundles are ignored by source control. The release identity currently uses `io.github.projectbrain.ProjectBrain` as its local Flatpak app ID; a public store submission must confirm ownership of the ID before publication.

## Local data

The database persists outside the installed program:

| Platform | Default database file |
| --- | --- |
| Linux Flatpak | `~/.var/app/io.github.projectbrain.ProjectBrain/data/project-brain/project-brain.db` |
| Windows | `%LOCALAPPDATA%\project-brain\project-brain.db` |
| Linux source development | `${XDG_DATA_HOME:-~/.local/share}/project-brain/project-brain.db` |

Close Project Moah before copying the database file for a backup. Removing or replacing the executable does not erase this per-user database. A Flatpak uninstall can offer a separate option to delete app data; leave that option unselected if the records should remain.

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

The Linux target is `desktop/dist/ProjectMoah-0.1.0-x86_64.flatpak`. The build stages an unpacked Electron app, compiles a pinned [Zypak](https://github.com/refi64/zypak) sandbox helper in the Flatpak SDK, and exports a single-file bundle. The installed app needs the declared Flatpak 25.08 runtime; it does not need a system Electron, Python, or Node.js installation. See [Flatpak's Electron guide](https://docs.flatpak.org/en/latest/electron.html) for the sandbox model.

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

Windows Setup and portable `.exe` artifacts appear in `desktop/dist/`. Building the Windows Python binary on a Windows runner is required even if Electron's own packaging tools can target another operating system.

## Build workflow and verification

The [desktop workflow](../.github/workflows/desktop.yml) runs Linux and Windows packaging in separate jobs. Each job builds the frontend and its own native Python sidecar, runs its package command, and uploads its artifacts. A successful workflow build proves that packages were produced; launching and using them in each target environment must be checked separately before calling a release verified.

The desktop acceptance check is: open the package through its launcher; create and switch projects; archive and restore one; close and reopen the app; confirm records persist and the backend process stops when the window exits. Keep a startup failure in the desktop window with an actionable message instead of exposing a terminal. The Flatpak launcher (`desktop/flatpak/project-brain.sh`) removes Chromium's stale single-instance lock files when no other instance holds its per-app lock, so a crash or forced stop cannot block the next launch.
