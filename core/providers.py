"""服务商预设与协议常量。

新增一家服务商只需要在 PROVIDERS 里加一行；
新增一种协议要在 llm.py 里加一个 ChatProtocol 实例，并在这里补进 PROTOCOLS。
"""

PROVIDERS = {
    "OpenAI": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o",
        "protocol": "openai",
    },
    "Anthropic Claude": {
        "base_url": "https://api.anthropic.com/v1",
        "model": "claude-sonnet-4-20250514",
        "protocol": "anthropic",
    },
    "Google Gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "model": "gemini-2.5-flash",
        "protocol": "gemini",
    },
    "DeepSeek": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "protocol": "openai",
    },
    "通义千问（阿里云百炼）": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "protocol": "openai",
    },
    "Kimi（月之暗面）": {
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k",
        "protocol": "openai",
    },
    "智谱 GLM": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
        "protocol": "openai",
    },
    "MiniMax": {
        "base_url": "https://api.minimax.chat/v1",
        "model": "abab6.5s-chat",
        "protocol": "openai",
    },
    "硅基流动": {
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "deepseek-ai/DeepSeek-V3",
        "protocol": "openai",
    },
    "火山方舟（豆包）": {
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "model": "doubao-pro-32k",
        "protocol": "openai",
    },
    "百度千帆": {
        "base_url": "https://qianfan.baidubce.com/v2",
        "model": "ernie-4.0-8k",
        "protocol": "openai",
    },
    "OpenRouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "model": "openai/gpt-4o-mini",
        "protocol": "openai",
    },
    "Mistral": {
        "base_url": "https://api.mistral.ai/v1",
        "model": "mistral-small-latest",
        "protocol": "openai",
    },
    "xAI Grok": {
        "base_url": "https://api.x.ai/v1",
        "model": "grok-beta",
        "protocol": "openai",
    },
    "自定义 / 中转站": {
        "base_url": "",
        "model": "",
        "protocol": "openai",
    },
}

# 界面上可以选的协议。gemini_openai 不在这里——它由 llm.py 在
# 「官方域名 + gemini 型号」时自动派生，用户不需要理解。
PROTOCOLS = [
    ("openai", "OpenAI 兼容（绝大多数服务商与中转站都用这个）"),
    ("anthropic", "Anthropic Messages"),
    ("gemini", "Google Gemini 原生"),
]

CONTEXT_HINTS = {
    "openai": "/chat/completions",
    "anthropic": "/messages",
    "gemini": "/models/{model}:generateContent",
}
