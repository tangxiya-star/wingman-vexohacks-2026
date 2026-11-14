# WHOOP 主动震动：非官方 BLE 接口核实

调查日期：2026-11-14。前半部分来自公开源码和项目维护者记录；用户随后授权的现场连接测试另记于文末。未安装第三方应用。

## 结论

**WHOOP 主动震动存在可用的非官方实现，不能从“官方 API 没有震动接口”推出“WHOOP 做不到”。** 当前 NOOP 源码有 WHOOP 5.0/MG 专用震动编码，并明确记录真实 MG 单次震动及重复次数的硬件验证。现场这台 Mac 于 14:33:24 成功获得控制应答，WHOOP 5.0 返回一次短震完成和停止成功；用户随后确认“感觉到了，震了一下”。仅成功接收标准心率广播不代表已获得私有控制通道。

## 可核对的证据

| 问题 | 一手来源结论 |
| --- | --- |
| 5.0/MG 能否主动震动？ | NOOP `MaverickHaptics.notificationBuzz` 明确使用 `RUN_HAPTIC_PATTERN_MAVERICK`，命令 19 / `0x13`，12 字节参数。文件标明该 buzz 在真实 MG 上确认；维护者记录用户 `@dwehrmann` 实测重复字节为 3 时震动 4 次。[源码及实机归因](https://github.com/ryanbr/noop/blob/2a1de7609843b095505274ad6fc811757210be80/Packages/WhoopProtocol/Sources/WhoopProtocol/HapticPayloads.swift#L12-L44) |
| 能否重复、停止？ | 单次参数包含 revision、8 个效果字节、2 字节 effect-loop control 和 1 字节整体重复次数。N 次脉冲编码为 N−1；当前 helper 限定 1–8 次。停止命令是 122，5/MG 参数为 revision 1，需区分 pending 与最终结果。[协议说明](https://github.com/ryanbr/noop/blob/2a1de7609843b095505274ad6fc811757210be80/docs/PROTOCOL_COMMANDS.md#L344-L358) |
| 是否只是写在文档中？ | 当前 BLEManager 实际将旧调用重映射到 5/MG 的 `0x13`，调用上述 helper，再以 puffin 帧经 CoreBluetooth 写入设备。[发送路径](https://github.com/ryanbr/noop/blob/2a1de7609843b095505274ad6fc811757210be80/Strand/BLE/BLEManager.swift#L2433-L2460) |
| 4.0 和 5.0 是否相同？ | 不同。5/MG 的 opcode、参数和帧格式都不同。源码记录真实 MG 曾拒绝旧命令 79，因此不能把 WHOOP 4 的示例原样发给 5/MG。[代际差异和拒绝记录](https://github.com/ryanbr/noop/blob/2a1de7609843b095505274ad6fc811757210be80/Strand/BLE/BLEManager.swift#L2433-L2443) |
| 有无其他语言实现？ | `whoop-rs` 提供 `buzz(loops)`，按设备代际选用 79 或 19；另有 `stop_haptics()`。这证明存在可参考实现，不能将其视为第二份独立实机验证。[Rust buzz](https://github.com/eugenehp/whoop-rs/blob/36e5be95e67e4f9eb78a1af062ee3fa26bdd8221/src/whoop_client.rs#L1172-L1195)、[Rust stop](https://github.com/eugenehp/whoop-rs/blob/36e5be95e67e4f9eb78a1af062ee3fa26bdd8221/src/whoop_client.rs#L1451-L1459) |

## Mac 与现有手机连接：尚需验证的部分

NOOP 的历史问题记录区分标准心率广播与加密配对：心率可以在未完全配对时收到，buzz、闹钟等控制能力需要真正的配对。因此当前 Mac 的实时 BPM 成功不能证明震动可写。[v1.45–1.46 连接问题记录](https://github.com/ryanbr/noop/blob/2a1de7609843b095505274ad6fc811757210be80/CHANGELOG.md#L2775-L2806)

项目的发行说明要求释放官方手机 App 的配对，并说明转移配对后官方 App 可能需要重新配对。[发行仓库的配对说明](https://github.com/app-noop/noop/blob/34a86ce3e303548f8280d52351f7790d28e7c447/README.md#L105-L131)

**Mac 直接控制的证据存在冲突，不能承诺即插即用。** 项目共享 Swift/CoreBluetooth 源码包含震动发送路径，但当前代码中又保留“macOS 无法完成 5/MG 所需认证配对”的说明（针对配置命令）；旧文档也曾给 Mac 提供配对指导。共享代码能编译不等于这台 Mac 已可完成认证。应先验证这只设备实际暴露的服务、固件、控制通道响应及一次实体短震，而不是据此断言所有 Mac 都可以或都不可以。[当前 Mac 限制注释](https://github.com/ryanbr/noop/blob/2a1de7609843b095505274ad6fc811757210be80/Strand/BLE/Commands.swift#L176-L186)

## 对本次 dating demo 的含义

- “候选匹配后震动一下”有明确实现依据，值得进入单次短震的实机验证。
- “越近震动越快”可以尝试由应用安排短震之间的间隔，这是基于可触发短震的工程推断；当前证据没有证明任意毫秒节奏、最小可靠间隔或高频连续控制。不要把重复次数控制误称为已验证的任意频率控制。
- 协议说明要求避免重叠触发；接受命令、返回成功、实际佩戴者感到震动是不同证据。先验证单次、停止及不同间隔，再接距离驱动。[完成状态与忙碌行为](https://github.com/ryanbr/noop/blob/2a1de7609843b095505274ad6fc811757210be80/docs/PROTOCOL_ALARMS.md#busy-execution-and-stop-completion)
- 当前在线的 WHOOP 心率 → 网页 / Vexo 77 链路未被本次调查修改。任何重新配对方案都应先说明会中断什么，再做设备操作。

## 现场首次控制尝试（2026-11-14）

用户随后授权在朋友的 WHOOP 上尝试一次短震。已通过标准 Device Information 读回确认设备为 WHOOP 5.0、序列号已在本机核对（仓库省略标识）、固件 `50.43.2.0`、硬件 `WG50_r45`；Mac 能发现 `fd4b0001` 私有服务及写入/通知特征。

`whoop_buzz.py` 首先核对 UUID 和读回序列号，再用 `response=True` 发送已验证编码的 `CLIENT_HELLO`。本次握手返回 `BleakGATTProtocolError (15): Insufficient Encryption`，程序在订阅私有通知和发送震动之前退出。因此本次尚未发出震动，也不能证明 Mac 永远无法控制；需手环进入配对模式后再验证。

脚本默认只读，只有显式 `--buzz` 才尝试一次短震。不会自动重复震动；一旦短震写入尝试开始，退出前会尝试发送停止命令。协议编码测试 4 项、脚本身份/握手/超时退出测试 3 项通过，均为离线验证。

### 后续握手与配对状态

- 14:29:14，用户关闭配对 iPhone 蓝牙后，读回同一序列号，再次写 `CLIENT_HELLO`，仍返回 ATT 15 / `Insufficient Encryption`。没有订阅私有通知或发送短震。
- 14:29:39，用户一度报告只看到蓝灯，重试结果相同。随后用户澄清看不到 WHOOP 侧面的配对灯，因此不能把这轮视为已可靠确认持续蓝闪配对模式后的失败。
- Mac 系统设置的已配对及附近设备列表没有显示目标 WHOOP，未进行手动配对或删除配对记录。未修改闹钟。
- 配对时应释放所有现有 WHOOP 连接；NOOP 记录了保持连接会阻止进入配对模式的问题。当前保留 `./start_whoop_vexo.command --no-heart-rate` 运行 HTTP 面板和 Vexo 77 动作监测，只暂停 WHOOP 心率接收。恢复心率需要按现场联动测试安排切换，避免打断两只 Vexo 的动作验收。

上述失败均发生在私有握手阶段；不能据此断言所有 Mac 无法控制 WHOOP。

### 持续蓝闪后控制成功（14:33）

用户明确确认 WHOOP 侧面持续闪蓝后，在已暂停心率自动连接的情况下重试。目标序列号、型号和固件再次读回一致。此次流程成功：

```text
14:33:24 CLIENT_HELLO ATT write confirmed
14:33:24 cmd=19 request=2 result=pending body=010100
14:33:24 cmd=19 request=2 result=success body=010500
14:33:24 cmd=122 request=3 result=pending body=010000
14:33:24 cmd=122 request=3 result=success body=010000
```

仅发送一次短震，零次重复，随后发送停止，脚本正常退出并断连。用户随后明确确认“感觉到了，震了一下”，证明这台 Mac 对这只 WHOOP 5.0 的主动短震控制已通过实机验证；其他硬件、连续调频和每次重连是否均无需再次配对尚未验证。网页和 Vexo 62/77 动作监测未为这轮成功测试重启。用户明确选择“现在恢复心率”后，于 14:34:08 启动原 `./start_whoop_vexo.command`，保留 `--band 77 --raise-hand`。

恢复验证：HTTP `/api/motion` 确认 62 和 77 均 `connected=true`、`ready=true`。用户戴回 WHOOP 后，14:35:22 起收到持续更新的真实心率，77 的日志恢复对应分档周期、100% 亮度和蓝色输出。当前面板已恢复正常心率接收，不再使用 `--no-heart-rate`。

### 第二次按需短震（14:37）

用户要求“再震一次”。保持既有 `whoop_dashboard.py` 进程运行，再次执行序列号核对、握手、一次短震和停止。14:37:20 收到 cmd 19 `success / 010500` 及 cmd 122 `success / 010000`。此次没有重新操作蓝灯配对，也没有重启心率面板或 Vexo 连接。这验证了当前已配对状态下的再次控制；本次实体体感尚未单独确认。

### 一次约 1 秒长震（14:40）

用户要求一次约 1 秒的长震。NOOP 的 [WHOOP 5/MG 硬件文档](https://github.com/ryanbr/noop/blob/2a1de7609843b095505274ad6fc811757210be80/docs/PROTOCOL_WHOOP5.md#L28-L41) 指向 TI DRV2625；[TI 原厂数据手册](https://www.ti.com/lit/ds/symlink/drv2625.pdf) §9.1.1 将 effect 16 定义为 `1000 ms Alert 100%`。采用 cmd 19 body `01 10 00 00 00 00 00 00 00 00 00 00`，单个效果、零重复，没有拼接短震。

新增 `whoop_buzz.py --buzz --pattern one-second`，默认 `notification` 保持原短震。两份相关离线测试共 9 项通过，覆盖长震成功、超时不重试以及退出停止。

14:40:50 实机返回 cmd 19 `success / 010500`，随后 cmd 122 `success / 010000`；用户明确确认“是，明显更长，接近 1 秒”。这是该设备上的体感验证，并非仪器测得精确 1000 ms。此次未中断 WHOOP 心率面板和两只 Vexo 的动作接收。
