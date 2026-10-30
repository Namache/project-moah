#!/bin/sh
# Chromium records its single-instance lock as "<hostname>-<pid>". Every Flatpak
# launch gets a fresh PID namespace, so a lock left by a crash or forced stop
# looks alive and makes the next launch quit silently. The exclusive lock below
# is held for the app's lifetime (the fd is inherited through exec), so getting
# it proves no other Project Moah instance is running and the files are stale.
# The settings folder keeps the old name (see main.cjs), so the rename resets nothing.
profile_dir="${XDG_CONFIG_HOME:-$HOME/.config}/Project Brain"
lock_dir="${XDG_RUNTIME_DIR:-/tmp}/app/${FLATPAK_ID:-io.github.projectbrain.ProjectBrain}"
mkdir -p "$lock_dir"
exec 9>"$lock_dir/instance.lock"
if flock -n 9; then
  rm -f "$profile_dir/SingletonLock" "$profile_dir/SingletonCookie" "$profile_dir/SingletonSocket"
fi
exec zypak-wrapper /app/lib/project-brain/project-brain-desktop --ozone-platform-hint=auto "$@"
