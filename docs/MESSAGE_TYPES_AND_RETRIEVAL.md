# 消息类型、向量化与检索行为说明

本文档说明当前 Seelenmaschine 中，不同消息在以下几个维度上的行为：

- 是否为该消息自身生成 embedding
- 是否会用该消息触发“历史记忆向量检索”
- 是否会成为“被向量检索的对象”
- 是否会成为“全文/关键词检索的对象”
- 是否计入对话轮数
- 是否进入 summary

本文基于当前代码实现整理，重点对应：

- `src/core/conversation.py`
- `src/memory/manager.py`
- `src/memory/sessions.py`
- `src/core/database.py`
- `src/tools/memory_search.py`

---

## 一、先区分 3 个容易混淆的概念

### 1. 是否生成 embedding

指的是：

> 这条消息在写入数据库时，是否会为它自身生成并保存向量。

这决定的是它将来有没有机会成为向量检索候选对象之一。

它**不等于**“当前处理这条消息时，会不会拿它去查历史”。

---

### 2. 是否触发历史向量检索

指的是：

> 当前系统在处理这条新消息时，会不会把它当成 query，去召回相似的历史 summaries / conversations。

这是一次“读历史”的行为。

例如普通 `process_message()` 中，用户消息会：

1. 先写入 memory
2. 生成该条消息的 embedding
3. 再用这条消息去做历史向量检索

---

### 3. 是否成为被向量检索的对象

指的是：

> 将来别的消息触发向量检索时，这条消息自身会不会作为候选结果被召回。

通常至少取决于两件事：

1. 它有没有 embedding
2. 检索 SQL / 检索逻辑是否允许该 `message_type`

---

## 二、最关键结论

### 当前系统里，检索主路径主要由 `message_type` 决定，而不是由 `role` 决定。

更准确地说：

- **是否进入向量检索 / 全文检索主路径，主要看 `message_type`**
- `role` 更多是一个**附加过滤条件**，不是主开关

因此：

- `role="user"` 且 `message_type="conversation"`：通常可检索
- `role="assistant"` 且 `message_type="conversation"`：通常也可检索
- `role="system"` 但 `message_type!="conversation"`：通常不进入当前检索主路径

---

## 三、行为总表

> 说明：以下表格描述的是**当前实现的主路径行为**。其中“可检索”指默认数据库 / memory search 主路径，不表示绝对无法通过未来自定义逻辑扩展支持。

| 消息来源 / 类型 | 常见 role | message_type | 是否生成 embedding | 是否触发历史向量检索 | 是否成为被向量检索对象 | 是否成为全文/关键词检索对象 | 是否计入轮数 | 是否进入 summary | 备注 |
|---|---|---|---|---|---|---|---|---|---|
| 普通用户消息 | `user` | `conversation` | 是 | 是 | 是 | 是 | 是 | 是 | 典型入口：`process_message()` + `add_user_message_async()` |
| 普通助手消息 | `assistant` | `conversation` | 是 | 否（通常是响应结果，不作为新 query） | 是 | 是 | 是 | 是 | 由 `add_assistant_message_async()` 写入 |
| 文件接收生成的 synthetic 消息（当前实现） | `user` | `conversation` | 是（优先使用 caption；无 caption 时回退到整条 synthetic message） | 是 | 是 | 是 | 是 | 是 | 当前按普通 conversation 流程处理，但 embedding 文本优先取 caption |
| 工具上下文消息 | `system` | `tool_call` | 通常否 | 否 | 否（默认主路径） | 否（默认主路径） | 否 | 否 | 当前通过 `add_context_message_async(..., message_type="tool_call")` 写入 |
| 定时任务触发消息 | `system` | `scheduled_task` | 通常否（写入时） | 会触发，但 query 主要是任务正文 | 默认否 | 默认否 | 否 | 否 | 用于把任务触发信息放入上下文 |
| 通用 system_event（如果未来使用） | 取决于调用方 | 取决于调用方 | 取决于调用方 | 取决于调用方 | 取决于调用方 | 取决于调用方 | 取决于调用方 | 取决于调用方 | 现在建议通过通用接口显式传参 |
| summary 记录 | N/A | summary 表，不在 conversation 表中 | 是 | 会被 summary 检索使用 | 是（summary 检索） | 是（summary 关键词检索） | 不适用 | 它本身就是 summary | 由 summary 机制单独存储 |

---

## 四、当前 conversation 主路径的真实含义

对一条普通 `conversation` 消息，通常同时满足三件事：

1. **它自己会生成 embedding**
2. **处理当前消息时，会用它去检索历史**
3. **它未来也会成为别的消息向量检索时的候选对象**

这是为什么 `conversation` 是当前系统里最“完整”的消息类型。

---

## 五、为什么说“role 不是主开关”

在当前代码设计里，`role` 更接近“检索结果过滤器”而不是“索引资格判定器”。

也就是说：

- 不会因为一条消息是 `assistant` 就天然不可检索
- 也不会因为一条消息是 `user` 就天然可检索

真正更关键的是：

- 它是否按 `conversation` 存储
- 它是否有 embedding
- 检索 SQL 是否纳入该 `message_type`

所以更准确的理解是：

> `role` 决定“你想筛谁”，`message_type` 决定“它是否在这条检索主路径里”。

---

## 六、数据库检索层面的当前规则

### 1. conversation 是默认主检索对象

当前数据库查询中，多处存在类似条件：

```sql
c.message_type = 'conversation'
```

这意味着：

- conversation 会进入当前 conversations 检索主路径
- `tool_call` / `scheduled_task` 等非 conversation 类型，默认不会进入这条路径

---

### 2. role 可以作为附加过滤条件

在 conversation 已被纳入候选集合后，检索层还可以继续按 role 过滤，例如：

- 只搜 `user`
- 只搜 `assistant`

但这是在“已属于可检索 message_type”之后才有意义。

---

## 七、对通用接口 `add_context_message(...)` 的推荐理解

当前已经引入通用接口：

- `MemoryManager.add_context_message(...)`
- `MemoryManager.add_context_message_async(...)`

可显式传入：

- `role`
- `message_type`
- `include_in_turn_count`
- `include_in_summary`
- `embedding`

这意味着未来如果要新增一种消息语义，应该优先从以下几个问题出发：

1. 它属于哪种 `message_type`？
2. 它是否需要 embedding？
3. 它是否应该计入轮数？
4. 它是否应该进入 summary？
5. 它是否应该进入现有检索主路径，还是只存在于上下文？

---

## 八、实用判断口诀

如果你只想快速判断一类消息的行为，可以用下面这套顺序：

### A. 它是不是 `conversation`？

如果是，通常：

- 更容易进入当前向量检索 / 全文检索主路径
- 更适合作为长期可回忆内容

如果不是，通常默认更像“上下文控制消息”。

### B. 它有没有 embedding？

如果没有 embedding：

- 它通常不会成为向量检索对象

### C. 当前处理流程有没有拿它当 query？

如果有：

- 它会触发本轮历史记忆召回

如果没有：

- 它只是被写入，不负责触发 recall

---

## 九、针对目前代码状态的简化版结论

### 可以简化成一句话：

> 当前系统里，默认是 **`message_type="conversation"` 的消息既会被向量化，也会成为向量检索与全文检索的主要对象；`role` 不是主判定条件，只是可选过滤维度。**

但严格一点还要补一句：

> “会被向量化”、“会触发历史向量检索”、“会成为被向量检索对象” 是三个不同概念，`conversation` 通常同时满足这三者，而其他消息类型不一定。

---

## 十、存储文本、embedding 文本、读回文本是否一致

这是另一个很容易混淆的问题。

当前系统里，至少要区分三种“文本”：

1. **存储文本**
   - 实际写入数据库 `text` 字段、后续恢复上下文时读回的文本

2. **embedding 文本**
   - 用来生成向量的文本
   - 它可以与存储文本相同，也可以不同

3. **读回/展示文本**
   - 之后从上下文、检索结果、数据库恢复中读到的文本
   - 通常更接近“存储文本”，而不是 embedding 文本

### 关键结论

> **embedding 用什么文本，并不等于数据库就存什么文本。**

也就是说：

- 可以用较短、更有语义密度的文本生成 embedding
- 但数据库里仍然保留完整原文

---

## 十一、当前实现下各类消息的一致性情况

| 消息类型 | 存储文本 | embedding 文本 | 之后读回时通常看到什么 | 是否完全一致 |
|---|---|---|---|---|
| 普通用户消息 | 用户原始消息 | 通常是用户原始消息 | 用户原始消息 | 通常一致 |
| 文件 synthetic 用户消息 | 完整文件消息（文件名、路径、MIME、caption 等） | **优先 caption；无 caption 时回退到完整文件消息** | 完整文件消息 | **不一定一致** |
| 普通 assistant 消息 | 默认会先去掉 blockquotes/citations 后再存（非 debug 模式） | 通常基于原 assistant 文本去生成 | 去掉 blockquotes 后的文本（常见情况） | **不一定一致** |
| tool_call / scheduled_task 等上下文消息 | 调用方传入的完整文本 | 通常没有 embedding | 通常就是存储时的完整文本 | 常见情况下存储与读回一致 |

---

## 十二、针对“能否读到完整消息”的实际结论

### 1. 文件消息

当前文件消息虽然在 embedding 上优先使用 `caption`，但：

- **数据库存储的是完整 synthetic file message**
- **之后恢复上下文、检索命中、再次读取时，通常读到的也是完整文件消息**

因此：

> 文件消息这类 `user/conversation` 记录，当前实现下通常是可以再次读到完整消息文本的。

### 2. assistant 消息

assistant 消息是一个重要例外：

- 在非 debug 模式下，存储前会经过 `strip_blockquotes(...)`
- 所以并不保证“未来任何时候都能读回最初原样的 assistant 文本”

### 3. 非 conversation 的上下文消息

像：

- `tool_call`
- `scheduled_task`

这类消息如果被写入数据库，是否完整主要取决于：

- 调用方当时传入的文本是什么
- 当前通用接口本身不会额外做自动摘要或裁剪

所以通常：

> 写进去什么，后面就会读到什么。

---

## 十三、可操作的记忆原则

如果你以后想判断“某类消息会不会丢失原文”，最稳的判断顺序是：

1. **它写入数据库时的 `text` 到底是什么？**
2. **embedding 是否用了另一份文本？**
3. **存储前有没有做清洗/裁剪/strip 处理？**

只要第 3 步没有发生额外清洗，那么：

- 读回文本通常等于存储文本
- 即使 embedding 文本不同，也不影响你之后读到完整存储文本
