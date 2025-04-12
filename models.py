from typing import List, Optional

from pydantic import BaseModel, Field, HttpUrl


class CustomFieldOption(BaseModel):
    """
    использована рекурсивная типизация, так как поле child может содержать такой же объект.
    """
    self: HttpUrl
    value: str
    id: str
    disabled: bool
    child: Optional['CustomFieldOption'] = None


class AvatarUrls(BaseModel):
    """
    Используются алиасы, чтобы преобразовать ключи с размерами в более понятные имена.
    """
    small: HttpUrl = Field(alias="24x24")
    xsmall: HttpUrl = Field(alias="16x16")
    medium: HttpUrl = Field(alias="32x32")
    large: HttpUrl = Field(alias="48x48")


class User(BaseModel):
    self: HttpUrl
    name: str
    key: str
    emailAddress: str
    avatarUrls: AvatarUrls
    displayName: str
    active: bool
    timeZone: str


class StatusCategory(BaseModel):
    self: HttpUrl
    id: int
    key: str
    colorName: str
    name: str


class Status(BaseModel):
    self: HttpUrl
    description: str
    iconUrl: HttpUrl
    name: str
    id: str
    statusCategory: StatusCategory


class IssueType(BaseModel):
    self: HttpUrl
    id: str
    description: str
    iconUrl: HttpUrl
    name: str
    subtask: bool
    avatarId: Optional[int] = None


class TimeInfo(BaseModel):
    iso8601: str
    jira: str
    friendly: str
    epochMillis: int


class Duration(BaseModel):
    millis: int
    friendly: str


class SLACycle(BaseModel):
    startTime: TimeInfo
    stopTime: Optional[TimeInfo] = None
    breachTime: Optional[TimeInfo] = None
    breached: bool
    paused: Optional[bool] = None
    withinCalendarHours: Optional[bool] = None
    goalDuration: Duration
    elapsedTime: Duration
    remainingTime: Duration


class SLALinks(BaseModel):
    self: HttpUrl


class SLA(BaseModel):
    """
    Для модели добавлены поля как для завершенных циклов, так и для текущего цикла.
    """
    id: str
    name: str
    _links: SLALinks
    completedCycles: List[SLACycle]
    ongoingCycle: Optional[SLACycle] = None


class Fields(BaseModel):
    customfield_20672: Optional[CustomFieldOption] = None
    assignee: Optional[User] = None
    status: Status
    creator: User
    issuetype: IssueType
    customfield_12671: Optional[SLA] = None
    description: Optional[str] = None
    customfield_12670: Optional[SLA] = None
    summary: str
    environment: Optional[str] = None
    duedate: Optional[str] = None
    # Здесь можно добавить другие поля при необходимости


class JiraIssue(BaseModel):
    expand: str
    id: str
    self: HttpUrl
    key: str
    fields: Fields


class JiraIssueList(BaseModel):
    issues: List[JiraIssue]


if __name__ == "__main__":
    pass
