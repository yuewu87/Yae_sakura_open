"""
Vault 记忆管理器 — 读写 Obsidian 兼容的 .md 文件
"""
import os
import re
import json
import math
import logging
from datetime import datetime
from collections import defaultdict

logger = logging.getLogger("Sakura-Vault")


def _vault_path():
    return os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "sakura_vault"))


_memories_cache = None


def _refresh_cache():
    global _memories_cache
    vp = _vault_path()
    _memories_cache = []
    if not os.path.exists(vp):
        return
    for f in sorted(os.listdir(vp)):
        if f.endswith(".md"):
            mem = _parse_memory(os.path.join(vp, f))
            if mem:
                _memories_cache.append(mem)


def _parse_memory(filepath):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            text = f.read()
    except Exception:
        return None
    fm = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].strip().split("\n"):
                line = line.strip()
                if ":" in line:
                    k, v = line.split(":", 1)
                    k, v = k.strip(), v.strip()
                    if v.startswith("[") and v.endswith("]"):
                        v = [x.strip().strip('"').strip("'") for x in v[1:-1].split(",") if x.strip()]
                    elif v.isdigit():
                        v = int(v)
                    fm[k] = v
            body = parts[2].strip()
    fm["content"] = body
    fm["file"] = os.path.basename(filepath)
    fm.setdefault("layer", "active")
    return fm


def add_memory(mem_type, content, importance=5, entities=None, date=None):
    vp = _vault_path()
    os.makedirs(vp, exist_ok=True)

    date_str = (date or datetime.now()).strftime("%Y-%m-%d %H:%M")
    slug = re.sub(r'[^\w\s-]', '', content[:30]).strip().lower()
    slug = re.sub(r'[-\s]+', '-', slug)
    if not slug:
        slug = "memory"
    base = f"{datetime.now().strftime('%Y-%m-%d')}-{slug}"
    filename = f"{base}.md"
    # 防止同名覆盖
    n = 1
    while os.path.exists(os.path.join(vp, filename)):
        filename = f"{base}-{n}.md"
        n += 1
    filepath = os.path.join(vp, filename)

    existing = get_all_memories()
    for mem in existing:
        if mem.get("content", "") == content:
            return None

    ent_str = json.dumps(entities or [], ensure_ascii=False)
    fm = f"""---
type: {mem_type}
importance: {importance}
layer: active
entities: {ent_str}
date: {date_str}
---

{content}
"""
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(fm)

    _refresh_cache()
    global _emb_ready
    _emb_ready = False  # 新记忆写入，向量需重建
    _invalidate_profile()  # 画像缓存也刷新
    logger.info(f"记忆已写入: {filename}")
    return filename


def get_all_memories():
    global _memories_cache
    if _memories_cache is None:
        _refresh_cache()
    return _memories_cache or []


# ---- 向量检索 (text2vec) ----
_emb_model = None
_emb_vectors = None       # numpy array [N, dims]
_emb_ready = False
_MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "text_models", "text2vec-base-chinese")


def _get_emb_model():
    global _emb_model
    if _emb_model is None:
        from text2vec import SentenceModel
        _emb_model = SentenceModel(_MODEL_PATH)
    return _emb_model


def _build_vectors():
    global _emb_vectors, _emb_ready
    if _emb_ready:
        return

    memories = get_all_memories()
    if not memories:
        _emb_ready = True
        return

    texts = [m.get("content", "") for m in memories]
    try:
        model = _get_emb_model()
        import numpy as np
        _emb_vectors = np.array(model.encode(texts, show_progress_bar=False))
    except Exception as e:
        logger.warning(f"向量构建失败: {e}")
    _emb_ready = True


def search_memories(query, top_k=5):
    """混合检索：Jaccard 关键词 + text2vec 语义嵌入"""
    try:
        from need.knowledge.retriever import _tokenize
    except ImportError:
        return get_all_memories()[:top_k]

    all_mems = get_all_memories()
    if not all_mems or not query.strip():
        return sorted(all_mems, key=lambda m: m.get("importance", 5), reverse=True)[:top_k]

    # 分层：core + active 优先，archive 兜底
    active_mems = [m for m in all_mems if m.get("layer") in ("core", "active")]
    archive_mems = [m for m in all_mems if m.get("layer") == "archive"]
    memories = active_mems if active_mems else all_mems

    query_tokens = _tokenize(query)
    if not query_tokens:
        return sorted(memories, key=lambda m: m.get("importance", 5), reverse=True)[:top_k]

    _build_vectors()

    q_set = set(query_tokens)
    scored = {}
    for i, mem in enumerate(memories):
        text = mem.get("content", "") + " ".join(mem.get("entities", []))
        mem_tokens = _tokenize(text)
        m_set = set(mem_tokens)

        # 路1: Jaccard 关键词精确匹配 (权重 0.3)
        union = q_set | m_set
        jaccard = len(q_set & m_set) / len(union) if union else 0
        base = jaccard * 0.3
        base *= (1 + mem.get("importance", 5) / 60)
        if base > 0.001:
            scored[i] = base

    # 路2: text2vec 语义嵌入 (权重 0.7)
    if _emb_vectors is not None and len(_emb_vectors) > 0:
        try:
            import numpy as np
            q_vec = np.array(_get_emb_model().encode([query], show_progress_bar=False))
            sims = np.dot(q_vec, _emb_vectors.T)[0]
            for i, sim in enumerate(sims):
                score = float(sim) * 0.7
                if score > 0.001:
                    scored[i] = scored.get(i, 0) + score
        except Exception:
            pass

    ranked = sorted(scored.items(), key=lambda x: x[1], reverse=True)
    result = [memories[i] for i, _ in ranked[:top_k]]

    # archive 兜底：活跃层结果不足时补充
    if len(result) < top_k and archive_mems:
        for m in archive_mems:
            if m not in result:
                result.append(m)
            if len(result) >= top_k:
                break

    return result


def degrade_stale(days_event=7, days_promise=14):
    """随时间流逝自动降级：事件>7天、约定>14天 → archive"""
    from datetime import datetime as dt
    now = dt.now()
    count = 0
    vp = _vault_path()
    if not os.path.exists(vp):
        return 0
    for f in os.listdir(vp):
        if not f.endswith(".md"):
            continue
        path = os.path.join(vp, f)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
            if "layer: active" not in text:
                continue
            mem = _parse_memory(path)
            if not mem:
                continue
            date_str = mem.get("date", "")
            try:
                mem_date = dt.strptime(date_str[:10], "%Y-%m-%d")
                age = (now - mem_date).days
            except Exception:
                continue
            mem_type = mem.get("type", "")
            if (mem_type == "event" and age >= days_event) or \
               (mem_type == "promise" and age >= days_promise):
                text = text.replace("layer: active", "layer: archive")
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text)
                count += 1
        except Exception:
            pass
    if count:
        _refresh_cache()
        global _emb_ready
        _emb_ready = False
        _invalidate_profile()
    return count


# ---- 用户画像缓存 ----
_profile_cache = None


def get_user_profile():
    """返回 core 层记忆（缓存，新记忆写入时自动刷新）"""
    global _profile_cache
    if _profile_cache is None:
        _profile_cache = [m for m in get_all_memories()
                          if m.get("layer") == "core"]
    return _profile_cache


def _invalidate_profile():
    global _profile_cache
    _profile_cache = None


def set_layer(content_substring, new_layer):
    """直接设置某条记忆的 layer"""
    vp = _vault_path()
    for f in os.listdir(vp):
        if f.endswith(".md"):
            path = os.path.join(vp, f)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    text = fh.read()
                if content_substring in text:
                    text = re.sub(r'layer: \w+', f'layer: {new_layer}', text)
                    with open(path, "w", encoding="utf-8") as fh:
                        fh.write(text)
                    _refresh_cache()
                    global _emb_ready
                    _emb_ready = False
                    _invalidate_profile()
                    return True
            except Exception:
                pass
    return False


def archive_memories(keywords):
    """将匹配的记忆降级到 archive 层（不删除）"""
    vp = _vault_path()
    if not os.path.exists(vp):
        return 0
    count = 0
    for f in os.listdir(vp):
        if f.endswith(".md"):
            path = os.path.join(vp, f)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    content = fh.read()
                for kw in keywords:
                    if kw in content and "layer: active" in content:
                        content = content.replace("layer: active", "layer: archive")
                        with open(path, "w", encoding="utf-8") as fh:
                            fh.write(content)
                        count += 1
                        break
            except Exception:
                pass
    if count:
        _refresh_cache()
        global _emb_ready
        _emb_ready = False
        _invalidate_profile()
    return count


def remove_memories(keywords):
    """删除内容含有关键词的记忆文件"""
    vp = _vault_path()
    if not os.path.exists(vp):
        return 0
    removed = 0
    for f in os.listdir(vp):
        if f.endswith(".md"):
            path = os.path.join(vp, f)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    content = fh.read()
                for kw in keywords:
                    if kw in content:
                        os.remove(path)
                        removed += 1
                        break
            except Exception:
                pass
    if removed:
        _refresh_cache()
        global _emb_ready
        _emb_ready = False
        _invalidate_profile()
    return removed


def clear_vault():
    """清空 vault 所有文件"""
    vp = _vault_path()
    if os.path.exists(vp):
        for f in os.listdir(vp):
            if f.endswith(".md"):
                os.remove(os.path.join(vp, f))
    global _memories_cache
    _memories_cache = []
    logger.info("Vault 已清空")
