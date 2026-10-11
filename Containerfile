FROM python:3.12-slim

ENV HF_HOME=/models \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    TOKENIZERS_PARALLELISM=false \
    PYTHONPATH=/workspace/projects/ukagaka-emotion

RUN python -m pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        torch \
    && python -m pip install --no-cache-dir \
        sentence-transformers \
        pytest \
        numpy

WORKDIR /workspace

