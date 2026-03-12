from pydantic import BaseModel, EmailStr

class UserProfileResponse(BaseModel):
    user_id: str
    username: str
    email: EmailStr | None = None

    display_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    profile_image_url: str | None = None

class UserProfileUpdateRequest(BaseModel):
    display_name: str
    first_name: str
    last_name: str
    phone: str