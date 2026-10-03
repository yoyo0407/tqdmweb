# Qtqdm 架構

| 檔案 | 責任 |
| --- | --- |
| `index.html` | 顯示狀態與曲線，送出使用者指令 |
| `charts.js` | 圖表設定、座標轉換、刻度與曲線繪製 |
| `chart_history.py` | 完整數值歷史、狀態 preview 與增量 paging |
| `console.py` | 鏡像 Python stdout／stderr、保存完整 log、限制網頁輸出長度 |
| `console.js` | 更新 Console Output、Follow Tail 與 Copy Output |
| `web.py` | Qtqdm 入口，接合 progress、console capture 與 dashboard |
| `dashboard.py` | 本機 HTTP server，驗證請求後呼叫 state／control callback |
| `board.py` | tqdmboard App HTTP server，不隨 training process 結束 |
| `board.html`／`board.js` | Basic／Advanced launcher UI 與原生選檔操作，自行呈現 training data 與 controls |
| `board_training.py` | 背景讀取 training state、保留快取、驗證 job_id 並轉送 controls |
| `training_view.js` | 兩個頁面共用的 progress／metrics／controls rendering behavior |
| `board_dialog.py` | Windows 原生 file／folder dialogs，取得本機完整路徑 |
| `board_files.py` | Python environment discovery、arguments／paths 驗證 |
| `board_process.py` | 啟動、停止、重啟 subprocess，收集原始 stdout／stderr |
| `board_monitor.py` | 背景採樣 Windows CPU／RAM 與 NVIDIA GPU，供 App 讀取快取 |
| `resources.js` | 顯示 system resource 數值、unavailable 與 sample age |
| `control.py` | 使用 Condition 協調網頁執行緒與訓練執行緒 |
| `progress.py` | 計數、歷史取樣，每一步開始前檢查控制狀態 |
| `csv_log.py` | 保存完整指標更新 |
| `../rl2048_demo.py` | 公開 2048 DQN 的 Qtqdm adapter；每個 move 回報 metrics 與處理 controls |
| `../rl2048_checkpoint.py` | 保存／恢復 model、target、optimizer、replay、game 與 RNG |
| `../third_party/rl2048/` | 固定版本的 MIT 上游環境、DQN、network 與 replay buffer，保留來源與修改紀錄 |

`qtqdm/__init__.py` 是公開匯入入口，讓使用者寫 `from qtqdm import Qtqdm`。`Qtqdm` 繼承 `Progress`，再加上 HTTP 伺服器；`Progress` 分別持有控制模組和 CSV 紀錄器。監看套件本身不需要 PyTorch。

## tqdmboard App

`../tqdmboard.cmd` 呼叫專案 `.venv` 的 Python 執行 `../tqdmboard.py`，進入 `board.py`。App HTTP server 與 Python training subprocess 分開；App 本身只依賴標準函式庫。`board_process.py` 以 shell=False 與獨立 argument list 啟動所選 script，保留 stdin pipe，收集合併的 stdout／stderr。每個 process 建立新 log，網頁只保留 bounded console buffer。

ProcessRunner 發現 `Qtqdm page: http://127.0.0.1:PORT/` 後，由 TrainingBridge 背景讀取 child `/state`。Board 的 `/state` 合併 process、resources 和 training 快取，自己的 HTML／JS 呈現 training data；沒有 iframe。Board `/training-control` 檢查 job_id，再轉送至 child `/control`。讀取 timeout 為 1 秒，快取失敗或超過 3 秒停用 controls；HTTP state 請求不等待 child 回應。新 process 清除舊快取，退出後保留最後收到的資料。`TQDMBOARD=1` 避免 Qtqdm 另開分頁，2048 範例在此模式以 `wait()` 保留結束後的畫面。App 透過 PYTHONPATH 讓外部 scripts 找到 Qtqdm。

NativePicker 用 Windows PowerShell 的 STA process 開啟系統 OpenFileDialog／FolderBrowserDialog。選取設定透過 stdin JSON 傳遞；回傳完整路徑，Cancel 回傳 null。App 不再提供 folder listing 或網頁 directory tree。只允許一個選擇視窗，App close 時結束自己的 dialog process。

App 的 Basic 是選擇 script、Arguments、Run／Stop／Quit、Console、Training Dashboard。Advanced 是 learning rate、checkpoint schedule、full metric history、overview axis settings、capabilities，以及 environment、working directory、Restart Process／Force Stop、PID／exit code 與 System Resources。內部 Qtqdm page 不分 Basic／Advanced。選中的 script 預設以自己的 folder 作 working directory，偵測附近環境。

`Restart Process` 等待舊 process 結束後啟動新的 process。Qtqdm 只監控一次 run；model／optimizer 始終在 script 中。完整使用方式見 `../TQDMBOARD.md`。

## 執行位置

Python 主執行緒負責訓練，背景 `ThreadingHTTPServer` 負責網頁請求。瀏覽器是另一個程式，每次讀取狀態或送出指令都透過 HTTP。訓練暫停時，背景伺服器仍能回應，所以繼續和停止按鈕仍然可用。

資料顯示：訓練呼叫 `set_postfix()` → 更新狀態與 CSV → 網頁讀取 `GET /state`。

`/state` 的 `charts` 依指標名稱提供 `overview`。每個點是 `[經過秒數, 數值, 項目步數, set_postfix 更新編號]`，步數以當前已開始處理的項目計算，接續工作會保留原步數。文字、布林值及非有限數值不加入曲線，但仍保留在最新指標與 CSV。Loss 使用 `charts.loss`，與其他指標共用格式。

Canvas 以實際 CSS 尺寸與 devicePixelRatio 設定 bitmap，ResizeObserver 在展開 Advanced 或改變視窗尺寸時重繪；destroy 在新 run reset 時釋放 observer。刻度精度依 tick spacing 計算，大步數不再使用 4 位有效數字裁切。Step／Update Index 使用整數刻度，Elapsed Time 保留小數。Caption 顯示座標範圍與實際 samples 區間；Full Metric History 保留所有數值 points，X Min=0 能顯示該 run 早期的資料。前端完整曲線讀 `/history`；`charts.overview` 為最多約 600 點的縮略資料。

兩張圖各自持有 X 軸種類、Y 指標與範圍，預設使用步數／loss（沒有 loss 時選第一個數值指標）。設定只存在目前頁面，重新整理會恢復預設；圖表設定不送到訓練控制端。切換軸種類會清除該軸範圍，另一軸保持不變。指定範圍時裁切繪圖，不刪除歷史資料；Y 軸自動範圍依 X 範圍內的取樣點計算，沒有點時使用整段資料。

控制：網頁送出 `POST /control` → `TrainingControl` 記錄要求 → 迭代器在下一步邊界檢查 → 網頁讀取實際狀態。

`POST /control` 使用 JSON：

```json
{"action": "pause"}
```

| action | value | 行為 |
| --- | --- | --- |
| `pause` | 不需要 | 等待目前這一步完成後暫停 |
| `resume` | 不需要 | 喚醒暫停的迴圈 |
| `stop` | 不需要 | 在下一個邊界結束迴圈，也能停止已暫停的工作 |
| `learning_rate` | 大於零的有限數值 | 步驟邊界呼叫註冊 handler，之後回報已生效值 |
| `save` | 不需要 | 在下一個步驟邊界保存，暫停時也能保存 |
| `schedule_save` | 尚未完成且不超過總目標的整數步數 | 完成指定步數後保存一次；新預訂取代舊預訂 |
| `cancel_save` | 不需要 | 取消尚未觸發的預訂 |

網頁執行緒只改控制狀態；optimizer 始終由訓練程式操作。HTTP 接受指令不代表訓練已經執行，因此 `/state` 分別提供暫停要求、已暫停、等待套用的 learning rate 與已生效值。

## Registered controls

`Progress.register_controls` 是公開入口，轉交 `TrainingControl.register_controls`。Script 提供 `save_checkpoint()` 與 `set_learning_rate(value)`，後者同時提供初始 learning rate；函式不直接依賴 PyTorch。Qtqdm 在下一個 step boundary 自動呼叫已註冊 handler，將結果寫回 control state。控制僅保留 handler 接入方式。

`checkpoint()` 在 Condition 鎖內取得待處理指令，釋放鎖後執行 callback，再取得鎖回報結果。已暫停时也會被指令喚醒，處理後繼續等待；同一 boundary 先套用 learning rate，再執行保存。Stop 優先取消尚未套用的 learning rate；已排入的保存仍可完成。Callback 發生 Exception 時回報 `learning_rate_error`／`save_error`，不讓一般控制失敗中斷 training；不保證回滾 handler 內部的部分修改。

`/state.control.capabilities` 宣告 pause、stop、save_checkpoint、learning_rate 的支援情況。網頁顯示支援摘要與 handler 錯誤，並依 run state 停用按鈕。2048 範例每次 process 執行建立自己的 model、optimizer 與 callbacks。

## Resource monitoring

`TqdmBoard` 持有與 training subprocess 分開的 `ResourceMonitor`。它用背景 thread 約每秒呼叫 Windows GetSystemTimes／GlobalMemoryStatusEx 與 nvidia-smi，使用 Lock 更新快取；`GET /state` 合併 runner snapshot 和 resources snapshot。前端 `resources.js` 只呈現數值，不向 training 發送同步要求。

GPU 查詢 timeout 為 1.2 秒；driver 缺失、查詢失敗或資料不可用時顯示錯誤／null，不沿用舊 GPU 數值。`sampled_at` 記錄採樣開始的 Unix timestamp，前端以它計算 sample age，超過 3 秒標記 stale。所有用量為 system-wide，CPU／RAM 目前限定 Windows。App close 會通知 sampler 結束並等待 thread 返回。

Condition 讓暫停的訓練等待通知，不需要持續輪詢。`resume`、`stop` 或工作結束都會通知等待者。結束後拒絕新的控制指令；停止後不能接續同一個迭代器。

## Single run lifecycle

Script 建立 model／optimizer、Qtqdm 與 handlers，然後執行一次迴圈。Qtqdm 拒絕重用同一個 iterator。完成、停止或例外後清除未完成控制，保留讀取用狀態；`wait()` 可保留 page，`close()` 結束 server。

2048 範例正常完成或受控停止後保存 checkpoint，失敗保留 traceback 與已寫入紀錄。再次執行由 App 啟動新 process；CLI 的 `--resume` 在該次執行恢復 checkpoint。沒有相同 process 的重新建模或 Restart schema。

## Console Output

`Qtqdm` 進入 `with` 時，`ConsoleCapture` 暫時替換 `sys.stdout`／`sys.stderr`。`TeeStream.write()` 先寫原本的 stream，再複製到 `ConsoleOutput`，因此終端機原本輸出仍可看到。離開 `with` 或 `close()` 都恢復 stream。例外的 traceback 另寫入 console buffer，供失敗後的網頁查看。

`ConsoleOutput` 以 Lock 保護最近 65,536 個字元與更新版本；`/state` 帶出 console snapshot，前端只在版本變更時更新文字。`console_path` 可指定新 `.log` 檔案，逐次寫入與 flush，內容不受 buffer 裁切影響。寫 log 發生 OSError 時停止寫檔並回報原因，網頁與原始終端機輸出仍繼續。

同一個 process 同時只允許一個 console capture，其他 monitor 可設 `capture_console=False`。此功能捕捉 Python text stream，不攔截 subprocess／native code 的底層輸出，也不包含 `with` 前後的 print。瀏覽器是 plain text viewer：移除常見 ANSI CSI sequence，carriage return 顯示為換行，不模擬互動式 CMD。套件仍只依賴 Python 標準函式庫。

顯示同步以 3 秒內為驗收門檻，仍採用每次請求完成後等待 250 ms 的輪詢，不加入訓練等待網頁的同步機制。驗證若觀察到超過 3 秒，再確認是否需要更嚴格的同步控制。

## 保存與接續

訓練程式透過 `progress.register_controls(save_checkpoint=save_function)` 提供保存函式，函式回傳保存路徑。網頁只送出要求；`control.py` 在訓練執行緒的步驟邊界呼叫函式，確保保存時沒有同時更新模型。寫檔時不持有控制鎖，網頁仍能讀取狀態。保存失敗會顯示原因並允許重試，訓練可繼續。

2048 範例每次手動／預訂保存都建立新檔案，頁面顯示最近成功的路徑。同時只保留一個未來預訂，達到指定已完成步數時觸發一次，包含最後一步。取消只影響尚未觸發的預訂；提前結束會清除剩餘預訂。暫停中的手動保存不會讓訓練繼續。

2048 範例在正常完成或透過網頁提前停止後，由訓練端寫出 `.pt` 保存檔。內容包括模型權重、optimizer 設定及內部狀態、下一步編號、原目標步數，以及 CPU／目前 CUDA 裝置的隨機數狀態。先寫臨時檔再替換正式檔，避免把未寫完的內容當成成功保存。

載入時，範例先重建相同的模型、optimizer 與固定種子的示範資料，再恢復保存內容。新的 `Qtqdm` 物件用 `initial` 顯示原本已完成的步數；新 CSV 從後續項目編號開始，曲線只呈現本次接續執行的資料，原 CSV 與保存檔保留。

`control.py` 的 `checkpoint()` 是控制指令檢查點；`rl2048_checkpoint.py` 的保存檔是持久化訓練狀態。兩者責任不同。

## 其他檔案

- `../example.py`：不依賴 PyTorch 的進度與曲線範例。
- `../tests/`：進度／CSV、控制／HTTP、保存／恢復測試。
- `../runs/`：每次訓練產生的 CSV 與 `.pt`，不放進 Git。
- `../.venv/`：獨立 Python 與 GPU 套件環境。
- `../requirements-gpu.txt`：可重建的 PyTorch CUDA 套件版本（2048 demo 使用）。

## Complete history transport

`Progress.history_since(after, limit)` 在 history lock 內以 update index 切出最多 2,000 次 updates，回傳 `charts`、`next_update`、`has_more`。每個 metric 的 full list 不裁切；所有 metric updates 與 cursor 在同一個鎖內提交，避免 HTTP 讀取時漏掉剛新增的 point。

Standalone page 從 child `/history?after=...` 讀取。Board 的 TrainingBridge 每個 polling cycle 最多取得 4 pages，append 至自己的 cache，並由 Board `/training-history?job_id=...&after=...` 提供前端增量讀取。主 `/state` 只提供 bounded previews 與 `history_updates`。Child 結束後保留 Board 已收到的資料；job_id 改變才清空。前端只追加新增 points，refresh 時從 cursor 0 重建；舊 job 的延遲 response 不加入新 job。完整歷史的 RAM 使用量隨 run 長度成長，CSV 持續保存磁碟紀錄。

## tqdm compatibility and nested bars

`Progress` 有兩種模式：傳入 iterable 時由 `__iter__` 計數；`items=None` 時是 manual 模式，由 `update(n)` 計數並在每次 update 後呼叫 `control.checkpoint()`。Manual bar 由 `_finalize_manual()` 在 `__exit__`／`close()` 時結束一次。

`web.py` 的 `_active_bars` 記錄目前正在執行的 bars（開始執行時 `_on_start` 加入，結束時 `_deactivate` 移除）。新建立的 `Qtqdm` 若發現有正在執行的 bar，就成為它的子 bar：`root` 指向最外層、`depth` 加一，不開 server、不擷取 Console、不寫 run record。子 bar 的 `control` 換成 `_ChildControl`，它把 checkpoint 轉給最外層的 `TrainingControl`，所以 Pause／Stop／Save 會在內層邊界生效，而且子 bar 結束時不會把外層的控制標成 finished。最外層 `snapshot()` 的 `bars` 列出子 bar 的計數與速度，`training_view.js` 的 `renderBars` 畫在主進度條下方。

## Zero-code tqdm patch

`patch.py` 的 `install()` 在 script 匯入 tqdm 前，把 `tqdm`、`tqdm.auto`、`tqdm.autonotebook` 的 `tqdm`／`trange` 換成 `PatchedTqdm`（Qtqdm 子類，容忍 tqdm 的位置參數、未知 keyword 與純顯示方法）；未安裝 tqdm 時註冊簡易 stand-in modules。`__main__.py` 做完替換後以 `runpy.run_path` 執行 script。tqdmboard 勾選 `patch_tqdm` 時，`board_process.launch_command` 改用 `python -u -m qtqdm SCRIPT ARGS`，設定隨 run record 的 config JSON 保存。已知限制：第三方套件內的進度條也會成為 Qtqdm 進度條。
