"""
Azure Authentication Configuration Helper

This module provides utilities to configure Azure authentication for different environments.
"""

import os
from typing import Dict, Optional

def setup_environment_credentials(
    tenant_id: str,
    client_id: str, 
    client_secret: str
) -> None:
    """
    Set up environment variables for Azure authentication.
    
    Args:
        tenant_id: Azure AD tenant ID
        client_id: Azure AD client ID (service principal ID)
        client_secret: Azure AD client secret
    """
    os.environ["AZURE_TENANT_ID"] = tenant_id
    os.environ["AZURE_CLIENT_ID"] = client_id
    os.environ["AZURE_CLIENT_SECRET"] = client_secret

def setup_managed_identity_credentials(
    client_id: Optional[str] = None
) -> None:
    """
    Set up environment for managed identity authentication.
    
    Args:
        client_id: Optional client ID for user-assigned managed identity
    """
    if client_id:
        os.environ["AZURE_CLIENT_ID"] = client_id
    
    # Clear any service principal credentials
    for env_var in ["AZURE_CLIENT_SECRET", "AZURE_TENANT_ID"]:
        if env_var in os.environ:
            del os.environ[env_var]

def get_auth_config() -> Dict[str, str]:
    """
    Get current authentication configuration.
    
    Returns:
        Dictionary with current authentication settings
    """
    config = {}
    
    # Check for environment variables
    env_vars = [
        "AZURE_TENANT_ID",
        "AZURE_CLIENT_ID", 
        "AZURE_CLIENT_SECRET",
        "AZURE_SUBSCRIPTION_ID"
    ]
    
    for var in env_vars:
        if var in os.environ:
            config[var] = os.environ[var]
        else:
            config[var] = "Not set"
    
    return config

def print_auth_status() -> None:
    """Print current authentication configuration status."""
    config = get_auth_config()
    
    print("Azure Authentication Configuration:")
    print("=" * 40)
    
    for key, value in config.items():
        if "SECRET" in key and value != "Not set":
            print(f"{key}: {'*' * 8} (hidden)")
        else:
            print(f"{key}: {value}")
    
    print("\nAuthentication Methods Available:")
    print("-" * 30)
    
    # Check for different auth methods
    if all(config[key] != "Not set" for key in ["AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET"]):
        print("✓ Service Principal (Environment Variables)")
    else:
        print("✗ Service Principal (Environment Variables)")
    
    if config["AZURE_CLIENT_ID"] != "Not set" and config["AZURE_CLIENT_SECRET"] == "Not set":
        print("✓ Managed Identity")
    else:
        print("✗ Managed Identity")
    
    # Check for Azure CLI
    try:
        import subprocess
        result = subprocess.run(["az", "account", "show"], capture_output=True, text=True)
        if result.returncode == 0:
            print("✓ Azure CLI")
        else:
            print("✗ Azure CLI")
    except FileNotFoundError:
        print("✗ Azure CLI (not installed)")

if __name__ == "__main__":
    print_auth_status() 