# Stop all running instances of main.py
Write-Host "Stopping any running local instances of main.py..." -ForegroundColor Yellow
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*python*main.py*" } | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force
    Write-Host "Stopped process ID: $($_.ProcessId)" -ForegroundColor Green
}
Write-Host "Done. Your bot is ready to be run on Cloud hosting without conflict." -ForegroundColor Cyan
