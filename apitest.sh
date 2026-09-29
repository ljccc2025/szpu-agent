#!/bin/bash
H="Content-Type: application/json"
B=http://127.0.0.1:8000
echo "TEST1_计算器工具:"
curl -s --max-time 60 -X POST $B/api/chat -H "$H" -d '{"session_id":"verify1","message":"请帮我计算 (2+3)*7 等于多少"}'
echo; echo "TEST2_时间工具:"
curl -s --max-time 60 -X POST $B/api/chat -H "$H" -d '{"session_id":"verify1","message":"现在服务器上是几点？"}'
echo; echo "TEST3_多轮上下文:"
curl -s --max-time 60 -X POST $B/api/chat -H "$H" -d '{"session_id":"verify1","message":"我刚才让你算的算式是什么？"}'
echo; echo "TEST4_历史接口:"
curl -s --max-time 10 $B/api/history/verify1 | head -c 500
echo; echo "APITEST_DONE"
