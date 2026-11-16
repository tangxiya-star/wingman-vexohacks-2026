# Wingman — 前后端接口约定（Holly ↔ Will）

> 这份文件是两人并行开发的唯一依据。改动任何字段前先在群里说一声，然后同步更新这里。产品定位见 [PRD.md](../PRD.md)（v6：dating，两个手环，同一个手势确认配对，资料来自真实的社交账号和品味）。

## 0. 当前实机模式：accel-latch（2026-11-14）

以下是当前展示适配层，优先于下文原姿态/单击产品流程；旧协议仍兼容。

- `HARDWARE_MODE=accel-latch`：`state_changed`、`room_update`、手机 `band_pose` 均带 `motion_mode`。前端 `?hardware=1` 也启用该文案，并禁用假硬件 DevPanel。
- `A=62 / Apple Watch`，`B=77 / WHOOP`。桥接器只读取现有本机 HTTP 服务，不新建 BLE 连接。
- 进入 `matched` 才开启新硬件轮次。清除上轮锁存后，两只设备必须上报同一 `reset_generation`、fresh、ready，再接受每人一次快速动作。
- 首个动作使用兼容事件 `band_tap {band,count:1,source:'quick_motion'}` 表示明确接受，并不声称发生实体单击。双方接受后进入 `mutual`，本轮两边锁存以 `band_pose up` 确认 Spark；不要求同时动作，也不要求一直举着。
- `band_pose up/down/unknown` 在该模式中分别表示 **已触发 / 等待动作 / 数据不可用**，不表示高度或持续姿势。完成后继续显示本轮 fresh 状态；重置/结束清轮。断线或过期变 unknown。
- 桥接器的姿态 heartbeat 最迟约 900 ms；服务器 2.5 s 无更新后过期。HTTP 数据必须在 2 s 内，拒绝旧轮、缺少设备、重复设备和未来时间。
- `heart_rate {band,bpm:number|null,source:'Apple Watch'|'WHOOP'}` 仅发给主人；服务端向该手机带上 `at`。缺失返回 null；服务端 10 s、前端 8 s 失效。不上大屏，不进入 ElevenLabs 的上下文或匹配模型。
- `set_led` 仍是原产品的界面状态消息，本桥接器不执行它。实体灯保留心率节奏与双敲温度演示；双敲不再解释为拒绝。
- 可选 `WINGMAN_HAPTICS=1` 复用 8767 协调器的 `/api/arm`，以稳定 event ID 开轮，复用服务内部连接。Spark 后继续接近反馈，只有结束/重置/断线才停止本桥接器拥有的轮次。Watch 震动是否可用取决于其独立应用连接；不由 HeartCast 在线推断。
- 大屏 **Reset session** 会清两人的当前资料并回到 idle；它不会终止 Python 服务。不要在 Wingman 活跃轮次中单独点 8765 的动作重置，否则 generation 会失配，应从 Wingman 重开。

## 1. 目录结构

| 目录 | 负责人 | 内容 |
|---|---|---|
| `/web` | Holly | 手机伴侣页（每人一个，`?band=A` / `?band=B`）+ 大屏 Room View |
| `/console` | Will | 电脑上的 Chrome 控制台（同时连两个手环、动作识别、Deepgram） |
| `/server` | Will | Mastra 后端 + WebSocket |
| `/docs` | 共同 | PRD、接口约定 |

## 1.5 运行环境（谁的电脑跑什么）

- **Demo 时**：后端和手环控制台都跑在 **Will 的电脑**上
- **开发和测试时**：**两台电脑都要能独立跑完整流程**
  - 后端一条命令启动（比如 `npm run dev:server`），不依赖只在 Will 电脑上才有的东西
  - 密钥放各自的 `.env`，repo 里提供 `.env.example`
  - 没有手环时，控制台的"模拟单击 / 双击 / 模拟手势"按钮可以代替真实手环
  - `/server` 提供 `MOCK_AI=1` 开关：不调 Gemini / ElevenLabs，直接返回写死的配对结果和一段示例音频，没有密钥也能跑
- **前端不写死后端地址**：
  - 默认连当前电脑：`ws://localhost:<port>/ws`
  - 用 URL 参数切换：`?server=192.168.x.x:<port>` 或 `?server=xxx.ngrok.app`
  - 这样同一个手机页面既能连 Holly 自己的电脑，也能连 Will 的电脑
- **端口**：后端统一用 `8787`（要改的话两人一起改）
- **手机访问**：同一个 Wi-Fi 用电脑 IP；需要 HTTPS（音频、运动传感器）时用 ngrok / cloudflared

## 2. 会话状态

```
idle → profiling → matched → mutual → meeting_confirmed → whisper → stay_in_touch
```

附加状态：`no_match`、`passed`、`expired`、`hidden`、`band_disconnected`

| 状态 | 两个手环的 LED | 说明 |
|---|---|---|
| `idle` / `profiling` | 灭 / 微白（录音时固件强制蓝色） | 建档中 |
| `matched` | 紫色慢闪 | 等两人各单击一次表示 yes |
| `mutual` | 紫色快闪 | 两人都 yes，互相找；做同一个手势才能确认 |
| `meeting_confirmed` | 绿色常亮 | 配对确认 |
| `passed` / `expired` / `hidden` | 灭 | **pass 和超时对外完全一样** |

**状态以后端为准。** 前端只根据 `state_changed` 切换页面。

## 3. WebSocket

- 地址：`ws://<server>/ws?role=phone|console|room&band=A|B&session=demo`
- 所有消息格式：`{ "type": "<事件名>", "ts": <毫秒时间戳>, "data": { ... } }`
- **`ts` 统一用控制台电脑的时钟**（两个手环连同一台电脑时天然一致；如果分两台电脑，要先做时钟校准）

### 手机 → 后端

| type | data |
|---|---|
| `join` | 见下方 **join 格式** |
| `profile_confirm` | `{ band, removed: string[] }`（用户在"我们读到了什么"页面删掉的 highlight / core 条目 id；确认后才进入配对） |
| `stay_in_touch` | `{ band, yes: boolean, contact?: string }` |
| `hide` | `{ band }` |

**join 格式**

```json
{
  "band": "A",
  "name": "Holly",
  "looking_for": "serious",          // "serious" | "open" | "friends"
  "dealbreaker": "Dishonesty",
  "wearing": "green jacket, white sneakers",
  "about": "可选，一句话",
  "consent": true,                   // 同意被配对
  "source_consent": true,            // 同意 Wingman 读取下面连接的内容（仅本次活动）
  "sources": {
    "letterboxd": { "username": "hollyt" },
    "reddit":     { "username": "holly_climbs" },
    "spotify":    { "playlist_url": "https://open.spotify.com/playlist/..." },   // P1
    "tiktok":     { "screenshots": ["data:image/jpeg;base64,..."] },            // 最多 4 张，前端已压缩到长边 1280px
    "instagram":  { "screenshots": ["data:image/jpeg;base64,..."] }
  }
}
```

- `sources` 至少要有 2 个来源（前端校验）
- 截图用 data URL 直接放在 WebSocket 消息里（每张约 100–250KB）；后端的 WebSocket 消息大小上限要放到 10MB 以上

### 控制台（手环）→ 后端

| type | data |
|---|---|
| `band_connected` / `band_disconnected` | `{ band }` |
| `band_tap` | `{ band, count: 1 \| 2 }` |
| `band_gesture` | `{ band, gesture: <gesture_id>, confidence }`（`ts` = 动作完成时刻） |
| `transcript` | `{ band, text, final: boolean }` |
| `heart_rate` | `{ band, bpm }`：WHOOP 实时心率，大约每秒一条。**只转发给这个手环主人自己的手机**，不上大屏，不给对方 |
| `band_pose` | `{ band, pose: 'up' \| 'down' \| 'unknown' }`：手环姿态（校准后的下垂 / 上举）。只在姿态变化时发。`mutual` 状态下两边**同时处于** `up`（不要求同一秒举起，先举的人一直举着就行）= 配对确认 |
| `hide` | `{ band }` |

**手环事件的含义由当前状态决定（后端判断）：**

| 状态 | 事件 | 含义 |
|---|---|---|
| `matched` | 单击 | 这个人说 yes |
| `matched` | 双击 | 这个人 pass → 两边都灭 |
| `mutual` | A、B 在 1 秒内上报**同一个** `band_gesture` | **配对确认（The Spark）** |
| `mutual` | 只有一边做手势 / 两边手势不同 | 忽略，继续快闪 |
| `mutual` | A、B 在 1 秒内都单击 | Spark 后备方案 |
| `mutual` | 双击 | 离开 → 两边都灭 |

后端发给手机的新消息：`heart_rate { bpm, at }`（只给本人）和 `band_pose { you, them }`。大屏的 `room_update` 里多了 `poses: { A, B }`，里面没有心率。

### 后端 → 手机 / 控制台 / 大屏

| type | data | 谁收 |
|---|---|---|
| `state_changed` | `{ state, match_gesture?, you_joined?, their_name?, meet_spot?, their_wearing? }`（`mutual` 时带上本次手势；发给手机时带 `you_joined` = 这个手环是否已经建档；配对确认后带 `their_name`；双方都说 yes 以后带 `meet_spot`（两人同一个见面点，场地用 `MEET_SPOTS` 配置）和 `their_wearing`（对方建档时说的穿着，只发给对方手机，不进 AI，不上大屏）） | 全部 |
| `profile_ready` | `{ core: [{ id, kind: "theme"\|"drawn_to", text, because[] }], highlights: [{ id, source, text }], failed_sources: string[] }`（品味内核 + 具体条目；失败的来源单独列出） | 本人 |
| `match_found` | `{ core_overlap: string[], type_fit: boolean, shared_specifics: [{ source, text }], shared_values[], reason, evidence[], opener }` | 每人只收自己那份 |
| `decision_status` | `{ you_said_yes: boolean }`（只告诉本人自己的状态，不透露对方） | 本人 |
| `whisper_ready` | `{ band, audio_url, text }` | 本人手机；没有手机就由控制台播放 |
| `contact_exchanged` | `{ name, contact, second_date_idea }`（双方都 yes 才发） | 两人 |
| `set_led` | `{ band: "A"\|"B"\|"both", mode: "off"\|"white"\|"purple_slow"\|"purple_fast"\|"green" }` | 控制台 |
| `room_update` | `{ state, leds: { A, B }, last_events[], core_overlap?, type_fit?, shared_specifics?, shared_values?, match_gesture?, names?: { A, B } }` | 大屏 |
| `error` | `{ code, message, retry: boolean }` | 全部 |

## 4. 资料与配对结果

`source` 取值：`letterboxd` | `reddit` | `tiktok` | `instagram` | `spotify` | `voice`

**Profile Agent 输出（后端内部；`highlights` 通过 `profile_ready` 发给本人）**

```json
{
  "core": [
    { "id": "c1", "kind": "theme", "text": "Bittersweet stories about timing and the people we almost had", "because": ["Past Lives ★★★★★", "Aftersun ★★★★★", "Perfect Days ★★★★½"] },
    { "id": "c2", "kind": "theme", "text": "Slow, hands-on crafts where progress is quiet", "because": ["ceramics TikToks", "r/bouldering"] },
    { "id": "c3", "kind": "drawn_to", "text": "Quiet, observant people with a dry sense of humor", "because": ["Perfect Days", "deadpan comedy TikToks"] }
  ],
  "highlights": [
    { "id": "h1", "source": "letterboxd", "text": "5★ Past Lives, Aftersun, Perfect Days" },
    { "id": "h2", "source": "reddit", "text": "Regular on r/bouldering and r/Letterboxd" },
    { "id": "h3", "source": "tiktok", "text": "Saves ceramic-studio and deadpan comedy TikToks" }
  ],
  "taste": { "films": [], "communities": [], "music": [], "aesthetics": [], "humor": "" },
  "core_values": [],
  "relationship_intent": "serious",
  "dealbreakers": [],
  "evidence": []
}
```

**Match Agent 输出**

```json
{
  "compatible": true,
  "core_overlap": ["You're both drawn to bittersweet stories about timing", "You both love slow, hands-on crafts"],
  "type_fit": { "a_fits_b": true, "b_fits_a": true },
  "shared_specifics": [
    { "source": "letterboxd", "text": "You both gave Past Lives 5★" },
    { "source": "reddit", "text": "You're both regulars on r/bouldering" },
    { "source": "tiktok", "text": "You both save ceramic-studio TikToks" }
  ],
  "shared_values": ["Looking for something serious"],
  "reasons_for_each": {
    "A": "Sam rated Past Lives 5★ and wrote about the ending, climbs at Mission Cliffs, and is looking for something real.",
    "B": "Holly loved Past Lives too, she's on r/bouldering every week, and she wants something serious."
  },
  "evidence": ["A.letterboxd: Past Lives ★★★★★", "B.letterboxd: Past Lives ★★★★★", "A.reddit: r/bouldering (34 comments)", "B.reddit: r/bouldering (12 posts)"],
  "uncertainty": "low",
  "opener_for_each": {
    "A": "Ask Sam what he thought of the ending of Past Lives.",
    "B": "Ask Holly which climbing gym she goes to."
  }
}
```

- **品味内核（core）**：找的是多个来源背后共同的模式，不是逐个来源的总结；每条至少引用 2 个具体条目（`because`）；`drawn_to` 只描述性格、价值观和气质，**不涉及外貌、身材、种族等**
- 配对先看内核重合和双向"你是对方的类型"（`type_fit`），再用具体共同项佐证；`match_found` 里 `type_fit` 只有双向都成立时才为 `true`
- 每条理由和开场白都必须引用一个**具体的共同项和来源**；"你们都喜欢电影"这种泛泛的不合格
- Gemini 提示词草稿见 [docs/prompts/](prompts/)
- 优先选冷门的共同点（小众 subreddit、冷门电影），而不是大家都喜欢的

## 5. 手势定义（待硬件测试后确定）

- **配对手势还没定**，等 Will 测完手环能稳定识别哪些动作后再选（测试步骤见 [Will 的 PRD §3.2](prd-will-backend.md)）
- 定下来后在这里补上：`gesture_id`、动作描述、识别规则
- 前端的手势提示动画和文案从配置里读，换手势不用改代码
- 阈值写在配置里，现场两个人各试 10 次再调

## 6. 措辞与安全规范

- 配对理由只基于双方连接的来源、上传的截图和填写的内容，不编造
- **原始资料（帖子、截图、评论）永远不给对方看**，只显示共同点
- 截图里如果有人脸，一律忽略；不从来源推断宗教、政治、性取向、健康等敏感信息
- **不使用、不推断外貌**；敏感信息只有本人明确写成价值观时才能提
- 不显示匹配度百分比或任何打分
- 被拒的一方永远不知道是被拒（pass 和超时对外一样）
- 确认配对不需要身体接触（同一个手势即可）
- 联系方式只在双方都选择保持联系时交换

## 7. 假数据 / Mock 后端

- `web/mock/server.mjs` 已经按这份约定实现了完整状态机（AI 结果写死），Will 可以直接参考消息格式：`cd web && npm run mock`
- 前端任意页面加 `?dev=1` 会出现"假手环控制台"，发送和真实控制台一样的事件
- 补充约定：
  - `whisper_ready.audio_url` 可以是 `null`，前端会用浏览器语音朗读 `text`
  - 新建连接时，后端要把当前状态补发给新连接（`state_changed` / `match_found` / `decision_status` / `whisper_ready`），这样手机刷新后能回到正确页面
  - 开发用：任意连接发 `{ type: "reset" }` 等同于 `POST /reset`

## 7. Voice chat ("Talk to Wingman") — added

- `GET http://<host>:8787/voice/session` → `{ signed_url }` (or `{ agent_id }`), 503 if ElevenLabs isn't set up. The phone starts an ElevenLabs conversational session with it (`@elevenlabs/react`).
- `join.sources.voice = { conversation_id?, transcript: [{ role: 'user'|'agent', text }] }`. The server re-fetches the transcript from ElevenLabs by `conversation_id` when it can, else uses the phone's copy. Counts as a source.
- `profile_ready.says_vs_shows: string | null` — one line comparing what they said they want with what their taste shows.
- Stated looks preferences are kept in the profile (`stated_type.looks`) but are **never** sent to the Match Agent or shown to a match.
- One-time setup: `cd server && npm run voice:setup` creates the agent and writes `ELEVENLABS_AGENT_ID` to `.env`.
