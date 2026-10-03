# tqdmboard

本機 Python training app。啟動 App 一次後，可在同一個網頁選擇不同的 Python scripts；training subprocess 結束後，App server 仍保持運作。不需要安裝新的 Python 套件。

## 啟動

在專案目錄的 CMD 執行：

```bat
tqdmboard
```

PowerShell 使用：

```powershell
& '.\tqdmboard.cmd'
```

也可以直接執行 Python entry point：

```powershell
& '.\.venv\Scripts\python.exe' tqdmboard.py
```

啟動時會開啟瀏覽器並印出本機 URL。關閉瀏覽器不會停止 App；可以重新開啟同一個 URL。`Quit App` 或終端機的 Ctrl+C 才會關閉 App。沒有設定 global PATH，所以從其他目錄啟動時，請指定 `tqdmboard.cmd` 的完整路徑。

`--directory "C:\path\to\project"` 可指定初始 folder；`--port 8765` 指定固定 port；`--no-browser` 不自動開啟瀏覽器。

## Basic

1. 按 Choose Script，使用 Windows 原生選檔視窗選擇 `.py`。Cancel 保留目前設定。
2. Script 所在 folder 自動成為 Working Directory，並偵測附近 Python environment。
3. 按 Run；Basic 顯示 process state、stdout／stderr 與 Qtqdm Training Dashboard。
4. Stop Process 結束 child process；Quit App 關閉 App。Script 結束後 App 仍可選擇下一個 script。

Process Console 提供 Follow Tail、Copy Output，完整 log 存在 `runs/tqdmboard/`。一般 Python script 也能執行；training controls 需要 script 接入 Qtqdm。

## Advanced

Advanced 預設收合，包含 Python Executable、Working Directory、Arguments、Restart Process、Force Stop、PID／exit code 和 System Resources。Choose Python／Choose Directory 同樣開啟系統視窗；也可手動填入這兩個欄位。

Arguments 使用原本 command-line 格式，例如 `--steps 100 --learning-rate 0.03 --momentum 0.6`。App 以 argument list 和 shell=False 啟動，含空白的單一 argument 使用引號。

Restart Process 先要求舊 script 停止，等 exit 後以現在的 launcher settings 啟動新 process，重新載入程式碼。Force Stop 立即終止 process tree，不保證保存新的 checkpoint。沒有 Qtqdm 內部的 Training Restart 或 hyperparameter 重啟表單。

Qtqdm-compatible script 自動出現在 iframe。App 設定 PYTHONPATH 讓外部 scripts 找到 Qtqdm，並設定 TQDMBOARD=1 避免額外開啟 browser tab。GPU 範例保持完成／停止後的頁面供閱讀；下一次執行由 Board 啟動新 process。

Training Dashboard 的 Basic 是 progress、metrics、Pause／Stop、手動 Save 和全程 history；Advanced 是 learning rate、checkpoint schedule、recent history 和 capabilities。Axis Settings 各自收合。App iframe 使用外層 Process Console，Open Dashboard 的獨立頁面另有 Python Console。

## Code architecture

```text
tqdmboard.cmd / tqdmboard.py
    └─ TqdmBoard (board.py): app HTTP server
         ├─ board.html / board.js: launcher UI
         ├─ NativePicker (board_dialog.py): Windows file / folder dialog
         ├─ board_files.py: environments / arguments
         ├─ ResourceMonitor (board_monitor.py): CPU / RAM / GPU sampling
         └─ ProcessRunner (board_process.py): subprocess lifecycle
              ├─ ConsoleOutput: stdout + stderr + persistent process log
              └─ selected Python script
                   └─ Qtqdm (single run)
                        └─ Dashboard / model / optimizer / checkpoint
```

App 與 training 使用不同 process；App 不存取 model／optimizer。它管理 Python executable、script、arguments、cwd、stdin／stdout，以及 process lifecycle。Training script 仍負責模型與訓練，既有 Qtqdm APIs 負責 training controls。

ProcessRunner 透過 Qtqdm 印出的 loopback URL 找到 child dashboard，前端直接顯示 iframe；沒有新增必須手動接入的 IPC schema。這是本機單 process launcher，不是 job queue，也不是 terminal emulator。Windows 的 Force Stop 會終止所啟動的 process tree，包含 `.venv` redirector 建立的 child interpreter；不會管理 script 自行建立的獨立服務。

## System Resources

App 顯示整台電腦的 CPU utilization、已用／總 RAM，以及 NVIDIA GPU utilization、已用／總 VRAM。數值包含其他應用程式，不代表所選 training process 的獨占用量；不必修改 training script。

`board_monitor.py` 的背景 thread 約每秒採樣一次，HTTP 只讀快取，不會為了查詢 GPU 阻塞網頁或訓練。Windows CPU／RAM 使用系統 API，GPU 使用 driver 隨附的 `nvidia-smi`；不需安裝 psutil 或 NVML Python module。CPU 初次採樣需等待第二組 counters 才能計算 utilization。

每次 GPU 查詢最多等待 1.2 秒，失敗或找不到 nvidia-smi 時標示 unavailable，CPU／RAM 仍更新。頁面顯示 Sample age，超過 3 秒標示 stale。關閉 App 會停止採樣 thread。CPU／RAM 採樣目前支援 Windows；monitor 不保存 resource history。

## Script 接入

基本使用 `with Qtqdm(items, desc="Training") as progress:`，再以 `set_postfix` 回報 metrics。需要 Save／Learning Rate 時，使用 `progress.register_controls(...)` 提供 handlers 與目前 learning rate；迴圈不必自己檢查請求。接口與範例詳見 `qtqdm/README.md`，GPU 範例已改用新接口。

此次完成基本接入、統一控制接口與外部 resource monitoring；依目前決定，不加入 tqdm static converter。

## 驗證

```powershell
& '.\.venv\Scripts\python.exe' -m unittest discover -s tests -v
```

測試涵蓋 native dialog initialization／selection／Cancel、Windows argument quoting、空白路徑、working directory、stdout／stderr、process exit／restart／force stop、初始化期間的 Stop，以及單次 training controls。網頁測試另驗證 RTX 5060 訓練、Basic／Advanced、單次 Qtqdm 與 Restart Process。
