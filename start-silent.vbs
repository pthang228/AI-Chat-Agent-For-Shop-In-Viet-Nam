' Double-click file này để khởi động TẤT CẢ dịch vụ mà KHÔNG hiện cửa sổ terminal đen.
' Nó gọi start-all.ps1 chạy ẩn. Log ở thư mục data\. Dừng: chạy stop-all.bat.
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = base
sh.Run "powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & base & "\start-all.ps1""", 0, False
