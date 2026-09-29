#!/usr/bin/env python3
"""Human review/correction GUI for nominal ROI samples.

Controls
A : accept displayed quadrilateral
R : redraw manually (click 4 banknote corners, then ENTER)
T : mark SOURCE_TRUNCATED
S : skip / leave pending
B : previous sample
Q or ESC : save and quit

The information header is rendered OUTSIDE the source image so it never
covers banknote pixels. Manual clicks are converted back into original-image
coordinates before being stored.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np
import pandas as pd


HEADER_H = 54


def order_quad(pts):
    pts = np.asarray(
        pts,
        dtype=np.float32
    ).reshape(4, 2)

    c = pts.mean(axis=0)

    ang = np.arctan2(
        pts[:, 1] - c[1],
        pts[:, 0] - c[0]
    )

    pts = pts[
        np.argsort(ang)
    ]

    i = int(
        np.argmin(
            pts.sum(axis=1)
        )
    )

    pts = np.roll(
        pts,
        -i,
        axis=0
    )

    if cv2.contourArea(
        pts.reshape(-1, 1, 2),
        oriented=True
    ) < 0:

        pts = np.array(
            [
                pts[0],
                pts[3],
                pts[2],
                pts[1]
            ],
            dtype=np.float32
        )

    return pts


def get_quad(row):
    vals = []

    for i in range(1, 5):
        vals.extend([
            row[f"p{i}_x"],
            row[f"p{i}_y"]
        ])

    arr = np.asarray(
        vals,
        dtype=float
    )

    if np.isnan(arr).any():
        return None

    return arr.reshape(
        4,
        2
    ).astype(
        np.float32
    )


def set_quad(
    df,
    idx,
    quad
):
    quad = order_quad(
        quad
    )

    for i, (x, y) in enumerate(
        quad,
        start=1
    ):
        df.at[
            idx,
            f"p{i}_x"
        ] = float(x)

        df.at[
            idx,
            f"p{i}_y"
        ] = float(y)


def normalize_dataframe_types(df):
    string_columns = [
        "device",
        "sample_id",
        "class_label",
        "relative_rgb_path",
        "review_image_path",
        "review_status",
        "review_note",
    ]

    for column in string_columns:
        if column not in df.columns:
            continue

        if column == "review_status":
            df[column] = (
                df[column]
                .fillna("PENDING")
                .astype("string")
            )

            df.loc[
                df[column]
                .str
                .strip()
                .eq(""),
                column
            ] = "PENDING"

        else:
            df[column] = (
                df[column]
                .fillna("")
                .astype("string")
            )

    return df


def load_annotations(path):
    df = pd.read_csv(
        path,
        dtype={
            "class_label": str
        }
    )

    return normalize_dataframe_types(
        df
    )


def save_annotations(
    df,
    path
):
    df.to_csv(
        path,
        index=False
    )


def draw_quad(
    image,
    quad,
    color=(0, 255, 255)
):
    if quad is None:
        return

    points = (
        np.round(quad)
        .astype(int)
    )

    cv2.polylines(
        image,
        [
            points.reshape(
                -1,
                1,
                2
            )
        ],
        True,
        color,
        2,
        cv2.LINE_AA
    )

    for i, (x, y) in enumerate(
        points,
        start=1
    ):
        cv2.circle(
            image,
            (x, y),
            4,
            (0, 0, 255),
            -1
        )

        cv2.putText(
            image,
            str(i),
            (x + 5, y - 5),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 0, 255),
            1,
            cv2.LINE_AA
        )


def draw_clicks(
    image,
    clicks
):
    if not clicks:
        return

    for i, (x, y) in enumerate(
        clicks,
        start=1
    ):
        cv2.circle(
            image,
            (x, y),
            5,
            (255, 0, 255),
            -1
        )

        cv2.putText(
            image,
            str(i),
            (x + 5, y - 5),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 0, 255),
            1,
            cv2.LINE_AA
        )


def render(
    img,
    row,
    quad,
    clicks=None
):
    """
    Important:
    - quad/click coordinates stay in ORIGINAL image coordinates.
    - HEADER_H pixels are added only for display.
    - source image pixels are never covered by the information header.
    """

    image_view = img.copy()

    draw_quad(
        image_view,
        quad
    )

    draw_clicks(
        image_view,
        clicks
    )

    h, w = image_view.shape[:2]

    canvas = np.zeros(
        (
            h + HEADER_H,
            w,
            3
        ),
        dtype=np.uint8
    )

    canvas[
        HEADER_H:HEADER_H + h,
        0:w
    ] = image_view

    top = (
        f"{row['device']} | "
        f"{row['sample_id']} | "
        f"{row['class_label']} | "
        f"{int(row['distance_cm'])}cm | "
        f"{row['review_status']}"
    )

    help_text = (
        "A accept | R redraw | "
        "T truncated | S skip | "
        "B back | Q quit"
    )

    cv2.putText(
        canvas,
        top,
        (5, 19),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.43,
        (255, 255, 255),
        1,
        cv2.LINE_AA
    )

    cv2.putText(
        canvas,
        help_text,
        (5, 42),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.38,
        (220, 220, 220),
        1,
        cv2.LINE_AA
    )

    return canvas


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--work-dir",
        required=True,
        type=Path
    )

    args = parser.parse_args()

    work_dir = args.work_dir

    reviewed_csv = (
        work_dir /
        "roi_object_annotations_reviewed.csv"
    )

    draft_csv = (
        work_dir /
        "roi_object_annotations_draft.csv"
    )

    if reviewed_csv.exists():

        df = load_annotations(
            reviewed_csv
        )

        dst = reviewed_csv

    else:

        if not draft_csv.exists():
            raise FileNotFoundError(
                f"Draft CSV tidak ditemukan: {draft_csv}"
            )

        df = load_annotations(
            draft_csv
        )

        dst = reviewed_csv

        save_annotations(
            df,
            dst
        )

    pending = list(
        df.index[
            df[
                "review_status"
            ].eq(
                "PENDING"
            )
        ]
    )

    if not pending:
        print(
            "Tidak ada sampel PENDING."
        )
        return

    pos = 0

    window_name = (
        "ROI boundary review"
    )

    cv2.namedWindow(
        window_name,
        cv2.WINDOW_NORMAL
    )

    while 0 <= pos < len(pending):

        idx = pending[pos]

        row = df.loc[idx]

        image_path = (
            work_dir /
            row["review_image_path"]
        )

        img = cv2.imread(
            str(image_path)
        )

        if img is None:
            raise RuntimeError(
                "Gagal membaca gambar: "
                f"{image_path}"
            )

        quad = get_quad(
            row
        )

        cv2.imshow(
            window_name,
            render(
                img,
                row,
                quad
            )
        )

        key = (
            cv2.waitKey(0)
            & 0xFF
        )

        if key in (
            ord("q"),
            27
        ):
            break

        elif key == ord("a"):

            if quad is None:
                print(
                    "Tidak ada proposal "
                    "quadrilateral. "
                    "Gunakan R atau T."
                )
                continue

            df.at[
                idx,
                "review_status"
            ] = "ACCEPTED_AUTO"

            df.at[
                idx,
                "review_note"
            ] = (
                "human accepted "
                "automatic quadrilateral"
            )

            save_annotations(
                df,
                dst
            )

            pos += 1

        elif key == ord("t"):

            df.at[
                idx,
                "review_status"
            ] = "SOURCE_TRUNCATED"

            df.at[
                idx,
                "review_note"
            ] = (
                "banknote not fully "
                "visible in source frame"
            )

            save_annotations(
                df,
                dst
            )

            pos += 1

        elif key == ord("s"):

            pos += 1

        elif key == ord("b"):

            pos = max(
                0,
                pos - 1
            )

        elif key == ord("r"):

            clicks = []

            def mouse_callback(
                event,
                x,
                y,
                flags,
                param
            ):
                # Header berada di luar koordinat
                # gambar asli. Klik pada header
                # tidak dianggap sebagai anotasi.
                if y < HEADER_H:
                    return

                image_x = x
                image_y = (
                    y - HEADER_H
                )

                h, w = img.shape[:2]

                if not (
                    0 <= image_x < w
                    and
                    0 <= image_y < h
                ):
                    return

                if (
                    event ==
                    cv2.EVENT_LBUTTONDOWN
                    and
                    len(clicks) < 4
                ):
                    clicks.append(
                        (
                            image_x,
                            image_y
                        )
                    )

                    cv2.imshow(
                        window_name,
                        render(
                            img,
                            row,
                            quad,
                            clicks
                        )
                    )

                elif (
                    event ==
                    cv2.EVENT_RBUTTONDOWN
                    and
                    clicks
                ):
                    clicks.pop()

                    cv2.imshow(
                        window_name,
                        render(
                            img,
                            row,
                            quad,
                            clicks
                        )
                    )

            cv2.setMouseCallback(
                window_name,
                mouse_callback
            )

            cv2.imshow(
                window_name,
                render(
                    img,
                    row,
                    quad,
                    clicks
                )
            )

            while True:

                redraw_key = (
                    cv2.waitKey(0)
                    & 0xFF
                )

                if redraw_key in (
                    27,
                    ord("q")
                ):
                    break

                if (
                    redraw_key in (
                        13,
                        10
                    )
                    and
                    len(clicks) == 4
                ):
                    set_quad(
                        df,
                        idx,
                        np.asarray(
                            clicks,
                            dtype=np.float32
                        )
                    )

                    df.at[
                        idx,
                        "review_status"
                    ] = (
                        "ACCEPTED_MANUAL"
                    )

                    df.at[
                        idx,
                        "review_note"
                    ] = (
                        "human redrawn "
                        "quadrilateral"
                    )

                    save_annotations(
                        df,
                        dst
                    )

                    pos += 1

                    break

            cv2.setMouseCallback(
                window_name,
                lambda *args: None
            )

    cv2.destroyAllWindows()

    df = load_annotations(
        dst
    )

    print()
    print(
        "=== REVIEW STATUS ==="
    )

    print(
        df[
            "review_status"
        ]
        .value_counts(
            dropna=False
        )
        .to_string()
    )

    print()
    print(
        f"Saved: {dst}"
    )


if __name__ == "__main__":
    main()