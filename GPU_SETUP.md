# 本機 GPU 環境

專案的 `.venv` 是獨立 Python 環境，GPU 套件安裝在裡面。執行時直接指定它的 Python，不需要設定全域 PATH 或啟用 PowerShell 腳本。

已驗證環境：Python 3.12.14、PyTorch 2.14.0+cu130、torchvision 0.29.0+cu130、NVIDIA GeForce RTX 5060（8 GB）、驅動 616.92。GPU 範例執行 100 次權重更新，loss 從約 6.5469 降至 1.5e-13，完整 CSV 有 100 筆紀錄。

在本專案目錄開啟 PowerShell，執行：

```powershell
& '.\.venv\Scripts\python.exe' gpu_training_demo.py --keep-open
```

這個範例會在 NVIDIA GPU 上訓練一個小型線性模型，學習把八個輸入數字相加。輸入資料由程式產生；模型會實際執行預測、反向傳播與權重更新。HTML 顯示真實 loss，並提供暫停／繼續、提前停止及 learning rate 控制。完整紀錄存入 `runs` 目錄，包含每一步實際使用的 learning rate。每次執行使用新檔名，按 Enter 後關閉本機網頁伺服器。

為方便操作按鈕，展示預設執行 1,000 步，每步刻意等待 0.03 秒；這不是模型速度測量。可使用 `--steps 100 --step-delay 0` 執行快速驗證。

兩張曲線可各自選擇 X 軸（步數、秒數或更新次數）與 Y 指標（此範例提供 loss、learning_rate），也能指定兩軸的上下限。留空會自動縮放；`Reset Axes`回到步數／loss。設定只影響圖表顯示，重新整理頁面會恢復預設。

`Console Output` 同時顯示終端機中的 Python stdout／stderr。範例每 25 步輸出 loss 與 learning rate，也輸出 checkpoint 路徑和最終摘要。`Follow Tail` 自動跟隨最新輸出，取消勾選可閱讀先前內容；`Copy Output` 複製目前 buffer。網頁保留最近 65,536 個字元，完整輸出另存為 `runs` 中與 CSV 同名前綴的 `.log` 檔案。

### Restart

`Restart Hyperparameters` 可調整 learning_rate、momentum、weight_decay、target_steps，按 `Restart` 後套用到新的 run。模型與 optimizer 重新初始化，從 step 0 開始；舊 run 在 step boundary 結束，正常／受控停止時先保存 checkpoint，舊 CSV／log／checkpoint 都保留。網頁 URL 不變，曲線與 console 切換到新 run。Completed／Stopped／Failed 後也能 Restart，只要用 `--keep-open` 保持 session 開啟。

即時 `Learning rate` 的 `Apply` 修改目前 run；Restart 表單修改下一個 run。Restart 不會自動接續 checkpoint，`--resume` 僅用於第一個 run。各 run 使用固定 seed 42 與相同示範資料，可比較 hyperparameters 的效果。新的 CLI 選項也能設定首次 run：

```powershell
& '.\.venv\Scripts\python.exe' gpu_training_demo.py --keep-open --learning-rate 0.03 --momentum 0.6 --weight-decay 0.001 --steps 1000
```

正常完成或按網頁的`Stop`後，範例會自動把模型、optimizer、下一步編號和隨機數狀態存到與 CSV 同名的 `.pt` 檔案。終端機會印出 `Checkpoint:` 路徑。

網頁另提供`Save Checkpoint`，在下一個步驟邊界建立新的 `.pt`，並顯示完整路徑。暫停時也能保存。輸入未來的已完成步數並按`Schedule Checkpoint`，會在該步完成後保存一次；可取消或改成另一個步數。同時只保留一個預訂，提前停止後不再等待未來的預訂。這些保存檔同樣能用 `--resume` 接續。

要接續訓練，把下面的檔名换成剛才保存的檔案：

```powershell
& '.\.venv\Scripts\python.exe' gpu_training_demo.py --resume '.\runs\gpu_training_日期時間.pt' --keep-open
```

預設接續至原本的目標步數；`--steps` 指的是包含舊步數在內的總目標。例如已完成 40 步，`--steps 100` 會再訓練 60 步。若保存檔已達到原目標，可加 `--steps 2000` 繼續到更大的目標。

接續會使用新的網頁和新的 CSV／`.pt`，進度與項目編號從保存位置繼續。曲線顯示本次執行的資料；先前的曲線資料仍在舊 CSV。範例只恢復同一個線性模型與固定種子的示範資料。程式崩潰、強制關閉或訓練失敗不會自動保存新的檔案；這裡的保存時機是正常完成與受控停止。

只驗證 GPU 訓練、不開瀏覽器：

```powershell
& '.\.venv\Scripts\python.exe' gpu_training_demo.py --no-browser
```

更完整的保存／接續 GPU 測試：

```powershell
& '.\.venv\Scripts\python.exe' checkpoint_smoke.py
```

測試使用 17,092 個參數的分類模型，包含 BatchNorm、Dropout 和 AdamW，以隨機批次訓練 120 步。第 60 步保存並重建模型，再驗證接續結果與不中斷的訓練完全相同：逐步 loss、模型權重、BatchNorm 緩衝值及 AdamW 狀態都逐項比對。RTX 5060 實測通過，平均 loss 從 1.3197 降至 0.2259。資料由程式產生；此測試涵蓋單張 GPU 與固定精度，尚未涵蓋混合精度或外部資料載入器。

一般程式與 Qtqdm 測試也可使用同一個環境：

```powershell
& '.\.venv\Scripts\python.exe' example.py
& '.\.venv\Scripts\python.exe' -m unittest discover -s tests -v
```

這個環境使用 Codex 附帶的 Python 建立；若移動專案或移除原本的 Python，應重新建立虛擬環境。PyTorch CUDA 套件含預先編譯的 GPU 運算元件；此範例只需現有 NVIDIA 驅動。

已將套件版本記錄在 `requirements-gpu.txt`。重建環境後可執行下列指令安裝相同版本：

```powershell
& '.\.venv\Scripts\python.exe' -m pip install -r requirements-gpu.txt
```

套件來源：[PyTorch 官方 CUDA 安裝站](https://download.pytorch.org/whl/cu130)。
