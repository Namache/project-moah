"""The once-a-day update check, done by the agent rather than by Project Moah.

Project Moah never goes online. Instead, the first brief (or context pack) of the day tells the
agent which version is installed and asks it to look up the latest release with its own tools,
then ask the person before anything is updated. Turned off in Settings, it is never added.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.models.app_setting import AppSetting
from app.services.settings import get_agent_settings
from app.services.system import APP_VERSION, FLATPAK_ID, agent_launch

LAST_CHECK = "update_check_last_day"
REPOSITORY = "Namache/project-moah"
OFFLINE = "Couldn't check for Project Moah updates, the machine is offline."
UNREACHABLE = "Couldn't check for Project Moah updates."


RESTARTED = "Project Moah restarted after the update and ready to use."
DOWNLOAD = f"https://github.com/{REPOSITORY}/releases/latest/download"
FLATPAK_FILE = "ProjectMoah-x86_64.flatpak"
# How each install updates and comes back on its own, so the person never has to reopen the app.
UPDATE_STEPS = {
    "windows": f"""\
Download {DOWNLOAD}/ProjectMoah-Setup-x64.exe to a temporary folder and run it with
  `/S --force-run`, which closes the app, installs and starts it again. If the app is under
  Program Files, add `/allusers` and run it elevated (PowerShell: `Start-Process <file>
  -ArgumentList '/S','/allusers','--force-run' -Verb RunAs -Wait`); they approve one prompt.""",
    "deb": f"""\
In a terminal: `cd /tmp && wget -O ProjectMoah-amd64.deb {DOWNLOAD}/ProjectMoah-amd64.deb &&
  sudo apt install ./ProjectMoah-amd64.deb`, then restart the app:
  `pkill -f project-brain-desktop; sleep 3; nohup "/opt/Project Moah/project-brain-desktop"
  >/dev/null 2>&1 &`.""",
    "flatpak": f"""\
In a terminal: `cd /tmp && curl -LO {DOWNLOAD}/{FLATPAK_FILE} && flatpak install --user
  --or-update {FLATPAK_FILE}`, then restart the app: `flatpak kill {FLATPAK_ID}; nohup flatpak
  run {FLATPAK_ID} >/dev/null 2>&1 &`.""",
}


def update_steps(install: str) -> str:
    """What to do after the person's yes, for this install."""
    steps = UPDATE_STEPS.get(install)
    if steps is None:
        return "Update it as the release page says for this system, then reopen the app."
    return f"""\
After their yes: {steps}
  When the app is running again, tell the person exactly "{RESTARTED}"
  If it did not come back, say so instead. Your Project Moah tools need a restart of your agent."""


def instructions(version: str = APP_VERSION, install: str | None = None) -> str:
    steps = update_steps(install or agent_launch()["install"])
    return f"""\
UPDATE CHECK (once a day; the person can turn it off in Settings > Agents)
Installed Project Moah version: {version}. Project Moah itself never goes online, so you check:
look up the latest release of github.com/{REPOSITORY} with your own tools, for example
`gh api repos/{REPOSITORY}/releases/latest` or https://api.github.com/repos/{REPOSITORY}/releases/latest
(compare its tag_name, without the leading v, to {version}).
- Newer: tell the person in one sentence (both versions) and ask whether they want to update.
  Update nothing without their yes.
  {steps}
- Same or older: say nothing about it.
- No network: say exactly "{OFFLINE}"
- Any other failure (not found, no permission): say exactly "{UNREACHABLE}"
Then carry on with the person's request. Do not check again in this session."""


def take_daily_check(session: Session, today: Callable[[], date] = date.today) -> str | None:
    """The update check text, once per local calendar day, or None (already given, or off).

    Giving it claims the day, so a second session the same day does not ask again, even if the
    first agent could not reach GitHub."""
    if not get_agent_settings(session).update_check_enabled:
        return None
    day = today().isoformat()
    row = session.get(AppSetting, LAST_CHECK) or AppSetting(key=LAST_CHECK)
    if row.value == day:
        return None
    row.value, row.updated_at = day, datetime.now(UTC)
    session.add(row)
    session.commit()
    return instructions()
