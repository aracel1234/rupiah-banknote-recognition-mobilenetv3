# Audit Report - RupiahSequenceCollector v1

## Scope
This project is a separate Android data collector for Subbab 5.7.3 temporal-sequence calibration. It does not replace or modify `RupiahCalibrationCollector_v3` and uses a different application id (`id.ac.ub.rupiah.sequence`) and a different Google Drive root (`RupiahSequenceCollector`).

## Research-plan checks
- Sequence plan contains exactly 40 sequences per device.
- Composition: 28 nominal sequences, 6 nonmoney sequences, and 6 object-transition sequences.
- The 28 nominal sequences are operationalized as 7 nominal classes x 4 scenarios: stable, light motion, distance change, and orientation change.
- The six nonmoney object identities and six transition pairings are an operationalization for data collection; the thesis proposal specifies the counts and behavior categories but not those exact object identities/pairings.
- Each sequence has a fixed 12-second protocol with stage labels and timestamps.
- Target collection rate is 5 analysis frames/second. The offline analyzer can replay both 5 FPS and 3 FPS candidates.
- The collector requires the confirmed 5.7.2 ROI/quality configuration before sequence capture; after the first saved sequence this configuration is locked for the collection session.

## Model and inference checks
- Selected model SHA-256: `fa373b8832a860302ce2b58bd712fc85ad4bf252bdfa9edf2fc1a276934a8676`.
- Model assets were copied from the existing Android implementation used by the thesis.
- `ModelRunner.kt` is identical to the production implementation except for the Kotlin package declaration.
- Class order is: `1000, 2000, 5000, 10000, 20000, 50000, 100000, nonuang`.
- Input and output tensor contracts are checked at runtime by `ModelRunner`.

## Static/source audits performed
1. Model asset hash/integrity checks passed.
2. `SequencePlan.kt` compiled and executed with local Kotlin compiler:
   - total = 40
   - nominal = 28
   - nonmoney = 6
   - transition = 6
   - unique IDs = 40
   - all sequence durations = 12,000 ms
3. Pure Kotlin compilation of `SequencePlan.kt`, `FrameRecord.kt`, and `LuminanceClahe.kt` passed.
4. Android manifest and all XML resources parsed successfully.
5. Static `R.id` audit found no missing resource IDs.
6. Python audit and analysis tools passed `py_compile`.
7. No embedded credentials, OAuth tokens, API keys, or secrets were found by repository text scan.

## End-to-end data-pipeline audit with synthetic data
A synthetic complete collection was generated with 40 sequences and 2,400 frame records.

`tools/audit_sequence_collection.py --require-complete` result:
- `ok = true`
- errors = none
- warnings = none
- sequences = 40
- frames = 2,400
- inference frames = 2,400
- saved checklist entries = 40

`tools/analyze_sequences.py` successfully replayed all thesis candidate combinations:
- FPS: 3 and 5
- confidence threshold: 0.50 through 0.95 in steps of 0.05
- temporal window: 1,000, 1,500, and 2,000 ms
- minimum results: 3
- smoothing: mean of the complete 8-class score vector

The analyzer produced candidate-level metrics and segment-level results, including nominal CAR/WAR/RR, nonmoney FAR, reset/transition false-accept behavior, and decision-time statistics.

## Storage safety audit
- Local-first write is used before Google Drive synchronization.
- Google Drive access uses Android Storage Access Framework (`ACTION_OPEN_DOCUMENT_TREE`) with persisted URI permission; there is no embedded Google credential.
- The Drive root is separate from the static calibration collector.
- Existing static calibration data is not read, overwritten, cleared, or migrated.
- A sequence can only be deleted through the explicit delete action in the sequence collector.
- Index/manifest files are finalized after sequence data files, reducing the chance of a manifest referring to a sequence that was never written.

## Build/runtime verification limitation
A full Android Gradle build, APK installation, and physical-device smoke test could not be completed inside this execution environment. The included Gradle wrapper attempted to download Gradle 8.9 but network/DNS access to `services.gradle.org` is unavailable here, and this environment does not expose an Android SDK/`ANDROID_HOME`.

Therefore the project has been source-audited and its data/analysis pipeline has been exercised end-to-end with synthetic data, but the final Android compile and physical POCO/Redmi runtime verification must be performed in the user's Android development environment before research data collection begins.

## Required pre-collection smoke test on the user's machine
Before collecting real research sequences:
1. Build `assembleDebug` successfully.
2. Install with `adb install -r` on POCO and Redmi.
3. Select a Google Drive folder and verify persisted access after app restart.
4. Configure the confirmed 5.7.2 ROI/quality parameters.
5. Capture one disposable nominal sequence, one disposable nonmoney sequence, and one disposable transition sequence.
6. Synchronize them to Drive.
7. Pull/export the collector folder and run `tools/audit_sequence_collection.py`.
8. Run `tools/analyze_sequences.py` and confirm output files are produced.
9. Delete/segregate the disposable smoke-test data before starting the formal 40-sequence collection.
