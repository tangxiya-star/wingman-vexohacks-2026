# Wingman 硬件 Demo：Vexo、心率与双人举手

本目录包含 Vexo 62/77 的蓝牙控制、Apple Watch/WHOOP 心率转发、双人举手 MATCH，以及 Watch/WHOOP 震动实验。62 号配置在 `band_config.py`；77 号由 `start_whoop_vexo.command` 的 `--band 77` 指定。这里只是独立硬件 demo，尚未接入仓库 `server/` 的配对工作流。
运行时保留 Mac 在附近且处于唤醒状态。Vexo 可以拔掉 USB，但需要足够电量。

## 首次安装

在 macOS 上准备 Python 3.12 和 Git；Node.js 用于官方识别器差分测试。官方 Vexo SDK 作为 Git submodule 固定在 `1e4291e2fa4896b1f603d3d4f0b009c483425da0`。

```sh
# 从 Wingman 仓库根目录进入
cd hardware/vexo
./setup.command
cp .env.example .env.local
# 编辑 .env.local，填入本机扫描并确认的心率源 ID
.venv/bin/python heart_rate.py --scan
.venv/bin/python heart_rate_receiver.py --scan
```

不要提交 `.env.local`、`runtime/`、设备校准、心率/IMU 记录、Watch 开发签名或构建目录。Git 已排除这些内容。设备 ID 在不同 Mac 上可能不同；仅连接自己已确认的设备。

无硬件检查与模拟：

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python heart_rate.py --sim --temperature-demo --seconds 20
```

两个终端分别运行 `./start_bio_demo.command`（62）和 `./start_whoop_vexo.command`（77 与面板），打开 [本机面板](http://127.0.0.1:8765/)。首次使用在各自终端输入 `d` 保存下垂、`u` 保存头顶姿态，各静止约 1 秒。详细步骤见下文。

[Watch 震动 App 安装与构建](watch-haptics/README.md)使用独立端口 8766；仓库清空了开发者 Team，安装时选择自己的 Team。它已通过编译/协议测试，真机触觉仍需独立验收。WHOOP 按需震动工具为 `whoop_buzz.py`；必须显式传入自己设备的 `--source` 和 `--serial`，默认只检查身份，只有 `--buzz` 才发送。


## 同时演示心率和温度

手环只有一颗可编程 RGB 灯。默认合并模式用**真实 Apple Watch 心率控制闪烁快慢，双敲触发模拟温度颜色动画**，亮度保持 100%。
手机和手表先开启 HeartCast，再双击 `start_bio_demo.command`，或运行：

```sh
./start_bio_demo.command
```

该入口使用 `.env.local` 中配置的手机身份，并启用 `--temperature-demo --raise-hand`：保留心率灯和双敲颜色动画，同时把抬手动作输出给 Mac。收到有效心率后，平时以**蓝灯**按下方心率档位闪烁。双敲 62 号，播放一轮颜色动画：

| 动画时间 | 灯光颜色 |
|---|---|
| 0–3 秒 | 蓝 |
| 3–6 秒 | 青 |
| 6–9 秒 | 黄 |
| 9–12 秒 | 橙 |
| 12–15 秒 | 红 |

15 秒播完后回到蓝色。无论当前是蓝、青、黄、橙还是红，每次双敲都会立即从蓝色重新计时并完整播放到红色。动画期间仍由实时心率决定闪烁快慢。
**颜色是纯模拟演示，不读取芯片温度或人体温度，也不代表测温结果。** 心率无效、过期或来源断开时仍会熄灯，动画不会绕过这项保护。

只运行一个控灯程序。`start_bio_demo.command` 在同一程序内处理心率、动画和抬手识别，不能再同时启动单独心率/温度/敲击演示或 Dashboard。
无硬件演示：`.venv/bin/python heart_rate.py --sim --temperature-demo --seconds 20`；此时心率与手环也是模拟的，模拟器在第 2 秒注入一次双敲，随后播放完整动画。

## 抬手动作 → Mac 事件

默认入口 `./start_bio_demo.command` 已开启此功能。Vexo 通过蓝牙把 **50 Hz 六轴 IMU** 数据发给 Mac，由 `TrainedRaiseDetector` 按官方 gesture-trainer 的模板流程识别，再输出 `hand_raise` 事件。

首次使用或重新佩戴后，在运行程序的终端完成以下步骤；每个命令都要按回车：

1. 手臂**自然下垂**，输入 `c`，保持静止约 1 秒，等待校准完成。程序不会再把启动后的第一个静止姿势自动当成下垂；未明确校准且没有有效保存模型时，不输出动作事件。
2. 输入 `t`，做 **3 轮“快速举过头顶 → 放下”**，在举起、放下两端各稍停约 1 秒。程序分别学习 3 个 `raise` 正例和 3 个 `lower` 负例；看到两类均为 `3/3` 才算训练完成。**训练期间不输出 `hand_raise`。**
3. 使用新动作验收：从自然下垂快速举起，识别后只发一次事件；保持举着不会重复，必须放下静止重新准备后才能再次触发。输入 `s` 查看状态、训练计数和最近匹配结果。

这是 **Mac 对个人动作模板的匹配**，不是 Vexo 固件自带的事件，不再用固定 130° 作为触发规则，也不能恢复三维位置轨迹或测出手的绝对高度。应用仍要求从下垂姿态起步、快速动作和放下后重新准备。官方模板把动作按时间重采样为 24 × 6 = 144 个数，角速度除以 250，再比较距离；官方默认未知门限为 0.5。本应用训练完成后可根据 3 个举起正例之间的最近邻距离扩大门限，以容纳个人示范差异；这是应用层调整，不是已验证的识别率。原理和限制见 [手势研究记录](docs/research/vexo-gesture-trainer.md)。

基线、模板与门限自动保存在 `runtime/raise_calibration_62.json`，文件包含 `band_number`、`simulated` 和版本为 2 的 `profile`。模拟模式独立使用 `runtime/sim_raise_calibration_62.json`，不混用真人模型。重启恢复模型后，仍须实际放下手并静止，才能重新进入待触发状态。**重新佩戴后输入 `c` 会清空旧模板，必须再用 `t` 重训。** 自定义 `--events-file` 时，校准文件随事件文件保存到同一目录。

动作识别不需要等手机心率恢复；只要 Vexo 与 Mac 的连接仍正常，HeartCast 断开时仅熄灭心率灯，抬手识别继续运行。

每次识别到的动作会向标准输出打印一行 JSON，同时追加到本目录的 `runtime/hand_events.jsonl`。模拟模式使用 `runtime/sim_hand_events.jsonl`。`runtime/` 已被 Git 忽略；默认保存事件及上述校准模型，**不记录原始 IMU 数据或心率历史**。

需要短时诊断时，显式输入 `r` 开始在 `runtime/debug/` 保存本地原始 IMU，输入 `x` 停止；最多记录 6000 个样本（50 Hz 时约 120 秒），不含心率。若要诊断训练过程，应**先 `r`、再 `t`**，完成后用 `x` 关闭记录。训练数据不能当作验收结果；验收需另做 **5 次新的实机举手正例**，以及打字、转腕、挠头、抬到肩部等普通动作负例，分别检查漏识别、重复和误报。

在另一个终端查看新事件：

```sh
tail -f runtime/hand_events.jsonl
```

事件格式示例（以下数值不是实测记录）：

```json
{"type":"hand_raise","gesture":"quick_overhead","device_time_ms":123456,"duration_ms":760,"angle_deg":163.0,"peak_gyro_dps":410.0,"match_distance":0.23,"simulated":false,"detected_by":"mac_imu_detector","band_number":62,"received_at":"2026-11-14T20:00:00Z","sequence":1}
```

`device_time_ms` 是手环的设备时间，`received_at` 是 Mac 收到事件的 UTC 时间，`sequence` 在本次程序运行中递增。`match_distance` 是与最近模板的距离，不是概率；`simulated` 明确区分模拟事件与真实数据产生的事件。

单独使用心率入口时可加 `--raise-hand` 开启动作识别，`--events-file` 可覆盖保存路径：

```sh
./start_heart_rate.command --raise-hand --events-file runtime/my_hand_events.jsonl
```

## Apple Watch 心率红灯

链路：Apple Watch → iPhone HeartCast → 标准蓝牙心率 → Mac → 蓝牙 → Vexo。
手机和手表均安装 [HeartCast（Logic Phase）](https://apps.apple.com/us/app/heartcast-heart-rate-monitor/id1499771124)。
**HeartCast 的手机端要运行在与 Watch 配对的 iPhone 上。Mac 只运行本目录的 Python 接收程序。**
在 Apple Silicon Mac 上安装 iPhone 版 HeartCast，不能代替配对的 iPhone；若窗口显示 Apple Watch 灰色、AirPods 被勾选、0 BPM，请回到手机端选择 Apple Watch 输入。

1. 打开手机和手表的 HeartCast，按提示允许心率、Workout 和蓝牙权限。
2. 在 Watch 上点 Start，确认手机也显示 BPM；首次连接时保持手机 App 在前台。
3. 退出 `tap_demo.py`、温度演示和 Dashboard，释放 Vexo 的唯一蓝牙连接。
4. 在本目录扫描心率广播（不连接、不读取心率）：

   ```sh
   .venv/bin/python heart_rate.py --scan
   ```

5. 确认自己的心率源 ID（可通过开始/停止手机广播核对），双敲 62 号使蓝灯闪烁，再运行：

```sh
.venv/bin/python -u heart_rate.py --source '上一步显示的自己的设备ID'
```

将扫描确认的手机 ID 填入 `.env.local` 的 `HEARTCAST_SOURCE_ID`。可在 Finder 双击 [start_heart_rate.command](start_heart_rate.command) 启动；它会自动进入本目录、使用 `.venv`，并锁定配置的手机。仓库不包含开发者的设备 ID。
运行前仍需在 Watch 上启动 HeartCast，并释放 62 号手环的其他蓝牙连接。
终端也可运行 `./start_heart_rate.command --seconds 60`；Ctrl+C 结束。
该 ID 是此 Mac 对蓝牙设备的标识；换 Mac 或设备标识变化时应重新扫描和确认。
识别到广播不代表已收到真实心率，实机验证状态见文末。

即使只有一个 HeartCast，程序也不会猜它属于你；不带 `--source` 时仅发现候选，不建立连接。
运行期间重连只尝试已选定的同一心率源。Vexo 断连则程序退出，双敲后重新运行即可。
单独心率模式使用红色 `blink`，默认合并模式的颜色由上方动画决定；两者都使用最大亮度（100%），每周期前半亮、后半灭。
闪烁周期按下面的心率档位选择，让快慢变化更明显：

| Apple Watch 心率（BPM） | 闪烁周期 | 每次亮 / 灭时长 |
|---|---|---|
| ≤70 | 1000 ms | 500 / 500 ms |
| 71–75 | 900 ms | 450 / 450 ms |
| 76–80 | 800 ms | 400 / 400 ms |
| 81–85 | 700 ms | 350 / 350 ms |
| 86–90 | 600 ms | 300 / 300 ms |
| 91–95 | 500 ms | 250 / 250 ms |
| 96–100 | 400 ms | 200 / 200 ms |
| 101–105 | 300 ms | 150 / 150 ms |
| 106–110 | 200 ms | 100 / 100 ms |
| >110 | 100 ms（硬件下限） | 50 / 50 ms |

**这是夸张的心率快慢映射，不按 `60000 / BPM` 计算，也不是每次真实心搏同步。** 例如 95 BPM 时每秒闪 2 次，用来突出心率上升，而非声称每分钟只闪 95 次。
电池低于 3.5 V 时固件会将实际亮度限制在约 25%；接入 USB 或电压恢复到 3.6 V 后解除限制。
同一档位且颜色不变时不反复写灯光命令，避免重置闪烁节奏。每次改变设置后会读取 Vexo 的设置确认。

没有有效心率时灯光关闭；收到接触不良、无效心率或心率源断开时停止闪烁。
默认 15 秒收不到心率通知也停止，可用 `--stale-after` 调整。Ctrl+C 会关灯并释放连接。

标准心率通知没有测量时间戳：程序能检测蓝牙通知停更，但无法区分“新测得的相同 BPM”和“转发 App 重发旧值”。
需要对照手机和 Watch 验证更新情况。终端打印 BPM；项目不保存心率历史、不上传云端。
HeartCast 自身的数据处理以其说明为准。它使用 workout 会话，可能影响活动圆环；结束时可按 App 选项丢弃运动记录。

调试参数：`--seconds 60` 运行一分钟；`--brightness 0.5` 调低亮度；`--usb` 仅将 Vexo 链路改为 USB，心率来源仍用蓝牙。
没有硬件时：

```sh
.venv/bin/python heart_rate.py --sim --seconds 15
```

`--sim` 的心率和手环都是模拟数据。`--demo-bpm 60 --seconds 10` 则把明确标记的固定模拟心率发给真实 62 号，仅用于灯光测试；不能当作 Apple Watch 已接通。

## WHOOP 心率直接接收至 Mac

在朋友手机的 WHOOP App 中进入 **Device Settings（设备设置）**，开启 **Heart Rate Broadcast / Broadcast Heart Rate（心率广播）**。WHOOP 开启标准蓝牙心率广播后，Mac 可以直接接收手环发送的 BPM；此入口不需要 Apple Watch 或 HeartCast。

先扫描确认自己的 WHOOP，将设备 ID 填入 `.env.local` 的 `WHOOP_SOURCE_ID`，可选填写 `WHOOP_NAME`。随后双击 `start_whoop_heart_rate.command`，或运行：

```sh
./start_whoop_heart_rate.command
```

这个入口默认锁定配置的设备，并显示配置的 `WHOOP_NAME` 标签；原有 Apple Watch 和 Vexo 启动入口保持独立。确认广播身份不代表已接收或核对真实 BPM。换 Mac 或设备 ID 变化后，需要重新扫描并确认身份。

先发现附近的标准心率广播，只列名称和设备 ID：

```sh
.venv/bin/python heart_rate_receiver.py --scan
```

通过朋友开启/关闭广播或设备信息确认哪一个 ID 属于她，再接收：

```sh
.venv/bin/python -u heart_rate_receiver.py --source '已确认的 WHOOP 设备 ID' --label '朋友的 WHOOP'
```

`heart_rate_receiver.py` 只向终端输出每次有效通知的 BPM 和断流状态，不连接 Vexo、不控制灯光，也不保存心率历史。它是朋友的独立心率输入，可以与用户自己的 Apple Watch 接收程序分开运行，不会替换现有来源。重连始终锁定指定 ID，不会自动选择另一台 WHOOP。

可加 `--seconds 60` 接收一分钟；`--stale-after 15` 设置停更提示时限；Ctrl+C 退出。2026-11-14 已实际连接配置的设备、订阅标准心率通知，并在 Mac 收到每秒更新且会变化的 BPM；尚未逐条对照朋友手机 App 的显示值。

### 在本机网页查看 WHOOP 心率

先停止正在运行的 WHOOP 终端接收程序，再双击 `start_whoop_dashboard.command`，或运行：

```sh
./start_whoop_dashboard.command
```

然后打开 [WHOOP 本机面板](http://127.0.0.1:8765/)。入口默认锁定 `WHOOP`，显示实时心率和连接状态；页面只在这台 Mac 上可访问，最近数据仅保存在内存。Ctrl+C 停止面板和接收。

**同一时间只运行一个 WHOOP 接收程序**：网页面板和 `start_whoop_heart_rate.command` 二选一。启动参数会传给后端，例如 `./start_whoop_dashboard.command --port 8766` 改用本机端口 8766。

### WHOOP 面板与 77 号 Vexo 同时运行

用户已确认新的手环是 **Vexo-HACK-77**。先停止其他 WHOOP 接收实例，双击 `start_whoop_vexo.command`，或运行：

```sh
./start_whoop_vexo.command
```

这个入口在**同一个进程**中接收 `WHOOP`、提供 [本机心率面板](http://127.0.0.1:8765/)，并用心率控制 77 号的灯光。它与纯网页面板、终端 WHOOP 接收入口三选一，不要同时启动。

有效心率按每 5 BPM 一档控制闪烁周期：≤70 BPM 为 1 秒，之后每档缩短 0.1 秒，>110 BPM 为 0.1 秒；请求最大亮度 100%。平时蓝色，双敲 77 号后蓝→青→黄→橙→红各 3 秒，共 15 秒后回蓝；任何颜色下再次双敲都会从蓝色重播。颜色仍是模拟温度，不是测温。

77 号仅由此入口的 `--band` 指定；`band_config.py` 中原有的 62 号及 Apple Watch 启动入口保持原配置。

2026-11-14 实机验证：已通过蓝牙连接 77 号，使用同一份真实 WHOOP 数据驱动网页和灯光，并从手环读回确认 100% 亮度及对应心率档位的闪烁周期。收到真实双敲事件后，五色演示和中途从蓝色重播均已由用户确认正常。USB 当时用于充电；77 号尚未做拔线复测。相关模拟及本地 HTTP 测试 8 项通过。

### 77 号抬手动作 → Mac 事件

`start_whoop_vexo.command` 同时启用 77 号的动作识别，使用与灯光相同的一条蓝牙连接。WHOOP 心率、网页和双敲颜色动画继续运行；动作识别采用上文的六轴个人模板流程。

77 号可单独完成 `c` 校准和 `t` 训练，也可把已训练模型作为起点迁移后先试用。独立训练时，手自然下垂约 1 秒后，做 3 轮快速举过头顶—放下，两端各停约 1 秒；各 3 个举起、放下模板录齐后，用新动作验收。迁移模型仍需在目标手环上验证，因为佩戴方向、手腕和动作速度可能不同。

77 号的模型保存在 `runtime/raise_calibration_77.json`，事件保存在 `runtime/hand_events_77.jsonl`，每条事件带有 `band_number: 77`。62 号原模型、事件与启动入口保持独立。77 号断开重连后恢复自己的模板，仍需实际下垂后再触发；重新佩戴使用 `c` 后要重新训练。

命令仍为 `c` 校准、`t` 训练、`s` 状态、`r/x` 开始/结束最多 120 秒的本地 IMU 诊断记录。动作识别不依赖 WHOOP 是否有有效 BPM；心率失效只会关闭心率灯。

按用户选择，已将 62 号当前模型复制为 77 号的独立模型，包含来源记录，保留 62 号原文件不变；77 号现已通过 BLE 连接并加载该模型，等待双人实测。62 号的 5/5 实机结果不代表 77 号已经验收通过；如果模板不适配，再单独校准训练。

### 两只手环同时举起：MATCH

保持 `start_bio_demo.command`（62 号）和 `start_whoop_vexo.command`（77 号与网页）同时运行，打开 [本机面板](http://127.0.0.1:8765/)。两张卡分别显示 62、77 号的当前姿态；两只都接近各自保存的头顶姿态时，MATCH 亮起。任意一只离开该姿态、姿态不确定、重新保存姿态、断连或超过 2 秒没有新数据，MATCH 解除。页面请求失败或切回页面时也会清除旧状态。

持续姿态和快速 `hand_raise` 事件独立判断。面板使用 `SustainedPoseEstimator` 的短窗口重力方向，不再等待官方手势分段或模板匹配成功。因此慢慢举起、启动时已举起，也可在姿态稳定后显示。首次使用或重新佩戴，在对应终端输入 `d` 保存自然下垂、输入 `u` 保存头顶，每次静止约 1 秒；两方向至少相差 60°。文件为 `runtime/pose_calibration_N.json`，与 `raise_calibration_N.json` 分开保存，`d/u` 不删除动作模板，`c/t` 也不删除姿态校准。开发现场 62 号曾使用明确标注的验收记录初始化；仓库不包含个人校准，两只手环都需要自己完成 `d/u`。

这是手环方向的代理，不能测出手的绝对高度；同方向的其他姿势也可能满足条件，大幅转腕可能解除 MATCH。77 号本轮原始数据连续，但官方分段将连续动作串成超过 3 秒的长段，尚未进入模板匹配。因此严格快速事件的迁移效果仍未通过验收，不能把新增持续姿态功能当作其通过证据。

两进程只共享本地最新状态，分别写入 `runtime/motion_state_62.json` 和 `runtime/motion_state_77.json`，由 `/api/motion` 合并；模拟文件使用 `sim_` 前缀，不会点亮真实面板。原始运动只在显式 `r/x` 诊断时短时记录。WHOOP 心率是否更新不影响举手 MATCH。

2026-11-14 14:50–14:52 Pacific，已保存 77 号本人明确下垂/头顶两个姿态。随后用户另做双人联动验收，确认“顺序正确，放下 77 后解除 MATCH”：双手放下 → 同时上举 → 只放下 77 → 全部放下。真实 API 与浏览器均观察到 MATCH，状态变化记录在 `runtime/debug/match_pose_trial_20261114T225005.jsonl`。这是一轮演示验收，仍有短暂 unknown 状态，不代表所有转腕姿势都稳定，也不等同于 77 号严格 `hand_raise` 模板通过验收。

本次发布在干净 Python 3.12 环境完成安装，157 项 Python 测试通过，20 秒模拟心率/温度动画正常结束；JavaScript 语法、Swift 协议检查与 Watch 未签名构建均通过。测试涵盖采样时间抖动、校准超时、重新佩戴保护、真实 SDK 模拟的 77 号独立训练、重连恢复、WHOOP 断开时继续接收动作，以及 HTTP 双人 MATCH/放下/失联。Watch 真机触觉和 77 号严格快速事件仍需各自验收。

## 芯片温度演示

旧的真实芯片温度合并模式仍可选：

```sh
./start_heart_rate.command --temperature
```

它每秒读取 Vexo 芯片温度，以首次读数为基线；基线或更低为蓝色，升高 0.25 / 0.50 / 0.75 / 1.00°C 时依次变为青 / 黄 / 橙 / 暖红。
可加 `--temperature-span 2`，改为升高 2°C 才达到暖红。芯片温度超过 5 秒未更新时熄灯。
`--temperature` 与 `--temperature-demo` 互斥：前者读取芯片，后者只播放模拟动画；两者都不能代表皮温、体温或发热检测。

独立的 `temperature_demo.py` 也保留。
先停止心率程序，然后运行：

```sh
.venv/bin/python temperature_demo.py
```

每秒显示手环**芯片温度**，以连接后的首次读数为基线，±2°C 对应蓝→绿→红。
这不是皮温、体温，也不是发热检测。支持 `--sim`、`--usb`、`--seconds`。
这是单独的温度模式；要将真实芯片温度与心率同时展示，使用 `heart_rate.py --temperature`，不能同时运行两个控灯程序。

## 环境与验证

现有 `.venv` 使用 Python 3.12，依赖在 `requirements.txt`，官方 SDK 保持在 `vexo-open-kit/python`，未修改。
原敲击变色演示仍可运行：`.venv/bin/python tap_demo.py`。

```sh
.venv/bin/python -m unittest discover -s tests -v
```

测试覆盖 BLE 心率格式、接触状态、损坏包、灯光周期、停更/断连熄灯、相同 BPM 恢复，以及多个心率源时拒绝猜选。
模拟测试通过不代表 Apple Watch 实机链路已通过。方案依据见 [研究记录](docs/research/apple-watch-vexo-heart-rate.md)。

2026-11-14：此前旧规则版本的 77 项测试通过，覆盖灯光模式、旧抬手检测器、事件 JSONL 和模拟集成；到位稳定确认延迟及 LED 超时恢复的回归均在修复前失败、修复后通过。CLI 模拟器也完整播放了 15 秒动画并回蓝。这一历史计数不代表当前模板版本的最终测试结果。当前模板版本的 105 项定向测试已通过，包含官方算法差分比对、模板训练/恢复/锁存、事件集成及原心率灯光回归；这些仍是软件测试。

历史实机验证：真实链路 Watch → iPhone HeartCast → Mac → BLE → Vexo 已跑通，用户确认 Apple Watch 来源、读数一致，以及拔掉 Vexo USB 后仍闪；旧芯片温度合并模式也已收到真实读数，并从 62 号读回确认灯光设置。单独的 `temperature_demo.py` 仅做过模拟验证。

分档模式已通过 BLE 连上 62 号并开启双敲事件；收到真实心率时，已从 62 号读回确认蓝色、对应心率档位及 100% 亮度。HeartCast 连接曾有间歇性断开，程序自动熄灯并重连。双敲 15 秒动画已获得用户实机反馈“完美”。未测量绝对端到端延迟，未进行长时间锁屏或脱腕实测。

旧固定角度规则曾出现漏报，已被当前官方模板流程替代；旧记录回放结果不能当作新版验收。

当前已补有限超时恢复：连接仍在时，普通灯光应答超时会使缓存失效，并重试最新目标；前两次超时期间动作接收继续，第三次仍失败或真正断连等错误则退出清理。恢复逻辑已通过模拟回归，不能据此宣称无线链路永不掉线。

当前手势版本为 `TrainedRaiseDetector`，要求显式 `c` 校准后 `t` 训练。62 号录齐三次举起/放下后，独立的新一轮五次快速上举恰好收到五个真实事件，头顶保持无重复；从待触发状态执行肩高动作没有误报。个人动作参数与原始记录不随源码发布。官方算法差分测试只证明移植一致；少量实测不代表换人、换手或重新佩戴后的普适识别率。

并行测试 WHOOP 震动时，可运行 `./start_whoop_vexo.command --no-heart-rate` 暂时让出 WHOOP 连接，保留 HTTP 面板和 77 号动作接收。此时 WHOOP 心率与对应灯光暂停，62 号独立运行；不能通过停止整个面板来释放 WHOOP，否则网页和 77 号动作也会断开。按现场需要选择该模式；恢复心率时去掉此参数。
