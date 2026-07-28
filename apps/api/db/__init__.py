"""共享数据库层 — API 与 Worker 共用。

导出 Base、Session 工厂和全部模型，保证 Alembic 可收集统一 metadata。
"""
