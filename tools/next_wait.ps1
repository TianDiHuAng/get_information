# 计算距离下一个采集时点（每天 09:00）还有多少秒
$now = Get-Date
$t = $now.Date.AddHours(9)
if ($t -le $now) { $t = $t.AddDays(1) }
[int](($t - $now).TotalSeconds)
