# Wingman — 前后端接口约定（Holly ↔ Will）

> 这份文件是两人并行开发的唯一依据。改动任何字段前先在群里说一声，然后同步更新这里。产品定位见 [PRD.md](../PRD.md)（v5：dating，两个手环，同一个手势确认配对）。

## 1. 目录结构

| 目录 | 负责人 | 内容 |
|---|---|---|
| `/web` | Holly | 手机伴侣页（每人一个，`?band=A` / `?band=B`）+ 大屏 Room View |
| `/console` | Will | 电脑上的 Chrome 控制台（同时连两个手环、动作识别、Deepgram） |
| `/server` | Will | Mastra 后端 + WebSocket |
| `/docs` | 共同 | PRD、接口约定 |

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
| `join` | `{ band: "A"\|"B", name, weekend, matters_most, looking_for: "serious"\|"open"\|"friends", dealbreaker, about?, consent: true }` |
| `stay_in_touch` | `{ band, yes: boolean, contact?: string }` |
| `hide` | `{ band }` |

### 控制台（手环）→ 后端

| type | data |
|---|---|
| `band_connected` / `band_disconnected` | `{ band }` |
| `band_tap` | `{ band, count: 1 \| 2 }` |
| `band_gesture` | `{ band, gesture: <gesture_id>, confidence }`（`ts` = 动作完成时刻） |
| `transcript` | `{ band, text, final: boolean }` |
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

### 后端 → 手机 / 控制台 / 大屏

| type | data | 谁收 |
|---|---|---|
| `state_changed` | `{ state, match_gesture? }`（`mutual` 时带上本次要做的手势） | 全部 |
| `match_found` | `{ shared_values[], reason, evidence[], opener }` | 每人只收自己那份 |
| `decision_status` | `{ you_said_yes: boolean }`（只告诉本人自己的状态，不透露对方） | 本人 |
| `whisper_ready` | `{ band, audio_url, text }` | 本人手机；没有手机就由控制台播放 |
| `contact_exchanged` | `{ name, contact, second_date_idea }`（双方都 yes 才发） | 两人 |
| `set_led` | `{ band: "A"\|"B"\|"both", mode: "off"\|"white"\|"purple_slow"\|"purple_fast"\|"green" }` | 控制台 |
| `room_update` | `{ state, leds: { A, B }, last_events[] }` | 大屏 |
| `error` | `{ code, message, retry: boolean }` | 全部 |

## 4. 配对结果（Match Agent 输出）

```json
{
  "compatible": true,
  "shared_values": ["Family comes first", "Weekends outdoors over nightlife", "Looking for something serious"],
  "reasons_for_each": {
    "A": "He puts family first, spends weekends hiking, and wants something real — just like you.",
    "B": "Holly is happiest outdoors, family comes first for her, and she's looking for something serious."
  },
  "evidence": ["B.matters_most: 'my family'", "A.transcript: 'family comes first for me'"],
  "uncertainty": "low",
  "opener_for_each": {
    "A": "Ask him what he misses most about home.",
    "B": "Ask Holly about the best hike she's ever done."
  }
}
```

## 5. 手势定义（待硬件测试后确定）

- **配对手势还没定**，等 Will 测完手环能稳定识别哪些动作后再选（测试步骤见 [Will 的 PRD §3.2](prd-will-backend.md)）
- 定下来后在这里补上：`gesture_id`、动作描述、识别规则
- 前端的手势提示动画和文案从配置里读，换手势不用改代码
- 阈值写在配置里，现场两个人各试 10 次再调

## 6. 措辞与安全规范

- 配对理由只基于双方写下或说出的内容，不编造
- **不使用、不推断外貌**；敏感信息只有本人明确写成价值观时才能提
- 不显示匹配度百分比或任何打分
- 被拒的一方永远不知道是被拒（pass 和超时对外一样）
- 确认配对不需要身体接触（同一个手势即可）
- 联系方式只在双方都选择保持联系时交换

## 7. 假数据

前端开发期间，用 `web/mock/` 里的脚本按顺序推送后端事件。Will 用 `wscat` 或脚本模拟手机事件和手环事件（包括 `band_gesture`）。
