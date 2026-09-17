# Run in Windows PowerShell after export_cet6_course.py. No cloud keys required.
param([string]$Voice = 'Microsoft Zira Desktop')
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$inputFile = Join-Path $repoRoot '.tmp/cet6-audio-input.json'
$outDir = Join-Path $repoRoot 'frontend/public/course-audio/cet6-v1'
[IO.Directory]::CreateDirectory($outDir) | Out-Null
$clips = Get-Content -LiteralPath $inputFile -Raw -Encoding UTF8 | ConvertFrom-Json
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$manifest = @()
try {
    $synth.SelectVoice($Voice)
    $synth.Rate = 0
    $format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
    foreach ($clip in $clips) {
        if ($clip.id -notmatch '^cet6_listening-(baseline|fresh)-[1-9]$') { throw 'Invalid clip id' }
        $target = Join-Path $outDir ($clip.id + '.wav')
        $synth.SetOutputToWaveFile($target, $format)
        $synth.Speak($clip.text)
        $synth.SetOutputToNull()
        $hasher = [Security.Cryptography.SHA256]::Create()
        try { $scriptHash = [BitConverter]::ToString($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($clip.text))).Replace('-', '').ToLowerInvariant() } finally { $hasher.Dispose() }
        $manifest += @{ id = $clip.id; voice = $Voice; rate = 0; sample_rate = 16000; transcript_sha256 = $scriptHash; audio_sha256 = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() }
    }
} finally { $synth.Dispose() }
$json = ConvertTo-Json -InputObject $manifest -Depth 3
[IO.File]::WriteAllText((Join-Path $repoRoot 'backend/app/data/cet6_audio_manifest.json'), $json, (New-Object Text.UTF8Encoding($false)))
Write-Output ('Generated {0} English audio files' -f $manifest.Count)
