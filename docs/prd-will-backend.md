# Wingman PRD — Will：手环 + 后端 + AI

**负责人：** Will Li  
**范围：** `/console` 手环控制台、`/server` Mastra 后端与 WebSocket、Gemini / ElevenLabs / Deepgram 集成  
**依赖：** [接口约定](contract.md)；手机端由 Holly 负责（见 [Holly 的 PRD](prd-holly-frontend.md)）  
**总 PRD：** [PRD.md](../PRD.md)（v4，dating）

---

## 1. 目标

让**真实的硬件事件真实地改变体验**：手环闪紫 → 戴手环的人点一下说 yes → 嘉宾找过来碰一下 → 手环变绿 → 播放 AI 根据双方三观生成的开场白。

两条原则必须在后端守住：
1. **配对只看三观，不看外貌**
2. **双方都说 yes 之前，谁都不能被找到**

整个流程可以反复演示，不需要手动修后端。

## 2. 不在范围内

- 手机端页面、摄像头识别、动效（Holly 负责）
- 账号、数据库、多人多手环
- 照片、人脸识别、自动录音或持续监听

## 3. 模块与需求

### 3.1 手环控制台 `/console`（第一个做，风险最大）

- 通过 Chrome 的 Web Bluetooth 连接 Vexo Open 手环
- 收到点击事件 → 发送 `band_tap`（区分单击和双击）
- 收到后端的 `set_led` → 控制 LED：

| mode | LED | 什么时候 |
|---|---|---|
| `off` / `white` | 灭 / 微白 | idle、hidden、passed |
| `purple_blink` | 紫色快闪 | matched（等你说 yes） |
| `purple_pulse` | 紫色慢闪 | mutual、finding（对方正在找你） |
| `green` | 绿色常亮 | meeting_confirmed |

- 控制台页面显示：
  - 连接状态、事件日志、当前 LED
  - **配对理由**（戴手环的人在这里看为什么配上）
  - 手动按钮：模拟单击、模拟双击、Hide（调试和后备用）
  - 见面后的"保持联系？"选择 → `wearer_stay_in_touch`
- 断开时发送 `band_disconnected`，页面上显示重连按钮
- **硬件限制：** 麦克风开着时 LED 固定为蓝色。录音必须在发送 `purple_blink` 之前结束
- **验收：** 真实点击手环，后端在 500ms 内收到 `band_tap`；后端能切换紫快闪、紫慢闪、绿色

### 3.2 语音建档（P0.5）

- 戴手环的人按下录音 → 通过手环麦克风说 30 秒"我是谁、我在乎什么、我在找什么" → Deepgram 转写 → `transcript`
- 控制台上显示转写文字，**可以手动修改**后再提交
- 后备方案：直接在控制台打字填同样的价值观问题
- 录音前要有明确提示（麦克风会录到周围人的声音）
- **验收：** 说完 10 秒内得到可编辑的文字

### 3.3 后端 `/server`

- Mastra + WebSocket，只有一个 session（`demo`），数据全放内存
- 按 [接口约定](contract.md) 维护状态机，**状态以后端为准**
- 每次状态变化都广播 `state_changed`，并同步发送 `set_led`
- 提供 `POST /reset`，一键回到 idle，方便反复演示
- 收到任意一方的 `hide` → 立即进入 `hidden`，清空配对，LED 熄灭
- 30 分钟没有活动 → `expired`，清空数据

### 3.4 Profile Agent（Gemini 4）

- 输入：嘉宾的价值观答案 / 戴手环的人的转写文字
- 输出：`{ core_values, lifestyle, relationship_intent, dealbreakers, about, evidence }`
- 只用本人提供的内容，不抓取任何外部信息

### 3.5 Match Agent（Gemini 4 + Mastra）

- 输入：两份价值观资料
- 输出：见 [接口约定 §4](contract.md#4-配对结果match-agent-输出)
- 提示词规则：
  - **relationship_intent 必须兼容**（一方要认真、一方只想交朋友 → 不配）
  - **任何一方的 dealbreaker 和对方冲突 → 不配**
  - 优先看深层价值观（家庭、人生目标、生活方式），其次才是兴趣爱好
  - 两边各给一个理由，每条理由都附上依据，没有依据就不说
  - **不使用、不推断外貌**；种族、宗教等敏感信息只有本人明确写成价值观时才能提
  - 不输出任何匹配度分数
  - 开场白从共同的价值观或经历切入
- 用结构化输出（JSON schema），解析失败重试 1 次
- **后备：** 准备一份写死的配对结果（对应 demo 用的两份资料），Gemini 超时（> 8 秒）时使用
- **验收：** 准备 3 组测试资料（合、不合、dealbreaker 冲突），结果分别是配上、不配、不配

### 3.6 双方同意（Mutual Yes）

- 进入 `matched` 后：
  - 戴手环的人**单击** = yes，**双击** = no
  - 嘉宾发 `guest_decision`
- 两边都 yes → `mutual`，LED 变紫慢闪，手机解锁找人模式
- 任何一方 no → `passed`，**发给另一方的消息和 `no_match` 完全一样**，不透露谁拒绝了
- 2 分钟内有一方没回应 → `expired`
- **验收：** 手机端在 `mutual` 之前发 `find_start` 会被拒绝

### 3.7 见面确认（The Spark）

- 在 `finding` 状态收到 `band_tap`（单击）时：
  - 如果 ±1.5 秒内收到了 `phone_bump` → 确认见面
  - 如果收到 `confirm_fallback` → 也确认见面
  - 只有 `band_tap` 没有手机信号 → 等 3 秒，再提示手机端点确认按钮
- 确认后：`meeting_confirmed` + `set_led: green` → 触发 Whisper
- 时间窗口现场再调

### 3.8 Whisper（ElevenLabs）

- 输入：配对结果里的 `opener_for_each`
- 生成两段短语音（每段不超过 8 秒），各发一个 `whisper_ready`
- 音频地址由后端提供，手机能直接播放（mp3）
- **后备：** 进入 `mutual` 时就提前生成语音，见面确认后直接发送
- **验收：** 从见面确认到手机收到 `whisper_ready` 不超过 2 秒

### 3.9 保持联系（P1）

- 收到双方的 `stay_in_touch` / `wearer_stay_in_touch`
- **两边都 yes** → Gemini 根据共同兴趣生成一条第二次约会建议 → 两边都发 `contact_exchanged`
- 否则 → 什么都不交换，也不透露对方的选择

## 4. 环境与密钥

- 密钥放 `.env`，**不要提交到 repo**（`.gitignore` 已经排除 `.env`）
- 需要：`GEMINI_API_KEY`、`ELEVENLABS_API_KEY`、`ELEVENLABS_VOICE_ID`、`DEEPGRAM_API_KEY`
- 后端要能被手机访问：同一个 Wi-Fi 下用电脑 IP，或者用 ngrok / cloudflared（摄像头和运动传感器需要 HTTPS）

## 5. 优先级与时间

| 优先级 | 任务 | 什么时候完成 |
|---|---|---|
| P0 | 手环蓝牙连接 + 收到点击 + 控制 LED | **最先做** |
| P0 | 后端 WebSocket + 状态机 + `/reset` | 集成点 1 之前 |
| P0 | ElevenLabs 生成语音 | **集成点 1**：点手环 → 手机播放语音 |
| P0 | Gemini 价值观配对 + 后备结果 | **集成点 2**：手机提交 → 手环闪紫 → 显示理由 |
| P0 | 双方同意逻辑 | 集成点 2 |
| P0 | 见面确认 + 绿灯 | **集成点 3**：完整流程 |
| P0.5 | Deepgram 语音建档 | 集成点 3 之后 |
| P1 | 手机碰撞与手环点击的时间比对 | 集成点 3 之后 |
| P1 | 保持联系 + 第二次约会建议 | 有空再做 |
| — | **冻结，只修 bug** | 交作品前 1–1.5 小时 |

## 6. 完成标准

连续跑 5 遍完整 demo，每遍之间只需要调用一次 `/reset`，不需要重启服务、不需要改代码；紫灯、yes、绿灯每一遍都由真实的手环事件触发；任何一方说 no 时，另一方看不出是被拒。
