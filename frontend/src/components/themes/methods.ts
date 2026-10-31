export type Method = 'keyword' | 'tfidf' | 'semantic' | 'bertopic' | 'llm'

export const METHODS: {
  id: Method
  label: string
  icon: string
  description: string
  badge?: string
}[] = [
  {
    id: 'keyword',
    label: 'Keyword Rules',
    icon: '🔑',
    description: 'Fast, deterministic. Matches reviews against predefined motorcycle keyword buckets. No ML, no API. Best for a quick first pass.',
    badge: 'Instant',
  },
  {
    id: 'tfidf',
    label: 'TF-IDF Clustering',
    icon: '📊',
    description: 'Classical ML baseline. TF-IDF vectors + K-Means. Bag-of-words, no semantic understanding.',
    badge: 'classical',
  },
  {
    id: 'semantic',
    label: 'Semantic Clustering',
    icon: '🧬',
    description: 'Embeds each review via local Ollama (nomic-embed-text). Clusters with HDBSCAN, names with c-TF-IDF. Captures semantic similarity that TF-IDF misses.',
    badge: 'Solid',
  },
  {
    id: 'bertopic',
    label: 'BERTopic Pipeline',
    icon: '🚀',
    description: 'Full BERTopic recipe — embeddings + UMAP + HDBSCAN + c-TF-IDF, with optional LLM-based theme name refinement using local Mistral. Best quality.',
    badge: 'Power user',
  },
  {
    id: 'llm',
    label: 'LLM Analysis',
    icon: '🤖',
    description: 'Sends reviews to a language model (Claude or a local Ollama model) for deep qualitative understanding, nuanced sentiment, and richer theme labels.',
    badge: 'AI',
  },
]
