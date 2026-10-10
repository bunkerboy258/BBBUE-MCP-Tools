Set-StrictMode -Version 1.0
$ErrorActionPreference = 'Stop'
$startupScript = Join-Path $PSScriptRoot '..\Scripts\MCP\Start-UE58OfficialMcpEditor.ps1'
$testProjectPath = [System.IO.Path]::GetFullPath((Join-Path $env:TEMP 'BBBMcpStartupTest\Test.uproject'))
$testEnginePath = [System.IO.Path]::GetFullPath((Join-Path $env:TEMP 'BBBMcpStartupTest\UE_5.8'))
$testEditorPath = Join-Path $testEnginePath 'Engine\Binaries\Win64\UnrealEditor.exe'
$global:bbbStartupProjectPath = $testProjectPath
$global:bbbStartupEditorPath = $testEditorPath
$global:bbbStartupPythonPath = (Get-Command python).Source
$global:bbbStartupGatewayPath = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\Scripts\MCP\mcp_task_gateway.py'))
$global:bbbStartupTest = $null

<#
/**
 * 失败时立即报警
 * @param Condition	通过条件
 * @param Message	失败说明
 * @return 测试结果
 */
#>
function global:Assert-StartupTest
{
    param([bool]$Condition, [string]$Message)

    if (-not $Condition)
    {
        throw $Message
    }
}

<#
/**
 * 隔离真实文件访问
 * @param LiteralPath	测试路径
 * @return 测试结果
 */
#>
function global:Test-Path
{
    param([string]$LiteralPath)

    return $LiteralPath -eq $global:bbbStartupProjectPath -or $LiteralPath -eq $global:bbbStartupEditorPath -or $LiteralPath -eq $global:bbbStartupPythonPath -or $LiteralPath -eq $global:bbbStartupGatewayPath
}

<#
/**
 * 隔离真实进程列表
 * @param ClassName	进程查询类
 * @param Filter	查询条件
 * @return 测试结果
 */
#>
function global:Get-CimInstance
{
    param($ClassName, $Filter)

    if ($Filter -like 'ProcessId = *')
    {
        return [pscustomobject]@{ ProcessId = 987655; ExecutablePath = $global:bbbStartupPythonPath; CommandLine = ($global:bbbStartupTest.GatewayArguments -join ' ') }
    }

    return $global:bbbStartupTest.Editors
}

<#
/**
 * 模拟端口归属
 * @param LocalAddress	地址
 * @param LocalPort	端口
 * @param State	监听状态
 * @param ErrorAction	错误处理
 * @return 测试结果
 */
#>
function global:Get-NetTCPConnection
{
    param($LocalAddress, $LocalPort, $State, $ErrorAction)

    if ($LocalPort -eq 8000)
    {
        if ($global:bbbStartupTest.GatewayStarted)
        {
            return [pscustomobject]@{ OwningProcess = 987655 }
        }
        return
    }

    if ($global:bbbStartupTest.Started -or $global:bbbStartupTest.Editors.Count -gt 0)
    {
        return [pscustomobject]@{ OwningProcess = 987654 }
    }

    if ($global:bbbStartupTest.PortOccupied)
    {
        return [pscustomobject]@{ OwningProcess = 123456 }
    }
}

<#
/**
 * 只返回替身 不启动真实进程
 * @param FilePath	编辑器路径
 * @param ArgumentList	启动参数
 * @param WindowStyle	窗口模式
 * @param PassThru	返回进程
 * @return 测试结果
 */
#>
function global:Start-Process
{
    param($FilePath, $ArgumentList, $WindowStyle, [switch]$PassThru)

    if ($FilePath -eq $global:bbbStartupPythonPath)
    {
        Assert-StartupTest ($WindowStyle -eq 'Hidden') '启动网关必须隐藏'
        Assert-StartupTest ($ArgumentList.Count -eq 12) '网关参数被 PowerShell 表达式拆开'
        Assert-StartupTest ($ArgumentList[1] -eq ('"' + $global:bbbStartupGatewayPath + '"')) '网关脚本必须作为一个完整参数'
        Assert-StartupTest ($ArgumentList[7] -eq ('"' + (Split-Path $global:bbbStartupProjectPath -Parent) + '"')) '项目目录必须作为一个完整参数'
        $global:bbbStartupTest.GatewayStarted = $true
        $global:bbbStartupTest.GatewayArguments = $ArgumentList
        return $global:bbbStartupTest.GatewayProcess
    }

    Assert-StartupTest ($FilePath -eq $global:bbbStartupEditorPath) '编辑器路径不匹配'
    Assert-StartupTest ($WindowStyle -eq 'Hidden') '启动宿主必须隐藏'
    $global:bbbStartupTest.Started = $true
    $global:bbbStartupTest.Arguments = $ArgumentList
    return $global:bbbStartupTest.Process
}

<#
/**
 * 模拟宿主存活检查
 * @param Id	测试进程编号
 * @param ErrorAction	错误处理
 * @return 测试结果
 */
#>
function global:Get-Process
{
    param($Id, $ErrorAction)

    Assert-StartupTest ($Id -eq 987654) '进程检查目标不匹配'
    if (-not $global:bbbStartupTest.EarlyExit)
    {
        return $global:bbbStartupTest.Process
    }
}

<#
/**
 * 记录清理意图 不终止真实进程
 * @param Id	测试进程编号
 * @param ErrorAction	错误处理
 * @return 测试结果
 */
#>
function global:Stop-Process
{
    param($Id, $ErrorAction)

    Assert-StartupTest ($Id -in @(987654, 987655)) '不允许关闭非测试宿主或网关'
    $global:bbbStartupTest.Stopped = $true
}

<#
/**
 * 只返回模拟协议响应 不访问网络
 * @param Uri	地址
 * @param Method	方法
 * @param ContentType	内容类型
 * @param Headers	协议头
 * @param Body	请求
 * @param TimeoutSec	超时
 * @param ErrorAction	错误处理
 * @return 测试结果
 */
#>
function global:Invoke-WebRequest
{
    param($Uri, $Method, $ContentType, $Headers, $Body, $TimeoutSec, $ErrorAction)

    Assert-StartupTest ($Uri -eq 'http://127.0.0.1:8000/mcp' -or $Uri -like 'http://127.0.0.1:18000/bbb-mcp-*') '协议地址不匹配'
    if ($Method -eq 'Delete')
    {
        $global:bbbStartupTest.DeletedSessions += 1
        return [pscustomobject]@{ Headers = @{}; Content = '' }
    }

    $request = $Body | ConvertFrom-Json
    if ($request.method -eq 'initialize')
    {
        return [pscustomobject]@{
            Headers = @{ 'Mcp-Session-Id' = 'startup-test'; 'Content-Type' = 'application/json' }
            Content = '{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-11-25"}}'
        }
    }

    Assert-StartupTest ($Headers['Mcp-Session-Id'] -eq 'startup-test') '缺少会话标识'
    Assert-StartupTest ($Headers['MCP-Protocol-Version'] -eq '2025-11-25') '缺少协商协议版本'
    if ($request.method -eq 'notifications/initialized')
    {
        return [pscustomobject]@{ Headers = @{}; Content = '' }
    }

    $text = ''
    if ($request.id -eq 2)
    {
        Assert-StartupTest ($request.params.name -eq 'list_toolsets') '未实际发现工具'
        $text = '- PythonTypes.BBBMcpRuntimeToolset_0x1234ABCD: test'
    }

    if ($request.id -eq 3)
    {
        Assert-StartupTest ($request.params.arguments.toolset_name -eq 'PythonTypes.BBBMcpRuntimeToolset_0x1234ABCD') '未使用实际发现的带哈希名称'
        Assert-StartupTest ($request.params.arguments.tool_name -eq 'inspect_mcp_performance') '未回读性能状态'
        $performance = @{
            process_id = 987654
            profile = $global:bbbStartupTest.Profile
            max_fps = $global:bbbStartupTest.FPS
            priority = $global:bbbStartupTest.Priority
            background_cpu_throttle = $false
            idle_when_not_foreground = 0
            matches_configured_settings = $true
        }
        $text = @{ returnValue = ($performance | ConvertTo-Json -Compress) } | ConvertTo-Json -Compress
    }

    $response = @{
        jsonrpc = '2.0'
        id = $request.id
        result = @{ isError = $false; content = @(@{ type = 'text'; text = $text }) }
    } | ConvertTo-Json -Depth 8 -Compress
    return [pscustomobject]@{
        Headers = @{ 'Content-Type' = 'text/event-stream' }
        Content = "data: {`"jsonrpc`":`"2.0`",`"id`":999,`"result`":{}}`n`ndata: $response`n`n"
    }
}

<#
/**
 * 验证公开网关活动回读 不访问实际网络
 * @param Uri\t公开入口
 * @param Method\tHTTP 方法
 * @param ContentType\t内容类型
 * @param Headers\t会话头
 * @param Body\t请求
 * @param TimeoutSec\t超时
 * @param ErrorAction\t错误处理
 * @return 网关活动报告
 */
#>
function global:Invoke-RestMethod
{
    param($Uri, $Method, $ContentType, $Headers, $Body, $TimeoutSec, $ErrorAction)

    Assert-StartupTest ($Uri -eq 'http://127.0.0.1:8000/mcp') '网关公开地址不匹配'
    $request = $Body | ConvertFrom-Json
    Assert-StartupTest ($request.params.name -eq 'inspect_editor_tasks') '未回读任务保护'
    $state = @{ activity = @{ process_id = 987654 }; host_changed = $false; draining = $false }
    return [pscustomobject]@{ result = @{ isError = $false; content = @(@{ text = ($state | ConvertTo-Json -Depth 5 -Compress) }) } }
}

<#
/**
 * 重置隔离测试状态
 * @param Profile	性能档位
 * @param FPS	帧率上限
 * @param Priority	优先级
 * @return 测试结果
 */
#>
function New-StartupTestState
{
    param([string]$Profile, [int]$FPS, [string]$Priority)

    $process = [pscustomobject]@{ Id = 987654; PriorityClass = ''; HasExited = $false }
    $process | Add-Member -MemberType ScriptMethod -Name WaitForExit -Value { param($Milliseconds) return $true }
    $gateway = [pscustomobject]@{ Id = 987655; HasExited = $false }
    $gateway | Add-Member -MemberType ScriptMethod -Name WaitForExit -Value { param($Milliseconds) return $true }
    $global:bbbStartupTest = [pscustomobject]@{
        Profile = $Profile
        FPS = $FPS
        Priority = $Priority
        Editors = @()
        Process = $process
        GatewayProcess = $gateway
        GatewayStarted = $false
        GatewayArguments = @()
        Started = $false
        Stopped = $false
        EarlyExit = $false
        PortOccupied = $false
        Arguments = @()
        DeletedSessions = 0
    }
}

<#
/**
 * 验证拒绝或失败的正确处理
 * @param Expected	预期错误文本
 * @return 测试结果
 */
#>
function Invoke-StartupFailureTest
{
    param([string]$Expected)

    $failed = $false
    try
    {
        $null = & $startupScript -ProjectPath $testProjectPath -EnginePath $testEnginePath -BackendPort 18000 -TimeoutSeconds 3
    }
    catch
    {
        $failed = $_.Exception.Message -like "*$Expected*"
        if (-not $failed)
        {
            throw
        }
    }

    Assert-StartupTest $failed '预期失败未发生'
}

$cases = @(
    @{ Input = 'Speed'; Profile = 'Speed'; FPS = 120; Priority = 'Normal'; Extra = @{} },
    @{ Input = 'Balanced'; Profile = 'Balanced'; FPS = 60; Priority = 'Normal'; Extra = @{} },
    @{ Input = 'Economy'; Profile = 'Economy'; FPS = 30; Priority = 'BelowNormal'; Extra = @{} },
    @{ Input = 'GamingBackground'; Profile = 'GamingBackground'; FPS = 15; Priority = 'BelowNormal'; Extra = @{} },
    @{ Input = 'gamingbackground'; Profile = 'GamingBackground'; FPS = 10; Priority = 'BelowNormal'; Extra = @{ MaxFPS = 10 } },
    @{ Input = 'GamingBackground'; Profile = 'GamingBackground'; FPS = 15; Priority = 'BelowNormal'; Extra = @{ EnableRendering = $true } }
)

foreach ($case in $cases)
{
    New-StartupTestState $case.Profile $case.FPS $case.Priority
    $extra = $case.Extra
    $result = & $startupScript -ProjectPath $testProjectPath -EnginePath $testEnginePath -BackendPort 18000 -PerformanceProfile $case.Input -TimeoutSeconds 3 @extra | ConvertFrom-Json
    Assert-StartupTest ($result.Status -eq 'Ready') '启动未报告就绪'
    Assert-StartupTest ($global:bbbStartupTest.Process.PriorityClass -eq $case.Priority) '启动优先级不匹配'
    Assert-StartupTest ($global:bbbStartupTest.Arguments -contains ('"' + $testProjectPath + '"')) '项目参数不匹配'
    Assert-StartupTest ($global:bbbStartupTest.Arguments -contains "-BBBMcpMaxFPS=$($case.FPS)") '帧率参数不匹配'
    Assert-StartupTest ($global:bbbStartupTest.DeletedSessions -ge 2) '协议测试会话未释放'
    Assert-StartupTest ($result.TaskProtection -eq 'Required' -and $result.GatewayProcessId -eq 987655) '共享任务保护未启用'
    Assert-StartupTest ($global:bbbStartupTest.Arguments -contains '-ModelContextProtocolPort=18000') '官方后端没有隔离端口'
    Assert-StartupTest ($global:bbbStartupTest.Arguments -contains '-Multiprocess') '资产宿主缺少构建锁隔离参数'
    Assert-StartupTest (($global:bbbStartupTest.Arguments -join ' ') -match 'ServerUrlPath=/bbb-mcp-[a-f0-9]{32}') '官方后端缺少私有路径'
    Assert-StartupTest (-not $global:bbbStartupTest.Stopped) '就绪宿主被错误关闭'
    Assert-StartupTest ($global:bbbStartupTest.Arguments -contains '-RenderOffscreen') '渲染模式不匹配'
    Assert-StartupTest (($global:bbbStartupTest.Arguments -contains '-NullRHI') -ne [bool]$extra['EnableRendering']) '无渲染模式不匹配'
}

New-StartupTestState 'Speed' 120 'Normal'
$global:bbbStartupTest.Editors = @([pscustomobject]@{ ProcessId = 987654; ExecutablePath = $testEditorPath; CommandLine = "$testProjectPath -ModelContextProtocolStartServer" })
Invoke-StartupFailureTest '未使用共享保护入口'
Assert-StartupTest (-not $global:bbbStartupTest.Started -and -not $global:bbbStartupTest.Stopped) '不匹配宿主不得启动或终止'

New-StartupTestState 'GamingBackground' 15 'BelowNormal'
$global:bbbStartupTest.Editors = @([pscustomobject]@{ ProcessId = 987654; ExecutablePath = $testEditorPath; CommandLine = "$testProjectPath -ModelContextProtocolStartServer -NullRHI -RenderOffscreen -ModelContextProtocolPort=18000 -BBBProtectedMcpPort=8000 -BBBProtectedMcpKey=12345678901234567890123456789012" })
Invoke-StartupFailureTest '宿主性能档位与请求不一致'
Assert-StartupTest (-not $global:bbbStartupTest.Started -and -not $global:bbbStartupTest.Stopped) '已有宿主的档位不匹配不得启动或终止'
Assert-StartupTest ($global:bbbStartupTest.DeletedSessions -eq 1) '失败测试会话未释放'

New-StartupTestState 'Speed' 120 'Normal'
$global:bbbStartupTest.EarlyExit = $true
Invoke-StartupFailureTest '在就绪前退出'
Assert-StartupTest $global:bbbStartupTest.Stopped '失败时必须清理自己创建的宿主'

New-StartupTestState 'Speed' 120 'Normal'
$global:bbbStartupTest.PortOccupied = $true
Invoke-StartupFailureTest '被其他进程占用'
Assert-StartupTest (-not $global:bbbStartupTest.Started -and -not $global:bbbStartupTest.Stopped) '端口冲突不得操作进程'

Write-Output 'PASS startup 6 profile cases and 4 refusal or cleanup cases no real process or HTTP calls'
