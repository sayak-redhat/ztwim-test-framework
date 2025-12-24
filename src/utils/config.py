"""Configuration management for ZTWIM Test Framework.

Handles loading settings and setting KUBECONFIG environment variable.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class OpenShiftConfig(BaseModel):
    """OpenShift cluster configuration."""
    kubeconfig: str = ""
    api_url: str = ""
    token: str = ""
    operator_namespace: str = "zero-trust-workload-identity-manager"
    test_namespace_prefix: str = "ztwim-test"
    cleanup_after_tests: bool = True


class ZTWIMConfig(BaseModel):
    """ZTWIM Operator installation configuration."""
    catalog_name: str = "redhat-operators"
    channel: str = "stable-v1"
    cluster_name: str = "test01"
    app_domain: str = ""  # Auto-detected if empty
    jwt_issuer_endpoint: str = ""  # Derived from app_domain if empty


class SpireServerConfig(BaseModel):
    """SpireServer component configuration."""
    replicas: int = 1
    trust_domain: str = "test.spiffe.io"
    image: str = ""
    log_level: str = "DEBUG"


class SpireAgentConfig(BaseModel):
    """SpireAgent component configuration."""
    image: str = ""
    log_level: str = "DEBUG"
    socket_path: str = "/run/spire/agent-sockets/spire-agent.sock"


class OIDCConfig(BaseModel):
    """OIDC Discovery configuration."""
    enabled: bool = True


class SpireConfig(BaseModel):
    """SPIRE components configuration."""
    server: SpireServerConfig = Field(default_factory=SpireServerConfig)
    agent: SpireAgentConfig = Field(default_factory=SpireAgentConfig)
    oidc: OIDCConfig = Field(default_factory=OIDCConfig)


class TestingConfig(BaseModel):
    """Test execution configuration."""
    default_timeout: int = 300
    poll_interval: int = 5
    retry_count: int = 3
    workers: int = 0


class LoggingConfig(BaseModel):
    """Logging configuration."""
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


class Settings(BaseSettings):
    """Main settings class for ZTWIM Test Framework."""
    
    openshift: OpenShiftConfig = Field(default_factory=OpenShiftConfig)
    ztwim: ZTWIMConfig = Field(default_factory=ZTWIMConfig)
    spire: SpireConfig = Field(default_factory=SpireConfig)
    testing: TestingConfig = Field(default_factory=TestingConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    @classmethod
    def from_yaml(cls, yaml_path: Path) -> "Settings":
        """Load settings from YAML file with environment variable expansion."""
        if not yaml_path.exists():
            return cls()
        
        with open(yaml_path) as f:
            content = f.read()
        
        # Expand environment variables in YAML content
        content = os.path.expandvars(content)
        yaml_config = yaml.safe_load(content) or {}
        
        return cls(**yaml_config)


def set_kubeconfig(kubeconfig_path: Optional[str] = None) -> str:
    """
    Set KUBECONFIG environment variable.
    
    Priority:
    1. Explicitly provided path (CLI argument)
    2. Existing KUBECONFIG environment variable
    3. Config file setting
    4. Default ~/.kube/config
    
    Args:
        kubeconfig_path: Path to kubeconfig file (optional)
    
    Returns:
        The kubeconfig path that was set
    
    Raises:
        FileNotFoundError: If specified kubeconfig doesn't exist
    """
    # Priority 1: Explicitly provided path
    if kubeconfig_path:
        path = Path(kubeconfig_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Kubeconfig not found: {path}")
        os.environ["KUBECONFIG"] = str(path)
        return str(path)
    
    # Priority 2: Existing environment variable
    if "KUBECONFIG" in os.environ and os.environ["KUBECONFIG"]:
        path = Path(os.environ["KUBECONFIG"]).expanduser().resolve()
        if path.exists():
            return str(path)
    
    # Priority 3: Load from config file
    settings = get_settings()
    if settings.openshift.kubeconfig:
        path = Path(settings.openshift.kubeconfig).expanduser().resolve()
        if path.exists():
            os.environ["KUBECONFIG"] = str(path)
            return str(path)
    
    # Priority 4: Default location
    default_path = Path.home() / ".kube" / "config"
    if default_path.exists():
        os.environ["KUBECONFIG"] = str(default_path)
        return str(default_path)
    
    raise FileNotFoundError(
        "No kubeconfig found. Please provide via:\n"
        "  1. CLI: --kubeconfig /path/to/kubeconfig\n"
        "  2. ENV: export KUBECONFIG=/path/to/kubeconfig\n"
        "  3. Config: config/settings.yaml -> openshift.kubeconfig"
    )


def get_config_path() -> Path:
    """Get the config file path."""
    # Check for config in multiple locations
    locations = [
        Path.cwd() / "config" / "settings.yaml",
        Path(__file__).parent.parent.parent / "config" / "settings.yaml",
        Path.home() / ".ztwim-test" / "settings.yaml",
    ]
    
    for path in locations:
        if path.exists():
            return path
    
    # Return default location even if it doesn't exist
    return locations[0]


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    config_path = get_config_path()
    return Settings.from_yaml(config_path)


def reload_settings() -> Settings:
    """Reload settings (clears cache)."""
    get_settings.cache_clear()
    return get_settings()
