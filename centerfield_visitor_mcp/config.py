from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    centerfield_base_url: str = "https://www.centerfield.co.kr"
    # Deployment-specific values — MUST be provided via environment variables
    # (CF_COMPANY_NAME, CF_PERSON_IN_CHARGE_MOBILE). No defaults are shipped.
    company_name: str = ""
    person_in_charge_mobile: str = ""
    building: str = "east"
    building_key: str = "East"
    # Default floor applied when a visitor record/tool call omits `floor` ("12" or "18").
    default_floor: str = "12"
    request_timeout: int = 30
    bulk_max_visitors: int = 200
    request_delay: float = 0.5

    class Config:
        env_file = ".env"
        env_prefix = "CF_"


settings = Settings()
