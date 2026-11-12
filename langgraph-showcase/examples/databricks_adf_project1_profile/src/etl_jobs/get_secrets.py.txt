import os
import logging
from typing import List, Optional
from azure.identity import (
    DefaultAzureCredential, 
    ManagedIdentityCredential, 
    ClientSecretCredential,
    EnvironmentCredential,
    AzureCliCredential
)
from azure.keyvault.secrets import SecretClient
from azure.core.exceptions import ClientAuthenticationError

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
key_vault_name = "omvmcnp1kvtradinge2edev"
client_id = "3073c9b4-9ae5-4689-a9fc-983e06c4366b"
key_vault_url = f"https://{key_vault_name}.vault.azure.net"

def get_credential() -> Optional[object]:
    """
    Try different authentication methods in order of preference.
    Returns the first working credential or None if all fail.
    """
    authentication_methods = [
        ("Environment Variables", lambda: EnvironmentCredential()),
        ("Managed Identity", lambda: ManagedIdentityCredential(client_id=client_id)),
        ("Azure CLI", lambda: AzureCliCredential()),
        ("Default Azure Credential", lambda: DefaultAzureCredential(managed_identity_client_id=client_id))
    ]
    
    for method_name, credential_func in authentication_methods:
        try:
            logger.info(f"Trying authentication method: {method_name}")
            credential = credential_func()
            
            # Test the credential by trying to get a token
            token = credential.get_token("https://vault.azure.net/.default")
            logger.info(f"Successfully authenticated using: {method_name}")
            return credential
            
        except Exception as e:
            logger.warning(f"Authentication method {method_name} failed: {str(e)}")
            continue
    
    logger.error("All authentication methods failed")
    return None

def get_secret_from_keyvault(secret_name: str) -> Optional[str]:
    """
    Retrieve a secret from Azure Key Vault using the best available authentication method.
    
    Args:
        secret_name: Name of the secret to retrieve
        
    Returns:
        The secret value or None if retrieval failed
    """
    try:
        # Get credential
        credential = get_credential()
        if not credential:
            logger.error("No valid authentication method found")
            return None
        
        # Create Secret Client
        client = SecretClient(vault_url=key_vault_url, credential=credential)
        
        # Get secret
        logger.info(f"Retrieving secret: {secret_name}")
        secret_value = client.get_secret(secret_name)
        
        logger.info(f"Successfully retrieved secret: {secret_name}")
        return secret_value.value
        
    except ClientAuthenticationError as e:
        logger.error(f"Authentication error: {e}")
        return None
    except Exception as e:
        logger.error(f"Error retrieving secret {secret_name}: {e}")
        return None

def main():
    """Main function to demonstrate secret retrieval."""
    secret_name = "EVENT-GRID-ACCESS-KEY"
    
    # Try to get the secret
    secret_value = get_secret_from_keyvault(secret_name)
    
    if secret_value:
        print(f"Secret '{secret_name}' retrieved successfully")
        print(f"Value: {secret_value[:10]}..." if len(secret_value) > 10 else f"Value: {secret_value}")
    else:
        print(f"Failed to retrieve secret '{secret_name}'")
        
        # Provide troubleshooting information
        print("\nTroubleshooting steps:")
        print("1. Ensure you're running in an environment with proper Azure authentication")
        print("2. Check if you're logged in with Azure CLI: az login")
        print("3. Verify environment variables are set (AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID)")
        print("4. Ensure the managed identity has access to the Key Vault")
        print("5. Check Key Vault access policies")

if __name__ == "__main__":
    main()