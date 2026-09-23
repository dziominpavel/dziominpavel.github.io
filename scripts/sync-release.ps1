<#
.SYNOPSIS
  Скрипт-обновитель (задача 7.1 change'а add-app-store): разносит эталонный
  release-скрипт (release.ps1 + release.bat) по всем репозиториям витрины.

.DESCRIPTION
  Источник истины — registry.yaml (как и у generate.py), либо явный список
  -Repos owner/name. Для каждого репозитория:
    1) читает удалённый release.ps1 и извлекает $SCRIPT_VERSION;
    2) сравнивает с версией эталона из scripts/release.ps1;
    3) без -Apply — только отчёт (dry-run); с -Apply — создаёт/обновляет оба
       файла (release.ps1 и release.bat) коммитом в ветку по умолчанию;
    4) в конце повторно сверяет версии всех копий: они обязаны совпасть.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File sync-release.ps1           # dry-run
  powershell -ExecutionPolicy Bypass -File sync-release.ps1 -Apply    # разнос
#>
param(
    [string]$RegistryPath = (Join-Path $PSScriptRoot "..\registry.yaml"),
    [string[]]$Repos,
    [switch]$Apply
)

$ErrorActionPreference = "Stop"

# --- gh может быть не в PATH у утилитных шеллов -----------------------------
$GhCmd = (Get-Command gh -ErrorAction SilentlyContinue).Source
if (-not $GhCmd) {
    $fallback = "C:\Program Files\GitHub CLI\gh.exe"
    if (Test-Path $fallback) { $GhCmd = $fallback }
    else { Write-Host "[ERROR] gh не найден (PATH и $fallback)" -ForegroundColor Red; exit 1 }
}

# --- эталон -----------------------------------------------------------------
$SourcePs1 = Join-Path $PSScriptRoot "release.ps1"
$SourceBat = Join-Path $PSScriptRoot "release.bat"
foreach ($f in @($SourcePs1, $SourceBat)) {
    if (-not (Test-Path $f)) { Write-Host "[ERROR] нет эталона: $f" -ForegroundColor Red; exit 1 }
}
$ethalonText = [System.IO.File]::ReadAllText($SourcePs1)
if ($ethalonText -notmatch '\$SCRIPT_VERSION\s*=\s*"(\d+\.\d+\.\d+)"') {
    Write-Host "[ERROR] в эталоне не найден `$SCRIPT_VERSION = `"x.y.z`"" -ForegroundColor Red
    exit 1
}
$EthalonVersion = $Matches[1]
Write-Host "Эталон: release-скрипт v$EthalonVersion ($SourcePs1)"

# --- цели -------------------------------------------------------------------
if (-not $Repos) {
    if (-not (Test-Path $RegistryPath)) {
        Write-Host "[ERROR] нет реестра: $RegistryPath (укажите -Repos)" -ForegroundColor Red
        exit 1
    }
    $Repos = Select-String -Path $RegistryPath -Pattern "repo:\s*(\S+)" |
        ForEach-Object { $_.Matches[0].Groups[1].Value }
    $Repos = @($Repos | Select-Object -Unique)
}
if (-not $Repos) { Write-Host "[ERROR] пустой список репозиториев" -ForegroundColor Red; exit 1 }
Write-Host "Репозиториев: $($Repos.Count) | режим: $(if ($Apply) { 'APPLY (запись)' } else { 'dry-run (только отчёт)' })"
Write-Host ""

function Invoke-Gh([string[]]$GhArgs) {
    # Нативные команды: при EAP=Stop даже подавленный stderr (2>$null) кидает
    # terminating error — для ожидаемых 404 («файла ещё нет») переключаем EAP.
    $eap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = & $GhCmd @GhArgs 2>$null
        return @{ Output = ($out -join "`n"); ExitCode = $LASTEXITCODE }
    } finally {
        $ErrorActionPreference = $eap
    }
}

function Get-RemoteScriptVersion([string]$Repo) {
    # возвращает @{ Sha; Version } или $null, если файла нет
    $r = Invoke-Gh @("api", "repos/$Repo/contents/release.ps1")
    if ($r.ExitCode -ne 0 -or -not $r.Output) { return $null }
    $obj = $r.Output | ConvertFrom-Json
    $text = [System.Text.Encoding]::UTF8.GetString(
        [System.Convert]::FromBase64String(($obj.content -replace "\s", "")))
    $ver = $null
    if ($text -match '\$SCRIPT_VERSION\s*=\s*"(\d+\.\d+\.\d+)"') { $ver = $Matches[1] }
    return @{ Sha = $obj.sha; Version = $ver }
}

function Set-RemoteFile([string]$Repo, [string]$Path, [string]$LocalPath, [string]$Sha, [string]$Message) {
    $b64 = [System.Convert]::ToBase64String([System.IO.File]::ReadAllBytes($LocalPath))
    $args = @("api", "-X", "PUT", "repos/$Repo/contents/$Path",
              "-f", "message=$Message", "-f", "content=$b64")
    if ($Sha) { $args += @("-f", "sha=$Sha") }
    $r = Invoke-Gh $args
    return ($r.ExitCode -eq 0)
}

# --- dry-run/apply по каждому репо ------------------------------------------
$rows = @()
foreach ($repo in $Repos) {
    $remote = Get-RemoteScriptVersion $repo
    $sha = $null; $ver = $null; $state = ""
    if ($null -eq $remote) {
        $state = "нет файла"
    } else {
        $sha = $remote.Sha; $ver = $remote.Version
        if ($ver -eq $EthalonVersion) { $state = "ok (уже актуален)" }
        elseif ($ver) { $state = "устарел: v$ver" }
        else { $state = "непонятная версия" }
    }

    if ($Apply -and $state -ne "ok (уже актуален)") {
        $msg = "chore(release): sync release script v$EthalonVersion"
        $ps1ok = Set-RemoteFile $repo "release.ps1" $SourcePs1 $sha $msg
        $batSha = $null
        $batRemote = Invoke-Gh @("api", "repos/$repo/contents/release.bat")
        if ($batRemote.ExitCode -eq 0 -and $batRemote.Output) {
            $batSha = ($batRemote.Output | ConvertFrom-Json).sha
        }
        $batok = Set-RemoteFile $repo "release.bat" $SourceBat $batSha $msg
        if ($ps1ok -and $batok) { $state = "обновлён (commit отправлен)" }
        else { $state = "ОШИБКА записи" }
        # после записи перечитываем фактическую версию
        $check = Get-RemoteScriptVersion $repo
        if ($check) { $ver = $check.Version }
    }

    $rows += [pscustomobject]@{ Repo = $repo; Version = $(if ($ver) { "v$ver" } else { "-" }); Action = $state }
}

$rows | Format-Table -AutoSize

# --- финальная проверка: все копии одной версии ------------------------------
$finalVersions = @()
foreach ($repo in $Repos) {
    $remote = Get-RemoteScriptVersion $repo
    $finalVersions += $(if ($remote -and $remote.Version) { $remote.Version } else { "MISSING" })
}
$unique = @($finalVersions | Select-Object -Unique)
if ($unique.Count -eq 1 -and $unique[0] -eq $EthalonVersion) {
    Write-Host "[OK] Все $($Repos.Count) копий release-скрипта: v$EthalonVersion" -ForegroundColor Green
    exit 0
} else {
    Write-Host "[FAIL] Копии разного версии/отсутствуют: $($unique -join ', ')" -ForegroundColor Red
    exit 1
}
