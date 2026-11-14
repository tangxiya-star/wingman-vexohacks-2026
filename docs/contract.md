# Wingman — 前后端接口约定（Holly ↔ Will）

> 这份文件是两人并行开发的唯一依据。改动任何字段前先在群里说一声，然后同步更新这里。

## 1. 目录结构

| 目录 | 负责人 | 内容 |
|---|---|---|
| `/web` | Holly | 手机端网页（嘉宾用） |
| `/console` | Will | 电脑上的 Chrome 控制台（连手环、Deepgram） |
| `/server` | Will | Mastra 后端 + WebSocket |
| `/docs` | 共同 | PRD、接口约定 |

## 2. 会话状态

```
idle → listening → profiling → matched → finding → meeting_confirmed → whisper → follow_up
```

附加状态：`no_match`、`snoozed`、`permission_denied`、`target_lost`、`band_disconnected`、`expired`

**状态以后端为准。** 前端只根据 `state_changed` 切换页面，不自己推断状态。

## 3. WebSocket

- 地址：`ws://<server>/ws?role=guest|console&session=<id>`
- hackathon 只有一个 session，`session=demo` 即可
- 所有消息格式：`{ "type": "<事件名>", "ts": <毫秒时间戳>, "data": { ... } }`

### 手机 → 后端

| type | data |
|---|---|
| `guest_join` | `{ name, link?, working_on, looking_for, can_offer, consent: true }` |
| `match_dismiss` | `{}` |
| `find_start` | `{}` |
| `target_locked` | `{ confidence }` |
| `target_lost` | `{}` |
| `phone_bump` | `{ peak_g }`（`ts` 用碰撞发生时刻） |
| `confirm_fallback` | `{}`（手动点"确认见面"） |
| `note_submit` | `{ text }` |

### 控制台（手环）→ 后端

| type | data |
|---|---|
| `band_connected` / `band_disconnected` | `{}` |
| `band_tap` | `{ count: 1 \| 2 }`（2 = 双击，表示稍后再说） |
| `transcript` | `{ text, final: boolean }` |

### 后端 → 手机 / 控制台

| type | data | 谁收 |
|---|---|---|
| `state_changed` | `{ state }` | 两边 |
| `match_found` | `{ headline, reason, evidence[], opener }`（只发给本人看的那一份） | 两边各收自己那份 |
| `whisper_ready` | `{ audio_url, text }` | 两边各收自己那份 |
| `followup_draft` | `{ text }` | 手机 |
| `set_led` | `{ mode: "off" \| "white" \| "purple_blink" \| "green" }` | 控制台 |
| `error` | `{ code, message, retry: boolean }` | 两边 |

## 4. 配对结果（Match Agent 输出）

```json
{
  "mutual_fit": "Holly needs healthcare distribution; the guest has sold to 3 outpatient clinics.",
  "reasons_for_each": {
    "wearer": "He has sold B2B into outpatient clinics — the channel you're trying to crack.",
    "guest": "She's building a healthcare AI agent and is looking for a distribution partner."
  },
  "evidence": ["guest.can_offer: 'B2B sales to clinics'", "wearer.looking_for: 'healthcare distribution'"],
  "uncertainty": "low",
  "opener_for_each": {
    "wearer": "Ask him what outpatient clinics actually buy.",
    "guest": "Ask Holly how she's getting her first hospital pilot."
  }
}
```

## 5. 措辞规范

- 用词沿用总 PRD：Someone here is worth meeting、The Hunt、The Spark、You found your person
- 每条理由都要有来自资料的依据，不编造
- 开场白不涉及敏感个人信息或资料里没有的推断

## 6. 假数据

前端开发期间，用 `web/mock/` 里的脚本按顺序推送上面的后端事件。Will 用 `wscat` 或脚本模拟手机事件。
