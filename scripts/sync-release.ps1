<#
.SYNOPSIS
  Скрипт разноса: доставляет эталонные файлы версионирования во все проекты
  владельца и следит за согласованностью копий.

.DESCRIPTION
  Источник проектов — versioning.yaml (все 12 проектов и их трек).
  registry.yaml НЕ используется: он описывает контракт витрины, а не перечень
  проектов, и трек static туда не входит.

  Два канала доставки:
    1) ЛОКАЛЬНЫЙ (docs/versioning.md, scripts/check-version.py, скелет
       CHANGELOG.md, блок AGENTS.md по маркерам <!-- versioning:begin/end -->,
       а для release-трека ещё release.ps1 + release.bat) — пишется в
       локальную копию проекта, каталог берётся из versioning.yaml.
    2) УДАЛЁННЫЙ (release.ps1 + release.bat через GitHub API) — только для
       release-трека; static-треку release-скрипт не разносится.

  Режим: без -Apply — только план (ничего не пишется); с -Apply — запись.
  -LocalOnly — локальный канал сам по себе: без обращений к gh, без проверки
  и записи удалённых копий release-скрипта (удалённый разнос — отдельное,
  явное действие).
  В конце всегда сверяются фактические копии с эталоном: расхождение -> exit 1.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File sync-release.ps1                    # план
  powershell -ExecutionPolicy Bypass -File sync-release.ps1 -LocalOnly -Apply  # разнос локально
  powershell -ExecutionPolicy Bypass -File sync-release.ps1 -Apply             # разнос + удалённый канал
#>
param(
    [string]$VersioningPath = (Join-Path $PSScriptRoot "..\versioning.yaml"),
    [string[]]$Repos,
    [switch]$LocalOnly,
    [switch]$Apply
)

$ErrorActionPreference = "Stop"

# --- эталоны -----------------------------------------------------------------
$SourcePs1 = Join-Path $PSScriptRoot "release.ps1"
$SourceBat = Join-Path $PSScriptRoot "release.bat"
$Root = Split-Path -Parent $PSScriptRoot
$SourceVersioning = Join-Path $Root "docs\versioning.md"
$SourceCheck = Join-Path $PSScriptRoot "check-version.py"
$SourceAgents = Join-Path $Root "docs\agents-versioning-block.md"

foreach ($f in @($SourcePs1, $SourceBat, $SourceVersioning, $SourceCheck, $SourceAgents)) {
    if (-not (Test-Path $f)) { Write-Host "[ERROR] нет эталона: $f" -ForegroundColor Red; exit 1 }
}
$ethalonText = [System.IO.File]::ReadAllText($SourcePs1)
if ($ethalonText -notmatch '\$SCRIPT_VERSION\s*=\s*"(\d+\.\d+\.\d+)"') {
    Write-Host "[ERROR] в эталоне не найден `$SCRIPT_VERSION = `"x.y.z`"" -ForegroundColor Red
    exit 1
}
$EthalonVersion = $Matches[1]
Write-Host "Эталон: release-скрипт v$EthalonVersion"

$AgentsBlock = [System.IO.File]::ReadAllText($SourceAgents)
if ($AgentsBlock -notmatch '<!-- versioning:begin -->' -or $AgentsBlock -notmatch '<!-- versioning:end -->') {
    Write-Host "[ERROR] в шаблоне блока нет маркеров versioning:begin/end" -ForegroundColor Red
    exit 1
}

# --- проекты из versioning.yaml ---------------------------------------------
function Get-ManifestProjects {
    if (-not (Test-Path $VersioningPath)) {
        Write-Host "[ERROR] нет versioning.yaml: $VersioningPath" -ForegroundColor Red
        exit 1
    }
    $py = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $py) { Write-Host "[ERROR] python не найден (нужен для чтения YAML)" -ForegroundColor Red; exit 1 }
    $json = & $py -c "import json,yaml,sys; print(json.dumps(yaml.safe_load(open(sys.argv[1], encoding='utf-8'))))" $VersioningPath 2>&1
    if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] versioning.yaml не разобрался: $json" -ForegroundColor Red; exit 1 }
    $data = $json | ConvertFrom-Json
    $result = @()
    foreach ($prop in $data.projects.PSObject.Properties) {
        $cfg = $prop.Value
        $result += [pscustomobject]@{
            Key         = $prop.Name
            Repo        = $(if ($cfg.repo) { [string]$cfg.repo } else { $null })
            Path        = $(if ($cfg.path) { [string]$cfg.path } else { $null })
            Track       = $(if ($cfg.track) { [string]$cfg.track } else { "release" })
            VersionFile = $(if ($null -ne $cfg.version_file) { [string]$cfg.version_file } else { $null })
            Changelog   = $(if ($cfg.changelog) { [string]$cfg.changelog } else { "CHANGELOG.md" })
            HasGit      = $(if ($null -ne $cfg.git) { [bool]$cfg.git } else { $true })
            Releases    = $(if ($null -ne $cfg.release) { [bool]$cfg.release } else { $true })
        }
    }
    return $result
}

$Projects = @(Get-ManifestProjects)
if ($Repos) {
    $Projects = @($Projects | Where-Object {
        $Repos -contains $_.Key -or ($_.Repo -and $Repos -contains $_.Repo)
    })
}
if (-not $Projects) { Write-Host "[ERROR] пустой список проектов" -ForegroundColor Red; exit 1 }

$ManifestDir = Split-Path -Parent $VersioningPath
foreach ($p in $Projects) {
    if ($p.Path) { $p | Add-Member -NotePropertyName LocalDir -NotePropertyValue (Join-Path $ManifestDir $p.Path) }
    else { $p | Add-Member -NotePropertyName LocalDir -NotePropertyValue $null }
}
$mode = if ($Apply -and $LocalOnly) { 'APPLY локально' }
        elseif ($Apply) { 'APPLY + удалённый канал' }
        else { 'plan (ничего не пишется)' }
Write-Host "Проектов: $($Projects.Count) | режим: $mode"
Write-Host ""

# --- удалённый канал (только release-трек) -----------------------------------
function Invoke-Gh([string[]]$GhArgs) {
    $eap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = & $script:GhCmd @GhArgs 2>$null
        return @{ Output = ($out -join "`n"); ExitCode = $LASTEXITCODE }
    } finally {
        $ErrorActionPreference = $eap
    }
}

function Get-RemoteScriptVersion([string]$Repo) {
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

# --- локальный канал ---------------------------------------------------------
function Get-DominantNewline([string]$Text) {
    if ($Text -match "`r`n") { return "`r`n" }
    return "`n"
}

function Update-AgentsBlock([string]$FilePath, [string]$Block) {
    <# Идемпотентная вставка/обновление блока между маркерами.
       Всё за пределами региона сохраняется побайтово. Возвращает действие. #>
    $nl = "`n"
    if (Test-Path $FilePath) {
        $text = [System.IO.File]::ReadAllText($FilePath)
        $nl = Get-DominantNewline $text
    } else {
        $text = ""
    }
    $beginMark = "<!-- versioning:begin -->"
    $endMark = "<!-- versioning:end -->"

    if ($text -match [regex]::Escape($beginMark) -and $text -match [regex]::Escape($endMark)) {
        $beginIdx = $text.IndexOf($beginMark)
        $endIdx = $text.IndexOf($endMark, $beginIdx)
        if ($endIdx -lt $beginIdx) { return @{ Action = "ОШИБКА: маркеры вне порядка"; Changed = $false } }
        $tailIdx = $text.IndexOf("`n", $endIdx)
        if ($tailIdx -lt 0) { $tailIdx = $text.Length } else { $tailIdx += 1 }
        $normalizedBlock = ($Block -replace "`r`n", "`n").TrimEnd("`n") + "`n"
        $inserted = $normalizedBlock -replace "`n", $nl
        $existing = $text.Substring($beginIdx, $tailIdx - $beginIdx)
        if ($existing -eq $inserted) {
            return @{ Action = "ok (блок актуален)"; Changed = $false }
        }
        $newText = $text.Substring(0, $beginIdx) + $inserted + $text.Substring($tailIdx)
        return @{ Action = "обновлён блок"; Changed = $true; Text = $newText }
    }

    if ($text.Trim() -eq "") {
        $normalizedBlock = ($Block -replace "`r`n", "`n").TrimEnd("`n") + "`n"
        return @{ Action = "создан AGENTS.md с блоком"; Changed = $true; Text = $normalizedBlock }
    }
    $sep = if ($text.EndsWith("`n") -or $text.EndsWith("`r`n")) { "" } else { $nl }
    $normalizedBlock = ($Block -replace "`r`n", "`n").TrimEnd("`n") + "`n"
    $newText = $text + $sep + $nl + ($normalizedBlock -replace "`n", $nl)
    return @{ Action = "дописан блок"; Changed = $true; Text = $newText }
}

function Test-SameFile([string]$Source, [string]$Target) {
    # Источник и цель могут совпадать (витрина — сама себе проект): копировать
    # файл на самого себя нельзя.
    return [System.IO.Path]::GetFullPath($Source) -eq [System.IO.Path]::GetFullPath($Target)
}

function Get-NormalizedHash([string]$Path) {
    # Сравнение без учёта перевода строк: у детей core.autocrlf=true, поэтому
    # после checkout/clone те же байты лежат в CRLF, а эталон хранится в LF.
    # 28591 (Latin-1) переводит байты в символы и обратно один-в-один,
    # поэтому содержимое сравнивается байт-в-байт, минуя только CR.
    $latin = [Text.Encoding]::GetEncoding(28591)
    $text = $latin.GetString([IO.File]::ReadAllBytes($Path)).Replace("`r", "")
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return [BitConverter]::ToString($sha.ComputeHash($latin.GetBytes($text))).Replace('-', '')
    } finally {
        $sha.Dispose()
    }
}

function Test-FileIdentical([string]$Source, [string]$Target) {
    # Сырые хэши не годятся: CRLF в дочерней копии давал ложное «расходится».
    if ((Get-NormalizedHash $Source) -ne (Get-NormalizedHash $Target)) { return $false }
    return $true
}

function Copy-IfDifferent([string]$Source, [string]$Target) {
    if (-not (Test-Path $Target)) { return "создан" }
    if (Test-SameFile $Source $Target) { return "ok (эталон здесь)" }
    if (Test-FileIdentical $Source $Target) { return "ok" }
    return "обновлён"
}

function Copy-PreservingEol([string]$Source, [string]$Target) {
    # Переводы строк цели сохраняем: у детей core.autocrlf=true, и запись LF
    # поверх CRLF даёт git-статус «M» при равном содержимом — дерево выглядит
    # грязным, а release.ps1, требующий чистого дерева, отказывается готовить
    # релиз. Цель ещё не существует — копируем байты эталона как есть.
    $bytes = [IO.File]::ReadAllBytes($Source)
    if (Test-Path $Target) {
        # Имя строго другой регистр: PowerShell-переменные регистронезависимы,
        # $target перезаписал бы строковый параметр $Target байтовым массивом.
        $existing = [IO.File]::ReadAllBytes($Target)
        if ($existing -contains 13) {
            $latin = [Text.Encoding]::GetEncoding(28591)
            $text = $latin.GetString($bytes).Replace("`r`n", "`n").Replace("`n", "`r`n")
            $bytes = $latin.GetBytes($text)
        }
    }
    [IO.File]::WriteAllBytes($Target, $bytes)
    (Get-Item $Target).LastWriteTime = (Get-Item $Source).LastWriteTime
}

function New-ChangelogSkeleton {
    return @"
# Changelog

Формат: Keep a Changelog, уровни — семантическое версионирование.
Правила ведения: ``docs/versioning.md``.

## [Unreleased]

"@
}

# --- план и (опционально) запись ---------------------------------------------
$GhCmd = $null
if (-not $LocalOnly) {
    $GhCmd = (Get-Command gh -ErrorAction SilentlyContinue).Source
    if (-not $GhCmd) {
        $fallback = "C:\Program Files\GitHub CLI\gh.exe"
        if (Test-Path $fallback) { $GhCmd = $fallback }
        else { Write-Host "[ERROR] gh не найден (PATH и $fallback)" -ForegroundColor Red; exit 1 }
    }
}

$rows = @()
$accessErrors = @()
foreach ($p in $Projects) {
    $local = $p.LocalDir
    if (-not $local -or -not (Test-Path $local)) {
        $accessErrors += "$($p.Key): локальная копия не найдена ($local)"
        $rows += [pscustomobject]@{ Project = $p.Key; Track = $p.Track; Action = "ОШИБКА доступа: нет каталога" }
        continue
    }

    $actions = @()

    # 1) эталонные файлы версионирования
    foreach ($pair in @(
        @($SourceVersioning, (Join-Path $local "docs\versioning.md")),
        @($SourceCheck, (Join-Path $local "scripts\check-version.py"))
    )) {
        $src = $pair[0]; $dst = $pair[1]
        $dir = Split-Path -Parent $dst
        $same = Test-SameFile $src $dst
        $state = if ($same) { "ok (эталон здесь)" }
                 elseif (Test-Path $dst) { Copy-IfDifferent $src $dst }
                 else { "создан" }
        $actions += "$(Split-Path $dst -Leaf): $state"
        if ($Apply -and ($state -eq "создан" -or $state -eq "обновлён")) {
            if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
            Copy-PreservingEol $src $dst
        }
    }

    # 2) CHANGELOG: скелет только если файла нет (содержимое не перезаписываем)
    $clPath = Join-Path $local $p.Changelog
    if (Test-Path $clPath) {
        $actions += "$($p.Changelog): ok (есть, не трогаю)"
    } else {
        $actions += "$($p.Changelog): создать скелет"
        if ($Apply) {
            [System.IO.File]::WriteAllText($clPath, (New-ChangelogSkeleton), (New-Object System.Text.UTF8Encoding($false)))
        }
    }

    # 3) блок правил в AGENTS.md (идемпотентно, соседний текст не трогаем)
    $agentsPath = Join-Path $local "AGENTS.md"
    $agentsPlan = Update-AgentsBlock $agentsPath $AgentsBlock
    $actions += "AGENTS.md: $($agentsPlan.Action)"
    if ($Apply -and $agentsPlan.Changed -and $agentsPlan.Text) {
        [System.IO.File]::WriteAllText($agentsPath, $agentsPlan.Text, (New-Object System.Text.UTF8Encoding($false)))
    }

    # 4) release-скрипт: только release-трек; локальный канал + канал удалённый
    $remoteNote = ""
    if (-not $p.Releases) {
        $remoteNote = "static/без релизов: release-скрипт не разносится"
    } else {
        foreach ($pair in @(
            @($SourcePs1, (Join-Path $local "release.ps1")),
            @($SourceBat, (Join-Path $local "release.bat"))
        )) {
            $src = $pair[0]; $dst = $pair[1]
            $state = if (Test-Path $dst) { Copy-IfDifferent $src $dst } else { "создан" }
            $actions += "$(Split-Path $dst -Leaf): $state"
            if ($Apply -and ($state -eq "создан" -or $state -eq "обновлён")) { Copy-PreservingEol $src $dst }
        }

        if ($LocalOnly) {
            $remoteNote = "локальный режим: канал пропущен"
        } elseif (-not $p.Repo) {
            $remoteNote = "нет repo: удалённый разнос пропущен"
        } else {
            $remote = Get-RemoteScriptVersion $p.Repo
            if ($null -eq $remote) { $remoteNote = "release.ps1: нет файла" }
            elseif ($remote.Version -eq $EthalonVersion) { $remoteNote = "release.ps1: ok (v$($remote.Version))" }
            else { $remoteNote = "release.ps1: устарел v$($remote.Version)" }

            if ($Apply -and $remote -and $remote.Version -ne $EthalonVersion) {
                $msg = "chore(release): sync release script v$EthalonVersion"
                $ps1ok = Set-RemoteFile $p.Repo "release.ps1" $SourcePs1 $remote.Sha $msg
                $batSha = $null
                $batRemote = Invoke-Gh @("api", "repos/$($p.Repo)/contents/release.bat")
                if ($batRemote.ExitCode -eq 0 -and $batRemote.Output) { $batSha = ($batRemote.Output | ConvertFrom-Json).sha }
                $batok = Set-RemoteFile $p.Repo "release.bat" $SourceBat $batSha $msg
                if ($ps1ok -and $batok) { $remoteNote = "release.ps1: обновлён" }
                else { $remoteNote = "release.ps1: ОШИБКА записи" }
            } elseif ($Apply -and -not $remote) {
                $msg = "chore(release): add release script v$EthalonVersion"
                $ps1ok = Set-RemoteFile $p.Repo "release.ps1" $SourcePs1 $null $msg
                $batok = Set-RemoteFile $p.Repo "release.bat" $SourceBat $null $msg
                if ($ps1ok -and $batok) { $remoteNote = "release.ps1: создан" }
                else { $remoteNote = "release.ps1: ОШИБКА записи" }
            }
        }
    }

    $rows += [pscustomobject]@{
        Project = $p.Key
        Track   = $p.Track
        Action  = ($actions -join "; ")
        Remote  = $remoteNote
    }
}

$rows | Format-Table -AutoSize -Wrap
if ($accessErrors) {
    Write-Host "[ERROR] Ошибки доступа:" -ForegroundColor Red
    $accessErrors | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
}

# --- финальная сверка копий с эталоном (всегда) -------------------------------
$divergence = @()
foreach ($p in $Projects) {
    if (-not $p.LocalDir -or -not (Test-Path $p.LocalDir)) { continue }
    foreach ($pair in @(
        @($SourceVersioning, (Join-Path $p.LocalDir "docs\versioning.md")),
        @($SourceCheck, (Join-Path $p.LocalDir "scripts\check-version.py"))
    )) {
        if (-not (Test-Path $pair[1])) { $divergence += "$($p.Key): нет $(Split-Path $pair[1] -Leaf)"; continue }
        if (-not (Test-FileIdentical $pair[0] $pair[1])) {
            $divergence += "$($p.Key): $(Split-Path $pair[1] -Leaf) расходится с эталоном"
        }
    }
    $clPath = Join-Path $p.LocalDir $p.Changelog
    if (-not (Test-Path $clPath)) { $divergence += "$($p.Key): нет $($p.Changelog)" }

    if ($p.Releases) {
        foreach ($pair in @(
            @($SourcePs1, (Join-Path $p.LocalDir "release.ps1")),
            @($SourceBat, (Join-Path $p.LocalDir "release.bat"))
        )) {
            if (-not (Test-Path $pair[1])) {
                $divergence += "$($p.Key): нет $(Split-Path $pair[1] -Leaf)"
                continue
            }
            if (-not (Test-FileIdentical $pair[0] $pair[1])) {
                $divergence += "$($p.Key): $(Split-Path $pair[1] -Leaf) расходится с эталоном"
            }
        }
    }

    $agentsPath = Join-Path $p.LocalDir "AGENTS.md"
    if (-not (Test-Path $agentsPath)) {
        $divergence += "$($p.Key): нет AGENTS.md"
    } else {
        $check = Update-AgentsBlock $agentsPath $AgentsBlock
        if ($check.Action -notlike "ok*") { $divergence += "$($p.Key): блок AGENTS.md '$($check.Action)'" }
    }

    if ($p.Releases -and $p.Repo -and -not $LocalOnly) {
        $remote = Get-RemoteScriptVersion $p.Repo
        $v = if ($remote -and $remote.Version) { $remote.Version } else { "MISSING" }
        if ($v -ne $EthalonVersion) { $divergence += "$($p.Key): remote release.ps1 = $v" }
    }
}

Write-Host ""
if ($divergence.Count -eq 0 -and -not $accessErrors) {
    $scope = if ($LocalOnly) { "локальные копии" } else { "все проекты" }
    Write-Host "[OK] $scope $($Projects.Count) согласованы с эталоном (release-скрипт v$EthalonVersion)" -ForegroundColor Green
    exit 0
}
Write-Host "[FAIL] Расхождений: $($divergence.Count)" -ForegroundColor Red
$divergence | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
exit 1
