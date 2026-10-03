# tqdmboard

本機 Python training app。啟動 App 一次後，可在同一個網頁選擇不同的 Python scripts；training subprocess 結束後，App server 仍保持運作。不需要安裝新的 Python 套件。

目前預設 demo 是 `rl2048_demo.py`，使用公開 2048 DQN，在 RTX 5060 訓練。執行方式、metrics、checkpoint 接續與來源見 `2048_DEMO.md`；demo 額外需要 `requirements-2048.txt`，Board 本身仍只使用標準函式庫。

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

啟動時會開啟瀏覽器並印出本機 URL。關閉最後一個 Board 分頁後，保留 3 秒供重新整理／重新開頁，接著停止 training process 並退出 App；仍有其他 Board 分頁時保持運作。一般分頁關閉透過 browser beacon 通知；瀏覽器崩潰或沒有送出通知時，90 秒 heartbeat timeout 後加上 3 秒緩衝退出。背景分頁每秒回報一次；若瀏覽器凍結分頁超過 90 秒，也可能觸發退出。App 尚未連上任何分頁時不自動退出，供 `--no-browser` 使用。`Quit App` 或終端機 Ctrl+C 可立即要求退出。退出先要求合作停止，最多等待 3 秒，仍未退出則 Force Stop，因此不保證新的 checkpoint。沒有設定 global PATH，所以從其他目錄啟動時，請指定 `tqdmboard.cmd` 的完整路徑。

`--directory "C:\path\to\project"` 可指定初始 folder；`--port 8765` 指定固定 port；`--no-browser` 不自動開啟瀏覽器。

## Basic

1. 按 Choose Script，使用 Windows 原生選檔視窗選擇 `.py`。Cancel 保留目前設定。
2. Script 所在 folder 自動成為 Working Directory，並偵測附近 Python environment。
3. 在 Basic 的 Arguments 填入所需 command-line arguments，再按 Run；Basic 顯示 process state、stdout／stderr、progress、metrics、Training History，以及 Pause／Stop／Save Checkpoint。
4. Stop Process 結束 child process；Quit App 關閉 App。Script 結束後 App 仍可選擇下一個 script。

Process Console 提供 Follow Tail、Copy Output，完整 log 存在 `runs/tqdmboard/`。一般 Python script 也能執行；training controls 需要 script 接入 Qtqdm。

## Advanced

Advanced 預設收合，包含 Python Executable、Working Directory、Restart Process、Force Stop、PID／exit code 和 System Resources；training 的 Learning Rate、Checkpoint Schedule、Full Metric History、capabilities 與 Training History Axes 也放在此處。Choose Python／Choose Directory 同樣開啟系統視窗；也可手動填入這兩個欄位。

兩張圖表各有 Smoothing：None (Raw)、EMA 0.6／0.9／0.99。EMA 的 weight 越大，曲線越平滑；公式為 `value = weight * previous + (1 - weight) * current`，首點使用原始值。只改顯示，不修改訓練、CSV 或儲存的數據。Overview 對其 downsampled points 計算 EMA；Full Metric History 對完整 points 計算，兩張圖的平滑曲線可能不同。

## Run History

Basic 的 Run History 選擇一次執行後按 View Record，可查看當時 Python／script／arguments／working directory、時間、exit code、Console、最後 metrics 與曲線。Live View 返回目前執行；回看模式停用 process 與 training controls，避免誤操作正在執行的程式。Refresh Records 更新清單。

資料庫保存在 `runs/tqdmboard/records.sqlite3`，完整 Console log 在同一 folder；Console viewer 顯示末尾約 64 KB。完整 numeric metric samples 按 update index 分頁讀取，重開 App 仍可回看。`--records-path` 可指定其他 SQLite 路徑。紀錄從此版本開始建立，不會自動還原舊 logs 的 arguments 或結果，也不包含 script 原始碼、model 檔案副本或 resource history；checkpoint 路徑仍指向 script 原本儲存的位置。

一般 Python scripts 保存指令、exit code 與 Console。使用 `with Qtqdm(...)` 的 scripts 在離開 context 時直接保存完整 final snapshot 與歷史，避免短程式在 polling 之間結束而漏掉結果；不用 context 時請呼叫 `close()`。Force Stop、crash 或磁碟寫入失敗只能保留已保存資料；沒有正常退出紀錄時標示 No exit recorded，training 顯示最後捕捉的結果。

Basic 的 Arguments 使用原本 command-line 格式，例如 `--steps 100 --learning-rate 0.03 --momentum 0.6`。App 以 argument list 和 shell=False 啟動，含空白的單一 argument 使用引號。

Restart Process 先要求舊 script 停止，等 exit 後以現在的 launcher settings 啟動新 process，重新載入程式碼。Force Stop 立即終止 process tree，不保證保存新的 checkpoint。沒有 Qtqdm 內部的 Training Restart 或 hyperparameter 重啟表單。

Qtqdm-compatible script 的狀態由 Board 自己的 UI 顯示。App 設定 PYTHONPATH 讓外部 scripts 找到 Qtqdm，並設定 TQDMBOARD=1 避免額外開啟 browser tab。GPU 範例保持完成／停止後的頁面供閱讀；下一次執行由 Board 啟動新 process。

只有外部 Board 分成 Basic／Advanced。內部 Qtqdm 獨立頁面直接呈現所有功能，不分組；兩個頁面共用 rendering behavior 與 chart code，各自擁有 markup、layout 和資料入口。Board 沒有 iframe，Process Console 顯示完整 child stdout／stderr。

## Code architecture

```text
tqdmboard.cmd / tqdmboard.py
    └─ TqdmBoard (board.py): app HTTP server
         ├─ board.html / board.js: launcher + training UI
         ├─ training_view.js / charts.js: shared rendering behavior
         ├─ TrainingBridge (board_training.py): training state cache / controls
         ├─ RunRecords (board_records.py): SQLite run metadata / raw samples
         ├─ BoardViewers (board_viewers.py): last-tab shutdown / refresh grace
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

ProcessRunner 透過 Qtqdm 印出的 loopback URL 找到 child dashboard。TrainingBridge 在背景每 250 ms 讀取其 `/state`，Board `/state` 合併 process、resources 與 training 快取；前端不跨 port 存取子頁面。Board `/training-control` 驗證 job_id 後轉送至 child `/control`，不需要 script 加入新接口。更換 process 清空 training 快取和 chart settings；process 結束後保留最後收到的資料，停用 controls。讀取 timeout 為 1 秒，資料超過 3 秒或讀取失敗時停用 controls。這是本機單 process launcher，不是 job queue，也不是 terminal emulator。Windows 的 Force Stop 會終止所啟動的 process tree，包含 `.venv` redirector 建立的 child interpreter；不會管理 script 自行建立的獨立服務。

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

測試涵蓋 native dialog initialization／selection／Cancel、Windows argument quoting、空白路徑、working directory、stdout／stderr、process exit／restart／force stop、初始化期間的 Stop，以及單次 training controls、control relay、child HTTP errors、stale job 拒絕、斷線資料保留和慢回應的隔離。網頁測試另驗證 RTX 5060 訓練、Basic／Advanced、單次 Qtqdm 與 Restart Process。

Chart display regression test：安裝 Node.js／Playwright 並有 Edge 時，從專案根目錄執行 `node tests/chart_ui_smoke.cjs`。測試 DPR 2、Advanced 展開、resize、大步數／微小數值刻度、手動範圍與 Arguments 的 Basic 位置；使用固定資料，不執行模型訓練。

Full Metric History 保留整個 run 的數值更新；追加 update 不裁掉早期 points。重新整理以 incremental history API 重建完整曲線。Board 保留收到的歷史，child process 結束後仍可查看；開始新 process 時才清空前一個 job。

`node tests/board_records_ui_smoke.cjs` 驗證短程式的 3501 點 final flush、重開 App 的完整紀錄、回看期間的控制隔離、EMA 不修改 raw data、重新整理、多分頁及最後分頁關閉後的 process／App 退出。
