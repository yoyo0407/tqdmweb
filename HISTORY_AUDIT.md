# History / process lifecycle audit

日期：2026-10-03。由一個 subagent 獨立審核及二次核對，主代理修正並執行回歸測試。

## 已確認與修正

| 問題 | 原因 | 修正 |
| --- | --- | --- |
| Refresh Records 看似沒作用 | 只更新清單，已開啟的紀錄不重新讀取 | 手動刷新 Overview、Metrics、Console、增量曲線，保留 Axes／EMA；終態變更也自動更新 |
| 訓練完成但 process 一直 running | Board 模式的 Qtqdm.wait() 仍等待 stdin Enter | Board 模式直接 close，自然退出；獨立使用仍等待 Enter |
| 下一次啟動後，上一筆沒有 Exit Code | 舊 watcher 發現目前 process 已更換，就跳過自己的 finish | finalizer 持有穩定 record_id，自己的紀錄一律完成；guard 僅保護目前 runner 狀態 |
| 崩潰後的 running 紀錄永遠不結束 | 沒有 owner／process identity 可供核對 | 新紀錄保存 PID＋建立身分；Board 啟動時區分 active、detached、interrupted、unknown，保留未知退出碼 |
| Monitor 保留最後一筆 running | child 已退出，Bridge 不再抓 state，但也沒有讀回 final archive | 從 SQLite 還原 final snapshot 與完整歷史；缺 final snapshot 時明示 Last captured |
| DB 可能先關閉，收尾 thread 還在寫 | 只等待目前 reader 一秒，未追蹤旧 finalizers | 等所有 owned finalizers 完成後才關閉 DB；stdout 與 process exit 分開 |
| Stop 與退出同時發生時，收尾又失敗 | stdin flush 失敗後，close 也可能拋 OSError，跳過紀錄保存 | 捕捉 stdin close 的錯誤，繼續保存真實 Exit Code |

subagent 在暫存測試中確定性重現了「延遲舊 watcher、先啟動下一次」的永久 running／null exit code，以及真實 pipe 的 flush／close 錯誤。

## 狀態語意

- Training State：最後捕捉的 Qtqdm 訓練狀態，和 Process State 分開。
- Process State：Python process 是否已退出；訓練完成後 script 自行執行其他工作時，process 仍可合法 running。
- Exit Code 0：有記錄到真實的成功退出；非零碼：有記錄到真實錯誤／強制停止。
- Pending：process 尚未退出，所以還沒有 Exit Code。
- Unknown：沒有可靠退出證據；不補寫 0，也不虛構結束時間。
- Detached：原 Board 已消失，但可確認原 child 還在執行；不自行終止它。
- Interrupted：原 owner 已消失，且可確認原 child 已不存在；退出碼仍未知。

舊版沒有 PID／建立身分且沒有退出紀錄的資料，重開 Board 後標 unknown；保留原本 metrics、curves、logs。

## 驗證

- Python：81 項測試通過，包括舊 finalizer 競態、broken stdin、PID recovery、Board wait、fast-exit final result／完整 3501 點歷史。
- History browser smoke：回看不影響執行、Refresh 更新已開啟內容且保留 Axes／EMA、running 紀錄自動顯示終態／Exit Code、Force Stop 真實非零退出碼、Last captured 標示、多分頁及最後關頁退出。
- RTX 5060 / 2048 browser smoke：Pause／Resume、LR、Save／Schedule、Resume checkpoint，完成後自動退出且 code=0；控制回應約 264 ms。
