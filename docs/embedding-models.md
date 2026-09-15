# Embedding Models Guide

ChronosGraph uses **`cl-nagoya/ruri-v3-310m`** as its default local embedding
model. This document explains why it was chosen and lists alternatives you can
switch to based on your environment.

---

## Recommended Model: `cl-nagoya/ruri-v3-310m`

This is the most balanced local embedding model currently available for
Japanese contexts.

### Why it was chosen

1. **Strong Japanese performance**: It scores near the top on the latest JMTEB
   (Japanese Mixed Text Embedding Benchmark), capturing subtle Japanese nuances
   accurately.
2. **Standard output dimension (768)**: The 768-dimension output matches many
   modern Japanese models and offers a good balance between storage efficiency
   and accuracy.
3. **Long context window (8,192 tokens)**: Compared with older lightweight
   models (often 512 tokens), it embeds much longer documents in one pass,
   reducing fragmentation for RAG.
4. **Easy to install**: It uses the `ModernBERT` architecture and works with
   standard `transformers`. No separate MeCab or Sudachi installation is needed.
5. **Practical size**: At 310M parameters it runs at reasonable speed even on
   recent CPUs, with or without a GPU.

> [!NOTE]
> `LocalModelEmbeddingProvider` follows the `EMBEDDING_DIMENSION` value in
> `.env` (default: 768). If you change the model, update the setting to match
> the new model's output dimension.

---

## Alternatives

Consider the following models depending on your environment and use case. When
switching, first confirm `EMBEDDING_PROVIDER=local-model` in `.env`, then update
`LOCAL_MODEL_NAME`.

### 1. Prefer lighter / faster models

Use these if `ruri-v3-310m` feels too heavy or if you need the fastest possible
response.

- **`cl-nagoya/ruri-v3-130m`**: A good balance of speed and accuracy; a natural
  first step down from 310m.
- **`cl-nagoya/ruri-v3-70m`**: An ultra-lightweight model that runs fast on CPUs
  and edge devices.

### 2. Prefer multilingual coverage / proven track record

Use these if you handle languages other than Japanese or want a widely adopted
model.

- **`intfloat/multilingual-e5-large`**: One of the most widely used multilingual
  models; very stable.
- **`BAAI/bge-m3`**: Supports long contexts up to 8,192 tokens and can do both
  dense and sparse vector search.

### 3. Prefer maximum accuracy

Use this when you have plenty of compute (e.g. 10 GB+ GPU VRAM) and need deep
contextual understanding.

- **`oshizo/japanese-e5-mistral-7b_slerp`**: A large 7B-parameter model capable
  of understanding meaning that shorter models miss.

---

## Configuration

Set the following in `.env`:

```bash
EMBEDDING_PROVIDER=local-model
LOCAL_MODEL_NAME=cl-nagoya/ruri-v3-310m
```

For the full configuration reference, see
[Configuration Reference](./configuration.md).
