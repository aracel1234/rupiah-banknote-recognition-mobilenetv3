# Model card

## Identity and license

| Item | Value |
|---|---|
| Author | Aracel Nestova Aprilyanto |
| Research year | 2026 |
| Architecture | MobileNetV3-Small with an eight-class classification head |
| Selected TFLite candidate | Dynamic Range Quantization |
| Main Android asset | `implementasi_android/app/src/main/assets/model/model.tflite` |
| Size | 1,107,648 bytes (1.05633544921875 MiB) |
| SHA-256 | `fa373b8832a860302ce2b58bd712fc85ad4bf252bdfa9edf2fc1a276934a8676` |
| License of the author's trained-model contributions | Apache-2.0, subject to the scope in [README.md](README.md) |

The maintainer authorizes direct use, modification, and redistribution of the
author's trained-model contributions under [LICENSE](LICENSE), including
integration in other applications and commercial use. Third-party rights and
notices remain applicable; this grant does not relicense source datasets,
images, or separately supplied pretrained assets. See
[DATASET_SOURCES.md](DATASET_SOURCES.md) and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Copies of the selected model are also present in the model-development,
calibration, and benchmark folders. Use the identity and SHA-256 rather than
the filename alone to identify a copy. Other research candidates have distinct
hashes and are not interchangeable with this selected asset.

## Intended use and limits

Offline recognition of **one Indonesian Rupiah banknote at a time**, positioned
inside the Android camera ROI. The research covers 2016 and 2022 emission-year
banknotes; emission year and front/back side are not output classes.

The model is an image classifier. It does not locate multiple banknotes,
authenticate currency, read serial numbers, recognize coins, or keep a count
of physical banknotes. Repeated frame predictions must not be summed as if
they were different banknotes.

The research provides technical evaluation on two Android devices. It does
not establish usability or accessibility through direct trials with blind or
visually impaired participants. Community testing is an intended next step.

## Tensor contract and preprocessing

| Item | Contract |
|---|---|
| Input shape | `[1, 224, 224, 3]` (NHWC) |
| Input dtype | `float32` |
| External color/range | RGB values in `[0, 255]` |
| Resize | Bilinear, half-pixel sampling, no antialias |
| Internal normalization | Embedded model preprocessing (`x / 127.5 - 1`) |
| Output shape/dtype | `[1, 8]`, `float32` |
| Output semantics | Softmax class probabilities |

Do not divide the input by 255, apply external `[-1, 1]` normalization, or apply
softmax to the output again. Dynamic-range quantization does not make this
model's input/output tensors INT8. Keep the class order:

| Index | Label |
|---:|---|
| 0 | `1000` |
| 1 | `2000` |
| 2 | `5000` |
| 3 | `10000` |
| 4 | `20000` |
| 5 | `50000` |
| 6 | `100000` |
| 7 | `nonuang` |

The Android application converts ROI YUV data using limited-range BT.601,
checks luminance and sharpness, resizes eligible images, and applies prediction
rejection and temporal averaging. Copying only `model.tflite` without preserving
the tensor contract and class order can produce incorrect integration.

Authoritative asset files:

- [Tensor contract](implementasi_android/app/src/main/assets/model/tensor_contract.json).
- [Class names](implementasi_android/app/src/main/assets/model/class_names.json).
- [Model identity](implementasi_android/app/src/main/assets/model/model_identity.json).
- [Asset integrity](implementasi_android/app/src/main/assets/model/asset_integrity.json).
- [Operational configuration](implementasi_android/app/src/main/assets/app_config.json).

## Data and training

The starting backbone uses ImageNet-pretrained weights loaded by
`tf.keras.applications.MobileNetV3Small`, with `include_top=False`, `alpha=1.0`,
`minimalistic=False`, and `include_preprocessing=True`. The project adds global
average pooling, dropout of 0.20, and an eight-class softmax head; it trains the
head and fine-tunes selected upper backbone layers before TFLite conversion.

The prepared dataset contains 43,766 samples: 35,012 training, 4,378 validation,
and 4,376 testing samples. Known crops from the same banknote source image stay
in one partition. Exact deduplication and source-image grouping do not prove
the absence of all visually similar or related images across public datasets.
Source versions and processing changes are documented in
[DATASET_SOURCES.md](DATASET_SOURCES.md).

## Evaluation

The repository's [held-out test metrics](pengembangan_model/07_compare/test/metrics_summary.csv)
report the following for `dynamic_range`:

| Metric | Value |
|---|---:|
| Accuracy | 0.9552102376599635 (95.52%) |
| Macro F1 | 0.9524515781271854 |
| Macro precision | 0.9543446096548656 |
| Macro recall | 0.9527061145342226 |

These values match the rounded model results in the final 2026 thesis. The
selection-stage metrics and Android benchmark timings in `07_compare` have a
different role; they should not be presented as new held-out or user-study
measurements.

The thesis reports 294 correct accepted denominations and 98 rejections in
392 banknote trials, no wrong denomination announcements in those trials, and
rejection of all 72 non-banknote trials. Reported median application-level
latency is 794.34 ms on POCO X5 Pro 5G and 995.89 ms on Xiaomi Redmi 4X.
These are results for the reported technical protocol, not guarantees for other
devices or real-world transactions. Acceptance declined particularly in dim
lighting. The raw technical trials were not rerun when adding this card.

## Operational configuration and future changes

The current application configuration is `operational_config_locked`, revision
`calib-operational-001`: 3 analysis FPS, 4 CPU threads, confidence threshold
0.65, a 1,500 ms temporal window, a minimum of 3 eligible inference results,
and CLAHE disabled. The temporal component averages complete score vectors;
it is not a majority vote or a rule requiring every label in the window to
be identical. A score of 0.65 is a decision threshold, not a demonstrated 65%
probability of correctness.

Keep the existing model/configuration and integrity locks as the research
baseline. Record new community variants separately and rerun relevant checks
when changing the model, tensor contract, image pipeline, or decision logic.
See [CONTRIBUTING.md](CONTRIBUTING.md).
