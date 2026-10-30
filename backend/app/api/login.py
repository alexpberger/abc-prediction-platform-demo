"""Login HTTP route. Authentication is not implemented."""

from fastapi import APIRouter

from app.login_mock import temporary_mock_login
from app.schemas.login import LoginRequest, LoginResponse

router = APIRouter()


@router.post("/login", response_model=LoginResponse)
def login(_body: LoginRequest) -> LoginResponse:
    """Accept a login form and return the temporary mock result.

    The password is validated only as a non-empty input. It is not checked,
    stored, or returned.
    """
    return LoginResponse.model_validate(temporary_mock_login())
