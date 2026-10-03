# Qtqdm 架構

| 檔案 | 責任 |
| --- | --- |
| `index.html` | 顯示狀態與曲線，送出使用者指令 |
| `charts.js` | 圖表設定、座標轉換、刻度與曲線繪製 |
| `chart_history.py` | 每個數值指標的近期資料與總覽取樣 |
| `web.py` | 提供本機 HTTP 介面，驗證指令並交給控制層 |
| `control.py` | 使用 Condition 協調網頁執行緒與訓練執行緒 |
| `progress.py` | 計數、歷史取樣，每一步開始前檢查控制狀態 |
| `csv_log.py` | 保存完整指標更新 |
| `../gpu_training_demo.py` | 建立 PyTorch 模型、實際套用 learning rate、執行 GPU 訓練 |
| `../training_checkpoint.py` | 保存／載入模型、optimizer、下一步編號與隨機數狀態 |

`qtqdm/__init__.py` 是公開匯入入口，讓使用者寫 `from qtqdm import Qtqdm`。`Qtqdm` 繼承 `Progress`，再加上 HTTP 伺服器；`Progress` 分別持有控制模組和 CSV 紀錄器。監看套件本身不需要 PyTorch。

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

網頁執行緒只改控制狀態；optimizer 始終由訓練程式操作。HTTP 接受指令不代表訓練已經執行，因此 `/state` 分別提供暫停要求、已暫停、等待套用的 learning rate 與已生效值。

Condition 讓暫停的訓練等待通知，不需要持續輪詢。`resume`、`stop` 或工作結束都會通知等待者。結束後拒絕新的控制指令；停止後不能接續同一個迭代器。

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
