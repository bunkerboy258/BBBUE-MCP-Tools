import json


class McpBusinessError(RuntimeError):
    """/** 业务失败保留原始结果供调用者检查 */"""

    def __init__(self, value):
        """
        /**
         * @param value	业务失败结果
         * @return 异常实例
         */
        """
        self.value = value
        super().__init__("MCP 业务失败: " + json.dumps(value, ensure_ascii=False))


class McpExecutionError(McpBusinessError):
    """/** 工具提供已核实的业务失败执行证据 */"""

    def __init__(self, state, code, message, details=None):
        """
        /**
         * @param state\t执行前拒绝或部分执行
         * @param code\t固定业务错误码
         * @param message\t客户端可读说明
         * @param details\t实际执行与清理证据
         * @return 可通过官方字符串返回值传输的业务失败
         */
        """
        if state not in {"rejected", "partial"}:
            raise ValueError("执行失败证据需要明确状态")
        super().__init__({"success": False, "code": code, "error": message,
            "execution": {"state": state, "details": details or {}}})


def decode_json_value(value):
    """
    /**
     * @param value	字符串或已经解析的返回值
     * @return JSON 值或原始普通文本
     */
    """
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def require_business_success(value):
    """
    /**
     * 仅检查业务根字段 不把查询结果中的嵌套诊断当作调用失败
     * @param value	原始业务返回值
     * @return 检查后的业务值
     */
    """
    value = decode_json_value(value)
    if isinstance(value, dict) and (value.get("success") is False or value.get("error")):
        raise McpBusinessError(value)
    return value


def decode_tool_result(response):
    """
    /**
     * 解码官方 MCP 返回包装 并检查业务失败
     * @param response	完整协议响应
     * @return 业务返回值或发现接口的普通文本
     */
    """
    result = response["result"]
    value = result.get("structuredContent")
    if value is None:
        texts = [item["text"] for item in result.get("content", []) if item.get("type") == "text"]
        if len(texts) != 1:
            return result
        value = decode_json_value(texts[0])
    if isinstance(value, dict) and "returnValue" in value:
        value = value["returnValue"]
    return require_business_success(value)
