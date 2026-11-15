#!/usr/bin/env bash
# TerraPulse reproducible L40 training. Run this from a checked-out repository.
# Starts an SSH-independent worker; no server credentials are embedded.
set -Eeuo pipefail
umask 077

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="${TP_TRAIN_ROOT:-$HOME/castor-audit/landslide-scar-gpu-v2}"
LOG="$ROOT/logs/worker.log"
mkdir -p "$ROOT"/{logs,data,checkpoints,release}

if [[ "${TP_WORKER:-0}" != 1 ]]; then
  if command -v pgrep >/dev/null && pgrep -af "[t]rain_landslide_gpu_detached.sh" | grep -Fq "TP_WORKER=1"; then
    echo "[TerraPulse] An existing training runner may be active. Check $LOG"
  fi
  nohup setsid env TP_WORKER=1 TP_TRAIN_ROOT="$ROOT" bash "$REPO/scripts/train_landslide_gpu_detached.sh" \
    </dev/null >> "$LOG" 2>&1 &
  echo "[TerraPulse] Detached worker PID $!"
  echo "[TerraPulse] Log: $LOG"
  echo "[TerraPulse] Status: $ROOT/status.json"
  echo "[TerraPulse] Results: $ROOT/release/"
  echo "[TerraPulse] SSH can disconnect. A server reboot will still stop the job."
  exit 0
fi

exec 9>"$ROOT/runner.lock"
if ! flock -n 9; then
  echo "[TerraPulse] Existing worker holds the lock; not starting a duplicate."
  exit 0
fi

record() {
  /usr/bin/python3 - "$ROOT/status.json" "$1" "$2" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
path = Path(sys.argv[1])
tmp = path.with_suffix(".tmp")
tmp.write_text(json.dumps({
    "status": sys.argv[2],
    "detail": sys.argv[3],
    "updated_utc": datetime.now(timezone.utc).isoformat(),
}, indent=2) + "\n")
tmp.replace(path)
PY
}

fail() {
  local result=$?
  trap - ERR
  record failed "See $LOG; exited with status $result"
  echo "[TerraPulse] FAILED (code $result). Logs retained, previous model untouched."
  exit "$result"
}
trap fail ERR

echo "[TerraPulse] Worker started: $(date -u)"
echo "[TerraPulse] Repository: $REPO"
record running "Finding existing CUDA PyTorch environment"

# Prefer an already working GPU environment. If none exists, create an
# isolated environment. Never install into system Python.
PY=""
CANDIDATES=(
  "$HOME/castor-audit/l4s-spatial/venv/bin/python"
  "$HOME/castor-audit/landslide-spatial/venv/bin/python"
  "$HOME/castor-audit/l4s-env/bin/python"
  "$HOME/castor-gpu-env/bin/python"
  "/opt/spaceapps/bin/python"
)
while IFS= read -r path; do CANDIDATES+=("$path"); done < <(
  find "$HOME/castor-audit" -maxdepth 5 \( -name python -o -name python3 \) \
    -path '*/bin/*' -print 2>/dev/null | head -35 || true
)
for p in "${CANDIDATES[@]}"; do
  [[ -x "$p" ]] || continue
  if "$p" -c 'import torch, h5py, requests, sklearn, onnx, onnxruntime; assert torch.cuda.is_available()' >/dev/null 2>&1; then
    PY="$p"
    echo "[TerraPulse] Using existing GPU environment: $PY"
    break
  fi
done

if [[ -z "$PY" ]]; then
  PY="$ROOT/venv/bin/python"
  if [[ ! -x "$PY" ]]; then
    /usr/bin/python3 -m venv --system-site-packages "$ROOT/venv"
  fi
  echo "[TerraPulse] Installing missing training packages in isolated environment."
  record running "Installing CUDA PyTorch and training dependencies; watch installation log"
  "$PY" -m pip install --disable-pip-version-check --timeout 90 --retries 5 \
    'torch>=2.5,<3' 'numpy>=1.26,<3' 'h5py>=3.9' 'requests>=2.31' \
    'scikit-learn>=1.4,<2' 'onnx>=1.16' 'onnxruntime>=1.22,<2'
fi

"$PY" - <<'PY'
import torch, h5py, requests, sklearn, onnx, onnxruntime
print(f"[TerraPulse] torch={torch.__version__} CUDA={torch.version.cuda} devices={torch.cuda.device_count()}", flush=True)
assert torch.cuda.is_available(), "PyTorch CUDA is unavailable"
assert torch.cuda.device_count() >= 2, "This two-GPU run requires both NVIDIA L40 devices"
PY

record running "Staging additional Landslide4Sense training chips"
BASELINE="$REPO/server_data/landslide_spatial_metrics.json"
COUNT="${TP_TRAIN_CHIPS:-2200}"
if (( COUNT < 1024 || COUNT > 3799 )); then
  echo "TP_TRAIN_CHIPS must be from 1024 to 3799."
  exit 2
fi

# Reuse individual already downloaded .npz files in castor-audit, when matching
# the pinned benchmark dataset revision, without changing existing experiments.
"$PY" - "$HOME/castor-audit" "$ROOT/data" "$BASELINE" <<'PY'
import json, sys
from pathlib import Path
top, target, baseline = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
rev = json.loads(baseline.read_text())["revision"]
reused = 0
for manifest in top.glob("*/**/manifest.json"):
    if target in manifest.parents:
        continue
    try:
        item = json.loads(manifest.read_text())
    except Exception:
        continue
    if item.get("revision") != rev:
        continue
    for part in ("train", "validation", "test"):
        folder = target / part
        folder.mkdir(parents=True, exist_ok=True)
        for n in item.get("chip_ids", {}).get(part, []):
            existing = manifest.parent / part / f"{n}.npz"
            dest = folder / f"{n}.npz"
            if existing.is_file() and not dest.exists():
                dest.symlink_to(existing.resolve())
                reused += 1
print(f"[TerraPulse] Reused {reused} prepared chip files", flush=True)
PY

cd "$REPO/machine learning"
"$PY" l4s_stage.py "$BASELINE" "$ROOT/data" "$COUNT" 2>&1 | tee "$ROOT/logs/staging.log"

record running "Training two independent U-Nets on both NVIDIA L40 GPUs"

train_one() {
  local gpu="$1" width="$2" seed="$3" output="$4" dropout="$5"
  if [[ -f "$output/complete.flag" && -s "$output/model.pt" ]]; then
    if "$PY" - "$output/model.pt" "$ROOT/data/manifest.json" "$REPO/machine learning/l4s_spatial.py" \
      "$width" 16 38 "$seed" "$dropout" <<'PY'
import hashlib, sys, torch
checkpoint_path, manifest_path, trainer_path = sys.argv[1:4]
width, batch, epochs, seed = map(int, sys.argv[4:8])
dropout = float(sys.argv[8])
expected = {
    "width": width, "batch": batch, "epochs": epochs, "seed": seed,
    "dropout": dropout,
    "manifest_sha256": hashlib.sha256(open(manifest_path, "rb").read()).hexdigest(),
    "trainer_sha256": hashlib.sha256(open(trainer_path, "rb").read()).hexdigest(),
}
try:
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    if checkpoint.get("training_signature") == expected:
        raise SystemExit(0)
except Exception:
    pass
raise SystemExit(1)
PY
    then
      echo "[TerraPulse] Reusing matching successful checkpoint $output"
      return
    fi
    echo "[TerraPulse] Existing checkpoint does not match this run; retraining $output"
    rm -f "$output/complete.flag"
  fi
  mkdir -p "$output"
  CUDA_VISIBLE_DEVICES="$gpu" "$PY" -u l4s_spatial.py train \
    --data "$ROOT/data" --output "$output" --device 0 \
    --width "$width" --batch 16 --epochs 38 --seed "$seed" --dropout "$dropout" \
    >"$output/train.log" 2>&1
  [[ -s "$output/model.pt" ]] || { echo "Missing checkpoint $output"; return 1; }
  touch "$output/complete.flag"
}

train_one 0 48 262617 "$ROOT/checkpoints/l40_0" 0.12 &
PID_A=$!
train_one 1 64 262619 "$ROOT/checkpoints/l40_1" 0.16 &
PID_B=$!
FAILURES=0
wait "$PID_A" || FAILURES=1
wait "$PID_B" || FAILURES=1
if (( FAILURES )); then
  echo "[TerraPulse] One or both GPU training jobs failed."
  tail -n 20 "$ROOT/checkpoints/l40_0/train.log" || true
  tail -n 20 "$ROOT/checkpoints/l40_1/train.log" || true
  exit 1
fi

record running "Selecting ONNX release by validation AP, testing fixed benchmark"
CUDA_VISIBLE_DEVICES=0 "$PY" -u l4s_spatial.py select \
  --data "$ROOT/data" --output "$ROOT/release" --device 0 \
  --checkpoints "$ROOT/checkpoints/l40_0/model.pt" "$ROOT/checkpoints/l40_1/model.pt" \
  >"$ROOT/logs/evaluation.log" 2>&1

"$PY" - "$BASELINE" "$ROOT/release/spatial-metrics.json" "$ROOT/release" <<'PY'
import json, sys
from pathlib import Path
prior = json.loads(Path(sys.argv[1]).read_text())
new = json.loads(Path(sys.argv[2]).read_text())
out = Path(sys.argv[3])
old_ap = prior["validation"]["average_precision"]
new_ap = new["validation"]["average_precision"]
gate = new_ap >= old_ap + 0.005
report = {
    "prior_validation_ap": old_ap,
    "new_validation_ap": new_ap,
    "validation_ap_gain": new_ap-old_ap,
    "publish_candidate": gate,
    "selection_rule": "new validation AP at least 0.005 greater than prior validation AP",
    "prior_test_f1": prior["test"]["f1"],
    "new_test_f1": new["test"]["f1"],
    "warning": "The fixed Landslide4Sense test subset was already inspected in earlier experiments. These are repeat benchmark comparisons, NOT independent new-country or event validation.",
}
(out/"promotion_review.json").write_text(json.dumps(report, indent=2)+"\n")
print("[TerraPulse] Release evaluation:", json.dumps(report, indent=2), flush=True)
PY

# Never replace the currently deployed 66.2% F1 model automatically:
# choosing/promoting models based on repeated test scores would leak test
# information. The candidate is left ready for a deliberate validation
# review and API deployment via the connected GitHub workflow.
record success "GPU training and held-out benchmark completed; candidate exported for review, not auto-deployed"
echo "[TerraPulse] SUCCESS: model and report:"
ls -lh "$ROOT/release"
echo "[TerraPulse] Current website model unchanged until candidate passes review."
