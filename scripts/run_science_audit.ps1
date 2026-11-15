# PowerShell 5.1+; run from repository root; read-only audit of science outputs.
param([string]$Server = "team01@197.140.32.128",[switch]$SkipWebBuild)
$ErrorActionPreference = 'Stop'
function Assert-Exit($name) {
  if ($LASTEXITCODE -ne 0) { throw "$name exited with code $LASTEXITCODE" }
}
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root
Write-Host "TerraPulse: scientific evidence audit"
if (-not $SkipWebBuild) {
  npm ci
  Assert-Exit 'npm ci'
  npm run build
  Assert-Exit 'npm run build'
}
ssh $Server 'mkdir -p ~/castor-audit/science-gate/outputs'
Assert-Exit 'remote mkdir'
$uploadSpec = $Server + ':~/castor-audit/science-gate/science_gate.py'
scp '.\scripts\science_gate.py' $uploadSpec
Assert-Exit 'upload science gate'
$remote = @'
set -euo pipefail
QA="$HOME/castor-audit/science-gate"
V2="$HOME/castor-audit/terrapulse-full/v2"
NIS="$HOME/castor-audit/terrapulse-nisar-real"
python3 -m venv "$QA/.venv"
"$QA/.venv/bin/python" -m pip install --disable-pip-version-check -q 'numpy>=1.24,<3' 'rasterio>=1.3,<2'
echo '=== 1. Audit reported flood confusion counts ==='
if test -f "$V2/outputs/model_report.json"; then
  "$QA/.venv/bin/python" "$QA/science_gate.py" report \
    --report "$V2/outputs/model_report.json" \
    --out "$QA/outputs/qa_model.json" || echo 'MODEL QA FAILED: inspect outputs'
else
  echo 'NOT FOUND: V2/outputs/model_report.json'
fi
echo '=== 2. Audit NISAR before/after observation grids ==='
BEFORE="$(find "$NIS" -type f -name before_HHHH.tif -print -quit 2>/dev/null || true)"
AFTER="$(find "$NIS" -type f -name after_HHHH.tif -print -quit 2>/dev/null || true)"
CHANGE="$NIS/outputs/nisar_HHHH_observed_change_db.tif"
if test -n "$BEFORE" && test -n "$AFTER"; then
  if test -f "$CHANGE"; then
    "$QA/.venv/bin/python" "$QA/science_gate.py" nisar \
      --before "$BEFORE" --after "$AFTER" --change "$CHANGE" \
      --out "$QA/outputs/qa_nisar.json" || echo 'NISAR QA NEEDS REVIEW'
  else
    "$QA/.venv/bin/python" "$QA/science_gate.py" nisar \
      --before "$BEFORE" --after "$AFTER" \
      --out "$QA/outputs/qa_nisar.json" || echo 'NISAR QA NEEDS REVIEW'
  fi
else
  echo 'MISSING real NISAR before/after files; do not claim pixel QA'
fi
echo '=== 3. Worker status ==='
if test -f "$NIS/outputs/run_status.json"; then
  "$QA/.venv/bin/python" -c 'import json,sys; s=json.load(open(sys.argv[1])); print("status:",s.get("status"),"sensor:",s.get("sensor"),"gpu_status:",s.get("gpu_status"))' "$NIS/outputs/run_status.json"
fi
find "$QA/outputs" -maxdepth 1 -type f -name 'qa_*.json' -print
'@
$remote | ssh $Server 'bash -s'
Assert-Exit 'remote audit invocation'
New-Item -ItemType Directory -Force -Path '.\audit-results' | Out-Null
$downloadSpec = $Server + ':~/castor-audit/science-gate/outputs/qa_*.json'
scp $downloadSpec '.\audit-results\'
if ($LASTEXITCODE -ne 0) {
  Write-Warning 'No QA JSON downloaded. Check source paths.'
} else {
  Write-Host 'Completed: audit-results\qa_model.json and qa_nisar.json'
}
