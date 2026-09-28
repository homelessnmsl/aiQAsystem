"""统一响应封装（FR-OPS-01；架构 4.3-3）

路由层只返回 ApiResponse.ok(data) / 抛 BizError，禁止手写 {"code": ...} 字面量。
"""
from typing import Any, Dict, Optional


class ApiResponse:
    """统一响应体 {"code", "message", "data"}（接口文档 1.2）"""

    @staticmethod
    def ok(data: Any = None, message: str = "success") -> Dict[str, Any]:
        """成功响应：code=0（HTTP 一律 200）"""
        return {"code": 0, "message": message, "data": data}

    @staticmethod
    def fail(code: int, message: str, data: Optional[Any] = None) -> Dict[str, Any]:
        """失败响应：code 取接口文档 1.4 错误码总表"""
        return {"code": code, "message": message, "data": data}
