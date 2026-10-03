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

## 使用

1. 在 Local File Browser 輸入 Directory，按 Browse；點選 folder 進入，或點選 `.py` script。
2. 選擇 Python Executable。App 會列出附近的 `.venv`／`venv` 與目前 Python；也可手動填入 executable 完整路徑。
3. Working Directory 預設為 script 所在 folder。相對資料路徑與 script 的輸出檔案會以它為基準。
4. Arguments 使用原本 command-line 格式，例如 `--steps 100 --learning-rate 0.03`。含空白的單一 argument 請使用引號。
5. 按 Run。Process Console 顯示 stdout／stderr，完整 process log 存在 App 專案的 `runs/tqdmboard/`。

同時管理一個 process。App 使用 argument list 與 `shell=False` 啟動，Arguments 不會交給 CMD 執行；像 `&` 的內容會當成 argument。

## Process 與 Training 控制

| 控制 | 行為 |
| --- | --- |
| Run | 啟動所選 script 與 Python environment |
| Stop Process | 要求 Qtqdm 停止，並通知 script 的 stdin 結束等待；正常流程可先保存 checkpoint |
| Restart Process | 先停止舊 process，再以目前 launcher settings 啟動新 process；重新載入 script 程式碼 |
| Force Stop | 立即終止目前 Python process，不保證產生新的 checkpoint |
| Training Dashboard 的 Restart | 在同一個 training process 內，使用 Restart Hyperparameters 重建 model／optimizer |

Running process 不能再次按 Run。若 graceful stop 尚未完成，App 會顯示 Stopping，並允許使用者選擇 Force Stop；不會因為顯示更新而要求 training 等待瀏覽器。

Qtqdm-compatible script 會自動出現在 Training Dashboard iframe 中。App 設定 `PYTHONPATH` 讓外部 folder 的 scripts 找到目前 Qtqdm，並設定 `TQDMBOARD=1`，避免額外開啟 browser tab。`TrainingSession` 在 App 模式會保持開啟，因此 Completed／Stopped／Failed 後仍可調整 hyperparameters 再 Restart，不需要額外加 `--keep-open`。

既有 `gpu_training_demo.py` 與 `example.py` 可直接選擇執行，這一步沒有要求使用者手動修改 script。tqdm static converter 尚未實作；目前前提仍是 training script 已符合 Qtqdm API。一般 `.py` 也能 Run 與顯示 Console，但沒有 Qtqdm dashboard 時不會出現 training controls。

## Code architecture

```text
tqdmboard.cmd / tqdmboard.py
    └─ TqdmBoard (board.py): app HTTP server
         ├─ board.html / board.js: launcher UI
         ├─ board_files.py: folder browser / environments / arguments
         ├─ ResourceMonitor (board_monitor.py): CPU / RAM / GPU sampling
         └─ ProcessRunner (board_process.py): subprocess lifecycle
              ├─ ConsoleOutput: stdout + stderr + persistent process log
              └─ selected Python script
                   └─ Qtqdm / TrainingSession
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

測試涵蓋 folder listing、Windows argument quoting、空白路徑、working directory、stdout／stderr、process exit／restart／force stop，以及 training session 的既有 controls。網頁測試另驗證外部 script integration、RTX 5060 訓練、Training Restart 與 Restart Process。
