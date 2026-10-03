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

啟動時會開啟瀏覽器並印出本機 URL。關閉瀏覽器分頁不會停止 App 或 training process，可用同一 URL 重新開啟。`Quit App` 或終端機 Ctrl+C 可立即要求退出。退出先要求合作停止，最多等待 3 秒，仍未退出則 Force Stop，因此不保證新的 checkpoint。沒有設定 global PATH，所以從其他目錄啟動時，請指定 `tqdmboard.cmd` 的完整路徑。

`--directory "C:\path\to\project"` 可指定初始 folder；`--port 8765` 指定固定 port；`--no-browser` 不自動開啟瀏覽器。

## Tabs

外部 Board 依操作目的分成四個 tabs，預設 Monitor。上方共用 Current Script、Process State、System Resources 與 Quit App，顯示目前 process，切到 History 也不改變。

| Tab | 內容 |
| --- | --- |
| Run | Script、Python Environment、Working Directory、Arguments、`Patch tqdm (no code changes)` 勾選框（以 `python -m qtqdm` 啟動，免改 script 即可顯示 tqdm 進度條）、Run／Restart Process |
| Monitor | Progress、Metrics、曲線、Pause／Resume／Stop、Save Checkpoint、Stop Process／Force Stop |
| Console | 目前 process 的 stdout／stderr、Follow Tail、Copy Output、完整 Log Path |
| History | Recorded Run · Read-only，內含 Overview／Charts／Console |

1. 在 Run 按 Choose Script，使用 Windows 原生選檔視窗選擇 `.py`。Cancel 保留目前設定。
2. Script 所在 folder 自動成為 Working Directory，並偵測附近 Python environment。
3. 填入 Arguments 後按 Run，接受啟動後切換至 Monitor；Script 結束後 App 仍可選擇下一個 script。
4. Monitor 的 Training Controls 展開 Learning Rate／Checkpoint Schedule；Chart Settings 調整 Overview 的 axes／smoothing；Full Metric History 展開完整曲線及自己的設定。
5. Console 顯示目前 process 的輸出，完整 log 在 `runs/tqdmboard/`。一般 Python script 也能執行；training controls 需要 script 接入 Qtqdm。

Tabs 只切換 DOM visibility，不做頁面 navigation、不重新建立 Monitor，也不發送 training／process commands。Monitor 和即時 Console 在背景持續更新；曲線設定跨 tab 保留，新 process 才 reset。支援左右方向鍵、Home／End 切換 tabs。

兩張圖表各有 Smoothing：None (Raw)、EMA 0.6／0.9／0.99。EMA 的 weight 越大，曲線越平滑；公式為 `value = weight * previous + (1 - weight) * current`，首點使用原始值。只改顯示，不修改訓練、CSV 或儲存的數據。Overview 對其 downsampled points 計算 EMA；Full Metric History 對完整 points 計算，兩張圖的平滑曲線可能不同。

## Run History

可用 Save Name 命名紀錄，Search Records 搜尋名稱、script、arguments 或狀態。Export ZIP 包含 `record.json`、完整 numeric samples 的 `metrics.csv` 與完整 `console.log`；不包含模型或 script 副本。Delete Record 刪除資料庫中的紀錄和曲線，保留原始 log 與 checkpoint。正在 running 或 detached 的紀錄不能刪除。

Monitor 與 History 都提供 Error Summary、可展開的 Traceback 與 Full Log Path。沒有 Python traceback 的異常退出會顯示 exit code；Board 不再用錯誤彈窗打斷操作。History 保存結束時的錯誤資訊，重開 App 仍可查看。

History 選擇一次執行後按 View Record。Overview 顯示當時 Python／script／arguments／working directory、時間、exit code、最後 metrics／checkpoint；Charts 顯示歷史曲線及自己的 axes／smoothing；Console 顯示該次執行的輸出。Refresh Records 更新清單及目前開啟紀錄的 Overview／metrics／Console／增量曲線，保留 Axes 與 Smoothing；再次 View Record 同一筆也保留設定。

History 使用獨立的 `board_history.js`、chart instances、Console view、record cursor 和 request generation。它只讀取紀錄 APIs，不影響目前 process、Monitor／Console 更新或其控制狀態；選取較慢的舊紀錄回應不會覆蓋後來的選擇。回到 Monitor 即可操作目前訓練，不需要 Live View 切換。正在執行的 run 也能回看，此時呈現按 View Record 當下保存的 snapshot，並非另一份 live monitor；手動 Refresh 讀取最新內容。每 2 秒檢查 metadata，Training State／Process State／Exit Code 改變時自動重新讀取目前紀錄，所以已開啟的 running 紀錄結束後會顯示最終結果。清單同時標出 Training 與 Process 狀態。

資料庫保存在 `runs/tqdmboard/records.sqlite3`，完整 Console log 在同一 folder；Console viewer 顯示末尾約 64 KB。完整 numeric metric samples 按 update index 分頁讀取，重開 App 仍可回看。`--records-path` 可指定其他 SQLite 路徑。紀錄從此版本開始建立，不會自動還原舊 logs 的 arguments 或結果，也不包含 script 原始碼、model 檔案副本或 resource history；checkpoint 路徑仍指向 script 原本儲存的位置。

一般 Python scripts 保存指令、exit code 與 Console。使用 `with Qtqdm(...)` 的 scripts 在離開 context 時直接保存完整 final snapshot 與歷史，避免短程式在 polling 之間結束而漏掉結果；不用 context 時請呼叫 `close()`。Force Stop、crash 或磁碟寫入失敗只能保留已保存資料；沒有正常退出紀錄時標示 No exit recorded，training 顯示最後捕捉的結果。Exit Code 未產生時明確標 Pending (process running)，沒有退出證據則標 Unknown (exit not recorded)，不會填入假的 0。

新紀錄保存 Board owner 與 child 的 PID／process creation identity。只有 Board 啟動時執行 recovery：仍有活著的 owner 時不更動；owner 已消失但原 child 尚在執行時標 detached；確定原 process 不存在時標 interrupted；舊紀錄沒有可驗證身分時標 unknown。這些狀態都保留原本 metrics／curves／Console，且未知 Exit Code 保留 null，不假造結束時間。

Run 的 Arguments 使用原本 command-line 格式，例如 `--steps 100`。App 以 argument list 和 shell=False 啟動，含空白的單一 argument 使用引號。

Restart Process 先要求舊 script 停止，等 exit 後以現在的 launcher settings 啟動新 process，重新載入程式碼。Force Stop 立即終止 process tree，不保證保存新的 checkpoint。沒有 Qtqdm 內部的 Training Restart 或 hyperparameter 重啟表單。

Qtqdm-compatible script 的狀態由 Board 自己的 UI 顯示。App 設定 PYTHONPATH 讓外部 scripts 找到 Qtqdm，並設定 TQDMBOARD=1 避免額外開啟 browser tab。Board 模式的 Qtqdm.wait() 完成／停止後直接 close，不等待 Enter，child process 自然退出；結果由 Board 和 History 保留。獨立使用 Qtqdm.wait() 仍等待 Enter。下一次執行由 Board 啟動新 process。

只有外部 Board 使用 Run／Monitor／Console／History tabs。內部 Qtqdm 獨立頁面直接呈現所有功能，不分組；兩個頁面共用 rendering behavior 與 chart code，各自擁有 markup、layout 和資料入口。Board 沒有 iframe，Process Console 顯示完整 child stdout／stderr。

## Code architecture

```text
tqdmboard.cmd / tqdmboard.py
    └─ TqdmBoard (board.py): app HTTP server
         ├─ board.html / board.js: tabs + launcher + live training UI
         ├─ board_history.js: independent records UI / names / search / export / delete
         ├─ board_errors.py / board_errors.js: error summary / traceback display
         ├─ training_view.js / charts.js: shared rendering behavior
         ├─ TrainingBridge (board_training.py): training state cache / controls
         ├─ RunRecords (board_records.py): SQLite run metadata / raw samples
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

ProcessRunner 透過 Qtqdm 印出的 loopback URL 找到 child dashboard。TrainingBridge 在背景每 250 ms 讀取其 `/state`，Board `/state` 合併 process、resources 與 training 快取；前端不跨 port 存取子頁面。Board `/training-control` 驗證 job_id 後轉送至 child `/control`，不需要 script 加入新接口。更換 process 清空 training 快取和 chart settings；process 結束後從 SQLite 讀回最後保存的 snapshot 與完整歷史，停用 controls；如果沒有 final snapshot，明確標 Last captured 並保留舊數據。讀取 timeout 為 1 秒，資料超過 3 秒或讀取失敗時停用 controls。ProcessRunner 的 stdout reader 與 exit finalizer 分開；每個 finalizer 持有穩定 record_id，即使下一次 execution 已啟動仍會完成上一筆紀錄，App 關閉前等待全部 finalizers。這是本機單 process launcher，不是 job queue，也不是 terminal emulator。Windows 的 Force Stop 會終止所啟動的 process tree，包含 `.venv` redirector 建立的 child interpreter；不會管理 script 自行建立的獨立服務。

## System Resources

App 顯示整台電腦的 CPU utilization、已用／總 RAM，以及 NVIDIA GPU utilization、已用／總 VRAM。數值包含其他應用程式，不代表所選 training process 的獨占用量；不必修改 training script。

`board_monitor.py` 的背景 thread 約每秒採樣一次，HTTP 只讀快取，不會為了查詢 GPU 阻塞網頁或訓練。Windows CPU／RAM 使用系統 API，GPU 使用 driver 隨附的 `nvidia-smi`；不需安裝 psutil 或 NVML Python module。CPU 初次採樣需等待第二組 counters 才能計算 utilization。

每次 GPU 查詢最多等待 1.2 秒，失敗或找不到 nvidia-smi 時標示 unavailable，CPU／RAM 仍更新。頁面顯示 Sample age，超過 3 秒標示 stale。關閉 App 會停止採樣 thread。CPU／RAM 採樣目前支援 Windows；monitor 不保存 resource history。

## Script 接入

### Resume

接續訓練時，在 Run 的 Arguments 輸入 script 提供的 `--resume PATH`（例如 2048 demo，見 `2048_DEMO.md`）。由 script 自己載入並驗證 checkpoint；Board 不檢查檔案內容。

基本使用 `with Qtqdm(items, desc="Training") as progress:`，再以 `set_postfix` 回報 metrics。需要 Save／Learning Rate 時，使用 `progress.register_controls(...)` 提供 handlers 與目前 learning rate；迴圈不必自己檢查請求。接口與範例詳見 `qtqdm/README.md`。

此次完成基本接入、統一控制接口與外部 resource monitoring；依目前決定，不加入 tqdm static converter。

## 驗證

```powershell
& '.\.venv\Scripts\python.exe' -m unittest discover -s tests -v
```

測試涵蓋 native dialog initialization／selection／Cancel、Windows argument quoting、空白路徑、working directory、stdout／stderr、process exit／restart／force stop、初始化期間的 Stop，以及單次 training controls、control relay、child HTTP errors、stale job 拒絕、斷線資料保留和慢回應的隔離。網頁測試另驗證 RTX 5060 訓練、四個 tabs、單次 Qtqdm 與 Restart Process。

Chart display regression test：安裝 Node.js／Playwright 並有 Edge 時，從專案根目錄執行 `node tests/chart_ui_smoke.cjs`。測試 DPR 2、Monitor details 展開、resize、大步數／微小數值刻度、手動範圍與 Arguments 的 Run 位置；使用固定資料，不執行模型訓練。

Full Metric History 保留整個 run 的數值更新；追加 update 不裁掉早期 points。重新整理以 incremental history API 重建完整曲線。Board 保留收到的歷史，child process 結束後仍可查看；開始新 process 時才清空前一個 job。

`node tests/board_records_ui_smoke.cjs` 驗證短程式的 3501 點 final flush、重開 App 的完整紀錄、回看期間 training steps 持續增加、Monitor chart settings 保留、過期 record response 隔離、tabs 不發送控制命令、EMA 不修改 raw data、重新整理，以及 Quit App 後的 process／App 退出；另驗證已開啟 running record 的手動 Refresh、Axes／EMA 保留與自動 terminal state／Exit Code 更新。

新增功能測試涵蓋紀錄命名與 ZIP 全量匯出、刪除保留 log、拒絕刪除 active record，以及錯誤摘要與 traceback 持久化。Records browser test 另驗證搜尋、下載、刪除與 Monitor 錯誤顯示；`node tests/board_2048_smoke.cjs` 使用 RTX 5060 驗證實際 Resume（Arguments 填入 `--resume`）。
