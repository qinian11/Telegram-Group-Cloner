
联系作者TG：[@hy499](https://t.me/hy499)
更多工具频道：[@HY599](https://t.me/HY599)

# Telegram 群组克隆控制台
用于管理 Telegram 监听账号、克隆账号池、消息替换和运行策略、实时完美克隆等。

## 启动
```bash
pip install -r requirements.txt
python main.py
```

## 主要能力
- 监听一个或多个源群组，并将消息转发到目标群组。
- 管理监听账号和多个克隆账号 session。
- 支持用户 ID 和关键词黑名单。
- 支持文本替换，包含 `普通文本替换` 和 `正则替换` 模式。
- 支持可选的昵称和头像同步。
- 支持每日克隆上限、身份切换冷却、发送间隔和自适应节流。
- 支持账号池状态查看、日志导出和配置校验。

## 配置文件
配置文件位置：
```text
setting/config.ini
```

示例：
```ini
[telegram]
api_id = 123456
api_hash = your_api_hash
monitor_phone = +8613800000000
source_group = https://t.me/source_a, @source_b
target_group = https://t.me/target_group

[proxy]
is_enabled = false
host = 127.0.0.1
port = 7890
type = socks5

[blacklist]
user_ids = 12345,67890
keywords = 广告, 兼职

[replacements]
你好 = 您好
旧文案 = 新文案

[strategy]
clone_name = true
clone_avatar = true
daily_clone_limit = 30
identity_cooldown_sec = 3600
min_send_interval = 1.0
max_send_interval = 3.0
replacements_mode = literal
replacements_case_insensitive = false
adaptive_throttle = true
adaptive_decay = 0.85
adaptive_penalty = 1.25
adaptive_cap = 30.0
shard_total = 1
shard_index = 0
```

## 目录结构
- `main.py`：启动入口。
- `app/`：主要处理
- `setting/`：配置文件。
- `sessions/`：Telegram session 文件。
- `sessions_banned/`：受限账号 session 归档。

## 使用建议
1. 先在设置页填写 API、监听手机号、源群组和目标群组。
2. 再在策略页调整节流、替换规则和账号池策略。
3. 先登录监听账号，再补充克隆账号池。
4. 先小流量验证日志和账号状态，再逐步扩大使用范围。
## 合规提示
请仅在合法、合规、明确授权的场景中使用本工具，并遵守 Telegram 及目标群组的相关规则。
## 尾声
熬夜更新不易，喜欢请打赏咖啡：
```text
TGCimkGvU5jNux68FJzcNRw2Zpz3izNwhm
```
<img width="2557" height="1387" alt="image" src="https://github.com/user-attachments/assets/b925b91e-dcf5-44e7-8d74-c942fd8a36a8" />

