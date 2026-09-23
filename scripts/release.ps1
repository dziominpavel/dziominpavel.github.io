# Единый release-скрипт проекта: публикует готовые артефакты из dist/ как GitHub Release.
#
# Версия скрипта печатается при каждом запуске — по ней контролируется расхождение
# копий между репозиториями (разнос копий — см. scripts/sync-release.ps1 в репо витрины).
#
# Поведение (см. capability app-release-pipeline):
#   1. читает версию из файла version (MAJOR.MINOR.PATCH) -> тег vX.Y.Z;
#   2. проверяет, что dist/ содержит ассеты (иначе отказ, тег не создаётся);
#   3. проверяет иконку по полю icon в store.yaml (иначе отказ);
#   4. проверяет gh установлен и авторизован (иначе отказ до каких-либо изменений);
#   5. отказывается перезаписывать существующий тег;
#   6. создаёт тег, пушит его и публикует релиз через gh.
#
# Сборка — ответственность билд-скрипта проекта, не release-скрипта.
# Исторические артефакты (папка dist/archive и т.п.) в релиз не переносятся.

param()

$SCRIPT_VERSION = "1.0.0"
Write-Host "release.ps1 v$SCRIPT_VERSION"

function Fail([string]$Message) {
    Write-Host "[ERROR] $Message" -ForegroundColor Red
    exit 1
}

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

# --- 1. Версия из файла version -------------------------------------------
$VersionFile = Join-Path $ProjectRoot "version"
if (-not (Test-Path $VersionFile)) {
    Fail "Не найден файл version в корне проекта. Версия берётся только из него (MAJOR.MINOR.PATCH)."
}
$Version = (Get-Content $VersionFile -Raw).Trim()
if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    Fail "Неверный формат version: '$Version' (ожидается MAJOR.MINOR.PATCH)."
}
$Tag = "v$Version"
Write-Host "Version: $Version (tag $Tag)"

# --- 2. Артефакты в dist/ ---------------------------------------------------
$DistDir = Join-Path $ProjectRoot "dist"
if (-not (Test-Path $DistDir)) {
    Fail "Нет папки dist/ — сначала соберите артефакты билд-скриптом проекта."
}
# Только верхний уровень dist/: подпапки (напр. dist/archive) — исторические.
$TopFiles = @(Get-ChildItem -Path $DistDir -File)
$Assets = @($TopFiles | Where-Object { $_.Extension -match '^\.(apk|zip|exe)$' })
if ($Assets.Count -eq 0) {
    Fail "Папка dist/ пуста (нет ассетов .apk/.zip/.exe). Тег и релиз НЕ создаются."
}

# --- 3. Иконка (поле icon в store.yaml) ------------------------------------
$StoreYaml = Join-Path $ProjectRoot "store.yaml"
if (-not (Test-Path $StoreYaml)) {
    Fail "Не найден store.yaml — без него нельзя проверить обязательную иконку проекта."
}
$IconLine = Select-String -Path $StoreYaml -Pattern '^\s*icon:\s*(\S+)\s*$' | Select-Object -First 1
if (-not $IconLine) {
    Fail "Нет иконки: поле icon в store.yaml не задано. Релиз не публикуется."
}
$IconValue = $IconLine.Matches[0].Groups[1].Value.Trim('"', "'")
$IconPath = $IconValue
if (-not [System.IO.Path]::IsPathRooted($IconPath)) { $IconPath = Join-Path $ProjectRoot $IconPath }
if (-not (Test-Path $IconPath)) {
    Fail "Нет иконки: icon='$IconValue' указывает на несуществующий файл. Релиз не публикуется."
}
Write-Host "Icon: OK ($IconPath)"

# --- 4. GitHub CLI установлен и авторизован --------------------------------
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Fail "GitHub CLI (gh) не найден. Установите: winget install GitHub.cli"
}
$null = & gh auth status 2>&1
if ($LASTEXITCODE -ne 0) {
    Fail "gh не авторизован. Выполните: gh auth login (публикации не было)."
}
Write-Host "gh: OK"

# --- 5. Git есть, тега ещё нет ---------------------------------------------
$null = & git rev-parse --verify HEAD 2>&1
if ($LASTEXITCODE -ne 0) { Fail "Это не git-репозиторий (или HEAD не существует)." }
$ExistingTag = & git tag --list $Tag
if ($ExistingTag) {
    Fail "Тег $Tag уже существует — существующий тег и релиз НЕ перезаписываются. Увеличьте version."
}
$OriginUrl = & git remote get-url origin
if ($OriginUrl -notmatch 'github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$') {
    Fail "Не найден remote origin с github.com — релиз некуда публиковать."
}
$RepoFullName = "$($Matches[1])/$($Matches[2])"
$RepoName = $Matches[2]

# --- 6. Имена ассетов по конвенции -----------------------------------------
# <Project>-<version>.apk | <Project>-<version>-win-x64.zip | <Project>-<version>-win-x64.exe
$StageDir = Join-Path ([System.IO.Path]::GetTempPath()) ("release-" + $Tag)
if (Test-Path $StageDir) { Remove-Item -Recurse -Force $StageDir }
New-Item -ItemType Directory -Path $StageDir | Out-Null
$Staged = @()
$RepoPattern = [regex]::Escape($RepoName)
foreach ($asset in $Assets) {
    $target = $asset.Name
    if ($asset.Name -notmatch "^$RepoPattern-$Version(-.*)\.(apk|zip|exe)$") {
        if ($asset.Extension -eq ".apk") {
            $target = "$RepoName-$Version.apk"
        } else {
            Write-Host "[WARN] Имя '$($asset.Name)' не соответствует конвенции — публикую как есть."
        }
    }
    Copy-Item $asset.FullName (Join-Path $StageDir $target)
    $Staged += Join-Path $StageDir $target
}
$Dupes = @($Staged | Group-Object | Where-Object { $_.Count -gt 1 })
if ($Dupes.Count -gt 0) {
    Fail "Два ассета приводятся к одному имени '$($Dupes[0].Name)' — поправьте билд-скрипт."
}

# --- 7. Тег + релиз ---------------------------------------------------------
Write-Host "Creating tag $Tag ..."
$null = & git tag -a $Tag -m "Release $Tag" 2>&1
if ($LASTEXITCODE -ne 0) { Fail "Не удалось создать тег $Tag." }

$null = & git push origin $Tag 2>&1
if ($LASTEXITCODE -ne 0) {
    & git tag -d $Tag | Out-Null
    Fail "Не удалось запушить тег $Tag. Релиз не создан."
}

Write-Host "Publishing release $Tag ($($Staged.Count) asset(s)) ..."
$ghOut = & gh release create $Tag @Staged --title $Tag --verify-tag 2>&1
if ($LASTEXITCODE -ne 0) {
    $ghError = ($ghOut -join " ")
    & git push --delete origin $Tag 2>&1 | Out-Null
    & git tag -d $Tag | Out-Null
    Fail "gh release create завершился ошибкой, тег откачен. Причина: $ghError"
}

Write-Host "[OK] Релиз $Tag опубликован: https://github.com/$RepoFullName/releases/tag/$Tag" -ForegroundColor Green
Write-Host "     Ассеты: $($Staged.Count) шт. (скрипт v$SCRIPT_VERSION)"
exit 0
