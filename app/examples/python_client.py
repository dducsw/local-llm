import os
from openai import OpenAI

api_key = os.environ["HPC_API_KEY"]

client = OpenAI(
    base_url=os.getenv("HPC_BASE_URL", "http://127.0.0.1:9000/v1"),
    api_key=api_key,
)

print("Available models:")
for model in client.models.list().data:
    print(" -", model.id)

response = client.chat.completions.create(
    model=os.getenv("HPC_MODEL", "qwen3.5-9b"),
    messages=[
        {
            "role": "user",
            "content": "Giải thích Tensor Parallelism trong 5 câu.",
        }
    ],
    temperature=0.2,
    max_tokens=256,
)

print()
print(response.choices[0].message.content)
