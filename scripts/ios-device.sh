#!/usr/bin/env bash
# scripts/ios-device.sh — Build SecondBrainApp for a physical iPhone, install & launch via devicectl.
#
# Prerequisites:
#   • Xcode (full app), same-network or USB-connected iPhone, Developer Mode enabled on device.
#   • Code signing: DEVELOPMENT_TEAM in Config-*.xcconfig (see ios/SecondBrainApp). Use
#     IOS_DEVICE_TEAM=… only to override from the CLI (alternate Apple account / CI).
#
# Usage:
#   ./scripts/ios-device.sh                  # Release (prod BACKEND_URL); picks paired iPhone (devicectl)
#   ./scripts/ios-device.sh --debug        # Debug + Config-Debug.xcconfig (local API base URL)
#   ./scripts/ios-device.sh --release      # same as default (explicit)
#   ./scripts/ios-device.sh --udid <UDID> # hardware UDID from devicectl / Xcode / Finder
#   IOS_DEVICE_TEAM=XXXXXXXXXX ./scripts/ios-device.sh   # optional; overrides xcconfig team

set -euo pipefail

REGEN=false
LOGS=false
TARGET_UDID=""
# Default Release on device: matches typical “test on phone against prod” and avoids YOUR_MACHINE_IP Debug base URL.
CONFIGURATION="Release"

while [[ $# -gt 0 ]]; do
  case $1 in
    --regen) REGEN=true;  shift ;;
    --logs)  LOGS=true;   shift ;;
    --debug) CONFIGURATION="Debug"; shift ;;
    --release) CONFIGURATION="Release"; shift ;;
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
DERIVED_DATA="./DerivedDataDevice"
APP_PATH="$DERIVED_DATA/Build/Products/${CONFIGURATION}-iphoneos/SecondBrainApp.app"

for cmd in xcodebuild xcrun python3; do
  command -v "$cmd" &>/dev/null || { echo "Error: '$cmd' not found."; exit 1; }
done

if ! xcrun devicectl list devices &>/dev/null; then
  echo "Error: 'devicectl' not usable (need recent Xcode with Core Device support, typically Xcode 15+)."
  exit 1
fi

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
  echo "       Run \`make ios-gen\` or \`./scripts/ios-device.sh --regen\`."
  exit 1
}

_devdir="$(xcode-select -p 2>/dev/null || true)"
if [[ "$_devdir" == *CommandLineTools* ]]; then
  echo "Error: xcode-select points at Command Line Tools (device builds need full Xcode):"
  echo "       $_devdir"
  echo "         sudo xcode-select -s /Applications/Xcode.app/Contents/Developer"
  exit 1
fi
if ! xcrun --sdk iphoneos --show-sdk-path &>/dev/null; then
  echo "Error: iphoneos SDK missing for active developer directory:"
  echo "       ${_devdir:-unknown}"
  echo "       Install device platform support: Xcode → Settings → Components / Platforms."
  exit 1
fi

if [[ -z "$TARGET_UDID" ]]; then
  echo "→ Picking paired physical iPhone (devicectl)…"
  if ! _pick_raw="$(python3 <<'EOF'
import json, subprocess, sys

raw = subprocess.check_output(["xcrun", "devicectl", "list", "devices", "--json-output", "-"])
data = json.loads(raw)
devices = data.get("result", {}).get("devices", [])
candidates = []
for d in devices:
    hw = d.get("hardwareProperties") or {}
    if hw.get("reality") != "physical":
        continue
    if hw.get("deviceType") != "iPhone":
        continue
    conn = d.get("connectionProperties") or {}
    if conn.get("pairingState") != "paired":
        continue
    udid = hw.get("udid") or ""
    if not udid:
        continue
    tunnel = conn.get("tunnelState") or ""
    dev_name = (d.get("deviceProperties") or {}).get("name") or hw.get("marketingName") or "iPhone"
    tun_rank = 0 if tunnel == "connected" else (1 if tunnel == "disconnected" else 9)
    candidates.append((tun_rank, dev_name, udid))

candidates.sort(key=lambda t: (t[0], t[1]))
if not candidates:
    sys.exit(1)
_, name, udid = candidates[0]
print(udid)
print(name)
EOF
  )"; then
    echo "Error: No paired physical iPhone found."
    echo "       Unlock the phone; connect USB or stay on the same network; trust this Mac."
    echo "       Settings → Privacy & Security → Developer Mode must be enabled."
    echo "       Check: xcrun devicectl list devices"
    echo "       Or pass an explicit hardware UDID:  ./scripts/ios-device.sh --udid <UDID>"
    exit 1
  fi
  TARGET_UDID="$(printf '%s\n' "$_pick_raw" | head -n1)"
  DEV_NAME="$(printf '%s\n' "$_pick_raw" | tail -n1)"
fi

[[ -n "$TARGET_UDID" ]] || {
  echo "Error: No device UDID (use --udid <UDID>)."
  exit 1
}

if [[ -z "${DEV_NAME:-}" ]]; then
  DEV_NAME="Device ${TARGET_UDID}"
fi
echo "→ Device: ${DEV_NAME} (${TARGET_UDID})"

echo "→ Building ${SCHEME} (${CONFIGURATION}) for iOS device…"
_xcb=(
  xcodebuild build
  -workspace "$WORKSPACE"
  -scheme "$SCHEME"
  -configuration "$CONFIGURATION"
  -sdk iphoneos
  -destination "platform=iOS,id=$TARGET_UDID"
  -derivedDataPath "$DERIVED_DATA"
  -allowProvisioningUpdates
)
[[ -n "${IOS_DEVICE_TEAM:-}" ]] && _xcb+=(DEVELOPMENT_TEAM="$IOS_DEVICE_TEAM")
"${_xcb[@]}"

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

echo "→ Installing ${BUNDLE_ID}…"
xcrun devicectl device install app --device "$TARGET_UDID" "$APP_PATH" --timeout 300

if $LOGS; then
  echo "→ Launching with console (Ctrl-C to stop)…"
  xcrun devicectl device process launch --console --device "$TARGET_UDID" "$BUNDLE_ID" --timeout 120
else
  echo "→ Launching…"
  xcrun devicectl device process launch --device "$TARGET_UDID" "$BUNDLE_ID" --timeout 120
  echo ""
  echo "✓ ${BUNDLE_ID} launched on ${DEV_NAME}"
fi
