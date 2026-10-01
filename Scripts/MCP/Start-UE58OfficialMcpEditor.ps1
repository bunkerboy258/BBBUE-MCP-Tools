[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectPath,
    [Parameter(Mandatory = $true)]
    [string]$EnginePath,
    [ValidateRange(1, 65535)]
    [int]$Port = 8000,
    [ValidateRange(1, 600)]
    [int]$TimeoutSeconds = 90,
    [switch]$EnableRendering,
    [ValidateSet('Speed', 'Balanced', 'Economy', 'GamingBackground')]
    [string]$PerformanceProfile = 'Speed',
    [ValidateRange(-1, 240)]
    [int]$MaxFPS = -1
)

$projectPath = [System.IO.Path]::GetFullPath($ProjectPath)
$engineRoot = [System.IO.Path]::GetFullPath($EnginePath)
$editorPath = Join-Path $engineRoot 'Engine\Binaries\Win64\UnrealEditor.exe'
$endpoint = "http://127.0.0.1:$Port/mcp"
$portArgumentPattern = "(?i)-ModelContextProtocolPort=$Port(\s|$)"

if (-not (Test-Path -LiteralPath $projectPath))
{
    throw "UE 项目不存在: $projectPath"
}

if (-not (Test-Path -LiteralPath $editorPath))
{
    throw "UE5.8 编辑器不存在: $editorPath"
}

$PerformanceProfile = @{
    Speed = 'Speed'
    Balanced = 'Balanced'
    Economy = 'Economy'
    GamingBackground = 'GamingBackground'
}[$PerformanceProfile]

$profileFrames = @{
    Speed = 120
    Balanced = 60
    Economy = 30
    GamingBackground = 15
}

if ([System.IO.Path]::GetExtension($projectPath) -ne '.uproject')
{
    throw '项目路径必须是 uproject 文件'
}

$profilePriorities = @{
    Speed = 'Normal'
    Balanced = 'Normal'
    Economy = 'BelowNormal'
    GamingBackground = 'BelowNormal'
}
$frameLimit = $profileFrames[$PerformanceProfile]
if ($MaxFPS -ge 0)
{
    $frameLimit = $MaxFPS
}

if ($frameLimit -eq 0)
{
    Write-Warning 'MCP 宿主不限制帧率 CPU 与 GPU 消耗可能明显增加'
}

if ($frameLimit -gt 0 -and $frameLimit -lt 30)
{
    Write-Warning 'MCP 帧率上限低于三十 串行请求延迟会累积'
}

if ($PerformanceProfile -eq 'GamingBackground')
{
    Write-Warning '后台游戏档降低持续调度频率 不限制编译 导入 烘焙与截图的资源峰值 不自动提速'
    if ($EnableRendering)
    {
        Write-Warning '后台游戏档启用渲染 GPU 消耗与显存占用不保证降低'
    }
}

$hostMutex = [System.Threading.Mutex]::new($false, 'Local\BBBUEOfficialMcpHost')
$ownsMutex = $false
$createdProcess = $null
$ready = $false
try
{
    try
    {
        $ownsMutex = $hostMutex.WaitOne(10000)
    }
    catch [System.Threading.AbandonedMutexException]
    {
        $ownsMutex = $true
    }

    if (-not $ownsMutex)
    {
        throw '其他会话正在启动 MCP 宿主 请等待其启动结束'
    }

    $editors = @(Get-CimInstance Win32_Process -Filter "Name = 'UnrealEditor.exe'")
    if ($editors.Count -gt 1)
    {
        throw '检测到多个 Unreal Editor 进程 必须先协调为单宿主 本脚本不终止其他会话'
    }

    $processId = $null
    if ($editors.Count -eq 1)
    {
        $existingEditor = $editors[0]
        $commandLine = $existingEditor.CommandLine
        $matchesProject = $commandLine -like "*$projectPath*" -and $existingEditor.ExecutablePath -eq $editorPath
        $matchesMode = -not $EnableRendering -and $commandLine -match '(?i)-NullRHI(\s|$)'
        if ($EnableRendering)
        {
            $matchesMode = $commandLine -match '(?i)-RenderOffscreen(\s|$)' -and $commandLine -notmatch '(?i)-NullRHI(\s|$)'
        }

        $matchesPort = $commandLine -match $portArgumentPattern
        if ($Port -eq 8000 -and $commandLine -notmatch '(?i)-ModelContextProtocolPort=')
        {
            $matchesPort = $true
        }

        if (-not $matchesProject -or -not $matchesMode -or -not $matchesPort -or $commandLine -notmatch '(?i)-ModelContextProtocolStartServer(\s|$)')
        {
            throw "已有编辑器 PID $($existingEditor.ProcessId) 与请求宿主不匹配 不启动第二实例 请协调现有会话"
        }

        $processId = $existingEditor.ProcessId
    }

    $listeners = @(Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -gt 0 -and ($null -eq $processId -or $listeners.OwningProcess -notcontains $processId))
    {
        throw "端口 $Port 被其他进程占用 不启动 MCP 宿主"
    }

    if ($null -eq $processId)
    {
        $arguments = @('"' + $projectPath + '"')
        if ($EnableRendering)
        {
            $arguments += '/Engine/Maps/Entry'
        }

        $arguments += @(
            '-ModelContextProtocolStartServer',
            "-ModelContextProtocolPort=$Port",
            "-BBBMcpPerformanceProfile=$PerformanceProfile",
            "-BBBMcpMaxFPS=$frameLimit",
            '-Unattended',
            '-NoSplash',
            '-NoSound',
            '-AutoDeclinePackageRecovery',
            '-stdout',
            '-FullStdOutLogOutput'
        )
        $consoleCommands = "t.MaxFPS $frameLimit,t.IdleWhenNotForeground 0"
        if (-not $EnableRendering)
        {
            $arguments += '-NullRHI'
        }

        if ($EnableRendering)
        {
            $arguments += '-RenderOffscreen'
            $consoleCommands += ',sg.ShadowQuality 0,sg.PostProcessQuality 0,r.Lumen.DiffuseIndirect.Allow 0,r.Lumen.Reflections.Allow 0,r.ScreenPercentage 35'
        }

        $arguments += '-ExecCmds="' + $consoleCommands + '"'
        $createdProcess = Start-Process -FilePath $editorPath -ArgumentList $arguments -WindowStyle Hidden -PassThru
        $createdProcess.PriorityClass = $profilePriorities[$PerformanceProfile]

        $processId = $createdProcess.Id
    }

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastReadinessError = '端口尚未监听'
    while ((Get-Date) -lt $deadline)
    {
        if ($null -eq (Get-Process -Id $processId -ErrorAction SilentlyContinue))
        {
            throw "MCP 宿主 PID $processId 在就绪前退出"
        }

        $listeners = @(Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
        if ($listeners.Count -gt 0 -and $listeners.OwningProcess -notcontains $processId)
        {
            throw "端口 $Port 已被其他进程占用 未连接到请求的 UE MCP 实例"
        }

        if ($listeners.OwningProcess -contains $processId)
        {
            $sessionHeaders = @{ Accept = 'application/json, text/event-stream' }
            $sessionId = $null
            $existingProfileMismatch = $false
            try
            {
                $initializeBody = @{ jsonrpc = '2.0'; id = 1; method = 'initialize'; params = @{ protocolVersion = '2025-11-25'; capabilities = @{}; clientInfo = @{ name = 'bbb-mcp-startup-check'; version = '1.0' } } } | ConvertTo-Json -Depth 8 -Compress
                $initializeResponse = Invoke-WebRequest -Uri $endpoint -Method Post -ContentType 'application/json' -Headers $sessionHeaders -Body $initializeBody -TimeoutSec 5 -ErrorAction Stop
                $sessionId = $initializeResponse.Headers['Mcp-Session-Id'] | Select-Object -First 1
                $initializeText = $initializeResponse.Content
                if ($initializeResponse.Headers['Content-Type'] -match 'text/event-stream')
                {
                    $initializeText = ($initializeText -split "`n" | Where-Object { $_ -like 'data:*' } | Select-Object -Last 1).Substring(5).Trim()
                }

                $initializeResult = $initializeText | ConvertFrom-Json
                if ($initializeResult.error -or -not $initializeResult.result.protocolVersion)
                {
                    throw 'MCP 初始化未返回有效协议版本'
                }

                if ($sessionId)
                {
                    $sessionHeaders['Mcp-Session-Id'] = $sessionId
                }

                $sessionHeaders['MCP-Protocol-Version'] = $initializeResult.result.protocolVersion
                $null = Invoke-WebRequest -Uri $endpoint -Method Post -ContentType 'application/json' -Headers $sessionHeaders -Body '{"jsonrpc":"2.0","method":"notifications/initialized"}' -TimeoutSec 5 -ErrorAction Stop
                $listBody = @{ jsonrpc = '2.0'; id = 2; method = 'tools/call'; params = @{ name = 'list_toolsets'; arguments = @{} } } | ConvertTo-Json -Depth 8 -Compress
                $listResponse = Invoke-WebRequest -Uri $endpoint -Method Post -ContentType 'application/json' -Headers $sessionHeaders -Body $listBody -TimeoutSec 5 -ErrorAction Stop
                $listText = $listResponse.Content
                if ($listResponse.Headers['Content-Type'] -match 'text/event-stream')
                {
                    $listText = ($listText -split "`n" | Where-Object { $_ -like 'data:*' } | ForEach-Object { $_.Substring(5).Trim() } | Where-Object { ($_ | ConvertFrom-Json).id -eq 2 } | Select-Object -First 1)
                }

                $listResult = $listText | ConvertFrom-Json
                if ($listResult.error -or $listResult.result.isError)
                {
                    throw 'MCP 工具发现失败'
                }

                $runtimeNames = @([regex]::Matches($listResult.result.content[0].text, '(?m)^- ([^\r\n: ]+\.BBBMcpRuntimeToolset(?:_0x[0-9A-Fa-f]{8})?)(?=:|\s|$)') | ForEach-Object { $_.Groups[1].Value })
                if ($runtimeNames.Count -ne 1)
                {
                    throw '性能工具集未唯一注册 不猜测工具命名空间'
                }

                $inspectBody = @{ jsonrpc = '2.0'; id = 3; method = 'tools/call'; params = @{ name = 'call_tool'; arguments = @{ toolset_name = $runtimeNames[0]; tool_name = 'inspect_mcp_performance'; arguments = @{} } } } | ConvertTo-Json -Depth 8 -Compress
                $inspectResponse = Invoke-WebRequest -Uri $endpoint -Method Post -ContentType 'application/json' -Headers $sessionHeaders -Body $inspectBody -TimeoutSec 5 -ErrorAction Stop
                $inspectText = $inspectResponse.Content
                if ($inspectResponse.Headers['Content-Type'] -match 'text/event-stream')
                {
                    $inspectText = ($inspectText -split "`n" | Where-Object { $_ -like 'data:*' } | ForEach-Object { $_.Substring(5).Trim() } | Where-Object { ($_ | ConvertFrom-Json).id -eq 3 } | Select-Object -First 1)
                }

                $inspectResult = $inspectText | ConvertFrom-Json
                if ($inspectResult.error -or $inspectResult.result.isError)
                {
                    throw 'MCP 性能工具尚不可调用'
                }

                $toolResult = $inspectResult.result.content[0].text | ConvertFrom-Json
                $performance = $toolResult.returnValue | ConvertFrom-Json
                if ($performance.process_id -ne $processId -or $performance.profile -ne $PerformanceProfile -or $performance.max_fps -ne $frameLimit -or $performance.priority -ne $profilePriorities[$PerformanceProfile] -or $performance.background_cpu_throttle -or $performance.idle_when_not_foreground -or -not $performance.matches_configured_settings)
                {
                    $existingProfileMismatch = $null -eq $createdProcess
                    throw '宿主性能档位与请求不一致 不修改其他会话的运行时配置'
                }

                $ready = $true
                [pscustomobject]@{
                    EditorProcessId = $processId
                    Endpoint = $endpoint
                    Project = $projectPath
                    Status = 'Ready'
                    Performance = $performance
                } | ConvertTo-Json -Depth 5 -Compress
                return
            }
            catch
            {
                if ($existingProfileMismatch)
                {
                    throw
                }

                $lastReadinessError = $_.Exception.Message
            }
            finally
            {
                if ($sessionId)
                {
                    try
                    {
                        $null = Invoke-WebRequest -Uri $endpoint -Method Delete -Headers $sessionHeaders -TimeoutSec 3 -ErrorAction Stop
                    }
                    catch
                    {
                        Write-Warning "就绪检查会话释放失败 $($_.Exception.Message)"
                    }
                }
            }
        }

        Start-Sleep -Milliseconds 100
    }

    throw "官方 Unreal MCP 未在 $TimeoutSeconds 秒内就绪 最后错误 $lastReadinessError"
}
finally
{
    try
    {
        if (-not $ready -and $null -ne $createdProcess -and -not $createdProcess.HasExited)
        {
            Stop-Process -Id $createdProcess.Id -ErrorAction Stop
            if (-not $createdProcess.WaitForExit(10000))
            {
                throw "本脚本创建的失败宿主 PID $($createdProcess.Id) 尚未退出"
            }
        }
    }
    finally
    {
        if ($ownsMutex)
        {
            $hostMutex.ReleaseMutex()
        }

        $hostMutex.Dispose()
    }
}
