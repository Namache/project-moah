---
title: Your data and backups
category: Core features
summary: Where your data lives and how to back it up.
keywords: backup, export, data, database, location, restore
related: troubleshooting-repository
---

Project Moah stores everything in one local database file. Nothing is uploaded anywhere.

{{only flatpak}}
The file is in `~/.var/app/io.github.projectbrain.ProjectBrain/data/project-brain/`.
{{end}}
{{only deb linux}}
The file is in `~/.local/share/project-brain/`.
{{end}}
{{only windows}}
The file is in `%LOCALAPPDATA%\project-brain\`.
{{end}}

*Settings*, under *Data*, shows where the file is and lets you export a backup. To restore, close Project Moah and replace the database file with your backup.

Removing or reinstalling the app keeps your data.
{{only flatpak}}
Only `flatpak uninstall --delete-data` removes it.
{{end}}
{{only deb linux}}
The package never touches your home folder, so `sudo apt remove project-moah` leaves it where it is.
{{end}}
{{only windows}}
Uninstalling from *Settings > Apps* leaves that folder where it is.
{{end}}
