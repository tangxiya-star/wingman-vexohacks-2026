# Apple Watch 心率 → Vexo 62 红灯：方案核查

核查日期：2026-11-14（America/Los_Angeles）。目标是把 Apple Watch 的最新心率映射成 Vexo-HACK-62 的红灯闪烁节奏。最新状态：已从用户开启的 iPhone HeartCast 收到持续变化的心率，62 号通过 BLE 按最新 BPM 闪红；用户确认 Apple Watch 来源、读数一致，并确认拔掉 Vexo USB 后仍闪。本文区分文档与协议核查、模拟测试和这次短时实机验证。

## 结论

本文保留初版方案核查；当前 demo 已按每 5 BPM 分档放大灯光节奏，具体行为以 [硬件 README](../../README.md) 为准。

**当前实际跑通的是 Watch → iPhone HeartCast → Mac → BLE → Vexo。** 用户此前提出希望省掉 iPhone 中转；讨论替代路线期间，用户又告知手机 HeartCast 已准备好，因此先完成了现有链路。标准 BLE 心率接收与 Vexo 红灯程序已通过 23 项测试及上述短时实机验证。仍需 iPhone 和唤醒状态的 Mac，不代表已经实现无手机直连。

**省掉手机的后续候选仍为：现成 Health Data Server（HDS）Watch App → 局域网 REST → Mac → BLE → Vexo，或自建独立 Watch App → BLE → Mac → BLE → Vexo。** 原生 BLE 路线可让 Mac 发布可写服务，Watch 主动连接并写入心率；还可进一步探索 Watch 直接控制 Vexo。HDS 美区商店价格为 $4.99，尚未购买或安装；本地路径无需 HDS Cloud 订阅。原生方案需要开发签名、安装及实机验证。两条替代路线均未实施。[20][21]

保留此前研究结论：HeartCast 是省去原生 App 开发的 demo 路线，不是 Apple 指定的最佳实践，也没有证据证明它是所有场景下延迟最低或最稳定的实现。它的标准 BLE Heart Rate Service 输出仍可作为替换输入，但不满足用户新增的“运行时无 iPhone 中转”约束。[1][2]

## 路线比较

| 路线 | 运行时链路 | 优点 | 成本与待验证项 |
|---|---|---|---|
| HDS 本地 REST（当前候选） | Watch HDS → 同局域网 HTTP → Mac → BLE → Vexo | 官方提供不连接手机的 REST 路径；本地服务器源码和消息格式可核查，复用已有 Mac 控灯代码。[20][21][22] | Watch App $4.99；需 Watch 自身能通过网络到达 Mac；现场 Wi-Fi 隔离、更新频率、停更识别与端到端延迟未实测。 |
| HeartCast + 当前 Python 程序（已跑通） | Watch → iPhone HeartCast → BLE HRS → Mac → BLE → Vexo | 基础心率功能免费；标准 BLE 心率服务；短时真实数据、红灯更新、拔掉 Vexo USB 已验证。[1][2] | 仍需 iPhone 中转。首次连接需 iPhone App 前台；绝对传输延迟、长时后台运行、真实断流和断连恢复仍未实测。[1] |
| 自己开发 Watch-only App | Watch HealthKit → Watch Core Bluetooth central → Vexo | 可在架构上去掉 iPhone/Mac 转发；可自己控制源时间戳、失效处理、权限和界面。Apple 支持独立 Watch App、实时 workout 数据与 Watch 连接 BLE 外设。[3][4][5] | 需要 Swift/watchOS 实现、开发签名、Developer Mode、安装和实机测试；活动 workout 的执行权限不能直接当作“任意 BLE 后台操作无限制”的保证。[6][7][8] |
| 自己开发 Watch + iPhone App | Watch HealthKit → workout mirroring / Watch Connectivity → iPhone BLE → Vexo | 不依赖 Mac，可做自有手机界面；Apple 提供 workout mirroring。[9] | 多一个转发与运行状态；Apple 明确写明 mirrored iOS App 被挂起时数据会缓存，回调可能相隔数分钟，不能仅靠 mirroring 假定锁屏时实时。[10] |
| ECHO | Watch → iPhone ECHO → BLE → Mac → Vexo | 同属手机 BLE 心率广播路线，可作为替换候选。[16] | 免费模式限 20 分钟；需比较付费选择；没有证据表明本项目中一定比 HeartCast 更稳定。[16] |
| HypeRate API | Watch/App → HypeRate 服务 → API 客户端 → Vexo | 面向直播/第三方集成提供心率 API，Indie API 可申请 key。[17] | 增加网络与服务依赖；当前两只本地可穿戴设备联动的 demo 不优先选择。后者是工程判断。 |

## 原生 Watch 直连：哪些能力已确认

- **心率入口**：在用户显式开启的 `HKWorkoutSession` 中，通过 `HKLiveWorkoutBuilder` 与 `HKLiveWorkoutBuilderDelegate` 接收新数据。需要 HealthKit 心率读取权限、workout 写入权限和 `workout-processing` 后台模式。Apple 表明活动 workout 可在用户放下手腕或使用其他 App 时继续接收传感器数据；必须提供清晰的开始、停止和保存/丢弃体验。[3]
- **蓝牙方向**：Watch 在此充当 **central**，Vexo 是 **peripheral**。与“让 Watch 广播成标准心率带”不同，不需要 Watch 实现 peripheral 广播。Apple 官方展示了 Watch 使用 `CBCentralManager` 连接 BLE 外设；`CBPeripheral.writeValue(_:for:type:)` 可写入外设特征。[4][11]
- **独立运行**：Apple 支持 Watch-only App，没有 iPhone 可执行程序，运行不依赖 companion App。因此“Watch 读取心率并直接给 Vexo 发指令”在框架层面有实现依据；这不等于该组合已在用户设备上验证。[5]
- **后台边界**：Watch 普通 BLE 后台扫描和及时通知有预算。Apple 建议在前台完成最初扫描、连接，再配置 `bluetooth-central`。这类后台唤醒与活动 workout 提供的执行时间是不同机制；公开文档不足以替代长期熄屏、离开 App、断连恢复和真实设备电量测试。[6][7]
- **开发安装**：通过 Xcode 在真实 Watch 运行开发版本，需要开发签名与开启 Developer Mode；后者涉及设备上的确认和重启。App Store/TestFlight 正常安装不要求用户开启 Developer Mode。[8][12]

## 对现有 Vexo 的具体含义

Vexo 使用自定义 BLE 服务，不能把它当作现成标准心率接收器直接和 HeartCast 配对。无论用 Mac、iPhone 还是 Watch，都需要程序把 BPM 翻译为 Vexo 的 LED 命令。[13]

只锁定 `Vexo-HACK-62` 和服务 `254f0001-df82-4a9c-a2b5-563a0f6b2021`。连接后订阅 TX 通知、用 `GET_INFO` 验证 `band_no == 62`，再写 LED 命令；任何时候都不能选“扫描到的第一只手环”。一个 Vexo 同时仅支持一个 BLE 连接，测试 Watch 直连前需要释放现有 Mac/Dashboard 连接。[13]

把最新有效 BPM 转为 `period_ms = round(60000 / BPM)`。初版采用每周期只亮 60 ms 的 `flash`；用户反馈不够直观后，已改为最大亮度的红色 `blink`：每周期前半亮、后半灭，仍保留真实心率节奏。历史初版 `heart_rate.py` 已实现此映射、BLE 通知超时停灯与会话清理，通过 23 项测试，并在真实 62 号读回确认 `blink` 与亮度 1.0。Apple Watch 经手机和 Mac 的实时链路已验证；HDS 尚未接入，其发送频率不同，不能直接沿用 BLE 通知的超时假设，见下节。[14]

**这叫“按最新心率节奏闪烁”，不能叫每一次真实心搏都精确同步。** Apple 的白皮书说明前台心率算法尝试约每 5 秒报告一个心率值，受信号质量影响；BPM 并不包含每个心搏发生的完整时间序列。闪灯会以最新 BPM 推算节奏，并存在测量和传输延迟。[15]

温度仅保留演示：Vexo 自身温度是芯片温度，不能标为用户皮温或体温。麦克风开启时 LED 会被固件固定为蓝色；心率红灯模式应关闭音频/音量流。低电量也会限制灯光或停止相关功能。[14]

后续用户确认使用同一颗可编程 RGB 灯同时展示心率和温度。已实现 `--temperature` 合并模式及 `start_bio_demo.command`：心率控制最大亮度的半亮半灭节奏，芯片温度每秒采样，首次读数为固定基线，默认升温 1°C 走完蓝→青→黄→橙→红色带。真实芯片温度变化与对应 LED 设置已读回确认；34 项测试通过，包含两种数据各自过期时停灯及恢复。它是相对芯片温度的视觉演示，不能作为人体温度变化测量。

## HeartCast 的使用与证据边界

官方 FAQ 描述 Watch 上启动会话后，由 iPhone 广播标准 Heart Rate Service（`0x180D`），设备通常显示为 HeartCast。首次发现时 iPhone App 需前台；已连接后厂商称可以让手机休眠。免费基础心率功能和可选 Audible/支持开发内购见官方 App Store 页面。需要的是 Logic Phase LLC 的 `id1499771124`，不能因应用重名装错。[1][2]

厂商声明心率不上传外部服务，同时披露 Google Analytics/Crashlytics 用于分析与崩溃诊断。前者是厂商声明，不是本项目完成的网络审计。公开产品说明不能证明其在当前 Watch/iPhone/macOS 组合上的端到端稳定性，仍需与 Watch/手机显示对照测试。[2]

## Mac 能否直接从 Apple Health 读取实时心率

Apple 官方明确：macOS 虽包含 HealthKit framework，但不能读取或写入健康数据，`HKHealthStore.isHealthDataAvailable()` 返回 `false`。2026-11-14 在当前 Mac（macOS 26.6.2）上用 Swift 调用该接口，实际也返回 `false`；这次只查询平台能力，未申请或读取健康数据。[18]

第三方 Mac 健康查看器可能通过手机同步副本。例如 Health Auto Export 的官方路径为 iPhone → iCloud → Mac，后台同步可能延迟，不能将它当作实时心率广播源。这并不否认 Mac 可以接收 BLE 心率或其他显式转发的数据，只是不能直接读取本地 HealthKit 来完成本项目。[19]

## HDS：现成 Watch App 直接向 Mac 发数据

**已核实的依据与边界**：App Store 作者的 12.0 发布说明明确说新增的 RTD（云）和 REST（本地）通信方式允许不连接手机使用；13.0 删除 Watch WebSocket 并将这两种方式设为默认。官方说明支持向指定 IP/端口发送数据，桌面仓库则提供本地 REST 接收实现。没有找到公开的 Watch App 本体源码，因而“不连接手机”是作者文档与服务端协议相互印证的能力，不能写成已审计 Watch 源码或已实机验证。[20][21][22]

官方配置步骤为在 Watch App 中关闭 **HDS Cloud**，输入 Mac 的局域网 IP 和端口，再从手表启动会话。默认端口是 `3476`，可修改；旧版文档的“REST Fallback”开关在 13.0 已成为默认，不应要求用户寻找已删除的选项。当前设备上的具体界面仍待安装后确认。Watch 需要自己连上可到达 Mac 的 Wi-Fi；在同一局域网是本地路径的起点，活动现场 Wi-Fi 若隔离客户端，即使网络名称相同也可能无法通信，这部分必须现场验证。安装或初始配置可能用到 iPhone，与心率运行时不经手机广播是两回事。[20][21]

已通过 GitHub 官方连接器读取作者当前 `hds_desktop` 服务端及 `hds_overlay` 消息解析代码，接入细节如下：[22][23][24]

| 项目 | 源码行为 |
|---|---|
| 监听 | `0.0.0.0:3476`；`--port` 可改变端口 |
| Watch → Mac | `PUT /`，请求体为 JSON；服务端读取其中的 `data` 字符串 |
| 心率消息 | overlay 按冒号分隔类型和值，类型枚举含 `heartRate`；由此对应的请求体示例为 `{"data":"heartRate:72"}`。这是代码推导示例，尚不是用户手表抓取的包 |
| Mac 客户端 | 官方桌面端将 `data` 原样发送到本机 `ws://localhost:3476/` 客户端；新 overlay 连接会替换旧连接 |
| 身份和时间 | 此路径未提供心率测量时间戳，接收处理也没有校验 Watch 身份或凭据；自有接收器需明确来源，并区分接收时间与测量时间 |

因此可实现一个兼容上述 `PUT` 的 Mac 接收器，直接复用 Vexo 控灯逻辑，无需运行官方 overlay 或把心率发到云。也可复用官方桌面程序，再由 Python 订阅本机 WebSocket；后者多一个本地进程且只能占用一个 overlay 连接。这是根据公开协议作出的实现判断，尚未编写或运行 HDS 接收代码。[22][23]

**心率只在变化时发送的限制需要先验证**：作者 8.0 发布说明写过只在心率或卡路里数值变化时发送。当前闭源 Watch 版本是否仍保留该行为，不能仅凭旧说明定论，但在实测前也不能假设每秒或每个测量样本都会发送。若数值长时间相同且不发送，原程序的“15 秒无新心率通知即停灯”会误判；若无限维持最后数值，又无法识别真实断流。应先捕获当前版本的完整消息节奏，确认是否有会话状态或其他周期消息，再定义停灯策略；有周期消息也不自动证明心率样本新鲜。HDS 的 `data` 心率格式本身不含样本时间戳。[20][22][23]

本轮没有购买 App、安装 Watch 软件、修改用户健康权限或建立 HDS 实机链路。现阶段只确认了一条更符合用户约束、具备公开本地接入协议的候选方案。

## 验证顺序

1. 确认真实 BPM 能进入程序，并保留接收时间；原生方案还应保留样本时间。来源明确标为 Apple Watch，不能自动切到现场其他人的心率设备。
2. 在 Vexo 62 上验证红色、周期与 BPM 对应关系，以及断流时熄灯。
3. 验证运行时无 iPhone 中转：HDS 路线让 Watch 自身连接可到达 Mac 的 Wi-Fi，断开手机后测试；原生路线验证 Watch 与 Vexo 直连。两条路线均需测试放下手腕、离开 App；原生开发版还要测试脱离 Xcode debugger 的运行状态。
4. 测试结束会话、摘表、蓝牙断开与恢复；验证不会无限重放最后一次旧心率。
5. 只有完成实际链路测量后，才报告更新间隔、延迟、可靠性和是否能独立离开 Mac 使用。

## 一手来源

1. [HeartCast FAQ & Support](https://www.heartcast.app/faq-help-support-issues/)
2. [HeartCast: Heart Rate Monitor — Logic Phase LLC，App Store](https://apps.apple.com/us/app/heartcast-heart-rate-monitor/id1499771124)
3. [Apple — Running workout sessions](https://developer.apple.com/documentation/healthkit/running-workout-sessions)
4. [Apple WWDC21 — Connect Bluetooth devices to Apple Watch](https://developer.apple.com/videos/play/wwdc2021/10005/)
5. [Apple — Creating independent watchOS apps](https://developer.apple.com/documentation/watchos-apps/creating-independent-watchos-apps)
6. [Apple — Using background tasks，Communicate over Bluetooth](https://developer.apple.com/documentation/watchkit/using-background-tasks)
7. [Apple WWDC22 — Get timely alerts from Bluetooth devices on watchOS](https://developer.apple.com/videos/play/wwdc2022/10135/)
8. [Apple — Enabling Developer Mode on a device](https://developer.apple.com/documentation/xcode/enabling-developer-mode-on-a-device)
9. [Apple WWDC23 — Build a multi-device workout app](https://developer.apple.com/videos/play/wwdc2023/10023/)
10. [Apple — workoutSession(_:didReceiveDataFromRemoteWorkoutSession:)](https://developer.apple.com/documentation/healthkit/hkworkoutsessiondelegate/workoutsession(_:didreceivedatafromremoteworkoutsession:))
11. [Apple — CBPeripheral.writeValue(_:for:type:)](https://developer.apple.com/documentation/corebluetooth/cbperipheral/writevalue(_:for:type:))
12. [Apple Xcode Help — Run an app on a device](https://help.apple.com/xcode/mac/current/en.lproj/dev5a825a1ca.html)
13. [Vexo Open Kit — Bluetooth contract explained](https://github.com/VexoAI-Org/vexo-open-kit/blob/main/docs/bluetooth-contract.md)，已核对本地同名文件。
14. [Vexo Open Kit — Protocol contract](https://github.com/VexoAI-Org/vexo-open-kit/blob/main/contract/contract.md)，已核对本地温度、LED、麦克风及低电量条款。
15. [Apple — Heart Rate, Calorimetry, and Activity on Apple Watch（2024-11）](https://www.apple.com/my/health/pdf/Heart_Rate_Calorimetry_Activity_on_Apple_Watch_November_2024.pdf)
16. [ECHO — Bluetooth Heart Rate Monitor，App Store](https://apps.apple.com/us/app/bluetooth-heart-rate-monitor/id1494679144)，由并行研究核对。
17. [HypeRate — API](https://www.hyperate.io/api)，由并行研究核对。
18. [Apple — HKHealthStore.isHealthDataAvailable()](https://developer.apple.com/documentation/healthkit/hkhealthstore/ishealthdataavailable())，已在当前 Mac 验证返回 false。
19. [Health Auto Export — Sync to Mac](https://help.healthyapps.dev/en/health-auto-export/sync-to-mac/)，由并行研究核对。
20. [Health Data Server — Aaron DeLory，App Store](https://apps.apple.com/us/app/health-data-server/id1496042074)，核对价格、12.0/13.0 通信方式说明及 8.0 仅变化时发送的历史说明。
21. [Rexios80/hds_desktop — README](https://github.com/Rexios80/hds_desktop/blob/master/README.md)，核对本地 REST/WebSocket 架构、关闭 HDS Cloud 与填写 Watch 端目标 IP 的步骤。
22. [Rexios80/hds_desktop — bin/hds_desktop.dart](https://github.com/Rexios80/hds_desktop/blob/master/bin/hds_desktop.dart)，核对监听端口、`PUT /`、JSON `data` 字段和单个本机 overlay 转发。
23. [Rexios80/hds_overlay — connection.dart](https://github.com/Rexios80/hds_overlay/blob/master/lib/services/connection/connection.dart)，核对 `类型:值` 消息解析。
24. [Rexios80/hds_overlay — data_type.dart](https://github.com/Rexios80/hds_overlay/blob/master/lib/hive/data_type.dart)，核对 `heartRate` 类型与 BPM 单位。
