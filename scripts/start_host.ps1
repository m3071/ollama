param(
    [string]$HostAddress = "0.0.0.0",
    [int]$Port = 8000,
    [string]$OllamaHost = "http://127.0.0.1:11434",
    [string]$Model = "scb10x/typhoon-ocr1.5-3b"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$runtimeDir = Join-Path $projectRoot ".runtime"
$envFile = Join-Path $projectRoot ".env"
$envExample = Join-Path $projectRoot ".env.example"
$venvDir = Join-Path $projectRoot ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$requirementsFile = Join-Path $projectRoot "requirements.txt"
$requirementsStateFile = Join-Path $runtimeDir "requirements.sha256"
$ollamaPidFile = Join-Path $runtimeDir "ollama.pid"
$apiPidFile = Join-Path $runtimeDir "api.pid"
$ngrokPidFile = Join-Path $runtimeDir "ngrok.pid"
$apiOut = Join-Path $runtimeDir "api.stdout.log"
$apiErr = Join-Path $runtimeDir "api.stderr.log"
$ollamaOut = Join-Path $runtimeDir "ollama.stdout.log"
$ollamaErr = Join-Path $runtimeDir "ollama.stderr.log"
$ngrokOut = Join-Path $runtimeDir "ngrok.stdout.log"
$ngrokErr = Join-Path $runtimeDir "ngrok.stderr.log"

New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message"
}

function Resolve-CommandPath([string[]]$Candidates) {
    foreach ($candidate in $Candidates) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($cmd) {
            return $cmd.Source
        }
    }
    return $null
}

function Wait-ForHttp([string]$Url, [int]$TimeoutSeconds = 60) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            Invoke-RestMethod -Method Get -Uri $Url | Out-Null
            return $true
        } catch {
            Start-Sleep -Seconds 2
        }
    }
    return $false
}

function Get-PublicIp {
    $providers = @(
        "https://api.ipify.org?format=text",
        "https://checkip.amazonaws.com"
    )

    foreach ($provider in $providers) {
        try {
            $response = Invoke-RestMethod -Method Get -Uri $provider -TimeoutSec 5
            $value = "$response".Trim()
            if ($value -match '^\d{1,3}(\.\d{1,3}){3}$') {
                return $value
            }
        } catch {
        }
    }

    return $null
}

function Get-EnvValue([string]$Key, [string]$Default = "") {
    $content = Get-Content $envFile -ErrorAction SilentlyContinue
    foreach ($line in $content) {
        if ($line -match "^\s*$([regex]::Escape($Key))=(.*)$") {
            return $matches[1]
        }
    }
    return $Default
}

function Get-BoolFromString([string]$Value) {
    if (-not $Value) {
        return $false
    }

    switch ($Value.Trim().ToLowerInvariant()) {
        "1" { return $true }
        "true" { return $true }
        "yes" { return $true }
        "on" { return $true }
        default { return $false }
    }
}

function Invoke-External {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [string]$WorkingDirectory = $projectRoot
    )

    $argText = if ($Arguments.Count -gt 0) { $Arguments -join " " } else { "" }
    Write-Host "   $FilePath $argText"
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $argText"
    }
}

function Invoke-ExternalOptional {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @()
    )

    $argText = if ($Arguments.Count -gt 0) { $Arguments -join " " } else { "" }
    Write-Host "   $FilePath $argText"
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        Write-Host "   Command failed but will be ignored: exit code ${LASTEXITCODE}"
        return $false
    }

    return $true
}

function Find-PythonExe {
    $resolved = Resolve-CommandPath @("python")
    if ($resolved) {
        return $resolved
    }

    $launcher = Resolve-CommandPath @("py")
    if ($launcher) {
        try {
            $candidate = & $launcher -3.12 -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $candidate) {
                return ($candidate | Select-Object -First 1).Trim()
            }
        } catch {
        }

        try {
            $candidate = & $launcher -3 -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $candidate) {
                return ($candidate | Select-Object -First 1).Trim()
            }
        } catch {
        }
    }

    $commonPaths = @(
        (Join-Path $env:LocalAppData "Programs\Python\Python312\python.exe"),
        (Join-Path $env:LocalAppData "Programs\Python\Python311\python.exe")
    )
    foreach ($path in $commonPaths) {
        if (Test-Path $path) {
            return $path
        }
    }

    return $null
}

function Ensure-Winget {
    $winget = Resolve-CommandPath @("winget")
    if (-not $winget) {
        $windowsApps = Join-Path $env:LocalAppData "Microsoft\WindowsApps\winget.exe"
        if (Test-Path $windowsApps) {
            return $windowsApps
        }
        throw "winget was not found. Please install App Installer from Microsoft Store, then run start.bat again."
    }
    return $winget
}

function Ensure-Python {
    $pythonExe = Find-PythonExe
    if ($pythonExe) {
        return $pythonExe
    }

    Write-Step "Installing Python 3.12"
    $winget = Ensure-Winget
    Invoke-External -FilePath $winget -Arguments @(
        "install",
        "--id", "Python.Python.3.12",
        "-e",
        "--accept-source-agreements",
        "--accept-package-agreements",
        "--silent"
    )

    $pythonExe = Find-PythonExe
    if (-not $pythonExe) {
        throw "Python installation finished, but python.exe could not be located."
    }
    return $pythonExe
}

function Find-OllamaExe {
    $resolved = Resolve-CommandPath @("ollama")
    if ($resolved) {
        return $resolved
    }

    $commonPaths = @(
        (Join-Path $env:LocalAppData "Programs\Ollama\ollama.exe"),
        (Join-Path $env:ProgramFiles "Ollama\ollama.exe")
    )
    foreach ($path in $commonPaths) {
        if (Test-Path $path) {
            return $path
        }
    }

    return $null
}

function Ensure-Ollama {
    $ollamaExe = Find-OllamaExe
    if ($ollamaExe) {
        return $ollamaExe
    }

    Write-Step "Installing Ollama"
    $winget = Ensure-Winget
    Invoke-External -FilePath $winget -Arguments @(
        "install",
        "--id", "Ollama.Ollama",
        "-e",
        "--accept-source-agreements",
        "--accept-package-agreements",
        "--silent"
    )

    $ollamaExe = Find-OllamaExe
    if (-not $ollamaExe) {
        throw "Ollama installation finished, but ollama.exe could not be located."
    }
    return $ollamaExe
}

function Find-CudaCompiler {
    $resolved = Resolve-CommandPath @("nvcc")
    if ($resolved) {
        return $resolved
    }

    $commonPaths = @(
        (Join-Path $env:ProgramFiles "NVIDIA GPU Computing Toolkit\CUDA\v13.2\bin\nvcc.exe"),
        (Join-Path $env:ProgramFiles "NVIDIA GPU Computing Toolkit\CUDA\v13.1\bin\nvcc.exe"),
        (Join-Path $env:ProgramFiles "NVIDIA GPU Computing Toolkit\CUDA\v13.0\bin\nvcc.exe"),
        (Join-Path $env:ProgramFiles "NVIDIA GPU Computing Toolkit\CUDA\v12.9\bin\nvcc.exe"),
        (Join-Path $env:ProgramFiles "NVIDIA GPU Computing Toolkit\CUDA\v12.8\bin\nvcc.exe"),
        (Join-Path $env:ProgramFiles "NVIDIA GPU Computing Toolkit\CUDA\v12.6\bin\nvcc.exe"),
        (Join-Path $env:ProgramFiles "NVIDIA GPU Computing Toolkit\CUDA\v12.5\bin\nvcc.exe"),
        (Join-Path $env:ProgramFiles "NVIDIA GPU Computing Toolkit\CUDA\v12.4\bin\nvcc.exe"),
        (Join-Path $env:ProgramFiles "NVIDIA GPU Computing Toolkit\CUDA\v12.3\bin\nvcc.exe"),
        (Join-Path $env:ProgramFiles "NVIDIA GPU Computing Toolkit\CUDA\v12.2\bin\nvcc.exe")
    )
    foreach ($path in $commonPaths) {
        if (Test-Path $path) {
            return $path
        }
    }

    return $null
}

function Ensure-CudaToolkit {
    if ($gpuInfo.Hint -ne "gpu") {
        return $null
    }

    $existingNvcc = Find-CudaCompiler
    if ($existingNvcc) {
        return $existingNvcc
    }

    Write-Step "Installing NVIDIA CUDA Toolkit"
    $winget = Ensure-Winget
    Invoke-External -FilePath $winget -Arguments @(
        "install",
        "--id", "Nvidia.CUDA",
        "-e",
        "--accept-source-agreements",
        "--accept-package-agreements",
        "--silent"
    )

    $installedNvcc = Find-CudaCompiler
    if (-not $installedNvcc) {
        Write-Host "CUDA Toolkit installation completed, but nvcc.exe was not found yet. A reboot or new shell may be required."
    }
    return $installedNvcc
}

function Find-NgrokExe {
    $resolved = Resolve-CommandPath @("ngrok")
    if ($resolved) {
        return $resolved
    }

    $commonPaths = @(
        (Join-Path $env:LocalAppData "Programs\ngrok\ngrok.exe"),
        (Join-Path $env:ProgramFiles "ngrok\ngrok.exe")
    )
    foreach ($path in $commonPaths) {
        if (Test-Path $path) {
            return $path
        }
    }

    return $null
}

function Ensure-Ngrok {
    $ngrokExe = Find-NgrokExe
    if ($ngrokExe) {
        return $ngrokExe
    }

    Write-Step "Installing ngrok"
    $winget = Ensure-Winget
    Invoke-External -FilePath $winget -Arguments @(
        "install",
        "--id", "Ngrok.Ngrok",
        "-e",
        "--accept-source-agreements",
        "--accept-package-agreements",
        "--silent"
    )

    $ngrokExe = Find-NgrokExe
    if (-not $ngrokExe) {
        throw "ngrok installation finished, but ngrok.exe could not be located."
    }
    return $ngrokExe
}

function Get-GpuInfo {
    $gpuNames = @()

    try {
        $gpuNames = Get-CimInstance Win32_VideoController -ErrorAction Stop |
            Where-Object {
                $_.Name -and
                $_.Name -notmatch "Microsoft Basic" -and
                $_.Name -notmatch "Remote Display"
            } |
            Select-Object -ExpandProperty Name
    } catch {
        $gpuNames = @()
    }

    $gpuNames = $gpuNames | Where-Object { $_ } | Select-Object -Unique
    if (-not $gpuNames -or $gpuNames.Count -eq 0) {
        return @{
            Hint = "cpu"
            Name = ""
            Acceleration = "cpu"
        }
    }

    $primary = $gpuNames[0].Trim()
    return @{
        Hint = "gpu"
        Name = $primary
        Acceleration = "auto"
    }
}

function Ensure-EnvFile([hashtable]$GpuInfo) {
    if (-not (Test-Path $envFile)) {
        Copy-Item $envExample $envFile
    }

    $content = Get-Content $envFile -ErrorAction SilentlyContinue
    $map = [ordered]@{}
    foreach ($line in $content) {
        if ($line -match "^\s*([^#=]+?)=(.*)$") {
            $map[$matches[1].Trim()] = $matches[2]
        }
    }

    $map["APP_HOST"] = $HostAddress
    $map["APP_PORT"] = "$Port"
    $map["OLLAMA_HOST"] = $OllamaHost
    $map["OLLAMA_MODEL"] = $Model
    $map["SYSTEM_GPU_HINT"] = $GpuInfo.Hint
    $map["SYSTEM_GPU_NAME"] = $GpuInfo.Name
    $map["OLLAMA_ACCELERATION"] = $GpuInfo.Acceleration

    $orderedKeys = @(
        "APP_HOST",
        "APP_PORT",
        "OLLAMA_HOST",
        "OLLAMA_MODEL",
        "OCR_API_KEY",
        "MAX_UPLOAD_MB",
        "REQUEST_TIMEOUT_SECONDS",
        "ALLOWED_MIME_TYPES",
        "IMAGE_DOWNLOAD_TIMEOUT_SECONDS",
        "OCR_SPEED_PRESET",
        "MAX_IMAGE_SIDE_PX",
        "IMAGE_JPEG_QUALITY",
        "SYSTEM_GPU_HINT",
        "SYSTEM_GPU_NAME",
        "OLLAMA_ACCELERATION",
        "REQUIRE_GPU",
        "INSTALL_CUDA",
        "NGROK_ENABLED",
        "NGROK_AUTHTOKEN",
        "NGROK_DOMAIN",
        "APP_ENV",
        "LOG_LEVEL",
        "MAX_CONCURRENCY",
        "OCR_TIMEOUT_SECONDS",
        "OCR_RETRY_ATTEMPTS",
        "OCR_RETRY_BACKOFF_SECONDS",
        "OLLAMA_KEEP_ALIVE"
    )

    $output = foreach ($key in $orderedKeys) {
        if ($map.Contains($key)) {
            "$key=$($map[$key])"
        }
    }
    Set-Content -Path $envFile -Value $output -Encoding UTF8
}

function Ensure-Venv([string]$PythonExe) {
    if (-not (Test-Path $venvPython)) {
        Write-Step "Creating Python virtual environment"
        Invoke-External -FilePath $PythonExe -Arguments @("-m", "venv", $venvDir)
    }
}

function Install-PythonDependencies {
    $requirementsHash = (Get-FileHash -Path $requirementsFile -Algorithm SHA256).Hash
    $installedHash = ""
    if (Test-Path $requirementsStateFile) {
        $installedHashLine = Get-Content $requirementsStateFile -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($installedHashLine) {
            $installedHash = $installedHashLine.Trim()
        }
    }

    if ((Test-Path $venvPython) -and $installedHash -eq $requirementsHash) {
        Write-Step "Python dependencies already up to date"
        return
    }

    Write-Step "Installing Python dependencies"
    Invoke-ExternalOptional -FilePath $venvPython -Arguments @("-m", "pip", "install", "--upgrade", "pip") | Out-Null
    Invoke-External -FilePath $venvPython -Arguments @("-m", "pip", "install", "-r", $requirementsFile)
    Set-Content -Path $requirementsStateFile -Value $requirementsHash -Encoding ASCII
}

function Start-Ollama([string]$OllamaExe, [string]$HostValue) {
    $hostOnly = $HostValue -replace "^https?://", ""
    $env:OLLAMA_HOST = $hostOnly
    $proc = Start-Process -FilePath $OllamaExe -ArgumentList "serve" -WorkingDirectory $projectRoot -RedirectStandardOutput $ollamaOut -RedirectStandardError $ollamaErr -PassThru
    Set-Content -Path $ollamaPidFile -Value $proc.Id -Encoding ASCII
}

function Start-Api {
    $env:APP_HOST = $HostAddress
    $env:APP_PORT = "$Port"
    $env:OLLAMA_HOST = $OllamaHost
    $env:OLLAMA_MODEL = $Model

    $proc = Start-Process -FilePath $venvPython -ArgumentList "start_api.py" -WorkingDirectory $projectRoot -RedirectStandardOutput $apiOut -RedirectStandardError $apiErr -PassThru
    Set-Content -Path $apiPidFile -Value $proc.Id -Encoding ASCII
}

function Start-Ngrok([string]$NgrokExe, [int]$TargetPort, [string]$NgrokAuthtoken, [string]$NgrokDomain) {
    if ($NgrokAuthtoken) {
        Invoke-External -FilePath $NgrokExe -Arguments @("config", "add-authtoken", $NgrokAuthtoken)
    }

    $arguments = @("http", "http://127.0.0.1:$TargetPort", "--log", "stdout")
    if ($NgrokDomain) {
        $arguments += @("--domain", $NgrokDomain)
    }

    $proc = Start-Process -FilePath $NgrokExe -ArgumentList $arguments -WorkingDirectory $projectRoot -RedirectStandardOutput $ngrokOut -RedirectStandardError $ngrokErr -PassThru
    Set-Content -Path $ngrokPidFile -Value $proc.Id -Encoding ASCII
}

function Get-NgrokPublicUrl {
    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:4040/api/tunnels" -TimeoutSec 5
            foreach ($tunnel in $response.tunnels) {
                if ($tunnel.public_url -and $tunnel.proto -eq "https") {
                    return $tunnel.public_url
                }
            }
            foreach ($tunnel in $response.tunnels) {
                if ($tunnel.public_url) {
                    return $tunnel.public_url
                }
            }
        } catch {
        }
        Start-Sleep -Seconds 2
    }

    return $null
}

function Get-OllamaProcessorStatus([string]$OllamaExe, [string]$ConfiguredModel) {
    try {
        $lines = & $OllamaExe ps 2>$null
        foreach ($line in $lines) {
            if ($line -like "$ConfiguredModel*") {
                if ($line -match "(\d+)%\s+GPU") {
                    return "gpu"
                }
                if ($line -match "(\d+)%\s+CPU") {
                    return "cpu"
                }
            }
        }
    } catch {
    }

    return "unknown"
}

$gpuInfo = Get-GpuInfo
if ($gpuInfo.Hint -eq "gpu") {
    Write-Host "Detected GPU: $($gpuInfo.Name)"
    Write-Host "Ollama will try to use the GPU automatically when the model runs."
} else {
    Write-Host "No dedicated GPU detected. The service will run in CPU mode."
}

$pythonExe = Ensure-Python
$ollamaExe = Ensure-Ollama
Ensure-Venv -PythonExe $pythonExe
Install-PythonDependencies
Ensure-EnvFile -GpuInfo $gpuInfo

$ngrokEnabled = Get-BoolFromString (Get-EnvValue -Key "NGROK_ENABLED" -Default "false")
$ngrokAuthtoken = Get-EnvValue -Key "NGROK_AUTHTOKEN"
$ngrokDomain = Get-EnvValue -Key "NGROK_DOMAIN"
$requireGpu = Get-BoolFromString (Get-EnvValue -Key "REQUIRE_GPU" -Default "false")
$installCuda = Get-BoolFromString (Get-EnvValue -Key "INSTALL_CUDA" -Default "true")
$ngrokRequested = $ngrokEnabled -or -not [string]::IsNullOrWhiteSpace($ngrokAuthtoken) -or -not [string]::IsNullOrWhiteSpace($ngrokDomain)
$ngrokUrl = $null
$cudaCompiler = $null
$cudaStatus = "not_applicable"

if ($gpuInfo.Hint -eq "gpu" -and $installCuda) {
    $cudaCompiler = Ensure-CudaToolkit
    if ($cudaCompiler) {
        Write-Host "CUDA Toolkit detected: $cudaCompiler"
        $cudaStatus = "installed"
    } else {
        $cudaStatus = "not_detected_after_install"
    }
} elseif ($gpuInfo.Hint -eq "gpu") {
    $existingCudaCompiler = Find-CudaCompiler
    if ($existingCudaCompiler) {
        $cudaCompiler = $existingCudaCompiler
        $cudaStatus = "installed"
    } else {
        $cudaStatus = "not_installed"
    }
}

$ollamaHealthUrl = "$OllamaHost/api/tags"
$apiHealthUrl = "http://127.0.0.1:$Port/health"

Write-Step "Ensuring Ollama is running"
if (-not (Wait-ForHttp -Url $ollamaHealthUrl -TimeoutSeconds 2)) {
    Start-Ollama -OllamaExe $ollamaExe -HostValue $OllamaHost
    if (-not (Wait-ForHttp -Url $ollamaHealthUrl -TimeoutSeconds 60)) {
        throw "Ollama did not become ready in time."
    }
}

Write-Step "Ensuring model is installed"
$env:OLLAMA_HOST = $OllamaHost
& $ollamaExe show $Model *> $null
if ($LASTEXITCODE -ne 0) {
    Invoke-External -FilePath $ollamaExe -Arguments @("pull", $Model)
}

Write-Step "Starting API"
if (-not (Wait-ForHttp -Url $apiHealthUrl -TimeoutSeconds 2)) {
    Start-Api
    if (-not (Wait-ForHttp -Url $apiHealthUrl -TimeoutSeconds 180)) {
        throw "API did not become ready in time."
    }
}

if ($ngrokRequested) {
    if ([string]::IsNullOrWhiteSpace($ngrokAuthtoken)) {
        Write-Host "ngrok requested but NGROK_AUTHTOKEN is empty. Skipping tunnel startup."
    } else {
        Write-Step "Starting ngrok tunnel"
        $ngrokExe = Ensure-Ngrok
        Start-Ngrok -NgrokExe $ngrokExe -TargetPort $Port -NgrokAuthtoken $ngrokAuthtoken -NgrokDomain $ngrokDomain
        $ngrokUrl = Get-NgrokPublicUrl
        if (-not $ngrokUrl) {
            Write-Host "ngrok started but public URL could not be detected yet. Check .runtime\\ngrok.stdout.log"
        }
    }
}

$serverIp = try {
    (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop | Where-Object {
        $_.IPAddress -notlike "127.*" -and $_.PrefixOrigin -ne "WellKnown"
    } | Select-Object -First 1 -ExpandProperty IPAddress)
} catch {
    $null
}
$publicIp = Get-PublicIp

Write-Host ""
Write-Host "API is ready."
Write-Host "Local URL: http://127.0.0.1:$Port"
if ($serverIp) {
    Write-Host "Host URL: http://$serverIp`:$Port"
}
if ($publicIp) {
    Write-Host "Public URL: http://$publicIp`:$Port"
}
if ($ngrokUrl) {
    Write-Host "ngrok URL: $ngrokUrl"
}
$processorStatus = Get-OllamaProcessorStatus -OllamaExe $ollamaExe -ConfiguredModel $Model
if ($processorStatus -eq "gpu") {
    Write-Host "Runtime Processor: GPU"
} elseif ($processorStatus -eq "cpu") {
    Write-Host "Runtime Processor: CPU"
    if ($gpuInfo.Hint -eq "gpu") {
        Write-Host "Warning: GPU was detected on this machine, but Ollama is still running the model on CPU."
    }
    if ($requireGpu) {
        Write-Host "REQUIRE_GPU is enabled, so /ready will report not ready until Ollama loads the model on GPU."
    }
}
Write-Host "CUDA Status: $cudaStatus"
if ($cudaCompiler) {
    Write-Host "CUDA Compiler: $cudaCompiler"
}
Write-Host "Model: $Model"
if ($gpuInfo.Hint -eq "gpu") {
    Write-Host "Acceleration: GPU available ($($gpuInfo.Name))"
} else {
    Write-Host "Acceleration: CPU"
}
