# Wingman PRD — Holly：手机伴侣页 + 大屏 + Demo

**负责人：** Xiya (Holly) Tang  
**范围：** `/web` 手机伴侣页、大屏 Room View、视觉风格、demo 讲稿与排练  
**依赖：** [接口约定](contract.md)；手环和后端由 Will 负责（见 [Will 的 PRD](prd-will-backend.md)）  
**总 PRD：** [PRD.md](../PRD.md)（v6：dating，两个手环，同一个手势，资料来自真实账号和品味）

---

## 1. 目标

核心体验在**两个手环**上：三观合 → 两个手环一起闪紫 → 各自单击说 yes → 快闪、互相找 → **面对面做同一个手势**（具体手势待硬件测试后确定） → 一起变绿 → 听到开场白。

你负责让这个过程**看得懂、有仪式感**：
1. 每个人的手机上能看到"为什么我们三观合"，听到开场白
2. 大屏上让评委和观众看清楚两个手环发生了什么
3. 讲好 3 分钟的故事

所有页面都要能在**没有后端**的情况下用假数据走完。

## 2. 不在范围内

- 手环蓝牙、LED、动作识别、Deepgram、Gemini、ElevenLabs（Will 负责）
- 账号、照片、摄像头

## 3. 手机伴侣页（`/web?band=A` 或 `?band=B`）

### Screen A — 加入（Join）：连接你的真实品味

顶部文案：**Show us the real you.** 副标题：Connect at least two.

**第一部分：来源卡片（至少连 2 个）**

| 来源 | 形式 | 说明文案 |
|---|---|---|
| 🎬 Letterboxd | 用户名输入框 | We read your public ratings |
| 👽 Reddit | 用户名输入框 | We read your public posts and subreddits |
| 🎵 TikTok | 上传 2–4 张截图 | Screenshot your Favorites or Liked tab |
| 📷 Instagram | 上传 2–4 张截图 | Screenshot your Saved or Following |
| 🎧 Spotify（P1） | 歌单链接 | A public playlist that's very you |

- 截图在前端压缩（长边 1280px、JPEG 质量 0.7），显示缩略图，可以删除
- 每张卡片连上后显示 ✓

**第二部分：三个快速字段**：名字、在找什么（三选一）、一个底线

**第三部分：两个勾选框**：同意被配对；同意 Wingman 读取我连接的内容（仅本次活动）

- **JOIN** → 发送 `join`（格式见 [接口约定](contract.md)）
- **验收：** 少于 2 个来源或没勾选同意时不能提交；截图压缩后每张不超过 300KB

### Screen A2 — 我们读到了你什么（What we picked up）

- 收到 `profile_ready` 后显示：
  - **Your core**：`kind: theme` 的条目，大字，下面一行小字 "because …"
  - **You seem drawn to**：`kind: drawn_to` 的条目
  - **Specifics**：每条 highlight 一行，带来源图标
  - 每一条右边都有 ✕ 可以删除
- `failed_sources` 里的来源显示"没读到，已跳过"，不阻塞流程
- **LOOKS LIKE ME** → 发送 `profile_confirm { removed }`
- 等待期间显示"正在读你的 Letterboxd…"这类逐个来源的进度文案
- **验收：** 删除的条目不会出现在之后的配对理由里

### Screen B — 发光（Glow）

收到 `state_changed: matched` + `match_found` 时显示：

- 标题：**Your band is glowing ✦**
- 副标题：Someone here gets your taste.
- 先显示 `core_overlap`（✦ You're both drawn to …），`type_fit` 为 true 时加一行 "✦ You're each other's type"
- 然后 `shared_specifics` 一条一行，带来源图标（比如 🎬 You both gave Past Lives 5★），下面是 `reason`，依据 `evidence` 可以折叠
- 操作说明（大字）：**单击手环 = 愿意认识，双击 = 跳过**
- 收到 `decision_status {you_said_yes: true}` → 显示"你已经说了 yes，等对方…"
- **不显示**对方名字、照片、匹配度
- **验收：** 理由完整显示；操作说明一眼能看懂

### Screen C — 互相找（Find）

收到 `state_changed: mutual` 时显示：

- 标题：**✦ You both said yes ✦**
- 说明：Look around for the other purple light.
- **手势提示（这一页的重点）**：一个循环播放的小动画，演示 `match_gesture`
- **手势还没定**：动画、手势名称和文案都从配置里读（比如 `web/config/gesture.json`），最后定下哪个手势，换配置就行，先用占位动画开发
- 文案：**When you meet, make the gesture together.**
- 小字：Both of you, at the same time.
- **验收：** 没看过 demo 的人看动画就知道要做什么动作

### Screen D — 配对成功（The Spark）

收到 `state_changed: meeting_confirmed` 时：

- 绿色光圈 + 成功动画 + **"You found each other. Meet {name}."**
- 收到 `whisper_ready` → **▶ HEAR YOUR OPENER**，点击播放（浏览器要求用户手势才能播放）
- **验收：** iPhone Safari 上能播放音频

### Screen E — 保持联系（Stay in Touch）

- "Want to stay in touch?" → **YES**（填 Instagram / 手机号）/ **No thanks** → `stay_in_touch`
- 收到 `contact_exchanged` → 显示对方联系方式 + 第二次约会建议
- 对方没选 yes → 只显示 "Thanks for meeting!"
- **验收：** 只有双方都 yes 才显示联系方式

### 被拒或超时

- 收到 `passed` 或 `expired` → **完全一样的文案**："No match right now. We'll keep looking."

### 全局

- 页面由 `state_changed` 驱动；断线自动重连
- 右上角常驻 **Hide** → `hide`
- 第一次进入时一句话说明："只有你们俩都说 yes，手环才会开始互相找。"

## 4. 大屏 Room View（`/web/room`，P1，demo 很加分）

投在大屏幕上给评委和观众看：

- 左右两个大圆，分别代表手环 A 和手环 B，**颜色和闪烁节奏与真实 LED 同步**（来自 `room_update`）
- 中间显示当前阶段：Matching → Glow → Both said yes → Find each other → ✦ Spark ✦
- `matched` 时显示两人共同的价值观（不显示各自的私人答案）
- `mutual` 时显示手势动画
- 确认配对时，两个圆同时变绿并向中间靠拢合成一个
- **验收：** 坐在后排的评委也能看懂现在发生了什么

## 5. 视觉与措辞

- 温暖、亲密、编辑感、高级感；深色背景，柔和渐变，圆形动效
- **紫色慢闪 = 发现，紫色快闪 = 互相找，绿色 = 配对成功**，和手环一致
- **绝对不要**做成左滑右滑的卡片堆或聊天界面
- 核心文案：*Values first. Then you meet.*

## 6. Demo（3 分钟）

Holly 戴手环 A，评委（或 Will）戴手环 B。

| 时间 | 内容 | 谁操作 |
|---|---|---|
| 0:00–0:30 | 问题：刷了几百张照片却很少见面；见了才发现三观不合 | Holly 讲 |
| 0:30–1:00 | Holly 对着手环说自己在乎什么；评委在手机上答 4 个问题。没有照片 | Holly + 评委 |
| 1:00–1:40 | 两个手环一起闪紫，大屏显示共同价值观 → 两人各单击一次 → 变快闪 | 两人 |
| 1:40–2:10 | 两人站在房间两头，靠紫光找到对方 | 两人 |
| 2:10–2:40 | 面对面一起做配对手势 → **两个手环同时变绿** → 播放开场白 | 两人 |
| 2:40–3:00 | 收尾："约会软件的终点是配对，Wingman 的终点是一场真实的对话" | Holly 讲 |

- 讲的时候强调三点：**没有照片**、**双方都说 yes 才开始找**、**两个人同时做同一个动作才算配对**
- 提前准备好评委的答案，保证和 Holly 三观合
- 排练配对手势，确保两个人做得够明显
- 准备一份录屏备用

## 7. 优先级与时间

| 优先级 | 任务 | 什么时候完成 |
|---|---|---|
| P0 | Screen A → B → C → D 用假数据走通 | 集成点 1 之前 |
| P0 | 接上真后端，`whisper_ready` 能播放 | **集成点 1** |
| P0 | Screen C 的手势提示动画 | 集成点 2 |
| P1 | 大屏 Room View | 集成点 2 之后 |
| P1 | Screen E 保持联系 | 集成点 3 之后 |
| P1 | 视觉打磨、动效 | 集成点 3 之后 |
| — | **冻结，只排练** | 交作品前 1–1.5 小时 |

## 8. 完成标准

一位没看过产品的评委戴上手环、扫码答题，在不需要讲解的情况下，看手机就知道什么时候点手环、什么时候做配对手势，并且能说出"系统为什么觉得我们三观合"。
