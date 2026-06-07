"""
知识库检索器 — jieba 分词 + TF-IDF 向量化 + 余弦相似度
"""
import os
import json
import re
import math
import logging
from collections import defaultdict

logger = logging.getLogger("Sakura-Knowledge")

_knowledge_items = []
_loaded = False

# 预计算：每条知识的 token 集合 + TF 向量
_item_tokens = []       # [{token: tf}, ...]
_item_token_sets = []   # [set(tokens), ...]
_all_tokens = set()     # 全局词汇表
_idf = {}               # {token: idf}
_vectors = []           # 每条知识的 TF-IDF 向量 [{token: tfidf}, ...]

# 对话上下文：记录最近检索到的条目 ID，用于加权
_context_boost = {}     # {item_id: weight}


def _load():
    global _knowledge_items, _loaded
    global _item_tokens, _item_token_sets, _all_tokens, _idf, _vectors
    if _loaded:
        return
    path = os.path.join(os.path.dirname(__file__), "..", "assets", "sakura_knowledge.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            _knowledge_items = data.get("items", [])
    except Exception as e:
        logger.warning(f"知识库加载失败: {e}")
        _loaded = True
        return

    # 预计算所有文档的 token 和 TF
    doc_count = len(_knowledge_items)
    token_docs = defaultdict(int)  # token 出现在多少篇文档中

    for item in _knowledge_items:
        text = item.get("title", "") + " " + item.get("content", "")
        keywords = " ".join(item.get("keywords", []))
        tokens = _tokenize(text + " " + keywords)
        _item_token_sets.append(set(tokens))

        # TF
        tf = defaultdict(float)
        for t in tokens:
            tf[t] += 1
        # 归一化
        max_freq = max(tf.values()) if tf else 1
        for t in tf:
            tf[t] /= max_freq
        _item_tokens.append(dict(tf))

        # 统计文档频率
        for t in set(tokens):
            token_docs[t] += 1
            _all_tokens.add(t)

    # IDF
    _idf = {}
    for token in _all_tokens:
        _idf[token] = math.log((doc_count + 1) / (token_docs[token] + 1)) + 1

    # TF-IDF 向量
    _vectors = []
    for tf in _item_tokens:
        vec = {}
        for token, tf_val in tf.items():
            vec[token] = tf_val * _idf.get(token, 1.0)
        _vectors.append(vec)

    _loaded = True
    logger.info(f"知识库已加载，共 {len(_knowledge_items)} 条")


def _tokenize(text):
    """中文分词"""
    text = text.lower().strip()
    if not text:
        return []
    try:
        import jieba
        jieba.setLogLevel(60)  # 屏蔽 jieba 内部日志
        tokens = jieba.lcut(text)
    except ImportError:
        # 降级：按字符切分
        tokens = list(text)
    # 过滤停用词和短词
    stop_words = {"的", "了", "是", "在", "和", "也", "都", "就", "与", "及",
                  "或", "有", "被", "从", "到", "把", "让", "对", "为", "这",
                  "那", "一个", "一种", "这个", "那个", "不", "而", "且", "但",
                  "着", "过", "之", "其", "它", "他", "她", "们", "我", "你",
                  "会", "能", "要", "可以", "没有", "不是", "什么", "怎么",
                  "哪", "吗", "吧", "呢", "啊", "哦", "嗯", "很", "非常", "都"}
    tokens = [t.strip() for t in tokens
              if len(t.strip()) >= 2 and t.strip() not in stop_words]
    return tokens


def _cosine_similarity(vec_a, vec_b):
    """两个稀疏向量的余弦相似度"""
    if not vec_a or not vec_b:
        return 0.0
    keys = set(vec_a.keys()) & set(vec_b.keys())
    if not keys:
        return 0.0
    dot = sum(vec_a[k] * vec_b[k] for k in keys)
    norm_a = math.sqrt(sum(v ** 2 for v in vec_a.values()))
    norm_b = math.sqrt(sum(v ** 2 for v in vec_b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _query_vector(tokens):
    """将查询 token 列表转为 TF-IDF 向量"""
    if not tokens:
        return {}
    tf = defaultdict(float)
    for t in tokens:
        if t in _all_tokens:
            tf[t] += 1
    if not tf:
        return {}
    max_freq = max(tf.values())
    vec = {}
    for t, f in tf.items():
        vec[t] = (f / max_freq) * _idf.get(t, 1.0)
    return vec


def retrieve(user_input, top_k=3, max_chars=800):
    """
    语义检索相关知识条目

    Args:
        user_input: 用户输入文本
        top_k: 返回前 K 条
        max_chars: 返回上下文总字符数上限

    Returns:
        str: 格式化的知识上下文，嵌入 system prompt
    """
    _load()
    if not _knowledge_items:
        return ""

    query_tokens = _tokenize(user_input)
    if not query_tokens:
        return ""

    q_vec = _query_vector(query_tokens)
    if not q_vec:
        return ""

    # 计算每条知识的得分 = 余弦相似度 + 上下文加成
    scored = []
    for i, vec in enumerate(_vectors):
        sim = _cosine_similarity(q_vec, vec)
        # 上下文加成：最近讨论过的话题 +20%
        item_id = _knowledge_items[i].get("id", "")
        boost = _context_boost.get(item_id, 0.0)
        score = sim * (1.0 + boost)
        if score > 0.005:
            scored.append((score, i))

    scored.sort(key=lambda x: x[0], reverse=True)

    # 取 top_k 条，控制总长度
    selected = []
    total_chars = 0
    for _, idx in scored[:top_k]:
        item = _knowledge_items[idx]
        text = f"【{item['title']}】{item['content']}"
        if total_chars + len(text) > max_chars:
            break
        selected.append(text)
        total_chars += len(text)

    # 更新上下文：本次选中的条目获得加成（衰减旧加成）
    for k in list(_context_boost.keys()):
        _context_boost[k] *= 0.5
        if _context_boost[k] < 0.01:
            del _context_boost[k]
    for _, idx in scored[:top_k]:
        item_id = _knowledge_items[idx].get("id", "")
        _context_boost[item_id] = min(_context_boost.get(item_id, 0) + 0.3, 1.0)

    if selected:
        return "\n".join(selected)
    return ""


def clear_context():
    """清除上下文记忆（切换话题时调用）"""
    global _context_boost
    _context_boost = {}
    logger.debug("知识库上下文已清除")
