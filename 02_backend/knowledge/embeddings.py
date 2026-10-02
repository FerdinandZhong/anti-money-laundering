"""Explicit local BGE-M3 ONNX embeddings. No downloads or implicit model swaps."""
from functools import lru_cache
import hashlib
from pathlib import Path
import threading


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


class Embedder:
    def __init__(self, directory):
        import onnxruntime as ort
        from tokenizers import Tokenizer
        path = Path(directory).expanduser().resolve()
        model = path / 'model_quantized.onnx'
        tokenizer = path / 'tokenizer.json'
        self.metadata = {'backend': 'bge_m3_onnx', 'dimension': 1024,
                         'model_sha256': digest(model), 'tokenizer_sha256': digest(tokenizer),
                         'max_tokens': 512, 'model_dir': str(path)}
        self.tokenizer = Tokenizer.from_file(str(tokenizer))
        self.tokenizer.enable_truncation(max_length=512)
        self.tokenizer.enable_padding(pad_id=1, pad_token='<pad>')
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 2
        self.session = ort.InferenceSession(str(model), sess_options=options, providers=['CPUExecutionProvider'])
        if 'dense_vecs' not in [o.name for o in self.session.get_outputs()]:
            raise ValueError('Expected BGE-M3 dense_vecs output')
        self.lock = threading.Lock()

    def encode(self, texts):
        import numpy as np
        vectors = []
        with self.lock:
            for start in range(0, len(texts), 4):
                tokens = self.tokenizer.encode_batch(texts[start:start + 4])
                inputs = {'input_ids': np.array([t.ids for t in tokens], dtype=np.int64),
                          'attention_mask': np.array([t.attention_mask for t in tokens], dtype=np.int64)}
                result = self.session.run(['dense_vecs'], inputs)[0]
                if result.shape[1] != 1024 or not np.isfinite(result).all():
                    raise ValueError('Invalid embedding output')
                norms = np.linalg.norm(result, axis=1, keepdims=True)
                if (norms == 0).any():
                    raise ValueError('Zero embedding')
                vectors.extend((result / norms).tolist())
        return vectors


@lru_cache(maxsize=2)
def _load(directory, model_stat, tokenizer_stat):
    return Embedder(directory)


def load(directory):
    path = Path(directory).expanduser().resolve()
    def signature(name):
        stat = (path / name).stat()
        return stat.st_size, stat.st_mtime_ns
    return _load(str(path), signature('model_quantized.onnx'), signature('tokenizer.json'))
