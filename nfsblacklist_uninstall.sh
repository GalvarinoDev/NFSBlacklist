#!/bin/bash
# nfsblacklist_uninstall.sh

RED='\033[0;31m'
YELLOW='\033[0;33m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
BOLD='\033[1m'
CLEAR='\033[0m'

info()    { printf "${CYAN}${BOLD}[NFSBL ]${CLEAR} %s\n" "$1"; }
success() { printf "${GREEN}${BOLD}[  OK  ]${CLEAR} %s\n" "$1"; }
warn()    { printf "${YELLOW}${BOLD}[ WARN ]${CLEAR} %s\n" "$1"; }
skip()    { printf "         %s\n" "$1"; }

# ── Branch identity ──────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$SCRIPT_DIR/nfsblacklist_identity.sh" ]; then
    source "$SCRIPT_DIR/nfsblacklist_identity.sh"
elif [ -f "$HOME/NFSBlacklist/nfsblacklist_identity.sh" ]; then
    source "$HOME/NFSBlacklist/nfsblacklist_identity.sh"
else
    INSTALL_DIR_NAME="NFSBlacklist"
    INSTALL_DIR="$HOME/NFSBlacklist"
    APP_TITLE="NFSBlacklist"
    XDG_ID="nfsblacklist"
fi

echo ""
echo -e "${BOLD}  $APP_TITLE -- Full Uninstaller${CLEAR}"
echo ""

zenity --question \
    --title="$APP_TITLE Uninstaller" \
    --text="This will remove all NFSBlacklist shortcuts, mod files from your game directories, Proton prefixes created by NFSBlacklist, and the NFSBlacklist install directory.\n\nYour game files (executables, saves, original data) are NOT touched.\n\nContinue?" \
    --ok-label="Cancel" \
    --cancel-label="Yes, Uninstall" 2>/dev/null

if [ $? -eq 0 ]; then
    zenity --info --title="$APP_TITLE" --text="Uninstall cancelled." 2>/dev/null
    exit 0
fi

echo ""

# ── Close Steam ──────────────────────────────────────────────────────────────
info "Closing Steam..."

if pgrep -x "steam" > /dev/null 2>&1 || pgrep -f "steam.sh" > /dev/null 2>&1; then
    steam -shutdown 2>/dev/null

    deadline=$((SECONDS + 120))
    while pgrep -x "steam" > /dev/null 2>&1 || pgrep -f "steam.sh" > /dev/null 2>&1; do
        if [ $SECONDS -ge $deadline ]; then
            warn "Steam did not close within 120 seconds."
            warn "Please close Steam manually and re-run the uninstaller."
            exit 1
        fi
        sleep 1
    done
    sleep 3
    sync
    success "Steam closed."
else
    skip "Steam was not running."
fi

echo ""

# ── Find Steam root ──────────────────────────────────────────────────────────
STEAM_ROOTS=(
    "$HOME/.local/share/Steam"
    "$HOME/.steam/steam"
    "$HOME/.steam/root"
    "$HOME/.steam/debian-installation"
    "/home/deck/.local/share/Steam"
)

STEAM_ROOT=""
for r in "${STEAM_ROOTS[@]}"; do
    if [ -d "$r/steamapps" ]; then
        STEAM_ROOT="$r"
        break
    fi
done

if [ -z "$STEAM_ROOT" ]; then
    warn "Steam root not found -- skipping shortcut/artwork cleanup."
else
    success "Steam found at $STEAM_ROOT"
fi

echo ""

# ── Remove NFSBlacklist shortcuts and artwork from shortcuts.vdf ─────────────
if [ -n "$STEAM_ROOT" ] && [ -d "$STEAM_ROOT/userdata" ]; then
    info "Removing NFSBlacklist shortcuts and artwork..."
python3 - "$STEAM_ROOT" <<'PYEOF'
import os, re, sys, struct

steam_root = sys.argv[1]
userdata   = os.path.join(steam_root, "userdata")

if not os.path.isdir(userdata):
    sys.exit(0)

removed_total = 0
appids_removed = set()

for uid in os.listdir(userdata):
    if not uid.isdigit() or int(uid) < 10000:
        continue
    vdf = os.path.join(userdata, uid, "config", "shortcuts.vdf")
    if not os.path.exists(vdf):
        continue
    try:
        with open(vdf, "rb") as f:
            data = f.read()
    except Exception:
        continue

    if not data.startswith(b'\x00shortcuts\x00'):
        continue

    header = b'\x00shortcuts\x00'
    body = data[len(header):]

    # Split into entries by finding entry start markers
    entry_starts = []
    for m in re.finditer(rb'\x00\d+\x00', body):
        entry_starts.append(m.start())

    if not entry_starts:
        continue

    entries = []
    for i, start in enumerate(entry_starts):
        end = entry_starts[i + 1] if i + 1 < len(entry_starts) else len(body)
        entries.append(body[start:end])

    kept = []
    removed_here = 0
    for entry in entries:
        # Check for NFSBlacklist tag
        if b'NFSBlacklist' in entry:
            # Extract appid for artwork cleanup
            marker = b'\x02appid\x00'
            marker_pos = entry.find(marker)
            if marker_pos != -1:
                appid_offset = marker_pos + len(marker)
                if appid_offset + 4 <= len(entry):
                    signed = struct.unpack_from("<i", entry, appid_offset)[0]
                    unsigned = signed if signed >= 0 else signed + 2**32
                    appids_removed.add(str(unsigned))
            removed_here += 1
            continue
        kept.append(entry)

    if removed_here == 0:
        continue

    # Re-index remaining entries
    reindexed = []
    for new_idx, entry in enumerate(kept):
        entry = re.sub(rb'^\x00\d+\x00', f'\x00{new_idx}\x00'.encode(), entry)
        reindexed.append(entry)

    new_body = b''.join(reindexed)
    new_data = header + new_body + b'\x08\x08'

    # Backup before writing
    bak = vdf + ".nfsbl_uninstall.bak"
    if not os.path.exists(bak):
        with open(bak, "wb") as f:
            f.write(data)

    with open(vdf, "wb") as f:
        f.write(new_data)
    removed_total += removed_here
    print(f"  uid {uid}: removed {removed_here} NFSBlacklist shortcut(s)")

    # Remove artwork files for removed appids
    grid_dir = os.path.join(userdata, uid, "config", "grid")
    if os.path.isdir(grid_dir):
        art_removed = 0
        for appid_str in appids_removed:
            import glob
            for f in glob.glob(os.path.join(grid_dir, f"{appid_str}*")):
                try:
                    os.remove(f)
                    art_removed += 1
                except OSError:
                    pass
        if art_removed > 0:
            print(f"  uid {uid}: removed {art_removed} artwork file(s)")

if removed_total > 0:
    print(f"  Total: {removed_total} NFSBlacklist shortcut(s) removed")
else:
    print("  No NFSBlacklist shortcuts to remove")

# Write appids to temp file for prefix cleanup
if appids_removed:
    with open("/tmp/nfsbl_appids.txt", "w") as f:
        for a in appids_removed:
            f.write(a + "\n")
PYEOF
    success "Shortcut and artwork cleanup done."
fi
echo ""

# ── Remove mod files from game directories ───────────────────────────────────
info "Removing mod files from game directories..."

# Read the NFSBlacklist config to find game install directories
if [ -f "$INSTALL_DIR/nfsblacklist.json" ]; then
python3 - "$INSTALL_DIR/nfsblacklist.json" <<'PYEOF'
import json, os, sys, shutil

config_path = sys.argv[1]
try:
    with open(config_path) as f:
        cfg = json.load(f)
except Exception:
    print("  Could not read config — skipping mod removal")
    sys.exit(0)

games = cfg.get("games", {})
if not games:
    print("  No games in config — skipping mod removal")
    sys.exit(0)

# Files and dirs placed by our mod installers
MOD_SCRIPTS = [
    # Widescreen Fix
    "NFSUnderground.WidescreenFix.asi", "NFSUnderground.WidescreenFix.ini",
    "NFSUnderground.WidescreenFix.dat", "NFSUnderground.WidescreenFix.tpk",
    "NFSUnderground2.WidescreenFix.asi", "NFSUnderground2.WidescreenFix.ini",
    "NFSUnderground2.WidescreenFix.dat",
    "NFSMostWanted.WidescreenFix.asi", "NFSMostWanted.WidescreenFix.ini",
    "NFSMostWanted.WidescreenFix.tpk",
    "NFSCarbon.WidescreenFix.asi", "NFSCarbon.WidescreenFix.ini",
    "NFSCarbon.WidescreenFix.tpk",
    # Extra Options
    "NFSUExtraOptions.asi", "NFSUExtraOptionsSettings.ini",
    "NFSU2ExtraOptions.asi", "NFSU2ExtraOptionsSettings.ini",
    "NFSMWExtraOptions.asi", "NFSMWExtraOptionsSettings.ini",
    "NFSCExtraOptions.asi", "NFSCExtraOptionsSettings.ini",
    # XtendedInput
    "NFSU_XtendedInput.asi", "NFSU_XtendedInput.ini",
    "NFS_XtendedInput.asi", "NFS_XtendedInput.ini", "NFS_XtendedInput.default.ini",
    "nfs_cursor.cur",
    # XenonEffects
    "NFSMW_XenonEffects.asi", "NFSMW_XenonEffects.ini",
]

# TPK folders placed by XtendedInput and XenonEffects
MOD_TPK_FILES = {
    "nfsu":  [("Global", "UG_ConsoleButtons.tpk")],
    "nfsmw": [("GLOBAL", "XtendedInputButtons.tpk"), ("GLOBAL", "XenonEffects.tpk")],
    "nfsc":  [("GLOBAL", "XtendedInputButtons.tpk")],
}

total_removed = 0

for key, game in games.items():
    install_dir = game.get("install_dir")
    if not install_dir or not os.path.isdir(install_dir):
        continue

    print(f"  {game.get('name', key)}:")

    # Remove scripts/ mod files
    scripts_dir = os.path.join(install_dir, "scripts")
    if os.path.isdir(scripts_dir):
        for fname in MOD_SCRIPTS:
            fpath = os.path.join(scripts_dir, fname)
            if os.path.exists(fpath):
                try:
                    os.remove(fpath)
                    total_removed += 1
                except OSError:
                    pass

    # Remove dinput8.dll (ASI loader placed by Widescreen Fix)
    dll_path = os.path.join(install_dir, "dinput8.dll")
    if os.path.exists(dll_path):
        try:
            os.remove(dll_path)
            total_removed += 1
            print(f"    removed dinput8.dll")
        except OSError:
            pass

    # Remove TPK files placed by our mods
    if key in MOD_TPK_FILES:
        for folder, tpk_name in MOD_TPK_FILES[key]:
            tpk_path = os.path.join(install_dir, folder, tpk_name)
            if os.path.exists(tpk_path):
                try:
                    os.remove(tpk_path)
                    total_removed += 1
                except OSError:
                    pass

    if total_removed > 0:
        print(f"    removed mod files")

if total_removed > 0:
    print(f"  Total: {total_removed} mod file(s) removed")
else:
    print("  No mod files to remove")
PYEOF
    success "Mod file cleanup done."
else
    skip "No NFSBlacklist config found — skipping mod removal."
fi
echo ""

# ── Remove compat tool mappings from config.vdf ─────────────────────────────
if [ -n "$STEAM_ROOT" ] && [ -f "/tmp/nfsbl_appids.txt" ]; then
    info "Removing compat tool mappings..."
python3 - "$STEAM_ROOT" <<'PYEOF'
import os, re, sys

steam_root = sys.argv[1]
config_vdf = os.path.join(steam_root, "config", "config.vdf")

if not os.path.exists(config_vdf):
    print("  config.vdf not found")
    sys.exit(0)

appids_file = "/tmp/nfsbl_appids.txt"
if not os.path.exists(appids_file):
    sys.exit(0)

with open(appids_file) as f:
    appids = {line.strip() for line in f if line.strip()}

if not appids:
    sys.exit(0)

with open(config_vdf, "r", encoding="utf-8", errors="replace") as f:
    content = f.read()

removed = 0
for appid in appids:
    pattern = rf'\t+"{re.escape(appid)}"\n\t+\{{[^}}]*\}}\n?'
    new_content, count = re.subn(pattern, '', content, flags=re.MULTILINE | re.DOTALL)
    if count > 0:
        content = new_content
        removed += count

if removed > 0:
    bak = config_vdf + ".nfsbl_uninstall.bak"
    if not os.path.exists(bak):
        import shutil
        shutil.copy2(config_vdf, bak)
    with open(config_vdf, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  Removed {removed} compat tool mapping(s)")
else:
    print("  No compat tool mappings to remove")
PYEOF
    success "Compat tool cleanup done."
fi
echo ""

# ── Remove Proton prefixes ───────────────────────────────────────────────────
if [ -f "/tmp/nfsbl_appids.txt" ]; then
    info "Removing Proton prefixes..."
    prefix_count=0
    while IFS= read -r appid; do
        [ -z "$appid" ] && continue
        # Check both NVMe and default locations
        for prefix_dir in \
            "$HOME/.local/share/Steam/steamapps/compatdata/$appid" \
            "$STEAM_ROOT/steamapps/compatdata/$appid"; do
            if [ -d "$prefix_dir" ]; then
                rm -rf "$prefix_dir" 2>/dev/null && prefix_count=$((prefix_count + 1))
                info "  Removed prefix: $appid"
            fi
        done
    done < /tmp/nfsbl_appids.txt

    if [ "$prefix_count" -gt 0 ]; then
        success "Removed $prefix_count Proton prefix(es)."
    else
        skip "No Proton prefixes to remove."
    fi
    rm -f /tmp/nfsbl_appids.txt
fi
echo ""

# ── Remove shared DLLs directory ─────────────────────────────────────────────
info "Removing shared DLL directory..."
SHARED_DLL_DIR="$HOME/.local/share/Steam/steamapps/compatdata/.nfsblacklist_shared_dlls"
if [ -d "$SHARED_DLL_DIR" ]; then
    rm -rf "$SHARED_DLL_DIR" && success "Removed shared DLLs."
else
    skip "No shared DLL directory."
fi
echo ""

# ── Remove NFSBlacklist install directory ────────────────────────────────────
info "Removing $INSTALL_DIR..."
if [ -d "$INSTALL_DIR" ]; then
    rm -rf "$INSTALL_DIR" && success "Removed $INSTALL_DIR"
else
    skip "Install directory not found."
fi
echo ""

# ── Remove .desktop shortcuts ────────────────────────────────────────────────
info "Removing desktop shortcuts..."

SHORTCUTS=(
    "$HOME/.local/share/applications/nfsblacklist.desktop"
    "$HOME/Desktop/NFSBlacklist.desktop"
)

for s in "${SHORTCUTS[@]}"; do
    [ -f "$s" ] && rm -f "$s" && success "Removed $s" || skip "$(basename "$s") not found"
done

command -v update-desktop-database &>/dev/null && \
    update-desktop-database "$HOME/.local/share/applications" 2>/dev/null && \
    success "Desktop database refreshed" || true
echo ""

# ── Done ─────────────────────────────────────────────────────────────────────
echo -e "${GREEN}${BOLD}  NFSBlacklist fully uninstalled.${CLEAR}"
echo ""
echo "  Your game files are untouched."
echo "  All NFSBlacklist mod files removed from game directories."
echo "  All NFSBlacklist shortcuts and artwork removed."
echo "  All Proton prefixes created by NFSBlacklist removed."
echo ""

info "Uninstall complete — restarting Steam..."
echo ""

gtk-launch steam.desktop

zenity --info \
    --title="$APP_TITLE Uninstaller" \
    --text="NFSBlacklist fully uninstalled.\n\nYour game files are untouched.\nAll mod files removed from game directories.\nAll shortcuts and artwork removed.\nAll Proton prefixes removed.\n\nSteam is restarting." \
    --timeout=12 \
    2>/dev/null &

for i in 10 9 8 7 6 5 4 3 2 1; do
    printf "\r  Closing in %d seconds... " "$i"
    sleep 1
done
echo ""
