"""Lazy singleton getters cho các service nặng (tránh block import)."""

_chat_svc = None
_indexing_svc = None


def get_chat_service():
    global _chat_svc
    if _chat_svc is None:
        from app.services.chat_service import ChatService
        _chat_svc = ChatService()
    return _chat_svc


def get_indexing_service():
    global _indexing_svc
    if _indexing_svc is None:
        from app.services.indexing_service import IndexingService
        _indexing_svc = IndexingService()
    return _indexing_svc
