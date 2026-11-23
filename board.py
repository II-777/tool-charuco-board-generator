"""Printable ChArUco sheet."""

from __future__ import annotations

import math
import zlib
from dataclasses import dataclass, replace
from pathlib import Path

import cv2
import numpy as np
import yaml


class BoardError(Exception):
    """A problem the operator can correct before printing."""

# 10 px/mm makes a US Letter page and a 30 mm square both an integer number of pixels.
PX_PER_MM = 10
DPI = 254
LETTER_W_MM = 215.9
LETTER_H_MM = 279.4
# A PDF that is exactly letter size gets scaled into the unprintable margin (100 mm prints as ~96 mm).
# The sheet is smaller than the paper and is centered, so a 100% print keeps true millimetres.
PRINTER_MARGIN_MM = 12.7
PAD_MM = 6.0
DEFAULT_SQUARE_MM = 30.0
SCALE_BAR_MM = 100.0

DICTIONARIES: dict[str, int] = {
    "DICT_4X4_50": cv2.aruco.DICT_4X4_50,
    "DICT_4X4_100": cv2.aruco.DICT_4X4_100,
    "DICT_5X5_50": cv2.aruco.DICT_5X5_50,
    "DICT_5X5_100": cv2.aruco.DICT_5X5_100,
    "DICT_6X6_250": cv2.aruco.DICT_6X6_250,
}


@dataclass(frozen=True)
class BoardSpec:
    squares_x: int
    squares_y: int
    dictionary: str
    square_mm: float
    marker_mm: float

    @property
    def corner_count(self) -> int:
        return (self.squares_x - 1) * (self.squares_y - 1)


@dataclass(frozen=True)
class CharucoHit:
    object_points: np.ndarray
    image_points: np.ndarray
    corners: np.ndarray
    ids: np.ndarray


def resolve_spec(spec: BoardSpec) -> BoardSpec:
    if spec.squares_x < 3 or spec.squares_y < 3:
        raise BoardError("the board needs at least 3 squares along each side")
    if spec.dictionary not in DICTIONARIES:
        known = ", ".join(sorted(DICTIONARIES))
        raise BoardError(f"unknown dictionary {spec.dictionary}. Choose one of: {known}")
    square = spec.square_mm
    marker = spec.marker_mm
    if square <= 0:
        square = DEFAULT_SQUARE_MM
    if square <= 5:
        raise BoardError("square size must be larger than 5 mm")
    if marker <= 0:
        marker = math.floor(square * 0.75 * 10) / 10
    if marker <= 0 or marker >= square:
        raise BoardError("marker size must be greater than 0 and smaller than the square")
    resolved = replace(spec, square_mm=square, marker_mm=marker)
    _require_dictionary_capacity(resolved)
    _require_page_fit(resolved)
    return resolved


def make_cv_board(spec: BoardSpec) -> cv2.aruco.CharucoBoard:
    dictionary = cv2.aruco.getPredefinedDictionary(DICTIONARIES[spec.dictionary])
    return cv2.aruco.CharucoBoard(
        (spec.squares_x, spec.squares_y),
        spec.square_mm / 1000.0,
        spec.marker_mm / 1000.0,
        dictionary,
    )


def make_detector(board: cv2.aruco.CharucoBoard) -> cv2.aruco.CharucoDetector:
    return cv2.aruco.CharucoDetector(board)


def render_pattern(spec: BoardSpec) -> np.ndarray:
    square_px = mm_to_px(spec.square_mm)
    size = (square_px * spec.squares_x, square_px * spec.squares_y)
    pattern = make_cv_board(spec).generateImage(size, marginSize=0, borderBits=1)
    if pattern is None or pattern.size == 0:
        raise BoardError("OpenCV did not draw the ChArUco board")
    return pattern


def write_board(pdf_path, spec: BoardSpec) -> BoardSpec:
    destination = Path(pdf_path)
    resolved = resolve_spec(spec)
    pattern = render_pattern(resolved)
    destination.parent.mkdir(parents=True, exist_ok=True)
    _write_pdf(destination, pattern, resolved, sheet_layout(resolved))
    _write_spec(destination.with_suffix(".yml"), resolved)
    return resolved


def _write_spec(path: Path, spec: BoardSpec) -> None:
    body = yaml.safe_dump(
        {
            "dictionary": spec.dictionary,
            "squares_x": spec.squares_x,
            "squares_y": spec.squares_y,
            "square_mm": spec.square_mm,
            "marker_mm": spec.marker_mm,
        },
        sort_keys=False,
    )
    path.write_text(
        "# Printed ChArUco sheet. Pass this file to tool-charuco-camera-calibration with --spec.\n" + body,
        encoding="utf-8",
    )


def detect_charuco(image: np.ndarray, board: cv2.aruco.CharucoBoard, detector: cv2.aruco.CharucoDetector) -> CharucoHit | None:
    detected = detector.detectBoard(image)
    if detected is None or len(detected) < 2:
        return None
    corners, ids = detected[0], detected[1]
    if corners is None or ids is None or len(ids) < 4:
        return None
    try:
        matched = board.matchImagePoints(corners, ids)
    except cv2.error:
        return None
    if matched is None or len(matched) != 2:
        return None
    obj, img = matched
    if obj is None or img is None:
        return None
    object_points = np.asarray(obj, dtype=np.float64).reshape(-1, 3)
    image_points = np.asarray(img, dtype=np.float64).reshape(-1, 2)
    if len(object_points) < 4 or len(object_points) != len(image_points):
        return None
    draw_corners = np.asarray(corners, dtype=np.float32).reshape(-1, 1, 2)
    draw_ids = np.asarray(ids, dtype=np.int32).reshape(-1, 1)
    if len(draw_corners) != len(draw_ids):
        return None
    return CharucoHit(
        object_points=object_points,
        image_points=image_points,
        corners=draw_corners,
        ids=draw_ids,
    )


def mm_to_px(mm: float, dpi: int = DPI) -> int:
    return int(round(mm * PX_PER_MM)) if dpi == DPI else int(round(mm * dpi / 25.4))


def mm_to_pt(mm: float) -> float:
    """PDF points. 30 mm is 30 / 25.4 * 72, so a 100% print is exactly 30 mm."""
    return mm * 72.0 / 25.4


@dataclass(frozen=True)
class SheetLayout:
    page_w_mm: float
    page_h_mm: float
    board_x_mm: float
    board_top_mm: float
    board_w_mm: float
    board_h_mm: float
    bar_x_mm: float
    bar_y_mm: float
    bar_mm: float
    text_mm: tuple[float, float, float]


def sheet_layout(spec: BoardSpec) -> SheetLayout:
    board_w = spec.square_mm * spec.squares_x
    board_h = spec.square_mm * spec.squares_y
    text_mm = (7.5, 11.5, 15.5)
    bar_y = 21.0
    board_top = 34.5
    instruction, detail, measure = _caption_lines(spec)
    content_w = max(
        board_w,
        SCALE_BAR_MM,
        _text_width_mm(instruction, 12),
        _text_width_mm(detail, 9),
        _text_width_mm(measure, 9),
    )
    page_w = content_w + 2 * PAD_MM
    page_h = board_top + board_h + PAD_MM
    limit_w = LETTER_W_MM - 2 * PRINTER_MARGIN_MM
    limit_h = LETTER_H_MM - 2 * PRINTER_MARGIN_MM
    if page_w > limit_w or page_h > limit_h:
        raise BoardError("board does not fit on US Letter; use fewer squares or a smaller --square-mm")
    return SheetLayout(
        page_w_mm=page_w,
        page_h_mm=page_h,
        board_x_mm=(page_w - board_w) / 2.0,
        board_top_mm=board_top,
        board_w_mm=board_w,
        board_h_mm=board_h,
        bar_x_mm=(page_w - SCALE_BAR_MM) / 2.0,
        bar_y_mm=bar_y,
        bar_mm=SCALE_BAR_MM,
        text_mm=text_mm,
    )


def _require_dictionary_capacity(spec: BoardSpec) -> None:
    dictionary = cv2.aruco.getPredefinedDictionary(DICTIONARIES[spec.dictionary])
    board = make_cv_board(spec)
    marker_ids = board.getIds()
    capacity = int(dictionary.bytesList.shape[0])
    if len(marker_ids) > capacity:
        raise BoardError(
            f"{spec.dictionary} has {capacity} markers and this board needs {len(marker_ids)}. Use a larger dictionary."
        )


def _require_page_fit(spec: BoardSpec) -> None:
    sheet_layout(spec)


def _caption_lines(spec: BoardSpec) -> tuple[str, str, str]:
    return (
        "Print at actual size. Do not scale to fit.",
        (
            f"{spec.dictionary}   {spec.squares_x}x{spec.squares_y} squares"
            f"   square {spec.square_mm:.1f} mm   marker {spec.marker_mm:.1f} mm"
        ),
        f"One black square is {spec.square_mm:.1f} mm. The bar is {SCALE_BAR_MM:.0f} mm.",
    )


def _write_pdf(pdf_path, pattern: np.ndarray, spec: BoardSpec, layout: SheetLayout) -> None:
    gray = pattern if pattern.ndim == 2 else cv2.cvtColor(pattern, cv2.COLOR_BGR2GRAY)
    gray = np.ascontiguousarray(gray, dtype=np.uint8)
    height, width = gray.shape
    if width != mm_to_px(spec.square_mm) * spec.squares_x or height != mm_to_px(spec.square_mm) * spec.squares_y:
        raise BoardError("the board squares are not the same size")
    compressed = zlib.compress(gray.tobytes(), 9)
    page_w_pt = mm_to_pt(layout.page_w_mm)
    page_h_pt = mm_to_pt(layout.page_h_mm)
    square_pt = mm_to_pt(spec.square_mm)
    board_w = square_pt * spec.squares_x
    board_h = square_pt * spec.squares_y
    board_x = mm_to_pt(layout.board_x_mm)
    board_y = mm_to_pt(layout.page_h_mm - layout.board_top_mm - layout.board_h_mm)
    bar_pt = mm_to_pt(layout.bar_mm)
    bar_x = mm_to_pt(layout.bar_x_mm)
    bar_y = mm_to_pt(layout.page_h_mm - layout.bar_y_mm)
    tick = mm_to_pt(2.0)
    instruction, detail, measure = _caption_lines(spec)
    contents = "\n".join(
        [
            "q",
            f"{board_w:.4f} 0 0 {board_h:.4f} {board_x:.4f} {board_y:.4f} cm",
            "/Im0 Do",
            "Q",
            "1 w",
            "0 0 0 RG",
            f"{bar_x:.4f} {bar_y:.4f} m {bar_x + bar_pt:.4f} {bar_y:.4f} l S",
            f"{bar_x:.4f} {bar_y - tick:.4f} m {bar_x:.4f} {bar_y + tick:.4f} l S",
            f"{bar_x + bar_pt:.4f} {bar_y - tick:.4f} m {bar_x + bar_pt:.4f} {bar_y + tick:.4f} l S",
            "BT",
            *_pdf_line(instruction, 12, mm_to_pt(layout.page_h_mm - layout.text_mm[0]), page_w_pt),
            *_pdf_line(detail, 9, mm_to_pt(layout.page_h_mm - layout.text_mm[1]), page_w_pt),
            *_pdf_line(measure, 9, mm_to_pt(layout.page_h_mm - layout.text_mm[2]), page_w_pt),
            *_pdf_line(f"{layout.bar_mm:.0f} mm", 9, bar_y - mm_to_pt(5.5), page_w_pt),
            "ET",
        ]
    ).encode("ascii")
    image = (
        f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
        f"/ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode "
        f"/Length {len(compressed)} >>\nstream\n".encode("ascii")
        + compressed
        + b"\nendstream"
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R /ViewerPreferences << /PrintScaling /None >> >>",
        b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
        (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_w_pt:.4f} {page_h_pt:.4f}] "
            f"/Resources << /XObject << /Im0 4 0 R >> /Font << /F1 5 0 R >> >> "
            f"/Contents 6 0 R >>"
        ).encode("ascii"),
        image,
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(contents)} >>\nstream\n".encode("ascii") + contents + b"\nendstream",
    ]
    pdf_path.write_bytes(_build_pdf(objects))


def _text_width_mm(text: str, size: float) -> float:
    return _text_width(text, size) * 25.4 / 72.0


def _pdf_line(text: str, size: float, baseline: float, page_w_pt: float) -> list[str]:
    width = _text_width(text, size)
    x = (page_w_pt - width) / 2.0
    return [
        f"/F1 {size:.2f} Tf",
        f"1 0 0 1 {x:.2f} {baseline:.2f} Tm",
        f"({_pdf_escape(text)}) Tj",
    ]


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _text_width(text: str, size: float) -> float:
    return sum(_HELVETICA.get(char, 500) for char in text) * size / 1000.0


def _build_pdf(objects: list[bytes]) -> bytes:
    chunks = [b"%PDF-1.6\n%\xe2\xe3\xcf\xd3\n"]
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(sum(len(chunk) for chunk in chunks))
        chunks.append(f"{number} 0 obj\n".encode("ascii"))
        chunks.append(body)
        if not body.endswith(b"\n"):
            chunks.append(b"\n")
        chunks.append(b"endobj\n")
    xref_at = sum(len(chunk) for chunk in chunks)
    xref = [f"xref\n0 {len(objects) + 1}\n".encode("ascii"), b"0000000000 65535 f \n"]
    xref.extend(f"{offset:010d} 00000 n \n".encode("ascii") for offset in offsets)
    trailer = (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode("ascii")
    )
    return b"".join(chunks + xref + [trailer])


# Helvetica character widths in thousandths of an em. Used only to center the caption.
_HELVETICA = {
    " ": 278, "!": 278, '"': 355, "#": 556, "$": 556, "%": 889, "&": 667, "'": 191,
    "(": 333, ")": 333, "*": 389, "+": 584, ",": 278, "-": 333, ".": 278, "/": 278,
    "0": 556, "1": 556, "2": 556, "3": 556, "4": 556, "5": 556, "6": 556, "7": 556, "8": 556, "9": 556,
    ":": 278, ";": 278, "<": 584, "=": 584, ">": 584, "?": 556, "@": 1015,
    "A": 667, "B": 667, "C": 722, "D": 722, "E": 667, "F": 611, "G": 778, "H": 722, "I": 278, "J": 500,
    "K": 667, "L": 556, "M": 833, "N": 722, "O": 778, "P": 667, "Q": 778, "R": 722, "S": 667, "T": 611,
    "U": 722, "V": 667, "W": 944, "X": 667, "Y": 667, "Z": 611,
    "[": 278, "\\": 278, "]": 278, "^": 469, "_": 556, "`": 333,
    "a": 556, "b": 556, "c": 500, "d": 556, "e": 556, "f": 278, "g": 556, "h": 556, "i": 222, "j": 222,
    "k": 500, "l": 222, "m": 833, "n": 556, "o": 556, "p": 556, "q": 556, "r": 333, "s": 500, "t": 278,
    "u": 556, "v": 500, "w": 722, "x": 500, "y": 500, "z": 500,
    "{": 334, "|": 260, "}": 334, "~": 584,
}
