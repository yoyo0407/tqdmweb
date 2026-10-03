# Qtqdm（本機版）

用 Python 包裝一個迴圈，並在本機瀏覽器顯示即時進度。這個版本只用 Python 標準函式庫與原生 HTML／JavaScript，不需要發布套件或安裝網頁框架。

## 使用

在專案根目錄執行 `example.py`。一般程式可以這樣寫：

```python
from qtqdm import Qtqdm

progress = Qtqdm(range(100), description="Training")
try:
    with progress:
        for item in progress:
            do_work(item)
finally:
    progress.wait()  # 短腳本可用這行保留完成畫面；按 Enter 關閉伺服器
```

若資料來源沒有 `len()`，可傳入 `total=100`；若總數未知，頁面會顯示目前進行到第幾項與速度，不顯示百分比或預估剩餘時間。進度條以「已開始處理」計算；頁面另外列出「已完成」數量，因此處理第一項時會看到進度 `1 / N`、已完成 `0`。

訓練或其他長時間工作可呼叫 `progress.set_postfix(loss=0.42, accuracy=0.87)`。頁面會顯示這些名稱與最新數值；它們只是附加資訊，不影響進度計算。

要保留完整紀錄，建立物件時加上 `csv_path="training.csv"`：

```python
progress = Qtqdm(range(100), csv_path="training.csv")
try:
    with progress:
        for step in progress:
            loss = train_step(step)
            progress.set_postfix(loss=loss)
finally:
    progress.wait()
```

每次 `set_postfix()` 都會把傳入的指標寫入 CSV 並立即刷新檔案緩衝區。欄位是更新編號、經過秒數、目前項目編號、指標名稱及原始值；同一次更新的多個指標各佔一列，共用更新編號。新增指標不需要更改欄位。CSV 保留每次呼叫傳入的值，與網頁曲線取樣無關；正常完成、途中出錯或呼叫 `close()` 都會關閉檔案。它不會自動量測模型，請在需要紀錄時呼叫 `set_postfix()`。

紀錄預設關閉。指定的目錄必須存在，檔名必須是新檔案，避免蓋掉舊結果；UTF-8 編碼含 BOM，方便 Excel 顯示中文。範例中的 `train_step()` 請換成自己的訓練函式。

傳入數值指標後，頁面會畫出兩張曲線：涵蓋整段訓練的總覽，以及最近 300 次該指標更新的細節。每個指標的總覽資料接近 600 筆時，取每隔一筆的點並把後續取樣間隔加倍；第一筆與最新一筆會保留。因此能持續看到全程趨勢，每個指標的記憶體與網頁傳輸資料量都有上限。總覽是取樣結果，可能看不到取樣點之間的短暫尖峰。

### 自訂座標軸

兩張圖可各自設定，按`Apply Axes`生效：

- X 軸可選步數、經過秒數或更新次數，預設為步數。
- Y 軸可選 `set_postfix()` 傳入的數值指標，例如 loss、accuracy、learning_rate；文字與非有限數值不列入選項。
- X／Y 下限與上限可分別指定，留空則自動縮放。兩者都有填寫時，下限必須小於上限。
- 切換 X 軸或 Y 指標會清除該軸的範圍；`Reset Axes`清除所有範圍並選步數／loss。重新整理頁面也會恢復預設。

步數是記錄指標時正在處理的項目編號，接續訓練時沿用原步數。更新次數則是本次工作呼叫 `set_postfix()` 的次數，同一步可有多次更新。圖表範圍只影響顯示，CSV 和已保留的歷史資料不變。自訂 X 範圍時，Y 自動縮放會參考該範圍內的取樣點。

## 程式結構

- `progress.py`：記錄完成數量、耗時與速度，不依賴網頁。
- `csv_log.py`：逐次寫入完整指標紀錄。
- `chart_history.py`：保留每個數值指標的曲線與總覽取樣。
- `charts.js`：獨立管理兩張圖的座標軸設定與繪圖。
- `console.py`／`console.js`：鏡像 Python stdout／stderr 與顯示 Console Output。
- `control.py`：接收暫停、繼續、停止、learning rate 與保存要求，在迴圈邊界協調執行。
- `web.py`：在 `127.0.0.1` 啟動本機 HTTP 伺服器，提供頁面與 `/state` JSON。
- `index.html`：每 250 毫秒讀取 `/state` 並更新畫面。

`with` 可以偵測迴圈內的例外，把狀態改為失敗，並讓頁面彈出錯誤提醒。例外仍會傳回原程式；`finally` 裡的 `wait()` 讓短腳本在失敗時也保留頁面，直到使用者按 Enter。

關閉瀏覽器分頁不會中斷 Python 工作。終端機會印出本機頁面網址，之後可用同一網址重新開啟；程式中也可呼叫 `progress.show()` 重新開頁面。

## 網頁控制

暫停／繼續與提前停止由 `Qtqdm` 的迭代器處理。按暫停後，當前迴圈內容完成才會暫停，畫面會先顯示等待，再顯示已暫停；停止同樣在這個邊界生效，並會喚醒已暫停的迴圈。停止會結束本次迴圈，不能用繼續按鈕重新啟動。已寫入的 CSV 會保留。

GPU 示範的訓練端另有 `training_checkpoint.py`，會在正常完成或受控停止後保存模型與 optimizer，並可使用 `--resume` 在新的工作中接續。這項保存由訓練程式負責；使用 Qtqdm 監看的其他程式也需要自行接入保存邏輯。

要啟用網頁保存，訓練端在迴圈前登記自己的函式：

```python
def save_model():
    # 使用自己的保存邏輯，然後回傳檔案路徑
    return write_training_checkpoint()

progress.control.enable_saving(save_model)
```

`write_training_checkpoint()` 是示意名稱，實際完整範例見 `gpu_training_demo.py`。保存函式在訓練執行緒執行，會暫時等待寫檔完成後才繼續下一步；網頁仍可操作。未登記保存函式時，頁面隱藏保存控制。

- `Save Checkpoint`：在下一個步驟邊界保存；已暫停時直接保存並維持暫停。
- `Schedule Checkpoint`：輸入絕對步數，例如 200 表示完成第 200 步後保存一次；新預訂會取代舊預訂。
- `Cancel Schedule`：取消尚未觸發的預訂，不能撤回已開始寫入的保存。

頁面顯示等待、寫入中、成功路徑或失敗原因。保存失敗後可重試；已完成、停止或失敗的工作不能再送出保存要求。GPU 範例每次手動與預訂保存使用新檔名，保留舊檔案。

接續時可以寫 `Qtqdm(remaining_items, total=100, initial=40)`，讓新頁面從 `40 / 100` 開始，CSV 的項目編號也會從 41 接著記錄。

learning rate 必須由自己的訓練程式接入。先回報目前值，網頁才會顯示這項控制；每一步開始時取出要求，交給 optimizer 套用，最後回報生效值：

```python
progress.control.report_learning_rate(optimizer.param_groups[0]["lr"])
with progress:
    for batch in progress:
        new_rate = progress.control.take_learning_rate()
        if new_rate is not None:
            for group in optimizer.param_groups:
                group["lr"] = new_rate
            progress.control.report_learning_rate(new_rate)
        # 接著執行自己的訓練步驟
```

暫停期間送出的 learning rate 會保持等待，繼續後由訓練端套用；多次要求以最後一次為準。完成、停止或失敗後，控制按鈕會停用。耗時與平均速度以實際經過的時間計算，包含暫停時間。

目前每個 `Qtqdm` 物件各有一個頁面，每個物件只能執行一次迴圈；下一次工作請建立新物件。程式結束或呼叫 `close()` 後，頁面無法繼續更新。第一版尚未處理多進度條整合。

## Console Output

`with progress:` 內的 Python `print()`、寫入 `sys.stdout`／`sys.stderr` 的內容會同時出現在原本終端機與網頁。離開 `with` 會恢復原始 stream；如果發生例外，網頁也保留 traceback。

```python
progress = Qtqdm(range(100), console_path="training.log")
try:
    with progress:
        print("Training started")
        for step in progress:
            print(f"Step {step + 1}")
finally:
    progress.wait()
```

`Follow Tail` 預設開啟，會自動捲動到最新輸出；關閉後可停在舊內容閱讀。`Copy Output` 複製目前可見的 buffer。網頁保留最近 65,536 個字元，超過時顯示提示；指定 `console_path` 可保存完整原始輸出，檔名必須是新檔案。GPU 範例自動建立 `.log`，與 CSV／checkpoint 使用相同時間前綴。

Console Output 是 plain text viewer，捕捉 `with` 期間的 Python text stream；不包含外部程式或 native code 直接寫入終端機的內容，也不提供 CMD 指令執行。常見 ANSI 顏色控制碼會移除，carriage return 轉成換行。既有 logging handler 若已綁定舊 stream，不會自動改綁；可在 `with` 內建立 handler，或直接呼叫 `progress.console.write(text)`。

同一個 process 僅允許一個啟用 capture 的 monitor。若有其他 monitor，請設 `capture_console=False`。顯示更新以 3 秒內為同步標準，正常連線時仍每 250 ms 輪詢；網頁關閉或斷線不會阻止訓練。

## 測試

在專案根目錄執行 `python -m unittest discover -s tests -v`。
