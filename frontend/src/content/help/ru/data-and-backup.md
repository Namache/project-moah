---
title: Ваши данные и резервные копии
category: Core features
summary: Где лежат ваши данные и как сделать резервную копию.
keywords: резервная копия, экспорт, данные, база данных, расположение, восстановить, backup
related: troubleshooting-repository
---

Project Moah хранит всё в одном локальном файле базы данных. Ничего никуда не загружается.

{{only flatpak}}
Файл лежит в `~/.var/app/io.github.projectbrain.ProjectBrain/data/project-brain/`.
{{end}}
{{only deb linux}}
Файл лежит в `~/.local/share/project-brain/`.
{{end}}
{{only windows}}
Файл лежит в `%LOCALAPPDATA%\project-brain\`.
{{end}}

В *Настройках*, в разделе *Данные*, показано, где лежит этот файл, и можно экспортировать резервную копию. Чтобы восстановить данные, закройте Project Moah и замените файл базы данных резервной копией.

При удалении или переустановке приложения данные сохраняются.
{{only flatpak}}
Их удаляет только `flatpak uninstall --delete-data`.
{{end}}
{{only deb linux}}
Пакет никогда не трогает вашу домашнюю папку, поэтому `sudo apt remove project-moah` оставляет их на месте.
{{end}}
{{only windows}}
Удаление через *Параметры > Приложения* оставляет эту папку на месте.
{{end}}
