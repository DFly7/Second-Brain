#!/usr/bin/env bash
# scripts/ios-sim.sh — Build SecondBrainApp and launch it on an iOS Simulator.
#
# Usage:
#   ./scripts/ios-sim.sh                  # auto-picks newest iPhone sim (all runtimes)
#   IOS_SIM_MAX_MAJOR=18 ./scripts/ios-sim.sh   # newest iPhone on iOS ≤ 18 only
#   ./scripts/ios-sim.sh --regen        # tuist install + generate first
#   ./scripts/ios-sim.sh --udid <UDID>  # target a specific simulator
#   ./scripts/ios-sim.sh --logs         # stream console after launch
#   ./scripts/ios-sim.sh --regen --logs # combine flags

set -euo pipefail

REGEN=false
LOGS=false
TARGET_UDID=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --regen) REGEN=true;  shift ;;
    --logs)  LOGS=true;   shift ;;
    --udid)  TARGET_UDID="$2"; shift 2 ;;
    -h|--help)
      sed -n '/^# Usage/,/^$/p' "$0" | sed 's/^# \{0,2\}//'
      exit 0 ;;
    *) echo "Unknown argument: $1  (try --help)"; exit 1 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
IOS_DIR="$REPO_ROOT/ios/SecondBrainApp"
cd "$IOS_DIR"

WORKSPACE="SecondBrainApp.xcworkspace"
SCHEME="SecondBrainApp"
DERIVED_DATA="./DerivedDataRun"
APP_PATH="$DERIVED_DATA/Build/Products/Debug-iphonesimulator/SecondBrainApp.app"

for cmd in xcodebuild xcrun python3; do
  command -v "$cmd" &>/dev/null || { echo "Error: '$cmd' not found."; exit 1; }
done

if $REGEN || [[ ! -d "$WORKSPACE" ]]; then
  command -v tuist &>/dev/null || {
    echo "Error: 'tuist' not found. Install from https://docs.tuist.dev"
    exit 1
  }
  echo "→ tuist install…"
  tuist install
  echo "→ tuist generate…"
  tuist generate --no-open
fi

[[ -d "$WORKSPACE" ]] || {
  echo "Error: $WORKSPACE not found."
  echo "       Run with --regen to generate it first."
  exit 1
}

_devdir="$(xcode-select -p 2>/dev/null || true)"
if [[ "$_devdir" == *CommandLineTools* ]]; then
  echo "Error: xcode-select points at Command Line Tools (no Simulator SDK for builds):"
  echo "       $_devdir"
  echo "       Point at full Xcode, then retry:"
  echo "         sudo xcode-select -s /Applications/Xcode.app/Contents/Developer"
  exit 1
fi
if ! xcrun --sdk iphonesimulator --show-sdk-path &>/dev/null; then
  echo "Error: iphonesimulator SDK missing for active developer directory:"
  echo "       ${_devdir:-unknown}"
  echo "       Install platforms: Xcode → Settings → Components"
  echo "       (install the iOS version that matches your Xcode / device support, including Simulator)"
  exit 1
fi

if [[ -z "$TARGET_UDID" ]]; then
  if [[ -n "${IOS_SIM_MAX_MAJOR:-}" ]]; then
    echo "→ Picking newest iPhone simulator with iOS major ≤ ${IOS_SIM_MAX_MAJOR} …"
  else
    echo "→ Picking newest available iPhone simulator (simctl) for install/launch…"
  fi
  if ! _pick_raw="$(IOS_SIM_MAX_MAJOR="${IOS_SIM_MAX_MAJOR:-}" python3 <<'EOF'
import json, os, subprocess, sys

raw = subprocess.check_output(["xcrun", "simctl", "list", "devices", "available", "-j"])
data = json.loads(raw)

max_s = os.environ.get("IOS_SIM_MAX_MAJOR", "").strip()
max_major = int(max_s) if max_s.isdigit() else None


def collect(major_cap):
    out = []
    for runtime, devices in data["devices"].items():
        if "iOS" not in runtime:
            continue
        ver = runtime.split("iOS-")[-1].replace("-", ".")
        ver_parts = tuple(int(x) for x in ver.split(".") if x.isdigit()) or (0,)
        runtime_major = ver_parts[0]
        if major_cap is not None and runtime_major > major_cap:
            continue
        for d in devices:
            if d.get("isAvailable") and "iPhone" in d["name"]:
                out.append((ver_parts, d["udid"], d["name"]))
    return out


candidates = collect(max_major)
if not candidates and max_major is not None:
    print(
        f"Note: IOS_SIM_MAX_MAJOR={max_major} excluded all runtimes; using any iPhone runtime.",
        file=sys.stderr,
    )
    candidates = collect(None)

if not candidates:
    sys.exit(1)

candidates.sort(key=lambda t: t[0], reverse=True)
_, udid, name = candidates[0]
print(udid)
print(name)
EOF
  )"; then
    echo "Error: No available iPhone simulator (simctl list devices available)."
    echo "       Xcode → Settings → Components: install an iOS simulator runtime."
    exit 1
  fi
  TARGET_UDID="$(printf '%s\n' "$_pick_raw" | head -n1)"
  SIM_NAME="$(printf '%s\n' "$_pick_raw" | tail -n1)"
fi

[[ -n "$TARGET_UDID" ]] || {
  echo "Error: No simulator UDID (use --udid <UDID>)."
  exit 1
}

if [[ -z "${SIM_NAME:-}" ]]; then
  SIM_NAME=$(xcrun simctl list devices available 2>/dev/null | grep "$TARGET_UDID" | sed 's/ (.*//' | xargs || true)
  [[ -n "${SIM_NAME:-}" ]] || SIM_NAME="Simulator"
fi
echo "→ Simulator: ${SIM_NAME} (${TARGET_UDID})"

# Explicit simulator id matches the install target; generic destination can fail when SDKROOT skews to iphoneos.
echo "→ Building ${SCHEME} (Debug) for iOS Simulator…"
xcodebuild build \
  -workspace "$WORKSPACE" \
  -scheme "$SCHEME" \
  -configuration Debug \
  -sdk iphonesimulator \
  -destination "platform=iOS Simulator,id=$TARGET_UDID" \
  -derivedDataPath "$DERIVED_DATA" \
  -quiet

[[ -d "$APP_PATH" ]] || {
  echo "Error: Build succeeded but .app not found at expected path:"
  echo "       $APP_PATH"
  exit 1
}

BUNDLE_ID=$(defaults read "$(pwd)/$APP_PATH/Info.plist" CFBundleIdentifier 2>/dev/null || true)
[[ -n "$BUNDLE_ID" ]] || {
  echo "Error: Could not read CFBundleIdentifier from $APP_PATH/Info.plist"
  exit 1
}

echo "→ Booting simulator…"
xcrun simctl boot "$TARGET_UDID" 2>/dev/null || true
open -a Simulator --args -CurrentDeviceUDID "$TARGET_UDID"

echo "→ Installing ${BUNDLE_ID}…"
xcrun simctl install "$TARGET_UDID" "$APP_PATH"

if $LOGS; then
  echo "→ Launching with console logs (Ctrl-C to stop)…"
  xcrun simctl launch --console-pty "$TARGET_UDID" "$BUNDLE_ID"
else
  echo "→ Launching…"
  xcrun simctl launch "$TARGET_UDID" "$BUNDLE_ID"
  echo ""
  echo "✓ ${BUNDLE_ID} running on ${SIM_NAME}"
fi
