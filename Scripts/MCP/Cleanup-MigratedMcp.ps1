[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [switch]$Execute
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = 'E:\BBB_Evac'
$repositoryRoot = 'E:\UE5.8\BBBUE-MCP-Tools'
$migrationCommit = 'c1858408898e02b308f9c3799c3dc51fffe30fcd'
$deletedCount = 0
$targets = [System.Collections.Generic.List[object]]::new()
$targetPaths = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)

<#
/**
 * 仅允许指定根目录内的真实路径 不经过符号链接或目录联接
 * @param Path	目标绝对路径
 * @param Root	允许的根目录
 * @return 规范化后的绝对路径
 */
#>
function Assert-CleanupPath
{
    param([string]$Path, [string]$Root)

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    if (-not $fullPath.StartsWith($Root + '\', [System.StringComparison]::OrdinalIgnoreCase))
    {
        throw "[MCP清理]路径越界 $fullPath"
    }

    $ancestor = $fullPath
    while ($ancestor)
    {
        if (Test-Path -LiteralPath $ancestor)
        {
            $item = Get-Item -LiteralPath $ancestor -Force
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0)
            {
                throw "[MCP清理]路径含链接或联接 $ancestor"
            }
        }

        $ancestor = [System.IO.Path]::GetDirectoryName($ancestor)
    }

    return $fullPath
}

<#
/**
 * 只读调用 Git并检查失败 不提交或推送任何修改
 * @param Arguments	Git参数
 * @return Git标准输出
 */
#>
function Invoke-CleanupGit
{
    param([string[]]$Arguments)

    $output = & git -C $repositoryRoot @Arguments
    if ($LASTEXITCODE -ne 0)
    {
        throw "[MCP清理]Git检查失败 $($Arguments -join ' ')"
    }

    return $output
}

<#
/**
 * 只登记明确文件 记录预检哈希供删除前再次核对
 * @param Path	目标文件
 * @param Root	允许的根目录
 * @param Hash	旧源码原始哈希 缓存传空值
 * @return 无返回值
 */
#>
function Add-CleanupTarget
{
    param([string]$Path, [string]$Root, [string]$Hash)

    $fullPath = Assert-CleanupPath $Path $Root
    if (-not (Test-Path -LiteralPath $fullPath))
    {
        Write-Host "[MCP清理]已不存在 跳过 $fullPath"
        return
    }

    $item = Get-Item -LiteralPath $fullPath -Force
    if ($item.PSIsContainer)
    {
        throw "[MCP清理]清单目标不是文件 $fullPath"
    }

    $actualHash = (Get-FileHash -LiteralPath $fullPath -Algorithm SHA256).Hash
    if ($Hash -and $actualHash -ne $Hash)
    {
        throw "[MCP清理]文件已改变 拒绝删除 $fullPath"
    }

    if ($targetPaths.Add($fullPath))
    {
        $targets.Add([pscustomobject]@{ Path = $fullPath; Root = $Root; Hash = $actualHash })
    }
}

try
{
    $gitRoot = (Invoke-CleanupGit @('rev-parse', '--show-toplevel')).Trim()
    if ([System.IO.Path]::GetFullPath($gitRoot) -ne $repositoryRoot)
    {
        throw '[MCP清理]新仓库Git根目录不匹配'
    }

    $manifestText = Invoke-CleanupGit @('show', "${migrationCommit}:Docs/MigrationManifest.json")
    $manifest = ($manifestText -join "`n") | ConvertFrom-Json
    if ($manifest.source_root -ne $projectRoot -or $manifest.repository_root -ne $repositoryRoot -or $manifest.files.Count -ne 36)
    {
        throw '[MCP清理]迁移清单与批准范围不匹配'
    }

    $loaderPath = Assert-CleanupPath (Join-Path $projectRoot 'Content\Python\init_unreal.py') $projectRoot
    $loader = Get-Content -LiteralPath $loaderPath -Raw -Encoding UTF8
    if (-not $loader.Contains($repositoryRoot + '\Scripts') -or -not $loader.Contains('BBBMcpBootstrap.register_mcp_toolsets()'))
    {
        throw '[MCP清理]项目尚未接入新仓库 拒绝删除旧源码'
    }

    foreach ($entry in $manifest.files)
    {
        $relativePath = [string]$entry.path
        if ($relativePath -notmatch '^(Scripts|Docs)/' -or $relativePath -match '(^|/)\.\.(/|$)' -or $entry.hash -notmatch '^[0-9A-Fa-f]{64}$')
        {
            throw "[MCP清理]非法清单条目 $relativePath"
        }

        $newPath = Assert-CleanupPath (Join-Path $repositoryRoot $relativePath) $repositoryRoot
        if (-not (Test-Path -LiteralPath $newPath -PathType Leaf))
        {
            throw "[MCP清理]新仓库缺少文件 $newPath"
        }

        $expectedBlob = (Invoke-CleanupGit @('rev-parse', "HEAD:$relativePath")).Trim()
        $actualBlob = (Invoke-CleanupGit @('hash-object', "--path=$relativePath", '--', $newPath)).Trim()
        if ($actualBlob -ne $expectedBlob)
        {
            throw "[MCP清理]新仓库文件有未提交修改 拒绝删除旧文件 $newPath"
        }

        $oldPath = Assert-CleanupPath (Join-Path $projectRoot $relativePath) $projectRoot
        Add-CleanupTarget $oldPath $projectRoot $entry.hash
        if ([System.IO.Path]::GetExtension($relativePath) -eq '.py')
        {
            $cacheDirectory = Assert-CleanupPath (Join-Path ([System.IO.Path]::GetDirectoryName($oldPath)) '__pycache__') $projectRoot
            if (Test-Path -LiteralPath $cacheDirectory -PathType Container)
            {
                $moduleName = [regex]::Escape([System.IO.Path]::GetFileNameWithoutExtension($oldPath))
                foreach ($cache in Get-ChildItem -LiteralPath $cacheDirectory -File -Force)
                {
                    if ($cache.Name -match ('^' + $moduleName + '(?:\.[^.]+)*\.pyc$'))
                    {
                        Add-CleanupTarget $cache.FullName $projectRoot ''
                    }
                }
            }
        }
    }

    $bootstrapCacheDirectory = Assert-CleanupPath (Join-Path $repositoryRoot 'Scripts\__pycache__') $repositoryRoot
    if (Test-Path -LiteralPath $bootstrapCacheDirectory -PathType Container)
    {
        foreach ($cache in Get-ChildItem -LiteralPath $bootstrapCacheDirectory -File -Force)
        {
            if ($cache.Name -match '^BBBMcpBootstrap(?:\.[^.]+)*\.pyc$')
            {
                Add-CleanupTarget $cache.FullName $repositoryRoot ''
            }
        }
    }

    Write-Host "[MCP清理]全部预检通过 待删除 $($targets.Count) 个文件 包含旧文件与对应缓存"
    $targets | Select-Object Path | Format-Table -AutoSize -Wrap | Out-Host
    Write-Warning '永久删除 不留备份 不提交Git 不推送 不更改Perforce记录 不关闭编辑器 若文件被占用请先协调相关会话'
    if (-not $Execute)
    {
        Write-Host '[MCP清理]当前仅预览 加上 -Execute 才会执行删除'
        return
    }

    foreach ($target in $targets)
    {
        $null = Assert-CleanupPath $target.Path $target.Root
        $actualHash = (Get-FileHash -LiteralPath $target.Path -Algorithm SHA256).Hash
        if ($actualHash -ne $target.Hash)
        {
            throw "[MCP清理]预检后文件发生变化 已停止 $($target.Path)"
        }

        if ($PSCmdlet.ShouldProcess($target.Path, '永久删除已迁移文件或对应缓存 不留备份'))
        {
            Remove-Item -LiteralPath $target.Path -Force -ErrorAction Stop
            if (Test-Path -LiteralPath $target.Path)
            {
                throw "[MCP清理]删除后文件仍存在 $($target.Path)"
            }

            $deletedCount += 1
            Write-Host "[MCP清理]已删除 $($target.Path)"
        }
    }

    Write-Host "[MCP清理]结束 已删除 $deletedCount 个文件 不清理清单外文件 不递归删除目录"
    Write-Host '[MCP清理]请将结果交给AI复核迁移状态和本地Git改动 Perforce已有edit或add记录仍保持原样'
}
catch
{
    Write-Error -Message "[MCP清理]失败 已删除 $deletedCount 个文件 不是事务 不自动重试或回滚 原因 $($_.Exception.Message)" -ErrorAction Continue
    throw
}
