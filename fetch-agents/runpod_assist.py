"""
Optional RunPod Flash sidecar for expert-agent triage.

This does NOT replace Fetch.ai routing. It is only used by the Expert agent
to generate extra debugging hints before replying through uAgents.
"""
import os

DEFAULT_RUNPOD_FLASH_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"


def _is_enabled(var_name: str, default: bool = False) -> bool:
    raw = os.getenv(var_name, str(default)).strip().lower()
    return raw in {"1", "true", "yes", "on"}


try:
    from runpod_flash import GpuGroup, LiveServerless, remote

    _FLASH_SDK_AVAILABLE = True
except Exception:
    GpuGroup = None
    LiveServerless = None
    remote = None
    _FLASH_SDK_AVAILABLE = False


def _safe_int(var_name: str, default: int) -> int:
    try:
        return int(os.getenv(var_name, str(default)))
    except ValueError:
        return default


if _FLASH_SDK_AVAILABLE:
    _gpu_group_name = os.getenv("RUNPOD_FLASH_GPU_GROUP", "ANY").strip().upper()
    _gpu_group = getattr(GpuGroup, _gpu_group_name, GpuGroup.ANY)

    _flash_resource = LiveServerless(
        name=os.getenv("RUNPOD_FLASH_ENDPOINT_NAME", "hackoverflow-expert-flash"),
        gpus=[_gpu_group],
        workersMin=_safe_int("RUNPOD_FLASH_WORKERS_MIN", 0),
        workersMax=_safe_int("RUNPOD_FLASH_WORKERS_MAX", 1),
        idleTimeout=_safe_int("RUNPOD_FLASH_IDLE_TIMEOUT_MIN", 5),
    )

    @remote(
        resource_config=_flash_resource,
        dependencies=[
            "torch",
            "transformers>=4.44.0",
        ],
    )
    def _flash_triage_worker(prompt: str, model_name: str, max_new_tokens: int) -> dict:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        global _FLASH_MODEL_CACHE
        try:
            cache = _FLASH_MODEL_CACHE
        except NameError:
            _FLASH_MODEL_CACHE = {}
            cache = _FLASH_MODEL_CACHE

        if model_name not in cache:
            tokenizer = AutoTokenizer.from_pretrained(model_name)
            dtype = torch.float16 if torch.cuda.is_available() else torch.float32
            model = AutoModelForCausalLM.from_pretrained(model_name, torch_dtype=dtype)
            device = "cuda" if torch.cuda.is_available() else "cpu"
            model.to(device)
            model.eval()
            cache[model_name] = {
                "tokenizer": tokenizer,
                "model": model,
                "device": device,
            }

        tokenizer = cache[model_name]["tokenizer"]
        model = cache[model_name]["model"]
        device = cache[model_name]["device"]

        inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=1536)
        inputs = {k: v.to(device) for k, v in inputs.items()}
        output_ids = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            pad_token_id=tokenizer.eos_token_id,
        )
        new_tokens = output_ids[0][inputs["input_ids"].shape[1] :]
        hint = tokenizer.decode(new_tokens, skip_special_tokens=True).strip()

        if device == "cuda":
            device_name = torch.cuda.get_device_name(0)
        else:
            device_name = "CPU"

        return {
            "hint": hint,
            "model": model_name,
            "device": device_name,
        }

else:

    async def _flash_triage_worker(prompt: str, model_name: str, max_new_tokens: int) -> dict:
        raise RuntimeError("runpod-flash is not installed")


def _build_prompt(code: str, error_message: str, language: str) -> str:
    return (
        "You are helping an AI coding agent that is stuck.\n"
        "Give exactly 3 short numbered lines:\n"
        "1) likely root cause\n"
        "2) one fix to try now\n"
        "3) one quick verification step\n"
        "Keep it concise and practical.\n\n"
        f"Language: {language}\n"
        f"Error: {error_message}\n"
        f"Code:\n{code[:4000]}"
    )


async def get_runpod_triage_hint(code: str, error_message: str, language: str) -> str | None:
    """
    Return an optional triage hint produced via RunPod Flash remote execution.

    Required env vars:
    - RUNPOD_EXPERT_ENABLED=true
    - RUNPOD_API_KEY
    - Optional: RUNPOD_FLASH_HF_MODEL
    """
    if not _is_enabled("RUNPOD_EXPERT_ENABLED", default=False):
        return None

    if not _FLASH_SDK_AVAILABLE:
        return None

    if not os.getenv("RUNPOD_API_KEY", "").strip():
        return None

    runpod_model = os.getenv("RUNPOD_FLASH_HF_MODEL", DEFAULT_RUNPOD_FLASH_MODEL).strip()
    max_new_tokens = _safe_int("RUNPOD_FLASH_MAX_NEW_TOKENS", 180)
    prompt = _build_prompt(code=code, error_message=error_message, language=language)

    try:
        result = await _flash_triage_worker(prompt, runpod_model, max_new_tokens)
        hint = str(result.get("hint", "")).strip()
        if not hint:
            return None
        model = str(result.get("model", runpod_model)).strip()
        device = str(result.get("device", "unknown")).strip()
        return f"{hint}\n\n[RunPod Flash inference: {model} on {device}]"
    except Exception:
        return None

    return None
