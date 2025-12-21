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
    Простой фильтр для OpenRouter API.
    Показывает только бесплатные модели (с :free).
    """
    if 'data' not in data:
        return data
    
    models = data['data']
    filtered_models = []
    
    for model in models:
        try:
            model_id = model.get('id', '')
            model_id_lower = model_id.lower()
            
            # Только бесплатные модели
            if ':free' not in model_id_lower:
                continue
            
            formatted_model = {
                'name': model_id,
                'is_free': True,
            }
            
            filtered_models.append(formatted_model)
                
        except Exception:
            continue
    
    # Возвращаем только бесплатные модели
    return {'models': filtered_models}


def aiio_filter(data: dict) -> dict:
    """
    Финальная версия фильтра: возвращает словари с префиксами.
    Это лечит ошибку 'str object has no get' и добавляет авторов.
    """
    raw_models = data.get('data', []) or data.get('models', [])
    
    prefix_map = {
        "kimi-k2": "moonshotai/",
        "deepseek": "deepseek-ai/",
        "glm-4": "zai-org/",
        "llama-3": "meta-llama/",
        "llama-4": "meta-llama/",
        "gpt-oss": "openai/",
        "qwen2": "Qwen/",
        "qwen3": "Qwen/",
        "mistral": "mistralai/",
        "devstral": "mistralai/",
        "magistral": "mistralai/",
        "nemo": "mistralai/"
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