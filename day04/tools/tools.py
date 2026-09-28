"""工具定义与实现（沿用第3天：Function Calling）

TOOLS_SCHEMA 告诉模型有哪些工具可用；TOOLS_MAP 供 Agent 实际执行。
以下为课程演示用的模拟数据（订单/产品/物流）。
"""
from typing import Any, Dict

ORDERS: Dict[str, Dict[str, Any]] = {
    "ORD001": {"order_id": "ORD001", "product": "iPhone 15 Pro", "status": "已发货", "amount": 7999, "customer": "张三"},
    "ORD002": {"order_id": "ORD002", "product": "华为 Mate 60", "status": "配送中", "amount": 5499, "customer": "李四"},
    "ORD003": {"order_id": "ORD003", "product": "小米 14", "status": "已完成", "amount": 3999, "customer": "王五"},
}

PRODUCTS: Dict[str, Dict[str, Any]] = {
    "iPhone 15 Pro": {"name": "iPhone 15 Pro", "price": 7999, "stock": 156, "desc": "A17 Pro 芯片，钛金属边框"},
    "华为 Mate 60": {"name": "华为 Mate 60", "price": 5499, "stock": 89, "desc": "麒麟芯片，支持卫星通话"},
    "小米 14": {"name": "小米 14", "price": 3999, "stock": 230, "desc": "骁龙 8Gen3，徕卡影像"},
    "AirPods Pro": {"name": "AirPods Pro", "price": 1899, "stock": 312, "desc": "主动降噪，空间音频"},
}

DELIVERIES: Dict[str, Dict[str, Any]] = {
    "ORD001": {"order_id": "ORD001", "carrier": "顺丰", "tracking": "SF1234567890", "status": "已签收"},
    "ORD002": {"order_id": "ORD002", "carrier": "圆通", "tracking": "YT9876543210", "status": "运输中"},
    "ORD003": {"order_id": "ORD003", "carrier": "中通", "tracking": "ZT1122334455", "status": "已揽收"},
}


def _normalize(text: str) -> str:
    return text.replace(" ", "").replace("　", "").lower()


def query_order(order_id: str) -> Dict[str, Any]:
    """查询订单状态和基本信息"""
    order = ORDERS.get(order_id.strip().upper())
    if not order:
        return {"success": False, "error": f"未找到订单 {order_id}"}
    return {"success": True, **order}


def get_product_info(product_name: str) -> Dict[str, Any]:
    """查询产品价格、库存和参数（忽略空格/大小写）"""
    keyword = _normalize(product_name)
    for name, info in PRODUCTS.items():
        normalized_name = _normalize(name)
        if keyword and (keyword in normalized_name or normalized_name in keyword):
            return {"success": True, **info}
    return {"success": False, "error": f"未找到产品 {product_name}", "available_products": list(PRODUCTS.keys())}


def check_delivery(order_id: str) -> Dict[str, Any]:
    """查询物流信息"""
    delivery = DELIVERIES.get(order_id.strip().upper())
    if not delivery:
        return {"success": False, "error": f"未找到订单 {order_id} 的物流信息"}
    return {"success": True, **delivery}


def transfer_to_human(agent_type: str = "general") -> Dict[str, Any]:
    """转接人工客服"""
    agents = {"general": "普通客服", "technical": "技术支持", "complaint": "投诉专员"}
    return {
        "success": True,
        "message": f"正在为您转接{agents.get(agent_type, '普通客服')}，请稍候...",
        "agent_type": agent_type,
        "queue_position": 1,
    }


TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "query_order",
            "description": "查询订单的状态和基本信息，例如：已发货、配送中、已完成",
            "parameters": {
                "type": "object",
                "properties": {"order_id": {"type": "string", "description": "订单号，例如：ORD001"}},
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_info",
            "description": "查询产品的价格、库存和参数信息",
            "parameters": {
                "type": "object",
                "properties": {"product_name": {"type": "string", "description": "产品名称，例如：iPhone 15 Pro"}},
                "required": ["product_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_delivery",
            "description": "查询订单的物流信息，包括承运商、运单号和物流状态",
            "parameters": {
                "type": "object",
                "properties": {"order_id": {"type": "string", "description": "订单号，例如：ORD001"}},
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "transfer_to_human",
            "description": "当用户要求转人工，或问题超出客服权限时，转接人工客服",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_type": {
                        "type": "string",
                        "description": "客服类型：general（普通）、technical（技术）、complaint（投诉）",
                        "enum": ["general", "technical", "complaint"],
                    }
                },
                "required": ["agent_type"],
            },
        },
    },
]

TOOLS_MAP = {
    "query_order": query_order,
    "get_product_info": get_product_info,
    "check_delivery": check_delivery,
    "transfer_to_human": transfer_to_human,
}
