"""Write a printable ChArUco sheet and the spec the calibration tool reads."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from board import BoardError, BoardSpec, write_board


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        destination = Path(args.output)
        spec = write_board(
            destination,
            BoardSpec(
                squares_x=args.squares_x,
                squares_y=args.squares_y,
                dictionary=args.dictionary,
                square_mm=args.square_mm,
                marker_mm=args.marker_mm,
            ),
        )
    except BoardError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"Wrote {destination}", flush=True)
    print(f"Wrote {destination.with_suffix('.yml')}", flush=True)
    print(
        "Print the PDF at actual size on US Letter. Do not scale to fit. "
        "The sheet is smaller than the paper so the printer does not shrink it. "
        f"Each square is {spec.square_mm:.1f} mm, marker {spec.marker_mm:.1f} mm.",
        flush=True,
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python main.py",
        description="Write a ChArUco sheet for lens calibration. Squares print at a known size on US Letter.",
    )
    parser.add_argument("--squares-x", type=int, default=5)
    parser.add_argument("--squares-y", type=int, default=7)
    parser.add_argument("--dictionary", default="DICT_4X4_50")
    parser.add_argument(
        "--square-mm",
        type=float,
        default=30.0,
        help="Square side in millimetres. Prints at this size on US Letter at actual size.",
    )
    parser.add_argument("--marker-mm", type=float, default=0, help="0 uses 75%% of the square")
    parser.add_argument(
        "--output",
        default="outputs/charuco-board.pdf",
        help="PDF to print. A yaml spec is written beside it.",
    )
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
