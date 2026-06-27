# Khởi động TẤT CẢ dịch vụ ở chế độ ẨN (không hiện cửa sổ terminal đen).
# Log của từng dịch vụ ghi vào data\*.out.log / *.err.log để kiểm tra khi cần.
# Gọi qua start-silent.vbs (double-click) để chạy hoàn toàn ẩn.
# Dừng: chạy stop-all.bat.

$ErrorActionPreference = 'SilentlyContinue'
$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
$npm  = "C:\Program Files\nodejs\npm.cmd"
$data = Join-Path $ROOT 'data'
if (-not (Test-Path $data)) { New-Item -ItemType Directory $data | Out-Null }

function Start-Svc($file, $svcArgs, $wd, $name) {
    Start-Process -WindowStyle Hidden -FilePath $file -ArgumentList $svcArgs -WorkingDirectory $wd `
        -RedirectStandardOutput (Join-Path $data "$name.out.log") `
        -RedirectStandardError  (Join-Path $data "$name.err.log")
}

Start-Svc $npm     'start'                     (Join-Path $ROOT 'zalo-node') 'zalo-node'
Start-Svc 'python' @('-m','app.main_node')     $ROOT                         'main_node'
Start-Svc 'python' @('scripts\run_meta.py')    $ROOT                         'run_meta'
Start-Svc 'python' @('-m','app.main_telegram') $ROOT                         'telegram'
Start-Svc $npm     @('run','dev')              (Join-Path $ROOT 'web-ui')    'web-ui'

Start-Sleep -Seconds 8
Start-Process 'http://localhost:5173'
