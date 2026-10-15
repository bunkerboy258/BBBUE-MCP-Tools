[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectPath,
    [Parameter(Mandatory = $true)]
    [string]$EnginePath,
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
    [string]$PerformanceProfile = 'Economy',
    [ValidateRange(-1, 240)]
    [int]$MaxFPS = -1,
    [ValidatePattern('^[A-Za-z0-9-]*$')]
    [string]$Culture = ''
)

$ErrorActionPreference = 'Stop'
$projectFile = [IO.Path]::GetFullPath($ProjectPath)
$editorPath = Join-Path ([IO.Path]::GetFullPath($EnginePath)) 'Engine\Binaries\Win64\UnrealEditor.exe'
if (-not (Test-Path -LiteralPath $projectFile -PathType Leaf) -or -not (Test-Path -LiteralPath $editorPath -PathType Leaf))
{
    throw '请提供现有 uproject 文件与 UE5.8 根目录'
}
if (-not $PythonPath)
{
    $PythonPath = (Get-Command python -ErrorAction Stop).Source
}
$service = & (Join-Path $PSScriptRoot 'Start-BBBMcpService.ps1') -ProjectPath $projectFile -Port $Port -PythonPath $PythonPath
$env:BBB_MCP_PROJECT = $projectFile
$route = & $PythonPath -B -c 'import os,sys;sys.path.insert(0,sys.argv[1]);from MCP.mcp_host_registry import project_key;print(project_key(os.environ["BBB_MCP_PROJECT"]))' (Split-Path $PSScriptRoot -Parent)
if ($LASTEXITCODE -ne 0)
{
    throw '项目身份核验失败'
}
$endpoint = "http://127.0.0.1:$Port/projects/$route/mcp"
$projectPattern = '(?i)(?:^|\s)"?' + [Regex]::Escape($projectFile) + '"?(?=\s|$)'
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
    $editors = @(Get-CimInstance Win32_Process -Filter "Name = 'UnrealEditor.exe'" | Where-Object { $_.CommandLine.Replace('/', '\') -match $projectPattern -and $_.CommandLine -notmatch '(?i)-BBBMcpHostRole=Test(\s|$)' })
    if ($editors.Count -eq 0)
    {
        $frames = @{ HighThroughput = 120; Balanced = 60; Economy = 30; GamingBackground = 15 }[$PerformanceProfile]
        if ($MaxFPS -ge 0)
        {
            $frames = $MaxFPS
        }
        $editorArguments = @('"' + $projectFile + '"', '/Engine/Maps/Entry', '-Multiprocess', '-NoSplash', '-AutoDeclinePackageRecovery',
            "-BBBMcpServicePort=$Port", ('-BBBMcpServicePython="' + $PythonPath + '"'), "-BBBMcpPerformanceProfile=$PerformanceProfile", "-BBBMcpMaxFPS=$frames",
            '-ini:EditorPerProjectUserSettings:[/Script/ModelContextProtocolEngine.ModelContextProtocolSettings]:bAutoStartServer=False',
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
        if state.get('connection')=='ready' and state['host']['verified']:
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
