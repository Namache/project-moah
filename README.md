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

- Everything stays on your computer in one local database. No account, no cloud, no telemetry.
- The app has no network permission. Agents talk to it through a local connection.
- It reads your repository's file names, Git status and commit messages, and never changes your code.

## Install

Download the file for your system from the [latest release](../../releases/latest).

### Linux (Fedora, Debian, Ubuntu and others), with Flatpak

1. Make sure Flatpak is installed. Fedora has it already. On Debian or Ubuntu:
   ```bash
   sudo apt install flatpak
   ```
2. Add Flathub, where the app's runtime comes from:
   ```bash
   flatpak remote-add --if-not-exists --user flathub https://dl.flathub.org/repo/flathub.flatpakrepo
   ```
3. Install the downloaded bundle, then open **Project Moah** from your app menu:
   ```bash
   flatpak install --user ProjectMoah-*.flatpak
   ```

Or open the `.flatpak` file in your software center and choose **Install**.

### Debian and Ubuntu, without Flatpak

Coming soon: a `.deb` package.

### Fedora, without Flatpak

Coming soon: an `.rpm` package.

### Windows

Coming soon: an installer for Windows 10 and 11.

## Connect your AI agent

Open the app and go to **Help → Connect Claude Code** (or **Connect Codex**). Copy the command shown there into a terminal once. From then on, every session can use Project Moah. No API key is needed.

## Your data

Your database is in `~/.var/app/io.github.projectbrain.ProjectBrain/data/project-brain/` (Flatpak). Make a copy any time with **Settings → Export Project Moah backup**.

## License

[MIT](LICENSE)
