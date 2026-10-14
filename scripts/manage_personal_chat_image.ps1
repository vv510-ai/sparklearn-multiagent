param(
    [Parameter(Mandatory = $true)][string]$Config,
    [ValidateSet('Start', 'Stop', 'Status')][string]$Action = 'Start'
)
$ErrorActionPreference = 'Stop'
$taskConfigPath = (Resolve-Path -LiteralPath $Config).Path
$taskConfig = Get-Content -LiteralPath $taskConfigPath -Raw | ConvertFrom-Json
$taskPython = Join-Path (Split-Path -Parent $taskConfig.python_path) 'pythonw.exe'
$taskRunner = Join-Path $PSScriptRoot 'run_personal_chat_image_background.py'
$taskWorker = Join-Path $PSScriptRoot 'personal_chat_image_worker.py'
foreach ($taskFile in @($taskPython, $taskRunner, $taskWorker)) {
    if (-not (Test-Path -LiteralPath $taskFile -PathType Leaf)) { throw '本机接入文件缺失，请重新核对安装路径。' }
}
$taskHash = [System.Security.Cryptography.SHA256]::Create()
try {
    $taskDigest = [BitConverter]::ToString($taskHash.ComputeHash([Text.Encoding]::UTF8.GetBytes($taskConfigPath.ToLowerInvariant()))).Replace('-', '').ToLowerInvariant()
} finally { $taskHash.Dispose() }
$taskName = 'LearnLoop-PersonalChatImage-' + $taskDigest.Substring(0, 16)
$taskDescription = 'LearnLoop personal Chat image worker. Starts only on demand; no login or timed trigger.'
$taskArguments = '"' + $taskRunner + '" --config "' + $taskConfigPath + '"'
$taskExisting = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($taskExisting -and ($taskExisting.Description -ne $taskDescription -or $taskExisting.Actions.Count -ne 1 -or $taskExisting.Actions[0].Execute -ne $taskPython -or $taskExisting.Actions[0].Arguments -ne $taskArguments)) {
    throw '同名任务与本接入程序不匹配，未修改现有任务。'
}
if ($Action -eq 'Status') {
    if ($taskExisting) { $taskExisting | Select-Object TaskName, State }
    else { Write-Output '尚未配置后台接入任务。' }
    return
}
if ($Action -eq 'Stop') {
    New-Item -ItemType File -Path (Join-Path $taskConfig.state_dir 'stop.requested') -Force | Out-Null
    Write-Output '已请求接入程序结束等待并断开浏览器；没有关闭 Chrome。'
    return
}
if (-not $taskExisting) {
    $taskIdentity = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $taskPrincipal = New-ScheduledTaskPrincipal -UserId $taskIdentity -LogonType Interactive -RunLevel Limited
    $taskActionDefinition = New-ScheduledTaskAction -Execute $taskPython -Argument $taskArguments -WorkingDirectory $PSScriptRoot
    $taskSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
    # No triggers: the worker starts only when this script is explicitly run.
    Register-ScheduledTask -TaskName $taskName -Description $taskDescription -Action $taskActionDefinition -Principal $taskPrincipal -Settings $taskSettings | Out-Null
}
if ((Get-ScheduledTask -TaskName $taskName).State -ne 'Running') {
    Start-ScheduledTask -TaskName $taskName
}
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State
