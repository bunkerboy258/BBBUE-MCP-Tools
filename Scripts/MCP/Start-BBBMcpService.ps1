[CmdletBinding()]
param(
    [string]$ProjectPath = '',
    [ValidateRange(1, 65535)]
    [int]$Port = 8000,
    [string]$PythonPath = '',
    [switch]$InstallAtLogon
)

$ErrorActionPreference = 'Stop'
if (-not $PythonPath)
{
    $PythonPath = (Get-Command python -ErrorAction Stop).Source
}
$serviceScript = Join-Path $PSScriptRoot 'mcp_service.py'
$serviceArguments = @('-B', $serviceScript, '--ensure', '--port', "$Port")
if ($ProjectPath)
{
    $serviceArguments += @('--project-file', [IO.Path]::GetFullPath($ProjectPath))
}
$serviceResult = & $PythonPath @serviceArguments
if ($LASTEXITCODE -ne 0)
{
    throw '常驻服务启动失败 具体原因见当前用户 LOCALAPPDATA\BBBMcp\startup.log'
}
$identity = $serviceResult | ConvertFrom-Json
if ($InstallAtLogon)
{
    $userIdentity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $actionArguments = '-B "' + $serviceScript + '" --supervise --port ' + $Port
    $supervisorPython = Join-Path (Split-Path $PythonPath -Parent) 'pythonw.exe'
    if (-not (Test-Path -LiteralPath $supervisorPython -PathType Leaf))
    {
        $supervisorPython = $PythonPath
    }
    $action = New-ScheduledTaskAction -Execute $supervisorPython -Argument $actionArguments
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $userIdentity
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    $principal = New-ScheduledTaskPrincipal -UserId $userIdentity -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName ('BBBMcpService-' + $Port) -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
    Start-ScheduledTask -TaskName ('BBBMcpService-' + $Port)
}
[PSCustomObject]@{ Endpoint = "http://127.0.0.1:$Port/mcp"; ProcessId = $identity.process_id; Service = 'ready' }
