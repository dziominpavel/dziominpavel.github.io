# Единый release-скрипт проекта: готовит и публикует релиз GitHub Release.
#
# Версия скрипта печатается при каждом запуске — по ней контролируется расхождение
# копий между репозиториями (разнос копий — см. scripts/sync-release.ps1 в репо витрины).
#
# Две фазы (см. capability app-release-pipeline):
#   release.ps1 -Prepare  — ДО сборки: классифицирует ## [Unreleased], записывает
#                           новый номер в файл version, сворачивает секцию.
#                           Не коммитит, не тегирует, не трогает dist/ и gh.
#   release.ps1           — ПОСЛЕ сборки: проверяет подготовленность (секция пуста,
#                           версия и changelog согласованы, дерево чисто), коммитит
#                           файлы бампа, создаёт тег, пушит и публикует релиз.
#
# Публикация (общее поведение):
#   1. читает версию из файла version (MAJOR.MINOR.PATCH) -> тег vX.Y.Z;
#   2. проверяет, что dist/ содержит ассеты (иначе отказ, тег не создаётся);
#   3. проверяет иконку по полю icon в store.yaml (иначе отказ);
#   4. проверяет gh установлен и авторизован (иначе отказ до каких-либо изменений);
#   5. отказывается перезаписывать существующий тег;
#   6. коммитит бамп, создаёт тег, пушит его и публикует релиз через gh;
#   7. после публикации best-effort оповещает витрину (repository_dispatch):
#      сбой оповещения даёт только предупреждение — релиз уже опубликован.
#
# Сборка — ответственность билд-скрипта проекта, не release-скрипта.
# Исторические артефакты (папка dist/archive и т.п.) в релиз не переносятся.

param(
    [switch]$Prepare,
    [switch]$Major
)

$SCRIPT_VERSION = "1.2.0"
Write-Host "release.ps1 v$SCRIPT_VERSION"

function Fail([string]$Message) {
    Write-Host "[ERROR] $Message" -ForegroundColor Red
    exit 1
}

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$VersionFilePath = Join-Path $ProjectRoot "version"
$ChangelogPath = Join-Path $ProjectRoot "CHANGELOG.md"
$SemVerPattern = '^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$'

# --- Чтение файлов ----------------------------------------------------------

function Read-Version {
    if (-not (Test-Path $VersionFilePath)) {
        Fail "Не найден файл version в корне проекта. Версия берётся только из него (MAJOR.MINOR.PATCH)."
    }
    try {
        $raw = [System.IO.File]::ReadAllBytes($VersionFilePath)
        $value = ([System.Text.Encoding]::UTF8.GetString($raw)).Trim()
    } catch {
        Fail "Файл version не читается: $($_.Exception.Message)"
    }
    if ($value -match "[^\x00-\x7F]") {
        Fail "Файл version содержит не-ASCII символы: '$value'"
    }
    if ($value -notmatch $SemVerPattern) {
        Fail "Неверный формат version: '$value' (ожидается MAJOR.MINOR.PATCH)."
    }
    return $value
}

# Возвращает hashtable: Lines, NewLine, UnreleasedStart, UnreleasedEnd, Body
function Read-Changelog {
    if (-not (Test-Path $ChangelogPath)) {
        Fail "Не найден CHANGELOG.md — без него релиз не публикуется (см. docs/versioning.md)."
    }
    $text = [System.IO.File]::ReadAllText($ChangelogPath)
    $newline = if ($text -match "`r`n") { "`r`n" } else { "`n" }
    # 0 = «вернуть все подстроки». Брать -1 нельзя: в PowerShell 7 это значит
    # «1 подстрока, считая от конца», файл не разбивается вовсе (about_Split).
    $lines = $text -split "\r?\n", 0

    $start = -1
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^## ') { $start = $i; break }
    }
    if ($start -lt 0) {
        Fail "В CHANGELOG.md нет ни одной секции ## ."
    }
    if ($lines[$start] -notmatch '^## \[Unreleased\]\s*$') {
        Fail "Первая секция CHANGELOG.md должна быть '## [Unreleased]', фактически: '$($lines[$start])'."
    }
    $end = $lines.Count
    for ($i = $start + 1; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^## ') { $end = $i; break }
    }
    $body = @()
    if ($end -gt ($start + 1)) { $body = @($lines[($start + 1)..($end - 1)]) }

    return @{
        Lines           = $lines
        NewLine         = $newline
        UnreleasedStart = $start
        UnreleasedEnd   = $end
        Body            = $body
    }
}

function Get-UnreleasedItems([object[]]$Body) {
    # Пустая секция = нет строк, кроме пустых и заголовков ### категорий.
    $items = @($Body | Where-Object {
        $line = $_.Trim()
        ($line -ne '') -and ($line -notmatch '^###')
    })
    return , $items
}

function Get-UnreleasedText([object[]]$Body) {
    return ($Body -join "`n")
}

# --- Классификация ----------------------------------------------------------

function Resolve-ReleaseLevel([object[]]$Body, [bool]$ForceMajor) {
    if ($ForceMajor) { return "MAJOR" }
    $text = Get-UnreleasedText $Body
    if ($text -match '(?i)BREAKING') { return "MAJOR" }
    # наивысший уровень выигрывает: Добавлено/Изменено -> MINOR раньше PATCH
    if ($text -match '(?m)^\s*###.*(\u0414\u043e\u0431\u0430\u0432\u043b\u0435\u043d|\u0418\u0437\u043c\u0435\u043d\u0435\u043d|Added|Changed|New)') { return "MINOR" }
    if ($text -match '(?m)^\s*###.*(\u0418\u0441\u043f\u0440\u0430\u0432\u043b\u0435\u043d|Fixed)') { return "PATCH" }
    # категории не распознаны, но пункты есть — никогда не заявлять «только фиксы»
    return "MINOR"
}

function Get-BumpedVersion([string]$Current, [string]$Level) {
    $parts = $Current.Split('.')
    $major = [int]$parts[0]
    $minor = [int]$parts[1]
    $patch = [int]$parts[2]
    switch ($Level) {
        "MAJOR" { return "$($major + 1).0.0" }
        "MINOR" { return "$major.$($minor + 1).0" }
        "PATCH" { return "$major.$minor.$($patch + 1)" }
    }
    Fail "Неизвестный уровень: $Level"
}

function Get-GitPorcelain {
    $out = & git status --porcelain 2>&1
    if ($LASTEXITCODE -ne 0) { return $null }
    # Унарная запятая: без неё PowerShell развернёт пустой массив в «ничего»,
    # и чистое дерево будет выглядеть как ошибка git ($null).
    $items = @($out | Where-Object { "$_".Trim() -ne '' })
    return , $items
}

# ===========================================================================
# ФАЗА ПОДГОТОВКИ: release.ps1 -Prepare
# ===========================================================================
if ($Prepare) {
    $version = Read-Version
    $cl = Read-Changelog
    $items = Get-UnreleasedItems $cl.Body

    if ($items.Count -eq 0) {
        Fail "Нет накопленных изменений: секция '## [Unreleased]' отсутствует или пуста. Нечего готовить — версия не меняется."
    }

    $dirty = Get-GitPorcelain
    if ($null -eq $dirty) {
        Fail "Это не git-репозиторий — подготовка релиза невозможна."
    }
    if ($dirty.Count -gt 0) {
        Fail ("Рабочее дерево не чистое, подготовка невозможна: сначала закоммичьте работу.`n" +
              ($dirty -join "`n"))
    }

    $level = Resolve-ReleaseLevel $cl.Body $Major.IsPresent
    $newVersion = Get-BumpedVersion $version $level
    if ($newVersion -eq $version) {
        Fail "Новая версия совпала с текущей ($version) — нечему бампиться."
    }
    $date = Get-Date -Format "yyyy-MM-dd"
    $newHeader = "## [$newVersion] — $date ($level)"

    # Тело секции: убираем ведущие пустые строки (свои добавляем сами).
    $body = @($cl.Body)
    while ($body.Count -gt 0 -and $body[0].Trim() -eq '') { $body = @($body | Select-Object -Skip 1) }

    $before = @($cl.Lines[0..$cl.UnreleasedStart])
    $after = if ($cl.UnreleasedEnd -lt $cl.Lines.Count) { @($cl.Lines[$cl.UnreleasedEnd..($cl.Lines.Count - 1)]) } else { @() }
    $newLines = @($before) + @('', $newHeader, '') + @($body) + @($after)

    $originalText = [System.IO.File]::ReadAllText($ChangelogPath)
    $originalVersion = [System.IO.File]::ReadAllBytes($VersionFilePath)
    $newText = ($newLines -join $cl.NewLine)

    try {
        [System.IO.File]::WriteAllText($ChangelogPath, $newText, (New-Object System.Text.UTF8Encoding($false)))
        [System.IO.File]::WriteAllText($VersionFilePath, $newVersion, (New-Object System.Text.UTF8Encoding($false)))
    } catch {
        [System.IO.File]::WriteAllText($ChangelogPath, $originalText, (New-Object System.Text.UTF8Encoding($false)))
        [System.IO.File]::WriteAllBytes($VersionFilePath, $originalVersion)
        Fail "Не удалось записать файлы бампа: $($_.Exception.Message)"
    }

    # Контроль: откат, если что-то пошло не так. Сознательно без Fail/exit,
    # иначе файлы остались бы изменёнными при провале.
    $restore = {
        [System.IO.File]::WriteAllText($ChangelogPath, $originalText, (New-Object System.Text.UTF8Encoding($false)))
        [System.IO.File]::WriteAllBytes($VersionFilePath, $originalVersion)
    }
    $problem = $null
    try {
        $checkVersion = ([System.Text.Encoding]::UTF8.GetString([System.IO.File]::ReadAllBytes($VersionFilePath))).Trim()
        if ($checkVersion -notmatch $SemVerPattern) { $problem = "version вне формата: $checkVersion" }
        $checkText = [System.IO.File]::ReadAllText($ChangelogPath)
        # 0 = «вернуть все подстроки» — как в Read-Changelog, см. комментарий там.
        $checkLines = $checkText -split "\r?\n", 0
        $checkHead = $null
        foreach ($line in $checkLines) {
            if ($line -match '^## \[?(\d+\.\d+\.\d+)\]?') { $checkHead = $Matches[1]; break }
        }
        if (-not $problem -and ($checkVersion -ne $newVersion -or $checkHead -ne $newVersion)) {
            $problem = "рассинхрон после бампа: version=$checkVersion, верх CHANGELOG=$checkHead"
        }
        $firstSection = $null
        foreach ($line in $checkLines) { if ($line -match '^## ') { $firstSection = $line; break } }
        if (-not $problem -and $firstSection -notmatch '^## \[Unreleased\]\s*$') {
            $problem = "первая секция стала: $firstSection"
        }
    } catch {
        $problem = "ошибка чтения после бампа: $($_.Exception.Message)"
    }
    if ($problem) {
        & $restore
        Fail "Контроль после бампа провален ($problem) — файлы восстановлены, тег не создавался."
    }

    Write-Host "[OK] Подготовлено: $version -> $newVersion ($level)" -ForegroundColor Green
    Write-Host "     Соберите артефакты в dist/, затем запустите release.ps1 без флагов."
    Write-Host "     Откат при неудачной сборке: git checkout -- version CHANGELOG.md"
    exit 0
}

# ===========================================================================
# ФАЗА ПУБЛИКАЦИИ: release.ps1
# ===========================================================================
$Version = Read-Version
$Tag = "v$Version"
Write-Host "Version: $Version (tag $Tag)"

$cl = Read-Changelog
$head = $null
foreach ($line in $cl.Lines) {
    if ($line -match '^## \[?(\d+\.\d+\.\d+)\]?') { $head = $Matches[1]; break }
}
if ($head -ne $Version) {
    Fail "Рассинхрон: version=$Version, верх CHANGELOG.md=$head. При бампе обновляются оба файла (release.ps1 -Prepare)."
}
if ((Get-UnreleasedItems $cl.Body).Count -gt 0) {
    Fail "Секция '## [Unreleased]' непуста — релиз не подготовлен, публиковать нечего. Сначала выполните: release.ps1 -Prepare"
}
Write-Host "CHANGELOG: верх секции $head, [Unreleased] пуст"

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
    Fail "Тег $Tag уже существует — существующий тег и релиз НЕ перезаписываются."
}
$OriginUrl = & git remote get-url origin
if ($OriginUrl -notmatch 'github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$') {
    Fail "Не найден remote origin с github.com — релиз некуда публиковать."
}
$RepoFullName = "$($Matches[1])/$($Matches[2])"
$RepoName = $Matches[2]

# --- 6. Дерево чисто, кроме файлов бампа -----------------------------------
$dirty = Get-GitPorcelain
if ($null -eq $dirty) { Fail "Не удалось получить git status --porcelain." }
$bumpFiles = @("version", "CHANGELOG.md")
$other = @($dirty | Where-Object {
    $path = "$_".Substring(3).Trim().Trim('"')
    -not ($bumpFiles -contains ($path -replace '^.* => ', ''))
})
if ($other.Count -gt 0) {
    Fail ("Незакоммиченные изменения в других файлах — тег не указал бы на работу, описанную в changelog. Сначала закоммичьте:`n" +
          ($other -join "`n"))
}

# --- 7. Коммит файлов бампа ------------------------------------------------
if ($dirty.Count -gt 0) {
    $level = "PATCH"
    foreach ($line in $cl.Lines) {
        if ($line -match '^## \[\d+\.\d+\.\d+\].*\((MAJOR|MINOR|PATCH)\)') { $level = $Matches[1]; break }
    }
    $null = & git add version CHANGELOG.md 2>&1
    if ($LASTEXITCODE -ne 0) { Fail "Не удалось добавить version и CHANGELOG.md в индекс." }
    $null = & git commit -m "release: $Version ($level)" 2>&1
    if ($LASTEXITCODE -ne 0) { Fail "Не удалось закоммитить бамп. Релиз не создан." }
    Write-Host "Committed: release: $Version ($level)"
}

# --- 7b. Пуш ветки: коммит бампа должен уехать на remote ---------------------
# Тег пушится отдельно (шаг 10); без этого шага ветка на GitHub остаётся
# позади тега — у клона файл version и верх changelog расходятся с тегом,
# а следующий релиз пришлось бы начинать с незапушенного бампа.
$CurrentBranch = & git rev-parse --abbrev-ref HEAD
$CurrentBranch = "$CurrentBranch".Trim()
if ($LASTEXITCODE -ne 0 -or $CurrentBranch -eq '' -or $CurrentBranch -eq 'HEAD') {
    Fail "Не удалось определить текущую ветку (или HEAD отсоединён) — коммит бампа не запушен, тег и релиз НЕ созданы."
}
$null = & git push origin $CurrentBranch 2>&1
if ($LASTEXITCODE -ne 0) {
    Fail "Не удалось запушить ветку $CurrentBranch с коммитом бампа. Тег и релиз НЕ созданы."
}
Write-Host "Pushed: ветка $CurrentBranch"

# --- 8. Тег укажет на коммит с секцией новой версии ------------------------
$null = & git show ("HEAD:CHANGELOG.md") 2>&1 | Out-Null
$headChangelog = & git show "HEAD:CHANGELOG.md"
if ($LASTEXITCODE -ne 0) { Fail "Не удалось прочитать CHANGELOG.md из HEAD." }
$sectionPattern = '^## \[' + [regex]::Escape($Version) + '\]'
$hasSection = @($headChangelog | Where-Object { $_ -match $sectionPattern }).Count -gt 0
if (-not $hasSection) {
    Fail "В HEAD:CHANGELOG.md нет секции [$Version] — тег создавать нельзя (релиз не публикуется)."
}

# --- 9. Имена ассетов по конвенции -----------------------------------------
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

# --- 10. Тег + релиз ---------------------------------------------------------
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

# --- 11. Оповещение витрины (best-effort) ------------------------------------
# Релиз уже опубликован, поэтому сбой оповещения — только предупреждение:
# код возврата не меняется, тег и релиз не откатываются (capability
# app-release-pipeline, «Оповещение витрины о релизе»).
$NotifyStore = "dziominpavel/dziominpavel.github.io"
$NotifyFile = [System.IO.Path]::GetTempFileName()
try {
    $NotifyJson = @{
        event_type     = "app-released"
        client_payload = @{ repo = $RepoFullName; tag = $Tag }
    } | ConvertTo-Json -Depth 4 -Compress
    # Без BOM: GitHub API ожидает JSON, BOM в начале тела — ошибка разбора.
    [System.IO.File]::WriteAllText($NotifyFile, $NotifyJson, (New-Object System.Text.UTF8Encoding($false)))
    $null = & gh api -X POST "repos/$NotifyStore/dispatches" --input $NotifyFile 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[WARN] Витрину оповестить не удалось — она подхватит релиз ближайшей сборкой по расписанию." -ForegroundColor Yellow
    } else {
        Write-Host "     Витрина оповещена: пересборка запущена по событию."
    }
} catch {
    Write-Host "[WARN] Оповещение витрины не выполнено: $($_.Exception.Message) — релиз опубликован." -ForegroundColor Yellow
} finally {
    Remove-Item -Path $NotifyFile -ErrorAction SilentlyContinue
}

exit 0
