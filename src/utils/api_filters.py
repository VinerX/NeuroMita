def apply_filter(filter_fn: str, data: dict) -> dict:
    if filter_fn == "filter_generate_content":
        return filter_generate_content(data)
    if filter_fn == "mistral_filter":
        return mistral_filter(data)
    if filter_fn == "openrouter_filter":
        return openrouter_filter(data)
    if filter_fn == "aiio_filter":
        return aiio_filter(data)
    return data


def filter_generate_content(data: dict) -> dict:
    """
    Фильтр для Gemini API.
    Оставляет только модели, поддерживающие generateContent.
    """
    if 'models' in data:
        filtered_models = []
        for model in data['models']:
            methods = model.get('supportedGenerationMethods', [])
            if 'generateContent' in methods:
                filtered_models.append(model)
        data['models'] = filtered_models
    return data


def mistral_filter(data: dict) -> dict:
    """
    Фильтр для Mistral API.
    Преобразует формат ответа Mistral в единый формат.
    """
    # Если Mistral возвращает модели в поле 'data'
    if 'data' in data and isinstance(data['data'], list):
        return {'models': data['data']}
    # Если уже в правильном формате
    return data


def openrouter_filter(data: dict) -> dict:
    """
    Фильтр для OpenRouter API с добавлением префиксов и сохранением метаданных.
    Возвращает и бесплатные, и платные модели; UI сам решает, что показывать.
    """
    if 'data' not in data:
        return data
    
    models = data['data']
    filtered_models = []
    
    # Карта префиксов
    prefix_map = {
        "trinity": "arcee-ai/",
        "tng-": "tngtech/",
        "kimi-k2": "moonshotai/",
        "deepseek": "deepseek-ai/",
        "glm-4": "zai-org/",
        "llama-3": "meta-llama/",
        "llama-4": "meta-llama/",
        "gpt-oss": "openai/",
        "qwen2": "Qwen/",
        "qwen3": "Qwen/",
        "qwen-2.5": "Qwen/",
        "mistral": "mistralai/",
        "devstral": "mistralai/",
        "magistral": "mistralai/",
        "olmo-": "allenai/",
        "nemotron": "nvidia/",
        "mimo-": "xiaomi/",
        "kat-coder": "kwaipilot/",
        "tongyi": "alibaba/",
        "dolphin-": "cognitivecomputations/",
        "gemma": "google/",
        "gemini": "google/",
        "claude": "anthropic/",
        "command": "cohere/",
        "dbrx": "databricks/",
        "amazon": "amazon/",
        "jamba": "ai21/",
        "bert": "openrouter/"
    }
    
    for model in models:
        try:
            model_id = model.get('id', '')
            model_id_lower = model_id.lower()

            # Добавляем префикс, если его нет
            if "/" not in model_id:
                for key, prefix in prefix_map.items():
                    if key in model_id_lower:
                        model_id = prefix + model_id
                        break

            pricing = model.get('pricing') if isinstance(model.get('pricing'), dict) else {}
            top_provider = model.get('top_provider') if isinstance(model.get('top_provider'), dict) else {}

            formatted_model = {
                'id': model_id,
                'name': model.get('name') or model_id,
                'canonical_slug': model.get('canonical_slug'),
                'context_length': model.get('context_length'),
                'top_provider_context_length': top_provider.get('context_length'),
                'max_completion_tokens': top_provider.get('max_completion_tokens'),
                'is_free': ':free' in model_id_lower,
                'pricing': pricing,
                'top_provider': top_provider,
                # Best-effort optional perf metadata if OpenRouter adds it.
                'latency': (
                    top_provider.get('latency')
                    or model.get('latency')
                    or model.get('avg_latency')
                    or model.get('p50_latency')
                ),
                'tokens_per_second': (
                    top_provider.get('tokens_per_second')
                    or top_provider.get('throughput')
                    or model.get('tokens_per_second')
                    or model.get('throughput')
                ),
            }

            filtered_models.append(formatted_model)

        except Exception:
            continue

    return {'models': filtered_models}


def aiio_filter(data: dict) -> dict:
    """
    Возвращает словари с префиксами.
    Это лечит ошибку 'str object has no get' и добавляет авторов.
    """
    raw_models = data.get('data', []) or data.get('models', [])
    
    prefix_map = {
        "trinity": "arcee-ai/",
        "tng-": "tngtech/",
        "kimi-k2": "moonshotai/",
        "deepseek": "deepseek-ai/",
        "glm-4": "zai-org/",
        "llama-3": "meta-llama/",
        "llama-4": "meta-llama/",
        "gpt-oss": "openai/",
        "qwen2": "Qwen/",
        "qwen3": "Qwen/",
        "qwen-2.5": "Qwen/",
        "mistral": "mistralai/",
        "devstral": "mistralai/",
        "magistral": "mistralai/",
        "olmo-": "allenai/",
        "nemotron": "nvidia/",
        "mimo-": "xiaomi/",
        "kat-coder": "kwaipilot/",
        "tongyi": "alibaba/",
        "dolphin-": "cognitivecomputations/",
        "gemma": "google/",
        "gemini": "google/",
        "claude": "anthropic/",
        "command": "cohere/",
        "dbrx": "databricks/",
        "amazon": "amazon/",
        "jamba": "ai21/",
        "bert": "openrouter/"
    }
    
    final_list = []
    
    for item in raw_models:
        # Достаем ID (он может быть строкой или в словаре)
        m_id = item.get('id', '') if isinstance(item, dict) else str(item)
        if not m_id: continue
        
        m_id = m_id.strip()
        
        # Клеим префикс, если его нет
        if "/" not in m_id:
            m_id_lower = m_id.lower()
            for key, prefix in prefix_map.items():
                if key in m_id_lower:
                    m_id = prefix + m_id
                    break
        
        # Возвращаем словарь
        # Это предотвратит ошибку в api_presets_controller
        final_list.append({
            'id': m_id, 
            'name': m_id   # Показываем полное имя в списке
        })
        
    return {'models': final_list}
