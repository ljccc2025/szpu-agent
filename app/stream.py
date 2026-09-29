"""M15 SSE 流式输出层：把 Agent 事件流封装成 Server-Sent Events 帧。

SSE 帧格式（W3C EventSource 规范）：

    event: <事件名>     (一行)
    data: <一行 JSON>   (一行)
    <空行表示一帧结束>

载荷一律走 json.dumps(ensure_ascii=False)：中文直接可读便于抓包排查，
而 JSON 编码会把换行转义掉，天然避免裸换行截断 SSE 帧。
"""
import json


def sse_pack(event, data):
    """把一个事件封装成 SSE 帧文本。"""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def chat_sse(agent, session_id, message):
    """把 Agent.chat_stream 的事件流转成 SSE 帧流，供 StreamingResponse 消费。"""
    for event, payload in agent.chat_stream(session_id, message):
        yield sse_pack(event, payload)
