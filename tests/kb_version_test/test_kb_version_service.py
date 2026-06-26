# -*- coding: utf-8 -*-
# @FileName : test_kb_version_service.py
# @Author   : SunJh
# @Time     : 2026/06/23 22:13
# @Todo     : 测试知识库版本管理的服务

from app.db.mysql import SessionLocal
from app.kb_version.schemas import KbVersionCreate, KbVersionOperation
from app.kb_version.service import KbVersionService

db = SessionLocal()

try:
    service = KbVersionService(db)

    # 1. 创建版本 1
    v1 = service.create_version(
        KbVersionCreate(description="测试版本 1"),
        operator_id="test_user",
    )
    db.commit()
    print("创建 v1:", v1.model_dump())

    # 2. 发布版本 1
    v1_pub = service.publish(
        v1.kb_version,
        operator_id="test_user",
        message="发布 v1",
    )
    db.commit()
    print("发布 v1:", v1_pub.model_dump())

    # 3. 创建版本 2
    v2 = service.create_version(
        KbVersionCreate(description="测试版本 2"),
        operator_id="test_user",
    )
    db.commit()
    print("创建 v2:", v2.model_dump())

    # 4. 发布版本 2
    v2_pub = service.publish(
        v2.kb_version,
        operator_id="test_user",
        message="发布 v2",
    )
    db.commit()
    print("发布 v2:", v2_pub.model_dump())

    # 5. 查看列表
    versions = service.list_versions()
    print("版本列表:", versions.model_dump())

    # 6. 快速回滚
    rollback = service.rollback(
        operator_id="test_user",
        message="快速回滚",
    )
    db.commit()
    print("快速回滚:", rollback.model_dump())

    # 7. 查看日志
    logs = service.list_action_logs(limit=10)
    print("操作日志:", [item.model_dump() for item in logs])

finally:
    db.close()