import logging
from pathlib import Path
from typing import Optional

from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)

env_path = Path(__file__).parent / ".env"
logger.debug(f"Loading .env from: {env_path}")
logger.debug(f"File exists: {env_path.exists()}")



class JiraSettings(BaseSettings):
    username: str = Field(..., env='USERNAME', alias='JIRA_USERNAME')
    password: str = Field(..., env='PASSWORD', alias='JIRA_PASSWORD')
    url: str = Field(..., env='URL', alias='JIRA_URL')
    search_string: str = '(("EXT System / Service" in ("Система Внутренних Списков", Anti-Fraud, Collection, "Collection CA", "Credit Scoring", "Data Verification", "Система принятия решений", "Автоматизированная cистема управления операционными рисками", "Система управления лимитами", "Система противодействия внутреннему мошенничеству", "Система противодействия мошенничеству", "Автоматизированная cистема управления операционными рисками", "Автоматизированная система управления операционными рисками") OR "EXT System / Service" in ("Anti Money Laundering") AND project in ("ROSBANK Support", "Почта Банк Support", "МТС Банк Support", "Банк Открытие Support") OR project in ("RTDM Support") AND labels = support) AND status not in (Closed, Resolved) AND (labels != nomon OR labels is EMPTY)) and (status = "open" or assignee is EMPTY)'
    model_config = SettingsConfigDict(env_file=env_path, extra="ignore")


class TelegramSettings(BaseSettings):
    """Telegram bot settings"""
    telegram_bot_token: str = Field(..., env="TELEGRAM_BOT_TOKEN")
    telegram_admin_chat_id: Optional[int] = Field(None, env="TELEGRAM_ADMIN_CHAT_ID")
    telegram_default_reminder_period: int = Field(30, env='TELEGRAM_DEFAULT_REMINDER_PERIOD')

    model_config = SettingsConfigDict(env_file=env_path, extra="allow")


class Settings(BaseSettings):
    """Main settings class that combines all other settings"""

    # database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    jira: JiraSettings = Field(default_factory=JiraSettings)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    model_config = SettingsConfigDict(env_file=env_path, extra='ignore')


# Create a global settings instance
settings = Settings()
logger.debug(f"Settings loaded: {settings}")
