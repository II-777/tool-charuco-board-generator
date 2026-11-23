# ChArUco board

Writes the printed sheet that `tool-charuco-camera-calibration` reads. Each square is 30 mm. The page is smaller than US Letter on purpose: a full-page PDF gets shrunk into the printer's margins.

![ChArUco board](assets/charuco-board.png)

```bash
uv sync
uv run python main.py
```

That writes `outputs/charuco-board.pdf` and `outputs/charuco-board.yml`. Print the PDF at **actual size** on letter paper. Do not scale to fit. Blank paper around the sheet is expected. The line on the sheet is 100 mm. If that line is not 100 mm, the squares are not 30 mm.

Pass `outputs/charuco-board.yml` to the calibration tool with `--spec`. The square count, dictionary, and millimetre sizes in that file are the board the camera must be shown.
