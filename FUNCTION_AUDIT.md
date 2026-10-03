# 功能精簡審核

審核日期：2026-10-03。範圍：Qtqdm、tqdmboard、training 範例、對應測試與使用文件。

判斷依據為實際呼叫位置、使用者已要求的行為、資料是否重複，以及維護成本。程式內沒有呼叫不一定代表公開 API 沒用途；例如 `show()` 是供使用者重新開啟頁面的接口。

## 已精簡

| 項目 | 審核證據 | 修改 |
| --- | --- | --- |
| 舊的手動控制接口 | `enable_saving`、`take_learning_rate`、`report_learning_rate` 在產品範例中已沒有呼叫，只有測試和舊文件使用 | 移除這三個方法，控制統一使用 `register_controls`；同步遷移測試與文件 |
| Loss 專用回傳格式 | 前端圖表只讀 `charts`，但後端另回傳內容重複的 `loss_recent`／`loss_overview` | 移除專用欄位，統一讀 `charts.loss.recent`／`overview` |
| 保存啟用欄位 | `saving_enabled` 與 `capabilities.save_checkpoint` 使用相同判斷 | 刪除前者，前端和測試共用 capabilities |
| App 內的兩個 Console | Process Console 已顯示完整 child stdout／stderr，iframe 又顯示 Python capture | 嵌入時隱藏 Dashboard Console 並停止更新它；獨立頁面仍提供 Console，capture 與 log 保存照常執行 |

以 1,000 次 loss 更新的獨立 Progress snapshot 作示例，移除重複 loss 欄位後，JSON 大小約從 55.6 KB 降至 32.1 KB，減少約 42%。實際差異取決於 history、metrics 與 Console 的大小。

## 已審核並保留

| 功能 | 用途與保留理由 |
| --- | --- |
| Run、script／environment／arguments／working directory | 決定執行什麼程式、使用哪個 Python，以及相對路徑的基準 |
| File Browser、Parent Directory、environment discovery | 在網頁選擇本機 scripts；environment 按鈕可恢復偵測到的選項 |
| Restart Process | 重新載入修改後的 script 或啟動 arguments |
| Training Restart 與 Hyperparameters | 在同一個 training process 重建 model／optimizer，保留 dashboard URL |
| Training Stop 與 Stop Process | 前者结束本次 run 並保留 session；後者關閉 child process，釋放 launcher |
| Pause／Resume | 在 step boundary 暫停與繼續同一個 run |
| Force Stop | 處理沒有完成 graceful stop 的 process，確保 Windows venv child interpreter 一併結束 |
| Save、Schedule、Cancel Schedule | 立即請求保存、在指定完成步數保存，以及取消未觸發預訂 |
| Checkpoint resume、step、optimizer、RNG state | 保存後可準確接續訓練；model weights 本身不足以還原這些狀態 |
| Initial／total／started／completed | 接續進度、未知總數，以及區分正在處理與已完成項目 |
| Latest Metrics、Recent History、Training History | 分別查看當前值、近期細節與整段趨勢；兩種 history 都限制記憶體 |
| X／Y Axis、bounds、Reset Axes | 使用者已要求自訂座標軸；Reset 可恢復可讀範圍 |
| CSV 與完整 Console log | CSV 保存數值指標；Console log 保存診斷輸出，兩者內容不同 |
| Follow Tail、Copy Output | 閱讀舊輸出與複製診斷資訊 |
| System Resources | 不修改 script 就能觀察 CPU／RAM／GPU，與 loss／metrics 提供不同資訊 |
| Capabilities 與錯誤提示 | 告知 script 支援的控制，以及 handler 執行失敗的原因 |
| `wait()`、`show()`、Open Dashboard | standalone script 的頁面保留、重新開啟與完整頁面閱讀 |
| `desc`、`tqdm` alias、mapping postfix | 接近既有 tqdm 的基本用法；實作成本很小 |
| `refresh` compatibility argument | 目前不改變輪詢，文件已說明；保留可避免既有 postfix 呼叫中的它被誤當成 metric。沒有擴充完整 tqdm 相容層 |
| Quit App、Ctrl+C、`--no-browser`、directory／port options | 明確的 App lifecycle 與不同本機啟動方式 |
| Slow handler／timeout／bounded buffers 的保護 | 避免訓練控制鎖、GPU query、長時間輸出影響 App 回應或記憶體 |
| 測試與 GPU smoke 範例 | 驗證 thread boundary、錯誤恢復、process cleanup、checkpoint 精確接續；屬維護工具 |

## 使用影響

目前 `gpu_training_demo.py` 與 `example.py` 可以直接執行。外部舊 script 若使用三個已移除的控制方法，需要依 `qtqdm/README.md` 改用 `register_controls`。外部 state reader 若讀取已移除的 loss／saving 欄位，需要改用統一格式。這次沒有修改保存檔格式。

確認同時保存與調參時，learning-rate handler 先執行，再保存 checkpoint；停用手動輪詢模式後，也保留對此行為的測試。
