from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """集中读取并校验环境变量。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("LLM_API_KEY", "API_KEY"),
    )
    base_url: str = Field(
        default="https://api.openai.com/v1",
        validation_alias=AliasChoices("LLM_BASE_URL", "BASE_URL"),
    )
    model_name: str = Field(
        default="gpt-4o-mini",
        validation_alias=AliasChoices("LLM_MODEL", "MODEL_NAME"),
    )
    llm_temperature: float = Field(default=0.0, ge=0, le=2)
    llm_timeout_seconds: float = Field(default=60.0, gt=0)
    llm_max_retries: int = Field(default=2, ge=0, le=5)
    llm_max_output_tokens: int = Field(default=4_096, ge=256, le=32_768)

    search_provider: Literal["mock", "tavily"] = "mock"
    search_api_key: SecretStr = SecretStr("")
    search_api_url: str = "https://api.tavily.com/search"
    search_results_limit: int = Field(default=5, ge=1, le=10)
    max_pages_per_step: int = Field(default=3, ge=1, le=5)
    search_include_raw_content: bool = True
    search_include_domains: str = ""
    search_exclude_domains: str = ""

    max_research_retries: int = Field(default=3, ge=1, le=10)
    max_research_loops: int = Field(default=8, ge=1, le=20)
    max_concurrent_research: int = Field(default=2, ge=1, le=20)
    research_timeout_seconds: float = Field(default=300.0, gt=0, le=3_600)
    research_task_token_limit: int = Field(default=200_000, ge=1_000)
    webpage_timeout_seconds: float = Field(default=15.0, gt=0, le=60)
    webpage_max_chars: int = Field(default=12_000, ge=1_000, le=50_000)

    @staticmethod
    def _split_domains(value: str) -> list[str]:
        """把逗号分隔的域名配置转换为 Tavily 参数。"""

        return [domain.strip() for domain in value.split(",") if domain.strip()]

    @property
    def included_search_domains(self) -> list[str]:
        return self._split_domains(self.search_include_domains)

    @property
    def excluded_search_domains(self) -> list[str]:
        return self._split_domains(self.search_exclude_domains)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """返回进程内复用的配置对象。"""

    return Settings()
