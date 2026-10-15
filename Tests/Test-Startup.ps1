Set-StrictMode -Version 1.0
$ErrorActionPreference = 'Stop'
foreach ($script in @('Start-BBBMcpService.ps1', 'Start-UE58OfficialMcpEditor.ps1'))
{
    $tokens = $null
    $parseErrors = $null
    $path = Join-Path $PSScriptRoot ('..\Scripts\MCP\' + $script)
    [System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$parseErrors) | Out-Null
    if ($parseErrors.Count -gt 0)
    {
        throw ($parseErrors | Out-String)
    }
}
Push-Location (Join-Path $PSScriptRoot '..')
try
{
    & python -B -m unittest discover -s Tests -p test_editor_startup.py
    if ($LASTEXITCODE -ne 0)
    {
        throw '编辑器自动登记验收失败'
    }
}
finally
{
    Pop-Location
}
