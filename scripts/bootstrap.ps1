Param(
  [string]$NodeVersion = $(Get-Content -ErrorAction SilentlyContinue "$PSScriptRoot/../.node-version")
)

if (-not $NodeVersion) {
  $NodeVersion = "24.6.0"
}

$ErrorActionPreference = "Stop"
$script:RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot ".."))
$cacheRoot = if ($env:XDG_CACHE_HOME) { $env:XDG_CACHE_HOME } else { Join-Path $script:RepoRoot ".cache" }
$npmCache = Join-Path $cacheRoot "npm"
$pipCache = Join-Path $cacheRoot "pip"
New-Item -ItemType Directory -Force -Path $npmCache | Out-Null
New-Item -ItemType Directory -Force -Path $pipCache | Out-Null

if (Get-Command fnm -ErrorAction SilentlyContinue) {
  fnm env --use-on-cd | Out-String | Invoke-Expression
  fnm install $NodeVersion | Out-Null
  fnm use $NodeVersion | Out-Null
} elseif (Get-Command volta -ErrorAction SilentlyContinue) {
  volta install "node@$NodeVersion" | Out-Null
} elseif (Get-Command nvm -ErrorAction SilentlyContinue) {
  nvm install $NodeVersion | Out-Null
  nvm use $NodeVersion | Out-Null
} else {
  Write-Warning "[bootstrap] fnm/volta/nvm が見つかりません。既存の Node を利用します。"
}

$env:NPM_CONFIG_CACHE = $npmCache
Push-Location $script:RepoRoot
try {
  if (Test-Path "package-lock.json") {
    npm ci
  } else {
    npm install
  }

  try {
    npx --yes playwright install | Out-Null
  } catch {
    Write-Warning "[bootstrap] playwright install をスキップしました: $($_.Exception.Message)"
  }
} finally {
  Pop-Location
}

$python = if ($env:PYTHON) { $env:PYTHON } else { "python" }
$venvPath = Join-Path $script:RepoRoot ".venv"
if (-not (Test-Path $venvPath)) {
  & $python -m venv $venvPath
}

$env:PIP_CACHE_DIR = $pipCache
& (Join-Path $venvPath "Scripts/python.exe") -m pip install --upgrade pip
& (Join-Path $venvPath "Scripts/pip.exe") install -r (Join-Path $script:RepoRoot "projects/04-llm-adapter-shadow/requirements.txt")
