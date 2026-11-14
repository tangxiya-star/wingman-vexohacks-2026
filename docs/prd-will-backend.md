# Wingman PRD — Will：手环 + 后端 + AI

**负责人：** Will Li  
**范围：** `/console` 手环控制台、`/server` Mastra 后端与 WebSocket、Gemini / ElevenLabs / Deepgram 集成  
**依赖：** [接口约定](contract.md)；手机端由 Holly 负责（见 [Holly 的 PRD](prd-holly-frontend.md)）  
**总 PRD：** [PRD.md](../PRD.md)

---

## 1. 目标

让**真实的硬件事件真实地改变体验**：手环被点击 → 后端确认见面 → 手环变绿 → 手机播放 AI 生成的开场白。整个流程可以反复演示，不需要手动修后端。

## 2. 不在范围内

- 手机端页面、摄像头识别、动效（Holly 负责）
- 账号、数据库、多人多手环
- 自动录音或持续监听

## 3. 模块与需求

### 3.1 手环控制台 `/console`（第一个做，风险最大）

- 通过 Chrome 的 Web Bluetooth 连接 Vexo Open 手环
- 收到点击事件 → 发送 `band_tap`（区分单击和双击）
- 收到后端的 `set_led` → 控制 LED：

| mode | LED | 什么时候 |
|---|---|---|
| `off` / `white` | 灭 / 微白 | idle、snoozed |
| `purple_blink` | 紫色闪烁 | matched、finding |
| `green` | 绿色常亮 | meeting_confirmed |

- 控制台页面显示：连接状态、最近的事件日志、当前 LED 状态、手动"模拟点击"按钮（调试和后备用）
- 断开时发送 `band_disconnected`，页面上显示重连按钮
- **硬件限制：** 麦克风开着时 LED 固定为蓝色。录音窗口必须在发送 `purple_blink` 之前结束
- **验收：** 真实点击手环，后端日志在 500ms 内收到 `band_tap`；后端能把 LED 切到紫色和绿色

### 3.2 语音建档（P0.5）

- 戴手环的人按下录音 → 通过手环麦克风录一段短音频（最长 20 秒）→ 用 Deepgram 转写 → 发送 `transcript`
- 控制台上显示转写文字，**可以手动修改**后再提交
- 后备方案：直接在控制台打字输入
- 录音前要有明确提示（麦克风会录到周围人的声音）
- **验收：** 说一句话，10 秒内得到可编辑的文字

### 3.3 后端 `/server`

- Mastra + WebSocket，只有一个 session（`demo`），数据全放内存
- 按 [接口约定](contract.md) 维护状态机，**状态以后端为准**
- 每次状态变化都广播 `state_changed`，并同步发送 `set_led`
- 提供 `POST /reset`，一键回到 idle，方便反复演示
- 30 分钟没有活动 → `expired`，清空数据

### 3.4 Profile Agent（Gemini 4）

- 输入：嘉宾表单 / 戴手环的人的转写文字
- 输出：`{ now_focus, looking_for, can_offer, shared_topics, evidence }`
- 只用用户自己提供的内容，不抓取链接

### 3.5 Match Agent（Gemini 4 + Mastra）

- 输入：两份 profile
- 输出：见 [接口约定 §4](contract.md#4-配对结果match-agent-输出)
- 提示词要求：
  - **优先互相有用**，而不是"背景相似"
  - 两边各给一个理由，格式都是"你缺什么 → 他有什么"
  - 每条理由都附上来自资料的依据，没有依据就不说
  - 开场白只问工作和项目，不涉及外貌或个人特征，**避免约会感**
  - 没有合理的配对 → 返回 `no_match`
- 用结构化输出（JSON schema），解析失败重试 1 次
- **后备：** 准备一份写死的配对结果，Gemini 超时（> 8 秒）时使用
- **验收：** 用 3 组测试资料，每组都能给出两条不同的、有依据的理由

### 3.6 见面确认（Handshake）

- 收到 `band_tap`（单击）且当前是 `finding` 状态时：
  - 如果 ±1.5 秒内收到了 `phone_bump` → 确认见面
  - 如果收到 `confirm_fallback` → 也确认见面
  - 只有 `band_tap` 没有手机信号 → 等 3 秒，再提示手机端点确认按钮
- 确认后：`state_changed: meeting_confirmed` + `set_led: green` → 触发 Whisper
- 双击（`count: 2`）→ `snoozed`，LED 熄灭
- 时间窗口现场再调

### 3.7 Whisper（ElevenLabs）

- 输入：配对结果里的 `opener_for_each`
- 生成两段短语音（每段不超过 8 秒），各发一个 `whisper_ready`
- 音频地址由后端提供，手机能直接播放（mp3）
- **后备：** 配对一出来就提前生成语音，见面确认后直接发送，不现场等待
- **验收：** 从见面确认到手机收到 `whisper_ready` 不超过 2 秒

### 3.8 跟进消息（P2）

- 收到 `note_submit` → Gemini 根据备注 + 配对信息起草跟进消息 → `followup_draft`
- 只起草，不发送

## 4. 环境与密钥

- 密钥放 `.env`，**不要提交到 repo**（`.gitignore` 里加上 `.env`）
- 需要：`GEMINI_API_KEY`、`ELEVENLABS_API_KEY`、`ELEVENLABS_VOICE_ID`、`DEEPGRAM_API_KEY`
- 后端要能被手机访问：同一个 Wi-Fi 下用电脑 IP，或者用 ngrok / cloudflared（摄像头和运动传感器需要 HTTPS）

## 5. 优先级与时间

| 优先级 | 任务 | 什么时候完成 |
|---|---|---|
| P0 | 手环蓝牙连接 + 收到点击 + 控制 LED | **最先做** |
| P0 | 后端 WebSocket + 状态机 + `/reset` | 集成点 1 之前 |
| P0 | ElevenLabs 生成语音 | **集成点 1**：点手环 → 手机播放语音 |
| P0 | Gemini 配对 + 后备结果 | **集成点 2**：手机提交 → 手环变紫 → 手机显示理由 |
| P0 | 见面确认 + 绿灯 | **集成点 3**：完整流程 |
| P0.5 | Deepgram 语音建档 | 集成点 3 之后 |
| P1 | 手机碰撞与手环点击的时间比对 | 集成点 3 之后 |
| P1 | Gemini Vision 识别摄像头截图 | 有空再做 |
| P2 | 跟进消息 | 有空再做 |
| — | **冻结，只修 bug** | 交作品前 1–1.5 小时 |

## 6. 完成标准

连续跑 5 遍完整 demo，每遍之间只需要调用一次 `/reset`，不需要重启服务、不需要改代码；手环的紫灯和绿灯每一遍都由真实事件触发。
