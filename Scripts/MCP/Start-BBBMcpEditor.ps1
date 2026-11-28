[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectPath,
    [string]$EnginePath = '',
    [ValidateRange(1, 65535)]
    [int]$Port = 8000,
    [string]$PythonPath = '',
    [ValidateRange(1, 600)]
    [int]$TimeoutSeconds = 90,
    [switch]$EnableRendering,
    [switch]$Visible,
    [switch]$EnableAudio,
    [switch]$MuteAudioOutput,
    [switch]$EnableSlateInspector,
    [ValidateSet('HighThroughput', 'Balanced', 'Economy', 'GamingBackground')]
    [string]$PerformanceProfile = 'Balanced',
    [ValidateRange(-1, 240)]
    [int]$MaxFPS = -1,
    [ValidatePattern('^[A-Za-z0-9-]*$')]
    [string]$Culture = ''
)

$ErrorActionPreference = 'Stop'
$projectFile = [IO.Path]::GetFullPath($ProjectPath)
$projectPattern = '(?i)(?:^|\s)"?' + [Regex]::Escape($projectFile) + '"?(?=\s|$)'
if (-not (Test-Path -LiteralPath $projectFile -PathType Leaf))
{
    throw '请提供现有 uproject 文件'
}
if (-not $EnginePath)
{
    $association = (Get-Content -LiteralPath $projectFile -Raw | ConvertFrom-Json).EngineAssociation
    if ($association)
    {
        $sourceBuilds = Get-ItemProperty -LiteralPath 'HKCU:\Software\Epic Games\Unreal Engine\Builds' -ErrorAction SilentlyContinue
        if ($sourceBuilds -and $sourceBuilds.PSObject.Properties[$association])
        {
            $EnginePath = $sourceBuilds.PSObject.Properties[$association].Value
        }
        if (-not $EnginePath)
        {
            $binaryBuild = Get-ItemProperty -LiteralPath ('HKLM:\SOFTWARE\EpicGames\Unreal Engine\' + $association) -ErrorAction SilentlyContinue
            if ($binaryBuild)
            {
                $EnginePath = $binaryBuild.InstalledDirectory
            }
        }
        if (-not $EnginePath)
        {
            $launcherFile = Join-Path $env:ProgramData 'Epic\UnrealEngineLauncher\LauncherInstalled.dat'
            if (Test-Path -LiteralPath $launcherFile)
            {
                $install = (Get-Content -LiteralPath $launcherFile -Raw | ConvertFrom-Json).InstallationList |
                    Where-Object AppName -eq ('UE_' + $association) | Select-Object -First 1
                if ($install)
                {
                    $EnginePath = $install.InstallLocation
                }
            }
        }
    }
    if (-not $EnginePath)
    {
        $running = @(Get-CimInstance Win32_Process -Filter "Name = 'UnrealEditor.exe'" |
            Where-Object { $_.ExecutablePath -and $_.CommandLine -and
                $_.CommandLine.Replace('/', '\') -match $projectPattern })
        if ($running.Count -eq 1)
        {
            $EnginePath = [IO.Directory]::GetParent($running[0].ExecutablePath).Parent.Parent.Parent.FullName
        }
    }
    if (-not $EnginePath)
    {
        throw '项目关联未找到已安装引擎 请指定 EnginePath'
    }
}
$editorPath = Join-Path ([IO.Path]::GetFullPath($EnginePath)) 'Engine\Binaries\Win64\UnrealEditor.exe'
if (-not (Test-Path -LiteralPath $editorPath -PathType Leaf))
{
    throw '引擎目录缺少 UnrealEditor.exe'
}
$versionFile = Join-Path ([IO.Path]::GetFullPath($EnginePath)) 'Engine\Build\Build.version'
$version = Get-Content -LiteralPath $versionFile -Raw | ConvertFrom-Json
if ($version.MajorVersion -ne 5 -or $version.MinorVersion -ne 9)
{
    throw 'MCP 需要 UE 5.9 编辑器'
}
if (-not $PythonPath)
{
    $PythonPath = (Get-Command python -ErrorAction Stop).Source
}
$service = & (Join-Path $PSScriptRoot 'Start-BBBMcpService.ps1') -ProjectPath $projectFile -Port $Port -PythonPath $PythonPath
$env:BBB_MCP_PROJECT = $projectFile
$routeCode = @'
import os,sys
sys.path.insert(0,sys.argv[1])
from MCP.mcp_host_registry import project_key
print(project_key(os.environ['BBB_MCP_PROJECT']))
'@
$route = $routeCode | & $PythonPath -B - (Split-Path $PSScriptRoot -Parent)
if ($LASTEXITCODE -ne 0)
{
    throw '项目身份核验失败'
}
$endpoint = "http://127.0.0.1:$Port/projects/$route/mcp"
$hashAlgorithm = [Security.Cryptography.SHA256]::Create()
try
{
    $projectHash = [BitConverter]::ToString($hashAlgorithm.ComputeHash([Text.Encoding]::UTF8.GetBytes($projectFile.ToLowerInvariant()))).Replace('-', '')
}
finally
{
    $hashAlgorithm.Dispose()
}
$hostMutex = [Threading.Mutex]::new($false, 'Local\BBBMcpEditorStart_' + $projectHash)
$ownsMutex = $false
try
{
    try
    {
        $ownsMutex = $hostMutex.WaitOne(60000)
    }
    catch [Threading.AbandonedMutexException]
    {
        $ownsMutex = $true
    }
    if (-not $ownsMutex)
    {
        throw '项目编辑器正在启动 请稍后复用当前服务'
    }
    $editors = @(Get-CimInstance Win32_Process -Filter "Name = 'UnrealEditor.exe'" | Where-Object { $_.CommandLine -and $_.CommandLine.Replace('/', '\') -match $projectPattern })
    if ($editors.Count -gt 1 -or ($editors.Count -eq 1 -and $editors[0].ExecutablePath -ine $editorPath))
    {
        throw '项目已有其他编辑器宿主 严禁多开 请先核验归属并复用现有宿主'
    }
    if ($editors.Count -eq 1)
    {
        $commandLine = $editors[0].CommandLine
        if (($Visible -or $EnableRendering) -and $commandLine -match '(?i)(?:^|\s)-NullRHI(?:\s|$)')
        {
            throw '现有宿主为无渲染模式 请先完成宿主交接'
        }
        if ($EnableAudio -and $commandLine -notmatch '(?i)(?:^|\s)-ini:Engine:\[Audio\]:UnfocusedVolumeMultiplier=1\.0(?:\s|$)')
        {
            throw '现有宿主未开启后台音频 请先完成宿主交接'
        }
        if ($EnableAudio -and $commandLine -notmatch '(?i)-ini:EditorPerProjectUserSettings:\[/Script/UnrealEd\.LevelEditorMiscSettings\]:bAllowBackgroundAudio=True(?:\s|$)')
        {
            throw '现有宿主未开启编辑器后台音频 请先完成宿主交接'
        }
        if ($Culture -and $commandLine -notmatch ('(?i)(?:^|\s)-culture=' + [Regex]::Escape($Culture) + '(?:\s|$)'))
        {
            throw '现有宿主语言和请求不一致 请先完成宿主交接'
        }
    }
    if ($editors.Count -eq 0)
    {
        $frames = @{ HighThroughput = 120; Balanced = 60; Economy = 30; GamingBackground = 15 }[$PerformanceProfile]
        if ($MaxFPS -ge 0)
        {
            $frames = $MaxFPS
        }
        $editorArguments = @('"' + $projectFile + '"', '-NoSplash', '-AutoDeclinePackageRecovery',
            "-BBBMcpServicePort=$Port", ('-BBBMcpServicePython="' + $PythonPath + '"'), "-BBBMcpPerformanceProfile=$PerformanceProfile", "-BBBMcpMaxFPS=$frames",
            '-ini:EditorPerProjectUserSettings:[/Script/ModelContextProtocol.ModelContextProtocolSettings]:bAutoStartServer=False',
            ('-ExecCmds="t.MaxFPS ' + $frames + ',t.IdleWhenNotForeground 0"'))
        if (-not $EnableRendering -and -not $Visible)
        {
            $editorArguments += '-NullRHI'
        }
        if (-not $Visible)
        {
            $editorArguments += @('-Unattended', '-RenderOffscreen')
        }
        if (-not $EnableAudio)
        {
            $editorArguments += '-NoSound'
        }
        if ($EnableAudio)
        {
            $editorArguments += @('-AudioMixer', '-ini:Engine:[Audio]:UnfocusedVolumeMultiplier=1.0', '-ini:EditorPerProjectUserSettings:[/Script/UnrealEd.LevelEditorMiscSettings]:bAllowBackgroundAudio=True')
        }
        if ($MuteAudioOutput)
        {
            $editorArguments += '-MuteAudio'
        }
        if ($EnableSlateInspector)
        {
            $editorArguments += '-EnablePlugins=SlateInspectorToolset'
        }
        if ($Culture)
        {
            $editorArguments += '-culture=' + $Culture
        }
        $windowStyle = 'Hidden'
        if ($Visible)
        {
            $windowStyle = 'Normal'
        }
        $createdEditor = Start-Process -FilePath $editorPath -ArgumentList $editorArguments -WindowStyle $windowStyle -PassThru
    }
    $env:BBB_MCP_URL = $endpoint
    $env:BBB_MCP_WAIT_SECONDS = "$TimeoutSeconds"
    $readiness = @'
import json,os,sys,time
sys.path.insert(0,sys.argv[1])
from MCP.mcp_call import McpSession
with McpSession(timeout_seconds=10) as session:
    deadline=time.monotonic()+int(os.environ['BBB_MCP_WAIT_SECONDS'])
    while time.monotonic()<deadline:
        state=session.inspect_tasks()
        if state.get('connection')=='ready' and state['host']['verified'] and state.get('source',{}).get('current'):
            print(json.dumps({'Endpoint':os.environ['BBB_MCP_URL'],'ProcessId':state['host']['process_id'],'ServiceProcessId':None}))
            break
        time.sleep(1)
    else:
        raise RuntimeError('EDITOR_CONNECT_TIMEOUT: inspect_tasks 返回的 hosts 包含具体进程接入状态')
'@
    $hostInfo = $readiness | & $PythonPath -B - (Split-Path $PSScriptRoot -Parent)
    if ($LASTEXITCODE -ne 0)
    {
        throw '编辑器接入等待结束 当前进程继续保留 请检查服务状态'
    }
    $result = $hostInfo | ConvertFrom-Json
    $result.ServiceProcessId = $service.ProcessId
    $result
}
finally
{
    if ($ownsMutex)
    {
        $hostMutex.ReleaseMutex()
    }
    $hostMutex.Dispose()
}
