#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
desktop_dir="$repo_dir/desktop"
app_id='io.github.projectbrain.ProjectBrain'
runtime_version='25.08'

if [[ "$(uname -m)" != 'x86_64' ]]; then
  echo 'The Flatpak target currently supports x86_64 only.' >&2
  exit 1
fi

for executable in flatpak node; do
  if ! command -v "$executable" >/dev/null 2>&1; then
    echo "Missing build tool: $executable" >&2
    exit 1
  fi
done

if command -v flatpak-builder >/dev/null 2>&1; then
  builder=(flatpak-builder)
elif flatpak info org.flatpak.Builder >/dev/null 2>&1; then
  builder=(flatpak run org.flatpak.Builder)
else
  echo 'Install flatpak-builder or the org.flatpak.Builder Flatpak to build this package.' >&2
  exit 1
fi

if [[ ! -x "$desktop_dir/dist/linux-unpacked/project-brain-desktop" ]]; then
  echo 'Build the Electron Linux directory first: npm run pack:linux --prefix desktop' >&2
  exit 1
fi
if [[ ! -x "$desktop_dir/dist/linux-unpacked/resources/bin/project-brain-backend" ]]; then
  echo 'The packaged Electron directory is missing its Linux backend sidecar.' >&2
  exit 1
fi

if ! flatpak info "org.freedesktop.Platform//$runtime_version" >/dev/null 2>&1; then
  echo "Install org.freedesktop.Platform//$runtime_version before building." >&2
  exit 1
fi
if ! flatpak info "org.freedesktop.Sdk//$runtime_version" >/dev/null 2>&1; then
  echo "Install org.freedesktop.Sdk//$runtime_version before building." >&2
  exit 1
fi

version="$(cd "$desktop_dir" && node -p "require('./package.json').version")"
build_dir="$desktop_dir/build/flatpak-build"
state_dir="$desktop_dir/build/flatpak-state"
repo_output="$desktop_dir/build/flatpak-repo"
bundle="$desktop_dir/dist/ProjectMoah-${version}-x86_64.flatpak"

mkdir -p "$desktop_dir/build" "$desktop_dir/dist"
"${builder[@]}" \
  --force-clean \
  --build-only \
  --state-dir="$state_dir" \
  "$build_dir" \
  "$desktop_dir/$app_id.yml"
# flatpak-builder's AppStream compose stage depends on an optional host tool.
# Finish and export the staged app directly, keeping these grants in sync with
# the manifest's finish-args.
flatpak build-finish \
  "$build_dir" \
  --command=project-brain \
  --socket=wayland \
  --socket=x11 \
  --share=ipc \
  --device=dri \
  --filesystem=~/.claude/projects:ro \
  --filesystem=~/.codex/sessions:ro
flatpak build-export "$repo_output" "$build_dir" stable
flatpak build-bundle \
  --arch=x86_64 \
  --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo \
  "$repo_output" \
  "$bundle" \
  "$app_id" \
  stable

echo "Created $bundle"
