# Third-party software and asset notices

The project's Apache-2.0 grant covers the author's original contributions.
Dependencies and pretrained/data assets retain their own terms. This document
identifies the declared components; it is not a complete license inventory of
every transitive or native component in a future APK.

## Android runtime and tests

The main app declares these components in
[app/build.gradle.kts](implementasi_android/app/build.gradle.kts):

| Component | Declared version | Upstream / license |
|---|---|---|
| AndroidX Activity KTX | 1.9.3 | [AndroidX](https://github.com/androidx/androidx), [Apache-2.0](https://github.com/androidx/androidx/blob/androidx-main/LICENSE.txt) |
| AndroidX Core KTX | 1.13.1 | AndroidX, Apache-2.0 |
| CameraX core, camera2, lifecycle, view | 1.4.2 | AndroidX, Apache-2.0 |
| TensorFlow Lite | 2.17.0 | [TensorFlow](https://github.com/tensorflow/tensorflow/tree/v2.17.0), [upstream license and included notices](LICENSES/TensorFlow-2.17.0.txt) |
| AndroidX Test core / runner | 1.6.1 / 1.6.2 | [AndroidX Test](https://github.com/android/android-test), Apache-2.0 |
| AndroidX Test JUnit extension | 1.2.1 | AndroidX Test, Apache-2.0 |

The benchmark app additionally declares AndroidX AppCompat 1.7.0 and
TensorFlow Lite 2.17.0. Kotlin is used for Android implementation; its
[license](https://github.com/JetBrains/kotlin/blob/master/license/LICENSE.txt)
is Apache-2.0. Individual bundled files and transitive components may carry
additional notices.

TensorFlow Lite executes the research model with CPU XNNPACK enabled. TensorFlow
and native dependencies may include separately licensed components. The copy
in `LICENSES/TensorFlow-2.17.0.txt` preserves the license file distributed in
TensorFlow's v2.17.0 source tag; it does not replace notices supplied inside
the resolved runtime artifacts.

## Model development and pretrained assets

The training scripts use TensorFlow/Keras, including ImageNet-pretrained
MobileNetV3-Small weights loaded through Keras Applications. The starting
backbone is not claimed as an architecture or pretrained asset created by this
project's author. See [Keras Applications](https://keras.io/api/applications/)
and [the model-building script](scripts/pengembangan_model/02_build_model.py).

Preserve the applicable notices for the exact TensorFlow/Keras distribution
and pretrained artifacts used. The project's grant covers the author's model
contributions and does not override independently applicable upstream terms.
The ImageNet training-image collection and the distributed pretrained weights
are distinct materials; this repository does not redistribute the ImageNet
image collection.

## Datasets, annotations, and sample photographs

The ten Roboflow sources, their creators, versions, processing changes, and
recorded CC BY 4.0 licenses are listed in
[DATASET_SOURCES.md](DATASET_SOURCES.md). COCO annotations and COCO photographs
have separate licensing considerations as described there. The root software
license does not change those terms.

## Binary distributions

When preparing an APK for community distribution, collect the notices from
the resolved dependencies and native libraries for that build and package
readable copies with the app or accompanying distribution materials. Include
the project's `LICENSE` and relevant `NOTICE` information and preserve the
applicable third-party copyright/license notices. Keep an accessible About or
Licenses page if exposing these notices in the application.

This documentation change does not publish a new APK or claim that existing
tracked benchmark APKs have received a completed transitive-license review.
