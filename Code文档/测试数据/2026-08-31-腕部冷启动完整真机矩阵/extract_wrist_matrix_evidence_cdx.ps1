param(
    [Parameter(Mandatory = $true)]
    [string]$SessionFile,

    [Parameter(Mandatory = $true)]
    [string]$OutputDir
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Get-Sha256WithReadWriteSharing {
    param([Parameter(Mandatory = $true)][string]$LiteralPath)
    $stream = [System.IO.FileStream]::new(
        $LiteralPath,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::ReadWrite -bor [System.IO.FileShare]::Delete
    )
    try {
        $sha = [System.Security.Cryptography.SHA256]::Create()
        try {
            return [Convert]::ToHexString($sha.ComputeHash($stream))
        } finally {
            $sha.Dispose()
        }
    } finally {
        $stream.Dispose()
    }
}

$sessionPath = (Resolve-Path -LiteralPath $SessionFile).Path
if (-not (Test-Path -LiteralPath $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}
$outputPath = (Resolve-Path -LiteralPath $OutputDir).Path

$captureMap = @(
    [pscustomobject]@{ CaptureIndex = 1; MatrixRound = 1; Valid = $true;  Port = 'COM6'; Placement = 'RIGHT_THUMB_NORMAL';        ExternalHr = '约70';    ExternalSpo2 = '约98';    ExternalRaw = '70bpm上下，98%上下' },
    [pscustomobject]@{ CaptureIndex = 2; MatrixRound = 2; Valid = $true;  Port = 'COM7'; Placement = 'RIGHT_THUMB_NORMAL';        ExternalHr = '约71';    ExternalSpo2 = '约98';    ExternalRaw = '71bpm左右，98%左右' },
    [pscustomobject]@{ CaptureIndex = 3; MatrixRound = 0; Valid = $false; Port = 'COM6'; Placement = 'LEFT_THUMB_NOT_RESET_ABORTED'; ExternalHr = '';        ExternalSpo2 = '';        ExternalRaw = '未取参照；seq=123起步，立即作废' },
    [pscustomobject]@{ CaptureIndex = 4; MatrixRound = 3; Valid = $true;  Port = 'COM6'; Placement = 'LEFT_THUMB_NORMAL';         ExternalHr = '约71-75'; ExternalSpo2 = '约97-98'; ExternalRaw = '97-98%，71-75bpm' },
    [pscustomobject]@{ CaptureIndex = 5; MatrixRound = 4; Valid = $true;  Port = 'COM7'; Placement = 'LEFT_THUMB_NORMAL';         ExternalHr = '约71';    ExternalSpo2 = '约98';    ExternalRaw = '98%，71bpm；用户确认此前及之后均为中位数口径' },
    [pscustomobject]@{ CaptureIndex = 6; MatrixRound = 5; Valid = $true;  Port = 'COM6'; Placement = 'RIGHT_THUMB_LIGHT_CONTACT'; ExternalHr = '约70';    ExternalSpo2 = '约98-99'; ExternalRaw = '98-99%，70bpm' },
    [pscustomobject]@{ CaptureIndex = 7; MatrixRound = 6; Valid = $true;  Port = 'COM7'; Placement = 'RIGHT_THUMB_LIGHT_CONTACT'; ExternalHr = '约68';    ExternalSpo2 = '约98';    ExternalRaw = '68bpm，98' },
    [pscustomobject]@{ CaptureIndex = 8; MatrixRound = 7; Valid = $true;  Port = 'COM6'; Placement = 'RIGHT_THUMB_FIRM_CONTACT';  ExternalHr = '约73';    ExternalSpo2 = '约98-99'; ExternalRaw = '73bpm，98-99' },
    [pscustomobject]@{ CaptureIndex = 9; MatrixRound = 8; Valid = $true;  Port = 'COM7'; Placement = 'RIGHT_THUMB_FIRM_CONTACT';  ExternalHr = '约74';    ExternalSpo2 = '约98';    ExternalRaw = '98，74bpm' }
)

$captures = [System.Collections.Generic.List[object]]::new()
$lineNumber = 0
Get-Content -LiteralPath $sessionPath -Encoding utf8 | ForEach-Object {
    $lineNumber++
    try {
        $event = $_ | ConvertFrom-Json -Depth 100
    } catch {
        return
    }

    if ($event.type -ne 'event_msg' -or
        -not $event.payload.PSObject.Properties['item']) {
        return
    }

    if ($event.payload.item.type -ne 'CommandExecution' -or
        [string]$event.payload.item.cwd -ne 'file:///D:/esp-box') {
        return
    }

    $stdout = [string]$event.payload.item.stdout
    if ($stdout -notmatch '(?m)^CAPTURE_PORT=(COM[67])\r?$') {
        return
    }

    $captures.Add([pscustomobject]@{
        SessionLine = $lineNumber
        CompletedUtc = [DateTimeOffset]$event.timestamp
        DurationSeconds = [double]$event.payload.item.duration.secs + ([double]$event.payload.item.duration.nanos / 1000000000.0)
        ExecutionId = [string]$event.payload.item.id
        Status = [string]$event.payload.item.status
        ExitCode = [int]$event.payload.item.exit_code
        Stdout = $stdout
    })
}

if ($captures.Count -ne 9) {
    throw "Expected 9 capture records (8 valid + 1 aborted), got $($captures.Count)"
}

$rawRecords = [System.Collections.Generic.List[object]]::new()
$frameRows = [System.Collections.Generic.List[object]]::new()
$diagRows = [System.Collections.Generic.List[object]]::new()
$summaryRows = [System.Collections.Generic.List[object]]::new()
$externalRows = [System.Collections.Generic.List[object]]::new()
$rawLog = [System.Text.StringBuilder]::new()

for ($index = 0; $index -lt $captures.Count; $index++) {
    $capture = $captures[$index]
    $map = $captureMap[$index]
    $stdout = $capture.Stdout
    $completedUtc = $capture.CompletedUtc
    $startedUtc = $completedUtc.AddSeconds(-$capture.DurationSeconds)
    $completedLocal = $completedUtc.ToOffset([TimeSpan]::FromHours(8))
    $startedLocal = $startedUtc.ToOffset([TimeSpan]::FromHours(8))

    if ($stdout -notmatch '(?m)^CAPTURE_PORT=(COM[67])\r?$') {
        throw "Capture $($map.CaptureIndex) has no port marker"
    }
    $actualPort = $matches[1]
    if ($actualPort -ne $map.Port) {
        throw "Capture $($map.CaptureIndex) port mismatch: $actualPort"
    }

    $hasSummary = $stdout -match '(?m)^CAPTURE_EXIT=0\r?$'
    if ($map.Valid -and (-not $hasSummary -or $capture.ExitCode -ne 0)) {
        throw "Valid capture $($map.CaptureIndex) is incomplete"
    }
    if (-not $map.Valid -and $hasSummary) {
        throw "Aborted capture unexpectedly has a completed summary"
    }

    $resetMethod = if ($stdout -match '(?m)^RESET_EXIT=0\r?$') {
        'ESPTOOL_HARD_RESET'
    } elseif ($stdout -match 'USB_UART_CHIP_RESET') {
        'USB_UART_CHIP_RESET_ON_OPEN'
    } else {
        'NO_RESET_CONFIRMED'
    }

    $rawRecords.Add([pscustomobject]@{
        capture_index = $map.CaptureIndex
        matrix_round = $map.MatrixRound
        valid_for_matrix = $map.Valid
        port = $map.Port
        placement = $map.Placement
        reset_method = $resetMethod
        external_hr_median = $map.ExternalHr
        external_spo2_median = $map.ExternalSpo2
        external_raw_user_text = $map.ExternalRaw
        source_jsonl_line = $capture.SessionLine
        capture_started_utc = $startedUtc.ToString('yyyy-MM-ddTHH:mm:ss.fffK')
        capture_completed_utc = $completedUtc.ToString('yyyy-MM-ddTHH:mm:ss.fffK')
        capture_started_local = $startedLocal.ToString('yyyy-MM-dd HH:mm:ss.fff zzz')
        capture_completed_local = $completedLocal.ToString('yyyy-MM-dd HH:mm:ss.fff zzz')
        command_duration_seconds = [math]::Round($capture.DurationSeconds, 3)
        command_execution_id = $capture.ExecutionId
        command_status = $capture.Status
        command_exit_code = $capture.ExitCode
        stdout = $stdout
    })

    [void]$rawLog.AppendLine("===== CAPTURE $($map.CaptureIndex) / MATRIX ROUND $($map.MatrixRound) / $($map.Port) / $($map.Placement) / VALID=$($map.Valid) =====")
    [void]$rawLog.AppendLine("SOURCE_JSONL_LINE=$($capture.SessionLine)")
    [void]$rawLog.AppendLine("COMMAND_EXECUTION_ID=$($capture.ExecutionId)")
    [void]$rawLog.AppendLine("CAPTURE_STARTED_LOCAL=$($startedLocal.ToString('yyyy-MM-dd HH:mm:ss.fff zzz'))")
    [void]$rawLog.AppendLine("CAPTURE_COMPLETED_LOCAL=$($completedLocal.ToString('yyyy-MM-dd HH:mm:ss.fff zzz'))")
    [void]$rawLog.AppendLine("COMMAND_DURATION_SECONDS=$([math]::Round($capture.DurationSeconds, 3))")
    [void]$rawLog.AppendLine("EXTERNAL_REFERENCE=$($map.ExternalRaw)")
    [void]$rawLog.AppendLine($stdout.TrimEnd())
    [void]$rawLog.AppendLine()

    $summary = [ordered]@{
        capture_index = $map.CaptureIndex
        matrix_round = $map.MatrixRound
        valid_for_matrix = $map.Valid
        port = $map.Port
        placement = $map.Placement
        reset_method = $resetMethod
        external_hr_median = $map.ExternalHr
        external_spo2_median = $map.ExternalSpo2
        capture_started_local = $startedLocal.ToString('yyyy-MM-dd HH:mm:ss.fff zzz')
        capture_completed_local = $completedLocal.ToString('yyyy-MM-dd HH:mm:ss.fff zzz')
        command_duration_seconds = [math]::Round($capture.DurationSeconds, 3)
        first_seq = ''
        total_frames = ''
        stable_frames = ''
        clean_hr_count = ''
        clean_hr_values = ''
        clean_hr_median = ''
        valid_spo2_count = ''
        valid_spo2_values = ''
        valid_spo2_median = ''
        false_lock_98_114_count = ''
        bad_valid_spo2_lt90_count = ''
        command_exit_code = $capture.ExitCode
    }

    foreach ($line in ($stdout -split '\r?\n')) {
        if ($line -match '^FRAME T=(?<t>[0-9.]+)s HR=(?<hr>\d+) SpO2=(?<spo2>\d+) conf=(?<conf>\d+) flags=0x(?<flags>[0-9A-Fa-f]+) seq=(?<seq>\d+)$') {
            $t = [double]$matches.t
            $hr = [int]$matches.hr
            $spo2 = [int]$matches.spo2
            $flagsValue = [Convert]::ToInt32($matches.flags, 16)
            $stable = $map.Valid -and $t -ge 45.0
            $frameRows.Add([pscustomobject]@{
                capture_index = $map.CaptureIndex
                matrix_round = $map.MatrixRound
                valid_for_matrix = $map.Valid
                port = $map.Port
                placement = $map.Placement
                t_seconds = $t
                seq = [int]$matches.seq
                heart_rate = $hr
                spo2 = $spo2
                confidence = [int]$matches.conf
                flags_hex = ('0x{0:X2}' -f $flagsValue)
                flag_hr_valid = [int](($flagsValue -band 1) -ne 0)
                flag_spo2_valid = [int](($flagsValue -band 2) -ne 0)
                flag_artifact = [int](($flagsValue -band 4) -ne 0)
                stable_segment = [int]$stable
                clean_hr = [int]($stable -and ($flagsValue -band 1) -ne 0 -and ($flagsValue -band 4) -eq 0 -and $hr -gt 0)
                clean_spo2 = [int]($stable -and ($flagsValue -band 2) -ne 0 -and ($flagsValue -band 4) -eq 0 -and $spo2 -gt 0)
                target_false_lock_98_114 = [int]($stable -and $hr -ge 98 -and $hr -le 114 -and ($flagsValue -band 1) -ne 0)
                bad_valid_spo2_lt90 = [int]($stable -and $spo2 -gt 0 -and $spo2 -lt 90 -and ($flagsValue -band 2) -ne 0)
                raw_line = $line
            })
            continue
        }

        if ($line -match '^DIAG T=(?<t>[0-9.]+)s .*signal_diag: rate=(?<rate>[0-9.]+) dc_ir=(?<dcir>\d+) dc_red=(?<dcred>\d+) ac_ir=(?<acir>\d+) ac_red=(?<acred>\d+) band=(?<band>[0-9.]+) quality=(?<quality>[0-9.]+) flags=0x(?<flags>[0-9A-Fa-f]+)$') {
            $diagRows.Add([pscustomobject]@{
                capture_index = $map.CaptureIndex
                matrix_round = $map.MatrixRound
                valid_for_matrix = $map.Valid
                port = $map.Port
                placement = $map.Placement
                t_seconds = [double]$matches.t
                rate_hz = [double]$matches.rate
                dc_ir = [long]$matches.dcir
                dc_red = [long]$matches.dcred
                ac_ir = [long]$matches.acir
                ac_red = [long]$matches.acred
                band_ratio = [double]$matches.band
                quality = [double]$matches.quality
                flags_hex = ('0x{0:X2}' -f [Convert]::ToInt32($matches.flags, 16))
                raw_line = $line
            })
            continue
        }

        if ($line -match '^SUMMARY (?<key>[A-Z0-9_]+)=(?<value>.*)$') {
            switch ($matches.key) {
                'FIRST_SEQ' { $summary.first_seq = $matches.value }
                'TOTAL_FRAMES' { $summary.total_frames = $matches.value }
                'STABLE_FRAMES' { $summary.stable_frames = $matches.value }
                'CLEAN_HR_COUNT' { $summary.clean_hr_count = $matches.value }
                'CLEAN_HR_VALUES' { $summary.clean_hr_values = $matches.value }
                'CLEAN_HR_MEDIAN' { $summary.clean_hr_median = $matches.value }
                'VALID_SPO2_COUNT' { $summary.valid_spo2_count = $matches.value }
                'VALID_SPO2_VALUES' { $summary.valid_spo2_values = $matches.value }
                'VALID_SPO2_MEDIAN' { $summary.valid_spo2_median = $matches.value }
                'FALSE_LOCK_98_114_COUNT' { $summary.false_lock_98_114_count = $matches.value }
                'BAD_VALID_SPO2_LT90_COUNT' { $summary.bad_valid_spo2_lt90_count = $matches.value }
            }
        }
    }

    $summaryRows.Add([pscustomobject]$summary)
    $externalRows.Add([pscustomobject]@{
        capture_index = $map.CaptureIndex
        matrix_round = $map.MatrixRound
        valid_for_matrix = $map.Valid
        port = $map.Port
        placement = $map.Placement
        external_hr_median = $map.ExternalHr
        external_spo2_median = $map.ExternalSpo2
        exact_user_text = $map.ExternalRaw
        note = if ($map.Valid) { 'Vange confirmed all reported references use a stable median convention.' } else { 'Invalid capture; no reference used.' }
    })
}

$rawJsonPath = Join-Path $outputPath 'raw_serial_captures_cdx.json'
$rawLogPath = Join-Path $outputPath 'raw_serial_captures_cdx.log'
$framesPath = Join-Path $outputPath 'frames_cdx.csv'
$diagPath = Join-Path $outputPath 'signal_diag_cdx.csv'
$summaryPath = Join-Path $outputPath 'capture_summary_cdx.csv'
$externalPath = Join-Path $outputPath 'external_reference_cdx.csv'
$readmePath = Join-Path $outputPath 'README_cdx.md'
$manifestPath = Join-Path $outputPath 'evidence_manifest_cdx.json'

$rawRecords | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $rawJsonPath -Encoding utf8NoBOM
$rawLog.ToString() | Set-Content -LiteralPath $rawLogPath -Encoding utf8NoBOM
$frameRows | Export-Csv -LiteralPath $framesPath -NoTypeInformation -Encoding utf8NoBOM
$diagRows | Export-Csv -LiteralPath $diagPath -NoTypeInformation -Encoding utf8NoBOM
$summaryRows | Export-Csv -LiteralPath $summaryPath -NoTypeInformation -Encoding utf8NoBOM
$externalRows | Export-Csv -LiteralPath $externalPath -NoTypeInformation -Encoding utf8NoBOM

$validFrames = @($frameRows | Where-Object { $_.valid_for_matrix }).Count
$abortedFrames = @($frameRows | Where-Object { -not $_.valid_for_matrix }).Count
$stableFrames = @($frameRows | Where-Object { $_.stable_segment -eq 1 }).Count
$cleanHrFrames = @($frameRows | Where-Object { $_.clean_hr -eq 1 }).Count
$cleanSpo2Frames = @($frameRows | Where-Object { $_.clean_spo2 -eq 1 }).Count
$targetLocks = @($frameRows | Where-Object { $_.target_false_lock_98_114 -eq 1 }).Count
$badSpo2 = @($frameRows | Where-Object { $_.bad_valid_spo2_lt90 -eq 1 }).Count
$sessionHash = Get-Sha256WithReadWriteSharing -LiteralPath $sessionPath
$matrixStartedLocal = ($captures | Select-Object -First 1).CompletedUtc.AddSeconds(-($captures | Select-Object -First 1).DurationSeconds).ToOffset([TimeSpan]::FromHours(8))
$matrixCompletedLocal = ($captures | Select-Object -Last 1).CompletedUtc.ToOffset([TimeSpan]::FromHours(8))
$matrixWallClockSeconds = ($matrixCompletedLocal - $matrixStartedLocal).TotalSeconds
$captureExecutionSeconds = ($captures | Measure-Object -Property DurationSeconds -Sum).Sum

$readme = @"
# 腕部冷启动完整真机矩阵原始数据归档

- 生成日期：2026-08-31
- 产出方：Codex
- 源会话 JSONL：`$sessionPath`
- 源会话 SHA-256：`$sessionHash`
- 提取规则：仅选择 cwd=`D:/esp-box`、stdout 含行首 `CAPTURE_PORT=COM6/COM7` 的 CommandExecution 记录。
- 捕获清单：8 轮有效采样 + 1 段未复位作废采样；作废数据保留但 `valid_for_matrix=false`。
- 外部参照：Vange 明确确认此前及之后回传值均按稳定读数中位口径。
- 矩阵首轮开始（北京时间）：$($matrixStartedLocal.ToString('yyyy-MM-dd HH:mm:ss.fff zzz'))
- 矩阵末轮结束（北京时间）：$($matrixCompletedLocal.ToString('yyyy-MM-dd HH:mm:ss.fff zzz'))
- 矩阵墙钟跨度：$([math]::Round($matrixWallClockSeconds, 3)) 秒（包含换手、放置和确认间隔）
- 采集命令累计执行：$([math]::Round($captureExecutionSeconds, 3)) 秒

## 文件

- `raw_serial_captures_cdx.json`：9 次命令的完整原始 stdout、执行 ID、JSONL 行号、复位方式和外部参照。
- `raw_serial_captures_cdx.log`：便于人工阅读的完整原始串口输出，不删减 DIAG、FRAME、SUMMARY 或复位证据。
- `frames_cdx.csv`：逐帧 HR、SpO2、confidence、flags、seq 与派生有效性字段。
- `signal_diag_cdx.csv`：逐窗口 rate、DC/AC、band、quality、flags。
- `capture_summary_cdx.csv`：每轮脚本原始 SUMMARY 与外部参照。
- `external_reference_cdx.csv`：Vange 每轮外部血氧仪原话和规范化中位数。
- `extract_wrist_matrix_evidence_cdx.ps1`：可复现提取脚本。
- `evidence_manifest_cdx.json`：归档文件大小与 SHA-256。

## 数量校验

- 原始捕获：9
- 有效捕获：8
- 作废捕获：1
- 有效捕获全部帧：$validFrames
- 作废捕获帧：$abortedFrames
- 有效稳定段帧：$stableFrames
- 干净 HR 帧：$cleanHrFrames
- 有效 SpO2 帧：$cleanSpo2Frames
- 稳定段 98--114 bpm 且 HR bit0 有效：$targetLocks
- 稳定段 SpO2<90 且 bit1 有效：$badSpo2

此目录保留原始数据和派生数据。矩阵验收结论见同日 `_cdx` 真机矩阵报告；原始数据不因后续审查或算法调整而删除或覆盖。
"@
$readme | Set-Content -LiteralPath $readmePath -Encoding utf8NoBOM

$filesForManifest = @(
    'extract_wrist_matrix_evidence_cdx.ps1',
    'raw_serial_captures_cdx.json',
    'raw_serial_captures_cdx.log',
    'frames_cdx.csv',
    'signal_diag_cdx.csv',
    'capture_summary_cdx.csv',
    'external_reference_cdx.csv',
    'README_cdx.md'
)
$manifest = foreach ($name in $filesForManifest) {
    $path = Join-Path $outputPath $name
    $item = Get-Item -LiteralPath $path
    [pscustomobject]@{
        file = $name
        bytes = $item.Length
        sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash
    }
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding utf8NoBOM

Write-Output "CAPTURE_COUNT=$($captures.Count)"
Write-Output "VALID_CAPTURE_COUNT=$(@($rawRecords | Where-Object { $_.valid_for_matrix }).Count)"
Write-Output "ABORTED_CAPTURE_COUNT=$(@($rawRecords | Where-Object { -not $_.valid_for_matrix }).Count)"
Write-Output "VALID_ALL_FRAME_COUNT=$validFrames"
Write-Output "ABORTED_FRAME_COUNT=$abortedFrames"
Write-Output "STABLE_FRAME_COUNT=$stableFrames"
Write-Output "CLEAN_HR_FRAME_COUNT=$cleanHrFrames"
Write-Output "VALID_SPO2_FRAME_COUNT=$cleanSpo2Frames"
Write-Output "TARGET_FALSE_LOCK_COUNT=$targetLocks"
Write-Output "BAD_VALID_SPO2_COUNT=$badSpo2"
Write-Output "MATRIX_STARTED_LOCAL=$($matrixStartedLocal.ToString('yyyy-MM-dd HH:mm:ss.fff zzz'))"
Write-Output "MATRIX_COMPLETED_LOCAL=$($matrixCompletedLocal.ToString('yyyy-MM-dd HH:mm:ss.fff zzz'))"
Write-Output "MATRIX_WALL_CLOCK_SECONDS=$([math]::Round($matrixWallClockSeconds, 3))"
Write-Output "CAPTURE_EXECUTION_SECONDS=$([math]::Round($captureExecutionSeconds, 3))"
Write-Output "SOURCE_SESSION_SHA256=$sessionHash"
Write-Output "OUTPUT_DIR=$outputPath"
