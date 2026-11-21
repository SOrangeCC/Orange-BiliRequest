# Orange BiliRequest

B 站直播弹幕点歌显示器：监听直播间的弹幕，把「点歌 xxx」识别出来，显示成一个 Material 3 风格的卡片列表。

只做这一件事：不播放音乐、不推流、不做 ASR、不登录、不建数据库。

---

## 1. 项目结构

```
OrangeBiliRequest/
├── main.py                     # 入口：命令行参数 + --demo 假弹幕
├── bilibili/
│   ├── __init__.py
│   └── danmaku.py              # conn-info 取 token + 聊天 WebSocket + 包/帧拆分
├── parser/
│   ├── __init__.py
│   └── song_parser.py          # 「点歌 xxx」规则匹配，产出 SongRequest
├── gui/
│   ├── __init__.py
│   └── app.py                  # Material 3 窗口、卡片列表、监听线程
├── tests/
│   ├── test_song_parser.py     # 解析规则表
│   └── test_danmaku_framing.py # 协议拆包/分帧，喂构造字节
├── requirements.txt
└── README.md
```

数据流只有一条：

```
DanmakuStream -> Danmaku(username, text, timestamp)
              -> parser.parse -> SongRequest(user, song, timestamp)
              -> ListenerThread 信号 -> SongCard 插入列表顶部
```

---

## 2. 安装依赖

需要 Python 3.10+。除 GUI 用的 PySide6 外全是标准库。

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows PowerShell 用 .venv\Scripts\Activate.ps1
pip install -r requirements.txt # 或 pip install PySide6
```

macOS / Linux 上把第一行激活命令换成 `source .venv/bin/activate`。

---

## 3. 启动命令

```bash
python main.py                  # 启动后在输入框里填房间号
python main.py --room 21452505  # 房间号直接带上
python main.py --demo           # 不联网，用脚本弹幕验证整条链路
python main.py --theme dark     # 强制深色（light / auto，auto 跟随系统）
```

界面操作顺序就三步：

1. 输入 B 站直播间房间号（地址栏 `live.bilibili.com/` 后面那串数字）；
2. 点 **开始监听**（再点一次变成 **停止监听**）；
3. 观众发「点歌 起风了」，卡片立刻出现在列表顶部；底部状态行显示已收到的弹幕数。

**清空列表** 按钮清掉所有卡片；右上角按钮在深色 / 浅色之间切换。列表最多保留最近 100 条，
新的进来、最旧的自动移除。

---

## 4. 支持的点歌写法

| 弹幕 | 结果 |
| --- | --- |
| `点歌 起风了` | 起风了 |
| `点歌: Lemon` / `点歌：Lemon` | Lemon |
| `点一首 稻香` / `点一首歌 晴天` | 稻香 / 晴天 |
| `点歌《漠河舞厅》` | 漠河舞厅 |
| `点歌起风了`（没空格） | 起风了 |

会被丢掉：

- 只有指令没有歌名：`点歌`、`点歌:`；
- 歌名少于 2 个字：`点歌 好`；
- 「点歌」不在开头：`有人点歌吗`、`求点歌 起风了`；
- 非文本消息：礼物、上舰、进场提示（只认 `DANMU_MSG`）。

歌名超过 40 字会截断，只影响卡片显示。

---

## 5. 测试方法

**离线单元测试（不联网，推荐先跑这个）**

```bash
python -m unittest discover -s tests -t . -v
```

覆盖：解析规则表；`op=5` 的多包拼接体怎么拆；半包不吞、一帧被两次 `recv` 收到时怎么拼回；
`DANMU_MSG` 里取用户名、正文和服务器时间戳。

**链路 + 界面，但不联网**

```bash
python main.py --demo
```

走的是和真实弹幕完全相同的路径（`Danmaku` → `parse` → 卡片），只是数据来源换成脚本，
里面故意放了 `点歌`、普通聊天这类应当被丢弃的输入。

**真实直播间**（房间必须正在直播）

点 **开始监听** 后状态行应依次出现：

```
已取到聊天 token（anonymous worker），正在连接…
已连接 broadcastlv.chat.bilibili.com（房间 21452505）
已收到 37 条弹幕 · 2 条点歌
```

自己用另一个账号发一条「点歌 测试歌曲」，卡片应当立刻出现。若状态行停在
`聊天服务器拒绝该 token（code -100）` 或 `拿不到聊天 token`，见下面第 6 节。

> 2026-10-10 在房间 21452505 实测过一次：匿名 worker 给 token → 连上
> `broadcastlv-mixed.chat.bilibili.com` → 20 秒里解出 3 条真实弹幕，用户名和时间戳都对。
> 上面三行状态就是那次跑出来的。

---

## 6. 连接方式与它的前提

- **必须先拿 token。** B 站聊天服务器在收到带 `key` 的 Auth 包之前不回任何数据；
  官方 conn-info（`getDanmuInfo`）对匿名请求返回 **-352**（多个 header/cookie 组合实测），
  所以默认走匿名 worker 端点取 token——它不需要登录，代价是它是第三方服务、没有契约，
  哪天可能就不回答了。这个 worker **只接受 POST**（GET 会被 Cloudflare 挡成 403 挑战页）。
  这时用 `--cookie "SESSDATA=...; buvid3=..."` 或环境变量
  `BILI_COOKIE` 改走官方接口。cookie 只从命令行 / 环境变量传入，不写文件、不打日志。
- **Auth 是现代扁平包**：`{"uid":0,"roomid":<int>,"protover":2,"platform":"web","type":2,"key":<token>,"buvid":<buvid3>}`。
  网上教程里常见的 `{"cmd":"Auth","args":[...]}` 会被立刻断开。
- **`protover=2`** 让服务器回 zlib 包装的 JSON；`3` 是网页端现在默认用的 protobuf，本项目不解。
- **`op=5` 的 body 是包中包**：一条 `op=5` 里可能拼了若干条完整包，必须再拆一次；
  拆出来的子包仍带 `op=5` 但版本降为 0，所以只能在「这段 body 不像包头」时停下，
  否则会把 JSON 的前 16 字节当成包头读掉（这正是「数到 61 帧、0 条弹幕」的来路）。
- **心跳 25 秒**，连接满 30 分钟重新取 token 重连；断线自动重连，不用管。
- **时间戳**优先用服务器给的 `info[0][4]`（epoch 毫秒），拿不到才退回本机时间。

---

## 7. 已知限制

- 房间没在直播、或者没人发点歌时列表就是空的——这是正常状态，不是坏了。
- 匿名 worker 失效时需要 `--cookie`；本项目不做扫码登录，也不存任何账号信息。
- 不去重：同一个人连发三次「点歌 晴天」会出现三张卡片。
- 弹幕用户名只显示在窗口里，不落盘、不写日志。
- 只处理文本弹幕；分房间（分区）跳转、多房间同时监听不在范围内。
- Windows / Linux / macOS 都只依赖 PySide6 和标准库，未在 macOS 上做过真实直播间验证。
