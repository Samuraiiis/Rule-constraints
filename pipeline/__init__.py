"""脑部 MRI 医学文献知识抽取系统 — 流水线包。

子模块：
    id_generator      确定性内容哈希 ID 生成（D-1）
    state_manager     文档级状态机 + 检查点 + 错误码（§16/§17/§18）
    single_doc_runner 单文档完整流水线编排（D-2 三阶段抽取 + 校验 + 落盘）
"""
