# 计算距离下一个采集时点（03:00 / 09:00 / 15:00 / 21:00）还有多少秒
$now = Get-Date
$best = 86400
foreach ($h in 3, 9, 15, 21) {
    $t = $now.Date.AddHours($h)
    if ($t -le $now) { $t = $t.AddDays(1) }
    $d = ($t - $now).TotalSeconds
    if ($d -lt $best) { $best = $d }
}
[int]$best
