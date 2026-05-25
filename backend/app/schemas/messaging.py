from pydantic import BaseModel, field_validator


class ChatMessageCreate(BaseModel):
    channel: str
    content: str

    @field_validator("content")
    @classmethod
    def validate_content(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("Message cannot be empty")
        return v[:500]

    @field_validator("channel")
    @classmethod
    def validate_channel(cls, v):
        if len(v) > 64:
            raise ValueError("Invalid channel")
        return v


class ChatMessageResponse(BaseModel):
    id: int
    channel: str
    sender_nation_id: int
    sender_nation_name: str
    content: str
    created_at: str

    model_config = {"from_attributes": True}


class DmChannelInfo(BaseModel):
    channel: str
    other_nation_id: int
    other_nation_name: str


class MailSendRequest(BaseModel):
    recipient_nation_id: int
    subject: str
    body: str

    @field_validator("subject")
    @classmethod
    def validate_subject(cls, v):
        v = v.strip()
        if not v or len(v) > 256:
            raise ValueError("Subject must be 1-256 characters")
        return v

    @field_validator("body")
    @classmethod
    def validate_body(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("Body cannot be empty")
        return v[:10000]


class MailSummaryResponse(BaseModel):
    id: int
    sender_nation_id: int
    sender_nation_name: str
    recipient_nation_id: int
    recipient_nation_name: str
    subject: str
    read: bool
    sent_at: str


class MailDetailResponse(BaseModel):
    id: int
    sender_nation_id: int
    sender_nation_name: str
    recipient_nation_id: int
    recipient_nation_name: str
    subject: str
    body: str
    read: bool
    sent_at: str


class UnreadCountResponse(BaseModel):
    count: int


class NationListItem(BaseModel):
    id: int
    name: str
    flag_color: str

    model_config = {"from_attributes": True}
