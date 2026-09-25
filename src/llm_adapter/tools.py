MEMORY_SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {"type": "array", "items": {"type": "string"}},
        "remaining": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["facts", "remaining"],
    "additionalProperties": False,
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "act",
            "description": "Choose and perform one browser-agent action.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["execute_browser_code", "ask_user", "finish"],
                    },
                    "code": {
                        "type": "string",
                        "description": "JavaScript async function body; use await, explicit return, and state for values shared between steps.",
                    },
                    "question": {"type": "string"},
                    "answer": {"type": "string"},
                    "success": {
                        "type": "boolean",
                        "description": "For finish only; omit for success or set false for failure.",
                    },
                    "intent": {
                        "type": "string",
                        "description": "Why this browser or user action is needed.",
                    },
                    "memory": MEMORY_SCHEMA,
                },
                "required": ["action", "memory"],
                "additionalProperties": False,
            },
        },
    },
]
