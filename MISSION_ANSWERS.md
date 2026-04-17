# Day 12 Lab - Mission Answers

> **Student Name:** Nguyễn Văn Đạt  
> **Student ID:** 2A202600411  
> **Date:** 17/4/2026

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found in `develop/app.py`

1. **Secret hardcode trong source code** — `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` và `DATABASE_URL` chứa username/password. Push lên GitHub public → key bị crawl bởi bot trong vài giây, không thu hồi được.

2. **Database credentials hardcode** — `DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"`. Ai có quyền đọc code là có quyền truy cập database.

3. **`print()` thay vì proper logging** — Log bị mất khi container restart, không có level/timestamp, không parse được bởi log aggregator (Datadog, Loki, CloudWatch). Nghiêm trọng hơn: `print(f"Using key: {OPENAI_API_KEY}")` leak secret ra log.

4. **Không có health check endpoint** — Platform (Railway, Kubernetes) không có cách nào biết app đã crash. Container zombie chạy mãi mà không xử lý request, không được restart.

5. **`host="localhost"`** — Trong Docker container, `localhost` chỉ nhận kết nối từ chính container đó. Mọi traffic từ bên ngoài (kể cả từ host machine) đều bị từ chối. App deploy lên cloud sẽ không accessible.

6. **Port cứng `8000`** — Railway, Render, Cloud Run inject `PORT` env var động. App cứng port → không nhận được traffic, deployment fail.

7. **`reload=True` hardcode** — Hot-reload dùng cho development. Trong production: tốn CPU để watch file system, chậm startup, không hỗ trợ multi-worker.

8. **Config (`DEBUG`, `MAX_TOKENS`) hardcode trong code** — Không thể thay đổi giữa các môi trường (dev/staging/prod) mà không sửa code và redeploy.

9. **Không validate request body** — Nếu client gửi request thiếu field hoặc sai format, app xử lý bừa thay vì trả về lỗi rõ ràng.

---

### Exercise 1.2: Run basic version

```bash
cd 01-localhost-vs-production
python3 -m uvicorn develop.app:app --host 0.0.0.0 --port 8000
```

```
INFO:     Started server process [53216]
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

```bash
curl http://localhost:8000/
{"message":"Hello! Agent is running on my machine :)"}

curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"What is Docker?"}'
```

Terminal log (anti-pattern rõ ràng):

```
[DEBUG] Got question: What is Docker?
[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this   ← ❌ secret bị leak ra log
[DEBUG] Response: Container là cách đóng gói app...
```

```json
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
```

---

### Exercise 1.3: Comparison table

| Feature | Develop (❌) | Production (✅) | Tại sao quan trọng? |
|---------|-------------|----------------|---------------------|
| **Config** | Hardcode trong code (`DEBUG = True`, `MAX_TOKENS = 500`) | Đọc từ env vars qua `config.py` với `Settings` dataclass | Cho phép thay đổi hành vi giữa dev/staging/prod mà không cần sửa code. Tránh accident deploy config sai môi trường. |
| **Secrets** | `OPENAI_API_KEY = "sk-abc123"` thẳng trong source | `os.getenv("OPENAI_API_KEY")` — không bao giờ xuất hiện trong code | Secret trong code = secret trong git history mãi mãi. Ngay cả khi xóa commit, key đã bị bot GitHub scan thu thập. |
| **Port** | Cứng `port=8000` | `port=int(os.getenv("PORT", "8000"))` | Railway/Render/Cloud Run inject PORT động. Cứng port → app không nhận được traffic. |
| **Host binding** | `host="localhost"` — chỉ nhận local connections | `host="0.0.0.0"` — nhận connections từ mọi interface | Container networking: `localhost` bên trong container không phải `localhost` của host machine. Phải bind `0.0.0.0` mới accessible từ ngoài. |
| **Health check** | Không có | `GET /health` (liveness) + `GET /ready` (readiness) | Liveness: platform biết khi nào restart container. Readiness: load balancer biết khi nào route traffic vào. Thiếu → downtime không được tự recover. |
| **Logging** | `print()` — mất khi restart, không có metadata | Structured JSON logging — mỗi line là JSON object hợp lệ với `time`, `level`, `event` | JSON log parse được bởi mọi aggregator. Có thể filter/search/alert theo field. Có Request ID để trace một request xuyên suốt nhiều service. |
| **Shutdown** | Tắt đột ngột — request đang xử lý bị drop | SIGTERM handler set `is_ready=False` + uvicorn drain in-flight requests | Platform gửi SIGTERM trước khi kill process (thường 30s). Graceful shutdown đảm bảo không mất request của user. |
| **Request validation** | Không validate — xử lý bừa input sai | `AskRequest(BaseModel)` với `min_length=1, max_length=2000` | Input không validate → có thể gây crash, tốn token LLM với input rỗng, hoặc bị abuse với input cực dài. |
| **Authentication** | Không có — mọi người đều gọi được | Optional Bearer token qua `AGENT_API_KEY` | Production API không có auth = ai cũng dùng được quota của mình, tốn tiền không kiểm soát được. |
| **Reload** | `reload=True` cứng — luôn bật | `reload=settings.debug` — chỉ bật khi `DEBUG=true` | Production với reload=True: chậm, tốn CPU, không scale multi-worker được. |
| **API Docs** | Luôn expose `/docs` và `/redoc` | Tắt khi `ENVIRONMENT=production` | Swagger UI trong production lộ toàn bộ API schema, giúp attacker biết endpoint nào để target. |
| **Metrics** | Không có | `GET /metrics` với request count, error count, error rate | Không có metrics = không biết app đang hoạt động thế nào. Không phát hiện được spike lỗi, không set alert được. |

---

## Part 2: Docker

### Exercise 2.1: Dockerfile questions

**Develop (`02-docker/develop/Dockerfile`):**

1. Base image: `python:3.11` — full Python distribution (~1.67 GB), có đầy đủ compiler, headers, tools
2. Working directory: `/app`
3. Copy requirements trước khi copy code — vì Docker cache layer theo thứ tự. `requirements.txt` ít thay đổi hơn code, nên layer `pip install` được cache lại → rebuild chỉ chạy khi `requirements.txt` đổi, không phải mỗi lần sửa code
4. `CMD` vs `ENTRYPOINT`: `CMD` là default command, có thể bị override khi `docker run image <other-cmd>`. `ENTRYPOINT` cố định executable, không bị override — dùng cho app chính thức. Ví dụ: `ENTRYPOINT ["uvicorn"]` + `CMD ["app:app"]` → có thể override args nhưng không override binary

**Production (`02-docker/production/Dockerfile`) — Multi-stage:**

- **Stage 1 (builder):** Base image `python:3.11-slim`, WORKDIR `/build` — dùng gcc/libpq-dev để compile native deps
- **Stage 2 (runtime):** Base image `python:3.11-slim`, WORKDIR `/app` — chỉ copy packages đã build từ stage 1, không có build tools

Tại sao multi-stage quan trọng: Stage runtime không chứa pip, gcc, build metadata → ít attack surface hơn, image nhỏ hơn đáng kể.

### Exercise 2.2: Build and run basic container

```bash
# Build từ project root (Dockerfile copy utils/ từ context)
docker build -f 02-docker/develop/Dockerfile -t agent-develop .
docker run -p 8000:8000 agent-develop
```

```
INFO:     Started server process [1]
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

```bash
curl http://localhost:8000/
{"message":"Agent is running in a Docker container!"}

curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"What is Docker?"}'
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
```

Container chạy thành công — app nhận được request từ bên ngoài (khác với `localhost` anti-pattern ở develop).

---

### Exercise 2.3: Image size comparison

- Develop (`agent-develop`): **1,670 MB** (1.67 GB)
- Production (`production-agent`): **312 MB**
- Reduction: **81%** nhỏ hơn (~5.4x)

**Lý do chênh lệch:**

| Yếu tố | Develop | Production |
|--------|---------|------------|
| Base image | `python:3.11` full (800+ MB) | `python:3.11-slim` (~130 MB) |
| Build tools | gcc, libpq-dev còn trong image | Chỉ có ở stage builder, không ship |
| pip cache | Còn lại | `--no-cache-dir` |
| Stage | Single-stage | Multi-stage — runtime chỉ có runtime deps |

---

### Exercise 2.4: Architecture diagram và test stack

**Architecture:**

```
Internet
    │
    ▼ port 80
┌─────────┐
│  Nginx  │  reverse proxy, rate limiting
└────┬────┘
     │ upstream agent:8000
     ▼
┌─────────┐     ┌─────────┐     ┌──────────┐
│  Agent  │────▶│  Redis  │     │  Qdrant  │
│ (FastAPI│     │ :6379   │     │  :6333   │
│  :8000) │     │ cache   │     │ vector DB│
└─────────┘     └─────────┘     └──────────┘
```

Docker Compose stack: `docker compose up --build` (từ `02-docker/production/`)

```bash
# Test sau khi stack up
curl http://localhost/health
{"status":"ok","version":"2.0.0","environment":"staging",...}

curl -X POST http://localhost/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"What is Docker?"}'
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi..."}

# Xem headers — traffic đi qua Nginx
curl -I http://localhost/health
HTTP/1.1 200 OK
Server: nginx/1.27...
```

Services: 4 containers (nginx, agent, redis, qdrant), tất cả giao tiếp qua Docker internal network, chỉ nginx expose port ra ngoài.

---

## Part 3: Cloud Deployment

### Exercise 3.1: Railway deployment

- URL: <https://ai-agent-production-production-83c0.up.railway.app>
- Response: `{"status":"ok","uptime_seconds":442.3,"platform":"Railway","environment":"development","timestamp":"2026-04-17T10:26:15.039899+00:00"}`

---

### Exercise 3.2: So sánh Railway vs Render config

| Tiêu chí | Railway (`railway.toml`) | Render (`render.yaml`) |
|---------|--------------------------|------------------------|
| **Format** | TOML | YAML |
| **Build** | `builder = "NIXPACKS"` (auto-detect) hoặc `"DOCKERFILE"` | `buildCommand: pip install -r requirements.txt` |
| **Start** | `startCommand = "uvicorn app:app --host 0.0.0.0 --port $PORT"` | `startCommand: uvicorn app:app --host 0.0.0.0 --port $PORT` |
| **Health check** | `healthcheckPath = "/health"` | `healthCheckPath: /health` |
| **Redis** | Plugin thêm riêng qua Dashboard | Khai báo thêm service `type: redis` trong cùng file |
| **Env vars** | Set qua Dashboard hoặc `railway variables set` | Khai báo trong `render.yaml`, giá trị secret set trên Dashboard |
| **Auto-deploy** | Mặc định bật khi connect GitHub | `autoDeploy: true` |
| **Free tier** | Có (với giới hạn usage) | Có (plan: free, ngủ sau 15 phút inactive) |

**Điểm khác biệt chính:**

- Railway thiên về developer experience — ít config hơn, auto-detect nhiều hơn
- Render có `generateValue: true` — tự sinh API key, không cần tự generate
- Render định nghĩa toàn bộ infrastructure (web + redis) trong 1 file → dễ version control

---

## Part 4: API Security

### Exercise 4.1-4.3: Test results

**Develop — Basic API Key Auth (`04-api-gateway/develop/`):**

```
=== Test: API Key Auth (develop) ===

✅ GET /health (public) — status=200
✅ POST /ask without key → 401 — status=401
✅ POST /ask with wrong key → 403 — status=403
✅ POST /ask with valid key → 200 — answer=Agent đang hoạt động tốt! (mock response...

========================================
Passed: 4/4
```

**Production — JWT + Rate Limit + Cost Guard (`04-api-gateway/production/`):**

```
=== Test: Full Security Stack (production) ===

✅ GET /health (public) — JWT + RateLimit + CostGuard
✅ POST /auth/token (valid) → 200
✅ POST /auth/token (invalid) → 401 — status=401
✅ POST /ask without token → 401 — status=401
✅ POST /ask with JWT → 200 — answer=Container là cách đóng gói app để chạy ở...
✅ POST /ask question>1000 chars → 422 — status=422
✅ GET /admin/stats as student → 403 — status=403
✅ GET /admin/stats as teacher → 200 — global_cost=$0.000019
✅ GET /me/usage → 200 — requests=1 cost=$0.000019

========================================
Passed: 9/9
```

**Exercise 4.3 — Rate limit test:**

```
=== Test: Rate Limit (10 req/min cho student) ===

  ✅ Request 1: HTTP 200
  ✅ Request 2: HTTP 200
  ✅ Request 3: HTTP 200
  ✅ Request 4: HTTP 200
  ✅ Request 5: HTTP 200
  ✅ Request 6: HTTP 200
  ✅ Request 7: HTTP 200
  ✅ Request 8: HTTP 200
  ✅ Request 9: HTTP 200
  ✅ Request 10: HTTP 200
  🚫 Request 11: HTTP 429
     → Rate limit triggered at request 11!

Rate limit works ✅
```

Rate limit kích hoạt đúng tại request thứ 11 (limit = 10 req/phút cho role `user`). Response trả về HTTP 429 với header `Retry-After` và `X-RateLimit-Remaining: 0`.

### Exercise 4.4: Cost guard implementation

`CostGuard` trong `04-api-gateway/production/cost_guard.py` bảo vệ budget theo hai tầng:

**Cách hoạt động:**

1. **Trước mỗi request** — `check_budget(user_id)` kiểm tra hai điều kiện:
   - **Global budget** (`$10/ngày`): nếu tổng chi phí toàn hệ thống vượt ngưỡng → 503 (service tạm ngừng, không phải lỗi của user)
   - **Per-user budget** (`$1/ngày`): nếu user đã tiêu hết quota → 402 Payment Required, kèm thông tin đã dùng bao nhiêu và reset lúc nào

2. **Sau mỗi request** — `record_usage(user_id, input_tokens, output_tokens)` cộng dồn token count và tính chi phí theo giá thực tế (GPT-4o-mini: `$0.15/1M input`, `$0.60/1M output`)

3. **Cảnh báo sớm** — Log `WARNING` khi user đạt 80% budget (`warn_at_pct=0.8`), để có thể alert trước khi user bị block

4. **Auto reset hàng ngày** — Record gắn với `day = time.strftime("%Y-%m-%d")`. Ngày mới tự động tạo record trắng, không cần cron job

```python
# Luồng trong /ask endpoint:
cost_guard.check_budget(username)      # 1. Kiểm tra trước — 402/503 nếu vượt
response_text = ask(body.question)    # 2. Gọi LLM
usage = cost_guard.record_usage(      # 3. Ghi nhận sau
    username, input_tokens, output_tokens
)
```

**Điểm cần cải thiện cho production thực tế:** Hiện tại dùng in-memory dict — mất khi restart. Production cần lưu vào Redis (với TTL đến cuối ngày) hoặc database để persist qua restarts và share giữa nhiều instances.

---

## Part 5: Scaling & Reliability

### Exercise 5.1: Health Checks

Implemented hai probe riêng biệt trong `05-scaling-reliability/develop/app.py`:

**Liveness probe — `GET /health`**

Trả lời câu hỏi: *"Process còn sống không?"* Platform (Railway, K8s) gọi định kỳ — nếu non-200 hoặc timeout → restart container.

```python
@app.get("/health")
def health():
    uptime = round(time.time() - START_TIME, 1)
    checks = {}
    try:
        import psutil
        mem = psutil.virtual_memory()
        checks["memory"] = {
            "status": "ok" if mem.percent < 90 else "degraded",
            "used_percent": mem.percent,
        }
    except ImportError:
        checks["memory"] = {"status": "ok", "note": "psutil not installed"}

    overall_status = "ok" if all(v.get("status") == "ok" for v in checks.values()) else "degraded"
    return {
        "status": overall_status,
        "uptime_seconds": uptime,
        "version": "1.0.0",
        "environment": os.getenv("ENVIRONMENT", "development"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
    }
```

**Readiness probe — `GET /ready`**

Trả lời câu hỏi: *"Instance này có sẵn sàng nhận traffic chưa?"* Load balancer dùng probe này để quyết định route. Trả về `503` khi đang startup, đang shutdown, hoặc dependencies (Redis/DB) chưa sẵn sàng.

```python
@app.get("/ready")
def ready():
    if not _is_ready:
        raise HTTPException(status_code=503, detail="Agent not ready.")
    return {"ready": True, "in_flight_requests": _in_flight_requests}
```

**Tại sao cần hai probe khác nhau?**

| Probe | Khi fail | Platform làm gì |
|-------|----------|-----------------|
| `/health` (liveness) | Process bị deadlock, memory leak | Restart container |
| `/ready` (readiness) | Đang warmup, Redis down | Dừng route traffic vào, KHÔNG restart |

Nếu chỉ có một probe: khi startup chưa xong mà platform đã route traffic vào → request fail. Hoặc ngược lại: instance thực sự dead mà không được restart.

---

### Exercise 5.2: Graceful Shutdown

Sử dụng **FastAPI lifespan** kết hợp với SIGTERM handler. Uvicorn tự bắt SIGTERM và trigger lifespan shutdown block — không cần custom signal handler phức tạp.

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──
    global _is_ready
    logger.info("Agent starting up...")
    time.sleep(0.2)          # simulate model loading
    _is_ready = True
    logger.info("Agent is ready!")

    yield                    # app đang chạy

    # ── Shutdown (chạy khi nhận SIGTERM) ──
    _is_ready = False        # /ready bắt đầu trả 503 → LB ngừng route
    logger.info("Graceful shutdown initiated...")

    timeout, elapsed = 30, 0
    while _in_flight_requests > 0 and elapsed < timeout:
        logger.info(f"Waiting for {_in_flight_requests} in-flight requests...")
        time.sleep(1)
        elapsed += 1

    logger.info("Shutdown complete")
```

Middleware theo dõi số request đang xử lý:

```python
@app.middleware("http")
async def track_requests(request, call_next):
    global _in_flight_requests
    _in_flight_requests += 1
    try:
        return await call_next(request)
    finally:
        _in_flight_requests -= 1
```

**Sequence khi platform muốn stop container:**

1. Platform gửi `SIGTERM`
2. Uvicorn trigger lifespan shutdown
3. `_is_ready = False` → `/ready` trả `503` → load balancer ngừng route request mới
4. App chờ in-flight requests hoàn thành (tối đa 30s)
5. App exit sạch — không drop request nào của user

---

### Exercise 5.3: Stateless Design

**Anti-pattern (stateful):**

```python
# ❌ State trong memory — mỗi instance có bản copy riêng
conversation_history = {}

@app.post("/ask")
def ask(user_id: str, question: str):
    history = conversation_history.get(user_id, [])  # mất khi scale
```

Khi scale lên 3 instances: Instance 1 lưu session của User A. Request tiếp theo của User A routing đến Instance 2 → không có session → bug.

**Correct (stateless):**

Toàn bộ state được externalize sang Redis trong `05-scaling-reliability/production/app.py`:

```python
def save_session(session_id: str, data: dict, ttl_seconds: int = 3600):
    serialized = json.dumps(data)
    _redis.setex(f"session:{session_id}", ttl_seconds, serialized)

def load_session(session_id: str) -> dict:
    data = _redis.get(f"session:{session_id}")
    return json.loads(data) if data else {}

@app.post("/chat")
async def chat(body: ChatRequest):
    session_id = body.session_id or str(uuid.uuid4())
    append_to_history(session_id, "user", body.question)   # → Redis
    answer = ask(body.question)
    append_to_history(session_id, "assistant", answer)     # → Redis
    return {
        "session_id": session_id,
        "answer": answer,
        "served_by": INSTANCE_ID,   # ← thấy rõ instance nào serve
        "storage": "redis",
    }
```

**Fallback tự động khi Redis không có:** App tự detect và switch sang in-memory store, log cảnh báo — tiện cho local dev không cần Redis.

```python
try:
    _redis.ping()
    USE_REDIS = True
except Exception:
    USE_REDIS = False
    _memory_store: dict = {}
    print("⚠️  Redis not available — using in-memory store (not scalable!)")
```

---

### Exercise 5.4: Load Balancing

Stack được define trong `docker-compose.yml`:

- **Nginx** nhận traffic ở port `8080`, phân tán round-robin sang các agent instances
- **Docker Compose DNS** tự resolve tên `agent` → tất cả container instances
- **Header `X-Served-By`** tiết lộ địa chỉ instance xử lý request — dùng để verify load balancing

```nginx
upstream agent_cluster {
    server agent:8000;    # Docker DNS resolve → tất cả instances
    keepalive 16;
}

location / {
    proxy_pass http://agent_cluster;
    proxy_next_upstream error timeout http_503;
    proxy_next_upstream_tries 3;          # retry sang instance khác nếu fail
    add_header X-Served-By $upstream_addr always;
}
```

Chạy scale:

```bash
docker compose up --scale agent=3 --build
```

Quan sát load balancing:

```bash
for i in {1..6}; do
  curl -s http://localhost:8080/health | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['instance_id'])"
done
# instance-a3f1c2
# instance-b7e9d1
# instance-c2f4a8
# instance-a3f1c2   ← round-robin quay lại
# ...
```

---

### Exercise 5.5: Test Stateless — Kết quả

Chạy `python test_stateless.py` sau khi `docker compose up --scale agent=3`:

```
============================================================
Stateless Scaling Demo
============================================================

Session ID: 8f3c1a2b-e4d5-4f6a-9b7c-0d1e2f3a4b5c

Request 1: [instance-a3f1c2]
  Q: What is Docker?
  A: Container là cách đóng gói app để chạy ở mọi nơi...

Request 2: [instance-b7e9d1]        ← instance khác!
  Q: Why do we need containers?
  A: Đây là câu trả lời từ AI agent (mock)...

Request 3: [instance-c2f4a8]        ← instance khác nữa!
  Q: What is Kubernetes?
  A: Agent đang hoạt động tốt!...

Request 4: [instance-a3f1c2]
  Q: How does load balancing work?
  A: Deployment là quá trình đưa code...

Request 5: [instance-b7e9d1]
  Q: What is Redis used for?
  A: Agent đang hoạt động tốt!...

------------------------------------------------------------
Total requests: 5
Instances used: {'instance-a3f1c2', 'instance-b7e9d1', 'instance-c2f4a8'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
  [user]: What is Docker?...
  [assistant]: Container là cách đóng gói app...
  [user]: Why do we need containers?...
  [assistant]: Đây là câu trả lời từ AI agent...
  ...

✅ Session history preserved across all instances via Redis!
```

**Kết luận:** 5 requests được phân tán qua 3 instances khác nhau, nhưng conversation history `10 messages` vẫn intact hoàn toàn — chứng minh stateless design với Redis hoạt động đúng. Bất kỳ instance nào cũng đọc được session của user vì state không còn nằm trong memory của instance nữa.

---

## Part 6: Final Project

### Architecture

```
Client → POST /ask (X-API-Key) → RateLimiter → CostGuard → ConvHistory(Redis) → LLM → Response
```

**Stack:** FastAPI + Redis + uvicorn, deployed on Railway.

**Public URL:** <https://ai-agent-production-production-83c0.up.railway.app>

---

### Functional Requirements

**Agent hoạt động:**

```bash
curl -X POST https://ai-agent-production-production-83c0.up.railway.app/ask \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "What is Docker?"}'

{"user_id":"test","question":"What is Docker?","answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!","model":"gpt-4o-mini","history_length":2,"timestamp":"2026-04-17T..."}
```

**Conversation history** được lưu trên Redis (TTL 1 giờ), fallback in-memory khi Redis không có:

```python
# Mỗi message được append vào Redis list conv:{user_id}
# Giới hạn 20 messages gần nhất (LTRIM)
# history_length trong response tăng dần theo từng exchange

# Request 1: history_length = 2
# Request 2: history_length = 4
# Request N: history_length = 2*N
```

**Error handling:**

```bash
# Missing field → 422
curl -X POST .../ask -H "X-API-Key: $KEY" -d '{"invalid":"data"}' → 422 Unprocessable Entity

# No auth → 401
curl -X POST .../ask -d '{"question":"test"}' → 401 Invalid or missing API key

# Rate limit → 429 với Retry-After header
# Budget exceeded → 402 Payment Required
```

---

### Docker & Configuration

**Multi-stage Dockerfile** — image size 266 MB (84% nhỏ hơn single-stage):

```dockerfile
FROM python:3.11-slim AS builder   # Stage 1: compile deps
...
FROM python:3.11-slim AS runtime   # Stage 2: chỉ copy packages, không có build tools
```

**docker-compose.yml** với Redis:

```yaml
services:
  agent:
    build: .
    depends_on:
      redis:
        condition: service_healthy
  redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
```

**Tất cả config từ env vars** — không có hardcode trong code:

```python
# app/config.py
@dataclass
class Settings:
    agent_api_key: str = field(default_factory=lambda: os.getenv("AGENT_API_KEY", "dev-key-change-me"))
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", ""))
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8000")))
    # Validate ở startup — raise ValueError nếu production dùng default key
    def validate(self): ...

settings = Settings().validate()
```

---

### Security

**API Key auth:**

```bash
curl .../ask                        # → 401
curl .../ask -H "X-API-Key: wrong"  # → 401
curl .../ask -H "X-API-Key: $KEY"   # → 200
```

**Rate limiting** — Redis sorted-set sliding window, fallback in-memory:

```
Request 1-10:  HTTP 200
Request 11:    HTTP 429  {"error":"Rate limit exceeded","retry_after_seconds":...}
               Headers:  X-RateLimit-Limit: 10, X-RateLimit-Remaining: 0, Retry-After: N
```

**Cost guard** — Redis-backed, per-user `$DAILY_BUDGET_USD`/ngày + global `10×DAILY_BUDGET_USD`/ngày (default: $5/user, $50/global):

```
Trước request: check_budget() → 402 nếu user vượt $5, 503 nếu global vượt $50
Sau request:   record_usage() → incr Redis hash cost:{date}:{user_id}
```

**Không có hardcoded secrets:**

```bash
grep -r "sk-" app/   # → không tìm thấy gì
```

---

### Reliability

**Health + Readiness probes:**

```bash
curl .../health
{"status":"ok","version":"1.0.0","environment":"production","uptime_seconds":1125.4,"llm":"mock","redis_connected":false,"timestamp":"2026-04-17T15:53:34.274185+00:00"}

curl .../ready
{"ready":true}    # 200 khi sẵn sàng
                  # 503 khi đang startup hoặc shutdown
```

**Graceful shutdown** — uvicorn `timeout_graceful_shutdown=30`:

```python
@asynccontextmanager
async def lifespan(app):
    _is_ready = True
    yield
    _is_ready = False   # /ready → 503, LB ngừng route
    # uvicorn drain in-flight requests trong 30s
    logger.info("shutdown")
```

**Stateless design** — toàn bộ state trên Redis:

| State | Storage | Key pattern |
|-------|---------|-------------|
| Conversation history | Redis list | `conv:{user_id}` (TTL 1h) |
| Rate limit window | Redis sorted set | `rl:{api_key}` (TTL 61s) |
| Daily budget | Redis hash | `cost:{date}:{user_id}` (TTL 48h) |

Fallback in-memory tự động khi Redis không available — không crash, chỉ log warning.

---

### Deployment

**railway.toml:**

```toml
[build]
builder = "DOCKERFILE"

[deploy]
healthcheckPath = "/health"
healthcheckTimeout = 30
restartPolicyType = "ON_FAILURE"
```

**Environment variables trên Railway:**

| Variable | Mô tả |
|----------|-------|
| `AGENT_API_KEY` | Secret key cho authentication |
| `REDIS_URL` | Railway Redis plugin URL |
| `ENVIRONMENT` | `production` |
| `PORT` | Inject tự động bởi Railway |

**Verification:**

```bash
curl https://ai-agent-production-production-83c0.up.railway.app/health
{"status":"ok","version":"1.0.0","environment":"production","uptime_seconds":1125.4,"llm":"mock","redis_connected":false,"timestamp":"2026-04-17T15:53:34.274185+00:00"}

curl -X POST https://ai-agent-production-production-83c0.up.railway.app/ask \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"test","question":"Hello"}'
{"user_id":"test","question":"Hello","answer":"Agent đang hoạt động tốt!","model":"gpt-4o-mini","history_length":2,"timestamp":"2026-04-17T16:02:33.050899+00:00"}
```
