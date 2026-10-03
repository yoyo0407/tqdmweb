# Qtqdm（本機版）

用 Python 包裝一個迴圈，並在本機瀏覽器顯示即時進度。這個版本只用 Python 標準函式庫與原生 HTML／JavaScript，不需要發布套件或安裝網頁框架。

要從同一個 App 選擇不同 Python scripts，請在專案目錄執行 `tqdmboard.cmd`。App 提供 Windows 原生選檔視窗、Basic／Advanced 分組、environment／arguments selection、Process Console 與由 App 自行呈現的 Training Dashboard；training process 結束後 App 仍運作。詳見 `../TQDMBOARD.md`。

## 使用

最短接入方式：

```python
from qtqdm import Qtqdm

with Qtqdm(range(100), desc="Training") as progress:
    for step in progress:
        loss = train_step(step)
        progress.set_postfix(loss=loss)
```

`train_step` 是自己的訓練函式。也可以用 `from qtqdm import tqdm`，接著寫 `with tqdm(...) as progress:`，保留熟悉的名稱。`desc` 與 `description` 都可用，但不要同時指定。`set_postfix({"loss": loss}, accuracy=accuracy)` 支援 mapping 加 keyword arguments；`refresh` 參數僅供呼叫相容，不改變網頁輪詢。沒有承諾完整 tqdm 相容，但常見寫法都能直接執行，見下方「tqdm 相容寫法」。

### tqdm 相容寫法

手動更新：不傳 iterable，改傳 `total`，每完成一批呼叫 `update(n)`。暫停在 `update()` 內生效；按 Stop 後 `progress.stopped` 變成 True，迴圈要自己 `break`。

```python
with tqdm(total=len(dataset), unit="sample") as progress:
    for batch in loader:
        train_step(batch)
        progress.update(len(batch))
        if progress.stopped:
            break
```

離開 `with` 或呼叫 `close()` 時結束：達到 `total`（或沒有 `total`）記為 finished，否則記為 stopped。

`trange(10)` 等於 `Qtqdm(range(10))`。`set_description()`、`n`、`unit`、`leave`、`disable`、`postfix` 可用；`ncols`、`position`、`mininterval`、`bar_format` 等終端機顯示參數會被接受但忽略，其他不認得的參數會報 TypeError。`disable=True` 不開網頁、不擷取 Console，只照常迭代。

巢狀進度條：外層迴圈執行中建立的 bar 會變成子 bar，顯示在外層頁面的主進度條下方，不另開 server。

```python
for epoch in trange(10, desc="Epoch"):
    for batch in tqdm(loader, desc="Batch", leave=False):
        loss = train_step(batch)
        ...
```

- Pause／Stop／Save 由最外層 bar 負責，但在內層每一步邊界就會生效，不必等整個 epoch。Stop 後內層迴圈先結束，外層在下一步結束。
- 內層呼叫 `set_postfix()` 會記到外層的 metrics 與曲線。同一個 epoch 內的點共用同一個 Step，建議把 X 軸切成 Update Index 或 Elapsed。
- `register_controls()` 只能在最外層呼叫。
- 新的內層 bar 開始時，會取代同一層已結束的 bar；`leave=False` 的 bar 結束時直接移除。
- 判斷父子關係只看「目前正在執行的 bar」：已建立但還沒開始跑的 bar 不會收編之後的 bar；外層結束後再建立的 bar 會是新的獨立頁面。

離開 `with` 會結束 Console capture 與這次控制；server 可保留完成或錯誤狀態。短腳本若要保留頁面直到使用者關閉，可使用下面的 `wait()` 範例。

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

傳入數值指標後，頁面會畫出兩張曲線：Basic 的 Training History 是整段訓練的取樣總覽；Advanced 的 Full Metric History 完整保留每筆數值更新，不使用 rolling window。新 update 不會刪掉前面的 points，重新整理會從 server 重新讀回歷史。總覽接近 600 個 samples 時降低取樣密度，第一筆與最新一筆仍保留；它不是完整曲線。

完整資料保存在 training process 記憶體，透過 `GET /history?after=UPDATE_INDEX` 每頁最多 2,000 次 updates 增量讀取，不在每次 `/state` 重送全部歷史。Board 另保留已收到的完整資料，process 結束後仍可刷新查看；新 process 會清空前一個 job 的畫面。完整歷史的 RAM 使用量會隨更新數增加，CSV 仍是磁碟上的完整紀錄。

### 事件標註

曲線會自動標註實際生效的 Pause／Resume／Stop、Learning Rate 調整，以及 Checkpoint 保存成功或失敗。不同操作以不同顏色的虛線顯示，密集事件只畫線以避免文字重疊；圖表下方列出目前 X 範圍內的事件數。History 回看也保留這些標註。

可在訓練程式中加入自己的事件：

```python
progress.mark("phase 2")
```

文字去除首尾空白後須為 1 至 100 個字元。事件記錄當下的經過時間、Step 與 Update Index，隨圖表 X 軸切換；子進度條的 `mark()` 記到最外層。事件只影響顯示，不修改訓練、metrics 或 CSV。

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
- `web.py`：Qtqdm 入口，接合 progress、console 與 dashboard。
- `dashboard.py`：在 `127.0.0.1` 啟動 HTTP server，提供頁面與 `/state` JSON。
- `index.html`：每 250 毫秒讀取 `/state` 並更新畫面。

`with` 可以偵測迴圈內的例外，把狀態改為失敗，並讓頁面彈出錯誤提醒。例外仍會傳回原程式；`finally` 裡的 `wait()` 讓短腳本在失敗時也保留頁面，直到使用者按 Enter。

關閉瀏覽器分頁不會中斷 Python 工作。終端機會印出本機頁面網址，之後可用同一網址重新開啟；程式中也可呼叫 `progress.show()` 重新開頁面。

## 網頁控制

暫停／繼續與提前停止由 `Qtqdm` 的迭代器處理。按暫停後，當前迴圈內容完成才會暫停，畫面會先顯示等待，再顯示已暫停；停止同樣在這個邊界生效，並會喚醒已暫停的迴圈。停止會結束本次迴圈，不能用繼續按鈕重新啟動。已寫入的 CSV 會保留。

2048 示範的訓練端另有 `rl2048_checkpoint.py`，會在正常完成或受控停止後保存模型與 optimizer，並可使用 `--resume` 在新的工作中接續。這項保存由訓練程式負責；使用 Qtqdm 監看的其他程式也需要自行接入保存邏輯。

要啟用網頁保存，訓練端在迴圈前登記自己的函式：

```python
def save_model():
    # 使用自己的保存邏輯，然後回傳檔案路徑
    return write_training_checkpoint()

progress.register_controls(save_checkpoint=save_model)
```

`write_training_checkpoint()` 是示意名稱，實際完整範例見 `rl2048_demo.py`。保存函式在訓練執行緒執行，會暫時等待寫檔完成後才繼續下一步；網頁仍可操作。未登記保存函式時，頁面隱藏保存控制。

- `Save Checkpoint`：在下一個步驟邊界保存；已暫停時直接保存並維持暫停。
- `Schedule Checkpoint`：輸入絕對步數，例如 200 表示完成第 200 步後保存一次；新預訂會取代舊預訂。
- `Cancel Schedule`：取消尚未觸發的預訂，不能撤回已開始寫入的保存。

頁面顯示等待、寫入中、成功路徑或失敗原因。保存失敗後可重試；已完成、停止或失敗的工作不能再送出保存要求。2048 範例每次手動與預訂保存使用新檔名，保留舊檔案。

接續時可以寫 `Qtqdm(remaining_items, total=100, initial=40)`，讓新頁面從 `40 / 100` 開始，CSV 的項目編號也會從 41 接著記錄。

## 統一控制接口

建議在迴圈開始前集中註冊 script 的控制 handlers：

```python
def save_now():
    # 保存自己的 model、optimizer、step 等狀態，回傳實際路徑。
    return write_training_checkpoint()

def set_learning_rate(value):
    for group in optimizer.param_groups:
        group["lr"] = value

progress.register_controls(
    save_checkpoint=save_now,
    set_learning_rate=set_learning_rate,
    learning_rate=optimizer.param_groups[0]["lr"],
)

with progress:
    for step in progress:
        loss = train_step(step)
        progress.set_postfix(loss=loss)
```

`write_training_checkpoint` 與 `train_step` 是示意名稱；可執行的完整範例是 `../rl2048_demo.py`。只需要儲存時可以只註冊 `save_checkpoint`；註冊 learning-rate handler 時必須提供目前 `learning_rate`。註冊資料先驗證，再啟用控制；開始迴圈後不能透過 `register_controls` 更換 handlers。

Qtqdm 自動在 step boundary 呼叫 handler，並回報成功／失敗。已暫停時也能保存與調整 learning rate，保持暫停；stop 已接受後不再執行尚未套用的 learning rate。Handler 在 training thread 執行且不持有控制鎖；慢 handler 會延後下一步，但不鎖住 HTTP server。失敗會顯示原因、保留上次成功回報的值並允許重試；handler 自行造成的部分修改不會自動回滾。

網頁列出 capabilities；未註冊的 Save／Learning Rate controls 不顯示，摘要標示 unavailable。Pause／Stop 是內建功能。每個 Qtqdm 只監控一次 run。Capabilities 表示 script 支援的功能，run 結束後按鈕仍會停用。Model、optimizer 與 checkpoint 內容仍由 script 決定，Qtqdm 不會自動猜測。

控制接入統一使用 `register_controls`。如果自己的舊 script 使用 `enable_saving`、`report_learning_rate` 或 `take_learning_rate`，請改成上述 handler 寫法；這三個舊接口已移除。尚未開始處理的多次 learning-rate 要求以最後一次為準。完成、停止或失敗後，控制按鈕會停用。耗時與平均速度以實際經過的時間計算，包含暫停時間。

目前每個 `Qtqdm` 物件各有一個頁面，每個物件只能執行一次迴圈；下一次工作請建立新物件。程式結束或呼叫 `close()` 後，頁面無法繼續更新。第一版尚未處理多進度條整合。

## Console Output

`with progress:` 內的 Python `print()`、寫入 `sys.stdout`／`sys.stderr` 的內容會同時出現在原本終端機與網頁。離開 `with` 會恢復原始 stream；如果發生例外，網頁也保留 traceback。

tqdmboard 的 Process Console 顯示完整 child stdout／stderr；Board 不嵌入 Qtqdm 頁面。Qtqdm 的獨立頁面始終顯示自己的 Console Output，Python capture 與 log 保存照常執行。

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

`Follow Tail` 預設開啟，會自動捲動到最新輸出；關閉後可停在舊內容閱讀。`Copy Output` 複製目前可見的 buffer。網頁保留最近 65,536 個字元，超過時顯示提示；指定 `console_path` 可保存完整原始輸出，檔名必須是新檔案。2048 範例自動建立 `.log`，與 CSV／checkpoint 使用相同時間前綴。

Console Output 是 plain text viewer，捕捉 `with` 期間的 Python text stream；不包含外部程式或 native code 直接寫入終端機的內容，也不提供 CMD 指令執行。常見 ANSI 顏色控制碼會移除，carriage return 轉成換行。既有 logging handler 若已綁定舊 stream，不會自動改綁；可在 `with` 內建立 handler，或直接呼叫 `progress.console.write(text)`。

同一個 process 僅允許一個啟用 capture 的 monitor。若有其他 monitor，請設 `capture_console=False`。顯示更新以 3 秒內為同步標準，正常連線時仍每 250 ms 輪詢；網頁關閉或斷線不會阻止訓練。

## 單次執行與介面分組

每個 Qtqdm instance 僅監控一次 run；完成、停止或失敗後，controls 停用。已移除多次 run 的 session、Training Restart、Restart Hyperparameters 與相同 URL 重建 model 的流程。

Qtqdm 獨立頁面直接顯示 Progress、Metrics、Pause／Stop、Save Checkpoint、Console、Training History、Learning Rate、Schedule／Cancel Checkpoint、Full Metric History、capabilities 與 Axis Settings，不分 Basic／Advanced。只有外部 tqdmboard 使用 Basic／Advanced layout。

2048 範例的初始 learning rate 與 target steps 等透過啟動 arguments 設定。即時 Learning Rate 控制仍使用註冊 handler。`--keep-open` 只保留完成／停止／失敗的頁面供閱讀，Enter 關閉；在 tqdmboard 內也會保留，直到 Stop Process 或 Restart Process 通知結束。

重新執行由 tqdmboard 的 Restart Process 處理：結束舊 process、啟動新 process。新 Qtqdm 使用新的 URL、CSV／log／checkpoint，舊檔保留。原本使用多次 run session 的 scripts 需改成直接建立 Qtqdm；可執行範例見 `../rl2048_demo.py`。

## 不改程式碼接入（python -m qtqdm）

已使用 `from tqdm import tqdm`、`from tqdm.auto import tqdm` 或 `trange` 的 script，不需修改即可顯示在 Qtqdm 頁面：

```
python -m qtqdm train.py --epochs 3
```

啟動時會印出 `qtqdm: patched tqdm (...) for train.py`，之後以 `runpy` 執行 script（`sys.argv` 與 `sys.path[0]` 與直接執行相同）。

被替換的項目：已安裝的 tqdm 的 `tqdm.tqdm`、`tqdm.trange`、`tqdm.auto.*`、`tqdm.autonotebook.*`；未安裝 tqdm 時改為註冊同名的簡易 `tqdm`、`tqdm.auto` 模組。替換的是 `qtqdm.patch.PatchedTqdm`（Qtqdm 的子類）：依 tqdm 的位置順序 `(iterable, desc, total, ...)` 接收參數，Qtqdm 不支援的 keyword 會忽略並在 stderr 警告一次；`refresh`、`clear`、`display`、`unpause` 不做事，`set_postfix_str` 存成 metric `postfix`，`tqdm.write` 等同 `print`。不提供 `reset()`，因為一個 Qtqdm 只監控一次 run。`tqdm.std`、`tqdm.notebook` 等其他模組不會被替換。

限制：第三方套件內建的進度條（例如下載進度）也會變成 Qtqdm 進度條。在執行中的外層進度條內建立時成為 nested bar，否則各自開獨立頁面。tqdmboard 的 Run tab 勾選 `Patch tqdm (no code changes)` 即以此方式啟動。

## 測試

在專案根目錄執行 `python -m unittest discover -s tests -v`。
