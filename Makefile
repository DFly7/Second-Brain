# Run from the repo root: make <target>
# ios-run passes flags through to scripts/ios-sim.sh, e.g.:
#   make ios-run ARGS="--logs"
#   make ios-run ARGS="--release"           # Release → Config-Release.xcconfig (prod API URL)
#   make ios-run ARGS="--regen --logs"
#   make ios-run ARGS="--udid <UDID>"
#
# Physical iPhone (Core Device / devicectl — Developer Mode required; Team ID is in xcconfig):
#   make ios-device                              # Release / prod API URL (default on device)
#   make ios-device ARGS="--debug"             # Debug xcconfig (local BACKEND_URL)
#   IOS_DEVICE_TEAM=XXXXXXXXXX make ios-device # optional CLI override only (ci / different Apple account)
#   make ios-device ARGS="--udid <UDID>"
#   make ios-devices                          # list paired devices (devicectl table)
#
# Usage examples:
#   make ios-sims                    # all available devices + UDIDs
#   make ios-sims-iphone             # section headers + iPhone rows only
#   make ios-destinations          # xcodebuild -showdestinations (default + iphonesimulator)
#   make ios-components-check      # xcodebuild -checkForNewerComponents (often "no updates" — still use Components UI)
#   make ios-platform-download     # xcodebuild -downloadPlatform iOS → ~/Downloads (if CLI install path helps)
#   make ios-open                  # open the .xcworkspace in Xcode (then Settings → Components / Platforms)
#   make ios-run ARGS="--udid <UDID>"

.PHONY: help test test-local test-docker lint ios-gen ios-run ios-device ios-devices ios-build ios-sims ios-sims-iphone ios-toolchain ios-destinations ios-components-check ios-platform-download ios-open

help: ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' Makefile \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# ── API tests ────────────────────────────────────────────────────────────────

test-local: ## Run API tests locally without Docker (requires: pip3 install -r api/requirements.txt)
	cd api && python3 -m pytest tests/ -v

test-docker: ## Run API tests inside Docker Compose (uses wiki_test DB)
	docker compose run --rm api pytest tests/ -v

test: test-local ## Alias for test-local

lint: ## Ruff + mypy static analysis on API source (no infrastructure needed)
	cd api && ruff check app/ tests/ && mypy app/

# ── iOS ──────────────────────────────────────────────────────────────────────

ios-gen: ## tuist install + generate (no open)
	cd ios/SecondBrainApp && tuist install && tuist generate --no-open

ios-run: ## Regenerate project, build (Debug), boot sim, install & launch (use ARGS="--release" for prod API URL)
	@$(MAKE) ios-gen
	./scripts/ios-sim.sh $(ARGS)

ios-device: ## Physical iPhone: generate, Release build (prod API), install & launch (ARGS="--debug" for Debug)
	@$(MAKE) ios-gen
	./scripts/ios-device.sh $(ARGS)

ios-devices: ## List paired devices (physical iPhones etc.) visible to devicectl
	xcrun devicectl list devices

ios-build: ## Simulator build only (no install/launch); no specific simulator required
	set -o pipefail && cd ios/SecondBrainApp && xcodebuild build \
		-workspace SecondBrainApp.xcworkspace \
		-scheme SecondBrainApp \
		-configuration Debug \
		-sdk iphonesimulator \
		-destination 'generic/platform=iOS Simulator'

ios-sims: ## List available simulator devices (names, states, UDIDs)
	xcrun simctl list devices available

ios-sims-iphone: ## Same as ios-sims but only iOS section headers + iPhone lines
	xcrun simctl list devices available | grep -E '^-- |^    iPhone '

ios-toolchain: ## Show active Xcode path and iphonesimulator SDK (debug ios-run / xcodebuild errors)
	@echo "xcode-select: $$(xcode-select -p)"
	@xcrun --sdk iphonesimulator --show-sdk-path && echo "iphonesimulator SDK: ok"
	@echo "Note: Simulator SDK can exist while Platform Support for device iOS is still missing."
	@echo "      ios-components-check may print 'No new updates' even when iOS platform is incomplete — use Xcode UI or ios-platform-download."

ios-destinations: ## xcodebuild -showdestinations (no -sdk and with -sdk iphonesimulator)
	@echo "========== -sdk iphonesimulator =========="
	@cd ios/SecondBrainApp && xcodebuild -workspace SecondBrainApp.xcworkspace -scheme SecondBrainApp -sdk iphonesimulator -showdestinations
	@echo ""
	@echo "========== default (no -sdk) =========="
	@cd ios/SecondBrainApp && xcodebuild -workspace SecondBrainApp.xcworkspace -scheme SecondBrainApp -showdestinations
	@echo ""
	@echo ""
	@echo "Empty or no 'platform:iOS Simulator' under Available destinations?"
	@echo "  • Xcode → Settings → Components (or Platforms): install Platform Support for the iOS version in the errors above (e.g. 26.5). Use Get / Download even if CLI said no updates."
	@echo "  • Or: make ios-platform-download  then install/import the .dmg if prompted."
	@echo "  • Or: install stable Xcode 16.x side-by-side, then: sudo xcode-select -s /Applications/Xcode_16.app/Contents/Developer"

ios-components-check: ## Ask Xcode to download/install updated platform support if available
	xcodebuild -runFirstLaunch -checkForNewerComponents
	@echo ""
	@echo "If that reported 'No new updates' but ios-destinations still has no simulators, install iOS platform support in Xcode Settings (see make ios-toolchain note) or try: make ios-platform-download"

ios-platform-download: ## Download iOS platform bundle to ~/Downloads (large; may help when UI/CLI check shows nothing)
	@echo "Downloading iOS platform to $$HOME/Downloads …"
	xcodebuild -downloadPlatform iOS -exportPath "$$HOME/Downloads"
	@echo "If needed: xcodebuild -importPlatform <path-to-.dmg>   (see filenames in Downloads)"

ios-open: ## Open SecondBrainApp.xcworkspace in Xcode (Settings → Components)
	open "$(CURDIR)/ios/SecondBrainApp/SecondBrainApp.xcworkspace"
