"""Mock LLM — simulates API latency without requiring a real key.

Replace `ask()` with an OpenAI / Anthropic call when ready.
"""
import random
import time

_RESPONSES: dict[str, list[str]] = {
    "docker": ["Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"],
    "deploy": ["Deployment là quá trình đưa code từ máy bạn lên server để người khác dùng được."],
    "health": ["Agent đang hoạt động bình thường. All systems operational."],
    "default": [
        "Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.",
        "Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.",
        "Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.",
    ],
}


def ask(question: str, delay: float = 0.1) -> str:
    """Return a canned response, after simulating network latency."""
    time.sleep(delay + random.uniform(0, 0.05))
    q = question.lower()
    for keyword, replies in _RESPONSES.items():
        if keyword != "default" and keyword in q:
            return random.choice(replies)
    return random.choice(_RESPONSES["default"])


def ask_stream(question: str):
    """Yield response word-by-word to simulate token streaming."""
    for word in ask(question).split():
        time.sleep(0.05)
        yield word + " "
