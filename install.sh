#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == "--help" ]]; then
  echo "Usage: ./install.sh [--replace]"
  echo "Installs for this user. Does not enable automation or touch saved accounts."
  exit 0
fi
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != "--replace" ) ]]; then
  echo "Unknown option. Use --help." >&2; exit 2
fi
if [[ "$EUID" -eq 0 ]]; then echo "Run as your normal desktop user, without sudo." >&2; exit 1; fi
files=("$HOME/.local/bin/codex-acc" "$HOME/.local/share/codex-auto-switch/codex_auto_switch.py" "$HOME/.config/systemd/user/codex-auto-switch.service" "$HOME/.local/share/applications/codex-account-center.desktop")
for target in "${files[@]}"; do
  if [[ -e "$target" && "${1:-}" != "--replace" ]]; then
    echo "Existing installation: $target. Review it first; --replace creates a backup." >&2; exit 1
  fi
done
if [[ "${1:-}" == "--replace" ]]; then
  backup_dir="$HOME/.local/state/codex-account-center/backups/$(date +%Y%m%d-%H%M%S)"
  install -d -m 700 "$backup_dir"
  for target in "${files[@]}"; do [[ ! -f "$target" ]] || cp -p "$target" "$backup_dir/$(basename "$target")"; done
  echo "Previous installation backed up to $backup_dir"
fi
install -Dm755 "$project_dir/src/codex-acc" "${files[0]}"
install -Dm755 "$project_dir/src/codex_auto_switch.py" "${files[1]}"
install -Dm644 "$project_dir/systemd/codex-auto-switch.service" "${files[2]}"
install -d "$HOME/.local/share/applications"
cat > "${files[3]}" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Codex Account Center
Comment=Manage saved Codex accounts and usage
Exec="$HOME/.local/bin/codex-acc" gui
Icon=utilities-terminal
Terminal=false
Categories=Utility;
DESKTOP
if command -v systemctl >/dev/null; then systemctl --user daemon-reload || true; fi
echo "Installed. Open Codex Account Center or run ~/.local/bin/codex-acc."
echo "Automation was not enabled or restarted. Review settings before starting it."
