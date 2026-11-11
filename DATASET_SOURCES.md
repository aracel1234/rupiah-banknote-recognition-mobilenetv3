# Dataset sources and attribution

## Scope and evidence

The model was trained using ten Rupiah banknote sources from Roboflow Universe
and non-banknote candidates from Microsoft COCO 2017 obtained through Kaggle.
The table preserves the source IDs and versions in the research acquisition
record: [source_registry.csv](persiapan_data/01_audit/source_registry.csv).

The 2026 thesis, Section 5.1.1 and Appendix A, records CC BY 4.0 for all ten
Roboflow sources. The author also confirmed this licensing record on
2026-11-11. The acquisition dates below are historical research dates, not a
claim that the current website contents are identical to the downloaded data.

During the repository review on 2026-11-11, the current project overview pages
for ds5, ds7, ds8, and ds9 could be read and displayed CC BY 4.0. The other six
pages could not be independently read during that review. Version-specific
license files/screenshots from the original downloads are not archived in this
repository. A recorded license is not a per-image ownership audit.

The repository's Apache-2.0 grant does **not** relicense third-party datasets,
images, annotations, or their modified copies.

## Banknote sources

All ten sources were acquired in COCO annotation format on **2026-04-16**.
Counts are source-image counts from the research archive, before classification
crop extraction, filtering, deduplication, and dataset splitting.

| ID | Creator / source workspace | Project | Version | Source images | Recorded license |
|---|---|---|---|---:|---|
| ds1 | agil-skripsi-2 | [5 - rotasi dan crop 20, 50, 80](https://universe.roboflow.com/agil-skripsi-2/5-rotasi-dan-crop-20-50-80) | V6 | 2,157 | CC BY 4.0 |
| ds2 | final-1-4a4rh | [1rb](https://universe.roboflow.com/final-1-4a4rh/1rb/dataset/1) | V1 | 1,000 | CC BY 4.0 |
| ds3 | final-xkyim | [20rb](https://universe.roboflow.com/final-xkyim/20rb-uxlxm) | V1 | 921 | CC BY 4.0 |
| ds4 | currency-yimpm | [deteksiuang](https://universe.roboflow.com/currency-yimpm/deteksiuang-xllap) | V13 | 8,601 | CC BY 4.0 |
| ds5 | Nur Hasanah / nur-hasanah-xhvuu | [money](https://universe.roboflow.com/nur-hasanah-xhvuu/money-chuen) | V2 | 8,396 | CC BY 4.0 |
| ds6 | raplong | [Rupiah](https://universe.roboflow.com/raplong/rupiah-nkyzq) | V2 | 3,420 | CC BY 4.0 |
| ds7 | tugas akhir / tugas-akhir-afuhz | [rupiah](https://universe.roboflow.com/tugas-akhir-afuhz/rupiah-m55hl) | V2 | 1,788 | CC BY 4.0 |
| ds8 | myta | [Rupiah Detector](https://universe.roboflow.com/myta/rupiah-detector) | V3 | 2,729 | CC BY 4.0 |
| ds9 | Teamkito Labs / teamkito-labs | [Uang](https://universe.roboflow.com/teamkito-labs/uang-wfprv) | V3 | 9,780 | CC BY 4.0 |
| ds10 | ramzi-guyzk | [Uang Rupiah](https://universe.roboflow.com/ramzi-guyzk/uang-rupiah-li6sa) | V2 | 1,552 | CC BY 4.0 |
| **Total** | | | | **40,344** | |

License: [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/),
with the [full legal code](https://creativecommons.org/licenses/by/4.0/legalcode).
It permits sharing and adaptation, including commercial use, subject to its
terms. Preserve supplied attribution and notices, link the source and license,
and indicate changes. Attribution must not imply the original creator endorses
this project.

## Non-banknote source (ds11)

- Source: [Microsoft COCO 2017 (Common Objects in Context)](https://www.kaggle.com/datasets/clkmuhammed/microsoft-coco-2017-common-objects-in-context).
- Kaggle uploader: **Muhammed Çelik**, account `clkmuhammed`.
- Version: **Kaggle Snapshot**, accessed **2026-05-22**.
- Original collection: the **COCO Consortium** and the respective image creators.
- Local research label: `nonuang`; this is not a single original COCO category.

The thesis reconciles 8,002 candidate images in the acquisition list with 8,000
files recorded in the initial audit. The existing registry records the latter
count; the two-image difference has not been assigned an unsupported cause.
The final non-banknote classification subset contains 5,184 samples.

COCO's [Terms of Use](https://cocodataset.org/dataset/termsofuse.htm) distinguish
annotations from images: annotations and the website are CC BY 4.0, while COCO
does not own the copyright of all images and refers users to the original
Flickr terms. The label `COCO annotations CC BY 4.0` in the registry must not be
interpreted as a blanket CC BY 4.0 license for every photograph. Preserve the
original image ID, creator/source URL, license ID, and applicable notices when
obtaining or redistributing these images.

## Transformations used in this research

Banknote data underwent label normalization, COCO metadata merging, bounding-box
crop extraction into RGB PNG images, visual exclusion of unsuitable samples,
exact pixel-level deduplication, and group-aware train/validation/test splitting.
Non-banknote candidates were selected and assigned the local class `nonuang`.
Images are resized to 224 x 224 when loaded for model development or inference;
crop extraction itself does not resize the images.

These transformations do not make the third-party images original works of the
project author or remove their source attribution. Source IDs such as `ds1`
remain important for tracing samples back to the acquisition record.

## Repository samples and further data contributions

Source photographs, extracted crops, and Android reference-test images remain
subject to their source terms even when only a few examples are included.
This includes the third-party image and annotation samples under
`persiapan_data/` and reference images under
`implementasi_android/app/src/androidTest/assets/reference/`.

For each new data contribution, record its creator, source, permission/license,
version or acquisition date, and processing steps. Keep private or unlicensed
material out of public pull requests. Preserve the original license evidence
with new downloads and add version-specific evidence to this document when
the historical files become available.

Licensing of project-authored model contributions is described in
[MODEL_CARD.md](MODEL_CARD.md); this document does not assert that every dataset
license automatically becomes the license of trained weights.
