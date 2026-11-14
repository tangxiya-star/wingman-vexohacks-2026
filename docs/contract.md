# Wingman — 前后端接口约定（Holly ↔ Will）

> 这份文件是两人并行开发的唯一依据。改动任何字段前先在群里说一声，然后同步更新这里。产品定位见 [PRD.md](../PRD.md)（v4，dating）。

## 1. 目录结构

| 目录 | 负责人 | 内容 |
|---|---|---|
| `/web` | Holly | 手机端网页（嘉宾用） |
| `/console` | Will | 电脑上的 Chrome 控制台（连手环、Deepgram） |
| `/server` | Will | Mastra 后端 + WebSocket |
| `/docs` | 共同 | PRD、接口约定 |

## 2. 会话状态

```
idle → listening → profiling → matched → mutual → finding → meeting_confirmed → whisper → stay_in_touch
```

附加状态：`no_match`、`passed`、`hidden`、`permission_denied`、`target_lost`、`band_disconnected`、`expired`

- `matched`：配对结果已发给双方，等待两边都说 yes
- `mutual`：双方都说了 yes，手机可以进入找人模式
- 任何一方说 no → `passed`，对另一方只显示"暂时没有配对"，**不透露被拒**

**状态以后端为准。** 前端只根据 `state_changed` 切换页面，不自己推断状态。

## 3. WebSocket

- 地址：`ws://<server>/ws?role=guest|console&session=<id>`
- hackathon 只有一个 session，`session=demo` 即可
- 所有消息格式：`{ "type": "<事件名>", "ts": <毫秒时间戳>, "data": { ... } }`

### 手机 → 后端

| type | data |
|---|---|
| `guest_join` | `{ name, weekend, matters_most, looking_for: "serious" \| "open" \| "friends", dealbreaker, about?, consent: true }` |
| `guest_decision` | `{ yes: boolean }`（配对后的"想见面吗"） |
| `find_start` | `{}` |
| `target_locked` | `{ confidence }` |
| `target_lost` | `{}` |
| `phone_bump` | `{ peak_g }`（`ts` 用碰撞发生时刻） |
| `confirm_fallback` | `{}`（手动点"确认见面"） |
| `stay_in_touch` | `{ yes: boolean, contact?: string }` |
| `hide` | `{}`（立即退出配对） |

### 控制台（手环）→ 后端

| type | data |
|---|---|
| `band_connected` / `band_disconnected` | `{}` |
| `band_tap` | `{ count: 1 \| 2 }` |
| `transcript` | `{ text, final: boolean }` |
| `wearer_stay_in_touch` | `{ yes: boolean, contact?: string }` |
| `hide` | `{}` |

**手环点击的含义由当前状态决定（后端判断）：**

| 状态 | 单击 | 双击 |
|---|---|---|
| `matched` | 戴手环的人说 yes | 戴手环的人说 no（pass） |
| `finding` | 见面确认（配合 `phone_bump`） | — |

### 后端 → 手机 / 控制台

| type | data | 谁收 |
|---|---|---|
| `state_changed` | `{ state }` | 两边 |
| `match_found` | `{ shared_values[], reason, evidence[], opener }`（只发给本人看的那一份） | 两边各收自己那份 |
| `whisper_ready` | `{ audio_url, text }` | 两边各收自己那份 |
| `contact_exchanged` | `{ name, contact, second_date_idea }`（双方都选 yes 才发） | 两边 |
| `set_led` | `{ mode: "off" \| "white" \| "purple_blink" \| "purple_pulse" \| "green" }` | 控制台 |
| `error` | `{ code, message, retry: boolean }` | 两边 |

## 4. 配对结果（Match Agent 输出）

```json
{
  "compatible": true,
  "shared_values": ["Family comes first", "Weekends outdoors over nightlife", "Looking for something serious"],
  "reasons_for_each": {
    "wearer": "He puts family first, spends weekends hiking, and wants something real — just like you.",
    "guest": "Holly is happiest outdoors, family comes first for her, and she's looking for something serious."
  },
  "evidence": ["guest.matters_most: 'my family'", "wearer.transcript: 'family comes first for me'"],
  "uncertainty": "low",
  "opener_for_each": {
    "wearer": "Ask him what he misses most about home.",
    "guest": "Ask Holly about the best hike she's ever done."
  }
}
```

## 5. 措辞与安全规范

- 配对理由只基于双方写下或说出的内容，不编造
- **不使用、不推断外貌**；种族、宗教等敏感信息只有本人明确写成价值观时才能提
- 不显示匹配度百分比或任何打分
- 被拒的一方永远不知道是被拒，只显示"暂时没有配对"
- 联系方式只在双方都选择保持联系时交换

## 6. 假数据

前端开发期间，用 `web/mock/` 里的脚本按顺序推送上面的后端事件。Will 用 `wscat` 或脚本模拟手机事件。
