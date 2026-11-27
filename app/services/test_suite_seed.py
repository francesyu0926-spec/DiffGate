"""用例集目录默认种子数据。"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import TestSuite

DEFAULT_TEST_SUITES: list[dict[str, str]] = [
    {
        "slug": "order-service-cases",
        "name": "Order Service Cases",
        "description": "订单域 API 回归用例集",
    },
    {
        "slug": "cart-service-cases",
        "name": "Cart Service Cases",
        "description": "购物车域 API 回归用例集",
    },
    {
        "slug": "user-api-cases",
        "name": "User API Cases",
        "description": "用户中心 API 回归用例集",
    },
    {
        "slug": "payment-gateway-cases",
        "name": "Payment Gateway Cases",
        "description": "支付网关 API 回归用例集",
    },
]


def seed_default_test_suites(db: Session) -> None:
    n = db.scalar(select(func.count()).select_from(TestSuite)) or 0
    if n:
        return
    for row in DEFAULT_TEST_SUITES:
        db.add(
            TestSuite(
                id=str(uuid.uuid4()),
                slug=row["slug"],
                name=row["name"],
                description=row.get("description"),
                enabled=True,
            )
        )
    db.commit()