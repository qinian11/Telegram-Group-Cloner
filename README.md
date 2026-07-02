
联系作者TG：[@hy499](https://t.me/hy499)
更多工具频道：[@HY599](https://t.me/HY599)

# TG 群组克隆控制台

一个 Windows 桌面版 Telegram 群组运营自动化控制台，支持配置 Telegram API、代理、源群/目标群、过滤与替换规则、账号池 session 管理、手机验证码登录、扫码登录、监听转发、日志导出。

## 快速启动

```powershell
python -m pip install -r requirements.txt
python main.py
```

无界面自检：

```powershell
python main.py --self-test
```

生成的单文件程序位于 `dist/TelegramGroupCloner.exe`。

## 目录

- `app/core/`：Telethon、账号池、登录、监听转发等核心逻辑。
- `app/ui/`：Tkinter 桌面界面。
- `setting/`：运行时配置目录，首次启动自动创建。
- `sessions/`：Telegram session 目录，首次启动自动创建。
- `sessions_banned/`：封禁账号迁移目录，首次启动自动创建。
- `cache/`：缓存目录，首次启动自动创建。
- `docs/`：使用说明、测试清单和已知限制。

## 合规提示
请仅在合法、合规、明确授权的场景中使用本工具，并遵守 Telegram 及目标群组的相关规则。
## 尾声
熬夜更新不易，喜欢请打赏咖啡：
```text
TGCimkGvU5jNux68FJzcNRw2Zpz3izNwhm
```
<img width="1203" height="837" alt="image" src="https://github.com/user-attachments/assets/41ecea4e-bfb3-4e05-921f-1b877b0d9914" />


