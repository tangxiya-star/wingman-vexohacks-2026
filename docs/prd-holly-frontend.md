# Wingman PRD — Holly：手机端体验 + Demo

**负责人：** Xiya (Holly) Tang  
**范围：** `/web` 手机网页、视觉风格、Wingman 标记、demo 讲稿与排练  
**依赖：** [接口约定](contract.md)；后端由 Will 负责（见 [Will 的 PRD](prd-will-backend.md)）  
**总 PRD：** [PRD.md](../PRD.md)（v4，dating）

---

## 1. 目标

让一个评委拿起手机，**不需要讲解**，就能完成：回答几个价值观问题 → 看到"为什么你们三观合" → 双方都说 yes → 用摄像头找到对方 → 碰一下 → 听到开场白。

评委要能感受到两件事：
1. **不看脸**：全程没有照片，配对只看三观
2. **一定会见面**：从配对到面对面说话只要两分钟，不是在线上聊天

整条体验要能在**没有后端、没有震动、没有碰撞检测**的情况下照样走完（用假数据和后备按钮）。

## 2. 不在范围内

- 手环蓝牙、LED、Deepgram、Gemini、ElevenLabs（Will 负责）
- 账号、登录、持久化存储
- 照片上传、人脸识别

## 3. 页面与需求

### Screen A — 加入（Join）

顶部文案：**No photos. Just you.**

| 字段 | 必填 | 形式 |
|---|---|---|
| 名字 | 是 | 输入框 |
| 理想的周末是什么样 | 是 | 一行 |
| 你现在最在乎的是什么 | 是 | 一行 |
| 你在找什么 | 是 | 三选一：something serious / open to see / new friends |
| 你绝对不能接受的一件事 | 是 | 一行 |
| 一句话介绍自己 | 否 | 一行 |
| 同意在本次活动中被配对 | 是 | 勾选框，不勾不能提交 |

- 按钮：**FIND MY PERSON** → 发送 `guest_join`
- 提交后显示等待动画，等后端推送 `match_found` 或 `no_match`
- **验收：** 漏填必填项时按钮不可点；整个页面没有任何上传照片的入口

### Screen B — 配对结果（Match）

- 标题：**Someone here shares your values**
- 正文：`shared_values` 一条一行（比如"你们都把家人放在第一位"），下面是 `reason`
- 小字：依据 `evidence`，可以折叠
- 问题：**Want to meet?**
- 按钮：**YES** → `guest_decision {yes: true}`；**Not now** → `guest_decision {yes: false}`
- 有震动的设备震一下；没有震动的设备用脉冲动画代替
- **不显示**对方照片、匹配度百分比或任何分数
- **验收：** 理由完整显示；iPhone 上（没有震动）也有明显的视觉提示

### Screen B2 — 等待对方（Waiting）

- 文案："Waiting for them to say yes…"
- 收到 `state_changed: mutual` → 自动进入 Screen C
- 收到 `state_changed: passed` → 显示 "No match right now. We'll keep looking."，**不能暗示被拒**
- **验收：** 两种结果都能正确跳转，被拒时的文案和"没有配对"完全一样

### Screen C — 找人（The Hunt）

- **只有在 `mutual` 状态下才能进入**
- 按 **FIND THEM** → 发送 `find_start`，打开后置摄像头（`getUserMedia`，`facingMode: environment`）
- 用 **jsQR** 在本地逐帧识别 Wingman 二维码，不依赖网络
- 三种状态：

| 状态 | 画面 | 发送事件 |
|---|---|---|
| 扫描中 | 平静的扫描动画，"Look for the glowing badge" | — |
| 锁定 | 目标光圈套住二维码 + 强震动，"FOUND THEM" | `target_locked` |
| 丢失 | 回到扫描动画 | `target_lost` |

- 底部常驻按钮：**I found them**（摄像头不可用时的后备）
- 摄像头权限被拒 → 显示说明和后备按钮，不卡死
- **验收：** 在比赛场地的灯光下，3 米内能识别打印的二维码

### Screen D — 见面（The Spark）

- 提示："用手机轻碰对方的手环"
- 用 `DeviceMotionEvent` 检测加速度峰值（阈值先定 2.5g，现场再调），检测到后发送 `phone_bump`
- iOS 需要先点按钮请求运动权限（`DeviceMotionEvent.requestPermission()`）
- 后备按钮：**确认见面** → `confirm_fallback`
- 收到 `meeting_confirmed` → 绿色光圈 + 成功动画 + **"You found each other. Meet {name}."**
- 收到 `whisper_ready` → 显示 **▶ HEAR YOUR OPENER**，点击播放 `audio_url`（浏览器要求用户手势才能播放音频）
- **验收：** 没有运动传感器也能用后备按钮走完；音频能在 iPhone Safari 上播放

### Screen E — 保持联系（Stay in Touch）

- 文案："You met {name}. Want to stay in touch?"
- **YES** → 让用户填一个联系方式（Instagram / 手机号），发送 `stay_in_touch {yes: true, contact}`
- **No thanks** → `stay_in_touch {yes: false}`
- 收到 `contact_exchanged` → 显示对方的联系方式 + 一条第二次约会的建议
- 如果对方没选 yes → 只显示 "Thanks for meeting!"，不透露对方的选择
- **验收：** 只有双方都选 yes 时才显示联系方式

### 全局

- 所有页面都由 `state_changed` 驱动；断线自动重连，并显示"重新连接中"
- 收到 `error` 时，如果 `retry: true` 显示重试按钮
- **右上角常驻 Hide 按钮** → 发送 `hide`，立即退出配对
- 第一次进入时，用一句话说明安全规则："只有双方都说 yes，对方才能找到你。"

## 4. 视觉与措辞

- 温暖、亲密、编辑感、高级感
- 深色背景，柔和渐变，圆形动效
- **紫色 = 发现，绿色 = 见面成功**，和手环 LED 一致
- **绝对不要**做成左滑右滑的卡片堆，也不要聊天界面
- 核心文案：*Values first. Then you meet.*

## 5. 实物

- 打印 2 份 Wingman 二维码徽章（A6 大小，加粗边框），戴手环的人别在胸前
- 二维码内容：`wingman:demo`

## 6. Demo（3 分钟）

| 时间 | 内容 | 谁操作 |
|---|---|---|
| 0:00–0:30 | 问题：我们刷了几百张照片却很少见面；见了面才发现三观不合 | Holly 讲 |
| 0:30–1:00 | Holly 对着手环说自己在乎什么，没有照片 | Holly |
| 1:00–1:40 | 嘉宾在手机上答价值观问题 → 配对 + 理由 → Holly 点手环说 yes → 嘉宾点 yes | 嘉宾 + Holly |
| 1:40–2:10 | 嘉宾打开摄像头找到 Holly 的徽章 | 嘉宾 |
| 2:10–2:40 | 手机碰手环 → 变绿 → 播放开场白 | 嘉宾 |
| 2:40–3:00 | 收尾："约会软件的终点是配对，Wingman 的终点是一场真实的对话" | Holly 讲 |

- 讲 demo 时要强调两次：**全程没有照片**、**双方都说 yes 才能找人**
- 提前准备好嘉宾的答案，和 Holly 的资料确实三观合，保证配对成功
- 准备一份录屏备用，现场网络或硬件出问题时播放

## 7. 优先级与时间

| 优先级 | 任务 | 什么时候完成 |
|---|---|---|
| P0 | A → B → B2 → D 用假数据走通 | 集成点 1 之前 |
| P0 | 接上真后端：`whisper_ready` 能播放 | **集成点 1** |
| P0 | 双方 yes 的逻辑（B、B2） | 集成点 2 |
| P0 | Screen C 摄像头 + jsQR | 集成点 2 之前 |
| P0 | 所有后备按钮、Hide 按钮 | 集成点 2 |
| P1 | 碰撞检测 | 集成点 3 |
| P1 | Screen E 保持联系 | 集成点 3 之后 |
| P1 | 视觉打磨、动效 | 集成点 3 之后 |
| — | **冻结，只排练** | 交作品前 1–1.5 小时 |

## 8. 完成标准

一位没看过产品的评委，用自己的手机扫码进入，在不需要讲解的情况下完成整个流程，并且能说出"系统为什么觉得我们三观合"。
