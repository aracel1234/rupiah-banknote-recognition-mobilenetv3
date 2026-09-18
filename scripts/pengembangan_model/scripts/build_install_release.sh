#!/usr/bin/env bash
set -euo pipefail
PROJECT="${1:-$(pwd)}"
cd "$PROJECT"
if [ -x ./gradlew ]; then
  ./gradlew clean assembleRelease
elif command -v gradle >/dev/null 2>&1; then
  gradle clean assembleRelease
else
  echo "Gradle wrapper tidak ditemukan. Buka project ini di Android Studio, Sync, lalu Build > Generate App Bundles or APKs > Build APKs." >&2
  exit 1
fi
APK="app/build/outputs/apk/release/app-release.apk"
[ -f "$APK" ] || { echo "APK release tidak ditemukan: $APK" >&2; exit 1; }
adb install -r "$APK"
echo "Installed: $APK"
