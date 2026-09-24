from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache
from typing import List


class Settings(BaseSettings):
    app_name: str = "Facturacion ICA SNRI"
    environment: str = "development"
    debug: bool = True

    upload_dir: str = "/app/uploads"
    max_file_size: int = 10 * 1024 * 1024
    allowed_mimes: List[str] = ["image/png", "image/jpeg", "application/pdf"]

    tesseract_cmd: str = "tesseract"
    tesseract_lang: str = "spa"
    ocr_dpi: int = 300

    llm_provider: str = "ollama"
    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "llama3.2:3b"
    openrouter_api_key: str = Field(default="", exclude=True)
    openrouter_model: str = "mistralai/mistral-7b-instruct"

    snri_wsdl_url: str = "http://webservices.ica.gov.co/WS_FACTURACION/?WSDL"
    snri_wsdl_local_path: str = "./wsdl/WS_FACTURACION.wsdl"
    snri_cert_path: str = Field(default="", exclude=True)
    snri_cert_password: str = Field(default="", exclude=True)
    snri_timeout: int = 30
    snri_demo_mode: bool = False
    snri_id_proyecto: int = 0
    snri_username: str = Field(default="", exclude=True)
    snri_password: str = Field(default="", exclude=True)
    snri_ip: str = Field(default="", exclude=True)
    snri_proceso: str = Field(default="", exclude=True)

    dian_wsdl_url: str = "https://vpfe-hab.dian.gov.co/WcfDianCustomerServices.svc?wsdl"

    sigma_api_url: str = "http://sigma.local/api"
    sigma_api_token: str = Field(default="", exclude=True)

    database_url: str = "postgresql+asyncpg://postgres:postgres@db:5432/facturacion"
    redis_url: str = "redis://redis:6379/0"

    app_secret_key: str = Field(default="", exclude=True)
    access_token_expire_minutes: int = 30
    rate_limit_per_minute: int = 60
    auth_enabled: bool = False

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache
def get_settings() -> Settings:
    return Settings()