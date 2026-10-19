# charger-watch

盯着 ChargeLab 充电桩的空闲状态。某个桩从占用或故障变成可用时，通过 Telegram 发一条消息，附上原页面链接。默认每两分钟检查一次；持续空闲时不会重复发消息。

程序只读充电桩页面所用的公开接口，不需要 ChargeLab 账号。它不会替你预约车位，也不会启动充电。该接口不是公开承诺的开发者 API，将来若有变化，可能需要更新代码。

## 准备 Telegram Bot

1. 在 Telegram 中打开 [@BotFather](https://t.me/BotFather)，发送 `/newbot`，按提示创建 Bot 并保存 Token。
2. 打开新 Bot，发送 `/start`。
3. 在本机运行 `python3 telegram_chat_id.py`，粘贴 Token。脚本会打印最近消息的 Chat ID，输入的 Token 不会显示在终端上。

Token 能控制这个 Bot，不要提交到 Git 仓库或发给别人。

## 在 Ubuntu 上运行

服务器需要 Python 3 和能访问 `api-v1-green.chargelab.io`、`api.telegram.org` 的网络。

```sh
git clone https://github.com/iMilesHo/charger-watch.git
cd charger-watch
sudo install -d -m 755 /opt/charger-watch
sudo install -m 644 charger_watch.py /opt/charger-watch/charger_watch.py
sudo install -m 644 charger-watch.service /etc/systemd/system/charger-watch.service
sudo install -m 600 .env.example /etc/charger-watch.env
sudo nano /etc/charger-watch.env
```

把配置文件中的示例桩号、Token 和 Chat ID 换成自己的。`CHARGERS` 可以填多个桩号，用逗号分隔。真实配置保存在服务器的 `/etc/charger-watch.env`，不放进公开仓库。

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now charger-watch
systemctl status charger-watch
journalctl -u charger-watch -n 30 --no-pager
```

第一次检查发现空闲时会提醒一次。之后只有在该桩先变为非空闲、再变为空闲时才重新提醒。请求失败不会改变上次记录的状态；发送失败会在下一轮重试。

想先检查接口是否可用，可以在配置 Telegram 之前运行：

```sh
CHARGERS=EVS-1234,EVS-5678 python3 charger_watch.py --status
```

如果日志里一直显示连接 Telegram 失败，先从服务器检查它能否访问 `https://api.telegram.org`；中国大陆的服务器可能需要出站代理，或者把服务放到能访问 Telegram 的机器上。
