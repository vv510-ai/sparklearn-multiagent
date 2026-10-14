param(
    [Parameter(Mandatory = $true)][string]$Config,
    [switch]$Once,
    [switch]$CheckBrowser,
    [switch]$Stop
)
$ErrorActionPreference = 'Stop'
$taskConfigPath = (Resolve-Path -LiteralPath $Config).Path
$taskConfig = Get-Content -Raw -LiteralPath $taskConfigPath | ConvertFrom-Json
if (-not (Test-Path -LiteralPath $taskConfig.python_path -PathType Leaf)) {
    throw '配对文件中的 Python 不可用，请重新核对本机环境。'
}
$taskArguments = @((Join-Path $PSScriptRoot 'personal_chat_image_worker.py'), '--config', $taskConfigPath)
if ($Once) { $taskArguments += '--once' }
if ($CheckBrowser) { $taskArguments += '--check-browser' }
if ($Stop) { $taskArguments += '--stop' }
& $taskConfig.python_path @taskArguments
exit $LASTEXITCODE
