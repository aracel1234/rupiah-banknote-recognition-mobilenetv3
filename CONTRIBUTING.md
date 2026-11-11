# Contributing

Contributions to code, documentation, accessibility testing, and data curation
are welcome. The existing repository is the starting point for community
development. [Issue #1](https://github.com/aracel1234/rupiah-banknote-recognition-mobilenetv3/issues/1)
records the initial InfiArtt collaboration discussion.

## Start with a focused change

1. Read [README.md](README.md), [MODEL_CARD.md](MODEL_CARD.md), and the
   [Android README](implementasi_android/README.md).
2. Open an issue describing the behavior, device, or improvement. Existing
   issues can be used when the proposal fits their scope.
3. Fork the repository and create a branch for one focused change.
4. Submit a pull request describing what changed, why, and how it was checked.

The maintainer reviews changes before they enter `main`. Contributions submitted
for inclusion are under the project's Apache-2.0 terms unless separately and
explicitly agreed otherwise, consistent with Section 5 of [LICENSE](LICENSE).
Contributors keep their applicable copyright. Credit is recorded by role in
[CREDITS.md](CREDITS.md) and commit/pull-request history.

## Build the main Android app

Open `implementasi_android/` in Android Studio. Install Android SDK Platform 35,
use JDK 17, and use the supplied Gradle wrapper. From that directory:

```bash
./gradlew :app:assembleDebug
```

The project targets ARM64 and ARMv7 and also builds a universal debug APK.
The universal output is normally
`app/build/outputs/apk/debug/app-universal-debug.apk`.
Use a device with Android API 23 or later. Offline Indonesian TTS voice data
must already be installed when using the app's own TTS route. Test TalkBack
and the offline speech route separately.

The separate `scripts/pengembangan_model/android-benchmark/` project measures
model execution; it is not the user-facing recognizer. It has its own minimum
Android version and dependencies.

## Preserve the research baseline

The starting research snapshot is commit
[`6f7bd82c4930f58ba708ce3d1e107dadc2a66132`](https://github.com/aracel1234/rupiah-banknote-recognition-mobilenetv3/commit/6f7bd82c4930f58ba708ce3d1e107dadc2a66132).
Historical outputs, hashes, and configuration locks document that snapshot.
Keep new experiments and community variants distinguishable from it.

For changes to model assets, preprocessing, class order, or decision parameters,
report the new model hash, tensor contract, configuration revision, and relevant
regression results. Do not overwrite evidence locks simply to bypass validation.
Use the existing reference-inference workflow when inference behavior changes.

Documentation-only changes can be checked by reviewing facts, links, paths, and
metadata; they do not require training or rerunning the full Android benchmark.

## Accessibility and real-device feedback

Useful reports include:

- Device model, Android version, app commit/version, TalkBack version, and TTS
  engine/voice if relevant.
- Steps to reproduce and the expected/observed result.
- Whether the task was completed independently and whether help was needed.
- Lighting, banknote denomination/emission year/condition, distance, and time
  to audible output when applicable.
- Wrong announcements, rejections, repeated speech, focus problems, camera
  permission handling, or behavior after returning to the app.

Start community trials using the existing model/configuration so accessibility
issues can be separated from model changes. Sequential multi-banknote counting
needs an explicit way to distinguish physical notes; do not add every frame
prediction to a total.

Participation and recording should be voluntary. Remove personal information
from logs or videos before posting them. Credit testers using their chosen
public names, with their agreement.

## Data and signing material

New image contributions need a creator, source, license/permission, version or
acquisition date, and processing record. Follow
[DATASET_SOURCES.md](DATASET_SOURCES.md); public availability alone does not
establish reuse permission.

Keep signing keys, passwords, tokens, `local.properties`, and generated build
files out of commits. Use a private local signing key for new binary releases.
The previously tracked benchmark keystores must not be reused for new public
releases; removing them from a branch does not remove older copies from Git
history. If an existing distributed app uses that signing identity, coordinate
the update/key-migration process before changing it.
