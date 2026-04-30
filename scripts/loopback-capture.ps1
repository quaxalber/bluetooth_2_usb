$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
$PythonBin = $null

function Test-PythonHasHid([string]$Candidate) {
  if (-not $Candidate) {
    return $false
  }

  try {
    & $Candidate -c "import hid" *> $null
    return $LASTEXITCODE -eq 0
  } catch {
    return $false
  }
}

$VenvPython = "$RepoRoot\venv\Scripts\python.exe"

if ($env:HOST_CAPTURE_PYTHON -and (Test-PythonHasHid $env:HOST_CAPTURE_PYTHON)) {
  $PythonBin = $env:HOST_CAPTURE_PYTHON
} elseif ((Test-Path $VenvPython) -and (Test-PythonHasHid $VenvPython)) {
  $PythonBin = $VenvPython
} elseif (Test-PythonHasHid "python") {
  $PythonBin = "python"
} else {
  try {
    & py -3 -c "import hid" *> $null
    if ($LASTEXITCODE -eq 0) {
      $PythonBin = "py -3"
    }
  } catch {
    # Intentionally ignored so the wrapper can fall through to the final error path.
  }
}

if (-not $PythonBin) {
  Write-Error "No suitable Python with hidapi found. Set HOST_CAPTURE_PYTHON or install the Python package 'hidapi'."
}

$env:PYTHONPATH = "$RepoRoot\src" + $(if ($env:PYTHONPATH) { ";$env:PYTHONPATH" } else { "" })

if ($PythonBin -eq "py -3") {
  & py -3 -m bluetooth_2_usb.loopback capture @args
} else {
  & $PythonBin -m bluetooth_2_usb.loopback capture @args
}

exit $LASTEXITCODE
