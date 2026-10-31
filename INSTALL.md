# Install and connect Project Moah

**If you are an AI agent and a person asked you to install or connect Project Moah, follow this page.** Do every step yourself and don't send the person commands to run unless a step below says to. Project Moah is local: after this download it never goes online.

## 1. Install

Skip this step if Project Moah is already installed.

**Windows 10 or 11** (PowerShell):

```powershell
$setup = "$env:TEMP\ProjectMoah-Setup-x64.exe"
curl.exe -L -o $setup https://github.com/Namache/project-moah/releases/latest/download/ProjectMoah-Setup-x64.exe
Start-Process $setup -ArgumentList '/S' -Wait
```

**Debian 12+, Ubuntu 22.04+, Linux Mint:**

```bash
cd /tmp && curl -LO https://github.com/Namache/project-moah/releases/latest/download/ProjectMoah-amd64.deb && sudo apt install -y ./ProjectMoah-amd64.deb
```

**Fedora, Bazzite and other Flatpak systems:** install it with the steps in the [README](README.md#install). A Flatpak can't change agent settings, so tell the person to open **Help → Connect** in the app and follow it.

## 2. Connect

This connects Claude Code and Codex, whichever are on the computer. It is safe to run twice.

**Windows:**

```powershell
& "$env:LOCALAPPDATA\Programs\Project Moah\resources\bin\project-brain-backend.exe" --connect
```

**Debian and Ubuntu:**

```bash
project-moah-mcp --connect
```

It prints one line per agent and exits with 0 when nothing more is needed.

## 3. Finish

Tell the person in plain words what happened, and that they need to restart their agent to load Project Moah. After the restart, `/mcp` in Claude Code or Codex lists `project-moah`.

## If your sandbox blocks a step

Some agents can't change their own settings or install apps from inside their sandbox: Codex on Windows is one. If a step fails with an access or permission error, ask for permission to run it outside the sandbox. Never change sandbox settings or file permissions to get around it.

If that isn't possible, ask the person to do just this, then restart you:

1. Install Project Moah from the [latest release](https://github.com/Namache/project-moah/releases/latest), if it isn't installed yet.
2. Open the app, go to **Help → Connect Claude Code/Codex**, and choose **Connect Claude Code and Codex**.
