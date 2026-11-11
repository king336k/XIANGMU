"""Bounded, local BGE ONNX encoder with OpenAI-compatible float embeddings."""
import asyncio
import hashlib
import hmac
import json
import os
from pathlib import Path
import threading
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

MODEL = "bge-small-zh-v1.5"
MODEL_SHA256 = "69a0b846f4f116b5e6aabf9546ea6754d02264f3211a13a1bd69b31b8040749a"
TOKENIZER_SHA256 = "48cea5d44424912a6fd1ea647bf4fe50b55ab8b1e5879c3275f80e339e8fae26"

class InputLimitError(ValueError):
    pass

class Encoder:
    model = MODEL
    def __init__(self, root):
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer
        self.np, self.ort = np, ort
        root = Path(root)
        for name, expected in [("model.onnx", MODEL_SHA256), ("tokenizer.json", TOKENIZER_SHA256)]:
            digest = hashlib.sha256()
            with (root / name).open("rb") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != expected:
                raise RuntimeError("model artifact checksum mismatch")
        self.tokenizer = Tokenizer.from_file(str(root / "tokenizer.json"))
        self.tokenizer.no_truncation()
        self.tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        self.session = ort.InferenceSession(str(root / "model.onnx"), sess_options=options, providers=["CPUExecutionProvider"])

    def encode(self, texts):
        np = self.np
        encoded = self.tokenizer.encode_batch(texts)
        lengths = [sum(item.attention_mask) for item in encoded]
        if any(length > 512 for length in lengths):
            raise InputLimitError("input exceeds 512 tokens including special tokens")
        inputs = {"input_ids": np.asarray([e.ids for e in encoded], dtype=np.int64),
                  "attention_mask": np.asarray([e.attention_mask for e in encoded], dtype=np.int64),
                  "token_type_ids": np.asarray([e.type_ids for e in encoded], dtype=np.int64)}
        inputs = {item.name: inputs[item.name] for item in self.session.get_inputs()}
        options = self.ort.RunOptions()
        timer = threading.Timer(15, lambda: setattr(options, "terminate", True))
        timer.daemon = True
        timer.start()
        try:
            hidden = self.session.run(None, inputs, run_options=options)[0]
        finally:
            timer.cancel()
        # Official BAAI pooling config: CLS token, not mean pooling. L2 normalize.
        vectors = hidden[:, 0, :]
        vectors = vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)
        if vectors.shape != (len(texts), 512) or not np.isfinite(vectors).all():
            raise RuntimeError("encoder returned invalid vectors")
        return vectors.tolist(), lengths


def create_app(encoder, key):
    if not isinstance(key, str) or len(key) < 8:
        raise RuntimeError("embedding service key must be configured")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    @app.middleware("http")
    async def request_log(request,call_next):
        started=time.monotonic();status=500
        try:
            response=await call_next(request);status=response.status_code
            return response
        finally:
            path=request.url.path
            if path!='/health':
                print(json.dumps({'component':'embedding','event':'request','method':request.method,
                    'path':path if path in {'/v1/models','/v1/embeddings'} else '[unmatched]',
                    'status':status,'duration_ms':round((time.monotonic()-started)*1000)}),flush=True)
    gate = asyncio.Semaphore(1)
    def error(status, message, code="invalid_request_error"):
        return JSONResponse({"error": {"message": message, "type": code, "code": code}}, status_code=status)
    def allowed(request):
        return hmac.compare_digest(request.headers.get("authorization", "").encode("utf-8"), ("Bearer " + key).encode("utf-8"))
    @app.get("/health")
    async def health():
        return {"status": "ready", "model": encoder.model, "dimensions": 512, "max_input_tokens": 512, "max_batch": 16}
    @app.get("/v1/models")
    async def models(request: Request):
        if not allowed(request):
            return error(401, "valid bearer key required", "authentication_error")
        return {"object": "list", "data": [{"id": encoder.model, "object": "model", "owned_by": "BAAI", "created": 0}]}
    @app.post("/v1/embeddings")
    async def embeddings(request: Request):
        if not allowed(request):
            return error(401, "valid bearer key required", "authentication_error")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 65536:
                return error(413, "request body exceeds 64KiB", "request_too_large")
        try:
            data = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            return error(400, "valid JSON object required")
        if not isinstance(data, dict) or data.get("model") != encoder.model:
            return error(400, "unknown model")
        if data.get("encoding_format", "float") != "float" or data.get("dimensions", 512) != 512:
            return error(400, "only 512-dimensional float embeddings supported")
        texts = data.get("input")
        if isinstance(texts, str):
            texts = [texts]
        if not isinstance(texts, list) or not 1 <= len(texts) <= 16 or any(not isinstance(text, str) or not text.strip() or len(text) > 1024 for text in texts):
            return error(400, "input must contain 1..16 nonempty strings of at most 1024 characters")
        try:
            await asyncio.wait_for(gate.acquire(), timeout=0.1)
        except asyncio.TimeoutError:
            return error(429, "encoder busy; retry later", "rate_limit_error")
        try:
            vectors, counts = await run_in_threadpool(encoder.encode, texts)
        except InputLimitError:
            return error(400, "input exceeds 512 tokens including special tokens; split the text", "input_too_long")
        except Exception:
            return error(503, "encoder unavailable or execution time limit reached", "service_unavailable")
        finally:
            gate.release()
        return {"object": "list", "model": encoder.model, "data": [{"object": "embedding", "index": index, "embedding": vector} for index, vector in enumerate(vectors)], "usage": {"prompt_tokens": sum(counts), "total_tokens": sum(counts)}}
    return app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(create_app(Encoder(os.environ.get("MODEL_DIR", "/model")), os.environ.get("EMBEDDING_API_KEY", "")), host="0.0.0.0", port=18885, workers=1, access_log=False)
