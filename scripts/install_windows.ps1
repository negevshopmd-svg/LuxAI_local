param([switch]$SelfTest, [switch]$CheckVenv)

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

function Test-CompatiblePython([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $false
    }
    try {
        $result = & $Path -I -c 'import sys; print("LuxAI_PY311_X64" if sys.version_info[:2] == (3, 11) and sys.maxsize > 2**32 else "UNSUPPORTED")' 2>$null
        return ($LASTEXITCODE -eq 0 -and ($result | Out-String).Trim() -eq 'LuxAI_PY311_X64')
    } catch {
        return $false
    }
}

function Find-Python311 {
    $candidates = New-Object 'System.Collections.Generic.List[string]'

    $launcher = Get-Command -Name 'py.exe' -CommandType Application -ErrorAction SilentlyContinue
    if ($null -ne $launcher) {
        try {
            $pathFromLauncher = & $launcher.Source -3.11 -c 'import sys; print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $pathFromLauncher) {
                $candidates.Add(($pathFromLauncher | Out-String).Trim())
            }
        } catch { }
    }

    if ($env:LOCALAPPDATA) {
        $candidates.Add((Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'))
    }
    if ($env:ProgramFiles) {
        $candidates.Add((Join-Path $env:ProgramFiles 'Python311\python.exe'))
    }

    foreach ($hive in @(
        'HKCU:\SOFTWARE\Python\PythonCore\3.11\InstallPath',
        'HKLM:\SOFTWARE\Python\PythonCore\3.11\InstallPath',
        'HKLM:\SOFTWARE\WOW6432Node\Python\PythonCore\3.11\InstallPath'
    )) {
        try {
            $key = Get-Item -LiteralPath $hive -ErrorAction Stop
            $installDir = [string]$key.GetValue('')
            if ($installDir) {
                $candidates.Add((Join-Path $installDir 'python.exe'))
            }
        } catch { }
    }

    $command = Get-Command -Name 'python.exe' -CommandType Application -ErrorAction SilentlyContinue
    if ($null -ne $command -and $command.Source -notmatch '\\WindowsApps\\') {
        $candidates.Add($command.Source)
    }

    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (Test-CompatiblePython $candidate) {
            return $candidate
        }
    }
    return $null
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

function Install-OfficialPython {
    if (-not [Environment]::Is64BitOperatingSystem) {
        throw 'LuxAI requires 64-bit Windows.'
    }

    $url = 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe'
    $installer = Join-Path $env:TEMP ('luxai-python311-' + [Guid]::NewGuid().ToString('N') + '.exe')
    Write-Status 'Python 3.11 x64 not found. Downloading the official python.org installer...'
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

    if ($SelfTest) {
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

    $basePython = Find-Python311
    if (-not $basePython -and -not (Test-UsableVenv)) {
        Install-OfficialPython
        $basePython = Find-Python311
    }

    $venvUsable = Test-UsableVenv
    if (-not $venvUsable) {
        if (-not $basePython) {
            $basePython = Find-Python311
        }
        if (-not $basePython) {
            throw 'Python 3.11 (64-bit) is unavailable. Use https://www.python.org/downloads/release/python-3119/ and rerun setup.'
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

    Invoke-PythonStep $script:VenvPython @('-m', 'ensurepip', '--upgrade') 'Checking pip'
    Invoke-PythonStep $script:VenvPython @('-m', 'pip', 'install', '--disable-pip-version-check', '--prefer-binary', '--retries', '2', '--timeout', '30', '-r', 'requirements.txt') 'Installing LuxAI dependencies'
    Invoke-PythonStep $script:VenvPython @('-m', 'compileall', '-q', 'main.py', 'luxai') 'Checking Python source'
    Invoke-PythonStep $script:VenvPython @('-c', 'import main; print("LuxAI imports OK")') 'Checking application imports'

    try {
        Invoke-PythonStep $script:VenvPython @('-m', 'luxai.ocr_setup') 'Installing optional Tesseract OCR (Russian and English)'
    } catch {
        Write-Status "WARNING: OCR could not be installed: $($_.Exception.Message)"
        Write-Status 'Jarvis can start; OCR setup will be retried when needed.'
    }

    Write-Status 'SUCCESS: LuxAI installation completed. Launch run_windows.bat.'
    Write-Status 'Note: voice models may download on first use; internet access may be required.'
    exit 0
} catch {
    Write-Status "ERROR: $($_.Exception.Message)"
    Write-Status "Installation incomplete. Details: $script:LogFile"
    exit 1
}