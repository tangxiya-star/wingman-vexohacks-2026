# VexoWatch

独立 Apple Watch App，通过 BLE 接收 Mac 的事件，在 App 前台调用系统触觉。最低 watchOS 10，无第三方依赖。

## 安装与演示

1. 用 Xcode 26.2 打开 `VexoWatch.xcodeproj`，选择共享 scheme **VexoWatch**。
2. 在 Signing & Capabilities 选择你的开发者 Team，选择已配对并启用开发者模式的 Apple Watch，运行安装。
3. 在手表打开 VexoWatch，点 **Local haptic test** 检查本地触觉。
4. 启动项目里的 Mac haptics 服务，手表点 **Connect to Mac**，允许蓝牙权限。
5. 等到 **Ready for Mac**，保持 App 打开，再从 Mac 发送事件。

只扫描指定 Vexo haptics 服务。断线后手动点 Connect，不自动重连、补发或播放历史事件。App 离开 active 状态后撤销 ready；恢复 active 后重新宣布 ready。App 内存中的 `(session, sequence)` 收件记录跨断线保留，后台收到的事件也会记录，恢复前台不会补震。

`ACK 0` 表示已调用 WatchKit 的 `play`，不代表佩戴者已经确认触觉。此 App 不创建 Workout session，也不读取或修改 HealthKit / HeartCast。本演示在非 active 状态主动忽略指令；手腕放下和后台提醒需另做实机验证，参见 [能力边界](../docs/research/apple-watch-haptics.md)。

## Mac 控制

从 `VEXO Hackathon` 根目录运行，使用独立的本地端口 8766，不重启 8765 面板：

```sh
.venv/bin/python -u watch_haptics.py
```

手表显示 `Ready for Mac` 后，另一个终端可发送一次系统触觉：

```sh
.venv/bin/python watch_buzz.py --kind notification
```

`--kind` 可选 `notification`、`click`、`success`。这是系统预设效果，不是任意毫秒时长控制。服务不会在启动、连接、重连时自动发震动；没有就绪的 Watch 时拒绝发送。每次只允许一个待确认指令，4 秒超时后不重试、不积压到重连后播放。

`GET http://127.0.0.1:8766/status` 查看连接状态。`POST /buzz` 接受 `{"kind":"notification"}`，需要 `X-Vexo-Token` 请求头；本次启动令牌保存在仅当前用户可读的 `runtime/watch_haptics.token`，不要提交或共享该文件。`play_called` 只表示 Watch 报告调用了触觉 API。

## 协议

| 属性 | UUID / 字节 |
| --- | --- |
| Service | `b41732d0-b80c-430b-ad6c-88af4eacb5e3` |
| Mac → Watch notify | `d50f9664-4e1e-4662-ac29-b1336546f6e5` |
| Watch → Mac write with response | `b35fe0ba-1cf7-4c2e-a4c2-d20484c2a309` |
| Ready / pause | `01 00` / `01 ff` |
| Command，10 bytes | `version=1: UInt8, kind: UInt8, session: UInt32LE, sequence: UInt32LE` |
| Kind | `1=notification, 2=click, 3=success` |
| ACK，11 bytes | 原 command 10 字节，加 `0=play已调用 / 1=重复忽略 / 2=非active忽略` |

Ready 必须在 notify 订阅成功后发送。所有 response 写入串行使用 `.withResponse`。无效长度、版本或 kind 不触发震动。BLE delegate 使用主队列，与 `@MainActor` UI 状态同步；项目启用 Swift 6 严格并发检查。

## 构建验证

从本目录运行，不需要连接或操作手表：

```sh
xcodebuild -project VexoWatch.xcodeproj -scheme VexoWatch \
  -configuration Debug -destination 'generic/platform=watchOS' \
  -derivedDataPath build CODE_SIGNING_ALLOWED=NO build
```

若 Xcode 提示需要下载 watchOS platform，先在 Xcode Settings → Components 安装。当前机器已用现有 watchOS 26.2 SDK 完成不依赖 destination 的完整编译、链接和 bundle 验证：

```sh
xcodebuild -project VexoWatch.xcodeproj -target VexoWatch \
  -configuration Debug -sdk watchos CODE_SIGNING_ALLOWED=NO \
  SYMROOT="$PWD/build/Products" OBJROOT="$PWD/build/Intermediates" build
```

未签名产物：`build/Products/Debug-watchos/VexoWatch.app`。安装到真机仍需开发签名。

纯协议检查在 Mac 上执行，不启动蓝牙：

```sh
mkdir -p build
xcrun swiftc -swift-version 6 -module-cache-path build/ModuleCache \
  VexoWatch/HapticCommand.swift Tests/ProtocolChecks.swift \
  -o build/protocol-checks
./build/protocol-checks
```
