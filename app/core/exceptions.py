class ResearchAgentError(Exception):
    """项目内可预期异常的基类。"""


class ConfigurationError(ResearchAgentError):
    """配置缺失或无效。"""


class LLMServiceError(ResearchAgentError):
    """模型请求或模型输出解析失败。"""


class LLMContentFilterError(LLMServiceError):
    """模型供应商拒绝了包含高风险内容的请求。"""


class ResearchTimeoutError(ResearchAgentError):
    """研究任务超过允许的总执行时间。"""


class ToolError(ResearchAgentError):
    """工具执行失败。"""


class SearchError(ToolError):
    """搜索服务调用失败。"""


class WebPageReadError(ToolError):
    """网页读取失败。"""


class CalculationError(ToolError):
    """算术表达式不安全或无法计算。"""
