import asyncio
from config import settings
from services.llm_service import validate_llm_provider_config, stream_ollama_response

print('LLM_PROVIDER', settings.LLM_PROVIDER)
print('OLLAMA_BASE_URL', settings.OLLAMA_BASE_URL)

try:
    validate_llm_provider_config()
    print('validate_llm_provider_config OK')
except Exception as e:
    print('validate error', repr(e))

async def test():
    async for chunk in stream_ollama_response('Hello', 'context text', []):
        print('chunk', chunk)

try:
    asyncio.run(test())
except Exception as e:
    import traceback
    traceback.print_exc()
