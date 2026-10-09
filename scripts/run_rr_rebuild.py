"""Rebuild the CP reward-rate matrices by executing notebooks/Make_RRMatrix.ipynb.

Sets COMPUTE_CP = True inside the kernel only (the saved notebook keeps
COMPUTE_CP = False, so re-running it casually reloads RRMats.mat instead of
spending ~6 h re-simulating). Cell outputs are written back into the notebook
when the run finishes; progress (one line per completed cell) goes to stdout.

Run from the project root, detached so it survives the terminal closing:

    nohup uv run python scripts/run_rr_rebuild.py > data/processed/RRMats_rebuild.log 2>&1 &
"""

import json
import time
from pathlib import Path

import nbformat
from nbclient import NotebookClient

NOTEBOOK = Path("notebooks/Make_RRMatrix.ipynb")
PARAMS_CELL = 3  # cell that defines COMPUTE_CP = False


def log(msg):
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}", flush=True)


def main():
    nb = nbformat.read(NOTEBOOK, as_version=4)
    code_idx = [i for i, c in enumerate(nb.cells) if c.cell_type == "code"]
    run = nbformat.v4.new_notebook()
    run.metadata = nb.metadata
    run.cells = [nb.cells[i] for i in code_idx]
    k = code_idx.index(PARAMS_CELL) + 1
    run.cells.insert(k, nbformat.v4.new_code_cell("COMPUTE_CP = True  # injected by scripts/run_rr_rebuild.py"))

    def on_executed(cell, cell_index, **_):  # fires after the execute reply (on_cell_complete fires at send)
        first = cell.source.strip().splitlines()[0][:70] if cell.source.strip() else ""
        log(f"finished cell {cell_index + 1}/{len(run.cells)}: {first}")

    log(f"start: {NOTEBOOK}")
    t0 = time.time()
    NotebookClient(run, timeout=None, kernel_name="python3", on_cell_executed=on_executed,
                   resources={"metadata": {"path": str(NOTEBOOK.parent)}}).execute()

    del run.cells[k]
    for i, cell in zip(code_idx, run.cells):
        nb.cells[i] = cell
    with open(NOTEBOOK, "w", encoding="utf-8") as f:
        json.dump(json.loads(nbformat.writes(nb)), f, indent=1, ensure_ascii=False)
        f.write("\n")
    log(f"done in {(time.time() - t0) / 3600:.2f} h; outputs written to {NOTEBOOK}")


if __name__ == "__main__":
    main()
