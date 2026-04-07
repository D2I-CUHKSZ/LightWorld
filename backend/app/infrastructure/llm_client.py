"""
LLM客户端封装
统一使用OpenAI格式调用
"""

import json
import re
import base64
import mimetypes
from typing import Optional, Dict, Any, List
from openai import OpenAI
from openai import NotFoundError

from ..config import Config


class LLMClient:
    """LLM客户端"""
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None
    ):
        self.api_key = api_key or Config.LLM_API_KEY
        self.base_url = base_url or Config.LLM_BASE_URL
        self.model = model or Config.LLM_MODEL_NAME
        
        if not self.api_key:
            raise ValueError("LLM_API_KEY 未配置")
        
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=Config.LLM_TIMEOUT_SECONDS,
        )
    
    def chat(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[Dict] = None
    ) -> str:
        """
        发送聊天请求
        
        Args:
            messages: 消息列表
            temperature: 温度参数
            max_tokens: 最大token数
            response_format: 响应格式（如JSON模式）
            
        Returns:
            模型响应文本
        """
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        
        if response_format:
            kwargs["response_format"] = response_format
        
        response = self.client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content
        # 部分模型（如MiniMax M2.5）会在content中包含<think>思考内容，需要移除
        content = re.sub(r'<think>[\s\S]*?</think>', '', content).strip()
        return content
    
    def chat_json(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.3,
        max_tokens: int = 4096
    ) -> Dict[str, Any]:
        """
        发送聊天请求并返回JSON
        
        Args:
            messages: 消息列表
            temperature: 温度参数
            max_tokens: 最大token数
            
        Returns:
            解析后的JSON对象
        """
        response = self.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"}
        )
        # 清理markdown代码块标记
        cleaned_response = response.strip()
        cleaned_response = re.sub(r'^```(?:json)?\s*\n?', '', cleaned_response, flags=re.IGNORECASE)
        cleaned_response = re.sub(r'\n?```\s*$', '', cleaned_response)
        cleaned_response = cleaned_response.strip()

        try:
            return json.loads(cleaned_response)
        except json.JSONDecodeError:
            raise ValueError(f"LLM返回的JSON格式无效: {cleaned_response}")

    def transcribe_audio(
        self,
        audio_path: str,
        model: str = "whisper-1",
    ) -> str:
        """
        使用 OpenAI 兼容音频接口转写音频。

        Args:
            audio_path: 音频文件路径
            model: 转写模型名

        Returns:
            转写后的文本
        """
        if self._should_use_dashscope_chat_asr(model):
            return self._transcribe_audio_with_dashscope_chat(audio_path, model)

        try:
            with open(audio_path, "rb") as audio_file:
                response = self.client.audio.transcriptions.create(
                    model=model,
                    file=audio_file,
                )
        except NotFoundError as exc:
            raise RuntimeError(
                "当前音频转写服务返回 404。"
                "通常表示所配置的 base_url 不支持 /audio/transcriptions 接口，"
                f"或模型 `{model}` 在该服务中不存在。"
            ) from exc

        text = getattr(response, "text", "")
        if not text and isinstance(response, dict):
            text = str(response.get("text", "") or "")
        return str(text or "").strip()

    def _should_use_dashscope_chat_asr(self, model: str) -> bool:
        base_url = (self.base_url or "").lower()
        model_name = (model or "").lower()
        return "dashscope.aliyuncs.com" in base_url and model_name.startswith("qwen")

    def _transcribe_audio_with_dashscope_chat(self, audio_path: str, model: str) -> str:
        mime_type = mimetypes.guess_type(audio_path)[0] or "audio/mpeg"
        with open(audio_path, "rb") as audio_file:
            encoded_audio = base64.b64encode(audio_file.read()).decode("utf-8")
        data_uri = f"data:{mime_type};base64,{encoded_audio}"

        response = self.client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": data_uri,
                            },
                        }
                    ],
                }
            ],
            extra_body={
                "asr_options": {
                    "enable_itn": False,
                }
            },
        )
        content = response.choices[0].message.content
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = str(item.get("text", "") or "").strip()
                    if text:
                        parts.append(text)
            return "\n".join(parts).strip()
        return str(content or "").strip()
