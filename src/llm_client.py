"""
Ollama LLM クライアント（共通モジュール）

他のスクリプトから import して使う。
Ollama が未起動の場合は自動で起動を試みる。

使い方:
  from llm_client import LLMClient
  llm = LLMClient()
  text = llm.generate("2040年の教室を描写して")
  text = llm.generate_with_image("この画像の品質を評価して", image_path)
"""

import base64
import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5-vl:7b"
FALLBACK_MODEL = "qwen2.5:7b"


class LLMClient:
    def __init__(self, model: str = DEFAULT_MODEL, timeout: int = 120):
        self.model = model
        self.timeout = timeout
        self._ensure_running()
        self.model = self._resolve_model(model)

    # ------------------------------------------------------------------
    # 起動・モデル管理
    # ------------------------------------------------------------------

    def _is_running(self) -> bool:
        try:
            urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=3)
            return True
        except Exception:
            return False

    def _ensure_running(self):
        if self._is_running():
            return
        print("[Ollama] サーバーが未起動です。起動を試みます...")
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(15):
            time.sleep(1)
            if self._is_running():
                print("[Ollama] 起動しました")
                return
        raise RuntimeError(
            "Ollama の起動に失敗しました。\n"
            "手動で起動してください: ollama serve\n"
            "未インストールの場合: setup-qwen.bat を実行してください"
        )

    def _list_models(self) -> list[str]:
        try:
            with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=5) as r:
                data = json.loads(r.read())
            return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []

    def _resolve_model(self, requested: str) -> str:
        """インストール済みモデルから最適なものを選ぶ"""
        available = self._list_models()
        if not available:
            print(f"[WARN] モデルが見つかりません。setup-qwen.bat を実行してください")
            return requested

        # 完全一致
        if requested in available:
            return requested

        # prefix マッチ（"qwen2.5-vl:7b" → "qwen2.5-vl:7b-..." など）
        base = requested.split(":")[0]
        for m in available:
            if m.startswith(base):
                print(f"[Ollama] モデル '{requested}' → '{m}' を使用")
                return m

        # フォールバック
        for fallback in [FALLBACK_MODEL, "qwen2.5:7b", "llama3.2:3b"]:
            for m in available:
                if m.startswith(fallback.split(":")[0]):
                    print(f"[Ollama] フォールバック: '{m}' を使用")
                    return m

        print(f"[WARN] 利用可能なモデル: {available}")
        return requested

    # ------------------------------------------------------------------
    # 生成
    # ------------------------------------------------------------------

    def _post(self, endpoint: str, payload: dict) -> str:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{OLLAMA_URL}{endpoint}",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            data = json.loads(r.read())
        return data.get("response") or data.get("message", {}).get("content", "")

    def generate(self, prompt: str, system: str = "") -> str:
        """テキスト生成"""
        payload: dict = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.7, "num_predict": 1024},
        }
        if system:
            payload["system"] = system
        return self._post("/api/generate", payload)

    def generate_with_image(self, prompt: str, image_path: Path | str, system: str = "") -> str:
        """画像付き生成（qwen2.5-vl など VL モデル必須）"""
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"画像が見つかりません: {image_path}")

        with open(image_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode("utf-8")

        payload: dict = {
            "model": self.model,
            "prompt": prompt,
            "images": [img_b64],
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 2048},
        }
        if system:
            payload["system"] = system
        return self._post("/api/generate", payload)

    def chat(self, messages: list[dict]) -> str:
        """チャット形式（複数ターン対応）"""
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.7},
        }
        return self._post("/api/chat", payload)
