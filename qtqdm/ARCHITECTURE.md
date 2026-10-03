# Qtqdm 架構

| 檔案 | 責任 |
| --- | --- |
| `index.html` | 顯示狀態與曲線，送出使用者指令 |
| `charts.js` | 圖表設定、座標轉換、刻度與曲線繪製 |
| `chart_history.py` | 每個數值指標的近期資料與總覽取樣 |
| `console.py` | 鏡像 Python stdout／stderr、保存完整 log、限制網頁輸出長度 |
| `console.js` | 更新 Console Output、Follow Tail 與 Copy Output |
| `web.py` | Qtqdm 入口，接合 progress、console capture 與 dashboard |
| `dashboard.py` | 本機 HTTP server，驗證請求後呼叫 state／control callback |
| `session.py` | 跨 run 的 lifecycle，排程 Restart 並維持同一個 URL |
| `restart.js` | Restart Hyperparameters 表單與狀態 |
| `board.py` | tqdmboard App HTTP server，不隨 training process 結束 |
| `board.html`／`board.js` | Local File Browser 與 launcher UI，嵌入 training dashboard |
| `board_files.py` | Folder listing、Python environment discovery、arguments／paths 驗證 |
| `board_process.py` | 啟動、停止、重啟 subprocess，收集原始 stdout／stderr |
| `control.py` | 使用 Condition 協調網頁執行緒與訓練執行緒 |
| `progress.py` | 計數、歷史取樣，每一步開始前檢查控制狀態 |
| `csv_log.py` | 保存完整指標更新 |
| `../gpu_training_demo.py` | 建立 PyTorch 模型、實際套用 learning rate、執行 GPU 訓練 |
| `../training_checkpoint.py` | 保存／載入模型、optimizer、下一步編號與隨機數狀態 |
| `../training_config.py` | GPU 範例的 hyperparameter 驗證，不依賴 PyTorch |

`qtqdm/__init__.py` 是公開匯入入口，讓使用者寫 `from qtqdm import Qtqdm`。`Qtqdm` 繼承 `Progress`，再加上 HTTP 伺服器；`Progress` 分別持有控制模組和 CSV 紀錄器。監看套件本身不需要 PyTorch。

## tqdmboard App

`../tqdmboard.cmd` 呼叫專案 `.venv` 的 Python 執行 `../tqdmboard.py`，進入 `board.py`。App HTTP server 與 Python training subprocess 分開；App 本身只依賴標準函式庫。`board_process.py` 以 shell=False 與獨立 argument list 啟動所選 script，保留 stdin pipe，收集合併的 stdout／stderr。每個 process 建立新 log，網頁只保留 bounded console buffer。

ProcessRunner 發現 `Qtqdm page: http://127.0.0.1:PORT/` 後，App 在 iframe 顯示原 training dashboard，保留既有 controls 與 hyperparameter form。App 透過 `TQDMBOARD=1` 告知 Qtqdm／TrainingSession 不另開分頁，並讓 TrainingSession 在工作完成後繼續等待 Restart。外部 folder 的 scripts 透過 PYTHONPATH 找到 Qtqdm，不需手動修改既有 compliant scripts。

`Restart Process` 會要求舊 process graceful stop，等待 exit 後才啟動新的 process；`Restart` training action 則由 child TrainingSession 處理。兩者分開，model／optimizer 仍只存在 training process 中。App server 在 child exit 後仍可選擇其他 script。完整使用方式與框架見 `../TQDMBOARD.md`。

## 執行位置

Python 主執行緒負責訓練，背景 `ThreadingHTTPServer` 負責網頁請求。瀏覽器是另一個程式，每次讀取狀態或送出指令都透過 HTTP。訓練暫停時，背景伺服器仍能回應，所以繼續和停止按鈕仍然可用。

資料顯示：訓練呼叫 `set_postfix()` → 更新狀態與 CSV → 網頁讀取 `GET /state`。

`/state` 的 `charts` 依指標名稱提供 `recent` 與 `overview`。每個點是 `[經過秒數, 數值, 項目步數, set_postfix 更新編號]`，步數以當前已開始處理的項目計算，接續工作會保留原步數。文字、布林值及非有限數值不加入曲線，但仍保留在最新指標與 CSV。原本的 `loss_recent`／`loss_overview` 仍回傳 `[經過秒數, loss]`，保留讀取相容性。

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
| `learning_rate` | 大於零的有限數值 | 訓練端取出並套用，之後回報已生效值 |
| `save` | 不需要 | 在下一個步驟邊界保存，暫停時也能保存 |
| `schedule_save` | 尚未完成且不超過總目標的整數步數 | 完成指定步數後保存一次；新預訂取代舊預訂 |
| `cancel_save` | 不需要 | 取消尚未觸發的預訂 |
| `restart` | hyperparameter JSON object | 由 TrainingSession 接收，結束舊 run 後執行新 run |

網頁執行緒只改控制狀態；optimizer 始終由訓練程式操作。HTTP 接受指令不代表訓練已經執行，因此 `/state` 分別提供暫停要求、已暫停、等待套用的 learning rate 與已生效值。

Condition 讓暫停的訓練等待通知，不需要持續輪詢。`resume`、`stop` 或工作結束都會通知等待者。結束後拒絕新的控制指令；停止後不能接續同一個迭代器。

## Restart lifecycle

`TrainingSession` 持有共用 Dashboard 與目前的 Qtqdm。Restart 先驗證 hyperparameters，再記錄一個 pending request 並要求目前 run 停止；已在排程或初始化時拒絕重複 Restart。訓練 callback 返回後，session 在同一個訓練執行緒呼叫 callback 建立新模型、optimizer 與 Qtqdm，不重用舊 iterator。

GPU callback 在正常完成或受控停止時寫 checkpoint，Restart 因此先保留舊 run 的 checkpoint／CSV／log。Failed run 保留已寫入檔案與 traceback，但不保證有新的 checkpoint。新 run 使用新檔名並從 step 0 開始；舊 checkpoint 不會自動載入。CLI 的 `--resume` 只用在第一個 run attempt。

`/state` 的 `run_id` 在新 Qtqdm 發布時增加，`restart` 包含 enabled／pending／parameters。前端在 run_id 改變後更新表單初值、重設 console version、error alert 與 LR input。新 Qtqdm 的步數、指標歷史、pause／stop／save 狀態都是獨立資料；dashboard URL 不變。

GPU 範例目前提供四個 Restart Hyperparameters：learning_rate > 0、momentum ∈ [0, 1)、weight_decay ≥ 0、target_steps 為正整數。驗證在伺服器端執行。即時 learning rate 控制仍只修改目前 optimizer；Restart 表單的值僅在下一個 run 生效。每個 run 的模型由固定 seed 42 重建，方便比較不同參數。

`--keep-open` 讓 session 在 Completed／Stopped／Failed 後等待下一個 Restart；Enter 會通知 session 停止並關閉 dashboard。沒有指定時，最後一個 run 返回且沒有待執行 Restart 就退出。

## Console Output

`Qtqdm` 進入 `with` 時，`ConsoleCapture` 暫時替換 `sys.stdout`／`sys.stderr`。`TeeStream.write()` 先寫原本的 stream，再複製到 `ConsoleOutput`，因此終端機原本輸出仍可看到。離開 `with` 或 `close()` 都恢復 stream。例外的 traceback 另寫入 console buffer，供失敗後的網頁查看。

`ConsoleOutput` 以 Lock 保護最近 65,536 個字元與更新版本；`/state` 帶出 console snapshot，前端只在版本變更時更新文字。`console_path` 可指定新 `.log` 檔案，逐次寫入與 flush，內容不受 buffer 裁切影響。寫 log 發生 OSError 時停止寫檔並回報原因，網頁與原始終端機輸出仍繼續。

同一個 process 同時只允許一個 console capture，其他 monitor 可設 `capture_console=False`。此功能捕捉 Python text stream，不攔截 subprocess／native code 的底層輸出，也不包含 `with` 前後的 print。瀏覽器是 plain text viewer：移除常見 ANSI CSI sequence，carriage return 顯示為換行，不模擬互動式 CMD。套件仍只依賴 Python 標準函式庫。

顯示同步以 3 秒內為驗收門檻，仍採用每次請求完成後等待 250 ms 的輪詢，不加入訓練等待網頁的同步機制。驗證若觀察到超過 3 秒，再確認是否需要更嚴格的同步控制。

## 保存與接續

訓練程式透過 `progress.control.enable_saving(save_function)` 提供保存函式，函式回傳保存路徑。網頁只送出要求；`control.py` 在訓練執行緒的步驟邊界呼叫函式，確保保存時沒有同時更新模型。寫檔時不持有控制鎖，網頁仍能讀取狀態。保存失敗會顯示原因並允許重試，訓練可繼續。

GPU 範例每次手動／預訂保存都建立新檔案，頁面顯示最近成功的路徑。同時只保留一個未來預訂，達到指定已完成步數時觸發一次，包含最後一步。取消只影響尚未觸發的預訂；提前結束會清除剩餘預訂。暫停中的手動保存不會讓訓練繼續。

GPU 範例在正常完成或透過網頁提前停止後，由訓練端寫出 `.pt` 保存檔。內容包括模型權重、optimizer 設定及內部狀態、下一步編號、原目標步數，以及 CPU／目前 CUDA 裝置的隨機數狀態。先寫臨時檔再替換正式檔，避免把未寫完的內容當成成功保存。

載入時，範例先重建相同的模型、optimizer 與固定種子的示範資料，再恢復保存內容。新的 `Qtqdm` 物件用 `initial` 顯示原本已完成的步數；新 CSV 從後續項目編號開始，曲線只呈現本次接續執行的資料，原 CSV 與保存檔保留。

`control.py` 的 `checkpoint()` 是控制指令檢查點；`training_checkpoint.py` 的保存檔是持久化訓練狀態。兩者責任不同。

## 其他檔案

- `../example.py`：不依賴 PyTorch 的進度與曲線範例。
- `../tests/`：進度／CSV、控制／HTTP、保存／恢復測試。
- `../checkpoint_smoke.py`：GPU 上驗證含 Dropout、BatchNorm 與 AdamW 的模型能精確接續。
- `../runs/`：每次訓練產生的 CSV 與 `.pt`，不放進 Git。
- `../.venv/`：獨立 Python 與 GPU 套件環境。
- `../requirements-gpu.txt`：可重建的 GPU 套件版本。
- `../GPU_SETUP.md`：RTX 5060 的執行指令。
