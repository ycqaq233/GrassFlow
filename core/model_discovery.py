"""
GrassFlow Model Discovery — 模型发现与能力查询

参考 opencode 的模型发现系统，实现：
  1. 从 models.dev 社区注册表获取模型目录（主数据源）
  2. 从各 provider 的 /v1/models 端点动态发现模型（备选）
  3. 本地文件缓存 + TTL 机制
  4. 支持 deepseek / openai / anthropic / ollama / 自定义 provider

使用方式：
    # 自动发现（推荐）
    models = await discover_models("openai", api_key="sk-xxx")

    # 手动指定 provider
    models = await discover_models("deepseek", api_key="sk-xxx")

    # 从缓存读取（不发请求）
    cached = get_cached_models("openai")

    # 查询单个模型能力
    info = get_model_info("openai", "gpt-4o")
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import aiohttp

logger = logging.getLogger(__name__)

# ============================================================================
# 常量
# ============================================================================

# models.dev API
MODELS_DEV_URL = os.environ.get(
    "GRASSFLOW_MODELS_URL", "https://models.dev/api.json"
)

# 本地缓存
_CACHE_DIR = Path.home() / ".Grass" / "cache"
_CACHE_FILENAME = "models.json"
_CACHE_TTL_SECONDS = 300  # 5 分钟

# 后台刷新间隔（秒）
_REFRESH_INTERVAL = 3600  # 1 小时

# 环境变量开关
_DISABLE_REMOTE_FETCH = os.environ.get(
    "GRASSFLOW_DISABLE_MODELS_FETCH", ""
).lower() in ("1", "true", "yes")
_LOCAL_MODELS_PATH = os.environ.get("GRASSFLOW_MODELS_PATH", "")

# Provider 默认端点映射
_PROVIDER_ENDPOINTS: Dict[str, str] = {
    "openai": "https://api.openai.com/v1/models",
    "deepseek": "https://api.deepseek.com/models",
    "anthropic": "https://api.anthropic.com/v1/models",
    "ollama": "http://localhost:11434/api/tags",
}

# Provider 环境变量映射
_PROVIDER_ENV_VARS: Dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "ollama": "",  # Ollama 不需要 API key
}

# Provider 默认 base URL
_PROVIDER_BASE_URLS: Dict[str, str] = {
    "openai": "https://api.openai.com",
    "deepseek": "https://api.deepseek.com",
    "anthropic": "https://api.anthropic.com",
    "ollama": "http://localhost:11434",
}


# ============================================================================
# 数据模型
# ============================================================================


@dataclass(frozen=True)
class ModelInfo:
    """模型信息

    Attributes:
        id: 模型 ID（provider 内唯一，如 "gpt-4o"）
        name: 显示名称（如 "GPT-4o"）
        provider: 所属 provider（如 "openai"）
        context_window: 上下文窗口大小（tokens），0 表示未知
        max_tokens: 最大输出 tokens，0 表示未知
        family: 模型家族（如 "gpt-4", "deepseek"）
        reasoning: 是否支持推理/思考模式
        tool_call: 是否支持工具调用
        temperature: 是否支持 temperature 参数
        attachment: 是否支持附件/多模态输入
        input_modalities: 输入模态列表（如 ["text", "image"]）
        output_modalities: 输出模态列表（如 ["text"]）
        cost_input: 输入价格（美元/百万 tokens），0 表示未知
        cost_output: 输出价格（美元/百万 tokens），0 表示未知
        release_date: 发布日期（YYYY-MM-DD）
        status: 模型状态（"active" / "alpha" / "beta" / "deprecated"）
        raw: 原始 API 返回数据
    """

    id: str
    name: str = ""
    provider: str = ""
    context_window: int = 0
    max_tokens: int = 0
    family: str = ""
    reasoning: bool = False
    tool_call: bool = True
    temperature: bool = True
    attachment: bool = False
    input_modalities: List[str] = field(default_factory=lambda: ["text"])
    output_modalities: List[str] = field(default_factory=lambda: ["text"])
    cost_input: float = 0.0
    cost_output: float = 0.0
    release_date: str = ""
    status: str = "active"
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典（排除 raw）"""
        d = asdict(self)
        d.pop("raw", None)
        return d

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "ModelInfo":
        """从字典反序列化"""
        return ModelInfo(**{k: v for k, v in data.items() if k != "raw"})


@dataclass
class DiscoveryResult:
    """发现结果

    Attributes:
        provider: provider 名称
        models: 模型列表
        source: 数据来源（"models_dev" / "api" / "cache" / "fallback"）
        fetched_at: 获取时间戳
        error: 错误信息（如果有）
    """

    provider: str
    models: List[ModelInfo] = field(default_factory=list)
    source: str = ""
    fetched_at: float = 0.0
    error: Optional[str] = None


# ============================================================================
# 缓存层
# ============================================================================


class ModelCache:
    """模型缓存 — 文件系统 + 内存双层缓存

    缓存结构 (~/.Grass/cache/models.json):
    {
        "fetched_at": 1234567890.0,
        "providers": {
            "openai": {
                "models": { "gpt-4o": {...}, ... },
                "source": "models_dev",
                "fetched_at": 1234567890.0
            },
            ...
        }
    }
    """

    def __init__(self, cache_dir: Optional[Path] = None, ttl: int = _CACHE_TTL_SECONDS):
        self._cache_dir = cache_dir or _CACHE_DIR
        self._cache_file = self._cache_dir / _CACHE_FILENAME
        self._ttl = ttl

        # 内存缓存
        self._memory_cache: Dict[str, Dict[str, Any]] = {}
        self._memory_fetched_at: float = 0.0

    def _ensure_dir(self) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _read_file_cache(self) -> Optional[Dict[str, Any]]:
        """读取文件缓存"""
        if not self._cache_file.exists():
            return None
        try:
            with open(self._cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.debug(f"读取缓存文件失败: {e}")
            return None

    def _write_file_cache(self, data: Dict[str, Any]) -> None:
        """写入文件缓存"""
        self._ensure_dir()
        try:
            with open(self._cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except OSError as e:
            logger.warning(f"写入缓存文件失败: {e}")

    def get(self, provider: str) -> Optional[List[ModelInfo]]:
        """从缓存获取模型列表

        优先内存缓存，其次文件缓存。超过 TTL 返回 None。
        """
        now = time.time()

        # 1. 内存缓存
        if provider in self._memory_cache:
            entry = self._memory_cache[provider]
            if now - entry.get("fetched_at", 0) < self._ttl:
                return self._deserialize_models(entry.get("models", {}), provider)

        # 2. 文件缓存
        file_data = self._read_file_cache()
        if file_data and "providers" in file_data:
            prov_data = file_data["providers"].get(provider)
            if prov_data and now - prov_data.get("fetched_at", 0) < self._ttl:
                # 回填内存缓存
                self._memory_cache[provider] = prov_data
                return self._deserialize_models(prov_data.get("models", {}), provider)

        return None

    def put(self, provider: str, models: List[ModelInfo], source: str) -> None:
        """写入缓存"""
        now = time.time()
        models_dict = {m.id: m.to_dict() for m in models}

        entry = {
            "models": models_dict,
            "source": source,
            "fetched_at": now,
        }

        # 写入内存
        self._memory_cache[provider] = entry

        # 合并写入文件
        file_data = self._read_file_cache() or {"providers": {}}
        file_data["providers"][provider] = entry
        file_data["fetched_at"] = now
        self._write_file_cache(file_data)

    def invalidate(self, provider: Optional[str] = None) -> None:
        """使缓存失效

        Args:
            provider: 指定 provider 名称。None 表示清除全部。
        """
        if provider:
            self._memory_cache.pop(provider, None)
            file_data = self._read_file_cache()
            if file_data and "providers" in file_data:
                file_data["providers"].pop(provider, None)
                self._write_file_cache(file_data)
        else:
            self._memory_cache.clear()
            if self._cache_file.exists():
                self._cache_file.unlink(missing_ok=True)

    @staticmethod
    def _deserialize_models(
        models_dict: Dict[str, Dict[str, Any]], provider: str
    ) -> List[ModelInfo]:
        """反序列化模型字典为 ModelInfo 列表"""
        result = []
        for model_id, data in models_dict.items():
            try:
                info = ModelInfo.from_dict(data)
                result.append(info)
            except Exception as e:
                logger.debug(f"反序列化模型 {provider}/{model_id} 失败: {e}")
        return result


# 全局缓存实例
_model_cache = ModelCache()


# ============================================================================
# models.dev 解析器
# ============================================================================


def _parse_models_dev_provider(
    provider_id: str, provider_data: Dict[str, Any]
) -> List[ModelInfo]:
    """将 models.dev 的 provider 数据解析为 ModelInfo 列表

    models.dev 格式:
    {
        "id": "openai",
        "name": "OpenAI",
        "env": ["OPENAI_API_KEY"],
        "api": "https://api.openai.com/v1",
        "models": {
            "gpt-4o": {
                "id": "gpt-4o",
                "name": "GPT-4o",
                "family": "gpt-4",
                "attachment": true,
                "reasoning": false,
                "tool_call": true,
                "temperature": true,
                "release_date": "2024-05-13",
                "modalities": {"input": ["text", "image"], "output": ["text"]},
                "limit": {"context": 128000, "output": 16384},
                "cost": {"input": 2.5, "output": 10.0}
            }
        }
    }
    """
    models_data = provider_data.get("models", {})
    result: List[ModelInfo] = []

    for model_id, model_data in models_data.items():
        if not isinstance(model_data, dict):
            continue

        # 跳过已弃用的模型
        status = model_data.get("status", "active")
        if status == "deprecated":
            continue

        limit = model_data.get("limit", {})
        cost = model_data.get("cost", {})
        modalities = model_data.get("modalities", {})

        info = ModelInfo(
            id=model_data.get("id", model_id),
            name=model_data.get("name", model_id),
            provider=provider_id,
            context_window=limit.get("context", 0),
            max_tokens=limit.get("output", 0),
            family=model_data.get("family", ""),
            reasoning=model_data.get("reasoning", False),
            tool_call=model_data.get("tool_call", True),
            temperature=model_data.get("temperature", True),
            attachment=model_data.get("attachment", False),
            input_modalities=modalities.get("input", ["text"]),
            output_modalities=modalities.get("output", ["text"]),
            cost_input=cost.get("input", 0.0),
            cost_output=cost.get("output", 0.0),
            release_date=model_data.get("release_date", ""),
            status=status,
            raw=model_data,
        )
        result.append(info)

    return result


async def _fetch_models_dev(
    session: aiohttp.ClientSession,
) -> Dict[str, List[ModelInfo]]:
    """从 models.dev 获取全部 provider 的模型目录

    Returns:
        { provider_id: [ModelInfo, ...] }
    """
    url = _LOCAL_MODELS_PATH if _LOCAL_MODELS_PATH else MODELS_DEV_URL

    # 本地文件路径
    if _LOCAL_MODELS_PATH and os.path.isfile(_LOCAL_MODELS_PATH):
        logger.info(f"从本地文件加载模型目录: {_LOCAL_MODELS_PATH}")
        with open(_LOCAL_MODELS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return _parse_all_providers(data)

    if _DISABLE_REMOTE_FETCH:
        logger.info("远程模型获取已禁用 (GRASSFLOW_DISABLE_MODELS_FETCH)")
        return {}

    logger.info(f"从 models.dev 获取模型目录: {url}")
    try:
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            if resp.status != 200:
                logger.warning(f"models.dev 返回 HTTP {resp.status}")
                return {}
            data = await resp.json(content_type=None)
            return _parse_all_providers(data)
    except Exception as e:
        logger.warning(f"获取 models.dev 失败: {e}")
        return {}


def _parse_all_providers(
    data: Dict[str, Any],
) -> Dict[str, List[ModelInfo]]:
    """解析 models.dev 完整 JSON 为 {provider: [ModelInfo]}"""
    result: Dict[str, List[ModelInfo]] = {}
    for provider_id, provider_data in data.items():
        if not isinstance(provider_data, dict):
            continue
        models = _parse_models_dev_provider(provider_id, provider_data)
        if models:
            result[provider_id] = models
    return result


# ============================================================================
# Provider 原生 /v1/models 解析器
# ============================================================================


def _parse_openai_models_response(
    data: Dict[str, Any], provider: str
) -> List[ModelInfo]:
    """解析 OpenAI 兼容的 /v1/models 响应

    格式: { "data": [{ "id": "gpt-4o", "object": "model", ... }] }
    """
    models_list = data.get("data", [])
    result: List[ModelInfo] = []
    for item in models_list:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id", "")
        if not model_id:
            continue

        # 跳过非聊天模型（embedding、tts、whisper 等）
        obj_type = item.get("object", "model")
        if obj_type not in ("model", "chat.completion"):
            continue

        result.append(ModelInfo(
            id=model_id,
            name=item.get("owned_by", model_id),
            provider=provider,
            raw=item,
        ))
    return result


def _parse_anthropic_models_response(
    data: Dict[str, Any], provider: str
) -> List[ModelInfo]:
    """解析 Anthropic /v1/models 响应

    格式: { "data": [{ "id": "claude-3-5-sonnet-20241022", "display_name": "...", ... }] }
    """
    models_list = data.get("data", [])
    result: List[ModelInfo] = []
    for item in models_list:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id", "")
        if not model_id:
            continue

        result.append(ModelInfo(
            id=model_id,
            name=item.get("display_name", model_id),
            provider=provider,
            raw=item,
        ))
    return result


def _parse_ollama_models_response(
    data: Dict[str, Any], provider: str
) -> List[ModelInfo]:
    """解析 Ollama /api/tags 响应

    格式: { "models": [{ "name": "llama3:latest", "size": ..., ... }] }
    """
    models_list = data.get("models", [])
    result: List[ModelInfo] = []
    for item in models_list:
        if not isinstance(item, dict):
            continue
        name = item.get("name", "")
        if not name:
            continue

        # Ollama 的 name 格式是 "model:tag"
        model_id = name.split(":")[0]

        # 从 details 提取信息
        details = item.get("details", {})
        family = details.get("family", "")

        # 尝试从 model_info 提取 context length
        model_info = item.get("model_info", {})
        context_window = 0
        for key, val in model_info.items():
            if "context_length" in key and isinstance(val, int):
                context_window = max(context_window, val)

        result.append(ModelInfo(
            id=model_id,
            name=name,
            provider=provider,
            context_window=context_window,
            family=family,
            reasoning=False,
            tool_call=True,
            temperature=True,
            raw=item,
        ))
    return result


async def _fetch_provider_models(
    session: aiohttp.ClientSession,
    provider: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> List[ModelInfo]:
    """从 provider 的原生 /v1/models 端点获取模型列表

    Args:
        session: aiohttp 会话
        provider: provider 名称
        api_key: API key（可选，会尝试从环境变量获取）
        base_url: base URL（可选，使用 provider 默认值）

    Returns:
        ModelInfo 列表
    """
    # 确定端点 URL
    if base_url:
        # 从 base_url 构造 models 端点
        base = base_url.rstrip("/")
        if provider == "anthropic":
            url = f"{base}/v1/models"
        elif provider == "ollama":
            url = f"{base}/api/tags"
        else:
            url = f"{base}/v1/models"
    elif provider in _PROVIDER_ENDPOINTS:
        url = _PROVIDER_ENDPOINTS[provider]
    else:
        logger.debug(f"Provider '{provider}' 没有已知的 models 端点")
        return []

    # 确定 API key
    if not api_key and provider in _PROVIDER_ENV_VARS:
        env_var = _PROVIDER_ENV_VARS[provider]
        if env_var:
            api_key = os.environ.get(env_var)

    # 构造请求头
    headers: Dict[str, str] = {"Accept": "application/json"}
    if api_key:
        if provider == "anthropic":
            headers["x-api-key"] = api_key
            headers["anthropic-version"] = "2023-06-01"
        else:
            headers["Authorization"] = f"Bearer {api_key}"

    logger.info(f"从 {provider} 获取模型列表: {url}")

    try:
        async with session.get(
            url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                logger.warning(
                    f"{provider} /models 返回 HTTP {resp.status}: {body[:200]}"
                )
                return []
            data = await resp.json(content_type=None)

            # 根据 provider 类型解析
            if provider == "anthropic":
                return _parse_anthropic_models_response(data, provider)
            elif provider == "ollama":
                return _parse_ollama_models_response(data, provider)
            else:
                # OpenAI 兼容格式（openai, deepseek, 自定义）
                return _parse_openai_models_response(data, provider)
    except Exception as e:
        logger.warning(f"从 {provider} 获取模型列表失败: {e}")
        return []


# ============================================================================
# 主入口
# ============================================================================


async def discover_models(
    provider: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    *,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> DiscoveryResult:
    """发现指定 provider 的可用模型

    发现策略：
      1. 检查本地缓存（除非 force_refresh）
      2. 尝试从 models.dev 获取该 provider 的模型目录
      3. 如果 models.dev 没有该 provider，回退到原生 /v1/models 端点
      4. 缓存结果

    Args:
        provider: provider 名称（如 "openai", "deepseek", "anthropic", "ollama"）
        api_key: API key（可选，会尝试从环境变量获取）
        base_url: base URL（可选，使用 provider 默认值）
        use_cache: 是否使用缓存（默认 True）
        force_refresh: 强制刷新，忽略缓存（默认 False）

    Returns:
        DiscoveryResult 包含模型列表和元数据
    """
    now = time.time()

    # 1. 检查缓存
    if use_cache and not force_refresh:
        cached = _model_cache.get(provider)
        if cached is not None:
            logger.debug(f"从缓存获取 {provider} 模型列表: {len(cached)} 个")
            return DiscoveryResult(
                provider=provider,
                models=cached,
                source="cache",
                fetched_at=now,
            )

    # 2. 从 models.dev 获取
    models: List[ModelInfo] = []
    source = ""

    async with aiohttp.ClientSession() as session:
        all_providers = await _fetch_models_dev(session)

        if provider in all_providers:
            models = all_providers[provider]
            source = "models_dev"
            logger.info(f"从 models.dev 获取 {provider} 模型: {len(models)} 个")

            # 缓存全部 provider 数据（如果拿到了多个）
            if use_cache:
                for prov_id, prov_models in all_providers.items():
                    if prov_id != provider:
                        _model_cache.put(prov_id, prov_models, "models_dev")
        else:
            # 3. 回退到原生 /v1/models 端点
            logger.info(f"models.dev 中没有 {provider}，尝试原生端点发现")
            models = await _fetch_provider_models(
                session, provider, api_key, base_url
            )
            source = "api" if models else "fallback"

    # 4. 缓存结果
    if use_cache and models:
        _model_cache.put(provider, models, source)

    return DiscoveryResult(
        provider=provider,
        models=models,
        source=source,
        fetched_at=now,
    )


async def discover_all_models(
    api_keys: Optional[Dict[str, str]] = None,
    *,
    providers: Optional[List[str]] = None,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> Dict[str, DiscoveryResult]:
    """发现多个 provider 的模型

    Args:
        api_keys: { provider: api_key } 映射（可选）
        providers: 要发现的 provider 列表。None 表示从 models.dev 获取全部。
        use_cache: 是否使用缓存
        force_refresh: 强制刷新

    Returns:
        { provider: DiscoveryResult }
    """
    api_keys = api_keys or {}
    results: Dict[str, DiscoveryResult] = {}

    if providers is None:
        # 从 models.dev 获取全部
        async with aiohttp.ClientSession() as session:
            all_providers = await _fetch_models_dev(session)

        if all_providers:
            now = time.time()
            for prov_id, prov_models in all_providers.items():
                if use_cache:
                    _model_cache.put(prov_id, prov_models, "models_dev")
                results[prov_id] = DiscoveryResult(
                    provider=prov_id,
                    models=prov_models,
                    source="models_dev",
                    fetched_at=now,
                )
            return results

    # 逐个 provider 发现
    target_providers = providers or list(_PROVIDER_ENDPOINTS.keys())
    tasks = [
        discover_models(
            prov,
            api_key=api_keys.get(prov),
            use_cache=use_cache,
            force_refresh=force_refresh,
        )
        for prov in target_providers
    ]
    discovery_results = await asyncio.gather(*tasks, return_exceptions=True)

    for prov, result in zip(target_providers, discovery_results):
        if isinstance(result, Exception):
            results[prov] = DiscoveryResult(
                provider=prov, error=str(result), fetched_at=time.time()
            )
        else:
            results[prov] = result

    return results


# ============================================================================
# 同步便捷接口
# ============================================================================


def discover_models_sync(
    provider: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    **kwargs,
) -> DiscoveryResult:
    """同步版本的 discover_models"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # 在已有的事件循环中——创建任务并阻塞等待
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                asyncio.run,
                discover_models(provider, api_key, base_url, **kwargs),
            )
            return future.result(timeout=30)
    else:
        return asyncio.run(
            discover_models(provider, api_key, base_url, **kwargs)
        )


# ============================================================================
# 查询接口
# ============================================================================


def get_cached_models(provider: str) -> List[ModelInfo]:
    """从缓存获取模型列表（不发请求）

    Args:
        provider: provider 名称

    Returns:
        ModelInfo 列表。缓存为空时返回空列表。
    """
    return _model_cache.get(provider) or []


def get_model_info(provider: str, model_id: str) -> Optional[ModelInfo]:
    """查询单个模型的能力信息（仅从缓存）

    Args:
        provider: provider 名称
        model_id: 模型 ID

    Returns:
        ModelInfo 或 None（缓存中不存在时）
    """
    models = _model_cache.get(provider)
    if not models:
        return None
    for m in models:
        if m.id == model_id:
            return m
    return None


def list_providers() -> List[str]:
    """列出缓存中所有可用的 provider"""
    file_data = _model_cache._read_file_cache()
    if file_data and "providers" in file_data:
        return list(file_data["providers"].keys())
    return list(_model_cache._memory_cache.keys())


def invalidate_cache(provider: Optional[str] = None) -> None:
    """使缓存失效

    Args:
        provider: 指定 provider 名称。None 表示清除全部。
    """
    _model_cache.invalidate(provider)


# ============================================================================
# 环境变量自动发现
# ============================================================================


def detect_available_providers() -> List[str]:
    """检测环境变量中可用的 provider

    检查各 provider 对应的 API key 环境变量是否已设置。
    Ollama 始终包含（不需要 API key）。

    Returns:
        可用 provider 名称列表
    """
    available = []
    for provider, env_var in _PROVIDER_ENV_VARS.items():
        if not env_var:
            # 无环境变量要求（如 Ollama）
            available.append(provider)
        elif os.environ.get(env_var):
            available.append(provider)
    return available
