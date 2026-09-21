#!/usr/bin/env bash
# Bootstrap the official wrapper without downloading an unverified third-party JAR.
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
for tool in java curl unzip sha256sum; do
    command -v "$tool" >/dev/null || { echo "Diperlukan: $tool" >&2; exit 1; }
done
if [[ -f "$project_dir/gradle/wrapper/gradle-wrapper.jar" ]]; then
    echo "Gradle wrapper sudah tersedia."
    exit 0
fi
setup_dir="$(mktemp -d)"
trap 'rm -rf -- "$setup_dir"' EXIT
curl --fail --location --retry 2 --connect-timeout 20 --max-time 900 \
    https://services.gradle.org/distributions/gradle-8.9-bin.zip -o "$setup_dir/gradle.zip"
curl --fail --location --retry 2 --connect-timeout 20 --max-time 90 \
    https://services.gradle.org/distributions/gradle-8.9-bin.zip.sha256 -o "$setup_dir/expected.sha256"
expected="$(tr -d '[:space:]' < "$setup_dir/expected.sha256")"
[[ "$expected" =~ ^[a-fA-F0-9]{64}$ ]] || { echo "Checksum resmi tidak valid" >&2; exit 1; }
actual="$(sha256sum "$setup_dir/gradle.zip")"
[[ "${actual%% *}" == "$expected" ]] || { echo "Checksum unduhan tidak cocok" >&2; exit 1; }
unzip -q "$setup_dir/gradle.zip" -d "$setup_dir"
mkdir "$setup_dir/wrapper-project"
printf 'rootProject.name = "wrapper-bootstrap"\n' > "$setup_dir/wrapper-project/settings.gradle.kts"
"$setup_dir/gradle-8.9/bin/gradle" --no-daemon -p "$setup_dir/wrapper-project" wrapper \
    --gradle-version 8.9 --distribution-type bin --gradle-distribution-sha256-sum "$expected"
cp "$setup_dir/wrapper-project/gradlew" "$project_dir/gradlew"
cp "$setup_dir/wrapper-project/gradlew.bat" "$project_dir/gradlew.bat"
cp "$setup_dir/wrapper-project/gradle/wrapper/gradle-wrapper.jar" "$project_dir/gradle/wrapper/"
cp "$setup_dir/wrapper-project/gradle/wrapper/gradle-wrapper.properties" "$project_dir/gradle/wrapper/"
chmod +x "$project_dir/gradlew"
echo "Wrapper resmi Gradle 8.9 siap. Buka proyek di Android Studio, lalu Sync."
