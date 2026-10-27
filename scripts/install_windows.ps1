param([switch]$SelfTest, [switch]$CheckVenv, [switch]$SkipOcr, [switch]$SkipLocalAI, [switch]$InventoryOnly)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:Root = Split-Path -Parent $PSScriptRoot
$script:Venv = Join-Path $script:Root '.venv'
$script:VenvPython = Join-Path $script:Venv 'Scripts\python.exe'
$script:VenvPythonw = Join-Path $script:Venv 'Scripts\pythonw.exe'
$script:LogDir = Join-Path $script:Root 'logs'
$script:LogFile = Join-Path $script:LogDir 'install_windows.log'

New-Item -ItemType Directory -Path $script:LogDir -Force | Out-Null
"===== LuxAI setup $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') =====" | Out-File -LiteralPath $script:LogFile -Append -Encoding UTF8

function Write-Status([string]$Message) {
    Write-Host $Message
    Add-Content -LiteralPath $script:LogFile -Value $Message -Encoding UTF8
}

function Get-CompatiblePythonVersion([string]$Path) {
    if (-not (Test-ExistingFile $Path)) {
        return $null
    }
    try {
        $result = & $Path -I -c "import sys; v=sys.version_info; print('LuxAI_PY=%d.%d.%d' % v[:3] if v.major == 3 and v.minor >= 11 and sys.maxsize > 2**32 else 'UNSUPPORTED')" 2>$null
        if ($LASTEXITCODE -ne 0) {
            return $null
        }
        $label = ($result | Out-String).Trim()
        if ($label -match '^LuxAI_PY=(3\.\d+\.\d+)$') {
            return [version]$Matches[1]
        }
    } catch { }
    return $null
}

function Test-StablePython([string]$Path) {
    if (-not (Test-CompatiblePython $Path)) {
        return $false
    }
    try {
        $result = & $Path -I -c "import sys; print('STABLE' if sys.version_info.releaselevel == 'final' else 'PREVIEW')" 2>$null
        return ($LASTEXITCODE -eq 0 -and ($result | Out-String).Trim() -eq 'STABLE')
    } catch {
        return $false
    }
}

function Test-CompatiblePython([string]$Path) {
    return ($null -ne (Get-CompatiblePythonVersion $Path))
}

function Get-InstalledPythonCandidates {
    $candidates = New-Object 'System.Collections.Generic.List[string]'
    $launcher = Get-Command -Name 'py.exe' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $launcher) {
        # Enumerate locally installed runtimes only; do not trigger the
        # newer Python install manager to download Python during detection.
        try {
            $entries = & $launcher.Source -0p 2>$null
            foreach ($entry in $entries) {
                $line = [string]$entry
                if ($line -match '(?i)([a-z]:\\.+?python(?:3(?:\.\d+)?)?\.exe)\s*$') {
                    $candidates.Add($Matches[1])
                }
            }
        } catch { }
    }

    $pythonRoots = @()
    if ($env:LOCALAPPDATA) {
        $pythonRoots += (Join-Path $env:LOCALAPPDATA 'Programs\Python')
    }
    if ($env:ProgramFiles) {
        $pythonRoots += (Join-Path $env:ProgramFiles 'Python')
        $pythonRoots += $env:ProgramFiles
    }
    foreach ($base in $pythonRoots) {
        if (-not $base -or -not (Test-Path -LiteralPath $base -PathType Container)) {
            continue
        }
        Get-ChildItem -LiteralPath $base -Directory -Filter 'Python3*' -ErrorAction SilentlyContinue |
            ForEach-Object { $candidates.Add((Join-Path $_.FullName 'python.exe')) }
    }

    foreach ($hive in @(
        'HKCU:\SOFTWARE\Python\PythonCore',
        'HKLM:\SOFTWARE\Python\PythonCore',
        'HKLM:\SOFTWARE\WOW6432Node\Python\PythonCore'
    )) {
        if (-not (Test-Path -LiteralPath $hive)) {
            continue
        }
        foreach ($versionKey in @(Get-ChildItem -LiteralPath $hive -ErrorAction SilentlyContinue)) {
            try {
                $installKey = Get-Item -LiteralPath ($versionKey.PSPath + '\InstallPath') -ErrorAction Stop
                $directory = [string]$installKey.GetValue('')
                if ($directory) {
                    $candidates.Add(([System.IO.Path]::Combine($directory, 'python.exe')))
                }
            } catch { }
        }
    }

    foreach ($command in @(Get-Command -Name 'python.exe' -All -CommandType Application -ErrorAction SilentlyContinue)) {
        if ($command.Source -and $command.Source -notmatch '\\WindowsApps\\') {
            $candidates.Add($command.Source)
        }
    }

    # Dedupe paths returned by py, PATH, registry and standard directories.
    return @($candidates | Select-Object -Unique)
}

function Get-InstalledPythonInventory {
    $inventory = @()
    foreach ($candidate in @(Get-InstalledPythonCandidates)) {
        $version = Get-CompatiblePythonVersion $candidate
        if ($null -ne $version) {
            $inventory += [pscustomobject]@{
                Path = $candidate
                Version = $version
                Stable = (Test-StablePython $candidate)
            }
        }
    }
    return $inventory
}

function Show-PythonCompatibility {
    $inventory = @(Get-InstalledPythonInventory)
    Write-Status 'Checking installed Python 3.11, 3.12, 3.13, 3.14 (64-bit):'
    foreach ($minor in @(11, 12, 13, 14)) {
        $matched = @($inventory | Where-Object { $_.Version.Minor -eq $minor -and $_.Stable })
        if ($matched.Count -gt 0) {
            $selected = $matched | Sort-Object Version -Descending | Select-Object -First 1
            Write-Status ("  Python 3.{0}: FOUND {1} - {2}" -f $minor, $selected.Version, $selected.Path)
        } else {
            Write-Status ("  Python 3.{0}: not installed (or not stable x64)" -f $minor)
        }
    }
}

function Find-CompatiblePython([int]$MaxMinor = 99, [switch]$StableOnly) {
    $bestPath = $null
    $bestVersion = [version]'0.0.0'
    foreach ($entry in @(Get-InstalledPythonInventory)) {
        if ($entry.Version.Minor -le $MaxMinor -and $entry.Version -gt $bestVersion -and
            ((-not $StableOnly) -or $entry.Stable)) {
            $bestPath = $entry.Path
            $bestVersion = $entry.Version
        }
    }
    if ($bestPath) {
        Write-Status "Selected Python $bestVersion (64-bit): $bestPath"
    }
    return $bestPath
}

function Find-PreferredPython {
    # Prefer verified stable 3.11-3.14 runtimes over a newer interpreter
    # whose native audio/GGUF dependencies may not yet support Windows.
    $supported = Find-CompatiblePython -MaxMinor 14 -StableOnly
    if ($supported) {
        return $supported
    }
    $released = Find-CompatiblePython -StableOnly
    if ($released) {
        return $released
    }
    return (Find-CompatiblePython)
}

function Test-ExistingFile([string]$Path) {
    try {
        return (Test-Path -LiteralPath $Path -PathType Leaf -ErrorAction Stop)
    } catch {
        return $false
    }
}

function Test-VenvBasePaths([string]$Directory) {
    $cfg = Join-Path $Directory 'pyvenv.cfg'
    if (-not (Test-Path -LiteralPath $cfg -PathType Leaf)) {
        return $false
    }
    $sawHome = $false
    foreach ($line in (Get-Content -LiteralPath $cfg -ErrorAction Stop)) {
        if ($line -match '^home\s*=\s*(.+?)\s*$') {
            $sawHome = $true
            $homeDir = $Matches[1].Trim().Trim('"')
            if (-not (Test-ExistingFile ([System.IO.Path]::Combine($homeDir, 'python.exe')))) {
                return $false
            }
        }
        if ($line -match '^executable\s*=\s*(.+?)\s*$') {
            $originalPython = $Matches[1].Trim().Trim('"')
            if (-not (Test-ExistingFile $originalPython)) {
                return $false
            }
        }
    }
    return $sawHome
}

function Test-UsableVenv {
    if (-not (Test-ExistingFile $script:VenvPythonw)) {
        return $false
    }
    if (-not (Test-VenvBasePaths $script:Venv)) {
        return $false
    }
    return (Test-CompatiblePython $script:VenvPython)
}

if ($CheckVenv) {
    if (Test-UsableVenv) {
        exit 0
    }
    exit 1
}

function Invoke-PythonStep([string]$Executable, [string[]]$Arguments, [string]$Title) {
    Write-Status ">> $Title"
    Push-Location $script:Root
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $Executable @Arguments 2>&1 | ForEach-Object {
            $line = ($_ | Out-String).TrimEnd()
            if ($line) {
                Write-Host $line
                Add-Content -LiteralPath $script:LogFile -Value $line -Encoding UTF8
            }
        }
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
        Pop-Location
    }
    if ($code -ne 0) {
        throw "$Title failed (exit code $code). See logs\install_windows.log."
    }
}

function Install-ApplicationDependencies {
    Invoke-PythonStep $script:VenvPython @('-m', 'ensurepip', '--upgrade') 'Checking pip'
    Invoke-PythonStep $script:VenvPython @('-m', 'pip', 'install', '--disable-pip-version-check', '--upgrade', 'pip') 'Updating pip to latest compatible stable version'
    # -U rechecks the index even for packages that are already installed.
    # The requirements constraints and Python-version markers still apply.
    # only-if-needed prevents needless upgrading of transitive dependencies.
    Invoke-PythonStep $script:VenvPython @('-m', 'pip', 'install', '--disable-pip-version-check', '--upgrade', '--upgrade-strategy', 'only-if-needed', '--prefer-binary', '--retries', '2', '--timeout', '30', '-r', 'requirements.txt') 'Updating all direct LuxAI dependencies to newest compatible stable versions'
    Invoke-PythonStep $script:VenvPython @('-m', 'pip', 'check') 'Checking installed package compatibility'
    Invoke-PythonStep $script:VenvPython @('-m', 'compileall', '-q', 'main.py', 'luxai') 'Checking Python source'
    Invoke-PythonStep $script:VenvPython @('-c', "import main; print('LuxAI imports OK')") 'Checking application imports'
}

function Install-OfficialPython {
    if (-not [Environment]::Is64BitOperatingSystem) {
        throw 'LuxAI requires 64-bit Windows.'
    }

    $url = 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe'
    $installer = Join-Path $env:TEMP ('luxai-python311-' + [Guid]::NewGuid().ToString('N') + '.exe')
    Write-Status 'No compatible Python 3.11+ x64 found. Downloading official Python 3.11 as a fallback...'
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing -ErrorAction Stop
        if ((Get-Item -LiteralPath $installer).Length -lt 10000000) {
            throw 'Python installer download is incomplete.'
        }
        $signature = Get-AuthenticodeSignature -LiteralPath $installer
        if ($signature.Status -ne 'Valid' -or
            $null -eq $signature.SignerCertificate -or
            $signature.SignerCertificate.Subject -notmatch 'Python Software Foundation') {
            throw 'Python installer digital signature could not be verified. It was NOT executed.'
        }

        Write-Status 'Official Python installer signature verified. Installing for the current user...'
        $args = @(
            '/quiet', 'InstallAllUsers=0', 'PrependPath=0',
            'Include_pip=1', 'Include_venv=1', 'Include_test=0',
            'Include_launcher=1', 'InstallLauncherAllUsers=0'
        )
        $process = Start-Process -FilePath $installer -ArgumentList $args -Wait -PassThru
        if ($process.ExitCode -ne 0) {
            throw "Official Python installer failed (exit code $($process.ExitCode))."
        }
    } finally {
        Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue
    }
}

function Assert-ProjectFiles {
    foreach ($file in @('main.py', 'requirements.txt')) {
        if (-not (Test-Path -LiteralPath (Join-Path $script:Root $file) -PathType Leaf)) {
            throw "Project file missing: $file. Extract the entire repository ZIP."
        }
    }
}

try {
    Write-Status '=== LuxAI Local | Windows setup ==='
    Assert-ProjectFiles
    if ($InventoryOnly) {
        Show-PythonCompatibility
        exit 0
    }

    if ($SelfTest) {
        $python = Get-Command -Name 'python.exe' -CommandType Application -ErrorAction Stop | Where-Object { $_.Source -notmatch '\\WindowsApps\\' } | Select-Object -First 1
        if ($null -eq $python) { throw 'Python executable not found on PATH.' }
        Write-Status "Self-test Python path: $($python.Source)"
        $rawProbe = & $python.Source -I -c "import sys; v=sys.version_info; print('LuxAI_PY=%d.%d.%d' % v[:3] if v.major == 3 and v.minor >= 11 and sys.maxsize > 2**32 else 'UNSUPPORTED')" 2>&1
        Write-Status "Self-test direct probe: $(($rawProbe | Out-String).Trim()) (exit=$LASTEXITCODE)"
        $version = Get-CompatiblePythonVersion $python.Source
        Write-Status "Self-test parsed result: $version"
        if ($null -eq $version -or $version.Major -ne 3 -or $version.Minor -lt 11) {
            throw 'The selected Python interpreter is not 64-bit Python 3.11 or newer.'
        }
        Write-Status "Installer self-test detected Python $version"
        $temporary = Join-Path $env:TEMP ('luxai-venv-selftest-' + [Guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $temporary -Force | Out-Null
        try {
            'home = Z:\luxai-path-that-does-not-exist' | Set-Content -LiteralPath (Join-Path $temporary 'pyvenv.cfg')
            if (Test-VenvBasePaths $temporary) {
                throw 'Broken portable .venv was incorrectly accepted.'
            }
        } finally {
            Remove-Item -LiteralPath $temporary -Recurse -Force -ErrorAction SilentlyContinue
        }
        Write-Status 'Installer self-test OK (broken virtualenv detected).'
        exit 0
    }

    Show-PythonCompatibility
    $basePython = Find-PreferredPython
    if (-not $basePython -and -not (Test-UsableVenv)) {
        Install-OfficialPython
        $basePython = Find-PreferredPython
    }

    $venvUsable = Test-UsableVenv
    if (-not $venvUsable) {
        if (-not $basePython) {
            $basePython = Find-PreferredPython
        }
        if (-not $basePython) {
            throw 'A compatible 64-bit Python >=3.11 was not found. Run install_windows.bat again or install Python from python.org.'
        }
        if (Test-Path -LiteralPath $script:Venv) {
            $oldName = '.venv.old-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 6)
            $oldLocation = Join-Path $script:Root $oldName
            Write-Status "Broken or transferred .venv detected. Preserving it as $oldName."
            Move-Item -LiteralPath $script:Venv -Destination $oldLocation -ErrorAction Stop
        }
        Invoke-PythonStep $basePython @('-m', 'venv', $script:Venv) 'Creating a fresh virtual environment'
        if (-not (Test-UsableVenv)) {
            throw 'New .venv failed verification. Check your Python installation.'
        }
    } else {
        Write-Status 'Existing .venv is valid; no reinstall of Python required.'
    }

    # Attempt newer runtimes first, automatically stepping down to an
    # installed, older interpreter if third-party native wheels are unavailable.
    # Never claim success unless dependencies and application import work.
    while ($true) {
        try {
            Install-ApplicationDependencies
            break
        } catch {
            $setupError = $_.Exception.Message
            $version = Get-CompatiblePythonVersion $script:VenvPython
            if ($null -eq $version -or $version.Minor -le 11) {
                throw
            }
            Write-Status "WARNING: Python $version could not run LuxAI: $setupError"
            $olderMinor = [int]$version.Minor - 1
            $fallback = Find-CompatiblePython -MaxMinor $olderMinor
            if (-not $fallback) {
                # Official, signed stable interpreter downloaded only if the
                # user has no lower compatible interpreter already installed.
                Install-OfficialPython
                $fallback = Find-CompatiblePython -MaxMinor 11
            }
            if (-not $fallback) {
                throw "No usable fallback after Python $version failed. Check $script:LogFile."
            }
            $oldName = '.venv.old-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 6)
            Write-Status "Preserving failed Python $version environment as $oldName."
            Move-Item -LiteralPath $script:Venv -Destination (Join-Path $script:Root $oldName) -ErrorAction Stop
            Invoke-PythonStep $fallback @('-m', 'venv', $script:Venv) 'Creating fallback virtual environment'
            if (-not (Test-UsableVenv)) {
                throw 'Fallback virtual environment failed verification.'
            }
        }
    }
    # GGUF models do not work merely because the .gguf file exists.
    # Install the optional CPU wheel by default; no C++ compiler or source build.
    # If a wheel is unavailable, keep core Jarvis and its voice controls usable.
    if ($SkipLocalAI) {
        Write-Status 'Optional llama-cpp-python installation skipped for test environment.'
    } else {
        try {
            Invoke-PythonStep $script:VenvPython @('-m', 'luxai.local_ai_setup') 'Installing and verifying local GGUF AI engine'
        } catch {
            Write-Status "WARNING: Local GGUF engine could not be installed: $($_.Exception.Message)"
            Write-Status 'Jarvis can still run. Automatic setup retries on launch; see logs\local_ai_install.log or retry Update.bat online.'
        }
    }

    if ($SkipOcr) {
        Write-Status 'Optional OCR installation skipped for test environment.'
    } else {
        try {
            Invoke-PythonStep $script:VenvPython @('-m', 'luxai.ocr_setup') 'Installing optional Tesseract OCR (Russian and English)'
        } catch {
            Write-Status "WARNING: OCR could not be installed: $($_.Exception.Message)"
            Write-Status 'Jarvis can start; OCR setup will be retried when needed.'
        }
    }

    Invoke-PythonStep $script:VenvPython @('Update.py', '--clean-installation') 'Removing unchanged bundled development files'
    Write-Status 'SUCCESS: LuxAI installation completed. Launch run_windows.bat.'
    Write-Status 'Note: voice models may download on first use; internet access may be required.'
    exit 0
} catch {
    Write-Status "ERROR: $($_.Exception.Message)"
    Write-Status "Installation incomplete. Details: $script:LogFile"
    exit 1
}
