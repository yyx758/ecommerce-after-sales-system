$ErrorActionPreference = "Stop"
$taskflowRoot = "D:\taskflow_lab"
$cachePath = Join-Path $taskflowRoot "ppnlp_home"

Write-Host "[1/4] Cleaning old Taskflow caches..."
if (Test-Path -LiteralPath "python_agent\.ppnlp_home") {
    Remove-Item -LiteralPath "python_agent\.ppnlp_home" -Recurse -Force
}
if (Test-Path -LiteralPath $cachePath) {
    Remove-Item -LiteralPath $cachePath -Recurse -Force
}

Write-Host "[2/4] Creating ASCII-only cache directory..."
New-Item -ItemType Directory -Path $cachePath -Force | Out-Null

Write-Host "[3/4] Setting environment variables..."
$env:PPNLP_HOME = $cachePath
$env:HOME = $taskflowRoot
$env:USERPROFILE = $taskflowRoot

Write-Host "[4/4] Running PaddleNLP Taskflow sentiment test..."
Write-Host "Note: this script uses the current .venv. If .venv contains Paddle 3.x, Taskflow may still fail on Windows."
.\.venv\Scripts\python.exe -c "from paddlenlp import Taskflow; s = Taskflow('sentiment_analysis'); samples = ['\u8fd9\u4e2a\u552e\u540e\u5904\u7406\u592a\u6162\u4e86', '\u5ba2\u670d\u5904\u7406\u5f97\u5f88\u597d']; print(s(samples))"
