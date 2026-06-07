import json
from typing import AsyncGenerator
from config import settings

SYSTEM_PROMPT_TEMPLATE = """You are a helpful and precise QA assistant. Your job is to answer the user's question based ONLY on the provided PDF document context.

Strict Rules:
1. Answer the question using ONLY the provided context blocks. Do NOT use any external knowledge.
2. If the context does not contain the answer, reply with: "I'm sorry, but that information is not available in the uploaded document." Do not try to make up, hypothesize, or hallucinate an answer.
3. Be direct, factual, and concise in your response.
4. For every statement you make that is derived from a context block, cite the page number in square brackets, e.g. "[Page X]". Do not cite page numbers that do not appear in the context.
5. If the user asks a follow-up question, use the chat history to understand their intent, but your answer must still be grounded strictly in the provided PDF context.

--- PDF DOCUMENT CONTEXT ---
{context_str}
"""

async def stream_openai_response(
    question: str, 
    context_str: str, 
    chat_history: list[dict]
) -> AsyncGenerator[str, None]:
    """Stream response from OpenAI Chat Completion API."""
    from openai import AsyncOpenAI
    
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_TEMPLATE.format(context_str=context_str)}
    ]
    
    # Append recent chat history (limit to last 6 messages to save tokens and context)
    for msg in chat_history[-6:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
        
    # Append current question
    messages.append({"role": "user", "content": question})
    
    try:
        response = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=messages,
            stream=True,
            temperature=0.0  # Force determinism, prevent hallucinations
        )
        
        async for chunk in response:
            if chunk.choices and len(chunk.choices) > 0:
                content = chunk.choices[0].delta.content
                if content:
                    yield f"data: {json.dumps({'type': 'content', 'text': content})}\n\n"
                    
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'text': f'OpenAI stream error: {str(e)}'})}\n\n"


def validate_llm_provider_config():
    provider = settings.LLM_PROVIDER.lower()
    if provider == "openai":
        if not settings.OPENAI_API_KEY:
            raise ValueError("OPENAI provider selected but OPENAI_API_KEY is not configured.")
    elif provider == "gemini":
        if not settings.GEMINI_API_KEY:
            raise ValueError("GEMINI provider selected but GEMINI_API_KEY is not configured.")
    elif provider == "azure":
        if not settings.AZURE_OPENAI_API_KEY or not settings.AZURE_OPENAI_ENDPOINT or not settings.AZURE_OPENAI_DEPLOYMENT:
            raise ValueError(
                "AZURE provider selected but Azure OpenAI configuration is incomplete. "
                "Set AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, and AZURE_OPENAI_DEPLOYMENT."
            )
    elif provider == "ollama":
        if not settings.OLLAMA_BASE_URL:
            raise ValueError("OLLAMA provider selected but OLLAMA_BASE_URL is not configured.")
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")

async def stream_ollama_response(
    question: str,
    context_str: str,
    chat_history: list[dict]
) -> AsyncGenerator[str, None]:
    """Stream response from a local Ollama server via OpenAI-compatible API."""
    from openai import AsyncOpenAI

    # Ollama exposes an OpenAI-compatible endpoint at /v1.
    # API key is not required by default, but OpenAI SDK expects a value.
    client = AsyncOpenAI(
        api_key="ollama",
        base_url=settings.OLLAMA_BASE_URL
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_TEMPLATE.format(context_str=context_str)}
    ]

    for msg in chat_history[-6:]:
        messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({"role": "user", "content": question})

    try:
        response = await client.chat.completions.create(
            model=settings.OLLAMA_MODEL,
            messages=messages,
            stream=True,
            temperature=0.0
        )

        async for chunk in response:
            if chunk.choices and len(chunk.choices) > 0:
                content = chunk.choices[0].delta.content
                if content:
                    yield f"data: {json.dumps({'type': 'content', 'text': content})}\n\n"

    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'text': f'Ollama stream error: {str(e)}'})}\n\n"

async def stream_gemini_response(
    question: str, 
    context_str: str, 
    chat_history: list[dict]
) -> AsyncGenerator[str, None]:
    """Stream response from Google Gemini API using the google-genai SDK."""
    from google import genai
    from google.genai import types
    
    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    
    system_instruction = SYSTEM_PROMPT_TEMPLATE.format(context_str=context_str)
    
    # Construct Content objects for chat history + current prompt
    contents = []
    
    for msg in chat_history[-6:]:
        role = "user" if msg["role"] == "user" else "model"
        contents.append(
            types.Content(
                role=role,
                parts=[types.Part.from_text(text=msg["content"])]
            )
        )
        
    contents.append(
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=question)]
        )
    )
    
    try:
        # Use client.aio for asynchronous calls
        response = await client.aio.models.generate_content_stream(
            model=settings.GEMINI_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.0  # Force determinism
            )
        )
        
        async for chunk in response:
            text = chunk.text
            if text:
                yield f"data: {json.dumps({'type': 'content', 'text': text})}\n\n"
                
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'text': f'Gemini stream error: {str(e)}'})}\n\n"

async def stream_azure_response(
    question: str, 
    context_str: str, 
    chat_history: list[dict]
) -> AsyncGenerator[str, None]:
    """Stream response from Azure OpenAI API."""
    from openai import AsyncAzureOpenAI
    
    client = AsyncAzureOpenAI(
        api_key=settings.AZURE_OPENAI_API_KEY,
        api_version=settings.AZURE_OPENAI_API_VERSION,
        azure_endpoint=settings.AZURE_OPENAI_ENDPOINT
    )
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_TEMPLATE.format(context_str=context_str)}
    ]
    
    for msg in chat_history[-6:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
        
    messages.append({"role": "user", "content": question})
    
    try:
        response = await client.chat.completions.create(
            model=settings.AZURE_OPENAI_DEPLOYMENT,
            messages=messages,
            stream=True,
            temperature=0.0
        )
        
        async for chunk in response:
            if chunk.choices and len(chunk.choices) > 0:
                content = chunk.choices[0].delta.content
                if content:
                    yield f"data: {json.dumps({'type': 'content', 'text': content})}\n\n"
                    
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'text': f'Azure OpenAI stream error: {str(e)}'})}\n\n"

async def stream_llm_response(
    question: str,
    pdf_name: str,
    context_chunks: list[dict],
    chat_history: list[dict]
) -> AsyncGenerator[str, None]:
    """
    Main entry point for generating streaming LLM answers.
    1. Streams citations first.
    2. Streams response tokens.
    """
    # 1. Yield source citations first so frontend can display them immediately
    sources = [
        {
            "page_number": chunk["page_number"],
            "pdf_name": chunk["pdf_name"],
            "snippet": chunk["text"][:250] + "..." if len(chunk["text"]) > 250 else chunk["text"]
        }
        for chunk in context_chunks
    ]
    
    yield f"data: {json.dumps({'type': 'sources', 'sources': sources})}\n\n"
    
    # 2. Format context text blocks
    context_str = ""
    for idx, chunk in enumerate(context_chunks):
        context_str += f"--- CONTEXT BLOCK {idx+1} (Page {chunk['page_number']}) ---\n{chunk['text']}\n\n"
        
    # 3. Route to the configured LLM provider
    provider = settings.LLM_PROVIDER.lower()
    
    if provider == "openai":
        async for chunk in stream_openai_response(question, context_str, chat_history):
            yield chunk
    elif provider == "gemini":
        async for chunk in stream_gemini_response(question, context_str, chat_history):
            yield chunk
    elif provider == "azure":
        async for chunk in stream_azure_response(question, context_str, chat_history):
            yield chunk
    elif provider == "ollama":
        async for chunk in stream_ollama_response(question, context_str, chat_history):
            yield chunk
    else:
        yield f"data: {json.dumps({'type': 'error', 'text': f'Unknown LLM provider: {provider}'})}\n\n"
        
    # Send end of stream token
    yield "data: [DONE]\n\n"
