# Mac → Apple Watch 主动震动：官方能力与实现边界

核查日期：2026-11-14（America/Los_Angeles）。本轮只读研究 Apple 官方文档与 WWDC，没有操作蓝牙、安装应用、启动服务或验证用户手表。目标是 dating demo 的匹配提醒，以及靠近时更频繁的触觉反馈。

## 可以直接实施的路线

**Mac 发布自定义 BLE 服务，Watch App 主动连接并订阅命令；Watch 在应用内调用系统触觉 API。运行时这条链路不需要 iPhone 转发。** Mac 使用 `CBPeripheralManager`，Watch 使用 `CBCentralManager`。Apple 明确支持前者在 macOS 发布服务、向订阅者发送 characteristic notification/indication；Watch 支持 central，但不能用 `CBPeripheralManager` 广播服务。因此角色必须是 Mac peripheral → Watch central。[Apple：CBPeripheralManager](https://developer.apple.com/documentation/corebluetooth/cbperipheralmanager)、[Apple：CBCentralManager](https://developer.apple.com/documentation/corebluetooth/cbcentralmanager)

需要安装我们自己的 Watch App，或一个已经实现相应命令接收功能的 Watch App。单靠 Mac 的蓝牙连接没有公开的 Apple Watch 通用“震动 characteristic”。这里的实现依据是 Watch 应用收到数据后调用 `WKInterfaceDevice.current().play(...)`；这是基于官方应用 API 作出的架构判断，不是已完成的实机链路。[Apple：play(_:)](https://developer.apple.com/documentation/watchkit/wkinterfacedevice/play(_:))

建议先实现这条最小流程：

1. Mac 广播一个项目专用 service UUID，发布通知特征；Watch 扫描该 UUID、连接、发现特征并 `setNotifyValue(true, for:)`。
2. Watch 显示连接来源与“测试震动”按钮；Mac 发送包含递增 command ID 的 `match` 或 `pulse` 命令，Watch 去重后在前台调用 `.notification` 或语义合适的系统 haptic。
3. 增加 Watch → Mac 的应用级 ACK，分别记录“收到命令”和“调用 haptic”；这两个状态均不能代替用户确认实际感觉到震动。
4. 真正后台收到首次 `match` 时，创建本地通知；用户打开 App 后再进入靠近反馈模式。不要把 BLE 后台唤醒当作持续震动的运行保证。

第 1 步使用 Apple 展示的连接与通知接口；command ID、ACK 和两阶段交互是本项目实现建议。[Apple WWDC22：Listen for alerts](https://developer.apple.com/videos/play/wwdc2022/10135/?time=221)

两端应配置 Bluetooth 使用说明 `NSBluetoothAlwaysUsageDescription`。若 Mac App 启用 App Sandbox，还需 Bluetooth entitlement。Watch 后台接收 BLE 时在 Watch target 的 Info.plist 加 `UIBackgroundModes = [bluetooth-central]`，不能只配置 iOS target。[Apple：Bluetooth 使用说明](https://developer.apple.com/documentation/bundleresources/information-property-list/nsbluetoothalwaysusagedescription)、[Apple：macOS Bluetooth entitlement](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.device.bluetooth)、[Apple WWDC22：后台配置](https://developer.apple.com/videos/play/wwdc2022/10135/?time=185)

## 前台、手腕放下与后台不能混为一谈

| 状态 | 官方证据与工程结论 |
|---|---|
| App 可交互前台 | `play(_:)` 是明确支持的路径，可先验证 Mac 命令触发一次震动。 |
| 刚放下手腕，App 仍是 frontmost | Apple 的 frontmost 文章明确列出可播放触觉；但 `play(_:)` 的 API 页又写 inactive 时无效。当前官方正文存在措辞冲突，因此必须在用户的 Watch/watchOS 上单独实测，不能承诺普通 BLE 回调在此状态一定会震动。 |
| 返回表盘、切到另一 App 或 frontmost 超时 | 普通后台 `play(_:)` 不生效；后台 BLE 唤醒可以处理事件并发本地通知，不能由此推导可随意调用触觉。 |
| 本 App 拥有活动 workout | `play(_:)` 明确允许的后台例外；但不能为 dating 功能凭空创建 workout 保活。 |

来源：[Apple：play(_:)](https://developer.apple.com/documentation/watchkit/wkinterfacedevice/play(_:))、[Apple：Taking advantage of frontmost app state](https://developer.apple.com/documentation/watchkit/taking-advantage-of-frontmost-app-state)。两页的当前官方 Markdown 正文也保留上述冲突。frontmost 文档说明用户可以调整 Return to Clock 时长，按 Digital Crown 或明确关闭 App 会使其进入后台；调长时长不等于获得无限后台执行。

`play(_:)` 使用系统定义的 haptic 类型，不接受任意振幅/波形参数。已经在播放时快速再次调用，会打断当前反馈，并有至少 100 ms 间隔；所以“每 0.1 秒发命令”不等于清晰的 10 Hz 感知脉冲。Apple 还提示触觉播放期间会暂停 HealthKit 的心率采样，这与本项目同时展示心率有关。[Apple：play(_:)](https://developer.apple.com/documentation/watchkit/wkinterfacedevice/play(_:))

## WWDC22 timely alerts 到底开放了什么

watchOS 9 引入：应用在前台建立连接并订阅特征后，系统可在应用停止运行时维持连接；特征变化时给应用一小段后台执行时间。Apple 的示例用途是本地通知或网络请求，视频没有宣布绕过 WatchKit 触觉 API 状态限制。后台通知应申请用户授权，并受其通知设置控制。[Apple WWDC22](https://developer.apple.com/videos/play/wwdc2022/10135/)、[Apple：通知授权](https://developer.apple.com/documentation/usernotifications/asking-permission-to-use-notifications)

视频明确的版本边界：Series 6 或更新硬件；watchOS 9 当时的后台执行机会预算为 5 次，扫描发现与特征更新共享预算，用户与 App 交互可重置。达到限制会退回较早的后台刷新行为；应处理 `LeGattNearBackgroundNotificationLimit` 和 `LeGattExceededBackgroundNotificationLimit`，不能把 2022 年的数值当作未来版本固定承诺。Apple 建议只发送时间敏感事件，不要用这种机制持续传周期数据。因此它适合偶发匹配提醒，不支持据此承诺在后台一路按距离高频震动。[Apple WWDC22：Limits](https://developer.apple.com/videos/play/wwdc2022/10135/?time=303)

`WKExtendedRuntimeSession` 的确允许屏幕关闭后继续蓝牙和 haptic，但官方只列 self care、mindfulness、physical therapy、smart alarm 四类，并要求按应用用途选择类型。Dating 不能因为需要执行时间就直接伪装成上述类型。`notifyUser(hapticType:repeatHandler:)` 是已运行、可调度的 smart-alarm 会话接口，会显示系统闹钟 UI，不是普通 BLE 应用的通用后台震动入口。[Apple：Extended runtime sessions](https://developer.apple.com/documentation/watchkit/using-extended-runtime-sessions)、[Apple：notifyUser](https://developer.apple.com/documentation/watchkit/wkextendedruntimesession/notifyuser(haptictype:repeathandler:))

现有 HeartCast 若拥有 workout，新 App 再开一个 workout 会发生冲突：Apple Watch 同时只允许一个 `HKWorkoutSession`，后开的会结束前一个。不能把另一个 App 的 workout 当作本 App 已获得后台 haptic 权限。[Apple：HKWorkoutSession](https://developer.apple.com/documentation/healthkit/hkworkoutsession)

## 真机安装与签名

Watch-only App 可以独立安装和运行，没有 companion iPhone executable；这支持运行时 Mac ↔ Watch 直连。开发安装仍需 Xcode 与手表完成配对，现行官方流程先配对 companion iPhone。[Apple：Independent watchOS apps](https://developer.apple.com/documentation/watchos-apps/creating-independent-watchos-apps)、[Apple：Device Hub](https://developer.apple.com/documentation/xcode/managing-your-simulated-and-physical-devices-in-device-hub)

1. Xcode → Settings → Apple Accounts 登录 Apple Account；工程选择 Watch-only App，配置唯一 Bundle ID、Automatic signing 和对应 Team。[Apple：构建与运行](https://developer.apple.com/documentation/xcode/building-and-running-an-app)
2. 将与 Watch 配对的 iPhone 连接 Mac，在设备上确认 Trust；通过 Xcode 的 Manage Devices / Device Hub（旧版 Devices and Simulators）完成开发配对并选择 Watch。实际入口依本机 Xcode 版本。[Apple：Device Hub](https://developer.apple.com/documentation/xcode/managing-your-simulated-and-physical-devices-in-device-hub)
3. 按 Xcode 提示在 iPhone 和 Watch 启用 Developer Mode；Watch 为设置 → 隐私与安全性 → 开发者模式，重启后确认开启。若开关不可见，先发起开发配对。涉及设备密码和重启，需用户在设备上完成。[Apple：Developer Mode](https://developer.apple.com/documentation/xcode/enabling-developer-mode-on-a-device)
4. Xcode 选择实体 Apple Watch 为目标后 Run；随后脱离 debugger 测试真实执行状态。较新系统完成配对后可无线调试，较旧组合可能仍依赖连接的 iPhone；不要把调试连接方式误称为 App 运行时数据中转。[Apple：Device Hub](https://developer.apple.com/documentation/xcode/managing-your-simulated-and-physical-devices-in-device-hub)

个人真机 demo 可先使用免费 Personal Team；Apple 列出的限制包括 10 个 App IDs、3 台设备、每设备 3 个 App，以及 7 天 provisioning profile，届时需重装开发版本。正式分发与 TestFlight 另需对应开发者计划。[Apple：Developer account overview](https://developer.apple.com/help/account/basics/about-your-developer-account)

## 本次需要验证的最小闭环

先验证“Watch App 可交互前台，Mac 单击一次，手表震动一次”，然后依次验证手腕放下、返回表盘、本地通知权限开启/关闭、断连重连与重复命令去重。记录每次 `applicationState`、BLE 接收、haptic 调用和用户感知。只有完成无 debugger 的实机验证，才将对应状态标为已跑通。

结论：**可以接通 Mac 直接 BLE 控制 Watch App 的前台震动；后台匹配通知有官方路径；后台连续变频震动仍有执行状态与预算限制。** 当前研究不证明已有运行代码或用户设备上已成功。

## 后续实现进度（同日）

- 已实现 `watch-haptics/VexoWatch.xcodeproj`，Watch-only、最低 watchOS 10，使用项目专用 BLE UUID，前台 Connect、通知接收、触觉调用、去重和 ACK。Swift 6 严格并发的完整 watchOS SDK 编译与链接通过；纯协议检查通过。
- Mac 的 `watch_haptics.py` 在 `127.0.0.1:8766` 提供独立控制服务；CoreBluetooth 已返回广播成功。`watch_buzz.py` 每次只提交一个事件，不自动重试。Mac 会拒绝未就绪手表、并发指令，超时和断连不重播；4 项离线测试通过。
- 用户已在 Xcode 完成 Apple Account 登录，选择 Personal Team 并生成 Apple Development 签名。用户确认已连接的 iPhone 17 Pro 是目标 Watch 的配对手机。
- 当前尚未安装至实际 Watch，也未验证真实触觉。Xcode 正在下载 watchOS 平台组件，配对 iPhone 的 Developer Mode 开启步骤等待用户完成。编译通过和 Mac 广播成功不能算作端到端验收。
