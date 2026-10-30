# Project Moah

**A shared memory and task board for your AI coding agents, that lives on your computer.**

Claude Code and Codex forget everything between sessions. Project Moah gives them one place to read and write what matters: your tasks, decisions, rules, known issues and where you left off. You see and steer all of it in a desktop app. *Moah* means "brain" in Hebrew.

![Project Moah home screen](docs/screenshot-home.png)

## What it does

- **Tasks** on a board or a list, with milestones, requirements and a "current focus" your agents start from.
- **Memory**: decisions, rules, facts, ideas, known issues, notes and warnings. Lock what agents must not change.
- **Context packs**: each agent session gets a short, ranked summary of what it needs, instead of your whole history.
- **Inbox**: agents suggest changes to locked things; nothing changes until you accept.
- **Checkpoints and handoffs**: pick up where the last session stopped, with any agent.
- **Brain view**: see how your memory links together, and what agents never reach.

![Task board](docs/screenshot-board.png)

## Private by design

- Everything stays on your computer in one local database. No account, no cloud, no telemetry, no automatic updates.
- The app never goes online. Agents talk to it through a local connection. The Flatpak version has no network permission at all.
- It reads your repository's file names, Git status and commit messages, and never changes your code.

## Install

Download the one file for your system from the [latest release](../../releases/latest):

| Your system | File |
| --- | --- |
| Windows 10 or 11 | `ProjectMoah-Setup-<version>-x64.exe` |
| Debian 12 or newer, Ubuntu 22.04 or newer, Linux Mint and similar | `ProjectMoah-<version>-amd64.deb` |
| Fedora, Bazzite and any other Linux with Flatpak | `ProjectMoah-<version>-x86_64.flatpak` |

### Windows

1. Run `ProjectMoah-Setup-<version>-x64.exe` and follow the installer.
2. Windows may say "Windows protected your PC", because the installer is not signed yet. Choose **More info**, then **Run anyway**.
3. Open **Project Moah** from the Start menu.

To show Git details for your repositories, also install [Git for Windows](https://git-scm.com/download/win). Everything else works without it.

### Debian and Ubuntu

Open a terminal in the folder you downloaded to (usually `cd ~/Downloads`), then run:

```bash
sudo apt install ./ProjectMoah-*.deb
```

Open **Project Moah** from your app menu. To remove it later: `sudo apt remove project-moah`.

### Fedora, Bazzite and other Linux, with Flatpak

Fedora and Bazzite already have Flatpak. On other systems, install it first from your package manager.

1. Add Flathub, where the app's runtime comes from:
   ```bash
   flatpak remote-add --if-not-exists --user flathub https://dl.flathub.org/repo/flathub.flatpakrepo
   ```
2. Install the downloaded bundle, then open **Project Moah** from your app menu:
   ```bash
   flatpak install --user ProjectMoah-*.flatpak
   ```

Or open the `.flatpak` file in your software center and choose **Install**.

## Connect your AI agent

Open the app and go to **Help → Connect Claude Code** (or **Connect Codex**). The commands there are made for the way you installed the app, so copy them as they are, once. From then on, every session can use Project Moah. No API key is needed.

## Your data

Your database stays in one folder, and uninstalling the app leaves it there:

| Installed with | Folder |
| --- | --- |
| Windows installer | `%LOCALAPPDATA%\project-brain\` |
| `.deb` | `~/.local/share/project-brain/` |
| Flatpak | `~/.var/app/io.github.projectbrain.ProjectBrain/data/project-brain/` |

**Settings → Data** shows the exact place. Make a copy any time with **Export Project Moah backup** there.

## License

[MIT](LICENSE)
