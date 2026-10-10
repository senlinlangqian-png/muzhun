param([string]$Manifest)
$ErrorActionPreference = 'Stop'
$payload = [System.IO.File]::ReadAllText($Manifest, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
$voice = New-Object -ComObject SAPI.SpVoice
$chinese = $voice.GetVoices() | Where-Object { $_.GetDescription() -like '*Chinese*' } | Select-Object -First 1
if ($payload.language -eq 'en') {
    $english = $voice.GetVoices() | Where-Object { $_.GetDescription() -like '*English*' } | Select-Object -First 1
    if ($english) { $voice.Voice = $english }
    $chinese = $null
}
if ($chinese) { $voice.Voice = $chinese }
$voice.Rate = 0
foreach ($scene in $payload.scenes) {
    $stream = New-Object -ComObject SAPI.SpFileStream
    $stream.Format.Type = 22
    $stream.Open($scene.output, 3, $false)
    $voice.AudioOutputStream = $stream
    if ($chinese) { $text = $scene.zh } else { $text = $scene.en }
    $null = $voice.Speak($text)
    $stream.Close()
}
Write-Output $voice.Voice.GetDescription()
