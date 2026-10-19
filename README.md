# charger-watch

盯着 ChargeLab 充电桩的空闲状态。某个桩从占用或故障变成可用时，通过 Server酱发一条微信消息，附上原页面链接。默认每两分钟检查一次；持续空闲时不会重复发消息。

程序只读充电桩页面所用的公开接口，不需要 ChargeLab 账号。它不会预约车位，也不会启动充电。这个接口不是公开承诺的开发者 API，将来若有变化，可能需要更新代码。

## 准备微信通知

1. 打开 [Server酱 Turbo](https://sct.ftqq.com/)，用微信扫码登录。
2. 在「通道配置」中设置微信消息通道，然后从「SendKey」页面复制以 `SCT` 开头的密钥。
3. 在 Server酱网页上发送一条测试消息，确认微信能收到。

SendKey 可以向你的微信发消息。不要把它提交到 Git 仓库；真实配置只保存在服务器上。免费额度和通道规则见 [官方文档](https://sct.ftqq.com/docs/getting-started/faq/)。

## 在 Ubuntu 上运行

服务器需要 Python 3，并且能访问 `api-v1-green.chargelab.io` 和 `sctapi.ftqq.com`。

```sh
git clone https://github.com/iMilesHo/charger-watch.git
cd charger-watch
sudo install -d -m 755 /opt/charger-watch
sudo install -m 644 charger_watch.py /opt/charger-watch/charger_watch.py
sudo install -m 644 charger-watch.service /etc/systemd/system/charger-watch.service
sudo install -m 600 .env.example /etc/charger-watch.env
sudo nano /etc/charger-watch.env
```

把配置文件中的示例桩号和 SendKey 换成自己的。`CHARGERS` 可以填多个桩号，用逗号分隔。

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now charger-watch
systemctl status charger-watch
journalctl -u charger-watch -n 30 --no-pager
```

第一次检查发现空闲时会提醒一次。之后只有在该桩先变为非空闲、再变为空闲时才重新提醒。请求失败不会改变上次记录的状态；发送失败会在下一轮重试。

配置 SendKey 前，可以先检查接口是否可用：

```sh
CHARGERS=EVS-1234,EVS-5678 python3 charger_watch.py --status
```
